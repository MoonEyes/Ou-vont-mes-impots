"""Logement : aides personnelles au logement par aide et par département, MaPrimeRénov', prêts à taux zéro, renvois.

Agrégats publiés seulement (aucune donnée individuelle). Ce module complète ce que d'autres vues publient déjà, sans le
recopier : le total des aides personnelles au logement par département est dans `prestations/` (même source CNAF),
les dépenses fiscales du logement (dont le crédit d'impôt accordé aux banques pour le PTZ) dans la vue des dépenses
fiscales, les crédits des programmes 109, 135, 177 et 174 dans `arbre/` et `realisations/`, l'Anah et le FNAP dans
`operateurs/`. Il y renvoie par des liens (fichier + identifiant), jamais par des montants additionnés.

Entrées : entrepôt brut data/lake/logement/ (non versionné)
  collectées par collecte/collecte.py (sources `logement_*` de collecte/catalogue.json), lancé par `collecter` :
    logement_caf_type_logement_dep.parquet, logement_caf_type_logement_nat.parquet
        CNAF, aides au logement selon le type de logement (location, accession, foyer), par département et France,
        foyers et montants mensuels, APL, ALF et ALS séparées, champ CAF, depuis juin 2016
    logement_caf_type_parc_dep.parquet, logement_caf_type_parc_nat.parquet
        CNAF, aides au logement selon le type de parc (public, privé), mêmes champs
    logement_ditp_barometre/ind-292.csv, logement_ditp_barometre/meta_indicateurs.csv
        DITP, baromètre des résultats de l'action publique : dossiers MaPrimeRénov' validés en cumul, par département
    logement_sdes_maprimerenov_2024.xlsx
        SDES, rénovations par geste aidées par MaPrimeRénov' : dossiers par étape, montants des travaux et des aides
    logement_senat_rlrg2024_ecologie.html
        Sénat, rapport sur l'exécution 2024 (mission Écologie) : exécution des crédits de MaPrimeRénov' par programme
    logement_sgfgas_ecoptz.csv
        SGFGAS, base des éco-prêts à taux zéro 2009-2021 (une ligne par prêt, sans nom ni identifiant)
  collectée par ce module (fichier de 307 Mo, gardé compressé en flux) :
    ptz/logement_sgfgas_ptz.csv.gz (+ .json : URL, octets, empreinte, date)
        SGFGAS, base des prêts à taux zéro 1995-2021 (une ligne par prêt, sans nom ni identifiant)
  lues en lecture seule dans site/data : local/geo/ (noms des départements), prestations/, arbre/, realisations/,
  operateurs/, comparaison/fiches.json et la vue des dépenses fiscales (identifiants des mesures liées).
Sorties (site/data/logement/, contrat docs/contrat_interface.md, schémas docs/schemas/logement_*.schema.json) :
  index.json                         repères, renvois, programmes budgétaires, écarts, sources, recherche préalable
  aides_personnelles/<annee>.json    par département : APL, ALF, ALS, ensemble ; type de logement ; type de parc
  maprimerenov.json                  dossiers validés par département (cumul), repères nationaux, exécution budgétaire
  ptz.json                           PTZ et éco-PTZ émis par année et par département : nombre et montants

Commandes :
  python pipeline/logement.py collecter   # réseau ; un refus 401/403/429 est noté, jamais contourné
  python pipeline/logement.py produire [--sortie DOSSIER]   # sans réseau
  python pipeline/logement.py             # les deux

Règles :
  - deux sources ne sont jamais additionnées ; leurs écarts sont publiés (valeur, différence, part), jamais tranchés ;
  - une valeur absente à la source est null, jamais 0 ; une année incomplète à la source a un montant annuel null ;
  - un prêt à taux zéro est un prêt remboursé par le ménage : son montant n'est pas une dépense de l'État (la dépense
    est le crédit d'impôt accordé à la banque, publié par la vue des dépenses fiscales) ;
  - les citations et tableaux repris d'un document sont relus à chaque production : la production échoue s'ils ont
    changé ;
  - toute date écrite vient de pipeline/reproductible.py ou des fichiers collectés : deux productions sur le même
    entrepôt sont identiques octet pour octet.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import io
import json
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "logement"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "logement"
DOMAINE = "logement"
LO = "Licence Ouverte 2.0"
CAF = "https://data.caf.fr"
CAF_API = f"{CAF}/api/explore/v2.1/catalog/datasets"
DITP_RAW = "https://raw.githubusercontent.com/DITP-pilotage/barometre-resultats/prod"
UA = "ou-vont-mes-impots/pipeline (projet citoyen open source)"

# --- Sources ---------------------------------------------------------------------------------------------------------


def _caf(jeu: str, cle: str, titre: str) -> dict:
    return {"id_catalogue": f"logement_{cle}", "fichier": f"logement_{cle}.parquet",
            "url": f"{CAF_API}/{jeu}/exports/parquet", "page": f"{CAF}/explore/dataset/{jeu}/", "jeu": jeu,
            "titre": titre, "producteur": "CNAF", "millesime": "juin 2016 à mars 2026 (mensuel)", "licence": LO,
            "verdict": "réutilisable tel quel (export parquet de l'API Opendatasoft)"}


SOURCES = {
    "caf_type_logement_dep": _caf(
        "al_s_type_log_dep", "caf_type_logement_dep",
        "CNAF, « AL - Répartition des allocataires selon le type de logement (accession, location, foyer) "
        "[Département] » (al_s_type_log_dep) : foyers et montant versé chaque mois, APL, ALF et ALS, champ CAF"),
    "caf_type_logement_nat": _caf(
        "al_s_type_log_nat", "caf_type_logement_nat",
        "CNAF, « AL - Répartition des allocataires selon le type de logement (accession, location, foyer) "
        "[National] » (al_s_type_log_nat) : mêmes champs, France"),
    "caf_type_parc_dep": _caf(
        "al_s_type_parc_dep", "caf_type_parc_dep",
        "CNAF, « AL - Répartition des allocataires selon le type de parc (privé ou public) [Département] » "
        "(al_s_type_parc_dep) : foyers et montant versé chaque mois, APL, ALF et ALS, champ CAF"),
    "caf_type_parc_nat": _caf(
        "al_s_type_parc_nat", "caf_type_parc_nat",
        "CNAF, « AL - Répartition des allocataires selon le type de parc (parc privé ou public) [National] » "
        "(al_s_type_parc_nat) : mêmes champs, France"),
    "ditp_barometre": {
        "id_catalogue": "logement_ditp_barometre", "fichier": "logement_ditp_barometre/ind-292.csv",
        "fichier_meta": "logement_ditp_barometre/meta_indicateurs.csv",
        "url": f"{DITP_RAW}/data/ind-292.csv", "url_meta": f"{DITP_RAW}/metadata/meta_indicateurs.csv",
        "page": "https://www.data.gouv.fr/fr/datasets/6448da436f2db2fc4e9b03ee/",
        "depot": "https://github.com/DITP-pilotage/barometre-resultats",
        "titre": "Direction interministérielle de la transformation publique (DITP), « Baromètre des résultats de "
                 "l'action publique », indicateur IND-292 « Nombre de logements bénéficiaires de MaPrimeRénov’ » "
                 "(« Nombre de dossiers MaPrimeRénov’ validés en cumul »), par département, région et France, mensuel",
        "producteur": "DITP", "millesime": "décembre 2022 à juillet 2026", "licence": LO,
        "verdict": "réutilisable tel quel (CSV du dépôt public de la DITP, désigné comme « Fichiers indicateurs » par le "
                   "jeu data.gouv.fr, publié sous Licence Ouverte 2.0)"},
    "sdes_maprimerenov": {
        "id_catalogue": "logement_sdes_maprimerenov_2024", "fichier": "logement_sdes_maprimerenov_2024.xlsx",
        "url": "https://www.statistiques.developpement-durable.gouv.fr/media/9634/download?inline",
        "page": "https://www.statistiques.developpement-durable.gouv.fr/"
                "les-renovations-energetiques-par-geste-aidees-par-maprimerenov-en-2024",
        "titre": "SDES, « Les rénovations énergétiques par geste aidées par MaPrimeRénov’ en 2024 », données et "
                 "graphiques (tableaux 1 et 5) : dossiers par étape de traitement, montants des travaux et des aides, "
                 "2020 à 2024, France hors DROM, hors rénovations d'ampleur",
        "producteur": "SDES (service statistique du ministère de la Transition écologique), d'après l'Anah",
        "millesime": "2020 à 2024 (publication du 24/07/2026)",
        "licence": "licence ouverte (décret n° 2017-638), mention du SDES et de la date de mise à jour",
        "verdict": "réutilisable tel quel (classeur ; national seulement)"},
    "senat_rlrg2024": {
        "id_catalogue": "logement_senat_rlrg2024_ecologie", "fichier": "logement_senat_rlrg2024_ecologie.html",
        "url": "https://www.senat.fr/rap/l24-743-211-1/l24-743-211-11.html",
        "page": "https://www.senat.fr/rap/l24-743-211-1/l24-743-211-11.html",
        "titre": "Sénat, rapport n° 743 (2024-2025) sur le projet de loi relative aux résultats de la gestion et "
                 "portant approbation des comptes de l'année 2024, tome II, annexe 11 (Écologie, développement et "
                 "mobilité durables), tableau « Exécution des crédits de MaPrimeRénov' en CP entre 2022 et 2024 » "
                 "(commission des finances, d'après les données de la Cour des comptes)",
        "producteur": "Sénat, commission des finances", "millesime": "exécution 2022 à 2024",
        "licence": "document parlementaire public",
        "verdict": "réutilisable tel quel (tableau HTML relu cellule par cellule à chaque production)"},
    "sgfgas_ptz": {
        "id_catalogue": "logement_sgfgas_ptz", "fichier": "ptz/logement_sgfgas_ptz.csv.gz",
        "url": "https://static.data.gouv.fr/resources/base-de-donnees-ptz-prets-a-taux-zero/20220412-162011/"
               "opendataptz2022.csv",
        "page": "https://www.data.gouv.fr/fr/datasets/base-de-donnees-ptz-prets-a-taux-zero/",
        "titre": "Ministère chargé du logement et SGFGAS, « Base de données PTZ (prêts à taux zéro) » : une ligne par "
                 "prêt émis de 1995 à 2021 (année, type d'opération, département, montants), données arrêtées au "
                 "31/03/2022, sans nom ni identifiant",
        "producteur": "Ministère de la Cohésion des territoires, SGFGAS", "millesime": "prêts émis de 1995 à 2021",
        "licence": "Licence Ouverte 1.0", "octets_source": 306736644,
        "verdict": "à adapter (microdonnées : agrégées par département et par année ; copie compressée en flux)"},
    "sgfgas_ecoptz": {
        "id_catalogue": "logement_sgfgas_ecoptz", "fichier": "logement_sgfgas_ecoptz.csv",
        "url": "https://static.data.gouv.fr/resources/base-de-donnees-eco-ptz-eco-pret-a-taux-zero/20220412-141925/"
               "opendataecoptz2022.csv",
        "page": "https://www.data.gouv.fr/fr/datasets/base-de-donnees-eco-ptz-eco-pret-a-taux-zero/",
        "titre": "Ministère chargé du logement et SGFGAS, « Base de données éco-PTZ (éco-prêt à taux zéro) » : une ligne "
                 "par prêt émis de 2009 à 2021 (année, type de prêt, département, montant des travaux et du prêt), "
                 "données arrêtées au 31/03/2022, sans nom ni identifiant",
        "producteur": "Ministère de la Cohésion des territoires, SGFGAS", "millesime": "prêts émis de 2009 à 2021",
        "licence": "Licence Ouverte 1.0",
        "verdict": "à adapter (microdonnées : agrégées par département et par année)"},
}
CATALOGUE_COLLECTE = [s["id_catalogue"] for k, s in SOURCES.items() if k != "sgfgas_ptz"]

INACCESSIBLES = [
    {"source": "MaPrimeRénov' : montants d'aide par département",
     "motif": "aucun jeu national ouvert (Anah, SDES, data.gouv.fr) ne publie les montants par département ; les "
              "directions régionales (DREAL) publient des fiches PDF région par région, non reprises ; seul le nombre "
              "de dossiers validés est publié par département (baromètre de la DITP)"},
    {"source": "Aides à la pierre : logements sociaux financés et subventions par département",
     "motif": "le bilan des logements aidés n'est pas publié en données ouvertes nationales (fiches régionales des "
              "DREAL, tableaux de quelques départements délégataires) ; la Caisse des dépôts publie par département la "
              "structure des plans de financement en pourcentage (2016-2018), sans montant ; seuls les crédits budgétaires "
              "(programme 135, action 01) et les comptes du FNAP (vue des opérateurs) sont reliés"},
    {"source": "Prêts à taux zéro et éco-prêts à taux zéro émis depuis 2022",
     "motif": "la base ouverte de la SGFGAS s'arrête aux prêts émis en 2021 (édition d'avril 2022) ; les statistiques "
              "plus récentes ne sont pas publiées en données ouvertes"},
    {"source": "Ressources du Fonds national d'aide au logement (FNAL) par financeur",
     "motif": "publiées dans les documents budgétaires (PDF) du programme 109, sans jeu ouvert ; non reprises"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Les producteurs publient déjà les agrégats nécessaires pour les aides personnelles au logement "
                  "(CNAF), le nombre de dossiers MaPrimeRénov' par département (DITP), les montants nationaux "
                  "(SDES, Sénat) et les prêts à taux zéro (SGFGAS) : ils sont repris tels quels ou agrégés. Aucun dépôt "
                  "public ne relie ces séries entre elles ni aux vues budgétaires : module écrit pour le dépôt, sur le "
                  "modèle de pipeline/prestations.py et pipeline/retraites.py.",
    "trouvailles": [
        {"nom": "CNAF, API data.caf.fr, jeux « AL - Répartition des allocataires » (type de logement, type de parc, "
                "départemental et national)", "url": f"{CAF}/explore/?q=al_s_type", "licence": LO,
         "mise_a_jour": "2026-09-28", "verdict": "réutilisable tel quel"},
        {"nom": "CNAF, s_ben_dep (toutes prestations par département)", "url": f"{CAF}/explore/dataset/s_ben_dep/",
         "licence": LO, "mise_a_jour": "2026-09-28",
         "verdict": "réutilisable tel quel (déjà lu par prestations ; mêmes valeurs que les jeux AL, vérifié)"},
        {"nom": "DITP-pilotage/barometre-resultats (données du baromètre des résultats de l'action publique)",
         "url": "https://github.com/DITP-pilotage/barometre-resultats",
         "licence": "Licence Ouverte 2.0 (jeu data.gouv.fr ; dépôt sans fichier de licence)",
         "dernier_commit": "2026-08-22", "verdict": "réutilisable tel quel"},
        {"nom": "etalab/barometre-resultats-donnees", "url": "https://github.com/etalab/barometre-resultats-donnees",
         "licence": "NOASSERTION", "dernier_commit": "2023-01-19",
         "verdict": "inspiration seulement (ancienne édition, remplacée par le dépôt de la DITP)"},
        {"nom": "SDES, Les rénovations énergétiques par geste aidées par MaPrimeRénov' en 2024",
         "url": SOURCES["sdes_maprimerenov"]["page"], "licence": "licence ouverte (décret n° 2017-638)",
         "mise_a_jour": "2026-07-24", "verdict": "réutilisable tel quel (national seulement)"},
        {"nom": "Anah, jeux publiés sur data.gouv.fr (opérations programmées, délégations locales, copropriétés, PPOM)",
         "url": "https://www.data.gouv.fr/fr/organizations/62da6837cde1491f3727cdb2/", "licence": LO,
         "mise_a_jour": "2026-11-18", "verdict": "inspiration seulement (aucun montant MaPrimeRénov' par territoire)"},
        {"nom": "Base de données PTZ (prêts à taux zéro) et base éco-PTZ (data.gouv.fr)",
         "url": SOURCES["sgfgas_ptz"]["page"], "licence": "Licence Ouverte 1.0", "mise_a_jour": "2022-04-12",
         "verdict": "à adapter (microdonnées agrégées par département et par année)"},
        {"nom": "Caisse des dépôts, plans de financement des logements sociaux par département (2016-2018)",
         "url": "https://opendata.caissedesdepots.fr/explore/dataset/logementsociaux_plans_de_fi_dep/",
         "licence": LO, "mise_a_jour": "2021-02-24",
         "verdict": "inspiration seulement (parts en pourcentage, sans montant)"},
        {"nom": "France Relance, données agrégées (data.economie.gouv.fr)",
         "url": "https://data.economie.gouv.fr/explore/dataset/france-relance-donnees-agregees/", "licence": LO,
         "mise_a_jour": "2021-09-06", "verdict": "inspiration seulement (arrêté en 2021)"},
        {"nom": "rouages-de-la-france/rouages.fr (foyers CAF par commune)",
         "url": "https://github.com/rouages-de-la-france/rouages.fr", "licence": "AGPL-3.0",
         "dernier_commit": "2026-11-16", "verdict": "inspiration seulement (communes, foyers seulement, TypeScript)"},
        {"nom": "Recherches GitHub « maprimerenov », « opendataptz », « pret a taux zero », « aides personnelles "
                "logement », « al_s_type_log_dep »", "url": "https://github.com/search", "licence": None,
         "dernier_commit": None,
         "verdict": "aucun autre dépôt pertinent (simulateurs d'éligibilité MaPrimeRénov', hors objet)"},
    ],
}

# --- Aides personnelles au logement ----------------------------------------------------------------------------------

AIDES = {"ensemble": "ndural", "apl": "apl", "alf": "alf", "als": "als"}   # suffixe des colonnes CNAF
NOMS_AIDES = {"ensemble": "Aides personnelles au logement (APL, ALF, ALS)",
              "apl": "Aide personnalisée au logement (APL)",
              "alf": "Allocation de logement familiale (ALF)",
              "als": "Allocation de logement sociale (ALS)"}
TYPES_LOGEMENT = {"Location": "location", "Accession": "accession", "Foyers": "foyer", "Inconnu": "inconnu"}
NOMS_TYPES_LOGEMENT = {"location": "Location", "accession": "Accession à la propriété",
                       "foyer": "Logement-foyer (résidence collective)", "inconnu": "Type de logement inconnu"}
TYPES_PARC = {"Parc public": "public", "Parc privé": "prive"}
NOMS_TYPES_PARC = {"public": "Parc public", "prive": "Parc privé"}
HORS_DEPARTEMENTS = {"978": "Saint-Martin", "99": "Code 99 de la CNAF (résidence à l'étranger ou inconnue)",
                     "XX": "Code XX de la CNAF (résidence inconnue)"}
COLONNES = ["foyers_decembre", "montant_annuel_eur", "montant_moyen_eur"]
DEFINITIONS_AIDES = {
    "foyers_decembre": "foyers allocataires des CAF payés au titre de décembre",
    "montant_annuel_eur": "somme des montants versés chaque mois de l'année par les CAF ; null si un mois manque à la "
                          "source",
    "montant_moyen_eur": "montant annuel / somme des foyers payés chaque mois : montant mensuel moyen par foyer",
    "ensemble": "colonne NDURAL de la CNAF (aides au logement) : un foyer perçoit au plus une des trois aides",
    "type_logement": "type de logement déclaré par l'allocataire (location, accession à la propriété, logement-foyer)",
    "type_parc": "parc public (logements des organismes de logement social) ou parc privé",
}

# --- MaPrimeRénov' ---------------------------------------------------------------------------------------------------

DITP_INDICATEUR = "IND-292"
DITP_DEFINITION = "Nombre de dossiers MaPrimeRénov’ validés en cumul"
DITP_NOM = "Nombre de logements bénéficiaires de MaPrimeRénov’"
SDES_TABLEAU1 = {"Dépôts": "depots", "Engagés": "engages", "Demandes de solde": "demandes_de_solde",
                 "Soldés": "soldes"}
SDES_TABLEAU5 = {"Nombre dossiers (en milliers)": ("nombre_dossiers", 1000),
                 "Montant travaux (en Md€)": ("montant_travaux_eur", 1e9),
                 "Subvention MaPrimeRénov' (en Md€)": ("subvention_maprimerenov_eur", 1e9),
                 "Montant moyen MaPrimeRénov' par dossier (en €)": ("montant_moyen_maprimerenov_eur", 1)}
SDES_CHAMPS = {"Tableau1": "Champ : France hors DROM. Hors rénovations d'ampleur.",
               "Tableau 5": "Champ : dossiers soldés hors rénovations d'ampleur, France hors DROM."}
SENAT_TITRE = "Exécution des crédits de MaPrimeRénov' en CP entre 2022 et 2024"
SENAT_SOURCE = "Source : commission des finances, d'après les données de la Cour des comptes"
SENAT_LIGNES = {"MaPrimeRénov' (programme 174)": "174", "MaPrimeRénov' (programme 362)": "362",
                "MaPrimeRénov' (programme 135)": "135", "Total": "total"}
SENAT_COLONNES = {"2022 Exécution": "execution_2022", "2023 Prévisions": "prevision_2023",
                  "2023 Exécution": "execution_2023", "2024 Prévisions": "prevision_2024",
                  "2024 Exécution": "execution_2024"}

# --- PTZ ---------------------------------------------------------------------------------------------------------------

SEUIL_SECRET = 5       # en dessous de 5 prêts dans une cellule département x année, le montant n'est pas publié
AUTRES_CODES_PRETS = {"20": "Corse (code 20 de la source, de 1995 à 2005, sans distinction entre Corse-du-Sud et "
                            "Haute-Corse)",
                      "978": "Saint-Martin"}
TYPES_PTZ = {"0": "ancien", "1": "neuf"}
TYPES_ECOPTZ = {"1": "Action seule ou bouquet d'actions", "2": "Obtention d'une performance globale minimale",
                "3": "Réhabilitation de système d'assainissement non collectif",
                "4": "Éco-PTZ complémentaire à un éco-PTZ individuel", "5": "Habiter Mieux"}
MESURES_PTZ = {"ptz": "210313", "eco_ptz": "210321"}

# --- Renvois -------------------------------------------------------------------------------------------------------

PROGRAMMES = {
    "109": "aides personnelles au logement (action 01) : crédits de l'État destinés à leur financement",
    "135": "aides à la pierre (action 01), accession à la propriété, habitat indigne, MaPrimeRénov' parcours "
           "« performance » depuis 2024 (d'après le rapport du Sénat repris dans maprimerenov.json)",
    "177": "hébergement et logement adapté des personnes sans domicile",
    "174": "MaPrimeRénov' parcours « efficacité » (rénovation par geste), d'après le rapport du Sénat repris dans "
           "maprimerenov.json",
}
OPERATEURS = ["anah", "fnap", "cglls", "ancols"]
PROGRAMMES_DEPENSES_FISCALES = {"109", "135", "177"}   # 174 : dépenses fiscales de l'énergie, hors logement


# --- Outils --------------------------------------------------------------------------------------------------------------

def chemin(cle: str) -> Path:
    return LAKE / SOURCES[cle]["fichier"]


def _duck():
    import duckdb
    return duckdb.connect()


def _charger(rel: str):
    p = SITE / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", html.unescape(s or "")).replace("’", "'")).strip()


def _r(v):
    return None if v is None else int(round(v))


def _ecart(objet: str, annee: int, source: str, montant, autre_source: str, autre_montant, lecture: str,
           unite: str = "euros") -> dict | None:
    if montant is None or autre_montant is None:
        return None
    return {"objet": objet, "annee": annee, "unite": unite, "source": source, "montant": _r(montant),
            "autre_source": autre_source, "autre_montant": _r(autre_montant), "ecart": _r(montant - autre_montant),
            "ecart_pct": round((montant - autre_montant) / autre_montant * 100, 1) if autre_montant else None,
            "lecture_ecart": lecture}


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def noms_departements() -> dict[str, str]:
    """Code -> nom des départements d'après site/data/local/geo (code officiel géographique)."""
    geo = SITE / "local" / "geo"
    fichiers = sorted(geo.glob("*.json"))
    if not fichiers:
        raise SystemExit("site/data/local/geo absent : lancer pipeline/local.py d'abord")
    out = {}
    for f in fichiers:
        d = json.loads(f.read_text(encoding="utf-8"))["departement"]
        out[str(d["code"])] = d["nom"]
    return out


# --- Lecture : CNAF ---------------------------------------------------------------------------------------------------

def lire_caf(cle: str, colonne: str, libelles: dict[str, str], par_departement: bool) -> dict:
    """{(geo, annee): {categorie: {aide: acc}}} ; acc = mois présents, montant, foyers sommés, valeurs de décembre.
    Les lignes multiples d'un même code et d'un même mois (décembre 2020 à 2022 à la source) sont additionnées."""
    p = chemin(cle)
    if not p.exists():
        raise SystemExit(f"data/lake/logement/{p.name} absent : lancer `python pipeline/logement.py collecter`")
    con = _duck()
    cats = {r[0] for r in con.execute(f"select distinct {colonne} from read_parquet('{p}')").fetchall()}
    if cats - set(libelles):
        raise SystemExit(f"{p.name} : catégories inconnues {sorted(cats - set(libelles))} (le jeu a changé de forme)")
    cols = ", ".join(f"sum(indfoy_{c})::double as f_{a}, sum(indmtt_{c})::double as m_{a}" for a, c in AIDES.items())
    geo = "numdep" if par_departement else "'FR'"
    rows = con.execute(f"select {geo} as geo, year(dtreffre) as an, month(dtreffre) as mois, {colonne} as cat, "
                       f"{cols} from read_parquet('{p}') group by all order by all").fetchall()
    out: dict = {}
    for r in rows:
        g, an, mois, cat = str(r[0]), int(r[1]), int(r[2]), libelles[r[3]]
        vals = r[4:]
        for i, aide in enumerate(AIDES):
            f, m = vals[2 * i], vals[2 * i + 1]
            for c in (cat, "_tous"):
                acc = out.setdefault((g, an), {}).setdefault(c, {}).setdefault(
                    aide, {"mois": {}, "montant": 0.0, "foyers": 0.0})
                acc["mois"][mois] = acc["mois"].get(mois, 0.0) + (f or 0.0)
                acc["montant"] += m or 0.0
                acc["foyers"] += f or 0.0
                if mois == 12:
                    acc["montant_dec"] = acc.get("montant_dec", 0.0) + (m or 0.0)
    return out


def triplet(acc: dict | None) -> list:
    """[foyers de décembre, montant annuel, montant mensuel moyen] ; null si absent ou année incomplète."""
    if not acc or 12 not in acc["mois"]:
        return [None, None, None]
    foyers_dec = int(round(acc["mois"][12]))
    if len(acc["mois"]) < 12:
        return [foyers_dec, None, None]
    moyen = round(acc["montant"] / acc["foyers"], 2) if acc["foyers"] else None
    return [foyers_dec, int(round(acc["montant"])), moyen]


def annees_completes(nat: dict) -> list[int]:
    return sorted(an for (g, an), cats in nat.items()
                  if len(cats["_tous"]["ensemble"]["mois"]) == 12)


def mois_absents(dep: dict, annees: list[int]) -> dict[str, list[str]]:
    """Codes et mois absents de la source pour les années publiées (« AAAA-MM »)."""
    out: dict[str, list[str]] = {}
    for (g, an), cats in dep.items():
        if an not in annees:
            continue
        mois = cats["_tous"]["ensemble"]["mois"]
        manque = [f"{an}-{m:02d}" for m in range(1, 13) if m not in mois]
        if manque:
            out.setdefault(g, []).extend(manque)
    return {g: sorted(v) for g, v in sorted(out.items())}


# --- Lecture : MaPrimeRénov' -----------------------------------------------------------------------------------------

def lire_ditp() -> dict:
    """{'definition', 'nom', 'dates', 'departements': {code: {date: valeur}}, 'france': {date: valeur}}."""
    p, pm = LAKE / SOURCES["ditp_barometre"]["fichier"], LAKE / SOURCES["ditp_barometre"]["fichier_meta"]
    if not p.exists() or not pm.exists():
        raise SystemExit("data/lake/logement/logement_ditp_barometre absent : lancer `python pipeline/logement.py "
                         "collecter`")
    meta = {r["indic_id"]: r for r in csv.DictReader(io.StringIO(pm.read_text(encoding="utf-8-sig")))}
    m = meta.get(DITP_INDICATEUR) or {}
    if _norm(m.get("indic_descr_baro")) != _norm(DITP_DEFINITION) or _norm(m.get("indic_nom_baro")) != _norm(DITP_NOM):
        raise SystemExit(f"baromètre : la définition publiée de {DITP_INDICATEUR} a changé ({m.get('indic_descr_baro')})")
    if m.get("indic_categorie_evolution") != "cumul_non_annuel":
        raise SystemExit(f"baromètre : {DITP_INDICATEUR} n'est plus publié en cumul")
    deps: dict[str, dict[str, float]] = {}
    france: dict[str, float] = {}
    for r in csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig"))):
        if r["indic_id"] != DITP_INDICATEUR:
            continue
        date = r["metric_enforce_date"]
        val = r["indic_va"] or (r["indic_vi"] if date.endswith("-12-01") else "")
        if not val:
            continue
        v = float(val)
        if r["maille"] == "DEPT":
            code = r["enforce_zone_id"][1:]
            deps.setdefault(code, {})[date] = v
        elif r["maille"] == "NAT":
            france[date] = v
    if not deps or not france:
        raise SystemExit("baromètre : aucune valeur départementale ou nationale lue")
    return {"definition": m["indic_descr_baro"], "nom": m["indic_nom_baro"], "departements": deps, "france": france}


def _feuille(chemin_xlsx: Path, nom: str) -> list[tuple]:
    import warnings

    import openpyxl
    with warnings.catch_warnings():   # en-têtes et pieds de page d'impression illisibles : sans effet sur les cellules
        warnings.simplefilter("ignore", UserWarning)
        wb = openpyxl.load_workbook(chemin_xlsx, read_only=True, data_only=True)
        try:
            return [tuple(r) for r in wb[nom].iter_rows(values_only=True)]
        finally:
            wb.close()


def lire_sdes() -> dict:
    """Tableaux 1 (dossiers par étape, milliers) et 5 (dossiers soldés : montants) du classeur du SDES."""
    p = chemin("sdes_maprimerenov")
    if not p.exists():
        raise SystemExit(f"data/lake/logement/{p.name} absent : lancer `python pipeline/logement.py collecter`")
    out = {}
    for feuille, libelles in (("Tableau1", SDES_TABLEAU1), ("Tableau 5", SDES_TABLEAU5)):
        lignes = _feuille(p, feuille)
        textes = [_norm(str(c)) for r in lignes for c in r if isinstance(c, str)]
        if _norm(SDES_CHAMPS[feuille]) not in textes:
            raise SystemExit(f"SDES, {feuille} : le champ publié a changé")
        entete = next(r for r in lignes if r and any(str(c) == "2020" for c in r if c is not None))
        annees = [int(str(c)) for c in entete if c is not None and re.fullmatch(r"20\d\d", str(c))]
        cols = [i for i, c in enumerate(entete) if c is not None and re.fullmatch(r"20\d\d", str(c))]
        valeurs = {}
        for r in lignes:
            lib = _norm(str(r[0])) if r and isinstance(r[0], str) else None
            for cle_src, cible in libelles.items():
                if lib == _norm(cle_src):
                    nom, mult = cible if isinstance(cible, tuple) else (cible, 1000)
                    valeurs[nom] = [None if r[i] is None else round(float(r[i]) * mult) for i in cols]
        manque = [v if not isinstance(v, tuple) else v[0] for v in libelles.values()
                  if (v if not isinstance(v, tuple) else v[0]) not in valeurs]
        if manque:
            raise SystemExit(f"SDES, {feuille} : lignes introuvables {manque} (le classeur a changé de forme)")
        out[feuille] = {"annees": annees, "valeurs": valeurs, "champ": SDES_CHAMPS[feuille]}
    return out


def lire_senat() -> dict:
    """Tableau « Exécution des crédits de MaPrimeRénov' en CP entre 2022 et 2024 » (M€), relu cellule par cellule."""
    p = chemin("senat_rlrg2024")
    if not p.exists():
        raise SystemExit(f"data/lake/logement/{p.name} absent : lancer `python pipeline/logement.py collecter`")
    s = re.sub(r"\s+", " ", html.unescape(p.read_text(encoding="utf-8", errors="replace"))).replace("’", "'")
    i = s.find(SENAT_TITRE)
    if i < 0:
        raise SystemExit("Sénat : le titre du tableau d'exécution de MaPrimeRénov' est introuvable")
    a = s.find("<table", i)
    b = s.find("</table>", a)
    if a < 0 or b < 0:
        raise SystemExit("Sénat : tableau d'exécution de MaPrimeRénov' introuvable")
    texte_apres = _norm(re.sub(r"<[^>]+>", " ", s[b:b + 600]))
    if not texte_apres.startswith(_norm(SENAT_SOURCE)):
        raise SystemExit("Sénat : la mention de source du tableau a changé")
    lignes = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", s[a:b], re.S):
        lignes.append([_norm(re.sub(r"<[^>]+>", " ", c)) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)])
    entete = lignes[0]
    idx = {}
    for j, c in enumerate(entete):
        if c in SENAT_COLONNES:
            idx[SENAT_COLONNES[c]] = j
    if set(idx) != set(SENAT_COLONNES.values()):
        raise SystemExit(f"Sénat : colonnes du tableau changées ({entete})")
    out = {}
    for ligne in lignes[1:]:
        cle = SENAT_LIGNES.get(_norm(ligne[0]).replace("’", "'"))
        if not cle:
            continue
        out[cle] = {nom: int(ligne[j].replace(" ", "").replace(" ", "")) for nom, j in idx.items()}
    if set(out) != set(SENAT_LIGNES.values()):
        raise SystemExit(f"Sénat : lignes du tableau changées ({sorted(out)})")
    return out


def controle_total_senat(senat: dict) -> list[dict]:
    """Somme des programmes contre total publié, colonne par colonne : un écart est publié, jamais corrigé."""
    out = []
    for col in SENAT_COLONNES.values():
        somme = sum(senat[p][col] for p in ("174", "362", "135"))
        out.append({"colonne": col, "somme_des_programmes": somme, "total_publie": senat["total"][col],
                    "ecart": somme - senat["total"][col]})
    return out


# --- Lecture : PTZ et éco-PTZ ------------------------------------------------------------------------------------------

def fichier_ptz() -> Path:
    """Copie compressée par ce module, sinon fichier brut déposé par collecte/collecte.py --lourd."""
    gz = chemin("sgfgas_ptz")
    if gz.exists():
        return gz
    brut = LAKE / "logement_sgfgas_ptz.csv"
    if brut.exists():
        return brut
    raise SystemExit("data/lake/logement/ptz/logement_sgfgas_ptz.csv.gz absent : lancer `python pipeline/logement.py "
                     "collecter`")


def code_departement(v) -> str | None:
    s = str(v or "").strip().upper()
    if not s:
        return None
    if s.isdigit() and len(s) == 1:
        s = "0" + s
    return s


def lire_prets(p: Path, colonnes: dict[str, str]) -> list[tuple]:
    """Agrégats (an, type, dept, nombre, somme des colonnes demandées) d'une base SGFGAS, lue en flux par DuckDB.
    Seules les colonnes année, type, département et montants sont lues (jamais commune, revenu ni prix)."""
    con = _duck()
    sommes = ", ".join(f"sum(try_cast({c} as double)) as {nom}" for nom, c in colonnes.items())
    # Les noms de régions sont encodés en Windows-1252 à la source : seules les colonnes numériques et le département
    # sont lues, en texte brut (« all_varchar »), ce qui évite tout décodage des colonnes non utilisées.
    req = (f"select try_cast(an as integer) as an, cast(type as varchar) as type, cast(dept as varchar) as dept, "
           f"count(*) as n, {sommes} from read_csv('{p}', header=true, all_varchar=true, delim=',', quote='\"', "
           f"encoding='latin-1') group by all order by all")
    return con.execute(req).fetchall()


def agreger_prets(lignes: list[tuple], noms: list[str], types: dict[str, str], annees: list[int],
                  departements: dict[str, str]) -> dict:
    """France (total et par type), départements, autres territoires, prêts sans département (secret statistique de la
    source). Un code de département ou de type inconnu arrête la production (le jeu a changé de forme)."""
    def vide() -> dict:   # None = aucune ligne de la source sous ce code cette année-là (publié null, jamais 0)
        return {"nombre": [None] * len(annees), **{n: [None] * len(annees) for n in noms}}

    france, sans_dep = vide(), vide()
    par_type: dict[str, dict] = {}
    deps: dict[str, dict] = {}
    autres: dict[str, dict] = {}
    for an, typ, dept, n, *sommes in lignes:
        if an not in annees:
            raise SystemExit(f"année inattendue dans la base SGFGAS : {an}")
        i = annees.index(an)
        t = types.get(str(typ).strip())
        if t is None:
            raise SystemExit(f"base SGFGAS : type de prêt inconnu « {typ} »")
        code = code_departement(dept)
        if code is None:
            cible = sans_dep
        elif code in departements:
            cible = deps.setdefault(code, vide())
        elif code in AUTRES_CODES_PRETS:
            cible = autres.setdefault(code, vide())
        else:
            raise SystemExit(f"base SGFGAS : code de département inconnu « {dept} »")
        for bloc in (france, par_type.setdefault(t, vide()), cible):
            bloc["nombre"][i] = (bloc["nombre"][i] or 0) + n
            for nom, v in zip(noms, sommes):
                bloc[nom][i] = (bloc[nom][i] or 0.0) + (v or 0.0)

    def arrondir(bloc: dict, masquer: bool) -> dict:
        """Montants arrondis à l'euro ; un département avec moins de SEUIL_SECRET prêts dans l'année : montant null."""
        out = {"nombre": bloc["nombre"]}
        for nom in noms:
            out[nom] = [None if v is None or (masquer and nb < SEUIL_SECRET) else int(round(v))
                        for v, nb in zip(bloc[nom], bloc["nombre"])]
        return out

    return {
        "france": arrondir(france, False),
        "par_type": {t: arrondir(v, False) for t, v in sorted(par_type.items())},
        "departements": {c: {"nom": departements[c], **arrondir(v, True)} for c, v in sorted(deps.items())},
        "autres_territoires": {c: {"nom": AUTRES_CODES_PRETS[c], **arrondir(v, True)} for c, v in sorted(autres.items())},
        "departement_non_renseigne": arrondir(sans_dep, False),
    }


# --- Liens vers les autres vues ----------------------------------------------------------------------------------------

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


def fichier_programme(numero: str) -> str | None:
    f = sorted((SITE / "arbre").glob(f"*_{numero}.json"))
    return f"arbre/{f[0].name}" if f else None


def mesures_par_programme() -> dict[str, list[str]]:
    doc = _charger("niches/mesures.json") or {}
    out: dict[str, list[str]] = {}
    for m in doc.get("mesures", []):
        code = (m.get("programme") or {}).get("code")
        if code:
            out.setdefault(str(code), []).append(m["id"])
    return {k: sorted(v) for k, v in out.items()}


def mesure(ident: str) -> dict | None:
    doc = _charger("niches/mesures.json") or {}
    return next((m for m in doc.get("mesures", []) if m.get("id") == ident), None)


def liens_programmes() -> list[dict]:
    mesures = mesures_par_programme()
    niches_prog = {str(p.get("programme")) for p in (_charger("niches/programmes.json") or {}).get("programmes", [])}
    out = []
    for code, role in PROGRAMMES.items():
        liens = []
        rel = fichier_programme(code)
        doc = _charger(rel) if rel else None
        if doc:
            liens.append({"vue": "arbre_etat", "fichier": rel, "id": doc["id"], "nom": doc["nom"], "md": doc["md"],
                          "millesime": doc.get("millesime"),
                          "actions": [{"id": e["id"], "nom": e["nom"], "md": e["md"]}
                                      for e in sorted(doc.get("enfants") or [], key=lambda e: e["id"])],
                          "lecture": "crédits de paiement du programme dans l'arbre du budget de l'État ; ne "
                                     "s'additionnent à aucun montant de cette vue"})
        if (SITE / "realisations" / f"{code}.json").exists():
            liens.append({"vue": "realisations", "fichier": f"realisations/{code}.json",
                          "lecture": "prévu et dépensé par année, indicateurs de performance du programme"})
        if code in niches_prog and code in PROGRAMMES_DEPENSES_FISCALES:
            liens.append({"vue": "depenses_fiscales_programmes", "fichier": "niches/programmes.json",
                          "programme": code,
                          "lecture": "dépense budgétaire et dépense fiscale (souvent appelée niche fiscale) rattachées "
                                     "au programme, publiées par la vue des dépenses fiscales"})
        if mesures.get(code) and code in PROGRAMMES_DEPENSES_FISCALES:
            liens.append({"vue": "depenses_fiscales_mesures", "fichier": "niches/mesures.json",
                          "mesures": mesures[code],
                          "lecture": "identifiants des dépenses fiscales rattachées au programme ; leurs montants ne "
                                     "sont pas recopiés ici"})
        out.append({"code": code, "role": role, "nom": doc["nom"] if doc else None, "liens": liens})
    return out


def liens_operateurs() -> list[dict]:
    doc = _charger("operateurs/operateurs.json") or {}
    par_id = {o["id"]: o for o in doc.get("operateurs", [])}
    return [{"vue": "operateurs", "fichier": "operateurs/operateurs.json", "id": i, "nom": par_id[i]["nom"],
             "programme_chef_de_file": par_id[i].get("programme_chef_de_file"),
             "lecture": "financements de l'État, taxes affectées et ressources propres de l'opérateur, publiés par la "
                        "vue des opérateurs"}
            for i in OPERATEURS if i in par_id]


def liens_renvois() -> list[dict]:
    out = []
    if _charger("prestations/index.json"):
        out.append({"vue": "prestations", "fichier": "prestations/nationales.json", "id": "aides_logement",
                    "lecture": "montants tous régimes (CAF et MSA) et comptes de la protection sociale des aides "
                               "personnelles au logement, par année ; non recopiés ici"})
    fiches = _charger("comparaison/fiches.json") or {}
    if any(f.get("id") == "logement" for f in fiches.get("fiches", [])):
        out.append({"vue": "comparaison", "fichier": "comparaison/fiches.json", "id": "logement",
                    "lecture": "dépenses publiques de logement en comparaison européenne (Eurostat, fonctions COFOG "
                               "GF0601 et GF1006)"})
    return out


# --- Production ----------------------------------------------------------------------------------------------------------

def _bloc(cats: dict | None) -> dict:
    return {aide: triplet((cats or {}).get(aide)) for aide in AIDES}


def _controle_somme(parties: list[list], tout: list) -> dict:
    """Écart maximal (valeur absolue) entre la somme des parties et l'ensemble, foyers et montant annuel."""
    out = {}
    for k, nom in ((0, "foyers"), (1, "montant_eur")):
        vals = [p[k] for p in parties]
        if tout[k] is None or any(v is None for v in vals):
            out[nom] = None
        else:
            out[nom] = int(round(sum(vals) - tout[k]))
    return out


def produire_aides(sortie: Path, noms: dict[str, str]) -> dict:
    log_dep = lire_caf("caf_type_logement_dep", "al_type_log", TYPES_LOGEMENT, True)
    log_nat = lire_caf("caf_type_logement_nat", "al_type_log", TYPES_LOGEMENT, False)
    parc_dep = lire_caf("caf_type_parc_dep", "al_type_parc", TYPES_PARC, True)
    parc_nat = lire_caf("caf_type_parc_nat", "al_type_parc", TYPES_PARC, False)
    annees = annees_completes(log_nat)
    if not annees or annees[0] > 2017:
        raise SystemExit(f"CNAF : années complètes inattendues {annees}")
    dernier = max((an, max(c["_tous"]["ensemble"]["mois"])) for (g, an), c in log_nat.items())
    absents = mois_absents(log_dep, annees)
    prest = _charger("prestations/index.json") or {}
    prest_fichiers = (prest.get("fichiers") or {}).get("departements") or {}
    codes = sorted({g for (g, an) in log_dep})
    inconnus = [c for c in codes if c not in noms and c not in HORS_DEPARTEMENTS]
    if inconnus:
        raise SystemExit(f"CNAF : codes de département inconnus {inconnus}")
    fichiers, serie_france, controles_annees = {}, {}, {}
    for an in annees:
        departements, hors = {}, {}
        ctl = {"aides_moins_ensemble": {"foyers": 0, "montant_eur": 0},
               "types_logement_moins_ensemble": {"foyers": 0, "montant_eur": 0},
               "types_parc_moins_ensemble": {"foyers": 0, "montant_eur": 0},
               "non_calculables": 0}

        def ligne(code: str) -> dict:
            cl, cp = log_dep.get((code, an), {}), parc_dep.get((code, an), {})
            aides = _bloc(cl.get("_tous"))
            d = {"aides": aides,
                 "type_logement": {t: _bloc(cl.get(t)) for t in NOMS_TYPES_LOGEMENT},
                 "type_parc": {t: _bloc(cp.get(t)) for t in NOMS_TYPES_PARC}}
            ens = aides["ensemble"]
            for nom_ctl, parties in (("aides_moins_ensemble", [aides[a] for a in ("apl", "alf", "als")]),
                                     ("types_logement_moins_ensemble",
                                      [d["type_logement"][t]["ensemble"] for t in NOMS_TYPES_LOGEMENT]),
                                     ("types_parc_moins_ensemble", [d["type_parc"][t]["ensemble"] for t in NOMS_TYPES_PARC])):
                e = _controle_somme(parties, ens)
                if e["foyers"] is None or e["montant_eur"] is None:
                    ctl["non_calculables"] += 1
                    continue
                for k in ("foyers", "montant_eur"):
                    if abs(e[k]) > abs(ctl[nom_ctl][k]):
                        ctl[nom_ctl][k] = e[k]
            return d

        for code in codes:
            if (code, an) not in log_dep:
                continue
            if code in noms:
                departements[code] = {"nom": noms[code], **ligne(code)}
            else:
                hors[code] = {"nom": HORS_DEPARTEMENTS[code], **ligne(code)}
        france = {"aides": _bloc(log_nat[("FR", an)]["_tous"]),
                  "type_logement": {t: _bloc(log_nat[("FR", an)].get(t)) for t in NOMS_TYPES_LOGEMENT},
                  "type_parc": {t: _bloc(parc_nat.get(("FR", an), {}).get(t)) for t in NOMS_TYPES_PARC}}
        # France (jeu national) contre somme des lignes départementales du même jeu (hors départements compris)
        somme = {}
        for aide in AIDES:
            f = [v["aides"][aide][0] for v in list(departements.values()) + list(hors.values())]
            m = [v["aides"][aide][1] for v in list(departements.values()) + list(hors.values())]
            somme[aide] = {"foyers_decembre": sum(x for x in f if x is not None),
                           "montant_annuel_eur": sum(x for x in m if x is not None),
                           "lignes_sans_valeur": sum(1 for x in m if x is None)}
        ctl["france_moins_somme_des_lignes"] = {
            aide: {"foyers_decembre": (france["aides"][aide][0] - somme[aide]["foyers_decembre"])
                   if france["aides"][aide][0] is not None else None,
                   "montant_annuel_eur": (france["aides"][aide][1] - somme[aide]["montant_annuel_eur"])
                   if france["aides"][aide][1] is not None else None,
                   "lignes_sans_montant_annuel": somme[aide]["lignes_sans_valeur"]}
            for aide in AIDES}
        controles_annees[str(an)] = ctl
        manquants = {g: [m for m in v if m.startswith(f"{an}-")] for g, v in absents.items()}
        manquants = {g: v for g, v in manquants.items() if v}
        doc = {
            "millesime": f"Année {an}",
            "source": "; ".join(SOURCES[k]["titre"] for k in ("caf_type_logement_dep", "caf_type_parc_dep",
                                                              "caf_type_logement_nat", "caf_type_parc_nat")),
            "urls_sources": [SOURCES[k]["page"] for k in ("caf_type_logement_dep", "caf_type_parc_dep",
                                                          "caf_type_logement_nat", "caf_type_parc_nat")],
            "unite": "foyers ; euros ; euros par foyer et par mois",
            "annee": an,
            "colonnes": COLONNES,
            "definitions": DEFINITIONS_AIDES,
            "aides": NOMS_AIDES,
            "types_logement": NOMS_TYPES_LOGEMENT,
            "types_parc": NOMS_TYPES_PARC,
            "departements": departements,
            "hors_departements": hors,
            "france": france,
            "mois_absents_a_la_source": manquants,
            "controles": ctl,
            "renvoi_total": ({"fichier": prest_fichiers[str(an)], "cle": "aides_logement",
                              "lecture": "le même ensemble (APL, ALF, ALS) par département, publié par la vue des "
                                         "prestations à partir d'un autre jeu de la même source (CNAF) : mêmes foyers, "
                                         "montants égaux à quelques euros près (arrondis de la source) ; à ne pas "
                                         "additionner"} if str(an) in prest_fichiers else None),
            "note_perimetre": "champ CAF (hors MSA) ; lignes multiples d'un même département et d'un même mois "
                              "additionnées (décembre 2020 à 2022 à la source) ; un mois absent à la source rend le "
                              "montant annuel null (Mayotte, Saint-Martin et code 99 : décembre 2020 à 2024) ; codes "
                              "hors département de la CNAF : 978 Saint-Martin, 99 et XX ; France : jeux nationaux de la "
                              "CNAF, comparés à la somme des lignes départementales dans `controles`",
        }
        rel = f"logement/aides_personnelles/{an}.json"
        dump(sortie / "aides_personnelles" / f"{an}.json", doc)
        fichiers[str(an)] = rel
        serie_france[str(an)] = {"aides": france["aides"],
                                 "type_parc": {t: france["type_parc"][t]["ensemble"] for t in NOMS_TYPES_PARC},
                                 "type_logement": {t: france["type_logement"][t]["ensemble"]
                                                   for t in NOMS_TYPES_LOGEMENT}}
    return {"annees": annees, "dernier_mois_publie": f"{dernier[0]}-{dernier[1]:02d}", "fichiers": fichiers,
            "france": serie_france, "controles": controles_annees, "mois_absents_a_la_source": absents}


def produire_maprimerenov(sortie: Path, noms: dict[str, str]) -> dict:
    ditp = lire_ditp()
    sdes = lire_sdes()
    senat = lire_senat()
    decembres = sorted(d for d in ditp["france"] if d.endswith("-12-01"))
    dernier = max(ditp["france"])
    dates = decembres + ([dernier] if dernier not in decembres else [])
    annees_calc = [int(d[:4]) for d in decembres[1:]]
    deps = {}
    for code in sorted(ditp["departements"]):
        if code not in noms:
            raise SystemExit(f"baromètre : département inconnu {code}")
        vals = ditp["departements"][code]
        cumul = [None if d not in vals else int(round(vals[d])) for d in dates]
        annee = [None if (a not in vals or b not in vals) else int(round(vals[b] - vals[a]))
                 for a, b in zip(decembres, decembres[1:])]
        deps[code] = {"nom": noms[code], "cumul": cumul, "annee": annee}
    france_cumul = [int(round(ditp["france"][d])) if d in ditp["france"] else None for d in dates]
    france_annee = [None if (a not in ditp["france"] or b not in ditp["france"])
                    else int(round(ditp["france"][b] - ditp["france"][a])) for a, b in zip(decembres, decembres[1:])]
    controle = []
    for i, d in enumerate(dates):
        s = [v["cumul"][i] for v in deps.values()]
        if None in s or france_cumul[i] is None:
            controle.append({"date": d, "somme_departements": None, "france": france_cumul[i], "ecart": None})
        else:
            controle.append({"date": d, "somme_departements": sum(s), "france": france_cumul[i],
                             "ecart": sum(s) - france_cumul[i]})
    t1, t5 = sdes["Tableau1"], sdes["Tableau 5"]
    liens_budget = []
    for code in ("174", "135", "362"):
        rel = fichier_programme(code)
        doc = _charger(rel) if rel else None
        if doc:
            liens_budget.append({"vue": "arbre_etat", "programme": code, "fichier": rel, "id": doc["id"],
                                 "nom": doc["nom"], "md": doc["md"], "millesime": doc.get("millesime"),
                                 "lecture": "crédits de tout le programme (MaPrimeRénov' en est une partie) ; ne "
                                            "s'additionnent pas aux montants de ce fichier"})
    doc = {
        "millesime": f"Dossiers validés en cumul de {dates[0][:7]} à {dernier[:7]} (baromètre) ; 2020 à 2024 (SDES) ; "
                     "exécution budgétaire 2022 à 2024 (Sénat)",
        "source": "; ".join(SOURCES[k]["titre"] for k in ("ditp_barometre", "sdes_maprimerenov", "senat_rlrg2024")),
        "urls_sources": [SOURCES[k]["page"] for k in ("ditp_barometre", "sdes_maprimerenov", "senat_rlrg2024")],
        "unite": "dossiers ; euros",
        "avertissement": "Trois producteurs, trois mesures différentes, jamais additionnées : le baromètre de la DITP "
                         "compte les dossiers validés depuis le lancement de MaPrimeRénov' (cumul), par département ; "
                         "le SDES publie au niveau national les dossiers et les montants des rénovations par geste "
                         "(France hors DROM, hors rénovations d'ampleur) ; le Sénat publie les crédits de paiement de "
                         "l'État consommés pour MaPrimeRénov', par programme. Les montants d'aide par département ne "
                         "sont pas publiés en données ouvertes.",
        "definitions": {
            "cumul": f"{ditp['definition']} (baromètre de la DITP, indicateur {DITP_INDICATEUR}) à chaque date de "
                     "`dates_cumul` ; la valeur de décembre 2022 est la valeur initiale publiée",
            "annee": "calculé par le site : différence entre les cumuls publiés de décembre de deux années successives "
                     "(dossiers validés dans l'année)",
            "depots_engages_soldes": "étapes de traitement des dossiers publiées par le SDES (en milliers, arrondis)",
            "subvention_maprimerenov_eur": "aides MaPrimeRénov' des dossiers soldés dans l'année (SDES)",
            "execution_cp": "crédits de paiement consommés dans l'année pour MaPrimeRénov', par programme budgétaire "
                            "(Sénat, d'après les données de la Cour des comptes)",
        },
        "dates_cumul": dates,
        "annees_calculees": annees_calc,
        "departements": deps,
        "france": {"cumul": france_cumul, "annee": france_annee},
        "controle_somme_departements": controle,
        "national_sdes": {
            "source": SOURCES["sdes_maprimerenov"]["page"],
            "champ": t1["champ"],
            "champ_montants": t5["champ"],
            "annees": t1["annees"],
            "etapes": t1["valeurs"],
            "soldes": {k: v for k, v in t5["valeurs"].items()},
            "annees_soldes": t5["annees"],
        },
        "budget_etat": {
            "source": SOURCES["senat_rlrg2024"]["page"],
            "tableau": SENAT_TITRE,
            "mention": SENAT_SOURCE,
            "unite": "millions d'euros (crédits de paiement)",
            "colonnes": list(SENAT_COLONNES.values()),
            "lignes": [{"programme": k, **v} for k, v in senat.items()],
            "controle_total": controle_total_senat(senat),
            "note": "valeurs reprises telles que publiées ; quand le total publié ne retombe pas sur la somme des "
                    "programmes, l'écart figure dans `controle_total` sans correction",
            "liens": liens_budget,
        },
        "limites": [
            "Le baromètre compte des dossiers, pas des montants ; un logement peut faire l'objet de plusieurs "
            "dossiers.",
            "Les montants du SDES portent sur les dossiers soldés de rénovation par geste, France hors DROM ; les "
            "rénovations d'ampleur font l'objet d'une publication distincte, non reprise ici.",
            "Les crédits budgétaires d'une année ne correspondent pas aux dossiers soldés la même année : paiements, "
            "avances et ressources propres de l'Anah suivent leurs propres calendriers.",
        ],
    }
    dump(sortie / "maprimerenov.json", doc)
    ecarts = []
    i_annee = {a: i for i, a in enumerate(t5["annees"])}
    sub = t5["valeurs"]["subvention_maprimerenov_eur"]
    for an in (2022, 2023, 2024):
        if an not in i_annee:
            continue
        e = _ecart("maprimerenov_montants", an, "sdes_subvention_dossiers_soldes", sub[i_annee[an]],
                   "senat_execution_cp_total", senat["total"][f"execution_{an}"] * 1e6,
                   "aides des dossiers soldés dans l'année, rénovation par geste, France hors DROM (SDES) contre crédits "
                   "de paiement de l'État consommés dans l'année pour MaPrimeRénov', tous programmes (Sénat) : "
                   "périmètres et calendriers différents ; l'Anah dispose aussi de ressources propres et de taxes "
                   "affectées (vue des opérateurs)")
        if e:
            ecarts.append(e)
    i1 = {a: i for i, a in enumerate(t1["annees"])}
    for k, an in enumerate(annees_calc):
        if an in i1 and france_annee[k] is not None:
            e = _ecart("maprimerenov_dossiers", an, "ditp_dossiers_valides_dans_l_annee", france_annee[k],
                       "sdes_dossiers_engages", t1["valeurs"]["engages"][i1[an]],
                       "dossiers validés dans l'année, France entière (calculé à partir des cumuls publiés par la "
                       "DITP) contre dossiers engagés de rénovation par geste, France hors DROM (SDES, milliers "
                       "arrondis) : définitions et champs différents publiés par chaque producteur", unite="dossiers")
            if e:
                ecarts.append(e)
    return {"fichier": "logement/maprimerenov.json", "dates_cumul": dates, "france_cumul": france_cumul,
            "france_annee": dict(zip([str(a) for a in annees_calc], france_annee)),
            "execution_cp_total_meur": {str(an): senat["total"][f"execution_{an}"] for an in (2022, 2023, 2024)},
            "ecarts": ecarts}


def produire_ptz(sortie: Path, noms: dict[str, str]) -> dict:
    lignes_ptz = lire_prets(fichier_ptz(), {"montant_ptz_eur": "vtpz", "montant_prets_operation_eur": "vtpr"})
    p_eco = chemin("sgfgas_ecoptz")
    if not p_eco.exists():
        raise SystemExit(f"data/lake/logement/{p_eco.name} absent : lancer `python pipeline/logement.py collecter`")
    lignes_eco = lire_prets(p_eco, {"montant_pret_eur": "mtpr", "montant_travaux_eur": "mttr"})
    if None in {l[0] for l in lignes_ptz} | {l[0] for l in lignes_eco}:
        raise SystemExit("base SGFGAS : année illisible")
    annees_ptz = sorted({l[0] for l in lignes_ptz})
    annees_eco = sorted({l[0] for l in lignes_eco})
    ptz = agreger_prets(lignes_ptz, ["montant_ptz_eur", "montant_prets_operation_eur"], TYPES_PTZ, annees_ptz, noms)
    eco = agreger_prets(lignes_eco, ["montant_pret_eur", "montant_travaux_eur"],
                        {k: f"type_{k}" for k in TYPES_ECOPTZ}, annees_eco, noms)
    for bloc in (ptz, eco):   # par territoire : nombre et montant du prêt (le total des opérations reste national)
        for d in list(bloc["departements"].values()) + list(bloc["autres_territoires"].values()):
            d.pop("montant_prets_operation_eur", None)
            d.pop("montant_travaux_eur", None)
    renvois = []
    for cle, ident in MESURES_PTZ.items():
        m = mesure(ident)
        if m:
            renvois.append({"vue": "depenses_fiscales_mesures", "fichier": "niches/mesures.json", "id": ident,
                            "libelle": m.get("libelle"), "pour": cle,
                            "lecture": "crédit d'impôt accordé aux établissements de crédit qui distribuent le prêt : "
                                       "c'est la dépense de l'État (dépense fiscale), publiée par la vue des dépenses "
                                       "fiscales ; elle ne s'additionne pas au montant des prêts"})
    doc = {
        "millesime": f"Prêts émis de {annees_ptz[0]} à {annees_ptz[-1]} (PTZ) et de {annees_eco[0]} à "
                     f"{annees_eco[-1]} (éco-PTZ), données arrêtées au 31/03/2022",
        "source": "; ".join(SOURCES[k]["titre"] for k in ("sgfgas_ptz", "sgfgas_ecoptz")),
        "urls_sources": [SOURCES[k]["page"] for k in ("sgfgas_ptz", "sgfgas_ecoptz")],
        "unite": "prêts ; euros",
        "avertissement": "Un prêt à taux zéro est un prêt, remboursé par le ménage : son montant n'est pas une dépense "
                         "de l'État. L'État prend en charge les intérêts sous la forme d'un crédit d'impôt accordé à "
                         "la banque, publié comme dépense fiscale (voir `renvois`).",
        "definitions": {
            "nombre": "nombre de prêts émis dans l'année (une ligne de la base par prêt)",
            "montant_ptz_eur": "somme des montants des prêts à taux zéro émis dans l'année",
            "montant_prets_operation_eur": "somme des montants de l'ensemble des prêts des opérations financées "
                                           "(prêt à taux zéro compris)",
            "montant_pret_eur": "somme des montants des éco-prêts à taux zéro émis dans l'année",
            "montant_travaux_eur": "somme des montants des travaux déclarés pour les éco-prêts",
            "departement_non_renseigne": "prêts dont la source ne donne pas le département (variable géographique "
                                         "vidée par la source pour le secret statistique, ou absente), comptés dans "
                                         "le total France",
            "autres_territoires": "codes de la source qui ne sont pas des départements actuels : 20 (Corse, de 1995 "
                                  "à 2005, avant la distinction entre 2A et 2B dans la base) et 978 (Saint-Martin)",
            "secret": f"montant d'un département et d'une année non publié (null) quand moins de {SEUIL_SECRET} prêts "
                      "y sont recensés ; le nombre reste publié",
            "null": "aucune ligne de la source sous ce code ou ce type cette année-là (par exemple Corse-du-Sud et "
                    "Haute-Corse avant 2005, codées 20 dans la base ; prêt à taux zéro dans l'ancien certaines années) ; "
                    "jamais remplacé par 0",
        },
        "annees_ptz": annees_ptz,
        "ptz": {"types": {k: v for k, v in sorted(TYPES_PTZ.items())}, **ptz},
        "annees_eco_ptz": annees_eco,
        "eco_ptz": {"types": {f"type_{k}": v for k, v in sorted(TYPES_ECOPTZ.items())}, **eco},
        "renvois": renvois,
        "limites": [
            "La base de la SGFGAS s'arrête aux prêts émis en 2021 : les années suivantes ne sont pas publiées en "
            "données ouvertes.",
            "Les montants sont ceux des offres de prêt déclarées par les établissements de crédit (euros courants).",
        ],
    }
    dump(sortie / "ptz.json", doc)
    i_ptz = {a: i for i, a in enumerate(annees_ptz)}
    i_eco = {a: i for i, a in enumerate(annees_eco)}
    return {"fichier": "logement/ptz.json",
            "dernier_annee_ptz": annees_ptz[-1],
            "ptz_derniere_annee": {"nombre": ptz["france"]["nombre"][i_ptz[annees_ptz[-1]]],
                                   "montant_ptz_eur": ptz["france"]["montant_ptz_eur"][i_ptz[annees_ptz[-1]]]},
            "eco_ptz_derniere_annee": {"nombre": eco["france"]["nombre"][i_eco[annees_eco[-1]]],
                                       "montant_pret_eur": eco["france"]["montant_pret_eur"][i_eco[annees_eco[-1]]]},
            "renvois": renvois}


def ecarts_aides(aides: dict) -> list[dict]:
    """Montants CAF (jeux nationaux, champ CAF) contre dépenses tous régimes de la CNAF (vue des prestations)."""
    nat = _charger("prestations/nationales.json") or {}
    detail = ((nat.get("prestations") or {}).get("aides_logement") or {})
    out = []
    for aide in ("apl", "alf", "als"):
        serie = ((detail.get("detail") or {}).get(aide) or {}).get("montant_eur") or {}
        for an, v in sorted(aides["france"].items()):
            e = _ecart(f"aides_personnelles_{aide}", int(an), "cnaf_montants_mensuels_champ_caf",
                       v["aides"][aide][1], "cnaf_depenses_tous_regimes", serie.get(an),
                       "somme des montants versés chaque mois par les CAF (champ CAF) contre dépenses annuelles tous "
                       "régimes de la CNAF (CAF et MSA, comptabilité de la CNAF, vue des prestations)")
            if e:
                out.append(e)
    return out


def produire(sortie: Path = SORTIE) -> dict:
    sortie = Path(sortie)
    noms = noms_departements()
    aides = produire_aides(sortie, noms)
    mpr = produire_maprimerenov(sortie, noms)
    ptz = produire_ptz(sortie, noms)
    ecarts = ecarts_aides(aides) + mpr.pop("ecarts")
    collecte = date_sources(DOMAINE)
    art_pierre = fichier_programme("135")
    doc135 = _charger(art_pierre) if art_pierre else None
    action01 = next((e for e in (doc135 or {}).get("enfants") or [] if e["id"].endswith("/135-01")), None)
    index = {
        "millesime": f"Aides personnelles au logement {aides['annees'][0]} à {aides['annees'][-1]} ; MaPrimeRénov' "
                     f"{mpr['dates_cumul'][0][:7]} à {mpr['dates_cumul'][-1][:7]} ; prêts à taux zéro "
                     f"jusqu'en {ptz['dernier_annee_ptz']}",
        "source": "CNAF (data.caf.fr), DITP (baromètre des résultats de l'action publique), SDES, Sénat, SGFGAS "
                  "(data.gouv.fr) ; liens vers le budget de l'État, les réalisations, les dépenses fiscales, les "
                  "prestations et les opérateurs",
        "urls_sources": sorted({s["page"] for s in SOURCES.values()}),
        "unite": "foyers, dossiers, prêts ; euros",
        "avertissement": "Les aides du logement passent par plusieurs canaux : prestations versées aux ménages (APL, "
                         "ALF, ALS), primes à la rénovation (MaPrimeRénov'), prêts à taux zéro (remboursés par les "
                         "ménages), subventions au logement social (aides à la pierre) et dépenses fiscales. Chaque "
                         "canal a sa source et son unité : les montants ne s'additionnent pas entre eux.",
        "fichiers": [
            {"fichier": rel, "contenu": f"aides personnelles au logement par département, année {an}"}
            for an, rel in sorted(aides["fichiers"].items())] + [
            {"fichier": "logement/maprimerenov.json", "contenu": "MaPrimeRénov' : dossiers validés par département, "
                                                                 "repères nationaux, exécution budgétaire"},
            {"fichier": "logement/ptz.json", "contenu": "prêts à taux zéro et éco-prêts à taux zéro par année et par "
                                                        "département"}],
        "aides_personnelles": {
            "annees": aides["annees"], "dernier_mois_publie": aides["dernier_mois_publie"],
            "fichiers": aides["fichiers"], "colonnes": COLONNES, "aides": NOMS_AIDES,
            "france": aides["france"], "controles": aides["controles"],
            "mois_absents_a_la_source": aides["mois_absents_a_la_source"],
        },
        "maprimerenov": mpr,
        "ptz": ptz,
        "aides_a_la_pierre": {
            "definition": "subventions publiques à la construction et à l'amélioration de logements sociaux : crédits "
                          "de l'action 01 « Construction locative et amélioration du parc » du programme 135 et "
                          "ressources du Fonds national des aides à la pierre (FNAP)",
            "liens": ([{"vue": "arbre_etat", "fichier": art_pierre, "id": action01["id"], "nom": action01["nom"],
                        "md": action01["md"], "millesime": doc135.get("millesime")}] if action01 else [])
                     + [l for l in liens_operateurs() if l["id"] == "fnap"],
            "non_publie": "logements sociaux financés et subventions par département : aucun jeu national ouvert (voir "
                          "`sources_inaccessibles`)",
        },
        "programmes": liens_programmes(),
        "operateurs": liens_operateurs(),
        "renvois": liens_renvois(),
        "ecarts": ecarts,
        "sources": {k: {kk: vv for kk, vv in s.items() if kk in ("id_catalogue", "titre", "producteur", "millesime",
                                                                 "licence", "url", "page", "verdict")}
                    for k, s in SOURCES.items()},
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "limites": [
            "Aides personnelles au logement : champ CAF (hors MSA) ; les dépenses tous régimes (CAF et MSA) sont "
            "publiées par la vue des prestations et comparées dans `ecarts`.",
            "MaPrimeRénov' : montants publiés au niveau national seulement ; par département, nombre de dossiers "
            "validés (cumul).",
            "Prêts à taux zéro : prêts émis jusqu'en 2021 (dernière édition ouverte de la base) ; un prêt n'est pas une "
            "dépense de l'État.",
            "Aides à la pierre : crédits budgétaires et comptes du FNAP seulement ; rien par département.",
        ],
        "regles": [
            "Deux sources ne sont jamais additionnées ; leurs écarts sont publiés dans `ecarts` avec leur lecture.",
            "Une valeur absente à la source est null, jamais 0 ; un mois absent rend le montant annuel null.",
            "Les montants déjà publiés par une autre vue (prestations, dépenses fiscales, budget de l'État, "
            "opérateurs) sont reliés par un lien, jamais recopiés pour être additionnés.",
        ],
        "confidentialite": "Agrégats publiés seulement : foyers allocataires, dossiers et prêts comptés par département "
                           "et par année ; aucune personne, aucun ménage ni aucune commune. Les bases de prêts de la "
                           "SGFGAS (une ligne par prêt, sans nom) sont lues pour l'année, le type, le département et "
                           f"les montants seulement ; un montant départemental de moins de {SEUIL_SECRET} prêts n'est "
                           "pas publié.",
        "collecte_le": collecte,
    }
    dump(sortie / "index.json", index)
    print(f"logement : {len(aides['fichiers'])} années d'aides personnelles, MaPrimeRénov' {len(mpr['dates_cumul'])} "
          f"dates, PTZ jusqu'en {ptz['dernier_annee_ptz']}, {len(ecarts)} écarts")
    return index


# --- Collecte --------------------------------------------------------------------------------------------------------

REFUS = (401, 403, 429, 451)


def _integrite():
    """collecte/integrite.py (contrôle d'intégrité des téléchargements), chargé par son chemin comme pipeline/fetch.py."""
    import importlib.util
    mod = sys.modules.get("integrite")
    if mod is None:
        spec = importlib.util.spec_from_file_location("integrite", ROOT / "collecte" / "integrite.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["integrite"] = mod
        spec.loader.exec_module(mod)
    return mod


def telecharger_compresse(url: str, dest: Path, octets_attendus: int | None = None, essais: int = 5) -> str:
    """Télécharge en flux et écrit une copie gzip (niveau 6, horodatage nul) + un fichier .json : URL, octets,
    empreinte sha256 du fichier publié, date. Un refus 401/403/429/451 est noté, jamais contourné."""
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    derniere = ""
    for i in range(essais):
        tmp = dest.with_name(dest.name + ".part")
        try:
            with requests.get(url, stream=True, timeout=(30, 300), headers={"User-Agent": UA}) as r:
                if r.status_code in REFUS:
                    return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
                r.raise_for_status()
                if "html" in (r.headers.get("Content-Type") or "").lower():
                    return "contenu inattendu (page HTML au lieu du fichier) : aucun contournement"
                h, n = hashlib.sha256(), 0
                with open(tmp, "wb") as brut, gzip.GzipFile(filename="", mode="wb", fileobj=brut, compresslevel=6,
                                                            mtime=0) as gz:
                    for bloc in r.iter_content(1 << 20):
                        gz.write(bloc)
                        h.update(bloc)
                        n += len(bloc)
            if octets_attendus and n != octets_attendus:
                raise IOError(f"transfert incomplet ({n} octets sur {octets_attendus})")
            # contrôle d'intégrité du temporaire (flux gzip complet, pas de page HTML) puis renommage atomique :
            # une version valide déjà présente n'est jamais remplacée par un fichier tronqué
            _integrite().remplacer_si_valide(tmp, dest, nom=dest.name)
            meta = {"url": url, "octets_source": n, "sha256_source": h.hexdigest(),
                    "collecte_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "compression": "gzip, niveau 6"}
            dest.with_suffix("").with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                                                                 encoding="utf-8")
            return "ok"
        except Exception as e:  # reprise réseau
            derniere = f"{type(e).__name__}: {e}"[:200]
            tmp.unlink(missing_ok=True)
            time.sleep(5 * (i + 1))
    return f"échec après {essais} essais : {derniere}"


def collecter(forcer: bool = False) -> dict:
    etat = {}
    cmd = [sys.executable, str(ROOT / "collecte" / "collecte.py"), *CATALOGUE_COLLECTE]
    if forcer:
        cmd.append("--force")
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    print(r.stdout[-3000:], end="")
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
    etat["catalogue"] = "ok" if r.returncode == 0 else f"code {r.returncode}"
    dest = chemin("sgfgas_ptz")
    if dest.exists() and dest.stat().st_size > 0 and not forcer:
        etat["sgfgas_ptz"] = "présent"
    else:
        etat["sgfgas_ptz"] = telecharger_compresse(SOURCES["sgfgas_ptz"]["url"], dest,
                                                   SOURCES["sgfgas_ptz"].get("octets_source"))
    print(f"sgfgas_ptz: {etat['sgfgas_ptz']}")
    return etat


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true", help="retélécharger les sources déjà présentes")
    ap.add_argument("--sortie", type=Path, default=SORTIE, help="dossier de sortie (défaut : site/data/logement)")
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter(a.forcer)
    if a.etape in ("produire", "tout"):
        produire(a.sortie)


if __name__ == "__main__":
    main()
