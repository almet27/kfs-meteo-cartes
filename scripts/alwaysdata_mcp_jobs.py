"""Stable MCP job interface for the KFS climatology scripts.
Trusted Python from one owned GitHub repository, fixed paths, immutable commit
and reviewed SHA256. This is NOT a sandbox for arbitrary untrusted Python.
Never pass shell commands, URLs, local paths, or credentials through MCP.
"""
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Literal

BASE = Path.home() / "kfs-infoclimat"
STATE = BASE / ".mcp_jobs"
REPO = "https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/"
Job = Literal["audit", "temperature", "archive"]
JOBS = {
    "audit": ("alwaysdata_climato_audit.py", "climato_audit.py",
              ".climato_audit.lock", "climato_audit.json"),
    "temperature": ("alwaysdata_climato_temperature_export.py",
                    "climato_temperature_export.py",
                    ".climato_temperature_export.lock", "climato_temperature_export.json"),
    "archive": ("alwaysdata_infoclimat_archive.py", "climatologie.py",
                ".mcp_archive_job.lock", None),
}
ENV = {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def job_lock(job):
    if job not in JOBS:
        raise ValueError("Job non autorise")
    STATE.mkdir(mode=0o700, exist_ok=True)
    f = (BASE / JOBS[job][2]).open("a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except BlockingIOError:
        f.close()
        return None

def write_state(job, state):
    p = STATE / (job + ".json")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.chmod(tmp, 0o600)
    tmp.replace(p)

def read_state(job):
    p = STATE / (job + ".json")
    if not p.exists():
        return {"statut": "Aucun lancement via cette interface"}
    return json.loads(p.read_text())

def installer_script_kfs(job: Job, commit: str, sha256: str) -> dict:
    """Install a reviewed script from the fixed KFS repository at an immutable commit.
    A human-approved SHA256 is required. Does not execute the script."""
    if job not in JOBS or not re.fullmatch(r"[a-f0-9]{40}", commit) or not re.fullmatch(r"[a-f0-9]{64}", sha256):
        return {"statut": "Parametres invalides"}
    lock = job_lock(job)
    if lock is None:
        return {"statut": "Travail en cours"}
    with lock:
        remote, local, _, _ = JOBS[job]
        target = BASE / local
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=BASE, delete=False) as f:
                tmp = Path(f.name)
            subprocess.run(["curl", "-4", "-fsSL", "--max-time", "45",
                            "--max-filesize", "150000",
                            REPO + commit + "/scripts/" + remote, "-o", str(tmp)],
                           check=True, timeout=50, capture_output=True, env=ENV)
            raw = tmp.read_bytes()
            if not 0 < len(raw) <= 150000 or hashlib.sha256(raw).hexdigest() != sha256:
                return {"statut": "Empreinte ou taille incorrecte"}
            compile(raw, str(target), "exec")
            if target.is_symlink():
                return {"statut": "Lien symbolique refuse"}
            if target.exists():
                backup = STATE / (job + ".previous.py")
                with tempfile.NamedTemporaryFile(dir=STATE, delete=False) as f:
                    copy = Path(f.name)
                try:
                    shutil.copyfile(target, copy)
                    os.chmod(copy, 0o600)
                    copy.replace(backup)
                finally:
                    copy.unlink(missing_ok=True)
            os.chmod(tmp, 0o600)
            tmp.replace(target)
            write_state(job, {"statut":"Installe, non lance", "commit":commit,
                              "sha256":sha256, "date":now()})
            return {"statut":"Script installe","job":job,"commit":commit,"sha256":sha256}
        except Exception as e:
            return {"statut":"Installation echouee","type_erreur":type(e).__name__}
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

def restaurer_script_kfs(job: Job) -> dict:
    """Restore the previous local version of one authorized script, without executing."""
    lock = job_lock(job)
    if lock is None:
        return {"statut":"Travail en cours"}
    with lock:
        backup = STATE / (job + ".previous.py")
        if not backup.is_file() or backup.is_symlink():
            return {"statut":"Aucune sauvegarde"}
        raw = backup.read_bytes()
        target = BASE / JOBS[job][1]
        if target.is_symlink():
            return {"statut":"Lien symbolique refuse"}
        compile(raw,str(target),"exec")
        with tempfile.NamedTemporaryFile(dir=BASE,delete=False) as f:
            tmp = Path(f.name)
            f.write(raw)
        try:
            os.chmod(tmp,0o600)
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
        write_state(job, {"statut":"Restaure, non lance", "date":now()})
        return {"statut":"Script restaure"}

def lancer_script_kfs(job: Job) -> dict:
    """Start one installed KFS climatology script with no arbitrary arguments."""
    lock = job_lock(job)
    if lock is None:
        return {"statut":"Travail en cours"}
    with lock:
        script = BASE / JOBS[job][1]
        if not script.is_file() or script.is_symlink():
            return {"statut":"Script absent ou non autorise"}
        sha = hashlib.sha256(script.read_bytes()).hexdigest()
        write_state(job, {"statut":"En cours","sha256":sha,"debut":now()})
        try:
            with (STATE / (job + ".log")).open("w") as log:
                p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                    "--worker", job],cwd=BASE,env=ENV,stdout=log,stderr=log,
                    pass_fds=(lock.fileno(),),start_new_session=True)
        except OSError as e:
            write_state(job, {"statut":"Lancement echoue","type_erreur":type(e).__name__})
            return {"statut":"Lancement echoue"}
        return {"statut":"Travail lance","job":job,"pid":p.pid}

def worker(job):
    script = BASE / JOBS[job][1]
    state = read_state(job)
    try:
        r = subprocess.run([sys.executable,str(script)],cwd=BASE,env=ENV,
                           timeout=1800)
        state.update(statut="Termine" if r.returncode==0 else "Echec",
                     code_retour=r.returncode,fin=now())
    except Exception as e:
        state.update(statut="Echec",type_erreur=type(e).__name__,fin=now())
    write_state(job,state)

def statut_script_kfs(job: Job) -> dict:
    """Return bounded execution status, not raw logs or credentials."""
    lock = job_lock(job)
    if lock is None:
        return {"statut":"En cours","job":job}
    with lock:
        state = read_state(job)
        if state.get("statut")=="En cours":
            state["statut"]="Interrompu sans rapport final"
        return {"job":job,**state}

def lire_resultat_kfs(job: Job, jour_fin: int=23, offset: int=0, limite: int=60) -> dict:
    """Read only the expected aggregate climatology report. Temperature is paginated.
    No raw database, arbitrary files, logs or secrets are returned."""
    if job not in ("audit","temperature"):
        return {"statut":"Utiliser statut_climatologie pour les archives"}
    if not (1<=jour_fin<=23 and 0<=offset<=1000 and 1<=limite<=100):
        return {"statut":"Parametres invalides"}
    lock = job_lock(job)
    if lock is None:
        return {"statut":"En cours"}
    with lock:
        state = read_state(job)
        if state.get("statut") != "Termine":
            return {"statut":"Relancer via lancer_script_kfs avant lecture","etat":state.get("statut")}
        p = BASE / JOBS[job][3]
        if not p.is_file() or p.is_symlink() or p.stat().st_size>2000000:
            return {"statut":"Rapport absent ou invalide"}
        if p.stat().st_mtime < dt.datetime.fromisoformat(state["debut"]).timestamp()-1:
            return {"statut":"Rapport ancien"}
        report=json.loads(p.read_text())
        if job=="audit":
            fields=("period_utc","days_expected","rows","stations","first_utc",
                "last_utc","invalid_rows","fields","valid_values","top_minutes",
                "station_days_24_hour_bins","stations_all_days_24_hour_bins","note")
            return {"statut":"Rapport disponible","rapport":{k:report[k] for k in fields if k in report}}
        start=dt.date.fromisoformat(report["start"])
        if start!=dt.date(2026,11,1):
            return {"statut":"Periode non prise en charge par cet export"}
        rows=[]
        for r in report["stations"]:
            if len(r["days"])<jour_fin:continue
            days=r["days"][:jour_fin]
            rows.append({k:r[k] for k in ("id","lon","lat","license")}|{
                "temp":round(sum((tn+tx)/2 for tn,tx in days)/jour_fin,3),
                "frost":sum(tn<=0 for tn,tx in days)})
        return {"statut":"Export disponible","start":str(start),
                "end":str(start+dt.timedelta(days=jour_fin-1)),
                "method":report["method"],"total":len(rows),"offset":offset,
                "next_offset":offset+limite if offset+limite<len(rows) else None,
                "stations":rows[offset:offset+limite]}

if __name__=="__main__":
    if len(sys.argv)!=3 or sys.argv[1]!="--worker" or sys.argv[2] not in JOBS:
        raise SystemExit(2)
    worker(sys.argv[2])
