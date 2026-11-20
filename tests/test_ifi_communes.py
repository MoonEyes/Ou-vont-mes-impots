"""Impôt sur la fortune immobilière par commune (pipeline/ifi_communes.py). Sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "ifi_communes"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import ifi_communes as ic  # noqa: E402
import valider_contrat as vc  # noqa: E402


def test_codes_et_unites():
    assert ic.code_insee("44 109") == "44109" and ic.code_insee(97422) == "97422" and ic.code_insee(6088) == "06088"
    assert ic.facteur("patrimoine moyen en millions d'euros") == 1_000_000
    assert ic.facteur("impôt moyen en milliers d'euros") == 1_000 and ic.facteur("impôt moyen en €") == 1


def test_fichiers_conformes_au_schema():
    js = vc.charger_jsonschema()
    for schema, motif, _ in vc.FICHIERS:
        if motif.startswith("ifi_communes/"):
            v = vc.validateur(js, schema)
            for f in sorted((ROOT / "site" / "data").glob(motif)):
                assert not vc.erreurs(v, json.loads(f.read_text(encoding="utf-8"))), f


def test_seuils_rupture_et_paris_par_arrondissement():
    idx = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
    assert "20 000" in idx["seuil"] and "50" in idx["seuil"] and "ISF" in idx["rupture"]
    d = json.loads((DOSSIER / "communes.json").read_text(encoding="utf-8"))
    paris = d["communes"]["75056"]
    assert paris["annees"] == {} and len(paris["arrondissements"]) == 20
    assert "06900" not in d["communes"]   # Monaco hors du code géographique


def test_montants_en_euros_toutes_annees():
    d = json.loads((DOSSIER / "communes.json").read_text(encoding="utf-8"))
    for an, v in d["communes"]["44109"]["annees"].items():
        assert v[0] > 50 and v[1] > 1_000_000 and v[2] > 1_000, an


@pytest.mark.skipif(not list(ic.LAKE.glob("ifi_*.xls*")), reason="entrepôt absent")
def test_production_reproductible(tmp_path):
    ic.produire(tmp_path / "a")
    ic.produire(tmp_path / "b")
    for f in sorted((tmp_path / "a").rglob("*.json")):
        assert f.read_bytes() == (tmp_path / "b" / f.relative_to(tmp_path / "a")).read_bytes(), f
