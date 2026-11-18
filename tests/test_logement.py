"""Logement (pipeline/logement.py) : cohérence des fichiers publiés, renvois, neutralité, sans réseau.

Les tests sur site/data/logement tournent sans réseau ni entrepôt ; la reproductibilité demande l'entrepôt
(data/lake/logement), sautée sinon.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "logement"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
import logement  # noqa: E402
from test_neutralite import fautes, textes  # noqa: E402

if not (DOSSIER / "index.json").exists():
    pytest.skip("site/data/logement absent : lancer `python pipeline/logement.py produire`", allow_module_level=True)

INDEX = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
MPR = json.loads((DOSSIER / "maprimerenov.json").read_text(encoding="utf-8"))
PTZ = json.loads((DOSSIER / "ptz.json").read_text(encoding="utf-8"))
AIDES = ("ensemble", "apl", "alf", "als")


def charger(rel: str):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


def annees_aides():
    return sorted(INDEX["aides_personnelles"]["fichiers"].items())


# --- Fichiers et en-têtes --------------------------------------------------------------------------------------------

def test_fichiers_annonces_presents_entetes_et_tailles():
    rels = [f["fichier"] for f in INDEX["fichiers"]]
    assert "logement/maprimerenov.json" in rels and "logement/ptz.json" in rels
    for an, rel in annees_aides():
        assert rel in rels and rel == f"logement/aides_personnelles/{an}.json"
    publies = {str(p.relative_to(SITE)) for p in DOSSIER.rglob("*.json")}
    assert publies == set(rels) | {"logement/index.json"}, "fichier publié hors index ou annoncé absent"
    for rel in publies:
        p = SITE / rel
        assert p.stat().st_size < 1_000_000, rel
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"] and all(u.startswith("https://") for u in d["urls_sources"]), rel


def test_aides_personnelles_par_departement_depuis_2017():
    annees = INDEX["aides_personnelles"]["annees"]
    assert annees[0] == 2017 and annees[-1] >= 2025 and annees == list(range(annees[0], annees[-1] + 1))
    for an, rel in annees_aides():
        d = charger(rel)
        assert d["annee"] == int(an) and d["colonnes"] == ["foyers_decembre", "montant_annuel_eur", "montant_moyen_eur"]
        assert len(d["departements"]) == 101 and set(d["hors_departements"]) <= {"978", "99", "XX"}
        for code, v in list(d["departements"].items()) + list(d["hors_departements"].items()):
            for aide in AIDES:
                f, m, moy = v["aides"][aide]
                assert f is None or (isinstance(f, int) and f >= 0), (an, code, aide)
                assert m is None or (isinstance(m, int) and m >= 0), (an, code, aide)
                assert moy is None or moy >= 0
                if m is not None and f:
                    assert moy is not None


# --- Cohérence interne ------------------------------------------------------------------------------------------------

def _somme_ok(parties, tout, tol_f=5, tol_m=20):
    if tout[0] is None or tout[1] is None or any(p[0] is None or p[1] is None for p in parties):
        return None
    return abs(sum(p[0] for p in parties) - tout[0]) <= tol_f and abs(sum(p[1] for p in parties) - tout[1]) <= tol_m


@pytest.mark.parametrize("an,rel", annees_aides())
def test_apl_alf_als_et_types_retombent_sur_l_ensemble(an, rel):
    d = charger(rel)
    verifies = 0
    for code, v in list(d["departements"].items()) + list(d["hors_departements"].items()):
        ens = v["aides"]["ensemble"]
        for parties in ([v["aides"][a] for a in ("apl", "alf", "als")],
                        [v["type_logement"][t]["ensemble"] for t in logement.NOMS_TYPES_LOGEMENT],
                        [v["type_parc"][t]["ensemble"] for t in logement.NOMS_TYPES_PARC]):
            ok = _somme_ok(parties, ens)
            assert ok is not False, (an, code)
            verifies += ok is True
    assert verifies >= 250, verifies
    c = d["controles"]
    for cle in ("aides_moins_ensemble", "types_logement_moins_ensemble", "types_parc_moins_ensemble"):
        assert abs(c[cle]["foyers"]) <= 5 and abs(c[cle]["montant_eur"]) <= 20, (an, cle, c[cle])


@pytest.mark.parametrize("an,rel", annees_aides())
def test_france_jeu_national_et_controle_recalculable(an, rel):
    d = charger(rel)
    lignes = list(d["departements"].values()) + list(d["hors_departements"].values())
    for aide in AIDES:
        fr = d["france"]["aides"][aide]
        c = d["controles"]["france_moins_somme_des_lignes"][aide]
        somme_f = sum(v["aides"][aide][0] for v in lignes if v["aides"][aide][0] is not None)
        somme_m = sum(v["aides"][aide][1] for v in lignes if v["aides"][aide][1] is not None)
        assert c["foyers_decembre"] == fr[0] - somme_f
        assert c["montant_annuel_eur"] == fr[1] - somme_m
        assert abs(c["foyers_decembre"]) <= 5, (an, aide, c)       # même jeu, même champ (arrondis)
        if c["lignes_sans_montant_annuel"] == 0:
            assert abs(c["montant_annuel_eur"]) <= 50, (an, aide, c)
        else:   # lignes à mois manquant (Mayotte, Saint-Martin, code 99) : le national les compte sur les autres mois
            assert c["montant_annuel_eur"] >= 0


@pytest.mark.parametrize("an,rel", annees_aides())
def test_ensemble_identique_a_la_vue_des_prestations(an, rel):
    d = charger(rel)
    r = d["renvoi_total"]
    if r is None:
        assert an not in (charger("prestations/index.json")["fichiers"]["departements"]
                          if (SITE / "prestations" / "index.json").exists() else {})
        return
    p = charger(r["fichier"])
    for code, v in d["departements"].items():
        mien, sien = v["aides"]["ensemble"], p["departements"][code][r["cle"]]
        assert mien[0] == sien[0], (an, code)
        if mien[1] is None or sien[1] is None:
            assert mien[1] == sien[1], (an, code)
        else:
            assert abs(mien[1] - sien[1]) <= 10, (an, code, mien, sien)


def test_valeurs_absentes_jamais_zero():
    for an, rel in annees_aides():
        d = charger(rel)
        lignes = {**d["departements"], **d["hors_departements"]}
        for code, mois in d["mois_absents_a_la_source"].items():
            assert code in lignes, (an, code)
            t = lignes[code]["aides"]["ensemble"]
            assert t[1] is None, (an, code, t)          # un mois absent : montant annuel null, jamais 0
            if f"{an}-12" in mois:
                assert t == [None, None, None], (an, code)
    assert INDEX["aides_personnelles"]["mois_absents_a_la_source"].get("976"), "Mayotte : décembres absents à la source"


def test_ecarts_aides_publies_et_recalculables():
    objets = {e["objet"] for e in INDEX["ecarts"]}
    assert {"aides_personnelles_apl", "aides_personnelles_alf", "aides_personnelles_als", "maprimerenov_montants",
            "maprimerenov_dossiers"} <= objets
    for e in INDEX["ecarts"]:
        assert e["ecart"] == e["montant"] - e["autre_montant"], e
        if e["autre_montant"]:
            assert abs(e["ecart_pct"] - (e["montant"] - e["autre_montant"]) / e["autre_montant"] * 100) < 0.06, e
        assert e["source"] != e["autre_source"] and len(e["lecture_ecart"]) > 30


# --- MaPrimeRénov' ------------------------------------------------------------------------------------------------------

def test_maprimerenov_cumuls_calculs_et_somme_des_departements():
    dates = MPR["dates_cumul"]
    assert dates == sorted(dates) and dates[0] == "2022-12-01" and len(MPR["departements"]) == 101
    dec = [d for d in dates if d.endswith("-12-01")]
    assert MPR["annees_calculees"] == [int(d[:4]) for d in dec[1:]]
    for code, v in list(MPR["departements"].items()) + [("FR", MPR["france"])]:
        assert len(v["cumul"]) == len(dates) and len(v["annee"]) == len(dec) - 1
        for i, a in enumerate(v["annee"]):
            if a is not None:
                assert a == v["cumul"][i + 1] - v["cumul"][i], code
        assert all(x is None or x >= 0 for x in v["cumul"])
    for c in MPR["controle_somme_departements"]:
        assert c["ecart"] == 0 and c["somme_departements"] == c["france"], c
    assert "calculé" in MPR["definitions"]["annee"]


def test_maprimerenov_tableau_du_senat_repris_tel_quel():
    lignes = {l["programme"]: l for l in MPR["budget_etat"]["lignes"]}
    assert lignes["174"]["execution_2024"] == 700 and lignes["135"]["execution_2024"] == 400
    assert lignes["total"]["execution_2024"] == 1100 and lignes["total"]["execution_2022"] == 2102
    for c in MPR["budget_etat"]["controle_total"]:
        somme = sum(lignes[p][c["colonne"]] for p in ("174", "362", "135"))
        assert c["somme_des_programmes"] == somme and c["ecart"] == somme - lignes["total"][c["colonne"]]
    # le total 2022 publié ne retombe pas sur ses lignes : l'écart est publié, jamais corrigé
    assert {c["colonne"]: c["ecart"] for c in MPR["budget_etat"]["controle_total"]}["execution_2022"] == 52
    for l in MPR["budget_etat"]["liens"]:
        assert (SITE / l["fichier"]).exists() and logement._noeud(charger(l["fichier"]), l["id"]) is not None


def test_maprimerenov_national_sdes_et_aucun_montant_departemental():
    s = MPR["national_sdes"]
    assert s["annees"][0] == 2020 and len(s["etapes"]["soldes"]) == len(s["annees"])
    assert all(v is None or v > 0 for v in s["soldes"]["subvention_maprimerenov_eur"])
    for v in MPR["departements"].values():
        assert set(v) == {"nom", "cumul", "annee"}     # aucun montant inventé par département
    assert any("par département" in i["source"] for i in INDEX["sources_inaccessibles"])


# --- Prêts à taux zéro ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cle,annees,montant", [("ptz", "annees_ptz", "montant_ptz_eur"),
                                                ("eco_ptz", "annees_eco_ptz", "montant_pret_eur")])
def test_prets_agregats_coherents(cle, annees, montant):
    b, ans = PTZ[cle], PTZ[annees]
    assert ans == list(range(ans[0], ans[-1] + 1))
    territoires = list(b["departements"].values()) + list(b["autres_territoires"].values()) \
        + [b["departement_non_renseigne"]]
    for i, _ in enumerate(ans):
        assert b["france"]["nombre"][i] == sum(t["nombre"][i] or 0 for t in territoires)
        assert b["france"]["nombre"][i] == sum(t["nombre"][i] or 0 for t in b["par_type"].values())
        masque = any(t["nombre"][i] and t[montant][i] is None for t in territoires)
        if not masque:
            assert abs(b["france"][montant][i] - sum(t[montant][i] or 0 for t in territoires)) <= len(territoires)
    for t in territoires + [b["france"]] + list(b["par_type"].values()):
        assert all(n is None or n >= 1 for n in t["nombre"]), "0 publié au lieu de null"
        assert all((n is None) == (m is None) or (n is not None and n < logement.SEUIL_SECRET)
                   for n, m in zip(t["nombre"], t[montant]))
    assert len(b["departements"]) >= (100 if cle == "ptz" else 96)   # éco-PTZ : aucun prêt recensé outre-mer


def test_ptz_total_de_la_base_et_corse_avant_2005():
    if PTZ["annees_ptz"][-1] == 2021:   # édition d'avril 2022 : 3 538 396 prêts annoncés par la SGFGAS
        assert sum(PTZ["ptz"]["france"]["nombre"]) == 3538396
    corse = PTZ["ptz"]["autres_territoires"]["20"]["nombre"]
    i2005 = PTZ["annees_ptz"].index(2005)
    assert all(n is not None for n in corse[:i2005]) and all(n is None for n in corse[i2005 + 1:])
    assert PTZ["ptz"]["departements"]["2A"]["nombre"][0] is None   # codé 20 à la source en 1995 : null, pas 0


def test_ptz_n_est_pas_une_depense_et_renvoie_aux_depenses_fiscales():
    assert "n'est pas une dépense de l'État" in PTZ["avertissement"]
    ids = {r["id"] for r in PTZ["renvois"]}
    if (SITE / "niches" / "mesures.json").exists():
        mesures = {m["id"] for m in charger("niches/mesures.json")["mesures"]}
        assert ids == {"210313", "210321"} and ids <= mesures
    for r in PTZ["renvois"]:
        assert not {"meur", "couts", "montant", "montant_eur"} & set(r), "montant de dépense fiscale recopié"


# --- Renvois ----------------------------------------------------------------------------------------------------------

def _liens(x):
    if isinstance(x, dict):
        if "vue" in x and "fichier" in x:
            yield x
        for v in x.values():
            yield from _liens(v)
    elif isinstance(x, list):
        for v in x:
            yield from _liens(v)


def test_liens_existent_et_ne_recopient_pas_les_depenses_fiscales():
    liens = list(_liens(INDEX))
    vues = {l["vue"] for l in liens}
    assert {"arbre_etat", "realisations", "depenses_fiscales_programmes", "depenses_fiscales_mesures",
            "operateurs"} <= vues
    mesures = {m["id"] for m in charger("niches/mesures.json")["mesures"]} \
        if (SITE / "niches" / "mesures.json").exists() else None
    for l in liens:
        assert (SITE / l["fichier"]).exists(), l
        if l["vue"] == "arbre_etat":
            n = logement._noeud(charger(l["fichier"]), l["id"])
            assert n is not None and abs(n["md"] - l["md"]) < 1e-9, l
        if l["vue"] == "depenses_fiscales_mesures" and mesures is not None:
            assert set(l.get("mesures") or [l.get("id")]) <= mesures
        if l["vue"].startswith("depenses_fiscales"):
            assert not {"meur", "couts", "md", "montant"} & set(l), l
    codes = {p["code"] for p in INDEX["programmes"]}
    assert {"109", "135", "177"} <= codes
    p174 = next(p for p in INDEX["programmes"] if p["code"] == "174")
    assert not any(l["vue"].startswith("depenses_fiscales") for l in p174["liens"])
    assert {o["id"] for o in INDEX["operateurs"]} >= {"anah", "fnap"}


def test_aides_a_la_pierre_reliees_et_absence_departementale_dite():
    a = INDEX["aides_a_la_pierre"]
    assert any(l["vue"] == "arbre_etat" and l["id"].endswith("/135-01") for l in a["liens"])
    assert any(l["vue"] == "operateurs" and l["id"] == "fnap" for l in a["liens"])
    assert any("pierre" in i["source"] for i in INDEX["sources_inaccessibles"])


# --- Sources, neutralité, confidentialité --------------------------------------------------------------------------

def test_sources_declarees_au_catalogue_et_recherche_publique():
    cat = {s["id"]: s for s in json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))["sources"]}
    for cle, s in INDEX["sources"].items():
        assert s["id_catalogue"] in cat, cle
        assert cat[s["id_catalogue"]]["domaine"] == "logement"
    r = INDEX["recherche_publique"]
    verdicts = {t["verdict"].split(" (")[0] for t in r["trouvailles"]}
    assert {"réutilisable tel quel", "à adapter", "inspiration seulement"} <= verdicts
    for t in r["trouvailles"]:
        if "github.com/" in t["url"] and t["url"] != "https://github.com/search":
            assert t.get("dernier_commit") and t.get("licence"), t["nom"]
    assert len(INDEX["sources_inaccessibles"]) >= 3


def test_libelles_neutres():
    erreurs = []
    for f in sorted(DOSSIER.rglob("*.json")):
        for cle, t in textes(json.loads(f.read_text(encoding="utf-8"))):
            erreurs += [f"{f.name} [{cle}] {r} : {t[:100]}" for r in fautes(t)]
    assert not erreurs, "\n".join(erreurs[:10])


def test_aucune_donnee_individuelle():
    interdits = {"commune", "communes", "insee", "cins", "epci", "nbsmic", "revenu", "pm2", "txno", "adresse", "nom_beneficiaire"}
    for f in DOSSIER.rglob("*.json"):
        def cles(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    yield k
                    yield from cles(v)
            elif isinstance(x, list):
                for v in x:
                    yield from cles(v)
        assert not interdits & set(cles(json.loads(f.read_text(encoding="utf-8")))), f.name


# --- Unitaires ----------------------------------------------------------------------------------------------------------

def test_triplet_annee_incomplete_et_decembre_absent():
    mois = {m: 10.0 for m in range(1, 13)}
    assert logement.triplet({"mois": mois, "montant": 1200.0, "foyers": 120.0}) == [10, 1200, 10.0]
    sans_mars = {m: 10.0 for m in range(1, 13) if m != 3}
    assert logement.triplet({"mois": sans_mars, "montant": 1100.0, "foyers": 110.0}) == [10, None, None]
    sans_dec = {m: 10.0 for m in range(1, 12)}
    assert logement.triplet({"mois": sans_dec, "montant": 1100.0, "foyers": 110.0}) == [None, None, None]
    assert logement.triplet(None) == [None, None, None]


def test_codes_et_agregation_des_prets():
    assert logement.code_departement("1") == "01" and logement.code_departement("2a") == "2A"
    assert logement.code_departement("") is None and logement.code_departement(None) is None
    noms = {"01": "Ain", "02": "Aisne"}
    lignes = [(2020, "1", "1", 3, 300.0, 900.0), (2020, "0", "02", 10, 1000.0, 3000.0), (2021, "1", None, 2, 50.0, 80.0),
              (2021, "1", "20", 7, 70.0, 140.0)]
    a = logement.agreger_prets(lignes, ["montant_ptz_eur", "montant_prets_operation_eur"], {"0": "ancien", "1": "neuf"},
                               [2020, 2021], noms)
    assert a["france"]["nombre"] == [13, 9] and a["france"]["montant_ptz_eur"] == [1300, 120]
    assert a["departements"]["01"]["montant_ptz_eur"] == [None, None]      # moins de 5 prêts : montant masqué
    assert a["departements"]["01"]["nombre"] == [3, None]                   # aucune ligne en 2021 : null, pas 0
    assert a["departements"]["02"]["montant_ptz_eur"] == [1000, None]
    assert a["autres_territoires"]["20"]["nombre"] == [None, 7]
    assert a["departement_non_renseigne"]["nombre"] == [None, 2]
    with pytest.raises(SystemExit):
        logement.agreger_prets([(2020, "1", "999", 1, 1.0, 1.0)], ["a", "b"], {"1": "neuf"}, [2020], noms)


def test_controle_total_senat_publie_sans_corriger():
    t = {"174": {c: 1 for c in logement.SENAT_COLONNES.values()}, "362": {c: 2 for c in logement.SENAT_COLONNES.values()},
         "135": {c: 3 for c in logement.SENAT_COLONNES.values()}, "total": {c: 5 for c in logement.SENAT_COLONNES.values()}}
    assert {c["ecart"] for c in logement.controle_total_senat(t)} == {1}


# --- Reproductibilité ---------------------------------------------------------------------------------------------------

@pytest.mark.skipif(not (logement.LAKE / "logement_caf_type_logement_dep.parquet").exists(),
                    reason="entrepôt data/lake/logement absent : reproductibilité non vérifiable ici")
def test_produire_deux_fois_donne_les_memes_octets(tmp_path):
    empreintes = []
    for graine in ("1", "2"):
        d = tmp_path / graine
        env = {**{k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}, "PYTHONHASHSEED": graine}
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "logement.py"), "produire", "--sortie", str(d)],
                           env=env, capture_output=True, text=True, timeout=1200)
        assert r.returncode == 0, r.stderr[-2000:]
        empreintes.append({str(f.relative_to(d)): hashlib.sha256(f.read_bytes()).hexdigest()
                           for f in sorted(d.rglob("*.json"))})
    assert empreintes[0] == empreintes[1]
