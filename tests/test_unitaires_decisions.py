"""Tests unitaires (entrées construites à la main) des montants et signes de pipeline/decisions.py."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import decisions as d  # noqa: E402


@pytest.mark.parametrize("brut,attendu", [
    ("89 753 974", 89753974.0), ("89 753 974", 89753974.0), ("-3000000", -3000000.0),
    ("+ 1 000", 1000.0), ("1,5", 1.5), ("− 12", -12.0), ("– 7", -7.0), ("", 0.0), (None, 0.0),
    ("texte", 0.0), (12, 12.0),
])
def test_montant(brut, attendu):
    assert d.montant(brut) == attendu


def test_nil_et_listify():
    assert d.nil(None) and d.nil({"@xsi:nil": "true"}) and not d.nil({})
    assert d.listify(None) == [] and d.listify({"@xsi:nil": "true"}) == []
    assert d.listify("a") == ["a"] and d.listify([1, 2]) == [1, 2]


def test_ae_cp_plf_et_plfr():
    assert d.ae_cp({"creditPaiement": "1 000"}, "creditPaiement") == 1000.0
    # PLFR : supplémentaire moins annulé (l'annulation est toujours soustraite, quel que soit son signe publié)
    p = {"creditPaiementSupplementaire": "500", "creditPaiementAnnule": "-200"}
    assert d.ae_cp(p, "creditPaiement") == 300.0
    assert d.ae_cp({"creditPaiementAnnule": "200"}, "creditPaiement") == -200.0


def test_premier_nombre_cellule_multiligne():
    assert d.premier_nombre("1 234 567|dont titre 2 : 12 000") == 1234567.0
    assert d.premier_nombre("titre|-12 500,5") == -12500.5
    assert d.premier_nombre("") == 0.0
    assert d.premier_nombre(None) == 0.0


@pytest.mark.parametrize("entete,contexte,typ,signe", [
    ("Crédits annulés", "", "", -1),
    ("Crédits ouverts", "", "", 1),
    ("Montant", "les crédits suivants sont ouverts", "", 1),
    ("Montant", "ouverts puis annulés", "", -1),
    ("Montant", "", "annulation", -1),
    ("Montant", "", "fonds_de_concours", 1),
    ("Montant", "", "autre", None),
])
def test_signe(entete, contexte, typ, signe):
    assert d._signe(entete, contexte, typ) == signe


def test_montant_compare_reports():
    assert d.montant_compare({}, {"cp": -5.0}, "reports_entrants") == 0.0
    assert d.montant_compare({}, {"cp": 5.0}, "reports_entrants") == 5.0
    assert d.montant_compare({}, {"cp": -5.0}, "annulations") == -5.0
