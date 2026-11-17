"""Subventions au format des données essentielles des conventions (pipeline/subventions.py).

Tests unitaires (lecture des montants, SIREN, départements, règle des personnes morales, conservation) toujours
lancés ; tests des fichiers publiés si site/data/subventions existe. Sans réseau.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "subventions"
sys.path.insert(0, str(ROOT / "pipeline"))
import subventions as sv  # noqa: E402


# --- Unitaires -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("brut,attendu", [
    ("1000,00", 1000.0), ("2000.00", 2000.0), (" 57 293.43", 57293.43), ("34771.0", 34771.0),
    ("1.234.567,89", 1234567.89), ("12 000", 12000.0), ("0", 0.0),
])
def test_montant_lu(brut, attendu):
    assert sv.montant(brut) == pytest.approx(attendu)


@pytest.mark.parametrize("brut", ["", "nc", "NC", "n.c.", None, "non communiqué", "-"])
def test_montant_nc_jamais_zero(brut):
    assert sv.montant(brut) is None


@pytest.mark.parametrize("brut,attendu", [
    ("13000800600061", "130008006"), ("385290309", "385290309"), ('"30294931800273"', "302949318"),
    ("1,30002E+13", ""), ("1.20014E+13", ""), ("", ""), ("NR CHORUS", ""), ("12345", ""),
    ("1234567800016", "012345678"),  # zéro de tête perdu par un tableur (SIRET à 13 chiffres)
])
def test_siren(brut, attendu):
    assert sv.siren(brut) == attendu


def test_departements():
    if not sv.GEO.exists():
        pytest.skip("site/data/local/geo absent")
    assert sv.dep_code("1") == "01" and sv.dep_code("2A") == "2A" and sv.dep_code("972") == "972"
    assert sv.dep_code("99") is None and sv.dep_code("ANCT-MGER") is None
    assert sv.dep_cp("63600") == "63" and sv.dep_cp("20000") == "2A" and sv.dep_cp("20200") == "2B"
    assert sv.dep_cp("97400") == "974" and sv.dep_cp("6000") == "06"
    assert sv.dep_nom("CGET - DDCS AIN-147") == "01"
    assert sv.dep_nom("DGCL - DDETS LOIRE-ATLANTIQUE-147") == "44"
    assert sv.dep_nom("DDCS HAUTE-LOIRE") == "43"
    assert sv.dep_nom("DGCL - DCS GUADELOUPE-147") == "971"
    assert sv.dep_nom("DGCL - ANCT-MGER-147") is None


def test_statut_personnes_morales_seules():
    stock = {"385290309": ("4110", "ADEME"), "123456789": ("1000", None), "222222222": ("2110", None),
             "333333333": ("", None)}
    assert sv.statut("385290309", stock) == ("pm", "4110")
    assert sv.statut("123456789", stock)[0] == "pp"
    assert sv.statut("222222222", stock)[0] == "pp"  # indivision : groupement de personnes physiques
    assert sv.statut("333333333", stock)[0] == "in"
    assert sv.statut("999999999", stock)[0] == "in"  # absent du stock : jamais nommé
    assert sv.statut("", stock)[0] == "ni"


def test_groupe_conservation_et_top():
    stock = {f"{i:09d}": ("9220", f"ASSOCIATION {i}") for i in range(1, 80)}
    par_siren = {s: {"montant": float(i), "lignes": 1} for i, s in enumerate(sorted(stock), 1)}
    exclus = sv.exclus_vide()
    exclus.update({"montant_eur": 10.0, "lignes": 2, "dont_personnes_physiques_eur": 10.0})
    total = sum(d["montant"] for d in par_siren.values()) + 10.0
    g = sv.groupe(par_siren, stock, exclus, total)
    assert len(g["top"]) == sv.TOP and g["top"][0]["montant_eur"] == 79.0
    assert g["autres_personnes_morales"]["nombre"] == 79 - sv.TOP
    somme = (sum(b["montant_eur"] for b in g["top"]) + g["autres_personnes_morales"]["montant_eur"]
             + g["exclus_personnes_physiques_ou_non_identifies"]["montant_eur"])
    assert somme == pytest.approx(total)
    with pytest.raises(SystemExit):
        sv.groupe(par_siren, stock, exclus, total + 100)


def test_sources_declarees():
    cat = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    ids = {s["id"]: s for s in cat["sources"]}
    for sid, s in sv.SOURCES.items():
        assert sid in ids, f"{sid} absent de collecte/catalogue.json"
        assert ids[sid]["domaine"] == "subventions"
        assert s["lecteur"] in sv.LECTEURS
        assert s["rattachement"]["type"] in ("programme_source", "programme_dispositif", "operateur", "hors_budget_etat")
        if not s["additionne"]:
            assert s.get("inclus_dans") in sv.SOURCES, sid
            assert any(r["source"] == sid for r in sv.RECOUVREMENTS), sid
        if not s.get("titres"):
            assert ids[sid].get("personnes_physiques"), f"{sid} : source avec SIRET, zone restreinte attendue"


def test_colonnes_sensibles_jamais_lues():
    """Adresse, genre (parité), direction artistique, dirigeants : aucune de ces colonnes n'est lue par un lecteur."""
    import inspect
    code = inspect.getsource(sv).lower()
    for motif in ("parite", "parité", "quidirige", "qui dirige", "adresse_", "dirigeant", "prenom"):
        assert f'"{motif}' not in code and f"'{motif}" not in code, motif


# --- Fichiers publiés --------------------------------------------------------------------------------------------------

publie = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                            reason="site/data/subventions absent : lancer `python pipeline/subventions.py produire`")


def charger(rel):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


@publie
def test_fichiers_sous_5_mo_et_entete():
    for f in DOSSIER.rglob("*.json"):
        assert f.stat().st_size < 5_000_000, f
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"], f


@publie
def test_sources_attendues_et_fichiers():
    idx = charger("subventions/index.json")
    ids = {s["id"] for s in idx["sources"]}
    absentes = {x["source"] for x in idx["sources_inaccessibles"]}
    assert ids | absentes == set(sv.SOURCES)
    for s in idx["sources"]:
        assert (SITE / s["fichier"]).exists()
        assert s["conventions"] > 0 and s["total_eur"] > 0, s["id"]


@publie
def test_aucune_personne_physique_nommee():
    def parcourir(x):
        if isinstance(x, dict):
            if "siren" in x and "categorie_juridique" in x:
                cj = x["categorie_juridique"]
                assert cj[0] in "23456789" and cj not in ("2110", "2210", "2310", "2385"), x
            for k, v in x.items():
                k2 = sv.sans_accent(k).lower()
                assert not any(m in k2 for m in ("prenom", "adresse", "genre", "parite", "dirige")), k
                parcourir(v)
        elif isinstance(x, list):
            for v in x:
                parcourir(v)
    for f in DOSSIER.rglob("*.json"):
        parcourir(json.loads(f.read_text(encoding="utf-8")))


@publie
def test_conservation_par_source():
    for f in (DOSSIER / "attribuants").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert sum(a["montant_eur"] for a in d["par_annee"]) == pytest.approx(d["total_eur"], abs=1), f.name
        assert sum(a["montant_eur"] for a in d["par_departement"]) == pytest.approx(d["total_eur"], abs=1), f.name
        assert sum(a["lignes_montant_non_communique"] for a in d["par_annee"]) == d["lignes_montant_non_communique"]
        assert d["nommes"]["montant_eur"] + d["agrege_confidentialite"]["montant_eur"] == \
            pytest.approx(d["total_eur"], abs=1), f.name
        if "titres" in d:
            t = d["titres"]
            s = sum(x["montant_eur"] for x in t["top"]) + t["autres_titres"]["montant_eur"] \
                + t["titres_non_nommes"]["montant_eur"]
            assert s == pytest.approx(t["total_eur"], abs=1)


@publie
def test_nc_jamais_compte_zero():
    """Une ligne « nc » n'ajoute ni montant ni convention : conventions + nc = lignes lues."""
    for f in (DOSSIER / "attribuants").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        for a in d["par_annee"]:
            if a["conventions"] == 0:
                assert a["montant_eur"] == 0 and a["lignes_montant_non_communique"] > 0


@publie
def test_totaux_toutes_sources_sans_recouvrement():
    idx = charger("subventions/index.json")
    add = [s for s in idx["sources"] if s["additionne"]]
    attendu = sum(s["total_eur"] - s["montant_retire_des_totaux_eur"] for s in add)
    assert idx["totaux"]["total_additionne_eur"] == pytest.approx(attendu, abs=1)
    an = charger("subventions/annees.json")
    assert sum(a["total_additionne_eur"] for a in an["annees"]) == pytest.approx(attendu, abs=1)
    assert set(an["sources_additionnees"]) == {s["id"] for s in add} | {
        k for k, s in sv.SOURCES.items() if s["additionne"] and k not in {x["id"] for x in idx["sources"]}}
    for a in an["annees"]:
        assert not set(a["par_source"]) - {s["id"] for s in add}
    dep = charger("subventions/departements.json")
    loc = sum(d["total_additionne_eur"] for d in dep["departements"].values()) + sum(dep["non_localise"].values())
    assert loc == pytest.approx(attendu, abs=1)
    ben = charger("subventions/beneficiaires.json")
    assert ben["total_eur"] == pytest.approx(attendu, abs=1)
    assert ben["autres_non_verifies"]["montant_eur"] == 0


@publie
def test_programmes_lolf_attendus():
    pr = charger("subventions/programmes.json")
    vus = {(p["programme"], p["source"]) for p in pr["programmes"]}
    idx = {s["id"] for s in charger("subventions/index.json")["sources"]}
    attendus = {("147", "subv_politique_ville_p147"), ("380", "subv_fonds_vert"), ("131", "subv_culture_scdl"),
                ("131", "subv_culture_festivals_p131"), ("180", "subv_presse_titres")}
    assert {a for a in attendus if a[1] in idx} <= vus
    ops = {o["source"]: o["programme_chef_de_file"] for o in pr["operateurs"]}
    if "subv_ademe_aides" in idx:
        assert ops["subv_ademe_aides"] == "181"
    for p in pr["programmes"]:
        for a in p["par_annee"]:
            assert a["montant_nomme_eur"] <= a["montant_eur"] + 1


@publie
def test_contrat_subventions():
    sys.path.insert(0, str(ROOT / "docs"))
    import valider_contrat as v
    js = v.charger_jsonschema()
    fautes = []
    for sch, motif, _ in v.FICHIERS:
        if not motif.startswith("subventions/"):
            continue
        for p in sorted(SITE.glob(motif)):
            doc = json.loads(p.read_text(encoding="utf-8"))
            fautes += [f"{p.name} : {e}" for e in v.erreurs(v.validateur(js, sch), doc)
                       + v.liens_fichiers(p, doc) + v.conservation_groupes(doc)]
    assert not fautes, "\n".join(fautes[:10])
