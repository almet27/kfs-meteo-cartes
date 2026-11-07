"""Tests hors reseau de l'atlas RainViewer publie dans Discord."""
import io
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import build_atlas as radar


class RainViewerTests(unittest.TestCase):
    def test_coords_france(self):
        for name,lon,lat in radar.CITIES:
            x,y=radar.location_pixel(lon,lat)
            self.assertTrue(0<=x<radar.COLS*radar.SIZE,(name,x))
            self.assertTrue(0<=y<radar.ROWS*radar.SIZE,(name,y))

    def test_metadata_validation_et_age(self):
        now=1786090000
        entries=[{'time':now-i*600,'path':f'/v2/radar/{i+1:04d}'} for i in range(8)]
        host,past=radar.validate_catalog({
            'host':'https://tilecache.rainviewer.com',
            'radar':{'past':entries}},now)
        self.assertEqual(host,'https://tilecache.rainviewer.com')
        self.assertEqual(len(past),8)
        self.assertEqual([ts for ts,path in past],sorted(ts for ts,path in past))
        with self.assertRaisesRegex(RuntimeError,'ancienne'):
            radar.validate_catalog({'host':host,
                'radar':{'past':[{'time':now-3000,'path':'/v2/radar/a'},
                                   {'time':now-2400,'path':'/v2/radar/b'}]}},now)
        with self.assertRaisesRegex(RuntimeError,'Hote'):
            radar.validate_catalog({'host':'https://evil.example','radar':{'past':[]}},now)

    def test_genere_deux_frames_sans_reseau(self):
        # Une tuile de precipitations differente par observation.
        sample=[]
        for index in range(2):
            tile=Image.new('RGBA',(radar.SIZE,radar.SIZE),(0,0,0,0))
            for x in range(100+index*35,200+index*35):
                for y in range(100,200):
                    tile.putpixel((x,y),(16,96,220,210))
            sample.append(tile)
        def fake_tiles(host,path):
            idx=0 if path.endswith('/a') else 1
            return [(x,y,sample[idx]) for y in range(radar.Y0,radar.Y0+radar.ROWS)
                    for x in range(radar.X0,radar.X0+radar.COLS)]
        observations=[(1786090000,'/v2/radar/a'),(1786090600,'/v2/radar/b')]
        with patch.object(radar,'obtain_tiles',side_effect=fake_tiles):
            frames,counts=radar.build_frames('https://tilecache.rainviewer.com',observations,[])
        self.assertEqual(len(frames),2)
        self.assertEqual(counts,[9,9])
        with tempfile.TemporaryDirectory() as temp:
            gif=Path(temp)/'test.gif'
            frames[0].save(gif,save_all=True,append_images=frames[1:],
                           duration=700,loop=0,optimize=True,disposal=2)
            with Image.open(gif) as im:
                self.assertEqual(im.size,(1536,1536))
                self.assertEqual(im.n_frames,2)

if __name__=='__main__':
    unittest.main()
