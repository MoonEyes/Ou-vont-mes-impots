"""Coherence interne des cas types et de leurs valeurs de reference OpenFisca (sans reseau).

Les tests sur les valeurs sont ignores (skip) tant que generer_reference.py n'a pas rempli
'reference_openfisca'. Tolerance : celle du fichier (1 %).
"""
import json
from pathlib import Path

import pytest

ICI = Path(__file__).resolve().parent
ROOT = ICI.parent.parent
DOC = json.loads((ICI / "cas_types.json").read_text(encoding="utf-8"))
CAS = DOC["cas"]
TOL = DOC["tolerance_relative"]
IDS = [c["id"] for c in CAS]

# Taux legaux 2025 sur les salaires (assiette CSG/CRDS = 98,25 % du brut sous 4 PASS).
CSG_DEDUCTIBLE, CSG_NON_DEDUCTIBLE, CRDS, ABATTEMENT_CSG = 0.068, 0.024, 0.005, 0.9825


def salaries(c):
    return [p for p in c["profil"]["personnes"] if p["statut_activite"] == "salarie_prive"]


def reference(c):
    if DOC["reference"]["statut"] != "ok" or c["reference_openfisca"] is None:
        pytest.skip("valeurs OpenFisca non generees (lancer generer_reference.py)")
    return c["reference_openfisca"]


# --- Structure du jeu de cas ------------------------------------------------------------

def test_vingt_cas_identifiants_uniques():
    assert len(CAS) == 20
    assert len(set(IDS)) == 20


def test_profils_conformes_au_contrat():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "docs" / "schemas" / "profil.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    for c in CAS:
        erreurs = [e.message for e in v.iter_errors(c["profil"])]
        assert not erreurs, (c["id"], erreurs)


def test_perimetre_v1():
    for c in CAS:
        p = c["profil"]
        assert p["residence"] == {**p["residence"], "zone": "metropole", "alsace_moselle": False}, c["id"]
        assert salaries(c), c["id"]
        for pers in p["personnes"]:
            assert pers["statut_activite"] in ("salarie_prive", "sans_activite"), c["id"]
            assert not pers.get("frontalier"), c["id"]


def test_couverture_des_situations():
    situations = {c["profil"]["foyer"]["situation"] for c in CAS}
    assert {"celibataire", "parent_isole", "couple_marie_pacse"} <= situations
    assert {len(c["profil"]["foyer"]["enfants"]) for c in CAS} == {0, 1, 2, 3}
    assert {c["profil"]["logement"]["statut"] for c in CAS} >= {"locataire", "proprietaire"}
    couples = [c for c in CAS if c["profil"]["foyer"]["situation"] == "couple_marie_pacse"]
    assert {len(salaries(c)) for c in couples} == {1, 2}
    personnes = [p for c in CAS for p in salaries(c)]
    assert any(p["cadre"] for p in personnes) and any(not p["cadre"] for p in personnes)
    assert any(p["temps_travail"]["type"] == "temps_partiel" for p in personnes)
    assert any(c["attendus"]["ir_foyer"] == "nul" for c in CAS)


# --- Valeurs de reference ---------------------------------------------------------------

def test_metadonnees_de_reference():
    ref = DOC["reference"]
    if ref["statut"] != "ok":
        pytest.skip("valeurs OpenFisca non generees")
    assert ref["date"] and ref["country_package_version"] and ref["source"].endswith("/calculate")
    assert TOL == 0.01


@pytest.mark.parametrize("c", CAS, ids=IDS)
def test_net_retrouve_et_brut_superieur(c):
    ref = reference(c)
    for p in salaries(c):
        r = ref["personnes"][p["role"]]
        net_annuel = p["salaire_net_avant_impot_mensuel"] * 12
        assert r["salaire_net_avant_impot"] == pytest.approx(net_annuel, rel=TOL)
        assert r["salaire_brut"] > r["salaire_net_avant_impot"]
        assert 1.15 < r["salaire_brut"] / r["salaire_net_avant_impot"] < 1.35


@pytest.mark.parametrize("c", CAS, ids=IDS)
def test_brut_moins_prelevements_salaries_egal_net(c):
    ref = reference(c)
    for p in salaries(c):
        r = ref["personnes"][p["role"]]
        reconstruit = r["salaire_brut"] - r["cotisations_salariales"] - r["csg"] - r["crds"]
        assert reconstruit == pytest.approx(r["salaire_net_avant_impot"], rel=TOL)
        assert r["csg"] == pytest.approx(r["csg_deductible"] + r["csg_non_deductible"], abs=0.02)


@pytest.mark.parametrize("c", CAS, ids=IDS)
def test_taux_csg_crds(c):
    ref = reference(c)
    for p in salaries(c):
        r = ref["personnes"][p["role"]]
        assiette = r["salaire_brut"] * ABATTEMENT_CSG
        assert r["csg_deductible"] == pytest.approx(assiette * CSG_DEDUCTIBLE, rel=TOL)
        assert r["csg_non_deductible"] == pytest.approx(assiette * CSG_NON_DEDUCTIBLE, rel=TOL)
        assert r["crds"] == pytest.approx(assiette * CRDS, rel=TOL)


@pytest.mark.parametrize("c", CAS, ids=IDS)
def test_cotisations_positives_et_ordonnees(c):
    ref = reference(c)
    for p in salaries(c):
        r = ref["personnes"][p["role"]]
        assert r["cotisations_salariales"] > 0
        assert 0 <= r["reduction_generale"] <= r["cotisations_patronales_avant_reduction"]
        assert r["cotisations_patronales"] == pytest.approx(
            r["cotisations_patronales_avant_reduction"] - r["reduction_generale"], abs=0.02)
        assert r["cotisations_patronales"] >= 0
        # Le patronal brut (avant reduction) depasse toujours le salarial.
        assert r["cotisations_patronales_avant_reduction"] > r["cotisations_salariales"]


def test_reduction_generale_selon_niveau_de_salaire():
    """Reduction maximale au SMIC, nulle pour les cadres au-dela de 1,6 SMIC."""
    for c in CAS:
        ref = reference(c)
        for p in salaries(c):
            r = ref["personnes"][p["role"]]
            net = p["salaire_net_avant_impot_mensuel"] / p["temps_travail"].get("quotite", 1)
            if net <= 1430:
                assert r["reduction_generale"] > 0.8 * r["cotisations_patronales_avant_reduction"], c["id"]
            if net >= 3800:
                assert r["reduction_generale"] == 0, c["id"]


@pytest.mark.parametrize("c", CAS, ids=IDS)
def test_impot_attendu(c):
    ref = reference(c)
    ir = ref["foyer"]["impot_revenu"]
    assert ir >= 0
    assert ref["foyer"]["ip_net"] == pytest.approx(ir, abs=1)
    attendu = c["attendus"]["ir_foyer"]
    if attendu == "nul":
        assert ir == 0
    elif attendu == "positif":
        assert ir > 0


@pytest.mark.parametrize("c", CAS, ids=IDS)
def test_parts_fiscales(c):
    ref = reference(c)
    f = c["profil"]["foyer"]
    n = len(f["enfants"])
    parts_enfants = 0.5 * min(n, 2) + 1.0 * max(n - 2, 0)
    base = {"celibataire": 1.0, "parent_isole": 1.5, "couple_marie_pacse": 2.0}[f["situation"]]
    if f["situation"] == "parent_isole" and n == 0:
        base = 1.0
    assert ref["foyer"]["nombre_de_parts"] == [base + parts_enfants]


def test_proprietaire_ou_locataire_ne_change_pas_l_impot():
    c4, c5 = (next(c for c in CAS if c["id"] == i) for i in ("C04", "C05"))
    assert reference(c4) == reference(c5)


def test_impot_croissant_avec_le_salaire_a_situation_egale():
    celibs = sorted((c for c in CAS if c["profil"]["foyer"]["situation"] == "celibataire"
                     and c["profil"]["personnes"][0]["temps_travail"]["type"] == "temps_plein"),
                    key=lambda c: c["profil"]["personnes"][0]["salaire_net_avant_impot_mensuel"])
    irs = [reference(c)["foyer"]["impot_revenu"] for c in celibs]
    assert irs == sorted(irs) and irs[-1] > irs[0]


def test_enfants_reduisent_l_impot():
    """Meme revenu (median seul) : celibataire C04 > parent isole 2 enfants C09."""
    par_id = {c["id"]: c for c in CAS}
    assert reference(par_id["C04"])["foyer"]["impot_revenu"] > reference(par_id["C09"])["foyer"]["impot_revenu"]
    assert reference(par_id["C13"])["foyer"]["impot_revenu"] >= reference(par_id["C14"])["foyer"]["impot_revenu"]
