"""Fonds européens structurels et d'investissement (pipeline/fonds_europeens.py) : cohérence, confidentialité, neutralité.

Les tests sur site/data/fonds_europeens tournent sans réseau ni entrepôt ; la reproductibilité demande l'entrepôt
(data/lake/europe/fe_cohesion_*, data/lake/_restreint/europe/fe_ops_*), sautée sinon.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "fonds_europeens"
LAKE = ROOT / "data" / "lake"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "pipeline"))
from test_neutralite import fautes, textes  # noqa: E402

import fonds_europeens as fe  # noqa: E402

FONDS_ATTENDUS = {"2014-2020": {"FEDER", "FSE", "IEJ", "FEADER", "FEAMP"},
                  "2021-2027": {"FEDER", "FSE+", "FTJ", "FEAMPA"},
                  "2023-2027": {"FEADER"}}
# Jugements propres à la mise en œuvre des fonds (en plus du lexique partagé) : le site décrit, il ne note pas.
JUGEMENTS = re.compile(r"(?<!\w)(?:retard\w*|sous-consomm\w*|sous-utilis\w*|absorption|gâch\w*|bon élève|mauvais élève|"
                       r"à la traîne|performan\w*|efficac\w* de la dépense|insuffisan\w*|excessi\w*)(?!\w)", re.I)


def _lire(rel: str):
    return json.loads((DATA / rel).read_text(encoding="utf-8"))


def _c(x) -> int:
    return round((x or 0) * 100)


@pytest.fixture(scope="module")
def index():
    return _lire("index.json")


@pytest.fixture(scope="module")
def programmes():
    return _lire("programmes.json")


# --- Outils (sans données) -------------------------------------------------------------------------------------


def test_rattachement_des_intitules_aux_regions():
    attendu = {
        "Bretagne - ERDF/ESF": "53", "Basse-Normandie - ERDF/ESF": "28", "Rhne-Alpes - ERDF/ESF": "84",
        "Provence-Alpes-CÃ´te d'Azur - Rural Development": "93", "Sud - Provence Alpes-Côte d'Azur - ERDF-ESF+-JTF": "93",
        "Guadeloupe et St Martin - ESF/ERDF": "01", "Saint Martin ERDF": "977", "Centre-Val de Loire - ERDF-ESF+": "24",
        "Interregional Massif Central - ERDF": "interregional", "Interregional Rhône-Saône - ERDF": "interregional",
        "Midi-Pyrénées et Garonne - ERDF/ESF/YEI": "76", "Lorraine et Vosges - ERDF/ESF/YEI": "44",
        "Franche-Comt et Jura - ERDF/ESF": "27", "Hauts de France ERDF-ESF+-JTF": "32", "Corse ERDF-ESF+": "94",
        "Île-de-France et bassin de la Seine - ERDF/ESF+": "11", "Pays de la Loire ERDF-ESF+-JTF": "52",
        "Réunion - Rural Development": "04", "Alsace - ESF/YEI": "44", "Limousin - ERDF/ESF": "75"}
    for titre, code in attendu.items():
        assert fe.region_du_titre(titre) == code, titre
    assert fe.region_du_titre("Employment and Social Inclusion - FR - ESF") is None


def test_lecture_des_montants_et_taux():
    assert fe.cents("1234,5") == 123450 and fe.cents("") == 0 and fe.cents("VOID") == 0
    assert fe.taux("16,67%") == 0.1667 and fe.taux("40.0") == 0.4 and fe.taux("0.42") == 0.42
    assert fe.taux("") is None
    assert fe.insee("35069.0") == "35069" and fe.insee("1053") == "01053" and fe.insee("x") is None
    assert fe.dep_unique("93") == "93" and fe.dep_unique("75,77,78") is None and fe.dep_unique("3") is None
    assert fe.serie_annuelle([100, 250, None, 300]) == [1.0, 1.5, None, 0.5]
    assert fe.periode_de("2014FR16M2OP003") == "2014-2020" and fe.periode_de("2023FR06AFSP001") == "2023-2027"


def test_identification_des_beneficiaires_regle_personnes_physiques():
    """Un bénéficiaire n'est nommé que s'il est une personne morale ; sinon motif d'agrégation, jamais de nom."""
    def op(**kw):
        return {"type_source": "", "siret": None, "nom_source": "", **kw}
    cle = fe.empreinte(fe.cle_nom("Commune de Testville"))
    rap = {"sirens": {"123456789": {"cj": "1000", "denomination": None},
                      "987654321": {"cj": "7210", "denomination": "COMMUNE DE TESTVILLE"}},
           "noms": {cle: {"candidats": 1, "siren": "987654321", "cj": "7210", "denomination": "COMMUNE DE TESTVILLE"},
                    fe.empreinte(fe.cle_nom("Association Ambigue")): {"candidats": 3}}}
    assert fe.identifier(op(type_source="Personne physique", nom_source="X"), rap, {})[3] == "personne_physique"
    assert fe.identifier(op(siret="12345678900011"), rap, {})[3] == "personne_physique"
    assert fe.identifier(op(siret="98765432100012"), rap, {})[:3] == ("987654321", "7210", "COMMUNE DE TESTVILLE")
    assert fe.identifier(op(nom_source="Commune de Testville"), rap, {})[3] == "nommé"
    assert fe.identifier(op(nom_source="Association Ambigue"), rap, {})[3] == "ambigu"
    assert fe.identifier(op(nom_source="Jean Martin"), rap, {})[3] == "nom_de_personne_possible"
    assert fe.identifier(op(nom_source="Inconnue Sans Equivalent"), rap, {})[3] == "non_rapproche"
    assert fe.identifier(op(siret="11122233300044"), rap, {})[3] == "siren_inconnu"


# --- Fichiers produits ------------------------------------------------------------------------------------------


def test_periodes_fonds_et_totaux(index):
    assert [t["periode"] for t in index["totaux"]] == fe.PERIODES
    for t in index["totaux"]:
        assert set(t["par_fonds"]) == FONDS_ATTENDUS[t["periode"]], t["periode"]
        for k in ("prevu_ue_eur", "paye_ue_eur"):
            somme = sum(_c(b[k]) for b in t["par_fonds"].values() if b[k] is not None)
            assert abs(somme - _c(t["total"][k])) <= 1, (t["periode"], k)
    tot = {t["periode"]: t["total"] for t in index["totaux"]}
    assert tot["2014-2020"]["prevu_ue_eur"] > 30e9 and tot["2021-2027"]["prevu_ue_eur"] > 15e9
    assert tot["2023-2027"]["prevu_national_eur"] is None   # non publié pour le FEADER du plan stratégique PAC


def test_prevu_ue_plus_national_egale_total(programmes):
    for p in programmes["programmes"]:
        for f, b in p["par_fonds"].items():
            if None not in (b["prevu_ue_eur"], b["prevu_national_eur"], b["prevu_total_eur"]):
                assert abs(_c(b["prevu_ue_eur"]) + _c(b["prevu_national_eur"]) - _c(b["prevu_total_eur"])) <= 2, \
                    (p["cci"], f)


def test_programmes_tous_rattaches_et_conservation_par_region(index, programmes):
    assert not index["verification"]["programmes_non_rattaches"]
    connus = {"2014FR16M2OP003": "53", "2021FR16FFPR010": "32", "2014FR06RDRP042": "44", "2014FR16RFOP001":
              "interregional", "2021FR16RFPR001": "977", "2014FR05M2OP001": "01", "2023FR06AFSP001": "national",
              "2014FR05SFOP001": "national", "2021FR05SFPR001": "national"}
    par_cci = {p["cci"]: p for p in programmes["programmes"]}
    for cci, groupe in connus.items():
        assert par_cci[cci]["groupe"] == groupe, cci
    assert all(p["groupe"] != "non_rattache" for p in programmes["programmes"])
    regions = _lire("regions.json")["regions"]
    assert {r["code"] for r in regions} >= set(fe.REGIONS) - {"977"} | {"national"}
    for t in index["totaux"]:
        for k in ("prevu_ue_eur", "paye_ue_eur", "decide_eur"):
            somme = sum(_c(per["total"][k]) for r in regions for per in r["periodes"]
                        if per["periode"] == t["periode"] and per["total"][k] is not None)
            if t["total"][k] is not None:
                assert abs(somme - _c(t["total"][k])) <= 25, (t["periode"], k)
    ordre = [r["code"] for r in regions]
    assert ordre == sorted(ordre, key=lambda c: (list(fe.REGIONS) + ["national", "interregional"]).index(c))


def test_themes_retombent_sur_les_totaux(index):
    th = {p["periode"]: p for p in _lire("themes.json")["periodes"]}
    tot = {t["periode"]: t for t in index["totaux"]}
    for per in ("2014-2020", "2021-2027"):
        somme = sum(_c(t["total"]["prevu_ue_eur"]) for t in th[per]["themes"] if t["total"]["prevu_ue_eur"])
        assert abs(somme - _c(tot[per]["total"]["prevu_ue_eur"])) <= 100, per
        assert all(t["libelle"] for t in th[per]["themes"])
    feader = sum(_c(m["prevu_ue_eur"]) for m in th["2014-2020"]["mesures_feader"] if m["prevu_ue_eur"])
    assert abs(feader - _c(tot["2014-2020"]["par_fonds"]["FEADER"]["prevu_ue_eur"])) <= 100
    for t in th["2021-2027"]["themes"]:
        assert t["objectifs_specifiques"] and all(o["libelle"] for o in t["objectifs_specifiques"]), t["code"]


def test_paiements_cumules_et_annuels(index):
    tot = {t["periode"]: t for t in index["totaux"]}
    for per in _lire("annees.json")["periodes"]:
        p = per["paiements_ue"]
        if not p["annees"]:
            continue
        assert abs(_c(p["cumul_total_eur"][-1]) - _c(tot[per["periode"]]["total"]["paye_ue_eur"])) <= 10, per["periode"]
        assert abs(sum(_c(x) for x in p["annuel_total_eur"]) - _c(p["cumul_total_eur"][-1])) <= 10
        assert p["annee_partielle"] == p["annees"][-1]
        for f, serie in p["cumul_par_fonds_eur"].items():
            assert len(serie) == len(p["annees"]), f


def test_frr_eurostat():
    f = _lire("frr.json")
    r = f["fonds_recus"]
    assert len(r["total_eur"]) == len(f["annees"])
    assert abs(sum(_c(x) for x in r["total_eur"] if x) - _c(r["cumul_eur"])) <= 1
    assert r["cumul_eur"] > 20e9 and "Eurostat" in f["source"]
    assert {c["code"] for c in f["emplois"]["categories"]} >= {"TOTAL", "CUR", "CAP"}


def test_listes_operations_confidentialite_et_conservation():
    idx = _lire("operations.json")
    assert idx["listes"] and [x["id"] for x in idx["listes"]] == sorted(x["id"] for x in idx["listes"])
    for l in idx["listes"]:
        d = json.loads((ROOT / "site" / "data" / l["fichier"]).read_text(encoding="utf-8"))
        col = d["colonnes"]
        i_cj, i_siren, i_den = col.index("categorie_juridique"), col.index("siren"), col.index("denomination")
        for row in d["operations"]:
            assert len(row) == len(col)
            assert re.fullmatch(r"[2-9]\d{3}", row[i_cj]) and row[i_cj] not in {"2110", "2210", "2310", "2385"}
            assert re.fullmatch(r"\d{9}", row[i_siren]) and row[i_den]
        # conservation : nommées + agrégées = total publié, par période et fonds
        for t in d["totaux"]:
            nn = [n for n in d["non_nommes"] if n["periode"] == t["periode"] and n["fonds"] == t["fonds"]]
            assert t["operations"] == t["operations_nommees"] + sum(n["nombre"] for n in nn), l["id"]
            assert abs(_c(t["cout_total_eur"]) - _c(t["cout_total_nomme_eur"])
                       - sum(_c(n["cout_total_eur"]) for n in nn)) <= len(nn) + 1, l["id"]
        assert d["controles"]["operations"] == sum(t["operations"] for t in d["totaux"])
        assert d["controles"]["nommees"] == len(d["operations"]) == l["operations_nommees"]
        assert not {"nom_source", "beneficiaire", "description", "resume", "adresse"} & set(json.dumps(d).split('"'))
        for c in d["comparaison_commission"]:
            assert c["lecture_ecart"] and c["cci"] in {p["cci"] for p in d["programmes"]}


def test_aucun_beneficiaire_feader_ni_aide_pac_nommes():
    for f in (DATA / "operations").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if "colonnes" in d:
            i = d["colonnes"].index("fonds")
            assert not {r[i] for r in d["operations"]} & {"FEADER"}, f.name


def test_recherche_publique_et_sources(index):
    for t in index["recherche_publique"]["trouvailles"]:
        assert t["verdict"] in {"réutilisable tel quel", "à adapter", "inspiration seulement"}
        assert t["licence"] and t["mise_a_jour"]
    assert any("europe-en-france" in s["url"] for s in index["sources_inaccessibles"])
    assert {lien["fichier"] for lien in index["liens"]} >= {"ue/contribution.json", "ue/beneficiaires/index.json"}


def test_neutralite_des_textes_rediges():
    erreurs = []
    for f in sorted(DATA.rglob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        for cle, t in textes(doc):
            erreurs += [f"{f.name} [{cle}] {r}" for r in fautes(t)]
        if f.parent.name == "operations":
            doc = {k: v for k, v in doc.items() if k not in ("operations", "non_nommes", "programmes")}
        for t in _textes(doc):
            if JUGEMENTS.search(t):
                erreurs.append(f"{f.name} jugement : {t[:120]}")
    assert not erreurs, "\n".join(erreurs[:20])


def _textes(x):
    if isinstance(x, dict):
        for k, v in x.items():
            if k not in ("libelle_source", "titre", "nom", "url"):
                yield from _textes(v)
    elif isinstance(x, list):
        for v in x:
            yield from _textes(v)
    elif isinstance(x, str):
        yield x


@pytest.mark.skipif(not (LAKE / "europe" / "fe_cohesion_1420_prevu.json").exists(), reason="entrepôt data/lake absent")
def test_produire_reproductible(tmp_path):
    empreintes = []
    for graine, sortie in (("1", tmp_path / "a"), ("2", tmp_path / "b")):
        env = {**{k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}, "PYTHONHASHSEED": graine}
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "fonds_europeens.py"), "produire",
                            "--sortie", str(sortie)], capture_output=True, text=True, env=env, timeout=600)
        assert r.returncode == 0, r.stderr[-2000:]
        empreintes.append({str(f.relative_to(sortie)): hashlib.sha256(f.read_bytes()).hexdigest()
                           for f in sorted(sortie.rglob("*.json"))})
    assert empreintes[0] == empreintes[1]
