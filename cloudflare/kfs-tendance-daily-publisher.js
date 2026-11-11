/* KFS METEO — publication quotidienne de /tendance en complément du dimanche.
   Fonction appelée par le déclenchement récurrent Cloudflare toutes les cinq minutes.
   Une publication par période matin (après 08:30 Paris) / soir (après 21:00 Paris),
   et seulement pour les cartes fraîchement produites par GitHub Actions.
*/
function kfsTendanceDailyWindow(time) {
  const hour=Number(time.hour),minute=Number(time.minute);
  if((hour===8&&minute>=30)||hour===9||hour===10)return "matin";
  if(time.weekday!=="Sun"&&(hour===21||hour===22))return "soir";
  return null;
}
function kfsTendanceDailyFresh(m,now,slot){
  if(!m||m.schema_version!==1||m.status!=="illustrative_model_maps"||
     !Array.isArray(m.period_maps)||m.period_maps.length!==4)return false;
  const dt=new Date(m.generated_utc);
  if(!Number.isFinite(dt.getTime())||dt.getTime()>now.getTime()+600000||
     now.getTime()-dt.getTime()>5*3600000)return false;
  const local=kfsParisTime(dt),current=kfsParisTime(now);
  if(local.year!==current.year||local.month!==current.month||local.day!==current.day)return false;
  const h=Number(local.hour),min=Number(local.minute);
  if(slot==="matin"&&(h<8||(h===8&&min<20)))return false;
  if(slot==="soir"&&h<20)return false;
  return [["j3",72],["j7",168],["j10",240],["j15",360]].every(([id,step])=>{
    const src=m.period_maps.find(x=>x.id===id);
    return !!src&&src.step_h===step&&src.size_bytes>=15000&&
      src.image_url==="https://almet27.github.io/kfs-meteo-cartes/forecast-maps/tendance/tendance-carte-"+id+".png";
  });
}
async function kfsTendanceDailyPublish(env,scheduledAt){
  const now=new Date(scheduledAt||Date.now()),time=kfsParisTime(now);
  const slot=kfsTendanceDailyWindow(time);
  if(!slot||!env.DISCORD_BOT_TOKEN)return;
  const res=await fetch(KFS_TENDANCE_REPO+"tendance-cartes.json?check="+
    encodeURIComponent(time.year+"-"+time.month+"-"+time.day+"-"+slot),{cache:"no-store"});
  if(!res.ok)throw Error("KFS tendance quotidienne : manifeste GitHub HTTP "+res.status);
  const manifest=await res.json();
  if(!kfsTendanceDailyFresh(manifest,now,slot)){
    console.log("KFS_TENDANCE_DAILY_WAIT_NEW_MAPS",slot,manifest?.generated_utc);
    return;
  }
  const stamp=time.year+time.month+time.day;
  const marker="KFS-TENDANCE-QUOTIDIENNE-"+stamp+"-"+slot.toUpperCase();
  const me=await kfsDiscordCall(env,"/users/@me");
  const history=await kfsDiscordCall(env,"/channels/"+KFS_TENDANCE_CHANNEL+"/messages?limit=100");
  const sentByBot=history.filter(m=>m.author?.id===me.id).map(m=>String(m.content||""));
  if(sentByBot.some(s=>s.includes(marker+"-COMPLETE"))){
    console.log("KFS_TENDANCE_DAILY_ALREADY_PUBLISHED",marker);return;
  }
  const cards=[["j3",72],["j7",168],["j10",240],["j15",360]];
  for(let i=0;i<cards.length;i++){
    const id=cards[i][0],piece=marker+"-"+id.toUpperCase();
    if(sentByBot.some(s=>s.includes(piece)))continue;
    const card=manifest.period_maps.find(x=>x.id===id);
    await kfsPostTendanceMapToChannel(env,card,i+1,cards.length,piece);
  }
  const stampFr=new Date(manifest.generated_utc).toLocaleString("fr-FR",{
    timeZone:"Europe/Paris",dateStyle:"short",timeStyle:"short"
  });
  await kfsDiscordCall(env,"/channels/"+KFS_TENDANCE_CHANNEL+"/messages","POST",{
    content:"✅ **KFS MÉTÉO — Tendance du "+(slot==="matin"?"matin":"soir")+" publiée**\n"+
      "Échéances J+3, J+7, J+10 et J+15. Dernière génération : **"+stampFr+
      "** (Paris). Sources des modèles précisées sur les cartes.\n_"+marker+"-COMPLETE_",
    allowed_mentions:{parse:[]}
  });
  console.log("KFS_TENDANCE_DAILY_PUBLISHED",marker);
}
