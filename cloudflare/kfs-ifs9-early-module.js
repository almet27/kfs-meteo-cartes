// ECMWF IFS HRES 9 km anticipé /france.
// Surfaces uniquement, depuis un cycle exact Open-Meteo Single Runs.
// Ne remplace ni les cartes GRIB 0.25° ni les cartes de pression T850/Z500.
async function kfsFranceIfs9Early(interaction,metric,rawDay,rawHour,zone){
 const endpoint="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+
  "/"+interaction.token+"/messages/@original";
 const base="https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/"+
  "forecast-maps/france/ifs-early9km/";
 const allowed=["tmin","tmax","gust","precip","rain","neige_frais"];
 const names={tmin:"Température minimale",tmax:"Température maximale",
  gust:"Rafales maximales",precip:"Précipitations totales",
  rain:"Pluie liquide",neige_frais:"Chutes de neige (cm)"};
 const answer=async(payload,bytes,filename,url)=>
  kfsFranceSendDiscord(endpoint,payload,bytes,filename||"",url);
 try{
  if(!allowed.includes(metric))
   throw Error("Pour ECMWF anticipé : Tmin, Tmax, rafales, précipitations, pluie ou chutes de neige.");
  if(zone!=="FR")
   throw Error("Premières cartes ECMWF 9 km actuellement disponibles pour France entière uniquement. Pour une région, sélectionne ECMWF IFS classique.");
  if(rawDay===undefined && rawHour!==undefined)
   throw Error("Pour ECMWF anticipé, sélectionne un JOUR (J+0 à J+2), et non une échéance horaire.");
  const day=rawDay===undefined?1:Number(rawDay);
  if(!Number.isInteger(day)||day<0||day>2)
   throw Error("Premières cartes ECMWF disponibles uniquement à J+0, J+1 ou J+2.");
  const catalogUrl=base+"latest.json?kfs="+Math.floor(Date.now()/120000);
  let response;
  for(let i=0;i<2;i++){
   response=await fetch(catalogUrl,{redirect:"follow",signal:AbortSignal.timeout(12000)});
   if(response.ok||![429,502,503,504].includes(response.status))break;
   if(i===0)await new Promise(resolve=>setTimeout(resolve,600));
  }
  if(!response?.ok){
   if(response?.status===404)
    throw Error("Le premier catalogue ECMWF anticipé n'est pas encore publié. "+
     "GitHub vérifie le run 12Z toutes les 15 min, et le publiera dès disponibilité.");
   throw Error("Catalogue ECMWF anticipé indisponible (HTTP "+(response?.status||"réseau")+").");
  }
  const meta=await response.json();
  const run=new Date(meta.run_utc||"");
  if(meta.schema!==1||meta.model!=="ecmwf_ifs"||
    meta.resolution_native_km!==9||!Number.isFinite(run.getTime())||
    run.getUTCHours()!==12||run.getTime()>Date.now()||
    !meta.days||typeof meta.days!=="object")
   throw Error("Catalogue ECMWF anticipé invalide : conserver les cartes officielles.");
  const dayInfo=meta.days[String(day)],map=dayInfo?.maps?.[metric];
  if(!map||map.file!=="ifs9-"+metric+"-j"+day+".webp"){
   const available=Object.keys(meta.days||{}).map(k=>"J+"+k).join(", ");
   throw Error("La carte "+names[metric]+" J+"+day+" n'a pas encore été publiée. "+
    "Journées disponibles : "+(available||"aucune"));
  }
  const url=base+map.file;
  const png=await kfsFranceReadWebP(url,meta.run_utc);
  if(!png.ok)throw Error("Fichier image anticipé indisponible (HTTP "+png.status+").");
  const bytes=await png.arrayBuffer();
  const now=new Date(),current12=Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),now.getUTCDate(),12);
  const old=now.getUTCHours()>=17&&run.getTime()<current12;
  const date=dayInfo.date;
  const coverage=(map.coverage_hours||0)>=23?"journée complète":
   "journée partielle ("+(map.coverage_hours||0)+" h)";
  const description="🗺️ **KFS MÉTÉO /france — ECMWF anticipé 9 km**\n"+
   "**"+names[metric]+" · J+"+day+" · "+date+"**\n"+
   "🕒 **Run vérifié : "+meta.run_utc.slice(0,16).replace("T"," ")+" UTC**"+
   (old?" · ⚠️ Nouveau 12Z encore en attente":"")+" \n"+
   "📊 "+coverage+" · Échantillonnage cartographique ~35–60 km"+
   "\n⚠️ Produit préliminaire de surface : **pas de T850/Z500**. "+
   "Le GRIB ECMWF complet est conservé dans le modèle IFS classique."+
   "\nSource : ECMWF via Open-Meteo (CC BY 4.0, usage non commercial)."+
   (metric==="neige_frais"?" Neige tombante estimée, pas neige au sol.":"");
  await answer({
   content:description,allowed_mentions:{parse:[]},
   attachments:[{id:0,filename:map.file}],
   embeds:[{image:{url:"attachment://"+map.file}}],
   components:[{type:1,components:[{type:2,style:5,label:"Source Open-Meteo",
    url:"https://open-meteo.com/en/docs/single-runs-api"}]}]
  },bytes,map.file,url);
 }catch(e){
  console.warn("KFS_FRANCE_IFS9_EARLY",String(e).slice(0,220));
  await answer({content:"⚠️ **/france · ECMWF anticipé** — "+
   String(e?.message||e).slice(0,400),allowed_mentions:{parse:[]}})
   .catch(()=>{});
 }
}
