"""Tests unitaires (entrées construites à la main) de pipeline/controle.py : tranches de dépenses, exercices,
filtres de confidentialité sur le texte libre et identifiants stables."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import controle as c  # noqa: E402


@pytest.mark.parametrize("brut,attendu", [
    ("< 10 000 euros", (0.0, 10000.0)),
    ("> = 100 000 euros et < 200 000 euros", (100000.0, 200000.0)),
    ("> = 10 000 000 euros", (10000000.0, None)),
    ("inconnu", None), ("", None), (None, None),
])
def test_tranche_depense(brut, attendu):
    assert c.tranche_depense(brut) == attendu


def test_annee_exercice():
    assert c.annee_exercice({"dateFin": "31/12/2023", "dateDebut": "01/01/2023"}) == 2023
    assert c.annee_exercice({"dateDebut": "01/01/2022"}) == 2022
    assert c.annee_exercice({}) is None


@pytest.mark.parametrize("texte", [
    "Réunion avec Jean DUPONT", "Échange avec M. Martin", "Rendez-vous Mme Durand", "Courrier à Me Leroy",
])
def test_texte_sans_personne_retire(texte):
    assert c.texte_sans_personne(texte) is None


def test_texte_sans_personne_garde_et_cible():
    assert c.texte_sans_personne("  Projet de loi   de finances ") == "Projet de loi de finances"
    assert c.texte_sans_personne("Commission des finances de l'Assemblée") is not None
    assert c.texte_sans_personne(None) is None
    assert c.cible_publiable("Députés") == "Députés"
    assert c.cible_publiable("Appeler le 06 12 34 56") == "texte libre non publié"
    assert c.cible_publiable("Jean DUPONT") == "texte libre non publié"


def test_norm_contient_id_stable():
    assert c.norm("L’Œuvre  d'Été") == "l oeuvre d ete"
    assert c.contient("rapport de la cour des comptes", "Cour des comptes")
    assert not c.contient("courtoisie", "cour")
    assert not c.contient("x", "")
    assert c.id_stable("a") == c.id_stable("a") and 0 <= c.id_stable("a") < 10**9
    assert c.id_stable("a") != c.id_stable("b")
