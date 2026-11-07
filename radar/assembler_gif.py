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
    parser.add_argument("--intervalle-max-minutes", type=int, default=15,
                        help="15 min pour une animation fiable ; jusqu'a 25 min en diagnostic avec avertissement")
    parser.add_argument("--validation-confirmee", action="store_true",
                        help="A utiliser UNIQUEMENT apres validation du georeferencement")
    parser.add_argument("--diagnostic", action="store_true",
                        help="GIF de test avec filigrane NON VALIDE, jamais pour diffusion")
    args = parser.parse_args()
    if args.diagnostic == args.validation_confirmee:
        parser.error("Choisir exactement un mode : --diagnostic OU --validation-confirmee.")
    if not 5 <= args.intervalle_max_minutes <= (25 if args.diagnostic else 15):
        parser.error("Intervalle maximal : 15 min en mode valide, 25 min en diagnostic.")
    if len(args.images) < 2:
        parser.error("Il faut au moins deux observations distinctes pour une animation.")
    if not 100 <= args.duree_ms <= 5000:
        parser.error("La duree d'une image doit etre entre 100 et 5000 ms.")
    ordered = sorted((instant(p), p) for p in args.images)
    times = [t for t, _ in ordered]
    if len(set(times)) != len(times):
        parser.error("Horodatages en double : chaque image doit correspondre a une observation distincte.")
    gaps = [(b-a).total_seconds()/60 for a, b in zip(times, times[1:])]
    if any(gap > args.intervalle_max_minutes for gap in gaps):
        parser.error(f"Intervalle de plus de {args.intervalle_max_minutes} min : animation discontinue.")
    if args.diagnostic:
        for gap in gaps:
            if gap > 15:
                print(f"AVERTISSEMENT : trou de {gap:g} min entre deux observations BUFR. "
                      "Aucune image n'a ete inventee.", flush=True)
    frames = []
    size = None
    for index, (timestamp, path) in enumerate(ordered):
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
        if args.diagnostic:
            warning = "RADAR NON VALIDE - DIAGNOSTIC UNIQUEMENT"
            draw.rectangle((8, 46, 420, 79), fill="#8b1723")
            draw.text((15, 55), warning, fill="white")
            if index < len(gaps) and gaps[index] > 15:
                note = f"TROU : prochain radar dans {gaps[index]:g} min"
                draw.rectangle((8, 85, 320, 116), fill="#9a3412")
                draw.text((15, 94), note, fill="white")
        frames.append(frame)
    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    # Duree proportionnelle a l'intervalle reel : une lacune n'accelere pas artificiellement l'animation.
    durations = [max(150, min(3000, round(args.duree_ms * gap / 10))) for gap in gaps]
    durations.append(args.duree_ms)
    frames[0].save(args.sortie, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    print(f"GIF cree : {args.sortie} ({len(frames)} observations, {times[0]} a {times[-1]})")

if __name__ == "__main__":
    main()
