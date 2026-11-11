#!/usr/bin/env node
// Five-day member trajectories, precomputed outside the shared Worker IP quota.
// Reuse the exact reducers used by the Discord command. No independence assumption.
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'cloudflare/kfs-proba-module.js'),'utf8');
const api=new Function(source+';return {KFS_PROBA_RULES,kfsProbaDay,kfsProbaMemberProbability,kfsProbaStormMembers};')();
const points=JSON.parse(fs.readFileSync(path.join(root,'proba/points-ecmwf.json'),'utf8')).zones;
const variables=['rain','snow_depth','snowfall','temperature_2m','wind_gusts_10m',
 'cape','precipitation','dew_point_2m'];
async function main(){
 const start=api.kfsProbaDay(1),end=api.kfsProbaDay(5);
 const entries=Object.entries(points).flatMap(([zone,locations])=>locations.map(([lat,lon],index)=>({zone,index,lat,lon})));
 const zones=Object.fromEntries(Object.keys(points).map(zone=>[zone,{}]));
 let consulted=null;
 for(let offset=0;offset<entries.length;offset+=24){
  const batch=entries.slice(offset,offset+24);
  const params=new URLSearchParams({latitude:batch.map(p=>p.lat).join(','),longitude:batch.map(p=>p.lon).join(','),
   models:'ncep_gefs025',hourly:variables.join(','),start_date:start,end_date:end,
   timezone:'Europe/Paris',temporal_resolution:'hourly_1'});
  let response;
  for(let attempt=0;attempt<4;attempt++){
   response=await fetch('https://ensemble-api.open-meteo.com/v1/ensemble?'+params,
   {signal:AbortSignal.timeout(90000)});
   if(response.status!==429)break;
   const message=await response.text();
   if(!/Minutely|Hourly/.test(message))throw Error(message);
   console.log('Rate limit; waiting before retry',attempt+1);
   await new Promise(resolve=>setTimeout(resolve,65000));
  }
  if(!response.ok)throw Error('Ensemble HTTP '+response.status);
  const raw=await response.json(),data=Array.isArray(raw)?raw:[raw];
  if(data.length!==batch.length)throw Error('Unexpected point count');
  consulted=new Date().toISOString();
  data.forEach((point,i)=>{
   const {zone,index}=batch[i];
   for(const [type,rule] of Object.entries(api.KFS_PROBA_RULES)){
    const fields=zones[zone][type]??={};
    for(const threshold of rule.allowed){
     const values=fields[String(threshold)]??=new Array(points[zone].length).fill(null);
     values[index]=type==='orage'?api.kfsProbaStormMembers(point.hourly,start,threshold,end):
      api.kfsProbaMemberProbability(point.hourly,start,type,threshold,end);
     if(!values[index] || values[index].members<5)throw Error('Incomplete member coverage: '+zone+'/'+type+'/'+threshold);
    }
   }
  });
  console.log('Five-day members:',Math.min(offset+24,entries.length)+'/'+entries.length,'points');
  if(offset+24<entries.length)await new Promise(resolve=>setTimeout(resolve,65000));
 }
 if(start!==api.kfsProbaDay(1))throw Error('Paris date changed during generation; rerun');
 // A partial new forecast must never replace a valid published dataset.
 for(const [zone,types] of Object.entries(zones))for(const [type,thresholds] of Object.entries(types)){
  for(const [threshold,values] of Object.entries(thresholds)){
   if(values.some(v=>!v||v.members<5||!Number.isFinite(v.amount)||!Number.isFinite(v.pct)))
    throw Error('Incomplete five-day forecast: '+zone+'/'+type+'/'+threshold);
  }
 }
 const output={schema:1,provider:'Open-Meteo five-day ensemble members',model:'ncep_gefs025',
  generated_at_utc:consulted,start_day:start,end_day:end,duration_days:5,timezone:'Europe/Paris',
  zone_points:points,zones,
  method:'Each perturbed ensemble member is tracked across five complete Paris days. Rain/falling snow: sum before threshold. Frost: minimum. Snow cover/gust/storm potential: maximum. No daily probability addition.',
  source:'https://open-meteo.com/en/docs/ensemble-api',license:'CC BY 4.0',
  notice:'30 perturbed GEFS members where available; experimental, uncalibrated proportions. Generation time is NOT model run time.'};
 const filename=path.join(root,'proba/five-day-probabilities.json');
 fs.writeFileSync(filename+'.tmp',JSON.stringify(output)+'\n');
 fs.renameSync(filename+'.tmp',filename);
 console.log('Published',filename,fs.statSync(filename).size,'bytes',start,'to',end);
}
main().catch(error=>{console.error(error);process.exitCode=1;});
