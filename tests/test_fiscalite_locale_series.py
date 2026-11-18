"""Séries longues de fiscalité locale par commune (pipeline/fiscalite_locale_series.py) : lecture du REI, fichiers publiés.

Les tests de lecture tournent sur des archives construites à la main (CSV en codes, classeur en libellés avec fichier
« trace ») ; les tests des fichiers sur site/data/fiscalite_locale_series (sautés si absent) ; la reproductibilité
sur les extraits de data/lake/fiscalite_locale_series (sautée sans entrepôt).
"""
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "fiscalite_locale_series"
sys.path.insert(0, str(ROOT / "pipeline"))
import fiscalite_locale_series as fl  # noqa: E402


# --- Règles de lecture (sans données) -------------------------------------------------------------------------------

def test_cellule_vide_null_jamais_zero():
    for v in ("", None, "  ", ".", "nc", "abc"):
        assert fl.nombre(v) is None, v
    assert fl.nombre("0") == 0.0 and fl.nombre(0) == 0.0       # un 0 publié reste 0
    assert fl.nombre("43.68000") == 43.68 and fl.nombre("1 234,5") == 1234.5
    assert fl.nombre("_x0033_") == 3.0                          # échappement des classeurs exportés
    assert fl.taux("0.14100") == 0.141 and fl.euros("186563") == 186563 and fl.euros("") is None


def test_codes_insee():
    assert fl.code_insee("01", "001") == "01001" and fl.code_insee("_x0030_1", "_x0030_01") == "01001"
    assert fl.code_insee("2A", "004") == "2A004" and fl.code_insee("971", "01") == "97101"
    assert fl.code_insee("44", "109") == "44109" and fl.code_insee("1", "1") == "01001"
    assert fl.code_insee("", "001") is None and fl.code_insee("44", "") is None
    assert fl.dep_de("97101") == "971" and fl.dep_de("2B033") == "2B" and fl.dep_de("44109") == "44"


def test_choix_des_variables_et_sommes():
    assert fl.choisir(("E12VOTE", "E12"), {"E12", "E12VOTE"}) == "E12VOTE"
    assert fl.choisir(("E12VOTE", "E12"), {"E12"}) == "E12"
    assert fl.choisir(("P33", "P33_1+P33_2+P33_3"), {"P33_1", "P33_3"}) == "P33_1+P33_3"
    assert fl.choisir(("P33", "P33_1+P33_2+P33_3"), {"P33", "P33_1"}) == "P33"   # jamais de double compte
    assert fl.choisir(("E42",), {"E12"}) is None


def test_libelle_controle_avant_lecture_par_position():
    assert fl.coherent("E12VOTE", "FB - COMMUNE / TAUX VOTE")
    assert fl.coherent("B32", "FNB - GFP / TAUX APPLICABLE SUR LE TERRITOIRE DE LA COMMUNE")
    assert fl.coherent("H33", "TH - INTERCOMMUNALITE / MONTANT REEL")
    assert fl.coherent("P33_2", "CFE - INTERCOMMUNALITE / PRODUIT REEL NET / FP UNIQUE OU EN ZAE")
    assert fl.coherent("E43", "FB - DÉPARTEMENT / MONTANT RÉEL")
    assert fl.coherent("F22", "FB - TAXE D'ENLEVEMENT O.M. /  TAUX PLEIN - TAUX NET")
    assert fl.coherent("F71", "FB - NIVEAU DE COLLECTIVITE PERCEVANT LA TEOM")
    assert not fl.coherent("E12", "FNB - COMMUNE / TAUX NET")          # foncier non bâti à la place du bâti
    assert not fl.coherent("E13", "FB - COMMUNE / TAUX NET")           # taux à la place du montant
    assert not fl.coherent("E32", "FB - COMMUNE / TAUX NET")           # commune à la place de l'intercommunalité


# --- Lecture d'archives construites à la main ------------------------------------------------------------------------

def _zip(tmp_path, membres: dict) -> Path:
    p = tmp_path / "rei.zip"
    with zipfile.ZipFile(p, "w") as z:
        for nom, octets in membres.items():
            z.writestr(nom, octets)
    return p


def test_archive_csv_en_codes(tmp_path):
    entete = "DEP;DIR;COM;LIBCOM;SIREPCI;OPTEPCI;E12;E12VOTE;E13;E32VOTE;E33;B12;B13;H12VOTE;H13THS;P12;P33;P33_1;F22;F13;F71"
    lignes = ["44;0;109;NANTES;244400404;FPU;40.0;40.42;1000;0.00;0;62.48;5;24.0;77;0.00;900;400;7.5;300;3",
              "971;0;01;LES ABYMES;200018653;FPU;;25.0;;0;0;64.65;;21.3;;0;;;;;1"]
    p = _zip(tmp_path, {"REI_2025.csv": ("\n".join([entete] + lignes) + "\n").encode("latin-1")})
    rows, meta = fl.extraire(p, 2025)
    assert [r["insee"] for r in rows] == ["44109", "97101"]
    n, a = rows
    assert n["taux_tfb_commune"] == 40.42 and n["produit_tfb_commune"] == 1000         # taux voté préféré
    assert n["produit_cfe_intercommunalite"] == 900                                     # total P33, pas P33+P33_1
    assert n["produit_th_commune"] == 77 and n["teom_niveau"] == 3
    assert n["taux_tfb_departement"] is None and meta["variables"]["taux_tfb_departement"] is None
    assert a["produit_tfb_commune"] is None and a["taux_cfe_commune"] == 0.0           # vide -> null ; 0 -> 0
    assert meta["variables"]["produit_cfe_intercommunalite"]["variable"] == "P33"


def _classeur(lignes: list[list]) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in lignes:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_classeur_en_libelles_lu_par_la_trace(tmp_path):
    libelles = ["DEPARTEMENT", "COMMUNE", "Libellé commune", "FB - COMMUNE / TAUX NET", "FB - COMMUNE / MONTANT REEL",
                "FB - DEPARTEMENT / TAUX NET", "FB - TAXE D'ENLEVEMENT O.M. / TOTAL - MONTANT REEL"]
    codes = ["DEP", "COM", "LIBCOM", "E12", "E13", "E42", "F13"]
    donnees = _classeur([libelles, ["_x0034_4", "_x0031_09", "NANTES", 27.51, 112526487, 15, None]])
    trace = _classeur([["NUMERO_DE_VARIABLE", "NOM_DE_VARIABLE", "LONGUEUR", "TITRE"]]
                      + [[i + 1, c, 5, libelles[i]] for i, c in enumerate(codes)])
    p = _zip(tmp_path, {"REI_COMPLET_2020.xlsx": donnees, "trace_rei_complet_2020.xlsx": trace})
    rows, meta = fl.extraire(p, 2020)
    assert rows[0]["insee"] == "44109" and rows[0]["taux_tfb_commune"] == 27.51
    assert rows[0]["produit_tfb_commune"] == 112526487 and rows[0]["produit_teom"] is None
    assert meta["variables"]["taux_tfb_departement"]["libelles"] == ["FB - DEPARTEMENT / TAUX NET"]


def test_classeur_mal_aligne_refuse(tmp_path):
    libelles = ["DEPARTEMENT", "COMMUNE", "FNB - COMMUNE / TAUX NET", "FB - COMMUNE / MONTANT REEL"]
    codes = ["DEP", "COM", "E12", "B12"]           # trace décalée : E12 tomberait sur le foncier non bâti
    donnees = _classeur([libelles, ["44", "109", 1.0, 2.0]])
    trace = _classeur([["NUMERO_DE_VARIABLE", "NOM_DE_VARIABLE", "LONGUEUR", "TITRE"]]
                      + [[i + 1, c, 5, ""] for i, c in enumerate(codes)])
    p = _zip(tmp_path, {"REI_2019.xlsx": donnees, "trace_2019.xlsx": trace})
    with pytest.raises(SystemExit, match="incohérent|introuvables|libellés"):
        fl.extraire(p, 2019)


def test_taux_deja_publies_null_et_produits_gardes():
    vide = {c: "" for c in fl.COLONNES_EXTRAIT}
    l10 = {**vide, "insee": "44109", "nom": "NANTES", "taux_tfb_commune": "27.51", "produit_tfb_commune": "100",
           "taux_cfe_commune": "0.0", "teom_niveau": "3"}
    l11 = {**l10, "taux_tfb_commune": "28.0", "produit_tfb_commune": "120"}
    metas = {a: {"variables": {f"produit_{k}": ({"variable": "X"} if k == "tfb_commune" else None)
                               for k, _, _ in fl.PRODUITS}} for a in (2010, 2011)}
    communes, totaux = fl.construire([2010, 2011], {2010: [l10], 2011: [l11]}, metas, deja=[2011])
    c = communes["44109"]
    assert c["taux"]["tfb_commune"] == [27.51, None]         # 2011 déjà dans local/taux
    assert c["taux"]["cfe_commune"] == [0, 0] or c["taux"]["cfe_commune"] == [0.0, 0.0]
    assert c["produits"]["tfb_commune"] == [100, 120] and c["teom_niveau"] == [3, 3]
    assert "th_commune" not in c["taux"]                     # série vide retirée
    assert totaux["tfb_commune"] == [100, 120] and totaux["teom"] == [None, None]


def test_decoupage_en_parties_contigues(monkeypatch):
    communes = {f"44{n:03d}": {"nom": "X" * 50, "taux": {"tfb_commune": [1.5] * 16}} for n in range(1, 301)}
    monkeypatch.setattr(fl, "CIBLE_OCTETS", 6000)
    parts = fl.decouper("44", communes, {"millesime": "m", "source": "s"})
    assert len(parts) > 1 and parts[0][0] == "44_1.json"
    vus = [c for _, p in parts for c in p["communes"]]
    assert vus == sorted(communes) and all(len(fl.dumps(p).encode()) <= 6000 for _, p in parts)


# --- Fichiers publiés ------------------------------------------------------------------------------------------------

publie = pytest.mark.skipif(not (DOSSIER / "index.json").exists(), reason="site/data/fiscalite_locale_series absent")


def _index():
    return json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))


def _fichiers():
    return sorted((DOSSIER / "communes").glob("*.json"))


@publie
def test_index_couvre_2010_a_la_derniere_annee_et_tous_les_fichiers():
    idx = _index()
    annees = [int(a) for a in idx["annees"]]
    assert annees[0] == 2010 and annees == list(range(2010, annees[-1] + 1)) and annees[-1] >= 2024
    listes = {p["fichier"] for d in idx["departements"] for p in d["parties"]}
    assert listes == {f"communes/{f.name}" for f in _fichiers()}
    assert len(idx["departements"]) >= 100
    for f in [DOSSIER / "index.json"] + _fichiers():
        assert f.stat().st_size < fl.MAX_OCTETS, f.name


@publie
def test_series_alignees_codes_dans_leur_partie_et_deja_publie_null():
    idx = _index()
    n = len(idx["annees"])
    deja = [idx["annees"].index(a) for a in idx["deja_publie"]["annees"]]
    bornes = {p["fichier"]: p for d in idx["departements"] for p in d["parties"]}
    total = 0
    for f in _fichiers():
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"] and d["annees"] == idx["annees"]
        b = bornes[f"communes/{f.name}"]
        assert len(d["communes"]) == b["communes"]
        for insee, c in d["communes"].items():
            assert b["premier"] <= insee <= b["dernier"] and fl.dep_de(insee) == d["departement"]
            for famille in ("taux", "produits"):
                for k, v in c.get(famille, {}).items():
                    assert len(v) == n, (insee, k)
                    if famille == "taux" and k in idx["deja_publie"]["colonnes"]:
                        assert all(v[i] is None for i in deja), (insee, k)
            dep = c.get("taux", {}).get("tfb_departement")
            if dep:
                assert all(v is None for a, v in zip(idx["annees"], dep) if int(a) >= 2021)
        total += len(d["communes"])
    assert total >= 36000


@publie
def test_exemples_nantes():
    idx = _index()
    part = next(p for d in idx["departements"] if d["departement"] == "44" for p in d["parties"]
                if p["premier"] <= "44109" <= p["dernier"])
    c = json.loads((DOSSIER / part["fichier"]).read_text(encoding="utf-8"))["communes"]["44109"]
    i10, i20 = idx["annees"].index("2010"), idx["annees"].index("2020")
    assert c["taux"]["tfb_commune"][i10] == 27.51 and c["taux"]["tfb_departement"][i10] == 8.53
    assert c["taux"]["tfb_commune"][i20] == 27.51 and c["produits"]["tfb_commune"][i20] == 112526487
    assert c["taux"]["cfe_intercommunalite_unique_ou_zone"][i20] == 31.49


@publie
def test_controle_local_taux_et_totaux():
    idx = _index()
    ctl = idx["controles"]["local_taux"]
    assert ctl["annees"] == idx["deja_publie"]["annees"]
    if ctl["annees"]:
        assert ctl["comparaisons"] > 10000 and ctl["ecarts"] <= ctl["comparaisons"]
    tot = idx["totaux_nationaux"]["produits"]["tfb_commune"]
    assert len(tot) == len(idx["annees"]) and all(isinstance(x, int) and x > 10**10 for x in tot)


@publie
def test_sources_declarees_au_catalogue_et_recherche_publique():
    idx = _index()
    cat = {s["id"] for s in json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))["sources"]}
    assert idx["sources"][0]["id_catalogue"] in cat
    trouv = idx["recherche_publique"]["trouvailles"]
    assert {x["verdict"] for x in trouv} <= {"réutilisable tel quel", "à adapter", "inspiration seulement"}
    assert all(x["licence"] and x["derniere_modification"] for x in trouv)


@pytest.mark.skipif(not (fl.EXTRAITS / f"rei_{fl.PREMIERE_ANNEE}.csv.gz").exists(),
                    reason="extraits data/lake/fiscalite_locale_series absents : reproductibilité non vérifiable ici")
def test_produire_deux_fois_donne_les_memes_octets(tmp_path):
    sorties = []
    for graine in ("1", "2"):
        d = tmp_path / graine
        env = {**{k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}, "PYTHONHASHSEED": graine}
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "fiscalite_locale_series.py"), "produire",
                            "--sortie", str(d)], env=env, capture_output=True, text=True, timeout=1800)
        assert r.returncode == 0, r.stderr[-2000:]
        sorties.append({str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*.json"))})
    assert sorties[0] == sorties[1] and len(sorties[0]) > 100
