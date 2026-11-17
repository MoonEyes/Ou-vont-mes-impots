"""Subventions publiées au format des « données essentielles des conventions de subvention » (décret 2017-779,
schéma SCDL `scdl/subventions`), source par source : qui attribue, combien, quelle année, dans quel département, à qui.

Un lecteur par source ramène chaque ligne à un enregistrement commun (année, montant, SIREN, département, programme
LOLF, dispositif) ; le reste du module est générique (agrégats, bénéficiaires nommés, contrôles).

Entrées : entrepôt brut data/lake/_restreint/subventions/ (zone restreinte : les fichiers sources contiennent des
entrepreneurs individuels) et data/lake/subventions/ (presse), collectés par collecte/collecte.py (entrées `subv_*` de
collecte/catalogue.json) ; stock SIRENE des unités légales (data/lake/_cache/local/, partagé avec pipeline/local.py).
Sorties (site/data/subventions/, chaque fichier < 5 Mo, avec `millesime` et `source`) :
  index.json                   sources, totaux, part nommée et part agrégée, recouvrements, recherche préalable
  attribuants/<source>.json    une source : par année, par département, par dispositif, par programme, bénéficiaires
  annees.json                  par année et par source
  departements.json            par département et par source (et par année)
  beneficiaires.json           bénéficiaires nommés, toutes sources additionnées (personnes morales)
  programmes.json              rattachement au programme LOLF (programme publié dans la source, ou chef de file de
                               l'opérateur attribuant), par année ; prévu pour pipeline/tracabilite.py (contrat 2.25)

Commandes :
  python pipeline/subventions.py collecter   # réseau : collecte/collecte.py sur les entrées subv_* (reprenable)
  python pipeline/subventions.py produire    # sans réseau (stock SIRENE téléchargé une fois s'il manque)
  python pipeline/subventions.py             # les deux

Règles :
  - seuls les bénéficiaires dont la catégorie juridique SIRENE est une personne morale (sirene.personne_morale) sont
    nommés ; entrepreneurs individuels, groupements de personnes physiques, identifiants absents, invalides ou absents
    du stock SIRENE sont agrégés (`exclus_personnes_physiques_ou_non_identifies`), avec leur montant ;
  - aucune adresse, aucun genre, aucune direction artistique, aucun nom de dirigeant, aucun objet de convention n'est
    publié : ces colonnes ne sont pas lues ; les noms d'usage (festival, équipe artistique, titre de presse) passent le
    filtre de noms de personnes de pipeline/local.py et sont retirés au moindre doute ;
  - un montant absent ou « nc » à la source n'est jamais compté 0 : la ligne est comptée dans
    `lignes_montant_non_communique` et exclue des sommes ;
  - deux sources qui se recouvrent ne sont jamais additionnées (`additionne`, `recouvrements`) ;
  - toute date écrite vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "subventions"
GEO = SITE / "local" / "geo"
TOP = 50
MAX_OCTETS = 5_000_000
csv.field_size_limit(10_000_000)

DATAGOUV = "https://www.data.gouv.fr/datasets/"
NOTE_ADDITION = ("Les totaux toutes sources n'additionnent que les sources marquées `additionne` ; une source qui en "
                 "détaille une autre (même argent publié deux fois) est publiée à part, sans être ajoutée.")

# --- Sources -------------------------------------------------------------------------------------------------------
# `rattachement` : comment relier la source au budget de l'État. `programme_source` : le programme LOLF est publié
# ligne par ligne ; `programme_dispositif` : le dispositif relève d'un seul programme (titre ou texte de la source) ;
# `operateur` : l'attribuant est un opérateur de l'État, relié au programme chef de file de site/data/operateurs ;
# `hors_budget_etat` : pas de programme LOLF unique.

SOURCES = {
    "subv_ademe_aides": {
        "titre": "ADEME, « Les aides financières de l'ADEME » (conventions de subvention au format SCDL)",
        "attribuant": "ADEME (Agence de l'environnement et de la maîtrise de l'énergie)",
        "producteur": "ADEME", "page": "https://data.ademe.fr/datasets/les-aides-financieres-de-l'ademe",
        "licence": "Licence Ouverte 2.0", "millesime": "Conventions signées de 2021 à 2026",
        "rattachement": {"type": "operateur", "operateur": "ADEME", "siren": "385290309",
                         "programme_chef_de_file": "181", "fichier": "operateurs/operateurs.json", "id": "ademe"},
        "additionne": True, "lecteur": "scdl_ademe",
    },
    "subv_fonds_vert": {
        "titre": "Ministère de la Transition écologique, « Fonds vert : liste des projets subventionnés »",
        "attribuant": "État, Fonds d'accélération de la transition écologique dans les territoires (Fonds vert)",
        "producteur": "Ministère de la Transition écologique", "page": DATAGOUV + "66a215a463a9da4fb801b8cf",
        "licence": "Licence Ouverte 2.0", "millesime": "Montants engagés en 2023, 2024 et 2025",
        "rattachement": {"type": "programme_dispositif", "programmes": ["380", "113"],
                         "note": "Fichiers « fonds-vert-<année> » : programme 380 ; fichiers « fonds-vert-p113-<année> » : "
                                 "programme 113 (titre des fichiers publiés)."},
        "additionne": True, "lecteur": "fonds_vert",
    },
    "subv_aeap": {
        "titre": "Agence de l'eau Artois-Picardie, « Conventions de subvention signées » (format SCDL)",
        "attribuant": "Agence de l'eau Artois-Picardie",
        "producteur": "Agence de l'eau Artois-Picardie", "page": DATAGOUV + "5b9249d2634f411b8339f194",
        "licence": "Licence Ouverte 2.0", "millesime": "Conventions signées de 2017 à 2026 (10e, 11e et 12e programmes "
                                                       "d'intervention)",
        "rattachement": {"type": "operateur", "operateur": "Agences de l'eau", "programme_chef_de_file": "113",
                         "fichier": "operateurs/operateurs.json", "id": "agencesdeleau"},
        "additionne": True, "lecteur": "scdl_aeap",
    },
    "subv_culture_scdl": {
        "titre": "Ministère de la Culture, « Données essentielles des conventions de subvention »",
        "attribuant": "Ministère de la Culture (administration centrale et DRAC)",
        "producteur": "Ministère de la Culture", "page": DATAGOUV + "donnees-essentielles-des-conventions-de-subvention-5",
        "licence": "Licence Ouverte 2.0", "millesime": "Montants engagés de 2019 à 2025",
        "rattachement": {"type": "programme_source", "colonne": "programme_code"},
        "additionne": True, "lecteur": "culture_scdl",
    },
    "subv_culture_festivals_p131": {
        "titre": "Ministère de la Culture, « Festivals financés au titre du programme 131 : Création »",
        "attribuant": "Ministère de la Culture (programme 131)",
        "producteur": "Ministère de la Culture", "page": DATAGOUV + "695b8b6f6bf16db672fa28df",
        "licence": "Licence Ouverte 2.0", "millesime": "Aides 2023 et 2024",
        "rattachement": {"type": "programme_dispositif", "programmes": ["131"]},
        "additionne": False, "inclus_dans": "subv_culture_scdl", "lecteur": "festivals",
    },
    "subv_culture_adsv": {
        "titre": "Ministère de la Culture, « Les aides déconcentrées au spectacle vivant (ADSV) »",
        "attribuant": "Ministère de la Culture (DRAC et DGCA, programme 131)",
        "producteur": "Ministère de la Culture", "page": DATAGOUV + "656565de619420d81ca3e3dc",
        "licence": "Licence Ouverte 2.0", "millesime": "Aides 2022 à 2024",
        "rattachement": {"type": "programme_dispositif", "programmes": ["131"]},
        "additionne": False, "inclus_dans": "subv_culture_scdl", "lecteur": "adsv",
    },
    "subv_politique_ville_p147": {
        "titre": "ANCT, « Subventions politique de la ville » (programme 147, format SCDL)",
        "attribuant": "État, politique de la ville (ANCT, services déconcentrés)",
        "producteur": "Agence nationale de la cohésion des territoires", "page": DATAGOUV + "5a69f47e88ee385c0c053a21",
        "licence": "Licence Ouverte 2.0", "millesime": "Dossiers engagés de 2016 à 2025",
        "rattachement": {"type": "programme_dispositif", "programmes": ["147"]},
        "additionne": True, "lecteur": "p147",
    },
    "subv_ars_pdl_fir": {
        "titre": "ARS Pays de la Loire, « Subventions au titre du Fonds d'intervention régional (FIR) 2025 »",
        "attribuant": "Agence régionale de santé des Pays de la Loire (FIR)",
        "producteur": "ARS Pays de la Loire",
        "page": DATAGOUV + "subventions-de-lars-des-pays-de-la-loire-au-titre-du-fonds-dintervention-regional-fir-2025",
        "licence": "Licence Ouverte 2.0", "millesime": "Conventions 2025",
        "rattachement": {"type": "hors_budget_etat",
                         "note": "Le FIR est un fonds des agences régionales de santé, financé principalement par "
                                 "l'assurance maladie : la source ne donne pas de programme LOLF."},
        "additionne": True, "region": {"code": "52", "nom": "Pays de la Loire"}, "lecteur": "scdl_fir",
    },
    "subv_presse_titres": {
        "titre": "Ministère de la Culture, « Aides à la presse : classement des titres de presse aidés »",
        "attribuant": "Ministère de la Culture (aides à la presse, programme 180)",
        "producteur": "Ministère de la Culture",
        "page": DATAGOUV + "aides-a-la-presse-classement-des-titres-de-presse-aides",
        "licence": "Licence Ouverte 2.0", "millesime": "Aides 2015 à 2023",
        "rattachement": {"type": "programme_dispositif", "programmes": ["180"]},
        "additionne": False, "inclus_dans": "subv_culture_scdl", "lecteur": "presse_titres", "titres": True,
    },
    "subv_presse_dispositifs": {
        "titre": "Ministère de la Culture, aides à la presse par dispositif (jeux listés par « Aides à la presse »)",
        "attribuant": "Ministère de la Culture (aides à la presse, programme 180)",
        "producteur": "Ministère de la Culture", "page": DATAGOUV + "aides-a-la-presse-1",
        "licence": "Licence Ouverte 2.0", "millesime": "Aides 2012 à 2025",
        "rattachement": {"type": "programme_dispositif", "programmes": ["180"]},
        "additionne": False, "inclus_dans": "subv_presse_titres", "lecteur": "presse_dispositifs", "titres": True,
    },
}

DISPOSITIFS_PRESSE = {
    "9af88bf7": "Aide au pluralisme de la presse périodique régionale et locale",
    "58300293": "Aide au pluralisme des services de presse tout en ligne",
    "64ad7473": "Aide au pluralisme des titres ultramarins",
    "7ba8071d": "Aide aux quotidiens régionaux, départementaux et locaux à faibles ressources de petites annonces",
    "dba1f9a9": "Aide à l'exemplaire des titres de presse postés",
    "58065ce0": "Aide à la distribution de la presse quotidienne nationale",
    "81de0b56": "Aide à l'exemplaire des titres de presse portés (aide au portage)",
    "3be0c144": "Aides aux publications nationales à faibles ressources publicitaires",
    "b4c8722e": "Fonds de soutien à l'émergence et à l'innovation dans la presse (FSEIP)",
    "801735a1": "Fonds stratégique pour le développement de la presse (FSDP)",
}

RECOUVREMENTS = [
    {"source": "subv_culture_festivals_p131", "autre_source": "subv_culture_scdl",
     "lecture": "Les festivals du programme 131 sont des conventions du ministère de la Culture : ils figurent aussi dans "
                "les données essentielles du ministère (programme 131). Publiés à part, jamais additionnés."},
    {"source": "subv_culture_adsv", "autre_source": "subv_culture_scdl",
     "lecture": "Les aides déconcentrées au spectacle vivant sont versées sur le programme 131 par les DRAC et la DGCA : "
                "elles figurent aussi dans les données essentielles du ministère. Publiées à part, jamais additionnées."},
    {"source": "subv_presse_titres", "autre_source": "subv_culture_scdl",
     "lecture": "Les aides à la presse relèvent du programme 180, présent dans les données essentielles du ministère "
                "de 2019 à 2025 (mêmes éditeurs). Publiées à part par titre, jamais additionnées."},
    {"source": "subv_presse_dispositifs", "autre_source": "subv_presse_titres",
     "lecture": "Chaque dispositif est une composante du total par titre du classement (2015 à 2023). Publiés à part, "
                "jamais additionnés."},
    {"source": "subv_fonds_vert", "autre_source": "subv_ademe_aides",
     "lecture": "Une partie des projets du Fonds vert est instruite par l'ADEME (colonne « opérateur ») et peut figurer "
                "dans les conventions de l'ADEME. Ces lignes sont retirées des totaux toutes sources "
                "(`montant_retire_des_totaux_eur`) et restent dans le fichier de la source."},
    {"source": "subv_fonds_vert", "autre_source": "subv_aeap",
     "lecture": "Des projets du Fonds vert sont instruits par les agences de l'eau ; la source ne nomme pas toujours "
                "l'agence (« Agence de l'eau »). Recouvrement possible avec l'agence Artois-Picardie, non chiffrable "
                "avec les données publiées."},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "trouvailles": [
        {"nom": "Schéma SCDL « subventions » (données essentielles des conventions de subvention), version 2.1.2",
         "url": "https://schema.data.gouv.fr/scdl/subventions/", "depot": "https://gitlab.com/opendatafrance/scdl/subventions",
         "licence": "Licence Ouverte 2.0 (copie GitHub OpenDataFrance/subventions : Unlicense)",
         "derniere_mise_a_jour": "2026-11-02", "verdict": "à adapter",
         "usage": "noms de champs repris comme pivot (nomAttribuant, dateConvention, idBeneficiaire, montant, "
                  "dispositifAide) ; chaque source garde son lecteur car seules l'ADEME, l'agence Artois-Picardie et "
                  "l'ARS Pays de la Loire suivent le schéma"},
        {"nom": "Validata (validation de fichiers contre un schéma Table Schema)",
         "url": "https://gitlab.com/validata-table/validata-table", "licence": "AGPL-3.0",
         "derniere_mise_a_jour": "2026-11-03", "verdict": "inspiration seulement",
         "usage": "les sources s'écartent du schéma (colonnes, séparateurs, encodages) : on contrôle les colonnes "
                  "lues par chaque lecteur plutôt que la conformité complète"},
        {"nom": "Data.Subvention (betagouv/api-subventions-asso)", "url": "https://github.com/betagouv/api-subventions-asso",
         "licence": "MIT", "derniere_mise_a_jour": "2026-10 (environ un mois avant la recherche)",
         "verdict": "inspiration seulement",
         "usage": "agrégateur des subventions aux associations réservé aux agents publics : pas de données ouvertes "
                  "réutilisables ici"},
        {"nom": "betagouv/SCDL-subventions-DataSubvention", "url": "https://github.com/betagouv/SCDL-subventions-DataSubvention",
         "licence": "Unlicense", "derniere_mise_a_jour": "plus d'un an avant la recherche", "verdict": "inspiration seulement",
         "usage": "copie du schéma SCDL"},
        {"nom": "brunocpu/fonds-vert-paca-carto", "url": "https://github.com/brunocpu/fonds-vert-paca-carto",
         "licence": "non précisée", "derniere_mise_a_jour": "2026-09-27", "verdict": "inspiration seulement",
         "usage": "cartographie du Fonds vert pour une région ; pas de traitement national ni de filtre SIRENE"},
        {"nom": "pipeline/local.py (sirene_cj, contient_nom_de_personne)", "url": "pipeline/local.py",
         "licence": "MIT (ce dépôt)", "derniere_mise_a_jour": "2026-11-17", "verdict": "réutilisable tel quel",
         "usage": "stock SIRENE des unités légales (catégorie juridique, dénomination) et filtre de noms de personnes"},
        {"nom": "pipeline/sirene.py (personne_morale)", "url": "pipeline/sirene.py", "licence": "MIT (ce dépôt)",
         "derniere_mise_a_jour": "2026-11-17", "verdict": "réutilisable tel quel",
         "usage": "règle des personnes morales commune au site"},
        {"nom": "collecte/collecte.py (types url et datagouv_ressources)", "url": "collecte/collecte.py",
         "licence": "MIT (ce dépôt)", "derniere_mise_a_jour": "2026-11-17", "verdict": "réutilisable tel quel",
         "usage": "collecte reprenable, manifeste et zone restreinte"},
    ],
}

LIMITES = [
    "Montants engagés ou attribués selon la source (pas les paiements) : une convention pluriannuelle est comptée "
    "l'année de sa signature ou de son engagement.",
    "Une ligne sans montant publié est comptée dans `lignes_montant_non_communique`, jamais comme 0.",
    "Le département est celui du bénéficiaire (ADEME, Culture, Fonds vert, festivals) ou du service attribuant "
    "(politique de la ville) ; l'agence Artois-Picardie, les ADSV, le FIR et la presse ne le publient pas.",
    "Politique de la ville 2021 : les identifiants des bénéficiaires sont publiés en notation scientifique "
    "(« 1,30002E+13 ») ; ils ne permettent pas de retrouver le SIREN, les montants sont agrégés.",
    "Fonds vert, programme 113, 2024 : le fichier ne publie pas de SIRET ; les montants sont agrégés.",
    "Festivals : environ la moitié des lignes n'ont pas de SIRET ; les montants sont agrégés.",
]

REGLE_PERSONNES = ("Seuls les bénéficiaires dont la catégorie juridique SIRENE est une personne morale (2xxx à 9xxx, hors "
                   "groupements de personnes physiques) sont nommés. Entrepreneurs individuels, identifiants absents, "
                   "invalides ou absents du stock SIRENE : montants agrégés, jamais nommés. Équipes artistiques "
                   "(festivals, ADSV) : une dénomination qui contient peut-être un nom de personne (filtre de "
                   "pipeline/local.py) est agrégée aussi (`dont_nom_de_personne_possible_eur`).")
REGLE_TITRES = ("Les aides à la presse sont publiées par titre (publication), sans SIREN : un titre est nommé s'il ne "
                "contient aucun prénom fréquent suivi d'un nom ni civilité (filtre de pipeline/local.py) ; sinon son "
                "montant est agrégé dans `titres_non_nommes`.")


# --- Utilitaires -----------------------------------------------------------------------------------------------------


def eur(v: float) -> float:
    return round(v + 0.0, 2)


def propre(v) -> str:
    if v is None:
        return ""
    s = unicodedata.normalize("NFC", str(v)).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().strip('"').strip()


def montant(v) -> float | None:
    """Montant publié, ou None (absent, « nc », illisible) : jamais 0 par défaut."""
    s = propre(v).replace(" ", "").replace("€", "")
    if not s or s.lower() in ("nc", "n.c.", "nd", "-", "null", "none"):
        return None
    if re.match(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$", s):  # 1.234.567,89
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return None
    return x if x == x else None


def siren(v) -> str:
    """SIREN d'un SIREN ou SIRET publié ; chaîne vide si absent ou illisible (notation scientifique, etc.)."""
    s = propre(v)
    if not s or re.search(r"[eE][+-]?\d", s):
        return ""
    d = re.sub(r"[\s.]", "", s)
    if not d.isdigit():
        return ""
    if len(d) in (13, 8):  # zéro de tête perdu par un tableur
        d = "0" + d
    return d[:9] if len(d) in (9, 14) else ""


def annee(v) -> int | None:
    m = re.search(r"(20[0-3]\d)", propre(v))
    return int(m.group(1)) if m else None


def sans_accent(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()


def decoder(octets: bytes) -> str:
    try:
        return octets.decode("utf-8-sig")
    except UnicodeDecodeError:
        return octets.decode("cp1252", errors="replace")


def lignes_csv(chemin: Path, sep: str | None = None) -> list[dict]:
    """Lit un CSV de taille moyenne (encodage et séparateur détectés) ; clés d'en-tête nettoyées des guillemets."""
    texte = decoder(chemin.read_bytes())
    lignes = texte.splitlines()
    while lignes and not lignes[0].strip(" ;,\t\"'"):
        lignes.pop(0)  # lignes vides en tête (politique de la ville 2019)
    texte = "\n".join(lignes)
    if sep is None:
        sep = ";" if lignes and lignes[0].count(";") >= lignes[0].count(",") else ","
    lecteur = csv.reader(io.StringIO(texte), delimiter=sep)
    entete = [propre(c).strip('"').strip() for c in next(lecteur)]
    return [dict(zip(entete, r)) for r in lecteur if any(propre(x) for x in r)]


def col(ligne: dict, *motifs: str) -> str | None:
    """Nom de colonne dont la forme normalisée commence par l'un des motifs (ordre de priorité)."""
    norm = {re.sub(r"[^a-z0-9]", "", sans_accent(c).lower()): c for c in ligne}
    for m in motifs:
        for k, c in norm.items():
            if k.startswith(m):
                return c
    return None


# --- Départements ------------------------------------------------------------------------------------------------------


def departements() -> dict[str, str]:
    """Code -> nom des 101 départements (site/data/local/geo, code officiel géographique)."""
    res = {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8")).get("departement") or {}
        if d.get("code"):
            res[d["code"]] = d["nom"]
    if len(res) != 101:
        raise SystemExit(f"site/data/local/geo : {len(res)} départements au lieu de 101")
    return res


DEPS: dict[str, str] = {}
DEPS_NOMS: list[tuple[str, str]] = []


def _init_deps() -> None:
    global DEPS_NOMS
    if not DEPS:
        DEPS.update(departements())
        DEPS_NOMS = sorted(((re.sub(r"[^A-Z]+", " ", sans_accent(n)).strip(), c) for c, n in DEPS.items()),
                           key=lambda x: -len(x[0]))


def dep_code(v) -> str | None:
    _init_deps()
    s = propre(v).upper()
    if not s:
        return None
    if re.match(r"^\d{1,3}$", s):
        s = s.zfill(2)
    return s if s in DEPS else None


def dep_cp(cp) -> str | None:
    s = re.sub(r"\D", "", propre(cp))
    if len(s) == 4:
        s = "0" + s
    if len(s) != 5:
        return None
    if s.startswith("97"):
        return dep_code(s[:3])
    if s.startswith("20"):
        return "2A" if int(s) < 20200 else "2B"
    return dep_code(s[:2])


def dep_nom(texte) -> str | None:
    """Département dont le nom figure dans le libellé du service attribuant (« CGET - DDCS AIN-147 »)."""
    _init_deps()
    t = " " + re.sub(r"[^A-Z]+", " ", sans_accent(propre(texte))) + " "
    for nom, c in DEPS_NOMS:
        if f" {nom} " in t:
            return c
    return None


# --- Lecteurs : chaque ligne -> enregistrement commun -----------------------------------------------------------------
# (annee, montant, siren, departement, programme, dispositif, nom_usage, recouvrement)


def rec(annee_, montant_, siren_, dep=None, programme=None, dispositif=None, nom_usage=None, recouvrement=False):
    return (annee_, montant_, siren_, dep, programme, dispositif, nom_usage, recouvrement)


def fichiers(sid: str) -> list[Path]:
    """Fichiers collectés d'une source, d'après le manifeste de l'entrepôt (sinon recherche dans les deux zones)."""
    try:
        m = json.loads((LAKE / "manifest.json").read_text(encoding="utf-8")).get(sid) or {}
    except (OSError, ValueError):
        m = {}
    res = [ROOT / f["chemin"] for f in m.get("fichiers", []) if (ROOT / f["chemin"]).exists()]
    if not res:
        for zone in (LAKE / "_restreint" / "subventions", LAKE / "subventions"):
            res += [p for p in sorted(zone.glob(f"{sid}*")) if p.is_file()]
            res += sorted(p for p in (zone / sid).glob("*") if p.is_file()) if (zone / sid).is_dir() else []
    return sorted(set(p for p in res if p.suffix.lower() == ".csv"))


def lire_scdl_ademe(sid):
    for f in fichiers(sid):
        for r in lignes_csv(f, ","):
            yield rec(annee(r.get("dateConvention")), montant(r.get("montant")), siren(r.get("idBeneficiaire")),
                      dep_code(r.get("_siret_infos._infos_commune.code_departement")), None,
                      propre(r.get("dispositifAide")) or None)


def lire_scdl_aeap(sid):
    for f in fichiers(sid):
        prog = "12e programme d'intervention" if "_12_" in f.name.upper() or "12_PRG" in f.name.upper() \
            else "10e et 11e programmes d'intervention"
        for r in lignes_csv(f, ";"):
            if not any(propre(v) for v in r.values()):
                continue
            yield rec(annee(r.get("dateConvention")), montant(r.get("montant")), siren(r.get("idBeneficiaire")),
                      None, None, prog)


def lire_scdl_fir(sid):
    for f in fichiers(sid):
        for r in lignes_csv(f, ","):
            yield rec(annee(r.get("dateConvention")), montant(r.get("montant")), siren(r.get("idBeneficiaire")),
                      None, None, propre(r.get("dispositifAide")) or None)


def lire_fonds_vert(sid):
    for f in fichiers(sid):
        a = annee(f.name)
        p113 = "p113" in f.name.lower()
        for r in lignes_csv(f, ","):
            c_sir = col(r, "siretbeneficiaire", "siren")
            c_op = col(r, "operateur")
            op = propre(r.get(c_op)) if c_op else ""
            c_dem = col(r, "demarche", "nomdemarcheds", "source")
            yield rec(a, montant(r.get("montant_engage")), siren(r.get(c_sir)) if c_sir else "",
                      dep_code(r.get("code_departement")), "113" if p113 else "380",
                      propre(r.get(c_dem)) or None if c_dem else None, None, op.upper() == "ADEME")


def lire_culture_scdl(sid):
    """163 Mo en cp1252 : lu en flux, ligne à ligne."""
    for f in fichiers(sid):
        with f.open(encoding="cp1252", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                prog = propre(r.get("programme_code"))
                yield rec(annee(r.get("annee")), montant(r.get("montant_engage")),
                          siren(r.get("beneficiaire_siren") or r.get("beneficiaire_siret")),
                          dep_code(r.get("beneficiaire_departement_code")), prog.zfill(3) if prog.isdigit() else None,
                          propre(r.get("origine_credits")) or None)


def lire_festivals(sid):
    for f in fichiers(sid):
        for r in lignes_csv(f, ";"):
            c_mt = col(r, "montant")
            insee = propre(r.get(col(r, "lieudufestivalcodeinsee") or "") or "")
            dep = (dep_code(insee[:3]) if insee.startswith("97") else dep_code(insee[:2])) if len(insee) == 5 else None
            dep = dep or dep_cp(r.get(col(r, "codepostal") or ""))
            yield rec(annee(r.get("Année")), montant(r.get(c_mt)), siren(r.get("SIRET")), dep, "131",
                      propre(r.get(col(r, "domaineartistique") or "")) or None, propre(r.get(col(r, "nomdufestival") or "")))


def lire_adsv(sid):
    """Colonnes lues : année, type d'aide, montant ADSV ou DGCA, SIRET, nom de l'équipe (filtré) ; jamais la direction
    ni la parité (genre) de l'équipe."""
    for f in fichiers(sid):
        for r in lignes_csv(f, ";"):
            m = montant(r.get(col(r, "montantattribueadsv") or ""))
            if m is None:
                m = montant(r.get(col(r, "montantdgca") or ""))
            yield rec(annee(r.get("Année")), m, siren(r.get(col(r, "nsiret", "siret") or "")), None, "131",
                      propre(r.get(col(r, "typeaide") or "")) or None, propre(r.get(col(r, "nomdelequipe") or "")))


def lire_p147(sid):
    for f in fichiers(sid):
        a_fichier = annee(f.name)
        for r in lignes_csv(f, ";"):
            c_att = col(r, "nomdelattribuant")
            c_code = col(r, "codedepartement")
            c_lib = col(r, "libelledepartement")
            c_ben = col(r, "identificationdubeneficiaire")
            c_mt = col(r, "montanttotal")
            dep = dep_code(r.get(c_code)) if c_code else None
            dep = dep or (dep_nom(r.get(c_lib)) if c_lib else None) or dep_nom(r.get(c_att))
            yield rec(a_fichier, montant(r.get(c_mt)), siren(r.get(c_ben)), dep, "147", None)


def _titres(chemin: Path, dispositif: str | None, c_total_motif: str):
    for r in lignes_csv(chemin, ";"):
        c_titre = col(r, "beneficiaires", "titre")
        c_mt = col(r, c_total_motif, "montant")
        yield rec(annee(r.get(col(r, "annee") or "")), montant(r.get(c_mt)), "", None, "180", dispositif,
                  propre(r.get(c_titre)))


def lire_presse_titres(sid):
    for f in fichiers(sid):
        yield from _titres(f, None, "totaldesaides")


def lire_presse_dispositifs(sid):
    for f in fichiers(sid):
        rid = re.search(r"_([0-9a-f]{8})\.csv$", f.name)
        disp = DISPOSITIFS_PRESSE.get(rid.group(1) if rid else "")
        if disp is None:
            continue  # ressource ancienne ou inconnue : la plus récente de chaque jeu suffit (elle contient les autres)
        yield from _titres(f, disp, "montant")


LECTEURS = {"scdl_ademe": lire_scdl_ademe, "scdl_aeap": lire_scdl_aeap, "scdl_fir": lire_scdl_fir,
            "fonds_vert": lire_fonds_vert, "culture_scdl": lire_culture_scdl, "festivals": lire_festivals,
            "adsv": lire_adsv, "p147": lire_p147, "presse_titres": lire_presse_titres,
            "presse_dispositifs": lire_presse_dispositifs}


# --- Classement des bénéficiaires --------------------------------------------------------------------------------------


def sirene_stock(sirens: set[str]) -> dict:
    """SIREN -> (catégorie juridique, dénomination si personne morale), stock SIRENE local (pipeline/local.py)."""
    import local
    return local.sirene_cj(sirens) if sirens else {}


def filtre_noms():
    import local
    liste = local.prenoms()
    return lambda nom: bool(nom) and not local.contient_nom_de_personne(nom, liste)


def statut(s: str, stock: dict) -> tuple[str, str | None]:
    """('pm', cj) nommable ; ('pp', cj) personne physique ; ('ni', None) sans SIREN ; ('in', None) absent du stock."""
    if not sirene.siren_valide(s):
        return "ni", None
    if s not in stock:
        return "in", None
    cj = stock[s][0] or ""
    if sirene.personne_morale(cj):
        return "pm", cj
    if cj.startswith("1") or cj in sirene.CJ_PERSONNES_PHYSIQUES:
        return "pp", cj
    return "in", None


EXCLUS_CLES = {"pp": "dont_personnes_physiques_eur", "ni": "dont_sans_siren_eur", "in": "dont_siren_introuvable_eur",
               "np": "dont_nom_de_personne_possible_eur"}
ARTISTIQUES = ("festivals", "adsv")  # équipes artistiques : dénomination passée au filtre de noms de personnes


def exclus_vide(artistique: bool = False) -> dict:
    return {"montant_eur": 0.0, "lignes": 0,
            **{k: 0.0 for c, k in EXCLUS_CLES.items() if c != "np" or artistique}}


def groupe(par_siren: dict, stock: dict, exclus: dict, total: float, noms_usage: dict | None = None) -> dict:
    """Groupe de bénéficiaires (commun.schema.json) ; conservation : top + autres + exclus = total, à 1 € près."""
    tries = sorted(par_siren.items(), key=lambda kv: (-kv[1]["montant"], kv[0]))
    top = []
    for s, d in tries[:TOP]:
        b = {"siren": s, "denomination": stock[s][1] or s, "categorie_juridique": stock[s][0],
             "montant_eur": eur(d["montant"]), "conventions": d["lignes"]}
        if d.get("sources"):
            b["sources"] = sorted(d["sources"])
        if noms_usage is not None and noms_usage.get(s):
            b["noms_usage"] = sorted(noms_usage[s])[:3]
        top.append(b)
    reste = tries[TOP:]
    ex = {k: (eur(v) if k != "lignes" else v) for k, v in exclus.items()}
    res = {"total_eur": eur(total), "top": top,
           "autres_personnes_morales": {"nombre": len(reste), "montant_eur": eur(sum(d["montant"] for _, d in reste))},
           "autres_non_verifies": {"nombre": 0, "montant_eur": 0.0,
                                   "note": "Aucun : chaque SIREN est vérifié dans le stock SIRENE."},
           "exclus_personnes_physiques_ou_non_identifies": ex}
    somme = (sum(b["montant_eur"] for b in top) + res["autres_personnes_morales"]["montant_eur"]
             + ex["montant_eur"])
    if abs(somme - res["total_eur"]) > 1:
        raise SystemExit(f"conservation rompue : {somme} != {total}")
    return res


# --- Production ----------------------------------------------------------------------------------------------------------


def dump(chemin: Path, obj) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    if len(texte.encode("utf-8")) > MAX_OCTETS:
        raise SystemExit(f"{chemin} dépasse 5 Mo")
    chemin.write_text(texte + "\n", encoding="utf-8")


def lire_tout() -> dict[str, list]:
    donnees = {}
    for sid, s in SOURCES.items():
        if not fichiers(sid):
            print(f"  {sid} : aucun fichier dans l'entrepôt", file=sys.stderr)
            continue
        donnees[sid] = list(LECTEURS[s["lecteur"]](sid))
        print(f"  {sid} : {len(donnees[sid])} lignes", file=sys.stderr)
    return donnees


def _r(d: dict) -> dict:
    return {k: (eur(v) if isinstance(v, float) else v) for k, v in d.items()}


def produire() -> dict:
    _init_deps()
    donnees = lire_tout()
    if not donnees:
        raise SystemExit("aucune source dans l'entrepôt : lancer d'abord `python pipeline/subventions.py collecter`")
    sirens = {r[2] for lignes in donnees.values() for r in lignes if sirene.siren_valide(r[2])}
    stock = sirene_stock(sirens)
    nommable = filtre_noms()
    date = date_sources("subventions")
    for f in SORTIE.rglob("*.json"):
        f.unlink()

    tot_annee = defaultdict(lambda: defaultdict(lambda: {"montant_eur": 0.0, "conventions": 0,
                                                         "lignes_montant_non_communique": 0}))
    tot_dep = defaultdict(lambda: defaultdict(float))
    tot_dep_annee = defaultdict(lambda: defaultdict(float))
    tot_dep_conv = defaultdict(int)
    non_localise = defaultdict(float)
    progs = defaultdict(lambda: {"par_annee": defaultdict(float), "nomme": defaultdict(float), "lignes": 0})
    glob_siren, glob_exclus, glob_total = {}, exclus_vide(), 0.0
    resume_sources = []

    for sid, lignes in donnees.items():
        s = SOURCES[sid]
        titres = bool(s.get("titres"))
        par_annee = defaultdict(lambda: {"montant_eur": 0.0, "conventions": 0, "lignes_montant_non_communique": 0,
                                         "montant_nomme_eur": 0.0})
        par_dep = defaultdict(lambda: {"montant_eur": 0.0, "conventions": 0})
        par_disp = defaultdict(lambda: {"montant_eur": 0.0, "conventions": 0})
        par_prog = defaultdict(lambda: defaultdict(float))
        artistique = s["lecteur"] in ARTISTIQUES
        par_siren, exclus, noms_usage = {}, exclus_vide(artistique), defaultdict(set)
        par_titre, titres_retires = defaultdict(lambda: {"montant": 0.0, "lignes": 0}), {"montant": 0.0, "noms": set()}
        total, nc, retire, sans_annee = 0.0, 0, 0.0, 0
        for a, m, si, dep, prog, disp, nom, recouv in lignes:
            if m is None:
                nc += 1
                par_annee[a or 0]["lignes_montant_non_communique"] += 1
                continue
            total += m
            pa = par_annee[a or 0]
            pa["montant_eur"] += m
            pa["conventions"] += 1
            if a is None:
                sans_annee += 1
            par_dep[dep or "non_publie"]["montant_eur"] += m
            par_dep[dep or "non_publie"]["conventions"] += 1
            if disp:
                par_disp[disp]["montant_eur"] += m
                par_disp[disp]["conventions"] += 1
            if prog:
                par_prog[prog][a or 0] += m
            if titres:
                if nommable(nom):
                    par_titre[nom]["montant"] += m
                    par_titre[nom]["lignes"] += 1
                else:
                    titres_retires["montant"] += m
                    titres_retires["noms"].add(nom)
                continue
            st, cj = statut(si, stock)
            if st == "pm" and artistique and not nommable(stock[si][1] or ""):
                st = "np"  # dénomination d'une équipe artistique qui contient peut-être un nom de personne
            if st == "pm":
                b = par_siren.setdefault(si, {"montant": 0.0, "lignes": 0})
                b["montant"] += m
                b["lignes"] += 1
                pa["montant_nomme_eur"] += m
                if prog:
                    progs[(prog, sid)]["nomme"][a or 0] += m
                if nom and nommable(nom):
                    noms_usage[si].add(nom[:120])
            else:
                exclus["montant_eur"] += m
                exclus["lignes"] += 1
                exclus[EXCLUS_CLES[st]] += m
            if s["additionne"]:
                if recouv:
                    retire += m
                    continue
                ta = tot_annee[a or 0][sid]
                ta["montant_eur"] += m
                ta["conventions"] += 1
                glob_total += m
                if dep:
                    tot_dep[dep][sid] += m
                    tot_dep_annee[dep][a or 0] += m
                    tot_dep_conv[dep] += 1
                else:
                    non_localise[sid] += m
                if st == "pm":
                    g = glob_siren.setdefault(si, {"montant": 0.0, "lignes": 0, "sources": set()})
                    g["montant"] += m
                    g["lignes"] += 1
                    g["sources"].add(sid)
                else:
                    glob_exclus["montant_eur"] += m
                    glob_exclus["lignes"] += 1
                    glob_exclus[EXCLUS_CLES[st]] += m
        for (a, d) in par_annee.items():
            if s["additionne"] and d["lignes_montant_non_communique"]:
                tot_annee[a][sid]["lignes_montant_non_communique"] += d["lignes_montant_non_communique"]
        for p, ann in par_prog.items():
            e = progs[(p, sid)]
            for a, v in ann.items():
                e["par_annee"][a] += v

        # fichier de la source
        obj = {"millesime": s["millesime"], "source": f"{s['titre']}, {s['page']}", "unite": "euros",
               "id": sid, "attribuant": s["attribuant"], "producteur": s["producteur"], "licence": s["licence"],
               "collecte_le": date, "rattachement": s["rattachement"], "additionne": s["additionne"],
               "inclus_dans": s.get("inclus_dans"),
               "total_eur": eur(total), "conventions": len(lignes) - nc, "lignes_montant_non_communique": nc,
               "conventions_sans_annee": sans_annee,
               "montant_retire_des_totaux_eur": eur(retire),
               "par_annee": [{"annee": a or None, **_r(d)} for a, d in sorted(par_annee.items())],
               "par_departement": [{"departement": k if k != "non_publie" else None,
                                    "nom": DEPS.get(k), **_r(d)} for k, d in
                                   sorted(par_dep.items(), key=lambda kv: (kv[0] == "non_publie", kv[0]))],
               "par_programme": [{"programme": p, "par_annee": [{"annee": a or None, "montant_eur": eur(v)}
                                                                 for a, v in sorted(ann.items())],
                                  "montant_eur": eur(sum(ann.values()))} for p, ann in sorted(par_prog.items())]}
        disp_tries = sorted(par_disp.items(), key=lambda kv: (-kv[1]["montant_eur"], kv[0]))
        obj["par_dispositif"] = [{"dispositif": k, **_r(d)} for k, d in disp_tries[:TOP]]
        obj["par_dispositif_autres"] = {"nombre": len(disp_tries[TOP:]),
                                        "montant_eur": eur(sum(d["montant_eur"] for _, d in disp_tries[TOP:]))}
        if titres:
            tries = sorted(par_titre.items(), key=lambda kv: (-kv[1]["montant"], kv[0]))
            obj["titres"] = {"total_eur": eur(total),
                             "top": [{"titre": t, "montant_eur": eur(d["montant"]), "lignes": d["lignes"]}
                                     for t, d in tries[:TOP]],
                             "autres_titres": {"nombre": len(tries[TOP:]),
                                               "montant_eur": eur(sum(d["montant"] for _, d in tries[TOP:]))},
                             "titres_non_nommes": {"nombre": len(titres_retires["noms"]),
                                                   "montant_eur": eur(titres_retires["montant"]),
                                                   "note": REGLE_TITRES}}
            ssum = (sum(t["montant_eur"] for t in obj["titres"]["top"]) + obj["titres"]["autres_titres"]["montant_eur"]
                    + obj["titres"]["titres_non_nommes"]["montant_eur"])
            if abs(ssum - obj["titres"]["total_eur"]) > 1:
                raise SystemExit(f"{sid} : conservation des titres rompue")
            nommes_n, nommes_m = len(tries), sum(d["montant"] for _, d in tries)
            agrege = titres_retires["montant"]
            obj["regle_personnes"] = REGLE_TITRES
        else:
            obj["beneficiaires"] = groupe(par_siren, stock, exclus, total,
                                          noms_usage if artistique else None)
            nommes_n, nommes_m, agrege = len(par_siren), sum(d["montant"] for d in par_siren.values()), exclus["montant_eur"]
            obj["regle_personnes"] = REGLE_PERSONNES
        obj["nommes"] = {"nombre": nommes_n, "montant_eur": eur(nommes_m)}
        obj["agrege_confidentialite"] = {"montant_eur": eur(agrege),
                                         "part_pct": round(agrege / total * 100, 2) if total else None}
        if s.get("region"):
            obj["region"] = s["region"]
        dump(SORTIE / "attribuants" / f"{sid}.json", obj)
        resume_sources.append({
            "id": sid, "titre": s["titre"], "attribuant": s["attribuant"], "producteur": s["producteur"],
            "page": s["page"], "licence": s["licence"], "millesime": s["millesime"],
            "rattachement": s["rattachement"], "additionne": s["additionne"], "inclus_dans": s.get("inclus_dans"),
            "annees": sorted({a for a in par_annee if a}), "conventions": obj["conventions"],
            "lignes_montant_non_communique": nc, "total_eur": eur(total),
            "montant_retire_des_totaux_eur": eur(retire),
            "nommes": obj["nommes"], "agrege_confidentialite": obj["agrege_confidentialite"],
            "fichier": f"subventions/attribuants/{sid}.json"})

    # par année, toutes sources
    annees = []
    for a in sorted(tot_annee):
        ps = tot_annee[a]
        annees.append({"annee": a or None,
                       "total_additionne_eur": eur(sum(d["montant_eur"] for d in ps.values())),
                       "conventions": sum(d["conventions"] for d in ps.values()),
                       "par_source": {k: _r(v) for k, v in sorted(ps.items())}})
    dump(SORTIE / "annees.json", {
        "millesime": "2016 à 2026 selon la source", "source": "voir subventions/index.json (sources)", "unite": "euros",
        "note": NOTE_ADDITION, "sources_additionnees": sorted(k for k, s in SOURCES.items() if s["additionne"]),
        "annees": annees})

    # par département
    deps = {}
    for c in sorted(tot_dep):
        deps[c] = {"nom": DEPS[c], "total_additionne_eur": eur(sum(tot_dep[c].values())), "conventions": tot_dep_conv[c],
                   "par_source": {k: eur(v) for k, v in sorted(tot_dep[c].items())},
                   "par_annee": {str(a): eur(v) for a, v in sorted(tot_dep_annee[c].items()) if a}}
    dump(SORTIE / "departements.json", {
        "millesime": "2016 à 2026 selon la source", "source": "voir subventions/index.json (sources)", "unite": "euros",
        "note": NOTE_ADDITION + " Le département est celui du bénéficiaire, ou du service attribuant pour la politique "
                                "de la ville.",
        "departements": deps,
        "non_localise": {k: eur(v) for k, v in sorted(non_localise.items())}})

    # bénéficiaires toutes sources
    benef = groupe(glob_siren, stock, glob_exclus, glob_total)
    dump(SORTIE / "beneficiaires.json", {
        "millesime": "2016 à 2026 selon la source", "source": "voir subventions/index.json (sources) ; " + SIRENE_SOURCE,
        "unite": "euros", "note": NOTE_ADDITION + " Les lignes du Fonds vert instruites par l'ADEME sont retirées "
                                                  "(recouvrement possible avec les conventions de l'ADEME).",
        "regle_personnes": REGLE_PERSONNES, **benef})

    # programmes LOLF
    programmes = []
    for (p, sid), e in sorted(progs.items()):
        programmes.append({"programme": p, "source": sid, "rattachement": SOURCES[sid]["rattachement"]["type"],
                           "additionne": SOURCES[sid]["additionne"],
                           "montant_eur": eur(sum(e["par_annee"].values())),
                           "par_annee": [{"annee": a or None, "montant_eur": eur(v),
                                          "montant_nomme_eur": eur(e["nomme"].get(a, 0.0))}
                                         for a, v in sorted(e["par_annee"].items())]})
    operateurs = [{"source": sid, "operateur": s["rattachement"]["operateur"],
                   "programme_chef_de_file": s["rattachement"]["programme_chef_de_file"],
                   "fichier": s["rattachement"]["fichier"], "id": s["rattachement"]["id"]}
                  for sid, s in SOURCES.items() if s["rattachement"]["type"] == "operateur" and sid in donnees]
    dump(SORTIE / "programmes.json", {
        "millesime": "2016 à 2026 selon la source", "source": "voir subventions/index.json (sources)", "unite": "euros",
        "note": "Montants engagés ou attribués, par programme LOLF publié dans la source (Culture) ou fixé par le "
                "dispositif (Fonds vert, politique de la ville, festivals, ADSV, presse). Un opérateur (ADEME, agence "
                "de l'eau) attribue sur ses ressources propres : il est relié au programme chef de file, sans montant "
                "par programme. " + NOTE_ADDITION,
        "programmes": programmes, "operateurs": operateurs})

    # index
    tot_add = sum(x["total_eur"] - x["montant_retire_des_totaux_eur"] for x in resume_sources if x["additionne"])
    agr_add = glob_exclus["montant_eur"]
    index = {
        "millesime": "2016 à 2026 selon la source", "source": "data.gouv.fr et data.ademe.fr (sources ci-dessous) ; "
                                                             + SIRENE_SOURCE,
        "unite": "euros", "collecte_le": date, "regle_personnes": REGLE_PERSONNES, "regle_titres": REGLE_TITRES,
        "note": NOTE_ADDITION, "limites": LIMITES,
        "totaux": {"total_additionne_eur": eur(tot_add), "nommes_additionnes": {
            "nombre": len(glob_siren), "montant_eur": eur(sum(d["montant"] for d in glob_siren.values()))},
            "agrege_confidentialite": {"montant_eur": eur(agr_add),
                                       "part_pct": round(agr_add / tot_add * 100, 2) if tot_add else None}},
        "sources": resume_sources, "recouvrements": RECOUVREMENTS,
        "sources_inaccessibles": sources_inaccessibles(donnees),
        "fichiers": ["subventions/annees.json", "subventions/departements.json", "subventions/beneficiaires.json",
                     "subventions/programmes.json"] + [x["fichier"] for x in resume_sources],
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(SORTIE / "index.json", index)
    return index


SIRENE_SOURCE = "Insee, base SIRENE des unités légales (data.gouv.fr, stock du 1er novembre 2026), catégorie juridique"


def sources_inaccessibles(donnees: dict) -> list[dict]:
    try:
        m = json.loads((LAKE / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {}
    res = []
    for sid in SOURCES:
        e = m.get(sid) or {}
        if sid not in donnees:
            res.append({"source": sid, "motif": e.get("erreur") or "absente de l'entrepôt"})
        elif e.get("statut") not in (None, "ok", "partiel"):
            res.append({"source": sid, "motif": f"dernière collecte : {e.get('statut')} ; données antérieures publiées"})
    return res


# --- Collecte ----------------------------------------------------------------------------------------------------------


def collecter() -> int:
    """Collecte des sources subv_* par collecte/collecte.py (manifeste, reprise, zone restreinte)."""
    sys.path.insert(0, str(ROOT / "collecte"))
    import collecte
    return collecte.main(list(SOURCES))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("etapes", nargs="*", help="collecter, produire (défaut : les deux)")
    a = ap.parse_args(argv)
    etapes = a.etapes or ["collecter", "produire"]
    if set(etapes) - {"collecter", "produire"}:
        ap.error("étapes possibles : collecter, produire")
    if "collecter" in etapes:
        collecter()
    if "produire" in etapes:
        idx = produire()
        t = idx["totaux"]
        print(f"subventions : {len(idx['sources'])} sources, {t['total_additionne_eur'] / 1e9:.2f} Md€ additionnés, "
              f"{t['nommes_additionnes']['nombre']} bénéficiaires nommés, "
              f"{t['agrege_confidentialite']['part_pct']} % agrégés")


if __name__ == "__main__":
    main()
