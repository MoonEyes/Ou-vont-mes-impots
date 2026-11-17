"""Tests sans réseau du bloc « Ce qui a été fait » (site/data/realisations/).

Ils lisent les fichiers produits par `python pipeline/realisations.py produire` et testent les règles du module.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import realisations as R  # noqa: E402

DOSSIER = ROOT / "site" / "data" / "realisations"
FICHIERS = sorted(DOSSIER.glob("[0-9]*.json"))
TENDANCES = {R.SENS_PUBLIE, R.SENS_INVERSE, "stable", "sens inconnu"}


def _json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tous():
    assert FICHIERS, "site/data/realisations/ vide : lancer `python pipeline/realisations.py produire`"
    return [(f, _json(f)) for f in FICHIERS]


# --- Métadonnées -----------------------------------------------------------------------------------------------------


def test_millesime_source_avertissement(tous):
    for f, d in tous + [(DOSSIER / "index.json", _json(DOSSIER / "index.json"))]:
        assert d.get("millesime"), f
        assert d.get("source"), f
        assert d.get("avertissement") == R.AVERTISSEMENT, f
    assert R.AVERTISSEMENT == ("Les indicateurs sont choisis par l'administration ; une évolution ne prouve pas l'effet "
                               "de la dépense.")


def test_taille_et_index(tous):
    idx = _json(DOSSIER / "index.json")
    assert sorted(idx["programmes"]) == sorted(d["programme"] for _, d in tous)
    for f, _ in tous:
        assert f.stat().st_size < 5_000_000, f


# --- 1. Prévu / dépensé ---------------------------------------------------------------------------------------------


def test_ecart_egal_depense_moins_vote(tous):
    n = 0
    for f, d in tous:
        for a in d["prevu_depense"]["annees"]:
            vote, dep = a["vote_lfi_eur"], a["depense_constatee_eur"]
            if vote is None or dep is None:
                assert a["ecart_eur"] is None and a["ecart_pct"] is None, (f, a["annee"])
                continue
            assert a["ecart_eur"] == round(dep - vote, 2), (f, a["annee"])
            if vote:
                assert a["ecart_pct"] == round((dep - vote) / vote * 100, 2), (f, a["annee"])
            n += 1
    assert n > 500


def test_annee_2024_et_trous_signales(tous):
    avec_2024 = 0
    for f, d in tous:
        annees = {a["annee"]: a for a in d["prevu_depense"]["annees"]}
        if 2024 in annees and annees[2024]["depense_constatee_eur"] is not None:
            avec_2024 += 1
            assert annees[2024]["source"].startswith("data.economie.gouv.fr/plrg-2024"), f
            assert annees[2024]["ouvert_en_gestion"]["total_eur"] is not None, f
        if annees:
            assert annees.get(2021, {}).get("trou"), f  # le trou 2021 est signalé, pas masqué
        for a in annees.values():
            assert a.get("trou") or a["source"], (f, a["annee"])
    assert avec_2024 >= 120


def test_programme_141_2024():
    d = _json(DOSSIER / "141.json")
    a = next(x for x in d["prevu_depense"]["annees"] if x["annee"] == 2024)
    assert d["libelle"] == "Enseignement scolaire public du second degré"
    assert 35e9 < a["depense_constatee_eur"] < 42e9
    assert 35e9 < a["vote_lfi_eur"] < 42e9


# --- 2. Résultats mesurés -------------------------------------------------------------------------------------------


def test_aucun_sens_sans_justification_de_source(tous):
    vus = 0
    for f, d in tous:
        for i in d["resultats_mesures"]["indicateurs"]:
            t, s = i["tendance"], i["sens_souhaite"]
            assert t["valeur"] in TENDANCES, (f, i["id"])
            if t["valeur"] not in (R.SENS_PUBLIE, R.SENS_INVERSE):
                continue
            vus += 1
            assert s["valeur"] in ("hausse", "baisse"), (f, i["id"])
            assert s["methode"] in ("colonne evolution", "position des cibles"), (f, i["id"])
            assert s["source"].startswith("data.economie.gouv.fr/"), (f, i["id"])
            assert s["justification"], (f, i["id"])
            assert t["justification"]["sens_souhaite"] == s["valeur"], (f, i["id"])
            if s["methode"] == "position des cibles":
                assert s["comparaisons"] and {c["sens"] for c in s["comparaisons"]} == {s["valeur"]}, (f, i["id"])
            hausse = t["variation"] > 0
            assert (t["valeur"] == R.SENS_PUBLIE) == (hausse == (s["valeur"] == "hausse")), (f, i["id"])
    assert vus > 100


def test_valeurs_brutes_conservees(tous):
    for f, d in tous:
        for i in d["resultats_mesures"]["indicateurs"]:
            for v in i["valeurs"] + i["cibles"]:
                assert v["brut"] is not None, (f, i["id"])
                assert v["source"], (f, i["id"])
            for e in i["ecarts_a_la_cible"]:
                assert e["ecart"] == round(e["realise"] - e["cible"], 6), (f, i["id"])


@pytest.mark.parametrize("brut,attendu", [
    ("1 234,5", 1234.5), ("21 883 082", 21883082.0), ("26 500 000", 26500000.0), ("72,7", 72.7),
    ("74.5", 74.5), ("83,6 (± 2,19)", 83.6), ("12 %", 12.0), (64555.0, 64555.0), ("-0,6", -0.6),
    ("nd", None), ("n.d", None), ("Sans objet", None), ("s.o.", None), ("Non déterminé", None), ("entre 5 et 10", None),
])
def test_nettoyage_valeurs(brut, attendu):
    v, b = R.valeur(brut)
    assert v == attendu
    assert b is not None


def _serie(realises, cibles=None, evolution=None):
    return {"id": "999-1", "code": None, "evolution": evolution,
            "realises": {a: {"valeur": v, "brut": str(v), "source": "rap2025"} for a, v in realises.items()},
            "cibles": {a: {"valeur": v, "brut": str(v), "source": "pap2025"} for a, v in (cibles or {}).items()}}


def test_sens_inconnu_sans_donnee():
    s = _serie({2023: 10.0, 2024: 20.0})
    sens = R.sens_souhaite(s)
    assert sens["valeur"] == "inconnu"
    assert R.tendance(s, sens)["valeur"] == "sens inconnu"


def test_sens_par_cibles_contradictoires_inconnu():
    s = _serie({2022: 10.0, 2023: 20.0}, {2023: 15.0, 2024: 18.0})  # 2023 : au-dessus ; 2024 : en dessous
    assert R.sens_souhaite(s)["valeur"] == "inconnu"


def test_sens_par_colonne_evolution_et_stabilite():
    s = _serie({2023: 10.0, 2024: 8.0}, evolution="Baisse")
    sens = R.sens_souhaite(s)
    assert sens["valeur"] == "baisse" and sens["methode"] == "colonne evolution"
    assert R.tendance(s, sens)["valeur"] == R.SENS_PUBLIE
    s = _serie({2023: 10.0, 2024: 12.0}, evolution="Stabilité")
    assert R.tendance(s, R.sens_souhaite(s))["valeur"] == "sens inconnu"
    s = _serie({2023: 100.0, 2024: 100.5}, evolution="Hausse")
    assert R.tendance(s, R.sens_souhaite(s))["valeur"] == "stable"


# --- 3. Réalisations concrètes --------------------------------------------------------------------------------------


def test_realisations_courtes_et_renvoi(tous):
    for f, d in tous:
        r = d["realisations_concretes"]
        assert len(r["liste"]) <= R.MAX_REALISATIONS, f
        montants = [x["montant_eur"] for x in r["liste"]]
        assert montants == sorted(montants, reverse=True), f
        if r["liste"]:
            assert (ROOT / "site" / "data" / r["fichier_beneficiaires"]).exists(), f
        if r["france2030"]:
            assert r["france2030"]["fichier"] == "beneficiaires/france2030.json"


# --- 4. Évaluations ---------------------------------------------------------------------------------------------------


def test_aucun_lien_non_verifie(tous):
    n = 0
    for f, d in tous:
        ev = d["evaluations"]
        if not ev["liens"]:
            assert ev["note"], f  # champ vide et signalé
        for l in ev["liens"]:
            n += 1
            assert l["verifie"] is True, (f, l["url"])
            assert l["statut_http"] == 200 and l["verifie_le"], (f, l["url"])
            assert l["url"].startswith("https://www.ccomptes.fr/"), (f, l["url"])
            if l["type"].startswith("note d'exécution"):
                assert R.norm(R.sans_annee(l["titre_publie"])) == R.norm(d["mission"]), (f, l["url"])
    assert n > 500
