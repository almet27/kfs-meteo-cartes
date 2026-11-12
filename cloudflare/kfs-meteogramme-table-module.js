// KFS /meteogramme : coloured hourly table PNG. Add to main module.
const KFS_MGRAM_TABLE_COLS=[
 ["Heure","time",79],["Temps","weather",76],["Temp °C","temp",91],
 ["Humid %","humidity",88],["Pluie mm","rain",90],["Neige cm","snow",95],
 ["Vent","direction",104],["Moy km/h","wind",93],["Raf km/h","gust",97],
 ["Press hPa","pressure",103],["CAPE","cape",88],
 ["Orage idx","storm",93],["Intensite","strength",104],
 ["Neige idx","snowRisk",91],["Gresil idx","graupel",91]
];
function kfsMgramFmtCell(v,d=0,unit=""){
  return Number.isFinite(v)?Number(v.toFixed(d)).toLocaleString("fr-FR")+unit:"—";
}
function kfsMgramWindArrow(dir){
  return Number.isFinite(dir)?["↓","↙","←","↖","↑","↗","→","↘"][Math.round((((dir%360)+360)%360)/45)%8]:"—";
}
function kfsMgramTableRows(rows){
 return rows.map(r=>({
  time:r.time.slice(11,16),weather:kfsMgramWx(r.code,r.isDay===0),
  temp:kfsMgramFmtCell(r.temp,1,"°"),humidity:kfsMgramFmtCell(r.humidity,0,"%"),
  rain:kfsMgramFmtCell(r.rain,1),snow:kfsMgramFmtCell(r.snow,1),
  direction:Number.isFinite(r.dir)?kfsMgramCompass(r.dir)+" "+kfsMgramWindArrow(r.dir):"—",
  wind:kfsMgramFmtCell(r.wind),gust:kfsMgramFmtCell(r.gust),
  pressure:kfsMgramFmtCell(r.pressure),cape:kfsMgramFmtCell(r.cape),
  storm:kfsMgramFmtCell(r.storm),strength:r.strength==="indét."?"Indet.":(r.strength||"—"),
  snowRisk:kfsMgramFmtCell(r.snowRisk),graupel:kfsMgramFmtCell(r.graupel),
  _values:{temp:r.temp,humidity:r.humidity,rain:r.rain,snow:r.snow,
    wind:r.wind,gust:r.gust,cape:r.cape,storm:r.storm,
    snowRisk:r.snowRisk,graupel:r.graupel}
 }));
}
// Draws the full table on a QuickChart canvas. Function source is sent as a string.
function kfsMgramTableCanvas(chart){
 const ctx=chart.ctx,cols=__COLS__,rows=__ROWS__,W=__W__,H=__H__;
 const pad=16,top=92,hh=43,rh=37;
 function rect(x,y,w,h,c){ctx.fillStyle=c;ctx.fillRect(x,y,w,h);}
 function txt(s,x,y,c,size,bold,align){
   ctx.fillStyle=c;ctx.font=(bold?"bold ":"")+size+"px Arial";
   ctx.textAlign=align||"center";ctx.textBaseline="middle";
   ctx.fillText(String(s),x,y);
 }
 function bg(key,v){
   if(typeof v!=="number"||!isFinite(v))return null;
   if(key==="temp")return v<0?"#b8d8ff":v<5?"#9feaf6":v<12?"#b7f5d2":v<20?"#f6f2a7":"#ffc7a0";
   if(key==="humidity")return v>=90?"#8bbce6":v>=70?"#add5f1":v>=45?"#d2e9fa":"#f0f6fd";
   if(key==="rain")return v>=8?"#3b77c0":v>=3?"#6aa9de":v>=.5?"#b7ddf5":v>0?"#d8effc":"#f1f7fc";
   if(key==="snow")return v>=3?"#83b9df":v>=.5?"#c8e9fa":v>0?"#e0f6ff":"#f4f9fd";
   if(key==="wind"||key==="gust")return v>=80?"#ef9d9e":v>=50?"#ffcf9c":v>=25?"#b5ebd7":"#d9f3e8";
   if(key==="cape")return v>=1800?"#f1a7a7":v>=800?"#ffd59f":v>=150?"#fff1be":"#f5f7fc";
   if(key==="storm"||key==="snowRisk"||key==="graupel")return v>=70?"#f6a5a6":v>=40?"#ffd3a0":v>=15?"#fff0ae":"#e8f5e9";
   return null;
 }
 rect(0,0,W,H,"#f0f5fc");rect(0,0,W,85,"#172947");rect(0,83,W,3,"#49b6cd");
 txt(__TITLE__,pad,29,"#ffffff",22,true,"left");
 txt(__SUBTITLE__,pad,62,"#d8e9f8",15,false,"left");
 let x=pad;
 for(let i=0;i<cols.length;i++){
   const w=cols[i][2];
   rect(x,top,w,hh,i%2===0?"#c9d7f8":"#d7e1fa");
   ctx.strokeStyle="#a3b5d2";ctx.strokeRect(x+.5,top+.5,w-1,hh-1);
   txt(cols[i][0],x+w/2,top+hh/2,"#22375b",13,true);
   x+=w;
 }
 for(let j=0;j<rows.length;j++){
   const r=rows[j],y=top+hh+j*rh;let xx=pad;
   for(let i=0;i<cols.length;i++){
     const key=cols[i][1],w=cols[i][2],v=r._values&&r._values[key];
     rect(xx,y,w,rh,bg(key,v)||(j%2===0?"#e7f0fc":"#f7fbff"));
     ctx.strokeStyle="#c6d4e8";ctx.strokeRect(xx+.5,y+.5,w-1,rh-1);
     txt(r[key]??"—",xx+w/2,y+rh/2,"#172947",key==="weather"?22:14,
       key==="temp"||key==="storm"||key==="gust");
     xx+=w;
   }
 }
 const foot=top+hh+rows.length*rh+17;
 txt("Indices 0-100 : diagnostics heuristiques, pas des probabilites calibrées. Graupel = grésil.",
     pad,foot,"#5e7292",13,false,"left");
 txt("Vent : direction d'origine + fleche du deplacement  |  Pluie / neige : quantites horaires",
     pad,foot+24,"#5e7292",13,false,"left");
}
function kfsMgramTableChart(rows,model,city,date){
 const cols=KFS_MGRAM_TABLE_COLS;
 const items=kfsMgramTableRows(rows).slice(0,27);
 const width=cols.reduce((a,b)=>a+b[2],0)+32;
 const height=160+items.length*37;
 const draw=kfsMgramTableCanvas.toString()
  .replace("__COLS__",JSON.stringify(cols))
  .replace("__ROWS__",JSON.stringify(items))
  .replace("__W__",String(width)).replace("__H__",String(height))
  .replace("__TITLE__",JSON.stringify("KFS MÉTÉO  /  "+city+"  /  "+model))
  .replace("__SUBTITLE__",JSON.stringify(date+"  ·  Heure de Paris  ·  Données heure par heure"));
 return {width,height,format:"png",version:"2",devicePixelRatio:1,
  backgroundColor:"#f0f5fc",
  chart:'{type:"bar",data:{labels:[],datasets:[]},options:{responsive:false,animation:false,'+
   'legend:{display:false},tooltips:{enabled:false},scales:{xAxes:[{display:false}],yAxes:[{display:false}]}},'+
   'plugins:[{beforeDraw:'+draw+'}]}'
 };
}
function kfsMgramFallbackTable(rows,model,city,date){
 const cols=KFS_MGRAM_TABLE_COLS,records=kfsMgramTableRows(rows);
 return {data:{title:"KFS MÉTÉO / "+city+" / "+model+" / "+date+
  " (indices non calibres)",columns:cols.map(c=>({title:c[0],dataIndex:c[1],width:c[2],
  align:"center"})),dataSource:records.map(row=>Object.fromEntries(cols.map(c=>[c[1],row[c[1]]])))},
  options:{cellHeight:37,cellWidth:90,fontFamily:"Arial",offsetTop:25,offsetLeft:7,
   backgroundColor:"#e8f1fb",paddingHorizontal:12,paddingVertical:12}};
}
async function kfsMgramTablePng(rows,model,city,date){
 try{return await kfsRenderEnsembleChart(kfsMgramTableChart(rows,model,city,date));}
 catch(e){console.warn("KFS_MGRAM_TABLE_RICH_FAIL",String(e).slice(0,220));}
 const r=await fetch("https://quickchart.io/v1/table",{
  method:"POST",headers:{"content-type":"application/json"},
  body:JSON.stringify(kfsMgramFallbackTable(rows,model,city,date)),
  signal:AbortSignal.timeout(23000)});
 if(!r.ok)throw Error("Rendu tableau QuickChart HTTP "+r.status);
 const bytes=await r.arrayBuffer(),s=new Uint8Array(bytes,0,Math.min(bytes.byteLength,8));
 if(bytes.byteLength<2500||bytes.byteLength>7*1024*1024||
    s[0]!==137||s[1]!==80||s[2]!==78||s[3]!==71)
  throw Error("Le tableau PNG retourné est invalide");
 return bytes;
}
