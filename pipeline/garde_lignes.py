"""Garde-fou de publication : aucun axe publié ne perd de lignes sans motif compté.

    python pipeline/garde_lignes.py                 # compare site/data (et data/processed) à HEAD ; code 7 si perte
    python pipeline/garde_lignes.py --base REV      # autre référence git (ex. origin/main)

Une « ligne » est un enregistrement : élément d'une liste JSON (à toute profondeur), ligne d'un CSV hors en-tête.
Le compte se fait par axe (premier dossier sous site/data, ou le fichier lui-même au premier niveau) : un axe qui
découpe un fichier en plusieurs ne perd rien, un fichier supprimé perd toutes ses lignes.

Une perte n'est admise que si pipeline/pertes_autorisees.json la couvre :

    {"pertes": [{"axe": "local", "lignes_max": 1200, "motif": "...", "jusqu_au": "2026-12-31"}]}

`lignes_max` est le nombre de lignes que l'axe peut perdre à ce passage, `motif` le dit en clair (source qui retire
des données, correction d'un doublon...) ; une autorisation périmée (`jusqu_au` passé) ne compte plus. Bibliothèque
standard seulement.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTORISATIONS = ROOT / "pipeline" / "pertes_autorisees.json"
DOSSIERS = ("site/data", "data/processed")
CODE_PERTE = 7
IGNORES = {"site/data/meta.json", "site/data/mise_a_jour.json"}


def compter(octets: bytes, nom: str) -> int:
    """Nombre d'enregistrements d'un fichier publié (0 si le format n'est pas tabulaire ni JSON)."""
    if nom.endswith(".json"):
        try:
            return _compter_json(json.loads(octets.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            return 0
    if nom.endswith((".csv", ".tsv")):
        texte = octets.decode("utf-8", errors="replace")
        lignes = sum(1 for _ in csv.reader(io.StringIO(texte), delimiter="\t" if nom.endswith(".tsv") else ","))
        return max(0, lignes - 1)
    return 0


def _compter_json(x) -> int:
    pile, n = [x], 0
    while pile:
        v = pile.pop()
        if isinstance(v, list):
            n += len(v)
            pile.extend(v)
        elif isinstance(v, dict):
            pile.extend(v.values())
    return n


def axe(chemin: str) -> str:
    for d in DOSSIERS:
        if chemin.startswith(d + "/"):
            reste = chemin[len(d) + 1:]
            return f"{d}/{reste.split('/', 1)[0]}"
    return chemin


def _git(*args: str, entree: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, input=entree, capture_output=True, check=True).stdout


def comptes_reference(base: str) -> dict[str, int]:
    """Lignes par axe dans la révision `base` (git cat-file --batch, sans extraire l'arbre)."""
    lignes = _git("ls-tree", "-r", "-z", base, "--", *DOSSIERS).split(b"\0")
    objets = []
    for l in lignes:
        if not l:
            continue
        meta, chemin = l.split(b"\t", 1)
        if meta.split()[1] == b"blob":
            objets.append((chemin.decode(), meta.split()[2].decode()))
    objets = [(c, o) for c, o in objets if c not in IGNORES and c.endswith((".json", ".csv", ".tsv"))]
    sortie = _git("cat-file", "--batch", entree="\n".join(o for _, o in objets).encode() + b"\n")
    comptes: dict[str, int] = {}
    pos = 0
    for c, _ in objets:
        fin_entete = sortie.index(b"\n", pos)
        taille = int(sortie[pos:fin_entete].split()[2])
        contenu = sortie[fin_entete + 1:fin_entete + 1 + taille]
        pos = fin_entete + 1 + taille + 1
        comptes[axe(c)] = comptes.get(axe(c), 0) + compter(contenu, c)
    return comptes


def comptes_courants() -> dict[str, int]:
    comptes: dict[str, int] = {}
    for d in DOSSIERS:
        base = ROOT / d
        if not base.exists():
            continue
        for f in base.rglob("*"):
            c = str(f.relative_to(ROOT))
            if f.is_file() and c not in IGNORES and f.suffix in (".json", ".csv", ".tsv") and "_restreint" not in f.parts:
                comptes[axe(c)] = comptes.get(axe(c), 0) + compter(f.read_bytes(), c)
    return comptes


def autorisations(aujourdhui: date | None = None) -> dict[str, dict]:
    if not AUTORISATIONS.exists():
        return {}
    jour = (aujourdhui or date.today()).isoformat()
    sortie = {}
    for p in json.loads(AUTORISATIONS.read_text(encoding="utf-8")).get("pertes", []):
        if not p.get("motif") or not isinstance(p.get("lignes_max"), int):
            continue   # une autorisation sans motif ni nombre ne vaut rien
        if p.get("jusqu_au") and p["jusqu_au"] < jour:
            continue
        nom = p["axe"] if "/" in p["axe"] else f"site/data/{p['axe']}"
        sortie[nom] = p
    return sortie


def controler(avant: dict[str, int], apres: dict[str, int], permis: dict[str, dict]) -> tuple[list[str], list[str]]:
    """(refus, pertes admises) ; une perte au-delà de lignes_max est refusée."""
    refus, admises = [], []
    for a in sorted(avant):
        perte = avant[a] - apres.get(a, 0)
        if perte <= 0:
            continue
        p = permis.get(a)
        texte = f"{a} : {avant[a]} -> {apres.get(a, 0)} lignes ({perte} perdues)"
        if p and perte <= p["lignes_max"]:
            admises.append(f"{texte}, admis : {p['motif']}")
        else:
            refus.append(texte + (f", au-delà des {p['lignes_max']} admises" if p else ", sans motif compté"))
    return refus, admises


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="HEAD", help="révision de référence (défaut : HEAD, la version publiée)")
    a = ap.parse_args(argv)
    refus, admises = controler(comptes_reference(a.base), comptes_courants(), autorisations())
    for l in admises:
        print(f"perte admise : {l}")
    for l in refus:
        print(f"::error::perte de lignes refusée : {l}")
    if refus:
        print(f"{len(refus)} axe(s) perdent des lignes sans motif compté : publication refusée "
              f"(ajouter le motif et le nombre dans {AUTORISATIONS.relative_to(ROOT)} si la perte est voulue)")
        return CODE_PERTE
    print("garde-fou : aucun axe publié ne perd de lignes sans motif compté")
    return 0


if __name__ == "__main__":
    sys.exit(main())
