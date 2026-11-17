"""Justice et défense (pipeline/justice_defense.py) : contrat, neutralité, confidentialité, cohérence des totaux.

Les tests sur site/data/justice_defense tournent sans réseau ni entrepôt ; la reproductibilité demande l'entrepôt
(data/lake/justice_defense/), sautée sinon.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "justice_defense"
LAKE = ROOT / "data" / "lake" / "justice_defense"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "pipeline"))
from test_neutralite import fautes, textes  # noqa: E402

import justice_defense as jd  # noqa: E402

FICHIERS = ["index.json", "prisons.json", "budget_justice.json", "ressorts.json", "armement.json"]
# Jugements propres au sujet, en plus du lexique partagé.
JUGEMENTS = re.compile(r"(?<!\w)(?:surpeupl\w*|surpopulation|laxis\w*|scandal\w*|indigne\w*|marchands? de mort|"
                       r"trop|insuffisan\w*|excessi\w*|dictatur\w*|régimes?)(?!\w)", re.I)


def _lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prisons():
    return _lire("prisons.json")


@pytest.fixture(scope="module")
def armement():
    return _lire("armement.json")


# ---------------------------------------------------------------------------------------------------- unitaires

def test_nombre_jamais_zero_pour_une_absence():
    assert jd.nombre("1 187") == 1187 and jd.nombre("202,6 %") == 202.6 and jd.nombre(2138.0) == 2138
    assert jd.nombre("0,0") == 0.0
    for absent in (None, "", "-", "nd", "nc", "Non déterminé", True):
        assert jd.nombre(absent) is None


def test_date_de_situation():
    assert jd._date_dans(["Effectifs actualisés au 1er septembre 2026"]) == "2026-09-01"
    assert jd._date_dans(["Effectif au :", "1er janvier 2019 "]) == "2019-01-01"
    assert jd._date_dans(["1er août 2015", "x"]) == "2015-08-01" and jd._date_dans(["sans date"]) is None


def test_departement_et_cle():
    assert jd._departement("97103") == "971" and jd._departement("2B042") == "2B" and jd._departement("44109") == "44"
    assert jd._cle_nom("St-Martin-de-Ré") == "SAINT MARTIN DE RE"


# ---------------------------------------------------------------------------------------------------- en-têtes

@pytest.mark.parametrize("nom", FICHIERS)
def test_entete_taille_et_neutralite(nom):
    f = DATA / nom
    assert f.stat().st_size < 5_000_000
    d = _lire(nom)
    assert d["millesime"] and d["source"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["date_sources"])
    assert "https://" in d["source"]
    for cle, t in textes(d):
        assert not fautes(t), f"{nom} [{cle}] {fautes(t)} : {t[:100]}"
        assert not JUGEMENTS.search(t), f"{nom} [{cle}] jugement : {t[:100]}"
        assert "—" not in t


@pytest.mark.parametrize("nom", FICHIERS)
def test_aucune_donnee_personnelle(nom):
    interdites = {"adresse", "voie", "code_postal", "telephone", "courriel", "email", "nom_prenom", "prenom", "dirigeant",
                  "responsable", "coordonnees", "latitude", "longitude", "x", "y"}

    def cles(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from cles(v)
        elif isinstance(x, list):
            for v in x:
                yield from cles(v)
    brut = (DATA / nom).read_text(encoding="utf-8")
    assert not interdites & set(cles(json.loads(brut)))
    assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", brut) and not re.search(r"\b0\d(?:[ .]?\d\d){4}\b", brut)
    assert not re.search(r"\b(?:M\.|Mme|Monsieur|Madame)\s+[A-Z]", brut)


# ---------------------------------------------------------------------------------------------------- prisons

def test_prisons_lignes_et_total_national(prisons):
    e = prisons["etablissements"]
    assert len(e) >= 200 and prisons["controles"]["lignes"] == len(e)
    assert sum(x["detenus"] or 0 for x in e) == prisons["controles"]["somme_detenus_lignes"]
    nat = prisons["national"]
    assert abs(prisons["controles"]["somme_detenus_lignes"] - nat["detenus"]) <= 0.02 * nat["detenus"]
    assert nat["date"] == prisons["date_reference"] == prisons["serie_nationale"][-1]["date"]
    cles = [(jd._cle_nom(x["disp"]), jd._cle_nom(x["etablissement"]), x["quartier"]) for x in e]
    assert cles == sorted(cles) and len(set(cles)) == len(cles)
    assert all(not ({"commune", "departement"} & set(x)) for x in e)  # aucun rattachement non publié


def test_prisons_densite_egale_detenus_sur_places(prisons):
    for s in prisons["serie_nationale"]:
        assert abs(round(100 * s["detenus"] / s["capacite_operationnelle"], 1) - s["densite_pct"]) <= 0.15, s["date"]
    for x in prisons["etablissements"]:
        if x["densite_pct"] is not None and x["capacite_operationnelle"]:
            assert abs(100 * x["detenus"] / x["capacite_operationnelle"] - x["densite_pct"]) <= 0.15, x


def test_prisons_serie_mensuelle_et_mois_absents_publies(prisons):
    dates = [s["date"] for s in prisons["serie_nationale"]]
    assert dates == sorted(set(dates)) and len(dates) >= 90
    c = prisons["couverture"]
    assert c["classeurs_lus"] == len(dates) and not set(c["mois_absents"]) & set(dates)
    a0, a1 = int(dates[0][:4]), int(dates[-1][:4])
    attendus = (a1 - a0) * 12 + int(dates[-1][5:7]) - int(dates[0][5:7]) + 1
    assert len(dates) + len(c["mois_absents"]) == attendus
    assert all(f["url"] is None or f["url"].startswith("https://static.data.gouv.fr/") for f in c["fichiers"])


def test_montant_par_etablissement_marque_calcule_avec_formule(prisons):
    m = prisons["montant_calcule"]
    assert m["statut"] == "calculé" and m["indicateur_publie"] is None and "realisations/107.json" in m["source_depense"]
    assert "dépense constatée du programme 107" in m["formule"] and len(m["limites"]) >= 3
    r107 = json.loads((ROOT / "site" / "data" / "realisations" / "107.json").read_text(encoding="utf-8"))
    dep = next(a["depense_constatee_eur"] for a in r107["prevu_depense"]["annees"] if int(a["annee"]) == m["annee"])
    assert m["depense_programme_107_eur"] == dep
    assert abs(m["montant_par_journee_eur"] - dep / (m["detenus_moyens"] * m["jours"])) < 0.02
    somme = prisons["controles"]["somme_montants_calcules_eur"]
    assert somme == sum(x["montant_calcule_eur"] or 0 for x in prisons["etablissements"])
    assert 0.95 * dep <= somme <= 1.001 * dep  # la répartition ne dépasse jamais la dépense
    assert "calculé" in prisons["avertissement"]


def test_aucun_indicateur_de_journee_de_detention_publie():
    """Si l'administration publie un jour l'indicateur dans realisations/107.json, le calcul du site doit être revu."""
    assert jd._depense_107()["indicateur_journee"] == []


# ---------------------------------------------------------------------------------------------------- budget

def test_budget_programmes_egaux_aux_credits_de_paiement():
    b = _lire("budget_justice.json")
    progs = b["budget"]["programmes"]
    assert [p["programme"] for p in progs] == ["166", "107", "182", "101", "310", "335"]
    assert abs(sum(p["cp_meur"] for p in progs) - b["budget"]["credits_paiement"][-1]["meur"]) <= 0.35
    f = b["frais_de_justice"]
    for k in range(3):
        assert abs(f["civile_et_commerciale"][k]["meur"] + f["criminelle_correctionnelle_contraventionnelle"][k]["meur"]
                   - f["total"][k]["meur"]) <= 0.2
    v = b["aide_juridictionnelle"]["verse_aux_avocats"]
    assert abs(v["civil_meur"] + v["penal_meur"] + v["administratif_meur"] - v["aide_juridictionnelle_meur"]) <= 0.25
    for p in progs:  # libellés identiques à ceux déjà publiés par programme
        r = json.loads((ROOT / "site" / "data" / "realisations" / f"{p['programme']}.json").read_text(encoding="utf-8"))
        assert jd._norm(r["libelle"]) == jd._norm(p["libelle"])
    assert all({"source", "montant", "autre_source", "autre_montant", "ecart"} <= set(e) for e in b["ecarts"])


# ---------------------------------------------------------------------------------------------------- ressorts

def test_ressorts_colonnes_reprises_seulement_si_coherentes():
    r = _lire("ressorts.json")
    coh = r["coherence_source"]
    assert r["colonnes"][0] == "insee" and all(len(c) == len(r["colonnes"]) for c in r["communes"])
    for col, cle in (("tribunal_judiciaire", "tribunal_judiciaire"), ("tribunal_proximite", "tribunal_proximite"),
                     ("conseil_prudhommes", "conseil_prudhommes")):
        part = coh["colonnes"][cle]["part_autre_departement_pct"]
        assert (col in r["colonnes"]) == (part <= 100 * jd.SEUIL_INCOHERENCE), col
    if "tribunal_judiciaire" not in r["colonnes"]:
        assert coh["colonnes_non_reprises"] == ["cour_appel", "tribunal_judiciaire"] and coh["constat"]
        assert "cours_appel" not in r and "tribunaux_judiciaires" not in r and "cour_appel" not in r["colonnes"]
    insee = [c[0] for c in r["communes"]]
    assert insee == sorted(set(insee)) and len(insee) == r["controles"]["communes"] > 30000
    for nom, table in (("tribunal_proximite", "tribunaux_proximite"), ("conseil_prudhommes", "conseils_prudhommes")):
        i = r["colonnes"].index(nom)
        assert {str(c[i]) for c in r["communes"] if c[i] is not None} <= set(r[table])


def test_juridictions_rattachees_a_une_commune_et_un_departement():
    r = _lire("ressorts.json")
    j = r["juridictions"]
    assert len(j) == r["controles"]["juridictions"] == sum(t["nombre"] for t in r["types"]) > 1000
    assert all(x["commune_insee"] is None or x["departement"] == jd._departement(x["commune_insee"]) for x in j)
    assert sum(sum(v.values()) for v in r["par_departement"].values()) == len(j)
    assert set(j[0]) == {"type", "numero", "nom", "commune_insee", "departement"}


# ---------------------------------------------------------------------------------------------------- armement

@pytest.mark.parametrize("cle,entier", [("prises_de_commandes", False), ("livraisons", False), ("licences", True)])
def test_armement_regions_et_total_general(armement, cle, entier):
    t = armement[cle]
    assert t["annees"] == list(range(2015, 2025)) and len(t["pays"]) > 100
    tol = 0 if entier else 0.06
    for k in range(10):
        s = sum(r["valeurs"][k] or 0 for r in t["regions"]) + sum(h["valeurs"][k] or 0 for h in t["hors_region"])
        assert abs(s - t["total_general"]["valeurs"][k]) <= tol * (len(t["regions"]) + len(t["hors_region"])) + 1e-9
    for p in t["pays"]:
        assert p["region"] in {r["region"] for r in t["regions"]}
        assert abs(sum(v or 0 for v in p["valeurs"]) - (p["total"] or 0)) <= tol * 10 + 1e-9 \
            or p["pays"] in t["controles"]["pays_dont_le_total_differe_de_la_somme"]
    assert sum(r["pays"] for r in t["regions"]) == len(t["pays"]) == t["controles"]["lignes_pays"]
    assert any(v is None for p in t["pays"] for v in p["valeurs"])  # tiret publié : null, jamais 0
    for e in t["controles"]["ecarts_regions"]:  # écart publié, jamais corrigé
        assert {"source", "montant", "autre_source", "autre_montant", "ecart"} <= set(e)


def test_armement_licences_par_categorie(armement):
    c = armement["licences_par_categorie"]
    noms = [x["categorie"] for x in c["categories"]]
    assert noms[:22] == [f"ML{i}" for i in range(1, 23)] and set(noms[22:]) <= {"AMA1", "AMA2", "AMA3", "AMA4"}
    assert sum(x["licences"] or 0 for x in c["categories"]) == c["total"]["licences"]
    assert sum(x["montant_eur"] or 0 for x in c["categories"]) == c["total"]["montant_eur"]
    # même total que la colonne de l'année dans l'annexe 6 (nombre de licences acceptées)
    k = armement["licences"]["annees"].index(c["annee"])
    assert armement["licences"]["total_general"]["valeurs"][k] == c["total"]["licences"]
    assert "ne s'additionnent pas" in armement["avertissement"]


# ---------------------------------------------------------------------------------------------------- index

def test_index_fichiers_sources_et_recherche():
    i = _lire("index.json")
    for f in i["fichiers"]:
        assert (ROOT / "site" / "data" / f["fichier"]).stat().st_size == f["octets"]
    assert {s["id_catalogue"] for s in i["sources"]} == {s["id_catalogue"] for s in jd.SOURCES.values()}
    catalogue = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    assert {s["id_catalogue"] for s in i["sources"]} <= {s["id"] for s in catalogue["sources"]}
    e = i["effectifs_defense"]
    assert e["statut"] == "donnee_absente_a_la_source" and e["a_relire"] is False
    assert any("effectifs" in s["source"].lower() for s in i["sources_inaccessibles"])
    verdicts = {t["verdict"] for t in i["recherche_publique"]["trouvailles"]}
    assert verdicts <= {"réutilisable tel quel", "à adapter", "inspiration seulement"} and len(verdicts) == 3
    assert all(t["licence"] and t["mise_a_jour"] for t in i["recherche_publique"]["trouvailles"])
    p = _lire("prisons.json")
    assert i["reperes"]["prisons"]["detenus"] == p["national"]["detenus"] and i["reperes"]["prisons"]["statut_montant"] == "calculé"


# ---------------------------------------------------------------------------------------------------- entrepôt

@pytest.mark.skipif(not (LAKE / "justice_defense_population_ecrouee").exists(), reason="entrepôt justice_defense absent")
def test_production_reproductible_octet_pour_octet(tmp_path):
    jd.produire(tmp_path)
    for nom in FICHIERS:
        a = hashlib.sha256((tmp_path / nom).read_bytes()).hexdigest()
        b = hashlib.sha256((DATA / nom).read_bytes()).hexdigest()
        assert a == b, f"{nom} : la production ne redonne pas le fichier versionné"
