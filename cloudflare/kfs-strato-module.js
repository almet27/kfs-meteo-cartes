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
      if (format === "json" || format === "signals") {
        const data = await res.json();
        if (format === "signals") {
          if (!data || data.model !== "ifs" || !data.run_utc ||
              data.chart !== "strato/ifs-ssw-signals.png" ||
              !data.diagnostic || !data.series)
            throw Error("Diagnostic stratwarm indisponible ou non conforme");
        } else if (!data || data.model !== "ifs" ||
            !data.run_utc || !data.maps || !data.maps["10"]) {
          throw Error("Catalogue incomplet ou non conforme");
        }
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

// En cas de catalogue Raw obsolète après une publication, consulte le dernier
// contenu via l'API GitHub. Uniquement pour les nouveaux graphiques, jamais
// pour les cartes ordinaires : on préserve le quota GitHub.
async function kfsStratoMetadata(requireWindCharts=false) {
  const m = await kfsStratoRead("strato/metadata.json",
    Math.floor(Date.now() / 300000), "json");
  if (!requireWindCharts ||
      (m.zonal_wind_charts?.comparison &&
       m.zonal_wind_series_60n?.["10"]))
    return m;
  const endpoint = "https://api.github.com/repos/almet27/kfs-meteo-cartes" +
    "/contents/strato/metadata.json?ref=main";
  const res = await fetch(endpoint, {
    headers: {
      "Accept": "application/vnd.github+json",
      "User-Agent": "KFS-Meteo-Strato"
    },
    cache: "no-store",
    signal: AbortSignal.timeout(12000)
  });
  if (!res.ok)
    throw Error("Ancien catalogue en cache ; source GitHub à jour indisponible (HTTP " +
      res.status + ").");
  const payload = await res.json();
  if (payload.encoding !== "base64" || !payload.content)
    throw Error("Catalogue GitHub API invalide.");
  const bytes = Uint8Array.from(
    atob(payload.content.replace(/\s/g, "")), c => c.charCodeAt(0));
  const fresh = JSON.parse(new TextDecoder().decode(bytes));
  if (!fresh.zonal_wind_charts?.comparison ||
      !fresh.zonal_wind_series_60n?.["10"] ||
      fresh.model !== "ifs")
    throw Error("Le catalogue actuel n'inclut pas encore les courbes zonales.");
  return fresh;
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
        description: "Cartes ou courbes des vents zonaux (60°N)",
        choices: [
          {name: "Vortex polaire / vents", value: "vortex"},
          {name: "Température stratosphérique", value: "temperature"},
          {name: "Vent zonal · courbe du niveau sélectionné", value: "vent_zonal"},
          {name: "Vent zonal · comparaison 10/50/100 hPa", value: "vent_zonal_comparaison"},
          {name: "Signaux de stratwarm · vent / T polaire / ondes", value: "signaux_stratwarm"}
        ]
      },
      {
        name: "echeance", type: 4, required: false,
        description: "Échéance pour les cartes seulement (graphiques sur J+1 à J+15)",
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
  const existingOptions = existing?.options || [];
  const carte = existingOptions.find(o => o.name === "carte");
  const choices = carte?.choices?.map(c => c.value) || [];
  if (existing && ["vent_zonal", "vent_zonal_comparaison", "signaux_stratwarm"].every(x => choices.includes(x)))
    return {registered: true, changed: false};
  const url = existing ? endpoint + "/" + existing.id : endpoint;
  const post = await fetch(url, {
    method: existing ? "PATCH" : "POST",
    headers, body: JSON.stringify(cmd),
    signal: AbortSignal.timeout(12000)
  });
  if (!post.ok) throw Error("Mise à jour /strato HTTP " + post.status +
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
    const isZonalChart = ["vent_zonal", "vent_zonal_comparaison"].includes(kind);
    if (!KFS_STRATO_LEVELS.includes(level) ||
        !["temperature", "vortex", "vent_zonal", "vent_zonal_comparaison", "signaux_stratwarm"].includes(kind) ||
        !KFS_STRATO_HOURS.includes(hours))
      throw Error("Paramètres /strato invalides");
    const m = await kfsStratoMetadata(isZonalChart);
    const stamp = Date.parse(m.run_utc || "");
    if (m.model !== "ifs" || !Number.isFinite(stamp) ||
        stamp > Date.now() + 3600000 || Date.now() - stamp > 48 * 3600000)
      throw Error("Run stratosphérique absent, ancien ou non vérifié.");
    if (kind === "signaux_stratwarm") {
      const data = await kfsStratoRead("strato/signals.json",
        Math.floor(Date.now() / 300000), "signals");
      if (data.run_utc !== m.run_utc)
        throw Error("Le diagnostic stratwarm attend encore les champs du dernier run.");
      const diagnosis = data.diagnostic;
      const series = data.series || {};
      if (!["inversion_prevue", "signaux_convergents", "surveillance",
             "pas_de_signal_marque"].includes(diagnosis.status) ||
          Object.keys(series.temperature_cap_10hpa_60_90n_c || {}).length < 12)
        throw Error("Indices de réchauffement polaire incomplets.");
      const chart = await kfsStratoRead(data.chart, data.run_utc, "png");
      const fmt = value => Number.isFinite(Number(value)) ?
        (Number(value) > 0 ? "+" : "") + Number(value).toFixed(1) : "indisponible";
      const inversions = (diagnosis.wind_inversion_hours || [])
        .filter(h => Number.isInteger(h) && h >= 24 && h <= 360);
      const firstInverse = inversions.length ? "J+" + inversions[0] / 24 : "aucune";
      const warming = diagnosis.warming_max_5d_k;
      const decel = diagnosis.deceleration_max_5d_ms;
      const wave = series.eddy_heat_flux_100hpa_60n_kms || {};
      const positiveFluxDays = Object.values(wave).filter(v => Number(v)>0).length;
      let content = "🌀 **KFS MÉTÉO — SIGNAUX PRÉCURSEURS DE STRATWARM**\n" +
        "📡 **ECMWF IFS** · hémisphère Nord · **J+1 à J+15**\n" +
        "🔄 Run **" + new Date(stamp).toISOString().slice(0,16).replace("T"," ") +
        " UTC**\n" +
        "🔎 **" + String(diagnosis.label).slice(0,100) + "**\n" +
        "🌬️ Vent zonal 10 hPa / 60°N : inversion prévue **" + firstInverse + "**\n" +
        "📉 Décélération maximale sur 5 j : **" + fmt(decel) + " m/s**\n" +
        "🌡️ Hausse maximale de T polaire (60–90°N) sur 5 j : **" +
        fmt(warming) + " °C**\n" +
        "〰️ Activité ondulatoire 100 hPa : flux v′T′ positif sur " +
        positiveFluxDays + "/15 échéances calculées (sans seuil climatologique).\n" +
        "⚠️ **Ce sont des signaux issus d'un seul modèle, pas une probabilité SSW.** " +
        "Une inversion prévue ne confirme pas un événement observé. " +
        "Le refroidissement de l'Europe n'en découle pas automatiquement.\n" +
        "*Repères d'affichage : +10 °C/5 j ou −10 m/s/5 j ; " +
        "non homologués comme critères de SSW. Source : ECMWF Open Data.*";
      await kfsStratoEdit(interaction, {
        content, allowed_mentions:{parse:[]}
      }, {
        name: "kfs-strato-signaux-stratwarm.png", bytes:chart
      });
      return;
    }
    if (isZonalChart) {
      const compare = kind === "vent_zonal_comparaison";
      const key = compare ? "comparison" : String(level);
      const expectedChart = "strato/ifs-zonal-wind-" +
        (compare ? "comparison" : level + "hpa") + ".png";
      const imagePath = m.zonal_wind_charts?.[key];
      if (imagePath !== expectedChart)
        throw Error("Graphique zonal indisponible pour ce run. " +
          "La génération quotidienne doit publier les courbes avant affichage.");
      const valuesByLevel = m.zonal_wind_series_60n || {};
      const levels = compare ? KFS_STRATO_LEVELS : [level];
      const good = levels.every(z => Object.keys(valuesByLevel[String(z)] || {}).length >= 10);
      if (!good) throw Error("Série de vent zonal trop incomplète pour une courbe.");
      const imageBytes = await kfsStratoRead(imagePath, m.run_utc, "png");
      const levelTitle = compare ? "10 / 50 / 100 hPa" : level + " hPa";
      let content = "📈 **KFS MÉTÉO — VENTS ZONAUX STRATOSPHÉRIQUES**\n" +
        "**ECMWF IFS** · **" + levelTitle + "** · **60°N** · J+1 à J+15\n" +
        "🔄 Run " + new Date(stamp).toISOString().slice(0, 16).replace("T", " ") + " UTC\n" +
        "🌬️ Vent U moyen sur les longitudes : **+** vents d'ouest · " +
        "**−** vents d'est · ligne zéro = inversion.";
      for (const z of levels) {
        const series = valuesByLevel[String(z)] || {};
        const points = Object.entries(series)
          .map(([hour, val]) => [Number(hour), Number(val)])
          .filter(([hour, val]) => Number.isFinite(hour) && Number.isFinite(val))
          .sort((a, b) => a[0] - b[0]);
        const last = points.at(-1);
        if (!last) continue;
        content += "\n• " + z + " hPa : J+" + (last[0] / 24) + " = **" +
          (last[1] > 0 ? "+" : "") + last[1].toFixed(1) + " m/s**";
        if (points.some(([, val]) => val < 0))
          content += " · inversion prévue à au moins une échéance";
      }
      const zonal10 = Object.entries(valuesByLevel["10"] || {})
        .map(([hour,val])=>({hour:Number(hour),value:Number(val)}))
        .filter(p=>Number.isFinite(p.hour)&&Number.isFinite(p.value));
      const earlyInversions = zonal10.filter(p=>p.value < 0).sort((a,b)=>a.hour-b.hour);
      if (earlyInversions.length)
        content += "\n🔎 **Signal stratwarm :** inversion à 10 hPa prévue dès J+" +
          earlyInversions[0].hour/24 + " ; vérifier aussi le réchauffement polaire et les ondes.";
      else
        content += "\n🔎 **Signal stratwarm :** surveiller tout ralentissement rapide " +
          "du 10 hPa, puis le réchauffement polaire.";
      content += "\n⚠️ Une inversion prévue isolée ne confirme pas " +
        "à elle seule un réchauffement stratosphérique majeur (SSW)." +
        "\n*ECMWF Open Data · CC BY 4.0 · courbes issues des champs réels du modèle.*";
      await kfsStratoEdit(interaction, {
        content, allowed_mentions: {parse: []}
      }, {
        name: "kfs-strato-" + (compare ? "comparison" : level + "hpa") +
          "-vent-zonal.png", bytes: imageBytes
      });
      return;
    }
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
