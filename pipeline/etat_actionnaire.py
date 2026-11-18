"""L'État actionnaire : dividendes reçus, cessions, opérations en capital, compte « Participations financières de l'État ».

Flux bruts par année, sans qualification : ce que l'État reçoit de ses participations (lignes 2110, 2116 et 2199 des
recettes non fiscales du budget général), ce que le compte d'affectation spéciale « Participations financières de
l'État » encaisse (cessions, reversements, versement du budget général) et dépense (programme 731, opérations en
capital ; programme 732, désendettement), en prévision (PLF, LFI) et en exécution (PLRG). Les montants de sources
différentes sont publiés côte à côte ; un écart entre deux sources est publié, jamais tranché ni additionné.

Valeur des participations : deux mesures publiées par des sources primaires, côte à côte et jamais additionnées.
Estimation de l'Agence des participations de l'État au 30 juin de chaque année (rapports relatifs à l'État actionnaire
annexés aux PLF 2024 et 2025, projet annuel de performances 2026) et valeur au bilan de l'État au 31 décembre 2025
(compte général de l'État). Chaque montant est retrouvé mot pour mot, à sa page, dans le document collecté.

Commandes :
    python collecte/collecte.py etat_actionnaire_plf25_recettes_bg etat_actionnaire_plf24_recettes_bg \
        etat_actionnaire_plf25_recettes_cas etat_actionnaire_plf24_recettes_cas etat_actionnaire_lfi23_recettes_cas \
        etat_actionnaire_plf25_depenses_destination etat_actionnaire_plrg_annexes etat_actionnaire_documents \
        etat_actionnaire_valeur_portefeuille
        (réseau, collecteur du dépôt : un refus 401/403 n'est jamais contourné ; sources déclarées dans
        collecte/catalogue.json, tracées dans data/lake/manifest.json ; les rapports qui nomment des dirigeants
        vont dans data/lake/_restreint/etat_actionnaire/)
    python pipeline/etat_actionnaire.py collecter   (réseau : catégorie juridique des entités nommées par les lignes
        d'exécution, API Recherche d'entreprises ; cache data/lake/_cache/etat_actionnaire_entites.json)
    python pipeline/etat_actionnaire.py produire [--sortie DOSSIER]   (sans réseau)

Sorties (site/data/etat_actionnaire/, contrat docs/contrat_interface.md, schémas docs/schemas/etat_actionnaire_*.json) :
    index.json, flux.json, entites.json, societes_controlees.json

Confidentialité : une entité n'est nommée que si son SIREN est une personne morale (sirene.personne_morale) ; sinon sa
ligne est agrégée. Aucun nom de personne physique n'est repris des documents parlementaires.
Sorties reproductibles : aucune heure de passage ; date = dernière collecte (pipeline/reproductible.py) ; ordres explicites.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "etat_actionnaire"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "etat_actionnaire"
CACHE_ENTITES = ROOT / "data" / "lake" / "_cache" / "etat_actionnaire_entites.json"
PLRG = LAKE / "etat_actionnaire_plrg_annexes"
DOCS = LAKE / "etat_actionnaire_documents"
# Rapports qui nomment des dirigeants (rémunérations, gouvernance) : zone restreinte de l'entrepôt, jamais publiés.
VALEUR = ROOT / "data" / "lake" / "_restreint" / "etat_actionnaire" / "etat_actionnaire_valeur_portefeuille"
ODS = "https://data.economie.gouv.fr/explore/dataset"
COMPTE = "Participations financières de l'État"
ANNEES_EXECUTION = [2023, 2024, 2025]

LIGNES_DIVIDENDES = {
    "2110": "Produits des participations de l'État dans des entreprises financières",
    "2116": "Produits des participations de l'État dans des entreprises non financières et bénéfices des "
            "établissements publics non financiers",
    "2199": "Autres dividendes et recettes assimilées",
}
NATURES_RECETTES = {"01": "cession", "02": "reversement_cession_indirecte", "03": "reversement_capital",
                    "04": "remboursement_creance", "05": "remboursement_autre_investissement",
                    "06": "versement_budget_general"}
LIBELLES_RECETTES = {  # libellés de la nomenclature ; une ligne sans prévision est absente des jeux des lois de finances
    "01": "Produit des cessions, par l'État, de titres, parts ou droits de sociétés détenus directement",
    "02": "Reversement de produits, sous toutes formes, résultant des cessions de titres, parts ou droits de sociétés "
          "détenus indirectement par l'État",
    "03": "Reversement de dotations en capital et de produits de réduction de capital ou de liquidation",
    "04": "Remboursement de créances rattachées à des participations financières",
    "05": "Remboursements de créances liées à d'autres investissements, de l'État, de nature patrimoniale",
    "06": "Versement du budget général",
}
PROGRAMMES_COMPTE = {"731": "Opérations en capital intéressant les participations financières de l'État",
                     "732": "Désendettement de l'État et d'établissements publics de l'État"}
PROGRAMMES_BG = {"367": "Financement des opérations patrimoniales sur le compte d'affectation spéciale "
                        "« Participations financières de l'État »",
                 "369": "Amortissement de la dette de l'État liée à la covid-19"}

# Lignes d'exécution dont le libellé nomme une entité : SIREN rapproché par le projet (répertoire Sirene), vérifié par
# `collecter`. Une ligne nommée absente de cette table, ou dont le SIREN n'est pas une personne morale, est agrégée.
ENTITES = {
    "211031": "775665599", "211038": "388202533", "211058": "180020026", "211609": "483790069",
    "211610": "552016628", "211618": "722031176", "211628": "441133808", "211631": "552081317",
    "211641": "352751143", "211648": "356000000", "211658": "318186756", "211668": "542089750",
    "211671": "776056467", "211679": "441639465", "211688": "380129866", "211691": "542107651",
    "211692": "315065292", "211698": "562082909", "219920": "572104891",
}
NOTES_ENTITES = {
    "211609": "Le libellé de la source ne distingue pas l'établissement public Bpifrance de la société Bpifrance. Le "
              "SIREN retenu est celui de l'établissement public (catégorie juridique 4120, actif au répertoire Sirene) : "
              "c'est lui que l'annexe 1 « Participations directes de l'État » du rapport relatif à l'État actionnaire "
              "2025 cite comme participation directe de l'État (« EPIC Bpifrance 100% », page 110).",
    "211668": "Libellé de la source : « TSA (ex- Thomson SA) ». Le SIREN retenu est celui de la société TSA (catégorie "
              "juridique 5710, active au répertoire Sirene, activité de holding), que l'annexe 1 « Participations "
              "directes de l'État » du rapport relatif à l'État actionnaire 2025 cite comme participation directe de "
              "l'État (« TSA 100% », page 110).",
}
# Lignes d'exécution au libellé générique (aucune entité désignée) : publiées telles quelles.
LIGNES_GENERIQUES = {"211601", "211621", "219901", "219902", "219906", "219907"}

# Opérations de 2025 citées dans le texte de l'annexe du Sénat (le tableau par entreprise, publié en image, n'est pas
# repris). Chaque citation est retrouvée mot pour mot dans le document collecté à chaque production.
SENAT = {"fichier": "senat_l25-736-2211.pdf", "url": "https://www.senat.fr/rap/l25-736-221/l25-736-2211.pdf",
         "titre": "Sénat, rapport n° 736 (2025-2026) sur le projet de loi relative aux résultats de la gestion et "
                  "portant approbation des comptes de l'année 2025, tome II, annexe n° 21, compte d'affectation "
                  "spéciale « Participations financières de l'État »"}
OPERATIONS_SENAT = [
    ("481043040", [
        ("augmentation de capital", 749_000_000,
         "l’entreprise Eutelsat à hauteur de 749 millions d’euros"),
        ("augmentation de capital", 750_000_000,
         "en contribuant à hauteur de 750 millions d’euros aux augmentations de capital d’un montant total de "
         "1,5 milliard d’euros réalisées par Eutelsat en 2025"),
        ("achat de titres", 258_000_000,
         "rachat par l’APE des actions d’Eutelsat détenue par Bpifrance pour un montant de 258 millions d’euros"),
    ]),
    ("352973622", [
        ("augmentation de capital", 625_000_000,
         "la société anonyme « Imprimerie nationale » à hauteur de 625 millions d’euros"),
    ]),
    ("813986486", [
        ("augmentation de capital", 30_000_000,
         "la Société pour le logement intermédiaire (SLI) à hauteur de 30 millions d’euros"),
    ]),
]
COMPOSITION_SENAT = [
    ("perimetre_agence_participations", "opérations du périmètre de l'Agence des participations de l'État", 2_328_000_000,
     "Ces opérations ont représenté 2 328 millions d’euros en 2025"),
    ("investissements_avenir_france_2030",
     "fonds propres du troisième programme d'investissements d'avenir et du plan France 2030", 640_000_000,
     "ces investissements ont représenté 640 millions d’euros"),
    ("banques_multilaterales", "banques multilatérales de développement", 204_000_000,
     "à hauteur de 204 millions d’euros de crédits exécutés en 2025"),
]
TOTAUX_SENAT = [  # (id, citation, {clé: millions d'euros})
    ("recettes", "TOTAL 8 027 4 416 1 179", {"execution_2024": 8027, "lfi_2025": 4416, "execution_2025": 1179}),
    ("depenses", "TOTAL 9 501 9 501 4 416 4 416 3 399 3 399",
     {"execution_2024": 9501, "lfi_2025": 4416, "execution_2025": 3399}),
]
PAP = {"fichier": "pap2026_cas_pfe.pdf",
       "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1088068/file/"
              "PAP2026_CS_CAS_Participations_financieres_Etat_YC.pdf",
       "titre": "Projet annuel de performances 2026 du compte d'affectation spéciale « Participations financières de "
                "l'État » (annexe au projet de loi de finances pour 2026)"}
INSEE = {"fichier": "insee_societes_controlees_2022.xlsx",
         "url": "https://www.insee.fr/fr/statistiques/fichier/8252208/tableaux_telechargement_2022.xlsx",
         "page": "https://www.insee.fr/fr/statistiques/8252208",
         "titre": "Insee, sociétés contrôlées majoritairement par l'État fin 2022 (répertoire des entreprises "
                  "contrôlées majoritairement par l'État)"}

# Valeur des participations : documents primaires (miroirs Assemblée nationale ; le site de l'Agence des participations
# de l'État répond 403). Chaque montant est retrouvé mot pour mot à la page indiquée (page du fichier PDF).
DOCS_VALEUR = {
    "jaune_2024": {"dossier": VALEUR, "fichier": "jaune_plf2024_etat_actionnaire.pdf",
                   "url": "https://www2.assemblee-nationale.fr/static/16/pdf/Annexes_PLF/Rapport_%C3%89tat_actionnaire.pdf",
                   "titre": "Rapport relatif à l'État actionnaire 2024, annexe au projet de loi de finances pour 2024 "
                            "(rapport d'activité 2022-2023 de l'Agence des participations de l'État)"},
    "jaune_2025": {"dossier": VALEUR, "fichier": "jaune_plf2025_etat_actionnaire.pdf",
                   "url": "https://www2.assemblee-nationale.fr/static/17/Annexes-DL/PLF2025-Jaunes/10-Jaune_Etat_actionnaire.pdf",
                   "titre": "Rapport relatif à l'État actionnaire 2025, annexe au projet de loi de finances pour 2025 "
                            "(rapport d'activité 2023-2024 de l'Agence des participations de l'État)"},
    "pap_2026": {"dossier": DOCS, "fichier": PAP["fichier"], "url": PAP["url"], "titre": PAP["titre"]},
    "rap_2025": {"dossier": VALEUR, "fichier": "rap2025_cas_pfe.pdf",
                 "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1109904/file/"
                        "Participations_financieres_Etat_YC.pdf",
                 "titre": "Rapport annuel de performances 2025 du compte d'affectation spéciale « Participations "
                          "financières de l'État » (annexe au projet de loi relative aux résultats de la gestion et "
                          "portant approbation des comptes de l'année 2025)"},
    "cge_2025": {"dossier": VALEUR, "fichier": "cge2025_presentation.pdf",
                 "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1109793/file/"
                        "Rapport%20de%20pr%C3%A9sentation%20du%20CGE%202025.pdf",
                 "titre": "Rapport de présentation du compte général de l'État 2025 (annexe au projet de loi relative "
                          "aux résultats de la gestion et portant approbation des comptes de l'année 2025)"},
}
# Estimation de l'Agence au 30 juin : (date, document, montants, [(page, citation)], note)
VALEUR_AGENCE = [
    ("2022-06-30", "jaune_2024", {"valeur_md": 128.0},
     [(8, "La valeur totale du portefeuille de l’APE est estimée au 30 juin 2023 à 153 Md€ (128 Md€ au 30 juin 2022).")],
     None),
    ("2023-06-30", "jaune_2024", {"valeur_md": 153.0, "valeur_cotee_md": 50.0},
     [(29, "La valeur totale du portefeuille de l’APE est estimée à 153 Md€ au 30 juin 2023, dont 50 Md€ correspondant "
           "à la valeur totale des participations dans des sociétés cotées (40 % de la valeur totale du portefeuille).")],
     "La source écrit aussi « 40 % de la valeur totale du portefeuille » ; 50 Md€ rapportés à 153 Md€ font 33 %. Les "
     "deux nombres sont reproduits tels que publiés, aucun n'est corrigé."),
    ("2024-06-30", "jaune_2025", {"valeur_md": 179.5, "valeur_cotee_md": 50.0, "entreprises": 85, "entreprises_cotees": 10},
     [(4, "85 entreprises composent le portefeuille, dont 10 cotées. La valeur de celui-ci s’établit à 179,5 Md€ au "
          "30 juin 2024."),
      (28, "La valeur totale du portefeuille de l’APE est estimée à 179,5 Md€ au 30 juin 2024, dont 50 Md€ correspondant "
           "à la valeur totale des participations dans des sociétés cotées (28 % de la valeur totale du portefeuille).")],
     None),
    ("2025-06-30", "pap_2026", {"valeur_md": 209.1, "valeur_cotee_md": 67.9, "entreprises": 86, "entreprises_cotees": 10},
     [(20, "regroupant, au 30 juin 2025, 86 entreprises dont 10 entreprises cotées"),
      (20, "valeur patrimoniale est estimée au 30 juin 2025 à 209,1 Md€ (dont 67,9 Md€ correspondent à la valeur totale "
           "des participations dans des sociétés cotées"),
      (23, "La valeur totale du portefeuille de l’APE est estimée à près de 209,1 Md€ au 30 juin 2025, avec une "
           "valorisation boursière du portefeuille coté de l’État qui s’établit à 68 Md€")],
     "Le même document écrit aussi « 68 Md€ » (page 23) pour les sociétés cotées : arrondi de 67,9 Md€. Le rapport "
     "annuel de l'agence est publié sur son site, qui refuse l'accès (403) : la valeur au 30 juin 2025 est reprise du "
     "projet annuel de performances 2026 du compte, dont les deux programmes ont pour responsable le directeur général "
     "de l'agence."),
]
METHODE_AGENCE = ("pap_2026", 23, "Précision méthodologique : pour les sociétés non cotées, la valeur retenue est la "
                                  "valeur comptable des capitaux propres au 31 décembre N-1.")
COTEES_FIN_2025 = ("2025-12-31", "rap_2025", {"valeur_cotee_md": 72.1, "entites": 89},
                   [(19, "le portefeuille de l’État actionnaire, qui compte 89 entités au 31 décembre 2025"),
                    (21, "Au 31 décembre 2025, la valorisation boursière du portefeuille coté de l’État s’établit à 72,1 Md€")])
BILAN_ETAT = ("2025-12-31", "cge_2025",
              {"valeur_md": 394.5, "entites_controlees_md": 237.3, "entites_non_controlees_md": 157.2, "entites": 1508,
               "entites_controlees": 633, "entites_non_controlees": 875},
              [(26, "Chiffres clés des participations de l’État au 31 décembre 2025 en milliards d’euros"),
               (26, "Nombre d'entités 633 entités 875 entités 1508 entités"),
               (26, "Valeur d'équivalence (EC) | Valeur nette comptable (ENC) 237,3 Md€ 157,2 Md€ 394,5 Md€"),
               (26, "Les entités contrôlées sont évaluées dans les comptes de l’État à leur valeur d’équivalence"),
               (28, "Les entités non contrôlées sont valorisées dans les comptes de l’État à leur valeur nette comptable")])
# Participations directes de l'État (annexe 1 du rapport 2025) : contrôle des rapprochements Bpifrance et TSA.
PARTICIPATIONS_DIRECTES = ("jaune_2025", 110, ["Participations directes de l’État", "EPIC Bpifrance 100%", "TSA 100%"])

MESURES = {
    "plf_eur": "prévision du projet de loi de finances de l'année",
    "lfi_eur": "prévision de la loi de finances initiale (jeu de la loi de finances ; 2025 pour le compte : projet "
               "annuel de performances 2026)",
    "lfi_plrg_eur": "prévision de la loi de finances initiale telle que reprise par le PLRG",
    "lfr_plrg_eur": "modification par les lois de finances rectificatives ou de fin de gestion (PLRG)",
    "prevision_revisee_eur": "prévision après lois de finances rectificatives (PLRG)",
    "evaluation_eur": "évaluation des recettes du compte reprise par le PLRG",
    "report_entrant_eur": "crédits reportés de l'année précédente (PLRG)",
    "credits_ouverts_eur": "crédits de paiement ouverts, tous mouvements compris (PLRG)",
    "execution_eur": "montant constaté : recouvrements pour une recette, dépenses constatées en crédits de paiement "
                     "pour un programme (PLRG)",
    "report_sortant_eur": "crédits reportés sur l'année suivante (PLRG)",
}

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "requetes": ["data.economie.gouv.fr : recettes, comptes d'affectation spéciale, comptes spéciaux, participations",
                 "data.gouv.fr : participations de l'État, agence des participations de l'État, État actionnaire",
                 "GitHub : agence participations etat ; etat actionnaire france ; participations financieres etat budget",
                 "Assemblée nationale, Sénat : rapport relatif à l'État actionnaire (annexes aux PLF), valeur du "
                 "portefeuille de l'agence, compte général de l'État 2025, rapport annuel de performances 2025 du compte"],
    "trouvailles": [
        {"nom": "Assemblée nationale, annexes « Rapport relatif à l'État actionnaire » des PLF 2024 et 2025 (rapports "
                "d'activité de l'Agence des participations de l'État)", "url": DOCS_VALEUR["jaune_2025"]["url"],
         "verdict": "réutilisable tel quel", "licence": "document budgétaire public", "date": "2024-10 (PLF 2025)",
         "usage": "valeur estimée du portefeuille au 30 juin 2022, 2023 et 2024 ; participations directes de l'État "
                  "(annexe 1), contrôle des rapprochements Bpifrance et TSA"},
        {"nom": "Assemblée nationale, rapport de présentation du compte général de l'État 2025",
         "url": DOCS_VALEUR["cge_2025"]["url"], "verdict": "réutilisable tel quel", "licence": "document budgétaire public",
         "date": "2026 (comptes 2025)", "usage": "valeur des participations au bilan de l'État au 31 décembre 2025"},
        {"nom": "Assemblée nationale, rapport annuel de performances 2025 du compte « Participations financières de "
                "l'État »", "url": DOCS_VALEUR["rap_2025"]["url"], "verdict": "réutilisable tel quel",
         "licence": "document budgétaire public", "date": "2026 (exécution 2025)",
         "usage": "valeur boursière des participations cotées et nombre d'entités au 31 décembre 2025"},
        {"nom": "data.economie.gouv.fr, recettes du budget général et des comptes spéciaux (PLF 2024, PLF 2025, LFI 2023), "
                "dépenses selon destination (PLF 2025)", "url": "https://data.economie.gouv.fr/explore/",
         "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0",
         "date": "2024-10-11 (jeux du PLF 2025)", "usage": "prévisions par ligne de recette et par action"},
        {"nom": "data.economie.gouv.fr, annexes CSV des PLRG 2023, 2024 et 2025", "url": f"{ODS}/plrg-2024/",
         "verdict": "à adapter", "licence": "Licence Ouverte 2.0", "date": "2026-04 (PLRG 2025)",
         "usage": "exécution par ligne ; trois formats de fichier différents selon l'année, lus par un même lecteur"},
        {"nom": INSEE["titre"], "url": INSEE["page"], "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "date": "fin 2022", "usage": "nombre de sociétés et effectifs"},
        {"nom": "data.gouv.fr, « Portefeuille des participations cotées de l'État » (ministère de l'économie)",
         "url": "https://www.data.gouv.fr/datasets/portefeuille-des-participations-cotees-de-l-etat",
         "verdict": "inspiration seulement", "licence": "Licence Ouverte", "date": "2014-03-11",
         "usage": "non repris : une seule publication, de 2014"},
        {"nom": "data.gouv.fr, « L'État actionnaire » (Cour des comptes, données du rapport de janvier 2017)",
         "url": "https://www.data.gouv.fr/datasets/letat-actionnaire", "verdict": "à adapter", "licence": "ODbL",
         "date": "2017-06-06", "usage": "non repris : période 2010-2016, licence de partage à l'identique"},
        {"nom": "GitHub, ogrre/ou-vont-mes-impots-api", "url": "https://github.com/ogrre/ou-vont-mes-impots-api",
         "verdict": "inspiration seulement", "licence": "MIT", "date": "2026-10-26 (dernier commit)",
         "usage": "non repris : seule la description du dépôt a été lue ; elle ne mentionne pas les participations de l'État"},
        {"nom": "GitHub, dépôts consacrés aux participations de l'État", "url": "https://github.com/search",
         "verdict": "aucun dépôt trouvé", "licence": "sans objet", "date": "2026-11-17",
         "usage": "trois requêtes sans résultat"},
    ],
}


# --- Outils ----------------------------------------------------------------------------------------------------------

def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).replace("’", "'").replace("‘", "'")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _espaces(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def nombre(v) -> float | None:
    """Montant d'une cellule ; vide, « nc » ou « s » : None (jamais 0)."""
    t = str(v if v is not None else "").replace(" ", "").replace("\xa0", "").replace(" ", "").strip()
    if t == "" or t.lower() in ("nc", "s", "nd", "-", "n/a"):
        return None
    return round(float(t.replace(",", ".")), 2)


def _somme(valeurs) -> float | None:
    vs = [v for v in valeurs if v is not None]
    return round(sum(vs), 2) if vs else None


def lire_csv(chemin: Path) -> list[dict]:
    """CSV des jeux et des annexes (point-virgule ou virgule, UTF-8 avec ou sans BOM) ; en-têtes normalisés."""
    texte = chemin.read_text(encoding="utf-8-sig")
    sep = "," if texte.split("\n", 1)[0].count(",") > texte.split("\n", 1)[0].count(";") else ";"
    lignes = list(csv.reader(texte.splitlines(), delimiter=sep))
    entete = [_norm(c).replace(" ", "_").replace("'", "_") for c in lignes[0]]
    return [dict(zip(entete, l)) for l in lignes[1:] if any(c.strip() for c in l)]


def _col(ligne: dict, *motifs: str):
    """Valeur de la première colonne dont le nom contient tous les fragments d'un motif (« a+b »)."""
    for m in motifs:
        for k, v in ligne.items():
            if all(f in k for f in m.split("+")):
                return v
    return None


def _code_libelle(texte: str) -> tuple[str | None, str]:
    """« 2110 - Libellé » ou « Libellé - 79101 » -> (code, libellé)."""
    t = _espaces(texte)
    m = re.match(r"^(\d{3,6}) - (.+)$", t)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^(.+?) - (\d{3,6})$", t)
    if m:
        return m.group(2), m.group(1)
    return None, t


def _est_compte(v) -> bool:
    return _norm(v) == _norm(COMPTE)


# --- Lecture des jeux de prévision (data.economie.gouv.fr) ------------------------------------------------------------

def previsions_dividendes() -> dict:
    """{ligne: {année: {mesure: montant}}} d'après les jeux « recettes du budget général » des PLF 2024 et 2025."""
    out = {c: {} for c in LIGNES_DIVIDENDES}
    for fichier, annee in (("etat_actionnaire_plf24_recettes_bg.csv", 2024), ("etat_actionnaire_plf25_recettes_bg.csv", 2025)):
        for l in lire_csv(LAKE / fichier):
            code = str(int(float(l["code_ligne_recettes"]))) if (l.get("code_ligne_recettes") or "").strip() else ""
            if code not in out:
                continue
            assert int(float(l["annee"])) == annee, (fichier, l)
            m = {"plf_eur": nombre(l.get("montant_recettes_plf"))}
            if "montant_recettes_lfi" in l:
                m["lfi_eur"] = nombre(l["montant_recettes_lfi"])
            out[code][annee] = m
    return out


def previsions_compte() -> tuple[dict, dict]:
    """({ligne: {année: mesures}}, {ligne: libellé}) d'après les jeux « recettes des CAS et CCF » (LFI 2023, PLF 2024, 2025)."""
    out: dict[str, dict] = {c: {} for c in NATURES_RECETTES}
    libelles: dict[str, str] = dict(LIBELLES_RECETTES)
    for fichier, annee in (("etat_actionnaire_lfi23_recettes_cas.csv", 2023), ("etat_actionnaire_plf24_recettes_cas.csv", 2024),
                           ("etat_actionnaire_plf25_recettes_cas.csv", 2025)):
        for l in lire_csv(LAKE / fichier):
            if not _est_compte(l.get("libelle_mission")):
                continue
            code = l["code_ligne_de_recette"].rsplit("-", 1)[-1]
            libelles[code] = _espaces(l["libelle_ligne_de_recette"])
            m = {"plf_eur": nombre(l.get(f"montant_recettes_plf_{annee}"))}
            if f"montant_recettes_lfi_{annee}" in l:
                m["lfi_eur"] = nombre(l[f"montant_recettes_lfi_{annee}"])
            out[code][annee] = m
    return out, libelles


def actions_plf2025() -> dict:
    """{programme: {action: (libellé, cp)}} d'après « PLF 2025, dépenses selon destination »."""
    out: dict[str, dict] = {}
    for l in lire_csv(LAKE / "etat_actionnaire_plf25_depenses_destination.csv"):
        assert l["loi"] == "PLF" and int(float(l["exercice"])) == 2025
        p = out.setdefault(l["programme"], {})
        lib, cp = p.get(l["action"], (_espaces(l["libelle_action"]), 0.0))
        p[l["action"]] = (lib, round(cp + (nombre(l["credit_de_paiement"]) or 0.0), 2))
    return out


# --- Lecture des annexes du PLRG ---------------------------------------------------------------------------------------

def plrg_dividendes(annee: int) -> dict:
    """{ligne: {"mesures": {...}, "execution": {code: (libellé, montant)}}} ; trois formats de fichier selon l'année."""
    out = {c: {"mesures": {}, "execution": {}, "total_publie": None} for c in LIGNES_DIVIDENDES}
    for l in lire_csv(PLRG / f"plrg_{annee}_recettes.csv"):
        prev = _col(l, "ligne+prevision") or ""
        code, _ = _code_libelle(prev.replace(" (total)", ""))
        if code not in out:
            continue
        ex = _espaces(_col(l, "ligne+execution") or "")
        recouvre = nombre(_col(l, "recouvrement"))
        if "(total)" in prev or "(total)" in ex:
            out[code]["total_publie"] = recouvre
        elif ex in ("", "0"):
            out[code]["mesures"] = {k: v for k, v in (("lfi_plrg_eur", nombre(_col(l, "lfi"))),
                                                         ("lfr_plrg_eur", nombre(_col(l, "lfr"))),
                                                         ("prevision_revisee_eur", nombre(_col(l, "total+prevision"))))
                                    if v is not None}
        else:
            c_ex, lib = _code_libelle(ex)
            assert c_ex and c_ex.startswith(code), (annee, ex)
            assert c_ex not in out[code]["execution"], (annee, c_ex)
            out[code]["execution"][c_ex] = (lib, recouvre)
    for code, d in out.items():
        somme = _somme(v for _, v in d["execution"].values())
        d["mesures"]["execution_eur"] = somme
        if d["total_publie"] is not None and somme is not None:
            assert abs(d["total_publie"] - somme) <= 1, (annee, code, d["total_publie"], somme)
    return out


def plrg_recettes_compte(annee: int) -> dict:
    """{ligne: {"evaluation_eur", "execution_eur", "detail": [(code, libellé, montant ou None)]}}."""
    out: dict[str, dict] = {}
    for l in lire_csv(PLRG / f"plrg_{annee}_cs_recouvrements.csv"):
        if not _est_compte(l.get("compte")):
            continue
        code, _ = _code_libelle(_col(l, "ligne+prevision") or "")
        assert code and code.startswith("791"), l
        d = out.setdefault(code[-2:], {"evaluation_eur": None, "detail": []})
        ex = _espaces(_col(l, "ligne+execution") or "")
        if ex in ("", "0"):
            d["evaluation_eur"] = nombre(_col(l, "evaluation"))
        else:
            c_ex, lib = _code_libelle(ex)
            d["detail"].append((c_ex, lib, nombre(_col(l, "recouvrement"))))
    for d in out.values():
        d["detail"].sort(key=lambda x: x[0])
        d["execution_eur"] = _somme(v for _, _, v in d["detail"])
    return out


def _programme(texte: str) -> str | None:
    m = re.search(r"- (\d{3})\s*$", texte or "")
    return m.group(1) if m else None


def plrg_depenses(annee: int, fichier: str, programmes: dict, compte_seul: bool) -> dict:
    """{programme: mesures} : crédits de paiement ouverts et dépenses constatées, tous titres confondus."""
    champs = (("lfi_plrg_eur", "lfi"), ("lfr_plrg_eur", "lfr"), ("report_entrant_eur", "report_n-1"),
              ("credits_ouverts_eur", "total_cp_ouverts"), ("execution_eur", "depenses_constatees"),
              ("report_sortant_eur", "report_n+1"))
    out: dict[str, dict] = {}
    for l in lire_csv(PLRG / f"plrg_{annee}_{fichier}.csv"):
        p = _programme(l.get("programme", ""))
        if p not in programmes or (compte_seul and not _est_compte(l.get("mission"))):
            continue
        d = out.setdefault(p, {})
        for cle, col in champs:
            v = nombre(l.get(col))
            if v is not None:
                d[cle] = round(d.get(cle, 0.0) + v, 2)
    return out


def plrg_solde(annee: int) -> dict:
    for l in lire_csv(PLRG / f"plrg_{annee}_cs_comptable.csv"):
        if _est_compte(l.get("mission")):
            return {"debut_eur": nombre(l["be_credit"]), "recettes_eur": nombre(l["op_recettes"]),
                    "depenses_eur": nombre(l["op_depenses"]), "fin_eur": nombre(l["bs_credit"])}
    raise SystemExit(f"compte « {COMPTE} » absent de la situation comptable {annee}")


# --- Documents (PDF, xlsx) ---------------------------------------------------------------------------------------------

def _pages_pdf(nom: str):
    import pdfplumber
    return pdfplumber.open(DOCS / nom)


def _lignes_mots(page) -> list[list[dict]]:
    """Mots d'une page regroupés par ligne ; un montant « 4 313 500 000 » reste un seul mot (espaces conservés)."""
    lignes: dict[int, list] = {}
    for w in page.extract_words(keep_blank_chars=True, x_tolerance=2.5):
        if w["text"].strip():
            lignes.setdefault(round(w["top"] / 3), []).append(w)
    return [sorted(v, key=lambda w: w["x0"]) for _, v in sorted(lignes.items())]


_MONTANT = re.compile(r"^-?\d{1,3}(?: \d{3})*$")
_DECIMAL = re.compile(r"^\d+(?:,\d+)?$")


def lire_pap() -> dict:
    """Projet annuel de performances 2026 : recettes du compte (LFI 2025, prévision 2026), crédits par action
    (LFI 2025, PLF 2026), dividendes perçus par l'État actionnaire 2014-2025 (milliards d'euros)."""
    recettes, actions, dividendes, pages = {}, {}, {}, {}
    with _pages_pdf(PAP["fichier"]) as pdf:
        for i, page in enumerate(pdf.pages):
            texte = page.extract_text() or ""
            if "ÉVALUATION ET JUSTIFICATION DES RECETTES" in texte and "Section / Ligne de recette" in texte:
                pages["recettes"] = i + 1
                for mots in _lignes_mots(page):
                    t = [w["text"].strip() for w in mots]
                    m = re.match(r"^(0[1-6]) - ", t[0])
                    nums = [x for x in t[1:] if _MONTANT.match(x)]
                    if m and len(nums) == 4:
                        recettes[m.group(1)] = {"lfi_2025": nombre(nums[0]), "prevision_2026": nombre(nums[1])}
                    elif t[0] == "Total" and len(nums) == 4:
                        recettes["total"] = {"lfi_2025": nombre(nums[0]), "prevision_2026": nombre(nums[1])}
            elif "PRESENTATION DES CREDITS PAR ACTION ET TITRE" in texte and "CREDITS DE PAIEMENTS" in texte \
                    and "Augmentations de capital" in texte:
                pages["actions"] = i + 1
                lignes = [[w["text"].strip() for w in mots] for mots in _lignes_mots(page)]
                debut = next(k for k, t in enumerate(lignes) if t[0].startswith("CREDITS DE PAIEMENT"))
                k = debut
                while k < len(lignes):
                    t = lignes[k]
                    m = re.match(r"^(0\d) – (.+)$", t[0])
                    if m or t[0] == "Totaux":
                        lfi = next(x for x in t[1:] if _MONTANT.match(x))
                        suite = lignes[k + 1]
                        plf = next(x for x in suite if _MONTANT.match(x))
                        lib = m.group(2) if m else "total"
                        if m and not _MONTANT.match(suite[0]):
                            lib = f"{lib} {suite[0]}"
                        actions[m.group(1) if m else "total"] = {"libelle": _espaces(lib), "lfi_2025": nombre(lfi),
                                                                 "plf_2026": nombre(plf)}
                        k += 1
                    k += 1
            elif "Dividendes perçus par l’État actionnaire (en Md€ par exercice budgétaire)" in texte:
                pages["dividendes"] = i + 1
                series = []
                for mots in _lignes_mots(page):
                    t = [w["text"].strip() for w in mots]
                    if len([x for x in t if re.fullmatch(r"20\d\d", x)]) >= 10:
                        dividendes["annees"] = [int(x) for x in t if re.fullmatch(r"20\d\d", x)]
                    else:
                        nums = [x for x in t if _DECIMAL.match(x)]
                        if len(nums) >= 12 and len(series) < 3:
                            series.append([float(x.replace(",", ".")) for x in nums[-12:]])
                assert "(Prévisions" in texte and "au 30/08/2025)" in texte
                dividendes["annees"].append(2025)
                dividendes["numeraire_md"], dividendes["actions_md"], dividendes["total_md"] = series
    assert set(recettes) == set(NATURES_RECETTES) | {"total"}, sorted(recettes)
    assert abs(sum(recettes[c]["lfi_2025"] for c in NATURES_RECETTES) - recettes["total"]["lfi_2025"]) < 1
    assert abs(sum(recettes[c]["prevision_2026"] for c in NATURES_RECETTES) - recettes["total"]["prevision_2026"]) < 2
    assert "total" in actions and len(actions) >= 4, sorted(actions)
    for cle in ("lfi_2025", "plf_2026"):
        assert abs(sum(a[cle] for c, a in actions.items() if c != "total") - actions["total"][cle]) < 1, cle
    assert dividendes["annees"] == list(range(2014, 2026)) and len(dividendes["total_md"]) == 12
    for n, a, t in zip(dividendes["numeraire_md"], dividendes["actions_md"], dividendes["total_md"]):
        assert abs(n + a - t) < 0.06, (n, a, t)
    return {"recettes": recettes, "actions": actions, "dividendes": dividendes, "pages": pages}


def lire_senat() -> dict:
    """Texte de l'annexe du Sénat, page par page (espaces normalisés) ; retrouve chaque citation et sa page."""
    with _pages_pdf(SENAT["fichier"]) as pdf:
        pages = [_espaces(p.extract_text() or "") for p in pdf.pages]

    def page_de(citation: str) -> int:
        trouvees = [i + 1 for i, t in enumerate(pages) if citation in t]
        if not trouvees:
            raise SystemExit(f"citation absente du document du Sénat collecté : « {citation} »")
        return trouvees[0]

    return {"page_de": page_de, "pages": len(pages)}


def lire_insee() -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(DOCS / INSEE["fichier"], read_only=True, data_only=True)

    def lignes(nom):
        return [list(r) for r in wb[nom].iter_rows(values_only=True) if any(c is not None for c in r)]

    def cellule(v):
        if isinstance(v, str):
            return nombre(v)  # « s » (secret statistique) -> None
        return v

    t1 = lignes("Tableau 1")
    assert "contrôlées majoritairement par l’État" in t1[0][0] and "Nombre de sociétés" in t1[1][1], t1[:2]
    serie = [{"annee": int(r[0]), "societes": int(r[1]), "effectifs_milliers": cellule(r[2]),
              "part_emploi_salarie_pct": cellule(r[3])} for r in t1[2:] if isinstance(r[0], (int, float))]
    t4 = lignes("Tableau 4")
    assert "activité économique détaillée en 2021 et 2022" in t4[0][0] and t4[2][1:5] == ["Fin 2021", "Fin 2022", "Fin 2021", "Fin 2022"]
    activites, parent = [], None
    for r in t4[3:]:
        if not isinstance(r[0], str) or r[0].startswith(("Note", "Champ", "Source")):
            continue
        brut = r[0]
        sous = brut.startswith(("Dont", " "))
        nom = _espaces(re.sub(r"^Dont\s+", "", brut.strip()))
        nom = nom[0].upper() + nom[1:]
        if not sous:
            parent = nom
        vals = [cellule(v) for v in r[1:5]]
        secret = [k for k, v in zip(("societes_2021", "societes_2022", "effectifs_2021", "effectifs_2022"), r[1:5]) if v == "s"]
        a = {"nom": nom, "niveau": 2 if sous else 1, "societes_2021": vals[0], "societes_2022": vals[1],
             "effectifs_2021": vals[2], "effectifs_2022": vals[3]}
        if sous:
            a["parent"] = parent
        if secret:
            a["secret_statistique"] = secret
        activites.append(a)
    assert activites[-1]["nom"] == "Ensemble" and activites[-1]["societes_2022"] == serie[-1]["societes"]
    return {"serie": serie, "activites": activites}


def textes_page(page, ecart: float = 10.0, marge: float = 20.0) -> list[str]:
    """Texte de la page entière, puis de chaque colonne. Les rapports sont composés en colonnes : une ligne est coupée
    là où deux mots sont séparés de plus de `ecart` points (gouttière), et chaque morceau rejoint la colonne qui
    commence à la même abscisse (à `marge` points près). Une phrase sur plusieurs lignes d'une colonne se lit ainsi
    d'un seul tenant."""
    mots = sorted(page.extract_words(x_tolerance=1.5), key=lambda w: (w["top"], w["x0"]))
    lignes: list[list[dict]] = []
    haut = None
    for w in mots:
        if haut is None or abs(w["top"] - haut) > 2.5:
            lignes.append([])
            haut = w["top"]
        lignes[-1].append(w)
    colonnes: list[tuple[float, list[str]]] = []
    for ligne in lignes:
        ligne.sort(key=lambda w: w["x0"])
        morceaux = [[ligne[0]]]
        for a, b in zip(ligne, ligne[1:]):
            if b["x0"] - a["x1"] > ecart:
                morceaux.append([])
            morceaux[-1].append(b)
        for m in morceaux:
            col = next((c for c in colonnes if abs(c[0] - m[0]["x0"]) <= marge), None)
            if col is None:
                col = (m[0]["x0"], [])
                colonnes.append(col)
            col[1].append(" ".join(w["text"] for w in m))
    return [_espaces(page.extract_text() or "")] + [_espaces(" ".join(c[1])) for c in colonnes]


def verifier_citations(cle: str, attendues: list[tuple[int, str]]) -> None:
    """Chaque citation doit se lire mot pour mot à sa page du document collecté ; sinon la production s'arrête."""
    import pdfplumber
    doc = DOCS_VALEUR[cle]
    chemin = doc["dossier"] / doc["fichier"]
    if not chemin.exists():
        raise SystemExit(f"document absent de l'entrepôt : {chemin} (python collecte/collecte.py "
                         f"{'etat_actionnaire_documents' if doc['dossier'] == DOCS else 'etat_actionnaire_valeur_portefeuille'})")
    lus: dict[int, list[str]] = {}
    with pdfplumber.open(chemin) as pdf:
        for page, citation in attendues:
            if not 1 <= page <= len(pdf.pages):
                raise SystemExit(f"{doc['fichier']} : page {page} absente ({len(pdf.pages)} pages)")
            if page not in lus:
                lus[page] = textes_page(pdf.pages[page - 1])
            if not any(citation in t for t in lus[page]):
                raise SystemExit(f"citation absente de {doc['fichier']}, page {page} : « {citation} »")


def _fr(x: float) -> str:
    """Nombre tel qu'écrit dans les documents : « 179,5 », « 1508 », « 128 »."""
    return (f"{x:.1f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)).replace(".", ",")


def _point(date: str, cle: str, montants: dict, citations: list[tuple[int, str]], note: str | None = None) -> dict:
    """Un relevé daté : chaque montant doit figurer dans l'une de ses citations, chaque citation à sa page."""
    for nom, v in montants.items():
        assert any(_fr(v) in c for _, c in citations), (date, nom, v)
    verifier_citations(cle, citations)
    p = {"date": date, "annee": int(date[:4]), **montants, "source": DOCS_VALEUR[cle]["titre"],
         "url": DOCS_VALEUR[cle]["url"], "citations": [{"page": page, "texte": c} for page, c in citations]}
    if note:
        p["note"] = note
    return p


def valeur_portefeuille() -> dict:
    """Valeur des participations : estimation de l'agence (30 juin) et valeur au bilan de l'État (31 décembre 2025),
    deux mesures publiées côte à côte, jamais additionnées. Contrôle aussi l'annexe des participations directes."""
    serie = [_point(d, cle, m, cits, note) for d, cle, m, cits, note in VALEUR_AGENCE]
    assert [p["date"] for p in serie] == sorted(p["date"] for p in serie)
    cle_m, page_m, cit_m = METHODE_AGENCE
    verifier_citations(cle_m, [(page_m, cit_m)])
    cle_d, page_d, cits_d = PARTICIPATIONS_DIRECTES
    verifier_citations(cle_d, [(page_d, c) for c in cits_d])
    d_c, cle_c, m_c, cits_c = COTEES_FIN_2025
    d_b, cle_b, m_b, cits_b = BILAN_ETAT
    bilan = _point(d_b, cle_b, m_b, cits_b)
    assert abs(bilan["entites_controlees_md"] + bilan["entites_non_controlees_md"] - bilan["valeur_md"]) < 0.15
    assert bilan["entites_controlees"] + bilan["entites_non_controlees"] == bilan["entites"]
    return {
        "definition": "Valeur des participations de l'État à une date donnée. Deux mesures sont publiées, chacune avec "
                      "son producteur, son périmètre et sa méthode : elles ne s'additionnent pas et ne se comparent pas "
                      "terme à terme. Une valeur n'est ni un prix de vente ni une somme disponible.",
        "agence": {
            "producteur": "Agence des participations de l'État",
            "perimetre": "entreprises relevant du périmètre de l'agence (85 au 30 juin 2024, 86 au 30 juin 2025)",
            "methode": "sociétés cotées : valeur boursière à la date indiquée ; sociétés non cotées : valeur comptable "
                       "des capitaux propres au 31 décembre de l'année précédente",
            "methode_citation": {"source": DOCS_VALEUR[cle_m]["titre"], "url": DOCS_VALEUR[cle_m]["url"],
                                 "page": page_m, "texte": cit_m},
            "statut": "approché",
            "unite": "milliards d'euros",
            "ordre": {"regle": "Dates croissantes ; chaque valeur est relevée dans le rapport de l'année suivante.",
                      "cles": ["date"]},
            "serie": serie,
            "cotees_fin_2025": {**_point(d_c, cle_c, m_c, cits_c), "statut": "approché"},
        },
        "bilan_etat": {
            "producteur": "Direction générale des Finances publiques (compte général de l'État)",
            "perimetre": "ensemble des participations de l'État au 31 décembre 2025 (entités contrôlées et non "
                         "contrôlées, établissements publics compris)",
            "methode": "entités contrôlées : valeur d'équivalence (part des capitaux propres détenue par l'État) ; "
                       "entités non contrôlées : valeur nette comptable (valeur brute diminuée des dépréciations)",
            "statut": "tracé",
            "unite": "milliards d'euros",
            **bilan,
        },
    }


# --- Entités nommées ---------------------------------------------------------------------------------------------------

def _tous_sirens() -> list[str]:
    return sorted(set(ENTITES.values()) | {s for s, _ in OPERATIONS_SENAT})


def collecter() -> int:
    """Catégorie juridique de chaque SIREN de la table (API Recherche d'entreprises) ; cache propre au module."""
    cache = json.loads(CACHE_ENTITES.read_text(encoding="utf-8")) if CACHE_ENTITES.exists() else {}
    for s in _tous_sirens():
        if s not in cache:
            entree = sirene._interroger(s)
            if entree is not None:
                cache[s] = entree
    CACHE_ENTITES.parent.mkdir(parents=True, exist_ok=True)
    CACHE_ENTITES.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    manquants = [s for s in _tous_sirens() if s not in cache]
    print(f"{len(cache)} SIREN vérifiés, {len(manquants)} sans réponse {manquants or ''}")
    return 1 if manquants else 0


def entite(siren: str | None, cache: dict) -> dict | None:
    """Entité publiable : SIREN valide, trouvé au répertoire, personne morale. Sinon None (ligne agrégée)."""
    e = cache.get(siren or "")
    if not e or not sirene.siren_valide(siren) or not e.get("trouve") or not sirene.personne_morale(e.get("cj")) \
            or not e.get("nom"):
        return None
    return {"siren": siren, "denomination": e["nom"], "categorie_juridique": str(e["cj"])}


def _categorie_source(libelle: str) -> str | None:
    n = _norm(libelle)
    if "entites non controlees" in n:
        return "Entités non contrôlées"
    if "entites controlees" in n:
        return "Entités contrôlées"
    return None


# --- Production --------------------------------------------------------------------------------------------------------

def _par_annee(d: dict) -> dict:
    return {str(a): {k: v for k, v in m.items() if v is not None} for a, m in sorted(d.items())
            if any(v is not None for v in m.values())}


def _fusion(*dicos: dict) -> dict:
    out: dict[int, dict] = {}
    for d in dicos:
        for a, m in d.items():
            out.setdefault(a, {}).update(m)
    return out


def _total(lignes: list[dict], codes=None) -> dict:
    """Somme par année et par mesure, seulement quand toutes les lignes retenues portent la mesure."""
    retenues = [l for l in lignes if codes is None or l["code"] in codes]
    out: dict[str, dict] = {}
    for a in sorted({a for l in retenues for a in l["par_annee"]}):
        presentes = [l["par_annee"][a] for l in retenues if a in l["par_annee"]]
        for mesure in sorted({k for p in presentes for k in p}):
            if all(mesure in p for p in presentes):
                out.setdefault(a, {})[mesure] = round(sum(p[mesure] for p in presentes), 2)
    return out


def _noeud_arbre(programme: str) -> dict | None:
    racine = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    pile = [racine]
    while pile:
        n = pile.pop()
        if n.get("niveau") == "programme" and n["id"].rsplit("/", 1)[-1] == programme:
            return n
        pile.extend(n.get("enfants", []))
    return None


def produire(sortie: Path = SORTIE) -> None:
    cache = json.loads(CACHE_ENTITES.read_text(encoding="utf-8")) if CACHE_ENTITES.exists() else {}
    pap = lire_pap()
    senat = lire_senat()
    collecte_le = date_sources("etat_actionnaire")
    ecarts: list[dict] = []

    # 1. Dividendes : lignes 2110, 2116, 2199 du budget général
    prev_div = previsions_dividendes()
    exec_div = {a: plrg_dividendes(a) for a in ANNEES_EXECUTION}
    lignes_div = []
    for code, lib in LIGNES_DIVIDENDES.items():
        pa = _fusion(prev_div[code], {a: exec_div[a][code]["mesures"] for a in ANNEES_EXECUTION})
        lignes_div.append({"code": code, "libelle": lib, "par_annee": _par_annee(pa)})
        for a, m in sorted(pa.items()):
            if m.get("lfi_eur") is not None and m.get("lfi_plrg_eur") is not None and abs(m["lfi_eur"] - m["lfi_plrg_eur"]) > 1:
                ecarts.append({"objet": f"ligne {code}, loi de finances initiale {a}", "annee": a,
                               "valeurs": [{"source": f"jeu « recettes du budget général » de la loi de finances {a}",
                                            "montant_eur": m["lfi_eur"]},
                                           {"source": f"PLRG {a}, annexe des recettes", "montant_eur": m["lfi_plrg_eur"]}],
                               "ecart_eur": round(m["lfi_plrg_eur"] - m["lfi_eur"], 2),
                               "lecture": "Les deux montants sont publiés ; aucun n'est retenu de préférence."})
    div = pap["dividendes"]
    serie_longue = {
        "source": f"{PAP['titre']}, page {pap['pages']['dividendes']}, tableau « Dividendes perçus par l’État actionnaire »",
        "url": PAP["url"], "unite": "milliards d'euros",
        "perimetre": "dividendes perçus par l'État actionnaire, par exercice budgétaire, en numéraire et en actions, "
                     "tels que publiés par le projet annuel de performances, qui n'en détaille pas la composition. "
                     "Cette série ne se compare pas terme à terme aux lignes 2110, 2116 et 2199 du budget général et "
                     "ne s'y additionne pas",
        "annees": div["annees"], "numeraire_md": div["numeraire_md"], "actions_md": div["actions_md"],
        "total_md": div["total_md"], "statuts": {"2025": "prévision au 30/08/2025"}}

    # 2. Compte d'affectation spéciale : recettes
    prev_cas, libelles = previsions_compte()
    exec_cas = {a: plrg_recettes_compte(a) for a in ANNEES_EXECUTION}
    soldes = {a: plrg_solde(a) for a in ANNEES_EXECUTION}
    lignes_rec = []
    for code, nature in NATURES_RECETTES.items():
        pa = _fusion(prev_cas[code],
                     {a: {k: exec_cas[a][code][k] for k in ("evaluation_eur", "execution_eur")}
                      for a in ANNEES_EXECUTION if code in exec_cas[a]},
                     {2025: {"lfi_eur": pap["recettes"][code]["lfi_2025"]},
                      2026: {"plf_eur": pap["recettes"][code]["prevision_2026"]}})
        detail = {str(a): [{"code": c, "libelle": lib, "execution_eur": v} for c, lib, v in exec_cas[a][code]["detail"]]
                  for a in ANNEES_EXECUTION if code in exec_cas[a] and exec_cas[a][code]["detail"]}
        lignes_rec.append({"code": code, "libelle": libelles[code], "nature": nature, "par_annee": _par_annee(pa),
                           "detail_execution": detail})
    total_rec = _total(lignes_rec)
    for a in ANNEES_EXECUTION:  # total d'exécution : situation comptable du compte, contrôlée par la somme des lignes
        somme = _somme(exec_cas[a][c]["execution_eur"] for c in exec_cas[a])
        assert abs(somme - soldes[a]["recettes_eur"]) <= 1, (a, somme, soldes[a])
        total_rec.setdefault(str(a), {})["execution_eur"] = soldes[a]["recettes_eur"]
    hors_bg = _total(lignes_rec, codes=set(NATURES_RECETTES) - {"06"})
    for a in ANNEES_EXECUTION:
        hors_bg.setdefault(str(a), {})["execution_eur"] = _somme(
            exec_cas[a][c]["execution_eur"] for c in exec_cas[a] if c != "06")
    sans_montant = [{"annee": a, "code": c, "libelle": lib} for a in ANNEES_EXECUTION for code in exec_cas[a]
                    for c, lib, v in exec_cas[a][code]["detail"] if v is None]

    # 3. Compte : dépenses par programme et par action
    dep = {a: plrg_depenses(a, "cs_cp", PROGRAMMES_COMPTE, True) for a in ANNEES_EXECUTION}
    plf25 = actions_plf2025()
    programmes = []
    for code, lib in PROGRAMMES_COMPTE.items():
        actions: dict[str, dict] = {}
        for act, (lib_a, cp) in sorted(plf25.get(code, {}).items()):
            actions[act] = {"code": act, "libelle": lib_a, "par_annee": {2025: {"plf_eur": cp}}}
        if code == "731":
            for c, a in sorted(pap["actions"].items()):
                if c == "total":
                    continue
                d = actions.setdefault(f"731-{c}", {"code": f"731-{c}", "libelle": a["libelle"], "par_annee": {}})
                d["par_annee"].setdefault(2025, {})["lfi_eur"] = a["lfi_2025"]
                d["par_annee"].setdefault(2026, {})["plf_eur"] = a["plf_2026"]
        pa = _fusion({a: dep[a].get(code, {}) for a in ANNEES_EXECUTION},
                     {2025: {"plf_eur": _somme(cp for _, cp in plf25.get(code, {}).values())}},
                     {2025: {"lfi_eur": pap["actions"]["total"]["lfi_2025"]},
                      2026: {"plf_eur": pap["actions"]["total"]["plf_2026"]}} if code == "731" else {})
        programmes.append({"code": code, "libelle": lib, "par_annee": _par_annee(pa),
                           "actions": [{**v, "par_annee": _par_annee(v["par_annee"])} for _, v in sorted(actions.items())]})
    total_dep = _total(programmes)
    for a in ANNEES_EXECUTION:
        somme = _somme(dep[a][p].get("execution_eur") for p in dep[a])
        assert abs(somme - soldes[a]["depenses_eur"]) <= 1, (a, somme, soldes[a])
    composition = [{"id": i, "libelle": lib, "annee": 2025, "montant_eur": float(montant), "citation": cit,
                    "page": senat["page_de"](cit)} for i, lib, montant, cit in COMPOSITION_SENAT]

    # 4. Budget général : programmes qui versent au compte
    bg = {a: plrg_depenses(a, "bg_cp", PROGRAMMES_BG, False) for a in ANNEES_EXECUTION}
    programmes_bg = []
    for code, lib in PROGRAMMES_BG.items():
        pa = _fusion({a: bg[a].get(code, {}) for a in ANNEES_EXECUTION},
                     {2025: {"plf_eur": _somme(cp for _, cp in plf25.get(code, {}).values())}})
        programmes_bg.append({"code": code, "libelle": lib, "par_annee": _par_annee(pa)})

    # 5. Écarts avec les totaux arrondis du Sénat (millions d'euros)
    controles_senat = []
    for ident, cit, vals in TOTAUX_SENAT:
        page = senat["page_de"](cit)
        ref = {"recettes": {"execution_2024": soldes[2024]["recettes_eur"], "execution_2025": soldes[2025]["recettes_eur"],
                            "lfi_2025": pap["recettes"]["total"]["lfi_2025"]},
               "depenses": {"execution_2024": soldes[2024]["depenses_eur"], "execution_2025": soldes[2025]["depenses_eur"],
                            "lfi_2025": pap["actions"]["total"]["lfi_2025"]}}[ident]
        for cle, m in sorted(vals.items()):
            mesure, annee = cle.rsplit("_", 1)
            objet = f"{'recettes' if ident == 'recettes' else 'dépenses'} du compte, " \
                    f"{'exécution' if mesure == 'execution' else 'loi de finances initiale'} {annee}"
            autre = f"PLRG {annee}, situation comptable des comptes spéciaux" if mesure == "execution" \
                else f"{PAP['titre']}"
            ecart = round(m * 1e6 - ref[cle], 2)
            controles_senat.append({"objet": objet, "senat_millions_eur": m, "autre_source_eur": ref[cle], "page": page})
            if abs(ecart) > 500_000:  # au-delà de l'arrondi au million
                ecarts.append({"objet": objet, "annee": int(annee),
                               "valeurs": [{"source": f"{SENAT['titre']}, page {page} (millions d'euros arrondis)",
                                            "montant_eur": m * 1e6},
                                           {"source": autre, "montant_eur": ref[cle]}],
                               "ecart_eur": ecart, "lecture": "Les deux montants sont publiés ; aucun n'est retenu de préférence."})

    entete_flux = "data.economie.gouv.fr (recettes du budget général et des comptes spéciaux, PLF 2024 et 2025, LFI 2023 ; " \
                  "dépenses selon destination, PLF 2025 ; annexes des PLRG 2023, 2024 et 2025) ; projet annuel de " \
                  "performances 2026 du compte ; Sénat, rapport n° 736 (2025-2026), tome II, annexe 21"
    flux = {
        "millesime": "Prévisions 2023 à 2026 (PLF, LFI), exécution 2023 à 2025 (PLRG) ; dividendes de l'État actionnaire 2014 à 2025",
        "source": entete_flux,
        "unite": "euros (série longue des dividendes : milliards d'euros)",
        "avertissement": "Flux bruts par année, en comptabilité budgétaire, sans qualification. Une recette de cession "
                         "ou une dépense en capital est une opération sur le patrimoine de l'État : elle ne dit rien de "
                         "la valeur des participations. Le versement du budget général au compte est un mouvement "
                         "interne à l'État. Les montants de sources différentes sont publiés côte à côte.",
        "collecte_le": collecte_le,
        "mesures": MESURES,
        "dividendes": {
            "definition": "Recettes non fiscales du budget général, section 21 « Dividendes et recettes assimilées » : "
                          "lignes 2110, 2116 et 2199. Elles ne transitent pas par le compte d'affectation spéciale.",
            "lignes": lignes_div, "total": _total(lignes_div), "serie_longue": serie_longue},
        "compte": {
            "nom": COMPTE, "type": "compte d'affectation spéciale",
            "recettes": {
                "lignes": lignes_rec, "total": total_rec, "hors_versement_budget_general": hors_bg,
                "note": "Total d'exécution : recettes de l'année à la situation comptable du compte (PLRG), égal à la "
                        "somme des lignes à un euro près. Une ligne absente d'une année n'a pas été publiée pour cette "
                        "année. Lignes d'exécution publiées sans montant : valeur absente (null), jamais zéro.",
                "lignes_sans_montant": sans_montant},
            "depenses": {
                "programmes": programmes, "total": total_dep,
                "note": "Exécution en crédits de paiement, connue par programme (PLRG). Le détail par action n'est "
                        "publié qu'en prévision (PLF 2025 : jeu de données ; LFI 2025 et PLF 2026 : projet annuel de "
                        "performances 2026). Les augmentations de capital, dotations en fonds propres et avances "
                        "d'actionnaire forment l'action 731-01.",
                "composition_2025_citee": {
                    "source": SENAT["titre"], "url": SENAT["url"],
                    "note": "Montants arrondis au million cités dans le texte de l'annexe ; les trois ensembles ne "
                            "couvrent pas toute la dépense du programme 731.",
                    "elements": composition}},
            "solde": {"definition": "solde reporté en début d'année, recettes et dépenses de l'année, solde reporté en "
                                    "fin d'année (situation comptable des comptes spéciaux, PLRG)",
                      "par_annee": {str(a): soldes[a] for a in ANNEES_EXECUTION}}},
        "budget_general_vers_compte": {
            "note": "Programmes du budget général dont la dépense est un versement au compte (ligne 06 de ses "
                    "recettes). Les autres versements (programmes de la mission « Investir pour la France de 2030 » "
                    "notamment) ne sont pas isolés par les annexes du PLRG.",
            "programmes": programmes_bg},
        "ecarts_entre_sources": ecarts,
        "rapprochement_senat": {
            "source": SENAT["titre"], "url": SENAT["url"],
            "note": "Totaux du compte publiés par le Sénat en millions d'euros arrondis, face au montant en euros d'une "
                    "autre source. Un écart supérieur à l'arrondi (500 000 €) est repris dans « ecarts_entre_sources ».",
            "totaux": controles_senat},
    }

    # 6. Entités : dividendes par ligne d'exécution, opérations de 2025 citées par le Sénat
    lignes_ex: dict[str, dict] = {}
    for a in ANNEES_EXECUTION:
        for ligne, d in exec_div[a].items():
            for c, (lib, v) in d["execution"].items():
                e = lignes_ex.setdefault(c, {"ligne": ligne, "code_execution": c, "libelle_source": lib, "execution_eur": {}})
                e["libelle_source"] = lib  # libellé de l'année la plus récente
                e["execution_eur"][str(a)] = v
    publiees, agregat = [], {"nombre": 0, "execution_eur": {}}
    for c in sorted(lignes_ex):
        e = lignes_ex[c]
        ent = entite(ENTITES.get(c), cache)
        if ent is None and c not in LIGNES_GENERIQUES:  # entité non vérifiée : jamais nommée, montants agrégés
            agregat["nombre"] += 1
            for a, v in e["execution_eur"].items():
                if v is not None:
                    agregat["execution_eur"][a] = round(agregat["execution_eur"].get(a, 0.0) + v, 2)
            continue
        ligne = {"ligne": e["ligne"], "code_execution": c, "libelle_source": e["libelle_source"],
                 "categorie_source": _categorie_source(e["libelle_source"]), "entite": ent,
                 "execution_eur": {str(a): e["execution_eur"].get(str(a)) for a in ANNEES_EXECUTION
                                   if str(a) in e["execution_eur"]}}
        if ent and c in NOTES_ENTITES:
            ligne["note"] = NOTES_ENTITES[c]
        publiees.append(ligne)
    for a in ANNEES_EXECUTION:  # conservation : lignes publiées + agrégat = total des trois lignes
        somme = _somme([l["execution_eur"].get(str(a)) for l in publiees] + [agregat["execution_eur"].get(str(a))])
        attendu = _somme(exec_div[a][c]["mesures"]["execution_eur"] for c in LIGNES_DIVIDENDES)
        assert abs(somme - attendu) <= 1, (a, somme, attendu)
    operations, non_nommees = [], 0
    for siren, mentions in OPERATIONS_SENAT:
        ent = entite(siren, cache)
        ms = [{"nature": nat, "montant_eur": float(montant), "citation": cit, "page": senat["page_de"](cit)}
              for nat, montant, cit in mentions]
        if ent is None:
            non_nommees += 1
            continue
        operations.append({"annee": 2025, "entite": ent, "mentions": ms})
    entites = {
        "millesime": "Exécution 2023 à 2025 (dividendes par ligne d'exécution) ; opérations de 2025 citées par le Sénat",
        "source": "data.economie.gouv.fr, annexes des PLRG 2023, 2024 et 2025 (recettes du budget général par ligne "
                  "d'exécution) ; Sénat, rapport n° 736 (2025-2026), tome II, annexe 21 ; API Recherche d'entreprises "
                  "(catégorie juridique)",
        "unite": "euros",
        "avertissement": "Montants versés au budget général par ligne d'exécution, tels que publiés. Le libellé est "
                         "celui de la nomenclature budgétaire, parfois ancien (par exemple « France TELECOM », "
                         "« GDF-SUEZ », « DCNS ») ; la dénomination actuelle est celle du répertoire Sirene. Un montant "
                         "reçu une année ne mesure ni le résultat ni la valeur de l'entité.",
        "collecte_le": collecte_le,
        "regle_personnes": "Une entité n'est nommée que si son SIREN, rapproché du libellé par le projet, est celui "
                           "d'une personne morale au répertoire Sirene. Une ligne dont l'entité n'est pas vérifiée "
                           "est comptée dans « non_verifiees », sans nom. Aucune personne physique n'est nommée.",
        "ordre": {"regle": "Lignes par code de ligne d'exécution croissant (nomenclature budgétaire) ; opérations dans "
                           "l'ordre du texte du Sénat.", "cles": ["code_execution"]},
        "annees": ANNEES_EXECUTION,
        "dividendes_par_ligne_d_execution": publiees,
        "non_verifiees": agregat,
        "operations_citees": {
            "source": SENAT["titre"], "url": SENAT["url"],
            "note": "Montants arrondis au million relevés dans le texte de l'annexe (pages indiquées), chacun avec sa "
                    "citation exacte. Deux montants différents cités pour une même opération sont tous deux publiés. Le "
                    "tableau des opérations par entreprise, publié en image dans ce document, n'est pas repris : sa "
                    "lecture automatique n'est pas fiable.",
            "operations": operations, "non_nommees": non_nommees},
    }

    # 7. Insee : sociétés contrôlées majoritairement par l'État
    insee = lire_insee()
    societes = {
        "millesime": f"Fin {insee['serie'][0]['annee']} à fin {insee['serie'][-1]['annee']} (activités : fin 2021 et fin 2022)",
        "source": f"{INSEE['titre']} ({INSEE['page']})",
        "unite": "nombre de sociétés, effectifs salariés, % de l'emploi salarié total",
        "avertissement": "Champ de l'Insee : sociétés dont l'État détient, directement ou non, la majorité du capital "
                         "ou des droits de vote, hors filiales et participations à l'étranger. Ce champ diffère de celui "
                         "des lignes budgétaires, qui comptent aussi des participations minoritaires. « s » à la "
                         "source (secret statistique) : valeur absente (null), jamais zéro.",
        "collecte_le": collecte_le, "url": INSEE["url"],
        "serie": insee["serie"], "activites": insee["activites"],
        "ordre": {"regle": "Années croissantes ; activités dans l'ordre du tableau de l'Insee.", "cles": ["annee"]},
    }

    # 8. Index : fichiers, sources, liens avec recettes.json et l'arbre du budget général
    recettes_site = json.loads((SITE / "recettes.json").read_text(encoding="utf-8"))
    arbre = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    noeuds = []
    for code, lib in PROGRAMMES_BG.items():
        n = _noeud_arbre(code)
        ex24 = bg[2024].get(code, {}).get("execution_eur")
        noeuds.append({"programme": code, "nom": lib, "present": n is not None,
                       "id": n["id"] if n else None, "md": n["md"] if n else None,
                       "execution_2024_plrg_eur": ex24,
                       "relation": "dépense du budget général versée au compte (ligne 06 de ses recettes)"
                                   + (", employée par le programme 732" if code == "369" else "")})

    def dernier(l, mesure="execution_eur", a="2025"):
        return l.get(a, {}).get(mesure)

    valeur = valeur_portefeuille()
    index = {
        "millesime": f"{flux['millesime']} ; valeur des participations au 30 juin 2022 à 2025 (estimation de l'Agence "
                     f"des participations de l'État) et au 31 décembre 2025 (compte général de l'État)",
        "source": f"{entete_flux} ; Insee, sociétés contrôlées majoritairement par l'État fin 2022 ; rapports relatifs "
                  f"à l'État actionnaire 2024 et 2025 (annexes aux PLF) ; rapport annuel de performances 2025 du "
                  f"compte ; rapport de présentation du compte général de l'État 2025",
        "unite": "euros (détail dans chaque fichier ; valeur des participations : milliards d'euros)",
        "avertissement": "Dividendes reçus, cessions et opérations en capital de l'État, présentés comme flux bruts "
                         "par année. Aucun montant n'est qualifié ; un écart entre deux sources est publié sans être "
                         "tranché. Ces flux ne mesurent pas la valeur des participations de l'État, publiée à part avec "
                         "son producteur, son périmètre et sa méthode.",
        "collecte_le": collecte_le,
        "definitions": {
            "valeur_portefeuille": "valeur des participations à une date donnée : estimation de l'Agence des "
                                   "participations de l'État pour son périmètre, ou valeur au bilan de l'État (compte "
                                   "général) ; deux mesures distinctes, jamais additionnées",
            "dividendes": "produits des participations versés au budget général (lignes 2110, 2116, 2199 des recettes "
                          "non fiscales)",
            "cessions": "ligne 01 des recettes du compte : produit des cessions de titres, parts ou droits de sociétés "
                        "détenus directement par l'État",
            "recapitalisations": "action 731-01 du compte : augmentations de capital, dotations en fonds propres, "
                                 "avances d'actionnaire et prêts assimilés ; connue par action en prévision, par "
                                 "programme en exécution",
            "versement_budget_general": "ligne 06 des recettes du compte : crédits du budget général transférés au "
                                        "compte, mouvement interne à l'État",
            "compte": "compte d'affectation spéciale « Participations financières de l'État » : il retrace les "
                      "opérations patrimoniales, hors gestion courante ; les dividendes n'y figurent pas",
        },
        "fichiers": [
            {"fichier": "etat_actionnaire/flux.json", "contenu": "dividendes, recettes et dépenses du compte, solde, "
                                                                  "programmes du budget général qui versent au compte, écarts entre sources"},
            {"fichier": "etat_actionnaire/entites.json", "contenu": "dividendes par ligne d'exécution et par entité "
                                                                     "(personnes morales), opérations de 2025 citées par le Sénat"},
            {"fichier": "etat_actionnaire/societes_controlees.json",
             "contenu": "sociétés contrôlées majoritairement par l'État : nombre, effectifs, activités (Insee)"},
        ],
        "chiffres_cles": {
            "annee": 2025, "mesure": "exécution (PLRG 2025)",
            "dividendes_eur": dernier(flux["dividendes"]["total"]),
            "cessions_eur": dernier(lignes_rec[0]["par_annee"]),
            "versement_budget_general_eur": dernier(lignes_rec[5]["par_annee"]),
            "recettes_compte_eur": dernier(total_rec),
            "depenses_programme_731_eur": dernier(programmes[0]["par_annee"]),
            "depenses_programme_732_eur": dernier(programmes[1]["par_annee"]),
            "solde_compte_fin_eur": soldes[2025]["fin_eur"],
            "societes_controlees": {"annee": insee["serie"][-1]["annee"], "nombre": insee["serie"][-1]["societes"]},
        },
        "liens": {
            "recettes": {
                "fichier": "recettes.json", "millesime": recettes_site["millesime"], "source_fichier": recettes_site["source"],
                "relation": "recettes.json recense les impôts par administration, en comptabilité nationale (Eurostat). "
                            "Les produits des participations sont des recettes non fiscales, suivies ici en "
                            "comptabilité budgétaire : ils n'y figurent pas et les deux séries ne s'additionnent pas."},
            "arbre": {
                "fichier": "arbre/racine.json", "millesime": arbre["millesime"],
                "relation": "L'arbre couvre le budget général. Les programmes 731 et 732 appartiennent à un compte "
                            "d'affectation spéciale et n'y figurent pas ; les programmes 367 et 369 du budget général, "
                            "qui versent au compte, y figurent quand ils portent une dépense.",
                "noeuds": noeuds},
        },
        "sources": [
            {"id": "etat_actionnaire_plf25_recettes_bg", "titre": "PLF 2025, recettes du budget général",
             "url": f"{ODS}/plf25-recettes-du-budget-general/", "licence": "Licence Ouverte 2.0"},
            {"id": "etat_actionnaire_plf24_recettes_bg", "titre": "PLF 2024, recettes du budget général (PLF et LFI)",
             "url": f"{ODS}/plf-2024-recettes-du-budget-general/", "licence": "Licence Ouverte 2.0"},
            {"id": "etat_actionnaire_plf25_recettes_cas", "titre": "PLF 2025, recettes des comptes d'affectation spéciale et des comptes de concours financiers",
             "url": f"{ODS}/plf25-recettes-des-cas-et-des-ccf/", "licence": "Licence Ouverte 2.0"},
            {"id": "etat_actionnaire_plf24_recettes_cas", "titre": "PLF 2024, recettes des comptes d'affectation spéciale et des comptes de concours financiers (PLF et LFI)",
             "url": f"{ODS}/plf-2024-recettes-des-cas-et-ccf/", "licence": "Licence Ouverte 2.0"},
            {"id": "etat_actionnaire_lfi23_recettes_cas", "titre": "LFI 2023, recettes des comptes d'affectation spéciale et des comptes de concours financiers (PLF et LFI)",
             "url": f"{ODS}/cas-ccf-recettes-lf-2023/", "licence": "Licence Ouverte 2.0"},
            {"id": "etat_actionnaire_plf25_depenses_destination", "titre": "PLF 2025, dépenses 2025 selon destination (programmes 731, 732, 367, 369)",
             "url": f"{ODS}/plf25-depenses-2025-selon-destination/", "licence": "Licence Ouverte 2.0"},
            {"id": "etat_actionnaire_plrg_annexes", "titre": "PLRG 2023, 2024 et 2025, annexes : recettes, dépenses, recouvrements et situation comptable des comptes spéciaux",
             "url": f"{ODS}/projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-lannee-plrg-2025/",
             "licence": "Licence Ouverte 2.0"},
            {"id": "etat_actionnaire_documents", "titre": INSEE["titre"], "url": INSEE["url"], "licence": "Licence Ouverte 2.0"},
            {"id": "etat_actionnaire_documents", "titre": SENAT["titre"], "url": SENAT["url"], "licence": "document parlementaire public"},
            {"id": "etat_actionnaire_documents", "titre": PAP["titre"], "url": PAP["url"], "licence": "document budgétaire public"},
            *({"id": "etat_actionnaire_valeur_portefeuille", "titre": DOCS_VALEUR[c]["titre"], "url": DOCS_VALEUR[c]["url"],
               "licence": "document budgétaire public"} for c in ("jaune_2024", "jaune_2025", "rap_2025", "cge_2025")),
        ],
        "sources_inaccessibles": [
            {"source": "Agence des participations de l'État, site de l'agence (rapports annuels et d'activité, "
                       "portefeuille) : la valeur au 30 juin 2025 est reprise du projet annuel de performances 2026",
             "motif": "refus d'accès HTTP 403, non contourné", "constate_le": "2026-11-18"}],
        "valeur_portefeuille": valeur,
        "limites": [
            "Valeur des participations : estimation publiée une fois par an par l'Agence des participations de l'État "
            "pour son seul périmètre (au 30 juin) ; elle mêle valeur boursière et valeur comptable. La valeur au bilan "
            "de l'État couvre un autre périmètre avec une autre méthode : les deux ne s'additionnent pas.",
            "La liste des entreprises du périmètre de l'agence, publiée dans son rapport annuel, n'est pas reprise : "
            "seules les entités des lignes de dividendes, vérifiées au répertoire Sirene, sont nommées.",
            "Montants par entreprise : seuls les dividendes versés au budget général sont publiés par entité (lignes "
            "d'exécution du PLRG). Les cessions et les opérations en capital ne sont pas publiées par entreprise en "
            "données ouvertes ; les opérations de 2025 reprises viennent du texte de l'annexe du Sénat.",
            "Le tableau des opérations par entreprise de l'annexe du Sénat est une image : il n'est pas repris.",
            "Le projet annuel de performances 2026 décrit des opérations prévues en 2026 par entreprise : elles ne sont "
            "pas reprises (prévisions rédigées en texte libre).",
            "Exécution par action du programme 731 : non publiée par les annexes du PLRG.",
            "Dividendes : pas de prévision 2026 par ligne dans les jeux collectés.",
        ],
        "ecarts_entre_sources": {"nombre": len(ecarts), "fichier": "etat_actionnaire/flux.json"},
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }

    for nom, doc in (("flux.json", flux), ("entites.json", entites), ("societes_controlees.json", societes), ("index.json", index)):
        _ecrire(sortie / nom, doc)
    print(f"etat_actionnaire : 4 fichiers dans {sortie} ; {len(publiees)} lignes d'exécution publiées, "
          f"{agregat['nombre']} agrégées ; {len(ecarts)} écart(s) entre sources")


def _ecrire(chemin: Path, doc: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("collecter")
    p = sp.add_parser("produire")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.cmd == "collecter":
        return collecter()
    produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
