"""Read-only audit of KFS Infoclimat SQLite archive. No network or secrets.
UTC hourly coverage is diagnostic only, not certification of climatological days.
"""
import collections
import datetime as dt
import json
import math
import sqlite3
from pathlib import Path

BASE = Path.home() / "kfs-infoclimat"
START = dt.date(2026, 11, 1)
END = dt.date(2026, 11, 25)
FIELDS = {"temperature": (-60, 65), "vent_rafales": (0, 400),
          "pluie_1h": (0, 200), "pluie_3h": (0, 400)}

def archive_diagnostic():
    import shutil
    # Fixed local paths only; no credentials, raw logs or arbitrary file output.
    free = shutil.disk_usage(BASE).free
    sizes = {}
    for label,name in (("raw_archive","climatologie.sqlite"),("compact_archive","climatologie_journaliere.sqlite")):
        p=BASE/name
        sizes[label]=p.stat().st_size if p.is_file() and not p.is_symlink() else 0
    kind="unknown"
    log=BASE/".mcp_jobs"/"archive.log"
    if log.is_file() and not log.is_symlink():
        with log.open("rb") as f:
            f.seek(max(0,log.stat().st_size-32768))
            tail=f.read(32768).decode("utf-8","replace").lower()
        categories=(
            ("disk_guard","espace disque insuffisant"),
            ("account_disk_quota","disk quota exceeded"),
            ("disk_full","no space left on device"),
            ("sqlite_full","database or disk is full"),
            ("sqlite_locked","database is locked"),
            ("sqlite_open_error","unable to open database file"),
            ("permission_denied","permissionerror"),
            ("api_or_quota","source unavailable or quota"),
            ("catalogue_http_or_curl","calledprocesserror"),
            ("source_timeout","timeoutexpired"),
            ("json_response_invalid","jsondecodeerror"),
            ("missing_file","filenotfounderror"),
            ("no_eligible_stations","aucune station eligible"),
            ("python_import_error","modulenotfounderror"),
            ("sqlite_schema_error","operationalerror"),
        )
        for label,pattern in categories:
            if pattern in tail:
                kind=label
                break
        if not tail.strip():
            kind="empty_log"
    status_file=BASE/"climatologie_journaliere_status.json"
    progress={}
    if status_file.is_file() and not status_file.is_symlink() and status_file.stat().st_size<=65536:
        try:
            d=json.loads(status_file.read_text())
            for k in ("daily_rows","stations_with_daily_rows","collected_windows","requests_this_run","db_bytes"):
                v=d.get(k)
                if isinstance(v,int) and not isinstance(v,bool) and v>=0:progress[k]=v
        except (ValueError,OSError,AttributeError):
            pass
    return {"archive_failure_category":kind,"filesystem_free_bytes":free,
            "database_bytes":sizes,"historical_progress":progress,
            "warning":"Filesystem free space is not the hosting account quota."}


def main():
    days = collections.defaultdict(lambda: [0] * len(FIELDS))
    fields = collections.Counter()
    valid = collections.Counter()
    minutes = collections.Counter()
    invalid = 0
    stations = set()
    first = last = None
    n = 0
    with sqlite3.connect((BASE / "climatologie.sqlite").as_uri()+"?mode=ro", uri=True, timeout=30) as db:
        for sid, stamp, raw in db.execute("SELECT station,dh_utc,data FROM observations WHERE dh_utc>=? AND dh_utc<?", (str(START), str(END))):
            n += 1
            try:
                t = dt.datetime.fromisoformat(stamp)
                row = json.loads(raw)
                if not isinstance(row, dict):
                    raise ValueError()
            except (ValueError, TypeError):
                invalid += 1
                continue
            stations.add(sid)
            first = min(first,stamp) if first else stamp
            last = max(last,stamp) if last else stamp
            minutes[t.minute] += 1
            fields.update(row.keys())
            masks = days[(sid,t.date())]
            for i,(key,(lo,hi)) in enumerate(FIELDS.items()):
                v = row.get(key)
                if isinstance(v,bool): continue
                try: v = float(v)
                except (ValueError,TypeError): continue
                if math.isfinite(v) and lo<=v<=hi:
                    masks[i] |= 1<<t.hour
                    valid[key] += 1
    full = collections.Counter()
    complete_days = {k:collections.Counter() for k in FIELDS}
    for (sid,date), masks in days.items():
        for i,k in enumerate(FIELDS):
            if masks[i] == (1<<24)-1:
                complete_days[k][sid]+=1
                full[k]+=1
    target = (END-START).days
    report = {"period_utc":[str(START),str(END)],"days_expected":target,
              "rows":n,"stations":len(stations),"first_utc":first,"last_utc":last,
              "invalid_rows":invalid,"fields":dict(fields),
              "valid_values":dict(valid),
              "top_minutes":minutes.most_common(12),
              "station_days_24_hour_bins":dict(full),
              "stations_all_days_24_hour_bins":{
                  k:sum(c==target for c in counts.values())
                  for k,counts in complete_days.items()},
              "note":"24 UTC hourly bins are a preliminary coverage check, not validated daily extrema or rainfall totals. Archive diagnostic: "+json.dumps(archive_diagnostic(),sort_keys=True)}
    out = BASE / "climato_audit.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    tmp.replace(out)
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
