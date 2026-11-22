#!/usr/bin/env python3
"""KFS synoptic overlay: unframed icons and conservative model-derived fronts.

Warm/cold boundaries are *candidate* frontal zones, never official surface analyses.
Air-mass categories describe the 850 hPa temperature only, not air-mass origin.
"""
from __future__ import annotations
import math
import numpy as np
import matplotlib.patheffects as pe
from matplotlib.offsetbox import DrawingArea
from matplotlib.lines import Line2D
from matplotlib.path import Path
from matplotlib.patches import PathPatch
import cartopy.crs as ccrs

def premium_pictogram(kind):
    """Original compact weather-TV vector icons, with soft dark outlines."""
    area = DrawingArea(48, 48, 0, 0)
    ink = "#123452"

    def curve(coords, color, width=2.8):
        path = Path(coords, [Path.MOVETO] + [Path.CURVE4]*(len(coords)-1))
        p = PathPatch(path, facecolor="none", edgecolor=color,
                      linewidth=width, capstyle="round", joinstyle="round")
        p.set_path_effects([pe.Stroke(linewidth=width+2.6, foreground=ink, alpha=.85), pe.Normal()])
        area.add_artist(p)

    def polygon(coords, codes, fill, edge=ink, width=1.35):
        p = PathPatch(Path(coords, codes), facecolor=fill, edgecolor=edge,
                      linewidth=width, joinstyle="round")
        p.set_path_effects([pe.SimplePatchShadow(offset=(1,-1.4), alpha=.35), pe.Normal()])
        area.add_artist(p)

    def cloud():
        verts = [(10,22),(5,22),(3,26),(4,30),
                 (5,35),(9,37),(14,37),
                 (16,44),(25,46),(30,41),
                 (33,40),(35,37),(35,34),
                 (42,35),(46,30),(43,25),
                 (41,22),(39,22),(35,22),
                 (10,22),(10,22)]
        codes = [Path.MOVETO]+[Path.CURVE4]*18+[Path.LINETO,Path.CLOSEPOLY]
        polygon(verts,codes,"#F4FAFF")

    def flake(x,y,r):
        for k in range(3):
            t=math.radians(60*k)
            dx,dy=r*math.cos(t),r*math.sin(t)
            line=Line2D([x-dx,x+dx],[y-dy,y+dy],color="#EAFBFF",
                        linewidth=1.6,solid_capstyle="round")
            line.set_path_effects([pe.Stroke(linewidth=3.5,foreground=ink),pe.Normal()])
            area.add_artist(line)

    if kind in ("vent_fort","tempete"):
        curve([(4,35),(12,35),(24,35),(32,35),
               (41,35),(43,44),(35,44),(31,44),(29,41),(29,40)],
              "#F5FAFF",3.4)
        curve([(4,25),(13,25),(31,25),(40,25),
               (47,25),(47,16),(41,16),(37,16),(35,18),(35,20)],
              "#A9EBFF",3.0)
        curve([(8,15),(12,15),(21,15),(26,15),
               (33,15),(33,7),(26,7),(23,7),(21,9),(21,10)],
              "#F5FAFF",2.8)
    elif kind=="pluie_forte":
        cloud()
        for x,y in ((13,9),(24,5),(35,9)):
            verts=[(x+2,y+8),(x+1,y+6),(x-3,y+2),(x-3,y),
                   (x-3,y-4),(x+4,y-4),(x+4,y),
                   (x+4,y+2),(x+3,y+5),(x+2,y+8),(x+2,y+8)]
            polygon(verts,[Path.MOVETO]+[Path.CURVE4]*9+[Path.CLOSEPOLY],"#44BCF4",width=.9)
    elif kind=="neige":
        cloud()
        for x,y in ((12,10),(24,6),(36,10)):
            flake(x,y,4.2)
    return area


def t850_celsius(data, unit):
    a=np.asarray(data,dtype=float)
    if "K" in str(unit) or np.nanmedian(a)>150:
        a=a-273.15
    if not np.isfinite(a).all() or np.nanmin(a)<-90 or np.nanmax(a)>60:
        raise ValueError("Temperature 850 hPa non plausible")
    return a

def air_masses(lon,lat,t850):
    """Two grounded synoptic labels: observed modeled temperature at 850hPa."""
    targets=[(-22.0,54.0),(20.0,51.0)]
    result=[]
    for x,y in targets:
        i=int(np.argmin(np.abs(lon-x)))
        j=int(np.argmin(np.abs(lat-y)))
        # Local mean to avoid unstable single-point classification
        mean=float(np.nanmean(t850[max(0,j-2):j+3,max(0,i-2):i+3]))
        if not math.isfinite(mean):continue
        label=("Air très froid" if mean<-7 else
               "Air froid" if mean<-2 else
               "Air frais" if mean<4 else
               "Air tempéré" if mean<9 else "Air doux")
        result.append({"lon":x,"lat":y,"temp_850_c":round(mean,1),
                       "label":label+" à 850 hPa",
                       "basis":"ECMWF t 850hPa (moyenne locale)"})
    return result

def km_dist(lon1,lat1,lon2,lat2):
    x=math.radians(lon2-lon1)*math.cos(math.radians((lat1+lat2)/2))*6371
    y=math.radians(lat2-lat1)*6371
    return math.hypot(x,y)

def frontal_candidates(lon,lat,current,previous,rain,step):
    """Conservative proxies; 850-hPa gradient + 6-h thermal evolution + rain.

    At far range (J+10/J+15), no individual warm/cold fronts are inferred.
    Real operational front analysis also needs human and multi-level validation.
    """
    if step>168:
        return []
    # Arrays are ascending lat/lon and aligned with the precipitation field.
    dy,dx=np.gradient(current,lat,lon,edge_order=1)
    x100=(dx/np.maximum(30,111*np.cos(np.radians(lat[:,None]))))*100
    y100=dy/111*100
    strength=np.hypot(x100,y100)
    delta=current-previous
    g=np.isfinite(strength)&np.isfinite(delta)&np.isfinite(rain)
    # Avoid Iberian/Pyrenean topographic gradients being misread as surface fronts.
    geographical=((lat[:,None]>=45)&(lat[:,None]<=62)&
                  (lon[None,:]>=-29)&(lon[None,:]<=27))
    qualified=g&geographical&(strength>=2.35)&(rain>=1.8)&(np.abs(delta)>=1.4)
    ys,xs=np.where(qualified)
    vals=[]
    for j,i in zip(ys,xs):
        warm=delta[j,i]>0
        score=float(strength[j,i])*(1+min(float(rain[j,i]),12)/8)
        vals.append((score,int(j),int(i),"chaud" if warm else "froid"))
    vals.sort(reverse=True)
    chosen=[]
    for score,j,i,kind in vals:
        x,y=float(lon[i]),float(lat[j])
        if any(k["kind"]==kind for k in chosen):continue
        if any(km_dist(x,y,k["lon"],k["lat"])<450 for k in chosen):continue
        gx,gy=float(x100[j,i]),float(y100[j,i])
        norm=math.hypot(gx,gy)
        if norm<0.00001:continue
        # tangent to thermal gradient, with orientation preserved.
        tx,ty=-gy/norm,gx/norm
        nx,ny=gx/norm,gy/norm  # toward warmer air
        chosen.append({"kind":kind,"lon":round(x,2),"lat":round(y,2),
                       "strength_c_per_100km":round(float(strength[j,i]),2),
                       "change_6h_c":round(float(delta[j,i]),1),
                       "rain_6h_mm":round(float(rain[j,i]),1),
                       "tangent":[round(tx,4),round(ty,4)],
                       "normal":[round(nx,4),round(ny,4)],
                       "confidence":"indice frontal, non validé comme front de surface"})
        if len(chosen)>=2:break
    return chosen

def _xy(lon,lat,dxkm,dykm):
    return (lon+dxkm/(111*max(.38,math.cos(math.radians(lat)))),
            lat+dykm/111)

def draw_frontal_candidates(ax,fronts):
    """Conventional red semi-circles / blue triangles on *short*, indicative segments."""
    for f in fronts:
        kind=f["kind"]
        x,y=f["lon"],f["lat"]
        tx,ty=f["tangent"]
        nx,ny=f["normal"]
        rgb="#5FC0FF" if kind=="froid" else "#FF766C"
        pts=[_xy(x,y,tx*dist,ty*dist) for dist in (-150,-90,-30,30,90,150)]
        ax.plot([q[0] for q in pts],[q[1] for q in pts],color="#092A46",
                linewidth=5.8,alpha=.85,zorder=13,transform=ccrs.PlateCarree())
        ax.plot([q[0] for q in pts],[q[1] for q in pts],color=rgb,
                linewidth=2.9,zorder=14,transform=ccrs.PlateCarree())
        for offset in (-90,0,90):
            center=_xy(x,y,tx*offset,ty*offset)
            sign=1 if kind=="froid" else -1
            if kind=="froid":
                a=_xy(*center,tx*(-14),ty*(-14))
                b=_xy(*center,tx*14,ty*14)
                tip=_xy(*center,nx*sign*30,ny*sign*30)
                ax.fill([a[0],b[0],tip[0]],[a[1],b[1],tip[1]],
                        facecolor=rgb,edgecolor="#DBF6FF",linewidth=.5,
                        transform=ccrs.PlateCarree(),zorder=15)
            else:
                # Semicircle protruding toward the colder side.
                arc=[]
                for angle in np.linspace(0,math.pi,15):
                    along=math.cos(angle)*17
                    bulge=math.sin(angle)*24
                    arc.append(_xy(*center,tx*along-nx*bulge,ty*along-ny*bulge))
                ax.plot([p[0] for p in arc],[p[1] for p in arc],
                        color=rgb,linewidth=3,transform=ccrs.PlateCarree(),zorder=15)
        ax.text(x,y+2.6,"FRONT POTENTIEL",fontsize=7.6,color="white",weight="bold",
                ha="center",va="bottom",zorder=16,
                bbox={"boxstyle":"round,pad=0.27","fc":"#092642","ec":rgb,"alpha":.92},
                transform=ccrs.PlateCarree())

def draw_air_masses(ax,masses):
    for a in masses:
        color="#CBE9FF" if a["temp_850_c"]<4 else "#FDE1A7"
        text=a["label"]+"\n"+("%+0.1f °C"%a["temp_850_c"])
        ax.text(a["lon"],a["lat"],text,color=color,fontsize=10,weight="bold",
                ha="center",va="center",zorder=12,
                bbox={"boxstyle":"round,pad=0.42","fc":"#052B51",
                      "ec":color,"alpha":.83,"lw":.75},
                transform=ccrs.PlateCarree())
