#!/usr/bin/env python3
"""KFS MÉTÉO — three premium illustrated synoptic cards tied to ECMWF model fields.

The background maps contain the actual IFS/AIFS geopotential and isobars.
The single luminous wind arrow represents the mean France 850-hPa vector,
not a front or a complete air-parcel trajectory. Never fabricate centres of action.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

ROOT = Path("forecast-maps")
EU = ROOT / "europe"
OUT = ROOT / "tendance"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1600, 1200
COL = {
    "navy": (9, 28, 51), "navy2": (6, 43, 77),
    "white": (247, 251, 255), "muted": (170, 195, 216),
    "cyan": (102, 218, 252), "blue": (95, 164, 246),
    "gold": (250, 203, 116), "light": (213, 237, 255),
    "green": (161, 229, 193), "border": (93, 160, 204),
}
STAGES = [
    {"id": "j3", "step": "72", "period": "J+3", "idx": "01",
     "confidence": "Modérée"},
    {"id": "j7", "step": "168", "period": "J+7", "idx": "02",
     "confidence": "Limitée"},
    {"id": "j10", "step": "240", "period": "J+10", "idx": "03",
     "confidence": "Faible"},
    {"id": "j15", "step": "360", "period": "J+15", "idx": "04",
     "confidence": "Très limitée"},
]
MONTHS = ["janvier","février","mars","avril","mai","juin",
          "juillet","août","septembre","octobre","novembre","décembre"]
SECTORS = [
    "nord","nord-nord-est","nord-est","est-nord-est",
    "est","est-sud-est","sud-est","sud-sud-est",
    "sud","sud-sud-ouest","sud-ouest","ouest-sud-ouest",
    "ouest","ouest-nord-ouest","nord-ouest","nord-nord-ouest",
]

def font(sz, bold=False):
    root="/usr/share/fonts/truetype/dejavu/DejaVuSans"
    return ImageFont.truetype(root+("-Bold.ttf" if bold else ".ttf"), sz)

def txt(draw, pos, value, size=25, col="white", bold=False):
    draw.text(pos,str(value),font=font(size,bold),fill=COL.get(col,col))

def rounded(draw, box, radius=24, fill=(11,34,61,235), outline=None, width=2):
    draw.rounded_rectangle(box,radius=radius,fill=fill,outline=outline,width=width)

def parsed(value):
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:raise RuntimeError("Horodatage de run sans fuseau")
    return dt.astimezone(timezone.utc)

def stamp(value):
    return parsed(value).strftime("%d/%m %H:%M UTC")

def sector(deg):
    if deg is None:return "indéterminé"
    return SECTORS[round(float(deg)/22.5)%16]

def temp_desc(t):
    if t>=9:return "Air doux à 850 hPa"
    if t>=5:return "Air relativement doux"
    if t>=1:return "Air plus frais en altitude"
    if t>=-3:return "Air froid à 850 hPa"
    return "Air très froid à 850 hPa"

def combine_title(fl1,fl2):
    if fl1.get("from_deg") is None or fl2.get("from_deg") is None:
        return "Évolution de la circulation"
    a,b=fl1["from_deg"],fl2["from_deg"]
    delta=abs((a-b+180)%360-180)
    if delta<=35:
        direction=sector(a)
        return "Flux d'"+direction if direction.startswith(("est","ouest")) else "Flux de "+direction
    if delta<=85:
        return "Flux contrastés : "+sector(a)+" / "+sector(b)
    return "Scénarios de flux divergents"

def select(meta, data, stage, model):
    step=stage["step"]
    details=data["models"].get(model,{}).get(step)
    if not details:raise RuntimeError("Prévisions manquantes : "+model+" +"+step+" h")
    chart_run=meta.get("runs_utc",{}).get(model,{}).get(step)
    if chart_run is None or parsed(chart_run)!=parsed(details["run_utc"]):
        raise RuntimeError("Run désynchronisé "+model+" +"+step+" : "+str(chart_run)+" vs "+str(details["run_utc"]))
    rel=meta["maps"][model][step]["z500_msl"]
    path=EU/Path(rel).name
    if not path.is_file() or path.stat().st_size<15000:raise RuntimeError("Carte météo absente : "+str(path))
    flow=details.get("flow_850",{}).get("france",{})
    t850=details.get("fields",{}).get("t850",{}).get("france",{}).get("mean")
    msl=details.get("fields",{}).get("msl",{}).get("france",{}).get("mean")
    if not flow or t850 is None or msl is None:raise RuntimeError("Diagnostic France incomplet")
    return path,details,flow,float(t850),float(msl)

def map_crop(path, size):
    with Image.open(path) as im:
        im=im.convert("RGB")
        # Remove the Matplotlib title and the outer colorbar/footnote;
        # preserve the real forecast isolines and the geographical outlines.
        w,h=im.size
        crop=im.crop((int(w*.033),int(h*.135),int(w*.967),int(h*.905)))
        crop=ImageOps.fit(crop,size,method=Image.Resampling.LANCZOS,centering=(.53,.47))
        crop=ImageEnhance.Color(crop).enhance(1.21)
        crop=ImageEnhance.Contrast(crop).enhance(1.12)
    return crop

def linear_bg():
    out=Image.new("RGB",(W,H))
    draw=ImageDraw.Draw(out)
    for y in range(H):
        t=y/max(1,H-1)
        col=tuple(round(a*(1-t)+b*t) for a,b in zip(COL["navy"],COL["navy2"]))
        draw.line((0,y,W,y),fill=col)
    return out.convert("RGBA")

def glow(canvas, bbox, color, alpha=60, blur=74):
    effect=Image.new("RGBA",canvas.size,(0,0,0,0))
    d=ImageDraw.Draw(effect)
    d.ellipse(bbox,fill=(*color,alpha))
    effect=effect.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(canvas,effect)

def cloud(draw, x, y):
    draw.ellipse((x+3,y+18,x+48,y+62),fill=(116,211,247,255))
    draw.ellipse((x+27,y+4,x+80,y+65),fill=(182,236,255,255))
    draw.ellipse((x+58,y+23,x+103,y+63),fill=(125,178,248,255))
    draw.rounded_rectangle((x+15,y+35,x+94,y+65),radius=19,fill=(137,212,253,255))

def curve_arrow(base, origin, bearing, scale=1.0):
    # At +72h from=235° => towards ENE, consistent with the France-mean vector.
    if bearing is None:return base
    direction=math.radians((float(bearing)+180)%360)
    ex,ey=origin
    vx=math.sin(direction)*235*scale
    vy=-math.cos(direction)*145*scale
    start=(ex-vx,ey-vy)
    points=[]
    for k in range(36):
        t=k/35
        sway=math.sin(math.pi*t)*23
        x=start[0]+vx*t-sway*vy/max(145,math.hypot(vx,vy))
        y=start[1]+vy*t+sway*vx/max(145,math.hypot(vx,vy))
        points.append((int(x),int(y)))
    overlay=Image.new("RGBA",base.size,(0,0,0,0))
    d=ImageDraw.Draw(overlay)
    for width,clr in ((43,(29,179,249,58)),(24,(75,201,252,135)),(10,(230,248,255,220))):
        d.line(points,fill=clr,width=width,joint="curve")
    ang=math.atan2(points[-1][1]-points[-4][1],points[-1][0]-points[-4][0])
    xx,yy=points[-1]
    length=43
    head=[
        (xx+length*math.cos(ang),yy+length*math.sin(ang)),
        (xx-length*.6*math.cos(ang-1.0),yy-length*.6*math.sin(ang-1.0)),
        (xx-length*.6*math.cos(ang+1.0),yy-length*.6*math.sin(ang+1.0))]
    d.polygon(head,fill=(232,250,255,242))
    return Image.alpha_composite(base,overlay)

def write_stage(stage,meta,data,now):
    step=stage["step"]
    if step == "360":
        return write_j15(stage,meta,data,now)
    ifs=select(meta,data,stage,"ifs")
    aifs=select(meta,data,stage,"aifs-single")
    _,di,wi,ti,pi=ifs
    _,da,wa,ta,pa=aifs
    created=parsed(di["valid_utc"])
    title=combine_title(wi,wa)
    air=temp_desc(ti)
    out=linear_bg()
    out=glow(out,(150,-250,1120,400),COL["blue"],90,106)
    out=glow(out,(-100,550,700,1170),COL["cyan"],65,100)
    draw=ImageDraw.Draw(out)
    draw.rectangle((0,0,14,H),fill=(*COL["cyan"],255))
    cloud(draw,55,18)
    txt(draw,(191,30),"KFS MÉTÉO",43,"white",True)
    txt(draw,(544,40),"ANALYSE SYNOPTIQUE   /   EUROPE & ATLANTIQUE",22,"muted",True)
    txt(draw,(55,112),title,55,"white",True)
    when="%d %s %d"%(created.day,MONTHS[created.month-1],created.year)
    rounded(draw,(59,185,679,231),radius=23,fill=(204,230,249,246))
    txt(draw,(81,190),stage["period"]+"   •   "+when,24,(9,42,77),True)
    txt(draw,(707,190),"IFS / AIFS • ÉCHÉANCE "+step+" H",22,"cyan",True)

    # Main ECMWF IFS synoptic field. Underlying isobars/geography are real data.
    mx,my,mw,mh=53,260,1494,677
    rounded(draw,(mx-5,my-5,mx+mw+5,my+mh+5),radius=29,
            fill=(30,72,105,255),outline=(119,194,238,255),width=3)
    hero=map_crop(ifs[0],(mw,mh)).convert("RGBA")
    # A slight blue tint harmonises the cartographic plot with the reference style.
    wash=Image.new("RGBA",hero.size,(10,49,91,18))
    hero=Image.alpha_composite(hero,wash)
    mask=Image.new("L",(mw,mh),0);ImageDraw.Draw(mask).rounded_rectangle((0,0,mw-1,mh-1),radius=22,fill=255)
    out.paste(hero,(mx,my),mask)
    # Decorative corner shading; no fabricated isobars or frontal lines.
    local=Image.new("RGBA",out.size,(0,0,0,0));ld=ImageDraw.Draw(local)
    rounded(ld,(mx+21,my+20,mx+382,my+106),radius=19,
            fill=(9,32,58,228),outline=(89,176,231,195))
    txt(ld,(mx+41,my+32),"CHAMPS IFS  /  PRESSION & Z500",21,"white",True)
    txt(ld,(mx+41,my+67),"Isobares et géopotentiel du modèle",17,"light")
    out=Image.alpha_composite(out,local)
    # Arrow: France-domain mean wind at 850hPa, not a charted frontal trajectory.
    out=curve_arrow(out,(1013,711),wi.get("from_deg"),scale=1.0)
    ink=ImageDraw.Draw(out)
    rounded(ink,(700,814,1045,892),radius=20,
            fill=(8,38,69,231),outline=(104,210,244,227))
    txt(ink,(724,825),"FLUX MOYEN FRANCE",19,"cyan",True)
    txt(ink,(724,850),"850 hPa  ·  "+sector(wi.get("from_deg")),20,"white",True)

    # AIFS secondary authentic synoptic inset; keeps uncertainty visible.
    inset=(1080,656,1510,911)
    ink.rounded_rectangle((inset[0]-6,inset[1]-6,inset[2]+6,inset[3]+6),
      radius=19,fill=(5,25,45,250),outline=COL["cyan"],width=3)
    mini=map_crop(aifs[0],(405,165))
    out.paste(mini,(1093,705))
    ink=ImageDraw.Draw(out)
    rounded(ink,(1093,665,1497,700),radius=8,fill=(10,42,75,250))
    txt(ink,(1108,670),"ALTERNATIVE AIFS",21,"white",True)
    txt(ink,(1098,875),"Run "+stamp(da["run_utc"]),17,"light")
    # Bottom weather infographic bar matching the user-supplied visual language.
    rounded(ink,(48,959,1552,1132),radius=31,
            fill=(9,36,67,242),outline=(111,188,233,220),width=3)
    for sx in (429,810,1190):
        ink.line((sx,978,sx,1112),fill=(110,159,198,160),width=2)
    cells=[
        (76,"COURANT DOMINANT","Flux "+sector(wi.get("from_deg")),"IFS · vent 850 hPa"),
        (462,"MASSE D'AIR",air,"T850 IFS  %+0.1f °C"%ti),
        (840,"COMPARAISON","IFS / AIFS","T850 AIFS  %+0.1f °C"%ta),
    ]
    for x,k,v,foot in cells:
        txt(ink,(x,981),k,17,"cyan",True)
        # Dynamic value truncation if too long, keep factual direction available.
        val=v if len(v)<27 else v[:24]+"…"
        sz=27 if len(val)<21 else 23
        txt(ink,(x,1016),val,sz,"white",True)
        txt(ink,(x,1070),foot,19,"muted")
    rounded(ink,(1215,1011,1525,1078),radius=27,
            fill=(248,201,108,248) if stage["id"]!="j10" else (179,207,239,242))
    txt(ink,(1243,1029),stage["confidence"]+"*",24,(20,40,62),True)
    txt(ink,(1217,981),"CONFIANCE",17,"cyan",True)
    txt(ink,(1217,1094),"* qualitative",15,"muted")
    txt(ink,(58,1143),"ECMWF Open Data (CC BY 4.0) • Runs IFS "+stamp(di["run_utc"])+" / AIFS "+stamp(da["run_utc"]),16,"light")
    txt(ink,(58,1170),"Infographie explicative : flux moyen France à 850 hPa, pas de fronts inventés ni de moyenne hebdomadaire.",15,"muted")
    path=OUT/("tendance-carte-"+stage["id"]+".png")
    out.convert("RGB").save(path,"PNG",optimize=True)
    return {
        "id":stage["id"],"step_h":int(step),"path":str(path),
        "image_url":"https://almet27.github.io/kfs-meteo-cartes/"+str(path),
        "size_bytes":path.stat().st_size,
        "run_utc":{"ifs":di["run_utc"],"aifs-single":da["run_utc"]},
        "valid_utc":{"ifs":di["valid_utc"],"aifs-single":da["valid_utc"]},
        "title":stage["period"]+" — "+title,
        "style":"illustration-europe-moderne-kfs-v2",
        "wind_850_france_ifs":wi,"temperature_850_france_ifs":ti,
        "confidence_label":stage["confidence"]+" (qualitative)",
        "model_comparison":"IFS et AIFS : champs ponctuels 500 hPa / MSL, horaires de validité éventuellement différents",
    }


def write_j15(stage, meta, data, now):
    """J+15: carte AIFS authentique et diagnostic GFS séparé ; aucun IFS fictif."""
    path, aifs, flow, t850, msl = select(meta, data, stage, "aifs-single")
    gfs = data.get("models", {}).get("gfs", {}).get("360")
    if not gfs:
        raise RuntimeError("GFS +360 h manquant : consensus J+15 non vérifiable")
    gt = gfs.get("fields", {}).get("t850", {}).get("france", {}).get("mean")
    gp = gfs.get("fields", {}).get("msl", {}).get("france", {}).get("mean")
    if gt is None or gp is None:
        raise RuntimeError("Champs GFS +360 h incomplets")
    if not gfs.get("run_utc") or not gfs.get("valid_utc"):
        raise RuntimeError("Horodatages GFS +360 h absents")
    valid = parsed(aifs["valid_utc"])
    valid_gfs = parsed(gfs["valid_utc"])
    if abs((valid-valid_gfs).total_seconds()) > 12*3600:
        raise RuntimeError("Échéances AIFS et GFS désynchronisées de plus de 12 h")
    out = linear_bg()
    out = glow(out, (0, -180, 1100, 400), COL["blue"], 85, 105)
    d = ImageDraw.Draw(out)
    d.rectangle((0, 0, 14, H), fill=(*COL["cyan"], 255))
    cloud(d, 55, 18)
    txt(d, (190, 32), "KFS MÉTÉO", 43, "white", True)
    txt(d, (55, 112), "Tendance européenne à J+15", 52, "white", True)
    rounded(d, (59, 185, 740, 234), radius=23, fill=(204, 230, 249, 246))
    txt(d, (78, 194), "J+15  •  " + valid.strftime("%d/%m/%Y %H:%M UTC"), 24, (9, 42, 77), True)
    txt(d, (775, 194), "AIFS + GFS  •  IFS indisponible", 22, "cyan", True)
    mx, my, mw, mh = 53, 260, 1494, 677
    rounded(d, (mx-5, my-5, mx+mw+5, my+mh+5), radius=29,
            fill=(30, 72, 105, 255), outline=(119, 194, 238, 255), width=3)
    hero = map_crop(path, (mw, mh)).convert("RGBA")
    mask = Image.new("L", (mw, mh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mw-1, mh-1), radius=22, fill=255)
    out.paste(hero, (mx, my), mask)
    d = ImageDraw.Draw(out)
    rounded(d, (78, 283, 790, 374), radius=17,
            fill=(9, 32, 58, 239), outline=(89, 176, 231, 195))
    txt(d, (105, 290), "AIFS  •  géopotentiel 500 hPa et pression", 24, "white", True)
    txt(d, (105, 331), "Champs du modèle — pictogrammes de risques non évalués", 18, "light")
    out = curve_arrow(out, (1013, 713), flow.get("from_deg"))
    d = ImageDraw.Draw(out)
    rounded(d, (520, 783, 1509, 904), radius=22,
            fill=(8, 38, 69, 234), outline=(104, 210, 244, 227))
    txt(d, (548, 794), "FRANCE  •  comparaison de masses d'air à 850 hPa", 24, "cyan", True)
    txt(d, (548, 837), "AIFS %+0.1f °C    |    GFS %+0.1f °C"%(t850, gt), 30, "white", True)
    rounded(d, (48, 959, 1552, 1132), radius=31,
            fill=(9, 36, 67, 242), outline=(111, 188, 233, 220), width=3)
    d.line((815, 981, 815, 1110), fill=(110, 159, 198, 160), width=2)
    txt(d, (80, 984), "ÉCHÉANCE LONGUE  •  SCÉNARIOS INCERTAINS", 23, "cyan", True)
    txt(d, (80, 1038), "Flux AIFS : "+sector(flow.get("from_deg")), 28, "white", True)
    txt(d, (846, 984), "RISQUES LOCALISÉS", 23, "cyan", True)
    txt(d, (846, 1038), "Non évalués sans données adaptées", 24, "white", True)
    txt(d, (58, 1143), "Runs : AIFS "+stamp(aifs["run_utc"])+" / GFS "+stamp(gfs["run_utc"]), 16, "light")
    txt(d, (58, 1170), "Carte AIFS réelle • comparaison GFS sectorielle • aucune localisation de risque inventée.", 15, "muted")
    output = OUT / "tendance-carte-j15.png"
    out.convert("RGB").save(output, "PNG", optimize=True)
    return {
        "id":"j15", "step_h":360, "path":str(output), "image_url":"https://almet27.github.io/kfs-meteo-cartes/"+str(output),
        "size_bytes":output.stat().st_size, "run_utc":{"aifs-single":aifs["run_utc"],"gfs":gfs["run_utc"]},
        "valid_utc":{"aifs-single":aifs["valid_utc"],"gfs":gfs["valid_utc"]},
        "title":"J+15 — scénarios AIFS et GFS", "style":"illustration-europe-kfs-v3",
        "confidence_label":"Très limitée — sorties déterministes",
        "risk_status":"non_evalue", "model_comparison":"Champs cartographiés AIFS ; diagnostic sectoriel GFS"
    }


def write_premium_stage(stage, meta, data, now, risk_document):
    """Infographie européenne 16:9 : champs météorologiques réels et risques non inventés."""
    step=stage["step"]
    if step=="360":
        chart, details, flow, t850, pressure=select(meta,data,stage,"aifs-single")
        model_a="AIFS"
        other=data.get("models",{}).get("gfs",{}).get(step)
        gfs_ok=(other is not None and
                other.get("fields",{}).get("t850",{}).get("france",{}).get("mean") is not None and
                bool(other.get("run_utc")))
        model_b="GFS" if gfs_ok else "GFS indisponible"
        other_t=float(other["fields"]["t850"]["france"]["mean"]) if gfs_ok else None
        other_run=other["run_utc"] if gfs_ok else None
    else:
        chart, details, flow, t850, pressure=select(meta,data,stage,"ifs")
        _,other,_,other_t,_=select(meta,data,stage,"aifs-single")
        other_run=other["run_utc"]
        model_a="IFS"
        model_b="AIFS"
    # Le GFS est affiché uniquement si les diagnostics NOAA sont réels,
    # horodatés et à échéance comparable (max. 12 h de décalage).
    gfs_record=data.get("models",{}).get("gfs",{}).get(step)
    gfs_ready=False
    gfs_t850=None
    if gfs_record:
        try:
            gfs_t850=float(gfs_record["fields"]["t850"]["france"]["mean"])
            gfs_pressure=float(gfs_record["fields"]["msl"]["france"]["mean"])
            gfs_ready=(math.isfinite(gfs_t850) and -80<gfs_t850<50 and
                       math.isfinite(gfs_pressure) and 850<gfs_pressure<1100 and
                       abs((parsed(gfs_record["valid_utc"])-
                            parsed(details["valid_utc"])).total_seconds())<=12*3600 and
                       bool(gfs_record.get("run_utc")))
        except (KeyError,TypeError,ValueError,OverflowError):
            gfs_ready=False
    if step=="360":
        model_b="GFS" if gfs_ready else "GFS indisponible"
        other_run=gfs_record["run_utc"] if gfs_ready else None
    date=parsed(details["valid_utc"])
    hazards=next((a for a in risk_document["stages"] if a["id"]==stage["id"]),None)
    if not hazards or hazards["step_h"]!=int(step):
        raise RuntimeError("Données de risque manquantes "+stage["id"])
    if parsed(hazards["run_utc"])!=parsed(details["run_utc"]):
        raise RuntimeError("Run de risques désynchronisé "+stage["id"])
    if parsed(hazards["valid_utc"])!=date:
        raise RuntimeError("Validité carte/risques différente")
    risk_map=Path(hazards["background_path"])
    if not risk_map.is_file() or risk_map.stat().st_size<20000:
        raise RuntimeError("Fond géoréférencé non généré")
    # Composition éditoriale : aucun titre/statistique ne masque la carte.
    # Haut 0-150 ; carte géoréférencée 156-876 ; bas 892-1200.
    W2,H2=1600,1200
    canvas=Image.new("RGBA",(W2,H2),(5,30,60,255))
    bgd=ImageDraw.Draw(canvas)
    for yy in range(H2):
        tint=yy/H2
        bgd.line((0,yy,W2,yy),
                 fill=(round(5+4*tint),round(28+22*tint),
                       round(55+29*tint),255),width=1)
    hero=Image.open(risk_map).convert("RGBA")
    if hero.size!=(1544,720):
        raise RuntimeError("Le fond doit mesurer 1544x720 pixels : relancer le calcul des risques")
    mask=Image.new("L",hero.size,0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,1543,719),radius=20,fill=255)
    canvas.paste(hero,(28,156),mask)
    d=ImageDraw.Draw(canvas)
    d.rounded_rectangle((26,154,1574,878),radius=22,
                        outline=(83,190,245,255),width=3)
    d.rectangle((0,0,12,H2),fill=(46,181,247,255))

    # Synthèse calculée uniquement sur les véritables champs de modèles.
    wind_dir=sector(flow.get("from_deg"))
    rain_state=hazards["risks"]["pluie_forte"]["status"]
    wind_state=hazards["risks"]["tempete"]["status"]
    marked_categories=[key for key,item in hazards["risks"].items()
                       if item.get("status")=="marque"]
    if rain_state=="marque":
        synopsis="Passages pluvieux marqués"
    elif wind_state=="marque":
        synopsis="Flux dynamique et vent soutenu"
    elif wind_dir in ("sud-ouest","ouest-sud-ouest") and t850>=5:
        synopsis="Influence océanique de sud-ouest"
    elif t850<0:
        synopsis="Refroidissement en altitude"
    else:
        synopsis="Flux dominant de "+wind_dir

    # BANDEAU HAUT, strictement au-dessus du plan cartographique.
    cloud(d,37,28)
    txt(d,(157,19),"KFS MÉTÉO  •  TENDANCE EUROPE",37,"white",True)
    txt(d,(158,81),stage["period"]+"  ·  "+date.strftime("%d/%m/%Y %H:%M")+" UTC",
        24,"cyan",True)
    if step=="360":
        model_names="AIFS"+(" / GFS" if gfs_ready else "")
    else:
        model_names="IFS / AIFS"+(" / GFS" if gfs_ready else "")
    run_segments=[model_a+" "+parsed(details["run_utc"]).strftime("%HZ")]
    if step!="360" and other_run:
        run_segments.append("AIFS "+parsed(other_run).strftime("%HZ"))
    if gfs_ready:
        run_segments.append("GFS "+parsed(gfs_record["run_utc"]).strftime("%HZ"))
    d.rounded_rectangle((922,20,1550,128),radius=22,
                        fill=(208,233,251,249))
    txt(d,(945,32),model_names,25,(9,42,77),True)
    txt(d,(945,84),"Runs : "+"  •  ".join(run_segments),17,(20,64,95),True)

    # BANDEAU RISQUES, entièrement sous la carte et jamais sur les pictogrammes.
    d.rounded_rectangle((30,895,1570,984),radius=22,
                        fill=(6,32,60,250),outline=(87,187,232,234),width=2)
    labels=[("neige","NEIGE"),("verglas","VERGLAS"),("orage","ORAGE"),
            ("tempete","VENT FORT"),("gel","GEL"),("canicule","CANICULE"),
            ("inondation","CRUES"),("pluie_forte","PLUIE FORTE")]
    palette={"absent":(165,199,217,255),"possible":(250,202,99,255),
             "marque":(255,118,92,255),
             "relief_uniquement":(184,217,249,255),
             "indisponible":(136,164,185,255)}
    pretty={"absent":"Pas de signal","possible":"Possible",
            "marque":"Marqué","relief_uniquement":"Relief seul",
            "indisponible":"Non calculé"}
    for i,(key,label) in enumerate(labels):
        xx=42+i*190
        if i:d.line((xx-8,907,xx-8,973),
                    fill=(102,157,195,150),width=2)
        state=hazards["risks"][key]["status"]
        txt(d,(xx+3,906),label,17,"white",True)
        txt(d,(xx+3,946),pretty.get(state,"Non calculé"),16,
            palette.get(state,"muted"),True)
        if state=="marque":
            d.ellipse((xx+156,908,xx+182,934),
                      fill=(220,39,58,255),outline=(255,255,255,255),width=2)
            txt(d,(xx+164,908),"!",21,"white",True)

    # BANDEAU SYNOPTIQUE en quatre colonnes.
    d.rounded_rectangle((30,996,1570,1113),radius=24,
                        fill=(7,31,60,248),outline=(104,193,239,240),width=2)
    for xx in (419,808,1198):
        d.line((xx,1009,xx,1099),
               fill=(115,177,209,180),width=2)
    txt(d,(53,1007),"FLUX DOMINANT",18,"cyan",True)
    flux="Flux de "+wind_dir
    if wind_dir.startswith(("est","ouest")):flux="Flux d'"+wind_dir
    txt(d,(53,1055),flux[:25],23,"white",True)
    txt(d,(440,1007),"TEMPÉRATURE 850 hPa • FRANCE",16,"cyan",True)
    txt(d,(440,1053),("%+0.1f °C"%t850).replace(".",","),27,"white",True)
    if gfs_ready:
        txt(d,(620,1061),"GFS : "+("%+0.1f °C"%gfs_t850).replace(".",","),
            15,"light",True)
    txt(d,(832,1007),"SYNTHÈSE / RISQUE",18,"cyan",True)
    if rain_state=="marque":principal="Pluies soutenues"
    elif wind_state=="marque":principal="Vent fort"
    elif hazards["risks"]["neige"]["status"]=="marque":principal="Neige hors relief"
    elif rain_state=="possible":principal="Pluie possible"
    elif wind_state=="possible":principal="Vent possible"
    else:principal="Signal faible ou incertain"
    txt(d,(832,1056),principal,22,"white",True)
    txt(d,(1219,1007),"CONFIANCE",18,"cyan",True)
    d.rounded_rectangle((1215,1046,1544,1095),radius=21,
                        fill=(251,209,110,255))
    txt(d,(1232,1058),stage["confidence"],22,(20,40,62),True)

    # LÉGENDE T850, SOUS LA CARTE : palette à échelle constante -20 / +20 °C.
    txt(d,(42,1121),synopsis,17,"white",True)
    warn="❗ Risque modélisé marqué : localisation indicative, pas une vigilance officielle." if marked_categories else "Signal météo indicatif : aucune vigilance officielle déduite."
    # Les polices DejaVu du pipeline ne contiennent pas toujours les emoji.
    warn=warn.replace("❗","! rouge =")
    txt(d,(42,1161),warn,13,"light")
    txt(d,(955,1121),"TEMPÉRATURE À 850 hPa  (°C)",16,"cyan",True)
    colour_stops=[
        (0.0,(20,42,130)),(.20,(36,82,186)),(.325,(75,153,215)),
        (.425,(145,216,232)),(.50,(117,190,165)),(.625,(245,220,133)),
        (.75,(241,160,92)),(.875,(233,103,74)),(1.0,(185,52,81))]
    left,right=955,1544
    for x in range(left,right+1):
        t=(x-left)/(right-left)
        for z in range(len(colour_stops)-1):
            t0,c0=colour_stops[z]
            t1,c1=colour_stops[z+1]
            if t<=t1:
                f=(t-t0)/(t1-t0)
                rgb=tuple(round(c0[k]*(1-f)+c1[k]*f) for k in range(3))
                d.line((x,1152,x,1168),fill=rgb+(255,),width=1)
                break
    d.rectangle((left,1152,right,1168),outline=(239,249,255,255),width=1)
    for label,value in [("-20",0.0),("-10",.25),("0",.5),("+10",.75),("+20",1.0)]:
        x=left+round((right-left)*value)
        txt(d,(max(left,x-17),1172),label,13,"white",True)
    out=OUT/("tendance-carte-"+stage["id"]+".png")
    canvas.convert("RGB").save(out,"PNG",optimize=True)
    runs={model_a.lower():details["run_utc"]}
    if other_run is not None:
        runs[model_b.lower()]=other_run
    if gfs_ready and step!="360":
        runs["gfs"]=gfs_record["run_utc"]
    display_models=model_a+" / "+model_b+(" / GFS" if gfs_ready and step!="360" else "")
    return {"id":stage["id"],"step_h":int(step),"path":str(out),
       "image_url":"https://almet27.github.io/kfs-meteo-cartes/"+str(out),
       "size_bytes":out.stat().st_size, "run_utc":runs,
       "valid_utc":details["valid_utc"], "title":stage["period"]+" — synthèse synoptique "+display_models,
       "confidence_label":stage["confidence"]+" (indicative)",
       "marked_phenomena":marked_categories, "not_official_warning":True,
       "gfs_available":gfs_ready,
       "risk_status":"altitude_filtered_georeferenced", "risks":hazards["risks"], "risk_markers":hazards["markers"],
       "t850_shading":hazards.get("t850_shading",{}),
       "style":"kfs-editorial-masses-air-sans-fronts-v10-grande-carte",
       "note":"Grande carte géoréférencée 1544x720 sans encart superposé ; ! rouge localisé = pic dépassant un seuil marqué, non officiel."}

def main():
    now=datetime.now(timezone.utc)
    data=json.loads((OUT/"tendance-analyse-donnees.json").read_text(encoding="utf-8"))
    meta=json.loads((EU/"metadata.json").read_text(encoding="utf-8"))
    atlas_stamp=data.get("europe_maps_generated_utc")
    if atlas_stamp is not None and atlas_stamp!=meta.get("generated_utc"):
        raise RuntimeError("Le catalogue des cartes a change depuis les diagnostics : relancer analyse+cartes ensemble")
    for source in (data,meta):
        moment=parsed(source["generated_utc"])
        if not timedelta(hours=-1)<now-moment<timedelta(hours=48):
            raise RuntimeError("Source météorologique trop ancienne ou future")
    if data.get("errors"):raise RuntimeError("Diagnostic numérique incomplet")
    risks=json.loads((OUT/"tendance-risques.json").read_text(encoding="utf-8"))
    if risks.get("schema_version")!=1 or risks.get("atlas_generated_utc")!=meta["generated_utc"]:
        raise RuntimeError("Analyse des risques non synchronisée avec les cartes Europe")
    if abs((parsed(risks["generated_utc"])-parsed(data["generated_utc"])).total_seconds())>7200:
        raise RuntimeError("Dates de traitement cartes / risques trop éloignées")
    maps=[write_premium_stage(s,meta,data,now,risks) for s in STAGES]
    manifest={
      "schema_version":1,"status":"illustrative_model_maps",
      "generated_utc":now.isoformat(),"source_generated_utc":data["generated_utc"],
      "charts_generated_utc":meta["generated_utc"],
      "source":"ECMWF Open Data (CC BY 4.0), NOAA GFS si disponible",
      "not_weekly_anomalies":True,"period_maps":maps,"public":True,
      "graphic_style":"KFS PREMIUM 16:9 — 4 échéances, champs réels",
      "note":"Cartes ECMWF IFS/AIFS et comparaison GFS si run NOAA vérifié ; ! rouge = signal modélisé marqué, pas de vigilance officielle. Aucun front inventé ni extrapolation à 4 semaines."}
    (OUT/"tendance-cartes.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"generated_utc":manifest["generated_utc"],
                      "cards":[{"id":x["id"],"size_bytes":x["size_bytes"],"title":x["title"]} for x in maps]},
                     ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
