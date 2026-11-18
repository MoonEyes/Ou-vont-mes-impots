"""Prélèvements hors bulletin de paie et affectation de chaque prélèvement à ses destinataires.

Entrées : entrepôt brut data/lake/ (non versionné), site/data/recettes.json (Eurostat gov_10a_taxag, déjà produit).
Sorties (chaque fichier porte `millesime`, `source` et `methode`) :
  site/data/prelevements/affectation.json        qui reçoit chaque prélèvement (parts, source exacte par part)
  site/data/prelevements/tva_conso.json          TVA et taxes sur la consommation par décile de niveau de vie
  site/data/prelevements/taxe_fonciere.json      méthode, agrégats nationaux, index des départements
  site/data/prelevements/taxe_fonciere/<dep>.json  estimation TFPB (propriétaire) et TEOM (locataire) par commune

Commandes (chacune < 9 min) :
  python pipeline/prelevements.py collecter   # réseau : sources manquantes dans data/lake/prelevements/ (reprenable)
  python pipeline/prelevements.py produire    # sans réseau : écrit site/data/prelevements/
  python pipeline/prelevements.py             # les deux (collecter ne retélécharge pas un fichier présent)

Règles :
  - aucune valeur inventée : une part ou une ventilation introuvable est marquée « non sourcée » ou absente ;
  - les paramètres lus dans des PDF officiels (annexe 3 du PLFSS 2026, Voies et moyens tome I du PLF 2026) sont saisis
    ici avec leur page, puis vérifiés automatiquement contre le texte du PDF quand il est dans l'entrepôt ;
  - openfisca-france-indirect-taxation (AGPL) n'est ni copié ni appelé : il exige les microdonnées Budget de famille
    (accès restreint) ; la méthode s'en inspire seulement (clés de consommation par poste COICOP).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "prelevements"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "prelevements"
REI_ZIP = (LAKE / "fiscalite" / "economie__impots-locaux-fichier-de-recensement-des-elements-dimposition-a-la-fiscalite-dir"
           / "REI-2025-fichier-notice-trace.zip")
ERFS_ZIP = LAKE / "comptes_nationaux" / "insee_ds_erfs_non_retropole.zip"
ANNEE = "2025"

# --- Sources téléchargées (verdict de réutilisation, licence, date) ------------------------------------------------

SOURCES = {
    "insee_ia88": {
        "fichier": "insee_IA88.xlsx",
        "url": "https://www.insee.fr/fr/statistiques/fichier/7669723/IA88.xlsx",
        "page": "https://www.insee.fr/fr/statistiques/7669723",
        "titre": "Insee Analyses n° 88 (sept. 2023, erratum 20/06/2025) : redistribution élargie, comptes nationaux "
                 "distribués 2019, tableaux complémentaires par vingtième de niveau de vie",
        "producteur": "Insee", "licence": "Licence Ouverte 2.0 (réutilisation libre avec mention de l'Insee)",
        "verdict": "réutilisable tel quel (montants par UC et par vingtième, recalés sur les comptes nationaux 2019)",
    },
    "insee_bdf_tf106": {
        "fichier": "insee_bdf2017_TF106.csv",
        "url": "https://www.insee.fr/fr/statistiques/fichier/4648335/TF106.csv",
        "page": "https://www.insee.fr/fr/statistiques/4648335",
        "titre": "Enquête Budget de famille 2017, TF106 : dépenses annuelles moyennes par ménage selon le décile de "
                 "niveau de vie (nomenclature COICOP 5 positions), publié le 15/09/2020",
        "producteur": "Insee", "licence": "Licence Ouverte 2.0",
        "verdict": "à adapter (structure de consommation 2017 utilisée comme clé de ventilation, pas comme montant)",
    },
    "insee_bdf_tf306": {
        "fichier": "insee_bdf2017_TF306.csv",
        "url": "https://www.insee.fr/fr/statistiques/fichier/4648335/TF306.csv",
        "page": "https://www.insee.fr/fr/statistiques/4648335",
        "titre": "Enquête Budget de famille 2017, TF306 : taux d'équipement selon le décile de niveau de vie "
                 "(code 30 : au moins une voiture)",
        "producteur": "Insee", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel",
    },
    "plfss2026_annexe3": {
        "fichier": "PLFSS2026_annexe3.pdf",
        "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1089896/file/"
               "PLFSS2026-Annexe3-20251015-103900-55-4.pdf",
        "titre": "PLFSS 2026, annexe 3, tableau 31 « Répartition des impositions affectées à la sécurité sociale "
                 "entre 2018 et 2025 » (p. 43 à 48), octobre 2025",
        "producteur": "Direction de la sécurité sociale", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "réutilisable tel quel (parts lues dans le tableau, vérifiées contre le texte du PDF)",
    },
    "plf2026_vm1": {
        "fichier": "PLF2026_voies_et_moyens_tome1.pdf",
        "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1087930/file/"
               "PLF%202026%20-%20V%26M%20TI%20-%20Evaluations%20des%20recettes.pdf",
        "titre": "PLF 2026, Évaluation des voies et moyens tome I (recettes) : TVA p. 34, accise ex-TICPE p. 28, "
                 "prévision révisée 2025, octobre 2025",
        "producteur": "Direction du budget / DGFiP", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "réutilisable tel quel (montants 2025 révisés, vérifiés contre le texte du PDF)",
    },
    "pap2026_cas_pensions": {
        "fichier": "PAP2026_CAS_Pensions.pdf",
        "url": "https://www.assemblee-nationale.fr/dyn/dyn/contenu/visualisation/1088071/file/"
               "PAP2026_CS_CAS_Pensions_YD.pdf",
        "titre": "PLF 2026, projet annuel de performances du compte d'affectation spéciale « Pensions » : objet du "
                 "compte (recettes au titre de l'article L. 61 du code des pensions civiles et militaires) et lignes de "
                 "recettes 01, 21 et 33 (LFI 2025), octobre 2025",
        "producteur": "Direction du budget / Service des retraites de l'État",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "réutilisable tel quel (destinataire et montants LFI 2025 lus dans le document, vérifiés contre le PDF)",
    },
    "jaune2026_pensions": {
        "fichier": "Jaune2026_Pensions.pdf",
        "url": "https://questions.assemblee-nationale.fr/dyn/contenu/visualisation/1090002/file/12-Jaune2026_Pensions.pdf",
        "titre": "PLF 2026, annexe « Rapport sur les pensions de retraite de la fonction publique » (jaune) : fiches "
                 "CNRACL, ERAFP (RAFP) et Ircantec, tableau des régimes des agents publics, octobre 2025",
        "producteur": "Direction du budget, DGAFP, DSS, Caisse des dépôts",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "réutilisable tel quel (gestionnaire, textes de référence, taux et montants 2024 lus dans les fiches)",
    },
    "cnav_circulaire_2024_23": {
        "fichier": "cnav_circulaire_2024_23.pdf",
        "url": "https://legislation.lassuranceretraite.fr/Pdf/circulaire_cnav_2024_23_16072024.pdf",
        "titre": "Cnav, circulaire n° 2024-23 du 16 juillet 2024 : droits à la retraite des micro-entrepreneurs, "
                 "répartition du forfait par risques (CSS art. L. 613-7 et D. 613-6)",
        "producteur": "Caisse nationale d'assurance vieillesse (Assurance retraite)",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "réutilisable tel quel (clés de répartition par risque et régime gestionnaire de la retraite)",
    },
    "cnav_circulaire_2025_14": {
        "fichier": "cnav_circulaire_2025_14.pdf",
        "url": "https://legislation.lassuranceretraite.fr/Pdf/circulaire_cnav_2025_14_04042025.pdf",
        "titre": "Cnav, circulaire n° 2025-14 du 4 avril 2025 : assiette des cotisations des travailleurs "
                 "indépendants (retraite de base : CSS art. L. 241-3 et D. 633-3 ; RCI : art. D. 635-7)",
        "producteur": "Caisse nationale d'assurance vieillesse (Assurance retraite)",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "réutilisable tel quel (rattachement de la retraite de base au régime général et du RCI)",
    },
}

SOURCES_LAC = {
    "rei_2025": {
        "chemin": str(REI_ZIP.relative_to(ROOT)),
        "titre": "DGFiP, fichier de recensement des éléments d'imposition à la fiscalité directe locale (REI) 2025",
        "page": "https://data.economie.gouv.fr/explore/dataset/"
                "impots-locaux-fichier-de-recensement-des-elements-dimposition-a-la-fiscalite-dir/",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel (déjà dans l'entrepôt)",
    },
    "erfs_2024": {
        "chemin": str(ERFS_ZIP.relative_to(ROOT)),
        "titre": "Insee, ERFS, indicateurs de niveau de vie (DS_ERFS_NON_RETROPOLE, API Melodi), déciles 2024",
        "page": "https://api.insee.fr/melodi/catalog/all",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel (déjà dans l'entrepôt)",
    },
    "eurostat_taxag": {
        "chemin": "site/data/recettes.json",
        "titre": "Eurostat gov_10a_taxag (impôts par administration bénéficiaire), produit par pipeline/transform.py",
        "page": "https://ec.europa.eu/eurostat/databrowser/view/gov_10a_taxag/default/table",
        "licence": "réutilisation libre avec mention d'Eurostat", "verdict": "réutilisable tel quel (déjà en place)",
    },
}

ECARTEES = [
    {"nom": "openfisca-france-indirect-taxation", "url": "https://github.com/openfisca/openfisca-france-indirect-taxation",
     "licence": "AGPL-3.0", "verdict": "inspiration seulement",
     "raison": "calcule la fiscalité indirecte à partir des microdonnées Budget de famille, en accès restreint "
               "(CASD, Quetelet) : inutilisable ici sans ces données ; rien n'en est copié dans le dépôt (MIT)."},
    {"nom": "Insee, comptes nationaux distribués (Insee Analyses n° 88)", "verdict": "réutilisé",
     "raison": "seule publication ouverte qui ventile toutes les taxes sur les produits par niveau de vie avec "
               "recalage sur les comptes nationaux."},
    {"nom": "IPP, Conseil des prélèvements obligatoires", "verdict": "non retenu",
     "raison": "pas de tableau ouvert et récent de TVA ou d'accises par décile trouvé ; les barèmes IPP (fiscalité "
               "indirecte, dans l'entrepôt) ne servent qu'à vérifier les taux."},
    {"nom": "Légifrance (articles L. 131-8 et L. 136-8 CSS)", "verdict": "accès refusé (HTTP 403)",
     "raison": "aucun contournement : les parts de CSG sont lues dans l'annexe 3 du PLFSS 2026 (tableau 31), "
               "qui reproduit l'état du droit 2025 ; les articles restent cités comme base légale."},
    {"nom": "Circulaires de l'Assurance maladie (circulaires.ameli.fr), intégration des indépendants",
     "url": "https://circulaires.ameli.fr/", "verdict": "inaccessible (connexion interrompue, 4 essais, 18/11/2026)",
     "raison": "seule source primaire repérée pour le destinataire des cotisations maladie-maternité et "
               "invalidité-décès des indépendants : ces deux clés restent non publiées."},
    {"nom": "Assurance retraite, « La protection sociale des travailleurs indépendants » (statistiques-recherche)",
     "url": "https://www.statistiques-recherche.lassuranceretraite.fr/", "verdict": "inaccessible (HTTP 503, 3 essais)",
     "raison": "aucun contournement ; les circulaires Cnav 2024-23 et 2025-14 suffisent pour la retraite."},
    {"nom": "Instance de gestion du régime local d'assurance maladie d'Alsace-Moselle (regime-local.fr)",
     "url": "https://www.regime-local.fr/", "verdict": "inaccessible (certificat TLS non valide)",
     "raison": "la vérification TLS n'est jamais désactivée ; le destinataire est lu dans l'annexe 3 du PLFSS 2026."},
    {"nom": "Service-public.fr Entreprendre, fiche F36238 (cotisations d'un entrepreneur individuel)",
     "url": "https://entreprendre.service-public.gouv.fr/vosdroits/F36238", "verdict": "non retenu",
     "raison": "liste les cotisations payées à l'Urssaf sans nommer le destinataire de chaque risque."},
]

# --- Paramètres d'affectation saisis depuis les documents (vérifiés contre le PDF par `verifier_documents`) --------

A3 = "PLFSS 2026, annexe 3, tableau 31, colonne 2025"
VM = "PLF 2026, Évaluation des voies et moyens tome I, prévision révisée 2025"

# Chaque motif doit apparaître (espaces normalisés) dans le texte du PDF correspondant. Motifs courts : la mise en
# page des tableaux varie selon l'extracteur de texte, les nombres et libellés de cellules restent.
MOTIFS_A3 = [
    "AM : 4,25 pt", "CNAF : 0,95 pt", "CADES : 0,45 pt", "CNSA : 2,08 pt", "UNEDIC : 1,47 pt",
    "Pour une fraction de 23,24", "5,18", "3,35 Md€",
    "11 423 12 086", "CNAM : 100%",
    "2 173 2 175", "maladie : 46,60 %", "vieillesse : 24,51 %", "RCO : 28,89%",
    "734 732", "1 081 1 067", "98 101", "54 56",
    "8 136 8 256", "2 562 2 518", "107 550", "110 432",
]
MOTIFS_VM = [
    "210,7 210,0 215,4", "-57,9 -56,4 -54,8", "-52,1 -52,7 -47,5", "-4,0 -4,0 -3,9", "96,8 96,9 109,1",
    "31,6 31,4 31,5", "-11,9 -12,0 -11,7", "-1,7 -1,2 -1,6", "-0,1 -0,1", "-2,0 -1,6 -1,5", "18,1 18,1 16,8",
    "(5 172 M€)",
]
# Revenus de remplacement (pensions), Casa, régime local : même tableau 31 et partie 3 de l'annexe 3.
MOTIFS_A3_REMPLACEMENT = [
    "AM : 1,88 pt CNAF : 0,95 pt CADES : 0,45 pt FSV : 2,94 pt CNSA : 2,08 pt",
    "AM : 0,18 pt CNAF : 0,95 pt CADES : 0,45 pt FSV : 2,94 pt CNSA : 2,08 pt",
    "AM : 1,27 pt CADES : 0,45 pt CNSA : 2,08 pt",
    "29 013 27 828", "977 950", "CNSA CNSA CNSA",
    "spécifiques au régime local d’Alsace-Moselle",
]
MOTIFS_PAP_PENSIONS = [
    "la cotisation à la charge des agents prévue au 2° de l’article L. 61",
    "Pensions civiles et militaires de retraite et allocations temporaires d’invalidité",
    "4 870 568 312", "35 077 620 585", "177 174 917",
]
MOTIFS_JAUNE = [
    "gestion : SRE", "décret n° 2007-173 du 7 février 2007, la CNRACL", "au taux de 11,10 % en 2024",
    "31,65 % en 2024", "2,25 Md€ de cotisations collectées", "Taux : 5 % salarial et 5 % patronal",
    "Décret n°2004-569 du 18 juin 2004", "Décret n° 70-1277 du 23 décembre 1970",
    "Gestion confiée à la Caisse des dépôts (CDC)", "5 201 M€ de produits",
    "Depuis le 01/01/2017 2,80% 4,20% 6,95% 12,55%",
]
MOTIFS_CNAV_2024 = [
    "Articles L.613-7 (II alinéa 2) et D.613-6 du CSS", "retraite de base 41,80%", "retraite complémentaire 16,50%",
    "maladie-maternité 8,90%", "invalidité-décès 3,10%",
]
MOTIFS_CNAV_2025 = [
    "Articles L.241-3, D.242-4 et D.633-3 du CSS", "Articles L.241-3 du CSS et D.635-7 du CSS",
    "régime complémentaire des indépendants (RCI)",
]
# Documents vérifiés : (clé de SOURCES, motifs, pages lues ; None = tout le document).
DOCUMENTS_VERIFIES = [
    ("plfss2026_annexe3", MOTIFS_A3 + MOTIFS_A3_REMPLACEMENT, range(20, 60)),
    ("plf2026_vm1", MOTIFS_VM, None),
    ("pap2026_cas_pensions", MOTIFS_PAP_PENSIONS, None),
    ("jaune2026_pensions", MOTIFS_JAUNE, (33, 56, 73, 83, 92, 93)),
    ("cnav_circulaire_2024_23", MOTIFS_CNAV_2024, None),
    ("cnav_circulaire_2025_14", MOTIFS_CNAV_2025, None),
]

DESTINATAIRES = {
    "etat": {"nom": "État (budget général)", "administration": "Etat"},
    "cnam": {"nom": "Assurance maladie (CNAM et régimes d'assurance maladie)", "administration": "Securite sociale"},
    "cnav": {"nom": "Assurance retraite (CNAV, branche vieillesse)", "administration": "Securite sociale"},
    "cnaf": {"nom": "Allocations familiales (CNAF)", "administration": "Securite sociale"},
    "branche_atmp": {"nom": "Branche accidents du travail et maladies professionnelles", "administration": "Securite sociale"},
    "cnsa": {"nom": "Branche autonomie (CNSA)", "administration": "Securite sociale"},
    "cades": {"nom": "Caisse d'amortissement de la dette sociale (CADES)", "administration": "Securite sociale"},
    "unedic": {"nom": "Assurance chômage (Unédic)", "administration": "Securite sociale"},
    "agirc_arrco": {"nom": "Retraite complémentaire (Agirc-Arrco)", "administration": "Securite sociale"},
    "fnal": {"nom": "Fonds national d'aide au logement (FNAL)", "administration": "Etat"},
    "acoss": {"nom": "Urssaf Caisse nationale (ACOSS), répartie ensuite entre branches", "administration": "Securite sociale"},
    "msa_maladie": {"nom": "MSA, non-salariés agricoles, maladie", "administration": "Securite sociale"},
    "msa_vieillesse": {"nom": "MSA, non-salariés agricoles, vieillesse", "administration": "Securite sociale"},
    "msa_rco": {"nom": "MSA, retraite complémentaire obligatoire des non-salariés agricoles", "administration": "Securite sociale"},
    "collectivites_territoriales": {"nom": "Collectivités territoriales (régions, départements, bloc communal)",
                                    "administration": "Collectivites locales"},
    "audiovisuel_public": {"nom": "Audiovisuel public (compte de concours financiers)", "administration": "Etat"},
    "afitf": {"nom": "Agence de financement des infrastructures de transport de France (AFITF)", "administration": "Etat"},
    "idfm": {"nom": "Île-de-France Mobilités", "administration": "Collectivites locales"},
    "zni_cspe": {"nom": "Fractions ZNI et CSPE (péréquation tarifaire, énergies renouvelables)", "administration": "Etat"},
    "commune": {"nom": "Commune", "administration": "Collectivites locales"},
    "epci": {"nom": "Intercommunalité (EPCI à fiscalité propre, y compris taxe GEMAPI)", "administration": "Collectivites locales"},
    "syndicats": {"nom": "Syndicats de communes fiscalisés", "administration": "Collectivites locales"},
    "tse": {"nom": "Établissements publics fonciers et Société des grands projets (taxes spéciales d'équipement)",
            "administration": "Etat"},
    "region_idf": {"nom": "Région Île-de-France (taxe additionnelle spéciale annuelle)", "administration": "Collectivites locales"},
    "bloc_communal_dechets": {"nom": "Commune ou groupement compétent pour les déchets (commune, EPCI, syndicat)",
                              "administration": "Collectivites locales"},
    # Profils étendus (fonctionnaires, contractuels du public, retraités, indépendants, Alsace-Moselle).
    "fsv": {"nom": "Fonds de solidarité vieillesse (FSV)", "administration": "Securite sociale"},
    "cas_pensions": {"nom": "État, compte d'affectation spéciale « Pensions » (géré par le Service des retraites de "
                            "l'État)", "administration": "Etat"},
    "cnracl": {"nom": "Caisse nationale de retraites des agents des collectivités locales (CNRACL, gérée par la Caisse "
                      "des dépôts)", "administration": "Securite sociale"},
    "ircantec": {"nom": "Ircantec (retraite complémentaire des agents publics contractuels, gérée par la Caisse des "
                        "dépôts)", "administration": "Securite sociale"},
    "erafp": {"nom": "Retraite additionnelle de la fonction publique (ERAFP)", "administration": "Securite sociale"},
    "rci_independants": {"nom": "Retraite complémentaire des indépendants (RCI, gérée par l'Assurance retraite)",
                         "administration": "Securite sociale"},
    "regime_local_am": {"nom": "Régime local d'assurance maladie d'Alsace-Moselle", "administration": "Securite sociale"},
}


def _part(dest, part, source, **kw):
    return {"destinataire": dest, "part": round(part, 6), "source": source, **kw}


def affectation_parametres(rei_tf: dict | None) -> dict:
    """Parts 2025 de chaque prélèvement. Toute part est accompagnée de sa source exacte."""
    p = {}
    unique = [
        ("vieillesse_plafonnee", "Cotisation d'assurance vieillesse plafonnée (salarié et employeur)", "cnav",
         "CSS art. L. 241-3 ; L. 222-1 (gestion par la CNAV)"),
        ("vieillesse_deplafonnee", "Cotisation d'assurance vieillesse déplafonnée (salarié et employeur)", "cnav",
         "CSS art. L. 241-3"),
        ("maladie", "Cotisation patronale d'assurance maladie, maternité, invalidité, décès", "cnam", "CSS art. L. 241-2"),
        ("famille", "Cotisation patronale d'allocations familiales", "cnaf", "CSS art. L. 241-6"),
        ("atmp", "Cotisation accidents du travail et maladies professionnelles", "branche_atmp", "CSS art. L. 241-5"),
        ("agirc_arrco", "Cotisations de retraite complémentaire Agirc-Arrco (tranches 1 et 2)", "agirc_arrco",
         "Accord national interprofessionnel du 17 novembre 2017 instituant le régime Agirc-Arrco"),
        ("ceg", "Contribution d'équilibre général (CEG)", "agirc_arrco",
         "Accord national interprofessionnel du 17 novembre 2017 (Agirc-Arrco), contribution d'équilibre général"),
        ("chomage", "Contribution patronale d'assurance chômage", "unedic",
         "Code du travail art. L. 5422-9 (contributions) et L. 5427-1 (gestion par l'Unédic)"),
        ("fnal", "Contribution au Fonds national d'aide au logement (0,1 % ou 0,5 %)", "fnal",
         "CSS art. L. 834-1 ; PLFSS 2026 annexe 3, partie 3 : « FNAL, affectataire des contributions patronales de "
         "0,1 % ou de 0,5 % »"),
        ("crds", "Contribution au remboursement de la dette sociale (CRDS)", "cades",
         "Ordonnance n° 96-50 du 24 janvier 1996, art. 14 et 19 ; " + A3 + " (8 256 M€ prévus en 2025)"),
        ("csa", "Contribution solidarité autonomie (0,3 %)", "cnsa",
         "Loi n° 2004-626 du 30 juin 2004, art. 11 ; CASF art. L. 14-10-4 ; " + A3 + " (2 518 M€ prévus en 2025)"),
        ("impot_revenu", "Impôt sur le revenu", "etat",
         "Recette du budget général de l'État (LFI 2025, état A, ligne 1101) ; aucune fraction affectée"),
        ("tabac", "Droit de consommation sur les tabacs", "cnam",
         "CGI art. 575 ; " + A3 + " : « CNAM : 100 % » (12 086 M€ prévus en 2025)"),
    ]
    for pid, lib, dest, ref in unique:
        p[pid] = {"libelle": lib, "statut": "sourcee", "ventilation": [_part(dest, 1.0, ref)], "reference_juridique": ref}
    p["chomage"]["note"] = ("L'Unédic reverse ensuite une part de ses ressources à France Travail (Code du travail "
                           "art. L. 5422-24) : taux 2025 non sourcé ici, donc non déduit.")
    p["fnal"]["note"] = ("Administration de rattachement du FNAL à confirmer en comptabilité nationale (contrat "
                        "d'interface, 3.5).")

    # CSG sur les revenus d'activité : 9,2 points (6,8 déductibles + 2,4 non déductibles), même clé pour les deux.
    csg = [("cnam", 4.25), ("cnsa", 2.08), ("unedic", 1.47), ("cnaf", 0.95), ("cades", 0.45)]
    total_csg = sum(v for _, v in csg)
    assert abs(total_csg - 9.2) < 1e-9
    p["csg_activite"] = {
        "libelle": "CSG sur les revenus d'activité (9,2 % : 6,8 % déductible et 2,4 % non déductible)",
        "statut": "sourcee", "points": dict(csg),
        "ventilation": [_part(d, v / total_csg, f"{A3} : « {d.upper() if d != 'cnam' else 'AM'} : "
                                                  f"{str(v).replace('.', ',')} pt »", points=v) for d, v in csg],
        "reference_juridique": "CSS art. L. 136-8 (taux) et L. 131-8 (affectation), dans leur rédaction applicable "
                               "en 2025 ; répartition reproduite par " + A3 + " (110 432 M€ prévus en 2025)",
        "note": "« AM » désigne les régimes d'assurance maladie (CNAM pour un salarié du privé). La clé est la même "
                "pour la CSG déductible et la CSG non déductible : la loi affecte des points de CSG, pas la part "
                "déductible.",
    }

    # TVA nette 2025 (comptabilité budgétaire) : État, sécurité sociale, collectivités, audiovisuel public.
    tva = {"etat": 96.9, "secu": 56.4, "collectivites_territoriales": 52.7, "audiovisuel_public": 4.0}
    tva_tot = 210.0
    assert abs(sum(tva.values()) - tva_tot) < 0.05
    cnam_md = 0.2324 * tva_tot
    acoss_md = 0.0518 * tva_tot - 3.35
    secu_cnam = tva["secu"] * cnam_md / (cnam_md + acoss_md)
    secu_acoss = tva["secu"] - secu_cnam
    src_tva = VM + " (tableau p. 34 : TVA nette totale 210,0 Md€)"
    p["tva"] = {
        "libelle": "Taxe sur la valeur ajoutée (TVA nette)", "statut": "sourcee", "total_md": tva_tot,
        "ventilation": [
            _part("etat", tva["etat"] / tva_tot, src_tva + " : TVA nette État 96,9 Md€", montant_md=tva["etat"]),
            _part("cnam", secu_cnam / tva_tot, src_tva + " : transferts à la sécurité sociale 56,4 Md€, répartis "
                  "entre CNAM et ACOSS selon les fractions de " + A3 + " (23,24 % à la CNAM ; 5,18 % à l'ACOSS "
                  "minorés de 3,35 Md€)", montant_md=round(secu_cnam, 3)),
            _part("acoss", secu_acoss / tva_tot, "idem", montant_md=round(secu_acoss, 3)),
            _part("collectivites_territoriales", tva["collectivites_territoriales"] / tva_tot,
                  src_tva + " : transferts aux collectivités territoriales 52,7 Md€",
                  montant_md=tva["collectivites_territoriales"],
                  dont=[{"destinataire": "régions (fraction remplaçant la DGF depuis 2018)", "montant_md": 5.172,
                         "source": "PLF 2026, Voies et moyens tome I, ligne 3101 (DGF) : « fractions de TVA aux "
                                   "régions (5 172 M€) »"}],
                  note="Le reste (départements, Ville de Paris, EPCI, communes : compensations de la taxe "
                       "d'habitation, de la part départementale de foncier bâti et de la CVAE) n'est pas ventilé "
                       "par bénéficiaire dans ce document : non sourcé à ce niveau."),
            _part("audiovisuel_public", tva["audiovisuel_public"] / tva_tot,
                  src_tva + " : compensation audiovisuel public 4,0 Md€", montant_md=tva["audiovisuel_public"]),
        ],
        "reference_juridique": "CGI art. 256 et suivants ; LFI 2018 art. 149 (régions) ; LFI 2020 art. 16 et LFI "
                               "2023 art. 55 (collectivités) ; CSS art. L. 131-8 (sécurité sociale) ; LFR 2022 "
                               "(audiovisuel public)",
        "note": "Comptabilité budgétaire. En comptabilité nationale (Eurostat D211, 2025) : État 98,70, collectivités "
                "52,75, sécurité sociale 57,37 Md€, ensemble 208,82 Md€ (site/data/recettes.json), contre 210,0 Md€ ici : "
                "les deux sources n'ont ni la même comptabilité ni la même date, parts et montants diffèrent donc "
                "(moins d'un point sur la part de l'État).",
    }

    # Accise sur les produits énergétiques (ex-TICPE), 2025.
    ticpe = [("etat", 18.1, "accise ex-TICPE brute État 18,1 Md€"),
             ("collectivites_territoriales", 12.0, "transfert aux collectivités territoriales 12,0 Md€"),
             ("afitf", 1.2, "transfert à l'AFITF 1,2 Md€"),
             ("idfm", 0.1, "transfert Île-de-France Mobilités 0,1 Md€"),
             ("zni_cspe", 0.1, "fraction ZNI et fraction CSPE 0,1 Md€")]
    t_tot = sum(v for _, v, _ in ticpe)
    p["ticpe"] = {
        "libelle": "Accise sur les produits énergétiques (ex-TICPE)", "statut": "sourcee", "brute_totale_md": 31.4,
        "ventilation": [_part(d, v / t_tot, VM + f" (tableau p. 28) : {lib}", montant_md=v) for d, v, lib in ticpe],
        "reference_juridique": "Code des impositions sur les biens et services (CIBS), accise sur les énergies ; "
                               "LFI 2005 art. 52 et LFI 2014 (fractions régionales et départementales)",
        "note": "Parts calculées sur la somme des destinataires (31,5 Md€) ; la ligne « Autres » (+0,2 Md€) et les "
                "arrondis du tableau (brute totale 31,4 Md€) ne sont pas ventilés. Les remboursements aux "
                "professionnels (1,6 Md€) sont imputés sur la part de l'État. Répartition entre régions et "
                "départements non sourcée dans ce document.",
    }

    # Alcools : droit de consommation (art. 403 CGI) et droits annexes.
    alc = {"droit_consommation": 2175, "cotisation_18": 732, "bieres": 1067, "vins": 101, "produits_intermediaires": 56}
    dc = alc["droit_consommation"]
    msa_m = 0.4660 * dc
    msa_v = 0.2451 * dc + alc["cotisation_18"] + alc["bieres"] + alc["vins"] + alc["produits_intermediaires"]
    msa_r = 0.2889 * dc
    a_tot = sum(alc.values())
    p["alcool"] = {
        "libelle": "Droits sur les alcools (droit de consommation, droits de circulation, cotisation > 18°)",
        "statut": "sourcee", "montants_2025_m": alc,
        "ventilation": [
            _part("msa_maladie", msa_m / a_tot, A3 + " : droit de consommation, « CCMSA non salariés - maladie : "
                  "46,60 % »", montant_md=round(msa_m / 1000, 3)),
            _part("msa_vieillesse", msa_v / a_tot, A3 + " : droit de consommation « vieillesse : 24,51 % » ; "
                  "cotisation > 18°, droits sur bières, vins et produits intermédiaires : « CCMSA non salariés - "
                  "vieillesse » (cellule fusionnée du tableau)", montant_md=round(msa_v / 1000, 3)),
            _part("msa_rco", msa_r / a_tot, A3 + " : droit de consommation, « RCO : 28,89 % »",
                  montant_md=round(msa_r / 1000, 3)),
        ],
        "reference_juridique": "CGI art. 403, 438, 520 A et 402 bis ; CSS art. L. 245-7 à L. 245-11",
        "note": "L'attribution de la cotisation > 18° et des droits de circulation à la MSA vieillesse est lue dans "
                "une cellule fusionnée du tableau 31 (même ligne visuelle) : à confirmer si le document est republié.",
    }

    if rei_tf:
        tot = sum(rei_tf["montants_m"].values())
        lib = {"commune": "E13 (part communale)", "epci": "E33 (part intercommunale) + E53gGEMAPI",
               "syndicats": "E23 (syndicats)", "tse": "E53 + E53A (taxes spéciales d'équipement)",
               "region_idf": "E53TASA (TASA)", "etat": "E00 (frais d'assiette, de dégrèvement et de non-valeurs)"}
        p["taxe_fonciere"] = {
            "libelle": "Taxe foncière sur les propriétés bâties (et taxes annexes adossées)", "statut": "sourcee",
            "total_md": round(tot / 1000, 3),
            "ventilation": [_part(d, v / tot, f"DGFiP, REI 2025, somme nationale de {lib[d]}",
                                  montant_md=round(v / 1000, 3))
                            for d, v in sorted(rei_tf["montants_m"].items(), key=lambda kv: -kv[1]) if v > 0],
            "reference_juridique": "CGI art. 1380 et 1388 (TFPB), 1636 B sexies (taux), 1607 bis à 1609 G (TSE, "
                                   "TASA), 1530 bis (GEMAPI), 1641 (frais de gestion perçus par l'État)",
            "note": "Moyenne nationale ; la répartition propre à chaque commune est dans taxe_fonciere/<dep>.json. "
                    "Depuis 2021 la part départementale est transférée aux communes : les départements ne la "
                    "perçoivent plus.",
        }
    else:
        p["taxe_fonciere"] = {"libelle": "Taxe foncière sur les propriétés bâties", "statut": "non sourcee",
                              "ventilation": [], "note": "REI 2025 absent de l'entrepôt : parts non calculées."}
    p["teom"] = {
        "libelle": "Taxe d'enlèvement des ordures ménagères (payée par le locataire via les charges)",
        "statut": "sourcee",
        "ventilation": [_part("bloc_communal_dechets", 1.0, "CGI art. 1520 et 1379-0 bis ; DGFiP REI 2025 (F13)")],
        "reference_juridique": "CGI art. 1520 (commune), 1379-0 bis (EPCI) ; décret n° 87-713 du 26 août 1987 "
                               "(charges récupérables sur le locataire)",
        "note": "Le REI ne dit pas, commune par commune, si la TEOM revient à la commune, à l'EPCI ou à un syndicat : "
                "ventilation interne au bloc communal non sourcée.",
    }
    p.update(affectation_etendue())
    return p


PAP = "PLF 2026, projet annuel de performances du compte d'affectation spéciale « Pensions »"
JAUNE = "PLF 2026, rapport sur les pensions de retraite de la fonction publique (jaune)"
CNAV24 = "Cnav, circulaire n° 2024-23 du 16 juillet 2024"
CNAV25 = "Cnav, circulaire n° 2025-14 du 4 avril 2025"
QUALITE = ("« trace » : le document désigne un seul destinataire, ou publie les points de chaque destinataire, et la "
           "part est lue telle quelle ; « approche » : le destinataire publié vaut pour le cas le plus courant, mais "
           "dépend d'une situation que le calcul ne connaît pas (précisée dans la note).")


def affectation_etendue() -> dict:
    """Profils étendus du calcul personnel : retraités, fonctionnaires, contractuels du public, indépendants,
    Alsace-Moselle. Chaque entrée sourcée cite un document primaire vérifié contre son PDF (DOCUMENTS_VERIFIES) ;
    une entrée sans destinataire publié reste « non sourcee », sans ventilation."""
    p = {}

    # CSG sur les pensions : une clé par taux, les points diffèrent (tableau 31, colonne 2025).
    taux_csg = {
        "csg_remplacement_taux_normal": ("taux normal de 8,3 % (5,9 % déductible et 2,4 % non déductible)",
                                         "retraites / invalidité, taux normal",
                                         [("cnam", 1.88), ("cnaf", 0.95), ("cades", 0.45), ("fsv", 2.94), ("cnsa", 2.08)],
                                         8.3),
        "csg_remplacement_taux_median": ("taux médian de 6,6 % (4,2 % déductible et 2,4 % non déductible)",
                                         "taux intermédiaire / pensions",
                                         [("cnam", 0.18), ("cnaf", 0.95), ("cades", 0.45), ("fsv", 2.94), ("cnsa", 2.08)],
                                         6.6),
        "csg_remplacement_taux_reduit": ("taux réduit de 3,8 % (entièrement déductible)", "taux réduit",
                                         [("cnam", 1.27), ("cades", 0.45), ("cnsa", 2.08)], 3.8),
    }
    for cle, (lib, ligne, pts, total) in taux_csg.items():
        assert abs(sum(v for _, v in pts) - total) < 1e-9, cle
        p[cle] = {
            "libelle": f"CSG sur les pensions de retraite et d'invalidité, {lib}",
            "statut": "sourcee", "qualite": "trace", "points": dict(pts),
            "ventilation": [_part(d, v / total, f"{A3}, CSG sur les revenus de remplacement, ligne « {ligne} » : "
                                                f"« {'AM' if d == 'cnam' else d.upper()} : {str(v).replace('.', ',')} pt »",
                                  points=v) for d, v in pts],
            "reference_juridique": "CSS art. L. 136-8 (taux) et L. 131-8 (affectation), rédaction applicable en 2025 ; "
                                   "répartition reproduite par " + A3 + " (CSG sur les revenus de remplacement : "
                                   "27 828 M€ prévus en 2025, tous taux et toutes natures de revenus confondus)",
            "note": "« AM » désigne les régimes d'assurance maladie, rattachés ici à l'assurance maladie (CNAM) comme "
                    "pour la CSG sur les revenus d'activité. Même clé pour la part déductible et la part non "
                    "déductible : la loi affecte des points de CSG. Le calcul choisit la clé selon le taux de la "
                    "personne (correspondance_calcul_selon_taux).",
        }

    p["casa"] = {
        "libelle": "Contribution additionnelle de solidarité pour l'autonomie (Casa, 0,3 % des pensions)",
        "statut": "sourcee", "qualite": "trace",
        "ventilation": [_part("cnsa", 1.0, A3 + " : contribution additionnelle de solidarité autonomie, affectataire "
                                            "« CNSA » (950 M€ prévus en 2025)")],
        "reference_juridique": "CASF art. L. 14-10-4 ; " + A3,
    }

    p["pension_civile_etat"] = {
        "libelle": "Retenue pour pension civile des fonctionnaires de l'État et contribution employeur de l'État",
        "statut": "sourcee", "qualite": "trace",
        "ventilation": [_part("cas_pensions", 1.0, PAP + " : recettes de la section 1 (« cotisation à la charge des "
                              "agents prévue au 2° de l'article L. 61 » et contribution employeur du 1°) ; LFI 2025 : "
                              "ligne 01 retenues pour pensions 4 870,6 M€, ligne 21 contributions des employeurs "
                              "35 077,6 M€ ; gestion par le Service des retraites de l'État (" + JAUNE + ")")],
        "reference_juridique": "Code des pensions civiles et militaires de retraite, art. L. 61 ; loi n° 2005-1719 du "
                               "30 décembre 2005, art. 51 (compte d'affectation spéciale « Pensions »)",
        "note": "La contribution employeur de l'État est une dépense du budget de l'État versée à ce compte de "
                "l'État : flux interne à l'État. Les montants cités couvrent les agents propres de l'État (ligne 01) "
                "et les agents civils de l'État (ligne 21), hors autres lignes de recettes du compte.",
    }
    p["allocation_temporaire_invalidite"] = {
        "libelle": "Contribution employeur au titre de l'allocation temporaire d'invalidité (fonctionnaires de l'État)",
        "statut": "sourcee", "qualite": "trace",
        "ventilation": [_part("cas_pensions", 1.0, PAP + " : « une contribution employeur versée au titre du "
                              "financement des allocations temporaires d'invalidité » ; LFI 2025 : ligne 33, "
                              "177,2 M€")],
        "reference_juridique": "Code général de la fonction publique, art. L. 824-1 ; " + PAP,
    }
    p["cnracl"] = {
        "libelle": "Retenue pour pension et contribution employeur des fonctionnaires territoriaux et hospitaliers",
        "statut": "sourcee", "qualite": "trace",
        "ventilation": [_part("cnracl", 1.0, JAUNE + ", partie CNRACL : régime « régi par le décret n° 2007-173 du "
                              "7 février 2007 », gestion confiée à la Caisse des dépôts ; cotisations des actifs "
                              "« au taux de 11,10 % en 2024 » et des employeurs « 31,65 % en 2024 »")],
        "reference_juridique": "Ordonnance n° 45-993 du 17 mai 1945 ; décret n° 2007-173 du 7 février 2007 ; décret "
                               "n° 2003-1306 du 26 décembre 2003",
        "note": "La CNRACL est un régime spécial de sécurité sociale (CSS art. L. 711-1, cité par le rapport). Une "
                "part plafonnée des cotisations finance son fonds d'action sociale et son fonds de prévention : elle "
                "reste à la CNRACL.",
    }
    p["ircantec"] = {
        "libelle": "Cotisations Ircantec des agents contractuels du public (salarié et employeur)",
        "statut": "sourcee", "qualite": "trace",
        "ventilation": [_part("ircantec", 1.0, JAUNE + ", fiche Ircantec : « Décret n° 70-1277 du 23 décembre "
                              "1970 », « Gestion confiée à la Caisse des dépôts (CDC) » ; taux depuis le 01/01/2017 : "
                              "2,80 % et 4,20 % (tranche A), 6,95 % et 12,55 % (tranche B) ; 5 201 M€ de produits "
                              "techniques en 2024")],
        "reference_juridique": "Décret n° 70-1277 du 23 décembre 1970 ; arrêté du 30 décembre 1970",
    }
    p["rafp"] = {
        "libelle": "Retraite additionnelle de la fonction publique (RAFP, sur les primes ; salarié et employeur)",
        "statut": "sourcee", "qualite": "trace",
        "ventilation": [_part("erafp", 1.0, JAUNE + ", fiche ERAFP : « Décret n°2004-569 du 18 juin 2004 », « Taux : 5 % "
                              "salarial et 5 % patronal », « 2,25 Md€ de cotisations collectées » en 2024")],
        "reference_juridique": "Loi n° 2003-775 du 21 août 2003, art. 76 ; décret n° 2004-569 du 18 juin 2004",
        "note": "L'ERAFP est un établissement public administratif ; rattachement à la sécurité sociale en "
                "comptabilité nationale à confirmer (même convention que pour Agirc-Arrco et l'Ircantec).",
    }
    p["regime_local_alsace_moselle"] = {
        "libelle": "Cotisation salariale d'assurance maladie du régime local d'Alsace-Moselle",
        "statut": "sourcee", "qualite": "trace",
        "ventilation": [_part("regime_local_am", 1.0, A3 + ", partie 3 : les Urssaf recouvrent, au titre des régimes "
                              "obligatoires de base, « des cotisations d'assurance maladie spécifiques au régime local "
                              "d'Alsace-Moselle »")],
        "reference_juridique": "CSS art. L. 325-1 (régime local), cité comme base légale ; " + A3,
        "note": "Montant national de la cotisation non publié dans ce document.",
    }

    note_affiliation = ("Vaut pour les artisans, commerçants et professions libérales non réglementées, affiliés à "
                        "l'Assurance retraite. Une profession libérale réglementée cotise à la Cipav ou à une autre "
                        "section de la CNAVPL : cas non distingué par le calcul, d'où le statut « approche ».")
    p["independants_retraite_base"] = {
        "libelle": "Cotisation de retraite de base des travailleurs indépendants (y compris la part du forfait "
                   "micro-social)",
        "statut": "sourcee", "qualite": "approche",
        "ventilation": [_part("cnav", 1.0, CNAV25 + " (« Articles L.241-3, D.242-4 et D.633-3 du CSS » : cotisation "
                              "de retraite de base des indépendants au taux du régime général) et " + CNAV24 +
                              " (part « retraite de base » du forfait micro-social, 41,80 % en vente et en "
                              "prestations de services commerciales)")],
        "reference_juridique": "CSS art. L. 241-3, D. 633-3, L. 613-7 et D. 613-6, cités par les circulaires",
        "note": note_affiliation,
    }
    p["independants_retraite_complementaire"] = {
        "libelle": "Cotisation de retraite complémentaire des travailleurs indépendants (RCI, y compris la part du "
                   "forfait micro-social)",
        "statut": "sourcee", "qualite": "approche",
        "ventilation": [_part("rci_independants", 1.0, CNAV25 + " (« Articles L.241-3 du CSS et D.635-7 du CSS », "
                              "« régime complémentaire des indépendants (RCI) ») et " + CNAV24 +
                              " (part « retraite complémentaire » du forfait micro-social, 16,50 % en vente et en "
                              "prestations de services commerciales)")],
        "reference_juridique": "CSS art. D. 635-7 et D. 613-6, cités par les circulaires",
        "note": note_affiliation,
    }
    sans_source = {
        "independants_maladie_maternite": (
            "Cotisation maladie-maternité des travailleurs indépendants (y compris indemnités journalières et part du "
            "forfait micro-social)",
            "La part du forfait est publiée (" + CNAV24 + ", 8,90 % en vente) mais pas son destinataire : la source "
            "primaire repérée (circulaires de l'Assurance maladie) était inaccessible. Non publiée, jamais supposée."),
        "independants_invalidite_deces": (
            "Cotisation invalidité-décès des travailleurs indépendants (y compris la part du forfait micro-social)",
            "La part du forfait est publiée (" + CNAV24 + ", 3,10 % en vente) mais pas son destinataire dans une "
            "source primaire accessible. Non publiée, jamais supposée."),
        "independants_formation_professionnelle": (
            "Contribution à la formation professionnelle des travailleurs indépendants",
            A3 + ", partie 3, indique que les Urssaf la recouvrent (0,29 Md€ en 2024) sans nommer l'organisme "
            "bénéficiaire, qui dépend de l'activité (commerçant, artisan, profession libérale). Non publiée."),
        "taxe_frais_chambre_consulaire": (
            "Taxe pour frais de chambre consulaire des micro-entrepreneurs",
            "Le bénéficiaire dépend de l'activité (chambre de commerce et d'industrie ou chambre de métiers et de "
            "l'artisanat) et aucun document primaire consulté ne donne sa répartition ni son rattachement en "
            "comptabilité nationale. Non publiée."),
    }
    for cle, (lib, note) in sans_source.items():
        p[cle] = {"libelle": lib, "statut": "non sourcee", "ventilation": [], "note": note}
    return p


CORRESPONDANCE_CALCUL = {
    "vieillesse_plafonnee_salarie": "vieillesse_plafonnee", "vieillesse_plafonnee_employeur": "vieillesse_plafonnee",
    "vieillesse_deplafonnee_salarie": "vieillesse_deplafonnee",
    "vieillesse_deplafonnee_employeur": "vieillesse_deplafonnee",
    "maladie_employeur": "maladie", "famille_employeur": "famille", "atmp": "atmp",
    "retraite_complementaire_salarie": "agirc_arrco", "retraite_complementaire_employeur": "agirc_arrco",
    "ceg_salarie": "ceg", "chomage_employeur": "chomage", "fnal": "fnal", "csa": "csa",
    "csg_deductible": "csg_activite", "csg_non_deductible": "csg_activite", "crds": "crds",
    "impot_revenu": "impot_revenu",
    # Profils étendus (web/src/calcul/moteur-etendu.ts) : identifiant de ligne -> clé de prelevements.
    "retenue_pension_civile": "pension_civile_etat", "contribution_cas_pensions": "pension_civile_etat",
    "ati": "allocation_temporaire_invalidite",
    "retenue_cnracl": "cnracl", "contribution_cnracl": "cnracl",
    "rafp_salarie": "rafp", "rafp_employeur": "rafp",
    "ircantec_salarie": "ircantec", "ircantec_employeur": "ircantec",
    "casa": "casa",
    "maladie_regime_local": "regime_local_alsace_moselle",
    "micro_retraite_base": "independants_retraite_base", "independant_retraite_base": "independants_retraite_base",
    "micro_retraite_complementaire": "independants_retraite_complementaire",
    "independant_retraite_complementaire": "independants_retraite_complementaire",
    "micro_maladie_maternite": "independants_maladie_maternite",
    "independant_maladie": "independants_maladie_maternite",
    "independant_indemnites_journalieres": "independants_maladie_maternite",
    "micro_invalidite_deces": "independants_invalidite_deces",
    "independant_invalidite_deces": "independants_invalidite_deces",
    "micro_formation_professionnelle": "independants_formation_professionnelle",
    "independant_formation_professionnelle": "independants_formation_professionnelle",
    "micro_taxe_chambre_consulaire": "taxe_frais_chambre_consulaire",
}

# CSG sur les pensions : la clé dépend du taux de la personne (exonéré : aucune ligne).
CORRESPONDANCE_CALCUL_SELON_TAUX = {
    "csg_pension_deductible": {"normal": "csg_remplacement_taux_normal", "median": "csg_remplacement_taux_median",
                               "reduit": "csg_remplacement_taux_reduit"},
    "csg_pension_non_deductible": {"normal": "csg_remplacement_taux_normal",
                                   "median": "csg_remplacement_taux_median"},
}

# --- Utilitaires ---------------------------------------------------------------------------------------------------


def dump(path: Path, obj, indent=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":"))
    if len(texte.encode("utf-8")) > 5_000_000:
        raise SystemExit(f"{path} dépasse 5 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def espaces(s: str) -> str:
    s = unicodedata.normalize("NFC", s).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def num(v) -> float:
    if v is None:
        return 0.0
    s = str(v).strip().replace(",", ".")
    try:
        return float(s) if s not in ("", "-") else 0.0
    except ValueError:
        return 0.0


def r2(x):
    return None if x is None else round(x, 2)


# --- Collecte (réseau) ---------------------------------------------------------------------------------------------


def telecharger(url: str, dest: Path, essais: int = 4, budget: float = 120.0) -> str:
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    derniere = ""
    for i in range(essais):
        try:
            r = requests.get(url, timeout=(15, budget), headers={"User-Agent": "ou-vont-mes-impots/pipeline"})
            if r.status_code in (401, 403, 451):
                return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
            r.raise_for_status()
            if r.content[:15].lower().startswith(b"<html") or b"Request Rejected" in r.content[:500]:
                return "page de refus renvoyée à la place du fichier : aucun contournement"
            from fetch import octets_annonces, remplacer_si_valide  # controle collecte/integrite.py
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(r.content)
            remplacer_si_valide(tmp, dest, octets_attendus=octets_annonces(r))  # invalide : dest conserve
            return "ok"
        except Exception as e:  # reprise réseau
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(2 * (i + 1))
    return f"échec après {essais} essais : {derniere}"


def collecter() -> dict:
    etat = {}
    for cle, s in SOURCES.items():
        dest = BRUT / s["fichier"]
        if dest.exists() and dest.stat().st_size > 0:
            etat[cle] = {"statut": "présent", "octets": dest.stat().st_size}
            continue
        res = telecharger(s["url"], dest)
        etat[cle] = {"statut": res, "collecte_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if dest.exists():
            etat[cle]["octets"] = dest.stat().st_size
        print(f"{cle}: {res}")
    dump(BRUT / "_sources.json", {"sources": SOURCES, "etat": etat}, indent=1)
    return etat


# --- Vérification des paramètres saisis ----------------------------------------------------------------------------


def texte_pdf(nom: str, pages=None) -> str | None:
    pdf = BRUT / nom
    signature = "" if pages is None else f".p{min(pages)}-{max(pages)}-{len(pages)}"
    cache = BRUT / (nom + signature + ".txt")
    if cache.exists() and pdf.exists() and cache.stat().st_mtime >= pdf.stat().st_mtime:
        return cache.read_text(encoding="utf-8")
    if not pdf.exists():
        return None
    import pdfplumber
    morceaux = []
    with pdfplumber.open(pdf) as doc:
        for i, page in enumerate(doc.pages):
            if pages is None or i in pages:
                morceaux.append(page.extract_text() or "")
    t = "\n".join(morceaux)
    cache.write_text(t, encoding="utf-8")
    return t


def verifier_documents() -> dict:
    out = {}
    for cle, motifs, pages in DOCUMENTS_VERIFIES:
        nom = SOURCES[cle]["fichier"]
        t = texte_pdf(nom, pages)
        if t is None:
            out[cle] = {"statut": "document absent de l'entrepôt : valeurs saisies non revérifiées"}
            continue
        t = espaces(t)
        manquants = [m for m in motifs if espaces(m) not in t]
        out[cle] = {"statut": "vérifié" if not manquants else "écart", "motifs": len(motifs), "manquants": manquants}
        if manquants:
            raise SystemExit(f"{nom} : paramètres saisis introuvables dans le PDF (le document a changé ?) : "
                             f"{manquants}")
    return out


# --- Taxe foncière (REI 2025) --------------------------------------------------------------------------------------

COLS_REI = ["DEP", "COM", "LIBCOM", "E00", "E11", "E13", "E14", "E23", "E33", "E53", "E53A", "E53gGEMAPI", "E53TASA",
            "F13", "F14", "F22", "H11THS", "H14"]
SEUIL_RS = 30  # articles de résidences secondaires minimum pour une valeur locative communale


def lire_rei() -> list[dict] | None:
    if not REI_ZIP.exists():
        return None
    with zipfile.ZipFile(REI_ZIP) as z:
        nom = next(n for n in z.namelist() if n.upper().endswith(".CSV"))
        with z.open(nom) as f:
            lecteur = csv.reader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";")
            entete = next(lecteur)
            idx = {c: entete.index(c) for c in COLS_REI if c in entete}
            manquantes = set(COLS_REI) - set(idx)
            if manquantes:
                raise SystemExit(f"REI 2025 : colonnes absentes {sorted(manquantes)}")
            lignes = []
            for row in lecteur:
                d = {c: row[i] for c, i in idx.items()}
                for c in COLS_REI[3:]:
                    d[c] = num(d[c])
                lignes.append(d)
    return lignes


def code_insee(dep: str, com: str) -> str:
    return dep + com if len(dep) == 2 else dep + com[-2:].zfill(2)


def taxe_fonciere(rei: list[dict]) -> tuple[dict, dict]:
    deps_site = {p.stem for p in (SITE / "communes").glob("*.json")}
    par_dep_vl = {}
    for d in rei:
        a = par_dep_vl.setdefault(d["DEP"], [0.0, 0.0])
        a[0] += d["H11THS"]
        a[1] += d["H14"]
    nat = {"commune": 0.0, "epci": 0.0, "syndicats": 0.0, "tse": 0.0, "region_idf": 0.0, "etat": 0.0}
    sorties, stats = {}, {"communes": 0, "avec_vl_communale": 0, "avec_vl_departementale": 0, "sans_estimation": 0}
    for d in rei:
        parts = {"commune": d["E13"], "epci": d["E33"] + d["E53gGEMAPI"], "syndicats": d["E23"],
                 "tse": d["E53"] + d["E53A"], "region_idf": d["E53TASA"], "etat": d["E00"]}
        for k, v in parts.items():
            nat[k] += v
        dep = d["DEP"]
        if dep not in deps_site:
            continue
        insee = code_insee(dep, d["COM"])
        montant_coll = sum(v for k, v in parts.items() if k != "etat")
        tot = montant_coll + d["E00"]
        stats["communes"] += 1
        if d["E11"] <= 0 or d["E14"] <= 0 or montant_coll <= 0:
            stats["sans_estimation"] += 1
            sorties.setdefault(dep, {})[insee] = None
            continue
        taux_eff = montant_coll / d["E11"]        # taux global effectif (toutes collectivités) sur la base communale
        frais = d["E00"] / montant_coll
        vl_dep = par_dep_vl[dep][0] / par_dep_vl[dep][1] if par_dep_vl[dep][1] else None
        vl_com = d["H11THS"] / d["H14"] if d["H14"] >= SEUIL_RS else None
        est_a = taux_eff * 0.5 * vl_com * (1 + frais) if vl_com else None
        est_b = taux_eff * 0.5 * vl_dep * (1 + frais) if vl_dep else None
        est_c = tot / d["E14"]
        logement = [x for x in (est_a, est_b) if x]
        central = est_a or est_b
        stats["avec_vl_communale" if est_a else "avec_vl_departementale"] += 1
        bas, haut = min(logement), max(logement + [est_c])
        # TEOM : taux plein × base foncière estimée (50 % de la valeur locative) ; c = moyenne par article de TEOM
        teom = None
        if d["F13"] > 0 and d["F22"] > 0:
            t = d["F22"] / 100
            ta = t * 0.5 * vl_com if vl_com else None
            tb = t * 0.5 * vl_dep if vl_dep else None
            tc = d["F13"] / d["F14"] if d["F14"] > 0 else None
            tl = [x for x in (ta, tb) if x]
            if tl:
                teom = [r2(min(tl)), r2(ta or tb), r2(max(tl + ([tc] if tc else [])))]
        sorties.setdefault(dep, {})[insee] = [r2(bas), r2(central), r2(haut)] + (teom or [None, None, None]) + [
            round(parts[k] / tot, 4) for k in ("commune", "epci", "syndicats", "tse", "region_idf", "etat")]
    return {"montants_m": {k: round(v / 1e6, 3) for k, v in nat.items()}, "stats": stats}, sorties


def produire_taxe_fonciere(rei, agregats, sorties):
    entete = {
        "millesime": "Exercice 2025 (taxe foncière et TEOM émises en 2025)",
        "source": "DGFiP, REI 2025 (data.economie.gouv.fr, Licence Ouverte 2.0), entrepôt data/lake/fiscalite/",
        "format": "communes : {code INSEE: [tf_bas, tf_central, tf_haut, teom_bas, teom_central, teom_haut, "
                  "part_commune, part_epci, part_syndicats, part_tse, part_region_idf, part_etat_frais]} ; euros par "
                  "an ; null = pas d'estimation (base ou montant nul) ; teom null = pas de TEOM",
    }
    for old in (SORTIE / "taxe_fonciere").glob("*.json"):
        old.unlink()
    for dep, communes in sorted(sorties.items()):
        dump(SORTIE / "taxe_fonciere" / f"{dep}.json", {**entete, "communes": communes})
    methode = {
        "millesime": "Exercice 2025",
        "source": "DGFiP, REI 2025 (montants réels, bases nettes, nombres d'articles, valeurs locatives des résidences "
                  "secondaires) ; taux communaux déjà publiés dans site/data/communes/",
        "unite": "euros par an",
        "methode": [
            "Propriétaire : taxe foncière ≈ taux global effectif × base foncière estimée × (1 + frais de gestion).",
            "Taux global effectif de la commune = (part communale E13 + intercommunale E33 + syndicats E23 + taxes "
            "spéciales d'équipement E53/E53A + GEMAPI + TASA) / base nette communale E11.",
            "Base foncière estimée = 50 % de la valeur locative (CGI art. 1388) ; valeur locative d'un logement = "
            "moyenne par article des bases de taxe d'habitation sur les résidences secondaires (H11THS / H14), "
            f"dans la commune si elle compte au moins {SEUIL_RS} articles, sinon dans le département.",
            "Frais de gestion = frais perçus par l'État (E00) rapportés aux montants des collectivités.",
            "Central = estimation avec la valeur locative communale (à défaut départementale). Bas = la plus faible "
            "des estimations « logement » (communale, départementale). Haut = la plus forte de celles-ci et de la "
            "moyenne par article de la commune ((montants + frais) / E14), qui inclut les locaux professionnels.",
            "Locataire : TEOM ≈ taux plein de TEOM (F22) × même base estimée, refacturée dans les charges (décret "
            "n° 87-713). Haut inclut la moyenne par article de TEOM (F13 / F14).",
            "Si l'utilisateur saisit le montant de son avis (profil : logement.taxe_fonciere_annuelle_eur), ce montant "
            "remplace l'estimation ; seules les parts par destinataire restent utiles.",
        ],
        "limites": [
            "Fourchette large assumée : la valeur locative réelle d'un logement dépend de sa surface et de sa "
            "catégorie cadastrale, inconnues ici.",
            "Les résidences secondaires peuvent différer des résidences principales (taille, standing).",
            "Exonérations et dégrèvements personnels (personnes âgées ou modestes, constructions neuves) non pris "
            "en compte.",
        ],
        "agregats_nationaux_m": agregats["montants_m"],
        "couverture": agregats["stats"],
        "departements": sorted(sorties),
        "fichiers": "taxe_fonciere/<dep>.json",
    }
    dump(SORTIE / "taxe_fonciere.json", methode, indent=1)


# --- TVA et taxes sur la consommation -----------------------------------------------------------------------------

# Taux légaux 2025 par poste COICOP (préfixe le plus long). Sources : CGI art. 278 (20 %), 278-0 bis et 278-0 bis A
# (5,5 %), 279 (10 %), 281 octies et 298 septies (2,1 %), 261, 261 C, 261 D et 261 E (exonérations).
TAUX_TVA = {
    "011": 0.055, "012": 0.055, "013": 0.055,
    "021": 0.20, "022": 0.20, "024": 0.20,
    "031": 0.20, "032": 0.20, "033": 0.20,
    "041": 0.0, "043": 0.20, "044": 0.20, "0443": 0.055, "045": 0.20, "046": 0.20,
    "051": 0.20, "052": 0.20, "053": 0.20, "054": 0.20, "055": 0.20, "056": 0.20, "057": 0.20,
    "061": 0.021, "062": 0.0, "063": 0.0, "064": 0.0,
    "071": 0.20, "072": 0.20, "073": 0.10, "074": 0.20,
    "081": 0.20, "0811": 0.0,
    "091": 0.20, "092": 0.20, "093": 0.20, "094": 0.20, "0942": 0.055, "0943": 0.0,
    "095": 0.20, "0951": 0.055, "0952": 0.021, "096": 0.20, "097": 0.20,
    "101": 0.0, "111": 0.10, "112": 0.10,
    "121": 0.20, "123": 0.20, "124": 0.0, "125": 0.0, "126": 0.0, "127": 0.20, "128": 0.20, "129": 0.20,
}
CLES = {"tabac": ["022"], "alcool": ["021"], "ticpe": ["0722", "0453"]}


def lire_tf(nom: str, cle_val: str, filtre=None) -> dict:
    p = BRUT / nom
    out = {}
    with p.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if filtre and not filtre(r):
                continue
            out[(r.get("NOMENCLATURE") or r.get("EQUIP"), r["DECUC"])] = num(r[cle_val])
    return out


def tva_theorique(conso: dict, dec: str) -> float:
    groupes = sorted({c for c, _ in conso if len(c) == 3 and not c.startswith("13") and c.isdigit()})
    total = 0.0
    for g in groupes:
        v = conso.get((g, dec), 0.0)
        enfants = [k for k in TAUX_TVA if len(k) == 4 and k.startswith(g)]
        reste = v
        for e in enfants:
            ve = conso.get((e, dec), 0.0)
            total += ve * TAUX_TVA[e] / (1 + TAUX_TVA[e])
            reste -= ve
        t = TAUX_TVA.get(g)
        if t is None:
            raise SystemExit(f"poste COICOP {g} sans taux de TVA : compléter TAUX_TVA")
        total += max(reste, 0.0) * t / (1 + t)
    return total


def lire_ia88() -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(BRUT / SOURCES["insee_ia88"]["fichier"], read_only=True, data_only=True)

    def feuille(nom):
        return [[c for c in row] for row in wb[nom].iter_rows(values_only=True)]

    def ligne(rows, debut):
        for r in rows:
            if isinstance(r[0], str) and espaces(r[0]).startswith(debut):
                return [float(x) for x in r[1:21]]
        raise SystemExit(f"IA88 : ligne « {debut} » introuvable")

    t2 = feuille("Tableau complémentaire 2")
    enc = feuille("Figure Encadré")
    out = {
        "tpp": ligne(t2, "Taxes sur les produits et sur la product"),
        "tp": ligne(t2, "Taxes sur la production"),
        "revdisp": ligne(t2, "Revenu disponible"),
        "transferts_eur_uc": ligne(t2, "Transferts nets, en euros par UC"),
        "transferts_md": ligne(t2, "Transferts nets, en milliards"),
        "avant": ligne(enc, "Revenus avant transferts (aux prix de ba"),
        "var_conso": ligne(enc, "Revenus primaires élargis (variante cons"),
        "var_revenu": ligne(enc, "Revenus primaires élargis (variante reve"),
    }
    return out


def deciles_erfs() -> dict:
    with zipfile.ZipFile(ERFS_ZIP) as z:
        nom = next(n for n in z.namelist() if n.endswith("_data.csv"))
        rows = list(csv.DictReader(io.TextIOWrapper(z.open(nom), encoding="utf-8-sig"), delimiter=";"))
    tout = [r for r in rows if r["AGE"] == "_T" and r["SEX"] == "_T" and r["PCS"] == "_T" and r["TPH"] == "_T"
            and r["EMPSTA_ENQ"] == "_T" and r["GEO"] == "FM" and r["UNIT_MEASURE"] == "EUR_ANNUEL"]
    an = max(int(r["TIME_PERIOD"]) for r in tout if r["ERFS_MEASURE"] == "D1_SL")
    b = {r["ERFS_MEASURE"]: float(r["OBS_VALUE"]) for r in tout if int(r["TIME_PERIOD"]) == an
         and r["QUANTILE"] == "_T" and re.fullmatch(r"D[1-9]_SL|MED_SL", r["ERFS_MEASURE"])}
    b["D5_SL"] = b.pop("MED_SL")  # le 5e décile est publié comme médiane
    return {"annee": str(an), "bornes": [b[f"D{i}_SL"] for i in range(1, 10)]}


def recettes_eurostat() -> dict:
    r = json.loads((SITE / "recettes.json").read_text(encoding="utf-8"))
    ens = lambda code, an: r["impots"][code]["par_administration"]["Ensemble"][an]  # noqa: E731
    return {an: {"d2": ens("D2", an), "d29": ens("D29", an), "d211": ens("D211", an), "d214a": ens("D214A", an)}
            for an in ("2019", ANNEE)}


def tva_conso() -> dict:
    ia = lire_ia88()
    conso = lire_tf(SOURCES["insee_bdf_tf106"]["fichier"], "CONSO")
    equip = lire_tf(SOURCES["insee_bdf_tf306"]["fichier"], "TAUX", lambda r: r["EQUIP"] == "30")
    euro = recettes_eurostat()
    erfs = deciles_erfs()

    d21 = {an: v["d2"] - v["d29"] for an, v in euro.items()}
    facteur = d21[ANNEE] / d21["2019"]
    # Vingtièmes -> déciles (pondération par le nombre d'UC de chaque vingtième, déduit des transferts nets)
    uc = [md * 1e9 / e for md, e in zip(ia["transferts_md"], ia["transferts_eur_uc"])]
    conso_v = [-a - b for a, b in zip(ia["tpp"], ia["tp"])]          # taxes sur les produits, hypothèse consommation
    revenu_v = [vr - av for vr, av in zip(ia["var_revenu"], ia["avant"])]  # hypothèse revenu (Insee, encadré)
    total_uc = sum(uc)
    total_2019_md = sum(c * u for c, u in zip(conso_v, uc)) / 1e9

    nationaux = {
        "tva": {"md": euro[ANNEE]["d211"], "source": "Eurostat gov_10a_taxag D211, 2025 (site/data/recettes.json)"},
        "ticpe": {"md": round(31.4 - 1.6, 3), "source": VM + " (p. 28) : accise ex-TICPE brute totale 31,4 Md€ moins "
                  "remboursements et dégrèvements 1,6 Md€ (gazole professionnel)"},
        "tabac": {"md": 12.086, "source": A3 + " : droit de consommation sur les tabacs, 12 086 M€"},
        "alcool": {"md": round((2175 + 732 + 1067 + 101 + 56) / 1000, 3),
                   "source": A3 + " : droits sur les alcools (consommation 2 175, cotisation > 18° 732, bières 1 067, "
                             "vins 101, produits intermédiaires 56 M€)"},
    }
    autres = d21[ANNEE] - sum(v["md"] for v in nationaux.values())
    nationaux["autres"] = {"md": round(autres, 3), "source": "Eurostat D2 - D29 (taxes sur les produits) 2025 moins "
                           "les quatre lignes ci-dessus : accises électricité et gaz, taxe sur les conventions "
                           "d'assurance, droits de mutation, etc."}
    # Clés de répartition par décile (Budget de famille 2017)
    decs = [str(i) for i in range(1, 11)]

    def cle(codes, dec):
        return sum(conso.get((c, dec), 0.0) for c in codes)
    base = {"tva": {d: tva_theorique(conso, d) for d in decs},
            "autres": {d: conso.get(("CTOTALE", d), 0.0) for d in decs}}
    for k, codes in CLES.items():
        base[k] = {d: cle(codes, d) for d in decs}
    moy = {k: sum(v.values()) / 10 for k, v in base.items()}

    tranches = []
    estime = {k: 0.0 for k in nationaux}
    for i, dec in enumerate(decs):
        vs = [2 * i, 2 * i + 1]
        u = uc[vs[0]] + uc[vs[1]]
        moyen = lambda serie: sum(serie[v] * uc[v] for v in vs) / u  # noqa: E731
        c19, r19, rd19 = moyen(conso_v), moyen(revenu_v), moyen(ia["revdisp"])
        central = c19 * facteur
        bas, haut = min(c19, r19) * facteur, max(c19, r19) * facteur
        poids = {k: nationaux[k]["md"] * base[k][dec] / moy[k] for k in nationaux}
        sp = sum(poids.values())
        detail = {}
        for k in nationaux:
            s = poids[k] / sp
            detail[k] = {"bas": r2(bas * s), "central": r2(central * s), "haut": r2(haut * s), "part": round(s, 4)}
            estime[k] += central * s * u
        taux_voit = equip.get(("30", dec))
        tranches.append({
            "decile": i + 1,
            "niveau_de_vie_min_eur": None if i == 0 else erfs["bornes"][i - 1],
            "niveau_de_vie_max_eur": None if i == 9 else erfs["bornes"][i],
            "taxes_produits_eur_par_uc": {"bas": r2(bas), "central": r2(central), "haut": r2(haut)},
            "taux_effort_pct_revenu_disponible_2019": round(100 * c19 / rd19, 1),
            "detail_eur_par_uc": detail,
            "ajustements": {
                "voiture": {
                    "taux_equipement_pct_2017": taux_voit,
                    "ticpe_si_voiture_eur_par_uc": r2(detail["ticpe"]["central"] / (taux_voit / 100)) if taux_voit else None,
                    "ticpe_sans_voiture_eur_par_uc": 0.0,
                    "source": "Insee BdF 2017 TF306 (code 30, au moins une voiture) : dépense de carburant supposée "
                              "portée par les ménages équipés",
                },
                "fumeur": {
                    "tabac_non_fumeur_eur_par_uc": 0.0,
                    "tabac_fumeur_eur_par_uc": None,
                    "note": "Non fumeur : le droit de consommation (CGI art. 575) ne frappe que l'achat de tabac. "
                            "Fumeur : montant par fumeur non sourcé (part de ménages fumeurs par décile non publiée) ; "
                            "garder la moyenne du décile, qui le sous-estime.",
                },
            },
        })
    ecarts = {}
    for k in nationaux:
        e = estime[k] / 1e9
        ecarts[k] = {"estime_md": round(e, 2), "reel_md": nationaux[k]["md"],
                     "ecart_pct": round(100 * (e - nationaux[k]["md"]) / nationaux[k]["md"], 1)}
    e_tot = sum(estime.values()) / 1e9
    ecarts["total_taxes_produits"] = {"estime_md": round(e_tot, 2), "reel_md": round(d21[ANNEE], 2),
                                      "ecart_pct": round(100 * (e_tot - d21[ANNEE]) / d21[ANNEE], 1)}
    return {
        "millesime": "2025 (montants recalés sur Eurostat 2025) ; répartition par niveau de vie Insee 2019 ; "
                     "structure de consommation Budget de famille 2017 ; déciles de niveau de vie ERFS "
                     + erfs["annee"],
        "source": "Insee, Insee Analyses n° 88 (comptes nationaux distribués 2019) ; Insee, Budget de famille 2017 "
                  "(TF106, TF306) ; Eurostat gov_10a_taxag ; PLF 2026 Voies et moyens tome I ; PLFSS 2026 annexe 3 ; "
                  "Insee ERFS",
        "unite": "euros par an et par unité de consommation (UC) ; un ménage paie le montant × son nombre d'UC "
                 "(1 pour le premier adulte, 0,5 par personne de 14 ans ou plus, 0,3 par enfant de moins de 14 ans)",
        "annee_reference": ANNEE,
        "methode": [
            "Total des taxes sur les produits par décile : Insee, comptes nationaux distribués 2019 (tableau "
            "complémentaire 2 : « taxes sur les produits et sur la production » moins « taxes sur la production »), "
            "vingtièmes regroupés en déciles et pondérés par leur nombre d'UC.",
            f"Recalage 2025 : × {round(facteur, 4)} = taxes sur les produits Eurostat (D2 - D29) 2025 / 2019 "
            f"({round(d21[ANNEE], 2)} / {round(d21['2019'], 2)} Md€).",
            "Central = hypothèse Insee de référence (taxes réparties comme la consommation, prix de marché). Bas et "
            "haut = encadrement par la variante Insee où ces taxes sont imputées aux revenus (encadré de l'IA 88).",
            "Détail par taxe dans chaque décile : montant national 2025 de la taxe × clé du décile (dépense Budget "
            "de famille 2017 du poste concerné, rapportée à la moyenne des déciles), normalisé pour que la somme des "
            "taxes égale le total du décile. Clés : TVA = TVA théorique (dépenses × taux légaux 2025 par poste "
            "COICOP) ; ex-TICPE = carburants (0722) et combustibles liquides (0453) ; tabac = 022 ; alcool = 021 ; "
            "autres = consommation totale.",
            "Pour placer un utilisateur : niveau de vie = revenu disponible du ménage / nombre d'UC, comparé aux "
            "bornes de déciles ERFS ; le site peut aussi appliquer le taux d'effort au revenu disponible.",
        ],
        "limites": [
            "L'hypothèse Insee attribue aux ménages toutes les taxes sur les produits, y compris celles payées en "
            "amont par les entreprises et les administrations.",
            "L'ex-TICPE payée par les professionnels est répartie comme si elle était refacturée aux acheteurs de "
            "carburant : la part des automobilistes est surestimée, celle des autres sous-estimée.",
            "Structures 2017 et 2019 supposées stables jusqu'en 2025 ; nombre d'UC de 2019.",
        ],
        "deciles_niveau_de_vie": {"annee": erfs["annee"], "bornes_eur_par_an": erfs["bornes"],
                                  "source": SOURCES_LAC["erfs_2024"]["titre"]},
        "recalage": {"facteur_2019_2025": round(facteur, 5), "taxes_produits_2019_md": round(d21["2019"], 2),
                     "taxes_produits_2025_md": round(d21[ANNEE], 2),
                     "total_insee_2019_md": round(total_2019_md, 2), "uc_2019_millions": round(total_uc / 1e6, 2),
                     "part_attribuee_aux_menages_2019": round(total_2019_md / d21["2019"], 4),
                     "lecture_ecart": "L'Insee attribue aux ménages résidents une partie seulement des taxes sur les "
                                      "produits de la comptabilité nationale (2019 : total Insee / Eurostat D21) ; "
                                      "l'écart publié ci-dessous reflète surtout cette différence de champ et la "
                                      "croissance du nombre d'UC depuis 2019, non corrigées."},
        "totaux_nationaux_2025_md": nationaux,
        "ecarts_au_total_national": ecarts,
        "tranches": tranches,
        "non_sourcé": [
            "montant de tabac par fumeur (ajustement « fumeur oui ») ;",
            "accises sur l'électricité et le gaz par décile (comprises dans « autres ») ;",
            "part de l'ex-TICPE réellement payée par les ménages.",
        ],
    }


# --- Production ----------------------------------------------------------------------------------------------------


def produire() -> None:
    manquants = [s["fichier"] for s in SOURCES.values() if not (BRUT / s["fichier"]).exists()]
    if manquants:
        raise SystemExit(f"sources absentes de data/lake/prelevements/ : {manquants} ; lancer "
                         f"`python pipeline/prelevements.py collecter`")
    verif = verifier_documents()
    rei = lire_rei()
    agregats, sorties = taxe_fonciere(rei) if rei else (None, {})
    if rei:
        produire_taxe_fonciere(rei, agregats, sorties)
    prelev = affectation_parametres(agregats)
    dump(SORTIE / "affectation.json", {
        "millesime": ANNEE, "annee": ANNEE,
        "source": "PLFSS 2026 annexe 3 (tableau 31) ; PLF 2026 Voies et moyens tome I ; PLF 2026 projet annuel de "
                  "performances du compte « Pensions » et rapport sur les pensions de retraite de la fonction "
                  "publique ; circulaires Cnav 2024-23 et 2025-14 ; DGFiP REI 2025 ; codes et lois cités pour chaque "
                  "part",
        "methode": "Une ventilation par prélèvement : part = fraction du produit 2025 attribuée au destinataire. "
                   "Les parts d'un prélèvement « sourcee » somment à 1. Un prélèvement ou une part introuvable est "
                   "marqué « non sourcee » et n'est jamais complété par une estimation. Champ « qualite » (profils "
                   "étendus) : " + QUALITE,
        "verification_documents": verif,
        "destinataires": DESTINATAIRES,
        "prelevements": prelev,
        "correspondance_calcul": CORRESPONDANCE_CALCUL,
        "correspondance_calcul_selon_taux": CORRESPONDANCE_CALCUL_SELON_TAUX,
        "sources": {**SOURCES, **SOURCES_LAC},
        "sources_ecartees": ECARTEES,
    }, indent=1)
    dump(SORTIE / "tva_conso.json", tva_conso(), indent=1)
    print(f"site/data/prelevements/ écrit ({len(sorties)} départements de taxe foncière)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter()
    if a.etape in ("produire", "tout"):
        produire()


if __name__ == "__main__":
    main()
