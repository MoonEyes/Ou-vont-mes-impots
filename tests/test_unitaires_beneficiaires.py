"""Tests unitaires (entrées construites à la main) de pipeline/beneficiaires.py : nombres, pourcentages, statut de
publication d'un SIREN (filtre de confidentialité), conservation des totaux et ordre de résolution."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import beneficiaires as b  # noqa: E402


def test_num_eur_sur_100():
    assert b.num("1 234,5") == 1234.5
    assert b.num("1 000") == 1000.0
    assert b.num(None) == 0.0 and b.num("") == 0.0 and b.num(3) == 3.0
    assert b.eur(1.005 + 1e-9) == 1.01
    assert b.sur_100(1, 3) == 33.333333
    assert b.sur_100(1, 0) is None
    assert b.propre(" a \n b ") == "a b"


@pytest.mark.parametrize("siren,cj,cache,attendu", [
    ("123", "5710", {}, ("ni", None)),                       # SIREN invalide
    ("123456789", "5710", {}, ("pm", "5710")),
    ("123456789", "5710.0", {}, ("pm", "5710")),              # catégorie lue en flottant
    ("123456789", 7210, {}, ("pm", "7210")),
    ("123456789", "1000", {}, ("pp", "1000")),               # entrepreneur individuel : jamais nommé
    ("123456789", "2110", {}, ("ni", None)),                 # indivision : jamais nommée
    ("123456789", "", {}, ("nv", None)),                     # catégorie inconnue, pas encore vérifiée
    ("123456789", "0000", {}, ("nv", None)),
    ("123456789", None, {"123456789": {"cj": "5499"}}, ("pm", "5499")),
    ("123456789", "", {"123456789": {"cj": "1000"}}, ("pp", "1000")),
    ("123456789", "", {"123456789": {"cj": None, "trouve": False}}, ("ni", None)),
])
def test_statut(siren, cj, cache, attendu):
    assert b.statut(siren, cj, cache) == attendu


def test_top_et_autres_conservation(monkeypatch):
    monkeypatch.setattr(b, "TOP", 2)
    par_siren = {"111111111": {"montant": 10.0, "nom": "A"}, "222222222": {"montant": 30.0, "nom": "B"},
                 "333333333": {"montant": 10.0, "nom": "C"}, "444444444": {"montant": 5.004, "nom": "D"}}
    nv = {"montant": 7.0, "sirens": {"555555555"}}
    r = b.top_et_autres(par_siren, 30 + 10 + 10 + 5.004 + 3 + 7, {"montant_eur": 3.0}, nv)
    assert [x["siren"] for x in r["top"]] == ["222222222", "111111111"]  # égalité départagée par le SIREN
    assert r["top"][0] == {"siren": "222222222", "nom": "B", "montant_eur": 30.0}
    assert r["autres"] == {"nombre": 2, "montant_eur": 15.0}
    assert r["non_verifies"]["montant_eur"] == 7.0 and r["non_verifies"]["nombre"] == 1
    with pytest.raises(SystemExit, match="Conservation rompue"):
        b.top_et_autres(par_siren, 1000.0, {"montant_eur": 3.0}, nv)


def test_tour_de_role():
    g1 = {"a": 3, "b": 2, "c": 1}
    g2 = {"x": 10, "a": 5}
    assert b.tour_de_role([g1, {}, g2]) == ["a", "x", "b", "c"]
    assert b.tour_de_role([]) == []
