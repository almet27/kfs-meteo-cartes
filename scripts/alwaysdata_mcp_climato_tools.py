"""Narrow MCP maintenance tools for KFS. No shell or arbitrary URL/path input."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BASE = Path.home() / "kfs-infoclimat"
AUDIT = BASE / "climato_audit.py"
REPORT = BASE / "climato_audit.json"
LOCK = BASE / ".climato_audit.lock"
URL = ("https://raw.githubusercontent.com/almet27/kfs-meteo-cartes/"
       "1386238f455e2b4fbea7e18437a83ff95027f729/"
       "scripts/alwaysdata_climato_audit.py")

def _try_lock():
    f = LOCK.open("a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f

def installer_audit_climatologie() -> dict:
    """Installe uniquement la version approuvée du script d'audit Infoclimat."""
    lock = _try_lock()
    if lock is None:
        return {"statut":"Audit en cours"}
    with lock:
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=BASE, delete=False) as f:
                tmp = Path(f.name)
            subprocess.run(["curl","-4","-fsSL","--max-time","30",
                            "--max-filesize","100000",URL,"-o",str(tmp)],
                           check=True, capture_output=True, timeout=35)
            raw = tmp.read_bytes()
            if not raw or len(raw)>100000:
                raise ValueError("Taille inattendue")
            compile(raw, str(AUDIT), "exec")
            os.chmod(tmp,0o600)
            tmp.replace(AUDIT)
            return {"statut":"Audit installe","version":"1386238f455e2b4fbea7e18437a83ff95027f729"}
        except Exception as exc:
            return {"statut":"Installation echouee","type_erreur":type(exc).__name__}
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

def lancer_audit_climatologie() -> dict:
    """Lance le controle en lecture seule de la couverture historique."""
    if not AUDIT.is_file():
        return {"statut":"Audit non installe"}
    lock = _try_lock()
    if lock is None:
        return {"statut":"Audit en cours"}
    with lock:
        env = {"HOME":str(Path.home()),"PATH":"/usr/bin:/bin","LANG":"C.UTF-8"}
        with (BASE/"climato_audit.log").open("w") as log:
            try:
                p = subprocess.Popen([sys.executable,str(AUDIT)],cwd=BASE,env=env,
                    stdout=log,stderr=log,start_new_session=True,pass_fds=(lock.fileno(),))
            except OSError as exc:
                return {"statut":"Lancement echoue","type_erreur":type(exc).__name__}
        return {"statut":"Audit lance","pid":p.pid}

def resultat_audit_climatologie() -> dict:
    """Lit uniquement le rapport agrégé de couverture climatologique."""
    lock = _try_lock()
    if lock is None:
        return {"statut":"Audit en cours"}
    with lock:
        if not REPORT.is_file():
            return {"statut":"Rapport indisponible"}
        try:
            if REPORT.stat().st_size > 100000:
                raise ValueError("Taille inattendue")
            report = json.loads(REPORT.read_text())
            # Return only the expected aggregate fields.
            keys = ("period_utc","days_expected","rows","stations","first_utc","last_utc",
                    "invalid_rows","fields","valid_values","top_minutes",
                    "station_days_24_hour_bins","stations_all_days_24_hour_bins","note")
            return {"statut":"Rapport disponible","rapport":{k:report[k] for k in keys if k in report}}
        except (ValueError,OSError,TypeError) as exc:
            return {"statut":"Lecture echouee","type_erreur":type(exc).__name__}
