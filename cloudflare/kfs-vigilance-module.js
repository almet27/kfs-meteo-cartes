// KFS METEO — module de vigilance Météo-France, préparé mais NON déployé.
// API officielle : https://public-api.meteofrance.fr/public/DPVigilance/v1/
// Ne pas utiliser de jeton temporaire pour une automatisation permanente.
const API = 'https://public-api.meteofrance.fr/public/DPVigilance/v1';
const TOPIC = '1021368320462700564';
const PHENOMENES = {'1':'Vent violent','2':'Pluie-inondation','3':'Orages','4':'Crues','5':'Neige-verglas','6':'Canicule','7':'Grand froid','8':'Avalanches','9':'Vagues-submersion'};

export function analyseVigilance(doc) {
  if (doc?.product?.type_cdp !== 'cdp_carte_externe' || !Array.isArray(doc.product.periods)) {
    throw Error('Format carte Météo-France inconnu');
  }
  const alerts = [];
  for (const period of doc.product.periods) {
    if (!['J','J1'].includes(period.echeance)) continue;
    if (!Array.isArray(period.timelaps?.domain_ids)) throw Error('Données départementales manquantes');
    for (const zone of period.timelaps.domain_ids) {
      const dep = String(zone.domain_id || '');
      if (!/^(?:[0-9]{2}|2A|2B)$/i.test(dep) || Number(zone.max_color_id) < 3) continue;
      for (const phenomene of zone.phenomenon_items || []) {
        const level = Number(phenomene.phenomenon_max_color_id);
        if (level !== 3 && level !== 4) continue;
        alerts.push({
          jour:period.echeance, date:period.begin_validity_time || '',
          departement:dep, niveau:level, phenomene:String(phenomene.phenomenon_id),
          horaires:(phenomene.timelaps_items || []).filter(t => Number(t.color_id) >= 3)
            .map(t => [t.begin_time || '', t.end_time || '', Number(t.color_id)])
        });
      }
    }
  }
  return alerts.sort((a,b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
}

async function tokenMeteoFrance(env) {
  if (env.MF_VIGILANCE_OAUTH_URL && env.MF_VIGILANCE_CLIENT_ID && env.MF_VIGILANCE_CLIENT_SECRET) {
    const base64 = btoa(env.MF_VIGILANCE_CLIENT_ID + ':' + env.MF_VIGILANCE_CLIENT_SECRET);
    const r = await fetch(env.MF_VIGILANCE_OAUTH_URL, {
      method:'POST',
      headers:{Authorization:'Basic ' + base64, 'Content-Type':'application/x-www-form-urlencoded'},
      body:'grant_type=client_credentials', signal:AbortSignal.timeout(12000)
    });
    if (!r.ok) throw Error('OAuth Météo-France HTTP ' + r.status);
    const j = await r.json();
    if (!j.access_token) throw Error('Jeton OAuth absent');
    return j.access_token;
  }
  if (env.MF_VIGILANCE_TOKEN) return env.MF_VIGILANCE_TOKEN;
  throw Error('Accès Météo-France non configuré');
}

async function fingerprint(alerts) {
  const bytes = new TextEncoder().encode(JSON.stringify(alerts));
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));
  return 'KFS-VIGILANCE-ID:' + Array.from(hash).slice(0,12).map(v=>v.toString(16).padStart(2,'0')).join('');
}

function messageVigilance(alerts, date) {
  const rouge = alerts.some(a => a.niveau === 4);
  const jours = ['J','J1'].map(jour => {
    const items = alerts.filter(a => a.jour === jour);
    if (!items.length) return '';
    const groupes = new Map();
    for (const item of items) {
      const label = (item.niveau === 4 ? '🔴 Rouge' : '🟠 Orange') + ' — ' +
        (PHENOMENES[item.phenomene] || 'Phénomène n°' + item.phenomene);
      if (!groupes.has(label)) groupes.set(label,new Set());
      groupes.get(label).add(item.departement);
    }
    return '**' + (jour === 'J' ? 'Aujourd’hui' : 'Demain') + '**\n' +
      Array.from(groupes,([label,deps])=>'• '+label+' : '+Array.from(deps).sort().join(', ')).join('\n');
  }).filter(Boolean);
  return [
    '**KFS MÉTÉO — NOUVELLE VIGILANCE '+(rouge?'ROUGE 🔴':'ORANGE 🟠')+'**',
    '📍 France métropolitaine : vigilance officielle J et J+1',
    ...jours,
    '🕒 Bulletin : ' + new Intl.DateTimeFormat('fr-FR',{timeZone:'Europe/Paris',dateStyle:'short',timeStyle:'short'}).format(new Date(date)),
    'Source : Météo-France — https://vigilance.meteofrance.fr/fr'
  ].join('\n').slice(0,1900);
}

export async function kfsVigilanceScheduled(env) {
  if (!env.DISCORD_BOT_TOKEN) return {ok:false,reason:'discord_missing'};
  if (!(env.MF_VIGILANCE_TOKEN ||
    (env.MF_VIGILANCE_OAUTH_URL && env.MF_VIGILANCE_CLIENT_ID && env.MF_VIGILANCE_CLIENT_SECRET)))
    return {ok:false,reason:'meteofrance_access_missing'};
  const token = await tokenMeteoFrance(env);
  const headers = {Authorization:'Bearer '+token,Accept:'*/*'};
  const response = await fetch(API+'/cartevigilance/encours',{headers,signal:AbortSignal.timeout(15000)});
  if (!response.ok) throw Error('API Vigilance HTTP '+response.status);
  const doc = await response.json();
  const date = doc?.meta?.product_datetime || doc?.product?.update_time;
  if (!date || !Number.isFinite(Date.parse(date)) || Date.now()-Date.parse(date)>36*3600000)
    throw Error('Carte Météo-France trop ancienne ou invalide');
  const alerts = analyseVigilance(doc);
  if (!alerts.length) return {ok:true,notified:false,reason:'no_orange_or_red'};
  const marker = await fingerprint(alerts);
  // Lire l'historique avant tout envoi : en cas d'erreur, aucun risque de spam.
  const hist = await fetch('https://discord.com/api/v10/channels/'+TOPIC+'/messages?limit=100',{
    headers:{Authorization:'Bot '+env.DISCORD_BOT_TOKEN},signal:AbortSignal.timeout(12000)
  });
  if (!hist.ok) throw Error('Lecture topic Discord HTTP '+hist.status);
  const messages = await hist.json();
  if (messages.some(m=>(m.embeds||[]).some(e=>e.footer?.text===marker)))
    return {ok:true,notified:false,reason:'already_posted'};
  const img = await fetch(API+'/vignettenationale-J-et-J1/encours',{
    headers,signal:AbortSignal.timeout(15000)
  });
  if (!img.ok || !(img.headers.get('content-type')||'').includes('image'))
    throw Error('Carte nationale officielle PNG non disponible : aucune alerte envoyée');
  const form = new FormData();
  form.append('payload_json',JSON.stringify({
    content:messageVigilance(alerts,date),
    allowed_mentions:{parse:[]},
    embeds:[{image:{url:'attachment://vigilance-meteofrance.png'},footer:{text:marker}}]
  }));
  form.append('files[0]',new Blob([await img.arrayBuffer()],{type:'image/png'}),'vigilance-meteofrance.png');
  const posted = await fetch('https://discord.com/api/v10/channels/'+TOPIC+'/messages',{
    method:'POST',headers:{Authorization:'Bot '+env.DISCORD_BOT_TOKEN},
    body:form,signal:AbortSignal.timeout(25000)
  });
  if (!posted.ok) throw Error('Publication Discord HTTP '+posted.status);
  const result = await posted.json();
  return {ok:true,notified:true,messageId:result.id,alerts:alerts.length};
}
// À intégrer explicitement au déclencheur toutes les 5 minutes du Worker existant.
// Pour un anti-doublon garanti au-delà de 100 messages, ajouter une persistance KV/D1.
