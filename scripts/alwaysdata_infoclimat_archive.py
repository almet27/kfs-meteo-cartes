"""KFS: archive Infoclimat November 2026, separate from live observations.
Run on Alwaysdata only. Credentials stay in ~/.kfs-infoclimat (no logs of token).
Archive raw UTC measurements; daily completeness and units must be verified
before computing climate statistics.
"""
import datetime as dt
import fcntl
import json
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

BASE = Path.home() / "kfs-infoclimat"
START = dt.date(2026, 11, 1)
END = dt.date(2026, 11, 25)  # exclusive: through Nov 24
BATCH = 20

def fetch(url):
    return json.loads(subprocess.check_output(
        ["curl", "-4", "-fsS", "--max-time", "90", "--config", "-"],
        input=('url = "' + url + '"\n').encode()
    ))

def main():
    lock = (BASE / ".climatologie.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Archive deja en cours", flush=True)
        return
    token = (BASE / ".token").read_text().strip()
    catalogue = fetch("https://www.infoclimat.fr/opendata/stations_xhr.php?format=geojson")
    allowed = set()
    for f in catalogue["features"]:
        p = f["properties"]
        lic = p.get("license") or {}
        if (p.get("country") == "FR" and lic.get("source") == "infoclimat.fr"
                and str(lic.get("code")) in ("0", "1") and p.get("id")):
            allowed.add(str(p["id"]))
    live = json.loads((BASE / "latest.json").read_text())
    stations = sorted(allowed.intersection(live))
    if not stations:
        raise SystemExit("Aucune station eligible")
    print("Stations candidates :", len(stations), flush=True)
    db = sqlite3.connect(BASE / "climatologie.sqlite", timeout=30)
    db.execute("CREATE TABLE IF NOT EXISTS observations (station TEXT, dh_utc TEXT, data TEXT, PRIMARY KEY(station,dh_utc))")
    db.execute("CREATE TABLE IF NOT EXISTS collected (station TEXT, debut TEXT, fin TEXT, PRIMARY KEY(station,debut,fin))")
    db.commit()
    start = START
    while start < END:
        stop = min(start + dt.timedelta(days=6), END)
        pending = [s for s in stations if not db.execute(
            "SELECT 1 FROM collected WHERE station=? AND debut=? AND fin=?",
            (s, str(start), str(stop))).fetchone()]
        for i in range(0, len(pending), BATCH):
            batch = pending[i:i+BATCH]
            params = [("method","get"),("format","json"),("token",token),
                      ("start",str(start)),("end",str(stop))]
            params.extend(("stations[]",s) for s in batch)
            try:
                with (BASE / ".collect.lock").open("a") as live_lock:
                    fcntl.flock(live_lock, fcntl.LOCK_EX)
                    data = fetch("https://www.infoclimat.fr/opendata/?" + urlencode(params))
                if str(data.get("status")).lower() != "ok" or not isinstance(data.get("hourly"),dict):
                    raise ValueError("Unexpected API response")
            except Exception:
                raise SystemExit("Collecte interrompue; relancer pour reprendre") from None
            for s in batch:
                count = 0
                rows = data["hourly"].get(s, [])
                if not isinstance(rows,list):
                    continue
                for row in rows:
                    if not isinstance(row,dict):
                        continue
                    dh = row.get("dh_utc")
                    try:
                        when = dt.datetime.strptime(dh, "%Y-%m-%d %H:%M:%S")
                    except (ValueError,TypeError):
                        continue
                    if not start <= when.date() < stop:
                        continue
                    db.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?)",
                               (s,dh,json.dumps(row,ensure_ascii=False)))
                    count += 1
                # A successful nonempty request is recorded, not certified complete.
                if count:
                    db.execute("INSERT OR IGNORE INTO collected VALUES (?,?,?)",
                               (s,str(start),str(stop)))
            db.commit()
            print(start, stop, min(i+BATCH,len(pending)), "/",len(pending),flush=True)
            time.sleep(2)
        start = stop
    print("Stations archivees :",db.execute("SELECT COUNT(DISTINCT station) FROM observations").fetchone()[0],flush=True)
    print("Nombre de releves :",db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],flush=True)
    db.close()

if __name__ == "__main__":
    main()
