const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../cloudflare/kfs-proba-module.js'),'utf8');
const api=new Function(source+';return {kfsProbaMemberProbability,kfsProbaStormMembers,kfsProbaRegister,kfsProbaFiveDayComplete,kfsProbaFiveDayRead,kfsProbaNormalizeHourly};')();
const start='2026-11-12',end='2026-11-16';
function hourly(variable,values){
 const time=Array.from({length:120},(_,i)=>new Date(Date.UTC(2026,10,12,0,i*60)).toISOString().slice(0,16));
 const data={time};
 values.forEach((v,i)=>data[variable+'_member'+String(i+1).padStart(2,'0')]=
  time.map((_,h)=>typeof v==='function'?v(h):v));
 return data;
}
test('rain threshold applies to the five-day member sum',()=>{
 const h=hourly('rain',[i=>i%24===0?3:0,i=>i%24===0?1:0]);
 const cumulative=api.kfsProbaMemberProbability(h,start,'pluie',10,end);
 assert.equal(cumulative.pct,50);
 assert.equal(cumulative.amount,10);
 assert.equal(api.kfsProbaMemberProbability(h,start,'pluie',10).pct,0);
});
test('event union follows the same members; daily probabilities cannot be added',()=>{
 const same=hourly('temperature_2m',[i=>i%24===0?-2:5,5]);
 assert.equal(api.kfsProbaMemberProbability(same,start,'gel',0,end).pct,50);
 const different=hourly('temperature_2m',[i=>i===0?-2:5,i=>i===24?-2:5]);
 assert.equal(api.kfsProbaMemberProbability(different,start,'gel',0,end).pct,100);
});
test('snow cover is a maximum; falling snow is summed with correct units',()=>{
 const cover=hourly('snow_depth',[0.02,0.01]);
 const result=api.kfsProbaMemberProbability(cover,start,'neige',3,end);
 assert.equal(result.pct,0);
 assert.equal(result.amount,1.5);
 const snowfall=hourly('snowfall',[i=>i%24===0?.7:0,0]);
 const fresh=api.kfsProbaMemberProbability(snowfall,start,'neige_chutes',3,end);
 assert.equal(fresh.pct,50);
 assert.ok(Math.abs(fresh.amount-2.5)<1e-10);
});
test('gust uses maximum and not sum',()=>{
 const h=hourly('wind_gusts_10m',[i=>i===80?100:20,40]);
 const result=api.kfsProbaMemberProbability(h,start,'vent',90,end);
 assert.equal(result.pct,50);
 assert.equal(result.amount,70);
});
test('missing day and incomplete member cannot become a low-risk forecast',()=>{
 const h=hourly('rain',[1,1]);
 h.rain_member01[55]=null;
 assert.equal(api.kfsProbaMemberProbability(h,start,'pluie',1,end),null);
 const partial=hourly('rain',[1,1]);
 partial.time=partial.time.slice(0,96);
 assert.equal(api.kfsProbaMemberProbability(partial,start,'pluie',1,end),null);
 const missingHour=hourly('rain',[1,1]);
 missingHour.time.splice(55,1);
 missingHour.rain_member01.splice(55,1);missingHour.rain_member02.splice(55,1);
 assert.equal(api.kfsProbaMemberProbability(missingHour,start,'pluie',1,end),null);
});
test('prepared data must match the dates, coordinates and freshness',async()=>{
 const old=global.fetch;
 const points=[{lat:49,lon:1},{lat:48,lon:2}];
 const j={schema:1,provider:'Open-Meteo ECMWF IFS ENS five-day members',
  model:'ecmwf_ifs025_ensemble',generated_at_utc:new Date().toISOString(),start_day:start,end_day:end,duration_days:5,
  zone_points:{FR:[[49,1],[48,2]]},zones:{FR:{pluie:{'10':[
   {pct:50,amount:25,members:50},{pct:80,amount:40,members:50}]}}}};
 global.fetch=async()=>new Response(JSON.stringify(j));
 try{
  assert.ok(await api.kfsProbaFiveDayRead('pluie',10,'FR',start,end,points));
  assert.equal(await api.kfsProbaFiveDayRead('pluie',10,'FR',start,'2026-11-17',points),null);
  assert.equal(await api.kfsProbaFiveDayRead('pluie',10,'FR',start,end,[...points].reverse()),null);
  j.generated_at_utc=new Date(Date.now()-29*3600000).toISOString();
  assert.equal(await api.kfsProbaFiveDayRead('pluie',10,'FR',start,end,points),null);
 }finally{global.fetch=old;}
});
test('storm potential is counted once per member across the five days',()=>{
 const h=hourly('cape',[i=>i===25?700:0,i=>i===85?700:0]);
 for(let n=1;n<=2;n++){
  const suffix='_member0'+n;
  h['precipitation'+suffix]=h.time.map(()=>1);
  h['wind_gusts_10m'+suffix]=h.time.map(()=>40);
 }
 const r=api.kfsProbaStormMembers(h,start,3,end);
 assert.equal(r.pct,100);
 assert.equal(r.members,2);
 h.cape_member01[60]=null;
 assert.equal(api.kfsProbaStormMembers(h,start,3,end),null);
});
test('daily command still accepts daily data without five-day coverage',()=>{
 const h=hourly('rain',[1,0]);
 assert.equal(api.kfsProbaMemberProbability(h,start,'pluie',10).pct,50);
});
test('Discord option explicitly identifies the five-day period',async()=>{
 const old=global.fetch;let command;
 global.fetch=async(_url,options)=>{
  if(options?.method==='POST'){command=JSON.parse(options.body);return new Response('{}');}
  return new Response('[]');
 };
 try{
  // Register uses the Worker application ID as an outer global.
  global.APPLICATION_ID='test-application';
  await api.kfsProbaRegister({DISCORD_BOT_TOKEN:'test-token'});
  const day=command.options.find(o=>o.name==='jour');
  assert.match(day.choices.find(c=>c.value===5).name,/J\+1 à J\+5/);
  assert.deepEqual(day.choices.filter(c=>c.value!==5).map(c=>c.value),[0,1,2,3]);
 }finally{global.fetch=old;delete global.APPLICATION_ID;}
});

test('five civil days retain the 23-hour spring and 25-hour autumn days',()=>{
 for(const [begin,finish,first,last,expected] of [
  ['2027-03-27T23:00:00Z','2027-04-01T22:00:00Z','2027-03-28','2027-04-01',119],
  ['2026-10-24T22:00:00Z','2026-10-29T23:00:00Z','2026-10-25','2026-10-29',121]]){
  const time=[];
  for(let t=Date.parse(begin);t<Date.parse(finish);t+=3600000)time.push(t/1000);
  const data=api.kfsProbaNormalizeHourly({time,rain_member01:time.map(()=>1),rain_member02:time.map(()=>1)});
  const result=api.kfsProbaMemberProbability(data,first,'pluie',120,last);
  assert.ok(result);
  assert.equal(result.amount,expected);
  assert.equal(result.pct,expected>=120?100:0);
 }
});

const stormTier=new Function(source+';return kfsProbaStormTier;')();
test('sensitive thunderstorm forecast detects weak to moderate environments without inflating severity',()=>{
 assert.equal(stormTier(80,0.12,15,null,null,null),1);
 assert.equal(stormTier(260,0.22,20,null,null,null),2);
 assert.equal(stormTier(580,0.6,28,null,null,null),3);
 assert.equal(stormTier(180,0,15,null,null,10),1);
 assert.equal(stormTier(800,0,50,null,null,null),0);
 assert.equal(stormTier(180,0,15,null,-220,10),0);
 assert.equal(stormTier(1700,2.6,65,null,null,13),4);
});
