"""Revenus et impôt sur le revenu par commune : IRCOM (DGFiP) et Filosofi (Insee), ramenés au COG en vigueur.

Pour chaque commune du code officiel géographique en vigueur (mêmes codes que site/data/local/geo) : nombre de foyers
fiscaux, foyers imposés, revenu fiscal de référence, impôt net, pour chaque année d'imposition publiée par la DGFiP
(revenus 2002 à 2024), et par tranche de revenu fiscal de référence quand la DGFiP publie ce détail ; niveau de vie
médian (médiane du revenu disponible par unité de consommation) publié par l'Insee (Filosofi 2021, Filosofi 2 2023).

Entrées (data/lake, collectées par collecte/collecte.py ; identifiants déclarés dans collecte/catalogue.json) :
  revenus_communes/revenus_communes_ircom/*            IRCOM 2003 à 2025, une ressource data.gouv.fr par année
  revenus_communes/revenus_communes_filosofi_2021.zip  Filosofi 2021, base communale, géographie au 01/01/2025
  comptes_nationaux/insee_ds_filosofi_cc.zip           Filosofi 2 2023 (Melodi DS_FILOSOFI_CC), géographie 2026
  revenus_communes/revenus_communes_passage_cog.zip    table de passage annuelle des communes 2026 (Insee)
  lecture seule : site/data/local/geo/<dep>.json (communes du COG en vigueur, noms officiels)
Sorties (site/data/revenus_communes/, avec `millesime` et `source`) :
  index.json                   années, colonnes, définitions, ruptures, couverture, contrôles, sources, recherche
  communes/<dep>.json          par commune : série IRCOM (cinq grandeurs, toutes les années), médianes Filosofi
                               (< 1 Mo : lu par le navigateur)
  tranches/<dep>.json          par commune et par tranche de revenu fiscal de référence, toutes les années où c'est
                               publié, une clé par année dans `par_annee` (< 5 Mo : téléchargement seulement, aucun
                               écran ne le lit ; un fichier par département et non par année et par département, pour
                               rester sous la limite de fichiers de l'hébergeur, docs/PERF.md)

Commandes :
  python pipeline/revenus_communes.py collecter     # réseau : collecte/collecte.py sur les quatre sources
  python pipeline/revenus_communes.py produire      # sans réseau ; --sortie DOSSIER pour une copie de contrôle
  python pipeline/revenus_communes.py               # les deux

Règles :
  - une valeur non communiquée par la source (« n.c. », « . », « #VALUE! », cellule vide) reste null, jamais 0 ; la
    raison est écrite (`etat` d'une ligne absente, `regle_null` des fichiers, comptes des marques dans l'index) ;
  - géographie : chaque année est lue dans sa propre géographie (déterminée par rapprochement avec la table de
    passage de l'Insee), puis ramenée aux communes en vigueur. Une commune issue de fusions reçoit la somme des
    anciennes communes (liste dans `recompose`) ; une valeur masquée chez l'une d'elles rend la somme null. Une ancienne
    commune dont le territoire est aujourd'hui partagé entre plusieurs communes n'est attribuée à aucune
    (`etat` = « perimetre ») ; les arrondissements de Paris, Lyon et Marseille sont additionnés dans leur commune ;
  - IRCOM et Filosofi ne s'additionnent pas et ne se comparent pas directement (foyers fiscaux contre ménages, revenu
    fiscal de référence contre revenu disponible par unité de consommation) ; Filosofi 2023 (Filosofi 2) n'est pas
    directement comparable à Filosofi 2021 (avertissement de l'Insee) ;
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
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
GEO = SITE / "local" / "geo"
SORTIE_DEFAUT = SITE / "revenus_communes"
MAX_OCTETS = 1_000_000          # fichiers lus par le navigateur
MAX_OCTETS_TELECHARGEMENT = 5_000_000   # tranches/<dep>.json : téléchargement seulement (règle commune : < 5 Mo)
COG = 2026                      # géographie de la table de passage et de local/geo

ID_IRCOM = "revenus_communes_ircom"
ID_FILO21 = "revenus_communes_filosofi_2021"
ID_FILO23 = "insee_ds_filosofi_cc"
ID_PASSAGE = "revenus_communes_passage_cog"
DOSSIER_IRCOM = LAKE / "revenus_communes" / ID_IRCOM
ZIP_FILO21 = LAKE / "revenus_communes" / f"{ID_FILO21}.zip"
ZIP_FILO23 = LAKE / "comptes_nationaux" / f"{ID_FILO23}.zip"
ZIP_PASSAGE = LAKE / "revenus_communes" / f"{ID_PASSAGE}.zip"

# Colonnes publiées (séries et tranches) et colonnes lues dans les fichiers IRCOM.
COLONNES = ["foyers", "foyers_imposes", "rfr_eur", "rfr_imposes_eur", "impot_net_eur"]
CIMR = ["impot_net_avant_cimr_eur", "cimr_eur"]   # revenus 2018 seulement (année de mise en place du prélèvement à la source)
LUES = COLONNES + ["salaires_foyers", "salaires_eur", "pensions_foyers", "pensions_eur"] + CIMR
OPTIONNELLES = set(CIMR)
MONTANTS = {"rfr_eur", "rfr_imposes_eur", "impot_net_eur", "salaires_eur", "pensions_eur"} | set(CIMR)
VILLES = {"75": ("75056", "PARIS", "751"), "13": ("13055", "MARSEILLE", "132"), "69": ("69123", "LYON", "6938")}
ARRONDISSEMENTS = {"75056": 20, "13055": 16, "69123": 9}

SOURCES = {
    "ircom": {
        "id_catalogue": ID_IRCOM,
        "titre": "DGFiP, « L'impôt sur le revenu par collectivité territoriale (IRCOM) » : foyers fiscaux, revenu fiscal "
                 "de référence, impôt net, foyers imposés, par commune et par tranche de revenu fiscal de référence",
        "page": "https://www.data.gouv.fr/datasets/536998cba3a729239d20505e",
        "producteur": "Direction générale des Finances publiques (DGFiP)", "licence": "Licence Ouverte 2.0",
        "millesime": "impôts 2003 à 2025 (revenus 2002 à 2024)",
        "verdict": "réutilisable tel quel (classeurs départementaux de chaque archive annuelle ; fichier communal "
                   "complet pour les revenus 2002, seule forme publiée)",
    },
    "filosofi_2021": {
        "id_catalogue": ID_FILO21,
        "titre": "Insee, « Revenus, pauvreté et niveau de vie en 2021 » (Filosofi), base communale, géographie au "
                 "1er janvier 2025 : niveau de vie médian et nombre de ménages fiscaux",
        "page": "https://www.insee.fr/fr/statistiques/7756729",
        "producteur": "Insee", "licence": "Licence Ouverte 2.0", "millesime": "revenus 2021",
        "verdict": "réutilisable tel quel (CSV : mesure, statut de confidentialité, statut de l'observation)",
    },
    "filosofi_2023": {
        "id_catalogue": ID_FILO23,
        "titre": "Insee, « Niveau de vie, taux de pauvreté, décomposition du revenu disponible en 2023 » (Filosofi 2, "
                 "jeu Melodi DS_FILOSOFI_CC), géographie au 1er janvier 2026 : niveau de vie médian par commune",
        "page": "https://catalogue-donnees.insee.fr/fr/catalogue/recherche/DS_FILOSOFI_CC",
        "producteur": "Insee", "licence": "Licence Ouverte 2.0", "millesime": "revenus 2023",
        "verdict": "réutilisable tel quel (entrée de catalogue déjà présente dans le dépôt, domaine comptes_nationaux)",
    },
    "passage_cog": {
        "id_catalogue": ID_PASSAGE,
        "titre": "Insee, « Tables de passage des communes », table annuelle 2026 : code de chaque commune et de chaque "
                 "arrondissement municipal dans chaque géographie du 1er janvier 2003 au 1er janvier 2026",
        "page": "https://www.insee.fr/fr/information/7671867",
        "producteur": "Insee", "licence": "Licence Ouverte 2.0", "millesime": "géographies 2003 à 2026",
        "verdict": "réutilisable tel quel (fusions, scissions et changements de code d'une même source)",
    },
    "local": {
        "titre": "site/data/local/geo (pipeline/local.py), lecture seule : communes en vigueur et noms officiels "
                 "(geo.api.gouv.fr)",
        "page": "site/data/local/index.json", "producteur": "pipeline/local.py", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (mêmes codes Insee)",
    },
}

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "requetes": ["data.gouv.fr IRCOM impôt sur le revenu par collectivité territoriale",
                 "Insee Filosofi base communale médiane niveau de vie", "Insee table de passage des communes",
                 "github ircom", "github impot revenu commune", "github filosofi commune",
                 "réutilisations data.gouv.fr du jeu IRCOM"],
    "trouvailles": [
        {"nom": "DGFiP, IRCOM sur data.gouv.fr (une ressource par année, 1993 à 2025)",
         "url": "https://www.data.gouv.fr/datasets/536998cba3a729239d20505e", "licence": "Licence Ouverte 2.0",
         "derniere_modification": "2026-05-26", "verdict": "réutilisable tel quel",
         "usage": "source unique des montants ; impôts 2003 à 2025 repris"},
        {"nom": "Insee, Filosofi 2021 base communale et Filosofi 2 2023 (Melodi DS_FILOSOFI_CC)",
         "url": "https://www.insee.fr/fr/statistiques/7756729", "licence": "Licence Ouverte 2.0",
         "derniere_modification": "2026-08-06", "verdict": "réutilisable tel quel",
         "usage": "médiane du niveau de vie ; l'entrée insee_ds_filosofi_cc du catalogue est reprise sans copie"},
        {"nom": "Insee, tables de passage des communes (géographie 2026)",
         "url": "https://www.insee.fr/fr/information/7671867", "licence": "Licence Ouverte 2.0",
         "derniere_modification": "2026-03-19", "verdict": "réutilisable tel quel",
         "usage": "géographie de chaque année et recomposition sur les communes en vigueur"},
        {"nom": "pipeline/local.py et site/data/local/geo (ce dépôt)", "url": "pipeline/local.py",
         "licence": "MIT", "derniere_modification": "dépôt courant", "verdict": "réutilisable tel quel",
         "usage": "liste des communes en vigueur, noms, fichiers par département"},
        {"nom": "collecte/collecte.py (ce dépôt)", "url": "collecte/collecte.py", "licence": "MIT",
         "derniere_modification": "dépôt courant", "verdict": "réutilisable tel quel",
         "usage": "collecte des quatre sources, manifeste et reprise"},
        {"nom": "zanzibarrr/ircom-impot-revenu-streamlit (application Streamlit sur l'IRCOM)",
         "url": "https://github.com/zanzibarrr/ircom-impot-revenu-streamlit", "licence": "MIT",
         "derniere_modification": "2026-10-24", "verdict": "inspiration seulement",
         "usage": "séries départementales 1984-2024 ; ni communes, ni passage de géographie"},
        {"nom": "gunout/ircom-2024", "url": "https://github.com/gunout/ircom-2024", "licence": "MIT",
         "derniere_modification": "2026-09-14", "verdict": "inspiration seulement",
         "usage": "page HTML sur un millésime ; aucun traitement réutilisable"},
        {"nom": "InseeFrLab/pynsee (accès aux API de l'Insee)", "url": "https://github.com/InseeFrLab/pynsee",
         "licence": "MIT", "derniere_modification": "2026-10-30", "verdict": "inspiration seulement",
         "usage": "téléchargement des fichiers publiés directement, sans dépendance supplémentaire"},
        {"nom": "Geoptis, « Revenu des français à la commune » (data.gouv.fr)",
         "url": "https://www.data.gouv.fr/datasets/revenu-des-francais-a-la-commune", "licence": "Licence Ouverte 2.0",
         "derniere_modification": "2025-12-10", "verdict": "inspiration seulement",
         "usage": "copie d'un millésime Filosofi 2021 ; la source de l'Insee est reprise directement"},
        {"nom": "Réutilisations du jeu IRCOM sur data.gouv.fr (cartostat « Revenus moyens 1992-2022 », Chiffres "
                "publics, Tout sur ma commune)", "url": "https://www.data.gouv.fr/datasets/536998cba3a729239d20505e",
         "licence": "sites, code non publié", "derniere_modification": "consulté le 2026-11-18",
         "verdict": "inspiration seulement",
         "usage": "aucun code ni jeu dérivé publié qui ramène toutes les années aux communes en vigueur"},
    ],
}

NON_REPRIS = [
    {"objet": "IRCOM 1993 à 2002 (revenus 1992 à 2001)",
     "motif": "autre format : foyers imposés et non imposés sans tranche de revenu fiscal de référence, impôt net des "
              "seuls foyers imposés, montants publiés en euros après conversion des francs ; non collectés par cet axe"},
    {"objet": "IRCOM, traitements et salaires, retraites et pensions",
     "motif": "colonnes publiées dans les mêmes fichiers, hors du périmètre de cet axe (impôt sur le revenu) ; "
              "lues pour le contrôle des formats, non publiées"},
    {"objet": "IRCOM, foyers non-résidents (direction des impôts des non-résidents, code « B31 »)",
     "motif": "lignes par pays de résidence, sans commune ; comptées dans les contrôles, non publiées"},
    {"objet": "Filosofi 2012 à 2020",
     "motif": "millésimes publiés par l'Insee dans d'autres géographies ; seuls le dernier millésime de Filosofi "
              "(2021) et Filosofi 2 (2023) sont repris dans cette version"},
]

DEFINITIONS = {
    "foyers": "nombre de foyers fiscaux : déclarations d'impôt sur le revenu déposées (une déclaration 2042 compte "
              "pour un foyer ; deux déclarations l'année d'un décès ou d'un mariage selon les années)",
    "foyers_imposes": "foyers fiscaux imposés (impôt final strictement positif, émission sur rôle) ; jusqu'à "
                      "l'année indiquée dans `ruptures`, la DGFiP publiait les « foyers fiscaux imposables »",
    "rfr_eur": "revenu fiscal de référence de l'ensemble des foyers (article 1417-IV du code général des impôts), en "
               "euros",
    "rfr_imposes_eur": "revenu fiscal de référence des foyers imposés (ou imposables, selon l'année), en euros",
    "impot_net_eur": "impôt net : somme de l'impôt sur le revenu payé ou restitué par l'ensemble des foyers, "
                     "déduction faite des prélèvements sociaux, pour la partie émise par rôle ; peut être négatif "
                     "dans les tranches basses (restitutions)",
    "mediane_eur": "niveau de vie médian (Insee) : médiane du revenu disponible par unité de consommation des "
                   "personnes des ménages fiscaux de la commune, en euros par an",
    "menages": "nombre de ménages fiscaux (Insee, Filosofi 2021) ; non publié à la commune dans Filosofi 2 (2023)",
}

REGLE_NULL = ("null dans une ligne publiée : valeur non communiquée par la source pour la commune ou pour au moins une "
              "des anciennes communes recomposées (« n.c. » ou « n.d. » : valeur non communiquée, secret statistique ; « . » : "
              "marque de la source sans définition dans la notice ; « #VALUE! » : erreur de calcul dans le fichier "
              "publié ; cellule vide). Une ligne entière null a sa raison dans `etat`. Jamais 0.")

ETATS = {
    "absente": "aucune ligne de la source pour cette commune ni pour ses anciennes communes cette année-là",
    "incomplete": "les codes de la source pour ce territoire ne correspondent au découpage d'aucune géographie (une "
                  "ancienne commune manque, ou fusions appliquées en partie) : aucune somme partielle",
    "perimetre": "une commune de la source couvrait aussi le territoire d'une autre commune actuelle (scission "
                 "postérieure) : aucune attribution",
}

STATUTS_FILOSOFI = {
    "publie": "valeur publiée par l'Insee",
    "secret": "valeur confidentielle (secret statistique, statut « C » de l'Insee)",
    "valeur_manquante": "valeur manquante à la source (statut « O » de l'Insee)",
    "hors_champ": "département hors du champ du millésime",
    "absente": "commune absente du fichier publié",
    "perimetre": "commune créée après la géographie du millésime : médianes des anciennes communes dans "
                 "`filosofi_anciennes`, jamais combinées (une médiane ne s'additionne pas)",
}

LIMITES = [
    "Les montants IRCOM décrivent l'impôt émis par rôle sur les revenus de l'année : les retenues à la source "
    "libératoires, les prélèvements forfaitaires et les crédits d'impôt correspondants ne sont pas comptés de la même "
    "façon selon les années (notices de la DGFiP dans chaque archive).",
    "Les tranches de revenu fiscal de référence changent : six tranches pour les revenus 2002, douze de 2003 à 2009 "
    "(bornes revues en 2006), huit depuis 2010 ; le détail par tranche n'est publié que pour une partie des "
    "communes, principalement celles d'environ 1 000 foyers fiscaux ou plus.",
    "Les communes sont celles du code officiel géographique en vigueur ; pour les années antérieures à une fusion, "
    "la valeur est la somme des anciennes communes, publiée comme telle (`recompose`).",
    "IRCOM compte des foyers fiscaux et leur revenu fiscal de référence ; Filosofi compte des ménages et leur revenu "
    "disponible par unité de consommation : les deux sources ne se comparent pas directement.",
    "Filosofi 2023 (Filosofi 2) n'est pas directement comparable aux millésimes 2012 à 2021 (changements de "
    "méthode signalés par l'Insee).",
]


# --- Lecture des valeurs ---------------------------------------------------------------------------------------------

def texte(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = unicodedata.normalize("NFC", str(v)).replace("\xa0", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def ascii_maj(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper()


def nombre(v):
    """Nombre publié, ou (None, marque) : une marque de la source n'est jamais lue comme 0."""
    if isinstance(v, bool):
        return None, "booleen"
    if isinstance(v, (int, float)):
        return (None, "nan") if v != v else (v, None)
    s = texte(v)
    if s == "":
        return None, "vide"
    t = s.replace(" ", "").replace(",", ".")
    if re.fullmatch(r"-?\d+(\.\d+)?", t):
        return float(t), None
    return None, s


def euros(v, facteur: int):
    return None if v is None else int(round(v * facteur))


def entier(v):
    return None if v is None else int(round(v))


def code_dep(v) -> str:
    s = re.sub(r"\.0$", "", texte(v))
    if re.fullmatch(r"\d{1,3}", s):
        return s.zfill(3)
    return s.upper()


def code_insee(dep3: str, commune) -> str | None:
    """Code Insee à partir du code de direction IRCOM (3 caractères) et du numéro de commune."""
    s = texte(commune)
    if not re.fullmatch(r"\d{1,3}", s):
        return None
    n = int(s)
    if n == 0:   # ligne de total sans commune (« 00 », Guadeloupe 2012)
        return None
    if dep3.startswith("97"):
        return dep3 + f"{n:02d}" if n < 100 else "97" + f"{n:03d}"
    if re.fullmatch(r"\d{2}[0-9]|2[AB]0", dep3):
        return dep3[:2] + f"{n:03d}"
    return None


def arrondissement(dep3: str, libelle: str) -> tuple[str, str] | None:
    """(commune, code de l'arrondissement) si la ligne est un arrondissement de Paris, Marseille ou Lyon."""
    ville = VILLES.get(dep3[:2])
    if not ville:
        return None
    m = re.match(rf"^{ville[1]}\b\D*(\d{{1,2}})", ascii_maj(libelle))
    if not m:
        return None
    n = int(m.group(1))
    if not 1 <= n <= ARRONDISSEMENTS[ville[0]]:
        return None
    return ville[0], (ville[2] + f"{n:02d}" if ville[0] != "69123" else ville[2] + str(n))


def bornes(libelle: str) -> tuple[int | None, int | None]:
    """Bornes d'une tranche publiée (« 0 à 10 000 », « + de 100 000 », « - de 9 000 », « Plus de 100 000 »)."""
    s = texte(libelle).replace(" ", "")
    m = re.fullmatch(r"(\d+)à(\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r"(?:\+de|Plusde)(\d+)", s, re.I)
    if m:
        return int(m.group(1)), None
    m = re.fullmatch(r"(?:-de|Moinsde)(\d+)", s, re.I)
    if m:
        return None, int(m.group(1))
    raise ValueError(f"tranche non reconnue : {libelle!r}")


def est_total(libelle: str) -> bool:
    return texte(libelle).upper() == "TOTAL"


# --- IRCOM : localisation des colonnes et lecture des lignes ----------------------------------------------------------

def colonnes_ircom(entete: list[str], sous_entete: list[str]) -> dict:
    """Position de chaque grandeur d'après les libellés de l'en-tête (et du sous-en-tête pour les salaires)."""
    pos = {}
    for j, h in enumerate(entete):
        b = ascii_maj(h)
        if b in ("DEP", "DEP."):
            pos["dep"] = j
        elif b == "COMMUNE":
            pos["commune"] = j
        elif b.startswith("LIBELLE DE LA COMMUNE") or b == "DEPARTEMENT":
            pos["libelle"] = j
        elif b.startswith("REVENU FISCAL DE REFERENCE PAR TRANCHE"):
            pos["tranche"] = j
        elif b.startswith("NOMBRE DE FOYERS FISCAUX IMPOS"):
            pos["foyers_imposes"] = j
            pos["_libelle_imposes"] = texte(h)
        elif b.startswith("NOMBRE DE FOYERS FISCAUX"):
            pos["foyers"] = j
        elif b.startswith("REVENU FISCAL DE REFERENCE DES FOYERS FISCAUX IMPOS"):
            pos["rfr_imposes_eur"] = j
        elif b.startswith("REVENU FISCAL DE REFERENCE DES FOYERS FISCAUX"):
            pos["rfr_eur"] = j
        elif b.startswith("IMPOT NET") and "AVANT CIMR" in b:
            pos["impot_net_avant_cimr_eur"] = j
        elif b.startswith("IMPOT NET"):   # « Impôt net (total) » ou, en 2018, « Impôt net (total, après CIMR) »
            if "impot_net_eur" in pos:
                raise ValueError(f"deux colonnes « Impôt net » sans distinction : {entete}")
            pos["impot_net_eur"] = j
        elif re.fullmatch(r"CIMR\W*", b):
            pos["cimr_eur"] = j
        elif b.startswith("TRAITEMENTS ET SALAIRES"):
            pos["salaires_foyers"], pos["salaires_eur"] = j, j + 1
        elif b.startswith("RETRAITES ET PENSIONS"):
            pos["pensions_foyers"], pos["pensions_eur"] = j, j + 1
    manquantes = [c for c in ["dep", "libelle", "tranche"] + LUES if c not in pos and c not in OPTIONNELLES]
    if manquantes:
        raise ValueError(f"colonnes IRCOM introuvables : {manquantes} dans {entete}")
    if sous_entete and ascii_maj(texte(sous_entete[pos["salaires_eur"]])) != "MONTANT":
        raise ValueError(f"sous-en-tête inattendu : {sous_entete}")
    return pos


def facteur_unite(lignes_haut: list[str]) -> tuple[int | None, str]:
    haut = " ".join(lignes_haut).lower()
    if "milliers d'euros" in haut or "milliers d’euros" in haut:
        return 1000, "milliers d'euros (mention du fichier ; bornes des tranches en euros)"
    if "montants en euros" in haut:
        return 1, "euros (mention du fichier)"
    return None, ""


def lire_feuille(lignes: list[list], nom: str, marques: Counter) -> dict:
    """Une feuille IRCOM (classeur départemental ou fichier communal complet) -> lignes de communes et du département."""
    i_ent = next((i for i, r in enumerate(lignes[:40])
                  if any(ascii_maj(texte(v)) == "COMMUNE" for v in r)
                  and any(ascii_maj(texte(v)) in ("DEP", "DEP.") for v in r)), None)
    if i_ent is None:
        raise ValueError(f"{nom} : en-tête des communes introuvable")
    entete = [texte(v) for v in lignes[i_ent]]
    sous = next(([texte(v) for v in r] for r in lignes[i_ent + 1:i_ent + 4]
                 if any(ascii_maj(texte(v)) == "MONTANT" for v in r)), [])
    pos = colonnes_ircom(entete, sous)
    facteur, methode = facteur_unite([texte(v) for r in lignes[:12] for v in r])
    out = {"pos": pos, "facteur": facteur, "unite_methode": methode, "communes": [], "departement": [],
           "libelle_imposes": pos["_libelle_imposes"], "lignes_sans_commune": 0,
           "cimr": all(c in pos for c in CIMR), "notes": [texte(v) for r in lignes for v in r[:3]
                                                         if re.match(r"^\*+ ", texte(v))]}
    derniere = max(v for k, v in pos.items() if not k.startswith("_"))
    for i, r in enumerate(lignes):
        if i <= i_ent or len(r) <= derniere:
            continue
        dep = code_dep(r[pos["dep"]])
        if not re.fullmatch(r"[0-9]{3}|2[AB]0|B31", dep):
            continue
        tranche = texte(r[pos["tranche"]])
        if not tranche:
            continue
        vals, ligne_marques = [], []
        for c in LUES:
            if c not in pos:   # colonne propre à une année (CIMR) : absente des autres
                vals.append(None)
                continue
            v, mq = nombre(r[pos[c]])
            if mq:
                ligne_marques.append(mq)
            vals.append(v)
        com = texte(r[pos["commune"]]) if "commune" in pos else ""
        if not com:   # sous-totaux de direction éventuels : jamais mêlés au total du département
            out["lignes_sans_commune"] += 1
            continue
        out["communes"].append({"dep": dep, "commune": com, "libelle": texte(r[pos["libelle"]]), "tranche": tranche,
                                "valeurs": vals, "marques": ligne_marques})
    # le bloc du département (classeurs départementaux) précède l'en-tête des communes : on le relit à part
    i_dep = next((i for i, r in enumerate(lignes[:i_ent])
                  if any(ascii_maj(texte(v)) in ("DEP", "DEP.") for v in r)
                  and any(ascii_maj(texte(v)) == "DEPARTEMENT" for v in r)), None)
    if i_dep is not None:
        for r in lignes[i_dep + 1:i_ent]:
            if len(r) <= derniere:
                continue
            dep = code_dep(r[pos["dep"]])
            tranche = texte(r[pos["tranche"]])
            if not re.fullmatch(r"[0-9]{3}|2[AB]0|B31", dep) or not tranche:
                continue
            vals = [nombre(r[pos[c]])[0] if c in pos else None for c in LUES]
            out["departement"].append({"dep": dep, "commune": "", "libelle": texte(r[pos["libelle"]]),
                                       "tranche": tranche, "valeurs": vals, "marques": []})
    for ligne in out["communes"]:
        for mq in ligne["marques"]:
            marques["(cellule vide)" if mq == "vide" else mq] += 1
    return out


def a_entete_communes(lignes: list[list]) -> bool:
    return any(any(ascii_maj(texte(v)) == "COMMUNE" for v in r) and any(ascii_maj(texte(v)) in ("DEP", "DEP.") for v in r)
               for r in lignes[:40])


def feuilles_xls(contenu: bytes, nom: str) -> list[list]:
    """Lignes de la feuille qui porte l'en-tête des communes (certains classeurs ont une feuille de brouillon)."""
    import xlrd
    b = xlrd.open_workbook(file_contents=contenu, on_demand=True)
    for k in range(b.nsheets):
        sh = b.sheet_by_index(k)
        lignes = [sh.row_values(i) for i in range(sh.nrows)]
        if a_entete_communes(lignes):
            return lignes
    raise ValueError(f"{nom} : aucune feuille ne porte l'en-tête des communes")


def feuilles_xlsx(flux, nom: str) -> list[list]:
    import openpyxl
    wb = openpyxl.load_workbook(flux, read_only=True, data_only=True)
    for ws in wb.worksheets:
        ws.reset_dimensions()
        lignes = [list(r) for r in ws.iter_rows(values_only=True)]
        if a_entete_communes(lignes):
            return lignes
    raise ValueError(f"{nom} : aucune feuille ne porte l'en-tête des communes")


def membres_departementaux(z: zipfile.ZipFile) -> list[tuple[str, bytes]]:
    """Classeurs départementaux d'une archive annuelle (dossier dep/, departemental/ ou archive imbriquée)."""
    out = []
    for n in sorted(z.namelist()):
        bas = n.lower()
        if bas.endswith("departemental.zip"):
            zz = zipfile.ZipFile(io.BytesIO(z.read(n)))
            out += [(f"{n}/{m}", zz.read(m)) for m in sorted(zz.namelist())
                    if re.search(r"(^|/)d?[0-9ab]{3}\.xls$", m.lower()) and "b31" not in m.lower().rsplit("/", 1)[-1]]
        elif re.search(r"(^|/)d?[0-9ab]{3}\.xls$", bas) and "/save/" not in bas and "b31" not in bas.rsplit("/", 1)[-1]:
            out.append((n, z.read(n)))   # b31 : non-résidents, sans commune
    return out


def annee_ressource(chemin: Path, url: str | None) -> int:
    for s in (url or "", chemin.name):
        m = re.search(r"revenus[-_](?:de[-_])?(\d{4})", s)
        if m:
            return int(m.group(1))
    raise ValueError(f"année introuvable : {chemin.name}")


def lire_ircom(chemin: Path, annee: int) -> dict:
    """Une année IRCOM : lignes des communes (codes de la source) et totaux départementaux."""
    marques = Counter()
    parties, fichier_source, reedite = [], "", False
    if chemin.suffix.lower() == ".xlsx":
        reedite = True
        parties.append(lire_feuille(feuilles_xlsx(chemin, chemin.name), chemin.name, marques))
        fichier_source = "fichier communal complet (xlsx), seule forme publiée pour cette année"
    else:
        z = zipfile.ZipFile(chemin)
        membres = membres_departementaux(z)
        if membres:
            for nom, contenu in membres:
                parties.append(lire_feuille(feuilles_xls(contenu, nom), nom, marques))
            fichier_source = f"{len(membres)} classeurs départementaux (xls) de l'archive"
        else:
            complet = [n for n in z.namelist() if re.search(r"ircom_communes_complet_revenus_\d{4}\.xlsx$", n)]
            if not complet:
                raise ValueError(f"{chemin.name} : ni classeur départemental ni fichier communal complet")
            parties.append(lire_feuille(feuilles_xlsx(io.BytesIO(z.read(complet[0])), complet[0]), complet[0], marques))
            fichier_source = "fichier communal complet (xlsx) de l'archive"
            reedite = True
    facteurs = {p["facteur"] for p in parties if p["facteur"]}
    if len(facteurs) > 1:
        raise ValueError(f"revenus {annee} : unités différentes selon les classeurs {facteurs}")
    facteur = facteurs.pop() if facteurs else None
    methode = next((p["unite_methode"] for p in parties if p["facteur"]), "")
    communes = [x for p in parties for x in p["communes"]]
    departement = [x for p in parties for x in p["departement"]]
    if facteur is None:   # aucune mention : rapport revenu fiscal de référence / foyers des totaux départementaux
        moyens = [x["valeurs"][2] / x["valeurs"][0] for x in departement
                  if est_total(x["tranche"]) and x["valeurs"][0] and x["valeurs"][2]]
        if not moyens:
            raise ValueError(f"revenus {annee} : unité indéterminable")
        if min(moyens) > 1000:
            facteur, methode = 1, "euros (aucune mention ; revenu fiscal de référence moyen par foyer supérieur à 1 000)"
        elif max(moyens) < 1000:
            facteur, methode = 1000, "milliers d'euros (aucune mention ; revenu fiscal de référence moyen inférieur à 1 000)"
        else:
            raise ValueError(f"revenus {annee} : unité ambiguë")
    libelles = Counter(p["libelle_imposes"] for p in parties)
    return {"annee": annee, "facteur": facteur, "unite_methode": methode, "communes": communes,
            "departement": departement, "marques": dict(sorted(marques.items())),
            "libelle_imposes": libelles.most_common(1)[0][0], "fichier_source": fichier_source, "reedite": reedite,
            "cimr": any(p["cimr"] for p in parties),
            "notes": sorted({n for p in parties for n in p["notes"]}),
            "lignes_sans_commune": sum(p["lignes_sans_commune"] for p in parties)}


# --- IRCOM : lignes -> communes de la source (codes Insee de l'année) -------------------------------------------------

def ordre_tranches(lignes: list[dict]) -> list[str]:
    """Libellés des tranches dans l'ordre publié (le plus fréquent par position, libellés numériques exclus)."""
    par_commune = defaultdict(list)
    for x in lignes:
        if not est_total(x["tranche"]):
            par_commune[(x["dep"], x["commune"])].append(x["tranche"])
    suites = Counter(tuple(v) for v in par_commune.values()
                     if not any(re.fullmatch(r"\d{1,2}", t) for t in v))
    if not suites:
        return []
    return list(suites.most_common(1)[0][0])


def communes_source(ircom: dict) -> tuple[dict, dict]:
    """{code source: {nom, total, tranches, arrondissements?}} et statistiques de lecture."""
    facteur = ircom["facteur"]
    tranches = ordre_tranches(ircom["communes"])
    for t in tranches:
        bornes(t)  # contrôle : tout libellé de tranche est compris
    stats = Counter()
    brut = defaultdict(lambda: {"nom": None, "total": None, "tranches": {}, "suite": []})
    hors = Counter()
    for x in ircom["communes"]:
        if x["dep"] == "B31":
            hors["lignes_non_residents"] += 1
            continue
        arr = arrondissement(x["dep"], x["libelle"])
        code = arr[1] if arr else code_insee(x["dep"], x["commune"])
        if code is None:
            stats["lignes_code_illisible"] += 1
            continue
        b = brut[code]
        b["nom"] = b["nom"] or x["libelle"]
        if arr:
            b["ville"] = arr[0]
        vals = [entier(v) if c not in MONTANTS else euros(v, facteur) for c, v in zip(LUES, x["valeurs"])]
        if est_total(x["tranche"]):
            b["total"] = vals
        else:
            b["suite"].append((x["tranche"], vals))
    sortie = {}
    for code, b in brut.items():
        tr = None
        if b["suite"]:
            libs = [t for t, _ in b["suite"]]
            # libellés numériques (« 01 », « 03 » : revenus 2002) lus comme rang de la tranche, si la position concorde
            lus = []
            for k, t in enumerate(libs):
                if re.fullmatch(r"\d{1,2}", t) and int(t) == k + 1 and k < len(tranches):
                    lus.append(tranches[k])
                    stats["tranches_lues_par_rang"] += 1
                else:
                    lus.append(t)
            if lus == tranches:
                tr = {t: v for t, (_, v) in zip(lus, b["suite"])}
            else:
                stats["communes_tranches_non_reconnues"] += 1
        if b["total"] is None:
            stats["communes_sans_total"] += 1
            continue
        sortie[code] = {"nom": b["nom"], "total": b["total"], "tranches": tr, "ville": b.get("ville")}
    stats.update(hors)
    return sortie, {"tranches": tranches, **dict(sorted(stats.items()))}


def villes(source: dict) -> dict:
    """Additionne les arrondissements de Paris, Marseille et Lyon dans leur commune (si tous sont publiés)."""
    par_ville = defaultdict(list)
    for code, v in source.items():
        if v.get("ville"):
            par_ville[v["ville"]].append(code)
    for ville, codes in sorted(par_ville.items()):
        lignes = [source.pop(c) for c in sorted(codes)]
        if ville in source:
            raise ValueError(f"{ville} publiée à la fois entière et par arrondissement")
        if len(codes) != ARRONDISSEMENTS[ville]:
            continue   # commune incomplète : absente (etat « incomplete » par la recomposition)
        total = somme([x["total"] for x in lignes])
        tranches = None
        if all(x["tranches"] for x in lignes) and len({tuple(x["tranches"]) for x in lignes}) == 1:
            tranches = {t: somme([x["tranches"][t] for x in lignes]) for t in lignes[0]["tranches"]}
        source[ville] = {"nom": ville, "total": total, "tranches": tranches, "arrondissements": sorted(codes)}
    return source


def somme(rangees: list[list]) -> list:
    """Somme colonne par colonne ; null si une valeur manque (jamais de somme partielle)."""
    out = []
    for col in zip(*rangees):
        out.append(None if any(v is None for v in col) else sum(col))
    return out


# --- Table de passage de l'Insee -----------------------------------------------------------------------------------

class Passage:
    """Table de passage annuelle de l'Insee, en mémoire compacte : une ligne par « atome » communal (plus petite unité
    stable de 2003 à 2026), avec son code dans chaque géographie."""

    def __init__(self, annees: list[int], atomes: list[tuple], niveaux: list[str], fichier: str):
        self.annees, self.atomes, self.niv, self.fichier = annees, atomes, niveaux, fichier
        self.col = {a: k for k, a in enumerate(annees)}
        self.par_code = {a: {} for a in annees}      # année -> code -> indices d'atomes
        for i, row in enumerate(atomes):
            for a, k in self.col.items():
                c = row[k]
                if c:
                    d = self.par_code[a]
                    d[c] = d[c] + (i,) if c in d else (i,)
        self.arm = {row[self.col[COG]] for row, n in zip(atomes, niveaux) if n == "ARM"}

    def existe(self, annee: int, code: str) -> bool:
        """Le code est celui d'une commune (pas d'un arrondissement) dans la géographie de l'année."""
        return code in self.par_code[annee] and code not in self.arm

    def vers(self, annee: int, code: str) -> set[str]:
        """Communes en vigueur couvertes par le code de l'année."""
        k = self.col[COG]
        return {self.atomes[i][k] for i in self.par_code[annee].get(code, ())}

    def depuis(self, annee: int, cible: str) -> set[str]:
        """Codes de l'année qui forment la commune en vigueur."""
        k = self.col[annee]
        return {self.atomes[i][k] for i in self.par_code[COG].get(cible, ()) if self.atomes[i][k]}

    def communes(self, annee: int) -> set[str]:
        return {c for c in self.par_code[annee] if c not in self.arm}


def lire_passage() -> Passage:
    if not ZIP_PASSAGE.exists():
        raise SystemExit(f"{ZIP_PASSAGE} absent : lancer `python pipeline/revenus_communes.py collecter`")
    z = zipfile.ZipFile(ZIP_PASSAGE)
    nom = next(n for n in z.namelist() if n.lower().endswith(".xlsx"))
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(z.read(nom)), read_only=True)
    ws = wb["COM"] if "COM" in wb.sheetnames else wb.worksheets[0]
    ws.reset_dimensions()
    lignes = ws.iter_rows(values_only=True)
    entete = None
    for r in lignes:
        if r and r[0] == "NIVGEO":
            entete = [texte(v) for v in r]
            break
    if not entete:
        raise ValueError("table de passage : en-tête NIVGEO introuvable")
    colonnes = {int(h[7:]): j for j, h in enumerate(entete) if re.fullmatch(r"CODGEO_\d{4}", h)}
    if max(colonnes) != COG:
        raise ValueError(f"table de passage en géographie {max(colonnes)}, attendu {COG}")
    annees = sorted(colonnes)
    atomes, niveaux, codes = [], [], {}
    for r in lignes:
        if not r or r[0] not in ("COM", "ARM"):
            continue
        atomes.append(tuple(codes.setdefault(texte(r[colonnes[a]]), texte(r[colonnes[a]])) for a in annees))
        niveaux.append(r[0])
    return Passage(annees, atomes, niveaux, nom)


def geographie_de(codes: set[str], passage: dict, annee_imposition: int) -> tuple[int, dict]:
    """Géographie (année du COG) dont la liste des communes diffère le moins de celle d'une année de la source
    (codes de la source absents de la géographie + communes de la géographie absentes de la source) ; à égalité, la
    plus proche de l'année d'imposition, puis la plus ancienne. Les codes des chefs-lieux de communes nouvelles
    existaient avant la fusion : compter les seuls codes connus ne suffit pas."""
    meilleur = None
    for a in passage.annees:
        geo_a = passage.communes(a)
        cle = (len(codes - geo_a) + len(geo_a - codes), abs(a - annee_imposition), a)
        if meilleur is None or cle < meilleur[0]:
            meilleur = (cle, a, geo_a)
    _, a, geo_a = meilleur
    inconnus = sorted(codes - geo_a)
    return a, {"codes_source": len(codes), "dans_geographie": len(codes) - len(inconnus),
               "communes_de_la_geographie_absentes": len(geo_a - codes), "non_rattaches": inconnus}


# --- Communes en vigueur (local/geo) ---------------------------------------------------------------------------------

def communes_vigueur() -> dict:
    """{dep: {"nom": nom du département, "communes": {code: nom}}} d'après site/data/local/geo."""
    out = {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[d["departement"]["code"]] = {"nom": d["departement"]["nom"],
                                         "communes": {c: v["nom"] for c, v in sorted(d["communes"].items())}}
    if not out:
        raise SystemExit("site/data/local/geo absent : lancer pipeline/local.py d'abord")
    return out


# --- Recomposition d'une année sur les communes en vigueur -----------------------------------------------------------

def recomposer(source: dict, geo: int, passage: "Passage", cibles: list[str], fenetre: int = 4) -> tuple[dict, dict]:
    """{code en vigueur: {"ligne", "tranches", "recompose"} ou {"etat", "details"}} pour une année, et rapprochement.

    Les fichiers IRCOM n'appliquent pas toujours toutes les fusions de l'année, et un même code peut désigner deux
    territoires selon la géographie (chef-lieu d'une commune nouvelle, commune rétablie). On forme donc des
    composantes : atomes communaux reliés par un code commun dans une géographie de la fenêtre (`geo` ± `fenetre`)
    ou dans la géographie en vigueur. Les codes de la source d'une composante doivent être exactement ses codes dans
    une même géographie (la plus proche de `geo` d'abord) ; ils sont alors lus dans cette géographie. Une commune en
    vigueur reçoit la somme de ses codes s'ils ne couvrent qu'elle (sinon « perimetre ») ; une composante sans
    géographie qui corresponde reste sans valeur (« incomplete »)."""
    ordre = sorted((a for a in passage.annees if abs(a - geo) <= fenetre), key=lambda a: (abs(a - geo), a))
    parent = list(range(len(passage.atomes)))

    def racine(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def unir(indices) -> None:
        indices = list(indices)
        r0 = racine(indices[0])
        for i in indices[1:]:
            r = racine(i)
            if r != r0:
                parent[max(r, r0)] = min(r, r0)
                r0 = min(r, r0)

    for a in sorted(set(ordre) | {COG}):
        for idx in passage.par_code[a].values():
            if len(idx) > 1:
                unir(idx)
    non_rattaches, atomes_code = [], {}
    for x in sorted(source):
        idx = sorted({i for a in ordre if passage.existe(a, x) for i in passage.par_code[a][x]})
        if not idx:
            non_rattaches.append(x)
            continue
        unir(idx)
        atomes_code[x] = idx
    composantes, codes_par_comp = defaultdict(list), defaultdict(set)
    k_cog = passage.col[COG]
    for i in range(len(passage.atomes)):
        composantes[racine(i)].append(i)
    for x, idx in atomes_code.items():
        codes_par_comp[racine(idx[0])].add(x)
    par_cible, autre_geo, ensemble_cibles = {}, 0, set(cibles)
    for r, atomes in sorted(composantes.items()):
        cibles_comp = sorted({passage.atomes[i][k_cog] for i in atomes} & ensemble_cibles)
        donnees = codes_par_comp.get(r, set())
        if donnees and not cibles_comp:   # territoire sans commune en vigueur (Saint-Barthélemy, Saint-Martin)
            non_rattaches += sorted(donnees)
            continue
        if not donnees:
            for t in cibles_comp:
                par_cible[t] = {"etat": "absente"}
            continue
        g_ok = next((g for g in ordre
                     if {passage.atomes[i][passage.col[g]] for i in atomes} - {""} == donnees), None)
        if g_ok is None:
            attendus = sorted({passage.atomes[i][passage.col[geo]] for i in atomes} - {""})
            for t in cibles_comp:
                par_cible[t] = {"etat": "incomplete", "details": {"codes_source": sorted(donnees),
                                                                  "codes_attendus": attendus}}
            continue
        autre_geo += len(donnees) if g_ok != geo else 0
        for t in cibles_comp:
            s = sorted(passage.depuis(g_ok, t))
            if not s:   # commune sans code dans cette géographie (Mayotte avant 2011)
                par_cible[t] = {"etat": "absente"}
                continue
            communs = {x: sorted(passage.vers(g_ok, x)) for x in s if passage.vers(g_ok, x) != {t}}
            if communs:
                par_cible[t] = {"etat": "perimetre", "details": communs}
                continue
            lignes = [source[x] for x in s]
            total = somme([x["total"] for x in lignes])
            tr = None
            if all(x["tranches"] for x in lignes):
                tr = {k: somme([x["tranches"][k] for x in lignes]) for k in lignes[0]["tranches"]}
            rec = []
            for x in s:
                rec += source[x].get("arrondissements", [x])
            par_cible[t] = {"ligne": total, "tranches": tr, "recompose": rec if rec != [t] else None,
                            "tranches_partielles": bool(any(x["tranches"] for x in lignes) and not tr)}
    out = {t: par_cible.get(t, {"etat": "absente"}) for t in cibles}
    rapprochement = {"codes_source": len(source), "codes_lus_dans_une_autre_geographie": autre_geo,
                     "fenetre_annees": [min(ordre), max(ordre)] if ordre else [],
                     "non_rattaches": sorted(non_rattaches)}
    return out, rapprochement


# --- Contrôles ---------------------------------------------------------------------------------------------------------

LECTURE_CONTROLES = ("somme des lignes « Total » des communes publiées dans le classeur départemental, comparée à la "
                     "ligne « Total » du département publiée par la DGFiP ; une valeur non communiquée (n.c.) manque à "
                     "la somme (`valeurs_non_communiquees`) ; un écart sans valeur non communiquée est publié tel quel")


def ecart(source, montant, autre_source, autre, **contexte) -> dict | None:
    if montant is None or autre is None:
        return None
    e = montant - autre
    return {**contexte, "source": source, "montant": montant, "autre_source": autre_source, "autre_montant": autre,
            "ecart": e, "ecart_pct": round(e / autre * 100, 3) if autre else None}


def controles_departements(ircom: dict, source_brut: dict, annee: int) -> list[dict]:
    """Somme des lignes communales publiées contre la ligne « Total » du département, par département."""
    facteur = ircom["facteur"]
    totaux = {}
    for x in ircom["departement"]:
        if est_total(x["tranche"]) and x["dep"] != "B31":
            vals = [entier(v) if c not in MONTANTS else euros(v, facteur) for c, v in zip(LUES, x["valeurs"])]
            totaux[x["dep"][:2] if not x["dep"].startswith("97") else x["dep"]] = vals
    sommes, masques = defaultdict(lambda: [0] * len(LUES)), defaultdict(lambda: [0] * len(LUES))
    for code, v in source_brut.items():
        dep = code[:3] if code.startswith("97") else code[:2]
        for k, x in enumerate(v["total"]):
            if x is None:
                masques[dep][k] += 1
            else:
                sommes[dep][k] += x
    out = []
    for dep in sorted(totaux):
        for k, c in enumerate(LUES):
            if c not in ("foyers", "rfr_eur", "impot_net_eur"):
                continue
            e = ecart("somme_des_communes_publiees", sommes[dep][k], "total_departemental_publie", totaux[dep][k],
                      annee=annee, departement=dep, grandeur=c, valeurs_non_communiquees=masques[dep][k])
            if e:
                out.append(e)
    return out


# --- Filosofi ----------------------------------------------------------------------------------------------------------

def lire_filosofi(chemin: Path, annee: int) -> dict:
    """{code commune: {mesure: (valeur, statut)}} pour MED_SL et NUM_HH (lecture en flux du CSV de l'Insee)."""
    if not chemin.exists():
        raise SystemExit(f"{chemin} absent : lancer `python pipeline/revenus_communes.py collecter`")
    z = zipfile.ZipFile(chemin)
    nom = next(n for n in z.namelist() if re.search(r"_data\.csv$", n))
    out = defaultdict(dict)
    with z.open(nom) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"), delimiter=";"):
            if r["GEO_OBJECT"] != "COM" or r["FILOSOFI_MEASURE"] not in ("MED_SL", "NUM_HH"):
                continue
            if str(r["TIME_PERIOD"]) != str(annee):
                raise ValueError(f"{chemin.name} : période {r['TIME_PERIOD']} au lieu de {annee}")
            v = r["OBS_VALUE"].strip()
            if r["CONF_STATUS"] == "C":
                val, statut = None, "secret"
            elif r["OBS_STATUS"] == "O" or v == "":
                val, statut = None, "valeur_manquante"
            else:
                val, statut = int(round(float(v))), "publie"
            out[r["GEO"]][r["FILOSOFI_MEASURE"]] = (val, statut)
    return {"fichier": nom, "communes": dict(out)}


def filosofi_vigueur(filo: dict, geo: int, passage: dict, cibles: list[str], dep_de: dict) -> tuple[dict, dict]:
    """Médiane par commune en vigueur ; anciennes communes à part (une médiane ne s'additionne pas)."""
    champ = {dep_de[c] for c in filo["communes"] if c in dep_de}
    champ |= {c[:3] if c.startswith("97") else c[:2] for c in filo["communes"]}
    out, anciennes = {}, {}
    for t in cibles:
        dep = dep_de[t]
        s = sorted(passage.depuis(geo, t))
        if dep not in champ:
            out[t] = [None, None, "hors_champ"]
            continue
        if s == [t] and passage.vers(geo, t) == {t}:
            m = filo["communes"].get(t)
            if not m:
                out[t] = [None, None, "absente"]
            else:
                med, st = m.get("MED_SL", (None, "absente"))
                out[t] = [med, m.get("NUM_HH", (None, None))[0], st]
            continue
        out[t] = [None, None, "perimetre"]
        anc = {}
        for x in s:
            m = filo["communes"].get(x)
            if m and passage.vers(geo, x) == {t}:
                med, st = m.get("MED_SL", (None, "absente"))
                anc[x] = [med, m.get("NUM_HH", (None, None))[0], st]
        if anc:
            anciennes[t] = anc
    return out, anciennes


# --- Production ----------------------------------------------------------------------------------------------------------

def dump(path: Path, obj, max_octets: int = MAX_OCTETS) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(txt.encode("utf-8"))
    if n > max_octets:
        raise SystemExit(f"{path} dépasse {max_octets} octets ({n} octets) : découper")
    tmp = path.with_suffix(".part")
    tmp.write_text(txt + "\n", encoding="utf-8")
    tmp.replace(path)
    return n


def manifeste() -> dict:
    p = LAKE / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def ressources_ircom(man: dict) -> list[tuple[int, Path, str | None]]:
    e = man.get(ID_IRCOM, {})
    urls = {f.get("chemin"): f.get("url") for f in e.get("fichiers", [])}
    out = []
    for p in sorted(DOSSIER_IRCOM.glob("*")):
        if p.suffix.lower() not in (".zip", ".xlsx") or p.name.endswith(".part"):
            continue
        url = urls.get(str(p.relative_to(ROOT)))
        out.append((annee_ressource(p, url), p, url))
    if not out:
        raise SystemExit(f"{DOSSIER_IRCOM} vide : lancer `python pipeline/revenus_communes.py collecter`")
    annees = [a for a, _, _ in out]
    if len(set(annees)) != len(annees):
        raise ValueError(f"années en double dans {DOSSIER_IRCOM} : {annees}")
    return sorted(out)


LECTURE_IMPOSES = ("libellé changé par la DGFiP : « foyers fiscaux imposables » (notice des revenus 2007 : foyers ayant "
                   "un impôt à acquitter ou ne bénéficiant pas d'un remboursement total de leurs crédits d'impôt, "
                   "dans la plupart des cas un impôt supérieur à 61 €), puis « foyers fiscaux imposés » (notice des "
                   "revenus 2012 : impôt final strictement positif) ; les deux séries ne se comparent pas directement")
LECTURE_CIMR = ("revenus 2018, année de mise en place du prélèvement à la source : `impot_net_eur` reprend la colonne "
                "« Impôt net (total, après CIMR) », qui porte la même définition (note « * ») que l'impôt net des "
                "autres années ; l'impôt avant CIMR et le CIMR sont publiés à part (`cimr`) ; les foyers imposés de "
                "cette année sont comptés après neutralisation du CIMR (note « *** » de la DGFiP)")
RUPTURES_DOCUMENTEES = [
    {"annee": 2006, "grandeur": "rfr_eur",
     "lecture": "réforme du barème de l'impôt sur le revenu applicable aux revenus 2006 (loi de finances pour 2006) : "
                "l'abattement de 20 % est intégré au barème et ne diminue plus le revenu fiscal de référence ; les "
                "bornes des tranches changent la même année"},
    {"annee": 2011, "grandeur": "foyers",
     "lecture": "décompte des foyers l'année d'un mariage : la notice des revenus 2007 compte trois déclarations "
                "(période commune et période antérieure pour chaque époux), la notice des revenus 2012 ne cite plus que "
                "le cas du décès"},
]


def norm_libelle(s: str) -> str:
    return re.sub(r"\s*\*+\s*$", "", texte(s))


def totaux_departementaux(ircom: dict) -> dict | None:
    """Somme des lignes « Total » des départements (hors non-résidents) : repère national, pas une donnée par commune."""
    facteur = ircom["facteur"]
    lignes = [x for x in ircom["departement"] if est_total(x["tranche"]) and x["dep"] != "B31"]
    if not lignes:
        return None
    out = {"departements": len(lignes)}
    for c in COLONNES + CIMR:
        vals = [x["valeurs"][LUES.index(c)] for x in lignes]
        if all(v is None for v in vals) and c in CIMR:
            continue
        out[c] = None if any(v is None for v in vals) else sum(
            entier(v) if c not in MONTANTS else euros(v, facteur) for v in vals)
    out["lecture"] = ("somme des lignes « Total » des départements publiées par la DGFiP, hors non-résidents ; repère "
                      "pour lire les ruptures, à ne pas additionner aux communes")
    return out


def ruptures_documentees(totaux: dict) -> list[dict]:
    """Ruptures expliquées par une réforme ou une règle de décompte, avec la variation constatée des totaux."""
    out = []
    for r in RUPTURES_DOCUMENTEES:
        a, g = r["annee"], r["grandeur"]
        avant, apres = (totaux.get(a - 1) or {}).get(g), (totaux.get(a) or {}).get(g)
        if avant is None or apres is None:
            continue
        unite = "Md€" if g.endswith("_eur") else "foyers"
        f = (lambda v: f"{v / 1e9:.1f}".replace(".", ",") + " Md€") if unite == "Md€" else \
            (lambda v: f"{v:,}".replace(",", " ") + " foyers")
        out.append({"annee": a, "grandeur": g, "type": "definition",
                    "constat": f"somme des totaux départementaux : {f(avant)} pour les revenus {a - 1}, {f(apres)} pour "
                               f"les revenus {a} ({(apres - avant) / avant * 100:+.1f} %)".replace(".", ","),
                    "lecture": r["lecture"]})
    return out


def produire(sortie: Path = SORTIE_DEFAUT, seulement: set[int] | None = None) -> dict:
    """Produit tout site/data/revenus_communes ; `seulement` (contrôles, tests) restreint les années lues."""
    man = manifeste()
    vigueur = communes_vigueur()
    dep_de = {c: dep for dep, d in vigueur.items() for c in d["communes"]}
    cibles = sorted(dep_de)
    passage = lire_passage()
    cog_communes = passage.communes(COG)
    ecarts_geo = {"communes_local_absentes_de_la_table": sorted(set(cibles) - cog_communes),
                  "communes_table_absentes_de_local": sorted(cog_communes - set(cibles))}
    date = date_sources("revenus_communes")
    ressources = [r for r in ressources_ircom(man) if not seulement or r[0] in seulement]
    annees = [a for a, _, _ in ressources]

    for d in ("communes", "tranches"):
        cible = sortie / d
        if cible.exists():
            for p in sorted(cible.rglob("*.json"), reverse=True):
                p.unlink()
            for p in sorted((x for x in cible.rglob("*") if x.is_dir()), reverse=True):
                p.rmdir()

    series = {t: [None] * len(annees) for t in cibles}
    etats = defaultdict(dict)
    recompositions = defaultdict(dict)
    avec_tranches = defaultdict(list)
    tranches_dep = defaultdict(dict)   # dep -> {annee: bloc de l'année}
    details_perimetre = defaultdict(dict)
    cimr = defaultdict(dict)
    infos_annees, controles, totaux = [], defaultdict(list), {}
    ruptures, libelle_prec, tranches_prec = [], None, None
    for k, (annee, chemin, url) in enumerate(ressources):
        ircom = lire_ircom(chemin, annee)
        brut, stats = communes_source(ircom)
        ctrl = controles_departements(ircom, brut, annee)
        totaux[annee] = totaux_departementaux(ircom)
        source = villes(dict(brut))
        geo, ecart_geo = geographie_de(set(source), passage, annee + 1)
        rec, rapprochement = recomposer(source, geo, passage, cibles)
        rapprochement = {**{kk: v for kk, v in ecart_geo.items() if kk != "non_rattaches"}, **rapprochement}
        tranches = stats.pop("tranches")
        colonnes_tr = COLONNES + (CIMR if ircom["cimr"] else [])
        lignes_tranches = defaultdict(dict)
        compte = Counter()
        for t, r in rec.items():
            if "ligne" in r:
                series[t][k] = [r["ligne"][LUES.index(c)] for c in COLONNES]
                if ircom["cimr"]:
                    cimr[t][str(annee)] = [r["ligne"][LUES.index(c)] for c in CIMR]
                compte["communes_publiees"] += 1
                if r["recompose"]:
                    recompositions[t][str(annee)] = r["recompose"]
                    compte["communes_recomposees"] += 1
                if r["tranches"]:
                    lignes_tranches[dep_de[t]][t] = [[r["tranches"][x][LUES.index(c)] for c in colonnes_tr]
                                                     for x in tranches]
                    avec_tranches[t].append(annee)
                    compte["communes_avec_tranches"] += 1
                if r["tranches_partielles"]:
                    compte["tranches_non_recomposees"] += 1
            else:
                etats[t][str(annee)] = r["etat"]
                compte[f"communes_{r['etat']}"] += 1
                if r.get("details"):
                    details_perimetre[t][str(annee)] = r["details"]
        fichiers_tranches = []
        bornes_tr = [{"libelle": x, "de_eur": bornes(x)[0], "a_eur": bornes(x)[1]} for x in tranches]
        for dep, communes in sorted(lignes_tranches.items()):
            tranches_dep[dep][str(annee)] = {
                "millesime": f"Revenus {annee} (IRCOM {annee + 1}, impôt sur les revenus de {annee} déclarés en "
                             f"{annee + 1})",
                "annee": annee, "tranches": bornes_tr, "colonnes": colonnes_tr,
                "communes": dict(sorted(communes.items()))}
            fichiers_tranches.append(dep)
        # ruptures relevées dans les fichiers (libellés, tranches, colonnes propres à une année)
        libelle = norm_libelle(ircom["libelle_imposes"])
        if not ircom["reedite"]:
            if libelle_prec and libelle_prec != libelle:
                ruptures.append({"annee": annee, "grandeur": "foyers_imposes", "type": "libelle",
                                 "constat": f"« {libelle_prec} » jusqu'aux revenus {annee - 1}, « {libelle} » ensuite",
                                 "lecture": LECTURE_IMPOSES})
            libelle_prec = libelle
        if tranches_prec is not None and tranches != tranches_prec:
            ruptures.append({"annee": annee, "grandeur": "tranches", "type": "tranches",
                             "constat": f"{len(tranches_prec)} tranches jusqu'aux revenus {annee - 1} (« "
                                        f"{tranches_prec[0]} » à « {tranches_prec[-1]} »), {len(tranches)} ensuite (« "
                                        f"{tranches[0]} » à « {tranches[-1]} »)",
                             "lecture": "les tranches de revenu fiscal de référence ne se comparent pas d'une période "
                                        "à l'autre ; les totaux par commune restent comparables"})
        tranches_prec = tranches
        if ircom["cimr"]:
            ruptures.append({"annee": annee, "grandeur": "impot_net_eur", "type": "colonnes",
                             "constat": "la DGFiP publie l'impôt net avant et après le crédit d'impôt de modernisation "
                                        "du recouvrement (CIMR) et le montant du CIMR",
                             "lecture": LECTURE_CIMR, "citations": ircom["notes"]})
        for c in ctrl:
            controles[c["departement"]].append(c)
        infos_annees.append({
            "annee": annee, "annee_imposition": annee + 1, "ircom": f"IRCOM {annee + 1}",
            "fichier_source": ircom["fichier_source"], "url": url, "geographie_source": geo,
            "rapprochement": {**{kk: v for kk, v in rapprochement.items() if kk != "non_rattaches"},
                              "non_rattaches": [{"code": c, "nom": source[c]["nom"],
                                                 "foyers": source[c]["total"][0]}
                                                for c in rapprochement["non_rattaches"]]},
            "unite_source": ircom["unite_methode"], "libelle_foyers_imposes": ircom["libelle_imposes"],
            **({"note_libelles": "fichier communal complet réédité par la DGFiP : libellés de colonnes harmonisés "
                                 "sur ceux des années récentes, pas forcément ceux de l'époque"}
               if ircom["reedite"] else {}),
            "notes_source": ircom["notes"],
            "tranches": bornes_tr, "colonnes_tranches": colonnes_tr, "marques_source": ircom["marques"],
            "lecture": {**{kk: v for kk, v in stats.items()},
                        "lignes_sans_commune_ignorees": ircom["lignes_sans_commune"]},
            "communes": dict(sorted(compte.items())),
            "totaux_departementaux": totaux[annee],
            "fichiers_tranches": f"revenus_communes/tranches/<dep>.json, par_annee.{annee}",
            "departements_tranches": fichiers_tranches,
        })
        print(f"revenus {annee} : géographie {geo}, {compte['communes_publiees']} communes, "
              f"{compte['communes_avec_tranches']} avec tranches, {len(rapprochement['non_rattaches'])} codes non "
              f"rattachés", flush=True)
    ruptures += ruptures_documentees(totaux)
    ruptures.sort(key=lambda x: (x["annee"], x["grandeur"], x["type"]))

    for dep, par_annee in sorted(tranches_dep.items()):
        ans = sorted(int(a) for a in par_annee)
        dump(sortie / "tranches" / f"{dep}.json", {
            "millesime": f"Revenus {ans[0]} à {ans[-1]} (IRCOM {ans[0] + 1} à {ans[-1] + 1}), années où la DGFiP "
                         f"publie ce détail pour au moins une commune du département",
            "source": SOURCES["ircom"]["titre"] + " ; " + SOURCES["ircom"]["page"],
            "unite": "foyers fiscaux ; euros", "date_sources": date,
            "departement": {"code": dep, "nom": vigueur[dep]["nom"]},
            "annees": ans, "regle_null": REGLE_NULL,
            "note": "par année (`par_annee.<annee>`) : une ligne par tranche, dans l'ordre de `tranches` de cette "
                    "année ; les tranches changent d'une période à l'autre (voir `ruptures` de l'index) ; communes en "
                    "vigueur ; une commune issue de fusions ne figure que si chacune de ses anciennes communes publie "
                    "ce détail (somme)",
            "par_annee": {str(a): par_annee[str(a)] for a in ans},
            "liens": {"communes": f"revenus_communes/communes/{dep}.json"}}, MAX_OCTETS_TELECHARGEMENT)

    # Filosofi
    filosofi = {}
    for an, chemin, geo_f, champ_txt in ((2021, ZIP_FILO21, 2025, "France métropolitaine, Martinique, La Réunion"),
                                        (2023, ZIP_FILO23, 2026, "France métropolitaine et La Réunion")):
        f = lire_filosofi(chemin, an)
        valeurs, anciennes = filosofi_vigueur(f, geo_f, passage, cibles, dep_de)
        filosofi[an] = {"valeurs": valeurs, "anciennes": anciennes, "geographie": geo_f, "fichier": f["fichier"],
                        "champ": champ_txt,
                        "statuts": dict(sorted(Counter(v[2] for v in valeurs.values()).items()))}

    # Fichiers par département
    resume, tailles = [], {}
    for dep in sorted(vigueur):
        communes = {}
        for t, nom in vigueur[dep]["communes"].items():
            c = {"nom": nom, "ircom": series[t]}
            if etats.get(t):
                c["etat"] = dict(sorted(etats[t].items()))
            if details_perimetre.get(t):
                c["perimetre"] = dict(sorted(details_perimetre[t].items()))
            if recompositions.get(t):
                c["recompose"] = dict(sorted(recompositions[t].items()))
            if avec_tranches.get(t):
                c["tranches"] = avec_tranches[t]
            if cimr.get(t):
                c["cimr"] = dict(sorted(cimr[t].items()))
            c["filosofi"] = [filosofi[an]["valeurs"][t] for an in sorted(filosofi)]
            anc = {str(an): filosofi[an]["anciennes"][t] for an in sorted(filosofi) if t in filosofi[an]["anciennes"]}
            if anc:
                c["filosofi_anciennes"] = anc
            communes[t] = c
        doc = {
            "millesime": f"Revenus {annees[0]} à {annees[-1]} (IRCOM) ; Filosofi 2021 et 2023 ; sources collectées au "
                         f"{date}",
            "source": "DGFiP, IRCOM (data.gouv.fr) ; Insee, Filosofi 2021 (base communale) et Filosofi 2 2023 "
                      "(Melodi) ; Insee, table de passage des communes 2026",
            "unite": "foyers fiscaux ; euros ; euros par an (niveau de vie médian)", "date_sources": date,
            "departement": {"code": dep, "nom": vigueur[dep]["nom"]},
            "annees": annees, "colonnes": COLONNES, "cimr_colonnes": CIMR,
            "filosofi_millesimes": sorted(filosofi), "filosofi_colonnes": ["mediane_eur", "menages", "statut"],
            "regle_null": REGLE_NULL, "etats": ETATS, "statuts_filosofi": STATUTS_FILOSOFI,
            "communes": communes,
            "controles": controles.get(dep, []), "controles_lecture": LECTURE_CONTROLES,
            "liens": {"geo": f"local/geo/{dep}.json", "index": "revenus_communes/index.json"},
        }
        tailles[dep] = dump(sortie / "communes" / f"{dep}.json", doc)
        resume.append({"code": dep, "nom": vigueur[dep]["nom"], "fichier": f"revenus_communes/communes/{dep}.json",
                       "communes": len(communes)})

    sources = {}
    for cle, s in SOURCES.items():
        s = dict(s)
        if s.get("id_catalogue"):
            e = man.get(s["id_catalogue"], {})
            s["collecte_le"] = (e.get("collecte_le") or "")[:10] or None
            s["statut_collecte"] = e.get("statut")
        sources[cle] = dict(sorted(s.items()))
    inaccessibles = [{"source": k, "constat": s.get("statut_collecte") or "absente de l'entrepôt"}
                     for k, s in sources.items() if s.get("id_catalogue") and s.get("statut_collecte") not in ("ok", "partiel")]
    nb_ctrl = sum(len(v) for v in controles.values())
    index = {
        "millesime": f"Revenus {annees[0]} à {annees[-1]} (IRCOM {annees[0] + 1} à {annees[-1] + 1}) ; Filosofi 2021 "
                     f"et 2023 ; sources collectées au {date}",
        "source": "DGFiP, IRCOM (data.gouv.fr) ; Insee, Filosofi ; Insee, table de passage des communes 2026",
        "unite": "foyers fiscaux ; euros ; euros par an (niveau de vie médian)",
        "date_sources": date,
        "geographie": {"cog": COG, "communes": len(cibles), "departements": len(vigueur),
                       "table_de_passage": passage.fichier, **ecarts_geo,
                       "jointure": "codes Insee des communes en vigueur, mêmes clés que local/geo/<dep>.json ; "
                                   "département du fichier = département de local/geo"},
        "annees": infos_annees,
        "colonnes": COLONNES,
        "definitions": DEFINITIONS,
        "ruptures": ruptures,
        "regle_null": REGLE_NULL, "etats": ETATS, "statuts_filosofi": STATUTS_FILOSOFI,
        "filosofi": [{"annee": an, "dispositif": "Filosofi" if an < 2023 else "Filosofi 2",
                      "geographie_source": filosofi[an]["geographie"], "champ": filosofi[an]["champ"],
                      "fichier_source": filosofi[an]["fichier"], "statuts": filosofi[an]["statuts"],
                      "communes_avec_anciennes": len(filosofi[an]["anciennes"])} for an in sorted(filosofi)],
        "departements": resume,
        "controles": {"nombre": nb_ctrl,
                      "egaux": sum(1 for v in controles.values() for c in v if c["ecart"] == 0),
                      "avec_valeurs_non_communiquees": sum(1 for v in controles.values() for c in v
                                                           if c["valeurs_non_communiquees"]),
                      "lecture": "par département et par année : somme des communes publiées contre le total "
                                 "départemental publié (foyers, revenu fiscal de référence, impôt net) ; détail dans "
                                 "communes/<dep>.json, champ `controles`"},
        "methode": [
            "Lecture : classeurs départementaux de chaque archive annuelle de la DGFiP (tous les départements) ; "
            "revenus 2002 : fichier communal complet, seule forme publiée. Colonnes repérées par leur libellé, unité "
            "lue dans le fichier (mention « milliers d'euros » ou « euros ») et, à défaut, déduite du revenu fiscal de "
            "référence moyen par foyer des totaux départementaux ; montants convertis en euros entiers.",
            "Géographie de chaque année : année du code officiel géographique qui contient le plus de codes de la "
            "source (`geographie_source`), d'après la table de passage annuelle de l'Insee ; codes absents de cette "
            "géographie publiés dans `rapprochement.non_rattaches`, non attribués.",
            "Communes en vigueur : somme des communes de la source qui forment aujourd'hui la commune (`recompose`) ; "
            "aucune somme si l'une manque (`etat` « incomplete ») ou si une commune de la source couvre aussi une "
            "autre commune actuelle (`etat` « perimetre »). Arrondissements de Paris, Marseille et Lyon additionnés "
            "dans leur commune quand tous sont publiés.",
            "Tranches : même règle ; libellés numériques « 01 », « 03 » du fichier des revenus 2002 lus comme rang "
            "de la tranche quand la position de la ligne concorde.",
            "Filosofi : niveau de vie médian (MED_SL) et ménages fiscaux (NUM_HH) des communes ; géographie de chaque "
            "millésime ramenée aux communes en vigueur sans combinaison de médianes.",
        ],
        "limites": LIMITES,
        "non_repris": NON_REPRIS,
        "regle": "agrégats publiés seulement, aucune donnée individuelle ; une valeur non communiquée reste null, "
                 "jamais 0 ; IRCOM et Filosofi ne s'additionnent pas ; aucune valeur n'est estimée",
        "tailles_octets": {"max_communes": max(tailles.values()), "total_communes": sum(tailles.values())},
        "sources": sources,
        "sources_inaccessibles": inaccessibles,
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "liens": {"geo": "local/geo/<dep>.json", "communes": "revenus_communes/communes/<dep>.json",
                  "tranches": "revenus_communes/tranches/<dep>.json"},
    }
    dump(sortie / "index.json", index)
    print(f"revenus_communes : {len(resume)} départements, {len(annees)} années, fichier max {max(tailles.values())} "
          f"octets, {nb_ctrl} contrôles")
    return index


def collecter() -> int:
    ids = [s["id_catalogue"] for s in SOURCES.values() if s.get("id_catalogue")]
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *ids])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT)
    ap.add_argument("--annees", help="contrôle : années de revenus à lire, séparées par des virgules (ex. 2002,2018)")
    a = ap.parse_args(argv)
    seulement = {int(x) for x in a.annees.split(",")} if a.annees else None
    if seulement and a.sortie.resolve() == SORTIE_DEFAUT.resolve():
        raise SystemExit("--annees réservé aux contrôles : préciser --sortie hors de site/data")
    if a.etape in ("collecter", "tout"):
        collecter()
    if a.etape in ("produire", "tout"):
        produire(a.sortie, seulement)


if __name__ == "__main__":
    main()
