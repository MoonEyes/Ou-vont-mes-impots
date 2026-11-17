"""Dette publique (pipeline/dette.py) : cohérence des fichiers publiés dans site/data/dette, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DETTE = SITE / "dette"
sys.path.insert(0, str(ROOT / "pipeline"))
import dette  # noqa: E402

if not (DETTE / "index.json").exists():
    pytest.skip("site/data/dette absent : lancer `python pipeline/dette.py produire`", allow_module_level=True)


def lire(nom):
    return json.loads((DETTE / nom).read_text(encoding="utf-8"))


INDEX, ENC, ITR, DET, FIN = (lire(f"{n}.json") for n in ("index", "encours", "interets", "detenteurs", "financement"))


def test_entetes_millesime_source_partout():
    for doc in (INDEX, ENC, ITR, DET, FIN):
        assert doc["millesime"] and doc["source"] and doc["unite"].startswith("milliards d'euros")
    for nom in INDEX["fichiers"].values():
        assert (SITE / nom).exists(), nom


def test_sous_secteurs_insee_somment_a_l_ensemble():
    ins = ENC["insee"]
    for a, total in ins["Ensemble"]["md"].items():
        somme = sum(ins[k]["md"][a] for k in ("Etat", "ODAC", "APUL", "ASSO"))
        assert abs(somme - total) <= 0.3, a  # arrondis a 0,1 Md EUR de la source


def test_series_couvrent_2000_a_la_derniere_annee():
    der = ENC["derniere_annee"]
    assert int(der) >= 2025
    for code in ("Etat", "ODAC", "APUL", "ASSO", "Ensemble"):
        assert set(map(str, range(2000, int(der) + 1))) <= set(ENC["insee"][code]["md"]), code
    for s in ("S13", "S1311", "S1313", "S1314"):
        assert "2000" in ENC["bce"]["secteurs"][s]["md"] and der in ENC["bce"]["secteurs"][s]["md"]
        assert "2000" in ITR["nationale"]["eurostat"]["secteurs"][s]["md"]


def test_pourcentage_du_pib_calcule_retombe_sur_le_publie():
    publie = ENC["insee"]["Ensemble"]["pct_pib_publie"]
    calc = ENC["insee"]["Ensemble"]["pct_pib"]
    for a in publie:
        if a in calc:
            assert abs(publie[a] - calc[a]) <= 0.6, a  # PIB Eurostat contre PIB Insee du trimestre


def test_ecarts_publies_pas_lisses():
    # l'ecart de definition Insee / Eurostat sur l'administration centrale doit rester visible
    assert any("Administration centrale" in e["agregat"] for e in ENC["ecarts"])
    assert all("explication" in e for e in ENC["ecarts"])
    assert ITR["budgetaire"]["ecarts"] and ITR["nationale"]["ecarts"]


def test_programme_117_trous_explicites_et_jamais_additionne():
    annees = ITR["budgetaire"]["annees"]
    assert set(annees) == {str(a) for a in range(2000, 2027)}
    for a, v in annees.items():
        assert (v["md"] is None) == (v["statut"] == "trou"), a
        if v["md"] is None:
            assert v["motif"]
    r117 = json.loads((SITE / "realisations" / "117.json").read_text(encoding="utf-8"))
    for x in r117["prevu_depense"]["annees"]:
        if x.get("depense_constatee_eur") is not None:
            assert abs(annees[str(x["annee"])]["md"] - x["depense_constatee_eur"] / 1e9) < 1e-3
    assert "jamais additionnées" in ITR["avertissement"]


def test_cas_c04_coherent_avec_openfisca_et_arithmetique():
    cas = json.loads((ROOT / "tests" / "cas_types" / "cas_types.json").read_text(encoding="utf-8"))
    ref = next(c for c in cas["cas"] if c["id"] == "C04")["reference_openfisca"]
    p = ref["personnes"]["declarant1"]
    social = p["cotisations_salariales"] + p["csg"] + p["crds"]
    assert abs(dette.C04["salaire_seul_eur"]["Securite sociale"] - social) < 1.0
    assert dette.C04["salaire_seul_eur"]["Etat"] == ref["foyer"]["impot_revenu"]
    c = ITR["cas_type"]
    lignes = c["par_administration"]
    assert abs(sum(l["montant_annuel_eur"] for l in lignes.values()) - c["total_annuel_eur"]) < 0.05
    assert abs(sum(l["sur_100_eur"] for l in lignes.values()) - 100) < 0.05
    for adm, l in lignes.items():
        ratio = ITR["nationale"]["eurostat"]["secteurs"][l["secteur"]]["part_depenses"][c["annee_ratios"]]
        assert l["part_interets_dans_depenses"] == ratio
        assert abs(l["interets_annuel_eur"] - l["montant_annuel_eur"] * ratio) < 0.05
    assert abs(c["interets_sur_100_eur"] - c["interets_annuel_eur"] / c["total_annuel_eur"] * 100) < 0.01
    assert 0 < c["interets_sur_100_eur"] < 10


def test_detenteurs_somment_au_total():
    der = DET["derniere_annee"]
    somme = sum(v["md"][der] for v in DET["eurostat"].values())
    assert abs(somme - DET["total_md"][der]) <= 0.5
    parts = sum(v["part"][der] for v in DET["eurostat"].values())
    assert abs(parts - 1) < 0.002
    for a, tot in DET["bce"]["total_md"].items():
        s = sum(DET["bce"]["detenteurs_md"][k].get(a, 0) for k in DET["bce"]["detenteurs_md"])
        assert abs(s - tot) <= 1.0, a


def test_financement_indexees_et_programme():
    neg = FIN["dette_negociable_etat"]
    for a, v in neg["indexee_inflation_md"].items():
        assert 0 <= v <= neg["total_md"][a]
    prog = FIN["programme_financement_etat"]["annees"]
    assert prog["2026"]["emissions_nettes_rachats_md"] == 310.0
    v = prog["2024"]
    assert abs(v["dont_valeur_nominale_md"] + v["dont_supplements_indexation_md"] - v["amortissements_md"]) < 0.05


def test_dette_sociale_relie_secu_sans_dupliquer():
    soc = INDEX["dette_sociale"]
    for lien in soc["liens_secu"]:
        racine = json.loads((SITE / lien["fichier"]).read_text(encoding="utf-8"))
        assert any(e["id"] == lien["noeud"] for e in racine["enfants"]), lien
    cades = soc["cades"]
    assert abs(cades["situation_nette_md"]["2025"] - (-138.1 + cades["dette_amortie_md"]["2025"])) < 0.05
    assert not (DETTE / "cades.json").exists()  # la CADES reste decrite dans secu/, ici seulement reliee


def test_sources_inaccessibles_et_recherche_publique():
    assert any("France Tr" in s["source"] for s in INDEX["sources_inaccessibles"])
    verdicts = {t["verdict"] for t in INDEX["recherche_publique"]["trouvailles"]}
    assert verdicts <= {"réutilisable tel quel", "à adapter", "inspiration seulement"}
    assert all(v["statut"] == "vérifié" for v in INDEX["verification_documents"].values())


def test_neutralite_pas_de_qualificatif():
    texte = json.dumps([INDEX, ENC, ITR, DET, FIN], ensure_ascii=False).lower()
    for mot in ("alarmant", "catastroph", "insoutenable", "explos", "scandale", "faillite"):
        assert mot not in texte, mot
