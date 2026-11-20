"""Compléments OFGL (pipeline/ofgl_complements.py) : fonctions, puis fichiers publiés (schéma, confidentialité,
absence jamais remplacée par 0, reproductibilité si l'entrepôt est présent). Sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "ofgl_complements"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import ofgl_complements as oc  # noqa: E402
import sirene  # noqa: E402
import valider_contrat as vc  # noqa: E402


def test_valeurs_absentes_jamais_zero():
    assert oc.euros(None) is None and oc.euros(float("nan")) is None and oc.euros("x") is None
    assert oc.euros(0) == 0 and oc.euros(12.6) == 13
    assert oc.nombre(None) is None and oc.nombre(35.7234) == 35.72 and oc.nombre(18.0) == 18


def test_patrimoine_euros_arrondis_ratios_a_deux_decimales():
    assert oc.valeur_patrimoine("Actif brut", 30448426.47) == 30448426
    assert oc.valeur_patrimoine("Taux de vétusté", 35.7234) == 35.72


def test_dix_huit_libelles_de_flux_intercommunaux():
    libs = oc._flux_epci_libelles()
    assert len(libs) == 2 * len(oc.FLUX_EPCI) == 18 and len(set(libs)) == 18
    assert "Subventions équipement versées - dépenses" in libs


def test_fichiers_conformes_au_schema():
    js = vc.charger_jsonschema()
    for schema, motif, _ in vc.FICHIERS:
        if motif.startswith("ofgl_complements/"):
            v = vc.validateur(js, schema)
            fichiers = sorted((ROOT / "site" / "data").glob(motif))
            assert fichiers, motif
            for f in fichiers:
                assert not vc.erreurs(v, json.loads(f.read_text(encoding="utf-8"))), f


def test_index_licences_et_couverture():
    idx = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
    for s in idx["sources"]:
        assert s["licence"]
        assert s["licence_note"] is None or "dotations-communes" in s["licence_note"]
    c = idx["couverture"]
    assert c["communes_flux"] > 30000 and c["communes_patrimoine"] > 30000 and c["sdis"] >= 90
    assert c["organismes_nommes"] + c["organismes_sans_nom"] == c["organismes"]


def test_un_fichier_par_departement_et_taille():
    fichiers = sorted((DOSSIER / "communes").glob("*.json"))
    assert len(fichiers) == len(list((ROOT / "site" / "data" / "local" / "geo").glob("*.json")))
    assert all(f.stat().st_size < oc.MAX_OCTETS for f in fichiers)


def test_organismes_nommes_seulement_personnes_morales():
    cj = {}
    p = oc.LAKE / "epl_categories.json"
    if p.exists():
        cj = json.loads(p.read_text(encoding="utf-8"))
    for f in sorted((DOSSIER / "communes").glob("*.json")):
        for siren, nom, *_ in json.loads(f.read_text(encoding="utf-8"))["organismes"]:
            assert (siren is None) == (nom is None), f
            if siren and cj:
                assert sirene.personne_morale(cj.get(siren)), siren


def test_grandchamp_et_erdre_et_gesvres():
    d = json.loads((DOSSIER / "communes" / "44.json").read_text(encoding="utf-8"))
    assert len(d["communes"]["44066"]["flux"]) == len(oc.FLUX_COM)
    e = d["epci"]["244400503"]
    assert "Erdre" in e["nom"] and e["fpic"]
    assert d["sdis"]["annees"]


@pytest.mark.skipif(not (oc.LAKE / "fpic.parquet").exists(), reason="entrepôt absent")
def test_production_reproductible(tmp_path):
    oc.produire(tmp_path / "a")
    oc.produire(tmp_path / "b")
    for f in sorted((tmp_path / "a").rglob("*.json")):
        assert f.read_bytes() == (tmp_path / "b" / f.relative_to(tmp_path / "a")).read_bytes(), f
