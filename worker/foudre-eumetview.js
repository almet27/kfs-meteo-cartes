// EUMETSAT MTG LI AFA public WMS. Optical flash areas, never ground-strike positions.
const KFS_LI_WMS="https://view.eumetsat.int/geoserver/wms";
const KFS_LI_LAYER="mtg_fd:li_afa";
const KFS_LI_STEP=300000;
const KFS_LI_MAX_AGE=30*60000;
async function kfsLiLatest(){
  const key=new Request("https://kfs-li-cache.invalid/capabilities-v1");
  const old=await caches.default.match(key);
  if(old){const value=await old.json();if(Date.now()-value.checked<60000){
    kfsLiCheckLatest(value.time);return value.time;
  }}
  const q=new URLSearchParams({service:"WMS",version:"1.3.0",request:"GetCapabilities"});
  const r=await fetch(KFS_LI_WMS+"?"+q,{signal:AbortSignal.timeout(8000)});
  if(!r.ok)throw Error("EUMETView catalogue HTTP "+r.status);
  const xml=await r.text(),pos=xml.indexOf("<Name>"+KFS_LI_LAYER+"</Name>");
  if(pos<0)throw Error("Couche EUMETSAT LI absente du catalogue.");
  const layer=xml.slice(pos,xml.indexOf("</Layer>",pos));
  const tag=layer.match(/<Dimension\b[^>]*\bname="time"[^>]*>/)?.[0];
  const time=Date.parse(tag?.match(/\bdefault="([^"]+)"/)?.[1]||"");
  kfsLiCheckLatest(time);
  await caches.default.put(key,new Response(JSON.stringify({time,checked:Date.now()}),{
    headers:{"Content-Type":"application/json","Cache-Control":"public,max-age=60"}}));
  return time;
}
function kfsLiCheckLatest(time){
  if(!Number.isFinite(time)||time>Date.now()+60000||Date.now()-(time+KFS_LI_STEP)>KFS_LI_MAX_AGE)
    throw Error("Dernière image EUMETSAT absente ou âgée de plus de 30 minutes.");
}
function kfsLiBBox(city){
  const dy=100/(F_R*111.195),dx=dy/Math.cos(city.lat*Math.PI/180);
  return [city.lon-F_X*dx,city.lat-(F_H-F_Y)*dy,
    city.lon+(F_W-F_X)*dx,city.lat+F_Y*dy];
}
async function kfsLiPng(bytes){
  // WMS PNG is explicitly checked: 8-bit RGBA, non-interlaced, bounded dimensions.
  const b=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes);
  if(b.length<33||b.length>4000000||b.slice(0,8).some((x,i)=>x!==[137,80,78,71,13,10,26,10][i]))
    throw Error("EUMETSAT : réponse PNG invalide.");
  const v=new DataView(b.buffer,b.byteOffset,b.byteLength),parts=[];
  let width,height,offset=8,ended=false;
  while(offset+12<=b.length){
    const length=v.getUint32(offset),end=offset+12+length;
    if(end>b.length)throw Error("EUMETSAT : PNG tronqué.");
    const type=String.fromCharCode(...b.slice(offset+4,offset+8));
    if(type==="IHDR"){
      width=v.getUint32(offset+8);height=v.getUint32(offset+12);
      if(length!==13||width!==F_W||height!==F_H||b[offset+16]!==8||b[offset+17]!==6||
         b[offset+18]!==0||b[offset+19]!==0||b[offset+20]!==0)
        throw Error("EUMETSAT : format PNG non pris en charge.");
    }else if(type==="IDAT")parts.push(b.slice(offset+8,offset+8+length));
    else if(type==="IEND"){ended=true;break;}
    offset=end;
  }
  if(!width||!parts.length||!ended)throw Error("EUMETSAT : PNG incomplet.");
  const stream=new Blob(parts).stream().pipeThrough(new DecompressionStream("deflate"));
  const reader=stream.getReader(),chunks=[];let size=0;
  const stride=width*4,expected=(stride+1)*height;
  for(;;){const {value,done}=await reader.read();if(done)break;size+=value.length;
    if(size>expected){await reader.cancel();throw Error("EUMETSAT : PNG trop volumineux.");}chunks.push(value);}
  if(size!==expected)throw Error("EUMETSAT : taille PNG incohérente.");
  const raw=foudreConcat(...chunks),pixels=new Uint8Array(width*height*4);
  let at=0;
  const paeth=(a,b,c)=>{const p=a+b-c,pa=Math.abs(p-a),pb=Math.abs(p-b),pc=Math.abs(p-c);
    return pa<=pb&&pa<=pc?a:pb<=pc?b:c;};
  for(let y=0;y<height;y++){
    const filter=raw[at++];if(filter>4)throw Error("EUMETSAT : filtre PNG inconnu.");
    for(let x=0;x<stride;x++){
      const i=y*stride+x,a=x>=4?pixels[i-4]:0,up=y?pixels[i-stride]:0,
        corner=y&&x>=4?pixels[i-stride-4]:0;
      const prediction=filter===0?0:filter===1?a:filter===2?up:
        filter===3?Math.floor((a+up)/2):paeth(a,up,corner);
      pixels[i]=(raw[at++]+prediction)&255;
    }
  }
  return pixels;
}
async function kfsLiFrame(city,time,deadline=Date.now()+18000){
  const q=new URLSearchParams({service:"WMS",version:"1.3.0",request:"GetMap",
    layers:KFS_LI_LAYER,styles:"",crs:"CRS:84",bbox:kfsLiBBox(city).map(x=>x.toFixed(7)).join(","),
    width:String(F_W),height:String(F_H),format:"image/png",transparent:"true",
    time:new Date(time).toISOString()});
  const key=new Request(KFS_LI_WMS+"?"+q);
  let r=await caches.default.match(key);
  if(!r){
    const remaining=Math.min(8000,deadline-Date.now());
    if(remaining<=0)throw Error("Délai EUMETSAT dépassé.");
    r=await fetch(key,{signal:AbortSignal.timeout(remaining)});
    if(!r.ok)throw Error("EUMETSAT image HTTP "+r.status);
    const body=new Uint8Array(await r.arrayBuffer());
    const pixels=await kfsLiPng(body);
    await caches.default.put(key,new Response(body,{headers:{
      "Content-Type":"image/png","Cache-Control":"public,max-age=3600"}}));
    return pixels;
  }
  return kfsLiPng(new Uint8Array(await r.arrayBuffer()));
}
async function foudreSatellite(city,minutes){
  const deadline=Date.now()+22000;
  const latest=await kfsLiLatest(),duration=Math.min(Number(minutes),120);
  if(![5,30,60,120].includes(duration))throw Error("Fenêtre EUMETSAT non prise en charge.");
  const count=duration/5,ages=new Uint8Array(F_W*F_H);
  // Six 5-min images form a 30-min visual union. Never count pixels as flashes.
  let failed=0,received=0;
  for(let i=0;i<count;i+=4){
    const tasks=Array.from({length:Math.min(4,count-i)},(_,j)=>({index:i+j,time:latest-(count-1-i-j)*KFS_LI_STEP}));
    const frames=await Promise.allSettled(tasks.map(t=>kfsLiFrame(city,t.time,deadline)));
    for(let j=0;j<frames.length;j++){
      if(frames[j].status!=="fulfilled"){failed++;continue;}
      received++;const rgba=frames[j].value,index=tasks[j].index+1;
      for(let p=0;p<ages.length;p++)if(rgba[p*4+3]>=32)ages[p]=index;
    }
  }
  if(!received)throw Error("Aucune image EUMETSAT LI exploitable.");
  kfsLiCheckLatest(latest);
  let activePixels=0;
  for(let y=0;y<F_H;y++)for(let x=0;x<F_W;x++)
    if(ages[y*F_W+x]&&Math.hypot(x-F_X,y-F_Y)<=F_R)activePixels++;
  return {ages,activePixels,received,failed,count,minutes:duration,
    from:latest-(count-1)*KFS_LI_STEP,to:latest+KFS_LI_STEP,checked:Date.now(),
    state:failed?"partial":"ok",provider:"EUMETSAT-MTG-LI-AFA"};
}
function foudreSatelliteLines(s,error){
  if(!s)return "🛰️ **Carte satellite indisponible** : "+String(error||"source inaccessible").slice(0,160)+"\n";
  const format=t=>new Date(t).toLocaleString("fr-FR",{timeZone:"Europe/Paris",
    day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
  const delay=Math.max(0,Math.round((s.checked-s.to)/60000));
  return "🛰️ **EUMETSAT · activité électrique satellite · "+s.minutes+" min**\n"+
    "Du **"+format(s.from)+"** au **"+format(s.to)+"** (Paris) · retard ≈ "+delay+" min.\n"+
    (s.activePixels?"🟠 Zones colorées : émissions lumineuses d’éclairs détectées.\n":
      "Aucune zone lumineuse fournie dans ce secteur pour cette fenêtre.\n")+
    "Bleu = plus ancien · jaune = plus récent. Zones optiques, sans localisation d’impacts au sol ni distinction CG/IC.\n"+
    (s.failed?"⚠️ Carte partielle : "+s.received+" images reçues sur "+s.count+".\n":"")+
    (s.minutes===120?"Carte limitée à 2 h ; le bilan Xweather garde la période choisie.\n":"");
}
