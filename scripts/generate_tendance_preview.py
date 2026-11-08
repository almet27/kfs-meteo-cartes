#!/usr/bin/env python3
"""Build a clearly labelled KFS Meteo /tendance preview from real published maps.

Not a four-week forecast. Weeks 3/4 remain unavailable until current IFS Extended
ensemble anomalies are retrievable and verified. No Discord or webhook requests.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path("forecast-maps")
EUROPE = ROOT / "europe"
DEST = ROOT / "tendance"
DEST.mkdir(parents=True, exist_ok=True)
DARK = "#111d32"
BLUE = "#193354"
MUTED = "#aabbd0"
WHITE = "#f5f9ff"
CYAN = "#55d8ef"
W = 1200
H = 2120

def font(size: int, bold: bool = False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans" + ("-Bold.ttf" if bold else ".ttf")
    return ImageFont.truetype(path, size)

def load_manifest():
    p = EUROPE / "metadata.json"
    meta = json.loads(p.read_text(encoding="utf8"))
    generated = datetime.fromisoformat(meta["generated_utc"].replace("Z", "+00:00"))
    age_hours = (datetime.now(timezone.utc) - generated).total_seconds() / 3600
    if age_hours < -1 or age_hours > 48:
        raise RuntimeError("Le catalogue IFS n'est pas assez recent (age en heures: %.1f)." % age_hours)
    return meta

def image_for(meta, model: str, step: str, metric: str) -> Path:
    path = meta["maps"][model][step][metric]
    file = EUROPE / Path(path).name
    if not file.is_file():
        raise FileNotFoundError(file)
    return file

def rounded(d, rect, fill, radius=25, outline=None):
    d.rounded_rectangle(rect, radius=radius, fill=fill, outline=outline, width=2)

def text(d, xy, message, sz, fill=WHITE, bold=False):
    d.text(xy, message, font=font(sz, bold), fill=fill)

def card(canvas, d, y, label, headline, caption, source, date_line):
    x1, x2 = 48, W - 48
    block_h = 495
    rounded(d, (x1, y, x2, y + block_h), BLUE)
    text(d, (x1 + 24, y + 18), label, 25, CYAN, True)
    text(d, (x1 + 24, y + 61), headline, 30, WHITE, True)
    with Image.open(source) as original:
        im = ImageOps.contain(original.convert("RGB"), (1044, 326), Image.Resampling.LANCZOS)
        canvas.paste(im, (x1 + (1104-im.width)//2, y + 104 + (326-im.height)//2))
    text(d, (x1 + 24, y + 446), caption, 19, WHITE)
    text(d, (x1 + 24, y + 469), date_line, 15, MUTED)
    return y + block_h

def unavailable(d, y, label):
    x1, x2 = 48, W - 48
    rounded(d, (x1, y, x2, y + 183), "#1c2940", outline="#48566c")
    text(d, (x1 + 24, y + 17), label, 24, CYAN, True)
    text(d, (x1 + 24, y + 58), "Tendance non disponible", 30, WHITE, True)
    text(d, (x1 + 24, y + 109), "En attente des anomalies hebdomadaires IFS Extended", 21, MUTED)
    return y + 183

def main():
    meta = load_manifest()
    samples = [
        ("SEMAINE 1  |  J+1 A J+7", "Exemple synoptique IFS a +72 h",
         "Z500 / pression ; illustration, pas moyenne hebdomadaire", "72", "z500_msl"),
        ("SEMAINE 2  |  J+8 A J+14", "Exemple synoptique IFS a +240 h",
         "Temperature 850 hPa ; pas une anomalie hebdomadaire", "240", "t850"),
    ]
    canvas = Image.new("RGB", (W, H), DARK)
    d = ImageDraw.Draw(canvas)
    text(d, (48, 39), "KFS METEO", 54, CYAN, True)
    text(d, (48, 109), "TENDANCE 4 SEMAINES", 43, WHITE, True)
    text(d, (48, 175), "MAQUETTE TECHNIQUE — NE PAS PUBLIER COMME PREVISION", 20, "#ffce84", True)
    text(d, (48, 212), "France et Europe de l'Ouest  |  Donnees : ECMWF Open Data", 22, MUTED)
    y = 265
    for label, title, caption, step, metric in samples:
        src = image_for(meta, "ifs", step, metric)
        run = meta.get("runs_utc", {}).get("ifs", {}).get(step, "inconnu")
        y = card(canvas, d, y, label, title, caption, src, "Run IFS : " + run)
        y += 23
    y = unavailable(d, y, "SEMAINE 3  |  J+15 A J+21") + 22
    y = unavailable(d, y, "SEMAINE 4  |  J+22 A J+28") + 35
    text(d, (48, y), "Les cartes J+3 et J+10 illustrent une echeance precise.", 23, MUTED)
    text(d, (48, y + 34), "Aucun scenario mensuel ou niveau de confiance n'est invente.", 23, MUTED)
    text(d, (48, H - 90), "Source : ECMWF Open Data (CC BY 4.0) — Maquette hors diffusion", 20, CYAN)
    text(d, (48, H - 54), "Generation : " + datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"), 19, MUTED)
    png = DEST / "tendance-apercu.png"
    canvas.save(png, format="PNG", optimize=True)
    summary = {
        "status": "preview_only",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "preview_path": str(png),
        "data_source": "ECMWF Open Data",
        "weekly_anomalies_verified": False,
        "discord_published": False,
        "week_1_and_2": "single-step synoptic examples; not weekly composites",
        "week_3_and_4": "no verified current IFS Extended source",
    }
    (DEST / "tendance-apercu.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(summary, ensure_ascii=False))

if __name__ == "__main__":
    main()
