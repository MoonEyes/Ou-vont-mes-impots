"""Tests unitaires (entrées construites à la main) de pipeline/realisations.py : montants d'annexes, valeurs
d'indicateurs, codes, rapprochement de libellés, tendance et sens souhaité."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import realisations as r  # noqa: E402


@pytest.mark.parametrize("brut,attendu", [
    ("1 234,5", 1234.5), ("1 234 567,25", 1234567.25), ("-12", -12.0), ("", 0.0), ("-", 0.0),
    (None, 0.0), (7, 7.0), (float("nan"), 0.0),
])
def test_montant(brut, attendu):
    assert r.montant(brut) == attendu


@pytest.mark.parametrize("brut,attendu", [
    ("1 234,5", (1234.5, "1 234,5")),
    ("12 %", (12.0, "12 %")),
    ("≤ 3,5", (3.5, "≤ 3,5")),
    ("env. 40", (40.0, "env. 40")),
    ("-2,5", (-2.5, "-2,5")),
    ("85 (provisoire)", (85.0, "85 (provisoire)")),
    (3.0, (3.0, "3")),
    (2.5, (2.5, "2.5")),
])
def test_valeur_numerique(brut, attendu):
    assert r.valeur(brut) == attendu


@pytest.mark.parametrize("brut", ["nd", "ND", "n.c.", "sans objet", "SO"])
def test_valeur_marques_sans_valeur_gardent_le_brut(brut):
    assert r.valeur(brut) == (None, brut)


def test_valeur_texte_intervalle_et_vide():
    assert r.valeur("[10;20]") == (None, "[10;20]")
    assert r.valeur("entre 10 et 20") == (None, "entre 10 et 20")
    assert r.valeur(None) == (None, None)
    assert r.valeur("  ") == (None, None)
    assert r.valeur(float("nan")) == (None, None)


def test_prog3_et_code_ind():
    assert r.prog3("141") == "141"
    assert r.prog3(141.0) == "141"
    assert r.prog3("P 102") == "102"
    assert r.prog3("Programme 7") == "007"
    assert r.prog3(None) is None
    assert r.code_ind("P141.1.2") == "P141-1-2"
    assert r.code_ind("141-01-02") == "P141-1-2"
    assert r.code_ind("p141 - 1 - 2") == "P141-1-2"
    assert r.code_ind("indicateur") is None


def test_norm_et_similarite():
    assert r.norm("L’Œuvre  d'Été !") == "l oeuvre d ete"
    assert r.similarite("Taux de réussite au baccalauréat", "taux reussite baccalaureat") == 1.0
    assert r.similarite("", "x") == 0.0
    assert 0 < r.similarite("taux de réussite", "taux d'échec") < 1


def _serie(realises, cibles=None, evolution=None):
    return {"evolution": evolution, "realises": {a: {"valeur": v} for a, v in realises.items()},
            "cibles": {a: {"valeur": v, "source": "rap2025"} for a, v in (cibles or {}).items()}}


def test_sens_souhaite_colonne_evolution():
    assert r.sens_souhaite(_serie({}, evolution="Hausse"))["valeur"] == "hausse"
    assert r.sens_souhaite(_serie({}, evolution="Stabilité"))["valeur"] == "stabilité"


def test_sens_souhaite_par_position_des_cibles():
    s = _serie({2022: 10, 2023: 12}, {2024: 15, 2026: 20})
    sens = r.sens_souhaite(s)
    assert sens["valeur"] == "hausse" and sens["methode"] == "position des cibles"
    assert len(sens["comparaisons"]) == 2
    # cibles contradictoires : sens inconnu
    assert r.sens_souhaite(_serie({2022: 10, 2023: 12}, {2024: 15, 2025: 5}))["valeur"] == "inconnu"
    # aucune cible postérieure à un réalisé
    assert r.sens_souhaite(_serie({2024: 10}, {2023: 5}))["valeur"] == "inconnu"


def test_tendance():
    hausse = {"valeur": "hausse", "methode": "m", "source": "s", "justification": "j"}
    inconnu = {"valeur": "inconnu", "methode": None, "source": None, "justification": "pas de sens"}
    t = r.tendance(_serie({2022: 100, 2023: 110}), hausse)
    assert t["valeur"] == r.SENS_PUBLIE and t["variation"] == 10 and t["variation_relative_pct"] == 10.0
    assert r.tendance(_serie({2022: 100, 2023: 90}), hausse)["valeur"] == r.SENS_INVERSE
    # sous le seuil de stabilité (1 %)
    assert r.tendance(_serie({2022: 100, 2023: 100.5}), hausse)["valeur"] == "stable"
    assert r.tendance(_serie({2023: 1}), hausse)["valeur"] == "sens inconnu"
    # départ à zéro : pas de variation relative, mais une tendance
    t0 = r.tendance(_serie({2022: 0, 2023: 3}), inconnu)
    assert t0["variation_relative_pct"] is None and t0["valeur"] == "sens inconnu"
    assert r.r2(None) is None and r.r2(1.006) == 1.01
