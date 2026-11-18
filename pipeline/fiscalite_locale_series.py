"""Séries longues de la fiscalité directe locale par commune : taux votés et produits, 2010 à la dernière année publiée.

Source unique : fichiers annuels du « recensement des éléments d'imposition à la fiscalité directe locale » (REI) de
la DGFiP (data.economie.gouv.fr, pièces jointes du jeu impots-locaux-fichier-de-recensement-des-elements-dimposition-
a-la-fiscalite-dir, Licence Ouverte). Une ligne par commune et par année : taux et montants émis au profit de la
commune, de son intercommunalité à fiscalité propre (et du département pour le foncier bâti jusqu'en 2020), pour la
taxe foncière sur les propriétés bâties et non bâties, la taxe d'habitation (résidences principales jusqu'en 2022,
résidences secondaires ensuite), la cotisation foncière des entreprises et la taxe d'enlèvement des ordures ménagères.

Complément de pipeline/local.py, sans doublon : `site/data/local/taux/<dep>.json` publie déjà, pour les trois
dernières années (jeu fiscalite-locale-des-particuliers), les taux du foncier bâti et non bâti, de la taxe
d'habitation sur les résidences secondaires et de la taxe d'enlèvement des ordures ménagères. Ces taux-là sont null
ici pour ces années (`deja_publie` : fichier et colonne à lire) ; les produits et la cotisation foncière des
entreprises, absents de local/taux, sont publiés pour toutes les années. Un contrôle compare les deux sources sur
les années communes (`controles.local_taux`), sans trancher.

Entrées (data/lake/fiscalite_locale_series/, hors git) :
  rei_<annee>.zip                 téléchargé par `collecter`, contrôlé par collecte/integrite.py, SUPPRIMÉ après
                                  extraction (fichiers lourds : 20 à 130 Mo compressés, jusqu'à 1 Go de XML)
  extraits/rei_<annee>.csv.gz     colonnes retenues seulement (environ 1 Mo par année), entrée de `produire`
  extraits/rei_<annee>.json       variables lues (code REI, titre, position), URL, empreinte et date de collecte
  lecture seule : site/data/local/taux/<dep>.json (contrôle et renvois) ; l'archive REI 2025 déjà présente dans
  data/lake/fiscalite/ (pipeline/prelevements.py) est lue sans être téléchargée de nouveau ni supprimée.
Sorties (site/data/fiscalite_locale_series/, chaque fichier < 1 Mo, avec `millesime` et `source`) :
  index.json                      années, séries, variables lues par année, ruptures, renvois vers local/taux,
                                  fichiers par département, totaux nationaux, contrôles, sources, recherche publique
  communes/<dep>.json             par commune : `taux` et `produits`, une valeur par année (alignée sur `annees`) ;
  communes/<dep>_<k>.json         découpage en parties (codes Insee contigus) quand le département dépasse 500 Ko

Commandes :
  python pipeline/fiscalite_locale_series.py collecter [--annees 2010-2025] [--force]   # réseau, année par année
  python pipeline/fiscalite_locale_series.py produire [--sortie DOSSIER]                # sans réseau
  python pipeline/fiscalite_locale_series.py                                            # les deux

Règles : une cellule vide ou absente reste null (jamais 0) ; un 0 publié reste 0 (par exemple taux communal de
cotisation foncière des entreprises nul dans une intercommunalité à fiscalité professionnelle unique) ; chaque année
est lue dans la géographie de son fichier (codes Insee de l'année, aucune recomposition des communes fusionnées) ;
aucune valeur estimée, aucune commune classée ; dates : date de collecte des extraits (SOURCE_DATE_EPOCH prioritaire,
comme pipeline/reproductible.py) ; tris explicites : deux productions sur les mêmes extraits sont identiques.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import iterparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch  # noqa: E402  (fetch.get, fetch.remplacer_si_valide : collecte/integrite.py)

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
DOSSIER_LAC = LAKE / "fiscalite_locale_series"
EXTRAITS = DOSSIER_LAC / "extraits"
REI_PRELEVEMENTS = (LAKE / "fiscalite" / "economie__impots-locaux-fichier-de-recensement-des-elements-dimposition-a-la-"
                    "fiscalite-dir")
SITE = ROOT / "site" / "data"
SORTIE_DEFAUT = SITE / "fiscalite_locale_series"
LOCAL_TAUX = SITE / "local" / "taux"
AXE = "fiscalite_locale_series"
ID_CATALOGUE = "fiscalite_locale_series_rei"   # collecte/catalogue.json (type urls, lourd : collecte par ce module)

PREMIERE_ANNEE = 2010
MAX_OCTETS = 1_000_000
CIBLE_OCTETS = 500_000      # parties plus légères pour un écran mobile (une commune = un fichier)
DATASET = "impots-locaux-fichier-de-recensement-des-elements-dimposition-a-la-fiscalite-dir"
API = f"https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/{DATASET}"
PIECES = f"https://data.economie.gouv.fr/api/v2/catalog/datasets/{DATASET}/attachments"
PAGE = "https://www.data.gouv.fr/datasets/6657c57abbefc8869c7c6364"
PAGE_ECO = f"https://data.economie.gouv.fr/explore/dataset/{DATASET}/information/"
SOURCE = ("DGFiP, fichiers annuels « Impôts locaux : fichier de recensement des éléments d'imposition à la fiscalité "
          f"directe locale (REI) », data.economie.gouv.fr ({PAGE_ECO}), Licence Ouverte")

# --- Séries publiées ------------------------------------------------------------------------------------------------
# (clé, variables REI candidates dans l'ordre de préférence, libellé). Le taux « voté » (suffixe VOTE) est préféré au
# taux « net » appliqué sur le territoire de la commune quand l'année le publie (même choix que pipeline/local.py).
TAUX = [
    ("tfb_commune", ("E12VOTE", "E12"), "taxe foncière sur les propriétés bâties, part communale"),
    ("tfb_intercommunalite", ("E32VOTE", "E32"), "taxe foncière sur les propriétés bâties, part intercommunale"),
    ("tfb_departement", ("E42",), "taxe foncière sur les propriétés bâties, part départementale (jusqu'en 2020)"),
    ("tfnb_commune", ("B12VOTE", "B12"), "taxe foncière sur les propriétés non bâties, part communale"),
    ("tfnb_intercommunalite", ("B32VOTE", "B32"), "taxe foncière sur les propriétés non bâties, part intercommunale"),
    ("th_commune", ("H12VOTE", "H12"), "taxe d'habitation, part communale (résidences secondaires depuis 2023)"),
    ("th_intercommunalite", ("H32VOTE", "H32"),
     "taxe d'habitation, part intercommunale (résidences secondaires depuis 2023)"),
    # P12 seul : P12VOTE est vide quand la commune ne vote pas de taux (intercommunalité à fiscalité unique)
    ("cfe_commune", ("P12",), "cotisation foncière des entreprises, part communale (taux net appliqué)"),
    ("cfe_intercommunalite_hors_zone", ("P32_1VOTE", "P32_1"),
     "cotisation foncière des entreprises, part intercommunale : fiscalité additionnelle ou hors zone d'activités"),
    ("cfe_intercommunalite_unique_ou_zone", ("P32_2VOTE", "P32_2"),
     "cotisation foncière des entreprises, part intercommunale : fiscalité professionnelle unique ou zone d'activités"),
    ("teom_taux_plein", ("F22",), "taxe d'enlèvement des ordures ménagères, taux plein"),
]
PRODUITS = [
    ("tfb_commune", ("E13",), "taxe foncière sur les propriétés bâties émise au profit de la commune"),
    ("tfb_intercommunalite", ("E33",), "taxe foncière sur les propriétés bâties émise au profit de l'intercommunalité"),
    ("tfb_departement", ("E43",), "taxe foncière sur les propriétés bâties émise au profit du département (jusqu'en 2020)"),
    ("tfnb_commune", ("B13",), "taxe foncière sur les propriétés non bâties émise au profit de la commune"),
    ("tfnb_intercommunalite", ("B33",),
     "taxe foncière sur les propriétés non bâties émise au profit de l'intercommunalité"),
    ("th_commune", ("H13", "H13THS"), "taxe d'habitation émise au profit de la commune (résidences secondaires depuis 2023)"),
    ("th_intercommunalite", ("H33", "H33THS"),
     "taxe d'habitation émise au profit de l'intercommunalité (résidences secondaires depuis 2023)"),
    ("cfe_commune", ("P13",), "cotisation foncière des entreprises émise au profit de la commune"),
    ("cfe_intercommunalite", ("P33", "P33_1+P33_2+P33_3"),
     "cotisation foncière des entreprises émise au profit de l'intercommunalité (toutes zones)"),
    ("teom", ("F13", "F23+F33+F43+F53+F63+F83"), "taxe d'enlèvement des ordures ménagères émise sur le territoire de la commune (toutes zones)"),
]
AUTRES = [("teom_niveau", ("F71", "TEOMBENEF"),
           "niveau qui perçoit la taxe d'enlèvement des ordures ménagères : 0 aucun, 1 commune, 2 syndicat, "
           "3 intercommunalité")]
IDENT = {"DEP": ("DEP", "DEPARTEMENT"), "COM": ("COM", "COMMUNE"), "LIBCOM": ("LIBCOM",),
         "OPTEPCI": ("OPTEPCI",), "SIREPCI": ("SIREPCI",)}
COLONNES_EXTRAIT = (["insee", "nom", "optepci", "sirepci"] + [f"taux_{k}" for k, _, _ in TAUX]
                    + [f"produit_{k}" for k, _, _ in PRODUITS] + [k for k, _, _ in AUTRES])

# Taux déjà publiés par pipeline/local.py (local/taux/<dep>.json) : série d'ici -> colonne de local/taux.
DEJA_PUBLIE = {"tfb_commune": "tfb_commune", "tfb_intercommunalite": "tfb_intercommunalite",
               "tfnb_commune": "tfnb_commune", "tfnb_intercommunalite": "tfnb_intercommunalite",
               "th_commune": "thrs_commune", "th_intercommunalite": "thrs_intercommunalite",
               "teom_taux_plein": "teom_taux_plein"}

RUPTURES = [
    {"annee": 2010, "series": ["cfe_commune", "cfe_intercommunalite_hors_zone", "cfe_intercommunalite_unique_ou_zone",
                               "cfe_intercommunalite"],
     "constat": "Première année de la cotisation foncière des entreprises (remplacement de la taxe professionnelle, "
                "loi de finances pour 2010). Pour 2010, le produit a été perçu par l'État et les collectivités ont "
                "reçu une compensation relais : les montants de 2010 ne sont pas des recettes des collectivités."},
    {"annee": 2011, "series": ["th_commune", "th_intercommunalite", "tfnb_commune", "tfnb_intercommunalite",
                               "tfb_departement"],
     "constat": "Réforme de la fiscalité locale de 2010 appliquée en 2011 : la part départementale de la taxe "
                "d'habitation et les parts départementale et régionale du foncier non bâti sont transférées au bloc "
                "communal (commune ou intercommunalité), la part régionale du foncier bâti au département. Les taux "
                "changent de niveau."},
    {"annee": 2021, "series": ["tfb_commune", "tfb_departement", "th_commune", "th_intercommunalite"],
     "constat": "Suppression de la taxe d'habitation sur les résidences principales : la part départementale du "
                "foncier bâti est transférée aux communes (le taux communal de 2021 intègre le taux départemental "
                "de 2020) ; le département ne vote plus de taux de foncier bâti. En 2021 et 2022, la taxe "
                "d'habitation sur les résidences principales encore due par une partie des foyers est perçue par "
                "l'État ; les taux et montants de taxe d'habitation publiés par le REI pour ces deux années sont "
                "repris tels quels."},
    {"annee": 2023, "series": ["th_commune", "th_intercommunalite"],
     "constat": "Fin de la taxe d'habitation sur les résidences principales : la taxe d'habitation ne porte plus que "
                "sur les résidences secondaires et autres locaux meublés non affectés à l'habitation principale "
                "(variables REI H13THS et H33THS pour les montants)."},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "requetes": ["data.gouv.fr recensement des éléments d'imposition fiscalité directe locale",
                 "data.economie.gouv.fr fiscalite-locale-des-particuliers, fiscalite-locale-des-entreprises",
                 "github REI DGFiP fichier recensement éléments imposition taux communes séries",
                 "collectivites-locales.gouv.fr taux de fiscalité directe locale votés"],
    "trouvailles": [
        {"nom": "DGFiP, REI annuels 1982 à 2025 (pièces jointes, une archive par année)", "url": PAGE,
         "licence": "Licence Ouverte 2.0", "derniere_modification": "2026-05-11", "verdict": "à adapter",
         "usage": "source unique : années 2010 à la dernière publiée ; CSV ou classeur selon l'année, en-têtes en codes "
                  "de variables ou en libellés (positions lues dans le fichier « trace » de l'archive)"},
        {"nom": "DGFiP, jeux fiscalite-locale-des-particuliers et fiscalite-locale-des-entreprises "
                "(data.economie.gouv.fr, extraits du REI)",
         "url": "https://data.economie.gouv.fr/explore/dataset/fiscalite-locale-des-particuliers/",
         "licence": "Licence Ouverte 2.0", "derniere_modification": "2026-05-22", "verdict": "inspiration seulement",
         "usage": "taux seulement, exercices 2021 à 2025 : déjà repris par pipeline/local.py (local/taux) ; ne couvre "
                  "ni les produits ni les années 2010 à 2020"},
        {"nom": "F. Geerolf, pages « Fiscalité directe locale (REI) » et « REI par commune 2009-2025 »",
         "url": "https://fgeerolf.com/data/dgfip/rei.html", "licence": "non précisée",
         "derniere_modification": "2026", "verdict": "inspiration seulement",
         "usage": "lecture des variables REI d'une année à l'autre (code R non repris)"},
        {"nom": "DGCL, taux de fiscalité directe locale votés et guide statistique de la fiscalité directe locale",
         "url": "https://www.collectivites-locales.gouv.fr/etudes-et-statistiques/acces-aux-statistiques-par-"
                "thematique/fiscalite/statistiques-sur-la-fiscalite-locale",
         "licence": "Licence Ouverte 2.0", "derniere_modification": "2025", "verdict": "inspiration seulement",
         "usage": "définitions et ruptures (réformes de 2010-2011 et 2021-2023) ; tableaux agrégés, pas de série "
                  "communale exploitable"},
    ],
    "verdict": "à adapter : aucune série communale publiée de 2010 à aujourd'hui ; les fichiers REI officiels sont "
               "relus année par année avec leur dictionnaire de variables",
}

DEFINITIONS = {
    "taux": "Taux en pour cent voté par la collectivité (variable « taux voté » quand l'année la publie, sinon "
            "« taux net » appliqué sur le territoire de la commune ; voir `variables`).",
    "produits": "Montant émis en euros au titre de l'année sur le territoire de la commune, au profit du niveau "
                "indiqué (« montant réel » ou « produit réel » du REI) : ce que les contribuables de la commune "
                "versent pour ce niveau avant dégrèvements pris en charge par l'État.",
    "teom_niveau": "Code publié par le REI : 0 pas de taxe, 1 commune, 2 syndicat, 3 intercommunalité.",
}
REGLE_NULL = ("null : commune absente du fichier de l'année (commune fusionnée, créée ou recodée), cellule vide dans "
              "la source, impôt sans objet cette année-là (`sans_objet`), ou taux déjà publié dans local/taux "
              "(`deja_publie`). Jamais 0 : un 0 est un 0 publié par la DGFiP.")
LIMITES = [
    "Codes communes de chaque année : une commune fusionnée a une série qui s'arrête, la commune nouvelle une série "
    "qui commence à sa création ; aucune recomposition (un taux ne s'additionne pas).",
    "Les produits sont des montants émis par l'administration fiscale, pas des recettes encaissées par la "
    "collectivité (comptes de gestion : voir local/budgets).",
    "La part syndicale, la taxe spéciale d'équipement, la taxe pour la gestion des milieux aquatiques et la "
    "prévention des inondations et les taxes additionnelles ne sont pas reprises dans les séries (taux des trois "
    "dernières années dans local/taux).",
    "Taux intercommunal de cotisation foncière des entreprises : deux colonnes du REI (hors zone, et unique ou zone "
    "d'activités) ; la colonne utile dépend du régime fiscal de l'intercommunalité.",
]


# --- Lecture des nombres ----------------------------------------------------------------------------------------------

def nombre(v) -> float | None:
    """Cellule REI -> nombre ; vide, absente ou illisible -> None (jamais 0)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = decoder_xml(str(v)).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if s in ("", ".", "-", "nc", "n.c.", "NC"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def taux(v) -> float | None:
    x = nombre(v)
    return None if x is None else round(x, 3)


def euros(v) -> int | None:
    x = nombre(v)
    return None if x is None else int(round(x))


def decoder_xml(s: str | None) -> str:
    """Échappements _xHHHH_ des classeurs exportés (en-têtes et libellés des REI 2016 à 2020)."""
    if s is None:
        return ""
    return re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m.group(1), 16)), s)


def code_insee(dep: str, com: str) -> str | None:
    """DEP (2 caractères, 3 en outre-mer) + COM (3 caractères, 2 en outre-mer) -> code Insee à 5 caractères."""
    dep, com = decoder_xml(str(dep or "")).strip(), decoder_xml(str(com or "")).strip()
    if dep.endswith(".0"):
        dep = dep[:-2]
    if com.endswith(".0"):
        com = com[:-2]
    if not dep or not com or not com.isdigit():
        return None
    if dep.isdigit() and len(dep) == 1:
        dep = "0" + dep
    if dep.startswith("97") and len(dep) == 3:
        code = dep + com.zfill(2)[-2:]
    else:
        code = dep[:2] + com.zfill(3)
    return code.upper() if re.fullmatch(r"(\d{5}|2[AB]\d{3})", code.upper()) else None


def dep_de(insee: str) -> str:
    return insee[:3] if insee.startswith("97") else insee[:2]


# --- Choix des variables d'une année ---------------------------------------------------------------------------------

def choisir(candidats: tuple[str, ...], disponibles: set[str]) -> str | None:
    """Première variable candidate présente ; « A+B+C » = somme des variables présentes (au moins une)."""
    for c in candidats:
        if "+" in c:
            parts = [p for p in c.split("+") if p in disponibles]
            if parts:
                return "+".join(parts)
        elif c in disponibles:
            return c
    return None


# Contrôle de cohérence code -> libellé (en-têtes en libellés lus par position dans le fichier « trace »).
FAMILLE = {"E": ("FB",), "B": ("FNB",), "H": ("TH",), "P": ("CFE",), "F": ("O.M", "OM", "ORDURES", "TEOM")}


def coherent(code: str, titre: str) -> bool:
    """Le libellé de la colonne correspond-il à la variable attendue (impôt, niveau, nature) ?"""
    t = " " + re.sub(r"\s+", " ", titre.upper().replace("É", "E").replace("È", "E")) + " "
    if code in ("F71", "TEOMBENEF"):
        return "O.M" in t or "TEOM" in t or "ORDURES" in t
    fam = FAMILLE.get(code[0])
    if not fam or not any(re.search(rf"(?<![A-Z]){re.escape(f)}(?![A-Z])", t) for f in fam):
        return False
    if code[0] == "F":
        return ("TAUX" in t) if code == "F22" else ("MONTANT" in t)
    niveau, nature = code[1], code[2]
    if nature == "2" and "TAUX" not in t:
        return False
    if nature == "3" and not ("MONTANT" in t or "PRODUIT" in t):
        return False
    attendu = {"1": ("COMMUNE",), "3": ("GFP", "INTERCO", "GROUPEMENT"), "4": ("DEPARTEMENT",)}[niveau]
    return any(a in t for a in attendu)


# --- Lecture d'une archive REI ---------------------------------------------------------------------------------------

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _col(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + ord(ch.upper()) - 64
        else:
            break
    return n - 1


def lignes_xlsx(f) -> "iter[list[str|None]]":
    """Lignes d'un classeur xlsx lues en flux (feuille la plus grosse), cellules creuses respectées."""
    with zipfile.ZipFile(f) as zz:
        ss = []
        if "xl/sharedStrings.xml" in zz.namelist():
            with zz.open("xl/sharedStrings.xml") as s:
                for _, el in iterparse(s):
                    if el.tag == NS + "si":
                        ss.append("".join(t.text or "" for t in el.iter(NS + "t")))
                        el.clear()
        feuilles = [i for i in zz.infolist() if i.filename.startswith("xl/worksheets/sheet")]
        feuille = max(feuilles, key=lambda i: i.file_size).filename
        with zz.open(feuille) as s:
            for _, el in iterparse(s):
                if el.tag != NS + "row":
                    continue
                vals: dict[int, str | None] = {}
                for c in el:
                    t = c.get("t")
                    if t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(NS + "t"))
                    else:
                        v = c.find(NS + "v")
                        val = v.text if v is not None else None
                        if t == "s" and val is not None:
                            val = ss[int(val)]
                    vals[_col(c.get("r"))] = val
                el.clear()
                if vals:
                    yield [vals.get(i) for i in range(max(vals) + 1)]


def lignes_csv(f) -> "iter[list[str]]":
    tete = f.read(4096)
    f.seek(0)
    enc = "utf-8-sig"
    try:
        tete.decode("utf-8")
    except UnicodeDecodeError:
        enc = "latin-1"
    texte = io.TextIOWrapper(f, encoding=enc, errors="replace", newline="")
    sep = ";" if tete.count(b";") >= tete.count(b",") else ","
    yield from csv.reader(texte, delimiter=sep)


def trace_positions(zf: zipfile.ZipFile, membre: str | None) -> dict[int, tuple[str, str]]:
    """Fichier « trace » de l'archive : position (1..n) -> (code de variable, titre)."""
    if not membre:
        return {}
    import openpyxl  # dépendance déjà utilisée par le dépôt (requirements)
    wb = openpyxl.load_workbook(io.BytesIO(zf.read(membre)), read_only=True)
    sortie = {}
    for r in wb.worksheets[0].iter_rows(values_only=True):
        if r and isinstance(r[0], (int, float)) and r[1]:
            sortie[int(r[0])] = (str(r[1]).strip().upper(), str(r[3] if len(r) > 3 and r[3] else "").strip())
    wb.close()
    return sortie


def membres(zf: zipfile.ZipFile) -> tuple[str, str | None]:
    """(fichier de données, fichier trace) d'une archive REI."""
    noms = [m for m in zf.namelist() if not m.endswith("/")]
    base = lambda m: m.rsplit("/", 1)[-1].lower()  # noqa: E731
    donnees = [m for m in noms if base(m).endswith((".csv", ".xlsx", ".txt")) and "trace" not in base(m)
               and "notice" not in base(m)]
    traces = [m for m in noms if "trace" in base(m) and base(m).endswith(".xlsx")]
    if len(donnees) != 1:
        raise SystemExit(f"archive REI : fichier de données introuvable ou ambigu ({noms})")
    return donnees[0], (traces[0] if traces else None)


def entete_codes(entete: list[str], traces: dict[int, tuple[str, str]]) -> tuple[list[str], dict[str, dict]]:
    """Codes de variables des colonnes. En-tête en codes (REI 2010-2015, 2021+) ou en libellés (positions de la trace)."""
    brut = [decoder_xml(h).strip() for h in entete]
    codes_entete = {h.upper() for h in brut}
    if {"E12", "E13", "B12"} <= codes_entete or {"E12VOTE", "E13", "B12"} <= codes_entete:
        codes = [h.upper() for h in brut]
        return codes, {c: {"position": i + 1, "titre": None} for i, c in enumerate(codes)}
    if not traces:
        raise SystemExit("REI : en-tête en libellés sans fichier trace pour le lire")
    codes, info = [], {}
    for i, titre in enumerate(brut):
        code, titre_trace = traces.get(i + 1, ("", ""))
        codes.append(code)
        if code:
            info[code] = {"position": i + 1, "titre": titre}
    return codes, info


def extraire(zip_path: Path, annee: int) -> tuple[list[dict], dict]:
    """Lit une archive REI et renvoie (lignes de l'extrait, variables lues)."""
    with zipfile.ZipFile(zip_path) as zf:
        donnees, trace = membres(zf)
        traces = trace_positions(zf, trace)
        with zf.open(donnees) as brut:
            f = io.BytesIO(brut.read()) if donnees.lower().endswith(".xlsx") else brut
            lecteur = lignes_xlsx(f) if donnees.lower().endswith(".xlsx") else lignes_csv(f)
            entete = next(lecteur)
            codes, info = entete_codes([h or "" for h in entete], traces)
            dispo = {c for c in codes if c}
            pos = {}
            for c in codes:
                if c and c not in pos:
                    pos[c] = codes.index(c)
            ident = {k: choisir(v, dispo) for k, v in IDENT.items()}
            if not ident["DEP"] or not ident["COM"]:
                raise SystemExit(f"REI {annee} : colonnes DEP/COM introuvables")
            choix = {}
            for prefixe, liste in (("taux_", TAUX), ("produit_", PRODUITS), ("", AUTRES)):
                for k, cand, _ in liste:
                    choix[prefixe + k] = choisir(cand, dispo)
            variables = {}
            for k, var in choix.items():
                if not var:
                    variables[k] = None
                    continue
                for v in var.split("+"):
                    titre = info.get(v, {}).get("titre")
                    if titre and not coherent(v, titre):
                        raise SystemExit(f"REI {annee} : la colonne {v} (position {pos[v] + 1}) a pour libellé "
                                         f"« {titre} », incohérent : lecture interrompue")
                variables[k] = {"variable": var, "positions": [pos[v] + 1 for v in var.split("+")],
                                "libelles": [info.get(v, {}).get("titre") for v in var.split("+")]}
            lignes, vus = [], set()

            def cell(row, v):
                i = pos[v]
                return row[i] if i < len(row) else None

            for row in lecteur:
                insee = code_insee(cell(row, ident["DEP"]), cell(row, ident["COM"]))
                if not insee or insee in vus:
                    continue
                vus.add(insee)
                ligne = {"insee": insee,
                         "nom": decoder_xml(cell(row, ident["LIBCOM"]) or "").strip() if ident["LIBCOM"] else "",
                         "optepci": decoder_xml(cell(row, ident["OPTEPCI"]) or "").strip() if ident["OPTEPCI"] else "",
                         "sirepci": decoder_xml(cell(row, ident["SIREPCI"]) or "").strip() if ident["SIREPCI"] else ""}
                for k, var in choix.items():
                    if not var:
                        ligne[k] = None
                    elif k.startswith("taux_"):
                        ligne[k] = taux(cell(row, var))
                    elif "+" in var:
                        vals = [euros(cell(row, v)) for v in var.split("+")]
                        ligne[k] = None if all(x is None for x in vals) else sum(x or 0 for x in vals)
                    elif k.startswith("produit_"):
                        ligne[k] = euros(cell(row, var))
                    else:
                        x = nombre(cell(row, var))
                        ligne[k] = None if x is None else int(x)
                lignes.append(ligne)
    lignes.sort(key=lambda r: r["insee"])
    return lignes, {"fichier": donnees, "trace": trace, "colonnes_identite": ident, "variables": variables}


# --- Collecte (réseau) ------------------------------------------------------------------------------------------------

def pieces_jointes() -> dict[int, str]:
    """Année -> URL de l'archive REI (liste des pièces jointes du jeu)."""
    r = fetch.get(f"{API}/attachments", controle="json")
    sortie = {}
    for a in r.json().get("attachments", []):
        m = a.get("metas", {})
        titre = m.get("title") or m.get("id") or ""
        g = re.search(r"REI[-_](\d{4})", titre, re.I)
        if g and titre.lower().endswith(".zip"):
            sortie[int(g.group(1))] = a.get("href") or m.get("url") or f"{PIECES}/{m.get('id')}"
    return sortie


def telecharger(url: str, dest: Path, essais: int = 5) -> dict:
    """Téléchargement en flux vers un temporaire, contrôle d'intégrité (collecte/integrite.py), renommage atomique."""
    tmp = dest.with_name(dest.name + ".part")
    erreur = None
    for i in range(1, essais + 1):
        try:
            with requests.get(url, stream=True, timeout=180, headers=fetch.HEADERS) as r:
                if r.status_code in (401, 403, 429):
                    raise SystemExit(f"{url} -> HTTP {r.status_code} : source notée inaccessible, aucun contournement")
                r.raise_for_status()
                h = hashlib.sha256()
                with open(tmp, "wb") as f:
                    for bloc in r.iter_content(1 << 20):
                        f.write(bloc)
                        h.update(bloc)
                fetch.remplacer_si_valide(tmp, dest, nom=dest.name, octets_attendus=fetch.octets_annonces(r))
                return {"sha256": h.hexdigest(), "octets": dest.stat().st_size}
        except SystemExit:
            raise
        except Exception as exc:  # coupure réseau, transfert tronqué (IntegriteInvalide)
            erreur = exc
            tmp.unlink(missing_ok=True)
            if i < essais:
                time.sleep(min(15 * i, 60))
    raise SystemExit(f"{url} injoignable ou incomplet après {essais} tentatives : {erreur}")


def ecrire_extrait(annee: int, lignes: list[dict], meta: dict) -> None:
    EXTRAITS.mkdir(parents=True, exist_ok=True)
    tmp = EXTRAITS / f"rei_{annee}.csv.gz.part"
    with gzip.open(tmp, "wt", encoding="utf-8", newline="", compresslevel=9) as g:
        g_mtime = csv.writer(g, delimiter=";", lineterminator="\n")
        g_mtime.writerow(COLONNES_EXTRAIT)
        for r in lignes:
            g_mtime.writerow(["" if r.get(c) is None else r[c] for c in COLONNES_EXTRAIT])
    os.replace(tmp, EXTRAITS / f"rei_{annee}.csv.gz")
    (EXTRAITS / f"rei_{annee}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                                encoding="utf-8")


def collecter(annees: list[int] | None, force: bool = False) -> None:
    urls = pieces_jointes()
    cibles = sorted(a for a in urls if a >= PREMIERE_ANNEE and (not annees or a in annees))
    if not cibles:
        raise SystemExit("aucune archive REI trouvée parmi les pièces jointes")
    DOSSIER_LAC.mkdir(parents=True, exist_ok=True)
    for a in cibles:
        if (EXTRAITS / f"rei_{a}.csv.gz").exists() and not force:
            print(f"  REI {a} : extrait présent")
            continue
        existant = sorted(REI_PRELEVEMENTS.glob(f"REI-{a}-*.zip")) if REI_PRELEVEMENTS.exists() else []
        if existant:
            zp, partage = existant[0], True
            empreinte = {"sha256": hashlib.sha256(zp.read_bytes()).hexdigest(), "octets": zp.stat().st_size}
        else:
            zp, partage = DOSSIER_LAC / f"rei_{a}.zip", False
            if not zp.exists():
                print(f"  REI {a} : téléchargement {urls[a]}")
                empreinte = telecharger(urls[a], zp)
            else:
                empreinte = {"sha256": hashlib.sha256(zp.read_bytes()).hexdigest(), "octets": zp.stat().st_size}
        print(f"  REI {a} : extraction ({empreinte['octets'] // 10**6} Mo)")
        lignes, meta = extraire(zp, a)
        meta.update({"annee": a, "url": urls[a], "archive": zp.name, **empreinte, "communes": len(lignes),
                     "collecte_le": datetime.now(timezone.utc).date().isoformat(),
                     "archive_partagee": str(zp.relative_to(ROOT)) if partage else None})
        ecrire_extrait(a, lignes, meta)
        if not partage:
            zp.unlink()   # fichiers lourds : le brut est supprimé dès que l'extrait est écrit
        print(f"  REI {a} : {len(lignes)} communes")


# --- Production (sans réseau) -----------------------------------------------------------------------------------------

def lire_extraits() -> tuple[list[int], dict[int, list[dict]], dict[int, dict]]:
    annees, lignes, metas = [], {}, {}
    for p in sorted(EXTRAITS.glob("rei_*.csv.gz")):
        a = int(re.search(r"rei_(\d{4})", p.name).group(1))
        if a < PREMIERE_ANNEE:
            continue
        with gzip.open(p, "rt", encoding="utf-8", newline="") as g:
            lignes[a] = list(csv.DictReader(g, delimiter=";"))
        metas[a] = json.loads((EXTRAITS / f"rei_{a}.json").read_text(encoding="utf-8"))
        annees.append(a)
    if not annees:
        raise SystemExit(f"aucun extrait dans {EXTRAITS} : lancer « collecter »")
    attendues = list(range(PREMIERE_ANNEE, max(annees) + 1))
    manquantes = sorted(set(attendues) - set(annees))
    if manquantes:
        raise SystemExit(f"extraits manquants : {manquantes} (relancer « collecter »)")
    return annees, lignes, metas


def date_collecte(metas: dict[int, dict]) -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), timezone.utc).date().isoformat()
    return max(m["collecte_le"] for m in metas.values())


def annees_local_taux() -> list[int]:
    """Années déjà publiées par pipeline/local.py dans local/taux (lues dans un fichier départemental)."""
    for p in sorted(LOCAL_TAUX.glob("*.json")):
        try:
            return sorted(int(e) for e in json.loads(p.read_text(encoding="utf-8")).get("exercices", []))
        except (OSError, ValueError):
            continue
    return []


def valeur(s: str, entier: bool):
    if s == "" or s is None:
        return None
    return int(s) if entier else (float(s) if "." in s else int(s))


def construire(annees, lignes, metas, deja: list[int]):
    """commune -> {nom, taux{serie: [..]}, produits{serie: [..]}, teom_niveau[..]} ; et totaux nationaux par année."""
    idx = {a: i for i, a in enumerate(annees)}
    n = len(annees)
    communes: dict[str, dict] = {}
    totaux = {k: [0] * n for k, _, _ in PRODUITS}
    for a in annees:
        i = idx[a]
        for r in lignes[a]:
            c = communes.setdefault(r["insee"], {"nom": "", "taux": {k: [None] * n for k, _, _ in TAUX},
                                                 "produits": {k: [None] * n for k, _, _ in PRODUITS},
                                                 "teom_niveau": [None] * n})
            if r["nom"]:
                c["nom"] = r["nom"]
            for k, _, _ in TAUX:
                if a in deja and k in DEJA_PUBLIE:
                    continue
                c["taux"][k][i] = valeur(r[f"taux_{k}"], False)
            for k, _, _ in PRODUITS:
                v = valeur(r[f"produit_{k}"], True)
                c["produits"][k][i] = v
                totaux[k][i] += v or 0
            c["teom_niveau"][i] = valeur(r["teom_niveau"], True)
    for k, _, _ in PRODUITS:   # total null si la variable n'existe pas cette année
        for a in annees:
            if not metas[a]["variables"].get(f"produit_{k}"):
                totaux[k][idx[a]] = None
    for c in communes.values():  # séries entièrement nulles retirées (commune sans cet impôt)
        c["taux"] = {k: v for k, v in c["taux"].items() if any(x is not None for x in v)}
        c["produits"] = {k: v for k, v in c["produits"].items() if any(x is not None for x in v)}
        if all(x is None for x in c["teom_niveau"]):
            del c["teom_niveau"]
    return dict(sorted(communes.items())), totaux


def controle_local(annees, lignes, deja: list[int]) -> dict:
    """Compare les taux du REI et ceux de local/taux (jeu fiscalite-locale-des-particuliers) sur les années communes."""
    if not deja:
        return {"annees": [], "comparaisons": 0, "ecarts": 0, "exemples": []}
    locaux: dict[str, dict] = {}
    colonnes = None
    for p in sorted(LOCAL_TAUX.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        colonnes = d.get("colonnes", colonnes)
        locaux.update(d.get("communes", {}))
    comp = ecarts = 0
    exemples = []
    par_serie = defaultdict(lambda: [0, 0])
    for a in deja:
        if a not in lignes:
            continue
        for r in lignes[a]:
            loc = locaux.get(r["insee"], {}).get(str(a))
            if not loc:
                continue
            for k, col in DEJA_PUBLIE.items():
                v_rei = valeur(r[f"taux_{k}"], False)
                v_loc = loc[colonnes.index(col)] if col in colonnes else None
                if v_rei is None or v_loc is None:
                    continue
                comp += 1
                par_serie[k][0] += 1
                if abs(float(v_rei) - float(v_loc)) > 0.0105:
                    ecarts += 1
                    par_serie[k][1] += 1
                    if len(exemples) < 10:
                        exemples.append({"annee": a, "insee": r["insee"], "serie": k, "rei": v_rei,
                                         "local_taux": v_loc})
    return {"annees": [str(a) for a in deja if a in lignes], "comparaisons": comp, "ecarts": ecarts,
            "par_serie": {k: {"comparaisons": v[0], "ecarts": v[1]} for k, v in sorted(par_serie.items())},
            "tolerance_points": 0.01, "exemples": exemples,
            "lecture": "Même taux attendu dans les deux publications de la DGFiP (fichier REI et jeu "
                       "fiscalite-locale-des-particuliers) ; un écart est publié tel quel, sans choisir de valeur."}


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"


def decouper(dep: str, communes: dict, entete: dict) -> list[tuple[str, dict]]:
    """Un fichier par département, découpé en parties de codes contigus au-delà de CIBLE_OCTETS."""
    complet = {**entete, "departement": dep, "partie": None, "communes": communes}
    if len(dumps(complet).encode()) <= CIBLE_OCTETS:
        return [(f"{dep}.json", complet)]
    codes = sorted(communes)
    tailles = {c: len(dumps({c: communes[c]}).encode()) for c in codes}
    base = len(dumps({**entete, "departement": dep, "partie": 1, "communes": {}}).encode())
    parts, cur, taille = [], [], base
    for c in codes:
        if cur and taille + tailles[c] > CIBLE_OCTETS:
            parts.append(cur)
            cur, taille = [], base
        cur.append(c)
        taille += tailles[c]
    if cur:
        parts.append(cur)
    return [(f"{dep}_{k}.json", {**entete, "departement": dep, "partie": k,
                                 "communes": {c: communes[c] for c in p}}) for k, p in enumerate(parts, 1)]


def produire(sortie: Path) -> dict:
    annees, lignes, metas = lire_extraits()
    deja_toutes = annees_local_taux()
    deja = [a for a in annees if a in deja_toutes]
    communes, totaux = construire(annees, lignes, metas, deja)
    date = date_collecte(metas)
    millesime = f"REI {annees[0]} à {annees[-1]}"
    sans_objet = {"tfb_departement": [a for a in annees if a >= 2021]}
    entete = {"millesime": millesime, "source": SOURCE, "date_sources": date,
              "annees": [str(a) for a in annees], "unite_taux": "%", "unite_produits": "euros",
              "series_taux": [k for k, _, _ in TAUX], "series_produits": [k for k, _, _ in PRODUITS],
              "deja_publie": {"annees": [str(a) for a in deja], "fichier": "local/taux/<dep>.json",
                              "colonnes": {k: v for k, v in DEJA_PUBLIE.items()}},
              "regle_null": REGLE_NULL}
    par_dep: dict[str, dict] = defaultdict(dict)
    for insee, c in communes.items():
        par_dep[dep_de(insee)][insee] = c
    if sortie.exists():
        for p in sorted((sortie / "communes").glob("*.json")):
            p.unlink()
    (sortie / "communes").mkdir(parents=True, exist_ok=True)
    fichiers, tailles = [], {}
    for dep in sorted(par_dep):
        parts = decouper(dep, par_dep[dep], entete)
        liste = []
        for nom, contenu in parts:
            texte = dumps(contenu)
            if len(texte.encode()) > MAX_OCTETS:
                raise SystemExit(f"communes/{nom} dépasse 1 Mo ({len(texte.encode())} octets)")
            (sortie / "communes" / nom).write_text(texte, encoding="utf-8")
            tailles[nom] = len(texte.encode())
            codes = sorted(contenu["communes"])
            liste.append({"fichier": f"communes/{nom}", "premier": codes[0], "dernier": codes[-1],
                          "communes": len(codes)})
        fichiers.append({"departement": dep, "parties": liste})
    idx = {a: i for i, a in enumerate(annees)}
    variables = {str(a): {k: (v or {}).get("variable") for k, v in sorted(metas[a]["variables"].items())}
                 for a in annees}
    index = {
        "millesime": millesime, "source": SOURCE, "date_sources": date,
        "presentation": "Taux votés et montants émis des impôts locaux de chaque commune, année par année depuis "
                        f"{annees[0]} : foncier bâti et non bâti, taxe d'habitation, cotisation foncière des "
                        "entreprises, taxe d'enlèvement des ordures ménagères, pour la commune, son "
                        "intercommunalité et, jusqu'en 2020, le département (foncier bâti).",
        "annees": [str(a) for a in annees],
        "series": {"taux": [{"cle": k, "libelle": l, "variables_candidates": list(c)} for k, c, l in TAUX],
                   "produits": [{"cle": k, "libelle": l, "variables_candidates": list(c)} for k, c, l in PRODUITS],
                   "autres": [{"cle": k, "libelle": l, "variables_candidates": list(c)} for k, c, l in AUTRES]},
        "definitions": DEFINITIONS, "regle_null": REGLE_NULL,
        "sans_objet": {k: [str(a) for a in v] for k, v in sans_objet.items()},
        "deja_publie": {**entete["deja_publie"],
                        "note": "Taux déjà publiés par pipeline/local.py pour ces années : null ici, à lire dans "
                                "local/taux/<dep>.json (exercice -> ligne alignée sur `colonnes` de ce fichier). "
                                "Produits et cotisation foncière des entreprises : publiés ici pour toutes les années."},
        "variables": variables,
        "lecture_annees": {str(a): {"fichier": metas[a]["fichier"], "trace": metas[a]["trace"],
                                    "communes": metas[a]["communes"], "url": metas[a]["url"],
                                    "sha256_archive": metas[a]["sha256"], "octets_archive": metas[a]["octets"]}
                           for a in annees},
        "ruptures": [r for r in RUPTURES if annees[0] <= r["annee"] <= annees[-1]],
        "totaux_nationaux": {
            "lecture": "Somme des montants des communes du fichier de l'année (France entière, euros). Calcul du "
                       "site sur les données REI, à afficher comme tel ; null si la variable n'existe pas cette année.",
            "produits": totaux},
        "departements": fichiers,
        "controles": {"local_taux": controle_local(annees, lignes, deja),
                      "communes_par_annee": {str(a): len(lignes[a]) for a in annees},
                      "taille_max_octets": max(tailles.values())},
        "methode": "Chaque archive annuelle du REI est téléchargée (contrôle d'intégrité), réduite aux colonnes "
                   "utiles (extrait), puis supprimée. Les colonnes sont identifiées par leur code de variable ; "
                   "quand l'en-tête porte des libellés, le code est lu à la même position dans le fichier « trace » "
                   "de l'archive, et le libellé est vérifié (impôt, niveau, taux ou montant).",
        "limites": LIMITES,
        "sources": [{"titre": "DGFiP, REI (recensement des éléments d'imposition à la fiscalité directe locale), "
                              f"archives {annees[0]} à {annees[-1]}", "id_catalogue": ID_CATALOGUE,
                     "page": PAGE, "page_producteur": PAGE_ECO,
                     "producteur": "Direction générale des Finances publiques (DGFiP)",
                     "licence": "Licence Ouverte 2.0"},
                    {"titre": "site/data/local/taux (pipeline/local.py), lecture seule : renvois et contrôle",
                     "page": "site/data/local/taux/", "producteur": "pipeline/local.py",
                     "licence": "Licence Ouverte 2.0"}],
        "sources_inaccessibles": [],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "ordre": "Communes dans l'ordre des codes Insee, années dans l'ordre chronologique ; aucun classement.",
    }
    (sortie / "index.json").write_text(dumps(index), encoding="utf-8")
    return {"annees": f"{annees[0]}-{annees[-1]}", "communes": len(communes), "fichiers": len(tailles),
            "taille_max": max(tailles.values())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("commande", nargs="?", choices=["collecter", "produire"])
    ap.add_argument("--annees", help="ex. 2010-2025 ou 2012,2015")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT)
    a = ap.parse_args(argv)
    annees = None
    if a.annees:
        annees = []
        for p in a.annees.split(","):
            d, _, f = p.partition("-")
            annees += list(range(int(d), int(f or d) + 1))
    if a.commande in (None, "collecter"):
        collecter(annees, a.force)
    if a.commande in (None, "produire"):
        print(json.dumps(produire(a.sortie), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
