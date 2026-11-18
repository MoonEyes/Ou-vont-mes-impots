"""Accueil du jeune enfant (pipeline/petite_enfance.py) : cohérence des fichiers publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "petite_enfance"
sys.path.insert(0, str(ROOT / "pipeline"))
import petite_enfance as pe  # noqa: E402

if not (DOSSIER / "index.json").exists():
    pytest.skip("site/data/petite_enfance absent : lancer `python pipeline/petite_enfance.py produire`",
                allow_module_level=True)

INDEX = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
NAT = json.loads((DOSSIER / "nationales.json").read_text(encoding="utf-8"))
DEPS = {an: json.loads((SITE / rel).read_text(encoding="utf-8")) for an, rel in INDEX["fichiers"]["departements"].items()}


def test_rattachement_des_caisses_aux_departements():
    assert pe.dep_de_caisse("011") == "01"
    assert pe.dep_de_caisse("598") == "59"
    assert pe.dep_de_caisse("201") == "2A" and pe.dep_de_caisse("202") == "2B"
    assert pe.dep_de_caisse("974") == "974" and pe.dep_de_caisse("976") == "976"


def test_annees_et_fichiers():
    assert INDEX["annees"] == list(range(2017, 2026))
    assert set(DEPS) == {str(a) for a in INDEX["annees"]}
    for an, d in DEPS.items():
        assert d["annee"] == int(an) and d["millesime"] and d["source"]
        assert len(d["departements"]) == 101
        assert {"75", "2A", "2B", "976", "974"} <= set(d["departements"])
        assert not set(d["departements"]) & {"20", "69D", "69M", "977", "978", "XXX"}


def test_cmg_postes_egaux_au_total_de_la_source():
    total = NAT["cmg"]["montant_eur"]
    for an, v in total.items():
        if v is None:
            continue
        somme = sum(p["montant_eur"][an] for p in NAT["cmg"]["postes"]) + NAT["cmg"]["non_ventile_eur"][an]
        assert somme == v, an
        assert abs(NAT["cmg"]["non_ventile_eur"][an]) <= 0.0001 * v, an


def test_cmg_departements_retrouvent_la_somme_nationale_des_versements():
    nat = NAT["cmg"]["montants_mensuels_caf_eur"]["valeurs"]
    for an in [str(a) for a in pe.ANNEES_CMG]:
        d = DEPS[an]
        somme = sum(x["cmg"]["montant_annuel_eur"] or 0 for x in d["departements"].values() if x["cmg"])
        somme += sum(h.get("cmg_montant_annuel_eur") or 0 for h in d["hors_departements"].values())
        manque = [c for c, x in d["departements"].items() if x["cmg"] and x["cmg"]["montant_annuel_eur"] is None]
        if not manque:
            assert abs(somme - nat[an]) <= len(d["departements"]) + 10, an
        else:   # un département incomplet à la source (Mayotte) : la somme reste en dessous
            assert somme <= nat[an]
    assert all(x["cmg"] is None for x in DEPS["2025"]["departements"].values())


def test_action_sociale_somme_des_caisses_egale_au_national():
    nat = NAT["action_sociale"]["petite_enfance_eur"]
    for an, v in nat.items():
        somme = sum(x["action_sociale_eur"]["petite_enfance"] for x in DEPS[an]["departements"].values()
                    if x["action_sociale_eur"])
        assert abs(somme - v) <= 0.0001 * v, an
    psu = next(p for p in NAT["action_sociale"]["postes"] if p["id"] == "fonctionnement_partenaires_fonds_nationaux")
    for an, v in psu["montant_eur"].items():
        assert 0 < v < nat[an]


def test_series_cnaf_distinctes_et_ecart_2022_publie():
    ids = [s["id"] for s in NAT["places_cnaf"]["series"]]
    assert ids == ["depuis_2022", "historique_2017_2022"]
    d22 = DEPS["2022"]["departements"]["01"]["places_cnaf"]
    assert [p["serie"] for p in d22] == ["depuis_2022", "historique_2017_2022"]
    assert len(DEPS["2019"]["departements"]["01"]["places_cnaf"]) == 1
    assert DEPS["2024"]["departements"]["01"]["places_cnaf"] == []
    paires = {(e["sujet"], e["annee"], e["source"], e["autre_source"]) for e in INDEX["ecarts"]}
    assert ("ensemble des places offertes", 2022, "cnaf_places", "cnaf_places_historique") in paires
    assert ("places en crèche", 2023, "cnaf_places", "drees_offre_accueil") in paires


def test_ecarts_recalculables():
    assert INDEX["ecarts"]
    for e in INDEX["ecarts"]:
        assert abs(e["valeur"] - e["autre_valeur"] - e["ecart"]) <= 0.01
        if e["autre_valeur"]:
            assert abs(e["ecart_pct"] - (e["valeur"] - e["autre_valeur"]) / e["autre_valeur"] * 100) < 0.06
        assert e["source"] in INDEX["sources"] and e["autre_source"] in INDEX["sources"]


def test_places_total_departements_coherent_avec_le_national():
    for serie, cle in (("depuis_2022", "cnaf_places"), ("historique_2017_2022", "cnaf_places_historique")):
        s = next(x for x in NAT["places_cnaf"]["series"] if x["id"] == serie)
        for an in s["annees"]:
            d = DEPS[str(an)]
            somme = sum(p["total"] for x in d["departements"].values() for p in x["places_cnaf"] if p["serie"] == serie)
            somme += sum(p["total"] for h in d["hors_departements"].values() for p in h.get("places_cnaf", [])
                         if p["serie"] == serie)
            nat = s["modes"]["total"][str(an)]
            assert abs(somme - nat) <= 0.002 * nat, (serie, an, somme, nat)


def test_liens_existent_et_ne_sont_pas_additionnes():
    for l in INDEX["liens"]:
        cible = SITE / l["fichier"]
        if not cible.exists():
            pytest.skip(f"{l['fichier']} absent")
        txt = cible.read_text(encoding="utf-8")
        assert f'"{l["id"]}"' in txt, l
        assert "ne s" in l["lecture"]


def test_corse_et_rhone_drees_dans_les_autres_territoires():
    d = DEPS["2024"]
    assert set(d["drees_autres_territoires"]) == {"20", "69D", "69M"}
    assert d["departements"]["2A"]["drees"]["agrements_assistants_maternels"] is None
    assert all(x["motif"] for x in d["non_disponibles"])
    total = NAT["places_drees"]["places"]["total"]["2024"]
    assert 500_000 <= total <= 505_000


def test_aucune_valeur_negative_hors_corrections_comptables():
    for d in DEPS.values():
        for x in d["departements"].values():
            for p in x["places_cnaf"] + x["couverture_cnaf"]:
                assert all(v is None or v >= 0 for k, v in p.items() if k != "serie")
            if x["cmg"]:
                assert (x["cmg"]["montant_annuel_eur"] or 0) >= 0


def test_sources_et_recherche_publique():
    for cle, s in INDEX["sources"].items():
        assert s["url"].startswith("https://") and s["licence"] and s["verdict"], cle
    assert INDEX["recherche_publique"]["trouvailles"]
    assert len(INDEX["sources_inaccessibles"]) >= 2
