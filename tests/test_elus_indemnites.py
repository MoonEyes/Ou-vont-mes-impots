"""Indemnités des élus par commune (pipeline/elus_indemnites.py) : total du compte 653, jamais par élu. Sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "elus_indemnites"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import elus_indemnites as ei  # noqa: E402
import valider_contrat as vc  # noqa: E402


def test_euros_absents_jamais_zero():
    assert ei.euros(None) is None and ei.euros("") is None and ei.euros("10.4") == 10


def test_fichiers_conformes_au_schema():
    js = vc.charger_jsonschema()
    for schema, motif, _ in vc.FICHIERS:
        if motif.startswith("elus_indemnites/"):
            v = vc.validateur(js, schema)
            fichiers = sorted((ROOT / "site" / "data").glob(motif))
            assert fichiers, motif
            for f in fichiers:
                assert not vc.erreurs(v, json.loads(f.read_text(encoding="utf-8"))), f


def test_total_seulement_aucun_nom_ni_montant_par_elu():
    idx = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
    assert idx["colonnes"] == ["c653"]
    assert "par élu" in idx["methode"] or "chacun" in idx["methode"]
    texte = (DOSSIER / "communes" / "44.json").read_text(encoding="utf-8")
    for interdit in ("maire", "adjoint", "nom", "prenom"):
        assert f'"{interdit}"' not in texte


def test_couverture_et_valeurs_positives():
    idx = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
    assert idx["couverture"]["communes_avec_serie"] > 34000
    d = json.loads((DOSSIER / "communes" / "44.json").read_text(encoding="utf-8"))
    serie = d["communes"]["44109"]
    assert set(serie) <= set(idx["annees"]) and all(v[0] is None or v[0] >= 0 for v in serie.values())


@pytest.mark.skipif(not list(ei.LAKE.glob("*_c653.csv")), reason="entrepôt absent")
def test_production_reproductible(tmp_path):
    ei.produire(tmp_path / "a")
    ei.produire(tmp_path / "b")
    for f in sorted((tmp_path / "a").rglob("*.json")):
        assert f.read_bytes() == (tmp_path / "b" / f.relative_to(tmp_path / "a")).read_bytes(), f
