/* KFS MÉTÉO — /statistiques modeles.
   Les scores proviennent du pipeline scripts/build_model_skill.py.
   Aucune série fictive ou interpolation de résultats manquants. */
let KFS_SKILL_SYNCED=false;
const KFS_SKILL_COLORS={ifs:"#37bdf2",aifs:"#75e2a4",aigfs:"#f59ed5",gfs:"#fbbf67"};
const KFS_SKILL_NAMES={ifs:"ECMWF IFS",aifs:"ECMWF AIFS",aigfs:"NOAA AIGFS",gfs:"NOAA GFS"};
const KFS_SKILL_KEYS=Object.keys(KFS_SKILL_NAMES);
function kfsSkillPreviousMonth(){
  const d=new Date();d.setUTCDate(1);d.setUTCMonth(d.getUTCMonth()-1);
  return d.toISOString().slice(0,7);
}
function kfsSkillMonthOK(month){
  return /^20\d\d-(0[1-9]|1[0-2])$/.test(month)&&
    month>="2026-04"&&month<=kfsSkillPreviousMonth();
}
function kfsSkillOptions(){
  return [
    {type:3,name:"mois",description:"Mois au format AAAA-MM (défaut : dernier mois complet)",required:false,min_length:7,max_length:7},
    {type:3,name:"parametre",description:"Variable vérifiée, erreur moyenne (plus bas = meilleur)",required:false,choices:[
      {name:"Température à 2 mètres (°C)",value:"temperature_2m"},
      {name:"Pression au niveau de la mer (hPa)",value:"pressure_msl"}
    ]}
  ];
}
async function kfsSkillRegister(env){
  if(!env.DISCORD_BOT_TOKEN)throw Error("Jeton Discord absent");
  const token="Bot "+env.DISCORD_BOT_TOKEN;
  const roots=[
    "https://discord.com/api/v10/applications/"+APPLICATION_ID+"/commands",
    "https://discord.com/api/v10/applications/"+APPLICATION_ID+"/guilds/1014144530037092352/commands"
  ];
  for(const root of roots){
    const headers={Authorization:token,"content-type":"application/json"};
    const listed=await fetch(root,{headers:{Authorization:token},signal:AbortSignal.timeout(12000)});
    if(!listed.ok)throw Error("Liste commandes statistiques HTTP "+listed.status);
    const existing=(await listed.json()).find(c=>c.name==="statistiques"&&c.type===1);
    const old=existing?.options||[];
    if(old.some(o=>o.type!==1&&o.type!==2))
      throw Error("La commande /statistiques existe déjà avec des options simples : ne pas l'écraser");
    const sub={type:1,name:"modeles",description:"Fiabilité des quatre modèles sur la France de J+1 à J+15",options:kfsSkillOptions()};
    const options=[...old.filter(o=>o.name!=="modeles"),sub];
    const command={name:"statistiques",type:1,
      description:existing?.description||"Statistiques météorologiques KFS MÉTÉO",
      options};
    const oldSub=old.find(o=>o.name==="modeles");
    const same=oldSub&&JSON.stringify(oldSub.options?.map(o=>[o.name,o.choices?.map(c=>c.value)]))===
      JSON.stringify(sub.options.map(o=>[o.name,o.choices?.map(c=>c.value)]));
    if(same)continue;
    const response=await fetch(root,{method:"POST",headers,body:JSON.stringify(command),signal:AbortSignal.timeout(12000)});
    if(!response.ok)throw Error("Enregistrement /statistiques HTTP "+response.status+" "+(await response.text()).slice(0,170));
  }
}
async function kfsSkillLoad(month){
  const base="https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/data/model-skill/";
  const response=await fetch(base+month+".json",{
    cf:{cacheEverything:true,cacheTtl:600},signal:AbortSignal.timeout(18000)});
  if(response.status===404)return null;
  if(!response.ok)throw Error("Archive mensuelle HTTP "+response.status);
  const data=await response.json();
  if(data?.schema!==1||data.period!==month||!data.metrics||!Array.isArray(data.run_dates))
    throw Error("Archive mensuelle non conforme");
  return data;
}
function kfsSkillChart(data,metric,month){
  const series=data.metrics[metric];
  const unit=series.unit|| (metric==="pressure_msl"?"hPa":"°C");
  const datasets=KFS_SKILL_KEYS.map(key=>({
    label:KFS_SKILL_NAMES[key],
    data:Array.from({length:15},(_,i)=>{
      const n=series.series?.[key]?.[i];
      return typeof n==="number"&&Number.isFinite(n)?n:null;
    }),
    borderColor:KFS_SKILL_COLORS[key],
    backgroundColor:KFS_SKILL_COLORS[key],
    borderWidth:3,pointRadius:3,pointHoverRadius:6,spanGaps:false,
    fill:false,lineTension:0.19
  }));
  return {
    width:1200,height:650,backgroundColor:"#111b2d",format:"png",
    chart:{type:"line",data:{labels:Array.from({length:15},(_,i)=>"J+"+(i+1)),datasets},
      options:{responsive:false,animation:false,
        title:{display:true,text:"KFS MÉTÉO   |   FRANCE   |   "+month+
          "   |   ERREUR MOYENNE "+(metric==="temperature_2m"?"TEMPÉRATURE":"PRESSION")+" ("+unit+")",
          fontColor:"#f5f8fd",fontSize:21,padding:24},
        legend:{display:true,position:"bottom",labels:{fontColor:"#f1f5fb",fontSize:15,boxWidth:24,padding:20}},
        tooltips:{mode:"index",intersect:false},
        scales:{
          xAxes:[{gridLines:{color:"rgba(180,206,240,.08)"},ticks:{fontColor:"#d3e3f5",fontSize:13}}],
          yAxes:[{gridLines:{color:"rgba(180,206,240,.13)"},
            scaleLabel:{display:true,labelString:"MAE ("+unit+") • plus faible = meilleur",fontColor:"#eff5fc",fontSize:15},
            ticks:{fontColor:"#d3e3f5",fontSize:13,beginAtZero:true}}]
        }
      }}
  };
}
async function kfsSkillSend(interaction,payload,image){
  const endpoint="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+
    "/"+interaction.token+"/messages/@original";
  let request;
  if(image){
    const form=new FormData();
    form.append("payload_json",JSON.stringify({
      ...payload,
      attachments:[{id:0,filename:"KFS-statistiques-modeles.png",
        description:"MAE des modèles ECMWF IFS, AIFS, NOAA AIGFS et GFS de J+1 à J+15"}]
    }));
    form.append("files[0]",new Blob([image],{type:"image/png"}),"KFS-statistiques-modeles.png");
    request={method:"PATCH",body:form,signal:AbortSignal.timeout(25000)};
  }else{
    request={method:"PATCH",headers:{"content-type":"application/json"},
      body:JSON.stringify(payload),signal:AbortSignal.timeout(15000)};
  }
  const response=await fetch(endpoint,request);
  if(!response.ok)throw Error("Réponse Discord HTTP "+response.status+" "+(await response.text()).slice(0,170));
}
async function kfsSkillComplete(interaction,month,metric){
  try{
    const data=await kfsSkillLoad(month);
    if(!data){
      await kfsSkillSend(interaction,{content:
        "📊 **KFS MÉTÉO — statistiques des modèles • "+month+"**\n"+
        "Aucune comparaison vérifiée n'est encore publiée pour ce mois. "+
        "Le calcul mensuel utilise des runs archivés réels confrontés à ERA5. "+
        "Les valeurs ne seront affichées qu'une fois la vérification terminée.",
        allowed_mentions:{parse:[]}},null);
      return;
    }
    const result=data.metrics?.[metric];
    if(!result||!result.n?.some(n=>n>0))throw Error(
      "Pas encore assez de prévisions et de références valides pour ce paramètre");
    const count=data.run_dates.length;
    const labels={temperature_2m:"Température à 2 m",pressure_msl:"Pression au niveau de la mer"};
    const nCommon=Math.max(...result.n);
    const j15=result.n[14]||0;
    const lines=["📊 **KFS MÉTÉO — fiabilité des modèles • "+month+"**",
      "**"+labels[metric]+"** | erreur absolue moyenne (MAE, "+result.unit+")",
      "**12 points en France · "+count+" runs 00Z du mois · jusqu'à "+nCommon+" comparaisons communes par échéance**",
      "Courbe la plus basse = modèle le plus proche de la référence.",
      "Référence : réanalyse ERA5 (non relevés directs de stations).",
      "Échantillon : jours 1, 5, 9, 13, 17, 21, 25 et 29, selon disponibilité.",
      j15?"J+15 : "+j15+" comparaisons vérifiées.":"⚠️ J+15 : données insuffisantes, aucun chiffre inventé."];
    const image=await kfsRenderEnsembleChart(kfsSkillChart(data,metric,month));
    await kfsSkillSend(interaction,{content:lines.join("\n"),allowed_mentions:{parse:[]}},image);
  }catch(error){
    console.error("KFS_SKILL_ERROR",String(error?.stack||error).slice(0,600));
    await kfsSkillSend(interaction,{content:
      "⚠️ **/statistiques modeles** : "+String(error?.message||error).slice(0,300),
      allowed_mentions:{parse:[]}},null).catch(e=>console.error("KFS_SKILL_DISCORD",String(e)));
  }
}
