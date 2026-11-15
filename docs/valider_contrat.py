"""Valide les fichiers de site/data contre le contrat d'interface (docs/schemas/*.schema.json).

Usage :
    python docs/valider_contrat.py            # tous les fichiers
    python docs/valider_contrat.py --quiet    # n'affiche que les erreurs et le bilan

Code de sortie : 0 si tout fichier present est conforme ; 1 si un fichier present est
non conforme ou si un fichier marque "existant" manque. Un fichier "prevu" absent est
signale (PREVU) sans faire echouer la validation.
"""
from __future__ import annotations

import argparse
import glob
import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
SCHEMAS = Path(__file__).resolve().parent / "schemas"
EXEMPLES = Path(__file__).resolve().parent / "exemples"

# (schema, motif relatif a site/data, etat attendu)
FICHIERS = [
    ("meta.schema.json", "meta.json", "existant"),
    ("sankey_etat.schema.json", "sankey_etat.json", "existant"),
    ("nature_etat.schema.json", "nature_etat.json", "existant"),
    ("arbre_etat.schema.json", "arbre/*.json", "existant"),
    ("programme.schema.json", "programmes/*.json", "existant"),
    ("arbre_administrations.schema.json", "arbre_administrations/racine.json", "existant"),
    ("arbre_administrations_methode.schema.json", "arbre_administrations/methode.json", "existant"),
    ("administrations.schema.json", "administrations.json", "existant"),
    ("recettes.schema.json", "recettes.json", "existant"),
    ("cofog.schema.json", "cofog.json", "existant"),
    ("deficit.schema.json", "deficit.json", "existant"),
    ("communes.schema.json", "communes/*.json", "existant"),
    ("affectation_prelevements.schema.json", "affectation_prelevements.json", "prevu"),
]

# Exemples du contrat du module de calcul (docs/exemples/<prefixe>*.json)
EXEMPLES_SCHEMAS = [("profil.schema.json", "profil_*.json"), ("resultat.schema.json", "resultat_*.json")]


def charger_jsonschema():
    try:
        return importlib.import_module("jsonschema")
    except ImportError:
        print("jsonschema absent : installation (pip install jsonschema)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "jsonschema>=4.18"])
        importlib.invalidate_caches()
        return importlib.import_module("jsonschema")


def best_match(erreurs_):
    from jsonschema.exceptions import best_match as bm
    return bm(erreurs_)


def validateur(js, nom_schema: str):
    schema = json.loads((SCHEMAS / nom_schema).read_text(encoding="utf-8"))
    cls = js.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema, format_checker=cls.FORMAT_CHECKER)


def erreurs(v, doc, limite: int = 5) -> list[str]:
    out = []
    for e in sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        if e.context:  # oneOf / anyOf : montrer l'erreur la plus precise
            e = best_match(e.context)
        chemin = "/" + "/".join(str(p) for p in e.absolute_path)
        out.append(f"{chemin} : {e.message[:200]}")
        if len(out) >= limite:
            out.append("...")
            break
    return out


def liens_arbre(chemin: Path, doc: dict) -> list[str]:
    """Controle hors schema : chaque 'fichier' reference par un noeud existe."""
    manquants = []

    def parcourir(n):
        if "fichier" in n and not (SITE / n["fichier"]).exists():
            manquants.append(f"{n['id']} -> {n['fichier']} introuvable")
        for e in n.get("enfants", []):
            parcourir(e)

    parcourir(doc)
    return manquants


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    js = charger_jsonschema()

    n_ok = n_ko = n_prevus = n_manquants = 0
    for nom_schema, motif, etat in FICHIERS:
        v = validateur(js, nom_schema)
        chemins = sorted(Path(p) for p in glob.glob(str(SITE / motif)))
        if not chemins:
            if etat == "prevu":
                n_prevus += 1
                print(f"PREVU    {motif} : absent (schema {nom_schema} pret)")
            else:
                n_manquants += 1
                print(f"MANQUANT {motif} : fichier attendu absent")
            continue
        ko_motif = 0
        for p in chemins:
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"KO       {p.relative_to(ROOT)} : JSON illisible ({exc})")
                ko_motif += 1
                continue
            errs = erreurs(v, doc)
            if nom_schema == "arbre_etat.schema.json":
                errs += liens_arbre(p, doc)
            if errs:
                ko_motif += 1
                print(f"KO       {p.relative_to(ROOT)}")
                for e in errs:
                    print(f"           {e}")
        n_ko += ko_motif
        n_ok += len(chemins) - ko_motif
        if not args.quiet and not ko_motif:
            print(f"OK       {motif} ({len(chemins)} fichier{'s' if len(chemins) > 1 else ''})")

    for nom_schema, motif in EXEMPLES_SCHEMAS:
        v = validateur(js, nom_schema)
        for p in sorted(EXEMPLES.glob(motif)):
            errs = erreurs(v, json.loads(p.read_text(encoding="utf-8")))
            if errs:
                n_ko += 1
                print(f"KO       {p.relative_to(ROOT)}")
                for e in errs:
                    print(f"           {e}")
            else:
                n_ok += 1
                if not args.quiet:
                    print(f"OK       {p.relative_to(ROOT)}")

    print(f"\nBilan : {n_ok} conformes, {n_ko} non conformes, {n_manquants} manquants, {n_prevus} prevus absents")
    return 1 if (n_ko or n_manquants) else 0


if __name__ == "__main__":
    sys.exit(main())
