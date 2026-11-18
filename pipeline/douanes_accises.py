"""Douane et accises : produit par produit (énergies, tabacs, alcools et boissons, droits de douane, autres), en série,
qui reçoit chaque produit (État et administration centrale, sécurité sociale, collectivités, Union européenne) et ce
que la douane perçoit elle-même.

Détaille sans recopier : les totaux par grande catégorie (Eurostat D214A « droits d'accise et impôts de
consommation », D2 ...) restent dans site/data/recettes.json ; la ventilation 2025 par organisme (CNAM, MSA,
régions, AFITF ...) reste dans site/data/prelevements/affectation.json ; la contribution de la France au budget de
l'Union reste dans site/data/ue/contribution.json. Cette vue y renvoie par des liens (fichier et champ).

Trois sources, montrées côte à côte, jamais additionnées entre elles ni arbitrées :
  - Insee, comptes nationaux annuels base 2020, tableau 3.217 « Principaux impôts par catégorie » (1995-2025) :
    produit de chaque impôt, quel que soit le service qui le perçoit ;
  - OCDE, statistiques des recettes publiques, détail des recettes fiscales de la France (DF_REVFRA) : chaque ligne
    d'accise et de droit de douane par niveau d'administration bénéficiaire (1970-2024) ;
  - bilans annuels de la douane (DGDDI) 2022 à 2025 : recettes perçues par la douane elle-même (2021-2025), lues dans
    les PDF et vérifiées contre leur texte à chaque production.

Commandes :
  python pipeline/douanes_accises.py collecter   # réseau, par collecte/collecte.py (entrée « douanes_accises » du
                                                 # catalogue) ; un refus 401/403/429 est noté, jamais contourné
  python pipeline/douanes_accises.py produire    # sans réseau : écrit site/data/douanes_accises/

Sorties (contrat docs/contrat_interface.md 2.41, schémas docs/schemas/douanes_accises_*.schema.json) :
  index.json, series.json, affectation.json, perception.json

Sorties reproductibles : aucune heure de passage (dates de pipeline/reproductible.py), ordres explicites.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ID_CATALOGUE = "douanes_accises"
BRUT = ROOT / "data" / "lake" / "douanes_accises" / ID_CATALOGUE
SORTIE = ROOT / "site" / "data" / "douanes_accises"
UNITE = "milliards d'euros"

SOURCES = {
    "insee_t_3217": {
        "fichier": "insee_t_3217.xlsx",
        "url": "https://www.insee.fr/fr/statistiques/fichier/8988845/t_3217_fr.xlsx",
        "page": "https://www.insee.fr/fr/statistiques/8988845",
        "titre": "Insee, comptes nationaux annuels base 2020, « Dépenses et recettes des administrations publiques en "
                 "2025 », tableau 3.217 « Principaux impôts par catégorie » (1995-2025)",
        "producteur": "Insee", "licence": "Licence Ouverte 2.0 (réutilisation libre avec mention de l'Insee)",
        "verdict": "réutilisable tel quel",
    },
    "ocde_revfra": {
        "fichier": "ocde_revfra_accises_douane.csv",
        "url": "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_REV_OECD@DF_REVFRA,/"
               "FRA.TAX_REV..T_5121+T_5123...A?format=csvfilewithlabels",
        "page": "https://data-explorer.oecd.org/ (Statistiques des recettes publiques, « France - recettes fiscales »)",
        "titre": "OCDE, Statistiques des recettes publiques, détail des recettes fiscales de la France (DF_REVFRA), "
                 "catégories 5121 (accises) et 5123 (droits de douane et droits à l'importation), par niveau "
                 "d'administration, millions d'euros",
        "producteur": "OCDE, d'après les données transmises par la France",
        "licence": "conditions d'utilisation de l'OCDE (réutilisation avec mention de la source)",
        "verdict": "réutilisable tel quel",
    },
    "dgddi_bilan_2022": {
        "fichier": "dgddi_bilan_2022.pdf",
        "url": "https://www.douane.gouv.fr/sites/default/files/2023-02/22/bilan-annuel-de-la-douane-2022.pdf",
        "titre": "Bilan annuel de la douane 2022, « Évolution des recettes douanières en millions d'euros (détail) », "
                 "colonnes 2021 et 2022 (page 25 du PDF)",
        "producteur": "Direction générale des douanes et droits indirects (DGDDI)",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié contre son texte)",
        "page_pdf": 25,
    },
    "dgddi_bilan_2023": {
        "fichier": "dgddi_bilan_2023.pdf",
        "url": "https://www.douane.gouv.fr/sites/default/files/2024-05/09/bilan-annuel-de-la-douane-2023.pdf",
        "titre": "Bilan annuel de la douane 2023, « Évolution des recettes douanières en millions d'euros (détail) », "
                 "colonne 2023 (page 60 du PDF)",
        "producteur": "Direction générale des douanes et droits indirects (DGDDI)",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié contre son texte)",
        "page_pdf": 60,
    },
    "dgddi_bilan_2024": {
        "fichier": "dgddi_bilan_2024.pdf",
        "url": "https://www.douane.gouv.fr/sites/default/files/2025-03/24/Bilan-annuel-2024-douane.pdf",
        "titre": "Bilan de la douane 2024, « Recettes douanières en millions d'euros (détail) », colonne 2024 "
                 "(page 25 du PDF)",
        "producteur": "Direction générale des douanes et droits indirects (DGDDI)",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié contre son texte)",
        "page_pdf": 25,
    },
    "dgddi_bilan_2025": {
        "fichier": "dgddi_bilan_2025.pdf",
        "url": "https://www.douane.gouv.fr/sites/default/files/2026-02/19/Bilan_Douane_2025.pdf",
        "titre": "Bilan de la douane 2025, « Recettes douanières en millions d'euros (détail) », colonne 2025 "
                 "(page 26 du PDF)",
        "producteur": "Direction générale des douanes et droits indirects (DGDDI)",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié contre son texte)",
        "page_pdf": 26,
    },
}

SOURCES_INACCESSIBLES = [
    {"source": "Bilan annuel de la douane 2021 (colonne 2020 du tableau des recettes)",
     "url": "https://www.douane.gouv.fr/sites/default/files/2022-02/14/bilan-annuel-2021-douane-FR.pdf",
     "constat": "HTTP 403 le 18/11/2026 ; non contourné",
     "effet": "recettes perçues par la douane publiées à partir de 2021"},
    {"source": "data.gouv.fr, recherche « douane », « accises », « recettes douane » (API, 18/11/2026)",
     "url": "https://www.data.gouv.fr/api/1/datasets/?q=douane",
     "constat": "aucun jeu de recettes douanières par produit : la DGDDI publie sur data.gouv.fr le commerce "
                "extérieur, des statistiques de consultation et de concours, pas ses recettes",
     "effet": "recettes perçues par la douane lues dans les bilans annuels (PDF)"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Aucun jeu ouvert ne publie les recettes de la douane par produit ; les deux séries officielles "
                  "réutilisables telles quelles sont le tableau 3.217 de l'Insee (produit par impôt) et le détail "
                  "des recettes fiscales de la France publié par l'OCDE (bénéficiaire par impôt). Aucun dépôt public "
                  "ne les réunit : module écrit pour le dépôt, sur le modèle de pipeline/outremer.py (collecte par "
                  "le catalogue) et de pipeline/prelevements.py (vérification des chiffres lus dans les PDF).",
    "trouvailles": [
        {"nom": "Insee, comptes nationaux annuels, tableau 3.217", "url": SOURCES["insee_t_3217"]["page"],
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "comptes 2025 (base 2020)",
         "verdict": "réutilisable tel quel"},
        {"nom": "OCDE, Statistiques des recettes publiques, détail France (DF_REVFRA)",
         "url": "https://sdmx.oecd.org/public/rest/dataflow/OECD.CTP.TPS/DSD_REV_OECD@DF_REVFRA/latest",
         "licence": "conditions d'utilisation de l'OCDE", "mise_a_jour": "2025-12-09 (dernière année 2024)",
         "verdict": "réutilisable tel quel"},
        {"nom": "DGDDI, bilans annuels de la douane 2022 à 2025 (PDF)",
         "url": "https://www.douane.gouv.fr/actualites/etiquette/missions-et-organisation-de-la-douane/bilans",
         "licence": "document administratif public", "mise_a_jour": "2026-02-19 (bilan 2025)",
         "verdict": "à adapter (aucun jeu ouvert équivalent : tableaux lus dans le PDF et vérifiés)"},
        {"nom": "Eurostat gov_10a_taxag (déjà dans le dépôt : site/data/recettes.json)",
         "url": "https://ec.europa.eu/eurostat/databrowser/view/gov_10a_taxag/default/table",
         "licence": "réutilisation libre avec mention d'Eurostat", "mise_a_jour": "déjà en place",
         "verdict": "réutilisé par lien (totaux D214A et D2 non recopiés)"},
        {"nom": "pipeline/prelevements.py du dépôt (affectation 2025 de l'accise sur les énergies, des tabacs et des "
                "alcools, d'après le PLF 2026 et le PLFSS 2026)",
         "url": "https://github.com/MoonEyes/Ou-vont-mes-impots", "licence": "licence du dépôt",
         "dernier_commit": "2026-11-17", "verdict": "réutilisé par lien (lu, non modifié)"},
        {"nom": "data.gouv.fr, « PLF 2023 voies et moyens tome 1, liste des taxes affectées » (Ministères économiques "
                "et financiers)", "url": "https://www.data.gouv.fr/datasets/640bc7871040ee1c4330406a",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2023-03-10",
         "verdict": "inspiration (un seul millésime, plafonds de taxes affectées, pas de série par produit)"},
        {"nom": "data.gouv.fr, « Ventes de tabacs manufacturés en France métropolitaine depuis 2018 »",
         "url": "https://www.data.gouv.fr/datasets/5c5c21248b4c4114cce91bf8", "licence": "Licence Ouverte 2.0",
         "mise_a_jour": "2019-07-16", "verdict": "non retenu (volumes vendus, pas de recettes)"},
        {"nom": "François Geerolf, republication du tableau 3.217 de l'Insee (fgeerolf.com)",
         "url": "https://fgeerolf.com/data/insee/t_3217.html", "licence": "non précisée",
         "dernier_commit": "2026-11-17 (dernière compilation affichée)",
         "verdict": "inspiration (la source Insee est lue directement)"},
        {"nom": "GitHub, recherche « recettes douanieres », « TICPE », « accises france », « douane france data »",
         "url": "https://github.com/search?type=repositories&q=recettes+douanieres", "licence": "sans objet",
         "verdict": "aucun dépôt réutilisable trouvé"},
    ],
}

# --- Produits ------------------------------------------------------------------------------------------------------

PRODUITS = [
    {"id": "energies", "libelle": "Accises sur les énergies (carburants, fioul, électricité, gaz, charbon)",
     "definition": "Accise sur les produits énergétiques (ex-TICPE, carburants et combustibles), accises sur "
                   "l'électricité (ex-TICFE), le gaz naturel (ex-TICGN) et le charbon ; regroupées depuis 2022 dans "
                   "le code des impositions sur les biens et services sous le nom d'« accise sur les énergies »."},
    {"id": "tabacs", "libelle": "Accises sur les tabacs",
     "definition": "Droit de consommation sur les tabacs manufacturés (cigarettes, tabac à rouler, cigares)."},
    {"id": "alcools_boissons", "libelle": "Accises sur les alcools et les boissons",
     "definition": "Droits sur les alcools, les vins, les bières et les produits intermédiaires, cotisation sur les "
                   "boissons de plus de 18 degrés et contributions sur les boissons sucrées ou édulcorées."},
    {"id": "droits_douane", "libelle": "Droits de douane reversés à l'Union européenne",
     "definition": "Droits du tarif douanier commun, perçus par la douane française sur les marchandises importées "
                   "de pays hors de l'Union européenne ; ils font partie des ressources propres du budget de l'Union."},
    {"id": "autres", "libelle": "Autres prélèvements liés à la douane",
     "definition": "Octroi de mer (outre-mer) et taxe générale sur les activités polluantes, publiés à part par "
                   "l'Insee et l'OCDE ; la douane perçoit aussi des droits de port, la TVA à l'importation de "
                   "certains redevables et d'autres taxes (voir perception.json)."},
]
IDS_PRODUITS = [p["id"] for p in PRODUITS]

# Lignes du tableau 3.217 (libellé exact de l'Insee, espaces de tête retirés) -> (id, produit).
LIGNES_INSEE = [
    ("Accises sur les produits énergétiques (TICPE)", "ticpe", "energies"),
    ("Accises sur l'électricité (TICFE)", "ticfe", "energies"),
    ("Accises sur le gaz naturel (TICGN)", "ticgn", "energies"),
    ("Autres taxes sur l'énergie", "autres_energie", "energies"),
    ("Accises sur les tabacs", "tabacs", "tabacs"),
    ("Accises sur les alcools et autres boissons", "alcools_boissons", "alcools_boissons"),
    ("Droits d'importation au profit de l'Union Européenne", "droits_importation_ue", "droits_douane"),
    ("Impôts et droits sur les importations (D212)", "impots_importations_d212", "droits_douane"),
    ("Octroi de mer des départements d'outre-mer", "octroi_de_mer", "autres"),
    ("Taxe générale sur les activités polluantes", "tgap", "autres"),
]
NOTES_INSEE = {
    "impots_importations_d212": "Catégorie de comptabilité nationale qui contient les droits d'importation au profit "
                                "de l'Union européenne et la part de l'octroi de mer classée en impôts sur les "
                                "importations : contexte, à ne pas additionner aux deux lignes qu'elle contient.",
    "octroi_de_mer": "Total de l'octroi de mer ; l'Insee en publie aussi la part classée en impôts sur les "
                     "importations (« dont part classée en impôts sur importations »), non reprise ici.",
    "tgap": "Total de la taxe ; l'Insee en classe une part en impôts sur la production, non reprise ici.",
}

# Lignes de l'OCDE (catégorie standard, catégorie propre à la France) -> (id, produit, libellé français de l'OCDE).
LIGNES_OCDE = [
    ("T_5121", "L_3551", "droit_produits_energetiques", "energies", "Droit intérieur sur les produits énergétiques"),
    ("T_5121", "L_3565", "electricite_chauffage", "energies", "Taxe sur électricité et chauffage"),
    ("T_5121", "L_3560", "redevances_prix_carburants", "energies", "Redevances incluses dans prix carburants"),
    ("T_5121", "L_3587", "produits_petroliers", "energies", "Taxe sur les produits pétroliers"),
    ("T_5121", "L_3579", "tabacs_allumettes", "tabacs", "Impôts et taxes sur tabacs et allumettes"),
    ("T_5121", "L_3561", "alcools", "alcools_boissons", "Droits sur alcools"),
    ("T_5121", "L_3568", "bieres_eaux_minerales", "alcools_boissons", "Droits sur bière et eaux minérales"),
    ("T_5121", "L_3554", "vins_cidres", "alcools_boissons", "Droits sur vins, cidres et hydromels"),
    ("T_5121", "L_6138", "boissons_sucrees", "alcools_boissons",
     "Contribution sur boissons sucrées et eaux en bouteille"),
    ("T_5123", "L_3333", "droits_douane_ue", "droits_douane", "Droits de douane perçus pour l'UE"),
    ("T_5121", "L_3585", "octroi_de_mer_accise", "autres", "Octroi de mer (classé en accises)"),
    ("T_5123", "L_3585", "octroi_de_mer_importations", "autres", "Octroi de mer (classé en droits à l'importation)"),
    ("T_5121", "L_3586", "tgap", "autres", "Taxe générale sur les activités polluantes"),
]
SECTEURS = [  # code OCDE -> (id, libellé)
    ("S1311", "administration_centrale", "État et organismes divers d'administration centrale"),
    ("S1314", "securite_sociale", "Administrations de sécurité sociale"),
    ("S1313", "collectivites", "Administrations publiques locales (collectivités et organismes locaux)"),
    ("S1315", "union_europeenne", "Institutions et organes de l'Union européenne"),
]
TOLERANCE_MEUR = 1.0  # la somme des bénéficiaires doit égaler le total publié à 1 M€ près

# --- Recettes perçues par la douane (bilans DGDDI), saisies depuis les PDF et vérifiées contre leur texte ----------
# (id, rubrique, libellé de la publication, motif cherché dans le texte du PDF ou None si le texte est illisible)
# Valeurs : chaîne telle qu'imprimée ; « - » = tiret du tableau ; « * » = astérisque seul (taxe transférée).

POSTES = [
    ("dedouanement", None, "Dédouanement"),
    ("droits_douane", "dedouanement", "Droits de douane"),
    ("tva_import", "dedouanement", "TVA import"),
    ("dedouanement_autres", "dedouanement", "Autres"),
    ("energie_environnement", None, "Énergie et environnement"),
    ("accise_produits_energetiques", "energie_environnement",
     "Accise sur les produits énergétiques (« TICPE » jusqu'au bilan 2024)"),
    ("tsc_dom", "energie_environnement", "Taxe spéciale de consommation dans les départements et régions d'outre-mer"),
    ("tva_petrole", "energie_environnement", "TVA pétrole"),
    ("taxes_professionnels_petrole", "energie_environnement",
     "Taxes et rémunérations pour le compte de professionnels du pétrole"),
    ("ticgn_ticfe_tichlc", "energie_environnement", "Accises sur le gaz naturel, l'électricité et le charbon"),
    ("tgap", "energie_environnement", "Taxe générale sur les activités polluantes"),
    ("contributions_indirectes", None, "Contributions indirectes"),
    ("alcools_boissons", "contributions_indirectes", "Alcools et boissons"),
    ("tabacs", "contributions_indirectes", "Tabacs"),
    ("contributions_indirectes_autres", "contributions_indirectes", "Autres contributions indirectes"),
    ("octroi_mer_maritime", None, "Octroi de mer et activités maritimes"),
    ("octroi_de_mer", "octroi_mer_maritime", "Octroi de mer"),
    ("droits_de_ports", "octroi_mer_maritime", "Droits de ports"),
    ("dafn", "octroi_mer_maritime", "Droit annuel de francisation et de navigation"),
    ("tsvr", None, "Taxe spéciale sur certains véhicules routiers (taxe à l'essieu)"),
    ("autres_taxes", None, "Autres taxes"),
    ("total", None, "Total"),
]
NON_VERIFIE = ("texte du PDF illisible à cet endroit (caractères superposés ou colonnes mêlées) : valeur lue sur "
               "la page, non revérifiée automatiquement")
POSTE_PRODUIT = {"droits_douane": "droits_douane", "accise_produits_energetiques": "energies",
                 "ticgn_ticfe_tichlc": "energies", "tabacs": "tabacs", "alcools_boissons": "alcools_boissons",
                 "octroi_de_mer": "autres", "tgap": "autres"}

# Bilan 2022 : deux colonnes (2021, 2022) sur la même ligne ; le motif contient les deux valeurs.
BILAN_2022 = {
    "dedouanement": ("9334", "3722", "DÉDOUANEMENT 9334 3722"),
    "droits_douane": ("2408", "3062", "Droits de douane 2408 3062"),
    "tva_import": ("6875", "593", "TVA import 6875 593"),
    "dedouanement_autres": ("51", "67", "Autres 51 67"),
    "energie_environnement": ("42512", "34697", "ÉNERGIE ET ENVIRONNEMENT 42512 34697"),
    "accise_produits_energetiques": ("31991", "32507", "TICPE 31991 32507"),
    "tsc_dom": ("533", "550", "TSC DOM 533 550"),
    "tva_petrole": ("259*", "*", "TVA pétrole 259* *"),
    "ticgn_ticfe_tichlc": ("9690", "1633", "TICGN + TICFE + TICHLC 9690 1633"),
    "taxes_professionnels_petrole": ("8", "8", None),
    "tgap": ("32*", "*", "TGAP 32* *"),
    "contributions_indirectes": ("19339", "18713", "CONTRIBUTIONS INDIRECTES (CI) 19339 18713"),
    "alcools_boissons": ("4130", "4290", "Alcools et boissons 4130 4290"),
    "tabacs": ("15204", "14414", "Tabacs 15204 14414"),
    "contributions_indirectes_autres": ("5", "9", "Autres CI 5 9"),
    "octroi_mer_maritime": ("2027", "2263", "OCTROI DE MER ET ACTIVITÉS MARITIMES 2027 2263"),
    "octroi_de_mer": ("1485", "1696", "Octroi de mer 1485 1696"),
    "droits_de_ports": ("492", "563", "Droits de ports 492 563"),
    "dafn": ("49", "4", "DAFN 49 4"),
    "tsvr": ("11*", "*", "11* *"),
    "autres_taxes": ("325", "293", "AUTRES TAXES 325 293"),
    "total": ("73548", "59688", "TOTAL 73548 59688"),
}
BILANS_UNE_COLONNE = {
    2023: ("dgddi_bilan_2023", {
        "dedouanement": ("3045", "DÉDOUANEMENT 3045"),
        "droits_douane": ("2 653", "Droits de douane 2 653"),
        "tva_import": ("331", "TVA import 331"),
        "dedouanement_autres": ("62", "Autres 62"),
        "energie_environnement": ("32 899", "ÉNERGIE ET ENVIRONNEMENT 32 899"),
        "accise_produits_energetiques": ("31 721", "dont TICPE 31 721"),
        "tsc_dom": ("583", "TSC DOM 583"),
        "tva_petrole": ("0,18", "TVA pétrole* 0,18"),
        "taxes_professionnels_petrole": ("11", "Taxes et rémunérations pour le compte 11"),
        "ticgn_ticfe_tichlc": ("35", None),
        "tgap": ("549", "TGAP* 549"),
        "contributions_indirectes": ("18 437", "CONTRIBUTIONS INDIRECTES (CI) 18 437"),
        "alcools_boissons": ("4 211", "Alcools et boissons 4 211"),
        "tabacs": ("14 214", "Tabacs 14 214"),
        "contributions_indirectes_autres": ("11", "Autres CI 11"),
        "octroi_mer_maritime": ("2263", "OCTROI DE MER ET ACTIVITÉS MARITIMES 2263"),
        "octroi_de_mer": ("1 696", "Octroi de mer 1 696"),
        "droits_de_ports": ("604", "Droits de ports 604"),
        "dafn": ("3", "DAFN* 3"),
        "tsvr": ("-", None),
        "autres_taxes": ("245", "AUTRES TAXES 245"),
        "total": ("56 924", "TOTAL 56 924"),
    }),
    2024: ("dgddi_bilan_2024", {
        "dedouanement": ("3 124", "DÉDOUANEMENT 3 124"),
        "droits_douane": ("2 693", "Droits de douane 2 693"),
        "tva_import": ("369", "TVA import 369"),
        "dedouanement_autres": ("62", "Autres 62"),
        "energie_environnement": ("32 278", "ÉNERGIE ET ENVIRONNEMENT 32 278"),
        "accise_produits_energetiques": ("31 660", "dontTICPE 31 660"),
        "tsc_dom": ("596,05", "TSC DOM 596,05"),
        "tva_petrole": ("0,97", None),
        "taxes_professionnels_petrole": ("12,49", None),
        "ticgn_ticfe_tichlc": ("0,0000576", "0,0000576"),
        "tgap": ("8,59", "TGAP* 8,59"),
        "contributions_indirectes": ("2 932,16", "CONTRIBUTIONS INDIRECTES (CI) 2 932,16"),
        "alcools_boissons": ("725,14", "Alcools et boissons 725,14"),
        "tabacs": ("2 197,30", "Tabacs 2 197,30"),
        "contributions_indirectes_autres": ("9,72", "Autres CI 9,72"),
        "octroi_mer_maritime": ("2 323,17", "OCTROI DE MER ET ACTIVITÉS MARITIMES 2 323,17"),
        "octroi_de_mer": ("1706,92", "Octroi de mer 1706,92"),
        "droits_de_ports": ("614,88", "Droits de ports 614,88"),
        "dafn": ("1,37", "DAFN* 1,37"),
        "tsvr": ("-", None),
        "autres_taxes": ("220,86", "AUTRES TAXES 220,86"),
        "total": ("40 878", "TOTAL 40 878"),
    }),
    2025: ("dgddi_bilan_2025", {
        "dedouanement": ("3 317", "DÉDOUANEMENT 3 317"),
        "droits_douane": ("2 893", "Droits de douane 2 893"),
        "tva_import": ("360", "TVA import 360"),
        "dedouanement_autres": ("64", "Autres 64"),
        "energie_environnement": ("31 905", "ÉNERGIE & ENVIRONNEMENT 31 905"),
        "accise_produits_energetiques": ("31 284", "dontAccise sur les produits énergétiques 31 284"),
        "tsc_dom": ("598,76", "TSC DROM 598,76"),
        "tva_petrole": ("0,20", "TVA pétrole* 0,20"),
        "taxes_professionnels_petrole": ("10,77", "Taxes et rémunérations pour le compte 10,77"),
        "tgap": ("11,29", "TGAP* 11,29"),
        "contributions_indirectes": ("156,75", "CONTRIBUTIONS INDIRECTES (CI) 156,75"),
        "alcools_boissons": ("57,99", "Alcools et boissons 57,99"),
        "tabacs": ("85,09", "Tabacs 85,09"),
        "contributions_indirectes_autres": ("13,67", "Autres CI 13,67"),
        "octroi_mer_maritime": ("2 372,58", "OCTROI DE MER & ACTIVITÉS MARITIMES 2 372,58"),
        "octroi_de_mer": ("1 740,74", "Octroi de mer 1 740,74"),
        "droits_de_ports": ("631,81", "Droits de ports 631,81"),
        "dafn": ("0,03", "DAFN* 0,03"),
        "autres_taxes": ("267,53", "AUTRES TAXES 267,53"),
        "total": ("37 919,49", "TOTAL 37 919,49"),
    }),
}
ANNEES_PERCEPTION = [2021, 2022, 2023, 2024, 2025]

LIENS = [
    {"vue": "recettes", "fichier": "recettes.json", "champ": "impots.D214A.par_administration",
     "lecture": "Eurostat, droits d'accise et impôts de consommation (D214A), total par administration bénéficiaire "
                "2005-2025 : catégorie plus large (taxes sur les assurances, les jeux, les transactions "
                "financières, etc.), même argent vu de plus haut, jamais additionné aux produits de cette vue."},
    {"vue": "recettes", "fichier": "recettes.json", "champ": "impots.D2.par_administration",
     "lecture": "Eurostat, impôts sur la production et les importations (D2), qui contiennent les accises et les "
                "droits de douane."},
    {"vue": "affectation_2025", "fichier": "prelevements/affectation.json", "champ": "prelevements.ticpe",
     "lecture": "Accise sur les produits énergétiques en 2025 : part de l'État, des collectivités, de l'AFITF, "
                "d'Île-de-France Mobilités (PLF 2026, Voies et moyens tome I)."},
    {"vue": "affectation_2025", "fichier": "prelevements/affectation.json", "champ": "prelevements.tabac",
     "lecture": "Droit de consommation sur les tabacs en 2025 : assurance maladie (PLFSS 2026, annexe 3)."},
    {"vue": "affectation_2025", "fichier": "prelevements/affectation.json", "champ": "prelevements.alcool",
     "lecture": "Droits sur les alcools en 2025 : régime des non-salariés agricoles (PLFSS 2026, annexe 3)."},
    {"vue": "ue", "fichier": "ue/contribution.json", "champ": "contribution_comptable_2024_md",
     "lecture": "Contribution de la France au budget de l'Union au sens comptable : prélèvement sur recettes et "
                "droits de douane reversés, nets des frais de perception."},
]


# --- Outils --------------------------------------------------------------------------------------------------------

def _norm(texte: str) -> str:
    """Texte comparable : minuscules, sans accents ni espaces (les PDF coupent ou collent les mots)."""
    t = unicodedata.normalize("NFKD", texte)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", "", t)


def _libelle(texte) -> str:
    return re.sub(r"\s+", " ", str(texte or "")).strip()


def nombre_publie(texte: str | None) -> float | None:
    """« 2 197,30 » -> 2197.3 ; « - », « * », vide -> None (jamais 0) ; « 259* » -> 259."""
    if texte is None:
        return None
    t = str(texte).replace(" ", " ").replace("\xa0", " ").replace("*", "").replace(" ", "").replace(",", ".")
    if t in ("", "-", "nc", "nd", "n.d."):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _md(v: float | None, chiffres: int = 3) -> float | None:
    return None if v is None else round(v, chiffres)


def _ecrire(nom: str, contenu: dict, dossier: Path) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / nom).write_text(json.dumps(contenu, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# --- Lecture des sources -------------------------------------------------------------------------------------------

def lire_insee(chemin: Path) -> tuple[list[int], dict[str, dict[int, float | None]]]:
    import openpyxl
    wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    lignes = [r for r in wb.worksheets[0].iter_rows(values_only=True)]
    wb.close()
    entete = next(r for r in lignes if sum(isinstance(c, int) and 1900 < c < 2100 for c in r) >= 5)
    cols = [(i, c) for i, c in enumerate(entete) if isinstance(c, int) and 1900 < c < 2100]
    par_libelle: dict[str, dict[int, float | None]] = {}
    for r in lignes:
        lib = _libelle(r[1] if len(r) > 1 else None)
        if not lib or lib in par_libelle:
            continue
        par_libelle[lib] = {a: (float(r[i]) if isinstance(r[i], (int, float)) else None) for i, a in cols}
    return [a for _, a in cols], par_libelle


def lire_ocde(chemin: Path) -> dict[tuple[str, str], dict[int, dict[str, float]]]:
    """(catégorie standard, catégorie France) -> année -> secteur -> millions d'euros."""
    out: dict[tuple[str, str], dict[int, dict[str, float]]] = {}
    with chemin.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["REF_AREA"] != "FRA" or r["MEASURE"] != "TAX_REV" or r["UNIT_MEASURE"] != "EUR":
                continue
            v = nombre_publie(r["OBS_VALUE"])
            if v is None:
                continue
            mult = int(r.get("UNIT_MULT") or 0)
            out.setdefault((r["STANDARD_REVENUE"], r["CTRY_SPECIFIC_REVENUE"]), {}) \
               .setdefault(int(r["TIME_PERIOD"]), {})[r["SECTOR"]] = v * 10 ** (mult - 6)
    return out


def texte_page_pdf(cle: str) -> str | None:
    pdf = BRUT / SOURCES[cle]["fichier"]
    cache = BRUT / (SOURCES[cle]["fichier"] + f".p{SOURCES[cle]['page_pdf']}.txt")
    if cache.exists() and pdf.exists() and cache.stat().st_mtime >= pdf.stat().st_mtime:
        return cache.read_text(encoding="utf-8")
    if not pdf.exists():
        return None
    import pdfplumber
    with pdfplumber.open(pdf) as doc:
        t = doc.pages[SOURCES[cle]["page_pdf"] - 1].extract_text() or ""
    cache.write_text(t, encoding="utf-8")
    return t


# --- Constructions -------------------------------------------------------------------------------------------------

def construire_series(annees: list[int], insee: dict[str, dict[int, float | None]]) -> dict:
    lignes = []
    for libelle, id_, produit in LIGNES_INSEE:
        if libelle not in insee:
            raise SystemExit(f"Insee 3.217 : ligne « {libelle} » introuvable (le tableau a changé ?)")
        valeurs = {str(a): _md(insee[libelle].get(a)) for a in annees}
        ligne = {"id": id_, "produit": produit, "libelle_source": libelle, "valeurs": valeurs}
        if id_ in NOTES_INSEE:
            ligne["note"] = NOTES_INSEE[id_]
        lignes.append(ligne)
    return {
        "millesime": f"{annees[0]}-{annees[-1]} (comptes nationaux annuels, base 2020)",
        "source": SOURCES["insee_t_3217"]["titre"] + " ; " + SOURCES["insee_t_3217"]["url"],
        "unite": UNITE,
        "annees": [str(a) for a in annees],
        "methode": "Valeurs du tableau 3.217 reprises telles quelles (milliards d'euros, arrondis à 3 décimales) ; "
                   "une case vide du tableau est publiée null. Comptabilité nationale : produit de l'impôt, quel que "
                   "soit le service qui le perçoit (douane ou finances publiques), en droits constatés.",
        "lignes": lignes,
        "ordre": "ordre du tableau de l'Insee, groupé par produit (energies, tabacs, alcools_boissons, droits_douane, "
                 "autres)",
    }


def construire_affectation(ocde: dict) -> dict:
    lignes, controles = [], []
    toutes_annees: set[int] = set()
    for std, pays, id_, produit, libelle_fr in LIGNES_OCDE:
        donnees = ocde.get((std, pays))
        if not donnees:
            raise SystemExit(f"OCDE : ligne {std}/{pays} absente du fichier (la nomenclature a changé ?)")
        serie: dict[str, dict] = {}
        for annee in sorted(donnees):
            d = donnees[annee]
            total = d.get("S13")
            if total is None or total == 0:
                continue  # impôt absent cette année-là (l'OCDE publie 0) : pas de ligne, jamais un 0 affiché
            parts_m = {sid: d.get(code) for code, sid, _ in SECTEURS}
            somme = sum(v for v in parts_m.values() if v is not None)
            if abs(somme - total) > TOLERANCE_MEUR:
                controles.append({"ligne": id_, "annee": annee, "total_publie_md": _md(total / 1000),
                                  "somme_beneficiaires_md": _md(somme / 1000),
                                  "lecture_ecart": "bénéficiaires non ventilés par la source cette année-là : "
                                                   "montants par bénéficiaire publiés null"})
                par_benef = {sid: None for _, sid, _ in SECTEURS}
                parts = {sid: None for _, sid, _ in SECTEURS}
            else:
                par_benef = {sid: _md((v or 0.0) / 1000) for sid, v in parts_m.items()}
                parts = {sid: round((v or 0.0) / total, 4) for sid, v in parts_m.items()}
            serie[str(annee)] = {"total_md": _md(total / 1000), "par_beneficiaire_md": par_benef, "parts": parts}
            toutes_annees.add(annee)
        lignes.append({"id": id_, "produit": produit, "categorie_ocde": std.replace("T_", ""),
                       "code_ocde": pays, "libelle": libelle_fr, "serie": serie})
    annees = sorted(toutes_annees)
    return {
        "millesime": f"{annees[0]}-{annees[-1]} (statistiques des recettes publiques de l'OCDE, édition 2025)",
        "source": SOURCES["ocde_revfra"]["titre"] + " ; " + SOURCES["ocde_revfra"]["url"],
        "unite": UNITE,
        "annees": [str(a) for a in annees],
        "beneficiaires": [{"id": sid, "libelle": lib, "code_ocde": code} for code, sid, lib in SECTEURS],
        "methode": "Pour chaque ligne d'impôt publiée par l'OCDE, montant reçu par chaque niveau d'administration "
                   "(millions d'euros convertis en milliards) et part de ce montant dans le total de la ligne. Une "
                   "année où l'impôt vaut 0 à la source n'est pas publiée ; une année où la somme des bénéficiaires "
                   "ne retrouve pas le total publié (à 1 M€ près) est publiée sans ventilation (null) et listée dans "
                   "« controles ». Un montant négatif publié par la source (régularisation d'une année antérieure) est "
                   "repris tel quel : la part correspondante est alors négative et une autre dépasse 1.",
        "perimetre": "« État et organismes divers d'administration centrale » regroupe l'État et ses agences (par "
                     "exemple l'Agence de financement des infrastructures de transport) : le détail par organisme "
                     "pour 2025 est dans prelevements/affectation.json. Les parts décrivent qui reçoit le produit "
                     "de l'impôt en comptabilité nationale, après les transferts de recettes prévus par la loi.",
        "lignes": lignes,
        "controles": controles,
        "ordre": "lignes dans l'ordre des produits (energies, tabacs, alcools_boissons, droits_douane, autres), "
                 "années croissantes",
    }


def verifier_et_lire_perception() -> tuple[dict, dict, list]:
    """Valeurs par année et par poste (millions d'euros), statut de vérification par document, contrôles internes."""
    valeurs: dict[int, dict[str, dict]] = {a: {} for a in ANNEES_PERCEPTION}
    verification: dict[str, dict] = {}

    def verifier(cle: str, motifs: list[str]) -> None:
        t = texte_page_pdf(cle)
        if t is None:
            verification[cle] = {"statut": "document absent de l'entrepôt : valeurs saisies non revérifiées"}
            return
        tn = _norm(t)
        manquants = [m for m in motifs if _norm(m) not in tn]
        if manquants:
            raise SystemExit(f"{SOURCES[cle]['fichier']} : valeurs saisies introuvables dans le PDF (le document a "
                             f"changé ?) : {manquants}")
        verification[cle] = {"statut": "vérifié", "motifs": len(motifs)}

    motifs_2022 = []
    for poste, (v21, v22, motif) in BILAN_2022.items():
        for annee, brut in ((2021, v21), (2022, v22)):
            valeurs[annee][poste] = {"brut": brut, "verifie": motif is not None, "source": "dgddi_bilan_2022"}
        if motif:
            motifs_2022.append(motif)
    verifier("dgddi_bilan_2022", motifs_2022)
    for annee, (cle, postes) in BILANS_UNE_COLONNE.items():
        motifs = []
        for poste, (brut, motif) in postes.items():
            valeurs[annee][poste] = {"brut": brut, "verifie": motif is not None, "source": cle}
            if motif:
                motifs.append(motif)
        verifier(cle, motifs)

    controles = []
    rubriques = [p for p, parent, _ in POSTES if parent is None and p != "total"]
    for annee in ANNEES_PERCEPTION:
        v = {p: nombre_publie(x["brut"]) for p, x in valeurs[annee].items()}
        for rub in rubriques:
            enfants = [p for p, parent, _ in POSTES if parent == rub]
            if not enfants or v.get(rub) is None:
                continue
            somme = sum(v.get(e) or 0.0 for e in enfants)
            if abs(somme - v[rub]) > 1.5:
                controles.append({"annee": annee, "poste": rub, "publie_m": v[rub], "somme_detail_m": round(somme, 2),
                                  "ecart_m": round(somme - v[rub], 2),
                                  "lecture_ecart": "la somme des lignes de détail publiées ne retrouve pas le "
                                                   "sous-total publié ; les deux sont reproduits tels quels"})
        somme = sum(v.get(r) or 0.0 for r in rubriques)
        if v.get("total") is not None and abs(somme - v["total"]) > 1.5:
            controles.append({"annee": annee, "poste": "total", "publie_m": v["total"],
                              "somme_detail_m": round(somme, 2), "ecart_m": round(somme - v["total"], 2),
                              "lecture_ecart": "la somme des rubriques publiées ne retrouve pas le total publié ; "
                                               "les deux sont reproduits tels quels"})
    return valeurs, verification, controles


def construire_perception() -> dict:
    valeurs, verification, controles = verifier_et_lire_perception()
    postes = []
    for poste, parent, libelle in POSTES:
        serie, marques = {}, {}
        for annee in ANNEES_PERCEPTION:
            x = valeurs[annee].get(poste)
            if x is None:
                serie[str(annee)] = None
                marques[str(annee)] = "ligne absente du tableau de cette année"
                continue
            serie[str(annee)] = nombre_publie(x["brut"])
            if x["brut"].strip() == "-":
                marques[str(annee)] = "tiret dans le tableau"
            elif x["brut"].strip() == "*":
                marques[str(annee)] = "astérisque seul : taxe transférée, plus perçue par la douane"
            elif "*" in x["brut"]:
                marques[str(annee)] = "valeur suivie d'un astérisque : taxe transférée ensuite"
            if not x["verifie"] and serie[str(annee)] is not None:
                marques[str(annee)] = "; ".join(filter(None, [marques.get(str(annee)), NON_VERIFIE]))
        e = {"id": poste, "rubrique": parent, "libelle": libelle, "produit": POSTE_PRODUIT.get(poste),
             "valeurs_m": serie}
        if marques:
            e["marques"] = marques
        postes.append(e)
    return {
        "millesime": "2021-2025 (bilans annuels de la douane 2022 à 2025)",
        "source": " ; ".join(f"{SOURCES[c]['titre']} : {SOURCES[c]['url']}"
                             for c in ("dgddi_bilan_2022", "dgddi_bilan_2023", "dgddi_bilan_2024",
                                       "dgddi_bilan_2025")),
        "unite": "millions d'euros",
        "annees": [str(a) for a in ANNEES_PERCEPTION],
        "methode": "Tableau « recettes douanières » de chaque bilan, saisi ligne par ligne tel qu'imprimé (millions "
                   "d'euros), puis comparé au texte du PDF à chaque production (verification_documents). 2021 et "
                   "2022 viennent du bilan 2022, qui publie les deux années. Un tiret, un astérisque seul ou une "
                   "ligne absente sont publiés null, jamais 0.",
        "perimetre": "Recettes perçues par la douane elle-même. Ce périmètre change d'une année à l'autre : la "
                     "perception de la TVA à l'importation (2022), des accises sur l'électricité et le gaz (2021 à "
                     "2023), puis des droits sur les tabacs et les alcools (2024 et 2025) est passée à la direction "
                     "générale des finances publiques ; les bilans le signalent (« diminution des perceptions liées "
                     "au transfert des missions fiscales »). Une baisse dans ce tableau peut donc venir d'un "
                     "transfert de perception, pas d'une baisse du produit de l'impôt (voir series.json).",
        "postes": postes,
        "controles": controles,
        "verification_documents": verification,
        "ordre": "ordre du tableau publié (rubrique puis lignes de détail)",
    }


def _valeur_insee(series: dict, id_: str, annee: str) -> float | None:
    return next(l_ for l_ in series["lignes"] if l_["id"] == id_)["valeurs"].get(annee)


def _valeur_ocde(aff: dict, ids: list[str], annee: str) -> float | None:
    tot = [next(l_ for l_ in aff["lignes"] if l_["id"] == i)["serie"].get(annee) for i in ids]
    if any(t is None for t in tot):
        return None
    return round(sum(t["total_md"] for t in tot), 3)


def _valeur_dgddi(perc: dict, poste: str, annee: str) -> float | None:
    v = next(p for p in perc["postes"] if p["id"] == poste)["valeurs_m"].get(annee)
    return None if v is None else round(v / 1000, 3)


def construire_ecarts(series: dict, aff: dict, perc: dict) -> list[dict]:
    """Même produit, même année, trois sources : montants côte à côte, écart à la ligne Insee ; jamais tranché."""
    comparaisons = [
        ("energies", "ticpe", ["droit_produits_energetiques"], "accise_produits_energetiques",
         "Accise sur les produits énergétiques (ex-TICPE)"),
        ("tabacs", "tabacs", ["tabacs_allumettes"], "tabacs", "Tabacs"),
        ("alcools_boissons", "alcools_boissons", ["alcools", "bieres_eaux_minerales", "vins_cidres", "boissons_sucrees"],
         "alcools_boissons", "Alcools et boissons"),
        ("droits_douane", "droits_importation_ue", ["droits_douane_ue"], "droits_douane", "Droits de douane"),
    ]
    lecture = ("L'Insee publie le produit de l'impôt en comptabilité nationale ; l'OCDE publie les recettes "
               "transmises par la France selon sa propre classification, ici la somme des lignes OCDE du même "
               "produit ; la douane publie ce qu'elle a perçu elle-même, sans ce que perçoivent les finances "
               "publiques après les transferts de perception. Les trois montants ne s'additionnent pas.")
    out = []
    for produit, l_insee, l_ocde, p_dgddi, libelle in comparaisons:
        for annee in [str(a) for a in ANNEES_PERCEPTION]:
            vi, vo, vd = _valeur_insee(series, l_insee, annee), _valeur_ocde(aff, l_ocde, annee), \
                _valeur_dgddi(perc, p_dgddi, annee)
            if sum(v is not None for v in (vi, vo, vd)) < 2:
                continue
            e = {"produit": produit, "libelle": libelle, "annee": annee,
                 "insee_md": vi, "ocde_md": vo, "douane_percu_md": vd,
                 "ecart_ocde_insee_md": None if vi is None or vo is None else round(vo - vi, 3),
                 "ecart_douane_insee_md": None if vi is None or vd is None else round(vd - vi, 3),
                 "lecture_ecart": lecture}
            out.append(e)
    return out


def construire_index(series: dict, aff: dict, perc: dict) -> dict:
    derniere_ocde = aff["annees"][-1]
    par_produit = []
    for p in PRODUITS:
        lignes_ocde = [l_ for l_ in aff["lignes"] if l_["produit"] == p["id"]]
        repartition = {}
        if all(l_["serie"].get(derniere_ocde) for l_ in lignes_ocde):
            tot = sum(l_["serie"][derniere_ocde]["total_md"] for l_ in lignes_ocde)
            for _, sid, _ in SECTEURS:
                vals = [l_["serie"][derniere_ocde]["par_beneficiaire_md"][sid] for l_ in lignes_ocde]
                repartition[sid] = None if any(v is None for v in vals) else round(sum(vals), 3)
            repartition = {"annee": derniere_ocde, "total_md": round(tot, 3), "par_beneficiaire_md": repartition,
                           "parts": {k: (None if v is None or not tot else round(v / tot, 4))
                                     for k, v in repartition.items()},
                           "source": "OCDE, somme des lignes du produit (affectation.json)"}
        par_produit.append({**p,
                            "lignes_series": [l_["id"] for l_ in series["lignes"] if l_["produit"] == p["id"]],
                            "lignes_affectation": [l_["id"] for l_ in lignes_ocde],
                            "postes_perception": sorted(k for k, v in POSTE_PRODUIT.items() if v == p["id"]),
                            "repartition_derniere_annee": repartition or None})
    return {
        "millesime": f"Insee {series['annees'][0]}-{series['annees'][-1]} ; OCDE {aff['annees'][0]}-{derniere_ocde} ; "
                     f"douane {perc['annees'][0]}-{perc['annees'][-1]}",
        "source": "Insee (comptes nationaux, tableau 3.217) ; OCDE (statistiques des recettes publiques, détail "
                  "France) ; DGDDI (bilans annuels de la douane 2022 à 2025)",
        "unite": UNITE,
        "date_sources": date_sources("douanes_accises"),
        "fichiers": {"series": "douanes_accises/series.json", "affectation": "douanes_accises/affectation.json",
                     "perception": "douanes_accises/perception.json"},
        "produits": par_produit,
        "definitions": {
            "accise": "Impôt sur la quantité d'un produit (litre de carburant, paquet de cigarettes, hectolitre "
                      "d'alcool), inclus dans le prix payé ; tu le verses quand tu achètes ce produit.",
            "produit": "Montant de l'impôt sur l'année, quel que soit le service qui le perçoit (Insee, OCDE).",
            "percu_par_la_douane": "Montant encaissé par la direction générale des douanes et droits indirects "
                                   "elle-même (bilans annuels) ; une partie des accises est perçue par la direction "
                                   "générale des finances publiques depuis les transferts de 2021 à 2025.",
            "beneficiaire": "Niveau d'administration qui reçoit le produit (État et ses agences, sécurité sociale, "
                            "collectivités, Union européenne), d'après l'OCDE.",
        },
        "liens": LIENS,
        "ecarts": construire_ecarts(series, aff, perc),
        "limites": [
            "Les trois sources n'ont ni le même périmètre ni la même comptabilité : elles sont montrées côte à côte, "
            "jamais additionnées entre elles.",
            "La ventilation par bénéficiaire s'arrête à la dernière année publiée par l'OCDE ; la ventilation 2025 "
            "par organisme (CNAM, MSA, régions, AFITF) est dans prelevements/affectation.json.",
            "La part des droits de douane conservée par la France au titre des frais de perception n'est publiée "
            "par aucune des trois sources : voir ue/contribution.json pour la contribution nette.",
            "Les recettes perçues par la douane ne sont publiées dans un tableau détaillé qu'à partir de 2021 (bilan "
            "2021 inaccessible, voir sources_inaccessibles).",
        ],
        "regle": "Aucune estimation : chaque montant vient d'une source citée ; une valeur absente est null, jamais "
                 "0 ; les écarts entre sources sont calculés et montrés, jamais corrigés.",
        "sources": [{"id": k, **{c: v for c, v in s.items() if c != "fichier"}} for k, s in SOURCES.items()],
        "sources_inaccessibles": SOURCES_INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }


# --- Commandes -----------------------------------------------------------------------------------------------------

def produire(sortie: Path = SORTIE) -> None:
    manquants = [s["fichier"] for k, s in SOURCES.items() if not k.startswith("dgddi") and not (BRUT / s["fichier"]).exists()]
    if manquants:
        raise SystemExit(f"entrepôt incomplet ({BRUT}) : {manquants} ; lancer « python pipeline/douanes_accises.py "
                         f"collecter »")
    annees, insee = lire_insee(BRUT / SOURCES["insee_t_3217"]["fichier"])
    series = construire_series(annees, insee)
    aff = construire_affectation(lire_ocde(BRUT / SOURCES["ocde_revfra"]["fichier"]))
    perc = construire_perception()
    index = construire_index(series, aff, perc)
    for nom, contenu in (("index.json", index), ("series.json", series), ("affectation.json", aff),
                         ("perception.json", perc)):
        _ecrire(nom, contenu, sortie)
    print(f"douanes_accises : {len(series['lignes'])} lignes Insee, {len(aff['lignes'])} lignes OCDE, "
          f"{len(perc['postes'])} postes douane, {len(index['ecarts'])} écarts -> {sortie}")


def collecter(forcer: bool = False) -> int:
    """Collecte par collecte/collecte.py (reprises, manifeste, aucun contournement d'un refus d'accès)."""
    cmd = [sys.executable, str(ROOT / "collecte" / "collecte.py"), ID_CATALOGUE]
    return subprocess.call(cmd + (["--force"] if forcer else []))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true", help="retélécharger les sources déjà présentes")
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter(a.forcer)
    if a.etape in ("produire", "tout"):
        produire(a.sortie)


if __name__ == "__main__":
    main()
