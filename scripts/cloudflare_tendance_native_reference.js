// Reference du Worker Cloudflare KFS. Ne pas deployer ce fichier seul.
async function kfsPostTendanceMapToChannel(env,src,index,total,marker){
  const id=String(src.id||"");
  if(!["j3","j7","j10","j15"].includes(id) && !/^week[34]-(t2m|precip)$/.test(id))throw Error("Carte inconnue : "+id);
  const weekly=id.startsWith("week");
  const filename=(weekly?"kfs-weekly-":"kfs-tendance-")+id+".png";
  const imgRes=await fetch("https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/forecast-maps/tendance/"+(weekly?"weekly-":"tendance-carte-")+id+".png",{cache:"no-store"});
  if(!imgRes.ok)throw Error("Carte source "+id+" HTTP "+imgRes.status);
  const data=await imgRes.arrayBuffer(),header=new Uint8Array(data);
  if(data.byteLength<15000||data.byteLength>6*1024*1024||header[0]!==137||header[1]!==80||header[2]!==78||header[3]!==71)
    throw Error("PNG "+id+" invalide");
  const body={
    content:(Object.values(src.risks||{}).some(r=>r?.status==="marque")?"❗ ":"🗺️ ")+
      "**KFS MÉTÉO — Carte européenne "+id.toUpperCase()+" · "+index+"/"+total+"**\n"+
      "_Modèles et runs dans la carte · ❗ = risque modélisé marqué, pas vigilance officielle · "+marker+"_",
    attachments:[{id:0,filename,description:"Carte synoptique KFS MÉTÉO "+id.toUpperCase()}],
    allowed_mentions:{parse:[]}
  };
  for(let tries=0;tries<4;tries++){
    const form=new FormData();
    form.append("payload_json",JSON.stringify(body));
    form.append("files[0]",new Blob([data],{type:"image/png"}),filename);
    const sent=await fetch("https://discord.com/api/v10/channels/"+KFS_TENDANCE_CHANNEL+"/messages",{
      method:"POST",headers:{"Authorization":"Bot "+env.DISCORD_BOT_TOKEN},body:form});
    if(sent.ok){
      const resp=await sent.json();
      console.log("KFS_TENDANCE_PUBLIC_IMAGE_ATTACHED",id,resp.id,resp.attachments?.length||0);
      return resp;
    }
    if(sent.status===429&&tries<3){
      const rate=await sent.json();
      await new Promise(done=>setTimeout(done,Math.min(12000,Math.max(500,Number(rate.retry_after||1)*1000))));
      continue;
    }
    throw Error("PNG Discord public "+id+" HTTP "+sent.status+" "+(await sent.text()).slice(0,180));
  }
}



async function kfsSendTendanceWithMap(interaction,endpoint,src,index,total){
  const id=String(src.id||"");
  if(!["j3","j7","j10","j15"].includes(id)&&!/^week[34]-(t2m|precip)$/.test(id))
    throw Error("Carte inconnue : "+id);
  const weekly=id.startsWith("week");
  const filename=(weekly?"kfs-weekly-":"kfs-tendance-")+id+".png";
  const url="https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/forecast-maps/tendance/"+
    (weekly?"weekly-":"tendance-carte-")+id+".png";
  const res=await fetch(url,{cache:"no-store",signal:AbortSignal.timeout(14000)});
  if(!res.ok)throw Error("PNG GitHub "+id+" HTTP "+res.status);
  const data=await res.arrayBuffer();
  const bytes=new Uint8Array(data);
  if(data.byteLength<15000||data.byteLength>6*1024*1024||
     bytes[0]!==137||bytes[1]!==80||bytes[2]!==78||bytes[3]!==71)
    throw Error("PNG carte "+id+" absent ou non valide");
  const marked=Object.entries(src.risks||{}).filter(([key,value])=>value?.status==="marque");
  const nice={tempete:"vent soutenu",pluie_forte:"fortes précipitations",
    neige:"neige hors relief",verglas:"verglas",orage:"orages",gel:"gel",
    canicule:"forte chaleur",inondation:"crues"};
  const titles=marked.map(([key])=>nice[key]||key);
  const headline=(marked.length?"❗ ":"🗺️ ")+"**KFS MÉTÉO — Carte européenne "+id.toUpperCase()+
    " · "+index+"/"+total+"**";
  const caption=headline+
    "\n"+String(src.title||"Prévisions synoptiques").slice(0,145)+
    (marked.length?"\n❗ **Signal modélisé marqué :** "+titles.join(", ")+
        ". _Ce symbole n'est pas une vigilance officielle._":
        "\n_Risques modélisés : aucun seuil marqué signalé sur cette échéance._")+
    "\n_Chaque image peut être ouverte en grand dans Discord._";
  // Une seule image jointe, sans embed.image ni drapeau éphémère.
  const payload={content:caption,allowed_mentions:{parse:[]},
    attachments:[{id:0,filename,
      description:"KFS MÉTÉO, carte synoptique européenne "+id.toUpperCase()}]};
  for(let attempt=0;attempt<4;attempt++){
    const form=new FormData();
    form.append("payload_json",JSON.stringify(payload));
    form.append("files[0]",new Blob([data],{type:"image/png"}),filename);
    const sent=await fetch(endpoint,{method:"POST",body:form});
    if(sent.ok){
      const msg=await sent.json();
      if(!(msg.attachments||[]).some(x=>x.filename===filename))
        console.warn("KFS_TENDANCE_UPLOAD_NO_ATTACHMENT",id,msg.id);
      else
        console.log("KFS_TENDANCE_NATIVE_IMAGE",id,msg.id);
      return;
    }
    if(sent.status===429&&attempt<3){
      const rate=await sent.json();
      await new Promise(done=>setTimeout(done,
        Math.min(12000,Math.max(500,Number(rate.retry_after||1)*1000))));
      continue;
    }
    throw Error("Envoi natif carte Discord "+id+" HTTP "+sent.status+" "+
      (await sent.text()).slice(0,200));
  }
}

