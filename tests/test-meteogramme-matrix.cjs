const assert=require("node:assert/strict");
(async()=>{
 const labelsX=["Temps","Temp","Pluie","CAPE","Orage"];
 const labelsY=["12:00","13:00","14:00"];
 const values=labelsY.flatMap((y,i)=>labelsX.map((x,j)=>({
   x,y,v:i*10+j,
   txt:j===0?"☀":j===1?(10+i)+"°":j===2?i+" mm":j===3?100*i+"":"55",
   color:j===0?"#d4edfe":j===1?"#b4f0bd":j===2?"#94c8f0":j===3?"#ffe0a0":"#ffc8a0"
 })));
 const chart='{type:"matrix",data:{datasets:[{data:'+JSON.stringify(values)+
   ',borderWidth:1,borderColor:"#e1eafa",backgroundColor:function(ctx){return ctx.raw.color;},'+
   'width:80,height:46}]},options:{layout:{padding:12},scales:{'+
   'x:{type:"category",labels:'+JSON.stringify(labelsX)+',offset:true,position:"top",'+
   'ticks:{color:"#172947",font:{size:14}},grid:{display:false}},'+
   'y:{type:"category",labels:'+JSON.stringify(labelsY)+',offset:true,reverse:true,'+
   'ticks:{color:"#172947",font:{size:14}},grid:{display:false}}},'+
   'plugins:{legend:{display:false},datalabels:{display:true,color:"#172947",'+
   'font:{size:14,weight:"bold"},formatter:function(value){return value.txt;}}}}';
 const req={version:"4",width:620,height:290,devicePixelRatio:1,format:"png",
   backgroundColor:"#f1f7ff",chart};
 const response=await fetch("https://quickchart.io/chart",{method:"POST",
    headers:{"content-type":"application/json"},body:JSON.stringify(req),
    signal:AbortSignal.timeout(25000)});
 const data=Buffer.from(await response.arrayBuffer()),err=response.headers.get("x-quickchart-error");
 console.log("MATRIX_HTTP",response.status,"ERROR",err||"none","BYTES",data.length);
 assert(response.ok,err);
 assert(!err,"QuickChart error: "+err);
 assert(data.length>2800);
 assert(data.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])));
 console.log("MATRIX_PNG_OK",data.readUInt32BE(16),data.readUInt32BE(20));
})().catch(e=>{console.error(e);process.exitCode=1});
