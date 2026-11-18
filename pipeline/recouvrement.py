"""Contrôle et recouvrement : ce que les administrations notifient, ce qu'elles encaissent, ce qui est estimé.

Trois notions jamais confondues, chacune avec son producteur, son périmètre, sa méthode et son année :
    notifié    : montant mis à la charge d'un contribuable ou d'un cotisant à l'issue d'un contrôle ;
    encaissé   : somme effectivement payée pendant l'année à la suite de contrôles ;
    estimation : ordre de grandeur calculé par un organisme, qui dépend de son périmètre et de sa méthode.
Les restitutions aux cotisants sont publiées à côté des redressements. La sphère fiscale (DGFiP) et la sphère
sociale (Urssaf, caisses de sécurité sociale) ne sont ni opposées ni additionnées : aucun total commun, aucun
rapport entre les deux n'est calculé. Les estimations ne sont jamais additionnées entre elles.

Commandes :
    python collecte/collecte.py recouvrement_urssaf_controle recouvrement_urssaf_travail_dissimule \
        recouvrement_urssaf_impayes_national recouvrement_urssaf_impayes_regions recouvrement_urssaf_lexique \
        recouvrement_etat_apurements recouvrement_etat_plan_comptable recouvrement_dgfip_annuaires \
        recouvrement_documents recouvrement_ce_ecart_tva
        (réseau, collecteur du dépôt : un refus 403/429 n'est jamais contourné ; sources déclarées dans
        collecte/catalogue.json, tracées dans data/lake/manifest.json)
    python pipeline/recouvrement.py produire [--sortie DOSSIER]   (sans réseau)

Sorties (site/data/recouvrement/, contrat docs/contrat_interface.md, schémas docs/schemas/recouvrement_*.json) :
    index.json, controle_fiscal.json, controle_urssaf.json, impayes.json, apurements_etat.json, estimations.json

Sorties reproductibles : aucune heure de passage (date de collecte lue par pipeline/reproductible.py), ordres
explicites. Chaque citation est recherchée mot pour mot dans le document collecté : la production échoue sinon.
Aucune personne physique : agrégats nationaux, régionaux et par organisme de recouvrement.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "recouvrement"
SORTIE = ROOT / "site" / "data" / "recouvrement"
DOCS = LAKE / "recouvrement_documents"
ANNUAIRES = LAKE / "recouvrement_dgfip_annuaires"

URL_URSSAF = "https://open.urssaf.fr/explore/dataset"
SOURCES = {
    "urssaf_controle": {
        "titre": "Résultats de l'activité du contrôle et de prévention par les Urssaf", "producteur": "Urssaf",
        "url": f"{URL_URSSAF}/resultats-du-controle-par-les-urssaf/", "licence": "ODbL",
        "fichier_collecte": "recouvrement_urssaf_controle.csv"},
    "urssaf_travail_dissimule": {
        "titre": "Résultats de la lutte contre le travail dissimulé par les Urssaf", "producteur": "Urssaf",
        "url": f"{URL_URSSAF}/resultats-de-la-lutte-contre-le-travail-illegal/", "licence": "ODbL",
        "fichier_collecte": "recouvrement_urssaf_travail_dissimule.csv"},
    "urssaf_impayes_national": {
        "titre": "Taux d'impayés mensuels, entreprises de 10 salariés ou plus, métropole", "producteur": "Urssaf",
        "url": f"{URL_URSSAF}/taux-rar-horsto-mensuels-entreprises-de-10-salaries-ou-plus/", "licence": "ODbL",
        "fichier_collecte": "recouvrement_urssaf_impayes_national.csv"},
    "urssaf_impayes_regions": {
        "titre": "Taux d'impayés mensuels, entreprises de 10 salariés ou plus, par région", "producteur": "Urssaf",
        "url": f"{URL_URSSAF}/taux-rar-horsto-mensuels-entreprises-de-10-salaries-ou-plus-par-region/",
        "licence": "ODbL", "fichier_collecte": "recouvrement_urssaf_impayes_regions.csv"},
    "urssaf_lexique": {
        "titre": "Lexique des activités et des services de l'Urssaf", "producteur": "Urssaf",
        "url": f"{URL_URSSAF}/lexique-des-activites-et-des-services-de-lurssaf/", "licence": "ODbL",
        "fichier_collecte": "recouvrement_urssaf_lexique.csv"},
    "etat_comptabilite_generale": {
        "titre": "Données de comptabilité générale de l'État sur dix ans (balances des comptes)",
        "producteur": "DGFiP (Compte général de l'État)",
        "url": "https://data.economie.gouv.fr/explore/dataset/balances_des_comptes_etat/",
        "licence": "Licence Ouverte 2.0", "fichier_collecte": "recouvrement_etat_apurements.csv"},
    "etat_plan_comptable": {
        "titre": "Plan comptable de l'État (pièce jointe du jeu balances_des_comptes_etat)", "producteur": "DGFiP",
        "url": "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/balances_des_comptes_etat/"
               "attachments/plan_comptable_de_letatxlsx",
        "licence": "Licence Ouverte 2.0",
        "fichier_collecte": "recouvrement_etat_plan_comptable/plan_comptable_de_l_etat.xlsx"},
    "dgfip_annuaire_2010": {
        "titre": "Annuaire statistique 2010 de la DGFiP, tableau 601 (contrôle fiscal 1996-2010)",
        "producteur": "DGFiP",
        "url": "https://static.data.gouv.fr/resources/annuaire-statistique/20211206-153459/"
               "annuaire-statistique-2010.zip",
        "licence": "Licence Ouverte",
        "fichier_collecte": "recouvrement_dgfip_annuaires/annuaire-statistique-2010.zip"},
    "dgfip_annuaire_2019": {
        "titre": "Annuaire statistique 2019 de la DGFiP, tableaux CFC_001 à CFC_004 (contrôle fiscal 2010-2019)",
        "producteur": "DGFiP",
        "url": "https://static.data.gouv.fr/resources/annuaire-statistique/20211206-152555/"
               "annuaire-statistique-2019.zip",
        "licence": "Licence Ouverte",
        "fichier_collecte": "recouvrement_dgfip_annuaires/annuaire-statistique-2019.zip"},
    "dpt_2026": {
        "titre": "Document de politique transversale « Lutte contre l'évasion et la fraude fiscale », annexe au "
                 "projet de loi de finances pour 2026",
        "producteur": "Gouvernement (annexe au PLF 2026), données DGFiP",
        "url": "https://www.assemblee-nationale.fr/dyn/dyn/contenu/visualisation/1090106/file/"
               "14-DPT2026_Fraude_Fiscale.pdf",
        "licence": "document budgétaire public",
        "fichier_collecte": "recouvrement_documents/dpt2026_fraude_fiscale.pdf"},
    "hcfips_2025": {
        "titre": "Note annuelle de suivi et d'évaluation des fraudes sociales, synthèse (décembre 2025)",
        "producteur": "Haut Conseil du financement de la protection sociale (HCFiPS)",
        "url": "https://www.strategie-plan.gouv.fr/files/files/Publications/2026/2026-01-13%20-%20HCFiPS%20-%20"
               "note%20annuelle%20fraude%20sociale/HCFIPS%20-%20Synth%C3%A8se%20Fraude%20sociale%202025%20-%20"
               "Version%20finalis%C3%A9e_0.pdf",
        "licence": "rapport public",
        "fichier_collecte": "recouvrement_documents/hcfips_synthese_fraude_sociale_2025.pdf"},
    "cour_des_comptes_2025": {
        "titre": "« La lutte contre la fraude fiscale », rapport public thématique (16 décembre 2025)",
        "producteur": "Cour des comptes",
        "url": "https://www.ccomptes.fr/sites/default/files/2025-12/20251216-Lutte-contre-la-fraude-fiscale.pdf",
        "licence": "rapport public",
        "fichier_collecte": "recouvrement_documents/cour_des_comptes_lutte_fraude_fiscale_2025.pdf"},
    "ce_ecart_tva_2025": {
        "titre": "« VAT gap in Europe, report 2025 », page de résultats par État membre (11 décembre 2025)",
        "producteur": "Commission européenne (DG TAXUD)",
        "url": "https://taxation-customs.ec.europa.eu/taxation/vat/fight-against-vat-fraud/vat-gap_en",
        "licence": "Commission européenne, réutilisation autorisée avec mention de la source (décision 2011/833/UE)",
        "fichier_collecte": "recouvrement_ce_ecart_tva/vat_gap_en.html"},
}

NOTIONS = {
    "notifie": {
        "libelle": "Montant notifié",
        "definition": "Montant mis à la charge d'un contribuable ou d'un cotisant à l'issue d'un contrôle : droits "
                      "rappelés et pénalités pour la DGFiP, redressements pour les Urssaf. Ce montant n'est pas une "
                      "somme entrée dans les caisses publiques : une partie est contestée, annulée, remise ou n'est "
                      "jamais recouvrée."},
    "encaisse": {
        "libelle": "Montant encaissé",
        "definition": "Somme effectivement payée pendant l'année à la suite de contrôles, quelle que soit l'année "
                      "du contrôle. Les encaissements d'une année portent donc sur des contrôles de plusieurs "
                      "années."},
    "estimation": {
        "libelle": "Estimation",
        "definition": "Ordre de grandeur calculé par un organisme à partir d'une méthode statistique. Le résultat "
                      "dépend du périmètre retenu et de la méthode ; ce n'est ni un montant notifié ni un montant "
                      "encaissé."},
    "restitution": {
        "libelle": "Montant restitué",
        "definition": "Somme rendue au cotisant quand le contrôle montre qu'il a versé davantage que ce qu'il "
                      "devait. Les Urssaf la publient à côté des redressements."},
    "apurement": {
        "libelle": "Créance retirée des comptes",
        "definition": "Créance que l'État cesse de poursuivre : admission en non-valeur (créance jugée "
                      "irrécouvrable) ou décision gracieuse (remise accordée au débiteur). Ces montants portent sur "
                      "toutes les créances concernées, pas seulement sur celles nées d'un contrôle."},
    "taux_impayes": {
        "libelle": "Taux d'impayés",
        "definition": "Part des cotisations dues qui restent à recouvrer à une date donnée (fin du mois, fin du "
                      "mois suivant, 90 jours après l'échéance), hors taxations d'office."},
}

REGLES = [
    "Chaque montant porte sa notion (notifié, encaissé, estimation, restitution, créance retirée des comptes), son "
    "producteur, son périmètre, sa méthode et son année.",
    "Un montant notifié et un montant encaissé de la même année ne portent pas sur les mêmes contrôles : leur "
    "rapport n'est pas un taux de recouvrement et n'est pas calculé ici. Le taux de recouvrement publié par la DGFiP "
    "est repris tel quel.",
    "La sphère fiscale (impôts, DGFiP) et la sphère sociale (cotisations et prestations, Urssaf et caisses de "
    "sécurité sociale) sont présentées avec le même format ; elles ne sont ni additionnées ni rapportées l'une à "
    "l'autre.",
    "Les estimations ne sont jamais additionnées entre elles ni à des montants notifiés ou encaissés : leurs "
    "périmètres se recouvrent en partie et leurs méthodes diffèrent.",
    "Les restitutions aux cotisants sont publiées à côté des redressements, avec la même unité et les mêmes années.",
    "Quand deux sources publient deux valeurs pour la même année, les deux sont publiées avec leur écart ; aucune "
    "n'est retenue contre l'autre.",
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "conclusion": "Aucun dépôt public ne rassemble ces séries : les jeux officiels sont repris tels quels avec le "
                  "collecteur du dépôt ; les tableaux du document budgétaire et des annuaires sont lus à la source.",
    "trouvailles": [
        {"nom": "open.urssaf.fr : résultats du contrôle, lutte contre le travail dissimulé, taux d'impayés",
         "url": "https://open.urssaf.fr/explore/?q=contr%C3%B4le", "verdict": "réutilisable tel quel",
         "licence": "ODbL", "mise_a_jour": "2025-07-17 (contrôle), 2026-10-21 (taux d'impayés)"},
        {"nom": "data.economie.gouv.fr : balances des comptes de l'État 2016-2025",
         "url": "https://data.economie.gouv.fr/explore/dataset/balances_des_comptes_etat/",
         "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-10-28"},
        {"nom": "data.gouv.fr : annuaire statistique de la DGFiP (éditions 2004 à 2019, tableaux 2022)",
         "url": "https://www.data.gouv.fr/datasets/annuaire-statistique/", "verdict": "à adapter",
         "licence": "Licence Ouverte", "mise_a_jour": "2023-03-13 (classeurs .xls par tableau, lus tels quels)"},
        {"nom": "collecte/collecte.py (collecteur du dépôt : exports ODS, URL, manifeste)",
         "url": "collecte/collecte.py", "verdict": "réutilisable tel quel", "licence": "MIT",
         "mise_a_jour": "2026-11-17"},
        {"nom": "pipeline/europe_comparaison.py (vérification des citations dans les documents collectés)",
         "url": "pipeline/europe_comparaison.py", "verdict": "à adapter", "licence": "MIT",
         "mise_a_jour": "2026-11-17"},
        {"nom": "jeandirel/P4-detection-fraude-fiscale-pilotage-recettes (modèle de détection, sans série publiée)",
         "url": "https://github.com/jeandirel/P4-detection-fraude-fiscale-pilotage-recettes",
         "verdict": "inspiration seulement", "licence": "aucune licence déclarée (non réutilisable)",
         "mise_a_jour": "2026-02-28"},
        {"nom": "Recherche GitHub « controle fiscal », « fraude fiscale », « urssaf open data », « vat gap », "
                "« tax gap » : aucun dépôt de données sur le contrôle fiscal ou social français",
         "url": "https://github.com/search?q=fraude+fiscale&type=repositories", "verdict": "inspiration seulement",
         "licence": "sans objet", "mise_a_jour": "2026-11-17"},
    ],
}

SOURCES_INACCESSIBLES = [
    {"source": "Commission européenne, classeur « VAT-GAP-2025-tables.xlsx » (séries par pays et par année)",
     "motif": "le serveur a répondu 429 (limite de requêtes atteinte) le 17/11/2026 ; non insisté. Seule la page de résultats "
              "par État membre est reprise (France, 2023)."},
    {"source": "DGFiP Analyses n° 7 (septembre 2024), étude d'origine de l'estimation du manque à gagner de TVA",
     "motif": "non collectée : l'estimation est reprise telle que la cite le document de politique transversale "
              "annexé au PLF 2026."},
    {"source": "Urssaf, montants encaissés à la suite des contrôles et des redressements pour travail dissimulé",
     "motif": "non publiés dans les jeux ouverts de l'Urssaf : seuls les montants notifiés (redressements) et les "
              "restitutions le sont. Le montant recouvré par la branche recouvrement est repris de la synthèse du "
              "HCFiPS, sous forme d'ordre de grandeur."},
    {"source": "DGFiP, montants notifiés et encaissés du contrôle fiscal en données ouvertes après 2019",
     "motif": "les tableaux statistiques 2022 de la DGFiP ne prolongent pas la série publiée jusqu'en 2019 ; les années 2016 à "
              "2024 sont lues dans le tableau du document de politique transversale (PDF)."},
]


# ----------------------------------------------------------------------------------------------------------------
# Outils
# ----------------------------------------------------------------------------------------------------------------

def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def nom_tri(nom: str) -> str:
    return _sans_accents(nom).lower()


def _cle(libelle: str) -> str:
    """Libellé de tableau normalisé : minuscules, sans accents, sans renvoi de note « (1) », espaces simples."""
    s = _sans_accents(str(libelle)).lower()
    s = re.sub(r"\(\s*\d+\s*\)", " ", s)
    s = s.replace("’", "'")
    return re.sub(r"\s+", " ", s).strip(" :-–")


def _nombre(x) -> float | None:
    """Valeur numérique d'une cellule ; vide, tiret ou « nc » : None (jamais 0)."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    if s in ("", "-", "–", "nc", "ns", "nd"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _r(x: float | None, n: int = 2) -> float | int | None:
    if x is None:
        return None
    v = round(x + 0.0, n)
    return int(v) if n == 0 else v


def _somme(valeurs) -> float | None:
    """Somme des valeurs présentes ; None si toutes sont absentes."""
    presentes = [v for v in valeurs if v is not None]
    return sum(presentes) if presentes else None


def _lire_csv(nom: str) -> list[dict]:
    chemin = LAKE / nom
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def serrer(s: str) -> str:
    """Texte réduit à ses caractères significatifs : sert à retrouver une citation malgré les retours à la ligne
    et les coupures de mots d'un PDF (espaces et traits d'union retirés des deux côtés, apostrophes unifiées)."""
    s = html.unescape(s).replace("’", "'").replace("‘", "'").replace("­", "")
    return re.sub(r"[\s\-‐‑–−]+", "", s)


_PDF = {}


def _pdf(nom: str):
    if nom not in _PDF:
        import pdfplumber
        _PDF[nom] = pdfplumber.open(DOCS / nom)
    return _PDF[nom]


def textes_page(nom: str, page: int) -> list[str]:
    """Textes d'une page de PDF : page entière, moitié gauche, moitié droite (documents en deux colonnes)."""
    p = _pdf(nom).pages[page - 1]
    milieu = _gouttiere(p)
    zones = [p, p.within_bbox((0, 0, milieu, p.height)), p.within_bbox((milieu, 0, p.width, p.height))]
    return [z.extract_text() or "" for z in zones]


def _gouttiere(p) -> float:
    """Abscisse qui sépare deux colonnes de texte : milieu de la plus large bande verticale presque vide entre
    30 % et 70 % de la largeur (au plus deux caractères la traversent) ; à défaut, le milieu de la page."""
    occupation = [0] * (int(p.width) + 2)
    for c in p.chars:
        for x in range(int(c["x0"]), int(c["x1"]) + 1):
            if 0 <= x < len(occupation):
                occupation[x] += 1
    meilleur, debut = (0, p.width / 2), None
    for x in range(int(p.width * 0.3), int(p.width * 0.7) + 1):
        if occupation[x] <= 2:
            debut = x if debut is None else debut
            if x - debut + 1 > meilleur[0]:
                meilleur = (x - debut + 1, (debut + x) / 2)
        else:
            debut = None
    return meilleur[1]


def texte_html(chemin: Path) -> str:
    t = chemin.read_text(encoding="utf-8", errors="replace")
    t = re.sub(r"(?s)<(script|style)\b.*?</\1>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def citation_presente(citation: str, textes: list[str]) -> bool:
    c = serrer(citation)
    return any(c in serrer(t) for t in textes)


def lignes_tableau(nom: str, page: int) -> list[dict]:
    """Lignes d'une page de PDF, mots regroupés en cellules : deux mots séparés de moins de 4 points forment une
    même cellule (séparateur de milliers), au-delà une nouvelle colonne."""
    p = _pdf(nom).pages[page - 1]
    par_ligne = defaultdict(list)
    for m in p.extract_words(x_tolerance=1.5):
        par_ligne[round(m["top"])].append(m)
    lignes = []
    for haut in sorted(par_ligne):
        mots = sorted(par_ligne[haut], key=lambda m: m["x0"])
        cellules, fin = [], None
        for m in mots:
            if cellules and m["x0"] - fin < 4:
                cellules[-1] += " " + m["text"]
            else:
                cellules.append(m["text"])
            fin = m["x1"]
        lignes.append({"haut": haut, "cellules": cellules, "texte": " ".join(cellules)})
    return lignes


_ENTIER = re.compile(r"^\d{1,3}(?: \d{3})*$|^\d+$")


def valeurs_ligne(cellules: list[str], n: int) -> tuple[list[float], list[str]] | None:
    """Les n dernières cellules entières d'une ligne (avant le pourcentage d'évolution) et ce qui les précède."""
    c = list(cellules)
    while c and not _ENTIER.match(c[-1]):
        c.pop()
    fin = len(c)
    debut = fin
    while debut > 0 and _ENTIER.match(c[debut - 1]) and fin - debut < n:
        debut -= 1
    if fin - debut < n:
        return None
    return [float(x.replace(" ", "")) for x in c[debut:fin]], c[:debut]


# ----------------------------------------------------------------------------------------------------------------
# Contrôle fiscal (DGFiP) : annuaires statistiques 1996-2019 et document de politique transversale 2016-2024
# ----------------------------------------------------------------------------------------------------------------

SERIES_FISCALES = [  # (id, libellé, notion, unité, groupe)
    ("total_droits_penalites", "Contrôle sur place et sur pièces : droits et pénalités", "notifie", "M€", "ensemble"),
    ("total_droits", "Contrôle sur place et sur pièces : droits simples rappelés", "notifie", "M€", "ensemble"),
    ("credits_non_rembourses", "Crédits d'impôt et taxes non remboursés (contrôles sur pièces et sur place)",
     "notifie", "M€", "ensemble"),
    ("place_droits", "Contrôle sur place : droits simples rappelés", "notifie", "M€", "sur_place"),
    ("place_penalites", "Contrôle sur place : pénalités", "notifie", "M€", "sur_place"),
    ("place_operations", "Contrôle sur place : nombre d'opérations", "activite", "nombre", "sur_place"),
    ("vc_droits", "Vérification de comptabilité : total des droits simples rappelés", "notifie", "M€", "sur_place"),
    ("vc_is", "Vérification de comptabilité : impôt sur les sociétés", "notifie", "M€", "sur_place"),
    ("vc_ir", "Vérification de comptabilité : impôt sur le revenu", "notifie", "M€", "sur_place"),
    ("vc_autres", "Vérification de comptabilité : autres impôts directs", "notifie", "M€", "sur_place"),
    ("vc_tca", "Vérification de comptabilité : taxes sur le chiffre d'affaires", "notifie", "M€", "sur_place"),
    ("vc_locaux", "Vérification de comptabilité : impôts locaux", "notifie", "M€", "sur_place"),
    ("vc_enr", "Vérification de comptabilité : droits d'enregistrement", "notifie", "M€", "sur_place"),
    ("vc_penalites", "Vérification de comptabilité : pénalités appliquées (tous impôts)", "notifie", "M€",
     "sur_place"),
    ("vc_operations", "Vérification de comptabilité : nombre d'opérations", "activite", "nombre", "sur_place"),
    ("esfp_droits", "Examen de situation fiscale personnelle : droits simples rappelés", "notifie", "M€",
     "sur_place"),
    ("esfp_penalites", "Examen de situation fiscale personnelle : pénalités appliquées", "notifie", "M€",
     "sur_place"),
    ("esfp_operations", "Examen de situation fiscale personnelle : nombre d'opérations", "activite", "nombre",
     "sur_place"),
    ("pieces_droits", "Contrôle sur pièces : droits simples rappelés", "notifie", "M€", "sur_pieces"),
    ("pieces_penalites", "Contrôle sur pièces : pénalités appliquées (tous impôts)", "notifie", "M€", "sur_pieces"),
    ("pieces_is", "Contrôle sur pièces : impôt sur les sociétés", "notifie", "M€", "sur_pieces"),
    ("pieces_ir", "Contrôle sur pièces : impôt sur le revenu", "notifie", "M€", "sur_pieces"),
    ("pieces_tca", "Contrôle sur pièces : taxes sur le chiffre d'affaires", "notifie", "M€", "sur_pieces"),
    ("pieces_remb_credits", "Contrôle sur pièces : demandes de remboursement de crédits rejetées", "notifie", "M€",
     "sur_pieces"),
    ("pieces_enr", "Contrôle sur pièces : droits d'enregistrement", "notifie", "M€", "sur_pieces"),
    ("pieces_divers", "Contrôle sur pièces : impôts divers", "notifie", "M€", "sur_pieces"),
    ("pieces_isf", "Contrôle sur pièces : impôt de solidarité sur la fortune, impôt sur la fortune immobilière",
     "notifie", "M€", "sur_pieces"),
    ("encaissements_hors_stdr", "Encaissements à la suite du contrôle fiscal, hors service de traitement des "
     "déclarations rectificatives (STDR)", "encaisse", "M€", "encaissements"),
    ("encaissements_stdr", "Encaissements du service de traitement des déclarations rectificatives (STDR)",
     "encaisse", "M€", "encaissements"),
    ("encaissements_total", "Encaissements à la suite du contrôle fiscal : total", "encaisse", "M€",
     "encaissements"),
]
LIBELLES_FISCAUX = {s[0]: s for s in SERIES_FISCALES}

# Tableau du document de politique transversale : numéro de ligne imprimé -> série.
LIGNES_DPT = {"3": "vc_operations", "4": "vc_is", "5": "vc_ir", "6": "vc_autres", "7": "vc_tca", "8": "vc_locaux",
              "9": "vc_enr", "10": "vc_droits", "11": "vc_penalites", "12": "esfp_operations", "13": "esfp_droits",
              "14": "esfp_penalites", "15": "place_operations", "16": "place_droits", "17": "place_penalites",
              "18": "pieces_is", "19": "pieces_ir", "20": "pieces_tca", "21": "pieces_enr", "22": "pieces_divers",
              "23": "pieces_isf", "24": "pieces_droits", "25": "total_droits", "25 bis": "total_droits_penalites"}
DPT_PDF = "dpt2026_fraude_fiscale.pdf"
DPT_PAGES = {"resultats": (73, 74), "encaissements": 84, "taux": 63}


def _classer_ligne_annuaire(section: str | None, cle: str) -> tuple[str | None, str | None]:
    """(nouvelle section, identifiant de série) pour une ligne des tableaux 601 / CFC_001 / CFC_002."""
    if cle.startswith("recapitulation des resultats du controle sur place et sur pieces"):
        return section, "total_droits"
    if cle.startswith("recapitulation des resultats du controle sur place"):
        return "place", None
    if cle.startswith("recapitulation des resultats du controle sur pieces"):
        return section, "pieces_droits"
    if "verification de comptabilite" in cle:
        return "vc", None
    if "examen contradictoire" in cle:
        return "esfp", None
    if cle.startswith("b - controle sur pieces"):
        return "pieces", None
    if section == "vc":
        for motif, sid in (("impot sur les societes", "vc_is"), ("impot sur le revenu", "vc_ir"),
                           ("autres impots", "vc_autres"), ("taxes sur le chiffre", "vc_tca"),
                           ("impots locaux", "vc_locaux"), ("droits d'enregistrement", "vc_enr"),
                           ("total des droits simples", "vc_droits"), ("penalites appliquees", "vc_penalites")):
            if motif in cle:
                return section, sid
        if cle.startswith("total"):
            return section, "vc_operations"
    elif section in ("esfp", "place"):
        for motif, suffixe in (("droits simples rappeles", "droits"), ("penalites", "penalites"),
                               ("nombre d'operations", "operations")):
            if motif in cle:
                return section, f"{section}_{suffixe}"
    elif section == "pieces":
        for motif, sid in (("impot sur les societes", "pieces_is"), ("impot sur le revenu", "pieces_ir"),
                           ("taxes sur le chiffre", "pieces_tca"), ("demandes de remboursement", "pieces_remb_credits"),
                           ("droits d'enregistrement", "pieces_enr"), ("impots divers", "pieces_divers"),
                           ("impot de solidarite", "pieces_isf")):
            if motif in cle:
                return section, sid
    return section, None


def _annee_cellule(x) -> int | None:
    if isinstance(x, float) and x == int(x) and 1990 <= x <= 2100:
        return int(x)
    m = re.match(r"^\s*((?:19|20)\d{2})\b", str(x))
    return int(m.group(1)) if m else None


def lire_tableau_xls(archive: Path, membre: str) -> tuple[dict[str, dict[int, float | None]], list[str]]:
    """Séries (identifiant -> année -> valeur) et notes d'un tableau .xls d'un annuaire statistique."""
    try:
        import xlrd
    except ImportError as e:  # même dépendance facultative que collecte/conversion.py (deploy/requirements-vps.txt)
        raise SystemExit("xlrd est requis pour lire les annuaires .xls : pip install 'xlrd>=2.0,<3'") from e
    with zipfile.ZipFile(archive) as z:
        feuille = xlrd.open_workbook(file_contents=z.read(membre)).sheet_by_index(0)
    lignes = [feuille.row_values(i) for i in range(feuille.nrows)]
    entete = next(i for i, l in enumerate(lignes) if sum(_annee_cellule(c) is not None for c in l) >= 5)
    colonnes = {j: _annee_cellule(c) for j, c in enumerate(lignes[entete]) if _annee_cellule(c) is not None}
    premiere = min(colonnes)
    series, notes, section = {}, [], None
    for l in lignes[entete + 1:]:
        libelle = next((str(c) for c in l[:premiere] if str(c).strip()), "")
        if not libelle:
            continue
        cle = _cle(libelle)
        if re.match(r"^\s*(\(\d\)|\*+|source)", libelle.strip(), re.I):
            notes.append(re.sub(r"\s+", " ", libelle).strip())
            continue
        section, sid = _classer_ligne_annuaire(section, cle)
        valeurs = {a: _nombre(l[j]) for j, a in colonnes.items()}
        if sid and any(v is not None for v in valeurs.values()):
            if sid in series:
                raise SystemExit(f"{membre} : série {sid} lue deux fois")
            series[sid] = valeurs
    return series, notes


def lire_plaintes(archive: Path, membre: str) -> tuple[list[int], list[dict], list[str]]:
    import xlrd
    with zipfile.ZipFile(archive) as z:
        feuille = xlrd.open_workbook(file_contents=z.read(membre)).sheet_by_index(0)
    lignes = [feuille.row_values(i) for i in range(feuille.nrows)]
    entete = next(i for i, l in enumerate(lignes) if sum(_annee_cellule(c) is not None for c in l) >= 5)
    colonnes = {j: _annee_cellule(c) for j, c in enumerate(lignes[entete]) if _annee_cellule(c) is not None}
    annees = sorted(colonnes.values())
    rangs, notes = [], []
    for l in lignes[entete + 1:]:
        libelle = re.sub(r"\s+", " ", str(l[0])).strip()
        if not libelle:
            continue
        if re.match(r"^(\*+|source)", libelle, re.I):
            notes.append(libelle)
            continue
        par_annee = {a: _nombre(l[j]) for j, a in colonnes.items()}
        rangs.append({"libelle": re.sub(r"\s*\*+$", "", libelle), "valeurs": [_r(par_annee[a], 0) for a in annees]})
    return annees, rangs, notes


def lire_dpt() -> dict:
    """Tableaux du document de politique transversale : résultats 2016-2024 (pages 73 et 74), encaissements."""
    series, annees = {}, None
    for page in DPT_PAGES["resultats"]:
        lignes = lignes_tableau(DPT_PDF, page)
        for i, l in enumerate(lignes):
            a = [int(c) for c in l["cellules"] if re.fullmatch(r"20\d{2}", c)]
            if len(a) >= 9 and annees is None:
                annees = a[:9]
            lu = valeurs_ligne(l["cellules"], 9)
            if not lu or not l["cellules"][-1].endswith("%"):
                continue
            valeurs, avant = lu
            numero = avant[-1] if avant and re.fullmatch(r"\d{1,2}(?: ?(?:bis|ter))?", avant[-1]) else None
            voisinage = _cle(" ".join(x["texte"] for x in lignes[max(0, i - 2):i + 3]))
            if numero in LIGNES_DPT:
                series[LIGNES_DPT[numero]] = valeurs
            elif numero is None and "penalites appliquees" in voisinage and "c)" in l["cellules"]:
                series["pieces_penalites"] = valeurs
            elif numero is None and "non rembourses" in voisinage:
                series["credits_non_rembourses"] = valeurs
    if annees != list(range(2016, 2025)):
        raise SystemExit(f"document de politique transversale : années du tableau inattendues ({annees})")
    attendues = set(LIGNES_DPT.values()) | {"pieces_penalites", "credits_non_rembourses"}
    manquantes = sorted(attendues - set(series))
    if manquantes:
        raise SystemExit(f"document de politique transversale : lignes non retrouvées {manquantes}")

    page = DPT_PAGES["encaissements"]
    lignes = lignes_tableau(DPT_PDF, page)
    textes = " ".join(l["texte"] for l in lignes)
    if "LES ENCAISSEMENTS" not in textes:
        raise SystemExit("document de politique transversale : tableau des encaissements introuvable page 84")
    entete = next((l for l in lignes if sum(bool(re.fullmatch(r"20\d{2}", c)) for c in l["cellules"]) >= 9), None)
    if entete is None or [int(c) for c in entete["cellules"] if re.fullmatch(r"20\d{2}", c)][:9] != annees:
        raise SystemExit("document de politique transversale : années du tableau des encaissements inattendues")
    debut = next(i for i, l in enumerate(lignes) if "LES ENCAISSEMENTS" in l["texte"])
    fin = next(i for i, l in enumerate(lignes) if i > debut and "RECOUVREMENT DES IMPOSITIONS" in l["texte"])
    trouvees = [valeurs_ligne(l["cellules"], 9) for l in lignes[debut:fin]]
    trouvees = [t[0] for t in trouvees if t and [int(x) for x in t[0]] != annees]
    if len(trouvees) != 3:
        raise SystemExit(f"document de politique transversale : {len(trouvees)} lignes d'encaissements lues, 3 attendues")
    series["encaissements_hors_stdr"], series["encaissements_stdr"], series["encaissements_total"] = trouvees
    return {"annees": annees, "series": series}


def produire_controle_fiscal(collecte_le: str) -> tuple[dict, dict]:
    ed2010, notes2010 = lire_tableau_xls(ANNUAIRES / "annuaire-statistique-2010.zip", "tab601_2010.xls")
    ed2019, notes2019 = lire_tableau_xls(ANNUAIRES / "annuaire-statistique-2019.zip", "CFC_001_2019.xls")
    ops2019, notes_ops = lire_tableau_xls(ANNUAIRES / "annuaire-statistique-2019.zip", "CFC_002_2019.xls")
    for sid, v in ops2019.items():
        if sid in ed2019:
            raise SystemExit(f"annuaire 2019 : série {sid} présente dans CFC_001 et CFC_002")
        ed2019[sid] = v
    dpt = lire_dpt()

    annees_annuaire = list(range(1996, 2020))
    chevauchement = []
    series = []
    for sid, libelle, notion, unite, groupe in SERIES_FISCALES:
        if sid in ed2010 or sid in ed2019:
            valeurs = []
            nd = 0 if unite == "nombre" else 2
            for a in annees_annuaire:
                src = ed2010 if a <= 2009 else ed2019
                valeurs.append(_r(src.get(sid, {}).get(a), nd))
            if sid in ed2010 and sid in ed2019 and ed2010[sid].get(2010) is not None \
                    and ed2019[sid].get(2010) is not None:
                chevauchement.append({"serie": sid, "edition_2010": _r(ed2010[sid][2010]),
                                      "edition_2019": _r(ed2019[sid][2010]),
                                      "ecart": _r(ed2019[sid][2010] - ed2010[sid][2010])})
            series.append({"id": f"annuaire_{sid}", "serie": sid, "libelle": libelle, "notion": notion,
                           "unite": unite, "groupe": groupe, "source": "annuaires",
                           "annees": annees_annuaire, "valeurs": valeurs})
        if sid in dpt["series"]:
            series.append({"id": f"dpt_{sid}", "serie": sid, "libelle": libelle, "notion": notion, "unite": unite,
                           "groupe": groupe, "source": "dpt_2026", "annees": dpt["annees"],
                           "valeurs": [_r(v, 0) for v in dpt["series"][sid]]})

    par_id = {s["id"]: s for s in series}

    def v(sid: str, annee: int):
        s = par_id[sid]
        return s["valeurs"][s["annees"].index(annee)]

    # Écarts entre les deux sources sur les années communes (2016 à 2019) : publiés, jamais tranchés.
    ecarts = []
    for sid in ("total_droits", "place_droits", "place_penalites", "pieces_droits", "place_operations"):
        for a in range(2016, 2020):
            x, y = v(f"annuaire_{sid}", a), v(f"dpt_{sid}", a)
            if x is None or y is None:
                continue
            e = {"serie": sid, "annee": a, "source": "annuaires", "valeur": x, "autre_source": "dpt_2026",
                 "autre_valeur": y, "ecart": _r(y - x), "unite": LIBELLES_FISCAUX[sid][3]}
            if sid == "total_droits":
                e["credits_non_rembourses_dpt"] = v("dpt_credits_non_rembourses", a)
            ecarts.append(e)
    lecture_ecart = ("Le document annexé au PLF 2026 présente à part les crédits d'impôt et taxes non remboursés "
                     "(note 9 de son tableau), que l'annuaire comptait dans les droits rappelés ; l'annuaire 2019 "
                     "applique en outre à l'année 2019 les montants définitivement notifiés (note 1 du tableau "
                     "CFC_002). Les deux séries sont publiées côte à côte et ne sont pas raccordées.")

    # Contrôles arithmétiques publiés (écart maximal relevé, en M€ ou en nombre).
    def ecart_max(total: str, parties: list[str], annees: list[int]) -> float:
        return max(abs(v(total, a) - sum(v(p, a) for p in parties)) for a in annees)

    coherence = {
        "dpt_total_droits_egale_place_plus_pieces": _r(ecart_max("dpt_total_droits", ["dpt_place_droits",
                                                                                       "dpt_pieces_droits"],
                                                                 dpt["annees"])),
        "dpt_droits_et_penalites_egale_droits_plus_penalites": _r(ecart_max(
            "dpt_total_droits_penalites", ["dpt_total_droits", "dpt_place_penalites", "dpt_pieces_penalites"],
            dpt["annees"])),
        "dpt_encaissements_total_egale_hors_stdr_plus_stdr": _r(ecart_max(
            "dpt_encaissements_total", ["dpt_encaissements_hors_stdr", "dpt_encaissements_stdr"], dpt["annees"])),
        "annuaire_total_droits_egale_place_plus_pieces": _r(ecart_max(
            "annuaire_total_droits", ["annuaire_place_droits", "annuaire_pieces_droits"], annees_annuaire)),
        "unite": "M€ ; écart maximal en valeur absolue sur toutes les années, dû aux arrondis de la source",
    }

    cit_taux = ("Au 30 juin 2025, le taux national d’encaissement net des créances issues du contrôle fiscal, au "
                "titre des impôts auto-liquidés et des impôts sur rôle, est de 67,99 %, le taux brut est de 51,60 %.")
    cit_rupture = ("À compter de 2019, les résultats du contrôle fiscal présentent les montants définitivement "
                   "notifiés qui font l’objet d’une demande de mise en recouvrement au terme de la procédure de "
                   "contrôle")
    if not any(cit_rupture in re.sub(r"\s+", " ", n) for n in notes_ops):
        raise SystemExit("annuaire 2019 : note de rupture de série 2019 introuvable dans CFC_002")
    if not citation_presente(cit_taux, textes_page(DPT_PDF, DPT_PAGES["taux"])):
        raise SystemExit("document de politique transversale : citation du taux d'encaissement introuvable page 63")

    annees_p, procedes, notes_p = lire_plaintes(ANNUAIRES / "annuaire-statistique-2019.zip", "CFC_003_2019.xls")
    annees_s, secteurs, notes_s = lire_plaintes(ANNUAIRES / "annuaire-statistique-2019.zip", "CFC_004_2019.xls")
    total_p = next(r for r in procedes if "plaintes" in r["libelle"].lower())
    total_s = next(r for r in secteurs if r["libelle"].lower() == "total")
    if total_p["valeurs"] != total_s["valeurs"] or annees_p != annees_s:
        raise SystemExit("annuaire 2019 : totaux des plaintes différents entre CFC_003 et CFC_004")

    doc = {
        "millesime": "Contrôle fiscal 1996 à 2019 (annuaires statistiques de la DGFiP) et 2016 à 2024 (document de "
                     "politique transversale annexé au PLF 2026)",
        "source": "DGFiP, annuaire statistique 2010 (tableau 601) et 2019 (tableaux CFC_001 à CFC_004), data.gouv.fr ; "
                  "document de politique transversale « Lutte contre l'évasion et la fraude fiscale », PLF 2026, "
                  "pages 63, 73, 74 et 84",
        "unite": "millions d'euros courants (montants) ; nombre (opérations, plaintes)",
        "avertissement": "Les montants notifiés (droits rappelés et pénalités) ne sont pas des recettes : ils "
                         "sont mis à la charge des contribuables à l'issue des contrôles. Les encaissements d'une "
                         "année portent sur des contrôles de plusieurs années. Deux sources couvrent les années "
                         "2016 à 2019 avec des périmètres différents : leurs écarts sont publiés.",
        "collecte_le": collecte_le,
        "sphere": "fiscale",
        "producteur": "Direction générale des finances publiques (DGFiP)",
        "perimetre": "Impôts contrôlés par la DGFiP, France entière : contrôle sur place (vérifications de "
                     "comptabilité, examens de situation fiscale personnelle) et contrôle sur pièces. Hors douane "
                     "(DGDDI).",
        "methode": "Chiffres de gestion publiés par l'administration : montants rappelés à l'issue des contrôles "
                   "de l'année (droits simples, pénalités) et sommes encaissées dans l'année. Aucun retraitement ; "
                   "valeurs reprises des tableaux publiés, null quand la ligne n'existe pas pour l'année.",
        "sources_series": {
            "annuaires": {"libelle": "Annuaires statistiques de la DGFiP : édition 2010 pour 1996 à 2009, édition "
                                     "2019 pour 2010 à 2019",
                          "annees": [1996, 2019], "sources": ["dgfip_annuaire_2010", "dgfip_annuaire_2019"]},
            "dpt_2026": {"libelle": "Document de politique transversale annexé au PLF 2026, tableau « Résultats du "
                                    "contrôle fiscal » et tableau « Les encaissements »",
                         "annees": [dpt["annees"][0], dpt["annees"][-1]], "sources": ["dpt_2026"]},
        },
        "series": series,
        "ruptures": [
            {"annee": 2019, "source": "dgfip_annuaire_2019", "tableau": "CFC_002, note 1",
             "texte": "À partir de 2019, l'annuaire compte les montants définitivement notifiés, après avis des "
                      "instances consultatives ; les années précédentes sont comptées avant ces avis.",
             "citation": next(re.sub(r"\s+", " ", n) for n in notes_ops if cit_rupture in re.sub(r"\s+", " ", n))},
            {"annee": 2020, "source": "dpt_2026", "tableau": "Les encaissements",
             "texte": "Le service de traitement des déclarations rectificatives (avoirs détenus à l'étranger) "
                      "n'apporte plus d'encaissements à partir de 2020 : la ligne vaut 0 dans le tableau publié."},
        ],
        "notes_sources": {"annuaire_2010_tableau_601": notes2010, "annuaire_2019_cfc_001": notes2019,
                          "annuaire_2019_cfc_002": [re.sub(r"\s+", " ", n) for n in notes_ops]},
        "raccord_editions_2010": {
            "definition": "Année 2010 lue dans les deux éditions de l'annuaire : valeurs de l'édition 2010, de "
                          "l'édition 2019 et écart, série par série.",
            "series": chevauchement},
        "ecarts_entre_sources": ecarts,
        "lecture_ecart": lecture_ecart,
        "coherence": coherence,
        "taux_recouvrement": {
            "date": "2025-06-30", "taux_net_pct": 67.99, "taux_brut_pct": 51.60, "source": "dpt_2026", "page": 63,
            "perimetre": "Créances issues du contrôle fiscal, impôts auto-liquidés et impôts sur rôle, tous "
                         "services de la DGFiP.",
            "methode": "Taux publié par la DGFiP. Le taux net exclut les créances sur lesquelles les comptables ne "
                       "peuvent pas agir (procédures collectives, contestations avec sursis de paiement).",
            "citation": cit_taux},
        "plaintes": {
            "definition": "Plaintes pour fraude fiscale : dénonciations obligatoires transmises aux parquets, "
                          "plaintes autorisées par la commission des infractions fiscales et plaintes pour saisine "
                          "de la police fiscale (notes du tableau).",
            "source": "dgfip_annuaire_2019", "annees": annees_p, "unite": "nombre",
            "par_procede": [r for r in procedes if r is not total_p],
            "par_secteur": [r for r in secteurs if r is not total_s],
            "total": total_p["valeurs"],
            "notes_sources": notes_p + [n for n in notes_s if n not in notes_p]},
    }
    resume = {
        "annee": dpt["annees"][-1],
        "notifie_droits_penalites_meur": v("dpt_total_droits_penalites", dpt["annees"][-1]),
        "notifie_droits_meur": v("dpt_total_droits", dpt["annees"][-1]),
        "credits_non_rembourses_meur": v("dpt_credits_non_rembourses", dpt["annees"][-1]),
        "encaisse_meur": v("dpt_encaissements_total", dpt["annees"][-1]),
        "premiere_annee": annees_annuaire[0],
    }
    return doc, resume


# ----------------------------------------------------------------------------------------------------------------
# Contrôle des cotisations (Urssaf) : redressements, restitutions, travail dissimulé
# ----------------------------------------------------------------------------------------------------------------

ORDRE_TYPES_CONTROLE = ["Contrôle comptable d'assiette", "Contrôle partiel d'assiette", "Autre action", "Prévention"]
ORDRE_TYPES_LCTD = ["Contrôle ciblé LCTI", "CCA (avec redressements LCTI)", "Autre action LCTI",
                    "Prévention/recherche LCTI"]
LIBELLES_LCTD = {
    "Contrôle ciblé LCTI": "Contrôle ciblé de lutte contre le travail dissimulé",
    "CCA (avec redressements LCTI)": "Contrôle comptable d'assiette ayant donné lieu à un redressement pour "
                                     "travail dissimulé",
    "Autre action LCTI": "Autre action de lutte contre le travail dissimulé",
    "Prévention/recherche LCTI": "Prévention et recherche",
}
MESURES_CONTROLE = [("nombre_actions", "nombre_actions", 0), ("nombre_de_regularisations", "nombre_regularisations", 0),
                    ("montant_redressements", "redressements_eur", 0), ("montant_restitutions", "restitutions_eur", 0),
                    ("montant_regularisations", "regularisations_eur", 0)]
MESURES_LCTD = [("nombre_actions", "nombre_actions", 0), ("nombre_redressements", "nombre_redressements", 0),
                ("montant_redressements", "redressements_eur", 0)]


def _agreger(lignes: list[dict], cle_type: str, mesures: list[tuple], ordre_types: list[str]) -> dict:
    annees = sorted({int(l["annee"][:4]) for l in lignes})
    types = sorted({l[cle_type] for l in lignes}, key=lambda t: (ordre_types.index(t) if t in ordre_types else 99, t))
    cumul = defaultdict(list)       # (type, année, mesure) -> valeurs
    organismes = defaultdict(lambda: defaultdict(list))  # organisme -> (année, mesure) -> valeurs
    infos = {}
    for l in lignes:
        a = int(l["annee"][:4])
        infos[l["organisme"]] = (l["region"], l["code_region"])
        for col, nom, _ in mesures:
            x = _nombre(l[col])
            cumul[(l[cle_type], a, nom)].append(x)
            organismes[l["organisme"]][(a, nom)].append(x)
    par_type = [{"type_action": t,
                 **{nom: [_r(_somme(cumul[(t, a, nom)]), nd) for a in annees] for _, nom, nd in mesures}}
                for t in types]
    total = {nom: [_r(_somme([x for t in types for x in cumul[(t, a, nom)]]), nd) for a in annees]
             for _, nom, nd in mesures}
    par_organisme = {o: {nom: [_r(_somme(organismes[o][(a, nom)]), nd) for a in annees] for _, nom, nd in mesures}
                     for o in organismes}
    return {"annees": annees, "types": par_type, "total": total, "organismes": par_organisme, "infos": infos}


def produire_controle_urssaf(collecte_le: str) -> tuple[dict, dict]:
    controle = _agreger(_lire_csv("recouvrement_urssaf_controle.csv"), "type_action", MESURES_CONTROLE,
                        ORDRE_TYPES_CONTROLE)
    lctd = _agreger(_lire_csv("recouvrement_urssaf_travail_dissimule.csv"), "type_d_action", MESURES_LCTD,
                    ORDRE_TYPES_LCTD)
    for t in lctd["types"]:
        t["libelle"] = LIBELLES_LCTD.get(t["type_action"], t["type_action"])
    if controle["annees"] != lctd["annees"]:
        raise SystemExit("Urssaf : années différentes entre contrôle et travail dissimulé")
    annees = controle["annees"]
    tot = controle["total"]
    # Identité publiée par l'Urssaf : régularisations = redressements + restitutions.
    identite = max(abs(g - (r + s)) for g, r, s in zip(tot["regularisations_eur"], tot["redressements_eur"],
                                                      tot["restitutions_eur"]))
    tot["part_restitutions_pct"] = [_r(100 * s / g, 1) if g else None
                                    for s, g in zip(tot["restitutions_eur"], tot["regularisations_eur"])]

    lexique = {l["libelle_technique"]: l["definition"].strip() for l in _lire_csv("recouvrement_urssaf_lexique.csv")}
    definitions = []
    for terme, cle in (("Redressements", "redressements"), ("Restitutions", "restitutions"),
                       ("Régularisations", "regularisation"),
                       ("Contrôle comptable d'assiette (CCA)", "controle comptable d'assiette (cca)"),
                       ("Lutte contre le travail dissimulé (LCTD)", "lutte contre le travail dissimule")):
        if cle not in lexique:
            raise SystemExit(f"lexique Urssaf : entrée « {cle} » introuvable")
        definitions.append({"terme": terme, "citation": lexique[cle], "source": "urssaf_lexique"})

    noms = sorted(set(controle["organismes"]) | set(lctd["organismes"]), key=nom_tri)
    organismes = []
    for o in noms:
        region, code = (controle["infos"].get(o) or lctd["infos"][o])
        c, d = controle["organismes"].get(o), lctd["organismes"].get(o)
        organismes.append({
            "organisme": o, "nom_tri": nom_tri(o), "region": region, "code_region": code,
            "controle": None if c is None else {k: c[k] for k in ("nombre_actions", "redressements_eur",
                                                                 "restitutions_eur", "regularisations_eur")},
            "travail_dissimule": None if d is None else {k: d[k] for k in ("nombre_actions", "redressements_eur")}})

    doc = {
        "millesime": f"Contrôles des Urssaf {annees[0]} à {annees[-1]}",
        "source": "Urssaf, open.urssaf.fr : « Résultats de l'activité du contrôle et de prévention par les Urssaf » "
                  "et « Résultats de la lutte contre le travail dissimulé par les Urssaf » (ODbL)",
        "unite": "euros courants (montants) ; nombre (actions, régularisations, redressements)",
        "avertissement": "Les redressements sont des montants notifiés aux cotisants, pas des sommes encaissées : "
                         "l'Urssaf ne publie pas en données ouvertes ce qui est ensuite payé. Les restitutions sont "
                         "des sommes rendues aux cotisants après contrôle ; elles figurent à côté des "
                         "redressements. L'année 2020 est marquée par la crise sanitaire (mention du lexique de "
                         "l'Urssaf).",
        "collecte_le": collecte_le,
        "sphere": "sociale",
        "producteur": "Urssaf (réseau des Urssaf régionales et des caisses générales de sécurité sociale "
                      "d'outre-mer)",
        "perimetre": "Cotisations et contributions sociales contrôlées par le réseau des Urssaf, France entière, "
                     "par organisme chargé du contrôle. Hors régime agricole (MSA) et hors contrôles des caisses "
                     "de prestations.",
        "methode": "Chiffres de gestion publiés par l'Urssaf, par organisme, type d'action et année ; sommes par "
                   "année faites ici sur les lignes publiées. Une valeur absente à la source reste null.",
        "annees": annees,
        "controle": {
            "source": "urssaf_controle",
            "definition": "Contrôles d'assiette et actions de prévention. Les régularisations additionnent, en "
                          "valeur absolue, les redressements (en faveur de l'Urssaf) et les restitutions (en "
                          "faveur du cotisant).",
            "types": controle["types"], "total": tot,
            "identite_regularisations": {
                "definition": "régularisations = redressements + restitutions ; écart maximal relevé sur les "
                              "totaux annuels, en euros",
                "ecart_max_eur": _r(identite, 0)}},
        "travail_dissimule": {
            "source": "urssaf_travail_dissimule",
            "definition": "Actions de lutte contre le travail dissimulé et redressements notifiés à ce titre. "
                          "Aucune restitution n'est publiée dans ce jeu.",
            "types": lctd["types"], "total": lctd["total"]},
        "regle": "Les deux jeux sont publiés séparément par l'Urssaf. La source ne précise pas si les redressements "
                 "pour travail dissimulé constatés lors d'un contrôle comptable d'assiette figurent aussi dans les "
                 "résultats du contrôle : les deux séries ne sont pas additionnées.",
        "definitions": definitions,
        "organismes": organismes,
        "ordre": {"regle": "Organismes par ordre alphabétique de leur nom (sans accents ni majuscules).",
                  "cles": ["nom_tri"]},
    }
    i = len(annees) - 1
    resume = {"annee": annees[-1], "redressements_eur": tot["redressements_eur"][i],
              "restitutions_eur": tot["restitutions_eur"][i], "regularisations_eur": tot["regularisations_eur"][i],
              "travail_dissimule_redressements_eur": lctd["total"]["redressements_eur"][i],
              "premiere_annee": annees[0], "organismes": len(organismes)}
    return doc, resume


# ----------------------------------------------------------------------------------------------------------------
# Taux d'impayés des cotisations (Urssaf)
# ----------------------------------------------------------------------------------------------------------------

TAUX = [("taux_impayes_fin_mois", "fin_mois"), ("taux_impayes_fin_mois_suivant", "fin_mois_suivant"),
        ("taux_impayes_echeance_90_jours", "a_90_jours")]


def _series_taux(lignes: list[dict]) -> dict:
    lignes = sorted(lignes, key=lambda l: l["dernier_jour_du_mois"])
    mois = [l["dernier_jour_du_mois"][:7] for l in lignes]
    if len(set(mois)) != len(mois):
        raise SystemExit("taux d'impayés : mois en double")
    return {"mois": mois, **{nom: [_r(_nombre(l[col]), 4) for l in lignes] for col, nom in TAUX}}


def produire_impayes(collecte_le: str) -> tuple[dict, dict]:
    national = _series_taux(_lire_csv("recouvrement_urssaf_impayes_national.csv"))
    par_region = defaultdict(list)
    noms = {}
    for l in _lire_csv("recouvrement_urssaf_impayes_regions.csv"):
        par_region[l["code_region"]].append(l)
        noms[l["code_region"]] = l["region"]
    regions = [{"code_region": c, "region": noms[c], "nom_tri": nom_tri(noms[c]), **_series_taux(par_region[c])}
               for c in sorted(par_region, key=lambda c: nom_tri(noms[c]))]
    dernier = max(i for i, x in enumerate(national["a_90_jours"]) if x is not None)
    doc = {
        "millesime": f"Taux d'impayés mensuels, {national['mois'][0]} à {national['mois'][-1]}",
        "source": "Urssaf, open.urssaf.fr : « Taux d'impayés mensuels, entreprises de 10 salariés ou plus », "
                  "métropole et par région (ODbL)",
        "unite": "% des cotisations dues",
        "avertissement": "Un impayé à une date donnée n'est pas une perte définitive : une partie est payée "
                         "ensuite. Le taux à 90 jours n'est connu qu'avec trois mois de recul : les derniers mois "
                         "sont null. Ces taux ne mesurent ni une fraude ni un résultat de contrôle.",
        "collecte_le": collecte_le,
        "sphere": "sociale",
        "notion": "taux_impayes",
        "producteur": "Urssaf",
        "perimetre": "Régime général, entreprises du secteur privé de 10 salariés ou plus ; série nationale : "
                     "métropole ; séries régionales : chaque région publiée par l'Urssaf. Hors taxations d'office.",
        "methode": "Rapport entre les cotisations restant à recouvrer et les cotisations dues, pour les "
                   "cotisations exigibles un mois donné, vu à la fin de ce mois, à la fin du mois suivant et 90 "
                   "jours après l'échéance. Séries corrigées des variations saisonnières par l'Urssaf.",
        "taux": {"fin_mois": "Taux d'impayés à la fin du mois d'exigibilité",
                 "fin_mois_suivant": "Taux d'impayés à la fin du mois suivant",
                 "a_90_jours": "Taux d'impayés 90 jours après l'échéance"},
        "national": {"source": "urssaf_impayes_national", **national},
        "regions": regions,
        "ordre": {"regle": "Régions par ordre alphabétique de leur nom (sans accents ni majuscules).",
                  "cles": ["nom_tri"]},
    }
    resume = {"mois": national["mois"][dernier], "taux_a_90_jours_pct": national["a_90_jours"][dernier],
              "premier_mois": national["mois"][0], "dernier_mois": national["mois"][-1], "regions": len(regions)}
    return doc, resume


# ----------------------------------------------------------------------------------------------------------------
# Créances retirées des comptes de l'État : admissions en non-valeur et décisions gracieuses
# ----------------------------------------------------------------------------------------------------------------

COMPTES = [  # (compte, catégorie, champ)
    ("6251400000", "admission_en_non_valeur", "créances liées aux impôts d'État"),
    ("6251800000", "admission_en_non_valeur", "autres créances de l'État"),
    ("6537100000", "admission_en_non_valeur", "créances d'impôts locaux"),
    ("6252400000", "decision_gracieuse", "créances liées aux impôts d'État"),
    ("6252800000", "decision_gracieuse", "autres créances de l'État"),
]


def libelles_plan_comptable() -> dict[str, str]:
    import openpyxl
    wb = openpyxl.load_workbook(LAKE / "recouvrement_etat_plan_comptable" / "plan_comptable_de_l_etat.xlsx",
                                read_only=True)
    libelles = {}
    for feuille in wb:
        for ligne in feuille.iter_rows(values_only=True):
            cellules = [c for c in ligne[:6] if c is not None]
            if len(cellules) >= 2 and str(cellules[0]).strip().isdigit():
                libelles.setdefault(str(cellules[0]).strip(), re.sub(r"\s+", " ", str(cellules[1])).strip())
    wb.close()
    return libelles


def produire_apurements(collecte_le: str) -> tuple[dict, dict]:
    libelles = libelles_plan_comptable()
    sommes = defaultdict(float)
    for l in _lire_csv("recouvrement_etat_apurements.csv"):
        x = _nombre(l["balance_sortie"])
        if x is not None:
            sommes[(l["compte"], int(l["annee"][:4]))] += x
    annees = sorted({a for _, a in sommes})
    comptes = []
    for compte, categorie, champ in COMPTES:
        if compte not in libelles:
            raise SystemExit(f"plan comptable de l'État : compte {compte} introuvable")
        comptes.append({"compte": compte, "libelle_source": libelles[compte], "categorie": categorie, "champ": champ,
                        "montants_eur": [_r(sommes[(compte, a)], 0) if (compte, a) in sommes else None
                                         for a in annees]})
    doc = {
        "millesime": f"Comptes de l'État {annees[0]} à {annees[-1]}",
        "source": "DGFiP, « Données de comptabilité générale de l'État sur dix ans » (balances des comptes ayant "
                  "servi au Compte général de l'État), data.economie.gouv.fr, comptes 62514, 62518, 62524, 62528 et "
                  "65371 ; libellés du plan comptable de l'État",
        "unite": "euros courants",
        "avertissement": "Ces charges portent sur toutes les créances concernées (impôts déclarés et non payés, "
                         "amendes, créances issues d'un contrôle), pas seulement sur celles nées d'un contrôle. "
                         "Elles ne mesurent pas une fraude. Les lignes ne sont pas additionnées à des montants "
                         "notifiés ou encaissés.",
        "collecte_le": collecte_le,
        "sphere": "fiscale",
        "notion": "apurement",
        "producteur": "DGFiP (comptabilité générale de l'État)",
        "perimetre": "Comptes de charges de l'État, budget général et comptes spéciaux : admissions en non-valeur "
                     "et décisions gracieuses sur les créances liées aux impôts d'État, sur les autres créances de "
                     "l'État et sur les impôts locaux (admissions en non-valeur prises en charge par l'État).",
        "methode": "Somme par année du solde de sortie de chaque compte, toutes missions et tous programmes ; "
                   "comptabilité en droits constatés. Une année sans ligne publiée pour un compte reste null.",
        "definitions": {
            "admission_en_non_valeur": "Décision de ne plus poursuivre une créance jugée irrécouvrable (débiteur "
                                       "insolvable ou disparu). La créance n'est pas éteinte en droit.",
            "decision_gracieuse": "Remise totale ou partielle accordée au débiteur à sa demande."},
        "annees": annees,
        "comptes": comptes,
    }
    i = len(annees) - 1
    resume = {"annee": annees[-1], "premiere_annee": annees[0],
              "admissions_non_valeur_impots_etat_eur": comptes[0]["montants_eur"][i],
              "decisions_gracieuses_impots_etat_eur": comptes[3]["montants_eur"][i]}
    return doc, resume


# ----------------------------------------------------------------------------------------------------------------
# Estimations publiées et constats sur l'absence d'estimation
# ----------------------------------------------------------------------------------------------------------------

HCFIPS_PDF = "hcfips_synthese_fraude_sociale_2025.pdf"
CDC_PDF = "cour_des_comptes_lutte_fraude_fiscale_2025.pdf"

ESTIMATIONS = [
    {"id": "dgfip_tva_sous_declaration", "sphere": "fiscale",
     "objet": "Manque à gagner de TVA dû à la sous-déclaration des entreprises qui déclarent de la TVA",
     "producteur": "DGFiP, département des études et statistiques fiscales",
     "publication": "DGFiP Analyses n° 7 (septembre 2024), citée par le document de politique transversale annexé "
                    "au PLF 2026",
     "annee_publication": 2024, "annee_donnees": None,
     "annee_donnees_note": "année des données non précisée dans le document collecté",
     "perimetre": "TVA seulement ; entreprises qui déposent des déclarations de TVA. Les entreprises qui ne "
                  "déclarent pas ne sont pas couvertes. Erreurs et fraudes ne sont pas distinguées.",
     "methode": "Extrapolation des redressements fiscaux, rapprochée d'une expérimentation de contrôles "
                "aléatoires.",
     "unite": "Md€", "valeur": None, "valeur_basse": 6.0, "valeur_haute": 10.0,
     "repere": "4 à 5 % de la TVA effectivement collectée (repère donné par la source)",
     "citation": "il a ainsi établi que le manque à gagner de TVA dû à la sous-déclaration des entreprises "
                 "déclarant de la TVA serait compris entre 6 et 10 Md€, soit 4-5 % du montant de TVA effectivement "
                 "collecté. Cette estimation, fondée sur une extrapolation des redressements fiscaux, a été validée "
                 "par une expérimentation de contrôles aléatoires",
     "langue_citation": "fr", "source": "dpt_2026", "document": DPT_PDF, "page": 40},
    {"id": "commission_europeenne_ecart_tva", "sphere": "fiscale",
     "objet": "Écart de TVA de la France (« VAT compliance gap »)",
     "producteur": "Commission européenne (DG TAXUD)",
     "publication": "« VAT gap in Europe, report 2025 » (11 décembre 2025)",
     "annee_publication": 2025, "annee_donnees": 2023,
     "perimetre": "TVA seulement, France. L'écart réunit la fraude, l'évitement, les erreurs, les faillites et les "
                  "insolvabilités : ce n'est pas une mesure de la fraude seule.",
     "methode": "Différence entre la TVA théoriquement due si toutes les règles étaient respectées (calculée à "
                "partir des comptes nationaux) et la TVA effectivement collectée.",
     "unite": "M€", "valeur": 12121.0, "valeur_basse": None, "valeur_haute": None,
     "repere": "5,6 % de la TVA théoriquement due ; 206 049 M€ de TVA collectée en 2023 (chiffres de la source)",
     "citation": "In 2023, France collected a total of €206 049 million in VAT revenue. The VAT compliance gap was "
                 "estimated at €12 121 million, equivalent to 5.6% of the VAT Total Tax Liability (VTTL)",
     "langue_citation": "en", "source": "ce_ecart_tva_2025", "document": "vat_gap_en.html", "page": None},
    {"id": "urssaf_cotisations_eludees", "sphere": "sociale",
     "objet": "Fraude aux cotisations dans le champ de recouvrement des Urssaf",
     "producteur": "Urssaf Caisse nationale (Acoss), citée par le document de politique transversale annexé au "
                   "PLF 2026",
     "publication": "Document de politique transversale « Lutte contre l'évasion et la fraude fiscale », PLF 2026",
     "annee_publication": 2025, "annee_donnees": None,
     "annee_donnees_note": "évaluation actualisée en 2024 à partir de contrôles menés en 2022 et 2023",
     "perimetre": "Cotisations et contributions recouvrées par les Urssaf, entreprises du secteur privé du "
                  "régime général. Hors régime agricole.",
     "methode": "Extrapolation des résultats de contrôles aléatoires menés en 2022 et 2023 dans tous les secteurs "
                "d'activité.",
     "unite": "Md€", "valeur": None, "valeur_basse": 4.8, "valeur_haute": 6.3, "repere": None,
     "citation": "Celle-ci est estimée entre 4,8 et 6,3 milliards d’euros en ce qui concerne le champ de "
                 "recouvrement des URSSAF.",
     "langue_citation": "fr", "source": "dpt_2026", "document": DPT_PDF, "page": 13},
    {"id": "hcfips_fraude_securite_sociale", "sphere": "sociale",
     "objet": "Fraude à la sécurité sociale, cotisations et prestations",
     "producteur": "Haut Conseil du financement de la protection sociale (HCFiPS)",
     "publication": "Note annuelle de suivi et d'évaluation des fraudes sociales, synthèse (décembre 2025)",
     "annee_publication": 2025, "annee_donnees": None,
     "annee_donnees_note": "actualisation adoptée le 4 décembre 2025 ; l'année des données n'est pas donnée dans "
                           "la synthèse",
     "perimetre": "Périmètre « donnant lieu actuellement à évaluation » : cotisations (plus de 52 % du montant), "
                  "assurés (36 %), professionnels (12 %). Non couverts selon la source : travailleurs indépendants "
                  "classiques, certaines prestations d'assurance maladie, sous-déclarations des "
                  "micro-entrepreneurs.",
     "methode": "Addition par le Haut Conseil des évaluations produites par les caisses de sécurité sociale, "
                "chacune avec sa méthode (contrôles aléatoires ou extrapolations).",
     "unite": "Md€", "valeur": 14.0, "valeur_basse": None, "valeur_haute": None,
     "repere": "13 Md€ lors de l'évaluation précédente (chiffre de la source)",
     "citation": "dans le périmètre donnant lieu actuellement à évaluation, aboutit à un montant de fraudes de "
                 "14 Md€, contre 13 Md€ lors de l’évaluation précédente",
     "langue_citation": "fr", "source": "hcfips_2025", "document": HCFIPS_PDF, "page": 1},
    {"id": "hcfips_micro_entrepreneurs", "sphere": "sociale",
     "objet": "Cotisations et contributions non déclarées par les micro-entrepreneurs",
     "producteur": "HCFiPS, d'après l'Urssaf",
     "publication": "Note annuelle de suivi et d'évaluation des fraudes sociales, synthèse (décembre 2025)",
     "annee_publication": 2025, "annee_donnees": None,
     "annee_donnees_note": "année des données non précisée dans la synthèse",
     "perimetre": "Micro-entrepreneurs, y compris utilisateurs de plateformes. Montant non compris dans "
                  "l'évaluation de la fraude à la sécurité sociale : la source ne sépare pas ici fraude et erreur.",
     "methode": "Taux de cotisations non déclarées estimé entre 18,8 % et 23,6 % (source), appliqué aux "
                "cotisations de cette population.",
     "unite": "Md€", "valeur": None, "valeur_basse": 1.4, "valeur_haute": 1.8, "repere": None,
     "citation": "En termes de montants, les cotisations éludées représentent entre 1,4 et 1,8 milliard d’euros.",
     "langue_citation": "fr", "source": "hcfips_2025", "document": HCFIPS_PDF, "page": 2},
    {"id": "hcfips_recettes_fiscales_affectees", "sphere": "fiscale",
     "objet": "Manque à gagner sur les recettes fiscales affectées à la sécurité sociale (TVA, droits sur le "
              "tabac)",
     "producteur": "HCFiPS, d'après la DGFiP et la douane",
     "publication": "Note annuelle de suivi et d'évaluation des fraudes sociales, synthèse (décembre 2025)",
     "annee_publication": 2025, "annee_donnees": None,
     "annee_donnees_note": "année des données non précisée dans la synthèse",
     "perimetre": "Part de TVA et droits de consommation sur le tabac affectés à la sécurité sociale, recouvrés par "
                  "l'administration fiscale et la douane (d'où le classement en sphère fiscale). Erreurs et "
                  "fraudes ne sont pas distinguées. Ce montant recoupe l'estimation de TVA de la DGFiP : il ne "
                  "s'y ajoute pas.",
     "methode": "Application à la part affectée à la sécurité sociale du taux de 4 à 5 % de TVA non recouvrée "
                "(DGFiP) et des 18 % de volumes de tabac consommés hors fiscalité nationale (douane).",
     "unite": "Md€", "valeur": 5.5, "valeur_basse": None, "valeur_haute": None,
     "repere": "près de 3 Md€ pour la TVA et plus de 2,5 Md€ pour les droits sur le tabac (chiffres de la source)",
     "citation": "5,5 MD€ de manque à gagner sur les recettes fiscales affectées à la Sécurité Sociale",
     "langue_citation": "fr", "source": "hcfips_2025", "document": HCFIPS_PDF, "page": 3},
    {"id": "hcfips_erreurs_controle_assiette", "sphere": "sociale",
     "objet": "Manque à gagner révélé par les contrôles comptables d'assiette (erreurs, hors fraude)",
     "producteur": "HCFiPS, d'après l'Urssaf",
     "publication": "Note annuelle de suivi et d'évaluation des fraudes sociales, synthèse (décembre 2025)",
     "annee_publication": 2025, "annee_donnees": None,
     "annee_donnees_note": "année des données non précisée dans la synthèse",
     "perimetre": "Cotisations recouvrées par les Urssaf ; erreurs relevées par les contrôles comptables "
                  "d'assiette, que la source range hors de la fraude.",
     "methode": "Évaluation reprise par le Haut Conseil ; la synthèse ne détaille pas le calcul.",
     "unite": "Md€", "valeur": 3.5, "valeur_basse": None, "valeur_haute": None, "repere": None,
     "citation": "font apparaître un manque à gagner évalué à 3,5 Md€, constant par rapport aux exercices "
                 "précédents.",
     "langue_citation": "fr", "source": "hcfips_2025", "document": HCFIPS_PDF, "page": 3},
]

CONSTATS = [
    {"id": "cour_absence_estimation", "sphere": "fiscale", "producteur": "Cour des comptes",
     "texte": "La Cour des comptes relève qu'il n'existe pas d'estimation statistique d'ensemble de l'écart fiscal "
              "ni de la fraude fiscale en France.",
     "citation": "L’absence d’estimation statistique de l’écart fiscal et de la fraude fiscale constitue une "
                 "carence regrettable que la Cour a signalée à plusieurs reprises.",
     "source": "cour_des_comptes_2025", "document": CDC_PDF, "page": 8},
    {"id": "cour_ordre_de_grandeur", "sphere": "fiscale", "producteur": "Cour des comptes",
     "texte": "Selon la Cour, aucun ordre de grandeur d'ensemble ne peut être avancé ; elle cite elle-même "
              "l'intervalle de 30 à 130 Md€ pour dire qu'il ne peut pas être départagé.",
     "citation": "Nul ne peut aujourd’hui se hasarder à affirmer que ce montant est proche de 30 ou de 130 Md€ sur "
                 "un total de prélèvements obligatoires de 1 268 Md€ en 2024.",
     "source": "cour_des_comptes_2025", "document": CDC_PDF, "page": 28},
    {"id": "cour_fraude_et_ecart", "sphere": "fiscale", "producteur": "Cour des comptes",
     "texte": "La Cour distingue la fraude fiscale, intentionnelle, de l'écart fiscal, qui comprend aussi les "
              "erreurs de bonne foi et les aléas du recouvrement.",
     "citation": "Or il convient pour la clarté du débat public de distinguer la « fraude fiscale », dont la "
                 "définition exige un caractère intentionnel, et l’« écart fiscal », concept plus neutre, qui inclut "
                 "non seulement la fraude fiscale mais aussi les erreurs commises de bonne foi par les contribuables "
                 "ainsi que les aléas du recouvrement des impôts.",
     "source": "cour_des_comptes_2025", "document": CDC_PDF, "page": 8},
    {"id": "cour_efficacite_non_mesurable", "sphere": "fiscale", "producteur": "Cour des comptes",
     "texte": "Faute d'estimation, la Cour indique que l'efficacité des mesures de lutte ne peut pas être évaluée "
              "rigoureusement.",
     "citation": "Reste qu’en l’absence d’estimation de l’écart fiscal ou de la fraude fiscale, la plus ou moins "
                 "grande efficacité de ces initiatives ne peut pas être évaluée rigoureusement.",
     "source": "cour_des_comptes_2025", "document": CDC_PDF, "page": 7},
    {"id": "hcfips_non_addition", "sphere": "sociale", "producteur": "HCFiPS",
     "texte": "Le Haut Conseil demande de ne pas ajouter les manques à gagner (micro-entrepreneurs, recettes "
              "fiscales affectées, erreurs d'assiette) au montant évalué de la fraude.",
     "citation": "ils ne doivent pas être ajoutés aux montants des fraudes, dès lors que les dissimulations "
                 "intentionnelles n'y sont pas isolées",
     "source": "hcfips_2025", "document": HCFIPS_PDF, "page": 2},
    {"id": "hcfips_lecture_hausse", "sphere": "sociale", "producteur": "HCFiPS",
     "texte": "Le Haut Conseil indique que la hausse des montants détectés traduit un effort de contrôle accru, "
              "pas une hausse de la fraude.",
     "citation": "Cette évolution ne doit pas être lue comme la résultante d’une augmentation de la fraude, mais "
                 "comme la traduction d’un plus fort investissement des organismes sur le sujet",
     "source": "hcfips_2025", "document": HCFIPS_PDF, "page": 2},
]

# Montants détectés et recouvrés par les caisses de sécurité sociale (ordres de grandeur de la synthèse du HCFiPS).
SECURITE_SOCIALE = [
    {"id": "hcfips_detecte_2024", "notion": "notifie", "terme_source": "détecté",
     "libelle": "Fraudes détectées par les caisses de sécurité sociale", "annee": 2024, "valeur": 2.0, "unite": "Md€", "precision": "plus de",
     "citation": "Plus de 2 Md€ détectés en 2024", "page": 2},
    {"id": "hcfips_recouvre_2024", "notion": "encaisse", "terme_source": "recouvré", "libelle": "Sommes recouvrées par les caisses de sécurité "
     "sociale à la suite des fraudes détectées", "annee": 2024, "valeur": 680.0, "unite": "M€", "precision": None,
     "citation": "680 M€ recouvrés", "page": 2},
    {"id": "hcfips_recouvre_branche_recouvrement_2024", "notion": "encaisse", "terme_source": "recouvré",
     "libelle": "dont branche recouvrement (Urssaf)", "annee": 2024, "valeur": 100.0, "unite": "M€", "precision": "un peu plus de",
     "citation": "avec un peu plus de 100 M€ recouvrés", "page": 2},
]


def produire_estimations(collecte_le: str) -> tuple[dict, dict]:
    page_ce = [texte_html(LAKE / SOURCES["ce_ecart_tva_2025"]["fichier_collecte"])]
    manquantes, n = [], 0

    def verifier(e: dict) -> None:
        nonlocal n
        n += 1
        textes = page_ce if e["document"].endswith(".html") else textes_page(e["document"], e["page"])
        if not citation_presente(e["citation"], textes):
            manquantes.append(e["id"])

    for e in ESTIMATIONS + CONSTATS:
        verifier(e)
    for m in SECURITE_SOCIALE:
        verifier({**m, "document": HCFIPS_PDF})
    if manquantes:
        raise SystemExit(f"citation introuvable dans le document collecté : {manquantes}")

    estimations = []
    for e in ESTIMATIONS:
        d = {k: e.get(k) for k in ("id", "sphere", "objet", "producteur", "publication", "annee_publication",
                                   "annee_donnees", "perimetre", "methode", "unite", "valeur", "valeur_basse",
                                   "valeur_haute", "repere", "citation", "langue_citation")}
        if e.get("annee_donnees_note"):
            d["annee_donnees_note"] = e["annee_donnees_note"]
        d["notion"] = "estimation"
        d["source"] = {"id": e["source"], "url": SOURCES[e["source"]]["url"], "page": e["page"],
                       "document": f"data/lake/recouvrement/{SOURCES[e['source']]['fichier_collecte']}"}
        estimations.append(d)
    constats = [{"id": c["id"], "sphere": c["sphere"], "producteur": c["producteur"], "texte": c["texte"],
                 "citation": c["citation"],
                 "source": {"id": c["source"], "url": SOURCES[c["source"]]["url"], "page": c["page"],
                            "document": f"data/lake/recouvrement/{SOURCES[c['source']]['fichier_collecte']}"}}
                for c in CONSTATS]
    secu = [{**{k: x for k, x in m.items() if k != "page"}, "sphere": "sociale",
             "producteur": "HCFiPS, d'après les caisses de sécurité sociale",
             "source": {"id": "hcfips_2025", "url": SOURCES["hcfips_2025"]["url"], "page": m["page"],
                        "document": f"data/lake/recouvrement/{SOURCES['hcfips_2025']['fichier_collecte']}"}}
            for m in SECURITE_SOCIALE]
    verification = {"citations": n, "retrouvees": n,
                    "methode": "chaque citation est recherchée mot pour mot dans le document collecté "
                               "(data/lake/recouvrement/), à la page indiquée, sans tenir compte des retours à la "
                               "ligne ni des coupures de mots ; la production échoue sinon"}
    doc = {
        "millesime": "Estimations publiées de 2024 à 2025 (données 2023 et 2024 quand l'année est donnée)",
        "source": "Document de politique transversale « Lutte contre l'évasion et la fraude fiscale » (PLF 2026) ; "
                  "HCFiPS, synthèse de la note annuelle sur les fraudes sociales (décembre 2025) ; Cour des comptes, "
                  "« La lutte contre la fraude fiscale » (16 décembre 2025) ; Commission européenne, « VAT gap in "
                  "Europe, report 2025 »",
        "unite": "milliards ou millions d'euros selon l'estimation (champ unite)",
        "avertissement": "Une estimation n'est ni un montant notifié ni un montant encaissé. Chaque estimation a "
                         "son périmètre et sa méthode ; plusieurs se recouvrent en partie. Elles ne sont "
                         "additionnées ni entre elles ni d'une sphère à l'autre. La Cour des comptes relève qu'il "
                         "n'existe pas d'estimation d'ensemble de la fraude fiscale : aucune n'est donnée ici.",
        "collecte_le": collecte_le,
        "regle": "Aucune somme d'estimations n'est calculée. Les estimations de la sphère fiscale et de la sphère "
                 "sociale sont listées avec le même format, dans l'ordre : sphère fiscale puis sphère sociale, "
                 "puis année de publication, puis identifiant.",
        "ordre": {"regle": "Sphère (fiscale puis sociale, ordre alphabétique), année de publication, identifiant.",
                  "cles": ["sphere", "annee_publication", "id"]},
        "estimations": sorted(estimations, key=lambda e: (e["sphere"], e["annee_publication"], e["id"])),
        "estimation_ensemble_fraude_fiscale": {
            "valeur": None,
            "note": "Aucune estimation officielle d'ensemble n'est publiée (constat de la Cour des comptes, "
                    "décembre 2025). Les seules estimations officielles de la sphère fiscale portent sur la TVA.",
            "constats": ["cour_absence_estimation", "cour_ordre_de_grandeur"]},
        "constats": constats,
        "securite_sociale_detecte_recouvre": {
            "perimetre": "Toutes les branches de la sécurité sociale (recouvrement, maladie, famille, vieillesse), "
                         "y compris les prestations servies pour le compte de l'État et des départements par la "
                         "branche famille.",
            "methode": "Ordres de grandeur arrondis donnés par la synthèse du HCFiPS ; « détecté » désigne les "
                       "montants de fraude constatés par les caisses dans l'année, « recouvré » les sommes "
                       "récupérées dans l'année.",
            "montants": secu},
        "verification_documents": verification,
    }
    resume = {"estimations": len(estimations), "constats": len(constats), "citations": n}
    return doc, resume


# ----------------------------------------------------------------------------------------------------------------
# Index
# ----------------------------------------------------------------------------------------------------------------

def produire(sortie: Path = SORTIE) -> None:
    collecte_le = date_sources("recouvrement")
    fiscal, r_fiscal = produire_controle_fiscal(collecte_le)
    urssaf, r_urssaf = produire_controle_urssaf(collecte_le)
    impayes, r_impayes = produire_impayes(collecte_le)
    apurements, r_apurements = produire_apurements(collecte_le)
    estimations, r_estimations = produire_estimations(collecte_le)

    def ref(fichier: str, **champs) -> dict:
        return {"fichier": f"recouvrement/{fichier}", **champs}

    est = {e["id"]: e for e in estimations["estimations"]}
    secu = {m["id"]: m for m in estimations["securite_sociale_detecte_recouvre"]["montants"]}
    a_f, a_u = r_fiscal["annee"], r_urssaf["annee"]
    vues = [
        {"id": "controle_fiscal", "sphere": "fiscale", "titre": "Contrôle fiscal",
         "producteur": "DGFiP", "annee": a_f,
         "notifie": [
             {"libelle": "Droits et pénalités, contrôle sur place et sur pièces", "valeur": r_fiscal[
                 "notifie_droits_penalites_meur"], "unite": "M€", **ref("controle_fiscal.json",
                                                                       serie="dpt_total_droits_penalites")},
             {"libelle": "Crédits d'impôt et taxes non remboursés", "valeur": r_fiscal["credits_non_rembourses_meur"],
              "unite": "M€", **ref("controle_fiscal.json", serie="dpt_credits_non_rembourses")}],
         "encaisse": [
             {"libelle": "Encaissements à la suite du contrôle fiscal", "valeur": r_fiscal["encaisse_meur"],
              "unite": "M€", **ref("controle_fiscal.json", serie="dpt_encaissements_total")}],
         "restitution": [],
         "restitution_note": "Les dégrèvements prononcés après contrôle ne sont pas publiés dans les tableaux "
                             "repris ici.",
         "estimation": [],
         "estimation_note": "Aucune estimation officielle d'ensemble de la fraude fiscale (constat de la Cour des "
                            "comptes). Estimations partielles sur la TVA : voir recouvrement/estimations.json.",
         "estimations_partielles": ["dgfip_tva_sous_declaration", "commission_europeenne_ecart_tva"]},
        {"id": "controle_urssaf", "sphere": "sociale", "titre": "Contrôle des cotisations par les Urssaf",
         "producteur": "Urssaf", "annee": a_u,
         "notifie": [
             {"libelle": "Redressements à l'issue des contrôles d'assiette", "valeur": r_urssaf["redressements_eur"],
              "unite": "€", **ref("controle_urssaf.json", serie="controle.total.redressements_eur")}],
         "encaisse": [],
         "encaisse_note": "Les sommes encaissées à la suite des contrôles ne sont pas publiées dans les jeux "
                          "ouverts de l'Urssaf.",
         "restitution": [
             {"libelle": "Restitutions aux cotisants à l'issue des contrôles", "valeur": r_urssaf["restitutions_eur"],
              "unite": "€", **ref("controle_urssaf.json", serie="controle.total.restitutions_eur")}],
         "estimation": [
             {"libelle": est["hcfips_erreurs_controle_assiette"]["objet"],
              "valeur": est["hcfips_erreurs_controle_assiette"]["valeur"], "unite": "Md€",
              **ref("estimations.json", id="hcfips_erreurs_controle_assiette")}]},
        {"id": "travail_dissimule", "sphere": "sociale", "titre": "Lutte contre le travail dissimulé par les Urssaf",
         "producteur": "Urssaf", "annee": a_u,
         "notifie": [
             {"libelle": "Redressements pour travail dissimulé",
              "valeur": r_urssaf["travail_dissimule_redressements_eur"], "unite": "€",
              **ref("controle_urssaf.json", serie="travail_dissimule.total.redressements_eur")}],
         "encaisse": [
             {"libelle": "Sommes recouvrées par la branche recouvrement à la suite des fraudes détectées (ordre de "
              "grandeur du HCFiPS)", "valeur": secu["hcfips_recouvre_branche_recouvrement_2024"]["valeur"],
              "unite": "M€", "precision": secu["hcfips_recouvre_branche_recouvrement_2024"]["precision"],
              **ref("estimations.json", id="hcfips_recouvre_branche_recouvrement_2024")}],
         "restitution": [],
         "restitution_note": "Aucune restitution n'est publiée dans le jeu sur le travail dissimulé.",
         "estimation": [
             {"libelle": est["urssaf_cotisations_eludees"]["objet"], "valeur_basse": est[
                 "urssaf_cotisations_eludees"]["valeur_basse"], "valeur_haute": est["urssaf_cotisations_eludees"][
                 "valeur_haute"], "unite": "Md€", **ref("estimations.json", id="urssaf_cotisations_eludees")}]},
        {"id": "securite_sociale", "sphere": "sociale", "titre": "Fraudes à la sécurité sociale, toutes branches",
         "producteur": "HCFiPS, d'après les caisses de sécurité sociale", "annee": 2024,
         "notifie": [
             {"libelle": secu["hcfips_detecte_2024"]["libelle"], "valeur": secu["hcfips_detecte_2024"]["valeur"],
              "unite": "Md€", "precision": secu["hcfips_detecte_2024"]["precision"],
              **ref("estimations.json", id="hcfips_detecte_2024")}],
         "encaisse": [
             {"libelle": secu["hcfips_recouvre_2024"]["libelle"], "valeur": secu["hcfips_recouvre_2024"]["valeur"],
              "unite": "M€", **ref("estimations.json", id="hcfips_recouvre_2024")}],
         "restitution": [],
         "restitution_note": "Non publié dans la synthèse du HCFiPS.",
         "estimation": [
             {"libelle": est["hcfips_fraude_securite_sociale"]["objet"],
              "valeur": est["hcfips_fraude_securite_sociale"]["valeur"], "unite": "Md€",
              **ref("estimations.json", id="hcfips_fraude_securite_sociale")}]},
    ]

    index = {
        "millesime": f"Contrôle fiscal {r_fiscal['premiere_annee']} à {a_f} ; contrôles des Urssaf "
                     f"{r_urssaf['premiere_annee']} à {a_u} ; taux d'impayés {r_impayes['premier_mois']} à "
                     f"{r_impayes['dernier_mois']} ; comptes de l'État {r_apurements['premiere_annee']} à "
                     f"{r_apurements['annee']} ; estimations publiées en 2024 et 2025",
        "source": "DGFiP (annuaires statistiques, document de politique transversale du PLF 2026, comptabilité "
                  "générale de l'État) ; Urssaf (open.urssaf.fr) ; HCFiPS ; Cour des comptes ; Commission "
                  "européenne",
        "unite": "selon le fichier : millions d'euros (contrôle fiscal), euros (Urssaf, comptes de l'État), % "
                 "(taux d'impayés), milliards ou millions d'euros (estimations)",
        "avertissement": "Trois notions sont séparées dans tous les fichiers : montant notifié, montant encaissé, "
                         "estimation. Elles ne mesurent pas la même chose et ne se comparent pas directement. La "
                         "sphère fiscale et la sphère sociale ne sont ni additionnées ni rapportées l'une à "
                         "l'autre.",
        "collecte_le": collecte_le,
        "notions": NOTIONS,
        "regles": REGLES,
        "spheres": {"fiscale": "Impôts et taxes contrôlés et recouvrés par la DGFiP",
                    "sociale": "Cotisations, contributions et prestations de sécurité sociale (Urssaf, caisses)"},
        "vues": vues,
        "ordre": {"regle": "Vues dans l'ordre : sphère fiscale puis sphère sociale (ordre alphabétique), puis "
                           "identifiant. Aucun total entre vues.",
                  "cles": ["sphere", "id"]},
        "fichiers": [
            ref("controle_fiscal.json", contenu="DGFiP : droits et pénalités notifiés, encaissements, opérations, "
                "plaintes, taux de recouvrement", sphere="fiscale", annees=[r_fiscal["premiere_annee"], a_f]),
            ref("controle_urssaf.json", contenu="Urssaf : redressements, restitutions, régularisations, travail "
                "dissimulé, par type d'action et par organisme", sphere="sociale",
                annees=[r_urssaf["premiere_annee"], a_u]),
            ref("impayes.json", contenu="Urssaf : taux d'impayés mensuels, métropole et régions", sphere="sociale",
                annees=[int(r_impayes["premier_mois"][:4]), int(r_impayes["dernier_mois"][:4])]),
            ref("apurements_etat.json", contenu="État : admissions en non-valeur et décisions gracieuses",
                sphere="fiscale", annees=[r_apurements["premiere_annee"], r_apurements["annee"]]),
            ref("estimations.json", contenu="Estimations publiées, constats de la Cour des comptes et du HCFiPS, "
                "montants détectés et recouvrés par la sécurité sociale", sphere="fiscale et sociale, séparées",
                annees=[2023, 2025]),
        ],
        "reperes": {"controle_fiscal": r_fiscal, "controle_urssaf": r_urssaf, "impayes": r_impayes,
                    "apurements_etat": r_apurements, "estimations": r_estimations},
        "sources": [{"id": k, **{c: v for c, v in s.items() if c != "fichier_collecte"},
                     "document": f"data/lake/recouvrement/{s['fichier_collecte']}"}
                    for k, s in sorted(SOURCES.items())],
        "sources_inaccessibles": SOURCES_INACCESSIBLES,
        "confidentialite": "Aucune personne physique ni aucun contribuable ou cotisant n'apparaît : les sources ne "
                           "publient que des agrégats (national, région, organisme de recouvrement). Rien n'a eu à "
                           "être agrégé ou retiré.",
        "limites": [
            "Les montants notifiés par la DGFiP après 2019 sont lus dans un tableau PDF, pas dans un jeu de données "
            "ouvert.",
            "L'Urssaf ne publie pas en données ouvertes les sommes encaissées à la suite de ses contrôles.",
            "Les contrôles de la douane, du régime agricole et des caisses de prestations ne sont pas détaillés ; "
            "seuls les ordres de grandeur de la synthèse du HCFiPS couvrent les caisses de prestations.",
            "Les admissions en non-valeur et décisions gracieuses portent sur toutes les créances, pas seulement "
            "sur celles nées d'un contrôle.",
            "Les séries par pays et par année de l'écart de TVA de la Commission européenne ne sont pas reprises "
            "(classeur inaccessible) : seule la valeur de la France pour 2023 l'est.",
        ],
        "verification_documents": estimations["verification_documents"],
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    vues.sort(key=lambda x: (x["sphere"], x["id"]))

    _ecrire(sortie / "controle_fiscal.json", fiscal)
    _ecrire(sortie / "controle_urssaf.json", urssaf)
    _ecrire(sortie / "impayes.json", impayes)
    _ecrire(sortie / "apurements_etat.json", apurements)
    _ecrire(sortie / "estimations.json", estimations)
    _ecrire(sortie / "index.json", index)


def _ecrire(chemin: Path, doc: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("produire")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
