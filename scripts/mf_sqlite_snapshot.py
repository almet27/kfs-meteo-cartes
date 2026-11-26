"""Package validated public MF observations and import into isolated SQLite.
No access to Infoclimat files, credentials, or live databases.
Usage: python mf_sqlite_snapshot.py bundle
       python mf_sqlite_snapshot.py import [--local]
"""
import argparse, datetime as dt, fcntl, gzip, hashlib, json, math, os, re
import shutil, sqlite3, tempfile, urllib.request
from pathlib import Path

YEAR=2026
ROOT=Path("climato/mf-daily")/str(YEAR)
URL="https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/main/climato/mf-daily/2026/"
HOME=Path.home()/"kfs-meteofrance"
LIMIT=32*1024*1024
FIELDS=["tn","tx","tm","rr","gust","wind","gustUtc"]

def read_json(path):return json.loads(path.read_text(encoding="utf-8"))
def atomic(path,raw):
    fd,name=tempfile.mkstemp(dir=path.parent,prefix=".new-")
    try:
        with os.fdopen(fd,"wb") as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)

def validate(index,docs):
    if index.get("schema")!=1 or index.get("year")!=YEAR or len(index.get("stations",[]))<400:raise ValueError("Index invalide ou incomplet")
    stations=index["stations"];seen=set();n=0
    stamp=dt.datetime.fromisoformat(index["generated_at"])
    if stamp.tzinfo is None or stamp>dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=10):raise ValueError("Date source invalide")
    for st in stations:
        sid=st["id"]
        if not re.fullmatch(r"\d{8}",sid) or sid in seen:raise ValueError("Station invalide ou dupliquee")
        seen.add(sid)
        if not (-6<=st["lon"]<=10 and 41<=st["lat"]<=52):raise ValueError("Coordonnees invalides")
        doc=docs[sid]
        if doc.get("station")!=sid or doc.get("year")!=YEAR or doc.get("schema")!=1 or doc.get("fields")!=FIELDS or doc.get("generated_at")!=index["generated_at"]:raise ValueError("Generation incoherente")
        counts=[[0]*6 for _ in range(12)];last=""
        for row in doc["rows"]:
            if len(row)!=8:raise ValueError("Ligne invalide")
            day=dt.date.fromisoformat(row[0])
            if day.year!=YEAR or day>=stamp.date() or row[0]<=last:raise ValueError("Date invalide")
            last=row[0];n+=1
            for i,(v,(lo,hi)) in enumerate(zip(row[1:7],[(-60,65),(-60,65),(-60,65),(0,1500),(0,540),(0,360)])):
                if v is not None:
                    if type(v) not in (float,int) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError("Valeur hors limites")
                    counts[day.month-1][i]+=1
            if row[1] is not None and row[2] is not None and row[1]>row[2]:raise ValueError("TN > TX")
        if not doc["rows"] or st["first"]!=doc["rows"][0][0] or st["last"]!=last or st["months"]!=counts:raise ValueError("Couverture incoherente")
    if seen!=set(docs) or n<50000:raise ValueError("Archive incomplete")
    return n

def bundle():
    index=read_json(ROOT/"index.json")
    docs={s["id"]:read_json(ROOT/(s["id"]+".json")) for s in index["stations"]}
    n=validate(index,docs)
    raw=gzip.compress(json.dumps({"index":index,"docs":docs},separators=(",",":"),allow_nan=False).encode(),compresslevel=6,mtime=0)
    if len(raw)>LIMIT:raise ValueError("Archive trop volumineuse")
    atomic(ROOT/"snapshot.json.gz",raw)
    atomic(ROOT/"snapshot.sha256",(hashlib.sha256(raw).hexdigest()+"\n").encode())
    print(json.dumps({"stations":len(docs),"rows":n,"bytes":len(raw)}))

def get(name,local):
    if local:return (ROOT/name).read_bytes()
    with urllib.request.urlopen(URL+name,timeout=90) as r:
        raw=r.read(LIMIT+1)
    if len(raw)>LIMIT:raise ValueError("Limite de taille depassee")
    return raw

def import_db(local):
    HOME.mkdir(mode=0o700,exist_ok=True)
    if shutil.disk_usage(HOME).free<250*1024*1024:raise RuntimeError("Espace libre insuffisant")
    with (HOME/".sync.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        digest=get("snapshot.sha256",local).decode().strip()
        raw=get("snapshot.json.gz",local)
        if not re.fullmatch(r"[a-f0-9]{64}",digest) or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError("Empreinte invalide, ancienne base conservee")
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:payload=f.read(128*1024*1024+1)
        if len(payload)>128*1024*1024:raise ValueError("Archive decompressee trop volumineuse")
        p=json.loads(payload);index,docs=p["index"],p["docs"];n=validate(index,docs)
        target=HOME/"observations.sqlite"
        if target.exists():
            with sqlite3.connect("file:"+str(target)+"?mode=ro",uri=True) as db:
                old=dict(db.execute("SELECT key,value FROM metadata"))
                old_ids={r[0] for r in db.execute("SELECT id FROM stations")}
                if old["sha256"]==digest:print("Deja synchronise");return
                if dt.datetime.fromisoformat(index["generated_at"])<=dt.datetime.fromisoformat(old["generated_at"]):raise ValueError("Generation ancienne")
                if not old_ids.issubset(docs):raise ValueError("Des stations ont disparu; ancienne base conservee")
                # Do not publish a source regression that removes valid daily records.
                old_rows=db.execute("SELECT count(*) FROM daily").fetchone()[0]
                if n<old_rows:raise ValueError("Couverture en baisse; ancienne base conservee")
        fd,name=tempfile.mkstemp(dir=HOME,suffix=".sqlite");os.close(fd)
        tmp=Path(name)
        try:
            with sqlite3.connect(tmp) as db:
                db.executescript("""CREATE TABLE stations(id TEXT PRIMARY KEY,name TEXT,lon REAL,lat REAL,first_day TEXT,last_day TEXT,coverage TEXT);
                CREATE TABLE daily(station TEXT,day TEXT,tn REAL,tx REAL,tm REAL,rr REAL,gust REAL,wind REAL,gust_utc TEXT,PRIMARY KEY(station,day)) WITHOUT ROWID;
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
                CREATE INDEX daily_day ON daily(day,station);""")
                db.executemany("INSERT INTO stations VALUES(?,?,?,?,?,?,?)",[(s["id"],s["name"],s["lon"],s["lat"],s["first"],s["last"],json.dumps(s["months"])) for s in index["stations"]])
                for sid,doc in docs.items():db.executemany("INSERT INTO daily VALUES(?,?,?,?,?,?,?,?,?)",[(sid,*r) for r in doc["rows"]])
                meta={"schema":"1","source":"Meteo-France Open Data","generated_at":index["generated_at"],"sha256":digest,"failed_departments":json.dumps(index["failed_departments"])}
                db.executemany("INSERT INTO metadata VALUES(?,?)",meta.items())
                db.commit()
                if db.execute("PRAGMA quick_check").fetchone()[0]!="ok" or db.execute("SELECT count(*) FROM daily").fetchone()[0]!=n:raise ValueError("Verification SQLite echouee")
            if target.exists():
                with target.open("rb") as f:atomic(HOME/"observations.previous.sqlite",f.read())
            os.replace(tmp,target)
            atomic(HOME/"status.json",json.dumps({"stations":len(docs),"rows":n,"generated_at":index["generated_at"],"failed_departments":index["failed_departments"],"sha256":digest}).encode())
            print((HOME/"status.json").read_text())
        finally:tmp.unlink(missing_ok=True)

if __name__=="__main__":
    os.umask(0o077)
    ap=argparse.ArgumentParser();ap.add_argument("action",choices=["bundle","import"]);ap.add_argument("--local",action="store_true");a=ap.parse_args()
    if a.action=="bundle":bundle()
    else:import_db(a.local)
