"""Solidarités des départements : allocations individuelles de solidarité (RSA, APA, PCH) dans les comptes, recettes
que les comptes rattachent à ces allocations (TICPE, FMDI, dotations de la CNSA), reste à charge calculé, et
bénéficiaires de l'aide sociale départementale (personnes âgées, personnes handicapées, enfance, RSA), par
collectivité et par année.

Ce module complète, sans les recopier, trois vues déjà publiées :
  - territoires/<dep>.json (pipeline/territoires.py) : dépenses d'aide sociale de la DREES par poste (RSA, APA, PCH,
    ASE, autres ; brutes et nettes), indicateurs ISD, APA à domicile et PCH payées en décembre ;
  - prestations/departements/<annee>.json (pipeline/prestations.py) : foyers du RSA payés par les CAF, départements
    où l'État finance le RSA ;
  - local/budgets/ (pipeline/local.py) : grands agrégats des comptes des départements.
Il y renvoie par des liens et publie les écarts entre sources, jamais additionnées.

Entrées (data/lake, collectées par collecte/collecte.py, identifiants déclarés dans collecte/catalogue.json) :
  collectivites/local_departements.parquet          OFGL, comptes consolidés des départements 2012-2025
  collectivites/local_regions.parquet               OFGL, comptes consolidés des régions (collectivités uniques)
  solidarites_departements/solidarites_ofgl_formules.parquet   OFGL, formules des agrégats (extrait)
  solidarites_departements/solidarites_drees_paph.xlsx         DREES, bénéficiaires PA et PH, séries longues
  solidarites_departements/solidarites_drees_ase.xlsx          DREES, bénéficiaires de l'ASE, séries longues
  solidarites_departements/solidarites_drees_minima_dep.xlsx   DREES, minima sociaux par département (tableau 11)
  lecture seule : site/data/territoires/, site/data/prestations/ (liens, écarts, financeur du RSA).
Sorties (site/data/solidarites_departements/, chaque fichier < 1 Mo, avec `millesime` et `source`) :
  index.json          collectivités par département, totaux nationaux, reste à charge calculé (national), écarts
                      nationaux, liens, méthode, limites, sources, sources inaccessibles, recherche préalable
  comptes.json        par collectivité et par exercice : allocations, frais d'hébergement, recettes rattachées,
                      population, euros par habitant, reste à charge calculé, financeur du RSA
  beneficiaires.json  par collectivité : séries de bénéficiaires de la DREES (aides aux personnes âgées et
                      handicapées, ASE, RSA), totaux estimés publiés par la DREES
  ecarts.json         écarts par collectivité entre sources (comptes contre enquête Aide sociale ; deux
                      publications de la DREES ; DREES contre CNAF)

Commandes :
  python pipeline/solidarites_departements.py collecter   # réseau : collecte/collecte.py sur les sources du module
  python pipeline/solidarites_departements.py produire    # sans réseau ; --sortie DOSSIER pour une copie de contrôle
  python pipeline/solidarites_departements.py             # les deux

Règles :
  - agrégats publiés seulement : aucune donnée individuelle, aucune personne nommée ;
  - une valeur absente de la source (agrégat non publié pour l'exercice, cellule vide, « - ») reste null, jamais 0 ;
    un 0 publié reste 0 ;
  - le reste à charge est un calcul du site (formule, périmètre et limites publiés dans les fichiers), pas une valeur
    de l'administration ; il est null dès qu'une composante manque ou que l'État finance le RSA ;
  - deux sources ne sont jamais additionnées ; leurs écarts sont publiés (montant, différence, part) avec leur lecture ;
  - dates par pipeline/reproductible.py ; tris explicites : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "solidarites_departements"
SITE = ROOT / "site" / "data"
SORTIE_DEFAUT = SITE / "solidarites_departements"
AXE = "solidarites_departements"
MAX_OCTETS = 1_000_000

DREES_API = "https://data.drees.solidarites-sante.gouv.fr/api/explore/v2.1/catalog/datasets"
DREES_PAGE = "https://data.drees.solidarites-sante.gouv.fr/explore/dataset"
OFGL_API = "https://data.ofgl.fr/api/explore/v2.1/catalog/datasets"
OFGL_PAGE = "https://data.ofgl.fr/explore/dataset"
DATASET_PAPH = "les-beneficiaires-de-l-aide-sociale-departementale-aux-personnes-agees-ou-handic"
DATASET_ASE = "les-beneficiaires-de-l-aide-sociale-a-l-enfance"
DATASET_MINIMA = "336_minima-sociaux-rsa-et-prime-d-activite"

# --- Sources ----------------------------------------------------------------------------------------------------------

SOURCES = {
    "ofgl_departements": {
        "id_catalogue": "local_departements", "fichier": "collectivites/local_departements.parquet",
        "titre": "OFGL, « Comptes consolidés des départements 2012-2025 » (ofgl-base-departements-consolidee) : "
                 "agrégats calculés par l'OFGL à partir des balances comptables publiées par la DGFiP, budgets "
                 "principaux et annexes, flux croisés neutralisés",
        "url": f"{OFGL_API}/ofgl-base-departements-consolidee/exports/parquet",
        "page": f"{OFGL_PAGE}/ofgl-base-departements-consolidee/",
        "producteur": "OFGL (Observatoire des finances et de la gestion publique locales), à partir des balances "
                      "comptables de la DGFiP",
        "licence": "Licence Ouverte 2.0", "millesime": "exercices 2012 à 2025",
        "verdict": "réutilisable tel quel (agrégats publiés ; même fichier que pipeline/local.py, lu par SIREN)",
    },
    "ofgl_regions": {
        "id_catalogue": "local_regions", "fichier": "collectivites/local_regions.parquet",
        "titre": "OFGL, « Comptes consolidés des régions » (ofgl-base-regions-consolidee) : comptes des collectivités "
                 "territoriales uniques de Martinique et de Guyane (depuis 2016) et de Corse (depuis 2018), qui "
                 "exercent les compétences départementales",
        "url": f"{OFGL_API}/ofgl-base-regions-consolidee/exports/parquet",
        "page": f"{OFGL_PAGE}/ofgl-base-regions-consolidee/",
        "producteur": "OFGL, à partir des balances comptables de la DGFiP", "licence": "Licence Ouverte 2.0",
        "millesime": "exercices 2016 à 2025 (Martinique, Guyane), 2018 à 2025 (Corse)",
        "verdict": "réutilisable tel quel (lignes des collectivités uniques seulement)",
    },
    "ofgl_formules": {
        "id_catalogue": "solidarites_ofgl_formules",
        "fichier": "solidarites_departements/solidarites_ofgl_formules.parquet",
        "titre": "OFGL, « Méthodologie OFGL - Formules des agrégats financiers » (extrait : départements et régions, "
                 "agrégats repris ici)",
        "url": f"{OFGL_API}/methodologie-ofgl-formules-des-agregats-financiers/exports/parquet",
        "page": f"{OFGL_PAGE}/methodologie-ofgl-formules-des-agregats-financiers/",
        "producteur": "OFGL", "licence": "Licence Ouverte 2.0", "millesime": "formules 2012 à 2025",
        "verdict": "réutilisable tel quel (formule de chaque agrégat par nomenclature M52 ou M57 et par exercice)",
    },
    "drees_paph": {
        "id_catalogue": "solidarites_drees_paph", "fichier": "solidarites_departements/solidarites_drees_paph.xlsx",
        "titre": "DREES, « Les bénéficiaires de l'aide sociale départementale aux personnes âgées ou handicapées », "
                 "séries longues 1996-2024 (enquête Aide sociale), un onglet par aide",
        "url": f"{DREES_API}/{DATASET_PAPH}/attachments/"
               "paph_les_beneficiaires_de_l_aide_sociale_departementale_series_longues_1996_2024_xlsx",
        "page": f"{DREES_PAGE}/{DATASET_PAPH}/",
        "producteur": "DREES", "licence": "Licence Ouverte 2.0", "millesime": "2000 à 2024 (fin d'année)",
        "verdict": "à adapter (classeur xlsx, un onglet par aide, colonnes repérées par leur en-tête ; code 6EA de "
                   "la source lu comme 6AE, code 20 comme 20R)",
    },
    "drees_ase": {
        "id_catalogue": "solidarites_drees_ase", "fichier": "solidarites_departements/solidarites_drees_ase.xlsx",
        "titre": "DREES, « Les bénéficiaires de l'aide sociale à l'enfance », séries longues 1996-2024 (enquête "
                 "Aide sociale), tableaux 1 à 10 par département",
        "url": f"{DREES_API}/{DATASET_ASE}/attachments/"
               "les_beneficiaires_de_l_aide_sociale_a_l_enfance_series_longues_1996_2024_xlsx",
        "page": f"{DREES_PAGE}/{DATASET_ASE}/",
        "producteur": "DREES", "licence": "Licence Ouverte 2.0", "millesime": "2002 à 2024 (au 31 décembre)",
        "verdict": "à adapter (classeur xlsx, colonnes repérées par leur en-tête ; code 20 lu comme 20R)",
    },
    "drees_minima": {
        "id_catalogue": "solidarites_drees_minima_dep",
        "fichier": "solidarites_departements/solidarites_drees_minima_dep.xlsx",
        "titre": "DREES, « Minima sociaux : données départementales par dispositif », tableau 11 : allocataires du "
                 "RSA par département au 31 décembre (CNAF et MSA)",
        "url": f"{DREES_API}/{DATASET_MINIMA}/attachments/minima_sociaux_donnees_departementales_par_dispositif_xlsx",
        "page": f"{DREES_PAGE}/{DATASET_MINIMA}/",
        "producteur": "DREES (données CNAF et MSA)", "licence": "Licence Ouverte 2.0", "millesime": "2009 à 2024",
        "verdict": "à adapter (classeur xlsx ; 2016 publié deux fois, la série reprend la valeur du nouveau "
                   "système de production de la CNAF)",
    },
    "territoires": {
        "titre": "site/data/territoires (pipeline/territoires.py), lecture seule : dépenses d'aide sociale de la "
                 "DREES par poste et par collectivité (série 376, brutes et nettes), APA à domicile et PCH payées "
                 "en décembre (jeu « APA et PCH - Montants versés »)",
        "page": "site/data/territoires/index.json", "producteur": "pipeline/territoires.py (DREES)",
        "licence": "Licence Ouverte 2.0", "millesime": "aide sociale 1999 à 2024",
        "verdict": "réutilisable tel quel (mêmes codes de collectivité que la DREES)",
    },
    "prestations": {
        "titre": "site/data/prestations (pipeline/prestations.py), lecture seule : foyers allocataires du RSA payés "
                 "par les CAF au titre de décembre (champ CAF), départements où l'État finance le RSA",
        "page": "site/data/prestations/index.json", "producteur": "pipeline/prestations.py (CNAF)",
        "licence": "Licence Ouverte 2.0", "millesime": "2019 à 2025",
        "verdict": "réutilisable tel quel (codes départementaux de l'Insee)",
    },
}
COLLECTABLES = ["solidarites_drees_paph", "solidarites_drees_ase", "solidarites_drees_minima_dep",
                "solidarites_ofgl_formules", "local_departements", "local_regions"]

INACCESSIBLES = [
    {"source": "CNSA, notifications des concours APA et PCH par département (concours définitifs 2023 et 2024, "
               "PDF et documents Word sur cnsa.fr)",
     "constat_le": "2026-11-18",
     "motif": "le serveur cnsa.fr ne transmet pas son certificat intermédiaire : le téléchargement est refusé par la "
              "vérification TLS (aucun contournement) ; documents PDF ou Word, sans jeu de données ouvert. Les "
              "dotations de la CNSA reçues par chaque département restent lisibles dans ses comptes (agrégat CNSA "
              "de l'OFGL), sans séparation entre APA, PCH et autres concours"},
    {"source": "DGCL, notes de répartition du FMDI, du dispositif de compensation péréquée (DCP) et du fonds national "
               "de péréquation des droits de mutation (critère du reste à charge des allocations individuelles de "
               "solidarité par département)",
     "constat_le": "2026-11-18",
     "motif": "publiées en PDF seulement (collectivites-locales.gouv.fr) ; la note 2025 du fonds de péréquation des "
              "droits de mutation est une image numérisée, sans texte lisible ; non reprises"},
    {"source": "Reste à charge des allocations individuelles de solidarité par département, calculé par "
               "l'administration",
     "constat_le": "2026-11-18",
     "motif": "aucun jeu de données ouvert trouvé (DREES, DGCL, OFGL, data.gouv.fr) ; le site publie un calcul à "
              "partir des comptes, avec sa formule et ses limites"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "requetes": ["data.drees : « aide sociale », bénéficiaires et dépenses de l'aide sociale départementale",
                 "data.ofgl.fr : catalogue complet (comptes des départements, formules des agrégats)",
                 "data.economie.gouv.fr : « balances comptables des départements »",
                 "data.gouv.fr : concours CNSA, compensation du RSA, FMDI, DCP, allocations individuelles de "
                 "solidarité",
                 "collectivites-locales.gouv.fr : notes FMDI, DCP, fonds de péréquation des droits de mutation",
                 "GitHub (dépôts et code) : « aide sociale départementale », « allocations individuelles de "
                 "solidarité », « reste à charge RSA APA PCH », « ofgl-base-departements-consolidee », "
                 "« les-beneficiaires-de-l-aide-sociale-departementale »"],
    "conclusion": "Les producteurs publient les agrégats nécessaires (comptes consolidés de l'OFGL, enquête Aide "
                  "sociale de la DREES) : ils sont repris tels quels. Aucun dépôt public ne rapproche, par "
                  "département, les allocations des comptes, les recettes que les comptes leur rattachent et les "
                  "bénéficiaires, avec les écarts entre sources : module écrit pour le dépôt, sur le modèle de "
                  "pipeline/territoires.py et pipeline/prestations.py.",
    "trouvailles": [
        {"nom": "OFGL, Comptes consolidés des départements 2012-2025", "url": SOURCES["ofgl_departements"]["page"],
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-07-17", "verdict": "réutilisable tel quel"},
        {"nom": "OFGL, Méthodologie, formules des agrégats financiers", "url": SOURCES["ofgl_formules"]["page"],
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "jeu courant (formules 2012 à 2025)",
         "verdict": "réutilisable tel quel"},
        {"nom": "DREES, Bénéficiaires de l'aide sociale départementale aux personnes âgées ou handicapées",
         "url": SOURCES["drees_paph"]["page"], "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-09-03",
         "verdict": "à adapter"},
        {"nom": "DREES, Bénéficiaires de l'aide sociale à l'enfance", "url": SOURCES["drees_ase"]["page"],
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-09-03", "verdict": "à adapter"},
        {"nom": "DREES, Minima sociaux, RSA et prime d'activité (336), données départementales",
         "url": SOURCES["drees_minima"]["page"], "licence": "Licence Ouverte 2.0", "mise_a_jour": "2025-12-04",
         "verdict": "à adapter"},
        {"nom": "DREES, Les dépenses d'aide sociale départementale (376)",
         "url": f"{DREES_PAGE}/376_les-depenses-d-aide-sociale-departementale/", "licence": "Licence Ouverte 2.0",
         "mise_a_jour": "2026-04-17",
         "verdict": "réutilisable tel quel (déjà publié par pipeline/territoires.py : lien, pas de copie)"},
        {"nom": "DGFiP, Balances comptables des départements depuis 2010 (data.economie.gouv.fr)",
         "url": "https://data.economie.gouv.fr/explore/dataset/balances-comptables-des-departements/",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-07-13",
         "verdict": "inspiration seulement (source des agrégats de l'OFGL, qui les publie déjà consolidés)"},
        {"nom": "CNSA, notifications des concours aux départements (cnsa.fr)", "url": "https://www.cnsa.fr/",
         "licence": "non précisée", "mise_a_jour": "2025-10 (concours définitifs 2024)",
         "verdict": "inaccessible (voir sources_inaccessibles)"},
        {"nom": "patrickaubert/asdep (paquet R)", "url": "https://github.com/patrickaubert/asdep",
         "licence": "fichier LICENSE.md, type non précisé", "dernier_commit": "2026-01-22",
         "verdict": "inspiration seulement (lecture des classeurs de la DREES, en R)"},
        {"nom": "Departement-de-l-Aude/app-finances-departements",
         "url": "https://github.com/Departement-de-l-Aude/app-finances-departements", "licence": "AGPL-3.0",
         "dernier_commit": "2026-08-24",
         "verdict": "inspiration seulement (tableau de bord Streamlit des agrégats de l'OFGL, sans recettes "
                    "rattachées ni bénéficiaires)"},
        {"nom": "TheoMrc/FranceRoueLibre", "url": "https://github.com/TheoMrc/FranceRoueLibre", "licence": "MIT",
         "dernier_commit": "2026-11-15",
         "verdict": "inspiration seulement (cartes des agrégats de l'OFGL, sans rapprochement avec la DREES)"},
        {"nom": "ArthurVerrez/chaque-euro", "url": "https://github.com/ArthurVerrez/chaque-euro",
         "licence": "AGPL-3.0", "dernier_commit": "2026-11-17",
         "verdict": "inspiration seulement (communes, pas d'aide sociale départementale)"},
        {"nom": "pipeline/territoires.py, pipeline/prestations.py, pipeline/local.py (ce dépôt)",
         "url": "https://github.com/MoonEyes/Ou-vont-mes-impots", "licence": "MIT", "dernier_commit": "dépôt courant",
         "verdict": "réutilisable tel quel (sorties publiées lues en lecture seule ; forme des écarts et des sources)"},
    ],
}

# --- Comptes (OFGL) ----------------------------------------------------------------------------------------------------

# (clé publiée, libellé de l'agrégat OFGL, rôle)
AGREGATS = [
    ("allocations_rsa", "Allocations RSA", "allocation"),
    ("allocations_apa", "Allocations APA", "allocation"),
    ("allocations_pch", "Allocations PCH", "allocation"),
    ("frais_hebergement", "Frais d'hébergement", "depense"),
    ("ticpe", "TICPE", "recette"),
    ("fmdi", "FMDI", "recette"),
    ("cnsa", "CNSA", "recette"),
]
COLONNES = [k for k, _, _ in AGREGATS]
PAR_LIBELLE = {lib: k for k, lib, _ in AGREGATS}
DEFINITIONS_COMPTES = {
    "allocations_rsa": "allocations du revenu de solidarité active versées aux organismes payeurs (CAF, MSA), et "
                       "reliquats du RMI",
    "allocations_apa": "allocation personnalisée d'autonomie (APA), à domicile et en établissement",
    "allocations_pch": "prestation de compensation du handicap (PCH) et allocation compensatrice pour tierce personne "
                       "(ACTP)",
    "frais_hebergement": "frais de séjour et d'hébergement payés par le département : aide sociale à l'hébergement "
                         "des personnes âgées et handicapées, placements de l'aide sociale à l'enfance (et frais "
                         "d'inhumation)",
    "ticpe": "fraction de la taxe intérieure de consommation sur les produits énergétiques (TICPE) perçue : "
             "compensation du transfert du RMI (2004) puis de l'extension au RSA (2009), et d'autres transferts ; "
             "pour une collectivité unique, fractions régionales comprises",
    "fmdi": "fonds de mobilisation départementale pour l'insertion (FMDI), versé par l'État au titre du RSA",
    "cnsa": "dotations versées par la Caisse nationale de solidarité pour l'autonomie (CNSA) : concours APA et PCH, "
            "et autres concours (maisons départementales des personnes handicapées, prévention, aide à domicile)",
}
LECTURE_COMPTES = ("montants des comptes de l'exercice (débit net pour une dépense, crédit net pour une recette), "
                   "budgets principaux et annexes, flux croisés neutralisés, tels que calculés et publiés par l'OFGL")

# Reste à charge calculé : allocations moins recettes que les comptes leur rattachent
RESTE_A_CHARGE = {
    "rsa": {"allocations": ["allocations_rsa"], "recettes": ["ticpe", "fmdi"]},
    "apa_pch": {"allocations": ["allocations_apa", "allocations_pch"], "recettes": ["cnsa"]},
}
RAC_DEFINITION = {
    "statut": "calculé",
    "producteur": "ce site, à partir des comptes publiés par l'OFGL ; ce n'est pas une valeur publiée par "
                  "l'administration",
    "formules": {"rsa": "allocations_rsa - ticpe - fmdi",
                 "apa_pch": "allocations_apa + allocations_pch - cnsa"},
    "perimetre": "chaque collectivité, chaque exercice clos de 2012 à 2025 ; montant null dès qu'une composante est "
                 "absente de la source, pour le RSA quand l'État le finance (premier exercice entier après la "
                 "recentralisation) et pour le RSA d'une collectivité unique (TICPE régionale et départementale "
                 "confondues)",
    "methode": "différence entre les allocations versées et les recettes que les comptes rattachent nommément à ces "
               "allocations ; un montant positif est la part des allocations que ces recettes ne couvrent pas",
    "limites": [
        "Les dotations de la CNSA comprennent aussi des concours sans lien avec l'APA ou la PCH (maisons "
        "départementales des personnes handicapées, prévention, aide à domicile) : le reste à charge APA et PCH "
        "calculé ici est donc plus bas que celui calculé avec les seuls concours APA et PCH.",
        "La TICPE perçue compense aussi d'autres transferts de compétences : après la recentralisation du RSA, la "
        "Seine-Saint-Denis perçoit encore environ 12,5 M€ par an de TICPE (contre 246 M€ en 2021).",
        "Le dispositif de compensation péréquée (DCP, frais de gestion de la taxe foncière transférés depuis 2014), "
        "les fonds de péréquation (droits de mutation, fonds de solidarité des départements) et les fonds de "
        "soutien exceptionnels ne sont pas isolés dans les comptes publiés : ils ne sont pas déduits.",
        "Les allocations des comptes (débit net de l'exercice) diffèrent des dépenses brutes de l'enquête Aide "
        "sociale de la DREES : les écarts sont publiés dans ecarts.json.",
    ],
}

# Collectivités : codes alignés sur ceux de la DREES (territoires/, beneficiaires.json)
SIREN_67A = {"226700011": "67", "226800019": "68", "200094332": "6AE"}
CTU_REGIONS = {"02": "972", "03": "973", "94": "20R"}
NOMS = {"6AE": "Collectivité européenne d'Alsace", "69": "Rhône (département avant 2015)",
        "69D": "Nouveau Rhône", "69M": "Métropole de Lyon", "20R": "Collectivité de Corse"}
DEPARTEMENTS_DE = {"6AE": ["67", "68"], "69D": ["69"], "69M": ["69"], "20R": ["2A", "2B"]}
PERIMETRES = {
    "6AE": "Collectivité européenne d'Alsace, depuis 2021 : compétences départementales du Bas-Rhin et du Haut-Rhin ; "
           "même série pour les départements 67 et 68, à ne pas additionner",
    "67": "Bas-Rhin, jusqu'en 2020 (code 67A et SIREN 226700011 dans la base de l'OFGL)",
    "68": "Haut-Rhin, jusqu'en 2020 (code 67A et SIREN 226800019 dans la base de l'OFGL)",
    "69": "département du Rhône avant la création de la Métropole de Lyon (jusqu'en 2014)",
    "69D": "Nouveau Rhône : département du Rhône hors Métropole de Lyon, depuis 2015",
    "69M": "Métropole de Lyon : compétences départementales sur son territoire, depuis 2015 (code 691 de l'OFGL)",
    "20R": "Collectivité de Corse, depuis 2018 : compétences départementales de la Corse-du-Sud et de la Haute-Corse "
           "(comptes publiés dans la base des régions de l'OFGL) ; même série pour 2A et 2B, à ne pas additionner",
    "2A": "Corse-du-Sud, jusqu'en 2017", "2B": "Haute-Corse, jusqu'en 2017",
    "972": "département de la Martinique jusqu'en 2015, collectivité territoriale de Martinique depuis 2016 (comptes "
           "publiés dans la base des régions de l'OFGL, TICPE régionale et départementale confondues)",
    "973": "département de la Guyane jusqu'en 2015, collectivité territoriale de Guyane depuis 2016 (comptes publiés "
           "dans la base des régions de l'OFGL, TICPE régionale et départementale confondues)",
    "75": "département de Paris jusqu'en 2018, Ville de Paris (commune et département) depuis 2019",
}
ANNEE_CTU = {"972": 2016, "973": 2016, "20R": 2018}
# Séries de la DREES : périmètres propres (la DREES publie aussi la Corse avant 2018 et 67, 68 après 2021)
NOMS_BENEF = {"6AE": "Collectivité européenne d'Alsace", "20R": "Corse", "69": "Rhône", "69D": "Nouveau Rhône",
              "69M": "Métropole de Lyon"}
PERIMETRES_BENEF = {
    "6AE": "Collectivité européenne d'Alsace, depuis 2021 ; la DREES publie aussi le Bas-Rhin (67) et le Haut-Rhin "
           "(68) : séries à ne pas additionner",
    "20R": "Corse : Collectivité de Corse depuis 2018 ; avant 2018, ensemble de la Corse-du-Sud et de la Haute-Corse "
           "publié par la DREES (code 20) ; à ne pas additionner avec 2A et 2B",
    "69": "Rhône : département du Rhône jusqu'en 2014 pour les aides aux personnes âgées et handicapées et l'aide "
          "sociale à l'enfance ; pour les allocataires du RSA, tout le territoire du Rhône, Métropole de Lyon comprise, "
          "toutes années",
    "69D": "Nouveau Rhône : département du Rhône hors Métropole de Lyon, depuis 2015",
    "69M": "Métropole de Lyon : compétences départementales sur son territoire, depuis 2015",
}

# --- Bénéficiaires (DREES) ---------------------------------------------------------------------------------------------

DEF_PA = "aides en cours au 31 décembre (une personne peut en cumuler plusieurs) ; APA : payées au titre de décembre"
SERIES = [
    # id, classeur, onglet, groupe, libellé, définition
    ("pa_aides", "paph", "Tab1-pa", "personnes_agees", "Aides sociales aux personnes âgées (ensemble)", DEF_PA),
    ("pa_aides_domicile", "paph", "Tab2-pa", "personnes_agees", "Aides sociales à domicile des personnes âgées",
     DEF_PA),
    ("pa_aides_accueil", "paph", "Tab3-pa", "personnes_agees", "Aides sociales à l'accueil des personnes âgées",
     DEF_PA),
    ("apa", "paph", "Tab4-pa", "personnes_agees", "Allocation personnalisée d'autonomie (APA), à domicile et en "
     "établissement", "bénéficiaires payés au titre de décembre"),
    ("apa_domicile", "paph", "Tab5-pa", "personnes_agees", "APA à domicile", "bénéficiaires payés au titre de "
     "décembre"),
    ("apa_etablissement", "paph", "Tab6-pa", "personnes_agees", "APA en établissement", "bénéficiaires payés au "
     "titre de décembre"),
    ("ash_pa", "paph", "Tab10-pa", "personnes_agees", "Aide sociale à l'hébergement (ASH) des personnes âgées en "
     "établissement", "bénéficiaires ayant un droit ouvert au 31 décembre"),
    ("pa_accueil_particuliers", "paph", "Tab11-pa", "personnes_agees", "Personnes âgées aidées pour un accueil chez "
     "des particuliers", "bénéficiaires ayant un droit ouvert au 31 décembre"),
    ("pa_aides_menageres", "paph", "Tab12-pa", "personnes_agees", "Personnes âgées bénéficiaires d'aides ménagères",
     "bénéficiaires ayant un droit ouvert au 31 décembre"),
    ("ph_aides", "paph", "Tab1-ph", "personnes_handicapees", "Aides sociales aux personnes handicapées (ensemble)",
     "aides en cours au 31 décembre (une personne peut en cumuler plusieurs)"),
    ("ph_aides_domicile", "paph", "Tab2-ph", "personnes_handicapees", "Aides sociales à domicile des personnes "
     "handicapées", "aides en cours au 31 décembre"),
    ("ph_aides_accueil", "paph", "Tab3-ph", "personnes_handicapees", "Aides sociales à l'accueil des personnes "
     "handicapées", "aides en cours au 31 décembre"),
    ("actp", "paph", "Tab4-ph", "personnes_handicapees", "Allocation compensatrice pour tierce personne (ACTP)",
     "bénéficiaires ayant un droit ouvert au 31 décembre"),
    ("pch", "paph", "Tab7-ph", "personnes_handicapees", "Prestation de compensation du handicap (PCH)",
     "bénéficiaires ayant un droit ouvert au 31 décembre"),
    ("pch_payes", "paph", "Tab7b-ph", "personnes_handicapees", "PCH, bénéficiaires payés", "bénéficiaires payés au "
     "titre de décembre"),
    ("ash_ph", "paph", "Tab8-ph", "personnes_handicapees", "Aide sociale à l'hébergement (ASH) des personnes "
     "handicapées en établissement", "bénéficiaires ayant un droit ouvert au 31 décembre"),
    ("ph_accueil_jour", "paph", "Tab9-ph", "personnes_handicapees", "Personnes handicapées aidées pour un accueil de "
     "jour en établissement", "bénéficiaires ayant un droit ouvert au 31 décembre"),
    ("ph_accueil_particuliers", "paph", "Tab10-ph", "personnes_handicapees", "Personnes handicapées aidées pour un "
     "accueil chez un particulier", "bénéficiaires ayant un droit ouvert au 31 décembre"),
    ("ph_aides_menageres", "paph", "Tab11-ph", "personnes_handicapees", "Personnes handicapées bénéficiaires d'aides "
     "ménagères ou d'auxiliaires de vie", "bénéficiaires ayant un droit ouvert au 31 décembre"),
    ("ase_accueillis", "ase", "Tab1-ase", "enfance", "Enfants accueillis à l'aide sociale à l'enfance (ASE)",
     "au 31 décembre : enfants confiés à l'ASE et placements directs par le juge"),
    ("ase_confies", "ase", "Tab2-ase", "enfance", "Enfants confiés à l'ASE", "au 31 décembre, sur décision "
     "administrative ou judiciaire"),
    ("ase_assistants_familiaux", "ase", "Tab3-ase", "enfance", "Enfants confiés à l'ASE accueillis par un assistant "
     "familial", "au 31 décembre"),
    ("ase_etablissements", "ase", "Tab4-ase", "enfance", "Enfants confiés à l'ASE accueillis en établissement",
     "au 31 décembre ; villages d'enfants compris depuis 2018"),
    ("ase_placements_directs", "ase", "Tab5-ase", "enfance", "Placements directs par le juge", "au 31 décembre"),
    ("ase_actions_educatives", "ase", "Tab6-ase", "enfance", "Bénéficiaires d'une action éducative (AED et AEMO)",
     "au 31 décembre"),
    ("ase_aed", "ase", "Tab7-ase", "enfance", "Aide éducative à domicile (AED)", "au 31 décembre"),
    ("ase_aemo", "ase", "Tab8-ase", "enfance", "Action éducative en milieu ouvert (AEMO)", "au 31 décembre"),
    ("ase_mesures_administratives", "ase", "Tab9-ase", "enfance", "Mesures administratives d'accueil à l'ASE",
     "bénéficiaires au 31 décembre"),
    ("ase_mesures_judiciaires", "ase", "Tab10-ase", "enfance", "Mesures judiciaires d'accueil à l'ASE (hors "
     "placements directs)", "bénéficiaires au 31 décembre"),
    ("rsa", "minima", "Tableau 11", "insertion", "Allocataires du RSA (RSA socle jusqu'en 2015)",
     "allocataires au 31 décembre, CAF et MSA, département de la caisse de gestion"),
]
GROUPES = {"personnes_agees": "Aide sociale aux personnes âgées", "personnes_handicapees": "Aide sociale aux "
           "personnes handicapées", "enfance": "Aide sociale à l'enfance", "insertion": "Revenu de solidarité active"}
CHAMPS = {"paph": "France métropolitaine et DROM, hors Mayotte",
          "ase": "France, Mayotte comprise à partir de 2015",
          "minima": "France ; Guadeloupe y compris Saint-Barthélemy et Saint-Martin"}
CODES_DREES = {"6EA": "6AE", "20": "20R"}
RUPTURES = {"rsa": "2016 : la CNAF a changé son système de production ; la DREES publie deux valeurs, la série reprend "
                   "celle du nouveau système, comparable aux années suivantes (l'autre valeur est dans "
                   "`rsa_2016_ancien_systeme`) ; jusqu'en 2015, RSA socle (le RSA activité est devenu la prime "
                   "d'activité en 2016)",
            "ash_pa": "rupture 2018-2019 : avant 2019, les bénéficiaires de l'ASH des personnes handicapées de 65 ans "
                      "ou plus du Pas-de-Calais étaient comptés parmi les personnes âgées (DREES)",
            "ash_ph": "rupture 2018-2019 dans le Pas-de-Calais (voir ash_pa)",
            "ase_etablissements": "depuis 2018, les villages d'enfants sont comptés parmi les établissements (DREES)"}

# --- Écarts -------------------------------------------------------------------------------------------------------------

# grandeur -> (clé comptes ou série, source, autre source, postes DREES 376 additionnés, lecture)
ECARTS_COMPTES = {
    "allocations_apa": (["apa"], "dépenses d'APA : comptes de l'exercice (débit net du compte 65114, OFGL) ; "
                                 "dépenses brutes déclarées par le département à l'enquête Aide sociale (DREES)"),
    "allocations_pch": (["pch", "actp"], "PCH et ACTP : comptes (débit net des comptes 651121 et 651122, OFGL) ; "
                                         "dépenses brutes de PCH et d'ACTP de l'enquête Aide sociale (DREES, deux "
                                         "postes d'une même source)"),
    "allocations_rsa": (["rsa_allocation"], "allocations du RSA : comptes (débit net des comptes 6515 et 6517, OFGL) ; "
                                            "dépenses brutes d'allocation de l'enquête Aide sociale (DREES)"),
}
LECTURES_ECARTS = {
    "allocations_apa": ECARTS_COMPTES["allocations_apa"][1],
    "allocations_pch": ECARTS_COMPTES["allocations_pch"][1],
    "allocations_rsa": ECARTS_COMPTES["allocations_rsa"][1],
    "beneficiaires_apa_domicile": "bénéficiaires de l'APA à domicile payés au titre de décembre : séries longues "
                                  "de l'enquête Aide sociale (DREES) ; jeu « APA et PCH - Montants versés » de la "
                                  "DREES (territoires/) ; même producteur, deux publications révisées à des dates "
                                  "différentes",
    "beneficiaires_pch_payes": "bénéficiaires de la PCH payés au titre de décembre : séries longues de l'enquête Aide "
                               "sociale (DREES) ; jeu « APA et PCH - Montants versés » (territoires/)",
    "beneficiaires_rsa": "allocataires du RSA au 31 décembre, CAF et MSA (DREES) ; foyers payés par les CAF au titre "
                         "de décembre, champ CAF (CNAF, prestations/)",
}
SOURCES_ECARTS = {
    "allocations_apa": ("ofgl_departements", "drees_376"), "allocations_pch": ("ofgl_departements", "drees_376"),
    "allocations_rsa": ("ofgl_departements", "drees_376"),
    "beneficiaires_apa_domicile": ("drees_paph", "drees_apa_pch"),
    "beneficiaires_pch_payes": ("drees_paph", "drees_apa_pch"),
    "beneficiaires_rsa": ("drees_minima", "cnaf_s_ben_dep"),
}
NOMS_SOURCES_ECARTS = {
    "ofgl_departements": "OFGL, comptes consolidés des départements (comptes.json)",
    "drees_376": "DREES, dépenses d'aide sociale départementale, séries longues (territoires/<dep>.json)",
    "drees_paph": "DREES, bénéficiaires de l'aide sociale aux personnes âgées ou handicapées (beneficiaires.json)",
    "drees_apa_pch": "DREES, « APA et PCH - Montants versés » (territoires/<dep>.json)",
    "drees_minima": "DREES, minima sociaux par département, tableau 11 (beneficiaires.json)",
    "cnaf_s_ben_dep": "CNAF, allocataires par département, champ CAF (prestations/departements/<annee>.json)",
}

METHODE = {
    "comptes": "agrégats de l'OFGL repris tels quels, lus par SIREN (le code 67A de l'OFGL porte jusqu'en 2020 deux "
               "lignes par exercice, Bas-Rhin et Haut-Rhin) ; euros arrondis à l'euro ; euros par habitant = montant / "
               "population totale publiée par l'OFGL pour l'exercice, 2 décimales ; collectivités uniques (Martinique, "
               "Guyane, Corse) lues dans la base des régions de l'OFGL",
    "beneficiaires": "séries longues de la DREES reprises telles quelles ; collectivités désignées par les codes de la "
                     "DREES (6EA lu 6AE, 20 lu 20R) ; une cellule vide ou « - » reste null, un 0 publié reste 0 ; "
                     "totaux estimés publiés par la DREES repris à part, jamais recalculés",
    "reste_a_charge": RAC_DEFINITION["methode"] + " ; formules : " + "; ".join(
        f"{k} = {v}" for k, v in RAC_DEFINITION["formules"].items()),
    "ecarts": "écart = valeur de la source moins valeur de l'autre source ; part = écart / autre valeur × 100, une "
              "décimale ; seules les collectivités de même périmètre dans les deux sources sont comparées (Bas-Rhin "
              "et Haut-Rhin jusqu'en 2020, Collectivité européenne d'Alsace depuis 2021 ; Rhône avant 2015 ; Nouveau "
              "Rhône et Métropole de Lyon depuis 2015) ; écart national : somme des collectivités des comptes hors "
              "Mayotte, face au total estimé de la DREES (France métropolitaine et DROM, hors Mayotte)",
}
LIMITES = [
    "Mayotte est hors du champ des séries de la DREES sur les personnes âgées et handicapées ; ses comptes sont "
    "publiés.",
    "Les dépenses d'aide sociale à l'enfance et les autres postes ne sont pas isolés dans les comptes publiés par "
    "l'OFGL : ils sont lisibles par poste dans territoires/<dep>.json (enquête Aide sociale de la DREES) ; les frais "
    "d'hébergement des comptes regroupent personnes âgées, personnes handicapées et enfance.",
    "Dotations de la CNSA, TICPE, dispositif de compensation péréquée : voir reste_a_charge.limites.",
    "Données provisoires 2025 de la DREES (bénéficiaires) publiées dans des classeurs annuels séparés : non reprises.",
    "Les séries longues de la DREES sont révisées chaque année (corrections de départements listées par la DREES) : "
    "une valeur peut différer d'une publication antérieure.",
    "L'adresse des séries longues de la DREES change à chaque millésime (années dans le nom de la pièce jointe) : "
    "l'entrée de collecte/catalogue.json est à mettre à jour ; une collecte en échec est signalée dans "
    "mise_a_jour.json.",
]
REGLE = ("agrégats publiés seulement, aucune personne nommée ; une valeur absente de la source reste null, jamais 0 ; "
         "le reste à charge est un calcul du site, publié avec sa formule et ses limites ; deux sources ne sont "
         "jamais additionnées, leurs écarts sont publiés ; les dépenses de la DREES par poste restent dans "
         "territoires/ et les foyers du RSA des CAF dans prestations/ : ce module y renvoie sans les recopier")
ORDRE = {"cles": ["code"], "regle": "collectivités par code croissant, années croissantes ; écarts par grandeur, "
                                    "code, année"}


# --- Utilitaires -------------------------------------------------------------------------------------------------------

def propre(v) -> str:
    if v is None:
        return ""
    s = unicodedata.normalize("NFC", str(v)).replace("\xa0", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def nombre(v):
    """Nombre publié, ou None (cellule vide, « - », « nd », texte)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if v != v else v
    s = propre(v).replace(" ", "").replace(",", ".")
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def entier(v):
    n = nombre(v)
    return None if n is None else int(round(n))


def marque(v):
    """Chaîne publiée à la place d'une valeur (« - », « nd »...), sinon None."""
    if v is None or isinstance(v, (int, float)):
        return None
    s = propre(v)
    return s if s and nombre(s) is None else None


def euros(v):
    return None if v is None else int(round(v))


def par_habitant(v, pop):
    return None if v is None or not pop else round(v / pop, 2)


def ecart(source, valeur, autre_source, autre_valeur, **cles) -> dict | None:
    """Écart publié (jamais une correction) : None si une des deux valeurs manque."""
    if valeur is None or autre_valeur is None:
        return None
    e = {**cles, "source": source, "valeur": valeur, "autre_source": autre_source, "autre_valeur": autre_valeur,
         "ecart": valeur - autre_valeur,
         "ecart_pct": round((valeur - autre_valeur) / autre_valeur * 100, 1) if autre_valeur else None}
    return e


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets ({n}) : découper")
    tmp = path.with_suffix(".part")
    tmp.write_text(texte + "\n", encoding="utf-8")
    tmp.replace(path)
    return n


def charger(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def chemin(cle: str) -> Path:
    return LAKE / SOURCES[cle]["fichier"]


def departements_de(code: str) -> list[str]:
    return DEPARTEMENTS_DE.get(code, [code])


# --- Lecture : comptes ---------------------------------------------------------------------------------------------------

def code_comptes(dep_code: str, siren: str, annee: int) -> str:
    """Code de collectivité publié (codes de la DREES) pour une ligne de la base des départements de l'OFGL."""
    if dep_code == "67A":
        if siren not in SIREN_67A:
            raise SystemExit(f"OFGL : SIREN inattendu sous le code 67A ({siren}) : le jeu a changé de forme")
        return SIREN_67A[siren]
    if dep_code == "691":
        return "69M"
    if dep_code == "69":
        return "69" if annee < 2015 else "69D"
    return dep_code


def lire_comptes() -> tuple[dict, list[int]]:
    """-> ({code: {nom, sirens, annees: {annee: {colonne: montant}}, population: {annee: ptot}}}, années)."""
    import duckdb
    con = duckdb.connect()
    libelles = [lib for _, lib, _ in AGREGATS]
    marques = ",".join("?" * len(libelles))
    out: dict = {}

    def ajouter(code, nom, siren, annee, agregat, montant, ptot):
        c = out.setdefault(code, {"nom": nom, "sirens": set(), "annees": defaultdict(dict), "population": {}})
        c["sirens"].add(siren)
        c["nom"] = nom  # nom du dernier exercice (lignes triées par année)
        if agregat is not None and montant is not None:
            c["annees"][annee][PAR_LIBELLE[agregat]] = float(montant)
        if ptot:
            c["population"][annee] = int(ptot)

    f = chemin("ofgl_departements")
    if not f.exists():
        raise SystemExit(f"{f} absent (python pipeline/solidarites_departements.py collecter)")
    lignes = con.execute(
        f"select dep_code, dep_name, siren, year(exer)::int a, agregat, montant, ptot from '{f}' "
        f"where agregat in ({marques}) order by a, dep_code, siren, agregat", libelles).fetchall()
    # population : présente sur toutes les lignes, y compris quand aucun agrégat repris n'est publié
    pops = con.execute(f"select dep_code, siren, year(exer)::int a, max(ptot) from '{f}' group by all "
                       f"order by a, dep_code, siren").fetchall()
    for dep, siren, a, p in pops:
        ajouter(code_comptes(dep, str(siren), a), None, str(siren), a, None, None, p)
    for dep, nom, siren, a, ag, m, p in lignes:
        ajouter(code_comptes(dep, str(siren), a), propre(nom), str(siren), a, ag, m, p)
    f = chemin("ofgl_regions")
    if f.exists():
        codes = list(CTU_REGIONS)
        for reg, nom, siren, a, ag, m, p in con.execute(
                f"select reg_code, reg_name, siren, year(exer)::int a, agregat, montant, ptot from '{f}' "
                f"where categ = 'CTU' and reg_code in ({','.join('?' * len(codes))}) "
                f"order by a, reg_code, siren, agregat", codes).fetchall():
            ajouter(CTU_REGIONS[reg], propre(nom), str(siren), a, ag if ag in PAR_LIBELLE else None, m, p)
    annees = sorted({a for c in out.values() for a in c["annees"]} | {a for c in out.values() for a in c["population"]})
    for code, c in out.items():
        if c["nom"] is None:
            c["nom"] = code
    return out, annees


def lire_formules() -> dict:
    """{colonne: [{collectivites, nomenclature, formule, annees}]} d'après la méthodologie de l'OFGL."""
    f = chemin("ofgl_formules")
    if not f.exists():
        return {}
    import duckdb
    con = duckdb.connect()
    noms = [d[0] for d in con.execute(f"select * from '{f}' limit 0").description]
    col_nom = "nomenclatures" if "nomenclatures" in noms else "nomenclature"
    out = defaultdict(lambda: defaultdict(set))
    for ag, typ, an, nomen, formule in con.execute(
            f"select agregat, type_collectivite, annee, {col_nom}, formule_avec_libelle from '{f}' "
            f"where type_collectivite in ('Départements', 'Régions') order by all").fetchall():
        if ag not in PAR_LIBELLE or not formule:
            continue
        out[PAR_LIBELLE[ag]][(propre(typ), propre(nomen), propre(formule))].add(int(str(an)[:4]))
    return {col: [{"collectivites": t, "nomenclature": n, "formule": fo, "annees": sorted(ans)}
                  for (t, n, fo), ans in sorted(v.items())] for col, v in sorted(out.items())}


# --- Lecture : bénéficiaires --------------------------------------------------------------------------------------------

def _annees_entete(entete) -> dict[int, int]:
    """index de colonne -> année (cellules « 2002 », 2002, « 2010 (2) »)."""
    out = {}
    for i, c in enumerate(entete):
        s = propre(c)
        m = re.fullmatch(r"((?:19|20)\d{2})(?:\s*\(\d+\))?", s)
        if m:
            out[i] = int(m.group(1))
    return out


def _cle_total(libelle: str) -> str | None:
    s = propre(libelle)
    if not s.upper().startswith("TOTAL"):
        return None
    if "DROM" in s:
        return "drom"
    if "métropolitaine" in s and "DROM" not in s and "entière" not in s:
        return "metropole"
    return "france"


def lire_onglet_drees(ws) -> dict:
    """Onglet d'une série longue de la DREES : {titre, annees, valeurs: {code: {annee: v}}, noms, totaux, marques}."""
    rows = list(ws.iter_rows(values_only=True))
    titre = next((propre(c) for c in rows[0] if c is not None), "")
    hi = next((i for i, r in enumerate(rows) if r and propre(r[0]) == "Code région"), None)
    if hi is None:
        raise SystemExit(f"DREES {ws.title} : en-tête « Code région » introuvable (le classeur a changé de forme)")
    cols = _annees_entete(rows[hi])
    valeurs, noms, totaux, marques = {}, {}, {}, defaultdict(int)
    for r in rows[hi + 1:]:
        tete = propre(r[0]) if r else ""
        if tete.upper().startswith("TOTAL"):
            cle = _cle_total(tete)
            if cle:
                totaux[cle] = {a: entier(r[j]) for j, a in cols.items() if j < len(r)}
            continue
        if not r or (r[1] is None and r[2] is None):
            if totaux:
                break
            continue
        code = propre(r[1])
        if not re.fullmatch(r"\d{2,3}|2A|2B|6AE|6EA|69D|69M", code):
            if totaux:
                break  # bloc suivant (par région)
            continue
        code = CODES_DREES.get(code, code)
        noms[code] = propre(r[2])
        v = {}
        for j, a in cols.items():
            x = r[j] if j < len(r) else None
            v[a] = entier(x)
            if marque(x):
                marques[marque(x)] += 1
        valeurs[code] = v
    if len(valeurs) < 95:
        raise SystemExit(f"DREES {ws.title} : {len(valeurs)} collectivités lues (le classeur a changé de forme)")
    return {"titre": titre, "annees": sorted(set(cols.values())), "valeurs": valeurs, "noms": noms,
            "totaux": totaux, "marques": dict(marques)}


def lire_rsa_drees(wb) -> dict:
    """Tableau 11 des minima sociaux : allocataires du RSA par département (2016 : valeur du nouveau système)."""
    rows = list(wb["Tableau 11"].iter_rows(values_only=True))
    titre = next((propre(c) for c in rows[0] if c is not None), "")
    hi = next((i for i, r in enumerate(rows) if r and any(isinstance(c, int) and 2009 <= c <= 2100 for c in r)), None)
    if hi is None:
        raise SystemExit("DREES minima tableau 11 : ligne des années introuvable")
    vus, cols, ancien_2016 = set(), {}, None
    for j, c in enumerate(rows[hi]):
        m = re.fullmatch(r"((?:19|20)\d{2})(?:\s*\((\d+)\))?", propre(c))
        if not m:
            continue
        a = int(m.group(1))
        if a in vus:  # année publiée deux fois : la dernière colonne (nouveau système) l'emporte
            ancien_2016 = cols[a] if a == 2016 else ancien_2016
        vus.add(a)
        cols[a] = j
    valeurs, noms, totaux, anciens, marques = {}, {}, {}, {}, defaultdict(int)
    for r in rows[hi + 1:]:
        code, lib = propre(r[1]) if len(r) > 1 else "", propre(r[2]) if len(r) > 2 else ""
        if not code and lib in ("France métropolitaine", "DOM", "France"):
            totaux[{"France métropolitaine": "metropole", "DOM": "drom", "France": "france"}[lib]] = {
                a: entier(r[j]) for a, j in cols.items()}
            continue
        if not re.fullmatch(r"\d{2,3}|2A|2B", code):
            if totaux.get("france"):
                break
            continue
        if len(code) == 1:
            code = "0" + code
        noms[code] = re.sub(r"\s*\(\d+\)$", "", lib)
        valeurs[code] = {a: entier(r[j]) for a, j in sorted(cols.items())}
        for a, j in cols.items():
            if marque(r[j]):
                marques[marque(r[j])] += 1
        if ancien_2016 is not None:
            anciens[code] = entier(r[ancien_2016])
    if len(valeurs) < 95:
        raise SystemExit(f"DREES minima tableau 11 : {len(valeurs)} départements lus")
    return {"titre": titre, "annees": sorted(cols), "valeurs": valeurs, "noms": noms, "totaux": totaux,
            "marques": dict(marques), "ancien_2016": anciens}


def lire_beneficiaires() -> dict:
    """{serie: {titre, annees, valeurs, noms, totaux, marques, classeur, onglet}} ; série absente si classeur absent."""
    import openpyxl
    classeurs = {"paph": chemin("drees_paph"), "ase": chemin("drees_ase"), "minima": chemin("drees_minima")}
    ouverts = {}
    out = {}
    try:
        for sid, cl, onglet, *_ in SERIES:
            if not classeurs[cl].exists():
                continue
            if cl not in ouverts:
                ouverts[cl] = openpyxl.load_workbook(classeurs[cl], read_only=True, data_only=True)
            wb = ouverts[cl]
            x = lire_rsa_drees(wb) if cl == "minima" else lire_onglet_drees(wb[onglet])
            out[sid] = {**x, "classeur": cl, "onglet": onglet}
    finally:
        for wb in ouverts.values():
            wb.close()
    return out


# --- Lecture : sorties publiées (lecture seule) -----------------------------------------------------------------------

def lire_territoires() -> dict:
    """{code: {postes 376 brutes utiles, apa_domicile, pch}} et totaux France de la DREES, d'après territoires/."""
    idx = charger(SITE / "territoires" / "index.json")
    if not idx:
        return {"collectivites": {}, "totaux_france": {}, "departements": []}
    coll = {}
    for d in idx.get("departements", []):
        doc = charger(SITE / d["fichier"]) if d.get("fichier") else None
        for c in ((doc or {}).get("aide_sociale") or {}).get("collectivites", []):
            if c["code"] in coll:
                continue
            postes = {p: (c.get("postes", {}).get(p, {}).get("brute") or {}).get("eur", {})
                      for p in ("apa", "pch", "actp", "rsa_allocation")}
            coll[c["code"]] = {"postes": postes,
                               "apa_domicile": {a: x.get("beneficiaires_decembre")
                                                for a, x in (c.get("apa_domicile") or {}).items()},
                               "pch_payes": {a: x.get("personnes_payees_decembre")
                                             for a, x in (c.get("pch") or {}).items()}}
    france = ((idx.get("totaux") or {}).get("aide_sociale_drees") or {}).get("france") or {}
    return {"collectivites": coll, "totaux_france": france,
            "departements": [{"code": d["code"], "nom": d["nom"]} for d in idx.get("departements", [])]}


def lire_prestations() -> dict:
    idx = charger(SITE / "prestations" / "index.json")
    if not idx:
        return {"rsa_recentralise": {}, "fichiers": {}, "foyers_rsa": {}}
    fichiers = (idx.get("fichiers") or {}).get("departements") or {}
    foyers = {}
    for an, rel in sorted(fichiers.items()):
        doc = charger(SITE / rel) or {}
        for code, x in (doc.get("departements") or {}).items():
            v = x.get("rsa")
            if isinstance(v, list) and v and isinstance(v[0], (int, float)):
                foyers.setdefault(code, {})[int(an)] = int(v[0])
    return {"rsa_recentralise": (idx.get("couverture_departementale") or {}).get("rsa_recentralise") or {},
            "fichiers": fichiers, "foyers_rsa": foyers}


def referentiel(terr: dict) -> list[dict]:
    """Départements du site (codes de local/geo) : depuis territoires/index.json, sinon local/geo."""
    if terr["departements"]:
        return sorted(terr["departements"], key=lambda d: d["code"])
    deps = []
    for f in sorted((SITE / "local" / "geo").glob("*.json")):
        g = charger(f) or {}
        deps.append({"code": f.stem, "nom": (g.get("departement") or {}).get("nom") or f.stem})
    return deps


# --- Calculs ----------------------------------------------------------------------------------------------------------

def financeur_rsa(code: str, annee: int, recentralise: dict) -> str:
    r = recentralise.get(code)
    if not r:
        return "departement"
    if annee >= r["premiere_annee_entiere"]:
        return "etat"
    debut = r.get("debut") or ""
    return "departement_puis_etat" if str(annee) in debut else "departement"


def reste_a_charge(vals: dict, code: str, annee: int, recentralise: dict) -> dict:
    """{rsa, apa_pch} : allocations moins recettes rattachées ; null si une composante manque ou n'est pas comparable."""
    out = {}
    for cle, f in RESTE_A_CHARGE.items():
        composantes = f["allocations"] + f["recettes"]
        if any(vals.get(c) is None for c in composantes):
            out[cle] = None
            continue
        if cle == "rsa" and (financeur_rsa(code, annee, recentralise) == "etat"
                             or annee >= ANNEE_CTU.get(code, 9999)):
            out[cle] = None
            continue
        out[cle] = euros(sum(vals[c] for c in f["allocations"]) - sum(vals[c] for c in f["recettes"]))
    return out


def code_drees_pour(code: str, annee: int) -> str | None:
    """Collectivité de la DREES de même périmètre qu'une collectivité des comptes, pour l'exercice."""
    if code in ("67", "68") and annee >= 2021:
        return None
    if code == "6AE" and annee < 2021:
        return None
    if code == "69" and annee >= 2015:
        return None
    if code in ("2A", "2B") and annee >= 2018:
        return None
    return code


# --- Production -------------------------------------------------------------------------------------------------------

def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    comptes_brut, annees_c = lire_comptes()
    formules = lire_formules()
    benef = lire_beneficiaires()
    terr = lire_territoires()
    prest = lire_prestations()
    deps = referentiel(terr)
    recentralise = prest["rsa_recentralise"]
    date = date_sources(AXE, "collectivites")
    noms_site = {d["code"]: d["nom"] for d in deps}
    annees_s = [str(a) for a in annees_c]
    manifeste = charger(LAKE / "manifest.json") or {}

    # --- comptes.json ---
    collectivites = {}
    for code in sorted(comptes_brut):
        c = comptes_brut[code]
        eur, eur_hab, rac, fin = {}, {}, {}, {}
        for a in sorted(set(c["annees"]) | set(c["population"])):
            vals = c["annees"].get(a, {})
            ligne = [euros(vals.get(k)) for k in COLONNES]
            pop = c["population"].get(a)
            eur[str(a)] = ligne
            eur_hab[str(a)] = [par_habitant(v, pop) for v in ligne]
            r = reste_a_charge({k: vals.get(k) for k in COLONNES}, code, a, recentralise)
            rac[str(a)] = [r["rsa"], r["apa_pch"]]
            fin[str(a)] = financeur_rsa(code, a, recentralise)
        x = {"nom": NOMS.get(code) or noms_site.get(code) or c["nom"], "departements": departements_de(code),
             "sirens": sorted(c["sirens"]), "population": {str(a): p for a, p in sorted(c["population"].items())},
             "eur": eur, "eur_hab": eur_hab, "reste_a_charge_calcule_eur": rac}
        if any(v != "departement" for v in fin.values()):
            x["financeur_rsa"] = fin
        if code in PERIMETRES:
            x["perimetre"] = PERIMETRES[code]
        collectivites[code] = x
    doc_comptes = {
        "millesime": f"Comptes {annees_c[0]} à {annees_c[-1]} (exercices clos, comptes de gestion)",
        "source": SOURCES["ofgl_departements"]["titre"] + " ; " + SOURCES["ofgl_regions"]["titre"],
        "unite": "eur : euros ; eur_hab : euros par habitant = eur / population totale de l'exercice (OFGL)",
        "date_sources": date,
        "annees": annees_s,
        "colonnes": COLONNES,
        "roles": {k: r for k, _, r in AGREGATS},
        "libelles_ofgl": {k: lib for k, lib, _ in AGREGATS},
        "definitions": DEFINITIONS_COMPTES,
        "formules_ofgl": formules,
        "lecture": LECTURE_COMPTES,
        "colonnes_reste_a_charge": list(RESTE_A_CHARGE),
        "reste_a_charge": RAC_DEFINITION,
        "format": "collectivites.<code>.eur.<annee> et eur_hab.<annee> : valeurs alignées sur `colonnes` ; "
                  "reste_a_charge_calcule_eur.<annee> : valeurs alignées sur `colonnes_reste_a_charge` ; null = "
                  "agrégat absent de la source pour l'exercice ou calcul impossible",
        "financeur_rsa": "departement, etat (RSA recentralisé, premier exercice entier) ou departement_puis_etat "
                         "(année du transfert) ; absent quand le département finance le RSA sur toute la période",
        "collectivites": collectivites,
        "regle": REGLE,
        "ordre": ORDRE,
    }

    # --- beneficiaires.json ---
    series_doc, coll_b, totaux_b = [], {}, {}
    for sid, cl, onglet, groupe, libelle, definition in SERIES:
        s = benef.get(sid)
        if not s:
            continue
        ans = s["annees"]
        d = {"id": sid, "groupe": groupe, "libelle": libelle, "definition": definition, "titre_source": s["titre"],
             "source": {"paph": "drees_paph", "ase": "drees_ase", "minima": "drees_minima"}[cl], "onglet": onglet,
             "champ": CHAMPS[cl], "annees": ans}
        if sid in RUPTURES:
            d["rupture"] = RUPTURES[sid]
        if s["marques"]:
            d["marques_source"] = dict(sorted(s["marques"].items()))
        series_doc.append(d)
        for code, v in s["valeurs"].items():
            x = coll_b.setdefault(code, {"nom": s["noms"].get(code), "departements": departements_de(code),
                                         "valeurs": {}})
            x["valeurs"][sid] = [v.get(a) for a in ans]
        for z, v in s["totaux"].items():
            totaux_b.setdefault(z, {})[sid] = [v.get(a) for a in ans]
    for code, x in coll_b.items():
        x["nom"] = NOMS_BENEF.get(code) or noms_site.get(code) or x["nom"] or code
        if code in PERIMETRES_BENEF:
            x["perimetre"] = PERIMETRES_BENEF[code]
        if code in benef.get("rsa", {}).get("ancien_2016", {}):
            x["rsa_2016_ancien_systeme"] = benef["rsa"]["ancien_2016"][code]
    annees_b = sorted({a for s in series_doc for a in s["annees"]})
    doc_benef = {
        "millesime": f"Bénéficiaires {annees_b[0]} à {annees_b[-1]} (fin d'année)" if annees_b else "aucune série",
        "source": " ; ".join(SOURCES[k]["titre"] for k in ("drees_paph", "drees_ase", "drees_minima")),
        "unite": "nombre de bénéficiaires, d'aides ou d'allocataires (voir series[].definition)",
        "date_sources": date,
        "groupes": GROUPES,
        "series": series_doc,
        "format": "collectivites.<code>.valeurs.<serie> : nombres alignés sur `series[].annees` de la série ; null = "
                  "non publié par la DREES ; totaux.<zone>.<serie> : totaux estimés publiés par la DREES (zone : "
                  "france, metropole, drom ; champ de la série)",
        "collectivites": {k: coll_b[k] for k in sorted(coll_b)},
        "totaux": {z: dict(sorted(v.items())) for z, v in sorted(totaux_b.items())},
        "regle": "séries de la DREES reprises telles quelles ; les totaux sont ceux publiés par la DREES (estimés pour "
                 "les collectivités non répondantes), jamais recalculés ; Alsace et Corse publiées au niveau de la "
                 "collectivité unique et, selon les années, des départements : séries à ne pas additionner",
        "ordre": ORDRE,
    }

    # --- écarts ---
    lignes_ecarts = []
    tcoll = terr["collectivites"]
    for code in sorted(comptes_brut):
        c = comptes_brut[code]
        for a in sorted(c["annees"]):
            cd = code_drees_pour(code, a)
            if cd is None or cd not in tcoll:
                continue
            for g, (postes, _) in ECARTS_COMPTES.items():
                vals = [tcoll[cd]["postes"].get(p, {}).get(str(a)) for p in postes]
                autre = None if any(v is None for v in vals) else sum(vals)
                e = ecart("ofgl_departements", euros(c["annees"][a].get(g)), "drees_376", autre)
                if e:
                    lignes_ecarts.append([g, code, a, e["valeur"], e["autre_valeur"], e["ecart"], e["ecart_pct"]])
    for sid, g in (("apa_domicile", "beneficiaires_apa_domicile"), ("pch_payes", "beneficiaires_pch_payes")):
        s = benef.get(sid)
        if not s:
            continue
        for code in sorted(s["valeurs"]):
            autre = tcoll.get(code, {}).get(sid, {})
            for a in s["annees"]:
                e = ecart("drees_paph", s["valeurs"][code].get(a), "drees_apa_pch", autre.get(str(a)))
                if e:
                    lignes_ecarts.append([g, code, a, e["valeur"], e["autre_valeur"], e["ecart"], e["ecart_pct"]])
    s = benef.get("rsa")
    if s:
        for code in sorted(s["valeurs"]):
            for a in s["annees"]:
                e = ecart("drees_minima", s["valeurs"][code].get(a), "cnaf_s_ben_dep",
                          prest["foyers_rsa"].get(code, {}).get(a))
                if e:
                    lignes_ecarts.append(["beneficiaires_rsa", code, a, e["valeur"], e["autre_valeur"], e["ecart"],
                                          e["ecart_pct"]])
    lignes_ecarts.sort(key=lambda l: (l[0], l[1], l[2]))
    par_grandeur = defaultdict(int)
    for l in lignes_ecarts:
        par_grandeur[l[0]] += 1
    doc_ecarts = {
        "millesime": f"Comptes {annees_c[0]} à {annees_c[-1]} ; bénéficiaires {annees_b[0] if annees_b else ''} à "
                     f"{annees_b[-1] if annees_b else ''}",
        "source": "comptes.json et beneficiaires.json (ce module) face à territoires/<dep>.json (DREES) et "
                  "prestations/departements/<annee>.json (CNAF)",
        "unite": "euros (allocations) ; nombre de bénéficiaires ou d'allocataires",
        "date_sources": date,
        "colonnes": ["grandeur", "code", "annee", "valeur", "autre_valeur", "ecart", "ecart_pct"],
        "grandeurs": {g: {"source": SOURCES_ECARTS[g][0], "autre_source": SOURCES_ECARTS[g][1],
                          "lecture_ecart": LECTURES_ECARTS[g], "lignes": par_grandeur.get(g, 0)}
                      for g in LECTURES_ECARTS},
        "sources_ecarts": NOMS_SOURCES_ECARTS,
        "methode": METHODE["ecarts"],
        "lignes": lignes_ecarts,
        "regle": "écarts publiés tels quels, jamais corrigés ni tranchés ; une ligne n'est écrite que si les deux "
                 "valeurs sont publiées",
        "ordre": {"cles": ["grandeur", "code", "annee"], "regle": "grandeur, code de collectivité, année croissants"},
    }

    # --- totaux nationaux et écarts nationaux ---
    totaux = {}
    for a in annees_c:
        t = {"collectivites": 0}
        sommes = {k: [0.0, 0] for k in COLONNES}
        for code in sorted(comptes_brut):
            vals = comptes_brut[code]["annees"].get(a)
            if not vals:
                continue
            t["collectivites"] += 1
            for k in COLONNES:
                if vals.get(k) is not None:
                    sommes[k][0] += vals[k]
                    sommes[k][1] += 1
        t["eur"] = {k: (euros(v) if n else None) for k, (v, n) in sommes.items()}
        t["collectivites_par_colonne"] = {k: n for k, (v, n) in sommes.items()}
        rac = {}
        for cle, f in RESTE_A_CHARGE.items():
            m, n, alloc, rec = 0, 0, 0.0, 0.0
            for code in sorted(collectivites):
                v = collectivites[code]["reste_a_charge_calcule_eur"].get(str(a))
                if v is None or v[list(RESTE_A_CHARGE).index(cle)] is None:
                    continue
                vals = comptes_brut[code]["annees"][a]
                m += v[list(RESTE_A_CHARGE).index(cle)]
                n += 1
                alloc += sum(vals[c] for c in f["allocations"])
                rec += sum(vals[c] for c in f["recettes"])
            rac[cle] = {"montant_eur": m if n else None, "collectivites": n, "allocations_eur": euros(alloc) if n
                        else None, "recettes_eur": euros(rec) if n else None,
                        "part_couverte_pct": round(rec / alloc * 100, 1) if n and alloc else None}
        t["reste_a_charge_calcule"] = rac
        totaux[str(a)] = t
    ecarts_nat = []
    france = terr["totaux_france"]
    for g, (postes, lecture) in ECARTS_COMPTES.items():
        for a in annees_c:
            vals = [(france.get(f"{p}.brute") or {}).get(str(a)) for p in postes]
            if any(v is None for v in vals):
                continue
            somme = [comptes_brut[c]["annees"].get(a, {}).get(g) for c in sorted(comptes_brut) if c != "976"]
            somme = [v for v in somme if v is not None]
            if not somme:
                continue
            e = ecart("ofgl_departements", euros(sum(somme)), "drees_376", sum(vals), annee=a, grandeur=g)
            e["lecture_ecart"] = (lecture + " ; somme des collectivités des comptes hors Mayotte ; total estimé par "
                                  "la DREES (France métropolitaine et DROM, hors Mayotte), qui complète les "
                                  "collectivités non répondantes")
            ecarts_nat.append(e)

    # --- index.json ---
    par_dep = []
    for d in deps:
        dep = d["code"]
        ccomptes = sorted(k for k, x in collectivites.items() if dep in x["departements"])
        cbenef = sorted(k for k, x in coll_b.items() if dep in x["departements"])
        liens = {}
        if (SITE / "territoires" / f"{dep}.json").exists():
            liens["depenses_drees_par_poste"] = f"territoires/{dep}.json"
        par_dep.append({"code": dep, "nom": d["nom"], "comptes": ccomptes, "beneficiaires": cbenef, "liens": liens})
    sources = {}
    for k, s in sorted(SOURCES.items()):
        x = {kk: vv for kk, vv in sorted(s.items()) if kk != "fichier"}
        if s.get("fichier"):
            x["entrepot"] = "data/lake/" + s["fichier"]
        sid = s.get("id_catalogue")
        if sid:
            x["collecte_le"] = (manifeste.get(sid, {}).get("collecte_le") or "")[:10] or None
        sources[k] = x
    inaccessibles = list(INACCESSIBLES)
    for k, s in sorted(SOURCES.items()):
        sid = s.get("id_catalogue")
        if sid and not chemin(k).exists():
            inaccessibles.append({"source": k, "constat_le": date,
                                  "motif": (manifeste.get(sid, {}).get("erreur") or "absente de l'entrepôt")[:300]})
    if not terr["collectivites"]:
        inaccessibles.append({"source": "territoires", "constat_le": date,
                              "motif": "site/data/territoires absent : écarts avec la DREES (dépenses) non calculés"})
    if not prest["foyers_rsa"]:
        inaccessibles.append({"source": "prestations", "constat_le": date,
                              "motif": "site/data/prestations absent : financeur du RSA et écarts avec la CNAF non "
                                       "calculés"})
    index = {
        "millesime": f"Comptes {annees_c[0]} à {annees_c[-1]} (OFGL) ; bénéficiaires "
                     f"{annees_b[0] if annees_b else ''} à {annees_b[-1] if annees_b else ''} (DREES)",
        "source": "OFGL (comptes consolidés des départements et des collectivités uniques, balances DGFiP) ; DREES "
                  "(enquête Aide sociale, minima sociaux) ; liens vers territoires/ (dépenses de la DREES par poste), "
                  "prestations/ (foyers du RSA des CAF) et local/ (budgets)",
        "unite": "euros ; euros par habitant ; nombre de bénéficiaires",
        "date_sources": date,
        "presentation": "Ce que les départements versent au titre des allocations individuelles de solidarité (RSA, "
                        "APA, PCH) d'après leurs comptes, les recettes que ces comptes rattachent à ces allocations "
                        "(TICPE, FMDI, dotations de la CNSA), un reste à charge calculé par le site, et le nombre de "
                        "bénéficiaires de l'aide sociale départementale publié par la DREES. Les dépenses par poste "
                        "de l'enquête Aide sociale (aide sociale à l'enfance comprise) sont dans territoires/ ; les "
                        "foyers du RSA payés par les CAF dans prestations/.",
        "annees_comptes": annees_c,
        "annees_beneficiaires": annees_b,
        "fichiers": {"comptes": f"{AXE}/comptes.json", "beneficiaires": f"{AXE}/beneficiaires.json",
                     "ecarts": f"{AXE}/ecarts.json"},
        "departements": par_dep,
        "collectivites": [{"code": k, "nom": (collectivites.get(k) or coll_b[k])["nom"],
                           "departements": departements_de(k),
                           "comptes": k in collectivites, "beneficiaires": k in coll_b,
                           **({"perimetre": PERIMETRES[k]} if k in PERIMETRES and k in collectivites else {}),
                           **({"perimetre_beneficiaires": PERIMETRES_BENEF[k]} if k in PERIMETRES_BENEF else {})}
                          for k in sorted(set(collectivites) | set(coll_b))],
        "liens": {
            "depenses_drees_par_poste": {"fichier": "territoires/<dep>.json",
                                         "chemin": "aide_sociale.collectivites[].postes.<poste>.<brute|nette>.eur",
                                         "postes": ["total", "rsa_allocation", "rsa_insertion", "apa", "pch", "actp",
                                                    "ase", "autres"]},
            "foyers_rsa_caf": {"fichiers": prest["fichiers"], "chemin": "departements.<code>.rsa"},
            "budgets_departements": "local/budgets/departements.json",
            "fonctions_departements": "local/budgets/fonctions/departements.json",
            "dotations_departements": "local/dotations/departements.json",
        },
        "totaux": totaux,
        "reste_a_charge": RAC_DEFINITION,
        "ecarts": sorted(ecarts_nat, key=lambda e: (e["grandeur"], e["annee"])),
        "ecarts_departements": {"fichier": f"{AXE}/ecarts.json", "lignes": len(lignes_ecarts),
                                "par_grandeur": dict(sorted(par_grandeur.items()))},
        "rsa_recentralise": recentralise,
        "methode": METHODE,
        "limites": LIMITES,
        "regle": REGLE,
        "ordre": ORDRE,
        "sources": sources,
        "sources_inaccessibles": inaccessibles,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }

    sortie.mkdir(parents=True, exist_ok=True)
    tailles = {"comptes.json": dump(sortie / "comptes.json", doc_comptes),
               "beneficiaires.json": dump(sortie / "beneficiaires.json", doc_benef),
               "ecarts.json": dump(sortie / "ecarts.json", doc_ecarts)}
    tailles["index.json"] = dump(sortie / "index.json", index)
    print(f"{AXE} : {len(collectivites)} collectivités (comptes {annees_c[0]}-{annees_c[-1]}), {len(series_doc)} "
          f"séries de bénéficiaires, {len(lignes_ecarts)} écarts départementaux, {len(ecarts_nat)} écarts nationaux, "
          f"fichier max {max(tailles.values())} octets")
    return index


# --- Collecte ---------------------------------------------------------------------------------------------------------

def collecter() -> int:
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *COLLECTABLES])


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
