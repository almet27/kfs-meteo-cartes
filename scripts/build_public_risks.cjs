// Standalone public risks builder. Exact thresholds and renderer copied from KFS worker 2865f71a.
// Node.js 22; no Discord token or Worker bindings required.
const fs=require('node:fs/promises');
const path=require('node:path');
const nativeFetch=globalThis.fetch;
async function fetch(url,options){
 if(String(url).includes('/hourly-web/')){try{return new Response(await fs.readFile('forecast-maps/france/hourly-web/'+String(url).split('/').pop()),{headers:{'Content-Type':'application/json'}})}catch{return new Response(null,{status:404})}}
 if(String(url).includes('/shortterm-daily/latest.json')){
  try{return new Response(await fs.readFile('forecast-maps/france/shortterm-daily/latest.json'),{headers:{'Content-Type':'application/json'}})}catch{return new Response(null,{status:404})}
 }
 return nativeFetch(url,options);
}
const KFS_PROBA_MODELS = [
  ["ECMWF IFS ENS","ecmwf_ifs025_ensemble"],
  ["ECMWF AIFS ENS","ecmwf_aifs025_ensemble"],
  ["GEFS NOAA","ncep_gefs025"],
  ["AIGEFS NOAA","ncep_aigefs025"],
  ["ICON EU EPS","dwd_icon_eu_eps"],
  ["UKMO MOGREPS-G","ukmo_global_ensemble_20km"],
  ["GEM EPS","cmc_gem_geps"]
];
const KFS_PROBA_DEPTS={"11":["75","77","78","91","92","93","94","95"],"24":["18","28","36","37","41","45"],"27":["21","25","39","58","70","71","89","90"],"28":["14","27","50","61","76"],"32":["02","59","60","62","80"],"44":["08","10","51","52","54","55","57","67","68","88"],"52":["44","49","53","72","85"],"53":["22","29","35","56"],"75":["16","17","19","23","24","33","40","47","64","79","86","87"],"76":["09","11","12","30","31","32","34","46","48","65","66","81","82"],"84":["01","03","07","15","26","38","42","43","63","69","73","74"],"93":["04","05","06","13","83","84"],"94":["2A","2B"]};
const KFS_PROBA_BLEND_MODELS=[KFS_PROBA_MODELS[0],KFS_PROBA_MODELS[2]];
const KFS_ALERT_RULES={vent:[100,'Rafales (40/70/100/140 km/h)','💨','V'],pluie:[40,'Pluie 24h (1/15/50/>80 mm)','🌧️','P'],neige_chutes:[5,'Neige en plaine ≤500 m (0,1/3/5/10 cm en 24h)','❄️','N'],gel:[-10,'Tmin (0/−4/−10/−15 °C)','🥶','F'],orage:[4,'Potentiel convectif fort (indice)','⚡','O']};
const KFS_ALERT_LEVEL_NAMES=["Très faible","Faible","Modéré","Fort","Très fort"];
const KFS_ALERT_COLORS=[[66,163,103],[233,220,89],[242,151,45],[213,58,58],[142,53,168],[63,77,89]];
const KFS_ALERT_THRESHOLDS={pluie:[1,15,50,80],vent:[40,70,100,140],neige_chutes:[0.1,3,5,10],gel:[0,-4,-10,-15],chaleur:[28,32,35,40],orage:[1,3,4,5],verglas:[1,1,1,1]};
const KFS_ALERT_PLAIN_MAX_ELEVATION=500;
function kfsProbaDay(day){
 const today=new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Paris",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
 const [y,m,d]=today.split("-").map(Number);
 const target=new Date(Date.UTC(y,m-1,d+day,12));
 return target.toISOString().slice(0,10);
}
function kfsProbaRings(feature){
 const g=feature.geometry;
 if(g.type==="Polygon")return g.coordinates;
 if(g.type==="MultiPolygon")return g.coordinates.flatMap(p=>p);
 return [];
}
function kfsProbaBBox(features){
 let b=[Infinity,Infinity,-Infinity,-Infinity];
 for(const f of features)for(const ring of kfsProbaRings(f))for(const pt of ring){
  if(pt[0]<b[0])b[0]=pt[0];if(pt[1]<b[1])b[1]=pt[1];
  if(pt[0]>b[2])b[2]=pt[0];if(pt[1]>b[3])b[3]=pt[1];
 }
 return b;
}
function kfsProbaInRing(x,y,ring){
 let found=false;
 for(let i=0,j=ring.length-1;i<ring.length;j=i++){
  const a=ring[i],b=ring[j];
  if((a[1]>y)!==(b[1]>y) && x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])found=!found;
 }
 return found;
}
function kfsProbaInFeature(x,y,f){
 let found=false;
 for(const ring of kfsProbaRings(f))if(kfsProbaInRing(x,y,ring))found=!found;
 return found;
}
function kfsProbaValidMemberResult(v){
 return !!v&&Number.isFinite(v.pct)&&v.pct>=0&&v.pct<=100&&
  Number.isFinite(v.amount)&&Number.isInteger(v.members)&&v.members>=2;
}
function kfsAlertColor(v){return KFS_ALERT_COLORS[Number.isInteger(v)&&v>=0&&v<=4?v:5];}
function kfsAlertPlainOnly(type){return ['vent','gel','chaleur'].includes(type);}
function kfsAlertPlainElevation(elevation){return Number.isFinite(elevation)&&elevation<=KFS_ALERT_PLAIN_MAX_ELEVATION;}
function kfsAlertIntensity(type,value,elevation){
 if(!Number.isFinite(value))return null;
 if(kfsAlertPlainOnly(type)&&!kfsAlertPlainElevation(elevation))return null;
 if(type==='neige_chutes'&&!kfsAlertPlainElevation(elevation))return null;
 if(type==='neige_montagne'&&(!Number.isFinite(elevation)||elevation<=500))return null;
 if(type==='verglas')return value>=1?1:0;
 const thresholds=type==='neige_montagne'?[5,10,20,30]:KFS_ALERT_THRESHOLDS[type];
 if(!thresholds)return null;
 const amount=type==='neige_chutes'||type==='neige_montagne'?value*7/10:value;
 let level=0;for(let i=0;i<thresholds.length;i++){
 if(type==='gel'?amount<=thresholds[i]:type==='pluie'&&i===3?amount>thresholds[i]:amount>=thresholds[i])level=i+1;
 }return level;
}
function kfsAlertRecordWind(row,amount,lat,lon,elevation){
 if(![amount,lat,lon].every(Number.isFinite)||!kfsAlertPlainElevation(elevation))return;
 const points=row.windEvidence??(row.windEvidence=[]);
 const p=points.find(p=>Math.abs(p.lat-lat)<0.001&&Math.abs(p.lon-lon)<0.001);
 if(p){if(amount>p.amount)p.amount=amount;}else points.push({lat,lon,amount});
}
function kfsAlertWindDistance(a,b){
 const rad=Math.PI/180,dy=(a.lat-b.lat)*111.195,dx=(a.lon-b.lon)*111.195*Math.cos((a.lat+b.lat)/2*rad);
 return Math.hypot(dx,dy);
}
function kfsAlertWindExtent(row){
 const v=row.values.vent;if(!v||v.level!==4)return;
 const points=(row.windEvidence||[]).filter(p=>p.amount>=140);
 const supported=points.some((p,i)=>points.slice(i+1).some(q=>kfsAlertWindDistance(p,q)>=15));
 if(!supported)row.values.vent={...v,level:3,extremeUnconfirmed:true};
}
async function kfsAlertShortGusts(rows,date,day,used){
 if(day>2)return false;
 let doc;
 try{
 const r=await fetch('https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/forecast-maps/france/shortterm-daily/latest.json',{cf:{cacheEverything:true,cacheTtl:300},signal:AbortSignal.timeout(9000)});
 if(!r.ok)return false;doc=await r.json();
 }catch{return false;}
 const age=Date.now()-Date.parse(doc?.generated_utc);
 if(doc?.schema!==1||!Number.isFinite(age)||age<0||age>18*3600000)return false;
 let count=0;
 const bounds=rows.map(row=>({row,b:kfsProbaBBox([row.f])}));
 for(const [id,name] of [['arome','ARÔME'],['icon_eu','ICON EU']]){
 const d=Object.values(doc.models?.[id]?.days||{}).find(x=>x.date===date);
 if(!d||!['complete','partial'].includes(d.coverage)||!Array.isArray(d.gust_points)||d.hours<4)continue;
 for(const pt of d.gust_points){
 if(!Array.isArray(pt)||pt.length!==4||!pt.every(Number.isFinite)||pt[2]<0||pt[2]>300||!kfsAlertPlainElevation(pt[3]))continue;
 const [lat,lon,amount,elevation]=pt;
 const target=bounds.find(({row,b})=>lon>=b[0]&&lon<=b[2]&&lat>=b[1]&&lat<=b[3]&&kfsProbaInFeature(lon,lat,row.f));
 if(!target)continue;
 const row=target.row,level=kfsAlertIntensity('vent',amount,elevation),old=row.values.vent;if(level===null)continue;kfsAlertRecordWind(row,amount,lat,lon,elevation);
 // A partial day can raise a level but must not create a low-risk value for the whole day.
 if(d.coverage==='partial'&&!old&&level<2)continue;
 if(!old||level>old.level||(level===old.level&&amount>old.amount)){
 row.values.vent={level,amount,models:[name],lat,lon,type:'vent',elevation,deterministic:true,partial:d.coverage!=='complete'};
 used.add(name);count++;
 }
 }}
 return count>0;
}
async function kfsAlertFreezingHourly(rows,date,day,used){
 const models=day<=1?[['ARÔME','arome'],['ECMWF IFS','ifs'],['GFS','gfs']]:[['ECMWF IFS','ifs'],['GFS','gfs']];
 const settled=await Promise.allSettled(models.map(async ([name,id])=>{
  const r=await fetch('https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/forecast-maps/france/hourly-web/'+id+'.json',{signal:AbortSignal.timeout(9000),cf:{cacheEverything:true,cacheTtl:300}});
  if(!r.ok)return null;const d=await r.json(),age=Date.now()-Date.parse(d.fetched_utc);
  if(d.schema!==1||d.model!==id||!Number.isFinite(age)||age<0||age>18*3600000||!Array.isArray(d.times)||!Array.isArray(d.points)||!Array.isArray(d.rows)||d.points.length!==d.rows.length)return null;
  const ci=Array.isArray(d.fields)?d.fields.indexOf('weather_code'):5;if(ci<0)return null;
  const fmt=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Paris',year:'numeric',month:'2-digit',day:'2-digit'});
  const ids=d.times.flatMap((t,i)=>Number.isFinite(Date.parse(t))&&fmt.format(new Date(t))===date?[i]:[]);
  if(!ids.length)return null;return {d,ids,ci,name};
 }));
 const bounds=rows.map(row=>({row,b:kfsProbaBBox([row.f])}));
 for(const result of settled){if(result.status!=='fulfilled'||!result.value)continue;const {d,ids,ci,name}=result.value;
  for(let j=0;j<d.points.length;j++){const p=d.points[j],r=d.rows[j];if(!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite)||!Array.isArray(r))continue;
   const hits=ids.filter(i=>[48,56,57,66,67].includes(r[i]?.[ci]));if(!hits.length)continue;
   const [lon,lat]=p,target=bounds.find(({row,b})=>lon>=b[0]&&lon<=b[2]&&lat>=b[1]&&lat<=b[3]&&kfsProbaInFeature(lon,lat,row.f));if(!target)continue;
   const row=target.row,old=row.values.verglas;
   if(!old||old.level<1||(old.deterministic&&hits.length>old.amount)){row.values.verglas={type:'verglas',level:1,amount:hits.length,models:[name],lat,lon,deterministic:true,partial:ids.length<24};used.add(name);}
  }
 }
}

async function kfsAlertData(day,zone,types,prepared=null){
 const date=kfsProbaDay(day),wanted=new Set(zone==='FR'?Object.values(KFS_PROBA_DEPTS).flat():KFS_PROBA_DEPTS[zone]||[]);
 if(!wanted.size)throw Error('Zone invalide');
 
let geo=prepared?.geo,data=prepared?.ensemble||{};
 if(!geo){
 const [g,r]=await Promise.allSettled([fetch('https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson',{cf:{cacheTtl:86400,cacheEverything:true},signal:AbortSignal.timeout(12000)}),fetch('https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/proba/ensemble-probabilities.json?day='+date,{cf:{cacheTtl:300,cacheEverything:true},signal:AbortSignal.timeout(15000)})]);
 if(g.status!=='fulfilled'||!g.value.ok)throw Error('Contours départementaux indisponibles');
 geo=await g.value.json();if(r.status==='fulfilled'&&r.value.ok){try{const x=await r.value.json();if(x.schema===2&&x.provider==='Open-Meteo ECMWF ENS + GEFS members'&&x.timezone==='Europe/Paris')data=x;}catch{}}
 }
 const features=geo.features.filter(f=>wanted.has(String(f.properties.code)));
 if(features.length!==wanted.size)throw Error('Contours départementaux incomplets');
 const models=KFS_PROBA_BLEND_MODELS.flatMap(([name,id])=>{const m=data.models?.[id],age=Date.now()-Date.parse(m?.generated_at_utc),p=Object.values(m?.periods||{}).find(period=>period?.start_day===date&&period?.end_day===date);return Number.isFinite(age)&&age>=0&&age<=28*3600000&&p?.start_day===date&&p?.end_day===date?[{name,id,m,p}]:[];});
 
 const rows=features.map(f=>({f,code:String(f.properties.code),name:f.properties.nom||f.properties.name||String(f.properties.code),values:{},best:null}));
 const used=new Set(),times=new Set();
 for(const z of zone==='FR'?Object.keys(KFS_PROBA_DEPTS):[zone]){
 const pts=data.zone_points?.[z];if(!Array.isArray(pts))continue;const local=rows.filter(o=>KFS_PROBA_DEPTS[z].includes(o.code));
 for(let i=0;i<pts.length;i++){const pt=pts[i];if(!Array.isArray(pt)||pt.length!==2||!pt.every(Number.isFinite))continue;
 const [lat,lon]=pt,row=local.find(x=>kfsProbaInFeature(lon,lat,x.f));if(!row)continue;
 if(types.includes('verglas')){
 const values=models.flatMap(m=>{const a=m.p.zones?.[z]?.verglas?.['1'],v=a?.[i];return Array.isArray(a)&&a.length===pts.length&&kfsProbaValidMemberResult(v)&&v.includes_rime===true&&v.members>=5?[{m,v}]:[]});
 if(values.length){const probability=values.reduce((a,x)=>a+x.v.pct,0)/values.length,amount=values.reduce((a,x)=>a+x.v.amount,0)/values.length,level=probability<10?0:probability<30?1:probability<50?2:probability<75?3:4,old=row.values.verglas;
 if(!old||probability>old.probability)row.values.verglas={type:'verglas',level,amount,probability,models:values.map(x=>x.m.name),lat,lon};
 for(const x of values){used.add(x.m.name);times.add(x.m.m.generated_at_utc);}
 }
 }
 for(const type of types.filter(t=>KFS_ALERT_RULES[t]||t==='chaleur'||t==='neige_montagne')){const key=type==='chaleur'?'gel':type==='neige_montagne'?'neige_chutes':type,base=type==='chaleur'?0:KFS_ALERT_RULES[key][0],snow=type==='neige_chutes'||type==='neige_montagne';const v=models.flatMap(m=>{const all=m.p.zones?.[z]?.[key]?.[String(base)],x=all?.[i],amount=type==='chaleur'?x?.tmax:x?.amount;const elevation=Number.isFinite(x?.elevation)?x.elevation:m.p.zones?.[z]?.neige_chutes?.['5']?.[i]?.elevation;return Array.isArray(all)&&all.length===pts.length&&kfsProbaValidMemberResult(x)&&Number.isFinite(amount)&&(!snow||Number.isFinite(elevation)&&(type==='neige_chutes'?elevation<=500:elevation>500))&&(!kfsAlertPlainOnly(type)||kfsAlertPlainElevation(elevation))?[{m,amount,elevation}]:[];});
 if(!v.length)continue;const amount=v.reduce((a,x)=>a+x.amount,0)/v.length,elevation=snow||kfsAlertPlainOnly(type)?Math.max(...v.map(x=>x.elevation)):null,level=kfsAlertIntensity(type,amount,elevation);if(level===null)continue;for(const x of v){used.add(x.m.name);times.add(x.m.m.generated_at_utc);}
 if(type==='vent')kfsAlertRecordWind(row,amount,lat,lon,elevation);
 if(!row.values[type]||level>row.values[type].level||(type==='vent'&&level===row.values[type].level&&amount>row.values[type].amount))row.values[type]={level,amount,models:v.map(x=>x.m.name),lat,lon,type,elevation};}
 }}
 const [local,regional]=prepared&&!prepared.manual?[[],[]]:await Promise.all([(types.length===1&&types[0]==='vent'&&day<=2?Promise.resolve([]):kfsAlertLocal(rows,date,day,types).catch(()=>[])),zone!=='FR'?kfsAlertRegionalEnsemble(rows,date,day,types).catch(()=>[]):Promise.resolve([])]);for(const m of regional)used.add(m);
 if(types.includes('vent')&&day<=2){const fresh=await kfsAlertShortGusts(rows,date,day,used).catch(()=>false);const corsica=rows.filter(r=>['2A','2B'].includes(r.code));const mainland=rows.filter(r=>!['2A','2B'].includes(r.code));if(corsica.length&&!prepared?.publicOnly)await kfsAlertWindLive(corsica,date,day,used,'94').catch(e=>console.warn('KFS_ALERT_WIND_CORSE',String(e).slice(0,200)));if(!fresh&&(!prepared||prepared.manual)&&mainland.length)await kfsAlertWindLive(mainland,date,day,used,zone).catch(e=>console.warn('KFS_ALERT_WIND_LIVE',String(e).slice(0,200)));}
 if(types.includes('verglas'))await kfsAlertFreezingHourly(rows,date,day,used).catch(()=>{});
 for(const row of rows){if(!prepared||prepared.manual)for(const [t,ms] of Object.entries(row.local||{})){if(row.values[t]&&!(t==='vent'&&day<=2))continue;const ranked=day<=1?['ARÔME','ICON EU']:day===2?['ICON EU','ECMWF IFS']:['ECMWF IFS','GFS'];const model=t==='vent'&&day<=2?ranked.filter(m=>ms[m]).sort((a,b)=>ms[b].value-ms[a].value)[0]:ranked.find(m=>ms[m]);if(model){const v=ms[model];const old=row.values[t];if(!old||v.level>old.level||(t==='vent'&&v.level===old.level&&v.value>old.amount)){row.values[t]={...v,amount:v.value,models:[model],type:t,deterministic:true};used.add(model);}}}kfsAlertWindExtent(row);row.best=Object.values(row.values).sort((a,b)=>b.level-a.level||["orage","vent","neige_chutes","pluie","verglas","gel","chaleur"].indexOf(a.type)-["orage","vent","neige_chutes","pluie","verglas","gel","chaleur"].indexOf(b.type))[0]||null;}
 return {rows,features,date,used:[...used],times:[...times],local};
}
function renderRisk(d,day,date){
 const esc=v=>String(v??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");
 const W=900,H=760,scale=Math.min(836/(15.8*Math.cos(46.4*Math.PI/180)),624/10.5),cos=Math.cos(46.4*Math.PI/180);
 const X=x=>450+(x-2.1)*cos*scale,Y=y=>340-(y-46.4)*scale;
 const symbols={vent:"💨",pluie:"🌧",neige_chutes:"❄",gel:"🌡",orage:"⚡",chaleur:"☀",verglas:"◇"};
 let svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 760" width="900" height="760" role="img"><rect width="900" height="760" fill="#091426"/><g stroke="#d7e5f0" stroke-width=".8" fill-rule="evenodd">';
 for(const row of d.rows){
  const path=kfsProbaRings(row.f).map(r=>r.map((p,i)=>(i?"L":"M")+X(p[0]).toFixed(1)+" "+Y(p[1]).toFixed(1)).join(" ")+"Z").join(" ");
  const v=row.best,title=row.name+" · "+(v?KFS_ALERT_LEVEL_NAMES[v.level]+" · "+v.type:"Données indisponibles");
  svg+='<path d="'+path+'" fill="rgb('+kfsAlertColor(v?.level).join(",") +')"><title>'+esc(title)+'</title></path>';
 }
 svg+='</g><g data-kfs-layer="risk-icons" pointer-events="none" text-anchor="middle" dominant-baseline="middle" font-family="system-ui,sans-serif" font-size="28">';
 const secondary=[];
 for(const row of d.rows){
  const v=row.best;if(!v||v.level<2||!Number.isFinite(v.lat)||!Number.isFinite(v.lon))continue;
  const x=X(v.lon).toFixed(1),y=Y(v.lat).toFixed(1);
  let icon="";
  if(v.type==="gel"){
   icon='<g transform="rotate(32 0 0)"><path d="M-3.4 2V-10a3.4 3.4 0 0 1 6.8 0V2a5.7 5.7 0 1 1 -6.8 0Z" fill="#f4f8ff" stroke="#34516c" stroke-width="1.4"/><path d="M0 -4V6" stroke="#2499ed" stroke-width="3.3" stroke-linecap="round"/><circle cx="0" cy="6.5" r="3.9" fill="#2499ed"/><path d="M1.4 -8H3M1.4 -4H3M1.4 0H3" stroke="#55728b" stroke-width=".9" stroke-linecap="round"/><path d="M-1.7 -9V-5" stroke="#fff" stroke-width="1" stroke-linecap="round"/></g>';
  }else if(v.type==="chaleur"){
   const color=v.type==="gel"?"#49baff":"#ff4b47";
   icon='<path d="M-3 -4V-9a3 3 0 0 1 6 0v5a6 6 0 1 1 -6 0Z" fill="#f3f8ff" stroke="#102030" stroke-width="1.4"/><path d="M0 -8V2" stroke="'+color+'" stroke-width="3.5" stroke-linecap="round"/><circle cx="0" cy="3" r="4" fill="'+color+'"/><path d="M4 -7h2M4 -3h2" stroke="#102030" stroke-width="1" stroke-linecap="round"/>';
  }else if(v.type==="pluie"){
   icon='<path d="M0 -11C-2.5 -7 -7 -2 -7 3A7 7 0 0 0 7 3C7 -2 2.5 -7 0 -11Z" fill="#39b9f5" stroke="#154c78" stroke-width="1.3"/><path d="M-3.8 1.5Q-5 5 -1.5 7" fill="none" stroke="#b9efff" stroke-width="1.5" stroke-linecap="round"/>';
  }else if(v.type==="verglas"){
   icon='<path d="M0 -12.5L12 9.5Q12.5 11 10.8 11H-10.8Q-12.5 11 -12 9.5Z" fill="#fff" stroke="#d52b2b" stroke-width="2.5" stroke-linejoin="round"/><g fill="#17212a" transform="rotate(-12 0 0)"><path d="M-4.5 -1L-3 -4.1H2.5L4.4 -1L5.1 .2V3.3H-5.1V.2Z"/><path d="M-2.5 -3.2H1.9L3 -.7H-3.5Z" fill="#fff"/><rect x="-4.6" y="2.5" width="2" height="1.8" rx=".4"/><rect x="2.6" y="2.5" width="2" height="1.8" rx=".4"/></g><path d="M-5 5C-2.5 3.5 -3.5 7.7 -6 8.1M2 5C4.8 3.5 4.1 7.7 1.5 8.2" fill="none" stroke="#17212a" stroke-width="1.15" stroke-linecap="round"/>';
  }else if(v.type==="vent"){
   icon='<path d="M-9 10V-9" stroke="#102030" stroke-width="4" stroke-linecap="round"/><path d="M-9 10V-9" stroke="#edf5fc" stroke-width="1.8" stroke-linecap="round"/><path d="M-8 -9L12 -5 12 0 -8 3Z" fill="#f6f8ff" stroke="#102030" stroke-width="1.3" stroke-linejoin="round"/><path d="M-8 -9L-3 -8 -3 2 -8 3Z M2 -7L7 -6 7 1 2 1.5Z" fill="#ef5348"/><path d="M-8 -9L12 -5 12 0 -8 3Z" fill="none" stroke="#102030" stroke-width="1.3" stroke-linejoin="round"/>';
  }else{
   icon='<text fill="#fff" stroke="#091426" stroke-width="2" paint-order="stroke">'+esc(symbols[v.type]||"!")+'</text>';
  }
  const iconScale=({gel:1.13,chaleur:1.25,pluie:1.40,verglas:1.12,vent:1.25})[v.type]||1;
  svg+='<g transform="translate('+x+' '+y+') scale('+iconScale+')"><title>'+esc(row.name+" · "+v.type)+'</title>'+icon+'</g>';
  const ice=row.values.verglas;if(v.type!=='verglas'&&ice?.level>=2)secondary.push('<g transform="translate('+(Number(x)+29)+' '+(Number(y)+5)+') scale(1.12)"><title>'+esc(row.name+' · verglas')+'</title><path d="M0 -12.5L12 9.5Q12.5 11 10.8 11H-10.8Q-12.5 11 -12 9.5Z" fill="#fff" stroke="#d52b2b" stroke-width="2.5" stroke-linejoin="round"/><g fill="#17212a" transform="rotate(-12 0 0)"><path d="M-4.5 -1L-3 -4.1H2.5L4.4 -1L5.1 .2V3.3H-5.1V.2Z"/><path d="M-2.5 -3.2H1.9L3 -.7H-3.5Z" fill="#fff"/><rect x="-4.6" y="2.5" width="2" height="1.8" rx=".4"/><rect x="2.6" y="2.5" width="2" height="1.8" rx=".4"/></g><path d="M-5 5C-2.5 3.5 -3.5 7.7 -6 8.1M2 5C4.8 3.5 4.1 7.7 1.5 8.2" fill="none" stroke="#17212a" stroke-width="1.15" stroke-linecap="round"/></g>');
 }
 svg+=secondary.join('');
 svg+='</g><text x="450" y="22" fill="#fff" font-size="18" font-weight="bold" text-anchor="middle" font-family="system-ui,sans-serif">KFS MÉTÉO · RISQUES J+'+day+' · '+esc(date)+'</text>';
 const names=["Très faible","Faible","Modéré","Fort","Très fort","Indisponible"];
 for(let i=0;i<6;i++){const x=36+i*140;svg+='<rect x="'+x+'" y="684" width="18" height="18" rx="3" fill="rgb('+KFS_ALERT_COLORS[i].join(",")+')"/><text x="'+(x+24)+'" y="698" fill="#e3eef5" font-size="13" font-family="system-ui,sans-serif">'+names[i]+'</text>'}
 svg+='<text x="450" y="730" fill="#b3c9da" font-size="12" text-anchor="middle" font-family="system-ui,sans-serif">Sources : '+esc(d.used.join(" · "))+' · risques modélisés, non officiels</text></svg>';

return svg;
}
(async()=>{
 const geoRes=await fetch('https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson',{signal:AbortSignal.timeout(20000)});
 if(!geoRes.ok)throw Error('Contours HTTP '+geoRes.status);
 const geo=await geoRes.json(),ensemble=JSON.parse(await fs.readFile('proba/ensemble-probabilities.json','utf8'));
 if(ensemble.schema!==2||ensemble.provider!=='Open-Meteo ECMWF ENS + GEFS members'||ensemble.timezone!=='Europe/Paris')throw Error('Ensemble incompatible');
 const today=kfsProbaDay(0),out='proba/public-risks';
 await fs.mkdir(out,{recursive:true});
 const manifest={schema:1,risk_schema:10,today,generated_utc:new Date().toISOString(),days:{}};
 for(let day=0;day<=5;day++){
  const date=kfsProbaDay(day);
  const d=await kfsAlertData(day,'FR',[...Object.keys(KFS_ALERT_RULES),'chaleur','verglas'],{geo,ensemble,publicOnly:true});
  const count=d.rows.filter(r=>r.best).length;if(!d.used.length||!count){console.warn('No valid risks',day);continue}
  const svg=renderRisk(d,day,date),file=today+'-j'+day+'.svg';
  if(!svg.startsWith('<svg')||!svg.endsWith('</svg>'))throw Error('Invalid SVG');
  await fs.writeFile(path.join(out,file),svg);
  manifest.days[day]={date,file,models:d.used,coverage:count,ensemble_times:d.times};
  console.log(day,date,count,d.used.join(', '),svg.length);
 }
 if(!Object.keys(manifest.days).length)throw Error('No valid risk maps');
 await fs.writeFile(path.join(out,'manifest.json'),JSON.stringify(manifest));
 for(const file of await fs.readdir(out))if(/^\d{4}-\d{2}-\d{2}-j[0-5]\.svg$/.test(file)&&!file.startsWith(today+'-'))await fs.unlink(path.join(out,file));
})().catch(e=>{console.error(e);process.exitCode=1});
