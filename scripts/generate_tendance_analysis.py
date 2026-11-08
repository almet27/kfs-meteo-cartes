#!/usr/bin/env python3
"""KFS METEO: numerical synoptic evidence and carefully qualified long-form analysis.

Preview only. IFS/AIFS deterministic Open Data snapshots are NOT weekly anomalies,
precipitation projections or sub-seasonal ensembles. Do not auto-post to Discord.
"""
from __future__ import annotations
import json
import math
import pathlib
from datetime import datetime, timedelta, timezone

import numpy as np
import xarray as xr
from ecmwf.opendata import Client

OUT = pathlib.Path("forecast-maps/tendance")
OUT.mkdir(parents=True, exist_ok=True)
STEPS = (72, 168, 240)
MODELS = {"ifs": "ECMWF IFS", "aifs-single": "ECMWF AIFS"}
REGIONS = {
    "france": ("France et alentours", (-5.5, 8.5, 42, 51.5)),
    "atlantique": ("Atlantique nord-est", (-42, -12, 40, 62)),
    "europe": ("Europe occidentale", (-11, 16, 42, 59)),
    "groenland": ("Groenland et environs", (-59, -18, 59, 81)),
}
PARAMS = (
    ("t850", {"param":"t","levelist":850}, "t", lambda a: a-273.15),
    ("msl", {"param":"msl"}, "msl", lambda a: a/100.0),
    ("z500", {"param":"gh","levelist":500}, "gh", lambda a: a/10.0),
    # Composantes du flux à 850 hPa en m/s (données facultatives).
    ("u850", {"param":"u","levelist":850}, "u", lambda a: a),
    ("v850", {"param":"v","levelist":850}, "v", lambda a: a),
)

def read_grib(path, name):
    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath":""})
    try:
        a = ds[name].squeeze().load()
        lat = np.asarray(a.latitude.values, dtype=float)
        lon = ((np.asarray(a.longitude.values, dtype=float)+180)%360)-180
        z = np.asarray(a.values, dtype=float)
        if lat.ndim != 1 or lon.ndim != 1 or z.ndim != 2:
            raise ValueError("Expected regular 2-D lat lon field")
        run = np.datetime_as_string(np.asarray(a.time.values),unit="m")+"Z"
        return lon,lat,z,run
    finally:
        ds.close()

def boxes(lon, lat, raw):
    result={}
    for key,(name,(west,east,south,north)) in REGIONS.items():
        xx = np.where((lon>=west)&(lon<=east))[0]
        yy = np.where((lat>=south)&(lat<=north))[0]
        if len(xx)<2 or len(yy)<2:
            continue
        data = raw[np.ix_(yy,xx)]
        mask=np.isfinite(data)
        if mask.mean()<0.9:
            continue
        weights=np.broadcast_to(np.cos(np.radians(lat[yy]))[:,None],data.shape)
        mean=np.average(data[mask],weights=weights[mask])
        result[key]={
            "region":name,
            "mean":round(float(mean),2),
            "min":round(float(np.min(data[mask])),2),
            "max":round(float(np.max(data[mask])),2),
            "grid_points":int(mask.sum()),
            "note":"Domaine rectangulaire, pouvant inclure des zones maritimes."
        }
    return result

def acquisition():
    now=datetime.now(timezone.utc)
    data={"status":"numerical_preview","generated_utc":now.isoformat(),
          "models":{},"errors":{},"steps_h":list(STEPS),
          "variables":{"t850":"temperatures degC at 850 hPa",
                       "msl":"mean sea level pressure hPa",
                       "z500":"geopotential height 500 hPa dam",
                       "u850":"eastward wind component at 850 hPa (m/s)",
                       "v850":"northward wind component at 850 hPa (m/s)"}}
    for model in MODELS:
        client=Client(source="ecmwf",model=model,resol="0p25")
        data["models"][model]={}
        for step in STEPS:
            key=str(step)
            fields={}
            runs=set()
            for variable,kwargs,name,conversion in PARAMS:
                target=OUT / ("temporary-"+model+"-"+key+"-"+variable+".grib2")
                try:
                    client.retrieve(stream="oper",type="fc",step=step,target=str(target),**kwargs)
                    lon,lat,field,run=read_grib(target,name)
                    if variable=="msl" and not 90000<np.nanmedian(field)<110000:
                        raise ValueError("MSLP source not in Pa")
                    if variable=="t850" and not 150<np.nanmedian(field)<340:
                        raise ValueError("T850 source not in Kelvin")
                    if variable=="z500" and not 4000<np.nanmedian(field)<6500:
                        raise ValueError("Z500 source not in metres")
                    if variable in ("u850", "v850") and not np.isfinite(field).all():
                        raise ValueError("Flux à 850 hPa non fini")
                    if variable in ("u850", "v850") and np.nanmedian(np.abs(field))>120:
                        raise ValueError("Unité de vent incohérente, attendu m/s")
                    fields[variable]=boxes(lon,lat,conversion(field))
                    runs.add(run)
                except Exception as e:
                    data["errors"][model+"-"+key+"-"+variable]=str(e)[:250]
                finally:
                    target.unlink(missing_ok=True)
            if all(k in fields for k in ("t850", "msl", "z500")) and len(runs)==1:
                issue=runs.pop()
                issue_dt=datetime.fromisoformat(issue.replace("Z","+00:00"))
                if now-issue_dt>timedelta(days=3) or issue_dt>now+timedelta(hours=1):
                    data["errors"][model+"-"+key]="Run trop ancien ou futur"
                    continue
                flow_850={}
                if "u850" in fields and "v850" in fields:
                    for region in set(fields["u850"]) & set(fields["v850"]):
                        u=fields["u850"][region]["mean"]
                        v=fields["v850"][region]["mean"]
                        vector_speed=math.hypot(u,v)
                        # Direction MÉTÉOROLOGIQUE de provenance : N=0°, E=90°.
                        direction=(math.degrees(math.atan2(-u,-v))+360)%360 if vector_speed>0.2 else None
                        flow_850[region]={
                            "u_mean_ms":u,
                            "v_mean_ms":v,
                            "vector_speed_ms":round(vector_speed,1),
                            "from_deg":round(direction) if direction is not None else None,
                            "note":"Vent vectoriel moyen à 850 hPa sur un domaine. Pas un vent de surface, ni une mesure directe d’advection."}
                data["models"][model][key]={
                    "run_utc":issue,
                    "valid_utc":(issue_dt+timedelta(hours=step)).isoformat(),
                    "fields":fields,
                    "flow_850":flow_850}
            else:
                data["errors"][model+"-"+key]="Champs ou cycles incomplets."
    import_gfs(data)
    return data


def import_gfs(data):
    """Only use fresh, run-matched NOAA numerical diagnostics."""
    source=pathlib.Path("forecast-maps/europe/noaa-diagnostics.json")
    reference_path=pathlib.Path("forecast-maps/europe/noaa-metadata.json")
    warnings=data.setdefault("warnings",[])
    if not source.is_file() or not reference_path.is_file():
        warnings.append("GFS : export numérique NOAA absent")
        return
    try:
        snapshot=json.loads(source.read_text(encoding="utf-8"))
        reference=json.loads(reference_path.read_text(encoding="utf-8"))
        now=datetime.now(timezone.utc)
        created=datetime.fromisoformat(snapshot["generated_utc"].replace("Z","+00:00"))
        published=datetime.fromisoformat(reference["generated_utc"].replace("Z","+00:00"))
        source_run=datetime.fromisoformat(snapshot["source_run_utc"].replace("Z","+00:00"))
        if not all(dt.utcoffset() is not None for dt in (created,published,source_run)):
            raise ValueError("horodatage NOAA sans fuseau")
        if not timedelta(hours=-1)<=now-created<=timedelta(hours=48):
            raise ValueError("diagnostic GFS périmé")
        if abs((created-published).total_seconds())>3600:
            raise ValueError("métadonnées et champs GFS désynchronisés")
        if snapshot["source_run_utc"]!=reference["run_utc"]:
            raise ValueError("cycle GFS différent du catalogue NOAA")
        if not timedelta(hours=0)<=created-source_run<=timedelta(hours=48):
            raise ValueError("run NOAA invalide")
        candidates=snapshot.get("models",{}).get("gfs",{})
        accepted={}
        for step in (72,168,240,360):
            key=str(step)
            record=candidates.get(key)
            chart=reference.get("maps",{}).get("gfs",{}).get(key,{})
            if not record or not all(name in chart for name in ("t850","z500_msl")):
                continue
            issue=datetime.fromisoformat(record["run_utc"].replace("Z","+00:00"))
            listed=datetime.fromisoformat(reference["runs_utc"]["gfs"][key].replace("Z","+00:00"))
            valid=datetime.fromisoformat(record["valid_utc"].replace("Z","+00:00"))
            if issue!=source_run or issue!=listed or abs((valid-issue-timedelta(hours=step)).total_seconds())>60:
                warnings.append("GFS +%s h : cycle ou validité incohérents"%key)
                continue
            fields=record.get("fields",{})
            if any(name not in fields or "france" not in fields[name] for name in ("t850","msl","z500")):
                continue
            if not (-80<fields["t850"]["france"]["mean"]<50 and
                    850<fields["msl"]["france"]["mean"]<1100 and
                    400<fields["z500"]["france"]["mean"]<650):
                warnings.append("GFS +%s h : unités suspectes"%key)
                continue
            accepted[key]=record
        if not accepted:
            warnings.append("GFS : aucune échéance chiffrée validée")
            return
        data["models"]["gfs"]=accepted
        data["gfs_source"]={"name":"NOAA NCEP GFS", "run_utc":snapshot["source_run_utc"],
                            "generated_utc":snapshot["generated_utc"],
                            "source_path":"forecast-maps/europe/noaa-diagnostics.json",
                            "steps_available_h":sorted(int(k) for k in accepted),
                            "note":"Sorties déterministes : heures de validité pouvant différer de celles d'IFS et d'AIFS."}
        print("GFS intégré :",sorted(accepted),flush=True)
    except (KeyError,ValueError,TypeError) as error:
        warnings.append("GFS non intégré : "+str(error)[:220])

def fmt(x,dec=1):
    return (("%+."+str(dec)+"f")%x).replace(".",",")

def get(data,model,step,var,reg):
    return data.get("models",{}).get(model,{}).get(str(step),{}).get("fields",{}).get(var,{}).get(reg,{}).get("mean")

def compare(data,step,variable,region,unit):
    a=get(data,"ifs",step,variable,region)
    b=get(data,"aifs-single",step,variable,region)
    if a is None or b is None:
        return ("Pour +%s h, il manque au moins un champ valide de %s sur %s : "
                "aucune conclusion comparative n'est possible."%(step,variable,region))
    diff=round(b-a,1)
    g=get(data,"gfs",step,variable,region)
    gfs=((" GFS : %.1f %s sur le même domaine à +%s h, depuis un run NOAA dont "
          "l'heure de validité peut différer."%(g,unit,step))
         if g is not None else " GFS : champ non disponible à cette échéance.")
    return ("À +%s h sur %s, IFS prévoit %.1f %s et AIFS %.1f %s "
            "(AIFS moins IFS : %s %s).%s "
            "La dispersion de trois sorties déterministes n'est pas une probabilité "
            "et ne remplace pas les ensembles."
            %(step,REGIONS[region][0],a,unit,b,unit,fmt(diff),unit,gfs))

def report(data):
    created=datetime.fromisoformat(data["generated_utc"])
    valid=sum(len(x) for x in data["models"].values())
    if valid<4:
        raise RuntimeError("Pas assez de champs numériques cohérents : pas de bulletin")
    parts=[
        "# KFS MÉTÉO — Analyse synoptique approfondie (maquette technique)",
        "",
        "> **Non diffusée sur Discord.** Analyse de sorties déterministes ponctuelles "
        "IFS, AIFS, et GFS si les données sont vérifiées. Ce document n'est pas une prévision probabiliste à quatre semaines.",
        "",
        "Génération : "+created.strftime("%d/%m/%Y %H:%M UTC")+". "
        "Sources : ECMWF Open Data et NOAA GFS vérifié le cas échéant. Champs : température à 850 hPa, "
        "pression au niveau de la mer, géopotentiel à 500 hPa et, lorsque accessibles, vents à 850 hPa. "
        "Toutes les heures citées sont en UTC.",
        "",
        "## 1. Méthode et limites de lecture",
        "",
        "Nous confrontons les prévisions numériques à +72, +168 et +240 heures ; GFS peut aussi fournir +360 h. "
        "Les valeurs fournies sont des moyennes spatiales calculées sur des boîtes "
        "géographiques fixes, non des observations au sol ni des anomalies par "
        "rapport à la climatologie. Une boîte peut comprendre la mer et la terre. "
        "Une température à 850 hPa caractérise une masse d'air en altitude : "
        "elle ne doit pas être présentée comme la température ressentie à deux mètres. "
        "La pression moyenne d'un vaste secteur ne suffit pas pour localiser "
        "précisément les centres dépressionnaires. Les données de précipitations "
        "ne sont pas incluses dans ce diagnostic.",
        "",
        "## 2. Première partie — évolution à court terme",
        "",
        compare(data,72,"t850","france","°C"),
        "",
        compare(data,72,"msl","atlantique","hPa"),
        "",
        compare(data,72,"z500","europe","dam"),
        "",
        "La lecture croisée des trois champs sert à examiner la cohérence du "
        "scénario synoptique à une échéance donnée. Elle ne démontre pas à elle "
        "seule un régime de NAO, un blocage anticyclonique ni une trajectoire "
        "des perturbations. Pour identifier ces structures, il faudrait examiner "
        "les gradients, les anomalies par rapport à une référence climatique "
        "et, idéalement, un ensemble de prévisions.",
        "",
        "## 3. Deuxième partie — évolution à moyen terme",
        "",
        compare(data,168,"t850","france","°C"),
        "",
        compare(data,168,"msl","atlantique","hPa"),
        "",
        compare(data,168,"z500","groenland","dam"),
        "",
        "À ce délai, les écarts entre deux modèles peuvent augmenter. Un accord "
        "ponctuel entre IFS et AIFS est intéressant, mais ne fournit pas à lui "
        "seul un niveau de confiance élevé. Il est nécessaire de comparer "
        "plusieurs cycles et d'examiner la dispersion des membres d'ensemble "
        "pour apprécier la robustesse d'une tendance.",
        "",
        "## 4. Troisième partie — fin de la période déterministe",
        "",
        compare(data,240,"t850","france","°C"),
        "",
        compare(data,240,"msl","atlantique","hPa"),
        "",
        compare(data,240,"z500","europe","dam"),
        "",
        "L'échéance de +240 heures représente un état de l'atmosphère prévu "
        "à environ dix jours, pas la moyenne de la deuxième semaine. "
        "Les détails géographiques sont à interpréter comme une possibilité "
        "de scénario, et non comme une prévision stabilisée de chaque région. "
        "Cette prudence s'applique encore davantage au-delà de J+10.",
        "",
        "## 5. Extension possible à J+15 via GFS",
        "",
        ("À +360 h, GFS indique sur la France une température moyenne à 850 hPa "
         "de %.1f °C et une pression moyenne de %.1f hPa. Il s'agit d'une seule "
         "sortie déterministe isolée et non d'une tendance probabiliste validée à J+15."
         %(get(data,"gfs",360,"t850","france"),get(data,"gfs",360,"msl","france"))
         if get(data,"gfs",360,"t850","france") is not None and
            get(data,"gfs",360,"msl","france") is not None
         else "Aucun champ GFS authentifié à +360 h disponible pour cette édition ; "
              "nous n'extrapolons pas J+10 jusqu'à J+15."),
        "",
        "## 6. Semaines 3 et 4 : état de disponibilité",
        "",
        "**Aucun signal de température, précipitation, NAO ou géopotentiel pour "
        "les semaines 3 et 4 n'est publié ici.** L'accès automatisé aux "
        "anomalies hebdomadaires IFS Extended n'est pas encore vérifié. "
        "La prévision sub-saisonnière devrait s'appuyer sur une moyenne d'ensemble, "
        "les anomalies hebdomadaires et leur dispersion, pas sur la prolongation "
        "arbitraire des champs à J+10. Toute estimation mensuelle précise "
        "sans ces données serait trompeuse.",
        "",
        "## 7. Signaux à surveiller",
        "",
        "Les prochaines actualisations devront notamment contrôler les "
        "tendances de pression entre les Açores, l'Atlantique nord et le "
        "Groenland, la position des dorsales et talwegs à 500 hPa, ainsi "
        "que la stabilité du contraste thermique à 850 hPa. La NAO, l'AO, "
        "la MJO et le vortex polaire ne seront commentés que si des indicateurs "
        "documentés et actualisés sont disponibles : ce sont des moteurs "
        "possibles de la circulation, pas des explications automatiques.",
        "",
        "## 8. Conclusion et confiance",
        "",
        "**Confiance qualitative : non évaluée.** Les sorties numériques "
        "ponctuelles seules ne justifient pas une probabilité ou une mention "
        "« confiance élevée ». Un futur bulletin opérationnel devra "
        "ajouter la dispersion d'ensemble, les anomalies hebdomadaires "
        "IFS Extended, une comparaison des runs successifs, puis une "
        "vérification météorologique des interprétations avant diffusion.",
        "",
        "Cette maquette démontre que des chiffres extraits directement des "
        "champs de modèles peuvent alimenter une discussion météorologique "
        "documentée. Elle ne constitue pas encore le bulletin définitif "
        "sur quatre semaines destiné aux membres du Discord KFS MÉTÉO.",
    ]
    return "\n".join(parts)+"\n"

def main():
    data=acquisition()
    if data["errors"]:
        print("Données incomplètes :",json.dumps(data["errors"],ensure_ascii=False))
    data_path=OUT/"tendance-analyse-donnees.json"
    data_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    md=report(data)
    (OUT/"tendance-analyse-apercu.md").write_text(md,encoding="utf-8")
    print("Rapport de",len(md.split()),"mots;",sum(map(len,data["models"].values())),"couples modèle-échéance; non diffusé.")
if __name__=="__main__":
    main()
