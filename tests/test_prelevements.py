"""Tests sans réseau des prélèvements hors bulletin et de leur affectation (site/data/prelevements/).

Ils lisent les fichiers produits par `python pipeline/prelevements.py produire` et testent les règles du module.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import prelevements as P  # noqa: E402

DOSSIER = ROOT / "site" / "data" / "prelevements"
ADMINISTRATIONS = {"Etat", "Collectivites locales", "Securite sociale"}


def _json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def affectation():
    f = DOSSIER / "affectation.json"
    assert f.exists(), "lancer `python pipeline/prelevements.py produire`"
    return _json(f)


@pytest.fixture(scope="module")
def tva():
    return _json(DOSSIER / "tva_conso.json")


@pytest.fixture(scope="module")
def recettes():
    return _json(ROOT / "site" / "data" / "recettes.json")


# --- Métadonnées ----------------------------------------------------------------------------------------------------


def test_millesime_et_source_partout():
    fichiers = sorted(DOSSIER.rglob("*.json"))
    assert len(fichiers) >= 4
    for f in fichiers:
        d = _json(f)
        assert d.get("millesime") and d.get("source"), f
        assert f.stat().st_size < 5_000_000, f
    for nom in ("affectation.json", "tva_conso.json", "taxe_fonciere.json"):
        assert _json(DOSSIER / nom).get("methode"), nom


def test_chaque_part_a_une_source(affectation):
    for pid, p in affectation["prelevements"].items():
        if p["statut"] == "non sourcee":
            continue
        assert p["ventilation"], pid
        for v in p["ventilation"]:
            assert v["source"].strip(), (pid, v)
            assert v["destinataire"] in affectation["destinataires"], (pid, v)


# --- Affectation ----------------------------------------------------------------------------------------------------


def test_parts_somment_a_100_pour_cent(affectation):
    for pid, p in affectation["prelevements"].items():
        if p["statut"] == "non sourcee":
            continue
        s = sum(v["part"] for v in p["ventilation"])
        assert abs(s - 1) < 1e-4, (pid, s)
        assert all(0 < v["part"] <= 1 for v in p["ventilation"]), pid


def test_prelevements_demandes_presents(affectation):
    attendus = {"vieillesse_plafonnee", "vieillesse_deplafonnee", "maladie", "famille", "atmp", "agirc_arrco", "ceg",
                "chomage", "fnal", "csa", "csg_activite", "crds", "impot_revenu", "tva", "ticpe", "taxe_fonciere"}
    assert attendus <= set(affectation["prelevements"])
    for cible in affectation["correspondance_calcul"].values():
        assert cible in affectation["prelevements"], cible


def test_csg_2025(affectation):
    csg = affectation["prelevements"]["csg_activite"]
    assert csg["points"] == {"cnam": 4.25, "cnsa": 2.08, "unedic": 1.47, "cnaf": 0.95, "cades": 0.45}
    assert abs(sum(csg["points"].values()) - 9.2) < 1e-9
    parts = {v["destinataire"]: v["part"] for v in csg["ventilation"]}
    assert parts["cnam"] == pytest.approx(4.25 / 9.2, abs=1e-6)
    assert parts["cades"] == pytest.approx(0.45 / 9.2, abs=1e-6)


def test_destinataires_rattaches_a_une_administration(affectation):
    for k, d in affectation["destinataires"].items():
        assert d["administration"] in ADMINISTRATIONS, k


def test_documents_verifies_ou_signales(affectation):
    for cle, v in affectation["verification_documents"].items():
        assert v["statut"] in ("vérifié", "document absent de l'entrepôt : valeurs saisies non revérifiées"), cle


def test_tva_secu_coherente_avec_les_fractions_legales():
    p = P.affectation_parametres(None)["tva"]
    m = {v["destinataire"]: v.get("montant_md", 0) for v in p["ventilation"]}
    # 23,24 % de la TVA nette totale à la CNAM, 5,18 % moins 3,35 Md€ à l'ACOSS (PLFSS 2026 annexe 3)
    assert m["cnam"] + m["acoss"] == pytest.approx(56.4, abs=0.05)
    assert m["cnam"] == pytest.approx(0.2324 * 210.0, rel=0.01)


# --- TVA et taxes sur la consommation -------------------------------------------------------------------------------


def test_tranches_ordonnees_et_fourchettes(tva):
    tr = tva["tranches"]
    assert [t["decile"] for t in tr] == list(range(1, 11))
    bornes = tva["deciles_niveau_de_vie"]["bornes_eur_par_an"]
    assert bornes == sorted(bornes) and len(bornes) == 9
    prec = 0
    for t in tr:
        m = t["taxes_produits_eur_par_uc"]
        assert 0 < m["bas"] <= m["central"] <= m["haut"], t["decile"]
        assert m["central"] > prec, "les montants par UC doivent croître avec le niveau de vie"
        prec = m["central"]
        somme = sum(v["central"] for v in t["detail_eur_par_uc"].values())
        assert somme == pytest.approx(m["central"], abs=1.0), t["decile"]
        for v in t["detail_eur_par_uc"].values():
            assert v["bas"] <= v["central"] <= v["haut"]


def test_effort_regressif(tva):
    taux = [t["taux_effort_pct_revenu_disponible_2019"] for t in tva["tranches"]]
    assert taux[0] > taux[4] > taux[9]


def test_ordre_de_grandeur_tva_nationale(tva, recettes):
    tva_reelle = recettes["impots"]["D211"]["par_administration"]["Ensemble"][P.ANNEE]
    assert tva["totaux_nationaux_2025_md"]["tva"]["md"] == tva_reelle
    e = tva["ecarts_au_total_national"]["tva"]
    assert e["reel_md"] == tva_reelle
    assert abs(e["ecart_pct"]) < 20, e
    assert e["estime_md"] == pytest.approx(tva_reelle, rel=0.2)
    total = tva["ecarts_au_total_national"]["total_taxes_produits"]
    assert abs(total["ecart_pct"]) < 20, total


def test_totaux_nationaux_sources(tva):
    for k, v in tva["totaux_nationaux_2025_md"].items():
        assert v["md"] > 0 and v["source"], k


def test_ajustements(tva):
    for t in tva["tranches"]:
        a = t["ajustements"]
        assert a["fumeur"]["tabac_non_fumeur_eur_par_uc"] == 0
        assert a["fumeur"]["tabac_fumeur_eur_par_uc"] is None  # non sourcé : jamais inventé
        v = a["voiture"]
        assert v["ticpe_sans_voiture_eur_par_uc"] == 0
        assert v["ticpe_si_voiture_eur_par_uc"] >= t["detail_eur_par_uc"]["ticpe"]["central"]


def test_tva_theorique_taux_couvrent_tous_les_postes():
    conso = P.lire_tf(P.SOURCES["insee_bdf_tf106"]["fichier"], "CONSO") if (
        P.BRUT / P.SOURCES["insee_bdf_tf106"]["fichier"]).exists() else None
    if conso is None:
        pytest.skip("entrepôt brut absent")
    for dec in ("1", "10"):
        t = P.tva_theorique(conso, dec)
        total = conso[("CTOTALE", dec)]
        assert 0.05 * total < t < 0.2 * total


# --- Taxe foncière --------------------------------------------------------------------------------------------------


def test_taxe_fonciere_communes():
    meta = _json(DOSSIER / "taxe_fonciere.json")
    communes_site = {p.stem for p in (ROOT / "site" / "data" / "communes").glob("*.json")}
    assert set(meta["departements"]) <= communes_site
    lyon = _json(DOSSIER / "taxe_fonciere" / "69.json")["communes"]["69123"]
    bas, central, haut = lyon[:3]
    assert 0 < bas <= central <= haut
    assert 200 < central < 3000
    for dep in meta["departements"]:
        for insee, v in _json(DOSSIER / "taxe_fonciere" / f"{dep}.json")["communes"].items():
            if v is None:
                continue
            assert v[0] <= v[1] <= v[2], insee
            if v[3] is not None:
                assert v[3] <= v[4] <= v[5], insee
            assert abs(sum(v[6:]) - 1) < 0.002, insee


def test_taxe_fonciere_parts_nationales(affectation):
    tf = affectation["prelevements"]["taxe_fonciere"]
    parts = {v["destinataire"]: v["part"] for v in tf["ventilation"]}
    assert parts["commune"] > 0.8  # la part départementale a été transférée aux communes en 2021
    assert "departement" not in parts
