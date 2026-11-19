"""Sécurité sociale et protection sociale : arbres de dépense en profondeur (module générique pipeline/arbre.py).

Entrées : entrepôt brut data/lake/secu/ (non versionné), rempli par `collecter` ou par collecte/catalogue.json
(type « url », fichier data/lake/secu/<id>.<format>).
Sorties (chaque fichier porte `millesime` et `source`) :
  site/data/secu/arbre/racine.json (+ sous-arbres)   comptes des organismes, exécution 2024 (vue par défaut)
  site/data/secu/arbre_2025/racine.json             comptes des organismes, exécution 2025 (premier niveau publié)
  site/data/secu/cps/racine.json (+ sous-arbres)    prestations de protection sociale 2024 (DREES), par régime
  site/data/secu/index.json                         vues, totaux, traçabilité, écarts, sources, recherche préalable

Commandes :
  python pipeline/secu.py collecter   # réseau : sources manquantes (reprenable), OCR des tableaux publiés en image
  python pipeline/secu.py produire    # sans réseau : écrit site/data/secu/
  python pipeline/secu.py             # les deux

Règles :
  - agrégats seulement (aucune donnée individuelle, aucune personne physique) ;
  - un montant publié est saisi avec sa page puis revérifié à chaque `produire` contre le texte du document (texte
    extrait du PDF ou de la page HTML, ou OCR mis en cache pour les tableaux publiés en image) : si le document a
    changé, la production échoue au lieu de publier un chiffre périmé ;
  - chaque feuille porte un mode de traçabilité : `publie` (lu tel quel dans le texte ou un jeu ouvert),
    `tableau_image` (lu dans un tableau publié en image, revérifié par OCR ou par une somme de contrôle),
    `derive` (calculé à partir de montants publiés : part publiée × total, différence, non ventilé de la source),
    `ecart` (différence de champ entre deux sources, publiée telle quelle) ;
  - les écarts entre sources ne sont jamais lissés : ils sont publiés dans `ecarts` ou comme nœud d'écart ;
  - comptabilité des organismes (CCSS, PLACSS) et comptes de la protection sociale (DREES, base comptabilité
    nationale) ne sont jamais additionnés : ce sont deux vues séparées.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import arbre  # noqa: E402  module générique (construire, _slug)

LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "secu"
OCR = BRUT / "_ocr_secu"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "secu"
UNITE = "milliards d'euros (Md€), dépenses (charges) de l'exercice"

# --- Sources (verdict de réutilisation, licence) -------------------------------------------------------------------

AN = "https://www.assemblee-nationale.fr/dyn"
SOURCES = {
    "placss2024": {
        "fichier": "secu_placss2024_texte.html", "url": f"{AN}/opendata/PRJLANR5L17B1456.html",
        "page": f"{AN}/17/textes/l17b1456_projet-loi.pdf",
        "titre": "Projet de loi d'approbation des comptes de la sécurité sociale 2024 (n° 1456, mai 2025), articles 1 "
                 "et 2 : tableau d'équilibre par branche des régimes obligatoires de base, FSV, ONDAM constaté, "
                 "dette amortie par la CADES",
        "producteur": "Gouvernement (DSS)", "millesime": "Exécution 2024",
        "licence": "document administratif public (CRPA L. 321-1)", "verdict": "réutilisable tel quel",
    },
    "placss2025": {
        "fichier": "secu_placss2025_texte.html", "url": f"{AN}/opendata/PRJLANR5L17B2843.html",
        "titre": "Projet de loi d'approbation des comptes de la sécurité sociale 2025 (n° 2843, 2026), articles 1 et 2",
        "producteur": "Gouvernement (DSS)", "millesime": "Exécution 2025",
        "licence": "document administratif public (CRPA L. 321-1)", "verdict": "réutilisable tel quel",
    },
    "placss2024_a3": {
        "fichier": "secu_placss2024_annexe3.pdf",
        "url": f"{AN}/contenu/visualisation/922636/file/PLACSS2024-Annexe3.pdf",
        "titre": "PLACSS 2024, annexe 3 « ONDAM et dépenses de santé » : premier constat 2024 par sous-objectif "
                 "(p. 12-13) et détail des soins de ville (tableau 7, p. 13, publié en image)",
        "producteur": "DSS", "millesime": "Exécution 2024 (constat de mars 2025)",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "réutilisable tel quel (tableaux en image : lus par OCR et revérifiés)",
    },
    "placss2024_a4": {
        "fichier": "secu_placss2024_annexe4.pdf",
        "url": f"{AN}/contenu/visualisation/922285/file/Annexe%204",
        "titre": "PLACSS 2024, annexe 4 « Recettes, dépenses et soldes du régime d'assurance chômage et des régimes de "
                 "retraite complémentaire » : compte consolidé des régimes complémentaires (tableau 2, p. 7) et poids "
                 "de l'Agirc-Arrco dans les prestations (tableau 1, p. 5)",
        "producteur": "DSS", "millesime": "Exécution 2024",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "réutilisable tel quel (tableaux en image : lus par OCR et revérifiés)",
    },
    "placss2024_a7": {
        "fichier": "secu_placss2024_annexe7.pdf",
        "url": f"{AN}/contenu/visualisation/922288/file/Annexe%207",
        "titre": "PLACSS 2024, annexe 7 « Comptes définitifs du FSV, de la CADES, du FRR... » : compte de résultat de "
                 "la CADES (p. 34) et compte détaillé du FSV (tableau 1, p. 68)",
        "producteur": "DSS", "millesime": "Exécution 2024 (comptes définitifs)",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "réutilisable tel quel (tableaux en image : OCR pour le FSV, somme de contrôle pour la CADES)",
    },
    "placss2024_a1_maladie": {
        "fichier": "secu_placss2024_annexe1_maladie.pdf",
        "url": f"{AN}/contenu/visualisation/922279/file/x",
        "titre": "PLACSS 2024, annexe 1 « Rapport d'évaluation des politiques de sécurité sociale, Maladie », "
                 "édition 2025, synthèse p. 7",
        "producteur": "DSS", "millesime": "Exécution 2024",
        "licence": "document administratif public (CRPA L. 321-1)", "verdict": "réutilisable tel quel",
    },
    "dss_chiffres_cles_2024": {
        "fichier": "secu_dss_chiffres_cles_2024.pdf",
        "url": "https://solidarites.gouv.fr/sites/solidarite/files/2025-09/Chiffres-cles-DSS-2024-ed25.pdf",
        "titre": "Les chiffres clés de la sécurité sociale 2024, édition 2025 (DSS, d'après la CCSS de juin 2025) : "
                 "prestations nettes par branche, structure des charges (graphiques 10, 16, 19)",
        "producteur": "DSS", "millesime": "Exécution 2024",
        "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "réutilisable tel quel (parts lues sur les graphiques, arrondies à 1 % par la source)",
    },
    "unedic": {
        "fichier": "datagouv__depenses-et-recettes-de-lassurance-chomage/financement-de-l-assurance-chomage_47a22bbe.csv",
        "url": "https://www.data.gouv.fr/fr/datasets/depenses-et-recettes-de-lassurance-chomage/",
        "titre": "Unédic, « Dépenses et recettes de l'assurance chômage » (data.gouv.fr, mis à jour le 01/09/2026), M€",
        "producteur": "Unédic", "millesime": "Exécution 2024 et 2025",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel (déjà dans l'entrepôt)",
    },
    "drees_cps": {
        "fichier": "secu_protection_sociale.parquet",
        "url": "https://data.drees.solidarites-sante.gouv.fr/explore/dataset/305_les-comptes-de-la-protection-sociale/",
        "titre": "DREES, Comptes de la protection sociale 1959-2024 : prestations par régime et par prestation (M€)",
        "producteur": "DREES", "millesime": "2024",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel (déjà dans l'entrepôt, catalogue "
                                                     "secu_protection_sociale)",
    },
}

INACCESSIBLES = [
    {"source": "Rapport à la Commission des comptes de la sécurité sociale de juin 2025 (résultats 2024), tableaux de "
               "charges par nature de chaque branche",
     "motif": "non localisé sur une URL stable joignable : la notice vie-publique.fr exige JavaScript et cookies, le "
              "PDF 299216 téléchargé est le rapport d'octobre 2024 (résultats 2023). Les parts publiées dans les "
              "« Chiffres clés 2024 » (même source) sont utilisées à la place"},
    {"source": "Open DAMIR, Open Medic, Open Bio, Open LPP (Assurance maladie)",
     "motif": "l'entrepôt ne contient que les pages HTML de téléchargement d'ameli.fr (fichiers mensuels de plusieurs "
              "Go non collectés) ; non intégrés : remboursements interrégimes en date de soins, champ différent de "
              "l'ONDAM"},
    {"source": "Comptes 2025 de l'Agirc-Arrco et compte de résultat 2025 de la CADES",
     "motif": "annexes du PLACSS 2025 non collectées ; l'arbre 2025 s'arrête aux montants du texte de loi"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "conclusion": "Aucun dépôt ni jeu ouvert ne fournit les comptes des branches par nature déjà structurés : arbre "
                  "construit sur le module générique du dépôt (pipeline/arbre.py), à partir des jeux ouverts DREES et "
                  "Unédic (réutilisables tels quels) et des annexes du PLACSS (lecture vérifiée).",
    "trouvailles": [
        {"nom": "DREES, Comptes de la protection sociale (ODS 305)", "url": SOURCES["drees_cps"]["url"],
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "données 2024", "verdict": "réutilisable tel quel"},
        {"nom": "Unédic, Dépenses et recettes de l'assurance chômage", "url": SOURCES["unedic"]["url"],
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-09-01", "verdict": "réutilisable tel quel"},
        {"nom": "PLACSS 2024 et 2025 (texte et annexes 1, 3, 4, 7)", "url": SOURCES["placss2024"]["url"],
         "licence": "document administratif public", "mise_a_jour": "2025 et 2026",
         "verdict": "à adapter (tableaux en image, lus par OCR)"},
        {"nom": "data.gouv.fr, « Comptes simplifiés des régimes de base » et rapports Cour des comptes 2015-2022",
         "url": "https://www.data.gouv.fr/fr/datasets/comptes-simplifies-des-regimes-de-base-de-securite-sociale-30378403/",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2014-01-06 (dernier millésime ancien)",
         "verdict": "inspiration seulement"},
        {"nom": "raphaeleadjerad/opendamir (agrégation Open DAMIR avec dask)",
         "url": "https://github.com/raphaeleadjerad/opendamir", "licence": "MPL-2.0",
         "dernier_commit": "2020-04-24", "verdict": "inspiration seulement"},
        {"nom": "Sofiane-h31/Projet-Damir (pipeline Open DAMIR 2015-2025)",
         "url": "https://github.com/Sofiane-h31/Projet-Damir", "licence": "aucune (réutilisation non autorisée)",
         "dernier_commit": "2026-04-17", "verdict": "inspiration seulement"},
        {"nom": "TLxFroSt/open-damir-lakehouse", "url": "https://github.com/TLxFroSt/open-damir-lakehouse",
         "licence": "aucune (réutilisation non autorisée)", "dernier_commit": "2026-10-03",
         "verdict": "inspiration seulement"},
        {"nom": "Recherches GitHub « ondam », « plfss », « comptes sécurité sociale »", "url": "https://github.com/search",
         "licence": None, "dernier_commit": None, "verdict": "aucun dépôt pertinent (homonymes)"},
    ],
}

# --- Montants publiés et motifs de vérification ---------------------------------------------------------------------
# Le motif est comparé au texte normalisé (espaces supprimés, apostrophes et tirets unifiés). Dans MOTIFS_*_OCR, la
# clé est l'index de page du PDF compté à partir de 0 (page imprimée différente) ; « p. » dans `ref` = page imprimée.

M = 1e6
MD = 1e9

# Texte du PLACSS 2024, article 1 (régimes obligatoires de base, Md€) et article 2
ROBSS_2024 = {"maladie": 253.0, "atmp": 16.3, "vieillesse": 293.8, "famille": 57.8, "autonomie": 39.9}
ROBSS_2024_TOTAL_Y_C_FSV = 643.1
MOTIFS_PLACSS2024 = ["Maladie 239,2 253,0", "professionnelles 16,9 16,3 0,7", "Vieillesse 288,2 293,8",
                     "Famille 58,9 57,8 1,1", "Autonomie 41,2 39,9 1,3", "626,4 642,8", "627,8 643,1",
                     "s'élevant à 256,4 milliards d'euros", "s'élevant à 16 milliards d'euros"]
ROBSS_2025 = {"maladie": 262.6, "atmp": 17.4, "vieillesse": 304.1, "famille": 58.5, "autonomie": 41.8}
ROBSS_2025_TOTAL_Y_C_FSV = 666.0
FSV_2025 = 21.4
MOTIFS_PLACSS2025 = ["Maladie 246,7 262,6", "17,2 17,4 -0,2", "Vieillesse 297,0 304,1", "Famille 59,7 58,5 1,2",
                     "Autonomie 41,9 41,8 0,1", "644,4 666,0", "Fonds de solidarité vieillesse 21,8 21,4 0,4",
                     "s'élevant à 265,4 milliards d'euros", "s'élevant à 16,2 milliards d'euros"]

# Annexe 3, texte (Md€) et tableau 7 (image, M€)
MOTIFS_A3 = ["Les dépenses de soins de ville hors crise atteignent 109,6 Md€",
             "établissements de santé s'élèvent à 105,5 Md€", "ONDAM médico-social s'élèvent à 31,2 Md€",
             "personnes âgées représentent 16,1 Md€", "situation de handicap 15,1 Md€",
             "se sont élevées à 6,6 Md€", "s'élèvent à 3,1 Md€", "ont atteint 0,4 Md€ en 2024"]
SOINS_DE_VILLE = [  # (clé, libellé, M€, sous-lignes)
    ("honoraires_medicaux", "Honoraires médicaux et dentaires", 26821, None),
    ("produits_sante", "Produits de santé (médicaments, dispositifs médicaux), nets des remises", 34182, [
        ("medicaments", "Médicaments remboursés (avant remises)", 31368),
        ("dispositifs_medicaux", "Dispositifs médicaux", 8983),
        ("remises", "Remises des laboratoires (en déduction)", -5082),
        ("clause_sauvegarde", "Clause de sauvegarde (en déduction)", -1086),
    ]),
    ("indemnites_journalieres", "Indemnités journalières (arrêts de travail maladie et AT-MP)", 17083, None),
    ("honoraires_paramedicaux", "Honoraires paramédicaux (infirmiers, kinésithérapeutes...)", 16200, None),
    ("transports", "Transports de patients", 6280, None),
    ("laboratoires", "Laboratoires de biologie médicale", 3456, None),
    ("remunerations_forfaitaires", "Rémunérations forfaitaires des médecins", 2484, None),
    ("autres_prestations", "Autres prestations de ville", 440, None),
    ("hors_prestations", "Hors prestations (cotisations des professionnels de santé, taxe sur les complémentaires)",
     2694, [
         ("cotisations_ps", "Prise en charge des cotisations des professionnels de santé", 2744),
         ("taxe_unocam", "Contribution des organismes complémentaires (en déduction)", -371),
     ]),
]
SOINS_DE_VILLE_TOTAL = 109638
MOTIFS_A3_OCR = {13: ["109638", "106945", "26821", "2484", "16200", "3456", "6280", "17083", "34182", "31368",
                      "-5082", "-1086", "8983", "2694", "2744", "-371"]}

# Annexe 4, tableau 2 (image, M€) : compte consolidé des régimes complémentaires obligatoires 2024
COMPLEMENTAIRES = {"charges": 120202, "retraite": 110855, "autres_prestations": 247,
                   "transferts": 4566, "rafp": 2990, "adossement": 1551, "autres_transferts": 24,
                   "autres_charges": 4534, "financieres": 1386, "gestion": 2708, "techniques": 440}
PART_AGIRC_ARRCO = 0.872
MOTIFS_A4_OCR = {7: ["120202", "110855", "4566", "2990", "1551", "4534", "1386", "2708"], 5: ["87,2%"]}

# Annexe 7 : FSV, tableau 1 (image, M€) ; CADES, compte de résultat (image pivotée, k€)
FSV_2024 = {"charges": 20457, "chomage": 12581, "maladie": 2333, "formation": 241, "service_national": 46,
            "prises_en_charge": 15254, "minimum_vieillesse": 4868, "complementaires": 221, "far": 64, "autres": 49}
MOTIFS_A7_OCR = {68: ["20457", "12581", "2333", "241", "4868", "221", "15254"]}
CADES_2024_KEUR = {"personnel": 862.1, "fonctionnement": 3423059.0, "charges": 3423921.2, "resultat": 15988628.8,
                   "produits": 19412550.0}

# Chiffres clés 2024 (texte) et parts lues sur les graphiques
MOTIFS_CC = ["13,0 milliards d'euros de prestations nettes", "288,5 milliards d'euros de prestations nettes",
             "234,6 milliards d'euros de prestations", "39,9 milliards d'euros en 2024"]
PARTS_ATMP = {"Indemnités journalières": 32, "Prestations de soins (incapacité temporaire hors IJ)": 7,
              "Charges amiante (Acaata et dotation au Fiva)": 4, "Incapacité permanente (rentes et capital)": 37,
              "Autres charges (dont transferts vers d'autres organismes)": 20}
PARTS_FAMILLE = {"Allocations en faveur des familles (allocations familiales...)": 65,
                 "Prestations d'accueil du jeune enfant (Paje)": 34, "Autres (principalement frais de tutelle)": 1}
PARTS_AUTONOMIE = {"aeeh_ajpa": 4, "gestion": 1, "transferts": 17}
MOTIFS_A1 = ["prestations nettes", "qui s'élèvent à 218,9 Md€"]

# Correspondance avec les destinataires de site/data/prelevements/affectation.json
DESTINATAIRES = {"maladie": "cnam", "atmp": "branche_atmp", "vieillesse": "cnav", "famille": "cnaf",
                 "autonomie": "cnsa", "agirc_arrco": "agirc_arrco", "unedic": "unedic", "cades": "cades"}

# --- Utilitaires -------------------------------------------------------------------------------------------------


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def normaliser(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    for a, b in (("’", "'"), ("‑", "-"), ("–", "-"), ("−", "-"), (" ", " "), (" ", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", "", s)


def chemin(cle: str) -> Path:
    return BRUT / SOURCES[cle]["fichier"]


def texte_source(cle: str) -> str | None:
    """Texte extrait (PDF : pdfplumber, HTML : balises retirées), mis en cache à côté de l'entrepôt."""
    src = chemin(cle)
    if not src.exists():
        return None
    cache = OCR / (src.name + ".txt")
    if cache.exists() and cache.stat().st_mtime >= src.stat().st_mtime:
        return cache.read_text(encoding="utf-8")
    if src.suffix == ".html":
        brut = src.read_text(encoding="utf-8", errors="ignore")
        t = html_lib.unescape(re.sub(r"<[^>]+>", " ", brut))
    else:
        import pdfplumber
        with pdfplumber.open(src) as doc:
            t = "\n".join((p.extract_text() or "") for p in doc.pages)
    OCR.mkdir(parents=True, exist_ok=True)
    cache.write_text(t, encoding="utf-8")
    return t


def ocr_page(cle: str, page: int) -> str | None:
    """OCR (tesseract, fra) d'une page (numérotation 1 = première page du PDF), mis en cache."""
    src = chemin(cle)
    cache = OCR / f"{src.stem}_p{page}.ocr.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    if not src.exists() or not shutil.which("tesseract") or not shutil.which("pdftoppm"):
        return None
    OCR.mkdir(parents=True, exist_ok=True)
    base = OCR / f"{src.stem}_p{page}"
    subprocess.run(["pdftoppm", "-r", "250", "-f", str(page), "-l", str(page), "-png", "-singlefile", str(src),
                    str(base)], check=True, capture_output=True)
    r = subprocess.run(["tesseract", f"{base}.png", "-", "-l", "fra", "--psm", "6"], capture_output=True, text=True)
    (base.with_suffix(".png")).unlink(missing_ok=True)
    cache.write_text(r.stdout, encoding="utf-8")
    return r.stdout


def verifier_documents() -> dict:
    """Chaque montant saisi doit se retrouver dans le document (texte ou OCR) ; sinon arrêt."""
    controles = [("placss2024", None, MOTIFS_PLACSS2024), ("placss2025", None, MOTIFS_PLACSS2025),
                 ("placss2024_a3", None, MOTIFS_A3), ("dss_chiffres_cles_2024", None, MOTIFS_CC),
                 ("placss2024_a1_maladie", None, MOTIFS_A1)]
    controles += [("placss2024_a3", p + 1, m) for p, m in MOTIFS_A3_OCR.items()]
    controles += [("placss2024_a4", p + 1, m) for p, m in MOTIFS_A4_OCR.items()]
    controles += [("placss2024_a7", p + 1, m) for p, m in MOTIFS_A7_OCR.items()]
    out: dict = {}
    for cle, page, motifs in controles:
        t = texte_source(cle) if page is None else ocr_page(cle, page)
        nom = cle if page is None else f"{cle} p. {page} (OCR)"
        if t is None:
            out[nom] = {"statut": "document ou OCR absent : valeurs saisies non revérifiées", "motifs": len(motifs)}
            continue
        tn = normaliser(t)
        manquants = [m for m in motifs if normaliser(m) not in tn]
        out[nom] = {"statut": "vérifié" if not manquants else "écart", "motifs": len(motifs), "manquants": manquants}
        if manquants:
            raise SystemExit(f"{nom} : montants saisis introuvables dans le document (a-t-il changé ?) : {manquants}")
    # Sommes de contrôle des tableaux lus en image
    c = CADES_2024_KEUR
    if abs(c["personnel"] + c["fonctionnement"] - c["charges"]) > 1 or abs(c["charges"] + c["resultat"]
                                                                           - c["produits"]) > 1:
        raise SystemExit("CADES : charges + résultat != produits (saisie à revoir)")
    out["placss2024_a7 p. 35 (CADES, tableau pivoté)"] = {
        "statut": "vérifié par somme de contrôle (charges + résultat = produits, au k€ près) et par l'article 2 du "
                  "PLACSS (dette amortie : 16 Md€)", "motifs": 5}
    sv = sum(v for _, _, v, _ in SOINS_DE_VILLE)
    if abs(sv - SOINS_DE_VILLE_TOTAL) > 3:
        raise SystemExit(f"soins de ville : somme {sv} != {SOINS_DE_VILLE_TOTAL}")
    return out


# --- Lignes plates pour arbre.construire -------------------------------------------------------------------------

NIVEAUX = ["organisme", "branche", "poste", "sous_poste", "detail"]


def ligne(chemin_cles: list[tuple[str, str]], md: float, source: str, mode: str, note: str | None = None,
          ref: str | None = None) -> dict:
    """chemin_cles : [(clé, libellé), ...] du niveau 1 à la feuille ; md en milliards d'euros."""
    r = {"eur": md * MD, "source": source, "mode": mode, "note": note, "ref": ref}
    for niv, (cle, lib) in zip(NIVEAUX, chemin_cles):
        r[niv] = cle
        r[f"lib_{niv}"] = lib
    return r


def lignes_2024() -> tuple[list[dict], dict]:
    L: list[dict] = []
    ecarts: dict[str, list] = {}
    rob = ("robss", "Régimes obligatoires de base (toutes branches) et Fonds de solidarité vieillesse")
    mal = ("maladie", "Assurance maladie (branche maladie)")
    # Branche maladie : ONDAM (hors médico-social) + écart de champ
    ondam = [("ondam_soins_de_ville", "ONDAM : soins de ville", SOINS_DE_VILLE_TOTAL / 1e3, "tableau_image",
              "PLACSS 2024 annexe 3, tableau 7 (constat comptable de mars 2025, hors crise sanitaire)"),
             ("ondam_etablissements", "ONDAM : établissements de santé (hôpitaux, cliniques)", 105.5, "publie",
              "PLACSS 2024 annexe 3, p. 13"),
             ("ondam_fir", "ONDAM : fonds d'intervention régional et soutien à l'investissement", 6.6, "publie",
              "PLACSS 2024 annexe 3, p. 14"),
             ("ondam_autres", "ONDAM : autres prises en charge (soins des Français à l'étranger, agences sanitaires)",
              3.1, "publie", "PLACSS 2024 annexe 3, p. 14"),
             ("ondam_crise", "ONDAM : dépenses liées à la crise sanitaire (covid)", 0.4, "publie",
              "PLACSS 2024 annexe 3, p. 11")]
    for cle, lib, md, mode, ref in ondam:
        if cle == "ondam_soins_de_ville":
            for k, l, v, sous in SOINS_DE_VILLE:
                if sous:
                    for k2, l2, v2 in sous:
                        L.append(ligne([rob, mal, (cle, lib), (k, l), (k2, l2)], v2 / 1e3, "placss2024_a3",
                                       "tableau_image", ref=ref))
                    reste = v - sum(x[2] for x in sous)
                    if reste:
                        petit = abs(reste) <= 2
                        L.append(ligne([rob, mal, (cle, lib), (k, l),
                                        ("arrondis" if petit else "non_ventile",
                                         "Arrondis de la source" if petit else "Non ventilé par la source")],
                                       reste / 1e3, "placss2024_a3", "derive",
                                       note="différence entre le total publié et ses lignes « dont »", ref=ref))
                else:
                    L.append(ligne([rob, mal, (cle, lib), (k, l)], v / 1e3, "placss2024_a3", "tableau_image", ref=ref))
            arrondi = SOINS_DE_VILLE_TOTAL - sum(x[2] for x in SOINS_DE_VILLE)
            if arrondi:
                L.append(ligne([rob, mal, (cle, lib), ("arrondis", "Arrondis de la source")], arrondi / 1e3,
                               "placss2024_a3", "derive", note="total publié moins somme des lignes publiées", ref=ref))
        else:
            L.append(ligne([rob, mal, (cle, lib)], md, "placss2024_a3", mode, ref=ref))
    ondam_maladie = SOINS_DE_VILLE_TOTAL / 1e3 + 105.5 + 6.6 + 3.1 + 0.4
    L.append(ligne([rob, mal, ("hors_ondam", "Hors ONDAM et écart de champ avec l'ONDAM (non ventilé)")],
                   ROBSS_2024["maladie"] - ondam_maladie, "placss2024", "ecart",
                   note="charges de la branche (253,0 Md€, tous régimes de base) moins les sous-objectifs ONDAM hors "
                        "médico-social : prestations en espèces maternité et invalidité, soins d'assurés de régimes "
                        "étrangers, transferts, gestion, charges financières, net de la part AT-MP comprise dans "
                        "l'ONDAM (IJ et soins des accidents du travail) et des différences de référentiel comptable "
                        "(PLACSS 2024 annexe 3, p. 6)"))
    ecarts["robss/maladie"] = [
        {"source": "placss2024_a1_maladie", "md": 218.9, "libelle": "prestations nettes de la branche maladie"},
        {"source": "dss_chiffres_cles_2024", "md": 234.6,
         "libelle": "prestations nettes versées par les régimes de base (champ maladie, publication différente)"},
        {"source": "drees_cps", "md": None,
         "libelle": "les comptes de la protection sociale (vue « cps ») rangent les soins des hôpitaux publics dans un "
                    "régime distinct de la CNAM : comparaison au niveau des prestations seulement"}]
    # AT-MP
    at = ("atmp", "Accidents du travail et maladies professionnelles (branche AT-MP)")
    L.append(ligne([rob, at, ("prestations_nettes", "Prestations nettes (IJ, soins, rentes, amiante)")], 13.0,
                   "dss_chiffres_cles_2024", "publie", ref="Chiffres clés 2024, p. 15"))
    L.append(ligne([rob, at, ("autres_charges", "Autres charges (transferts vers d'autres branches, gestion)")],
                   ROBSS_2024["atmp"] - 13.0, "placss2024", "derive",
                   note="charges de la branche (PLACSS) moins prestations nettes (Chiffres clés)"))
    # Vieillesse
    vi = ("vieillesse", "Retraite de base (branche vieillesse, tous régimes de base)")
    L.append(ligne([rob, vi, ("prestations_nettes", "Pensions et prestations nettes, tous régimes de base "
                                                    "(dont fonctionnaires, collectivités, agricoles, spéciaux)")],
                   288.5, "dss_chiffres_cles_2024", "publie", ref="Chiffres clés 2024, p. 18"))
    L.append(ligne([rob, vi, ("autres_charges", "Autres charges (transferts, gestion, charges financières)")],
                   ROBSS_2024["vieillesse"] - 288.5, "placss2024", "derive",
                   note="charges de la branche (PLACSS) moins prestations nettes (Chiffres clés)"))
    # Famille : aucun montant par nature publié dans les sources collectées
    fa = ("famille", "Famille (branche famille)")
    L.append(ligne([rob, fa], ROBSS_2024["famille"], "placss2024", "publie", ref="PLACSS 2024, article 1"))
    # Autonomie
    au = ("autonomie", "Autonomie (branche autonomie, CNSA)")
    L.append(ligne([rob, au, ("ondam_pa", "Établissements et services pour personnes âgées (Ehpad, Ssiad...)")],
                   16.1, "placss2024_a3", "publie", ref="PLACSS 2024 annexe 3, p. 14"))
    L.append(ligne([rob, au, ("ondam_ph", "Établissements et services pour personnes en situation de handicap")],
                   15.1, "placss2024_a3", "publie", ref="PLACSS 2024 annexe 3, p. 14"))
    reste_au = ROBSS_2024["autonomie"] - 16.1 - 15.1
    aeeh = round(PARTS_AUTONOMIE["aeeh_ajpa"] / 100 * ROBSS_2024["autonomie"], 3)
    gest = round(PARTS_AUTONOMIE["gestion"] / 100 * ROBSS_2024["autonomie"], 3)
    note_p = "part publiée (graphique 19 des Chiffres clés 2024, arrondie à 1 %) × charges de la branche"
    L.append(ligne([rob, au, ("aeeh_ajpa", "AEEH et allocation journalière du proche aidant")], aeeh,
                   "dss_chiffres_cles_2024", "derive", note=note_p))
    L.append(ligne([rob, au, ("gestion", "Charges de gestion et autres charges")], gest, "dss_chiffres_cles_2024",
                   "derive", note=note_p))
    L.append(ligne([rob, au, ("transferts", "Transferts (concours aux départements pour l'APA et la PCH, autres "
                                            "branches)")], reste_au - aeeh - gest, "placss2024", "derive",
                   note=f"reste des charges ; la part publiée est de {PARTS_AUTONOMIE['transferts']} %"))
    # FSV (compte détaillé, M€)
    fs = ("fsv", "Fonds de solidarité vieillesse (FSV)")
    f = FSV_2024
    pec = ("prises_en_charge", "Cotisations retraite prises en charge (périodes validées sans cotiser)")
    for k, lib in (("chomage", "au titre du chômage"), ("maladie", "au titre des arrêts maladie"),
                   ("formation", "au titre de la formation professionnelle"),
                   ("service_national", "au titre du service national")):
        L.append(ligne([rob, fs, pec, (k, lib)], f[k] / 1e3, "placss2024_a7", "tableau_image",
                       ref="PLACSS 2024 annexe 7, p. 68"))
    nv = f["prises_en_charge"] - sum(f[k] for k in ("chomage", "maladie", "formation", "service_national"))
    L.append(ligne([rob, fs, pec, ("non_ventile", "Non ventilé par la source")], nv / 1e3, "placss2024_a7", "derive",
                   note="total publié des prises en charge moins ses lignes publiées"))
    L.append(ligne([rob, fs, ("minimum_vieillesse", "Minimum vieillesse (Aspa et anciennes allocations)")],
                   f["minimum_vieillesse"] / 1e3, "placss2024_a7", "tableau_image", ref="PLACSS 2024 annexe 7, p. 68"))
    L.append(ligne([rob, fs, ("complementaires", "Versements aux régimes complémentaires (chômage)")],
                   f["complementaires"] / 1e3, "placss2024_a7", "tableau_image", ref="PLACSS 2024 annexe 7, p. 68"))
    L.append(ligne([rob, fs, ("gestion", "Frais d'assiette, de recouvrement et autres")], (f["far"] + f["autres"]) / 1e3,
                   "placss2024_a7", "tableau_image", ref="PLACSS 2024 annexe 7, p. 68"))
    d = f["charges"] - f["prises_en_charge"] - f["minimum_vieillesse"] - f["complementaires"] - f["far"] - f["autres"]
    if d:
        L.append(ligne([rob, fs, ("arrondis", "Arrondis de la source")], d / 1e3, "placss2024_a7", "derive",
                       note="charges nettes publiées moins somme des lignes publiées"))
    ecarts["robss/fsv"] = [{"source": "placss2024", "md": 20.5, "libelle": "dépenses du FSV, article 1 (arrondi)"}]
    # Neutralisation des transferts internes
    somme = sum(ROBSS_2024.values()) + f["charges"] / 1e3
    L.append(ligne([rob, ("transferts_internes", "Transferts entre branches et avec le FSV (déduits : comptés deux "
                                                  "fois ci-dessus)")], ROBSS_2024_TOTAL_Y_C_FSV - somme,
                   "placss2024", "derive",
                   note="total « toutes branches y compris FSV, hors transferts » (643,1 Md€, article 1) moins la "
                        "somme des branches et du FSV : cotisations retraite prises en charge par le FSV et la "
                        "branche famille, transferts AT-MP vers maladie..."))
    # Retraites complémentaires (compte consolidé, M€)
    co = ("complementaires", "Retraites complémentaires obligatoires (Agirc-Arrco et autres régimes)")
    c = COMPLEMENTAIRES
    aa = round(PART_AGIRC_ARRCO * c["retraite"])
    ref4 = "PLACSS 2024 annexe 4, tableaux 1 et 2"
    L.append(ligne([co, ("agirc_arrco", "Agirc-Arrco (salariés du privé) : pensions de retraite")], aa / 1e3,
                   "placss2024_a4", "derive",
                   note="87,2 % (poids publié de l'Agirc-Arrco dans les prestations) × 110 855 M€ de prestations de "
                        "retraite des régimes complémentaires", ref=ref4))
    L.append(ligne([co, ("autres_regimes", "Autres régimes complémentaires (Ircantec, RAFP, indépendants, "
                                           "professions libérales...) : pensions de retraite")],
                   (c["retraite"] - aa) / 1e3, "placss2024_a4", "derive", note="reste des prestations", ref=ref4))
    L.append(ligne([co, ("invalidite_deces", "Prestations d'invalidité, de décès et extralégales")],
                   c["autres_prestations"] / 1e3, "placss2024_a4", "tableau_image", ref=ref4))
    tr = ("transferts", "Transferts versés")
    for k, lib in (("rafp", "Fonds de capitalisation du RAFP"), ("adossement", "Prestations prises en charge pour "
                                                                                "adossement"),
                   ("autres_transferts", "Autres transferts")):
        L.append(ligne([co, tr, (k, lib)], c[k] / 1e3, "placss2024_a4", "tableau_image", ref=ref4))
    ac = ("autres_charges", "Autres charges")
    for k, lib in (("financieres", "Charges financières"), ("gestion", "Charges de gestion courante"),
                   ("techniques", "Autres charges techniques")):
        L.append(ligne([co, ac, (k, lib)], c[k] / 1e3, "placss2024_a4", "tableau_image", ref=ref4))
    for k, tot, parts in (("transferts", c["transferts"], ("rafp", "adossement", "autres_transferts")),
                          ("autres_charges", c["autres_charges"], ("financieres", "gestion", "techniques"))):
        d = tot - sum(c[p] for p in parts)
        if d:
            L.append(ligne([co, (k, dict([tr, ac])[k]), ("arrondis", "Arrondis de la source")], d / 1e3,
                           "placss2024_a4", "derive", note="total publié moins somme des lignes"))
    ecarts["complementaires/agirc_arrco"] = [
        {"source": "drees_cps", "md": None, "libelle": "prestations Agirc-Arrco des comptes de la protection sociale "
                                                       "(vieillesse et survie), voir la vue « cps »"}]
    # Unédic (M€)
    un = ("unedic", "Assurance chômage (Unédic)")
    u = lire_unedic()["2024"]
    for k, lib in (("allocations", "Allocations chômage et aides"),
                   ("france_travail", "Financement de France Travail et frais de recouvrement"),
                   ("retraites", "Cotisations de retraite complémentaire des chômeurs (versées à l'Agirc-Arrco)"),
                   ("autres", "Autres dépenses"), ("activite_partielle", "Activité partielle (chômage partiel)")):
        L.append(ligne([un, (k, lib)], u[k] / 1e3, "unedic", "publie", ref="colonne « Dépenses » de la source"))
    ecarts["unedic"] = [{"source": "placss2024_a4", "md": 45.2, "libelle": "dépenses 2024 (compte en trésorerie, "
                                                                          "provisoire)"}]
    # CADES (k€)
    ca = ("cades", "Remboursement de la dette sociale (CADES)")
    k = CADES_2024_KEUR
    L.append(ligne([ca, ("amortissement", "Dette sociale amortie dans l'année (résultat de la CADES)")],
                   k["resultat"] / 1e6, "placss2024_a7", "tableau_image", ref="PLACSS 2024 annexe 7, p. 34"))
    L.append(ligne([ca, ("interets", "Intérêts et frais de fonctionnement de la dette")], k["fonctionnement"] / 1e6,
                   "placss2024_a7", "tableau_image", ref="PLACSS 2024 annexe 7, p. 34"))
    L.append(ligne([ca, ("personnel", "Personnel")], k["personnel"] / 1e6, "placss2024_a7", "tableau_image",
                   ref="PLACSS 2024 annexe 7, p. 34"))
    ecarts["cades/amortissement"] = [{"source": "placss2024", "md": 16.0, "libelle": "dette amortie, article 2"}]
    return L, ecarts


def lignes_2025() -> tuple[list[dict], dict]:
    L: list[dict] = []
    rob = ("robss", "Régimes obligatoires de base (toutes branches) et Fonds de solidarité vieillesse")
    libs = {"maladie": "Assurance maladie (branche maladie)", "atmp": "Accidents du travail et maladies "
            "professionnelles (branche AT-MP)", "vieillesse": "Retraite de base (branche vieillesse, tous régimes de "
            "base)", "famille": "Famille (branche famille)", "autonomie": "Autonomie (branche autonomie, CNSA)"}
    for k, v in ROBSS_2025.items():
        L.append(ligne([rob, (k, libs[k])], v, "placss2025", "publie", ref="PLACSS 2025, article 1"))
    L.append(ligne([rob, ("fsv", "Fonds de solidarité vieillesse (FSV)")], FSV_2025, "placss2025", "publie",
                   ref="PLACSS 2025, article 1"))
    L.append(ligne([rob, ("transferts_internes", "Transferts entre branches et avec le FSV (déduits : comptés deux "
                                                  "fois ci-dessus)")],
                   ROBSS_2025_TOTAL_Y_C_FSV - sum(ROBSS_2025.values()) - FSV_2025, "placss2025", "derive",
                   note="total « y compris FSV, hors transferts » (666,0 Md€) moins la somme des branches et du FSV"))
    un = ("unedic", "Assurance chômage (Unédic)")
    u = lire_unedic()["2025"]
    for k, lib in (("allocations", "Allocations chômage et aides"),
                   ("france_travail", "Financement de France Travail et frais de recouvrement"),
                   ("retraites", "Cotisations de retraite complémentaire des chômeurs (versées à l'Agirc-Arrco)"),
                   ("autres", "Autres dépenses"), ("activite_partielle", "Activité partielle (chômage partiel)")):
        L.append(ligne([un, (k, lib)], u[k] / 1e3, "unedic", "publie", ref="colonne « Dépenses » de la source"))
    L.append(ligne([("cades", "Remboursement de la dette sociale (CADES)"),
                    ("amortissement", "Dette sociale amortie dans l'année")], 16.2, "placss2025", "publie",
                   ref="PLACSS 2025, article 2"))
    ecarts = {"robss/maladie": [{"source": "placss2025", "md": 265.4,
                                 "libelle": "dépenses constatées dans le champ de l'ONDAM (interbranches : maladie, "
                                            "AT-MP, autonomie), article 2"}],
              "cades": [{"source": "placss2025", "md": None, "libelle": "intérêts de la dette 2025 : compte de "
                                                                         "résultat non collecté"}]}
    return L, ecarts


def lire_unedic() -> dict:
    import csv
    p = chemin("unedic")
    if not p.exists():
        raise SystemExit(f"{p} absent : lancer la collecte de l'entrepôt (catalogue) ou `secu.py collecter`")
    out = {}
    with p.open(encoding="utf-8-sig") as fh:
        for r in csv.reader(fh, delimiter=";"):
            if not r or not r[0].strip().lstrip("﻿").isdigit():
                continue
            v = [float(x) if x not in ("", None) else 0.0 for x in r[1:]]
            out[r[0].strip().lstrip("﻿")] = {
                "total": v[4], "allocations": v[5], "retraites": v[6], "activite_partielle": v[7],
                "france_travail": v[8], "autres": v[9]}
    for an, u in out.items():
        if abs(u["allocations"] + u["retraites"] + u["activite_partielle"] + u["france_travail"] + u["autres"]
               - u["total"]) > 2:
            raise SystemExit(f"Unédic {an} : le détail des dépenses ne somme pas au total")
    return out


# --- Vue DREES : comptes de la protection sociale ------------------------------------------------------------------

REGIMES_DESTINATAIRES = {
    "Caisse nationale d’assurance maladie": "cnam", "Caisse nationale d’assurance vieillesse": "cnav",
    "Caisse nationale des allocations familiales": "cnaf", "Caisse nationale de solidarité pour l'autonomie": "cnsa",
    "Association générale des institutions de retraite des cadres et association des régimes de retraite "
    "complémentaire des salariés": "agirc_arrco", "UNEDIC et autres régimes": "unedic"}


def lignes_cps(annee: str = "2024") -> tuple[list[dict], dict]:
    import pandas as pd
    d = pd.read_parquet(chemin("drees_cps"))
    d = d[(d.annee == annee) & (~d.regime_nom.str.startswith("Total")) & (d.ps_niveau != "0")]
    if d.empty:
        raise SystemExit(f"DREES CPS : pas de données {annee}")
    lib = dict(zip(d.ps_code, d.ps_lib))
    L: list[dict] = []
    niv = ["secteur", "regime", "risque", "sous_risque", "groupe", "prestation"]
    for (si_code, si_nom, regime), g in d.groupby(["si_code", "si_nom", "regime_nom"]):
        vals = dict(zip(g.ps_code, g.val))
        codes = set(vals)

        def enfants(c):
            return [o for o in codes if o != c and o.startswith(c) and o[len(c)] in ".0123456789"
                    and not any(p != c and p != o and p.startswith(c) and o.startswith(p) and p in codes
                                for p in codes)]

        def chemin_code(c):
            ch = [p for p in sorted(codes, key=len) if c.startswith(p) and (p == c or c[len(p)] in ".0123456789")]
            return ch

        for c in codes:
            ens = enfants(c)
            base = [(si_code, si_nom), (regime, regime)]
            ch = [(p, lib[p]) for p in chemin_code(c)]
            if not ens:
                L.append({**_cps_ligne(base + ch, vals[c]), "mode": "publie"})
            else:
                reste = vals[c] - sum(vals[e] for e in ens)
                if abs(reste) >= 0.005:
                    L.append({**_cps_ligne(base + ch + [(c + "_nv", "Non ventilé par la source")], reste),
                              "mode": "derive", "note": "montant du poste moins la somme de ses sous-postes"})
    for r in L:
        r["source"] = "drees_cps"
    return L, {"niveaux": niv}


def _cps_ligne(ch, val_m):
    niv = ["secteur", "regime", "risque", "sous_risque", "groupe", "prestation", "detail"]
    r = {"eur": val_m * M}
    for n, (cle, l) in zip(niv, ch):
        r[n] = cle
        r[f"lib_{n}"] = l
    return r


# --- Arbre : construction (arbre.construire) puis décoration (source, traçabilité, écarts) -------------------------

def _niveaux(noms: list[str]) -> list[dict]:
    return [{"id": n, "cle": n, "libelle": f"lib_{n}"} for n in noms]


def decorer_et_ecrire(rows: list[dict], noms_niveaux: list[str], nom_racine: str, dossier: Path, entete: dict,
                      decoupe_apres: str | None, ecarts: dict, destinataires: dict) -> dict:
    racine = arbre.construire(rows, _niveaux(noms_niveaux), "eur")
    # Agrégats par chemin : traçabilité et sources
    acc: dict[tuple, dict] = {}
    for r in rows:
        if not r["eur"]:
            continue
        cles = []
        for n in [None] + noms_niveaux:
            if n is not None:
                v = r.get(n)
                if v in (None, ""):
                    continue
                cles.append(arbre._norm(v))
            a = acc.setdefault(tuple(cles), {"abs": 0.0, "direct": 0.0, "modes": {}, "sources": set()})
            a["abs"] += abs(r["eur"])
            if r["mode"] in ("publie", "tableau_image"):
                a["direct"] += abs(r["eur"])
            a["modes"][r["mode"]] = a["modes"].get(r["mode"], 0.0) + r["eur"]
            a["sources"].add(r["source"])
        feuille = acc[tuple(cles)]
        feuille.setdefault("feuille", r)
    stats = {"noeuds": 0, "feuilles": 0, "profondeur": 0, "fichiers": 0}
    dossier.mkdir(parents=True, exist_ok=True)
    for old in dossier.glob("*.json"):
        old.unlink()

    def md(e):
        return round(e / 1e9, 6)

    def noeud(n, ch, prof):
        stats["noeuds"] += 1
        stats["profondeur"] = max(stats["profondeur"], prof)
        nid = "/".join(ch) or "racine"
        a = acc[tuple(ch)]
        out = {"id": nid, "nom": n.get("nom", nom_racine), "niveau": n.get("niveau", "racine"), "md": md(n["eur"]),
               "sources": sorted(a["sources"]),
               "tracabilite_pct": round(100 * a["direct"] / a["abs"], 1) if a["abs"] else None}
        if not n["enfants"]:
            f = a.get("feuille") or {}
            out["mode"] = f.get("mode")
            if f.get("note"):
                out["note"] = f["note"]
            if f.get("ref"):
                out["ref"] = f["ref"]
        else:
            out["modes_md"] = {k: md(v) for k, v in sorted(a["modes"].items())}
        if nid in ecarts:
            out["ecarts"] = ecarts[nid]
        dest = destinataires.get(nid)
        if dest:
            out["destinataire"] = dest
        return out

    def serialiser(n, ch, prof, coupe):
        out = noeud(n, ch, prof)
        enfants = sorted(n["enfants"].values(), key=lambda e: -abs(e["eur"]))
        if not enfants:
            stats["feuilles"] += 1
            return out
        if coupe:
            fichier = f"{arbre._slug(ch)}.json"
            sous = {**entete, **out, "enfants": [serialiser(e, ch + [e["cle"]], prof + 1, False) for e in enfants]}
            dump(dossier / fichier, sous)
            stats["fichiers"] += 1
            return {**out, "fichier": f"secu/{dossier.name}/{fichier}", "nb_enfants": len(enfants)}
        out["enfants"] = [serialiser(e, ch + [e["cle"]], prof + 1, e["niveau"] == decoupe_apres) for e in enfants]
        return out

    doc = {**entete, **serialiser(racine, [], 0, False)}
    dump(dossier / "racine.json", doc)
    stats["fichiers"] += 1
    a = acc[()]
    stats["total_md"] = md(racine["eur"])
    stats["tracabilite_pct"] = round(100 * a["direct"] / a["abs"], 1)
    stats["modes_md"] = {k: md(v) for k, v in sorted(a["modes"].items())}
    return stats


DEST_ROBSS = {f"robss/{k}": v for k, v in DESTINATAIRES.items() if k in ROBSS_2024}
DEST_ROBSS.update({"complementaires/agirc_arrco": "agirc_arrco", "unedic": "unedic", "cades": "cades"})
# Destinataires « Sécurité sociale » de prelevements/affectation.json sans nœud propre dans les arbres secu/
# (constat M3 de docs/QUALITE.md) : dits ici, avec le motif, plutôt que laissés sans lien ni explication.
DEST_SANS_NOEUD = {
    "acoss": {"motif": "Caisse de recouvrement (Urssaf Caisse nationale) : la recette est répartie ensuite entre les "
                       "branches ; cette répartition par branche n'est pas publiée dans prelevements/affectation.json, "
                       "donc aucun nœud unique ne la reçoit.", "noeud_englobant": "robss"},
    "msa_maladie": {"motif": "Régime des non-salariés agricoles : sa branche maladie fait partie des régimes "
                             "obligatoires de base, que l'arbre présente par branche et non par régime.",
                    "noeud_englobant": "robss/maladie"},
    "msa_vieillesse": {"motif": "Régime des non-salariés agricoles : sa retraite de base fait partie des régimes "
                                "obligatoires de base, que l'arbre présente par branche et non par régime.",
                       "noeud_englobant": "robss/vieillesse"},
    "msa_rco": {"motif": "Retraite complémentaire obligatoire des non-salariés agricoles : aucun nœud propre ; son "
                         "rattachement à un nœud des régimes complémentaires n'est pas établi poste par poste.",
                "noeud_englobant": None},
    # Destinataires ajoutés à prelevements/affectation.json par l'affectation étendue (vague 3), sans nœud propre.
    "cnracl": {"motif": "Caisse de retraite des agents des collectivités locales et des hôpitaux : régime de base, que "
                        "l'arbre présente par branche (retraite de base, tous régimes) et non par régime.",
               "noeud_englobant": "robss/vieillesse"},
    "erafp": {"motif": "Retraite additionnelle de la fonction publique : régime complémentaire regroupé avec les autres "
                       "régimes complémentaires, sans nœud propre.",
              "noeud_englobant": "complementaires/autres_regimes"},
    "fsv": {"motif": "Le Fonds de solidarité vieillesse a un nœud dans l'arbre, mais le lien vers ce destinataire de "
                     "l'affectation n'y est pas encore posé (arbre produit avant l'affectation étendue).",
            "noeud_englobant": "robss/fsv"},
    "ircantec": {"motif": "Retraite complémentaire des agents publics contractuels : régime complémentaire regroupé "
                          "avec les autres régimes complémentaires, sans nœud propre.",
                 "noeud_englobant": "complementaires/autres_regimes"},
    "rci_independants": {"motif": "Retraite complémentaire des indépendants : régime complémentaire regroupé avec les "
                                  "autres régimes complémentaires, sans nœud propre.",
                         "noeud_englobant": "complementaires/autres_regimes"},
    "regime_local_am": {"motif": "Régime local d'assurance maladie d'Alsace-Moselle : régime complémentaire "
                                 "obligatoire de la branche maladie, que l'arbre ne présente pas à part.",
                        "noeud_englobant": "robss/maladie"},
}


def sources_de(cles) -> dict:
    return {k: {x: SOURCES[k][x] for x in ("titre", "url", "producteur", "millesime", "licence", "verdict")}
            for k in sorted(cles)}


def produire() -> dict:
    manquants = [s["fichier"] for s in SOURCES.values() if not (BRUT / s["fichier"]).exists()]
    if manquants:
        raise SystemExit(f"sources absentes de data/lake/secu/ : {manquants} ; lancer "
                         f"`python pipeline/secu.py collecter`")
    verif = verifier_documents()
    vues = {}
    methode = ("Montants des comptes des organismes (comptabilité générale, droits constatés) : tableau d'équilibre "
               "par branche des régimes obligatoires de base (PLACSS), sous-objectifs de l'ONDAM, comptes "
               "définitifs du FSV et de la CADES, compte consolidé des régimes complémentaires, comptes de "
               "l'Unédic. Chaque nœud : montant (Md€), sources, part du montant lue directement dans une source "
               "(tracabilite_pct) ; chaque feuille : mode de traçabilité. Les écarts avec d'autres sources sont "
               "listés dans `ecarts`, jamais lissés.")
    commun = ("La CADES rembourse la dette passée de la sécurité sociale. La branche vieillesse des régimes de base "
              "inclut les pensions des fonctionnaires (régimes spéciaux).")

    def officiel(total: float, texte: str) -> str:
        # Total du tableau d'équilibre voté (article 1), lu dans le texte par verifier_documents().
        return ("Ce total n'est pas un chiffre publié : il additionne les comptes de plusieurs organismes. Le chiffre "
                "officiel le plus proche, les dépenses des régimes obligatoires de base et du FSV, est de "
                f"{f'{total:.1f}'.replace('.', ',')} Md€ ({texte}, article 1).")

    # Avertissement propre à chaque vue : la vue 2025 n'a pas de régimes complémentaires, donc aucun des deux doubles
    # comptes cités pour 2024 (versements de l'Unédic et du FSV aux régimes complémentaires) ne s'y produit.
    avert_2024 = ("Les organismes se versent des fonds entre eux : les transferts entre branches et avec le FSV sont "
                  "déduits (nœud négatif) ; restent comptés deux fois les cotisations de retraite complémentaire des "
                  "chômeurs (Unédic vers Agirc-Arrco, 2,5 Md€ en 2024) et les versements du FSV aux régimes "
                  "complémentaires (0,2 Md€). " + commun + " " + officiel(ROBSS_2024_TOTAL_Y_C_FSV, "PLACSS 2024"))
    avert_2025 = ("Les organismes se versent des fonds entre eux : les transferts entre branches et avec le FSV sont "
                  "déduits (nœud négatif). " + commun + " Les régimes complémentaires (Agirc-Arrco et autres) ne "
                  "figurent pas dans cette vue, leurs comptes 2025 n'étant pas collectés : ce total ne se compare pas "
                  "à celui de 2024. " + officiel(ROBSS_2025_TOTAL_Y_C_FSV, "PLACSS 2025"))
    for nom, (rows, ecarts), mill, dossier, src_txt, avert in (
            ("arbre", lignes_2024(), "Exécution 2024", SORTIE / "arbre",
             "PLACSS 2024 (texte, annexes 1, 3, 4, 7), DSS Chiffres clés 2024, Unédic (data.gouv.fr)", avert_2024),
            ("arbre_2025", lignes_2025(), "Exécution 2025", SORTIE / "arbre_2025",
             "PLACSS 2025 (texte), Unédic (data.gouv.fr)", avert_2025)):
        cles = {r["source"] for r in rows} | {e["source"] for v in ecarts.values() for e in v}
        entete = {"millesime": mill, "source": src_txt, "unite": UNITE}
        dest = DEST_ROBSS if nom == "arbre" else {k: v for k, v in DEST_ROBSS.items() if k != "complementaires/agirc_arrco"}
        stats = decorer_et_ecrire(rows, NIVEAUX, "Sécurité sociale et régimes sociaux : dépenses des organismes",
                                  dossier, {**entete, "methode": methode, "avertissement": avert,
                                            "sources_detail": sources_de(cles)},
                                  None, ecarts, dest)
        vues[nom] = {"millesime": mill, "fichier": f"secu/{nom}/racine.json", **stats}
    rows, _ = lignes_cps("2024")
    entete = {"millesime": "2024", "source": SOURCES["drees_cps"]["titre"], "unite": "milliards d'euros (Md€), "
              "prestations de protection sociale"}
    dest_cps = {}
    stats = decorer_et_ecrire(rows, ["secteur", "regime", "risque", "sous_risque", "groupe", "prestation", "detail"],
                              "Prestations de protection sociale (tous financeurs)", SORTIE / "cps",
                              {**entete, "methode": "Comptes de la protection sociale (DREES, base comptabilité "
                                                    "nationale) : prestations versées en 2024, par secteur, régime, "
                                                    "risque et prestation. Vue séparée : jamais additionnée aux "
                                                    "comptes des organismes.",
                               "sources_detail": sources_de({"drees_cps"})},
                              "regime", {}, dest_cps)
    _destinataires_cps(SORTIE / "cps")
    vues["cps"] = {"millesime": "2024", "fichier": "secu/cps/racine.json", **stats}
    index = {
        "millesime": "Exécution 2024 (vue par défaut), exécution 2025, protection sociale 2024",
        "source": "PLACSS 2024 et 2025, DSS, Unédic, DREES (détail dans `sources`)",
        "unite": UNITE,
        "vue_defaut": "arbre",
        "vues": vues,
        "liens_affectation": {
            "fichier": "prelevements/affectation.json",
            "regle": "un nœud portant `destinataire` = X reçoit les prélèvements dont la ventilation désigne le "
                     "destinataire X de prelevements/affectation.json",
            "noeuds": {v: k for k, v in DEST_ROBSS.items()},
            "sans_noeud": DEST_SANS_NOEUD},
        "verification_documents": verif,
        "sources": sources_de(SOURCES),
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "genere_le": date_sources(),
    }
    dump(SORTIE / "index.json", index)
    for k, v in vues.items():
        print(f"secu/{k} : {v['total_md']:.1f} Md€, {v['noeuds']} nœuds, profondeur {v['profondeur']}, "
              f"traçabilité directe {v['tracabilite_pct']} %, {v['fichiers']} fichier(s)")
    return index


def _destinataires_cps(dossier: Path) -> None:
    """Ajoute `destinataire` aux nœuds régime de la vue DREES (racine et sous-arbres)."""
    for p in dossier.glob("*.json"):
        doc = json.loads(p.read_text(encoding="utf-8"))

        def marquer(n):
            if n.get("niveau") == "regime" and n["nom"] in REGIMES_DESTINATAIRES:
                n["destinataire"] = REGIMES_DESTINATAIRES[n["nom"]]
            for e in n.get("enfants", []):
                marquer(e)
        marquer(doc)
        dump(p, doc)


# --- Collecte (réseau) ---------------------------------------------------------------------------------------------

def telecharger(url: str, dest: Path, essais: int = 4, budget: float = 600.0) -> str:
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    derniere = ""
    for i in range(essais):
        try:
            r = requests.get(url, timeout=(15, budget), headers={"User-Agent": "ou-vont-mes-impots/pipeline"})
            if r.status_code in (401, 403, 429, 451):
                return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
            r.raise_for_status()
            if dest.suffix == ".pdf" and not r.content.startswith(b"%PDF"):
                return "page de refus ou HTML renvoyé à la place du PDF : aucun contournement"
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
        elif cle in ("unedic", "drees_cps"):
            etat[cle] = {"statut": "absent : collecté par collecte/collecte.py (catalogue)"}
        else:
            etat[cle] = {"statut": telecharger(s["url"], dest),
                         "collecte_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        print(f"{cle}: {etat[cle]['statut']}")
    for cle, pages in (("placss2024_a3", MOTIFS_A3_OCR), ("placss2024_a4", MOTIFS_A4_OCR),
                       ("placss2024_a7", MOTIFS_A7_OCR)):
        for p in pages:
            if ocr_page(cle, p + 1) is None:
                print(f"OCR impossible ({cle} p. {p + 1}) : tesseract ou pdftoppm absent")
    return etat


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
