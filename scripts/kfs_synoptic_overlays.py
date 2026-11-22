#!/usr/bin/env python3
"""KFS synoptic overlay: unframed icons and conservative model-derived fronts.

Warm/cold boundaries are *candidate* frontal zones, never official surface analyses.
Air-mass categories describe the 850 hPa temperature only, not air-mass origin.
"""
from __future__ import annotations
import math
import numpy as np
import cartopy.crs as ccrs

from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from matplotlib.offsetbox import OffsetImage


@lru_cache(maxsize=12)
def _emoji_pixels(symbol):
    """Render actual color emoji with the Ubuntu Noto Color Emoji font."""
    font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109)
    image = Image.new("RGBA", (192, 192))
    ImageDraw.Draw(image).text((18, 18), symbol, font=font, embedded_color=True)
    bounds = image.getbbox()
    if not bounds:
        raise RuntimeError("Emoji météo non rendu : " + symbol)
    image = image.crop(bounds)
    if not np.any(np.ptp(np.asarray(image)[:,:,:3], axis=2)>20):
        raise RuntimeError("Emoji météo sans couleur : " + symbol)
    image.thumbnail((116,116), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (128,128))
    canvas.alpha_composite(image, ((128-image.width)//2,(128-image.height)//2))
    # Thin outline retains legibility against both warm and cold air masses.
    mask = canvas.getchannel("A").filter(ImageFilter.MaxFilter(5))
    outline = Image.new("RGBA", canvas.size, (16,40,66,0))
    outline.putalpha(mask.point(lambda a: int(a*.8)))
    outline.alpha_composite(canvas)
    return np.asarray(outline)


@lru_cache(maxsize=1)
def _windsock_pixels():
    """Red/white windsock symbol; orientation is decorative, not wind direction."""
    image = Image.new("RGBA", (384,384))
    d = ImageDraw.Draw(image)
    # Pole and foot, outlined to remain visible on the temperature palette.
    d.line([(78,53),(78,323)], fill="#173451", width=23)
    d.line([(78,53),(78,323)], fill="#F0F5FA", width=11)
    d.rounded_rectangle((39,315,117,334), radius=8, fill="#E5EDF3",
                        outline="#173451", width=5)
    top=[(91,67),(143,76),(195,85),(247,94),(299,103),(351,112)]
    bottom=[(91,179),(143,171),(195,163),(247,155),(299,147),(351,139)]
    for i in range(5):
        color="#E63740" if i%2==0 else "#F8FBFF"
        d.polygon([top[i],top[i+1],bottom[i+1],bottom[i]], fill=color)
        y1=round(top[i][1]*.78+bottom[i][1]*.22)
        y2=round(top[i+1][1]*.78+bottom[i+1][1]*.22)
        d.line([(top[i][0]+3,y1),(top[i+1][0]-3,y2)],
               fill="#FF9090" if i%2==0 else "#FFFFFF",width=7)
    d.line(top+list(reversed(bottom))+[top[0]],fill="#173451",width=6,joint="curve")
    d.ellipse((80,66,105,180),fill="#AD2431",outline="#173451",width=5)
    d.ellipse((85,77,99,169),fill="#702C32")
    return np.asarray(image.resize((128,128),Image.Resampling.LANCZOS))


def premium_pictogram(kind):
    """Unicode weather emoji rendered in color, with transparent background."""
    if kind in ("vent_fort", "tempete"):
        return OffsetImage(_windsock_pixels(), zoom=.36, interpolation="lanczos")
    symbols = {"pluie_forte":"💦", "neige":"❄️",
               "orage":"⚡", "verglas":"🧊", "gel":"🥶",
               "canicule":"🌡️", "inondation":"🌊"}
    if kind not in symbols:
        raise ValueError("Phénomène météo inconnu : " + kind)
    # Each call creates its own Matplotlib artist; only pixels are cached.
    return OffsetImage(_emoji_pixels(symbols[kind]), zoom=.36, interpolation="lanczos")


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
