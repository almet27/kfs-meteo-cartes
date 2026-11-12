// KFS /meteogramme : coloured hourly table PNG. Add to main module.
const KFS_MGRAM_TABLE_COLS=[
 ["Heure","time",79],["Temps","weather",76],["Temp °C","temp",91],
 ["Humid %","humidity",88],["Pluie mm","rain",90],["Neige cm","snow",95],
 ["Vent","direction",104],["Moy km/h","wind",93],["Raf km/h","gust",97],
 ["Press hPa","pressure",103],["CAPE","cape",88],
 ["Orage idx","storm",93],["Intensite","strength",104],
 ["Neige idx","snowRisk",91],["Graupel idx","graupel",91]
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
function kfsMgramTableColor(key,v,i){
 const neutral=i%2?"#f5faff":"#e8f1fb";
 if(!Number.isFinite(v))return neutral;
 if(key==="temp")return v<0?"#b8d8ff":v<5?"#9feaf6":v<12?"#b7f5d2":v<20?"#f6f2a7":"#ffc7a0";
 if(key==="humidity")return v>=90?"#8bbce6":v>=70?"#add5f1":v>=45?"#d2e9fa":"#f0f6fd";
 if(key==="rain")return v>=8?"#3b77c0":v>=3?"#6aa9de":v>=.5?"#b7ddf5":v>0?"#d8effc":"#f1f7fc";
 if(key==="snow")return v>=3?"#83b9df":v>=.5?"#c8e9fa":v>0?"#e0f6ff":"#f4f9fd";
 if(key==="wind"||key==="gust")return v>=80?"#ef9d9e":v>=50?"#ffcf9c":v>=25?"#b5ebd7":"#d9f3e8";
 if(key==="cape")return v>=1800?"#f1a7a7":v>=800?"#ffd59f":v>=150?"#fff1be":"#f5f7fc";
 if(key==="storm"||key==="snowRisk"||key==="graupel")return v>=70?"#f6a5a6":v>=40?"#ffd3a0":v>=15?"#fff0ae":"#e8f5e9";
 return neutral;
}
function kfsMgramTableChart(rows,model,city,date){
 const columns=KFS_MGRAM_TABLE_COLS.filter(c=>c[1]!=="time");
 const display=kfsMgramTableRows(rows.slice(0,27));
 const xs=columns.map(c=>c[0]),ys=display.map(r=>r.time);
 const data=[],colors=[];
 display.forEach((row,j)=>columns.forEach((col,i)=>{
   const key=col[1];
   data.push({x:xs[i],y:ys[j],v:j*columns.length+i,txt:row[key]});
   colors.push(kfsMgramTableColor(key,row._values[key],j));
 }));
 const width=1640,height=Math.max(410,rows.length*40+185);
 const chart='{type:"matrix",data:{datasets:[{data:'+JSON.stringify(data)+
  ',borderColor:"#edf4fc",borderWidth:1,backgroundColor:'+JSON.stringify(colors)+
  ',width:105,height:35}]},options:{responsive:false,layout:{padding:12},'+
  'scales:{x:{type:"category",labels:'+JSON.stringify(xs)+
  ',offset:true,position:"top",ticks:{color:"#233a62",font:{size:13,weight:"bold"},maxRotation:0,autoSkip:false},grid:{display:false}},'+
  'y:{type:"category",labels:'+JSON.stringify(ys)+
  ',offset:true,reverse:true,ticks:{color:"#233a62",font:{size:14,weight:"bold"},autoSkip:false},grid:{display:false}}},'+
  'plugins:{title:{display:true,text:'+JSON.stringify("KFS MÉTÉO  •  "+city+"  •  "+model)+
  ',color:"#172947",font:{size:25,weight:"bold"},padding:18},'+
  'subtitle:{display:true,text:'+JSON.stringify(date+" · Heure de Paris · Pluie/neige horaires · Vent: direction d'origine")+
  ',color:"#617597",font:{size:15},padding:12},'+
  'legend:{display:false},datalabels:{display:true,color:"#172947",'+
  'font:{size:14,weight:"bold"},formatter:function(value){return value.txt;}}}}}';
 return {version:"4",width,height,format:"png",devicePixelRatio:1,
    backgroundColor:"#f0f5fc",chart};
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
