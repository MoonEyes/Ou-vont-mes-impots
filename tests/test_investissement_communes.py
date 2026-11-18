"""Investissement réalisé par commune (pipeline/investissement_communes.py) : méthode sur des extraits construits à la
main (réel = débit net moins ordre, budget principal, 204 à part, rattachement par SIREN, crédits votés rapprochés
seulement sur le SIRET du budget principal) ; puis contrôles des fichiers publiés (sautés si absent).
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "investissement_communes"
sys.path.insert(0, str(ROOT / "pipeline"))
import investissement_communes as ic  # noqa: E402


def ecrire(p: Path, lignes: list[str]):
    p.write_text("\n".join(lignes) + "\n", encoding="utf-8")


@pytest.fixture
def lac(tmp_path, monkeypatch):
    lake, geo = tmp_path / "lake", tmp_path / "geo"
    lake.mkdir()
    geo.mkdir()
    monkeypatch.setattr(ic, "LAKE", lake)
    monkeypatch.setattr(ic, "GEO", geo)
    (geo / "44.json").write_text(json.dumps({"departement": {"code": "44"}, "communes": {
        "44001": {"nom": "Abbaretz", "siren": "214400012"}, "44002": {"nom": "Aigrefeuille", "siren": "214400020"}},
        "epci": {}}), encoding="utf-8")
    (lake / "meta_2024.json").write_text(json.dumps({"dataset": "balances-comptables-des-communes-en-2024",
                                                     "champs": ["cbudg", "compte"], "modifie": "2025-07-01",
                                                     "lignes": 10, "licence": "Licence Ouverte v2.0"}), encoding="utf-8")
    ecrire(lake / "2024_presence.csv", ["siren;ident;ndept;insee;n", "214400012;21440001200017;044;001;300",
                                        "214499999;21449999900010;044;099;10"])  # ancienne commune : pas de rattachement
    ecrire(lake / "2024_c20.csv", ["siren;ident;d;o", "214400012;21440001200017;1000.4;0.0"])
    ecrire(lake / "2024_c204.csv", ["siren;ident;d;o", "214400012;21440001200017;500;0"])
    ecrire(lake / "2024_c21.csv", ["siren;ident;d;o", "214400012;21440001200017;20000;5000",
                                   "214499999;21449999900010;7;0"])
    ecrire(lake / "2024_c23.csv", ["siren;ident;d;o", "214400012;21440001200017;3000;3000"])
    return lake


def test_filtre_budget_principal():
    assert ic.filtre_bp({"champs": ["cbudg"], "dataset": "x"}) == 'cbudg="1"'
    assert ic.filtre_bp({"champs": ["budget"], "dataset": "x"}) == 'budget="BP"'
    with pytest.raises(SystemExit):
        ic.filtre_bp({"champs": ["compte"], "dataset": "x"})


def test_reel_moins_ordre_et_204_a_part(lac):
    res, siret, _ = ic.montants_annee("2024")
    # 21 : 20 000 - 5 000 d'ordre ; 23 : tout en ordre -> 0 publié ; 204 jamais dans l'équipement
    assert res["214400012"] == [1000 + 15000 + 0, 1000, 15000, 0, 500]
    assert siret["214400012"] == "21440001200017"


def test_vote_seulement_si_champ_renseigne():
    b, jeux = ic.bloc_vote({"c21": {"propnouv": 100.0, "jeux": ["j1"]}, "c23": {"propnouv": None, "jeux": ["j1"]}},
                           "propnouv")
    assert b == [100, 0, 100, 0, 0] and jeux == ["j1"]
    assert ic.bloc_vote({"c21": {"propnouv": None}}, "propnouv") == (None, [])


def test_production(lac, tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "ANNEES", ["2024"])
    monkeypatch.setattr(ic.deliberations, "votes_equipement", lambda: {
        "21440001200017": {"2024": {"budget_primitif": {"c21": {"propnouv": 40000.0, "jeux": ["jeu1"]}}}},
        "21440002000099": {"2024": {"budget_primitif": {"c21": {"propnouv": 1.0, "jeux": ["jeu2"]}}}}})
    sortie = tmp_path / "sortie"
    stats = ic.produire(sortie)
    assert stats["communes"] == 1
    d = json.loads((sortie / "communes" / "44.json").read_text(encoding="utf-8"))
    c = d["communes"]["44001"]
    assert c["m"]["2024"] == [16000, 1000, 15000, 0, 500]
    assert c["vote"]["2024"]["budget_primitif"] == [40000, 0, 40000, 0, 0] and c["vote"]["2024"]["jeux"] == ["jeu1"]
    assert "44002" not in d["communes"]  # aucune balance : absente, jamais 0
    idx = json.loads((sortie / "index.json").read_text(encoding="utf-8"))
    assert idx["couverture"]["2024"]["balances_sans_commune_en_vigueur"] == 1
    assert "taux" not in json.dumps(idx["statut"])
    # reproductible octet pour octet
    avant = (sortie / "communes" / "44.json").read_bytes()
    ic.produire(sortie)
    assert (sortie / "communes" / "44.json").read_bytes() == avant


publie = pytest.mark.skipif(not (DOSSIER / "index.json").exists(), reason="site/data/investissement_communes absent")


@publie
def test_fichiers_publies():
    idx = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
    assert idx["annees"][0] == "2010" and idx["annees"][-1] >= "2025"
    assert idx["colonnes"] == ic.COLONNES
    for f in sorted((DOSSIER / "communes").glob("*.json")):
        assert f.stat().st_size < ic.MAX_OCTETS, f
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"]
        for insee, c in d["communes"].items():
            assert re.match(r"^(\d{5}|2[AB]\d{3})$", insee) and re.match(r"^\d{9}$", c["siren"])
            for a, v in c["m"].items():
                assert a in idx["annees"] and len(v) == 5 and v[0] == v[1] + v[2] + v[3]


@publie
def test_ordre_de_grandeur_nantes():
    """Nantes (44109) : équipement du budget principal de l'ordre de la centaine de millions d'euros par an."""
    d = json.loads((DOSSIER / "communes" / "44.json").read_text(encoding="utf-8"))
    m = d["communes"]["44109"]["m"]
    assert all(20e6 < v[0] < 600e6 for v in m.values())
