"""Emploi dans les territoires (pipeline/emploi_territoires.py) : Unédic par département, Dares par commune."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "emploi_territoires"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import emploi_territoires as et  # noqa: E402
import valider_contrat as vc  # noqa: E402


def test_nombres():
    assert et.num(None) is None and et.num(float("nan")) is None and et.num(12.04) == 12 and et.num(12.34) == 12.3


def test_fichiers_conformes_au_schema():
    js = vc.charger_jsonschema()
    for schema, motif, _ in vc.FICHIERS:
        if motif.startswith("emploi_territoires/"):
            v = vc.validateur(js, schema)
            fichiers = sorted((ROOT / "site" / "data").glob(motif))
            assert fichiers, motif
            for f in fichiers:
                assert not vc.erreurs(v, json.loads(f.read_text(encoding="utf-8"))), f


def test_departements_du_code_geographique_seulement():
    d = json.loads((DOSSIER / "departements.json").read_text(encoding="utf-8"))
    geo = {f.stem for f in (ROOT / "site" / "data" / "local" / "geo").glob("*.json")}
    assert set(d["departements"]) <= geo and len(d["departements"]) >= 96
    assert all(m.endswith("-12") or m == d["dernier_mois"] for x in d["departements"].values() for m in x["mois"])


def test_inscrits_arrondis_a_cinq():
    d = json.loads((DOSSIER / "communes" / "44.json").read_text(encoding="utf-8"))
    assert all(v is None or v % 5 == 0 for serie in d["communes"].values() for v in serie)
    assert len(d["communes"]["44066"]) == len(d["annees"])


@pytest.mark.skipif(not (et.LAKE / "dares.parquet").exists(), reason="entrepôt absent")
def test_production_reproductible(tmp_path):
    et.produire(tmp_path / "a")
    et.produire(tmp_path / "b")
    for f in sorted((tmp_path / "a").rglob("*.json")):
        assert f.read_bytes() == (tmp_path / "b" / f.relative_to(tmp_path / "a")).read_bytes(), f
