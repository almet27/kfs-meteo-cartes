import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const code=fs.readFileSync("cloudflare/kfs-climato-phenomenes.js","utf8");
let snowApiCalls=0;
const countedFetch=(input,options)=>{
  if(String(input).includes("archive-api.open-meteo.com"))snowApiCalls++;
  return fetch(input,options);
};
const sandbox={
  console,fetch:countedFetch,Request,Response,URLSearchParams,TextDecoder,DecompressionStream,Date,Math,Number,Set,Map,
  caches:{default:{match:async()=>null,put:async()=>{}}},
  KFS_Q_BASE:"https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/BASE/QUOT/",
  kfsQFilename:(id,year)=>{
    const p=year<1950?"before-1949":year<=2024?"previous-1950-2024":"latest-2025-2026";
    return "Q_"+id.slice(0,2)+"_"+p+"_RR-T-Vent.csv.gz";
  },
  kfsQDate:(s)=> /^\d{8}$/.test(s)?s.slice(0,4)+"-"+s.slice(4,6)+"-"+s.slice(6,8):null,
  kfsQNumber:(x)=>x===null||x===undefined||String(x).trim()===""?null:Number(x),
  kfsQCalendarDate:x=>x,
  kfsQR:(x,s="")=>String(x)+s,
  kfsClimStations:async()=>[],
  kfsClimDistance:()=>0,
  KFS_Q_MONTHS:["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"]
};
const context=vm.createContext(sandbox);
vm.runInContext(code,context);
assert.equal(vm.runInContext("kfsPValid('1','9')",context),1);
assert.equal(vm.runInContext("kfsPValid('1','1')",context),1);
assert.equal(vm.runInContext("kfsPValid('1','2')",context),null);
assert.equal(vm.runInContext("kfsPValid('', '1')",context),null);
for(const [year,expectedOrage,expectedNeige] of [[2024,20,7],[2025,14,4]]) {
  const data=await vm.runInContext(
    "kfsPArchive([{id:'27347001'}],"+year+")",context
  );
  const days=data.byStation["27347001"];
  const orage=days.filter(d=>d.orage===1).length;
  const neige=days.filter(d=>d.neige===1).length;
  const validOrage=days.filter(d=>d.orage===0||d.orage===1).length;
  const validNeige=days.filter(d=>d.neige===0||d.neige===1).length;
  console.log(JSON.stringify({station:"EVREUX-HUEST",year,orage,neige,validOrage,validNeige,filename:data.filename}));
  assert.equal(orage,expectedOrage);
  assert.equal(neige,expectedNeige);
  assert.ok(validOrage>=365,"Orage coverage insufficient");
  assert.ok(validNeige>=364,"Snow coverage insufficient");
}
for(const [year,minimum,maximum] of [[2024,8.8,9.1],[2025,2.8,3.1]]){
  const report=await vm.runInContext("kfsPLocalSnowReport({name:'L\\'Aigle',lat:48.765,lon:0.626},"+year+",0)",context);
  assert.equal(report.embeds.length,1);
  const embed=report.embeds[0];
  const field=embed.fields.find(f=>f.name.includes("Épaisseur maximale au sol"));
  assert.ok(field,"Missing local snow-depth field");
  const m=field.value.match(/([0-9.]+) cm/);
  assert.ok(m,"Missing cm unit in model output");
  assert.ok(Number(m[1])>=minimum&&Number(m[1])<=maximum,"Unexpected L'Aigle snow depth "+m[1]);
  assert.ok(embed.description.includes("Estimation locale"),"Must flag model data");
  assert.ok(!embed.description.includes("Évreux"),"Must not attribute distant measurements");
  console.log(JSON.stringify({city:"L'Aigle",year,depth:field.value,fields:embed.fields.length}));
}
assert.equal(snowApiCalls,2,"One Open-Meteo request per historical year is required");
const throttled=vm.createContext({...sandbox,
  fetch:async(input)=>String(input).includes("open-meteo.com")
    ?new Response("quota exceeded",{status:429})
    :fetch(input)
});
vm.runInContext(code,throttled);
const fallback=await vm.runInContext("kfsPLocalSnowReport({name:'L\\'Aigle',lat:48.765,lon:0.626},2024,0)",throttled);
assert.ok(fallback.embeds[0].description.includes("temporairement indisponible"));
assert.ok(fallback.embeds[0].description.includes("429"));
assert.ok(!fallback.embeds[0].description.includes("station sélectionnée"));
assert.ok(fallback.embeds[0].fields[0].value.includes("Aucune station distante"));
console.log("ERA5-Land HTTP 429 handled without false snow values");

console.log("KFS CLIMATO PHENOMENES: TESTS PASSED");
