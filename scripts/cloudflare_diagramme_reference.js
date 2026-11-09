const KFS_ENSEMBLE_META_CODES=["ecmwf_ifs025_ensemble","ncep_gefs025","ncep_gefs05"];
function kfsUnixMs(v){
 const n=Number(v);
 return Number.isFinite(n)&&n>0?(n>1e12?n:n*1000):null;
}
async function kfsEnsembleMeta(modelCode){
 if(!KFS_ENSEMBLE_META_CODES.includes(modelCode))throw Error("Ensemble inconnu");
 const url="https://api.open-meteo.com/data/"+modelCode+
   "/static/meta.json?kfs="+Math.floor(Date.now()/300000);
 const res=await fetch(url,{cache:"no-store",signal:AbortSignal.timeout(10000)});
 if(!res.ok)throw Error("Métadonnées "+modelCode+" HTTP "+res.status);
 const d=await res.json(),init=kfsUnixMs(d.last_run_initialisation_time),
       available=kfsUnixMs(d.last_run_availability_time),now=Date.now();
 if(init===null||init>now+600000||now-init>7*86400000)
   throw Error("Date du run "+modelCode+" invalide");
 const date=new Date(init);
 if(![0,6,12,18].includes(date.getUTCHours())||date.getUTCMinutes()!==0)
   throw Error("Cycle "+modelCode+" inattendu");
 return {modelCode,init,available,
   iso:date.toISOString().replace(".000Z","Z"),
   ready:available!==null&&available>=init&&available<=now-600000};
}
function kfsEnsembleRunTitle(meta){
 if(!meta?.iso)return "RUN non vérifié";
 const d=new Date(meta.init),month=new Intl.DateTimeFormat("fr-FR",{
   timeZone:"UTC",month:"long"}).format(d);
 return "RUN "+String(d.getUTCHours()).padStart(2,"0")+"Z du "+
   d.getUTCDate()+" "+month+" "+d.getUTCFullYear();
}

// KFS /diagramme — ECMWF ENS / GEFS (non-commercial use of Open-Meteo).
// Source: Open-Meteo Ensemble API. The API does not identify a precise
// initialization time, so never attach an unverified "RUN 00Z" label.
let KFS_DIAGRAMME_SYNCED=false;

async function kfsRegisterDiagramme(env){
  if(!env.DISCORD_BOT_TOKEN)throw Error("Jeton Discord absent");
  const command={
    name:"diagramme",type:1,
    description:"Diagrammes d'ensemble ECMWF ENS ou GEFS pour une ville",
    options:[
      {type:3,name:"modele",description:"Ensemble météorologique",required:true,
       choices:[{name:"ECMWF ENS (51 membres)",value:"ens"},{name:"GEFS (31 membres)",value:"gefs"}]},
      {type:3,name:"ville",description:"Ville en France, ex. Évreux",required:true,
       min_length:2,max_length:75},
      {type:3,name:"parametre",description:"Un diagramme ou les trois graphiques",required:false,
       choices:[{name:"Complet : température + pluie + pression",value:"complet"},
         {name:"Température à 2 m",value:"temperature"},
         {name:"Précipitations sur 6 heures",value:"pluie"},
         {name:"Pression atmosphérique",value:"pression"}]},
      {type:4,name:"periode",description:"Durée des prévisions",required:false,
       choices:[{name:"10 jours",value:10},{name:"15 jours",value:15}]}
    ]
  };
  const response=await fetch("https://discord.com/api/v10/applications/"+
    APPLICATION_ID+"/commands",{
    method:"POST",headers:{"Authorization":"Bot "+env.DISCORD_BOT_TOKEN,
      "content-type":"application/json"},body:JSON.stringify(command),
    signal:AbortSignal.timeout(12000)
  });
  if(!response.ok)throw Error("Discord /diagramme HTTP "+response.status+" "+
    (await response.text()).slice(0,230));
  console.log("KFS_DIAGRAMME_REGISTERED");
}

function kfsEnsembleQuantile(sorted,q){
  const pos=(sorted.length-1)*q,low=Math.floor(pos),high=Math.ceil(pos);
  return sorted[low]+(sorted[high]-sorted[low])*(pos-low);
}
function kfsEnsembleSummarize(values){
  const data=values.filter(Number.isFinite).sort((a,b)=>a-b);
  if(data.length<8)return null;
  const round=n=>Math.round(n*10)/10;
  return {p10:round(kfsEnsembleQuantile(data,.1)),
    p50:round(kfsEnsembleQuantile(data,.5)),
    p90:round(kfsEnsembleQuantile(data,.9)),
    mean:round(data.reduce((a,b)=>a+b,0)/data.length),
    n:data.length};
}
function kfsEnsembleCollect(hourly,variable){
  const re=new RegExp("^"+variable+"_member[0-9]+$");
  return Object.entries(hourly).filter(([key,value])=>
    (key===variable||re.test(key))&&Array.isArray(value)&&value.length===hourly.time.length)
    .map(([key,value])=>({key,value}));
}
function kfsEnsembleSeries(hourly,params){
  const rawTime=hourly.time||[];
  const ts=rawTime.map(t=>Date.parse(t.endsWith("Z")?t:t+"Z"));
  if(ts.length<30||ts.some(t=>!Number.isFinite(t)))throw Error("Horodatages du modèle incomplets");
  const members={temperature:kfsEnsembleCollect(hourly,"temperature_2m"),
    pluie:kfsEnsembleCollect(hourly,"precipitation"),
    pression:kfsEnsembleCollect(hourly,"pressure_msl")};
  const wanted=params==="complet"?["temperature","pluie","pression"]:[params];
  const values={},timeIndices=[];
  for(let i=0;i<ts.length;i++){
    const d=new Date(ts[i]);
    if(i>0&&d.getUTCHours()%6===0&&d.getUTCMinutes()===0)timeIndices.push(i);
  }
  if(timeIndices.length<8)throw Error("Échéances à six heures manquantes");
  for(const name of wanted){
    if(members[name].length<8)throw Error("Le champ "+name+
      " n'est pas disponible sur suffisamment de membres de cet ensemble");
    const samples=[];
    for(const idx of timeIndices){
      const vals=[];
      if(name==="pluie"){
        const window=[];
        for(let j=Math.max(0,idx-7);j<=idx;j++){
          if(ts[j]>ts[idx]-6*3600000&&ts[j]<=ts[idx])window.push(j);
        }
        if(!window.length)continue;
        for(const m of members[name]){
          const relevant=window.map(j=>m.value[j]);
          if(relevant.every(Number.isFinite))
            vals.push(relevant.reduce((a,b)=>a+Math.max(0,b),0));
        }
      }else{
        for(const m of members[name]){
          const val=m.value[idx];
          if(Number.isFinite(val))vals.push(val);
        }
      }
      samples.push(kfsEnsembleSummarize(vals));
    }
    values[name]={samples,memberCount:members[name].length};
  }
  const dateLabels=timeIndices.map(i=>new Intl.DateTimeFormat("fr-FR",{
    timeZone:"Europe/Paris",day:"2-digit",month:"2-digit",
    hour:"2-digit",hourCycle:"h23"}).format(new Date(ts[i])).replace(", "," "));
  return {timeIndices,dateLabels,values,wanted,timestamps:timeIndices.map(i=>ts[i])};
}
function kfsEnsembleChart(name,series,modelLabel,city,duration,runTitle){
  const titles={
    temperature:["TEMPÉRATURE À 2 M","Température (°C)","#ef744c","rgba(239,116,76,0.18)"],
    pluie:["PRÉCIPITATIONS SUR 6 HEURES","Cumul pluie/neige (mm / 6 h)","#278ed1","rgba(39,142,209,0.20)"],
    pression:["PRESSION AU NIVEAU DE LA MER","Pression (hPa)","#36a987","rgba(54,169,135,0.19)"]
  };
  const [title,unit,color,fill]=titles[name];
  const data=series.values[name].samples;
  const extract=key=>data.map(s=>s?.[key]??null);
  const chart={
    type:"line",
    data:{labels:series.dateLabels,datasets:[
      {label:"P90",data:extract("p90"),borderColor:"rgba(0,0,0,0)",
        pointRadius:0,borderWidth:0,fill:false,tension:.2},
      {label:"Fourchette P10–P90",data:extract("p10"),borderColor:"rgba(0,0,0,0)",
        pointRadius:0,borderWidth:0,backgroundColor:fill,fill:"-1",tension:.2},
      {label:"Médiane des membres",data:extract("p50"),borderColor:color,
        pointRadius:0,borderWidth:3,fill:false,tension:.18},
      {label:"Moyenne des membres",data:extract("mean"),borderColor:"#a0aabe",
        pointRadius:0,borderWidth:2,borderDash:[7,5],fill:false,tension:.18}
    ]},
    options:{
      responsive:false,animation:false,maintainAspectRatio:false,
      layout:{padding:{left:12,right:18,top:10,bottom:6}},
      plugins:{
        title:{display:true,text:[
          "KFS MÉTÉO  |  "+modelLabel+"  |  "+city+"  |  "+duration+" jours  |  "+runTitle,
          title+"  ·  médiane et incertitude de l'ensemble"
        ],align:"start",color:"#172942",font:{size:18,weight:"bold"},padding:20},
        legend:{position:"bottom",labels:{color:"#31445d",boxWidth:15,
          filter:({text})=>text!=="P90",font:{size:12}}},
        tooltip:{enabled:false}
      },
      scales:{
        x:{grid:{color:"rgba(120,135,156,.08)"},ticks:{color:"#52637a",
          font:{size:11},maxTicksLimit:13,autoSkip:true,maxRotation:0}},
        y:{beginAtZero:name==="pluie",title:{display:true,text:unit,color:"#52637a",
          font:{size:12}},grid:{color:"rgba(120,135,156,.15)"},
          ticks:{color:"#52637a",font:{size:11}}}
      }
    }
  };
  return {version:"4",format:"png",backgroundColor:"#ffffff",
    width:1220,height:420,devicePixelRatio:1,chart};
}
async function kfsRenderEnsembleChart(configuration){
  const r=await fetch("https://quickchart.io/chart",{
    method:"POST",headers:{"content-type":"application/json"},
    body:JSON.stringify(configuration),signal:AbortSignal.timeout(25000)
  });
  if(!r.ok)throw Error("Service graphique indisponible (HTTP "+r.status+")");
  const bytes=await r.arrayBuffer();
  const sig=new Uint8Array(bytes,0,Math.min(8,bytes.byteLength));
  if(bytes.byteLength<3000||bytes.byteLength>7*1024*1024||
     sig[0]!==137||sig[1]!==80||sig[2]!==78||sig[3]!==71)
    throw Error("Le diagramme PNG retourné n'est pas valide");
  return bytes;
}
async function kfsCompleteDiagramme(interaction,model,cityName,param,duration){
  const endpoint="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+
    "/"+interaction.token+"/messages/@original";
  async function reply(payload,images=[]){
    const headers={},request={method:"PATCH"};
    if(images.length){
      const form=new FormData();
      form.append("payload_json",JSON.stringify(payload));
      images.forEach((p,index)=>form.append("files["+index+"]",
        new Blob([p.bytes],{type:"image/png"}),p.filename));
      request.body=form;
    }else{
      headers["content-type"]="application/json";
      request.body=JSON.stringify(payload);
      request.headers=headers;
    }
    const r=await fetch(endpoint,request);
    if(!r.ok)throw Error("Discord réponse HTTP "+r.status+
      " "+(await r.text()).slice(0,200));
  }
  try{
    if(!["ens","gefs"].includes(model)||!["complet","temperature","pluie","pression"].includes(param)||
      ![10,15].includes(duration)||cityName.length<2||cityName.length>75)
      throw Error("Paramètres de commande non valides");
    const geoUrl=new URL("https://geocoding-api.open-meteo.com/v1/search");
    geoUrl.searchParams.set("name",cityName);
    geoUrl.searchParams.set("count","5");
    geoUrl.searchParams.set("countryCode","FR");
    geoUrl.searchParams.set("language","fr");
    geoUrl.searchParams.set("format","json");
    const geoResponse=await fetch(geoUrl,{cache:"no-store",
      signal:AbortSignal.timeout(12000)});
    if(!geoResponse.ok)throw Error("Géocodage des villes indisponible");
    const places=(await geoResponse.json()).results||[];
    const city=places.find(x=>x.name?.toLocaleLowerCase("fr")===cityName.toLocaleLowerCase("fr"))||places[0];
    if(!city||!Number.isFinite(city.latitude)||!Number.isFinite(city.longitude))
      throw Error("Ville française introuvable : "+cityName);
    const cityLabel=city.name+(city.admin1?", "+city.admin1:"");
    const modelName=model==="ens"?"ECMWF ENS":"NOAA GEFS";
    const modelCode=model==="ens"?"ecmwf_ifs025_ensemble":
      duration===10?"ncep_gefs025":"ncep_gefs05";
    let ensembleMetaBefore=null;
    try{ensembleMetaBefore=await kfsEnsembleMeta(modelCode);}
    catch(e){console.warn("KFS_META_BEFORE",String(e).slice(0,180));}
    const feed=new URL("https://ensemble-api.open-meteo.com/v1/ensemble");
    feed.searchParams.set("latitude",String(city.latitude));
    feed.searchParams.set("longitude",String(city.longitude));
    feed.searchParams.set("models",modelCode);
    feed.searchParams.set("hourly","temperature_2m,precipitation,pressure_msl");
    feed.searchParams.set("temporal_resolution","native");
    feed.searchParams.set("forecast_days",String(duration));
    feed.searchParams.set("timezone","UTC");
    feed.searchParams.set("cell_selection","land");
    const response=await fetch(feed,{cache:"no-store",
      signal:AbortSignal.timeout(60000)});
    if(!response.ok){
      const body=(await response.text()).slice(0,170);
      throw Error("Source d'ensemble indisponible : HTTP "+response.status+" "+body);
    }
    const payload=await response.json();
    if(payload.error)throw Error(String(payload.reason||"Réponse météo indisponible").slice(0,170));
    if(!payload.hourly?.time?.length)throw Error("Aucune échéance d'ensemble disponible");
    const series=kfsEnsembleSeries(payload.hourly,param);
    let ensembleMetaAfter=null;
    try{ensembleMetaAfter=await kfsEnsembleMeta(modelCode);}
    catch(e){console.warn("KFS_META_AFTER",String(e).slice(0,180));}
    const runVerified=Boolean(ensembleMetaBefore?.ready&&ensembleMetaAfter?.ready&&
      ensembleMetaBefore.iso===ensembleMetaAfter.iso);
    const latestEnsembleMeta=ensembleMetaAfter||ensembleMetaBefore;
    const shortEnsCycle=Boolean(model==="ens"&&duration===15&&latestEnsembleMeta&&
      [6,18].includes(new Date(latestEnsembleMeta.init).getUTCHours()));
    const runTitle=runVerified?kfsEnsembleRunTitle(latestEnsembleMeta)+
      (shortEnsCycle?" (échéances courtes)":""):"RUN à confirmer";
    const charts=await Promise.all(series.wanted.map(async name=>{
      const config=kfsEnsembleChart(name,series,modelName,cityLabel,duration,runTitle);
      return {name,filename:"kfs-"+model+"-"+name+".png",
        bytes:await kfsRenderEnsembleChart(config)};
    }));
    const names={temperature:"température 2 m",pluie:"précipitations 6 h",
      pression:"pression MSL"};
    const models=series.wanted.map(n=>series.values[n].memberCount);
    const units=model==="ens"?"ECMWF ENS 0,25°":"GEFS "+(duration===10?"0,25°":"0,5°");
    const last=series.timestamps.at(-1);
    const valid=Number.isFinite(last)?new Intl.DateTimeFormat("fr-FR",{
      timeZone:"Europe/Paris",day:"2-digit",month:"long",year:"numeric"}
    ).format(new Date(last)):"";
    const content="📈 **KFS MÉTÉO — DIAGRAMME D'ENSEMBLE**\n"+
      "📍 **"+cityLabel+"** · **"+modelName+"** · "+duration+" jours\n"+
      "📊 Paramètres : "+series.wanted.map(n=>names[n]).join(", ")+
      "\n🔎 "+units+" · "+Math.min(...models)+" membres minimum · jusqu'au "+valid+
      "\nBande colorée : percentiles **10–90 %** · trait : médiane · pointillés : moyenne."+
      (runVerified?"\n🕒 **"+runTitle+"** · cycle confirmé disponible chez Open-Meteo.":
        latestEnsembleMeta?"\n⏳ "+kfsEnsembleRunTitle(latestEnsembleMeta)+" détecté chez Open-Meteo, mais sa propagation est encore en cours : run des courbes non confirmé.":
        "\n⚠️ Initialisation du run non vérifiable actuellement.")+
      (shortEnsCycle?"\nℹ️ ECMWF ENS 06Z/18Z : les échéances à 15 jours peuvent encore provenir du dernier cycle long 00Z/12Z.":"")+
      "\n_Source et données : Open-Meteo (CC BY 4.0), données ECMWF/NOAA. Utilisation non commerciale._";
    const embeds=charts.map(p=>({
      title:names[p.name].toLocaleUpperCase("fr"),
      image:{url:"attachment://"+p.filename}
    }));
    await reply({content,embeds,allowed_mentions:{parse:[]},
      attachments:charts.map((p,i)=>({id:i,filename:p.filename,
        description:"KFS "+modelName+" — "+cityLabel+" — "+names[p.name]}))},charts);
  }catch(error){
    const msg="⚠️ **KFS MÉTÉO /diagramme** : "+
      String(error?.message||error).slice(0,400)+
      "\nLes valeurs manquantes ne sont pas remplacées par des estimations fictives.";
    await reply({content:msg,allowed_mentions:{parse:[]}}).catch(e=>
      console.error("KFS_DIAGRAMME_REPLY_ERROR",String(e)));
    console.error("KFS_DIAGRAMME_ERROR",String(error));
  }
}


async function kfsEnsembleNotifyDiscord(env){
 if(!env.DISCORD_BOT_TOKEN)return;
 const channel=String(env.KFS_RUN_ALERT_CHANNEL_ID||KFS_TENDANCE_CHANNEL||"");
 if(!/^\d{17,20}$/.test(channel))throw Error("Canal Discord non valide");
 const all=await Promise.allSettled(KFS_ENSEMBLE_META_CODES.map(kfsEnsembleMeta));
 const m=all.map((r,i)=>{
   if(r.status==="fulfilled")return r.value;
   console.warn("KFS_ENSEMBLE_SOURCE_PENDING",KFS_ENSEMBLE_META_CODES[i],
     String(r.reason).slice(0,150));
   return null;
 }).filter(Boolean);
 const now=Date.now();
 const valid=x=>x&&x.ready&&x.available&&now-x.available>=600000&&
   now-x.available<=4*3600000;
 const ecmwf=m.find(x=>x.modelCode==="ecmwf_ifs025_ensemble");
 const gefs=m.filter(x=>x.modelCode==="ncep_gefs025"||
   x.modelCode==="ncep_gefs05").filter(valid)
   .sort((a,b)=>b.init-a.init||Number(b.modelCode==="ncep_gefs05")-
     Number(a.modelCode==="ncep_gefs05"))[0];
 const pending=[{id:"ens",name:"ECMWF ENS",meta:ecmwf},
   {id:"gefs",name:"GEFS",meta:gefs}].filter(x=>valid(x.meta));
 if(!pending.length){console.log("KFS_ENSEMBLE_NO_AVAILABLE_RUN");return;}
 const history=await kfsDiscordCall(env,"/channels/"+channel+"/messages?limit=100");
 const seen=new Set();
 for(const msg of history||[]){
   if(!msg.author?.bot)continue;
   const combined=String(msg.content||"")+" "+
     (msg.embeds||[]).map(e=>String(e.footer?.text||"")).join(" ");
   for(const hit of combined.matchAll(/KFS-ENSEMBLE-RUN:(?:ens|gefs):\d{4}-\d{2}-\d{2}T(?:00|06|12|18):00:00Z/g))
     seen.add(hit[0]);
 }
 for(const x of pending){
   const key="KFS-ENSEMBLE-RUN:"+x.id+":"+x.meta.iso;
   if(seen.has(key))continue;
   const d=new Date(x.meta.init);
   const month=new Intl.DateTimeFormat("fr-FR",{timeZone:"UTC",month:"long"}).format(d);
   const hour=String(d.getUTCHours()).padStart(2,"0");
   const hint=x.id==="gefs"&&x.meta.modelCode==="ncep_gefs025"?
      "\nLes diagrammes à 10 jours sont prêts ; la version à 15 jours peut arriver ensuite.":"";
   const content="Toc toc ! Le nouveau run "+x.name+" "+hour+"Z du "+
      d.getUTCDate()+" "+month+
      " vient de sortir ! Tu peux le consulter en tapant /diagramme."+hint;
   await kfsDiscordCall(env,"/channels/"+channel+"/messages","POST",{
     content,embeds:[{footer:{text:key}}],allowed_mentions:{parse:[]}
   });
   seen.add(key);
   console.log("KFS_ENSEMBLE_NOTIFIED",key,x.meta.modelCode);
 }
}

