#!/usr/bin/env python3
"""Zoom radar GIF diagnostic sur une commune francaise (non valide pour diffusion)."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageSequence
from pyproj import Transformer

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--entree',required=True,type=Path)
    p.add_argument('--sortie',required=True,type=Path)
    p.add_argument('--ville',required=True)
    p.add_argument('--horodatages',type=Path)
    p.add_argument('--latitude',type=float,required=True)
    p.add_argument('--longitude',type=float,required=True)
    p.add_argument('--rayon-km',type=float,default=180)
    a=p.parse_args()
    if not 41 <= a.latitude <= 52 or not -6 <= a.longitude <= 10:
        p.error('Coordonnees hors France metropolitaine')
    if not 30 <= a.rayon_km <= 350:
        p.error('Rayon attendu entre 30 et 350 km')
    # Projection identique au trace candidat; calibration graphique encore provisoire.
    transformer=Transformer.from_crs('EPSG:4326',
        '+proj=lcc +lat_1=45 +lat_0=45 +lon_0=0 +datum=WGS84 +units=m +no_defs',
        always_xy=True)
    x,y=transformer.transform(a.longitude,a.latitude)
    times=json.loads(a.horodatages.read_text()) if a.horodatages else []
    frames=[]; durations=[]
    with Image.open(a.entree) as gif:
        for index,frame in enumerate(ImageSequence.Iterator(gif)):
            im=frame.convert('RGB')
            w,h=im.size
            # Zone des axes Matplotlib du radar candidat (fractions de la figure).
            left,right=0.092*w,0.970*w
            top,bottom=0.0355*h,0.9215*h
            # Limites fixes des axes du radar candidat, a confirmer avant diffusion.
            xmin,xmax=-550000.,650000.
            ymin,ymax=-250000.,850000.
            cx=left+(x-xmin)/(xmax-xmin)*(right-left)
            cy=bottom-(y-ymin)/(ymax-ymin)*(bottom-top)
            rx=(a.rayon_km*1000)/(xmax-xmin)*(right-left)
            ry=(a.rayon_km*1000)/(ymax-ymin)*(bottom-top)
            crop=im.crop((round(cx-rx),round(cy-ry),round(cx+rx),round(cy+ry)))
            crop=crop.resize((720,720),Image.Resampling.LANCZOS)
            d=ImageDraw.Draw(crop)
            d.rectangle((0,0,720,62),fill='#152536')
            d.text((18,12),f'Radar {a.ville} | rayon {a.rayon_km:g} km',fill='white')
            stamp=times[index].replace('T',' ').replace('Z',' UTC') if index<len(times) else 'heure inconnue'
            d.text((18,35),stamp+' | NON VALIDE',fill='#ff9b9b')
            d.ellipse((353,353,367,367),fill='#ff2020',outline='white',width=2)
            d.line((360,341,360,379),fill='white',width=2)
            d.line((341,360,379,360),fill='white',width=2)
            frames.append(crop)
            durations.append(frame.info.get('duration',650))
    if len(frames)<2:
        raise SystemExit('Le GIF source doit contenir au moins deux images.')
    a.sortie.parent.mkdir(parents=True,exist_ok=True)
    frames[0].save(a.sortie,save_all=True,append_images=frames[1:],
                   duration=durations,loop=0,optimize=True)
    print(f'Zoom diagnostic cree : {a.sortie} ({len(frames)} images)')
if __name__=='__main__':
    main()
