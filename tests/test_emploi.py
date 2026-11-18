"""Emploi et assurance chômage (pipeline/emploi.py) : cohérence des fichiers publiés et règles du module, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "emploi"
sys.path.insert(0, str(ROOT / "pipeline"))
import emploi  # noqa: E402


# --- fonctions pures (toujours testées) ------------------------------------------------------------------------------

def test_absence_jamais_zero():
    for v in (None, "", "-", "nd", "nc", True, "texte"):
        assert emploi._nombre(v) is None and emploi._meur(v) is None
    assert emploi._nombre("17\xa0103") == 17103 and emploi._nombre("1,5") == 1.5
    assert emploi._meur("8\xa0424") == 8_424_000_000 and emploi._meur(-59205) == -59_205_000_000


def test_code_libelle_section_departement():
    assert emploi._code_libelle("IZ Hébergement et restauration") == ("IZ", "Hébergement et restauration")
    assert emploi._code_libelle("OQ :  Enseignement, santé") == ("OQ", "Enseignement, santé")
    assert emploi._code_libelle("MC autres activités") == ("MC", "Autres activités")
    assert emploi.section_naf("011") == "A" and emploi.section_naf("561") == "I" and emploi.section_naf("990") == "U"
    assert emploi.section_naf("xx") is None
    assert emploi.departement("001") == "01" and emploi.departement("02A") == "2A" and emploi.departement("971") == "971"


def test_sections_naf_couvrent_les_divisions_sans_chevauchement():
    vues = {}
    for s, a, b, _ in emploi.SECTIONS_NAF:
        for d in range(a, b + 1):
            assert d not in vues, d
            vues[d] = s
    assert vues[10] == "C" and vues[33] == "C" and vues[84] == "O"


def test_ecart_recalculable_et_nul_si_une_valeur_manque():
    e = emploi._ecart("x", 2020, "a", 110, "b", 100, "lecture")
    assert e["ecart"] == 10 and e["ecart_pct"] == 10.0
    assert emploi._ecart("x", 2020, "a", None, "b", 100, "l") is None
    assert emploi._ecart("x", 2020, "a", 5, "b", None, "l") is None


def test_controle_des_comptes():
    ok = {k: 0 for k, _ in emploi.COLONNES_FINANCEMENT}
    ok.update(recettes_total=10 * emploi.MILLION, recettes_contributions=10 * emploi.MILLION,
              depenses_total=8 * emploi.MILLION, depenses_allocations=8 * emploi.MILLION,
              solde_technique=2 * emploi.MILLION)
    assert emploi.controler_financement({2024: ok}) == []
    faux = dict(ok, depenses_allocations=4 * emploi.MILLION)
    assert emploi.controler_financement({2024: faux}) == ["2024 depenses_total"]


def test_sources_documentees():
    for cle, s in emploi.SOURCES.items():
        assert s["url"].startswith("https://") and s["page"].startswith("https://"), cle
        assert s["licence"] and s["producteur"] and s["millesime"] and s["verdict"] and s["fichier"], cle
    assert any("Dares" in i["source"] and "anti-robot" in i["motif"] for i in emploi.INACCESSIBLES)
    assert emploi.RECHERCHE_PUBLIQUE["trouvailles"]


# --- fichiers publiés --------------------------------------------------------------------------------------------------

fichiers = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                              reason="site/data/emploi absent : lancer `python pipeline/emploi.py produire`")


def charger(rel):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index():
    return charger("emploi/index.json")


@pytest.fixture(scope="module")
def unedic():
    return charger("emploi/unedic.json")


@pytest.fixture(scope="module")
def ft():
    return charger("emploi/france_travail.json")


@pytest.fixture(scope="module")
def ap():
    return charger("emploi/activite_partielle.json")


@pytest.fixture(scope="module")
def aides():
    return charger("emploi/aides_embauche.json")


@fichiers
def test_entetes_et_fichiers(index):
    for rel in index["fichiers"].values():
        doc = charger(rel)
        assert doc["millesime"] and len(doc["source"]) > 10, rel
        assert (SITE / rel).stat().st_size < 1_000_000, rel
    assert index["annees"][0] <= 2011 and index["derniere_annee"] >= 2025


@fichiers
def test_comptes_unedic_sommes_et_ordres_de_grandeur(unedic, index):
    for an, c in unedic["comptes"].items():
        assert abs(sum(c[k] for k in unedic["structure"]["recettes"] if c[k]) - c["recettes_total"]) <= 2e6, an
        assert abs(sum(c[k] for k in unedic["structure"]["depenses"] if c[k]) - c["depenses_total"]) <= 2e6, an
        assert 25e9 < c["recettes_total"] < 60e9 and 25e9 < c["depenses_total"] < 60e9, an
        assert c["dette"] < 0, an
    assert unedic["comptes"]["2011"]["recettes_csg"] is None  # absent à la source : null, jamais 0
    assert unedic["comptes"]["2020"]["depenses_activite_partielle"] == 7_454_000_000
    cc = index["chiffres_cles"]
    assert cc["unedic_dette_eur"] == unedic["comptes"][str(cc["annee"])]["dette"]
    assert 2e6 < cc["allocataires_indemnises_moyenne_mensuelle"] < 4e6


@fichiers
def test_ecarts_recalculables(index):
    assert {e["objet"] for e in index["ecarts"]} == {"allocations_unedic", "activite_partielle_unedic"}
    for e in index["ecarts"]:
        assert e["ecart"] == e["valeur"] - e["autre_valeur"]
        assert e["source"] != e["autre_source"] and e["lecture_ecart"]


@fichiers
def test_france_travail_cote_a_cote(ft):
    a = ft["annees"]
    assert a["2024"]["unedic_financement_et_frais_de_recouvrement_eur"] == 4_889_000_000
    assert a["2011"]["financement_etat_execution_cp_eur"] is None  # jaune absent : null
    assert "jamais additionnés" in ft["regle"]
    for v in a.values():
        assert not any(k.startswith("total") for k in v)
    assert {c["action"] for c in ft["credits_etat_programme_102"]} == {"01", "02"}


@fichiers
def test_activite_partielle(ap):
    dep = ap["depenses_annuelles"]
    assert dep["2020"]["etude_2022_total_eur"] == dep["2020"]["etude_2022_etat_eur"] + dep["2020"]["etude_2022_unedic_eur"]
    assert dep["2021"]["etude_2022_provisoire"] is True and dep["2007"]["etude_2022_unedic_eur"] is None
    mois = ap["consommation_mensuelle"]["mois"]
    assert mois[0]["mois"] == "2020-03" and mois[-1]["mois"] == "2021-12" and mois[-1]["provisoire"]
    an = ap["consommation_mensuelle"]["annees"]["2020"]
    assert an["heures"] == sum(m["heures"] for m in mois if m["mois"].startswith("2020"))
    # la somme mensuelle 2020 retrouve le total annuel du tableau 5 de la même étude (au million près)
    assert abs(an["montant_etat_unedic_eur"] - dep["2020"]["etude_2022_total_eur"]) < 1e6
    secteurs = ap["indemnites_par_secteur"]["secteurs"]
    assert len(secteurs) >= 30 and len({s["code"] for s in secteurs}) == len(secteurs)
    tot = ap["indemnites_par_secteur"]["totaux"]
    for a in ap["indemnites_par_secteur"]["annees_completes"]:
        assert tot[str(a)]["annee_complete"] and tot[str(a)]["trimestres"] == 4
        assert tot[str(a)]["indemnites_eur"] == sum(s["annees"][str(a)]["indemnites_eur"] for s in secteurs)
    h = {s["code"]: s for s in ap["heures_par_secteur_2020_2021"]["secteurs"]}
    assert abs(sum(s["part_heures_pct"] for c, s in h.items() if c != "ensemble" and s["part_heures_pct"]) - 100) < 0.1
    assert h["AZ"]["part_heures_pct"] is None  # hors champ du graphique : null, jamais 0
    assert [c["action"] for c in ap["credits_etat_programme_103"]] == ["03"]


@fichiers
def test_aides_embauche_secret_statistique(aides):
    j = aides["aide_embauche_jeunes"]
    assert j["total_aides_validees"] == j["total_par_departement"] > 400_000
    nd = [g for g in j["groupes"] if g["aides"] is None]
    assert nd and all(g["aides"] is None or g["aides"] >= 5 for g in j["groupes"])
    assert sum(s["groupes_secret_statistique"] for s in j["sections"]) == len(nd)
    assert sum(s["aides_connues"] for s in j["sections"]) == sum(g["aides"] for g in j["groupes"] if g["aides"])
    assert sum(s["aides_connues"] for s in j["sections"]) + j["aides_secteur_non_renseigne"] <= j["total_aides_validees"]
    assert {"2A", "2B", "75", "971"} <= {d["code"] for d in j["departements"]}
    assert not any("montant" in k for k in j)  # aucun montant estimé
    assert "apprentis" in aides["note"]


@fichiers
def test_liens_vers_les_autres_vues_existent(unedic, ft, ap):
    for doc in (unedic, ft, ap):
        for l in doc["liens"]:
            assert (SITE / l["fichier"]).exists(), l
    for doc, cle in ((ft, "credits_etat_programme_102"), (ap, "credits_etat_programme_103")):
        for c in doc[cle]:
            if c["execution_2024_lien"]:
                assert (SITE / c["execution_2024_lien"]["fichier"]).exists()
