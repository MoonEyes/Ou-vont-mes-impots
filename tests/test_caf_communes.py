"""Prestations de la CAF par commune (pipeline/caf_communes.py) : secret statistique respecté, arrondissements jamais
additionnés, noms de quartier filtrés. Sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "caf_communes"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import caf_communes as cc  # noqa: E402
import valider_contrat as vc  # noqa: E402


def test_arrondissements_ramenes_a_leur_commune():
    assert cc.commune_mere("75112") == "75056" and cc.commune_mere("69381") == "69123" and cc.commune_mere("13216") == "13055"
    assert cc.commune_mere("75056") is None and cc.commune_mere("44109") is None


def test_valeur_non_diffusee_reste_nulle():
    assert cc.entier(None) is None and cc.entier(float("nan")) is None and cc.entier(5.0) == 5


def test_fichiers_conformes_au_schema():
    js = vc.charger_jsonschema()
    for schema, motif, _ in vc.FICHIERS:
        if motif.startswith("caf_communes/"):
            v = vc.validateur(js, schema)
            fichiers = sorted((ROOT / "site" / "data").glob(motif))
            assert fichiers, motif
            for f in fichiers:
                assert not vc.erreurs(v, json.loads(f.read_text(encoding="utf-8"))), f


def test_index_ecrit_le_secret_et_le_montant_de_decembre():
    idx = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
    assert "arrondis à 5" in idx["secret_statistique"] and "décembre" in idx["montant"]
    assert "intercommunalité" in idx["aah"]
    assert idx["couverture"]["communes_publiees"] > 34000


def test_effectifs_arrondis_a_cinq():
    d = json.loads((DOSSIER / "communes" / "44.json").read_text(encoding="utf-8"))
    i = d["colonnes"].index("rsa_foyers")
    for c in d["communes"].values():
        for v in c["annees"].values():
            assert v[i] is None or v[i] % 5 == 0


def test_paris_par_arrondissement_sans_total_calcule():
    d = json.loads((DOSSIER / "communes" / "75.json").read_text(encoding="utf-8"))
    paris = d["communes"]["75056"]
    assert len(paris["arrondissements"]) == 20 and paris["annees"] == {}


@pytest.mark.skipif(not (cc.LAKE / "com.parquet").exists(), reason="entrepôt absent")
def test_production_reproductible(tmp_path):
    cc.produire(tmp_path / "a")
    cc.produire(tmp_path / "b")
    for f in sorted((tmp_path / "a").rglob("*.json")):
        assert f.read_bytes() == (tmp_path / "b" / f.relative_to(tmp_path / "a")).read_bytes(), f
