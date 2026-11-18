"""Millésimes du budget de l'État : exécution 2025 préparée (non affichée) et vérification des éditions attendues.

Le site montre par défaut l'exécution 2024 (arbre site/data/arbre/, jeu « budget vert » du PLF 2026, retraité au format
PLF 2026 par la direction du budget). Les résultats de la gestion 2025 (PLRG 2025) sont publiés depuis avril 2026. Ce
module prépare la vue « exécution 2025 » sans rien changer à la vue par défaut : le passage relève du propriétaire du
site. Il publie aussi, pour chaque source signalée « en retard » par la page de fraîcheur au 18 novembre 2026, ce que
les producteurs officiels ont effectivement publié à cette date.

Commandes :
    python collecte/collecte.py etat_plrg_2024 etat_plrg_2025   (réseau, collecteur du dépôt, contrôle d'intégrité
        collecte/integrite.py ; un refus 401/403/429 est noté, jamais contourné)
    python pipeline/millesimes.py produire [--sortie DOSSIER]   (sans réseau)

Entrées (lecture seule) :
    data/lake/etat/etat_plrg_<a>/Annexe1-Etat_CP-<a>.csv   dépenses constatées du budget général par programme et titre
    data/lake/etat/etat_plrg_<a>/Annexe2-Etat_CP-<a>.csv   comptes spéciaux (avances à l'audiovisuel public)
    data/raw/situation_budgetaire.json                      situation mensuelle budgétaire au 31/12 (prélèvements sur
                                                            recettes, contrôles), étape « base »
    pipeline/grands_postes.json, pipeline/niveaux.json      mêmes conventions que l'arbre du site
    site/data/arbre/racine.json                             exécution 2024 affichée (comparaison de méthode)
    web/src/**/*.ts, pipeline/*.py                          relevé des écrans et pipelines qui lisent la vue par défaut

Sorties (site/data/millesimes/, contrat docs/contrat_interface.md, schémas docs/schemas/millesimes_index.schema.json
et arbre_etat.schema.json) :
    index.json                  vérification des éditions attendues, comparaison 2024 / 2025, dossier de bascule
    execution2025/racine.json   arbre grand poste > mission > programme de l'exécution 2025 (format des arbres du site)

Sorties reproductibles : dates = collecte de l'entrepôt (pipeline/reproductible.py) et dates de constat écrites ici.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arbre  # noqa: E402
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "etat"
RAW = ROOT / "data" / "raw"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "millesimes"
WEB = ROOT / "web" / "src"
POSTES = json.loads((Path(__file__).parent / "grands_postes.json").read_text(encoding="utf-8"))
NIVEAUX = json.loads((Path(__file__).parent / "niveaux.json").read_text(encoding="utf-8"))

ODS = "https://data.economie.gouv.fr/explore/dataset"
AN = "https://www.assemblee-nationale.fr/dyn/contenu/visualisation"
AN_PLF27 = "https://www2.assemblee-nationale.fr/static/17/Annexes-DL/PLF_2027"
DOSSIER_PLF27 = "https://www.assemblee-nationale.fr/dyn/17/dossiers/plf_2027"
CONSTAT_LE = "2026-11-18"
UNITE_ARBRE = "milliards d'euros (crédits de paiement)"

PLRG = {
    2024: {"dossier": LAKE / "etat_plrg_2024", "dataset": "plrg-2024", "id": "etat_plrg_2024",
           "publie": "2025-04-29"},
    2025: {"dossier": LAKE / "etat_plrg_2025",
           "dataset": "projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-"
                      "lannee-plrg-2025", "id": "etat_plrg_2025", "publie": "2026-04-22"},
}
PSR = {"PSRCT": "PSR au profit des collectivités territoriales", "PSRUE": "PSR au profit de l'Union européenne"}
AUDIOVISUEL = "Avances à l'audiovisuel public"


def src_plrg(a: int, annexe: str) -> str:
    return f"{ODS}/{PLRG[a]['dataset']}/ (PLRG {a}, {annexe}, dépenses constatées)"


SRC_SITUATION = f"{ODS}/situations-mensuelles-budgetaires-series-longues/ (situation au 31 décembre)"
SRC_ARBRE_SITE = "site/data/arbre/racine.json (exécution 2024 affichée : budget vert du PLF 2026, retraité)"


# --- Lecture -----------------------------------------------------------------------------------------------------------

def nombre(v) -> float:
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))


def lire_csv(chemin: Path) -> list[dict]:
    if not chemin.exists():
        raise SystemExit(f"{chemin.relative_to(ROOT)} absent : lancer « python collecte/collecte.py "
                         f"{chemin.parent.name} »")
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def programme(libelle: str) -> tuple[str, str]:
    m = re.search(r"^(.*?)\s*-\s*(\d{3})\s*$", libelle)
    if not m:
        raise SystemExit(f"programme illisible : {libelle!r}")
    return m.group(2), m.group(1).strip()


def situation(annee: int) -> dict[str, float]:
    col = f"31_12_{annee}"
    lignes = json.loads((RAW / "situation_budgetaire.json").read_text(encoding="utf-8"))
    return {r["ligne_d_information"].strip(): nombre(r[col]) for r in lignes if r.get(col) is not None}


def lignes_execution(annee: int) -> tuple[list[dict], dict]:
    """Lignes plates de l'exécution `annee` au périmètre du site (budget général hors remboursements et
    dégrèvements, avances à l'audiovisuel public, prélèvements sur recettes), méthode PLRG pour toutes les années."""
    d = PLRG[annee]["dossier"]
    lignes, ecarts = [], {"remboursements_eur": 0.0, "hors_perimetre_eur": defaultdict(float),
                          "budget_general_brut_eur": 0.0}
    for r in lire_csv(d / f"Annexe1-Etat_CP-{annee}.csv"):
        mission = r["Mission"].strip()
        poste = POSTES.get(mission)
        if poste is None:
            raise SystemExit(f"Mission sans grand poste (pipeline/grands_postes.json) : {mission}")
        v = nombre(r["Depenses_constatees"])
        ecarts["budget_general_brut_eur"] += v
        if poste == "exclu":
            ecarts["remboursements_eur"] += v
            continue
        if poste == "hors_perimetre":
            ecarts["hors_perimetre_eur"][mission] += v
            continue
        num, lib = programme(r["Programme"])
        lignes.append({"grand_poste": poste, "mission": mission, "programme": num, "libelle_programme": lib,
                       "eur": v, "source": "annexe 1"})
    for r in lire_csv(d / f"Annexe2-Etat_CP-{annee}.csv"):
        if r["Mission"].strip() != AUDIOVISUEL:
            continue
        num, lib = programme(r["Programme"])
        lignes.append({"grand_poste": POSTES[AUDIOVISUEL], "mission": AUDIOVISUEL, "programme": num,
                       "libelle_programme": lib, "eur": nombre(r["Depenses_constatees"]), "source": "annexe 2"})
    sit = situation(annee)
    for code, ligne in PSR.items():
        sp = POSTES["_lignes_speciales"][code]
        lignes.append({"grand_poste": "Prelevements sur recettes", "mission": sp["mission"], "programme": None,
                       "libelle_programme": None, "eur": sit[ligne], "source": "situation mensuelle"})
    ecarts["situation"] = sit
    return lignes, ecarts


# --- Comparaison ------------------------------------------------------------------------------------------------------

def par_poste(lignes: list[dict]) -> dict[str, float]:
    out = defaultdict(float)
    for l in lignes:
        out[l["grand_poste"]] += l["eur"]
    return out


def site_2024() -> tuple[dict[str, float], str]:
    r = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    return {gp["id"]: gp["md"] * 1e9 for gp in r["enfants"]}, r.get("millesime")


def e(x: float | None) -> int | None:
    return None if x is None else int(round(x))


def pct(a: float, b: float) -> float | None:
    return None if not a else round((b - a) / a * 100, 1)


def comparaison(l24: list[dict], l25: list[dict]) -> dict:
    p24, p25 = par_poste(l24), par_poste(l25)
    s24, mill_site = site_2024()
    postes = sorted(set(p24) | set(p25) | set(s24), key=lambda p: (-(p25.get(p) or 0), p))
    lignes = []
    for p in postes:
        a, b, s = p24.get(p), p25.get(p), s24.get(p)
        lignes.append([p, e(s), e(a), e(b), e(None if a is None or b is None else b - a),
                       None if a is None or b is None else pct(a, b),
                       e(None if a is None or s is None else a - s)])
    tot = [sum(x) for x in (s24.values(), p24.values(), p25.values())]
    return {
        "colonnes": ["grand_poste", "execution_2024_affichee_eur", "execution_2024_plrg_eur", "execution_2025_plrg_eur",
                     "variation_plrg_eur", "variation_plrg_pct", "ecart_methode_2024_eur"],
        "definitions": {
            "execution_2024_affichee_eur": f"montant affiché aujourd'hui par le site ({mill_site}) : jeu budget vert du "
                                           "PLF 2026, crédits retraités au format PLF 2026 par la direction du budget, "
                                           "arrondi au millier d'euros",
            "execution_2024_plrg_eur": "dépenses constatées 2024 lues dans le PLRG 2024 avec la méthode de ce module",
            "execution_2025_plrg_eur": "dépenses constatées 2025 lues dans le PLRG 2025 avec la même méthode",
            "variation_plrg_eur": "exécution 2025 moins exécution 2024, toutes deux selon le PLRG (même méthode)",
            "variation_plrg_pct": "variation rapportée à l'exécution 2024 selon le PLRG, en %, une décimale",
            "ecart_methode_2024_eur": "exécution 2024 selon le PLRG moins exécution 2024 affichée : effet du "
                                      "retraitement au format PLF 2026, publié tel quel",
        },
        "lignes": lignes,
        "totaux": {"execution_2024_affichee_eur": e(tot[0]), "execution_2024_plrg_eur": e(tot[1]),
                   "execution_2025_plrg_eur": e(tot[2]), "variation_plrg_eur": e(tot[2] - tot[1]),
                   "variation_plrg_pct": pct(tot[1], tot[2]), "ecart_methode_2024_eur": e(tot[1] - tot[0])},
        "lecture": ("Les deux exécutions sont comparées avec la même méthode (PLRG, dépenses constatées). La colonne "
                    "« affichée » reprend l'exécution 2024 de l'arbre du site, construite autrement (budget vert "
                    "retraité) : l'écart de méthode est publié, il ne s'additionne à rien et n'est pas une dépense."),
    }


def controles(annee: int, lignes: list[dict], ec: dict) -> dict:
    sit = ec["situation"]
    bg = sum(l["eur"] for l in lignes if l["source"] == "annexe 1")
    psr = sum(l["eur"] for l in lignes if l["source"] == "situation mensuelle")
    ref_bg = sit.get("Total dépenses nettes du budget général")
    ref_psr = sit.get("Total prélèvements sur recettes")
    return {
        "annee": annee,
        "budget_general_hors_remboursements_eur": e(bg),
        "depenses_nettes_budget_general_situation_eur": e(ref_bg),
        "ecart_budget_general_eur": e(None if ref_bg is None else bg - ref_bg),
        "remboursements_et_degrevements_retires_eur": e(ec["remboursements_eur"]),
        "prelevements_sur_recettes_eur": e(psr),
        "prelevements_sur_recettes_situation_eur": e(ref_psr),
        "hors_perimetre_eur": {k: e(v) for k, v in sorted(ec["hors_perimetre_eur"].items())},
        "lecture": ("Le budget général de l'arbre (PLRG, dépenses constatées hors remboursements et dégrèvements) et "
                    "les dépenses nettes de la situation mensuelle sont deux publications de la même exécution ; leur "
                    "écart est publié tel quel."),
    }


# --- Vérification des éditions attendues (constat du 18 novembre 2026) -------------------------------------------------
# Sources « en retard » de site/data/fraicheur/index.json (commit 0c0b2f3, date de référence 2026-11-18). Chaque constat
# a été établi à la date CONSTAT_LE sur les sites des producteurs : catalogue complet de data.economie.gouv.fr (620 jeux),
# recherche data.gouv.fr, dossier législatif du PLF 2027 de l'Assemblée nationale, en-têtes HTTP des fichiers cités.

PUBLIE_OUVERT, PUBLIE_PDF, NON_PUBLIE, NON_LOCALISE = ("publié en données ouvertes", "publié en PDF seulement",
                                                      "non publié en données ouvertes", "non localisé")
RATTRAPE, A_INTEGRER, AXE_OCCUPE, ATTENTE = ("rattrapé", "à intégrer", "axe en cours chez un autre agent",
                                             "en attente du producteur")
CONSTATS = {
    "budget_vert": {
        "edition": "projet de loi de finances pour 2027",
        "publication": NON_PUBLIE,
        "constat": ("Le rapport sur l'impact environnemental du budget (jaune « Budget vert ») du PLF 2027 est publié en "
                    "PDF sur le site de l'Assemblée nationale ; le jeu de données « PLF 2027 - Budget vert » ne figure "
                    "ni au catalogue de data.economie.gouv.fr ni sur data.gouv.fr. L'édition 2026 du jeu avait été mise "
                    "en ligne le 13 novembre 2025, cinq semaines après le dépôt du projet."),
        "url": f"{AN}/1129732/file/4-Jaune%202027%20-%20Budget%20vert.pdf",
        "suite": ATTENTE,
        "effet": ("Le jeu attendu porterait l'exécution 2025 et le budget voté 2026 par action : il compléterait "
                  "l'exécution 2025 préparée ici (programme) jusqu'au niveau de l'action."),
    },
    "plf_destination_nature": {
        "edition": "projet de loi de finances pour 2026 (puis 2027)",
        "publication": NON_PUBLIE,
        "constat": ("Aucun jeu « dépenses selon nomenclatures destination et nature » pour le PLF 2026 ni le PLF 2027 au "
                    "catalogue de data.economie.gouv.fr : la dernière édition ouverte est celle du PLF 2025. Les projets "
                    "annuels de performance 2027 sont publiés en PDF, mission par mission."),
        "url": DOSSIER_PLF27, "suite": ATTENTE, "effet": "La vue « par type de dépense » reste celle du PLF 2025.",
    },
    "budget_vert_justification": {
        "edition": "projet de loi de finances pour 2026",
        "publication": NON_PUBLIE,
        "constat": ("Pas de jeu « budget vert, justification des crédits et des taxes affectées » après celui du "
                    "PLF 2025 au catalogue de data.economie.gouv.fr."),
        "url": f"{ODS}/plf25-budget-vert-justification-des-credits-budgetaires-et-des-taxes-affectees/",
        "suite": ATTENTE, "effet": "aucun",
    },
    "jaune_associations": {
        "edition": "projet de loi de finances pour 2026 (puis 2027)",
        "publication": PUBLIE_PDF,
        "constat": ("Jeu de données de l'annexe « Effort financier de l'État en faveur des associations » absent après "
                    "le PLF 2025 ; l'annexe du PLF 2027 est publiée en PDF (1,3 Mo) sur le site de l'Assemblée "
                    "nationale."),
        "url": f"{AN}/1129753/file/14-Jaune%202027%20-%20Effort%20financier%20de%20l%27Etat%20en%20faveur%20des%20"
               "associations.pdf",
        "suite": A_INTEGRER, "axe": "beneficiaires",
        "effet": "Lecture d'un PDF de liste : à arbitrer (le jeu ouvert reste la forme attendue).",
    },
    "jaune_operateurs": {
        "edition": "projet de loi de finances pour 2027",
        "publication": PUBLIE_PDF,
        "constat": ("Annexe « Opérateurs de l'État » du PLF 2027 publiée en PDF (11,9 Mo, modifié le 15 octobre 2026) "
                    "sur le miroir de l'Assemblée nationale ; la liste des opérateurs en CSV (data.gouv.fr, publiée "
                    "par un particulier pour le PLF 2026) n'a pas d'édition 2027."),
        "url": f"{AN_PLF27}/22-Jaune-2027-Operateurs.pdf",
        "suite": A_INTEGRER, "axe": "operateurs",
        "effet": ("Intégration non faite dans ce passage : l'entrepôt ne contient plus les jaunes 2024 à 2026 ni le "
                  "cache des SIREN ; une nouvelle production de pipeline/operateurs.py sans ces caches perdrait les "
                  "SIREN déjà résolus. À lancer avec « collecter » puis « siren » (appels réseau) avant « produire »."),
    },
    "jaune_cabinets": {
        "edition": "projet de loi de finances pour 2027",
        "publication": PUBLIE_PDF,
        "constat": "Annexe « Personnels affectés dans les cabinets ministériels » du PLF 2027 publiée en PDF.",
        "url": f"{AN}/1129777/file/20-Jaune%202027%20-%20Personnels%20affect%C3%A9s%20dans%20les%20cabinets%20"
               "minist%C3%A9riels.pdf",
        "suite": AXE_OCCUPE, "axe": "fonction_publique",
        "effet": "Axe fonction publique en cours de modification par l'agent « fonction-publique-remunerations ».",
    },
    "jaune_conseils": {
        "edition": "projet de loi de finances pour 2027",
        "publication": PUBLIE_PDF,
        "constat": "Annexe « Recours aux conseils extérieurs » du PLF 2027 publiée en PDF (9,3 Mo, 15 octobre 2026).",
        "url": f"{AN_PLF27}/27-Jaune-2027-Recours-aux-cabinets-de-conseil.pdf",
        "suite": AXE_OCCUPE, "axe": "fonction_publique",
        "effet": "Axe fonction publique en cours de modification par l'agent « fonction-publique-remunerations ».",
    },
    "depenses_fiscales": {
        "edition": "projet de loi de finances pour 2027",
        "publication": NON_LOCALISE,
        "constat": ("Tome II de l'évaluation des voies et moyens du PLF 2027 non localisé sur le site de l'Assemblée "
                    "nationale ; budget.gouv.fr refuse les requêtes de scripts (HTTP 403, constat de l'axe dépenses "
                    "fiscales le 17 novembre 2026), non contourné."),
        "url": DOSSIER_PLF27, "suite": ATTENTE, "axe": "niches", "effet": "aucun",
    },
    "taxes_affectees": {
        "edition": "projet de loi de finances pour 2025 (puis 2026, 2027)",
        "publication": PUBLIE_PDF,
        "constat": ("Liste des taxes affectées en données ouvertes absente après le PLF 2024 ; le tome I des voies et "
                    "moyens est publié en PDF (PLF 2026 sur le site de l'Assemblée nationale)."),
        "url": f"{AN}/1087930/file/PLF%202026%20-%20V%26M%20TI%20-%20Evaluations%20des%20recettes.pdf",
        "suite": ATTENTE, "effet": "Source suivie par le catalogue sans page qui la lise.",
    },
    "participations_recettes": {
        "edition": "projet de loi de finances pour 2026",
        "publication": PUBLIE_PDF,
        "constat": ("Pas de jeu « recettes du budget général » après le PLF 2025 au catalogue de data.economie.gouv.fr ; "
                    "le jaune « État actionnaire » du PLF 2027 est publié en PDF. L'exécution 2025 (PLRG 2025) est déjà "
                    "lue par la page."),
        "url": f"{AN_PLF27}/10-Jaune-2027-Etat-actionnaire.pdf", "suite": ATTENTE, "axe": "etat_actionnaire",
        "effet": "Prévisions 2026 et 2027 absentes en données ouvertes.",
    },
    "participations_compte": {
        "edition": "projet de loi de finances pour 2026",
        "publication": NON_PUBLIE,
        "constat": "Pas de jeu « recettes des comptes d'affectation spéciale » après le PLF 2025.",
        "url": f"{ODS}/plf25-recettes-des-cas-et-des-ccf/", "suite": ATTENTE, "axe": "etat_actionnaire",
        "effet": "Prévisions 2026 et 2027 absentes en données ouvertes.",
    },
    "participations_depenses": {
        "edition": "projet de loi de finances pour 2026",
        "publication": NON_PUBLIE,
        "constat": "Pas de jeu « dépenses selon destination » après le PLF 2025.",
        "url": f"{ODS}/plf25-depenses-2025-selon-destination/", "suite": ATTENTE, "axe": "etat_actionnaire",
        "effet": "Prévisions 2026 et 2027 absentes en données ouvertes.",
    },
    "pensions_recettes": {
        "edition": "projet de loi de finances pour 2026",
        "publication": PUBLIE_PDF,
        "constat": ("Pas de jeu « recettes des comptes d'affectation spéciale » après le PLF 2025 ; le jaune « Pensions "
                    "de retraite de la fonction publique » du PLF 2027 est publié en PDF."),
        "url": f"{AN_PLF27}/12-Jaune-2027-Pensions-de-retraite-fonction-publique.pdf", "suite": ATTENTE,
        "axe": "retraites", "effet": "Prévisions 2026 et 2027 absentes en données ouvertes.",
    },
    "pensions_depenses": {
        "edition": "projet de loi de finances pour 2026",
        "publication": NON_PUBLIE,
        "constat": "Pas de jeu « dépenses selon destination » après le PLF 2025.",
        "url": f"{ODS}/plf25-depenses-2025-selon-destination/", "suite": ATTENTE, "axe": "retraites",
        "effet": "Prévisions 2026 et 2027 absentes en données ouvertes.",
    },
    "placss_annexe1": {
        "edition": "approbation des comptes de la sécurité sociale 2025",
        "publication": NON_LOCALISE,
        "constat": ("Annexes 3, 4, 5 et 7 du projet d'approbation des comptes 2025 localisées sur le site de "
                    "l'Assemblée nationale ; l'annexe 1 (rapport d'évaluation des politiques de sécurité sociale, "
                    "maladie) n'y a pas été localisée."),
        "url": "https://www.assemblee-nationale.fr/dyn/opendata/PRJLANR5L17B2843.html", "suite": ATTENTE,
        "effet": "Source suivie par le catalogue sans page qui la lise.",
    },
    "placss_annexe3": {
        "edition": "approbation des comptes de la sécurité sociale 2025", "publication": PUBLIE_PDF,
        "constat": "Annexe 3 (ONDAM et dépenses de santé) publiée en PDF ; collectée le 18 novembre 2026.",
        "url": f"{AN}/1112982/file/PLACSS2025-Annexe%203.pdf", "suite": RATTRAPE,
        "nouvelle_source": "secu_placss2025_annexe3", "effet": "Source suivie par le catalogue sans page qui la lise.",
    },
    "placss_annexe4": {
        "edition": "approbation des comptes de la sécurité sociale 2025", "publication": PUBLIE_PDF,
        "constat": "Annexe 4 (assurance chômage, retraites complémentaires) publiée en PDF ; collectée le 18 novembre 2026.",
        "url": f"{AN}/1112985/file/PLACSS2025_Annexe%204.pdf", "suite": RATTRAPE,
        "nouvelle_source": "secu_placss2025_annexe4", "effet": "Source suivie par le catalogue sans page qui la lise.",
    },
    "placss_annexe7": {
        "edition": "approbation des comptes de la sécurité sociale 2025", "publication": PUBLIE_PDF,
        "constat": ("Annexe 7 (comptes définitifs du FSV, de la CADES et du FRR) publiée en PDF ; collectée le "
                    "18 novembre 2026."),
        "url": f"{AN}/1112991/file/PLACSS2025_Annexe%207.pdf", "suite": RATTRAPE,
        "nouvelle_source": "secu_placss2025_annexe7", "effet": "Source suivie par le catalogue sans page qui la lise.",
    },
}
# (identifiant dans fraicheur/index.json, famille, axes qui la lisent au 18/11/2026)
EN_RETARD = [
    ("budget_etat_vert", "budget_vert", ["base"]),
    ("budget_etat_plf", "plf_destination_nature", ["base"]),
    ("benef_associations_plf25", "jaune_associations", ["beneficiaires"]),
    ("etat_jaune_operateurs_plf2026", "jaune_operateurs", ["operateurs"]),
    ("datagouv__projet-de-loi-de-finances-pour-2026-plf-2026-jaune-operateurs-de-letat-liste-des-operateurs-et-"
     "categories", "jaune_operateurs", ["operateurs"]),
    ("etat_budget_vert_2026", "budget_vert", ["vie_politique", "decisions"]),
    ("economie__plf25-budget-vert-justification-des-credits-budgetaires-et-des-taxes-affectees",
     "budget_vert_justification", ["decisions"]),
    ("niches_vm", "depenses_fiscales", ["niches"]),
    ("etat_actionnaire_plf25_depenses_destination", "participations_depenses", ["etat_actionnaire"]),
    ("etat_actionnaire_plf25_recettes_cas", "participations_compte", ["etat_actionnaire"]),
    ("etat_actionnaire_plf25_recettes_bg", "participations_recettes", ["etat_actionnaire"]),
    ("fp_jaune_cabinets_plf2026", "jaune_cabinets", ["fonction_publique"]),
    ("fp_jaune_conseils_plf2026", "jaune_conseils", ["fonction_publique"]),
    ("retraites_plf25_depenses_destination", "pensions_depenses", ["retraites"]),
    ("retraites_plf25_recettes_cas", "pensions_recettes", ["retraites"]),
    ("etat_plf25_destination_nature", "plf_destination_nature", []),
    ("etat_operateurs_2026", "jaune_operateurs", []),
    ("secu_placss2024_annexe1_maladie", "placss_annexe1", []),
    ("secu_placss2024_annexe3", "placss_annexe3", []),
    ("secu_placss2024_annexe4", "placss_annexe4", []),
    ("secu_placss2024_annexe7", "placss_annexe7", []),
    ("fiscalite_taxes_affectees_plf2024", "taxes_affectees", []),
]


def verification() -> list[dict]:
    out = []
    for sid, fam, axes in EN_RETARD:
        c = CONSTATS[fam]
        out.append({"id": sid, "famille": fam, "axes": axes, "edition_attendue": c["edition"],
                    "publication": c["publication"], "constat": c["constat"], "url": c["url"],
                    "constat_le": CONSTAT_LE, "suite": c["suite"], "nouvelle_source": c.get("nouvelle_source"),
                    "effet": c["effet"]})
    return out


# --- Dossier de bascule vers l'exécution 2025 -------------------------------------------------------------------------

MOTIFS_WEB = [
    (re.compile(r"(?<![\w/])arbre/racine\.json"), "lit l'arbre de la vue par défaut (arbre/racine.json)"),
    (re.compile(r"VUES_ARBRE\[0\]|vueArbre\("), "prend la première vue de VUES_ARBRE (vue par défaut)"),
    (re.compile(r"listeProgrammes\("), "liste des programmes tirée de l'arbre d'exécution 2024"),
    (re.compile(r"execution2024"), "désigne la vue « execution2024 » par sa clé"),
    (re.compile(r"'Exécution 2024'"), "écrit le millésime « Exécution 2024 » en dur"),
]
MOTIF_PIPELINE = re.compile(r'(?<![\w/])arbre/racine\.json|SITE\s*/\s*"arbre"|"arbre"\s*/\s*"racine\.json"')
PRODUCTEURS = {"arbre.py", "transform.py", "millesimes.py", "fraicheur.py", "tout.py"}


def ecrans_concernes() -> list[dict]:
    out = []
    for p in sorted(WEB.rglob("*.ts")):
        t = p.read_text(encoding="utf-8")
        motifs = [lib for rx, lib in MOTIFS_WEB if rx.search(t)]
        if motifs:
            out.append({"fichier": str(p.relative_to(ROOT)), "motifs": motifs})
    return out


def pipelines_concernes() -> list[str]:
    return [f"pipeline/{p.name}" for p in sorted((ROOT / "pipeline").glob("*.py"))
            if p.name not in PRODUCTEURS and MOTIF_PIPELINE.search(p.read_text(encoding="utf-8"))]


def bascule(l24: list[dict], l25: list[dict]) -> dict:
    m24 = {l["mission"] for l in l24}
    s24 = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    missions_site = {m["nom"] for gp in s24["enfants"] for m in gp.get("enfants", [])}
    m25 = {l["mission"] for l in l25}
    return {
        "decision": ("Passer la vue par défaut de l'exécution 2024 à l'exécution 2025 est soumis au propriétaire du "
                     "site : ce module ne modifie ni l'arbre affiché, ni site/data/meta.json, ni web/."),
        "donnees_pretes": ["millesimes/execution2025/racine.json"],
        "ecrans": ecrans_concernes(),
        "pipelines": pipelines_concernes(),
        "missions_libelles_differents": sorted(m25 - missions_site),
        "missions_absentes_2025": sorted(m24 - m25),
        "missions_nouvelles_2025": sorted(m25 - m24),
        "impacts": [
            {"sujet": "niveau de détail",
             "constat": ("L'exécution 2025 préparée s'arrête au programme (PLRG 2025, annexes 1 et 2) ; l'exécution "
                         "2024 affichée descend à l'action (budget vert du PLF 2026). Le niveau de l'action pour 2025 "
                         "viendra du jeu budget vert du PLF 2027, non publié en données ouvertes au 18 novembre 2026.")},
            {"sujet": "méthode",
             "constat": ("L'arbre affiché suit le retraitement au format PLF 2026 de la direction du budget ; l'arbre "
                         "préparé suit les dépenses constatées du PLRG. L'écart de méthode est publié par grand poste "
                         "pour 2024 (comparaison.ecart_methode_2024_eur).")},
            {"sujet": "identifiants",
             "constat": ("Les libellés de mission du PLRG diffèrent parfois de ceux du budget vert "
                         "(missions_libelles_differents) : les identifiants de nœuds (chemins) changent, donc les liens "
                         "profonds vers le détail d'un nœud et l'index de recherche (web/scripts/index-recherche.mjs) "
                         "sont à régénérer.")},
            {"sujet": "millésimes mêlés",
             "constat": ("Les pages qui rapportent un montant d'un autre axe au total de l'arbre par défaut (pipelines "
                         "et écrans listés) mêleraient des montants 2024 à un total 2025 tant que leur propre source "
                         "n'est pas passée à 2025 : chaque axe doit passer en même temps, ou garder une référence 2024 "
                         "écrite en clair.")},
            {"sujet": "vue par défaut et textes",
             "constat": ("Changer l'ordre de VUES_ARBRE (web/src/donnees.ts), le dossier par défaut (site/data/arbre/), "
                         "meta.millesime.etat_defaut (pipeline/transform.py) et les textes qui écrivent "
                         "« Exécution 2024 » en dur.")},
        ],
        "etapes_proposees": [
            "valider la décision de bascule",
            "attendre le jeu « PLF 2027 - Budget vert » pour garder le niveau de l'action, ou accepter un arbre 2025 "
            "arrêté au programme",
            "ajouter l'exécution 2025 à MILLESIMES de pipeline/transform.py (vue non par défaut), puis en faire la vue "
            "par défaut",
            "passer les axes listés à leur source 2025 (PLRG 2025 déjà dans l'entrepôt : annexe titre et catégorie, "
            "annexe 2)",
            "régénérer l'index de recherche et vérifier les liens profonds",
        ],
    }


# --- Production -------------------------------------------------------------------------------------------------------

RECHERCHE_PREALABLE = {
    "verdict": "réutilisable tel quel pour les données ; aucun outil public ne prépare une bascule de millésime",
    "trouvailles": [
        {"nom": "pipeline/transform.py et pipeline/arbre.py (ce dépôt)", "verdict": "réutilisable tel quel",
         "licence": "celle du dépôt", "date": "2026-11-17", "usage": "format et écriture de l'arbre, conventions"},
        {"nom": "data.economie.gouv.fr, PLRG 2024 et 2025 (annexes CSV)", "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "date": "2026-04-22 (PLRG 2025)", "usage": "exécution par programme"},
        {"nom": "data.economie.gouv.fr, situations mensuelles budgétaires (séries longues)",
         "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "date": "2026-11-04",
         "usage": "prélèvements sur recettes et contrôles au 31 décembre"},
        {"nom": "data.economie.gouv.fr, plf-2026-budget-vert", "verdict": "à adapter", "licence": "Licence Ouverte 2.0",
         "date": "2025-11-13", "usage": "pas de colonne exécution 2025 (l'édition PLF 2027 la portera)"},
    ],
}
LIMITES = [
    "L'exécution 2025 préparée n'a pas le niveau de l'action : le PLRG publie les dépenses constatées par programme et "
    "par titre.",
    "La comparaison 2024 / 2025 est faite avec la même méthode (PLRG) ; l'exécution 2024 affichée par le site suit une "
    "autre méthode et n'est montrée qu'avec son écart.",
    "Les constats de publication sont datés du 18 novembre 2026 : une édition mise en ligne après cette date n'y figure "
    "pas.",
    "Les montants sont des crédits de paiement consommés (euros courants), sans correction de l'inflation.",
]


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def produire(sortie: Path = SORTIE) -> dict:
    l24, ec24 = lignes_execution(2024)
    l25, ec25 = lignes_execution(2025)
    entete25 = {"millesime": "Exécution 2025",
                "source": f"{src_plrg(2025, 'annexes 1 et 2')} ; prélèvements sur recettes : {SRC_SITUATION}",
                "unite": UNITE_ARBRE}
    stats = arbre.ecrire(arbre.construire(l25, NIVEAUX["niveaux"], "eur"), NIVEAUX["racine"],
                         NIVEAUX["decoupe_apres"], sortie / "execution2025", entete25)
    comp = comparaison(l24, l25)
    verif = verification()
    par_suite = defaultdict(int)
    for v in verif:
        par_suite[v["suite"]] += 1
    index = {
        "millesime": "Exécution 2025 préparée (non affichée) ; exécution 2024 ; constats de publication au "
                     "18 novembre 2026",
        "source": (f"{src_plrg(2024, 'annexes 1 et 2')} ; {src_plrg(2025, 'annexes 1 et 2')} ; {SRC_SITUATION} ; "
                   f"{SRC_ARBRE_SITE} ; {DOSSIER_PLF27}"),
        "unite": "euros (crédits de paiement consommés)",
        "presentation": ("Cette page de travail prépare l'exécution 2025 du budget de l'État dans le format des arbres "
                         "du site et dit, pour chaque source attendue, ce que les producteurs ont publié. Elle ne change "
                         "pas la vue affichée par défaut, qui reste l'exécution 2024."),
        "collecte_le": date_sources("etat"),
        "vue_par_defaut": {"actuelle": "Exécution 2024", "preparee": "Exécution 2025",
                           "statut": "soumis au propriétaire du site"},
        "execution_2025": {
            "fichier": "millesimes/execution2025/racine.json",
            "niveaux": ["grand_poste", "mission", "programme"],
            "total_eur": e(sum(l["eur"] for l in l25)),
            "arbre": stats,
            "perimetre": ("Budget général hors remboursements et dégrèvements (PLRG, annexe 1), avances à l'audiovisuel "
                          "public (annexe 2), prélèvements sur recettes au profit des collectivités et de l'Union "
                          "européenne (situation mensuelle au 31 décembre) : mêmes conventions que l'arbre du site "
                          "(pipeline/grands_postes.json)."),
            "methode": ("Somme des dépenses constatées en crédits de paiement par programme, tous titres confondus ; "
                        "chaque mission rattachée à son grand poste ; les pensions des fonctionnaires restent dans "
                        "chaque ministère (contributions employeur, titre 2)."),
            "publie_le": PLRG[2025]["publie"],
        },
        "controles": [controles(2024, l24, ec24), controles(2025, l25, ec25)],
        "comparaison": comp,
        "bascule": bascule(l24, l25),
        "verification": {"date_reference": CONSTAT_LE,
                         "origine": "site/data/fraicheur/index.json, sources au statut « en retard » (commit 0c0b2f3)",
                         "nombre": len(verif), "par_suite": dict(sorted(par_suite.items())), "sources": verif},
        "sources": [
            {"id": PLRG[a]["id"], "titre": f"PLRG {a}, annexes 1 et 2 (CSV)", "url": f"{ODS}/{PLRG[a]['dataset']}/",
             "licence": "Licence Ouverte 2.0", "publie_le": PLRG[a]["publie"],
             "entrepot": f"data/lake/etat/{PLRG[a]['id']}/"} for a in sorted(PLRG)] + [
            {"id": "situation_budgetaire", "titre": "Situation mensuelle budgétaire de l'État, séries longues",
             "url": f"{ODS}/situations-mensuelles-budgetaires-series-longues/", "licence": "Licence Ouverte 2.0",
             "publie_le": None, "entrepot": "data/raw/situation_budgetaire.json"}],
        "recherche_prealable": RECHERCHE_PREALABLE,
        "limites": LIMITES,
        "ordre": {"comparaison": "grands postes par exécution 2025 décroissante",
                  "verification": "ordre de la page de fraîcheur (page, puis titre)",
                  "ecrans": "chemin de fichier"},
    }
    dump(sortie / "index.json", index)
    print(f"millésimes : exécution 2025 {index['execution_2025']['total_eur'] / 1e9:.1f} Md€ ; "
          f"{len(verif)} sources vérifiées", file=sys.stderr)
    return index


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("commande", choices=["produire"])
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    produire(a.sortie)


if __name__ == "__main__":
    main()
