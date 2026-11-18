"""Territoires comparables : typologies des communes (densité, aires d'attraction, strates de l'OFGL) et croisements prédéfinis.

Pour chaque commune du code officiel géographique en vigueur (mêmes codes que site/data/local/geo) : niveau de la
grille communale de densité 2025 de l'Insee (7 niveaux et 3 niveaux), catégorie et tranche de l'aire d'attraction des
villes 2020 (Insee), strate de population de l'OFGL ; puis, pour une liste FERMÉE de croisements (CROISEMENTS, douze
paires de grandeurs d'une même année et d'un même périmètre communal ; CROISEMENTS_DEP, une paire entre départements,
facette : tranche de population), les deux valeurs de la commune et, par case
(niveau de densité, strate, catégorie d'aire, ensemble), la dispersion des communes : quantiles et bandes par tranche
de la grandeur en abscisse. Aucun coefficient, aucune droite de régression : deux chiffres côte à côte ne disent pas
que l'un explique l'autre, et ce sont des moyennes de communes, pas d'habitants.

Entrées (data/lake, collectées par collecte/collecte.py ; identifiants déclarés dans collecte/catalogue.json) :
  typologies/typologies_grille_densite.xlsx          Insee, grille communale de densité 2025, géographie 2026
  typologies/typologies_aav2020.zip                  Insee, aires d'attraction des villes 2020, géographie 2026
  typologies/typologies_ofgl_communes.csv            OFGL, comptes consolidés des communes 2023 et 2024 (5 agrégats)
  revenus_communes/revenus_communes_passage_cog.zip  Insee, table de passage annuelle 2026 (entrée existante, lue)
  lecture seule : site/data/local/geo/<dep>.json, site/data/local/taux/<dep>.json, site/data/revenus_communes/communes,
                  site/data/investissement_communes/communes, site/data/territoires/<dep>.json (dotations DGCL,
                  aide sociale DREES), site/data/fiscalite_locale_series/communes, site/data/solidarites_departements/
                  comptes.json (population OFGL), site/data/assurance_maladie_territoires/departements.json
Sorties (site/data/typologies/, chaque fichier < 1 Mo, avec `millesime` et `source`) :
  index.json                 variables, croisements prédéfinis, facettes (cases), strates de l'OFGL, contrôles, sources
  croisements/<id>.json      par facette et par case : effectif, quantiles, bandes ; axes communs à toutes les cases
  communes/<dep>.json        par commune : typologies et valeurs des variables (null avec motif)

Commandes :
  python pipeline/typologies.py collecter     # réseau : collecte/collecte.py sur les quatre entrées
  python pipeline/typologies.py produire      # sans réseau ; --sortie DOSSIER pour une copie de contrôle
  python pipeline/typologies.py               # les deux

Règles :
  - règle 13 : un croisement n'existe que si ses deux grandeurs portent sur la même année et le même périmètre (la
    commune, dans ses limites de l'année des données, inchangées jusqu'au code officiel géographique 2026) ; sinon la
    valeur est null avec son motif (`perimetre`) ;
  - une valeur non publiée (secret statistique, absence) reste null avec son motif, jamais 0 ;
  - quantiles, moyennes de communes, bandes et rapports agrégés par strate sont des calculs du site
    (`statut` = « calculé par le site », méthode écrite à côté) ; les montants par habitant sont ceux publiés par
    l'OFGL (`euros_par_habitant`) ;
  - dates par pipeline/reproductible.py ; tris explicites : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
GEO = SITE / "local" / "geo"
TAUX = SITE / "local" / "taux"
REVENUS = SITE / "revenus_communes" / "communes"
INVESTISSEMENT = SITE / "investissement_communes" / "communes"
TERRITOIRES = SITE / "territoires"
REI_SERIES = SITE / "fiscalite_locale_series" / "communes"
SOLIDARITES = SITE / "solidarites_departements" / "comptes.json"
ASSURANCE_MALADIE = SITE / "assurance_maladie_territoires" / "departements.json"
SORTIE_DEFAUT = SITE / "typologies"
MAX_OCTETS = 1_000_000
COG = 2026

ID_GRILLE = "typologies_grille_densite"
ID_AAV = "typologies_aav2020"
ID_OFGL = "typologies_ofgl_communes"
ID_PASSAGE = "revenus_communes_passage_cog"
F_GRILLE = LAKE / "typologies" / f"{ID_GRILLE}.xlsx"
F_AAV = LAKE / "typologies" / f"{ID_AAV}.zip"
F_OFGL = LAKE / "typologies" / f"{ID_OFGL}.csv"
F_PASSAGE = LAKE / "revenus_communes" / f"{ID_PASSAGE}.zip"

N_MIN = 10            # effectif minimal d'une case ou d'une bande pour publier des quantiles
N_BANDES = 10         # tranches de la grandeur en abscisse (déciles nationaux, mêmes bornes dans toutes les cases)
N_BANDES_DEP = 4      # départements : quatre tranches (quartiles nationaux), une centaine de points seulement
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
STATUT_TRACE = "tracé"
STATUT_CALCULE = "calculé par le site"

URL_GRILLE = "https://www.insee.fr/fr/information/8571524"
URL_AAV = "https://www.insee.fr/fr/information/4803954"
URL_OFGL = "https://www.data.gouv.fr/datasets/comptes-consolides-des-communes-2017-2024/"
URL_OFGL_API = "https://data.ofgl.fr/explore/dataset/ofgl-base-communes-consolidee/"

AVERTISSEMENT = ("Mettre deux chiffres côte à côte ne dit pas que l'un explique l'autre ; ce sont des moyennes de "
                 "communes, pas d'habitants.")
AVERTISSEMENT_DEP = ("Mettre deux chiffres côte à côte ne dit pas que l'un explique l'autre ; ce sont des moyennes de "
                     "départements, pas d'habitants.")

# --- Variables ----------------------------------------------------------------------------------------------------

AGREGATS = {  # libellé exact de l'OFGL -> préfixe de variable
    "Dépenses totales": "depenses_totales",
    "Encours de dette": "encours_dette",
    "Dotation globale de fonctionnement": "dgf",
    "Impôts locaux": "impots_locaux",
    "Dépenses d'équipement": "depenses_equipement",
}
ANNEES_OFGL = (2023, 2024)
DEFINITIONS_OFGL = {
    "depenses_totales": "dépenses totales de la commune (budget principal et budgets annexes consolidés, flux "
                        "internes neutralisés, remboursements d'emprunts compris selon la définition de l'OFGL)",
    "encours_dette": "encours de dette au 31 décembre (budget principal et budgets annexes consolidés)",
    "dgf": "dotation globale de fonctionnement reçue de l'État, telle qu'inscrite aux comptes de la commune",
    "impots_locaux": "impôts locaux perçus par la commune (taxes foncières, taxe d'habitation sur les résidences "
                     "secondaires et autres impôts directs, selon la définition de l'OFGL)",
    "depenses_equipement": "dépenses d'équipement (investissements directs de la commune)",
}
LIBELLES_OFGL = {
    "depenses_totales": "dépenses totales par habitant",
    "encours_dette": "dette (encours) par habitant",
    "dgf": "dotation globale de fonctionnement de l'État par habitant",
    "impots_locaux": "impôts locaux par habitant",
    "depenses_equipement": "dépenses d'équipement par habitant",
}


def _variables() -> dict:
    v = {}
    for nom, cle in AGREGATS.items():
        for a in ANNEES_OFGL:
            v[f"{cle}_hab_{a}"] = {
                "libelle": LIBELLES_OFGL[cle], "annee": a, "unite": "euros par habitant",
                "definition": DEFINITIONS_OFGL[cle] + ", divisé par la population totale de l'exercice (OFGL)",
                "agregat_ofgl": nom, "statut": STATUT_TRACE, "source": "ofgl",
                "methode": "valeur `euros_par_habitant` publiée par l'OFGL (montant de l'exercice divisé par la "
                           "population totale de l'exercice), reprise telle quelle",
            }
    v["niveau_vie_median_2023"] = {
        "libelle": "niveau de vie médian des habitants", "annee": 2023, "unite": "euros par an",
        "definition": "médiane du revenu disponible par unité de consommation des personnes des ménages fiscaux de la "
                      "commune (Insee, Filosofi 2)",
        "statut": STATUT_TRACE, "source": "filosofi_2023",
        "methode": "valeur publiée par l'Insee, reprise telle quelle ; null si l'Insee ne la publie pas (secret "
                   "statistique, champ)",
    }
    v["rfr_moyen_foyer_2023"] = {
        "libelle": "revenu fiscal de référence moyen par foyer fiscal", "annee": 2023, "unite": "euros par foyer",
        "definition": "revenu fiscal de référence de l'ensemble des foyers fiscaux de la commune divisé par leur "
                      "nombre (DGFiP, IRCOM, revenus 2023)",
        "statut": STATUT_CALCULE, "source": "ircom_2023",
        "methode": "rfr_eur / foyers de la même ligne IRCOM (revenus 2023, même commune), arrondi à l'euro ; null "
                   "si l'un des deux termes est null",
    }
    v["impot_revenu_moyen_foyer_2023"] = {
        "libelle": "impôt sur le revenu net moyen par foyer fiscal", "annee": 2023, "unite": "euros par foyer",
        "definition": "impôt sur le revenu net de l'ensemble des foyers fiscaux de la commune divisé par leur nombre "
                      "(DGFiP, IRCOM, revenus 2023 ; un impôt net peut être négatif : crédits d'impôt restitués)",
        "statut": STATUT_CALCULE, "source": "ircom_2023",
        "methode": "impot_net_eur / foyers de la même ligne IRCOM (revenus 2023, même commune), arrondi à l'euro ; "
                   "null si l'un des deux termes est null",
    }
    v["equipement_paye_hab_2023"] = {
        "libelle": "investissement payé par la commune par habitant", "annee": 2023, "unite": "euros par habitant",
        "definition": "dépenses d'équipement réellement mandatées par la commune en 2023 (comptes 20 hors 204, 21 et "
                      "23, budget principal, balance comptable de la DGFiP), divisées par la population totale de "
                      "l'exercice 2023 publiée par l'OFGL",
        "statut": STATUT_CALCULE, "source": "investissement",
        "methode": "équipement 2023 de site/data/investissement_communes (somme publiée par l'axe) / population totale "
                   "2023 de l'OFGL pour la même commune, arrondi à 0,1 € ; null si la balance 2023 n'est pas publiée "
                   "sous le SIREN de la commune, si la population manque ou si la commune a changé de territoire",
    }
    v["dotations_etat_hab_2024"] = {
        "libelle": "subventions d'investissement attribuées par l'État à la commune, par habitant", "annee": 2024,
        "unite": "euros par habitant",
        "definition": "somme des subventions attribuées à la commune elle-même au titre de la DETR, de la DSIL, de la "
                      "DPV et de la DSID pour l'exercice 2024 (listes de la DGCL ; projets de l'intercommunalité non "
                      "compris), divisée par la population totale 2024 publiée par l'OFGL ; 0 si aucun projet de la "
                      "commune n'est publié pour 2024 ; montant attribué, pas un montant payé",
        "statut": STATUT_CALCULE, "source": "dotations",
        "methode": "somme des subventions des projets de l'exercice 2024 du bénéficiaire de type commune portant ce "
                   "code Insee (site/data/territoires, même liste, même exercice) / population totale 2024 de l'OFGL, "
                   "arrondi à 0,1 € ; aucun projet de 2024 n'est publié sans bénéficiaire nommé (contrôle "
                   "`dotations_non_nommees_2024`)",
    }
    v["produit_fb_commune_hab_2023"] = {
        "libelle": "foncier bâti émis au profit de la commune, par habitant", "annee": 2023,
        "unite": "euros par habitant",
        "definition": "montant de taxe foncière sur les propriétés bâties émis en 2023 au profit de la commune sur son "
                      "territoire (DGFiP, REI, montant réel, avant dégrèvements pris en charge par l'État), divisé "
                      "par la population totale 2023 publiée par l'OFGL",
        "statut": STATUT_CALCULE, "source": "rei_series",
        "methode": "produit tfb_commune 2023 de site/data/fiscalite_locale_series / population totale 2023 de l'OFGL "
                   "pour la même commune, arrondi à 0,1 € ; null si l'un des deux manque ou si la commune a changé de "
                   "territoire",
    }
    for a in (2023, 2024):
        v[f"taux_fb_commune_{a}"] = {
            "libelle": "taux communal voté de taxe foncière sur les propriétés bâties", "annee": a, "unite": "%",
            "definition": "taux voté par le conseil municipal pour la part communale du foncier bâti (DGFiP, REI)",
            "statut": STATUT_TRACE, "source": "taux",
            "methode": "taux publié par la DGFiP pour l'exercice, repris tel quel",
        }
    return v


VARIABLES = _variables()

# --- Croisements prédéfinis (liste fermée : l'écran n'en affiche aucun autre) ------------------------------------

CROISEMENTS = [
    {"id": "depenses_niveau_vie_2023", "annee": 2023, "x": "niveau_vie_median_2023", "y": "depenses_totales_hab_2023",
     "titre": "Dépenses de la commune par habitant et niveau de vie médian des habitants, 2023"},
    {"id": "dette_niveau_vie_2023", "annee": 2023, "x": "niveau_vie_median_2023", "y": "encours_dette_hab_2023",
     "titre": "Dette de la commune par habitant et niveau de vie médian des habitants, 2023"},
    {"id": "dgf_niveau_vie_2023", "annee": 2023, "x": "niveau_vie_median_2023", "y": "dgf_hab_2023",
     "titre": "Dotation globale de fonctionnement de l'État par habitant et niveau de vie médian, 2023"},
    {"id": "taux_fb_niveau_vie_2023", "annee": 2023, "x": "niveau_vie_median_2023", "y": "taux_fb_commune_2023",
     "titre": "Taux communal de foncier bâti et niveau de vie médian des habitants, 2023"},
    {"id": "impots_locaux_rfr_2023", "annee": 2023, "x": "rfr_moyen_foyer_2023", "y": "impots_locaux_hab_2023",
     "titre": "Impôts locaux par habitant et revenu fiscal de référence moyen par foyer, 2023"},
    {"id": "depenses_taux_fb_2024", "annee": 2024, "x": "taux_fb_commune_2024", "y": "depenses_totales_hab_2024",
     "titre": "Dépenses de la commune par habitant et taux communal de foncier bâti, 2024"},
    {"id": "equipement_dette_2024", "annee": 2024, "x": "encours_dette_hab_2024", "y": "depenses_equipement_hab_2024",
     "titre": "Dépenses d'équipement par habitant et dette par habitant, 2024"},
    {"id": "dgf_depenses_2024", "annee": 2024, "x": "dgf_hab_2024", "y": "depenses_totales_hab_2024",
     "titre": "Dotation globale de fonctionnement par habitant et dépenses par habitant, 2024"},
    {"id": "equipement_paye_niveau_vie_2023", "annee": 2023, "x": "niveau_vie_median_2023",
     "y": "equipement_paye_hab_2023",
     "titre": "Investissement payé par la commune par habitant et niveau de vie médian des habitants, 2023"},
    {"id": "dotations_etat_equipement_2024", "annee": 2024, "x": "depenses_equipement_hab_2024",
     "y": "dotations_etat_hab_2024",
     "titre": "Subventions d'investissement attribuées par l'État par habitant et dépenses d'équipement par "
              "habitant, 2024"},
    {"id": "impot_revenu_impots_locaux_2023", "annee": 2023, "x": "impot_revenu_moyen_foyer_2023",
     "y": "impots_locaux_hab_2023",
     "titre": "Impôts locaux par habitant et impôt sur le revenu moyen par foyer, 2023"},
    {"id": "produit_fb_niveau_vie_2023", "annee": 2023, "x": "niveau_vie_median_2023",
     "y": "produit_fb_commune_hab_2023",
     "titre": "Foncier bâti émis au profit de la commune par habitant et niveau de vie médian, 2023"},
]

# Croisements entre départements (même liste fermée ; points : départements, facette : tranche de population).
VARIABLES_DEP = {
    "aide_sociale_nette_hab_2024": {
        "libelle": "dépenses nettes d'aide sociale du département par habitant", "annee": 2024,
        "unite": "euros par habitant", "niveau": "departement",
        "definition": "dépenses nettes d'aide sociale de la collectivité départementale (personnes âgées, personnes "
                      "handicapées, enfance, insertion), par habitant, telles que publiées par la DREES (enquête Aide "
                      "sociale)",
        "statut": STATUT_TRACE, "source": "drees_aide_sociale",
        "methode": "valeur eur_hab publiée par la DREES pour 2024, reprise telle quelle (site/data/territoires, "
                   "aide_sociale) ; null si non publiée",
    },
    "prescriptions_hab_2024": {
        "libelle": "prescriptions des médecins libéraux du département par habitant", "annee": 2024,
        "unite": "euros par habitant", "niveau": "departement",
        "definition": "montant des prescriptions des médecins libéraux exerçant dans le département (médicaments, "
                      "arrêts de travail indemnisés, analyses, soins, transports ; Cnam, SNDS), divisé par la "
                      "population totale 2024 de la collectivité départementale publiée par l'OFGL",
        "statut": STATUT_CALCULE, "source": "cnam_prescriptions",
        "methode": "prescriptions 2024 (site/data/assurance_maladie_territoires) / population totale 2024 de l'OFGL "
                   "(site/data/solidarites_departements), même département, arrondi à 0,1 € ; null si le territoire "
                   "du département ne correspond pas à une seule collectivité départementale publiée par l'OFGL "
                   "(Rhône et Métropole de Lyon, Corse, Alsace)",
    },
}
CROISEMENTS_DEP = [
    {"id": "aide_sociale_prescriptions_2024", "annee": 2024, "niveau": "departement",
     "x": "aide_sociale_nette_hab_2024", "y": "prescriptions_hab_2024",
     "titre": "Dépenses d'assurance maladie (prescriptions des médecins libéraux) par habitant et dépenses nettes "
              "d'aide sociale du département par habitant, 2024"},
]
PERIMETRE_DEP = ("le département : collectivité départementale pour l'aide sociale, territoire du département pour les "
                 "prescriptions ; un département dont le territoire ne correspond pas à une seule collectivité "
                 "départementale publiée par l'OFGL (Rhône et Métropole de Lyon, Corse, Alsace) n'est pas croisé "
                 "(motif `perimetre`)")
STRATES_DEP = {  # tranches de population totale fixées par le site pour les départements (aucune strate officielle lue)
    "1": (0, 249999), "2": (250000, 499999), "3": (500000, 999999), "4": (1000000, None),
}


def libelle_strate_dep(code: str) -> str:
    de, a = STRATES_DEP[code]
    if de == 0:
        return f"moins de {a + 1:,} habitants".replace(",", " ")
    if a is None:
        return f"{de:,} habitants ou plus".replace(",", " ")
    return f"{de:,} à {a:,} habitants".replace(",", " ")

PERIMETRE = ("la commune, dans ses limites de l'année des données ; une commune dont le territoire a changé entre "
             "cette année et le code officiel géographique 2026 (fusion, scission) n'est pas croisée (motif "
             "`perimetre`)")

# --- Facettes ------------------------------------------------------------------------------------------------------

CATEGORIES_AAV = {  # modalités de CATEAAV2020 (Insee, documentation du zonage en aires d'attraction des villes 2020)
    "11": "commune-centre", "12": "autre commune du pôle principal", "13": "commune d'un pôle secondaire",
    "20": "commune de la couronne", "30": "commune hors attraction des villes",
}
TRANCHES_AAV = {  # TAAV2017 (Insee)
    "0": "commune hors attraction des villes", "1": "aire de moins de 50 000 habitants",
    "2": "aire de 50 000 à moins de 200 000 habitants", "3": "aire de 200 000 à moins de 700 000 habitants",
    "4": "aire de 700 000 habitants ou plus (hors Paris)", "5": "aire de Paris",
}
STRATES_OFGL = {  # strates de population de l'OFGL ; bornes contrôlées à chaque production sur `ptot_n`
    "0": (0, 99), "1": (100, 199), "2": (200, 499), "3": (500, 1999), "4": (2000, 3499), "5": (3500, 4999),
    "6": (5000, 9999), "7": (10000, 19999), "8": (20000, 49999), "9": (50000, 99999), "10": (100000, None),
}


def libelle_strate(code: str) -> str:
    de, a = STRATES_OFGL[code]
    if de == 0:
        return f"moins de {a + 1} habitants"
    if a is None:
        return f"{de:,} habitants ou plus".replace(",", " ")
    return f"{de:,} à {a:,} habitants".replace(",", " ")


# --- Sources et recherche publique ----------------------------------------------------------------------------------

SOURCES = {
    "grille": {"id_catalogue": ID_GRILLE, "producteur": "Insee", "licence": "Licence Ouverte 2.0", "page": URL_GRILLE,
               "titre": "Insee, « La grille de densité 2025 » : niveau de densité de chaque commune (7 niveaux, 3 "
                        "niveaux, rural croisé avec les aires d'attraction), géographie au 1er janvier 2026",
               "millesime": "grille 2025 (recensement 2021), géographie 2026",
               "verdict": "réutilisable tel quel (feuille « Maille communale »)"},
    "aav": {"id_catalogue": ID_AAV, "producteur": "Insee", "licence": "Licence Ouverte 2.0", "page": URL_AAV,
            "titre": "Insee, « Base des aires d'attraction des villes 2020 » au 1er janvier 2026 : aire, catégorie de "
                     "la commune dans l'aire, tranche de taille de l'aire",
            "millesime": "zonage 2020, géographie 2026",
            "verdict": "réutilisable tel quel (feuilles « Composition_communale » et « AAV2020 »)"},
    "ofgl": {"id_catalogue": ID_OFGL, "producteur": "Observatoire des finances et de la gestion publique locales (OFGL)",
             "licence": "Licence Ouverte 2.0", "page": URL_OFGL,
             "titre": "OFGL, « Comptes consolidés des communes 2018-2025 » (data.ofgl.fr ofgl-base-communes-consolidee) : "
                      "exercices 2023 et 2024, cinq agrégats, montant, population totale, euros par habitant, strate de "
                      "population",
             "millesime": "exercices 2023 et 2024",
             "verdict": "réutilisable tel quel (export filtré de l'API du portail de l'OFGL, même jeu que data.gouv.fr)"},
    "passage": {"id_catalogue": ID_PASSAGE, "producteur": "Insee", "licence": "Licence Ouverte 2.0",
                "page": "https://www.insee.fr/fr/information/7671867",
                "titre": "Insee, table de passage annuelle des communes 2026 (entrée du catalogue de "
                         "pipeline/revenus_communes.py, lue sans copie)",
                "millesime": "géographies 2003 à 2026", "verdict": "réutilisable tel quel"},
    "filosofi_2023": {"producteur": "Insee (via pipeline/revenus_communes.py)", "licence": "Licence Ouverte 2.0",
                      "page": "site/data/revenus_communes/index.json",
                      "titre": "Insee, Filosofi 2 2023 : niveau de vie médian par commune (géographie 2026)",
                      "lecture": "site/data/revenus_communes (pipeline/revenus_communes.py)", "millesime": "revenus 2023",
                      "verdict": "réutilisable tel quel"},
    "ircom_2023": {"producteur": "DGFiP (via pipeline/revenus_communes.py)", "licence": "Licence Ouverte 2.0",
                   "page": "site/data/revenus_communes/index.json",
                   "titre": "DGFiP, impôt sur le revenu par collectivité territoriale (IRCOM), revenus 2023, communes en vigueur en 2026",
                   "lecture": "site/data/revenus_communes (pipeline/revenus_communes.py)", "millesime": "revenus 2023",
                   "verdict": "réutilisable tel quel"},
    "taux": {"producteur": "DGFiP (via pipeline/local.py)", "licence": "Licence Ouverte 2.0",
             "page": "site/data/local/index.json",
             "titre": "DGFiP, recensement des éléments d'imposition (REI) : taux votés de foncier bâti par commune, exercices 2023 et 2024",
             "lecture": "site/data/local/taux (pipeline/local.py)", "millesime": "exercices 2023 et 2024",
             "verdict": "réutilisable tel quel"},
    "investissement": {"producteur": "DGFiP (via pipeline/investissement_communes.py)", "licence": "Licence Ouverte 2.0",
                       "page": "site/data/investissement_communes/index.json",
                       "titre": "DGFiP, balances comptables des communes 2023 : dépenses d'équipement mandatées (budget "
                                "principal), site/data/investissement_communes",
                       "millesime": "exercice 2023", "verdict": "réutilisable tel quel"},
    "dotations": {"producteur": "DGCL (via pipeline/territoires.py)", "licence": "Licence Ouverte 2.0",
                  "page": "site/data/projets_subventionnes/index.json",
                  "titre": "DGCL, projets financés par les dotations de soutien à l'investissement (DETR, DSIL, DPV, "
                           "DSID), exercice 2024, site/data/territoires (relié par site/data/projets_subventionnes)",
                  "millesime": "exercice 2024", "verdict": "réutilisable tel quel"},
    "rei_series": {"producteur": "DGFiP (via pipeline/fiscalite_locale_series.py)", "licence": "Licence Ouverte 2.0",
                   "page": "site/data/fiscalite_locale_series/index.json",
                   "titre": "DGFiP, recensement des éléments d'imposition (REI) 2023 : montant de foncier bâti émis au "
                            "profit de la commune, site/data/fiscalite_locale_series",
                   "millesime": "REI 2023", "verdict": "réutilisable tel quel"},
    "drees_aide_sociale": {"producteur": "DREES (via pipeline/territoires.py)", "licence": "Licence Ouverte 2.0",
                           "page": "site/data/territoires/index.json",
                           "titre": "DREES, enquête Aide sociale : dépenses nettes d'aide sociale des départements par "
                                    "habitant, 2024, site/data/territoires (aide_sociale)",
                           "millesime": "2024", "verdict": "réutilisable tel quel"},
    "cnam_prescriptions": {"producteur": "Cnam (via pipeline/assurance_maladie_territoires.py) ; OFGL (via "
                                         "pipeline/solidarites_departements.py)", "licence": "Licence Ouverte 2.0",
                           "page": "site/data/assurance_maladie_territoires/index.json",
                           "titre": "Cnam, prescriptions des médecins libéraux par département, 2024 ; OFGL, population "
                                    "totale 2024 des départements",
                           "millesime": "2024", "verdict": "réutilisable tel quel"},
    "geo": {"producteur": "pipeline/local.py", "licence": "Licence Ouverte 2.0", "page": "site/data/local/index.json",
            "titre": "site/data/local/geo : communes en vigueur, noms officiels, population municipale (geo.api.gouv.fr)",
            "millesime": "code officiel géographique en vigueur", "verdict": "réutilisable tel quel"},
}

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "requetes": ["Insee grille communale de densité 2025 fichier communal", "Insee aires d'attraction des villes 2020 "
                 "composition communale 2026", "OFGL moyennes par strate de population communes",
                 "data.ofgl.fr catalogue des jeux", "data.gouv.fr comptes consolidés des communes ressources",
                 "github grille densité insee commune", "github uPlot", "pynsee typologies communes"],
    "trouvailles": [
        {"nom": "Insee, grille communale de densité 2025 (fichier_diffusion_2026.xlsx)", "url": URL_GRILLE,
         "licence": "Licence Ouverte 2.0", "derniere_modification": "2026-05-15", "verdict": "réutilisable tel quel",
         "usage": "niveau de densité de chaque commune en vigueur"},
        {"nom": "Insee, aires d'attraction des villes 2020 au 1er janvier 2026", "url": URL_AAV,
         "licence": "Licence Ouverte 2.0", "derniere_modification": "2026-03-19", "verdict": "réutilisable tel quel",
         "usage": "catégorie de la commune dans l'aire, tranche de taille de l'aire"},
        {"nom": "OFGL, comptes consolidés des communes (data.gouv.fr et data.ofgl.fr)", "url": URL_OFGL,
         "licence": "Licence Ouverte 2.0", "derniere_modification": "2026-07-28", "verdict": "réutilisable tel quel",
         "usage": "montants par habitant publiés et strate de population (champ `tranche_population`) ; le jeu ne "
                  "contient aucune moyenne par strate : les rapports par strate sont calculés par le site"},
        {"nom": "OFGL, catalogue de data.ofgl.fr (96 jeux consultés le 2026-11-18)",
         "url": "https://data.ofgl.fr/explore/", "licence": "Licence Ouverte 2.0",
         "derniere_modification": "2026-11-03", "verdict": "inspiration seulement",
         "usage": "aucun jeu de moyennes par strate publié ; les tableaux de bord de l'OFGL ne sont pas des données "
                  "ouvertes téléchargeables"},
        {"nom": "pipeline/revenus_communes.py, pipeline/local.py (ce dépôt)", "url": "pipeline/revenus_communes.py",
         "licence": "MIT", "derniere_modification": "dépôt courant", "verdict": "réutilisable tel quel",
         "usage": "niveau de vie médian, revenu fiscal de référence, taux, communes en vigueur (lecture seule)"},
        {"nom": "InseeFrLab/pynsee", "url": "https://github.com/InseeFrLab/pynsee", "licence": "MIT",
         "derniere_modification": "2026-10-30", "verdict": "inspiration seulement",
         "usage": "non utilisé : les deux fichiers de l'Insee sont lus directement, sans dépendance au build"},
        {"nom": "leeoniya/uPlot", "url": "https://github.com/leeoniya/uPlot", "licence": "MIT",
         "derniere_modification": "2026-09", "verdict": "inspiration seulement",
         "usage": "non retenu : les petits multiples en SVG suffisent, sans nuage de points interactif ni dépendance "
                  "ajoutée au site"},
    ],
}

NON_REPRIS = [
    {"objet": "grille de densité à la maille intercommunalité, bassin de vie et département",
     "motif": "publiée dans le même fichier ; l'écran repère une commune ou les communes d'un département"},
    {"objet": "rural périurbain (grille croisée avec les aires d'attraction, colonne DENS_AAV)",
     "motif": "repris par commune (`densite_aav`) mais pas en facette : les catégories de l'aire d'attraction "
              "forment déjà une facette"},
    {"objet": "comptes 2025",
     "motif": "comptes de 97 communes non encore disponibles (OFGL, juillet 2026) ; aucune grandeur de revenu 2025 "
              "à croiser"},
    {"objet": "croisement de grandeurs d'années différentes ou de périmètres différents (commune et intercommunalité)",
     "motif": "règle 13 : non affiché"},
]

LIMITES = [
    "Chaque point est une commune : une commune de 80 habitants compte autant qu'une ville de 100 000 habitants dans les "
    "quantiles et les moyennes de communes.",
    "Une relation visible dans l'ensemble des communes peut s'inverser à l'intérieur de chaque niveau de densité ou de "
    "chaque strate (paradoxe de Simpson) : la vue d'ensemble est toujours montrée à côté de la vue par case.",
    "Les montants par habitant des petites communes varient fortement d'une année à l'autre (un équipement, un "
    "emprunt) : la bande de la case dit plus que le point d'une commune.",
    "Les compétences exercées par l'intercommunalité à la place de la commune ne sont pas dans les comptes de la "
    "commune : deux communes de même strate n'exercent pas forcément les mêmes compétences.",
    "Niveau de vie (Insee, ménages, revenu disponible) et revenu fiscal de référence (DGFiP, foyers fiscaux) ne "
    "mesurent pas la même chose ; ils ne sont jamais comparés entre eux.",
    "Investissement payé : budget principal de la commune (balance de la DGFiP) ; dépenses d'équipement de l'OFGL : "
    "budgets principal et annexes consolidés. Les deux ne sont jamais comparés entre eux.",
    "Subventions d'investissement de l'État : montants attribués à la commune elle-même (DETR, DSIL, DPV, DSID), pas "
    "les montants payés, ni ceux attribués à son intercommunalité, ni le Fonds vert (montant engagé, autre "
    "dispositif) ; une commune sans projet publié en 2024 compte pour 0.",
    "Départements : la dépense d'aide sociale est celle de la collectivité départementale ; les prescriptions sont "
    "celles des médecins libéraux qui exercent dans le département, quel que soit le lieu de vie du patient.",
]

METHODE = {
    "perimetre": PERIMETRE,
    "codes": "comptes de l'OFGL : ligne retenue si le code de la collectivité égale le code commune 2025 et si elle "
             "est seule pour ce code et cet exercice, puis si la commune 2025 est la même commune en 2026 (table de "
             "passage de l'Insee) ; taux de foncier bâti : code de l'exercice, retenu si la commune est la même en "
             "2026 ; Filosofi 2023 et IRCOM sont déjà en géographie 2026 (pipeline/revenus_communes.py)",
    "quantiles": "quantiles par interpolation linéaire entre valeurs triées (p = 10, 25, 50, 75, 90 %), calculés par "
                 "le site sur les communes de la case qui ont les deux valeurs ; publiés à partir de "
                 f"{N_MIN} communes",
    "bandes": f"abscisse découpée en {N_BANDES} tranches aux déciles nationaux de la grandeur en abscisse (mêmes "
              "bornes dans toutes les cases) ; dans chaque tranche, quantiles de la grandeur en ordonnée si la "
              f"tranche compte au moins {N_MIN} communes de la case",
    "moyenne_communes": "moyenne simple des valeurs des communes de la case (chaque commune compte pour un), calculée "
                        "par le site",
    "rapport_strate": "pour chaque strate de l'OFGL et chaque agrégat : somme des montants des communes divisée par la "
                      "somme de leurs populations totales, même exercice, mêmes communes (calcul du site, l'OFGL ne "
                      "publiant pas de moyenne par strate dans ce jeu)",
    "axes": "bornes d'affichage communes à toutes les cases : 1er et 99e centiles nationaux de chaque grandeur ; une "
            "commune au-delà est dessinée au bord avec une marque",
    "quantiles_dep": "départements : quantiles par interpolation linéaire entre valeurs triées (p = 10, 25, 50, 75, "
                     f"90 %), calculés par le site sur les départements de la case qui ont les deux valeurs ; publiés à "
                     f"partir de {N_MIN} départements",
    "bandes_dep": f"départements : abscisse découpée en {N_BANDES_DEP} tranches aux quartiles nationaux (mêmes bornes "
                  "dans toutes les cases) ; dans chaque tranche, quantiles de la grandeur en ordonnée si la tranche "
                  f"compte au moins {N_MIN} départements de la case",
    "axes_dep": "départements : bornes d'affichage communes à toutes les cases, valeurs nationales la plus basse et "
                "la plus haute ; chaque département croisé est publié avec ses deux valeurs (`territoires`)",
    "par_habitant": "montant de l'année divisé par la population totale du même exercice publiée par l'OFGL, même "
                    "commune ou même département, calculé par le site (règle 13 : même année, même périmètre)",
}


# --- Lecture des sources --------------------------------------------------------------------------------------------

def nombre(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def code5(v) -> str:
    s = str(v).strip()
    return s.zfill(5) if s.isdigit() else s


def dep_de(code: str) -> str:
    return code[:3] if code.startswith("97") else code[:2]


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def feuilles_xlsx(octets: bytes) -> dict[str, list[list]]:
    """Lecture minimale d'un classeur (feuilles -> lignes de valeurs) sans feuille de styles : le classeur des aires
    d'attraction porte une feuille de styles que openpyxl refuse."""
    x = zipfile.ZipFile(io.BytesIO(octets))
    ss = []
    if "xl/sharedStrings.xml" in x.namelist():
        ss = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t"))
              for si in ET.fromstring(x.read("xl/sharedStrings.xml"))]
    wb = ET.fromstring(x.read("xl/workbook.xml"))
    rels = ET.fromstring(x.read("xl/_rels/workbook.xml.rels"))
    cible = {r.get("Id"): r.get("Target") for r in rels}
    out = {}
    for s in wb.find("m:sheets", NS):
        rid = s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        chemin = "xl/" + cible[rid].lstrip("/").removeprefix("xl/")
        lignes = []
        for r in ET.fromstring(x.read(chemin)).find("m:sheetData", NS):
            ligne = {}
            for c in r:
                ref = re.match(r"([A-Z]+)", c.get("r")).group(1)
                col = 0
                for ch in ref:
                    col = col * 26 + ord(ch) - 64
                v = c.find("m:v", NS)
                val = v.text if v is not None else None
                if c.get("t") == "s" and val is not None:
                    val = ss[int(val)]
                elif c.get("t") == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
                ligne[col - 1] = val
            lignes.append([ligne.get(i) for i in range(max(ligne) + 1)] if ligne else [])
        out[s.get("name")] = lignes
    return out


def table(lignes: list[list], premiere: str) -> list[dict]:
    """Lignes d'une feuille à partir de l'en-tête de codes dont la première cellule vaut `premiere`."""
    for i, r in enumerate(lignes):
        if r and r[0] == premiere:
            ent = [str(h) if h is not None else "" for h in r]
            return [dict(zip(ent, l)) for l in lignes[i + 1:] if l and l[0]]
    raise ValueError(f"en-tête {premiere} introuvable")


def lire_grille(chemin: Path = F_GRILLE) -> tuple[dict, dict, dict]:
    if not chemin.exists():
        raise SystemExit(f"{chemin} absent : lancer `python pipeline/typologies.py collecter`")
    f = feuilles_xlsx(chemin.read_bytes())
    nom = next(n for n in f if "communale" in n.lower())
    out, lib7, libaav = {}, {}, {}
    for r in table(f[nom], "CODGEO"):
        c = code5(r["CODGEO"])
        d7, d3, da = (str(int(float(r[k]))) if r.get(k) not in (None, "") else None for k in ("DENS7", "DENS", "DENS_AAV"))
        out[c] = {"densite": d7, "densite3": d3, "densite_aav": da}
        if d7:
            lib7[d7] = str(r["LIBDENS7"]).strip()
        if da:
            libaav[da] = str(r["LIBDENS_AAV"]).strip()
        if d3:
            libaav.setdefault("_3_" + d3, str(r["LIBDENS"]).strip())
    lib3 = {k[3:]: v for k, v in libaav.items() if k.startswith("_3_")}
    libaav = {k: v for k, v in libaav.items() if not k.startswith("_3_")}
    return out, {"7": dict(sorted(lib7.items(), key=lambda kv: int(kv[0]))),
                 "3": dict(sorted(lib3.items(), key=lambda kv: int(kv[0]))),
                 "aav": dict(sorted(libaav.items(), key=lambda kv: int(kv[0])))}, {"fichier": nom}


def lire_aav(chemin: Path = F_AAV) -> dict:
    if not chemin.exists():
        raise SystemExit(f"{chemin} absent : lancer `python pipeline/typologies.py collecter`")
    z = zipfile.ZipFile(chemin)
    nom = next(n for n in z.namelist() if n.lower().endswith(".xlsx"))
    f = feuilles_xlsx(z.read(nom))
    tranches = {str(r["AAV2020"]): str(r["TAAV2017"]) for r in table(f["AAV2020"], "AAV2020")}
    out = {}
    for r in table(f["Composition_communale"], "CODGEO"):
        aav = str(r["AAV2020"])
        out[code5(r["CODGEO"])] = {"aav": str(r["CATEAAV2020"]), "aav_tranche": tranches.get(aav)}
    return out


class Passage:
    """Table de passage annuelle : pour une année, codes de cette année qui forment chaque commune 2026, et
    communes 2026 couvertes par chaque code de cette année."""

    def __init__(self, depuis: dict, vers: dict):
        self.depuis, self.vers = depuis, vers

    def stable(self, annee: int, code: str) -> bool:
        """La commune de l'année porte le même code et le même territoire en 2026."""
        if annee == COG:
            return True
        return self.depuis.get(annee, {}).get(code) == {code} and self.vers.get(annee, {}).get(code) == {code}


ARRONDISSEMENTS = {"75056", "13055", "69123"}


def lire_passage(annees=(2023, 2024, 2025), chemin: Path = F_PASSAGE) -> Passage:
    if not chemin.exists():
        raise SystemExit(f"{chemin} absent : lancer `python pipeline/typologies.py collecter`")
    import openpyxl
    z = zipfile.ZipFile(chemin)
    nom = next(n for n in z.namelist() if n.lower().endswith(".xlsx"))
    wb = openpyxl.load_workbook(io.BytesIO(z.read(nom)), read_only=True)
    ws = wb["COM"] if "COM" in wb.sheetnames else wb.worksheets[0]
    ws.reset_dimensions()
    lignes = ws.iter_rows(values_only=True)
    ent = None
    for r in lignes:
        if r and r[0] == "NIVGEO":
            ent = [str(h) if h is not None else "" for h in r]
            break
    if not ent or f"CODGEO_{COG}" not in ent:
        raise ValueError(f"table de passage : colonne CODGEO_{COG} introuvable")
    k = ent.index(f"CODGEO_{COG}")
    ks = {a: ent.index(f"CODGEO_{a}") for a in annees}
    depuis = {a: defaultdict(set) for a in annees}
    vers = {a: defaultdict(set) for a in annees}
    for r in lignes:
        if not r or r[0] not in ("COM", "ARM"):
            continue
        c26 = code5(r[k]) if r[k] else ""
        for a, j in ks.items():
            ca = code5(r[j]) if r[j] else ""
            if r[0] == "ARM":   # arrondissements : rattachés à leur commune (Paris, Lyon, Marseille), sans changement
                continue
            if c26 and ca:
                depuis[a][c26].add(ca)
                vers[a][ca].add(c26)
    for a in annees:
        for c in ARRONDISSEMENTS:
            depuis[a].setdefault(c, {c})
            vers[a].setdefault(c, {c})
    return Passage({a: dict(d) for a, d in depuis.items()}, {a: dict(d) for a, d in vers.items()})


def lire_ofgl(chemin: Path = F_OFGL) -> tuple[dict, dict, dict]:
    """(valeurs[(annee, code2025)][prefixe] = (euros_par_habitant, montant, ptot), strate[code2025], controles)."""
    if not chemin.exists():
        raise SystemExit(f"{chemin} absent : lancer `python pipeline/typologies.py collecter`")
    lignes = defaultdict(list)
    strate, bornes = {}, defaultdict(lambda: [None, None])
    ecarts_hab, lignes_lues = 0, 0
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            lignes_lues += 1
            ag = AGREGATS.get(r["agregat"])
            if not ag:
                raise ValueError(f"agrégat inattendu dans l'export de l'OFGL : {r['agregat']}")
            a, cc, ci = int(str(r["exer"])[:4]), code5(r["com_code"]), code5(r["insee"])
            lignes[(a, cc, ag)].append((ci, nombre(r["euros_par_habitant"]), nombre(r["montant"]), nombre(r["ptot"])))
            t = str(r["tranche_population"]).strip()
            if t:
                strate.setdefault(cc, t)
                pn = nombre(r.get("ptot_n"))
                if pn is not None:
                    b = bornes[t]
                    b[0] = pn if b[0] is None else min(b[0], pn)
                    b[1] = pn if b[1] is None else max(b[1], pn)
            eh, mo, pt = nombre(r["euros_par_habitant"]), nombre(r["montant"]), nombre(r["ptot"])
            if eh is not None and mo is not None and pt and abs(mo / pt - eh) > 0.01:
                ecarts_hab += 1
    valeurs, motifs = defaultdict(dict), Counter()
    for (a, cc, ag), ls in lignes.items():
        if len(ls) == 1 and ls[0][0] == cc:
            valeurs[(a, cc)][ag] = ls[0][1:]
        else:
            valeurs[(a, cc)].setdefault("_perimetre", set()).add(ag)
            motifs["perimetre"] += 1
    controles = {
        "lignes_lues": lignes_lues,
        "ecarts_euros_par_habitant": {"nombre": ecarts_hab,
                                      "lecture": "lignes où montant / population totale diffère de plus de 0,01 € de "
                                                 "la valeur euros_par_habitant publiée"},
        "lignes_anciennes_communes": motifs["perimetre"],
        "bornes_strates_constatees": {k: [int(v[0]), int(v[1])] for k, v in sorted(bornes.items(),
                                                                                   key=lambda kv: int(kv[0]))},
    }
    return dict(valeurs), strate, controles


def verifier_strates(bornes: dict) -> list[str]:
    """Écarts entre les bornes déclarées (STRATES_OFGL) et les populations constatées (`ptot_n`)."""
    out = []
    for k, (mi, ma) in bornes.items():
        if k not in STRATES_OFGL:
            out.append(f"strate {k} inconnue")
            continue
        de, a = STRATES_OFGL[k]
        if mi < de or (a is not None and ma > a):
            out.append(f"strate {k} : populations {mi} à {ma} hors des bornes {de} à {a}")
    return out


def lire_geo() -> dict:
    out = {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for c, v in d["communes"].items():
            out[c] = {"nom": v["nom"], "departement": v.get("departement") or dep_de(c),
                      "population": v.get("population")}
    if not out:
        raise SystemExit("site/data/local/geo absent : lancer pipeline/local.py")
    return out


def lire_taux() -> dict:
    """taux[(exercice, code de l'exercice)] = taux communal voté de foncier bâti."""
    out = {}
    for f in sorted(TAUX.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        j = d["colonnes"].index("tfb_commune")
        for c, par in d["communes"].items():
            for ex, ligne in par.items():
                if ligne and ligne[j] is not None:
                    out[(int(ex), c)] = ligne[j]
    return out


def lire_revenus() -> tuple[dict, dict, dict]:
    """(niveau de vie médian 2023 ou motif, rfr moyen des revenus 2023 ou motif, impôt net moyen des revenus 2023 ou
    motif) par commune 2026."""
    nv, rfr, impot = {}, {}, {}
    for f in sorted(REVENUS.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        kf = d["filosofi_millesimes"].index(2023)
        ka = d["annees"].index(2023)
        cf, cr = d["colonnes"].index("foyers"), d["colonnes"].index("rfr_eur")
        ci = d["colonnes"].index("impot_net_eur")
        for c, v in d["communes"].items():
            fl = (v.get("filosofi") or [None] * (kf + 1))[kf]
            if fl and fl[2] == "publie" and fl[0] is not None:
                nv[c] = (fl[0], None)
            else:
                nv[c] = (None, (fl[2] if fl else "absente"))
            ligne = (v.get("ircom") or [None] * (ka + 1))[ka]
            if ligne and ligne[cf] and ligne[cr] is not None:
                rfr[c] = (round(ligne[cr] / ligne[cf]), None)
            else:
                rfr[c] = (None, (v.get("etat") or {}).get("2023") or "non_communique")
            if ligne and ligne[cf] and ligne[ci] is not None:
                impot[c] = (round(ligne[ci] / ligne[cf]), None)
            else:
                impot[c] = (None, (v.get("etat") or {}).get("2023") or "non_communique")
    return nv, rfr, impot


def lire_investissement(annee: int = 2023) -> dict:
    """Dépenses d'équipement mandatées de l'exercice (budget principal) par commune en vigueur ; absente : pas de clé."""
    out = {}
    for f in sorted(INVESTISSEMENT.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        j = d["colonnes"].index("equipement")
        for c, v in d["communes"].items():
            ligne = (v.get("m") or {}).get(str(annee))
            if ligne and ligne[j] is not None:
                out[c] = ligne[j]
    return out


def lire_dotations(annee: int = 2024) -> tuple[dict, dict]:
    """Somme des subventions attribuées (DETR, DSIL, DPV, DSID) de l'exercice aux bénéficiaires de type commune, par
    code Insee ; contrôle : projets de l'exercice publiés sans bénéficiaire nommé."""
    out, ctrl = defaultdict(float), {"fichiers": 0, "projets_communes": 0, "non_nommes": 0}
    for f in sorted(TERRITOIRES.glob("*.json")):
        if f.stem == "index":
            continue
        ie = json.loads(f.read_text(encoding="utf-8")).get("investissement_etat") or {}
        fmt = ie.get("format_projet") or []
        if not fmt:
            continue
        ctrl["fichiers"] += 1
        ke, ks = fmt.index("exercice"), fmt.index("subvention_eur")
        ctrl["non_nommes"] += ((ie.get("totaux") or {}).get(str(annee)) or {}).get("non_nommes", {}).get("projets", 0)
        for b in ie.get("beneficiaires", []):
            if b.get("type") != "commune" or not b.get("insee"):
                continue
            for pr in b.get("projets", []):
                if pr[ke] == annee and pr[ks] is not None:
                    out[b["insee"]] += pr[ks]
                    ctrl["projets_communes"] += 1
    return dict(out), ctrl


def lire_rei_fb(annee: int = 2023) -> dict:
    """Montant de foncier bâti émis au profit de la commune (REI) pour l'année, par commune."""
    out = {}
    for f in sorted(REI_SERIES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        k = d["annees"].index(str(annee))
        for c, v in d["communes"].items():
            serie = (v.get("produits") or {}).get("tfb_commune") or []
            if k < len(serie) and serie[k] is not None:
                out[c] = serie[k]
    return out


# --- Statistiques ---------------------------------------------------------------------------------------------------

def quantile(tri: list[float], p: float) -> float:
    """Interpolation linéaire entre valeurs triées (définition 7 de Hyndman et Fan)."""
    if not tri:
        raise ValueError("liste vide")
    h = (len(tri) - 1) * p
    i = int(h)
    if i + 1 >= len(tri):
        return tri[-1]
    return tri[i] + (h - i) * (tri[i + 1] - tri[i])


def arrondi(v: float | None, unite: str) -> float | None:
    if v is None:
        return None
    if unite == "%":
        return round(v, 2)
    if unite in ("euros par an", "euros par foyer"):
        return round(v)
    return round(v, 1)


def resume(valeurs: list[float], unite: str) -> dict | None:
    if len(valeurs) < N_MIN:
        return None
    t = sorted(valeurs)
    return {"q": [arrondi(quantile(t, p), unite) for p in QUANTILES],
            "moyenne_communes": arrondi(sum(t) / len(t), unite)}


def bornes_bandes(xs: list[float], n: int = N_BANDES) -> list[float]:
    t = sorted(xs)
    return [quantile(t, k / n) for k in range(n + 1)]


def bande_de(x: float, bornes: list[float]) -> int:
    n = len(bornes) - 1
    for k in range(n):
        if x <= bornes[k + 1]:
            return k
    return n - 1


def case_stats(paires: list[tuple[float, float]], bornes: list[float], ux: str, uy: str,
               unite_points: str = "communes") -> dict:
    n = len(paires)
    out = {"n": n, "x": resume([p[0] for p in paires], ux), "y": resume([p[1] for p in paires], uy)}
    bandes = []
    par = defaultdict(list)
    for x, y in paires:
        par[bande_de(x, bornes)].append(y)
    for k in range(len(bornes) - 1):
        ys = par.get(k, [])
        r = resume(ys, uy)
        bandes.append({"n": len(ys), "y": r["q"] if r else None})
    out["bandes"] = bandes
    if n < N_MIN:
        out["motif"] = f"moins de {N_MIN} {unite_points} : quantiles non publiés"
    return out


# --- Départements ---------------------------------------------------------------------------------------------------

def valeurs_departements() -> tuple[dict, dict]:
    """Valeurs des variables départementales par département (valeur, motif) et nom ; tranche de population 2024."""
    comptes = json.loads(SOLIDARITES.read_text(encoding="utf-8"))["collectivites"]
    am = json.loads(ASSURANCE_MALADIE.read_text(encoding="utf-8"))
    k24 = am["annees"].index(2024)
    couvre = defaultdict(list)   # département -> collectivités de l'OFGL qui le couvrent avec une population 2024
    for code, c in sorted(comptes.items()):
        if (c.get("population") or {}).get("2024"):
            for d in c["departements"]:
                couvre[d].append(code)
    out, info = {}, {}
    for d, x in sorted(am["departements"].items()):
        v = {}
        colls = couvre.get(d, [])
        pop = comptes[colls[0]]["population"]["2024"] if colls == [d] and comptes[d]["departements"] == [d] else None
        presc = (x.get("prescriptions") or {}).get("total") or []
        p24 = presc[k24] if k24 < len(presc) else None
        if pop is None:
            v["prescriptions_hab_2024"] = (None, "perimetre")
        elif p24 is None:
            v["prescriptions_hab_2024"] = (None, "non_publie")
        else:
            v["prescriptions_hab_2024"] = (round(p24 / pop, 1), None)
        f = TERRITOIRES / f"{d}.json"
        asoc = json.loads(f.read_text(encoding="utf-8")).get("aide_sociale") if f.exists() else None
        lignes = [c for c in (asoc or {}).get("collectivites", []) if c.get("code") == d]
        if pop is None:
            v["aide_sociale_nette_hab_2024"] = (None, "perimetre")
        elif not lignes:
            v["aide_sociale_nette_hab_2024"] = (None, "absente")
        else:
            eh = ((((lignes[0].get("postes") or {}).get("total") or {}).get("nette") or {}).get("eur_hab") or {})
            val = eh.get("2024")
            v["aide_sociale_nette_hab_2024"] = (val, None) if val is not None else (None, "non_publie")
        strate_ = None
        if pop is not None:
            strate_ = next(k for k, (de, a) in STRATES_DEP.items() if pop >= de and (a is None or pop <= a))
        out[d] = v
        info[d] = {"nom": x.get("nom"), "population_2024": pop, "strate": strate_}
    return out, info


def produire_departements(sortie: Path, date: str) -> tuple[list[dict], dict]:
    vals, info = valeurs_departements()
    facette = {"libelle": "tranche de population totale du département (2024, OFGL ; tranches fixées par le site)",
               "source": "cnam_prescriptions",
               "cases": [{"code": k, "libelle": libelle_strate_dep(k), "bornes": list(STRATES_DEP[k])}
                         for k in sorted(STRATES_DEP, key=int)]}
    resumes = []
    for cr in CROISEMENTS_DEP:
        vx, vy = VARIABLES_DEP[cr["x"]], VARIABLES_DEP[cr["y"]]
        assert vx["annee"] == vy["annee"] == cr["annee"], cr["id"]   # règle 13 : même année
        paires = {d: (v[cr["x"]][0], v[cr["y"]][0]) for d, v in vals.items()
                  if v[cr["x"]][0] is not None and v[cr["y"]][0] is not None}
        xs, ys = [p[0] for p in paires.values()], [p[1] for p in paires.values()]
        bornes = bornes_bandes(xs, N_BANDES_DEP)
        tx, ty = sorted(xs), sorted(ys)
        axes = {"x": [arrondi(tx[0], vx["unite"]), arrondi(tx[-1], vx["unite"])],
                "y": [arrondi(ty[0], vy["unite"]), arrondi(ty[-1], vy["unite"])]}
        groupes, sans_case = defaultdict(list), 0
        for d, p_ in paires.items():
            k = info[d]["strate"]
            if k is None:
                sans_case += 1
            else:
                groupes[k].append(p_)
        territoires = {}
        for d in sorted(vals):
            t = {"nom": info[d]["nom"], "strate": info[d]["strate"], "x": vals[d][cr["x"]][0], "y": vals[d][cr["y"]][0]}
            m = {var: vals[d][var][1] for var in (cr["x"], cr["y"]) if vals[d][var][1]}
            if m:
                t["motifs"] = m
            territoires[d] = t
        doc = {
            "millesime": f"{cr['annee']}", "source": f"{SOURCES[vx['source']]['titre']} ; {SOURCES[vy['source']]['titre']}",
            "date_sources": date, "id": cr["id"], "titre": cr["titre"], "annee": cr["annee"],
            "niveau": "departement", "unite_points": "départements",
            "x": {"variable": cr["x"], **{k: vx[k] for k in ("libelle", "unite", "annee", "statut")}},
            "y": {"variable": cr["y"], **{k: vy[k] for k in ("libelle", "unite", "annee", "statut")}},
            "perimetre": PERIMETRE_DEP, "avertissement": AVERTISSEMENT_DEP,
            "statut": STATUT_CALCULE,
            "methode": METHODE["quantiles_dep"] + ". " + METHODE["bandes_dep"] + ". " + METHODE["axes_dep"] + ".",
            "quantiles": [int(p * 100) for p in QUANTILES], "n_min": N_MIN,
            "bandes_bornes": [arrondi(b, vx["unite"]) for b in bornes], "axes": axes,
            "communes": 0, "territoires_croises": len(paires),
            "ensemble": case_stats(list(paires.values()), bornes, vx["unite"], vy["unite"], "départements"),
            "facettes": {"strate_departement": {
                "cases": [{"code": cs["code"], **case_stats(groupes.get(cs["code"], []), bornes, vx["unite"],
                                                            vy["unite"], "départements")}
                          for cs in facette["cases"]],
                "communes_sans_case": sans_case}},
            "territoires": territoires,
            "regle_null": "null : valeur non publiée par la source ou non croisable ; motif dans `motifs` (voir "
                          "`motifs` de typologies/index.json). Jamais 0.",
        }
        dump(sortie / "croisements" / f"{cr['id']}.json", doc)
        resumes.append({**cr, "fichier": f"croisements/{cr['id']}.json", "communes": 0,
                        "territoires_croises": len(paires), "perimetre": PERIMETRE_DEP,
                        "sources": [vx["source"], vy["source"]]})
    return resumes, facette


# --- Production -----------------------------------------------------------------------------------------------------

def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    if len(txt.encode("utf-8")) > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets : à découper")
    path.write_text(txt + "\n", encoding="utf-8")
    return len(txt.encode("utf-8"))


def par_habitant(montant, ligne_ofgl: dict) -> float | None:
    """montant / population totale de l'exercice publiée par l'OFGL (même commune, même exercice)."""
    pops = [v[2] for k, v in sorted(ligne_ofgl.items()) if k != "_perimetre" and v[2]]
    if montant is None or not pops:
        return None
    return round(montant / pops[0], 1)


def valeurs_communes(geo, grille, aav, ofgl, strate, passage, taux, nv, rfr, impot=None, equip=None, dot=None,
                     fb=None) -> tuple[dict, Counter]:
    """Valeur de chaque variable pour chaque commune en vigueur : (valeur, motif)."""
    out, motifs = {}, Counter()
    for c in sorted(geo):
        v = {}
        for nom, cle in AGREGATS.items():
            for a in ANNEES_OFGL:
                var = f"{cle}_hab_{a}"
                ligne = ofgl.get((a, c), {})
                if not passage.stable(2025, c):
                    v[var] = (None, "perimetre")
                elif cle in ligne.get("_perimetre", set()):
                    v[var] = (None, "perimetre")
                elif cle in ligne and ligne[cle][0] is not None:
                    v[var] = (round(ligne[cle][0], 2), None)
                elif cle in ligne:
                    v[var] = (None, "non_publie")
                else:
                    v[var] = (None, "absente")
        v["niveau_vie_median_2023"] = nv.get(c, (None, "absente"))
        v["rfr_moyen_foyer_2023"] = rfr.get(c, (None, "absente"))
        v["impot_revenu_moyen_foyer_2023"] = (impot or {}).get(c, (None, "absente"))
        for var, a, source_, defaut in (("equipement_paye_hab_2023", 2023, equip or {}, None),
                                        ("dotations_etat_hab_2024", 2024, dot or {}, 0.0),
                                        ("produit_fb_commune_hab_2023", 2023, fb or {}, None)):
            ligne = ofgl.get((a, c), {})
            montant = source_.get(c, defaut)
            if not (passage.stable(2025, c) and passage.stable(a, c)) or ligne.get("_perimetre"):
                v[var] = (None, "perimetre")
            elif montant is None:
                v[var] = (None, "absente")
            elif par_habitant(montant, ligne) is None:
                v[var] = (None, "non_publie")
            else:
                v[var] = (par_habitant(montant, ligne), None)
        for a in (2023, 2024):
            var = f"taux_fb_commune_{a}"
            if not passage.stable(a, c):
                v[var] = (None, "perimetre")
            elif (a, c) in taux:
                v[var] = (taux[(a, c)], None)
            else:
                v[var] = (None, "absente")
        for var, (val, m) in v.items():
            motifs[(var, m or "publie")] += 1
        out[c] = v
    return out, motifs


def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    date = date_sources("typologies")
    geo = lire_geo()
    grille, libelles, meta_grille = lire_grille()
    aav = lire_aav()
    ofgl, strate, ctrl_ofgl = lire_ofgl()
    hors_bornes = verifier_strates(ctrl_ofgl["bornes_strates_constatees"])
    if hors_bornes:
        raise SystemExit("strates de l'OFGL : " + " ; ".join(hors_bornes))
    passage = lire_passage((2023, 2024, 2025))
    taux = lire_taux()
    nv, rfr, impot = lire_revenus()
    equip = lire_investissement(2023)
    dot, ctrl_dot = lire_dotations(2024)
    if ctrl_dot["non_nommes"]:
        raise SystemExit(f"dotations 2024 : {ctrl_dot['non_nommes']} projets sans bénéficiaire nommé ; le 0 d'une "
                         "commune sans projet ne serait plus sûr")
    fb = lire_rei_fb(2023)
    vals, motifs = valeurs_communes(geo, grille, aav, ofgl, strate, passage, taux, nv, rfr, impot, equip, dot, fb)

    facettes = {
        "densite": {"libelle": "niveau de densité (grille communale de densité 2025, Insee, 7 niveaux)",
                    "source": "grille", "cases": [{"code": k, "libelle": l} for k, l in libelles["7"].items()]},
        "strate": {"libelle": "strate de population (OFGL)", "source": "ofgl",
                   "cases": [{"code": k, "libelle": libelle_strate(k), "bornes": list(STRATES_OFGL[k])}
                             for k in sorted(STRATES_OFGL, key=int)]},
        "aav": {"libelle": "place dans l'aire d'attraction des villes 2020 (Insee)", "source": "aav",
                "cases": [{"code": k, "libelle": l} for k, l in CATEGORIES_AAV.items()]},
    }

    def case_de(c: str, facette: str) -> str | None:
        if facette == "densite":
            return (grille.get(c) or {}).get("densite")
        if facette == "strate":
            return strate.get(c) if passage.stable(2025, c) else None
        return (aav.get(c) or {}).get("aav")

    def nom_source(var: str) -> str:
        s = SOURCES[VARIABLES[var]["source"]]
        return s["titre"]

    # Croisements
    resume_croisements, axes_tous = [], {}
    sortie.mkdir(parents=True, exist_ok=True)
    for cr in CROISEMENTS:
        vx, vy = VARIABLES[cr["x"]], VARIABLES[cr["y"]]
        assert vx["annee"] == vy["annee"] == cr["annee"], cr["id"]   # règle 13 : même année
        paires = {c: (v[cr["x"]][0], v[cr["y"]][0]) for c, v in vals.items()
                  if v[cr["x"]][0] is not None and v[cr["y"]][0] is not None}
        xs = [p[0] for p in paires.values()]
        ys = [p[1] for p in paires.values()]
        bornes = bornes_bandes(xs)
        tx, ty = sorted(xs), sorted(ys)
        axes = {"x": [arrondi(quantile(tx, 0.01), vx["unite"]), arrondi(quantile(tx, 0.99), vx["unite"])],
                "y": [arrondi(quantile(ty, 0.01), vy["unite"]), arrondi(quantile(ty, 0.99), vy["unite"])]}
        axes_tous[cr["id"]] = axes
        par_facette = {}
        for fac, desc in facettes.items():
            groupes = defaultdict(list)
            sans_case = 0
            for c, p in paires.items():
                k = case_de(c, fac)
                if k is None:
                    sans_case += 1
                else:
                    groupes[k].append(p)
            par_facette[fac] = {
                "cases": [{"code": cs["code"], **case_stats(groupes.get(cs["code"], []), bornes, vx["unite"],
                                                            vy["unite"])} for cs in desc["cases"]],
                "communes_sans_case": sans_case,
            }
        ensemble = case_stats(list(paires.values()), bornes, vx["unite"], vy["unite"])
        doc = {
            "millesime": f"{cr['annee']}", "source": f"{nom_source(cr['x'])} ; {nom_source(cr['y'])}",
            "date_sources": date, "id": cr["id"], "titre": cr["titre"], "annee": cr["annee"],
            "x": {"variable": cr["x"], **{k: vx[k] for k in ("libelle", "unite", "annee", "statut")}},
            "y": {"variable": cr["y"], **{k: vy[k] for k in ("libelle", "unite", "annee", "statut")}},
            "perimetre": PERIMETRE, "avertissement": AVERTISSEMENT,
            "statut": STATUT_CALCULE,
            "methode": METHODE["quantiles"] + ". " + METHODE["bandes"] + ". " + METHODE["axes"] + ".",
            "quantiles": [int(p * 100) for p in QUANTILES], "n_min": N_MIN,
            "bandes_bornes": [arrondi(b, vx["unite"]) for b in bornes], "axes": axes,
            "communes": len(paires), "ensemble": ensemble, "facettes": par_facette,
        }
        dump(sortie / "croisements" / f"{cr['id']}.json", doc)
        resume_croisements.append({**cr, "fichier": f"croisements/{cr['id']}.json", "communes": len(paires),
                                   "perimetre": PERIMETRE,
                                   "sources": [VARIABLES[cr["x"]]["source"], VARIABLES[cr["y"]]["source"]]})

    res_dep, facette_dep = produire_departements(sortie, date)
    resume_croisements += res_dep
    facettes["strate_departement"] = facette_dep

    # Rapports par strate (calcul du site, sommes des montants / sommes des populations)
    rapports = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0]))
    for (a, c), ligne in ofgl.items():
        t = strate.get(c)
        if t is None:
            continue
        for cle, val in ligne.items():
            if cle == "_perimetre":
                continue
            _, montant, ptot = val
            if montant is None or not ptot:
                continue
            r = rapports[(a, cle)][t]
            r[0] += 1
            r[1] += montant
            r[2] += ptot
    strates_ofgl = {
        "statut": STATUT_CALCULE, "methode": METHODE["rapport_strate"],
        "perimetre": "communes dont le compte de l'exercice est publié par l'OFGL sous leur code 2025 (anciennes "
                     "communes fusionnées exclues)",
        "unite": "euros par habitant",
        "lignes": [{"annee": a, "agregat": cle, "strate": t, "communes": r[0],
                    "euros_par_habitant": round(r[1] / r[2], 1) if r[2] else None}
                   for (a, cle) in sorted(rapports) for t, r in sorted(rapports[(a, cle)].items(),
                                                                       key=lambda kv: int(kv[0]))],
    }

    # Communes par département
    colonnes = list(VARIABLES)
    par_dep = defaultdict(dict)
    for c in sorted(vals):
        g = geo[c]
        v = vals[c]
        gr, aa = grille.get(c) or {}, aav.get(c) or {}
        ligne = {"nom": g["nom"], "population": g["population"],
                 "densite": gr.get("densite"), "densite3": gr.get("densite3"), "densite_aav": gr.get("densite_aav"),
                 "aav": aa.get("aav"), "aav_tranche": aa.get("aav_tranche"),
                 "strate": strate.get(c) if passage.stable(2025, c) else None,
                 "v": [v[k][0] for k in colonnes]}
        m = {k: v[k][1] for k in colonnes if v[k][1]}
        if m:
            ligne["motifs"] = m
        par_dep[g["departement"]][c] = ligne
    deps = []
    for d in sorted(par_dep):
        doc = {"millesime": "grille de densité 2025 ; aires d'attraction des villes 2020 ; comptes 2023 et 2024 ; "
                            "revenus 2023 ; taux 2023 et 2024",
               "source": "Insee (grille communale de densité, aires d'attraction des villes) ; OFGL (comptes "
                         "consolidés des communes) ; DGFiP (REI, IRCOM) ; Insee (Filosofi 2) ; voir typologies/index.json",
               "date_sources": date, "departement": d, "colonnes": colonnes,
               "regle_null": "null : valeur non publiée par la source ou non croisable ; le motif est dans "
                             "`motifs.<variable>` (voir `motifs` de typologies/index.json). Jamais 0.",
               "communes": par_dep[d]}
        dump(sortie / "communes" / f"{d}.json", doc)
        deps.append({"departement": d, "fichier": f"communes/{d}.json", "communes": len(par_dep[d])})

    couverture = {
        "communes_cog": len(geo),
        "grille_sans_commune": sorted(set(grille) - set(geo))[:20],
        "communes_sans_grille": sorted(set(geo) - set(grille))[:20],
        "communes_sans_aav": sorted(set(geo) - set(aav))[:20],
        "communes_sans_strate": sum(1 for c in geo if not (strate.get(c) and passage.stable(2025, c))),
        "valeurs": {var: {m: n for (vv, m), n in sorted(motifs.items()) if vv == var} for var in VARIABLES},
    }
    index = {
        "millesime": "grille de densité 2025 (géographie 2026) ; aires d'attraction des villes 2020 (géographie 2026) ; "
                     "comptes 2023 et 2024 ; revenus 2023 ; taux 2023 et 2024",
        "source": "Insee (grille communale de densité, aires d'attraction des villes) ; OFGL (comptes consolidés des "
                  "communes, " + URL_OFGL + ") ; DGFiP (REI, IRCOM) ; Insee (Filosofi 2)",
        "date_sources": date,
        "presentation": "Des communes qui se ressemblent (même niveau de densité, même strate de population, même "
                        "place dans l'aire d'attraction d'une ville) et, pour quelques paires de chiffres choisies "
                        "d'avance, comment ces chiffres se répartissent entre elles. La page ne dit pas pourquoi une "
                        "commune dépense, s'endette ou taxe plus ou moins qu'une autre.",
        "avertissement": AVERTISSEMENT,
        "variables": {**VARIABLES, **VARIABLES_DEP}, "croisements": resume_croisements, "facettes": facettes,
        "strates_departements": {"source": "population totale 2024 de l'OFGL (site/data/solidarites_departements)",
                                 "regle": "tranches fixées par le site ; aucune strate officielle de département "
                                          "n'est lue", "tranches": {k: list(v) for k, v in STRATES_DEP.items()}},
        "densite_libelles": libelles, "aav_categories": CATEGORIES_AAV, "aav_tranches": TRANCHES_AAV,
        "strates_ofgl": strates_ofgl,
        "motifs": {"absente": "aucune ligne de la source pour cette commune et cette année",
                   "perimetre": "territoire de la commune différent entre l'année des données et 2026 (fusion, "
                                "scission, ancienne commune) : non croisé",
                   "non_publie": "ligne présente, valeur non publiée par la source",
                   "secret": "valeur confidentielle (secret statistique de l'Insee)",
                   "hors_champ": "département hors du champ de Filosofi 2023",
                   "valeur_manquante": "valeur manquante à la source (Insee)",
                   "non_communique": "valeur non communiquée par la DGFiP",
                   "incomplete": "anciennes communes incomplètes dans l'IRCOM (voir revenus_communes)"},
        "departements": deps, "couverture": couverture,
        "controles": {"ofgl": ctrl_ofgl, "grille": meta_grille, "strates_hors_bornes": hors_bornes,
                      "dotations_2024": ctrl_dot},
        "methode": METHODE, "limites": LIMITES, "non_repris": NON_REPRIS, "sources": SOURCES,
        "sources_inaccessibles": [], "recherche_publique": RECHERCHE_PUBLIQUE,
        "ordre": "communes par code Insee ; cases dans l'ordre des nomenclatures de l'Insee et de l'OFGL ; aucune "
                 "commune n'est classée",
    }
    dump(sortie / "index.json", index)
    return index


def collecter() -> int:
    ids = [s["id_catalogue"] for s in SOURCES.values() if s.get("id_catalogue")]
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *ids])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter()
    if a.etape in ("produire", "tout"):
        produire(a.sortie)


if __name__ == "__main__":
    main()
