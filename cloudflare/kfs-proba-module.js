
// KFS /proba — prévisions multi-ensembles, J+0 à J+3, France / régions.
// Pas de taux de confiance inventé : décompte des membres, puis moyenne
// à poids égaux entre familles d'ensembles effectivement disponibles.
// Source données : Open-Meteo Ensemble API ; contours : IGN / INSEE (geojson).
const KFS_PROBA_MODELS = [
  ["ECMWF IFS ENS","ecmwf_ifs025_ensemble"],
  ["ECMWF AIFS ENS","ecmwf_aifs025_ensemble"],
  ["GEFS NOAA","ncep_gefs025"],
  ["AIGEFS NOAA","ncep_aigefs025"],
  ["ICON EU EPS","icon_eu_eps"],
  ["UKMO MOGREPS-G","ukmo_global_ensemble_20km"],
  ["GEM EPS","cmc_gem_geps"]
];
const KFS_PROBA_REGIONS = [
 ["11","Île-de-France"],["24","Centre-Val de Loire"],
 ["27","Bourgogne-Franche-Comté"],["28","Normandie"],
 ["32","Hauts-de-France"],["44","Grand Est"],
 ["52","Pays de la Loire"],["53","Bretagne"],
 ["75","Nouvelle-Aquitaine"],["76","Occitanie"],
 ["84","Auvergne-Rhône-Alpes"],["93","Provence-Alpes-Côte d'Azur"],
 ["94","Corse"]
];
const KFS_PROBA_RULES = {
 neige:{unit:"cm",defaults:1,allowed:[1,3,5,10],variable:"snow_depth",title:"Neige présente au sol"},
 pluie:{unit:"mm / 24 h",defaults:10,allowed:[1,5,10,20,40],variable:"rain",title:"Cumul de pluie"},
 vent:{unit:"km/h",defaults:80,allowed:[60,80,100,120],variable:"wind_gusts_10m",title:"Rafales maximales"}
};
let KFS_PROBA_LAST_REGISTER=0;
async function kfsProbaRegister(env){
 if(!env.DISCORD_BOT_TOKEN)throw Error("Jeton Discord absent");
 const cmd={name:"proba",type:1,description:"Probabilités météo jusqu'à J+3 · France et régions",options:[
  {name:"phenomene",type:3,description:"Neige au sol, pluie ou rafales",required:true,
   choices:[{name:"🌨️ Neige au sol",value:"neige"},{name:"🌧️ Pluie",value:"pluie"},{name:"💨 Rafales",value:"vent"}]},
  {name:"zone",type:3,description:"France entière ou région",required:false,
   choices:[{name:"France métropolitaine",value:"FR"},...KFS_PROBA_REGIONS.map(([code,name])=>({name,value:code}))]},
  {name:"jour",type:4,description:"De J+0 à J+3",required:false,
   choices:[0,1,2,3].map(i=>({name:"J+"+i,value:i}))},
  {name:"seuil",type:4,description:"Neige : 1/3/5/10 cm ; pluie : 1/5/10/20/40 mm ; vent : 60/80/100/120 km/h",required:false,min_value:1,max_value:120}
 ]};
 const r=await fetch("https://discord.com/api/v10/applications/"+APPLICATION_ID+"/commands",{
  method:"POST",headers:{Authorization:"Bot "+env.DISCORD_BOT_TOKEN,"content-type":"application/json"},
  body:JSON.stringify(cmd)
 });
 if(!r.ok)throw Error("Discord /proba HTTP "+r.status+": "+(await r.text()).slice(0,240));
 KFS_PROBA_LAST_REGISTER=Date.now();
 return true;
}
async function kfsProbaEdit(interaction,payload,bytes){
 const endpoint="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+"/"+interaction.token+"/messages/@original";
 let r;
 if(bytes){
  const f=new FormData();
  f.append("payload_json",JSON.stringify({...payload,attachments:[{id:0,filename:"kfs-proba.png",description:"Carte KFS des probabilités issues d'ensembles"}]}));
  f.append("files[0]",new Blob([bytes],{type:"image/png"}),"kfs-proba.png");
  r=await fetch(endpoint,{method:"PATCH",body:f});
 }else{
  r=await fetch(endpoint,{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
 }
 if(!r.ok)throw Error("Réponse Discord HTTP "+r.status+": "+(await r.text()).slice(0,120));
}
// Retourne les polygones (y compris les îles et les éventuels trous) en WGS84.
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
function kfsProbaSamples(features,regional){
 const samples=[];
 for(const f of features){
  const [left,bottom,right,top]=kfsProbaBBox([f]);
  const candidates=regional?[
   [.15,.15],[.35,.15],[.55,.15],[.8,.15],
   [.15,.35],[.35,.35],[.55,.35],[.8,.35],
   [.15,.55],[.35,.55],[.55,.55],[.8,.55],
   [.15,.8],[.35,.8],[.55,.8],[.8,.8],
   [.5,.5],[.5,.7],[.7,.5],[.3,.7]
  ]:[[.32,.45],[.68,.55],[.5,.72],[.5,.27],[.5,.5]];
  let picked=0;
  for(const [fx,fy] of candidates){
   const lon=left+(right-left)*fx,lat=bottom+(top-bottom)*fy;
   if(kfsProbaInFeature(lon,lat,f)){
    samples.push({lon:+lon.toFixed(3),lat:+lat.toFixed(3),value:null,models:[]});
    picked++;
    if(!regional&&picked>=3)break;
   }
  }
  if(!picked){
   const ring=kfsProbaRings(f).sort((a,b)=>b.length-a.length)[0]||[];
   if(ring.length){
    const a=ring[Math.floor(ring.length/2)];
    samples.push({lon:a[0],lat:a[1],value:null,models:[]});
   }
  }
 }
 return samples;
}
async function kfsProbaFeatures(){
 const uri="https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/regions-version-simplifiee.geojson";
 const r=await fetch(uri,{cf:{cacheTtl:86400,cacheEverything:true},signal:AbortSignal.timeout(10000)});
 if(!r.ok)throw Error("Contours France non accessibles : "+r.status);
 const j=await r.json();
 const codes=new Set(KFS_PROBA_REGIONS.map(x=>x[0]));
 const feats=(j.features||[]).filter(f=>codes.has(String(f.properties?.code)));
 if(feats.length!==13)throw Error("Contours régionaux incomplets ("+feats.length+"/13)");
 return feats;
}
function kfsProbaDay(day){
 const today=new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Paris",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
 const [y,m,d]=today.split("-").map(Number);
 const target=new Date(Date.UTC(y,m-1,d+day,12));
 return target.toISOString().slice(0,10);
}
function kfsProbaMemberProbability(hourly,day,type,threshold){
 if(!hourly?.time?.length)return null;
 const times=hourly.time;
 const ids=[];
 for(let i=0;i<times.length;i++)if(String(times[i]).startsWith(day))ids.push(i);
 if(!ids.length)return null;
 let pass=0,valid=0;
 const prefix=KFS_PROBA_RULES[type].variable;
 const keys=Object.keys(hourly).filter(k=>k.startsWith(prefix+"_")&&/member\d+/.test(k));
 for(const key of keys){
  const arr=hourly[key];
  if(!Array.isArray(arr))continue;
  const nums=ids.map(i=>arr[i]).filter(v=>typeof v==="number"&&Number.isFinite(v));
  if(nums.length<Math.ceil(ids.length*0.7))continue;
  valid++;
  let event=false;
  if(type==="pluie")event=nums.reduce((a,b)=>a+b,0)>=threshold;
  else if(type==="vent")event=Math.max(...nums)>=threshold;
  else event=Math.max(...nums)*100>=threshold; // API snow_depth en mètres
  if(event)pass++;
 }
 return valid>=2?{pct:100*pass/valid,members:valid}:null;
}
async function kfsProbaModel(model,samples,day,type,threshold){
 const varName=KFS_PROBA_RULES[type].variable;
 const params=new URLSearchParams({
  latitude:samples.map(p=>p.lat).join(","),
  longitude:samples.map(p=>p.lon).join(","),
  models:model[1],hourly:varName,forecast_days:"4",
  timezone:"Europe/Paris",temporal_resolution:"hourly_3"
 });
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),18000);
 let result;
 try{
  const r=await fetch("https://ensemble-api.open-meteo.com/v1/ensemble?"+params,{
   signal:controller.signal,headers:{accept:"application/json"}
  });
  if(!r.ok)throw Error("HTTP "+r.status+": "+(await r.text()).slice(0,100));
  result=await r.json();
 }finally{clearTimeout(timer);}
 const arr=Array.isArray(result)?result:[result];
 if(arr.length!==samples.length)throw Error("Nombre de points inattendu");
 const values=arr.map(p=>{
  if(type==="neige"&&typeof p.elevation==="number"&&p.elevation>800)return null;
  return kfsProbaMemberProbability(p.hourly,day,type,threshold);
 });
 return {name:model[0],values};
}
function kfsProbaClamp(x,lo,hi){return Math.max(lo,Math.min(hi,x));}
function kfsProbaPalette(p){
 const cs=[[17,37,64],[30,106,159],[36,168,166],[229,196,71],[246,128,53],[224,49,72]];
 const u=kfsProbaClamp(p/20,0,5),k=Math.min(4,Math.floor(u)),f=u-k;
 return cs[k].map((v,i)=>Math.round(v*(1-f)+cs[k+1][i]*f));
}
function kfsProbaRender(features,samples,zone){
 const W=900,H=615,P={x:24,y:26,w:852,h:515};
 const rgba=new Uint8Array(W*H*4);
 for(let i=0;i<rgba.length;i+=4){rgba[i]=9;rgba[i+1]=20;rgba[i+2]=38;rgba[i+3]=255;}
 const bbox=zone==="FR"?[-5.8,41.15,10.0,51.65]:(()=>{
  const a=kfsProbaBBox(features),dx=a[2]-a[0],dy=a[3]-a[1];
  return [a[0]-.12*dx,a[1]-.12*dy,a[2]+.12*dx,a[3]+.12*dy];
 })();
 const lonToX=lon=>P.x+(lon-bbox[0])/(bbox[2]-bbox[0])*P.w;
 const latToY=lat=>P.y+(bbox[3]-lat)/(bbox[3]-bbox[1])*P.h;
 const GW=100,GH=64,field=new Float32Array(GW*GH);
 const scale=Math.cos((bbox[1]+bbox[3])*Math.PI/360);
 const maxDist=zone==="FR"?3.4:Math.max(.9,(bbox[2]-bbox[0])*.62);
 const valid=samples.filter(s=>Number.isFinite(s.value));
 for(let gy=0;gy<GH;gy++)for(let gx=0;gx<GW;gx++){
  const lon=bbox[0]+(bbox[2]-bbox[0])*gx/(GW-1);
  const lat=bbox[3]-(bbox[3]-bbox[1])*gy/(GH-1);
  let num=0,den=0,nearest=Infinity;
  for(const p of valid){
   const dx=(p.lon-lon)*scale,dy=p.lat-lat,d2=dx*dx+dy*dy;
   nearest=Math.min(nearest,Math.sqrt(d2));
   const w=1/(d2+.01);num+=p.value*w;den+=w;
  }
  field[gy*GW+gx]=(den&&nearest<=maxDist)?num/den:-1;
 }
 function put(x,y,r,g,b){
  if(x<0||y<0||x>=W||y>=H)return;
  const p=(y*W+x)*4;rgba[p]=r;rgba[p+1]=g;rgba[p+2]=b;
 }
 function line(x0,y0,x1,y1,color){
  x0=Math.round(x0);y0=Math.round(y0);x1=Math.round(x1);y1=Math.round(y1);
  let dx=Math.abs(x1-x0),sx=x0<x1?1:-1,dy=-Math.abs(y1-y0),sy=y0<y1?1:-1,err=dx+dy;
  for(let i=0;i<3000;i++){
   put(x0,y0,...color);
   if(x0===x1&&y0===y1)break;
   let e=2*err;
   if(e>=dy){err+=dy;x0+=sx;}
   if(e<=dx){err+=dx;y0+=sy;}
  }
 }
 const rings=features.map(f=>kfsProbaRings(f).map(r=>r.map(c=>[lonToX(c[0]),latToY(c[1])])));
 // Remplissage scanline dans les polygones, pas de couleurs inventées sur la mer.
 for(const rr of rings){
  for(let y=P.y;y<P.y+P.h;y++){
   const cross=[];
   for(const ring of rr)for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const a=ring[i],b=ring[j];
    if((a[1]>y)!==(b[1]>y))cross.push(a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]));
   }
   cross.sort((a,b)=>a-b);
   for(let n=0;n+1<cross.length;n+=2){
    const first=Math.max(P.x,Math.floor(cross[n])),last=Math.min(P.x+P.w-1,Math.ceil(cross[n+1]));
    for(let x=first;x<=last;x++){
     const xx=kfsProbaClamp((x-P.x)/P.w*(GW-1),0,GW-1),
      yy=kfsProbaClamp((y-P.y)/P.h*(GH-1),0,GH-1);
     const x0=Math.floor(xx),y0=Math.floor(yy),x1=Math.min(GW-1,x0+1),y1=Math.min(GH-1,y0+1);
     const fx=xx-x0,fy=yy-y0;
     let v1=field[y0*GW+x0],v2=field[y0*GW+x1],v3=field[y1*GW+x0],v4=field[y1*GW+x1];
     const all=[v1,v2,v3,v4].filter(v=>v>=0);
     const p=all.length===4?((v1*(1-fx)+v2*fx)*(1-fy)+(v3*(1-fx)+v4*fx)*fy):(all.length?all.reduce((a,b)=>a+b,0)/all.length:-1);
     put(x,y,...(p<0?[63,77,89]:kfsProbaPalette(p)));
    }
   }
  }
 }
 for(const rr of rings)for(const ring of rr)for(let i=1;i<ring.length;i++){
  line(ring[i-1][0],ring[i-1][1],ring[i][0],ring[i][1],[219,231,241]);
 }
 // Bandeau de légende graduée, 0% à 100%. Les textes sont dans le message Discord.
 const ly=565,left=124,right=775;
 for(let x=left;x<=right;x++){
  const c=kfsProbaPalette(100*(x-left)/(right-left));
  for(let y=ly;y<ly+15;y++)put(x,y,...c);
 }
 for(let i=0;i<=4;i++){
  const x=Math.round(left+(right-left)*i/4);
  for(let y=ly-5;y<ly+20;y++)put(x,y,246,250,254);
 }
 return {rgba,W,H};
}
function kfsProbaCrc(a){
 let c=-1;
 for(const b of a){c^=b;for(let k=0;k<8;k++)c=c&1?(c>>>1)^0xedb88320:c>>>1;}
 return (c^(-1))>>>0;
}
function kfsProbaUint32(n){return new Uint8Array([(n>>>24)&255,(n>>>16)&255,(n>>>8)&255,n&255]);}
function kfsProbaChunk(type,data){
 const t=new TextEncoder().encode(type),c=new Uint8Array(t.length+data.length);
 c.set(t);c.set(data,t.length);
 const out=new Uint8Array(12+data.length);
 out.set(kfsProbaUint32(data.length));out.set(c,4);out.set(kfsProbaUint32(kfsProbaCrc(c)),8+data.length);
 return out;
}
async function kfsProbaPng(frame){
 const {rgba,W,H}=frame;
 const raw=new Uint8Array(H*(W*4+1));
 for(let y=0;y<H;y++)raw.set(rgba.subarray(y*W*4,(y+1)*W*4),y*(W*4+1)+1);
 const c=new CompressionStream("deflate");
 const stream=new Blob([raw]).stream().pipeThrough(c);
 const compressed=new Uint8Array(await new Response(stream).arrayBuffer());
 const hdr=new Uint8Array(13);hdr.set(kfsProbaUint32(W),0);hdr.set(kfsProbaUint32(H),4);hdr[8]=8;hdr[9]=6;
 const chunks=[new Uint8Array([137,80,78,71,13,10,26,10]),kfsProbaChunk("IHDR",hdr),kfsProbaChunk("IDAT",compressed),kfsProbaChunk("IEND",new Uint8Array())];
 const size=chunks.reduce((a,b)=>a+b.length,0),res=new Uint8Array(size);
 let pos=0;for(const chunk of chunks){res.set(chunk,pos);pos+=chunk.length;}
 return res;
}
async function kfsProbaComplete(interaction,phenom,zone,jour,seuil){
 try{
  const rules=KFS_PROBA_RULES[phenom];
  if(!rules||![0,1,2,3].includes(jour)||!rules.allowed.includes(seuil))throw Error(
   "Paramètres invalides. Seuils autorisés : neige 1/3/5/10 cm, pluie 1/5/10/20/40 mm, rafales 60/80/100/120 km/h."
  );
  const all=await kfsProbaFeatures(),features=zone==="FR"?all:all.filter(f=>String(f.properties.code)===zone);
  if(!features.length)throw Error("Région non reconnue.");
  const points=kfsProbaSamples(features,zone!=="FR");
  if(points.length<2)throw Error("Échantillonnage spatial insuffisant.");
  const day=kfsProbaDay(jour),available=[],failures=[];
  // Un appel par modèle, toujours à partir des véritables membres de l'ensemble.
  // Exécution séquentielle : évite de saturer l'API gratuite sur une demande.
  for(const model of KFS_PROBA_MODELS){
   try{
    const r=await kfsProbaModel(model,points,day,phenom,seuil);
    let count=0;
    for(let i=0;i<points.length;i++){
     const v=r.values[i];
     if(v){points[i].models.push(v.pct);count++;}
    }
    if(count)available.push(r.name);
    else failures.push(r.name+" : variable indisponible");
   }catch(e){failures.push(model[0]+" : "+String(e.message||e).slice(0,80));}
  }
  for(const p of points)if(p.models.length)p.value=p.models.reduce((a,b)=>a+b,0)/p.models.length;
  const counted=points.filter(p=>Number.isFinite(p.value));
  if(!counted.length)throw Error("Aucun membre d'ensemble exploitable pour ce paramètre. Aucune probabilité affichée.");
  const frame=kfsProbaRender(features,points,zone),png=await kfsProbaPng(frame);
  const name=zone==="FR"?"France métropolitaine":KFS_PROBA_REGIONS.find(r=>r[0]===zone)?.[1]||zone;
  const label=phenom==="neige"?"épaisseur de neige présente au sol ≥ "+seuil+" cm":
   phenom==="pluie"?"cumul de pluie ≥ "+seuil+" mm sur le jour":
   "rafale maximale ≥ "+seuil+" km/h sur le jour";
  const values=counted.map(p=>p.value);
  const min=Math.round(Math.min(...values)),max=Math.round(Math.max(...values));
  const content="**KFS MÉTÉO · /proba · "+name+" · J+"+jour+" ("+day+")**\n"+
   "**Événement :** "+label+"\n"+
   "🗺️ **Probabilité estimée :** "+min+" à "+max+" % sur les points échantillonnés.\n"+
   "📊 **Modèles exploités :** "+available.join(", ")+" ("+available.length+" familles).\n"+
   "**Échelle de la carte :** 0 % · 25 % · 50 % · 75 % · 100 % (de gauche à droite).\n"+
   (phenom==="neige"?"🏔️ Les points situés au-dessus de 800 m sont écartés ; neige au sol modélisée, pas chute fraîche.\n":"")+
   "ℹ️ Estimation **non calibrée**, issue des proportions de membres (poids égal par modèle), et non une probabilité officielle de vigilance. "+
   "Échantillonnage régional : ne remplace pas une prévision locale fine.\n"+
   "_Sources : ensembles Open-Meteo ; contours IGN/INSEE. Données consultées le "+new Date().toISOString().slice(0,16).replace("T"," ")+" UTC._";
  await kfsProbaEdit(interaction,{content,allowed_mentions:{parse:[]}},png);
 }catch(e){
  console.error("KFS_PROBA_ERROR",String(e));
  try{await kfsProbaEdit(interaction,{content:"⚠️ /proba : "+String(e.message||e).slice(0,1500),allowed_mentions:{parse:[]}});}
  catch(err){console.error("KFS_PROBA_DISCORD_ERROR",String(err));}
 }
}
