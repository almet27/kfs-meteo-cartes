
// KFS /proba — prévisions multi-ensembles, J+0 à J+3, France / régions.
// Pas de taux de confiance inventé : décompte des membres, puis moyenne
// à poids égaux entre familles d'ensembles effectivement disponibles.
// Source données : Open-Meteo Ensemble API ; contours : IGN / INSEE (geojson).
const KFS_PROBA_MODELS = [
  ["ECMWF IFS ENS","ecmwf_ifs025_ensemble"],
  ["ECMWF AIFS ENS","ecmwf_aifs025_ensemble"],
  ["GEFS NOAA","ncep_gefs025"],
  ["AIGEFS NOAA","ncep_aigefs025"],
  ["ICON EU EPS","dwd_icon_eu_eps"],
  ["UKMO MOGREPS-G","ukmo_global_ensemble_20km"],
  ["GEM EPS","cmc_gem_geps"]
];
const KFS_PROBA_REGIONS = [
 ["11","Île-de-France"],["24","Centre-Val de Loire"],
 ["27","Bourgogne-Franche-Comté"],["28","Normandie"],
 ["32","Hauts-de-France"],["44","Grand Est"],
 ["52","Pays de la Loire"],["53","Bretagne"],
 ["75","Nouvelle-Aquitaine"],["76","Occitanie"],
 ["84","Auvergne-Rhône-Alpes"],["93","Provence-Alpes-Côte d'Azur"],
 ["94","Corse"]
];
const KFS_PROBA_RULES = {
 neige:{unit:"cm",defaults:1,allowed:[1,3,5,10],variable:"snow_depth",title:"Neige présente au sol"},
 pluie:{unit:"mm / 24 h",defaults:0.1,allowed:[0.1,1,5,10,20,40],variable:"rain",title:"Cumul de pluie"},
 vent:{unit:"km/h",defaults:80,allowed:[60,80,100,120],variable:"wind_gusts_10m",title:"Rafales maximales"},
 orage:{unit:"niveau",defaults:3,allowed:[1,2,3,4,5],variable:"cape",title:"Potentiel orageux"}
};
let KFS_PROBA_LAST_REGISTER=0;
async function kfsProbaRegister(env){
 if(!env.DISCORD_BOT_TOKEN)throw Error("Jeton Discord absent");
 const cmd={name:"proba",type:1,description:"Probabilités météo jusqu'à J+3 · France et régions",options:[
  {name:"phenomene",type:3,description:"Pluie, neige, rafales et orages",required:true,
   choices:[{name:"🌨️ Neige au sol",value:"neige"},{name:"🌧️ Pluie",value:"pluie"},{name:"💨 Rafales",value:"vent"},{name:"🌩️ Orages",value:"orage"}]},
  {name:"zone",type:3,description:"France entière ou région",required:false,
   choices:[{name:"France métropolitaine",value:"FR"},...KFS_PROBA_REGIONS.map(([code,name])=>({name,value:code}))]},
  {name:"jour",type:4,description:"De J+0 à J+3",required:false,
   choices:[0,1,2,3].map(i=>({name:"J+"+i,value:i}))},
  {name:"seuil",type:10,description:"Seuil pluie/neige/rafales (non utilisé pour orage)",required:false,min_value:0.1,max_value:120},
  {name:"niveau",type:3,description:"Orages : niveau minimum à évaluer (défaut : modéré)",required:false,
   choices:[{name:"Faible",value:"faible"},{name:"Moyen",value:"moyen"},{name:"Modéré",value:"modere"},{name:"Fort",value:"fort"},{name:"Extrême",value:"extreme"}]}
 ]};
 const endpoint="https://discord.com/api/v10/applications/"+APPLICATION_ID+"/commands";
 const verify=await fetch(endpoint,{headers:{Authorization:"Bot "+env.DISCORD_BOT_TOKEN}});
 if(verify.ok){
  const registered=await verify.json();
  const same=Array.isArray(registered)&&registered.some(existing=>existing.name==="proba"&&existing.description===cmd.description&&JSON.stringify(existing.options||[])===JSON.stringify(cmd.options));
  if(same){KFS_PROBA_LAST_REGISTER=Date.now();return true;}
 }
 const r=await fetch(endpoint,{
  method:"POST",headers:{Authorization:"Bot "+env.DISCORD_BOT_TOKEN,"content-type":"application/json"},
  body:JSON.stringify(cmd)
 });
 if(!r.ok)throw Error("Discord /proba HTTP "+r.status+": "+(await r.text()).slice(0,240));
 KFS_PROBA_LAST_REGISTER=Date.now();
 return true;
}
async function kfsProbaEdit(interaction,payload,bytes){
 const endpoint="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+"/"+interaction.token+"/messages/@original";
 let r;
 if(bytes){
  const f=new FormData();
  f.append("payload_json",JSON.stringify({...payload,attachments:[{id:0,filename:"kfs-proba.png",description:"Carte KFS des probabilités issues d'ensembles"}]}));
  f.append("files[0]",new Blob([bytes],{type:"image/png"}),"kfs-proba.png");
  r=await fetch(endpoint,{method:"PATCH",body:f});
 }else{
  r=await fetch(endpoint,{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
 }
 if(!r.ok)throw Error("Réponse Discord HTTP "+r.status+": "+(await r.text()).slice(0,120));
}
// Retourne les polygones (y compris les îles et les éventuels trous) en WGS84.
function kfsProbaRings(feature){
 const g=feature.geometry;
 if(g.type==="Polygon")return g.coordinates;
 if(g.type==="MultiPolygon")return g.coordinates.flatMap(p=>p);
 return [];
}
function kfsProbaBBox(features){
 let b=[Infinity,Infinity,-Infinity,-Infinity];
 for(const f of features)for(const ring of kfsProbaRings(f))for(const pt of ring){
  if(pt[0]<b[0])b[0]=pt[0];if(pt[1]<b[1])b[1]=pt[1];
  if(pt[0]>b[2])b[2]=pt[0];if(pt[1]>b[3])b[3]=pt[1];
 }
 return b;
}
function kfsProbaInRing(x,y,ring){
 let found=false;
 for(let i=0,j=ring.length-1;i<ring.length;j=i++){
  const a=ring[i],b=ring[j];
  if((a[1]>y)!==(b[1]>y) && x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])found=!found;
 }
 return found;
}
function kfsProbaInFeature(x,y,f){
 let found=false;
 for(const ring of kfsProbaRings(f))if(kfsProbaInRing(x,y,ring))found=!found;
 return found;
}
function kfsProbaSamples(features,regional){
 const samples=[];
 for(const f of features){
  const [left,bottom,right,top]=kfsProbaBBox([f]);
  const candidates=regional?[
   [.15,.15],[.35,.15],[.55,.15],[.8,.15],
   [.15,.35],[.35,.35],[.55,.35],[.8,.35],
   [.15,.55],[.35,.55],[.55,.55],[.8,.55],
   [.15,.8],[.35,.8],[.55,.8],[.8,.8],
   [.5,.5],[.5,.7],[.7,.5],[.3,.7]
  ]:[[.32,.45],[.68,.55],[.5,.72],[.5,.27],[.5,.5]];
  let picked=0;
  for(const [fx,fy] of candidates){
   const lon=left+(right-left)*fx,lat=bottom+(top-bottom)*fy;
   if(kfsProbaInFeature(lon,lat,f)){
    samples.push({lon:+lon.toFixed(3),lat:+lat.toFixed(3),value:null,models:[]});
    picked++;
    if((!regional&&picked>=2)||(regional&&picked>=12))break;
   }
  }
  if(!picked){
   const ring=kfsProbaRings(f).sort((a,b)=>b.length-a.length)[0]||[];
   if(ring.length){
    const a=ring[Math.floor(ring.length/2)];
    samples.push({lon:a[0],lat:a[1],value:null,models:[]});
   }
  }
 }
 return samples;
}
async function kfsProbaFeatures(){
 const uri="https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/regions-version-simplifiee.geojson";
 const r=await fetch(uri,{cf:{cacheTtl:86400,cacheEverything:true},signal:AbortSignal.timeout(10000)});
 if(!r.ok)throw Error("Contours France non accessibles : "+r.status);
 const j=await r.json();
 const codes=new Set(KFS_PROBA_REGIONS.map(x=>x[0]));
 const feats=(j.features||[]).filter(f=>codes.has(String(f.properties?.code)));
 if(feats.length!==13)throw Error("Contours régionaux incomplets ("+feats.length+"/13)");
 return feats;
}
const KFS_PROBA_DEPTS={"11":["75","77","78","91","92","93","94","95"],"24":["18","28","36","37","41","45"],"27":["21","25","39","58","70","71","89","90"],"28":["14","27","50","61","76"],"32":["02","59","60","62","80"],"44":["08","10","51","52","54","55","57","67","68","88"],"52":["44","49","53","72","85"],"53":["22","29","35","56"],"75":["16","17","19","23","24","33","40","47","64","79","86","87"],"76":["09","11","12","30","31","32","34","46","48","65","66","81","82"],"84":["01","03","07","15","26","38","42","43","63","69","73","74"],"93":["04","05","06","13","83","84"],"94":["2A","2B"]};
const KFS_PROBA_CITIES={"11":[["Paris",2.3522,48.8566],["Versailles",2.1301,48.8014],["Cergy",2.0767,49.036],["Meaux",2.888,48.96]],"24":[["Orleans",1.9093,47.9029],["Tours",0.6848,47.3941],["Chartres",1.489,48.4469],["Bourges",2.396,47.082],["Chateauroux",1.693,46.81]],"27":[["Dijon",5.0415,47.322],["Besancon",6.0256,47.2378],["Auxerre",3.568,47.799],["Belfort",6.86,47.638]],"28":[["Rouen",1.0993,49.4431],["Caen",-0.3707,49.1829],["Le Havre",0.1079,49.4944],["Cherbourg",-1.622,49.64],["Evreux",1.1516,49.024]],"32":[["Lille",3.0573,50.6292],["Amiens",2.2957,49.8942],["Arras",2.7782,50.291],["Beauvais",2.081,49.43],["Dunkerque",2.377,51.034]],"44":[["Strasbourg",7.752,48.5734],["Reims",4.0317,49.2583],["Metz",6.1757,49.1193],["Nancy",6.184,48.692],["Troyes",4.073,48.297]],"52":[["Nantes",-1.5536,47.2184],["Angers",-0.5632,47.4784],["Le Mans",0.199,48.006],["La Roche-sur-Yon",-1.426,46.67],["Laval",-0.77,48.07]],"53":[["Rennes",-1.6778,48.1173],["Brest",-4.486,48.39],["Quimper",-4.096,47.996],["Lorient",-3.37,47.75],["Saint-Brieuc",-2.763,48.514]],"75":[["Bordeaux",-0.5792,44.8378],["Limoges",1.2611,45.8336],["Poitiers",0.34,46.58],["La Rochelle",-1.152,46.16],["Bayonne",-1.475,43.49]],"76":[["Toulouse",1.4442,43.6047],["Montpellier",3.8767,43.6108],["Nimes",4.36,43.837],["Perpignan",2.897,42.698],["Tarbes",0.074,43.233]],"84":[["Lyon",4.8357,45.764],["Grenoble",5.724,45.1885],["Saint-Etienne",4.387,45.4397],["Clermont-Ferrand",3.088,45.777],["Annecy",6.13,45.899]],"93":[["Marseille",5.3698,43.2965],["Nice",7.262,43.71],["Toulon",5.93,43.125],["Avignon",4.8055,43.949],["Gap",6.078,44.559]],"94":[["Ajaccio",8.74,41.93],["Bastia",9.451,42.697],["Porto-Vecchio",9.28,41.59],["Corte",9.152,42.305]]};
async function kfsProbaDepartments(zone){
 if(zone==="FR")return [];
 const wanted=new Set(KFS_PROBA_DEPTS[zone]||[]);
 if(!wanted.size)throw Error("Code de région non reconnu pour les départements.");
 const url="https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson";
 const r=await fetch(url,{cf:{cacheTtl:86400,cacheEverything:true},signal:AbortSignal.timeout(12000)});
 if(!r.ok)throw Error("Contours départementaux non disponibles (HTTP "+r.status+").");
 const data=await r.json();
 const found=(data.features||[]).filter(f=>wanted.has(String(f.properties?.code)));
 if(new Set(found.map(f=>f.properties.code)).size!==wanted.size)
  throw Error("Départements incomplets ("+found.length+"/"+wanted.size+").");
 return found;
}

function kfsProbaDay(day){
 const today=new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Paris",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
 const [y,m,d]=today.split("-").map(Number);
 const target=new Date(Date.UTC(y,m-1,d+day,12));
 return target.toISOString().slice(0,10);
}
function kfsProbaMemberProbability(hourly,day,type,threshold){
 if(!hourly?.time?.length)return null;
 const ids=[];
 for(let i=0;i<hourly.time.length;i++)if(String(hourly.time[i]).startsWith(day))ids.push(i);
 if(!ids.length)return null;
 let pass=0,valid=0,anyRain=0,amountSum=0;
 const keys=Object.keys(hourly).filter(k=>k.startsWith(KFS_PROBA_RULES[type].variable+"_")&&/member\d+/.test(k));
 for(const key of keys){
  const arr=hourly[key];if(!Array.isArray(arr))continue;
  const nums=ids.map(i=>arr[i]).filter(v=>typeof v==="number"&&Number.isFinite(v));
  if(nums.length<Math.ceil(ids.length*0.85))continue;
  const amount=type==="pluie"?Math.max(0,nums.reduce((a,b)=>a+b,0)):
   type==="vent"?Math.max(0,...nums):Math.max(0,...nums)*100;
  if(!Number.isFinite(amount))continue;
  valid++;amountSum+=amount;
  if(amount>=threshold)pass++;
  if(type==="pluie"&&amount>=0.1)anyRain++;
 }
 return valid>=2?{pct:100*pass/valid,amount:amountSum/valid,members:valid,
  wetPct:type==="pluie"?100*anyRain/valid:null}:null;
}

// KFS /proba /orage : seuils *heuristiques*, NON calibrés en risque d'orages violents.
// Les catégories décrivent un potentiel convectif multi-paramètres, pas une vigilance.
const KFS_STORM_NAMES=["AUCUN","FAIBLE","MOYEN","MODERE","FORT","EXTREME"];
const KFS_STORM_LEVELS={faible:1,moyen:2,modere:3,fort:4,extreme:5};
const KFS_STORM_TEMPO="hourly_3";
// Ne jamais utiliser la CAPE seule comme certitude d'orage ou de sévérité.
function kfsProbaStormTier(cape,rain,gust,weatherCode,cin){
 const convective=[95,96,99].includes(weatherCode);
 const cp=Number.isFinite(cape)?cape:null;
 const pr=Number.isFinite(rain)?rain:null;
 const gu=Number.isFinite(gust)?gust:null;
 if(cp===null && !convective)return 0;
 let level=convective?1:0;
 // Pluie et instabilité doivent coexister au même pas de temps.
 if(cp!==null && pr!==null && cp>=150 && pr>=0.2)level=Math.max(level,1);
 if(cp!==null && pr!==null && cp>=400 && pr>=0.5)level=Math.max(level,2);
 if(cp!==null && pr!==null && gu!==null && cp>=900 && pr>=1 && gu>=40)
  level=Math.max(level,3);
 if(cp!==null && pr!==null && gu!==null && cp>=1600 && pr>=2.5 && gu>=60)
  level=Math.max(level,4);
 if(cp!==null && pr!==null && gu!==null && cp>=3000 && pr>=5 && gu>=90)
  level=Math.max(level,5);
 // CIN négative très marquée : réduit l'indice lorsque le modèle ne
 // prévoit pas explicitement d'orage (évite CAPE brute => signal abusif).
 if(!convective && Number.isFinite(cin) && cin<=-200)level=Math.max(0,level-1);
 return level;
}
function kfsProbaStormMembers(hourly,day,minimum){
 if(!Array.isArray(hourly?.time))return null;
 const ids=[];
 for(let i=0;i<hourly.time.length;i++)if(String(hourly.time[i]).startsWith(day))ids.push(i);
 if(ids.length<3)return null;
 const suffixes=new Set();
 for(const key of Object.keys(hourly))
  {const match=key.match(/^(?:cape|weather_code)_member(\d+)$/);if(match)suffixes.add(match[1]);}
 let valid=0,meet=0,active=0,sum=0;
 for(const suffix of suffixes){
  const get=(key,i)=>{
   const value=hourly[key+"_member"+suffix]?.[i];
   return Number.isFinite(value)?value:null;
  };
  const capes=ids.map(i=>get("cape",i));
  const codes=ids.map(i=>get("weather_code",i));
  if(!capes.some(Number.isFinite) && !codes.some(Number.isFinite))continue;
  let level=0,observed=0;
  for(let j=0;j<ids.length;j++){
   const i=ids[j],cape=capes[j],wc=codes[j];
   if(cape===null && wc===null)continue;
   observed++;
   const l=kfsProbaStormTier(cape,get("precipitation",i),
     get("wind_gusts_10m",i),wc,get("convective_inhibition",i));
   level=Math.max(level,l);
  }
  if(observed<Math.ceil(ids.length*.6))continue;
  valid++;meet+=Number(level>=minimum);active+=Number(level>=1);sum+=level;
 }
 return valid>=2?{pct:100*meet/valid,amount:sum/valid,stormPct:100*active/valid,members:valid}:null;
}
// Un lot géographique = plusieurs appels facturés par Open-Meteo.
// Cache de données brutes (indépendant des seuils) et disjoncteur HTTP 429.
// Le cache partagé utilise Cache API ; en développement, mémoire par isolate.
const KFS_PROBA_CACHE_MEMORY=new Map();
const KFS_PROBA_INFLIGHT=new Map();
function kfsProbaCacheHash(str){
 let h=2166136261;
 for(let i=0;i<str.length;i++)h=Math.imul(h^str.charCodeAt(i),16777619)>>>0;
 return h.toString(36)+"-"+str.length;
}
function kfsProbaCacheRequest(key){
 return new Request("https://kfs-meteo-ia.alain-leprevost.workers.dev/__proba_internal_cache__/"+key);
}
async function kfsProbaCacheRead(key){
 const item=KFS_PROBA_CACHE_MEMORY.get(key);
 if(item&&Date.now()<item.expires)return item.payload;
 if(item)KFS_PROBA_CACHE_MEMORY.delete(key);
 try{
  if(typeof caches==="undefined"||!caches.default)return null;
  const r=await caches.default.match(kfsProbaCacheRequest(key));
  if(!r||!r.ok)return null;
  const payload=await r.json();
  if(!payload||Date.now()>=payload.expires)return null;
  if(KFS_PROBA_CACHE_MEMORY.size>40)KFS_PROBA_CACHE_MEMORY.clear();
  KFS_PROBA_CACHE_MEMORY.set(key,{payload,expires:payload.expires});
  return payload;
 }catch(e){console.error("KFS_PROBA_CACHE_READ",String(e));return null;}
}
async function kfsProbaCacheWrite(key,payload,ttl){
 const expires=Date.now()+ttl*1000,data={...payload,expires};
 if(KFS_PROBA_CACHE_MEMORY.size>40)KFS_PROBA_CACHE_MEMORY.clear();
 KFS_PROBA_CACHE_MEMORY.set(key,{payload:data,expires});
 try{
  if(typeof caches==="undefined"||!caches.default)return;
  await caches.default.put(kfsProbaCacheRequest(key),
   new Response(JSON.stringify(data),{headers:{"cache-control":"public, max-age="+ttl,"content-type":"application/json"}}));
 }catch(e){console.error("KFS_PROBA_CACHE_WRITE",String(e));}
}
function kfsProbaDailyFuseKey(){
 return "open-meteo-day-limit-"+new Date().toISOString().slice(0,10);
}
async function kfsProbaReadEnsemble(params){
 const text=params.toString();
 const key="ensemble-"+kfsProbaCacheHash(text);
 const cached=await kfsProbaCacheRead(key);
 if(cached?.data)return cached.data;
 const fuse=await kfsProbaCacheRead(kfsProbaDailyFuseKey());
 if(fuse?.dailyLimit)throw Error("HTTP 429 - quota quotidien Open-Meteo atteint. Les nouvelles données sont indisponibles ; des résultats en cache restent possibles.");
 if(KFS_PROBA_INFLIGHT.has(key))return KFS_PROBA_INFLIGHT.get(key);
 const action=(async()=>{
  const again=await kfsProbaCacheRead(key);
  if(again?.data)return again.data;
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),10500);
  try{
   const r=await fetch("https://ensemble-api.open-meteo.com/v1/ensemble?"+text,{
    signal:controller.signal,headers:{accept:"application/json"},
    cf:{cacheTtl:1800,cacheEverything:true}
   });
   if(!r.ok){
    const msg=(await r.text()).slice(0,220);
    if(r.status===429&&/Daily API request limit exceeded/i.test(msg)){
     const next=new Date(),now=Date.now();
     const tomorrow=Date.UTC(next.getUTCFullYear(),next.getUTCMonth(),next.getUTCDate()+1,0,20);
     const ttl=Math.max(900,Math.ceil((tomorrow-now)/1000));
     await kfsProbaCacheWrite(kfsProbaDailyFuseKey(),{dailyLimit:true,noticedAt:new Date().toISOString()},ttl);
    }
    throw Error("HTTP "+r.status+": "+msg.replace(/\s+/g," ").slice(0,100));
   }
   const data=await r.json();
   // Une valeur obtenue ne doit plus être refetchée pour un autre seuil ou
   // un autre membre Discord de la même région.
   await kfsProbaCacheWrite(key,{data,retrievedAt:new Date().toISOString()},8*3600);
   return data;
  }finally{clearTimeout(timer);}
 })();
 KFS_PROBA_INFLIGHT.set(key,action);
 try{return await action;}finally{KFS_PROBA_INFLIGHT.delete(key);}
}

async function kfsProbaStormModel(model,samples,day,minimum){
 const base={latitude:samples.map(p=>p.lat).join(","),
  longitude:samples.map(p=>p.lon).join(","),models:model[1],
  start_date:day,end_date:day,timezone:"Europe/Paris",temporal_resolution:KFS_STORM_TEMPO};
 const variants=[
  ["cape","precipitation","wind_gusts_10m","weather_code"],
  ["cape","precipitation","wind_gusts_10m"]
 ];
 const deadline=Date.now()+12000;
 let error="";
 for(const fields of variants){
  const left=Math.min(8000,deadline-Date.now());
  if(left<1500)break;
  const params=new URLSearchParams({...base,hourly:fields.join(",")});
  try{
   const data0=await kfsProbaReadEnsemble(params),data=Array.isArray(data0)?data0:[data0];
   if(data.length!==samples.length){error="Nombre de points inattendu";continue;}
   const values=data.map(x=>kfsProbaStormMembers(x.hourly,day,minimum));
   if(values.some(Boolean))return {name:model[0],values,fields};
   error="Aucun membre valide";
  }catch(e){
   error=String(e.message||e).slice(0,120);
   if(/HTTP 429|HTTP 5\d\d/i.test(error))break;
  }
 }
 throw Error("Orage "+model[0]+": "+error);
}
async function kfsProbaModel(model,samples,day,type,threshold){
 const varName=KFS_PROBA_RULES[type].variable;
 const params=new URLSearchParams({
  latitude:samples.map(p=>p.lat).join(","),
  longitude:samples.map(p=>p.lon).join(","),
  models:model[1],hourly:varName,start_date:day,end_date:day,
  timezone:"Europe/Paris",temporal_resolution:"hourly_1"
 });
 const result=await kfsProbaReadEnsemble(params);
 const arr=Array.isArray(result)?result:[result];
 if(arr.length!==samples.length)throw Error("Nombre de points inattendu");
 const values=arr.map(p=>{
  if(type==="neige"&&typeof p.elevation==="number"&&p.elevation>800)return null;
  return kfsProbaMemberProbability(p.hourly,day,type,threshold);
 });
 return {name:model[0],values};
}
function kfsProbaClamp(x,lo,hi){return Math.max(lo,Math.min(hi,x));}
// Seule la quantité moyenne est codée par la couleur, pas le %.
// ZONAGES : quantité moyenne en mm / cm / km/h, indépendamment des % de risque.
const KFS_PROBA_SCALE={
 pluie:{unit:"mm",ticks:[0,1,3,5,10,20,40],
  colors:[[20,49,83],[35,91,151],[50,150,200],[48,189,164],[208,198,76],[241,143,58],[222,66,83]]},
 neige:{unit:"cm",ticks:[0,0.5,1,3,5,10,20],
  colors:[[26,52,91],[45,94,160],[76,148,209],[105,172,230],[135,138,221],[168,98,210],[224,67,157]]},
 vent:{unit:"km/h",ticks:[0,30,50,70,90,110,130],
  colors:[[24,53,90],[45,109,164],[62,161,169],[197,193,76],[243,154,65],[234,92,65],[201,50,111]]},
 orage:{unit:"niveau",ticks:[0,1,2,3,4,5],
  colors:[[19,35,58],[35,96,157],[62,170,180],[229,198,70],[242,111,53],[190,42,87]]}
};
function kfsProbaClassIndex(amount,type){
 const ticks=KFS_PROBA_SCALE[type].ticks;
 if(!Number.isFinite(amount))return -1;
 for(let i=1;i<ticks.length;i++)if(amount<ticks[i])return i-1;
 return ticks.length-1;
}
function kfsProbaAmountPalette(amount,type){
 const index=kfsProbaClassIndex(amount,type);
 return index<0?[63,77,89]:KFS_PROBA_SCALE[type].colors[index];
}
function kfsProbaRender(features,samples,zone,type,departments=[]){
 const W=900,H=760,P={x:32,y:28,w:836,h:624};
 const rgba=new Uint8Array(W*H*4);
 for(let i=0;i<rgba.length;i+=4){rgba[i]=9;rgba[i+1]=20;rgba[i+2]=38;rgba[i+3]=255;}
 const bbox=zone==="FR"?[-5.8,41.15,10.0,51.65]:(()=>{
  const a=kfsProbaBBox(features),dx=a[2]-a[0],dy=a[3]-a[1];
  return [a[0]-.12*dx,a[1]-.12*dy,a[2]+.12*dx,a[3]+.12*dy];
 })();
 // Projection locale avec conservation du ratio géographique.
 const centerLon=(bbox[0]+bbox[2])/2,centerLat=(bbox[1]+bbox[3])/2;
 const cosLat=Math.cos(centerLat*Math.PI/180);
 const scale=Math.min(P.w/((bbox[2]-bbox[0])*cosLat),P.h/(bbox[3]-bbox[1]));
 const centerX=P.x+P.w/2,centerY=P.y+P.h/2;
 const lonToX=lon=>centerX+(lon-centerLon)*cosLat*scale;
 const latToY=lat=>centerY-(lat-centerLat)*scale;
 const xToLon=x=>centerLon+(x-centerX)/(cosLat*scale);
 const yToLat=y=>centerLat-(y-centerY)/scale;
 const GW=100,GH=82,field=new Float32Array(GW*GH);
 const maxDist=zone==="FR"?3.4:Math.max(.9,(bbox[2]-bbox[0])*.62);
 const valid=samples.filter(s=>Number.isFinite(s.value)&&Number.isFinite(s.amount));
 for(let gy=0;gy<GH;gy++)for(let gx=0;gx<GW;gx++){
  const lon=xToLon(P.x+P.w*gx/(GW-1));
  const lat=yToLat(P.y+P.h*gy/(GH-1));
  let num=0,den=0,nearest=Infinity;
  for(const p of valid){
   const dx=(p.lon-lon)*cosLat,dy=p.lat-lat,d2=dx*dx+dy*dy;
   nearest=Math.min(nearest,Math.sqrt(d2));
   const w=1/(d2+.01);num+=p.amount*w;den+=w;
  }
  field[gy*GW+gx]=(den&&nearest<=maxDist)?num/den:-1;
 }
 function put(x,y,r,g,b){
  if(x<0||y<0||x>=W||y>=H)return;
  const p=(y*W+x)*4;rgba[p]=r;rgba[p+1]=g;rgba[p+2]=b;
 }
 function line(x0,y0,x1,y1,color){
  x0=Math.round(x0);y0=Math.round(y0);x1=Math.round(x1);y1=Math.round(y1);
  let dx=Math.abs(x1-x0),sx=x0<x1?1:-1,dy=-Math.abs(y1-y0),sy=y0<y1?1:-1,err=dx+dy;
  for(let i=0;i<3000;i++){
   put(x0,y0,...color);
   if(x0===x1&&y0===y1)break;
   let e=2*err;
   if(e>=dy){err+=dy;x0+=sx;}
   if(e<=dx){err+=dx;y0+=sy;}
  }
 }
 const rings=features.map(f=>kfsProbaRings(f).map(r=>r.map(c=>[lonToX(c[0]),latToY(c[1])])));
 // Remplissage scanline dans les polygones, pas de couleurs inventées sur la mer.
 for(const rr of rings){
  for(let y=P.y;y<P.y+P.h;y++){
   const cross=[];
   for(const ring of rr)for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const a=ring[i],b=ring[j];
    if((a[1]>y)!==(b[1]>y))cross.push(a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]));
   }
   cross.sort((a,b)=>a-b);
   for(let n=0;n+1<cross.length;n+=2){
    const first=Math.max(P.x,Math.floor(cross[n])),last=Math.min(P.x+P.w-1,Math.ceil(cross[n+1]));
    for(let x=first;x<=last;x++){
     const xx=kfsProbaClamp((x-P.x)/P.w*(GW-1),0,GW-1),
      yy=kfsProbaClamp((y-P.y)/P.h*(GH-1),0,GH-1);
     const x0=Math.floor(xx),y0=Math.floor(yy),x1=Math.min(GW-1,x0+1),y1=Math.min(GH-1,y0+1);
     const fx=xx-x0,fy=yy-y0;
     let v1=field[y0*GW+x0],v2=field[y0*GW+x1],v3=field[y1*GW+x0],v4=field[y1*GW+x1];
     const all=[v1,v2,v3,v4].filter(v=>v>=0);
     const p=all.length===4?((v1*(1-fx)+v2*fx)*(1-fy)+(v3*(1-fx)+v4*fx)*fy):(all.length?all.reduce((a,b)=>a+b,0)/all.length:-1);
     put(x,y,...(p<0?[63,77,89]:kfsProbaAmountPalette(p,type)));
    }
   }
  }
 }
 // Contours départementaux fins ; dessinés sous le contour régional.
 if(zone!=="FR")for(const d of departments)for(const ring of kfsProbaRings(d))
  for(let i=1;i<ring.length;i++)
   line(lonToX(ring[i-1][0]),latToY(ring[i-1][1]),
        lonToX(ring[i][0]),latToY(ring[i][1]),[139,182,211]);
 for(const rr of rings)for(const ring of rr)for(let i=1;i<ring.length;i++){
  line(ring[i-1][0],ring[i-1][1],ring[i][0],ring[i][1],[219,231,241]);
 }
 // Police pixel 5×7, labels intégrés dans l'image pour la lecture sur Discord.
 const glyphs={
  "A":["01110","10001","10001","11111","10001","10001","10001"],
  "B":["11110","10001","10001","11110","10001","10001","11110"],
  "C":["01111","10000","10000","10000","10000","10000","01111"],
  "D":["11110","10001","10001","10001","10001","10001","11110"],
  "E":["11111","10000","10000","11110","10000","10000","11111"],
  "F":["11111","10000","10000","11110","10000","10000","10000"],
  "G":["01111","10000","10000","10111","10001","10001","01110"],
  "H":["10001","10001","10001","11111","10001","10001","10001"],
  "I":["01110","00100","00100","00100","00100","00100","01110"],
  "J":["00111","00010","00010","00010","10010","10010","01100"],
  "K":["10001","10010","10100","11000","10100","10010","10001"],
  "L":["10000","10000","10000","10000","10000","10000","11111"],
  "M":["10001","11011","10101","10101","10001","10001","10001"],
  "N":["10001","11001","10101","10011","10001","10001","10001"],
  "O":["01110","10001","10001","10001","10001","10001","01110"],
  "P":["11110","10001","10001","11110","10000","10000","10000"],
  "Q":["01110","10001","10001","10001","10101","10010","01101"],
  "R":["11110","10001","10001","11110","10100","10010","10001"],
  "S":["01111","10000","10000","01110","00001","00001","11110"],
  "T":["11111","00100","00100","00100","00100","00100","00100"],
  "U":["10001","10001","10001","10001","10001","10001","01110"],
  "V":["10001","10001","10001","10001","10001","01010","00100"],
  "W":["10001","10001","10001","10101","10101","10101","01010"],
  "X":["10001","10001","01010","00100","01010","10001","10001"],
  "Y":["10001","10001","01010","00100","00100","00100","00100"],
  "Z":["11111","00001","00010","00100","01000","10000","11111"],
  " ":["00000","00000","00000","00000","00000","00000","00000"],
  "0":["01110","10001","10011","10101","11001","10001","01110"],
  "1":["00100","01100","00100","00100","00100","00100","01110"],
  "2":["01110","10001","00001","00010","00100","01000","11111"],
  "3":["11110","00001","00001","01110","00001","00001","11110"],
  "4":["00010","00110","01010","10010","11111","00010","00010"],
  "5":["11111","10000","11110","00001","00001","10001","01110"],
  "6":["00110","01000","10000","11110","10001","10001","01110"],
  "7":["11111","00001","00010","00100","01000","01000","01000"],
  "8":["01110","10001","10001","01110","10001","10001","01110"],
  "9":["01110","10001","10001","01111","00001","00010","11100"],
  "%":["11001","11010","00100","01000","10110","00110","00000"],
  ".":["00000","00000","00000","00000","00000","00100","00100"],
  "m":["00000","00000","11010","10101","10101","10101","10101"],
  "c":["00000","00000","01110","10000","10000","10000","01110"],
  "k":["10000","10000","10100","11000","10100","10010","10001"],
  "h":["10000","10000","10110","11001","10001","10001","10001"],
  "/":["00001","00001","00010","00100","01000","10000","10000"],
  "-":["00000","00000","00000","11111","00000","00000","00000"]
 };
 function rect(x,y,w,h,color){
  for(let a=Math.max(0,Math.round(y));a<Math.min(H,y+h);a++)for(let b=Math.max(0,Math.round(x));b<Math.min(W,x+w);b++)put(b,a,...color);
 }
 function txt(str,x,y,scale=2,color=[255,255,255]){
  let px=Math.round(x);
  for(const char of String(str)){
   const rows=glyphs[char];if(!rows){px+=3*scale;continue;}
   for(let yy=0;yy<7;yy++)for(let xx=0;xx<5;xx++)if(rows[yy][xx]==="1")
    rect(px+xx*scale,y+yy*scale,scale,scale,color);
   px+=6*scale;
  }
 }
 // Distribution spatiale homogène des valeurs : premier point au nord,
 // ensuite les points les plus éloignés de ceux déjà retenus.
 // Les points échantillonnés et les appels API restent inchangés (pas de 429 accru).
 const pending=[...valid].sort((a,b)=>b.lat-a.lat||b.value-a.value);
 const ordered=[],marked=[],placedBoxes=[];
 if(pending.length)ordered.push(pending.shift());
 while(pending.length){
  let best=0,bestScore=-Infinity;
  for(let i=0;i<pending.length;i++){
   const p=pending[i],x=lonToX(p.lon),y=latToY(p.lat);
   const nearest=Math.min(...ordered.map(q=>Math.hypot(lonToX(q.lon)-x,latToY(q.lat)-y)));
   const score=nearest+p.value*.025;
   if(score>bestScore){bestScore=score;best=i;}
  }
  ordered.push(pending.splice(best,1)[0]);
 }
 // Préserver les emplacements des villes sans modifier leur rendu.
 // Sur les petites régions, réduire la densité des étiquettes météo.
 const cityGuardRadius=zone==="28"?50:(zone==="24"||zone==="32"?0:40);
 const cityAnchors=(KFS_PROBA_CITIES[zone]||[]).map(([,lon,lat])=>({x:lonToX(lon),y:latToY(lat)}));
 const maxMarks=zone==="FR"?12:(zone==="24"?5:zone==="94"?6:zone==="11"?7:10);
 for(const p of ordered){
  const x=lonToX(p.lon),y=latToY(p.lat);
  if(!Number.isFinite(x)||!Number.isFinite(y))continue;
  if(cityGuardRadius>0&&cityAnchors.some(q=>
     Math.abs(q.x-x)<cityGuardRadius&&Math.abs(q.y-y)<cityGuardRadius*.7))continue;
  const score=Math.round(p.value),unit=KFS_PROBA_SCALE[type].unit;
  const qty=type==="orage"?KFS_STORM_NAMES[kfsProbaClassIndex(p.amount,"orage")]:
   (type==="vent"?Math.round(p.amount):Math.round(p.amount*10)/10)+unit;
  const proba=score+"%",lw=Math.max(proba.length,qty.length)*12+14,h=39;
  const candidates=[[x-lw/2,y-22],[x-lw/2,y+10],[x-lw/2,y-52],
    [x+12,y-22],[x-lw-12,y-22]];
  let chosen=null;
  for(const [xx,yy] of candidates){
   const bx=Math.round(kfsProbaClamp(xx,P.x+2,P.x+P.w-lw-3));
   const by=Math.round(kfsProbaClamp(yy,P.y+2,P.y+P.h-h-3));
   if(placedBoxes.some(q=>!(bx+lw+8<q.x||bx>q.x+q.w+8||by+h+8<q.y||by>q.y+q.h+8)))continue;
   chosen={x:bx,y:by,w:lw,h};break;
  }
  if(!chosen)continue;
  placedBoxes.push(chosen);
  marked.push({x,y});
  rect(chosen.x-1,chosen.y-1,lw+2,h,[228,241,252]);
  rect(chosen.x,chosen.y,lw,h-2,[10,29,50]);
  txt(proba,chosen.x+7,chosen.y+3,2,score>=50?[255,225,133]:[255,255,255]);
  txt(qty,chosen.x+7,chosen.y+21,2,[134,220,255]);
  if(marked.length>=maxMarks)break;
 }
 // Grandes villes : marqueurs géoréférencés, noms non superposés aux chiffres.
 if(zone!=="FR"){
  const boxes=[];
  for(const [name,lon,lat] of (KFS_PROBA_CITIES[zone]||[])){
   if(!features.some(f=>kfsProbaInFeature(lon,lat,f)))continue;
   const x=lonToX(lon),y=latToY(lat);
   if(x<P.x||x>P.x+P.w||y<P.y||y>P.y+P.h)continue;
   rect(Math.round(x)-2,Math.round(y)-2,5,5,[10,27,46]);
   rect(Math.round(x)-1,Math.round(y)-1,3,3,[252,253,255]);
   const label=name.normalize("NFD").replace(/[\u0300-\u036f]/g,"").toUpperCase();
   const lw=label.length*12+10,lh=21;
   const positions=[[x+9,y-9],[x-lw-9,y-9],[x-lw/2,y-27],[x-lw/2,y+8],[x+9,y+11],[x-lw-9,y+11]];
   for(const [xx,yy] of positions){
    const bx=Math.round(xx),by=Math.round(yy);
    if(bx<P.x||by<P.y||bx+lw>P.x+P.w||by+lh>P.y+P.h)continue;
    if(marked.some(q=>Math.abs(q.x-(bx+lw/2))<lw/2+57&&Math.abs(q.y-(by+lh/2))<lh/2+26))continue;
    if(boxes.some(q=>!(bx+lw+4<q.x||bx>q.x+q.w+4||by+lh+4<q.y||by>q.y+q.h+4)))continue;
    rect(bx,by,lw,lh,[9,25,43]);
    txt(label,bx+5,by+4,2,[244,249,255]);
    boxes.push({x:bx,y:by,w:lw,h:lh});
    break;
   }
  }
 }
 // Légende en classes de quantité, réparties en bandes de même largeur.
 const legend=KFS_PROBA_SCALE[type],ly=679,left=64,right=834;
 const names=type==="orage"?KFS_STORM_NAMES:
  legend.ticks.map((start,i)=>{
   const end=legend.ticks[i+1];
   return end===undefined?String(start)+"+":String(start)+"-"+String(end);
  });
 const width=(right-left)/names.length;
 for(let i=0;i<names.length;i++){
  const l=Math.round(left+i*width),r=Math.round(left+(i+1)*width);
  const color=legend.colors[i];
  for(let x=l;x<r;x++)for(let y=ly;y<ly+18;y++)put(x,y,...color);
  for(let y=ly-3;y<ly+22;y++)put(l,y,246,250,254);
  txt(names[i],Math.round((l+r-names[i].length*12)/2),710,2,[241,246,250]);
 }
 for(let y=ly-3;y<ly+22;y++)put(right,y,246,250,254);
 if(type!=="orage")txt(legend.unit,right-legend.unit.length*12,738,2,[197,228,249]);
 return {rgba,W,H};
}
function kfsProbaCrc(a){
 let c=-1;
 for(const b of a){c^=b;for(let k=0;k<8;k++)c=c&1?(c>>>1)^0xedb88320:c>>>1;}
 return (c^(-1))>>>0;
}
function kfsProbaUint32(n){return new Uint8Array([(n>>>24)&255,(n>>>16)&255,(n>>>8)&255,n&255]);}
function kfsProbaChunk(type,data){
 const t=new TextEncoder().encode(type),c=new Uint8Array(t.length+data.length);
 c.set(t);c.set(data,t.length);
 const out=new Uint8Array(12+data.length);
 out.set(kfsProbaUint32(data.length));out.set(c,4);out.set(kfsProbaUint32(kfsProbaCrc(c)),8+data.length);
 return out;
}
async function kfsProbaPng(frame){
 const {rgba,W,H}=frame;
 const raw=new Uint8Array(H*(W*4+1));
 for(let y=0;y<H;y++)raw.set(rgba.subarray(y*W*4,(y+1)*W*4),y*(W*4+1)+1);
 const c=new CompressionStream("deflate");
 const stream=new Blob([raw]).stream().pipeThrough(c);
 const compressed=new Uint8Array(await new Response(stream).arrayBuffer());
 const hdr=new Uint8Array(13);hdr.set(kfsProbaUint32(W),0);hdr.set(kfsProbaUint32(H),4);hdr[8]=8;hdr[9]=6;
 const chunks=[new Uint8Array([137,80,78,71,13,10,26,10]),kfsProbaChunk("IHDR",hdr),kfsProbaChunk("IDAT",compressed),kfsProbaChunk("IEND",new Uint8Array())];
 const size=chunks.reduce((a,b)=>a+b.length,0),res=new Uint8Array(size);
 let pos=0;for(const chunk of chunks){res.set(chunk,pos);pos+=chunk.length;}
 return res;
}
async function kfsProbaComplete(interaction,phenom,zone,jour,seuil){
 try{
  const rules=KFS_PROBA_RULES[phenom];
  if(!rules||![0,1,2,3].includes(jour)||!rules.allowed.includes(seuil))throw Error(
   "Paramètres invalides. Seuils autorisés : neige 1/3/5/10 cm, pluie 0,1/1/5/10/20/40 mm, rafales 60/80/100/120 km/h."
  );
  const all=await kfsProbaFeatures(),features=zone==="FR"?all:all.filter(f=>String(f.properties.code)===zone);
  if(!features.length)throw Error("Région non reconnue.");
  const departmentsPromise=zone==="FR"?Promise.resolve([]):kfsProbaDepartments(zone).catch(e=>{
   console.error("KFS_PROBA_DEPARTMENTS",String(e));return [];
  });
  const points=kfsProbaSamples(features,zone!=="FR");
  if(points.length<2)throw Error("Échantillonnage spatial insuffisant.");
  const day=kfsProbaDay(jour),available=[],failures=[];
  // Quatre familles variées maximum par carte, deux appels simultanés
  // (Open-Meteo limite la concurrence et facture les coordonnées).
  const selected=[KFS_PROBA_MODELS[0],KFS_PROBA_MODELS[2],
    KFS_PROBA_MODELS[1],KFS_PROBA_MODELS[4]];
  const requestDeadline=Date.now()+24000;
  for(let offset=0;offset<selected.length;offset+=2){
   if(Date.now()>requestDeadline-2500)break;
   const batch=selected.slice(offset,offset+2);
   const settled=await Promise.allSettled(batch.map(m=>phenom==="orage"?
    kfsProbaStormModel(m,points,day,seuil):kfsProbaModel(m,points,day,phenom,seuil)));
   for(let j=0;j<settled.length;j++){
    const outcome=settled[j],model=batch[j];
   if(outcome.status==="rejected"){
    failures.push(model[0]+" : "+String(outcome.reason).slice(0,80));
    continue;
   }
   const r=outcome.value;
   let count=0;
   for(let i=0;i<points.length;i++){
    const v=r.values[i];
    if(v){points[i].models.push(v.pct);(points[i].amountModels ||= []).push(v.amount);
    if(Number.isFinite(v.wetPct))(points[i].wetModels ||= []).push(v.wetPct);
    if(Number.isFinite(v.stormPct))(points[i].stormModels ||= []).push(v.stormPct);
    count++;}
   }
   if(count)available.push(r.name);
   else failures.push(r.name+" : variable indisponible");
   }
   if(failures.some(x=>/Daily API request limit exceeded|quota quotidien Open-Meteo/i.test(x)))break;
  }
  for(const p of points){if(p.models.length)p.value=p.models.reduce((a,b)=>a+b,0)/p.models.length;if(p.amountModels?.length)p.amount=p.amountModels.reduce((a,b)=>a+b,0)/p.amountModels.length;if(p.wetModels?.length)p.wetValue=p.wetModels.reduce((a,b)=>a+b,0)/p.wetModels.length;
   if(p.stormModels?.length)p.stormValue=p.stormModels.reduce((a,b)=>a+b,0)/p.stormModels.length;}
  const counted=points.filter(p=>Number.isFinite(p.value));
  if(!counted.length)throw Error("Aucun ensemble disponible pour cette prévision. "+
   (failures.some(x=>x.includes("429"))?"Le fournisseur renvoie HTTP 429 (quota temporaire).":"Modèles sans données ou trop lents.")+
   " Détail : "+failures.slice(0,2).join(" ; ").slice(0,250));
  const departments=await departmentsPromise;
  const frame=kfsProbaRender(features,points,zone,phenom,departments),png=await kfsProbaPng(frame);
  const name=zone==="FR"?"France métropolitaine":KFS_PROBA_REGIONS.find(r=>r[0]===zone)?.[1]||zone;
  const label=phenom==="orage"?"potentiel orageux au moins "+KFS_STORM_NAMES[seuil].toLowerCase():
    phenom==="neige"?"épaisseur de neige présente au sol ≥ "+seuil+" cm":
   phenom==="pluie"?"cumul de pluie ≥ "+seuil+" mm sur le jour":
   "rafale maximale ≥ "+seuil+" km/h sur le jour";
  const values=counted.map(p=>p.value);
  const amounts=counted.map(p=>p.amount).filter(Number.isFinite);
  const unit=KFS_PROBA_SCALE[phenom].unit;
  const minAmount=amounts.length?Math.min(...amounts):null,maxAmount=amounts.length?Math.max(...amounts):null;
  const min=Math.round(Math.min(...values)),max=Math.round(Math.max(...values));
  const stormValues=counted.map(p=>p.stormValue).filter(Number.isFinite);
  const stormRange=phenom==="orage"&&stormValues.length?
   "⚡ **Probabilité d'un signal orageux (≥ faible) :** "+Math.round(Math.min(...stormValues))+
   " à "+Math.round(Math.max(...stormValues))+" % sur les points étudiés.\n":"";
  const wetValues=counted.map(p=>p.wetValue).filter(Number.isFinite);
  const wetRange=phenom==="pluie"&&seuil>0.1&&wetValues.length?
   "🌦️ **Risque d’avoir de la pluie (≥ 0,1 mm) :** "+Math.round(Math.min(...wetValues))+" à "+Math.round(Math.max(...wetValues))+" % aux points étudiés.\n":"";
  const caution=phenom==="pluie"&&seuil>=10?
   "💡 Une probabilité faible pour ≥ "+seuil+" mm n'exclut pas une journée avec des pluies faibles ou des averses.\n":"";

  const content="**KFS MÉTÉO · /proba · "+name+" · J+"+jour+" ("+day+")**\n"+
   "**Événement :** "+label+"\n"+
   "🗺️ **Probabilité estimée :** "+min+" à "+max+" % sur les points échantillonnés.\n"+
   "📊 **Modèles exploités :** "+available.join(", ")+" ("+available.length+" familles).\n"+
   (phenom==="orage"?
     "**Carte :** couleurs = catégorie moyenne indicative de potentiel convectif ; blanc = proportion des membres atteignant le niveau demandé ; bleu = niveau moyen.\n":
     "**Carte :** couleurs = quantité moyenne (en "+unit+") ; chiffre blanc = probabilité d’atteindre le seuil ; chiffre bleu = quantité moyenne.\n")+
   (phenom==="orage"?"**Échelle orage :** aucun · faible · moyen · modéré · fort · extrême.\n":
     "**Échelle des quantités (classes) :** "+KFS_PROBA_SCALE[phenom].ticks.map((v,i,arr)=>i===arr.length-1?v+" et +":v+"-"+arr[i+1]).join(" · ")+" "+unit+".\n")+
   (zone!=="FR"?"**Repères :** limites départementales et grandes villes.\n":"")+
   (minAmount!==null?(phenom==="orage"?
      "**Indice convectif moyen :** "+minAmount.toFixed(1)+" à "+maxAmount.toFixed(1)+" / 5.\n":
      "**Quantité moyenne :** "+(Math.round(minAmount*10)/10)+" à "+(Math.round(maxAmount*10)/10)+" "+unit+" sur les points étudiés.\n"):"")+
     stormRange+wetRange+caution+
   (phenom==="neige"?"🏔️ Les points situés au-dessus de 800 m sont écartés ; neige au sol modélisée, pas chute fraîche.\n":"")+
   (phenom==="orage"?"⚠️ **Indice orageux expérimental**, fondé sur CAPE, pluie, rafales et codes météo disponibles. Fort/extrême = potentiel convectif, pas prévision certaine de grêle, tornade ou rafales destructrices. **Aucune équivalence avec la vigilance Météo-France.**\n":"")+
   "ℹ️ Estimation **non calibrée**, issue des proportions de membres (poids égal par modèle), et non une probabilité officielle de vigilance. "+
   "Échantillonnage régional : ne remplace pas une prévision locale fine.\n"+
   "_Sources : ensembles Open-Meteo ; contours IGN/INSEE. Données consultées le "+new Date().toISOString().slice(0,16).replace("T"," ")+" UTC._";
  try{await kfsProbaEdit(interaction,{content,allowed_mentions:{parse:[]}},png);}
  catch(e){
   console.error("KFS_PROBA_IMAGE_UPLOAD",String(e));
   await kfsProbaEdit(interaction,{
    content:content+"\n⚠️ Carte non jointe : Discord a refusé l'image. "+String(e.message||e).slice(0,150),
    allowed_mentions:{parse:[]}
   });
  }
 }catch(e){
  console.error("KFS_PROBA_ERROR",String(e));
  try{await kfsProbaEdit(interaction,{content:"⚠️ /proba : "+String(e.message||e).slice(0,1500),allowed_mentions:{parse:[]}});}
  catch(err){console.error("KFS_PROBA_DISCORD_ERROR",String(err));}
 }
}
