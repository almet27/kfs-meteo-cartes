/* KFS METEO — /climato, source Météo-France (licence ouverte)
   À intégrer dans le Worker kfs-meteo-ia, sans ajouter de secret.
   Appels à brancher dans le Worker existant (voir CLIMATO-INSTALLATION.md).
   Ne publie jamais une valeur non présente dans une fiche.
*/
const KFS_CLIM_BASE = "https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/REF_STATION/";
const KFS_CLIM_MONTHS = ["Janv.","Févr.","Mars","Avril","Mai","Juin","Juil.","Août","Sept.","Oct.","Nov.","Déc.","Année"];
const KFS_CLIM_GROUPS = ["Températures","Précipitations","Vent","Soleil et évapotranspiration","Phénomènes"];
const KFS_CLIM_OPTS = [
  {name:"Bilan",value:"bilan"},
  {name:"Toutes les statistiques",value:"complet"},
  {name:"Températures et gel",value:"temperature"},
  {name:"Précipitations",value:"pluie"},
  {name:"Vent et rafales",value:"vent"},
  {name:"Soleil et évapotranspiration",value:"soleil"},
  {name:"Orage, brouillard, neige, grêle",value:"phenomenes"},
  {name:"Records historiques",value:"records"},
  {name:"Tableau des 12 mois",value:"mensuel"}
];
const KFS_CLIM_DEFINITIONS = [
  ["La température la plus élevée","🌡️ Record de chaleur","Températures","°C",true],
  ["Température maximale (","Tmax moyenne","Températures","°C"],
  ["Température moyenne (","Température moyenne","Températures","°C"],
  ["Température minimale (","Tmin moyenne","Températures","°C"],
  ["La température la plus basse","❄️ Record de froid","Températures","°C",true],
  ["Précipitations : Hauteur quotidienne maximale","🌧️ Record de pluie sur 24 h","Précipitations","mm",true],
  ["Précipitations : Hauteur moyenne mensuelle","Cumul moyen de pluie","Précipitations","mm"],
  ["Degrés Jours Unifiés","Degrés jours unifiés","Soleil et évapotranspiration","°C"],
  ["Rayonnement global","Rayonnement global","Soleil et évapotranspiration","J/cm²"],
  ["Durée d'insolation","Durée d'ensoleillement","Soleil et évapotranspiration","h"],
  ["Evapotranspiration Potentielle","Évapotranspiration potentielle","Soleil et évapotranspiration","mm"],
  ["Rafale maximale de vent","💨 Record de rafale","Vent","m/s",true],
  ["Vitesse du vent moyenné sur 10 mn","Vent moyen sur 10 min","Vent","m/s"]
];
const kfsClimN = s => String(s||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().trim();
const kfsClimFloat = raw => {
  const v=String(raw??"").trim();
  if(v===".")return 0;
  if(!/^-?\d+(?:[.,]\d+)?$/.test(v))return null;
  const n=Number(v.replace(",","."));
  return Number.isFinite(n)?n:null;
};
const kfsClimFormat = n => n===null||n===undefined?"n/d":Number(n).toLocaleString("fr-FR",{maximumFractionDigits:1});
const kfsClimDistance = (a,b,c,d) => {
  const r=Math.PI/180, x=(c-a)*r, y=(d-b)*r;
  const v=Math.sin(x/2)**2+Math.cos(a*r)*Math.cos(c*r)*Math.sin(y/2)**2;
  return 12742*Math.asin(Math.min(1,Math.sqrt(v)));
};
async function kfsClimFetch(url,ttl=86400){
  const r=await fetch(url,{cf:{cacheEverything:true,cacheTtl:ttl},headers:{"accept":"application/json,text/plain,*/*"}});
  if(!r.ok)throw Error("Données source indisponibles : HTTP "+r.status);
  return r;
}
async function kfsClimCity(raw){
  const input=String(raw||"").trim();
  if(input.length<2||input.length>80)throw Error("Indique une ville française (2 à 80 caractères).");
  // Référentiel officiel des communes. Un code postal ajouté permet de lever les homonymies.
  const zip=(input.match(/\b\d{5}\b/)||[])[0];
  const name=input.replace(/\b\d{5}\b/g,"").replace(/[(),]/g," ").trim();
  let cities=[];
  try{
    const u="https://geo.api.gouv.fr/communes?nom="+encodeURIComponent(name)+"&fields=nom,code,centre,codesPostaux,departement&format=json&geometry=centre&limit=20";
    const r=await kfsClimFetch(u,86400);
    const data=await r.json();
    if(Array.isArray(data))cities=data.filter(c=>Array.isArray(c.centre?.coordinates));
  }catch(_){}
  if(cities.length){
    const exact=cities.filter(c=>kfsClimN(c.nom)===kfsClimN(name));
    const pool=exact.length?exact:cities;
    const picked=(zip&&pool.find(c=>c.codesPostaux?.includes(zip)))||pool[0];
    return {name:picked.nom,code:picked.code,lat:picked.centre.coordinates[1],lon:picked.centre.coordinates[0],dep:picked.departement?.code||""};
  }
  // Repli en cas d'indisponibilité du répertoire des communes.
  const u="https://geocoding-api.open-meteo.com/v1/search?name="+encodeURIComponent(name)+"&count=10&language=fr&countryCode=FR";
  const json=await (await kfsClimFetch(u,86400)).json();
  const loc=json.results?.find(x=>Number.isFinite(x.latitude)&&Number.isFinite(x.longitude));
  if(!loc)throw Error("Ville introuvable : précise son nom ou son code postal.");
  return {name:loc.name,code:"",lat:loc.latitude,lon:loc.longitude,dep:loc.admin2||""};
}
async function kfsClimStations(){
  const data=await (await kfsClimFetch(KFS_CLIM_BASE+"liste_fiches_clim.geojson",86400)).json();
  if(!Array.isArray(data.features))throw Error("Catalogue officiel des stations non exploitable.");
  const stations=data.features.map(f=>{
    const xy=f.geometry?.coordinates||[];
    return {id:String(f.properties?.num||""),name:String(f.properties?.nom||"Station"),lon:Number(xy[0]),lat:Number(xy[1])};
  }).filter(x=>/^\d{8}$/.test(x.id)&&Number.isFinite(x.lat)&&Number.isFinite(x.lon));
  if(!stations.length)throw Error("Aucune station reconnue dans le catalogue officiel.");
  return stations;
}
function kfsClimParse(txt,id){
  const lines=txt.replace(/\r/g,"").split("\n");
  const header=lines.find(l=>l.includes("Indicatif :"))||"";
  if(!header.includes(id))throw Error("Fiche station incohérente");
  const edit=(lines.join("\n").match(/Edité le\s*:\s*(\d{2})\/(\d{2})\/(\d{4})/)||[]);
  const meta={id,name:header.split("(")[0].trim(),date:edit.length?edit[3]+"-"+edit[2]+"-"+edit[1]:""};
  const out=[];
  let section="",group="",groupCategory="",period="1991–2020",last=null;
  for(const raw of lines){
    const line=raw.trim(),cells=raw.split(";");
    if(cells.length>=14&&cells[1]!==undefined){
      const label=cells[0].trim();
      if(label==="Date"){
        if(last)last.dates=cells.slice(1,14).map(x=>x.trim());
        continue;
      }
      let definition=null;
      if(label && group){
        let cat=groupCategory;
        let unit="jours";
        let title=label.replace(/\s+/g," ");
        if(group==="occurrences")cat="Phénomènes";
        if(group==="rafales")cat="Vent";
        definition=[title,title,cat,unit,false];
      } else if(!label){
        definition=KFS_CLIM_DEFINITIONS.find(d=>section.startsWith(d[0]))||null;
      }
      if(definition){
        last={label:definition[1],group:definition[2],unit:definition[3],record:!!definition[4],
          period,values:cells.slice(1,14).map(kfsClimFloat),dates:[]};
        out.push(last);
      }
      continue;
    }
    const p=line.match(/^Statistiques établies sur la période (\d{4})-(\d{4})/);
    if(p){period=p[1]+"–"+p[2];continue;}
    if(!line||/^Date\b/.test(line)||/^FICHE CLIMATOLOGIQUE|^Edité le|^Statistiques\s+\d{4}-|^Janv|^Données non disponibles|^Ces statistiques|^Rr :|^\(Tn|^\(Rr|^[-−] :/.test(line))continue;
    if(line==="Nombre moyen de jours avec"){
      group="seuils";continue;
    }
    if(line==="Nombre moyen de jours avec rafales"){
      group="rafales";groupCategory="Vent";continue;
    }
    if(line.startsWith("Nombre moyen de jours avec brouillard")){
      group="occurrences";groupCategory="Phénomènes";continue;
    }
    if(KFS_CLIM_DEFINITIONS.some(d=>line.startsWith(d[0]))){
      section=line;group="";period="1991–2020";
      if(line.startsWith("Précipitations"))groupCategory="Précipitations";
      else if(line.startsWith("Rafale")||line.startsWith("Vitesse du vent"))groupCategory="Vent";
      else if(line.startsWith("Température")||line.startsWith("La température"))groupCategory="Températures";
      continue;
    }
    // Les groupes de seuils changent de contexte après la partie précipitations.
    if(line.startsWith("Précipitations"))groupCategory="Précipitations";
  }
  // Les occurrences sans donnée restent absentes : on ne calcule ni ne devine une valeur.
  if(!out.length)throw Error("Fiche reçue mais statistiques illisibles");
  return {meta,rows:out};
}
async function kfsClimStationForCity(city){
  const stations=(await kfsClimStations()).map(x=>({...x,km:kfsClimDistance(city.lat,city.lon,x.lat,x.lon)})).sort((a,b)=>a.km-b.km);
  // Un seul jeu de mesures dans le bulletin, jamais une combinaison cachée de postes.
  for(let i=0;i<Math.min(stations.length,12);i+=4){
    const batch=stations.slice(i,i+4);
    const docs=await Promise.all(batch.map(async s=>{
      try{
        const t=await (await kfsClimFetch(KFS_CLIM_BASE+"FICHECLIM_"+s.id+".data",86400)).text();
        const parsed=kfsClimParse(t,s.id);
        return {station:s,...parsed};
      }catch(e){return null;}
    }));
    const suitable=docs.filter(Boolean).filter(d=>d.rows.some(x=>x.group==="Températures"&&x.values[12]!==null)
      &&d.rows.some(x=>x.group==="Précipitations"&&x.values[12]!==null));
    if(suitable.length){
      // Privilégie le poste le plus proche ayant au moins T et RR.
      suitable.sort((a,b)=>a.station.km-b.station.km);
      return suitable[0];
    }
  }
  throw Error("Aucune fiche climatologique exploitable trouvée parmi les 12 stations les plus proches.");
}
function kfsClimSelect(rows,rubrique){
  if(rubrique==="temperature")return rows.filter(r=>r.group==="Températures");
  if(rubrique==="pluie")return rows.filter(r=>r.group==="Précipitations");
  if(rubrique==="vent")return rows.filter(r=>r.group==="Vent");
  if(rubrique==="soleil")return rows.filter(r=>r.group==="Soleil et évapotranspiration");
  if(rubrique==="phenomenes")return rows.filter(r=>r.group==="Phénomènes");
  if(rubrique==="records")return rows.filter(r=>r.record);
  if(rubrique==="bilan"){
    const named=["Température moyenne","Tmax moyenne","Tmin moyenne","Cumul moyen de pluie","Durée d’ensoleillement","Vent moyen sur 10 min"];
    const main=rows.filter(r=>named.includes(r.label));
    const frost=rows.find(r=>r.group==="Températures"&&/^Tn\s*<=?\s*0\s*°?C/i.test(r.label));
    const heat=rows.find(r=>r.group==="Températures"&&/^Tx\s*>=?\s*30\s*°?C/i.test(r.label));
    if(frost)main.push(frost);
    if(heat)main.push(heat);
    return main;
  }
  return rows;
}
function kfsClimMessage(city,doc,rubrique,month){
  const m=month==="annee"||!month?12:Number(month)-1;
  if(!Number.isInteger(m)||m<0||m>12)throw Error("Mois invalide.");
  const selected=kfsClimSelect(doc.rows,rubrique);
  if(!selected.length)throw Error("Aucune statistique disponible pour cette rubrique dans la fiche de la station.");
  const subtitle="📍 "+city.name+(city.dep?" ("+city.dep+")":"")+"\n"+
    "Station : **"+doc.station.name+"** · n° "+doc.station.id+" · **"+kfsClimFormat(doc.station.km)+" km**"+
    (doc.station.km>30?"\n⚠️ Station éloignée : ces valeurs ne décrivent pas précisément le microclimat de la ville.":"")+
    "\nPériode : **"+KFS_CLIM_MONTHS[m]+"**";
  const source=KFS_CLIM_BASE+"FICHECLIM_"+doc.station.id+".pdf";
  const embeds=[];
  const groups=rubrique==="records"?["Records historiques"]:KFS_CLIM_GROUPS;
  for(const group of groups){
    const vals=selected.filter(r=>rubrique==="records"?r.record:r.group===group);
    if(!vals.length)continue;
    const fields=[];
    if(rubrique==="mensuel"){
      for(const r of vals){
        const lines=KFS_CLIM_MONTHS.slice(0,12).map((month,i)=>
          month.padEnd(6," ")+" "+(r.values[i]===null?"—":kfsClimFormat(r.values[i])+" "+r.unit));
        fields.push({name:r.label,value:lines.join("\n").slice(0,1020),inline:true});
      }
    }else{
      for(const r of vals){
        const v=r.values[m];
        if(v===null||v===undefined)continue;
        const when=r.record&&r.dates[m]?" (record : "+r.dates[m]+")":"";
        const note=r.period!=="1991–2020"?" · période "+r.period:"";
        fields.push({name:r.label,value:"**"+kfsClimFormat(v)+" "+r.unit+"**"+when+note,inline:true});
      }
    }
    if(fields.length){
      // Limites Discord : 25 champs et 10 embeds ; diviser au besoin.
      for(let i=0;i<fields.length;i+=20)
        embeds.push({title:(embeds.length?"":"📊 KFS MÉTÉO — Climatologie")+" · "+group,
          url:source,description:embeds.length?"":subtitle,color:0x2179b5,
          fields:fields.slice(i,i+20),
          footer:{text:"Source : Météo-France · Fiche officielle"+(doc.meta.date?" · Éditée "+doc.meta.date:"")+" · références indiquées dans la fiche"}});
    }
  }
  if(!embeds.length)throw Error("Aucune valeur publiée pour la rubrique et le mois demandés.");
  return {embeds:embeds.slice(0,10),allowed_mentions:{parse:[]}};
}
async function kfsClimatoHandle(interaction,appId){
  const options=interaction.data?.options||[];
  const opt=n=>options.find(x=>x.name===n)?.value;
  const discordUrl="https://discord.com/api/v10/webhooks/"+appId+"/"+interaction.token+"/messages/@original";
  let payload;
  try{
    const city=await kfsClimCity(opt("ville"));
    const station=await kfsClimStationForCity(city);
    payload=kfsClimMessage(city,station,String(opt("rubrique")||"bilan"),String(opt("mois")||"annee"));
  }catch(e){
    payload={content:"⚠️ **KFS MÉTÉO — /climato** : "+String(e?.message||e).slice(0,300)
      +"\nLes données manquantes ne sont jamais remplacées par des estimations.",allowed_mentions:{parse:[]}};
  }
  const r=await fetch(discordUrl,{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
  if(!r.ok)console.error("KFS_CLIMATO_DISCORD_HTTP",r.status,(await r.text()).slice(0,300));
}
async function kfsClimatoRegister(botToken,appId,guildId){
  if(!botToken||!appId||!guildId)throw Error("Informations Discord de l'application absentes.");
  const command={type:1,name:"climato",description:"Statistiques climatiques officielles Météo-France par ville",options:[
    {type:3,name:"ville",description:"Ville en France : Évreux, Rouen, Paris, Bourth...",required:true,min_length:2,max_length:80},
    {type:3,name:"rubrique",description:"Catégorie (défaut : bilan)",required:false,choices:KFS_CLIM_OPTS},
    {type:3,name:"mois",description:"Mois ou année complète",required:false,choices:[
      {name:"Année complète",value:"annee"},
      ...KFS_CLIM_MONTHS.slice(0,12).map((name,i)=>({name,value:String(i+1)}))
    ]}
  ]};
  const u="https://discord.com/api/v10/applications/"+appId+"/guilds/"+guildId+"/commands";
  const r=await fetch(u,{method:"POST",headers:{"Authorization":"Bot "+botToken,"Content-Type":"application/json"},body:JSON.stringify(command)});
  if(!r.ok)throw Error("Discord refuse /climato : HTTP "+r.status+" "+(await r.text()).slice(0,150));
}
