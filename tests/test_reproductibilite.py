"""Reproductibilité : chaque commande `produire` lancée deux fois sur le même entrepôt donne des sorties identiques
octet pour octet.

Les deux passages tournent dans un bac à sable (copie de pipeline/, site/ et data/processed/, entrepôt data/lake et
data/raw en lien symbolique, aucun réseau) avec deux graines de hachage Python différentes (PYTHONHASHSEED) : un
ordre d'ensemble, un hash() ou un choix arbitraire du moteur SQL se voit donc. Les dates écrites viennent de
pipeline/reproductible.py (date de la dernière collecte). Test lent (plusieurs minutes) ; sauté sans entrepôt
(runner GitHub, clone sans data/lake).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAKE = ROOT / "data" / "lake"

# Modules de précision lus depuis l'entrepôt (README, « Commandes »), dans l'ordre de leurs dépendances.
COMMANDES = [
    ["pipeline/prelevements.py", "produire"],
    ["pipeline/niches.py", "produire"],
    ["pipeline/secu.py", "produire"],
    ["pipeline/realisations.py", "produire"],
    ["pipeline/vie_politique.py", "produire"],
    ["pipeline/decisions.py", "produire"],
    ["pipeline/controle.py", "produire"],
    ["pipeline/local.py", "decisions"],
]

pytestmark = pytest.mark.skipif(not (LAKE / "manifest.json").exists(),
                                reason="entrepôt data/lake absent : reproductibilité non vérifiable ici")


def _bac(tmp: Path) -> Path:
    for x in ROOT.iterdir():
        if x.name not in ("site", "pipeline", "data", "web", ".git"):
            (tmp / x.name).symlink_to(x)
    shutil.copytree(ROOT / "pipeline", tmp / "pipeline", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "site", tmp / "site")
    (tmp / "data").mkdir()
    for d in ("lake", "raw"):
        (tmp / "data" / d).symlink_to(ROOT / "data" / d)
    if (ROOT / "data" / "processed").exists():
        shutil.copytree(ROOT / "data" / "processed", tmp / "data" / "processed")
    return tmp


def _empreintes(bac: Path) -> dict[str, str]:
    out = {}
    for base in ("site", "data/processed"):
        for f in sorted((bac / base).rglob("*")):
            if f.is_file():
                out[str(f.relative_to(bac))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def test_produire_deux_fois_donne_les_memes_octets(tmp_path):
    bac = _bac(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}
    passages = []
    for graine in ("1", "2"):
        for c in COMMANDES:
            r = subprocess.run([sys.executable, *c], cwd=bac, env={**env, "PYTHONHASHSEED": graine},
                               capture_output=True, text=True, timeout=1800)
            assert r.returncode == 0, f"{' '.join(c)} :\n{r.stderr[-2000:]}"
        passages.append(_empreintes(bac))
    a, b = passages
    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    assert not diff, f"{len(diff)} fichier(s) différents entre deux productions :\n" + "\n".join(diff[:30])
