"""Tests unitaires (entrées construites à la main, lecture des fichiers remplacée) des calculs de
pipeline/tracabilite.py : arrondis, répartition d'un programme entre parts, ventilation des achats, synthèse à 100 %."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import tracabilite as t  # noqa: E402

SRC_VIDE = {"vp": None, "f2030": None, "marches": None, "plrg": {}, "operateurs": None}


def _nature(postes: dict) -> dict:
    return {"total_eur": sum(postes.values()), "postes": [{"id": k, "eur": v} for k, v in postes.items()]}


def _lire(fichiers: dict):
    return lambda rel: fichiers.get(rel)


def _somme(res, part):
    return sum(c["eur"] for c in res["comp"][part])


def test_r2_pct():
    assert t.r2(1.234) == 1.23
    assert t.pct(1, 3) == 33.333
    assert t.pct(5, 0) == 0.0


def test_identifies_groupe():
    g = {"top": [{"montant_eur": 10.0}, {"montant_eur": 5.5}], "autres_personnes_morales": {"montant_eur": 4.5}}
    assert t.identifies_groupe(g) == 20.0


def test_composante_statut():
    c = t.composante(1.234, ["s"], "Exécution 2024", 0, None, "d")
    assert c["eur"] == 1.23 and c["statut"] == "exact" and c["niveau_identification"] == "entite"
    assert t.composante(1, ["s"], "m", 1, "raison", "d", "categorie")["statut"] == "approche"


def test_achats_par_ministere(monkeypatch):
    monkeypatch.setattr(t, "lire", _lire({
        "nature/101.json": _nature({"fonctionnement": 20, "investissement": 10, "salaires": 70}),
        "nature/102.json": _nature({"fonctionnement": 0}) | {"total_eur": 0},
    }))
    feuilles = [{"type": "programme", "code": "101", "mission": "Justice", "eur": 1000.0},
                {"type": "programme", "code": "102", "mission": "Justice", "eur": 50.0},
                {"type": "programme", "code": "103", "mission": "Mission inconnue", "eur": 50.0},
                {"type": "psr", "code": "psr_x", "mission": "Justice", "eur": 50.0}]
    assert dict(t.achats_par_ministere(feuilles)) == {"Justice": pytest.approx(300.0)}


def test_feuille_negative(monkeypatch):
    monkeypatch.setattr(t, "lire", _lire({}))
    r = t.calculer_feuille({"type": "programme", "code": "999", "eur": -10.0, "mission": "X"}, SRC_VIDE, {})
    assert r["comp"]["non_publie"][0]["eur"] == -10.0 and r["nature_connue"] == 0.0


def test_feuille_remunerations_dette_et_residu(monkeypatch):
    monkeypatch.setattr(t, "lire", _lire({"nature/150.json": _nature(
        {"salaires": 30, "cotisations": 10, "dette": 20, "fonctionnement": 15, "interventions": 25})}))
    r = t.calculer_feuille({"type": "programme", "code": "150", "eur": 1000.0, "mission": "X"}, SRC_VIDE, {})
    assert _somme(r, "nominatif_par_choix") == pytest.approx(400.0)
    assert _somme(r, "anonyme_par_nature") == pytest.approx(200.0)
    assert _somme(r, "beneficiaire_identifie") == 0.0
    assert _somme(r, "non_publie") == pytest.approx(400.0)
    assert r["nature_connue"] == 1000.0 and r["ecrete"] == 0.0


def test_feuille_programme_dette_entier_anonyme(monkeypatch):
    monkeypatch.setattr(t, "lire", _lire({}))
    code = next(iter(t.DETTE_PROGRAMMES))
    r = t.calculer_feuille({"type": "programme", "code": code, "eur": 500.0, "mission": "X"}, SRC_VIDE, {})
    assert _somme(r, "anonyme_par_nature") == 500.0 and not r["comp"]["non_publie"]


def test_feuille_beneficiaire_unique_de_la_nomenclature(monkeypatch):
    code = "841"
    monkeypatch.setattr(t, "lire", _lire({f"nature/{code}.json": _nature({"salaires": 10, "interventions": 90})}))
    r = t.calculer_feuille({"type": "programme", "code": code, "eur": 100.0, "mission": "X"}, SRC_VIDE, {})
    assert _somme(r, "beneficiaire_identifie") == pytest.approx(90.0)
    assert "France Télévisions" in r["comp"]["beneficiaire_identifie"][0]["detail"]


def test_feuille_psr(monkeypatch):
    monkeypatch.setattr(t, "lire", _lire({}))
    r = t.calculer_feuille({"type": "psr", "code": "psr_union_europeenne", "eur": 20.0, "mission": "X"}, SRC_VIDE, {})
    c = r["comp"]["beneficiaire_identifie"][0]
    assert c["eur"] == 20.0 and c["niveau_identification"] == "entite" and r["nature_connue"] == 20.0
    r2 = t.calculer_feuille({"type": "psr", "code": "psr_collectivites", "eur": 20.0, "mission": "X"}, SRC_VIDE, {})
    assert r2["comp"]["beneficiaire_identifie"][0]["niveau_identification"] == "categorie"


def test_feuille_marches_au_prorata_des_achats(monkeypatch):
    monkeypatch.setattr(t, "lire", _lire({"nature/101.json": _nature({"fonctionnement": 40, "interventions": 60})}))
    src = dict(SRC_VIDE, marches={"par_ministere": {"Justice": {
        "top": [{"montant_eur": 100.0}], "autres_personnes_morales": {"montant_eur": 0.0}}}})
    f = {"type": "programme", "code": "101", "eur": 1000.0, "mission": "Justice"}
    # achats du ministère : 400 ; titulaires nommés : 100 -> 25 % des achats du programme (400) = 100
    r = t.calculer_feuille(f, src, {"Justice": 400.0})
    ident = r["comp"]["beneficiaire_identifie"]
    assert len(ident) == 1 and ident[0]["eur"] == pytest.approx(100.0) and ident[0]["statut"] == "approche"
    # taux plafonné à 100 % des achats
    r = t.calculer_feuille(f, src, {"Justice": 10.0})
    assert _somme(r, "beneficiaire_identifie") == pytest.approx(400.0)


def test_feuille_scsp_plafonnee_par_la_categorie_32(monkeypatch):
    monkeypatch.setattr(t, "lire", _lire({"nature/101.json": _nature({"subventions_operateurs": 30,
                                                                      "interventions": 70})}))
    scsp = {"101": [{"operateur": "Op", "niveau": "entite", "eur": 500.0, "exact": False, "nb_programmes": 1,
                     "scsp_eur": 500.0}]}
    r = t.calculer_feuille({"type": "programme", "code": "101", "eur": 1000.0, "mission": "X"}, SRC_VIDE, {}, scsp)
    assert _somme(r, "beneficiaire_identifie") == pytest.approx(300.0)
    assert r["ecrete"] == pytest.approx(200.0)
    assert "plafonnée" in r["comp"]["beneficiaire_identifie"][0]["raison_approche"]


def _comps(**eur):
    c = {k: [] for k in t.PARTS}
    for k, v in eur.items():
        c[k].append(t.composante(v, ["s"], "m", 0, None, "d", "entite"))
    return c


def test_synthese_somme_exactement_100():
    s = t.synthese(3.0, _comps(beneficiaire_identifie=1.0, nominatif_par_choix=1.0, non_publie=1.0), 3.0)
    pcts = [p["pct"] for p in s["parts"].values()]
    assert round(sum(pcts), 3) == 100.0
    assert s["maillons"][0]["pct"] == 100.0 and s["maillons"][1]["pct"] == 100.0
    assert s["taux_tracabilite_pct"] == pytest.approx(66.667)
    assert s["maillons"][3]["pct"] == pytest.approx(33.333)


def test_synthese_noeud_negatif():
    s = t.synthese(-5.0, _comps(non_publie=-5.0), 0.0)
    assert s["parts"]["non_publie"]["pct"] == 100.0
    assert all(s["parts"][k]["pct"] == 0.0 for k in t.PARTS if k != "non_publie")
