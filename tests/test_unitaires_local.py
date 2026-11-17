"""Tests unitaires (entrées construites à la main, sans data/lake) de pipeline/local.py : nombres, euros par
habitant, SIREN, filtres de noms de personnes et séries par millésime."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import local  # noqa: E402

PRENOMS = {"JEAN", "MARIE", "PIERRE", "CATHERINE"}


@pytest.mark.parametrize("brut,attendu", [
    ("1 234,5", 1234.5), ("1 234", 1234.0), ("-12,75", -12.75), (7, 7.0), (2.5, 2.5),
    (None, None), ("", None), ("nc", None), ("ε", None), (float("nan"), None),
])
def test_num(brut, attendu):
    assert local.num(brut) == attendu


def test_euros_et_par_hab():
    assert local.euros(None) is None
    assert local.euros(1234.6) == 1235
    assert local.par_hab(1000, 3) == 333.33
    assert local.par_hab(None, 3) is None
    assert local.par_hab(1000, 0) is None
    assert local.par_hab(1000, None) is None


def test_siren_dep_et_annee():
    assert local.siren_de("212 401 377") == "212401377"
    assert local.siren_de("21240137700016") == "212401377"  # SIRET -> SIREN
    assert local.siren_de("1234") == "" and local.siren_de(None) == ""
    assert local.dep_de_insee("44109") == "44"
    assert local.dep_de_insee("97411") == "974"
    assert local.dep_de_insee("2A004") == "2A"
    assert local.annee_dot("2024-01-01") == "2024" and local.annee_dot(2023) == "2023"
    assert local._milliers(34875) == "34 875"


def test_propre_et_norm_col():
    assert local.propre(None) == ""
    assert local.propre("  a  b\n") == "a b"
    assert local.norm_col("Montant (€) Total") == "montanttotal"
    assert local.norm_col("Bénéficiaire_SIRET") == "beneficiairesiret"


@pytest.mark.parametrize("texte", [
    "Subvention à M. Dupont", "Aide Mme Durand", "MONSIEUR LEROY pour travaux", "Messieurs Martin frères",
    "Aide à Jean Dupont", "Prix Marie-Curie de Catherine Martin", "aide pierre martin",
])
def test_contient_nom_de_personne(texte):
    assert local.contient_nom_de_personne(texte, PRENOMS)


@pytest.mark.parametrize("texte", [
    "Association Saint-Jean de Nantes", "Paroisse Sainte-Marie", "Club ST JEAN", "Jean",
    "Comité des fêtes", "Fête de la Saint-Pierre",
])
def test_ne_contient_pas_de_nom_de_personne(texte):
    assert not local.contient_nom_de_personne(texte, PRENOMS)


@pytest.mark.xfail(strict=True, reason=(
    "BUG local.contient_nom_de_personne : un prénom suivi d'une particule (« de », « du », « des ») n'est pas "
    "reconnu, car la particule fait partie de MOTS_OUTILS : « Aide à Marie de Kergariou » serait publié avec le nom "
    "de la personne physique."))
def test_nom_a_particule_reconnu():
    assert local.contient_nom_de_personne("Aide à Marie de Kergariou", PRENOMS)


def test_objet_publiable():
    assert local.objet_publiable("  Rénovation   de l'école  ", PRENOMS) == "Rénovation de l'école"
    assert local.objet_publiable("Aide à Jean Dupont", PRENOMS) is None
    assert local.objet_publiable("non disponible", PRENOMS) is None
    assert local.objet_publiable("NULL", PRENOMS) is None
    assert local.objet_publiable("", PRENOMS) is None
    assert local.objet_publiable("x" * 200, PRENOMS) == "x" * 140
    assert local.objet_publiable("abcdef", PRENOMS, longueur=3) == "abc"


def test_prenoms_minimaux_sans_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "CACHE", tmp_path)
    monkeypatch.setattr(local, "_PRENOMS", None)
    p = local.prenoms()
    assert "JEAN" in p and "FRANCE" not in p
    assert local.contient_nom_de_personne("Subvention Ile-de-France Mobilités") is False
    assert local.prenoms() is p  # mémoïsé


def test_serie_selectionne_les_millesimes_et_calcule_par_habitant():
    lib = dict(local.AGREGATS)
    k0, k1 = local.CLES[0], local.CLES[1]
    lignes = [
        {"id": "44109", "nom": "Nantes", "siren": 212401093, "annee": 2023, "agregat": lib[k0], "montant": "1 000",
         "pop": 10},
        {"id": "44109", "nom": "Nantes", "annee": 2023, "agregat": lib[k1], "montant": "nc", "pop": 10},
        {"id": "44109", "nom": "Nantes", "annee": 2019, "agregat": lib[k0], "montant": "5", "pop": 10},  # hors millésime
        {"id": "44109", "nom": "Nantes", "annee": 2023, "agregat": "Agrégat inconnu", "montant": "5", "pop": 10},
    ]
    s = local.serie(lignes, "id", ["2022", "2023"])
    x = s["44109"]
    assert x["siren"] == "212401093"
    assert list(x["eur"]) == ["2023"]
    assert x["eur"]["2023"][0] == 1000 and x["eur"]["2023"][1] is None
    assert x["eur_hab"]["2023"][0] == 100.0 and x["eur_hab"]["2023"][1] is None
    assert x["population"] == {"2023": 10}


def test_annees_ofgl_garde_les_derniers_exercices(monkeypatch, tmp_path):
    con = local.ddb()
    con.execute(f"""copy (select make_date(a, 12, 31) exer from range(2015, 2025) t(a))
                    to '{tmp_path / "local_departements.parquet"}' (format parquet)""")
    monkeypatch.setattr(local, "COLL", tmp_path)
    attendu = [str(a) for a in range(2024 - local.NB_ANNEES + 1, 2025)]
    assert local.annees_ofgl(local.ddb()) == attendu
