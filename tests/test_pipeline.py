"""Tests du pipeline sur les donnees deja telechargees (data/raw)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import transform  # noqa: E402

SITE = ROOT / "site" / "data"


@pytest.fixture(scope="module", autouse=True)
def run_transform():
    transform.main()


def test_sankey_conservation_a_chaque_niveau():
    s = json.loads((SITE / "sankey_etat.json").read_text(encoding="utf-8"))
    levels = {i: n["level"] for i, n in enumerate(s["nodes"])}
    for lvl in (0, 1, 2):
        sortant = sum(l["value"] for l in s["links"] if levels[l["source"]] == lvl)
        assert sortant == pytest.approx(s["total"], abs=0.05), f"niveau {lvl}"


def test_chaque_noeud_conserve_son_flux():
    s = json.loads((SITE / "sankey_etat.json").read_text(encoding="utf-8"))
    for i, n in enumerate(s["nodes"]):
        if n["level"] in (1, 2):
            entrant = sum(l["value"] for l in s["links"] if l["target"] == i)
            sortant = sum(l["value"] for l in s["links"] if l["source"] == i)
            assert entrant == pytest.approx(sortant, abs=0.01), n["name"]


def test_detail_et_nature_retombent_sur_le_total():
    s = json.loads((SITE / "sankey_etat.json").read_text(encoding="utf-8"))
    n = json.loads((SITE / "nature_etat.json").read_text(encoding="utf-8"))
    assert sum(t["md"] for t in n["titres"]) == pytest.approx(s["total"], abs=0.05)
    total_prog = 0.0
    for f in (SITE / "programmes").glob("*.json"):
        p = json.loads(f.read_text(encoding="utf-8"))
        assert sum(a["md"] for a in p["actions"]) == pytest.approx(sum(p["nature"].values()), abs=0.01), f.name
        total_prog += sum(p["nature"].values())
    assert total_prog == pytest.approx(s["total"], abs=0.05)


def _charger_arbre(n):
    if "fichier" in n:
        n = json.loads((SITE / n["fichier"]).read_text(encoding="utf-8"))
    return n


def test_arbre_chaque_noeud_egal_somme_enfants_jusqu_aux_feuilles():
    racine = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    profondeurs, feuilles = [], []

    def visite(n, d):
        n = _charger_arbre(n)
        enfants = n.get("enfants", [])
        assert n["nom"] != "?", n["id"]
        if enfants:
            assert sum(e["md"] for e in enfants) == pytest.approx(n["md"], abs=1e-4), n["id"]
            for e in enfants:
                visite(e, d + 1)
        else:
            profondeurs.append(d)
            feuilles.append(n["md"])

    visite(racine, 0)
    assert sum(feuilles) == pytest.approx(racine["md"], abs=0.01)
    assert max(profondeurs) >= 6  # descend bien sous le programme


def test_arbre_generique_profondeur_libre():
    import arbre
    rows = [{"a": "X", "b": "1", "c": None, "v": 2e9}, {"a": "X", "b": "2", "c": "z", "v": 1e9}]
    niveaux = [{"id": n, "cle": n, "libelle": n} for n in "abc"]
    r = arbre.construire(rows, niveaux, "v")
    x = r["enfants"]["X"]
    assert x["eur"] == 3e9 and x["enfants"]["1"]["enfants"] == {}  # c absent : branche plus courte
    assert x["enfants"]["2"]["enfants"]["z"]["eur"] == 1e9


def test_arbre_administrations_coherent_et_double_compte_explique():
    racine = json.loads((SITE / "arbre_administrations" / "racine.json").read_text(encoding="utf-8"))
    assert {e["nom"] for e in racine["enfants"]} == {"Etat", "Collectivites locales", "Securite sociale"}

    def visite(n):
        if n.get("enfants"):
            assert sum(e["md"] for e in n["enfants"]) == pytest.approx(n["md"], abs=1e-3), n["id"]
            for e in n["enfants"]:
                visite(e)
    visite(racine)
    m = json.loads((SITE / "arbre_administrations" / "methode.json").read_text(encoding="utf-8"))
    surplus = m["somme_administrations_md"] - m["total_consolide_md"]
    # Le surplus restant est positif et ne depasse pas les transferts entre administrations publies.
    assert 0 <= surplus <= m["ecart_consolidation_md"]
    assert m["ecart_consolidation_md"] >= m["transferts_courants_entre_administrations_md"]


def test_recettes_un_impot_va_a_une_seule_administration():
    r = json.loads((SITE / "recettes.json").read_text(encoding="utf-8"))
    for code in ("D211", "D51A_C1", "D61"):
        par = r["impots"][code]["par_administration"]
        for annee, total in par["Ensemble"].items():
            somme = sum(par[a].get(annee, 0) for a in ("Etat", "Collectivites locales", "Securite sociale"))
            assert somme == pytest.approx(total, rel=0.01), (code, annee)


def test_remboursements_exclus():
    s = json.loads((SITE / "sankey_etat.json").read_text(encoding="utf-8"))
    assert not any("Remboursements" in n["name"] for n in s["nodes"])


def test_mission_inconnue_fait_echouer(monkeypatch):
    rows = transform.load("budget_etat_plf") + [{
        "mission": "Mission imaginaire", "programme": 999.0, "libelle_programme": "x", "cp_plf": 1.0}]
    monkeypatch.setattr(transform, "load", lambda name: rows)
    with pytest.raises(SystemExit, match="Mission imaginaire"):
        transform.budget_etat()


def test_codes_insee_et_commune_connue():
    dep44 = json.loads((SITE / "communes" / "44.json").read_text(encoding="utf-8"))
    assert all(len(code) == 5 for code in dep44)
    nom, tfb, _ = dep44["44109"]
    assert nom == "NANTES" and 0 < tfb < 100


def test_jsonstat_extraction():
    data = {
        "id": ["geo", "cat", "time"], "size": [1, 2, 2],
        "dimension": {"cat": {"category": {"index": {"A": 0, "B": 1}}},
                      "time": {"category": {"index": {"2023": 0, "2024": 1}}}},
        "value": {"0": 1, "1": 2, "2": 3},  # B/2024 manquant
    }
    assert transform.jsonstat_series(data, "cat") == {"A": {"2023": 1, "2024": 2}, "B": {"2023": 3}}


def test_derive_de_schema_detectee(tmp_path):
    ref = ROOT / "schemas" / "deficit_france.json"
    original = ref.read_text(encoding="utf-8")
    try:
        ref.write_text(json.dumps({"champ_fantome": "text"}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "check_schema.py")],
                           capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 1 and "champ_fantome" in r.stdout
    finally:
        ref.write_text(original, encoding="utf-8")
        (ROOT / "schema_drift.md").unlink(missing_ok=True)
