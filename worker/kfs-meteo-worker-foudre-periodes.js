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
          // Écarter les points hors secteur, afin de réduire le coût CPU.
          const dx=Math.abs(Number(pair[0])-city.lon);
          const dy=Math.abs(Number(pair[1])-city.lat);
          if(dx>2.2||dy>1.5){last=null;continue;}
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
const FOUDRE_CRC_TABLE=Uint32Array.from({length:256},(_,i)=>{
  let c=i;
  for(let k=0;k<8;k++)c=(c>>>1)^((c&1)?0xedb88320:0);
  return c>>>0;
});
function foudreCrc(data){
  let crc=0xffffffff;
  for(let i=0;i<data.length;i++)
    crc=FOUDRE_CRC_TABLE[(crc^data[i])&255]^(crc>>>8);
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
  let obj;
  try{obj=await res.json();}
  catch{throw Error("Xweather : réponse HTTP "+res.status+" non JSON.");}
  const errorCode=String(obj?.error?.code||"").slice(0,55).replace(/[^A-Za-z0-9_-]/g,"");
  const warnings=(Array.isArray(obj?.warnings)?obj.warnings:[obj?.warning,obj?.error])
    .map(w=>String(w?.code||""));
  const noData=(errorCode==="warn_no_data"||warnings.includes("warn_no_data"));
  if(noData){
    const empty={pulses:[],collecte:Date.now(),limite:false};
    await cache.put(key,new Response(JSON.stringify(empty),{
      headers:{"Cache-Control":"public,max-age=90","Content-Type":"application/json"}
    }));
    return {...empty,cache:false};
  }
  if(!res.ok)
    throw Error("Xweather HTTP "+res.status+(errorCode?" ("+errorCode+")":""));
  if(obj.success!==true||!Array.isArray(obj.response))
    throw Error("Xweather : réponse inattendue"+(errorCode?" ("+errorCode+")":"")+".");
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

// === /foudre : statistiques sur 5 min, 30 min, 1 h, 6 h et 24 h ===
// La carte montre uniquement les décharges CG des cinq dernières minutes.
// Lightning Summary fournit des totaux incluant CG et IC, pas un historique géolocalisé.
const FOUDRE_PERIODES={5:"5 minutes",30:"30 minutes",60:"1 heure",360:"6 heures",1440:"24 heures"};
const FOUDRE_FROM={30:"-30minutes",60:"-1hour",360:"-6hours",1440:"-24hours"};
const FOUDRE_SUMMARY_CACHE_S=120;
const foudreNombre=n=>Number.isFinite(n)&&n>=0?n.toLocaleString("fr-FR"):"n/d";
const foudreKA=n=>Number.isFinite(n)?(n/1000).toLocaleString("fr-FR",{
  maximumFractionDigits:1})+" kA":"n/d";
function foudrePeriode(minutes){
  const n=Number(minutes??30);
  if(!Object.prototype.hasOwnProperty.call(FOUDRE_PERIODES,String(n)))
    throw Error("Période invalide : choisir 5, 30, 60, 360 ou 1440 minutes.");
  return n;
}
function foudreSummaryRange(summary,minutes){
  const range=summary?.range;
  if(!range||!Number.isFinite(range.fromTimestamp)||!Number.isFinite(range.toTimestamp))
    throw Error("Lightning Summary : fenêtre temporelle impossible à vérifier.");
  const diff=range.toTimestamp-range.fromTimestamp;
  // Si l'API a ignoré le paramètre from, interdire d'annoncer 30 min alors que 5 min ont été obtenues.
  if(Math.abs(diff-minutes*60)>120)
    throw Error("Lightning Summary : période renvoyée différente de "+FOUDRE_PERIODES[minutes]+".");
  // Une réponse ancienne ne doit pas être présentée comme une mesure en direct.
  const age=Date.now()/1000-range.toTimestamp;
  if(age>900||age< -120)
    throw Error("Lightning Summary : horaire de fin trop ancien ou futur.");
  return range;
}
function foudreSummaryConvert(api,minutes){
  const payload=Array.isArray(api?.response)?api.response[0]:api?.response;
  const s=payload?.summary;
  if(!s||typeof s!=="object")
    throw Error("Lightning Summary : données statistiques absentes.");
  const range=foudreSummaryRange(s,minutes);
  const p=s.pulse||{},amp=s.peakAmp||{};
  const count=Number.isFinite(p.count)?p.count:
              Number.isFinite(s.range.count)?s.range.count:null;
  if(count===null||count<0||!Number.isInteger(count))
    throw Error("Lightning Summary : total de décharges invalide.");
  const pick=v=>Number.isFinite(v)&&v>=0&&Number.isInteger(v)?v:null;
  return {
    windowFrom:range.fromTimestamp,windowTo:range.toTimestamp,
    count,cg:pick(p.cg),ic:pick(p.ic),
    positive:pick(p.positive),negative:pick(p.negative),
    maxPositive:Number.isFinite(amp?.positive?.max)?amp.positive.max:null,
    maxNegative:Number.isFinite(amp?.negative?.max)?amp.negative.max:null
  };
}
function foudreSummaryError(res,obj){
  const code=String(obj?.error?.code||"").replace(/[^a-zA-Z0-9_-]/g,"").slice(0,64);
  if(res.status===401||code==="invalid_client")
    return "Clé Xweather refusée (401).";
  if(res.status===403||code==="insufficient_scope"||code==="unauthorized_namespace")
    return "Lightning Summary non autorisé sur ce compte Xweather.";
  if(res.status===429||code.startsWith("maxhits"))
    return "Quota Xweather atteint (429).";
  return "Lightning Summary : HTTP "+res.status+(code?" ("+code+")":"")+".";
}
async function foudreSummary(city,minutes,env){
  if(!FOUDRE_FROM[minutes])throw Error("Lightning Summary : période non prise en charge.");
  if(!env.XWEATHER_CLIENT_ID||!env.XWEATHER_CLIENT_SECRET)
    throw Error("Identifiants Xweather absents dans Cloudflare.");
  const lat=city.lat.toFixed(3),lon=city.lon.toFixed(3);
  const cacheKey=new Request("https://kfs-foudre-summary.invalid/"+
    minutes+"/"+lat+"/"+lon);
  const hit=await caches.default.match(cacheKey);
  if(hit){
    const saved=await hit.json();
    // Ne pas servir de statistiques périmées si le cache dépasse sa durée autorisée.
    if(saved?.collecte&&Date.now()-saved.collecte<FOUDRE_SUMMARY_CACHE_S*1000)
      return {...saved,cache:true};
  }
  const q=new URLSearchParams({
    p:lat+","+lon,radius:"100km",
    from:FOUDRE_FROM[minutes],to:"now",format:"json",
    client_id:env.XWEATHER_CLIENT_ID,
    client_secret:env.XWEATHER_CLIENT_SECRET
  });
  // Action "closest" documentée pour Lightning Summary.
  const res=await fetch("https://data.api.xweather.com/lightning/summary/closest?"+q);
  let obj;
  try{obj=await res.json();}catch{
    throw Error("Lightning Summary : réponse non JSON (HTTP "+res.status+").");
  }
  const code=String(obj?.error?.code||"");
  if(!res.ok||code==="invalid_client"||code==="insufficient_scope"||
     code==="unauthorized_namespace"||code.startsWith("maxhits"))
    throw Error(foudreSummaryError(res,obj));
  if(code==="warn_invalid_param")
    throw Error("Lightning Summary : paramètres de période refusés (ou non autorisés).");
  if(code==="warn_no_data"){
    const empty={state:"empty",collecte:Date.now()};
    await caches.default.put(cacheKey,new Response(JSON.stringify(empty),{
      headers:{"Cache-Control":"public,max-age="+FOUDRE_SUMMARY_CACHE_S,
               "Content-Type":"application/json"}}));
    return {...empty,cache:false};
  }
  if(obj?.success!==true)
    throw Error(foudreSummaryError(res,obj));
  if(Array.isArray(obj.response)&&obj.response.length===0){
    const empty={state:"empty",collecte:Date.now()};
    await caches.default.put(cacheKey,new Response(JSON.stringify(empty),{
      headers:{"Cache-Control":"public,max-age="+FOUDRE_SUMMARY_CACHE_S,
               "Content-Type":"application/json"}}));
    return {...empty,cache:false};
  }
  const value={state:"ok",data:foudreSummaryConvert(obj,minutes),collecte:Date.now()};
  await caches.default.put(cacheKey,new Response(JSON.stringify(value),{
    headers:{"Cache-Control":"public,max-age="+FOUDRE_SUMMARY_CACHE_S,
             "Content-Type":"application/json"}}));
  const cost=res.headers?.get("X-Cost-Tokens");
  if(cost&&/^\d+$/.test(cost))console.log("KFS /foudre Summary, crédits API :",cost);
  return {...value,cache:false};
}
function foudreSummaryLines(summary,minutes){
  if(!summary)return "⚠️ Statistiques "+FOUDRE_PERIODES[minutes]+
    " indisponibles : aucune donnée inventée.\n";
  if(summary.state==="error")
    return "⚠️ **Statistiques "+FOUDRE_PERIODES[minutes]+" indisponibles** : "+
      String(summary.message||"Erreur API").slice(0,190)+"\n";
  if(summary.state==="empty")
    return "ℹ️ **Statistiques "+FOUDRE_PERIODES[minutes]+"** : "+
      "aucune décharge trouvée par Lightning Summary.\n";
  const p=summary.data;
  return "📊 **Bilan Lightning Summary · "+FOUDRE_PERIODES[minutes]+"**\n"+
    "• Total des décharges **CG + IC** : **"+foudreNombre(p.count)+"**\n"+
    "• Nuage-sol (CG) : **"+foudreNombre(p.cg)+
      "** · intranuageux (IC) : **"+foudreNombre(p.ic)+"**\n"+
    "• Polarité (CG + IC) : 🟠 positives **"+foudreNombre(p.positive)+
      "** · 🔵 négatives **"+foudreNombre(p.negative)+"**\n"+
    "• Crête max positive : **"+(p.maxPositive===null?"n/d":"+"+foudreKA(Math.abs(p.maxPositive)))+
      "** · max négative : **"+(p.maxNegative===null?"n/d":"−"+foudreKA(Math.abs(p.maxNegative)))+"**\n";
}
async function completeFoudre(interaction,rawCity,env,rawPeriode=30){
  try{
    const periode=foudrePeriode(rawPeriode);
    const city=await radarVille(rawCity);
    // La carte 5 min et les statistiques Summary sont des requêtes distinctes.
    // Elles sont indépendantes : une panne du Summary n'empêche pas l'affichage de la carte.
    const requests=[foudreData(city,env)];
    if(periode>5)requests.push(foudreSummary(city,periode,env));
    const settled=await Promise.allSettled(requests);
    const strikes=settled[0].status==="fulfilled"?settled[0].value:null;
    const mapError=settled[0].status==="rejected"?
      String(settled[0].reason?.message||settled[0].reason).slice(0,170):null;
    const summary=periode===5?null:
      settled[1].status==="fulfilled"?settled[1].value:
      {state:"error",message:String(settled[1].reason?.message||settled[1].reason)};
    // Même sans détection d'impacts, conserver la carte du secteur.
    // Distinguer une réponse vide d'une erreur d'accès à la source.
    const heure=new Date(strikes?.collecte||summary?.collecte||Date.now())
      .toLocaleString("fr-FR",{timeZone:"Europe/Paris",
        day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
    let message="⚡ **KFS MÉTÉO — Foudre "+city.name+" ("+city.dept+")**\n"+
      "📍 Rayon **100 km** · période choisie : **"+FOUDRE_PERIODES[periode]+
      "** · consultation "+heure+"\n\n";
    if(periode>5)message+=foudreSummaryLines(summary,periode)+"\n";
    if(strikes){
      const plus=strikes.pulses.filter(x=>x.amp>0).length;
      const minus=strikes.pulses.filter(x=>x.amp<0).length;
      message+="🗺️ **Carte des impacts CG : 5 dernières minutes uniquement**\n"+
        "🟠 Positifs : **"+foudreNombre(plus)+
        "** · 🔵 Négatifs : **"+foudreNombre(minus)+"**\n";
      const biggest=[...strikes.pulses].sort((a,b)=>Math.abs(b.amp)-Math.abs(a.amp))
        .slice(0,4).map(x=>(x.amp>=0?"+":"−")+
          foudreKA(Math.abs(x.amp)));
      if(biggest.length)message+="⚡ Courants récents les plus forts : **"+
        biggest.join(" · ")+"**\n";
      if(strikes.limite)message+="⚠️ Liste récente limitée à 1 000 décharges ; compteurs partiels.\n";
      if(strikes.cache)message+="_Carte basée sur un cache de 90 secondes au maximum._\n";
      if(strikes.pulses.length===0)
        message+="Aucun impact nuage-sol récent détecté : carte sans impact.\n";
    }else{
      message+="⚠️ **Carte 5 min indisponible** : "+mapError+
        ". Les statistiques ne sont pas une carte historique.\n";
    }
    message+="_Source : [Vaisala Xweather](https://www.xweather.com/)"+
      " · 30 min à 24 h = agrégats, sans positions historiques._";
    if(message.length>1950)message=message.slice(0,1940);
    // Toujours envoyer la carte du secteur, y compris lorsque le nombre d'impacts est zéro.
    // Si l'API est en échec, ne pas présenter ce fond vide comme un ciel sans foudre.
    try{
      const {png}=await foudreImage(city,strikes?.pulses||[]);
      await foudreMessage(interaction,message,png);
      return;
    }catch(e){
      console.error("KFS /foudre rendu PNG",String(e));
      message+="\n⚠️ Carte PNG indisponible : "+String(e.message||e).slice(0,100);
    }
    await foudreMessage(interaction,message,null);
  }catch(e){
    console.error("KFS /foudre",String(e));
    await foudreMessage(interaction,
      "⚠️ **/foudre indisponible** : "+String(e.message||"Erreur inconnue")+
      "\nAucune donnée météorologique inventée.",null);
  }
}

// === /live Infoclimat UNIQUEMENT : station récente la plus proche ===
// Catalogue public GeoJSON Infoclimat, mesures depuis l'API OpenData authentifiée.
// Clé API liée à l'IP source : pour Cloudflare, utiliser un relais IP fixe autorisé.
// Secrets possibles : INFOCLIMAT_RELAY_URL + INFOCLIMAT_RELAY_SECRET (conseillé)
// ou INFOCLIMAT_API_TOKEN (accès direct susceptible d'être refusé sur Cloudflare).
// Pas de Weather Underground ni de secours Open-Meteo dans /live.

const IC_CATALOGUE="https://www.infoclimat.fr/opendata/stations_xhr.php?format=geojson";
const IC_DATA="https://www.infoclimat.fr/opendata/";
const IC_MAX_CANDIDATES=12;
const IC_MAX_AGE_MIN=100;
const IC_CACHE_SECONDS=900; // fair use : 15 min.
const icNum=x=>{
  if(x===null||x===undefined||x===""||typeof x==="boolean")return null;
  const n=typeof x==="number"?x:Number(String(x).replace(",","."));
  return Number.isFinite(n)&&n>-900&&n<1e9?n:null;
};
const icValue=(v,unit="",digits=1)=>{
  const n=icNum(v);
  return n===null?"non disponible":n.toLocaleString("fr-FR",{
    maximumFractionDigits:digits})+(unit?" "+unit:"");
};
function icHaversine(a,b){
  const rad=Math.PI/180,dLat=(b.lat-a.lat)*rad,dLon=(b.lon-a.lon)*rad;
  const z=Math.sin(dLat/2)**2+Math.cos(a.lat*rad)*Math.cos(b.lat*rad)*
    Math.sin(dLon/2)**2;
  return 6371*2*Math.atan2(Math.sqrt(z),Math.sqrt(Math.max(0,1-z)));
}
function icStationFromFeature(f){
  const p=f?.properties||{};
  const c=f?.geometry?.coordinates;
  if(!Array.isArray(c)||c.length<2)return null;
  const lon=icNum(c[0]),lat=icNum(c[1]);
  const rawId=p.id_station??p.idStation??p.station_id??p.code_station??
    p.code??p.id??f.id;
  const id=String(rawId??"").trim();
  if(!id||!/^[A-Za-z0-9_-]{4,25}$/.test(id)||
     lat===null||lon===null||lat < -90||lat>90||lon < -180||lon>180)return null;
  return {
    id,lat,lon,
    name:String(p.nom??p.name??p.station??p.libelle??p.station_name??
      p.nom_station??id).trim().slice(0,90),
    license:String(p.licence??p.license??"").slice(0,90)
  };
}
async function icStations(city){
  const cache=caches.default,cacheKey=new Request("https://kfs-ic-cache.invalid/catalogue");
  let geo;
  try{
    const cached=await cache.match(cacheKey);
    if(cached)geo=await cached.json();
    else{
      const r=await fetch(IC_CATALOGUE,{headers:{accept:"application/geo+json,application/json"}});
      if(!r.ok)throw Error("Catalogue Infoclimat HTTP "+r.status);
      const body=await r.text();
      if(body.length>5_000_000)throw Error("Catalogue Infoclimat trop volumineux.");
      geo=JSON.parse(body);
      if(!Array.isArray(geo.features)||geo.features.length===0)
        throw Error("Catalogue Infoclimat sans stations.");
      // Cache partagé : ne solliciter Infoclimat qu'une fois par jour et par cache.
      await cache.put(cacheKey,new Response(JSON.stringify(geo),{
        headers:{"Content-Type":"application/json","Cache-Control":"public,max-age=86400"}}));
    }
  }catch(e){throw Error("Catalogue des stations indisponible : "+String(e.message||e));}
  const stations=geo.features.map(icStationFromFeature).filter(Boolean)
    .map(s=>({...s,distanceKm:icHaversine(city,s)}))
    .sort((a,b)=>a.distanceKm-b.distanceKm);
  if(!stations.length)
    throw Error("Aucune station compatible dans le catalogue Infoclimat.");
  return stations.slice(0,IC_MAX_CANDIDATES);
}
function icTimestamp(time){
  if(time===null||time===undefined)return null;
  if(typeof time==="number"){
    const stamp=time<1e12?time*1000:time;return Number.isFinite(stamp)?stamp:null;
  }
  const s=String(time).trim();
  const normalized=/^\d{4}-\d\d-\d\d \d\d:\d\d/.test(s)?s.replace(" ","T"):s;
  const utc=/(?:Z|[+-]\d\d:?\d\d)$/i.test(normalized)?normalized:normalized+"Z";
  const t=Date.parse(utc);
  return Number.isFinite(t)?t:null;
}
function icDecode(json,id){
  const h=json?.hourly;
  if(!h||typeof h!=="object")return null;
  const rows=h[id]??h[String(id)]??h[id.toUpperCase()]??h[id.toLowerCase()];
  if(!Array.isArray(rows)||!rows.length)return null;
  const now=Date.now();
  const valid=rows.filter(x=>{
    const t=icTimestamp(x.dh_utc??x.datetime??x.timestamp??x.date);
    return t!==null&&t<=now+5*60000&&t>=now-IC_MAX_AGE_MIN*60000;
  }).sort((a,b)=>icTimestamp(b.dh_utc??b.datetime??b.timestamp??b.date)-
                  icTimestamp(a.dh_utc??a.datetime??a.timestamp??a.date));
  if(!valid.length)return null;
  const ob=valid[0];
  if(icNum(ob.temperature)===null&&icNum(ob.vent_moyen)===null&&
     icNum(ob.pression)===null&&icNum(ob.humidite)===null)return null;
  return {ob,epoch:icTimestamp(ob.dh_utc??ob.datetime??ob.timestamp??ob.date)};
}
function icApiStartEnd(){
  // Jours civils UTC : max 2 jours consécutifs, facilite la compatibilité API.
  const now=Date.now(),last=new Date(now-86400000).toISOString().slice(0,10),
        today=new Date(now).toISOString().slice(0,10);
  return {start:last,end:today};
}
async function icGetData(ids,env){
  const dates=icApiStartEnd();
  const q=new URLSearchParams({
    method:"get",format:"json",start:dates.start,end:dates.end
  });
  for(const id of ids)q.append("stations[]",id);
  let response;
  if(env.INFOCLIMAT_RELAY_URL){
    // Relais privé installé sur un hébergement à IP sortante autorisée.
    const base=new URL(env.INFOCLIMAT_RELAY_URL);
    if(base.protocol!=="https:")throw Error("Le relais Infoclimat doit utiliser HTTPS.");
    // Ne laisser passer que les paramètres métier, jamais le jeton Infoclimat.
    for(const id of ids)base.searchParams.append("stations[]",id);
    base.searchParams.set("start",dates.start);
    base.searchParams.set("end",dates.end);
    response=await fetch(base.toString(),{headers:{
      "Authorization":"Bearer "+(env.INFOCLIMAT_RELAY_SECRET||""),
      "Accept":"application/json"
    }});
  }else if(env.INFOCLIMAT_API_TOKEN){
    q.set("token",env.INFOCLIMAT_API_TOKEN);
    // ATTENTION : Cloudflare n'offre pas d'IP sortante stable sur l'offre ordinaire.
    response=await fetch(IC_DATA+"?"+q.toString(),{headers:{accept:"application/json"}});
  }else{
    throw Error("Clé Infoclimat non configurée : INFOCLIMAT_API_TOKEN ou relais IP fixe manquant.");
  }
  if(!response.ok)throw Error("API Infoclimat HTTP "+response.status);
  const raw=await response.text();
  if(/wrong ip address|could not authenticate|invalid token|ip non autoris/i.test(raw))
    throw Error("Clé Infoclimat refusée : l'adresse IP de sortie doit être autorisée. "+
      "Cloudflare peut nécessiter un relais à IP fixe.");
  if(raw.length>6_000_000)throw Error("Réponse Infoclimat trop volumineuse.");
  let data;
  try{data=JSON.parse(raw);}catch{
    throw Error("API Infoclimat n'a pas renvoyé de JSON valide.");
  }
  if(!data?.hourly||typeof data.hourly!=="object")
    throw Error("Réponse Infoclimat sans relevés horaires utilisables.");
  return data;
}
function icCompass(direction){
  const degrees=icNum(direction);
  if(degrees===null)return "non disponible";
  const dirs=["N","NNE","NE","ENE","E","ESE","SE","SSE","S",
    "SSO","SO","OSO","O","ONO","NO","NNO"];
  return dirs[Math.round((((degrees%360)+360)%360)/22.5)%16]+
    " ("+Math.round(degrees)+"°)";
}
function icReport(city,station,result){
  const ob=result.ob;
  const time=new Date(result.epoch).toLocaleString("fr-FR",{
    timeZone:"Europe/Paris",day:"2-digit",month:"2-digit",
    year:"numeric",hour:"2-digit",minute:"2-digit"});
  const age=(Date.now()-result.epoch)/60000;
  const p=ob.pression;
  const message=
    "📡 **KFS MÉTÉO — /live "+city.name+
      (city.dept?" ("+city.dept+")":"")+"**\n"+
    "🏡 **Station Infoclimat : "+station.name.replaceAll("*","")+"**\n"+
    "📍 "+icValue(station.distanceKm,"km")+" de "+city.name+
      " · ID : "+station.id+"\n"+
    "🕒 Relevé du **"+time+"** (il y a "+icValue(age,"min",0)+")\n\n"+
    "🌡️ **Température** : **"+icValue(ob.temperature,"°C")+"**\n"+
    "💧 **Humidité** : **"+icValue(ob.humidite,"%",0)+
      "** · Point de rosée : **"+icValue(ob.point_de_rosee,"°C")+"**\n"+
    "💨 **Vent moyen** : **"+icValue(ob.vent_moyen,"km/h")+"**"+
      " · Rafales : **"+icValue(ob.vent_rafales,"km/h")+"**\n"+
    "🧭 **Direction du vent** : "+icCompass(ob.vent_direction)+"\n"+
    "🌧️ **Pluie sur 1 h** : **"+icValue(ob.pluie_1h,"mm")+"**"+
      " · sur 3 h : **"+icValue(ob.pluie_3h,"mm")+"**\n"+
    "📊 **Pression** : **"+icValue(p,"hPa")+"**\n\n"+
    (station.distanceKm>50?"⚠️ La station est éloignée : mesures non représentatives de la commune.\n":"")+
    "ℹ️ Mesures d'une station physique disponible à proximité, "+
      "pas une observation effectuée dans toute la ville.\n"+
    "🔗 https://www.infoclimat.fr/opendata/\n"+
    "_Source : Association Infoclimat / réseau StatIC ou station officielle ; "+
      "réutilisation non commerciale, crédit de la station._";
  if(message.length>1950)throw Error("Bulletin Infoclimat trop long.");
  return message;
}
async function icSend(interaction,content){
  const endpoint="https://discord.com/api/v10/webhooks/"+
    APPLICATION_ID+"/"+interaction.token+"/messages/@original";
  const response=await fetch(endpoint,{method:"PATCH",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({content,allowed_mentions:{parse:[]}})});
  if(!response.ok)console.error("Discord /live Infoclimat",response.status,
                               (await response.text()).slice(0,180));
}
async function completeLive(interaction,cityInput,env){
  try{
    const city=await radarVille(cityInput);
    const cache=caches.default;
    const cacheKey=new Request("https://kfs-ic-cache.invalid/obs/"+
      city.lat.toFixed(3)+"/"+city.lon.toFixed(3));
    const hit=await cache.match(cacheKey);
    if(hit){
      const saved=await hit.json();
      if(saved?.epoch&&Date.now()-saved.epoch<=IC_MAX_AGE_MIN*60000){
        await icSend(interaction,icReport(city,saved.station,saved.result));
        return;
      }
    }
    const nearest=await icStations(city);
    const response=await icGetData(nearest.map(x=>x.id),env);
    // Recherche la station exploitable la plus proche, et non la plus récente éloignée.
    const selected=nearest.map(station=>({station,result:icDecode(response,station.id)}))
      .find(x=>x.result!==null);
    if(!selected)
      throw Error("Aucun relevé récent parmi les "+nearest.length+
        " stations Infoclimat les plus proches.");
    // Garder le résultat 15 minutes : fair use adapté à l'API associative.
    await cache.put(cacheKey,new Response(JSON.stringify({
      station:selected.station,result:selected.result,epoch:selected.result.epoch
    }),{headers:{"Content-Type":"application/json",
                "Cache-Control":"public,max-age="+IC_CACHE_SECONDS}}));
    await icSend(interaction,icReport(city,selected.station,selected.result));
  }catch(error){
    console.error("KFS /live Infoclimat",String(error.message||error));
    await icSend(interaction,"⚠️ **/live Infoclimat indisponible**\n"+
      String(error.message||"Erreur de récupération.")+
      "\nAucune donnée Open-Meteo ou Weather Underground n'a été substituée.");
  }
}
async function registerLiveCommand(env){
  if(!env.DISCORD_BOT_TOKEN)throw Error("Missing DISCORD_BOT_TOKEN");
  const command={name:"live",type:1,
    description:"Relevé réel de la station Infoclimat disponible la plus proche",
    options:[{type:3,name:"ville",required:true,min_length:2,max_length:80,
      description:"Commune française (ex. Bourth ou Rouen, 76)"}]};
  const r=await fetch("https://discord.com/api/v10/applications/"+
    APPLICATION_ID+"/commands",{method:"POST",headers:{
      "Authorization":"Bot "+env.DISCORD_BOT_TOKEN,
      "Content-Type":"application/json"},body:JSON.stringify(command)});
  if(!r.ok)throw Error("Discord /live HTTP "+r.status+
    " "+(await r.text()).slice(0,220));
}

async function registerFoudreCommand(env){
  if(!env.DISCORD_BOT_TOKEN)throw Error("Missing DISCORD_BOT_TOKEN");
  const command={name:"foudre",type:1,
    description:"Carte 5 min et bilan de foudre sur une période au choix",
    options:[
      {type:3,name:"ville",required:true,min_length:2,max_length:80,
        description:"Ville française (ex. Bourth ou Rouen, 76)"},
      {type:4,name:"periode",required:false,
        description:"Période du bilan (défaut : 30 minutes)",
        choices:[
          {name:"5 minutes",value:5},
          {name:"30 minutes (défaut)",value:30},
          {name:"1 heure",value:60},
          {name:"6 heures",value:360},
          {name:"24 heures",value:1440}
        ]}
    ]};
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
      catch(e){return json({ok:false,error:String(e)},502);}
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
      const rawPeriode=interaction.data.options?.find(x=>x.name==="periode")?.value??30;
      if(![5,30,60,360,1440].includes(rawPeriode))
        return json({type:4,data:{content:"Période invalide. Choisir 5, 30, 60, 360 ou 1440 minutes."}});
      ctx.waitUntil(completeFoudre(interaction,ville,env,rawPeriode));
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