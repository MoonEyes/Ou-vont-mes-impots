"""Tests unitaires (entrées construites à la main, sans réseau ni data/lake) des lecteurs de cellules de
pipeline/niches.py : montants des dépenses fiscales (virgules, « nc », « ε », milliers) et choix d'édition."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import niches  # noqa: E402


def test_espaces_unifie_les_blancs_insecables():
    assert niches.espaces("1 234 5  ") == "1 234 5"
    assert niches.espaces("a\n\t b") == "a b"


@pytest.mark.parametrize("brut,attendu", [
    ("1 234,5", {"brut": "1234,5", "meur": 1234.5}),
    ("1 234 567", {"brut": "1234567", "meur": 1234567.0}),
    ("-12,25", {"brut": "-12,25", "meur": -12.25}),
    ("0", {"brut": "0", "meur": 0.0}),
    (42, {"brut": "42", "meur": 42.0}),
    (42.0, {"brut": "42", "meur": 42.0}),
    (3.5, {"brut": "3.5", "meur": 3.5}),
])
def test_valeur_montants(brut, attendu):
    assert niches.valeur(brut) == attendu


@pytest.mark.parametrize("brut,marque", [
    ("ε", "ε"), (" ε ", "ε"), ("e", "ε"), ("€", "ε"),  # ε mal encodé dans certains classeurs
    ("nc", "nc"), ("NC", "nc"), (" Nc ", "nc"),
    ("-", "-"), ("–", "-"), ("—", "-"),
])
def test_valeur_marques_sans_montant(brut, marque):
    assert niches.valeur(brut) == {"brut": marque, "meur": None}


def test_valeur_absent_et_texte_libre():
    assert niches.valeur(None) is None
    assert niches.valeur("   ") is None
    assert niches.valeur("non chiffrable") == {"brut": "non chiffrable", "meur": None}


def test_code6_complete_et_rejette():
    assert niches.code6("110101") == "110101"
    assert niches.code6(10101) == "010101"
    assert niches.code6("10101.0") == "010101"
    assert niches.code6("abc") is None
    assert niches.code6("123") is None
    assert niches.code6(None) is None


def test_nombre_beneficiaires():
    assert niches.nombre_beneficiaires("ménages", "1 234") == {"nombre": 1234, "nature": "ménages"}
    assert niches.nombre_beneficiaires(None, "nc") == {"nombre": None, "nature": None, "brut": "nc"}
    assert niches.nombre_beneficiaires("entreprises", None) == {"nombre": None, "nature": "entreprises"}


def test_annee_texte():
    assert niches.annee_texte(2019.0) == "2019"
    assert niches.annee_texte(" 1998 ") == "1998"
    assert niches.annee_texte("") is None
    assert niches.annee_texte(None) is None


def test_nombre_fr():
    assert niches._nombre_fr("1 234,5") == 1234.5
    assert niches._nombre_fr("12 000") == 12000.0
    assert niches._nombre_fr("-") is None
    assert niches._nombre_fr("") is None


def test_edition_reference_selection_du_millesime():
    derniere = max(niches.EDITIONS)
    # l'année N est chiffrée en réalisation par le PLF N+2
    assert niches.edition_reference(derniere - 4) == derniere - 2
    # jamais au-delà de la dernière édition lue
    assert niches.edition_reference(derniere - 1) == derniere
    assert niches.edition_reference(derniere + 5) == derniere


def _mesure(ident, prog, couts):
    return {"id": ident, "programme": {"code": prog} if prog else None,
            "couts": {a: {"brut": b, "meur": m, **({"hors_reference": True} if h else {})} for a, (b, m, h) in couts.items()}}


def test_par_programme_hors_reference_et_non_chiffre():
    """Constats I2 et I3 : un coût hors référence reste hors des sommes ; un programme sans mesure chiffrée mais avec
    une mesure « nc » publie null et une mention, jamais 0 ; « - » seul reste 0."""
    progs = {p: {"noeud": f"G/M/{p}", "nom": p, "mission": "M", "grand_poste": "G", "budget_md": 1.0}
             for p in ("101", "102", "103", "104")}
    mesures = {m["id"]: m for m in [
        _mesure("000001", "101", {"2024": ("10", 10.0, False), "2025": ("nc", None, False), "2026": ("5", 5.0, False)}),
        _mesure("000002", "101", {"2024": ("19", 19.0, True)}),  # hors référence : jamais additionné
        _mesure("000003", "102", {"2024": ("nc", None, False), "2025": ("ε", None, False), "2026": ("-", None, False)}),
        _mesure("000004", "103", {"2024": ("-", None, False), "2025": ("-", None, False), "2026": ("-", None, False)}),
        _mesure("000005", "999", {"2024": ("nc", None, False), "2025": ("2", 2.0, False), "2026": ("7", 7.0, True)}),
    ]}
    pp = niches.par_programme(mesures, progs, {"millesime": "x", "total_md": 4.0})
    P = {p["programme"]: p for p in pp["programmes"]}
    assert P["101"]["fiscal_meur"] == {"2024": 10.0, "2025": None, "2026": 5.0}
    assert P["101"]["hors_reference_meur"] == {"2024": 19.0} and set(P["101"]["mention"]) == {"2025"}
    assert P["101"]["total_2024_meur"] == 1010.0 and P["101"]["part_fiscale_2024"] == round(10 / 1010, 4)
    assert P["102"]["fiscal_meur"] == {"2024": None, "2025": None, "2026": 0.0}
    assert set(P["102"]["mention"]) == {"2024", "2025"} and "non chiffré" in P["102"]["mention"]["2024"]
    assert P["102"]["part_fiscale_2024"] is None and P["102"]["total_2024_meur"] == 1000.0
    assert P["102"]["non_chiffrees"] == {"2024": 1, "2025": 1, "2026": 0}
    assert P["103"]["fiscal_meur"] == {"2024": 0.0, "2025": 0.0, "2026": 0.0} and "mention" not in P["103"]
    for p in P.values():
        assert not {"chiffrees", "nc", "budget_md"} & set(p)
    h = pp["hors_arbre"][0]
    assert h["programme"] == "999" and h["fiscal_meur"] == {"2024": None, "2025": 2.0, "2026": 0.0}
    assert h["hors_reference_meur"] == {"2026": 7.0} and set(h["mention"]) == {"2024"}
    g = pp["grands_postes"][0]
    assert g["fiscal_2024_meur"] == 10.0 and g["fiscal_2025_meur"] == 0.0 and g["fiscal_2026_meur"] == 5.0
    assert g["programmes_non_chiffres"] == {"2024": 1, "2025": 2, "2026": 0}
