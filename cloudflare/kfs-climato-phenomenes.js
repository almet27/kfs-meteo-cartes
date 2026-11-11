/* KFS MÉTÉO — occurrences historiques d'orages et de neige.
   Archives quotidiennes Météo-France "autres-parametres" (ORAG, NEIG,
   SOLNEIGE, HNEIGEF, NEIGETOTX/06). Zéro uniquement si observé.
   Ne modifie aucune commande Discord hors /climato.
*/
const KFS_P_FIELDS=["ORAG","NEIG","SOLNEIGE","HNEIGEF","NEIGETOTX","NEIGETOT06"];
function kfsPValid(raw,quality) {
  const n=kfsQNumber(raw),q=kfsQNumber(quality);
  // Q=9 : premier niveau de contrôle climatologique passé (donnée filtrée).
  // Exclure les codes douteux comme Q=2 ; Q=0 et Q=1 restent admis.
  if(n===null||(q!==null&&!([0,1,9].includes(q))))return null;
  return n;
}
async function kfsPArchive(stations,year) {
  const ids=stations.map(s=>s.id).sort(),dept=/^(97|98)/.test(ids[0])?ids[0].slice(0,3):ids[0].slice(0,2);
  const filename=kfsQFilename(ids[0],year).replace("_RR-T-Vent.csv.gz","_autres-parametres.csv.gz");
  const cacheKey=new Request("https://kfs-meteo-ia.alain-leprevost.workers.dev/_cache_climato_pheno/v2/"+dept+"/"+year+"/"+ids.join("."));
  try{
    const cached=await caches.default.match(cacheKey);
    if(cached){
      const data=await cached.json();
      if(data?.filename===filename&&data.byStation)return data;
    }
  }catch(_){}
  const url=KFS_Q_BASE+filename;
  const res=await fetch(url,{cf:{cacheEverything:true,cacheTtl:year>=2025?21600:172800}});
  if(!res.ok||!res.body)throw Error("Archive phénomènes indisponible ("+filename+" : HTTP "+res.status+").");
  const result={filename,byStation:Object.fromEntries(ids.map(id=>[id,[]]))};
  const wanted=new Set(ids);
  const reader=res.body.pipeThrough(new DecompressionStream("gzip")).getReader();
  const decoder=new TextDecoder();
  let pending="",header=null,positions=null,lines=0;
  function process(line){
    if(!line)return;
    if(header===null){
      header=line.replace(/^\uFEFF/,"").split(";").map(x=>x.trim().toUpperCase());
      if(!header.includes("NUM_POSTE")||!header.includes("AAAAMMJJ"))throw Error("Colonnes de l'archive phénomènes non reconnues.");
      positions={poste:header.indexOf("NUM_POSTE"),date:header.indexOf("AAAAMMJJ"),
        fields:Object.fromEntries(KFS_P_FIELDS.map(key=>[key,[header.indexOf(key),header.indexOf("Q"+key)]]))};
      return;
    }
    const id=line.slice(0,8);
    if(!wanted.has(id)||line.charAt(8)!==";")return;
    const cols=line.split(";");
    if(cols[positions.poste]!==id)return;
    const date=kfsQDate(cols[positions.date]);
    if(!date||Number(date.slice(0,4))!==year)return;
    const get=key=>{
      const [p,q]=positions.fields[key];
      return p<0?null:kfsPValid(cols[p],q<0?null:cols[q]);
    };
    result.byStation[id].push({date,orage:get("ORAG"),neige:get("NEIG"),
      neigeSol:get("SOLNEIGE"),neigeFraiche:get("HNEIGEF"),
      neigeEpaisseur:get("NEIGETOTX")??get("NEIGETOT06")});
  }
  try {
    for(;;){
      const {value,done}=await reader.read();
      if(done)break;
      pending+=decoder.decode(value,{stream:true});
      let end;
      while((end=pending.indexOf("\n"))!==-1){
        process(pending.slice(0,end).replace(/\r$/,""));
        pending=pending.slice(end+1);
        if(++lines>25000000)throw Error("Archive phénomènes anormalement volumineuse.");
      }
      if(pending.length>2000000)throw Error("Ligne d'archive phénomènes trop longue.");
    }
    pending+=decoder.decode();
    if(pending)process(pending.replace(/\r$/,""));
  } finally {
    try{await reader.cancel();}catch(_){}
  }
  for(const id of ids){
    const unique=new Map(result.byStation[id].map(d=>[d.date,d]));
    result.byStation[id]=[...unique.values()].sort((a,b)=>a.date.localeCompare(b.date));
  }
  try{
    await caches.default.put(cacheKey,new Response(JSON.stringify(result),{
      headers:{"content-type":"application/json","Cache-Control":"public,max-age="+(year>=2025?21600:172800)}
    }));
  }catch(e){console.warn("KFS_PHENO_CACHE",String(e).slice(0,100));}
  return result;
}
function kfsPStats(days,field) {
  // Indicateurs d'occurrence binaires : ne pas traiter une valeur inconnue comme un zéro.
  const occurrence=["orage","neige","neigeSol"].includes(field);
  const observed=days.filter(d=>occurrence?(d[field]===0||d[field]===1):(d[field]!==null&&Number.isFinite(d[field])));
  return {valid:observed.length,jours:observed.filter(d=>d[field]===1).length,
    dates:observed.filter(d=>d[field]===1).map(d=>d.date)};
}
function kfsPExpectedDays(year,month) {
  const today=new Date();
  const endOfObservations=new Date(Date.UTC(today.getUTCFullYear(),today.getUTCMonth(),today.getUTCDate()-1));
  const start=new Date(Date.UTC(year,month?month-1:0,1));
  const end=new Date(Date.UTC(year,month||12,0));
  const effectiveEnd=new Date(Math.min(end.getTime(),endOfObservations.getTime()));
  return Math.max(0,Math.round((effectiveEnd.getTime()-start.getTime())/86400000)+1);
}
async function kfsPSelect(city,year,month,rubrique) {
  const expected=kfsPExpectedDays(year,month);
  if(!expected)throw Error("Cette période n'a pas encore commencé : aucune observation possible.");
  const all=(await kfsClimStations()).map(s=>({...s,km:kfsClimDistance(city.lat,city.lon,s.lat,s.lon)}))
    // Une station lointaine ne doit pas être présentée comme le climat de la commune.
    .filter(s=>s.km<=80).sort((a,b)=>a.km-b.km).slice(0,24);
  const groups=new Map();
  for(const s of all){
    const dep=/^(97|98)/.test(s.id)?s.id.slice(0,3):s.id.slice(0,2);
    if(!groups.has(dep))groups.set(dep,[]);
    groups.get(dep).push(s);
  }
  const choices=[],errors=[];
  for(const group of [...groups.values()].slice(0,3)) {
    try{
      const data=await kfsPArchive(group,year);
      for(const station of group){
        const days=(data.byStation[station.id]||[]).filter(d=>!month||Number(d.date.slice(5,7))===month);
        const valid=kfsPStats(days,rubrique==="orages"?"orage":"neige").valid;
        if(valid)choices.push({station,days,filename:data.filename,valid});
      }
    }catch(e){errors.push(String(e?.message||e));}
  }
  if(!choices.length)throw Error("Aucune station à moins de 80 km ne publie des relevés d'"+
    (rubrique==="orages"?"orage":"occurrence de neige")+" pour cette période."+
    (errors.length?" "+errors[0]:"")+" Les absences ne valent pas zéro.");
  const complete=choices.filter(x=>x.valid>=Math.ceil(expected*.85));
  if(!complete.length) {
    const top=choices.sort((a,b)=>b.valid-a.valid)[0];
    throw Error("Couverture insuffisante pour un bilan fiable : au mieux "+top.valid+" jours observés sur "+
      expected+" attendus ("+top.station.name+"). Aucun total trompeur n'est affiché.");
  }
  complete.sort((a,b)=>a.station.km-b.station.km||b.valid-a.valid);
  return {...complete[0],expected};
}

/* KFS_CLIMATO_NEIGE_LOCALE_V1 : profondeur neige dans la commune via
   ERA5-Land si aucune station locale complète. Deux sources affichées séparément.
   ERA5-Land = réanalyse approximative, jamais une observation in situ.
*/
async function kfsPLocalSnowArchive(city,year){
  if(year<1950)throw Error("La réanalyse ERA5-Land de l'enneigement est disponible à partir de 1950.");
  const start=year+"-01-01",nowYear=new Date().getUTCFullYear();
  const end=year===nowYear?new Date(Date.now()-7*86400000).toISOString().slice(0,10):year+"-12-31";
  if(end<start)throw Error("Pas encore d'archives ERA5-Land pour l'année en cours.");
  const lat=Number(city.lat.toFixed(3)),lon=Number(city.lon.toFixed(3));
  const base="https://kfs-meteo-ia.alain-leprevost.workers.dev";
  const key=new Request(base+"/_clim_neige_local_v2/"+year+"/"+lat+"/"+lon);
  const oldKey=new Request(base+"/_clim_neige_local_v1/"+year+"/"+lat+"/"+lon);
  // Ne jamais refaire une requête si une copie valide est déjà en cache.
  for(const cacheKey of [key,oldKey]){
    try{
      const res=await caches.default.match(cacheKey);
      if(res){
        const data=await res.json();
        if(data?.year===year&&Array.isArray(data.depth)&&Array.isArray(data.fall))return data;
      }
    }catch(_){}
  }
  // Une seule requête pour deux paramètres : l'ancien code faisait un second
  // appel ECMWF IFS dont les HTTP 429 bloquaient tout le bulletin.
  const endpoint="https://archive-api.open-meteo.com/v1/archive?"+
    new URLSearchParams({latitude:String(lat),longitude:String(lon),start_date:start,end_date:end,
      hourly:"snow_depth,snowfall",models:"era5_land",timezone:"Europe/Paris"}).toString();
  const r=await fetch(endpoint,{cf:{cacheEverything:true,cacheTtl:year===nowYear?21600:604800}});
  if(!r.ok){
    if(r.status===429)throw Error("L'API historique Open-Meteo est temporairement limitée (HTTP 429). "+
      "Les estimations ne peuvent pas être actualisées maintenant ; aucune valeur n'est inventée.");
    throw Error("Archive ERA5-Land indisponible : HTTP "+r.status);
  }
  const j=await r.json();
  if(j.error||!Array.isArray(j.hourly?.time)||!Array.isArray(j.hourly?.snow_depth)||
    !Array.isArray(j.hourly?.snowfall)||
    j.hourly_units?.snow_depth!=="m"||j.hourly_units?.snowfall!=="cm")
    throw Error("L'archive ERA5-Land ne renvoie pas les deux séries et unités attendues.");
  function aggregate(key,mode){
    const days=new Map();
    const times=j.hourly.time,values=j.hourly[key];
    for(let i=0;i<times.length;i++){
      const val=values[i],date=String(times[i]||"").slice(0,10);
      if(val===null||!Number.isFinite(Number(val))||!/^\d{4}-\d{2}-\d{2}$/.test(date))continue;
      const x=Math.max(0,Number(val))*(key==="snow_depth"?100:1);
      const entry=days.get(date)||{date,value:mode==="sum"?0:null,samples:0};
      entry.samples++;
      entry.value=mode==="sum"?entry.value+x:entry.value===null?x:Math.max(entry.value,x);
      days.set(date,entry);
    }
    return [...days.values()].sort((a,b)=>a.date.localeCompare(b.date));
  }
  const result={year,sourceFall:"era5_land",depth:aggregate("snow_depth","max"),
    fall:aggregate("snowfall","sum"),depthLat:j.latitude,depthLon:j.longitude};
  if(result.depth.length<100&&year!==nowYear)throw Error("Historique d'épaisseur de neige trop incomplet.");
  try{
    await caches.default.put(key,new Response(JSON.stringify(result),{
      headers:{"content-type":"application/json","Cache-Control":"public,max-age="+(year===nowYear?21600:2592000)}
    }));
  }catch(e){console.warn("KFS_NEIGE_CACHE",String(e).slice(0,100));}
  return result;
}

async function kfsPLocalSnowObservations(city,year,month){
  // Ne jamais présenter une station à 60 km comme une mesure locale d'enneigement.
  const all=(await kfsClimStations()).map(s=>({...s,km:kfsClimDistance(city.lat,city.lon,s.lat,s.lon)}))
    .filter(s=>s.km<=25).sort((a,b)=>a.km-b.km).slice(0,12);
  const grouped=new Map();
  for(const s of all){
    const dep=/^(97|98)/.test(s.id)?s.id.slice(0,3):s.id.slice(0,2);
    if(!grouped.has(dep))grouped.set(dep,[]);
    grouped.get(dep).push(s);
  }
  const choices=[];
  for(const group of [...grouped.values()]){
    try{
      const out=await kfsPArchive(group,year);
      for(const station of group){
        const days=(out.byStation[station.id]||[]).filter(d=>!month||Number(d.date.slice(5,7))===month);
        const snow=kfsPStats(days,"neige");
        const depth=days.filter(d=>d.neigeEpaisseur!==null&&Number.isFinite(d.neigeEpaisseur));
        if(snow.valid||depth.length)choices.push({station,snow,depth});
      }
    }catch(e){console.warn("KFS_NEIGE_LOCAL_STATION",String(e).slice(0,100));}
  }
  choices.sort((a,b)=>a.station.km-b.station.km);
  return choices[0]||null;
}
async function kfsPLocalSnowReport(city,year,month){
  let model;
  try{
    model=await kfsPLocalSnowArchive(city,year);
  }catch(e){
    const reason=String(e?.message||e);
    // Une limite du fournisseur ne doit pas provoquer l'erreur générique
    // « la station sélectionnée peut ne pas disposer ... » : cela n'a aucun rapport.
    if(!/HTTP 429|indisponible|trop incomplet|pas encore d'archives/i.test(reason))throw e;
    const period=month?KFS_Q_MONTHS[month-1]+" "+year:"année "+year;
    const fields=[];
    try{
      const obs=await kfsPLocalSnowObservations(city,year,month);
      if(obs){
        const coverage=kfsPExpectedDays(year,month),parts=[];
        if(obs.snow.valid>=Math.ceil(coverage*.85))
          parts.push("Jours avec chute de neige observés : **"+obs.snow.jours+"** ("+obs.snow.valid+"/"+coverage+" jours mesurés).");
        else if(obs.snow.valid)
          parts.push("Chutes : seulement "+obs.snow.valid+"/"+coverage+" jours renseignés — pas de total annuel fiable.");
        if(obs.depth.length>=Math.ceil(coverage*.8)){
          const max=obs.depth.reduce((a,b)=>b.neigeEpaisseur>a.neigeEpaisseur?b:a);
          parts.push("Hauteur maximale mesurée : **"+kfsQR(max.neigeEpaisseur," cm")+"** le "+kfsQCalendarDate(max.date)+".");
        }else if(obs.depth.length)
          parts.push("Hauteur : seulement "+obs.depth.length+"/"+coverage+" jours renseignés — pas de maximum annuel fiable.");
        if(parts.length)fields.push({name:"📍 Mesures locales disponibles",
          value:"Station **"+obs.station.name+"** à "+kfsQR(obs.station.km," km")+"\n"+parts.join("\n"),inline:false});
      }
    }catch(stationError){console.warn("KFS_NEIGE_SAUVEGARDE",String(stationError).slice(0,120));}
    if(!fields.length)fields.push({name:"📍 Stations locales",
      value:"Aucune série de neige exploitable à moins de 25 km. Aucune station distante, notamment Évreux, n'est substituée.",inline:false});
    return {embeds:[{title:"KFS MÉTÉO — ❄️ Neige · "+period,color:0xd99429,
      description:"📍 **"+city.name+"**\n⚠️ **Archive de réanalyse temporairement indisponible.** "+
        reason+"\nL'épaisseur et les jours de neige au sol ne sont pas inventés.",
      fields,footer:{text:"Source locale : Météo-France si disponible · estimation ERA5-Land en attente de disponibilité"}}],
      allowed_mentions:{parse:[]}};
  }
  const yearDays=kfsPExpectedDays(year,month);
  const period=month?KFS_Q_MONTHS[month-1]+" "+year:"année "+year;
  const select=xs=>xs.filter(d=>!month||Number(d.date.slice(5,7))===month);
  const depth=select(model.depth),fall=select(model.fall);
  if(!depth.length||depth.length<Math.ceil(yearDays*.8))
    throw Error("Couverture de la réanalyse locale insuffisante ("+depth.length+"/"+yearDays+" jours).");
  const covered=depth.filter(d=>d.value>=1);
  const covered5=depth.filter(d=>d.value>=5);
  const snow=fall.filter(d=>d.value>=.2),snow1=fall.filter(d=>d.value>=1);
  const max=depth.reduce((a,b)=>!a||b.value>a.value?b:a,null);
  const maxFall=fall.reduce((a,b)=>!a||b.value>a.value?b:a,null);
  const fields=[
    {name:"🌨️ Jours de neige (simulation)",value:"**"+snow.length+" j** avec au moins 0,2 cm de neige tombée calculée\n"+
      "**"+snow1.length+" j** avec au moins 1 cm · "+fall.length+" journées renseignées",inline:true},
    {name:"⛄ Jours avec neige au sol (simulation)",value:"**"+covered.length+" j** avec ≥1 cm\n"+
      "**"+covered5.length+" j** avec ≥5 cm · "+depth.length+" journées renseignées",inline:true},
    {name:"📏 Épaisseur maximale au sol (estimation)",value:"**"+kfsQR(max.value," cm")+"** · "+kfsQCalendarDate(max.date),inline:true},
    {name:"❄️ Neige tombée maximale en 24 h (simulation)",value:"**"+kfsQR(maxFall?.value," cm")+"** · "+(maxFall?kfsQCalendarDate(maxFall.date):"n/d"),inline:true}
  ];
  if(month&&covered.length)
    fields.push({name:"📆 Journées avec au moins 1 cm au sol (modèle)",
      value:covered.slice(0,22).map(d=>kfsQCalendarDate(d.date)+" : "+kfsQR(d.value," cm")).join("\n").slice(0,1000),inline:false});
  if(!month){
    const list=KFS_Q_MONTHS.map((name,i)=>{
      const mm=String(i+1).padStart(2,"0");
      const a=depth.filter(d=>d.date.slice(5,7)===mm);
      const b=fall.filter(d=>d.date.slice(5,7)===mm);
      return name.slice(0,4).padEnd(5," ")+" "+String(b.filter(d=>d.value>=.2).length).padStart(2," ")+" / "+
        String(a.filter(d=>d.value>=1).length).padStart(2," ")+" / "+
        (a.length?kfsQR(Math.max(...a.map(d=>d.value))," cm"):"n/d");
    });
    fields.push({name:"📅 Par mois : jours de neige / jours neige au sol / maxi",
      value:"\x60\x60\x60\n"+list.join("\n")+"\n\x60\x60\x60",inline:false});
  }
  // Bloc séparé : relevés réellement observés à moins de 25 km, s'ils existent.
  try{
    const obs=await kfsPLocalSnowObservations(city,year,month);
    if(obs){
      const coverage=yearDays;
      const parts=[];
      if(obs.snow.valid>=Math.ceil(coverage*.85))
        parts.push("Chutes observées : **"+obs.snow.jours+" jours** ("+obs.snow.valid+"/"+coverage+" jours)");
      else if(obs.snow.valid)
        parts.push("Chutes : série incomplète ("+obs.snow.valid+"/"+coverage+" jours) — **total annuel non fiable**");
      const vals=obs.depth;
      if(vals.length>=Math.ceil(coverage*.8)){
        const maxMeasured=vals.reduce((a,b)=>b.neigeEpaisseur>a.neigeEpaisseur?b:a);
        parts.push("Hauteur maximale mesurée : **"+kfsQR(maxMeasured.neigeEpaisseur," cm")+"** le "+
          kfsQCalendarDate(maxMeasured.date)+" ("+vals.length+"/"+coverage+" jours)");
      }else if(vals.length)parts.push("Hauteur : "+vals.length+"/"+coverage+" jours renseignés — série incomplète");
      if(parts.length)fields.unshift({name:"📍 Relevés de station (distincts du modèle)",
        value:"**"+obs.station.name+"** à "+kfsQR(obs.station.km," km")+"\n"+parts.join("\n"),inline:false});
    }
  }catch(e){console.warn("KFS_NEIGE_LOCAL_STATION_FAIL",String(e).slice(0,120));}
  const label=model.sourceFall==="era5_land"?"ERA5-Land ~9–11 km":model.sourceFall==="ecmwf_ifs"?"ECMWF IFS ~9 km":"ERA5 ~25 km";
  const cautions=["🔎 **Estimation locale par réanalyse** : les valeurs ne sont pas des mesures exactes à "+city.name+".",
    "ERA5-Land (environ 9–11 km) peut surestimer la neige au sol. Ne pas confondre chute et épaisseur."];
  if(year===new Date().getUTCFullYear())cautions.push("Année en cours : réanalyse publiée avec décalage.");
  return {embeds:[{title:"KFS MÉTÉO — ❄️ Neige · "+period,url:"https://open-meteo.com/en/docs/historical-weather-api",
    color:0x1975b8,description:"📍 **"+city.name+"** · Maillage historique centré près de "+
      kfsQR(model.depthLat,"°N")+", "+kfsQR(model.depthLon,"°E")+"\n"+cautions.join("\n"),
    fields,footer:{text:"Hauteur au sol : Copernicus ERA5-Land via Open-Meteo · Chutes : "+label+" via Open-Meteo · Reconstitution, non mesure de station"}}],
    allowed_mentions:{parse:[]}};
}

async function kfsPReport(city,year,month,rubrique) {
  const chosen=await kfsPSelect(city,year,month,rubrique);
  const days=chosen.days,field=rubrique==="orages"?"orage":"neige";
  const main=kfsPStats(days,field);
  const period=month?KFS_Q_MONTHS[month-1]+" "+year:"année "+year;
  const fields=[{name:rubrique==="orages"?"⛈️ Jours avec orage":"❄️ Jours avec chute de neige",
    value:"**"+main.jours+" jour(s)** sur **"+main.valid+" jour(s)** disposant d'une observation du phénomène.",inline:false}];
  if(rubrique==="neige"){
    const sol=kfsPStats(days,"neigeSol");
    if(sol.valid)fields.push({name:"⛄ Sol couvert de neige",value:"**"+sol.jours+" jour(s)** · "+sol.valid+" jours renseignés",inline:true});
    else fields.push({name:"⛄ Sol couvert de neige",value:"Non mesuré à cette station (ne signifie pas absence de neige).",inline:true});
    const deep=days.filter(d=>d.neigeEpaisseur!==null&&Number.isFinite(d.neigeEpaisseur));
    if(deep.length){
      const max=deep.reduce((a,b)=>b.neigeEpaisseur>a.neigeEpaisseur?b:a);
      fields.push({name:"📏 Épaisseur maximale de neige au sol",value:"**"+kfsQR(max.neigeEpaisseur," cm")+"** · "+kfsQCalendarDate(max.date)+" · "+deep.length+" jours renseignés",inline:true});
    }
    const fresh=days.filter(d=>d.neigeFraiche!==null&&Number.isFinite(d.neigeFraiche));
    if(fresh.length){
      const max=fresh.reduce((a,b)=>b.neigeFraiche>a.neigeFraiche?b:a);
      fields.push({name:"🌨️ Neige fraîche maximale sur 24 h",value:"**"+kfsQR(max.neigeFraiche," cm")+"** · "+kfsQCalendarDate(max.date)+" · "+fresh.length+" jours renseignés",inline:true});
    }
  }
  if(!month) {
    const monthly=KFS_Q_MONTHS.map((m,i)=>{
      const sub=kfsPStats(days.filter(d=>Number(d.date.slice(5,7))===i+1),field);
      return m.slice(0,4).padEnd(5," ")+" "+String(sub.valid?sub.jours:"—").padStart(3," ")+" / "+String(sub.valid).padStart(2," ");
    });
    fields.push({name:"📅 Détail mensuel : jours / jours observés",
      value:"\x60\x60\x60\n"+monthly.join("\n")+"\n\x60\x60\x60",inline:false});
  } else if(main.dates.length) {
    fields.push({name:"📆 Dates observées",
      value:main.dates.slice(0,18).map(kfsQCalendarDate).join(" · ")+(main.dates.length>18?" · …":""),
      inline:false});
  }
  try{
    const txt=await(await kfsClimFetch(KFS_CLIM_BASE+"FICHECLIM_"+chosen.station.id+".data",86400)).text();
    const doc=kfsClimParse(txt,chosen.station.id);
    const row=doc.rows.find(r=>r.group==="Phénomènes"&&kfsClimN(r.label).startsWith(rubrique==="orages"?"orage":"neige"));
    const normal=row?.values?.[month?month-1:12];
    if(normal!==null&&normal!==undefined)fields.push({
      name:"📊 Normale climatologique (référence distincte)",
      value:"**"+kfsQR(normal," jour(s)")+"** · période "+(row.period||"indiquée par Météo-France"),
      inline:false});
  }catch(_){}
  const total=chosen.expected;
  const cautions=[];
  if(main.valid<total*.95)cautions.push("⚠️ Couverture partielle ("+main.valid+"/"+total+" jours attendus) : aucun décompte n'est extrapolé.");
  if(chosen.station.km>30)cautions.push("⚠️ Station éloignée : le résultat n'est pas propre au microclimat exact de la ville.");
  if(year===new Date().getUTCFullYear())cautions.push("Année en cours : relevés partiels.");
  return {embeds:[{title:"KFS MÉTÉO — "+(rubrique==="orages"?"⛈️ Orages":"❄️ Neige")+" · "+period,
    color:0x1975b8,description:"📍 **"+city.name+"** · Station **"+chosen.station.name+"** (n° "+chosen.station.id+") · "+kfsQR(chosen.station.km," km")+
      (cautions.length?"\n"+cautions.join("\n"):""),
    fields,footer:{text:"Source : Météo-France · "+chosen.filename+" · qualité 0/1 (validée), 9 (premier contrôle) · jours sans mesure exclus"}}],
    allowed_mentions:{parse:[]}};
}
