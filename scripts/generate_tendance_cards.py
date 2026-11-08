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
    maps=[write_stage(s,meta,data,now) for s in STAGES]
    manifest={
      "schema_version":1,"status":"illustrative_model_maps",
      "generated_utc":now.isoformat(),"source_generated_utc":data["generated_utc"],
      "charts_generated_utc":meta["generated_utc"],
      "source":"ECMWF Open Data (CC BY 4.0)",
      "not_weekly_anomalies":True,"period_maps":maps,"public":True,
      "graphic_style":"KFS ÉDITORIAL MODERNE v2 — actualisé automatiquement sur les modèles",
      "note":"Infographies tirées des vraies cartes IFS/AIFS, flux moyen 850 hPa calculé, sans fronts inventés ni prévisions à 4 semaines extrapolées."}
    (OUT/"tendance-cartes.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"generated_utc":manifest["generated_utc"],
                      "cards":[{"id":x["id"],"size_bytes":x["size_bytes"],"title":x["title"]} for x in maps]},
                     ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
