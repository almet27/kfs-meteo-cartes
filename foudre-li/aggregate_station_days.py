#!/usr/bin/env python3
"""Aggregate validated daily EUMETSAT station coverage without treating absent days as zero."""
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from parallax import METHOD
root=Path("data/eumetsat-li")
months=defaultdict(dict)
for path in sorted((root/"daily").glob("????-??-??.json")):
    d=json.loads(path.read_text())
    day=date.fromisoformat(path.stem)
    if d.get("schema")!=1 or d.get("date")!=path.stem or d.get("pilot") is not False or d.get("complete") is not True or d.get("parallax")!=METHOD or d.get("radius_km")!=15:
        raise ValueError(f"Invalid daily source {path}")
    if d.get("coverage_fraction",0)<.995 or d.get("max_gap_seconds",999)>30:
        raise ValueError(f"Incomplete day {path}")
    ids=d["station_ids"]; hits=d["stations_with_flashes"]
    if len(ids)!=len(set(ids)) or not set(hits)<=set(ids) or len(ids)!=d["station_count"]:
        raise ValueError(f"Invalid stations {path}")
    months[path.stem[:7]][path.stem]=(ids,hits)
for month,days in months.items():
    stations=defaultdict(lambda: {"valid":[],"active":[]})
    for day,(ids,hits) in days.items():
        for sid in ids:
            stations[sid]["valid"].append(int(day[-2:]))
            if hits.get(sid,0)>0: stations[sid]["active"].append(int(day[-2:]))
    payload={"schema":1,"month":month,"source":"EUMETSAT MTG LI LFL","radius_km":15,"parallax":METHOD,"timezone":"Europe/Paris","stations":stations}
    out=root/"monthly"/(month+".json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,separators=(",",":"))+"\n")
