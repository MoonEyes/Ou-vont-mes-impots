"""Tests sans reseau des fichiers de precision : nature, effectifs, beneficiaires nommes.

Ils lisent site/data/ tel que produit par `python pipeline/beneficiaires.py tout`.
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import beneficiaires  # noqa: E402
import sirene  # noqa: E402

SITE = ROOT / "site" / "data"
BENEF = SITE / "beneficiaires"
DOSSIERS = [BENEF, SITE / "nature", SITE / "effectifs"]
TOL_EUR = 1.0


def _json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _tous_les_json():
    return [f for d in DOSSIERS for f in sorted(d.glob("*.json"))]


def _somme_groupe(g: dict) -> float:
    exclus = g["exclus_personnes_physiques_ou_non_identifies"]["montant_eur"]
    nv = g.get("autres_non_verifies", {}).get("montant_eur", 0.0)
    return sum(b["montant_eur"] for b in g["top"]) + g["autres_personnes_morales"]["montant_eur"] + nv + exclus


# --- Regle personnes physiques (bloquante) --------------------------------------------------------------------------


def _sans_accent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def verifier_personnes_morales(obj, chemin="") -> None:
    """Leve AssertionError si une categorie juridique hors 2xxx-9xxx ou un champ prenom apparait."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert "prenom" not in _sans_accent(k), f"champ prenom interdit : {chemin}/{k}"
            if k == "categorie_juridique":
                assert sirene.personne_morale(v), f"categorie juridique {v!r} non publiable : {chemin}"
            if k == "siren":
                assert sirene.siren_valide(v), f"SIREN invalide nomme : {chemin}"
                assert sirene.personne_morale(obj.get("categorie_juridique")), f"SIREN sans categorie : {chemin}"
            verifier_personnes_morales(v, f"{chemin}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            verifier_personnes_morales(v, f"{chemin}[{i}]")


def test_regle_personnes_physiques_detecte_une_violation():
    with pytest.raises(AssertionError):
        verifier_personnes_morales({"top": [{"siren": "123456789", "categorie_juridique": "1000"}]})
    with pytest.raises(AssertionError):
        verifier_personnes_morales({"top": [{"siren": "123456789", "categorie_juridique": "5710", "Prénom": "x"}]})


@pytest.mark.parametrize("fichier", sorted(BENEF.glob("*.json")), ids=lambda p: p.name)
def test_seules_des_personnes_morales_sont_nommees(fichier):
    verifier_personnes_morales(_json(fichier), fichier.name)
    texte = fichier.read_text(encoding="utf-8")
    assert '"categorie_juridique":"1000"' not in texte
    assert "prenom" not in _sans_accent(texte)


def test_csv_publie_sans_personne_physique():
    lignes = (BENEF / "beneficiaires_publies.csv").read_text(encoding="utf-8").splitlines()
    assert lignes[0].split(",")[:5] == ["source", "groupe", "siren", "denomination", "categorie_juridique"]
    assert "prenom" not in _sans_accent(lignes[0])
    for l in lignes[1:]:
        cj = l.rsplit(",", 2)[-2]
        assert sirene.personne_morale(cj), l


def test_classement_statut():
    cache = {"111111111": {"cj": "1000", "trouve": True}, "222222222": {"cj": "9220", "trouve": True, "nom": "A"}}
    assert beneficiaires.statut("NR CHORUS", "9220", cache) == ("ni", None)
    assert beneficiaires.statut("111111111", "0", cache) == ("pp", "1000")
    assert beneficiaires.statut("111111111", "1000", {}) == ("pp", "1000")
    assert beneficiaires.statut("222222222", None, cache) == ("pm", "9220")
    assert beneficiaires.statut("333333333", "0", cache)[0] == "nv"


# --- Millesime et source ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("fichier", _tous_les_json(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_millesime_et_source(fichier):
    d = _json(fichier)
    assert d.get("millesime"), fichier
    assert d.get("source"), fichier


def test_taille_des_fichiers():
    for d in DOSSIERS:
        for f in d.iterdir():
            assert f.stat().st_size < 5_000_000, f


# --- Conservation des montants ---------------------------------------------------------------------------------------


def test_conservation_associations_par_programme():
    n = 0
    for f in sorted(BENEF.glob("programme_*.json")):
        a = _json(f)["associations"]
        if not a:
            continue
        n += 1
        assert len(a["top"]) <= beneficiaires.TOP
        montants = [b["montant_eur"] for b in a["top"]]
        assert montants == sorted(montants, reverse=True)
        assert _somme_groupe(a) == pytest.approx(a["total_source_eur"], abs=TOL_EUR), f.name
    assert n > 50


def test_conservation_associations_total_source():
    """Le total des fichiers programme retombe sur le total de la source (11,8 Md EUR, credits 2023)."""
    total = sum((_json(f)["associations"] or {}).get("total_source_eur", 0) for f in BENEF.glob("programme_*.json"))
    index = _json(BENEF / "index.json")["controle"]["programmes"]
    assert total == pytest.approx(index["associations_total_eur"], abs=100)
    assert 10e9 < total < 14e9


@pytest.mark.parametrize("fichier,cle", [("france2030.json", "par_operateur"), ("marches_etat.json", "par_ministere")])
def test_conservation_france2030_et_marches(fichier, cle):
    d = _json(BENEF / fichier)
    assert _somme_groupe(d["ensemble"]) == pytest.approx(d["ensemble"]["total_eur"], abs=TOL_EUR)
    for nom, g in d[cle].items():
        assert _somme_groupe(g) == pytest.approx(g["total_eur"], abs=TOL_EUR), nom
        assert len(g["top"]) <= beneficiaires.TOP
    assert sum(g["total_eur"] for g in d[cle].values()) == pytest.approx(d["ensemble"]["total_eur"], abs=10)


def test_index_liste_les_fichiers():
    idx = _json(BENEF / "index.json")
    for f in idx["fichiers"]["programmes"]:
        assert (SITE / f).exists(), f
    assert (SITE / idx["fichiers"]["france2030"]).exists()
    assert (SITE / idx["fichiers"]["marches_etat"]).exists()


# --- Nature reelle et arbre ----------------------------------------------------------------------------------------------


def test_nature_coherente_en_interne():
    for f in sorted((SITE / "nature").glob("*.json")):
        d = _json(f)
        assert sum(p["eur"] for p in d["postes"]) == pytest.approx(d["total_eur"], abs=TOL_EUR), f.name
        assert sum(c["eur"] for c in d["categories"]) == pytest.approx(d["total_eur"], abs=TOL_EUR), f.name
        c = d["controle_arbre"]
        if c["total_arbre_eur"] is not None:
            assert c["ecart_eur"] == pytest.approx(d["total_eur"] - c["total_arbre_eur"], abs=TOL_EUR)


def test_nature_retombe_sur_l_arbre_dans_la_tolerance_publiee():
    racine = _json(SITE / "arbre" / "racine.json")
    controle = _json(BENEF / "index.json")["controle"]["nature"]
    tolerance = controle["tolerance_pct"]
    nature, arbre = 0.0, 0.0
    for f in (SITE / "nature").glob("*.json"):
        c = _json(f)["controle_arbre"]
        if c["total_arbre_eur"] is not None:
            nature += _json(f)["total_eur"]
            arbre += c["total_arbre_eur"]
    assert abs(nature - arbre) / arbre * 100 <= tolerance
    assert controle["ecart_global_pct"] == pytest.approx((nature - arbre) / arbre * 100, abs=0.01)
    # les programmes couverts representent l'essentiel de l'arbre
    assert arbre / (racine["md"] * 1e9) > 0.8


def test_effectifs_cout_moyen():
    n = 0
    for f in sorted((SITE / "effectifs").glob("*.json")):
        d = _json(f)
        if d["cout_moyen_par_etpt_eur"]:
            n += 1
            assert d["cout_moyen_par_etpt_eur"] == pytest.approx(d["titre2_eur"] / d["etpt"], abs=1)
            assert "Millésimes différents" in d["avertissement"]
            assert d["millesime_etpt"] == "LFI 2023"
    assert n > 30
