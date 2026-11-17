"""Retraites par régime (pipeline/retraites.py) : cohérence des fichiers publiés et règles du module, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "retraites"
sys.path.insert(0, str(ROOT / "pipeline"))
import retraites  # noqa: E402


# --- fonctions pures (toujours testées) ------------------------------------------------------------------------------

def test_absence_jamais_zero():
    for v in (None, "", "nc", "s", True):
        assert retraites._nombre(v) is None and retraites._entier(v) is None and retraites._arrondi(v) is None
    assert retraites._nombre("1 234,5") == 1234.5
    assert retraites._entier(12.6) == 13 and retraites._arrondi(2341.84) == 2341.8 and retraites._arrondi(2149.0) == 2149


def test_origine_des_recettes_par_libelle():
    cas = {
        "Personnels civils : retenues pour pensions : agents propres de l'État": "cotisations_salariales",
        "Personnels civils : retenues pour pensions : validation des services auxiliaires : part agent : retenues "
        "rétroactives, versements du régime général": "cotisations_salariales",
        "Personnels militaires : contributions des employeurs : primes et indemnités": "contributions_employeurs",
        "Financement de la retraite du combattant : participation du budget général": "budget_general",
        "Cotisations salariales et patronales": "cotisations_salariales_et_patronales",
        "Contribution au Fonds spécial des pensions des ouvriers des établissements industriels de l'État (FSPOEIE)":
            "contribution_fspoeie_ratocem",
        "Compensations inter-régimes généralisée et spécifique": "transferts",
        "Recettes diverses (administration centrale) : Caisse nationale de retraite des agents des collectivités "
        "locales (CNRACL) : transfert au titre de l'article 59": "transferts",
        "Autres financements : Fonds de solidarité vieillesse (FSV), Fonds de solidarité invalidité (FSI)": "transferts",
        "Recettes diverses : récupération des indus sur pensions : personnels civils": "autres",
        "Autres recettes diverses": "autres",
    }
    for libelle, attendu in cas.items():
        assert retraites.origine_recette(libelle) == attendu, libelle
        assert attendu in retraites.ORIGINES


def test_ecart_recalculable_et_nul_si_une_valeur_manque():
    e = retraites._ecart("x", "cnracl", 2022, "effectif", "a", 110, "b", 100, "lecture de l'écart")
    assert e["ecart"] == 10 and e["ecart_pct"] == 10.0
    assert retraites._ecart("x", "cnracl", 2022, "effectif", "a", None, "b", 100, "l") is None
    assert retraites._ecart("x", "cnracl", 2022, "effectif", "a", 5, "b", None, "l") is None


def test_identifiants_de_regimes_uniques_et_types_connus():
    ids = [v[0] for v in retraites.REGIMES.values()]
    assert len(ids) == len(set(ids))
    assert {v[2] for v in retraites.REGIMES.values()} <= {"base", "complementaire", "integre", "ensemble", None}
    assert set(retraites.CPS_REGIMES) | set(retraites.SECU_ARBRE) | set(retraites.ACTIONS_REGIMES.values()) <= set(ids)


def test_sources_documentees_et_cor_non_republie():
    for cle, s in retraites.SOURCES.items():
        assert s["url"].startswith("https://") and s["page"].startswith("https://"), cle
        assert s["licence"] and s["producteur"] and s["millesime"] and s["verdict"], cle
    assert not any("cor-retraites" in s["url"] or "COR" in s["producteur"] for s in retraites.SOURCES.values())
    assert any("COR" in i["source"] for i in retraites.INACCESSIBLES)


# --- fichiers publiés --------------------------------------------------------------------------------------------------

pytestmark_fichiers = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                                         reason="site/data/retraites absent : lancer `python pipeline/retraites.py produire`")


def charger(rel):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index():
    return charger("retraites/index.json")


@pytest.fixture(scope="module")
def regimes():
    return charger("retraites/regimes.json")


@pytest.fixture(scope="module")
def etat():
    return charger("retraites/etat.json")


@pytestmark_fichiers
def test_regimes_demandes_couverts(index, regimes):
    ids = {r["id"] for r in index["regimes"]}
    assert ids == set(regimes["regimes"])
    assert {"tous_regimes", "cnav_avec_independants", "msa_salaries", "msa_non_salaries", "etat_civils",
            "etat_militaires", "cnracl", "sncf", "ratp", "cnieg", "canssm", "enim", "agirc_arrco"} <= ids
    assert index["annees"] == regimes["annees"] and index["annees"][0] <= 2004 and index["annees"][-1] >= 2024
    for rid, r in regimes["regimes"].items():
        for s in retraites.SERIES + ["source_eacr"]:
            assert set(r[s]) == {str(a) for a in regimes["annees"]}, (rid, s)


@pytestmark_fichiers
def test_null_et_jamais_zero(regimes):
    for rid, r in regimes["regimes"].items():
        for s in retraites.SERIES:
            for an, v in r[s].items():
                assert v is None or v > 0 or (v == 0 and not s.startswith("pension")), (rid, s, an, v)
        for s, ans in r.get("zeros_source", {}).items():  # un 0 de la source est publié null, avec mention
            assert s.startswith("pension") and ans
            for an in ans:
                assert r[s][str(an)] is None, (rid, s, an)
    assert "zeros_source" in regimes["regimes"]["cnavpl"]


@pytestmark_fichiers
def test_ordres_de_grandeur_tous_regimes_et_droits(regimes):
    t = regimes["regimes"]["tous_regimes"]
    assert 16_000_000 < t["retraites_droit_direct"]["2024"] < 19_000_000
    assert 1_000 < t["pension_droit_direct_eur_mois"]["2024"] < 2_500
    for rid, r in regimes["regimes"].items():
        for an in regimes["annees"]:
            d, tot = r["retraites_droit_direct"][str(an)], r["retraites_tous_droits"][str(an)]
            if d is not None and tot is not None:  # droit direct ou dérivé >= droit direct
                assert tot >= d, (rid, an)
    # aucun régime ne dépasse l'ensemble des régimes (les effectifs ne s'additionnent pas, mais restent bornés)
    for rid, r in regimes["regimes"].items():
        for an in ("2022", "2024"):
            if r["retraites_droit_direct"][an] is not None:
                assert r["retraites_droit_direct"][an] <= t["retraites_droit_direct"][an], (rid, an)


@pytestmark_fichiers
def test_cotisants_seulement_quand_publies(index, regimes):
    assert set(index["cotisants"]) == {"tous_regimes", "cnracl", "ircantec"}
    for r in index["regimes"]:
        assert r["cotisants_publies"] == (r["id"] in index["cotisants"]) == ("cotisants" in regimes["regimes"][r["id"]])
    for rid, c in index["cotisants"].items():
        valeurs = regimes["regimes"][rid]["cotisants"]["valeurs"]
        assert sorted(int(a) for a, v in valeurs.items() if v is not None) == [a for a in c["annees"]
                                                                               if str(a) in valeurs]
        assert c["source"] in index["sources"]
    c = regimes["regimes"]["cnracl"]["cotisants"]
    for an, rapport in c["rapport_cotisants_retraites_droit_direct"].items():
        if rapport is not None:
            assert abs(rapport - c["valeurs"][an] / regimes["regimes"]["cnracl"]["retraites_droit_direct"][an]) < 1e-3


@pytestmark_fichiers
def test_ecarts_publies_recalculables_et_jamais_tranches(index, regimes):
    assert index["ecarts"]
    for e in index["ecarts"]:
        assert abs(e["valeur"] - e["autre_valeur"] - e["ecart"]) <= 0.11, e
        assert abs(e["ecart_pct"] - (e["valeur"] - e["autre_valeur"]) / e["autre_valeur"] * 100) < 0.06
        assert e["lecture_ecart"] and e["regime"] in regimes["regimes"]
        for s in e["source"].split(" + ") + [e["autre_source"]]:
            assert s in index["sources"], s
    couples = {(e["regime"], e["source"]) for e in index["ecarts"]}
    assert ("etat_civils", "sre_civils") in couples and ("cnracl", "cdc_cnracl_retraites") in couples
    assert ("etat_militaires", "sre_militaires + sre_gendarmes") in couples
    # l'autre valeur est bien celle de regimes.json : aucune série n'est corrigée par une autre source
    for e in index["ecarts"]:
        if e["autre_source"] == "drees_eacr" and e["grandeur"] == "eur_mois":
            assert regimes["regimes"][e["regime"]]["pension_droit_direct_eur_mois"][str(e["annee"])] == e["autre_valeur"]


@pytestmark_fichiers
def test_msa_libelles_de_la_source_repris_sans_correction(index):
    m = index["ecarts_msa"]
    assert len(m["lignes"]) >= 5
    for l in m["lignes"]:
        assert l["colonne_salaries_agricoles"] > 0 and l["colonne_non_salaries_agricoles"] > 0
        if l["eacr_msa_salaries_tous_droits"] is not None:
            assert l["ecart_salaries"] == l["colonne_salaries_agricoles"] - l["eacr_msa_salaries_tous_droits"]
            assert l["ecart_non_salaries"] == l["colonne_non_salaries_agricoles"] - l["eacr_msa_non_salaries_tous_droits"]
    grandes = {l["annee"]: l["colonne_salaries_agricoles"] > l["colonne_non_salaries_agricoles"] for l in m["lignes"]}
    majorite = sorted(grandes.values()).count(True) >= len(grandes) / 2
    assert m["annees_colonnes_inversees"] == sorted(a for a, g in grandes.items() if g != majorite)
    for a in m["annees_colonnes_inversees"]:
        assert str(a) in m["constat"]


@pytestmark_fichiers
def test_cas_pensions_sommes_et_origines(etat):
    c = etat["cas_pensions"]
    assert [p["programme"] for p in c["programmes"]] == ["741", "742", "743"]
    for p in c["programmes"]:
        assert p["cp_eur"] == sum(a["cp_eur"] for a in p["actions"])
    assert c["depenses_cp_eur"] == sum(p["cp_eur"] for p in c["programmes"])
    assert 55e9 < c["depenses_cp_eur"] < 85e9
    for s in c["sections"]:
        assert s["recettes_eur"] == sum(l["montant_eur"] for l in s["lignes"]) == sum(s["par_origine_eur"].values())
        for o, v in s["par_origine_eur"].items():
            assert v == sum(l["montant_eur"] for l in s["lignes"] if l["origine"] == o)
        if s["depenses_cp_eur"] is not None:
            assert s["recettes_moins_depenses_eur"] == s["recettes_eur"] - s["depenses_cp_eur"]
        for l in s["lignes"]:
            assert l["origine"] == retraites.origine_recette(l["libelle"])
    assert c["recettes_eur"] == sum(s["recettes_eur"] for s in c["sections"]) == sum(c["recettes_par_origine_eur"].values())
    assert c["recettes_moins_depenses_eur"] == c["recettes_eur"] - c["depenses_cp_eur"]
    assert abs(sum(c["recettes_par_origine_pct"].values()) - 100) < 0.05
    assert set(c["recettes_par_origine_eur"]) == set(c["origines"]) == set(retraites.ORIGINES)


@pytestmark_fichiers
def test_credits_aux_regimes_speciaux_egalent_l_arbre_de_l_etat(etat):
    cr = etat["credits_regimes_speciaux"]
    assert [p["programme"] for p in cr["programmes"]] == ["195", "197", "198"]
    for p in cr["programmes"]:
        doc = charger(p["fichier"])
        assert doc["id"] == p["id"] and p["execution_2024_eur"] == round(doc["md"] * 1e9)
        for a in p["actions"]:
            if "fichier" in a:
                n = retraites._noeud(doc, a["id"])
                assert n is not None and a["execution_2024_eur"] == round(n["md"] * 1e9), a
        assert p["plf_2025_cp_eur"] == sum(a["plf_2025_cp_eur"] or 0 for a in p["actions"])
    assert cr["total_execution_2024_eur"] == sum(p["execution_2024_eur"] for p in cr["programmes"])
    regimes_lies = {a["regime"] for p in cr["programmes"] for a in p["actions"] if a["regime"]}
    assert regimes_lies == {"sncf", "ratp", "enim", "canssm"}


@pytestmark_fichiers
def test_retraites_de_l_etat_moyenne_et_effectifs(etat):
    r = etat["retraites_etat"]
    assert set(r["populations"]) == {"sre_civils", "sre_militaires", "sre_gendarmes"}
    for k, p in r["populations"].items():
        assert set(p["effectif"]) == set(p["pension_moyenne_eur_mois"]) == {str(a) for a in r["annees"]}
        for an, eff in p["effectif"].items():
            assert eff is None or (eff > 0 and 500 < p["pension_moyenne_eur_mois"][an] < 6000), (k, an)
    assert 1_400_000 < r["populations"]["sre_civils"]["effectif"]["2024"] < 1_900_000


@pytestmark_fichiers
def test_liens_existent_et_ne_recopient_pas_les_montants(index, regimes):
    vues = set()
    for r in index["regimes"]:
        for l in r["liens"]:
            vues.add(l["vue"])
            assert (SITE / l["fichier"]).exists(), l
            if l["vue"] in ("secu_cps", "secu_arbre", "arbre_etat"):
                n = retraites._noeud(charger(l["fichier"]), l["id"])
                assert n is not None and n["md"] == l["md"], l
            for autre in l.get("partage_avec", []):
                assert autre in regimes["regimes"]
    assert vues == {"secu_cps", "secu_arbre", "arbre_etat", "prestations"}
    # aucun montant de pensions (masse) dans regimes.json : seulement des effectifs et des moyennes mensuelles
    texte = (DOSSIER / "regimes.json").read_text(encoding="utf-8")
    assert "montant_eur" not in texte and "_md" not in texte
    prest = charger("prestations/nationales.json")
    assert "pensions_retraite" in prest["prestations"]


@pytestmark_fichiers
def test_entetes_tailles_et_aucune_personne_physique():
    for f in sorted(DOSSIER.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert doc["millesime"] and doc["source"], f.name
        assert f.stat().st_size < 1_000_000, f.name
        texte = f.read_text(encoding="utf-8").lower()
        for cle in ('"adresse"', '"courriel"', '"telephone"', '"dirigeant"', '"responsable"', '"prenom"', '"siren"'):
            assert cle not in texte, (f.name, cle)


@pytestmark_fichiers
def test_sources_inaccessibles_et_recherche_publique(index):
    assert len(index["sources_inaccessibles"]) >= 3
    verdicts = {t["verdict"].split(" (")[0] for t in index["recherche_publique"]["trouvailles"]}
    assert {"réutilisable tel quel", "à adapter", "inspiration seulement"} <= verdicts
    for t in index["recherche_publique"]["trouvailles"]:
        assert "licence" in t and ("dernier_commit" in t or "mise_a_jour" in t)


@pytest.mark.skipif(not (retraites.BRUT / "retraites_eacr_part1.xlsx").exists(),
                    reason="entrepôt data/lake/secu absent : reproductibilité non vérifiable ici")
def test_production_reproductible(tmp_path, monkeypatch):
    avant = {f.name: f.read_bytes() for f in sorted(DOSSIER.glob("*.json"))}
    monkeypatch.setattr(retraites, "SORTIE", tmp_path)
    retraites.produire()
    apres = {f.name: f.read_bytes() for f in sorted(tmp_path.glob("*.json"))}
    assert apres == avant
