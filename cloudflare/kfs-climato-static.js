/* KFS StatIC pilot: read-only, separate from official Météo-France.
   API: https://portail.chom.engineering/llms-full.txt
   Licence Ouverte 2.0 as listed by provider, attribution Infoclimat.
*/
const KFS_STATIC_BASE="https://climato.chom.engineering";
async function kfsStaticFetch(path,params,ttl){
  const url=new URL(KFS_STATIC_BASE+path);
  for(const [k,v] of Object.entries(params||{}))url.searchParams.set(k,String(v));
  const res=await fetch(url,{headers:{accept:"application/json"},cf:{cacheEverything:true,cacheTtlByStatus:{"200-299":ttl,"400-599":0}},signal:AbortSignal.timeout(9000)});
  if(!res.ok)throw Error("API StatIC indisponible (HTTP "+res.status+").");
  return res.json();
}
function kfsStaticPeriod(year,month){
  const today=new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Paris",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
  if(month==="en_cours"){year=Number(today.slice(0,4));month=Number(today.slice(5,7));}
  else month=kfsQMonth(month);
  const from=year+"-"+String(month||1).padStart(2,"0")+"-01";
  const end=new Date(Date.UTC(year,month||12,1)).toISOString().slice(0,10);
  const to=end<today?end:today;
  if(to<=from)throw Error("Aucune journée terminée sur la période demandée.");
  return {from,to,expected:Math.round((Date.parse(to)-Date.parse(from))/86400000),year,month};
}
function kfsStaticCandidates(rows,city,period){
  const dedup=new Map();
  for(const r of rows){
    if(r.pays!=="FR"||r.ouverte!==true||r.parametre!=="air_temperature"||!r.ic_id||!r.libelle||!Number.isFinite(r.latitude)||!Number.isFinite(r.longitude))continue;
    const first=String(r.premiere_obs||"").slice(0,10),last=String(r.derniere_obs||"").slice(0,10);
    if(!first||!last||first>=period.to||last<period.from)continue;
    const km=kfsClimDistance(city.lat,city.lon,r.latitude,r.longitude);
    if(km>50)continue;
    dedup.set(r.ic_id,{id:String(r.ic_id),name:String(r.libelle),km,alt:r.altitude});
  }
  return [...dedup.values()].sort((a,b)=>a.km-b.km).slice(0,4);
}
function kfsStaticDays(rows,id,period){
  const days=new Map();
  const val=(v,lo,hi)=>typeof v==="number"&&Number.isFinite(v)&&v>=lo&&v<=hi?v:null;
  for(const r of rows){
    if(String(r.ic_id)!==id||!/^\d{4}-\d{2}-\d{2}$/.test(r.date)||r.date<period.from||r.date>=period.to)continue;
    const count=Number(r.n_obs),rejected=Number(r.n_obs_rejetees??0),qc=Number(r.taux_qc_valide);
    // Conservative KFS sample-density filter; plausibility is not siting certification.
    if(!Number.isFinite(count)||!Number.isFinite(rejected)||rejected<0||count-rejected<24||!Number.isFinite(qc)||qc<0.99||qc>1)continue;
    let tn=val(r.tn,-50,50),tx=val(r.tx,-50,55),tm=val(r.tm??r.tntxm,-50,55);
    if(tn===null||tx===null||tn>tx)continue;
    if(tm!==null&&(tm<tn||tm>tx))tm=null;
    days.set(r.date,{date:r.date,tn,tx,tm,rr:val(r.rr,0,2000),gust:null,wind:null,gustUtc:null});
  }
  return [...days.values()].sort((a,b)=>a.date.localeCompare(b.date));
}
async function kfsStaticReport(city,year,month){
  const period=kfsStaticPeriod(year,month);
  const catalog=await kfsStaticFetch("/statIC/stations",{},86400);
  if(!Array.isArray(catalog.stations))throw Error("Catalogue StatIC non reconnu.");
  // Independent network identity check: reject official MF posts, even if listed by StatIC.
  const ref=await kfsStaticFetch("/ref/stations",{genre:"static",parametre:"air_temperature",actif_depuis:period.from},86400);
  if(!Array.isArray(ref.features))throw Error("Référentiel des réseaux Infoclimat non reconnu ; aucun repli Météo-France.");
  const ids=new Set(ref.features.map(f=>f.properties).filter(s=>s&&s.genre==="static"&&Object.hasOwn(s,"mfid")&&!String(s.mfid??"").trim()&&!String(s.type_poste??"").trim()&&s.ic_id&&!/^TEST MF CSV/i.test(s.libelle_source||s.libelle||"")).map(s=>String(s.ic_id)));
  const candidates=kfsStaticCandidates(catalog.stations.filter(s=>ids.has(String(s.ic_id))),city,period);
  if(!candidates.length)throw Error("Aucune station StatIC ouverte à moins de 50 km avec des observations sur cette période.");
  // Bounded parallel requests; no whole-France scraping.
  const found=await Promise.all(candidates.map(async station=>{
    try{
      const data=await kfsStaticFetch("/statIC/journaliere",{station:station.id,from:period.from,to:period.to},3600);
      if(data.tronque||!Array.isArray(data.mesures))return null;
      const days=kfsStaticDays(data.mesures,station.id,period);
      return days.length?{station,days}:null;
    }catch(e){console.warn("KFS_STATIC_STATION",String(e).slice(0,150));return null;}
  }));
  const available=found.filter(Boolean);
  if(!available.length)throw Error("Aucune série StatIC suffisamment échantillonnée pour cette période, ou source temporairement indisponible.");
  const selected=available.find(x=>x.days.length>=Math.ceil(period.expected*.8))||available.sort((a,b)=>b.days.length-a.days.length||a.station.km-b.station.km)[0];
  const a=kfsQAggregate(selected.days),s=selected.station;
  const range=period.from+" au "+new Date(Date.parse(period.to)-86400000).toISOString().slice(0,10);
  const p=(n,u)=>kfsQR(n,u);
  const fields=[
    {name:"🌡️ Températures moyennes",value:"Tmin : **"+p(a.meanTn," °C")+"**\nTmax : **"+p(a.meanTx," °C")+"**\n(Tn + Tx)/2 : **"+p(a.meanTm," °C")+"**",inline:true},
    {name:"Extrêmes observés",value:"Min : "+p(a.mostCold?.tn," °C")+" ("+a.mostCold?.date+")\nMax : "+p(a.mostHot?.tx," °C")+" ("+a.mostHot?.date+")",inline:true},
    {name:"🌧️ Précipitations",value:(a.rainSum===null?"Non disponibles":p(a.rainSum," mm")+(a.counts.rr<period.expected?" · cumul partiel":""))+"\n"+a.counts.rr+"/"+period.expected+" jours renseignés ; qualité pluie non certifiée.",inline:true},
    {name:"❄️ Gel / chaleur",value:a.frost+" j de gel (Tn ≤ 0 °C) · "+a.hot30+" j ≥ 30 °C, sur jours retenus.",inline:true},
    {name:"Couverture et fraîcheur",value:a.observed+"/"+period.expected+" jours retenus · dernière date retenue : **"+selected.days.at(-1).date+"**. "+(a.observed<period.expected?"Période incomplète ; statistiques partielles. ":"")+"Minimum 24 observations thermiques non rejetées et 99 % physiquement plausibles (filtre KFS, ne certifie pas l'installation).",inline:false}
  ];
  return {embeds:[{title:"KFS MÉTÉO — Station participative StatIC",color:0x1975b8,description:"📍 **"+city.name+"** · **"+s.name+"** ("+s.id+", "+p(s.km," km")+")\n"+range+"\nRéseau StatIC vérifié (sans identifiant Météo-France) ; aucune normale officielle calculée. Températures agrégées sur les jours civils locaux.",fields,footer:{text:"Source : Infoclimat / réseau StatIC · agrégats chom.engineering · Licence Ouverte 2.0 (selon portail) · Calculs KFS"}}],allowed_mentions:{parse:[]}};
}
