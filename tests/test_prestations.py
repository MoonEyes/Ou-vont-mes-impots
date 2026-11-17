"""Prestations versées aux ménages (pipeline/prestations.py) : cohérence des fichiers publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "prestations"
sys.path.insert(0, str(ROOT / "pipeline"))
import prestations  # noqa: E402

if not (DOSSIER / "index.json").exists():
    pytest.skip("site/data/prestations absent : lancer `python pipeline/prestations.py produire`",
                allow_module_level=True)

INDEX = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
NAT = json.loads((DOSSIER / "nationales.json").read_text(encoding="utf-8"))
ATTENDUES = {"allocations_familiales", "aides_logement", "rsa", "prime_activite", "aah", "aspa", "paje", "ars", "are",
             "pensions_retraite", "indemnites_journalieres"}


def charger(rel):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


def test_prestations_demandees_couvertes_depuis_2019():
    assert {p["id"] for p in INDEX["prestations"]} == ATTENDUES == set(NAT["prestations"])
    assert INDEX["annees"][0] == 2019
    for pid, s in NAT["prestations"].items():
        assert s["derniere_annee"] and s["derniere_annee"] >= 2024, pid
        assert set(s["montant_eur"]) == {str(a) for a in INDEX["annees"]}, pid


def test_codes_drees_disjoints_pas_de_double_compte():
    vus = {}
    for p in prestations.PRESTATIONS:
        for c in p["cps"]:
            assert c not in vus, (c, p["id"], vus.get(c))
            for autre in vus:  # aucun code n'est le parent d'un autre
                assert not c.startswith(autre + ".") and not autre.startswith(c + "."), (c, autre)
            vus[c] = p["id"]


def test_totaux_calcules_source_par_source():
    t = INDEX["totaux"]
    for an, total in t["drees_cps"]["montant_eur"].items():
        somme = [NAT["prestations"][p]["sources_montant"]["drees_cps"][an] for p in t["drees_cps"]["prestations"]]
        if total is None:
            assert None in somme or not any(somme)
        else:
            assert abs(sum(somme) - total) <= len(somme)
            assert total < t["drees_cps"]["total_prestations_protection_sociale_eur"][an]
    for an, total in t["cnaf_depenses"]["montant_eur"].items():
        somme = sum(NAT["prestations"][p]["sources_montant"]["cnaf_depenses"][an]
                    for p in t["cnaf_depenses"]["prestations"])
        assert abs(somme - total) <= 10


def test_ecarts_publies_et_recalculables():
    assert INDEX["ecarts"] and INDEX["ecarts_departements"]
    for e in INDEX["ecarts"] + INDEX["ecarts_departements"]:
        assert abs(e["montant"] - e["autre_montant"] - e["ecart"]) <= 1
        if e["autre_montant"]:
            assert abs(e["ecart_pct"] - (e["montant"] - e["autre_montant"]) / e["autre_montant"] * 100) < 0.06
    paires = {(e["prestation"], e["source"], e["autre_source"]) for e in INDEX["ecarts"]}
    assert ("rsa", "cnaf_depenses", "drees_cps") in paires
    assert ("are", "unedic", "drees_cps") in paires
    assert ("aides_logement", "cnaf_depenses", "arbre_etat") in paires


def test_liens_vers_les_financeurs_existent_et_ne_sont_pas_additionnes():
    for p in INDEX["prestations"]:
        assert p["liens"], p["id"]
        for l in p["liens"]:
            assert (SITE / l["fichier"]).exists(), l
            if l["vue"] != "local":
                assert prestations._noeud(l["fichier"], l["id"]) is not None, l
    # les nœuds DREES liés (2024) retrouvent le montant DREES 2024 de la prestation
    for p in INDEX["prestations"]:
        md = sum(l["md"] for l in p["liens"] if l["vue"] == "secu_cps")
        ref = NAT["prestations"][p["id"]]["sources_montant"]["drees_cps"]["2024"]
        assert abs(md * 1e9 - ref) < 5e6, (p["id"], md, ref)
    liens = {p["id"]: {l["vue"] for l in p["liens"]} for p in INDEX["prestations"]}
    assert "arbre_etat" in liens["aah"] and "arbre_etat" in liens["prime_activite"]
    assert "arbre_etat" in liens["aides_logement"] and "local" in liens["rsa"]


@pytest.mark.parametrize("an", sorted(INDEX["fichiers"]["departements"]))
def test_departements_somme_egale_national_cnaf(an):
    d = charger(INDEX["fichiers"]["departements"][an])
    assert len(d["departements"]) >= 101
    for pid in prestations.DEPARTEMENTALES:
        for code, v in d["departements"].items():
            f, m, moy = v[pid]
            assert f is None or isinstance(f, int) and f >= 0, (code, pid)
            assert m is None or m >= 0
        foyers = sum(v[pid][0] or 0 for v in list(d["departements"].values()) + list(d["hors_departements"].values()))
        nat = NAT["prestations"][pid]["beneficiaires"][an]
        if nat is not None:
            assert abs(foyers - nat) <= max(5, nat * 1e-4), (an, pid, foyers, nat)  # écarts d'unité de la source


def test_valeurs_masquees_jamais_remplacees_par_zero():
    vals, _ = prestations.lire_drees_aspa_departements() if prestations.chemin(
        "drees_minima_departementales").exists() else ({}, {})
    for an, rel in INDEX["fichiers"]["departements"].items():
        d = charger(rel)
        for code, v in d["departements"].items():
            source = vals.get(code, {}).get(int(an)) if vals else v["aspa"][0]
            assert v["aspa"][0] == source, (an, code)


def test_rsa_recentralise_finance_par_l_etat():
    d = charger(INDEX["fichiers"]["departements"]["2024"])
    for code in ("93", "66", "09", "973", "974", "976"):
        assert d["departements"][code]["financeur_rsa"] == "etat", code
    assert d["departements"]["44"]["financeur_rsa"] == "departement"
    assert prestations.financeur_rsa("09", 2022) == "departement_puis_etat"


def test_recherche_publique_et_sources():
    r = INDEX["recherche_publique"]
    assert r["trouvailles"] and all(t["verdict"] for t in r["trouvailles"])
    for t in r["trouvailles"]:
        if "github.com/" in t["url"] and t["url"] != "https://github.com/search":
            assert t.get("dernier_commit") and t.get("licence"), t["nom"]
    assert INDEX["sources_inaccessibles"]
