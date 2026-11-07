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


// === /foudre ville : carte locale Xweather ===
// Secrets : XWEATHER_CLIENT_ID et XWEATHER_CLIENT_SECRET.
// Fenetre API standard : 5 min / rayon 100 km / maximum 1000 impulsions.

const F_W=600,F_H=600,F_X=300,F_Y=308,F_R=228;
const F_COLORS={bg:[15,28,44,255],grid:[46,69,84,255],border:[100,126,142,255],
  pos:[255,196,74,255],neg:[64,189,250,255],white:[240,248,255,255],
  black:[7,16,25,255]};
function foudreCanvas(){
  const pixels=new Uint8Array(F_W*F_H*4);
  const pixel=(x,y,c)=>{
    x=Math.round(x);y=Math.round(y);
    if(x<0||y<0||x>=F_W||y>=F_H)return;
    const i=(y*F_W+x)*4;
    pixels[i]=c[0];pixels[i+1]=c[1];pixels[i+2]=c[2];pixels[i+3]=c[3];
  };
  const rect=(x,y,w,h,c)=>{
    for(let yy=Math.max(0,Math.round(y));yy<Math.min(F_H,Math.round(y+h));yy++)
      for(let xx=Math.max(0,Math.round(x));xx<Math.min(F_W,Math.round(x+w));xx++)pixel(xx,yy,c);
  };
  const line=(xa,ya,xb,yb,c)=>{
    if(![xa,ya,xb,yb].every(Number.isFinite))return;
    if((xa < -50&&xb < -50)||(xa > 650&&xb > 650)||
       (ya < -50&&yb < -50)||(ya > 650&&yb > 650))return;
    let x=Math.round(xa),y=Math.round(ya),ex=Math.round(xb),ey=Math.round(yb);
    const dx=Math.abs(ex-x),dy=Math.abs(ey-y),sx=x<ex?1:-1,sy=y<ey?1:-1;
    if(dx+dy>2000)return;
    let err=dx-dy;
    for(let k=0;k<dx+dy+2;k++){
      pixel(x,y,c);if(x===ex&&y===ey)break;
      const e=err*2;
      if(e>-dy){err-=dy;x+=sx;}
      if(e<dx){err+=dx;y+=sy;}
    }
  };
  const dot=(x,y,r,c)=>{
    for(let yy=-r;yy<=r;yy++)for(let xx=-r;xx<=r;xx++)
      if(xx*xx+yy*yy<=r*r)pixel(x+xx,y+yy,c);
  };
  const circle=(cx,cy,r,c)=>{
    for(let i=0;i<900;i++){
      const a=i*2*Math.PI/900,b=(i+1)*2*Math.PI/900;
      line(cx+r*Math.cos(a),cy+r*Math.sin(a),cx+r*Math.cos(b),cy+r*Math.sin(b),c);
    }
  };
  const glyph={
    "0":["111","101","101","101","111"],"1":["010","110","010","010","111"],
    "2":["111","001","111","100","111"],"3":["111","001","111","001","111"],
    "4":["101","101","111","001","001"],"5":["111","100","111","001","111"],
    "6":["111","100","111","101","111"],"7":["111","001","010","010","010"],
    "8":["111","101","111","101","111"],"9":["111","101","111","001","111"],
    "+":["000","010","111","010","000"],"-":["000","000","111","000","000"]
  };
  const label=(s,x,y,c)=>{
    const v=String(s);rect(x-3,y-3,v.length*8+4,16,F_COLORS.black);
    for(let i=0;i<v.length;i++)for(let yy=0;yy<5;yy++)for(let xx=0;xx<3;xx++)
      if(glyph[v[i]]?.[yy]?.[xx]==="1")rect(x+i*8+xx*2,y+yy*2,2,2,c);
  };
  rect(0,0,F_W,F_H,F_COLORS.bg);
  return {pixels,pixel,rect,line,dot,circle,label};
}
function foudreXY(city,lat,lon){
  return [
    F_X+(lon-city.lon)*111.195*Math.cos(city.lat*Math.PI/180)*F_R/100,
    F_Y-(lat-city.lat)*111.195*F_R/100
  ];
}
async function foudreFond(canvas,city){
  const url="https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements.geojson";
  try{
    const response=await fetch(url,{cf:{cacheTtl:86400,cacheEverything:true}});
    if(!response.ok)return;
    const features=(await response.json()).features||[];
    for(const item of features){
      const geo=item.geometry||{};
      const polygons=geo.type==="Polygon"?[geo.coordinates]:
                     geo.type==="MultiPolygon"?geo.coordinates:[];
      for(const polygon of polygons)for(const ring of polygon){
        let last=null;
        for(const pair of ring){
          if(!pair||pair.length<2)continue;
          const p=foudreXY(city,pair[1],pair[0]);
          if(last)canvas.line(last[0],last[1],p[0],p[1],F_COLORS.grid);
          last=p;
        }
      }
    }
  }catch(e){console.warn("/foudre fond non disponible",String(e));}
}
function foudreConcat(...arr){
  const result=new Uint8Array(arr.reduce((n,x)=>n+x.length,0));
  let i=0;for(const x of arr){result.set(x,i);i+=x.length;}return result;
}
function foudreU32(n){return new Uint8Array([n>>>24&255,n>>>16&255,n>>>8&255,n&255]);}
function foudreCrc(data){
  let crc=0xffffffff;
  for(const value of data){
    crc^=value;
    for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);
  }
  return (crc^0xffffffff)>>>0;
}
function foudreChunk(type,payload){
  const name=new TextEncoder().encode(type);
  return foudreConcat(foudreU32(payload.length),name,payload,
                      foudreU32(foudreCrc(foudreConcat(name,payload))));
}
async function foudrePng(canvas){
  const stride=F_W*4+1,raw=new Uint8Array(stride*F_H);
  for(let y=0;y<F_H;y++)raw.set(
    canvas.pixels.subarray(y*F_W*4,(y+1)*F_W*4),y*stride+1);
  const compressed=new Uint8Array(await new Response(
    new Blob([raw]).stream().pipeThrough(new CompressionStream("deflate"))
  ).arrayBuffer());
  const header=foudreConcat(foudreU32(F_W),foudreU32(F_H),
                            new Uint8Array([8,6,0,0,0]));
  return foudreConcat(new Uint8Array([137,80,78,71,13,10,26,10]),
    foudreChunk("IHDR",header),foudreChunk("IDAT",compressed),
    foudreChunk("IEND",new Uint8Array()));
}
async function foudreData(city,env){
  if(!env.XWEATHER_CLIENT_ID||!env.XWEATHER_CLIENT_SECRET)
    throw Error("Identifiants Xweather absents de Cloudflare.");
  const lat=city.lat.toFixed(3),lon=city.lon.toFixed(3);
  // Cache de 90 secondes, pour diminuer la consommation du quota gratuit.
  const key=new Request("https://kfs-foudre-cache.invalid/"+lat+"/"+lon);
  const cache=caches.default;
  const hit=await cache.match(key);
  if(hit)return {...await hit.json(),cache:true};
  const params=new URLSearchParams({
    p:lat+","+lon,radius:"100km",limit:"1000",format:"json",
    client_id:env.XWEATHER_CLIENT_ID,client_secret:env.XWEATHER_CLIENT_SECRET
  });
  const res=await fetch("https://data.api.xweather.com/lightning/closest?"+params);
  if(!res.ok)throw Error("Xweather : erreur HTTP "+res.status);
  const obj=await res.json();
  if(obj.success!==true||!Array.isArray(obj.response))
    throw Error("Xweather : réponse non valide.");
  const collecte=Date.now();
  const pulses=obj.response.filter(x=>
    String(x?.ob?.pulse?.type||"").toLowerCase()==="cg"&&
    Number.isFinite(x?.ob?.pulse?.peakamp)&&
    Number.isFinite(x?.loc?.lat)&&Number.isFinite(x?.loc?.long)&&
    Number.isFinite(x?.ob?.timestamp)&&
    collecte/1000-x.ob.timestamp>=-30&&collecte/1000-x.ob.timestamp<=330
  ).map(x=>({amp:x.ob.pulse.peakamp,lat:x.loc.lat,lon:x.loc.long}));
  const value={pulses,collecte,limite:obj.response.length>=1000};
  await cache.put(key,new Response(JSON.stringify(value),{
    headers:{"Cache-Control":"public,max-age=90","Content-Type":"application/json"}
  }));
  return {...value,cache:false};
}
async function foudreImage(city,pulses){
  const c=foudreCanvas();
  for(let km=-100;km<=100;km+=50){
    const x=F_X+km*F_R/100,y=F_Y+km*F_R/100;
    c.line(x,40,x,570,F_COLORS.grid);
    c.line(40,y,560,y,F_COLORS.grid);
  }
  await foudreFond(c,city);
  c.circle(F_X,F_Y,F_R,F_COLORS.white);
  c.dot(F_X,F_Y,5,F_COLORS.white);
  const shown=[];
  for(const s of pulses){
    const [x,y]=foudreXY(city,s.lat,s.lon);
    if(Math.hypot(x-F_X,y-F_Y)>F_R)continue;
    shown.push({...s,x,y});
  }
  for(const s of shown){
    const color=s.amp>=0?F_COLORS.pos:F_COLORS.neg;
    const radius=Math.max(3,Math.min(9,3+Math.floor(Math.abs(s.amp)/25000)));
    c.dot(s.x,s.y,radius+2,F_COLORS.black);
    c.dot(s.x,s.y,radius,color);
    c.line(s.x-3,s.y,s.x+3,s.y,F_COLORS.black);
    if(s.amp>=0)c.line(s.x,s.y-3,s.x,s.y+3,F_COLORS.black);
  }
  // Sur la carte, nombres signes des 12 impacts les plus puissants, en kA.
  for(const s of [...shown].sort((a,b)=>Math.abs(b.amp)-Math.abs(a.amp)).slice(0,12)){
    const value=(s.amp>=0?"+":"-")+Math.round(Math.abs(s.amp)/1000);
    const x=Math.max(6,Math.min(F_W-value.length*8-6,Math.round(s.x+10)));
    const y=Math.max(5,Math.min(F_H-20,Math.round(s.y-22)));
    c.label(value,x,y,s.amp>=0?F_COLORS.pos:F_COLORS.neg);
  }
  return {png:await foudrePng(c),shown};
}
async function foudreMessage(interaction,content,png){
  const url="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+
            "/"+interaction.token+"/messages/@original";
  let options;
  if(png){
    const filename="foudre-kfs.png",form=new FormData();
    form.append("payload_json",JSON.stringify({
      content,allowed_mentions:{parse:[]},
      embeds:[{title:"KFS MÉTÉO · Foudre en direct",
               image:{url:"attachment://"+filename}}],
      attachments:[{id:0,filename}]
    }));
    form.append("files[0]",new Blob([png],{type:"image/png"}),filename);
    options={method:"PATCH",body:form};
  }else{
    options={method:"PATCH",headers:{"Content-Type":"application/json"},
             body:JSON.stringify({content,allowed_mentions:{parse:[]}})};
  }
  const response=await fetch(url,options);
  if(!response.ok)console.error("Discord /foudre",response.status,
                                (await response.text()).slice(0,300));
}
async function completeFoudre(interaction,rawCity,env){
  try{
    const city=await radarVille(rawCity);
    const result=await foudreData(city,env);
    const {png,shown}=await foudreImage(city,result.pulses);
    const plus=shown.filter(x=>x.amp>0).length,minus=shown.filter(x=>x.amp<0).length;
    const strongest=[...shown].sort((a,b)=>Math.abs(b.amp)-Math.abs(a.amp))
       .slice(0,4).map(x=>(x.amp>0?"+":"")+(x.amp/1000).toFixed(1)+" kA");
    const date=new Date(result.collecte).toLocaleString("fr-FR",{
      timeZone:"Europe/Paris",day:"2-digit",month:"2-digit",
      hour:"2-digit",minute:"2-digit"});
    const content="⚡ **KFS MÉTÉO — Foudre "+city.name+" ("+city.dept+")**\n"+
      "📍 Rayon 100 km · impacts nuage-sol · 5 min avant "+date+"\n"+
      "🟠 Positifs : **"+plus+"** · 🔵 Négatifs : **"+minus+"**\n"+
      (strongest.length?"⚡ Plus forts : **"+strongest.join(" · ")+"**\n":
          "Aucun impact nuage-sol détecté sur la période.\n")+
      "Carte : chiffres signés en kA, taille croissante avec le courant.\n"+
      (result.limite?"⚠️ Résultats limités à 1 000 impulsions.\n":"")+
      (result.cache?"_Données mises en cache jusqu'à 90 s._\n":"")+
      "_Données : [Powered by Vaisala Xweather](https://www.xweather.com/) · contours : france-geojson._";
    await foudreMessage(interaction,content,png);
  }catch(e){
    console.error("KFS /foudre",String(e));
    await foudreMessage(interaction,
      "⚠️ **/foudre indisponible** : "+String(e.message||"Erreur inconnue")+
      "\nAucun impact fictif n'a été ajouté.",null);
  }
}

// === /live : donnees meteorologiques recentes de modeles Open-Meteo ===
// Les valeurs sont modelisees, elles ne proviennent pas d'une station locale.
const LIVE_METEO=["temperature_2m","relative_humidity_2m","apparent_temperature",
"dew_point_2m","is_day","precipitation","rain","showers","snowfall","weather_code",
"cloud_cover","cloud_cover_low","cloud_cover_mid","cloud_cover_high","pressure_msl",
"surface_pressure","wind_speed_10m","wind_direction_10m","wind_gusts_10m",
"visibility","cape"].join(",");
const LIVE_AIR=["european_aqi","pm2_5","pm10","ozone","uv_index"].join(",");
const liveFinite=v=>typeof v==="number"&&Number.isFinite(v);
const liveFmt=(v,unit="",digits=1)=>liveFinite(v)?
  v.toLocaleString("fr-FR",{maximumFractionDigits:digits})+(unit?" "+unit:""):"n/d";
function liveCompass(v){
  const d=["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSO","SO","OSO","O","ONO","NO","NNO"];
  return liveFinite(v)?d[Math.round(((v%360)+360)%360/22.5)%16]+
    " ("+Math.round(v)+"°)":"n/d";
}
function liveSky(code){
  const m={0:"Ciel dégagé",1:"Peu nuageux",2:"Partiellement nuageux",3:"Couvert",
   45:"Brouillard",48:"Brouillard givrant",51:"Bruine",53:"Bruine",55:"Bruine dense",
   61:"Pluie faible",63:"Pluie",65:"Pluie forte",71:"Neige faible",73:"Neige",
   75:"Neige forte",80:"Averses",81:"Averses",82:"Fortes averses",
   95:"Orages",96:"Orages avec grêle",99:"Orages avec forte grêle"};
  return liveFinite(code)?m[code]||"Code temps "+code:"n/d";
}
function liveDate(s){
  if(typeof s!=="string")return {text:"n/d",age:null};
  const t=Date.parse(s+"Z"); // timezone=GMT, horodatage source UTC.
  if(!Number.isFinite(t))return {text:"n/d",age:null};
  const text=new Date(t).toLocaleString("fr-FR",{timeZone:"Europe/Paris",
    day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})+" (Paris)";
  return {text,age:(Date.now()-t)/60000};
}
function liveAqiLabel(v){
  if(!liveFinite(v))return "n/d";
  return v<=20?"bon":v<=40?"assez bon":v<=60?"moyen":v<=80?"mauvais":
         v<=100?"très mauvais":"extrêmement mauvais";
}
function liveReport(city,weather,air){
  const w=weather.current||{},a=air?.current||{};
  if(!liveFinite(w.temperature_2m))throw Error("Données météo actuelles indisponibles.");
  const date=liveDate(w.time),airDate=liveDate(a.time);
  const alert=date.age===null?"⚠️ Heure météo indisponible.\n":
    date.age>180?"⚠️ Données anciennes (plus de 3 heures).\n":
    date.age< -30?"⚠️ Échéance future du modèle.\n":"";
  const airBlock=air?
    "🌿 **Qualité de l'air (modèle CAMS)**\n"+
    "AQI européen : **"+liveFmt(a.european_aqi,"",0)+"** ("+
      liveAqiLabel(a.european_aqi)+")\n"+
    "PM2,5 : "+liveFmt(a.pm2_5,"µg/m³")+" · PM10 : "+liveFmt(a.pm10,"µg/m³")+"\n"+
    "Ozone : "+liveFmt(a.ozone,"µg/m³")+" · UV : "+liveFmt(a.uv_index)+"\n"+
    "Heure air : "+airDate.text+"\n\n":
    "🌿 **Qualité de l'air :** non disponible actuellement\n\n";
  const text=
    "📡 **KFS MÉTÉO — /live "+city.name+(city.dept?" ("+city.dept+")":"")+"**\n"+
    "🕒 Heure du modèle : **"+date.text+"**\n"+alert+
    "🌡️ **Température / humidité**\n"+
    "Température : **"+liveFmt(w.temperature_2m,"°C")+
      "** · Ressentie : **"+liveFmt(w.apparent_temperature,"°C")+"**\n"+
    "Humidité : **"+liveFmt(w.relative_humidity_2m,"%",0)+
      "** · Rosée : **"+liveFmt(w.dew_point_2m,"°C")+"**\n\n"+
    "💨 **Vent à 10 m**\n"+
    "Moyen : **"+liveFmt(w.wind_speed_10m,"km/h",0)+
      "** · Rafales : **"+liveFmt(w.wind_gusts_10m,"km/h",0)+"**\n"+
    "Origine : **"+liveCompass(w.wind_direction_10m)+"**\n\n"+
    "🌦️ **Ciel et précipitations**\n"+
    liveSky(w.weather_code)+" · "+(w.is_day===1?"Jour":w.is_day===0?"Nuit":"Heure inconnue")+"\n"+
    "Nébulosité : "+liveFmt(w.cloud_cover,"%",0)+" · bas/moyen/haut : "+
      liveFmt(w.cloud_cover_low,"%",0)+"/"+liveFmt(w.cloud_cover_mid,"%",0)+
      "/"+liveFmt(w.cloud_cover_high,"%",0)+"\n"+
    "Précipitations (pas actuel) : **"+liveFmt(w.precipitation,"mm",2)+"**"+
      " · pluie "+liveFmt(w.rain,"mm",2)+" · averses "+liveFmt(w.showers,"mm",2)+
      " · neige "+liveFmt(w.snowfall,"cm",2)+"\n"+
    "Visibilité : "+(liveFinite(w.visibility)?liveFmt(w.visibility/1000,"km"):"n/d")+
      " · CAPE : "+liveFmt(w.cape,"J/kg",0)+"\n\n"+
    "🧭 **Pression**\n"+
    "Niveau mer : **"+liveFmt(w.pressure_msl,"hPa")+
      "** · Surface : **"+liveFmt(w.surface_pressure,"hPa")+"**\n\n"+
    airBlock+
    "ℹ️ **Données récentes de modèles, pas de mesures d'une station météo.**"+
      " Les mises à jour ne sont pas continues.\n"+
    "_Sources : [Open-Meteo](https://open-meteo.com/) · "+
      "[CAMS](https://open-meteo.com/en/docs/air-quality-api)._";
  if(text.length>1900)throw Error("Message /live trop long.");
  return text;
}
async function liveJson(url){
  const r=await fetch(url);
  if(!r.ok)throw Error("Open-Meteo HTTP "+r.status);
  const obj=await r.json();
  if(obj.error)throw Error("Open-Meteo : "+String(obj.reason||"erreur"));
  return obj;
}
async function liveCurrent(city){
  const geo={latitude:String(city.lat),longitude:String(city.lon),timezone:"GMT"};
  const q=new URLSearchParams({...geo,current:LIVE_METEO,wind_speed_unit:"kmh",
    temperature_unit:"celsius",precipitation_unit:"mm"});
  const aq=new URLSearchParams({...geo,current:LIVE_AIR});
  const weather=await liveJson("https://api.open-meteo.com/v1/forecast?"+q);
  let air=null;
  try{air=await liveJson("https://air-quality-api.open-meteo.com/v1/air-quality?"+aq);}
  catch(e){console.warn("Air /live indisponible",String(e));}
  return {weather,air};
}

// === /live Weather Underground : PWS prioritaires, Open-Meteo en secours ===
// Station du compte : IBOURTH5, sur le secteur de Bourth.
// Publication WU DESACTIVEE par defaut, activation expresse via
// WEATHER_UNDERGROUND_DISCORD_ENABLED = "true" APRES validation du droit de publication.
// Cle API privee : WEATHER_UNDERGROUND_API_KEY dans les Secrets Cloudflare.

const WU_BASE="https://api.weather.com";
const WU_STATION="IBOURTH5";
const WU_MAX_RADIUS_KM=40;
const WU_MAX_OBS_AGE_MIN=25;
const WU_CACHE_SECONDS=300;
const wuOk=v=>typeof v==="number"&&Number.isFinite(v);
const wuFmt=(v,unit="",digits=1)=>wuOk(v)?
  v.toLocaleString("fr-FR",{maximumFractionDigits:digits})+(unit?" "+unit:""):"n/d";
function wuDegrees(v){
  const compass=["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSO","SO","OSO","O","ONO","NO","NNO"];
  return wuOk(v)?compass[Math.round(((v%360)+360)%360/22.5)%16]+
    " ("+Math.round(v)+"°)":"n/d";
}
function wuTimestamp(ob){
  const when=typeof ob.obsTimeUtc==="string"?Date.parse(ob.obsTimeUtc):
    wuOk(ob.epoch)?ob.epoch*1000:NaN;
  if(!Number.isFinite(when))throw Error("Horodatage PWS non valide.");
  const age=(Date.now()-when)/60000;
  if(age< -2||age>WU_MAX_OBS_AGE_MIN)
    throw Error("Observation PWS trop ancienne ou incohérente.");
  return {
    age,
    time:new Date(when).toLocaleString("fr-FR",{
      timeZone:"Europe/Paris",day:"2-digit",month:"2-digit",
      hour:"2-digit",minute:"2-digit",second:"2-digit"})
  };
}
function wuDistKm(from,to){
  const rad=Math.PI/180, dLat=(to.lat-from.lat)*rad,dLon=(to.lon-from.lon)*rad;
  const a=Math.sin(dLat/2)**2+Math.cos(from.lat*rad)*Math.cos(to.lat*rad)*
    Math.sin(dLon/2)**2;
  return 6371*2*Math.atan2(Math.sqrt(a),Math.sqrt(Math.max(0,1-a)));
}
async function wuFetch(path,params,key){
  const q=new URLSearchParams({...params,apiKey:key});
  const r=await fetch(WU_BASE+path+"?"+q.toString());
  if(!r.ok)throw Error("Weather Underground : HTTP "+r.status);
  const obj=await r.json();
  if(!obj||typeof obj!=="object")throw Error("Weather Underground : réponse invalide.");
  return obj;
}
async function wuNearest(city,apiKey){
  if(radarNorm(city.name)==="bourth")
    return [{id:WU_STATION,name:"Bourth – la Morière",distanceKm:null}];
  const o=await wuFetch("/v3/location/near",{
    geocode:city.lat.toFixed(4)+","+city.lon.toFixed(4),product:"pws",format:"json"},apiKey);
  const l=o.location||{};
  if(!Array.isArray(l.stationId))throw Error("Aucune liste PWS disponible.");
  return l.stationId.map((id,i)=>({
    id,name:l.stationName?.[i]||id,
    distanceKm:Number(l.distanceKm?.[i]),
    qc:Number(l.qcStatus?.[i]),
    lastEpoch:Number(l.updateTimeUtc?.[i])
  })).filter(s=>typeof s.id==="string"&&/^[A-Z0-9]{4,20}$/i.test(s.id)&&
    Number.isFinite(s.distanceKm)&&s.distanceKm<=WU_MAX_RADIUS_KM&&
    s.qc!==0&&(!Number.isFinite(s.lastEpoch)||
       Date.now()/1000-s.lastEpoch<=WU_MAX_OBS_AGE_MIN*60))
     .slice(0,4);
}
async function wuObservation(station,city,apiKey){
  const o=await wuFetch("/v2/pws/observations/current",{
    stationId:station.id,format:"json",units:"m",numericPrecision:"decimal"},apiKey);
  const ob=o.observations?.[0];
  if(!ob||String(ob.stationID).toUpperCase()!==station.id.toUpperCase())
    throw Error("Station "+station.id+" sans observation récente.");
  if(Number(ob.qcStatus)===0)throw Error("Observation PWS rejetée par contrôle qualité.");
  const stamp=wuTimestamp(ob);
  if(!ob.metric||!wuOk(ob.metric.temp))
    throw Error("Température PWS indisponible.");
  const distanceKm=wuOk(ob.lat)&&wuOk(ob.lon)?
    wuDistKm(city,{lat:ob.lat,lon:ob.lon}):station.distanceKm;
  if(wuOk(distanceKm)&&distanceKm>WU_MAX_RADIUS_KM)
    throw Error("Station trop éloignée de la localité.");
  return {ob,distanceKm,stamp,stationName:station.name||ob.neighborhood||station.id};
}
async function wuCurrent(city,env){
  if(!env.WEATHER_UNDERGROUND_API_KEY)
    throw Error("Clé Weather Underground absente.");
  if(env.WEATHER_UNDERGROUND_DISCORD_ENABLED!=="true")
    throw Error("Diffusion Weather Underground non activée : autorisation d'utilisation à confirmer.");
  const key=env.WEATHER_UNDERGROUND_API_KEY;
  const cacheKey=new Request("https://kfs-pws-cache.invalid/live/"+
    city.lat.toFixed(3)+"/"+city.lon.toFixed(3));
  const cached=await caches.default.match(cacheKey);
  if(cached){
    const value=await cached.json();
    // Ne jamais resservir un relevé devenu trop vieux.
    if(Date.now()-value.obEpoch<=WU_MAX_OBS_AGE_MIN*60000)
      return {...value,fromCache:true};
  }
  const stations=await wuNearest(city,key);
  if(!stations.length)throw Error("Aucune station PWS récente dans un rayon de 40 km.");
  let lastError="Station sans observation exploitable.";
  for(const station of stations){
    try{
      const current=await wuObservation(station,city,key);
      const record={...current,obEpoch:Date.parse(current.ob.obsTimeUtc),
        stationId:station.id};
      // Éviter les valeurs sensibles dans les caches : aucune clé dans le résultat.
      const response=new Response(JSON.stringify(record),{headers:{
        "Content-Type":"application/json","Cache-Control":"public,max-age="+WU_CACHE_SECONDS}});
      await caches.default.put(cacheKey,response);
      return {...record,fromCache:false};
    }catch(e){lastError=String(e.message||e);}
  }
  throw Error("Aucune mesure PWS valide : "+lastError);
}
function wuReport(city,pws){
  const {ob,stamp,distanceKm,stationId,stationName}=pws;
  const m=ob.metric||{},label=(ob.neighborhood||stationName||stationId).slice(0,80);
  const stationUrl="https://www.wunderground.com/dashboard/pws/"+stationId;
  return "📡 **KFS MÉTÉO — /live "+city.name+
    (city.dept?" ("+city.dept+")":"")+"**\n"+
    "🛰️ **Véritables mesures d'une station Weather Underground (PWS)**\n"+
    "📍 Station : **"+label+"** · "+stationId+"\n"+
    (wuOk(distanceKm)?"Distance : "+wuFmt(distanceKm,"km")+" de "+city.name+"\n":"")+
    "🕒 Dernier relevé : **"+stamp.time+"** (Paris)"+
      " · il y a "+wuFmt(stamp.age,"min",0)+"\n\n"+
    "🌡️ **Température et humidité**\n"+
    "• Température : **"+wuFmt(m.temp,"°C")+"**"+
      " · Humidité : **"+wuFmt(ob.humidity,"%",0)+"**\n"+
    "• Point de rosée : **"+wuFmt(m.dewpt,"°C")+"**\n"+
    "• Refroidissement éolien : "+wuFmt(m.windChill,"°C")+
      " · Indice de chaleur : "+wuFmt(m.heatIndex,"°C")+"\n\n"+
    "💨 **Vent**\n"+
    "• Moyen : **"+wuFmt(m.windSpeed,"km/h")+"**"+
      " · Rafales : **"+wuFmt(m.windGust,"km/h")+"**\n"+
    "• Direction d'origine : **"+wuDegrees(ob.winddir)+"**\n\n"+
    "🌧️ **Précipitations mesurées**\n"+
    "• Intensité instantanée : **"+wuFmt(m.precipRate,"mm/h",2)+"**\n"+
    "• Cumul depuis minuit (heure de la station) : **"+
      wuFmt(m.precipTotal,"mm",2)+"**\n\n"+
    "🧭 **Autres mesures**\n"+
    "• Pression ramenée au niveau de la mer : **"+wuFmt(m.pressure,"hPa")+"**\n"+
    "• Rayonnement solaire : "+wuFmt(ob.solarRadiation,"W/m²",0)+
      " · Indice UV : "+wuFmt(ob.uv,"",1)+"\n"+
    (Number(ob.qcStatus)===-1?"⚠️ Mesure non encore validée par le contrôle qualité.\n":"")+
    (pws.fromCache?"_Réponse conservée en cache 5 minutes au maximum._\n":"")+
    "🔗 "+stationUrl+"\n"+
    "_Data provided by Weather Underground. "+
      "Mesures de station individuelle non représentatives de toute la commune._";
}

async function liveSend(interaction,message){
  const url="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+
            "/"+interaction.token+"/messages/@original";
  const r=await fetch(url,{method:"PATCH",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({content:message,allowed_mentions:{parse:[]}})});
  if(!r.ok)console.error("/live Discord",r.status,(await r.text()).slice(0,200));
}
async function completeLive(interaction,ville,env){
  try{
    const city=await radarVille(ville);
    if(env.WEATHER_UNDERGROUND_API_KEY&&
       env.WEATHER_UNDERGROUND_DISCORD_ENABLED==="true"){
      try{
        const pws=await wuCurrent(city,env);
        await liveSend(interaction,wuReport(city,pws));
        return;
      }catch(error){
        console.warn("/live PWS indisponible, repli modèle",String(error.message||error));
      }
    }
    // Repli explicite : estimations Open-Meteo (aucune mesure PWS inventée).
    const {weather,air}=await liveCurrent(city);
    const note=env.WEATHER_UNDERGROUND_DISCORD_ENABLED==="true"?
      "⚠️ Station Weather Underground indisponible : **repli sur modèles Open-Meteo**.\n\n":
      "ℹ️ Source Weather Underground désactivée. **Estimations Open-Meteo**.\n\n";
    await liveSend(interaction,note+liveReport(city,weather,air));
  }catch(error){
    console.error("KFS /live",String(error));
    await liveSend(interaction,"⚠️ **/live indisponible** : "+
      String(error.message||"Erreur météo temporaire")+
      "\nAucune valeur fictive n'a été affichée.");
  }
}
async function registerLiveCommand(env){
  if(!env.DISCORD_BOT_TOKEN)throw Error("Missing DISCORD_BOT_TOKEN");
  const command={name:"live",type:1,
    description:"Météo locale actuelle : température, vent, pluie, pression, qualité de l'air",
    options:[{type:3,name:"ville",description:"Commune française (ex. Bourth ou Rouen, 76)",
              required:true,min_length:2,max_length:80}]};
  const r=await fetch("https://discord.com/api/v10/applications/"+
    APPLICATION_ID+"/commands",{method:"POST",headers:{
    "Authorization":"Bot "+env.DISCORD_BOT_TOKEN,"Content-Type":"application/json"},
    body:JSON.stringify(command)});
  if(!r.ok)throw Error("Discord /live HTTP "+r.status+" "+(await r.text()).slice(0,250));
}

async function registerFoudreCommand(env){
  if(!env.DISCORD_BOT_TOKEN)throw Error("Missing DISCORD_BOT_TOKEN");
  const command={name:"foudre",type:1,
    description:"Carte foudre en temps réel, polarité et kA autour d'une ville",
    options:[{type:3,name:"ville",required:true,min_length:2,max_length:80,
              description:"Ville française (ex. Bourth ou Rouen, 76)"}]};
  const r=await fetch("https://discord.com/api/v10/applications/"+APPLICATION_ID+"/commands",{
    method:"POST",headers:{"Authorization":"Bot "+env.DISCORD_BOT_TOKEN,
      "Content-Type":"application/json"},body:JSON.stringify(command)});
  if(!r.ok)throw Error("Discord /foudre HTTP "+r.status+" "+(await r.text()).slice(0,300));
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

    ctx.waitUntil(Promise.all([registerCommand(env),registerRadarCommand(env),registerFoudreCommand(env),registerLiveCommand(env)]));

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

    if (url.pathname==="/register-live") {
      if(request.method!=="POST")return new Response("Method Not Allowed",{status:405});
      if(!env.SETUP_KEY||request.headers.get("Authorization")!=="Bearer "+env.SETUP_KEY)
        return new Response("Unauthorized",{status:401});
      try{await registerLiveCommand(env);return json({ok:true,command:"live"});}
      catch(error){return json({ok:false,error:String(error)},502);}
    }

    if (url.pathname==="/register-foudre") {
      if(request.method!=="POST")return new Response("Method Not Allowed",{status:405});
      if(!env.SETUP_KEY||request.headers.get("Authorization")!=="Bearer "+env.SETUP_KEY)
        return new Response("Unauthorized",{status:401});
      try{await registerFoudreCommand(env);return json({ok:true,command:"foudre"});}
      catch(e){return json({ok:false,error:String(e)},502);}
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

    if(interaction.type===2 && interaction.data?.name==="live"){
      const ville=String(interaction.data.options?.find(x=>x.name==="ville")?.value||"").trim();
      if(ville.length<2||ville.length>80)
        return json({type:4,data:{content:"Indique une ville de 2 à 80 caractères."}});
      ctx.waitUntil(completeLive(interaction,ville,env));
      return json({type:5});
    }

    if(interaction.type===2 && interaction.data?.name==="foudre"){
      const ville=String(interaction.data.options?.find(x=>x.name==="ville")?.value||"").trim();
      if(ville.length<2||ville.length>80)
        return json({type:4,data:{content:"Indique une ville entre 2 et 80 caractères."}});
      ctx.waitUntil(completeFoudre(interaction,ville,env));
      return json({type:5});
    }

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