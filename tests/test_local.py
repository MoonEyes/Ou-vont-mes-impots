"""Tests sans reseau de l'axe « Pres de chez moi » (site/data/local/, produit par `python pipeline/local.py tout`)."""
import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import local  # noqa: E402
import sirene  # noqa: E402

LOCAL = ROOT / "site" / "data" / "local"
TOUS = sorted(LOCAL.rglob("*.json"))
pytestmark = pytest.mark.skipif(not (LOCAL / "index.json").exists(), reason="site/data/local absent")


def _json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _sans_accent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


# --- Fonctions pures --------------------------------------------------------------------------------------------------


def test_par_hab_et_siren():
    assert local.par_hab(1000, 3) == 333.33
    assert local.par_hab(None, 3) is None and local.par_hab(10, 0) is None
    assert local.siren_de("234 400 034") == "234400034"
    assert local.siren_de("22440002800011") == "224400028"
    assert local.siren_de("NR CHORUS") == "" and local.siren_de("12345") == ""
    assert local.dep_de_insee("97411") == "974" and local.dep_de_insee("2A004") == "2A"


def test_objet_publiable_retire_les_noms_de_personnes():
    pr = {"JEAN", "GREGORY", "MARIE"}
    assert local.objet_publiable("Subvention à Mme Durand pour son projet", pr) is None
    assert local.objet_publiable("Aide versée à M. Martin", pr) is None
    assert local.objet_publiable("Documentaire de Gregory Dupont", pr) is None
    assert local.objet_publiable("Non disponible", pr) is None
    assert local.objet_publiable("Ecole Sainte-Marie, subvention 2025", pr) == "Ecole Sainte-Marie, subvention 2025"
    assert local.objet_publiable("Voirie de Saint-Jean-de-Boiseau", pr) == "Voirie de Saint-Jean-de-Boiseau"
    assert local.objet_publiable("Subvention au club de football", pr) == "Subvention au club de football"


def test_colonnes_scdl_normalisees():
    cols = ["nomAttribuant", "idAttribuant", "dateConvention", "idBeneficiaire", "montant", "Date de la convention"]
    assert local.colonne(cols, "idattribuant") == "idAttribuant"
    assert local.colonne(cols, "dateconvention") == "dateConvention"
    assert local.colonne(["Dépense/Recette"], "depensesrecettes", "depenserecette") == "Dépense/Recette"


def test_serie_calcule_les_euros_par_habitant():
    lignes = [{"id": "X", "nom": "N", "annee": 2024, "agregat": "Frais de personnel", "montant": 1000.4, "pop": 7},
              {"id": "X", "nom": "N", "annee": 2024, "agregat": "Agregat ignore", "montant": 5, "pop": 7}]
    s = local.serie(lignes, "id", ["2024"])
    i = local.CLES.index("frais_personnel")
    assert s["X"]["eur"]["2024"][i] == 1000
    assert s["X"]["eur_hab"]["2024"][i] == round(1000 / 7, 2)
    assert sum(v is not None for v in s["X"]["eur"]["2024"]) == 1


# --- Contrat des fichiers ---------------------------------------------------------------------------------------------


def test_millesime_et_source_partout():
    assert TOUS, "aucun fichier produit"
    for p in TOUS:
        d = _json(p)
        assert d.get("millesime"), f"millesime manquant : {p}"
        assert d.get("source"), f"source manquante : {p}"


def test_tailles():
    for p in TOUS:
        assert p.stat().st_size < 5_000_000, f"{p} depasse 5 Mo"
    assert sum(p.stat().st_size for p in LOCAL.rglob("*") if p.is_file()) < 300_000_000


def test_hierarchie_coherente():
    geos = sorted((LOCAL / "geo").glob("*.json"))
    assert len(geos) >= 96
    regions = _json(LOCAL / "budgets" / "regions.json")["collectivites"]
    n = 0
    for p in geos:
        g = _json(p)
        assert g["departement"]["code"] == p.stem
        assert g["region"]["code"] and g["region"]["nom"]
        for insee, c in g["communes"].items():
            assert re.match(r"^([0-9]{2}|2[AB])[0-9]{3}$", insee), insee
            assert c["departement"] == p.stem, f"{insee} : departement incoherent"
            assert c["region"] == g["region"]["code"], f"{insee} : region incoherente"
            assert local.dep_de_insee(insee) == p.stem
            if c.get("epci"):
                assert c["epci"] in g["epci"], f"{insee} : EPCI absent de la table"
            n += 1
    assert n >= 34000
    assert len(regions) >= 13


def _verifier_budget(d: dict, p: Path):
    k = len(d["agregats"])
    for code, c in d["collectivites"].items():
        for a, vals in c["eur"].items():
            assert len(vals) == k
            pop = c["population"].get(a)
            for v, h in zip(vals, c["eur_hab"][a]):
                if v is None or not pop:
                    assert h is None, f"{p} {code} {a}"
                else:
                    assert h == round(v / pop, 2), f"{p} {code} {a} : eur_hab != eur / population"


def test_euros_par_habitant_budgets():
    fichiers = sorted((LOCAL / "budgets" / "communes").glob("*.json")) + [
        LOCAL / "budgets" / "departements.json", LOCAL / "budgets" / "regions.json"]
    for p in fichiers:
        _verifier_budget(_json(p), p)
    for p in sorted((LOCAL / "budgets" / "epci").glob("*.json")):
        d = _json(p)
        _verifier_budget(d, p)
        _verifier_budget({**d, "collectivites": d["bloc_communal_consolide"]}, p)
        assert "flux" in d["methode_bloc_communal"]


def test_euros_par_habitant_fonctions():
    d = _json(LOCAL / "budgets" / "fonctions" / "departements.json")
    for code, x in d["departements"].items():
        for f in x["fonctions"].values():
            for a, vals in f["eur"].items():
                pop = x["population"][a]
                assert f["eur_hab"][a] == [None if v is None else round(v / pop, 2) for v in vals]
    for p in (LOCAL / "budgets" / "fonctions").glob("*.json"):
        if p.name == "departements.json":
            continue
        x = _json(p)
        for f in x["fonctions"].values():
            for a, vals in f["eur"].items():
                assert f["eur_hab"][a] == [local.par_hab(v, x["population"]) for v in vals]


def test_bloc_communal_sans_double_compte():
    """Bloc consolide <= EPCI + communes membres (flux croises retires), quand toutes les communes sont produites."""
    i = local.CLES.index("depenses_fonctionnement")
    vus = 0
    for p in (LOCAL / "budgets" / "communes").glob("*.json"):
        com = _json(p)["collectivites"]
        geo = _json(LOCAL / "geo" / p.name)
        ep = LOCAL / "budgets" / "epci" / p.name
        if not ep.exists():
            continue
        e = _json(ep)
        membres = {}
        for insee, c in geo["communes"].items():
            membres.setdefault(c.get("epci"), []).append(insee)
        for siren, x in e["bloc_communal_consolide"].items():
            if siren not in e["collectivites"] or siren not in membres:
                continue
            a = max(x["eur"])
            ins = membres[siren]
            if not all(a in com.get(c, {}).get("eur", {}) for c in ins):
                continue
            brut = e["collectivites"][siren]["eur"][a][i] + sum(com[c]["eur"][a][i] or 0 for c in ins)
            assert x["eur"][a][i] <= brut * 1.01, f"{siren} {a} : bloc consolide superieur a la somme brute"
            vus += 1
    assert vus >= 5


# --- Personnes physiques (bloquant) ----------------------------------------------------------------------------------


def _aucun_prenom(obj, chemin=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert "prenom" not in _sans_accent(k), f"champ prenom interdit : {chemin}/{k}"
            if k == "categorie_juridique":
                assert sirene.personne_morale(v), f"categorie {v!r} non publiable : {chemin}"
            _aucun_prenom(v, f"{chemin}/{k}")
    elif isinstance(obj, list):
        for v in obj:
            _aucun_prenom(v, chemin)


def test_aucune_personne_physique_nommee():
    dossiers = [p for p in (LOCAL / "decisions").iterdir() if p.is_dir()]
    assert dossiers
    for d in dossiers:
        for p in d.glob("*.json"):
            x = _json(p)
            _aucun_prenom(x, str(p))
            if "lignes" in x:
                c = x["colonnes"]
                i_s, i_cj = c.index("siren"), c.index("categorie_juridique")
                for lg in x["lignes"]:
                    assert sirene.siren_valide(lg[i_s]), f"{p} : SIREN invalide nomme"
                    assert sirene.personne_morale(lg[i_cj]), f"{p} : categorie {lg[i_cj]} nommee"
                    obj = lg[c.index("objet")]
                    assert obj is None or not local.contient_nom_de_personne(obj), f"{p} : nom possible : {obj}"
            for b in x.get("top_beneficiaires", []):
                assert sirene.siren_valide(b["siren"]) and sirene.personne_morale(b["categorie_juridique"])
            for lst in x.get("deliberations_subventions", {}).values():
                for dl in lst:
                    assert not local.contient_nom_de_personne(dl[2]), f"{p} : nom possible : {dl[2]}"


def test_conservation_decisions():
    for p in (LOCAL / "decisions").glob("*/index.json"):
        x = _json(p)
        if "total_source_eur" not in x:
            continue
        publie = sum(a["montant_eur"] for a in x["annees"].values())
        exclus = x["exclus_personnes_physiques_ou_non_identifies"]["montant_eur"]
        assert abs(publie + exclus - x["total_source_eur"]) <= 1 + len(x["annees"]), p
        for a, v in x["annees"].items():
            assert sum(len(_json(p.parent / f)["lignes"]) for f in v["fichiers"]) == v["lignes"]


def test_couverture_decisions_publiee():
    c = _json(LOCAL / "decisions" / "index.json")["couverture"]
    for t in ("commune", "epci", "departement", "region"):
        assert 0 <= c[t]["couvertes_subventions"] <= c[t]["total"]
    assert c["region"]["couvertes_subventions"] >= 2  # Pays de la Loire et Bretagne au moins


def test_region_pdl_vote_et_mandate_et_programmes():
    p = LOCAL / "decisions" / "234400034" / "index.json"
    if not p.exists():
        pytest.skip("Region Pays de la Loire absente de l'entrepot")
    x = _json(p)
    assert x["total_mandate_eur"] > 0 and x["total_source_eur"] > 0
    assert any(v["deliberations"] for v in x["programmes"].values()), "lien programme -> deliberation absent"


# --- Index -----------------------------------------------------------------------------------------------------------


def test_index_coherent():
    ix = _json(LOCAL / "index.json")
    blocs = ix["blocs"]
    assert blocs == local.BLOCS
    for p in sorted((LOCAL / "budgets" / "communes").glob("*.json")):
        b = _json(p)["collectivites"]
        geo = _json(LOCAL / "geo" / p.name)["communes"]
        for insee in geo:
            v = ix["communes"][insee]
            assert v & 1, f"{insee} : geo absent"
            assert bool(v >> blocs.index("budget_commune") & 1) == (insee in b)


def test_exemple_nantes():
    p = LOCAL / "budgets" / "communes" / "44.json"
    if not p.exists():
        pytest.skip("Loire-Atlantique non produite")
    n = _json(p)["collectivites"]["44109"]
    a = max(n["eur"])
    assert n["eur"][a][local.CLES.index("depenses_fonctionnement")] > 3e8
    geo = _json(LOCAL / "geo" / "44.json")["communes"]["44109"]
    assert geo["epci"] == "244400404" and geo["region"] == "52"
