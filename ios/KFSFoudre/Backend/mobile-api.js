// Insert before the Worker's default export; call from fetch before /discord routing.
// Secret: FOUDRE_MOBILE_TOKEN. Credentials for Xweather remain server-side.
const KFS_MOBILE_INFLIGHT=new Map();
const mobileJson=(obj,status=200,headers={})=>new Response(JSON.stringify(obj),{status,headers:{
  "Content-Type":"application/json;charset=utf-8","Cache-Control":"no-store",...headers}});
function mobileDistance(lat1,lon1,lat2,lon2){
  const rad=Math.PI/180,a=Math.sin((lat2-lat1)*rad/2)**2+
    Math.cos(lat1*rad)*Math.cos(lat2*rad)*Math.sin((lon2-lon1)*rad/2)**2;
  return 6371*2*Math.atan2(Math.sqrt(a),Math.sqrt(Math.max(0,1-a)));
}
async function mobileTokenMatches(request,env){
  if(!env.FOUDRE_MOBILE_TOKEN)return false;
  const supplied=request.headers.get("Authorization")||"";
  const expected="Bearer "+env.FOUDRE_MOBILE_TOKEN;
  // Constant-length SHA-256 comparison avoids exposing the configured token.
  const hash=async s=>new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(s)));
  const [a,b]=await Promise.all([hash(supplied),hash(expected)]);
  let diff=0;for(let i=0;i<a.length;i++)diff|=a[i]^b[i];return diff===0;
}
async function kfsMobileAPI(request,env){
  if(request.method!=="POST")return mobileJson({error:"Méthode non autorisée"},405,{Allow:"POST"});
  if(!await mobileTokenMatches(request,env))return mobileJson({error:"Accès personnel requis"},401);
  if(Number(request.headers.get("Content-Length")||0)>2048)return mobileJson({error:"Requête trop volumineuse"},413);
  let body;try{const text=await request.text();if(text.length>2048)throw Error();body=JSON.parse(text);}
  catch{return mobileJson({error:"Requête invalide"},400);}
  const {latitude:lat,longitude:lon,radiusKm:radius,positionTimestamp:position}=body;
  if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat<41||lat>52||lon< -6||lon>10||
     ![10,30,50,100].includes(radius)||!Number.isFinite(position)||
     Math.abs(Date.now()/1000-position)>120)
    return mobileJson({error:"Position récente en France métropolitaine et rayon valide requis"},400);
  // One personal phone, at most one source consultation/minute per edge location.
  // This is a throttle, not a contractual global quota cap; the iPhone also caps sessions.
  const minute=Math.floor(Date.now()/60000);
  const key=new Request("https://kfs-mobile-rate.invalid/v1/"+minute);
  if(KFS_MOBILE_INFLIGHT.has(minute)||await caches.default.match(key))
    return mobileJson({error:"Prochaine consultation dans une minute",retryAfterSeconds:60},429,{"Retry-After":"60"});
  KFS_MOBILE_INFLIGHT.set(minute,true);
  for(const m of KFS_MOBILE_INFLIGHT.keys())if(m<minute-2)KFS_MOBILE_INFLIGHT.delete(m);
  try{
    await caches.default.put(key,new Response("used",{headers:{"Cache-Control":"public,max-age=120"}}));
    const source=await foudreData({lat,lon},env);
    const now=Date.now()/1000;
    const strikes=source.pulses.filter(p=>p.time>=now-300&&p.time<=now+10)
      .map(p=>({id:[p.time.toFixed(3),p.lat.toFixed(5),p.lon.toFixed(5),p.type,p.amp??"na"].join(":"),
        latitude:p.lat,longitude:p.lon,timestamp:p.time,type:p.type,
        peakCurrentKA:Number.isFinite(p.amp)?p.amp/1000:null,
        distanceKm:mobileDistance(lat,lon,p.lat,p.lon)}))
      .filter(p=>p.distanceKm<=radius).sort((a,b)=>b.timestamp-a.timestamp);
    return mobileJson({schema:1,provider:"Vaisala Xweather",collectedAt:source.collecte/1000,
      windowSeconds:300,pollAfterSeconds:60,state:source.etat,
      partial:source.limite,strikes,
      note:strikes.length?"Courants de crête mesurés, en kA.":
        "Aucune décharge fournie pour cette fenêtre. Cela ne prouve pas l’absence d’orage."});
  }catch(e){
    // Never expose an upstream URL (it may contain API credentials).
    const message=String(e?.message||"");
    const quota=/429|maxhits|quota/i.test(message);
    return mobileJson({error:quota?"Quota Xweather atteint":"Source foudre momentanément indisponible",
      retryAfterSeconds:quota?900:120},quota?429:503,{"Retry-After":quota?"900":"120"});
  }
}
