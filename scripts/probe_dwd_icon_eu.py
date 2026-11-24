#!/usr/bin/env python3
"""Read-only DWD ICON-EU pilot: verify four real forecast fields from one run.

No changes to operational products. No Open-Meteo calls. No assumption
that min/max/precip fields are daily totals: report native interval metadata.
"""
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path
import bz2, json, tempfile
from eccodes import codes_grib_new_from_file, codes_get, codes_release

BASE="https://opendata.dwd.de/weather/nwp/icon-eu/grib/"
FIELDS=("tmin_2m","tmax_2m","vmax_10m","tot_prec")
STEP=6
LIMIT=12*1024*1024

def download(cycle,field):
    name=("icon-eu_europe_regular-lat-lon_single-level_"+
          cycle.strftime("%Y%m%d%H")+f"_{STEP:03d}_{field.upper()}.grib2.bz2")
    url=BASE+cycle.strftime("%H")+"/"+field+"/"+name
    with urlopen(Request(url,headers={"User-Agent":"KFS-Meteo-DWD-Pilot/1.0"}),timeout=40) as r:
        payload=r.read(LIMIT+1)
    if len(payload)>LIMIT:
        raise ValueError("Unexpectedly large DWD test field")
    decoded=bz2.decompress(payload)
    if not decoded.startswith(b"GRIB"):
        raise ValueError("Not a GRIB message")
    with tempfile.TemporaryFile() as fp:
        fp.write(decoded);fp.seek(0)
        gid=codes_grib_new_from_file(fp)
        if gid is None:raise ValueError("No GRIB message")
        try:
            result={key:codes_get(gid,key) for key in (
                "dataDate","dataTime","startStep","endStep","stepType","shortName",
                "units","gridType","numberOfPoints","minimum","maximum")}
            if (int(result["dataDate"])!=int(cycle.strftime("%Y%m%d"))
                    or int(result["dataTime"])!=cycle.hour*100
                    or int(result["endStep"])!=STEP
                    or int(result["numberOfPoints"])<10000):
                raise ValueError("Wrong cycle, lead or grid")
            return {"url":url,"compressed_bytes":len(payload),**result}
        finally:
            codes_release(gid)

def main():
    now=datetime.now(timezone.utc)
    start=now.replace(hour=now.hour//3*3,minute=0,second=0,microsecond=0)
    for lag in range(1,5):
        cycle=start-timedelta(hours=3*lag)
        try:
            first=download(cycle,FIELDS[0])
        except HTTPError as exc:
            if exc.code==404:continue
            raise
        result={FIELDS[0]:first}
        for field in FIELDS[1:]:
            result[field]=download(cycle,field)
        report={"source":"DWD Open Data","model":"ICON-EU","run_utc":cycle.isoformat(),
                "forecast_hour":STEP,"fields":result,
                "note":"Native GRIB interval metadata; not yet daily aggregation or production."}
        Path("dwd-icon-eu-pilot.json").write_text(json.dumps(report,indent=2)+"\n")
        print("KFS_DWD_PILOT_OK",json.dumps(report),flush=True)
        return
    raise RuntimeError("No complete recent ICON-EU test cycle found")

if __name__=="__main__":main()
