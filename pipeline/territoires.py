"""Territoires : enrichit « Près de chez moi » (local/) avec trois familles de sources ouvertes, par département.

1. Projets financés par les dotations de soutien à l'investissement local (DETR, DSIL, DPV, DSID, programme 119),
   2018 à 2025 : chaque projet (intitulé, coût HT, subvention, taux), par bénéficiaire (SIREN, code INSEE).
2. Inventaire SRU (article 55) : taux de logements sociaux, commune déficitaire, carencée, exemptée, prélèvement net
   majoré, par commune et par édition.
3. Aide sociale départementale (DREES) : dépenses brutes et nettes 1999-2024 par poste (APA, PCH, ACTP, ASE, RSA,
   hébergement PA/PH...), indicateurs financiers ISD (par habitant, par bénéficiaire), APA à domicile et PCH
   (bénéficiaires et montants versés).

Entrées (data/lake, collectées par collecte/collecte.py, ids déclarés dans collecte/catalogue.json) :
  collectivites/datagouv__projets-finances-par-les-dotations-de-soutien-a-linvestissement-des-collectivites-territoriales/*.csv
  collectivites/territoires_sru/*.csv
  collectivites/drees__376_les-depenses-d-aide-sociale-departementale/*series_longues*.xlsx
  secu/drees__619_indicateurs-financiers.parquet
  collectivites/drees__apa-et-pch-montants-verses/*.xlsx
  lecture seule : site/data/local/ (geo, budgets/departements.json, dotations/communes) pour les liens, les noms
  officiels, la population (euros par habitant) et un contrôle croisé ; stock SIRENE (pipeline/local.py) pour la
  catégorie juridique des bénéficiaires.
Sorties (site/data/territoires/, chaque fichier < 5 Mo, avec `millesime` et `source`) :
  index.json        couverture par source, totaux, écarts entre sources, liens vers les fichiers, sources, recherche
  <dep>.json        un fichier par département de local/geo : projets, SRU, aide sociale, écarts du département

Commandes :
  python pipeline/territoires.py collecter          # réseau : collecte/collecte.py sur les sources du module
  python pipeline/territoires.py produire           # sans réseau ; --sortie DOSSIER pour une copie de contrôle
  python pipeline/territoires.py                    # les deux

Règles :
  - une valeur absente, « ND », « NR », « NA », « Pas d'inventaire » reste null (la marque de la source est gardée à
    côté), jamais 0 ; un 0 publié par la source reste 0 ; « - € » (format comptable) dans la colonne du prélèvement
    SRU vaut 0 € et la règle est écrite dans `methode` ;
  - bénéficiaire nommé seulement si personne morale (catégorie juridique SIRENE 2xxx à 9xxx, ou commune,
    intercommunalité, syndicat, département reconnus par leur code) ; le reste est agrégé sans nom ni intitulé ;
  - intitulés de projets : null s'ils contiennent une civilité ou un prénom suivi d'un nom (pipeline/local.py) ;
  - deux sources ne sont jamais additionnées ; leurs écarts sont publiés (montant, différence, part) avec la raison ;
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
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
LOCAL = SITE / "local"
SORTIE_DEFAUT = SITE / "territoires"
MAX_OCTETS = 5_000_000

ID_DGCL = "datagouv__projets-finances-par-les-dotations-de-soutien-a-linvestissement-des-collectivites-territoriales"
ID_SRU = "territoires_sru"
ID_ASD = "drees__376_les-depenses-d-aide-sociale-departementale"
ID_ISD = "drees__619_indicateurs-financiers"
ID_APAPCH = "drees__apa-et-pch-montants-verses"
DOSSIERS = {ID_DGCL: LAKE / "collectivites" / ID_DGCL, ID_SRU: LAKE / "collectivites" / ID_SRU,
            ID_ASD: LAKE / "collectivites" / ID_ASD, ID_APAPCH: LAKE / "collectivites" / ID_APAPCH}
ISD_PARQUET = LAKE / "secu" / f"{ID_ISD}.parquet"

SOURCES = {
    "dgcl_investissement": {
        "id_catalogue": ID_DGCL,
        "titre": "DGCL, « Projets financés par les dotations de soutien à l'investissement des collectivités "
                 "territoriales » (DETR, DSIL, DPV, DSID ; programme 119), un CSV par exercice",
        "page": "https://www.data.gouv.fr/datasets/6176785207139a929a2776fe",
        "producteur": "Direction générale des collectivités locales (DGCL)", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (CSV « ; » publiés sur data.gouv.fr, collecte générique)",
    },
    "sru": {
        "id_catalogue": ID_SRU,
        "titre": "Ministère chargé du logement, « Communes et inventaire SRU » (article 55 de la loi SRU), un CSV par "
                 "édition",
        "page": "https://www.data.gouv.fr/datasets/6564969d3579e21795ebd378",
        "producteur": "Ministère de la Transition écologique (DGALN)", "licence": "Licence Ouverte 2.0",
        "verdict": "à adapter : colonnes, séparateur et encodage (Windows-1252) changent d'une édition à l'autre ; "
                   "colonnes repérées par leur nom",
    },
    "drees_aide_sociale": {
        "id_catalogue": ID_ASD,
        "titre": "DREES, « Les dépenses d'aide sociale départementale », séries longues 1999-2024 (enquête Aide "
                 "sociale), milliers d'euros",
        "page": "https://data.drees.solidarites-sante.gouv.fr/explore/dataset/"
                "376_les-depenses-d-aide-sociale-departementale/",
        "producteur": "DREES", "licence": "Licence Ouverte 2.0",
        "verdict": "à adapter : classeur xlsx, un onglet par poste et par mesure (brute, nette), lu par en-têtes",
    },
    "drees_isd": {
        "id_catalogue": ID_ISD,
        "titre": "DREES, indicateurs sociaux départementaux (ISD), « Indicateurs financiers » (FI01 à FI11)",
        "page": "https://data.drees.solidarites-sante.gouv.fr/explore/dataset/619_indicateurs-financiers/",
        "producteur": "DREES", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (export parquet de l'API Opendatasoft)",
    },
    "drees_apa_pch": {
        "id_catalogue": ID_APAPCH,
        "titre": "DREES, « APA et PCH - Montants versés » : APA à domicile (bénéficiaires payés en décembre, dépenses "
                 "couvertes après participation des bénéficiaires) et PCH (personnes payées et montants versés pour "
                 "le mois de décembre)",
        "page": "https://data.drees.solidarites-sante.gouv.fr/explore/dataset/apa-et-pch-montants-verses/",
        "producteur": "DREES", "licence": "Licence Ouverte 2.0",
        "verdict": "à adapter : un onglet par année, colonnes repérées par leur en-tête",
    },
    "local": {
        "titre": "site/data/local (pipeline/local.py), lecture seule : communes, EPCI et population (geo.api.gouv.fr), "
                 "population des départements (OFGL), dotations par commune",
        "page": "site/data/local/index.json", "producteur": "pipeline/local.py", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (mêmes codes INSEE et SIREN)",
    },
}

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "requetes": ["github DETR DSIL projets dotations investissement local csv",
                 "github aide sociale départementale DREES dépenses département séries longues",
                 "github loi SRU taux logements sociaux communes carencées prélèvement"],
    "trouvailles": [
        {"nom": "collecte/collecte.py (ce dépôt)", "verdict": "réutilisable tel quel", "licence": "MIT",
         "derniere_modification": "dépôt courant", "usage": "collecte des cinq sources, manifeste et reprise"},
        {"nom": "pipeline/local.py (ce dépôt) : objet_publiable, sirene_cj, siren_de", "verdict": "réutilisable tel quel",
         "licence": "MIT", "derniere_modification": "dépôt courant",
         "usage": "règle personnes physiques, catégorie juridique SIRENE, nettoyage des SIREN"},
        {"nom": "pipeline/prestations.py (ce dépôt)", "verdict": "à adapter", "licence": "MIT",
         "derniere_modification": "dépôt courant", "usage": "forme des écarts entre sources et des sources déclarées"},
        {"nom": "patrickaubert/asdep (paquet R, rdrr.io/github/patrickaubert/asdep)", "verdict": "inspiration seulement",
         "licence": "fichier LICENSE.md présent, type non affiché sur la page lue",
         "derniere_modification": "documentation construite le 2024-03-04",
         "usage": "lecture des classeurs DREES de l'aide sociale départementale ; en R et sur des millésimes antérieurs"},
        {"nom": "jeux DGCL, SRU, DREES sur data.gouv.fr et data.drees", "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "derniere_modification": "voir sources.*.collecte_le",
         "usage": "aucun outil public trouvé qui publie ces trois sources jointes par code INSEE et département"},
    ],
}

TYPES_PUBLICS = {"commune", "epci", "departement", "syndicat", "syndicat intercommunal", "syndicat mixte", "petr",
                 "collectivité à statut particulier"}
NOMS_GENERIQUES = {"COM", "COMMUNE", "EPCI", "NON RENSEIGNE", "DIVERS", "E", "NAN", "NONE", ""}

# DREES : (poste, mesure, onglet). Brute = avant récupérations et recouvrements ; nette = après.
SERIES_ASD = [
    ("total", "nette", "Tot-tab1"), ("total", "brute", "Tot-tab2"),
    ("personnes_agees", "nette", "PA-tab1"), ("personnes_agees", "brute", "PA-tab2"),
    ("apa", "brute", "PA-tab3"), ("pa_aide_domicile", "brute", "PA-tab4"), ("apa_domicile", "brute", "PA-tab5"),
    ("pa_aide_accueil", "brute", "PA-tab6"), ("ash_pa_etablissement", "apres_recuperations", "PA-tab7"),
    ("apa_etablissement", "brute", "PA-tab8"),
    ("personnes_handicapees", "nette", "PH-tab1"), ("personnes_handicapees", "brute", "PH-tab2"),
    ("ph_aide_domicile", "brute", "PH-tab3"), ("actp", "brute", "PH-tab4"), ("pch", "brute", "PH-tab5"),
    ("ph_aide_accueil", "brute", "PH-tab6"), ("ph_hebergement_etablissement", "brute", "PH-tab7"),
    ("ase", "nette", "ASE-tab1"), ("ase", "brute", "ASE-tab2"), ("ase_allocations", "brute", "ASE-tab3"),
    ("ase_actions_educatives", "brute", "ASE-tab4"), ("ase_prevention_specialisee", "brute", "ASE-tab5"),
    ("ase_placements", "brute", "ASE-tab6"), ("ase_placement_familial", "brute", "ASE-tab7"),
    ("ase_placements_hors_familles", "brute", "ASE-tab8"),
    ("rsa_insertion", "nette", "RSA-RMI-tab1"), ("rsa_insertion", "brute", "RSA-RMI-tab2"),
    ("rsa_allocation", "brute", "RSA-RMI-tab3"), ("rsa_insertion_hors_cui", "brute", "RSA-RMI-tab4"),
    ("rsa_cui", "brute", "RSA-RMI-tab5"),
    ("autres", "nette", "autres-tab1"), ("autres", "brute", "autres-tab2"),
]
POSTES = {
    "total": ("Ensemble de l'aide sociale départementale", None),
    "personnes_agees": ("Aide aux personnes âgées (hors ACTP et PCH des 60 ans ou plus)", None),
    "apa": ("Allocation personnalisée d'autonomie (APA), domicile et établissement", "personnes_agees"),
    "pa_aide_domicile": ("Personnes âgées : aide à domicile (APA à domicile et aide ménagère)", "personnes_agees"),
    "apa_domicile": ("APA à domicile", "personnes_agees"),
    "pa_aide_accueil": ("Personnes âgées : aide à l'accueil (APA en établissement, ASH, accueil familial)",
                        "personnes_agees"),
    "ash_pa_etablissement": ("Aide sociale à l'hébergement (ASH) des personnes âgées en établissement, après "
                             "récupérations auprès des bénéficiaires, obligés alimentaires et héritiers",
                             "personnes_agees"),
    "apa_etablissement": ("APA en établissement", "personnes_agees"),
    "personnes_handicapees": ("Aide aux personnes handicapées (y compris ACTP et PCH des 60 ans ou plus)", None),
    "ph_aide_domicile": ("Personnes handicapées : aide à domicile (PCH, ACTP, aides ménagères)",
                         "personnes_handicapees"),
    "actp": ("Allocation compensatrice pour tierce personne (ACTP)", "personnes_handicapees"),
    "pch": ("Prestation de compensation du handicap (PCH)", "personnes_handicapees"),
    "ph_aide_accueil": ("Personnes handicapées : aide à l'accueil (établissements, accueil familial, services "
                        "d'accompagnement)", "personnes_handicapees"),
    "ph_hebergement_etablissement": ("Personnes handicapées : hébergement et accueil de jour en établissement",
                                     "personnes_handicapees"),
    "ase": ("Aide sociale à l'enfance (ASE), hors personnel sauf assistants familiaux", None),
    "ase_allocations": ("ASE : allocations (mensuelles, secours, bourses)", "ase"),
    "ase_actions_educatives": ("ASE : actions éducatives (AED, AEMO)", "ase"),
    "ase_prevention_specialisee": ("ASE : prévention spécialisée", "ase"),
    "ase_placements": ("ASE : placements", "ase"),
    "ase_placement_familial": ("ASE : placement familial (assistants familiaux)", "ase_placements"),
    "ase_placements_hors_familles": ("ASE : placements hors familles d'accueil (établissements)", "ase_placements"),
    "rsa_insertion": ("RSA, RSO, RMI et insertion (allocation, insertion, contrats aidés)", None),
    "rsa_allocation": ("Allocation du RSA", "rsa_insertion"),
    "rsa_insertion_hors_cui": ("Insertion liée au RSA, hors contrats uniques d'insertion", "rsa_insertion"),
    "rsa_cui": ("Contrats uniques d'insertion (CUI) des bénéficiaires du RSA", "rsa_insertion"),
    "autres": ("Autres dépenses d'aide sociale (frais communs, personnel, autres)", None),
}
MESURES = {
    "brute": "dépenses brutes : avant déduction des recouvrements auprès d'autres collectivités, des remboursements "
             "de participations et de prestations et des récupérations auprès des bénéficiaires, de leurs obligés "
             "alimentaires ou de leurs héritiers (DREES)",
    "nette": "dépenses nettes : après déduction des récupérations et recouvrements ; elles englobent les dépenses "
             "prises en charge par l'État par l'intermédiaire de la CNSA, du FMDI et de la TICPE (DREES)",
    "apres_recuperations": "aide sociale à l'hébergement après déduction des récupérations auprès des bénéficiaires, "
                           "de leurs obligés alimentaires ou de leurs héritiers (DREES)",
}
# Département de local/geo -> collectivités de la DREES qui y exercent les compétences départementales.
COLLECTIVITES_DREES = {"67": ["67", "6AE"], "68": ["68", "6AE"], "69": ["69", "69D", "69M"],
                       "2A": ["2A", "20R"], "2B": ["2B", "20R"]}
PERIMETRES = {
    "6AE": "Collectivité européenne d'Alsace (depuis 2021) : compétences départementales du Bas-Rhin et du Haut-Rhin ; "
           "même série dans les fichiers 67 et 68, à ne pas additionner",
    "20R": "Collectivité de Corse (depuis 2018) : compétences départementales de la Corse-du-Sud et de la "
           "Haute-Corse ; même série dans les fichiers 2A et 2B, à ne pas additionner",
    "69": "territoire du Rhône : avant 2015, département du Rhône ; depuis 2015, Nouveau Rhône et Métropole de Lyon "
          "réunis (somme publiée par la DREES)",
    "69D": "Nouveau Rhône (département, depuis 2015)",
    "69M": "Métropole de Lyon (compétences départementales, depuis 2015)",
}
# Codes de la DREES -> code de la collectivité dans local/budgets/departements.json (population OFGL)
CODE_OFGL = {"6AE": ["67A"], "69D": ["69"], "69M": ["691"], "69": ["69", "691"]}
ISD_FI11 = "cont_depenses_brutes_aide_sociale_hab"

METHODE = {
    "investissement_etat": "un projet = une ligne du fichier DGCL de l'exercice ; département : celui du code INSEE de "
                           "la commune, à défaut celui du siège de l'EPCI (local/geo), à défaut le code département du "
                           "fichier (« 67A » rattaché à 67, « 20A » et « 20B » à 2A et 2B) ; nom : COG pour les "
                           "communes et les EPCI, dénomination SIRENE pour les autres personnes morales, à défaut nom "
                           "publié par la DGCL pour un type de collectivité ; taux = taux publié (subvention / coût HT)",
    "sru": "une édition = un fichier publié (population au 1er janvier de l'année d'édition, inventaire des logements "
           "sociaux au 1er janvier de l'année précédente) ; taux en pourcentage ; « Pas d'inventaire », « >25% », "
           "« Entrée au dispositif », « NC » gardés dans `taux_sru_texte` ou `lls_texte`, valeur numérique null ; "
           "« - € » dans la colonne du prélèvement (format comptable) lu comme 0 €, la chaîne publiée est gardée dans "
           "`prelevement_texte`",
    "aide_sociale": "milliers d'euros de la DREES convertis en euros (× 1 000, arrondi à l'euro) ; euros par habitant "
                    "calculés = euros / population OFGL de l'exercice (local/budgets/departements.json), 2 décimales ; "
                    "les indicateurs ISD sont repris tels que publiés par la DREES (leur dénominateur est celui de la "
                    "DREES) ; APA à domicile par bénéficiaire = dépenses couvertes de l'année / bénéficiaires payés "
                    "en décembre ; PCH par personne = montant versé pour décembre / personnes payées en décembre",
}
LIMITES = [
    "DETR, DSIL, DPV, DSID : montants attribués (programme 119), pas les paiements ; 2018 : SIREN souvent absent.",
    "Aide sociale : Mayotte hors du champ de l'enquête de la DREES ; Alsace et Corse publiées au niveau de la "
    "collectivité unique ; RSA recentralisé (Guyane, La Réunion, Seine-Saint-Denis, Pyrénées-Orientales) : la DREES "
    "publie 0 pour l'allocation à partir de l'année de recentralisation.",
    "Indicateurs ISD et calculs par habitant : dénominateurs différents (population DREES, population OFGL) ; les "
    "écarts sont publiés dans `ecarts`.",
    "SRU : seules les communes soumises au dispositif ou entrantes figurent dans l'inventaire.",
]


# --- Utilitaires -----------------------------------------------------------------------------------------------------

def propre(v) -> str:
    if v is None:
        return ""
    s = unicodedata.normalize("NFC", str(v)).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def nombre(v):
    """Nombre publié, ou None. Accepte « 1 234,5 », « 52,95 % », « 46 559,19 € »."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)
    s = propre(v).replace("€", "").replace("%", "").replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return None
    return float(s)


def marque(v):
    """Chaîne publiée à la place d'une valeur (ND, NR, NA, « Pas d'inventaire »...), sinon None."""
    if v is None or isinstance(v, (int, float)):
        return None
    s = propre(v)
    return s if s and nombre(s) is None else None


def euros(v):
    return None if v is None else int(round(v))


def par(montant, base, decimales=2):
    if montant is None or not base:
        return None
    return round(montant / base, decimales)


def dep_de_insee(code: str) -> str:
    return code[:3] if code.startswith("97") else code[:2]


def norm_dep(v: str) -> str | None:
    s = propre(v).upper().rstrip("-")
    if s in ("", "NAN", "NONE"):
        return None
    if s in ("20A", "2A"):
        return "2A"
    if s in ("20B", "2B"):
        return "2B"
    if s == "67A":
        return "67"
    if len(s) == 3 and s.startswith("0"):
        s = s[1:]
    if len(s) == 1:
        s = "0" + s
    return s


def ascii_maj(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper().strip()


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse 5 Mo ({n} octets) : découper")
    tmp = path.with_suffix(".part")
    tmp.write_text(texte + "\n", encoding="utf-8")
    tmp.replace(path)
    return n


def charger(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def ecart(cle, montant, autre_cle, autre, lecture, **contexte) -> dict | None:
    if montant is None or autre is None:
        return None
    d = round(montant - autre, 2)
    return {**contexte, "source": cle, "montant": montant, "autre_source": autre_cle, "autre_montant": autre,
            "ecart": d, "ecart_pct": round(d / autre * 100, 2) if autre else None, "lecture": lecture}


# --- Référentiel local (lecture seule) -------------------------------------------------------------------------------

def referentiel() -> dict:
    deps, communes, epci = {}, {}, {}
    for f in sorted((LOCAL / "geo").glob("*.json")):
        g = charger(f)
        deps[f.stem] = g["departement"]["nom"]
        for insee, c in g["communes"].items():
            communes[insee] = c
        for s, e in g.get("epci", {}).items():
            epci.setdefault(s, e)
    siren_insee = {c["siren"]: insee for insee, c in communes.items() if c.get("siren")}
    b = charger(LOCAL / "budgets" / "departements.json") or {}
    pop = {code: {a: v for a, v in (x.get("population") or {}).items()} for code, x in b.get("collectivites", {}).items()}
    idx = charger(LOCAL / "index.json") or {}
    siren_dep = {s: d for d, s in (idx.get("sirens", {}).get("departements") or {}).items()}
    return {"deps": deps, "communes": communes, "epci": epci, "siren_insee": siren_insee, "pop": pop,
            "siren_dep": siren_dep, "dep_siren": {d: s for s, d in siren_dep.items()}}


# --- 1. Investissement : DETR, DSIL, DPV, DSID -------------------------------------------------------------------

def lire_dgcl() -> list[dict]:
    lignes = []
    for f in sorted(DOSSIERS[ID_DGCL].glob("*.csv")):
        for r in csv.DictReader(io.StringIO(f.read_bytes().decode("utf-8-sig")), delimiter=";"):
            lignes.append(r)
    return lignes


def investissement(ref: dict, liste_prenoms: set | None = None) -> tuple[dict, dict]:
    """-> (par département, couverture). Département : INSEE, puis siège de l'EPCI, puis code du fichier."""
    import local  # lecture seule : règle personnes physiques et SIRENE (pipeline/local.py)
    import sirene
    lignes = lire_dgcl()
    sirens = sorted({s for r in lignes if (s := local.siren_de(r.get("beneficiaire_siren")))})
    cj = local.sirene_cj(set(sirens)) if sirens else {}
    communes, epci, siren_insee = ref["communes"], ref["epci"], ref["siren_insee"]
    par_dep = defaultdict(lambda: {"benef": {}, "exclus": defaultdict(lambda: [0, 0.0, 0.0]),
                                   "anomalies": []})
    couv = {"lignes": 0, "annees": set(), "dispositifs": defaultdict(int), "programmes": set(),
            "sans_departement": [0, 0.0], "exclus": [0, 0.0], "nommes": 0, "intitules_retires": 0,
            "subvention_superieure_au_cout": 0, "siren_absent": 0}
    for r in lignes:
        couv["lignes"] += 1
        an = propre(r.get("exercice"))[:4]
        disp = propre(r.get("dispositif"))
        couv["annees"].add(an)
        couv["dispositifs"][disp] += 1
        couv["programmes"].add(propre(r.get("programme")))
        sub, cout, taux = nombre(r.get("subvention")), nombre(r.get("cout_ht")), nombre(r.get("taux"))
        typ = propre(r.get("beneficiaire_type")).lower() or None
        siren = local.siren_de(r.get("beneficiaire_siren")) or None
        insee = propre(r.get("beneficiaire_code_insee")) or None
        nom_src = propre(r.get("beneficiaire_nom"))
        if not insee and not disp.startswith("DSID") and re.fullmatch(r"\d[\dAB]\d{3}", nom_src) \
                and nom_src in communes:
            insee = nom_src  # code INSEE saisi à la place du nom (la DSID va aux départements : jamais)
        if insee and insee not in communes:
            insee = None
        if not siren:
            couv["siren_absent"] += 1
        if siren and siren in epci:
            insee = None  # intercommunalité : le code INSEE éventuel est celui de la commune siège
        elif siren and siren in siren_insee:
            insee = siren_insee[siren]
        elif insee and typ in (None, "commune"):
            siren = communes[insee].get("siren") or siren
        elif insee:
            insee = None  # code INSEE d'un bénéficiaire qui n'est pas une commune : sert seulement au département
        dep = (dep_de_insee(insee) if insee else None) or \
              ((epci[siren].get("departement_siege") or "").split(",")[0] or None if siren in epci else None) or \
              (dep_de_insee(propre(r.get("beneficiaire_code_insee"))) if propre(r.get("beneficiaire_code_insee"))
               in communes else None) or norm_dep(r.get("beneficiaire_dep"))
        if dep not in ref["deps"]:
            couv["sans_departement"][0] += 1
            couv["sans_departement"][1] += sub or 0
            continue
        # identité publiable
        nom = None
        if typ == "departement" and not insee and (siren in ref["siren_dep"] or not siren):
            siren = siren or ref["dep_siren"].get(dep)
            nom = f"Département : {ref['deps'][dep]}"
        elif insee:
            nom, typ = communes[insee]["nom"], typ or "commune"
        elif siren and siren in epci:
            nom, typ = epci[siren]["nom"], typ or "epci"
        elif siren and siren in cj:
            c, denom = cj[siren]
            if sirene.personne_morale(c):
                nom = denom or (nom_src if typ in TYPES_PUBLICS else None)
            else:
                siren = None  # personne physique ou groupement : jamais nommé
        elif typ in TYPES_PUBLICS and ascii_maj(nom_src) not in NOMS_GENERIQUES:
            nom = local.objet_publiable(nom_src, liste_prenoms, 120)
        if not nom:
            x = par_dep[dep]["exclus"][an]
            x[0] += 1
            x[1] += sub or 0
            x[2] += cout or 0
            couv["exclus"][0] += 1
            couv["exclus"][1] += sub or 0
            continue
        cle = siren or (f"insee-{insee}" if insee else f"nom-{typ or 'inconnu'}-{ascii_maj(nom)}")
        b = par_dep[dep]["benef"].setdefault(cle, {"id": cle, "siren": siren, "insee": insee, "type": typ, "nom": nom,
                                                   "projets": []})
        if b["type"] is None and typ:
            b["type"] = typ
        intitule = local.objet_publiable(r.get("intitule"), liste_prenoms, 300)
        if propre(r.get("intitule")) and intitule is None:
            couv["intitules_retires"] += 1
        p = [int(an), disp, intitule, euros(cout), euros(sub), round(taux, 4) if taux is not None else None]
        b["projets"].append(p)
        couv["nommes"] += 1
        if sub is not None and cout is not None and sub > cout:
            couv["subvention_superieure_au_cout"] += 1
            par_dep[dep]["anomalies"].append({"beneficiaire": cle, "exercice": int(an), "dispositif": disp,
                                              "constat": "subvention publiée supérieure au coût HT publié",
                                              "subvention_eur": euros(sub), "cout_ht_eur": euros(cout)})
    return par_dep, couv


def bloc_investissement(d: dict, ref: dict, dep: str, id_dep: dict) -> dict:
    benefs = []
    totaux = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for b in d["benef"].values():
        b["projets"].sort(key=lambda p: (-p[0], -(p[4] or 0), p[1], p[2] or "", p[3] or 0))
        t = defaultdict(lambda: [0, 0, 0])
        for p in b["projets"]:
            t[str(p[0])][0] += 1
            t[str(p[0])][1] += p[4] or 0
            t[str(p[0])][2] += p[3] or 0
            totaux[str(p[0])][p[1]][0] += 1
            totaux[str(p[0])][p[1]][1] += p[4] or 0
        b["totaux"] = {a: {"projets": v[0], "subvention_eur": v[1], "cout_ht_eur": v[2]} for a, v in sorted(t.items())}
        b["subvention_totale_eur"] = sum(v[1] for v in t.values())
        if b["insee"]:
            b["lien"] = {"fichier": f"local/geo/{dep_de_insee(b['insee'])}.json", "cle": f"communes.{b['insee']}"}
        benefs.append(b)
    benefs.sort(key=lambda b: (-b["subvention_totale_eur"], b["id"]))
    exclus = {a: {"projets": v[0], "subvention_eur": euros(v[1]), "cout_ht_eur": euros(v[2])}
              for a, v in sorted(d["exclus"].items())}
    for a, v in exclus.items():
        totaux[a]["non_nommes"] = [v["projets"], v["subvention_eur"]]
    # commune -> bénéficiaires qui la concernent : la commune elle-même, son EPCI (fichier du siège de l'EPCI)
    par_commune = defaultdict(set)
    for b in benefs:
        if b["insee"]:
            par_commune[b["insee"]].add((b["id"], dep))
    for insee, c in ref["communes"].items():
        if c.get("departement") == dep and c.get("epci") in id_dep:
            par_commune[insee].add((c["epci"], id_dep[c["epci"]]))
    annees = sorted({a for b in benefs for a in b["totaux"]} | set(exclus))
    return {
        "annees": [int(a) for a in annees],
        "format_projet": ["exercice", "dispositif", "intitule", "cout_ht_eur", "subvention_eur", "taux"],
        "ordre": "bénéficiaires par subvention totale décroissante, puis identifiant ; projets par exercice "
                 "décroissant, puis subvention décroissante",
        "beneficiaires": benefs,
        "par_commune": {k: [list(x) for x in sorted(v)] for k, v in sorted(par_commune.items())},
        "format_par_commune": "code INSEE -> [[identifiant du bénéficiaire, département du fichier territoires]]",
        "totaux": {a: {k: {"projets": v[0], "subvention_eur": v[1]} for k, v in sorted(x.items())}
                   for a, x in sorted(totaux.items())},
        "exclus_personnes_physiques_ou_non_identifies": exclus,
        "anomalies": sorted(d["anomalies"], key=lambda x: (x["beneficiaire"], x["exercice"], x["dispositif"],
                                                           x["subvention_eur"])),
    }


# --- 2. SRU ---------------------------------------------------------------------------------------------------------

def _col(entete: list[str], motif: str) -> int | None:
    rx = re.compile(motif, re.I)
    for i, c in enumerate(entete):
        if rx.search(ascii_maj(c).replace(" ", "_")):
            return i
    return None


def lire_sru() -> dict:
    """-> {edition: {insee: {...}}} ; édition = année de la population municipale du fichier."""
    editions = {}
    for f in sorted(DOSSIERS[ID_SRU].glob("*.csv")):
        brut = f.read_bytes()
        try:
            t = brut.decode("utf-8-sig")
        except UnicodeDecodeError:
            t = brut.decode("cp1252")
        lignes_txt = t.splitlines()
        sep = ";" if sum(x.count(";") for x in lignes_txt[:3]) > sum(x.count(",") for x in lignes_txt[:3]) else ","
        rows = list(csv.reader(io.StringIO(t), delimiter=sep))
        hi = next(i for i, r in enumerate(rows) if any("INSEE" in c for c in r))
        h = [propre(c) for c in rows[hi]]
        ci = {k: _col(h, m) for k, m in {
            "insee": r"CODE_INSEE", "nom": r"^NOM_COMMUNE", "population": r"POPULATION_MUNICIPALE_01_01_(\d{4})",
            "epci": r"CODE_SIREN_EPCI", "lls": r"NOMBRE_LLS", "taux": r"^TAUX_SRU", "cible": r"^TAUX_CIBLE",
            "deficitaire": r"DEFICITAIRE", "carencee": r"CARENCEE", "exemptee": r"EXEMPTEE",
            "prelevement": r"PRELEVEMENT_NET"}.items()}
        an_pop = re.search(r"(\d{4})", h[ci["population"]]).group(1)
        inv = re.search(r"(\d{2})_(\d{2})_(\d{4})", h[ci["lls"]] or "")
        prel = re.search(r"(\d{4})", h[ci["prelevement"]]) if ci["prelevement"] is not None else None
        ed = {"_fichier": f.name, "_inventaire_au": f"{inv.group(3)}-{inv.group(2)}-{inv.group(1)}" if inv else None,
              "_prelevement_annee": int(prel.group(1)) if prel else None,
              "_colonnes": {k: h[i] for k, i in ci.items() if i is not None}}

        def v(r, k, ci=ci):
            i = ci[k]
            return r[i] if i is not None and i < len(r) else None

        def drapeau(x):
            s = propre(x)
            return True if s == "1" else False if s == "0" else None

        communes = {}
        for r in rows[hi + 1:]:
            insee = propre(v(r, "insee"))
            if not re.fullmatch(r"\d[\dAB]\d{3}", insee):
                continue
            taux_t, lls_t, prel_t = propre(v(r, "taux")), propre(v(r, "lls")), propre(v(r, "prelevement"))
            prelev = None
            if prel_t:
                prelev = 0.0 if re.fullmatch(r"-\s*€?", prel_t) else nombre(prel_t)
            x = {"nom": propre(v(r, "nom")), "population": euros(nombre(v(r, "population"))),
                 "epci": propre(v(r, "epci")) or None,
                 "lls": euros(nombre(lls_t)), "taux_sru": nombre(taux_t), "taux_cible": nombre(v(r, "cible")),
                 "deficitaire": drapeau(v(r, "deficitaire")), "carencee": drapeau(v(r, "carencee")),
                 "exemptee": drapeau(v(r, "exemptee"))}
            if ci["prelevement"] is not None:
                x["prelevement_net_eur"] = round(prelev, 2) if prelev is not None else None
                if prel_t and (prelev is None or not re.search(r"\d", prel_t)):
                    x["prelevement_texte"] = prel_t
            if marque(taux_t):
                x["taux_sru_texte"] = marque(taux_t)
            if marque(lls_t):
                x["lls_texte"] = marque(lls_t)
            communes[insee] = x
        ed["communes"] = communes
        editions[an_pop] = ed
    return dict(sorted(editions.items()))


def bloc_sru(editions: dict, dep: str, ref: dict) -> dict | None:
    communes = defaultdict(dict)
    for an, ed in editions.items():
        for insee, x in ed["communes"].items():
            if dep_de_insee(insee) != dep:
                continue
            c = communes[insee]
            c.setdefault("nom", ref["communes"].get(insee, {}).get("nom") or x["nom"])
            c.setdefault("editions", {})[an] = {k: v for k, v in x.items() if k != "nom"}
    if not communes:
        return None
    return {"editions": [{"edition": int(an), "inventaire_au": ed["_inventaire_au"],
                          "prelevement_annee": ed["_prelevement_annee"]} for an, ed in editions.items()],
            "communes": {k: communes[k] for k in sorted(communes)}}


# --- 3. Aide sociale départementale (DREES) ------------------------------------------------------------------------

def _classeur(motif: str, dossier: Path):
    import openpyxl
    f = sorted(p for p in dossier.glob("*.xlsx") if re.search(motif, p.name, re.I))
    if not f:
        raise SystemExit(f"{dossier} : aucun classeur « {motif} » (python pipeline/territoires.py collecter)")
    return openpyxl.load_workbook(f[-1], read_only=True, data_only=True), f[-1].name


def lire_asd() -> tuple[dict, dict, dict, list]:
    """-> (series[code][(poste, mesure)][annee] = valeur, noms, totaux nationaux, années)."""
    wb, _ = _classeur(r"s_ries_longues|series_longues", DOSSIERS[ID_ASD])
    series, noms, nat, marques = defaultdict(dict), {}, defaultdict(dict), defaultdict(int)
    annees = set()
    for poste, mesure, onglet in SERIES_ASD:
        rows = list(wb[onglet].iter_rows(values_only=True))
        hi = next(i for i, r in enumerate(rows) if r[0] == "Code région")
        cols = {j: str(c) for j, c in enumerate(rows[hi]) if c is not None and re.fullmatch(r"\d{4}", str(c))}
        for r in rows[hi + 1:]:
            if r[0] is None and r[1] is None:
                break
            tete = propre(r[0])
            if tete.startswith("TOTAL"):
                cle = {"TOTAL estimé France métropolitaine": "metropole", "TOTAL estimé DROM (hors Mayotte)": "drom",
                       "TOTAL estimé France métropolitaine et DROM (hors Mayotte)": "france"}.get(tete)
                if cle:
                    nat[cle][(poste, mesure)] = {a: euros(nombre(r[j]) * 1000) if nombre(r[j]) is not None else None
                                                 for j, a in cols.items()}
                continue
            code = propre(r[1])
            if not r[2]:  # ligne de région
                continue
            noms[code] = propre(r[2])
            vals = {}
            for j, a in cols.items():
                x = r[j] if j < len(r) else None
                n = nombre(x)
                vals[a] = euros(n * 1000) if n is not None else None
                if marque(x):
                    marques[marque(x)] += 1
                annees.add(a)
            series[code][(poste, mesure)] = vals
    return series, noms, nat, sorted(annees)


def lire_isd() -> tuple[dict, dict]:
    import duckdb
    con = duckdb.connect()
    rows = con.execute(f"""select code_dep, id_indicateur, code_isd, libelle_indicateur, annee, value
                           from '{ISD_PARQUET}' order by code_dep, id_indicateur, annee""").fetchall()
    isd, libelles = defaultdict(lambda: defaultdict(dict)), {}
    for code, ind, cisd, lib, an, val in rows:
        libelles[ind] = {"code_isd": cisd, "libelle": lib}
        isd[propre(code)][ind][str(an)] = nombre(val)
    return isd, dict(sorted(libelles.items()))


def _lignes_dep(rows, hi):
    for r in rows[hi + 1:]:
        if len(r) > 2 and r[1] is not None and r[2] is not None:
            code = propre(r[1])
            if re.fullmatch(r"\d{2,3}|2A|2B|20R|6AE|69D|69M|\d{2}[A-Z]", code):
                yield code, r


def lire_apa_pch() -> tuple[dict, dict, list]:
    """-> apa[code][annee] = (beneficiaires_decembre, depenses_couvertes) ; pch[code][annee] = (personnes, montant)."""
    apa, pch, notes = defaultdict(dict), defaultdict(dict), []
    wb, _ = _classeur(r"^APA", DOSSIERS[ID_APAPCH])
    rows = list(wb["APA_dom"].iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r[0] == "Code région")
    cols = {j: str(c) for j, c in enumerate(rows[hi]) if c is not None and re.fullmatch(r"\d{4}", str(c))}
    benef = defaultdict(dict)
    for code, r in _lignes_dep(rows, hi):
        for j, a in cols.items():
            benef[code][a] = r[j] if j < len(r) else None
    for ws in wb.worksheets:
        if not re.fullmatch(r"\d{4}", ws.title):
            continue
        rows = list(ws.iter_rows(values_only=True))
        hi = next((i for i, r in enumerate(rows) if len(r) > 1 and propre(r[1]).startswith("Code")), None)
        if hi is None:
            continue
        jt = next((j for r in rows[max(0, hi - 1):hi + 1] for j, c in enumerate(r)
                   if c and "Total des dépenses couvertes" in propre(c)), None)
        if jt is None:
            notes.append(f"APA à domicile {ws.title} : seules les dépenses d'intervenants sont publiées, non reprises")
            continue
        for code, r in _lignes_dep(rows, hi):
            apa[code][ws.title] = (benef[code].get(ws.title), r[jt] if jt < len(r) else None)
    wb, _ = _classeur(r"^PCH", DOSSIERS[ID_APAPCH])
    tables = defaultdict(dict)
    for ws in wb.worksheets:
        m = re.fullmatch(r"Tabl\.([12])-(\d{4})", ws.title)
        if not m:
            continue
        rows = list(ws.iter_rows(values_only=True))
        hi = next((i for i, r in enumerate(rows) if len(r) > 1 and propre(r[1]).startswith("Code")), None)
        jt = next((j for j, c in enumerate(rows[hi]) if c and propre(c).upper().startswith("TOTAL PCH")), None) \
            if hi is not None else None
        if jt is None:
            notes.append(f"PCH {ws.title} : colonne « TOTAL PCH » absente, onglet non repris")
            continue
        for code, r in _lignes_dep(rows, hi):
            tables[(m.group(1), m.group(2))][code] = r[jt] if jt < len(r) else None
    for (t, an), vals in tables.items():
        for code, v in vals.items():
            p = pch[code].setdefault(an, [None, None])
            p[0 if t == "1" else 1] = v
    return apa, pch, notes


def valeur_et_marque(x):
    n = nombre(x)
    return (euros(n) if n is not None else None), marque(x)


def bloc_aide_sociale(dep: str, ref: dict, asd: tuple, isd: tuple, apa_pch: tuple) -> tuple[dict | None, list]:
    series, noms, _nat, annees = asd
    isd_v, isd_lib = isd
    apa, pch, _ = apa_pch
    codes = COLLECTIVITES_DREES.get(dep, [dep])
    out, ecarts = [], []
    for code in codes:
        if code not in series and code not in isd_v:
            continue
        pops = [ref["pop"].get(c) for c in CODE_OFGL.get(code, [code])]
        pop = {}
        if pops and all(pops):
            for a in sorted(set.intersection(*[set(p) for p in pops])):
                if all(p.get(a) for p in pops):
                    pop[a] = sum(p[a] for p in pops)
        postes = {}
        for (poste, mesure), vals in series.get(code, {}).items():
            postes.setdefault(poste, {})[mesure] = {"eur": vals,
                                                    "eur_hab": {a: par(vals.get(a), pop[a]) for a in sorted(pop)
                                                                if a in vals}}
        ind = {k: dict(sorted(v.items())) for k, v in sorted(isd_v.get(code, {}).items())}
        apad = {}
        for an, (b, dpc) in sorted(apa.get(code, {}).items()):
            bn, bm = valeur_et_marque(b)
            dn, dm = valeur_et_marque(dpc)
            apad[an] = {"beneficiaires_decembre": bn, "depenses_couvertes_eur": dn,
                        "eur_par_beneficiaire": par(dn, bn)}
            if bm or dm:
                apad[an]["marque_source"] = bm or dm
        pchd = {}
        for an, (pers, mont) in sorted(pch.get(code, {}).items()):
            pn, pm = valeur_et_marque(pers)
            mn, mm = valeur_et_marque(mont)
            pchd[an] = {"personnes_payees_decembre": pn, "montant_decembre_eur": mn,
                        "eur_par_personne_decembre": par(mn, pn)}
            if pm or mm:
                pchd[an]["marque_source"] = pm or mm
        c = {"code": code, "nom": noms.get(code) or ref["deps"].get(code) or code, "postes": postes,
             "population_ofgl": pop, "isd": ind, "apa_domicile": apad, "pch": pchd}
        if code in PERIMETRES:
            c["perimetre"] = PERIMETRES[code]
        if not pop:
            c["note"] = "population OFGL non publiée pour cette collectivité : euros par habitant non calculés"
        out.append(c)
        # écarts entre sources
        brut = postes.get("total", {}).get("brute", {})
        for a in sorted(brut.get("eur_hab", {})):
            e = ecart("calcul_drees_376_population_ofgl", brut["eur_hab"][a], "drees_isd_fi11",
                      ind.get(ISD_FI11, {}).get(a),
                      "dépenses totales brutes par habitant : même numérateur (DREES), dénominateurs différents "
                      "(population OFGL de l'exercice ; population retenue par la DREES)",
                      collectivite=code, annee=int(a), grandeur="eur_par_habitant")
            if e:
                ecarts.append(e)
        apa376 = postes.get("apa_domicile", {}).get("brute", {}).get("eur", {})
        for an, x in apad.items():
            e = ecart("drees_376_apa_domicile_brute", apa376.get(an), "drees_apa_depenses_couvertes",
                      x["depenses_couvertes_eur"],
                      "champs différents : dépenses brutes d'APA à domicile (comptes du département) ; dépenses "
                      "couvertes par l'APA à domicile après participation des bénéficiaires, données transmises "
                      "par le département, parfois partielles",
                      collectivite=code, annee=int(an), grandeur="eur")
            if e:
                ecarts.append(e)
    if not out:
        return None, []
    return {"collectivites": out}, ecarts


# --- Production ------------------------------------------------------------------------------------------------------

def manifeste() -> dict:
    p = LAKE / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    ref = referentiel()
    if not ref["deps"]:
        raise SystemExit("site/data/local/geo absent : lancer pipeline/local.py d'abord")
    man = manifeste()
    inaccessibles = []
    for cle, s in SOURCES.items():
        sid = s.get("id_catalogue")
        if not sid:
            continue
        e = man.get(sid, {})
        s["collecte_le"] = (e.get("collecte_le") or "")[:10] or None
        if e.get("statut") not in ("ok", "partiel"):
            inaccessibles.append({"source": cle, "constat": e.get("erreur") or "absente de l'entrepôt",
                                  "statut": e.get("statut")})
    inv, couv_inv = investissement(ref)
    id_dep = {cle: dep for dep, d in sorted(inv.items()) for cle in d["benef"]}
    sru = lire_sru()
    asd = lire_asd()
    isd = lire_isd()
    apa_pch = lire_apa_pch()
    date = date_sources("collectivites", "secu")
    millesime = (f"Projets {min(couv_inv['annees'])} à {max(couv_inv['annees'])} ; SRU éditions "
                 f"{min(sru)} à {max(sru)} ; aide sociale {asd[3][0]} à {asd[3][-1]} ; sources collectées au {date}")
    source = "DGCL (DETR, DSIL, DPV, DSID), ministère chargé du logement (inventaire SRU), DREES (enquête Aide " \
             "sociale, ISD, APA et PCH) ; liens vers site/data/local"
    sortie.mkdir(parents=True, exist_ok=True)
    for p in sortie.glob("*.json"):
        p.unlink()
    resume, ecarts_tous, tailles = [], [], {}
    totaux_inv = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    cmp_local = {"communes_comparees": 0, "egales": 0, "differences": []}
    for dep in sorted(ref["deps"]):
        doc = {"millesime": millesime, "source": source,
               "unite": "euros ; euros par habitant ; taux en pourcentage (SRU) ou en part (projets)",
               "date_sources": date, "departement": {"code": dep, "nom": ref["deps"][dep]}}
        liens = {}
        for nom_lien, rel in (("geo", f"local/geo/{dep}.json"), ("dotations_communes", f"local/dotations/communes/{dep}.json"),
                              ("taux", f"local/taux/{dep}.json"), ("budget_departement", "local/budgets/departements.json"),
                              ("dotations_departement", "local/dotations/departements.json"),
                              ("fonctions_departement", "local/budgets/fonctions/departements.json")):
            if (SITE / rel).exists():
                liens[nom_lien] = rel
        doc["liens"] = liens
        b = bloc_investissement(inv[dep], ref, dep, id_dep) if dep in inv else None
        if b:
            doc["investissement_etat"] = b
            for a, x in b["totaux"].items():
                for k, v in x.items():
                    totaux_inv[a][k][0] += v["projets"]
                    totaux_inv[a][k][1] += v["subvention_eur"]
            # contrôle croisé avec local/dotations/communes (15 plus gros projets par année, totaux complets)
            dl = charger(SITE / "local" / "dotations" / "communes" / f"{dep}.json") or {}
            for insee, par_an in sorted((dl.get("investissement_etat") or {}).items()):
                ids = [x for x in b["beneficiaires"] if x["insee"] == insee]
                for a, x in sorted(par_an.items()):
                    cmp_local["communes_comparees"] += 1
                    t = sum(y["totaux"].get(a, {}).get("subvention_eur", 0) for y in ids)
                    if abs(t - x["total"]) <= 1:
                        cmp_local["egales"] += 1
                    else:
                        cmp_local["differences"].append({"insee": insee, "annee": int(a), "territoires_eur": t,
                                                         "local_eur": x["total"]})
        s = bloc_sru(sru, dep, ref)
        if s:
            doc["sru"] = s
        a_s, ecarts = bloc_aide_sociale(dep, ref, asd, isd, apa_pch)
        if a_s:
            doc["aide_sociale"] = a_s
        doc["ecarts"] = ecarts
        ecarts_tous += [{**e, "departement": dep} for e in ecarts]
        tailles[dep] = dump(sortie / f"{dep}.json", doc)
        resume.append({"code": dep, "nom": ref["deps"][dep], "fichier": f"territoires/{dep}.json",
                       "projets": sum(len(x["projets"]) for x in b["beneficiaires"]) if b else 0,
                       "beneficiaires_nommes": len(b["beneficiaires"]) if b else 0,
                       "communes_sru": len(s["communes"]) if s else 0,
                       "aide_sociale": [c["code"] for c in a_s["collectivites"]] if a_s else []})
    # écarts nationaux : somme des départements et total estimé par la DREES
    series, _noms, nat, annees = asd
    ecarts_nat = []
    for (poste, mesure), vals in sorted(nat.get("france", {}).items()):
        if (poste, mesure) not in (("total", "brute"), ("total", "nette")):
            continue
        for a in annees:
            # chaque territoire une fois : la collectivité unique quand elle publie, sinon ses départements
            somme, manque = 0, False
            for c in sorted(series):
                if c in ("69D", "69M"):
                    continue
                if c in ("67", "68") and series.get("6AE", {}).get((poste, mesure), {}).get(a) is not None:
                    continue
                if c in ("2A", "2B") and series.get("20R", {}).get((poste, mesure), {}).get(a) is not None:
                    continue
                if c in ("6AE", "20R") and series[c].get((poste, mesure), {}).get(a) is None:
                    continue
                v = series[c].get((poste, mesure), {}).get(a)
                if v is None:
                    manque = True
                    continue
                somme += v
            e = ecart("somme_des_collectivites", somme, "drees_total_estime", vals.get(a),
                      "le total de la DREES est estimé : il complète les collectivités non répondantes ; la somme "
                      "ne compte que les valeurs publiées" + (" (au moins une valeur absente)" if manque else ""),
                      poste=poste, mesure=mesure, annee=int(a), grandeur="eur")
            if e:
                ecarts_nat.append(e)
    isd_lib = isd[1]
    apa, pch, notes = apa_pch
    index = {
        "millesime": millesime, "source": source, "unite": "euros",
        "date_sources": date,
        "departements": resume,
        "jointure": "les communes sont désignées par leur code INSEE, les mêmes clés que local/geo/<dep>.json "
                    "(communes) ; les intercommunalités et les autres bénéficiaires par leur SIREN ; les départements "
                    "par le code de local/geo",
        "couverture": {
            "investissement_etat": {
                "annees": sorted(int(a) for a in couv_inv["annees"]), "projets": couv_inv["lignes"],
                "projets_nommes": couv_inv["nommes"],
                "dispositifs": dict(sorted(couv_inv["dispositifs"].items())),
                "programmes": sorted(couv_inv["programmes"]),
                "exclus_personnes_physiques_ou_non_identifies": {"projets": couv_inv["exclus"][0],
                                                                 "subvention_eur": euros(couv_inv["exclus"][1])},
                "sans_departement": {"projets": couv_inv["sans_departement"][0],
                                     "subvention_eur": euros(couv_inv["sans_departement"][1])},
                "siren_absent_a_la_source": couv_inv["siren_absent"],
                "intitules_retires": couv_inv["intitules_retires"],
                "subvention_superieure_au_cout": couv_inv["subvention_superieure_au_cout"],
                "departements": sum(1 for r in resume if r["projets"]),
            },
            "sru": {"editions": [{"edition": int(a), "communes": len(e["communes"]), "fichier_source": e["_fichier"],
                                  "inventaire_au": e["_inventaire_au"], "prelevement_annee": e["_prelevement_annee"],
                                  "colonnes_source": e["_colonnes"]} for a, e in sru.items()],
                    "departements": sum(1 for r in resume if r["communes_sru"])},
            "aide_sociale": {"annees": [int(a) for a in annees], "collectivites_drees": len(series),
                             "departements": sum(1 for r in resume if r["aide_sociale"]),
                             "isd_indicateurs": isd_lib,
                             "apa_domicile_annees": sorted({int(a) for v in apa.values() for a in v}),
                             "pch_annees": sorted({int(a) for v in pch.values() for a in v}),
                             "notes": notes},
        },
        "postes": [{"id": k, "nom": v[0], "parent": v[1],
                    "mesures": {m: o for p, m, o in SERIES_ASD if p == k}} for k, v in POSTES.items()],
        "mesures": MESURES,
        "totaux": {
            "investissement_etat": {a: {k: {"projets": v[0], "subvention_eur": v[1]} for k, v in sorted(x.items())}
                                    for a, x in sorted(totaux_inv.items())},
            "aide_sociale_drees": {z: {f"{p}.{m}": v for (p, m), v in sorted(x.items())}
                                   for z, x in sorted(nat.items())},
        },
        "ecarts": ecarts_nat,
        "ecarts_departements": {"nombre": len(ecarts_tous),
                                "par_grandeur": dict(sorted(_compte(ecarts_tous, "source").items()))},
        "controle_local": {**cmp_local, "differences": cmp_local["differences"][:50],
                           "lecture": "total des subventions par commune et par exercice : liste complète de ce "
                                      "module comparée au total de local/dotations/communes/<dep>.json, même source"},
        "contrat_detr": "le contrat (2.15) annonce « DETR/DSIL/DPV/DSID par projet » : la source est déclarée dans "
                        "collecte/catalogue.json (" + ID_DGCL + ") ; local/dotations/communes garde les 15 projets "
                        "les plus élevés par commune et par exercice, la liste complète par projet est ici",
        "methode": METHODE,
        "limites": LIMITES,
        "regle": "une valeur absente ou masquée à la source reste null avec sa marque, jamais 0 ; deux sources ne sont "
                 "jamais additionnées, leurs écarts sont publiés ; bénéficiaires nommés : personnes morales seulement",
        "tailles_octets": {"max": max(tailles.values()), "total": sum(tailles.values())},
        "sources": {k: dict(sorted(v.items())) for k, v in sorted(SOURCES.items())},
        "sources_inaccessibles": inaccessibles,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(sortie / "index.json", index)
    print(f"territoires : {len(resume)} départements, {couv_inv['nommes']} projets nommés, "
          f"{sum(r['communes_sru'] for r in resume)} communes SRU, {len(ecarts_tous)} écarts départementaux, "
          f"fichier max {max(tailles.values())} octets")
    return index


def _compte(lignes, cle):
    c = defaultdict(int)
    for x in lignes:
        c[x[cle]] += 1
    return c


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
