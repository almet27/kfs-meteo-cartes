/* KFS METEO /climato orages — WWLLN WGLC v2026 monthly gridded lightning archive.
   Derived from https://doi.org/10.5281/zenodo.20277101, CC BY-SA 4.0,
   Jed O. Kaplan, processed lightning stroke density (not exact CG flash counts).
   Source files: data/wglc/wglc_france_YYYY.json.gz.
*/
const kfsWglcFmt=value=>Number(value).toLocaleString("fr-FR",{maximumFractionDigits:6});
async function kfsWglcArchive(year){
  if(year<2010||year>2025)return null;
  const url="https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/data/wglc/wglc_france_"+
    year+".json.gz";
  const response=await fetch(url,{cf:{cacheEverything:true,cacheTtl:86400}});
  if(response.status===404)return null;
  if(!response.ok||!response.body)throw Error("Archive WGLC indisponible : HTTP "+response.status);
  let txt;
  try{
    txt=await new Response(response.body.pipeThrough(new DecompressionStream("gzip"))).text();
  }catch(e){throw Error("Archive WGLC invalide (décompression)");}
  if(txt.length>18000000)throw Error("Archive foudre trop volumineuse.");
  const archive=JSON.parse(txt);
  if(archive.year!==year||archive.version!==1||
    !Array.isArray(archive.lon)||!Array.isArray(archive.lat)||
    !Array.isArray(archive.monthly)||archive.monthly.length!==12)
    throw Error("Structure des archives de foudre non reconnue.");
  return archive;
}
function kfsWglcCity(archive,city){
  if(city.lat<40.5||city.lat>52||city.lon<(-6.5)||city.lon>11)
    return null;
  const closest=(grid,target)=>grid.reduce((best,current,i)=>
    Math.abs(current-target)<Math.abs(grid[best]-target)?i:best,0);
  const y=closest(archive.lat,city.lat),x=closest(archive.lon,city.lon),
    lat=archive.lat[y],lon=archive.lon[x],
    dist=kfsClimDistance(city.lat,city.lon,lat,lon);
  if(dist>12)return null; // No invented station extension.
  const width=archive.lon.length,idx=y*width+x;
  const series=archive.monthly.map(arr=>{
    const v=arr?.[idx];
    return typeof v==="number"&&Number.isFinite(v)&&v>=0?v:null;
  });
  return {lat,lon,dist,series};
}
async function kfsWglcStormReport(city,year,month){
  const period=month?KFS_Q_MONTHS[month-1]+" "+year:"année "+year;
  let archiveResult=null,error=null;
  try{
    const archive=await kfsWglcArchive(year);
    if(archive)archiveResult=kfsWglcCity(archive,city);
  }catch(e){error=String(e?.message||e);}
  // Always keep actual observer-station days separately, never replace missing
  // lightning-derived days with a guessed number.
  let obs=null,stationError=null;
  try{
    const found=await kfsPSelect(city,year,month,"orages");
    obs={station:found.station,stat:kfsPStats(found.days,"orage"),expected:found.expected};
  }catch(e){stationError=String(e?.message||e);}
  const fields=[];
  if(archiveResult){
    const w=archiveResult,selected=month?[w.series[month-1]]:w.series,
      valid=selected.filter(v=>v!==null);
    if(valid.length){
      const sum=valid.reduce((a,b)=>a+b,0);
      fields.push({name:"⚡ Activité de foudre locale (réseau WWLLN)",
        value:"Densité reconstituée sur la maille de **"+city.name+"** (≈ 5–10 km).\n"+
          (month?"Indice mensuel brut : ":"Somme des indices mensuels : ")+
          "**"+kfsWglcFmt(sum)+" coups/km²"+"**\n"+
          "Mesures corrigées de l'efficacité de détection ; **ce n'est pas un décompte exact d'impacts au sol**.",inline:false});
      if(!month){
        const lines=KFS_Q_MONTHS.map((name,i)=>name.slice(0,4).padEnd(5," ")+
          (w.series[i]!==null?kfsWglcFmt(w.series[i])+" /km²":"non disponible"));
        fields.push({name:"📅 Activité électrique par mois — maillage WWLLN",
          value:"\x60\x60\x60\n"+lines.join("\n")+"\n\x60\x60\x60",inline:false});
      }
    }
  }else{
    const why=year<2010||year>2025?
      "Archives WGLC disponibles pour 2010–2025.":
      (error||"Maille WGLC ou données nationales non disponibles.");
    fields.push({name:"⚡ Détection des impacts",
      value:"Données historiques de localisation non disponibles pour cette demande. "+why+
        "\nAucun nombre d'impacts n'est inventé.",inline:false});
  }
  if(obs){
    const st=obs.station,stText=st.km<=25?"Station de proximité":"Station éloignée : uniquement indicative pour la commune";
    fields.push({name:"⛈️ Jours d'orage observés — Météo-France",
      value:"**"+obs.stat.jours+" jours** sur "+obs.stat.valid+"/"+obs.expected+
        " jours renseignés · station **"+st.name+"** à "+kfsQR(st.km," km")+
        "\n"+stText+". Ces jours ne sont pas déduits des impacts de foudre.",inline:false});
  }else{
    fields.push({name:"⛈️ Jours d'orage observés",
      value:"Série quotidienne suffisamment complète non trouvée ("+
        (stationError||"absence de station")+" ). Aucun total n'est extrapolé.",inline:false});
  }
  const detail=archiveResult?
    "\nMaille WWLLN utilisée : "+kfsQR(archiveResult.lat,"°N")+", "+
      kfsQR(archiveResult.lon,"°E")+".":"";
  return {embeds:[{title:"KFS MÉTÉO — ⛈️ Orages et activité foudre · "+period,
    color:0x277f9c,
    description:"📍 **"+city.name+"**"+detail+
      "\nLes impulsions détectées sont distinctes des éclairs nuage-sol vérifiés et des jours d'orage.",
    fields,footer:{text:"Foudre : WWLLN/WGLC v2026 © Jed O. Kaplan, CC BY-SA 4.0 (2010–2025) · "+
      "Jours d'orage : Météo-France, stations observées"}}],allowed_mentions:{parse:[]}};
}
