const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const zlib=require('node:zlib'),crypto=require('node:crypto');
let now=Date.parse('2026-11-11T01:05:00Z');
class Clock extends Date{static now(){return now;}}
const entries=new Map();
const context=vm.createContext({console,Date:Clock,URL,URLSearchParams,Request,Response,
  Blob,FormData,TextEncoder,TextDecoder,Uint8Array,Uint32Array,ArrayBuffer,DataView,
  Intl,CompressionStream,DecompressionStream,AbortSignal,
  caches:{default:{async match(k){return entries.get(k.url)?.clone();},
    async put(k,r){entries.set(k.url,r.clone());}}}});
vm.runInContext(fs.readFileSync(process.env.KFS_WORKER_SOURCE||'worker.js','utf8').replace('export default {','const workerDefault={'),context);
const run=s=>vm.runInContext(s,context);
function syntheticPng(){
  const stride=600*4,raw=Buffer.alloc((stride+1)*600),rgba=Buffer.alloc(stride*600);
  for(let i=0;i<rgba.length;i++)rgba[i]=(i*17+(i>>7))%256;
  const paeth=(a,b,c)=>{const p=a+b-c,pa=Math.abs(p-a),pb=Math.abs(p-b),pc=Math.abs(p-c);
    return pa<=pb&&pa<=pc?a:pb<=pc?b:c;};
  for(let y=0;y<600;y++){
    const filter=y%5;raw[y*(stride+1)]=filter;
    for(let x=0;x<stride;x++){
      const i=y*stride+x,a=x>=4?rgba[i-4]:0,b=y?rgba[i-stride]:0,c=y&&x>=4?rgba[i-stride-4]:0;
      const prediction=filter===0?0:filter===1?a:filter===2?b:filter===3?Math.floor((a+b)/2):paeth(a,b,c);
      raw[y*(stride+1)+x+1]=(rgba[i]-prediction+256)%256;
    }
  }
  const chunk=(type,payload)=>Buffer.concat([Buffer.from([(payload.length>>>24)&255,(payload.length>>>16)&255,(payload.length>>>8)&255,payload.length&255]),Buffer.from(type),payload,Buffer.alloc(4)]);
  const h=Buffer.alloc(13);h.writeUInt32BE(600,0);h.writeUInt32BE(600,4);h[8]=8;h[9]=6;
  return {rgba,png:Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',h),chunk('IDAT',zlib.deflateSync(raw)),chunk('IEND',Buffer.alloc(0))])};
}
(async()=>{
  const fixture=syntheticPng();context.bytes=new Uint8Array(fixture.png);
  assert.deepEqual(Buffer.from(await run('kfsLiPng(bytes)')),fixture.rgba,'all five PNG row filters');
  context.bytes=new Uint8Array(fixture.png.slice(0,50));
  await assert.rejects(run('kfsLiPng(bytes)'),/tronqué|incomplet/);
  context.fetch=async()=>new Response('<WMS_Capabilities><Layer><Name>mtg_fd:li_afa</Name><Dimension name="time" default="2026-11-11T00:50:00Z"/></Layer></WMS_Capabilities>');
  assert.equal(await run('kfsLiLatest()'),Date.parse('2026-11-11T00:50:00Z'));
  now=Date.parse('2026-11-11T01:40:00Z');
  await assert.rejects(run('kfsLiLatest()'),/plus de 30 minutes/);
  now=Date.parse('2026-11-11T01:05:00Z');
  const frames=[];
  context.capture=t=>frames.push(t);
  context.oneFrame=()=>{const p=new Uint8Array(600*600*4);p[(308*600+300)*4+3]=255;return p;};
  run(`kfsLiLatest=async()=>Date.parse('2026-11-11T00:50:00Z');
    kfsLiFrame=async(city,time)=>{capture(time);return oneFrame();};
    globalThis.city={name:'Châteauroux',dept:'36',lat:46.8023,lon:1.6903};`);
  let result=await run('foudreSatellite(city,30)');
  assert.equal(frames.length,6);assert.equal(result.to-result.from,1800000);
  assert.equal(result.activePixels,1);assert.equal(result.ages[308*600+300],6);
  context.result=result;
  const text=run('foudreSatelliteLines(result)');
  assert.match(text,/retard ≈ 10 min/);assert.match(text,/sans localisation d’impacts au sol/);
  let calls=0;context.failSome=()=>++calls===2;
  run(`kfsLiFrame=async()=>{if(failSome())throw Error('missing frame');return oneFrame();}`);
  result=await run('foudreSatellite(city,30)');
  assert.equal(result.state,'partial');assert.equal(result.failed,1);assert.equal(result.received,5);
  run(`kfsLiFrame=async()=>{throw Error('outage');}`);
  await assert.rejects(run('foudreSatellite(city,30)'),/Aucune image/);
  // Optional real official PNG fixtures: compare the decoder with independent Pillow hashes.
  if(process.argv[2]){
    const m=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),data=new Map();
    for(const f of m.frames){
      context.bytes=new Uint8Array(fs.readFileSync(f.file));
      const rgba=await run('kfsLiPng(bytes)');
      assert.equal(crypto.createHash('sha256').update(rgba).digest('hex'),f.sha256_rgba);
      data.set(Date.parse(f.time),rgba);
    }
    context.actualFrame=t=>data.get(t);context.city=m.city;
    const latest=Math.max(...data.keys());context.latest=latest;
    run('kfsLiLatest=async()=>latest;kfsLiFrame=async(city,time)=>actualFrame(time);foudreFond=async()=>{};');
    const sat=await run('foudreSatellite(city,30)');context.sat=sat;
    const image=await run('foudreImage(city,[],sat)');
    fs.writeFileSync('foudre-eumetview-archive-test.png',image.png);
    assert.ok(sat.activePixels>0);console.log('REAL DATA:',sat.activePixels,'illuminated display pixels; 6 independently verified official PNGs.');
  }
  console.log('PASS: PNG row filters, corrupt PNG, source freshness, 30-min union, optical labelling, partial and failed source.');
})().catch(e=>{console.error(e);process.exitCode=1;});
