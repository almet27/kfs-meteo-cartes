// KFS MÉTÉO /strato — cartes natives ECMWF IFS depuis GitHub Pages.
// Aucun appel à Open-Meteo ni à une API payante. Fichiers calculés par GitHub Actions.
// Priorité au CDN GitHub brut : GitHub Pages peut être désactivé (HTTP 404).
// jsDelivr est un miroir indépendant, Pages reste un dernier secours.
const KFS_STRATO_BASES = [
  "https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/",
  "https://cdn.jsdelivr.net/gh/almet27/kfs-meteo-cartes@main/",
  "https://almet27.github.io/kfs-meteo-cartes/"
];
async function kfsStratoRead(path, version, format) {
  const errors = [];
  for (const base of KFS_STRATO_BASES) {
    try {
      const res = await fetch(base + path + "?kfs=" + encodeURIComponent(String(version)), {
        cache: "no-store",
        signal: AbortSignal.timeout(format === "png" ? 18000 : 11000)
      });
      if (!res.ok) throw Error("HTTP " + res.status);
      if (format === "json") {
        const data = await res.json();
        if (!data || data.model !== "ifs" ||
            !data.run_utc || !data.maps || !data.maps["10"])
          throw Error("Catalogue incomplet ou non conforme");
        return data;
      }
      const bytes = await res.arrayBuffer();
      const sig = new Uint8Array(bytes, 0, Math.min(bytes.byteLength, 8));
      if (bytes.byteLength < 4000 || bytes.byteLength > 8 * 1024 * 1024 ||
          sig[0] !== 137 || sig[1] !== 80 || sig[2] !== 78 || sig[3] !== 71)
        throw Error("Données reçues non PNG");
      return bytes;
    } catch (e) {
      const host = new URL(base).hostname;
      const err = String(e?.message || e).slice(0, 75);
      errors.push(host + ": " + err);
      console.warn("KFS_STRATO_FALLBACK", host, err);
    }
  }
  throw Error("Catalogue/cartes indisponibles sur les trois sources : " +
    errors.join(" ; ").slice(0, 310));
}

const KFS_STRATO_LEVELS = [10, 50, 100];
const KFS_STRATO_HOURS = [24, 72, 120, 168, 240, 360];
let KFS_STRATO_SYNCED = false;

async function kfsStratoRegister(env) {
  if (!env.DISCORD_BOT_TOKEN) throw Error("Jeton Discord absent");
  const endpoint = "https://discord.com/api/v10/applications/" +
    APPLICATION_ID + "/commands";
  const headers = {
    "Authorization": "Bot " + env.DISCORD_BOT_TOKEN,
    "content-type": "application/json"
  };
  const cmd = {
    name: "strato",
    type: 1,
    description: "Stratosphère nord : température, vents et vortex polaire (ECMWF IFS, J+15)",
    options: [
      {
        name: "niveau", type: 4, required: false,
        description: "Niveau stratosphérique (10 hPa par défaut)",
        choices: [
          {name: "10 hPa · ~30 km", value: 10},
          {name: "50 hPa · ~20 km", value: 50},
          {name: "100 hPa · ~16 km", value: 100}
        ]
      },
      {
        name: "carte", type: 3, required: false,
        description: "Température ou vitesse du vent et contours du vortex",
        choices: [
          {name: "Vortex polaire / vents", value: "vortex"},
          {name: "Température stratosphérique", value: "temperature"}
        ]
      },
      {
        name: "echeance", type: 4, required: false,
        description: "Échéance de prévision (72 h par défaut)",
        choices: KFS_STRATO_HOURS.map(h => ({
          name: "J+" + (h / 24) + " · " + h + " h", value: h
        }))
      }
    ]
  };
  const list = await fetch(endpoint, {
    headers: {Authorization: headers.Authorization},
    signal: AbortSignal.timeout(12000)
  });
  if (!list.ok) throw Error("Lecture commandes Discord HTTP " + list.status);
  const registered = await list.json();
  // Empêche les POST répétitifs à chaque exécution des triggers Cloudflare.
  const existing = Array.isArray(registered) ?
    registered.find(c => c.name === "strato" && c.type === 1) : null;
  if (existing) return {registered: true, changed: false};
  const post = await fetch(endpoint, {
    method: "POST", headers, body: JSON.stringify(cmd),
    signal: AbortSignal.timeout(12000)
  });
  if (!post.ok) throw Error("Enregistrement /strato HTTP " + post.status +
    " " + (await post.text()).slice(0, 160));
  console.log("KFS_STRATO_REGISTERED");
  return {registered: true, changed: true};
}

async function kfsStratoEdit(interaction, payload, file) {
  const url = "https://discord.com/api/v10/webhooks/" +
    APPLICATION_ID + "/" + interaction.token + "/messages/@original";
  let body, headers = {};
  if (file) {
    const form = new FormData();
    form.append("payload_json", JSON.stringify({
      ...payload, attachments: [{
        id: 0, filename: file.name,
        description: "KFS MÉTÉO - carte stratosphérique ECMWF IFS"
      }]
    }));
    form.append("files[0]", new Blob([file.bytes], {type: "image/png"}), file.name);
    body = form;
  } else {
    headers["content-type"] = "application/json";
    body = JSON.stringify(payload);
  }
  const res = await fetch(url, {
    method: "PATCH", headers, body,
    signal: AbortSignal.timeout(25000)
  });
  if (!res.ok) throw Error("Publication Discord HTTP " + res.status +
    " " + (await res.text()).slice(0, 170));
}

async function kfsStratoComplete(interaction, level, kind, hours) {
  try {
    if (!KFS_STRATO_LEVELS.includes(level) ||
        !["temperature", "vortex"].includes(kind) ||
        !KFS_STRATO_HOURS.includes(hours))
      throw Error("Paramètres /strato invalides");
    const m = await kfsStratoRead("strato/metadata.json", Math.floor(Date.now() / 300000), "json");
    const stamp = Date.parse(m.run_utc || "");
    if (m.model !== "ifs" || !Number.isFinite(stamp) ||
        stamp > Date.now() + 3600000 || Date.now() - stamp > 48 * 3600000)
      throw Error("Run stratosphérique absent, ancien ou non vérifié.");
    const path = m.maps?.[String(level)]?.[String(hours)]?.[kind];
    const expected = "strato/ifs-h" + String(hours).padStart(3, "0") +
      "-" + level + "hpa-" + kind + ".png";
    if (path !== expected)
      throw Error("Carte non calculée pour ce niveau ou cette échéance.");
    const bytes = await kfsStratoRead(path, m.run_utc, "png");
    const target = new Date(stamp + hours * 3600000);
    const fmt = date => new Intl.DateTimeFormat("fr-FR", {
      timeZone: "Europe/Paris", day: "2-digit", month: "2-digit",
      year: "numeric", hour: "2-digit", minute: "2-digit"
    }).format(date);
    const approx = {10: "~30 km", 50: "~20 km", 100: "~16 km"}[level];
    const title = kind === "vortex" ?
      "vitesse du vent et géopotentiel du vortex" : "température";
    let msg = "🌀 **KFS MÉTÉO — STRATOSPHÈRE NORD**\n" +
      "**ECMWF IFS** · **" + level + " hPa** (" + approx + ") · " +
      "**J+" + (hours / 24) + "**\n" +
      "🗺️ " + title + " · validité **" + fmt(target) + "**\n" +
      "🔄 Run " + new Date(stamp).toISOString().slice(0, 16).replace("T", " ") +
      " UTC";
    if (level === 10) {
      const wind = Number(m.zonal_wind_10hpa_60n?.[String(hours)]);
      if (Number.isFinite(wind)) {
        const direction = wind < 0 ? "vents d'est (inversion)" :
          "vents d'ouest";
        msg += "\n🌬️ Vent zonal moyen 60°N / 10 hPa : **" +
          (wind > 0 ? "+" : "") + wind.toFixed(1) + " m/s** · " + direction;
        if (wind < 0)
          msg += "\n⚠️ Inversion à cette échéance : **un seul point " +
            "de prévision ne confirme pas un SSW majeur.**";
      }
    }
    msg += "\n*Données : ECMWF Open Data CC BY 4.0 · " +
      "Carte native calculée à partir des champs du modèle.*";
    await kfsStratoEdit(interaction,
      {content: msg, allowed_mentions: {parse: []}},
      {name: "kfs-strato-" + level + "hpa-j" + (hours / 24) +
        "-" + kind + ".png", bytes});
  } catch (error) {
    console.error("KFS_STRATO_ERROR", String(error));
    await kfsStratoEdit(interaction, {
      content: "⚠️ **KFS MÉTÉO /strato** : " +
        String(error?.message || error).slice(0, 330) +
        "\nAucune donnée météorologique fictive n'a été générée.",
      allowed_mentions: {parse: []}
    }).catch(e => console.error("KFS_STRATO_REPLY_ERROR", String(e)));
  }
}
