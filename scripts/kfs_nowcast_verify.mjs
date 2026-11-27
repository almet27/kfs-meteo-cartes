// KFS operational nowcast verification. Same correction kernel as the public site at deployment v1.
// Independent holdout stations; predictions stored before observations arrive.
import fs from "node:fs";
import assert from "node:assert/strict";
let kfsNowResidualCache=new Map();
const KFS_NOW_FIELDS={temp:["temperature_2m",6,5,2.5],wind:["wind_speed_10m",3,18,10],gust:["wind_gusts_10m",3,25,14],humidity:["relative_humidity_2m",6,25,15],dew:["dew_point_2m",6,5,2.5]};
const kfsNowDist=(a,b,c,d)=>111.195*Math.hypot(b-d,(a-c)*Math.cos((b+d)*Math.PI/360));
const kfsNowClamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const kfsNowRound=x=>Math.round(x*10)/10;
function kfsNowRH(t,d){return Number.isFinite(t)&&Number.isFinite(d)&&d<=t+0.5?kfsNowClamp(100*Math.exp(17.625*d/(243.04+d)-17.625*t/(243.04+t)),0,100):null;}

function kfs48Weight(model,t,now=Date.now()){
 const h=Math.max(0,(t-Math.floor(now/3600000)*3600000)/3600000);
 const w=h<=12?{arome:45,"icon-d2":25,ifs:22.5,gfs:7.5}:h<=24?{arome:40,"icon-d2":20,ifs:28,gfs:12}:{arome:29.75,"icon-d2":15,ifs:42.5,gfs:12.75};
 return w[model]||0;
}

function kfsHourlyField(doc,row,key){const fields=Array.isArray(doc.fields)?doc.fields:["temperature_2m","wind_speed_10m","wind_gusts_10m","precipitation","wind_direction_10m","weather_code"];const i=fields.indexOf(key),v=i>=0?row?.[i]:null;return Number.isFinite(v)?v:null;}

function kfsNowModelValue(d,lon,lat,t,field){
 const times=d._nowTimes||d.times.map(Date.parse);let best=-1,dist=40;for(let j=0;j<d.points.length;j++){const p=d.points[j],km=kfsNowDist(lon,lat,p[0],p[1]);if(km<dist){best=j;dist=km;}}if(best<0)return null;
 const a=d.rows[best];let i=times.findIndex(x=>x>=t);if(i<0)return null;const get=j=>kfsHourlyField(d,a?.[j],field);
 if(times[i]===t)return get(i);
 if(i>0&&times[i]-times[i-1]<=3600000){const v=get(i-1),w=get(i);if(Number.isFinite(v)&&Number.isFinite(w))return v+(w-v)*(t-times[i-1])/(times[i]-times[i-1]);}
 if(Math.abs(times[i]-t)<=12*60000)return get(i);return null;
}
function kfsNowBaseline(docs,lon,lat,t,field,now){let sum=0,w=0,n=0;for(const d of docs){const v=kfsNowModelValue(d,lon,lat,t,field),weight=kfs48Weight(d.model,t,now);if(Number.isFinite(v)&&weight>0){sum+=v*weight;w+=weight;n++;}}return n>=2&&w?sum/w:null;}
function kfsNowcastPrepare(docs,obs){
 if(!obs?.rows?.length||!Array.isArray(docs))return null;const now=Date.now(),usable=docs.filter(d=>Array.isArray(d.points)&&Array.isArray(d.times)&&Array.isArray(d.rows)&&now-Date.parse(d.fetched_utc)<=6*3600000&&Date.parse(d.fetched_utc)<=now+120000).map(d=>({...d,_nowTimes:d.times.map(Date.parse)}));if(usable.length<2)return null;
 const key=obs.at+"|"+usable.map(d=>d.model+":"+d.fetched_utc).sort().join("|");if(kfsNowResidualCache.has(key))return kfsNowResidualCache.get(key);
 const fields={};for(const [kind,[field,,limit]] of Object.entries(KFS_NOW_FIELDS)){
  const seen=new Map();for(const r of obs.rows.filter(r=>r.kind===kind).sort((a,b)=>(b.alt!==null)-(a.alt!==null)||b.t-a.t)){const k=Math.round(r.lon*100)+":"+Math.round(r.lat*100);if(seen.has(k))continue;if(r.alt!==null&&r.alt>700)continue;const base=kfsNowBaseline(usable,r.lon,r.lat,r.t,field,now);if(!Number.isFinite(base)||Math.abs(r.v-base)>limit*2)continue;seen.set(k,{...r,error:kfsNowClamp(r.v-base,-limit,limit)});}
  fields[kind]=[...seen.values()];
 }
 const out={fields,docs:usable,at:obs.at};kfsNowResidualCache.set(key,out);if(kfsNowResidualCache.size>6)kfsNowResidualCache.delete(kfsNowResidualCache.keys().next().value);return out;
}
function kfsNowcastAdjust(res,kind,lon,lat,t,raw,now=Date.now()){
 const config=KFS_NOW_FIELDS[kind];if(!res||!config||!Number.isFinite(raw)||!Number.isFinite(t)||now-res.at>20*60000)return null;
 const [field,horizon,,cap]=config,h=(t-now)/3600000;if(h<0||h>=horizon)return null;
 const near=(res.fields[kind]||[]).map(r=>({...r,km:kfsNowDist(lon,lat,r.lon,r.lat)})).filter(r=>r.km<=55&&now-r.t<=75*60000).sort((a,b)=>a.km-b.km).slice(0,8);
 if(near.length<2||near[0].km>32)return null;
 const sorted=near.map(r=>r.error).sort((a,b)=>a-b),median=sorted[Math.floor(sorted.length/2)],tol=kind==="temp"||kind==="dew"?2.5:kind==="humidity"?13:kind==="gust"?13:9;
 const ok=near.filter(r=>Math.abs(r.error-median)<=tol);if(ok.length<2)return null;
 let sw=0,se=0;for(const r of ok){const w=Math.exp(-r.km/24)*Math.exp(-(now-r.t)/3600000)*(r.source==="MF"?1:0.8)*(r.alt===null?0.8:1);sw+=w;se+=w*r.error;}
 if(sw<0.18)return null;const current=kfsNowBaseline(res.docs,lon,lat,Math.floor(now/3600000)*3600000,field,now),change=Number.isFinite(current)?Math.abs(raw-current):0;
 const fast=kind==="temp"||kind==="dew"?2.5:kind==="humidity"?15:kind==="gust"?20:12;
 const taper=Math.max(0,1-h/horizon)**1.35*(change>fast?.45:1);
 const delta=kfsNowClamp(se/sw,-cap,cap)*taper;
 let value=raw+delta;if(kind==="humidity")value=kfsNowClamp(value,0,100);if(kind==="wind"||kind==="gust")value=Math.max(0,value);
 return {value:kfsNowRound(value),delta:kfsNowRound(value-raw),n:ok.length};
}

const H=3600000,now=Date.now(),root="nowcast",statePath=root+"/pending.json",skillPath=root+"/skill.json";
const read=(p,fallback)=>{try{return JSON.parse(fs.readFileSync(p,"utf8"))}catch(e){if(e.code==="ENOENT")return fallback;throw e}};
const save=(p,x)=>{fs.writeFileSync(p+".tmp",JSON.stringify(x));fs.renameSync(p+".tmp",p)};
const siteKey=(lon,lat)=>Math.round(lon*1000)+":"+Math.round(lat*1000);
function holdout(key){let h=2166136261;for(const c of key)h=Math.imul(h^c.charCodeAt(0),16777619);return (h>>>0)%5===0;}
function observations(m){
 const rows=[],actuals=new Map(),sites=new Map();
 const add=(lon,lat,t,kind,v,alt=null)=>{if(![lon,lat,t,v].every(Number.isFinite)||t>now+120000||lon< -6||lon>11||lat<41||lat>52)return;const key=siteKey(lon,lat);if(Number.isFinite(alt)&&alt>700)return;
 const r={lon,lat,t,kind,v,source:"MF",alt,key};if(!holdout(key)&&now-t<=75*60000)rows.push(r);if(holdout(key)){sites.set(key,{lon,lat,key});const validTime=Math.round(t/H)*H;if(Math.abs(t-validTime)<=10*60000&&t<=now){const k=key+"|"+kind+"|"+validTime,prev=actuals.get(k);if(!prev||Math.abs(t-validTime)<Math.abs(prev.t-validTime))actuals.set(k,r);}}};
 const h=m.web_history;if(h?.schema===1){const times=(h.times||[]).map(Date.parse);for(const r of h.stations||[]){if(!Array.isArray(r[4]))continue;for(let i=0;i<times.length;i++){const a=r[4][i];if(!Array.isArray(a))continue;add(r[0],r[1],times[i],"temp",a[0]);add(r[0],r[1],times[i],"gust",a[1]);}}}
 if(m.web_nowcast_schema===1){for(const r of m.web_nowcast||[]){const [lon,lat,stamp,alt,temp,dew,rh,wind]=r,t=Date.parse(stamp);for(const [kind,v] of [["temp",temp],["dew",dew],["humidity",rh],["wind",wind]])add(lon,lat,t,kind,v,Number.isFinite(alt)?alt:null);}}
 const testSites=[...sites.values()];
 return {rows:rows.filter(r=>!testSites.some(s=>kfsNowDist(r.lon,r.lat,s.lon,s.lat)<1.5)),actuals,sites:testSites};
}
function test(){
 const t=Math.floor(Date.now()/H)*H;
 const docs=["arome","ifs"].map(model=>({model,fetched_utc:new Date().toISOString(),points:[[1,48]],times:[t,t+H,t+2*H,t+3*H].map(x=>new Date(x).toISOString()),rows:[[[10],[10],[10],[10]]]}));
 const rows=[{lon:1,lat:48,t,kind:"temp",v:7,source:"MF",alt:100},{lon:1.04,lat:48,t,kind:"temp",v:7,source:"MF",alt:100}];
 const res=kfsNowcastPrepare(docs,{rows,at:Date.now()});
 const v=kfsNowcastAdjust(res,"temp",1,48,t+H,10,t);assert(v&&v.value<10&&v.value>=7.5);assert.equal(kfsNowcastAdjust(res,"temp",1,48,t+6*H,10,t),null);assert.equal(kfsNowcastAdjust(res,"temp",8,48,t+H,10,t),null);assert.equal(kfsNowcastPrepare(docs.slice(0,1),{rows,at:t}),null);
 console.log("Nowcast synthetic tests passed");
}
if(process.argv.includes("--test")){test();process.exit(0)}
const manifest=read(process.argv[2],null);if(!manifest||!Number.isFinite(Date.parse(manifest.observation_utc))||now-Date.parse(manifest.observation_utc)>90*60000||Date.parse(manifest.observation_utc)>now+120000)throw Error("Fresh station manifest required");
const dir="forecast-maps/france/hourly-web/",docs=["arome","gfs","ifs","icon-d2"].map(k=>read(dir+k+".json",null)).filter(d=>d&&d.schema===1&&Date.parse(d.fetched_utc)<=now&&now-Date.parse(d.fetched_utc)<=6*H);
const obs=observations(manifest);fs.mkdirSync(root,{recursive:true});let state=read(statePath,{schema:1,lastIssue:null,pending:[]}),skill=read(skillPath,{schema:1,method:"KFS v1 · stations Météo-France exclues de la correction · MAE appariée · horizon horaire",months:{}});
if(state.schema!==1||skill.schema!==1)throw Error("Incompatible archive");
let scored=0,remaining=[];
for(const p of state.pending){const a=obs.actuals.get(p.key+"|"+p.kind+"|"+p.valid);if(a&&p.valid<=now&&a.t>=p.issued){const month=new Date(p.valid).toISOString().slice(0,7),b=skill.months[month]??={},f=b[p.kind]??={},v=f[p.lead]??={n:0,rawSum:0,correctedSum:0};v.n++;v.rawSum+=Math.abs(a.v-p.raw);v.correctedSum+=Math.abs(a.v-p.corrected);scored++;}else if(now-p.valid<30*H)remaining.push(p);}
state.pending=remaining;
const issue=Math.floor(now/H)*H;
if(state.lastIssue!==issue&&docs.length>=2){
 const res=kfsNowcastPrepare(docs,{rows:obs.rows,at:now});let added=0;
 if(res)for(const site of obs.sites)for(const [kind,[field,horizon]] of Object.entries(KFS_NOW_FIELDS))for(let lead=1;lead<=horizon;lead++){const valid=issue+lead*H;if(valid<=now)continue;const raw=kfsNowBaseline(res.docs,site.lon,site.lat,valid,field,now),r=kfsNowcastAdjust(res,kind,site.lon,site.lat,valid,raw,now);if(!r||!Number.isFinite(raw))continue;state.pending.push({key:site.key,kind,valid,issued:now,lead,raw,corrected:r.value});added++;}
 if(added)state.lastIssue=issue;console.log("Archived independent forecasts:",added);
}
skill.updated_utc=new Date(now).toISOString();skill.last_scored=scored;skill.pending=state.pending.length;save(statePath,state);save(skillPath,skill);console.log("Verified paired samples:",scored,"pending:",state.pending.length);
