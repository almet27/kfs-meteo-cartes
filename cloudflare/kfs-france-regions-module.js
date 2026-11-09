
// KFS /france : calcul dynamique de cartes régionales, sans publier 13x des PNG sur GitHub.
// Utilise les contours des régions/départements et les villes de /proba.
// Les valeurs régionales sont des échantillons déterministes via Open-Meteo,
// distincts des cartes nationales GRIB; il faut le signaler explicitement.
const KFS_FRANCE_REGION_MODELS={
 ifs:["ECMWF IFS","ecmwf_ifs025"],
 gfs:["NOAA GFS","ncep_gfs_global"],
 "aifs-single":["ECMWF AIFS","ecmwf_aifs025_single"],
 aigfs:["NOAA AIGFS","ncep_aigfs025"],
 arome:["ARÔME France","meteofrance_arome_france"],
 icon_eu:["ICON Europe","icon_eu"]
};
const KFS_FRANCE_REGION_METRICS={
 tmin:["Température minimale","temperature_2m_min","°C"],
 tmax:["Température maximale","temperature_2m_max","°C"],
 gust:["Rafales maximales","wind_gusts_10m_max","km/h"],
 precip:["Précipitations totales","precipitation_sum","mm"],
 rain:["Pluie seule","rain_sum","mm"],
 orage:["Potentiel orageux",null,"indice"],
 neige_sol:["Tenue de neige possible",null,"indice"]
};
const KFS_FRANCE_REGION_SCALES={
 tmin:[[-12,-8,-4,0,4,8,12,16,20,24,28],[42,70,154],[70,100,190],[92,162,218],[112,197,214],[151,218,179],[191,221,118],[229,219,85],[244,172,65],[234,116,59],[209,71,65],[170,44,74],[130,38,100]],
 tmax:[[-10,-5,0,5,10,15,20,25,30,35],[45,74,164],[72,113,200],[99,181,225],[134,206,202],[181,219,138],[229,223,107],[244,185,80],[244,128,65],[224,78,66],[180,49,81],[132,34,94]],
 gust:[[0,20,35,45,55,70,85,100,120],[77,127,181],[110,172,221],[132,198,193],[160,212,125],[228,219,92],[242,174,76],[231,119,69],[219,74,85],[169,48,119],[123,39,125]],
 precip:[[0,.2,1,2,5,10,20,30,50,80],[42,67,105],[123,199,227],[69,155,218],[57,106,199],[64,117,160],[56,148,122],[164,195,72],[241,213,69],[240,145,69],[200,62,87],[129,43,104]],
 rain:[[0,.2,1,2,5,10,20,30,50,80],[42,67,105],[123,199,227],[69,155,218],[57,106,199],[64,117,160],[56,148,122],[164,195,72],[241,213,69],[240,145,69],[200,62,87],[129,43,104]],
 orage:[[0,1,2,3],[83,174,153],[235,210,90],[240,146,76],[221,59,85]],
 neige_sol:[[0,1,2,3],[83,174,153],[190,215,91],[240,158,79],[220,73,115]]
};
const KFS_FRANCE_REGION_CACHE_TTL=300;
// Classification WMO: aucun symbole ne sera créé sans code météo valide.
function kfsFranceWmoIcon(code){
 if(!Number.isInteger(code))return null;
 if(code===0)return "sun";
 if(code===1||code===2)return "partly";
 if(code===3)return "cloud";
 if(code===45||code===48)return "fog";
 if([51,53,55,56,57,61,63,65,66,67,80,81,82].includes(code))return "rain";
 if([71,73,75,77,85,86].includes(code))return "snow";
 if([95,96,97,99].includes(code))return "storm";
 return null;
}
function kfsFranceWmoRank(code){
 const kind=kfsFranceWmoIcon(code);
 return ({sun:0,partly:1,cloud:2,fog:3,rain:4,snow:5,storm:6})[kind]??-1;
}
// Décrit les CONDITIONS PRÉDOMINANTES de la journée, pas son pire instant.
// On ne représente plus toute la journée comme pluvieuse à cause d'une seule averse.
// Fenêtre du jour : 07h-19h locales; pour J+0 partiel, horaires réellement présents.
function kfsFranceDayCondition(record,date){
 const h=record?.hourly||{}, times=h.time||[];
 let hours=[];
 for(let i=0;i<times.length;i++)
  if(String(times[i]).startsWith(date)){
   const hour=Number(String(times[i]).slice(11,13));
   if(hour>=7&&hour<20)hours.push(i);
  }
 if(hours.length<3){
  hours=[];
  for(let i=0;i<times.length;i++)
   if(String(times[i]).startsWith(date))hours.push(i);
 }
 const allowed=["sun","partly","cloud","fog","rain","snow","storm"];
 const categories=[],clouds=[];
 for(const i of hours){
  const code=h.weather_code?.[i],kind=kfsFranceWmoIcon(code);
  if(kind)categories.push(kind);
  const cover=h.cloud_cover?.[i];
  if(Number.isFinite(cover))clouds.push(cover);
 }
 // Si weather_code n'est pas accessible, aucun ciel n'est déduit du thermomètre.
 const valid=Math.max(categories.length,clouds.length);
 if(valid<Math.min(3,hours.length)||valid===0){
  const dateIndex=record?.daily?.time?.indexOf(date)??-1;
  const fallback=dateIndex>=0?record.daily?.weather_code?.[dateIndex]:null;
  return kfsFranceWmoIcon(fallback);
 }
 const counts=Object.fromEntries(allowed.map(x=>[x,0]));
 for(const category of categories)counts[category]++;
 const n=categories.length;
 const wet=counts.rain+counts.snow+counts.storm;
 const cloudMean=clouds.length>=3?clouds.reduce((a,b)=>a+b,0)/clouds.length:null;
 // On privilégie les phénomènes durables, mais un orage/une chute de neige
 // suffisamment marqué reste affiché. Les courtes averses sont mixtes.
 const minimum=Math.max(2,Math.ceil(n*.20));
 if(counts.storm>=Math.max(1,Math.ceil(n*.15)))return "storm";
 if(counts.snow>=minimum)return "snow";
 if(counts.rain>=Math.max(3,Math.ceil(n*.35)))return "rain";
 if(wet>=Math.max(2,Math.ceil(n*.12))){
  if(counts.snow>=2)return "snowshowers";
  return "showers";
 }
 if(counts.fog>=Math.max(3,Math.ceil(n*.35)))return "fog";
 if(cloudMean!==null){
  if(cloudMean<25)return "sun";
  if(cloudMean<70)return "partly";
  return "cloud";
 }
 if(n){
  const dominant=["sun","partly","cloud","fog"].sort((a,b)=>
    counts[b]-counts[a])[0];
  return counts[dominant]>0?dominant:"partly";
 }
 return null;
}

function kfsFranceRegionColor(v,metric){
 const spec=KFS_FRANCE_REGION_SCALES[metric];
 if(!Number.isFinite(v))return [55,72,91];
 const bounds=spec[0];
 let idx=0;while(idx<bounds.length-1&&v>=bounds[idx+1])idx++;
 return spec[Math.min(idx+1,spec.length-1)];
}
function kfsFranceRegionDisplayValue(v,metric){
 if(!Number.isFinite(v))return "ND";
 if(metric==="tmin"||metric==="tmax")return Math.round(v)+"C";
 if(metric==="orage"||metric==="neige_sol")return ["NUL","FAIBLE","POSSIBLE","MARQUE"][Math.min(3,Math.max(0,Math.round(v)))];
 return metric==="gust"?String(Math.round(v)):String(Math.round(v*10)/10);
}
function kfsFranceRegionalRender(features,depts,samples,zone,metric,subtitle){
 const W=920,H=790,P={x:35,y:62,w:850,h:605};
 const rgba=new Uint8Array(W*H*4);
 for(let i=0;i<rgba.length;i+=4){rgba[i]=9;rgba[i+1]=23;rgba[i+2]=42;rgba[i+3]=255;}
 const bbox=kfsProbaBBox(features),dx=bbox[2]-bbox[0],dy=bbox[3]-bbox[1];
 const centerLon=(bbox[0]+bbox[2])/2,centerLat=(bbox[1]+bbox[3])/2;
 const cosLat=Math.cos(centerLat*Math.PI/180);
 const spanX=Math.max(dx*1.15,.9),spanY=Math.max(dy*1.15,.7);
 const scale=Math.min(P.w/(spanX*cosLat),P.h/spanY);
 const centerX=P.x+P.w/2,centerY=P.y+P.h/2;
 const xx=lon=>centerX+(lon-centerLon)*cosLat*scale;
 const yy=lat=>centerY-(lat-centerLat)*scale;
 const lon=x=>centerLon+(x-centerX)/(cosLat*scale);
 const lat=y=>centerLat-(y-centerY)/scale;
 function put(x,y,color){x=Math.round(x);y=Math.round(y);
  if(x<0||y<0||x>=W||y>=H)return;
  const i=(y*W+x)*4;rgba[i]=color[0];rgba[i+1]=color[1];rgba[i+2]=color[2];
 }
 function rect(x,y,w,h,color){const left=Math.max(0,Math.round(x)),top=Math.max(0,Math.round(y));
  for(let j=top;j<Math.min(H,top+h);j++)for(let i=left;i<Math.min(W,left+w);i++)put(i,j,color);
 }
 function line(x0,y0,x1,y1,color){x0=Math.round(x0);y0=Math.round(y0);x1=Math.round(x1);y1=Math.round(y1);
  let dX=Math.abs(x1-x0),sx=x0<x1?1:-1,dY=-Math.abs(y1-y0),sy=y0<y1?1:-1,err=dX+dY;
  for(let n=0;n<6000;n++){put(x0,y0,color);if(x0===x1&&y0===y1)break;const e2=2*err;
   if(e2>=dY){err+=dY;x0+=sx;}if(e2<=dX){err+=dX;y0+=sy;}}
 }
 // Pictogrammes vectoriels compacts : couleurs et formes lisibles sans pastille noire.
 function dot(cx,cy,r,color){
  for(let y=Math.floor(cy-r);y<=Math.ceil(cy+r);y++)
   for(let x=Math.floor(cx-r);x<=Math.ceil(cx+r);x++)
    if((x-cx)*(x-cx)+(y-cy)*(y-cy)<=r*r)put(x,y,color);
 }
 function icon(cx,cy,kind){
  const ink=[11,44,72],white=[240,248,255],gray=[202,221,234],
        sun=[255,198,67],blue=[67,187,255],snow=[248,250,255],gold=[255,219,79];
  const cloud=(x,y)=>{
   // Fin contour blanc: lisibilité sur fonds de température, pluie et rafales.
   dot(x-8,y+1,8,ink);dot(x,y-4,10,ink);dot(x+10,y+1,8,ink);
   rect(x-14,y,29,10,ink);
   dot(x-8,y,6,white);dot(x,y-5,8,gray);dot(x+10,y,6,white);
   rect(x-13,y,27,8,gray);rect(x-11,y+7,23,2,white);
  };
  const sunshine=(x,y)=>{
   dot(x,y,9,ink);dot(x,y,7,sun);
   for(let a=0;a<8;a++){const p=a*Math.PI/4;
    line(x+Math.cos(p)*11,y+Math.sin(p)*11,
         x+Math.cos(p)*15,y+Math.sin(p)*15,sun);}
  };
  if(kind==="sun"){sunshine(cx,cy);return;}
  if(kind==="partly"){sunshine(cx-8,cy-7);cloud(cx+4,cy+4);return;}
  if(kind==="showers"||kind==="snowshowers"){
   sunshine(cx-10,cy-9);cloud(cx+4,cy-3);
   if(kind==="showers"){
    for(let i=0;i<2;i++)line(cx+i*11-5,cy+9,cx+i*11-9,cy+17,blue);
   }else{
    for(let i=0;i<2;i++){
     const x=cx+i*11-3,y=cy+13;
     line(x-3,y,x+3,y,snow);line(x,y-3,x,y+3,snow);
    }
   }
   return;
  }
  cloud(cx,cy-3);
  if(kind==="cloud")return;
  if(kind==="fog"){
   for(let i=0;i<3;i++)line(cx-12,cy+10+i*4,cx+12-(i%2)*4,cy+10+i*4,white);
  }else if(kind==="rain"){
   for(let i=0;i<3;i++)line(cx-10+i*10,cy+9,cx-14+i*10,cy+17,blue);
  }else if(kind==="snow"){
   for(let i=0;i<3;i++){
    const x=cx-11+i*11,y=cy+13;
    line(x-3,y,x+3,y,snow);line(x,y-4,x,y+4,snow);
    line(x-3,y-3,x+3,y+3,snow);line(x-3,y+3,x+3,y-3,snow);
   }
  }else if(kind==="storm"){
   line(cx+1,cy+7,cx-5,cy+17,gold);
   line(cx-5,cy+17,cx+2,cy+15,gold);
   line(cx+2,cy+15,cx-1,cy+24,gold);
   line(cx-9,cy+10,cx-12,cy+16,blue);
  }
 }
 const GW=108,GH=86,field=new Float32Array(GW*GH);
 const valid=samples.filter(p=>Number.isFinite(p.value));
 if(valid.length<2)throw Error("Pas assez de points valides pour afficher cette région.");
 const maxDist=Math.max(.72,Math.hypot(dx*cosLat,dy)*.62);
 function interpolate(x,y){
  let acc=0,weights=0,nearest=Infinity;
  for(const p of valid){const u=(p.lon-x)*cosLat,v=p.lat-y,d=u*u+v*v;
   nearest=Math.min(nearest,Math.sqrt(d));const w=1/(d+.007);
   acc+=p.value*w;weights+=w;}
  return weights&&nearest<=maxDist?acc/weights:NaN;
 }
 for(let j=0;j<GH;j++)for(let i=0;i<GW;i++)
  field[j*GW+i]=interpolate(lon(P.x+P.w*i/(GW-1)),lat(P.y+P.h*j/(GH-1)));
 const regions=features.flatMap(f=>kfsProbaRings(f).map(r=>r.map(c=>[xx(c[0]),yy(c[1])])));
 for(let y=P.y;y<P.y+P.h;y++){
  const crosses=[];
  for(const ring of regions)for(let i=0,j=ring.length-1;i<ring.length;j=i++){
   const a=ring[i],b=ring[j];
   if((a[1]>y)!==(b[1]>y))crosses.push(a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]));
  }
  crosses.sort((a,b)=>a-b);
  for(let k=0;k+1<crosses.length;k+=2){
   const from=Math.max(P.x,Math.floor(crosses[k])),to=Math.min(P.x+P.w-1,Math.ceil(crosses[k+1]));
   for(let x=from;x<=to;x++){
    const fx=(x-P.x)/P.w*(GW-1),fy=(y-P.y)/P.h*(GH-1);
    const i=Math.max(0,Math.min(GW-1,Math.floor(fx))),j=Math.max(0,Math.min(GH-1,Math.floor(fy)));
    const i2=Math.min(GW-1,i+1),j2=Math.min(GH-1,j+1),u=fx-i,v=fy-j;
    const corners=[[field[j*GW+i],(1-u)*(1-v)],[field[j*GW+i2],u*(1-v)],
       [field[j2*GW+i],(1-u)*v],[field[j2*GW+i2],u*v]].filter(q=>Number.isFinite(q[0]));
    let value=NaN;
    if(corners.length){const den=corners.reduce((a,b)=>a+b[1],0);
      value=den>0?corners.reduce((a,b)=>a+b[0]*b[1],0)/den:NaN;}
    put(x,y,kfsFranceRegionColor(value,metric));
   }
  }
 }
 // Départements sous contour de région : ensemble complet vérifié par /proba.
 for(const d of depts)for(const ring of kfsProbaRings(d))
  for(let i=1;i<ring.length;i++)line(xx(ring[i-1][0]),yy(ring[i-1][1]),
   xx(ring[i][0]),yy(ring[i][1]),[174,207,228]);
 for(const ring of regions)for(let i=1;i<ring.length;i++)
  line(ring[i-1][0],ring[i-1][1],ring[i][0],ring[i][1],[248,250,254]);
 // Font 5x7 déterministe, déjà utilisé sur les cartes /proba.
 const glyphs={
  "A":["01110","10001","10001","11111","10001","10001","10001"],
  "B":["11110","10001","10001","11110","10001","10001","11110"],
  "C":["01111","10000","10000","10000","10000","10000","01111"],
  "D":["11110","10001","10001","10001","10001","10001","11110"],
  "E":["11111","10000","10000","11110","10000","10000","11111"],
  "F":["11111","10000","10000","11110","10000","10000","10000"],
  "G":["01111","10000","10000","10111","10001","10001","01110"],
  "H":["10001","10001","10001","11111","10001","10001","10001"],
  "I":["01110","00100","00100","00100","00100","00100","01110"],
  "J":["00111","00010","00010","00010","10010","10010","01100"],
  "K":["10001","10010","10100","11000","10100","10010","10001"],
  "L":["10000","10000","10000","10000","10000","10000","11111"],
  "M":["10001","11011","10101","10101","10001","10001","10001"],
  "N":["10001","11001","10101","10011","10001","10001","10001"],
  "O":["01110","10001","10001","10001","10001","10001","01110"],
  "P":["11110","10001","10001","11110","10000","10000","10000"],
  "Q":["01110","10001","10001","10001","10101","10010","01101"],
  "R":["11110","10001","10001","11110","10100","10010","10001"],
  "S":["01111","10000","10000","01110","00001","00001","11110"],
  "T":["11111","00100","00100","00100","00100","00100","00100"],
  "U":["10001","10001","10001","10001","10001","10001","01110"],
  "V":["10001","10001","10001","10001","10001","01010","00100"],
  "W":["10001","10001","10001","10101","10101","10101","01010"],
  "X":["10001","10001","01010","00100","01010","10001","10001"],
  "Y":["10001","10001","01010","00100","00100","00100","00100"],
  "Z":["11111","00001","00010","00100","01000","10000","11111"],
  " ":["00000","00000","00000","00000","00000","00000","00000"],
  "0":["01110","10001","10011","10101","11001","10001","01110"],
  "1":["00100","01100","00100","00100","00100","00100","01110"],
  "2":["01110","10001","00001","00010","00100","01000","11111"],
  "3":["11110","00001","00001","01110","00001","00001","11110"],
  "4":["00010","00110","01010","10010","11111","00010","00010"],
  "5":["11111","10000","11110","00001","00001","10001","01110"],
  "6":["00110","01000","10000","11110","10001","10001","01110"],
  "7":["11111","00001","00010","00100","01000","01000","01000"],
  "8":["01110","10001","10001","01110","10001","10001","01110"],
  "9":["01110","10001","10001","01111","00001","00010","11100"],
  "%":["11001","11010","00100","01000","10110","00110","00000"],
  ".":["00000","00000","00000","00000","00000","00100","00100"],
  "m":["00000","00000","11010","10101","10101","10101","10101"],
  "c":["00000","00000","01110","10000","10000","10000","01110"],
  "k":["10000","10000","10100","11000","10100","10010","10001"],
  "h":["10000","10000","10110","11001","10001","10001","10001"],
  "/":["00001","00001","00010","00100","01000","10000","10000"],
  "-":["00000","00000","00000","11111","00000","00000","00000"]
 };
 function txt(value,x,y,size=2,color=[250,250,255]){
  let offset=Math.round(x);
  for(const ch of String(value).toUpperCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"")){
   const cells=glyphs[ch]||glyphs[" "];
   if(!cells){offset+=6*size;continue;}
   for(let i=0;i<7;i++)for(let j=0;j<5;j++)if(cells[i][j]==="1")
    rect(offset+j*size,y+i*size,size,size,color);
   offset+=6*size;
  }
 }
 function wordWidth(str,size=2){return String(str).normalize("NFD").replace(/[\u0300-\u036f]/g,"").length*6*size;}
 const occupied=[],cityPlaces=[];
 for(const [name,x,y] of (KFS_PROBA_CITIES[zone]||[])){
  if(!features.some(f=>kfsProbaInFeature(x,y,f)))continue;
  const px=xx(x),py=yy(y),title=name.toUpperCase();
  const w=wordWidth(title)+12,h=24;
  for(const [tx,ty] of [[px+9,py-18],[px-w-10,py-18],[px-w/2,py-37],[px-w/2,py+11]]){
   const a={x:Math.round(tx),y:Math.round(ty),w,h};
   if(a.x<P.x||a.y<P.y||a.x+w>P.x+P.w||a.y+h>P.y+P.h)continue;
   if(occupied.some(t=>!(a.x>t.x+t.w+5||a.x+a.w+5<t.x||a.y>t.y+t.h+6||a.y+a.h+6<t.y)))continue;
   rect(a.x,a.y,a.w,a.h,[9,30,50]);txt(title,a.x+6,a.y+5,2,[244,249,255]);
   occupied.push(a);cityPlaces.push({x:px,y:py});break;
  }
  rect(px-2,py-2,5,5,[250,250,255]);rect(px-1,py-1,3,3,[13,43,64]);
 }
 // Labels quantitatifs sur des mailles distinctes, espacés des principales villes.
 const ordered=[...valid].sort((a,b)=>b.lat-a.lat),shown=[];
 const maxMarks=zone==="94"?4:zone==="11"?5:9;
 for(const p of ordered){
  const x=xx(p.lon),y=yy(p.lat),label=kfsFranceRegionDisplayValue(p.value,metric);
  if(label.length>11)continue;
  const w=wordWidth(label)+14,h=24;
  if(cityPlaces.some(c=>Math.abs(c.x-x)<45&&Math.abs(c.y-y)<30))continue;
  const a={x:Math.round(x-w/2),y:Math.round(y-17),w,h};
  if(a.x<P.x||a.x+w>P.x+P.w||a.y<P.y||a.y+h>P.y+P.h)continue;
  if(occupied.some(t=>!(a.x>t.x+t.w+6||a.x+a.w+6<t.x||a.y>t.y+t.h+6||a.y+a.h+6<t.y)))continue;
  if(shown.some(q=>Math.hypot(x-q[0],y-q[1])<105))continue;
  rect(a.x,a.y,w,h,[9,30,50]);txt(label,a.x+7,a.y+5,2,[247,251,255]);
  occupied.push(a); // Réserver aussi la boîte de chaque valeur, pas seulement celle des villes.
  shown.push([x,y]);
  if(shown.length>=maxMarks)break;
 }
 const zoneName=KFS_PROBA_REGIONS.find(r=>r[0]===zone)?.[1]||"REGION";
 txt("KFS METEO FRANCE",40,14,3,[239,247,255]);
 txt(zoneName,385,20,2,[200,233,250]);
 txt(KFS_FRANCE_REGION_METRICS[metric][0],40,40,2,[112,216,244]);
 // Répartition géographique : des symboles pour toutes les parties de la région,
 // limités aux points ayant une prévision exploitable, sans inventer de soleil.
 const weatherPoints=samples.filter(p=>Number.isFinite(p.value)&&
   p.weatherKind&&features.some(f=>kfsProbaInFeature(p.lon,p.lat,f)));
 const positions=[];
 const maximum=zone==="11"||zone==="94"?7:12;
 const offsets=[[0,0],[0,-37],[-37,0],[37,0],[0,37],[-33,-33],
                [33,-33],[-33,33],[33,33],[0,-53],[-53,0],[53,0],[0,53]];
 const free=(r,q,pad=0)=>r.x>=q.x+q.w+pad||r.x+r.w+pad<=q.x||
   r.y>=q.y+q.h+pad||r.y+r.h+pad<=q.y;
 const pending=[...weatherPoints];
 while(pending.length&&positions.length<maximum){
  let best=null;
  for(let index=0;index<pending.length;index++){
   const p=pending[index],sx=xx(p.lon),sy=yy(p.lat);
   for(const [ox,oy] of offsets){
    const x=sx+ox,y=sy+oy;
    const box={x:x-21,y:y-23,w:43,h:51};
    if(box.x<P.x+3||box.y<P.y+3||box.x+box.w>P.x+P.w-3||
       box.y+box.h>P.y+P.h-3)continue;
    if(!features.some(f=>kfsProbaInFeature(lon(x),lat(y),f)))continue;
    if(occupied.some(q=>!free(box,q,8)))continue;
    if(cityPlaces.some(c=>Math.hypot(c.x-x,c.y-y)<40))continue;
    const minDistance=positions.length?
      Math.min(...positions.map(q=>Math.hypot(q.x-x,q.y-y))):250;
    if(minDistance<77)continue;
    // Chercher les régions non encore représentées plutôt que d'empiler
    // les icônes au nord ou près d'une seule ville.
    const score=minDistance-Math.hypot(ox,oy)*.25;
    if(!best||score>best.score)
      best={index,x,y,kind:p.weatherKind,score};
   }
  }
  if(!best)break;
  positions.push({x:best.x,y:best.y,kind:best.kind});
  pending.splice(best.index,1);
 }
 for(const p of positions)icon(p.x,p.y,p.kind);
 // Légende quantitative + unités, hors territoire.
 const scaleSpec=KFS_FRANCE_REGION_SCALES[metric],levels=scaleSpec[0],
       colors=scaleSpec.slice(1),x0=75,y0=700,band=770/colors.length;
 for(let i=0;i<colors.length;i++){
  rect(Math.round(x0+i*band),y0,Math.ceil(band),20,colors[i]);
  const label=metric==="orage"||metric==="neige_sol"?String(i):String(levels[Math.min(i,levels.length-1)]);
  if(i%Math.max(1,Math.ceil(colors.length/9))===0)
   txt(label,Math.round(x0+i*band),730,2,[228,241,252]);
 }
 txt(KFS_FRANCE_REGION_METRICS[metric][2],795,756,2,[220,237,249]);
 txt(subtitle,40,762,2,[185,222,241]);
 return {rgba,W,H};
}
async function kfsFranceRegionRequest(model,metric,day,hour,samples){
 const params=KFS_FRANCE_REGION_MODELS[model];
 if(!params)throw Error("Modèle régional inconnu.");
 const risk=metric==="orage"||metric==="neige_sol";
 if(risk&&!["arome","icon_eu"].includes(model))
  throw Error("Les cartes de risque régionales sont calculées pour ARÔME et ICON.");
 if(risk&&![6,12,24,36,48].includes(hour))
  throw Error("Choisis une échéance H+6, H+12, H+24, H+36 ou H+48.");
 if(!risk&&!Number.isInteger(day))throw Error("Jour non valide.");
 if(["arome","icon_eu"].includes(model)&&!risk&&day>2)
  throw Error("ARÔME et ICON sont limités à 48 h : J+0 à J+2 selon la couverture.");
 const latitude=samples.map(p=>p.lat.toFixed(3)).join(","),
       longitude=samples.map(p=>p.lon.toFixed(3)).join(",");
 const fields=risk?(metric==="orage"?
   ["cape","precipitation","wind_speed_850hPa","wind_direction_850hPa","wind_speed_500hPa","wind_direction_500hPa"]:
   ["temperature_2m","wet_bulb_temperature_2m","snowfall",...(model==="icon_eu"?["snow_depth","soil_temperature_0cm"]:[])]):[];
 // Les prévisions horaires déterminent le temps dominant de la journée.
 // Les 13 régions conservent le même échantillonnage et un unique lot d'appels.
 // Retirer graduellement les variables facultatives sur HTTP 400, sans
 // perturber les températures, rafales et précipitations existantes.
 const url=new URL("https://api.open-meteo.com/v1/forecast");
 const baseHour=risk?fields:["temperature_2m"];
 const candidates=risk?[
   [...baseHour,"weather_code"],
   baseHour
 ]:[
   [...baseHour,"weather_code","cloud_cover"],
   [...baseHour,"weather_code"],
   baseHour
 ];
 const createParams=(variables,includeDailyCode)=>({latitude,longitude,
  models:params[1],timezone:"Europe/Paris",
  ...(risk?{hourly:variables.join(","),forecast_hours:"48"}:{
   daily:[KFS_FRANCE_REGION_METRICS[metric][1],
    ...(includeDailyCode?["weather_code"]:[])].join(","),
   hourly:variables.join(","),
   forecast_days:String(Math.max(day+2,4))
  })});
 let response=null;
 for(let attempt=0;attempt<candidates.length+1;attempt++){
  const fieldsForCall=candidates[Math.min(attempt,candidates.length-1)];
  const dailyCode=attempt<candidates.length;
  url.search=new URLSearchParams(createParams(fieldsForCall,dailyCode)).toString();
  response=await fetch(url,{signal:AbortSignal.timeout(14500),
    cf:{cacheEverything:true,cacheTtl:450}});
  if(response.ok)break;
  if(response.status!==400)break;
 }
 if(!response.ok)throw Error("Source modèle "+params[0]+" HTTP "+response.status+
  " ; aucune carte inventée.");
 const raw=await response.json(),records=Array.isArray(raw)?raw:[raw];
 if(records.length!==samples.length)throw Error("Incohérence de points dans la réponse météo.");
 const date=kfsProbaDay(day),coverage=[],codes=[],kinds=[];
 const values=records.map(rec=>{
  if(risk){
   const h=rec.hourly||{},length=h.time?.length||0;
   const ending=Math.min(hour,length),starting=({6:0,12:6,24:12,36:24,48:36})[hour];
   const present=h.weather_code?.slice(starting,ending).filter(Number.isInteger)||[];
   const representative=present.reduce((a,b)=>kfsFranceWmoRank(b)>kfsFranceWmoRank(a)?b:a,null);
   codes.push(representative);
   kinds.push(kfsFranceWmoIcon(representative));
   let max=null;
   for(let i=starting;i<ending;i++){
    let level=null;
    if(metric==="orage"){
      const cape=h.cape?.[i],rain=h.precipitation?.[i],
            a=h.wind_speed_850hPa?.[i],b=h.wind_speed_500hPa?.[i],
            da=h.wind_direction_850hPa?.[i],db=h.wind_direction_500hPa?.[i];
      if([cape,rain,a,b,da,db].every(Number.isFinite)){
       const rad=Math.PI/180;
       const shear=Math.hypot(
        b*Math.sin(db*rad)-a*Math.sin(da*rad),
        b*Math.cos(db*rad)-a*Math.cos(da*rad));
       level=cape>=1200&&shear>=45&&rain>=.3?3:
        cape>=500&&shear>=25&&rain>=.1?2:
        cape>=150&&(rain>=.1||shear>=40)?1:0;
      }
    }else{
      const t=h.temperature_2m?.[i],tw=h.wet_bulb_temperature_2m?.[i],
            snow=h.snowfall?.[i];
      if([t,tw,snow].every(Number.isFinite)){
       if(model==="arome")level=snow>=.2&&tw<=.8&&t<=2.5?2:snow>.05&&tw<=1.8?1:0;
       else{
        const d=h.snow_depth?.[i],soil=h.soil_temperature_0cm?.[i];
        if([d,soil].every(Number.isFinite)){
         const prev=h.snow_depth?.[Math.max(0,starting-1)];
         const gain=Number.isFinite(prev)?d-prev:null;
         level=d>=.015&&soil<=1.5&&tw<=.8&&gain!==null&&gain>=.005?3:
          d>=.005&&soil<=2.5&&tw<=1.5?2:
          snow>.05&&tw<=1.8&&soil<=3?1:0;
        }
       }
      }
    }
    if(level!==null)max=Math.max(max??0,level);
   }
   return max;
  }
  const index=rec.daily?.time?.indexOf(date)??-1;
  const q=index>=0?rec.daily?.[KFS_FRANCE_REGION_METRICS[metric][1]]?.[index]:null;
  const fallbackCode=index>=0&&Number.isInteger(rec.daily?.weather_code?.[index])?
    rec.daily.weather_code[index]:null;
  codes.push(fallbackCode);
  kinds.push(kfsFranceDayCondition(rec,date));
  const hours=rec.hourly?.time?.filter(t=>String(t).startsWith(date)).length||0;
  coverage.push(hours);
  return Number.isFinite(q)?q:null;
 });
 const ok=values.filter(Number.isFinite);
 if(ok.length<Math.max(2,Math.ceil(samples.length*.65)))
  throw Error("Données régionales insuffisantes pour "+params[0]+
    ", "+KFS_FRANCE_REGION_METRICS[metric][0]+
    " (points exploitables "+ok.length+"/"+samples.length+").");
 return {values,codes,kinds,date,coverage:risk?null:
  (Math.min(...coverage)>=23?"complete":"partial"),count:ok.length};
}
async function kfsFranceRegionHandle(interaction,model,metric,rawDay,rawHour,zone){
 const endpoint="https://discord.com/api/v10/webhooks/"+APPLICATION_ID+"/"+interaction.token+"/messages/@original";
 try{
  if(!KFS_FRANCE_REGION_MODELS[model]||!KFS_FRANCE_REGION_METRICS[metric]||
    !KFS_PROBA_REGIONS.some(x=>x[0]===zone))throw Error("Sélection régionale invalide.");
  const day=rawDay===undefined?0:Number(rawDay),hour=rawHour===undefined?24:Number(rawHour);
  if(!Number.isInteger(day)||day<0||day>5)throw Error("Choisis J+0 à J+5.");
  const risk=metric==="orage"||metric==="neige_sol";
  const name=KFS_PROBA_REGIONS.find(r=>r[0]===zone)[1];
  // Inclure la date cible et une fenêtre de 5 min : J+1 ne recycle jamais
  // le fichier d'hier, et un nouveau run devient visible rapidement.
  const currentDate=kfsProbaDay(day);
  const key="https://kfs-meteo-ia.alain-leprevost.workers.dev/__cache/france-regions/v5-daytime/"+
      encodeURIComponent([zone,model,metric,risk?hour:day,currentDate,
        Math.floor(Date.now()/300000)].join("-"));
  let bytes=null,record=null;
  try{
   const cached=await caches.default.match(new Request(key));
   if(cached){const packet=await cached.arrayBuffer(),sig=new Uint8Array(packet,0,8);
    if(sig[0]===137&&sig[1]===80&&sig[2]===78&&sig[3]===71)bytes=packet;}
  }catch{}
  if(!bytes){
   const all=await kfsProbaFeatures(),features=all.filter(f=>String(f.properties?.code)===zone);
   if(features.length!==1)throw Error("Contour régional indisponible.");
   const points=kfsProbaSamples(features,true);
   if(points.length<2)throw Error("Échantillonnage régional insuffisant.");
   const [departments,forecast]=await Promise.all([
    kfsProbaDepartments(zone),kfsFranceRegionRequest(model,metric,day,hour,points)
   ]);
   for(let i=0;i<points.length;i++){
    points[i].value=forecast.values[i];
    points[i].weatherCode=forecast.codes?.[i]??null;
    points[i].weatherKind=forecast.kinds?.[i]??null;
   }
   record=forecast;
   const note=risk?"H+"+hour:"J+"+day;
   const frame=kfsFranceRegionalRender(features,departments,points,zone,metric,note);
   bytes=await kfsProbaPng(frame);
   try{
    await caches.default.put(new Request(key),new Response(bytes,{
     headers:{"content-type":"image/png","cache-control":"public,max-age="+KFS_FRANCE_REGION_CACHE_TTL}
    }));
   }catch{}
  }
  const filename="kfs-france-"+model+"-"+metric+"-"+zone+".png";
  const cautions=risk?
    "\n⚠️ Indice qualitatif indicatif, pas une probabilité ni une vigilance officielle.":
    "\nℹ️ Carte régionale interpolée entre points de prévision via Open-Meteo, distincte du produit national GRIB.";
  const partial=record?.coverage==="partial"?"\n⚠️ Journée partiellement couverte.":"";
  const title="🗺️ **KFS MÉTÉO /france — "+name+"**\n"+
   "**"+KFS_FRANCE_REGION_MODELS[model][0]+" · "+KFS_FRANCE_REGION_METRICS[metric][0]+
   " · "+(risk?"H+"+hour:"J+"+day)+"**"+
   (record?.date&&!risk?" · "+record.date:"")+
   "\n📍 Villes principales et limites départementales."+
   "\n🌤️ Pictogrammes : "+
   (risk?"code météo le plus marqué de la période.":"temps dominant entre 7 h et 20 h locales, selon les données horaires.")+
   partial+cautions;
  await kfsFranceSendDiscord(endpoint,{
   content:title,allowed_mentions:{parse:[]},
   embeds:[{image:{url:"attachment://"+filename}}],
   attachments:[{id:0,filename}]
  },bytes,filename);
 }catch(err){
  console.error("KFS_FRANCE_REGION",zone,model,metric,String(err).slice(0,180));
  await kfsFranceSendDiscord(endpoint,{content:"⚠️ **/france — région** : "+
    String(err?.message||err).slice(0,330),allowed_mentions:{parse:[]}})
    .catch(()=>{});
 }
}
