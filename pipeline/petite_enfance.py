"""Accueil du jeune enfant : dépenses (complément de libre choix du mode de garde, action sociale des CAF pour la
petite enfance, dont la prestation de service unique des crèches), places d'accueil et taux de couverture, par
année et par département.

Agrégats publiés seulement (aucune donnée individuelle, aucun établissement nommé). Ce module ne republie pas les
prestations familiales de pipeline/prestations.py : la prestation d'accueil du jeune enfant (PAJE) y est publiée en
total ; ici, seul son complément de libre choix du mode de garde est détaillé (par mode de garde, et par
département), avec un lien vers la ligne PAJE, jamais un montant ajouté à elle.

Entrées : entrepôt brut data/lake/ (non versionné), collecté par collecte/collecte.py (domaine « petite_enfance »
de collecte/catalogue.json, plus secu_caf_s_ben_dep déjà déclaré pour pipeline/prestations.py) :
  petite_enfance/pe_caf_places_dep[_hist].parquet        CNAF, places offertes aux moins de 3 ans par mode et département
  petite_enfance/pe_caf_places_nat[_hist].parquet        CNAF, mêmes places, France
  petite_enfance/pe_caf_couverture_dep[_hist].parquet    CNAF, taux de couverture par mode et département
  petite_enfance/pe_caf_couverture_nat[_hist].parquet    CNAF, taux de couverture, France
  petite_enfance/pe_caf_action_sociale_dep.parquet       CNAF, dépenses d'action sociale par fonction et par caisse
  petite_enfance/pe_caf_action_sociale_nat.parquet       CNAF, dépenses d'action sociale par fonction, France
  petite_enfance/pe_caf_depenses_nat.parquet             CNAF, dépenses tous régimes par prestation (lignes du CMG)
  petite_enfance/pe_caf_cmg_dep.parquet                  CNAF, foyers bénéficiaires du CMG par type et département
  petite_enfance/pe_drees_offre_accueil_2024.xlsx        DREES, offre d'accueil des moins de 3 ans (volet PMI)
  secu/secu_caf_s_ben_dep.parquet                        CNAF, foyers et montants mensuels par prestation et département
Sorties :
  site/data/petite_enfance/index.json                  dispositifs, sources, écarts entre sources, liens, recherche
  site/data/petite_enfance/nationales.json             séries annuelles France
  site/data/petite_enfance/departements/<annee>.json   par département

Commandes :
  python pipeline/petite_enfance.py collecter   # réseau (collecte/collecte.py ; un refus 401/403/429 n'est jamais contourné)
  python pipeline/petite_enfance.py produire    # sans réseau
  python pipeline/petite_enfance.py             # les deux

Règles :
  - deux sources ne sont jamais additionnées ; les écarts (CNAF et DREES pour les places, dépenses comptables et
    montants versés chaque mois pour le CMG, ancienne et nouvelle série de la CNAF) sont publiés tels quels ;
  - les deux séries de places de la CNAF (historique 2017-2022, nouvelle méthode depuis 2022) ne sont pas raccordées ;
  - une valeur absente ou non disponible à la source reste null avec une mention, jamais 0 ;
  - toute date écrite vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "petite_enfance"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "petite_enfance"
DOMAINE = "petite_enfance"
ANNEES = list(range(2017, 2026))
ANNEES_CMG = list(range(2017, 2025))     # années complètes avant la rupture de septembre 2025
M = 1e6

CAF = "https://data.caf.fr/explore/dataset/"
CAF_API = "https://data.caf.fr/api/explore/v2.1/catalog/datasets/"
DREES_331 = "https://data.drees.solidarites-sante.gouv.fr/explore/dataset/331_l-offre-d-accueil-du-jeune-enfant/"
SOURCES = {
    "cnaf_places": {
        "fichiers": ["pe_caf_places_dep.parquet", "pe_caf_places_nat.parquet"],
        "url": f"{CAF_API}nbpla_pe_dep/exports/parquet", "page": f"{CAF}nbpla_pe_dep/",
        "titre": "CNAF, « Nombre de places offertes pour les enfants de moins de 3 ans » [Département] et [National] "
                 "(nbpla_pe_dep, nbpla_pe_nat) : places au mois de décembre, par mode d'accueil",
        "producteur": "CNAF (indicateur de l'Observatoire national de la petite enfance)", "millesime": "2022 et 2023",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel (export parquet de l'API Opendatasoft)",
    },
    "cnaf_places_historique": {
        "fichiers": ["pe_caf_places_dep_hist.parquet", "pe_caf_places_nat_hist.parquet"],
        "url": f"{CAF_API}nbpla_pe_dep_hist/exports/parquet", "page": f"{CAF}nbpla_pe_dep_hist/",
        "titre": "CNAF, « Nombre de places offertes pour les enfants de moins de 3 ans, historique 2017-2022 » "
                 "[Département] et [National] (nbpla_pe_dep_hist, nbpla_pe_nat_hist)",
        "producteur": "CNAF (indicateur de l'Observatoire national de la petite enfance)", "millesime": "2017 à 2022",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel (ancienne méthode, série distincte)",
    },
    "cnaf_couverture": {
        "fichiers": ["pe_caf_couverture_dep.parquet", "pe_caf_couverture_nat.parquet"],
        "url": f"{CAF_API}txcouv_pe_dep/exports/parquet", "page": f"{CAF}txcouv_pe_dep/",
        "titre": "CNAF, « Taux de couverture d'accueil du jeune enfant » [Département] et [National] (txcouv_pe_dep, "
                 "txcouv_pe_nat) : places pour 100 enfants de moins de 3 ans, par mode d'accueil",
        "producteur": "CNAF (indicateur de l'Observatoire national de la petite enfance)", "millesime": "2022 et 2023",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel",
    },
    "cnaf_couverture_historique": {
        "fichiers": ["pe_caf_couverture_dep_hist.parquet", "pe_caf_couverture_nat_hist.parquet"],
        "url": f"{CAF_API}txcouv_pe_dep_hist/exports/parquet", "page": f"{CAF}txcouv_pe_dep_hist/",
        "titre": "CNAF, « Taux de couverture d'accueil du jeune enfant, historique 2017-2022 » [Département] et "
                 "[National] (txcouv_pe_dep_hist, txcouv_pe_nat_hist)",
        "producteur": "CNAF (indicateur de l'Observatoire national de la petite enfance)", "millesime": "2017 à 2022",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel (ancienne méthode, série distincte)",
    },
    "cnaf_action_sociale": {
        "fichiers": ["pe_caf_action_sociale_dep.parquet", "pe_caf_action_sociale_nat.parquet"],
        "url": f"{CAF_API}vfdas_dep/exports/parquet", "page": f"{CAF}vfdas_dep/",
        "titre": "CNAF, « Dépenses d'action sociale » [Département] et [National] (vfdas_dep, vfdas_nat) : "
                 "ventilation fonctionnelle des dépenses d'action sociale des CAF au 31 décembre, en euros",
        "producteur": "CNAF", "millesime": "2017 à 2025", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (caisse rattachée à son département par son numéro d'organisme)",
    },
    "cnaf_depenses": {
        "fichiers": ["pe_caf_depenses_nat.parquet"],
        "url": f"{CAF_API}dep_tr_nat/exports/parquet", "page": f"{CAF}dep_tr_nat/",
        "titre": "CNAF, « Dépenses tous régimes [National] » (dep_tr_nat) : lignes du complément de libre choix du "
                 "mode de garde, tous régimes (CAF et MSA), France hors Mayotte, M€",
        "producteur": "CNAF", "millesime": "2013 à 2025", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (même jeu que pipeline/prestations.py, lignes de détail)",
    },
    "cnaf_cmg_foyers": {
        "fichiers": ["pe_caf_cmg_dep.parquet"],
        "url": f"{CAF_API}ndurcmg_s_sitfam_dep/exports/parquet", "page": f"{CAF}ndurcmg_s_sitfam_dep/",
        "titre": "CNAF, « CMG : répartition des allocataires selon le type de CMG et la situation familiale » "
                 "[Département] (ndurcmg_s_sitfam_dep) : foyers bénéficiaires chaque mois, champ CAF",
        "producteur": "CNAF", "millesime": "juin 2016 à mars 2026 (mensuel)", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (somme des situations familiales)",
    },
    "cnaf_cmg_montants": {
        "fichiers": ["../secu/secu_caf_s_ben_dep.parquet"],
        "url": f"{CAF_API}s_ben_dep/exports/parquet", "page": f"{CAF}s_ben_dep/",
        "titre": "CNAF, « Toutes prestations : répartition des allocataires selon la prestation [Départemental] » "
                 "(s_ben_dep) : colonnes du complément de libre choix du mode de garde (foyers et montant versé "
                 "chaque mois), champ CAF",
        "producteur": "CNAF", "millesime": "juin 2016 à mars 2026 (mensuel)", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (même fichier que pipeline/prestations.py, autres colonnes)",
    },
    "drees_offre_accueil": {
        "fichiers": ["pe_drees_offre_accueil_2024.xlsx"],
        "url": "https://data.drees.solidarites-sante.gouv.fr/api/v2/catalog/datasets/331_l-offre-d-accueil-du-jeune-"
               "enfant/attachments/l_offre_d_accueil_des_enfants_de_moins_de_3_ans_series_longues_et_resulats_"
               "detailles_2024_xlsx",
        "page": DREES_331,
        "titre": "DREES, « L'offre d'accueil des enfants de moins de 3 ans : séries longues et résultats détaillés "
                 "2024 » (enquête Aide sociale auprès des départements, volet protection maternelle et infantile) : "
                 "places agréées en établissement au 31 décembre, agréments d'assistants maternels",
        "producteur": "DREES", "millesime": "1993 à 2024 (France) ; 2010 à 2024 (départements)",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel (classeur, lecture des tableaux par titre)",
    },
}

# --- Libellés ----------------------------------------------------------------------------------------------------

MODES_PLACES = [  # (id, colonne CNAF sans suffixe, nom)
    ("eaje_psu", "pl_psu_col", "Crèches financées par la prestation de service unique (multi-accueil, familiales, "
                               "parentales, micro-crèches)"),
    ("eaje_hors_psu", "pl_hors_psu_col", "Autres crèches (micro-crèches financées par le complément de libre choix "
                                         "du mode de garde, crèches de personnel)"),
    ("eaje", "pl_eaje", "Ensemble des crèches (établissements d'accueil du jeune enfant)"),
    ("prescolarisation", "pl_prescol", "École maternelle (enfants de 2 ans)"),
    ("assistantes_maternelles", "pl_am_ind", "Assistantes maternelles"),
    ("garde_domicile", "pl_gad_ind", "Salariée à domicile"),
    ("accueil_individuel", "pl_ind", "Ensemble de l'accueil individuel"),
    ("total", "tot_offre", "Ensemble des places offertes (accueil formel)"),
]
MODES_TAUX = [(i, c.replace("pl_", "txcouv_").replace("tot_offre", "txcouv"), n) for i, c, n in MODES_PLACES]

CMG_POSTES = [  # (id, nom, lignes de dep_tr_nat)
    ("assistantes_maternelles", "Emploi direct d'une assistante maternelle agréée",
     ["CMG Assistantes maternelles - Rémunération", "CMG Assistantes maternelles - Cotisations"]),
    ("garde_domicile", "Emploi direct d'une garde d'enfants à domicile (« assistantes parentales » dans la source)",
     ["CMG Assistantes parentales - Rémunération", "CMG Assistantes parentales - Cotisations"]),
    ("micro_creche", "Recours à une micro-crèche", ["CMG Structure - Micro-crèches"]),
    ("association_entreprise", "Recours à une association ou une entreprise",
     ["CMG Structure - Autres associations/entreprises"]),
]
CMG_TOTAL = "PAJE complément mode de garde (CMG)"
CMG_TYPES = [("assistantes_maternelles", "indfoy_cmg_assmat"), ("garde_domicile", "indfoy_cmg_gardom"),
             ("structure_hors_micro_creche", "indfoy_cmg_str"), ("micro_creche", "indfoy_cmg_str_mc")]

# Action sociale petite enfance (0 à 6 ans) : colonnes « masf1… » de la ventilation fonctionnelle.
AS_POSTES = [
    ("fonctionnement_partenaires_fonds_nationaux", "masf1pfn",
     "Aides au fonctionnement des structures partenaires, fonds nationaux (prestations de service, dont la "
     "prestation de service unique des crèches)"),
    ("fonctionnement_partenaires_fonds_locaux", "masf1pfl",
     "Aides au fonctionnement des structures partenaires, fonds locaux de la caisse"),
    ("investissement_partenaires_fonds_nationaux", "masf1invfn",
     "Subventions d'investissement aux structures partenaires, fonds nationaux"),
    ("investissement_partenaires_fonds_locaux", "masf1invfl",
     "Subventions d'investissement aux structures partenaires, fonds locaux"),
    ("prets_partenaires", "masf1ppr", "Prêts d'investissement aux structures partenaires"),
    ("structures_caf_fonctionnement_fonds_locaux", "masf1cfl",
     "Fonctionnement des structures gérées par la caisse, fonds locaux"),
    ("structures_caf_fonctionnement_fonds_nationaux", "masf1cps",
     "Fonctionnement des structures gérées par la caisse, prestations de service (fonds affectés)"),
    ("structures_caf_investissement", "masf1cin", "Investissement des structures gérées par la caisse"),
    ("aides_familles_subventions", "masf1fsu", "Aides financières aux familles (subventions)"),
    ("aides_familles_prets", "masf1fpr", "Aides financières aux familles (prêts)"),
    ("gestion_fonctionnement", "masf1gfn", "Gestion administrative des œuvres, fonctionnement, fonds nationaux"),
    ("gestion_investissement", "masf1gin", "Gestion administrative des œuvres, investissement, fonds nationaux"),
]
AS_TOTAL_PE, AS_TOTAL = "masfb1to", "masfbtot"

DREES_CATEGORIES = [  # (id, nom ; tableaux départementaux des places par année)
    ("creches_collectives", "Crèches collectives (micro-crèches comprises)", "Tab28-PMI"),
    ("creches_familiales", "Crèches familiales", "Tab29-PMI"),
    ("multi_accueil", "Multi-accueil collectif et familial", "Tab30-PMI"),
    ("jardins_enfants", "Jardins d'enfants", "Tab31-PMI"),
    ("gestion_parentale", "Établissements et services à gestion parentale", "Tab32-PMI"),
]
DREES_NAT_PLACES = {"Crèches collectives": "creches_collectives", "Crèches familiales": "creches_familiales",
                    "Multi accueil collectif et familial": "multi_accueil", "Jardins d'enfants": "jardins_enfants",
                    "Etablissements et services à gestion parentale": "gestion_parentale",
                    "Total établissements et services d'accueil de jeunes enfants": "total"}
DREES_NAT_ASSMAT = [
    ("agrements", "Assistants maternels agréés au 31 décembre"),
    ("capacite_agreee", "Capacités totales d'accueil autorisées"),
    ("en_activite_particuliers", "Assistants maternels agréés en activité"),
    ("places_potentielles", "Estimation du nombre de places potentiellement offertes"),
]

DEFINITIONS = {
    "places": "places offertes aux enfants de moins de 3 ans au mois de décembre (indicateur de l'Observatoire "
              "national de la petite enfance, calculé par la CNAF) : offre théorique ; une place peut être vacante "
              "ou occupée par plusieurs enfants",
    "couverture": "places offertes pour 100 enfants de moins de 3 ans (taux de couverture de la CNAF)",
    "action_sociale": "dépenses d'action sociale des CAF pour la petite enfance (0 à 6 ans), en euros, ventilation "
                      "fonctionnelle au 31 décembre ; financées par le fonds national d'action sociale de la branche "
                      "famille et les fonds locaux des caisses",
    "cmg": "complément de libre choix du mode de garde : partie de la prestation d'accueil du jeune enfant qui prend "
           "en charge une partie de la rémunération et des cotisations d'une assistante maternelle ou d'une garde à "
           "domicile, ou du coût d'une micro-crèche ou d'une association ou entreprise",
    "places_agreees": "places agréées en établissement d'accueil du jeune enfant au 31 décembre, déclarées par les "
                      "services de protection maternelle et infantile des départements (DREES)",
    "agrements": "agréments d'assistants maternels en cours de validité au 31 décembre (DREES)",
}

LECTURE_PLACES = ("la CNAF compte les places offertes en décembre aux moins de 3 ans (crèches, école maternelle, "
                  "assistantes maternelles en activité, salariées à domicile) ; la DREES compte les places agréées "
                  "par les services de protection maternelle et infantile (moins de 6 ans, établissements seulement)")
LECTURE_ASSMAT = ("la CNAF compte les places offertes aux moins de 3 ans par les assistantes maternelles en "
                  "activité ; la DREES estime les places potentielles des assistants maternels employés par des "
                  "particuliers, tous âges")
LECTURE_SERIES = ("la CNAF a changé de méthode en 2022 ; elle publie 2022 dans les deux séries, qui ne sont pas "
                  "raccordées")
LECTURE_CMG = ("dépenses comptables tous régimes (CAF et MSA), cotisations sociales prises en charge comprises ; "
               "montants versés chaque mois par les CAF (champ CAF), qui ne comprennent pas en totalité les "
               "cotisations prises en charge")
RUPTURE_CMG = ("à partir de septembre 2025, les foyers bénéficiaires du complément pour l'emploi direct d'une "
               "assistante maternelle ou d'une garde à domicile ne figurent presque plus dans les jeux "
               "départementaux de la CNAF (réforme du complément entrée en vigueur le 1er septembre 2025) ; l'année "
               "2025 n'est pas reprise par département")

LIENS = [
    {"vue": "prestations", "fichier": "prestations/nationales.json", "id": "paje",
     "lecture": "le complément de libre choix du mode de garde est une partie de la prestation d'accueil du jeune "
                "enfant publiée dans les prestations : même argent, déjà compté dans ce total, ne s'y ajoute pas"},
    {"vue": "secu_arbre", "fichier": "secu/arbre/racine.json", "id": "robss/famille",
     "lecture": "dépenses 2024 de la branche famille (comptes des organismes) : elles comprennent les prestations "
                "et l'action sociale des CAF ; même argent vu du côté du financeur, ne s'ajoute pas"},
]

INACCESSIBLES = [
    {"source": "Prestation de service unique des crèches, montant isolé (national et par département)",
     "motif": "aucun jeu ouvert ne la sépare des autres prestations de service : la ventilation de l'action sociale "
              "des CAF la range dans « fonctionnement des structures partenaires, fonds nationaux », qui comprend "
              "aussi les bonus et les autres prestations de service ; le rapport annuel de l'Observatoire national "
              "de la petite enfance la cite en PDF seulement"},
    {"source": "Dépenses de l'accueil du jeune enfant tous financeurs (CNAF, État, collectivités, ménages)",
     "motif": "publiées par l'Observatoire national de la petite enfance (rapport « L'accueil du jeune enfant ») en "
              "PDF seulement, sans fichier de données ; non reprises"},
    {"source": "Complément de libre choix du mode de garde par département : montants par mode de garde",
     "motif": "le jeu départemental de la CNAF publie les foyers par mode de garde, et le montant pour l'ensemble "
              "du complément seulement"},
    {"source": "Crédit d'impôt pour frais de garde des jeunes enfants",
     "motif": "dépense fiscale de l'État, publiée dans l'axe des dépenses fiscales du site, pas ici"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Les producteurs publient déjà les agrégats nécessaires (API Opendatasoft de la CNAF, classeur de "
                  "la DREES) : ils sont repris tels quels. Les dépôts publics trouvés reprennent le taux de "
                  "couverture ou les places par commune pour un diagnostic territorial ; aucun ne relie places, "
                  "complément de libre choix du mode de garde et action sociale des CAF, ni ne publie les écarts "
                  "entre la CNAF et la DREES : module écrit pour le dépôt, sur le modèle de pipeline/prestations.py.",
    "trouvailles": [
        {"nom": "CNAF, API data.caf.fr (nbpla_pe, txcouv_pe, vfdas, ndurcmg, dep_tr_nat, s_ben_dep)",
         "url": "https://data.caf.fr/", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-09-28",
         "verdict": "réutilisable tel quel"},
        {"nom": "DREES, L'offre d'accueil du jeune enfant (331)", "url": DREES_331, "licence": "Licence Ouverte 2.0",
         "mise_a_jour": "2026-05-28", "verdict": "réutilisable tel quel"},
        {"nom": "data.gouv.fr, jeux CNAF « Taux de couverture d'accueil du jeune enfant » (communal à national)",
         "url": "https://www.data.gouv.fr/fr/datasets/taux-de-couverture-daccueil-du-jeune-enfant-departement/",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-01-22",
         "verdict": "réutilisable tel quel (mêmes jeux que data.caf.fr)"},
        {"nom": "DREES, enquête Modes de garde et d'accueil des jeunes enfants (data.gouv.fr)",
         "url": "https://www.data.gouv.fr/fr/datasets/modes-de-garde-et-daccueil-et-scolarisation-des-enfants-ages-"
                "de-moins-de-6-ans/", "licence": None, "mise_a_jour": "2024-02-13",
         "verdict": "inspiration seulement (enquête auprès des ménages, pas de dépenses ni de départements)"},
        {"nom": "rouages-de-la-france/rouages.fr (scripts/petite-enfance-emettre.ts)",
         "url": "https://github.com/rouages-de-la-france/rouages.fr", "licence": "AGPL-3.0",
         "dernier_commit": "2026-11-09", "verdict": "inspiration seulement (communes, TypeScript)"},
        {"nom": "vigie-civique/vigie-commune (collectors/enfance.py)",
         "url": "https://github.com/vigie-civique/vigie-commune", "licence": "MIT", "dernier_commit": "2026-10-22",
         "verdict": "inspiration seulement (une commune)"},
        {"nom": "Hpoinseaux/diag_360 et Guillaume-BR/diag360 (indicateur i130, taux de couverture)",
         "url": "https://github.com/Hpoinseaux/diag_360", "licence": "MIT (diag_360) ; aucune (diag360)",
         "dernier_commit": "2026-02-17", "verdict": "inspiration seulement (un indicateur)"},
        {"nom": "aubryprieur/api_territory_statistics (import_childcare_by_territory.py)",
         "url": "https://github.com/aubryprieur/api_territory_statistics", "licence": None,
         "dernier_commit": "2026-11-10", "verdict": "inspiration seulement (sans licence)"},
        {"nom": "rundata-re/rundata (scripts/build-creches.py)", "url": "https://github.com/rundata-re/rundata",
         "licence": None, "dernier_commit": None, "verdict": "inspiration seulement (La Réunion)"},
        {"nom": "Recherches GitHub « vfdas », « complement mode de garde caf », « places creches departement », "
                "« onape petite enfance »", "url": "https://github.com/search", "licence": None,
         "dernier_commit": None, "verdict": "aucun autre dépôt pertinent"},
    ],
}


# --- Lecture de l'entrepôt ----------------------------------------------------------------------------------------

def chemin(cle: str, i: int = 0) -> Path:
    return (BRUT / SOURCES[cle]["fichiers"][i]).resolve()


def _duck():
    import duckdb
    return duckdb.connect()


def _an(v) -> int:
    return int(str(v)[:4])


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else round(float(v), 2)
    return None


def dep_de_caisse(numorg: str) -> str:
    """Numéro d'organisme d'une CAF -> code du département (201 Corse-du-Sud, 202 Haute-Corse, 97x outre-mer)."""
    numorg = str(numorg)
    if numorg.startswith("97"):
        return numorg
    if numorg in ("201", "202"):
        return {"201": "2A", "202": "2B"}[numorg]
    return numorg[:2]


def lire_cnaf_mode(cle: str, modes: list, suffixe: str, nat: bool) -> dict:
    """{(code|'FR', année): {mode: valeur}} pour un jeu places ou taux (départemental ou national)."""
    f = chemin(cle, 1 if nat else 0)
    cols = [f"{c}_{suffixe}" for _, c, _ in modes]
    geo = "'FR'" if nat else "numdep"
    out = {}
    for r in _duck().execute(f"select {geo}, annee, {', '.join(cols)} from '{f}' order by 1, 2").fetchall():
        out[(str(r[0]), _an(r[1]))] = {m[0]: _num(v) for m, v in zip(modes, r[2:])}
    return out


def lire_action_sociale() -> tuple[dict, dict]:
    """({(dep, année): {poste: €}}, {année: {poste: €}}) ; postes AS_POSTES + petite_enfance + ensemble."""
    cols = [c for _, c, _ in AS_POSTES] + [AS_TOTAL_PE, AS_TOTAL]
    ids = [i for i, _, _ in AS_POSTES] + ["petite_enfance", "ensemble_action_sociale"]
    con = _duck()
    dep: dict = {}
    for r in con.execute(f"select numorg, dfrefenr, {', '.join(cols)} from '{chemin('cnaf_action_sociale')}' "
                         f"order by 1, 2").fetchall():
        cle = (dep_de_caisse(r[0]), _an(r[1]))
        if cle in dep:
            raise SystemExit(f"vfdas_dep : deux caisses pour le département {cle} (rattachement à revoir)")
        dep[cle] = {i: (round(v) if v is not None else None) for i, v in zip(ids, r[2:])}
    nat = {_an(r[0]): {i: (round(v) if v is not None else None) for i, v in zip(ids, r[1:])}
           for r in con.execute(f"select dfrefenr, {', '.join(cols)} from '{chemin('cnaf_action_sociale', 1)}' "
                                f"order by 1").fetchall()}
    return dep, nat


def lire_cmg_national() -> dict[str, dict[int, float]]:
    """libellé dep_tr_nat -> {année: euros} (tous régimes, France hors Mayotte)."""
    libelles = [CMG_TOTAL] + [l for _, _, ls in CMG_POSTES for l in ls]
    out: dict = {l: {} for l in libelles}
    for lib, an, v in _duck().execute(
            f"select prestations, annee, dep_ts_regimes from '{chemin('cnaf_depenses')}' where annee >= ? "
            f"order by 1, 2", [ANNEES[0]]).fetchall():
        if lib in out and v is not None:
            out[lib][int(an)] = round(v * M)
    for lib, s in out.items():
        if not s:
            raise SystemExit(f"dep_tr_nat : libellé introuvable « {lib} » (le jeu a changé de forme)")
    return out


def lire_cmg_departements() -> tuple[dict, dict]:
    """({(dep, année): {foyers_decembre, montant_annuel_eur, mois}}, {(dep, année): {type: foyers en décembre}})."""
    con = _duck()
    mont: dict = {}
    for dep, an, mois, foy, mt in con.execute(
            f"select numdep, year(dtreffre), month(dtreffre), sum(indfoy_cmg)::double, sum(indmtt_cmg)::double "
            f"from '{chemin('cnaf_cmg_montants')}' group by all order by 1, 2, 3").fetchall():
        a = mont.setdefault((str(dep), int(an)), {"mois": [], "montant": 0.0, "foyers_decembre": None})
        a["mois"].append(int(mois))
        a["montant"] += mt or 0.0
        if mois == 12:
            a["foyers_decembre"] = int(foy) if foy is not None else None
    types: dict = {}
    sel = ", ".join(f"sum({c})::bigint" for _, c in CMG_TYPES)
    for r in con.execute(f"select numdep, year(dtreffre), {sel} from '{chemin('cnaf_cmg_foyers')}' "
                         f"where month(dtreffre) = 12 group by all order by 1, 2").fetchall():
        types[(str(r[0]), int(r[1]))] = {t: (int(v) if v is not None else None) for (t, _), v in zip(CMG_TYPES, r[2:])}
    return mont, types


def _cellule(v):
    """Valeur d'une cellule DREES : nombre, ou None (« ND », vide, autre texte)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "")
    return int(s) if s.isdigit() else None


CODE_DEP = re.compile(r"^(\d{2}|2A|2B|97\d|69D|69M)$")
# Territoires publiés par la DREES en plus des départements : Collectivité de Corse (depuis 2018, à la place de 2A et
# 2B), Nouveau Rhône et Métropole de Lyon (parties du Rhône ; en 2024, à la place du Rhône).
AUTRES_DREES = {"20": "Collectivité de Corse", "69D": "Nouveau Rhône", "69M": "Métropole de Lyon"}


def motif_nd(code: str, an: int) -> str:
    if code in ("2A", "2B"):
        return "publié pour la Collectivité de Corse (code 20)"
    if code in ("69D", "69M"):
        return "publié pour le Rhône entier (code 69)"
    if code == "69":
        return "publié pour le Nouveau Rhône (69D) et la Métropole de Lyon (69M)"
    return "non disponible à la source"


def _feuille(wb, titre: str) -> list[tuple]:
    return [tuple(r) for r in wb[titre].iter_rows(values_only=True)]


def _entete_annees(lignes: list[tuple]) -> tuple[int, dict[int, int]]:
    """(index de la ligne d'en-tête, {colonne: année}) : en-têtes « 2015 », « 2015 3 » (renvoi de note), 2024."""
    for i, r in enumerate(lignes[:10]):
        cols = {j: int(str(v)[:4]) for j, v in enumerate(r)
                if v is not None and re.match(r"^(19|20)\d\d(\s+\d)?$", str(v).strip())}
        if len(cols) >= 2:
            return i, cols
    raise SystemExit("classeur DREES : ligne des années introuvable (le classeur a changé de forme)")


def lire_drees() -> dict:
    """Places agréées par catégorie et département, agréments d'assistants maternels, séries nationales."""
    import openpyxl
    wb = openpyxl.load_workbook(chemin("drees_offre_accueil"), read_only=True, data_only=True)
    noms: dict[str, str] = {}
    dep_places: dict = {}     # (dep, an) -> {categorie: places}
    nd: list = []             # cellules non disponibles à la source
    for cat, _, feuille in DREES_CATEGORIES + [("agrements", "", "Tab33-PMI")]:
        lignes = _feuille(wb, feuille)
        h, cols = _entete_annees(lignes)
        for r in lignes[h + 1:]:
            code = str(r[1]).strip() if r[1] is not None else ""
            if not CODE_DEP.match(code):
                continue
            noms.setdefault(code, str(r[2]).strip())
            for j, an in cols.items():
                v = _cellule(r[j])
                if v is None:
                    nd.append({"departement": code, "annee": an, "donnee": cat, "valeur_source": r[j],
                               "motif": motif_nd(code, an)})
                dep_places.setdefault((code, an), {})[cat] = v
    total_2024: dict = {}
    lignes = _feuille(wb, "Tab17-PMI")
    entete = next(i for i, r in enumerate(lignes) if r[1] == "Code département")
    j_total = next(j for j, v in enumerate(lignes[entete]) if v and str(v).startswith("Total"))
    for r in lignes[entete + 1:]:
        code = str(r[1]).strip() if r[1] is not None else ""
        if CODE_DEP.match(code):
            total_2024[code] = _cellule(r[j_total])
    nat_places: dict = {}
    lignes = _feuille(wb, "Tab2-SL-Places-Nat")
    h, cols = _entete_annees(lignes)
    for r in lignes[h + 1:]:
        cle = DREES_NAT_PLACES.get(str(r[0]).strip()) if r[0] else None
        if cle:
            nat_places[cle] = {an: _cellule(r[j]) for j, an in sorted(cols.items())}
    nat_assmat: dict = {}
    lignes = _feuille(wb, "Tab3-SL-Assmat-Nat")
    h, cols = _entete_annees(lignes)
    for r in lignes[h + 1:]:
        lib = str(r[0] or "")
        for cle, debut in DREES_NAT_ASSMAT:
            if lib.startswith(debut):
                nat_assmat[cle] = {an: _cellule(r[j]) for j, an in sorted(cols.items())}
    manquants = [c for c in list(DREES_NAT_PLACES.values()) if c not in nat_places] + \
                [c for c, _ in DREES_NAT_ASSMAT if c not in nat_assmat]
    if manquants:
        raise SystemExit(f"classeur DREES : lignes introuvables {manquants} (le classeur a changé de forme)")
    return {"noms": noms, "dep": dep_places, "total_2024": total_2024, "nat_places": nat_places,
            "nat_assmat": nat_assmat, "non_disponibles": nd}


# --- Production ---------------------------------------------------------------------------------------------------

def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    if len(txt.encode()) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo")
    path.write_text(txt + "\n", encoding="utf-8")


def _ecart(sujet, annee, a_cle, a, b_cle, b, lecture, unite="places") -> dict | None:
    if a is None or b is None:
        return None
    return {"sujet": sujet, "annee": annee, "unite": unite, "source": a_cle, "valeur": a, "autre_source": b_cle,
            "autre_valeur": b, "ecart": round(a - b, 2),
            "ecart_pct": round((a - b) / b * 100, 1) if b else None, "lecture": lecture}


def _serie(d: dict, annees) -> dict[str, object]:
    return {str(a): d.get(a) for a in annees}


def produire() -> dict:
    manquants = [f"{c}:{f}" for c, s in SOURCES.items() for f in s["fichiers"] if not (BRUT / f).resolve().exists()]
    if manquants:
        raise SystemExit(f"sources absentes de data/lake : {manquants} (lancer `collecter`)")
    date = date_sources(DOMAINE)

    places = lire_cnaf_mode("cnaf_places", MODES_PLACES, "dep", False)
    places_h = lire_cnaf_mode("cnaf_places_historique", MODES_PLACES, "dep", False)
    taux = lire_cnaf_mode("cnaf_couverture", MODES_TAUX, "dep", False)
    taux_h = lire_cnaf_mode("cnaf_couverture_historique", MODES_TAUX, "dep", False)
    places_nat = lire_cnaf_mode("cnaf_places", MODES_PLACES, "nat", True)
    places_nat_h = lire_cnaf_mode("cnaf_places_historique", MODES_PLACES, "nat", True)
    taux_nat = lire_cnaf_mode("cnaf_couverture", MODES_TAUX, "nat", True)
    taux_nat_h = lire_cnaf_mode("cnaf_couverture_historique", MODES_TAUX, "nat", True)
    as_dep, as_nat = lire_action_sociale()
    cmg_nat = lire_cmg_national()
    cmg_dep, cmg_types = lire_cmg_departements()
    drees = lire_drees()

    # --- séries nationales ---
    an_places = sorted({a for (_, a) in places_nat})
    an_places_h = sorted({a for (_, a) in places_nat_h})

    def series_cnaf(d: dict, ans: list, modes: list) -> dict:
        return {m: {str(a): d[("FR", a)][m] for a in ans} for m, _, _ in modes}

    postes_cmg = []
    for pid, nom, lignes in CMG_POSTES:
        postes_cmg.append({"id": pid, "nom": nom, "lignes_source": lignes,
                           "montant_eur": {str(a): (sum(cmg_nat[l][a] for l in lignes)
                                                    if all(a in cmg_nat[l] for l in lignes) else None)
                                           for a in ANNEES},
                           "detail_eur": {l: _serie(cmg_nat[l], ANNEES) for l in lignes} if len(lignes) > 1 else None})
    non_ventile = {str(a): (cmg_nat[CMG_TOTAL][a] - sum(p["montant_eur"][str(a)] for p in postes_cmg)
                            if a in cmg_nat[CMG_TOTAL] and all(p["montant_eur"][str(a)] is not None for p in postes_cmg)
                            else None) for a in ANNEES}
    montants_mensuels = {a: round(sum(v["montant"] for (d, an), v in cmg_dep.items() if an == a))
                         for a in ANNEES_CMG}
    foyers_types_nat = {a: {t: sum(v[t] or 0 for (d, an), v in cmg_types.items() if an == a) for t, _ in CMG_TYPES}
                        for a in ANNEES_CMG}
    an_drees = sorted(drees["nat_places"]["total"])
    nationales = {
        "millesime": f"{ANNEES[0]} à {ANNEES[-1]}",
        "source": "CNAF (data.caf.fr) ; DREES, enquête Aide sociale (volet protection maternelle et infantile)",
        "unite": "euros ; places ; places pour 100 enfants de moins de 3 ans ; foyers",
        "date_sources": date,
        "definitions": DEFINITIONS,
        "cmg": {
            "nom": "Complément de libre choix du mode de garde (partie de la prestation d'accueil du jeune enfant)",
            "source": "cnaf_depenses", "perimetre": "tous régimes (CAF et MSA), France hors Mayotte, droits constatés",
            "montant_eur": _serie(cmg_nat[CMG_TOTAL], ANNEES), "ligne_source": CMG_TOTAL, "postes": postes_cmg,
            "non_ventile_eur": non_ventile,
            "non_ventile_note": "ligne totale de la source moins la somme de ses lignes de détail (arrondis et "
                                "lignes de faible montant de la source) ; non réparti entre les postes",
            "lien": LIENS[0],
            "montants_mensuels_caf_eur": {"source": "cnaf_cmg_montants", "valeurs": _serie(montants_mensuels, ANNEES_CMG),
                                          "methode": "somme des montants versés chaque mois par les CAF, tous "
                                                     "départements et codes hors département (champ CAF)",
                                          "note": RUPTURE_CMG},
            "foyers_decembre_par_type": {"source": "cnaf_cmg_foyers", "valeurs": {str(a): foyers_types_nat[a]
                                                                                  for a in ANNEES_CMG},
                                         "methode": "somme des lignes départementales du jeu (champ CAF), foyers "
                                                    "payés au titre de décembre ; un foyer qui recourt à deux modes "
                                                    "de garde compte dans les deux"},
        },
        "action_sociale": {
            "nom": "Action sociale des CAF pour la petite enfance (0 à 6 ans)", "source": "cnaf_action_sociale",
            "perimetre": "ensemble des CAF, ventilation fonctionnelle au 31 décembre",
            "petite_enfance_eur": {str(a): as_nat[a]["petite_enfance"] for a in sorted(as_nat)},
            "ensemble_action_sociale_eur": {str(a): as_nat[a]["ensemble_action_sociale"] for a in sorted(as_nat)},
            "postes": [{"id": i, "nom": n, "colonne_source": c,
                        "montant_eur": {str(a): as_nat[a][i] for a in sorted(as_nat)}} for i, c, n in AS_POSTES],
            "note": "la prestation de service unique versée aux gestionnaires de crèches est comprise dans les aides "
                    "au fonctionnement des structures partenaires sur fonds nationaux, avec les autres prestations "
                    "de service et bonus ; la source ne la sépare pas",
        },
        "places_cnaf": {
            "series": [
                {"id": "depuis_2022", "source": "cnaf_places", "annees": an_places,
                 "modes": series_cnaf(places_nat, an_places, MODES_PLACES)},
                {"id": "historique_2017_2022", "source": "cnaf_places_historique", "annees": an_places_h,
                 "modes": series_cnaf(places_nat_h, an_places_h, MODES_PLACES)},
            ],
            "modes": [{"id": i, "nom": n} for i, _, n in MODES_PLACES],
            "note": LECTURE_SERIES + " ; France hors Mayotte",
        },
        "couverture_cnaf": {
            "series": [
                {"id": "depuis_2022", "source": "cnaf_couverture", "annees": sorted({a for (_, a) in taux_nat}),
                 "modes": series_cnaf(taux_nat, sorted({a for (_, a) in taux_nat}), MODES_TAUX)},
                {"id": "historique_2017_2022", "source": "cnaf_couverture_historique",
                 "annees": sorted({a for (_, a) in taux_nat_h}),
                 "modes": series_cnaf(taux_nat_h, sorted({a for (_, a) in taux_nat_h}), MODES_TAUX)},
            ],
            "note": LECTURE_SERIES,
        },
        "places_drees": {
            "source": "drees_offre_accueil", "annees": an_drees,
            "categories": [{"id": c, "nom": n} for c, n, _ in DREES_CATEGORIES] + [{"id": "total", "nom":
                                                                                 "Ensemble des établissements"}],
            "places": {c: {str(a): v for a, v in drees["nat_places"][c].items()} for c in DREES_NAT_PLACES.values()},
            "assistants_maternels": {c: {str(a): v for a, v in drees["nat_assmat"][c].items()}
                                     for c, _ in DREES_NAT_ASSMAT},
            "note": "France hors Mayotte ; chiffres arrondis à la dizaine par la DREES ; nomenclature des "
                    "établissements modifiée en 2022 (réforme des modes d'accueil de 2021)",
        },
    }

    # --- écarts publiés ---
    ecarts = []
    for a in ANNEES:
        for cle, d in (("cnaf_places", places_nat), ("cnaf_places_historique", places_nat_h)):
            if ("FR", a) in d:
                ecarts.append(_ecart("places en crèche", a, cle, d[("FR", a)]["eaje"], "drees_offre_accueil",
                                     drees["nat_places"]["total"].get(a), LECTURE_PLACES))
                ecarts.append(_ecart("places chez une assistante maternelle", a, cle,
                                     d[("FR", a)]["assistantes_maternelles"], "drees_offre_accueil",
                                     drees["nat_assmat"]["places_potentielles"].get(a), LECTURE_ASSMAT))
    for a in sorted(set(an_places) & set(an_places_h)):
        ecarts.append(_ecart("ensemble des places offertes", a, "cnaf_places", places_nat[("FR", a)]["total"],
                             "cnaf_places_historique", places_nat_h[("FR", a)]["total"], LECTURE_SERIES))
        ecarts.append(_ecart("taux de couverture global", a, "cnaf_couverture", taux_nat[("FR", a)]["total"],
                             "cnaf_couverture_historique", taux_nat_h[("FR", a)]["total"], LECTURE_SERIES,
                             "places pour 100 enfants"))
    for a in ANNEES_CMG:
        ecarts.append(_ecart("complément de libre choix du mode de garde", a, "cnaf_depenses",
                             cmg_nat[CMG_TOTAL].get(a), "cnaf_cmg_montants", montants_mensuels[a], LECTURE_CMG,
                             "euros"))
    ecarts = [e for e in ecarts if e]

    # --- départements ---
    noms = {c: n for c, n in drees["noms"].items() if c not in AUTRES_DREES}
    noms.setdefault("976", "Mayotte")
    codes = sorted(noms, key=lambda c: (len(c) > 2 and c.startswith("97"), c))
    hors = sorted({d for (d, _) in list(places) + list(places_h) + list(cmg_dep) + list(cmg_types)} - set(codes))
    nd_par_an: dict = {}
    for x in drees["non_disponibles"]:
        nd_par_an.setdefault(x["annee"], []).append(x)
    fichiers = {}
    for an in ANNEES:
        deps = {}
        for code in codes:
            ligne: dict = {"nom": noms[code]}
            p = []
            if (code, an) in places:
                p.append({"serie": "depuis_2022", **places[(code, an)]})
            if (code, an) in places_h:
                p.append({"serie": "historique_2017_2022", **places_h[(code, an)]})
            ligne["places_cnaf"] = p
            t = []
            if (code, an) in taux:
                t.append({"serie": "depuis_2022", **taux[(code, an)]})
            if (code, an) in taux_h:
                t.append({"serie": "historique_2017_2022", **taux_h[(code, an)]})
            ligne["couverture_cnaf"] = t
            ligne["action_sociale_eur"] = as_dep.get((code, an))
            if an in ANNEES_CMG and (code, an) in cmg_dep:
                c = cmg_dep[(code, an)]
                complet = len(set(c["mois"])) == 12
                ligne["cmg"] = {"foyers_decembre": c["foyers_decembre"],
                                "montant_annuel_eur": round(c["montant"]) if complet else None,
                                "foyers_decembre_par_type": cmg_types.get((code, an))}
            else:
                ligne["cmg"] = None
            dr = drees["dep"].get((code, an))
            ligne["drees"] = None if dr is None else {
                "places_agreees": {c: dr.get(c) for c, _, _ in DREES_CATEGORIES},
                "places_agreees_total": drees["total_2024"].get(code) if an == 2024 else None,
                "agrements_assistants_maternels": dr.get("agrements")}
            deps[code] = ligne
        autres = {}
        for code, nom in AUTRES_DREES.items():
            dr = drees["dep"].get((code, an))
            if dr and any(v is not None for v in dr.values()):
                autres[code] = {"nom": nom, "places_agreees": {c: dr.get(c) for c, _, _ in DREES_CATEGORIES},
                                "places_agreees_total": drees["total_2024"].get(code) if an == 2024 else None,
                                "agrements_assistants_maternels": dr.get("agrements")}
        hd = {}
        for code in hors:
            h = {}
            pl = [{"serie": serie, "total": d[(code, an)]["total"]}
                  for serie, d in (("depuis_2022", places), ("historique_2017_2022", places_h)) if (code, an) in d]
            if pl:
                h["places_cnaf"] = pl
            if an in ANNEES_CMG and (code, an) in cmg_dep:
                c = cmg_dep[(code, an)]
                h["cmg_foyers_decembre"] = c["foyers_decembre"]
                h["cmg_montant_annuel_eur"] = round(c["montant"]) if len(set(c["mois"])) == 12 else None
            if h:
                hd[code] = h
        notes = ["Mayotte : hors champ des places et taux de la CNAF et des tableaux de la DREES (null)",
                 "codes hors département de la CNAF : 977 Saint-Barthélemy, 978 Saint-Martin, 99 et XX ou XXX "
                 "(résidence inconnue ou à l'étranger)",
                 "un montant annuel du complément est null quand un mois manque à la source",
                 "DREES : la Corse est publiée en une seule collectivité (code 20) depuis 2018, et le Rhône en "
                 "deux parties (Nouveau Rhône 69D, Métropole de Lyon 69M) ; ces territoires sont dans "
                 "drees_autres_territoires, jamais additionnés aux départements"]
        if an == 2025:
            notes.append(RUPTURE_CMG)
        if an == 2022:
            notes.append(LECTURE_SERIES + " : les deux séries sont données pour 2022")
        nd = nd_par_an.get(an, [])
        doc = {
            "millesime": f"Année {an}",
            "source": "CNAF (places, taux de couverture, action sociale, complément de libre choix du mode de garde) ; "
                      "DREES (places agréées, agréments d'assistants maternels)",
            "unite": "places ; places pour 100 enfants de moins de 3 ans ; euros ; foyers",
            "annee": an,
            "definitions": DEFINITIONS,
            "modes_places": [{"id": i, "nom": n} for i, _, n in MODES_PLACES],
            "postes_action_sociale": [{"id": i, "nom": n} for i, _, n in AS_POSTES] + [
                {"id": "petite_enfance", "nom": "Ensemble de l'action sociale petite enfance"},
                {"id": "ensemble_action_sociale", "nom": "Ensemble de l'action sociale de la caisse (toutes "
                                                          "fonctions)"}],
            "types_cmg": [{"id": "assistantes_maternelles", "nom": "Emploi direct d'une assistante maternelle"},
                          {"id": "garde_domicile", "nom": "Emploi direct d'une garde à domicile"},
                          {"id": "structure_hors_micro_creche", "nom": "Association ou entreprise"},
                          {"id": "micro_creche", "nom": "Micro-crèche"}],
            "categories_drees": [{"id": c, "nom": n} for c, n, _ in DREES_CATEGORIES],
            "departements": deps,
            "hors_departements": hd,
            "drees_autres_territoires": autres,
            "non_disponibles": [{k: (str(v) if k == "valeur_source" and v is not None else v) for k, v in x.items()}
                                for x in nd],
            "notes": notes,
        }
        rel = f"petite_enfance/departements/{an}.json"
        dump(SITE / rel, doc)
        fichiers[str(an)] = rel

    index = {
        "millesime": nationales["millesime"],
        "source": nationales["source"],
        "unite": nationales["unite"],
        "date_sources": date,
        "annees": ANNEES,
        "derniere_annee": ANNEES[-1],
        "dispositifs": [
            {"id": "cmg", "nom": nationales["cmg"]["nom"], "financeur": "Sécurité sociale, branche famille (CNAF ; "
             "MSA pour le régime agricole)", "sources": ["cnaf_depenses", "cnaf_cmg_montants", "cnaf_cmg_foyers"],
             "annees_departements": ANNEES_CMG, "liens": [LIENS[0]]},
            {"id": "action_sociale", "nom": nationales["action_sociale"]["nom"], "financeur": "Sécurité sociale, "
             "branche famille : fonds national d'action sociale et fonds locaux des CAF",
             "sources": ["cnaf_action_sociale"], "annees_departements": sorted(as_nat), "liens": [LIENS[1]]},
            {"id": "places", "nom": "Places d'accueil offertes aux enfants de moins de 3 ans",
             "sources": ["cnaf_places", "cnaf_places_historique", "cnaf_couverture", "cnaf_couverture_historique"],
             "annees_departements": sorted(set(an_places) | set(an_places_h))},
            {"id": "places_agreees", "nom": "Places agréées en établissement et agréments d'assistants maternels",
             "sources": ["drees_offre_accueil"],
             "annees_departements": sorted({a for (_, a) in drees["dep"] if a in ANNEES})},
        ],
        "fichiers": {"nationales": "petite_enfance/nationales.json", "departements": fichiers},
        "chiffres_cles": {
            "annee": 2024,
            "cmg_eur": cmg_nat[CMG_TOTAL].get(2024),
            "action_sociale_petite_enfance_eur": as_nat.get(2024, {}).get("petite_enfance"),
            "places_cnaf": places_nat.get(("FR", 2023), {}).get("total"), "places_cnaf_annee": 2023,
            "couverture_cnaf": taux_nat.get(("FR", 2023), {}).get("total"), "couverture_cnaf_annee": 2023,
            "places_agreees_drees": drees["nat_places"]["total"].get(2024),
            "note": "chaque chiffre garde sa source et son année ; ils ne s'additionnent pas",
        },
        "ecarts": ecarts,
        "liens": LIENS,
        "couverture_departementale": {"departements": len(codes), "codes_hors_departement": hors,
                                      "cellules_non_disponibles_drees": len(drees["non_disponibles"])},
        "regle": "deux sources ne sont jamais additionnées ; les écarts sont publiés tels quels ; les deux séries de "
                 "la CNAF ne sont pas raccordées ; une valeur absente à la source reste null, jamais 0 ; le "
                 "complément de libre choix du mode de garde est déjà compté dans la prestation d'accueil du jeune "
                 "enfant (axe prestations) et ne s'y ajoute pas",
        "sources": {k: {kk: vv for kk, vv in v.items() if kk != "fichiers"} for k, v in SOURCES.items()},
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(SORTIE / "nationales.json", nationales)
    dump(SORTIE / "index.json", index)
    print(f"petite_enfance : {len(codes)} départements, {len(ANNEES)} années, {len(ecarts)} écarts publiés")
    return index


# --- Collecte ------------------------------------------------------------------------------------------------------

def collecter(forcer: bool = False) -> int:
    """Collecte par collecte/collecte.py (reprises, manifeste, aucun contournement d'un refus d'accès)."""
    base = [sys.executable, str(ROOT / "collecte" / "collecte.py")] + (["--force"] if forcer else [])
    codes = [subprocess.call(base + ["--domaine", DOMAINE]), subprocess.call(base + ["secu_caf_s_ben_dep"])]
    return max(codes)


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
