#!/usr/bin/env python3
"""KFS /strato — signaux déterministes de perturbation stratosphérique.
Source : ECMWF IFS Open Data (CC BY 4.0).
Ce produit n'est ni une probabilité SSW ni une confirmation d'un SSW observé.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from ecmwf.opendata import Client

ROOT = Path("strato")
ROOT.mkdir(parents=True, exist_ok=True)
RUN_META = ROOT / "metadata.json"
OUT = ROOT / "signals.json"
PNG = ROOT / "ifs-ssw-signals.png"
STEPS = tuple(range(24, 361, 24))
SOURCE = "ECMWF IFS Open Data · CC BY 4.0"

def read_indicators(path):
    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    try:
        if not {"t", "v"}.issubset(ds.data_vars):
            raise RuntimeError("Champs GRIB T/V absents")
        lat = np.asarray(ds.latitude.values, dtype=float)
        i60 = int(np.argmin(np.abs(lat - 60)))
        if abs(lat[i60] - 60) > .3:
            raise RuntimeError("Latitude 60N non disponible")
        t10 = np.asarray(ds["t"].sel(isobaricInhPa=10).values, dtype=float)
        t100 = np.asarray(ds["t"].sel(isobaricInhPa=100).values, dtype=float)
        v100 = np.asarray(ds["v"].sel(isobaricInhPa=100).values, dtype=float)
        if t10.ndim != 2 or t10.shape != t100.shape or t10.shape != v100.shape:
            raise ValueError("Grilles ECMWF non comparables")
        if not all(np.all(np.isfinite(x)) for x in (t10,t100,v100)):
            raise ValueError("Données thermiques GRIB incomplètes")
        mask_cap = lat >= 60
        mask_pole = lat >= 80
        if mask_cap.sum() < 10 or mask_pole.sum() < 3:
            raise ValueError("Résolution polaire insuffisante")
        zonal_t = np.mean(t10, axis=1)
        w = np.cos(np.deg2rad(lat))
        # Cap 60-90N area-weighted, pas une moyenne simple des cellules.
        cap_temp = float(np.average(zonal_t[mask_cap], weights=w[mask_cap])-273.15)
        pole_temp = float(np.average(zonal_t[mask_pole], weights=w[mask_pole])-273.15)
        t60 = float(np.mean(t10[i60])-273.15)
        vt = v100[i60]
        tt = t100[i60]
        # Covariance de perturbations longitudinales. Proxy de flux d'ondes;
        # pas un flux Eliassen-Palm complet ni un calcul d'anomalie climatologique.
        wave = float(np.mean((vt-vt.mean())*(tt-tt.mean())))
        if not all(np.isfinite(x) for x in (cap_temp,pole_temp,t60,wave)):
            raise ValueError("Diagnostic non fini")
        return {"temperature_cap_10hpa_60_90n_c":round(cap_temp,2),
                "temperature_pole_10hpa_80_90n_c":round(pole_temp,2),
                "gradient_pole_minus_60n_10hpa_k":round(pole_temp-t60,2),
                "eddy_heat_flux_100hpa_60n_kms":round(wave,2)}
    finally:
        ds.close()

def max_delta(series, window=5, maximum=True):
    v=[(round(series[b]-series[a],2),a,b)
       for a in STEPS for b in (a+window*24,)
       if a in series and b in series]
    if not v:return None
    return (max if maximum else min)(v)

def diagnose(wind, series):
    u=wind
    t=series["temperature_cap_10hpa_60_90n_c"]
    gradient=series["gradient_pole_minus_60n_10hpa_k"]
    invert=sorted(h for h in u if u[h]<0)
    warm=max_delta(t,5,True)
    slow=max_delta(u,5,False)
    positive_gradient=sorted(h for h in gradient if gradient[h]>0)
    # >10 K / 5 j et baisse U10 >10 m/s /5 j sont des repères
    # d'affichage internes, PAS des critères scientifiques formels de SSW.
    fastwarm=bool(warm and warm[0]>=10)
    fastslow=bool(slow and slow[0]<=-10)
    if invert:
        if len(invert)<=3 and not fastwarm:
            code, title="inversion_prevue","Inversion temporaire prévue, sans réchauffement polaire rapide"
        else:
            code, title="inversion_prevue","Inversion zonale prévue à 10 hPa"
    elif fastwarm and fastslow:
        code,title="signaux_convergents","Ralentissement et réchauffement polaire prévus"
    elif fastwarm or fastslow or min(u.values())<=5:
        code,title="surveillance","Signal précurseur partiel à surveiller"
    else:
        code,title="pas_de_signal_marque","Aucun signal marqué dans cette prévision"
    return {
        "status":code, "label":title,
        "wind_inversion_hours":invert,
        "thermal_gradient_positive_hours":positive_gradient,
        "warming_max_5d_k":warm[0] if warm else None,
        "warming_window_hours":list(warm[1:]) if warm else [],
        "deceleration_max_5d_ms":slow[0] if slow else None,
        "deceleration_window_hours":list(slow[1:]) if slow else [],
        "guidance": "Un ralentissement, une hausse polaire et l'activité ondulatoire "
                    "peuvent précéder un SSW. La valeur U<0 m/s à 10 hPa et 60N "
                    "est un critère fréquemment utilisé pour diagnostiquer un "
                    "SSW majeur observé en hiver; une simple prévision d'inversion "
                    "n'est pas une confirmation.",
        "threshold_disclaimer":"Réchauffement >=10 K/5 jours et décélération <=-10 m/s/5 jours "
            "ne sont que des repères d'affichage non calibrés, pas des probabilités.",
    }

def render(wind, series, diagnostic, run):
    days=np.array(STEPS,dtype=float)/24
    def values(data):
        return np.array([data.get(h,np.nan) for h in STEPS],dtype=float)
    u=values(wind)
    temp=values(series["temperature_cap_10hpa_60_90n_c"])
    flux=values(series["eddy_heat_flux_100hpa_60n_kms"])
    fig,axes=plt.subplots(3,1,figsize=(12.5,11.4),dpi=135,sharex=True)
    fig.patch.set_facecolor("#081629")
    for ax in axes:
        ax.set_facecolor("#122641")
        ax.grid(color="#cde4fb",alpha=.17)
        ax.tick_params(colors="#d0e0f1",labelsize=10)
        ax.set_xlim(.75,15.25)
        for sp in ax.spines.values():sp.set_color("#6a84a0")
    ax=axes[0]
    ax.plot(days,u,color="#ffc36a",linewidth=2.8,marker="o",markersize=4.3)
    ax.axhline(0,color="#ffe2aa",ls="--",linewidth=1.6)
    ax.fill_between(days,u,0,where=(u<0)&np.isfinite(u),color="#fd6473",alpha=.27)
    ax.set_title("01  |  VENT ZONAL 10 hPa / 60°N",loc="left",
                 color="#eaf3fc",fontsize=13,weight="bold")
    ax.set_ylabel("U 60°N (m/s)",color="#bcd5ec")
    ax.text(.985,.91,"< 0 m/s : inversion prévue",transform=ax.transAxes,
            ha="right",va="top",color="#ffb6bb",fontsize=10)
    ax=axes[1]
    ax.plot(days,temp,color="#ff977f",linewidth=2.8,marker="o",markersize=4.3)
    ax.set_title("02  |  TEMPÉRATURE POLAIRE 10 hPa · 60–90°N",loc="left",
                 color="#eaf3fc",fontsize=13,weight="bold")
    ax.set_ylabel("Température (°C)",color="#bcd5ec")
    if diagnostic["warming_max_5d_k"] is not None:
        ax.text(.985,.91,"Variation maximale de T sur 5 j : %+.1f °C"%diagnostic["warming_max_5d_k"],
                transform=ax.transAxes,ha="right",va="top",
                color="#ffd0ba",fontsize=10)
    ax=axes[2]
    ax.bar(days,flux,width=.68,color=[
        "#5ac1df" if np.isfinite(v) and v>=0 else "#9f8bcc" for v in flux])
    ax.axhline(0,color="#a3c1da",linewidth=1)
    ax.set_title("03  |  ACTIVITÉ ONDULATOIRE 100 hPa · 60°N",loc="left",
                 color="#eaf3fc",fontsize=13,weight="bold")
    ax.set_ylabel("v'T' (K·m/s)",color="#bcd5ec")
    ax.set_xticks([1,3,5,7,10,12,15],
                  ["J+1","J+3","J+5","J+7","J+10","J+12","J+15"])
    fig.suptitle("KFS MÉTÉO  |  SIGNAUX PRÉCURSEURS DE STRATWARM",
                 ha="left",x=.075,y=.981,color="#ffffff",
                 fontsize=18,weight="bold")
    fig.text(.075,.938,
             "ECMWF IFS · run "+run.strftime("%d/%m/%Y %HZ UTC")+
             " · prévision déterministe J+1 à J+15",
             color="#b8cde3",fontsize=11)
    fig.text(.075,.039,
             "SSW majeur : inversion des vents zonaux observée en hiver à 10 hPa / 60°N.",
             color="#d1e6f7",fontsize=10)
    fig.text(.075,.021,
             "v'T' = indicateur d'activité des ondes, pas flux EP complet · "
             "aucune probabilité SSW calculée.",
             color="#b5d0e4",fontsize=9)
    fig.subplots_adjust(left=.135,right=.97,top=.875,bottom=.11,hspace=.33)
    fig.savefig(PNG,dpi=135,facecolor=fig.get_facecolor())
    plt.close(fig)

def main():
    source=json.loads(RUN_META.read_text(encoding="utf-8"))
    run=datetime.fromisoformat(source["run_utc"].replace("Z","+00:00"))
    run=run.astimezone(timezone.utc)
    wind_raw=source["zonal_wind_series_60n"]["10"]
    wind={int(h):float(v) for h,v in wind_raw.items()}
    if len(wind)<12 or set(wind)-set(STEPS):
        raise RuntimeError("Série U10 insuffisante ou échéances incohérentes")
    if datetime.now(timezone.utc)-run>timedelta(days=3):
        raise RuntimeError("Run stratosphérique trop ancien : signaux non actualisés")
    if OUT.exists() and PNG.exists():
        try:
            old=json.loads(OUT.read_text(encoding="utf-8"))
            if old.get("run_utc")==source["run_utc"] and \
               all(len(old.get("series",{}).get(k,{}))==15 for k in (
                "temperature_cap_10hpa_60_90n_c",
                "temperature_pole_10hpa_80_90n_c",
                "gradient_pole_minus_60n_10hpa_k",
                "eddy_heat_flux_100hpa_60n_kms"
               )):
                if old.get("algorithm_version")==2:
                    print("SSW SIGNALS : run déjà calculé",source["run_utc"])
                    return
                # Refaire le graphique depuis les valeurs brutes du même run :
                # aucune requête météo supplémentaire après un changement de présentation.
                existing={key:{int(h):float(v) for h,v in values.items()}
                          for key,values in old["series"].items()}
                diagnostic=diagnose(wind,existing)
                render(wind,existing,diagnostic,run)
                old["diagnostic"]=diagnostic
                old["algorithm_version"]=2
                old["generated_utc"]=datetime.now(timezone.utc).isoformat()
                OUT.write_text(json.dumps(old,ensure_ascii=False,indent=2)+"\n",
                               encoding="utf-8")
                print("SSW SIGNALS UPDATED from cache",diagnostic["label"],flush=True)
                return
        except (ValueError,OSError):
            pass
    client=Client(source="ecmwf",model="ifs",resol="0p25")
    keys=("temperature_cap_10hpa_60_90n_c",
          "temperature_pole_10hpa_80_90n_c",
          "gradient_pole_minus_60n_10hpa_k",
          "eddy_heat_flux_100hpa_60n_kms")
    series={k:{} for k in keys}
    errors={}
    for hour in STEPS:
        file=ROOT/(".ssw-h%03d.grib2"%hour)
        try:
            client.retrieve(date=run.strftime("%Y-%m-%d"),time=run.hour,
                stream="oper",type="fc",step=hour,levtype="pl",
                levelist=[10,100],param=["t","v"],target=str(file))
            r=read_indicators(file)
            for k,v in r.items():series[k][hour]=v
            print("SSW SIGNALS OK",hour,r,flush=True)
        except Exception as e:
            errors[str(hour)]=str(e)[:180]
            print("SSW SIGNALS ERROR",hour,e,flush=True)
        finally:
            file.unlink(missing_ok=True)
    if any(len(series[k])<12 for k in keys):
        raise RuntimeError("Échantillonnage SSW insuffisant, ancien jeu préservé : "+
                           str(errors))
    diagnosis=diagnose(wind,series)
    render(wind,series,diagnosis,run)
    result={
        "schema":1,"algorithm_version":2,"model":"ifs","run_utc":source["run_utc"],
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "source":SOURCE,"chart":"strato/"+PNG.name,
        "wind_10hpa_60n":wind_raw,
        "series":{key:{str(h):v for h,v in sorted(vals.items())}
                  for key,vals in series.items()},
        "diagnostic":diagnosis,
        "errors":errors,
        "limitations":"Single deterministic forecast. No climatology/ensemble, "
                      "no formal observed SSW diagnosis, no forecast of "
                      "surface-weather impacts."
    }
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                   encoding="utf-8")
    print("SSW SIGNALS BUILT",len(wind),diagnosis["label"],flush=True)

if __name__=="__main__":
    main()
