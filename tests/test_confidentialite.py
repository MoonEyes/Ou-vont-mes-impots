# tests/test_confidentialite.py
"""Aucune donnee de personne physique hors elus et candidats dans site/data."""
import json
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site" / "data"
CJ_INTERDITES = re.compile(r"^(1\d{3}|2110|2210|2310|2385)$")
CLES_INTERDITES = {"donateur", "donateurs", "mandataire", "mandataire_financier", "adresse",
                   "date_naissance", "naissance", "courriel", "email", "telephone", "iban"}


def _parcourir(x, colonnes=None):
    if isinstance(x, dict):
        yield from ((k, v) for k, v in x.items())
        for v in x.values():
            yield from _parcourir(v, x.get("colonnes"))
    elif isinstance(x, list):
        if colonnes and "categorie_juridique" in colonnes and len(x) == len(colonnes) \
                and not any(isinstance(v, (list, dict)) for v in x):
            yield "categorie_juridique", x[colonnes.index("categorie_juridique")]
        for v in x:
            yield from _parcourir(v, colonnes)


def test_aucune_personne_physique_publiee():
    fautes = []
    for f in SITE.rglob("*.json"):
        for cle, val in _parcourir(json.loads(f.read_text(encoding="utf-8"))):
            if cle in CLES_INTERDITES or (cle == "categorie_juridique" and CJ_INTERDITES.match(str(val or ""))):
                fautes.append(f"{f.relative_to(SITE)} : {cle}={str(val)[:40]}")
    assert not fautes, "\n".join(fautes[:20])


def test_rien_de_restreint_dans_site():
    assert not [p for p in SITE.rglob("*") if "_restreint" in p.parts]


def test_groupements_de_personnes_physiques_jamais_nommes():
    import sys
    sys.path.insert(0, str(SITE.parents[1] / "pipeline"))
    import sirene
    for cj in ("1000", "2110", "2210", "2310", "2385", "", None, "0"):
        assert not sirene.personne_morale(cj), cj
    for cj in ("5710", "9220", "7210", "2900"):
        assert sirene.personne_morale(cj), cj
