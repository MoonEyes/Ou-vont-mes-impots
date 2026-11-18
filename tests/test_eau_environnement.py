"""Eau et environnement (pipeline/eau_environnement.py) : contrat, contrôles des tableaux, confidentialité, neutralité.

Les tests sur site/data/eau_environnement tournent sans réseau ni entrepôt ; la reproductibilité demande l'entrepôt
(data/lake/eau_environnement/ et data/lake/_restreint/subventions/), sautée sinon.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "data"
DATA = SITE / "eau_environnement"
LAKE = ROOT / "data" / "lake"
sys.path.insert(0, str(ROOT / "tests"))
from test_neutralite import fautes, textes  # noqa: E402

AGENCES = {"ensemble", "adour_garonne", "artois_picardie", "loire_bretagne", "rhin_meuse", "rhone_mediterranee_corse",
           "seine_normandie"}


def _lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def agences():
    return _lire("agences_eau.json")


@pytest.fixture(scope="module")
def ademe():
    return _lire("ademe.json")


@pytest.fixture(scope="module")
def fonds_vert():
    return _lire("fonds_vert.json")


def _ligne(agence: dict, rid: str) -> dict:
    return next(l for l in agence["redevances"]["lignes"] if l["id"] == rid)


def test_sept_entrees_et_annees(agences):
    assert {a["id"] for a in agences["agences"]} == AGENCES
    for a in agences["agences"]:
        assert a["redevances"]["annees"][0] == 2019 and a["redevances"]["annees"][-1] >= 2024
        assert a["autorisations_engagement"]["annees"] == a["redevances"]["annees"]


def test_controles_des_tableaux_dans_l_arrondi(agences):
    assert len(agences["controles"]) >= 7 * 6 * 3
    for c in agences["controles"]:
        assert c["ecart_meur"] is not None and abs(c["ecart_meur"]) <= 0.3, c


def test_identites_des_redevances(agences):
    for a in agences["agences"]:
        cats = [l for l in a["redevances"]["lignes"] if l["niveau"] == "categorie"]
        for an in a["redevances"]["annees"]:
            s = sum(l["valeurs_meur"][str(an)] or 0 for l in cats)
            assert abs(s - _ligne(a, "redevances_encaissees")["valeurs_meur"][str(an)]) <= 0.3, (a["id"], an)
        assert a["ecretement_meur"] == _ligne(a, "ecretement")["valeurs_meur"]


def test_somme_des_six_agences_proche_de_la_synthese(agences):
    assert agences["somme_six_agences"]
    for s in agences["somme_six_agences"]:
        assert abs(s["ecart_meur"]) <= 0.5, s


def test_chiffres_repere_2024(agences):
    ens = next(a for a in agences["agences"] if a["id"] == "ensemble")
    assert _ligne(ens, "redevances_encaissees")["valeurs_meur"]["2024"] == pytest.approx(2315.8)
    assert _ligne(ens, "fiscalite_affectee")["valeurs_meur"]["2024"] == pytest.approx(2317.1)
    assert ens["ecretement_meur"]["2019"] == pytest.approx(45.1)
    assert ens["ecretement_meur"]["2024"] is None   # cellule vide : null, jamais 0
    assert agences["plafond_redevances"]["valeurs_meur"]["2024"] == pytest.approx(2347.62)
    assert "article 46" in agences["plafond_redevances"]["citation"]


def test_editions_comparees(agences):
    assert agences["valeurs_comparees_editions"] > 1000
    for e in agences["ecarts_editions"]:
        assert abs(e["ecart_meur"]) >= 0.05 and e["annee"] <= 2023


def test_ademe_sommes(ademe):
    t = ademe["total"]["montant_eur"]
    assert sum(x["montant_eur"] for x in ademe["par_annee"]) == pytest.approx(t, abs=1)
    assert sum(r["montant_eur"] for r in ademe["par_region"]) + ademe["non_localise"]["montant_eur"] \
        == pytest.approx(t, abs=1)
    assert sum(d["montant_eur"] for d in ademe["par_dispositif"]) + ademe["par_dispositif_autres"]["montant_eur"] \
        == pytest.approx(t, abs=1)
    assert all(d["conventions"] >= 3 for d in ademe["par_dispositif"])
    assert [r["region"] for r in ademe["par_region"]] == sorted(r["region"] for r in ademe["par_region"])
    for f in ademe["fonds_nommes"]:
        assert f["dispositifs"] and f["montant_eur"] <= t


def test_fonds_vert_sommes_et_comparaison(fonds_vert):
    t = fonds_vert["total"]["montant_eur"]
    assert sum(x["montant_eur"] for x in fonds_vert["par_annee"]) == pytest.approx(t, abs=1)
    assert sum(r["montant_eur"] for r in fonds_vert["par_region"]) + fonds_vert["region_non_publiee"]["montant_eur"] \
        == pytest.approx(t, abs=1)
    for x in fonds_vert["par_instructeur"]:
        s = x["non_renseigne"]["montant_eur"] + sum(i["montant_eur"] for i in x["instructeurs"])
        ref = sum(y["montant_eur"] for y in fonds_vert["par_annee"] if y["annee"] == x["annee"])
        assert s == pytest.approx(ref, abs=1)
    for c in fonds_vert["agences_eau"]["comparaison"]:
        assert c["liste_fonds_vert_eur"] != 0      # aucun projet : null, pas 0
        if not c["colonne_operateur_publiee"]:
            assert c["liste_projets"] is None
    assert (SITE / fonds_vert["laureats"]["fichier"]).exists()


def test_aucun_beneficiaire_nomme():
    interdit = {"siren", "siret", "denomination", "nom_beneficiaire", "raison_sociale", "beneficiaire", "top"}
    for f in sorted(DATA.glob("*.json")):
        pile = [json.loads(f.read_text(encoding="utf-8"))]
        while pile:
            x = pile.pop()
            if isinstance(x, dict):
                assert not interdit & set(x), f"{f.name} : {interdit & set(x)}"
                pile += list(x.values())
            elif isinstance(x, list):
                pile += x


def test_liens_vers_les_autres_vues():
    idx = _lire("index.json")
    for l in idx["liens"]:
        assert (SITE / l["fichier"]).exists(), l["fichier"]
    for t in idx["recherche_publique"]["trouvailles"]:
        assert t["verdict"].startswith(("réutilisable tel quel", "à adapter", "inspiration seulement",
                                        "aucun dépôt pertinent"))


def test_neutralite_et_redaction():
    erreurs = []
    for f in sorted(DATA.glob("*.json")):
        texte = f.read_text(encoding="utf-8")
        assert "\u2014" not in texte, f"tiret long dans {f.name}"
        for cle, t in textes(json.loads(texte)):
            erreurs += [f"{f.name} [{cle}] {r}" for r in fautes(t)]
    assert not erreurs, "\n".join(erreurs[:20])


@pytest.mark.skipif(not (LAKE / "eau_environnement" / "eau_jaune_agences_eau_plf2026.pdf").exists()
                    or not (LAKE / "_restreint" / "subventions" / "subv_ademe_aides.csv").exists(),
                    reason="entrepôt data/lake absent")
def test_produire_reproductible_et_identique_au_depot(tmp_path):
    empreintes = []
    for graine, sortie in (("1", tmp_path / "a"), ("2", tmp_path / "b")):
        env = {**{k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}, "PYTHONHASHSEED": graine}
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "eau_environnement.py"), "produire",
                            "--sortie", str(sortie)], capture_output=True, text=True, env=env, timeout=300)
        assert r.returncode == 0, r.stderr[-2000:]
        empreintes.append({f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(sortie.glob("*.json"))})
    assert empreintes[0] == empreintes[1]
    depot = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(DATA.glob("*.json"))}
    assert empreintes[0] == depot
