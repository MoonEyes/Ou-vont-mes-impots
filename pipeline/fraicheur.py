"""Fraîcheur des données : pour chaque source lue par le site, date de dernière collecte, millésime publié, date de
publication déclarée par la source, prochaine publication attendue (calendrier officiel, sinon null) et statut.

Entrées (lecture seule) :
  collecte/catalogue.json            sources déclarées de l'entrepôt (identifiant, type, portail, jeu, titre, licence) et
                                     sources non collectables
  pipeline/sources.json              sources de l'étape « base » (data/raw, téléchargées par pipeline/fetch.py)
  pipeline/entrees_lac.json          sources lues par chaque étape (relevé de `pipeline/tout.py inventorier`)
  data/lake/manifest.json            dernière collecte de chaque source : date, statut, erreur, signature, en-têtes HTTP
  data/raw/<id>.schema.json          date de modification déclarée par la source pour la version utilisée (« base »)
  data/lake/_cache/fraicheur/verifications.json
                                     vérification des sources de l'étape « base » faite par `collecter`
  data/lake/_cache/tout/etat.json    statut de chaque étape dans le passage en cours (pipeline/tout.py)
  site/data/mise_a_jour.json         rapport du dernier passage écrit : statut des étapes, sources inaccessibles
  site/data/<sortie>/index.json      millésime publié par chaque page (en-tête), millésime ou date de collecte par source
                                     quand la page les publie, sources signalées inaccessibles par la page
  .github/workflows/data.yml         jour et heure de la mise à jour hebdomadaire
Sortie :
  site/data/fraicheur/index.json     (contrat d'interface, section « Fraîcheur des données »)

Commandes :
  python pipeline/fraicheur.py collecter   # réseau : vérifie les 12 sources de pipeline/sources.json (métadonnées
                                           # seulement) ; un refus 401/403/429/451 est noté, jamais contourné
  python pipeline/fraicheur.py produire [--sortie DOSSIER]   # sans réseau
  python pipeline/fraicheur.py             # les deux (étape « fraicheur » de pipeline/tout.py, avant le datapackage)

Règles :
  - un statut est un constat daté, jamais un jugement sur la source ou son producteur ;
  - « en retard » ne s'appuie que sur un calendrier officiel (loi organique, règlement) ou sur une version plus récente
    déclarée par la source elle-même ; sans calendrier connu, la prochaine publication est null ;
  - « inaccessible » : refus ou indisponibilité constatés à la dernière collecte (401, 403, 429, 451, 5xx, délai,
    coupure) ; rien n'est contourné et la dernière version obtenue reste publiée ;
  - aucune date n'est inventée : une date inconnue est null, avec l'explication ;
  - toute date écrite vient des entrées (manifeste, vérifications, rapport) et la date de référence de
    pipeline/reproductible.py : deux productions sur les mêmes entrées sont identiques octet pour octet.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ICI = Path(__file__).resolve().parent
ROOT = ICI.parent
sys.path.insert(0, str(ICI))
import reproductible  # noqa: E402
import tout  # noqa: E402

SITE = ROOT / "site" / "data"
SORTIE = SITE / "fraicheur"
CACHE = ROOT / "data" / "lake" / "_cache" / "fraicheur"
VERIFICATIONS = CACHE / "verifications.json"
UA = "ou-vont-mes-impots-collecte/0.3 (projet citoyen open source, collecte de donnees ouvertes)"
EXCLUES = ("fraicheur", "datapackage")   # étapes sans source propre

# --- Statuts ------------------------------------------------------------------------------------------------------

STATUTS = {
    "a_jour": {
        "libelle": "à jour",
        "definition": "La dernière collecte a abouti et aucune nouvelle édition n'était attendue à la date de référence "
                      "selon le calendrier officiel connu. Sans calendrier connu, la collecte vérifie que la version "
                      "utilisée est celle publiée par la source ce jour-là.",
    },
    "en_retard": {
        "libelle": "en retard sur le calendrier",
        "definition": "Une nouvelle édition était attendue avant la date de référence selon un calendrier officiel "
                      "(loi organique, règlement), ou la source déclare une version plus récente que celle utilisée, "
                      "et cette édition ne figure pas dans les données collectées. Cela décrit l'état de la collecte, "
                      "pas la qualité de la source.",
    },
    "inaccessible": {
        "libelle": "inaccessible au dernier passage",
        "definition": "Refus ou indisponibilité de la source constatés lors de la dernière collecte (accès refusé, "
                      "limite de requêtes, serveur indisponible, délai dépassé, transfert coupé). Rien n'est contourné : "
                      "la dernière version obtenue reste publiée.",
    },
    "non_verifiee": {
        "libelle": "non vérifiée",
        "definition": "Aucune collecte datée et réussie n'est enregistrée pour cette source (collecte faite par le "
                      "module de la page sans trace datée, collecte en erreur ou jamais lancée) : le site ne peut pas "
                      "dire si elle est à jour.",
    },
}
ORDRE_STATUTS = list(STATUTS)

# Refus ou indisponibilité (mêmes motifs que pipeline/tout.py, plus les transferts tronqués de collecte/collecte.py).
ACCES = re.compile(tout.RESEAU.pattern + r"|transfert (?:tronqu|interrompu|coup)|incomplet \(transfert|budget de temps",
                   re.I)

# --- Calendriers officiels -----------------------------------------------------------------------------------------

FICHE_AN = ("https://www.assemblee-nationale.fr/dyn/contenu/telechargement/629134/file/"
            "Fiche%2053%20-%20Examen%20LF.pdf")
CALENDRIERS = {
    "plf": {
        "libelle": "Projet de loi de finances de l'année et ses annexes",
        "regle": "dépôt au plus tard le premier mardi d'octobre de l'année qui précède celle du budget",
        "reference": "Loi organique relative aux lois de finances, article 39 ; Assemblée nationale, fiche de synthèse "
                     "n° 53 « L'examen des lois de finances » (septembre 2022)",
        "url": FICHE_AN,
    },
    "plrg": {
        "libelle": "Projet de loi relatif aux résultats de la gestion et portant approbation des comptes de l'année "
                   "(ancienne loi de règlement) et rapports annuels de performance",
        "regle": "dépôt avant le 1er mai de l'année qui suit l'exécution du budget (avant le 1er juin jusqu'à "
                 "l'exécution 2021)",
        "reference": "Loi organique relative aux lois de finances, articles 46 et 54, modifiés par la loi organique "
                     "n° 2021-1836 du 28 décembre 2021 ; Assemblée nationale, fiche de synthèse n° 53 (septembre 2022)",
        "url": FICHE_AN,
    },
    "placss": {
        "libelle": "Projet de loi d'approbation des comptes de la sécurité sociale de l'année",
        "regle": "dépôt avant le 1er juin de l'année qui suit celle des comptes (depuis les comptes 2022)",
        "reference": "Code de la sécurité sociale, article LO 111-6 (loi organique n° 2022-354 du 14 mars 2022) ; "
                     "Sénat, rapport n° 789 (2022-2023)",
        "url": "https://www.senat.fr/rap/l22-789/l22-7898.html",
    },
    "pde": {
        "libelle": "Notification du déficit et de la dette publics à la Commission européenne, publiée par Eurostat",
        "regle": "publication au plus tard trois semaines après les notifications des États membres, faites avant le "
                 "1er avril et avant le 1er octobre",
        "reference": "Règlement (CE) n° 479/2009 du Conseil, articles 3 et 14",
        "url": "https://eur-lex.europa.eu/eli/reg/2009/479",
    },
}

# Publications récurrentes rattachées à un calendrier officiel : famille, libellé, calendrier, motifs d'identifiant
# (le groupe nommé « a » donne l'édition ; sans groupe, l'édition est lue dans le jeu ou le titre). Une nouvelle édition
# d'une famille s'y rattache d'elle-même si son identifiant suit le motif ; une nouvelle publication s'ajoute ici.
FAMILLES = [
    ("budget_vert", "Budget vert (crédits par action : exécution, budget voté, projet)", "plf",
     [r"budget_etat_vert", r"etat_budget_vert_(?P<a>\d{4})", r"economie__plf(?P<a>\d{2})-budget-vert",
      r"economie__budgetvert_plf(?P<a>\d{4})_opendata_vf"]),
    ("budget_vert_justification", "Budget vert, justification des crédits et des taxes affectées", "plf",
     [r"economie__plf(?P<a>\d{2})-budget-vert-justification-des-credits-budgetaires-et-des-taxes-affectees"]),
    ("plf_destination_nature", "Dépenses du projet de loi de finances par destination et par nature", "plf",
     [r"budget_etat_plf", r"etat_plf(?P<a>\d{2})_destination_nature"]),
    ("jaune_operateurs", "Annexe « Opérateurs de l'État » (jaune)", "plf",
     [r"etat_jaune_operateurs_plf(?P<a>\d{4})", r"etat_operateurs_(?P<a>\d{4})",
      r"datagouv__projet-de-loi-de-finances-pour-(?P<a>\d{4})-plf-\d{4}-jaune-operateurs-de-letat-liste-des-"
      r"operateurs-et-categories"]),
    ("jaune_associations", "Annexe « Effort financier de l'État en faveur des associations » (jaune)", "plf",
     [r"assoc_jaune_plf(?P<a>\d{4})", r"benef_associations_plf(?P<a>\d{2})"]),
    ("jaune_cabinets", "Annexe « Personnels affectés dans les cabinets ministériels » (jaune)", "plf",
     [r"fp_jaune_cabinets_plf(?P<a>\d{4})"]),
    ("jaune_conseils", "Annexe « Recours aux conseils extérieurs » (jaune)", "plf",
     [r"fp_jaune_conseils_plf(?P<a>\d{4})"]),
    ("depenses_fiscales", "Évaluation des voies et moyens, tome II (dépenses fiscales)", "plf",
     [r"fiscalite_voies_moyens_t2_plf(?P<a>\d{4})", r"economie__plf(?P<a>\d{4})_voies_et_moyens_t2_liste_des_depenses_"
      r"fiscales", r"economie__projet-de-loi-de-finances-pour-(?P<a>\d{4})-plf-\d{4}-donnees-du-plf-et-des-annexes-proje",
      r"niches_vm"]),
    ("taxes_affectees", "Évaluation des voies et moyens, tome I (taxes affectées)", "plf",
     [r"fiscalite_taxes_affectees_plf(?P<a>\d{4})"]),
    ("participations_recettes", "Recettes du budget général : produits des participations de l'État", "plf",
     [r"etat_actionnaire_plf(?P<a>\d{2})_recettes_bg"]),
    ("participations_compte", "Recettes du compte « Participations financières de l'État »", "plf",
     [r"etat_actionnaire_(?:plf|lfi)(?P<a>\d{2})_recettes_cas"]),
    ("participations_depenses", "Dépenses du compte « Participations financières de l'État »", "plf",
     [r"etat_actionnaire_plf(?P<a>\d{2})_depenses_destination"]),
    ("pensions_recettes", "Recettes du compte d'affectation spéciale Pensions", "plf",
     [r"retraites_plf(?P<a>\d{2})_recettes_cas"]),
    ("pensions_depenses", "Dépenses selon destination (compte Pensions, régimes sociaux et de retraite)", "plf",
     [r"retraites_plf(?P<a>\d{2})_depenses_destination"]),
    ("resultats_gestion", "Résultats de la gestion : crédits exécutés par programme (annexes)", "plrg",
     [r"plrg_(?P<a>\d{4})_cp", r"etat_plrg_(?P<a>\d{4})", r"etat_plr_(?P<a>\d{4})", r"etat_actionnaire_plrg_annexes"]),
    ("performance", "Rapports annuels de performance", "plrg", [r"etat_performance_rap_(?P<a>\d{4})"]),
    ("placss_texte", "Approbation des comptes de la sécurité sociale : texte", "placss",
     [r"secu_placss(?P<a>\d{4})_texte"]),
    ("placss_annexe1", "Approbation des comptes de la sécurité sociale : annexe 1", "placss",
     [r"secu_placss(?P<a>\d{4})_annexe1\w*"]),
    ("placss_annexe3", "Approbation des comptes de la sécurité sociale : annexe 3", "placss",
     [r"secu_placss(?P<a>\d{4})_annexe3\w*"]),
    ("placss_annexe4", "Approbation des comptes de la sécurité sociale : annexe 4", "placss",
     [r"secu_placss(?P<a>\d{4})_annexe4\w*"]),
    ("placss_annexe7", "Approbation des comptes de la sécurité sociale : annexe 7", "placss",
     [r"secu_placss(?P<a>\d{4})_annexe7\w*"]),
    ("deficit_dette_ue", "Déficit et dette publics notifiés (Eurostat, procédure concernant les déficits excessifs)",
     "pde", [r"deficit_france", r"eu_deficit_dette", r"eu_gov_10dd_edpt1_ue27"]),
]
_FAMILLES = [(f, lib, cal, [re.compile(rf"^(?:{m})$") for m in motifs]) for f, lib, cal, motifs in FAMILLES]

# --- Sorties lues pour le millésime des sources de l'étape « base » (pipeline/transform.py) -------------------------

BASE_SORTIES = {
    "budget_etat_vert": ["arbre/racine.json", "arbre_lfi2025/racine.json"],
    "plrg_2024_cp": ["arbre/racine.json"],
    "plrg_2025_cp": ["arbre_lfi2025/racine.json"],
    "situation_budgetaire": ["deficit.json"],
    "situation_budgetaire_lois": ["deficit.json"],
    "budget_etat_plf": ["nature_etat.json", "arbre_plf2025_nature/racine.json"],
    "taux_communes": ["communes/01.json"],
    "cofog_france": ["cofog.json"],
    "cofog_administrations": ["arbre_administrations/racine.json"],
    "deficit_france": ["deficit.json"],
    "comptes_administrations": ["administrations.json"],
    "recettes_impots": ["recettes.json"],
}
# Nom de chaque page en langage courant (le titre technique de pipeline/tout.py reste publié dans `titre`).
LIBELLES_ETAPES = {
    "base": "Budget de l'État, comptes publics européens et taux des communes",
    "beneficiaires": "Qui reçoit l'argent : nature, effectifs et bénéficiaires par programme",
    "operateurs": "Opérateurs de l'État",
    "vie_politique": "Vie politique",
    "realisations": "Ce qui a été fait : prévu, dépensé, indicateurs",
    "decisions": "Votes, amendements et mouvements de crédits",
    "prelevements": "Prélèvements et leurs destinataires",
    "secu": "Sécurité sociale et protection sociale",
    "niches": "Dépenses fiscales et exonérations de cotisations",
    "ue": "La France et l'Union européenne",
    "dette": "Dette publique",
    "tracabilite": "Traçabilité de chaque euro",
    "local": "Budget de ma commune et collectivités locales",
    "controle": "Contrôle, représentation d'intérêts et aides aux entreprises",
    "local_fonctions": "Dépenses des collectivités par fonction",
    "subventions": "Subventions par convention",
    "territoires": "Territoires : dotations d'investissement, logement social, aide sociale",
    "prestations": "Prestations versées aux ménages",
    "europe_comparaison": "La France et ses voisins européens",
    "aide_developpement": "Aide publique au développement",
    "associations": "Associations, fonds et fondations",
    "education_recherche": "Éducation et recherche",
    "etat_actionnaire": "L'État actionnaire",
    "fonction_publique": "Fonction publique",
    "formation": "Formation professionnelle",
    "justice_defense": "Justice et défense",
    "local_satellites": "Syndicats, action sociale communale, mobilité et eau",
    "marches": "Marchés publics",
    "numerique_etat": "Numérique de l'État",
    "outremer": "Collectivités d'outre-mer",
    "recouvrement": "Contrôle et recouvrement des impôts et cotisations",
    "retraites": "Retraites par régime",
    "sante_etablissements": "Établissements de santé et médico-sociaux",
    "solidarites_departements": "Solidarités des départements",
    "fonds_europeens": "Fonds européens en France",
    "aides_entreprises": "Aides aux entreprises",
    "logement": "Logement",
    "revenus_communes": "Revenus des communes",
    "fraicheur": "Fraîcheur des données",
    "datapackage": "Métadonnées de réutilisation des données",
}
# Lexique neutre (docs/lexique_neutre.json) appliqué aux notes reprises du catalogue et des pages : substitutions
# explicites, sans changer le sens (« niche » toujours avec sa définition).
SUBSTITUTIONS = [
    (re.compile(r"(?<!appelées )\bniches sociales\b"), "exonérations de cotisations (souvent appelées niches sociales)"),
    (re.compile(r"(?<!appelées )\bniches fiscales\b"), "dépenses fiscales (souvent appelées niches fiscales)"),
    (re.compile(r"\btrop lents\b"), "lents"),
]


def neutraliser(texte: str) -> str:
    for rx, par in SUBSTITUTIONS:
        texte = rx.sub(par, texte)
    return texte


PORTAILS_LIBELLE = {"economie": "data.economie.gouv.fr", "datagouv": "data.gouv.fr", "ofgl": "data.ofgl.fr",
                    "esr": "data.enseignementsup-recherche.gouv.fr", "eurostat": "Eurostat", "drees": "DREES",
                    "caf": "CNAF (data.caf.fr)", "urssaf": "Urssaf", "cdc": "Caisse des dépôts", "ameli": "Assurance "
                    "maladie (data.ameli.fr)", "education": "data.education.gouv.fr", "atih": "ATIH"}
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
        "décembre"]
JOURS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"]

RECHERCHE_PREALABLE = {
    "date": "2026-11-18",
    "conclusion": "Aucun outil public ne donne une prochaine publication fiable pour ces sources : les dates déclarées "
                  "par les producteurs sur data.gouv.fr sont antérieures à leur dernière mise à jour. Le module reprend "
                  "les traces de collecte du dépôt (manifeste, rapport de passage) et les calendriers fixés par les "
                  "textes officiels ; il est écrit pour le dépôt.",
    "trouvailles": [
        {"nom": "API data.gouv.fr (udata 17.26.0) : champs frequency, frequency_date, quality.update_fulfilled_in_time",
         "url": "https://www.data.gouv.fr/api/1/datasets/", "licence": "MIT (udata, PyPI)",
         "dernier_commit": "2026-11-13",
         "verdict": "inspiration seulement : relevé du 18/11/2026 sur les 49 jeux data.gouv.fr du catalogue, la date de "
                    "prochaine mise à jour déclarée est antérieure à la dernière mise à jour pour 49 jeux sur 49 ; "
                    "l'indicateur update_fulfilled_in_time ne donne pas de date"},
        {"nom": "Métadonnées Opendatasoft (metas.default.modified, metas.dcat.accrualperiodicity)",
         "url": "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/", "licence": "Licence Ouverte 2.0",
         "dernier_commit": None,
         "verdict": "réutilisable tel quel : date de modification lue dans la signature du manifeste de collecte et dans "
                    "data/raw ; la périodicité déclarée n'est pas une date et n'est pas reprise"},
        {"nom": "Calendrier des publications d'Eurostat (calendrier internet, iCal)",
         "url": "https://ec.europa.eu/eurostat/news/internet-calendar", "licence": "réutilisation libre avec mention",
         "dernier_commit": None,
         "verdict": "à adapter : dates exactes, mais le calendrier de l'année suivante paraît en janvier ; le délai fixé "
                    "par le règlement (CE) n° 479/2009 est retenu"},
        {"nom": "OCHA-DAP/hdx-data-freshness (statuts fresh, due, overdue, delinquent selon la fréquence déclarée)",
         "url": "https://github.com/OCHA-DAP/hdx-data-freshness", "licence": "MIT",
         "dernier_commit": "2023-05-30 (version 2.0.0 sur PyPI)",
         "verdict": "inspiration seulement : statuts fondés sur une fréquence déclarée, peu fiable ici ; le site s'appuie "
                    "sur des calendriers officiels"},
        {"nom": "dbt-labs/dbt-core, « source freshness » (warn_after, error_after sur une date de chargement)",
         "url": "https://github.com/dbt-labs/dbt-core", "licence": "Apache-2.0",
         "dernier_commit": "2026-11-12 (version 1.12.7 sur PyPI)",
         "verdict": "inspiration seulement : seuils de durée choisis par l'utilisateur, pas de calendrier officiel"},
        {"nom": "pipeline/datapackage.py (lignée des sources) et pipeline/tout.py (étapes, motifs de refus réseau)",
         "url": "https://github.com/MoonEyes/Ou-vont-mes-impots", "licence": "MIT", "dernier_commit": "2026-11-17",
         "verdict": "réutilisable tel quel : étapes, sorties et motifs de refus importés de pipeline/tout.py ; règle "
                    "d'adresse des jeux reprise de pipeline/datapackage.py"},
    ],
}


# --- Dates ----------------------------------------------------------------------------------------------------------

def _instant(x) -> datetime | None:
    """Date-heure UTC d'une chaîne ISO 8601, RFC 1123 (en-tête HTTP) ou « AAAA-MM-JJ HH:MM » ; None sinon."""
    if not isinstance(x, str) or not x.strip():
        return None
    s = x.strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(s)
        except (TypeError, ValueError, IndexError):
            return None
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _jour(x) -> str | None:
    d = _instant(x)
    return d.date().isoformat() if d else None


def date_longue(iso: str | None) -> str:
    """« 6 octobre 2026 » ; « date inconnue » si absente."""
    if not iso:
        return "date inconnue"
    d = date.fromisoformat(iso[:10])
    return f"{'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]} {d.year}"


def premier_mardi_octobre(annee: int) -> date:
    d = date(annee, 10, 1)
    return d + timedelta(days=(1 - d.weekday()) % 7)


def echeance(calendrier: str, edition: int) -> date:
    """Date limite de dépôt de l'édition `edition` (année du budget, de l'exécution ou des comptes)."""
    if calendrier == "plf":
        return premier_mardi_octobre(edition - 1)
    if calendrier == "plrg":
        return date(edition + 1, 4, 30) if edition >= 2022 else date(edition + 1, 5, 31)
    if calendrier == "placss":
        return date(edition + 1, 5, 31)
    raise ValueError(calendrier)


def prochaine_notification_pde(publication: str | None, collecte: str | None) -> date | None:
    """Prochaine publication des notifications (22 avril, 22 octobre : trois semaines après le 1er avril et le 1er
    octobre). Après une publication datée P : première fenêtre ouverte après P (une publication faite dans une fenêtre
    est cette notification). Sans date de publication, après une collecte datée C : premier délai après C."""
    if publication:
        p = date.fromisoformat(publication)
        for annee in (p.year, p.year + 1):
            for mois in (4, 10):
                if date(annee, mois, 1) > p:
                    return date(annee, mois, 1) + timedelta(days=21)
    if collecte:
        c = date.fromisoformat(collecte)
        for annee in (c.year, c.year + 1):
            for mois in (4, 10):
                if date(annee, mois, 22) > c:
                    return date(annee, mois, 22)
    return None


def libelle_edition(calendrier: str, edition: int | None, quand: date | None = None) -> str:
    if calendrier == "plf":
        return f"projet de loi de finances pour {edition}"
    if calendrier == "plrg":
        return f"résultats de la gestion {edition} (exécution du budget {edition})"
    if calendrier == "placss":
        return f"approbation des comptes de la sécurité sociale {edition}"
    return f"notification d'{'avril' if quand and quand.month == 4 else 'octobre'} {quand.year if quand else ''}".strip()


# --- Entrées --------------------------------------------------------------------------------------------------------

@dataclass
class Etape:
    id: str
    titre: str
    sorties: list[str]          # relatives à site/data
    modules: list[str]          # noms des modules pipeline/<module>.py appelés


@dataclass
class Entrees:
    catalogue: dict
    config: dict
    lecture: dict
    manifeste: dict
    date_reference: str
    etapes: list[Etape]
    site: Path
    lake: Path
    rapport: dict = field(default_factory=dict)
    etat_passage: dict = field(default_factory=dict)
    schemas_bruts: dict = field(default_factory=dict)
    verifications: dict = field(default_factory=dict)
    portails: dict = field(default_factory=dict)
    workflow: str = ""


def _lire_json(p: Path, defaut=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def etapes_du_pipeline() -> list[Etape]:
    out = []
    for e in tout.ordre():
        mods = sorted({Path(c[0]).stem for c in e.collecter + e.produire})
        out.append(Etape(e.id, e.titre, [s.removeprefix("site/data/") for s in e.sorties if s.startswith("site/data/")],
                         mods))
    return out


def charger(racine: Path = ROOT) -> Entrees:
    manifeste = _lire_json(racine / "data" / "lake" / "manifest.json")
    if not isinstance(manifeste, dict):
        raise SystemExit("data/lake/manifest.json absent : lancer la collecte (python collecte/collecte.py) ; "
                         "dernière version publiée gardée")
    catalogue = _lire_json(racine / "collecte" / "catalogue.json", {})
    portails = dict(catalogue.get("portails", {}))
    for cle, p in (_lire_json(racine / "collecte" / "portails_ods.json", {}) or {}).get("portails", {}).items():
        portails.setdefault(cle, p.get("base"))
    bruts = {}
    for p in sorted((racine / "data" / "raw").glob("*.schema.json")):
        d = _lire_json(p)
        if isinstance(d, dict):
            bruts[p.name.removesuffix(".schema.json")] = d
    workflow = racine / ".github" / "workflows" / "data.yml"
    return Entrees(
        catalogue=catalogue,
        config=_lire_json(racine / "pipeline" / "sources.json", {}),
        lecture=_lire_json(racine / "pipeline" / "entrees_lac.json", {}) or {},
        manifeste=manifeste,
        date_reference=reproductible.date_sources() if racine == ROOT else _date_manifeste(manifeste),
        etapes=etapes_du_pipeline(),
        site=racine / "site" / "data",
        lake=racine / "data" / "lake",
        rapport=_lire_json(racine / "site" / "data" / "mise_a_jour.json", {}) or {},
        etat_passage=_lire_json(racine / "data" / "lake" / "_cache" / "tout" / "etat.json", {}) or {},
        schemas_bruts=bruts,
        verifications=_lire_json(racine / "data" / "lake" / "_cache" / "fraicheur" / "verifications.json", {}) or {},
        portails=portails,
        workflow=workflow.read_text(encoding="utf-8") if workflow.exists() else "",
    )


def _date_manifeste(manifeste: dict) -> str:
    """Même règle que pipeline/reproductible.py (SOURCE_DATE_EPOCH, sinon dernière collecte), pour un autre dépôt."""
    if os.environ.get("SOURCE_DATE_EPOCH"):
        return datetime.fromtimestamp(int(os.environ["SOURCE_DATE_EPOCH"]), timezone.utc).date().isoformat()
    jours = [_jour(e.get("collecte_le")) for e in manifeste.values() if isinstance(e, dict)]
    jours = [j for j in jours if j]
    return max(jours) if jours else datetime.now(timezone.utc).date().isoformat()


# --- Sources ----------------------------------------------------------------------------------------------------------

def titre_court(t: str | None) -> str:
    """Titre du catalogue sans la mention du module qui le collecte, au lexique neutre."""
    t = re.sub(r"\s*;\s*collecte par .*$", "", t or "")
    t = re.sub(r"\s*\((?:lu par |lus par |collecte par )?pipeline/[a-z_]+\.py[^)]*\)", "", t)
    return neutraliser(t.strip(" ;,")) or "(sans titre)"


def url_page(entree: dict, portails: dict) -> str | None:
    """Adresse de la page du jeu (même règle que pipeline/datapackage.py), sinon premier fichier collecté."""
    portail, jeu = entree.get("portail") or "", entree.get("dataset")
    if entree.get("type") == "eurostat" and jeu:
        return f"https://ec.europa.eu/eurostat/databrowser/view/{jeu}/default/table"
    if (portail == "datagouv" or entree.get("type") == "datagouv") and jeu:
        return f"https://www.data.gouv.fr/datasets/{jeu}/"
    base = portails.get(portail.removeprefix("ods_")) or portails.get(portail)
    if base and jeu and portail != "eurostat":
        return f"{base.rstrip('/')}/explore/dataset/{jeu}/"
    for f in entree.get("fichiers") or []:
        if isinstance(f, dict) and str(f.get("url", "")).startswith("http"):
            return f["url"]
    if str(entree.get("url", "")).startswith("http"):
        return entree["url"]
    for u in entree.get("urls") or []:
        if isinstance(u, dict) and str(u.get("url", "")).startswith("http"):
            return u["url"]
    return None


def producteur(entree: dict, url: str | None) -> str:
    if entree.get("producteur"):
        return str(entree["producteur"])
    portail = entree.get("portail") or ""
    if portail in PORTAILS_LIBELLE:
        return PORTAILS_LIBELLE[portail]
    if entree.get("type") == "eurostat":
        return "Eurostat"
    if entree.get("type") in ("datagouv", "datagouv_ressources"):
        return "data.gouv.fr"
    hote = re.sub(r"^https?://([^/]+).*$", r"\1", url or "")
    return hote or "producteur non renseigné"


def inventaire(E: Entrees) -> list[dict]:
    """Sources suivies : pipeline/sources.json, catalogue, sources lues par une étape hors catalogue, collectes de
    modules tracées dans le manifeste. Une entrée par identifiant."""
    vus, out = set(), []
    eco, euro = "data.economie.gouv.fr", "Eurostat"
    for s in E.config.get("ods", []) + E.config.get("ods_pieces_jointes", []):
        out.append({"id": s["id"], "origine": "sources.json", "type": "ods", "dataset": s["dataset"],
                    "titre": s.get("description") or s["id"], "producteur": eco,
                    "url": f"https://{eco}/explore/dataset/{s['dataset']}/"})
    for s in E.config.get("eurostat", []):
        out.append({"id": s["id"], "origine": "sources.json", "type": "eurostat", "dataset": s["dataset"],
                    "titre": s.get("description") or s["id"], "producteur": euro,
                    "url": f"https://ec.europa.eu/eurostat/databrowser/view/{s['dataset']}/default/table"})
    vus.update(x["id"] for x in out)
    for s in E.catalogue.get("sources", []):
        if s["id"] in vus:
            continue
        vus.add(s["id"])
        u = url_page({**(E.manifeste.get(s["id"]) or {}), **s}, E.portails)
        out.append({"id": s["id"], "origine": "catalogue", "type": s.get("type"), "dataset": s.get("dataset"),
                    "titre": titre_court(s.get("titre")), "producteur": producteur(s, u), "url": u,
                    "_cat": s})
    lus = sorted({sid for d in (E.lecture.get("etapes") or {}).values() for sid in (d.get("sources") or {})})
    modules = sorted(k for k, e in E.manifeste.items() if isinstance(e, dict)
                     and str(e.get("origine") or "").startswith("pipeline/"))
    for sid, origine in [(x, "lue_par_une_etape") for x in lus] + [(x, "module") for x in modules]:
        if sid in vus:
            continue
        vus.add(sid)
        e = E.manifeste.get(sid) or {}
        u = url_page(e, E.portails)
        out.append({"id": sid, "origine": origine, "type": None, "dataset": e.get("dataset"),
                    "titre": titre_court(e.get("titre") or sid), "producteur": producteur(e, u), "url": u})
    return out


def etapes_des_sources(E: Entrees, sources: list[dict]) -> dict[str, list[str]]:
    """Étapes (pages) qui lisent chaque source : relevé pipeline/entrees_lac.json, champs module, lu_par et titre du
    catalogue, origine du manifeste (pipeline/<module>.py) ; étape « base » pour pipeline/sources.json."""
    par_module: dict[str, list[str]] = {}
    for e in E.etapes:
        for m in e.modules:
            par_module.setdefault(m, []).append(e.id)
    ordre = {e.id: i for i, e in enumerate(E.etapes)}
    lecture = {}
    for eid, d in (E.lecture.get("etapes") or {}).items():
        for sid in d.get("sources") or {}:
            lecture.setdefault(sid, set()).add(eid)
    out = {}
    for s in sources:
        ids = set(lecture.get(s["id"], ()))
        if s["origine"] == "sources.json":
            ids.add("base")
        cat = s.get("_cat") or {}
        man = E.manifeste.get(s["id"]) or {}
        for texte in (cat.get("module"), cat.get("lu_par"), cat.get("titre"), man.get("origine")):
            for m in re.findall(r"pipeline/([a-z_]+)\.py", str(texte or "")):
                ids.update(par_module.get(m, []))
        out[s["id"]] = sorted((i for i in ids if i in ordre and i not in EXCLUES), key=ordre.get)
    return out


# --- Millésimes publiés ---------------------------------------------------------------------------------------------

def millesime_fichier(site: Path, rel: str) -> str | None:
    d = _lire_json(site / rel)
    if isinstance(d, dict) and isinstance(d.get("millesime"), str) and d["millesime"].strip():
        return d["millesime"].strip()
    return None


def fichier_reference(site: Path, e: Etape) -> str | None:
    """Fichier dont l'en-tête donne le millésime de la page : index.json, resume.json ou racine.json d'une sortie, sinon
    le premier fichier JSON de la première sortie."""
    premiers = []
    for rel in e.sorties:
        p = site / rel
        if p.is_dir():
            for n in ("index.json", "resume.json", "racine.json"):
                if (p / n).exists():
                    return f"{rel}/{n}"
            fs = sorted(p.glob("*.json"))
            if fs:
                premiers.append(fs[0].relative_to(site).as_posix())
        elif p.suffix == ".json" and p.exists():
            premiers.append(rel)
    return premiers[0] if premiers else None


def _ids_candidats(cle, v: dict) -> set[str]:
    ids = {str(cle)} if cle else set()
    for k in ("id", "id_catalogue", "id_collecte"):
        if isinstance(v.get(k), str):
            ids.add(v[k])
    if v.get("catalogue"):
        ids.update(re.findall(r"[A-Za-z0-9_]+(?:__[A-Za-z0-9_.-]+)?", str(v["catalogue"])))
    for k in ("entrepot", "fichier"):
        if isinstance(v.get(k), str) and v[k]:
            ids.add(Path(v[k]).name.split(".")[0])
    return ids


def details_des_pages(E: Entrees, connus: set[str]) -> dict[str, dict]:
    """Millésime et date de collecte publiés par une page pour une source (champ `sources` de son index)."""
    out: dict[str, dict] = {}
    for e in E.etapes:
        ref = fichier_reference(E.site, e)
        doc = _lire_json(E.site / ref) if ref else None
        sources = doc.get("sources") if isinstance(doc, dict) else None
        if isinstance(sources, dict):
            elements = list(sources.items())
        elif isinstance(sources, list):
            elements = [(None, x) for x in sources]
        else:
            continue
        for cle, v in elements:
            if not isinstance(v, dict):
                continue
            for sid in sorted(_ids_candidats(cle, v) & connus):
                x = out.setdefault(sid, {"etape": e.id, "fichier": ref})
                if isinstance(v.get("millesime"), str) and v["millesime"].strip() and "millesime" not in x:
                    x["millesime"] = v["millesime"].strip()
                if _jour(v.get("collecte_le")) and "collecte_le" not in x:
                    x["collecte_le"] = _jour(v.get("collecte_le"))
    return out


def signalements(E: Entrees) -> dict[str, list[dict]]:
    """Sources signalées inaccessibles ou non publiées par chaque page (`sources_inaccessibles` de son index)."""
    out = {}
    for e in E.etapes:
        ref = fichier_reference(E.site, e)
        doc = _lire_json(E.site / ref) if ref else None
        liste = doc.get("sources_inaccessibles") if isinstance(doc, dict) else None
        if not isinstance(liste, list):
            continue
        for x in liste:
            if not isinstance(x, dict):
                continue
            source = x.get("source") or (f"année {x['annee']}" if x.get("annee") else None) or x.get("url") or "source"
            constat = x.get("constat") or x.get("motif") or x.get("consequence") or ""
            out.setdefault(e.id, []).append({"source": neutraliser(str(source)[:300]),
                                             "constat": neutraliser(str(constat)[:400]), "fichier": ref})
    return out


# --- Publication déclarée par la source -------------------------------------------------------------------------------

def _tete_eurostat(lake: Path, chemin: str) -> str | None:
    """Champ « updated » d'un fichier JSON-stat d'Eurostat (lu dans les premiers ko)."""
    p = lake.parent.parent / chemin if chemin.startswith("data/") else lake / chemin
    try:
        with p.open("rb") as f:
            tete = f.read(65536).decode("utf-8", "replace")
    except OSError:
        return None
    m = re.search(r'"updated"\s*:\s*"([^"]+)"', tete)
    return m.group(1) if m else None


def publication(E: Entrees, s: dict) -> dict | None:
    """Date de publication ou de modification déclarée par la source pour la version collectée, et sa nature."""
    if s["origine"] == "sources.json":
        brut = E.schemas_bruts.get(s["id"]) or {}
        j = _jour(brut.get("modified"))
        if j:
            return {"date": j, "nature": "date de mise à jour déclarée par la source pour la version utilisée"}
        return None
    m = E.manifeste.get(s["id"]) or {}
    if not m:
        return None
    sig = m.get("signature_source")
    if isinstance(sig, str) and "|" in sig and _jour(sig.split("|")[0]):
        return {"date": _jour(sig.split("|")[0]), "nature": "date de modification du jeu déclarée par le portail"}
    if m.get("source_modifiee_le") and _jour(m["source_modifiee_le"]):
        return {"date": _jour(m["source_modifiee_le"]), "nature": "date de modification du jeu déclarée par le portail"}
    if isinstance(sig, str) and _jour(sig) and (m.get("portail") == "datagouv" or s.get("type") == "datagouv"):
        return {"date": _jour(sig), "nature": "date de mise à jour du jeu sur data.gouv.fr"}
    fichiers = [f for f in m.get("fichiers") or [] if isinstance(f, dict)]
    jours = []
    for f in fichiers:
        sigf = f.get("signature")
        if isinstance(sigf, str) and "|" in sigf and _jour(sigf.split("|")[0]):
            jours.append(_jour(sigf.split("|")[0]))
    if jours:
        nature = ("date de modification du fichier sur data.gouv.fr" if s.get("type") == "datagouv_ressources"
                  else "date du fichier dans le répertoire de publication")
        return {"date": max(jours), "nature": nature}
    jours = [_jour(f.get("last_modified")) for f in fichiers if _jour(f.get("last_modified"))]
    if jours:
        return {"date": max(jours), "nature": "date de dernière modification déclarée par le serveur (en-tête HTTP)"}
    jours = [_jour(_tete_eurostat(E.lake, f["chemin"])) for f in fichiers if f.get("chemin")]
    jours = [j for j in jours if j]
    if jours:
        return {"date": max(jours), "nature": "date de mise à jour déclarée par Eurostat"}
    return None


# --- Calendriers ------------------------------------------------------------------------------------------------------

def _edition_depuis(texte: str) -> int | None:
    annees = [int(a) for a in re.findall(r"(?<!\d)(20\d\d)(?!\d)", texte or "")]
    if annees:
        return max(annees)
    m = re.search(r"plf-?(\d{2})(?!\d)", texte or "")
    return 2000 + int(m.group(1)) if m else None


def famille_de(s: dict) -> tuple[str, str, int | None] | None:
    """(famille, calendrier, édition) d'une source rattachée à une publication récurrente, sinon None."""
    for fam, _lib, cal, motifs in _FAMILLES:
        for rx in motifs:
            m = rx.match(s["id"])
            if not m:
                continue
            if cal == "pde":
                return fam, cal, None
            a = m.groupdict().get("a")
            if a:
                ed = int(a) + (2000 if len(a) == 2 else 0)
            else:
                ed = _edition_depuis(s.get("dataset") or "") or _edition_depuis(s.get("titre") or "")
            return fam, cal, ed
    return None


# --- Statut -----------------------------------------------------------------------------------------------------------

def etats_des_etapes(E: Entrees) -> dict[str, dict]:
    """Statut de chaque étape : passage en cours (data/lake/_cache/tout/etat.json) s'il est plus récent que le rapport
    écrit (site/data/mise_a_jour.json), sinon ce rapport, avec ses sources inaccessibles."""
    out = {}
    genere = _instant(E.rapport.get("genere_le"))
    for x in E.rapport.get("etapes") or []:
        out[x.get("etape")] = {"statut": x.get("statut"), "le": genere.date().isoformat() if genere else None,
                               "origine": "rapport", "sources_inaccessibles": [
                                   str(c.get("constat") or "")[:400] for c in x.get("sources_inaccessibles") or []]}
    for eid, x in sorted(E.etat_passage.items()):
        le = _instant(x.get("le")) if isinstance(x, dict) else None
        if le and (genere is None or le > genere):
            out[eid] = {"statut": x.get("statut"), "le": le.date().isoformat(), "origine": "passage_en_cours",
                        "sources_inaccessibles": []}
    return out


def collecte(E: Entrees, s: dict, pages: dict) -> dict:
    """Dernière collecte d'une source : {derniere_collecte, derniere_verification, origine, statut_collecte, acces,
    constat, partiel, version_plus_recente}."""
    r = {"derniere_collecte": None, "derniere_verification": None, "origine": None, "statut_collecte": None,
         "acces": None, "constat": None, "partiel": False, "version_plus_recente": None}
    if s["origine"] == "sources.json":
        v = E.verifications.get(s["id"])
        if not isinstance(v, dict):
            r["constat"] = "vérification non lancée (python pipeline/fraicheur.py collecter)"
            return r
        r["derniere_verification"] = _jour(v.get("verifie_le"))
        r["origine"] = "verification"
        if v.get("statut") != "ok":
            r.update(statut_collecte="erreur", acces="refus", constat=str(v.get("constat") or "")[:300])
            return r
        r["statut_collecte"] = "ok"
        tenu = _instant((E.schemas_bruts.get(s["id"]) or {}).get("modified"))
        source = _instant(v.get("modifie_le"))
        if tenu and source and source > tenu:
            r["version_plus_recente"] = source.date().isoformat()
        else:
            r["derniere_collecte"] = r["derniere_verification"]
        return r
    m = E.manifeste.get(s["id"])
    if isinstance(m, dict):
        r["derniere_verification"] = _jour(m.get("collecte_le"))
        r["origine"] = "manifeste"
        st = m.get("statut")
        r["statut_collecte"] = st
        if st in ("ok", "partiel"):
            r["derniere_collecte"] = r["derniere_verification"]
            echecs = [f.get("erreur", "") for f in m.get("erreurs_fichiers") or [] if isinstance(f, dict)]
            if st == "partiel":
                r["partiel"] = True
                n_refus = sum(1 for x in echecs if ACCES.search(x))
                r["constat"] = (f"collecte partielle : {len(echecs)} ressource(s) en échec"
                                + (f", dont {n_refus} refusée(s) ou indisponible(s), non contournée(s)" if n_refus else ""))
            return r
        err = str(m.get("erreur") or "")
        if st == "delai_depasse" or ACCES.search(err):
            r["acces"] = "refus"
        r["constat"] = _constat_court(err) or st
        return r
    page = pages.get(s["id"]) or {}
    if page.get("collecte_le"):
        r.update(derniere_collecte=page["collecte_le"], derniere_verification=page["collecte_le"], origine="page",
                 statut_collecte="ok")
        return r
    r["constat"] = "aucune collecte datée dans le manifeste de l'entrepôt (source collectée par le module de la page " \
                   "ou pas encore collectée)"
    return r


def _constat_court(err: str) -> str:
    """Erreur de collecte sans adresse de requête : code HTTP et nature du refus seulement."""
    e = re.sub(r"https?://\S+", "", err or "")
    m = re.search(r"HTTP\s*(\d{3})", e) or re.search(r"\b(\d{3}) (?:Client|Server) Error", e)
    if m:
        return f"réponse HTTP {m.group(1)}"
    if re.search(r"timed? ?out|d[eé]lai|budget de temps", e, re.I):
        return "délai dépassé"
    if re.search(r"Connection|IncompleteRead|tronqu|interrompu|coup", e, re.I):
        return "connexion coupée ou transfert interrompu"
    return re.sub(r"\s+", " ", e).strip()[:200]


def statut_source(s: dict, c: dict, prochaine: dict | None, date_ref: str,
                  remplacee: tuple[int, int] | None = None) -> tuple[str, str]:
    """(statut, explication). Ordre : inaccessible, en retard, à jour, non vérifiée. `remplacee` = (édition de la
    source, dernière édition collectée de la même publication) quand une édition plus récente est collectée."""
    statut, texte = _statut_source(c, prochaine, date_ref)
    if remplacee:
        texte = texte.replace(" ; aucun calendrier officiel connu pour la prochaine édition.", ".")
        texte += (f" Édition {remplacee[0]} gardée pour les séries : l'édition {remplacee[1]} de la même publication "
                  "est collectée.")
    return statut, texte


def _statut_source(c: dict, prochaine: dict | None, date_ref: str) -> tuple[str, str]:
    quand = date_longue(c["derniere_verification"])
    if c["acces"] == "refus":
        return "inaccessible", (f"Dernière tentative de collecte le {quand} : {c['constat'] or 'refus ou indisponibilité'}"
                                ". Rien n'a été contourné ; la dernière version obtenue reste publiée.")
    if c["version_plus_recente"]:
        return "en_retard", (f"La source déclare une version modifiée le {date_longue(c['version_plus_recente'])}, "
                             f"plus récente que la version utilisée (vérification du {quand}).")
    if prochaine and prochaine["passee"]:
        return "en_retard", (f"Édition « {prochaine['edition']} » attendue au plus tard le "
                             f"{date_longue(prochaine['date'])} selon le calendrier officiel : elle ne figure pas dans "
                             f"les données collectées au {date_longue(date_ref)}.")
    if c["derniere_collecte"]:
        texte = f"Dernière collecte réussie le {date_longue(c['derniere_collecte'])}"
        if c["origine"] == "verification":
            texte = (f"Version utilisée identique à celle que publie la source (vérification du "
                     f"{date_longue(c['derniere_collecte'])})")
        if c["origine"] == "page":
            texte += " (date publiée par la page qui lit la source)"
        if c["partiel"] and c["constat"]:
            texte += f" ; {c['constat']}"
        if prochaine:
            texte += f". Prochaine édition attendue au plus tard le {date_longue(prochaine['date'])}."
        else:
            texte += " ; aucun calendrier officiel connu pour la prochaine édition."
        return "a_jour", texte
    if c["statut_collecte"] == "sans_ressource":
        return "non_verifiee", "Le jeu ne publie aucun fichier téléchargeable lors de la dernière collecte."
    if c["statut_collecte"] == "lourd_ignore":
        return "non_verifiee", "Fichiers de plus de 100 Mo : collectés seulement à la demande (option --lourd)."
    if c["statut_collecte"] in ("erreur", "delai_depasse"):
        return "non_verifiee", f"Dernière collecte en erreur le {quand} : {c['constat']}."
    return "non_verifiee", f"Pas de collecte datée : {c['constat'] or 'aucune trace de collecte'}."


# --- Mise à jour hebdomadaire -----------------------------------------------------------------------------------------

def mise_a_jour_hebdomadaire(E: Entrees) -> dict:
    """Jour et heure lus dans .github/workflows/data.yml ; étapes dans l'ordre de pipeline/tout.py."""
    wf = E.workflow or ""
    cron = re.search(r'cron:\s*"([^"]+)"', wf)
    jour = heure = None
    if cron:
        champs = cron.group(1).split()
        if len(champs) == 5 and champs[0].isdigit() and champs[1].isdigit():
            heure = f"{int(champs[1]):02d}:{int(champs[0]):02d}"
            if champs[4].isdigit():
                jour = JOURS[int(champs[4]) % 7]
    budget = re.search(r"pipeline/tout\.py \$\{ETAPES[^\n]*--budget (\d+)", wf)
    return {
        "fichier": ".github/workflows/data.yml",
        "cron": cron.group(1) if cron else None,
        "jour": jour,
        "heure_utc": heure,
        "relecture_mensuelle": bool(re.search(r"date -u \+%d\)\"? -le 7", wf)),
        "budget_s": int(budget.group(1)) if budget else None,
        "etapes": [{"etape": e.id, "titre": e.titre, "libelle": LIBELLES_ETAPES.get(e.id, e.titre)} for e in E.etapes],
    }


# --- Construction -----------------------------------------------------------------------------------------------------

def construire(E: Entrees) -> dict:
    sources = inventaire(E)
    par_source = etapes_des_sources(E, sources)
    pages = details_des_pages(E, {s["id"] for s in sources})
    etats = etats_des_etapes(E)
    ref_etape = {e.id: fichier_reference(E.site, e) for e in E.etapes}
    mill_etape = {eid: (millesime_fichier(E.site, ref) if ref else None) for eid, ref in ref_etape.items()}
    base_mill = []
    for rel in dict.fromkeys(r for v in BASE_SORTIES.values() for r in v):
        m = millesime_fichier(E.site, rel)
        if m and m not in base_mill:
            base_mill.append(m)
    if base_mill:
        mill_etape["base"] = " ; ".join(base_mill)

    # Familles : dernière édition détenue (sources présentes) et prochaine échéance.
    familles: dict[str, dict] = {}
    for s in sources:
        f = famille_de(s)
        if f:
            s["_famille"] = f
            fam, cal, ed = f
            x = familles.setdefault(fam, {"calendrier": cal, "editions": set()})
            if ed:
                x["editions"].add(ed)
    date_ref = date.fromisoformat(E.date_reference)
    ordre_etape = {e.id: i for i, e in enumerate(E.etapes)}
    sortie = []
    for s in sources:
        eids = par_source.get(s["id"], [])
        c = collecte(E, s, pages)
        pub = publication(E, s)
        prochaine = None
        famille = edition = None
        if s.get("_famille"):
            famille, cal, edition = s["_famille"]
            if cal == "pde":
                d = prochaine_notification_pde(pub["date"] if pub else None, c["derniere_collecte"])
                if d:
                    prochaine = {"date": d.isoformat(), "edition": libelle_edition("pde", None, d), "calendrier": cal}
            else:
                derniere = max(familles[famille]["editions"]) if familles[famille]["editions"] else None
                if edition and derniere and edition == derniere:
                    d = echeance(cal, edition + 1)
                    prochaine = {"date": d.isoformat(), "edition": libelle_edition(cal, edition + 1), "calendrier": cal}
            if prochaine:
                prochaine["passee"] = date.fromisoformat(prochaine["date"]) <= date_ref
        remplacee = None
        if famille and edition and not prochaine and familles[famille]["editions"]:
            remplacee = (edition, max(familles[famille]["editions"]))
        statut, explication = statut_source(s, c, prochaine, E.date_reference, remplacee)
        page = pages.get(s["id"]) or {}
        if page.get("millesime"):
            mill, origine_mill, fichier_mill = page["millesime"], "source", page.get("fichier")
        elif eids:
            if s["origine"] == "sources.json" and s["id"] in BASE_SORTIES:
                ms = [m for m in (millesime_fichier(E.site, r) for r in BASE_SORTIES[s["id"]]) if m]
                mill = " ; ".join(dict.fromkeys(ms)) or None
                fichier_mill = BASE_SORTIES[s["id"]][0] if mill else None
            else:
                mill, fichier_mill = mill_etape.get(eids[0]), ref_etape.get(eids[0])
            origine_mill = "page" if mill else None
        else:
            mill = origine_mill = fichier_mill = None
        sortie.append({
            "id": s["id"],
            "titre": s["titre"],
            "producteur": s["producteur"],
            "url": s["url"],
            "origine": s["origine"],
            "etapes": eids,
            "derniere_collecte": c["derniere_collecte"],
            "derniere_verification": c["derniere_verification"],
            "collecte_origine": c["origine"],
            "statut_collecte": c["statut_collecte"],
            "millesime_publie": mill,
            "millesime_origine": origine_mill,
            "fichier_millesime": fichier_mill if mill else None,
            "publication_source": pub,
            "famille": famille,
            "edition": edition,
            "prochaine_publication": prochaine,
            "statut": statut,
            "explication": explication,
        })
    sortie.sort(key=lambda x: (ordre_etape.get(x["etapes"][0], 999) if x["etapes"] else 999,
                               x["titre"].casefold(), x["id"]))

    signal = signalements(E)
    etapes = []
    for e in E.etapes:
        if e.id in EXCLUES:
            continue
        mine = [x for x in sortie if x["etapes"] and x["etapes"][0] == e.id]
        lues = [x for x in sortie if e.id in x["etapes"]]
        dates = [x["derniere_collecte"] for x in lues if x["derniere_collecte"]]
        et = etats.get(e.id) or {}
        etapes.append({
            "etape": e.id,
            "titre": e.titre,
            "libelle": LIBELLES_ETAPES.get(e.id, e.titre),
            "sorties": e.sorties,
            "statut_passage": et.get("statut"),
            "statut_passage_le": et.get("le"),
            "statut_passage_origine": et.get("origine"),
            "millesime": mill_etape.get(e.id),
            "fichier_millesime": ("arbre/racine.json" if e.id == "base" and mill_etape.get("base")
                                  else ref_etape.get(e.id) if mill_etape.get(e.id) else None),
            "sources": len(lues),
            "sources_principales": len(mine),
            "par_statut": {k: sum(1 for x in lues if x["statut"] == k) for k in ORDRE_STATUTS},
            "derniere_collecte": max(dates) if dates else None,
            "premiere_collecte": min(dates) if dates else None,
            "sources_inaccessibles_passage": et.get("sources_inaccessibles") or [],
            "signalements": signal.get(e.id, []),
        })
    comptes = {k: sum(1 for x in sortie if x["statut"] == k) for k in ORDRE_STATUTS}
    calendriers = [{"id": k, **v, "familles": [
        {"famille": f, "libelle": lib, "derniere_edition": max(familles[f]["editions"]) if f in familles
         and familles[f]["editions"] else None} for f, lib, cal, _m in FAMILLES if cal == k and f in familles]}
        for k, v in CALENDRIERS.items()]
    genere = E.rapport.get("genere_le")
    return {
        "millesime": f"État des sources au {E.date_reference} (dernière collecte de l'entrepôt)",
        "source": "collecte/catalogue.json, pipeline/sources.json, pipeline/entrees_lac.json, manifeste de collecte "
                  "(data/lake/manifest.json), site/data/mise_a_jour.json, en-têtes des fichiers de site/data",
        "date_reference": E.date_reference,
        "date_reference_definition": "date de la dernière collecte enregistrée dans l'entrepôt (pipeline/reproductible.py) "
                                     ": les statuts « en retard » sont établis à cette date",
        "rapport_passage": {"fichier": "mise_a_jour.json", "genere_le": genere, "mode": E.rapport.get("mode"),
                            "note": "Le rapport de passage est écrit après la dernière étape : une étape déjà passée "
                                    "dans le passage en cours prend son statut dans data/lake/_cache/tout/etat.json "
                                    "(statut_passage_origine « passage_en_cours »)."},
        "mise_a_jour_hebdomadaire": mise_a_jour_hebdomadaire(E),
        "statuts": STATUTS,
        "calendriers": calendriers,
        "comptes": comptes,
        "total": len(sortie),
        "etapes": etapes,
        "sources": sortie,
        "non_collectables": [{"source": neutraliser(str(x.get("source") or "")),
                              "motif": neutraliser(str(x.get("motif") or ""))}
                             for x in E.catalogue.get("non_collectables", []) if isinstance(x, dict)],
        "ordre": {"cles": ["etape", "titre", "id"],
                  "regle": "Sources rangées par page, dans l'ordre de la mise à jour, puis par titre alphabétique. Aucun "
                           "classement par statut ni par producteur."},
        "limites": [
            "La date de dernière collecte est celle du manifeste de l'entrepôt ; une source collectée par le module "
            "d'une page sans trace datée est « non vérifiée », même si la page s'affiche normalement.",
            "Les calendriers retenus sont des dates limites fixées par des textes (loi organique, règlement) : la mise "
            "en ligne en données ouvertes peut suivre le dépôt du document de quelques jours.",
            "Une source sans calendrier officiel connu n'a pas de prochaine publication (null) : elle ne peut pas être "
            "« en retard », seulement à jour à la date de sa dernière collecte.",
            "Le millésime publié est celui déclaré par la page qui lit la source (en-tête du fichier), ou par la source "
            "elle-même quand la page le publie source par source.",
            "Le rapport de passage (site/data/mise_a_jour.json) est écrit après la dernière étape : les sources "
            "inaccessibles qu'il signale sont celles du passage qu'il décrit (date genere_le).",
        ],
        "recherche_prealable": RECHERCHE_PREALABLE,
    }


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def produire(sortie: Path = SORTIE, racine: Path = ROOT) -> dict:
    doc = construire(charger(racine))
    dump(sortie / "index.json", doc)
    print(f"{sortie / 'index.json'} : {doc['total']} sources, "
          + ", ".join(f"{k} {v}" for k, v in doc["comptes"].items()), flush=True)
    return doc


# --- Collecte : vérification des sources de l'étape « base » ------------------------------------------------------

def _get(session, url: str, params: dict | None = None, essais: int = 5):
    """GET poli avec reprises (2, 4, 8, 16 s) ; un refus 401/403/429/451 n'est jamais retenté ni contourné."""
    import requests
    erreur = None
    for n in range(essais):
        try:
            r = session.get(url, params=params, timeout=(20, 60))
            if r.status_code in (401, 403, 429, 451):
                return None, f"HTTP {r.status_code} (accès refusé, non contourné)"
            if r.status_code >= 500:
                erreur = f"HTTP {r.status_code} (serveur indisponible)"
            elif r.status_code >= 400:
                return None, f"HTTP {r.status_code}"
            else:
                return r.json(), None
        except (requests.RequestException, ValueError) as exc:
            erreur = f"{type(exc).__name__} : {str(exc)[:160]}"
        if n < essais - 1:
            time.sleep(2 ** (n + 1))
    return None, erreur


def collecter(racine: Path = ROOT) -> dict:
    """Vérifie chaque source de pipeline/sources.json : métadonnées seulement (date de modification déclarée)."""
    import requests
    cfg = json.loads((racine / "pipeline" / "sources.json").read_text(encoding="utf-8"))
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    out, deja = {}, {}
    for s in cfg.get("ods", []) + cfg.get("ods_pieces_jointes", []):
        url = f"{cfg['ods_base']}/{s['dataset']}"
        if url not in deja:
            deja[url] = _get(sess, url)
        doc, err = deja[url]
        modifie = ((doc or {}).get("metas") or {}).get("default", {}).get("modified") if doc else None
        out[s["id"]] = {"verifie_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "statut": "ok" if doc else "inaccessible", "modifie_le": modifie,
                        "constat": None if doc else f"{err} ({url})"}
        time.sleep(0.5)
    for s in cfg.get("eurostat", []):
        params = {k: v for k, v in (s.get("params") or {}).items() if k not in ("sinceTimePeriod", "lastTimePeriod")}
        params["lastTimePeriod"] = "1"
        url = f"{cfg['eurostat_base']}/{s['dataset']}"
        doc, err = _get(sess, url, params)
        out[s["id"]] = {"verifie_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "statut": "ok" if doc else "inaccessible", "modifie_le": (doc or {}).get("updated"),
                        "constat": None if doc else f"{err} ({url})"}
        time.sleep(0.5)
    cache = racine / "data" / "lake" / "_cache" / "fraicheur"
    cache.mkdir(parents=True, exist_ok=True)
    tmp = cache / f"verifications.json.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, cache / "verifications.json")
    for k, v in out.items():
        print(f"[fraicheur] {k} : {v['statut']}" + (f" ; {v['constat']}" if v["constat"] else ""), flush=True)
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--sortie", help="dossier de sortie (défaut : site/data/fraicheur)")
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter()
    if a.etape in ("produire", "tout"):
        produire(Path(a.sortie) if a.sortie else SORTIE)


if __name__ == "__main__":
    main()
