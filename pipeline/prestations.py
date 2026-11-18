"""Prestations versées aux ménages : montants, bénéficiaires et montant moyen par prestation, année et département.

Agrégats publiés seulement (aucune donnée individuelle). Chaque prestation est reliée à son financeur dans les arbres
déjà publiés (budget de l'État `arbre/`, Sécurité sociale `secu/`, départements `local/`) par des liens, jamais par des
montants additionnés : le site n'ajoute pas un lien à un total, ce qui exclut le double compte.

Entrées : entrepôt brut data/lake/secu/ (non versionné)
  tous collectés par `collecter` (noms de fichiers stables ; les quatre premiers aussi par collecte/collecte.py) :
    caf__dep_tr_nat.parquet          CNAF, dépenses par prestation, tous régimes (CAF et MSA), M€, 2013-2025
    caf__s_ben_nat.parquet           CNAF, foyers et montants mensuels par prestation, France, depuis 2016
    secu_protection_sociale.parquet  DREES, comptes de la protection sociale (base comptabilité nationale), M€
    datagouv__depenses-et-recettes-de-lassurance-chomage/*.csv   Unédic, dépenses de l'assurance chômage, M€
    secu_caf_s_ben_dep.parquet               CNAF, foyers et montants mensuels par prestation et département
    secu_drees_minima_nationales.xlsx        DREES, allocataires des minima sociaux au 31 décembre (France)
    secu_drees_minima_departementales.xlsx   DREES, allocataires des minima sociaux par département
    secu_drees_minima_depenses.xlsx          DREES, dépenses des minima sociaux (euros constants de la dernière année)
    secu_francetravail_indemnises.xlsx       France Travail, allocataires indemnisés par allocation, mensuel
Sorties :
  site/data/prestations/index.json                 prestations, financeurs et liens, totaux, écarts, sources
  site/data/prestations/nationales.json            séries annuelles : montant, bénéficiaires, montant moyen
  site/data/prestations/departements/<annee>.json  par département : foyers, montant annuel, montant mensuel moyen

Commandes :
  python pipeline/prestations.py collecter   # réseau : sources manquantes ; un refus 401/403/429 est noté, jamais contourné
  python pipeline/prestations.py produire    # sans réseau
  python pipeline/prestations.py             # les deux

Règles :
  - deux comptabilités ne sont jamais additionnées : comptes de la CNAF (dépenses comptables tous régimes), comptes de
    la protection sociale de la DREES (comptabilité nationale), comptes de l'Unédic ; chaque série garde sa source et
    les totaux sont calculés source par source ;
  - les écarts entre sources sont publiés tels quels (montant, différence, part), jamais lissés ;
  - une valeur masquée ou non disponible à la source reste telle quelle (chaîne de la source, ou null), jamais 0 ;
  - toute date écrite vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BRUT = ROOT / "data" / "lake" / "secu"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "prestations"
ANNEE_DEBUT = 2019
M = 1e6

# --- Sources ---------------------------------------------------------------------------------------------------------

DREES_API = "https://data.drees.solidarites-sante.gouv.fr/api/explore/v2.1/catalog/datasets"
DREES_336 = f"{DREES_API}/336_minima-sociaux-rsa-et-prime-d-activite/attachments"
SOURCES = {
    "cnaf_depenses": {
        "fichier": "caf__dep_tr_nat.parquet",
        "url": "https://data.caf.fr/api/explore/v2.1/catalog/datasets/dep_tr_nat/exports/parquet",
        "page": "https://data.caf.fr/explore/dataset/dep_tr_nat/",
        "titre": "CNAF, « Dépenses par prestation » (dep_tr_nat) : dépenses annuelles tous régimes (CAF et MSA) et CAF "
                 "seules, par prestation, en M€",
        "producteur": "CNAF", "millesime": "2013 à 2025", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (export parquet de l'API Opendatasoft)",
    },
    "cnaf_beneficiaires": {
        "fichier": "caf__s_ben_nat.parquet",
        "url": "https://data.caf.fr/api/explore/v2.1/catalog/datasets/s_ben_nat/exports/parquet",
        "page": "https://data.caf.fr/explore/dataset/s_ben_nat/",
        "titre": "CNAF, « Toutes prestations : répartition des allocataires selon la prestation » (s_ben_nat) : foyers, "
                 "personnes couvertes et montant versé chaque mois, France, champ CAF",
        "producteur": "CNAF", "millesime": "juin 2016 à mars 2026 (mensuel)", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft)",
    },
    "cnaf_departements": {
        "fichier": "secu_caf_s_ben_dep.parquet",
        "url": "https://data.caf.fr/api/explore/v2.1/catalog/datasets/s_ben_dep/exports/parquet",
        "page": "https://data.caf.fr/explore/dataset/s_ben_dep/",
        "titre": "CNAF, « Toutes prestations : répartition des allocataires selon la prestation [Départemental] » "
                 "(s_ben_dep) : foyers, personnes couvertes et montant versé chaque mois, par département, champ CAF",
        "producteur": "CNAF", "millesime": "juin 2016 à mars 2026 (mensuel)", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (export parquet de l'API Opendatasoft)",
    },
    "drees_cps": {
        "fichier": "secu_protection_sociale.parquet",
        "url": f"{DREES_API}/305_les-comptes-de-la-protection-sociale/exports/parquet",
        "page": "https://data.drees.solidarites-sante.gouv.fr/explore/dataset/305_les-comptes-de-la-protection-sociale/",
        "titre": "DREES, Comptes de la protection sociale : prestations par prestation et par régime (M€, base "
                 "comptabilité nationale ; détail par prestation à partir de 2020)",
        "producteur": "DREES", "millesime": "2020 à 2024", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (export parquet, même jeu que secu/cps)",
    },
    "drees_minima_nationales": {
        "fichier": "secu_drees_minima_nationales.xlsx",
        "url": f"{DREES_336}/minima_sociaux_donnees_nationales_par_dispositif_xlsx",
        "page": "https://data.drees.solidarites-sante.gouv.fr/explore/dataset/336_minima-sociaux-rsa-et-prime-d-activite/",
        "titre": "DREES, « Minima sociaux : données nationales par dispositif », tableau 2 : allocataires au 31 décembre, "
                 "France",
        "producteur": "DREES", "millesime": "1999 à 2024", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (classeur, lecture des lignes par libellé)",
    },
    "drees_minima_departementales": {
        "fichier": "secu_drees_minima_departementales.xlsx",
        "url": f"{DREES_336}/minima_sociaux_donnees_departementales_par_dispositif_xlsx",
        "page": "https://data.drees.solidarites-sante.gouv.fr/explore/dataset/336_minima-sociaux-rsa-et-prime-d-activite/",
        "titre": "DREES, « Minima sociaux : données départementales par dispositif », tableau 7 : allocataires de "
                 "l'ASV et de l'Aspa selon le département de résidence au 31 décembre",
        "producteur": "DREES", "millesime": "1996 à 2024", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (classeur)",
    },
    "drees_minima_depenses": {
        "fichier": "secu_drees_minima_depenses.xlsx",
        "url": f"{DREES_336}/minima_sociaux_donnees_de_depenses_par_dispositif_xlsx",
        "page": "https://data.drees.solidarites-sante.gouv.fr/explore/dataset/336_minima-sociaux-rsa-et-prime-d-activite/",
        "titre": "DREES, « Minima sociaux : données de dépenses par dispositif », tableau 1 : dépenses d'allocations "
                 "(M€ constants de la dernière année ; seule la dernière année, égale aux euros courants, est reprise)",
        "producteur": "DREES", "millesime": "2009 à 2024", "licence": "Licence Ouverte 2.0",
        "verdict": "à adapter (euros constants : comparaison limitée à la dernière année)",
    },
    "francetravail_indemnises": {
        "fichier": "secu_francetravail_indemnises.xlsx",
        "url": "https://statistiques.francetravail.org/indem/teleindemalloc",
        "page": "https://www.data.gouv.fr/fr/datasets/allocataires-de-lassurance-chomage/",
        "titre": "France Travail, « Allocataires indemnisés, données mensuelles » (fichier national des allocataires), "
                 "feuille « Brut France » : allocataires indemnisés au titre du dernier jour de chaque mois",
        "producteur": "France Travail", "millesime": "janvier 2006 à décembre 2025 (mensuel)",
        "licence": "Licence Ouverte 2.0 (fiche data.gouv.fr « fr-lo »)",
        "verdict": "réutilisable tel quel (classeur)",
    },
    "unedic": {
        "fichier": "datagouv__depenses-et-recettes-de-lassurance-chomage/financement-de-l-assurance-chomage_47a22bbe.csv",
        "url": "https://data.unedic.org/api/explore/v2.1/catalog/datasets/financement-de-l-assurance-chomage/exports/"
               "csv?use_labels=true",
        "page": "https://www.data.gouv.fr/fr/datasets/depenses-et-recettes-de-lassurance-chomage/",
        "titre": "Unédic, « Dépenses et recettes de l'assurance chômage », colonne « allocations brutes et aides » (M€)",
        "producteur": "Unédic", "millesime": "2011 à 2025", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft)",
    },
    "rsa_recentralise": {
        "url": "https://blog.landot-avocats.net/2022/04/11/recentralisation-du-rsa-mode-demploi/",
        "titre": "Financement du RSA par l'État dans six départements : Guyane et Mayotte (2019), La Réunion (2020), "
                 "Seine-Saint-Denis et Pyrénées-Orientales (2022), Ariège (1er décembre 2022)",
        "producteur": "lois de finances 2019, 2020 et 2022 ; CAF de l'Ariège",
        "pages": ["https://blog.landot-avocats.net/2018/12/31/recentralisation-du-rsa-a-mayotte-et-en-guyane/",
                  "https://www.banquedesterritoires.fr/letat-reprend-en-main-la-gestion-du-rsa-la-reunion",
                  "https://www.banquedesterritoires.fr/seine-saint-denis-jean-castex-acte-la-renationalisation-du-"
                  "financement-du-rsa-des-2022",
                  "https://www.banquedesterritoires.fr/apres-la-seine-saint-denis-le-rsa-renationalise-dans-les-"
                  "pyrenees-orientales",
                  "https://caf.fr/professionnels/offres-et-services/caf-de-l-ariege/partenaires-locaux/newsletter-avril-"
                  "2023/recentralisation-du-rsa"],
        "millesime": "2019 à 2022", "licence": "textes publics", "verdict": "réutilisable tel quel (dates seulement)",
    },
}
COLLECTABLES = ["cnaf_depenses", "cnaf_beneficiaires", "drees_cps", "unedic", "cnaf_departements", "drees_minima_nationales", "drees_minima_departementales",
                "drees_minima_depenses", "francetravail_indemnises"]

# Départements où l'État finance le RSA : (code, première année entière, mois de début si en cours d'année)
RSA_RECENTRALISE = {"973": (2019, None), "976": (2019, None), "974": (2020, None), "93": (2022, None),
                    "66": (2022, None), "09": (2023, "décembre 2022")}

INACCESSIBLES = [
    {"source": "France Travail, allocataires indemnisés de l'ARE par département",
     "motif": "le fichier mensuel publié (fiche data.gouv.fr « Séries brutes sur l'indemnisation par régions et "
              "départements ») ne contient que des séries régionales ; aucune série départementale n'est reprise"},
    {"source": "Montants de l'ARE, de l'Aspa, des pensions de retraite et des indemnités journalières par département",
     "motif": "aucun jeu ouvert départemental trouvé (CNAV, MSA, Unédic, Assurance maladie) ; seuls les effectifs "
              "de l'Aspa (DREES) sont publiés par département"},
    {"source": "Effectifs de retraités par régime et de bénéficiaires d'indemnités journalières",
     "motif": "non repris : les effectifs par régime comptent plusieurs fois une personne qui perçoit des pensions de "
              "plusieurs régimes, et aucun jeu ouvert annuel des bénéficiaires d'indemnités journalières n'a été "
              "trouvé ; montants seuls"},
    {"source": "Comptes de la protection sociale 2019 et 2025 par prestation",
     "motif": "le jeu DREES ne détaille les prestations qu'à partir de 2020 (2019 : grands risques seulement) et "
              "s'arrête à 2024"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "conclusion": "Les producteurs publient déjà les agrégats nécessaires (API Opendatasoft de la CNAF et de la DREES, "
                  "fichiers France Travail et Unédic) : ils sont repris tels quels. Aucun dépôt ne relie ces "
                  "prestations à leurs financeurs ni ne publie les écarts entre sources : module écrit pour le dépôt, "
                  "sur le modèle de pipeline/secu.py.",
    "trouvailles": [
        {"nom": "CNAF, API data.caf.fr (s_ben_dep, s_ben_nat, dep_tr_nat)", "url": "https://data.caf.fr/",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-09-28", "verdict": "réutilisable tel quel"},
        {"nom": "DREES, Minima sociaux, RSA et prime d'activité (336)",
         "url": SOURCES["drees_minima_nationales"]["page"], "licence": "Licence Ouverte 2.0",
         "mise_a_jour": "2025-12-04", "verdict": "réutilisable tel quel"},
        {"nom": "DREES, Comptes de la protection sociale (305)", "url": SOURCES["drees_cps"]["page"],
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "données 2024", "verdict": "réutilisable tel quel"},
        {"nom": "DREES, Données mensuelles sur les prestations de solidarité",
         "url": "https://data.drees.solidarites-sante.gouv.fr/explore/dataset/donnees-mensuelles-sur-les-prestations-"
                "de-solidarite/", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-09-02",
         "verdict": "à adapter (effectifs mensuels ; non repris, les effectifs CNAF couvrent le même champ)"},
        {"nom": "France Travail, Allocataires de l'assurance chômage (data.gouv.fr)",
         "url": SOURCES["francetravail_indemnises"]["page"], "licence": "Licence Ouverte 2.0",
         "mise_a_jour": "2026-10-13", "verdict": "réutilisable tel quel (national ; régional seulement)"},
        {"nom": "Unédic, Dépenses et recettes de l'assurance chômage", "url": SOURCES["unedic"]["page"],
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-09-01", "verdict": "réutilisable tel quel"},
        {"nom": "rouages-de-la-france/rouages.fr (scripts/caf-emettre.ts : foyers CAF par commune)",
         "url": "https://github.com/rouages-de-la-france/rouages.fr", "licence": "AGPL-3.0",
         "dernier_commit": "2026-11-16", "verdict": "inspiration seulement (communes, foyers seulement, TypeScript)"},
        {"nom": "tawiza/tawiza (collecteur data.caf.fr)", "url": "https://github.com/tawiza/tawiza",
         "licence": "MIT", "dernier_commit": "2026-08-03", "verdict": "inspiration seulement"},
        {"nom": "openfisca/openfisca-france-data", "url": "https://github.com/openfisca/openfisca-france-data",
         "licence": "AGPL-3.0", "dernier_commit": "2026-09-09",
         "verdict": "inspiration seulement (microsimulation sur données d'enquête, pas d'agrégats publiés)"},
        {"nom": "DNUM-SocialGouv/aides-jeunes", "url": "https://github.com/DNUM-SocialGouv/aides-jeunes",
         "licence": "AGPL-3.0", "dernier_commit": "2026-11-12",
         "verdict": "inspiration seulement (simulateur individuel, hors objet)"},
        {"nom": "Recherches GitHub « data.caf.fr », « minima sociaux drees », « allocataires caf departement », "
                "« comptes protection sociale drees »", "url": "https://github.com/search", "licence": None,
         "dernier_commit": None, "verdict": "aucun autre dépôt pertinent"},
    ],
}

# --- Prestations --------------------------------------------------------------------------------------------------
# caf : libellés de dep_tr_nat (colonne dep_ts_regimes, tous régimes) ; ben : suffixe des colonnes s_ben (CAF) ;
# cps : codes de prestation DREES (sommés, jamais imbriqués) ; principale : série de référence affichée.

APL, ALF, ALS = ("Aide personnalisée au logement (APL)", "Allocation logement familiale (ALF)",
                 "Allocation logement sociale (ALS)")
PRESTATIONS = [
    {"id": "allocations_familiales", "nom": "Allocations familiales", "groupe": "famille",
     "caf": ["Allocations familiales (AF)"], "ben": "af", "cps": ["E11-30.1.01"], "principale": "cnaf_depenses",
     "financeur": "Sécurité sociale, branche famille (CNAF ; MSA pour le régime agricole)"},
    {"id": "aides_logement", "nom": "Aides personnelles au logement (APL, ALF, ALS)", "groupe": "logement",
     "caf": [APL, ALF, ALS], "ben": "ndural", "cps": ["E11-50.1", "E11-50.2", "E11-50.3"],
     "principale": "cnaf_depenses", "financeur": "État, programme 109 « Aide à l'accès au logement »",
     "detail_caf": {"apl": APL, "alf": ALF, "als": ALS}},
    {"id": "rsa", "nom": "Revenu de solidarité active (RSA)", "groupe": "minima_sociaux",
     "caf": ["Revenu solidarité active (RSA versé yc prime, créances, indus)"], "ben": "rsa", "cps": ["E11-60.1.02"],
     "principale": "cnaf_depenses", "drees": "Revenu de solidarité active",
     "financeur": "Départements ; État dans les départements où le RSA est recentralisé (programme 304)"},
    {"id": "prime_activite", "nom": "Prime d'activité", "groupe": "soutien_activite",
     "caf": ["Prime d'activité"], "ben": "ppa", "cps": ["E11-60.2.01"], "principale": "cnaf_depenses",
     "financeur": "État, programme 304 « Inclusion sociale et protection des personnes »"},
    {"id": "aah", "nom": "Allocation aux adultes handicapés (AAH, avec ses compléments)", "groupe": "minima_sociaux",
     "caf": ["Allocation adultes handicapés (AAH + MVA + GRPH)"], "ben": "aah", "cps": ["E11-12.2.11"],
     "principale": "cnaf_depenses", "drees": "Allocation aux adultes handicapés",
     "financeur": "État, programme 157 « Handicap et dépendance »"},
    {"id": "aspa", "nom": "Minimum vieillesse (Aspa et ASV)", "groupe": "minima_sociaux",
     "cps": ["E11-21.2"], "principale": "drees_cps", "drees": "Allocation supplémentaire vieillesse",
     "financeur": "Fonds de solidarité vieillesse (FSV)"},
    {"id": "paje", "nom": "Prestation d'accueil du jeune enfant (PAJE)", "groupe": "famille",
     "caf": ["Total Prestation d'accueil du jeune enfant (PAJE)"], "ben": "ndurpaje",
     "cps": ["E11-30.1.06", "E11-30.1.07", "E11-30.1.08", "E11-30.3.03", "E11-30.3.04", "E11-30.3.05",
             "E11-30.3.08", "E11-30.6.05"], "principale": "cnaf_depenses",
     "financeur": "Sécurité sociale, branche famille (CNAF ; MSA pour le régime agricole)"},
    {"id": "ars", "nom": "Allocation de rentrée scolaire (ARS)", "groupe": "famille",
     "caf": ["Allocation de rentrée scolaire (ARS)"], "ben": "ars", "cps": ["E11-30.2.02"], "annuelle": True,
     "principale": "cnaf_depenses",
     "financeur": "Sécurité sociale, branche famille (CNAF ; MSA pour le régime agricole)"},
    {"id": "are", "nom": "Allocation d'aide au retour à l'emploi (ARE, y compris en formation)", "groupe": "chomage",
     "cps": ["E11-42.1.01", "E11-41.1.01"], "principale": "unedic",
     "financeur": "Assurance chômage (Unédic) ; France Travail verse l'allocation"},
    {"id": "pensions_retraite", "nom": "Pensions de retraite (droit direct et réversion), tous régimes",
     "groupe": "retraite", "cps": ["E11-21.1", "E11-22.1"], "principale": "drees_cps", "par_regime": True,
     "financeur": "Régimes de retraite de base, complémentaires et supplémentaires"},
    {"id": "indemnites_journalieres", "nom": "Indemnités journalières (maladie, accidents du travail, maternité "
                                             "et paternité)", "groupe": "sante",
     "cps": ["E11-11.1.01", "E11-11.1.11", "E11-30.6.01"], "principale": "drees_cps",
     "detail_cps": {"maladie": "E11-11.1.01", "at_mp": "E11-11.1.11", "maternite_paternite": "E11-30.6.01"},
     "financeur": "Assurance maladie (branches maladie et AT-MP, tous régimes)"},
]
PAR_ID = {p["id"]: p for p in PRESTATIONS}
DEPARTEMENTALES = ["allocations_familiales", "aides_logement", "rsa", "prime_activite", "aah", "paje", "ars"]

# Liens vers les arbres publiés (exécution 2024). `partage` : le nœud finance aussi d'autres prestations.
P304 = "Solidarite, travail et sante/Solidarité, insertion et égalité des chances/304/304-11"
LIENS = {
    "aides_logement": [
        ("arbre_etat", "arbre/Logement-et-territoires_Coh-sion-des-territoires_109.json",
         "Logement et territoires/Cohésion des territoires/109/109-01", [])],
    "prime_activite": [
        ("arbre_etat", "arbre/Solidarite-travail-et-sante_Solidarit-insertion-et-galit-des-chances_304.json", P304,
         ["rsa"])],
    "rsa": [
        ("arbre_etat", "arbre/Solidarite-travail-et-sante_Solidarit-insertion-et-galit-des-chances_304.json", P304,
         ["prime_activite"])],
    "aah": [
        ("arbre_etat", "arbre/Solidarite-travail-et-sante_Solidarit-insertion-et-galit-des-chances_157.json",
         "Solidarite, travail et sante/Solidarité, insertion et égalité des chances/157/157-12", [])],
    "aspa": [("secu_arbre", "secu/arbre/racine.json", "robss/fsv/minimum_vieillesse", [])],
    "are": [("secu_arbre", "secu/arbre/racine.json", "unedic/allocations", [])],
    "indemnites_journalieres": [
        ("secu_arbre", "secu/arbre/racine.json", "robss/maladie/ondam_soins_de_ville/indemnites_journalieres", [])],
    "pensions_retraite": [
        ("secu_arbre", "secu/arbre/racine.json", "robss/vieillesse/prestations_nettes", []),
        ("secu_arbre", "secu/arbre/racine.json", "complementaires/agirc_arrco", []),
        ("secu_arbre", "secu/arbre/racine.json", "complementaires/autres_regimes", [])],
    "allocations_familiales": [("secu_arbre", "secu/arbre/racine.json", "robss/famille", ["paje", "ars"])],
    "paje": [("secu_arbre", "secu/arbre/racine.json", "robss/famille", ["allocations_familiales", "ars"])],
    "ars": [("secu_arbre", "secu/arbre/racine.json", "robss/famille", ["allocations_familiales", "paje"])],
}
LECTURE_LIEN = {
    "arbre_etat": "crédits de paiement exécutés en 2024 (budget de l'État) : même argent que la prestation, vu du "
                  "côté du financeur ; ne s'ajoute pas au montant de la prestation",
    "secu_arbre": "dépenses 2024 de l'organisme (comptes des organismes de sécurité sociale) : même argent que la "
                  "prestation, vu du côté du financeur ; ne s'ajoute pas au montant de la prestation",
    "secu_cps": "prestation 2024 dans les comptes de la protection sociale (DREES), par régime qui la verse",
}
LECTURE_ECART = {
    ("cnaf_depenses", "drees_cps"): "champs et conventions comptables différents : dépenses comptables de la CNAF "
                                    "(CAF et MSA, indus et rappels compris) ; comptabilité nationale pour la DREES",
    ("unedic", "drees_cps"): "champs différents : l'Unédic compte toutes les allocations et aides de l'assurance "
                             "chômage ; la DREES isole l'ARE et l'ARE formation, tous régimes",
    ("drees_cps", "drees_minima_depenses"): "écart de champ publié par la DREES : prime de Noël, indus et rappels "
                                            "compris dans les dépenses des minima sociaux, pas dans les comptes de la "
                                            "protection sociale ; pour le minimum vieillesse, ASV de premier étage "
                                            "comprise dans les comptes de la protection sociale seulement",
    ("cnaf_depenses", "drees_minima_depenses"): "champs différents : dépenses comptables de la CNAF ; dépenses des "
                                                "minima sociaux de la DREES (tous organismes payeurs, prime de Noël "
                                                "comprise)",
    ("cnaf_depenses", "arbre_etat"): "le nœud du budget de l'État est la part financée par l'État ; il peut couvrir "
                                     "plusieurs prestations ou d'autres dépenses, et d'autres ressources peuvent "
                                     "financer la prestation",
    ("drees_cps", "secu_arbre"): "comptes des organismes (droits constatés, PLACSS) et comptabilité nationale "
                                 "(DREES) : champs différents",
    ("unedic", "secu_arbre"): "même source (Unédic) : le nœud de l'arbre Sécurité sociale reprend la même colonne",
    ("cnaf_beneficiaires", "drees_minima_nationales"): "foyers payés par les CAF en décembre (CNAF) ; allocataires "
                                                       "au 31 décembre tous organismes payeurs, MSA comprise (DREES)",
    ("cnaf_departements", "cnaf_depenses"): "somme des montants mensuels des CAF (CNAF, champ CAF) comparée aux "
                                            "dépenses annuelles tous régimes (CAF et MSA, indus et rappels compris)",
}

LECTURE_PAJE = ("la ligne PAJE des dépenses de la CNAF comprend les cotisations sociales prises en charge au titre du "
                "complément de libre choix du mode de garde (lignes « CMG ... Cotisations »), que les montants "
                "mensuels par allocataire ne comprennent pas en totalité ; écart non ventilé par la source")


# --- Lecture de l'entrepôt ----------------------------------------------------------------------------------------

def chemin(cle: str) -> Path:
    return BRUT / SOURCES[cle]["fichier"]


def _duck():
    import duckdb
    return duckdb.connect()


def lire_cnaf_depenses(annees: list[int]) -> dict[str, dict[int, float]]:
    """libellé dep_tr_nat -> {année: euros} (tous régimes)."""
    con = _duck()
    libelles = sorted({l for p in PRESTATIONS for l in p.get("caf", [])} | {APL, ALF, ALS})
    out: dict[str, dict[int, float]] = {l: {} for l in libelles}
    for lib, an, v in con.execute(
            f"select prestations, annee, dep_ts_regimes from '{chemin('cnaf_depenses')}' "
            f"where annee >= ? order by 1, 2", [min(annees)]).fetchall():
        if lib in out and v is not None:
            out[lib][int(an)] = v * M
    for lib, serie in out.items():
        if not serie:
            raise SystemExit(f"dep_tr_nat : libellé introuvable « {lib} » (le jeu a changé de forme)")
    return out


def _colonnes_ben(p: dict) -> tuple[str, str]:
    return f"indfoy_{p['ben']}", f"indmtt_{p['ben']}"


def lire_cnaf_mensuel(cle: str, par_departement: bool) -> dict:
    """{(dep|'FR', année): {ben: {'mois': n, 'foyers_dec': x, 'montant': Σ, 'foyers_somme': Σ, ...}}}."""
    con = _duck()
    cols = []
    for p in PRESTATIONS:
        if p.get("ben"):
            f, m = _colonnes_ben(p)
            cols += [f"sum({f})::double as {f}", f"sum({m})::double as {m}"]
    geo = "numdep" if par_departement else "'FR'"
    rows = con.execute(
        f"select {geo} as geo, year(dtreffre) as an, month(dtreffre) as mois, {', '.join(cols)} "
        f"from '{chemin(cle)}' group by all order by 1, 2, 3").fetchall()
    noms = ["geo", "an", "mois"] + [c.split(" as ")[1] for c in cols]
    out: dict = {}
    for r in rows:
        d = dict(zip(noms, r))
        cle_g = (str(d["geo"]), int(d["an"]))
        for p in PRESTATIONS:
            if not p.get("ben"):
                continue
            f, m = _colonnes_ben(p)
            acc = out.setdefault(cle_g, {}).setdefault(p["id"], {"mois": set(), "montant": 0.0, "foyers_somme": 0.0,
                                                                  "foyers_dec": None, "montant_dec": None})
            acc["mois"].add(d["mois"])
            acc["montant"] += d[m] or 0.0
            acc["foyers_somme"] += d[f] or 0.0
            if d["mois"] == 12:
                acc["foyers_dec"], acc["montant_dec"] = d[f], d[m]
    return out


def agreger_cnaf(acc: dict | None, p: dict) -> tuple:
    """(foyers en décembre, montant annuel, montant moyen) ; null si l'année est incomplète à la source."""
    if not acc or acc["foyers_dec"] is None:
        return None, None, None
    if p.get("annuelle"):  # ARS : une seule campagne, publiée en décembre
        f, mt = acc["foyers_dec"], acc["montant_dec"]
        return int(f), (round(mt) if mt else None), (round(mt / f, 2) if f and mt else None)
    if len(acc["mois"]) < 12:
        return int(acc["foyers_dec"]), None, None
    moyen = acc["montant"] / acc["foyers_somme"] if acc["foyers_somme"] else None
    return int(acc["foyers_dec"]), round(acc["montant"]), (round(moyen, 2) if moyen is not None else None)


def lire_cps(annees: list[int]) -> tuple[dict, dict, dict]:
    """({code: {année: €}} tous régimes, {année: total des prestations}, {(si_code, régime): {année: €}} retraites)."""
    con = _duck()
    f = chemin("drees_cps")
    codes = sorted({c for p in PRESTATIONS for c in p["cps"]})
    par_code: dict[str, dict[int, float]] = {c: {} for c in codes}
    for code, an, v in con.execute(
            f"select ps_code, annee::int, sum(val) from '{f}' where si_niveau = '0' and annee::int >= ? "
            f"and ps_code in ({','.join('?' * len(codes))}) group by all order by 1, 2",
            [min(annees)] + codes).fetchall():
        par_code[code][an] = v * M
    total = {an: v * M for an, v in con.execute(
        f"select annee::int, sum(val) from '{f}' where si_niveau = '0' and ps_code = 'E11-0' and annee::int >= ? "
        f"group by 1 order by 1", [min(annees)]).fetchall()}
    regimes: dict = {}
    for si, reg, an, v in con.execute(
            f"select si_code, regime_nom, annee::int, sum(val) from '{f}' where si_niveau = '2' and annee::int >= ? "
            f"and ps_code in ('E11-21.1', 'E11-22.1') group by all order by 1, 2, 3", [min(annees)]).fetchall():
        regimes.setdefault((si, reg), {})[an] = v * M
    return par_code, total, regimes


def lire_unedic() -> dict[int, float]:
    texte = chemin("unedic").read_text(encoding="utf-8-sig").lstrip("﻿")
    lignes = list(csv.reader(io.StringIO(texte), delimiter=";"))
    entete = [c.strip() for c in lignes[0]]
    i_an = entete.index("Année")
    i_v = next(i for i, c in enumerate(entete) if c.startswith("Dépenses - allocations brutes"))
    return {int(l[i_an]): float(l[i_v]) * M for l in lignes[1:] if l and l[i_an].strip().isdigit() and l[i_v].strip()}


def _feuille(cle: str, nom: str) -> list[tuple]:
    import openpyxl
    wb = openpyxl.load_workbook(chemin(cle), read_only=True, data_only=True)
    try:
        return [tuple(r) for r in wb[nom].iter_rows(values_only=True)]
    finally:
        wb.close()


def _colonnes_annees(entete: tuple) -> dict[int, int]:
    """année -> index de colonne (dernière occurrence : une année répétée signale une nouvelle méthode)."""
    out = {}
    for i, c in enumerate(entete):
        s = str(c).strip() if c is not None else ""
        if len(s) >= 4 and s[:4].isdigit() and 1990 <= int(s[:4]) <= 2100 and (len(s) == 4 or s[4] in " ("):
            out[int(s[:4])] = i
    return out


def _valeur_source(v):
    """Nombre tel quel ; marque de la source (« nd », « ns », « s »...) gardée telle quelle ; vide -> null."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return int(round(v)) if float(v).is_integer() or abs(v) >= 100 else float(v)
    return str(v).strip()


def lire_drees_nationales() -> dict[str, dict[int, object]]:
    rows = _feuille("drees_minima_nationales", "Tableau 2")
    entete = next(r for r in rows if sum(isinstance(c, int) and 1990 <= c <= 2100 for c in r) > 5)
    cols = _colonnes_annees(entete)
    out = {}
    for r in rows:
        lib = next((str(c) for c in r if isinstance(c, str)), "")
        for p in PRESTATIONS:
            if p.get("drees") and lib.startswith(p["drees"]):
                out[p["id"]] = {an: _valeur_source(r[i]) for an, i in cols.items()}
    manquants = [p["id"] for p in PRESTATIONS if p.get("drees") and p["id"] not in out]
    if manquants:
        raise SystemExit(f"DREES minima nationales : lignes introuvables {manquants}")
    return out


def lire_drees_depenses() -> tuple[int, dict[str, float]]:
    """(dernière année, {prestation: euros}) : seule la dernière année est en euros courants."""
    rows = _feuille("drees_minima_depenses", "Tableau 1")
    entete = next(r for r in rows if sum(isinstance(c, int) and 1990 <= c <= 2100 for c in r) > 5)
    cols = _colonnes_annees(entete)
    derniere = max(cols)
    unite = " ".join(str(c) for r in rows[:3] for c in r if isinstance(c, str))
    if f"constants {derniere}" not in unite:
        raise SystemExit(f"DREES dépenses : unité inattendue ({unite[:120]})")
    reperes = {"rsa": "RSA", "aah": "AAH", "aspa": "Minimum vieillesse"}
    out = {}
    for r in rows:
        lib = next((str(c) for c in r if isinstance(c, str)), "")
        for pid, debut in reperes.items():
            if lib.startswith(debut) and isinstance(r[cols[derniere]], (int, float)):
                out[pid] = r[cols[derniere]] * M
    if set(out) != set(reperes):
        raise SystemExit(f"DREES dépenses : lignes introuvables {set(reperes) - set(out)}")
    return derniere, out


def lire_drees_aspa_departements() -> tuple[dict[str, dict[int, object]], dict[str, str]]:
    rows = _feuille("drees_minima_departementales", "Tableau 7")
    i_ent = next(i for i, r in enumerate(rows) if any(str(c).strip() == "N° Dep" for c in r if c is not None))
    entete = rows[i_ent]
    i_code = next(i for i, c in enumerate(entete) if c is not None and str(c).strip() == "N° Dep")
    cols = _colonnes_annees(entete)
    vals, noms = {}, {}
    for r in rows[i_ent + 1:]:
        code = r[i_code]
        if code is None:
            continue
        code = str(code).strip()
        if not (code[:2].isdigit() and len(code) <= 3):
            break  # fin du bloc par département de résidence
        code = {"20A": "2A", "20B": "2B"}.get(code, code)
        noms[code] = str(r[i_code + 1]).strip()
        vals[code] = {an: _valeur_source(r[i]) for an, i in cols.items()}
    if len(vals) < 100:
        raise SystemExit(f"DREES Aspa par département : {len(vals)} départements lus")
    return vals, noms


def lire_francetravail() -> dict[int, dict[int, int]]:
    """{année: {mois: allocataires ARE (hors convention de gestion) + ARE formation (hors convention de gestion)}}."""
    rows = _feuille("francetravail_indemnises", "Brut France")
    i_ent = next(i for i, r in enumerate(rows) if r and "ARE (hors ARE-CG)" in [str(c).strip() for c in r if c])
    entete = [str(c).strip() if c is not None else "" for c in rows[i_ent]]
    i_are, i_aref = entete.index("ARE (hors ARE-CG)"), entete.index("AREF (hors AREF-CG)")
    out: dict[int, dict[int, int]] = {}
    for r in rows[i_ent + 1:]:
        d = r[0]
        if d is None or not hasattr(d, "year") or r[i_are] is None:
            continue
        an, mois = d.year, d.month  # janvier 2006 est daté du dernier jour du mois, les suivants du premier
        out.setdefault(an, {})[mois] = int(r[i_are]) + int(r[i_aref] or 0)
    return out


# --- Arbres publiés -------------------------------------------------------------------------------------------------

def _noeud(fichier: str, ident: str) -> dict | None:
    def chercher(n):
        if n.get("id") == ident:
            return n
        for e in n.get("enfants") or []:
            t = chercher(e)
            if t:
                return t
        return None
    p = SITE / fichier
    return chercher(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None


def liens_cps(codes: list[str]) -> list[dict]:
    """Nœuds de secu/cps (prestations 2024 par régime) dont l'identifiant finit par un des codes."""
    out = []
    for f in sorted((SITE / "secu" / "cps").glob("*.json")):
        def parcourir(n):
            ident = n.get("id", "")
            if any(ident.endswith("/" + c) for c in codes) and "fichier" not in n:
                out.append({"vue": "secu_cps", "fichier": f"secu/cps/{f.name}", "id": ident, "nom": n["nom"],
                            "md": n["md"]})
                return
            for e in n.get("enfants") or []:
                parcourir(e)
        parcourir(json.loads(f.read_text(encoding="utf-8")))
    return sorted(out, key=lambda x: (-x["md"], x["id"]))


def fichiers_regimes_cps() -> dict[str, str]:
    racine = json.loads((SITE / "secu" / "cps" / "racine.json").read_text(encoding="utf-8"))
    return {g["id"]: g["fichier"] for s in racine.get("enfants", []) for g in s.get("enfants", []) if "fichier" in g}


# --- Production -------------------------------------------------------------------------------------------------------

def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def _r(v):
    return None if v is None else round(v)


def _ecart(a_cle, a, b_cle, b, annee, lecture_cle=None) -> dict | None:
    if a is None or b is None or isinstance(a, str) or isinstance(b, str):
        return None
    return {"annee": annee, "source": a_cle, "montant": _r(a), "autre_source": b_cle, "autre_montant": _r(b),
            "ecart": _r(a - b), "ecart_pct": round((a - b) / b * 100, 1) if b else None,
            "lecture_ecart": LECTURE_ECART.get(lecture_cle or (a_cle, b_cle))}


def financeur_rsa(dep: str, annee: int) -> str:
    if dep not in RSA_RECENTRALISE:
        return "departement"
    debut, mois = RSA_RECENTRALISE[dep]
    if annee >= debut:
        return "etat"
    return "departement_puis_etat" if mois and str(annee) in mois else "departement"


def produire() -> dict:
    manquants = [k for k in COLLECTABLES if not chemin(k).exists()]
    if manquants:
        raise SystemExit(f"sources absentes de data/lake/secu : {manquants} (lancer `collecter`)")
    date = date_sources("secu")

    ben_nat = lire_cnaf_mensuel("cnaf_beneficiaires", par_departement=False)
    ben_dep = lire_cnaf_mensuel("cnaf_departements", par_departement=True)
    # années complètes publiées par la CNAF (12 mois)
    annees_cnaf = sorted(an for (g, an), v in ben_nat.items()
                         if an >= ANNEE_DEBUT and len(v["rsa"]["mois"]) == 12)
    annees = list(range(ANNEE_DEBUT, max(annees_cnaf) + 1))
    dep_cnaf = lire_cnaf_depenses(annees)
    cps, cps_total, cps_regimes = lire_cps(annees)
    unedic = lire_unedic()
    drees_nat = lire_drees_nationales()
    an_dep_drees, drees_dep = lire_drees_depenses()
    aspa_dep, noms_dep = lire_drees_aspa_departements()
    ft = lire_francetravail()
    annees_cps = sorted(an for an in cps_total if an in annees and any(cps[c].get(an) for c in cps))

    # --- séries nationales ---
    series, ecarts, liens = {}, [], {}
    for p in PRESTATIONS:
        pid = p["id"]
        s: dict = {"nom": p["nom"], "groupe": p["groupe"], "financeur": p["financeur"],
                   "serie_principale": p["principale"], "montant_eur": {}, "sources_montant": {}}
        if p.get("caf"):
            s["sources_montant"]["cnaf_depenses"] = {
                str(an): _r(sum(dep_cnaf[l].get(an, 0.0) for l in p["caf"])) if all(an in dep_cnaf[l] for l in
                                                                                       p["caf"]) else None
                for an in annees}
        s["sources_montant"]["drees_cps"] = {
            str(an): (_r(sum(cps[c].get(an, 0.0) for c in p["cps"])) if an in annees_cps else None) for an in annees}
        if pid == "are":
            s["sources_montant"]["unedic"] = {str(an): _r(unedic.get(an)) for an in annees}
        s["montant_eur"] = dict(s["sources_montant"][p["principale"]])
        s["derniere_annee"] = max((int(a) for a, v in s["montant_eur"].items() if v is not None), default=None)
        if p.get("detail_caf"):
            s["detail"] = {k: {"nom": lib, "source": "cnaf_depenses",
                               "montant_eur": {str(an): _r(dep_cnaf[lib].get(an)) for an in annees}}
                           for k, lib in p["detail_caf"].items()}
        if p.get("detail_cps"):
            s["detail"] = {k: {"code_drees": c, "source": "drees_cps",
                               "montant_eur": {str(an): (_r(cps[c].get(an)) if an in annees_cps else None)
                                               for an in annees}} for k, c in p["detail_cps"].items()}
        # bénéficiaires et montant moyen
        if p.get("ben"):
            agr = {an: agreger_cnaf(ben_nat.get(("FR", an), {}).get(pid), p) for an in annees}
            s["beneficiaires"] = {str(an): agr[an][0] for an in annees}
            s["beneficiaires_definition"] = ("foyers allocataires des CAF payés au titre de décembre (champ CAF, "
                                             "hors MSA ; Mayotte absente des mois de décembre 2020 à 2024 à la "
                                             "source)" if not p.get("annuelle") else
                                             "foyers allocataires des CAF ayant perçu l'allocation de l'année "
                                             "(champ CAF, hors MSA)")
            s["source_beneficiaires"] = "cnaf_beneficiaires"
            s["montant_moyen_eur"] = {str(an): agr[an][2] for an in annees}
            s["montant_moyen_periode"] = "an" if p.get("annuelle") else "mois"
            s["montant_moyen_methode"] = (
                "somme des montants versés par les CAF dans l'année / somme des foyers payés chaque mois (CNAF, champ "
                "CAF) : montant mensuel moyen par foyer" if not p.get("annuelle") else
                "montant versé par les CAF / foyers bénéficiaires (CNAF, champ CAF) : montant moyen par foyer et par an")
        elif pid == "aspa":
            eff = drees_nat["aspa"]
            s["beneficiaires"] = {str(an): eff.get(an) for an in annees}
            s["beneficiaires_definition"] = "allocataires de l'Aspa et de l'ASV au 31 décembre, France (DREES)"
            s["source_beneficiaires"] = "drees_minima_nationales"
            moy = {}
            for an in annees:
                m, e0, e1 = s["montant_eur"].get(str(an)), eff.get(an - 1), eff.get(an)
                ok = all(isinstance(x, (int, float)) for x in (m, e0, e1))
                moy[str(an)] = round(m / ((e0 + e1) / 2) / 12, 2) if ok else None
            s["montant_moyen_eur"] = moy
            s["montant_moyen_periode"] = "mois"
            s["montant_moyen_methode"] = ("minimum vieillesse (DREES, comptes de la protection sociale) / moyenne des "
                                          "effectifs au 31 décembre de l'année précédente et de l'année / 12 : ordre "
                                          "de grandeur, méthode de la DREES pour ce dispositif")
        elif pid == "are":
            s["beneficiaires"] = {str(an): (ft.get(an, {}).get(12)) for an in annees}
            s["beneficiaires_moyenne_mensuelle"] = {
                str(an): (round(sum(ft[an].values()) / 12) if len(ft.get(an, {})) == 12 else None) for an in annees}
            s["beneficiaires_definition"] = ("allocataires indemnisés en ARE et en ARE formation (hors convention de "
                                             "gestion) au titre du dernier jour de décembre, France (France Travail)")
            s["source_beneficiaires"] = "francetravail_indemnises"
            s["montant_moyen_eur"] = {str(an): None for an in annees}
            s["montant_moyen_methode"] = ("non calculé : les effectifs (France Travail) et les montants (Unédic, "
                                          "DREES) n'ont pas le même champ")
        else:
            s["beneficiaires"] = {str(an): None for an in annees}
            s["montant_moyen_eur"] = {str(an): None for an in annees}
            s["montant_moyen_methode"] = "non calculé : effectifs non repris (voir sources_inaccessibles)"
        if p.get("drees") and pid != "aspa":
            s["comparaison_beneficiaires"] = {"source": "drees_minima_nationales",
                                              "definition": "allocataires au 31 décembre, tous organismes payeurs",
                                              "valeurs": {str(an): drees_nat[pid].get(an) for an in annees}}
        if p.get("par_regime"):
            fichiers = fichiers_regimes_cps()
            regs = []
            for (si, reg), v in cps_regimes.items():
                if not any(v.get(an) for an in annees_cps):
                    continue
                regs.append({"code_secteur": si, "regime": reg, "fichier": fichiers.get(f"{si}/{reg}"),
                             "montant_eur": {str(an): (_r(v.get(an)) if an in annees_cps else None)
                                             for an in annees}})
            der = str(max(annees_cps))
            regs.sort(key=lambda x: (-(x["montant_eur"][der] or 0), x["regime"]))
            for x in regs:
                if x["fichier"] is None:
                    del x["fichier"]
            s["par_regime"] = regs
        series[pid] = s

        # écarts nationaux entre sources
        srcs = s["sources_montant"]
        for an in annees:
            a = str(an)
            if "cnaf_depenses" in srcs:
                e = _ecart("cnaf_depenses", srcs["cnaf_depenses"][a], "drees_cps", srcs["drees_cps"][a], an)
                if e:
                    ecarts.append({"prestation": pid, **e})
            if pid == "are":
                e = _ecart("unedic", srcs["unedic"][a], "drees_cps", srcs["drees_cps"][a], an)
                if e:
                    ecarts.append({"prestation": pid, **e})
        if pid in drees_dep:
            a = str(an_dep_drees)
            base = "cnaf_depenses" if "cnaf_depenses" in srcs else "drees_cps"
            e = _ecart(base, srcs[base].get(a), "drees_minima_depenses", drees_dep[pid], an_dep_drees)
            if e:
                ecarts.append({"prestation": pid, **e})
        if p.get("drees") and pid != "aspa":
            for an in annees:
                e = _ecart("cnaf_beneficiaires", s["beneficiaires"][str(an)], "drees_minima_nationales",
                           drees_nat[pid].get(an), an)
                if e:
                    ecarts.append({"prestation": pid, "grandeur": "beneficiaires", **e})

        # liens vers les financeurs (arbres publiés, 2024)
        lp = []
        for vue, fichier, ident, partage in LIENS.get(pid, []):
            n = _noeud(fichier, ident)
            if n is None:
                raise SystemExit(f"lien {pid} : nœud {ident} absent de {fichier}")
            lien = {"vue": vue, "fichier": fichier, "id": ident, "nom": n["nom"], "md": n["md"],
                    "millesime": "Exécution 2024", "lecture": LECTURE_LIEN[vue]}
            if partage:
                lien["partage_avec"] = partage
            lp.append(lien)
            ref = srcs[p["principale"]].get("2024")
            cle = ("drees_cps" if p["principale"] == "drees_cps" else p["principale"], vue)
            if not partage and ref is not None and len(LIENS[pid]) == 1:
                e = _ecart(p["principale"], ref, vue, n["md"] * 1e9, 2024, cle)
                if e:
                    ecarts.append({"prestation": pid, "lien": ident, **e})
        if len(LIENS.get(pid, [])) > 1 and srcs[p["principale"]].get("2024") is not None:
            # plusieurs nœuds qui, ensemble, financent la prestation : un seul écart, sur leur somme
            somme = sum(l["md"] for l in lp) * 1e9
            e = _ecart(p["principale"], srcs[p["principale"]]["2024"], LIENS[pid][0][0], somme, 2024,
                       (p["principale"], LIENS[pid][0][0]))
            ecarts.append({"prestation": pid, "lien": " + ".join(l["id"] for l in lp), **e})
        cps_l = liens_cps(p["cps"])
        for l in cps_l:
            l["millesime"] = "2024"
        lp += cps_l
        if pid == "rsa":
            lp.append({"vue": "local", "fichier": "local/budgets/departements.json", "id": "collectivites",
                       "nom": "Budgets des départements (OFGL)", "millesime": "comptes 2022 à 2025",
                       "lecture": "dépenses des départements, qui financent le RSA hors départements où il est "
                                  "recentralisé ; agrégats budgétaires, le RSA n'y est pas isolé"})
        liens[pid] = lp

    # écart RSA + prime d'activité financés par l'État vs action 304-11 (nœud partagé)
    n304 = _noeud("arbre/Solidarite-travail-et-sante_Solidarit-insertion-et-galit-des-chances_304.json", P304)
    part_etat_rsa = next((l["md"] for l in liens["rsa"] if l["vue"] == "secu_cps"
                          and l["id"].startswith("S13111/")), 0.0) * 1e9
    ppa_cps = series["prime_activite"]["sources_montant"]["drees_cps"].get("2024")
    if ppa_cps is not None:
        ecarts.append({"prestation": "prime_activite+rsa", "lien": P304, **_ecart(
            "drees_cps", ppa_cps + part_etat_rsa, "arbre_etat", n304["md"] * 1e9, 2024, ("cnaf_depenses", "arbre_etat")),
            "note": "prime d'activité (tous régimes) + RSA financé par l'État (régime d'intervention sociale de "
                    "l'État), comptes de la protection sociale 2024, comparés à l'action 304-11"})

    # --- totaux, source par source (jamais additionnées entre elles) ---
    caf_ids = [p["id"] for p in PRESTATIONS if p.get("caf")]
    totaux = {
        "drees_cps": {"prestations": [p["id"] for p in PRESTATIONS],
                      "montant_eur": {str(an): (_r(sum(series[p["id"]]["sources_montant"]["drees_cps"][str(an)]
                                                       for p in PRESTATIONS)) if an in annees_cps else None)
                                      for an in annees},
                      "total_prestations_protection_sociale_eur": {str(an): (_r(cps_total.get(an)) if an in annees_cps
                                                                             else None) for an in annees},
                      "lecture": "somme des prestations couvertes dans les comptes de la protection sociale "
                                 "(DREES) ; chaque code de prestation compté une fois ; à rapprocher du total de "
                                 "toutes les prestations de protection sociale de la même source"},
        "cnaf_depenses": {"prestations": caf_ids,
                          "montant_eur": {str(an): _r(sum(series[i]["sources_montant"]["cnaf_depenses"][str(an)]
                                                          for i in caf_ids)) for an in annees},
                          "lecture": "somme des prestations versées par les CAF et la MSA couvertes ici (CNAF, tous "
                                     "régimes) ; l'Aspa, l'ARE, les pensions et les indemnités journalières n'y sont "
                                     "pas"},
    }
    for t in totaux.values():
        part = t.get("total_prestations_protection_sociale_eur")
        if part:
            t["part_du_total_pct"] = {a: (round(t["montant_eur"][a] / part[a] * 100, 1)
                                          if t["montant_eur"][a] and part[a] else None) for a in part}

    # --- départements ---
    hors = sorted({c for (c, an) in ben_dep} - set(noms_dep))
    ecarts_dep = []
    fichiers_dep = []
    for an in annees:
        valeurs, hors_v = {}, {}
        somme = {pid: 0.0 for pid in DEPARTEMENTALES}
        complet = {pid: [] for pid in DEPARTEMENTALES}  # codes dont des mois manquent à la source
        for code in sorted({c for (c, a) in ben_dep if a == an}):
            ligne = {}
            for pid in DEPARTEMENTALES:
                acc = ben_dep.get((code, an), {}).get(pid)
                f, mt, moy = agreger_cnaf(acc, PAR_ID[pid])
                ligne[pid] = [f, mt, moy]
                if acc:  # somme de contrôle : tous les mois publiés, départements et codes hors département
                    somme[pid] += (acc["montant_dec"] or 0.0) if PAR_ID[pid].get("annuelle") else acc["montant"]
                    if not PAR_ID[pid].get("annuelle") and len(acc["mois"]) < 12:
                        complet[pid].append(code)
            if code in noms_dep:
                a = aspa_dep[code].get(an) if code in aspa_dep else None
                ligne["aspa"] = [a, None, None]
                ligne["financeur_rsa"] = financeur_rsa(code, an)
                valeurs[code] = {"nom": noms_dep[code], **ligne}
            else:
                hors_v[code] = ligne
        for pid in DEPARTEMENTALES:
            nat = series[pid]["sources_montant"]["cnaf_depenses"][str(an)]
            if nat:
                e = _ecart("cnaf_departements", somme[pid], "cnaf_depenses", nat, an)
                if complet[pid]:
                    e["codes_mois_manquants"] = complet[pid]
                if pid == "paje":
                    e["lecture_ecart"] += " ; " + LECTURE_PAJE
                ecarts_dep.append({"prestation": pid, **e})
        doc = {
            "millesime": f"Année {an}",
            "source": f"{SOURCES['cnaf_departements']['titre']} ; Aspa : {SOURCES['drees_minima_departementales']['titre']}",
            "unite": "foyers ; euros ; euros par foyer et par mois (ARS : par an)",
            "annee": an,
            "colonnes": ["foyers_decembre", "montant_annuel_eur", "montant_moyen_eur"],
            "definitions": {
                "foyers_decembre": "foyers allocataires des CAF payés au titre de décembre (ARS : foyers bénéficiaires "
                                   "de l'année) ; Aspa : allocataires au 31 décembre (DREES)",
                "montant_annuel_eur": "somme des montants versés chaque mois de l'année par les CAF (ARS : montant de "
                                      "la campagne annuelle) ; null si l'année est incomplète à la source",
                "montant_moyen_eur": "montant annuel / somme des foyers payés chaque mois (ARS : montant / foyers)",
                "financeur_rsa": "departement, etat (RSA recentralisé) ou departement_puis_etat (année du transfert)",
            },
            "prestations": {pid: PAR_ID[pid]["nom"] for pid in DEPARTEMENTALES + ["aspa"]},
            "departements": valeurs,
            "hors_departements": hors_v,
            "note_perimetre": "champ CAF (hors MSA) ; une année dont un mois manque à la source (Mayotte, décembre "
                              "2020 à 2024) a un montant annuel null ; codes hors département de la CNAF : 978 Saint-Martin, 99 et XX "
                              "(résidence inconnue ou à l'étranger) ; Corse : effectifs de l'Aspa estimés par la DREES",
        }
        rel = f"prestations/departements/{an}.json"
        dump(SITE / rel, doc)
        fichiers_dep.append(rel)

    index = {
        "millesime": f"{annees[0]} à {annees[-1]} (CNAF, Unédic) ; {annees_cps[0]} à {annees_cps[-1]} (DREES)",
        "source": "CNAF (data.caf.fr), DREES (comptes de la protection sociale, minima sociaux), Unédic, France "
                  "Travail ; liens vers le budget de l'État (exécution 2024) et les comptes de la Sécurité sociale",
        "unite": "euros ; foyers ou allocataires",
        "date_sources": date,
        "annees": annees,
        "derniere_annee": {pid: series[pid]["derniere_annee"] for pid in series},
        "prestations": [{"id": p["id"], "nom": p["nom"], "groupe": p["groupe"], "financeur": p["financeur"],
                         "serie_principale": p["principale"], "departemental": p["id"] in DEPARTEMENTALES
                         or p["id"] == "aspa", "liens": liens[p["id"]]} for p in PRESTATIONS],
        "fichiers": {"nationales": "prestations/nationales.json",
                     "departements": {str(an): f for an, f in zip(annees, fichiers_dep)}},
        "totaux": totaux,
        "ecarts": ecarts,
        "ecarts_departements": ecarts_dep,
        "couverture_departementale": {
            "prestations": DEPARTEMENTALES + ["aspa"],
            "grandeurs": {pid: "foyers, montant annuel, montant moyen (CNAF, champ CAF)" for pid in DEPARTEMENTALES}
            | {"aspa": "allocataires seulement (DREES)"},
            "annees": annees, "annees_aspa": sorted(an for an in annees if any(
                isinstance(v.get(an), int) for v in aspa_dep.values())),
            "departements": len(noms_dep), "codes_hors_departement": hors,
            "rsa_recentralise": {d: {"premiere_annee_entiere": v[0], **({"debut": v[1]} if v[1] else {})}
                                 for d, v in sorted(RSA_RECENTRALISE.items())},
            "non_couvert": ["are", "pensions_retraite", "indemnites_journalieres"],
        },
        "regle": "agrégats publiés seulement ; une valeur masquée ou non disponible reste telle quelle, jamais 0 ; "
                 "les liens vers les arbres désignent le même argent vu du côté du financeur et ne s'additionnent "
                 "jamais aux montants des prestations ; les totaux sont calculés source par source",
        "sources": {k: {kk: vv for kk, vv in v.items()} for k, v in sorted(SOURCES.items())},
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    nationales = {
        "millesime": index["millesime"], "source": index["source"],
        "unite": "euros ; foyers ou allocataires ; euros par foyer et par mois (ARS : par an)",
        "annees": annees, "prestations": series,
    }
    dump(SORTIE / "nationales.json", nationales)
    dump(SORTIE / "index.json", index)
    print(f"prestations : {len(series)} prestations, {len(fichiers_dep)} années départementales, "
          f"{len(ecarts)} écarts nationaux, {len(ecarts_dep)} écarts départementaux")
    return index


# --- Collecte ---------------------------------------------------------------------------------------------------------

def telecharger(url: str, dest: Path, essais: int = 5) -> str:
    import requests
    for i in range(essais):
        try:
            r = requests.get(url, timeout=(20, 300), headers={"User-Agent": "ou-vont-mes-impots/pipeline"})
            if r.status_code in (401, 403, 429, 451):
                return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
            r.raise_for_status()
            if dest.suffix in (".xlsx", ".parquet") and r.content[:4] not in (b"PK\x03\x04", b"PAR1"):
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
    for cle in COLLECTABLES:
        dest = chemin(cle)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0 and not forcer:
            etat[cle] = "présent"
        else:
            etat[cle] = telecharger(SOURCES[cle]["url"], dest)
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
