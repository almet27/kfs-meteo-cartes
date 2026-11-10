// KFS_FRANCE_MINMAX_OVERVIEW_20261110
// Vue sans J+ pour /france. Les données déjà publiées sont utilisées sans interpolation de valeurs manquantes.
async function kfsFranceMinMaxOverview(interaction,model,zone){
  const endpoint="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+"/"+interaction.token+"/messages/@original";
  const names={ifs:"ECMWF IFS",gfs:"NOAA GFS","aifs-single":"ECMWF AIFS",aigfs:"NOAA AIGFS",
    arome:"ARÔME France",icon_eu:"ICON Europe","ifs9-early":"ECMWF IFS 9 km anticipé"};
  const types=["tmin","tmax"],items=[],missing=[];
  const parts=new Intl.DateTimeFormat("en-US",{timeZone:"Europe/Paris",
    year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date());
  const val=k=>Number(parts.find(p=>p.type===k)?.value);
  const today=Date.UTC(val("year"),val("month")-1,val("day"));
  const dateAt=d=>new Date(today+d*86400000).toISOString().slice(0,10);
  const add=(day,date,kind,url,run,ext,partial=false)=>items.push({day,date,kind,url,run,ext,partial});
  try{
    if(!names[model])throw Error("Modèle non reconnu.");
    if(zone!=="FR"){
      if(model==="ifs9-early")throw Error("Les cartes ECMWF 9 km anticipées ne couvrent pas encore les régions.");
      const regions=await kfsProbaFeatures();
      const features=regions.filter(f=>String(f.properties?.code)===zone);
      if(features.length!==1)throw Error("Zone régionale introuvable.");
      const samples=kfsProbaSamples(features,true);
      const departments=await kfsProbaDepartments(zone);
      const last=["arome","icon_eu"].includes(model)?2:3;
      for(let day=1;day<=last;day++){
        for(const kind of types){
          try{
            const forecast=await kfsFranceRegionRequest(model,kind,day,24,samples);
            if(forecast.date!==dateAt(day))throw Error("Date du modèle incohérente");
            const points=samples.map((p,i)=>({...p,value:forecast.values[i],
              weatherCode:forecast.codes?.[i]??null,weatherKind:forecast.kinds?.[i]??null}));
            const frame=kfsFranceRegionalRender(features,departments,points,zone,kind,"J+"+day);
            const bytes=await kfsProbaPng(frame);
            items.push({day,date:forecast.date,kind,ext:"png",partial:forecast.coverage!=="complete",
              filename:"kfs-france-"+zone+"-j"+day+"-"+kind+".png",bytes});
          }catch(error){missing.push("J+"+day+" "+kind+" ("+String(error.message||error).slice(0,55)+")");}
        }
      }
    }else if(["ifs","gfs","aifs-single","aigfs"].includes(model)){
      const root="https://github.com/almet27/kfs-meteo-cartes/releases/download/france-"+model+"/";
      const primary=await kfsFranceReadCatalog(root,model);
      if(primary.schema!==2||primary.model!==model||primary.area!=="France")
        throw Error("Catalogue France invalide.");
      let secondary=null;
      const last=["ifs","gfs"].includes(model)?5:3;
      let ext=null;
      if(last===5){
        const rootExt="https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/forecast-maps/france/daily-extended/";
        try{
          const resp=await fetch(rootExt+"latest.json?kfs="+Math.floor(Date.now()/300000),
            {signal:AbortSignal.timeout(11000)});
          if(resp.ok){
            const value=await resp.json(),stamp=Date.parse(value.generated_utc||"");
            if(value.schema===1&&value.not_native_grib===true&&Number.isFinite(stamp)&&
              Date.now()-stamp<48*3600000&&stamp<Date.now()+3600000)ext=value;
          }
        }catch(error){console.warn("KFS_FRANCE_MINMAX_EXT",String(error).slice(0,160));}
      }
      for(let day=1;day<=last;day++){
        const date=dateAt(day);
        if(day>=4){
          const entry=ext?.models?.[model]?.days?.[String(day)];
          for(const kind of types){
            const asset=entry?.maps?.[kind],file="daily-"+model+"-"+kind+"-d"+day+".webp";
            if(entry?.date===date&&asset?.filename===file&&asset.bytes>=10000)
              add(day,date,kind,"https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/forecast-maps/france/daily-extended/"+file,
                ext.generated_utc,"webp");
            else missing.push("J+"+day+" "+kind);
          }
          continue;
        }
        let active=primary,activeRoot=root;
        let record=Object.values(primary.daily||{}).find(info=>info?.date===date);
        if(!record?.maps?.tmin?.file||!record?.maps?.tmax?.file){
          try{
            if(!secondary){
              const oldRoot="https://github.com/almet27/kfs-meteo-cartes/releases/download/france-"+model+"-daily/";
              secondary={root:oldRoot,data:await kfsFranceReadCatalog(oldRoot,model)};
            }
            const old=secondary.data,age=Date.parse(primary.run_utc)-Date.parse(old.run_utc);
            const candidate=Object.values(old.daily||{}).find(info=>info?.date===date);
            if(old.schema===2&&old.model===model&&old.area==="France"&&
              Number.isFinite(age)&&age>=0&&age<=36*3600000&&
              candidate?.maps?.tmin?.file&&candidate?.maps?.tmax?.file){
              active=old;activeRoot=secondary.root;record=candidate;
            }
          }catch(error){console.warn("KFS_FRANCE_MINMAX_DAILY",String(error).slice(0,130));}
        }
        for(const kind of types){
          const file=record?.maps?.[kind]?.file;
          if(/^daily-(tmin|tmax)-d[0-3]\.webp$/.test(file||""))
            add(day,date,kind,activeRoot+file,active.run_utc,"webp",record.coverage!=="complete");
          else missing.push("J+"+day+" "+kind);
        }
      }
    }else if(model==="arome"||model==="icon_eu"){
      const base="https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/forecast-maps/france/shortterm-daily/";
      const response=await fetch(base+"latest.json?kfs="+Math.floor(Date.now()/300000),
        {signal:AbortSignal.timeout(12000)});
      if(!response.ok)throw Error("Catalogue ARÔME/ICON non publié (HTTP "+response.status+").");
      const meta=await response.json(),stamp=Date.parse(meta.generated_utc||"");
      if(meta.schema!==1||meta.not_native_grid!==true||!Number.isFinite(stamp)||
        Date.now()-stamp>36*3600000)throw Error("Catalogue court terme ancien ou invalide.");
      for(let day=1;day<=2;day++){
        const record=meta.models?.[model]?.days?.[String(day)];
        for(const kind of types){
          const filename="daily-"+model+"-"+kind+"-d"+day+".png",asset=record?.maps?.[kind];
          if(record?.date===dateAt(day)&&asset?.filename===filename&&asset.size_bytes>=12000)
            add(day,record.date,kind,base+filename,meta.models[model].run_utc,"png",record.coverage!=="complete");
          else missing.push("J+"+day+" "+kind);
        }
      }
    }else if(model==="ifs9-early"){
      const base="https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/forecast-maps/france/ifs-early9km/";
      const response=await fetch(base+"latest.json?kfs="+Math.floor(Date.now()/300000),
        {signal:AbortSignal.timeout(12000)});
      if(!response.ok)throw Error("Catalogue IFS 9 km anticipé non encore publié.");
      const meta=await response.json(),stamp=Date.parse(meta.run_utc||"");
      if(meta.schema!==1||meta.model!=="ecmwf_ifs"||meta.resolution_native_km!==9||
        !Number.isFinite(stamp)||Date.now()-stamp>36*3600000)
        throw Error("Catalogue ECMWF anticipé ancien ou invalide.");
      for(let day=1;day<=2;day++){
        const record=meta.days?.[String(day)];
        for(const kind of types){
          const asset=record?.maps?.[kind],file="ifs9-"+kind+"-j"+day+".webp";
          if(record?.date===dateAt(day)&&asset?.file===file)
            add(day,record.date,kind,base+file,meta.run_utc,"webp",(asset.coverage_hours||0)<23);
          else missing.push("J+"+day+" "+kind);
        }
      }
    }
    if(!items.length)throw Error("Aucune carte Tmin/Tmax vérifiée pour les prochains jours.");
    const readImage=async it=>{
      if(it.bytes)return it;
      let data;
      if(it.ext==="webp"){
        const r=await kfsFranceReadWebP(it.url,it.run);
        if(!r.ok)throw Error("HTTP "+r.status);
        data=new Uint8Array(await r.arrayBuffer());
        if(data.length<1000||data.length>7500000||data[0]!==82||data[1]!==73||
          data[2]!==70||data[3]!==70||data[8]!==87||data[9]!==69||
          data[10]!==66||data[11]!==80)throw Error("WebP incorrect");
      }else{
        const r=await fetch(it.url,{signal:AbortSignal.timeout(12000)});
        if(!r.ok)throw Error("HTTP "+r.status);
        data=new Uint8Array(await r.arrayBuffer());
        if(data.length<1000||data.length>7500000||data[0]!==137||data[1]!==80||
           data[2]!==78||data[3]!==71)throw Error("PNG incorrect");
      }
      return {...it,bytes:data,
        filename:"kfs-france-"+model+"-j"+it.day+"-"+it.kind+"."+it.ext};
    };
    const loaded=[];
    for(let i=0;i<items.length;i+=4){
      const chunk=await Promise.allSettled(items.slice(i,i+4).map(readImage));
      chunk.forEach((r,j)=>{
        if(r.status==="fulfilled")loaded.push(r.value);
        else missing.push("J+"+items[i+j].day+" "+items[i+j].kind+" (image indisponible)");
      });
    }
    if(!loaded.length)throw Error("Fichiers de prévision indisponibles sur ce run.");
    const zoneName=zone==="FR"?"France entière":KFS_PROBA_REGIONS.find(r=>r[0]===zone)?.[1]||zone;
    const days=[...new Set(loaded.map(it=>it.day))].sort((a,b)=>a-b);
    const summary=days.map(d=>{
      const v=loaded.filter(x=>x.day===d);
      const present=v.map(x=>x.kind==="tmin"?"Tmin":"Tmax").join(" + ");
      return "📅 **J+"+d+" — "+dateAt(d).split("-").reverse().join("/")+"** : "+present+
        (v.some(x=>x.partial)?" ⚠️ journée partielle":"");
    }).join("\n");
    const caveat=["ifs","gfs"].includes(model)&&days.some(d=>d>=4)?
      "\nℹ️ J+4/J+5 : cartes issues d'un échantillonnage Open-Meteo (25–35 km), distinct des GRIB natifs.":"";
    const regionNote=zone!=="FR"?"\nℹ️ Cartes régionales interpolées entre points de prévision Open-Meteo.":"";
    const missingNote=missing.length?"\n⚠️ Non disponibles : "+missing.slice(0,9).join(", ")+
      (missing.length>9?"…":"")+".":"";
    const content=("🌡️ **KFS MÉTÉO /france — MINIMALES ET MAXIMALES**\n"+
      "**"+names[model]+" · "+zoneName+"**\n"+summary+
      "\n📊 Tmin et Tmax de chaque jour civil (heure de Paris)."+caveat+regionNote+missingNote+
      "\n_Source : "+(["ifs","aifs-single","ifs9-early"].includes(model)?"ECMWF":
        ["gfs","aigfs"].includes(model)?"NOAA":"Météo-France/ICON")+
      " ; diffusion et traitement KFS MÉTÉO._").slice(0,1950);
    const attachments=loaded.map((v,i)=>({id:i,filename:v.filename,
      description:"J+"+v.day+" "+(v.kind==="tmin"?"température minimale":"température maximale")}));
    const embeds=loaded.map(v=>({title:"J+"+v.day+" • "+(v.kind==="tmin"?"Températures minimales":"Températures maximales")+
      " • "+v.date,image:{url:"attachment://"+v.filename}}));
    const form=new FormData();
    form.append("payload_json",JSON.stringify({content,allowed_mentions:{parse:[]},attachments,embeds}));
    loaded.forEach((v,i)=>form.append("files["+i+"]",new Blob([v.bytes],{
      type:v.ext==="png"?"image/png":"image/webp"}),v.filename));
    const reply=await fetch(endpoint,{method:"PATCH",body:form,signal:AbortSignal.timeout(19000)});
    if(!reply.ok)throw Error("Discord HTTP "+reply.status+" "+
      (await reply.text().catch(()=>"")).slice(0,160));
  }catch(error){
    console.error("KFS_FRANCE_MINMAX_OVERVIEW",model,zone,String(error).slice(0,300));
    await kfsFranceSendDiscord(endpoint,{content:"⚠️ **/france — Tmin/Tmax des prochains jours** : "+
      String(error?.message||error).slice(0,260)+
      "\nTu peux toujours choisir un J+ explicite pour une seule carte.",
      allowed_mentions:{parse:[]}}).catch(()=>{});
  }
}
