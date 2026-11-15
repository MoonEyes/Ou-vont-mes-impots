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
    nom, tfb, _ = dep44["44066"]
    assert nom == "GRANDCHAMP DES FONTAINES" and 0 < tfb < 100


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
