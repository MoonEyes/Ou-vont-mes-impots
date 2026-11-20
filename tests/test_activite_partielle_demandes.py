"""Activité partielle 2020, demandes (pipeline/activite_partielle_demandes.py) : sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
F = ROOT / "site" / "data" / "activite_partielle_demandes" / "index.json"
sys.path.insert(0, str(ROOT / "pipeline"))
import activite_partielle_demandes as apd  # noqa: E402


def test_nombre():
    assert apd.nombre("") is None and apd.nombre("nc") is None and apd.nombre("2495.00") == 2495


def test_fichier_publie():
    if not F.exists():
        pytest.skip("absent")
    d = json.loads(F.read_text(encoding="utf-8"))
    assert d["lignes"] == sorted(d["lignes"], key=lambda x: (x[0], x[1]))
    assert {l[0] for l in d["lignes"]} <= set(d["regions"]) and {l[1] for l in d["lignes"]} <= set(d["secteurs"])
    assert any("ni additionnés" in r for r in d["regles"])
