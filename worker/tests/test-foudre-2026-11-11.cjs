const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let now = Date.parse('2026-11-11T00:53:28Z');
class Clock extends Date { static now() { return now; } }
const entries = new Map(), queries = [];
const cache = {
  async match(key) { return entries.get(key.url)?.clone(); },
  async put(key, value) { entries.set(key.url, value.clone()); }
};
const sec = () => now / 1000;
const summary = () => ({success:true,response:[{summary:{
  range:{fromTimestamp:sec()-1800,toTimestamp:sec(),maxTimestamp:sec()-529,count:8},
  pulse:{count:8,cg:1,ic:7,positive:1,negative:7},
  peakAmp:{positive:{max:8000},negative:{max:107000}}
}}]});
const pulse = (type, age) => ({loc:{lat:46.8,long:1.69},ob:{
  timestamp:sec()-age,pulse:{type,peakamp:type==='ic'?8000:-10000}}});
const context = vm.createContext({console,Date:Clock,URL,URLSearchParams,Request,Response,
  Blob,FormData,TextEncoder,TextDecoder,Uint8Array,Uint32Array,ArrayBuffer,Intl,
  caches:{default:cache},async fetch(url) {
    const u = new URL(url); queries.push(u);
    assert.equal(u.searchParams.get('filter'),'all');
    return new Response(JSON.stringify(u.pathname.includes('/summary/') ? summary() :
      {success:true,response:[pulse('ic',120),pulse('cg',299),pulse('cg',301)]}));
  }});
const source = fs.readFileSync(process.argv[2] || 'worker.js','utf8');
vm.runInContext(source.replace('export default {','const workerDefault = {'),context);
const run = code => vm.runInContext(code,context);
(async()=>{
  run(`globalThis.city={name:'Châteauroux',dept:'36',lat:46.8023,lon:1.6903};
    globalThis.env={XWEATHER_CLIENT_ID:'test-id',XWEATHER_CLIENT_SECRET:'test-secret'};`);
  const data = await run('foudreData(city,env)');
  assert.equal(data.pulses.length,2);
  assert.equal(data.pulses[0].type,'ic');
  assert.ok(Number.isFinite(data.pulses[0].time));
  assert.equal(data.diagnostic.écartéesTemps,1);
  assert.equal(queries[0].searchParams.get('from'),'-5minutes');
  now += 2000;
  const cached = await run('foudreData(city,env)');
  assert.equal(cached.cache,true);
  assert.equal(cached.pulses.length,1,'expired strike must leave cached map');
  const total = await run('foudreSummary(city,30,env)');
  assert.equal(total.data.count,8);
  assert.equal(total.data.ic,7);
  assert.equal(total.data.lastTimestamp,sec()-529);
  context.total = total;
  const lines = run('foudreSummaryLines(total,30)');
  assert.match(lines,/01:44:41/);
  assert.match(lines,/intranuageux \(IC\) : \*\*7\*\*/);
  let sent, images = 0;
  context.capture = (...args) => {sent=args;};
  context.image = () => {images++; return {png:new Uint8Array([1])};};
  await run(`radarVille=async()=>city;
    foudreData=async()=>({pulses:[],collecte:Date.now(),diagnostic:{}});
    foudreSummary=async()=>total;
    foudreImage=async()=>image();
    foudreMessage=async(...args)=>capture(...args);
  `);
  await run('completeFoudre({},"Châteauroux",env,30)');
  assert.equal(images,0,'no empty map when source returns no positions');
  assert.equal(sent[2],null);
  assert.match(sent[1],/Activité électrique détectée sur 30 minutes/);
  assert.match(sent[1],/01:44:41/);
  assert.ok(sent[1].length<1950);
  await run('foudreData=async()=>{throw Error("Quota Xweather atteint (429)");}');
  await run('completeFoudre({},"Châteauroux",env,30)');
  assert.equal(images,0);
  assert.match(sent[1],/Carte 5 min indisponible/);
  assert.match(sent[1],/8/,'summary survives map outage');
  await run(`foudreData=async()=>({pulses:[{type:'ic',amp:8000,lat:46.8,lon:1.69,time:Date.now()/1000}],collecte:Date.now()});`);
  await run('completeFoudre({},"Châteauroux",env,5)');
  assert.equal(images,1);
  assert.match(sent[1],/intranuageux \(IC\) : \*\*1\*\*/);
  assert.ok(sent[2]);
  console.log('PASS: all-type queries, strict 5-min window, cache expiry, 8-pulse summary, last detection, empty/error handling, IC map.');
})().catch(e=>{console.error(e);process.exitCode=1;});
