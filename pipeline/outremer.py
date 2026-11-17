"""Collectivités d'outre-mer : Saint-Pierre-et-Miquelon (975), Saint-Barthélemy (977), Saint-Martin (978),
Wallis-et-Futuna (986), Polynésie française (987), Nouvelle-Calédonie (988).

Complète « Près de chez moi » (pipeline/local.py, 101 départements, lu en lecture seule) pour les six territoires
que local.py ne couvre pas. Même format par territoire : communes (population), dotations de l'État par commune et
par collectivité (mêmes clés que local/dotations/). S'y ajoutent ce que les sources ouvertes publient par
territoire : crédits de l'État (Cour des comptes 2018-2020 ; document de politique transversale Outre-mer du
PLF 2026) et, pour la Nouvelle-Calédonie, le budget de la collectivité, de ses établissements publics et le
rendement de ses impôts, publiés en francs CFP.

Entrées : entrepôt brut data/lake/outremer/outremer/ (non versionné), collecté par collecte/collecte.py (entrée
« outremer » de collecte/catalogue.json, tracée dans data/lake/manifest.json) :
  geo_<code>.json                    geo.api.gouv.fr, communes du territoire (code officiel géographique, population)
  dotations_communes_<code>.csv      OFGL « dotations-communes » (DGCL, montants notifiés), une extraction par code
  dotations_collectivites.csv        OFGL « dotations-departements », lignes des six codes (975 et 978 publiés)
  dotations_intercommunalites.csv    OFGL « dotations-gfp », lignes des six codes (987 publié)
  nc_budget.csv, nc_epa.csv, nc_epic.csv, nc_impots.csv (+ .meta.json)   data.gouv.nc, DBAF, francs CFP
  ccomptes_financement_etat_outremer.zip   Cour des comptes, données du rapport de mai 2022 (ODbL)
  dpt2026_outremer.pdf               annexe au PLF 2026, document de politique transversale Outre-mer
Sorties (site/data/outremer/, chacune < 5 Mo, avec `millesime` et `source`) :
  index.json            territoires, blocs et statut de publication, parité, sources, écarts, recherche préalable
  <code>.json           un territoire : communes, dotations, crédits de l'État, statut de chaque bloc
  988_budget.json       Nouvelle-Calédonie : budgets de la collectivité par chapitre, établissements publics,
                        rendement des impôts (francs CFP et euros)

Commandes :
  python pipeline/outremer.py collecter   # réseau, par collecte/collecte.py ; un refus 401/403/429 est noté
  python pipeline/outremer.py produire    # sans réseau, reproductible octet pour octet
  python pipeline/outremer.py             # les deux

Règles :
  - un bloc que les sources ouvertes ne publient pas porte le statut « non publié en données ouvertes » et un
    motif ; il n'est jamais vide, jamais estimé ;
  - un montant en francs CFP est publié deux fois : montant d'origine (`devise_source` = « XPF ») et montant en
    euros à la parité fixe 1 € = 119,33174 XPF ;
  - une valeur absente à la source est null, jamais 0 ; un 0 publié reste 0 ;
  - deux sources ne sont jamais additionnées ; quand elles décrivent le même argent, l'écart est publié ;
  - aucune personne physique : les chapitres d'opérations individualisées du budget calédonien (libellés au nom
    d'entreprises, parfois individuelles) sont agrégés sans libellé ; articles et sous-fonctions ne sont pas lus ;
  - le tableau par territoire du document de politique transversale n'est publié que si l'extraction du PDF
    est vérifiée (somme des programmes = mission, somme des missions = total, pour chaque colonne, à l'arrondi
    de la source près).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "outremer" / "outremer"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "outremer"
ID_CATALOGUE = "outremer"
MAX_OCTETS = 5_000_000

# Parité fixe du franc CFP : 1 000 XPF = 8,38 € (arrêté du 31 décembre 1998), soit 1 € = 119,33174 XPF.
XPF_PAR_EUR = 119.33174
PUBLIE = "publié"
NON_PUBLIE = "non publié en données ouvertes"

TERRITOIRES = {
    "975": {"nom": "Saint-Pierre-et-Miquelon", "monnaie": "EUR",
            "statut_juridique": "collectivité d'outre-mer (article 74 de la Constitution)"},
    "977": {"nom": "Saint-Barthélemy", "monnaie": "EUR",
            "statut_juridique": "collectivité d'outre-mer (article 74 de la Constitution)"},
    "978": {"nom": "Saint-Martin", "monnaie": "EUR",
            "statut_juridique": "collectivité d'outre-mer (article 74 de la Constitution)"},
    "986": {"nom": "Wallis-et-Futuna", "monnaie": "XPF",
            "statut_juridique": "collectivité d'outre-mer (article 74 de la Constitution)"},
    "987": {"nom": "Polynésie française", "monnaie": "XPF",
            "statut_juridique": "collectivité d'outre-mer (article 74 de la Constitution)"},
    "988": {"nom": "Nouvelle-Calédonie", "monnaie": "XPF",
            "statut_juridique": "collectivité à statut particulier (titre XIII de la Constitution)"},
}
CODES = list(TERRITOIRES)

BLOCS = {
    "geo": "communes du code officiel géographique et population",
    "dotations_communes": "dotations de l'État notifiées à chaque commune (DGF et composantes)",
    "dotations_intercommunalites": "dotations de l'État notifiées aux intercommunalités (DGF et composantes)",
    "dotations_collectivite": "dotations de l'État notifiées à la collectivité (DGF et composantes)",
    "credits_etat_2018_2020": "crédits de l'État par territoire, lois de finances et exécution 2018 à 2020 "
                              "(Cour des comptes)",
    "credits_etat_plf2026": "crédits de l'État par territoire, mission et programme : exécution 2024, loi de "
                            "finances 2025, projet de loi de finances 2026 (document de politique transversale)",
    "budget_collectivite": "budget de la collectivité (dépenses et recettes)",
    "budget_communes": "budget de chaque commune (dépenses et recettes)",
    "impots_territoriaux": "rendement des impôts votés par la collectivité",
}

# --- Sources ---------------------------------------------------------------------------------------------------------

OFGL = "https://data.ofgl.fr/explore/dataset"
NC = "https://data.gouv.nc/explore/dataset"
SOURCES = {
    "geo": {
        "titre": "API Découpage administratif (geo.api.gouv.fr) : communes des six territoires, population municipale",
        "producteur": "Insee (code officiel géographique, populations légales), DINUM",
        "url": "https://geo.api.gouv.fr/communes?codeDepartement=<code>", "page": "https://geo.api.gouv.fr/",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel",
    },
    "ofgl_dotations_communes": {
        "titre": "OFGL, « Dotations des communes » (dotations-communes) : montants notifiés par la DGCL, par commune",
        "producteur": "DGCL, mis en ligne par l'OFGL", "url": f"{OFGL}/dotations-communes/",
        "page": f"{OFGL}/dotations-communes/", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (975, 986, 987, 988 ; aucune ligne pour 977 et 978)",
    },
    "ofgl_dotations_collectivites": {
        "titre": "OFGL, « Dotations des départements » (dotations-departements) : montants notifiés par la DGCL aux "
                 "collectivités de Saint-Pierre-et-Miquelon et de Saint-Martin",
        "producteur": "DGCL, mis en ligne par l'OFGL", "url": f"{OFGL}/dotations-departements/",
        "page": f"{OFGL}/dotations-departements/", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (975 et 978 ; aucune ligne pour 977, 986, 987, 988)",
    },
    "ofgl_dotations_intercommunalites": {
        "titre": "OFGL, « Dotations des groupements à fiscalité propre » (dotations-gfp) : montants notifiés par la "
                 "DGCL aux communautés de communes de la Polynésie française",
        "producteur": "DGCL, mis en ligne par l'OFGL", "url": f"{OFGL}/dotations-gfp/",
        "page": f"{OFGL}/dotations-gfp/", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (987 ; aucune ligne pour les cinq autres codes)",
    },
    "nc_budget": {
        "titre": "Gouvernement de la Nouvelle-Calédonie, « Situation budgétaire de la Nouvelle-Calédonie depuis "
                 "2012 » : budget total et réalisé par budget, sens, section, chapitre et article, en francs CFP",
        "producteur": "Direction du budget et des affaires financières de la Nouvelle-Calédonie (DBAF)",
        "url": f"{NC}/situation-budgetaire-de-la-nouvelle-caledonie-depuis-2012/",
        "page": f"{NC}/situation-budgetaire-de-la-nouvelle-caledonie-depuis-2012/",
        "licence": "Licence Ouverte 2.0", "fichier_meta": "nc_budget.meta.json",
        "verdict": "à adapter (chapitres seulement ; opérations individualisées agrégées ; conversion en euros)",
    },
    "nc_epa": {
        "titre": "Gouvernement de la Nouvelle-Calédonie, « Situation budgétaire des établissements publics "
                 "administratifs (EPA) de la Nouvelle-Calédonie depuis 2012 », en francs CFP",
        "producteur": "Direction du budget et des affaires financières de la Nouvelle-Calédonie (DBAF)",
        "url": f"{NC}/situation-budgetaire-epa-depuis-2012/", "page": f"{NC}/situation-budgetaire-epa-depuis-2012/",
        "licence": "Licence Ouverte 2.0", "fichier_meta": "nc_epa.meta.json",
        "verdict": "à adapter (totaux par établissement, sens et section ; conversion en euros)",
    },
    "nc_epic": {
        "titre": "Gouvernement de la Nouvelle-Calédonie, « Situation budgétaire des établissements publics à "
                 "caractère industriel et commercial (EPIC) de la Nouvelle-Calédonie depuis 2012 », en francs CFP",
        "producteur": "Direction du budget et des affaires financières de la Nouvelle-Calédonie (DBAF)",
        "url": f"{NC}/situation-budgetaire-epic-depuis-2012/", "page": f"{NC}/situation-budgetaire-epic-depuis-2012/",
        "licence": "Licence Ouverte 2.0", "fichier_meta": "nc_epic.meta.json",
        "verdict": "à adapter (totaux par établissement, sens et section ; conversion en euros)",
    },
    "nc_impots": {
        "titre": "Gouvernement de la Nouvelle-Calédonie, « Rendement des impôts depuis 2010 » : montant des titres "
                 "émis par impôt et par année, en francs CFP",
        "producteur": "Gouvernement de la Nouvelle-Calédonie",
        "url": f"{NC}/rendement-des-impots-depuis-2010/", "page": f"{NC}/rendement-des-impots-depuis-2010/",
        "licence": "Licence Ouverte 2.0", "fichier_meta": "nc_impots.meta.json",
        "verdict": "réutilisable tel quel (conversion en euros ajoutée)",
    },
    "cour_des_comptes": {
        "titre": "Cour des comptes, « Les financements de l'État en outre-mer » (mai 2022), données du rapport : "
                 "tableau « Territoires » (lois de finances initiales et exécution 2018 à 2020, par territoire)",
        "producteur": "Cour des comptes",
        "url": "https://www.ccomptes.fr/system/files/2022-05/20220524-donnees-financement-Etat-outremer.zip",
        "page": "https://www.ccomptes.fr/fr/publications/les-financements-de-letat-en-outre-mer",
        "licence": "ODbL 1.0 (partage à l'identique)",
        "verdict": "réutilisable tel quel (lignes des six territoires)",
    },
    "dpt_plf2026": {
        "titre": "Annexe au projet de loi de finances pour 2026, document de politique transversale « Outre-mer » : "
                 "tableaux « Effort budgétaire et financier de l'État » par territoire, mission et programme",
        "producteur": "Direction générale des outre-mer, direction du budget",
        "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1090079/file/4-DPT2026_OutreMer.pdf",
        "page": "https://www.budget.gouv.fr/documentation/documents-budgetaires/exercice-2026",
        "licence": "document budgétaire public (annexe au projet de loi de finances)",
        "verdict": "à adapter (PDF : lecture par position des mots, publiée seulement si les sommes se vérifient)",
    },
}

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "conclusion": "Les producteurs publient déjà les agrégats repris ici (API geo.api.gouv.fr, portails Opendatasoft "
                  "de l'OFGL et du gouvernement de la Nouvelle-Calédonie, fichiers de la Cour des comptes). Aucun "
                  "dépôt public ne réunit les six collectivités d'outre-mer dans un même format : module écrit pour "
                  "le dépôt, sur le modèle de pipeline/local.py (clés des dotations) et de pipeline/prestations.py.",
    "trouvailles": [
        {"nom": "geo.api.gouv.fr, communes par code de collectivité d'outre-mer", "url": "https://geo.api.gouv.fr/",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "code officiel géographique en vigueur",
         "verdict": "réutilisable tel quel"},
        {"nom": "OFGL, dotations-communes, dotations-gfp et dotations-departements", "url": "https://data.ofgl.fr/",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-09-22", "verdict": "réutilisable tel quel"},
        {"nom": "data.gouv.nc, situation budgétaire de la Nouvelle-Calédonie, des EPA et des EPIC, rendement des "
                "impôts", "url": "https://data.gouv.nc/", "licence": "Licence Ouverte 2.0",
         "mise_a_jour": "2026-10-31", "verdict": "à adapter (francs CFP, chapitres nominatifs agrégés)"},
        {"nom": "Cour des comptes, données du rapport « Les financements de l'État en outre-mer »",
         "url": SOURCES["cour_des_comptes"]["page"], "licence": "ODbL 1.0", "mise_a_jour": "2022-05-25",
         "verdict": "réutilisable tel quel"},
        {"nom": "Document de politique transversale Outre-mer, PLF 2026 (PDF)", "url": SOURCES["dpt_plf2026"]["url"],
         "licence": "document budgétaire public", "mise_a_jour": "PLF 2026 (octobre 2025)",
         "verdict": "à adapter (aucun jeu ouvert équivalent : tableaux lus dans le PDF et vérifiés)"},
        {"nom": "pipeline/local.py du dépôt (clés des dotations, format des communes)",
         "url": "https://github.com/MoonEyes/Ou-vont-mes-impots", "licence": "licence du dépôt",
         "dernier_commit": "2026-11-17", "verdict": "à adapter (mêmes clés, lu en lecture seule, non modifié)"},
        {"nom": "adriens/odata-data-gouv-nc (catalogue des jeux de data.gouv.nc)",
         "url": "https://github.com/adriens/odata-data-gouv-nc", "licence": "non précisée",
         "dernier_commit": "2024-03-21", "verdict": "inspiration seulement (liste de jeux, aucun traitement budgétaire)"},
        {"nom": "adriens/nodes23-data (catalogue de data.gouv.nc en graphe)",
         "url": "https://github.com/adriens/nodes23-data", "licence": "non précisée",
         "dernier_commit": "2023-09-21", "verdict": "inspiration seulement"},
        {"nom": "Recherches GitHub « situation-budgetaire-de-la-nouvelle-caledonie-depuis-2012 », « outre-mer "
                "budget dotations », « 119.33174 XPF »", "url": "https://github.com/search", "licence": None,
         "dernier_commit": None, "verdict": "aucun autre dépôt pertinent"},
        {"nom": "Recherche de jeux ouverts de budget : Polynésie française (service-public.pf : brochures PDF), "
                "Saint-Barthélemy (organisation data.gouv.fr sans jeu), comptes des collectivités d'outre-mer dans "
                "les bases de l'OFGL", "url": "https://www.data.gouv.fr/organizations/collectivite-de-saint-barthelemy/datasets",
         "licence": None, "mise_a_jour": "2026-11-17", "verdict": "aucun jeu ouvert trouvé : blocs déclarés non publiés"},
    ],
}

MOTIFS_NON_PUBLIE = {
    "budget_communes": "les comptes des communes de ce territoire ne figurent dans aucune base ouverte consultée le "
                       "17/11/2026 (bases de l'OFGL ofgl-base-communes et ofgl-base-communes-consolidee : aucune "
                       "ligne pour ce code)",
    "budget_collectivite": "aucun jeu ouvert du budget de cette collectivité trouvé le 17/11/2026 (bases de l'OFGL "
                           "des départements et des régions : aucune ligne pour ce code ; data.gouv.fr : aucun jeu)",
    "budget_collectivite_987": "le budget de la Polynésie française est diffusé en documents PDF (brochures de la "
                               "direction du budget et des finances, service-public.pf) ; aucun jeu ouvert "
                               "structuré trouvé le 17/11/2026",
    "budget_collectivite_977": "l'organisation « Collectivité de Saint-Barthélemy » de data.gouv.fr ne publiait aucun "
                               "jeu le 17/11/2026 ; aucune ligne pour ce code dans les bases de l'OFGL",
    "impots_territoriaux": "aucun jeu ouvert du rendement des impôts de cette collectivité trouvé le 17/11/2026",
    "dotations_communes": "aucune ligne pour ce code dans le jeu OFGL dotations-communes",
    "dotations_collectivite": "aucune ligne pour ce code dans le jeu OFGL dotations-departements",
    "dotations_intercommunalites": "aucune ligne pour ce code dans le jeu OFGL dotations-gfp",
}

# Variables OFGL -> clés publiées : celles de pipeline/local.py (DOT_COMMUNES, DOT_DEP), plus la dotation
# particulière « élu local », présente pour ces territoires.
DOT_COMMUNES = {
    "Montant Dotation DGF": "dgf_totale", "Montant Dotation forfaitaire": "dgf_forfaitaire",
    "Montant Dotation DSU": "dgf_dsu", "Montant Dotation DSR": "dgf_dsr", "Montant Dotation DNP": "dgf_dnp",
    "Montant Dotation Commune nouvelle": "dgf_commune_nouvelle", "Montant Dotation DACOM": "dgf_dacom",
    "Montant dotation biodiversité et aménités rurales": "dotation_biodiversite",
    "Montant de DCRTP de la commune": "dcrtp", "Montant du prélèvement DILICO": "dilico_prelevement",
    "Montant du reversement DILICO N-1": "dilico_reversement", "Dotation DPEL": "dpel"}
DOT_COLLECTIVITE = {
    "Montant DGF notifiée totale": "dgf_totale", "Montant Dotation forfaitaire": "dgf_forfaitaire",
    "Montant Dotation de compensation": "dgf_compensation",
    "Montant Dotation de péréquation urbaine": "dgf_perequation_urbaine",
    "Montant Dotation de fonctionnement minimale": "dgf_fonctionnement_minimale",
    "Montant de la DCRTP": "dcrtp", "Montant du prélèvement DILICO": "dilico_prelevement",
    "Montant du reversement DILICO N-1": "dilico_reversement"}
DOT_INTERCO = {
    "Montant DGF": "dgf_totale", "Montant Dotation intercommunalité": "dgf_intercommunalite",
    "Montant Dotation de compensation": "dgf_compensation", "Montant de la DCTP des EPCI": "dctp",
    "Montant du prélèvement DILICO": "dilico_prelevement", "Montant de reversement DILICO N-1": "dilico_reversement"}
RRF_COMMUNES = "Recettes réelles de fonctionnement des communes N-2"
RRF_COLLECTIVITE = "Recettes Réelles de Fonctionnement (comptes de gestion N-2)"
NOTE_DOTATIONS = ("dgf_totale = dotation globale de fonctionnement notifiée ; dgf_dacom = dotation d'aménagement des "
                  "communes d'outre-mer ; dpel = dotation particulière « élu local ». Montants notifiés par la DGCL, "
                  "en euros, y compris pour les territoires dont la monnaie est le franc CFP.")
NOTE_RRF = ("recettes réelles de fonctionnement du compte de gestion de l'année N-2, publiées par la DGCL parmi les "
            "critères de calcul des dotations de l'année N : seul agrégat de comptes publié pour ces collectivités ; "
            "ce n'est pas un budget détaillé")

# Budgets de la Nouvelle-Calédonie : le jeu publie le code sans libellé ; libellés des documents budgétaires de la
# DBAF (rapport du budget primitif annexe de reversement 2020 : « BUDGET : 02 Budget reverse », « BUDGET ANNEXE 03 :
# Budget reparti »).
NC_BUDGETS = {
    "01": "budget principal (budget propre de la Nouvelle-Calédonie)",
    "02": "budget annexe de reversement (taxes affectées, centimes additionnels et fonds de concours reversés)",
    "03": "budget annexe de répartition (dotations aux provinces et aux communes)",
}
NC_BUDGETS_SOURCE = "https://dbaf.gouv.nc/sites/default/files/documents/rapport_bp_2020_b02.pdf"
COLONNES_XPF = ["budget_total_xpf", "realise_xpf", "budget_total_eur", "realise_eur"]

# Document de politique transversale : colonnes des tableaux par territoire et décalage (points) de leur bord droit
# par rapport au bord droit de la dernière colonne.
DPT_COLONNES = ["execution_2024_ae", "execution_2024_cp", "lfi_2025_ae", "lfi_2025_cp", "plf_2026_ae", "plf_2026_cp"]
DPT_DECALAGES = [244, 193, 145, 97, 49, 0]
DPT_TITRES = {"SAINT-PIERRE-ET-MIQUELON": "975", "SAINT-BARTHELEMY": "977", "SAINT-MARTIN": "978",
              "WALLIS-ET-FUTUNA": "986", "POLYNESIE FRANCAISE": "987", "NOUVELLE-CALEDONIE": "988"}
DPT_AUTRES_TITRES = {"GUADELOUPE", "MARTINIQUE", "GUYANE", "LA REUNION", "MAYOTTE", "CREDITS NON REPARTIS", "TAAF",
                     "TERRES AUSTRALES ET ANTARCTIQUES FRANCAISES"}
DPT_PSR_DGF = "3101"
CONTROLE_DPT = ("somme des programmes = mission et somme des missions = total général, pour chacune des six colonnes, "
                "à l'arrondi de la source près (1 € par ligne additionnée)")


# --- Utilitaires -----------------------------------------------------------------------------------------------------

def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse 5 Mo ({n} octets) : découper")
    tmp = path.with_suffix(".part")
    tmp.write_text(texte + "\n", encoding="utf-8")
    tmp.replace(path)
    return n


def sans_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def cle_nom(s: str) -> str:
    """Nom de territoire comparable d'une source à l'autre (casse, accents, tirets, apostrophes)."""
    return re.sub(r"[^A-Z]", "", sans_accents(s).upper())


def propre(v) -> str:
    """Libellé nettoyé : espaces insécables et multiples, apostrophes doublées par l'export."""
    s = unicodedata.normalize("NFC", str(v or "")).replace(" ", " ").replace(" ", " ").replace("''", "'")
    return re.sub(r"\s+", " ", s).strip()


def num(v):
    """Nombre de la source ; vide, « - » ou non numérique : None (jamais 0)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    if s in ("", "-", "nc", "NC", "nd", "ND"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def entier(v):
    return None if v is None else int(round(v))


def xpf_en_eur(v):
    """Francs CFP -> euros à la parité fixe, arrondi à l'euro ; None reste None."""
    return None if v is None else int(round(v / XPF_PAR_EUR))


def lire_csv(nom: str) -> list[dict]:
    p = BRUT / nom
    if not p.exists():
        raise SystemExit(f"source absente : {p} (lancer `python pipeline/outremer.py collecter`)")
    return list(csv.DictReader(io.StringIO(p.read_bytes().decode("utf-8-sig")), delimiter=";"))


def meta_ods(nom: str) -> dict:
    """Métadonnées d'un jeu Opendatasoft (date de modification, licence), None si le fichier manque."""
    p = BRUT / nom
    try:
        m = json.loads(p.read_text(encoding="utf-8"))["metas"]["default"]
    except (OSError, ValueError, KeyError):
        return {}
    return {"modifie_le": str(m.get("modified") or "")[:10] or None, "licence": m.get("license"),
            "enregistrements": m.get("records_count")}


# --- 1. Géographie ---------------------------------------------------------------------------------------------------

def lire_geo(code: str) -> dict:
    """{insee: {nom, population, siren, epci}} trié par code ; siren et epci : null quand l'API ne les publie pas."""
    p = BRUT / f"geo_{code}.json"
    if not p.exists():
        raise SystemExit(f"source absente : {p}")
    res = {}
    for c in sorted(json.loads(p.read_text(encoding="utf-8")), key=lambda x: x["code"]):
        res[c["code"]] = {"nom": c["nom"], "population": c.get("population"), "siren": c.get("siren"),
                          "epci": c.get("codeEpci"), "territoire": code}
    return res


# --- 2. Dotations ----------------------------------------------------------------------------------------------------

def nom_ofgl(v: str) -> str:
    """« HIENGHENE (988) » -> « HIENGHENE »."""
    return re.sub(r"\s*\(\d+\)\s*$", "", propre(v))


def lire_dotations_communes(code: str) -> dict:
    """{'communes': {insee: {nom, eur: {annee: {cle: euros}}}}, 'rrf': {insee: {annee: euros}}, 'annees': [...]}."""
    communes, rrf, annees = {}, {}, set()
    for r in lire_csv(f"dotations_communes_{code}.csv"):
        if r["unite"] != "euros":
            continue
        v, a, insee = num(r["valeur"]), str(r["exercice"])[:4], r["code_insee"]
        if v is None:
            continue
        if r["variable"] == RRF_COMMUNES:
            rrf.setdefault(insee, {})[a] = entier(v)
            continue
        k = DOT_COMMUNES.get(r["variable"])
        if k is None:
            continue
        annees.add(a)
        x = communes.setdefault(insee, {"nom": nom_ofgl(r["commune"]), "eur": {}})
        x["eur"].setdefault(a, {})[k] = entier(v)
    tri = lambda d: {k: d[k] for k in sorted(d)}  # noqa: E731
    communes = {i: {"nom": communes[i]["nom"], "eur": {a: tri(communes[i]["eur"][a]) for a in sorted(communes[i]["eur"])}}
                for i in sorted(communes)}
    return {"communes": communes, "rrf": {i: tri(rrf[i]) for i in sorted(rrf)}, "annees": sorted(annees)}


def lire_dotations_collectivites() -> dict:
    """{code: {'nom', 'eur': {annee: {cle: euros}}, 'rrf': {annee: euros}, 'population_dgf': {annee: n}}}."""
    res: dict = {}
    for r in lire_csv("dotations_collectivites.csv"):
        code, a, v = r["code_departement"], str(r["exercice"])[:4], num(r["valeur"])
        if code not in TERRITOIRES or v is None:
            continue
        x = res.setdefault(code, {"nom": propre(r["nom_departement"]), "eur": {}, "rrf": {}, "population_dgf": {}})
        if r["variable"] == "Population DGF" and r["unite"] == "habitants":
            x["population_dgf"][a] = entier(v)
        elif r["unite"] == "euros" and r["variable"] == RRF_COLLECTIVITE:
            x["rrf"][a] = entier(v)
        elif r["unite"] == "euros" and r["variable"] in DOT_COLLECTIVITE:
            x["eur"].setdefault(a, {})[DOT_COLLECTIVITE[r["variable"]]] = entier(v)
    for x in res.values():
        x["eur"] = {a: {k: x["eur"][a][k] for k in sorted(x["eur"][a])} for a in sorted(x["eur"])}
        x["rrf"] = {a: x["rrf"][a] for a in sorted(x["rrf"])}
        x["population_dgf"] = {a: x["population_dgf"][a] for a in sorted(x["population_dgf"])}
    return res


def lire_dotations_intercommunalites() -> dict:
    """{code: {'epci': {siren: {nom, eur: {annee: {cle: euros}}}}, 'annees': [...]}} (lignes des groupements)."""
    res: dict = {}
    for r in lire_csv("dotations_intercommunalites.csv"):
        code, k, v = r["code_departement"], DOT_INTERCO.get(r["variable"]), num(r["valeur"])
        if code not in TERRITOIRES or r["unite"] != "euros" or k is None or v is None:
            continue
        a = str(r["exercice"])[:4]
        x = res.setdefault(code, {"epci": {}, "annees": set()})
        x["annees"].add(a)
        e = x["epci"].setdefault(r["siren"], {"nom": nom_ofgl(r["nom_epci"]), "eur": {}})
        e["eur"].setdefault(a, {})[k] = entier(v)
    for x in res.values():
        x["annees"] = sorted(x["annees"])
        x["epci"] = {s: {"nom": x["epci"][s]["nom"],
                         "eur": {a: {k: x["epci"][s]["eur"][a][k] for k in sorted(x["epci"][s]["eur"][a])}
                                 for a in sorted(x["epci"][s]["eur"])}} for s in sorted(x["epci"])}
    return res


# --- 3. Cour des comptes : financements de l'État 2018-2020 ----------------------------------------------------------

def lire_cour_des_comptes() -> dict:
    """{code: {'annees': {annee: {lfi_ae_eur, lfi_cp_eur, execution_ae_eur, execution_cp_eur}}, population...}}.

    Tableau « Territoires » : bloc de gauche (territoire, année, LFI AE/CP, exécution AE/CP), bloc de droite
    (territoire, population au 1er janvier 2018, moins de 60 ans, CP exécutés par habitant 2018 à 2020).
    L'en-tête porte « (En M€) » ; les montants sont en euros : vérifié par CP exécutés 2018 / population = montant
    par habitant publié (arrêt si la relation ne tient plus).
    """
    p = BRUT / "ccomptes_financement_etat_outremer.zip"
    if not p.exists():
        raise SystemExit(f"source absente : {p}")
    with zipfile.ZipFile(p) as z:
        nom = next(n for n in z.namelist() if n.endswith("D_Territoires.csv"))
        lignes = list(csv.reader(io.StringIO(z.read(nom).decode("utf-8-sig")), delimiter=";"))
    par_nom = {cle_nom(t["nom"]): c for c, t in TERRITOIRES.items()}
    res = {c: {"annees": {}} for c in TERRITOIRES}
    courant = None
    for r in lignes[2:]:
        r = r + [""] * (19 - len(r))
        if r[1].strip():
            courant = par_nom.get(cle_nom(r[1]))
        an = num(r[2])
        if courant and an is not None:
            res[courant]["annees"][str(int(an))] = {
                "lfi_ae_eur": entier(num(r[3])), "lfi_cp_eur": entier(num(r[4])),
                "execution_ae_eur": entier(num(r[5])), "execution_cp_eur": entier(num(r[6]))}
        code = par_nom.get(cle_nom(r[10])) if r[10].strip() else None
        if code:
            arr = lambda v: None if num(v) is None else round(num(v), 2)  # noqa: E731
            res[code].update({
                "population_2018": entier(num(r[11])), "population_moins_60_ans_2018": entier(num(r[12])),
                "cp_executes_par_habitant_eur": {"2018": arr(r[13]), "2019": arr(r[14]), "2020": arr(r[15])},
                "cp_executes_par_habitant_moins_60_ans_eur": {"2018": arr(r[16]), "2019": arr(r[17]),
                                                              "2020": arr(r[18])}})
    for code, x in res.items():
        if set(x["annees"]) != {"2018", "2019", "2020"} or "population_2018" not in x:
            raise SystemExit(f"Cour des comptes : lignes attendues absentes pour {code} (le fichier a changé de forme)")
        cp, pop, pub = x["annees"]["2018"]["execution_cp_eur"], x["population_2018"], \
            x["cp_executes_par_habitant_eur"]["2018"]
        if abs(cp / pop - pub) > 0.01:
            raise SystemExit(f"Cour des comptes : unité à revoir pour {code} ({cp} / {pop} != {pub})")
    return res


# --- 4. Document de politique transversale (PDF) ---------------------------------------------------------------------

def _lignes_page(page) -> list[tuple[float, list[dict]]]:
    """Mots de la page regroupés en lignes (haut à ±1 point), triés de gauche à droite."""
    par_haut = defaultdict(list)
    for w in page.extract_words(x_tolerance=1.5, y_tolerance=2):
        par_haut[round(w["top"])].append(w)
    lignes: list[list] = []
    for t in sorted(par_haut):
        if lignes and t - lignes[-1][0] <= 1:
            lignes[-1][1].extend(par_haut[t])
        else:
            lignes.append([t, list(par_haut[t])])
    return [(t, sorted(ws, key=lambda w: w["x0"])) for t, ws in lignes]


def _valeurs_dpt(mots: list[dict], bord: float) -> list | None:
    """Six nombres d'une ligne de tableau : chaque groupe de chiffres va à la colonne dont le bord droit le suit."""
    bords = [bord - d for d in DPT_DECALAGES]
    groupes: list[list[dict]] = [[] for _ in bords]
    for w in mots:
        i = next((i for i, b in enumerate(bords) if w["x1"] <= b + 2), None)
        if i is None:
            return None
        groupes[i].append(w)
    valeurs = []
    for g, b in zip(groupes, bords):
        if not g:
            valeurs.append(None)  # cellule vide à la source
            continue
        if abs(g[-1]["x1"] - b) > 2 or any(len(w["text"]) != 3 for w in g[1:]):
            return None
        valeurs.append(int("".join(w["text"] for w in g)))
    return valeurs


_GROUPE = re.compile(r"\d{1,3}")
_REPERE_SYNTHESE = "SYNTHESE TOUS CREDITS"


def _page_synthese(chemin: Path, pdf) -> int:
    """Indice de la première page des tableaux de synthèse (pdftotext si présent, sinon pdfplumber)."""
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(chemin), "-"], capture_output=True, check=False)
        pages = r.stdout.decode("utf-8", "replace").split("\f")
        debut = next((i for i, t in enumerate(pages) if _REPERE_SYNTHESE in t), None)
    else:
        debut = next((i for i, pg in enumerate(pdf.pages) if _REPERE_SYNTHESE in (pg.extract_text() or "")), None)
    if debut is None:
        raise ValueError("tableaux de synthèse introuvables dans le PDF")
    return debut


def lire_dpt() -> dict:
    """{code: {'total': [6], 'missions': [{mission, valeurs, programmes: [{code, libelle, valeurs}]}], 'pages'}}.

    Les tableaux « Effort budgétaire et financier de l'État » par territoire sont lus par position des mots
    (pdfplumber). Une ligne = un bloc de lignes de texte séparées de 10 points au plus (libellés sur plusieurs
    lignes). Lève ValueError si un tableau ne peut pas être lu ; `verifier_dpt` contrôle ensuite les sommes.
    """
    import pdfplumber
    p = BRUT / "dpt2026_outremer.pdf"
    if not p.exists():
        raise ValueError(f"source absente : {p}")
    res: dict = {}
    courant, termine = None, True
    with pdfplumber.open(p) as pdf:
        debut = _page_synthese(p, pdf)
        for no in range(debut, len(pdf.pages)):
            lignes = [(t, ws) for t, ws in _lignes_page(pdf.pages[no]) if t >= 60]
            chiffres = [w for _, ws in lignes for w in ws if w["x0"] > 190 and _GROUPE.fullmatch(w["text"])]
            bord = max((w["x1"] for w in chiffres), default=None)
            # Un nombre de la première colonne peut déborder sur la zone des libellés : un groupe de chiffres
            # appartient au tableau dès qu'il commence à moins d'une largeur de colonne du premier bord droit.
            gauche = (bord - DPT_DECALAGES[0] - 62) if bord else None
            est_nombre = lambda w: bool(gauche and w["x0"] > gauche and _GROUPE.fullmatch(w["text"]))  # noqa: E731
            blocs: list[list] = []
            for t, ws in lignes:
                if blocs and t - blocs[-1][-1][0] <= 10:
                    blocs[-1].append((t, ws))
                else:
                    blocs.append([(t, ws)])
            for bloc in blocs:
                texte = " ".join(w["text"] for _, ws in bloc for w in ws if w["x1"] < 232 and not est_nombre(w))
                titre = sans_accents(" ".join(w["text"] for _, ws in bloc for w in ws)).upper().strip()
                if titre in DPT_TITRES or titre in DPT_AUTRES_TITRES:
                    courant, termine = DPT_TITRES.get(titre), False
                    if courant:
                        res[courant] = {"total": None, "missions": [], "pages": [no + 1, no + 1]}
                    continue
                if courant is None or termine:
                    continue
                mots = [w for _, ws in bloc for w in ws if est_nombre(w)]
                if not mots or any(w["x0"] > 232 and not est_nombre(w) for _, ws in bloc for w in ws):
                    continue  # en-tête du tableau, texte hors tableau
                valeurs = _valeurs_dpt(mots, bord)
                if valeurs is None:
                    raise ValueError(f"page {no + 1} : ligne illisible « {texte[:60]} »")
                t = res[courant]
                t["pages"][1] = no + 1
                m = re.match(r"^(\d{3,4}) - (.+)$", texte)
                if texte.lower().startswith("total général"):
                    t["total"], termine = valeurs, True
                elif m:
                    if not t["missions"]:
                        raise ValueError(f"page {no + 1} : programme {m.group(1)} sans mission")
                    t["missions"][-1]["programmes"].append({"code": m.group(1), "libelle": propre(m.group(2)),
                                                            "valeurs": valeurs})
                elif texte:
                    t["missions"].append({"mission": propre(texte), "valeurs": valeurs, "programmes": []})
                else:
                    raise ValueError(f"page {no + 1} : ligne de nombres sans libellé")
    return res


def verifier_dpt(t: dict | None) -> list[str]:
    """Anomalies d'un tableau lu : vide si chaque somme se vérifie, colonne par colonne.

    Tolérance : 1 € par ligne additionnée (la source arrondit chaque ligne à l'euro) ; une erreur de lecture d'un
    groupe de chiffres donnerait un écart d'au moins 1 000 €.
    """
    if not t or t.get("total") is None or not t.get("missions"):
        return ["tableau ou total général introuvable"]
    fautes = []
    for j, col in enumerate(DPT_COLONNES):
        if any(m["valeurs"][j] is None for m in t["missions"]) or t["total"][j] is None:
            fautes.append(f"{col} : cellule vide")
            continue
        if abs(sum(m["valeurs"][j] for m in t["missions"]) - t["total"][j]) > len(t["missions"]):
            fautes.append(f"{col} : somme des missions différente du total général")
        for m in t["missions"]:
            vals = [p["valeurs"][j] for p in m["programmes"]]
            if not vals or None in vals or abs(sum(vals) - m["valeurs"][j]) > len(vals):
                fautes.append(f"{col} : somme des programmes différente de la mission « {m['mission']} »")
    return fautes


# --- 5. Nouvelle-Calédonie -------------------------------------------------------------------------------------------

def nature_chapitre(chapitre: str, libelle: str) -> str:
    """`report` (résultat reporté), `ordre` (écritures entre sections ou patrimoniales, sans flux), sinon `reel`."""
    if chapitre in ("001", "002"):
        return "report"
    lib = sans_accents(libelle).upper()
    if any(m in lib for m in ("TRANSFERTS ENTRE", "OPERATIONS PATRIMONIALES", "OPERATIONS ORDRE", "OPERATIONS D'ORDRE",
                              "VIREMENT A LA SECTION", "VIREMENT DE LA SECTION")):
        return "ordre"
    return "reel"


def _quadruplet(bt, re_):
    return [entier(bt), entier(re_), xpf_en_eur(bt), xpf_en_eur(re_)]


def lire_nc_budget() -> dict:
    """Budgets de la Nouvelle-Calédonie par exercice, budget, sens, section et chapitre (francs CFP et euros)."""
    acc: dict = defaultdict(lambda: [0.0, 0.0])
    libelles: dict = {}
    individualises = defaultdict(set)
    for r in lire_csv("nc_budget.csv"):
        an, budget, sens, section = str(r["exercice_budgetaire"])[:4], r["code_budget"], r["sens"], r["section_lc"]
        chap, lib = r["chapitre"].strip(), propre(r["libelle_long_chapitre"])
        if len(chap) > 3:  # opération individualisée (9240403...) : libellé au nom d'un projet ou d'une entreprise
            individualises[an].add(chap)
            chap, lib = chap[:3], None
        else:
            libelles.setdefault(chap, lib)
        k = (an, budget, sens, section, chap, lib is None)
        acc[k][0] += num(r["budget_total"]) or 0.0
        acc[k][1] += num(r["realise"]) or 0.0
    annees = sorted({k[0] for k in acc})
    chapitres: dict = {a: [] for a in annees}
    totaux: dict = {a: {} for a in annees}
    for (an, budget, sens, section, chap, agrege), (bt, re_) in sorted(acc.items()):
        lib = "opérations individualisées (chapitres à 7 chiffres agrégés, libellés non repris)" if agrege \
            else libelles.get(chap)
        nature = "reel" if agrege else nature_chapitre(chap, lib or "")
        chapitres[an].append([budget, sens, section, chap, lib, nature] + _quadruplet(bt, re_))
        t = totaux[an].setdefault(budget, {}).setdefault(sens, {}).setdefault(
            section, {"total": [0.0, 0.0], "hors_ordre_et_reports": [0.0, 0.0]})
        t["total"][0] += bt
        t["total"][1] += re_
        if nature == "reel":
            t["hors_ordre_et_reports"][0] += bt
            t["hors_ordre_et_reports"][1] += re_
    for a in totaux:
        for b in totaux[a].values():
            for s in b.values():
                for sec in s.values():
                    sec["total"] = _quadruplet(*sec["total"])
                    sec["hors_ordre_et_reports"] = _quadruplet(*sec["hors_ordre_et_reports"])
    return {"annees": annees, "chapitres": chapitres, "totaux": totaux,
            "chapitres_individualises_agreges": {a: len(individualises[a]) for a in annees}}


def lire_nc_etablissements() -> dict:
    """{sigle: {'type': 'EPA'|'EPIC', 'annees': {annee: {sens: {section: [4]}}}}} (totaux tous chapitres)."""
    res: dict = {}
    for typ, nom in (("EPA", "nc_epa.csv"), ("EPIC", "nc_epic.csv")):
        acc: dict = defaultdict(lambda: [0.0, 0.0])
        for r in lire_csv(nom):
            k = (propre(r["collectivite"]), str(r["exercice_budgetaire"])[:4], r["sens"], r["section_lc"])
            acc[k][0] += num(r["budget_total"]) or 0.0
            acc[k][1] += num(r["realise"]) or 0.0
        for (sigle, an, sens, section), (bt, re_) in sorted(acc.items()):
            e = res.setdefault(sigle, {"type": typ, "annees": {}})
            e["annees"].setdefault(an, {}).setdefault(sens, {})[section] = _quadruplet(bt, re_)
    return {s: res[s] for s in sorted(res)}


def lire_nc_impots() -> dict:
    """{'annees': [...], 'impots': [{libelle, montants_xpf: [...], montants_eur: [...]}], totaux par année}."""
    par_lib: dict = defaultdict(dict)
    for r in lire_csv("nc_impots.csv"):
        v = num(r["montant_titre"])
        par_lib[propre(r["lib_long_lc"])][str(r["annee"])[:4]] = None if v is None else entier(v)
    annees = sorted({a for d in par_lib.values() for a in d})
    impots = [{"libelle": lib, "montants_xpf": [par_lib[lib].get(a) for a in annees],
               "montants_eur": [xpf_en_eur(par_lib[lib].get(a)) for a in annees]} for lib in sorted(par_lib)]
    tot = [sum(i["montants_xpf"][j] or 0 for i in impots) for j in range(len(annees))]
    return {"annees": annees, "impots": impots, "total_xpf": tot, "total_eur": [xpf_en_eur(v) for v in tot],
            "nombre_impots": [sum(1 for i in impots if i["montants_xpf"][j] is not None) for j in range(len(annees))]}


# --- Production ------------------------------------------------------------------------------------------------------

def _ecart(territoire, annee, source, montant, autre_source, autre_montant, lecture) -> dict | None:
    if montant is None or autre_montant is None:
        return None
    e = montant - autre_montant
    return {"territoire": territoire, "annee": annee, "source": source, "montant": montant,
            "autre_source": autre_source, "autre_montant": autre_montant, "ecart": e,
            "ecart_pct": round(e / autre_montant * 100, 2) if autre_montant else None, "lecture_ecart": lecture}


def _dgf_ofgl(dc: dict, dint: dict | None, dcoll: dict | None, annee: str) -> int | None:
    """DGF notifiée du territoire (communes + intercommunalités + collectivité) ; None si rien n'est publié."""
    vals = [c["eur"].get(annee, {}).get("dgf_totale") for c in dc["communes"].values()]
    if dint:
        vals += [e["eur"].get(annee, {}).get("dgf_totale") for e in dint["epci"].values()]
    if dcoll:
        vals.append(dcoll["eur"].get(annee, {}).get("dgf_totale"))
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def produire() -> dict:
    date = date_sources(ID_CATALOGUE)
    for c in CODES:
        if not (BRUT / f"geo_{c}.json").exists():
            raise SystemExit(f"entrepôt {BRUT} incomplet : lancer `python pipeline/outremer.py collecter`")
    geo = {c: lire_geo(c) for c in CODES}
    dot_com = {c: lire_dotations_communes(c) for c in CODES}
    dot_coll = lire_dotations_collectivites()
    dot_int = lire_dotations_intercommunalites()
    cdc = lire_cour_des_comptes()
    inaccessibles = []
    try:
        dpt = lire_dpt()
        dpt_fautes = {c: verifier_dpt(dpt.get(c)) for c in CODES}
    except Exception as exc:  # PDF illisible ou forme inattendue : bloc déclaré non publié, jamais deviné
        dpt, dpt_fautes = {}, {c: [f"lecture du PDF impossible : {exc}"[:200]] for c in CODES}
    nc = lire_nc_budget()
    nc_etab = lire_nc_etablissements()
    nc_imp = lire_nc_impots()
    metas = {k: meta_ods(s["fichier_meta"]) for k, s in SOURCES.items() if s.get("fichier_meta")}
    en_cours = nc["annees"][-1]
    complet = nc["annees"][-2]
    etat_nc = (metas["nc_budget"].get("modifie_le") or date)

    if SORTIE.exists():
        for f in sorted(SORTIE.glob("*.json")):
            f.unlink()

    millesime_dot = lambda an: f"dotations notifiées {an[0]} à {an[-1]}" if an else None  # noqa: E731
    ecarts, fiches = [], []
    for code in CODES:
        t = TERRITOIRES[code]
        communes = geo[code]
        dc, dcoll, dint = dot_com[code], dot_coll.get(code), dot_int.get(code)
        inconnues = sorted(set(dc["communes"]) - set(communes))
        if inconnues:
            raise SystemExit(f"{code} : communes des dotations absentes du code officiel géographique : {inconnues}")
        blocs: dict = {"geo": {"statut": PUBLIE, "source": "geo"}}

        # dotations des communes
        if dc["communes"]:
            blocs["dotations_communes"] = {"statut": PUBLIE, "source": "ofgl_dotations_communes",
                                           "communes": len(dc["communes"]), "annees": dc["annees"]}
            dotations_communes = {
                "statut": PUBLIE, "unite": "euros", "annees": dc["annees"],
                "cles": sorted({k for c in dc["communes"].values() for v in c["eur"].values() for k in v}),
                "note": NOTE_DOTATIONS, "communes": dc["communes"],
                "recettes_reelles_fonctionnement_n_moins_2": {"definition": NOTE_RRF, "unite": "euros",
                                                              "communes": dc["rrf"]}}
        else:
            blocs["dotations_communes"] = {"statut": NON_PUBLIE, "motif": MOTIFS_NON_PUBLIE["dotations_communes"]}
            dotations_communes = dict(blocs["dotations_communes"])

        # dotations des intercommunalités
        if dint and dint["epci"]:
            blocs["dotations_intercommunalites"] = {"statut": PUBLIE, "source": "ofgl_dotations_intercommunalites",
                                                    "intercommunalites": len(dint["epci"]), "annees": dint["annees"]}
            dotations_intercommunalites = {
                "statut": PUBLIE, "unite": "euros", "annees": dint["annees"],
                "cles": sorted({k for e in dint["epci"].values() for v in e["eur"].values() for k in v}),
                "note": "dgf_totale = dotation d'intercommunalité + dotation de compensation ; montants notifiés "
                        "par la DGCL, en euros",
                "epci": dint["epci"]}
        else:
            blocs["dotations_intercommunalites"] = {"statut": NON_PUBLIE,
                                                    "motif": MOTIFS_NON_PUBLIE["dotations_intercommunalites"]}
            dotations_intercommunalites = dict(blocs["dotations_intercommunalites"])

        # dotations de la collectivité
        if dcoll and dcoll["eur"]:
            an = sorted(dcoll["eur"])
            blocs["dotations_collectivite"] = {"statut": PUBLIE, "source": "ofgl_dotations_collectivites", "annees": an}
            dotations_collectivite = {
                "statut": PUBLIE, "unite": "euros", "annees": an,
                "cles": sorted({k for v in dcoll["eur"].values() for k in v}), "nom": dcoll["nom"],
                "eur": dcoll["eur"], "population_dgf": dcoll["population_dgf"],
                "recettes_reelles_fonctionnement_n_moins_2": {"definition": NOTE_RRF, "unite": "euros",
                                                              "eur": dcoll["rrf"]}}
        else:
            blocs["dotations_collectivite"] = {"statut": NON_PUBLIE,
                                               "motif": MOTIFS_NON_PUBLIE["dotations_collectivite"]}
            dotations_collectivite = dict(blocs["dotations_collectivite"])

        # crédits de l'État : Cour des comptes
        blocs["credits_etat_2018_2020"] = {"statut": PUBLIE, "source": "cour_des_comptes",
                                           "annees": sorted(cdc[code]["annees"])}
        credits = {"cour_des_comptes_2018_2020": {
            "statut": PUBLIE, "unite": "euros", "licence": SOURCES["cour_des_comptes"]["licence"],
            "definitions": {
                "lfi": "crédits ouverts en loi de finances initiale, répartis par territoire",
                "execution": "crédits consommés",
                "ae": "autorisations d'engagement", "cp": "crédits de paiement",
                "cp_executes_par_habitant_eur": "crédits de paiement exécutés divisés par la population estimée au "
                                                "1er janvier 2018 (calcul de la Cour des comptes) ; null quand la "
                                                "Cour ne publie pas l'année"},
            **cdc[code]}}

        # crédits de l'État : document de politique transversale
        if not dpt_fautes[code]:
            d = dpt[code]
            blocs["credits_etat_plf2026"] = {"statut": PUBLIE, "source": "dpt_plf2026", "pages_pdf": d["pages"]}
            credits["dpt_plf2026"] = {
                "statut": PUBLIE, "unite": "euros", "colonnes": DPT_COLONNES, "pages_pdf": d["pages"],
                "definitions": {
                    "execution_2024": "crédits consommés en 2024", "lfi_2025": "loi de finances initiale pour 2025",
                    "plf_2026": "projet de loi de finances pour 2026",
                    "ae": "autorisations d'engagement", "cp": "crédits de paiement",
                    "programmes_3101_et_suivants": "codes à quatre chiffres : prélèvements sur les recettes de "
                                                   "l'État au profit des collectivités, comptés par la source dans "
                                                   "la mission « Relations avec les collectivités territoriales »"},
                "controle": CONTROLE_DPT,
                "total_general": d["total"], "missions": d["missions"]}
            psr = next((p for m in d["missions"] for p in m["programmes"] if p["code"] == DPT_PSR_DGF), None)
            for an, col in (("2024", "execution_2024_cp"), ("2025", "lfi_2025_cp")):
                e = _ecart(code, an, f"dpt_plf2026, prélèvement sur recettes {DPT_PSR_DGF} ({col})",
                           psr["valeurs"][DPT_COLONNES.index(col)] if psr else None,
                           "ofgl, DGF notifiée aux communes, aux intercommunalités et à la collectivité",
                           _dgf_ofgl(dc, dint, dcoll, an),
                           "le document de politique transversale donne le prélèvement sur recettes au titre de la "
                           "DGF réparti par territoire (exécution ou loi de finances) ; l'OFGL donne les montants "
                           "notifiés par la DGCL aux communes, aux intercommunalités (987) et à la collectivité "
                           "(975 et 978) ; un écart nul recoupe les deux sources, il ne s'ajoute à rien")
                if e:
                    ecarts.append(e)
        else:
            motif = ("extraction du PDF non vérifiée (" + " ; ".join(dpt_fautes[code][:3]) + ") : tableau non repris ; "
                     "la source ne publie pas ce tableau en données ouvertes")
            blocs["credits_etat_plf2026"] = {"statut": NON_PUBLIE, "motif": motif}
            credits["dpt_plf2026"] = dict(blocs["credits_etat_plf2026"])

        # budgets
        blocs["budget_communes"] = {"statut": NON_PUBLIE, "motif": MOTIFS_NON_PUBLIE["budget_communes"]}
        if code == "988":
            blocs["budget_collectivite"] = {"statut": PUBLIE, "source": "nc_budget", "fichier": "outremer/988_budget.json",
                                            "annees": nc["annees"], "devise_source": "XPF"}
            blocs["impots_territoriaux"] = {"statut": PUBLIE, "source": "nc_impots", "fichier": "outremer/988_budget.json",
                                            "annees": nc_imp["annees"], "devise_source": "XPF"}
            resume = {b: {s: {sec: v["hors_ordre_et_reports"] for sec, v in secs.items()} for s, secs in sens.items()}
                      for b, sens in nc["totaux"][complet].items()}
            budget_collectivite = {
                "statut": PUBLIE, "fichier": "outremer/988_budget.json", "devise_source": "XPF",
                "parite": {"xpf_par_eur": XPF_PAR_EUR}, "exercice": int(complet), "colonnes": COLONNES_XPF,
                "budgets": NC_BUDGETS,
                "note": f"dernier exercice entier publié ({complet}), hors écritures d'ordre et résultats reportés ; les "
                        "trois budgets ne s'additionnent pas (les budgets annexes reversent ou répartissent des "
                        "recettes, en partie vers le budget principal)",
                "hors_ordre_et_reports": resume}
        else:
            cle = f"budget_collectivite_{code}" if f"budget_collectivite_{code}" in MOTIFS_NON_PUBLIE \
                else "budget_collectivite"
            blocs["budget_collectivite"] = {"statut": NON_PUBLIE, "motif": MOTIFS_NON_PUBLIE[cle]}
            blocs["impots_territoriaux"] = {"statut": NON_PUBLIE, "motif": MOTIFS_NON_PUBLIE["impots_territoriaux"]}
            budget_collectivite = dict(blocs["budget_collectivite"])
        population = sum(c["population"] or 0 for c in communes.values()) if all(
            c["population"] is not None for c in communes.values()) else None

        sources_lues = sorted({b["source"] for b in blocs.values() if b.get("source")})
        mill = [f"communes : code officiel géographique en vigueur, sources collectées le {date}"]
        if dc["annees"]:
            mill.append(millesime_dot(dc["annees"]) + " (communes)")
        if dcoll and dcoll["eur"]:
            mill.append(millesime_dot(sorted(dcoll["eur"])) + " (collectivité)")
        mill.append("crédits de l'État 2018 à 2020 (Cour des comptes)")
        if not dpt_fautes[code]:
            mill.append("exécution 2024, LFI 2025 et PLF 2026 (document de politique transversale)")
        if code == "988":
            mill.append(f"budget de la Nouvelle-Calédonie {nc['annees'][0]} à {en_cours}")
        fiche = {
            "millesime": " ; ".join(mill),
            "source": " ; ".join(SOURCES[s]["titre"] for s in sources_lues),
            "sources": sources_lues,
            "territoire": {"code": code, "nom": t["nom"], "statut_juridique": t["statut_juridique"],
                           "monnaie": t["monnaie"], "population": population, "communes": len(communes)},
            "blocs": {b: blocs[b] for b in BLOCS},
            "communes": communes,
            "note_communes": "communes du code officiel géographique ; siren et epci : null, l'API ne les publie pas "
                             "pour ce territoire" + (" ; à Wallis-et-Futuna, les trois entrées sont les "
                                                     "circonscriptions territoriales" if code == "986" else "")
                             + (" ; la collectivité unique y figure comme une commune" if code in ("977", "978")
                                else ""),
            "dotations_communes": dotations_communes,
            "dotations_intercommunalites": dotations_intercommunalites,
            "dotations_collectivite": dotations_collectivite,
            "credits_etat": credits,
            "budget_collectivite": budget_collectivite,
            "budget_communes": dict(blocs["budget_communes"]),
        }
        dump(SORTIE / f"{code}.json", fiche)
        fiches.append({"code": code, "nom": t["nom"], "statut_juridique": t["statut_juridique"],
                       "monnaie": t["monnaie"], "population": population, "communes": len(communes),
                       "fichier": f"outremer/{code}.json",
                       "blocs": {b: blocs[b]["statut"] for b in BLOCS}})

    # Nouvelle-Calédonie : détail
    dump(SORTIE / "988_budget.json", {
        "millesime": f"exercices {nc['annees'][0]} à {en_cours} ; {en_cours} : exercice en cours, situation au "
                     f"{etat_nc} ; rendement des impôts {nc_imp['annees'][0]} à {nc_imp['annees'][-1]}",
        "source": " ; ".join(SOURCES[s]["titre"] for s in ("nc_budget", "nc_epa", "nc_epic", "nc_impots")),
        "sources": ["nc_budget", "nc_epa", "nc_epic", "nc_impots"],
        "territoire": {"code": "988", "nom": TERRITOIRES["988"]["nom"]},
        "unite": "francs CFP (XPF) et euros", "devise_source": "XPF",
        "parite": {"xpf_par_eur": XPF_PAR_EUR,
                   "methode": "montant en euros = montant en francs CFP / 119,33174, arrondi à l'euro (parité fixe : "
                              "1 000 XPF = 8,38 €)"},
        "annees": nc["annees"], "exercice_en_cours": int(en_cours), "situation_au": etat_nc,
        "avertissement": f"{en_cours} est l'exercice en cours : le réalisé est celui du dernier jour du mois publié "
                         f"(jeu modifié le {etat_nc}), pas celui d'une année entière.",
        "budgets": NC_BUDGETS,
        "budgets_source": NC_BUDGETS_SOURCE,
        "definitions": {
            "budget_total": "crédits ou recettes inscrits au budget de l'exercice (budget primitif et décisions "
                            "modificatives)",
            "realise": "montant réalisé (dépenses mandatées, recettes titrées)",
            "sens": "D = dépenses, R = recettes",
            "nature": "reel = chapitre de dépenses ou de recettes ; ordre = écritures entre sections ou "
                      "patrimoniales, sans flux d'argent (chapitres « transferts entre les sections », « opérations "
                      "patrimoniales », « opérations d'ordre », « virement à la section d'investissement », "
                      "« virement de la section de fonctionnement ») ; report = résultat reporté de l'exercice précédent "
                      "(chapitres 001 et 002)",
            "hors_ordre_et_reports": "somme des chapitres de nature « reel »",
        },
        "methode": "sommes des lignes du jeu par exercice, budget, sens, section et chapitre ; articles et "
                   "sous-fonctions non repris ; les trois budgets ne sont jamais additionnés ; le libellé de chaque "
                   "code de budget vient des documents budgétaires de la DBAF, le jeu ne le publie pas",
        "regle_personnes": "les chapitres à sept chiffres (opérations individualisées, libellées au nom d'un projet "
                           "ou d'une entreprise, parfois individuelle) sont agrégés sous leurs trois premiers "
                           "chiffres, sans libellé",
        "collectivite": {
            "colonnes_totaux": COLONNES_XPF,
            "totaux": nc["totaux"],
            "colonnes_chapitres": ["budget", "sens", "section", "chapitre", "libelle", "nature"] + COLONNES_XPF,
            "chapitres": nc["chapitres"],
            "chapitres_individualises_agreges": nc["chapitres_individualises_agreges"],
        },
        "etablissements": {
            "note": "sigle publié par la source ; l'intitulé complet de l'établissement ne figure pas dans le jeu. "
                    "Totaux tous chapitres, écritures d'ordre et reports compris.",
            "colonnes": COLONNES_XPF,
            "etablissements": nc_etab,
        },
        "impots": {
            "definition": "montant des titres de recettes émis par impôt et par année, tel que publié ; une année "
                          "sans ligne pour un impôt est null",
            "ordre": "alphabétique sur le libellé publié",
            **nc_imp,
        },
    })

    # sources et index
    manifeste = _manifeste()
    sources = {}
    for k, s in SOURCES.items():
        e = {x: s[x] for x in ("titre", "producteur", "url", "page", "licence", "verdict")}
        e["collecte_le"] = date
        if k in metas and metas[k]:
            e["modifie_le"] = metas[k].get("modifie_le")
        sources[k] = e
    if manifeste.get("statut") not in (None, "ok"):
        inaccessibles.append({"source": "entrée « outremer » du catalogue",
                              "motif": f"collecte incomplète (statut {manifeste.get('statut')})"})
    for code in CODES:
        if dpt_fautes[code]:
            inaccessibles.append({"source": f"{SOURCES['dpt_plf2026']['titre']} ({TERRITOIRES[code]['nom']})",
                                  "motif": "tableau non repris : " + " ; ".join(dpt_fautes[code][:3])})
    inaccessibles += [
        {"source": "Budget des communes des six territoires",
         "motif": MOTIFS_NON_PUBLIE["budget_communes"]},
        {"source": "Budget de la Polynésie française", "motif": MOTIFS_NON_PUBLIE["budget_collectivite_987"]},
        {"source": "Budget de la collectivité de Saint-Barthélemy", "motif": MOTIFS_NON_PUBLIE["budget_collectivite_977"]},
        {"source": "Budget des collectivités de Saint-Pierre-et-Miquelon, de Saint-Martin et de Wallis-et-Futuna",
         "motif": MOTIFS_NON_PUBLIE["budget_collectivite"]},
        {"source": "Intitulé des budgets 01, 02 et 03 de la Nouvelle-Calédonie",
         "motif": "le jeu ne publie que le code ; libellés repris des documents budgétaires de la DBAF"},
    ]
    dpt_lus = [c for c in CODES if not dpt_fautes[c]]
    index = {
        "millesime": f"sources collectées le {date} ; dotations {min(a for c in CODES for a in dot_com[c]['annees'])} à "
                     f"{max(a for c in CODES for a in dot_com[c]['annees'])} ; crédits de l'État 2018 à 2020 et "
                     f"2024 à 2026 ; budget de la Nouvelle-Calédonie {nc['annees'][0]} à {en_cours}",
        "source": "pipeline/outremer.py (voir `sources` et chaque fichier)",
        "collecte_le": date,
        "territoires": fiches,
        "blocs": BLOCS,
        "statuts": {PUBLIE: "le bloc est repris d'une source ouverte, citée dans le fichier du territoire",
                    NON_PUBLIE: "aucune source ouverte ne publie ce bloc pour ce territoire à la date de collecte : "
                                "cela décrit l'état de la publication, pas l'usage de l'argent ; aucune valeur "
                                "n'est estimée"},
        "parite_xpf": {"xpf_par_eur": XPF_PAR_EUR, "devise_source": "XPF",
                       "methode": "montant en euros = montant en francs CFP / 119,33174, arrondi à l'euro ; le "
                                  "montant d'origine en francs CFP est toujours publié à côté",
                       "territoires_en_francs_cfp": [c for c in CODES if TERRITOIRES[c]["monnaie"] == "XPF"]},
        "fichiers": {"territoire": "outremer/<code>.json", "budget_nouvelle_caledonie": "outremer/988_budget.json"},
        "lien_local": {"fichier": "local/index.json",
                       "lecture": "« Près de chez moi » couvre les 101 départements ; ces six territoires n'y "
                                  "figurent pas et sont décrits ici avec les mêmes clés de dotations"},
        "ecarts": sorted(ecarts, key=lambda e: (e["territoire"], e["annee"])),
        "credits_etat_plf2026": {"territoires_lus": dpt_lus, "colonnes": DPT_COLONNES,
                                 "controle": CONTROLE_DPT + " ; un territoire dont le contrôle ne passe pas "
                                                            "n'est pas repris"},
        "limites": [
            "Les crédits de l'État par territoire viennent de deux sources de périmètres différents (Cour des "
            "comptes 2018 à 2020 ; document de politique transversale 2024 à 2026) : elles ne sont ni raccordées ni "
            "additionnées.",
            "Le document de politique transversale précise que certaines dépenses ne sont pas réparties par "
            "territoire (« crédits non répartis ») et que les trois colonnes (exécution, loi de finances, projet de "
            "loi) ne sont pas de même nature.",
            "Les dotations notifiées par la DGCL ne couvrent pas tous les concours de l'État à ces territoires "
            "(dotations propres à la Polynésie française et à la Nouvelle-Calédonie, contrats, fiscalité).",
            "Le fichier de la Cour des comptes porte l'en-tête « (En M€) » : les montants sont en euros (contrôle "
            "à chaque production : crédits de paiement exécutés / population = montant par habitant publié).",
            f"Budget de la Nouvelle-Calédonie : {en_cours} est l'exercice en cours ; les établissements publics "
            "sont publiés par sigle.",
        ],
        "sources": sources,
        "sources_inaccessibles": inaccessibles,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(SORTIE / "index.json", index)
    print(f"outremer : {len(CODES)} territoires, {sum(f['communes'] for f in fiches)} communes, "
          f"DPT lu pour {len(dpt_lus)} territoires, {len(ecarts)} écarts -> {SORTIE.relative_to(ROOT)}")
    return index


def _manifeste() -> dict:
    try:
        return json.loads((LAKE / "manifest.json").read_text(encoding="utf-8")).get(ID_CATALOGUE, {})
    except (OSError, ValueError):
        return {}


# --- Collecte --------------------------------------------------------------------------------------------------------

def collecter(forcer: bool = False) -> int:
    """Collecte par collecte/collecte.py (reprises, manifeste, aucun contournement d'un refus d'accès)."""
    cmd = [sys.executable, str(ROOT / "collecte" / "collecte.py"), ID_CATALOGUE]
    return subprocess.call(cmd + (["--force"] if forcer else []))


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
