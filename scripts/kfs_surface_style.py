"""KFS surface cards: projected display, interpolation and WMO icons.

Only the display is interpolated; label values come from actual sample points.
No extra weather API requests and no extension into unsampled areas.
"""
import math
from functools import lru_cache
import numpy as np
import matplotlib.tri as mtri
import matplotlib.patheffects as pe
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.offsetbox import AnnotationBbox, DrawingArea
from matplotlib.patches import Circle, PathPatch, Polygon
from matplotlib.path import Path
from matplotlib.lines import Line2D
import cartopy.crs as ccrs
from cartopy.io import shapereader
from cartopy.mpl.path import shapely_to_path
from shapely.geometry import box
from kfs_weather_symbols import kind, detailed_kind

GEO = ccrs.PlateCarree()
TEMP_MIN, TEMP_MAX = -16, 40
TEMP_STOPS = [(-16,"#36206e"),(-10,"#203eac"),(-5,"#2872db"),
              (0,"#80d9f4"),(4,"#9de6bd"),(9,"#67c97b"),
              (14,"#d7e85d"),(19,"#ffe47a"),(24,"#ffb348"),
              (30,"#f66a35"),(35,"#d1354d"),(40,"#8b225d")]
TEMP_CMAP = LinearSegmentedColormap.from_list("kfs_surface",
    [((t-TEMP_MIN)/(TEMP_MAX-TEMP_MIN),c) for t,c in TEMP_STOPS], N=256)

def france_axes(fig):
    ax=fig.add_axes((.08,.15,.84,.70),projection=ccrs.LambertConformal(
        central_longitude=2.5,central_latitude=46.5,standard_parallels=(44,49)))
    ax.set_extent((-5.65,9.85,41.15,51.5),crs=GEO)
    return ax

@lru_cache(maxsize=1)
def mainland():
    path=shapereader.natural_earth(resolution="110m",category="cultural",
                                  name="admin_0_countries")
    for rec in shapereader.Reader(path).records():
        if rec.attributes.get("ADMIN")=="France":
            return rec.geometry.intersection(box(-6,41,10,52))
    raise RuntimeError("France polygon unavailable")

def projected(ax, coords):
    ll=np.asarray(coords,dtype=float)
    return ax.projection.transform_points(GEO,ll[:,1],ll[:,0])[:,:2]

def surface(ax,coords,values,metric,cmap,norm):
    v=np.asarray(values,dtype=float)
    xy=projected(ax,coords)
    ok=np.isfinite(v)&np.isfinite(xy).all(axis=1)
    xy,v=xy[ok],v[ok]
    if len(v)<3:
        raise RuntimeError("Insufficient real surface samples")
    tri=mtri.Triangulation(xy[:,0],xy[:,1])
    vertices=xy[tri.triangles]
    edges=np.linalg.norm(vertices-np.roll(vertices,1,axis=1),axis=2)
    tri.set_mask(np.max(edges,axis=1)>125000)
    if metric in ("tmin","tmax"):
        cmap,norm=TEMP_CMAP,Normalize(TEMP_MIN,TEMP_MAX)
        # Interpolate numeric values first, then apply the fixed temperature palette.
        levels=np.linspace(TEMP_MIN,TEMP_MAX,113)
        artist=ax.tricontourf(tri,v,levels=levels,cmap=cmap,norm=norm,
                              extend="both",zorder=1)
    else:
        artist=ax.tripcolor(tri,v,shading="flat",cmap=cmap,norm=norm,zorder=1)
    clip=shapely_to_path(ax.projection.project_geometry(mainland(),GEO))
    if hasattr(artist,"set_clip_path"):
        artist.set_clip_path(clip,ax.transData)
    else:
        for c in artist.collections:
            c.set_clip_path(clip,ax.transData)
    return artist

def labels(ax,coords,values,metric):
    """Distribute genuine sampled values with pixel-space collision protection."""
    ax.apply_aspect()
    xy=projected(ax,coords)
    px=ax.transData.transform(xy)
    valid=np.flatnonzero(np.isfinite(np.asarray(values,dtype=float)))
    if not len(valid):return []
    chosen=[]
    # Start near the centre and maximise distance to the labels already chosen.
    center=np.median(px[valid],axis=0)
    idx=int(valid[np.argmin(np.linalg.norm(px[valid]-center,axis=1))])
    target=27 if metric in ("tmin","tmax") else 17
    for _ in range(target):
        chosen.append(idx)
        distances=np.min(np.linalg.norm(px[valid,None,:]-px[np.array(chosen)][None,:,:],axis=2),axis=1)
        best=int(np.argmax(distances))
        if distances[best]<69:break
        idx=int(valid[best])
    for i in chosen:
        v=float(values[i])
        label=f"{v:.0f}°" if metric in ("tmin","tmax") else f"{v:.0f}" if metric=="gust" else f"{v:.1f}"
        t=ax.text(*xy[i],label,ha="center",va="center",fontsize=9,
                  color="#102d43",fontweight="bold",zorder=8)
        t.set_path_effects([pe.withStroke(linewidth=2.7,foreground="#f7fbff")])
    return [px[i] for i in chosen]

def icon(code):
    mode=detailed_kind(code)
    if mode is None:return None
    area=DrawingArea(34,34,0,0)
    def line(points,col,w=1.8):
        area.add_artist(Line2D(*zip(*points),color=col,linewidth=w,
            solid_capstyle="round",solid_joinstyle="round"))
    def sun(x,y):
        for j in range(8):
            a=j*math.pi/4
            line([(x+8*math.cos(a),y+8*math.sin(a)),(x+11*math.cos(a),y+11*math.sin(a))],"#ffce61",2)
        area.add_artist(Circle((x,y),6,facecolor="#ffcf5c",edgecolor="#c27b21",linewidth=.8))
    def cloud():
        verts=[(7,12),(2,12),(1,20),(8,22),(10,30),(22,31),(25,23),(34,24),(35,12),(27,12),(7,12),(7,12)]
        codes=[Path.MOVETO]+[Path.CURVE4]*9+[Path.LINETO,Path.CLOSEPOLY]
        area.add_artist(PathPatch(Path(verts,codes),facecolor="#f2f7fc",edgecolor="#284b65",linewidth=1.25,joinstyle="round"))
    if mode=="sun":sun(17,17)
    else:
        if mode=="partly":sun(10,23)
        cloud()
        if mode in ("drizzle","rain","heavy_rain","showers","freezing","mixed"):
            xs=(13,23) if mode=="drizzle" else (9,17,25,32) if mode=="heavy_rain" else (10,18,26)
            for x in xs:
                if mode=="drizzle":area.add_artist(Circle((x,6),1.2,facecolor="#1598e5",edgecolor="none"))
                else:line([(x,9),(x-3,3)],"#1598e5",2.4)
            if mode=="freezing":line([(9,1),(28,1)],"#e2f7ff",2.6)
            if mode=="mixed":line([(16,3),(22,3)],"#fff",2);line([(19,0),(19,6)],"#fff",2)
            if mode=="showers":line([(6,22),(10,25)],"#ffce61",2.4)
        elif mode in ("snow","heavy_snow","snow_grains"):
            for x in ((7,14,21,28) if mode=="heavy_snow" else (9,18,27)):
                for j in range(3):
                    a=j*math.pi/3
                    line([(x-3*math.cos(a),5-3*math.sin(a)),(x+3*math.cos(a),5+3*math.sin(a))],"#e9faff",1.5)
        elif mode in ("fog","rime_fog"):
            for y in (9,5,1):line([(5,y),(28,y)],"#e3eef7",1.6)
        elif mode in ("storm","hail_storm"):
            area.add_artist(Polygon([(18,12),(12,5),(17,6),(14,0),(24,8),(19,7)],closed=True,facecolor="#ffce55",edgecolor="#a96b14",linewidth=.7))
            if mode=="hail_storm":
                for x in (8,25,31):area.add_artist(Circle((x,5),2.2,facecolor="#e9faff",edgecolor="#284b65",linewidth=.7))
    return area

# Large-city anchors, nationwide. Temperature labels and icons are offset independently.
WEATHER_CITIES=[(-4.49,48.38),(-1.55,47.22),(-.58,44.84),(1.44,43.60),
 (2.35,48.86),(3.06,50.63),(1.10,49.44),(4.84,45.76),(5.37,43.30),
 (7.75,48.58),(7.26,43.71),(-1.68,48.12),(-.37,49.18),(5.04,47.32),
 (3.09,45.78),(1.26,45.83),(.10,47.99),(4.03,49.26),(6.18,48.69),
 (3.88,43.61),(.34,46.58),(-.37,43.30),(2.89,42.70),(8.74,41.92),
 (9.45,42.70),(4.39,45.44),(6.13,45.90),(4.36,43.84),(2.30,47.08)]
def symbols(ax,coords,codes,protected,max_icons=29):
    if codes is None or len(codes)!=len(coords):return 0
    ax.apply_aspect()
    ll=np.asarray(coords,dtype=float)
    xy=projected(ax,coords)
    px=ax.transData.transform(xy)
    valid=np.array([bool(detailed_kind(c)) for c in codes])&np.isfinite(px).all(axis=1)
    indices=np.flatnonzero(valid)
    if not len(indices):return 0
    scale=ax.figure.dpi/72.
    used=[];reserved=np.asarray(protected)
    taken=set()
    for lon,lat in WEATHER_CITIES:
        if len(used)>=max_icons:break
        dist=np.hypot((ll[indices,1]-lon)*.72,ll[indices,0]-lat)
        k=int(np.argmin(dist));i=int(indices[k])
        if dist[k]>.55 or i in taken:continue
        # Keep the selected code at its actual sampled position. A small offset only moves the drawing.
        offsets=[(0,17),(0,-17),(18,0),(-18,0),(16,16),(-16,16),(16,-16),(-16,-16),(0,0)]
        best=None
        for ox,oy in offsets:
            p=px[i]+np.array([ox,oy])*scale
            if any(np.linalg.norm(p-q)<34*scale for q in used):continue
            if len(reserved) and np.any((np.abs(reserved[:,0]-p[0])<17*scale)&(np.abs(reserved[:,1]-p[1])<14*scale)):continue
            if not ax.bbox.contains(*p):continue
            best=(ox,oy,p);break
        if best is None:continue
        ox,oy,p=best
        graphic=icon(codes[i])
        ax.add_artist(AnnotationBbox(graphic,xy[i],xybox=(ox,oy),xycoords="data",
            boxcoords="offset points",frameon=False,zorder=12,pad=0,
            arrowprops=dict(arrowstyle="-",color="#385268",lw=.5) if ox or oy else None))
        used.append(p);taken.add(i)
    return len(used)
