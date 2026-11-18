"""Assurance maladie par territoire (pipeline/assurance_maladie_territoires.py) : règles du module et cohérence des
fichiers publiés, sans réseau. La vérification des montants saisis dans les PDF demande l'entrepôt (sautée sinon)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "assurance_maladie_territoires"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
import assurance_maladie_territoires as amt  # noqa: E402
from test_neutralite import fautes, textes  # noqa: E402


# --- fonctions pures (toujours testées) ------------------------------------------------------------------------------

def test_absence_jamais_zero():
    for v in (None, "", "NS", "NC", "ns", "-", True):
        assert amt.nombre(v) is None, v
    assert amt.motif_absence("NS") == "secret_statistique" and amt.motif_absence("NC") == "non_calcule"
    assert amt.motif_absence("") == "absent" and amt.motif_absence("12") is None


def test_nombres_des_fichiers_mensuels():
    assert amt.nombre("12.502,30") == 12502.30
    assert amt.nombre("9.671.38") == 9671.38
    assert amt.nombre("0,00") == 0.0 and amt.nombre("-101,5") == -101.5
    assert amt.nombre("168508748") == 168508748.0
    assert amt.md(-0.0001, 2) == 0.0 and str(amt.md(-0.0001, 2)) == "0.0"


def test_lignes_dont_jamais_additionnees_et_postes_connus():
    postes = {p for p, _ in amt.POSTES_ES}
    assert amt.poste_es("dont dotation populationnelle SSR") is None
    assert amt.poste_es('"dont facturation directe (actes, consultations externes, scanner-irmn)"') is None
    cas = {"Frais de séjours et de soins (GHS)": "sejours_mco", "OQN SSR": "smr", "OQN Psychiatrie": "psychiatrie",
           "Médicament en sus du GHS": "medicaments_dispositifs_en_sus", "Dispositifs Médicaux (LPP)":
               "medicaments_dispositifs_en_sus", "Forfaits de dialyse et DTP": "dialyse",
           "Forfaits d'hospitalisation à domicile (GHT)": "hospitalisation_domicile",
           "Enfance Inadapté prive": "medico_social", "Scanner": "imagerie", "Moyen Séjour": "smr",
           "Long Séjour": "autres", "MIGAC ODMCO": "sejours_mco", "Conventions internationales": "autres"}
    for lib, attendu in cas.items():
        assert amt.poste_es(lib) == attendu, lib
        assert attendu in postes


def test_statuts_et_sous_objectifs():
    assert amt.statut_es("OQN lucratif conventionné") == "prive_lucratif"
    assert amt.statut_es("Privé non lucratif conventionné") == "prive_non_lucratif"
    assert amt.statut_es("Public proprement dit") == "public"
    cas = {"ONDAM TOTAL": "total", "Soins de ville ": "soins_de_ville", "Établissements de santé ":
           "etablissements_sante", "Etablissements et services médico-sociaux": "medico_social",
           "Dépenses relatives aux établisemments et services pour personnes âgées": "medico_social_personnes_agees",
           "Contribution de l'assurance maladie aux dépenses en établissements et services pour personnes handicapées":
               "medico_social_personnes_handicapees",
           "Dépenses relatives au Fonds d'intervention régional et soutien national à l'investissement ": "fir",
           "Autres prises en charges ": "autres_prises_en_charge", "Source : DSS/SDEPF/6B": None}
    for lib, attendu in cas.items():
        assert amt.id_sous_objectif(lib) == attendu, lib


def test_constat_pdf_lu_dans_le_texte_et_refus_si_document_change():
    texte = " ".join(amt.CONSTATS_PDF[2019][3].values())
    c = amt.lire_constat_pdf(2019, texte)
    assert c["valeurs"]["total"]["constat"] == 200.2 and c["valeurs"]["total"]["ecart_objectif_initial"] == -0.1
    assert c["valeurs"]["etablissements_sante"]["objectif_rectifie"] == 82.6
    with pytest.raises(SystemExit):
        amt.lire_constat_pdf(2019, texte.replace("200,2", "200,9"))


def test_sources_documentees():
    for cle, s in amt.SOURCES.items():
        assert s["url"].startswith("https://") and s["page"].startswith("https://"), cle
        for k in ("titre", "producteur", "millesime", "licence", "verdict", "format"):
            assert s[k], (cle, k)
    assert all(i["source"] and i["motif"] for i in amt.INACCESSIBLES)
    assert {t["verdict"].split(" (")[0] for t in amt.RECHERCHE_PUBLIQUE["trouvailles"]} <= {
        "réutilisable tel quel", "à adapter", "inspiration seulement", "réutilisé par liens"}


# --- fichiers publiés -------------------------------------------------------------------------------------------------

fichiers = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                              reason="site/data/assurance_maladie_territoires absent : lancer produire")


def charger(rel: str):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index():
    return charger("assurance_maladie_territoires/index.json")


@pytest.fixture(scope="module")
def ondam():
    return charger("assurance_maladie_territoires/ondam.json")


@fichiers
def test_departements_complets_et_ordre_par_code(index):
    codes = [d["code"] for d in index["departements"]]
    assert len(codes) == 101 and {"2A", "2B", "971", "976"} <= set(codes)
    assert codes == sorted(codes, key=lambda c: (len(c) > 2, c))
    assert "jamais un classement" in index["ordre"]["regle"]
    for an, rel in index["fichiers"]["departements"].items():
        d = charger(rel)
        assert d["annee"] == int(an) and [x["code"] for x in d["departements"]] == codes


@fichiers
def test_secret_statistique_null_avec_motif(index):
    vus = 0
    for rel in index["fichiers"]["departements"].values():
        for dep in charger(rel)["departements"]:
            for g, c in dep["honoraires"].items():
                for k in ("sans_depassement", "depassements"):
                    if c[k] is None:
                        assert c[f"{k}_absence"] in ("secret_statistique", "non_calcule", "absent"), (dep["code"], g)
                        vus += 1
                    else:
                        assert f"{k}_absence" not in c
    assert vus > 0  # la source applique le secret statistique (orthoptistes de petits départements)


@fichiers
def test_france_publiee_et_controles_de_la_source(index):
    for c in index["controles_professions"]:
        assert abs(c["difference"]) <= 2, c  # arrondis de la Cnam
    der = index["france"][str(index["derniere_annee"])]
    p = der["prescriptions_medecins"]
    somme = sum(p[k] for k in ("medicaments", "dispositifs_medicaux", "biologie", "soins_infirmiers", "kinesitherapie",
                               "transports", "indemnites_journalieres", "autres"))
    assert abs(somme - p["total"]) <= 10


@fichiers
def test_etablissements_prives_somme_et_lignes_dont_exclues(index):
    an = index["derniere_annee_etablissements_prives_complete"]
    assert an in index["annees_etablissements_prives"]
    d = charger(index["fichiers"]["departements"][str(an)])
    assert d["etablissements_prives_complet"] and len(d["etablissements_prives_mois"]) == 12
    hors = sum(index["hors_departements_etablissements_prives"].get(str(an), {}).values())
    somme = sum(x["etablissements_prives"]["total"] for x in d["departements"] if x["etablissements_prives"])
    assert abs(somme + hors - d["france"]["etablissements_prives"]["total"]) <= len(d["departements"]) + 2
    for x in d["departements"]:
        e = x["etablissements_prives"]
        if e:
            assert abs(sum(e["postes"].values()) - e["total"]) <= 10
            assert abs(sum(e["statuts"].values()) - e["total"]) <= 5
    assert all(v["poste"] is None for v in index["correspondance_series_etablissements"].values()
               if v["libelle_source"].strip('"').lower().startswith("dont"))
    for an2 in sorted(set(index["annees"]) - set(index["annees_etablissements_prives"])):
        assert charger(index["fichiers"]["departements"][str(an2)])["france"]["etablissements_prives"] is None


@fichiers
def test_ondam_publie_sans_recalcul(ondam):
    assert ondam["annees"] == list(range(2019, ondam["derniere_annee"] + 1)) and ondam["derniere_annee"] >= 2025
    for an, c in ondam["constats"].items():
        v = c["valeurs"]
        for s, x in v.items():
            assert x["constat"] is not None and x["constat"] > 0, (an, s)
        ms = v["medico_social_personnes_agees"]["constat"] + v["medico_social_personnes_handicapees"]["constat"]
        assert abs(ms - v["medico_social"]["constat"]) <= 0.15, an
    for c in ondam["controles_arrondis"]:
        assert abs(c["difference_arrondis"]) <= 0.15, c
    assert ondam["constats"]["2024"]["valeurs"]["total"]["constat"] == 256.4
    assert ondam["objectifs"]["2027"]["valeurs"]["medico_social"] is None  # non publié : jamais recalculé
    assert {r["annee"] for r in ondam["ruptures_de_champ"]} >= {2020, 2021}


@fichiers
def test_liens_vers_les_autres_vues(index, ondam):
    for lien in index["liens"] + ondam["liens"]:
        assert (SITE / lien["fichier"]).exists(), lien["fichier"]


@fichiers
def test_textes_neutres_sans_tiret_long(index, ondam):
    erreurs = []
    for doc in (index, ondam):
        for cle, t in textes(doc):
            erreurs += [f"[{cle}] {r} : {t[:80]}" for r in fautes(t)]
    assert not erreurs, "\n".join(erreurs)
    for f in DOSSIER.rglob("*.json"):
        assert "—" not in f.read_text(encoding="utf-8"), f.name


@fichiers
def test_taille_des_fichiers():
    for f in DOSSIER.rglob("*.json"):
        assert f.stat().st_size < 1_000_000, f.name


# --- entrepôt (sauté sans data/lake) ------------------------------------------------------------------------------------

@pytest.mark.skipif(not amt.chemin("amt_plfss2021_annexe7").exists(), reason="entrepôt absent")
def test_montants_saisis_presents_dans_les_pdf():
    for an in amt.CONSTATS_PDF:
        assert amt.lire_constat_pdf(an)["valeurs"]["total"]["constat"] > 0
