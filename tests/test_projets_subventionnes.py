"""Projets subventionnés par l'État (pipeline/projets_subventionnes.py) : lecture, règles de publication, fichiers.

Les tests de règles tournent sur des lignes construites à la main ; les tests des fichiers publiés portent sur
site/data/projets_subventionnes (sautés si absent).
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "projets_subventionnes"
sys.path.insert(0, str(ROOT / "pipeline"))
import projets_subventionnes as ps  # noqa: E402


# --- Règles (sans données) -------------------------------------------------------------------------------------------

def test_codes_et_dates():
    assert ps.code5("1004") == "01004" and ps.code5("2A004") == "2A004" and ps.code5("97411") == "97411"
    for v in ("NULL", "", None, "abc", "123"):
        assert ps.code5(v) is None, v
    assert ps.dep_de("97411") == "974" and ps.dep_de("2B033") == "2B" and ps.dep_de("44109") == "44"
    assert ps.date_iso("12/03/2021") == "2021-03-12" and ps.date_iso("2024-01-25") == "2024-01-25"
    assert ps.date_iso("") is None and ps.date_iso("bientôt") is None


def test_badges_une_ligne_par_commune():
    lignes = [{"insee_com": "01053", "id_acv": "ACV035", "lib_acv": "Bourg-en-Bresse", "date_signature": "2024-01-25"},
              {"insee_com": "1053", "id_acv": "ACV001", "lib_acv": "Bourg", "date_signature": ""},
              {"insee_com": "NULL", "id_acv": "ACV002", "lib_acv": "x", "date_signature": ""}]
    b = ps.lire_badges(lignes, "acv")
    assert list(b) == ["01053"] and b["01053"]["id"] == "ACV001" and b["01053"]["date_signature"] is None
    p = ps.lire_badges([{"insee_com": "01033", "id_pvd": "pvd-84-01-1", "date_signature": "12/03/2021"}], "pvd")
    assert p == {"01033": {"id": "pvd-84-01-1", "date_signature": "2021-03-12"}}


def _ligne(siren, montant, insee="44109", annee=2024, intitule="Rénovation de la piscine"):
    return {"annee": annee, "programme": "380", "insee": insee, "dep": "44", "siren": siren, "intitule": intitule,
            "demarche": "Renaturation des villes", "montant": montant, "ej": "2104"}


def test_personnes_physiques_et_non_identifies_agreges():
    communes = {"44109": ("Nantes", "44")}
    deps = {"44": "Loire-Atlantique"}
    stock = {"214401093": ("7210", "COMMUNE DE NANTES"), "123456789": ("1000", None),
             "855800462": ("6540", None)}
    publiables = {"214401093": ("7210", "COMMUNE DE NANTES"), "855800462": ("6540", None)}
    lignes = [_ligne("214401093", 1000.0), _ligne("123456789", 50.0), _ligne("", 7.0),
              _ligne("855800462", 3.0), _ligne("999999999", 2.0), _ligne("214401093", None),
              _ligne("214401093", 5.0, insee=None)]
    par_dep, nat = ps.produire_fonds_vert(lignes, communes, deps, publiables, stock, set())
    d = par_dep["44"]
    publies = d["communes"]["44109"]
    assert len(publies) == 2 and {x[4] for x in publies} == {1000.0, None}   # montant non communiqué : null, pas 0
    assert set(d["beneficiaires"]) == {"214401093"}
    ex = d["exclus"]["2024"]
    assert ex["projets"] == 4 and ex["dont_personnes_physiques"] == 1 and ex["dont_sans_siren"] == 1
    assert ex["dont_nom_de_personne_possible"] == 1 and ex["dont_siren_introuvable"] == 1
    assert ex["montant_eur"] == 62.0
    n = nat["par_annee"]["2024"]
    assert n["lignes"] == 7 and n["lignes_montant_non_communique"] == 1 and n["montant_eur"] == 1067.0
    assert n["non_localises"] == {"projets": 1, "montant_eur": 5.0}
    assert n["projets_publies"] == 2 and n["montant_publie_eur"] == 1000.0


def test_intitule_avec_nom_de_personne_retire():
    communes, deps = {"44109": ("Nantes", "44")}, {"44": "Loire-Atlantique"}
    stock = publiables = {"214401093": ("7210", "COMMUNE DE NANTES")}
    lignes = [_ligne("214401093", 10.0, intitule="Subvention à M. Dupont pour sa toiture")]
    par_dep, nat = ps.produire_fonds_vert(lignes, communes, deps, publiables, stock, set())
    assert par_dep["44"]["communes"]["44109"][0][3] is None and nat["intitules_retires"] == 1


def test_totaux_ignorent_les_montants_non_communiques():
    t = ps.totaux_par_annee([(2024, "380", None, "a", 10.0, "1", None), (2024, "380", None, "b", None, "1", None),
                             (2023, "113", None, "c", 2.5, "1", None)])
    assert t == {"2023": {"projets": 1, "montant_eur": 2.5, "lignes_montant_non_communique": 0},
                 "2024": {"projets": 2, "montant_eur": 10.0, "lignes_montant_non_communique": 1}}


def test_jamais_realise_ni_livre_dans_le_code():
    assert ps.STATUT_DGCL == "subvention attribuée" and ps.STATUT_FV == "montant engagé"
    assert {d["statut"] for d in ps.DISPOSITIFS} == {"subvention attribuée", "montant engagé"}


# --- Fichiers publiés ------------------------------------------------------------------------------------------------

def _publies():
    if not (DOSSIER / "index.json").exists():
        pytest.skip("site/data/projets_subventionnes absent")
    return json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))


def test_index_et_departements():
    i = _publies()
    assert len(i["departements"]) == 101
    for d in i["departements"]:
        f = DOSSIER.parent / d["fichier"]
        assert f.exists() and f.stat().st_size < 1_000_000, d["fichier"]
        if d["fichier_dgcl"]:
            assert (DOSSIER.parent / d["fichier_dgcl"]).exists()
    assert {x["id"] for x in i["dispositifs"]} >= {"DETR", "DSIL", "DPV", "DSID", "Fonds vert"}
    assert i["sans_projet"] == "aucun projet publié pour ces dispositifs"


def test_statut_tel_que_publie_jamais_realise():
    _publies()
    interdit = re.compile(r"\b(réalisés?|livrés?|ne fait rien)\b", re.I)
    for f in sorted(DOSSIER.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        # les intitulés reproduits tels quels ne sont pas de la rédaction du site
        for cle in ("statuts", "sans_projet", "limites", "methode", "ordre"):
            if cle in d:
                assert not interdit.search(json.dumps(d[cle], ensure_ascii=False)
                                           .replace("ne disent pas si le projet est réalisé", "")
                                           .replace("ne dit pas si le projet est réalisé", "")), (f.name, cle)


def test_beneficiaires_personnes_morales_et_conservation():
    i = _publies()
    for d in i["departements"]:
        x = json.loads((DOSSIER.parent / d["fichier"]).read_text(encoding="utf-8"))
        for s, b in x["beneficiaires"].items():
            assert re.match(r"^[2-9]\d{3}$", b["categorie_juridique"]) and b["categorie_juridique"] not in (
                "2110", "2210", "2310", "2385"), (d["code"], s)
        lignes = [p for c in x["communes"].values() for p in c.get("fonds_vert", [])]
        lignes += [p for v in x["communes_hors_cog"].values() for p in v]
        assert all(p[5] in x["beneficiaires"] for p in lignes)
        assert sum(v["projets"] for v in x["fonds_vert_totaux"]["par_annee"].values()) == len(lignes)
        for a, t in x["fonds_vert_totaux"]["par_annee"].items():
            somme = sum(p[4] for p in lignes if str(p[0]) == a and p[4] is not None)
            assert abs(somme - t["montant_eur"]) < 1, (d["code"], a)
        for insee, c in x["communes"].items():
            assert insee.startswith(d["code"]) or d["code"] in ("2A", "2B")
            assert c.get("fonds_vert") or c.get("badges")


def test_controle_avec_subventions_et_totaux_nationaux():
    i = _publies()
    for c in i["controles"]["fonds_vert_subventions"]:
        assert c["ecart_eur"] is not None and abs(c["ecart_eur"]) < 1, c
    for a, v in i["fonds_vert"]["par_annee"].items():
        somme = v["montant_publie_eur"] + v["exclus"]["montant_eur"] + v["non_localises"]["montant_eur"]
        assert abs(somme - v["montant_eur"]) < 1, a
        projets = v["projets_publies"] + v["exclus"]["projets"] + v["non_localises"]["projets"]
        assert projets == v["lignes"], a
