#!/usr/bin/env python3
"""Diagnostic HTTP Météo-France : affiche seulement les codes, jamais les secrets."""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TOKEN_URL = "https://portail-api.meteofrance.fr/token"
ENDPOINTS = {
    "paquet_standard": "https://public-api.meteofrance.fr/public/DPPaquetObs/paquet/stations/infrahoraire-6m?format=geojson",
    "paquet_v1": "https://public-api.meteofrance.fr/public/DPPaquetObs/v1/paquet/stations/infrahoraire-6m?format=geojson",
    "paquet_v2": "https://public-api.meteofrance.fr/public/DPPaquetObs/v2/paquet/stations/infrahoraire-6m?format=geojson",
    "ciblee_v2": "https://public-api.meteofrance.fr/public/DPObs/v2/liste-stations",
    "ciblee_v1": "https://public-api.meteofrance.fr/public/DPObs/v1/liste-stations",
}

def main():
    basic = os.environ.get("METEOFRANCE_BASIC_AUTH", "").strip()
    if not basic:
        raise SystemExit("Le secret METEOFRANCE_BASIC_AUTH est absent")
    request = urllib.request.Request(TOKEN_URL,
        data=b"grant_type=client_credentials",
        headers={"Authorization": "Basic " + basic,
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=20) as response:
        access = json.loads(response.read())["access_token"]
    print("OAuth2: 200 (jeton obtenu, valeur masquée)")
    now = datetime.now(timezone.utc)
    six = now - timedelta(minutes=18)
    six = six.replace(minute=(six.minute // 6) * 6, second=0, microsecond=0)
    hour = (now - timedelta(minutes=25)).replace(minute=0, second=0, microsecond=0)
    ENDPOINTS["paquet_v2_dated_6m"] = (
        "https://public-api.meteofrance.fr/public/DPPaquetObs/v2/paquet/stations/infrahoraire-6m?"
        + "date=" + six.strftime("%Y-%m-%dT%H:%M:%SZ") + "&format=geojson")
    ENDPOINTS["paquet_v2_dated_hourly"] = (
        "https://public-api.meteofrance.fr/public/DPPaquetObs/v2/paquet/stations/horaire?"
        + "date=" + hour.strftime("%Y-%m-%dT%H:%M:%SZ") + "&format=geojson")
    for name, url in ENDPOINTS.items():
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + access, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                print(name + ": HTTP " + str(response.status))
        except urllib.error.HTTPError as error:
            detail = error.read(240).decode("utf-8", errors="replace").replace(access, "[REDACTED]").replace(basic, "[REDACTED]")
            print(name + ": HTTP " + str(error.code) + " " + detail.replace("\\n"," ")[:240])
        except Exception as error:
            print(name + ": réseau inaccessible (" + type(error).__name__ + ")")

if __name__ == "__main__":
    main()
