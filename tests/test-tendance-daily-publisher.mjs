import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const src=fs.readFileSync("cloudflare/kfs-tendance-daily-publisher.js","utf8");
const messages=[], sent=[];
const paris=d=>Object.fromEntries(new Intl.DateTimeFormat("en-GB",{
  timeZone:"Europe/Paris",weekday:"short",year:"numeric",month:"2-digit",day:"2-digit",
  hour:"2-digit",minute:"2-digit",hourCycle:"h23"
}).formatToParts(d).map(p=>[p.type,p.value]));
const manifest={schema_version:1,status:"illustrative_model_maps",
  generated_utc:"2026-11-11T07:45:00Z",
  source_generated_utc:"2026-11-11T07:37:00Z",
  period_maps:[["j3",72],["j7",168],["j10",240],["j15",360]].map(([id,step])=>
    ({id,step_h:step,size_bytes:120000,
    image_url:"https://almet27.github.io/kfs-meteo-cartes/forecast-maps/tendance/tendance-carte-"+id+".png"}))
};
const ctx=vm.createContext({
  Date,Intl,Math,Number,console,
  KFS_TENDANCE_REPO:"https://example.com/tendance/",
  KFS_TENDANCE_CHANNEL:"12345",
  kfsParisTime:paris,
  fetch:async()=>new Response(JSON.stringify(manifest),{status:200}),
  kfsDiscordCall:async(_env,path,method="GET",payload)=>{
    if(path.includes("/users/@me"))return {id:"me"};
    if(method==="GET"&&path.includes("/messages?"))return messages;
    if(method==="POST"){
      messages.unshift({author:{id:"me"},content:payload.content});
      return {id:"sent"+messages.length};
    }
    throw Error("Unrecognized "+path+" "+method);
  },
  kfsPostTendanceMapToChannel:async(_env,src,index,total,key)=>{
    sent.push({src:src.id,index,total,key});
    messages.unshift({author:{id:"me"},content:key});
  },
  Response
});
vm.runInContext(src,ctx);
const execute=(date)=>vm.runInContext('kfsTendanceDailyPublish({DISCORD_BOT_TOKEN:"fake"},'+JSON.stringify(date)+')',ctx);
await execute("2026-11-11T07:50:00Z");
assert.equal(sent.length,4,"Four images should publish");
assert.ok(messages[0].content.includes("-COMPLETE"),"Missing completion marker");
await execute("2026-11-11T07:55:00Z");
assert.equal(sent.length,4,"Must not duplicate published images");
manifest.generated_utc="2026-11-10T20:30:00Z";
await execute("2026-11-11T08:00:00Z");
assert.equal(sent.length,4,"Stale manifest must not publish");
assert.equal(vm.runInContext('kfsTendanceDailyWindow(kfsParisTime(new Date("2026-11-15T20:10:00Z")))',ctx),null,"Sunday evening is reserved to weekly bulletin");
console.log("KFS daily tendency scheduler: four maps, idempotence, stale guard, Sunday exclusion — PASSED");
