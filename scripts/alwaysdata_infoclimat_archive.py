"""KFS compact historical archive, separate from raw November and live feed.
Bounded resumable pilot: 12 requests per execution, five UTC days per request.
Store only daily aggregates and collection status. Never delete original data.
"""
import datetime as dt
import fcntl
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from urllib.parse import urlencode

BASE = Path.home() / "kfs-infoclimat"
FIRST = dt.date(2020, 1, 1)
BATCH = 20
REQUEST_LIMIT = 12
PAUSE = 3
PRIORITY = "STATIC0064"
RECENT_FIRST = dt.date(2026, 8, 1)
DB = BASE / "climatologie_journaliere.sqlite"
REPORT = BASE / "climatologie_journaliere_status.json"
CAT = "https://www.infoclimat.fr/opendata/stations_xhr.php?format=geojson"

def fetch(url):
    if any(c in url for c in ('"', '\r', '\n')):
        raise ValueError("URL invalide")
    return json.loads(subprocess.check_output(
        ["curl", "-4", "-fsS", "--max-time", "60", "--max-filesize", "25000000", "--config", "-"],
        input=('url = "' + url + '"\n').encode(), stderr=subprocess.DEVNULL,
        timeout=65))

def val(row,key,lo,hi):
    v = row.get(key)
    if v is None or isinstance(v,bool):
        return None
    try:
        v = float(v)
    except (ValueError,TypeError):
        return None
    return v if math.isfinite(v) and lo<=v<=hi else None

def day_summary(rows, day):
    start=dt.datetime.combine(day,dt.time())
    stop=start+dt.timedelta(days=1)
    temp,wind,gust,r1,r3={}, {}, {}, {}, {}
    for t,r in rows:
        if start<t<=stop and t.minute==0 and t.second==0:
            v=val(r,"pluie_1h",0,200)
            if v is not None:r1[t]=v
            v=val(r,"pluie_3h",0,400)
            if v is not None and t.hour%3==0:r3[t]=v
        if not start<=t<stop:continue
        h=t.hour
        v=val(r,"temperature",-45,55)
        if v is not None:
            b=temp.setdefault(h,[v,v,t,t])
            b[0]=min(b[0],v);b[1]=max(b[1],v)
            b[2]=min(b[2],t);b[3]=max(b[3],t)
        v=val(r,"vent_moyen",0,250)
        if v is not None:
            b=wind.setdefault(h,[0.0,0]);b[0]+=v;b[1]+=1
        v=val(r,"vent_rafales",0,350)
        if v is not None and (h not in gust or v>gust[h][0]):gust[h]=(v,t)
    complete=len(temp)==24 and all((temp[h+1][2]-temp[h][3]).total_seconds()<=3600 for h in range(23))
    tn=min(b[0] for b in temp.values()) if complete else None
    tx=max(b[1] for b in temp.values()) if complete else None
    one=[r1.get(start+dt.timedelta(hours=h)) for h in range(1,25)]
    three=[r3.get(start+dt.timedelta(hours=h)) for h in range(3,25,3)]
    a=sum(one) if all(v is not None for v in one) else None
    b=sum(three) if all(v is not None for v in three) else None
    conflict=a is not None and b is not None and abs(a-b)>max(1.0,0.1*max(a,b))
    rain=None if conflict else (a if a is not None else b)
    best=max(gust.values(),key=lambda v:v[0]) if gust else None
    return (tn,tx,len(temp),round(rain,2) if rain is not None else None,
            "conflict" if conflict else ("1h" if a is not None else ("3h" if b is not None else None)),
            round(sum(a/n for a,n in wind.values())/len(wind),2) if wind else None,len(wind),
            best[0] if best else None,best[1].isoformat(" ") if best else None,len(gust))

def report(db,requests,eligible,note):
    out={"schema":1,"updated_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
         "first_target":str(FIRST),"requests_this_run":requests,"eligible_stations":eligible,
         "daily_rows":db.execute("SELECT COUNT(*) FROM daily").fetchone()[0],
         "stations_with_daily_rows":db.execute("SELECT COUNT(DISTINCT station) FROM daily").fetchone()[0],
         "first_day":db.execute("SELECT MIN(day) FROM daily").fetchone()[0],
         "last_day":db.execute("SELECT MAX(day) FROM daily").fetchone()[0],
         "collected_windows":db.execute("SELECT COUNT(*) FROM batches").fetchone()[0],
         "db_bytes":DB.stat().st_size,"note":note}
    # Compact public-data export for the priority station; separate from raw observations.
    # Do not publish automatically: CC BY-NC and source provenance must accompany the values.
    st=db.execute("SELECT id,lat,lon,license FROM stations WHERE id=?",(PRIORITY,)).fetchone()
    if st:
        months=[]
        for month in range(8,13):
            begin=dt.date(2026,month,1)
            end=min(dt.date(2027,1,1) if month==12 else dt.date(2026,month+1,1),dt.datetime.now(dt.timezone.utc).date())
            if end<=begin:continue
            rows=db.execute("SELECT day,tn,tx,rain,wind,wind_hours,gust,gust_utc,gust_hours FROM daily WHERE station=? AND day>=? AND day<? ORDER BY day",(PRIORITY,str(begin),str(end))).fetchall()
            t=[(r[1],r[2]) for r in rows if r[1] is not None and r[2] is not None]
            rain=[r[3] for r in rows if r[3] is not None]
            winds=[(r[4],r[5]) for r in rows if r[4] is not None and r[5]>0]
            gusts=[(r[6],r[7]) for r in rows if r[6] is not None]
            g=max(gusts,key=lambda x:x[0]) if gusts else (None,None)
            months.append({"month":begin.strftime("%Y-%m"),"expected_days":(end-begin).days,"observed_days":len(rows),"temperature_days":len(t),"rain_days":len(rain),"temperature_mean":round(sum((a+b)/2 for a,b in t)/len(t),2) if t else None,"tn_mean":round(sum(a for a,b in t)/len(t),2) if t else None,"tx_mean":round(sum(b for a,b in t)/len(t),2) if t else None,"tn_min":min(a for a,b in t) if t else None,"tx_max":max(b for a,b in t) if t else None,"rain_mm":round(sum(rain),2) if rain else None,"wind_hours":sum(n for v,n in winds),"wind_mean_kmh":round(sum(v*n for v,n in winds)/sum(n for v,n in winds),2) if winds else None,"gust_max_kmh":g[0],"gust_utc":g[1],"gust_hours":sum(r[8] for r in rows)})
        export={"schema":1,"station":{"id":st[0],"name":"Puzeaux","lat":st[1],"lon":st[2],"license":st[3]},"source":"Infoclimat / StatIC","source_url":"https://www.infoclimat.fr/stations/metadonnees.php?id=STATIC0064","usage":"non-commercial" if st[3]=="2" else "open","method":"UTC days; monthly means of daily sampled extrema; rain sums only validated days; incomplete coverage remains explicit","months":months}
        dest=BASE/"climatologie_puzeaux_export.json";tmp=dest.with_suffix(".tmp");tmp.write_text(json.dumps(export,allow_nan=False));tmp.replace(dest)
        out["priority_station"]={"id":PRIORITY,"months":months}
    tmp=REPORT.with_suffix(".tmp");tmp.write_text(json.dumps(out));tmp.replace(REPORT)
    print(json.dumps(out),flush=True)

def main():
    os.umask(0o077)
    with (BASE/".climatologie.lock").open("a") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        # Preserve free space for live feed and existing raw archive.
        import shutil
        if shutil.disk_usage(BASE).free<150000000:
            raise SystemExit("Espace disque insuffisant")
        token=(BASE/".token").read_text().strip()
        cat=fetch(CAT)
        stations={}
        for f in cat["features"]:
            p=f.get("properties",{});lic=p.get("license") or {}
            if p.get("country")!="FR" or lic.get("source")!="infoclimat.fr" or not p.get("id"):continue
            if str(lic.get("code")) not in ("0","1") and not (str(p["id"])==PRIORITY and str(lic.get("code"))=="2"):continue
            try:lon,lat=map(float,f["geometry"]["coordinates"][:2])
            except (KeyError,ValueError,TypeError):continue
            if -5.8<=lon<=10.1 and 41<=lat<=51.6:stations[str(p["id"])]=(lat,lon,str(lic["code"]))
        live=json.loads((BASE/"latest.json").read_text())
        ids=sorted(set(stations).intersection(live))
        if PRIORITY in stations and PRIORITY not in ids:ids.insert(0,PRIORITY)
        if not ids:raise SystemExit("Aucune station eligible")
        with sqlite3.connect(DB,timeout=30) as db:
            db.execute("CREATE TABLE IF NOT EXISTS stations(id TEXT PRIMARY KEY,lat REAL,lon REAL,license TEXT)")
            db.execute("""CREATE TABLE IF NOT EXISTS daily(station TEXT,day TEXT,
                tn REAL,tx REAL,temp_hours INTEGER,rain REAL,rain_method TEXT,
                wind REAL,wind_hours INTEGER,gust REAL,gust_utc TEXT,gust_hours INTEGER,
                PRIMARY KEY(station,day)) WITHOUT ROWID""")
            db.execute("CREATE TABLE IF NOT EXISTS batches(station TEXT,begin TEXT,end TEXT,PRIMARY KEY(station,begin,end)) WITHOUT ROWID")
            db.executemany("INSERT OR REPLACE INTO stations VALUES(?,?,?,?)",[(s,*stations[s]) for s in ids]);db.commit()
            today=dt.datetime.now(dt.timezone.utc).date()
            # End at the start of today; the UTC midnight observation is needed for rain.
            # Fixed five-day blocks are stable across executions. Also collect the
            # previous completed day to keep recent data fresh as the backfill advances.
            blocks=[(today-dt.timedelta(days=1),today)]
            cursor=FIRST+dt.timedelta(days=((today-FIRST).days//5)*5)
            if cursor==today:cursor-=dt.timedelta(days=5)
            while cursor>=FIRST:
                stop=min(cursor+dt.timedelta(days=5),today)
                if stop>cursor and (cursor,stop) not in blocks:blocks.append((cursor,stop))
                cursor-=dt.timedelta(days=5)
            # First repair recent months of Puzeaux, even if excluded from live feed.
            # Fixed blocks prevent duplicate requests; preserve the general backfill.
            priority_blocks=[]
            if PRIORITY in ids:
                cursor=RECENT_FIRST
                while cursor<today:
                    stop=min(cursor+dt.timedelta(days=5),today)
                    priority_blocks.append((cursor,stop,[PRIORITY]))
                    cursor=stop
            requests=0
            work=priority_blocks+[(begin,end,ids) for begin,end in blocks]
            for begin,end,candidates in work:
                done={r[0] for r in db.execute("SELECT station FROM batches WHERE begin=? AND end=?",(str(begin),str(end)))}
                pending=[s for s in candidates if s not in done]
                for pos in range(0,len(pending),BATCH):
                    if requests>=REQUEST_LIMIT:
                        report(db,requests,len(ids),"Bounded pilot; resume on next execution")
                        return
                    if DB.stat().st_size>100000000 or shutil.disk_usage(BASE).free<150000000:
                        report(db,requests,len(ids),"Disk guard reached; collection stopped")
                        return
                    group=pending[pos:pos+BATCH]
                    params=[("method","get"),("format","json"),("token",token),("start",str(begin)),("end",str(end+dt.timedelta(days=1)))]
                    params.extend(("stations[]",s) for s in group)
                    try:
                        with (BASE/".collect.lock").open("a") as shared:
                            fcntl.flock(shared,fcntl.LOCK_EX)
                            payload=fetch("https://www.infoclimat.fr/opendata/?"+urlencode(params))
                        if str(payload.get("status")).lower()!="ok" or not isinstance(payload.get("hourly"),dict):raise ValueError()
                    except Exception:
                        report(db,requests,len(ids),"Source unavailable or quota; stop and retry later")
                        raise SystemExit(1) from None
                    requests+=1
                    for sid in group:
                        raw=payload["hourly"].get(sid,[])
                        if not isinstance(raw,list):continue
                        bytime={}
                        for r in raw:
                            if not isinstance(r,dict):continue
                            try:t=dt.datetime.strptime(r.get("dh_utc"),"%Y-%m-%d %H:%M:%S")
                            except (ValueError,TypeError):continue
                            if begin<=t.date()<=end:bytime[t]=r
                        observations=sorted(bytime.items())
                        for n in range((end-begin).days):
                            day=begin+dt.timedelta(days=n)
                            if not any(t.date()==day for t,r in observations):continue
                            stats=day_summary(observations,day)
                            # Prefer a full temperature or rain day over an older partial entry.
                            db.execute("""INSERT INTO daily VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                              ON CONFLICT(station,day) DO UPDATE SET
                              tn=COALESCE(excluded.tn,daily.tn),tx=COALESCE(excluded.tx,daily.tx),
                              temp_hours=MAX(daily.temp_hours,excluded.temp_hours),
                              rain=COALESCE(excluded.rain,daily.rain),
                              rain_method=CASE WHEN excluded.rain IS NOT NULL THEN excluded.rain_method ELSE daily.rain_method END,
                              wind=CASE WHEN excluded.wind_hours>=daily.wind_hours THEN excluded.wind ELSE daily.wind END,
                              wind_hours=MAX(daily.wind_hours,excluded.wind_hours),
                              gust=CASE WHEN excluded.gust_hours>=daily.gust_hours THEN excluded.gust ELSE daily.gust END,
                              gust_utc=CASE WHEN excluded.gust_hours>=daily.gust_hours THEN excluded.gust_utc ELSE daily.gust_utc END,
                              gust_hours=MAX(daily.gust_hours,excluded.gust_hours)""",(sid,str(day),*stats))
                        # Empty response is recorded as unavailable, not zero weather.
                        db.execute("INSERT OR IGNORE INTO batches VALUES(?,?,?)",(sid,str(begin),str(end)))
                    db.commit()
                    time.sleep(PAUSE)
            report(db,requests,len(ids),"All current candidate windows requested")

if __name__=="__main__":
    main()
