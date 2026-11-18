"""Séries longues des impôts locaux par commune (pipeline/fiscalite_locale_series.py) : contrat, non-duplication de
local/taux, cohérence des totaux, neutralité, reproductibilité.

Les tests sur site/data/fiscalite_locale_series tournent sans réseau ni entrepôt ; la reproductibilité demande les
extraits REI (data/lake/fiscalite_locale_series/extraits), sautée sinon.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "fiscalite_locale_series"
LOCAL = ROOT / "site" / "data" / "local" / "taux"
EXTRAITS = ROOT / "data" / "lake" / "fiscalite_locale_series" / "extraits"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "pipeline"))
from test_neutralite import fautes, textes  # noqa: E402

import fiscalite_locale_series as fls  # noqa: E402


@functools.lru_cache(maxsize=None)
def _lire(rel: str) -> dict:
    return json.loads((DATA / rel).read_text(encoding="utf-8"))


def _dep(groupe: str, dep: str) -> dict:
    """Fichier d'un département, parties réunies (communes dans l'ordre des codes)."""
    index = _lire("index.json")
    d = next(x for x in index["departements"] if x["departement"] == dep)
    parts = [_lire(p["fichier"]) for p in d[groupe]]
    out = dict(parts[0])
    out["communes"] = {k: v for p in parts for k, v in p["communes"].items()}
    return out


@pytest.fixture(scope="module")
def index():
    return _lire("index.json")


def test_annees_depuis_2010_consecutives(index):
    a = index["annees"]
    assert a[0] == 2010 and a == list(range(a[0], a[-1] + 1)) and a[-1] >= 2024
    assert [s["annee"] for s in index["sources_par_annee"]] == a
    assert set(index["communes_par_annee"]) == {str(x) for x in a}
    for s in index["sources_par_annee"]:
        assert s["url"].startswith("https://data.economie.gouv.fr/") and len(s["sha256"]) == 64


def test_fichiers_departements_complets_et_legers(index):
    deps = [d["departement"] for d in index["departements"]]
    assert deps == sorted(deps) and len(deps) >= 100 and {"2A", "2B", "971", "974", "75"} <= set(deps)
    publies = set()
    for d in index["departements"]:
        for groupe in ("taux", "produits"):
            n = 0
            for part in d[groupe]:
                p = DATA / part["fichier"]
                assert p.stat().st_size < 1_000_000, p
                codes = list(json.loads(p.read_text(encoding="utf-8"))["communes"])
                assert codes[0] == part["premiere_commune"] and codes[-1] == part["derniere_commune"]
                n += len(codes)
                publies.add(part["fichier"])
            assert n == d["communes"], (d["departement"], groupe)
    assert publies == {str(p.relative_to(DATA)) for p in DATA.glob("*/*.json")}


def test_series_alignees_sur_les_annees(index):
    n = len(index["annees"])
    cles = {g: {v["cle"] for v in index["variables"][g]} for g in ("taux", "produits")}
    for groupe in ("taux", "produits"):
        for d in ("44", "2A", "974"):
            f = _dep(groupe, d)
            assert f["annees"] == index["annees"] and f["millesime"] and f["source"]
            assert f["unite"] == ("%" if groupe == "taux" else "euros")
            for code, c in f["communes"].items():
                assert fls.departement(code) == d
                assert set(c["series"]) <= cles[groupe]
                for s in c["series"].values():
                    assert len(s) == n and any(v is not None for v in s)


def test_part_departementale_du_foncier_bati_jusqu_en_2020(index):
    i2021 = index["annees"].index(2021)
    for groupe in ("taux", "produits"):
        f = _dep(groupe, "44")
        nantes = f["communes"]["44109"]["series"]
        assert nantes["tfb_departement"][i2021 - 1] is not None
        assert all(v is None for v in nantes["tfb_departement"][i2021:])
    prod = _dep("produits", "44")["communes"]["44109"]["series"]
    assert prod["tfb_commune"][i2021] > prod["tfb_commune"][i2021 - 1]


def test_pas_de_doublon_avec_local_taux(index):
    """Un taux publié (non nul) dans local/taux/<dep>.json pour un exercice vaut null ici."""
    col = index["complement_local_taux"]["colonnes"]
    rang = {a: i for i, a in enumerate(index["annees"])}
    controles = 0
    for d in ("44", "75", "971"):
        p = LOCAL / f"{d}.json"
        if not p.exists():
            continue
        lt = json.loads(p.read_text(encoding="utf-8"))
        f = _dep("taux", d)
        assert f["complement_local_taux"]["fichier"] == f"local/taux/{d}.json"
        ex = f["complement_local_taux"]["exercices"]
        assert ex == [int(e) for e in lt["exercices"] if int(e) in rang]
        for code, c in f["communes"].items():
            lc = lt["communes"].get(code, {})
            for k, kl in col.items():
                j = lt["colonnes"].index(kl)
                for e in ex:
                    lv = (lc.get(str(e)) or [None] * (j + 1))[j]
                    if lv is not None and k in c["series"]:
                        assert c["series"][k][rang[e]] is None, (d, code, k, e)
                        controles += 1
    assert controles > 0
    e = index["complement_local_taux"]["ecarts_taux_nets_votes"]
    assert e["comparaisons"] == e["egales"] + e["differentes"]


def test_produits_et_autres_taux_publies_sur_toute_la_periode(index):
    f = _dep("produits", "44")["communes"]["44109"]["series"]
    assert all(v is not None for v in f["tfb_commune"])
    assert f["cfe_intercommunalite_unique"][-1] > 0
    t = _dep("taux", "44")["communes"]["44109"]["series"]
    assert t["cfe_intercommunalite_unique"][-1] is not None  # absent de local/taux : publié tous les exercices


def test_totaux_nationaux_egaux_a_la_somme_des_fichiers(index):
    tot = index["totaux_nationaux_produits"]["series"]
    for k in ("tfb_commune", "cfe_intercommunalite_unique"):
        for i in (0, len(index["annees"]) - 1):
            s = 0
            for d in index["departements"]:
                for c in _dep("produits", d["departement"])["communes"].values():
                    v = c["series"].get(k, [None] * (i + 1))[i]
                    s += v or 0
            assert s == tot[k][i], (k, index["annees"][i])


def test_codes_rei_par_annee(index):
    th = index["codes_rei"]["produits"]["th_commune"]
    assert th["2015"] == "H13" and th[str(index["annees"][-1])] == "H13THS"
    assert index["codes_rei"]["taux"]["tfb_departement"]["2020"] == "E42"
    assert index["codes_rei"]["taux"]["tfb_departement"]["2022"] is None


def test_recherche_publique_classee(index):
    for t in index["recherche_publique"]["trouvailles"]:
        assert t["verdict"] in {"réutilisable tel quel", "à adapter", "inspiration seulement"}
        assert t["licence"] and t["mise_a_jour"]


def test_neutralite_textes():
    erreurs = []
    for f in [DATA / "index.json", *sorted(DATA.glob("*/44*.json"))]:
        doc = json.loads(f.read_text(encoding="utf-8"))
        for cle, t in textes(doc):
            erreurs += [f"{f.name} [{cle}] {r}" for r in fautes(t)]
        assert "—" not in f.read_text(encoding="utf-8")
    assert not erreurs, "\n".join(erreurs[:20])


def test_aides_code_commune_et_teom():
    assert fls.insee({"DEP": "44", "COM": "109"}) == "44109"
    assert fls.insee({"DEP": "2A", "COM": "1"}) == "2A001"
    assert fls.insee({"DEP": "971", "COM": "01"}) == "97101"
    assert fls.insee({"DEP": "01", "COM": "1", "IDCOM": "01001"}) == "01001"
    assert fls.departement("97411") == "974" and fls.departement("2B033") == "2B"
    r = {"F23": "10", "F33": "5", "F43": "", "F22": "8.5"}
    assert fls._valeur(r, ["F13", "F23"], somme_teom=True) == 15
    assert fls._valeur({"F13": "", "F23": "3"}, ["F13", "F23"]) is None
    assert fls._valeur({"E12": "8.7899999999999991"}, ["E12"]) == pytest.approx(8.79)
    assert fls._arrondi(8.7899999999999991, True) == 8.79 and fls._arrondi(12.0, True) == 12


@pytest.mark.skipif(not (EXTRAITS / "rei_2010.csv.gz").exists(), reason="extraits REI absents de data/lake")
def test_produire_reproductible_et_identique_au_depot(tmp_path):
    empreintes = []
    for graine, sortie in (("1", tmp_path / "a"), ("2", tmp_path / "b")):
        env = {**{k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}, "PYTHONHASHSEED": graine}
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "fiscalite_locale_series.py"), "produire",
                            "--sortie", str(sortie)], capture_output=True, text=True, env=env, timeout=600)
        assert r.returncode == 0, r.stderr[-2000:]
        empreintes.append({str(f.relative_to(sortie)): hashlib.sha256(f.read_bytes()).hexdigest()
                           for f in sorted(sortie.rglob("*.json"))})
    assert empreintes[0] == empreintes[1]
    depot = {str(f.relative_to(DATA)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(DATA.rglob("*.json"))}
    assert empreintes[0] == depot
