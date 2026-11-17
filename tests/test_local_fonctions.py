"""Tests sans reseau des depenses par fonction (site/data/local/fonctions/, pipeline/local_fonctions.py)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import local_fonctions as lf  # noqa: E402

DOSSIER = ROOT / "site" / "data" / "local" / "fonctions"
FICHIERS = sorted(DOSSIER.glob("*.json"))
produit = pytest.mark.skipif(not (DOSSIER / "index.json").exists(), reason="site/data/local/fonctions absent")


def _json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


# --- Fonctions pures --------------------------------------------------------------------------------------------------


def test_code_fonction_budgets_votes_par_fonction():
    assert lf.code_fonction("93222", "M57") == "222"      # fonctionnement ventile, fonction 222
    assert lf.code_fonction("90844", "M57") == "844"      # investissement ventile, voirie
    assert lf.code_fonction("923", "M57") == "01"         # operations non ventilees
    assert lf.code_fonction("943", "M71") == "01"
    assert lf.code_fonction("212", "M57") == "212"
    assert lf.code_fonction("93", "M57") == "93"          # code court : laisse tel quel
    assert lf.code_fonction("953", "M14") == "953"        # M14 : 9 = action economique
    assert lf.code_fonction(None, "M57") == ""


def test_agreger_applique_les_formules():
    lignes = {
        "fonctionnement": [{"siren": "1", "categ": "Commune", "nomen": "M57", "fonction": "212", "d": "100", "c": "10"},
                           {"siren": "1", "categ": "Commune", "nomen": "M57", "fonction": "", "d": "5", "c": "0"}],
        "investissement_debit": [{"siren": "1", "categ": "Commune", "nomen": "M57", "fonction": "90844",
                                  "d": "50", "c": "999"}],
        "investissement_avances": [{"siren": "1", "categ": "Commune", "nomen": "M57", "fonction": "844",
                                    "d": "999", "c": "20"}],
    }
    x = lf.agreger(lignes)["1"]
    assert x["codes"]["212"] == [90.0, 0.0]               # DN = debit - credit
    assert x["codes"]["844"] == [0.0, 30.0]               # D - C(avances)
    assert x["codes"][""] == [5.0, 0.0]


def test_ventiler_niveaux_themes_et_sur_100():
    codes = {"212": [60.0, 20.0], "21": [0.0, 0.0], "844": [0.0, 10.0], "311": [10.0, 0.0], "": [0.0, 0.0]}
    v = lf.ventiler(codes, "M57", 10, True)
    assert v["total"][:2] == [70, 30] and v["part_ventilee"] == 1.0
    assert v["f"]["2"][:2] == [60, 20] and v["f"]["21"][:4] == [60, 20, 6.0, 2.0]
    assert v["f"]["8"][:2] == [0, 10] and v["f"]["84"][5] == 10.0
    assert v["themes"]["ecoles"][4:] == [60.0, 20.0]       # sur 100 euros de depenses totales
    assert v["themes"]["voirie"][:2] == [0, 10] and v["themes"]["culture"][:2] == [10, 0]
    s = sum(x[4] + x[5] for k, x in v["f"].items() if len(k) == 1)
    assert s == pytest.approx(100, abs=0.05)
    m14 = lf.ventiler({"822": [5.0, 5.0], "41": [1.0, 0.0]}, "M14", None, True)
    assert m14["themes"]["voirie"][:2] == [5, 5] and m14["themes"]["sport"][:2] == [1, 0]
    assert m14["f"]["82"][2] is None                       # pas de population : pas d'euros par habitant


def test_themes_et_libelles_par_nomenclature():
    for t, d in lf.THEMES.items():
        assert d["libelle"] and {"M57", "M14"} <= set(d), t
        for p in d["M57"]:
            assert p[:2] in lf.M57 or p in lf.M57, (t, p)
    assert lf.M57["84"] == "Voirie" and lf.M57["21"] == "Enseignement du premier degré"
    assert lf.M14["41"] == "Sport" and lf.M14["3"] == "Culture"


# --- Fichiers produits ------------------------------------------------------------------------------------------------


@produit
def test_tailles_et_entetes():
    total = 0
    for f in FICHIERS:
        n = f.stat().st_size
        total += n
        assert n < 5_000_000, f.name
        d = _json(f)
        assert d["millesime"] and d["source"] and d["colonnes"] == lf.COLONNES, f.name
    assert total < 150_000_000


@produit
def test_toutes_les_communes_ont_un_statut():
    idx = _json(DOSSIER / "index.json")
    vues = {}
    for f in FICHIERS:
        if f.stem in ("index", "regions"):
            continue
        for insee, c in _json(f)["communes"].items():
            assert c["statut"] in ("publie", "non_publie")
            assert (c["statut"] == "publie") == bool(c.get("annees")), insee
            vues[insee] = c["statut"]
    assert set(vues) == set(idx["communes"])
    for insee, m in idx["communes"].items():
        assert bool(m & 1) == (vues[insee] == "publie"), insee
    for a, c in idx["couverture"].items():
        assert c["communes"] <= c["communes_total"] and 0 <= c["part_population"] <= 1


@produit
def test_coherence_des_montants():
    d = _json(DOSSIER / "44.json")
    nantes = d["communes"]["44109"]["annees"]
    for a, y in nantes.items():
        if not y:
            continue
        tot = y["total"]
        n1 = [k for k in y["f"] if len(k) == 1]
        for i in (0, 1):  # niveaux 1 + non ventile = total (a l'arrondi pres)
            assert abs(sum(y["f"][k][i] for k in n1) + y["non_ventile"][i] - tot[i]) <= len(n1) + 1
        for k, v in y["f"].items():
            if len(k) == 2 and y["population"]:
                assert v[2] == pytest.approx(v[0] / y["population"], abs=0.01)


@produit
def test_regions_presentes():
    r = _json(DOSSIER / "regions.json")["regions"]
    assert len(r) >= 17
    for code, x in r.items():
        y = x["annees"][max(x["annees"])]
        assert y and y["f"] and "8" in y["f"], code   # transports
