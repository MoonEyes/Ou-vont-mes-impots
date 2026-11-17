"""Territoires (pipeline/territoires.py) : cohérence des fichiers publiés et règles de lecture, sans réseau.

Les tests de lecture tournent sur des valeurs construites à la main ; les tests de cohérence sur site/data/territoires
(sautés si absent) ; la reproductibilité sur l'entrepôt (sautée sans data/lake).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "territoires"
sys.path.insert(0, str(ROOT / "pipeline"))
import territoires as t  # noqa: E402

CIVILITE = re.compile(r"\b(M\.|MM\.|Mme|Mlle|Monsieur|Madame|Mademoiselle)\s")


# --- Règles de lecture (sans données) -------------------------------------------------------------------------------

def test_valeurs_absentes_jamais_zero():
    for v in ("ND", "NR", "NA", "Pas d'inventaire", ">25%", "Entrée au dispositif", "", None, "38;62%"):
        assert t.nombre(v) is None, v
    assert t.nombre("0") == 0 and t.nombre(0) == 0  # un 0 publié reste 0
    assert t.marque("ND") == "ND" and t.marque(12.5) is None and t.marque("12,5") is None
    assert t.valeur_et_marque("NR") == (None, "NR")


def test_formats_francais():
    assert t.nombre("52,95 %") == 52.95
    assert t.nombre("46 559,19 €") == 46559.19
    assert t.nombre("1 234,5") == 1234.5
    assert t.euros(1234.5) == 1234 and t.euros(None) is None
    assert t.par(None, 10) is None and t.par(10, 0) is None and t.par(10, 4) == 2.5


def test_codes_departement_dgcl():
    assert t.norm_dep("001") == "01" and t.norm_dep("044") == "44" and t.norm_dep("44-") == "44"
    assert t.norm_dep("20A") == "2A" and t.norm_dep("20B") == "2B" and t.norm_dep("67A") == "67"
    assert t.norm_dep("971") == "971" and t.norm_dep("nan") is None and t.norm_dep("") is None
    assert t.dep_de_insee("44109") == "44" and t.dep_de_insee("97411") == "974"


def test_ecart_recalculable_et_absent_si_une_valeur_manque():
    e = t.ecart("a", 110, "b", 100, "lecture de test", annee=2024)
    assert e["ecart"] == 10 and e["ecart_pct"] == 10.0 and e["annee"] == 2024
    assert t.ecart("a", None, "b", 100, "x") is None and t.ecart("a", 1, "b", None, "x") is None


# --- Fichiers publiés -----------------------------------------------------------------------------------------------

publie = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                            reason="site/data/territoires absent : python pipeline/territoires.py produire")


def _index():
    return json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))


def _deps():
    for f in sorted(DOSSIER.glob("*.json")):
        if f.name != "index.json":
            yield f, json.loads(f.read_text(encoding="utf-8"))


@publie
def test_un_fichier_par_departement_de_local_sous_5_mo():
    idx = _index()
    geo = {f.stem for f in (SITE / "local" / "geo").glob("*.json")}
    codes = {d["code"] for d in idx["departements"]}
    assert codes == geo or not geo
    for d in idx["departements"]:
        p = SITE / d["fichier"]
        assert p.exists() and p.stat().st_size < 5_000_000, d["fichier"]


@publie
def test_couverture_des_trois_sources():
    c = _index()["couverture"]
    inv = c["investissement_etat"]
    assert inv["annees"][0] == 2018 and inv["annees"][-1] >= 2025 and inv["programmes"] == ["119"]
    assert {"DETR", "DSIL", "DPV", "DSID"} <= set(inv["dispositifs"])
    assert inv["projets"] == inv["projets_nommes"] + inv["exclus_personnes_physiques_ou_non_identifies"]["projets"] \
        + inv["sans_departement"]["projets"]
    assert inv["departements"] >= 100
    assert [e["edition"] for e in c["sru"]["editions"]][-1] >= 2026 and c["sru"]["departements"] >= 90
    assert c["aide_sociale"]["annees"][0] == 1999 and c["aide_sociale"]["annees"][-1] >= 2024
    assert c["aide_sociale"]["departements"] >= 100


@publie
def test_totaux_projets_reconstitues_depuis_les_departements():
    idx = _index()
    tot = {}
    for _f, d in _deps():
        ie = d.get("investissement_etat")
        if not ie:
            continue
        for b in ie["beneficiaires"]:
            assert b["projets"] and b["subvention_totale_eur"] == sum(p[4] or 0 for p in b["projets"])
            for an, x in b["totaux"].items():
                assert x["projets"] == sum(1 for p in b["projets"] if str(p[0]) == an)
        for an, x in ie["totaux"].items():
            for k, v in x.items():
                s = tot.setdefault(an, {}).setdefault(k, [0, 0])
                s[0] += v["projets"]
                s[1] += v["subvention_eur"] or 0
    for an, x in idx["totaux"]["investissement_etat"].items():
        for k, v in x.items():
            assert tot[an][k] == [v["projets"], v["subvention_eur"]], (an, k)


@publie
def test_personnes_physiques_jamais_nommees():
    for f, d in _deps():
        for b in (d.get("investissement_etat") or {}).get("beneficiaires", []):
            assert b["nom"] and "prenom" not in b, f.name
            assert b["siren"] is None or re.fullmatch(r"\d{9}", b["siren"]), (f.name, b["id"])
            assert b["type"] in t.TYPES_PUBLICS or b["siren"], (f.name, b["id"])  # sinon SIRENE a confirmé
            for p in b["projets"]:
                assert p[2] is None or not CIVILITE.search(p[2]), (f.name, p[2])


@publie
def test_liens_vers_local_existent():
    for f, d in _deps():
        for rel in d["liens"].values():
            assert (SITE / rel).exists(), (f.name, rel)
        ie = d.get("investissement_etat") or {}
        for insee, refs in ie.get("par_commune", {}).items():
            for _ident, dep in refs:
                assert (DOSSIER / f"{dep}.json").exists(), (f.name, insee, dep)


@publie
def test_ecarts_publies_et_recalculables():
    idx = _index()
    tous = list(idx["ecarts"])
    for _f, d in _deps():
        tous += d["ecarts"]
    assert len(tous) == len(idx["ecarts"]) + idx["ecarts_departements"]["nombre"]
    sources = {e["source"] for e in tous}
    assert {"calcul_drees_376_population_ofgl", "drees_376_apa_domicile_brute", "somme_des_collectivites"} <= sources
    for e in tous:
        assert abs(e["montant"] - e["autre_montant"] - e["ecart"]) <= 0.011, e
        if e["autre_montant"]:
            assert abs(e["ecart_pct"] - e["ecart"] / e["autre_montant"] * 100) < 0.011, e
        assert len(e["lecture"]) > 20


@publie
def test_exemple_nantes_et_loire_atlantique():
    d = json.loads((DOSSIER / "44.json").read_text(encoding="utf-8"))
    ie = d["investissement_etat"]
    nantes = [b for b in ie["beneficiaires"] if b["insee"] == "44109"]
    assert len(nantes) == 1 and nantes[0]["siren"] == "214401093" and nantes[0]["nom"] == "Nantes"
    assert ["244400404", "44"] in ie["par_commune"]["44109"]  # Nantes Métropole
    sru = d["sru"]["communes"]["44109"]["editions"]
    assert sru["2026"]["taux_sru"] and sru["2026"]["deficitaire"] is False
    a = {c["code"]: c for c in d["aide_sociale"]["collectivites"]}["44"]
    for poste in ("total", "apa", "pch", "ase", "rsa_allocation", "ash_pa_etablissement",
                  "ph_hebergement_etablissement"):
        assert any(v["eur"].get("2024") for v in a["postes"][poste].values()), poste
    assert a["postes"]["total"]["brute"]["eur"]["2024"] > a["postes"]["total"]["nette"]["eur"]["2024"]
    assert a["isd"]["cont_depenses_brutes_aide_sociale_hab"]["2024"] > 0
    assert a["apa_domicile"]["2024"]["eur_par_beneficiaire"] and a["pch"]["2024"]["eur_par_personne_decembre"]


@publie
def test_collectivites_uniques_sans_double_compte_affiche():
    for dep in ("67", "68", "2A", "2B"):
        d = json.loads((DOSSIER / f"{dep}.json").read_text(encoding="utf-8"))
        uniques = [c for c in d["aide_sociale"]["collectivites"] if c["code"] in ("6AE", "20R")]
        assert uniques and "ne pas additionner" in uniques[0]["perimetre"], dep


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


@pytest.mark.skipif(not (ROOT / "data" / "lake" / "collectivites" / t.ID_DGCL).exists(),
                    reason="entrepôt data/lake absent : reproductibilité non vérifiable ici")
def test_produire_deux_fois_donne_les_memes_octets(tmp_path):
    sorties = []
    for graine in ("1", "2"):
        d = tmp_path / graine
        env = {**{k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}, "PYTHONHASHSEED": graine}
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "territoires.py"), "produire", "--sortie", str(d)],
                           env=env, capture_output=True, text=True, timeout=1800)
        assert r.returncode == 0, r.stderr[-2000:]
        sorties.append({f.name: f.read_bytes() for f in sorted(d.glob("*.json"))})
    assert sorties[0] == sorties[1]
