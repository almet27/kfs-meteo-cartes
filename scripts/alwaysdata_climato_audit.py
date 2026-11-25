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
              "note":"24 UTC hourly bins are a preliminary coverage check, not validated daily extrema or rainfall totals."}
    out = BASE / "climato_audit.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    tmp.replace(out)
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
