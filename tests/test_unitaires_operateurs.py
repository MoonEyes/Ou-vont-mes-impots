"""Tests unitaires (entrées construites à la main, sans PDF ni réseau) de pipeline/operateurs.py : clés,
sigles, rapprochement SIREN et arrondis."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import operateurs as o  # noqa: E402


def test_norm_propre_sans_accent():
    assert o.norm("École « normale » supérieure !") == "ecolenormalesuperieure"
    assert o.norm(None) == ""
    assert o.propre("  l’Agence \n  X ") == "l'Agence X"
    assert o.sans_accent("Énergie") == "Energie"


def test_sigle_et_requete():
    assert o.sigle("ADEME - Agence de l'environnement") == "ADEME"
    assert o.sigle("CEA – Commissariat") == "CEA"
    assert o.sigle("Agences de l'eau") is None
    assert o.sigle("A - trop court") is None
    assert o.requete_siren("ADEME - Agence de l'environnement") == "Agence de l'environnement"
    assert o.requete_siren("Agences de l'eau") == "Agences de l'eau"


def test_cle_alias_et_nom_sans_sigle():
    assert o.cle("ENSTA Paris") == o.cle("ENSTA")
    assert o.cle("Conseil national des communes « Compagnon de la Libération »") == o.cle("Ordre de la Libération")
    assert o.cle("Établissement public - long nom tout en minuscules") == "etablissementpublic"


def test_choisir_par_sigle_et_debut_de_denomination():
    nom = "CNES - Centre national d'études spatiales"
    x = {"siren": "775665912", "nature_juridique": "4110", "sigle": "CNES",
         "nom_complet": "CENTRE NATIONAL D'ETUDES SPATIALES (CNES)"}
    r = o.choisir(nom, [x])
    assert r == {"siren": "775665912", "categorie_juridique": "4110", "methode": "dénomination identique"}
    y = {**x, "nom_complet": "CENTRE NATIONAL D'ETUDES SPATIALES SIEGE", "nom_raison_sociale": ""}
    assert o.choisir(nom, [y])["methode"] == "sigle et début de dénomination"


def test_choisir_refuse_hors_droit_public_et_personnes_physiques():
    nom = "Agence X"
    base = {"siren": "111111111", "nom_complet": "AGENCE X"}
    for cj in ("1000", "2110", "5710", "9220", "", None):
        assert o.choisir(nom, [{**base, "nature_juridique": cj}]) is None, cj
    assert o.choisir(nom, [{**base, "nature_juridique": "7389"}])["siren"] == "111111111"


def test_r0():
    assert o.r0(None) is None
    assert o.r0(12.6) == 13.0
