#!/usr/bin/env python3
"""Validate ChatGPT meteorological handoff; never publish to Discord.

Accept only structured, clearly sourced documents with explicit availability
disclosures. Mark a document ready only after extended-range ensemble verification.
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("forecast-maps/tendance")
SOURCE = ROOT / "tendance-analyse-donnees.json"
DOCUMENT = ROOT / "chatgpt-bulletin.json"

def parsed_date(value):
    if not isinstance(value, str):
        raise ValueError("Horodatage manquant")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.utcoffset() is None:
        raise ValueError("Fuseau horaire absent")
    return date.astimezone(timezone.utc)

def main():
    report = json.loads(DOCUMENT.read_text(encoding="utf-8"))
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    if report.get("schema_version") != 1:
        raise ValueError("Version de schema non reconnue")
    required = ("title", "summary", "body_markdown", "source_path", "source_generated_utc")
    if any(not isinstance(report.get(k),str) or not report[k].strip() for k in required):
        raise ValueError("Bulletin incomplet")
    if report["source_path"] != str(SOURCE):
        raise ValueError("Chemin de donnees sources incoherent")
    if parsed_date(report["source_generated_utc"]) != parsed_date(source["generated_utc"]):
        raise ValueError("Bulletin et champs numeriques non synchronises")
    if abs((now-parsed_date(source["generated_utc"])).total_seconds()) > 48*3600:
        raise ValueError("Donnees numeriques perimees, rapport non utilisable")
    created = parsed_date(report["created_utc"])
    if created > now + timedelta(minutes=20) or created < parsed_date(source["generated_utc"]):
        raise ValueError("Date de redaction incoherente")
    body = report["body_markdown"]
    words = len(body.split())
    if words < 650 or words > 1600:
        raise ValueError("Texte trop court ou trop long: %d mots" % words)
    models = report.get("source_models",[])
    if not models or any(x not in source.get("models",{}) for x in models):
        raise ValueError("Modeles non traces dans les donnees")
    if re.search(r"(?i)(mot.de.passe|token secret|authorization: bearer|sk-[A-Za-z0-9]{15,})", body):
        raise ValueError("Possibles secrets detectes dans le bulletin")
    if report.get("discord_channel_id") not in (None, "", "1441767343498858578"):
        raise ValueError("Identifiant de salon Discord inconnu")
    readable = ROOT / "chatgpt-bulletin.md"
    if not readable.exists() or report["created_utc"] not in readable.read_text(encoding="utf-8"):
        raise ValueError("La version Markdown est absente ou ne correspond pas au bulletin JSON")
    is_ready = report.get("status") == "ready" and report.get("ready_for_discord") is True
    if is_ready:
        extended = json.loads((ROOT / "extended-weekly.json").read_text(encoding="utf-8"))
        gen_utc = parsed_date(extended["generated_utc"])
        if extended.get("verified") is not True or not {3,4}.issubset(set(extended.get("weeks", []))):
            raise ValueError("Les semaines 3 et 4 ne sont pas validees")
        if gen_utc > now or now - gen_utc > timedelta(days=7):
            raise ValueError("Les donnees Extended sont obsoletes")
        if report.get("weeks_3_4") != "verified":
            raise ValueError("Le bulletin doit marquer les semaines 3 et 4 comme verifiees")
        if report.get("discord_channel_id") != "1441767343498858578":
            raise ValueError("Salon de publication absent")
    elif report.get("status") != "draft" or report.get("ready_for_discord") is not False or report.get("weeks_3_4") != "unverified":
        raise ValueError("Statut invalide : pas de diffusion sans donnees Extended")
    out = {
        "validated_utc":now.isoformat(),
        "status":"passed_ready_validation" if is_ready else "passed_draft_validation",
        "ready_for_discord":is_ready,
        "word_count":words,
        "data_source":report["source_path"],
        "models":models,
        "discord_sent":False
    }
    (ROOT/"chatgpt-handoff-validation.json").write_text(
        json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("::error::Echec de validation du brouillon : "+str(exc),file=sys.stderr)
        sys.exit(1)
