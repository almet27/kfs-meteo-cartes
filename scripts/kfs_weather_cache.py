"""Quota-aware, bounded local storage of validated weather API responses.

GitHub Actions restores/saves this cache even after failed downloads. No
credentials, no cross-provider substitution, no modification of source dates.
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from email.utils import parsedate_to_datetime
import gzip, hashlib, json, os, time

ROOT=Path(os.environ.get("KFS_WEATHER_CACHE",".kfs-weather-cache"))
ROOT.mkdir(parents=True,exist_ok=True)
BLOCK=ROOT/"open-meteo-cooldown.json"

class QuotaDeferred(RuntimeError):
    pass

def utc_hour():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")

def cache_key(scope, identity):
    raw=json.dumps([scope,identity],sort_keys=True,separators=(",",":"))
    return ROOT/(hashlib.sha256(raw.encode()).hexdigest()+".json.gz")

def prune():
    now=time.time()
    files=list(ROOT.glob("*.json.gz"))
    for path in files:
        if now-path.stat().st_mtime>3*86400:
            path.unlink(missing_ok=True)
    files=sorted(ROOT.glob("*.json.gz"),key=lambda p:p.stat().st_mtime,reverse=True)
    size=0
    for path in files:
        size+=path.stat().st_size
        if size>150*1024*1024:
            path.unlink(missing_ok=True)

def check_quota():
    try:
        until=float(json.loads(BLOCK.read_text())["until"])
    except (OSError,ValueError,KeyError,TypeError):
        return
    if time.time()<until:
        raise QuotaDeferred("Open-Meteo en pause jusqu'à "+
            datetime.fromtimestamp(until,timezone.utc).isoformat())

def record_quota(exc):
    if not isinstance(exc,HTTPError) or exc.code!=429:
        return
    raw=exc.headers.get("Retry-After","") if exc.headers else ""
    delay=3600
    if raw:
        try:delay=max(delay,float(raw))
        except (ValueError,TypeError):
            try:delay=max(delay,parsedate_to_datetime(raw).timestamp()-time.time())
            except (ValueError,TypeError,OverflowError):pass
    until=time.time()+delay
    BLOCK.write_text(json.dumps({"until":until}),encoding="utf-8")
    raise QuotaDeferred("HTTP 429 : téléchargements suspendus jusqu'à "+
        datetime.fromtimestamp(until,timezone.utc).isoformat()) from exc

def cached(scope,identity,fetch,validate=None):
    path=cache_key(scope,identity)
    if path.exists():
        try:
            with gzip.open(path,"rt",encoding="utf-8") as f:
                result=json.load(f)
            if validate:validate(result)
            print("KFS_CACHE_HIT",scope,path.name[:12],flush=True)
            return result
        except (OSError,ValueError,TypeError,KeyError,EOFError):
            path.unlink(missing_ok=True)
    check_quota()
    try:
        result=fetch()
    except HTTPError as exc:
        record_quota(exc)
        raise
    if validate:validate(result)
    tmp=path.with_suffix(".tmp")
    with gzip.open(tmp,"wt",encoding="utf-8",compresslevel=5) as f:
        json.dump(result,f,ensure_ascii=False,separators=(",",":"),allow_nan=False)
    tmp.replace(path)
    print("KFS_CACHE_SAVED",scope,path.name[:12],flush=True)
    return result

def validate_rows(rows,n,section):
    if not isinstance(rows,list) or len(rows)!=n:
        raise ValueError("Nombre de points du cache incorrect")
    if any(not isinstance(r,dict) or not isinstance(r.get(section),dict)
           or not r[section].get("time") for r in rows):
        raise ValueError("Données météorologiques incomplètes")

def render_revision(*paths):
    h=hashlib.sha256()
    for path in paths:
        h.update(Path(path).read_bytes())
    return h.hexdigest()[:16]
