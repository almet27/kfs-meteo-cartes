const vm=require('node:vm');const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const build=fs.readFileSync(path.join(root,'scripts/build_proba_5days.cjs'),'utf8');
const moduleSource=fs.readFileSync(path.join(root,'cloudflare/kfs-proba-module.js'),'utf8');
const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Paris'}).format(new Date());
const first=Date.parse(today+'T00:00:00Z')-3600000;
const time=Array.from({length:168},(_,i)=>(first+i*3600000)/1000);
const hourly={time};
for(const [variable,value] of Object.entries({rain:1,snow_depth:.01,snowfall:0,temperature_2m:1,wind_gusts_10m:60,cape:500,precipitation:1,dew_point_2m:10}))
 for(let n=1;n<=6;n++)hourly[variable+'_member0'+n]=time.map(()=>value);
const disk=new Map();let calls=0,waits=0;
const mockFs={
 readFileSync(file){if(file.endsWith('kfs-proba-module.js'))return moduleSource;if(file.endsWith('points-ecmwf.json'))return JSON.stringify({zones:{FR:[[49,1],[48,2]]}});return disk.get(file);},
 existsSync(file){return disk.has(file);},writeFileSync(file,data){disk.set(file,data);},
 renameSync(a,b){disk.set(b,disk.get(a));disk.delete(a);},statSync(file){return {size:disk.get(file).length};}
};
async function run(){
 const context={require:name=>name==='node:fs'?mockFs:require(name),__dirname:path.join(root,'scripts'),
  Intl,Date,Response,URLSearchParams,AbortSignal,process:{exitCode:0},console:{log(){},error:console.error},
  setTimeout:callback=>{waits++;callback();},fetch:async()=>{calls++;if(calls===1)throw new TypeError('Test connection timeout');return new Response(JSON.stringify([{hourly},{hourly}]));}};
 await vm.runInNewContext(build,context);
 assert.equal(context.process.exitCode,0);
}
require('node:test').test('generation retries connection failures and resumes completed batches',async()=>{
 await run();assert.equal(calls,2);assert.equal(waits,1);
 const checkpoint=[...disk.entries()].find(([file])=>file.endsWith('five-day-checkpoint.json'));
 assert.equal(JSON.parse(checkpoint[1]).next,2);
 await run();assert.equal(calls,2,'Resume must not download already completed points');
 const output=[...disk.entries()].find(([file])=>file.endsWith('five-day-probabilities.json'));
 assert.equal(JSON.parse(output[1]).zones.FR.pluie['20'][0].members,6);
 console.log('Verified: transient retry, checkpoint save, full resume, and publication without repeated downloads.');
});
