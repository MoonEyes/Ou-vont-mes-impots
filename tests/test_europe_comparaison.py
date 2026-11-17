"""La France et ses voisins (pipeline/europe_comparaison.py) : contrat, neutralité, cohérence des fiches.

Les tests sur site/data/comparaison tournent sans réseau ni entrepôt ; la reproductibilité et la vérification des
citations Eurostat demandent l'entrepôt (data/lake/europe/eu_comparaison_*), sautées sinon.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "comparaison"
LAKE = ROOT / "data" / "lake" / "europe"
sys.path.insert(0, str(ROOT / "tests"))
from test_neutralite import fautes, textes  # noqa: E402

PAYS_UE = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE", "IT", "LT", "LU",
           "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"}
POSTES = {"sante", "retraites", "education", "defense", "ordre_public", "transports", "logement", "environnement",
          "interets_dette"}
# Jugements de niveau propres à une comparaison entre pays (en plus du lexique partagé).
JUGEMENTS = re.compile(r"(?<!\w)(?:pas assez|trop|insuffisan\w*|excessi\w*|meilleur\w*|pire\w*|retard\w*|en avance|"
                       r"champion\w*|lanterne|bon élève|mauvais élève|à la traîne|dérive\w*|vert|rouge)(?!\w)", re.I)


def _lire(rel: str) -> dict:
    return json.loads((DATA / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index():
    return _lire("index.json")


@pytest.fixture(scope="module")
def fiches():
    return _lire("fiches.json")


def test_pays_complets_et_ordre_alphabetique(index):
    pays = index["pays"]
    assert {p["geo"] for p in pays} == PAYS_UE
    assert [p["nom_tri"] for p in pays] == sorted(p["nom_tri"] for p in pays)
    assert index["ordre"]["cles"] == ["nom_tri"] and "alphabétique" in index["ordre"]["regle"]
    assert {a["geo"] for a in index["agregats"]} == {"EU27_2020", "EA20"}


def test_series_depenses_couvrent_2000_et_tous_les_pays(index):
    assert len(index["depenses"]["fichiers"]) == 11  # TOTAL + 10 divisions
    for f in index["depenses"]["fichiers"]:
        d = json.loads((ROOT / "site" / "data" / f["fichier"]).read_text(encoding="utf-8"))
        assert d["annees"][0] == 2000
        assert set(d["series"]) == PAYS_UE | {"EU27_2020", "EA20"}
        for g, codes in d["series"].items():
            for c, s in codes.items():
                assert len(s["pct_pib"]) == len(s["part_total"]) == len(s["eur_hab"]) == len(d["annees"]), (g, c)
    assert index["depenses"]["controle_somme_divisions"]["ecart_max_pct_du_total"] < 0.5


def test_prelevements_identite_et_parts(index):
    p = _lire("prelevements.json")
    assert p["annees"][0] == 2000 and p["identite"]["ecart_max_pct_du_total"] < 0.5
    total = p["categories"][0]["code"]
    fr = p["series"]["FR"]
    i = len(p["annees"]) - 1
    assert fr[total]["part_total"][i] == 100.0
    somme = sum(c["signe"] * fr[c["code"]]["part_total"][i] for c in p["categories"] if c["signe"])
    assert abs(somme - 100) < 0.1


def test_fiches_grands_postes_coherentes(fiches):
    assert {f["id"] for f in fiches["fiches"] if f["type"] == "depense"} == POSTES
    assert fiches["ordre"]["cles"] == ["-pct_pib", "nom_tri"]
    for f in fiches["fiches"]:
        vals = [p["pct_pib"] for p in f["pays_par_valeur"]]
        assert vals == sorted(vals, reverse=True), f["id"]
        assert len(vals) == f["rang_sur"] == f["pays_publies"] >= 25
        assert f["mediane_ue_pct_pib"] == pytest.approx(statistics.median(vals), abs=0.01)
        fr = f["france"]["pct_pib"]
        assert f["rang"] == 1 + sum(v > fr for v in vals)
        assert f["ecart_mediane_points_pib"] == pytest.approx(fr - f["mediane_ue_pct_pib"], abs=0.011)
        assert f["evolution_10_ans"]["annee_arrivee"] - f["evolution_10_ans"]["annee_depart"] == 10
        assert f["avertissements"], f["id"]


def test_avertissements_eurostat_cites_et_relies(index, fiches):
    ids = {a["id"] for a in index["avertissements"]}
    themes = {a["theme"] for a in index["avertissements"]}
    assert {"périmètres", "prestations fiscalisées", "systèmes de retraite"} <= themes
    for a in index["avertissements"]:
        assert a["source"]["url"].startswith("https://ec.europa.eu/eurostat/")
        assert len(a["citation"]) > 40
    for f in fiches["fiches"]:
        assert set(f["avertissements"]) <= ids, f["id"]
    v = index["verification_documents"]
    assert v["citations"] == v["retrouvees"] == len(index["avertissements"])


def test_recherche_publique_classee(index):
    for t in index["recherche_publique"]["trouvailles"]:
        assert t["verdict"] in {"réutilisable tel quel", "à adapter", "inspiration seulement"}
        assert t["licence"] and t["mise_a_jour"]


def test_neutralite_libelles_comparaison():
    erreurs = []
    for f in sorted(DATA.rglob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        for cle, t in textes(doc):
            erreurs += [f"{f.name} [{cle}] {r}" for r in fautes(t)]
        # tous les textes rédigés en français par le pipeline (citations Eurostat exclues, en anglais)
        for t in _textes_francais(doc):
            if JUGEMENTS.search(t):
                erreurs.append(f"{f.name} jugement de niveau : {t[:120]}")
    assert not erreurs, "\n".join(erreurs[:20])


def _textes_francais(x, cle=None):
    if isinstance(x, dict):
        for k, v in x.items():
            if k not in ("citation", "series", "statuts", "pays_par_valeur", "url", "nom", "geo", "nom_tri", "code"):
                yield from _textes_francais(v, k)
    elif isinstance(x, list):
        for v in x:
            yield from _textes_francais(v, cle)
    elif isinstance(x, str):
        yield x


@pytest.mark.skipif(not (LAKE / "eu_comparaison_cofog_pib.json").exists(), reason="entrepôt data/lake absent")
def test_produire_reproductible_et_identique_au_depot(tmp_path):
    empreintes = []
    for graine, sortie in (("1", tmp_path / "a"), ("2", tmp_path / "b")):
        env = {**{k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}, "PYTHONHASHSEED": graine}
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "europe_comparaison.py"), "produire",
                            "--sortie", str(sortie)], capture_output=True, text=True, env=env, timeout=300)
        assert r.returncode == 0, r.stderr[-2000:]
        empreintes.append({str(f.relative_to(sortie)): hashlib.sha256(f.read_bytes()).hexdigest()
                           for f in sorted(sortie.rglob("*.json"))})
    assert empreintes[0] == empreintes[1]
