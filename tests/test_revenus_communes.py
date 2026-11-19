"""Revenus par commune (pipeline/revenus_communes.py) : règles de lecture, recomposition géographique, fichiers publiés.

Les tests de lecture tournent sur des valeurs construites à la main ; les tests des fichiers sur
site/data/revenus_communes (sautés si absent) ; la reproductibilité sur l'entrepôt (sautée sans data/lake).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "revenus_communes"
sys.path.insert(0, str(ROOT / "pipeline"))
import revenus_communes as rc  # noqa: E402


# --- Règles de lecture (sans données) -------------------------------------------------------------------------------

def test_marques_de_la_source_jamais_zero():
    for v in ("n.c.", "n.d.", ".", "#VALUE!", "", None, "  "):
        assert rc.nombre(v)[0] is None, v
    assert rc.nombre("n.c.") == (None, "n.c.") and rc.nombre("") == (None, "vide")
    assert rc.nombre(0) == (0, None) and rc.nombre("0") == (0.0, None)   # un 0 publié reste 0
    assert rc.nombre("1 234,5") == (1234.5, None) and rc.nombre(-59.932) == (-59.932, None)
    assert rc.euros(22419.175, 1000) == 22419175 and rc.euros(None, 1000) is None


def test_codes_insee_depuis_les_codes_de_direction():
    assert rc.code_insee("010", "001") == "01001" and rc.code_insee("2A0", "004") == "2A004"
    assert rc.code_insee("971", "34") == "97134" and rc.code_insee("971", "134") == "97134"
    assert rc.code_insee("971", 1.0) == "97101" and rc.code_insee("976", "617") == "97617"
    assert rc.code_insee("592", "350") == "59350" and rc.code_insee("921", "002") == "92002"
    assert rc.code_insee("971", "00") is None and rc.code_insee("B31", "100") is None
    assert rc.code_dep(10.0) == "010" and rc.code_dep(130.0) == "130" and rc.code_dep("130.0") == "130"
    assert rc.code_dep("2A0") == "2A0" and rc.code_dep("b31") == "B31"


def test_arrondissements_paris_lyon_marseille():
    assert rc.arrondissement("750", "PARIS 01") == ("75056", "75101")
    assert rc.arrondissement("755", "Paris 20e Arrondissement") == ("75056", "75120")
    assert rc.arrondissement("131", "MARSEILLE 16EME") == ("13055", "13216")
    assert rc.arrondissement("690", "Lyon 9e Arrondissement") == ("69123", "69389")
    assert rc.arrondissement("690", "LYON") is None and rc.arrondissement("270", "LYONS-LA-FORET") is None
    assert rc.arrondissement("440", "PARIS 01") is None


def test_bornes_des_tranches():
    assert rc.bornes("0 à 10 000") == (0, 10000) and rc.bornes("12 001 à 13500") == (12001, 13500)
    assert rc.bornes("+ de 100 000") == (100000, None) and rc.bornes("Plus de 100 000") == (100000, None)
    assert rc.bornes("- de 9 000") == (None, 9000)
    with pytest.raises(ValueError):
        rc.bornes("01")
    assert rc.est_total("TOTAL") and rc.est_total(" Total ") and not rc.est_total("Totaux")


def test_somme_sans_somme_partielle():
    assert rc.somme([[1, 2, None], [3, 4, 5]]) == [4, 6, None]
    assert rc.somme([[1, -2], [3, 4]]) == [4, 2]


def test_unite_lue_dans_le_fichier():
    assert rc.facteur_unite(["Montants en milliers d'euros (exceptés ceux des RFR par tranche)"])[0] == 1000
    assert rc.facteur_unite(["(Montants en euros)"])[0] == 1
    assert rc.facteur_unite(["IRCOM revenus 2003"])[0] is None


ENTETE = ["", "Dép.", "Commune", "Libellé de la commune", "Revenu fiscal de référence par tranche (en euros)",
          "Nombre de foyers fiscaux", "Revenu fiscal de référence des foyers fiscaux", "Impôt net (total)*",
          "Nombre de foyers fiscaux imposés", "Revenu fiscal de référence des foyers fiscaux imposés",
          "Traitements et salaires", "", "Retraites et pensions", ""]
SOUS = [""] * 10 + ["Nombre de foyers concernés", "Montant", "Nombre de foyers concernés", "Montant"]


def test_colonnes_reperees_par_libelle_et_colonnes_cimr():
    pos = rc.colonnes_ircom(ENTETE, SOUS)
    assert [pos[c] for c in rc.COLONNES] == [5, 8, 6, 9, 7] and "cimr_eur" not in pos
    e2018 = ENTETE[:7] + ["Impôt net (total, avant CIMR)**", "Impôt net (total, après CIMR)*", "CIMR",
                          "Nombre de foyers fiscaux imposés ***",
                          "Revenu fiscal de référence des foyers fiscaux imposés ***"] + ENTETE[10:]
    pos = rc.colonnes_ircom(e2018, [""] * 2 + SOUS)
    assert pos["impot_net_avant_cimr_eur"] == 7 and pos["impot_net_eur"] == 8 and pos["cimr_eur"] == 9
    assert pos["foyers_imposes"] == 10


def test_lecture_d_une_feuille_avec_bloc_departement():
    lignes = [
        ["", "DGFiP"], ["", "IRCOM revenus 2024"], ["", "Montants en milliers d'euros (exceptés ceux des RFR par tranche)"],
        ["", "Dép.", "", "Département"] + ENTETE[4:],
        ["", "440", "", "LOIRE-ATLANTIQUE", "Total", 900, 40000.5, 2000.25, 450, 30000, 600, 25000, 300, 9000],
        ENTETE, SOUS,
        ["", "440", "001", "Abbaretz", "Total", 480, 22419.175, 1542.261, 256, 17338.246, 322, 12360.117, 180,
         5539.188],
        ["", "440", "002", "Aigrefeuille", "0 à 10 000", 120, 504.736, -2.137, "n.c.", "n.c.", 50, 315.371, 26, "."],
        ["", "440", "002", "Aigrefeuille", "Total", 420, 17581.325, "n.c.", 194, 12662.0, 278, 12639.0, 120, 3460.8],
        ["", "* Impôt sur le revenu émis par voie de rôle"],
    ]
    from collections import Counter
    m = Counter()
    f = rc.lire_feuille(lignes, "essai", m)
    assert f["facteur"] == 1000 and len(f["communes"]) == 3 and len(f["departement"]) == 1
    assert f["departement"][0]["valeurs"][0] == 900
    assert m["n.c."] == 3 and m["."] == 1
    assert f["notes"] == ["* Impôt sur le revenu émis par voie de rôle"]


def _passage():
    """Trois géographies : X2 fusionne dans X1 en 2016 ; Y1 couvre Y1 et Y2 jusqu'en 2015, puis Y2 est rétablie."""
    annees = [2015, 2016, 2026]
    atomes = [("01001", "01001", "01001"), ("01002", "01001", "01001"),
              ("01011", "01011", "01011"), ("01011", "01012", "01012"), ("01020", "01020", "01020")]
    return rc.Passage(annees, atomes, ["COM"] * len(atomes), "essai")


def _ligne(foyers):
    return {"nom": "x", "total": [foyers] + [1] * (len(rc.LUES) - 1), "tranches": None}


def test_recomposition_fusion_scission_et_absence():
    p = _passage()
    cibles = ["01001", "01011", "01012", "01020"]
    # géographie 2015 : la commune nouvelle 01001 est la somme de 01001 et 01002 ; 01011 couvre aussi 01012
    rec, rap = rc.recomposer({"01001": _ligne(10), "01002": _ligne(5), "01011": _ligne(7)}, 2015, p, cibles)
    assert rec["01001"]["ligne"][0] == 15 and rec["01001"]["recompose"] == ["01001", "01002"]
    assert rec["01011"]["etat"] == "perimetre" and rec["01012"]["etat"] == "perimetre"
    assert rec["01020"]["etat"] == "absente" and rap["non_rattaches"] == []
    # géographie 2016 : fusion appliquée par la source, chaque commune lue telle quelle
    rec, _ = rc.recomposer({"01001": _ligne(15), "01011": _ligne(4), "01012": _ligne(3), "01020": _ligne(2)},
                           2016, p, cibles)
    assert rec["01001"]["ligne"][0] == 15 and rec["01001"]["recompose"] is None
    assert rec["01011"]["ligne"][0] == 4 and rec["01012"]["ligne"][0] == 3
    # géographie mêlée : 01002 encore publiée à part dans un fichier en géographie 2016
    rec, rap = rc.recomposer({"01001": _ligne(10), "01002": _ligne(5)}, 2016, p, cibles)
    assert rec["01001"]["ligne"][0] == 15 and rap["codes_lus_dans_une_autre_geographie"] == 2
    # code inconnu de toutes les géographies : non rattaché, jamais attribué
    rec, rap = rc.recomposer({"99999": _ligne(1)}, 2016, p, cibles)
    assert rap["non_rattaches"] == ["99999"] and all("ligne" not in r for r in rec.values())


def test_recomposition_refusee_si_ensemble_incoherent():
    annees = [2012, 2013, 2026]
    atomes = [("02001", "02001", "02001"), ("02002", "02001", "02001"), ("02003", "02001", "02001")]
    p = rc.Passage(annees, atomes, ["COM"] * 3, "essai")
    # 02003 publiée à part alors que 02002 est déjà absorbée : aucune géographie ne donne cet ensemble
    rec, _ = rc.recomposer({"02001": _ligne(10), "02003": _ligne(2)}, 2013, p, ["02001"])
    assert rec["02001"]["etat"] == "incomplete"
    assert rec["02001"]["details"]["codes_source"] == ["02001", "02003"]


def test_geographie_par_difference_symetrique():
    p = _passage()
    assert rc.geographie_de({"01001", "01002", "01011", "01020"}, p, 2016)[0] == 2015
    assert rc.geographie_de({"01001", "01011", "01012", "01020"}, p, 2016)[0] in (2016, 2026)


# --- Fichiers publiés -----------------------------------------------------------------------------------------------

publie = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                            reason="site/data/revenus_communes absent : python pipeline/revenus_communes.py produire")


def _index():
    return json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))


def _communes():
    for f in sorted((DOSSIER / "communes").glob("*.json")):
        yield f, json.loads(f.read_text(encoding="utf-8"))


@publie
def test_un_fichier_par_departement_de_local_et_toutes_les_communes():
    idx = _index()
    geo = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in (SITE / "local" / "geo").glob("*.json")}
    assert {d["code"] for d in idx["departements"]} == set(geo) or not geo
    for f, d in _communes():
        assert f.stat().st_size < rc.MAX_OCTETS, f.name
        if geo:
            assert set(d["communes"]) == set(geo[f.stem]["communes"]), f.name
    tranches = sorted((DOSSIER / "tranches").rglob("*.json"))
    assert tranches and all(f.parent == DOSSIER / "tranches" for f in tranches)   # un fichier par département
    for f in tranches:
        assert f.stat().st_size < rc.MAX_OCTETS_TELECHARGEMENT, f
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["annees"] == sorted(int(a) for a in d["par_annee"]) and d["departement"]["code"] == f.stem


@publie
def test_series_alignees_et_raison_de_chaque_ligne_absente():
    idx = _index()
    annees = [a["annee"] for a in idx["annees"]]
    assert annees[0] <= 2002 and annees[-1] >= 2024 and annees == sorted(set(annees))
    for f, d in _communes():
        assert d["annees"] == annees and d["colonnes"] == rc.COLONNES
        for code, c in d["communes"].items():
            assert len(c["ircom"]) == len(annees), (f.name, code)
            etat = c.get("etat", {})
            for a, ligne in zip(annees, c["ircom"]):
                assert (ligne is None) == (str(a) in etat), (f.name, code, a)
                if ligne and ligne[0] is not None and ligne[1] is not None:
                    assert ligne[1] <= ligne[0], (f.name, code, a)   # foyers imposés <= foyers
            for a, codes in c.get("recompose", {}).items():
                assert codes and codes != [code] and c["ircom"][annees.index(int(a))] is not None, (f.name, code, a)
            if c.get("tranches"):
                t = json.loads((DOSSIER / "tranches" / f"{f.stem}.json").read_text(encoding="utf-8"))
                for a in c["tranches"]:
                    assert code in t["par_annee"][str(a)]["communes"], (code, a)


@publie
def test_valeurs_masquees_null_et_jamais_zero():
    t = json.loads((DOSSIER / "tranches" / "01.json").read_text(encoding="utf-8"))
    amberieu = t["par_annee"]["2024"]["communes"]["01004"]
    assert amberieu[1][1] is None   # « n.c. » publié par la DGFiP (foyers imposés, tranche 10 001 à 12 000)
    assert amberieu[0][4] < 0       # impôt net négatif publié tel quel (restitutions)
    idx = _index()
    assert all(a["marques_source"] for a in idx["annees"])
    assert "Jamais 0" in idx["regle_null"]


@publie
def test_exemples_nantes_paris():
    d = json.loads((DOSSIER / "communes" / "44.json").read_text(encoding="utf-8"))
    n = d["communes"]["44109"]
    i = d["annees"].index(2024)
    assert n["nom"] == "Nantes" and n["ircom"][i] == [204285, 101601, 6655252217, 5327343657, 512135884]
    assert n["filosofi"][0][2] == "publie" and n["filosofi"][1][1] is None
    p = json.loads((DOSSIER / "communes" / "75.json").read_text(encoding="utf-8"))["communes"]["75056"]
    assert all(len(v) == 20 for v in p["recompose"].values())


@publie
def test_controles_recalculables_et_ruptures():
    idx = _index()
    n = sans_masque = 0
    for _f, d in _communes():
        for c in d["controles"]:
            n += 1
            assert c["ecart"] == c["montant"] - c["autre_montant"]
            if c["ecart"] and not c["valeurs_non_communiquees"]:
                sans_masque += 1
    assert n == idx["controles"]["nombre"] and sans_masque <= 10
    r = {(x["annee"], x["grandeur"], x["type"]) for x in idx["ruptures"]}
    assert (2012, "foyers_imposes", "libelle") in r and (2018, "impot_net_eur", "colonnes") in r
    assert (2010, "tranches", "tranches") in r


@publie
def test_filosofi_statuts_coherents():
    idx = _index()
    assert [f["annee"] for f in idx["filosofi"]] == [2021, 2023]
    for _f, d in _communes():
        for c in d["communes"].values():
            for (med, men, statut), an in zip(c["filosofi"], d["filosofi_millesimes"]):
                assert (med is None) == (statut != "publie")
                if an == 2023:
                    assert men is None


@publie
def test_sources_declarees_au_catalogue_et_recherche_publique():
    idx = _index()
    cat = {s["id"] for s in json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))["sources"]}
    for cle, s in idx["sources"].items():
        if cle != "local":
            assert s["id_catalogue"] in cat, cle
    verdicts = {x["verdict"] for x in idx["recherche_publique"]["trouvailles"]}
    assert verdicts <= {"réutilisable tel quel", "à adapter", "inspiration seulement"}
    assert all(x["licence"] and x["derniere_modification"] for x in idx["recherche_publique"]["trouvailles"])


@pytest.mark.skipif(not (rc.DOSSIER_IRCOM.exists() and rc.ZIP_PASSAGE.exists() and rc.ZIP_FILO23.exists()),
                    reason="entrepôt data/lake absent : reproductibilité non vérifiable ici")
def test_produire_deux_fois_donne_les_memes_octets(tmp_path):
    sorties = []
    for graine in ("1", "2"):
        d = tmp_path / graine
        env = {**{k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}, "PYTHONHASHSEED": graine}
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "revenus_communes.py"), "produire", "--sortie",
                            str(d), "--annees", "2002,2018"], env=env, capture_output=True, text=True, timeout=1800)
        assert r.returncode == 0, r.stderr[-2000:]
        sorties.append({str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*.json"))})
    assert sorties[0] == sorties[1] and len(sorties[0]) > 150
