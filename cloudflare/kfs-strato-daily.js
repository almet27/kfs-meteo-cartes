// KFS MÉTÉO – publication quotidienne de la planche vortex polaire 10 hPa.
// Ce module est intégré au script Cloudflare kfs-meteo-ia.
// Utilise le cron existant */5 * * * *, le bot Discord existant et les cartes GitHub.
// N'ajoute aucun secret ni aucune dépendance externe.
let KFS_STRATO_DAILY_RUNNING = false;
const KFS_STRATO_DAILY_FILE = "strato/ifs-10hpa-vortex-overview.png";

function kfsStratoDailySlot(scheduledTime) {
  const t = kfsParisTime(new Date(scheduledTime));
  const h = Number(t.hour), minute = Number(t.minute);
  if (!Number.isInteger(h) || h < 11 || h > 18 ||
      ![0, 30].includes(minute) || (h === 11 && minute < 30))
    return null;
  return t.year + "-" + t.month + "-" + t.day;
}

async function kfsStratoDailyAlreadySent(env, channel, marker, date) {
  // Vérifie suffisamment d'historique pour que la forte activité du bot
  // n'entraîne pas une deuxième publication dans la même journée.
  let before = "";
  const cutoff = Date.parse(date + "T00:00:00Z") - 7200000;
  for (let page = 0; page < 8; page++) {
    const query = "/channels/" + channel + "/messages?limit=100" +
      (before ? "&before=" + before : "");
    const messages = await kfsDiscordCall(env, query);
    if (!Array.isArray(messages))
      throw Error("Historique Discord indisponible : publication annulée");
    if (messages.some(m =>
      m.author?.bot && (String(m.content || "").includes(marker) ||
      (m.embeds || []).some(e => String(e.footer?.text || "").includes(marker))))) {
      return true;
    }
    if (messages.length < 100) return false;
    const oldest = messages[messages.length - 1];
    if (Date.parse(String(oldest?.timestamp || "")) < cutoff) return false;
    before = String(oldest?.id || "");
    if (!/^\d{17,20}$/.test(before))
      throw Error("Historique Discord tronqué : anti-doublon impossible");
  }
  // Ne jamais publier quand le contrôle d'unicité ne peut être garanti.
  throw Error("Historique Discord trop dense : anti-doublon non vérifiable");
}

async function kfsStratoDailyPublish(env, scheduledTime) {
  const date = kfsStratoDailySlot(scheduledTime);
  if (!date || KFS_STRATO_DAILY_RUNNING) return;
  if (!env.DISCORD_BOT_TOKEN) throw Error("Jeton Discord /strato absent");
  KFS_STRATO_DAILY_RUNNING = true;
  try {
    const channel = String(env.KFS_STRATO_CHANNEL_ID || KFS_TENDANCE_CHANNEL || "");
    if (!/^\d{17,20}$/.test(channel))
      throw Error("Salon Discord /strato invalide");
    const marker = "KFS-STRATO-DAILY-" + date;
    const metadata = await kfsStratoMetadata(false, true);
    if (metadata.model !== "ifs" ||
        metadata.run_utc !== date + "T00:00:00Z") {
      console.log("KFS_STRATO_DAILY_RUN_NOT_READY", date, metadata.run_utc);
      return;
    }
    const overview = metadata.overview_10hpa;
    if (!overview || overview.run_utc !== metadata.run_utc ||
        overview.level_hpa !== 10 ||
        overview.image !== KFS_STRATO_DAILY_FILE ||
        !Array.isArray(overview.forecast_hours) ||
        overview.forecast_hours.join(",") !== "24,72,120,168,240,360") {
      console.warn("KFS_STRATO_DAILY_OVERVIEW_NOT_READY", date);
      return;
    }
    if (await kfsStratoDailyAlreadySent(env, channel, marker, date)) {
      console.log("KFS_STRATO_DAILY_ALREADY_SENT", marker);
      return;
    }
    const png = await kfsStratoRead(overview.image, metadata.run_utc, "png");
    const filename = "KFS-vortex-polaire-" + date + ".png";
    const diagnostic = String(overview.diagnostic || "").slice(0, 220);
    const message = "🌀 **KFS MÉTÉO — VORTEX POLAIRE · POINT QUOTIDIEN**\n" +
      "📅 **" + date.split("-").reverse().join("/") + "** · ECMWF IFS **00Z**\n" +
      "🗺️ Six cartes polaires 10 hPa (J+1, J+3, J+5, J+7, J+10, J+15) " +
      "· anomalies de géopotentiel vs NOAA 1991–2020.\n" +
      "📈 Évolution des vents zonaux à 60°N jusqu'à J+15.\n" +
      "🔎 **Diagnostic :** " + (diagnostic || "Situation stratosphérique à surveiller") + "\n" +
      "⚠️ Une inversion prévue ne confirme pas un SSW majeur " +
      "et ne préjuge pas d'une vague de froid en France.\n" +
      "-# Sources : ECMWF Open Data CC BY 4.0 · NOAA NCEP/NCAR R1. " + marker;
    const form = new FormData();
    form.append("payload_json", JSON.stringify({
      content: message, allowed_mentions: {parse: []}
    }));
    form.append("files[0]", new Blob([png], {type: "image/png"}), filename);
    const resp = await fetch(
      "https://discord.com/api/v10/channels/" + channel + "/messages", {
        method: "POST",
        headers: {"Authorization": "Bot " + env.DISCORD_BOT_TOKEN},
        body: form,
        signal: AbortSignal.timeout(25000)
      });
    if (!resp.ok)
      throw Error("Discord /strato quotidien HTTP " + resp.status +
        " : " + (await resp.text()).slice(0, 200));
    const posted = await resp.json();
    console.log("KFS_STRATO_DAILY_POSTED", marker, posted.id);
  } finally {
    KFS_STRATO_DAILY_RUNNING = false;
  }
}
