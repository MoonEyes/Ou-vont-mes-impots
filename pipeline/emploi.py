"""Emploi et assurance chômage : comptes de l'Unédic, financement de France Travail, activité partielle, aides à l'embauche.

Agrégats publiés seulement (aucune donnée individuelle, aucun employeur nommé). La formation professionnelle et
l'apprentissage restent dans `formation/` (pipeline/formation.py) ; les dépenses de l'Unédic de l'année sont aussi
dans l'arbre de `secu/`, l'allocation chômage dans `prestations/` et France Travail dans `operateurs/` : ce module y
renvoie par des liens (fichier + identifiant), sans additionner les montants des différentes vues.

Entrées : entrepôt brut data/lake/emploi/ (non versionné), rempli par `collecter` :
    unedic_financement.csv          Unédic, « Dépenses et recettes de l'Assurance chômage » (M€, 2011 à 2025)
    unedic_indicateurs_france.csv   Unédic, « Indicateurs de suivi de l'Assurance chômage - total France » (mensuel)
    unedic_activite_partielle_2022.xlsx
                                    Unédic, « Activité partielle : état des lieux et perspectives » (février 2022),
                                    graphiques et tableaux (dépenses de l'État et de l'Unédic depuis 2007, consommation
                                    mensuelle 2020-2021, heures par secteur)
    urssaf_chomage_partiel_na38.csv Urssaf, masse salariale et assiette chômage partiel trimestrielles, secteur NA38
    dares_aej.xlsx                  Dares (ASP, DGEFP), recours à l'aide à l'embauche des jeunes (au 5 mars 2022)
  et, déjà publiés par d'autres étapes : site/data/operateurs/operateurs.json (France Travail, jaunes budgétaires),
  site/data/programmes/102.json et 103.json (PLF 2025 par sous-action), site/data/arbre/*_102.json et *_103.json
  (exécution 2024 par action).
Sorties (site/data/emploi/, contrat docs/contrat_interface.md, schémas docs/schemas/emploi_*.schema.json) :
    index.json, unedic.json, france_travail.json, activite_partielle.json, aides_embauche.json

Commandes :
    python pipeline/emploi.py collecter [--forcer]   (réseau ; reprises espacées ; un refus 401/403/429 est noté,
                                                      jamais contourné)
    python pipeline/emploi.py produire               (sans réseau)

Règles :
  - les montants de sources différentes sont publiés côte à côte, avec leurs écarts, jamais additionnés ;
  - aucune estimation de montant n'est faite à partir d'un nombre d'aides ou d'heures ;
  - une valeur absente ou couverte par le secret statistique (« nd ») est null, avec mention, jamais 0 ;
  - toute date écrite vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BRUT = ROOT / "data" / "lake" / "emploi"
MANIFESTE = ROOT / "data" / "lake" / "manifest.json"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "emploi"
LO = "Licence Ouverte 2.0"
UNEDIC = "https://data.unedic.org"
URSSAF = "https://open.urssaf.fr"
UA = {"User-Agent": "ou-vont-mes-impots/pipeline (projet citoyen open source)"}
MILLION = 1_000_000

SOURCES = {
    "unedic_financement": {
        "fichier": "unedic_financement.csv",
        "url": f"{UNEDIC}/api/explore/v2.1/catalog/datasets/financement-de-l-assurance-chomage/exports/csv"
               "?use_labels=true",
        "page": f"{UNEDIC}/explore/dataset/financement-de-l-assurance-chomage/",
        "titre": "Unédic, « Dépenses et recettes de l'Assurance chômage » : recettes, dépenses, soldes et dette de "
                 "l'Assurance chômage par année (M€)",
        "producteur": "Unédic", "millesime": "2011 à 2025", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft, mis à jour le 1er septembre 2026)",
    },
    "unedic_indicateurs": {
        "fichier": "unedic_indicateurs_france.csv",
        "url": f"{UNEDIC}/api/explore/v2.1/catalog/datasets/indicateurs-de-suivi-de-lassurance-chomage-total-france/"
               "exports/csv?use_labels=true",
        "page": f"{UNEDIC}/explore/dataset/indicateurs-de-suivi-de-lassurance-chomage-total-france/",
        "titre": "Unédic, « Indicateurs de suivi de l'Assurance chômage - total France » : allocataires indemnisés et "
                 "dépense d'allocation, par mois",
        "producteur": "Unédic", "millesime": "janvier 2007 à décembre 2025", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft ; sommes et moyennes annuelles calculées ici)",
    },
    "unedic_activite_partielle": {
        "fichier": "unedic_activite_partielle_2022.xlsx",
        "url": f"{UNEDIC}/api/explore/v2.1/catalog/datasets/activite-partielle-etat-des-lieux-et-perspectives-"
               "fevrier-2022/attachments/activite_partielle_etat_des_lieux_et_perspectives_fevrier_2022_graphiques_"
               "et_tableaux_xlsx",
        "page": f"{UNEDIC}/explore/dataset/activite-partielle-etat-des-lieux-et-perspectives-fevrier-2022/",
        "titre": "Unédic, « Activité partielle : état des lieux et perspectives » (février 2022), classeur des "
                 "graphiques et tableaux : tableau 5 (dépenses de l'État et de l'Unédic depuis 2007), tableau 6 "
                 "(consommation par mois de recours, d'après les demandes d'indemnisation de l'ASP), graphique 5 et "
                 "tableau 2 (heures par secteur)",
        "producteur": "Unédic (d'après ASP, Dares, DGEFP)", "millesime": "2007 à 2021 (2021 provisoire)",
        "licence": LO,
        "verdict": "réutilisable tel quel (classeur figé ; aucune mise à jour publiée depuis février 2022)",
    },
    "urssaf_chomage_partiel": {
        "fichier": "urssaf_chomage_partiel_na38.csv",
        "url": f"{URSSAF}/api/explore/v2.1/catalog/datasets/assiette-chomage-partiel-trimestrielle-du-secteur-prive-"
               "par-na38/exports/csv?use_labels=false&delimiter=%3B",
        "page": f"{URSSAF}/explore/dataset/assiette-chomage-partiel-trimestrielle-du-secteur-prive-par-na38/",
        "titre": "Urssaf, « Masse salariale et assiette chômage partiel trimestrielles du secteur privé, France "
                 "entière x secteur NA38 » : indemnités d'activité partielle déclarées par les employeurs",
        "producteur": "Urssaf Caisse nationale", "millesime": "2018 à 2026 (trimestriel)", "licence": "ODbL",
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft ; sommes annuelles calculées ici)",
    },
    "dares_aej": {
        "fichier": "dares_aej.xlsx",
        "url": "https://static.data.gouv.fr/resources/donnees-sur-le-recours-a-laide-a-lembauche-des-jeunes/"
               "20220317-153415/aej-open-data-17-03.xlsx",
        "page": "https://www.data.gouv.fr/fr/datasets/donnees-sur-le-recours-a-laide-a-lembauche-des-jeunes/",
        "titre": "Dares, « Données sur le recours à l'aide à l'embauche des jeunes » (NOE, ASP, DGEFP, au 5 mars "
                 "2022) : aides validées par semaine, secteur (groupe de la NAF) et département de l'employeur",
        "producteur": "Dares (d'après ASP et DGEFP)", "millesime": "aides validées de novembre 2020 à mars 2022",
        "licence": LO, "verdict": "réutilisable tel quel (classeur ; « nd » = moins de 5 aides, secret statistique)",
    },
}

DEJA_PUBLIES = {
    "operateurs": {"fichiers": ["operateurs/operateurs.json"], "titre": "Opérateurs de l'État, jaunes budgétaires des "
                   "PLF 2024 à 2026 (pipeline/operateurs.py) : financement de France Travail par l'État"},
    "programmes": {"fichiers": ["programmes/102.json", "programmes/103.json"], "titre": "PLF 2025, dépenses selon "
                   "destination et nature, par sous-action (pipeline/transform.py)"},
    "arbre_etat": {"fichiers": ["arbre/*_102.json", "arbre/*_103.json"], "titre": "Exécution 2024 du budget de l'État "
                   "par action (pipeline/arbre.py)"},
}

INACCESSIBLES = [
    {"source": "Dares, « L'activité partielle » (séries mensuelles d'heures indemnisées, de salariés et de montants "
               "par secteur, dares.travail-emploi.gouv.fr)",
     "motif": "page de vérification anti-robot (« Vérification de sécurité ») constatée le 18/11/2026 : non collecté, "
              "non contourné ; les heures indemnisées par secteur ne sont publiées ici que pour mars 2020 à décembre "
              "2021 (étude de l'Unédic) et les montants par secteur et par année viennent de l'Urssaf"},
    {"source": "Portail de données de la Dares (data.dares.travail-emploi.gouv.fr)",
     "motif": "aucun jeu sur l'activité partielle ni sur les aides à l'embauche dans le catalogue (33 jeux, relevé le "
              "18/11/2026)"},
    {"source": "France Travail, comptes financiers et rapports financiers annuels (ressources par financeur, "
               "dépenses par section)",
     "motif": "aucun jeu ouvert (14 jeux de France Travail sur data.gouv.fr, aucun budgétaire) ; documents PDF non "
              "repris ; le financement par l'État vient des jaunes budgétaires (operateurs/), celui de l'Unédic de "
              "ses comptes"},
    {"source": "Aides à l'embauche autres que l'aide à l'embauche des jeunes (emplois francs, aide à l'embauche en "
               "PME 2016-2017, aide exceptionnelle aux contrats de professionnalisation) : bénéficiaires et montants "
               "par année",
     "motif": "aucun jeu ouvert trouvé (data.gouv.fr, portail de la Dares) ; seuls les crédits de l'État par "
              "action (exécution 2024) et sous-action (PLF 2025) sont publiés"},
    {"source": "Exécution par sous-action des programmes 102 et 103 (activité partielle, emplois francs) avant 2024",
     "motif": "non diffusée en jeu ouvert à ce niveau ; les rapports annuels de performance (PDF) ne sont pas repris"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Les producteurs publient déjà les agrégats (Unédic, Urssaf, Dares sur data.gouv.fr) : ils sont "
                  "repris tels quels. Aucun dépôt public ne réunit les comptes de l'Unédic, le financement de France "
                  "Travail et l'activité partielle avec leurs écarts : module écrit pour le dépôt.",
    "trouvailles": [
        {"nom": "Unédic, Dépenses et recettes de l'Assurance chômage", "url": SOURCES["unedic_financement"]["page"],
         "licence": LO, "mise_a_jour": "2026-09-01", "verdict": "réutilisable tel quel"},
        {"nom": "Unédic, Indicateurs de suivi de l'Assurance chômage", "url": SOURCES["unedic_indicateurs"]["page"],
         "licence": LO, "mise_a_jour": "2026-07-02", "verdict": "réutilisable tel quel"},
        {"nom": "Unédic, Activité partielle : état des lieux et perspectives (février 2022)",
         "url": SOURCES["unedic_activite_partielle"]["page"], "licence": LO, "mise_a_jour": "2022-10-06",
         "verdict": "réutilisable tel quel"},
        {"nom": "Urssaf, Masse salariale et assiette chômage partiel par secteur NA38",
         "url": SOURCES["urssaf_chomage_partiel"]["page"], "licence": "ODbL", "mise_a_jour": "2026-08-28",
         "verdict": "réutilisable tel quel"},
        {"nom": "Dares, recours à l'aide à l'embauche des jeunes", "url": SOURCES["dares_aej"]["page"],
         "licence": LO, "mise_a_jour": "2022-03-17", "verdict": "réutilisable tel quel"},
        {"nom": "Etalab, dashboard-aides-entreprises (demandes d'activité partielle 2020 par région et secteur)",
         "url": "https://github.com/etalab/dashboard-aides-entreprises", "licence": "non précisée sur le dépôt",
         "dernier_commit": "non relevé (API GitHub non accessible depuis la session)",
         "verdict": "inspiration seulement (heures demandées, pas indemnisées ; arrêté fin 2020)"},
        {"nom": "Urssaf, indemnisation de l'activité partielle des salariés des particuliers employeurs (2020-2021)",
         "url": f"{URSSAF}/explore/dataset/mesures-exceptionnelles-covid-19-indemnisation-activite-partielle-emploi-"
                "domicil/", "licence": "ODbL", "mise_a_jour": "2022-08-30",
         "verdict": "inspiration seulement (champ particulier, non repris)"},
    ],
}

# Colonnes du jeu « Dépenses et recettes » (ordre de la source) -> clé publiée.
COLONNES_FINANCEMENT = [
    ("recettes_total", "Recettes totales"),
    ("recettes_contributions", "Contributions d'Assurance chômage assises sur les salaires bruts"),
    ("recettes_csg", "Part de la CSG sur les revenus d'activité reçue en compensation de l'ancienne part salariale "
                     "(depuis 2019)"),
    ("recettes_autres", "Autres produits, dont contribution au contrat de sécurisation professionnelle"),
    ("depenses_total", "Dépenses totales"),
    ("depenses_allocations", "Allocations versées (ARE, AREF, ASP, AREP, ATI et autres) et aides (ARCE et autres)"),
    ("depenses_retraites", "Financement des points de retraite complémentaire des allocataires indemnisés"),
    ("depenses_activite_partielle", "Dépenses d'activité partielle de l'Unédic"),
    ("depenses_france_travail", "Financement de Pôle emploi, devenu France Travail, et frais de recouvrement"),
    ("depenses_autres", "Frais de gestion et charges financières"),
    ("solde_technique", "Recettes totales moins dépenses totales"),
    ("elements_exceptionnels", "Produits et charges d'événements non récurrents"),
    ("solde_financier", "Solde après éléments exceptionnels"),
    ("dette", "Encours total de dette moins la trésorerie disponible (signe de la source : négatif = dette nette)"),
]
RECETTES = ["recettes_contributions", "recettes_csg", "recettes_autres"]
DEPENSES = ["depenses_allocations", "depenses_retraites", "depenses_activite_partielle", "depenses_france_travail",
            "depenses_autres"]

# Sections de la NAF rév. 2 par division (deux premiers chiffres).
SECTIONS_NAF = [
    ("A", 1, 3, "Agriculture, sylviculture et pêche"), ("B", 5, 9, "Industries extractives"),
    ("C", 10, 33, "Industrie manufacturière"),
    ("D", 35, 35, "Production et distribution d'électricité, de gaz, de vapeur et d'air conditionné"),
    ("E", 36, 39, "Production et distribution d'eau ; assainissement, gestion des déchets et dépollution"),
    ("F", 41, 43, "Construction"), ("G", 45, 47, "Commerce ; réparation d'automobiles et de motocycles"),
    ("H", 49, 53, "Transports et entreposage"), ("I", 55, 56, "Hébergement et restauration"),
    ("J", 58, 63, "Information et communication"), ("K", 64, 66, "Activités financières et d'assurance"),
    ("L", 68, 68, "Activités immobilières"), ("M", 69, 75, "Activités spécialisées, scientifiques et techniques"),
    ("N", 77, 82, "Activités de services administratifs et de soutien"),
    ("O", 84, 84, "Administration publique"), ("P", 85, 85, "Enseignement"),
    ("Q", 86, 88, "Santé humaine et action sociale"), ("R", 90, 93, "Arts, spectacles et activités récréatives"),
    ("S", 94, 96, "Autres activités de services"),
    ("T", 97, 98, "Activités des ménages en tant qu'employeurs"),
    ("U", 99, 99, "Activités extra-territoriales"),
]

LECTURES = {
    "ap_unedic": "même organisme, deux comptages : l'étude de 2022 retient selon les années les versements de "
                 "l'année ou les montants consommés au titre de l'année (2015, 2020, 2021, cette dernière "
                 "provisoire), les comptes annuels retiennent les charges comptables de l'exercice",
    "allocations": "champs différents : les comptes comptent toutes les allocations et aides (dont ARCE, aide à la "
                   "création d'entreprise) ; l'indicateur mensuel suit la dépense d'allocation du mois",
    "ap_indemnite_allocation": "deux grandeurs différentes, comparées sans être additionnées : l'Urssaf mesure les "
                               "indemnités versées par les employeurs à leurs salariés (assiette déclarée) ; l'Unédic "
                               "mesure l'allocation remboursée aux employeurs par l'État et l'Unédic",
}


# --- Utilitaires ------------------------------------------------------------------------------------------------------

def chemin(cle: str) -> Path:
    return BRUT / SOURCES[cle]["fichier"]


def _nombre(v):
    """Nombre ou None (vide, « nd », « - », texte) ; jamais 0 pour une absence."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    t = str(v).replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    if t in ("", "-", "nd", "nc", "s", "ns"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _meur(v) -> int | None:
    """M€ de la source -> euros entiers (None si absent)."""
    n = _nombre(v)
    return None if n is None else int(round(n * MILLION))


def _arrondi(v, d: int = 1):
    if v is None:
        return None
    r = round(float(v), d)
    return int(r) if r == int(r) else r


def _code_libelle(texte: str) -> tuple[str, str]:
    """« IZ Hébergement et restauration » ou « IZ : Hébergement... » -> (« IZ », « Hébergement... »)."""
    t = " ".join(str(texte).split())
    code, _, reste = t.partition(" ")
    reste = reste.lstrip(": ").strip()
    return code.strip(), reste[:1].upper() + reste[1:]


def section_naf(code: str) -> str | None:
    try:
        div = int(str(code)[:2])
    except ValueError:
        return None
    return next((s for s, a, b, _ in SECTIONS_NAF if a <= div <= b), None)


def departement(code: str) -> str:
    c = str(code).strip().upper()
    return c[1:] if len(c) == 3 and c.startswith("0") else c


def _ecart(objet: str, annee, source: str, valeur, autre_source: str, autre_valeur, lecture: str) -> dict | None:
    if valeur is None or autre_valeur is None:
        return None
    d = valeur - autre_valeur
    return {"objet": objet, "annee": annee, "source": source, "valeur": valeur, "autre_source": autre_source,
            "autre_valeur": autre_valeur, "ecart": d,
            "ecart_pct": round(d / autre_valeur * 100, 1) if autre_valeur else None, "lecture_ecart": lecture}


def _charger(rel: str):
    p = SITE / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def fichier_programme(numero: str) -> str | None:
    f = sorted((SITE / "arbre").glob(f"*_{numero}.json"))
    return f"arbre/{f[0].name}" if f else None


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def _xlsx(cle: str):
    import openpyxl
    p = chemin(cle)
    if not p.exists():
        raise SystemExit(f"{p} absent : lancer `python pipeline/emploi.py collecter`")
    return openpyxl.load_workbook(p, read_only=True, data_only=True)


def _csv(cle: str) -> list[list[str]]:
    p = chemin(cle)
    if not p.exists():
        raise SystemExit(f"{p} absent : lancer `python pipeline/emploi.py collecter`")
    with p.open(encoding="utf-8-sig") as fh:
        return [[c.lstrip("﻿") for c in r] for r in csv.reader(fh, delimiter=";") if r]


# --- Lecture des sources ----------------------------------------------------------------------------------------------

def lire_financement() -> dict[int, dict]:
    out = {}
    for r in _csv("unedic_financement"):
        if not r[0].strip().isdigit():
            continue
        if len(r) < 1 + len(COLONNES_FINANCEMENT):
            raise SystemExit(f"Unédic : ligne {r[0]} incomplète ({len(r)} colonnes)")
        out[int(r[0])] = {k: _meur(v) for (k, _), v in zip(COLONNES_FINANCEMENT, r[1:])}
    if not out:
        raise SystemExit("Unédic : aucune année lue dans « Dépenses et recettes »")
    return out


def controler_financement(f: dict[int, dict]) -> list[str]:
    """Les composantes somment aux totaux de la source (à 2 M€ près : arrondis de la source)."""
    fautes = []
    for an, u in sorted(f.items()):
        for total, parts in (("recettes_total", RECETTES), ("depenses_total", DEPENSES)):
            s = sum(u[p] or 0 for p in parts)
            if abs(s - u[total]) > 2 * MILLION:
                fautes.append(f"{an} {total}")
        if abs(u["recettes_total"] - u["depenses_total"] - u["solde_technique"]) > 2 * MILLION:
            fautes.append(f"{an} solde_technique")
    return fautes


def lire_indicateurs() -> dict[int, dict]:
    lignes = _csv("unedic_indicateurs")
    tete = lignes[0]
    i_ind = tete.index("Nombre d'allocataires indemnisés")
    i_dep = tete.index("Dépense mensuelle")
    par_an: dict[int, list] = defaultdict(list)
    for r in lignes[1:]:
        if len(r[0]) == 7 and r[0][:4].isdigit():
            par_an[int(r[0][:4])].append((r[0], _nombre(r[i_ind]), _nombre(r[i_dep])))
    out = {}
    for an, mois in sorted(par_an.items()):
        ind = [m[1] for m in mois if m[1] is not None]
        dep = [m[2] for m in mois if m[2] is not None]
        complet = len(mois) == 12 and len(ind) == 12 and len(dep) == 12
        out[an] = {"mois": len(mois),
                   "allocataires_indemnises_moyenne_mensuelle": int(round(sum(ind) / len(ind))) if complet else None,
                   "depense_allocations_somme_mensuelle_eur": int(round(sum(dep))) if complet else None}
    return out


def _lignes_feuille(wb, nom: str) -> list[tuple]:
    return [tuple(c for c in r) for r in wb[nom].iter_rows(values_only=True)]


def lire_ap_depenses(wb) -> dict[int, dict]:
    """Tableau 5 : dépenses de l'État et de l'Unédic au titre de l'activité partielle (M€)."""
    out = {}
    for r in _lignes_feuille(wb, "Tableau 5"):
        v = [c for c in r if c is not None]
        if len(v) < 4:
            continue
        an = str(v[0]).strip()
        provisoire = "(p)" in an
        an = an.replace("(p)", "").strip()
        if not an.isdigit():
            continue
        out[int(an)] = {"etat_eur": _meur(v[1]), "unedic_eur": _meur(v[2]), "total_eur": _meur(v[3]),
                        "provisoire": provisoire}
    return out


def lire_ap_mensuel(wb) -> list[dict]:
    """Tableau 6 : consommation d'activité partielle de droit commun et d'APLD par mois de recours."""
    out = []
    for r in _lignes_feuille(wb, "Tableau 6"):
        v = [c for c in r if c is not None]
        if len(v) < 7:
            continue
        m = v[0]
        provisoire = False
        if isinstance(m, dt.datetime):
            mois = m.strftime("%Y-%m")
        elif isinstance(m, str) and "déc-21" in m:
            mois, provisoire = "2021-12", True
        else:
            continue
        out.append({"mois": mois, "provisoire": provisoire, "etablissements": int(v[1]),
                    "salaries": int(round(v[2] * MILLION)), "heures": int(round(v[3] * MILLION)),
                    "montant_etat_unedic_eur": int(round(v[4] * 1000 * MILLION)),
                    "montant_unedic_eur": int(round(v[5] * 1000 * MILLION)),
                    "montant_horaire_brut_moyen_eur": round(float(v[6]), 2)})
    return out


def lire_ap_secteurs(wb) -> list[dict]:
    """Graphique 5 (parts des heures et des salariés du privé) et tableau 2 (heures moyennes par salarié)."""
    parts, moyennes = {}, {}
    for r in _lignes_feuille(wb, "Graphique 5"):
        v = [c for c in r if c is not None]
        if len(v) == 3 and isinstance(v[1], float) and " : " in str(v[0]):
            parts[_code_libelle(v[0])[0]] = (_code_libelle(v[0])[1], v[1], v[2])
    for r in _lignes_feuille(wb, "Tableau 2"):
        v = [c for c in r if c is not None]
        if len(v) == 4 and isinstance(v[1], float):
            code = "ensemble" if str(v[0]).strip() == "Ensemble" else _code_libelle(v[0])[0]
            moyennes[code] = (_code_libelle(v[0])[1] if code != "ensemble" else "Ensemble", v[1], v[2], v[3])
    codes = sorted(set(parts) | {c for c in moyennes if c != "ensemble"})
    out = []
    for c in codes:
        p = parts.get(c)
        m = moyennes.get(c)
        out.append({"code": c, "libelle": (p or m)[0],
                    "part_heures_pct": round(p[1] * 100, 2) if p else None,
                    "part_salaries_prive_fin_2019_pct": round(p[2] * 100, 2) if p else None,
                    "heures_par_salarie_mars2020_dec2021": round(m[1], 1) if m else None,
                    "heures_par_semaine_mars_mai_2020": round(m[2], 1) if m else None,
                    "heures_par_semaine_juin2020_dec2021": round(m[3], 1) if m else None})
    if "ensemble" in moyennes:
        m = moyennes["ensemble"]
        out.append({"code": "ensemble", "libelle": "Ensemble", "part_heures_pct": 100.0,
                    "part_salaries_prive_fin_2019_pct": 100.0,
                    "heures_par_salarie_mars2020_dec2021": round(m[1], 1),
                    "heures_par_semaine_mars_mai_2020": round(m[2], 1),
                    "heures_par_semaine_juin2020_dec2021": round(m[3], 1)})
    return out


def lire_urssaf() -> tuple[list[dict], list[int], dict[int, int]]:
    """Sommes annuelles par secteur NA38 ; (secteurs, années complètes, trimestres publiés par année)."""
    lignes = _csv("urssaf_chomage_partiel")
    tete = lignes[0]
    ix = {c: tete.index(c) for c in ("grand_secteur_d_activite", "secteur_na17", "secteur_na38", "annee",
                                     "trimestre", "masse_salariale_brute", "assiette_chomage_partiel")}
    cumul: dict[tuple, dict] = {}
    trimestres: dict[int, set] = defaultdict(set)
    for r in lignes[1:]:
        an, tri = int(r[ix["annee"]]), int(r[ix["trimestre"]])
        trimestres[an].add(tri)
        cle = r[ix["secteur_na38"]]
        e = cumul.setdefault(cle, {"grand": r[ix["grand_secteur_d_activite"]], "na17": r[ix["secteur_na17"]],
                                   "ans": defaultdict(lambda: {"ap": 0.0, "ms": 0.0, "n_ap": 0, "n_ms": 0})})
        a = e["ans"][an]
        for k, col in (("ap", "assiette_chomage_partiel"), ("ms", "masse_salariale_brute")):
            n = _nombre(r[ix[col]])
            if n is not None:
                a[k] += n
                a["n_" + k] += 1
    nb_tri = {an: len(t) for an, t in sorted(trimestres.items())}
    completes = [an for an, n in nb_tri.items() if n == 4]
    secteurs = []
    for cle in sorted(cumul):
        e = cumul[cle]
        code, lib = _code_libelle(cle)
        series = {}
        for an in sorted(nb_tri):
            a = e["ans"].get(an)
            ok = a is not None and a["n_ap"] == nb_tri[an]
            ms_ok = a is not None and a["n_ms"] == nb_tri[an]
            series[str(an)] = {
                "indemnites_eur": int(round(a["ap"])) if ok else None,
                "masse_salariale_eur": int(round(a["ms"])) if ms_ok else None,
                "part_indemnites_pct": round(a["ap"] / (a["ap"] + a["ms"]) * 100, 2) if ok and ms_ok and
                (a["ap"] + a["ms"]) else None}
        g_code, g_lib = _code_libelle(e["grand"])
        n_code, n_lib = _code_libelle(e["na17"])
        secteurs.append({"code": code, "libelle": lib, "na17": n_code, "na17_libelle": n_lib,
                         "grand_secteur": g_lib, "annees": series})
    return secteurs, completes, nb_tri


def lire_aej() -> dict:
    wb = _xlsx("dares_aej")

    def lignes(nom, n):
        out = []
        for r in wb[nom].iter_rows(values_only=True):
            v = list(r[:n])
            if v[0] is None or (n == 3 and v[1] is None):
                continue
            if v[-1] is None or str(v[0]).startswith(("Semaine", "Code", "Note", "Source", "Champ", "Tableau")):
                continue
            out.append(v)
        return out

    semaines = [{"semaine": str(s), "aides": int(n) if _nombre(n) is not None else None}
                for s, n in lignes("Semaine de validation", 2)]
    groupes, non_renseigne = [], None
    for c, l, n in lignes("Secteur d'activité", 3):
        if str(c).strip().lower() == "nc":  # secteur non renseigné à la source : compté à part
            non_renseigne = int(n) if _nombre(n) is not None else None
            continue
        groupes.append({"code": str(c), "libelle": str(l).strip(), "section": section_naf(c),
                        "aides": int(n) if _nombre(n) is not None else None})
    deps = [{"code": departement(c), "libelle": str(l).strip(), "aides": int(n) if _nombre(n) is not None else None}
            for c, l, n in lignes("Département de l'employeur", 3)]
    return {"semaines": semaines, "groupes": groupes, "secteur_non_renseigne": non_renseigne, "departements": deps}


# --- Crédits de l'État (déjà publiés par d'autres étapes) ------------------------------------------------------------

def credits_etat(programme: str, actions: list[str]) -> list[dict]:
    """Exécution 2024 par action (arbre/) et PLF 2025 par sous-action (programmes/) : deux millésimes côte à côte."""
    rel = fichier_programme(programme)
    arbre = _charger(rel) if rel else None
    plf = _charger(f"programmes/{programme}.json") or {}
    out = []
    for code in actions:
        noeud = next((e for e in (arbre or {}).get("enfants", []) if e["id"].endswith(f"/{programme}-{code}")), None)
        act = next((a for a in plf.get("actions", []) if a["code"] == code), None)
        out.append({
            "programme": programme, "action": code,
            "libelle": (act or {}).get("nom") or (noeud or {}).get("nom"),
            "execution_2024_eur": int(round(noeud["md"] * 1e9)) if noeud else None,
            "execution_2024_lien": {"fichier": rel, "id": noeud["id"]} if noeud else None,
            "plf_2025_cp_eur": int(round(act["md"] * 1e9)) if act else None,
            "plf_2025_sous_actions": [{"code": s["code"], "libelle": s["nom"], "cp_eur": int(round(s["md"] * 1e9))}
                                      for s in (act or {}).get("sous_actions", []) if s.get("code")],
        })
    return out


def france_travail_etat() -> tuple[dict, str | None]:
    doc = _charger("operateurs/operateurs.json")
    if not doc:
        return {}, None
    ft = next((o for o in doc.get("operateurs", []) if o.get("id") == "francetravail"), None)
    if not ft:
        return {}, doc.get("millesime")
    out = {}
    for an, v in sorted(ft["annees"].items()):
        fe = v.get("financement_etat") or {}
        cv = v.get("credits_votes_lfi") or {}
        out[an] = {
            "nature": v.get("nature"),
            "financement_etat_execution_cp_eur": _int(v.get("financement_etat_total_cp_eur")),
            "dont_subvention_pour_charges_de_service_public_cp_eur": _int((fe.get("scsp") or {}).get("cp_eur")),
            "dont_transferts_cp_eur": _int((fe.get("transferts") or {}).get("cp_eur")),
            "credits_votes_lfi_cp_eur": _int(v.get("credits_votes_lfi_total_cp_eur")),
            "credits_votes_lfi_scsp_cp_eur": _int((cv.get("scsp") or {}).get("cp_eur")),
            "budget_initial_charges_eur": _int((v.get("budget_initial") or {}).get("charges_eur")),
            "budget_initial_produits_eur": _int((v.get("budget_initial") or {}).get("produits_eur")),
            "etpt_sous_plafond": _arrondi(v.get("etpt_sous_plafond")),
            "etpt_hors_plafond": _arrondi(v.get("etpt_hors_plafond")),
            "source_jaune": (v.get("sources") or {}).get("financement_etat") or (v.get("sources") or {}).get(
                "credits_votes_lfi"),
        }
    return out, doc.get("millesime")


def _int(v):
    return None if v is None else int(round(v))


# --- Production -------------------------------------------------------------------------------------------------------

def produire() -> dict:
    date = date_sources("emploi")
    fin = lire_financement()
    fautes = controler_financement(fin)
    if fautes:
        raise SystemExit("Unédic : composantes et totaux incohérents : " + ", ".join(fautes))
    ind = lire_indicateurs()
    wb = _xlsx("unedic_activite_partielle")
    ap_dep = lire_ap_depenses(wb)
    ap_mois = lire_ap_mensuel(wb)
    ap_sect = lire_ap_secteurs(wb)
    secteurs, completes, nb_tri = lire_urssaf()
    aej = lire_aej()
    annees = sorted(fin)
    derniere = annees[-1]
    ecarts: list[dict] = []

    # --- unedic.json ---
    comptes = {str(an): fin[an] for an in annees}
    for an in annees:
        ecarts.append(_ecart("allocations_unedic", an, "unedic_financement", fin[an]["depenses_allocations"],
                             "unedic_indicateurs", (ind.get(an) or {}).get("depense_allocations_somme_mensuelle_eur"),
                             LECTURES["allocations"]))
    unedic = {
        "millesime": f"{annees[0]} à {annees[-1]} (comptes) ; {min(ind)} à {max(ind)} (indicateurs mensuels)",
        "source": f"{SOURCES['unedic_financement']['titre']} ; {SOURCES['unedic_indicateurs']['titre']} : "
                  f"{SOURCES['unedic_financement']['page']} ; {SOURCES['unedic_indicateurs']['page']}",
        "unite": "euros (montants publiés en millions d'euros par l'Unédic) ; personnes",
        "annees": annees,
        "definitions": {k: d for k, d in COLONNES_FINANCEMENT},
        "comptes": comptes,
        "structure": {
            "recettes": RECETTES, "depenses": DEPENSES,
            "regle": "les composantes somment aux totaux de la source (contrôlé à 2 millions d'euros près, arrondis "
                     "de la source) ; solde technique = recettes totales moins dépenses totales"},
        "indicateurs_annuels": {str(an): v for an, v in sorted(ind.items())},
        "indicateurs_methode": "moyenne des 12 valeurs mensuelles du nombre d'allocataires indemnisés et somme des 12 "
                               "dépenses mensuelles, calculées ici ; une année incomplète est null",
        "note": "la CSG remplace depuis 2019 l'ancienne contribution salariale : la baisse des contributions en 2019 "
                "correspond à ce transfert ; la dette est publiée avec le signe de la source (négatif = dette nette)",
        "liens": [],
    }
    for rel, mill in (("secu/arbre/racine.json", None), ("secu/arbre_2025/racine.json", None)):
        doc = _charger(rel)
        if doc:
            unedic["liens"].append({"vue": "secu_arbre", "fichier": rel, "id": "unedic", "millesime":
                                    doc.get("millesime"), "lecture": "même source (comptes de l'Unédic), vue dans "
                                    "l'arbre de la Sécurité sociale : non additionné"})
    if _charger("prestations/index.json"):
        unedic["liens"].append({"vue": "prestations", "fichier": "prestations/index.json", "id": "are",
                                "lecture": "allocation chômage parmi les prestations versées aux ménages"})

    # --- france_travail.json ---
    etat_ft, mill_op = france_travail_etat()
    ans_ft = sorted({str(a) for a in annees} | set(etat_ft))
    ft_annees = {}
    for an in ans_ft:
        u = fin.get(int(an))
        e = etat_ft.get(an) or {}
        ft_annees[an] = {
            "unedic_financement_et_frais_de_recouvrement_eur": u["depenses_france_travail"] if u else None,
            **{k: e.get(k) for k in ("nature", "financement_etat_execution_cp_eur",
                                     "dont_subvention_pour_charges_de_service_public_cp_eur", "dont_transferts_cp_eur",
                                     "credits_votes_lfi_cp_eur", "credits_votes_lfi_scsp_cp_eur",
                                     "budget_initial_charges_eur", "budget_initial_produits_eur",
                                     "etpt_sous_plafond", "etpt_hors_plafond", "source_jaune")},
        }
    france_travail = {
        "millesime": f"{ans_ft[0]} à {ans_ft[-1]} (Unédic) ; {mill_op or 'jaunes budgétaires non disponibles'} (État)",
        "source": f"{SOURCES['unedic_financement']['titre']} ({SOURCES['unedic_financement']['page']}) ; "
                  f"{DEJA_PUBLIES['operateurs']['titre']} ; {DEJA_PUBLIES['arbre_etat']['titre']} ; "
                  f"{DEJA_PUBLIES['programmes']['titre']}",
        "unite": "euros ; emplois en équivalent temps plein travaillé (ETPT)",
        "annees": {an: ft_annees[an] for an in ans_ft},
        "definitions": {
            "unedic_financement_et_frais_de_recouvrement_eur": "dépense de l'Unédic pour financer Pôle emploi, devenu "
            "France Travail (11 % des recettes de l'avant-dernière année depuis 2019), et frais de recouvrement des "
            "contributions (colonne unique dans la source)",
            "financement_etat_execution_cp_eur": "crédits de l'État versés à l'opérateur dans l'année (jaune "
            "« Opérateurs de l'État »), toutes natures : subvention pour charges de service public, transferts "
            "(aides et allocations qu'il verse pour le compte de l'État), dotations",
            "credits_votes_lfi_cp_eur": "crédits prévus par la loi de finances initiale pour l'opérateur",
            "budget_initial_charges_eur": "charges du budget initial de l'opérateur voté par son conseil (jaune)",
        },
        "regle": "le financement par l'Unédic et le financement par l'État viennent de deux sources différentes, "
                 "aux périmètres différents : ils sont publiés côte à côte, jamais additionnés ; le budget de "
                 "l'opérateur n'est pas reconstitué",
        "credits_etat_programme_102": credits_etat("102", ["01", "02"]),
        "liens": [{"vue": "operateurs", "fichier": "operateurs/operateurs.json", "id": "francetravail",
                   "lecture": "fiche de l'opérateur (financement de l'État, emplois, rémunérations)"},
                  {"vue": "secu_arbre", "fichier": "secu/arbre/racine.json", "id": "unedic/france_travail",
                   "lecture": "même colonne des comptes de l'Unédic, vue dans l'arbre de la Sécurité sociale"}],
    }

    # --- activite_partielle.json ---
    ans_ap = sorted(set(ap_dep) | {a for a in annees})
    dep = {}
    for an in ans_ap:
        s = ap_dep.get(an) or {}
        dep[str(an)] = {"etude_2022_etat_eur": s.get("etat_eur"), "etude_2022_unedic_eur": s.get("unedic_eur"),
                        "etude_2022_total_eur": s.get("total_eur"), "etude_2022_provisoire": s.get("provisoire"),
                        "comptes_unedic_eur": (fin.get(an) or {}).get("depenses_activite_partielle")}
        ecarts.append(_ecart("activite_partielle_unedic", an, "unedic_activite_partielle", s.get("unedic_eur"),
                             "unedic_financement", (fin.get(an) or {}).get("depenses_activite_partielle"),
                             LECTURES["ap_unedic"]))
    par_an_mois: dict[str, dict] = {}
    for m in ap_mois:
        a = par_an_mois.setdefault(m["mois"][:4], {"mois": 0, "heures": 0, "montant_etat_unedic_eur": 0,
                                                   "montant_unedic_eur": 0, "contient_provisoire": False})
        a["mois"] += 1
        for k in ("heures", "montant_etat_unedic_eur", "montant_unedic_eur"):
            a[k] += m[k]
        a["contient_provisoire"] = a["contient_provisoire"] or m["provisoire"]
    totaux_secteurs = {}
    for an in sorted(nb_tri):
        vals = [s["annees"][str(an)]["indemnites_eur"] for s in secteurs]
        totaux_secteurs[str(an)] = {"trimestres": nb_tri[an], "annee_complete": an in completes,
                                    "indemnites_eur": sum(vals) if all(v is not None for v in vals) else None}
    comparaison = {"lecture": LECTURES["ap_indemnite_allocation"], "annees": {
        str(an): {"indemnites_urssaf_eur": totaux_secteurs[str(an)]["indemnites_eur"],
                  "allocations_etat_unedic_etude_2022_eur": ap_dep[an]["total_eur"],
                  "etude_2022_provisoire": ap_dep[an]["provisoire"]}
        for an in completes if an in ap_dep}}
    activite_partielle = {
        "millesime": f"{min(ans_ap)} à {max(ans_ap)} (dépenses) ; mars 2020 à décembre 2021 (heures) ; "
                     f"{min(nb_tri)} à {max(nb_tri)} (indemnités par secteur, Urssaf)",
        "source": f"{SOURCES['unedic_activite_partielle']['titre']} ({SOURCES['unedic_activite_partielle']['page']}) ; "
                  f"{SOURCES['unedic_financement']['titre']} ; {SOURCES['urssaf_chomage_partiel']['titre']} "
                  f"({SOURCES['urssaf_chomage_partiel']['page']}) ; {DEJA_PUBLIES['arbre_etat']['titre']} ; "
                  f"{DEJA_PUBLIES['programmes']['titre']}",
        "unite": "euros ; heures ; personnes ; établissements",
        "definitions": {
            "activite_partielle": "dispositif par lequel un employeur réduit ou suspend l'activité de salariés : "
                                  "l'employeur verse au salarié une indemnité et reçoit de l'Agence de services et de "
                                  "paiement une allocation financée par l'État et l'Unédic",
            "etude_2022": "tableau 5 de l'étude de l'Unédic de février 2022 (versements de l'année, ou montants "
                          "consommés au titre de l'année pour 2015, 2020 et 2021)",
            "comptes_unedic_eur": "colonne « activité partielle » des comptes annuels de l'Unédic",
            "indemnites_eur": "assiette chômage partiel déclarée à l'Urssaf : indemnités d'activité partielle "
                              "versées par les employeurs du secteur privé (régime général) à leurs salariés",
            "montant_etat_unedic_eur": "allocation remboursée aux employeurs par l'État et l'Unédic, d'après les "
                                       "demandes d'indemnisation (Agence de services et de paiement)",
            "APLD": "activité partielle de longue durée, ouverte par accord d'entreprise ou de branche depuis "
                    "juillet 2020",
        },
        "depenses_annuelles": dep,
        "consommation_mensuelle": {
            "champ": "activité partielle de droit commun et activité partielle de longue durée, hors particuliers "
                     "employeurs, demandes d'indemnisation retraitées des doublons (données du 17 janvier 2022)",
            "mois": ap_mois,
            "annees": par_an_mois,
            "methode": "sommes annuelles des heures et des montants calculées ici ; les salariés et établissements "
                       "ne se somment pas d'un mois à l'autre (une même personne compte chaque mois)",
        },
        "heures_par_secteur_2020_2021": {
            "champ": "heures indemnisées de mars 2020 à décembre 2021, établissements hors agriculture, activités "
                     "extra-territoriales et particuliers employeurs ; salariés du privé fin 2019 (Acoss) ; "
                     "nomenclature agrégée en 17 postes",
            "secteurs": ap_sect,
            "note": "parts publiées par l'Unédic ; les heures par secteur ne sont pas recalculées en volume, le champ "
                    "des parts différant de celui du total mensuel",
        },
        "indemnites_par_secteur": {
            "champ": "secteur privé, régime général, France entière ; secteurs de la nomenclature agrégée NA38 "
                     "publiés par l'Urssaf",
            "annees_completes": completes,
            "totaux": totaux_secteurs,
            "secteurs": secteurs,
            "methode": "somme des quatre trimestres de chaque année, calculée ici ; année incomplète signalée par "
                       "`annee_complete` ; part = indemnités / (indemnités + masse salariale), comme l'Urssaf",
        },
        "indemnites_et_allocations": comparaison,
        "credits_etat_programme_103": credits_etat("103", ["03"]),
        "regle": "l'allocation (État et Unédic) et l'indemnité (versée par l'employeur) sont deux grandeurs "
                 "différentes : publiées côte à côte, jamais additionnées ; aucun montant n'est estimé à partir des "
                 "heures",
        "liens": [{"vue": "secu_arbre", "fichier": "secu/arbre/racine.json", "id": "unedic/activite_partielle",
                   "lecture": "même colonne des comptes de l'Unédic (exécution 2024)"}],
    }

    # --- aides_embauche.json ---
    groupes = aej["groupes"]
    sections = []
    for s, _, _, lib in SECTIONS_NAF:
        g = [x for x in groupes if x["section"] == s]
        if not g:
            continue
        connus = [x["aides"] for x in g if x["aides"] is not None]
        sections.append({"code": s, "libelle": lib, "aides_connues": sum(connus),
                         "groupes_secret_statistique": sum(1 for x in g if x["aides"] is None)})
    total_sem = sum(x["aides"] for x in aej["semaines"] if x["aides"] is not None)
    total_dep = sum(x["aides"] for x in aej["departements"] if x["aides"] is not None)
    aides_embauche = {
        "millesime": "aide à l'embauche des jeunes : aides validées jusqu'au 5 mars 2022 ; crédits de l'État : "
                     "exécution 2024 et PLF 2025",
        "source": f"{SOURCES['dares_aej']['titre']} ({SOURCES['dares_aej']['page']}) ; "
                  f"{DEJA_PUBLIES['arbre_etat']['titre']} ; {DEJA_PUBLIES['programmes']['titre']}",
        "unite": "nombre d'aides validées ; euros",
        "aide_embauche_jeunes": {
            "definition": "aide de l'État (plan « 1 jeune, 1 solution ») à l'employeur, hors fonction publique et "
                          "particuliers employeurs, qui a embauché en contrat à durée indéterminée ou déterminée de "
                          "plus de 3 mois un jeune de moins de 26 ans entre le 1er août 2020 et le 31 mars 2021, "
                          "pour une rémunération jusqu'à deux fois le salaire minimum ; 4 000 euros au plus sur un "
                          "an, proratisés selon la durée du travail et de l'emploi",
            "total_aides_validees": total_sem,
            "total_par_departement": total_dep,
            "semaines": aej["semaines"],
            "sections": sections,
            "groupes": groupes,
            "aides_secteur_non_renseigne": aej["secteur_non_renseigne"],
            "departements": aej["departements"],
            "note": "« nd » de la source (moins de 5 aides, secret statistique) publié null ; les totaux par section "
                    "comptent les seules valeurs publiées ; secteur « nc » de la source compté à part "
                    "(aides_secteur_non_renseigne) ; aucun montant versé n'est publié par la source ni "
                    "estimé ici",
        },
        "credits_etat_programme_103": credits_etat("103", ["05"]),
        "note": "l'apprentissage et les aides aux employeurs d'apprentis (programme 103, action 01) sont publiés "
                "par la vue formation, sans être recopiés ici",
        "liens": [{"vue": "formation", "fichier": "formation/index.json", "id": "index",
                   "lecture": "formation professionnelle et apprentissage"}],
    }

    ecarts = [e for e in ecarts if e]
    d = fin[derniere]
    index = {
        "millesime": f"{annees[0]} à {annees[-1]} (Unédic) ; exécution 2024 et PLF 2025 (État)",
        "source": "Unédic (comptes, indicateurs, étude sur l'activité partielle de 2022) ; Urssaf (indemnités "
                  "d'activité partielle par secteur) ; Dares (aide à l'embauche des jeunes) ; jaunes budgétaires et "
                  "budget de l'État déjà publiés (operateurs/, arbre/, programmes/)",
        "unite": "euros ; personnes ; heures",
        "date_sources": date,
        "annees": annees,
        "derniere_annee": derniere,
        "fichiers": {"unedic": "emploi/unedic.json", "france_travail": "emploi/france_travail.json",
                     "activite_partielle": "emploi/activite_partielle.json",
                     "aides_embauche": "emploi/aides_embauche.json"},
        "chiffres_cles": {
            "annee": derniere,
            "unedic_recettes_eur": d["recettes_total"], "unedic_depenses_eur": d["depenses_total"],
            "unedic_allocations_eur": d["depenses_allocations"], "unedic_dette_eur": d["dette"],
            "unedic_vers_france_travail_eur": d["depenses_france_travail"],
            "unedic_activite_partielle_eur": d["depenses_activite_partielle"],
            "allocataires_indemnises_moyenne_mensuelle": (ind.get(derniere) or {}).get(
                "allocataires_indemnises_moyenne_mensuelle"),
            "note": "comptes de l'Unédic de l'année ; montants en euros, dette avec le signe de la source",
        },
        "ecarts": ecarts,
        "regle": "agrégats publiés seulement ; montants de sources différentes publiés côte à côte avec leurs écarts, "
                 "jamais additionnés ; aucun montant estimé à partir d'un nombre d'aides ou d'heures ; une valeur "
                 "absente ou en secret statistique est null, jamais 0",
        "limites": [
            "activité partielle : heures indemnisées publiées pour la période de mars 2020 à décembre 2021 (étude de "
            "l'Unédic) ; les séries de la Dares ne sont pas accessibles aux scripts",
            "étude de 2022 : montants 2021 provisoires, non mis à jour par la source",
            "France Travail : pas de compte complet de l'opérateur en données ouvertes ; financement par l'État "
            "(jaunes) et par l'Unédic (comptes) publiés séparément",
            "aides à l'embauche : nombre d'aides validées pour l'aide à l'embauche des jeunes seulement ; crédits de "
            "l'État par action et sous-action pour les autres dispositifs",
            "indemnités par secteur (Urssaf) : secteur privé du régime général, hors particuliers employeurs et "
            "hors régime agricole",
        ],
        # `entrepot` : nom dans data/lake/emploi/ (pas `fichier`, réservé par le contrat aux liens vers site/data)
        "sources": {k: {("entrepot" if c == "fichier" else c): x for c, x in v.items()}
                    for k, v in sorted(SOURCES.items())},
        "deja_publies": DEJA_PUBLIES,
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(SORTIE / "unedic.json", unedic)
    dump(SORTIE / "france_travail.json", france_travail)
    dump(SORTIE / "activite_partielle.json", activite_partielle)
    dump(SORTIE / "aides_embauche.json", aides_embauche)
    dump(SORTIE / "index.json", index)
    print(f"emploi : Unédic {annees[0]}-{annees[-1]} (dette {derniere} {d['dette'] / 1e9:.1f} Md€), "
          f"{len(ap_mois)} mois d'activité partielle, {len(secteurs)} secteurs Urssaf, {total_sem} aides à "
          f"l'embauche des jeunes, {len(ecarts)} écarts")
    return index


# --- Collecte ---------------------------------------------------------------------------------------------------------

def _manifeste(sid: str, entree: dict) -> None:
    """Entrée du manifeste de l'entrepôt, sous le même verrou que collecte/collecte.py, écriture atomique."""
    MANIFESTE.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFESTE.with_name(MANIFESTE.name + ".lock"), "w") as v:
        fcntl.flock(v, fcntl.LOCK_EX)
        try:
            m = json.loads(MANIFESTE.read_text(encoding="utf-8")) if MANIFESTE.exists() else {}
            m[sid] = entree
            tmp = MANIFESTE.with_name(MANIFESTE.name + ".tmp")
            tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, MANIFESTE)
        finally:
            fcntl.flock(v, fcntl.LOCK_UN)


def telecharger(url: str, dest: Path, essais: int = 5) -> tuple[str, bytes | None]:
    import requests
    derniere = ""
    for i in range(essais):
        try:
            r = requests.get(url, timeout=(20, 300), headers=UA)
            if r.status_code in (401, 403, 429, 451):
                return f"accès refusé (HTTP {r.status_code}) : aucun contournement", None
            r.raise_for_status()
            debut = r.content[:200].lower()
            if (dest.suffix == ".xlsx" and r.content[:4] != b"PK\x03\x04") or \
                    (dest.suffix == ".csv" and (b"<html" in debut or b"<!doctype" in debut)):
                return "contenu inattendu (page HTML au lieu du fichier) : aucun contournement", None
            return "ok", r.content
        except Exception as e:  # coupure réseau : reprise espacée
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(5 * (i + 1))
    return f"échec après {essais} essais : {derniere}", None


def collecter(forcer: bool = False) -> dict:
    BRUT.mkdir(parents=True, exist_ok=True)
    etat = {}
    for cle, s in SOURCES.items():
        dest = chemin(cle)
        if dest.exists() and dest.stat().st_size > 0 and not forcer:
            etat[cle] = "présent"
        else:
            etat[cle], contenu = telecharger(s["url"], dest)
            if contenu is not None:
                tmp = dest.with_suffix(dest.suffix + ".part")
                tmp.write_bytes(contenu)
                import fetch  # contrôle d'intégrité (collecte/integrite.py) avant le renommage atomique
                fetch.remplacer_si_valide(tmp, dest, nom=dest.name)
                _manifeste(f"emploi__{cle}", {
                    "collecte_le": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    "domaine": "emploi", "licence": s["licence"], "origine": "pipeline/emploi.py",
                    "producteur": s["producteur"], "personnes_physiques": False, "statut": "ok",
                    "fichiers": [{"chemin": str(dest.relative_to(ROOT)), "octets": len(contenu),
                                  "sha256": hashlib.sha256(contenu).hexdigest(), "url": s["url"]}]})
        print(f"{cle}: {etat[cle]}")
    return etat


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
