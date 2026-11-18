"""Millésimes (pipeline/millesimes.py) : exécution 2025 préparée sans changer la vue par défaut, vérification datée.

Les tests sur site/data/millesimes tournent sans réseau ; la reproduction octet pour octet demande l'entrepôt
(data/lake/etat/etat_plrg_2024 et etat_plrg_2025), sautée sinon.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "millesimes"
LAKE = ROOT / "data" / "lake" / "etat"
sys.path.insert(0, str(ROOT / "tests"))
from test_neutralite import fautes, textes  # noqa: E402


@pytest.fixture(scope="module")
def index():
    return json.loads((DATA / "index.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def racine():
    return json.loads((DATA / "execution2025" / "racine.json").read_text(encoding="utf-8"))


def test_entetes(index, racine):
    for d in (index, racine):
        assert d["millesime"] and d["source"]
    assert racine["millesime"] == "Exécution 2025"
    assert racine["unite"].startswith("milliards d'euros")
    for p in DATA.rglob("*.json"):
        assert p.stat().st_size < 1_000_000, p


def test_vue_par_defaut_inchangee(index):
    assert index["vue_par_defaut"]["actuelle"] == "Exécution 2024"
    meta = json.loads((ROOT / "site" / "data" / "meta.json").read_text(encoding="utf-8"))
    assert meta["millesime"]["etat_defaut"] == "Exécution 2024"
    assert json.loads((ROOT / "site" / "data" / "arbre" / "racine.json").read_text(encoding="utf-8"))["millesime"] \
        == "Exécution 2024"
    donnees = (ROOT / "web" / "src" / "donnees.ts").read_text(encoding="utf-8")
    debut = donnees.index("VUES_ARBRE: VueArbre[] = [")
    assert "cle: 'execution2024'" in donnees[debut:debut + 200]
    # Onglet « Dépensé en 2025 (par politique) » (vague 3) : millesimes/ est une vue de plus, jamais la vue par défaut.
    assert donnees.index("cle: 'execution2024'") < donnees.index("millesimes/")


def _somme(n: dict) -> None:
    if n.get("enfants"):
        assert abs(sum(e["md"] for e in n["enfants"]) - n["md"]) < 1e-4, n["id"]
        for e in n["enfants"]:
            _somme(e)


def test_arbre_execution_2025(index, racine):
    _somme(racine)
    assert abs(racine["md"] * 1e9 - index["execution_2025"]["total_eur"]) < 1e3
    niveaux = set()

    def parcourir(n):
        niveaux.add(n["niveau"])
        assert "fichier" not in n  # feuilles au programme : un seul fichier
        for e in n.get("enfants", []):
            parcourir(e)
    parcourir(racine)
    assert niveaux <= {"racine", "grand_poste", "mission", "programme"}
    postes = {gp["id"] for gp in racine["enfants"]}
    assert "exclu" not in postes and "hors_perimetre" not in postes


def test_comparaison_coherente(index, racine):
    c = index["comparaison"]
    col = {k: i for i, k in enumerate(c["colonnes"])}
    lignes = c["lignes"]
    assert {l[0] for l in lignes} == {gp["id"] for gp in racine["enfants"]}
    for l in lignes:
        if l[col["variation_plrg_eur"]] is not None:
            assert abs(l[col["execution_2025_plrg_eur"]] - l[col["execution_2024_plrg_eur"]]
                       - l[col["variation_plrg_eur"]]) <= 1
    t = c["totaux"]
    assert abs(sum(l[col["execution_2025_plrg_eur"]] for l in lignes) - t["execution_2025_plrg_eur"]) <= len(lignes)
    assert t["execution_2025_plrg_eur"] == index["execution_2025"]["total_eur"]
    # l'exécution 2024 affichée est celle de l'arbre du site
    site = json.loads((ROOT / "site" / "data" / "arbre" / "racine.json").read_text(encoding="utf-8"))
    assert abs(t["execution_2024_affichee_eur"] - site["md"] * 1e9) < 1e4


def test_controles(index):
    for c in index["controles"]:
        assert c["prelevements_sur_recettes_eur"] == c["prelevements_sur_recettes_situation_eur"]
        assert c["remboursements_et_degrevements_retires_eur"] > 0
        assert abs(c["ecart_budget_general_eur"]) < 0.02 * c["depenses_nettes_budget_general_situation_eur"]


def test_verification(index):
    v = index["verification"]
    assert v["nombre"] == len(v["sources"]) == 22
    assert sum(v["par_suite"].values()) == 22
    ids = [s["id"] for s in v["sources"]]
    assert len(set(ids)) == 22
    for s in v["sources"]:
        assert s["url"].startswith("https://")
        if s["suite"] == "rattrapé":
            assert s["nouvelle_source"]
    cat = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    connus = {s["id"] for s in cat["sources"]}
    for s in v["sources"]:
        if s["nouvelle_source"]:
            assert s["nouvelle_source"] in connus


def test_bascule(index):
    b = index["bascule"]
    assert b["donnees_pretes"] == ["millesimes/execution2025/racine.json"]
    for e in b["ecrans"]:
        assert (ROOT / e["fichier"]).exists()
    for p in b["pipelines"]:
        assert (ROOT / p).exists()
    assert any(e["fichier"] == "web/src/donnees.ts" for e in b["ecrans"])


def test_neutralite(index):
    erreurs = [(k, t, f) for k, t in textes(index) for f in fautes(t)]
    assert not erreurs, erreurs[:5]


@pytest.mark.skipif(not ((LAKE / "etat_plrg_2024").exists() and (LAKE / "etat_plrg_2025").exists()),
                    reason="entrepôt PLRG absent")
def test_reproductible(tmp_path):
    for i in (1, 2):
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "millesimes.py"), "produire", "--sortie",
                        str(tmp_path / str(i))], check=True, capture_output=True)
    for p in (tmp_path / "1").rglob("*.json"):
        q = tmp_path / "2" / p.relative_to(tmp_path / "1")
        assert p.read_bytes() == q.read_bytes(), p
    for p in (tmp_path / "1").rglob("*.json"):
        assert p.read_bytes() == (DATA / p.relative_to(tmp_path / "1")).read_bytes(), p
