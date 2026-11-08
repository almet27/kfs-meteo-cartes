"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const code=fs.readFileSync("worker/kfs-meteo-worker-foudre-periodes-live-wu.js","utf8");
const start=code.indexOf("// === /cartes : accès direct");
const stop=code.indexOf("async function registerLiveCommand(env){",start);
assert(start>=0&&stop>start,"Bloc /cartes introuvable");
const calls=[];
const api=vm.runInNewContext(
  code.slice(start,stop)+"\n({CARTES_METEOCIEL_ZONES,CARTES_METEOCIEL_TYPES,cartesMeteocielPage,cartesMeteocielResponse,registerCartesCommand})",
  {URL,APPLICATION_ID:"APP_TEST",fetch:async (url,opts)=>{
    calls.push({url,opts});
    return {ok:true,status:200,text:async()=>"OK"};
  }}
);

assert.equal(api.CARTES_METEOCIEL_ZONES.length,21);
assert.equal(api.CARTES_METEOCIEL_TYPES.length,7);
assert(new Set(api.CARTES_METEOCIEL_ZONES.map(x=>x[0])).size===21);
assert(new Set(api.CARTES_METEOCIEL_TYPES.map(x=>x.id)).size===7);
const expectedPaths={
  temperature:"temperatures.php",
  tmax:"tmaxi.php",tmin:"tmini.php",vent:"vent.php",
  rafales:"vent-rafales.php",rafalesmax:"vent-rafales.php",pluie:"rr.php"
};
for(const [zone] of api.CARTES_METEOCIEL_ZONES) {
  for(const metric of api.CARTES_METEOCIEL_TYPES) {
    const selected=api.cartesMeteocielPage(zone,metric.id);
    assert(selected,"Sélection manquante");
    const url=new URL(selected.url);
    assert.equal(url.origin,"https://www.meteociel.fr");
    assert.equal(url.pathname,"/observations-meteo/"+expectedPaths[metric.id]);
    assert.equal(url.searchParams.get("region"),zone);
    assert.equal(url.searchParams.get("archive"),null);
    if(metric.id==="tmax"||metric.id==="tmin") {
      assert.equal(url.searchParams.get("prov"),"1");
    }
    if(metric.id==="rafales") assert.equal(url.searchParams.get("mode"),"0");
    if(metric.id==="rafalesmax") assert.equal(url.searchParams.get("mode"),"2");
    assert.equal(api.cartesMeteocielResponse(zone,metric.id).type,4);
  }
}
assert.equal(api.cartesMeteocielPage("bad","temperature"),null);
assert.equal(api.cartesMeteocielPage("fr","not-a-type"),null);
const sample=api.cartesMeteocielResponse("r14","rafalesmax");
assert(sample.data.content.includes("Normandie"));
assert(sample.data.content.includes("Rafales maximales sur 24 h glissantes"));
assert.equal(sample.data.components[0].components[0].style,5);
assert.equal(sample.data.components[0].components[0].url,
  api.cartesMeteocielPage("r14","rafalesmax").url);
assert.equal(sample.data.allowed_mentions.parse.length,0);
assert(!JSON.stringify(sample).includes('"image"'),"Image tierce non autorisée");

const otherRoutes=[
  'async function complete(', 'async function completeLive(',
  'async function completeRadar(', 'async function completeFoudre('
];
for(const route of otherRoutes) assert(code.includes(route),"Route supprimée : "+route);
assert(code.includes('url.pathname==="/register-cartes"'));
assert(code.includes('interaction.data?.name==="cartes"'));
assert(code.includes('registerCartesCommand(env)'));
assert(!code.includes("KFS radar : déclenchement Cron inattendu, ignoré."));

(async()=>{
  await api.registerCartesCommand({DISCORD_BOT_TOKEN:"FAKE_TOKEN"});
  assert.equal(calls.length,1);
  assert.equal(calls[0].opts.method,"POST");
  assert.equal(calls[0].url,"https://discord.com/api/v10/applications/APP_TEST/commands");
  const cmd=JSON.parse(calls[0].opts.body);
  assert.equal(cmd.name,"cartes");
  assert.equal(cmd.options.length,2);
  assert.equal(cmd.options[0].choices.length,21);
  assert.equal(cmd.options[1].choices.length,7);
  assert(cmd.options[0].choices.length<=25);
  assert(cmd.options[1].choices.length<=25);
  assert(cmd.options.every(x=>x.required===true));
  console.log("OK /cartes : 21 zones, 7 mesures, 147 URL vérifiées, lien Discord et enregistrement.");
})().catch(e=>{console.error(e);process.exitCode=1});
