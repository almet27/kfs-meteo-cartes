const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'cloudflare/kfs-proba-module.js'),'utf8');
function api(){return new Function(source+`;return {
 kfsProbaBlend,kfsProbaPreparedEnsembles,kfsProbaMemberProbability,kfsProbaResolveEnsembles,kfsProbaMultiComplete,
 setDeps(d){
  if(d.prepared)kfsProbaPreparedEnsembles=d.prepared;
  if(d.model)kfsProbaModel=d.model;
  if(d.storm)kfsProbaStormModel=d.storm;
  if(d.features)kfsProbaFeatures=d.features;
  if(d.samples)kfsProbaSamples=d.samples;
  if(d.resolve)kfsProbaResolveEnsembles=d.resolve;
  if(d.edit)kfsProbaEdit=d.edit;
  kfsProbaDepartments=async()=>[];kfsProbaRender=()=>'<svg/>';kfsProbaPng=async()=>new Uint8Array([1]);
 }
};`)();}
const member=(pct,members,amount=10)=>({pct,members,amount});
test('each model has half the weight despite unequal member counts',()=>{
 const r=api().kfsProbaBlend([
  {id:'ecmwf_ifs025_ensemble',name:'ECMWF',values:[member(70,50,20)]},
  {id:'ncep_gefs025',name:'GEFS',values:[member(40,30,10)]}
 ],1)[0];
 assert.equal(r.pct,55);assert.equal(r.amount,15);assert.equal(r.members,80);
 assert.equal(r.sources.length,2);
});
test('missing and invalid data are excluded, never counted as zero probability',()=>{
 const r=api().kfsProbaBlend([
  {id:'ens',values:[member(70,50),null,member(70,1),member(NaN,50)]},
  {id:'gefs',values:[null,member(40,30),null,null]}
 ],4);
 assert.equal(r[0].pct,70);assert.equal(r[0].sources.length,1);
 assert.equal(r[1].pct,40);assert.equal(r[2],null);assert.equal(r[3],null);
});
test('prepared ensembles reject stale, mismatched-period and mismatched-grid sources separately',async()=>{
 const old=global.fetch,a=api(),points=[{lat:49,lon:1}],day='2026-11-12';
 const make=()=>({generated_at_utc:new Date().toISOString(),periods:{'1':{start_day:day,end_day:day,zones:{FR:{pluie:{'1':[member(70,50)]}}}}}});
 const j={schema:2,provider:'Open-Meteo ECMWF ENS + GEFS members',timezone:'Europe/Paris',zone_points:{FR:[[49,1]]},
  models:{ecmwf_ifs025_ensemble:make(),ncep_gefs025:make()}};
 global.fetch=async()=>new Response(JSON.stringify(j));
 try{
  assert.equal((await a.kfsProbaPreparedEnsembles('pluie',1,'FR',1,day,day,points)).length,2);
  j.models.ncep_gefs025.generated_at_utc=new Date(Date.now()-29*3600000).toISOString();
  assert.equal((await a.kfsProbaPreparedEnsembles('pluie',1,'FR',1,day,day,points)).length,1);
  j.models.ecmwf_ifs025_ensemble.periods['1'].end_day='2026-11-13';
  assert.equal((await a.kfsProbaPreparedEnsembles('pluie',1,'FR',1,day,day,points)).length,0);
  j.models.ecmwf_ifs025_ensemble=make();j.zone_points.FR=[[48,2]];
  assert.equal((await a.kfsProbaPreparedEnsembles('pluie',1,'FR',1,day,day,points)).length,0);
 }finally{global.fetch=old;}
});
test('prepared and live data for the same ensemble cannot give that ensemble double weight',async()=>{
 const a=api(),calls=[];
 a.setDeps({prepared:async()=>[{id:'ecmwf_ifs025_ensemble',name:'ECMWF',values:[member(70,50),null]}],
  model:async model=>{calls.push(model[1]);return {name:model[0],values:[member(model[1]==='ncep_gefs025'?40:90,30),member(40,30)]};}});
 const r=await a.kfsProbaResolveEnsembles('pluie',1,'FR',1,'2026-11-12','2026-11-12',[{},{}]);
 assert.equal(calls.length,2);assert.equal(r.values[0].pct,55);
 assert.equal(r.values[0].sources.length,2);assert.equal(r.values[1].pct,40);
});
test('complete daily periods are required before mixing ensembles',()=>{
 const time=Array.from({length:23},(_,i)=>'2026-11-12T'+String(i).padStart(2,'0')+':00');
 assert.equal(api().kfsProbaMemberProbability({time,rain_member01:time.map(()=>1),rain_member02:time.map(()=>0)},'2026-11-12','pluie',1),null);
});
test('daily and five-day messages describe equal weights and explicit single-source fallback within Discord limits',async()=>{
 const a=api(),messages=[];
 a.setDeps({features:async()=>[{}],samples:()=>[{lat:49,lon:1},{lat:48,lon:2}],
  resolve:async()=>({values:[
   {pct:55,amount:15,sources:[{id:'ecmwf_ifs025_ensemble',members:50},{id:'ncep_gefs025',members:30}]},
   {pct:70,amount:10,sources:[{id:'ecmwf_ifs025_ensemble',members:50}]}],
   results:[{name:'ECMWF IFS ENS',consulted:'2026-11-11T10:00:00.000Z'},{name:'GEFS NOAA',consulted:'2026-11-11T10:00:00.000Z'}]}),
  edit:async(_interaction,payload)=>messages.push(payload.content)});
 for(const day of [1,6])for(const [type,threshold] of [['pluie',10],['neige_chutes',1],['gel',0],['orage',2],['vent',90],['neige',1]])
  assert.equal(await a.kfsProbaMultiComplete({},type,'FR',day,threshold),true);
 for(const content of messages){
  assert.match(content,/50 % ECMWF ENS \+ 50 % GEFS/);assert.match(content,/Mode dégradé/);
  assert.ok(content.length<=2000,'Discord message too long: '+content.length);
 }
 assert.match(messages[6],/probabilités journalières ne sont pas additionnées/);
});
test('the builder checkpoints both models, resumes without redownloading, and aggregates members before mixing',async()=>{
 const build=fs.readFileSync(path.join(root,'scripts/build_proba_ensembles.cjs'),'utf8');
 const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Paris'}).format(new Date());
 const first=Date.parse(today+'T00:00:00Z')-3600000;
 const time=Array.from({length:168},(_,i)=>(first+i*3600000)/1000);
 function data(model){
  const hourly={time};
  for(const [variable,value] of Object.entries({rain:model==='ncep_gefs025'?0:1,snow_depth:.01,snowfall:0,temperature_2m:1,wind_gusts_10m:60,cape:500,precipitation:1,dew_point_2m:10}))
   for(let n=1;n<=6;n++)hourly[variable+'_member0'+n]=time.map(()=>value);
  return {hourly};
 }
 const disk=new Map();let calls=0;
 const mockFs={readFileSync(file){if(file.endsWith('kfs-proba-module.js'))return source;if(file.endsWith('points-ecmwf.json'))return JSON.stringify({zones:{FR:[[49,1],[48,2]]}});return disk.get(file);},
  existsSync:file=>disk.has(file),writeFileSync:(file,v)=>disk.set(file,v),
  renameSync(a,b){disk.set(b,disk.get(a));disk.delete(a);},statSync:file=>({size:disk.get(file).length})};
 async function run(){
  const context={require:name=>name==='node:fs'?mockFs:require(name),__dirname:path.join(root,'scripts'),
   Intl,Date,Response,URLSearchParams,AbortSignal,process:{env:{},exitCode:0},console:{log(){},error:console.error},setTimeout:cb=>cb(),
   fetch:async url=>{calls++;const model=new URL(url).searchParams.get('models');return new Response(JSON.stringify([data(model),data(model)]));}};
  await vm.runInNewContext(build,context);assert.equal(context.process.exitCode,0);
 }
 await run();assert.equal(calls,2);await run();assert.equal(calls,2);
 const output=JSON.parse([...disk].find(([p])=>p.endsWith('ensemble-probabilities.json'))[1]);
 const ens=output.models.ecmwf_ifs025_ensemble.periods['6'].zones.FR.pluie['40'][0];
 const gefs=output.models.ncep_gefs025.periods['6'].zones.FR.pluie['40'][0];
 assert.equal(ens.amount,120);assert.equal(ens.pct,100);assert.equal(gefs.pct,0);
 assert.equal(api().kfsProbaBlend([{id:'ens',values:[ens]},{id:'gefs',values:[gefs]}],1)[0].pct,50);
});

test('publishing rejects missing shards, duplicate points, wrong dates and mismatched coordinates',()=>{
 const {merge}=require('../scripts/merge_proba_ensembles.cjs');
 assert.throws(()=>merge([]),/Missing shards/);
 const points=JSON.parse(fs.readFileSync(path.join(root,'proba/points-ecmwf.json'),'utf8')).zones;
 const rules=new Function(source+';return KFS_PROBA_RULES;')();
 const day=new Function(source+';return kfsProbaDay;')();
 const entries=Object.entries(points).flatMap(([zone,p])=>p.map((_,index)=>({zone,index})));
 const shards=[];
 for(const id of ['ecmwf_ifs025_ensemble','ncep_gefs025'])for(const index of [0,1]){
  const periods={};
  for(const jour of [0,1,2,3,4,5,6]){
   const zones=Object.fromEntries(Object.entries(points).map(([zone,p])=>[zone,
    Object.fromEntries(Object.entries(rules).map(([type,rule])=>[type,
     Object.fromEntries(rule.allowed.map(t=>[t,p.map(()=>member(70,50))]))]))]));
   periods[jour]={start_day:day(jour===6?1:jour),end_day:day(jour===6?5:jour),zones};
  }
  shards.push({schema:2,provider:'Open-Meteo ECMWF ENS + GEFS members',timezone:'Europe/Paris',zone_points:points,
   partition:{model:id,index,total:2,points:entries.filter((_,i)=>i%2===index)},
   models:{[id]:{generated_at_utc:new Date().toISOString(),periods}}});
 }
 assert.equal(Object.keys(merge(shards).models).length,2);
 const wrong=structuredClone(shards);wrong[1].partition.points.push(wrong[0].partition.points[0]);
 assert.throws(()=>merge(wrong),/Duplicate/);
 const wrongDates=structuredClone(shards);wrongDates[0].models.ecmwf_ifs025_ensemble.periods[0].end_day=day(1);
 assert.throws(()=>merge(wrongDates),/Wrong shard forecast period/);
 const wrongGrid=structuredClone(shards);wrongGrid[0].zone_points.FR[0][0]+=1;
 assert.throws(()=>merge(wrongGrid),/Invalid shard metadata/);
});
