"""Correction LFL par tables de parallaxe EUMETSAT SSP 0.
Les tables régionales sont préparées hors collecte par build_parallax_lut.py.
Aucune hauteur arbitraire, aucun déplacement sans table vérifiée.
"""
from datetime import datetime, timezone
from pathlib import Path
import math

METHOD = "EUMETSAT-SSP0-ice-CTH-2005-2018"
LUT = Path(__file__).with_name("parallax-lut.npz")


class Parallax:
    def __init__(self, path=LUT):
        import numpy as np
        with np.load(path, allow_pickle=False) as d:
            self.lat = d["lat"]
            self.lon = d["lon"]
            self.dlat = d["dlat"]
            self.dlon = d["dlon"]
            if str(d["method"].item()) != METHOD:
                raise ValueError("Source de table inattendue")
        shape = (12, len(self.lat), len(self.lon))
        if self.dlat.shape != shape or self.dlon.shape != shape:
            raise ValueError("Dimensions LUT incorrectes")
        if not (np.all(np.diff(self.lat) > 0) and np.all(np.diff(self.lon) > 0)
                and self.lat[0] <= 40.5 and self.lat[-1] >= 52
                and self.lon[0] <= -7.5 and self.lon[-1] >= 10):
            raise ValueError("Couverture LUT insuffisante")
        if not (np.isfinite(self.dlat).all() and np.isfinite(self.dlon).all()
                and np.max(np.abs(self.dlat)) < 1 and np.max(np.abs(self.dlon)) < 1):
            raise ValueError("Décalages LUT non valides")

    def correct(self, lat, lon, ts):
        import numpy as np
        t = datetime.fromtimestamp(ts, timezone.utc)
        mid = t.replace(day=15, hour=0, minute=0, second=0, microsecond=0)
        if t < mid:
            before = mid.replace(year=mid.year - (mid.month == 1),
                                 month=12 if mid.month == 1 else mid.month - 1)
            after = mid
        else:
            before = mid
            after = mid.replace(year=mid.year + (mid.month == 12),
                                month=1 if mid.month == 12 else mid.month + 1)
        w = (t-before).total_seconds()/(after-before).total_seconds()
        i = int(np.argmin(abs(self.lat-lat)))
        j = int(np.argmin(abs(self.lon-lon)))
        a, b = before.month-1, after.month-1
        return (float(lat+(1-w)*self.dlat[a,i,j]+w*self.dlat[b,i,j]),
                float(lon+(1-w)*self.dlon[a,i,j]+w*self.dlon[b,i,j]))

def apply(feed, table=None):
    # Always derive output from the original coordinates, not an earlier correction.
    for p in feed["flashes"]:
        lat = float(p.get("raw_lat", p["lat"]))
        lon = float(p.get("raw_lon", p["lon"]))
        p["raw_lat"], p["raw_lon"] = round(lat,5), round(lon,5)
        new_lat, new_lon = table.correct(lat,lon,p["ts"]) if table else (lat,lon)
        p["lat"], p["lon"] = round(new_lat,5), round(new_lon,5)
    feed["parallax"] = METHOD if table else "uncorrected"
    return feed
