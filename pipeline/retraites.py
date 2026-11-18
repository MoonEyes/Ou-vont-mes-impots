"""Retraites par régime : retraités, cotisants quand ils sont publiés, pension moyenne, ressources par origine.

Agrégats publiés seulement (aucune donnée individuelle). Les montants de pensions par régime sont déjà publiés par
`prestations/` (comptes de la protection sociale de la DREES) et les dépenses des organismes par `secu/` : ce module
ne les recopie pas, il y renvoie par des liens (fichier + identifiant), jamais par des montants additionnés.

Entrées : entrepôt brut data/lake/secu/ (non versionné), collectées par `collecter` et par collecte/collecte.py :
    retraites_eacr_part1.xlsx                 DREES, enquête annuelle auprès des caisses de retraite (EACR), table
                                              A-Cadrage : effectifs et pensions moyennes par caisse, 2004-2024
    retraites_drees_cotisants_2004_2016.xlsx  DREES, retraités de droit direct et emploi intérieur, tous régimes
    retraites_sre_civils.json, retraites_sre_militaires.json, retraites_sre_gendarmes.json
                                              Service des retraites de l'État (DGFiP), cubes « stock droit direct 1 »
    retraites_plf25_recettes_cas.json         PLF 2025, recettes des comptes d'affectation spéciale (CAS Pensions)
    retraites_plf25_depenses_destination.json PLF 2025, dépenses selon destination (programmes 741, 742, 743 du CAS
                                              Pensions ; 195, 197, 198 de la mission Régimes sociaux et de retraite)
    retraites_cdc_cnracl_actifs.json, retraites_cdc_cnracl_retraites.json, retraites_cdc_ircantec_cotisants.json
                                              Caisse des dépôts : actifs et retraités de la CNRACL, cotisants de l'Ircantec
    retraites_msa_stock/ret_stock_<an>.csv    MSA, retraités du régime agricole par intercommunalité, 2016-2023
Sorties :
  site/data/retraites/index.json    régimes, liens, écarts entre sources, sources, limites
  site/data/retraites/regimes.json  séries annuelles par régime : retraités, nouveaux retraités, pensions moyennes,
                                    cotisants quand ils sont publiés
  site/data/retraites/etat.json     CAS Pensions (dépenses par programme, recettes par origine), retraités de l'État
                                    (SRE), crédits de l'État aux régimes spéciaux (mission Régimes sociaux et de retraite)

Commandes :
  python pipeline/retraites.py collecter   # réseau : sources manquantes ; un refus 401/403/429 est noté, jamais contourné
  python pipeline/retraites.py produire    # sans réseau
  python pipeline/retraites.py             # les deux

Règles :
  - les effectifs par régime ne sont jamais additionnés : une personne qui perçoit des pensions de plusieurs régimes
    est comptée dans chacun ; seule la série « tous régimes » de la DREES compte chaque personne une fois ;
  - aucune masse de pensions n'est recalculée (effectif × pension moyenne) : la DREES indique que ce produit diffère
    des dépenses ; les montants sont ceux de `prestations/` et de `secu/`, reliés par des liens ;
  - les écarts entre sources sont publiés tels quels (valeur, différence, part), jamais lissés ni tranchés ;
  - une valeur absente à la source est null, jamais 0 ;
  - toute date écrite vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BRUT = ROOT / "data" / "lake" / "secu"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "retraites"

# --- Sources ---------------------------------------------------------------------------------------------------------

DREES = "https://data.drees.solidarites-sante.gouv.fr"
ECO = "https://data.economie.gouv.fr"
CDC = "https://opendata.caissedesdepots.fr"
LO = "Licence Ouverte 2.0"
MSA_RESSOURCES = {2016: "7ee63af4-9efa-4bbf-af0b-46c7f14b4f83", 2017: "46ebb1fe-81be-462f-8b72-eaa4d68ed869",
                  2018: "8497327d-84e3-40da-ad1f-fd450ec23df0", 2019: "11bff7f3-526c-4620-a677-dc7259770bf4",
                  2020: "0f8c041e-76c3-49a2-b49b-fb3127717d04", 2021: "9cc74b33-c871-44e9-b1f6-c1623e4fee1d",
                  2022: "94d5ca80-7973-4caf-833b-2c82b68727b0", 2023: "4a631cbe-e1ff-4dd9-8889-d68524b3813f"}


def _ods(portail: str, jeu: str) -> dict:
    return {"url": f"{portail}/api/explore/v2.1/catalog/datasets/{jeu}/exports/json",
            "page": f"{portail}/explore/dataset/{jeu}/"}


SOURCES = {
    "drees_eacr": {
        "fichier": "retraites_eacr_part1.xlsx",
        "url": f"{DREES}/api/explore/v2.1/catalog/datasets/donnes_eacr/attachments/"
               "62_eacr_diffusee_part_1_version_du_26_mai_2026_xlsx",
        "page": f"{DREES}/explore/dataset/donnes_eacr/",
        "titre": "DREES, « Données de l'enquête annuelle auprès des caisses de retraite » (EACR), classeur partie 1 "
                 "(version du 26 mai 2026), table A-Cadrage : effectifs de retraités au 31 décembre et pensions "
                 "moyennes de décembre, par caisse ; lignes « tous régimes » estimées par la DREES (modèle Ancêtre, "
                 "échantillon interrégimes de retraités)",
        "producteur": "DREES", "millesime": "2004 à 2024", "licence": LO,
        "verdict": "réutilisable tel quel (classeur ; documentation : pièce jointe DocumentationEACR_mai2026.pdf)",
    },
    "drees_cotisants": {
        "fichier": "retraites_drees_cotisants_2004_2016.xlsx",
        "url": f"{DREES}/api/explore/v2.1/catalog/datasets/1393_les-effectifs-et-montants-de-pension-des-retraites/"
               "attachments/rapport_des_effectifs_de_retraites_et_de_cotisants_de_2004_a_2016xlsx",
        "page": f"{DREES}/explore/dataset/1393_les-effectifs-et-montants-de-pension-des-retraites/",
        "titre": "DREES, « Les effectifs de retraités, montants de pensions et âges de départ à la retraite », "
                 "classeur « Rapport des effectifs de retraités et de cotisants de 2004 à 2016 » : retraités de droit "
                 "direct, emploi intérieur et rapport cotisants / retraités, tous régimes",
        "producteur": "DREES", "millesime": "2004 à 2016", "licence": "non précisée sur la fiche du jeu",
        "verdict": "réutilisable tel quel (classeur ; série arrêtée en 2016)",
    },
    "sre_civils": {
        "fichier": "retraites_sre_civils.json", **_ods(ECO, "retraite-cube-stock-civil-droit-direct-1"),
        "titre": "Service des retraites de l'État (DGFiP), « Retraite - Cube stock civil droit direct 1 » : pensions "
                 "civiles de droit direct en paiement au 31 décembre, effectif et somme des montants mensuels",
        "producteur": "DGFiP, Service des retraites de l'État", "millesime": "2015 à 2025", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft)",
    },
    "sre_militaires": {
        "fichier": "retraites_sre_militaires.json", **_ods(ECO, "cube-stock-militaire-armee-droit-direct-1"),
        "titre": "Service des retraites de l'État (DGFiP), « Retraite - Cube stock militaire armée droit direct 1 » : "
                 "pensions militaires de droit direct (hors gendarmes) en paiement au 31 décembre",
        "producteur": "DGFiP, Service des retraites de l'État", "millesime": "2015 à 2025", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft)",
    },
    "sre_gendarmes": {
        "fichier": "retraites_sre_gendarmes.json", **_ods(ECO, "cube-stock-gendarme-droit-direct-1"),
        "titre": "Service des retraites de l'État (DGFiP), « Retraite - Cube stock militaire gendarme droit direct 1 » "
                 ": pensions de droit direct des gendarmes en paiement au 31 décembre",
        "producteur": "DGFiP, Service des retraites de l'État", "millesime": "2015 à 2025", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft)",
    },
    "plf25_recettes_cas": {
        "fichier": "retraites_plf25_recettes_cas.json", **_ods(ECO, "plf25-recettes-des-cas-et-des-ccf"),
        "titre": "Direction du budget, « PLF 2025 - Recettes des CAS et des CCF » : lignes de recettes du compte "
                 "d'affectation spéciale Pensions (sections YD-1, YD-2, YD-3), prévisions 2025",
        "producteur": "Direction du budget", "millesime": "PLF 2025", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft)",
    },
    "plf25_depenses": {
        "fichier": "retraites_plf25_depenses_destination.json", **_ods(ECO, "plf25-depenses-2025-selon-destination"),
        "titre": "Direction du budget, « PLF 2025 - Dépenses 2025 selon destination » : crédits de paiement des "
                 "programmes 741, 742 et 743 (CAS Pensions) et 195, 197 et 198 (mission Régimes sociaux et de retraite)",
        "producteur": "Direction du budget", "millesime": "PLF 2025", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft)",
    },
    "cdc_cnracl_actifs": {
        "fichier": "retraites_cdc_cnracl_actifs.json", **_ods(CDC, "actifs-cotisant-a-la-cnracl-selon-les-employeurs"),
        "titre": "Caisse des dépôts, « Actifs à la CNRACL selon les employeurs » : agents cotisants par type de "
                 "collectivité, femmes et hommes",
        "producteur": "Caisse des dépôts (gestionnaire de la CNRACL)", "millesime": "2014 à 2022", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft ; jeu non mis à jour depuis novembre 2023)",
    },
    "cdc_cnracl_retraites": {
        "fichier": "retraites_cdc_cnracl_retraites.json",
        **_ods(CDC, "retraitescnracl_droitrisk_sexe_effectifs_agemoy_pensionmoy"),
        "titre": "Caisse des dépôts, « Effectifs de retraités de la CNRACL par type de droit et risque » : pensions "
                 "en paiement (vieillesse et invalidité, droit direct et droit dérivé), pension moyenne annuelle",
        "producteur": "Caisse des dépôts (gestionnaire de la CNRACL)", "millesime": "2014 à 2022", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft ; jeu non mis à jour depuis novembre 2023)",
    },
    "cdc_ircantec_cotisants": {
        "fichier": "retraites_cdc_ircantec_cotisants.json", **_ods(CDC, "cotisantsircantec_typecoll_nbagents"),
        "titre": "Caisse des dépôts, « Effectifs de cotisants à l'IRCANTEC, par employeurs » : cotisants par famille "
                 "d'employeurs",
        "producteur": "Caisse des dépôts (gestionnaire de l'Ircantec)", "millesime": "2014 à 2021", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft ; jeu non mis à jour depuis novembre 2023)",
    },
    "msa_retraites": {
        "fichier": "retraites_msa_stock",
        "url": "https://www.data.gouv.fr/fr/datasets/r/<identifiant de la ressource>",
        "page": "https://www.data.gouv.fr/fr/datasets/retraites-au-regime-agricole/",
        "titre": "MSA, « Retraités au régime agricole » : retraités ayant au moins une prestation vieillesse en "
                 "paiement au 31 décembre, salariés agricoles et non-salariés agricoles, par intercommunalité "
                 "(un fichier par année, sommé ici sur la France)",
        "producteur": "Mutualité sociale agricole", "millesime": "2016 à 2023", "licence": LO,
        "verdict": "à adapter (les deux colonnes d'effectifs changent de contenu d'une année à l'autre : voir "
                   "ecarts_msa dans index.json)",
        "ressources": {str(a): f"https://www.data.gouv.fr/fr/datasets/r/{r}" for a, r in sorted(MSA_RESSOURCES.items())},
    },
}
COLLECTABLES = [k for k in SOURCES if k != "msa_retraites"]

INACCESSIBLES = [
    {"source": "Conseil d'orientation des retraites (COR), séries du rapport annuel (cotisants, ressources et dépenses "
               "par régime, projections)",
     "motif": "fichiers non repris : leur réutilisation est soumise à l'accord du COR ; aucune valeur du COR n'est "
              "publiée ici"},
    {"source": "Cotisants par régime (CNAV, MSA, Agirc-Arrco, fonction publique de l'État, SNCF, RATP, industries "
               "électriques et gazières, mines, marins)",
     "motif": "aucun jeu ouvert annuel trouvé (portails de la DREES, de la DGFiP, de la Caisse des dépôts, data.gouv.fr)"
              " ; publiés seulement : actifs de la CNRACL (2014-2022), cotisants de l'Ircantec (2014-2021), emploi "
              "intérieur tous régimes (DREES, 2004-2016)"},
    {"source": "Ressources par origine (cotisations, État, transferts) des régimes hors compte d'affectation spéciale "
               "Pensions",
     "motif": "publiées dans les rapports de la Commission des comptes de la sécurité sociale et les annexes au "
              "projet de loi d'approbation des comptes (documents PDF, tableaux non diffusés en jeu ouvert) ; non "
              "reprises ; seules les recettes du CAS Pensions (PLF 2025) et les crédits de l'État aux régimes spéciaux "
              "sont publiés en données ouvertes"},
    {"source": "DREES, EACR, classeur partie 2 (minima de pension, cumul emploi-retraite, conditions de liquidation, "
               "invalidité, rentes d'accident du travail)",
     "motif": "hors objet de cette vue (effectifs, pensions moyennes, financement) : non collecté"},
    {"source": "Exécution du compte d'affectation spéciale Pensions (recettes et dépenses constatées)",
     "motif": "le jeu ouvert utilisé donne les prévisions du PLF 2025 ; l'exécution par ligne de recette n'est pas "
              "diffusée en jeu ouvert"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "conclusion": "Les producteurs publient déjà les agrégats (DREES, Service des retraites de l'État, direction du "
                  "budget, Caisse des dépôts, MSA) : ils sont repris tels quels. Aucun dépôt public ne publie ces "
                  "séries par régime avec leurs écarts et leurs liens vers les financeurs : module écrit pour le "
                  "dépôt, sur le modèle de pipeline/prestations.py.",
    "trouvailles": [
        {"nom": "DREES, Données de l'enquête annuelle auprès des caisses de retraite (EACR)",
         "url": SOURCES["drees_eacr"]["page"], "licence": LO, "mise_a_jour": "2026-05-22",
         "verdict": "réutilisable tel quel"},
        {"nom": "DREES, Les effectifs de retraités, montants de pensions et âges de départ à la retraite",
         "url": SOURCES["drees_cotisants"]["page"], "licence": "non précisée", "mise_a_jour": "2024-10-30",
         "verdict": "à adapter (classeurs par édition ; séries par régime reprises de l'EACR, plus récente)"},
        {"nom": "DGFiP, cubes « Retraite » du Service des retraites de l'État (16 jeux)",
         "url": f"{ECO}/explore/?q=retraite+cube", "licence": LO, "mise_a_jour": "2026-08-11",
         "verdict": "réutilisable tel quel (cubes « stock droit direct 1 » repris)"},
        {"nom": "Direction du budget, PLF 2025 : recettes des CAS et des CCF, dépenses selon destination",
         "url": SOURCES["plf25_recettes_cas"]["page"], "licence": LO, "mise_a_jour": "2024-10-11",
         "verdict": "réutilisable tel quel"},
        {"nom": "Caisse des dépôts, jeux CNRACL et Ircantec", "url": f"{CDC}/explore/?q=cnracl", "licence": LO,
         "mise_a_jour": "2023-11-09", "verdict": "réutilisable tel quel (séries arrêtées en 2021 ou 2022)"},
        {"nom": "MSA, Retraités au régime agricole (data.gouv.fr)", "url": SOURCES["msa_retraites"]["page"],
         "licence": LO, "mise_a_jour": "2026-01-06", "verdict": "à adapter (colonnes à contrôler année par année)"},
        {"nom": "g-pliberal/retraitecomptenotionelle (scripts/fetch/drees_eacr.py)",
         "url": "https://github.com/g-pliberal/retraitecomptenotionelle", "licence": "Apache-2.0",
         "dernier_commit": "2026-11-17", "verdict": "inspiration seulement (simulation d'une réforme, hors objet)"},
        {"nom": "ManZanau/retraites-simulateur", "url": "https://github.com/ManZanau/retraites-simulateur",
         "licence": "licence propre au dépôt", "dernier_commit": "2026-10-20",
         "verdict": "inspiration seulement (simulateur, pas d'agrégats par régime)"},
        {"nom": "ArthurVerrez/chaque-euro", "url": "https://github.com/ArthurVerrez/chaque-euro",
         "licence": "AGPL-3.0", "dernier_commit": "2026-11-17",
         "verdict": "inspiration seulement (site voisin ; licence différente, données non reprises)"},
        {"nom": "AxelCorral/retraites-cor2026", "url": "https://github.com/AxelCorral/retraites-cor2026",
         "licence": "licence propre au dépôt", "dernier_commit": "2026-06-16",
         "verdict": "inspiration seulement (repose sur les séries du COR, non réutilisables sans accord)"},
        {"nom": "Recherches GitHub « eacr drees », « donnes_eacr », « retraites régimes cotisants », « sre pensions "
                "cube »", "url": "https://github.com/search", "licence": None, "dernier_commit": None,
         "verdict": "aucun autre dépôt pertinent"},
    ],
}

# --- Régimes de l'EACR ------------------------------------------------------------------------------------------------
# (code de caisse CC, libellé de la caisse dans la table A) -> identifiant, nom affiché, type selon la nomenclature de la
# documentation de l'EACR (annexe 2). Une caisse absente de cette table est publiée sous un identifiant dérivé de son
# libellé, avec un type null : rien n'est écarté en silence.

REGIMES = {
    ("0000", "Tous régimes"): ("tous_regimes", "Tous régimes (chaque personne comptée une fois, estimation DREES)",
                              "ensemble"),
    ("0010", "CNAV"): ("cnav", "Régime général (CNAV), avant l'intégration des indépendants", "base"),
    ("0015", "CNAV"): ("cnav_avec_independants", "Régime général (CNAV), y compris sécurité sociale des indépendants",
                       "base"),
    ("0012", "Fonction publique d'état civile"): ("etat_civils", "Fonction publique de l'État, civils (SRE)", "integre"),
    ("0013", "Fonction publique d'état militaire"): ("etat_militaires", "Fonction publique de l'État, militaires (SRE)",
                                                     "integre"),
    ("0019", "CSS Mayotte"): ("css_mayotte", "Caisse de sécurité sociale de Mayotte", "base"),
    ("0021", "MSA salariés"): ("msa_salaries", "MSA, salariés agricoles", "base"),
    ("0022", "MSA exploitants"): ("msa_non_salaries", "MSA, non-salariés agricoles (base)", "base"),
    ("0023", "MSA exploitants complémentaire"): ("msa_non_salaries_complementaire",
                                                 "MSA, non-salariés agricoles (complémentaire)", "complementaire"),
    ("0032", "CNRACL"): ("cnracl", "CNRACL (agents des collectivités locales et des hôpitaux)", "integre"),
    ("0033", "FSPOEIE"): ("fspoeie", "FSPOEIE (ouvriers des établissements industriels de l'État)", None),
    ("0043", "RCI complémentaire"): ("rci_complementaire", "Régime complémentaire des indépendants (RCI)",
                                     "complementaire"),
    ("0043", "SSI complémentaire"): ("ssi_complementaire", "Sécurité sociale des indépendants, complémentaire",
                                     "complementaire"),
    ("0060", "SNCF"): ("sncf", "SNCF (caisse de prévoyance et de retraite du personnel ferroviaire)", "integre"),
    ("0061", "SNCF coordination"): ("sncf_coordination", "SNCF, pensions de coordination", "integre"),
    ("0070", "ENIM"): ("enim", "Marins (ENIM)", "integre"),
    ("0080", "CANSSM"): ("canssm", "Mines (CANSSM)", "integre"),
    ("0090", "CAVIMAC"): ("cavimac", "Cultes (Cavimac)", "base"),
    ("0100", "CNIEG"): ("cnieg", "Industries électriques et gazières (CNIEG)", "base"),
    ("0300", "RATP"): ("ratp", "RATP (caisse de retraite et de prévoyance)", "integre"),
    ("0301", "RATP coordination"): ("ratp_coordination", "RATP, pensions de coordination", "integre"),
    ("0500", "CRPCEN"): ("crpcen", "Clercs et employés de notaire (CRPCEN)", "base"),
    ("0600", "Banque de France"): ("banque_de_france", "Banque de France", None),
    ("1000", "IRCANTEC"): ("ircantec", "Ircantec (agents non titulaires de l'État et des collectivités)",
                           "complementaire"),
    ("2100", "CNAVPL"): ("cnavpl", "Professions libérales (CNAVPL), base", "base"),
    ("2200", "CNAVPL complementaire"): ("cnavpl_complementaire", "Professions libérales (CNAVPL), complémentaire",
                                        "complementaire"),
    ("2201", "CNBF"): ("cnbf", "Avocats (CNBF), base", "base"),
    ("2202", "CNBF complémentaire"): ("cnbf_complementaire", "Avocats (CNBF), complémentaire", "complementaire"),
    ("3000", "ERAFP"): ("rafp", "Retraite additionnelle de la fonction publique (RAFP)", "complementaire"),
    ("5600", "AGIRC-ARRCO"): ("agirc_arrco", "Agirc-Arrco (salariés du privé, complémentaire)", "complementaire"),
}

# champ de la table A -> (série d'effectifs, {mesure de la table: série de pension})
CHAMPS = {
    "ddir": ("retraites_droit_direct", {"m1": "pension_droit_direct_eur_mois", "mont": "pension_totale_eur_mois"}),
    "ddert": ("retraites_droit_derive", {"m2": "pension_droit_derive_eur_mois"}),
    "dtot": ("retraites_tous_droits", {}),
    "nl_ddir": ("nouveaux_retraites_droit_direct", {}),
}
SERIES = ["retraites_droit_direct", "retraites_droit_derive", "retraites_tous_droits",
          "nouveaux_retraites_droit_direct", "pension_droit_direct_eur_mois", "pension_totale_eur_mois",
          "pension_droit_derive_eur_mois"]
DEFINITIONS = {
    "retraites_droit_direct": "retraités de droit direct du régime, vivants au 31 décembre (champ « ddir » de l'EACR)",
    "retraites_droit_derive": "bénéficiaires d'une pension de droit dérivé (réversion), avec ou sans droit direct, "
                              "vivants au 31 décembre (champ « ddert »)",
    "retraites_tous_droits": "retraités de droit direct ou de droit dérivé, vivants au 31 décembre (champ « dtot »)",
    "nouveaux_retraites_droit_direct": "personnes ayant liquidé un droit direct dans le régime au cours de l'année, "
                                       "vivantes au 31 décembre (champ « nl_ddir »)",
    "pension_droit_direct_eur_mois": "avantage principal de droit direct moyen des retraités de droit direct, montant "
                                     "de décembre, en euros par mois (mesure « m1 » : minima de pension compris, hors "
                                     "réversion, hors majorations)",
    "pension_totale_eur_mois": "pension totale moyenne des retraités de droit direct, montant de décembre, en euros "
                               "par mois (mesure « mont » : majorations comprises ; Agirc-Arrco : droit direct et "
                               "majorations seulement)",
    "pension_droit_derive_eur_mois": "avantage principal de droit dérivé moyen des bénéficiaires d'un droit dérivé, "
                                     "montant de décembre, en euros par mois (mesure « m2 »)",
    "source_eacr": "millésime de l'enquête ou du modèle d'où vient la valeur retenue de l'année (la DREES interroge "
                   "les caisses deux fois sur chaque année ; la valeur la plus récente est gardée)",
    "zeros_source": "séries et années pour lesquelles la source donne une pension moyenne égale à 0 : valeur publiée "
                    "null",
    "cotisants": "effectif de cotisants publié par une autre source que l'EACR, avec sa définition ; absent quand "
                 "aucun jeu ouvert n'a été trouvé",
}

# Régimes dont le nom figure tel quel parmi les régimes des comptes de la protection sociale (secu/cps/).
CPS_REGIMES = {
    "cnav_avec_independants": "Caisse nationale d’assurance vieillesse",
    "agirc_arrco": "Association générale des institutions de retraite des cadres et association des régimes de "
                   "retraite complémentaire des salariés",
    "msa_salaries": "Régime des salariés agricoles",
    "msa_non_salaries": "Exploitants agricoles",
    "ircantec": "Institution de retraite complémentaire des agents non titulaires de l’État et des collectivités "
                "publiques",
    "rafp": "Régime additionnel de la fonction publique",
    "etat_civils": "Régimes pour les agents de l'État (y compris ex-L)",
    "etat_militaires": "Régimes pour les agents de l'État (y compris ex-L)",
}
SECU_ARBRE = {"agirc_arrco": "complementaires/agirc_arrco"}
# action de la mission Régimes sociaux et de retraite -> régime de l'EACR nommé dans l'intitulé de l'action
ACTIONS_REGIMES = {"198-03": "sncf", "198-04": "ratp", "197-01": "enim", "195-01": "canssm"}
PROGRAMMES_CAS = ["741", "742", "743"]
PROGRAMMES_RSR = ["195", "197", "198"]
SECTIONS_PROGRAMMES = {"YD-1": "741", "YD-2": "742", "YD-3": "743"}
# section du CAS Pensions -> régimes de l'EACR dont elle finance les pensions (intitulés des sections)
SECTIONS_REGIMES = {"YD-1": ["etat_civils", "etat_militaires"], "YD-2": ["fspoeie"], "YD-3": []}

ORIGINES = {
    "cotisations_salariales": "retenues pour pensions sur la rémunération des agents (lignes « retenues pour pensions »)",
    "contributions_employeurs": "contributions des employeurs : État, établissements publics, autres employeurs "
                                "d'agents détachés (lignes « contributions des employeurs »)",
    "cotisations_salariales_et_patronales": "ligne « Cotisations salariales et patronales » du régime des ouvriers "
                                            "de l'État, non séparées à la source",
    "contribution_fspoeie_ratocem": "ligne « Contribution au FSPOEIE et au RATOCEM »",
    "budget_general": "lignes « participation du budget général »",
    "transferts": "compensations entre régimes, transfert de la CNRACL, versements du Fonds de solidarité vieillesse",
    "autres": "recettes diverses, récupération d'indus",
}

LECTURE_ECART = {
    "sre": "champs différents : l'EACR ne compte les pensions d'invalidité des fonctionnaires qu'à partir de 62 ans "
           "et retient l'avantage principal de droit direct (mesure m1) ; le cube du Service des retraites de l'État "
           "compte toutes les pensions de droit direct en paiement et donne la somme des montants mensuels, dont la "
           "composition n'est pas détaillée sur la fiche du jeu",
    "cnracl": "champs différents : la Caisse des dépôts compte les pensions en paiement (vieillesse et invalidité) ; "
              "l'EACR ne compte les pensions d'invalidité qu'à partir de 62 ans",
    "msa": "valeurs lues sous les libellés de colonnes du fichier de la MSA (somme des intercommunalités) ; champ de "
           "la MSA : au moins une prestation vieillesse en paiement ; champ de l'EACR : retraités de droit direct ou "
           "dérivé",
}


def chemin(cle: str) -> Path:
    return BRUT / SOURCES[cle]["fichier"]


def _json(cle: str) -> list[dict]:
    return json.loads(chemin(cle).read_text(encoding="utf-8"))


def _slug(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def _nombre(v):
    """Nombre de la source, ou None (cellule vide, texte) : jamais 0 à la place d'une absence."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _entier(v):
    n = _nombre(v)
    return None if n is None else int(round(n))


def _arrondi(v, d=1):
    n = _nombre(v)
    if n is None:
        return None
    r = round(n, d)
    return int(r) if r == int(r) else r


# --- Lectures ---------------------------------------------------------------------------------------------------------

def lire_eacr() -> dict[tuple[str, str], dict]:
    """Table A-Cadrage : {(cc, caisse): {série: {année: valeur}, 'source_eacr': {année: millésime}}}.

    Lignes retenues : Sexe, Resid, Liq et StatutSNCF = « Ensemble », PlusRécent vrai (documentation de l'EACR)."""
    import openpyxl
    wb = openpyxl.load_workbook(chemin("drees_eacr"), read_only=True, data_only=True)
    ws = wb["A-Cadrage"]
    ws.reset_dimensions()
    lignes = ws.iter_rows(values_only=True)
    entete = [str(c) for c in next(lignes)]
    attendu = {"Année", "Source", "CC", "Caisse", "Sexe", "Resid", "Champ", "Liq", "StatutSNCF", "PlusRécent",
               "effectifs", "m1", "m2", "mont"}
    if not attendu <= set(entete):
        raise SystemExit(f"EACR, table A-Cadrage : colonnes manquantes {sorted(attendu - set(entete))}")
    out: dict[tuple[str, str], dict] = {}
    for ligne in lignes:
        x = dict(zip(entete, ligne))
        if x["Année"] is None or x["Champ"] not in CHAMPS:
            continue
        if not (x["Sexe"] == "Ensemble" and x["Resid"] == "Ensemble" and x["Liq"] == "Ensemble"
                and x["StatutSNCF"] == "Ensemble" and x["PlusRécent"] is True):
            continue
        cle = (str(x["CC"]).zfill(4), str(x["Caisse"]).strip())
        an = int(x["Année"])
        reg = out.setdefault(cle, {s: {} for s in SERIES} | {"source_eacr": {}, "zeros_source": {}})
        serie, mesures = CHAMPS[x["Champ"]]
        if an in reg[serie]:
            raise SystemExit(f"EACR : deux lignes « plus récentes » pour {cle} {an} {x['Champ']}")
        reg[serie][an] = _entier(x["effectifs"])
        for mesure, nom in mesures.items():
            v = _arrondi(x[mesure])
            if v == 0:  # pension moyenne à 0 pour un effectif non nul : valeur non fournie, publiée null avec mention
                reg["zeros_source"].setdefault(nom, []).append(an)
                v = None
            reg[nom][an] = v
        if x["Champ"] in ("ddir", "dtot"):
            reg["source_eacr"].setdefault(an, str(x["Source"]))
    wb.close()
    return out


def lire_drees_cotisants() -> dict[int, dict]:
    """{année: retraités de droit direct, emploi intérieur (personnes), rapport publié} ; tous régimes, y compris
    résidents à l'étranger."""
    import openpyxl
    wb = openpyxl.load_workbook(chemin("drees_cotisants"), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    ws.reset_dimensions()
    out = {}
    for ligne in ws.iter_rows(values_only=True):
        if ligne and isinstance(ligne[0], (int, float)) and 1990 < ligne[0] < 2100 and len(ligne) >= 5:
            retr, emploi, rapport = _nombre(ligne[1]), _nombre(ligne[3]), _nombre(ligne[4])
            out[int(ligne[0])] = {"retraites_droit_direct": None if retr is None else int(round(retr * 1000)),
                                  "emploi_interieur": None if emploi is None else int(round(emploi * 1000)),
                                  "rapport": None if rapport is None else round(rapport, 3)}
    wb.close()
    return out


def lire_sre(cle: str) -> dict[int, tuple[int, float]]:
    """{année: (effectif, somme des montants mensuels)} ; une ligne sans effectif ou sans montant fait échouer."""
    out: dict[int, list] = {}
    for x in _json(cle):
        an, eff, mt = int(x["annee"]), _entier(x["effectif"]), _nombre(x["montant_pension"])
        if eff is None or mt is None:
            raise SystemExit(f"{cle} : effectif ou montant absent pour {an}")
        acc = out.setdefault(an, [0, 0.0])
        acc[0] += eff
        acc[1] += mt
    return {an: (v[0], v[1]) for an, v in sorted(out.items())}


def origine_recette(libelle: str) -> str:
    l = libelle.lower()
    if "participation du budget général" in l:
        return "budget_general"
    if "retenues pour pensions" in l:
        return "cotisations_salariales"
    if "contributions des employeurs" in l:
        return "contributions_employeurs"
    if l.startswith("cotisations salariales et patronales"):
        return "cotisations_salariales_et_patronales"
    if l.startswith("contribution au fonds spécial des pensions des ouvriers"):
        return "contribution_fspoeie_ratocem"
    if any(m in l for m in ("compensation", "transfert", "fonds de solidarité vieillesse")):
        return "transferts"
    return "autres"


def lire_recettes_cas() -> list[dict]:
    out = []
    for x in _json("plf25_recettes_cas"):
        if x.get("libelle_mission") != "Pensions":
            continue
        out.append({"code": x["code_ligne_de_recette"], "section": x["code_section"],
                    "section_nom": x["libelle_section"], "libelle": x["libelle_ligne_de_recette"],
                    "origine": origine_recette(x["libelle_ligne_de_recette"]),
                    "montant_eur": _entier(x["montant_recettes_plf_2025"])})
    return sorted(out, key=lambda r: r["code"])


def lire_depenses_plf(programmes: list[str]) -> dict[str, dict]:
    """{programme: {nom, mission, actions: {code: {nom, cp_eur}}}} ; crédits de paiement sommés par action."""
    out: dict[str, dict] = {}
    for x in _json("plf25_depenses"):
        if x.get("programme") not in programmes:
            continue
        p = out.setdefault(x["programme"], {"nom": x["libelle_programme"], "mission": x["libelle_mission"],
                                            "actions": {}})
        a = p["actions"].setdefault(x["action"], {"nom": x["libelle_action"], "cp_eur": 0.0})
        a["cp_eur"] += _nombre(x["credit_de_paiement"]) or 0.0
    return out


def lire_cnracl_actifs() -> dict[int, int]:
    out: dict[int, float] = {}
    for x in _json("cdc_cnracl_actifs"):
        f, h = _nombre(x.get("effectif_f")), _nombre(x.get("effectif_h"))
        if f is None or h is None:
            raise SystemExit(f"cdc_cnracl_actifs : effectif absent ({x.get('annee')}, {x.get('type_collectivite')})")
        out[int(x["annee"])] = out.get(int(x["annee"]), 0.0) + f + h
    return {a: int(round(v)) for a, v in sorted(out.items())}


def lire_cnracl_retraites() -> dict[int, dict]:
    """{année: {droit_direct, droit_derive (pensions en paiement), pension_vieillesse_droit_direct_eur_mois}}."""
    out: dict[int, dict] = {}
    for x in _json("cdc_cnracl_retraites"):
        an = int(x["annee"])
        f, h = _nombre(x.get("stock_pens_femme")), _nombre(x.get("stock_pens_homme"))
        if f is None or h is None:
            raise SystemExit(f"cdc_cnracl_retraites : effectif absent ({an})")
        r = out.setdefault(an, {"droit_direct": 0, "droit_derive": 0, "pension_vieillesse_droit_direct_eur_mois": None})
        cle = "droit_direct" if x["nature_droit"] == "Droit direct" else "droit_derive"
        r[cle] += int(round(f + h))
        if cle == "droit_direct" and x["type_risque"] == "Vieillesse":
            r["pension_vieillesse_droit_direct_eur_mois"] = _arrondi((_nombre(x.get("pension_moy_annuelle")) or 0) / 12) \
                if _nombre(x.get("pension_moy_annuelle")) is not None else None
    return dict(sorted(out.items()))


def lire_ircantec_cotisants() -> dict[int, int]:
    out: dict[int, float] = {}
    for x in _json("cdc_ircantec_cotisants"):
        v = _nombre(x.get("effectif_cotisants"))
        if v is None:
            raise SystemExit(f"cdc_ircantec_cotisants : effectif absent ({x.get('annee')})")
        out[int(x["annee"])] = out.get(int(x["annee"]), 0.0) + v
    return {a: int(round(v)) for a, v in sorted(out.items())}


COL_MSA = ("Nb.retraites.salaries.agricoles", "Nb.retraites.non.salaries.agricoles")


def lire_msa() -> dict[int, dict]:
    """{année: {colonne: somme, 'intercommunalites': n, 'non_numeriques': n}} ; une cellule non numérique (secret
    statistique, vide) n'est pas comptée et son nombre est publié."""
    out = {}
    for f in sorted(chemin("msa_retraites").glob("ret_stock_*.csv")):
        an = int(f.stem.rsplit("_", 1)[1])
        with f.open(encoding="utf-8-sig", newline="") as fh:
            lignes = list(csv.DictReader(fh, delimiter=";"))
        if not lignes or not set(COL_MSA) <= set(lignes[0]):
            raise SystemExit(f"{f.name} : colonnes attendues absentes")
        sommes, manquants = {c: 0 for c in COL_MSA}, 0
        for l in lignes:
            for c in COL_MSA:
                v = (l[c] or "").strip()
                if v.isdigit():
                    sommes[c] += int(v)
                else:
                    manquants += 1
        out[an] = {**sommes, "intercommunalites": len(lignes), "non_numeriques": manquants}
    return out


# --- Liens vers les vues déjà publiées --------------------------------------------------------------------------------

def _charger(rel: str):
    p = SITE / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _noeud(doc, ident: str):
    if not isinstance(doc, dict):
        return None
    if doc.get("id") == ident:
        return doc
    for e in doc.get("enfants") or []:
        t = _noeud(e, ident)
        if t:
            return t
    return None


def fichiers_regimes_cps() -> dict[str, str]:
    """{nom du régime: fichier} d'après secu/cps/racine.json."""
    racine = _charger("secu/cps/racine.json") or {}
    return {g["nom"]: g["fichier"] for s in racine.get("enfants", []) for g in s.get("enfants", []) if "fichier" in g}


def fichier_programme(numero: str) -> str | None:
    f = sorted((SITE / "arbre").glob(f"*_{numero}.json"))
    return f"arbre/{f[0].name}" if f else None


def liens_regime(rid: str, cps: dict[str, str], partages: dict[str, list[str]]) -> list[dict]:
    out = []
    nom = CPS_REGIMES.get(rid)
    if nom and nom in cps:
        doc = _charger(cps[nom])
        l = {"vue": "secu_cps", "fichier": cps[nom], "id": doc["id"], "nom": doc["nom"], "md": doc["md"],
             "millesime": doc.get("millesime"),
             "lecture": "toutes les prestations versées par le régime dans les comptes de la protection sociale "
                        "(DREES), pensions et autres prestations ; ne s'additionne à aucun montant de cette vue"}
        if len(partages.get(nom, [])) > 1:
            l["partage_avec"] = [r for r in partages[nom] if r != rid]
        out.append(l)
    if rid in SECU_ARBRE:
        doc = _charger("secu/arbre/racine.json")
        n = _noeud(doc, SECU_ARBRE[rid])
        if n:
            out.append({"vue": "secu_arbre", "fichier": "secu/arbre/racine.json", "id": n["id"], "nom": n["nom"],
                        "md": n["md"], "millesime": doc.get("millesime"),
                        "lecture": "dépenses de l'organisme (comptes des organismes de sécurité sociale)"})
    for action, r in sorted(ACTIONS_REGIMES.items()):
        if r != rid:
            continue
        rel = fichier_programme(action.split("-")[0])
        doc = _charger(rel) if rel else None
        n = next((e for e in (doc or {}).get("enfants", []) if e["id"].endswith("/" + action)), None)
        if n:
            out.append({"vue": "arbre_etat", "fichier": rel, "id": n["id"], "nom": n["nom"], "md": n["md"],
                        "millesime": doc.get("millesime"),
                        "lecture": "crédits versés par l'État au régime (mission Régimes sociaux et de retraite) : "
                                   "une ressource du régime, pas une dépense supplémentaire"})
    if rid != "tous_regimes" and _charger("prestations/nationales.json"):
        out.append({"vue": "prestations", "fichier": "prestations/nationales.json", "id": "pensions_retraite",
                    "nom": "Pensions de retraite (droit direct et réversion), tous régimes",
                    "lecture": "montants des pensions par régime (comptes de la protection sociale), publiés par la "
                               "vue des prestations : non recopiés ici"})
    return out


# --- Production -------------------------------------------------------------------------------------------------------

def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def _ecart(objet: str, regime: str, annee: int, grandeur: str, source: str, valeur, autre_source: str, autre_valeur,
           lecture: str) -> dict | None:
    if valeur is None or autre_valeur is None:
        return None
    d = valeur - autre_valeur
    return {"objet": objet, "regime": regime, "annee": annee, "grandeur": grandeur, "source": source,
            "valeur": valeur, "autre_source": autre_source, "autre_valeur": autre_valeur,
            "ecart": _arrondi(d), "ecart_pct": round(d / autre_valeur * 100, 1) if autre_valeur else None,
            "lecture_ecart": lecture}


def _serie(valeurs: dict[int, object], annees: list[int]) -> dict[str, object]:
    return {str(a): valeurs.get(a) for a in annees}


def produire() -> dict:
    date = date_sources("secu")
    eacr = lire_eacr()
    annees = sorted({a for reg in eacr.values() for s in SERIES for a in reg[s]})

    # --- régimes ---
    regimes: dict[str, dict] = {}
    ordre = []
    for (cc, caisse), reg in sorted(eacr.items()):
        rid, nom, typ = REGIMES.get((cc, caisse), (f"{_slug(caisse)}_{cc}", caisse, None))
        if rid in regimes:
            raise SystemExit(f"identifiant de régime en double : {rid}")
        ans = sorted({a for s in SERIES for a, v in reg[s].items() if v is not None})
        regimes[rid] = {
            "nom": nom, "code_caisse": cc, "libelle_source": caisse, "type": typ,
            "premiere_annee": ans[0] if ans else None, "derniere_annee": ans[-1] if ans else None,
            **{s: _serie(reg[s], annees) for s in SERIES},
            "source_eacr": _serie(reg["source_eacr"], annees),
        }
        if reg["zeros_source"]:
            regimes[rid]["zeros_source"] = {s: sorted(a) for s, a in sorted(reg["zeros_source"].items())}
        ordre.append(rid)

    # --- cotisants publiés hors EACR ---
    cot_drees = lire_drees_cotisants()
    actifs_cnracl = lire_cnracl_actifs()
    cot_ircantec = lire_ircantec_cotisants()
    cotisants = {
        "tous_regimes": {
            "source": "drees_cotisants", "annees": sorted(cot_drees),
            "definition": "emploi intérieur (comptes nationaux), que la DREES rapporte aux retraités de droit direct "
                          "tous régimes pour son « rapport cotisants / retraités » ; série arrêtée en 2016",
            "valeurs": _serie({a: v["emploi_interieur"] for a, v in cot_drees.items()}, annees),
            "rapport_cotisants_retraites_publie": _serie({a: v["rapport"] for a, v in cot_drees.items()}, annees),
            "retraites_droit_direct_publies": _serie({a: v["retraites_droit_direct"] for a, v in cot_drees.items()},
                                                    annees),
        },
        "cnracl": {
            "source": "cdc_cnracl_actifs", "annees": sorted(actifs_cnracl),
            "definition": "agents actifs affiliés à la CNRACL, femmes et hommes, tous types de collectivités "
                          "territoriales et hospitalières (somme des lignes du jeu)",
            "valeurs": _serie(actifs_cnracl, annees),
        },
        "ircantec": {
            "source": "cdc_ircantec_cotisants", "annees": sorted(cot_ircantec),
            "definition": "cotisants de l'Ircantec, toutes familles d'employeurs (somme des lignes du jeu)",
            "valeurs": _serie(cot_ircantec, annees),
        },
    }
    for rid, c in cotisants.items():
        if rid in regimes:
            regimes[rid]["cotisants"] = c
            if rid != "tous_regimes":
                c["rapport_cotisants_retraites_droit_direct"] = {
                    a: (round(c["valeurs"][a] / regimes[rid]["retraites_droit_direct"][a], 3)
                        if c["valeurs"][a] and regimes[rid]["retraites_droit_direct"][a] else None)
                    for a in c["valeurs"]}
                c["rapport_methode"] = ("cotisants de cette source / retraités de droit direct de l'EACR : deux "
                                        "sources, deux champs ; ordre de grandeur")

    # --- écarts entre sources ---
    ecarts = []
    sre = {k: lire_sre(k) for k in ("sre_civils", "sre_militaires", "sre_gendarmes")}
    cubes = {"etat_civils": ["sre_civils"], "etat_militaires": ["sre_militaires", "sre_gendarmes"]}
    for rid, cles in cubes.items():
        if rid not in regimes:
            continue
        for an in sorted(set.intersection(*(set(sre[k]) for k in cles))):
            eff = sum(sre[k][an][0] for k in cles)
            moy = _arrondi(sum(sre[k][an][1] for k in cles) / eff) if eff else None
            src = " + ".join(cles)
            ecarts.append(_ecart("retraités de droit direct", rid, an, "effectif", src, eff, "drees_eacr",
                                 regimes[rid]["retraites_droit_direct"].get(str(an)), LECTURE_ECART["sre"]))
            ecarts.append(_ecart("pension moyenne de droit direct", rid, an, "eur_mois", src, moy, "drees_eacr",
                                 regimes[rid]["pension_droit_direct_eur_mois"].get(str(an)), LECTURE_ECART["sre"]))
    cnracl_cdc = lire_cnracl_retraites()
    if "cnracl" in regimes:
        for an, v in cnracl_cdc.items():
            ecarts.append(_ecart("retraités de droit direct", "cnracl", an, "effectif", "cdc_cnracl_retraites",
                                 v["droit_direct"], "drees_eacr",
                                 regimes["cnracl"]["retraites_droit_direct"].get(str(an)), LECTURE_ECART["cnracl"]))
            ecarts.append(_ecart("bénéficiaires d'un droit dérivé", "cnracl", an, "effectif", "cdc_cnracl_retraites",
                                 v["droit_derive"], "drees_eacr",
                                 regimes["cnracl"]["retraites_droit_derive"].get(str(an)), LECTURE_ECART["cnracl"]))
    if "tous_regimes" in regimes:
        for an, v in sorted(cot_drees.items()):
            ecarts.append(_ecart("retraités de droit direct", "tous_regimes", an, "effectif", "drees_cotisants",
                                 v["retraites_droit_direct"], "drees_eacr",
                                 regimes["tous_regimes"]["retraites_droit_direct"].get(str(an)),
                                 "même producteur : valeur du classeur de 2016 (en milliers, arrondie avant 2011) et "
                                 "valeur de la diffusion de 2026"))
    msa = lire_msa()
    ecarts_msa, inverses = [], []
    for an, v in sorted(msa.items()):
        a, b = v[COL_MSA[0]], v[COL_MSA[1]]
        sal = regimes.get("msa_salaries", {}).get("retraites_tous_droits", {}).get(str(an))
        nsa = regimes.get("msa_non_salaries", {}).get("retraites_tous_droits", {}).get(str(an))
        ligne = {"annee": an, "colonne_salaries_agricoles": a, "colonne_non_salaries_agricoles": b,
                 "intercommunalites": v["intercommunalites"], "cellules_non_numeriques": v["non_numeriques"],
                 "eacr_msa_salaries_tous_droits": sal, "eacr_msa_non_salaries_tous_droits": nsa}
        if sal is not None and nsa is not None:
            ligne["ecart_salaries"] = a - sal
            ligne["ecart_non_salaries"] = b - nsa
        ecarts_msa.append(ligne)
    # constat sans dépendre de l'EACR : la colonne « salariés » est tantôt la plus grande des deux, tantôt la plus petite
    grande = {an: v[COL_MSA[0]] > v[COL_MSA[1]] for an, v in msa.items()}
    if len(set(grande.values())) > 1:
        majorite = sorted(grande.values()).count(True) >= len(grande) / 2
        inverses = sorted(an for an, g in grande.items() if g != majorite)
    ecarts = [e for e in ecarts if e]

    # --- État : CAS Pensions, SRE, crédits aux régimes spéciaux ---
    recettes = lire_recettes_cas()
    dep_cas = lire_depenses_plf(PROGRAMMES_CAS)
    dep_rsr = lire_depenses_plf(PROGRAMMES_RSR)
    programmes_cas, sections = [], []
    for num in PROGRAMMES_CAS:
        p = dep_cas.get(num)
        if not p:
            raise SystemExit(f"PLF 2025 : programme {num} absent du jeu des dépenses")
        actions = [{"action": c, "nom": a["nom"], "cp_eur": _entier(a["cp_eur"])} for c, a in sorted(p["actions"].items())]
        programmes_cas.append({"programme": num, "nom": p["nom"], "cp_eur": sum(a["cp_eur"] for a in actions),
                               "actions": actions})
    for code in sorted({r["section"] for r in recettes}):
        lignes = [r for r in recettes if r["section"] == code]
        par_origine = {o: sum(r["montant_eur"] for r in lignes if r["origine"] == o) for o in ORIGINES}
        total = sum(r["montant_eur"] for r in lignes)
        prog = SECTIONS_PROGRAMMES.get(code)
        dep = next((p["cp_eur"] for p in programmes_cas if p["programme"] == prog), None)
        sections.append({
            "section": code, "nom": lignes[0]["section_nom"], "programme": prog,
            "regimes": [r for r in SECTIONS_REGIMES.get(code, []) if r in regimes], "recettes_eur": total,
            "depenses_cp_eur": dep, "recettes_moins_depenses_eur": None if dep is None else total - dep,
            "par_origine_eur": {o: v for o, v in par_origine.items() if v},
            "lignes": [{"code": r["code"], "libelle": r["libelle"], "origine": r["origine"],
                        "montant_eur": r["montant_eur"]} for r in lignes],
        })
    total_recettes = sum(s["recettes_eur"] for s in sections)
    total_depenses = sum(p["cp_eur"] for p in programmes_cas)
    par_origine_total = {o: sum(s["par_origine_eur"].get(o, 0) for s in sections) for o in ORIGINES}

    credits = []
    for num in PROGRAMMES_RSR:
        rel = fichier_programme(num)
        doc = _charger(rel) if rel else None
        plf = dep_rsr.get(num, {"nom": None, "actions": {}})
        codes = sorted(set(plf["actions"]) | {e["id"].rsplit("/", 1)[1] for e in (doc or {}).get("enfants", [])})
        actions = []
        for c in codes:
            n = next((e for e in (doc or {}).get("enfants", []) if e["id"].endswith("/" + c)), None)
            a = plf["actions"].get(c)
            actions.append({
                "action": c, "nom": (a or {}).get("nom") or (n or {}).get("nom"),
                "regime": ACTIONS_REGIMES.get(c),
                "execution_2024_eur": None if n is None else int(round(n["md"] * 1e9)),
                "plf_2025_cp_eur": None if a is None else _entier(a["cp_eur"]),
                **({"fichier": rel, "id": n["id"]} if n else {}),
            })
        credits.append({
            "programme": num, "nom": plf["nom"] or (doc or {}).get("nom"),
            "execution_2024_eur": None if doc is None else int(round(doc["md"] * 1e9)),
            "plf_2025_cp_eur": sum(a["plf_2025_cp_eur"] or 0 for a in actions) if plf["actions"] else None,
            **({"fichier": rel, "id": doc["id"]} if doc else {}),
            "actions": actions,
        })

    annees_sre = sorted(set.union(*(set(v) for v in sre.values())))
    populations = {"sre_civils": "Pensions civiles de droit direct", "sre_militaires": "Pensions militaires de droit "
                   "direct, hors gendarmes", "sre_gendarmes": "Pensions de droit direct des gendarmes"}
    etat = {
        "millesime": f"PLF 2025 (compte d'affectation spéciale Pensions, crédits aux régimes spéciaux) ; exécution "
                     f"2024 (crédits aux régimes spéciaux) ; {annees_sre[0]} à {annees_sre[-1]} (retraités de l'État)",
        "source": "Direction du budget (PLF 2025 : recettes des CAS et des CCF, dépenses selon destination) ; "
                  "Service des retraites de l'État (DGFiP), cubes de pensions en paiement ; budget de l'État, "
                  "exécution 2024 (site/data/arbre)",
        "unite": "euros ; pensions en paiement ; euros par mois",
        "cas_pensions": {
            "millesime": "PLF 2025 (prévisions, avant vote et avant exécution)",
            "definition": "compte d'affectation spéciale : ses dépenses (pensions des fonctionnaires civils et "
                          "militaires de l'État, des ouvriers de l'État, pensions militaires d'invalidité) sont "
                          "financées par des recettes qui lui sont affectées",
            "depenses_cp_eur": total_depenses, "recettes_eur": total_recettes,
            "recettes_moins_depenses_eur": total_recettes - total_depenses,
            "programmes": programmes_cas,
            "recettes_par_origine_eur": par_origine_total,
            "recettes_par_origine_pct": {o: round(v / total_recettes * 100, 2) for o, v in par_origine_total.items()},
            "origines": ORIGINES,
            "sections": sections,
            "methode": "chaque ligne de recette du PLF est classée par son libellé (règles dans `origines`) ; les "
                       "contributions des employeurs comprennent celles que l'État verse comme employeur depuis les "
                       "programmes du budget général : la même somme figure donc en dépense de personnel de ces "
                       "programmes et en recette du compte, elle ne s'additionne pas aux dépenses du budget général",
        },
        "retraites_etat": {
            "definition": "pensions de droit direct en paiement au 31 décembre, liquidées par le Service des "
                          "retraites de l'État ; pension moyenne = somme des montants mensuels / effectif",
            "annees": annees_sre,
            "populations": {
                k: {"nom": populations[k],
                    "effectif": _serie({a: v[0] for a, v in sre[k].items()}, annees_sre),
                    "pension_moyenne_eur_mois": _serie({a: _arrondi(v[1] / v[0]) for a, v in sre[k].items() if v[0]},
                                                       annees_sre)}
                for k in ("sre_civils", "sre_militaires", "sre_gendarmes")},
            "note": "les mêmes pensions sont décrites dans regimes.json (etat_civils, etat_militaires) d'après "
                    "l'EACR, avec un champ différent : les écarts sont dans index.json",
        },
        "credits_regimes_speciaux": {
            "definition": "crédits de la mission Régimes sociaux et de retraite du budget général, versés aux "
                          "régimes spéciaux ; deux millésimes côte à côte (exécution 2024 d'après l'arbre du budget "
                          "de l'État, prévision du PLF 2025), qui ne sont pas un écart entre sources",
            "programmes": credits,
            "total_execution_2024_eur": sum(c["execution_2024_eur"] or 0 for c in credits),
            "total_plf_2025_cp_eur": sum(c["plf_2025_cp_eur"] or 0 for c in credits),
        },
        "limites": [
            "PLF 2025 : prévisions déposées en octobre 2024, ni les montants votés ni l'exécution",
            "les recettes du compte ne sont pas ventilées par régime au-delà des trois sections",
            "le programme 743 finance des pensions militaires d'invalidité et des allocations de reconnaissance, qui "
            "ne sont pas des pensions de retraite",
        ],
    }

    # --- index ---
    cps = fichiers_regimes_cps()
    partages: dict[str, list[str]] = {}
    for rid, nom in CPS_REGIMES.items():
        if rid in regimes:
            partages.setdefault(nom, []).append(rid)
    derniere = max(r["derniere_annee"] for r in regimes.values() if r["derniere_annee"])
    tous = regimes.get("tous_regimes", {})
    index = {
        "millesime": f"{annees[0]} à {annees[-1]} (DREES, EACR) ; PLF 2025 et exécution 2024 (État)",
        "source": "DREES (enquête annuelle auprès des caisses de retraite) ; Service des retraites de l'État ; "
                  "direction du budget (PLF 2025) ; Caisse des dépôts (CNRACL, Ircantec) ; MSA ; liens vers les "
                  "prestations, la Sécurité sociale et le budget de l'État déjà publiés",
        "unite": "personnes ; euros par mois ; euros",
        "date_sources": date,
        "annees": annees,
        "derniere_annee": derniere,
        "fichiers": {"regimes": "retraites/regimes.json", "etat": "retraites/etat.json"},
        "regimes": [{"id": rid, "nom": regimes[rid]["nom"], "code_caisse": regimes[rid]["code_caisse"],
                     "type": regimes[rid]["type"], "premiere_annee": regimes[rid]["premiere_annee"],
                     "derniere_annee": regimes[rid]["derniere_annee"],
                     "cotisants_publies": rid in cotisants,
                     "liens": liens_regime(rid, cps, partages)} for rid in ordre],
        "tous_regimes": {
            "annee": derniere,
            "retraites_droit_direct": tous.get("retraites_droit_direct", {}).get(str(derniere)),
            "retraites_tous_droits": tous.get("retraites_tous_droits", {}).get(str(derniere)),
            "pension_droit_direct_eur_mois": tous.get("pension_droit_direct_eur_mois", {}).get(str(derniere)),
            "note": "estimation de la DREES (modèle Ancêtre) : chaque personne comptée une fois, résidents en France "
                    "ou à l'étranger",
        } if tous else None,
        "types": {"base": "régime de base", "complementaire": "régime complémentaire",
                  "integre": "régime intégré (base et complémentaire dans une seule pension)",
                  "ensemble": "ensemble des régimes",
                  "null": "type non lu dans la nomenclature de la documentation de l'EACR"},
        "definitions": DEFINITIONS,
        "ecarts": ecarts,
        "ecarts_msa": {
            "source": "msa_retraites", "autre_source": "drees_eacr",
            "lignes": ecarts_msa,
            "annees_colonnes_inversees": inverses,
            "constat": ("dans les fichiers de la MSA, la colonne intitulée « salariés agricoles » porte le plus grand "
                        "des deux effectifs certaines années et le plus petit les autres années ("
                        + ", ".join(str(a) for a in inverses) + ") ; les libellés de la source sont repris sans "
                        "correction, et la comparaison avec l'EACR est donnée pour chaque colonne") if inverses else
                       "les deux colonnes gardent le même ordre de grandeur d'une année à l'autre",
            "lecture_ecart": LECTURE_ECART["msa"],
        },
        "cotisants": {rid: {"source": c["source"], "annees": c["annees"], "definition": c["definition"]}
                      for rid, c in cotisants.items()},
        "regle": "agrégats publiés seulement ; les effectifs des régimes ne s'additionnent pas (une personne qui "
                 "perçoit des pensions de plusieurs régimes est comptée dans chacun) ; aucune masse de pensions n'est "
                 "recalculée à partir d'un effectif et d'une moyenne ; une valeur absente à la source est null, "
                 "jamais 0 ; les écarts entre sources sont publiés tels quels, sans choisir une source",
        "limites": [
            "effectifs au 31 décembre et montants perçus en décembre : selon la DREES, effectif × pension moyenne × 12 "
            "ne redonne pas les dépenses de l'année",
            "pensions moyennes par régime : part versée par ce régime seulement, pas la pension totale d'une "
            "personne qui a cotisé à plusieurs régimes",
            "régime général : deux séries distinctes à la source (avant et après l'intégration de la sécurité sociale "
            "des indépendants), non raccordées ici",
            "SNCF : années publiées par la DREES sur le seul champ des « pensions normales » laissées vides",
            "cotisants : publiés en données ouvertes pour la CNRACL, l'Ircantec et l'ensemble des régimes "
            "(jusqu'en 2016) seulement",
            "ressources par origine : publiées en données ouvertes pour le compte d'affectation spéciale Pensions "
            "(prévisions du PLF 2025) et pour les crédits de l'État aux régimes spéciaux seulement",
        ],
        # `entrepot` : nom dans data/lake/secu/ (pas `fichier`, réservé par le contrat aux liens vers site/data)
        "sources": {k: {("entrepot" if c == "fichier" else c): x for c, x in v.items()}
                    for k, v in sorted(SOURCES.items())},
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    doc_regimes = {
        "millesime": f"{annees[0]} à {annees[-1]}",
        "source": f"{SOURCES['drees_eacr']['titre']} ; cotisants : Caisse des dépôts (CNRACL, Ircantec) et DREES "
                  "(emploi intérieur)",
        "unite": "personnes ; euros par mois (montants de décembre)",
        "annees": annees,
        "definitions": DEFINITIONS,
        "note_perimetre": "lignes retenues dans la table A-Cadrage : ensemble des sexes, des lieux de résidence et "
                          "des modes de liquidation, valeur la plus récente de chaque année ; une année sans ligne "
                          "pour un régime est null ; une pension moyenne égale à 0 dans la source est publiée null "
                          "et l'année est listée dans `zeros_source` du régime",
        "regimes": {rid: regimes[rid] for rid in ordre},
    }
    dump(SORTIE / "regimes.json", doc_regimes)
    dump(SORTIE / "etat.json", etat)
    dump(SORTIE / "index.json", index)
    print(f"retraites : {len(regimes)} régimes, {annees[0]}-{annees[-1]}, {len(ecarts)} écarts, "
          f"{len(ecarts_msa)} années MSA, CAS Pensions {total_depenses / 1e9:.1f} Md€ de dépenses prévues")
    return index


# --- Collecte ---------------------------------------------------------------------------------------------------------

def telecharger(url: str, dest: Path, essais: int = 5) -> str:
    import requests
    derniere = ""
    for i in range(essais):
        try:
            r = requests.get(url, timeout=(20, 300), headers={"User-Agent": "ou-vont-mes-impots/pipeline"})
            if r.status_code in (401, 403, 429, 451):
                return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
            r.raise_for_status()
            debut = r.content[:4]
            if (dest.suffix == ".xlsx" and debut != b"PK\x03\x04") or (dest.suffix == ".json" and debut[:1] != b"[") \
                    or (dest.suffix == ".csv" and b"<html" in r.content[:200].lower()):
                return "contenu inattendu (page HTML au lieu du fichier) : aucun contournement"
            from fetch import octets_annonces, remplacer_si_valide  # controle collecte/integrite.py
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(r.content)
            remplacer_si_valide(tmp, dest, octets_attendus=octets_annonces(r))  # invalide : dest conserve
            return "ok"
        except Exception as e:  # reprise réseau
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(4 * (i + 1))
    return f"échec après {essais} essais : {derniere}"


def collecter(forcer: bool = False) -> dict:
    etat = {}
    cibles = [(cle, SOURCES[cle]["url"], chemin(cle)) for cle in COLLECTABLES]
    cibles += [(f"msa_retraites_{an}", url, chemin("msa_retraites") / f"ret_stock_{an}.csv")
               for an, url in SOURCES["msa_retraites"]["ressources"].items()]
    for cle, url, dest in cibles:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0 and not forcer:
            etat[cle] = "présent"
        else:
            etat[cle] = telecharger(url, dest)
        print(f"{cle}: {etat[cle]}")
    return etat


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true", help="retélécharger les sources déjà présentes")
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter(a.forcer)
    if a.etape in ("produire", "tout"):
        produire()


if __name__ == "__main__":
    main()
