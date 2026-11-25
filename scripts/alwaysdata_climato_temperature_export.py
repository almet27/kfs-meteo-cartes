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


EXTRA = BASE / "climato_rain_wind_export.json"

def number(row, key, upper):
    v = row.get(key)
    if v is None or isinstance(v, bool):
        return None
    try:
        v = float(v)
    except (ValueError, TypeError):
        return None
    return v if math.isfinite(v) and 0 <= v <= upper else None

def local_extra():
    stations = catalog()
    records = []
    stop = END + dt.timedelta(days=1)
    n_days = (stop - START).days
    start_time = dt.datetime.combine(START, dt.time())
    stop_time = dt.datetime.combine(stop, dt.time())
    with sqlite3.connect((BASE / "climatologie.sqlite").as_uri()+"?mode=ro",
                         uri=True, timeout=30) as db:
        ids = [r[0] for r in db.execute("SELECT DISTINCT station FROM observations")]
        for sid in sorted(ids):
            if sid not in stations:
                continue
            rain1, rain3, wind, gust = {}, {}, {}, {}
            for stamp, raw in db.execute(
                "SELECT dh_utc,data FROM observations WHERE station=? AND dh_utc>=? AND dh_utc<=? ORDER BY dh_utc",
                (sid, start_time.isoformat(" "), stop_time.isoformat(" "))):
                try:
                    t = dt.datetime.fromisoformat(stamp)
                    row = json.loads(raw)
                    if not isinstance(row, dict):
                        continue
                except (ValueError, TypeError):
                    continue
                if t.minute == 0 and t.second == 0 and start_time < t <= stop_time:
                    v = number(row, "pluie_1h", 200)
                    if v is not None:
                        rain1[t] = v
                    v = number(row, "pluie_3h", 400)
                    if t.hour % 3 == 0 and v is not None:
                        rain3[t] = v
                if not start_time <= t < stop_time:
                    continue
                h = t.replace(minute=0, second=0, microsecond=0)
                v = number(row, "vent_moyen", 250)
                if v is not None:
                    b = wind.setdefault(h, [0.0, 0])
                    b[0] += v
                    b[1] += 1
                v = number(row, "vent_rafales", 350)
                if v is not None and (h not in gust or v > gust[h][0]):
                    gust[h] = [v, stamp]
            rr, rain_days, rain_3h_days, disagreement = 0.0, 0, 0, 0
            for i in range(n_days):
                d = start_time + dt.timedelta(days=i)
                one = [rain1.get(d+dt.timedelta(hours=h)) for h in range(1,25)]
                three = [rain3.get(d+dt.timedelta(hours=h)) for h in range(3,25,3)]
                a = sum(one) if all(v is not None for v in one) else None
                b = sum(three) if all(v is not None for v in three) else None
                if a is not None and b is not None and abs(a-b) > max(1.0,0.1*max(a,b)):
                    disagreement += 1
                    continue
                if a is not None:
                    rr += a
                    rain_days += 1
                elif b is not None:
                    rr += b
                    rain_days += 1
                    rain_3h_days += 1
            best = max(gust.values(),key=lambda x:x[0]) if gust else None
            records.append({**stations[sid],
                "rain_mm":round(rr,2) if rain_days else None,
                "rain_days":rain_days, "rain_3h_days":rain_3h_days,
                "rain_disagreement_days":disagreement,
                "wind_mean_kmh":round(sum(a/n for a,n in wind.values())/len(wind),2) if wind else None,
                "wind_hours":len(wind),
                "gust_max_kmh":best[0] if best else None,
                "gust_date_utc":best[1] if best else None,
                "gust_hours":len(gust)})
    report = {"schema":1,"source":"Infoclimat - stations ouvertes",
              "start":str(START),"end":str(END),"expected_days":n_days,
              "expected_hours":n_days*24,
              "method":"Rain: complete nonoverlapping hourly or 3h windows ending at exact UTC boundaries, assumed trailing accumulations; days with inconsistent complete 1h/3h totals excluded. Partial totals only on complete days. Wind: equal weighting of valid hourly sample means; gust: largest reported sample, not certified maximum. Coverage per metric. No missing value treated as zero.",
              "stations":records}
    tmp = EXTRA.with_suffix(".tmp")
    tmp.write_text(json.dumps(report,separators=(",",":")))
    tmp.replace(EXTRA)
    print("Rain/wind export:",len(records),"stations; full rain:",sum(r["rain_days"]==n_days for r in records),flush=True)

def lire_export_pluie_vent(offset:int=0,limite:int=50)->dict:
    """Read only aggregated public station rain and wind data and coverage, never raw files."""
    import fcntl
    if not 0<=offset<=2000 or not 1<=limite<=100:
        return {"statut":"Parametres invalides"}
    with (BASE/".climato_temperature_export.lock").open("a") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return {"statut":"Export en cours"}
        if not EXTRA.is_file() or EXTRA.is_symlink() or EXTRA.stat().st_size>2000000:
            return {"statut":"Export indisponible"}
        d=json.loads(EXTRA.read_text())
        if d.get("schema")!=1 or not isinstance(d.get("stations"),list):
            return {"statut":"Rapport invalide"}
        rows=d["stations"]
        keys=("id","lon","lat","license","rain_mm","rain_days","rain_3h_days",
              "rain_disagreement_days","wind_mean_kmh","wind_hours","gust_max_kmh","gust_date_utc","gust_hours")
        return {"statut":"Export disponible",**{k:d[k] for k in ("source","start","end","expected_days","expected_hours","method")},
                "total":len(rows),"offset":offset,"next_offset":offset+limite if offset+limite<len(rows) else None,
                "stations":[{k:r[k] for k in keys if k in r} for r in rows[offset:offset+limite]]}

if __name__ == "__main__":
    main()
    local_extra()
