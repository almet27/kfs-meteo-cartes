const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const cache=new Map();let upstream=0;
const context=vm.createContext({Response,Request,URL,URLSearchParams,TextEncoder,Uint8Array,
  crypto:webcrypto,console,caches:{default:{async match(k){return cache.get(k.url)?.clone();},
    async put(k,r){cache.set(k.url,r.clone());}}},async foudreData(){upstream++;const t=Date.now()/1000;
      return {collecte:Date.now(),etat:'resultats',limite:false,pulses:[
        {lat:48,lon:1,type:'cg',amp:-65000,time:t-10},
        {lat:48,lon:1,type:'ic',amp:null,time:t-10},
        {lat:45,lon:1,type:'cg',amp:80000,time:t-10},
        {lat:48,lon:1,type:'cg',amp:10000,time:t-400}]};}});
vm.runInContext(fs.readFileSync(__dirname+'/mobile-api.js','utf8'),context);
const env={FOUDRE_MOBILE_TOKEN:'test-token-abcdefghijklmnopqrstuvwxyz-1234567890'};
const request=(data,token=env.FOUDRE_MOBILE_TOKEN)=>new Request('https://worker.example/mobile/v1/lightning',{
  method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(data)});
const invoke=async r=>{context.req=r;context.env=env;return vm.runInContext('kfsMobileAPI(req,env)',context);};
(async()=>{
  const input={latitude:48,longitude:1,radiusKm:50,positionTimestamp:Date.now()/1000};
  assert.equal((await invoke(request(input,'wrong'))).status,401);assert.equal(upstream,0);
  assert.equal((await invoke(request({...input,latitude:0}))).status,400);
  assert.equal((await invoke(request({...input,positionTimestamp:0}))).status,400);
  const response=await invoke(request(input)),feed=await response.json();
  assert.equal(response.status,200);assert.equal(feed.strikes.length,2);
  assert.equal(feed.strikes[0].peakCurrentKA,-65);assert.equal(feed.strikes[1].peakCurrentKA,null);
  assert.equal(feed.strikes[0].distanceKm,0);assert.equal(upstream,1);
  assert.equal((await invoke(request(input))).status,429);assert.equal(upstream,1);
  assert.ok(!JSON.stringify(feed).includes(env.FOUDRE_MOBILE_TOKEN));
  console.log('PASS: authentication, GPS freshness, geographic scope, signed kA, missing current, radius, source age, throttle, no credentials in response');
})().catch(e=>{console.error(e);process.exitCode=1;});
