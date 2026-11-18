"""Confidentialité : aucune dénomination publiée d'association, de fonds de dotation ou d'organisation reliée
(entites/) ne doit être un nom de personne seul (« Prénom Nom », « Prénom Nom, président »).

Filtre : pipeline/associations.py, nom_de_personne_seul (prénoms fréquents de SIRENE quand le cache est présent,
liste minimale de pipeline/local.py sinon). Une telle dénomination n'est pas nommée : son montant reste agrégé.
Les sociétés au nom de leur fondateur (marchés, aides) restent nommées : personnes morales (sirene.personne_morale).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import associations as A  # noqa: E402

SITE = ROOT / "site" / "data"


def test_filtre_nom_de_personne_seul():
    assert A.nom_de_personne_seul("JEAN DUPONT")
    assert A.nom_de_personne_seul("Bernard Martin, président")
    assert A.nom_de_personne_seul("Marie Durand")
    assert not A.nom_de_personne_seul("ASSOCIATION JEAN DUPONT")
    assert not A.nom_de_personne_seul("FONDATION PIERRE DURAND")
    assert not A.nom_de_personne_seul("CLUB DE RUGBY")
    assert not A.nom_de_personne_seul("SAINT-JEAN DE LUZ")
    assert not A.nom_de_personne_seul(None)
    # Une dénomination ainsi détectée n'est jamais publiée (même règle que les associations de financement électoral).
    assert A.denomination_nominative("JEAN DUPONT")


def _noms(p: Path):
    d = json.loads(p.read_text(encoding="utf-8"))

    def w(x, cle=""):
        if isinstance(x, dict):
            for k, v in x.items():
                yield from w(v, k)
        elif isinstance(x, list):
            if len(x) > 1 and isinstance(x[0], str) and re.fullmatch(r"\d{9}|\d{14}|\d{3}-FDD-[\w-]+", x[0]) \
                    and isinstance(x[1], str):
                yield x[1]
            for v in x:
                yield from w(v, cle)
        elif isinstance(x, str) and cle in ("nom", "denomination", "nom_usuel", "libelle"):
            yield x
    yield from w(d)


FICHIERS = sorted([*SITE.glob("associations/programmes/*.json"), SITE / "associations" / "fonds_fondations.json",
                   *SITE.glob("entites/**/*.json")])


@pytest.mark.parametrize("fichier", [f for f in FICHIERS if f.exists()], ids=lambda p: str(p.relative_to(SITE)))
def test_aucun_nom_de_personne_seul_publie(fichier: Path):
    fautes = sorted({n for n in _noms(fichier) if A.nom_de_personne_seul(n)})
    assert not fautes, f"{fichier.relative_to(SITE)} : dénominations qui ressemblent à un nom de personne : {fautes[:10]}"
