"""Polices municipales (pipeline/police_municipale.py) : rapprochement des noms par département. Sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "police_municipale"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import police_municipale as pm  # noqa: E402
import valider_contrat as vc  # noqa: E402


def test_normalisation_des_noms():
    assert pm.norm("ST NAZAIRE") == pm.norm("Saint-Nazaire") == "saint nazaire"
    assert pm.norm("Foret-Fouesnant (la)") == pm.norm("La Forêt-Fouesnant")
    assert pm.cle_dep(1) == "01" and pm.cle_dep("2A") == "2A" and pm.cle_dep(974) == "974" and pm.cle_dep("AIN") is None


def test_valeurs():
    assert pm.valeur("3") == 3 and pm.valeur(0.5) == 0.5 and pm.valeur(None) is None and pm.valeur("x") is None


def test_fichiers_conformes_au_schema():
    js = vc.charger_jsonschema()
    for schema, motif, _ in vc.FICHIERS:
        if motif.startswith("police_municipale/"):
            v = vc.validateur(js, schema)
            for f in sorted((ROOT / "site" / "data").glob(motif)):
                assert not vc.erreurs(v, json.loads(f.read_text(encoding="utf-8"))), f


def test_couverture_et_rapprochement_ecrits():
    idx = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
    for an, c in idx["couverture"]["par_annee"].items():
        assert c["rapprochees"] / c["lignes"] > 0.9, an
    assert "code Insee" in idx["rapprochement"] and "jamais 0" in idx["absence"]


@pytest.mark.skipif(not list(pm.LAKE.glob("pm_*")), reason="entrepôt absent")
def test_production_reproductible(tmp_path):
    pm.produire(tmp_path / "a")
    pm.produire(tmp_path / "b")
    for f in sorted((tmp_path / "a").rglob("*.json")):
        assert f.read_bytes() == (tmp_path / "b" / f.relative_to(tmp_path / "a")).read_bytes(), f
