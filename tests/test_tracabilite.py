"""Tests sans réseau du taux de traçabilité (site/data/tracabilite/, produit par pipeline/tracabilite.py)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import tracabilite  # noqa: E402

TRAC = ROOT / "site" / "data" / "tracabilite"
FICHIERS = sorted(TRAC.glob("*.json")) if TRAC.exists() else []
pytestmark = pytest.mark.skipif(not FICHIERS, reason="site/data/tracabilite absent")


def _json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _noeuds():
    for f in FICHIERS:
        d = _json(f)
        if f.name == "resume.json":
            yield f.name + ":global", d["global"]
            for g in d["grands_postes"] + d["missions"]:
                yield f"{f.name}:{g['id']}", g
        else:
            yield f.name, d


def test_parts_somment_a_100():
    for nom, n in _noeuds():
        if not n["total_eur"]:
            continue
        assert abs(sum(p["pct"] for p in n["parts"].values()) - 100) < 0.01, nom
        assert abs(sum(p["eur"] for p in n["parts"].values()) - n["total_eur"]) <= max(1.0, 1e-9 * n["total_eur"]), nom


def test_aucun_taux_sans_source():
    for nom, n in _noeuds():
        for k, p in n["parts"].items():
            if p["eur"] > 0:
                assert p["sources"], (nom, k)
        for m in n["maillons"]:
            if m["pct"] > 0:
                assert m["sources"], (nom, m["maillon"])


def test_taux_approche_porte_ecart_et_raison():
    for f in FICHIERS:
        if f.name == "resume.json":
            continue
        d = _json(f)
        for k, lst in d["composantes"].items():
            for c in lst:
                assert c["sources"], (f.name, k)
                if c["statut"] == "approche":
                    assert c["raison_approche"], (f.name, k)
                    assert isinstance(c["ecart_millesime_ans"], int)
                else:
                    assert c["ecart_millesime_ans"] == 0 and not c["raison_approche"], (f.name, k)


def test_maillon_programme_100_et_bornes():
    for nom, n in _noeuds():
        assert n["maillons"][0]["maillon"] == "programme" and n["maillons"][0]["pct"] == 100.0, nom
        for m in n["maillons"]:
            assert 0 <= m["pct"] <= 100.001, (nom, m)


def test_resume_couvre_la_racine():
    r = _json(TRAC / "resume.json")
    racine = _json(ROOT / "site" / "data" / "arbre" / "racine.json")
    assert abs(r["global"]["total_eur"] - racine["md"] * 1e9) < 1e6
    assert {g["nom"] for g in r["grands_postes"]} == {g["nom"] for g in racine["enfants"]}
    assert len(r["programmes"]) == len(FICHIERS) - 1


def test_synthese_sur_echantillon():
    comp = {k: [] for k in tracabilite.PARTS}
    comp["nominatif_par_choix"].append(tracabilite.composante(30, ["s1"], "m", 0, None, "", "categorie"))
    comp["beneficiaire_identifie"].append(tracabilite.composante(20, ["s2"], "m", 1, "millésime", ""))
    comp["non_publie"].append(tracabilite.composante(50, ["s3"], "m", 0, None, "", "aucun"))
    s = tracabilite.synthese(100.0, comp, 100.0)
    assert s["parts"]["beneficiaire_identifie"]["statut"] == "approche"
    assert s["parts"]["beneficiaire_identifie"]["ecart_millesime_ans"] == 1
    assert s["taux_tracabilite_pct"] == 50.0
    assert sum(p["pct"] for p in s["parts"].values()) == 100.0
