const PUBLIC_KEY = "e90f56b552edd55d7d36673b258ebc8dadbe75c78a7a1615399e9e3e4ca26440";

const APPLICATION_ID = "1567640649929461770";

const json = (body, status=200) => new Response(JSON.stringify(body), {status,headers:{"content-type":"application/json;charset=utf-8"}});

const hex = s => Uint8Array.from(s.match(/../g) || [], h=>parseInt(h,16));

async function valid(request, raw) {

  const sig=request.headers.get("X-Signature-Ed25519");

  const ts=request.headers.get("X-Signature-Timestamp");

  if (!sig || !ts || !/^[0-9a-f]{128}$/i.test(sig) || !/^\d+$/.test(ts)) return false;

  if (Math.abs(Date.now()/1000-Number(ts))>300) return false;

  try {

    const key=await crypto.subtle.importKey("raw",hex(PUBLIC_KEY),{name:"Ed25519"},false,["verify"]);

    return crypto.subtle.verify("Ed25519",key,hex(sig),new TextEncoder().encode(ts+raw));

  } catch {return false;}

}

const n=v=>Number.isFinite(v)?Math.round(v):"—";

const pick=(obj,k)=>obj?.[k]??[];

const wx={0:"soleil",1:"peu nuageux",2:"éclaircies",3:"couvert",45:"brouillard",48:"brouillard givrant",51:"bruine",53:"bruine",55:"bruine forte",61:"pluie faible",63:"pluie",65:"pluie forte",71:"neige faible",73:"neige",75:"neige forte",80:"averses",81:"averses",82:"fortes averses",95:"orages",96:"orages/grêle",99:"orages/grêle"};

const finite=v=>typeof v==="number"&&Number.isFinite(v);

const fmt=(v,u="")=>finite(v)?Math.round(v)+u:"n/d";

const average=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:null;

const dayLabel=day=>new Intl.DateTimeFormat("fr-FR",{weekday:"short",day:"numeric",month:"short",timeZone:"UTC"}).format(new Date(day+"T12:00:00Z"));

async function modelForecast(p,id,days=16){

  const q=new URLSearchParams({latitude:String(p.latitude),longitude:String(p.longitude),timezone:"auto",forecast_days:String(days),models:id,daily:"weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_gusts_10m_max"});

  const r=await fetch("https://api.open-meteo.com/v1/forecast?"+q);

  if(!r.ok)throw Error(id+": HTTP "+r.status+" "+(await r.text()).slice(0,220));

  const d=(await r.json()).daily;

  if(!d?.time?.length)throw Error("Données absentes "+id);

  return d;

}

function dayData(d,date){

  if(!d)return null;

  const i=d.time.indexOf(date);

  return i<0?null:{lo:d.temperature_2m_min?.[i],hi:d.temperature_2m_max?.[i],rain:d.precipitation_sum?.[i],gust:d.wind_gusts_10m_max?.[i],code:d.weather_code?.[i]};

}

function modelLine(name,d,date){

  const x=dayData(d,date);

  if(!x||!finite(x.lo)||!finite(x.hi))return name+" : indisponible";

  return name+" "+fmt(x.lo,"°")+"/"+fmt(x.hi,"°")+" · pluie "+fmt(x.rain," mm")+" · raf. "+fmt(x.gust," km/h");

}

function regime(models,dates){

  const highs=[],rains=[],gusts=[],codes=[];

  for(const d of models)for(const date of dates){

    const x=dayData(d,date);if(!x)continue;

    if(finite(x.hi))highs.push(x.hi);

    if(finite(x.rain))rains.push(x.rain);

    if(finite(x.gust))gusts.push(x.gust);

    if(finite(x.code))codes.push(x.code);

  }

  return {temp:average(highs),rain:average(rains),gust:gusts.length?Math.max(...gusts):null,wet:rains.length?rains.filter(x=>x>=2).length/rains.length:null,thunder:codes.some(x=>[95,96,99].includes(x))};

}

function trendText(ifs,aifs,dates){

  if(!ifs&&!aifs)return "Tendance J+6 à J+15 indisponible : modèles non accessibles.";

  const blocks=[[5,9,"J+6 à J+10"],[10,14,"J+11 à J+15"]];

  const out=[];

  for(const [start,end,label] of blocks){

    const period=dates.slice(start,end+1);

    const r=regime([ifs,aifs].filter(Boolean),period);

    const ri=ifs?regime([ifs],period):null,ra=aifs?regime([aifs],period):null;

    let text=label+" : ";

    if(!finite(r.temp)){out.push(text+"données insuffisantes.");continue;}

    text+="maximales moyennes des scénarios autour de "+fmt(r.temp,"°C")+". ";

    if(r.wet!==null)text+=r.wet>=0.6?"Signal humide assez récurrent. ":r.wet<=0.25?"Signal plutôt sec. ":"Alternance de périodes sèches et humides. ";

    if(finite(r.gust)&&r.gust>=70)text+="Épisodes venteux possibles. ";

    if(r.thunder)text+="Signal orageux ponctuel à surveiller. ";

    if(ri&&ra&&finite(ri.temp)&&finite(ra.temp)){

      const delta=Math.abs(ri.temp-ra.temp);

      text+="Écart IFS/AIFS sur les maximales moyennes : "+fmt(delta,"°C")+(delta>=4?" (forte divergence).":delta>=2?" (divergence modérée).":" (accord relatif).");

    }else text+="Un seul modèle disponible : confiance non évaluable.";

    out.push(text);

  }

  return out.join("\n\n");

}

async function seasonalText(p){
// ECMWF EC46/SEAS5 are ensemble forecasts; this is a raw signal, not a climatological anomaly.*

  try{

    const q=new URLSearchParams({latitude:String(p.latitude),longitude:String(p.longitude),timezone:"auto",forecast_days:"45",models:"ecmwf_seasonal_ensemble_mean_seamless",daily:"temperature_2m_max,temperature_2m_min,precipitation_sum"});

    const r=await fetch("https://seasonal-api.open-meteo.com/v1/seasonal?"+q);

    if(!r.ok)return "ECMWF saisonnier : données non accessibles (HTTP "+r.status+").";

    const d=(await r.json()).daily;

    if(!d?.time?.length)return "ECMWF saisonnier : aucune donnée exploitable.";

    const now=new Date();const target=new Date(now.getTime()+30*86400000);const lo=new Date(target.getTime()-7*86400000),hi=new Date(target.getTime()+7*86400000);

    const values=d.time.map((date,i)=>({date:new Date(date+"T12:00:00Z"),min:d.temperature_2m_min?.[i],max:d.temperature_2m_max?.[i],rain:d.precipitation_sum?.[i]})).filter(x=>x.date>=lo&&x.date<=hi);

    const t=average(values.map(x=>x.max).filter(finite)),rains=values.map(x=>x.rain).filter(finite);

    if(!finite(t))return "ECMWF saisonnier : signal thermique indisponible.";

    return "ECMWF saisonnier, autour de J+30 (fenêtre ±7 jours) : maximale moyenne brute de l'ensemble ≈ "+fmt(t,"°C")+(rains.length?", précipitations cumulées indicatives sur la fenêtre ≈ "+fmt(rains.reduce((a,b)=>a+b,0)," mm"):"")+". Ce n'est PAS une anomalie par rapport aux normales ni une prévision quotidienne fiable. Sans climatologie de référence et dispersion de l'ensemble, aucune tendance chaud/froid ou sec/humide ne peut être établie.";

  }catch{return "ECMWF saisonnier : données momentanément indisponibles.";}

}

async function hourlyCheck(p,name,id,dates){

 try {

  const q=new URLSearchParams({latitude:String(p.latitude),longitude:String(p.longitude),timezone:"auto",forecast_days:"3",models:id,hourly:"temperature_2m"});

  const r=await fetch("https://api.open-meteo.com/v1/forecast?"+q);

  if(!r.ok)return name+": HTTP "+r.status+" "+(await r.text()).slice(0,100);

  const h=(await r.json()).hourly;

  if(!h?.time?.length)return name+": aucune heure disponible";

  return name+": "+dates.map(day=>{

   const a=h.time.map((t,i)=>t.startsWith(day)?h.temperature_2m?.[i]:null).filter(finite);

   return day+" "+(a.length?fmt(Math.min(...a),"°")+"/"+fmt(Math.max(...a),"°")+" ("+a.length+" h)":"aucune valeur");

  }).join(" | ");

 }catch(e){return name+": "+String(e.message||e).slice(0,100);}

}

async function localHourly(p,id,dates){

 const q=new URLSearchParams({latitude:String(p.latitude),longitude:String(p.longitude),timezone:"auto",forecast_days:"3",models:id,hourly:"temperature_2m"});

 const r=await fetch("https://api.open-meteo.com/v1/forecast?"+q);

 if(!r.ok)throw Error(id+" HTTP "+r.status);

 const h=(await r.json()).hourly;

 if(!h?.time)return new Map();

 return new Map(dates.map(day=>{

  const v=h.time.map((t,i)=>({time:t,temp:h.temperature_2m?.[i]})).filter(x=>x.time.startsWith(day)&&finite(x.temp));

  if(v.length<18)return [day,null];

  const min=v.reduce((a,b)=>b.temp<a.temp?b:a);

  const max=v.reduce((a,b)=>b.temp>a.temp?b:a);

  return [day,{lo:min.temp,hi:max.temp,minHour:min.time.slice(11,16),maxHour:max.time.slice(11,16),hours:v.length}];

 }));

}

function fineLine(name,hourly,day){

 const x=hourly?.get(day);

 return x?name+" · min "+fmt(x.lo,"°")+" à "+x.minHour+" · max "+fmt(x.hi,"°")+" à "+x.maxHour:null;

}

async function skyNarrative(p,date){

 const models=[["AROME HD","meteofrance_arome_france_hd"],["ICON-D2","icon_d2"],["ICON-EU","icon_eu"]];

 const slots=[["matin",6,12],["après-midi",12,18],["soirée",18,24]];

 function describe(rows){

  const codes=rows.map(x=>x.code).filter(finite);

  const clouds=rows.map(x=>x.cloud).filter(finite);

  const rains=rows.map(x=>x.rain).filter(finite);

  const vis=rows.map(x=>x.vis).filter(finite);

  const avg=a=>a.reduce((u,v)=>u+v,0)/a.length;

  if(codes.some(x=>[95,96,99].includes(x)))return "un risque d'orages";

  if(codes.some(x=>[71,73,75,77,85,86].includes(x)))return "des chutes de neige possibles";

  if(codes.some(x=>[45,48].includes(x))||(vis.length>=2&&avg(vis)<1000))return "du brouillard";

  if(codes.some(x=>[61,63,65,80,81,82].includes(x))||(rains.length&&rains.reduce((a,b)=>a+b,0)>=1))return "des pluies ou averses";

  if(codes.some(x=>[51,53,55,56,57].includes(x)))return "quelques bruines";

  const c=clouds.length?avg(clouds):null;

  if(c!==null)return c>=85?"un ciel couvert":c>=60?"un ciel très nuageux":c>=35?"un ciel variable avec des éclaircies":c>=15?"de belles éclaircies":"un temps largement ensoleillé";

  if(codes.length){const code=codes[Math.floor(codes.length/2)];return code===0?"un ciel dégagé":code===1?"un temps peu nuageux":code===2?"un ciel partagé entre nuages et éclaircies":code===3?"un ciel couvert":null;}

  return null;

 }

 for(const [name,id] of models){

  try{

   const q=new URLSearchParams({latitude:String(p.latitude),longitude:String(p.longitude),timezone:"auto",forecast_days:"3",models:id,hourly:"weather_code,cloud_cover,rain,snowfall,visibility,wind_speed_10m,wind_gusts_10m,wind_direction_10m"});

   const r=await fetch("https://api.open-meteo.com/v1/forecast?"+q);

   if(!r.ok)continue;

   const h=(await r.json()).hourly;

   if(!h?.time?.length)continue;

   const periods=slots.map(([label,start,end])=>{

    const rows=h.time.map((time,i)=>({time,code:h.weather_code?.[i],cloud:h.cloud_cover?.[i],rain:h.rain?.[i],snow:h.snowfall?.[i],vis:h.visibility?.[i]})).filter(x=>x.time.startsWith(date)&&Number(x.time.slice(11,13))>=start&&Number(x.time.slice(11,13))<end&&[x.code,x.cloud,x.rain,x.snow,x.vis].some(finite));

    return {label,description:rows.length>=3?describe(rows):null};

   });

   if(periods.filter(x=>x.description).length<2)continue;

   const phrases=periods.filter(x=>x.description).map(x=>x.description+" "+(x.label==="matin"?"le matin":x.label==="après-midi"?"l'après-midi":"en soirée"));

   const dayRows=h.time.map((time,i)=>({time,rain:h.rain?.[i],snow:h.snowfall?.[i],code:h.weather_code?.[i]})).filter(x=>x.time.startsWith(date));

   const rainy=dayRows.filter(x=>finite(x.rain));

   const snowy=dayRows.filter(x=>finite(x.snow));

   const snowCodes=dayRows.some(x=>[71,73,75,77,85,86].includes(x.code));

   const rainSum=rainy.reduce((sum,x)=>sum+x.rain,0);

   const snowSum=snowy.reduce((sum,x)=>sum+x.snow,0);

   const completeRain=rainy.length>=23;

   const completeSnow=snowy.length>=23;

   const mm=x=>(Math.round(x*10)/10).toLocaleString("fr-FR",{maximumFractionDigits:1});

   let amounts="🌧️ **Pluie :** "+(rainy.length?(completeRain?mm(rainSum)+" mm prévus":mm(rainSum)+" mm sur "+rainy.length+" h renseignées (cumul partiel)"):"cumul indisponible");

   if(snowCodes||snowSum>0){

    amounts+="\n❄️ **Neige :** "+(snowy.length?(completeSnow?mm(snowSum)+" cm prévus":mm(snowSum)+" cm sur "+snowy.length+" h renseignées (cumul partiel)"):"risque signalé, quantité indisponible");

   }

   const winds=h.time.map((time,i)=>({time,speed:h.wind_speed_10m?.[i],gust:h.wind_gusts_10m?.[i],direction:h.wind_direction_10m?.[i]})).filter(x=>x.time.startsWith(date));

   const speeds=winds.filter(x=>finite(x.speed)).map(x=>x.speed);

   const gusts=winds.filter(x=>finite(x.gust));

   const directions=winds.filter(x=>finite(x.direction));

   let windText="💨 **Vent :** ";

   if(!speeds.length&&!gusts.length)windText+="données indisponibles";

   else{

    const parts=[];

    if(speeds.length)parts.push("moyen "+Math.round(speeds.reduce((a,b)=>a+b,0)/speeds.length)+" km/h");

    if(gusts.length){const peak=gusts.reduce((a,b)=>b.gust>a.gust?b:a);parts.push("rafales jusqu'à "+Math.round(peak.gust)+" km/h vers "+peak.time.slice(11,16));}

    if(directions.length){

     const rad=directions.map(x=>x.direction*Math.PI/180);

     const avgAngle=(Math.atan2(rad.reduce((a,v)=>a+Math.sin(v),0),rad.reduce((a,v)=>a+Math.cos(v),0))*180/Math.PI+360)%360;

     const points=["nord","nord-est","est","sud-est","sud","sud-ouest","ouest","nord-ouest"];

     parts.push("dominante "+points[Math.round(avgAngle/45)%8]);

    }

    windText+=parts.join(" · ");

    if(winds.length<23)windText+=" (données horaires partielles)";

   }

   return "🌤️ **Évolution du temps :** "+phrases.join(", puis ")+".\n"+amounts+"\n"+windText+"\n_Source : "+name+" via Open-Meteo ; tendance indicative._";

  }catch(e){console.warn("Narrative model unavailable",name,String(e));}

 }

 return "🌤️ Évolution matin/après-midi : données horaires insuffisantes pour une description fiable.";

}

async function forecast(city,echeance){

  const geo=await fetch("https://geocoding-api.open-meteo.com/v1/search?"+new URLSearchParams({name:city,count:"1",language:"fr",format:"json"}));

  if(!geo.ok)throw Error("Géocodage indisponible.");

  const places=(await geo.json()).results;

  if(!places?.length)return ["📍 Localité introuvable. Indique une ville précise."];

  const p=places[0];

  const specs=[["AROME","meteofrance_arome_france_hd",3],["ICON-D2","icon_d2",3],["ICON-EU","icon_eu",6],["GFS","gfs_seamless",6],["ECMWF IFS","ecmwf_ifs025",16],["ECMWF AIFS","ecmwf_aifs025_single",16]];

  const results=await Promise.allSettled(specs.map(async ([name,id,days])=>[name,await modelForecast(p,id,days)]));

  const failures=results.map((x,i)=>x.status==="rejected"?specs[i][0]+": "+String(x.reason?.message||x.reason).slice(0,180):null).filter(Boolean);

  for(let i=0;i<results.length;i++)if(results[i].status==="rejected")console.warn("Model unavailable",specs[i][0],String(results[i].reason));

  const map=new Map(results.filter(x=>x.status==="fulfilled").map(x=>x.value));

  if(!map.size)throw Error("Aucun modèle disponible.");

  const dates=(map.get("ECMWF IFS")||map.get("GFS")||[...map.values()][0]).time.slice(0,15);

  const fine=await Promise.allSettled([localHourly(p,"meteofrance_arome_france_hd",dates.slice(0,2)),localHourly(p,"icon_d2",dates.slice(0,2))]);

  const aromeFine=fine[0].status==="fulfilled"?fine[0].value:new Map();

  const iconFine=fine[1].status==="fulfilled"?fine[1].value:new Map();

  const heading="🌦️ **KFS MÉTÉO — "+p.name+", "+(p.admin1||p.country||"")+"**";

  const short=["**🔎 Aujourd’hui / Demain — AROME et ICON-D2**"];

  for(const date of dates.slice(0,2)){

    const a=fineLine("AROME",aromeFine,date);

    const i=fineLine("ICON-D2",iconFine,date);

    short.push("**"+(date===dates[0]?"Aujourd’hui — ":"Demain — ")+dayLabel(date)+"**\n"+(a||"AROME : échéance non disponible")+"\n"+(i||modelLine("ICON-EU (repli)",map.get("ICON-EU"),date)));

  }

  short.push("_Min/max calculées sur les heures disponibles (au moins 18 h), susceptibles de manquer un extrême. ICON-EU est indiqué explicitement en repli._");

  short.push("**📅 J+2 à J+5 — GFS / ECMWF IFS**");

  for(const date of dates.slice(2,6))short.push("**"+dayLabel(date)+"**\n"+modelLine("GFS",map.get("GFS"),date)+"\n"+modelLine("IFS",map.get("ECMWF IFS"),date));

  const mid=heading+"\n\n"+short.join("\n\n")+"\n\n_Source : Open-Meteo. Prévisions déterministes, valeurs à la maille du modèle._";

  const long="**🧭 Analyse technique J+6 à J+15 — ECMWF IFS / AIFS**\n\n"+trendText(map.get("ECMWF IFS"),map.get("ECMWF AIFS"),dates)+"\n\n_Analyse fondée sur des températures et précipitations de surface : elle ne décrit pas la circulation synoptique en altitude. À longue échéance, les scénarios restent incertains._";

  const seasonal="**📆 Tendance vers J+30 — ECMWF saisonnier**\n\n"+await seasonalText(p);

  const checks=specs.map(([name])=>{

    const d=map.get(name);

    if(!d)return name+" : échec HTTP ou données absentes";

    const days=dates.slice(0,2).map(date=>{

      const x=dayData(d,date);

      return date+" min="+(x?.lo===null?"null":String(x?.lo??"absent"))+" max="+(x?.hi===null?"null":String(x?.hi??"absent"));

    });

    return name+" ("+d.time.length+" jours) : "+days.join(" | ");

  });

  const diagnostic="**🛠️ Diagnostic des données (temporaire)**\n"+checks.map(x=>"• "+x).join("\n")+(failures.length?"\n**Erreurs API :**\n"+failures.join("\n"):"");

  const hourly=await Promise.all([hourlyCheck(p,"AROME horaire","meteofrance_arome_france_hd",dates.slice(0,2)),hourlyCheck(p,"ICON-D2 horaire","icon_d2",dates.slice(0,2))]);

  if(echeance==="aujourdhui"||echeance==="demain"){

    const date=dates[echeance==="aujourdhui"?0:1];

    const a=fineLine("AROME",aromeFine,date);

    const i=fineLine("ICON-D2",iconFine,date);

    return [heading+"\n**"+(echeance==="aujourdhui"?"Aujourd’hui":"Demain")+" — "+dayLabel(date)+"**\n"+(a||"AROME : échéance non disponible")+"\n"+(i||modelLine("ICON-EU (repli)",map.get("ICON-EU"),date))+"\n\n"+await skyNarrative(p,date)];

  }

  if(echeance==="5jours")return [mid];

  if(echeance==="15jours")return [heading+"\n"+long];

  if(echeance==="1mois")return [heading+"\n"+seasonal];

  return [mid,long,seasonal];

}

async function complete(interaction, city, echeance) {

  let content;

  try {content=await forecast(city,echeance);} catch(e){content=["⚠️ "+(e.message||"Erreur météo temporaire.")];}

  const messages=(Array.isArray(content)?content:[content]).flatMap(message => {
    const parts=[];
    let remaining=String(message);
    while(remaining.length>1950){
      let cut=remaining.lastIndexOf("\n",1950);
      if(cut<900)cut=1950;
      parts.push(remaining.slice(0,cut));
      remaining=remaining.slice(cut).trimStart();
    }
    if(remaining)parts.push(remaining);
    return parts;
  });

  const base=`https://discord.com/api/v10/webhooks/${APPLICATION_ID}/${interaction.token}`;

  for(let i=0;i<messages.length;i++){

    const endpoint=i===0?base+"/messages/@original":base;

    const r=await fetch(endpoint,{method:i===0?"PATCH":"POST",headers:{"content-type":"application/json"},body:JSON.stringify({content:messages[i],allowed_mentions:{parse:[]}})});

    if(!r.ok)console.error("Discord reply failed",r.status,await r.text());

  }

}
// === /radar : animation RainViewer, avec repli Windy ===
// Conserve les prévisions /meteo.

const WINDY_RADAR_ZOOM=9;

function radarNorm(v){

  return String(v).normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().replace(/[-'’\s]+/g," ").trim();

}

async function radarVille(ville){

  const raw=ville.trim();
// Accepte "Bourth" ou "Rouen, 76" pour distinguer les homonymes.

  const match=raw.match(/^(.*?)(?:,\s*(\d{2,3}))?$/);

  const name=match?.[1]?.trim();

  const dept=match?.[2]||null;

  if(!name||name.length<2||name.length>80)throw Error("Indique une ville française de 2 à 80 caractères.");

  const q=new URLSearchParams({nom:name,fields:"nom,centre,departement,code",format:"json",geometry:"centre",limit:"30"});

  const response=await fetch("https://geo.api.gouv.fr/communes?"+q.toString());

  if(!response.ok)throw Error("Recherche des communes momentanément indisponible.");

  const places=await response.json();

  if(!Array.isArray(places))throw Error("Réponse du géocodage incorrecte.");

  let matching=places.filter(p=>radarNorm(p.nom)===radarNorm(name));

  if(dept)matching=matching.filter(p=>String(p.departement?.code||"")===dept);

  if(!matching.length)throw Error("Ville introuvable. Indique son nom exact, par exemple Rouen ou Rouen, 76.");

  if(matching.length>1){

    const suggestions=matching.slice(0,5).map(p=>p.nom+", "+(p.departement?.code||p.code||"?")).join(" ; ");

    throw Error("Plusieurs communes portent ce nom. Précise le département : "+suggestions);

  }

  const city=matching[0];

  const [lon,lat]=city.centre?.coordinates||[];

  if(!Number.isFinite(lon)||!Number.isFinite(lat)||lat<41||lat>52||lon< -6||lon>10)throw Error("Commune située hors de la zone radar couverte.");

  return {name:city.nom,dept:city.departement?.code||"",lon,lat};

}



function windyRadarUrl(latitude,longitude){

  if(!Number.isFinite(latitude)||!Number.isFinite(longitude)||

     latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180)

    throw Error("Coordonnées de la commune invalides.");
// Format de partage documenté par Windy : ?radar,latitude,longitude,zoom.*

  return "https://www.windy.com/?radar,"+

    latitude.toFixed(4)+","+longitude.toFixed(4)+","+WINDY_RADAR_ZOOM;

}
// L'atlas RainViewer est assemble automatiquement par GitHub Actions.*
// Cloudflare fait seulement le recadrage; aucun encodage GIF dans le Worker.*

const RAINVIEWER_BASE="https://almet27.github.io/kfs-meteo-cartes/rainviewer/";

const RAINVIEWER_MAX_AGE_MIN=50;

async function rainViewerManifest(){

  const r=await fetch(RAINVIEWER_BASE+"radar-rainviewer.json?t="+Math.floor(Date.now()/60000),

                      {headers:{accept:"application/json"}});

  if(!r.ok)throw Error("Animation RainViewer non publiée (HTTP "+r.status+")");

  const m=await r.json();

  if(m.schema!==1||m.provider!=="RainViewer"||m.projection!=="EPSG:3857"||

     m.zoom!==6||m.tile_size!==512||m.x0!==31||m.y0!==21||

     m.width!==1536||m.height!==1536||

     !Number.isInteger(m.nombre_images)||m.nombre_images<2||m.nombre_images>8||

     m.gif!=="radar-rainviewer.gif"||

     !Array.isArray(m.observations_utc)||m.observations_utc.length!==m.nombre_images)

    throw Error("Manifeste RainViewer invalide ou incomplet");

  const age=(Date.now()-Date.parse(m.derniere_observation_utc))/60000;

  if(!Number.isFinite(age)||age < -5||age > RAINVIEWER_MAX_AGE_MIN)

    throw Error("Dernier GIF RainViewer périmé");

  return m;

}

function rainViewerCrop(m,city){
// Coordonnées Web Mercator XYZ strictement identiques aux tuiles RainViewer.*

  const lat=Math.max(-85,Math.min(85,city.lat))*Math.PI/180;

  const xc=((city.lon+180)/360*2**m.zoom-m.x0)*m.tile_size;

  const yc=((1-Math.asinh(Math.tan(lat))/Math.PI)/2*2**m.zoom-m.y0)*m.tile_size;

  if(xc<0||xc>=m.width||yc<0||yc>=m.height)

    throw Error("Ville hors de la zone radar RainViewer");

  const kmPerPixel=40075.016686*Math.cos(lat)/(m.tile_size*2**m.zoom);

  const side=Math.max(200,Math.min(850,Math.round(360/kmPerPixel)));

  const left=Math.max(0,Math.min(m.width-side,Math.round(xc-side/2)));

  const top=Math.max(0,Math.min(m.height-side,Math.round(yc-side/2)));

  return {trim:{left,right:m.width-side-left,top,bottom:m.height-side-top},

    pinX:Math.round((xc-left)*720/side),pinY:Math.round((yc-top)*720/side)};

}

async function radarEditOriginal(interaction,content,embed=null,file=null){

  const endpoint="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+"/"+interaction.token+"/messages/@original";

  let options;

  if(file){

    const filename="radar-rainviewer.gif";

    const form=new FormData();

    form.append("payload_json",JSON.stringify({

      content,allowed_mentions:{parse:[]},

      embeds:[{title:"KFS Météo · Radar animé RainViewer",

               image:{url:"attachment://"+filename},

               url:"https://www.rainviewer.com/"}],

      attachments:[{id:0,filename}]

    }));

    form.append("files[0]",new Blob([file],{type:"image/gif"}),filename);

    options={method:"PATCH",body:form};

  }else{

    const payload={content,allowed_mentions:{parse:[]}};

    if(embed)payload.embeds=[embed];

    options={method:"PATCH",headers:{"content-type":"application/json"},

             body:JSON.stringify(payload)};

  }

  const r=await fetch(endpoint,options);

  if(!r.ok)console.error("Discord /radar response failed",r.status,

                          (await r.text()).slice(0,350));

}

async function sendWindyFallback(interaction,city,reason){

  const link=windyRadarUrl(city.lat,city.lon);

  const title="Radar des précipitations · "+city.name+(city.dept?" ("+city.dept+")":"");

  const text="🌧️ **"+title+"**\n"+

    "⚠️ Animation RainViewer indisponible pour le moment ("+reason+").\n"+

    "🗺️ **Radar interactif Windy :** "+link+

    "\n▶️ Utilise la barre de lecture sur Windy pour afficher le déplacement des précipitations.";

  await radarEditOriginal(interaction,text,{title:"Voir le radar sur Windy",

    url:link,description:"Carte des précipitations centrée sur "+city.name,color:0x2874a6});

}

async function completeRadar(interaction,rawCity){

  let city;

  try{

    city=await radarVille(rawCity);

    const windy=windyRadarUrl(city.lat,city.lon);

    const m=await rainViewerManifest();

    const {trim,pinX,pinY}=rainViewerCrop(m,city);

    const gifUrl=RAINVIEWER_BASE+m.gif+"?observation="+

                 encodeURIComponent(m.derniere_observation_utc);

    const options={anim:true,trim,fit:"contain",width:720,height:720};

    const pin={url:RAINVIEWER_BASE+"radar-marker.png",

               width:56,height:56,

               left:Math.max(0,Math.min(664,pinX-28)),

               top:Math.max(0,Math.min(664,pinY-28))};

    let output=null;
// Si la superposition du repère échoue sur Cloudflare,*
// le GIF est quand même diffusé sans repère.*

    for(const transform of [{...options,draw:[pin]},options]){

      try{

        const response=await fetch(gifUrl,{cf:{image:transform}});

        if(!response.ok)throw Error("GIF HTTP "+response.status);

        const bytes=await response.arrayBuffer();

        if(bytes.byteLength<100||bytes.byteLength>8_000_000||

           !["GIF87a","GIF89a"].includes(new TextDecoder().decode(bytes.slice(0,6))))

          throw Error("GIF invalide ou trop volumineux pour Discord");

        output=bytes;

        break;

      }catch(error){

        console.warn("RainViewer /radar GIF: tentative suivante",String(error));

      }

    }

    if(!output)throw Error("transformation GIF indisponible");

    const date=new Date(m.derniere_observation_utc).toLocaleString("fr-FR",{

      timeZone:"Europe/Paris",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});

    const description="🌧️ **Radar animé · "+city.name+(city.dept?" ("+city.dept+")":"")+

      "** · 180 km autour\n"+

      "🕒 Dernière image : **"+date+"**\n"+
      "🗺️ **Carte interactive :** "+windy
     ;

    await radarEditOriginal(interaction,description,null,output);

  }catch(error){

    console.error("Radar RainViewer:",String(error));

    if(city){

      await sendWindyFallback(interaction,city,String(error.message||"service temporairement indisponible"));

    }else{

      await radarEditOriginal(interaction,"⚠️ /radar : "+String(error.message||"Ville introuvable."));

    }

  }

}

async function registerRadarCommand(env){

  if(!env.DISCORD_BOT_TOKEN)throw Error("Missing DISCORD_BOT_TOKEN");

  const command={name:"radar",description:"GIF RainViewer + radar Windy autour d'une ville française",type:1,

    options:[{type:3,name:"ville",description:"Ville (ex. Bourth ou Rouen, 76)",required:true,min_length:2,max_length:80}]};

  const r=await fetch("https://discord.com/api/v10/applications/"+APPLICATION_ID+"/commands",{

    method:"POST",

    headers:{"Authorization":"Bot "+env.DISCORD_BOT_TOKEN,"Content-Type":"application/json"},

    body:JSON.stringify(command)

  });

  if(!r.ok)throw Error("Discord /radar registration HTTP "+r.status+" : "+(await r.text()).slice(0,320));

  console.log("Discord /radar registered");

}

async function registerCommand(env) {

  if (!env.DISCORD_BOT_TOKEN) throw new Error("Missing DISCORD_BOT_TOKEN");

  const command={name:"meteo",description:"Prévisions météo par échéance",type:1,options:[{type:3,name:"ville",description:"Ville à prévoir",required:true,min_length:2,max_length:80},{type:3,name:"echeance",description:"Période souhaitée",required:true,choices:[{"name":"Aujourd'hui","value":"aujourdhui"},{"name":"Demain","value":"demain"},{"name":"5 jours","value":"5jours"},{"name":"15 jours","value":"15jours"},{"name":"1 mois","value":"1mois"},{"name":"Complet","value":"complet"}]}]};

  const response=await fetch("https://discord.com/api/v10/applications/"+APPLICATION_ID+"/commands",{

    method:"POST",

    headers:{"Authorization":"Bot "+env.DISCORD_BOT_TOKEN,"Content-Type":"application/json"},

    body:JSON.stringify(command)

  });

  if (!response.ok) {

    const detail=(await response.text()).slice(0,400);

    throw new Error("Discord command registration failed: HTTP "+response.status+" "+detail);

  }

  console.log("Discord /meteo command registered successfully");

}

export default {

  async scheduled(event,env,ctx) {
// Conserver /meteo et enregistrer /radar sans modifier les previsions.*

    ctx.waitUntil(Promise.all([registerCommand(env),registerRadarCommand(env)]));

  },

  async fetch(request,env,ctx) {

    const url=new URL(request.url);

    if (url.pathname==="/radar-status") {

      if(request.method!=="GET")return new Response("Method Not Allowed",{status:405});

      try{

        const m=await rainViewerManifest();

        return json({mode:"gif_discord",fournisseur:"RainViewer",

                     disponible:true,nombre_images:m.nombre_images,

                     derniere_observation_utc:m.derniere_observation_utc,

                     animation:RAINVIEWER_BASE+m.gif,

                     secours:"Windy"});

      }catch(error){

        return json({mode:"lien_windy_secours",fournisseur:"RainViewer",

                     disponible:false,probleme:String(error.message||error),

                     secours:"Windy"},503);

      }

    }

    if (url.pathname==="/register-radar") {

      if(request.method!=="POST")return new Response("Method Not Allowed",{status:405});

      if(!env.SETUP_KEY||request.headers.get("Authorization")!=="Bearer "+env.SETUP_KEY)

        return new Response("Unauthorized",{status:401});

      try{

        await registerRadarCommand(env);

        return json({ok:true,command:"radar"});

      }catch(error){return json({ok:false,error:String(error)},502);}

    }

    if (url.pathname==="/register-command") {

      if (request.method!=="POST") return new Response("Method Not Allowed",{status:405});

      const auth=request.headers.get("Authorization");

      if (!env.SETUP_KEY || !env.DISCORD_BOT_TOKEN || !auth || auth!=="Bearer "+env.SETUP_KEY) return new Response("Unauthorized",{status:401});

      const command={name:"meteo",description:"Prévisions météo par échéance",type:1,options:[{type:3,name:"ville",description:"Ville à prévoir",required:true,min_length:2,max_length:80},{type:3,name:"echeance",description:"Période souhaitée",required:true,choices:[{"name":"Aujourd'hui","value":"aujourdhui"},{"name":"Demain","value":"demain"},{"name":"5 jours","value":"5jours"},{"name":"15 jours","value":"15jours"},{"name":"1 mois","value":"1mois"},{"name":"Complet","value":"complet"}]}]};

      const result=await fetch("https://discord.com/api/v10/applications/"+APPLICATION_ID+"/commands",{

        method:"POST",headers:{"Authorization":"Bot "+env.DISCORD_BOT_TOKEN,"Content-Type":"application/json"},body:JSON.stringify(command)

      });

      const body=await result.text();

      return new Response(body,{status:result.status,headers:{"Content-Type":"application/json"}});

    }

    if (url.pathname!=="/discord") return new Response("KFS METEO Worker actif. Endpoint Discord : /discord");

    if (request.method!=="POST") return new Response("Method Not Allowed",{status:405});

    const raw=await request.text();

    if (!await valid(request,raw)) return new Response("Invalid request signature",{status:401});

    let interaction;

    try {interaction=JSON.parse(raw);} catch {return new Response("Invalid JSON",{status:400});}

    if (interaction.type===1) return json({type:1});

    if(interaction.type===2 && interaction.data?.name==="radar"){

      const ville=String(interaction.data.options?.find(x=>x.name==="ville")?.value||"").trim();

      if(ville.length<2||ville.length>80)return json({type:4,data:{content:"Indique une ville entre 2 et 80 caractères."}});

      ctx.waitUntil(completeRadar(interaction,ville));

      return json({type:5});

    }

    if (interaction.type!==2 || interaction.data?.name!=="meteo") return json({type:4,data:{content:"Commande non reconnue."}});

    const city=String(interaction.data.options?.find(x=>x.name==="ville")?.value||"").trim();

    if (city.length<2||city.length>80) return json({type:4,data:{content:"Indique une ville de 2 à 80 caractères."}});

    const echeance=String(interaction.data.options?.find(x=>x.name==="echeance")?.value||"");

    if(!["aujourdhui","demain","5jours","15jours","1mois","complet"].includes(echeance))return json({type:4,data:{content:"Choisis une échéance obligatoire."}});

    ctx.waitUntil(complete(interaction,city,echeance));

    return json({type:5}); // réponse différée PUBLIQUE

  }

};