"""Genere collecte/RAPPORT_COLLECTE.md a partir de data/lake/manifest.json (et decouvertes.json).

Usage : python collecte/rapport.py
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collecte import DECOUVERTES_PATH, LAKE, MANIFEST, charger_catalogue, lire_manifeste, maintenant  # noqa: E402

RAPPORT = Path(__file__).resolve().parent / "RAPPORT_COLLECTE.md"


def fichiers_valides(e: dict) -> list[dict]:
    return [f for f in e.get("fichiers", []) if f.get("octets")]


def synthese(manifeste: dict) -> dict:
    dom = defaultdict(lambda: {"sources": 0, "ok": 0, "erreurs": 0, "octets": 0, "lignes": 0, "fichiers": 0})
    tot = {"sources": 0, "ok": 0, "erreurs": 0, "octets": 0, "lignes": 0, "fichiers": 0}
    for e in manifeste.values():
        for agg in (dom[e.get("domaine", "?")], tot):
            agg["sources"] += 1
            agg["ok" if e.get("statut") in ("ok", "partiel") else "erreurs"] += 1
            for f in fichiers_valides(e):
                agg["octets"] += f["octets"]
                agg["lignes"] += f.get("lignes") or 0
                agg["fichiers"] += 1
    return {"domaines": dict(sorted(dom.items())), "total": tot}


def generer(manifeste: dict, decouvertes: dict | None = None, catalogue: dict | None = None) -> str:
    s = synthese(manifeste)
    t = s["total"]
    L = ["# Rapport de collecte de l'entrepot brut", "",
         f"Genere le {maintenant()} par `collecte/rapport.py` a partir de `{MANIFEST.relative_to(LAKE.parent.parent)}`.", "",
         "## Vue d'ensemble", "",
         f"- Sources suivies : {t['sources']} (ok : {t['ok']}, en erreur ou delai depasse : {t['erreurs']})",
         f"- Fichiers : {t['fichiers']}, volume : {t['octets'] / 1e6:,.1f} Mo",
         f"- Lignes comptees (Parquet et CSV) : {t['lignes']:,}".replace(",", " "),
         f"- Origine : {sum(1 for e in manifeste.values() if e.get('origine') != 'decouverte')} du catalogue manuel, "
         f"{sum(1 for e in manifeste.values() if e.get('origine') == 'decouverte')} des decouvertes automatiques"]
    try:
        u = shutil.disk_usage(LAKE)
        L.append(f"- Espace disque libre : {u.free / 1e9:,.1f} Go")
    except OSError:
        pass
    L += ["", "## Par domaine", "", "| Domaine | Sources | OK | Erreurs | Fichiers | Mo | Lignes |", "|---|---:|---:|---:|---:|---:|---:|"]
    for d, a in s["domaines"].items():
        L.append(f"| {d} | {a['sources']} | {a['ok']} | {a['erreurs']} | {a['fichiers']} | {a['octets'] / 1e6:,.1f} | {a['lignes']:,} |".replace(",", " "))

    err = {k: e for k, e in manifeste.items() if e.get("statut") not in ("ok", "partiel")}
    L += ["", f"## Erreurs ({len(err)})", ""]
    if not err:
        L.append("Aucune.")
    for k, e in sorted(err.items()):
        ant = " (fichiers d'une collecte precedente conserves)" if any(f.get("donnees_anterieures") for f in e.get("fichiers", [])) else ""
        L.append(f"- `{k}` [{e.get('statut')}] : {(e.get('erreur') or '').replace(chr(10), ' ')[:200]}{ant}")

    part = {k: e for k, e in manifeste.items() if e.get("erreurs_fichiers")}
    if part:
        L += ["", f"## Sources partielles ({len(part)}) : ressources en echec, les autres collectees", ""]
        for k, e in sorted(part.items()):
            L.append(f"- `{k}` : {len(e['erreurs_fichiers'])} ressource(s) en echec, ex. {e['erreurs_fichiers'][0]['erreur'][:150]}")

    pp = {k: e for k, e in manifeste.items() if e.get("personnes_physiques")}
    L += ["", f"## Sources avec donnees de personnes physiques ({len(pp)})", "",
          "Publiees en open data officiel, stockees sous `data/lake/_restreint/`. Collecte autorisee, affichage nominatif interdit.", ""]
    for k, e in sorted(pp.items()):
        mo = sum(f["octets"] for f in fichiers_valides(e)) / 1e6
        L.append(f"- `{k}` ({e.get('domaine')}, {e.get('statut')}, {mo:,.1f} Mo) : {e.get('titre')}")

    ign = [(k, i) for k, e in manifeste.items() for i in e.get("ignores", [])]
    lourdes = []
    if catalogue:
        lourdes = [s_ for s_ in catalogue.get("sources", []) if s_.get("lourd") and manifeste.get(s_["id"], {}).get("statut") not in ("ok", "partiel")]
    L += ["", "## Sources lourdes non prises", ""]
    if not ign and not lourdes:
        L.append("Aucune.")
    for s_ in lourdes:
        L.append(f"- `{s_['id']}` (catalogue, lourde) : {s_['titre']}")
    for k, i in ign:
        L.append(f"- `{k}` : ressource {i.get('titre')} ({(i.get('octets') or 0) / 1e6:,.0f} Mo, {i.get('motif')})")

    if catalogue and catalogue.get("non_collectables"):
        L += ["", "## Sources identifiees mais non collectables automatiquement", ""]
        L += [f"- {n['source']} : {n['motif']}" for n in catalogue["non_collectables"]]

    if decouvertes:
        jeux = decouvertes.get("jeux", [])
        par_portail = defaultdict(lambda: [0, 0, 0])
        for j in jeux:
            p = par_portail[j["portail"]]
            p[0] += 1
            p[1] += j["score"] >= 4
            p[2] += manifeste.get(j["id"], {}).get("statut") in ("ok", "partiel")
        L += ["", "## Decouvertes automatiques", "",
              f"`collecte/decouvertes.json` genere le {decouvertes.get('genere_le')} : {len(jeux)} jeux, "
              f"dont {sum(1 for j in jeux if j.get('doublon_de'))} doublons data.gouv.fr de portails ODS.", "",
              "| Portail | Jeux | Score >= 4 | Collectes |", "|---|---:|---:|---:|"]
        for p, (n, f, c) in sorted(par_portail.items()):
            L.append(f"| {p} | {n} | {f} | {c} |")
    return "\n".join(L) + "\n"


def main() -> int:
    dec = json.loads(DECOUVERTES_PATH.read_text(encoding="utf-8")) if DECOUVERTES_PATH.exists() else None
    RAPPORT.write_text(generer(lire_manifeste(), dec, charger_catalogue()), encoding="utf-8")
    print(f"ecrit : {RAPPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
