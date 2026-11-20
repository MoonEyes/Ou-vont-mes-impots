"""Budgets des universités (pipeline/universites.py) : fonctions pures et cohérence des fichiers publiés, sans réseau."""
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "universites"
sys.path.insert(0, str(ROOT / "pipeline"))
import universites  # noqa: E402


def _json(nom: str):
    p = DOSSIER / nom
    if not p.exists():
        pytest.skip(f"{p} absent")
    return json.loads(p.read_text(encoding="utf-8"))


def test_valeur_absente_jamais_zero():
    assert universites.valeur(None, 0) is None
    assert universites.valeur(float("nan"), 0) is None
    assert universites.valeur("x", 1) is None
    assert universites.valeur(0, 0) == 0
    assert universites.valeur(12.345, 1) == 12.3
    assert universites.valeur(1234.6, 0) == 1235


def test_indicateurs_documentes():
    cles = [k for k, *_ in universites.INDICATEURS]
    assert len(cles) == len(set(cles))
    for _k, col, lib, unite in universites.INDICATEURS:
        assert col and lib and unite in universites.DECIMALES
    # ratios « sur 100 € » : repris de la source, jamais calculés
    assert {"personnel_sur_100", "ressources_propres_sur_100"} <= set(cles)


def test_fichiers_publies_coherents():
    idx = _json("index.json")
    et = _json("etablissements.json")
    cles = [i["cle"] for i in idx["indicateurs"]]
    assert et["colonnes"] == ["nature", *cles]
    assert idx["couverture"]["etablissements"] == len(et["etablissements"]) > 100
    natures = {str(e["annee"]): e["nature"] for e in idx["exercices"]}
    for e in et["etablissements"]:
        for an, vals in e["exercices"].items():
            assert len(vals) == len(et["colonnes"])
            assert vals[0] == natures[an]
            assert all(v is None or (isinstance(v, (int, float)) and not math.isnan(v)) for v in vals[1:])
    # ordre alphabétique (sans accents), jamais par montant
    noms = [e["nom"] for e in et["etablissements"]]
    import unicodedata
    cle = lambda s: "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    assert [cle(n) for n in noms] == sorted(cle(n) for n in noms)


def test_aucun_calcul_du_site():
    idx = _json("index.json")
    assert all(i["statut"] == "publié par la source" for i in idx["indicateurs"])
    texte = json.dumps(idx, ensure_ascii=False).lower()
    assert "par étudiant" not in texte.replace("aucun montant par étudiant", "")
    assert idx["manques"] and "subvention pour charges de service public" in idx["manques"][0]["quoi"]
