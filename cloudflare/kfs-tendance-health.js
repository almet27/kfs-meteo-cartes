/* KFS MÉTÉO — diagnostic public minimal, sans jeton ni contenu Discord.
   Sert à vérifier que le bulletin automatique /tendance a été publié.
*/
async function kfsTendanceHealth(env){
  const now=new Date(),local=kfsParisTime(now);
  const stamp=local.year+local.month+local.day;
  const result={ok:true,date_paris:local.year+"-"+local.month+"-"+local.day,
    checked_utc:now.toISOString(),maps_generated_utc:null,
    published_morning:false,published_evening:false,discord_check:"unknown"};
  try{
    const response=await fetch(KFS_TENDANCE_REPO+"tendance-cartes.json?check="+Date.now(),{cache:"no-store"});
    if(response.ok){
      const doc=await response.json();
      if(typeof doc.generated_utc==="string")result.maps_generated_utc=doc.generated_utc;
      if(typeof doc.source_generated_utc==="string")result.maps_source_utc=doc.source_generated_utc;
    }else result.map_source="unavailable";
  }catch(_){result.map_source="unavailable";}
  try{
    const me=await kfsDiscordCall(env,"/users/@me");
    const messages=await kfsDiscordCall(env,"/channels/"+KFS_TENDANCE_CHANNEL+"/messages?limit=100");
    const mine=messages.filter(m=>m.author?.id===me.id).map(m=>String(m.content||""));
    result.published_morning=mine.some(s=>s.includes("KFS-TENDANCE-QUOTIDIENNE-"+stamp+"-MATIN-COMPLETE"));
    result.published_evening=mine.some(s=>s.includes("KFS-TENDANCE-QUOTIDIENNE-"+stamp+"-SOIR-COMPLETE"));
    result.discord_check="ok";
  }catch(_){result.discord_check="unavailable";}
  return new Response(JSON.stringify(result),{
    headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}});
}
