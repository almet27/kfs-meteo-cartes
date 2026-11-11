#!/usr/bin/env node
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'cloudflare/kfs-proba-module.js'),'utf8');
const api=new Function(source+';return {KFS_PROBA_RULES,KFS_PROBA_BLEND_MODELS,kfsProbaDay,kfsProbaValidMemberResult};')();
function merge(shards){
 const points=JSON.parse(fs.readFileSync(path.join(root,'proba/points-ecmwf.json'),'utf8')).zones;
 const output={schema:2,provider:'Open-Meteo ECMWF ENS + GEFS members',timezone:'Europe/Paris',
  generated_at_utc:new Date().toISOString(),zone_points:points,models:{},
  method:'Each ensemble is reduced member by member over the same Paris civil period; probabilities and mean quantities receive equal 50/50 model weights at display time.',
  source:'https://open-meteo.com/en/docs/ensemble-api',license:'CC BY 4.0',
  notice:'Experimental uncalibrated proportions. Acquisition times are NOT model initialization times.'};
 for(const [name,id] of api.KFS_PROBA_BLEND_MODELS){
  const parts=shards.filter(s=>s.partition?.model===id),seen=new Set(),partIndices=new Set();
  if(parts.length!==2)throw Error('Missing shards for '+id);
  const model=output.models[id]={name,generated_at_utc:null,periods:{}};
  for(const j of parts){
   const partition=j.partition,m=j.models?.[id],age=Date.now()-Date.parse(m?.generated_at_utc);
   if(j.schema!==2||j.provider!==output.provider||j.timezone!=='Europe/Paris'||partition.total!==2||
    ![0,1].includes(partition.index)||partIndices.has(partition.index)||!Number.isFinite(age)||age<0||age>6*3600000||
    JSON.stringify(j.zone_points)!==JSON.stringify(points))throw Error('Invalid shard metadata: '+id);
   partIndices.add(partition.index);
   if(!model.generated_at_utc||m.generated_at_utc<model.generated_at_utc)model.generated_at_utc=m.generated_at_utc;
   for(const {zone,index} of partition.points){
    const key=zone+'/'+index;
    if(!points[zone]?.[index]||seen.has(key))throw Error('Duplicate or unknown shard point: '+key);
    seen.add(key);
    for(const jour of [0,1,2,3,5]){
     const start=api.kfsProbaDay(jour===5?1:jour),end=api.kfsProbaDay(jour===5?5:jour);
     const period=m.periods?.[jour];
     if(period?.start_day!==start||period.end_day!==end)throw Error('Wrong shard forecast period');
     const target=model.periods[jour]??={start_day:start,end_day:end,zones:{}};
     const types=target.zones[zone]??={};
     for(const [type,rule] of Object.entries(api.KFS_PROBA_RULES)){
      const fields=types[type]??={};
      for(const threshold of rule.allowed){
       const input=period.zones?.[zone]?.[type]?.[threshold],value=input?.[index];
       if(!Array.isArray(input)||input.length!==points[zone].length||
        (value!==null&&!api.kfsProbaValidMemberResult(value)))throw Error('Invalid shard values');
       const values=fields[threshold]??=new Array(points[zone].length).fill(null);
       values[index]=value;
      }
     }
     if(!api.kfsProbaValidMemberResult(types.pluie['1'][index])||!api.kfsProbaValidMemberResult(types.gel['0'][index]))
      throw Error('Missing core forecast');
    }
   }
  }
  const count=Object.values(points).reduce((n,p)=>n+p.length,0);
  if(seen.size!==count)throw Error('Incomplete shard coverage');
 }
 return output;
}
if(require.main===module){
 const directory=process.argv[2]||path.join(root,'ensemble-shards');
 const files=fs.readdirSync(directory,{recursive:true}).filter(f=>/^ensemble-shard.*\.json$/.test(path.basename(f)));
 const result=merge(files.map(f=>JSON.parse(fs.readFileSync(path.join(directory,f),'utf8'))));
 const filename=path.join(root,'proba/ensemble-probabilities.json');
 fs.writeFileSync(filename+'.tmp',JSON.stringify(result)+'\n');fs.renameSync(filename+'.tmp',filename);
 console.log('Published validated ECMWF ENS + GEFS dataset:',fs.statSync(filename).size,'bytes');
}
module.exports={merge};
