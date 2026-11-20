"""Totaux ATIH (pipeline/hopitaux_totaux.py) : seules les lignes de total de la source sont publiées."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
F = ROOT / "site" / "data" / "hopitaux_totaux" / "index.json"
sys.path.insert(0, str(ROOT / "pipeline"))
import hopitaux_totaux as ht  # noqa: E402


def test_valeur():
    assert ht.valeur(None, "produits_eur") is None and ht.valeur(float("nan"), "x") is None
    assert ht.valeur(1.234, "taux_caf_pct") == 1.23 and ht.valeur(10.6, "produits_eur") == 11


def test_seulement_des_totaux_de_la_source():
    if not F.exists():
        pytest.skip("absent")
    d = json.loads(F.read_text(encoding="utf-8"))
    assert d["licence"] == "ODbL 1.0"
    assert all("TOT" in l[1:4] for l in d["lignes"])
    assert {l[0] for l in d["lignes"]} >= {2020, 2024}
