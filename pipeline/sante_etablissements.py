"""Établissements de santé et médico-sociaux : qui existe, où, avec quelle activité publiée et quels prix affichés.

Ce module ne publie AUCUN flux d'argent public par établissement après 2015 : ces données ne sont pas ouvertes
(voir `limites.json`). Il donne le référentiel des établissements (FINESS), l'activité publiée par établissement
(Open CCAM, ATIH), les prix d'hébergement et tarifs dépendance des EHPAD (CNSA ; ce sont des prix facturés aux
résidents, pas une dépense publique), l'historique Hospi Diag 2011-2015 (derniers comptes par établissement ouverts)
et les comptes agrégés par catégorie d'établissement (ATIH, 2020-2024). Les montants nationaux versés par
l'assurance maladie sont dans `secu/` (ONDAM) : le lien est fait par renvoi, jamais par addition. Les subventions du
fonds d'intervention régional de l'ARS Pays de la Loire sont traitées par pipeline/subventions.py : renvoi seulement.

Entrées : entrepôt brut data/lake/sante/ et data/lake/secu/ (non versionné), sources déclarées dans
collecte/catalogue.json :
    sante_finess_structures          FINESS - Structures (Agence du numérique en santé), json.gz, flux en vigueur
    sante_finess_ej_gel, _et_gel     FINESS, extractions gelées au 04/05/2026 (libellés de nomenclature, écart)
    sante_open_ccam_etablissements   ATIH, Open CCAM par établissement (un csv par année) et documentation
    sante_cnsa_prix_ehpad            CNSA, prix hébergement et tarifs dépendance des EHPAD, données brutes annuelles
    sante_hospi_diag                 ANAP, Hospi Diag 2011-2015 (xlsx)
    sirene_categories_juridiques.json   catégories juridiques Sirene déjà vérifiées (écrit par `collecter`, sans nom)
    secu_atih_finances_ebnl          ATIH, données financières agrégées des établissements publics et EBNL
Sorties (site/data/sante_etablissements/, schémas docs/schemas/sante_etablissements_*.schema.json) :
    index.json                 périmètre, sources, totaux nationaux, nomenclature, liens, écarts, confidentialité
    limites.json               ce qui n'est PAS ouvert, ce qui existe à la place, recherches faites
    departements.json          par département : établissements, actes publiés, prix médians des EHPAD
    departements/<dep>.json    par commune, et établissements nommés (personnes morales seulement)
    hospi_diag.json            historique 2011-2015 : produits, recettes T2A et MIGAC, charges, résultat, dette
    finances_agregees.json     comptes agrégés par catégorie d'établissement, 2020-2024

Commandes :
    python pipeline/sante_etablissements.py collecter   # réseau : collecteur du dépôt puis catégories juridiques
                                                        # Sirene ; un refus 401/403/429 est noté, jamais contourné
    python pipeline/sante_etablissements.py produire    # sans réseau
    python pipeline/sante_etablissements.py             # les deux

Règles :
  - aucune donnée de patient : Open CCAM ne contient que des comptes d'actes par établissement, sans les lignes de
    moins de 11 séjours (retirées par l'ATIH) ; seuls des totaux par établissement et par an sont publiés ici ;
  - aucun professionnel nommé : les structures d'exercice libéral, les pharmacies d'officine, les laboratoires et
    toute structure dont l'entité juridique est une personne physique sont hors périmètre ; un établissement n'est
    nommé que si sa catégorie juridique Sirene est celle d'une personne morale (pipeline/sirene.py) et si sa
    dénomination ne contient pas un titre de personne ; sinon il est compté, jamais listé ;
  - adresses, téléphones, courriels, coordonnées géographiques : jamais lus au-delà du code de la commune ;
  - une valeur absente ou marquée non disponible à la source reste null, jamais 0 ;
  - toute date écrite vient de pipeline/reproductible.py ; ordres explicites : deux productions sur le même
    entrepôt sont identiques octet pour octet.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import statistics
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "sante"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "sante_etablissements"
REL = "sante_etablissements"

COLLECTABLES = ["sante_finess_structures", "sante_finess_ej_gel", "sante_finess_et_gel",
                "sante_open_ccam_etablissements", "sante_cnsa_prix_ehpad", "sante_hospi_diag",
                "secu_atih_finances_ebnl"]

SOURCES = {
    "finess_structures": {
        "titre": "FINESS - Structures : personnes morales (entités juridiques) et entités géographiques d'exercice, "
                 "flux de nouvelle génération, extraction mensuelle",
        "producteur": "Agence du numérique en santé",
        "url": "https://www.data.gouv.fr/datasets/finess-structures-1/",
        "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (référentiel en vigueur, mis à jour chaque jour ; aucun libellé de "
                   "nomenclature dans le flux)"},
    "finess_gel": {
        "titre": "FINESS, extractions des entités juridiques et des établissements au 04/05/2026 (flux historique, "
                 "gelé depuis le déploiement de la nouvelle version de FINESS le 20/07/2026)",
        "producteur": "Ministère chargé de la santé",
        "url": "https://www.data.gouv.fr/datasets/finess-extraction-du-fichier-des-etablissements/",
        "licence": "Licence Ouverte",
        "verdict": "à adapter (gelé : utilisé pour les libellés des catégories et des statuts, et pour l'écart "
                   "avec le flux en vigueur)"},
    "open_ccam": {
        "titre": "Open CCAM par établissement : nombre de séjours et d'actes par code d'acte CCAM (activité de "
                 "médecine, chirurgie, obstétrique et odontologie, PMSI)",
        "producteur": "ATIH",
        "url": "https://data-essentiel.atih.sante.fr/explore/dataset/open-ccam-etablissements/",
        "licence": "ODbL 1.0",
        "mention_obligatoire": "source OpenCCAM, année de chaque colonne, https://www.scansante.fr/",
        "verdict": "réutilisable tel quel (un csv par année)"},
    "cnsa_prix_ehpad": {
        "titre": "Prix hébergement et tarifs dépendance des EHPAD, données brutes déclarées par les établissements "
                 "(application Prix-ESMS), situation au 31 décembre de chaque année",
        "producteur": "CNSA",
        "url": "https://www.data.gouv.fr/datasets/prix-hebergement-et-tarifs-dependance-des-ehpad-donnees-brutes/",
        "licence": "non précisée : la fiche data.gouv.fr indique « notspecified » et la notice de la CNSA "
                   "(29/08/2025) ne nomme aucune licence ; elle indique une mise à disposition du public dans le "
                   "cadre de la loi n° 2016-1321 du 7 octobre 2016 pour une République numérique",
        "verdict": "à adapter (données brutes non retravaillées par la CNSA : colonnes de texte libre écartées, "
                   "valeurs hors bornes écartées des médianes)"},
    "hospi_diag": {
        "titre": "Hospi Diag, données 2011 à 2015 : carte d'identité et indicateurs financiers par établissement "
                 "de médecine, chirurgie, obstétrique",
        "producteur": "ANAP (avec l'ATIH)",
        "url": "https://www.data.gouv.fr/datasets/hospi-diag/",
        "licence": "Licence Ouverte",
        "verdict": "à adapter (historique seulement : jeu non mis à jour depuis le 18/07/2017 ; l'année 2010, "
                   "publiée aussi, n'est pas reprise)"},
    "atih_finances": {
        "titre": "Indicateurs de suivi financier de l'ATIH, données financières des établissements publics ou privés à but non lucratif, agrégées par "
                 "secteur, catégorie et activité principale, 2020 à 2024",
        "producteur": "ATIH",
        "url": "https://data-essentiel.atih.sante.fr/explore/dataset/isf-finance-ebnl-public/",
        "licence": "ODbL 1.0",
        "verdict": "réutilisable tel quel (déjà au catalogue : secu_atih_finances_ebnl ; agrégats sans aucun "
                   "établissement)"},
}

# Règle n°0 : recherche de l'existant, faite le 17/11/2026 (data.gouv.fr, portail de l'ATIH, GitHub).
RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "verdict": "jeux officiels réutilisés tels quels ou adaptés ; aucun dépôt public ne produit déjà ce croisement "
               "par commune ; aucun jeu ouvert trouvé pour les comptes, les dotations MIGAC et Ségur ou les "
               "forfaits soins par établissement",
    "trouvailles": [
        {"nom": "FINESS - Structures (Agence du numérique en santé)", "classement": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "derniere_modification": "2026-11-17 (quotidien)",
         "url": SOURCES["finess_structures"]["url"]},
        {"nom": "FINESS, extractions gelées (ministère chargé de la santé)", "classement": "à adapter",
         "licence": "Licence Ouverte", "derniere_modification": "2026-05-12 (gelé)", "url": SOURCES["finess_gel"]["url"]},
        {"nom": "Open CCAM par établissement (ATIH)", "classement": "réutilisable tel quel", "licence": "ODbL 1.0",
         "derniere_modification": "2026-06-25", "url": SOURCES["open_ccam"]["url"]},
        {"nom": "Prix des EHPAD, données brutes (CNSA)", "classement": "à adapter", "licence": "non précisée",
         "derniere_modification": "2026-02-13", "url": SOURCES["cnsa_prix_ehpad"]["url"]},
        {"nom": "Prix des EHPAD, données retraitées (CNSA)", "classement": "inspiration seulement",
         "licence": "non précisée", "derniere_modification": "2021-11-29 (ancien)",
         "url": "https://www.data.gouv.fr/datasets/prix-hebergement-et-tarifs-dependance-des-ehpad/"},
        {"nom": "Hospi Diag (ANAP)", "classement": "à adapter", "licence": "Licence Ouverte",
         "derniere_modification": "2017-07-18", "url": SOURCES["hospi_diag"]["url"]},
        {"nom": "Indicateurs de suivi financier, finances agrégées des établissements publics et EBNL (ATIH)",
         "classement": "réutilisable tel quel", "licence": "ODbL 1.0", "derniere_modification": "2026-10-01",
         "url": SOURCES["atih_finances"]["url"]},
        {"nom": "Subventions de l'ARS des Pays de la Loire au titre du fonds d'intervention régional",
         "classement": "réutilisable tel quel, déjà traité par pipeline/subventions.py (renvoi)",
         "licence": "Licence Ouverte 2.0", "derniere_modification": "2026-07-21",
         "url": "https://www.data.gouv.fr/datasets/"
                "subventions-de-lars-des-pays-de-la-loire-au-titre-du-fonds-dintervention-regional/"},
    ],
    "recherches_sans_resultat": [
        {"portail": "data.gouv.fr (API de recherche)", "requetes": ["MIGAC", "dotations hôpitaux", "hôpitaux comptes",
         "comptes financiers établissements publics de santé", "EPRD hôpital", "Ségur", "forfait soins EHPAD",
         "dotation soins EHPAD"],
         "resultat": "aucun jeu sur les comptes, les dotations ou les forfaits soins par établissement ; « Ségur » "
                     "ne renvoie que des jeux sans rapport (commune du Ségur, zones inondables)"},
        {"portail": "data-essentiel.atih.sante.fr (53 jeux)", "requetes": ["catalogue complet"],
         "resultat": "activité et référentiels de coûts nationaux, finances agrégées par catégorie ; aucun compte "
                     "par établissement"},
        {"portail": "GitHub (recherche de dépôts)", "requetes": ["finess", "hospidiag", "ehpad prix",
         "open ccam atih"], "resultat": "aucun dépôt réutilisable pour ce croisement"},
    ],
}

# --- Périmètre ---------------------------------------------------------------------------------------------------

# Catégories agrégées FINESS hors périmètre : exercice libéral et commerce (souvent des personnes physiques ou des
# sociétés portant le nom d'un professionnel).
AGREGATS_EXCLUS = {
    "2103": "structures d'exercice libéral (maisons de santé, communautés professionnelles, lieux de soins non "
            "programmés, équipes de soins spécialisées)",
    "3101": "laboratoires de biologie médicale",
    "3201": "commerce de biens à usage médical (pharmacies d'officine, propharmacies, oxygène à domicile)",
}
STATUT_PERSONNE_PHYSIQUE = "70"

DOMAINES = [  # (identifiant, premier chiffre de la catégorie agrégée FINESS, libellé)
    ("hospitalier", "1", "Établissements relevant de la loi hospitalière (hôpitaux, cliniques, psychiatrie, soins "
                         "médicaux et de réadaptation, soins de longue durée, dialyse, hospitalisation à domicile)"),
    ("soins_prevention", "2", "Autres établissements de soins et de prévention (centres de santé, protection "
                              "maternelle et infantile, dispensaires)"),
    ("autres_sanitaires", "3", "Autres établissements à caractère sanitaire (transfusion sanguine, santé au "
                               "travail, structures d'appui)"),
    ("social_medico_social", "4", "Établissements et services sociaux et médico-sociaux (personnes âgées, "
                                  "handicap, protection de l'enfance, hébergement social)"),
    ("formation", "6", "Établissements de formation des personnels sanitaires et sociaux"),
    ("non_classe", None, "Catégorie sans libellé dans la dernière nomenclature publiée (extraction gelée de mai "
                         "2026)"),
]
DOMAINE_IDS = [d[0] for d in DOMAINES]
SECTEURS = [  # regroupement du projet d'après les plages de codes du statut juridique FINESS
    ("public", 1, 39, "Public (État, collectivités, établissements publics)"),
    ("prive_non_lucratif", 40, 69, "Privé à but non lucratif (organismes de sécurité sociale, mutuelles, "
                                   "associations, fondations, congrégations)"),
    ("prive_commercial", 70, 99, "Privé à caractère commercial et autres organismes privés (sociétés, "
                               "groupements de coopération de droit privé)"),
]
SECTEUR_IDS = [s[0] for s in SECTEURS]
CATEGORIE_EHPAD = "500"

TITRE_PERSONNE = re.compile(
    r"(?<![A-Za-zÀ-ÿ])(?:DR|DRS|DOCTEUR|DOCTEURS|PR|PROFESSEUR|MME|MMES|MADAME|MLLE|MADEMOISELLE|MONSIEUR|MR|"
    r"M\.|MM\.|MAITRE|MAÎTRE|CABINET|VEUVE|VVE|EPOUSE|ÉPOUSE|NEE|NÉE)(?![A-Za-zÀ-ÿ])", re.I)

# Bornes de vraisemblance des prix déclarés (euros par jour) : hors bornes, la valeur déclarée reste publiée pour
# l'établissement mais n'entre pas dans les médianes.
PRIX_MIN, PRIX_MAX = 20.0, 400.0
TARIF_MIN, TARIF_MAX = 1.0, 80.0

HD_ANNEES = [2011, 2012, 2013, 2014, 2015]
HD_MESURES = [  # (clé publiée, radical de la colonne Hospi Diag, libellé de la source)
    ("produits_eur", "CI_F1", "Total des produits courants de fonctionnement (cliniques : d'exploitation)"),
    ("recettes_t2a_eur", "CI_F2", "dont recettes de tarification à l'activité (T2A)"),
    ("recettes_migac_eur", "CI_F3", "dont recettes MIGAC (missions d'intérêt général et aide à la "
                                    "contractualisation)"),
    ("charges_eur", "CI_F7", "Total des charges courantes de fonctionnement"),
    ("resultat_eur", "CI_F9", "Résultat consolidé (cliniques : résultat net)"),
    ("encours_dette_eur", "CI_F15", "Encours de la dette"),
]

FIN_MESURES = [  # (clé publiée, colonne ATIH, libellé ATIH)
    ("produits_eur", "realn_prtot", "Total des produits"),
    ("charges_eur", "realtot_chtot", "Total des charges du compte de résultat principal"),
    ("charges_personnel_eur", "realtot_ct1", "Titre 1 - Charges de personnel du compte de résultat principal"),
    ("resultat_principal_eur", "realn_excdef", "Résultat principal"),
    ("encours_dette_eur", "exercn_encoursdette", "Encours de la dette"),
]

NOEUDS_SECU = [  # (identifiant du nœud de secu/arbre/racine.json, ce qu'il finance ici)
    ("robss/maladie/ondam_etablissements", "hospitalier"),
    ("robss/maladie/ondam_fir", "hospitalier"),
    ("robss/autonomie/ondam_pa", "social_medico_social"),
    ("robss/autonomie/ondam_ph", "social_medico_social"),
]


# --- Outils ------------------------------------------------------------------------------------------------------

def nombre(v) -> float | None:
    """Nombre de la source (virgule décimale, espaces) ; vide, « . » ou marque (.z, .v, .m) : None, jamais 0."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not s or s.startswith(".") and not s[1:].isdigit():
        return None
    try:
        return float(s)
    except ValueError:
        return None


def entier(v) -> int | None:
    x = nombre(v)
    return None if x is None else int(round(x))


def departement(cog: str | None) -> str | None:
    """Département d'un code commune Insee (2A, 2B, 971 à 976 ; collectivités d'outre-mer : 975, 977, 978...)."""
    if not cog or len(cog) != 5:
        return None
    return cog[:3] if cog[:2] in ("97", "98") else cog[:2]


DEP_CCAM = {"9A": "971", "9B": "972", "9C": "973", "9D": "974", "9E": "975", "98": "976"}


def departement_ccam(code: str | None) -> str | None:
    """Département d'Open CCAM (codes FINESS d'outre-mer 9A à 9E et 98) ramené au code officiel."""
    c = (code or "").strip().upper()
    if not c:
        return None
    return DEP_CCAM.get(c, c.zfill(2))


def secteur(statut: str | None) -> str | None:
    try:
        n = int(statut)
    except (TypeError, ValueError):
        return None
    for ident, a, b, _lib in SECTEURS:
        if a <= n <= b:
            return ident
    return None


def domaine(agregat: str | None) -> str:
    for ident, chiffre, _lib in DOMAINES:
        if chiffre and agregat and agregat[0] == chiffre:
            return ident
    return "non_classe"


def nom_publiable(nom: str | None) -> str | None:
    """Dénomination d'une personne morale, sans titre de personne (docteur, madame, cabinet...) ; sinon None."""
    if not nom:
        return None
    nom = re.sub(r"\s+", " ", str(nom)).strip()
    if not nom or TITRE_PERSONNE.search(nom):
        return None
    return nom[:120]


def nom_tri(nom: str) -> str:
    s = unicodedata.normalize("NFD", nom or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def mediane(valeurs: list[float]) -> float | None:
    return round(statistics.median(valeurs), 2) if valeurs else None


def _r(x: float | None, n: int = 2):
    if x is None:
        return None
    y = round(x, n)
    return int(y) if n == 0 or y == int(y) and abs(y) >= 1000 else y


def un_fichier(dossier: str, motif: str) -> Path:
    fichiers = sorted((BRUT / dossier).glob(motif))
    if not fichiers:
        raise FileNotFoundError(f"data/lake/sante/{dossier}/{motif} absent : lancer `collecter`")
    return fichiers[-1]


# --- Lecture des sources -----------------------------------------------------------------------------------------

def flux_json(chemin: Path, cle: str):
    """Objets du tableau `cle` d'un grand JSON compressé, lus un par un (le fichier entier demande 3 Go en mémoire)."""
    dec = json.JSONDecoder()
    with gzip.open(chemin, "rt", encoding="utf-8") as f:
        buf = ""
        while True:
            bloc = f.read(1 << 20)
            if not bloc:
                return
            buf += bloc
            i = buf.find(f'"{cle}"')
            j = buf.find("[", i) if i >= 0 else -1
            if j >= 0:
                buf = buf[j + 1:]
                break
            buf = buf[-(len(cle) + 8):]
        while True:
            s = buf.lstrip(" \n\r\t,")
            if s.startswith("]"):
                return
            try:
                obj, k = dec.raw_decode(s)
            except json.JSONDecodeError:
                bloc = f.read(1 << 20)
                if not bloc:
                    return
                buf = s + bloc
                continue
            buf = s[k:]
            yield obj


def date_generation(chemin: Path) -> str:
    with gzip.open(chemin, "rt", encoding="utf-8") as f:
        m = re.search(r'"generatedAt"\s*:\s*"(\d{4}-\d{2}-\d{2})', f.read(400))
    return m.group(1) if m else ""


def lire_nomenclature() -> dict:
    """Libellés des catégories, catégories agrégées et statuts juridiques, lus dans les extractions gelées."""
    cat, agr, statuts, actifs_gel = {}, {}, {}, []
    with un_fichier("sante_finess_et_gel", "*.csv").open(encoding="utf-8", errors="replace", newline="") as f:
        for r in csv.reader(f, delimiter=";"):
            if r and r[0] == "structureet" and len(r) > 21:
                cat[r[18]] = (r[19].strip(), r[20].strip())
                agr[r[20].strip()] = r[21].strip()
                actifs_gel.append((r[18], r[20].strip()))
    with un_fichier("sante_finess_ej_gel", "*.csv").open(encoding="utf-8", errors="replace", newline="") as f:
        for r in csv.reader(f, delimiter=";"):
            if r and r[0] == "structureej" and len(r) > 17:
                statuts[r[16]] = r[17].strip()
    return {"categories": cat, "agregats": agr, "statuts": statuts, "actifs_gel": actifs_gel}


def _commune(adresses: list[dict]) -> tuple[str | None, str | None]:
    """Code commune (et nom d'acheminement) d'une structure : seule information d'adresse lue."""
    for a in sorted(adresses or [], key=lambda x: (x.get("usageAdresse") != "03", x.get("usageAdresse") or "")):
        cog = a.get("cogCommune")
        if cog and len(cog) == 5:
            nom = re.sub(r"\s+CEDEX.*$", "", (a.get("ligneAcheminement") or "").strip(), flags=re.I)
            return cog, nom or None
    return None, None


def lire_finess() -> dict:
    """Personnes morales et entités géographiques d'exercice (actives ou non), sans adresse ni contact."""
    chemin = un_fichier("sante_finess_structures", "*.json.gz")
    pm, ege = {}, {}
    for o in flux_json(chemin, "pmej"):
        g = o.get("informationsGeneralesPMEJ") or {}
        fej = g.get("numFinessPm")
        cog, _ = _commune(o.get("adresse"))
        ej = {"finess": fej, "siren": g.get("siren") if sirene.siren_valide(g.get("siren")) else None,
              "statut": g.get("statutJuridique"), "nom": g.get("denominationLonguePmSmsse") or g.get("denominationPm"),
              "actif": o.get("etatObjet") == "A", "commune": cog}
        if fej:
            pm[fej] = ej
        for e in o.get("ege") or []:
            i = e.get("informationsGeneralesEGE") or {}
            fin = i.get("numFinessEge")
            if not fin:
                continue
            cog, nom_com = _commune(e.get("adresse"))
            ege[fin] = {"finess": fin, "ej": ej, "nom": i.get("nomEgeLong") or i.get("nomEgeCourt"),
                        "categorie": e.get("categorieentiteGeographiqueExercice"),
                        "actif": e.get("etatObjet") == "A" and not i.get("dateFermeture"),
                        "commune": cog, "nom_commune": nom_com}
    return {"pm": pm, "ege": ege, "date": date_generation(chemin), "fichier": chemin.name}


def lire_ccam() -> dict:
    """Par année : {finess géographique: [actes publiés, codes d'actes publiés, département de la source]}."""
    annees = {}
    for p in sorted((BRUT / "sante_open_ccam_etablissements").glob("*.csv")):
        m = re.search(r"(\d{2})\.csv$", p.name)
        if not m:
            continue
        an = 2000 + int(m.group(1))
        par = {}
        with p.open(encoding="utf-8", errors="replace", newline="") as f:
            rd = csv.DictReader(f, delimiter=";")
            for r in rd:
                r = {k.lower(): v for k, v in r.items() if k}
                geo = (r.get("finessgeo") or r.get("finess") or "").strip()
                n = entier(r.get("nb_actes"))
                if not geo or n is None:
                    continue
                x = par.setdefault(geo, [0, 0, (r.get("dep") or "").strip() or None])
                x[0] += n
                x[1] += 1
        annees[an] = par
    return annees


PRIX_COLONNES = [  # (clé publiée, colonne CNSA, nature)
    ("prix_hebergement_chambre_seule_eur", "prixhebpermcs", "prix"),
    ("prix_hebergement_chambre_seule_aide_sociale_eur", "prixhebpermcsa", "prix"),
    ("tarif_dependance_gir_1_2_eur", "tarif_gir_12", "tarif"),
    ("tarif_dependance_gir_3_4_eur", "tarif_gir_34", "tarif"),
    ("tarif_dependance_gir_5_6_eur", "tarif_gir_56", "tarif"),
]


def lire_prix_ehpad() -> dict:
    """Par année : {finess: {clé: valeur déclarée ou None, "maj": date}}. Les colonnes de texte libre ne sont pas lues."""
    annees = {}
    for p in sorted((BRUT / "sante_cnsa_prix_ehpad").glob("*.csv")):
        m = re.search(r"(20\d{2})[-_]brute", p.name)
        if not m:
            continue
        par = {}
        with p.open(encoding="utf-8", errors="replace", newline="") as f:
            rd = csv.reader(f, delimiter=";", quotechar='"')
            entete = [c.strip().lower() for c in next(rd)]
            ix = {c: entete.index(c) for _k, c, _n in PRIX_COLONNES if c in entete}
            i_fin, i_maj = entete.index("finesset"), entete.index("date_maj") if "date_maj" in entete else None
            for r in rd:
                if len(r) <= i_fin or not re.fullmatch(r"[0-9AB]{9}", r[i_fin].strip()):
                    continue
                d = {k: (nombre(r[ix[c]]) if c in ix and len(r) > ix[c] else None) for k, c, _n in PRIX_COLONNES}
                maj = r[i_maj].strip()[:10] if i_maj is not None and len(r) > i_maj else ""
                d["maj"] = maj if re.fullmatch(r"\d{4}-\d{2}-\d{2}", maj) else None
                par[r[i_fin].strip()] = d
        annees[int(m.group(1))] = par
    return annees


def dans_bornes(cle: str, v: float | None) -> bool:
    if v is None:
        return False
    nature = next(n for k, _c, n in PRIX_COLONNES if k == cle)
    return (PRIX_MIN <= v <= PRIX_MAX) if nature == "prix" else (TARIF_MIN <= v <= TARIF_MAX)


def lire_hospi_diag() -> list[dict]:
    import openpyxl
    lignes = []
    for an in HD_ANNEES:
        p = un_fichier("sante_hospi_diag", f"*{an}_*.xlsx")
        wb = openpyxl.load_workbook(p, read_only=True)
        ws = wb[f"hd{an}"]
        it = ws.iter_rows(values_only=True)
        ent = [str(c).strip() if c is not None else "" for c in next(it)]
        ix = {c: i for i, c in enumerate(ent) if c}
        for r in it:
            fin = str(r[ix["finess"]] or "").strip()
            if not re.fullmatch(r"[0-9AB]{9}", fin):
                continue
            ligne = {"finess": fin, "annee": an, "categorie": str(r[ix["cat"]] or "").strip() or None,
                     "champ": str(r[ix["champ_pmsi"]] or "").strip() or None, "referentiel": None}
            for cle, radical, _lib in HD_MESURES:
                d = nombre(r[ix[radical + "_D"]]) if radical + "_D" in ix else None
                o = nombre(r[ix[radical + "_O"]]) if radical + "_O" in ix else None
                v = d if d is not None else o
                if v is not None and ligne["referentiel"] is None:
                    ligne["referentiel"] = "D" if d is not None else "O"
                ligne[cle] = None if v is None else int(round(v))
            lignes.append(ligne)
        wb.close()
    return lignes


def lire_finances() -> list[dict]:
    import duckdb
    p = LAKE / "secu" / "secu_atih_finances_ebnl.parquet"
    if not p.exists():
        raise FileNotFoundError("data/lake/secu/secu_atih_finances_ebnl.parquet absent : lancer `collecter`")
    cols = ", ".join(c for _k, c, _l in FIN_MESURES)
    con = duckdb.connect()
    res = con.execute(f"select annee, secteur, categorie, activite_principale, nb_es, {cols} from '{p}' "
                      "order by annee, secteur, categorie, activite_principale").fetchall()
    con.close()
    return [{"annee": int(r[0]), "secteur": r[1], "categorie": r[2], "activite_principale": r[3],
             "etablissements": int(r[4]) if r[4] is not None else None,
             **{k: (None if r[5 + i] is None else int(round(r[5 + i]))) for i, (k, _c, _l) in enumerate(FIN_MESURES)}}
            for r in res]


# --- Catégories juridiques Sirene ---------------------------------------------------------------------------------

CJ_LOCAL = BRUT / "sirene_categories_juridiques.json"


def categories_juridiques(cache_partage: dict | None = None) -> dict:
    """{SIREN: {"cj", "trouve"}} : copie de l'axe (data/lake/sante/, sans aucun nom) complétée par le cache partagé.

    Le cache partagé (data/lake/_cache/) est réécrit en entier par chaque module qui l'utilise : la copie de l'axe
    garde les catégories déjà vérifiées même si une autre étape écrase le cache entre deux productions."""
    local = json.loads(CJ_LOCAL.read_text(encoding="utf-8")) if CJ_LOCAL.exists() else {}
    partage = sirene.charger_cache() if cache_partage is None else cache_partage
    return {**{s: {"cj": v.get("cj"), "trouve": v.get("trouve")} for s, v in partage.items()}, **local}


def garder_categories(sirens: list[str], cache_partage: dict) -> int:
    """Ajoute à la copie de l'axe les catégories connues pour ces SIREN (jamais de nom, jamais de retrait)."""
    local = json.loads(CJ_LOCAL.read_text(encoding="utf-8")) if CJ_LOCAL.exists() else {}
    for s in sirens:
        v = cache_partage.get(s)
        if v is not None:
            local[s] = {"cj": v.get("cj"), "trouve": v.get("trouve")}
    CJ_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    CJ_LOCAL.write_text(json.dumps(local, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return len(local)


# --- Production --------------------------------------------------------------------------------------------------

def dump(chemin: Path, obj) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def motif_non_nomme(e: dict, cache: dict) -> str | None:
    """None si l'établissement peut être nommé ; sinon le motif pour lequel il est seulement compté."""
    ej = e["ej"]
    if ej["statut"] == STATUT_PERSONNE_PHYSIQUE:
        return "personne_physique"
    if not ej["siren"]:
        return "siren_absent"
    c = cache.get(ej["siren"])
    if c is None:
        return "categorie_juridique_non_verifiee"
    if not sirene.personne_morale(c.get("cj")):
        return "personne_physique" if c.get("trouve") and c.get("cj") else "siren_inconnu_de_sirene"
    if nom_publiable(e["nom"]) is None or nom_publiable(ej["nom"]) is None:
        return "titre_de_personne_dans_la_denomination"
    return None


MOTIFS = {
    "absent_de_finess": "identifiant absent du FINESS en vigueur (Hospi Diag seulement)",
    "personne_physique": "entité juridique personne physique ou groupement de personnes physiques (statut FINESS "
                         "70 ou catégorie juridique Sirene)",
    "siren_absent": "numéro SIREN absent du répertoire FINESS : catégorie juridique non vérifiable",
    "siren_inconnu_de_sirene": "numéro SIREN non retrouvé par l'API Recherche d'entreprises",
    "categorie_juridique_non_verifiee": "catégorie juridique Sirene pas encore interrogée (reprendre `collecter`)",
    "titre_de_personne_dans_la_denomination": "dénomination contenant un titre de personne (docteur, madame, "
                                              "cabinet...)",
}

LIMITES = [
    {"sujet": "Comptes par hôpital (produits, charges, résultat, dette) après 2015",
     "etat": "non publié en données ouvertes par établissement",
     "ce_qui_existe": "Hospi Diag en données ouvertes s'arrête à l'exercice 2015 (jeu non mis à jour depuis le "
                      "18/07/2017), repris dans hospi_diag.json ; l'ATIH publie les comptes 2020 à 2024 agrégés par "
                      "secteur, catégorie et activité, sans établissement, repris dans finances_agregees.json.",
     "fichiers": [f"{REL}/hospi_diag.json", f"{REL}/finances_agregees.json"]},
    {"sujet": "Dotations MIGAC (missions d'intérêt général et aide à la contractualisation) par établissement",
     "etat": "non publié en données ouvertes par établissement après 2015",
     "ce_qui_existe": "les recettes MIGAC par établissement figurent dans Hospi Diag jusqu'en 2015 "
                      "(hospi_diag.json) ; ensuite, le total national est dans l'ONDAM (secu/) et les dotations "
                      "sont notifiées par arrêtés des agences régionales de santé, sans jeu national trouvé.",
     "fichiers": [f"{REL}/hospi_diag.json", "secu/arbre/racine.json"]},
    {"sujet": "Crédits du Ségur de la santé (revalorisations, investissement) par établissement",
     "etat": "non publié en données ouvertes par établissement",
     "ce_qui_existe": "aucun jeu trouvé sur data.gouv.fr le 17/11/2026 ; le total national du soutien à "
                      "l'investissement est compté avec le fonds d'intervention régional dans l'ONDAM (secu/).",
     "fichiers": ["secu/arbre/racine.json"]},
    {"sujet": "Fonds d'intervention régional (FIR) par bénéficiaire",
     "etat": "publié par une seule agence régionale de santé parmi celles recherchées",
     "ce_qui_existe": "l'ARS Pays de la Loire publie ses subventions FIR 2025 : elles sont traitées par "
                      "pipeline/subventions.py et ne sont pas reprises ici.",
     "fichiers": ["subventions/attribuants/subv_ars_pdl_fir.json"]},
    {"sujet": "Forfaits soins des EHPAD (financement par l'assurance maladie) et forfaits dépendance (départements) "
              "par établissement",
     "etat": "non publié en données ouvertes par établissement",
     "ce_qui_existe": "seuls les prix facturés aux résidents sont publiés (CNSA) ; le total national versé aux "
                      "établissements et services pour personnes âgées est dans secu/ (nœud robss/autonomie/ondam_pa).",
     "fichiers": ["secu/arbre/racine.json"]},
    {"sujet": "Montants facturés à l'assurance maladie par établissement (tarifs des séjours, honoraires)",
     "etat": "non publié : Open CCAM donne des nombres d'actes, pas des montants",
     "ce_qui_existe": "nombre d'actes CCAM publiés par établissement et par an (colonnes actes_ccam_*).",
     "fichiers": [f"{REL}/departements.json"]},
    {"sujet": "Activité hors médecine, chirurgie, obstétrique et odontologie (psychiatrie, soins médicaux et de "
              "réadaptation, hospitalisation à domicile) par établissement",
     "etat": "non publié par établissement dans Open CCAM",
     "ce_qui_existe": "l'ATIH publie cette activité par type d'établissement au niveau national (non repris ici).",
     "fichiers": []},
    {"sujet": "Comptes des cliniques privées et des gestionnaires privés d'EHPAD",
     "etat": "hors des jeux de santé ouverts",
     "ce_qui_existe": "les sociétés déposent leurs comptes annuels au greffe (registre national des entreprises) ; "
                      "ce dépôt n'est pas repris ici.",
     "fichiers": []},
]


def produire(sortie: Path = SORTIE) -> dict:
    nomen = lire_nomenclature()
    fin = lire_finess()
    ccam = lire_ccam()
    prix = lire_prix_ehpad()
    cache = categories_juridiques()
    collecte = date_sources("sante")
    an_ccam = sorted(ccam)
    an_prix = sorted(prix)
    dernier_prix = an_prix[-1]
    cat_lib, agr_lib, statut_lib = nomen["categories"], nomen["agregats"], nomen["statuts"]

    def agregat(cat):
        return cat_lib.get(cat, ("", ""))[1] or None

    # --- périmètre : entités géographiques actives -------------------------------------------------------------
    exclus = Counter()
    actifs = []
    for e in fin["ege"].values():
        if not e["actif"]:
            continue
        agr = agregat(e["categorie"])
        if e["ej"]["statut"] == STATUT_PERSONNE_PHYSIQUE:
            exclus["personne_physique"] += 1
        elif agr in AGREGATS_EXCLUS:
            exclus[agr] += 1
        else:
            e["domaine"], e["secteur"], e["dep"] = domaine(agr), secteur(e["ej"]["statut"]), departement(e["commune"])
            actifs.append(e)
    actifs.sort(key=lambda e: e["finess"])
    geos_activite = {g for par in ccam.values() for g in par} | set(prix[dernier_prix])

    def a_lister(e) -> bool:
        return e["domaine"] == "hospitalier" or e["categorie"] == CATEGORIE_EHPAD or e["finess"] in geos_activite

    # --- comptes par commune et par département ---------------------------------------------------------------
    def vide():
        return {"n": 0, "dom": Counter(), "sec": Counter(), "cat": Counter(), "ehpad": 0,
                "prix": defaultdict(lambda: defaultdict(list)), "ehpad_prix": Counter(), "ccam": Counter(),
                "non_nommes": Counter(), "etabs": []}

    communes, deps, nat = defaultdict(vide), defaultdict(vide), vide()
    noms_communes = defaultdict(Counter)
    for e in actifs:
        if e["commune"] and e["nom_commune"]:
            noms_communes[e["commune"]][e["nom_commune"]] += 1
        for niveau in (communes[e["commune"]] if e["commune"] else None, deps[e["dep"]] if e["dep"] else None, nat):
            if niveau is None:
                continue
            niveau["n"] += 1
            niveau["dom"][e["domaine"]] += 1
            niveau["sec"][e["secteur"] or "inconnu"] += 1
            niveau["cat"][e["categorie"] or "inconnue"] += 1
            if e["categorie"] == CATEGORIE_EHPAD:
                niveau["ehpad"] += 1
            for an in an_prix:
                p = prix[an].get(e["finess"])
                if p:
                    niveau["ehpad_prix"][an] += 1
                    for k, _c, _n in PRIX_COLONNES:
                        if dans_bornes(k, p[k]):
                            niveau["prix"][an][k].append(p[k])
        if e["commune"]:
            for an in an_ccam:
                x = ccam[an].get(e["finess"])
                if x:
                    communes[e["commune"]]["ccam"][an] += x[0]
        if a_lister(e):
            motif = motif_non_nomme(e, cache)
            if motif:
                for niveau in (deps[e["dep"]] if e["dep"] else None, nat):
                    if niveau is not None:
                        niveau["non_nommes"][motif] += 1
            elif e["dep"]:
                deps[e["dep"]]["etabs"].append(e)
                nat["etabs"].append(e)

    # activité par département et nationale : colonne `dep` de la source (établissements fermés depuis compris)
    ccam_dep, ccam_nat, ccam_etabs, ccam_hors = defaultdict(Counter), Counter(), {}, {}
    for an in an_ccam:
        ccam_etabs[an] = len(ccam[an])
        ccam_hors[an] = sum(1 for g in ccam[an] if g not in fin["ege"] or not fin["ege"][g]["actif"])
        for g, (n, _codes, dep) in ccam[an].items():
            ccam_nat[an] += n
            if dep:
                ccam_dep[departement_ccam(dep)][an] += n

    def comptes(niv) -> list:
        return ([niv["n"]] + [niv["dom"].get(d, 0) for d in DOMAINE_IDS] + [niv["sec"].get(s, 0) for s in SECTEUR_IDS]
                + [niv["ehpad"]])

    def bloc_prix(niv, an) -> list:
        return [niv["ehpad_prix"].get(an, 0)] + [mediane(niv["prix"][an][k]) for k, _c, _n in PRIX_COLONNES]

    COL_COMPTES = ["etablissements"] + DOMAINE_IDS + SECTEUR_IDS + ["ehpad"]
    COL_PRIX = ["ehpad_avec_prix"] + [k.replace("_eur", "_median_eur") for k, _c, _n in PRIX_COLONNES]
    COL_ETAB = (["finess", "nom", "finess_entite_juridique", "siren", "entite_juridique", "commune", "categorie",
                 "secteur"] + [f"actes_ccam_{a}" for a in an_ccam]
                + [k for k, _c, _n in PRIX_COLONNES] + ["prix_declares_le"])
    millesime = (f"FINESS au {fin['date']} ; Open CCAM {an_ccam[0]}-{an_ccam[-1]} ; prix des EHPAD au 31 décembre "
                 f"{an_prix[0]} à {dernier_prix}")
    source = ("Agence du numérique en santé (FINESS - Structures) ; ATIH (source OpenCCAM, https://www.scansante.fr/) ; "
              "CNSA (prix des EHPAD, données brutes)")
    note_prix = ("Prix en euros par jour, toutes taxes comprises, déclarés par chaque EHPAD : ce sont des sommes "
                 "facturées aux résidents, pas une dépense publique. Le prix d'hébergement est à la charge du "
                 "résident (l'aide sociale à l'hébergement du département peut en prendre une partie en charge, "
                 "sous conditions). Le tarif dépendance GIR 5-6 reste à la charge de tous les résidents ; les "
                 "tarifs GIR 1-2 et 3-4 sont en partie couverts par l'allocation personnalisée d'autonomie.")

    def ligne_etab(e) -> list:
        p = prix[dernier_prix].get(e["finess"]) or {}
        return ([e["finess"], nom_publiable(e["nom"]), e["ej"]["finess"], e["ej"]["siren"],
                 nom_publiable(e["ej"]["nom"]), e["commune"], e["categorie"], e["secteur"]]
                + [(ccam[a].get(e["finess"]) or [None])[0] for a in an_ccam]
                + [_r(p.get(k)) for k, _c, _n in PRIX_COLONNES] + [p.get("maj")])

    # --- fichiers par département ---------------------------------------------------------------------------------
    if (sortie / "departements").exists():
        for vieux in (sortie / "departements").glob("*.json"):
            vieux.unlink()
    par_dep_communes = defaultdict(list)
    for cog in communes:
        par_dep_communes[departement(cog)].append(cog)
    fichiers_dep = {}
    for dep in sorted(deps):
        d = deps[dep]
        lignes_c = []
        for cog in sorted(par_dep_communes.get(dep, [])):
            c = communes[cog]
            nom = sorted(noms_communes[cog].items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if noms_communes[cog] else None
            lignes_c.append([cog, nom] + comptes(c) + bloc_prix(c, dernier_prix)
                            + [c["ccam"].get(an_ccam[-1]) if c["ccam"] else None])
        etabs = sorted(d["etabs"], key=lambda e: (e["commune"] or "", nom_tri(nom_publiable(e["nom"]) or ""), e["finess"]))
        rel = f"{REL}/departements/{dep}.json"
        fichiers_dep[dep] = rel
        dump(sortie / "departements" / f"{dep}.json", {
            "millesime": millesime, "source": source, "departement": dep, "collecte_le": collecte,
            "unite": "nombre d'établissements actifs ; nombre d'actes CCAM publiés ; euros par jour pour les prix",
            "note_perimetre": "Établissements actifs du périmètre (voir index.json). Les établissements sont "
                              "comptés dans leur commune d'implantation ; seuls les hôpitaux, cliniques, autres "
                              "établissements relevant de la loi hospitalière, les EHPAD et les établissements "
                              "ayant une activité ou un prix publié sont listés par leur nom.",
            "note_prix": note_prix,
            "communes": {"colonnes": ["code", "nom"] + COL_COMPTES + COL_PRIX + [f"actes_ccam_{an_ccam[-1]}"],
                         "annee_prix": dernier_prix, "lignes": lignes_c},
            "etablissements": {"colonnes": COL_ETAB, "annee_prix": dernier_prix,
                               "ordre": "commune (code), puis nom sans accents, puis numéro FINESS",
                               "lignes": [ligne_etab(e) for e in etabs]},
            "non_nommes": {"regle": "comptés dans les communes et le département, jamais listés",
                           "total": sum(d["non_nommes"].values()),
                           "par_motif": {m: d["non_nommes"][m] for m in sorted(d["non_nommes"])}},
        })

    # --- départements.json ---------------------------------------------------------------------------------------
    tous_deps = sorted(set(deps) | set(ccam_dep))
    dump(sortie / "departements.json", {
        "millesime": millesime, "source": source, "collecte_le": collecte,
        "unite": "nombre d'établissements actifs ; nombre d'actes CCAM publiés ; euros par jour pour les prix",
        "note_prix": note_prix,
        "note": "Les actes CCAM par département suivent la colonne « dep » d'Open CCAM (établissement où l'acte a été "
                "réalisé, y compris des établissements fermés depuis) ; les lignes de moins de 11 séjours sont "
                "absentes de la source : chaque total est un minimum publié.",
        "colonnes": COL_COMPTES, "annees_ccam": an_ccam, "annees_prix": an_prix, "colonnes_prix": COL_PRIX,
        "departements": {dep: {
            "comptes": comptes(deps[dep]) if dep in deps else None,
            "actes_ccam": [ccam_dep[dep].get(a) if dep in ccam_dep else None for a in an_ccam],
            "prix_ehpad": {str(a): bloc_prix(deps[dep], a) for a in an_prix} if dep in deps else None,
            "etablissements_nommes": len(deps[dep]["etabs"]) if dep in deps else 0,
            "fichier": fichiers_dep.get(dep)} for dep in tous_deps},
    })

    # --- Hospi Diag ----------------------------------------------------------------------------------------------
    hd = lire_hospi_diag()
    lignes_hd, hd_non = [], defaultdict(Counter)
    for li in sorted(hd, key=lambda x: (x["finess"], x["annee"])):
        e = fin["ege"].get(li["finess"])
        ej = e["ej"] if e else fin["pm"].get(li["finess"])
        faux = {"ej": ej, "nom": (e or ej or {}).get("nom")} if ej else None
        motif = motif_non_nomme(faux, cache) if faux else "absent_de_finess"
        if motif:
            hd_non[li["annee"]][motif] += 1
            continue
        cog = (e or ej).get("commune")
        lignes_hd.append([li["finess"], li["annee"], nom_publiable(faux["nom"]), ej["siren"], departement(cog), cog,
                          li["categorie"], li["champ"], li["referentiel"]] + [li[k] for k, _r2, _l in HD_MESURES])
    dump(sortie / "hospi_diag.json", {
        "millesime": f"Exercices {HD_ANNEES[0]} à {HD_ANNEES[-1]} (historique, jeu non mis à jour depuis 2017)",
        "source": "ANAP, Hospi Diag (data.gouv.fr/datasets/hospi-diag), comptes financiers et liasses fiscales",
        "unite": "euros", "collecte_le": collecte, "annees": HD_ANNEES,
        "avertissement": "Historique seulement : ce sont les derniers comptes par établissement publiés en données "
                         "ouvertes. Aucune année après 2015 n'existe dans ce jeu.",
        "definitions": {k: lib for k, _r2, lib in HD_MESURES} | {
            "referentiel": "D = comptes financiers (établissements publics et privés ex-dotation globale) ; "
                           "O = liasses fiscales (cliniques, ex-objectif quantifié national) ; les deux "
                           "référentiels ne s'additionnent pas",
            "categorie": "catégorie Hospi Diag : CHR, CH, CLCC, EBNL, CLI",
            "champ": "DGF, OQN ou APs, tel que publié"},
        "note": "L'identifiant est celui de Hospi Diag : numéro FINESS de l'entité juridique pour les établissements "
                "publics, de l'établissement pour les cliniques. Le nom, le SIREN et la commune viennent du FINESS "
                "en vigueur. Une valeur vide ou marquée non concernée, non validée ou manquante à la source est null.",
        "colonnes": ["finess", "annee", "nom", "siren", "departement", "commune", "categorie", "champ", "referentiel"]
                    + [k for k, _r2, _l in HD_MESURES],
        "ordre": "numéro FINESS, puis année",
        "lignes": lignes_hd,
        "non_nommes": {"regle": "lignes non reprises, comptées par année et par motif : établissement absent du "
                                "FINESS en vigueur (fermeture, fusion, changement de numéro) ou entité juridique "
                                "non vérifiée comme personne morale",
                       "par_annee": {str(a): {m: hd_non[a][m] for m in sorted(hd_non[a])} for a in HD_ANNEES}},
    })

    # --- finances agrégées (ATIH) --------------------------------------------------------------------------------
    finances = lire_finances()
    totaux_fin = {}
    for li in finances:
        t = totaux_fin.setdefault(li["annee"], {"etablissements": 0, **{k: 0 for k, _c, _l in FIN_MESURES}})
        t["etablissements"] += li["etablissements"] or 0
        for k, _c, _l in FIN_MESURES:
            t[k] += li[k] or 0
    an_fin = sorted(totaux_fin)
    dump(sortie / "finances_agregees.json", {
        "millesime": f"Exercices {an_fin[0]} à {an_fin[-1]}",
        "source": "ATIH, indicateurs de suivi financier : données financières des établissements publics ou à but non lucratif "
                  "(data-essentiel.atih.sante.fr/explore/dataset/isf-finance-ebnl-public), ODbL 1.0",
        "unite": "euros", "collecte_le": collecte, "licence": "ODbL 1.0",
        "avertissement": "Agrégats par secteur, catégorie et activité principale : aucun établissement n'est "
                         "identifié. Les cliniques privées à but lucratif ne sont pas dans ce jeu.",
        "definitions": {k: lib for k, _c, lib in FIN_MESURES} | {
            "etablissements": "Nombre d'établissements de la ligne",
            "activite_principale": "Champ d'activité principale (au moins 80 % de l'activité totale, sinon « mixte »)"},
        "colonnes": ["annee", "secteur", "categorie", "activite_principale", "etablissements"]
                    + [k for k, _c, _l in FIN_MESURES],
        "lignes": [[li["annee"], li["secteur"], li["categorie"], li["activite_principale"], li["etablissements"]]
                   + [li[k] for k, _c, _l in FIN_MESURES] for li in finances],
        "totaux": {"methode": "somme des lignes publiées de l'année (calcul du projet)",
                   "par_annee": {str(a): totaux_fin[a] for a in an_fin}},
    })

    # --- limites -------------------------------------------------------------------------------------------------
    lignes_filtrees = {}
    for an in an_prix:
        hors = Counter()
        for p in prix[an].values():
            for k, _c, _n in PRIX_COLONNES:
                if p[k] is not None and not dans_bornes(k, p[k]):
                    hors[k] += 1
        lignes_filtrees[str(an)] = {k: hors.get(k, 0) for k, _c, _n in PRIX_COLONNES}
    dump(sortie / "limites.json", {
        "millesime": "État des publications au 17/11/2026",
        "source": "Recherche du projet sur data.gouv.fr, data-essentiel.atih.sante.fr et GitHub (détail dans "
                  "`recherche_publique`)",
        "collecte_le": collecte,
        "avertissement": "Cette page décrit l'état de la publication des données, pas l'usage de l'argent : une "
                         "donnée non ouverte ne dit rien de la régularité ni de l'utilité d'une dépense.",
        "non_ouvert": LIMITES,
        "limites": [
            "Open CCAM : les lignes de moins de 11 séjours sont absentes de la source ; les totaux d'actes par "
            "établissement, commune et département sont des minimums publiés.",
            "Open CCAM ne couvre que la médecine, la chirurgie, l'obstétrique et l'odontologie.",
            "Prix des EHPAD : données déclarées par les établissements, non retravaillées par la CNSA ; un "
            f"établissement sans déclaration n'a pas de prix (null). Bornes retenues pour les médianes : {PRIX_MIN:g} "
            f"à {PRIX_MAX:g} euros par jour pour l'hébergement, {TARIF_MIN:g} à {TARIF_MAX:g} euros par jour pour la "
            "dépendance ; la valeur déclarée reste publiée telle quelle pour l'établissement.",
            "FINESS ne contient aucune donnée budgétaire ; le flux en vigueur ne porte pas les libellés de "
            "nomenclature, repris de l'extraction gelée de mai 2026.",
            "Hospi Diag : deux référentiels comptables (comptes financiers, liasses fiscales) qui ne s'additionnent "
            "pas ; aucune donnée après 2015.",
            "Licence des prix des EHPAD : non précisée par la CNSA (voir `sources` dans index.json).",
        ],
        "valeurs_hors_bornes_ecartees_des_medianes": lignes_filtrees,
        "hors_perimetre": {
            "regle": "structures d'exercice libéral, commerce de biens à usage médical, laboratoires et entités "
                     "juridiques personnes physiques : ni listées ni comptées",
            "etablissements_actifs_exclus": {
                **{f"categorie_agregee_{a}": {"libelle": AGREGATS_EXCLUS[a], "nombre": exclus.get(a, 0)}
                   for a in sorted(AGREGATS_EXCLUS)},
                "personne_physique": {"libelle": "entité juridique de statut « Personne physique » (code 70)",
                                      "nombre": exclus.get("personne_physique", 0)}}},
        "sources_inaccessibles": [],
        "recherche_publique": RECHERCHE_PUBLIQUE,
    })

    # --- index ---------------------------------------------------------------------------------------------------
    liens = []
    racine = SITE / "secu" / "arbre" / "racine.json"
    if racine.exists():
        arbre = json.loads(racine.read_text(encoding="utf-8"))

        def chercher(n, ident):
            if n.get("id") == ident:
                return n
            for x in n.get("enfants", []):
                r = chercher(x, ident)
                if r:
                    return r
            return None
        for ident, dom in NOEUDS_SECU:
            n = chercher(arbre, ident)
            if n:
                liens.append({"vue": "secu_arbre", "fichier": "secu/arbre/racine.json", "id": ident,
                              "libelle": n.get("nom"), "md": n.get("md"), "millesime": arbre.get("millesime"),
                              "domaine": dom})
    fir = SITE / "subventions" / "attribuants" / "subv_ars_pdl_fir.json"
    if fir.exists():
        liens.append({"vue": "subventions", "fichier": "subventions/attribuants/subv_ars_pdl_fir.json",
                      "libelle": "Subventions de l'ARS Pays de la Loire au titre du fonds d'intervention régional "
                                 "(pipeline/subventions.py)", "domaine": "hospitalier"})

    gel = [(c, a) for c, a in nomen["actifs_gel"] if a not in AGREGATS_EXCLUS]
    cats_actives = Counter(e["categorie"] for e in actifs)
    octets = sorted(((p.stat().st_size, p.name) for p in (sortie / "departements").glob("*.json")), reverse=True)
    index = {
        "millesime": millesime, "source": source, "collecte_le": collecte,
        "unite": "nombre d'établissements actifs ; nombre d'actes CCAM publiés ; euros par jour pour les prix",
        "avertissement": "Aucun montant d'argent public par établissement n'est publié ici après 2015 : ces données "
                         "ne sont pas ouvertes (limites.json). Les prix des EHPAD sont des sommes facturées aux "
                         "résidents.",
        "perimetre": "Entités géographiques actives du répertoire FINESS, hors structures d'exercice libéral, "
                     "pharmacies et autre commerce de biens à usage médical, laboratoires de biologie médicale et "
                     "entités juridiques personnes physiques.",
        "regle_personnes": "Aucune donnée de patient, aucun professionnel nommé. Un établissement n'est listé par "
                           "son nom que si son entité juridique est une personne morale (catégorie juridique Sirene "
                           "2xxx à 9xxx, hors groupements de personnes physiques) et si sa dénomination ne contient "
                           "pas de titre de personne ; sinon il est seulement compté. Les établissements sociaux et "
                           "médico-sociaux autres que les EHPAD sont seulement comptés. Adresse, téléphone, courriel "
                           "et coordonnées géographiques ne sont pas repris.",
        "note_prix": note_prix,
        "domaines": [{"id": i, "libelle": lib,
                      "regle": "premier chiffre de la catégorie agrégée FINESS" if ch else
                               "catégorie absente de la nomenclature gelée"} for i, ch, lib in DOMAINES],
        "secteurs": [{"id": i, "libelle": lib, "statuts_juridiques_finess": f"{a:02d} à {b:02d}",
                      "regle": "regroupement du projet d'après les plages de codes du statut juridique FINESS"}
                     for i, a, b, lib in SECTEURS],
        "categories": [{"code": c, "libelle": cat_lib.get(c, ("", ""))[0] or None, "categorie_agregee": agregat(c),
                        "libelle_categorie_agregee": agr_lib.get(agregat(c)) if agregat(c) else None,
                        "domaine": domaine(agregat(c)), "etablissements": n}
                       for c, n in sorted(cats_actives.items(), key=lambda kv: (kv[0] or ""))],
        "statuts_juridiques": [{"code": c, "libelle": statut_lib.get(c), "secteur": secteur(c), "etablissements": n}
                               for c, n in sorted(Counter(e["ej"]["statut"] for e in actifs).items(),
                                                  key=lambda kv: (kv[0] or ""))],
        "colonnes": COL_COMPTES, "colonnes_prix": COL_PRIX, "annees_ccam": an_ccam, "annees_prix": an_prix,
        "totaux": {
            "comptes": comptes(nat),
            "communes_avec_etablissement": len(communes),
            "departements": len(deps),
            "actes_ccam": {str(a): ccam_nat[a] for a in an_ccam},
            "etablissements_avec_actes_ccam": {str(a): ccam_etabs[a] for a in an_ccam},
            "prix_ehpad": {str(a): bloc_prix(nat, a) for a in an_prix},
            "etablissements_nommes": len(nat["etabs"]),
        },
        "confidentialite": {
            "motifs": MOTIFS,
            "non_nommes": {m: nat["non_nommes"][m] for m in sorted(nat["non_nommes"])},
            "hors_perimetre": {**{a: exclus.get(a, 0) for a in sorted(AGREGATS_EXCLUS)},
                               "personne_physique": exclus.get("personne_physique", 0)},
        },
        "ecarts": [
            {"objet": "établissements actifs du périmètre",
             "source": "finess_structures", "date": fin["date"], "nombre": len(actifs),
             "autre_source": "finess_gel", "autre_date": "2026-05-04", "autre_nombre": len(gel),
             "ecart": len(actifs) - len(gel),
             "lecture_ecart": "deux dates d'extraction et deux générations du répertoire (la nouvelle version de "
                              "FINESS a été déployée le 20/07/2026) ; l'écart est publié tel quel."},
            {"objet": f"établissements avec une activité Open CCAM {an_ccam[-1]}",
             "source": "open_ccam", "date": str(an_ccam[-1]), "nombre": ccam_etabs[an_ccam[-1]],
             "autre_source": "finess_structures", "autre_date": fin["date"],
             "autre_nombre": ccam_etabs[an_ccam[-1]] - ccam_hors[an_ccam[-1]],
             "ecart": ccam_hors[an_ccam[-1]],
             "lecture_ecart": "établissements d'Open CCAM absents ou inactifs dans le FINESS en vigueur (fermetures, "
                              "fusions, changements de numéro) : comptés au département, pas à la commune."},
            {"objet": f"EHPAD avec un prix déclaré au 31 décembre {dernier_prix}",
             "source": "cnsa_prix_ehpad", "date": str(dernier_prix), "nombre": nat["ehpad_prix"].get(dernier_prix, 0),
             "autre_source": "finess_structures", "autre_date": fin["date"], "autre_nombre": nat["ehpad"],
             "ecart": nat["ehpad_prix"].get(dernier_prix, 0) - nat["ehpad"],
             "lecture_ecart": "EHPAD actifs du répertoire sans prix déclaré à la CNSA à cette date, ou déclarés "
                              "sous un autre numéro."},
        ],
        "liens": liens,
        "regle_liens": "un lien renvoie au financeur national (même argent vu du côté de l'assurance maladie) ; "
                       "aucun montant n'est réparti par établissement et rien ne s'additionne.",
        "sources": {k: {**v, "millesime": {
            "finess_structures": fin["date"], "finess_gel": "2026-05-04",
            "open_ccam": f"{an_ccam[0]}-{an_ccam[-1]}", "cnsa_prix_ehpad": f"{an_prix[0]}-{dernier_prix}",
            "hospi_diag": f"{HD_ANNEES[0]}-{HD_ANNEES[-1]}", "atih_finances": f"{an_fin[0]}-{an_fin[-1]}"}[k]}
            for k, v in SOURCES.items()},
        "fichiers": {
            "limites": f"{REL}/limites.json", "departements": f"{REL}/departements.json",
            "departement": f"{REL}/departements/<dep>.json", "hospi_diag": f"{REL}/hospi_diag.json",
            "finances_agregees": f"{REL}/finances_agregees.json",
            "plus_gros_fichier_octets": octets[0][0] if octets else 0,
        },
        "recherche_publique": {"date": RECHERCHE_PUBLIQUE["date"], "verdict": RECHERCHE_PUBLIQUE["verdict"],
                               "fichier": f"{REL}/limites.json"},
    }
    dump(sortie / "index.json", index)
    return index


# --- Collecte ----------------------------------------------------------------------------------------------------

def sirens_a_verifier() -> list[str]:
    """SIREN des entités juridiques dont un établissement peut être listé, dans un ordre fixe."""
    nomen, fin = lire_nomenclature(), lire_finess()
    geos = {g for par in lire_ccam().values() for g in par} | {g for par in lire_prix_ehpad().values() for g in par}
    hd = {li["finess"] for li in lire_hospi_diag()}
    out = set()
    for e in fin["ege"].values():
        agr = nomen["categories"].get(e["categorie"], ("", ""))[1]
        if (e["actif"] and (agr[:1] == "1" or e["categorie"] == CATEGORIE_EHPAD)) or e["finess"] in geos \
                or e["finess"] in hd:
            if e["ej"]["siren"] and agr not in AGREGATS_EXCLUS:
                out.add(e["ej"]["siren"])
    out |= {fin["pm"][f]["siren"] for f in hd if f in fin["pm"] and fin["pm"][f]["siren"]}
    return sorted(out)


def collecter(budget_s: float = 480) -> dict:
    """Collecteur du dépôt pour les sources du catalogue, puis catégories juridiques Sirene (reprise possible)."""
    r = subprocess.run([sys.executable, str(ROOT / "collecte" / "collecte.py"), *COLLECTABLES], cwd=ROOT)
    sirens = sirens_a_verifier()
    garder_categories(sirens, sirene.charger_cache())
    cache, restants = sirene.resoudre([s for s in sirens if s not in categories_juridiques({})], budget_s=budget_s)
    garder_categories(sirens, cache)
    return {"collecte": r.returncode, "sirens_restants": restants}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("commande", nargs="?", choices=["collecter", "produire"])
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    ap.add_argument("--budget", type=float, default=480, help="secondes accordées à la vérification Sirene")
    a = ap.parse_args(argv)
    if a.commande in (None, "collecter"):
        etat = collecter(a.budget)
        print(f"collecte : code {etat['collecte']} ; SIREN restant à vérifier : {etat['sirens_restants']}")
    if a.commande in (None, "produire"):
        idx = produire(a.sortie)
        t = idx["totaux"]
        print(f"{t['comptes'][0]} établissements actifs, {t['communes_avec_etablissement']} communes, "
              f"{t['etablissements_nommes']} nommés, {sum(idx['confidentialite']['non_nommes'].values())} seulement "
              f"comptés ; plus gros fichier : {idx['fichiers']['plus_gros_fichier_octets']} octets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
