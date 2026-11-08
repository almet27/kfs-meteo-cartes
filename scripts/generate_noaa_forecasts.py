#!/usr/bin/env python3
"""KFS NOAA: split T850 and Z500+MSLP, using real GFS/AIGFS GRIB fields."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.colors import ListedColormap, BoundaryNorm
from kfs_premium_palettes import (
    KFS_Z500_CMAP, KFS_Z500_NORM, KFS_Z500_LEVELS, KFS_Z500_TICKS,
    KFS_T850_CMAP, KFS_T850_NORM, KFS_T850_LEVELS, KFS_T850_TICKS,
)
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cf
from herbie import Herbie

OUT=Path("forecast-maps/europe")
OUT.mkdir(parents=True,exist_ok=True)
STEPS=[24,48,72,120,168,240,360]
# Attendre environ 5 h après le cycle pour disposer des champs longue échéance GFS/AIGFS.
now=datetime.now(timezone.utc)-timedelta(hours=5)
RUN=now.replace(hour=(now.hour//6)*6,minute=0,second=0,microsecond=0)
metadata={"generated_utc":datetime.now(timezone.utc).isoformat(),"run_utc":RUN.isoformat(),"runs_utc":{"gfs":{},"aigfs":{}},
          "source":"NOAA NCEP NOMADS","maps":{},"errors":{}}

def subset(dataset):
    names=list(dataset.data_vars)
    if len(names)!=1: raise ValueError("Expected one parameter, found "+str(names))
    da=dataset[names[0]].squeeze()
    lat=np.asarray(da.latitude.values)
    lon=(np.asarray(da.longitude.values)+180)%360-180
    if lat.ndim!=1 or lon.ndim!=1: raise ValueError("Non regular latitude/longitude grid")
    iy=np.where((lat>=28)&(lat<=87))[0]
    ix=np.where((lon>=-67)&(lon<=42))[0]
    ix=ix[np.argsort(lon[ix])]
    return lon[ix],lat[iy],da.values[np.ix_(iy,ix)],str(da.attrs.get("units",""))

def field(model,step,product,pattern):
    h=Herbie(RUN.replace(tzinfo=None),model=model,product=product,fxx=step,verbose=False)
    ds=h.xarray(pattern,remove_grib=True)
    if ds is None: raise RuntimeError("No NOAA field "+pattern)
    return subset(ds)

def canvas():
    fig=plt.figure(figsize=(14,9),dpi=155)
    ax=fig.add_subplot(111,projection=ccrs.PlateCarree())
    ax.set_extent([-65,40,30,85],crs=ccrs.PlateCarree())
    ax.add_feature(cf.LAND,facecolor="#f0f0f0")
    ax.add_feature(cf.OCEAN,facecolor="#dceaf3")
    ax.coastlines("110m",linewidth=.7)
    ax.add_feature(cf.BORDERS,linewidth=.4)
    return fig,ax

def save(fig,model,step,param):
    filename=f"{model}-h{step:03}-{param}.png"
    fig.savefig(OUT/filename,bbox_inches="tight",facecolor="white")
    plt.close(fig)
    metadata["maps"].setdefault(model,{}).setdefault(str(step),{})[param]="forecast-maps/europe/"+filename


# Couleurs lisibles dès 0.1 mm ; les zones sèches restent non coloriées.
PRECIP_LEVELS=[.1,.25,.5,1,2,3,5,8,12,20,30,45,65,90]
RAIN_COLORS=["#91e0ff","#55c5ff","#1b95ed","#1164cb","#143ba6","#167e91",
             "#23b85a","#85d232","#e0df23","#f6b12e","#ef772a","#da3740",
             "#a72564","#6e155b"]

def render_precip_total(lon,lat,total,model,title,step):
    fig,ax=canvas()
    cmap=ListedColormap(RAIN_COLORS)
    norm=BoundaryNorm(PRECIP_LEVELS,cmap.N,extend="max")
    display=np.ma.masked_where(~np.isfinite(total)|(total<.1),total)
    shade=ax.pcolormesh(lon,lat,display,cmap=cmap,norm=norm,shading="auto",
                        transform=ccrs.PlateCarree(),rasterized=True)
    fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,
                 extend="max",ticks=[.1,.5,1,2,5,12,30,65],
                 label="Pluie + neige (cumul TOTAL, mm équivalent-eau / 6 h)")
    ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\n"
                 f"Précipitations TOTALES (pluie et neige non séparables) | période +{step-6} à +{step} h\n"
                 f"Run : {RUN.strftime('%d/%m %H:%M')} UTC · zones sèches (<0,1 mm) en blanc")
    save(fig,model,step,"precip6h")


SNOW_COLORS=["#a7f0ff","#6fdcff","#3db7fb","#1e81ed","#2659cc","#5338bd",
             "#7744cd","#9950e1","#b44ede","#c73bb5","#d21a84","#a60c77",
             "#7b0c71","#500557"]

def render_gfs_phase(lon,lat,quantity,uncertain,step,kind):
    # Quantité ESTIMÉE ; CPOFP décrit seulement la phase A L'ÉCHÉANCE.
    # Ce n'est pas le cumul distinct natif de pluie ou de neige du GFS.
    fig,ax=canvas()
    cmap=ListedColormap(RAIN_COLORS if kind=="rain" else SNOW_COLORS)
    norm=BoundaryNorm(PRECIP_LEVELS,cmap.N,extend="max")
    shown=np.ma.masked_where(~np.isfinite(quantity)|(quantity<.1),quantity)
    shade=ax.pcolormesh(lon,lat,shown,cmap=cmap,norm=norm,shading="auto",
                        transform=ccrs.PlateCarree(),rasterized=True)
    # Gris clair : pluie/neige presente mais fraction gelee inconnue.
    # Ne pas faire passer ces zones pour du temps sec.
    unknown=np.ma.masked_where(~uncertain,np.ones_like(quantity))
    ax.pcolormesh(lon,lat,unknown,cmap=ListedColormap(["#c4cbd3"]),
                  vmin=0,vmax=1,shading="auto",transform=ccrs.PlateCarree(),rasterized=True)
    name="Pluie estimée" if kind=="rain" else "Précipitations gelées estimées (dont neige)"
    fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,
                 extend="max",ticks=[.1,.5,1,2,5,12,30,65],
                 label=name+" (mm équivalent-eau sur 6 h)")
    ax.set_title(f"KFS MÉTÉO | GFS | Atlantique Nord · Groenland · Europe | +{step} h\n"
                 f"{name} · ESTIMATION indicative, période +{step-6} à +{step} h\n"
                 f"APCP 6 h × fraction CPOFP instantanée à +{step} h · Run {RUN.strftime('%d/%m %H:%M')} UTC\n"
                 "Gris : précipitations présentes, mais phase non déterminée ; blanc : temps sec")
    save(fig,"gfs",step,kind+"6h")


# Données numériques supplémentaires pour l'analyse ChatGPT /tendance.
# Les images NOAA existantes restent indépendantes de cet export.
DIAG_STEPS={72,168,240,360}
REGIONS={
    "france":("France et alentours",(-5.5,8.5,42,51.5)),
    "atlantique":("Atlantique nord-est",(-42,-12,40,62)),
    "europe":("Europe occidentale",(-11,16,42,59)),
    "groenland":("Groenland et environs",(-59,-18,59,81)),
}
diagnostics={"schema_version":1,"generated_utc":metadata["generated_utc"],
             "source_run_utc":RUN.isoformat(),"source":"NOAA GFS / NCEP NOMADS",
             "models":{"gfs":{}},"errors":{},"steps_h":sorted(DIAG_STEPS)}
def regional_means(lon,lat,data):
    results={}
    for key,(name,(west,east,south,north)) in REGIONS.items():
        xx=np.where((lon>=west)&(lon<=east))[0]
        yy=np.where((lat>=south)&(lat<=north))[0]
        if len(xx)<2 or len(yy)<2:continue
        area=np.asarray(data[np.ix_(yy,xx)],dtype=float)
        finite=np.isfinite(area)
        if np.mean(finite)<.90:continue
        weights=np.broadcast_to(np.cos(np.radians(lat[yy]))[:,None],area.shape)
        mean=float(np.average(area[finite],weights=weights[finite]))
        results[key]={"region":name,"mean":round(mean,2),
                      "min":round(float(np.min(area[finite])),2),
                      "max":round(float(np.max(area[finite])),2),
                      "grid_points":int(np.count_nonzero(finite)),
                      "note":"Moyenne spatiale sur une boîte géographique incluant potentiellement la mer."}
    return results
def regional_flow(fields):
    flows={}
    if not all(n in fields for n in ("u850","v850")):return flows
    for region in set(fields["u850"])&set(fields["v850"]):
        u=fields["u850"][region]["mean"]
        v=fields["v850"][region]["mean"]
        speed=float(np.hypot(u,v))
        direction=float((np.degrees(np.arctan2(-u,-v))+360)%360) if speed>.2 else None
        flows[region]={"u_mean_ms":u,"v_mean_ms":v,
                       "vector_speed_ms":round(speed,1),
                       "from_deg":round(direction) if direction is not None else None,
                       "note":"Vecteur moyen vent 850 hPa, pas un vent au sol ni une trajectoire réelle d'advection."}
    return flows

for model,title in [("gfs","GFS"),("aigfs","AIGFS")]:
    for step in STEPS:
        key=f"{model}-h{step:03}"
        metadata["runs_utc"][model][str(step)]=RUN.isoformat()
        diag_fields={}
        pressure_product="pgrb2.0p25" if model=="gfs" else "sfc"
        upper_product="pgrb2.0p25" if model=="gfs" else "pres"
        try:
            lon,lat,t850,u=field(model,step,upper_product,":TMP:850 mb:")
            if not 150<np.nanmedian(t850)<330:raise ValueError("T850 values not Kelvin: "+u)
            if model=="gfs" and step in DIAG_STEPS:
                diag_fields["t850"]=regional_means(lon,lat,t850-273.15)
            fig,ax=canvas()
            shade=ax.contourf(lon,lat,t850-273.15,levels=KFS_T850_LEVELS,
                              cmap=KFS_T850_CMAP,norm=KFS_T850_NORM,
                              extend="both",transform=ccrs.PlateCarree())
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,ticks=KFS_T850_TICKS,
                         label="Température à 850 hPa (°C) · Couleurs KFS météo")
            ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\nTempérature 850 hPa · Run : {RUN.strftime('%d/%m %H:%M')} UTC · Validité : {(RUN+timedelta(hours=step)).strftime('%d/%m %H:%M')} UTC")
            save(fig,model,step,"t850")
        except Exception as e:
            metadata["errors"][key+"-t850"]=str(e)[:350]
        try:
            lon,lat,msl,u=field(model,step,pressure_product,":PRMSL:mean sea level:")
            x,y,z500,zunits=field(model,step,upper_product,":HGT:500 mb:")
            if not (np.array_equal(lon,x) and np.array_equal(lat,y)):
                raise ValueError("Z500 and MSLP grids differ")
            if not 90000<np.nanmedian(msl)<110000: raise ValueError("MSLP invalid: "+u)
            if not 4000<np.nanmedian(z500)<6500: raise ValueError("Z500 invalid: "+zunits)
            if model=="gfs" and step in DIAG_STEPS:
                diag_fields["msl"]=regional_means(lon,lat,msl/100)
                diag_fields["z500"]=regional_means(lon,lat,z500/10)
            fig,ax=canvas()
            shade=ax.contourf(lon,lat,z500/10,levels=KFS_Z500_LEVELS,
                              cmap=KFS_Z500_CMAP,norm=KFS_Z500_NORM,
                              extend="both",transform=ccrs.PlateCarree())
            # Z500 est colore, les lignes blanches representent UNIQUEMENT la MSLP.
            # Les isohypses sombres sont supprimees pour ne pas masquer les isobares.
            lines=ax.contour(
                lon,lat,msl/100,levels=np.arange(940,1061,5),
                colors="#FFFFFF",linewidths=1.25,linestyles="solid",
                transform=ccrs.PlateCarree())
            labels=ax.clabel(lines,inline=True,inline_spacing=4,
                             fmt="%d",fontsize=7.5,colors="#FFFFFF")
            for label in labels:
                label.set_path_effects([
                    pe.Stroke(linewidth=2.0,foreground="#122337"),
                    pe.Normal(),
                ])
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,ticks=KFS_Z500_TICKS,
                         label="Géopotentiel Z500 (dam) · Couleurs KFS météo")
            ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\nZ500 (dam) et pression au sol (hPa) · Run : {RUN.strftime('%d/%m %H:%M')} UTC · Validité : {(RUN+timedelta(hours=step)).strftime('%d/%m %H:%M')} UTC")
            save(fig,model,step,"z500_msl")
        except Exception as e:
            metadata["errors"][key+"-z500_msl"]=str(e)[:350]

        # Champs de vent GFS à 850 hPa. Erreur non bloquante pour les cartes existantes.
        if model=="gfs" and step in DIAG_STEPS:
            try:
                ux,uy,u850,u_unit=field("gfs",step,upper_product,":UGRD:850 mb:")
                vx,vy,v850,v_unit=field("gfs",step,upper_product,":VGRD:850 mb:")
                if not (np.array_equal(ux,vx) and np.array_equal(uy,vy)):
                    raise ValueError("Grilles GFS U850/V850 distinctes")
                if not (np.isfinite(u850).all() and np.isfinite(v850).all()):
                    raise ValueError("Vent GFS à 850 hPa incomplet")
                if np.nanmedian(np.abs(u850))>120 or np.nanmedian(np.abs(v850))>120:
                    raise ValueError("Vent GFS 850 hPa hors plage m/s")
                diag_fields["u850"]=regional_means(ux,uy,u850)
                diag_fields["v850"]=regional_means(vx,vy,v850)
            except Exception as e:
                diagnostics["errors"][key+"-wind850"]=str(e)[:260]
            if all(n in diag_fields for n in ("t850","msl","z500")):
                diagnostics["models"]["gfs"][str(step)]={
                    "run_utc":RUN.isoformat(),
                    "valid_utc":(RUN+timedelta(hours=step)).isoformat(),
                    "fields":diag_fields,
                    "flow_850":regional_flow(diag_fields)}
            else:
                diagnostics["errors"][key+"-required"]="T850, pression ou Z500 absent : scénario exclu de l'analyse"

        # Vent a 10 m : U/V instantanes, vitesse en km/h.
        try:
            lon,lat,uw,_=field(model,step,pressure_product,":UGRD:10 m above ground:")
            x,y,vw,_=field(model,step,pressure_product,":VGRD:10 m above ground:")
            if not (np.array_equal(lon,x) and np.array_equal(lat,y)):
                raise ValueError("Grilles U/V incompatibles")
            if np.nanmax(np.abs(uw))>180 or np.nanmax(np.abs(vw))>180:
                raise ValueError("Valeurs de vent hors limites")
            speed=np.hypot(uw,vw)*3.6
            fig,ax=canvas()
            shade=ax.contourf(lon,lat,speed,levels=[0,10,20,30,40,50,60,75,90,110,130,160,200],
                              cmap="turbo",extend="max",transform=ccrs.PlateCarree())
            xx,yy=np.meshgrid(lon,lat)
            skip=(slice(None,None,max(1,len(lat)//22)),slice(None,None,max(1,len(lon)//26)))
            ax.quiver(xx[skip],yy[skip],uw[skip],vw[skip],color="#233245",alpha=.78,
                      scale=680,width=.0016,transform=ccrs.PlateCarree())
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,
                         label="Vitesse du vent à 10 m (km/h) — flèches : direction")
            ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\nVent à 10 m · Run : {RUN.strftime('%d/%m %H:%M')} UTC · Validité : {(RUN+timedelta(hours=step)).strftime('%d/%m %H:%M')} UTC")
            save(fig,model,step,"wind10m")
        except Exception as e:
            metadata["errors"][key+"-wind10m"]=str(e)[:350]

        # Precipitations totales des 6 h precedentes en mm d'eau.
        # Le produit AIGFS ne distingue pas la pluie et la neige ; ne pas inventer une partition.
        try:
            accumulation=f":APCP:surface:{step-6}-{step} hour acc"
            lon,lat,total,units=field(model,step,pressure_product,accumulation)
            if np.nanmin(total)<-1 or np.nanmax(total)>1500:
                raise ValueError("Cumuls de précipitation inattendus : "+units)
            total=np.maximum(0,total)
            render_precip_total(lon,lat,total,model,title,step)
            if model=="gfs":
                # GFS met à disposition CPOFP (% précipitations gelées, instantané).
                # La fraction de précipitations sur 6 h est INDICATIVE et non un champ
                # de cumul natif. Valeurs -50 = absence de precipitations : ne pas
                # les interpréter comme 0 % de neige.
                try:
                    px,py,phase,phase_units=field("gfs",step,pressure_product,":CPOFP:surface:")
                    if not (np.array_equal(lon,px) and np.array_equal(lat,py)):
                        raise ValueError("Grille CPOFP incompatible avec APCP")
                    valid=np.isfinite(phase)&(phase>=0)&(phase<=100)
                    wet=np.isfinite(total)&(total>=.1)
                    if not np.any(wet&valid):
                        raise ValueError("CPOFP n'est pas renseigné dans les zones de précipitations")
                    fraction=np.where(valid,phase/100,np.nan)
                    rain=np.where(valid,total*(1-fraction),np.nan)
                    frozen=np.where(valid,total*fraction,np.nan)
                    uncertain=wet&(~valid)
                    render_gfs_phase(lon,lat,rain,uncertain,step,"rain")
                    render_gfs_phase(lon,lat,frozen,uncertain,step,"snow")
                    metadata.setdefault("derived_estimates",{}).setdefault(model,{})[str(step)]={
                        "rain6h":"APCP_6h*(1-CPOFP_at_valid_time/100)",
                        "snow6h":"APCP_6h*CPOFP_at_valid_time/100",
                        "warning":"ESTIMATION. CPOFP est instantané en fin d'intervalle. "
                                  "Le champ snow6h contient les précipitations gelées "
                                  "(dont neige, potentiellement grésil), et non un cumul neige natif.",
                        "wet_cells_with_valid_phase":int(np.count_nonzero(wet&valid)),
                        "wet_cells_total":int(np.count_nonzero(wet))}
                except Exception as error:
                    metadata["errors"][key+"-rain6h-snow6h"]=str(error)[:350]

        except Exception as e:
            metadata["errors"][key+"-precip6h"]=str(e)[:350]
(OUT/"noaa-diagnostics.json").write_text(
    json.dumps(diagnostics,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("GFS numerical diagnostics",json.dumps({"steps":list(diagnostics["models"]["gfs"]),
                                              "errors":diagnostics["errors"]},ensure_ascii=False),flush=True)
(OUT/"noaa-metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
print("NOAA summary",json.dumps({"maps":metadata["maps"],"errors":metadata["errors"]},ensure_ascii=False),flush=True)
if not metadata["maps"]:raise RuntimeError("No genuine GFS/AIGFS fields, publication aborted")
