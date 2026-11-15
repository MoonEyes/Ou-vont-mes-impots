"""Arbre de depense a profondeur libre.

Entree : lignes plates (une par plus petite maille connue) + liste ordonnee de niveaux.
Sortie : site/data/arbre/racine.json (jusqu'au niveau de decoupe) et un fichier par
sous-arbre au-dela (site/data/arbre/<chemin>.json), charge a la demande par le site.

Format d'un noeud : {"id", "nom", "niveau", "md", "enfants": [...]}  ou, au point
de decoupe, {"id", "nom", "niveau", "md", "fichier": "arbre/xxx.json"} sans enfants.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _norm(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v) if v not in (None, "") else "?"


def construire(rows: list[dict], niveaux: list[dict], montant: str) -> dict:
    """Construit l'arbre complet en memoire. Les lignes a montant nul sont ignorees."""
    racine = {"enfants": {}, "eur": 0.0}
    for r in rows:
        v = r.get(montant) or 0.0
        if not v:
            continue
        noeud = racine
        noeud["eur"] += v
        for niv in niveaux:
            cle = _norm(r.get(niv["cle"]))
            if cle == "?" and not niv.get("obligatoire"):
                continue  # niveau non renseigne par la source : on le saute, la branche est juste moins profonde
            enfant = noeud["enfants"].get(cle)
            if enfant is None:
                nom = r.get(niv["libelle"]) or cle
                enfant = noeud["enfants"][cle] = {"cle": cle, "nom": str(nom).strip(), "niveau": niv["id"],
                                                  "enfants": {}, "eur": 0.0}
            enfant["eur"] += v
            noeud = enfant
    return racine


def _slug(chemin: list[str]) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "-", "_".join(chemin)).strip("-")


def ecrire(racine: dict, nom_racine: str, decoupe_apres: str, dossier: Path, entete: dict | None = None) -> dict:
    """Serialise l'arbre, decoupe en fichiers, et renvoie des statistiques de controle.

    `entete` (ex. {"millesime": ..., "source": ...}) est recopie en tete de chaque fichier ecrit.
    """
    entete = entete or {}
    dossier.mkdir(parents=True, exist_ok=True)
    for old in dossier.glob("*.json"):
        old.unlink()
    stats = {"noeuds": 0, "feuilles": 0, "profondeur": 0, "fichiers": 0}

    def md(eur: float) -> float:
        return round(eur / 1e9, 6)

    def serialiser(n: dict, chemin: list[str], profondeur: int, coupe: bool) -> dict:
        stats["noeuds"] += 1
        stats["profondeur"] = max(stats["profondeur"], profondeur)
        nid = "/".join(chemin) or "racine"
        out = {"id": nid, "nom": n.get("nom", nom_racine), "niveau": n.get("niveau", "racine"), "md": md(n["eur"])}
        enfants = sorted(n["enfants"].values(), key=lambda e: -e["eur"])
        if not enfants:
            stats["feuilles"] += 1
            return out
        if coupe:
            fichier = f"{_slug(chemin)}.json"
            prefixe = f"{dossier.name}/"
            sous = {**entete, **out, "enfants": [serialiser(e, chemin + [e["cle"]], profondeur + 1, False) for e in enfants]}
            (dossier / fichier).write_text(json.dumps(sous, ensure_ascii=False, separators=(",", ":")) + "\n",
                                           encoding="utf-8")
            stats["fichiers"] += 1
            return {**out, "fichier": prefixe + fichier, "nb_enfants": len(enfants)}
        out["enfants"] = [serialiser(e, chemin + [e["cle"]], profondeur + 1, e["niveau"] == decoupe_apres)
                          for e in enfants]
        return out

    arbre = {**entete, **serialiser(racine, [], 0, False)}
    (dossier / "racine.json").write_text(json.dumps(arbre, ensure_ascii=False, separators=(",", ":")) + "\n",
                                         encoding="utf-8")
    stats["fichiers"] += 1
    return stats
