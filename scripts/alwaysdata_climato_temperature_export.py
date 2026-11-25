"""KFS local climate: sampled UTC day extrema, one station at a time.
Read-only archive; no historical API requests; estimates, not certified records.
"""
import datetime as dt
import json
import math
from pathlib import Path
import sqlite3
import subprocess

BASE = Path.home() / "kfs-infoclimat"
START = dt.date(2026, 11, 1)
END = dt.date(2026, 11, 23)
OUT = BASE / "climato_temperature_export.json"
CATALOG = "https://www.infoclimat.fr/opendata/stations_xhr.php?format=geojson"

def catalog():
    raw = subprocess.check_output(["curl", "-4", "-fsSL", "--max-time", "60", CATALOG])
    result = {}
    for f in json.loads(raw)["features"]:
        p = f.get("properties", {})
        lic = p.get("license") or {}
        if not (p.get("country") == "FR" and lic.get("source") == "infoclimat.fr"
                and str(lic.get("code")) in ("0", "1") and p.get("id")):
            continue
        try:
            lon, lat = map(float, f["geometry"]["coordinates"][:2])
        except (ValueError, TypeError, KeyError):
            continue
        if -5.8 <= lon <= 10.1 and 41 <= lat <= 51.6:
            sid = str(p["id"])
            result[sid] = {"id": sid, "lon": round(lon, 5), "lat": round(lat, 5),
                           "license": str(lic["code"])}
    return result

def day_extrema(rows):
    hours = {}
    prev = None
    for stamp, raw in rows:
        try:
            t = dt.datetime.fromisoformat(stamp)
            v = json.loads(raw).get("temperature")
            if isinstance(v, bool):
                continue
            v = float(v)
        except (ValueError, TypeError, AttributeError):
            continue
        if not math.isfinite(v) or not -45 <= v <= 55:
            continue
        if prev is not None and t-prev > dt.timedelta(hours=1):
            return None
        prev = t
        b = hours.setdefault(t.hour, [v, v])
        b[0] = min(b[0], v)
        b[1] = max(b[1], v)
    if len(hours) != 24:
        return None
    return [round(min(b[0] for b in hours.values()), 2),
            round(max(b[1] for b in hours.values()), 2)]

def main():
    stations = catalog()
    records = []
    with sqlite3.connect((BASE / "climatologie.sqlite").as_uri()+"?mode=ro",
                         uri=True, timeout=30) as db:
        ids = [r[0] for r in db.execute("SELECT DISTINCT station FROM observations")]
        for sid in sorted(ids):
            if sid not in stations:
                continue
            days = []
            for i in range((END-START).days+1):
                d = START + dt.timedelta(days=i)
                rows = db.execute("SELECT dh_utc,data FROM observations WHERE station=? AND dh_utc>=? AND dh_utc<? ORDER BY dh_utc",
                                  (sid, str(d), str(d+dt.timedelta(days=1))))
                value = day_extrema(rows)
                if value is None:
                    break
                days.append(value)
            if days:
                records.append({**stations[sid], "days": days})
    if not records:
        raise SystemExit("No eligible station")
    report = {"schema": 1, "source": "Infoclimat - stations ouvertes",
              "start": str(START), "end": str(END),
              "method": "sampled UTC calendar-day extrema (00-24 UTC), 24 valid hourly bins, max 60 min between consecutive valid observations within day; mean of daily (Tmin+Tmax)/2; frost Tmin<=0; non-certified, not directly comparable to MF climate-day windows",
              "stations": records}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, separators=(",", ":")))
    tmp.replace(OUT)
    print("Export:",len(records),"stations;",sum(len(r["days"])==23 for r in records),"complete through Nov 23",flush=True)

if __name__ == "__main__":
    main()
