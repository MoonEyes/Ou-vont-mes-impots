"""Tests sans réseau des opérateurs de l'État (pipeline/operateurs.py) et de leur source dans la traçabilité."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import operateurs  # noqa: E402
import tracabilite  # noqa: E402

SORTIE = ROOT / "site" / "data" / "operateurs"
OPS = SORTIE / "operateurs.json"
publie = pytest.mark.skipif(not OPS.exists(), reason="site/data/operateurs absent")


def _json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# --- Fonctions d'analyse (sans PDF) --------------------------------------------------------------------------------


def _mot(t, x0, x1):
    return {"text": t, "x0": x0, "x1": x1, "top": 100.0}


def test_separer_recolle_les_milliers_et_garde_les_colonnes():
    ligne = [_mot("Transferts", 47, 79), _mot("6", 223, 227), _mot("943", 229, 241), _mot("286", 243, 254),
             _mot("726", 282, 293), _mot("995", 295, 307), _mot("-109", 320, 334), _mot("879", 336, 347)]
    txt, nums = operateurs.separer(ligne, 200)
    assert [w["text"] for w in txt] == ["Transferts"]
    assert [v for v, _, _ in nums] == [6943286.0, 726995.0, -109879.0]
    assert operateurs.colonnes(nums, [254, 307, 347, 400]) == {0: 6943286.0, 1: 726995.0, 2: -109879.0}


def test_cle_stable_entre_jaunes():
    assert operateurs.cle("Pôle emploi") == operateurs.cle("France Travail")
    assert operateurs.cle("SGP - Société du Grand Paris") == operateurs.cle("SGP - Société des grands projets")
    assert operateurs.cle("ADEME - Agence de l'environnement") == "ademe"
    assert operateurs.cle("Agences de l'eau") == "agencesdeleau"


def test_siren_seulement_personne_morale_publique_et_nom_identique():
    nom = "ADEME - Agence de l'environnement et de la maîtrise de l'énergie"
    bon = {"siren": "385290309", "nature_juridique": "4110",
           "nom_complet": "AGENCE DE L'ENVIRONNEMENT ET DE LA MAITRISE DE L'ENERGIE"}
    homonyme_prive = {**bon, "siren": "123456789", "nature_juridique": "5710"}
    personne = {**bon, "siren": "999999999", "nature_juridique": "1000"}
    autre = {**bon, "siren": "111111111", "nom_complet": "AGENCE DE L'EAU"}
    assert operateurs.choisir(nom, [personne, homonyme_prive, autre]) is None
    r = operateurs.choisir(nom, [homonyme_prive, bon])
    assert r["siren"] == "385290309" and r["methode"] == "dénomination identique"


def test_repartition_scsp_par_programme(monkeypatch):
    feuilles = [{"type": "programme", "code": c, "eur": 100.0} for c in ("101", "102", "103")]
    nat = {"101": 0.5, "102": 0.3, "103": 0.0}
    monkeypatch.setattr(tracabilite, "lire", lambda rel: {"total_eur": 1.0, "postes": [
        {"id": "subventions_operateurs", "eur": nat[rel.split("/")[1][:3]]}]})
    ops = {"operateurs": [
        {"nom": "A - Mono", "niveau": "operateur", "annees": {"2024": {
            "nature": "execution", "financement_etat": {"scsp": {"cp_eur": 20.0}}, "programmes_financeurs": ["101"]}}},
        {"nom": "Catégorie B", "niveau": "categorie", "annees": {"2024": {
            "nature": "execution", "financement_etat": {"scsp": {"cp_eur": 16.0}},
            "programmes_financeurs": ["101", "102", "103"]}}},
        {"nom": "C - LFI seulement", "niveau": "operateur", "annees": {"2024": {
            "nature": "lfi", "financement_etat": {"scsp": {"cp_eur": 99.0}}, "programmes_financeurs": ["101"]}}}]}
    r = tracabilite.scsp_par_programme(feuilles, ops)
    assert set(r) == {"101", "102"}
    a = r["101"][0]
    assert a["exact"] and a["eur"] == 20.0 and a["niveau"] == "entite"
    b101 = next(x for x in r["101"] if x["operateur"] == "Catégorie B")
    b102 = r["102"][0]
    assert not b101["exact"] and b101["niveau"] == "categorie"
    # le programme 101 (50) garde 20 pour A ; B (16) se répartit sans dépasser 50 en 101 ni 30 en 102
    assert b101["eur"] + b102["eur"] == pytest.approx(16.0)
    assert a["eur"] + b101["eur"] <= 50.0 + 1e-6 and b102["eur"] <= 30.0 + 1e-6


def test_repartition_scsp_respecte_le_plafond_du_programme(monkeypatch):
    feuilles = [{"type": "programme", "code": c, "eur": 100.0} for c in ("201", "202")]
    nat = {"201": 0.1, "202": 0.9}
    monkeypatch.setattr(tracabilite, "lire", lambda rel: {"total_eur": 1.0, "postes": [
        {"id": "subventions_operateurs", "eur": nat[rel.split("/")[1][:3]]}]})
    ops = {"operateurs": [
        {"nom": "Gros", "niveau": "operateur", "annees": {"2024": {
            "nature": "execution", "financement_etat": {"scsp": {"cp_eur": 50.0}},
            "programmes_financeurs": ["201", "202"]}}},
        {"nom": "Petit", "niveau": "operateur", "annees": {"2024": {
            "nature": "execution", "financement_etat": {"scsp": {"cp_eur": 10.0}}, "programmes_financeurs": ["201"]}}}]}
    r = tracabilite.scsp_par_programme(feuilles, ops)
    assert sum(x["eur"] for x in r["201"]) <= 10.0 + 1e-6
    petit = next(x for x in r["201"] if x["operateur"] == "Petit")
    assert petit["eur"] == pytest.approx(10.0, abs=0.01)  # le programme 201 revient à son seul opérateur possible
    assert sum(x["eur"] for x in r["202"]) == pytest.approx(50.0, abs=0.01)


# --- Fichiers publiés ----------------------------------------------------------------------------------------------


@publie
def test_identifiants_uniques_et_annees():
    d = _json(OPS)
    ids = [o["id"] for o in d["operateurs"]]
    assert len(ids) == len(set(ids))
    for o in d["operateurs"]:
        for a, v in o["annees"].items():
            assert 2019 <= int(a) <= 2025, (o["id"], a)
            assert v["sources"], (o["id"], a)


@publie
def test_ordres_de_grandeur_2024():
    idx = _json(SORTIE / "index.json")
    t = idx["totaux"]["2024"]
    assert 30e9 < t["scsp_cp_eur"] < 40e9
    assert 350_000 < t["etpt_sous_plafond"] < 450_000
    assert 15e9 < t["taxes_affectees_eur"] < 30e9
    assert idx["couverture"]["operateurs_liste_plf2026"] >= 400
    d = {o["id"]: o for o in _json(OPS)["operateurs"]}
    ft = d["francetravail"]["annees"]["2024"]
    assert ft["financement_etat"]["scsp"]["cp_eur"] > 1e9
    assert d["francecompetences"]["annees"]["2024"]["taxes_affectees_eur"] > 5e9


@publie
def test_totaux_recalculables():
    idx = _json(SORTIE / "index.json")
    ops = _json(OPS)["operateurs"]
    for a, t in idx["totaux"].items():
        s = sum(((o["annees"].get(a) or {}).get("financement_etat") or {}).get("scsp", {}).get("cp_eur") or 0
                for o in ops)
        assert abs(s - t.get("scsp_cp_eur", 0)) < 1, a


@publie
def test_aucune_donnee_individuelle():
    texte = OPS.read_text(encoding="utf-8")
    assert "commentaire" not in texte.lower()
    assert not re.search(r"\b(M\.|Mme|Monsieur|Madame)\s+[A-Z]", texte)
    d = _json(OPS)
    for o in d["operateurs"]:
        for m in o.get("membres", []):
            if m["categorie_juridique"]:
                assert m["categorie_juridique"][0] in "23456789"
        if o["siren"]:
            assert re.fullmatch(r"\d{9}", o["siren"]) and o["categorie_juridique"][0] in "47"


@publie
def test_composantes_operateurs_dans_la_tracabilite():
    trac = ROOT / "site" / "data" / "tracabilite"
    if not (trac / "resume.json").exists():
        pytest.skip("traçabilité absente")
    vues = 0
    for f in trac.glob("programme_*.json"):
        d = _json(f)
        comps = [c for c in d["composantes"]["beneficiaire_identifie"]
                 if tracabilite.SRC_OPERATEURS in c["sources"]]
        if not comps:
            continue
        vues += 1
        nat = _json(ROOT / "site" / "data" / "nature" / f"{d['programme']}.json")
        part32 = sum(p["eur"] for p in nat["postes"] if p["id"] == "subventions_operateurs") / nat["total_eur"]
        assert sum(c["eur"] for c in comps) <= part32 * d["total_eur"] + 1, f.name
        for c in comps:
            assert c["detail"].startswith("Subvention pour charges de service public 2024 : ")
            assert c["statut"] == "exact" or c["raison_approche"]
    assert vues >= 50
