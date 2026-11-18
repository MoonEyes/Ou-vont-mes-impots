"""Sécurité intérieure (pipeline/securite_interieure.py) : contrat, neutralité, cohérence des totaux.

Les tests sur site/data/securite_interieure tournent sans réseau ni entrepôt ; la reproductibilité demande
l'entrepôt (data/lake/securite_interieure/), sautée sinon.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "securite_interieure"
LAKE = ROOT / "data" / "lake" / "securite_interieure"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "pipeline"))
from test_neutralite import fautes, textes  # noqa: E402

import securite_interieure as si  # noqa: E402

FICHIERS = ["index.json", "budget.json", "effectifs.json", "amendes.json"]
# Jugements propres au sujet, en plus du lexique partagé, et sujet exclu (délinquance).
JUGEMENTS = re.compile(r"(?<!\w)(?:laxis\w*|sécuritaire\w*|répressi\w*|insuffisan\w*|excessi\w*|manque\w* de moyens|"
                       r"sous-effectif\w*|matraqu\w*|pompe à fric|vache à lait)(?!\w)", re.I)
HORS_SUJET = re.compile(r"(?<!\w)(?:délinquance|crimes?|délits?|faits constatés|victimes?|mis en cause)(?!\w)", re.I)
TOLERANCE = 1.0  # euro


def _lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def budget():
    return _lire("budget.json")


@pytest.fixture(scope="module")
def amendes():
    return _lire("amendes.json")


@pytest.fixture(scope="module")
def effectifs():
    return _lire("effectifs.json")


# ---------------------------------------------------------------------------------------------------- unitaires

def test_nombre_jamais_zero_pour_une_absence():
    assert si.nombre("8 069,00") == 8069.0 and si.nombre("336340107") == 336340107.0
    assert si.nombre("1394907265,6") == 1394907265.6 and si.nombre("-3605029466.38") == -3605029466.38
    assert si.nombre("0") == 0.0
    for absent in (None, "", "-", "nc", "nd", True):
        assert si.nombre(absent) is None


def test_codes_dans_les_libelles():
    assert si.code_programme("Police nationale - 176") == "176"
    assert si.code_programme("Désendettement de l'État - 755 ") == "755"
    assert si.code_programme("Titre 2") is None
    assert si._code_fin("Contrôle automatisé - 746") == "746"
    assert si._sans_code("Amendes perçues - 74601") == "Amendes perçues"


def test_csv_compresse_lu_comme_le_texte(tmp_path):
    texte = "Mission;Programme\nSécurités;Police nationale - 176\n"
    (tmp_path / "a.csv").write_bytes(gzip.compress(texte.encode("utf-8")))
    (tmp_path / "b.csv").write_text("﻿" + texte, encoding="utf-8")
    assert si.lire_csv(tmp_path / "a.csv") == si.lire_csv(tmp_path / "b.csv") == [
        {"Mission": "Sécurités", "Programme": "Police nationale - 176"}]


# ---------------------------------------------------------------------------------------------------- en-têtes

@pytest.mark.parametrize("nom", FICHIERS)
def test_entete_taille_et_neutralite(nom):
    f = DATA / nom
    assert f.stat().st_size < 1_000_000  # chargé par le navigateur
    d = _lire(nom)
    assert d["millesime"] and d["source"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["date_sources"])
    assert "https://" in d["source"]
    for cle, t in textes(d):
        assert not fautes(t), f"{nom} [{cle}] {fautes(t)} : {t[:100]}"
        assert not JUGEMENTS.search(t), f"{nom} [{cle}] jugement : {t[:100]}"
    brut = f.read_text(encoding="utf-8")
    assert "—" not in brut


@pytest.mark.parametrize("nom", ["budget.json", "effectifs.json", "amendes.json"])
def test_aucune_statistique_de_delinquance(nom):
    for cle, t in textes(_lire(nom)):
        t = re.sub(r"statistiques? de délinquance", " ", t)  # mention de l'exclusion du sujet
        assert not HORS_SUJET.search(t), f"{nom} [{cle}] : {t[:100]}"


def test_index_liste_les_fichiers_et_la_recherche_publique():
    d = _lire("index.json")
    assert [f["fichier"] for f in d["fichiers"]] == [f"securite_interieure/{n}" for n in FICHIERS[1:]]
    for f in d["fichiers"]:
        assert f["octets"] == (DATA / Path(f["fichier"]).name).stat().st_size
    verdicts = {t["verdict"] for t in d["recherche_publique"]["trouvailles"]}
    assert "réutilisable tel quel" in verdicts
    assert all(t["licence"] and t["mise_a_jour"] for t in d["recherche_publique"]["trouvailles"])
    assert d["sources_inaccessibles"]


# ---------------------------------------------------------------------------------------------------- budget

def test_quatre_programmes_dans_l_ordre(budget):
    assert [p["programme"] for p in budget["programmes"]] == ["176", "152", "161", "207"]


def test_nature_retombe_sur_l_execution(budget):
    for p in budget["programmes"]:
        for n, e in zip(p["nature"], p["execution"]):
            assert n["annee"] == e["annee"]
            somme = sum(t["eur"] for t in n["titres"])
            assert abs(somme - n["controle"]["somme_categories_eur"]) <= TOLERANCE
            for t in n["titres"]:
                assert abs(sum(c["eur"] for c in t["categories"]) - t["eur"]) <= TOLERANCE
                assert all(c["categorie"][0] == t["titre"] for c in t["categories"])
            assert abs(sum(t["part_pct"] for t in n["titres"]) - 100) < 0.1
            ecart = n["controle"]["ecart_eur"]
            assert ecart is not None and (abs(ecart) <= TOLERANCE or any(
                x["objet"] == f"programme {p['programme']}, dépenses {e['annee']}" for x in budget["ecarts"]))


def test_total_egal_personnel_plus_autres_titres(budget):
    for p in budget["programmes"]:
        for e in p["execution"]:
            parts = [x["depenses_constatees_eur"] for x in (e["personnel"], e["autres_titres"]) if x]
            assert abs(sum(parts) - e["total"]["depenses_constatees_eur"]) <= TOLERANCE


def test_programme_207_sans_titre_2_reste_null(budget):
    p = next(x for x in budget["programmes"] if x["programme"] == "207")
    assert all(e["personnel"] is None for e in p["execution"])


def test_actions_somme_des_sous_actions_et_lignes_techniques_a_part(budget):
    for p in budget["programmes"]:
        for a in p["actions"]:
            assert a["code"].startswith(p["programme"] + "-")
            for k in ("execution_2024_eur", "lfi_2025_eur", "plf_2026_eur"):
                vals = [s[k] for s in a["sous_actions"] if s[k] is not None]
                assert (a[k] is None) == (not vals)
                if vals:
                    assert abs(sum(vals) - a[k]) <= TOLERANCE
        for t in p["lignes_techniques_budget_vert"]:
            assert not re.fullmatch(r"\d{3}-\d{2}", t["code"])


def test_mission_calculee_et_securite_routiere_sans_total(budget):
    m = budget["mission"]
    assert m["statut"] == "calculé" and m["formule"]
    for a in m["annees"]:
        tot = sum(next(e for e in p["execution"] if e["annee"] == a["annee"])["total"]["depenses_constatees_eur"]
                  for p in budget["programmes"])
        assert abs(tot - a["depenses_constatees_eur"]) <= TOLERANCE
    sr = budget["securite_routiere"]
    assert "total" not in json.dumps(list(sr.keys())) and {x["programme"] for x in sr["lignes"]} == {"176", "152", "207", "751"}


# ---------------------------------------------------------------------------------------------------- amendes

def test_amendes_retombent_sur_la_situation_comptable(amendes):
    assert amendes["compte"] == "Contrôle de la circulation et du stationnement routiers"
    for a in amendes["annees"]:
        c = a["controles"]
        assert abs(c["ecart_recettes_eur"]) <= TOLERANCE and abs(c["ecart_depenses_eur"]) <= TOLERANCE
        s = a["situation"]
        # solde de sortie = solde d'entrée + recettes - dépenses
        assert abs(s["solde_entree_eur"] + s["recettes_eur"] - s["depenses_eur"] - s["solde_sortie_eur"]) <= TOLERANCE
        assert [d["programme"] for d in a["depenses"]] == ["751", "753", "754", "755"]
        assert abs(sum(d["part_depenses_pct"] for d in a["depenses"]) - 100) < 0.05
        assert sum(x["recouvrement_eur"] for x in a["recettes_par_section"]) == pytest.approx(a["recouvrements_total_eur"])


def test_soldes_enchaines_d_une_annee_a_l_autre(amendes):
    an = amendes["annees"]
    for a, b in zip(an, an[1:]):
        assert abs(a["situation"]["solde_sortie_eur"] - b["situation"]["solde_entree_eur"]) <= TOLERANCE


# ---------------------------------------------------------------------------------------------------- effectifs

def test_effectifs_votes_et_absences(effectifs):
    for p in effectifs["programmes"]:
        assert [x["annee"] for x in p["etpt_lfi"]] == effectifs["annees"]
        if p["programme"] == "207":
            assert all(x["etpt"] is None for x in p["etpt_lfi"])  # pas de plafond propre : null, jamais 0
        else:
            assert all(x["etpt"] and x["etpt"] > 0 for x in p["etpt_lfi"])
            cats = p["categories_lfi_2023"]
            assert abs(sum(c["etpt"] for c in cats) - p["etpt_lfi"][-1]["etpt"]) < 0.05


# ---------------------------------------------------------------------------------------------------- reproductibilité

@pytest.mark.skipif(not (LAKE / "securite_interieure_plrg_annexes").exists(),
                    reason="entrepôt data/lake/securite_interieure absent")
def test_deux_productions_identiques(tmp_path):
    empreintes = []
    for k in ("a", "b"):
        si.produire(tmp_path / k)
        empreintes.append({f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((tmp_path / k).iterdir())})
    assert empreintes[0] == empreintes[1]
