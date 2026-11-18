"""Territoires comparables (pipeline/typologies.py) : lecture des sources, statistiques, liste fermée des croisements.

Les tests de lecture tournent sur des fichiers construits à la main ; les tests des fichiers publiés sur
site/data/typologies (sautés si absent).
"""
import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "typologies"
sys.path.insert(0, str(ROOT / "pipeline"))
import typologies as ty  # noqa: E402


# --- Règles (sans données) -------------------------------------------------------------------------------------------

def test_nombre_null_jamais_zero():
    for v in ("", None, "  ", "nc", "abc"):
        assert ty.nombre(v) is None, v
    assert ty.nombre("0") == 0.0 and ty.nombre("1 234,5") == 1234.5 and ty.nombre(12) == 12.0


def test_codes():
    assert ty.code5("1001") == "01001" and ty.code5("2A004") == "2A004" and ty.code5(44109) == "44109"
    assert ty.dep_de("97101") == "971" and ty.dep_de("2B033") == "2B" and ty.dep_de("44109") == "44"


def test_quantiles_interpolation_lineaire():
    t = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert ty.quantile(t, 0.5) == 3.0 and ty.quantile(t, 0.25) == 2.0 and ty.quantile(t, 1.0) == 5.0
    assert ty.quantile([10.0, 20.0], 0.5) == 15.0
    with pytest.raises(ValueError):
        ty.quantile([], 0.5)


def test_case_trop_petite_sans_quantiles():
    bornes = ty.bornes_bandes([float(i) for i in range(100)])
    petite = ty.case_stats([(1.0, 2.0)] * (ty.N_MIN - 1), bornes, "euros par habitant", "euros par habitant")
    assert petite["x"] is None and petite["y"] is None and "motif" in petite
    assert all(b["y"] is None for b in petite["bandes"])
    grande = ty.case_stats([(float(i), float(i)) for i in range(100)], bornes, "euros par habitant",
                           "euros par habitant")
    assert grande["y"]["q"][2] == 49.5 and grande["y"]["moyenne_communes"] == 49.5
    assert sum(b["n"] for b in grande["bandes"]) == 100 and len(grande["bandes"]) == ty.N_BANDES


def test_bornes_des_strates():
    assert ty.verifier_strates({"0": [0, 99], "3": [500, 1999], "10": [100000, 2_000_000]}) == []
    assert ty.verifier_strates({"3": [480, 1999]}) and ty.verifier_strates({"11": [1, 2]})
    assert ty.libelle_strate("0") == "moins de 100 habitants"
    assert ty.libelle_strate("10").endswith("habitants ou plus")


def test_passage_stable():
    p = ty.Passage({2023: {"01001": {"01001"}, "01002": {"01002", "01003"}}},
                   {2023: {"01001": {"01001"}, "01002": {"01002"}, "01003": {"01002"}}})
    assert p.stable(2023, "01001") and not p.stable(2023, "01002") and not p.stable(2023, "99999")
    assert p.stable(ty.COG, "01002")


def test_lecture_ofgl_et_anciennes_communes(tmp_path):
    f = tmp_path / "ofgl.csv"
    ent = ["exer", "com_code", "insee", "tranche_population", "agregat", "montant", "ptot", "ptot_n",
           "euros_par_habitant"]
    lignes = [
        ["2023", "01001", "01001", "3", "Dépenses totales", "1000", "10", "11", "100"],
        ["2023", "01002", "01002", "2", "Dépenses totales", "500", "5", "300", "100"],   # commune nouvelle 2024 :
        ["2023", "01002", "01003", "2", "Dépenses totales", "400", "4", "300", "100"],   # deux comptes 2023
        ["2023", "01004", "01004", "0", "Encours de dette", "0", "50", "50", "0"],        # 0 publié reste 0
        ["2023", "01005", "01005", "0", "Encours de dette", "", "50", "50", ""],
    ]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(ent)
    w.writerows(lignes)
    f.write_text("﻿" + buf.getvalue(), encoding="utf-8")
    val, strate, ctrl = ty.lire_ofgl(f)
    assert val[(2023, "01001")]["depenses_totales"][0] == 100.0
    assert "depenses_totales" in val[(2023, "01002")]["_perimetre"]
    assert val[(2023, "01004")]["encours_dette"][0] == 0.0
    assert val[(2023, "01005")]["encours_dette"][0] is None
    assert strate == {"01001": "3", "01002": "2", "01004": "0", "01005": "0"}
    assert ctrl["ecarts_euros_par_habitant"]["nombre"] == 0 and ctrl["lignes_anciennes_communes"] == 1
    lignes.append(["2023", "01006", "01006", "0", "Autre agrégat", "1", "1", "1", "1"])
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(ent)
    w.writerows(lignes)
    f.write_text(buf.getvalue(), encoding="utf-8")
    with pytest.raises(ValueError):
        ty.lire_ofgl(f)


def test_lecture_xlsx_sans_feuille_de_styles():
    """Classeur minimal écrit à la main (sans styles.xml), lu par le lecteur interne."""
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   '<sheet name="Composition_communale" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<si><t>CODGEO</t></si><si><t>CATEAAV2020</t></si><si><t>01001</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
                   '2006/main"><sheetData><row r="1"><c r="A1"><v>titre</v></c></row>'
                   '<row r="2"><c r="A2" t="s"><v>0</v></c><c r="C2" t="s"><v>1</v></c></row>'
                   '<row r="3"><c r="A3" t="s"><v>2</v></c><c r="C3"><v>20</v></c></row></sheetData></worksheet>')
    f = ty.feuilles_xlsx(b.getvalue())
    t = ty.table(f["Composition_communale"], "CODGEO")
    assert t == [{"CODGEO": "01001", "": None, "CATEAAV2020": "20"}]


def test_croisements_predefinis_meme_annee():
    """Règle 13 : chaque croisement porte sur deux grandeurs de la même année ; liste fermée de 6 à 10."""
    assert 6 <= len(ty.CROISEMENTS) <= 10
    ids = [c["id"] for c in ty.CROISEMENTS]
    assert len(set(ids)) == len(ids)
    for c in ty.CROISEMENTS:
        vx, vy = ty.VARIABLES[c["x"]], ty.VARIABLES[c["y"]]
        assert vx["annee"] == vy["annee"] == c["annee"], c["id"]
        assert c["x"] != c["y"]
        assert str(c["annee"]) in c["titre"]


def test_aucun_coefficient_ni_regression_dans_le_code_publie():
    texte = (ROOT / "pipeline" / "typologies.py").read_text(encoding="utf-8")
    for interdit in ("corrcoef", "linregress", "polyfit", "pearson", "spearman", "r2_score"):
        assert interdit not in texte.lower()


# --- Fichiers publiés --------------------------------------------------------------------------------------------------

def _index():
    p = DOSSIER / "index.json"
    if not p.exists():
        pytest.skip("site/data/typologies absent")
    return json.loads(p.read_text(encoding="utf-8"))


def test_index_liste_fermee_et_fichiers():
    idx = _index()
    assert [c["id"] for c in idx["croisements"]] == [c["id"] for c in ty.CROISEMENTS]
    publies = sorted(p.stem for p in (DOSSIER / "croisements").glob("*.json"))
    assert publies == sorted(c["id"] for c in ty.CROISEMENTS)      # aucun croisement hors de la liste
    assert idx["avertissement"] == ty.AVERTISSEMENT
    assert "ne dit pas que l'un explique l'autre" in idx["avertissement"]
    assert "moyennes de communes, pas d'habitants" in idx["avertissement"]


def _cles(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _cles(v)
    elif isinstance(x, list):
        for v in x:
            yield from _cles(v)


def test_croisements_publies():
    idx = _index()
    for c in idx["croisements"]:
        d = json.loads((DOSSIER / c["fichier"]).read_text(encoding="utf-8"))
        assert d["x"]["annee"] == d["y"]["annee"] == d["annee"] == c["annee"]
        assert d["statut"] == "calculé par le site" and d["methode"] and d["avertissement"] == ty.AVERTISSEMENT
        assert not {k for k in _cles(d) if re.search(r"coef|regress|correl|pente|r2", k)}
        assert set(d["facettes"]) == {"densite", "strate", "aav"}     # vue par case toujours avec l'ensemble
        assert d["ensemble"]["n"] == d["communes"]
        for fac in d["facettes"].values():
            assert sum(cs["n"] for cs in fac["cases"]) + fac["communes_sans_case"] == d["communes"]
            for cs in fac["cases"]:
                if cs["n"] < d["n_min"]:
                    assert cs["x"] is None and cs["y"] is None
                for b in cs["bandes"]:
                    assert (b["y"] is None) == (b["n"] < d["n_min"])
                    if b["y"]:
                        assert b["y"] == sorted(b["y"])
        assert len(d["bandes_bornes"]) == ty.N_BANDES + 1 and d["bandes_bornes"] == sorted(d["bandes_bornes"])


def test_communes_null_avec_motif():
    idx = _index()
    total = 0
    for dep in idx["departements"]:
        d = json.loads((DOSSIER / dep["fichier"]).read_text(encoding="utf-8"))
        assert d["colonnes"] == list(ty.VARIABLES)
        for c, v in d["communes"].items():
            total += 1
            for k, val in zip(d["colonnes"], v["v"]):
                if val is None:
                    assert v.get("motifs", {}).get(k), (c, k)
                else:
                    assert k not in v.get("motifs", {})
    assert total == idx["couverture"]["communes_cog"]


def test_strates_controlees():
    idx = _index()
    assert idx["controles"]["strates_hors_bornes"] == []
    assert idx["controles"]["ofgl"]["ecarts_euros_par_habitant"]["nombre"] == 0
    assert idx["strates_ofgl"]["statut"] == "calculé par le site"
    assert {c["code"] for c in idx["facettes"]["strate"]["cases"]} == set(ty.STRATES_OFGL)
