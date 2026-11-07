#!/usr/bin/env python3
"""Assembler des images radar deja georeferencees en GIF chronologique.

Les PNG doivent representer la meme emprise, le meme style et la meme projection.
Usage:
 python radar/assembler_gif.py --validation-confirmee --sortie radar-sortie/radar-animation.gif \
   2026-11-07T11-00-00Z.png 2026-11-07T11-05-00Z.png

IMPORTANT: --validation-confirmee est une attestation manuelle, pas une validation automatique.
"""
import argparse
import datetime as dt
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)")
def instant(path):
    match = PATTERN.search(path.name)
    if not match:
        raise ValueError(f"Horodatage UTC absent du nom : {path.name} (attendu AAAA-MM-JJTHH-MM-SSZ)")
    return dt.datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=dt.timezone.utc)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--sortie", type=Path, required=True)
    parser.add_argument("--duree-ms", type=int, default=650)
    parser.add_argument("--validation-confirmee", action="store_true",
                        help="A utiliser UNIQUEMENT apres validation du georeferencement")
    args = parser.parse_args()
    if not args.validation_confirmee:
        parser.error("Georeferencement non confirme : refus de creer un GIF destine a la diffusion.")
    if len(args.images) < 2:
        parser.error("Il faut au moins deux observations distinctes pour une animation.")
    if not 100 <= args.duree_ms <= 5000:
        parser.error("La duree d'une image doit etre entre 100 et 5000 ms.")
    ordered = sorted((instant(p), p) for p in args.images)
    times = [t for t, _ in ordered]
    if len(set(times)) != len(times):
        parser.error("Horodatages en double : chaque image doit correspondre a une observation distincte.")
    if any((b-a).total_seconds() > 900 for a, b in zip(times, times[1:])):
        parser.error("Intervalle de plus de 15 min entre deux observations : animation discontinue.")
    frames = []
    size = None
    for timestamp, path in ordered:
        with Image.open(path) as source:
            frame = source.convert("RGB")
        if size is None:
            size = frame.size
        if frame.size != size:
            parser.error(f"Dimensions incompatibles pour {path.name}: {frame.size} au lieu de {size}.")
        draw = ImageDraw.Draw(frame)
        stamp = timestamp.strftime("%d/%m/%Y %H:%M UTC")
        draw.rectangle((8, 8, 265, 39), fill="#172b40")
        draw.text((15, 16), stamp, fill="white")
        frames.append(frame)
    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(args.sortie, save_all=True, append_images=frames[1:],
                   duration=args.duree_ms, loop=0, optimize=True)
    print(f"GIF cree : {args.sortie} ({len(frames)} observations, {times[0]} a {times[-1]})")

if __name__ == "__main__":
    main()
