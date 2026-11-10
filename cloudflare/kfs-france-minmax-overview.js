// KFS_FRANCE_MINMAX_OVERVIEW_20261110_V2
// Deux cartes seulement en absence de J+ : Tmin et Tmax sur toute la période.
async function kfsFranceMinMaxOverview(interaction,model,zone){
 const endpoint="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+"/"+interaction.token+"/messages/@original";
 const available={
  ifs:{name:"ECMWF IFS",api:"ecmwf_ifs025",days:5},
  gfs:{name:"NOAA GFS",api:"ncep_gfs_global",days:5},
  "aifs-single":{name:"ECMWF AIFS",api:"ecmwf_aifs025_single",days:5},
  aigfs:{name:"NOAA AIGFS",api:"ncep_aigfs025",days:5},
  arome:{name:"ARÔME France",api:"meteofrance_arome_france",days:2},
  icon_eu:{name:"ICON Europe",api:"icon_eu",days:2}
 };
 try{
  if(model==="ifs9-early")throw Error("Les horaires extrêmes du run anticipé 9 km ne sont pas publiés. Choisis ECMWF IFS classique sans J+, ou un J+ pour la carte 9 km.");
  const cfg=available[model];
  if(!cfg)throw Error("Modèle non disponible pour ce bilan.");
  const allFeatures=await kfsProbaFeatures();
  const features=zone==="FR"?allFeatures:allFeatures.filter(f=>String(f.properties.code)===zone);
  if(!features.length)throw Error("Région inconnue.");
  const samples=[],seen=new Set();
  const add=(lon,lat)=>{
   const key=Number(lon).toFixed(3)+","+Number(lat).toFixed(3);
   if(!seen.has(key)){seen.add(key);samples.push({lon:Number(lon),lat:Number(lat)});}
  };
  for(const f of features){
   const grid=kfsProbaSamples([f],true);
   // Six points répartis dans toute la région, plutôt que les six premiers
   // (qui favorisaient une portion de la région, notamment au nord).
   const chosen=zone==="FR"?
    [...new Set([0,.2,.4,.6,.8,1].map(f=>Math.round((grid.length-1)*f)))].map(i=>grid[i]):
    grid.slice(0,15);
   for(const p of chosen)add(p.lon,p.lat);
   if(zone==="FR"){
    for(const [,lon,lat] of (KFS_PROBA_CITIES[f.properties.code]||[]).slice(0,2))
     if(kfsProbaInFeature(lon,lat,f))add(lon,lat);
   }
  }
  if(samples.length<3)throw Error("Échantillonnage insuffisant.");
  const parts=new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Paris",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
  const [year,month,day]=parts.split("-").map(Number);
  const localDay=n=>new Date(Date.UTC(year,month-1,day+n,12)).toISOString().slice(0,10);
  const dates=new Set(Array.from({length:cfg.days},(_,i)=>localDay(i+1)));
  const start=localDay(1),end=localDay(cfg.days);
  const records=[];
  for(let at=0;at<samples.length;at+=35){
   const part=samples.slice(at,at+35);
   const p=new URLSearchParams({
    latitude:part.map(p=>p.lat.toFixed(3)).join(","),
    longitude:part.map(p=>p.lon.toFixed(3)).join(","),
    models:cfg.api,hourly:"temperature_2m",timezone:"Europe/Paris",
    forecast_days:String(cfg.days+2),temperature_unit:"celsius"
   });
   const url="https://api.open-meteo.com/v1/forecast?"+p;
   let response=null;
   for(let attempt=0;attempt<2;attempt++){
    try{
     response=await fetch(url,{signal:AbortSignal.timeout(13500),
      cf:{cacheEverything:true,cacheTtl:900}});
     if(response.ok||![429,500,502,503,504].includes(response.status))break;
    }catch(e){if(attempt)throw e;}
    if(attempt===0)await new Promise(resolve=>setTimeout(resolve,400));
   }
   if(!response?.ok)throw Error("Source "+cfg.name+" HTTP "+(response?.status||"indisponible")+". Aucun horaire inventé.");
   const raw=await response.json(),batch=Array.isArray(raw)?raw:[raw];
   if(batch.length!==part.length)throw Error("Réponse multi-points incomplète du modèle.");
   records.push(...batch);
  }
  const pointPairs=[];
  for(let i=0;i<samples.length;i++){
   const hourly=records[i]?.hourly||{},times=hourly.time||[],values=hourly.temperature_2m||[];
   let low=null,high=null,coverage=new Set();
   for(let j=0;j<times.length;j++){
    const date=String(times[j]).slice(0,10),value=values[j];
    if(!dates.has(date)||!Number.isFinite(value))continue;
    coverage.add(date);
    if(!low||value<low.value)low={value,time:times[j]};
    if(!high||value>high.value)high={value,time:times[j]};
   }
   if(low&&high)pointPairs.push({point:samples[i],low,high,coverage});
  }
  if(pointPairs.length<Math.max(3,Math.floor(samples.length*.75)))
   throw Error("Températures et horaires insuffisants dans le modèle.");
  const when=t=>String(t).slice(8,10)+"/"+String(t).slice(5,7)+
   " "+String(t).slice(11,13)+"H";
  const depts=zone==="FR"?[]:await kfsProbaDepartments(zone);
  const kinds=[["tmin","low","MINIMALES"],["tmax","high","MAXIMALES"]];
  const prepared=[];
  for(const [metric,key,title] of kinds){
   const points=pointPairs.map(item=>({
    ...item.point,value:item[key].value,extremeWhen:when(item[key].time)
   }));
   const range="J+1 A J+"+cfg.days+" / HEURE PARIS";
   const frame=kfsFranceRegionalRender(features,depts,points,zone,metric,range);
   const bytes=await kfsProbaPng(frame);
   if(bytes.length<10000||bytes.length>7900000)throw Error("Carte "+title+" trop petite ou volumineuse.");
   const absolute=pointPairs.map(item=>item[key]).reduce((a,b)=>
    (metric==="tmin"?b.value<a.value:b.value>a.value)?b:a);
   prepared.push({metric,key,title,bytes,filename:"kfs-france-"+model+"-extreme-"+metric+".png",absolute});
  }
  // Les dates/heures changent selon la position : elles sont affichées sous
  // les températures de plusieurs points repères directement sur les cartes.
  const name=zone==="FR"?"France métropolitaine":
    (KFS_PROBA_REGIONS.find(x=>x[0]===zone)?.[1]||zone);
  const daysCovered=[...new Set(pointPairs.flatMap(x=>[...x.coverage]))].sort();
  const partial=daysCovered.length<cfg.days?
   "\n⚠️ Période partiellement couverte par ce modèle : certaines échéances ne sont pas disponibles.":"";
  const formatValue=v=>v.toFixed(1).replace(".",",")+" °C";
  const lines=["🌡️ **KFS MÉTÉO /france — extrêmes des prochains jours**",
   "**"+cfg.name+" · "+name+"**",
   "📅 **Du "+start.split("-").reverse().join("/")+" au "+
     end.split("-").reverse().join("/")+" (J+1 à J+"+cfg.days+")**",
   "🔵 **Tmin la plus basse échantillonnée :** "+formatValue(prepared[0].absolute.value)+
      " · "+when(prepared[0].absolute.time),
   "🔴 **Tmax la plus haute échantillonnée :** "+formatValue(prepared[1].absolute.value)+
      " · "+when(prepared[1].absolute.time),
   "📍 **Sur chaque carte :** valeur prévue et date/heure à plusieurs points repères, en heure française.",
   "_Extrêmes calculés par point sur toute la période, à partir des heures disponibles. Les dates/heures diffèrent selon les lieux. Cartes interpolées entre points ; ce ne sont pas des records observés._",
   "_Source : "+cfg.name+" via Open-Meteo._"+partial];
  const form=new FormData();
  const attachment=prepared.map((x,i)=>({id:i,filename:x.filename}));
  const embeds=prepared.map(x=>({title:x.title+" · du "+start.slice(8,10)+"/"+
   start.slice(5,7)+" au "+end.slice(8,10)+"/"+end.slice(5,7),
   image:{url:"attachment://"+x.filename}}));
  form.append("payload_json",JSON.stringify({
   content:lines.join("\n").slice(0,1950),allowed_mentions:{parse:[]},
   attachments:attachment,embeds
  }));
  prepared.forEach((x,i)=>form.append("files["+i+"]",
   new Blob([x.bytes],{type:"image/png"}),x.filename));
  const response=await fetch(endpoint,{method:"PATCH",body:form,signal:AbortSignal.timeout(19000)});
  if(!response.ok)throw Error("Discord HTTP "+response.status+" "+
   (await response.text().catch(()=>"")).slice(0,110));
 }catch(error){
  console.error("KFS_FRANCE_EXTREMES_V2",model,zone,String(error).slice(0,300));
  await kfsFranceSendDiscord(endpoint,{content:"⚠️ **/france — températures extrêmes :** "+
   String(error?.message||error).slice(0,350),allowed_mentions:{parse:[]}}).catch(()=>{});
 }
}
