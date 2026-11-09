"""Petits pictogrammes météo vectoriels basés exclusivement sur les codes WMO du modèle.

Aucune inférence à partir des températures ou des couleurs de la carte.
Le symbole représente le phénomène le plus significatif dans la période,
pas une observation ni une probabilité. L'absence de code => pas de pictogramme.
"""
from __future__ import annotations
import math
from matplotlib.offsetbox import AnnotationBbox, DrawingArea
from matplotlib.patches import Circle, FancyBboxPatch, Polygon
from matplotlib.lines import Line2D

ANCHORS = (
    (-3.20, 48.08), (-0.30, 49.64), (2.42, 50.18), (5.80, 49.05),
    (-2.05, 46.10), (2.20, 46.65), (6.25, 46.40),
    (-0.18, 44.15), (3.25, 44.38), (6.48, 43.80),
)
CITIES = (
    (-4.49, 48.38), (-1.55, 47.22), (-.58, 44.84),
    (1.44, 43.60), (2.35, 48.86), (3.06, 50.63),
    (1.10, 49.44), (4.84, 45.76), (5.37, 43.30),
    (7.75, 48.58), (7.26, 43.71),
)
PRIORITY = {"sun":0, "partly":1, "cloud":2, "fog":3,
            "rain":4, "snow":5, "storm":6}

def kind(code):
    if code is None or isinstance(code, bool):
        return None
    try:
        c=int(code)
        if float(code)!=c:
            return None
    except (TypeError,ValueError,OverflowError):
        return None
    if c==0:return "sun"
    if c in (1,2):return "partly"
    if c==3:return "cloud"
    if c in (45,48):return "fog"
    if c in (51,53,55,56,57,61,63,65,66,67,80,81,82):return "rain"
    if c in (71,73,75,77,85,86):return "snow"
    if c in (95,96,97,99):return "storm"
    return None

def representative(codes):
    """Le code le plus significatif de la période, seulement parmi les valides."""
    valid=[int(x) for x in codes if kind(x)]
    return max(valid,key=lambda x:PRIORITY[kind(x)]) if valid else None

def _weather_icon(code,size=32):
    mode=kind(code)
    if mode is None:
        return None
    area=DrawingArea(size,size,0,0)
    white="#eff8ff"; ink="#12344c"; cloud="#cbdde9"
    sun="#ffd15d"; rain="#56caff"; snow="#ffffff"
    def circle(x,y,r,fill,edge=ink,linewidth=1.2):
        area.add_artist(Circle((x,y),r,facecolor=fill,edgecolor=edge,linewidth=linewidth))
    def stroke(points,col,linewidth=1.6):
        area.add_artist(Line2D([p[0] for p in points],[p[1] for p in points],
            color=col,linewidth=linewidth,solid_capstyle="round",solid_joinstyle="round"))
    def sunshine(cx,cy):
        circle(cx,cy,6,sun)
        for i in range(8):
            angle=i*math.pi/4
            stroke(((cx+9*math.cos(angle),cy+9*math.sin(angle)),
                    (cx+12*math.cos(angle),cy+12*math.sin(angle))),sun,2.0)
    def cloudy(x,y):
        circle(x-6,y,6.5,cloud)
        circle(x+1,y+4,8.5,cloud)
        circle(x+9,y,6,cloud)
        area.add_artist(FancyBboxPatch((x-12,y-6),25,10,boxstyle="round,pad=0,rounding_size=3",
            facecolor=cloud,edgecolor=ink,linewidth=1.1))
    if mode=="sun":
        sunshine(16,16)
    elif mode=="partly":
        sunshine(11,19)
        cloudy(17,13)
    else:
        cloudy(16,17)
        if mode=="fog":
            for i in range(3):stroke(((5,11-i*4),(27-(i%2)*5,11-i*4)),white,1.6)
        elif mode=="rain":
            for x in (10,17,24):stroke(((x,10),(x-3,3)),rain,2)
        elif mode=="snow":
            for x in (10,17,24):
                for pts in [((x-3,5),(x+3,5)),((x,2),(x,8)),((x-2.2,3),(x+2.2,7))]:
                    stroke(pts,snow,1.3)
        elif mode=="storm":
            area.add_artist(Polygon(((15,11),(11,4),(16,6),(13,0),(23,10),(18,8)),
                closed=True,facecolor=sun,edgecolor=ink,linewidth=.8))
    return area

def overlay(ax,coords,codes,max_icons=8,exclude_cities=True):
    """Place au maximum max_icons, uniquement aux points effectivement échantillonnés."""
    if not codes or len(coords)!=len(codes):
        return 0
    plotted=[]
    for lo,la in ANCHORS:
        nearest=min(range(len(coords)),
            key=lambda i:((coords[i][1]-lo)*math.cos(math.radians(la)))**2+
                         (coords[i][0]-la)**2)
        latitude,longitude=coords[nearest]
        if exclude_cities and any(math.hypot((longitude-x)*.72,latitude-y)<.42
                                  for x,y in CITIES):
            continue
        if any(math.hypot((longitude-x)*.72,latitude-y)<1.15 for x,y in plotted):
            continue
        graphic=_weather_icon(codes[nearest],size=32)
        if graphic is None:
            continue
        ab=AnnotationBbox(graphic,(longitude,latitude),xycoords="data",
            box_alignment=(.5,.5),frameon=False,zorder=13,pad=0)
        ax.add_artist(ab)
        plotted.append((longitude,latitude))
        if len(plotted)>=max_icons:break
    return len(plotted)
