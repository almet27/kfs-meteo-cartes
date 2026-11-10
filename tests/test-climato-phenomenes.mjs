import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const code=fs.readFileSync("cloudflare/kfs-climato-phenomenes.js","utf8");
const sandbox={
  console,fetch,Request,Response,TextDecoder,DecompressionStream,Date,Math,Number,Set,Map,
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
console.log("KFS CLIMATO PHENOMENES: TESTS PASSED");
