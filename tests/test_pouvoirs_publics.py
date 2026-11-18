"""Pouvoirs publics (pipeline/pouvoirs_publics.py) : fonctions de lecture et cohérence des fichiers publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "pouvoirs_publics"
sys.path.insert(0, str(ROOT / "pipeline"))
import pouvoirs_publics as pp  # noqa: E402


# --- fonctions pures ------------------------------------------------------------------------------------------------

def test_nombres_absents_jamais_zero():
    for v in (None, "", "N.D.", "nc", "-"):
        assert pp.nombre(v) is None
    assert pp.nombre("1 234,5") == 1234.5
    assert pp.nombre("– 33 404 831") == -33404831
    assert pp.nombre("+0,43") == 0.43
    assert pp.euros("127,7", "M€") == 127_700_000
    with pytest.raises(pp.LectureImpossible):
        pp.euros("N.D.", "M€")


def test_decoupage_des_colonnes_par_l_ecart_publie():
    # « 606 045 922 604 745 017 – 1 300 905 » : trois montants collés, un seul découpage vérifie b - a = écart
    assert pp.trois_montants("606 045 922 604 745 017 – 1 300 905".split()) == (606045922, 604745017, -1300905)
    assert pp.trois_montants("607 647 569 607 647 569 0".split()) == (607647569, 607647569, 0)
    assert pp.trois_montants("– 33 404 831 – 34 135 148 – 730 317".split()) == (-33404831, -34135148, -730317)
    with pytest.raises(pp.LectureImpossible):
        pp.trois_montants("1 2 3".split())
    assert pp.deux_egaux("122 563 852 122 563 852".split()) == 122563852
    with pytest.raises(pp.LectureImpossible):
        pp.deux_egaux("1 000 2 000".split())


def test_bareme_gouvernement_selon_les_decrets():
    d = {"coef_president_pm": 2.0, "coef_ministre": 1.4, "majoration_pct": 5.0, "coef_secretaire_etat": 1.33,
         "residence_pct": 3.0, "fonction_pct": 25.0}
    lignes = {l["fonction"]: l for l in pp.bareme_gouvernement(5931.95, d)}
    assert lignes["Président de la République"]["total_brut_mensuel_eur"] == pytest.approx(16038.5, abs=0.02)
    assert lignes["Premier ministre"]["total_brut_mensuel_eur"] == lignes["Président de la République"]["total_brut_mensuel_eur"]
    assert lignes["Ministre et ministre délégué"]["total_brut_mensuel_eur"] == pytest.approx(10692.34, abs=0.02)
    assert lignes["Secrétaire d'État"]["total_brut_mensuel_eur"] == pytest.approx(10157.71, abs=0.02)
    assert all(l["statut"] == "approché" for l in lignes.values())


def test_fusion_garde_les_ecarts_sans_trancher():
    v = pp.fusionner({("501", 2024, "lfi"): (1.0, "a")}, {("501", 2024, "lfi"): (2.0, "b")},
                     {("501", 2024, "lfi"): (1.0, "a")})
    assert v[("501", 2024, "lfi")] == [(1.0, "a"), (2.0, "b")]
    dot = pp.construire_dotations(v, "m", "2026-01-01")
    ligne = next(a for s in dot["series"] if s["programme"] == "501" for a in s["annees"] if a["annee"] == 2024)
    assert ligne["lfi_eur"] is None and len(dot["ecarts_entre_sources"]) == 1
    assert next(m for m in dot["mission"] if m["annee"] == 2024)["lfi_eur"] is None


# --- fichiers publiés -----------------------------------------------------------------------------------------------

def _charger(nom):
    p = DOSSIER / nom
    if not p.exists():
        pytest.skip(f"{p} absent (lancer python pipeline/pouvoirs_publics.py produire)")
    return json.loads(p.read_text(encoding="utf-8"))


def test_entetes_et_taille():
    for nom in ("index.json", "dotations.json", "budgets_institutions.json", "indemnites.json"):
        d = _charger(nom)
        assert d["millesime"] and "http" in d["source"] and d["collecte_le"]
        assert (DOSSIER / nom).stat().st_size < 5_000_000


def test_total_mission_egal_somme_des_programmes():
    d = _charger("dotations.json")
    for m in d["mission"]:
        for nature in d["natures"]:
            total = m[f"{nature}_eur"]
            if total is None:
                continue
            somme = sum(a[f"{nature}_eur"] or 0 for s in d["series"] for a in s["annees"] if a["annee"] == m["annee"])
            assert total == pytest.approx(somme, abs=0.5), (m["annee"], nature)
    # repères publiés par le projet annuel de performances 2026 (récapitulation des crédits, « Totaux »)
    par_annee = {m["annee"]: m for m in d["mission"]}
    assert par_annee[2025]["lfi_eur"] == 1_137_842_143
    assert par_annee[2026]["plf_eur"] == 1_140_179_221


def test_chaque_valeur_a_sa_source_et_null_si_absente():
    d = _charger("dotations.json")
    for s in d["series"]:
        for a in s["annees"]:
            for nature in d["natures"]:
                if a[f"{nature}_eur"] is not None:
                    assert a[f"{nature}_sources"], (s["programme"], a["annee"], nature)
    # Assemblée nationale 2024 : dotation complémentaire de fin de gestion comprise dans la dépense constatée
    an = next(s for s in d["series"] if s["programme"] == "511")
    a24 = next(a for a in an["annees"] if a["annee"] == 2024)
    assert a24["lfi_eur"] == 607_647_569 and a24["execution_eur"] == 627_181_842


def test_budgets_lus_et_controles():
    d = _charger("budgets_institutions.json")
    assert all(c["ok"] for c in d["controles"]) and len(d["controles"]) >= 5
    ids = [f["id"] for f in d["faits"]]
    assert len(ids) == len(set(ids))
    for f in d["faits"]:
        assert f["institution"] in d["institutions"] and f["grandeur"] in d["grandeurs"]
        assert "page" in f["source"] and f["extrait"]
    v = {f["id"]: f["valeur_eur"] for f in d["faits"]}
    assert v["an_2026_depenses_totales"] == 644_010_717 and v["senat_2026_depenses"] == 382_279_387


def test_indemnites_par_fonction_sans_personne():
    d = _charger("indemnites.json")
    dep = {l["element"]: l for l in d["parlementaires"] if l["fonction"] == "Député"}
    composantes = sum(dep[k]["montant_brut_mensuel_eur"] for k in (
        "indemnité parlementaire de base", "indemnité de résidence (3 %)", "indemnité de fonction (25 %)"))
    assert dep["total brut mensuel"]["montant_brut_mensuel_eur"] == pytest.approx(composantes, abs=0.02)
    assert d["moyenne_hors_echelle_mensuelle_eur"] == dep["indemnité parlementaire de base"]["montant_brut_mensuel_eur"]
    assert {g["fonction"] for g in d["gouvernement"]} == {"Président de la République", "Premier ministre",
                                                          "Ministre et ministre délégué", "Secrétaire d'État"}
    # le barème des élus locaux reste dans fonction_publique/ : renvoi, jamais recopie
    assert d["elus_locaux"] is None or ("lignes" not in d["elus_locaux"]
                                        and d["elus_locaux"]["fichier"] == "fonction_publique/indemnites_elus.json")
    texte = json.dumps(d, ensure_ascii=False)
    for cle in ('"nom"', '"prenom"', '"titulaire"'):
        assert cle not in texte


def test_index_recherche_prealable_et_reperes():
    d = _charger("index.json")
    assert {r["classement"] for r in d["recherche_prealable"]} <= {"réutilisable tel quel", "à adapter",
                                                                   "inspiration seulement"}
    assert d["reperes"]["president_statut"] == "approché"
    assert [f["fichier"] for f in d["fichiers"]] == ["pouvoirs_publics/dotations.json",
                                                     "pouvoirs_publics/budgets_institutions.json",
                                                     "pouvoirs_publics/indemnites.json"]
