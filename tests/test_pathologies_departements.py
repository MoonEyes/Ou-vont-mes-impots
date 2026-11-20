"""Patients par pathologie et par département (pipeline/pathologies_departements.py) : licence ODbL, ordre de la
source, aucun montant déduit. Sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "pathologies_departements"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import pathologies_departements as pd_  # noqa: E402
import valider_contrat as vc  # noqa: E402


def test_fichiers_conformes_au_schema_et_sous_odbl():
    js = vc.charger_jsonschema()
    for schema, motif, _ in vc.FICHIERS:
        if motif.startswith("pathologies_departements/"):
            v = vc.validateur(js, schema)
            for f in sorted((ROOT / "site" / "data").glob(motif)):
                doc = json.loads(f.read_text(encoding="utf-8"))
                assert not vc.erreurs(v, doc), f
                assert doc["licence"] == "ODbL 1.0" and "partage à l'identique" in doc["mention"]


def test_ordre_de_la_source_et_population_en_tete():
    idx = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
    assert idx["ordre"][0] == "POP_TOT_IND"
    d = json.loads((DOSSIER / "departements.json").read_text(encoding="utf-8"))
    assert d["pathologies"] == idx["ordre"]
    an = max(d["departements"]["44"]["annees"])
    ligne = d["departements"]["44"]["annees"][an]
    assert len(ligne) == len(idx["ordre"]) and ligne[0][1] is None
    assert "montant" not in json.dumps(d, ensure_ascii=False)


@pytest.mark.skipif(not (pd_.LAKE / "effectifs.parquet").exists(), reason="entrepôt absent")
def test_production_reproductible(tmp_path):
    pd_.produire(tmp_path / "a")
    pd_.produire(tmp_path / "b")
    for f in sorted((tmp_path / "a").rglob("*.json")):
        assert f.read_bytes() == (tmp_path / "b" / f.relative_to(tmp_path / "a")).read_bytes(), f
