"""Tests unitaires (entrées construites à la main) des conversions de montants et des clés de tri de
pipeline/vie_politique.py."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import vie_politique as vp  # noqa: E402


@pytest.mark.parametrize("brut,attendu", [
    ("1 234,56", 1234.56),
    ("1 234 567", 1234567.0),
    ("1234.56", 1234.56),
    ("1.234,56", 1234.56),  # point de milliers et virgule décimale
    ("12 €", 12.0),
    ("-5", -5.0),
    (1234, 1234.0),
    (12.5, 12.5),
])
def test_nombre(brut, attendu):
    assert vp.nombre(brut) == pytest.approx(attendu)


@pytest.mark.parametrize("brut", [None, "", "-", "nc", "NC", "nan", "None", float("nan"), "texte"])
def test_nombre_absent(brut):
    assert vp.nombre(brut) is None


def test_montant_conversion_franc_pacifique():
    # parité fixe : 1 000 F CFP = 8,38 EUR ; le montant XPF est publié en milliers ici
    assert vp._montant("119,33", "XPF") == pytest.approx(1.0)
    assert vp._montant("1000", "CFP") == pytest.approx(1000 / 119.33)
    assert vp._montant("1000", "EUR") == 1000.0
    assert vp._montant("nc", "XPF") is None


def test_arrondi_et_somme():
    assert vp.arrondi(None) is None
    assert vp.arrondi("1.234") == 1.23
    assert vp.arrondi(1005) == 1005.0
    assert vp._somme([{"a": 1.111}, {"a": None}, {"b": 3}, {"a": 2.222}], "a") == 3.33
    assert vp._somme([{"a": None}], "a") is None


def test_deux_nombres_cas_documentes():
    assert vp._deux_nombres(["449313", "449371"]) == (449313.0, 449371.0)
    assert vp._deux_nombres(["470", "371", "470", "371"]) == (470371.0, 470371.0)
    assert vp._deux_nombres(["12", "345", "6", "789"]) == (12345.0, 6789.0)


def test_deux_nombres_montants_differents_de_meme_longueur():
    assert vp._deux_nombres(["470", "371", "470", "372"]) == (470371.0, 470372.0)


def test_cle_alpha_ordre_naturel_sans_accent():
    noms = ["Liste 10", "liste 2", "Écologie", "Avenir"]
    assert sorted(noms, key=vp.cle_alpha) == ["Avenir", "Écologie", "liste 2", "Liste 10"]


def test_nom_tri_retire_l_article_et_unifie():
    assert vp.nom_tri("Les Républicains") == "REPUBLICAINS"
    assert vp.nom_tri("L’Avenir") == "AVENIR"
    assert vp.nom_tri("La  France   insoumise") == "FRANCE INSOUMISE"
    assert vp.nom_tri("Lutte ouvrière") == "LUTTE OUVRIERE"  # « Lu » n'est pas un article
