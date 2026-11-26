#!/usr/bin/env node
// Prepare both ensembles once, outside the shared Cloudflare Open-Meteo quota.
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'cloudflare/kfs-proba-module.js'),'utf8');
const api=new Function(source+';return {KFS_PROBA_RULES,KFS_PROBA_BLEND_MODELS,kfsProbaDay,kfsProbaMemberProbability,kfsProbaStormMembers,kfsProbaNormalizeHourly,kfsProbaValidMemberResult};')();
// /alerte: 10 cm snowfall at altitude, in the existing mm-water approximation.
api.KFS_PROBA_RULES.neige_chutes.allowed.push(100/7);
const points=JSON.parse(fs.readFileSync(path.join(root,'proba/points-ecmwf.json'),'utf8')).zones;
// Mean of each complete member's daily maximum, for /alerte heat.
function alertTmax(hourly,start,end){
 const ids=hourly.time.map((t,i)=>String(t).slice(0,10)>=start&&String(t).slice(0,10)<=end?i:-1).filter(i=>i>=0);
 const values=Object.keys(hourly).filter(k=>k.startsWith('temperature_2m_')&&/member\d+/.test(k)).flatMap(k=>{const a=ids.map(i=>hourly[k]?.[i]);return a.length&&a.every(Number.isFinite)?[Math.max(...a)]:[];});
 return values.length>=2?values.reduce((x,y)=>x+y,0)/values.length:null;
}
const variables=['rain','snow_depth','snowfall','temperature_2m','wind_gusts_10m','cape','precipitation','dew_point_2m','weather_code'];
// Snow depth quality check: a sustained warm, snow-free 24-hour period
// must not produce a large increase in the model's snow depth.
// Reject the whole snow-depth series only when at least half the comparable
// ensemble members show the anomaly. Keep the other variables unchanged.
function suspectSnowDepth(hourly){
 const times=hourly?.time;if(!Array.isArray(times)||times.length<25)return false;
 let comparable=0,suspect=0;
 for(const key of Object.keys(hourly).filter(k=>/^snow_depth_member\d+$/.test(k))){
  const suffix=key.slice('snow_depth'.length),depth=hourly[key],temp=hourly['temperature_2m'+suffix],snow=hourly['snowfall'+suffix];
  if(!Array.isArray(depth)||!Array.isArray(temp)||!Array.isArray(snow))continue;
  let tested=false,bad=false;
  for(let i=24;i<times.length;i++){
   if(Date.parse(times[i])-Date.parse(times[i-24])!==86400000)continue;
   const t=temp.slice(i-24,i+1),s=snow.slice(i-23,i+1);
   if(t.length!==25||s.length!==24||!t.every(Number.isFinite)||!s.every(v=>Number.isFinite(v)&&v>=0)||!Number.isFinite(depth[i])||!Number.isFinite(depth[i-24]))continue;
   tested=true;
   if(Math.min(...t)>=4&&s.reduce((a,v)=>a+v,0)<=0.01&&depth[i]-depth[i-24]>=0.03){bad=true;break;}
  }
  if(tested){comparable++;if(bad)suspect++;}
 }
 return comparable>=10&&suspect>=Math.ceil(comparable/2);
}

async function probaCycle(id){
 try{
  const r=await fetch('https://api.open-meteo.com/data/'+id+'/static/meta.json?ts='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(8000)});
  if(!r.ok)return null;
  const j=await r.json(),init=Number(j.last_run_initialisation_time),avail=Number(j.last_run_availability_time);
  const ms=init>1e12?init:init*1000,ready=avail>1e12?avail:avail*1000;
  if(!Number.isFinite(ms)||!Number.isFinite(ready)||ready<ms||ready>Date.now()-600000||Date.now()-ms>7*86400000)return null;
  const d=new Date(ms);if(![0,6,12,18].includes(d.getUTCHours())||d.getUTCMinutes()!==0)return null;
  return d.toISOString();
 }catch{return null;}
}
async function main(){
 const today=api.kfsProbaDay(0),last=api.kfsProbaDay(6);
 const total=Number(process.env?.PROBA_SHARD_TOTAL??1),shard=Number(process.env?.PROBA_SHARD_INDEX??0);
 if(!Number.isInteger(total)||total<1||!Number.isInteger(shard)||shard<0||shard>=total)throw Error('Invalid shard');
 const selected=api.KFS_PROBA_BLEND_MODELS.filter(([,id])=>!process.env?.PROBA_MODEL||process.env.PROBA_MODEL===id);
 if(!selected.length||(total>1&&selected.length!==1))throw Error('Invalid model selection');
 const entries=Object.entries(points).flatMap(([zone,locations])=>locations.map(([lat,lon],index)=>({zone,index,lat,lon}))).filter((_,i)=>i%total===shard);
 const suffix=total>1?'-'+selected[0][1]+'-'+shard:'';
 const filename=path.join(root,'proba/ensemble'+(suffix?'-shard'+suffix:'-probabilities')+'.json');
 const checkpoint=path.join(root,'proba/ensemble-checkpoint'+suffix+'.json');
 const delay=Number(process.env?.PROBA_BATCH_DELAY_MS??65000);
 const batchSize=24;
 let state={schema:9,today,models:{}};
 if(fs.existsSync(checkpoint)){
  try{
   const saved=JSON.parse(fs.readFileSync(checkpoint,'utf8'));
   if(saved.schema===9&&saved.today===today&&saved.total===total&&saved.shard===shard&&saved.models&&
    JSON.stringify(saved.zone_points)===JSON.stringify(points))state=saved;
  }catch(error){console.log('Ignoring incompatible checkpoint:',error.message);}
 }
 state.zone_points=points;state.total=total;state.shard=shard;
 for(const [name,id] of selected){
  let model=state.models[id];
  const currentCycle=await probaCycle(id);
  if(!model||(currentCycle&&model.checkpoint_cycle!==currentCycle)||!Number.isInteger(model.next)||model.next<0||model.next>entries.length||
   !Number.isFinite(Date.parse(model.generated_at_utc))||Date.now()-Date.parse(model.generated_at_utc)>6*3600000||
  ![0,1,2,3,4,5,6].every(j=>model.periods?.[String(j)]?.start_day===api.kfsProbaDay(j===6?1:j)&&
   model.periods?.[String(j)]?.end_day===api.kfsProbaDay(j===6?5:j))){
   const periods=Object.fromEntries([0,1,2,3,4,5,6].map(j=>[String(j),{
    start_day:api.kfsProbaDay(j===6?1:j),end_day:api.kfsProbaDay(j===6?5:j),
    zones:Object.fromEntries(Object.keys(points).map(zone=>[zone,{}]))
   }]));
   model=state.models[id]={name,next:0,checkpoint_cycle:currentCycle,generated_at_utc:new Date().toISOString(),periods};
  }
  for(let offset=model.next;offset<entries.length;offset+=batchSize){
   const batch=entries.slice(offset,offset+batchSize);
   const params=new URLSearchParams({latitude:batch.map(p=>p.lat).join(','),longitude:batch.map(p=>p.lon).join(','),
    models:id,hourly:variables.join(','),start_date:api.kfsProbaDay(-1),end_date:last,
    timeformat:'unixtime',timezone:'Europe/Paris',temporal_resolution:'hourly_1'});
   let raw, runUtc=null;
   for(let attempt=0;attempt<4;attempt++){
    try{
     const before=await probaCycle(id);
     const response=await fetch('https://ensemble-api.open-meteo.com/v1/ensemble?'+params,
      {signal:AbortSignal.timeout(90000)});
     if(!response.ok){
      const message=(await response.text()).slice(0,250);
      if(response.status===429&&/Daily/i.test(message))throw Error('Daily quota exhausted: '+message);
      throw Error('Ensemble HTTP '+response.status+': '+message);
     }
     raw=await response.json();const after=await probaCycle(id);runUtc=before&&before===after?before:null;console.log(name,'cycle:',runUtc||'unknown','metadata before:',before,'after:',after);break;
    }catch(error){
     if(attempt===3||/Daily quota/.test(error.message))throw error;
     console.log(name,'temporary failure:',error.message,'retry',attempt+1);
     await new Promise(resolve=>setTimeout(resolve,Math.max(delay,/HTTP 429/.test(error.message)?65000:10000)));
    }
   }
   const data=Array.isArray(raw)?raw:[raw];
   if(data.length!==batch.length)throw Error('Unexpected point count for '+name);
   data.forEach((point,i)=>{
    const {zone,index}=batch[i],hourly=api.kfsProbaNormalizeHourly(point.hourly);
    const snowDepthSuspect=suspectSnowDepth(hourly);
    if(snowDepthSuspect)console.warn('Snow depth QC: excluded inconsistent series',name,zone,index, batch[i].lat,batch[i].lon);
    for(const [jour,period] of Object.entries(model.periods)){
     for(const [type,rule] of Object.entries(api.KFS_PROBA_RULES)){
      const fields=period.zones[zone][type]??={};
      for(const threshold of rule.allowed){
       const values=fields[String(threshold)]??=new Array(points[zone].length).fill(null);
       const value=type==='orage'?api.kfsProbaStormMembers(hourly,period.start_day,threshold,period.end_day):
        api.kfsProbaMemberProbability(hourly,period.start_day,type,threshold,period.end_day);
       // Snow depth is valid at every model elevation for every period. Do not mask mountain points.
        values[index]=type==='neige'&&snowDepthSuspect?null:(value&&['neige','neige_chutes','vent','gel'].includes(type)?{...value,elevation:Number.isFinite(point.elevation)?point.elevation:null,...(type==='gel'&&threshold===0?{tmax:alertTmax(hourly,period.start_day,period.end_day)}:{})}:value);
       if(values[index]&&runUtc)values[index].run_utc=runUtc;
      }
     }
     // Core variables must cover every point and the entire requested period.
     // Other missing fields remain null so the command can explicitly fall back.
     if(!api.kfsProbaValidMemberResult(period.zones[zone].pluie['1'][index])||
      !api.kfsProbaValidMemberResult(period.zones[zone].gel['0'][index]))
      throw Error('Incomplete member coverage: '+name+'/'+zone+'/'+jour+'/'+index);
    }
   });
   model.next=Math.min(offset+batchSize,entries.length);
   fs.writeFileSync(checkpoint+'.tmp',JSON.stringify(state));
   fs.renameSync(checkpoint+'.tmp',checkpoint);
   console.log(name,model.next+'/'+entries.length,'points');
   if(model.next<entries.length)await new Promise(resolve=>setTimeout(resolve,delay));
  }
 }
 if(today!==api.kfsProbaDay(0))throw Error('Paris date changed during generation; rerun');
 for(const model of Object.values(state.models)){
  if(model.next!==entries.length)throw Error('Partial model must not be published');
  for(const period of Object.values(model.periods))for(const [zone,types] of Object.entries(period.zones)){
   for(const fields of Object.values(types))for(const values of Object.values(fields)){
    if(values.length!==points[zone].length||values.some(v=>v!==null&&!api.kfsProbaValidMemberResult(v)))
     throw Error('Malformed ensemble dataset');
   }
  }
 }
 const output={schema:2,provider:'Open-Meteo ECMWF ENS + GEFS members',timezone:'Europe/Paris',
  generated_at_utc:new Date().toISOString(),zone_points:points,
  partition:total>1?{model:selected[0][1],index:shard,total,points:entries.map(({zone,index})=>({zone,index}))}:null,
  models:Object.fromEntries(selected.map(([,id])=>{
   const {next,...model}=state.models[id];return [id,model];
  })),
  method:'For each ensemble and period: follow each member, aggregate rain/snowfall before threshold; use minimum for frost and maximum for snow depth/gusts/storm potential. At display time, average the two ensemble probabilities with equal 50/50 weights, independently of member counts.',
  source:'https://open-meteo.com/en/docs/ensemble-api',license:'CC BY 4.0',
  notice:'Experimental uncalibrated ensemble proportions. Acquisition times are NOT model initialization times.'};
 fs.writeFileSync(filename+'.tmp',JSON.stringify(output)+'\n');
 fs.renameSync(filename+'.tmp',filename);
 console.log('Published',filename,fs.statSync(filename).size,'bytes');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
