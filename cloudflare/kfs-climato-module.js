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
  const lines=String(txt).replace(/\r/g,"").split("\n");
  const header=lines.find(x=>x.includes("Indicatif :"))||"";
  if(!new RegExp("\\b"+id+"\\b").test(header))throw Error("Identifiant de station incorrect dans la fiche");
  const edit=(txt.match(/Edité le\s*:\s*(\d{2})\/(\d{2})\/(\d{4})/)||[]);
  const meta={id,name:header.split("(")[0].trim(),date:edit.length?edit[3]+"-"+edit[2]+"-"+edit[1]:""};
  const rows=[];
  let section="",group="",period="1991–2020",record=false,recordPeriod="",last=null;
  const labels=[
    [/^La température la plus élevée/i,"Record de chaleur","Températures","°C",true],
    [/^Température maximale\b/i,"Tmax moyenne","Températures","°C",false],
    [/^Température moyenne\b/i,"Température moyenne","Températures","°C",false],
    [/^Température minimale\b/i,"Tmin moyenne","Températures","°C",false],
    [/^La température la plus basse/i,"Record de froid","Températures","°C",true],
    [/^(Précipitations : )?Hauteur quotidienne maximale/i,"Record de pluie sur 24 h","Précipitations","mm",true],
    [/^(Précipitations : )?Hauteur moyenne mensuelle/i,"Cumul moyen de pluie","Précipitations","mm",false],
    [/^Hauteur de précipitations/i,"Cumul moyen de pluie","Précipitations","mm",false],
    [/^Degrés Jours Unifiés/i,"Degrés jours unifiés","Soleil et évapotranspiration","°C",false],
    [/^Rayonnement global/i,"Rayonnement global","Soleil et évapotranspiration","J/cm²",false],
    [/^Durée d.insolation/i,"Durée d'ensoleillement","Soleil et évapotranspiration","h",false],
    [/^Evapotranspiration Potentielle/i,"Évapotranspiration potentielle","Soleil et évapotranspiration","mm",false],
    [/^(La )?[Rr]afale maximale de vent/i,"Record de rafale","Vent","m/s",true],
    [/^Vitesse du vent moyenné sur 10 mn/i,"Vent moyen sur 10 min","Vent","m/s",false]
  ];
  const identify= s=>labels.find(d=>d[0].test(s));
  for(const raw of lines){
    const line=raw.trim(),cells=raw.split(";");
    const pd=line.match(/^Statistiques établies sur la période (\d{4})-(\d{4})/);
    if(pd){period=pd[1]+"–"+pd[2];continue;}
    const rec=line.match(/Records établis sur la période du ([0-9-]+) au ([0-9-]+)/i);
    if(rec){recordPeriod=rec[1]+" au "+rec[2];continue;}
    if(cells.length>=14){
      const label=cells[0].trim();
      if(label==="Date"){
        if(last&&last.record)last.dates=cells.slice(1,14).map(s=>s.trim());
        continue;
      }
      let d=null;
      if(group){
        if(!label)continue;
        if(/^Tx\s*[<>]=|^Tn\s*[<>]=/i.test(label))d=[null,label,"Températures","jours",false];
        else if(/^Rr\s*[<>]=/i.test(label))d=[null,label,"Précipitations","jours",false];
        else if(group==="vent"&&/m\/s/.test(label))d=[null,"Rafales "+label,"Vent","jours",false];
        else if(/^(Orage|Brouillard|Neige|Grêle)/i.test(label))d=[null,label,"Phénomènes","jours",false];
      }else if(!label){d=identify(section);}
      if(d){
        const values=cells.slice(1,14).map(kfsClimFloat);
        if(values.some(v=>v!==null)){
          last={label:d[1],group:d[2],unit:d[3],record:!!d[4],
            period,recordPeriod:d[4]?recordPeriod:"",values,dates:[]};
          rows.push(last);
        }
      }
      continue;
    }
    if(!line||/^FICHE CLIMATOLOGIQUE|^Edité le|^Statistiques\s+\d{4}|^Janv|^Données non disponibles|^Ces statistiques|^Rr :|^Tn :|^\(Tn|^\(Rr|^[-−] :|^16 m\/s/.test(line))continue;
    if(line.startsWith("Nombre moyen de jours avec")){
      group=/rafales/i.test(line)?"vent":/brouillard|orage|grêle|neige/i.test(line)?"phenomenes":"seuils";
      section="";period="1991–2020";recordPeriod="";last=null;
      continue;
    }
    if(identify(line)){
      group="";section=line;period="1991–2020";recordPeriod="";last=null;
    }
  }
  if(!rows.length)throw Error("Statistiques non lisibles dans la fiche officielle");
  return {meta,rows};
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
    const named=["Température moyenne","Tmax moyenne","Tmin moyenne","Cumul moyen de pluie","Durée d\'ensoleillement","Vent moyen sur 10 min"];
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
  return {embeds,allowed_mentions:{parse:[]}};
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
  const pages=payload.embeds?Array.from({length:Math.ceil(payload.embeds.length/10)},(_,i)=>payload.embeds.slice(i*10,i*10+10)):[];
  const first=pages.length?{...payload,embeds:pages[0]}:payload;
  const r=await fetch(discordUrl,{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify(first)});
  if(!r.ok){console.error("KFS_CLIMATO_DISCORD_HTTP",r.status,(await r.text()).slice(0,300));return;}
  for(let i=1;i<pages.length;i++){
    const follow=await fetch("https://discord.com/api/v10/webhooks/"+appId+"/"+interaction.token,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({embeds:pages[i],allowed_mentions:{parse:[]}})});
    if(!follow.ok)console.error("KFS_CLIMATO_FOLLOWUP_HTTP",follow.status);
  }
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
