"""Categorie juridique d'un SIREN via l'API Recherche d'entreprises (recherche-entreprises.api.gouv.fr).

Cache disque : data/lake/_cache/recherche_entreprises.json (non versionne, comme tout data/lake/).
Pour une personne physique (entrepreneur individuel, categorie 1000), le cache ne garde QUE la
categorie : aucun nom ni prenom n'est conserve. Les appels sont espaces (limite de l'API : 7 par seconde)
et bornes en duree (`budget_s`) pour que chaque commande reste courte ; on relance pour continuer.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "lake" / "_cache" / "recherche_entreprises.json"
API = "https://recherche-entreprises.api.gouv.fr/search"
HEADERS = {"User-Agent": "ou-vont-mes-impots/0.1 (projet citoyen open source)"}
PAUSE_S = 0.2

SIREN_RE = re.compile(r"^\d{9}$")
CJ_RE = re.compile(r"^\d{4}$")


def siren_valide(s) -> bool:
    return bool(s) and bool(SIREN_RE.match(str(s)))


def personne_morale(cj) -> bool:
    """Categories juridiques 2xxx a 9xxx (1000 = entrepreneur individuel, 0/vide = inconnu)."""
    return bool(cj) and bool(CJ_RE.match(str(cj))) and str(cj)[0] in "23456789"


def charger_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def _sauver(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".part")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(CACHE)


def _interroger(siren: str) -> dict | None:
    """Renvoie l'entree de cache, ou None si l'API est injoignable (on reessaiera plus tard)."""
    for tentative in range(5):
        try:
            r = requests.get(API, params={"q": siren, "page": 1, "per_page": 1}, headers=HEADERS, timeout=30)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(2 ** tentative)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** tentative)
            continue
        if r.status_code >= 400:
            return {"cj": None, "trouve": False}
        res = [x for x in r.json().get("results", []) if x.get("siren") == siren]
        if not res:
            return {"cj": None, "trouve": False}
        x = res[0]
        cj = x.get("nature_juridique")
        entree = {"cj": cj, "trouve": True}
        if personne_morale(cj):  # jamais de nom pour une personne physique
            entree["nom"] = (x.get("nom_complet") or "").strip()
        return entree
    return None


def resoudre(sirens, budget_s: float = 480, cache: dict | None = None, paralleles: int = 10) -> tuple[dict, int]:
    """Complete le cache pour les SIREN donnes (dans l'ordre fourni). Renvoie (cache, restants).

    L'API repond en 1 a 6 s : appels en parallele, mais jamais plus de 1 / PAUSE_S par seconde au total.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    cache = charger_cache() if cache is None else cache
    a_faire = [s for s in dict.fromkeys(sirens) if siren_valide(s) and s not in cache]
    debut = time.monotonic()
    verrou = threading.Lock()
    prochain = [time.monotonic()]
    faits = [0]

    def tache(s):
        if time.monotonic() - debut > budget_s:
            return
        with verrou:  # espacement global des appels
            attente = prochain[0] - time.monotonic()
            prochain[0] = max(prochain[0], time.monotonic()) + PAUSE_S
        if attente > 0:
            time.sleep(attente)
        entree = _interroger(s)
        if entree is not None:
            with verrou:
                cache[s] = entree
                faits[0] += 1
                if faits[0] % 300 == 0:
                    _sauver(dict(cache))
                    print(f"  {faits[0]}/{len(a_faire)} SIREN resolus", file=sys.stderr)

    with ThreadPoolExecutor(paralleles) as ex:
        list(ex.map(tache, a_faire))
    _sauver(cache)
    restants = len([s for s in a_faire if s not in cache])
    return cache, restants
