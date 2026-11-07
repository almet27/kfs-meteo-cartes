"""Tests synthetiques de non-regression : aucune donnee Meteo-France necessaire."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from radar import zoom_ville, assembler_gif


class TestRadarZoom(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.grids = self.root / 'grids'
        self.grids.mkdir()
        self.times = ['2026-11-07T11:10:00Z', '2026-11-07T11:20:00Z']
        (self.root / 'radar-images.json').write_text(json.dumps(self.times))

    def write_grid(self, minute, x0=-664972.4748):
        image = np.zeros((1536, 1536), dtype=np.float32)
        image[600+minute:650+minute, 600:650] = 32.0
        np.savez_compressed(
            self.grids / f'radar-grid-2026-11-07T11-{10+minute:02d}-00Z.npz',
            reflectivite=image, x0_m=x0, y0_m=1009030.6272,
            dx_m=1000.0, dy_m=1000.0,
            proj4='+proj=lcc +lat_1=45 +lat_0=45 +lon_0=0 +datum=WGS84 +units=m +no_defs',
            observation_utc=f'2026-11-07T11:{10+minute:02d}:00+00:00')

    def run_zoom(self):
        params = ['zoom_ville.py', '--dossier-grilles', str(self.grids),
                  '--horodatages', str(self.root / 'radar-images.json'),
                  '--sortie', str(self.root / 'zoom.gif'),
                  '--ville', 'Bourth', '--latitude', '48.77', '--longitude', '0.81']
        with patch.object(sys, 'argv', params), patch.object(zoom_ville, 'FONDS', []):
            zoom_ville.main()

    def test_deux_grilles_generent_gif_horodate(self):
        self.write_grid(0)
        self.write_grid(10)
        self.run_zoom()
        with Image.open(self.root / 'zoom.gif') as gif:
            self.assertEqual(gif.n_frames, 2)
            self.assertEqual(gif.size, (720, 720))
        metadata = json.loads((self.root / 'zoom.json').read_text())
        self.assertEqual(len(metadata['observations_utc']), 2)
        self.assertFalse(metadata['diffusion_discord_autorisee'])

    def test_huit_observations_regulieres_generent_huit_images(self):
        minutes=list(range(0,40,5))
        self.times=[f'2026-11-07T11:{10+m:02d}:00Z' for m in minutes]
        (self.root / 'radar-images.json').write_text(json.dumps(self.times))
        for minute in minutes:
            self.write_grid(minute)
        self.run_zoom()
        with Image.open(self.root / 'zoom.gif') as gif:
            self.assertEqual(gif.n_frames, 8)
            self.assertEqual(gif.size, (720, 720))
        metadata=json.loads((self.root / 'zoom.json').read_text())
        self.assertEqual(metadata['intervalles_minutes'], [5.0]*7)
        self.assertFalse(metadata['diffusion_discord_autorisee'])

    def test_geometries_incoherentes_refusees(self):
        self.write_grid(0)
        self.write_grid(10, x0=-664900.0)
        with self.assertRaisesRegex(ValueError, 'Geometrie incoherente'):
            self.run_zoom()
        self.assertFalse((self.root / 'zoom.gif').exists())

    def test_une_grille_ne_genere_pas_de_faux_gif(self):
        self.write_grid(0)
        self.run_zoom()
        self.assertFalse((self.root / 'zoom.gif').exists())


    def test_lacune_20_minutes_acceptee_seulement_en_diagnostic(self):
        source = []
        for label, couleur in [('11-35-00', '#215c91'), ('11-55-00', '#9b4120')]:
            path = self.root / f'radar-candidat-2026-11-07T{label}Z.png'
            Image.new('RGB', (160, 120), couleur).save(path)
            source.append(str(path))
        params = ['assembler_gif.py', '--diagnostic', '--sortie',
                  str(self.root / 'test-gap.gif')] + source
        with patch.object(sys, 'argv', params), self.assertRaises(SystemExit):
            assembler_gif.main()  # seuil par defaut : 15 minutes
        self.assertFalse((self.root / 'test-gap.gif').exists())
        params[2:2] = ['--intervalle-max-minutes', '25']
        with patch.object(sys, 'argv', params):
            assembler_gif.main()
        with Image.open(self.root / 'test-gap.gif') as gif:
            self.assertEqual(gif.n_frames, 2)
            self.assertGreaterEqual(gif.info['duration'], 1200)


if __name__ == '__main__':
    unittest.main()
