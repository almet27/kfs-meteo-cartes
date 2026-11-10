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
  const cacheKey=new Request("https://kfs-meteo-ia.alain-leprevost.workers.dev/_cache_climato_pheno/"+dept+"/"+year+"/"+ids.join("."));
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
