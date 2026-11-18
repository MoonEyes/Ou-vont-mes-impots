"""Assurance maladie par territoire : dépenses par grand poste et par département, exécution de l'ONDAM.

Agrégats publiés seulement (aucune donnée individuelle, aucun professionnel ni établissement nommé). Les comptes des
branches et l'arbre de l'ONDAM 2024 détaillé restent dans `secu/` ; les établissements de santé (référentiel,
activité) dans `sante_etablissements/` : ce module y renvoie par des liens, jamais par des montants additionnés.

Entrées : entrepôt brut data/lake/assurance_maladie_territoires/ (non versionné), rempli par `collecter` (sources
déclarées dans collecte/catalogue.json, type « url », fichier <id>.<format>) :
    amt_ameli_honoraires.csv            Cnam, data.ameli.fr « honoraires » : honoraires sans dépassement et
                                        dépassements des professionnels de santé libéraux, par profession et
                                        département, 2010-2025
    amt_ameli_prescriptions.csv         Cnam, data.ameli.fr « prescriptions » (filtre « Ensemble des médecins ») :
                                        montants prescrits par les médecins libéraux, par poste et département
    amt_es_cpam_<an>.csv                agrégat écrit par `collecter` à partir de l'archive annuelle ES_R_<an>.zip
                                        (Cnam, « Données par CPAM sur les dépenses d'assurance maladie relatives aux
                                        établissements de santé privés », ~700 Mo décompressés) lue en flux mois par
                                        mois ; l'archive est supprimée après agrégation
    amt_plfss<an>_annexe_ondam.xlsx     DSS, tableaux de l'annexe « ONDAM et dépenses de santé » des PLFSS 2023 à 2027
    amt_plfss<an>_annexe7.pdf           DSS, annexe 7 des PLFSS 2021 et 2022 (constats 2019 et 2020, texte vérifié)
Sorties (site/data/assurance_maladie_territoires/, schémas docs/schemas/assurance_maladie_territoires_*.schema.json) :
    index.json                 périmètre, définitions, séries nationales, fichiers, liens, écarts, sources, limites
    ondam.json                 exécution de l'ONDAM par sous-objectif 2019-2025, objectifs 2026 et 2027
    departements/<an>.json     par département : honoraires, prescriptions par poste, établissements privés

Commandes :
    python pipeline/assurance_maladie_territoires.py collecter   # réseau ; un refus 401/403/429 est noté, jamais
                                                                 # contourné ; reprenable
    python pipeline/assurance_maladie_territoires.py produire    # sans réseau
    python pipeline/assurance_maladie_territoires.py             # les deux

Règles :
  - trois champs différents, jamais additionnés entre eux ni avec l'ONDAM : honoraires (base de remboursement, par
    département du cabinet principal), prescriptions des médecins libéraux (base de remboursement, par département
    du médecin prescripteur), établissements privés (montant remboursé par le régime général, par département de la
    caisse primaire) ; l'ONDAM est un objectif national tous régimes, en droits constatés ;
  - « NS » (secret statistique : moins de 5 professionnels) et « NC » restent null, jamais 0, avec leur motif ;
  - les lignes « dont » du fichier des établissements privés (sous-totaux) ne sont jamais ajoutées aux autres ;
  - les montants de l'ONDAM sont ceux publiés (aucun écart recalculé) ; les ruptures de champ sont signalées ;
  - toute date écrite vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import MANIFESTE, date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AXE = "assurance_maladie_territoires"
BRUT = ROOT / "data" / "lake" / AXE
SITE = ROOT / "site" / "data"
SORTIE = SITE / AXE

# --- Sources ---------------------------------------------------------------------------------------------------------

AMELI = "https://data.ameli.fr/api/explore/v2.1/catalog/datasets"
AMELI_DEP = "https://open-data-assurance-maladie.ameli.fr/depenses"
SSFR = "https://www.securite-sociale.fr/files/live/sites/SSFR/files/medias/PLFSS"
ODBL = "Open Database License (ODbL)"
DOC_PUBLIC = "document administratif public (CRPA L. 321-1)"

SOURCES = {
    "amt_ameli_honoraires": {
        "fichier": "amt_ameli_honoraires.csv", "format": "csv",
        "url": f"{AMELI}/honoraires/exports/csv?delimiter=%3B",
        "page": "https://data.ameli.fr/explore/dataset/honoraires/",
        "titre": "Cnam, « Professionnels de santé libéraux : montants des honoraires par territoire (département, "
                 "région) » : honoraires sans dépassement et dépassements, par profession, 2010 à 2025",
        "producteur": "Caisse nationale de l'Assurance maladie (Cnam), d'après le SNDS", "millesime": "2010 à 2025",
        "licence": ODBL, "verdict": "réutilisable tel quel (export de l'API ; série labellisée par l'Autorité de la "
                                    "statistique publique)",
    },
    "amt_ameli_prescriptions": {
        "fichier": "amt_ameli_prescriptions.csv", "format": "csv",
        "url": f"{AMELI}/prescriptions/exports/csv?delimiter=%3B"
               "&where=profession_sante%3D%27Ensemble%20des%20m%C3%A9decins%27",
        "page": "https://data.ameli.fr/explore/dataset/prescriptions/",
        "titre": "Cnam, « Professionnels de santé libéraux : montants des prescriptions par poste et par territoire "
                 "(département, région) », lignes « Ensemble des médecins », 2010 à 2025",
        "producteur": "Caisse nationale de l'Assurance maladie (Cnam), d'après le SNDS", "millesime": "2010 à 2025",
        "licence": ODBL, "verdict": "réutilisable tel quel (export filtré de l'API)",
    },
    "amt_es_cpam": {
        "fichier": "amt_es_cpam_<an>.csv", "format": "csv",
        "url": f"{AMELI_DEP}/download.php?Dir_Rep=ES_Tables_R_Avec_Libelle&Annee=<an>",
        "page": "https://www.data.gouv.fr/datasets/donnees-par-cpam-sur-les-depenses-dassurance-maladie-relatives-"
                "aux-etablissements-de-sante-prives/",
        "titre": "Cnam, « Données par CPAM sur les dépenses d'assurance maladie relatives aux établissements de santé "
                 "privés » (fichiers mensuels HTOT, régime général, en date de remboursement), agrégés par département, "
                 "statut d'établissement et série de prestations",
        "producteur": "Caisse nationale de l'Assurance maladie (Cnam), d'après le SNDS", "millesime": "2024 et 2025",
        "licence": "Licence Ouverte 2.0",
        "verdict": "à adapter (archive annuelle de ~700 Mo décompressés, lue en flux mois par mois puis supprimée ; "
                   "seul l'agrégat par département est gardé dans l'entrepôt)",
    },
    "amt_plfss2027_annexe_ondam": {
        "fichier": "amt_plfss2027_annexe_ondam.xlsx", "format": "xlsx",
        "url": f"{SSFR}/2027/Annexe-5-Donnees-PLFSS-2027.xlsx",
        "page": "https://www.securite-sociale.fr/la-secu-en-detail/loi-de-financement/annee-en-cours",
        "titre": "PLFSS 2027, annexe 5 « ONDAM et dépenses de santé », données (tableaux 3, 4, 5, 8 et 13) : "
                 "réalisations 2025, objectif 2026 voté, prévision 2026 et objectif 2027 proposé",
        "producteur": "Direction de la sécurité sociale (DSS/SDEPF/6B)", "millesime": "Constat 2025, octobre 2026",
        "licence": DOC_PUBLIC, "verdict": "réutilisable tel quel (classeur publié avec l'annexe)",
    },
    "amt_plfss2026_annexe_ondam": {
        "fichier": "amt_plfss2026_annexe_ondam.xlsx", "format": "xlsx",
        "url": f"{SSFR}/2026/Annexe%205%20Tableaux%20PLFSS%202026%20(1).xlsx",
        "page": "https://www.securite-sociale.fr/home/la-secu-en-detail/loi-de-financement/annees-passees/"
                "plfss-2026.html",
        "titre": "PLFSS 2026, annexe 5 « ONDAM et dépenses de santé », tableaux (tableau 1 : réalisations 2024)",
        "producteur": "Direction de la sécurité sociale (DSS/SDEPF/6B)", "millesime": "Constat 2024, octobre 2025",
        "licence": DOC_PUBLIC, "verdict": "réutilisable tel quel (classeur publié avec l'annexe)",
    },
    "amt_plfss2025_annexe_ondam": {
        "fichier": "amt_plfss2025_annexe_ondam.xlsx", "format": "xlsx",
        "url": "https://contrib.securite-sociale.fr/files/live/sites/SSFR/files/medias/PLFSS/2025/"
               "Annexe%205%20Tableaux%202025.xlsx",
        "page": "https://www.securite-sociale.fr/home/la-secu-en-detail/loi-de-financement/annees-passees/"
                "plfss-2025.html",
        "titre": "PLFSS 2025, annexe 5 « ONDAM et dépenses de santé », tableaux (tableau 1 : réalisations 2023)",
        "producteur": "Direction de la sécurité sociale (DSS/SDEPF/6B)", "millesime": "Constat 2023, octobre 2024",
        "licence": DOC_PUBLIC, "verdict": "réutilisable tel quel (classeur publié avec l'annexe)",
    },
    "amt_plfss2024_annexe_ondam": {
        "fichier": "amt_plfss2024_annexe_ondam.xlsx", "format": "xlsx",
        "url": f"{SSFR}/2024/Annexe%205_Donn%c3%a9es.xlsx",
        "page": "https://www.securite-sociale.fr/home/la-secu-en-detail/loi-de-financement/annees-passees/"
                "plfss-2024.html",
        "titre": "PLFSS 2024, annexe 5 « ONDAM et dépenses de santé », données (tableau 3 : réalisations 2022)",
        "producteur": "Direction de la sécurité sociale (DSS/SDEPF/6B)", "millesime": "Constat 2022, octobre 2023",
        "licence": DOC_PUBLIC, "verdict": "réutilisable tel quel (classeur publié avec l'annexe)",
    },
    "amt_plfss2023_annexe_ondam": {
        "fichier": "amt_plfss2023_annexe_ondam.xlsx", "format": "xlsx",
        "url": f"{SSFR}/2023/Annexe%205_Tableaux.xlsx",
        "page": "https://www.securite-sociale.fr/home/la-secu-en-detail/loi-de-financement/annees-passees/"
                "plfss-2023.html",
        "titre": "PLFSS 2023, annexe 5 « ONDAM et dépenses de santé », tableaux (tableau 3 : réalisations 2021)",
        "producteur": "Direction de la sécurité sociale (DSS/SDEPF/6B)", "millesime": "Constat 2021, octobre 2022",
        "licence": DOC_PUBLIC, "verdict": "réutilisable tel quel (classeur publié avec l'annexe)",
    },
    "amt_plfss2022_annexe7": {
        "fichier": "amt_plfss2022_annexe7.pdf", "format": "pdf",
        "url": f"{SSFR}/2022/PLFSS-2022-Annexe%207.pdf",
        "page": "https://www.securite-sociale.fr/la-secu-en-detail/loi-de-financement/annees-passees/plfss-2",
        "titre": "PLFSS 2022, annexe 7 « ONDAM et dépenses de santé », tableau 3 : dépenses dans le champ de l'ONDAM "
                 "en 2020",
        "producteur": "Direction de la sécurité sociale (DSS/6B)", "millesime": "Constat 2020, octobre 2021",
        "licence": DOC_PUBLIC, "verdict": "réutilisable tel quel (texte du PDF, montants saisis et revérifiés)",
    },
    "amt_plfss2021_annexe7": {
        "fichier": "amt_plfss2021_annexe7.pdf", "format": "pdf",
        "url": f"{SSFR}/2021/PLFSS-2021-ANNEXE%207.pdf",
        "page": "https://www.securite-sociale.fr/la-secu-en-detail/loi-de-financement/annees-passees/plfss-1",
        "titre": "PLFSS 2021, annexe 7 « ONDAM et dépenses de santé », tableau 1 : réalisations dans le champ de "
                 "l'ONDAM en 2019",
        "producteur": "Direction de la sécurité sociale (DSS/6B)", "millesime": "Constat 2019, octobre 2020",
        "licence": DOC_PUBLIC, "verdict": "réutilisable tel quel (texte du PDF, montants saisis et revérifiés)",
    },
}
ANNEES_ES = (2024, 2025)  # 2023 et avant : fichiers sans libellés et codes de série différents d'un mois à l'autre

INACCESSIBLES = [
    {"source": "Dépenses des hôpitaux publics par département (dotations, séjours valorisés par l'assurance maladie)",
     "motif": "aucun jeu ouvert ne localise les versements de l'assurance maladie aux hôpitaux publics par département "
              "après 2015 (voir sante_etablissements/limites.json) ; le fichier des établissements privés ne contient "
              "que les factures liquidées par les caisses primaires"},
    {"source": "Open DAMIR (Cnam, base complète interrégimes, fichiers mensuels de plusieurs Go)",
     "motif": "non intégré : la géographie s'arrête à 13 zones (régions de 2016), sans département ; le détail "
              "national par poste est déjà publié par l'ONDAM et par secu/"},
    {"source": "Remboursements de soins de ville par caisse primaire (régime général)",
     "motif": "seul le fichier national (NTOT) est publié ; la série par caisse n'existe que pour les établissements "
              "privés"},
    {"source": "Site institutionnel assurance-maladie.ameli.fr (notices et descriptifs des variables)",
     "motif": "refus HTTP 403 opposé aux scripts : non contourné ; notices lues sur data.ameli.fr et data.gouv.fr"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Les jeux officiels de la Cnam (data.ameli.fr, open-data-assurance-maladie.ameli.fr) et les classeurs "
                  "de l'annexe ONDAM des PLFSS (securite-sociale.fr) sont réutilisés tels quels ; aucun dépôt public ne "
                  "fournit l'exécution de l'ONDAM par sous-objectif en série ni les dépenses par département déjà "
                  "structurées : agrégation écrite ici, sur le modèle des autres axes du dépôt.",
    "trouvailles": [
        {"nom": "Cnam, data.ameli.fr : honoraires et prescriptions des professionnels de santé libéraux par "
                "département", "url": "https://data.ameli.fr/pages/data-professionnels-sante-liberaux/",
         "licence": ODBL, "mise_a_jour": "2026-10-28", "verdict": "réutilisable tel quel"},
        {"nom": "Cnam, Données par CPAM sur les dépenses relatives aux établissements de santé privés",
         "url": SOURCES["amt_es_cpam"]["page"], "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-11-18",
         "verdict": "à adapter (agrégation en flux)"},
        {"nom": "DSS, annexe « ONDAM et dépenses de santé » des PLFSS 2021 à 2027 (classeurs et PDF)",
         "url": "https://www.securite-sociale.fr/home/la-secu-en-detail/comptes-statistiques-et-etudes-de-la-"
                "sécurité-sociale/lobjectif-national-des-depens-1.html",
         "licence": DOC_PUBLIC, "mise_a_jour": "octobre 2026", "verdict": "réutilisable tel quel"},
        {"nom": "Comité d'alerte sur l'évolution des dépenses d'assurance maladie, avis 2011-2026",
         "url": "https://www.securite-sociale.fr/home/la-secu-en-detail/comptes-statistiques-et-etudes-de-la-"
                "sécurité-sociale/lobjectif-national-des-depens-1.html",
         "licence": DOC_PUBLIC, "mise_a_jour": "2026-10-21",
         "verdict": "inspiration seulement (taux d'évolution en texte, sans tableau de montants)"},
        {"nom": "Cnam, Open DAMIR (base complète interrégimes)",
         "url": "https://www.data.gouv.fr/datasets/open-damir-base-complete-sur-les-depenses-dassurance-maladie-"
                "interregimes/", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-11-18",
         "verdict": "inspiration seulement (pas de département)"},
        {"nom": "raphaeleadjerad/opendamir (agrégation Open DAMIR avec dask)",
         "url": "https://github.com/raphaeleadjerad/opendamir", "licence": "MPL-2.0", "dernier_commit": "2020-04-24",
         "verdict": "inspiration seulement"},
        {"nom": "Sofiane-h31/Projet-Damir et TLxFroSt/open-damir-lakehouse",
         "url": "https://github.com/TLxFroSt/open-damir-lakehouse", "licence": "aucune (réutilisation non autorisée)",
         "dernier_commit": "2026-10-03", "verdict": "inspiration seulement"},
        {"nom": "Axes du dépôt secu/ (ONDAM 2024 détaillé) et sante_etablissements/ (référentiel, activité)",
         "url": "https://github.com/MoonEyes/Ou-vont-mes-impots", "licence": "celle du dépôt",
         "verdict": "réutilisé par liens (aucun montant recopié)"},
    ],
}

# --- Nomenclatures ----------------------------------------------------------------------------------------------------

# Honoraires : groupes publiés (libellés de la source, regroupements faits par la Cnam elle-même)
PROFESSIONS = [
    ("medecins", "Ensemble des médecins", "Médecins (généralistes et spécialistes)"),
    ("medecins_generalistes", "Ensemble des médecins généralistes", "Médecins généralistes"),
    ("medecins_specialistes", "Ensemble des médecins spécialistes (hors généralistes)", "Médecins spécialistes"),
    ("chirurgiens_dentistes", "Ensemble des chirurgiens-dentistes", "Chirurgiens-dentistes"),
    ("sages_femmes", "Sages-femmes", "Sages-femmes"),
    ("auxiliaires_medicaux", "Ensemble des auxiliaires médicaux",
     "Auxiliaires médicaux (infirmiers, kinésithérapeutes, orthophonistes, orthoptistes, pédicures-podologues)"),
    ("infirmiers", "Infirmiers", "Infirmiers"),
    ("masseurs_kinesitherapeutes", "Masseurs-kinésithérapeutes", "Masseurs-kinésithérapeutes"),
    ("orthophonistes", "Orthophonistes", "Orthophonistes"),
    ("orthoptistes", "Orthoptistes", "Orthoptistes"),
    ("pedicures_podologues", "Pédicures-podologues", "Pédicures-podologues"),
]
# Groupes disjoints dont la Cnam publie la somme (contrôle de cohérence, jamais republiée comme total ici)
COMPOSITION_PROFESSIONS = {"medecins": ["medecins_generalistes", "medecins_specialistes"],
                           "auxiliaires_medicaux": ["infirmiers", "masseurs_kinesitherapeutes", "orthophonistes",
                                                    "orthoptistes", "pedicures_podologues"]}

POSTES_PRESCRIPTION = [
    ("1", "medicaments", "Médicaments"),
    ("2", "dispositifs_medicaux", "Dispositifs médicaux (liste des produits et prestations : lits, fauteuils, "
                                  "oxygène, prothèses, matériel pour diabétiques, aides auditives et visuelles...)"),
    ("3", "biologie", "Biologie (prélèvements et analyses)"),
    ("4", "soins_infirmiers", "Soins infirmiers"),
    ("5", "kinesitherapie", "Kinésithérapie"),
    ("6", "transports", "Transports de patients"),
    ("7", "indemnites_journalieres", "Indemnités journalières (arrêts de travail)"),
    ("8", "autres", "Autres (pédicurie, orthophonie, orthoptie, vaccination, cures thermales, déplacements...)"),
    ("total", "total", "Ensemble des prescriptions"),
]

# Établissements privés : regroupement des séries de prestations (code SERIE de la source -> poste publié).
# Règle : les séries dont le libellé commence par « dont » sont des sous-totaux et ne sont jamais additionnées.
POSTES_ES = [
    ("sejours_mco", "Séjours en médecine, chirurgie, obstétrique (forfaits de séjour, suppléments, urgences, "
                    "dotations de mission et de qualité)"),
    ("smr", "Soins médicaux et de réadaptation (ex-soins de suite et de réadaptation)"),
    ("psychiatrie", "Psychiatrie"),
    ("medicaments_dispositifs_en_sus", "Médicaments et dispositifs médicaux facturés en plus du séjour"),
    ("dialyse", "Dialyse"),
    ("hospitalisation_domicile", "Hospitalisation à domicile"),
    ("medico_social", "Établissements pour enfants et adultes handicapés ou personnes âgées facturés aux caisses"),
    ("imagerie", "Imagerie (scanner, IRM, tomographie) et autres forfaits techniques"),
    ("autres", "Autres séries (établissements non conventionnés, conventions internationales, honoraires et "
               "divers)"),
]
STATUTS_ES = [("prive_lucratif", "Privé à but lucratif"), ("prive_non_lucratif", "Privé à but non lucratif"),
              ("public", "Public (factures liquidées par les caisses primaires)"), ("autre", "Autre ou non précisé")]

# ONDAM : sous-objectifs (libellés de la source normalisés -> identifiant)
SOUS_OBJECTIFS = [
    ("total", "ONDAM total", None),
    ("soins_de_ville", "Soins de ville", None),
    ("etablissements_sante", "Établissements de santé", None),
    ("medico_social", "Établissements et services médico-sociaux", None),
    ("medico_social_personnes_agees", "Établissements et services pour personnes âgées", "medico_social"),
    ("medico_social_personnes_handicapees", "Établissements et services pour personnes handicapées", "medico_social"),
    ("fir", "Fonds d'intervention régional et soutien national à l'investissement", None),
    ("autres_prises_en_charge", "Autres prises en charge", None),
]
COMPOSITION_ONDAM = {
    "soins_de_ville": "honoraires médicaux, dentaires et paramédicaux, rémunérations forfaitaires, biologie, "
                      "transports, produits de santé (médicaments de ville, rétrocession hospitalière, dispositifs "
                      "médicaux, nets des remises et de la clause de sauvegarde), indemnités journalières maladie et "
                      "accidents du travail, cotisations des professionnels de santé prises en charge",
    "etablissements_sante": "activité de médecine, chirurgie, obstétrique des établissements publics et privés, soins "
                            "médicaux et de réadaptation, psychiatrie, soins de longue durée, dotations et forfaits, "
                            "médicaments et dispositifs facturés en plus des séjours",
    "medico_social": "dépenses des établissements et services pour personnes âgées et pour personnes handicapées",
    "fir": "dotations de l'assurance maladie au fonds d'intervention régional des agences régionales de santé et au "
           "fonds pour la modernisation et l'investissement en santé ; aides à l'investissement médico-social depuis "
           "2022",
    "autres_prises_en_charge": "soins des assurés français à l'étranger, dotations aux opérateurs financés par "
                               "l'assurance maladie, dépenses médico-sociales hors champ de la Caisse nationale de "
                               "solidarité pour l'autonomie",
}

# --- Utilitaires -----------------------------------------------------------------------------------------------------


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = s.replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def nombre(v) -> float | None:
    """Nombre de la source ; « NS », « NC », vide, texte : None (jamais 0)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if not s or s.upper() in ("NS", "NC", "ND", "-", "S"):
        return None
    s = s.replace(",", ".")
    if s.count(".") > 1:  # séparateur de milliers « . » (fichiers HTOT : « 9.671.38 », « 1.408,77 »)
        tete, fin = s.rsplit(".", 1)
        s = tete.replace(".", "") + "." + fin
    try:
        return float(s)
    except ValueError:
        return None


def motif_absence(v) -> str | None:
    s = str(v or "").strip().upper()
    if s == "NS":
        return "secret_statistique"
    if s == "NC":
        return "non_calcule"
    if s == "":
        return "absent"
    return None


def md(v, d: int = 3) -> float | None:
    return None if v is None else round(float(v), d) + 0.0  # + 0.0 : jamais « -0.0 »


def code_dep(code: str) -> str:
    c = str(code or "").strip()
    if c.endswith(".0"):
        c = c[:-2]
    return c.zfill(2) if c.isdigit() and len(c) < 2 else c


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n",
                    encoding="utf-8")


def chemin(cle: str, an: int | None = None) -> Path:
    f = SOURCES[cle]["fichier"]
    return BRUT / (f.replace("<an>", str(an)) if an is not None else f)


def url_source(cle: str, an: int | None = None) -> str:
    u = SOURCES[cle]["url"]
    return u.replace("<an>", str(an)) if an is not None else u


# --- Lecture : data.ameli.fr -------------------------------------------------------------------------------------------


def _lignes_csv(p: Path):
    with open(p, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f, delimiter=";")


def lire_honoraires() -> tuple[dict, dict]:
    """{annee: {dep: {groupe: {"sans_depassement": v, "depassements": v}}}}, {dep: nom}. dep « FR » = France."""
    voulus = {lib: gid for gid, lib, _ in PROFESSIONS}
    out: dict = defaultdict(lambda: defaultdict(dict))
    noms: dict[str, str] = {}
    absences: dict = defaultdict(int)
    for r in _lignes_csv(chemin("amt_ameli_honoraires")):
        gid = voulus.get(r["profession_sante"].strip())
        if gid is None:
            continue
        dep = code_dep(r["departement"])
        if dep == "999":
            if r["region"].strip() != "99":
                continue  # totaux régionaux : non repris (la vue est départementale)
            dep = "FR"
        else:
            noms.setdefault(dep, r["libelle_departement"].strip())
        an = int(r["annee"][:4])
        cell = {}
        for cle, col in (("sans_depassement", "hono_sans_depassement_totaux"), ("depassements", "depassements_totaux")):
            v = nombre(r[col])
            cell[cle] = None if v is None else int(round(v))
            if v is None:
                cell[f"{cle}_absence"] = motif_absence(r[col]) or "absent"
                absences[(an, cell[f"{cle}_absence"])] += 1
        out[an][dep][gid] = cell
    return out, noms


def lire_prescriptions() -> dict:
    """{annee: {dep: {poste: valeur | None}}} ; dep « FR » = France ; prescriptions de l'ensemble des médecins."""
    postes = {code: pid for code, pid, _ in POSTES_PRESCRIPTION}
    out: dict = defaultdict(lambda: defaultdict(dict))
    for r in _lignes_csv(chemin("amt_ameli_prescriptions")):
        if r["profession_sante"].strip() != "Ensemble des médecins":
            continue
        dep = code_dep(r["departement"])
        if dep == "999":
            if r["region"].strip() != "99":
                continue
            dep = "FR"
        pid = postes.get(r["poste_prescription"].strip())
        if pid is None:
            continue
        v = nombre(r["montant_total_prescription"])
        out[int(r["annee"][:4])][dep][pid] = None if v is None else int(round(v))
        if v is None:
            out[int(r["annee"][:4])][dep][f"{pid}_absence"] = motif_absence(r["montant_total_prescription"])
    return out


# --- Établissements privés : agrégation en flux (collecte) puis lecture de l'agrégat ---------------------------------

COLONNES_AGREGAT = ["annee", "mois", "dpt", "l_dpt", "eta_typ", "l_eta_typ", "serie", "l_serie", "rem_mon"]


def agreger_es(zip_path: Path, an: int, dest: Path) -> dict:
    """Lit l'archive annuelle mois par mois (en flux), écrit l'agrégat (département, statut, série, mois)."""
    sommes: dict = defaultdict(float)
    libelles: dict = {}
    mois_vus = set()
    lignes = 0
    with zipfile.ZipFile(zip_path) as z:
        for nom in sorted(z.namelist()):
            if not nom.upper().endswith(".CSV"):
                continue
            with z.open(nom) as brut:
                lecteur = csv.reader(io.TextIOWrapper(brut, encoding="latin-1", newline=""), delimiter=";")
                tete = next(lecteur)
                ix = {k.strip().lower(): i for i, k in enumerate(tete)}
                manque = {"trt_date", "rem_mon", "dpt", "l_dpt", "eta_typ", "l_eta_typ", "serie", "l_serie"} - set(ix)
                if manque:
                    raise SystemExit(f"{nom} : colonnes absentes {sorted(manque)} (format de la source changé)")
                for row in lecteur:
                    if len(row) < len(tete):
                        continue
                    mois = row[ix["trt_date"]].strip()
                    if not mois.startswith(str(an)):
                        continue
                    v = nombre(row[ix["rem_mon"]])
                    if v is None:
                        continue
                    dpt = code_dep(row[ix["dpt"]])
                    cle = (mois, dpt, row[ix["eta_typ"]].strip(), row[ix["serie"]].strip())
                    sommes[cle] += v
                    libelles[("dpt", dpt)] = row[ix["l_dpt"]].strip()
                    libelles[("eta", cle[2])] = row[ix["l_eta_typ"]].strip()
                    libelles[("serie", cle[3])] = row[ix["l_serie"]].strip()
                    mois_vus.add(mois)
                    lignes += 1
    tmp = dest.with_suffix(".csv.part")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(COLONNES_AGREGAT)
        for (mois, dpt, eta, serie), v in sorted(sommes.items()):
            w.writerow([an, mois, dpt, libelles[("dpt", dpt)], eta, libelles[("eta", eta)], serie,
                        libelles[("serie", serie)], f"{v:.2f}"])
    tmp.replace(dest)
    return {"lignes_lues": lignes, "mois": sorted(mois_vus), "cellules": len(sommes)}


def poste_es(libelle: str) -> str | None:
    """Poste publié d'une série ; None pour une ligne « dont » (sous-total jamais additionné)."""
    n = norm(libelle).strip('"')
    if n.startswith("dont"):
        return None
    regles = [
        ("autres", ("long sejour",)),
        ("medicaments_dispositifs_en_sus", ("en sus", "dispositifs medicaux", "lpp", "atu", "medicaments sous",
                                            "pharmaceutique")),
        ("dialyse", ("dialyse",)),
        ("hospitalisation_domicile", ("domicile", "(ght)")),
        ("smr", ("ssr", "smr", "readaptation", "moyen sejour")),
        ("psychiatrie", ("psychiatr", "psy", "maladies mentales")),
        ("medico_social", ("handicap", "inadapt", "personnes agees")),
        ("imagerie", ("scanner", "irm", "tomographie", "forfait technique", "forfaits techniques")),
        ("sejours_mco", ("ghs", "sejour", "urgence", "migac", "odmco", "ifaq", "coefficient prudentiel", "neonat",
                         "proximite", "securite et environnement", "pathologie chronique", "reanimation",
                         "prelevement", "greffe", "transplantation", "accueil", "medecine", "chirurgie",
                         "gynecologie")),
    ]
    for pid, mots in regles:
        if any(m in n for m in mots):
            return pid
    return "autres"


def statut_es(libelle: str) -> str:
    n = norm(libelle)
    if "public" in n:
        return "public"
    if "non lucratif" in n:
        return "prive_non_lucratif"
    if "lucratif" in n:
        return "prive_lucratif"
    return "autre"


def lire_es(an: int) -> dict | None:
    p = chemin("amt_es_cpam", an)
    if not p.exists():
        return None
    par_dep: dict = defaultdict(lambda: {"total": 0.0, "postes": defaultdict(float), "statuts": defaultdict(float)})
    series: dict = {}
    mois = set()
    noms = {}
    for r in _lignes_csv(p):
        v = float(r["rem_mon"])
        mois.add(r["mois"])
        pid = poste_es(r["l_serie"])
        series[r["serie"]] = (r["l_serie"], pid)
        if pid is None:
            continue
        dep = r["dpt"]
        noms[dep] = re.sub(r"^\w{2,3}-", "", r["l_dpt"]).strip()
        d = par_dep[dep]
        d["total"] += v
        d["postes"][pid] += v
        d["statuts"][statut_es(r["l_eta_typ"])] += v
    return {"annee": an, "mois": sorted(mois), "complet": len(mois) == 12, "departements": par_dep,
            "series": dict(sorted(series.items())), "noms": noms}


# --- ONDAM -------------------------------------------------------------------------------------------------------------


def id_sous_objectif(libelle: str) -> str | None:
    n = norm(libelle)
    if n.startswith("ondam total"):
        return "total"
    if n.startswith("soins de ville"):
        return "soins_de_ville"
    if n.startswith("etablissements de sante"):
        return "etablissements_sante"
    if n.startswith("etablissements et services medico") or n.startswith("etablissements et services medico-soc"):
        return "medico_social"
    if "personnes agees" in n:
        return "medico_social_personnes_agees"
    if "handicap" in n:
        return "medico_social_personnes_handicapees"
    if "fonds d'intervention regional" in n:
        return "fir"
    if n.startswith("autres prise"):
        return "autres_prises_en_charge"
    return None


# Constats lus dans les classeurs : (source, feuille, colonnes) ; colonnes = indices dans la ligne (0 = libellé)
CONSTATS_XLSX = {
    2025: ("amt_plfss2027_annexe_ondam", "I.2.1 Tableau 3",
           {"objectif_initial": 1, "objectif_rectifie": 2, "constat": 3, "ecart_objectif_initial": 5,
            "ecart_objectif_rectifie": 6}, "Constat 2025 actualisé en septembre 2026 (PLFSS 2027)"),
    2024: ("amt_plfss2026_annexe_ondam", "I.2_Tableau 1",
           {"objectif_initial": 1, "objectif_rectifie": 2, "constat": 3, "taux": 5, "ecart_objectif_initial": 6,
            "ecart_objectif_rectifie": 7}, "Constat 2024 d'octobre 2025 (PLFSS 2026)"),
    2023: ("amt_plfss2025_annexe_ondam", "I.2_Tableau 1",
           {"base": 1, "objectif_initial": 2, "objectif_rectifie": 3, "constat": 4, "taux": 5,
            "ecart_objectif_initial": 6, "ecart_objectif_rectifie": 7}, "Constat 2023 (PLFSS 2025)"),
    2022: ("amt_plfss2024_annexe_ondam", "I_Tableau 3",
           {"base": 1, "objectif_initial": 2, "objectif_rectifie": 3, "constat": 4, "taux": 5,
            "ecart_objectif_initial": 6, "ecart_objectif_rectifie": 7}, "Constat 2022 (PLFSS 2024)"),
    2021: ("amt_plfss2023_annexe_ondam", "I_Tableau_3",
           {"base": 2, "objectif_initial": 3, "objectif_rectifie": 4, "constat": 5, "taux": 6,
            "ecart_objectif_initial": 7, "ecart_objectif_rectifie": 8}, "Constat 2021 (PLFSS 2023)"),
}
# Constats saisis dans le texte des PDF (Md€ ; taux en %), revérifiés à chaque production contre le texte extrait.
# Ordre des colonnes de la source : base, objectif initial, objectif rectifié, constat, taux, puis les deux écarts.
CONSTATS_PDF = {
    2020: ("amt_plfss2022_annexe7", "Constat 2020 (PLFSS 2022, tableau 3)", "rectifie_puis_initial", {
        "total": "ONDAM TOTAL 200,3 200,6 205,6 218,9 219,4 9,4% 0,5 13,8",
        "soins_de_ville": "Soins de ville 91,4 91,3 93,6 93,8 94,7 3,7% 0,9 1,2",
        "etablissements_sante": "Établissements de santé 82,6 82,5 84,4 90,0 89,7 8,8% -0,3 5,3",
        "medico_social": "Établissements et services médico-sociaux 20,9 21,0 21,6 24,0 24,0 14,4% 0,0 2,3",
        "medico_social_personnes_agees": "9,6 9,6 10,0 12,0 12,0 24,8% 0,0 2,0",
        "medico_social_personnes_handicapees": "11,4 11,4 11,7 12,0 12,0 5,6% 0,0 0,3",
        "fir": "Dépenses relatives au Fonds d'intervention régional 3,5 3,5 3,6 3,9 3,9 10,7% 0,0 0,3",
        "autres_prises_en_charge": "Autres prises en charges 1,9 2,3 2,4 7,2 7,0 211,7% -0,2 4,6",
    }),
    2019: ("amt_plfss2021_annexe7", "Constat 2019 (PLFSS 2021, tableau 1)", "rectifie_puis_initial", {
        "total": "ONDAM TOTAL 195,1 195,2 200,4 200,4 200,2 2,6% -0,1 -0,1",
        "soins_de_ville": "Soins de ville 89,2 89,0 91,5 91,4 91,4 2,6% 0,0 -0,1",
        "etablissements_sante": "Établissements de santé 80,4 80,4 82,6 82,6 82,4 2,5% -0,1 -0,1",
        "medico_social": "Établissements et services médico-sociaux 20,4 20,5 20,8 21,0 20,9 2,3% 0,0 0,1",
        "medico_social_personnes_agees": "9,2 9,3 9,5 9,6 9,6 3,3% 0,0 0,1",
        "medico_social_personnes_handicapees": "11,1 11,2 11,4 11,4 11,4 1,5% 0,0 0,0",
        "fir": "Dépenses relatives au Fonds d'intervention régional 3,3 3,3 3,5 3,5 3,5 4,9% 0,0 0,0",
        "autres_prises_en_charge": "Autres prises en charge 1,8 1,9 1,9 2,0 1,9 5,0% 0,0 0,0",
    }),
}

RUPTURES = [
    {"annee": 2021, "sous_objectifs": ["medico_social", "medico_social_personnes_agees",
                                        "medico_social_personnes_handicapees"],
     "note": "jusqu'en 2020, la source présente la contribution de l'assurance maladie aux dépenses médico-sociales ; à "
             "partir de 2021 (création de la branche autonomie), l'ensemble des dépenses des établissements et services "
             "financées dans le champ de l'ONDAM : le constat 2020 est de 24,0 Md€ dans l'ancien champ et la base 2021 "
             "de 25,4 Md€ dans le nouveau"},
    {"annee": 2021, "sous_objectifs": ["fir"],
     "note": "le sous-objectif comprend le soutien national à l'investissement (fonds pour la modernisation et "
             "l'investissement en santé) à partir de 2021, et les aides à l'investissement médico-social à partir de "
             "2022"},
    {"annee": 2020, "sous_objectifs": ["total", "autres_prises_en_charge", "etablissements_sante", "soins_de_ville"],
     "note": "2020 à 2023 : les dépenses liées à la crise sanitaire (tests, vaccins, masques, indemnités "
             "journalières dérogatoires, dotations à Santé publique France) sont incluses, surtout dans « autres prises "
             "en charge » ; elles atteignent 18,3 Md€ en 2020 et 2021, 11,7 Md€ en 2022, 1,1 Md€ en 2023 et 0,4 Md€ "
             "en 2024 (PLFSS 2026, annexe 5)"},
]
MOTIFS_COVID = {"amt_plfss2026_annexe_ondam": None}  # chiffres covid lus dans le PDF de l'annexe (repère, voir note)


def _xlsx_lignes(cle: str, feuille: str) -> list[list]:
    import openpyxl
    wb = openpyxl.load_workbook(chemin(cle), read_only=True, data_only=True)
    try:
        return [list(r) for r in wb[feuille].iter_rows(values_only=True)]
    finally:
        wb.close()


def _ligne_utile(row: list) -> tuple[str, list] | None:
    """Libellé (première cellule texte) et valeurs qui suivent ; None si la ligne n'a pas de libellé."""
    cells = [c for c in row if c is not None]
    if not cells or not isinstance(cells[0], str):
        return None
    return cells[0], cells


def lire_constat_xlsx(an: int) -> dict:
    cle, feuille, cols, libelle = CONSTATS_XLSX[an]
    lignes = _xlsx_lignes(cle, feuille)
    titre = next((c for r in lignes for c in r if isinstance(c, str) and "alisation" in c), "")
    if str(an) not in titre:
        raise SystemExit(f"{cle} : feuille {feuille} ne porte pas sur {an} ({titre!r})")
    valeurs = {}
    for row in lignes:
        lu = _ligne_utile(row)
        if not lu:
            continue
        sid = id_sous_objectif(lu[0])
        if sid is None or sid in valeurs:
            continue
        cells = lu[1]
        v = {k: (md(cells[i]) if i < len(cells) and isinstance(cells[i], (int, float)) else None)
             for k, i in cols.items() if k != "taux"}
        if "taux" in cols:
            t = cells[cols["taux"]] if cols["taux"] < len(cells) else None
            v["taux_evolution_pct"] = round(t * 100, 1) if isinstance(t, (int, float)) else None
        valeurs[sid] = v
    if an == 2025:  # taux 2025 : tableau 4 du même classeur
        for row in _xlsx_lignes(cle, "I.2.1 Tableau 4"):
            lu = _ligne_utile(row)
            sid = id_sous_objectif(lu[0]) if lu else None
            if sid in valeurs and isinstance(lu[1][1], (int, float)):
                valeurs[sid]["taux_evolution_pct"] = round(lu[1][1] * 100, 1)
    manquants = [s for s, _, _ in SOUS_OBJECTIFS if s not in valeurs]
    if manquants:
        raise SystemExit(f"{cle} : sous-objectifs absents {manquants}")
    return {"source": cle, "document": libelle, "valeurs": valeurs}


def texte_pdf(cle: str) -> str:
    out = subprocess.run(["pdftotext", "-layout", str(chemin(cle)), "-"], capture_output=True, check=True).stdout
    return re.sub(r"\s+", " ", out.decode("utf-8", "replace").replace("’", "'"))


def lire_constat_pdf(an: int, texte: str | None = None) -> dict:
    cle, libelle, ordre, motifs = CONSTATS_PDF[an]
    texte = texte if texte is not None else texte_pdf(cle)
    valeurs = {}
    for sid, motif in motifs.items():
        if motif not in texte:
            raise SystemExit(f"{cle} : ligne « {motif} » introuvable dans le texte (document modifié ?)")
        nums = re.findall(r"-?\d+,\d+%?", motif)
        f = [float(x.rstrip("%").replace(",", ".")) for x in nums]
        base, init, rect, constat, taux, e1, e2 = f[-7:]
        e_rect, e_init = (e1, e2) if ordre == "rectifie_puis_initial" else (e2, e1)
        valeurs[sid] = {"base": base, "objectif_initial": init, "objectif_rectifie": rect, "constat": constat,
                        "taux_evolution_pct": taux, "ecart_objectif_initial": e_init,
                        "ecart_objectif_rectifie": e_rect}
    return {"source": cle, "document": libelle, "valeurs": valeurs}


def lire_objectifs_2026_2027() -> dict:
    cle = "amt_plfss2027_annexe_ondam"
    out = {"2026_lfss": {}, "2026_prevision_plfss2027": {}, "2027_plfss": {}}
    for row in _xlsx_lignes(cle, "I.3.1 Tableau 5"):
        lu = _ligne_utile(row)
        sid = id_sous_objectif(lu[0]) if lu else None
        if sid and isinstance(lu[1][2], (int, float)):
            out["2026_lfss"][sid] = md(lu[1][2])
    for row in _xlsx_lignes(cle, "I.3.3 Tableau 8"):
        lu = _ligne_utile(row)
        sid = id_sous_objectif(lu[0]) if lu else None
        if sid and isinstance(lu[1][2], (int, float)):
            out["2026_prevision_plfss2027"][sid] = md(lu[1][2])
    lignes = _xlsx_lignes(cle, "I.5 Tableau 13")
    entete = next(r for r in lignes if r and any(isinstance(c, str) and "Soins de ville" in c for c in r))
    ids = [("total" if isinstance(c, str) and "ONDAM 2027" in c else id_sous_objectif(c)) if isinstance(c, str)
           else None for c in entete]
    ligne = next(r for r in lignes if r and isinstance(r[0] if r[0] is not None else r[1], str)
                 and "ONDAM 2027" in str(r[0] or r[1]) and "PLFSS" in str(r[0] or r[1]))
    for sid, v in zip(ids, ligne):
        if sid and isinstance(v, (int, float)):
            out["2027_plfss"][sid] = md(v)
    out["2027_plfss"].setdefault("medico_social", None)  # le tableau 13 ne publie que les deux composantes
    return out


# --- Production ------------------------------------------------------------------------------------------------------


def _entete(millesime: str, source: str) -> dict:
    return {"millesime": millesime, "source": source}


def produire_ondam() -> dict:
    constats = {}
    for an in sorted(CONSTATS_PDF):
        constats[str(an)] = lire_constat_pdf(an)
    for an in sorted(CONSTATS_XLSX):
        constats[str(an)] = lire_constat_xlsx(an)
    obj = lire_objectifs_2026_2027()
    # Cohérence publiée : les deux composantes médico-sociales s'ajoutent au sous-objectif (arrondis de la source)
    controles = []
    for an, c in constats.items():
        v = c["valeurs"]
        somme = sum(v[s]["constat"] for s in ("soins_de_ville", "etablissements_sante", "medico_social", "fir",
                                               "autres_prises_en_charge"))
        controles.append({"annee": int(an), "total_publie": v["total"]["constat"], "somme_sous_objectifs": md(somme, 2),
                          "difference_arrondis": md(v["total"]["constat"] - somme, 2)})
    annees = sorted(int(a) for a in constats)
    sources = sorted({c["source"] for c in constats.values()} | {"amt_plfss2027_annexe_ondam"})
    return {
        **_entete(f"Constats {annees[0]} à {annees[-1]}, objectifs 2026 et 2027",
                  "; ".join(url_source(s) for s in sources)),
        "unite": "milliards d'euros (Md€), dépenses dans le champ de l'ONDAM, tous régimes, en droits constatés",
        "date_sources": date_sources(AXE),
        "definition": "L'objectif national de dépenses d'assurance maladie (ONDAM) est voté chaque année par le "
                      "Parlement dans la loi de financement de la sécurité sociale ; il est découpé en sous-objectifs. "
                      "Le constat est la dépense finalement enregistrée dans ce champ, publiée par la direction de la "
                      "sécurité sociale dans l'annexe « ONDAM et dépenses de santé » du projet de loi de l'année "
                      "suivante (actualisée en septembre).",
        "sous_objectifs": [{"id": s, "libelle": lib, "parent": p, "composition": COMPOSITION_ONDAM.get(s)}
                           for s, lib, p in SOUS_OBJECTIFS],
        "annees": annees,
        "derniere_annee": annees[-1],
        "definitions": {
            "base": "dépense de l'année précédente, ramenée au champ de l'année (publiée certaines années)",
            "objectif_initial": "objectif voté dans la loi de financement de l'année",
            "objectif_rectifie": "objectif révisé par la loi de financement de l'année suivante",
            "constat": "dépense constatée dans le champ de l'ONDAM",
            "taux_evolution_pct": "évolution publiée par la source, à champ constant (pas recalculée ici)",
            "ecart_objectif_initial": "constat moins objectif initial, publié par la source (positif : dépense "
                                      "au-dessus de l'objectif)",
            "ecart_objectif_rectifie": "constat moins objectif rectifié, publié par la source",
        },
        "constats": constats,
        "objectifs": {
            "2026": {"statut": "objectif voté (loi de financement de la sécurité sociale pour 2026)",
                     "valeurs": obj["2026_lfss"], "source": "amt_plfss2027_annexe_ondam"},
            "2026_prevision": {"statut": "prévision de dépense 2026 publiée avec le projet de loi pour 2027 (non "
                                         "constatée)", "valeurs": obj["2026_prevision_plfss2027"],
                               "source": "amt_plfss2027_annexe_ondam"},
            "2027": {"statut": "objectif proposé par le projet de loi de financement pour 2027 (non voté)",
                     "valeurs": obj["2027_plfss"], "source": "amt_plfss2027_annexe_ondam",
                     "note": "le tableau 13 de la source publie séparément les établissements pour personnes âgées "
                             "et pour personnes handicapées, sans leur total : celui-ci reste null"},
        },
        "ruptures_de_champ": RUPTURES,
        "controles_arrondis": controles,
        "liens": [
            {"vue": "secu_arbre", "fichier": "secu/arbre/racine.json",
             "lecture": "ONDAM 2024 détaillé (soins de ville par poste : honoraires, produits de santé, indemnités "
                        "journalières...) et autres dépenses de la branche maladie ; même argent, autre découpage"},
            {"vue": "sante_etablissements", "fichier": "sante_etablissements/index.json",
             "lecture": "référentiel et activité des établissements de santé et médico-sociaux"},
        ],
        "regle": "montants publiés par la source, sans recalcul ; un écart est celui publié par la source ; les "
                 "constats de différentes éditions ne sont pas révisés après coup",
    }


def _bloc_honoraires(h: dict) -> dict:
    out = {}
    for gid, _, _ in PROFESSIONS:
        c = h.get(gid)
        out[gid] = c if c is not None else {"sans_depassement": None, "depassements": None,
                                             "sans_depassement_absence": "absent", "depassements_absence": "absent"}
    return out


def _bloc_prescriptions(p: dict) -> dict:
    out = {}
    for _, pid, _ in POSTES_PRESCRIPTION:
        out[pid] = p.get(pid)
        if p.get(f"{pid}_absence"):
            out[f"{pid}_absence"] = p[f"{pid}_absence"]
    return out


def _bloc_es(d: dict | None) -> dict | None:
    if d is None:
        return None
    return {"total": round(d["total"]), "postes": {pid: round(d["postes"].get(pid, 0.0)) for pid, _ in POSTES_ES},
            "statuts": {sid: round(d["statuts"].get(sid, 0.0)) for sid, _ in STATUTS_ES}}


def produire() -> dict:
    hono, noms = lire_honoraires()
    presc = lire_prescriptions()
    es = {an: lire_es(an) for an in ANNEES_ES}
    es = {an: v for an, v in es.items() if v is not None}
    deps = sorted(noms, key=lambda c: (len(c) > 2, c))
    annees = sorted(set(hono) | set(presc))
    date = date_sources(AXE)
    SORTIE.mkdir(parents=True, exist_ok=True)

    ondam = produire_ondam()
    dump(SORTIE / "ondam.json", ondam)

    fichiers_dep = {}
    france = {}
    hors_departements = {}
    for an in annees:
        e = es.get(an)
        lignes = []
        for dep in deps:
            lignes.append({
                "code": dep, "nom": noms[dep],
                "honoraires": _bloc_honoraires(hono.get(an, {}).get(dep, {})),
                "prescriptions_medecins": _bloc_prescriptions(presc.get(an, {}).get(dep, {})),
                "etablissements_prives": _bloc_es(e["departements"].get(dep)) if e else None,
            })
        nat_es = None
        if e:
            nat = {"total": 0.0, "postes": defaultdict(float), "statuts": defaultdict(float)}
            for dep, d in e["departements"].items():
                nat["total"] += d["total"]
                for k, v in d["postes"].items():
                    nat["postes"][k] += v
                for k, v in d["statuts"].items():
                    nat["statuts"][k] += v
            nat_es = _bloc_es(nat)
            hors = sorted(set(e["departements"]) - set(deps))
            if hors:
                hors_departements[str(an)] = {c: round(e["departements"][c]["total"]) for c in hors}
        fr = {"honoraires": _bloc_honoraires(hono.get(an, {}).get("FR", {})),
              "prescriptions_medecins": _bloc_prescriptions(presc.get(an, {}).get("FR", {})),
              "etablissements_prives": nat_es}
        france[str(an)] = fr
        rel = f"{AXE}/departements/{an}.json"
        doc = {
            **_entete(str(an), "; ".join([SOURCES["amt_ameli_honoraires"]["page"],
                                          SOURCES["amt_ameli_prescriptions"]["page"]]
                                         + ([url_source("amt_es_cpam", an)] if e else []))),
            "annee": an, "unite": "euros (montant annuel)", "date_sources": date,
            "etablissements_prives_mois": e["mois"] if e else [],
            "etablissements_prives_complet": bool(e and e["complet"]),
            "france": fr,
            "departements": lignes,
        }
        dump(SITE / rel, doc)
        fichiers_dep[str(an)] = rel

    # Séries des établissements privés : correspondance série -> poste publiée (transparence du regroupement)
    correspondance = {}
    for an, e in sorted(es.items()):
        for code, (lib, pid) in e["series"].items():
            correspondance.setdefault(code, {"libelle_source": lib, "poste": pid})

    # Contrôles : sommes des professions publiées par la Cnam (France, dernière année complète)
    controles = []
    for an in annees:
        fr = france[str(an)]["honoraires"]
        for g, parts in COMPOSITION_PROFESSIONS.items():
            tot = fr[g]["sans_depassement"]
            vals = [fr[p]["sans_depassement"] for p in parts]
            if tot is not None and None not in vals:
                controles.append({"annee": an, "groupe": g, "publie": tot, "somme_composantes": sum(vals),
                                  "difference": tot - sum(vals)})

    dernier_complet_es = max((an for an, e in es.items() if e["complet"]), default=None)
    index = {
        **_entete(f"{annees[0]} à {annees[-1]} (honoraires et prescriptions) ; établissements privés "
                  f"{', '.join(str(a) for a in sorted(es))} ; ONDAM {ondam['annees'][0]} à {ondam['annees'][-1]}",
                  "; ".join([SOURCES["amt_ameli_honoraires"]["page"], SOURCES["amt_ameli_prescriptions"]["page"],
                             SOURCES["amt_es_cpam"]["page"], SOURCES["amt_plfss2027_annexe_ondam"]["page"]])),
        "unite": "euros (montants annuels) ; ONDAM en milliards d'euros",
        "date_sources": date,
        "perimetre": "Dépenses de l'assurance maladie vues de trois façons qui ne s'additionnent pas : (1) l'ONDAM, "
                     "objectif national voté chaque année et son exécution par sous-objectif, tous régimes ; (2) par "
                     "département, l'activité des professionnels de santé libéraux (honoraires) et ce que les médecins "
                     "libéraux prescrivent (médicaments, biologie, transports, arrêts de travail...), sur la base de "
                     "remboursement ; (3) par département, les montants remboursés par le régime général aux "
                     "établissements de santé privés (cliniques).",
        "annees": annees,
        "derniere_annee": annees[-1],
        "annees_etablissements_prives": sorted(es),
        "derniere_annee_etablissements_prives_complete": dernier_complet_es,
        "fichiers": {"ondam": f"{AXE}/ondam.json", "departements": fichiers_dep},
        "departements": [{"code": d, "nom": noms[d]} for d in deps],
        "ordre": {"cles": ["code"], "regle": "ordre des codes officiels des départements (métropole puis outre-mer), "
                                            "jamais un classement par montant"},
        "professions": [{"id": g, "libelle": lib, "libelle_source": src} for g, src, lib in PROFESSIONS],
        "postes_prescription": [{"id": p, "libelle": lib, "code_source": c} for c, p, lib in POSTES_PRESCRIPTION],
        "postes_etablissements_prives": [{"id": p, "libelle": lib} for p, lib in POSTES_ES],
        "statuts_etablissements_prives": [{"id": s, "libelle": lib} for s, lib in STATUTS_ES],
        "correspondance_series_etablissements": correspondance,
        "france": france,
        "definitions": {
            "honoraires.sans_depassement": "honoraires des professionnels de santé libéraux au tarif de la "
                                           "convention avec l'assurance maladie (base de remboursement), y compris "
                                           "rémunérations forfaitaires et indemnités de déplacement ; département du "
                                           "cabinet principal ; professionnels actifs au 31 décembre",
            "honoraires.depassements": "part facturée au-delà du tarif conventionnel ; non remboursée par "
                                       "l'assurance maladie obligatoire",
            "prescriptions_medecins": "montant, sur la base de remboursement, de ce que les médecins libéraux du "
                                      "département ont prescrit et qui a été exécuté (par une pharmacie, un "
                                      "laboratoire, un infirmier, un transporteur...) ; indemnités journalières : "
                                      "arrêts de travail prescrits ; la base de remboursement comprend la part "
                                      "remboursée, le ticket modérateur et les franchises",
            "etablissements_prives": "montants remboursés par le régime général (85 % des dépenses de l'ensemble des "
                                     "régimes selon la source) aux établissements de santé privés et à certains "
                                     "établissements facturant directement les caisses, en date de remboursement ; "
                                     "département de la caisse primaire de l'assuré ; les lignes « dont » de la "
                                     "source sont exclues",
            "absence": "secret_statistique : moins de 5 professionnels dans le département (« NS » à la source) ; "
                       "non_calcule : « NC » à la source ; absent : ligne non publiée. Une valeur absente est null, "
                       "jamais 0.",
        },
        "comparabilite": [
            {"elements": ["honoraires", "prescriptions_medecins"],
             "lecture": "un même euro peut figurer deux fois : une séance de kinésithérapie prescrite par un médecin "
                        "est dans les prescriptions du médecin et dans les honoraires du kinésithérapeute ; ces deux "
                        "vues ne s'additionnent pas"},
            {"elements": ["prescriptions_medecins", "ondam.soins_de_ville"],
             "lecture": "la base de remboursement n'est pas le montant remboursé : la part de l'assurance maladie en "
                        "est une fraction ; l'ONDAM est en droits constatés, tous régimes, net des remises des "
                        "laboratoires"},
            {"elements": ["departements", "france"],
             "lecture": "honoraires et prescriptions : le total « France » est celui publié par la Cnam ; il peut "
                        "différer de la somme des départements (secret statistique, arrondis). Établissements privés : "
                        "le total « France » est la somme des départements et des codes hors département de la source "
                        "(voir hors_departements_etablissements_prives)"},
        ],
        "hors_departements_etablissements_prives": hors_departements,
        "controles_professions": controles[-6:],
        "liens": [
            {"vue": "secu_arbre", "fichier": "secu/arbre/racine.json",
             "lecture": "comptes de la branche maladie et ONDAM 2024 par poste (vue nationale) ; même argent, jamais "
                        "additionné aux montants par département"},
            {"vue": "sante_etablissements", "fichier": "sante_etablissements/index.json",
             "lecture": "établissements de santé par département (référentiel, activité) ; aucun versement par "
                        "établissement n'est ouvert après 2015"},
            {"vue": "prestations", "fichier": "prestations/index.json",
             "lecture": "autres prestations sociales par département"},
        ],
        "regle": "aucun professionnel ni établissement nommé ; trois champs jamais additionnés ; ordre des "
                 "départements par code ; valeurs absentes null avec motif",
        "limites": [
            "Aucun montant par département pour les hôpitaux publics (dotations et séjours valorisés) : non ouvert.",
            "Les honoraires et prescriptions sont localisés au cabinet du professionnel, pas au domicile du patient.",
            "Les établissements privés sont suivis pour le seul régime général ; une année incomplète est signalée "
            "par la liste des mois couverts.",
            "Les montants ne sont pas rapportés à la population : aucun classement entre départements n'est fait ici.",
        ],
        "sources": {k: {kk: v for kk, v in s.items() if kk != "fichier"} for k, s in SOURCES.items()},
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(SORTIE / "index.json", index)
    return {"annees": annees, "departements": len(deps), "etablissements_prives": sorted(es),
            "ondam": ondam["annees"]}


# --- Collecte --------------------------------------------------------------------------------------------------------


def _manifeste(sid: str, fichiers: list[dict], extra: dict | None = None) -> None:
    MANIFESTE.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFESTE.with_name(MANIFESTE.name + ".lock"), "w") as v:
        fcntl.flock(v, fcntl.LOCK_EX)
        try:
            m = json.loads(MANIFESTE.read_text(encoding="utf-8")) if MANIFESTE.exists() else {}
            m[sid] = {"collecte_le": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                      "domaine": AXE, "origine": f"pipeline/{AXE}.py", "personnes_physiques": False, "statut": "ok",
                      "licence": SOURCES.get(sid, {}).get("licence", SOURCES["amt_es_cpam"]["licence"]),
                      "fichiers": fichiers, **(extra or {})}
            tmp = MANIFESTE.with_name(MANIFESTE.name + ".tmp")
            tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, MANIFESTE)
        finally:
            fcntl.flock(v, fcntl.LOCK_UN)


def _desc(p: Path, url: str) -> dict:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return {"chemin": str(p.relative_to(ROOT)), "octets": p.stat().st_size, "sha256": h.hexdigest(), "url": url}


def _curl(url: str, dest: Path) -> int:
    """Téléchargement par curl (proxy et autorités de certification de l'environnement) ; renvoie le code HTTP.

    curl plutôt que requests : certains serveurs publics (securite-sociale.fr) refusent la négociation TLS de la
    bibliothèque Python ; ce n'est pas un contournement d'accès, la même requête publique est faite."""
    r = subprocess.run(["curl", "-sS", "-L", "--max-time", "900", "-A", "ou-vont-mes-impots/pipeline", "-o", str(dest),
                        "-w", "%{http_code}", url], capture_output=True, text=True)
    if r.returncode != 0:
        raise OSError(f"curl {r.returncode} : {r.stderr.strip()[:160]}")
    return int(r.stdout.strip() or 0)


def telecharger(url: str, dest: Path, essais: int = 5, attendu: bytes | None = None) -> str:
    derniere = ""
    tmp = dest.with_suffix(dest.suffix + ".part")
    for i in range(essais):
        try:
            code = _curl(url, tmp)
            if code in (401, 403, 429, 451):
                tmp.unlink(missing_ok=True)
                return f"accès refusé (HTTP {code}) : aucun contournement"
            if code >= 400:
                raise OSError(f"HTTP {code}")
            debut = tmp.read_bytes()[:256]
            if (attendu and not debut.startswith(attendu)) or b"<html" in debut.lower():
                tmp.unlink()
                return "contenu inattendu (page HTML au lieu du fichier) : aucun contournement"
            tmp.replace(dest)
            return "ok"
        except Exception as e:  # reprise réseau espacée
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(10 * (i + 1))
    tmp.unlink(missing_ok=True)
    return f"échec après {essais} essais : {derniere}"


ATTENDU = {"xlsx": b"PK\x03\x04", "pdf": b"%PDF", "csv": None}


def collecter(forcer: bool = False) -> dict:
    BRUT.mkdir(parents=True, exist_ok=True)
    etat = {}
    for cle, s in SOURCES.items():
        if cle == "amt_es_cpam":
            continue
        dest = chemin(cle)
        if dest.exists() and dest.stat().st_size > 0 and not forcer:
            etat[cle] = "présent"
        else:
            etat[cle] = telecharger(s["url"], dest, attendu=ATTENDU[s["format"]])
            if etat[cle] == "ok":
                _manifeste(cle, [_desc(dest, s["url"])])
        print(f"{cle}: {etat[cle]}", flush=True)
    for an in ANNEES_ES:
        cle = f"amt_es_cpam_{an}"
        dest = chemin("amt_es_cpam", an)
        if dest.exists() and dest.stat().st_size > 0 and not forcer:
            etat[cle] = "présent"
            print(f"{cle}: présent", flush=True)
            continue
        page = url_source("amt_es_cpam", an)
        liste = BRUT / f"ES_R_{an}.html"
        html = ""
        for i in range(5):
            try:
                if _curl(page, liste) == 200:
                    html = liste.read_text(encoding="latin-1")
                    break
            except OSError:
                pass
            time.sleep(10 * (i + 1))
        liste.unlink(missing_ok=True)
        if not html:
            etat[cle] = "page de téléchargement injoignable"
            print(f"{cle}: {etat[cle]}", flush=True)
            continue
        lien = re.search(r'href="\./(download_file\.php\?[^"]+ES_R_\d{4}\.zip)"', html)
        if not lien:
            etat[cle] = "lien de l'archive introuvable sur la page"
            continue
        archive = BRUT / f"ES_R_{an}.zip"
        etat[cle] = telecharger(f"{AMELI_DEP}/{lien.group(1)}", archive, attendu=b"PK\x03\x04")
        if etat[cle] == "ok":
            info = agreger_es(archive, an, dest)
            taille = archive.stat().st_size
            archive.unlink()  # brut lourd supprimé après agrégation
            _manifeste(cle, [_desc(dest, page)], {"archive_octets": taille, "archive_supprimee": True,
                                                  "mois": info["mois"], "lignes_lues": info["lignes_lues"]})
            etat[cle] = f"ok ({len(info['mois'])} mois, {info['lignes_lues']} lignes lues, archive supprimée)"
        print(f"{cle}: {etat[cle]}", flush=True)
    return etat


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true", help="retélécharger les sources déjà présentes")
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter(a.forcer)
    if a.etape in ("produire", "tout"):
        print(json.dumps(produire(), ensure_ascii=False))


if __name__ == "__main__":
    main()
