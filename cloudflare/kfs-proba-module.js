// KFS /proba — prévisions multi-ensembles, J+0 à J+3 et cinq jours cumulés, France / régions.
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
 neige_chutes:{unit:"mm équiv.-eau",defaults:0.1,allowed:[0.1,1,3,5],variable:"snowfall",title:"Précipitations sous forme de neige"},
 pluie:{unit:"mm / 24 h",defaults:1,allowed:[0.1,1,5,10,20,40],variable:"rain",title:"Cumul de pluie"},
 gel:{unit:"°C",defaults:0,allowed:[0,-2,-5,-10],variable:"temperature_2m",title:"Température minimale à 2 m"},
 vent:{unit:"km/h",defaults:90,allowed:[54,60,80,90,100,120],variable:"wind_gusts_10m",title:"Rafales maximales"},
 orage:{unit:"niveau",defaults:2,allowed:[1,2,3,4,5],variable:"cape",title:"Potentiel orageux"}
};
let KFS_PROBA_LAST_REGISTER=0;
async function kfsProbaRegister(env){
 if(!env.DISCORD_BOT_TOKEN)throw Error("Jeton Discord absent");
 const cmd={name:"proba",type:1,description:"Probabilités météo par jour ou sur 5 jours cumulés",options:[
  {name:"phenomene",type:3,description:"Pluie, neige, gelées, rafales et orages",required:true,
   choices:[{name:"🌨️ Neige au sol",value:"neige"},
    {name:"❄️ Précipitations neigeuses (même sans tenue)",value:"neige_chutes"},
    {name:"🌧️ Pluie",value:"pluie"},{name:"🥶 Gelées (Tmin 2 m)",value:"gel"},{name:"💨 Rafales",value:"vent"},{name:"🌩️ Orages",value:"orage"}]},
  {name:"zone",type:3,description:"France entière ou région",required:false,
   choices:[{name:"France métropolitaine",value:"FR"},...KFS_PROBA_REGIONS.map(([code,name])=>({name,value:code}))]},
  {name:"jour",type:4,description:"Une journée ou cinq jours cumulés (J+1 à J+5)",required:false,
   choices:[...[0,1,2,3].map(i=>({name:"J+"+i,value:i})),
    {name:"5 jours cumulés (J+1 à J+5)",value:5}]},
  {name:"seuil",type:10,description:"Gel 0/-2/-5/-10°C · neige 1/3/5/10cm · neige fraîche · pluie · vent",required:false,min_value:-10,max_value:120},
  {name:"niveau",type:3,description:"Orages : niveau minimum à évaluer (défaut : moyen)",required:false,
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
function kfsProbaMemberProbability(hourly,day,type,threshold,endDay=day){
 if(!hourly?.time?.length)return null;
 const ids=[];
 for(let i=0;i<hourly.time.length;i++)if(String(hourly.time[i]).slice(0,10)>=day && String(hourly.time[i]).slice(0,10)<=endDay)ids.push(i);
 if(!ids.length || (endDay!==day&&!kfsProbaPeriodComplete(hourly.time,ids,day,endDay,1)))return null;
 let pass=0,valid=0,anyRain=0,amountSum=0;
 const keys=Object.keys(hourly).filter(k=>k.startsWith(KFS_PROBA_RULES[type].variable+"_")&&/member\d+/.test(k));
 for(const key of keys){
  const arr=hourly[key];if(!Array.isArray(arr))continue;
  const nums=ids.map(i=>arr[i]).filter(v=>typeof v==="number"&&Number.isFinite(v));
  if(nums.length<(endDay!==day?ids.length:Math.ceil(ids.length*0.85)))continue;
  const amount=type==="pluie"?Math.max(0,nums.reduce((a,b)=>a+b,0)):
   // Open-Meteo 'snowfall' est un cumul horaire de neige fraiche en cm.
   // 7 cm = 10 mm eau selon sa documentation ; ne pas confondre avec neige au sol.
   type==="neige_chutes"?Math.max(0,nums.reduce((a,b)=>a+b,0))*10/7:
   type==="vent"?Math.max(0,...nums):type==="gel"?Math.min(...nums):Math.max(0,...nums)*100;
  if(!Number.isFinite(amount))continue;
  valid++;amountSum+=amount;
  if(type==="gel"?amount<=threshold:amount>=threshold)pass++;
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
function kfsProbaStormTier(cape,rain,gust,weatherCode,cin,dewpoint){
 // Indice NON calibre. Deux signaux : convection prevue et environnement favorable.
 const thunder=[95,96,99].includes(weatherCode);
 const cp=Number.isFinite(cape)?cape:null;
 const pr=Number.isFinite(rain)?rain:null;
 const gu=Number.isFinite(gust)?gust:null;
 const td=Number.isFinite(dewpoint)?dewpoint:null;
 const inhibition=Number.isFinite(cin)?cin:null;
 if(cp===null&&!thunder)return 0;
 const moist=td!==null&&td>=8;
 const capOpen=inhibition===null||inhibition>-125;
 let level=thunder?1:0;
 if(cp!==null){
  // La CAPE + l'humidite peuvent signaler un risque AVANT les pluies prevues.
  if((cp>=100&&pr!==null&&pr>=0.1)||(cp>=225&&moist&&capOpen))
   level=Math.max(level,1);
  if((cp>=300&&pr!==null&&pr>=0.25)||(cp>=500&&moist&&capOpen))
   level=Math.max(level,2);
  // Modere exige une precipitation modelisee, pas seulement de la CAPE.
  if(cp>=650&&pr!==null&&pr>=0.7&&((gu!==null&&gu>=30)||moist))
   level=Math.max(level,3);
  if(cp>=950&&pr!==null&&pr>=1&&gu!==null&&gu>=35)
   level=Math.max(level,3);
  // Niveaux fort et extreme : criteres combines stricts.
  if(cp>=1500&&pr!==null&&pr>=2&&gu!==null&&gu>=55)
   level=Math.max(level,4);
  if(cp>=2800&&pr!==null&&pr>=4&&gu!==null&&gu>=85)
   level=Math.max(level,5);
 }
 // Un CIN absent n'est pas traite comme nul.
 if(!thunder&&inhibition!==null&&inhibition<=-200)
  level=Math.max(0,level-1);
 return level;
}
function kfsProbaStormMembers(hourly,day,minimum,endDay=day){
 if(!Array.isArray(hourly?.time))return null;
 const ids=[];
 for(let i=0;i<hourly.time.length;i++)if(String(hourly.time[i]).slice(0,10)>=day && String(hourly.time[i]).slice(0,10)<=endDay)ids.push(i);
 if(ids.length<3 || (endDay!==day&&!kfsProbaPeriodComplete(hourly.time,ids,day,endDay)))return null;
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
     get("wind_gusts_10m",i),wc,get("convective_inhibition",i),get("dew_point_2m",i));
   level=Math.max(level,l);
  }
  if(observed<(endDay!==day?ids.length:Math.ceil(ids.length*.6)))continue;
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

async function kfsProbaStormModel(model,samples,day,minimum,endDay=day){
 const base={latitude:samples.map(p=>p.lat).join(","),
  longitude:samples.map(p=>p.lon).join(","),models:model[1],
  start_date:endDay===day?day:kfsProbaShiftDay(day,-1),
  end_date:endDay===day?day:kfsProbaShiftDay(endDay,1),timeformat:endDay===day?"iso8601":"unixtime",timezone:"Europe/Paris",temporal_resolution:KFS_STORM_TEMPO};
 const variants=[
  ["cape","precipitation","wind_gusts_10m","weather_code","dew_point_2m","convective_inhibition"],
  ["cape","precipitation","wind_gusts_10m","weather_code","dew_point_2m"],
  ["cape","precipitation","wind_gusts_10m"]
 ];
 const deadline=Date.now()+14000;
 let error="";
 for(const fields of variants){
  const left=Math.min(8000,deadline-Date.now());
  if(left<1500)break;
  const params=new URLSearchParams({...base,hourly:fields.join(",")});
  try{
   const data0=await kfsProbaReadEnsemble(params),data=Array.isArray(data0)?data0:[data0];
   if(data.length!==samples.length){error="Nombre de points inattendu";continue;}
   const values=data.map(x=>kfsProbaStormMembers(kfsProbaNormalizeHourly(x.hourly),day,minimum,endDay));
   if(values.some(Boolean))return {name:model[0],values,fields};
   error="Aucun membre valide";
  }catch(e){
   error=String(e.message||e).slice(0,120);
   if(/HTTP 429|HTTP 5\d\d/i.test(error))break;
  }
 }
 throw Error("Orage "+model[0]+": "+error);
}
async function kfsProbaModel(model,samples,day,type,threshold,endDay=day){
 const varName=KFS_PROBA_RULES[type].variable;
 const params=new URLSearchParams({
  latitude:samples.map(p=>p.lat).join(","),
  longitude:samples.map(p=>p.lon).join(","),
  models:model[1],hourly:varName,start_date:endDay===day?day:kfsProbaShiftDay(day,-1),
  end_date:endDay===day?day:kfsProbaShiftDay(endDay,1),timeformat:endDay===day?"iso8601":"unixtime",
  timezone:"Europe/Paris",temporal_resolution:"hourly_1"
 });
 const result=await kfsProbaReadEnsemble(params);
 const arr=Array.isArray(result)?result:[result];
 if(arr.length!==samples.length)throw Error("Nombre de points inattendu");
 const values=arr.map(p=>{
  if(endDay===day&&type==="neige"&&typeof p.elevation==="number"&&p.elevation>800)return null;
  return kfsProbaMemberProbability(kfsProbaNormalizeHourly(p.hourly),day,type,threshold,endDay);
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
 neige_chutes:{unit:"mm équiv.-eau",ticks:[0,0.1,0.5,1,3,5,10],
  colors:[[26,48,76],[43,89,147],[61,139,192],[103,195,225],[143,177,228],[154,126,216],[211,83,190]]},
 gel:{unit:"°C",ticks:[-15,-10,-7,-5,-3,-1,0,3],
  colors:[[91,41,128],[82,69,164],[57,105,183],[57,142,204],[69,179,208],[98,198,196],[153,188,179],[200,188,148]]},
 vent:{unit:"km/h",ticks:[0,30,50,70,90,110,130],
  colors:[[24,53,90],[45,109,164],[62,161,169],[197,193,76],[243,154,65],[234,92,65],[201,50,111]]},
 orage:{unit:"niveau",ticks:[0,1,2,3,4,5],
  colors:[[19,35,58],[35,96,157],[62,170,180],[229,198,70],[242,111,53],[190,42,87]]},
 probabilite:{unit:"%",ticks:[0,10,25,40,60,80,100],
  colors:[[23,54,94],[36,116,173],[56,180,201],[206,208,88],[248,168,58],[231,78,67],[174,32,90]]}
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
  field[gy*GW+gx]=(den&&nearest<=maxDist)?num/den:NaN;
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
     const all=[v1,v2,v3,v4].filter(Number.isFinite);
     const p=all.length===4?((v1*(1-fx)+v2*fx)*(1-fy)+(v3*(1-fx)+v4*fx)*fy):(all.length?all.reduce((a,b)=>a+b,0)/all.length:NaN);
     put(x,y,...(!Number.isFinite(p)?[63,77,89]:kfsProbaAmountPalette(p,type)));
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
  "-":["00000","00000","00000","11111","00000","00000","00000"],
  "+":["00000","00100","00100","11111","00100","00100","00000"],
  "°":["01100","10010","01100","00000","00000","00000","00000"]
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
  const qty=type==="probabilite"?"":type==="orage"?KFS_STORM_NAMES[kfsProbaClassIndex(p.amount,"orage")]:
   (type==="vent"?Math.round(p.amount):Math.round(p.amount*10)/10)+unit;
  const proba=score+"%",lw=Math.max(proba.length,qty.length)*12+14,h=type==="probabilite"?23:39;
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
  if(type!=="probabilite")txt(qty,chosen.x+7,chosen.y+21,2,[134,220,255]);
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
   return end===undefined?(type==="probabilite"?"100":String(start)+"+"):String(start)+(type==="gel"?"/":"-")+String(end);
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
// ECMWF Open Data : probabilities already calculated by the real IFS ENS.
// No quota Open-Meteo, no on-demand large GRIB downloads. GitHub Action
// precomputes them from type=ep products and publishes a compact JSON.
const KFS_PROBA_ECMWF_FIELDS={
 pluie:{"1":"tpg1","5":"tpg5","10":"tpg10","20":"tpg20"},
 vent:{"54":"10fgg15","90":"10fgg25"}
};
async function kfsProbaEcmwfRead(type,threshold,zone,day,points){
 const field=KFS_PROBA_ECMWF_FIELDS[type]?.[String(threshold)];
 if(!field)return null;
 const urls=[
  "https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/proba/ecmwf-probabilities.json",
  "https://almet27.github.io/kfs-meteo-cartes/proba/ecmwf-probabilities.json"
 ];
 try{
  let j=null;
  for(const url of urls){
   try{
    const resp=await fetch(url,{signal:AbortSignal.timeout(3500),
     headers:{accept:"application/json"},cf:{cacheTtl:900,cacheEverything:true}});
    if(!resp.ok)continue;
    j=await resp.json();
    if(j&&j.schema===1)break;
   }catch(e){console.error("KFS_PROBA_ECMWF_SOURCE",String(e).slice(0,140));}
  }
  if(!j)throw Error("Aucun fichier ECMWF publié disponible.");
  if(j.schema!==1||j.provider!=="ECMWF IFS ENS Open Data")throw Error("Fichier ECMWF mal formé.");
  const age=Date.now()-Date.parse(j.run_utc);
  if(!Number.isFinite(age)||age<0||age>48*3600000)throw Error("Run ECMWF trop ancien (>48h).");
  const d=j.days?.[day],vals=d?.fields?.[field]?.[zone];
  if(!Array.isArray(vals)||vals.length!==points.length)
   throw Error("Carte ECMWF absente pour cette échéance ou cette région.");
  if(vals.some(v=>!Number.isFinite(v)||v<0||v>100))
   throw Error("Données de probabilité ECMWF invalides.");
  if(j.zone_point_counts?.[zone]!==points.length)
   throw Error("Échantillonnage des points ECMWF incompatible.");
  return {source:"ECMWF",field,values:vals,run:j.run_utc,period_start:d.valid_from_utc,
   period_end:d.valid_to_utc,age_hours:Math.round(age/3600000)};
 }catch(e){console.error("KFS_PROBA_ECMWF_OPEN",String(e));return null;}
}

// Expérimental : fraction de 8 membres IFS-ENS, générée hors Open-Meteo.
// Sans fichier valide, ne jamais inventer une carte.
const KFS_PROBA_ECMWF_SUBSET_FIELDS={
 neige:{"1":"snow1","3":"snow3","5":"snow5","10":"snow10"},
 pluie:{"0.1":"rain_liquid0p1","1":"rain_liquid1","5":"rain_liquid5",
        "10":"rain_liquid10","20":"rain_liquid20","40":"rain_liquid40"},
 neige_chutes:{"0.1":"snowfall0p1","1":"snowfall1","3":"snowfall3","5":"snowfall5"},
 orage:{"1":"storm1","2":"storm2","3":"storm3","4":"storm4","5":"storm5"}
};
async function kfsProbaEcmwfSubsetRead(type,threshold,zone,day,points){
 const field=KFS_PROBA_ECMWF_SUBSET_FIELDS[type]?.[String(threshold)];
 if(!field)return null;
 const urls=[
  "https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/proba/ecmwf-subset-probabilities.json",
  "https://almet27.github.io/kfs-meteo-cartes/proba/ecmwf-subset-probabilities.json"
 ];
 try{
  let j=null;
  for(const url of urls){
   try{
    const resp=await fetch(url,{signal:AbortSignal.timeout(3000),headers:{accept:"application/json"},
     cf:{cacheTtl:900,cacheEverything:true}});
    if(!resp.ok)continue;
    j=await resp.json();
    if(j?.schema===1)break;
   }catch(e){console.error("KFS_PROBA_SUBSET_SOURCE",String(e).slice(0,150));}
  }
  if(!j||j.provider!=="ECMWF IFS ENS 8-member subset"||j.ensemble_members?.length!==8)
   throw Error("Fichier ECMWF ENS 8 membres indisponible.");
  const age=Date.now()-Date.parse(j.run_utc);
  if(!Number.isFinite(age)||age<0||age>48*3600000)
   throw Error("Run ECMWF ENS échantillonné trop ancien.");
  const d=j.days?.[day],pct=d?.fields?.[field]?.[zone];
  const meanKey=type==="neige"?"snow_mean_cm":type==="neige_chutes"?"snowfall_mean_mmwe":type==="pluie"?"rain_liquid_mean_mm":"storm_mean_level";
  const amounts=d?.fields?.[meanKey]?.[zone];
  if(!Array.isArray(pct)||pct.length!==points.length||!Array.isArray(amounts)||
    amounts.length!==points.length||j.zone_point_counts?.[zone]!==points.length)
   throw Error("Points ECMWF ENS incomplets.");
  if(pct.some(v=>!Number.isFinite(v)||v<0||v>100)||amounts.some(v=>!Number.isFinite(v)||v<0))
   throw Error("Probabilités/quantités expérimentales invalides ou incomplètes.");
  // Optional synoptic diagnostics: missing fields are never treated as zero.
  const optional=(key,max)=>{
   const arr=d?.fields?.[key]?.[zone];
   return Array.isArray(arr)&&arr.length===points.length&&
    arr.every(x=>x===null||(Number.isFinite(x)&&x>=0&&x<=max))&&
    arr.some(Number.isFinite)?arr:null;
  };
  const diagnostics=type==="orage"?{
   organized:optional("storm_organized_pct",100),
   ascent:optional("storm_ascent_support_pct",100),
   shear:optional("shear_850_500_mean_ms",150)
  }:null;
  const stormTrend=type==="orage"?Object.keys(j.days).sort().map(date=>{
   const fieldSet=j.days[date]?.fields||{};
   const maxField=key=>{
    const a=fieldSet[key]?.[zone];
    return Array.isArray(a)&&a.length===points.length&&
      a.every(v=>Number.isFinite(v)&&v>=0&&v<=100)?Math.max(...a):null;
   };
   return {date,requested:maxField(field),weak:maxField("storm1")};
  }).filter(x=>x.requested!==null&&x.weak!==null):null;  return {source:"ECMWF-8",values:pct,amounts,run:j.run_utc,diagnostics,stormTrend,
    members:j.ensemble_members.length,period_start:d.valid_from_utc,period_end:d.valid_to_utc};
 }catch(e){console.error("KFS_PROBA_ECMWF_SUBSET",String(e));return null;}
}

// Cumuls ECMWF réels, calculés indépendamment sur 8 membres IFS ENS.
// Les % officiels restent issus du produit ENS complet (type=ep).
async function kfsProbaEcmwfRainMeanRead(zone,day,points,run,validFrom,validTo){
 const urls=[
  "https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/proba/ecmwf-subset-probabilities.json",
  "https://almet27.github.io/kfs-meteo-cartes/proba/ecmwf-subset-probabilities.json"
 ];
 for(const url of urls){
  try{
   const r=await fetch(url,{signal:AbortSignal.timeout(3500),
    headers:{accept:"application/json"},cf:{cacheTtl:900,cacheEverything:true}});
   if(!r.ok)continue;
   const j=await r.json(),d=j?.days?.[day],values=d?.fields?.rain_mean_mm?.[zone];
   if(j?.schema!==1||j.provider!=="ECMWF IFS ENS 8-member subset"||
     j.run_utc!==run||j.ensemble_members?.length!==8||j.zone_point_counts?.[zone]!==points.length||
     d?.valid_from_utc!==validFrom||d?.valid_to_utc!==validTo||
     !Array.isArray(values)||values.length!==points.length||
     values.some(v=>!Number.isFinite(v)||v<0||v>500)){
    console.error("KFS_PROBA_RAIN_MEAN_REJECT","absent, incompatible ou d'un autre run",url);
    continue;
   }
   return {values,members:8,run};
  }catch(e){console.error("KFS_PROBA_RAIN_MEAN_SOURCE",String(e).slice(0,160));}
 }
 return null;
}

// ECMWF IFS ENS: native minimum temperature over eight consecutive 3-hour UTC windows.
// The GitHub Actions dataset avoids /proba gel requests to Open-Meteo.
async function kfsProbaEcmwfFrostRead(threshold,zone,day,points){
 const field="frost"+Math.abs(threshold);
 if(!["frost0","frost2","frost5","frost10"].includes(field))return null;
 const urls=[
  "https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/proba/ecmwf-frost-probabilities.json",
  "https://almet27.github.io/kfs-meteo-cartes/proba/ecmwf-frost-probabilities.json"
 ];
 for(const url of urls){
  try{
   const resp=await fetch(url,{signal:AbortSignal.timeout(3500),
    headers:{accept:"application/json"},cf:{cacheTtl:900,cacheEverything:true}});
   if(!resp.ok)continue;
   const j=await resp.json(),d=j?.days?.[day];
   if(j?.schema!==1||j?.provider!=="ECMWF IFS ENS 8-member frost subset"||
    j?.ensemble_members?.length!==8||j?.sampling_interval_hours!==3||
    j?.zone_point_counts?.[zone]!==points.length)continue;
   const age=Date.now()-Date.parse(j.run_utc);
   if(!Number.isFinite(age)||age<0||age>48*3600000)continue;
   const values=d?.fields?.[field]?.[zone],amounts=d?.fields?.frost_mean_c?.[zone];
   if(!Array.isArray(values)||!Array.isArray(amounts)||
    values.length!==points.length||amounts.length!==points.length||
    values.some(v=>!Number.isFinite(v)||v<0||v>100)||
    amounts.some(v=>!Number.isFinite(v)||v< -90||v>60))continue;
   return {values,amounts,run:j.run_utc,period_start:d.valid_from_utc,
    period_end:d.valid_to_utc,members:8};
  }catch(e){console.error("KFS_PROBA_FROST_ECMWF",String(e).slice(0,160));}
 }
 return null;
}

async function kfsProbaComplete(interaction,phenom,zone,jour,seuil){
 try{
  if(jour===5)return await kfsProbaFiveDayComplete(interaction,phenom,zone,seuil);
  const rules=KFS_PROBA_RULES[phenom];
  if(!rules||![0,1,2,3].includes(jour)||!rules.allowed.includes(seuil))throw Error(
   "Paramètres invalides. Seuils : gel 0/-2/-5/-10 °C ; chutes de neige 0,1/1/3/5 mm équiv.-eau ; neige au sol 1/3/5/10 cm ; pluie 0,1/1/5/10/20/40 mm ; rafales 54/60/80/90/100/120 km/h."
  );
  const all=await kfsProbaFeatures(),features=zone==="FR"?all:all.filter(f=>String(f.properties.code)===zone);
  if(!features.length)throw Error("Région non reconnue.");
  const departmentsPromise=zone==="FR"?Promise.resolve([]):kfsProbaDepartments(zone).catch(e=>{
   console.error("KFS_PROBA_DEPARTMENTS",String(e));return [];
  });
  const points=kfsProbaSamples(features,zone!=="FR");
  if(points.length<2)throw Error("Échantillonnage spatial insuffisant.");
  const day=kfsProbaDay(jour),available=[],failures=[];
  // Gelées : l'IFS ENS gratuit fonctionne indépendamment du quota Open-Meteo.
  const frost=phenom==="gel"?await kfsProbaEcmwfFrostRead(seuil,zone,day,points):null;
  if(frost){
   for(let i=0;i<points.length;i++){points[i].value=frost.values[i];points[i].amount=frost.amounts[i];}
   const departments=await departmentsPromise;
   const frame=kfsProbaRender(features,points,zone,"gel",departments),png=await kfsProbaPng(frame);
   const name=zone==="FR"?"France métropolitaine":KFS_PROBA_REGIONS.find(r=>r[0]===zone)?.[1]||zone;
   const min=Math.round(Math.min(...frost.values)),max=Math.round(Math.max(...frost.values));
   const minT=Math.min(...frost.amounts).toFixed(1),maxT=Math.max(...frost.amounts).toFixed(1);
   const content="**KFS MÉTÉO · /proba gelées · "+name+" · J+"+jour+" ("+day+")**\n"+
    "🥶 **Gel à 2 m :** température minimale ≤ "+seuil+" °C sur 24 h UTC.\n"+
    "🗺️ **Fraction des membres :** "+min+" à "+max+" % aux points étudiés.\n"+
    "🌡️ **Température minimale moyenne :** "+minT+" à "+maxT+" °C.\n"+
    "**Carte :** couleurs = Tmin moyenne ; blanc = % de membres sous le seuil ; bleu = Tmin en °C.\n"+
    "📊 **Source :** IFS ENS ECMWF, 8 membres, minimum des huit fenêtres successives de 3 h (mn2t3).\n"+
    "🕓 **Période :** "+frost.period_start+" → "+frost.period_end+" (UTC, pas exactement le jour civil français).\n"+
    "**Run :** "+frost.run+".\n"+
    (zone!=="FR"?"**Repères :** limites départementales et grandes villes.\n":"")+
    "⚠️ Ensemble limité à 8 membres à 0,25°, fraction non calibrée ; gel sous abri à 2 m, pas gel au sol, microclimat ni vigilance officielle.\n"+
    "_Données ECMWF Open Data, licence CC BY 4.0._";
   try{await kfsProbaEdit(interaction,{content,allowed_mentions:{parse:[]}},png);}
   catch(e){await kfsProbaEdit(interaction,{content:content+"\n⚠️ Carte indisponible : "+String(e.message||e).slice(0,150),allowed_mentions:{parse:[]}});}
   return;
  }
  const subset=await kfsProbaEcmwfSubsetRead(phenom,seuil,zone,day,points);
  if(subset){
   for(let i=0;i<points.length;i++){points[i].value=subset.values[i];points[i].amount=subset.amounts[i];}
   const departments=await departmentsPromise;
   const frame=kfsProbaRender(features,points,zone,phenom,departments),png=await kfsProbaPng(frame);
   const name=zone==="FR"?"France métropolitaine":KFS_PROBA_REGIONS.find(r=>r[0]===zone)?.[1]||zone;
   const minimum=Math.round(Math.min(...subset.values)),maximum=Math.round(Math.max(...subset.values));
   const label=phenom==="neige"?"neige présente au sol ≥ "+seuil+" cm":
    phenom==="pluie"?"pluie liquide cumulée ≥ "+seuil+" mm sur 24 h":
    phenom==="neige_chutes"?"précipitations sous forme de neige ≥ "+seuil+" mm d'équivalent-eau sur 24 h":
    "potentiel orageux au moins "+KFS_STORM_NAMES[seuil].toLowerCase();
   const valueType=phenom==="neige"?"épaisseur moyenne de neige au sol (cm)":phenom==="neige_chutes"?"cumul moyen de neige fraîche (mm équiv.-eau sur 24 h)":phenom==="pluie"?"cumul moyen de pluie liquide (mm sur 24 h)":"indice moyen de potentiel convectif (0–5)";
   const maxValue=(arr)=>arr?.filter(Number.isFinite).length?
    Math.max(...arr.filter(Number.isFinite)):null;
   const orgMax=maxValue(subset.diagnostics?.organized);
   const liftMax=maxValue(subset.diagnostics?.ascent);
   const shearMax=maxValue(subset.diagnostics?.shear);
   const stormTrend=phenom==="orage"&&subset.stormTrend?.length?
    "🗓️ **Évolution "+KFS_STORM_NAMES[seuil].toLowerCase()+" (maximum local par jour) :** "+
      subset.stormTrend.map(x=>x.date.slice(8,10)+"/"+x.date.slice(5,7)+" "+x.requested.toFixed(1).replace(".0","")+" %").join(" · ")+".\n"+
    "🔎 **Signal orageux faible, même run :** "+
      subset.stormTrend.map(x=>x.date.slice(8,10)+"/"+x.date.slice(5,7)+" "+x.weak.toFixed(1).replace(".0","")+" %").join(" · ")+".\n"+
    (subset.stormTrend.every(x=>x.requested===0)?"💡 Aucun des 8 membres n'atteint le niveau demandé aux points analysés ; des variations existent parfois au niveau faible.\n":""):"";
   const stormDiagnostics=phenom==="orage"?
    (orgMax!==null?"🌪️ **Potentiel d'organisation convective :** jusqu'à "+Math.round(orgMax)+" % des membres aux points échantillonnés (niveau ≥ moyen et cisaillement 850–500 hPa ≥ 15 m/s).\n":"")+
    (shearMax!==null?"💨 **Cisaillement 850–500 hPa :** jusqu'à "+shearMax.toFixed(1)+" m/s (maximum quotidien moyen d'ensemble local).\n":"")+
    (liftMax!==null?"↗️ **Convection avec ascendance 700 hPa :** jusqu'à "+Math.round(liftMax)+" % des membres (ω ≤ −0,05 Pa/s).\n":"")+
    ((orgMax!==null||shearMax!==null||liftMax!==null)?
     "ℹ️ Ces diagnostics décrivent l'environnement, pas des orages violents certains. Cisaillement 850–500 ≠ 0–6 km ; ascendance synoptique ≠ courant ascendant de la cellule.\n":""):
    "";
   const content="**KFS MÉTÉO · /proba · "+name+" · J+"+jour+" ("+day+")**\n"+
    "**Événement :** "+label+".\n"+
    "🗺️ **Probabilité indicative :** "+minimum+" à "+maximum+" % sur les points échantillonnés.\n"+
    "📊 **Source sans Open-Meteo :** "+subset.members+" membres sélectionnés de l'IFS ENS ouvert d'ECMWF.\n"+
    "**Carte :** chiffres % = fraction des membres dépassant le seuil ; couleur = "+valueType+" ; chiffres bleus = quantité moyenne.\n"+
    (phenom==="pluie"?"💧 **Cumul moyen de pluie :** "+
      Math.min(...subset.amounts).toFixed(1)+" à "+Math.max(...subset.amounts).toFixed(1)+
      " mm sur 24 h, calculé sur les mêmes 8 membres et le même run que les probabilités.\n":"")+
    stormTrend+stormDiagnostics+
    "**Run :** "+subset.run+" · **période UTC :** "+subset.period_start+" → "+subset.period_end+".\n"+
    (zone!=="FR"?"**Repères :** départements et grandes villes.\n":"")+
    (phenom==="neige"?"🏔️ Le relief montagneux est inclus ; le modèle représente les zones naturelles, pas la tenue sur les routes.\n":
     phenom==="neige_chutes"?"❄️ Neige tombant durant la période, avec ou sans tenue au sol ; mm équivalent-eau, pas épaisseur au sol. Le relief est inclus.\n":
     phenom==="pluie"?"💧 Pluie liquide calculée par TP − SF (précipitations totales moins neige fraîche en équivalent-eau). **Les périodes et runs sont identiques.**\n":
     "⛈️ Indice heuristique CAPE, précipitations convectives, humidité (point de rosée) et rafales ; ne prévoit pas directement l'occurrence ni la sévérité d'un orage.\n")+
    "⚠️ **Probabilités expérimentales non calibrées.** Échantillon de 8 membres et deux échéances par 24 h, à maille 0,25°. Ne remplace pas une vigilance officielle.\n"+
    "_ECMWF Open Data, licence CC BY 4.0._";
   try{await kfsProbaEdit(interaction,{content,allowed_mentions:{parse:[]}},png);}
   catch(e){await kfsProbaEdit(interaction,{content:content+"\n⚠️ Image indisponible : "+String(e.message||e).slice(0,150),allowed_mentions:{parse:[]}});}
   return;
  }
  const ecmwf=await kfsProbaEcmwfRead(phenom,seuil,zone,day,points);
  if(ecmwf){
   const rainMean=phenom==="pluie"?
    await kfsProbaEcmwfRainMeanRead(zone,day,points,ecmwf.run,ecmwf.period_start,ecmwf.period_end):null;
   for(let i=0;i<points.length;i++){
    points[i].value=ecmwf.values[i]; // % d'ensemble ECMWF complet, seuil demandé
    points[i].amount=rainMean?rainMean.values[i]:ecmwf.values[i];
   }
   const departments=await departmentsPromise;
   const frame=kfsProbaRender(features,points,zone,rainMean?"pluie":"probabilite",departments);
   const png=await kfsProbaPng(frame);
   const name=zone==="FR"?"France métropolitaine":KFS_PROBA_REGIONS.find(r=>r[0]===zone)?.[1]||zone;
   const min=Math.round(Math.min(...ecmwf.values)),max=Math.round(Math.max(...ecmwf.values));
   const what=phenom==="pluie"?"précipitations totales (pluie ou neige) ≥ "+seuil+" mm":
     "rafales de vent ≥ "+seuil+" km/h";
   const content="**KFS MÉTÉO · /proba · "+name+" · J+"+jour+" ("+day+")**\n"+
    "**Événement ECMWF ENS :** "+what+".\n"+
    "🗺️ **Probabilité ECMWF :** "+min+" à "+max+" % aux points étudiés.\n"+
    (rainMean?
      "💧 **Cumul moyen estimé :** "+Math.min(...rainMean.values).toFixed(1)+" à "+Math.max(...rainMean.values).toFixed(1)+" mm sur 24 h (8 membres ENS).\n"+
      "**Carte :** zones de couleur = quantités en mm ; chiffres jaunes/blancs = risque en % ; chiffres bleus = cumul moyen en mm.\n":
      "ℹ️ Cumul moyen en mm indisponible pour ce run ; la carte reste en probabilités sans inventer de quantité.\n")+
    "📊 **Source :** ECMWF IFS ENS Open Data (probabilités natives)"+
      (rainMean?" et cumuls moyens d’un échantillon de 8 membres":"")+".\n"+
    "🕓 **Validité des prévisions :** "+ecmwf.period_start+" → "+ecmwf.period_end+
    " (période de 24 h UTC, pas exactement le jour civil français).\n"+
    "**Modèle :** IFS ENS run "+ecmwf.run+" · dernières données consultées à la génération.\n"+
    (zone!=="FR"?"**Repères :** départements et grandes villes.\n":"")+
    "ℹ️ Probabilité d'ensemble ECMWF à la maille la plus proche (0,25°), non une probabilité officielle de vigilance.\n"+
    "_Source : ECMWF Open Data, CC BY 4.0, www.ecmwf.int. Redistribution KFS MÉTÉO._";
   try{await kfsProbaEdit(interaction,{content,allowed_mentions:{parse:[]}},png);}
   catch(e){
    console.error("KFS_PROBA_ECMWF_IMAGE",String(e));
    await kfsProbaEdit(interaction,{content:content+"\n⚠️ Carte PNG indisponible : "+String(e.message||e).slice(0,180),
     allowed_mentions:{parse:[]}});
   }
   return;
  }
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
    phenom==="neige_chutes"?"précipitations sous forme de neige ≥ "+seuil+" mm équiv.-eau sur le jour (même sans tenue au sol)":
   phenom==="pluie"?"cumul de pluie ≥ "+seuil+" mm sur le jour":
   phenom==="gel"?"température minimale à 2 m ≤ "+seuil+" °C sur la journée":
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
   (phenom==="gel"?
     "**Carte :** couleurs = température minimale moyenne à 2 m en °C ; blanc = fraction des membres sous le seuil ; bleu = Tmin moyenne.\n":
    phenom==="orage"?
     "**Carte :** couleurs = catégorie moyenne indicative de potentiel convectif ; blanc = proportion des membres atteignant le niveau demandé ; bleu = niveau moyen.\n":
     "**Carte :** couleurs = quantité moyenne (en "+unit+") ; chiffre blanc = probabilité d’atteindre le seuil ; chiffre bleu = quantité moyenne.\n")+
   (phenom==="gel"?"**Échelle Tmin :** classes de température en °C, de −15 °C à +3 °C et au-delà.\n":
    phenom==="orage"?"**Échelle orage :** aucun · faible · moyen · modéré · fort · extrême.\n":
     "**Échelle des quantités (classes) :** "+KFS_PROBA_SCALE[phenom].ticks.map((v,i,arr)=>i===arr.length-1?v+" et +":v+"-"+arr[i+1]).join(" · ")+" "+unit+".\n")+
   (zone!=="FR"?"**Repères :** limites départementales et grandes villes.\n":"")+
   (minAmount!==null?(phenom==="gel"?
      "**Tmin moyenne des membres :** "+minAmount.toFixed(1)+" à "+maxAmount.toFixed(1)+" °C sur les points étudiés.\n":
     phenom==="orage"?
      "**Indice convectif moyen :** "+minAmount.toFixed(1)+" à "+maxAmount.toFixed(1)+" / 5.\n":
      "**Quantité moyenne :** "+(Math.round(minAmount*10)/10)+" à "+(Math.round(maxAmount*10)/10)+" "+unit+" sur les points étudiés.\n"):"")+
     stormRange+wetRange+caution+
   (phenom==="neige"?"🏔️ Les points situés au-dessus de 800 m sont écartés ; neige au sol modélisée, pas chute fraîche.\n":
    phenom==="neige_chutes"?"❄️ **Neige qui tombe, sans exigence de tenue au sol.** Cumul en mm équiv.-eau, pas en cm de neige sur les routes. En secours Open-Meteo, équivalent-eau approximatif obtenu à partir de chutes en cm (conversion 7 cm ≈ 10 mm d’eau).\n":"")+
   (phenom==="gel"?"❄️ Gel estimé à 2 m sous abri, pas une mesure de gel au sol ou de verglas ; les microclimats et fonds de vallée peuvent être plus froids.\n":"")+
   (phenom==="orage"?"⚠️ **Indice orageux expérimental**, fondé sur CAPE, pluie, point de rosée, CIN (si disponible), rafales et codes météo. Signal précurseur possible sans pluie prévue : déclenchement non garanti. Fort/extrême ne signifie pas grêle, tornade ou rafales destructrices certaines. **Aucune équivalence avec la vigilance Météo-France.**\n":"")+
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




// Five-day probabilities follow each member across the entire period.
// Daily percentages are never summed or treated as independent events.
function kfsProbaShiftDay(day,delta){
 return new Date(Date.parse(day+"T12:00:00Z")+delta*86400000).toISOString().slice(0,10);
}
function kfsProbaNormalizeHourly(hourly){
 if(!hourly?.time?.some(v=>typeof v==="number"))return hourly;
 const f=new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Paris",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});
 return {...hourly,time:hourly.time.map(v=>typeof v==="number"?f.format(new Date(v*1000)).replace(" ","T"):v)};
}
function kfsProbaPeriodComplete(times,ids,start,end,interval=0){
 if(!interval)interval=(Date.parse(times[ids[1]])-Date.parse(times[ids[0]]))/3600000;
 if(![1,3].includes(interval))return false;
 const days=new Map();
 for(const i of ids){const date=String(times[i]).slice(0,10);if(!days.has(date))days.set(date,[]);days.get(date).push(times[i]);}
 const offset=date=>{
  const parts=new Intl.DateTimeFormat("en-US",{timeZone:"Europe/Paris",timeZoneName:"longOffset"}).formatToParts(new Date(date+"T12:00:00Z"));
  const text=parts.find(p=>p.type==="timeZoneName").value;
  const match=text.match(/GMT([+-])(\d{2}):(\d{2})/);
  return match?(match[1]==="-"?-1:1)*(Number(match[2])*60+Number(match[3])):0;
 };
 for(let d=start;d<=end;d=new Date(Date.parse(d+"T12:00:00Z")+86400000).toISOString().slice(0,10)){
  const previous=new Date(Date.parse(d+"T12:00:00Z")-86400000).toISOString().slice(0,10);
  const expected=Math.ceil((24-(offset(d)-offset(previous))/60)/interval);
  const samples=days.get(d)||[];
  if(samples.length!==expected)return false;
  const hours=samples.map(t=>Number(String(t).slice(11,13)));
  if(Math.min(...hours)!==0 || Math.max(...hours)<24-interval)return false;
 }
 return true;
}
async function kfsProbaFiveDayRead(type,threshold,zone,start,end,points){
 const url="https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/proba/five-day-probabilities.json";
 try{
  const r=await fetch(url,{signal:AbortSignal.timeout(5000),cf:{cacheTtl:600,cacheEverything:true}});
  if(!r.ok)return null;
  const j=await r.json(),age=Date.now()-Date.parse(j.generated_at_utc);
  const p=j.zones?.[zone]?.[type]?.[String(threshold)];
  if(j.schema!==1 || !(["Open-Meteo ECMWF IFS ENS five-day members","Open-Meteo five-day ensemble members"].includes(j.provider)) ||
   !(["ecmwf_ifs025_ensemble","ncep_gefs025"].includes(j.model)) ||
   j.start_day!==start || j.end_day!==end || j.duration_days!==5 ||
   !Number.isFinite(age)||age<0||age>28*3600000 ||
   JSON.stringify(j.zone_points?.[zone])!==JSON.stringify(points.map(p=>[p.lat,p.lon])))return null;
  if(!Array.isArray(p)||p.length!==points.length || p.some(v=>!v ||
   !Number.isFinite(v.pct)||v.pct<0||v.pct>100||!Number.isFinite(v.amount)||
   !Number.isInteger(v.members)||v.members<2))return null;
  return {values:p,source:(j.model==="ncep_gefs025"?"NOAA GEFS":"ECMWF IFS ENS")+" via Open-Meteo",consulted:j.generated_at_utc};
 }catch(e){console.error("KFS_PROBA_FIVE_DAY_READ",String(e));return null;}
}
async function kfsProbaFiveDayComplete(interaction,type,zone,threshold){
 const rules=KFS_PROBA_RULES[type];
 if(!rules||!rules.allowed.includes(threshold))throw Error("Seuil ou phénomène invalide pour les cinq jours cumulés.");
 const start=kfsProbaDay(1),end=kfsProbaDay(5);
 const all=await kfsProbaFeatures(),features=zone==="FR"?all:all.filter(f=>String(f.properties.code)===zone);
 if(!features.length)throw Error("Région non reconnue.");
 const departments=await kfsProbaDepartments(zone).catch(()=>[]);
 const points=kfsProbaSamples(features,zone!=="FR");
 let result=await kfsProbaFiveDayRead(type,threshold,zone,start,end,points);
 if(!result){
  // One request for all five days, using actual member trajectories.
  const model=KFS_PROBA_MODELS[0];
  const r=type==="orage"?await kfsProbaStormModel(model,points,start,threshold,end):
   await kfsProbaModel(model,points,start,type,threshold,end);
  result={values:r.values,source:r.name+" via Open-Meteo",consulted:new Date().toISOString()};
 }
 for(let i=0;i<points.length;i++){
  const v=result.values[i];if(v){points[i].value=v.pct;points[i].amount=v.amount;}
 }
 const counted=points.filter(p=>Number.isFinite(p.value)&&Number.isFinite(p.amount));
 if(!counted.length)throw Error("Les membres ne couvrent pas encore les cinq jours complets. Réessaie après l'actualisation des données.");
 const name=zone==="FR"?"France métropolitaine":KFS_PROBA_REGIONS.find(r=>r[0]===zone)?.[1]||zone;
 const label=type==="pluie"?"cumul de pluie sur les cinq jours ≥ "+threshold+" mm":
  type==="neige_chutes"?"cumul des chutes de neige sur les cinq jours ≥ "+threshold+" mm équiv.-eau":
  type==="gel"?"température à 2 m ≤ "+threshold+" °C au moins une fois":
  type==="neige"?"épaisseur de neige au sol ≥ "+threshold+" cm au moins une fois":
  type==="vent"?"rafale ≥ "+threshold+" km/h au moins une fois":
  "potentiel orageux au moins "+KFS_STORM_NAMES[threshold].toLowerCase()+" au moins une fois";
 const quantity=type==="pluie"||type==="neige_chutes"?"cumul sur les cinq jours":
  type==="gel"?"minimum sur les cinq jours":type==="neige"?"épaisseur maximale sur les cinq jours":
  type==="vent"?"rafale maximale sur les cinq jours":"niveau maximal sur les cinq jours";
 const members=result.values.filter(Boolean).map(v=>v.members);
 const memberText=Math.min(...members)===Math.max(...members)?String(Math.min(...members)):
  Math.min(...members)+" à "+Math.max(...members);
 const content="**KFS MÉTÉO · /proba · "+name+" · 5 JOURS CUMULÉS (J+1 à J+5)**\n"+
  "🗓️ **Période :** du "+start+" à 00 h au "+end+" à 24 h (heure de Paris).\n"+
  "**Événement :** "+label+".\n"+
  "🗺️ **Probabilité indicative :** "+Math.round(Math.min(...counted.map(p=>p.value)))+" à "+
   Math.round(Math.max(...counted.map(p=>p.value)))+" % aux points étudiés.\n"+
  "**Carte :** chiffres blancs = % de membres atteignant le seuil ; couleurs et chiffres bleus = moyenne du "+quantity+" ("+KFS_PROBA_SCALE[type].unit+").\n"+
  "**Calcul :** "+memberText+" membres suivis sur toute la période ; un membre est compté une seule fois.\n"+
  (type==="pluie"||type==="neige_chutes"?"Les quantités sont additionnées pour chaque membre avant de tester le seuil.\n":
   "Le seuil doit être atteint au moins une fois au cours des cinq jours.\n")+
  (counted.length<points.length?"⚠️ Données complètes sur "+counted.length+"/"+points.length+" points échantillonnés.\n":"")+
  (type==="orage"?"⚠️ Potentiel convectif expérimental ; ce pourcentage ne mesure pas une probabilité calibrée d'orage violent.\n":"")+
  (type==="neige"?"❄️ Épaisseur maximale de neige présente au sol ; les épaisseurs quotidiennes ne sont pas additionnées.\n":"")+
  "📊 **Source :** "+result.source+" · consultée le "+result.consulted+".\n"+
  "_Fraction d'ensemble non calibrée, à la maille du modèle ; ne remplace pas une vigilance officielle._";
 const frame=kfsProbaRender(features,points,zone,type,departments),png=await kfsProbaPng(frame);
 try{await kfsProbaEdit(interaction,{content,allowed_mentions:{parse:[]}},png);}
 catch(e){await kfsProbaEdit(interaction,{content:content+"\n⚠️ Carte indisponible : "+String(e.message||e).slice(0,150),allowed_mentions:{parse:[]}});}
}
