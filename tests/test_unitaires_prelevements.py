"""Tests unitaires (entrées construites à la main) de pipeline/prelevements.py : nombres, codes INSEE et TVA
théorique (taux appliqués hors taxe : t / (1 + t))."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import prelevements as p  # noqa: E402


@pytest.mark.parametrize("brut,attendu", [
    ("12,5", 12.5), (" 3 ", 3.0), ("", 0.0), ("-", 0.0), (None, 0.0), ("nc", 0.0), (4, 4.0),
])
def test_num(brut, attendu):
    assert p.num(brut) == attendu


def test_r2_et_part():
    assert p.r2(None) is None and p.r2(1.006) == 1.01
    assert p._part("Etat", 1 / 3, "src", note="n") == {"destinataire": "Etat", "part": 0.333333, "source": "src",
                                                       "note": "n"}


def test_code_insee():
    assert p.code_insee("44", "109") == "44109"
    assert p.code_insee("2A", "004") == "2A004"
    assert p.code_insee("971", "105") == "97105"


def test_tva_theorique_sous_postes_et_reste(monkeypatch):
    monkeypatch.setattr(p, "TAUX_TVA", {"011": 0.055, "044": 0.20, "0443": 0.10})
    conso = {("011", "D1"): 105.5, ("044", "D1"): 220.0, ("0443", "D1"): 110.0,
             ("13A", "D1"): 999.0, ("130", "D1"): 999.0,  # hors champ (non numérique, 13x)
             ("011", "D2"): 1000.0}
    # 011 : 105,5 x 0,055/1,055 = 5,5 ; 0443 : 110 x 0,1/1,1 = 10 ; reste 044 : 110 x 0,2/1,2
    assert p.tva_theorique(conso, "D1") == pytest.approx(5.5 + 10 + 110 * 0.2 / 1.2)


def test_tva_theorique_poste_sans_taux(monkeypatch):
    monkeypatch.setattr(p, "TAUX_TVA", {})
    with pytest.raises(SystemExit, match="sans taux"):
        p.tva_theorique({("011", "D1"): 1.0}, "D1")
