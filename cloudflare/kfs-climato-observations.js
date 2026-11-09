/* KFS CLIMATO : bilans annuels et mensuels calculés sur données quotidiennes Météo-France.
   Ne confond pas jours de forte chaleur, séquences chaudes conventionnelles
   et vigilance officielle canicule. Ne remplace aucune donnée manquante.
*/
const KFS_Q_BASE="https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/BASE/QUOT/";
const KFS_Q_MONTHS=["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"];
function kfsQFilename(poste,annee) {
  const dept=/^(97|98)/.test(poste)?poste.slice(0,3):poste.slice(0,2);
  const period=annee<1950?"before-1949":annee<=2024?"previous-1950-2024":"latest-2025-2026";
  if(annee>2026)throw Error("Les archives postérieures à 2026 ne sont pas encore paramétrées.");
  return "Q_"+dept+"_"+period+"_RR-T-Vent.csv.gz";
}
function kfsQDate(s){
  if(!/^\d{8}$/.test(String(s)))return null;
  return s.slice(0,4)+"-"+s.slice(4,6)+"-"+s.slice(6,8);
}
function kfsQNumber(raw) {
  if(raw===undefined||raw===null||!String(raw).trim())return null;
  const val=Number(String(raw).replace(",","."));
  return Number.isFinite(val)?val:null;
}
function kfsQCalendarDate(d) {
  return new Date(d+"T12:00:00Z").toLocaleDateString("fr-FR",{day:"numeric",month:"long",year:"numeric",timeZone:"UTC"});
}
function kfsQInputYear(x) {
  const now=new Date().getUTCFullYear();
  if(x===undefined||x===null||x==="")return now-1;
  const year=Number(x);
  if(!Number.isInteger(year)||year<1850||year>now)throw Error("Année invalide : indique une année de 1850 à "+now+".");
  return year;
}
function kfsQMonth(x) {
  if(!x||x==="annee")return 0;
  const n=Number(x);
  if(!Number.isInteger(n)||n<1||n>12)throw Error("Mois invalide.");
  return n;
}
async function kfsQStationDays(poste,year) {
  const filename=kfsQFilename(poste,year);
  const cacheKey=new Request("https://kfs-meteo-ia.alain-leprevost.workers.dev/_cache_climato/"+encodeURIComponent(poste)+"/"+year);
  const cached=await caches.default.match(cacheKey);
  if(cached) {
    const data=await cached.json();
    if(Array.isArray(data.days))return {...data,filename,fromCache:true};
  }
  const url=KFS_Q_BASE+filename;
  const r=await fetch(url,{cf:{cacheEverything:true,cacheTtl:year>=2025?21600:172800}});
  if(!r.ok||!r.body)throw Error("Archive quotidienne officielle indisponible ("+filename+" : HTTP "+r.status+").");
  let reader;
  try {
    reader=r.body.pipeThrough(new DecompressionStream("gzip")).getReader();
  } catch(e) {throw Error("Impossible de décompresser l'archive Météo-France : "+String(e).slice(0,100));}
  const decoder=new TextDecoder();
  let pending="",header=null,days=[],lines=0;
  function process(line){
    if(!line)return;
    if(!header){
      header=line.replace(/^\uFEFF/,"").split(";").map(x=>x.trim().toUpperCase());
      if(!header.includes("NUM_POSTE")||!header.includes("AAAAMMJJ"))throw Error("Format de l'archive quotidienne non reconnu.");
      return;
    }
    // Éviter la conversion coûteuse des autres milliers de stations.
    if(!line.startsWith(poste+";"))return;
    const cols=line.split(";");
    if(cols[header.indexOf("NUM_POSTE")]!==poste)return;
    const date=kfsQDate(cols[header.indexOf("AAAAMMJJ")]);
    if(!date||Number(date.slice(0,4))!==year)return;
    const get=(key)=>{
      const p=header.indexOf(key);
      return p<0?null:kfsQNumber(cols[p]);
    };
    const wind=get("FXI")??get("FXI3S");
    const maxWindHr=get("HXI")??get("HXI3S");
    days.push({date,tx:get("TX"),tn:get("TN"),tm:get("TM")??get("TNTXM"),
      rr:get("RR"),gust:wind===null?null:wind*3.6,
      gustUtc:maxWindHr===null?null:String(Math.round(maxWindHr)).padStart(4,"0"),
      wind:get("FFM")===null?null:get("FFM")*3.6});
  }
  try {
    for(;;) {
      const {value,done}=await reader.read();
      if(done)break;
      pending+=decoder.decode(value,{stream:true});
      let start=0,end;
      while((end=pending.indexOf("\n",start))>=0){
        process(pending.slice(start,end).replace(/\r$/,""));
        start=end+1;
        if(++lines>25000000)throw Error("Archive anormalement volumineuse.");
      }
      pending=pending.slice(start);
      if(pending.length>2000000)throw Error("Ligne d'archive trop longue.");
    }
    pending+=decoder.decode();
    if(pending)process(pending.replace(/\r$/,""));
  } finally {
    try{await reader.cancel();}catch(_){}
  }
  const unique=new Map(days.map(d=>[d.date,d]));
  days=[...unique.values()].sort((a,b)=>a.date.localeCompare(b.date));
  const data={days};
  if(days.length) {
    try {
      await caches.default.put(cacheKey,new Response(JSON.stringify(data),{
        headers:{"Cache-Control":"public,max-age="+(year>=2025?21600:172800),"content-type":"application/json"}
      }));
    } catch(e){console.warn("KFS_DAILY_CACHE_SKIP",String(e).slice(0,100));}
  }
  return {...data,filename,fromCache:false};
}
function kfsQAggregate(days) {
  const valid=(key)=>days.filter(d=>d[key]!==null&&Number.isFinite(d[key]));
  const mean=(values)=>values.length?values.reduce((a,x)=>a+x,0)/values.length:null;
  const tx=valid("tx"),tn=valid("tn"),tm=valid("tm"),rr=valid("rr"),gust=valid("gust"),wind=valid("wind");
  const maxima=(arr,key,isMin=false)=>arr.length?arr.reduce((a,d)=>isMin?d[key]<a[key]?d:a:d[key]>a[key]?d:a):null;
  const mostHot=maxima(tx,"tx"),mostCold=maxima(tn,"tn",true),mostRain=maxima(rr,"rr"),mostWind=maxima(gust,"gust");
  const sorted=[...days].sort((a,b)=>a.date.localeCompare(b.date));
  const episodes=[];let run=[];
  const endRun=()=>{if(run.length>=3)episodes.push({start:run[0].date,end:run[run.length-1].date,days:run.length});run=[];};
  for(const day of sorted){
    const match=day.tx!==null&&day.tx>30;
    if(match){
      if(run.length && (Date.parse(day.date)-Date.parse(run[run.length-1].date)!==86400000))endRun();
      run.push(day);
    } else endRun();
  }
  endRun();
  return {
    observed:days.length,
    counts:{tx:tx.length,tn:tn.length,tm:tm.length,rr:rr.length,gust:gust.length},
    meanTx:mean(tx.map(d=>d.tx)),meanTn:mean(tn.map(d=>d.tn)),meanTm:mean(tm.map(d=>d.tm)),
    rainSum:rr.length?rr.reduce((s,d)=>s+d.rr,0):null,meanWind:mean(wind.map(d=>d.wind)),
    hot25:tx.filter(d=>d.tx>=25).length,hot30:tx.filter(d=>d.tx>=30).length,
    hot35:tx.filter(d=>d.tx>=35).length,hot40:tx.filter(d=>d.tx>=40).length,
    tropical:tn.filter(d=>d.tn>=20).length,
    frost:tn.filter(d=>d.tn<=0).length,cold5:tn.filter(d=>d.tn<=-5).length,
    cold10:tn.filter(d=>d.tn<=-10).length,veryCold:tn.filter(d=>d.tn<=-15).length,
    wet1:rr.filter(d=>d.rr>=1).length,wet10:rr.filter(d=>d.rr>=10).length,
    wet20:rr.filter(d=>d.rr>=20).length,
    gust80:gust.filter(d=>d.gust>=80).length,gust100:gust.filter(d=>d.gust>=100).length,
    mostHot,mostCold,mostRain,mostWind,
    episodes,hotSequenceDays:episodes.reduce((s,e)=>s+e.days,0)
  };
}
const kfsQR=(x,unit="")=>x===null||x===undefined?"n/d":Number(x).toLocaleString("fr-FR",{maximumFractionDigits:1})+unit;
function kfsQReport(city,station,year,month,data,rubrique){
  const days=data.days.filter(d=>month===0||Number(d.date.slice(5,7))===month);
  if(!days.length)throw Error("Aucune mesure quotidienne disponible pour "+year+(month?" / "+KFS_Q_MONTHS[month-1]:"")+" à la station "+station.station.name+".");
  const a=kfsQAggregate(days);
  const periode=month?KFS_Q_MONTHS[month-1]+" "+year:"année "+year;
  const description="📍 **"+city.name+"** · Station **"+station.station.name+"** (n° "+station.station.id+", "+kfsQR(station.station.km," km")+")"+
    "\n📆 **"+periode+"** · **"+a.observed+" jours** avec observations"+(year===new Date().getUTCFullYear()?" · année en cours":"");
  const fields=[];
  const add=(name,value)=>fields.push({name,value:inlineFormat(value),inline:true});
  function inlineFormat(v){return String(v).slice(0,1000);}
  const extreme=(row,key,unit,utc=false)=>row?kfsQR(row[key],unit)+" — **"+kfsQCalendarDate(row.date)+"**"+(utc&&row.gustUtc?" · "+row.gustUtc.slice(0,2)+"h"+row.gustUtc.slice(2,4)+" UTC":""):"n/d";
  if(!["pluie","vent","episodes"].includes(rubrique)){
    add("🌡️ Températures moyennes","Moyenne : **"+kfsQR(a.meanTm," °C")+"**\nTmax : **"+kfsQR(a.meanTx," °C")+"**\nTmin : **"+kfsQR(a.meanTn," °C")+"**");
    add("🔥 Journée la plus chaude",extreme(a.mostHot,"tx"," °C"));
    add("❄️ Journée la plus froide",extreme(a.mostCold,"tn"," °C"));
    add("☀️ Jours chauds","≥ 25 °C : **"+a.hot25+"**\n≥ 30 °C : **"+a.hot30+"**\n≥ 35 °C : **"+a.hot35+"**\n≥ 40 °C : **"+a.hot40+"**");
    add("🧊 Jours froids","Gel (Tn ≤ 0 °C) : **"+a.frost+"**\nTn ≤ −5 °C : **"+a.cold5+"**\nTn ≤ −10 °C : **"+a.cold10+"**\nTn ≤ −15 °C : **"+a.veryCold+"**");
    add("🌙 Nuits tropicales","Tn ≥ 20 °C : **"+a.tropical+"**");
  }
  if(["bilan","complet","episodes","temperature"].includes(rubrique)||!rubrique){
    const labels=a.episodes.slice(0,4).map(e=>kfsQCalendarDate(e.start)+" → "+kfsQCalendarDate(e.end)+" ("+e.days+" j)").join("\n");
    add("🥵 Séquences chaudes (indicateur simplifié)","**"+a.episodes.length+" séquence(s), "+a.hotSequenceDays+" jours**\nCritère : au moins 3 jours consécutifs avec Tmax > 30 °C (sans condition sur les nuits). Ce n’est pas une définition officielle de canicule."+(labels?"\n"+labels:""));
  }
  if(["bilan","complet","pluie"].includes(rubrique)||!rubrique){
    add("🌧️ Précipitations","Cumul : **"+kfsQR(a.rainSum," mm")+"**\nJours ≥1 mm : **"+a.wet1+"**\nJours ≥10 mm : **"+a.wet10+"**\nJours ≥20 mm : **"+a.wet20+"**");
    add("🌧️ Jour le plus pluvieux",extreme(a.mostRain,"rr"," mm"));
  }
  if(["bilan","complet","vent"].includes(rubrique)||!rubrique){
    add("💨 Rafale maximale",extreme(a.mostWind,"gust"," km/h",true));
    add("🌬️ Vent moyen",kfsQR(a.meanWind," km/h")+"\nJours avec rafale ≥80 km/h : **"+a.gust80+"**\n≥100 km/h : **"+a.gust100+"**");
  }
  if(rubrique==="mensuel"&&month===0){
    const vals=Array.from({length:12},(_,i)=>{
      const sub=kfsQAggregate(data.days.filter(d=>Number(d.date.slice(5,7))===i+1));
      return [KFS_Q_MONTHS[i].slice(0,4),kfsQR(sub.meanTm),kfsQR(sub.mostHot?.tx),kfsQR(sub.mostCold?.tn),kfsQR(sub.rainSum),kfsQR(sub.mostWind?.gust)];
    });
    const rows=vals.map(v=>v.map((z,i)=>String(z).padEnd([4,5,5,5,6,5][i]," ")).join(" ")).join("\n");
    fields.push({name:"📅 Détail mensuel · Tmoy Tmax absolue Tmin absolue Pluie Rafale",value:"\x60\x60\x60\n"+rows+"\n\x60\x60\x60".slice(0,1010),inline:false});
  }
  const counts=a.counts;
  fields.push({name:"📋 Couverture des mesures",value:"Tmax : "+counts.tx+" jours · Tmin : "+counts.tn+" · pluie : "+counts.rr+" · rafales : "+counts.gust+".\nLes valeurs manquantes ne sont pas assimilées à zéro.",inline:false});
  const embeds=[];
  for(let i=0;i<fields.length;i+=20)embeds.push({
    title:"KFS MÉTÉO — Climatologie observée · "+periode+(i?" (suite)":""),
    description:i?"":description,
    color:0x1975b8,fields:fields.slice(i,i+20),
    footer:{text:"Source : Météo-France · Archives quotidiennes · "+data.filename+" · Calculs KFS (canicule non officielle)"}
  });
  return {embeds,allowed_mentions:{parse:[]}};
}
async function kfsClimatoHandleV2(interaction,appId) {
  const args=interaction.data?.options||[];
  const get=n=>args.find(x=>x.name===n)?.value;
  const discord="https://discord.com/api/v10/webhooks/"+appId+"/"+interaction.token;
  let payload;
  try {
    const city=await kfsClimCity(String(get("ville")||""));
    const selected=await kfsClimStationForCity(city);
    const rubrique=String(get("rubrique")||"bilan");
    const month=String(get("mois")||"annee");
    if(["normales","records"].includes(rubrique)){
      payload=kfsClimMessage(city,selected,rubrique==="normales"?"complet":"records",month);
    } else {
      const year=kfsQInputYear(get("annee"));
      const result=await kfsQStationDays(selected.station.id,year);
      payload=kfsQReport(city,selected,year,kfsQMonth(month),result,rubrique);
    }
  } catch(e) {
    payload={content:"⚠️ **KFS MÉTÉO — /climato** : "+String(e?.message||e).slice(0,350)+
      "\nLa station sélectionnée peut ne pas disposer d'une série complète pour l'année choisie. Aucune valeur n'est inventée.",allowed_mentions:{parse:[]}};
    console.error("KFS_CLIMATO_V2_ERROR",String(e?.stack||e).slice(0,500));
  }
  const pages=payload.embeds?Array.from({length:Math.ceil(payload.embeds.length/10)},(_,i)=>payload.embeds.slice(i*10,i*10+10)):[];
  const first=pages.length?{...payload,embeds:pages[0]}:payload;
  const result=await fetch(discord+"/messages/@original",{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify(first)});
  if(!result.ok){console.error("KFS_CLIMATO_V2_DISCORD",result.status,(await result.text()).slice(0,300));return;}
  for(let i=1;i<pages.length;i++){
    const r=await fetch(discord,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({embeds:pages[i],allowed_mentions:{parse:[]}})});
    if(!r.ok)console.error("KFS_CLIMATO_V2_PAGE",r.status);
  }
}
async function kfsClimatoRegisterV2(botToken,appId,guildId){
  if(!botToken||!appId||!guildId)throw Error("Configuration Discord absente");
  const cmd={name:"climato",type:1,
    description:"Statistiques officielles annuelles, mensuelles et normales Météo-France par ville",
    options:[
      {type:3,name:"ville",description:"Ville française (ex. Évreux, Rouen, Paris)",required:true,min_length:2,max_length:80},
      {type:4,name:"annee",description:"Année observée : ex. 2024 ou 2025 (défaut : dernière année complète)",required:false,min_value:1850,max_value:2026},
      {type:3,name:"mois",description:"Mois de l'année (défaut : année entière)",required:false,
        choices:[{name:"Année complète",value:"annee"},...KFS_Q_MONTHS.map((name,i)=>({name,value:String(i+1)}))]},
      {type:3,name:"rubrique",description:"Bilan, détails, statistiques normales ou records",required:false,
        choices:[
          {name:"Bilan annuel ou mensuel",value:"bilan"},
          {name:"Toutes les statistiques observées",value:"complet"},
          {name:"Tableau des 12 mois observés",value:"mensuel"},
          {name:"Température, chaleur et gel",value:"temperature"},
          {name:"Pluies et cumuls",value:"pluie"},
          {name:"Vent et rafales",value:"vent"},
          {name:"Épisodes chauds",value:"episodes"},
          {name:"Normales 1991–2020",value:"normales"},
          {name:"Records historiques de la station",value:"records"}
        ]}
    ]};
  const u="https://discord.com/api/v10/applications/"+appId+"/guilds/"+guildId+"/commands";
  const r=await fetch(u,{method:"POST",headers:{"Authorization":"Bot "+botToken,"content-type":"application/json"},body:JSON.stringify(cmd)});
  if(!r.ok)throw Error("Discord /climato register HTTP "+r.status+" : "+(await r.text()).slice(0,250));
  console.log("KFS_CLIMATO_V2_REGISTER_OK",r.status);
  return r.status;
}
