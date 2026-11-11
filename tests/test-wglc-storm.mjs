import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source=fs.readFileSync("cloudflare/kfs-climato-foudre-wglc.js","utf8");
const seen=[];
const sandbox={
  console,Response,Request,DecompressionStream,TextDecoder,Intl,Math,Date,
  fetch:async url=>{
    const match=String(url).match(/wglc_france_(\d{4})\.json\.gz$/);
    assert.ok(match,"archive path was unexpected");
    seen.push(Number(match[1]));
    const path="data/wglc/wglc_france_"+match[1]+".json.gz";
    if(!fs.existsSync(path))return new Response("",{status:404});
    return new Response(fs.readFileSync(path),{status:200,headers:{"content-type":"application/octet-stream"}});
  },
  KFS_Q_MONTHS:["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"],
  kfsClimDistance:(lat1,lon1,lat2,lon2)=>{
    const R=6371,r=Math.PI/180,dl=(lat2-lat1)*r,do_=(lon2-lon1)*r;
    return 2*R*Math.asin(Math.sqrt(Math.sin(dl/2)**2+Math.cos(lat1*r)*Math.cos(lat2*r)*Math.sin(do_/2)**2));
  },
  kfsQR:(x,unit="")=>String(Math.round(Number(x)*10)/10)+unit,
  kfsPStats:()=>({jours:20,valid:365}),
  kfsPSelect:async()=>({station:{name:"EVREUX-HUEST",km:46,id:"27347001"},days:[],expected:366})
};
const ctx=vm.createContext(sandbox);
vm.runInContext(source,ctx);

for(const year of [2010,2024,2025]){
  const d=await vm.runInContext("kfsWglcArchive("+year+")",ctx);
  assert.equal(d.year,year);
  assert.equal(d.monthly.length,12);
  const p=vm.runInContext("kfsWglcCity",ctx)(d,{name:"L'Aigle",lat:48.765,lon:0.626});
  assert.ok(p,"The L'Aigle local WWLLN grid must be resolved");
  assert.ok(p.dist<=10,"Nearest cell too far");
  assert.equal(p.series.length,12);
  assert.ok(p.series.some(x=>typeof x==="number"),"No archive values");
  assert.ok(p.series.every(x=>x===null||x>=0),"Bad negative lightning density");
  console.log("WGLC",year,"L'Aigle",p.lat,p.lon,p.series,"distance",p.dist);
}

const r=await vm.runInContext("kfsWglcStormReport({name:'L\\'Aigle',lat:48.765,lon:0.626},2024,0)",ctx);
assert.equal(r.embeds.length,1);
assert.ok(r.embeds[0].fields.some(x=>x.name.includes("WWLLN")),"Missing lightning archive");
const st=r.embeds[0].fields.find(x=>x.name.includes("Météo-France"));
assert.ok(st,"Official station distinct from grid");
assert.ok(st.value.includes("Station éloignée"),"Must flag remote station");
assert.ok(!r.embeds[0].description.includes("Station EVREUX"),"Remote station must not be presented as city source");
assert.ok(r.embeds[0].footer.text.includes("CC BY-SA"),"License attribution must be present");
assert.ok(r.embeds[0].fields.some(x=>x.name.includes("par mois")),"Monthly breakdown missing");
assert.ok(seen.every(x=>[2010,2024,2025].includes(x)));
console.log("KFS /climato WGLC lightning archive tests: PASSED");
