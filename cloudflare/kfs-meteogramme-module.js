// KFS METEO — /meteogramme
// Intended to be inserted before the worker's "export default" object.
// Uses existing kfsDiagGeo, kfsDiagGet, kfsDiagPut and kfsRenderEnsembleChart.
// All risk percentages below are heuristic indices, NOT calibrated probabilities.
const KFS_MGRAM_MODELS={
  gfs:{name:"GFS",code:"ncep_gfs_global",days:7},
  ifs:{name:"ECMWF IFS",code:"ecmwf_ifs025",days:7},
  arome:{name:"ARÔME France",code:"meteofrance_arome_france",days:2},
  icon:{name:"ICON Europe",code:"icon_eu",days:2}
};
let KFS_MGRAM_SYNCED=false;
async function kfsMgramRegister(env){
  if(!env.DISCORD_BOT_TOKEN)throw Error("DISCORD_BOT_TOKEN absent");
  const endpoint="https://discord.com/api/v10/applications/"+APPLICATION_ID+"/commands";
  const headers={"Authorization":"Bot "+env.DISCORD_BOT_TOKEN,"content-type":"application/json"};
  const modelChoices=Object.entries(KFS_MGRAM_MODELS).map(([value,m])=>({name:m.name,value}));
  const command={name:"meteogramme",type:1,
    description:"Météogramme horaire par ville · GFS/ECMWF 7 j, AROME/ICON 48 h",
    options:[
      {type:3,name:"ville",description:"Ville française (ex. Évreux)",required:true,min_length:2,max_length:75},
      {type:3,name:"modele",description:"Modèle météorologique",required:true,choices:modelChoices},
      {type:4,name:"jour",description:"Jour à détailler (J+0 à J+6 ; AROME/ICON : J+0 à J+1)",
        required:false,choices:Array.from({length:7},(_,i)=>({name:"J+"+i,value:i}))},
      {type:3,name:"affichage",description:"Un jour détaillé ou toute la période avec export horaire",
        required:false,choices:[
          {name:"Jour choisi · 2 graphiques + CSV",value:"jour"},
          {name:"Période complète · 7 j ou 48 h + CSV",value:"complet"}
        ]}
    ]};
  const list=await fetch(endpoint,{headers:{Authorization:headers.Authorization},signal:AbortSignal.timeout(12000)});
  if(!list.ok)throw Error("Lecture commandes Discord HTTP "+list.status);
  const commands=await list.json();
  const current=Array.isArray(commands)?commands.find(c=>c.name==="meteogramme"):null;
  if(current && current.options?.length===command.options.length &&
      current.options.some(x=>x.name==="affichage") &&
      current.options.find(x=>x.name==="modele")?.choices?.length===4) return;
  const resp=await fetch(endpoint,{method:"POST",headers,body:JSON.stringify(command),signal:AbortSignal.timeout(12000)});
  if(!resp.ok)throw Error("Enregistrement /meteogramme HTTP "+resp.status+" "+(await resp.text()).slice(0,200));
}
async function kfsMgramFetch(lat,lon,code,days,origin){
  const key=[lat.toFixed(3),lon.toFixed(3),code,days].join(":");
  const previous=await kfsDiagGet(origin,"mgram-hourly-v1",key);
  if(previous?.data?.hourly?.time?.length)return previous.data;
  const base=[
    "weather_code","temperature_2m","precipitation","rain","snowfall",
    "wind_speed_10m","wind_gusts_10m","wind_direction_10m","pressure_msl","cape"
  ];
  const extras=["showers","wet_bulb_temperature_2m","freezing_level_height"];
  const build=fields=>{
    const u=new URL("https://api.open-meteo.com/v1/forecast");
    u.searchParams.set("latitude",String(lat));
    u.searchParams.set("longitude",String(lon));
    u.searchParams.set("models",code);
    u.searchParams.set("timezone","Europe/Paris");
    u.searchParams.set("forecast_days",String(days));
    u.searchParams.set("hourly",fields.join(","));
    u.searchParams.set("wind_speed_unit","kmh");
    u.searchParams.set("precipitation_unit","mm");
    u.searchParams.set("cell_selection","land");
    return u;
  };
  const get=async(fields)=>{
    const resp=await fetch(build(fields),{signal:AbortSignal.timeout(17000)});
    if(!resp.ok)throw Error("Open-Meteo HTTP "+resp.status+" : "+(await resp.text()).slice(0,170));
    return resp.json();
  };
  let payload;
  try{payload=await get(base.concat(extras));}
  catch(error){
    console.warn("KFS_MGRAM_OPTIONAL_FALLBACK",String(error).slice(0,140));
    try{payload=await get(base);}
    catch(err){
      if(!String(err).includes("HTTP 400"))throw err;
      payload=await get(base.filter(f=>f!=="cape"&&f!=="rain"));
    }
  }
  if(!payload?.hourly?.time?.length)throw Error("Série horaire indisponible");
  // Nonavailable optional fields must stay null: never silently borrow another model.
  if(payload.hourly.cape===undefined){
    try{
      const extra=await get(["cape"]);
      if(JSON.stringify(extra.hourly?.time)===JSON.stringify(payload.hourly.time))
        payload.hourly.cape=extra.hourly.cape;
    }catch(e){console.warn("KFS_MGRAM_CAPE_MISSING",String(e).slice(0,120));}
  }
  await kfsDiagPut(origin,"mgram-hourly-v1",key,{data:payload},900);
  return payload;
}
function kfsMgramWx(code,isNight){
  const n=Number(code);
  if(n===0)return isNight?"🌙":"☀️";
  if(n===1)return isNight?"🌙":"🌤️";
  if(n===2)return "⛅";
  if(n===3)return "☁️";
  if(n===45||n===48)return "🌫️";
  if(n>=51&&n<=57)return "🌦️";
  if(n>=61&&n<=67)return "🌧️";
  if(n>=71&&n<=77)return "❄️";
  if(n>=80&&n<=82)return "🌦️";
  if(n>=85&&n<=86)return "🌨️";
  if(n>=95&&n<=99)return "⛈️";
  return "—";
}
function kfsMgramCompass(dir){
  if(!Number.isFinite(dir))return "—";
  return ["N","NE","E","SE","S","SO","O","NO"][Math.round(((dir%360)+360)%360/45)%8];
}
function kfsMgramRound(value,digits=0){
  return Number.isFinite(value)?Number(value.toFixed(digits)):null;
}
function kfsMgramClamp(x){return Math.max(0,Math.min(100,Math.round(x)));}
function kfsMgramRisk(row){
  const cap=Number.isFinite(row.cape)?Math.max(0,row.cape):null;
  const rain=Number.isFinite(row.rain)?Math.max(0,row.rain):null;
  const showers=Number.isFinite(row.showers)?Math.max(0,row.showers):null;
  const snow=Number.isFinite(row.snow)?Math.max(0,row.snow):null;
  const temp=Number.isFinite(row.temp)?row.temp:null;
  const wet=Number.isFinite(row.wet)?row.wet:temp;
  const freezing=Number.isFinite(row.freezing)?row.freezing:null;
  let storm=null;
  if(cap!==null){
    const conv=Math.min(1,cap/1300);
    const wetSignal=Math.min(1,(showers??rain??0)/2);
    storm=kfsMgramClamp((row.code>=95?55:0)+65*conv+20*wetSignal+
      (row.code>=95?12:0));
    if(cap<50&&row.code<95)storm=0;
  }else if(row.code>=95)storm=75;
  let strength="—";
  if(storm!==null&&storm>=20){
    strength=cap===null?"indét.":cap>=1800?"fort":cap>=650?"moyen":"faible";
  }
  let snowRisk=null;
  if(snow!==null){
    if(snow>=.5)snowRisk=95;
    else if(snow>.01)snowRisk=80;
    else if((rain??0)>.1&&wet!==null&&wet<=0)snowRisk=55;
    else if((rain??0)>.1&&wet!==null&&wet<=2)snowRisk=20;
    else snowRisk=0;
  }
  // Graupel is not an Open-Meteo native hourly variable.
  // Do not create a fictitious probability when necessary indicators are missing.
  let graupel=null;
  if(cap!==null&&wet!==null&&showers!==null&&freezing!==null){
    const instability=Math.min(1,cap/1000);
    const convective=Math.min(1,showers/2);
    const coldFactor=wet<=6?Math.max(0,1-Math.abs(wet-1)/9):0;
    const lowerFreezing=freezing<=1700?1:freezing<=2400?.4:0;
    graupel=kfsMgramClamp(100*instability*convective*coldFactor*lowerFreezing);
  }
  return {storm,strength,snowRisk,graupel};
}
function kfsMgramRows(hourly){
  const a=hourly.time||[];
  const value=(key,i)=>Number.isFinite(hourly[key]?.[i])?hourly[key][i]:null;
  return a.map((time,i)=>{
    const code=value("weather_code",i);
    const total=value("precipitation",i),liquid=value("rain",i),show=value("showers",i);
    const cm=value("snowfall",i);
    // If showers are supplied, liquid precipitation consists of rain + showers.
    // Otherwise derive total liquid from total precip minus snow water equivalent.
    const rain=liquid!==null&&show!==null?liquid+show:
      (total!==null&&cm!==null?Math.max(0,total-cm/0.7):liquid??total);
    const row={time,code,temp:value("temperature_2m",i),
      rain,snow:cm,wind:value("wind_speed_10m",i),
      gust:value("wind_gusts_10m",i),dir:value("wind_direction_10m",i),
      pressure:value("pressure_msl",i),cape:value("cape",i),
      showers:show,wet:value("wet_bulb_temperature_2m",i),
      freezing:value("freezing_level_height",i)};
    return {...row,...kfsMgramRisk(row)};
  });
}
function kfsMgramCsv(rows,model,city){
  const columns=["date_locale","modele","ville","picto","temperature_C","pluie_mm_h",
    "neige_cm_h","vent_kmh","rafale_kmh","direction_degres","direction_cardinale",
    "pression_hPa","CAPE_J_kg","indice_orage_pct","intensite_potentielle",
    "indice_neige_pct","indice_graupel_pct"];
  const escape=x=>'"'+String(x??"").replace(/"/g,'""')+'"';
  const records=rows.map(r=>[
    r.time,model,city,kfsMgramWx(r.code,false),r.temp,r.rain,r.snow,
    r.wind,r.gust,r.dir,kfsMgramCompass(r.dir),r.pressure,r.cape,
    r.storm,r.strength,r.snowRisk,r.graupel
  ].map(escape).join(";"));
  return "\ufeff"+columns.join(";")+"\r\n"+records.join("\r\n")+"\r\n";
}
function kfsMgramPlot(rows,title,mode){
  const labels=rows.map(r=>r.time.slice(11,16)+" "+kfsMgramWx(r.code,false));
  const val=(key,dec=1)=>rows.map(r=>kfsMgramRound(r[key],dec));
  const grid="#334356",font="#e7eef8";
  const axis=(id,pos,label,min,max)=>({
    id,type:"linear",position:pos,display:true,
    scaleLabel:{display:true,labelString:label,fontColor:font},
    ticks:{fontColor:font,min,max,beginAtZero:min===0},
    gridLines:{color:grid,drawOnChartArea:id==="temp"||id==="risk"}
  });
  const common={borderWidth:2,pointRadius:1,fill:false,spanGaps:false};
  const line=(label,key,color,axisId)=>({
    type:"line",label,data:val(key),borderColor:color,backgroundColor:color,
    yAxisID:axisId,...common
  });
  let datasets,yAxes;
  if(mode==="weather"){
    datasets=[
      {type:"bar",label:"Pluie (mm/h)",data:val("rain",2),yAxisID:"liquid",
       backgroundColor:"#43a8e6",borderWidth:0},
      {type:"bar",label:"Neige (cm/h)",data:val("snow",2),yAxisID:"liquid",
       backgroundColor:"#c6eafa",borderWidth:0},
      line("Température (°C)","temp","#ffc66d","temp"),
      line("Rafales (km/h)","gust","#f58595","wind"),
      line("Vent moyen (km/h)","wind","#7ed8b2","wind")
    ];
    yAxes=[axis("temp","left","Température °C"),
      axis("liquid","right","Pluie mm / neige cm",0),
      axis("wind","right","Vent / rafales km/h",0)];
  }else{
    datasets=[
      line("CAPE (J/kg)","cape","#f6be5b","cape"),
      line("Pression (hPa)","pressure","#79acff","pressure"),
      line("Indice orage (%)","storm","#ef6a72","risk"),
      line("Indice neige (%)","snowRisk","#d6ecff","risk"),
      line("Indice graupel (%)","graupel","#b79cfa","risk")
    ];
    yAxes=[axis("risk","left","Indices diagnostiques 0-100",0,100),
      axis("cape","right","CAPE J/kg",0),
      axis("pressure","right","Pression hPa")];
  }
  return {
    width:1450,height:550,version:"2",format:"png",backgroundColor:"#101c2d",
    chart:{type:"bar",data:{labels,datasets},options:{
      responsive:false,animation:false,
      title:{display:true,text:title,fontColor:font,fontSize:21},
      legend:{display:true,position:"top",labels:{fontColor:font,fontSize:14,boxWidth:18}},
      layout:{padding:{left:12,right:22,top:18,bottom:10}},
      scales:{
        xAxes:[{ticks:{fontColor:font,fontSize:10,maxRotation:60,minRotation:45,autoSkip:false},
          gridLines:{color:grid}}],
        yAxes
      }
    }}
  };
}
async function kfsMgramSend(interaction,payload,files){
  const u="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+
    "/"+interaction.token+"/messages/@original";
  let body,headers;
  if(files.length){
    body=new FormData();
    body.append("payload_json",JSON.stringify(payload));
    for(let i=0;i<files.length;i++){
      const f=files[i];
      body.append("files["+i+"]",new Blob([f.bytes],{type:f.type}),f.filename);
    }
  }else{
    body=JSON.stringify(payload);
    headers={"content-type":"application/json"};
  }
  const r=await fetch(u,{method:"PATCH",headers,body,signal:AbortSignal.timeout(25000)});
  if(!r.ok)throw Error("Envoi Discord HTTP "+r.status+" "+(await r.text()).slice(0,250));
}
async function kfsMgramComplete(interaction,cityName,model,jour,view,origin){
  try{
    const spec=KFS_MGRAM_MODELS[model];
    if(!spec||cityName.length<2||cityName.length>75||
      !Number.isInteger(jour)||jour<0||jour>6||!["jour","complet"].includes(view))
      throw Error("Paramètres de commande invalides");
    if(view==="jour"&&jour>=spec.days)
      throw Error(spec.name+" couvre 48 h : choisis J+0 ou J+1.");
    const geoUrl=new URL("https://geocoding-api.open-meteo.com/v1/search");
    geoUrl.searchParams.set("name",cityName);
    geoUrl.searchParams.set("count","5");
    geoUrl.searchParams.set("countryCode","FR");
    geoUrl.searchParams.set("language","fr");
    const matches=(await kfsDiagGeo(geoUrl,origin)).results||[];
    const selected=matches.find(x=>x.name?.toLowerCase()===cityName.toLowerCase())||matches[0];
    if(!selected||!Number.isFinite(selected.latitude)||!Number.isFinite(selected.longitude))
      throw Error("Commune française introuvable : "+cityName);
    const label=selected.name+(selected.admin1?" ("+selected.admin1+")":"");
    const weather=await kfsMgramFetch(selected.latitude,selected.longitude,spec.code,spec.days,origin);
    const all=kfsMgramRows(weather.hourly);
    const dates=[...new Set(all.map(r=>r.time.slice(0,10)))].slice(0,spec.days);
    if(dates.length<spec.days)throw Error("Prévisions incomplètes sur "+spec.days+" jours");
    const chosen=view==="complet"?dates:[dates[jour]];
    const rows=all.filter(r=>chosen.includes(r.time.slice(0,10)));
    if(rows.length<20)throw Error("Données horaires insuffisantes");
    const csv=kfsMgramCsv(rows,spec.name,label);
    const files=[{filename:"kfs-meteogramme-"+model+".csv",bytes:new TextEncoder().encode(csv),
      type:"text/csv;charset=utf-8"}];
    const pngs=[];
    let plotError="";
    for(const date of chosen){
      const day=rows.filter(r=>r.time.startsWith(date));
      try{
        const png=await kfsRenderEnsembleChart(kfsMgramPlot(day,
          spec.name+" • "+label+" • "+date+" • heure de Paris","weather"));
        pngs.push({filename:"kfs-"+model+"-"+date+".png",type:"image/png",bytes:png});
        if(view==="jour"){
          const second=await kfsRenderEnsembleChart(kfsMgramPlot(day,
            "Instabilité / pression / indices • "+date,"risk"));
          pngs.push({filename:"kfs-risques-"+model+"-"+date+".png",type:"image/png",bytes:second});
        }
      }catch(error){
        plotError=String(error?.message||error).slice(0,120);
        console.error("KFS_MGRAM_CHART",date,plotError);
      }
    }
    files.push(...pngs);
    const max=(field)=>{const values=rows.map(r=>r[field]).filter(Number.isFinite);return values.length?Math.max(...values):null;};
    const sum=(field)=>kfsMgramRound(rows.map(r=>r[field]).filter(Number.isFinite)
      .reduce((a,b)=>a+b,0),1);
    const fmt=(x,unit)=>x===null?"n/d":String(kfsMgramRound(x,1))+unit;
    const period=view==="complet"?spec.days+" jours":chosen[0];
    const content="🌦️ **KFS MÉTÉO — Météogramme "+spec.name+" · "+label+"**\n"+
      "📅 **"+period+"** · données horaires · heure locale Europe/Paris\n"+
      "🌡️ Température, pluie, neige, vent moyen/rafales et direction, pression et CAPE.\n"+
      "🌧️ Pluie totale : **"+fmt(sum("rain")," mm")+"** · neige fraîche : **"+fmt(sum("snow")," cm")+"**"+
      " · rafale maxi : **"+fmt(max("gust")," km/h")+"**\n"+
      "⚡ Indice orage maxi : **"+fmt(max("storm")," %")+"**"+
      " · indice neige : **"+fmt(max("snowRisk")," %")+"**"+
      " · indice graupel : **"+fmt(max("graupel")," %")+"**\n"+
      "📎 **CSV joint** : chaque heure et les 17 colonnes, dont pictos météo, orientation et intensité orageuse."+
      (pngs.length?"\n🖼️ "+pngs.length+" graphique(s) en pièces jointes.":"")+
      (plotError?"\n⚠️ Certains graphiques sont indisponibles : "+plotError:"")+
      "\n⚠️ **Indices orage/neige/graupel (%) : diagnostics heuristiques, PAS probabilités calibrées d'ensemble.**"+
      " La puissance orageuse est un potentiel CAPE, non une prévision de sévérité."+
      "\n_Source : Open-Meteo, modèle "+spec.name+" ; présentation KFS MÉTÉO._";
    await kfsMgramSend(interaction,
      {content:content.slice(0,1950),allowed_mentions:{parse:[]},
        attachments:files.map((f,i)=>({id:i,filename:f.filename,
          description:i===0?"Météogramme horaire complet CSV":"Graphique météogramme "+spec.name}))},files);
  }catch(error){
    console.error("KFS_METEOGRAMME_ERROR",String(error?.stack||error));
    await kfsMgramSend(interaction,{content:"⚠️ **/meteogramme** : "+
      String(error?.message||error).slice(0,350),allowed_mentions:{parse:[]}},[]).catch(
      e=>console.error("KFS_MGRAM_REPLY",String(e)));
  }
}
