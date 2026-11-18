"""Union européenne, dans les deux sens : ce que la France verse au budget de l'UE et ce qui en revient, nommé.

Entrées : entrepôt brut data/lake/ (non versionné) et site/data/arbre/racine.json (branche « Prelevements sur
recettes/Union européenne » de l'arbre État, exécution 2024).
Sorties (chaque fichier porte `millesime` et `source`) :
  site/data/ue/contribution.json              ce qui part : PSR-UE, réparti selon l'usage du budget de l'UE
                                              (rubriques et pôles du CFP 2021-2027), engagements 2024 par programme (FTS)
  site/data/ue/retours.json                   ce qui revient par année et par rubrique, solde net de la France
  site/data/ue/beneficiaires/index.json       bénéficiaires nommés : couverture, totaux par source, année, région
  site/data/ue/beneficiaires/<dep>.json       bénéficiaires nommés d'un département (personnes morales seulement)

Sources de bénéficiaires :
  - Kohesio (Commission, DG REGIO), exports officiels France 2014-2020 et 2021-2027 : FEDER, FSE, FSE+, IEJ, FTJ ;
    montants = budget UE programmé par opération, rattaché à l'année de début de l'opération ;
  - Financial Transparency System (FTS, Commission), jeux annuels 2023 à 2025 : gestion directe et indirecte,
    montant contracté par bénéficiaire, SIREN lu dans le numéro de TVA intracommunautaire (FRcc + SIREN) ;
  - Horizon Europe, participants français (MESR, jeu fr-esr-horizon-projects-entities, d'après eCorda/CORDIS) :
    SIREN fourni par la source, subvention signée rattachée à l'année de l'appel. Horizon figure aussi dans le FTS
    (programme 1.0.11) : les deux vues ne s'additionnent pas (le total nommé additionne Kohesio et FTS seulement).

Règle personnes physiques (bloquante) : seules les personnes morales (catégorie juridique 2xxx à 9xxx, vérifiée via
l'API Recherche d'entreprises) sont nommées, sous leur dénomination SIRENE. Entrepreneurs individuels (1000), lignes
FTS « Private Persons », noms Kohesio non rapprochés d'un SIREN : agrégés, jamais nommés. Les bénéficiaires de la PAC
(FEAGA, FEADER ; programmes FTS 3.1.x) ne sont pas collectés : seul leur montant global est publié.

Commandes :
  python pipeline/ue.py collecter                 # réseau : sources manquantes (s'arrête sur un refus, sans contourner)
  python pipeline/ue.py resoudre [--budget 480]   # réseau, reprenable : noms Kohesio -> SIREN, SIREN -> catégorie
  python pipeline/ue.py produire                  # sans réseau : écrit site/data/ue/
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import sirene

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "europe" / "ue_documents"             # documents publics sans données personnelles
RESTREINT = LAKE / "_restreint" / "europe" / "ue"   # listes de bénéficiaires (peuvent contenir des personnes physiques)
CACHE = LAKE / "_cache" / "ue"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "ue"
DOSSIER_DEP = SORTIE / "beneficiaires"
KOHESIO_INSTANTANE = "2026-09-24"
ANNEES_FTS = (2023, 2024, 2025)
SEUIL_NOMS_EUR = 50_000  # noms Kohesio rapprochés par l'API (par ordre de montant décroissant) ; en dessous : agrégés
API = "https://recherche-entreprises.api.gouv.fr/search"

# --- Sources (verdict de la recherche publique, licence, date) ---------------------------------------------------

SOURCES = {
    "kohesio_2021_2027": {
        "chemin": RESTREINT / "kohesio" / f"FR-pp21-27-{KOHESIO_INSTANTANE.replace('-', '')}.csv",
        "url": f"https://kohesio.ec.europa.eu/api/data/object?id=data/projects-2021-2027/{KOHESIO_INSTANTANE}/"
               f"FR-pp21-27-{KOHESIO_INSTANTANE.replace('-', '')}.csv",
        "titre": f"Kohesio, export officiel France 2021-2027 (instantané du {KOHESIO_INSTANTANE})",
        "producteur": "Commission européenne (DG REGIO)", "licence": "réutilisation autorisée (décision 2011/833/UE)",
        "verdict": "réutilisable tel quel (liste d'opérations ; SIREN absent, rapproché par le nom)"},
    "kohesio_2014_2020": {
        "chemin": RESTREINT / "kohesio" / f"FR-pp14-20-{KOHESIO_INSTANTANE.replace('-', '')}.csv",
        "url": f"https://kohesio.ec.europa.eu/api/data/object?id=data/projects-2014-2020/{KOHESIO_INSTANTANE}/"
               f"FR-pp14-20-{KOHESIO_INSTANTANE.replace('-', '')}.csv",
        "titre": f"Kohesio, export officiel France 2014-2020 (instantané du {KOHESIO_INSTANTANE})",
        "producteur": "Commission européenne (DG REGIO)", "licence": "réutilisation autorisée (décision 2011/833/UE)",
        "verdict": "réutilisable tel quel (liste d'opérations ; SIREN absent, rapproché par le nom)"},
    **{f"fts_{a}": {
        "chemin": RESTREINT / "fts" / f"{a}_FTS_dataset_en.xlsx",
        "url": f"https://ec.europa.eu/budget/financial-transparency-system/download/{a}_FTS_dataset_en.xlsx",
        "titre": f"Financial Transparency System, jeu annuel {a} (engagements de l'année)",
        "producteur": "Commission européenne (DG BUDG)", "licence": "réutilisation autorisée (décision 2011/833/UE)",
        "verdict": "réutilisable tel quel (gestion directe et indirecte ; SIREN lu dans le n° de TVA)"}
        for a in ANNEES_FTS},
    "horizon_mesr": {
        "chemin": LAKE / "europe" / "esr__fr-esr-horizon-projects-entities.parquet",
        "url": "https://data.enseignementsup-recherche.gouv.fr/explore/dataset/fr-esr-horizon-projects-entities/",
        "titre": "Horizon Europe, participations françaises aux projets lauréats (MESR, d'après eCorda)",
        "producteur": "Ministère de l'Enseignement supérieur et de la Recherche", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (SIREN et département fournis ; préféré au CSV CORDIS qui n'a que la TVA)"},
    "jaune_ue_plf2025": {
        "chemin": BRUT / "jaune_relations_financieres_ue_plf2025.pdf",
        "url": "https://www2.assemblee-nationale.fr/static/17/Annexes-DL/PLF2025-Jaunes/"
               "13-Jaune%20relations_financieres_UE.pdf",
        "titre": "Annexe au PLF 2025 « Relations financières avec l'Union européenne » (données Commission 2021-2023, "
                 "CFP 2021-2027 après révision de 2024)",
        "producteur": "Direction du budget", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (tableaux saisis ici et revérifiés contre le texte du PDF)"},
    "senat_np_plf2026": {
        "chemin": BRUT / "senat_np_affaires_europeennes_plf2026.pdf",
        "url": "https://www.senat.fr/fileadmin/cru-1762483659/Commissions/Finances/2025-2026/PLF_2026/NP/"
               "Affaires_europeennes_NP_PLF_2026.pdf",
        "titre": "Sénat, commission des finances, note de présentation « Affaires européennes » PLF 2026 (cite l'annexe "
                 "« Relations financières avec l'UE » du PLF 2026 : données 2024)",
        "producteur": "Sénat", "licence": "réutilisation libre avec mention (documents parlementaires)",
        "verdict": "réutilisable tel quel (chiffres 2024 de l'annexe PLF 2026, introuvable en ligne)"},
    "senat_np_plf2027": {
        "chemin": BRUT / "senat_np_affaires_europeennes_plf2027.pdf",
        "url": "https://www.senat.fr/fileadmin/cru-1792598966/Commissions/Finances/2026-2027/PLF_2027/NP/"
               "NP_Affaires_europeennes_PLF_2027.pdf",
        "titre": "Sénat, commission des finances, note de présentation « Affaires européennes » PLF 2027 (données 2025)",
        "producteur": "Sénat", "licence": "réutilisation libre avec mention (documents parlementaires)",
        "verdict": "réutilisable tel quel"},
    "geo_departements": {
        "chemin": CACHE / "departements.json", "url": "https://geo.api.gouv.fr/departements?fields=nom,code,codeRegion",
        "titre": "API Découpage administratif, départements", "producteur": "Etalab", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel"},
    "geo_regions": {
        "chemin": CACHE / "regions.json", "url": "https://geo.api.gouv.fr/regions",
        "titre": "API Découpage administratif, régions", "producteur": "Etalab", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel"},
}

INACCESSIBLES = [
    {"source": "Commission européenne, « EU spending and revenue 2000-2024 » (xlsx, soldes budgétaires opérationnels "
               "par État membre et dépenses par rubrique)",
     "url": "https://commission.europa.eu/document/download/45d0623a-529e-44d2-aae4-2ca9bac87ec3_en"
            "?filename=eu_budget_spending_and_revenue_2000-2023.xlsx",
     "constat": "HTTP 429 (page « Sorry ») au téléchargement, deux essais espacés le 17/11/2026 ; non contourné",
     "effet": "exécution 2024 du budget de l'UE par rubrique non publiée ; usage réparti selon les plafonds du CFP"},
    {"source": "Annexe au PLF 2026 « Relations financières avec l'Union européenne » (PDF)",
     "url": "https://www2.assemblee-nationale.fr/static/17/Annexes-DL/PLF2026-Jaunes/13-Jaune%20relations_financieres_UE.pdf",
     "constat": "HTTP 404 à l'adresse de l'annexe 2025 transposée ; ses chiffres 2024 sont repris de la note du Sénat",
     "effet": "retours 2024 publiés pour trois rubriques seulement (PAC, compétitivité, cohésion) et le total"},
    {"source": "Kohesio, API de recherche du site (kohesio.ec.europa.eu/api/facet/...)",
     "url": "https://kohesio.ec.europa.eu/api/facet/eu/search/projects",
     "constat": "HTTP 404 ; l'équipe Kohesio réserve cette API au site et renvoie vers les exports officiels, utilisés ici",
     "effet": "aucun"},
]

RECHERCHE_PUBLIQUE = [
    {"trouvaille": "exports officiels Kohesio par pays (kohesio.ec.europa.eu/api/data/object?id=...)",
     "verdict": "réutilisable tel quel", "licence": "décision 2011/833/UE", "date": f"instantané {KOHESIO_INSTANTANE}"},
    {"trouvaille": "FTS, jeux annuels xlsx (data.europa.eu, jeu « fts »)", "verdict": "réutilisable tel quel",
     "licence": "décision 2011/833/UE", "date": "fichiers 2023-2025 modifiés le 01/10/2026"},
    {"trouvaille": "MESR fr-esr-horizon-projects-entities (SIREN des participants français)",
     "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "date": "collecté le 15/11/2026"},
    {"trouvaille": "CORDIS cordis-HORIZONprojects-csv.zip", "verdict": "inspiration seulement (doublon du jeu MESR, "
     "sans SIREN)", "licence": "décision 2011/833/UE", "date": "fichier du 05/11/2026"},
    {"trouvaille": "github.com/rouages-de-la-france/rouages.fr (scripts/europe-emettre.ts, Kohesio 2014-2020 par commune)",
     "verdict": "inspiration seulement (pas de bénéficiaires nommés, TypeScript)", "licence": "non vérifiée",
     "date": "commit d'octobre 2026"},
    {"trouvaille": "github.com/clementlefevre/Kohesio (scripts/download_kohesio_projects.py)",
     "verdict": "inspiration seulement (motif d'URL des exports repris)", "licence": "MIT", "date": "mis à jour le 14/05/2026"},
    {"trouvaille": "github.com/c-mongan/ireland-mcp (docs/kohesio-exports.md)",
     "verdict": "inspiration seulement (confirmation des listes d'exports datées)", "licence": "non vérifiée",
     "date": "vérifié le 08/10/2026"},
    {"trouvaille": "github.com/pudo-attic/dpkg-eu-fts", "verdict": "inspiration seulement (archivé, ancien format FTS)",
     "licence": "non vérifiée", "date": "archivé"},
]

# --- Paramètres saisis depuis les PDF officiels (revérifiés à chaque production) ----------------------------------

# CFP 2021-2027 après révision du 29/02/2024, M€ courants, jaune PLF 2025 tableau « Comparaison du CFP adopté pour
# 2021-2027 au CFP 2014-2020 » (colonne « CFP 2021-2027 post révision »). Pôles = feuilles ; marges exclues.
CFP = [
    ("1", "Marché unique, innovation et numérique", 149_939, [
        ("1", "Recherche et innovation (dont Horizon Europe)", 93_406),
        ("2", "Investissements stratégiques européens (InvestEU, MIE)", 33_072),
        ("3", "Marché unique", 6_623), ("4", "Espace", 15_195)]),
    ("2", "Cohésion, résilience et valeurs", 429_825, [
        ("5", "Développement et cohésion à l'échelle régionale (FEDER, Fonds de cohésion)", 276_279),
        ("6", "Relance et résilience", 20_985),
        ("7", "Capital humain, cohésion sociale et valeurs (FSE+, Erasmus+)", 131_125)]),
    ("3", "Ressources naturelles et environnement", 400_302, [
        ("8", "Politique agricole et maritime (PAC, pêche)", 385_099),
        ("9", "Environnement et action pour le climat (LIFE, FTJ)", 14_457)]),
    ("4", "Migration et gestion des frontières", 28_333, [("10", "Migration", 12_244),
                                                         ("11", "Gestion des frontières", 15_213)]),
    ("5", "Sécurité et défense", 16_425, [("12", "Sécurité", 5_060), ("13", "Défense", 10_615)]),
    ("6", "Voisinage et le monde", 113_697, [("14", "Action extérieure", 97_850), ("15", "Aide de préadhésion", 14_558)]),
    ("7", "Administration publique européenne", 82_474, [
        ("16", "Écoles européennes et pensions", 19_481),
        ("17", "Dépenses administratives des institutions", 62_993)]),
]
CFP_TOTAL = 1_220_995
NGEU = {"1": 11_486, "2": 776_500, "3": 18_939}  # M€ courants, jaune PLF 2025, tableau « CFP 2021-2027 et plan de relance »
NGEU_TOTAL = 806_925

# Retours en France par rubrique, M€ (Commission, rapports financiers ; jaune PLF 2025)
RETOURS_RUBRIQUES = {
    "1": ("Compétitivité (marché unique, innovation, numérique)", {2021: 2626, 2022: 2958, 2023: 2711}),
    "2a": ("Cohésion", {2021: 2344, 2022: 2350, 2023: 2281}),
    "2b": ("Politiques internes (résilience et valeurs)", {2021: 452, 2022: 605, 2023: 622}),
    "3": ("Agriculture et pêche (PAC)", {2021: 9419, 2022: 9499, 2023: 9540}),
    "4": ("Frontières et migrations", {2021: 162, 2022: 208, 2023: 109}),
    "5": ("Sécurité et défense", {2021: 76, 2022: 143, 2023: 142}),
    "6": ("Action extérieure", {2021: 43, 2022: 128, 2023: 71}),
    "7": ("Dépenses administratives", {2021: 456, 2022: 508, 2023: 518}),
    "is": ("Instruments spéciaux", {2021: 151, 2022: 493, 2023: 504}),
}
RETOURS_TOTAL = {2021: 15_729, 2022: 16_892, 2023: 16_498, 2024: 16_456, 2025: 16_400}
RETOURS_2024 = {"3": 9_600, "1": 3_400, "2a": 1_400}      # Sénat NP PLF 2026 (annexe PLF 2026)
RETOURS_2025 = {"3": 9_500}                               # Sénat NP PLF 2027
SOLDE_COMPTABLE = {2021: (-12_380, -0.49), 2022: (-9_584, -0.36), 2023: (-9_333, -0.33), 2024: (-7_900, -0.27),
                   2025: (-9_500, -0.31)}
SOLDE_OPERATIONNEL = {2023: (-6_400, -0.22)}
PSR_VOTE = {2018: 19_912, 2019: 21_443, 2020: 21_480, 2021: 27_200, 2022: 26_359, 2023: 24_994, 2024: 21_610,
            2025: 23_098, 2026: 28_440}
PSR_EXECUTE = {2018: 20_645, 2019: 21_025, 2020: 23_691, 2021: 26_368, 2022: 25_230, 2023: 23_873, 2024: 22_276,
               2025: 22_961, 2026: 28_118}

MOTIFS = {
    "jaune_ue_plf2025": [
        "1. Recherche et innovation 69 576 93 406", "2. Investissements stratégiques européens 31 301 33 072",
        "3. Marché unique 4 989 6 623", "4. Espace 11 286 15 195",
        "5. Développement et cohésion à l'échelle régionale 269 073 276 279", "6. Relance et résilience 5 975 20 985",
        "7. Capital humain, cohésion sociale et valeurs 112 509 131 125", "8. Politique agricole et maritime 387 812 385 099",
        "9. Environnement et action pour le climat 3 453 14 457", "10. Migration 7 460 12 244",
        "11. Gestion des frontières 5 579 15 213", "12. Sécurité 3 490 5 060", "13. Défense 590 10 615",
        "14. Action extérieure 85 408 97 850", "15. Aide de préadhésion 12 955 14 558",
        "Ecoles européennes et pensions 13 802 19 481", "Dépenses administratives des institutions 55 782 62 993",
        "1. Marché unique, innovation et digital 114 511 149 939", "2. Cohésion, résilience et valeurs 386 065 429 825",
        "3. Ressources naturelles et environnement 391 836 400 302", "4. Migration et gestion des frontières 3 607 28 333",
        "5. Sécurité et défense 4 080 16 425", "6. Voisinage et le monde 94 365 113 697",
        "7. Administration publique européenne 69 584 82 474", "TOTAL 1 064 049 1 220 995",
        "1. Marché unique, innovation et digital 114 511 151 318 11 486 162 804",
        "2. Cohésion, résilience et valeurs 386 065 429 408 776 500 1 205 908",
        "3. Ressources naturelles et environnement 391 836 400 997 18 939 419 936",
        "TOTAL 1 064 049 1 215 871 806 925 2 022 796",
        "1. Com pétitivité 2 626 2 958 2 711", "2.a. Cohésion 2 344 2 350 2 281",
        "2.b. Politiques internes 452 605 622", "3. Agriculture 9 419 9 499 9 540",
        "4. Frontières et m igrations 162 208 109", "5. Sécurité et défense 76 143 142",
        "6. Action extérieure 43 128 71", "7. Dépenses adm inistratives 456 508 518",
        "Instrum ents spéciaux 151 493 504", "Total 15 729 16 892 16 498",
        "France - 12 380 -0,49% - 9 584 -0,36% - 9 333 -0,33%",
        "– 6,4 Md€ selon la méthode de la Commission (-0,22 % du RNB)",
    ],
    "senat_np_plf2026": [
        "Crédits votés en 19 912 21 443 21 480 27 200 26 359 24 994 21 610 23 098 PLF",
        "Crédits exécutés 20 645 21 025 23 691 26 368 25 230 23 873 22 276 22 972*",
        "les dépenses réalisées en France s’élevaient à 16,456 milliards d’euros",
        "soit un montant de 9,6 milliards", "(respectivement 3,4 milliards d’euros et 1,4 milliard d’euros)",
        "à - 7,9 milliards d’euros (- 9,3 milliards d’euros en 2023)", "(- 0,27 % en 2024)",
    ],
    "senat_np_plf2027": [
        "Crédits votés en 21 443 21 480 27 200 26 359 24 994 21 610 23 098 28 440 PLF",
        "Crédits exécutés 21 025 23 691 26 368 25 230 23 873 22 276 22 961 28 118",
        "les dépenses réalisées en France s’élevaient à 16,4 milliards", "soit un montant de 9,5 milliards",
        "– 9,5 milliards d’euros selon la méthode comptable, contre – 7,9 milliards d’euros en 2024",
        "(– 0,31 % en 2025)", "28,1 milliards d’euros en 2021 à 24,3 milliards d’euros en 2024",
    ],
}

# --- Utilitaires ----------------------------------------------------------------------------------------------


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def espaces(s: str) -> str:
    s = unicodedata.normalize("NFC", s).replace(" ", " ").replace(" ", " ").replace("'", "’")
    return re.sub(r"\s+", " ", s).strip()


def md(m_eur: float) -> float:
    """Millions -> milliards d'euros."""
    return round(m_eur / 1000, 6)


def sans_accent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Collecte ---------------------------------------------------------------------------------------------------


def telecharger(url: str, dest: Path, budget: float = 900.0) -> str:
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    derniere = ""
    for i in range(3):
        try:
            r = requests.get(url, timeout=(20, budget), headers=sirene.HEADERS)
            if r.status_code in (401, 403, 429, 451):
                return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
            r.raise_for_status()
            if r.content[:200].lstrip().lower().startswith((b"<html", b"<!doctype")) and not url.endswith("html"):
                return "page HTML renvoyée à la place du fichier : aucun contournement"
            from fetch import octets_annonces, remplacer_si_valide  # controle collecte/integrite.py
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(r.content)
            remplacer_si_valide(tmp, dest, octets_attendus=octets_annonces(r))  # invalide : dest conserve
            return "ok"
        except Exception as e:  # reprise réseau
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(3 * (i + 1))
    return f"échec après 3 essais : {derniere}"


def collecter() -> dict:
    etat = {}
    for cle, s in SOURCES.items():
        dest = s["chemin"]
        if dest.exists() and dest.stat().st_size > 0:
            etat[cle] = {"statut": "présent", "octets": dest.stat().st_size}
            continue
        if cle == "horizon_mesr":
            etat[cle] = {"statut": "absent : collecté par collecte/collecte.py (catalogue)"}
            continue
        res = telecharger(s["url"], dest)
        etat[cle] = {"statut": res, "collecte_le": maintenant()}
        print(f"{cle}: {res}", file=sys.stderr)
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "collecte.json").write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    return etat


# --- Vérification des paramètres saisis ----------------------------------------------------------------------


def texte_pdf(chemin: Path) -> str | None:
    if not chemin.exists():
        return None
    cache = CACHE / (chemin.stem + ".txt")
    if not (cache.exists() and cache.stat().st_mtime >= chemin.stat().st_mtime):
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(["pdftotext", "-layout", str(chemin), str(cache)], check=True)
    return cache.read_text(encoding="utf-8")


def verifier_documents() -> dict:
    out = {}
    for cle, motifs in MOTIFS.items():
        t = texte_pdf(SOURCES[cle]["chemin"])
        if t is None:
            out[cle] = {"statut": "document absent de l'entrepôt : valeurs saisies non revérifiées", "motifs": len(motifs)}
            continue
        t = espaces(t)
        manquants = [m for m in motifs if espaces(m) not in t]
        if manquants:
            raise SystemExit(f"{cle} : paramètres saisis introuvables dans le PDF (document changé ?) : {manquants}")
        out[cle] = {"statut": "vérifié", "motifs": len(motifs)}
    return out


# --- Géographie -------------------------------------------------------------------------------------------------


def geo() -> tuple[dict, dict]:
    deps = {d["code"]: d for d in json.loads(SOURCES["geo_departements"]["chemin"].read_text(encoding="utf-8"))}
    regs = {r["code"]: r["nom"] for r in json.loads(SOURCES["geo_regions"]["chemin"].read_text(encoding="utf-8"))}
    return deps, regs


def dep_insee(code_commune: str | None) -> str | None:
    """Département d'un code commune INSEE (2A/2B, outre-mer sur 3 caractères)."""
    if not code_commune:
        return None
    c = code_commune.strip().upper()
    if len(c) != 5:
        return None
    return c[:3] if c.startswith("97") else c[:2]


def dep_postal(cp: str | None) -> str | None:
    if not cp:
        return None
    cp = re.sub(r"\D", "", str(cp))
    if len(cp) != 5:
        return None
    if cp.startswith("97") or cp.startswith("98"):
        return cp[:3]
    if cp.startswith("20"):
        return "2A" if int(cp) < 20200 else "2B"
    return cp[:2]


# --- Kohesio ------------------------------------------------------------------------------------------------------

FONDS = {"ERDF": "FEDER", "ESF": "FSE", "ESF+": "FSE+", "YEI": "IEJ", "JTF": "FTJ", "CF": "Fonds de cohésion",
         "ERDF|ESF": "FEDER et FSE"}


def fonds_kohesio(code: str | None, programme: str | None) -> str:
    if code:
        return FONDS.get(code, code)
    p = programme or ""
    if "YEI" in p:
        return "FSE et IEJ"
    if "ERDF" in p and "ESF" in p:
        return "FEDER et FSE"
    if "ESF" in p:
        return "FSE"
    return "non précisé"


def lire_kohesio() -> list[dict]:
    """Opérations Kohesio France (deux périodes) : une ligne par opération, montant UE programmé."""
    import duckdb
    lignes = []
    nuts3_dep: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for cle, periode in (("kohesio_2014_2020", "2014-2020"), ("kohesio_2021_2027", "2021-2027")):
        f = SOURCES[cle]["chemin"]
        rel = duckdb.sql(f"""select Beneficiary_Name n, Beneficiary_Local_Identifier li, Project_EU_Budget eu,
                 Operation_Start_Date d, Fund_Code fc, Programme_Name pn, LAU_IDs lau, NUTS3_Code n3
                 from read_csv('{f}', all_varchar=true, header=true)""")
        for n, li, eu, d, fc, pn, lau, n3 in rel.fetchall():
            try:
                v = float(eu) if eu not in (None, "") else 0.0
            except ValueError:
                v = 0.0
            dep = None
            if lau:
                premier = re.split(r"[,;|]", lau)[0].strip()
                dep = dep_insee(premier.split("_")[-1])
            if dep and n3:
                nuts3_dep[n3][dep] += 1
            annee = int(d[-4:]) if d and re.match(r"^\d{2}/\d{2}/\d{4}$", d) else None
            lignes.append({"source": cle, "periode": periode, "nom": (n or "").strip(), "li": (li or "").strip(),
                           "eur": v, "annee": annee, "fonds": fonds_kohesio(fc, pn), "dep": dep, "nuts3": n3})
    # NUTS 3 -> département, déduit des opérations qui portent les deux (majorité)
    corresp = {n3: max(c.items(), key=lambda x: x[1])[0] for n3, c in nuts3_dep.items()}
    for l in lignes:
        if not l["dep"] and l["nuts3"]:
            l["dep"] = corresp.get(l["nuts3"])
    return lignes


MOTS_VIDES = {"DE", "DU", "DES", "LA", "LE", "LES", "L", "D", "ET", "EN", "A", "AU", "AUX", "SUR", "POUR", "SAS", "SASU",
              "SARL", "SA", "EURL", "SCOP", "SCA", "SNC", "GIE", "SEM", "SPL", "SCIC", "SCEA", "EARL", "GAEC", "SCI",
              "STE", "SOCIETE", "ETS", "ETABLISSEMENTS", "CEDEX"}
EQUIVALENCES = {"VILLE": "COMMUNE", "MAIRIE": "COMMUNE", "ASSO": "ASSOCIATION", "ST": "SAINT"}


def jetons(nom: str) -> frozenset:
    s = sans_accent(nom or "").upper()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\bCONSEIL REGIONAL\b", "REGION", s)
    s = re.sub(r"\bCONSEIL DEPARTEMENTAL\b", "DEPARTEMENT", s)
    out = set()
    for t in s.split():
        t = EQUIVALENCES.get(t, t)
        if t and t not in MOTS_VIDES:
            out.add(t)
    return frozenset(out)


def score_nom(nom: str, candidat: dict) -> float:
    """Ressemblance entre le nom publié et un résultat de l'API (0 à 1) ; 1 = même nom ou même sigle."""
    a = jetons(nom)
    if not a:
        return 0.0
    meilleur = 0.0
    for champ in ("nom_raison_sociale", "nom_complet", "sigle"):
        b = jetons(candidat.get(champ) or "")
        if not b:
            continue
        if a == b:
            return 1.0
        inter = len(a & b)
        jacc = inter / len(a | b)
        if (a <= b or b <= a) and min(len(a), len(b)) >= 3 and abs(len(a) - len(b)) <= 1:
            jacc = max(jacc, 0.8)
        meilleur = max(meilleur, jacc)
    return meilleur


SEUIL_SCORE = 0.8
CACHE_NOMS = CACHE / "noms_kohesio.json"


def _rechercher_nom(nom: str, dep: str | None) -> dict | None:
    import requests
    params = {"q": nom[:200], "page": 1, "per_page": 5}
    if dep:
        params["departement"] = dep
    for tentative in range(5):
        try:
            r = requests.get(API, params=params, headers=sirene.HEADERS, timeout=30)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(2 ** tentative)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** tentative)
            continue
        if r.status_code >= 400:
            return {"trouve": False}
        res = r.json().get("results", [])
        notes = sorted(((score_nom(nom, x), i, x) for i, x in enumerate(res)), key=lambda t: (-t[0], t[1]))
        if not notes or notes[0][0] < SEUIL_SCORE:
            return {"trouve": False}
        if len(notes) > 1 and notes[1][0] == notes[0][0] and notes[1][2]["siren"] != notes[0][2]["siren"]:
            return {"trouve": False, "ambigu": True}
        x = notes[0][2]
        cj = x.get("nature_juridique")
        entree = {"trouve": True, "siren": x["siren"], "cj": cj, "score": round(notes[0][0], 3)}
        if sirene.personne_morale(cj):  # jamais de nom pour une personne physique
            entree["nom"] = (x.get("nom_complet") or "").strip()
            entree["dep_siege"] = (x.get("siege") or {}).get("departement")
        return entree
    return None


def cle_nom(nom: str, dep: str | None) -> str:
    return f"{' '.join(sorted(jetons(nom)))}|{dep or ''}"


def noms_a_resoudre(lignes: list[dict]) -> list[tuple[str, str | None, float]]:
    """(nom, département dominant, montant) des noms Kohesio sans SIREN, par montant décroissant."""
    par_nom: dict[str, dict] = {}
    for l in lignes:
        if not l["nom"] or sirene.siren_valide(l["li"][:9]):
            continue
        k = " ".join(sorted(jetons(l["nom"])))
        if not k:
            continue
        e = par_nom.setdefault(k, {"nom": l["nom"], "eur": 0.0, "deps": defaultdict(float)})
        e["eur"] += l["eur"]
        if l["dep"]:
            e["deps"][l["dep"]] += l["eur"]
    out = []
    for e in par_nom.values():
        dep = max(e["deps"].items(), key=lambda x: x[1])[0] if e["deps"] else None
        out.append((e["nom"], dep, e["eur"]))
    return sorted(out, key=lambda t: -t[2])


def resoudre_noms(budget_s: float = 480, paralleles: int = 20) -> int:
    from concurrent.futures import ThreadPoolExecutor
    cache = json.loads(CACHE_NOMS.read_text(encoding="utf-8")) if CACHE_NOMS.exists() else {}
    a_faire = [(n, d) for n, d, eur in noms_a_resoudre(lire_kohesio())
               if eur >= SEUIL_NOMS_EUR and cle_nom(n, d) not in cache]
    debut = time.monotonic()
    verrou = threading.Lock()
    prochain = [time.monotonic()]
    faits = [0]

    def sauver():
        tmp = CACHE_NOMS.with_suffix(".part")
        tmp.write_text(json.dumps(dict(cache), ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE_NOMS)

    def tache(nd):
        nom, dep = nd
        if time.monotonic() - debut > budget_s:
            return
        with verrou:
            attente = prochain[0] - time.monotonic()
            prochain[0] = max(prochain[0], time.monotonic()) + sirene.PAUSE_S
        if attente > 0:
            time.sleep(attente)
        e = _rechercher_nom(nom, dep)
        if e is not None:
            with verrou:
                cache[cle_nom(nom, dep)] = e
                faits[0] += 1
                if faits[0] % 300 == 0:
                    sauver()
                    print(f"  {faits[0]}/{len(a_faire)} noms", file=sys.stderr)

    CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(paralleles) as ex:
        list(ex.map(tache, a_faire))
    sauver()
    restants = len([1 for n, d in a_faire if cle_nom(n, d) not in cache])
    print(f"noms Kohesio : {faits[0]} résolus, {restants} restants", file=sys.stderr)
    return restants


# --- FTS et Horizon ---------------------------------------------------------------------------------------------


def parquet_fts(annee: int) -> Path:
    """Conversion xlsx -> parquet (cache disque, refaite si le xlsx change)."""
    import csv
    import duckdb
    import openpyxl
    src = SOURCES[f"fts_{annee}"]["chemin"]
    dst = src.with_name(f"fts_{annee}.parquet")
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    tmp = src.with_name(f"fts_{annee}.csv.part")
    wb = openpyxl.load_workbook(src, read_only=True)
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row in wb.worksheets[0].iter_rows(values_only=True):
            w.writerow(["" if v is None else v for v in row])
    duckdb.sql(f"copy (select * from read_csv('{tmp}', all_varchar=true, header=true)) to '{dst}' (format parquet)")
    tmp.unlink()
    return dst


COL_MONTANT = "Beneficiary’s contracted amount (EUR)"


def lire_fts() -> tuple[list[dict], dict]:
    """Lignes France du FTS (hors PAC) et totaux par programme (toute l'UE, engagements de l'année)."""
    import duckdb
    lignes, programmes = [], {}
    for a in ANNEES_FTS:
        p = parquet_fts(a)
        rel = duckdb.sql(f"""select "Name of beneficiary" nom, "VAT number of beneficiary" tva, "Postal code" cp,
              "Beneficiary type" bt, "Programme name" prog, "Management type" gm,
              try_cast("{COL_MONTANT}" as double) eur, "Beneficiary country" pays from '{p}'""")
        tot = defaultdict(lambda: [0.0, 0.0])
        for nom, tva, cp, bt, prog, gm, eur, pays in rel.fetchall():
            eur = eur or 0.0
            code = (prog or "").split(" - ")[0].strip()
            tot[prog or "non précisé"][0] += eur
            if pays != "France":
                continue
            tot[prog or "non précisé"][1] += eur
            tva = (tva or "").replace(" ", "").upper()
            siren = tva[4:13] if re.match(r"^FR[0-9A-Z]{2}\d{9}$", tva) else None
            lignes.append({"source": "fts", "annee": a, "siren": siren, "eur": eur, "programme": prog or "non précisé",
                           "code": code, "pac": code.startswith("3.1."), "ngeu": code == "2.2.21",
                           "personne_privee": bt == "Private Persons",
                           "dep": dep_postal(cp), "type": bt})
        programmes[a] = dict(tot)
    return lignes, programmes


def lire_horizon() -> list[dict]:
    import duckdb
    p = SOURCES["horizon_mesr"]["chemin"]
    rel = duckdb.sql(f"""select siren_main, try_cast(fund_eur as double), call_year, activity_geo_unit_code,
          programme_name_fr from '{p}' where country_code = 'FRA'""")
    out = []
    for siren, eur, an, geo_, prog in rel.fetchall():
        dep = None
        if geo_:
            m = re.match(r"^FR-(\d[0-9AB]{1,2})", geo_.split(",")[0].strip())
            if m:
                dep = m.group(1)
                if len(dep) == 3 and not dep.startswith("97"):  # FR-75C : Paris
                    dep = dep[:2]
        out.append({"source": "horizon", "annee": int(an) if an and an.isdigit() else None, "siren": siren,
                    "eur": eur or 0.0, "programme": prog or "Horizon Europe", "dep": dep})
    return out


def resoudre_siren(budget_s: float = 480) -> int:
    fts, _ = lire_fts()
    sirens = [l["siren"] for l in sorted(fts, key=lambda l: -l["eur"]) if l["siren"] and not l["pac"]]
    sirens += [l["siren"] for l in sorted(lire_horizon(), key=lambda l: -l["eur"]) if l["siren"]]
    sirens += [l["li"][:9] for l in lire_kohesio() if sirene.siren_valide(l["li"][:9])]
    _, restants = sirene.resoudre(sirens, budget_s=budget_s)
    print(f"SIREN FTS / Horizon / Kohesio : {restants} restants", file=sys.stderr)
    return restants


# --- Production -------------------------------------------------------------------------------------------------


def psr_arbre() -> dict:
    racine = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    noeud = None

    def walk(n):
        nonlocal noeud
        if n["id"] == "Prelevements sur recettes/Union européenne":
            noeud = n
        for e in n.get("enfants", []):
            walk(e)

    walk(racine)
    if noeud is None:
        raise SystemExit("branche « Prelevements sur recettes/Union européenne » absente de arbre/racine.json")
    return {"md": noeud["md"], "id": noeud["id"], "total_arbre_md": racine["md"], "millesime": racine["millesime"]}


def contribution(programmes: dict, fts_france: list[dict]) -> dict:
    arbre = psr_arbre()
    psr = arbre["md"]
    if abs(psr - md(PSR_EXECUTE[2024])) > 0.001:
        raise SystemExit(f"PSR-UE de l'arbre ({psr}) != exécution 2024 publiée ({md(PSR_EXECUTE[2024])})")
    total_poles = sum(v for _, _, _, poles in CFP for _, _, v in poles)
    rubriques = []
    for code, nom, plafond, poles in CFP:
        s = sum(v for _, _, v in poles)
        rubriques.append({
            "code": code, "nom": nom, "cfp_md": md(s), "plafond_rubrique_md": md(plafond),
            "part": round(s / total_poles, 6), "contribution_france_md": round(psr * s / total_poles, 6),
            "eur_sur_100": round(100 * s / total_poles, 2),
            "poles": [{"code": pc, "nom": pn, "cfp_md": md(v), "part": round(v / total_poles, 6),
                       "contribution_france_md": round(psr * v / total_poles, 6),
                       "eur_sur_100": round(100 * v / total_poles, 2)} for pc, pn, v in poles]})
    a = 2024
    tot_ue = sum(v[0] for v in programmes[a].values())
    tries = sorted(programmes[a].items(), key=lambda kv: -kv[1][0])
    progs = [{"code": k.split(" - ")[0].strip(), "nom": k.split(" - ", 1)[-1].strip(),
              "rubrique": k.split(".")[0] if re.match(r"^\d\.", k) else None,
              "md": round(v[0] / 1e9, 6), "part": round(v[0] / tot_ue, 6), "dont_france_md": round(v[1] / 1e9, 6)}
             for k, v in tries[:40]]
    reste = tries[40:]
    return {
        "millesime": "Exécution 2024 (PSR-UE) ; CFP 2021-2027 après révision de 2024 ; engagements FTS 2024",
        "source": f"{SOURCES['jaune_ue_plf2025']['titre']} ; {SOURCES['senat_np_plf2026']['titre']} ; "
                  f"{SOURCES['senat_np_plf2027']['titre']} ; {SOURCES['fts_2024']['titre']} ; arbre État ({arbre['millesime']})",
        "unite": "milliards d'euros",
        "methode": ("Le prélèvement sur recettes au profit de l'UE (PSR-UE) n'est pas affecté à une politique : il comble, "
                    "avec les autres ressources propres, l'ensemble du budget de l'Union. Sa répartition par usage est "
                    "donc une convention : au prorata des plafonds du cadre financier pluriannuel (CFP) 2021-2027 par "
                    "pôle, marges non affectées exclues. NextGenerationEU, financé par l'emprunt de l'Union et non par "
                    "le PSR, est présenté à part."),
        "avertissement": ("Répartition proportionnelle conventionnelle : « sur 100 € versés par la France, X € vont à la PAC » "
                          "décrit la structure du budget de l'UE sur 2021-2027, pas un fléchage de l'argent français."),
        "psr_ue": {"annee": 2024, "md": psr, "noeud_arbre": arbre["id"], "fichier_arbre": "arbre/racine.json",
                   "eur_sur_100_budget_etat": round(100 * psr / arbre["total_arbre_md"], 2),
                   "source": "arbre État (exécution 2024) ; égal à l'exécution 2024 publiée par le Sénat (22 276 M€)"},
        "serie_psr_ue": [{"annee": an, "vote_md": md(PSR_VOTE[an]), "execute_md": md(PSR_EXECUTE[an]),
                          "statut": "prévision d'exécution" if an >= 2026 else "exécuté",
                          "source": ("Sénat, NP PLF 2027" if an >= 2025 else "Sénat, NP PLF 2026")}
                         for an in sorted(PSR_EXECUTE)],
        "usage": {"cle": "CFP 2021-2027 après révision du 29/02/2024, plafonds en crédits d'engagement, M€ courants",
                  "cfp_total_md": md(CFP_TOTAL), "poles_total_md": md(total_poles),
                  "marges_exclues_md": md(CFP_TOTAL - total_poles), "rubriques": rubriques,
                  "source": SOURCES["jaune_ue_plf2025"]["titre"]},
        "next_generation_eu": {
            "total_md": md(NGEU_TOTAL), "par_rubrique_md": {k: md(v) for k, v in NGEU.items()},
            "note": ("Plan de relance 2021-2026 financé par l'emprunt commun de l'Union, hors PSR ; son remboursement par "
                     "le budget de l'UE (donc en partie par le PSR) commence en 2028. Rubrique 2 : surtout la facilité pour "
                     "la reprise et la résilience (FRR)."),
            "source": SOURCES["jaune_ue_plf2025"]["titre"]},
        "programmes_engagements": {
            "millesime": "Engagements 2024", "source": SOURCES["fts_2024"]["titre"],
            "perimetre": ("gestion directe et indirecte seulement : la gestion partagée (PAC, FEDER, FSE+, l'essentiel du "
                          "budget) n'y figure pas ; montants contractés dans l'année, toute l'UE"),
            "total_md": round(tot_ue / 1e9, 6), "programmes": progs,
            "autres": {"nombre": len(reste), "md": round(sum(v[0] for _, v in reste) / 1e9, 6)}},
        "contribution_comptable_2024_md": 24.3,
        "note_contribution_comptable": ("Contribution totale 2024 au sens de la méthode comptable (PSR + droits de douane "
                                        "reversés, nets des frais de perception) : 24,3 Md€ (Sénat, NP PLF 2027). "
                                        "ue/retours.json publie la même grandeur déduite (retours - solde net "
                                        "comptable) : " + str(md(RETOURS_TOTAL[2024] - SOLDE_COMPTABLE[2024][0])
                                                             ).replace(".", ",") + " Md€ pour 2024, avant arrondi."),
        "sources_inaccessibles": INACCESSIBLES,
    }


def retours() -> dict:
    annees = []
    for an in sorted(RETOURS_TOTAL):
        par = None
        if an <= 2023:
            par = {k: {"nom": n, "md": md(v[an])} for k, (n, v) in RETOURS_RUBRIQUES.items()}
            if abs(sum(v[an] for _, v in RETOURS_RUBRIQUES.values()) - RETOURS_TOTAL[an]) > 2:
                raise SystemExit(f"retours {an} : somme des rubriques != total")
            src = "Commission, rapports financiers (annexe PLF 2025 « Relations financières avec l'UE »)"
        elif an == 2024:
            par = {k: {"nom": RETOURS_RUBRIQUES[k][0], "md": md(v)} for k, v in RETOURS_2024.items()}
            src = "annexe PLF 2026 « Relations financières avec l'UE », citée par le Sénat (NP PLF 2026)"
        else:
            par = {k: {"nom": RETOURS_RUBRIQUES[k][0], "md": md(v)} for k, v in RETOURS_2025.items()}
            src = "annexe PLF 2027 « Relations financières avec l'UE », citée par le Sénat (NP PLF 2027)"
        solde, pct = SOLDE_COMPTABLE[an]
        e = {"annee": an, "retours_md": md(RETOURS_TOTAL[an]), "par_rubrique": par,
             "rubriques_completes": an <= 2023,
             "solde_net_comptable_md": md(solde), "solde_net_pct_rnb": pct,
             "contribution_comptable_md": md(RETOURS_TOTAL[an] - solde),
             "psr_ue_execute_md": md(PSR_EXECUTE[an]), "source": src}
        if an in SOLDE_OPERATIONNEL:
            e["solde_net_operationnel_md"], e["solde_net_operationnel_pct_rnb"] = (md(SOLDE_OPERATIONNEL[an][0]),
                                                                                 SOLDE_OPERATIONNEL[an][1])
        annees.append(e)
    return {
        "millesime": "2021 à 2025 (retours et solde net) ; 2024 = année de l'arbre État",
        "source": f"{SOURCES['jaune_ue_plf2025']['titre']} ; {SOURCES['senat_np_plf2026']['titre']} ; "
                  f"{SOURCES['senat_np_plf2027']['titre']}",
        "unite": "milliards d'euros",
        "lecture": ("Retours = dépenses du budget de l'UE réalisées en France, hors plan de relance NextGenerationEU. "
                    "Solde net comptable = retours - contribution totale (PSR + droits de douane reversés) ; négatif = la "
                    "France verse plus qu'elle ne reçoit. contribution_comptable_md est déduite (retours - solde) ; "
                    "ue/contribution.json (`contribution_comptable_2024_md`) en publie la valeur arrondie citée par le "
                    "Sénat pour 2024."),
        "methodes_solde": {
            "comptable": "contribution totale, droits de douane compris, moins toutes les dépenses de l'UE en France",
            "operationnel": "méthode de la Commission : hors droits de douane et hors dépenses administratives",
            "correction_britannique": "hors droits de douane ; utilisée avant 2021"},
        "limites": ["Le solde net ne mesure ni les gains du marché unique ni l'effet en France de fonds dépensés ailleurs.",
                    "Les retours 2024 et 2025 ne sont publiés que pour quelques rubriques (PAC, compétitivité, cohésion).",
                    "Les bénéficiaires nommés (ue/beneficiaires/) ne couvrent pas la PAC, non collectée."],
        "annees": annees,
        "fichier_beneficiaires": "ue/beneficiaires/index.json",
    }


def beneficiaires(cache_cj: dict, programmes_fts: dict, fts: list[dict]) -> dict:
    deps, regs = geo()
    noms = json.loads(CACHE_NOMS.read_text(encoding="utf-8")) if CACHE_NOMS.exists() else {}
    kohesio = lire_kohesio()
    horizon = lire_horizon()

    # dénominations SIRENE et catégorie : cache de l'API (personnes morales seulement)
    def statut(siren):
        e = cache_cj.get(siren)
        if e is None:
            return "non_verifie", None, None
        if not e.get("trouve") or not e.get("cj"):
            return "inconnu", None, None
        if not sirene.personne_morale(e["cj"]):
            return "personne_physique", None, None
        return "pm", e["cj"], e.get("nom")

    # dominants par nom Kohesio (même clé que la résolution)
    dominant = {}
    for nom, dep, _ in noms_a_resoudre(kohesio):
        dominant[" ".join(sorted(jetons(nom)))] = dep

    stats = {s: defaultdict(float) for s in ("kohesio_2014_2020", "kohesio_2021_2027", "fts", "horizon")}
    lignes_n = defaultdict(int)
    benef: dict[str, dict] = {}          # (dep|siren) -> entrée
    par_annee = {s: defaultdict(float) for s in stats}
    par_dep_src = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    denominations = {}

    def ajouter(src, l, siren, cj, nom_sirene, dep_siege=None):
        dep = l.get("dep") or dep_siege or "non_localise"
        if dep not in deps and dep != "non_localise":
            dep = "non_localise"
        stats[src]["total"] += l["eur"]
        par_annee[src][str(l["annee"]) if l["annee"] else "non précisée"] += l["eur"]
        par_dep_src[dep][src]["total"] += l["eur"]
        if siren is None:
            return
        stats[src]["nomme"] += l["eur"]
        par_dep_src[dep][src]["nomme"] += l["eur"]
        denominations[siren] = nom_sirene
        b = benef.setdefault((dep, siren), {"siren": siren, "cj": cj, "eur": 0.0, "detail": defaultdict(lambda: [0.0, 0])})
        b["eur"] += l["eur"]
        prog = l.get("fonds") or l.get("programme")
        if src == "fts" and len(prog) > 60:
            prog = prog[:57].rstrip() + "..."
        d = b["detail"][(src, l["annee"], prog)]
        d[0] += l["eur"]
        d[1] += 1

    for l in kohesio:
        src = l["source"]
        lignes_n[src] += 1
        siren, cj, nom_s, dep_siege = None, None, None, None
        if sirene.siren_valide(l["li"][:9]):
            st, cj, nom_s = statut(l["li"][:9])
            if st == "pm":
                siren = l["li"][:9]
            else:
                stats[src]["exclus_" + st] += l["eur"]
        else:
            k = " ".join(sorted(jetons(l["nom"])))
            e = noms.get(f"{k}|{dominant.get(k) or ''}") if k else None
            if e and e.get("trouve") and sirene.personne_morale(e.get("cj")) and e.get("nom"):
                siren, cj, nom_s, dep_siege = e["siren"], e["cj"], e["nom"], e.get("dep_siege")
            elif e and e.get("trouve"):
                stats[src]["exclus_personne_physique"] += l["eur"]
            elif e is None:
                stats[src]["exclus_nom_non_soumis"] += l["eur"]
            else:
                stats[src]["exclus_non_rapproche"] += l["eur"]
        ajouter(src, l, siren, cj, nom_s, dep_siege)

    for l in fts:
        lignes_n["fts"] += 1
        if l["pac"]:
            stats["fts"]["hors_total_pac_non_collectee"] += l["eur"]
            continue
        if l["ngeu"]:  # facilité pour la reprise (NextGenerationEU), hors retours au sens de l'annexe budgétaire
            stats["fts"]["hors_total_nextgenerationeu_frr"] += l["eur"]
            continue
        siren = cj = nom_s = None
        if l["personne_privee"]:
            stats["fts"]["exclus_personne_physique"] += l["eur"]
        elif not l["siren"]:
            stats["fts"]["exclus_sans_tva_francaise"] += l["eur"]
        else:
            st, cj, nom_s = statut(l["siren"])
            if st == "pm":
                siren = l["siren"]
            else:
                stats["fts"]["exclus_" + st] += l["eur"]
        ajouter("fts", l, siren, cj, nom_s)

    for l in horizon:
        lignes_n["horizon"] += 1
        siren = cj = nom_s = None
        if sirene.siren_valide(l["siren"]):
            st, cj, nom_s = statut(l["siren"])
            if st == "pm":
                siren = l["siren"]
            else:
                stats["horizon"]["exclus_" + st] += l["eur"]
        else:
            stats["horizon"]["exclus_sans_siren"] += l["eur"]
        ajouter("horizon", l, siren, cj, nom_s)

    # fichiers par département
    for f in DOSSIER_DEP.glob("*.json"):
        f.unlink()
    entete_src = ("Kohesio (Commission, exports France 2014-2020 et 2021-2027, instantané "
                  f"{KOHESIO_INSTANTANE}) ; FTS {ANNEES_FTS[0]}-{ANNEES_FTS[-1]} (Commission) ; Horizon Europe "
                  "(MESR, fr-esr-horizon-projects-entities) ; catégorie juridique : " + sirene.API.split('/')[2])
    millesime = (f"Kohesio : opérations 2014-2027 (instantané {KOHESIO_INSTANTANE}) ; FTS : engagements "
                 f"{ANNEES_FTS[0]} à {ANNEES_FTS[-1]} ; Horizon Europe : appels 2021 à 2026")
    index_deps = []
    nb_nommes = set()
    for dep in sorted(set(d for d, _ in benef) | set(par_dep_src)):
        liste = []
        for (d, siren), b in benef.items():
            if d != dep:
                continue
            detail = sorted(([s, a, p, round(v[0], 2), v[1]] for (s, a, p), v in b["detail"].items()
                             if round(v[0], 2) != 0), key=lambda x: (-x[3]))
            if not detail:  # montants nuls (engagement annulé) : rien à montrer
                continue
            nb_nommes.add(siren)
            liste.append({"siren": siren, "denomination": denominations[siren], "categorie_juridique": b["cj"],
                          "montant_eur": round(b["eur"], 2),
                          "montant_hors_horizon_eur": round(sum(x[3] for x in detail if x[0] != "horizon"), 2),
                          "detail": detail})
        liste.sort(key=lambda x: -x["montant_eur"])
        totaux = {s: {"total_eur": round(v["total"], 2), "nomme_eur": round(v.get("nomme", 0.0), 2),
                      "non_nomme_eur": round(v["total"] - v.get("nomme", 0.0), 2)}
                  for s, v in par_dep_src[dep].items()}
        info = deps.get(dep)
        doc = {"millesime": millesime, "source": entete_src, "unite": "euros",
               "departement": dep, "nom": info["nom"] if info else "Non localisé",
               "region": {"code": info["codeRegion"], "nom": regs.get(info["codeRegion"])} if info else None,
               "totaux": totaux, "beneficiaires": liste}
        nom_fichier = f"{dep}.json"
        texte = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        if len(texte.encode("utf-8")) > 1_000_000:  # découpe : on garde les plus gros, le reste agrégé
            garde = []
            for x in liste:
                garde.append(x)
                doc["beneficiaires"] = garde
                if len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 950_000:
                    garde.pop()
                    break
            reste = liste[len(garde):]
            doc["beneficiaires_hors_fichier"] = {"nombre": len(reste),
                                                 "montant_eur": round(sum(x["montant_eur"] for x in reste), 2),
                                                 "note": "plus petits montants, non listés pour tenir sous 1 Mo"}
        dump(DOSSIER_DEP / nom_fichier, doc)
        index_deps.append({"code": dep, "nom": doc["nom"], "region": doc["region"]["code"] if doc["region"] else None,
                           "fichier": f"ue/beneficiaires/{nom_fichier}", "beneficiaires": len(doc["beneficiaires"]),
                           "total_eur": round(sum(v["total_eur"] for s, v in totaux.items() if s != "horizon"), 2),
                           "nomme_eur": round(sum(v["nomme_eur"] for s, v in totaux.items() if s != "horizon"), 2)})

    par_region = defaultdict(lambda: {"total_eur": 0.0, "nomme_eur": 0.0})
    for d in index_deps:
        r = d["region"] or "non_localise"
        par_region[r]["total_eur"] += d["total_eur"]
        par_region[r]["nomme_eur"] += d["nomme_eur"]
    noms_regions = {**regs, "non_localise": "Non localisé"}

    def bloc(src):
        s = stats[src]
        out = {k: round(v, 2) for k, v in sorted(s.items())}
        out["lignes"] = lignes_n[src]
        return out

    tot_hors_h = sum(stats[s]["total"] for s in ("kohesio_2014_2020", "kohesio_2021_2027", "fts"))
    nomme_hors_h = sum(stats[s].get("nomme", 0.0) for s in ("kohesio_2014_2020", "kohesio_2021_2027", "fts"))
    index = {
        "millesime": millesime, "source": entete_src, "unite": "euros",
        "regle_personnes_physiques": ("seules les personnes morales (catégorie juridique 2xxx à 9xxx vérifiée via l'API "
                                      "Recherche d'entreprises) sont nommées, sous leur dénomination SIRENE ; "
                                      "entrepreneurs individuels, « Private Persons » du FTS et noms non rapprochés "
                                      "sont agrégés ; bénéficiaires de la PAC non collectés"),
        "lecture": ("Kohesio : budget UE programmé par opération (année = début de l'opération) ; FTS : montant contracté "
                    "dans l'année d'engagement ; Horizon : subvention signée (année de l'appel). Horizon recoupe le FTS "
                    "(programme 1.0.11) : total_nomme_eur et les totaux par département l'excluent ; "
                    "montant_eur d'un bénéficiaire l'inclut, montant_hors_horizon_eur non."),
        "rapprochement_kohesio": (f"nom publié rapproché d'un SIREN par l'API Recherche d'entreprises (même département, "
                                  f"ressemblance des mots du nom >= {SEUIL_SCORE}, résultat ambigu rejeté) pour les noms "
                                  f"cumulant au moins {SEUIL_NOMS_EUR} € ; le reste est agrégé"),
        "sources": {s: {**bloc(s), "titre": t} for s, t in (
            ("kohesio_2014_2020", SOURCES["kohesio_2014_2020"]["titre"]),
            ("kohesio_2021_2027", SOURCES["kohesio_2021_2027"]["titre"]),
            ("fts", f"Financial Transparency System {ANNEES_FTS[0]}-{ANNEES_FTS[-1]}, bénéficiaires établis en France"),
            ("horizon", SOURCES["horizon_mesr"]["titre"]))},
        "par_annee": {s: {a: round(v, 2) for a, v in sorted(d.items())} for s, d in par_annee.items()},
        "par_region": [{"code": r, "nom": noms_regions.get(r, r), "total_eur": round(v["total_eur"], 2),
                        "nomme_eur": round(v["nomme_eur"], 2)}
                       for r, v in sorted(par_region.items(), key=lambda kv: -kv[1]["total_eur"])],
        "departements": index_deps,
        "total_eur": round(tot_hors_h, 2), "total_nomme_eur": round(nomme_hors_h, 2),
        "part_nommee": round(nomme_hors_h / tot_hors_h, 4) if tot_hors_h else None,
        "beneficiaires_nommes": len(nb_nommes),
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "sources_inaccessibles": INACCESSIBLES,
    }
    dump(DOSSIER_DEP / "index.json", index)
    return index


def produire() -> dict:
    verif = verifier_documents()
    fts, programmes = lire_fts()
    cache_cj = sirene.charger_cache()
    c = contribution(programmes, fts)
    c["verification_documents"] = verif
    dump(SORTIE / "contribution.json", c)
    r = retours()
    idx = beneficiaires(cache_cj, programmes, fts)
    r["beneficiaires_nommes"] = {"nombre": idx["beneficiaires_nommes"], "total_nomme_eur": idx["total_nomme_eur"],
                                 "total_eur": idx["total_eur"], "part_nommee": idx["part_nommee"]}
    r["verification_documents"] = verif
    dump(SORTIE / "retours.json", r)
    bilan = {"psr_2024_md": c["psr_ue"]["md"], "retours_2024_md": md(RETOURS_TOTAL[2024]),
             "solde_2024_md": md(SOLDE_COMPTABLE[2024][0]), "beneficiaires_nommes": idx["beneficiaires_nommes"],
             "total_nomme_eur": idx["total_nomme_eur"], "part_nommee": idx["part_nommee"]}
    print(json.dumps(bilan, ensure_ascii=False), file=sys.stderr)
    return bilan


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("commande", nargs="*", default=["collecter", "produire"],
                    choices=["collecter", "resoudre", "produire"])
    ap.add_argument("--budget", type=float, default=480, help="secondes maximum pour chaque résolution réseau")
    args = ap.parse_args(argv)
    for cmd in args.commande:
        if cmd == "collecter":
            collecter()
        elif cmd == "resoudre":
            resoudre_noms(args.budget)
            resoudre_siren(args.budget)
        elif cmd == "produire":
            produire()


if __name__ == "__main__":
    main()
