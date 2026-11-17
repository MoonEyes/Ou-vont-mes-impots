"""Tests sans réseau de l'axe Union européenne (site/data/ue/), produit par `python pipeline/ue.py produire`."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import ue  # noqa: E402
import valider_contrat as vc  # noqa: E402

DOSSIER = ROOT / "site" / "data" / "ue"
SCHEMAS = {"contribution.json": "ue_contribution.schema.json", "retours.json": "ue_retours.schema.json",
           "beneficiaires/index.json": "ue_beneficiaires_index.schema.json"}


def _json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contribution():
    f = DOSSIER / "contribution.json"
    assert f.exists(), "lancer `python pipeline/ue.py produire`"
    return _json(f)


@pytest.fixture(scope="module")
def retours():
    return _json(DOSSIER / "retours.json")


@pytest.fixture(scope="module")
def index():
    return _json(DOSSIER / "beneficiaires" / "index.json")


def _deps():
    return sorted(p for p in (DOSSIER / "beneficiaires").glob("*.json") if p.name != "index.json")


# --- En-tête, taille, schémas --------------------------------------------------------------------------------------


def test_millesime_source_et_taille():
    fichiers = sorted(DOSSIER.rglob("*.json"))
    assert len(fichiers) >= 99
    for f in fichiers:
        d = _json(f)
        assert d.get("millesime") and d.get("source"), f
        assert f.stat().st_size <= 1_000_000, f


def test_schemas_couverts_par_le_validateur():
    motifs = {m for _, m, _ in vc.FICHIERS}
    for m in ("ue/contribution.json", "ue/retours.json", "ue/beneficiaires/index.json", "ue/beneficiaires/[0-9n]*.json"):
        assert m in motifs, m


def test_schemas():
    js = pytest.importorskip("jsonschema")
    for rel, schema in SCHEMAS.items():
        assert not vc.erreurs(vc.validateur(js, schema), _json(DOSSIER / rel)), rel
    v = vc.validateur(js, "ue_beneficiaires_dep.schema.json")
    for f in _deps():
        assert not vc.erreurs(v, _json(f)), f


# --- Ce qui part ----------------------------------------------------------------------------------------------------


def test_psr_egal_a_la_branche_de_l_arbre(contribution):
    arbre = ue.psr_arbre()
    assert contribution["psr_ue"]["md"] == arbre["md"]
    assert contribution["psr_ue"]["noeud_arbre"] == "Prelevements sur recettes/Union européenne"
    assert abs(arbre["md"] - ue.PSR_EXECUTE[2024] / 1000) < 0.001


def test_usage_conserve_le_psr(contribution):
    psr = contribution["psr_ue"]["md"]
    rubs = contribution["usage"]["rubriques"]
    assert abs(sum(r["contribution_france_md"] for r in rubs) - psr) < 1e-4
    assert abs(sum(r["eur_sur_100"] for r in rubs) - 100) < 0.05
    for r in rubs:
        assert abs(sum(p["contribution_france_md"] for p in r["poles"]) - r["contribution_france_md"]) < 1e-4
        assert r["cfp_md"] <= r["plafond_rubrique_md"] + 0.002  # marges exclues
    pac = next(p for r in rubs for p in r["poles"] if p["code"] == "8")
    assert 30 < pac["eur_sur_100"] < 33


def test_cfp_saisi_coherent():
    for code, nom, plafond, poles in ue.CFP:
        assert sum(v for _, _, v in poles) <= plafond, code
    assert sum(p for _, _, p, _ in ue.CFP) == ue.CFP_TOTAL
    assert sum(ue.NGEU.values()) == ue.NGEU_TOTAL


def test_programmes_fts(contribution):
    pe = contribution["programmes_engagements"]
    somme = sum(p["md"] for p in pe["programmes"]) + pe["autres"]["md"]
    assert abs(somme - pe["total_md"]) < 1e-3
    assert any(p["code"] == "1.0.11" for p in pe["programmes"])  # Horizon Europe


def test_sources_inaccessibles_publiees(contribution):
    assert any("429" in s["constat"] for s in contribution["sources_inaccessibles"])


# --- Ce qui revient et solde net ----------------------------------------------------------------------------------


def test_solde_net_et_contribution(retours):
    an = {a["annee"]: a for a in retours["annees"]}
    assert set(an) >= {2021, 2022, 2023, 2024, 2025}
    for a in an.values():
        assert a["solde_net_comptable_md"] < 0  # la France est contributrice nette
        assert abs(a["retours_md"] - a["solde_net_comptable_md"] - a["contribution_comptable_md"]) < 1e-6
        assert a["source"]
    assert abs(an[2024]["contribution_comptable_md"] - 24.3) < 0.1  # recoupe la note du Sénat (PLF 2027)
    for a in an.values():
        if a["rubriques_completes"]:
            assert abs(sum(r["md"] for r in a["par_rubrique"].values()) - a["retours_md"]) < 0.003


def test_documents_verifies(retours):
    for cle, v in retours["verification_documents"].items():
        assert v["statut"] in ("vérifié",) or v["statut"].startswith("document absent"), cle


# --- Bénéficiaires nommés ----------------------------------------------------------------------------------------


def test_aucune_personne_physique_nommee():
    for f in _deps():
        for b in _json(f)["beneficiaires"]:
            assert ue.sirene.personne_morale(b["categorie_juridique"]), (f.name, b["siren"])
            assert not any("nom" in k and k != "denomination" for k in b), b.keys()


def test_conservation_par_source(index):
    for src, s in index["sources"].items():
        exclus = sum(v for k, v in s.items() if k.startswith("exclus_"))
        assert abs(s.get("nomme", 0) + exclus - s["total"]) < 1, src


def test_departements_somment_aux_sources(index):
    hors_horizon = sum(s["total"] for k, s in index["sources"].items() if k != "horizon")
    assert abs(sum(d["total_eur"] for d in index["departements"]) - hors_horizon) < 10
    assert abs(index["total_eur"] - hors_horizon) < 1
    nomme = sum(d["nomme_eur"] for d in index["departements"])
    assert abs(nomme - index["total_nomme_eur"]) < 10


def test_fichiers_departement_coherents(index):
    for d in index["departements"]:
        doc = _json(ROOT / "site" / "data" / d["fichier"])
        assert doc["departement"] == d["code"]
        hors = doc.get("beneficiaires_hors_fichier", {}).get("montant_eur", 0)
        listes = sum(b["montant_hors_horizon_eur"] for b in doc["beneficiaires"])
        nomme = sum(v["nomme_eur"] for k, v in doc["totaux"].items() if k != "horizon")
        assert listes <= nomme + 1 + hors
        for b in doc["beneficiaires"]:
            assert abs(sum(x[3] for x in b["detail"]) - b["montant_eur"]) < 1


def test_pac_jamais_nommee():
    for f in _deps():
        for b in _json(f)["beneficiaires"]:
            for src, _, prog, _, _ in b["detail"]:
                assert not (src == "fts" and prog.startswith("3.1.")), (f.name, b["siren"], prog)


def test_au_moins_un_departement_par_region(index):
    assert len({d["region"] for d in index["departements"] if d["region"]}) == 18
    assert index["beneficiaires_nommes"] > 0


# --- Règles unitaires ---------------------------------------------------------------------------------------------


def test_departement_depuis_codes():
    assert ue.dep_insee("79191") == "79"
    assert ue.dep_insee("97411") == "974"
    assert ue.dep_insee("2A004") == "2A"
    assert ue.dep_postal("20000") == "2A" and ue.dep_postal("20600") == "2B"
    assert ue.dep_postal("97200") == "972" and ue.dep_postal("75005") == "75"
    assert ue.dep_postal("1000") is None


def test_rapprochement_de_nom_strict():
    cand = lambda n: {"nom_complet": n, "nom_raison_sociale": n}  # noqa: E731
    assert ue.score_nom("Région OCCITANIE", cand("REGION OCCITANIE")) == 1.0
    assert ue.score_nom("Commune de RIMONT", cand("COMMUNE DE RIMONT")) == 1.0
    assert ue.score_nom("Ville de Thionville", cand("COMMUNE DE THIONVILLE")) == 1.0
    # faux positif évité : deux mots en commun ne suffisent pas
    assert ue.score_nom("Conseil régional PACA", cand("CONSEIL REGIONAL DES MAROCAINS DE FRANCE PACA")) < ue.SEUIL_SCORE
    assert ue.score_nom("Conseil départemental de Saône-et-Loire",
                        cand("SOCIETE DE SAINT-VINCENT-DE-PAUL - CONSEIL DEPARTEMENTAL DE SAONE-ET-LOIRE")) < ue.SEUIL_SCORE


def test_fonds_kohesio():
    assert ue.fonds_kohesio("ERDF", None) == "FEDER"
    assert ue.fonds_kohesio(None, "Youth Employment - FR - ESF/YEI") == "FSE et IEJ"
    assert ue.fonds_kohesio(None, "Réunion - ESF") == "FSE"
