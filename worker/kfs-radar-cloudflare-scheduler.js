/**
 * KFS MÉTÉO — déclencheur Cloudflare indépendant du Worker Discord.
 * Configure le déclencheur toutes les cinq minutes dans Cloudflare.
 * Secret Cloudflare : GITHUB_RADAR_DISPATCH_TOKEN.
 * GitHub fine-grained PAT : dépôt almet27/kfs-meteo-cartes, Actions: Read and write.
 *
 * Ce Worker ne télécharge pas de tuiles radar et ne contient aucun secret.
 * Il déclenche le workflow GitHub; le workflow compare les dernières
 * observations RainViewer avant de reconstruire éventuellement un GIF.
 */
const TARGET = "https://api.github.com/repos/almet27/kfs-meteo-cartes/actions/" +
  "workflows/rainviewer-discord.yml/dispatches";
const EXPECTED_CRON = "*/5 * * * *";

async function dispatchRadar(env) {
  const token = String(env.GITHUB_RADAR_DISPATCH_TOKEN || "").trim();
  if (!token) {
    console.error("KFS radar : secret GITHUB_RADAR_DISPATCH_TOKEN absent.");
    return {ok:false,code:"missing_secret"};
  }
  const response = await fetch(TARGET, {
    method:"POST",
    headers:{
      "Authorization":"Bearer "+token,
      "Accept":"application/vnd.github+json",
      "X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"KFS-Meteo-Radar-Scheduler"
    },
    body:JSON.stringify({ref:"main"}),
    signal:AbortSignal.timeout(20000)
  });
  if(response.status===204) {
    console.log("KFS radar : GitHub workflow_dispatch accepté (HTTP 204).");
    return {ok:true,code:"accepted"};
  }
  const status=response.status;
  // Ne jamais enregistrer le corps de l'erreur pour ne pas exposer de secrets.
  console.error("KFS radar : échec du déclenchement GitHub (HTTP "+status+").");
  return {ok:false,code:"github_http_"+status};
}

export default {
  async scheduled(event, env, ctx) {
    if(event.cron!==EXPECTED_CRON) {
      console.warn("KFS radar : déclenchement Cron inattendu, ignoré.");
      return;
    }
    ctx.waitUntil(dispatchRadar(env));
  },

  async fetch(request,env) {
    const url=new URL(request.url);
    if(request.method!=="GET" || url.pathname!=="/status")
      return new Response("Not Found",{status:404});
    return new Response(JSON.stringify({
      service:"kfs-radar-github-scheduler",
      enabled:!!env.GITHUB_RADAR_DISPATCH_TOKEN,
      cron:EXPECTED_CRON,
      github_workflow:"rainviewer-discord.yml",
      note:"Le statut confirme la configuration, pas la fraîcheur du radar. " +
        "Consulter GitHub Actions pour les dernières exécutions."
    }),{headers:{"Content-Type":"application/json;charset=utf-8",
      "Cache-Control":"no-store"}});
  }
};
