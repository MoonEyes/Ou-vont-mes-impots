"""Immobilier de l'État : parc, valeur, cessions, loyers payés, compte « Gestion du patrimoine immobilier de l'État ».

Ce que publie ce module, sans qualification :
  - le parc immobilier de l'État tel que la Direction de l'immobilier de l'État le publie en données ouvertes (jeux
    « Parc de l'immobilier de l'État » au 31/12/2021, 2022 et 2023), agrégé par ministère, département, type de bien et
    type de propriétaire ; les adresses, coordonnées et désignations de sites sont écartées à la lecture ;
  - les séries du document de politique transversale « Politique immobilière de l'État » annexé au PLF 2025 (données
    2012 à 2023) : nombre de biens, surfaces, valeur au bilan par ministère, dépenses immobilières, loyers payés,
    prises à bail, grands baux (sans bailleur : la source n'en nomme aucun), cessions par administration et par
    nature ; chaque ligne reprise est retrouvée, nombre par nombre, à sa page du document collecté ;
  - le compte d'affectation spéciale « Gestion du patrimoine immobilier de l'État » : recettes par ligne d'exécution
    (cessions, redevances), dépenses du programme 723, solde (annexes CSV des PLRG 2023, 2024, 2025), prévisions du
    projet annuel de performances 2026 et rapprochement avec le rapport annuel de performances 2025 ;
  - les cessions 2013 à 2017 du jeu « Cessions immobilières de l'État depuis 2013 » (nombre, nature, procédure,
    nature juridique de l'acquéreur ; le jeu ne donne pas de prix).

Les montants de sources différentes pour un même objet sont publiés côte à côte dans `ecarts_entre_sources`, jamais
tranchés ni additionnés.

Commandes :
    python pipeline/immobilier_etat.py collecter   (réseau, par collecte/collecte.py et son contrôle d'intégrité ; un
        refus 401/403/429 n'est jamais contourné)
    python pipeline/immobilier_etat.py produire [--sortie DOSSIER]   (sans réseau ; s'arrête si une ligne reprise d'un
        PDF ne se retrouve plus dans le document collecté ou si un total ne se retrouve pas)

Sorties (site/data/immobilier_etat/, contrat docs/contrat_interface.md, schémas docs/schemas/immobilier_etat_*.json) :
    index.json, parc.json, valeur.json, cessions.json, loyers.json, compte.json

Confidentialité : aucune adresse, aucune coordonnée, aucune désignation de site ; les propriétaires des biens occupés
ne sont publiés que par type (la source n'en donne pas le nom, sauf libellés génériques) ; les acquéreurs des
cessions 2013 à 2017 ne le sont que par nature juridique. Aucun bailleur n'est nommé.
Sorties reproductibles : date = dernière collecte du domaine (pipeline/reproductible.py) ; ordres explicites.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOMAINE = "immobilier_etat"
LAKE = ROOT / "data" / "lake" / DOMAINE
SORTIE = ROOT / "site" / "data" / DOMAINE
PLRG = LAKE / "immobilier_etat_plrg_annexes"
DOCS = LAKE / "immobilier_etat_documents"
ODS = "https://data.economie.gouv.fr/explore/dataset"
COMPTE = "Gestion du patrimoine immobilier de l'État"
ANNEES_PLRG = [2023, 2024, 2025]
IDS_COLLECTE = ["immobilier_etat_parc_2021", "immobilier_etat_parc_2022", "immobilier_etat_parc_2023",
                "immobilier_etat_cessions_2013", "immobilier_etat_plrg_annexes", "immobilier_etat_documents"]

PARC = {  # fichier collecté -> métadonnées du jeu
    "2021": {"fichier": "immobilier_etat_parc_2021.csv", "jeu": "parc_immobilier_etat_20211231",
             "datagouv": "https://www.data.gouv.fr/datasets/parc-de-limmobilier-de-letat-au-31-12-2021",
             "titre": "Parc de l'immobilier de l'État au 31/12/2021", "perimetre": "publication complète du jeu"},
    "2022": {"fichier": "immobilier_etat_parc_2022.csv", "jeu": "parc_immobilier_etat_20221231",
             "datagouv": "https://www.data.gouv.fr/datasets/parc-de-limmobilier-de-letat-au-31-12-2022",
             "titre": "Parc de l'immobilier de l'État au 31/12/2022", "perimetre": "mise à jour partielle"},
    "2023": {"fichier": "immobilier_etat_parc_2023.csv", "jeu": "parc_immobilier_etat_20231231",
             "datagouv": "https://www.data.gouv.fr/datasets/parc-de-limmobilier-de-letat-au-31-12-2023",
             "titre": "Parc de l'immobilier de l'État au 31/12/2023", "perimetre": "mise à jour partielle"},
}
CESSIONS_2013 = {"fichier": "immobilier_etat_cessions_2013.csv", "jeu": "cessions-immobilieres-de-letat-copie",
                 "datagouv": "https://www.data.gouv.fr/datasets/cessions-immobilieres-de-letat-depuis-2013",
                 "titre": "Cessions immobilières de l'État depuis 2013"}
DOC = {
    "dpt": {"fichier": "dpt2025_politique_immobiliere.pdf",
            "url": "https://www2.assemblee-nationale.fr/static/17/Annexes-DL/PLF2025-Oranges/12-Orange_Politique_immobiliere.pdf",
            "titre": "Document de politique transversale « Politique immobilière de l'État », annexe au projet de loi de "
                     "finances pour 2025 (données au 31 décembre 2023), miroir Assemblée nationale"},
    "pap": {"fichier": "pap2026_cas_gpie.pdf",
            "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1088065/file/"
                   "PAP2026_CS_CAS_Gestion_patrimoine_immobilier_Etat_YB.pdf",
            "titre": "Projet annuel de performances 2026 du compte d'affectation spéciale « Gestion du patrimoine "
                     "immobilier de l'État » (annexe au projet de loi de finances pour 2026)"},
    "rap": {"fichier": "rap2025_cas_gpie.pdf",
            "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1109862/file/"
                   "Gestion_patrimoine_immobilier_Etat_YB.pdf",
            "titre": "Rapport annuel de performances 2025 du compte d'affectation spéciale « Gestion du patrimoine "
                     "immobilier de l'État » (annexe au projet de loi relative aux résultats de la gestion et portant "
                     "approbation des comptes de l'année 2025)"},
}
PLRG_URL = {2023: f"{ODS}/projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-"
                  "lannee-plrg-2023/",
            2024: f"{ODS}/plrg-2024/",
            2025: f"{ODS}/projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-"
                  "lannee-plrg-2025/"}

# --- Tableaux du document de politique transversale (page du fichier PDF, valeurs dans l'ordre des colonnes) ---------
# Chaque ligne est retrouvée à la production : libellé (si `controle_libelle`) puis nombres, dans cet ordre, sur la page.
DPT_INVENTAIRE = {  # p. 10 et 11 : nombre de biens au 31 décembre
    "annees": ["2019", "2020", "2021", "2022", "2023"],
    "series": [
        ("global", "batiments", 10, [191000, 191500, 191800, 192550, 194456]),
        ("global", "terrains", 10, [30500, 30500, 30500, 30469, 30918]),
        ("global", "total", 10, [221500, 222000, 222300, 223019, 225374]),
        ("occupes_etat_et_operateurs", "batiments", 10, [187000, 187500, 186800, 187317, 187896]),
        ("occupes_etat_et_operateurs", "terrains", 10, [27000, 27000, 26900, 27000, 27425]),
        ("occupes_etat_et_operateurs", "total", 10, [214000, 214500, 213700, 214317, 215321]),
        ("inventaire_comptable", "batiments", 11, [92000, 92000, 93800, 91900, 90198]),
        ("inventaire_comptable", "total", 11, [100000, 100000, 101000, 99900, 98278]),
    ],
}
PERIMETRES_INVENTAIRE = {
    "global": "inventaire immobilier global : biens dont l'État et ses opérateurs ou établissements publics nationaux "
              "sont propriétaires ou occupants",
    "occupes_etat_et_operateurs": "biens occupés par l'État et ses établissements publics ou opérateurs",
    "inventaire_comptable": "inventaire comptable de l'État : biens à l'actif du bilan de l'État qu'il utilise pour ses "
                            "missions",
}
DPT_SURFACES_TOTAL = [  # p. 11 : m² de surface utile brute (SUB) bâtie au 31 décembre
    ("etat", 11, "État en m² bâtis SUB",
     {"2012": 65328387, "2013": 67242288, "2014": 67037687, "2015": 65453646, "2016": 66472080, "2017": 64255561,
      "2018": 58398060, "2019": 59487706, "2020": 57051097}),
    ("total", 11, "Total en m² bâtis SUB",
     {"2012": 100566836, "2013": 101199169, "2014": 100424562, "2015": 97460580, "2016": 97213227, "2017": 99075916,
      "2018": 96611946, "2019": 96795576, "2020": 94313511}),
    ("etat", 11, "État en m² bâtis SUB", {"2021": 56028663, "2022": 56379763, "2023": 57112726}),
    ("total", 11, "Total en m² bâtis SUB", {"2021": 93780985, "2022": 94433197, "2023": 95882868}),
]
TERRAINS_DPT = ("La surface totale de terrains non bâtis (contenance cadastrale des biens propriétés et/ou occupés par "
                "l’État, ses opérateurs/établissements publics) s’élève à près de 4,1 millions d’hectares au 31 "
                "décembre 2023.")
DPT_SURFACES_TYPE = {  # p. 12 : m² SUB par type de bâtiment (État et opérateurs)
    "page": 12, "annees": ["2017", "2018", "2019", "2020", "2021", "2022", "2023"],
    "lignes": [
        ("Bureaux", [23858990, 22210733, 22365416, 22543680, 23415831, 22831959, 22916253]),
        ("Logements", [16173076, 15984589, 17500243, 17874424, 17985634, 18114568, 18347690]),
        ("Bâtiment d'enseignement", [21432372, 20912723, 19804830, 19784315, 18913070, 20033714, 20170969]),
        ("Local d'activité", [29571911, 29299300, 28893011, 29690099, 28913291, 28849405, 29650464]),
        ("Bâtiment culturel", [2927997, 2916259, 2939449, 3684150, 3300361, 3288875, 3374452]),
        ("Culte et monument", [1300189, 1259188, 1264833, 383346, 756888, 737425, 747023]),
        ("Infrastructure", [3811381, 4029154, 4027794, 353497, 495910, 577251, 676017]),
        ("Total", [99075916, 96611946, 96795576, 94313511, 93780985, 94433197, 95882868]),
    ],
    "note": "En 2020, les biens atypiques (infrastructures portuaires, plateformes aéronautiques, monuments et "
            "mémoriaux) qui n'ont pas vocation à être mesurés en m² de surface utile brute ont été exclus du mesurage "
            "(2,4 millions de m² concernés, selon la source).",
}
DPT_VALEUR_TOTALE = {  # p. 15 : valeur comptable du patrimoine contrôlé par l'État, millions d'euros
    "page": 15, "annees": [str(a) for a in range(2012, 2024)],
    "valeurs": [59064, 58568, 58425, 60910, 59988, 63124, 65213, 65716, 68214, 70330, 73327, 74985],
}
DPT_VNC_MINISTERE = {  # p. 16 : valeur nette comptable par ministère, millions d'euros, au 31 décembre
    "page": 16, "annees": ["2017", "2018", "2019", "2020", "2021", "2022", "2023"],
    "lignes": [
        ("Affaires étrangères", [5208, 4943, 4916, 5161, 5251, 5280, 5163]),
        ("Affaires sociales, travail", [979, 990, 1013, 1265, 1197, 1223, 977]),
        ("Agriculture", [467, 484, 530, 542, 573, 637, 511]),
        ("Armées", [16425, 16665, 16240, 17520, 17728, 18228, 16535]),
        ("Culture", [1414, 1434, 1498, 1629, 1651, 1726, 1402]),
        ("Économie et finances", [7297, 7402, 7276, 7469, 7610, 7807, 5866]),
        ("Éducation nationale, enseignement supérieur", [1806, 1887, 1969, 2064, 2209, 2292, 2070]),
        ("Intérieur", [12333, 12872, 13277, 13462, 16121, 15454, 14480]),
        ("Justice", [12674, 13886, 14191, 14263, 15260, 16628, 16775]),
        ("Services du Premier ministre", [1356, 1325, 1420, 1377, 1336, 1502, 1568]),
        ("Transition écologique", [3165, 3325, 3385, 3462, 1395, 2550, 2552]),
        ("Biens remis au Domaine", [None, None, None, None, None, None, 788]),
        ("Multi-occupation", [None, None, None, None, None, None, 4554]),
        ("Tiers", [None, None, None, None, None, None, 486]),
    ],
    "total": [63124, 65213, 65716, 68214, 70330, 73327, 73727],
}
DPT_OPERATEURS = (17, "La valeur comptable brute des biens immobiliers de ces 416 opérateurs s’élève à 93,3 milliards "
                      "d’euros en 2023 (88 Md€ en 2022, 82,8 Md€ en 2021 et75,2 Md€ en 2020)",
                  {"2020": 75.2, "2021": 82.8, "2022": 88.0, "2023": 93.3})
DPT_CONCESSION = (16, "La valeur comptable des biens concédés est de 1 258 M€ au 31 décembre 2023.", 1258)
DPT_EMPHYTEOSES = {  # p. 25 : emphytéoses et baux à construction dont l'État est titulaire
    "page": 25, "annees": ["2017", "2018", "2019", "2020", "2021", "2022", "2023"],
    "nombre": [155, 148, 156, 154, 156, 208, 213], "valeur_comptable_meur": [427, 393, 410, 418, 469, 699, 1018],
}
DPT_DEPENSES = {  # p. 19 : dépenses immobilières de l'État (décaissements, millions d'euros)
    "page": 19, "annees": ["2018", "2019", "2020", "2021", "2022", "2023"],
    "lignes": [
        ("Immobilisations, y compris entretien lourd", [1763, 1886, 1934, 2226, 3119, 3462]),
        ("Fluides", [768, 793, 777, 802, 949, 1381]),
        ("Matériaux / Outillage", [238, 213, 226, 160, 170, 266]),
        ("Loyers", [1619, 1421, 1633, 1738, 1780, 1875]),
        ("Entretien (hors entretien lourd)", [1086, 991, 1149, 1241, 1263, 1401]),
        ("Assurance", [12, 13, 12, 11, 12, 15]),
        ("Nettoyage / Déchets", [337, 314, 383, 396, 395, 380]),
        ("Taxes", [46, 32, 48, 35, 37, 53]),
        ("Autres", [1135, 1069, 1265, 411, 431, 637]),
    ],
    "total": [7004, 6732, 7426, 7020, 8156, 9470],
}
DPT_LOYERS = {  # p. 23 : loyers payés par l'État (décaissements, millions d'euros)
    "page": 23, "annees": [str(a) for a in range(2014, 2024)],
    "valeurs": [1579, 1660, 1540, 1522, 1619, 1421, 1633, 1738, 1780, 1875],
    "note_citation": (24, "Les chiffres ci-dessus intègrent également les annuités de crédit-baux contractés "
                          "antérieurement à 2018"),
}
DPT_PRISES_A_BAIL = {"page": 24, "annees": ["2019", "2020", "2021", "2022", "2023"],
                     "valeurs": [2253, 2852, 2976, 3122, 3917]}
# p. 24 et 25 : prises à bail dont le loyer annuel dépasse 1 M€ en Île-de-France et 0,5 M€ hors taxe ailleurs
# (ministère, date d'effet, surface louée m², occupant, loyer annuel HT en euros, département, prix au m²).
GRANDS_BAUX = [
    ("Premier ministre", "01/07/2023", "11 317,00", "Service État", "6 835 627,00", "PARIS", "604,01"),
    ("Culture", "01/01/2025", "10 951,10", "Service Opérateur", "5 913 594,00", "PARIS", "540,00"),
    ("Finances", "01/01/2023", "9 188,40", "Service Opérateur", "3 675 360,00", "PARIS", "400,00"),
    ("Finances", "02/04/2026", "12 087,00", "Service Opérateur", "2 963 640,00", "SEINE-SAINT-DENIS", "245,19"),
    ("Intérieur", "01/01/2023", "9 307,00", "Service État", "2 780 890,00", "HAUTS-DE-SEINE", "298,80"),
    ("Intérieur", "01/01/2024", "10 391,30", "Service État", "2 361 359,34", "HAUTS-DE-SEINE", "227,24"),
    ("Finances", "02/11/2023", "5 415,00", "Service État", "1 731 260,00", "HAUTS-DE-SEINE", "319,72"),
    ("Intérieur", "16/03/2021", "11 387,00", "Service État", "1 630 688,00", "HAUTE-GARONNE", "143,21"),
    ("Écologie", "01/11/2023", "11 560,00", "Service État", "1 411 000,00", "CÔTE-D’OR", "122,06"),
    ("Culture", "01/01/2024", "7 164,00", "Service Opérateur", "1 396 980,00", "PARIS", "195,00"),
    ("Intérieur", "01/05/2023", "10 057,47", "Service État", "1 274 424,17", "GIRONDE", "126,71"),
    ("Travail", "01/09/2025", "5 007,00", "Service Opérateur", "1 220 656,00", "GIRONDE", "243,79"),
    ("Enseignement supérieur", "01/10/2023", "2 200,00", "Service Opérateur", "1 090 065,30", "ESSONNE", "495,48"),
    ("Enseignement supérieur", "01/09/2023", "1 680,65", "Service Opérateur", "1 016 386,50", "HAUTS-DE-SEINE",
     "604,76"),
    ("Intérieur", "01/05/2023", "6 378,40", "Service État", "853 195,00", "LOT-ET-GARONNE", "133,76"),
    ("Intérieur", "01/06/2018", "4 670,00", "Service État", "718 778,89", "LOIR-ET-CHER", "153,91"),
    ("Finances", "01/05/2023", "2 160,00", "Service État", "712 300,00", "POLYNÉSIE FRANÇAISE", "329,77"),
    ("Intérieur", "01/05/2023", "5 550,00", "Service État", "700 000,00", "LOIRET", "126,13"),
    ("Justice", "01/08/2023", "2 744,50", "Service État", "644 957,50", "GIRONDE", "235,00"),
    ("Intérieur", "01/04/2023", "5 046,20", "Service État", "640 000,00", "SAÔNE-ET-LOIRE", "126,83"),
    ("Écologie", "01/07/2023", "2 831,00", "Service État", "622 000,00", "RHÔNE", "219,71"),
    ("Intérieur", "16/08/2022", "6 955,00", "Service État", "610 700,00", "RHÔNE", "87,81"),
    ("Intérieur", "15/12/2017", "4 109,00", "Service État", "607 929,60", "MOSELLE", "147,95"),
    ("Intérieur", "27/03/2023", "4 182,10", "Service État", "590 730,00", "NORD", "141,25"),
    ("Intérieur", "01/01/2019", "6 054,00", "Service État", "588 931,00", "HÉRAULT", "97,28"),
    ("Intérieur", "01/09/2023", "5 446,00", "Service État", "574 498,09", "NORD", "105,49"),
    ("Intérieur", "01/10/2019", "5 720,26", "Service État", "572 957,73", "EURE-ET-LOIR", "100,16"),
    ("Intérieur", "29/06/2023", "3 420,00", "Service État", "570 724,00", "SEINE-MARITIME", "166,88"),
    ("Intérieur", "01/11/2019", "3 825,00", "Service État", "562 697,27", "VOSGES", "147,11"),
    ("Intérieur", "15/11/2022", "5 299,00", "Service État", "556 590,00", "HAUTE-MARNE", "105,04"),
    ("Justice", "15/11/2022", "5 803,00", "Service État", "550 870,00", "HAUTE-MARNE", "94,93"),
    ("Justice", "01/08/2022", "2 017,00", "Service Opérateur", "530 294,00", "GUYANE", "262,91"),
    ("Finances", "24/12/2022", "5 148,00", "Service État", "513 635,54", "NORD", "99,77"),
    ("Intérieur", "08/12/2022", "2 923,00", "Service État", "510 644,00", "LANDES", "174,70"),
    ("Justice", "01/11/2023", "3 048,00", "Service État", "501 714,12", "GIRONDE", "164,60"),
]
GRANDS_BAUX_SOURCE = (25, "Source de données : PAB Web – extraction du 4 juin 2024")
DPT_CESSIONS_ADMIN = {  # p. 29 : produits des cessions par administration occupante (euros), outil de suivi des cessions
    "page": 29, "annees": ["2017", "2018", "2019", "2020", "2021", "2022", "2023"],
    "lignes": [
        ("Affaires étrangères", [30040731, 28779869, 4084750, 6572855, 18235535, 17493435, 23016106]),
        ("Agriculture", [2275758, 6665677, 8504764, 6007375, 8338434, 8769006, 8641474]),
        ("Culture", [792502, 1973000, 3792833, 282000, 882170, 16403076, 77592022]),
        ("Armées", [31869271, 55898094, 406839549, 15479547, 23125921, 16512034, 13983831]),
        ("Écologie", [65327774, 34938027, 47767375, 28770176, 35443580, 21245330, 32189574]),
        ("Économie", [27770214, 19803130, 68962126, 6000674, 8281293, 99344127, 61010473]),
        ("Éducation nationale, enseignement supérieur", [134330050, 15258503, 57548254, 14365366, 7848037, 4486674,
                                                          31025195]),
        ("Intérieur", [44654062, 17142503, 12472319, 6049801, 23553286, 10113169, 6736673]),
        ("Justice", [5751499, 4385982, 5177910, 1135166, 6446169, 2191214, 4553844]),
        ("Services du Premier ministre", [4630000, 48150000, 400, 3100000, 30150000, 12001, None]),
        ("Affaires sociales (logement, travail, jeunesse et sports)", [2916152, 1070896, 3341840, 5913514, 28925739,
                                                                       1043047, 6189287]),
        ("Biens non affectés", [7092316, 2539372, 6154526, 3055118, 3169624, 5347767, 14296063]),
    ],
    "total": [357450329, 236605353, 624646646, 96731592, 194399788, 202950880, 279234542],
}
DPT_CESSIONS_NATURE = {  # p. 28 : nombre de biens cédés et somme des prix de vente (millions d'euros)
    "page": 28, "annees": ["2021", "2022", "2023"],
    "lignes": [
        ("Terrains", [(419, 17.4), (393, 40.2), (340, 21.1)]),
        ("Logements", [(99, 50.4), (96, 39.6), (135, 51.3)]),
        ("Locaux d'activité", [(60, 57.4), (42, 11.0), (44, 54.3)]),
        ("Infrastructures", [(52, 6.4), (65, 3.4), (76, 13.4)]),
        ("Bureaux", [(57, 62.7), (63, 108.2), (49, 138.8)]),
        ("Cultes et monuments", [(1, 0.001), (2, 0.6), (1, 0.03)]),
    ],
    "total": [(688, 194.4), (661, 203.0), (645, 279.0)],
}
# Projet annuel de performances 2026 (p. 13) et rapport annuel de performances 2025 (p. 12 et 13) du compte.
PAP_LIGNES = [
    (13, "01 - Produits des cessions immobilières", "cessions", [230000000, 160000000, 200000000, 200000000]),
    (13, "02 - Produits de redevances domaniales", "redevances", [110000000, 110000000, 110000000, 110000000]),
    (13, "Total", "total", [340000000, 270000000, 310000000, 310000000]),
]
PAP_COLONNES = ["lfi_2025", "prevision_2026", "prevision_2027", "prevision_2028"]
PAP_CREDITS = (12, [("2026", 210000000, 321500000), ("2027", 340000000, 297000000), ("2028", 340000000, 291300000)])
RAP_RECETTES = [
    (13, "01 - Produits des cessions immobilières", "cessions", 230000000, 241995669),
    (13, "02 - Produits de redevances domaniales", "redevances", 110000000, 123951814),
    (13, "Total", "total", 340000000, 365947483),
]
RAP_CITATIONS = [
    (12, "Fin 2025, 242 M€ ont été encaissés au titre des produits de cessions immobilières dont 239,3 M€ de cessions "
         "immobilières et 2,7 M€ de fonds de concours et de versements du budget général."),
    (12, "Solde cumulé du compte depuis sa création +862 400 466"),
    (12, "Au 31 décembre 2025, la consommation des crédits s’élève au total à 388,8 M€ en AE et 267,6 M€ en CP"),
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "requetes": ["data.gouv.fr : inventaire immobilier de l'État ; parc de l'immobilier de l'État ; cessions "
                 "immobilières ; loyers ; patrimoine immobilier de l'État",
                 "data.economie.gouv.fr : immobilier, cessions, loyer, patrimoine immobilier",
                 "GitHub : parc immobilier etat ; inventaire immobilier etat ; cessions immobilieres etat",
                 "Assemblée nationale, budget.gouv.fr : document de politique transversale « Politique immobilière de "
                 "l'État », projet et rapport annuels de performances du compte"],
    "trouvailles": [
        {"nom": "data.gouv.fr / data.economie.gouv.fr, « Parc de l'immobilier de l'État » au 31/12/2021, 2022 et 2023 "
                "(Direction de l'immobilier de l'État)", "url": PARC["2023"]["datagouv"],
         "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "date": "2024-12-20 (dernière publication)",
         "usage": "agrégats par ministère, département, type de bien, type de propriétaire"},
        {"nom": "data.gouv.fr, « Cessions immobilières de l'État depuis 2013 »", "url": CESSIONS_2013["datagouv"],
         "verdict": "à adapter", "licence": "Licence Ouverte 2.0", "date": "2018-12-13",
         "usage": "nombre de cessions 2013 à 2017 ; pas de prix dans le jeu, adresses écartées"},
        {"nom": "data.gouv.fr, « Inventaire immobilier de l'État » (ancien jeu)",
         "url": "https://www.data.gouv.fr/datasets/inventaire-immobilier-de-letat", "verdict": "inspiration seulement",
         "licence": "Licence Ouverte 2.0", "date": "2022-02-09",
         "usage": "non repris : le producteur annonce qu'il n'est plus mis à jour et renvoie au jeu « Parc de "
                  "l'immobilier de l'État »"},
        {"nom": "data.economie.gouv.fr, « Travaux d'évaluations immobilières domaniales depuis 2012 »",
         "url": f"{ODS}/travaux-devaluations-immobilieres-domaniales/", "verdict": "inspiration seulement",
         "licence": "Licence Ouverte 2.0", "date": "2018-12-13", "usage": "non repris : hors du périmètre de l'axe"},
        {"nom": "Assemblée nationale, document de politique transversale « Politique immobilière de l'État » annexé au "
                "PLF 2025", "url": DOC["dpt"]["url"], "verdict": "réutilisable tel quel",
         "licence": "document budgétaire public", "date": "2024-10 (données 2023)",
         "usage": "séries 2012 à 2023 : biens, surfaces, valeur, dépenses, loyers, baux, cessions"},
        {"nom": "Assemblée nationale, projet annuel de performances 2026 et rapport annuel de performances 2025 du "
                "compte « Gestion du patrimoine immobilier de l'État »", "url": DOC["rap"]["url"],
         "verdict": "réutilisable tel quel", "licence": "document budgétaire public", "date": "2026 (exécution 2025)",
         "usage": "prévisions 2025 à 2028, rapprochement de l'exécution 2025"},
        {"nom": "data.economie.gouv.fr, annexes CSV des PLRG 2023, 2024 et 2025 (comptes spéciaux)",
         "url": PLRG_URL[2025], "verdict": "à adapter", "licence": "Licence Ouverte 2.0", "date": "2026-04 (PLRG 2025)",
         "usage": "recettes par ligne d'exécution, dépenses du programme 723, solde ; formats d'en-tête différents "
                  "selon l'année"},
        {"nom": "GitHub, dépôts consacrés à l'immobilier de l'État", "url": "https://github.com/search",
         "verdict": "aucun dépôt trouvé", "licence": "sans objet", "date": "2026-11-18",
         "usage": "trois requêtes sans résultat pertinent"},
    ],
}
SOURCES_INACCESSIBLES = [
    {"source": "budget.gouv.fr, documents de politique transversale du PLF 2026",
     "url": "https://www.budget.gouv.fr/documentation/documents-budgetaires",
     "motif": "le site répond par une page de contrôle d'accès aux requêtes automatisées (18/11/2026) ; non contourné. "
              "Le document « Politique immobilière de l'État » annexé au PLF 2026 n'a pas été localisé sur le miroir de "
              "l'Assemblée nationale : les séries s'arrêtent à 2023."},
]


# --- Outils ----------------------------------------------------------------------------------------------------------

def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).replace("’", "'").replace("‘", "'")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _espaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ").replace(" ", " ")).strip()


def nombre(v) -> float | None:
    """Montant d'une cellule ; vide, « nc », « - » : None (jamais 0)."""
    t = str(v if v is not None else "").replace(" ", "").replace("\xa0", "").replace(" ", "").strip()
    if t == "" or t.lower() in ("nc", "s", "nd", "-", "n/a"):
        return None
    try:
        return round(float(t.replace(",", ".")), 2)
    except ValueError:
        return None


def _fr(n) -> str:
    """Nombre écrit comme dans les documents budgétaires : 1 234 567 ou 17,4."""
    if isinstance(n, float) and not n.is_integer():
        e, d = f"{n}".split(".")
        return f"{int(e):,}".replace(",", " ") + "," + d
    return f"{int(n):,}".replace(",", " ")


def lire_csv(chemin: Path) -> list[dict]:
    """CSV point-virgule ou virgule, UTF-8 avec ou sans BOM ; en-têtes normalisés."""
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        tete = f.readline()
        f.seek(0)
        sep = "," if tete.count(",") > tete.count(";") else ";"
        lignes = csv.reader(f, delimiter=sep)
        entete = [_norm(c).replace(" ", "_").replace("'", "_") for c in next(lignes)]
        return [dict(zip(entete, l)) for l in lignes if any(c.strip() for c in l)]


def _col(ligne: dict, *motifs: str):
    for m in motifs:
        for k, v in ligne.items():
            if all(f in k for f in m.split("+")):
                return v
    return None


def _code_libelle(texte: str) -> tuple[str | None, str]:
    """« Libellé - 76101 » -> ("76101", "Libellé")."""
    t = _espaces(texte)
    m = re.match(r"^(.+?) - (\d{3,6})$", t)
    return (m.group(2), m.group(1)) if m else (None, t)


# --- Documents PDF ---------------------------------------------------------------------------------------------------

_PAGES: dict[str, list[str]] = {}


def pages(cle: str) -> list[str]:
    """Texte de chaque page (pdftotext -layout), espaces normalisés ; mis en cache par processus."""
    if cle not in _PAGES:
        chemin = DOCS / DOC[cle]["fichier"]
        if not chemin.exists():
            raise FileNotFoundError(f"{chemin} absent : lancer `python pipeline/immobilier_etat.py collecter`")
        r = subprocess.run(["pdftotext", "-layout", str(chemin), "-"], capture_output=True, check=True)
        _PAGES[cle] = [_espaces(p) for p in r.stdout.decode("utf-8", errors="replace").split("\f")]
    return _PAGES[cle]


def sequence(texte: str, jetons: list[str], fenetre: int = 600) -> bool:
    """Vrai si les jetons apparaissent dans cet ordre, chacun à moins de `fenetre` caractères du précédent."""
    debut = 0
    while True:
        i = texte.find(jetons[0], debut)
        if i < 0:
            return False
        pos, ok = i + len(jetons[0]), True
        for j in jetons[1:]:
            k = texte.find(j, pos)
            if k < 0 or k - pos > fenetre:
                ok = False
                break
            pos = k + len(j)
        if ok:
            return True
        debut = i + 1


def verifier(cle: str, page: int, jetons: list[str], quoi: str) -> None:
    if not sequence(pages(cle)[page - 1], [j for j in jetons if j]):
        raise ValueError(f"{DOC[cle]['fichier']} p. {page} : {quoi} introuvable ({' | '.join(jetons)[:160]})")


def citer(cle: str, page: int, texte: str) -> dict:
    if _espaces(texte) not in pages(cle)[page - 1]:
        raise ValueError(f"{DOC[cle]['fichier']} p. {page} : citation introuvable : {texte[:100]}")
    return {"document": cle, "page": page, "texte": texte}


def _serie(annees: list[str], valeurs: list) -> dict:
    return {a: v for a, v in zip(annees, valeurs) if v is not None}


def _verifier_total(lignes: list[tuple[str, list]], total: list, annees: list[str], quoi: str, tolerance=0.5) -> None:
    for i, a in enumerate(annees):
        s = sum(v[i] for _, v in lignes if v[i] is not None)
        if abs(s - total[i]) > tolerance:
            raise ValueError(f"{quoi} {a} : somme des lignes {s} différente du total publié {total[i]}")


def _ecarts_somme(lignes, total, annees, quoi: str, part_max: float = 0.01) -> list[dict]:
    """Écarts entre la somme des lignes et le total publié par la source : publiés, jamais corrigés.

    Au-delà de `part_max` du total, la reprise est jugée fausse et la production s'arrête."""
    out = []
    for i, a in enumerate(annees):
        s = sum(v[i] for _, v in lignes if v[i] is not None)
        if s != total[i]:
            if abs(s - total[i]) > part_max * abs(total[i]):
                raise ValueError(f"{quoi} {a} : somme des lignes {s} trop éloignée du total publié {total[i]}")
            out.append({"annee": a, "somme_des_lignes": s, "total_publie": total[i], "difference": total[i] - s})
    return out


# --- Parc (jeux de la Direction de l'immobilier de l'État) ------------------------------------------------------------

GROUPES_PROPRIETAIRE = {
    "Etat": "etat",
    "Personne Physique": "prive", "Pers.Mor.Privé": "prive", "SEM": "prive",
    "Autre Proprié.": "autre_ou_etranger",
}
LIBELLES_GROUPES = {
    "etat": "État (domaine public ou privé)",
    "autre_personne_publique": "autre personne publique (collectivité, établissement public, office public de l'habitat)",
    "prive": "propriétaire privé (personne physique, personne morale de droit privé, société d'économie mixte), par type "
             "seulement",
    "autre_ou_etranger": "autre propriétaire (notamment organismes publics étrangers)",
    "plusieurs": "plusieurs propriétaires de types différents",
    "non_renseigne": "type de propriétaire non renseigné",
}
RE_DEPT = re.compile(r"^(\d{2}|2A|2B|97\d|98\d)$")


def _groupe(type_proprietaire: str) -> str:
    t = _espaces(type_proprietaire)
    if not t:
        return "non_renseigne"
    if "|" in t:
        return "plusieurs"
    return GROUPES_PROPRIETAIRE.get(t, "autre_personne_publique")


def _dept(v: str) -> str:
    t = _espaces(v).upper()
    if not t:
        return "non_renseigne"
    if t == "N/A":
        return "sans_departement"
    if t.isdigit() and len(t) == 1:
        t = "0" + t
    return t if RE_DEPT.match(t) else "autre_code"


# Types de bien bâtis ; les autres (espaces naturels ou aménagés, réseaux, voirie, ouvrages d'art) ont une surface de
# terrain ou d'emprise, jamais additionnée à celle des bâtiments.
TYPES_BATIS = {"Bâtiment technique", "Logement", "Bureau", "Bâtiment d'enseignement ou de sport",
               "Bâtiment sanitaire ou social", "Bâtiment culturel", "Bâtiment agricole ou d'élevage",
               "Monument et mémorial", "Édifice du culte", "Commerce"}


def _acc():
    return {"biens": 0, "batiments": 0, "surface_batiments_m2": 0.0, "batiments_avec_surface": 0,
            "autres_biens": 0, "surface_autres_biens_m2": 0.0, "autres_biens_avec_surface": 0}


def _ajouter(acc: dict, surface: float | None, bati: bool) -> None:
    acc["biens"] += 1
    k = "batiments" if bati else "autres_biens"
    acc[k] += 1
    if surface is not None:
        acc[f"surface_{k}_m2"] += surface
        acc[f"{k}_avec_surface"] += 1


def _fige(acc: dict) -> dict:
    out = {"biens": acc["biens"]}
    for k in ("batiments", "autres_biens"):
        out[k] = acc[k]
        out[f"surface_{k}_m2"] = round(acc[f"surface_{k}_m2"]) if acc[f"{k}_avec_surface"] else None
        out[f"{k}_avec_surface"] = acc[f"{k}_avec_surface"]
    return out


def agreger_parc(cle: str) -> dict:
    """Agrégats d'un fichier « Parc de l'immobilier de l'État » ; adresses et coordonnées jamais lues en sortie."""
    meta = PARC[cle]
    lignes = lire_csv(LAKE / meta["fichier"])
    total, par_min, par_dept, par_type, par_prop, par_region = _acc(), {}, {}, {}, {}, {}
    min_groupes = defaultdict(Counter)
    min_dept_absent = Counter()
    regions_dept = defaultdict(Counter)
    erp = Counter()
    dates = Counter()
    for l in lignes:
        s = nombre(l.get("surface_m2"))
        ministere = _espaces(l.get("ministere")) or "non renseigné"
        d = _dept(l.get("dept", ""))
        region = _espaces(l.get("libelle_nouvelle_region"))
        region = region if region and region != "-" else "non renseigné"
        typ = _espaces(l.get("type")) or "non renseigné"
        prop = _espaces(l.get("type_proprietaire")) or "non renseigné"
        bati = typ in TYPES_BATIS
        _ajouter(total, s, bati)
        for dico, k in ((par_min, ministere), (par_dept, d), (par_type, typ), (par_prop, prop), (par_region, region)):
            _ajouter(dico.setdefault(k, _acc()), s, bati)
        min_groupes[ministere][_groupe(l.get("type_proprietaire", ""))] += 1
        if d == "non_renseigne":
            min_dept_absent[ministere] += 1
        if RE_DEPT.match(d):
            regions_dept[d][region] += 1
        erp[_espaces(l.get("erp")) or "non renseigné"] += 1
        dates[_espaces(l.get("date_de_reference"))] += 1
    groupes_tot = Counter()
    for c in min_groupes.values():
        groupes_tot.update(c)
    return {
        "fichier_source": meta["jeu"], "titre": meta["titre"], "url": f"{ODS}/{meta['jeu']}/",
        "url_datagouv": meta["datagouv"], "au": f"{cle}-12-31", "perimetre_publication": meta["perimetre"],
        "dates_de_reference_inscrites": dict(sorted(dates.items())),
        "total": _fige(total),
        "par_ministere": [{"ministere": m, **_fige(a), "departement_non_renseigne": min_dept_absent.get(m, 0),
                           "par_groupe_proprietaire": dict(sorted(min_groupes[m].items()))}
                          for m, a in sorted(par_min.items(), key=lambda x: (-x[1]["biens"], x[0]))],
        "par_departement": [{"code": d, "region": regions_dept[d].most_common(1)[0][0] if d in regions_dept else None,
                             **_fige(a)} for d, a in sorted(par_dept.items())],
        "par_region": [{"region": r, **_fige(a)} for r, a in sorted(par_region.items(), key=lambda x: (-x[1]["biens"], x[0]))],
        "par_type_de_bien": [{"type": t, **_fige(a)} for t, a in sorted(par_type.items(), key=lambda x: (-x[1]["biens"], x[0]))],
        "par_type_proprietaire": [{"type": t, "groupe": _groupe(t if t != "non renseigné" else ""), **_fige(a)}
                                  for t, a in sorted(par_prop.items(), key=lambda x: (-x[1]["biens"], x[0]))],
        "par_groupe_proprietaire": dict(sorted(groupes_tot.items())),
        "etablissement_recevant_du_public": dict(sorted(erp.items())),
    }


# --- Cessions 2013 à 2017 (jeu sans prix) -----------------------------------------------------------------------------

def cessions_historiques() -> dict:
    lignes = lire_csv(LAKE / CESSIONS_2013["fichier"])
    par_annee = Counter()
    croise = {k: defaultdict(Counter) for k in ("nature", "type_procedure_ayant_mene_a_la_vente",
                                                  "nature_juridique_acquereur", "ministere_occupant", "dep_code")}
    for l in lignes:
        a = _espaces(l.get("annee_cession"))[:4] or "non renseigné"
        par_annee[a] += 1
        for k in croise:
            v = _espaces(l.get(k)) or "non renseigné"
            croise[k][v][a] += 1
    annees = sorted(par_annee)

    def tab(k):
        return [{"valeur": v, "total": sum(c.values()), "par_annee": {a: c[a] for a in annees if c[a]}}
                for v, c in sorted(croise[k].items(), key=lambda x: (-sum(x[1].values()), x[0]))]

    return {"fichier_source": CESSIONS_2013["jeu"], "titre": CESSIONS_2013["titre"],
            "url": f"{ODS}/{CESSIONS_2013['jeu']}/", "url_datagouv": CESSIONS_2013["datagouv"],
            "unite": "nombre de biens cédés (le jeu ne donne aucun prix)", "annees": annees,
            "par_annee": {a: par_annee[a] for a in annees}, "total": sum(par_annee.values()),
            "par_nature_de_bien": tab("nature"), "par_procedure": tab("type_procedure_ayant_mene_a_la_vente"),
            "par_nature_juridique_acquereur": tab("nature_juridique_acquereur"),
            "par_ministere_occupant": tab("ministere_occupant"), "par_departement": tab("dep_code"),
            "note": "Le titre du jeu annonce les cessions « depuis 2013 » ; le fichier publié le 13/12/2018 couvre les "
                    "années de cession 2013 à 2017. Les acquéreurs n'y sont décrits que par leur nature juridique ; "
                    "aucune adresse ni commune n'est reprise."}


# --- Compte d'affectation spéciale (PLRG) -----------------------------------------------------------------------------

def _est_compte(v) -> bool:
    return _norm(v).startswith(_norm(COMPTE))


def plrg_recettes(annee: int) -> dict:
    sections: dict[str, dict] = {}
    for l in lire_csv(PLRG / f"plrg_{annee}_cs_recouvrements.csv"):
        if not _est_compte(_col(l, "compte")):
            continue
        code_prev, lib_prev = _code_libelle(_col(l, "ligne_de_prevision"))
        code_exec, lib_exec = _code_libelle(_col(l, "ligne_d_execution") or "")
        s = sections.setdefault(code_prev, {"code": code_prev, "libelle": lib_prev, "evaluation_eur": None,
                                            "execution_eur": 0.0, "lignes_execution": []})
        ev, rec = nombre(_col(l, "evaluations")), nombre(_col(l, "recouvrements"))
        if code_exec is None:  # ligne de prévision : évaluation des recettes
            s["evaluation_eur"] = round((s["evaluation_eur"] or 0) + (ev or 0), 2)
        else:
            s["lignes_execution"].append({"code": code_exec, "libelle": lib_exec, "execution_eur": rec})
            s["execution_eur"] = round(s["execution_eur"] + (rec or 0), 2)
    for s in sections.values():
        s["lignes_execution"].sort(key=lambda x: (-(x["execution_eur"] or 0), x["code"]))
    return {"annee": str(annee), "sections": [sections[k] for k in sorted(sections)],
            "evaluation_eur": round(sum(s["evaluation_eur"] or 0 for s in sections.values()), 2),
            "execution_eur": round(sum(s["execution_eur"] for s in sections.values()), 2)}


MESURES_CP = [("lfi_eur", "lfi"), ("lfr_eur", "lfr"), ("report_entrant_eur", "report_n-1"),
              ("mouvements_reglementaires_eur", "mvts_reglementaires"), ("fonds_de_concours_eur", "fdc_et_adp"),
              ("fongibilite_asymetrique_eur", "fongibilite"), ("credits_ouverts_eur", "total_cp_ouverts"),
              ("execution_eur", "depenses_constatees"), ("report_sortant_eur", "report_n+1")]


def plrg_depenses(annee: int) -> list[dict]:
    progs = []
    for l in lire_csv(PLRG / f"plrg_{annee}_cs_cp.csv"):
        if not _est_compte(_col(l, "mission")):
            continue
        code, lib = _code_libelle(_col(l, "programme"))
        progs.append({"programme": code, "libelle": lib, **{m: nombre(_col(l, c)) for m, c in MESURES_CP}})
    return sorted(progs, key=lambda p: p["programme"] or "")


def plrg_solde(annee: int) -> dict:
    for l in lire_csv(PLRG / f"plrg_{annee}_cs_comptable.csv"):
        if _est_compte(_col(l, "mission")):
            debut = (nombre(_col(l, "be_credit")) or 0) - (nombre(_col(l, "be_debit")) or 0)
            fin = (nombre(_col(l, "bs_credit")) or 0) - (nombre(_col(l, "bs_debit")) or 0)
            return {"debut_eur": round(debut, 2), "recettes_eur": nombre(_col(l, "op_recettes")),
                    "depenses_eur": nombre(_col(l, "op_depenses")), "fin_eur": round(fin, 2)}
    raise ValueError(f"PLRG {annee} : situation comptable du compte absente")


# --- Production --------------------------------------------------------------------------------------------------------

def _entete(collecte: str, source: str, avertissement: str, unite: str) -> dict:
    return {"millesime": "2026", "source": source, "unite": unite, "avertissement": avertissement,
            "collecte_le": collecte}


def produire_parc(collecte: str) -> dict:
    publications = [agreger_parc(k) for k in sorted(PARC)]
    inv = {}
    for perimetre, nature, page, valeurs in DPT_INVENTAIRE["series"]:
        libelle = {"batiments": "Bâtiments", "terrains": "Terrains", "total": "Total"}[nature]
        verifier("dpt", page, [libelle] + [_fr(v) for v in valeurs], f"inventaire {perimetre} {nature}")
        inv.setdefault(perimetre, {"perimetre": PERIMETRES_INVENTAIRE[perimetre]})[nature] = \
            _serie(DPT_INVENTAIRE["annees"], valeurs)
    surfaces_tot = {"etat": {}, "total": {}}
    for cle, page, libelle, serie in DPT_SURFACES_TOTAL:
        verifier("dpt", page, [libelle] + [_fr(v) for v in serie.values()], f"surfaces {cle}")
        surfaces_tot[cle].update(serie)
    st = DPT_SURFACES_TYPE
    for lib, vals in st["lignes"]:
        verifier("dpt", st["page"], [_fr(v) for v in vals], f"surfaces {lib}")
    _verifier_total(st["lignes"][:-1], st["lignes"][-1][1], st["annees"], "surfaces par type")
    dernier = publications[0]
    return {
        **_entete(collecte, "Direction de l'immobilier de l'État : jeux « Parc de l'immobilier de l'État » "
                            "(data.economie.gouv.fr, data.gouv.fr) ; document de politique transversale « Politique "
                            "immobilière de l'État » annexé au PLF 2025",
                  "Les jeux ouverts ne couvrent pas tout le parc : ils excluent les données confidentielles, certains "
                  "ministères occultent la localisation, et les fichiers au 31/12/2022 et au 31/12/2023 ne mettent à "
                  "jour que quelques ministères. Les comptes de biens du document budgétaire portent sur l'inventaire "
                  "complet : les deux séries sont publiées côte à côte, jamais additionnées.",
                  "nombre de biens (bâtiments et terrains, une ligne par bien) ; surfaces en m²"),
        "definitions": {
            "bien": "une ligne du jeu : un bâtiment ou un terrain dont l'État ou un de ses établissements publics "
                    "nationaux est propriétaire ou occupant, inscrit ou non à l'actif du bilan de l'État",
            "surface_batiments_m2": "somme des surfaces renseignées (m²) des biens bâtis (bureaux, logements, "
                                    "bâtiments techniques, d'enseignement, sanitaires, culturels, agricoles, édifices du "
                                    "culte, monuments, commerces) ; une surface absente n'est pas comptée, "
                                    "`batiments_avec_surface` dit combien en ont une",
            "surface_autres_biens_m2": "somme des surfaces renseignées (m²) des autres biens (espaces naturels ou "
                                       "aménagés, réseaux et voirie, ouvrages d'art, type non renseigné) : surfaces de "
                                       "terrain ou d'emprise, jamais additionnées à celles des bâtiments",
            "departement": "code du département inscrit dans le jeu ; `non_renseigne` : localisation absente ou "
                           "occultée par le ministère ; `sans_departement` : valeur « N/A » (biens à l'étranger "
                           "notamment) ; `autre_code` : code hors nomenclature",
            "groupe_proprietaire": LIBELLES_GROUPES,
            "surface_utile_brute": "surface utile brute (SUB) : mesure des bâtiments retenue par le document budgétaire",
        },
        "publications": publications,
        "comparaison_publications": [
            {"au": p["au"], "perimetre_publication": p["perimetre_publication"], "biens": p["total"]["biens"],
             "ministeres": len(p["par_ministere"])} for p in publications],
        "inventaire_document_budgetaire": {
            "source": DOC["dpt"]["titre"], "url": DOC["dpt"]["url"], "pages": [10, 11],
            "unite": "nombre de biens au 31 décembre", "series": inv},
        "surfaces_document_budgetaire": {
            "source": DOC["dpt"]["titre"], "url": DOC["dpt"]["url"],
            "unite": "m² de surface utile brute (SUB) bâtie au 31 décembre",
            "etat_et_operateurs": {"page": 11, "occupes_par_l_etat": surfaces_tot["etat"],
                                   "total": surfaces_tot["total"]},
            "par_type": {"page": st["page"], "annees": st["annees"],
                         "lignes": [{"type": lib, "valeurs": _serie(st["annees"], v)} for lib, v in st["lignes"][:-1]],
                         "total": _serie(st["annees"], st["lignes"][-1][1]), "note": st["note"]}},
        "ecarts_entre_sources": [{
            "objet": "nombre de biens du parc",
            "valeurs": [{"source": f"jeu ouvert {dernier['fichier_source']}", "au": dernier["au"],
                         "biens": dernier["total"]["biens"]},
                        {"source": "document de politique transversale, inventaire global", "au": "2021-12-31",
                         "biens": inv["global"]["total"]["2021"]}],
            "lecture": "Le jeu ouvert exclut les données confidentielles et ne couvre pas tous les ministères ; le "
                       "document budgétaire compte l'inventaire complet. L'écart n'est pas réparti entre ces causes."},
            {"objet": "surface des terrains et espaces",
             "valeurs": [*({"source": f"jeu ouvert {p['fichier_source']}, somme des surfaces des biens non bâtis",
                            "au": p["au"], "hectares": round(p["total"]["surface_autres_biens_m2"] / 10000)
                            if p["total"]["surface_autres_biens_m2"] is not None else None} for p in publications),
                         {"source": "document de politique transversale, page 11", "au": "2023-12-31",
                          "hectares": 4100000, "citation": citer("dpt", 11, TERRAINS_DPT)["texte"]}],
             "lecture": "Les surfaces des biens non bâtis sont reprises telles que publiées dans chaque fichier, sans "
                        "contrôle de leur unité ; elles ne se comparent pas directement au total des terrains du "
                        "document budgétaire, qui porte sur tout l'inventaire. Aucune n'est corrigée."}],
        "ordre": {"par_ministere": ["-biens", "ministere"], "par_departement": ["code"],
                  "par_type_de_bien": ["-biens", "type"]},
    }


def produire_valeur(collecte: str) -> dict:
    vt = DPT_VALEUR_TOTALE
    verifier("dpt", vt["page"], ["En M€"] + [_fr(v) for v in vt["valeurs"]], "valeur comptable totale")
    vm = DPT_VNC_MINISTERE
    for lib, vals in vm["lignes"]:
        verifier("dpt", vm["page"], [_fr(v) for v in vals if v is not None], f"valeur nette comptable {lib}")
    verifier("dpt", vm["page"], ["Total"] + [_fr(v) for v in vm["total"]], "valeur nette comptable, total")
    _verifier_total(vm["lignes"], vm["total"], vm["annees"], "valeur nette comptable par ministère", tolerance=3)
    em = DPT_EMPHYTEOSES
    verifier("dpt", em["page"], ["Nombre"] + [_fr(v) for v in em["nombre"]], "emphytéoses, nombre")
    verifier("dpt", em["page"], [_fr(v) for v in em["valeur_comptable_meur"]], "emphytéoses, valeur")
    p, cit, serie = DPT_OPERATEURS
    pc, citc, conc = DPT_CONCESSION
    return {
        **_entete(collecte, DOC["dpt"]["titre"],
                  "Valeur comptable au bilan de l'État selon les normes comptables de l'État : depuis 2018, seuls les "
                  "bureaux et logements sont évalués en valeur vénale, les autres biens au coût (amorti pour le bâti). "
                  "Ce n'est pas un prix de vente. La valeur des biens des opérateurs figure à leur propre bilan : elle "
                  "est publiée à part, jamais additionnée.",
                  "millions d'euros (_meur) ou milliards d'euros (_md)"),
        "url": DOC["dpt"]["url"],
        "valeur_comptable_patrimoine_controle": {
            "page": vt["page"], "unite": "millions d'euros, au 31 décembre", "statut": "tracé",
            "valeurs_meur": _serie(vt["annees"], vt["valeurs"]),
            "note": "Les routes, autoroutes, concessions et ouvrages hydrauliques, retracés par ailleurs au bilan de "
                    "l'État, ne sont pas compris (source, page 15). Le montant 2023 comprend les logements concédés du "
                    "ministère des armées."},
        "logements_concedes_2023": {"valeur_meur": conc, "citation": citer("dpt", pc, citc)},
        "valeur_nette_comptable_par_ministere": {
            "page": vm["page"], "unite": "millions d'euros, au 31 décembre", "annees": vm["annees"],
            "lignes": [{"ministere": lib, "valeurs_meur": _serie(vm["annees"], v)} for lib, v in vm["lignes"]],
            "total_meur": _serie(vm["annees"], vm["total"]),
            "note": "À partir de 2023, la source répartit la valeur entre les gestionnaires présents sur les bâtiments "
                    "et ajoute trois lignes (biens remis au Domaine, multi-occupation, tiers) ; la répartition 2023 "
                    "n'est pas comparable ligne à ligne avec les années précédentes. Elle exclut les logements "
                    "concédés (1 258 M€)."},
        "emphyteoses_et_baux_a_construction": {
            "page": em["page"], "definition": "baux de longue durée dont l'État est titulaire (droits immobiliers)",
            "nombre": _serie(em["annees"], em["nombre"]),
            "valeur_comptable_meur": _serie(em["annees"], em["valeur_comptable_meur"])},
        "operateurs": {"page": p, "unite": "milliards d'euros, valeur comptable brute", "statut": "tracé",
                       "valeurs_md": serie, "citation": citer("dpt", p, cit),
                       "perimetre": "416 opérateurs de l'État soumis au décret du 7 novembre 2012 (2023)"},
        "ecarts_entre_sources": [{
            "objet": "valeur du patrimoine contrôlé par l'État au 31 décembre 2023",
            "valeurs": [{"mesure": "valeur comptable du patrimoine contrôlé (tableau de la page 15)", "meur": 74985},
                        {"mesure": "total de la valeur nette comptable par ministère (page 16)", "meur": 73727}],
            "lecture": "La source indique que la ventilation par ministère ne reprend pas les logements concédés "
                       "(1 258 M€) ; 74 985 moins 73 727 font 1 258."}],
    }


def produire_loyers(collecte: str, parc: dict) -> dict:
    lo = DPT_LOYERS
    verifier("dpt", lo["page"], ["Loyers (en M€)"] + [_fr(v) for v in lo["valeurs"]], "loyers payés")
    de = DPT_DEPENSES
    for lib, vals in de["lignes"]:
        verifier("dpt", de["page"], [lib.split(",")[0].split(" (")[0]] + [_fr(v) for v in vals], f"dépenses {lib}")
    verifier("dpt", de["page"], ["Total"] + [_fr(v) for v in de["total"]], "dépenses, total")
    _verifier_total(de["lignes"], de["total"], de["annees"], "dépenses immobilières", tolerance=3)
    pb = DPT_PRISES_A_BAIL
    # la source écrit « 3917 » sans séparateur pour 2023
    verifier("dpt", pb["page"], ["Nombre"] + [_fr(v) for v in pb["valeurs"][:-1]] + [str(pb["valeurs"][-1])],
             "prises à bail")
    baux = []
    for (mini, date, surf, occ, loyer, dep, prix) in GRANDS_BAUX:
        page = 24 if sequence(pages("dpt")[23], [date, surf, occ, loyer + " €"]) else 25
        verifier("dpt", page, [date, surf, occ, loyer + " €", prix], f"grand bail {date} {loyer}")
        # département : écrit sur plusieurs lignes dans la source quand il est long ; son premier mot est contrôlé
        verifier("dpt", page, [re.split(r"[- ]", dep)[0]], f"département du bail {date} {loyer}")
        j, m, a = date.split("/")
        baux.append({"ministere": mini, "date_effet": f"{a}-{m}-{j}", "surface_m2": nombre(surf),
                     "occupant": occ, "loyer_annuel_ht_eur": nombre(loyer), "departement": dep,
                     "loyer_par_m2_eur": nombre(prix), "page": page})
    cit_baux = citer("dpt", *GRANDS_BAUX_SOURCE)
    par_min = defaultdict(lambda: {"baux": 0, "loyer_annuel_ht_eur": 0.0, "surface_m2": 0.0})
    for b in baux:
        x = par_min[b["ministere"]]
        x["baux"] += 1
        x["loyer_annuel_ht_eur"] = round(x["loyer_annuel_ht_eur"] + b["loyer_annuel_ht_eur"], 2)
        x["surface_m2"] = round(x["surface_m2"] + b["surface_m2"], 2)
    # Biens occupés dont l'État n'est pas propriétaire (jeux ouverts) : propriétaires par type seulement.
    occupes = []
    for pub in parc["publications"]:
        hors_etat = [t for t in pub["par_type_proprietaire"] if t["groupe"] != "etat"]
        occupes.append({"au": pub["au"], "fichier_source": pub["fichier_source"],
                        "perimetre_publication": pub["perimetre_publication"],
                        "biens_hors_etat": sum(t["biens"] for t in hors_etat),
                        "par_groupe_proprietaire": {g: n for g, n in pub["par_groupe_proprietaire"].items() if g != "etat"},
                        "par_type_proprietaire": hors_etat})
    return {
        **_entete(collecte, DOC["dpt"]["titre"] + " ; jeux « Parc de l'immobilier de l'État »",
                  "Loyers payés par l'État pour les biens qu'il prend à bail, en décaissements, tels que publiés par le "
                  "document budgétaire (dernière année : 2023). Aucun bailleur n'est nommé : la source n'en nomme "
                  "aucun ; les jeux ouverts ne donnent que le type de propriétaire des biens occupés.",
                  "millions d'euros (_meur) ou euros (_eur)"),
        "url": DOC["dpt"]["url"],
        "loyers_payes": {"page": lo["page"], "unite": "millions d'euros (décaissements)", "statut": "tracé",
                         "valeurs_meur": _serie(lo["annees"], lo["valeurs"]),
                         "perimetre": citer("dpt", *lo["note_citation"])["texte"] + "."},
        "depenses_immobilieres": {"page": de["page"], "unite": "millions d'euros (décaissements)", "annees": de["annees"],
                                  "lignes": [{"poste": lib, "valeurs_meur": _serie(de["annees"], v)}
                                             for lib, v in de["lignes"]],
                                  "total_meur": _serie(de["annees"], de["total"])},
        "prises_a_bail": {"page": pb["page"], "definition": "prises à bail initiales, renouvellements et avenants",
                          "nombre": _serie(pb["annees"], pb["valeurs"])},
        "grands_baux": {
            "definition": "prises à bail dont le loyer annuel dépasse 1 M€ en Île-de-France et 0,5 M€ hors taxe dans "
                          "les autres régions, telles que listées par le document budgétaire",
            "source_des_donnees": cit_baux["texte"], "baux": baux,
            "par_ministere": [{"ministere": k, **v} for k, v in sorted(par_min.items(), key=lambda x: (-x[1]["loyer_annuel_ht_eur"], x[0]))],
            "note": "La source ne nomme pas les bailleurs ; certaines dates d'effet sont postérieures à l'extraction "
                    "(baux signés à effet futur)."},
        "biens_occupes_non_proprietes_de_l_etat": {
            "definition": "biens des jeux ouverts dont le type de propriétaire n'est pas l'État ; la source ne donne "
                          "pas le loyer ligne à ligne",
            "publications": occupes},
        "ecarts_entre_sources": [{
            "objet": "loyers payés par l'État en 2023",
            "valeurs": [{"mesure": "tableau « Loyers payés par l'État » (page 23)", "meur": 1875},
                        {"mesure": "ligne « Loyers » des dépenses immobilières (page 19)", "meur": 1875}],
            "lecture": "Les deux tableaux du même document donnent le même montant."}],
        "ordre": {"grands_baux": "ordre de la source (loyer annuel décroissant par page)",
                  "par_ministere": ["-loyer_annuel_ht_eur", "ministere"]},
    }


def produire_cessions(collecte: str, compte: dict) -> dict:
    ca = DPT_CESSIONS_ADMIN
    for lib, vals in ca["lignes"]:
        verifier("dpt", ca["page"], [_fr(v) for v in vals if v is not None], f"cessions {lib}")
    verifier("dpt", ca["page"], ["Total"] + [_fr(v) for v in ca["total"]], "cessions, total")
    ecarts_somme = _ecarts_somme(ca["lignes"], ca["total"], ca["annees"], "cessions par administration")
    cn = DPT_CESSIONS_NATURE
    for lib, vals in cn["lignes"] + [("Total général", cn["total"])]:
        jetons = [lib.split(" ")[0]] if lib not in ("Cultes et monuments",) else []
        for n, m in vals:
            jetons += [_fr(n), _fr(m) if not float(m).is_integer() else str(int(m))]
        verifier("dpt", cn["page"], jetons, f"cessions par nature {lib}")
    recettes = {a: compte["par_annee"][a]["recettes"] for a in compte["par_annee"]}
    cas = {a: next(s for s in r["sections"] if s["code"] == "76101") for a, r in recettes.items()}
    return {
        **_entete(collecte, DOC["dpt"]["titre"] + " ; annexes CSV des PLRG 2023 à 2025 ; jeu « Cessions immobilières "
                            "de l'État depuis 2013 »",
                  "Produits de cessions selon deux mesures publiées côte à côte : l'outil de suivi des cessions de la "
                  "Direction de l'immobilier de l'État (prix des biens cédés dans l'année, document budgétaire) et les "
                  "recettes encaissées par le compte d'affectation spéciale (PLRG). Elles diffèrent par le moment "
                  "d'enregistrement et le périmètre ; elles ne sont jamais additionnées.",
                  "euros (_eur) ; millions d'euros (_meur)"),
        "outil_de_suivi_des_cessions": {
            "source": DOC["dpt"]["titre"], "url": DOC["dpt"]["url"],
            "par_administration_occupante": {
                "page": ca["page"], "unite": "euros", "annees": ca["annees"],
                "lignes": [{"administration": lib, "valeurs_eur": _serie(ca["annees"], v)} for lib, v in ca["lignes"]],
                "total_eur": _serie(ca["annees"], ca["total"]),
                "ecarts_somme_total": ecarts_somme,
                "note": "Le total publié par la source diffère de la somme de ses lignes certaines années "
                        "(`ecarts_somme_total`) ; les deux sont reproduits tels quels, aucun n'est corrigé. La source "
                        "laisse vide la case 2023 des services du Premier ministre."},
            "par_nature_de_bien": {
                "page": cn["page"], "annees": cn["annees"],
                "lignes": [{"nature": lib, "par_annee": {a: {"biens": n, "prix_meur": m} for a, (n, m) in
                                                         zip(cn["annees"], vals)}} for lib, vals in cn["lignes"]],
                "total": {a: {"biens": n, "prix_meur": m} for a, (n, m) in zip(cn["annees"], cn["total"])}}},
        "compte_affectation_speciale": {
            "definition": "recettes de la section « Produits des cessions immobilières » (ligne 76101) du compte "
                          "« Gestion du patrimoine immobilier de l'État », par ligne d'exécution",
            "par_annee": {a: {"evaluation_eur": s["evaluation_eur"], "execution_eur": s["execution_eur"],
                              "lignes_execution": s["lignes_execution"], "source": PLRG_URL[int(a)]}
                          for a, s in sorted(cas.items())}},
        "historique_2013_2017": cessions_historiques(),
        "ecarts_entre_sources": [{
            "objet": "produits de cessions immobilières en 2023",
            "valeurs": [{"mesure": "outil de suivi des cessions, total (document budgétaire, page 29)",
                         "eur": ca["total"][-1]},
                        {"mesure": "recettes de la ligne 76101 du compte, exécution (PLRG 2023)",
                         "eur": cas["2023"]["execution_eur"]}],
            "lecture": "La ligne du compte comprend aussi des versements du budget général, des contributions de tiers "
                       "à des travaux et des pénalités ; l'outil de suivi compte le prix des biens cédés. Les deux "
                       "montants sont publiés tels quels."}],
    }


def produire_compte(collecte: str) -> dict:
    par_annee = {}
    for a in ANNEES_PLRG:
        rec, dep, sol = plrg_recettes(a), plrg_depenses(a), plrg_solde(a)
        tot_dep = round(sum(p["execution_eur"] or 0 for p in dep), 2)
        if abs(rec["execution_eur"] - (sol["recettes_eur"] or 0)) > 1:
            raise ValueError(f"PLRG {a} : recettes {rec['execution_eur']} différentes de la situation comptable "
                             f"{sol['recettes_eur']}")
        if abs(tot_dep - (sol["depenses_eur"] or 0)) > 1:
            raise ValueError(f"PLRG {a} : dépenses {tot_dep} différentes de la situation comptable {sol['depenses_eur']}")
        if abs(sol["debut_eur"] + sol["recettes_eur"] - sol["depenses_eur"] - sol["fin_eur"]) > 1:
            raise ValueError(f"PLRG {a} : solde de début + recettes - dépenses différent du solde de fin")
        par_annee[str(a)] = {"source": PLRG_URL[a], "recettes": rec, "depenses": dep, "solde": sol}
    # Projet annuel de performances 2026 : recettes et crédits prévus.
    prevision = {"source": DOC["pap"]["titre"], "url": DOC["pap"]["url"], "recettes": [], "credits_723": []}
    for page, lib, cle, vals in PAP_LIGNES:
        verifier("pap", page, [lib] + [_fr(v) for v in vals], f"PAP recettes {lib}")
        prevision["recettes"].append({"ligne": cle, "libelle": lib, **{c: v for c, v in zip(PAP_COLONNES, vals)}})
    page, credits = PAP_CREDITS
    for an, ae, cp in credits:
        verifier("pap", page, [_fr(ae), _fr(cp)], f"PAP crédits {an}")
        prevision["credits_723"].append({"annee": an, "autorisations_engagement_eur": ae, "credits_paiement_eur": cp})
    # Rapport annuel de performances 2025 : rapprochement avec le PLRG.
    rap = {"source": DOC["rap"]["titre"], "url": DOC["rap"]["url"], "recettes": [], "citations": []}
    for page, lib, cle, lfi, exe in RAP_RECETTES:
        verifier("rap", page, [lib, _fr(lfi), _fr(exe)], f"RAP recettes {lib}")
        rap["recettes"].append({"ligne": cle, "libelle": lib, "lfi_eur": lfi, "execution_eur": exe})
    rap["citations"] = [citer("rap", p, t) for p, t in RAP_CITATIONS]
    r25 = par_annee["2025"]["recettes"]
    ecarts = []
    for ligne, code in (("cessions", "76101"), ("redevances", "76102")):
        s = next(x for x in r25["sections"] if x["code"] == code)
        rr = next(x for x in rap["recettes"] if x["ligne"] == ligne)
        ecarts.append({"objet": f"section {code} en 2025, prévision", "valeurs": [
            {"mesure": "évaluation des recettes reprise par le PLRG 2025", "eur": s["evaluation_eur"]},
            {"mesure": "prévision de la loi de finances initiale citée par le rapport annuel de performances 2025",
             "eur": rr["lfi_eur"]}],
            "lecture": "Les deux montants sont publiés tels quels ; la source ne détaille pas leur différence."})
        ecarts.append({"objet": f"section {code} en 2025, exécution", "valeurs": [
            {"mesure": "somme des lignes d'exécution du PLRG 2025", "eur": s["execution_eur"]},
            {"mesure": "exécution publiée par le rapport annuel de performances 2025", "eur": rr["execution_eur"]}],
            "lecture": "Le rapport arrondit à l'euro ; un écart de plus de 1 € serait publié tel quel."})
    return {
        **_entete(collecte, "Annexes CSV des PLRG 2023, 2024 et 2025 (data.economie.gouv.fr) ; projet annuel de "
                            "performances 2026 et rapport annuel de performances 2025 du compte",
                  "Comptabilité budgétaire du compte d'affectation spéciale « Gestion du patrimoine immobilier de "
                  "l'État » : ce qu'il encaisse (cessions, redevances et loyers perçus par l'État) et ce qu'il dépense "
                  "(programme 723, opérations immobilières et entretien). Le programme 721 (contribution au "
                  "désendettement) n'a pas de crédits sur la période.",
                  "euros"),
        "compte": COMPTE,
        "definitions": {
            "evaluation_eur": "évaluation des recettes de la ligne de prévision (PLRG)",
            "execution_eur": "recouvrements effectués pour une recette, dépenses constatées en crédits de paiement pour "
                             "un programme (PLRG)",
            "credits_ouverts_eur": "crédits de paiement ouverts, tous mouvements compris (PLRG)",
            "report_entrant_eur": "crédits reportés de l'année précédente", "report_sortant_eur": "crédits reportés sur "
                                                                                                    "l'année suivante",
            "solde": "situation comptable du compte : solde de début, recettes, dépenses, solde de fin (PLRG)",
            "programme_723": "Opérations immobilières et entretien des bâtiments de l'État",
            "programme_721": "Contribution des cessions immobilières au désendettement de l'État",
        },
        "par_annee": par_annee,
        "prevision_pap_2026": prevision,
        "rapport_annuel_2025": rap,
        "ecarts_entre_sources": ecarts,
    }


def produire(sortie: Path = SORTIE) -> None:
    collecte = date_sources(DOMAINE)
    compte = produire_compte(collecte)
    parc = produire_parc(collecte)
    valeur = produire_valeur(collecte)
    loyers = produire_loyers(collecte, parc)
    cessions = produire_cessions(collecte, compte)
    c25 = compte["par_annee"]["2025"]
    dep723 = next(p for p in c25["depenses"] if p["programme"] == "723")
    index = {
        **_entete(collecte, "Direction de l'immobilier de l'État (data.gouv.fr, data.economie.gouv.fr) ; document de "
                            "politique transversale « Politique immobilière de l'État » (PLF 2025) ; PLRG 2023 à 2025 ; "
                            "projet et rapport annuels de performances du compte",
                  "Ce que l'État possède ou occupe comme bâtiments et terrains, ce que ce parc vaut au bilan, ce que "
                  "l'État vend, ce qu'il paie comme loyers et ce que retrace le compte « Gestion du patrimoine "
                  "immobilier de l'État ». Chaque montant porte son année et sa source ; les mesures de sources "
                  "différentes sont publiées côte à côte, jamais additionnées.",
                  "voir chaque fichier"),
        "presentation": "Le parc immobilier de l'État : nombre de biens, surfaces, valeur au bilan, cessions, loyers "
                        "payés pour les biens pris à bail et compte d'affectation spéciale. Les séries du document "
                        "budgétaire s'arrêtent à 2023 ; le compte est suivi jusqu'en 2025.",
        "definitions": {
            "parc": "bâtiments et terrains dont l'État et ses établissements publics nationaux sont propriétaires ou "
                    "occupants (inventaire de la Direction de l'immobilier de l'État)",
            "valeur": "valeur comptable au bilan de l'État (normes comptables de l'État), pas un prix de marché",
            "cessions": "ventes de biens immobiliers de l'État (y compris baux emphytéotiques réglés en une fois)",
            "loyers": "loyers payés par l'État pour les biens qu'il prend à bail (décaissements)",
            "compte": "compte d'affectation spéciale « Gestion du patrimoine immobilier de l'État » : il encaisse les "
                      "produits de cession et les redevances domaniales et finance des opérations immobilières et "
                      "l'entretien (programme 723)",
        },
        "fichiers": [
            {"fichier": f"{DOMAINE}/parc.json", "contenu": "jeux ouverts agrégés par ministère, département, type ; "
                                                           "nombre de biens et surfaces du document budgétaire"},
            {"fichier": f"{DOMAINE}/valeur.json", "contenu": "valeur comptable 2012 à 2023, par ministère 2017 à 2023, "
                                                             "emphytéoses, opérateurs"},
            {"fichier": f"{DOMAINE}/cessions.json", "contenu": "produits de cessions par administration et par nature, "
                                                               "recettes du compte, cessions 2013 à 2017"},
            {"fichier": f"{DOMAINE}/loyers.json", "contenu": "loyers payés 2014 à 2023, dépenses immobilières, prises à "
                                                             "bail, grands baux, propriétaires par type"},
            {"fichier": f"{DOMAINE}/compte.json", "contenu": "compte d'affectation spéciale 2023 à 2025, prévisions 2026 "
                                                             "à 2028, rapprochement du rapport annuel 2025"},
        ],
        "chiffres_cles": {
            "biens_inventaire_global": {"annee": "2023", "valeur": DPT_INVENTAIRE["series"][2][3][-1],
                                        "unite": "biens", "source": "document de politique transversale, page 10",
                                        "statut": "tracé"},
            "surface_batie_sub_m2": {"annee": "2023", "valeur": DPT_SURFACES_TYPE["lignes"][-1][1][-1],
                                     "unite": "m² SUB", "source": "document de politique transversale, page 12",
                                     "statut": "tracé"},
            "valeur_comptable_meur": {"annee": "2023", "valeur": DPT_VALEUR_TOTALE["valeurs"][-1],
                                      "unite": "millions d'euros", "source": "document de politique transversale, page 15",
                                      "statut": "tracé"},
            "loyers_payes_meur": {"annee": "2023", "valeur": DPT_LOYERS["valeurs"][-1], "unite": "millions d'euros",
                                  "source": "document de politique transversale, page 23", "statut": "tracé"},
            "cessions_outil_suivi_eur": {"annee": "2023", "valeur": DPT_CESSIONS_ADMIN["total"][-1], "unite": "euros",
                                         "source": "document de politique transversale, page 29", "statut": "tracé"},
            "compte_recettes_eur": {"annee": "2025", "valeur": c25["recettes"]["execution_eur"], "unite": "euros",
                                    "source": "PLRG 2025", "statut": "tracé"},
            "compte_depenses_723_eur": {"annee": "2025", "valeur": dep723["execution_eur"], "unite": "euros",
                                        "source": "PLRG 2025", "statut": "tracé"},
            "compte_solde_fin_eur": {"annee": "2025", "valeur": c25["solde"]["fin_eur"], "unite": "euros",
                                     "source": "PLRG 2025", "statut": "tracé"},
        },
        "sources": [
            *({"nom": m["titre"], "url": m["datagouv"], "licence": "Licence Ouverte 2.0",
               "producteur": "Direction de l'immobilier de l'État"} for _, m in sorted(PARC.items())),
            {"nom": CESSIONS_2013["titre"], "url": CESSIONS_2013["datagouv"], "licence": "Licence Ouverte 2.0",
             "producteur": "Direction de l'immobilier de l'État"},
            *({"nom": f"PLRG {a}, annexes CSV des comptes spéciaux", "url": PLRG_URL[a], "licence": "Licence Ouverte 2.0",
               "producteur": "Direction du budget"} for a in ANNEES_PLRG),
            *({"nom": d["titre"], "url": d["url"], "licence": "document budgétaire public",
               "producteur": "Gouvernement (annexe budgétaire)"} for _, d in sorted(DOC.items())),
        ],
        "sources_inaccessibles": SOURCES_INACCESSIBLES,
        "limites": [
            "Les jeux ouverts du parc excluent les données confidentielles ; plusieurs ministères (dont l'Intérieur et "
            "la Transition écologique) n'y figurent pas ou presque pas, et la localisation des biens des Armées y est "
            "occultée.",
            "Les fichiers datés du 31/12/2022 et du 31/12/2023 ne mettent à jour que quelques ministères et portent "
            "tous la date de référence « 2021-12-31 » dans leur colonne ; elle est publiée telle quelle.",
            "Les séries du document de politique transversale s'arrêtent à 2023 : le document annexé au PLF 2026 n'a "
            "pas pu être collecté.",
            "Aucun bailleur n'est nommé : le document budgétaire n'en nomme aucun et les jeux ouverts ne donnent qu'un "
            "type de propriétaire (dont « personne physique », jamais détaillé).",
            "La valeur au bilan suit les normes comptables de l'État et a changé de méthode en 2018 ; elle ne mesure "
            "pas un prix de vente.",
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    for nom, doc in (("index", index), ("parc", parc), ("valeur", valeur), ("cessions", cessions),
                     ("loyers", loyers), ("compte", compte)):
        _ecrire(sortie / f"{nom}.json", doc)


def _ecrire(chemin: Path, doc: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def collecter(forcer: bool = False) -> int:
    """Collecte par collecte/collecte.py (reprises, contrôle d'intégrité, aucun contournement d'un refus d'accès)."""
    cmd = [sys.executable, str(ROOT / "collecte" / "collecte.py"), *IDS_COLLECTE]
    return subprocess.call(cmd + (["--force"] if forcer else []), cwd=ROOT)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("collecter")
    c.add_argument("--force", action="store_true")
    p = sp.add_parser("produire")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.cmd == "collecter":
        return collecter(a.force)
    produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
