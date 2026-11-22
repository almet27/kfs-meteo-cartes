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
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageColor
from kfs_synoptic_overlays import AIR_STOPS, premium_pictogram

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


def write_premium_stage(stage, meta, data, now, risk_document):
    """Infographie européenne 16:9 : champs météorologiques réels et risques non inventés."""
    step=stage["step"]
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
    date=parsed(details["valid_utc"])
    hazards=next((a for a in risk_document["stages"] if a["id"]==stage["id"]),None)
    if not hazards or hazards["step_h"]!=int(step):
        raise RuntimeError("Données de risque manquantes "+stage["id"])
    if hazards.get("model")!="ifs":
        raise RuntimeError("Fond de risques non IFS "+stage["id"])
    if parsed(hazards["run_utc"])!=parsed(details["run_utc"]):
        raise RuntimeError("Run de risques désynchronisé "+stage["id"])
    if parsed(hazards["valid_utc"])!=date:
        raise RuntimeError("Validité carte/risques différente")
    risk_map=Path(hazards["background_path"])
    if not risk_map.is_file() or risk_map.stat().st_size<20000:
        raise RuntimeError("Fond géoréférencé non généré")
    # Carte bord à bord, comme la maquette validée. Aucun recadrage géographique.
    W2,H2=1600,940
    canvas=Image.new("RGBA",(W2,H2),"#EEF0F2")
    with Image.open(risk_map) as src:
        hero=src.convert("RGBA")
    if hero.size!=(1600,700):
        raise RuntimeError("Le fond doit mesurer 1600x700 pixels")
    canvas.alpha_composite(hero,(0,0))
    d=ImageDraw.Draw(canvas)
    ink="#162E4C"
    muted="#506174"
    blue="#355579"
    # Titres flottants, compacts : fond neutre et accent anthracite.
    d.rounded_rectangle((14,12,561,88),radius=15,fill="#F1F3F5",outline="#D2D7DC",width=1)
    d.rounded_rectangle((14,12,23,88),radius=4,fill=blue)
    txt(d,(36,17),"Tendance météo",32,ink,True)
    txt(d,(38,56),"KFS MÉTÉO  •  Situation et masses d’air",17,muted)
    d.rounded_rectangle((904,12,1586,88),radius=15,fill="#F1F3F5",outline="#D2D7DC",width=1)
    txt(d,(923,20),"Échéance : "+stage["period"],24,ink,True)
    txt(d,(924,53),date.strftime("%d/%m/%Y  %HZ")+"  •  Carte IFS",16,muted)
    d.line((1181,25,1181,75),fill="#CED4DB",width=2)
    txt(d,(1195,20),"ECMWF IFS · "+parsed(details["run_utc"]).strftime("%HZ"),19,ink,True)
    comparisons="AIFS "+parsed(other_run).strftime("%HZ")
    if gfs_ready:comparisons+=" • GFS "+parsed(gfs_record["run_utc"]).strftime("%HZ")
    txt(d,(1195,54),comparisons,16,muted)

    # Footer: scale, four actual calculated hazard types, dynamic summary.
    d.rounded_rectangle((0,700,1600,940),radius=16,fill="#F3F4F6",outline="#D4D9DF",width=1)
    for x in (398,1040):
        d.line((x,719,x,905),fill="#C5CCD4",width=2)
    txt(d,(25,717),"Température à 850 hPa",22,ink,True)
    txt(d,(25,751),"≈ 1 500 m d’altitude",17,muted)
    left,right=27,370
    stops=[(t,ImageColor.getrgb(col)) for t,col in AIR_STOPS]
    for x in range(left,right+1):
        t=(x-left)/(right-left)
        for (t0,c0),(t1,c1) in zip(stops,stops[1:]):
            if t<=t1:
                f=(t-t0)/(t1-t0)
                col=tuple(round(c0[k]*(1-f)+c1[k]*f) for k in range(3))
                d.line((x,790,x,817),fill=col,width=1)
                break
    for label,value in [("-20",0),("-10",.25),("0",.5),("+10",.75),("+20 °C",1)]:
        x=left+round((right-left)*value)
        d.line((x,818,x,824),fill=muted,width=1)
        tw=d.textlength(label,font=font(13,True))
        txt(d,(max(12,min(385-tw,x-tw/2)),831),label,13,ink,True)
    txt(d,(25,865),"T850 moy. France : %+.1f °C"%t850,16,ink,True)
    txt(d,(25,887),"Isobares : 5 hPa  •  H / D",14,muted)

    def pill(x,y,label):
        width=int(d.textlength(label,font=font(19,True)))+24
        d.rounded_rectangle((x,y,x+width,y+30),radius=10,fill=blue)
        txt(d,(x+12,y+3),label,19,"#FFFFFF",True)
    pill(415,712,"Risques atmosphériques · 6 h")
    entries=[
        ("pluie_forte","pluie_forte","Pluie","≥ 10 mm","! > 50 mm"),
        ("neige","neige","Neige hors relief","≥ 0,5 mm éq.","! ≥ 2 mm éq."),
        ("tempete","vent_fort","Rafales","≥ 50 km/h","! ≥ 100 km/h"),
        ("gel","gel","Gel (Tmin 2 m)","≤ 0 °C","! ≤ −10 °C"),
    ]
    for i,(key,kind,label,normal,severe) in enumerate(entries):
        x=411+i*156
        if i:d.line((x,751,x,899),fill="#D5D9DF",width=1)
        icon=Image.fromarray(premium_pictogram(kind).get_data()).convert("RGBA")
        icon.thumbnail((57,57),Image.Resampling.LANCZOS)
        canvas.alpha_composite(icon,(x+78-icon.width//2,746))
        def centred(text,y,size,col,bold=False):
            tw=d.textlength(text,font=font(size,bold))
            txt(d,(x+78-tw/2,y),text,size,col,bold)
        centred(label,807,14,ink,True)
        centred(normal,829,14,muted)
        centred(severe,850,14,"#B7273C",True)
        risk=hazards["risks"][key]
        state=risk.get("status","indisponible")
        pretty={"absent":"Pas de signal","possible":"Possible","marque":"Marqué",
                "relief_uniquement":"Relief seul","indisponible":"Non calculé"}
        state_label="Sévère" if risk.get("severity")=="severe" else pretty.get(state,"Non calculé")
        centred(state_label,877,13,"#AE2839" if state=="marque" else "#506174",True)

    # Fact-based, independently composed for each forecast time.
    wind_dir=sector(flow.get("from_deg"))
    risks=hazards["risks"]
    marked_categories=[k for k,v in risks.items() if v.get("status")=="marque"]
    flux=("Flux d’" if wind_dir.startswith(("est","ouest")) else "Flux de ")+wind_dir
    sentence=flux+" sur la France, avec "+temp_desc(t850).lower()+"."
    signals=[]
    if risks["pluie_forte"].get("status") in ("possible","marque"):
        signals.append("pluie jusqu’à %.0f mm/6 h"%risks["pluie_forte"]["max"])
    if risks["tempete"].get("status") in ("possible","marque"):
        signals.append("rafales jusqu’à %.0f km/h"%risks["tempete"]["max"])
    if risks["neige"].get("status") in ("possible","marque"):
        signals.append("neige hors relief")
    if risks["gel"].get("status") in ("possible","marque"):
        signals.append("gel jusqu’à %.0f °C"%risks["gel"]["min"])
    if signals:sentence+=" Signaux sur France et abords : "+", ".join(signals)+"."
    elif all(risks[k].get("status")!="indisponible" for k, *_ in entries):
        sentence+=" Aucun signal notable parmi les quatre risques calculés."
    else:sentence+=" Aucun signal notable parmi les données disponibles."
    missing=[label for k,_,label,_,_ in entries if risks[k].get("status")=="indisponible"]
    if missing:sentence+=" Non calculé : "+", ".join(missing)+"."
    sentence+=" Confiance "+stage["confidence"].lower()+"."
    pill(1058,712,"Synthèse")
    def wrap_px(s,width,sz):
        lines=[];current=""
        for word in s.split():
            candidate=(current+" "+word).strip()
            if current and d.textlength(candidate,font=font(sz))>width:
                lines.append(current);current=word
            else:current=candidate
        if current:lines.append(current)
        return lines
    sz=20
    lines=wrap_px(sentence,513,sz)
    while len(lines)>7 and sz>15:
        sz-=1;lines=wrap_px(sentence,513,sz)
    for i,line in enumerate(lines):
        txt(d,(1058,750+i*(sz+4)),line,sz,ink)
    d.line((22,911,1578,911),fill="#D5D9DF",width=1)
    txt(d,(25,918),"Source : ECMWF Open Data • Comparaisons AIFS/GFS si disponibles • ! rouge = seuil KFS, pas une vigilance officielle.",12,muted)
    txt(d,(1322,918),"Prévision ponctuelle à "+step+" h",12,muted)
    out=OUT/("tendance-carte-"+stage["id"]+".png")
    canvas.convert("RGB").save(out,"PNG",optimize=True)
    runs={model_a.lower():details["run_utc"]}
    if other_run is not None:
        runs[model_b.lower()]=other_run
    if gfs_ready:
        runs["gfs"]=gfs_record["run_utc"]
    display_models=model_a+" / "+model_b+(" / GFS" if gfs_ready else "")
    return {"id":stage["id"],"step_h":int(step),"path":str(out),
       "image_url":"https://almet27.github.io/kfs-meteo-cartes/"+str(out),
       "size_bytes":out.stat().st_size, "run_utc":runs,
       "valid_utc":details["valid_utc"], "title":stage["period"]+" — synthèse synoptique "+display_models,
       "confidence_label":stage["confidence"]+" (indicative)",
       "marked_phenomena":marked_categories, "not_official_warning":True,
       "gfs_available":gfs_ready,
       "risk_status":"altitude_filtered_georeferenced", "risks":hazards["risks"], "risk_markers":hazards["markers"],
       "t850_shading":hazards.get("t850_shading",{}),
       "style":"kfs-editorial-plein-cadre-neutre-v11","summary":sentence,
       "note":"Carte géoréférencée bord à bord 1600x700, bandeau neutre et synthèse issue des champs IFS ; ! rouge = seuil KFS non officiel."}

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
