const assert=require("node:assert/strict");
const fs=require("node:fs");
const root=require("node:path").resolve(__dirname,"..");
const main=fs.readFileSync(root+"/cloudflare/kfs-meteogramme-module.js","utf8");
const table=fs.readFileSync(root+"/cloudflare/kfs-meteogramme-table-module.js","utf8");
const api=new Function(main+"\n"+table+
  "\nreturn {rows:kfsMgramRows,table:kfsMgramTableChart,csv:kfsMgramCsv,cols:KFS_MGRAM_TABLE_COLS};")();
const hourly={
  time:["2026-11-12T12:00","2026-11-12T13:00","2026-11-12T14:00"],
  weather_code:[0,61,95],temperature_2m:[9,8,7],relative_humidity_2m:[55,85,92],
  is_day:[1,1,1],rain:[0,1,3],precipitation:[0,1,4],showers:[0,0,1],snowfall:[0,0,0],
  wind_speed_10m:[7,14,25],wind_gusts_10m:[13,30,50],wind_direction_10m:[40,230,270],
  pressure_msl:[1017,1014,1011],cape:[0,100,700],
  wet_bulb_temperature_2m:[4,5,4],freezing_level_height:[1500,1200,1200]
};
for(let i=3;i<24;i++){
 hourly.time.push("2026-11-12T"+String(i).padStart(2,"0")+":00");
 for(const key of Object.keys(hourly)){
   if(key!=="time")hourly[key].push(hourly[key][i%3]);
 }
}
const rows=api.rows(hourly);
assert.equal(rows.length,24);
assert.equal(rows[1].humidity,85);
const csv=api.csv(rows,"GFS","Évreux");
assert(csv.includes("humidite_pct"));
assert(csv.includes('"85"'));
assert.equal(api.cols.length,15);
const cfg=api.table(rows,"GFS","Évreux","2026-11-12");
assert(cfg.chart.includes("KFS MÉTÉO"));
const chart=new Function("return ("+cfg.chart+")")();
assert.equal(chart.type,"matrix");
assert.equal(chart.data.datasets[0].data.length,rows.length*(api.cols.length-1));
assert.equal(typeof chart.options.plugins.datalabels.formatter,"function");
console.log("LOCAL_TEST_OK","tableColumns",api.cols.length,"rows",rows.length,
  "matrixWxH",cfg.width,cfg.height,"csvCols",csv.split("\n")[0].split(";").length);

if(process.env.KFS_TEST_QUICKCHART==="1"){
  (async()=>{
    const response=await fetch("https://quickchart.io/chart",{
      method:"POST",headers:{"content-type":"application/json"},
      body:JSON.stringify(cfg),signal:AbortSignal.timeout(25000)
    });
    const buffer=Buffer.from(await response.arrayBuffer());
    const error=response.headers.get("x-quickchart-error");
    assert(response.ok,"QuickChart HTTP "+response.status+" "+error);
    assert(!error,"QuickChart error: "+error);
    assert(buffer.length>2800,"PNG returned too small: "+buffer.length);
    assert(buffer.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])));
    console.log("QUICKCHART_PNG_OK",buffer.length,buffer.readUInt32BE(16),buffer.readUInt32BE(20));
  })().catch(e=>{console.error(e);process.exitCode=1});
}
