"""Marchés publics de tous les acheteurs (État, collectivités, hôpitaux, établissements publics, autres), 2019 à 2025.

Étend pipeline/beneficiaires.py (marchés des seuls services de l'État, 2024) à l'ensemble des données essentielles de
la commande publique (DECP) consolidées, avec des règles de qualité publiées et comptées une à une.

Entrées (entrepôt brut, non versionné) :
  data/lake/_restreint/beneficiaires/benef_decp/*.parquet   DECP consolidées (entrée `benef_decp` du catalogue ; zone
                                                            restreinte : le fichier contient des entrepreneurs individuels)
  data/lake/marches/marches_decp_doublons_sources/*.parquet statistiques des doublons entre sources (même jeu)
  data/lake/_cache/local/sirene_unite_legale.parquet        stock SIRENE des unités légales (partagé avec local.py)
Sorties (site/data/marches/, chaque fichier < 5 Mo, avec `millesime` et `source`) :
  index.json                 règles de qualité et lignes écartées (comptées, montants publiés à part), totaux, repère
                             du recensement OECP, centrales d'achat, doublons entre sources, limites, recherche préalable
  annees.json                par année : marchés, montant, par nature, par type, lignes écartées de l'année
  categories.json            par catégorie d'acheteur et par année
  departements.json          par département de l'acheteur et par année ; liens vers les fichiers par département
  departements/<code>.json   par acheteur (SIREN) du département : montants par année et premiers titulaires nommés
  regions.json               par région de l'acheteur (déduite du département) et par année
  secteurs.json              par division du vocabulaire commun des marchés publics (CPV, deux premiers chiffres)
  titulaires.json            principaux titulaires nommés (personnes morales), sur la période et par année
  acheteurs.json             principaux acheteurs nommés, tous départements réunis

Commandes :
  python pipeline/marches.py collecter   # réseau : collecte/collecte.py (benef_decp, marches_decp_doublons_sources)
  python pipeline/marches.py produire    # sans réseau (stock SIRENE téléchargé une fois par local.py s'il manque)
  python pipeline/marches.py             # les deux

Règles de qualité (chaque ligne écartée est comptée dans le premier motif rencontré, dans cet ordre) :
  1. seules les lignes `donneesActuelles` sont lues (dernière version publiée de chaque marché) ;
  2. une seule ligne par couple (uid, titulaire) ; le montant d'un marché à plusieurs titulaires est réparti à parts
     égales entre eux ;
  3. nature normalisée (casse, tirets) ; concessions et délégations de service public hors champ ;
  4. année = année de la notification initiale ; dates absentes ou impossibles écartées ; hors 2019-2025 à part ;
  5. montant non renseigné : jamais compté 0, ligne à part ;
  6. lignes marquées « aberrant » et « suspect » par le producteur écartées, comptées, total publié à part ;
  7. montant négatif écarté ;
  8. série de montants identiques : au moins SERIE_MIN_MARCHES marchés d'un même acheteur, la même année, déclarés au
     même montant d'au moins SERIE_SEUIL_EUR (montant global vraisemblablement repris sur chaque lot) : écartés,
     comptés, montant déclaré publié à part (`series_repetees`) ;
  9. SIRET du titulaire à 14 chiffres, clé de contrôle valide ; sinon ligne écartée et comptée.
Confidentialité : un titulaire ou un acheteur n'est nommé que si sa catégorie juridique SIRENE est une personne morale
(sirene.personne_morale) et que sa diffusion n'est pas partielle ; son nom vient du stock SIRENE. Les colonnes de nom,
d'objet, de commune et de coordonnées des DECP ne sont jamais lues. Entrepreneurs individuels : agrégés, jamais nommés.
Toute date écrite vient de pipeline/reproductible.py ; les sommes sont faites en entiers (millionièmes d'euro) : deux
productions sur le même entrepôt sont identiques octet pour octet.
"""
from __future__ import annotations

import argparse
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
SORTIE = SITE / "marches"
STOCK_SIRENE = LAKE / "_cache" / "local" / "sirene_unite_legale.parquet"
ID_DECP, ID_DOUBLONS = "benef_decp", "marches_decp_doublons_sources"

ANNEES = list(range(2019, 2026))
ANNEE_PLANCHER = 2000          # avant : date impossible (l'obligation de publication date de 2018)
TOP_TITULAIRES = 10
MAX_OCTETS = 5_000_000
SEUIL_DECOUPE = 4_500_000      # au-delà, un fichier départemental est découpé en parties
SERIE_SEUIL_EUR = 100_000_000  # règle 8 : montant unitaire à partir duquel une série de montants identiques est écartée
SERIE_MIN_MARCHES = 3          # règle 8 : nombre de marchés distincts du même acheteur, même année, même montant
TOP_NATIONAL = 100             # titulaires et acheteurs nommés publiés sur la période
TOP_ANNEE = 20                 # titulaires nommés publiés pour chaque année
TOP_SERIES = 25                # séries écartées détaillées (règle 8)
TOP_GROS = 15                  # plus gros montants unitaires retenus, publiés pour être vérifiables
MICRO = 1_000_000              # sommes en millionièmes d'euro (entiers : résultat indépendant de l'ordre de calcul)

PAGE_JEU = "https://www.data.gouv.fr/datasets/donnees-essentielles-de-la-commande-publique-consolidees-format-tabulaire"
SOURCE = ("data.gouv.fr, « Données essentielles de la commande publique consolidées (format tabulaire) », Colmo "
          f"(jeu 608c055b35eb4e6ee20eb325, Licence Ouverte 2.0, mise à jour quotidienne) : {PAGE_JEU} ; Insee, base "
          "SIRENE des unités légales (catégorie juridique et dénomination)")
UNITE = "euros HT (montant notifié ; pour un accord-cadre, montant maximum estimé)"

# Colonnes lues, et seulement elles (aucune colonne de nom, d'objet, de commune ni de coordonnées).
COLONNES = ("uid", "acheteur_id", "titulaire_id", "nature", "type", "montant", "montant_anomalie", "dateNotification",
            "modification_id", "donneesActuelles", "acheteur_categorie", "acheteur_departement_code",
            "acheteur_departement_nom", "sourceDataset", "codeCPV")

# --- Repère officiel -----------------------------------------------------------------------------------------------
# Saisie manuelle : la page officielle refuse les scripts (HTTP 403, non contourné). Valeur relevée sur une page
# accessible qui cite l'étude de l'OECP ; à ressaisir quand l'OECP publie un nouveau millésime.
REPERE_OECP = {
    "annee": 2024,
    "montant_eur": 233_300_000_000,
    "nombre_marches": 223_383,
    "producteur": "Observatoire économique de la commande publique (OECP), direction des affaires juridiques des "
                  "ministères économiques et financiers",
    "publication": "« Les chiffres des marchés publics 2024 », recensement économique de la commande publique, mars 2026",
    "perimetre": "Marchés recensés par l'OECP pour 2024, d'un montant d'au moins 40 000 € HT (seuil de déclaration "
                 "abaissé de 90 000 à 40 000 € HT), y compris les marchés de défense ou de sécurité.",
    "detail_publie": [
        {"libelle": "Secteur public local", "montant_eur": 100_700_000_000, "nombre_marches": 159_435},
        {"libelle": "État (hors secteur hospitalier)", "montant_eur": 72_400_000_000, "nombre_marches": 30_629},
        {"libelle": "Secteur hospitalier", "montant_eur": 42_600_000_000, "nombre_marches": 19_469},
        {"libelle": "Autres acheteurs (entités de réseau, entreprises publiques, caisses de sécurité sociale, "
                    "associations)", "montant_eur": 17_500_000_000, "nombre_marches": 13_850},
    ],
    "saisie": "manuelle",
    "source_officielle": {"url": "https://www.economie.gouv.fr/daj/oecp-recensement-economique-commande-publique",
                          "acces": "inaccessible aux scripts le 17/11/2026 (HTTP 403), non contourné"},
    "page_consultee": {"titre": "Seban Avocats, « Panorama de la commande publique : les chiffres de 2024 », 16/04/2026 "
                                "(compte rendu de l'étude de l'OECP)",
                       "url": "https://www.seban-associes.avocat.fr/panorama-de-la-commande-publique-les-chiffres-de-2024/",
                       "consultee_le": "2026-11-17"},
    "recoupement": {"titre": "Weka, « Recensement des marchés publics : les résultats 2024 sont connus » (plus de "
                             "233 milliards d'euros, 223 000 marchés)",
                    "url": "https://www.weka.fr/actualite/commande-publique/article/recensement-des-marches-publics-"
                           "les-resultats-2024-sont-connus-212163/"},
}

# Centrales d'achat repérées parmi les acheteurs des DECP (SIREN vérifiés dans le stock SIRENE, qui fournit le nom).
CENTRALES_ACHAT = ("776056467",   # Union des groupements d'achats publics (UGAP)
                   "130005010",   # Réseau des acheteurs hospitaliers (Resah)
                   "924435951",   # Centrale d'achat du numérique et des télécoms
                   "512929514",   # Centrale d'achat public des territoires
                   "800765794")   # Centrale d'achat de l'informatique hospitalière

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "verdict": "Jeu consolidé officiel réutilisé tel quel (aucune collecte ni consolidation refaite) ; règles de "
               "qualité et agrégats propres au site.",
    "trouvailles": [
        {"nom": "DECP consolidées, format tabulaire (Colmo), data.gouv.fr", "url": PAGE_JEU,
         "licence": "Licence Ouverte 2.0", "derniere_mise_a_jour": "2026-11-17", "classement": "réutilisable tel quel",
         "usage": "source unique des marchés ; colonnes `donneesActuelles`, `montant_anomalie`, `acheteur_categorie` "
                  "et fichier `statistiques-doublons-sources` repris"},
        {"nom": "ColinMaudry/decp-processing (code de collecte et de consolidation des DECP)",
         "url": "https://github.com/ColinMaudry/decp-processing", "licence": "GPL-3.0",
         "dernier_commit": "2026-11-14", "classement": "inspiration seulement",
         "usage": "règles lues (catégories d'acheteur, détection des montants « suspect » et « aberrant ») ; code "
                  "non repris : son résultat publié suffit et sa licence diffère de celle du dépôt (MIT)"},
        {"nom": "DECP du ministère de l'Économie (data.economie.gouv.fr, decp-v3-marches-valides)",
         "url": "https://data.economie.gouv.fr/explore/dataset/decp-v3-marches-valides/information/",
         "licence": "Licence Ouverte 2.0", "classement": "inspiration seulement",
         "usage": "moins de sources que le jeu consolidé d'après la fiche de celui-ci : non utilisé"},
        {"nom": "pipeline/beneficiaires.py (marchés des services de l'État, 2024)", "url": "pipeline/beneficiaires.py",
         "licence": "MIT", "classement": "à adapter",
         "usage": "règles reprises (dernière version, répartition entre co-titulaires, personnes morales seules) et "
                  "étendues ; module non modifié"},
    ],
}


# --- Utilitaires ---------------------------------------------------------------------------------------------------


def propre(v) -> str:
    if v is None:
        return ""
    s = unicodedata.normalize("NFC", str(v)).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def eur(micro) -> float:
    """Millionièmes d'euro (entier) -> euros arrondis au centime."""
    return round(int(micro) / MICRO, 2)


def dump(chemin: Path, obj) -> int:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    octets = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(octets) > MAX_OCTETS:
        raise SystemExit(f"{chemin} dépasse 5 Mo : découper")
    chemin.write_bytes(octets)
    return len(octets)


def luhn(chiffres: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(chiffres)):
        n = int(c)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def siren_valide(s) -> bool:
    s = str(s or "")
    return bool(re.fullmatch(r"\d{9}", s)) and s != "000000000" and luhn(s)


def siret_valide(s) -> bool:
    """14 chiffres, SIREN à clé valide, SIRET à clé valide (La Poste, 356000000 : somme des chiffres multiple de 5)."""
    s = str(s or "")
    if not re.fullmatch(r"\d{14}", s) or not siren_valide(s[:9]):
        return False
    if s[:9] == "356000000":
        return luhn(s) or sum(int(c) for c in s) % 5 == 0
    return luhn(s)


NATURES = {"marche": "Marché", "accord cadre": "Accord-cadre", "marche subsequent": "Marché subséquent",
           "marche de partenariat": "Marché de partenariat",
           "marche de defense ou de securite": "Marché de défense ou de sécurité"}
NATURE_NON_RENSEIGNEE = "Non renseignée"
NATURE_HORS_CHAMP = "hors champ"
ORDRE_NATURES = list(NATURES.values()) + [NATURE_NON_RENSEIGNEE]


def nature_normalisee(v) -> str:
    """« MARCHE », « marché », « Accord cadre », « ACCORD-CADRE »... -> libellé unique ; concessions et délégations
    de service public -> hors champ ; vide -> non renseignée ; toute autre valeur arrête la production."""
    t = propre(v)
    if not t:
        return NATURE_NON_RENSEIGNEE
    cle = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    cle = re.sub(r"[\s_-]+", " ", cle).strip()
    if cle in NATURES:
        return NATURES[cle]
    if cle.startswith(("concession", "delegation de service public")):
        return NATURE_HORS_CHAMP
    raise SystemExit(f"nature de marché inconnue dans la source : {t!r} (compléter NATURES)")


TYPES = {"travaux": "Travaux", "services": "Services", "fournitures": "Fournitures"}
TYPE_AUTRE = "Non catégorisé"


def type_normalise(v) -> str:
    return TYPES.get(propre(v).lower(), TYPE_AUTRE)


# Catégories d'acheteur. Celles du producteur (colonne `acheteur_categorie`, tirée de la catégorie juridique SIRENE)
# sont reprises telles quelles ; un acheteur sans catégorie dans la source est classé d'après sa catégorie juridique.
CATEGORIES_SOURCE = {
    "État": "catégorie juridique 71xx (services de l'État)",
    "Commune": "7210, 7312 et Ville de Paris",
    "Groupement de communes": "734x et Métropole de Lyon",
    "Syndicat mixte": "7354, 7355",
    "Département": "7220",
    "Département outre-mer": "7225 et collectivités uniques d'outre-mer",
    "Région": "7230 et Collectivité de Corse",
    "Établissement hospitalier": "7364",
    "EPIC": "4110, 4120, 4140 (établissements publics industriels et commerciaux)",
}
CAT_EPA_NATIONAL = "Établissement public national administratif"
CAT_EPA_LOCAL = "Établissement public local administratif"
CAT_CONSULAIRE = "Organisme consulaire"
CAT_GIP = "Groupement d'intérêt public"
CAT_AUTRE_PUBLIC = "Autre personne morale de droit public"
CAT_REGIE = "Régie locale ou autre établissement industriel et commercial"
CAT_SOCIETE = "Société commerciale ou civile"
CAT_SECU = "Organisme de sécurité sociale, mutuelle ou organisme à régime particulier"
CAT_ASSO = "Association ou fondation"
CAT_INCONNUE = "Non identifié"
CATEGORIES_SIRENE = {
    CAT_EPA_NATIONAL: "7382 à 7389",
    CAT_EPA_LOCAL: "733x, 735x hors syndicats mixtes, 736x hors hôpitaux, 737x (CCAS, SDIS, établissements "
                   "d'enseignement, médico-sociaux, offices de l'habitat...)",
    CAT_CONSULAIRE: "7381",
    CAT_GIP: "7410",
    CAT_AUTRE_PUBLIC: "autres 7xxx",
    CAT_REGIE: "4xxx hors 4110, 4120, 4140",
    CAT_SOCIETE: "3xxx, 5xxx, 6xxx (dont entreprises publiques locales et bailleurs sociaux)",
    CAT_SECU: "8xxx",
    CAT_ASSO: "9xxx",
    CAT_INCONNUE: "identifiant d'acheteur invalide, SIREN absent du stock SIRENE ou catégorie non classée",
}
ORDRE_CATEGORIES = list(CATEGORIES_SOURCE) + list(CATEGORIES_SIRENE)


def categorie_acheteur(cat_source, cj) -> tuple[str, str]:
    """(catégorie, origine) : `decp` si la source la donne, sinon `sirene` (dérivée de la catégorie juridique)."""
    c = propre(cat_source)
    if c:
        if c not in CATEGORIES_SOURCE:
            raise SystemExit(f"catégorie d'acheteur inconnue dans la source : {c!r} (compléter CATEGORIES_SOURCE)")
        return c, "decp"
    cj = str(cj or "")
    if not sirene.CJ_RE.match(cj):
        return CAT_INCONNUE, "sirene"
    if cj == "7381":
        return CAT_CONSULAIRE, "sirene"
    if cj == "7410":
        return CAT_GIP, "sirene"
    if cj.startswith("738"):
        return CAT_EPA_NATIONAL, "sirene"
    if cj.startswith(("733", "735", "736", "737")):
        return CAT_EPA_LOCAL, "sirene"
    if cj.startswith("7"):
        return CAT_AUTRE_PUBLIC, "sirene"
    if cj.startswith("4"):
        return CAT_REGIE, "sirene"
    if cj[0] in "356":
        return CAT_SOCIETE, "sirene"
    if cj.startswith("8"):
        return CAT_SECU, "sirene"
    if cj.startswith("9"):
        return CAT_ASSO, "sirene"
    return CAT_INCONNUE, "sirene"


def statut_siren(siren: str | None, stock: dict) -> tuple[str, str | None, str | None]:
    """('pm', cj, nom) nommable ; ('pp', ...) personne physique ; ('nd', ...) diffusion partielle ou sans nom ;
    ('in', ...) absent du stock SIRENE ou catégorie illisible. Seul 'pm' est nommé."""
    e = stock.get(siren) if siren else None
    if e is None:
        return "in", None, None
    cj, nom, diffusion = e
    if sirene.personne_morale(cj):
        nom = propre(nom)
        if diffusion != "O" or not nom or "[ND]" in nom:
            return "nd", None, None
        return "pm", cj, nom
    if cj.startswith("1") or cj in sirene.CJ_PERSONNES_PHYSIQUES:
        return "pp", None, None
    return "in", None, None


DEP_RE = re.compile(r"^(?:\d{2}|2[AB]|9[78]\d)$")


def departement(code) -> str | None:
    c = propre(code).upper()
    return c if DEP_RE.match(c) else None


# Divisions du vocabulaire commun pour les marchés publics (CPV, règlement (CE) n° 213/2008) : deux premiers chiffres
# du code, libellés officiels en français.
CPV_DIVISIONS = {
    "03": "Produits agricoles, de l'élevage, de la pêche, de la sylviculture et produits connexes",
    "09": "Produits pétroliers, combustibles, électricité et autres sources d'énergie",
    "14": "Produits d'exploitation minière, métaux de base et produits connexes",
    "15": "Produits alimentaires, boissons, tabac et produits connexes",
    "16": "Machines agricoles",
    "18": "Vêtements, articles chaussants, bagages et accessoires",
    "19": "Cuir et textiles, plastiques et caoutchouc",
    "22": "Imprimés et produits connexes",
    "24": "Produits chimiques",
    "30": "Machines de bureau et matériel informatique, équipement et fournitures, excepté les meubles et logiciels",
    "31": "Machines, appareils, équipement et consommables électriques ; éclairage",
    "32": "Équipement de radio, de télévision, de communication, de télécommunication et équipements connexes",
    "33": "Matériels médicaux, pharmaceutiques et produits de soins personnels",
    "34": "Équipements de transport et produits auxiliaires pour le transport",
    "35": "Équipements de sécurité, de lutte contre l'incendie, de police et de défense",
    "37": "Instruments de musique, articles de sport, jeux, jouets, articles pour artisanat, articles pour travaux "
          "artistiques et accessoires",
    "38": "Équipements de laboratoire, d'optique et de précision (excepté les lunettes)",
    "39": "Meubles (y compris les meubles de bureau), aménagements, appareils électroménagers (à l'exclusion de "
          "l'éclairage) et produits de nettoyage",
    "41": "Eau collectée et purifiée",
    "42": "Machines industrielles",
    "43": "Machines pour l'exploitation minière et le travail en carrière, matériel de construction",
    "44": "Structures et matériaux de construction ; produits auxiliaires pour la construction (excepté les "
          "appareils électriques)",
    "45": "Travaux de construction",
    "48": "Logiciels et systèmes d'information",
    "50": "Services de réparation et d'entretien",
    "51": "Services d'installation (à l'exception des logiciels)",
    "55": "Services d'hôtellerie, de restauration et de commerce au détail",
    "60": "Services de transport (à l'exclusion du transport des déchets)",
    "63": "Services de transport complémentaires et auxiliaires ; services des agences de voyages",
    "64": "Services des postes et télécommunications",
    "65": "Services publics (eau, gaz, électricité et autres réseaux)",
    "66": "Services financiers et d'assurance",
    "70": "Services immobiliers",
    "71": "Services d'architecture, services de construction, services d'ingénierie et services d'inspection",
    "72": "Services de technologies de l'information, conseil, développement de logiciels, internet et appui",
    "73": "Services de recherche et développement et services de conseil connexes",
    "75": "Services de l'administration publique, de la défense et de la sécurité sociale",
    "76": "Services relatifs à l'industrie du pétrole et du gaz",
    "77": "Services agricoles, sylvicoles, horticoles, aquacoles et apicoles",
    "79": "Services aux entreprises : droit, marketing, conseil, recrutement, impression et sécurité",
    "80": "Services d'enseignement et de formation",
    "85": "Services de santé et services sociaux",
    "90": "Services d'évacuation des eaux usées, d'élimination des déchets, de nettoyage et services "
          "environnementaux",
    "92": "Services récréatifs, culturels et sportifs",
    "98": "Autres services communautaires, sociaux et personnels",
}
CPV_ILLISIBLE = "00"
LIBELLE_CPV_ILLISIBLE = "Code absent ou illisible dans la source"


def division_cpv(code) -> str:
    """« 45233140-2 », « 45000000 » -> « 45 » ; code absent, de moins de huit chiffres ou division inconnue -> « 00 »."""
    c = re.sub(r"\D", "", propre(code))
    return c[:2] if len(c) >= 8 and c[:2] in CPV_DIVISIONS else CPV_ILLISIBLE


# Régions (code officiel géographique depuis 2016) d'après le département de l'acheteur ; les collectivités
# d'outre-mer (975, 977, 978, 98x) ne sont pas des régions et sont regroupées à part.
REGIONS = {
    "84": ("Auvergne-Rhône-Alpes", "01 03 07 15 26 38 42 43 63 69 73 74"),
    "27": ("Bourgogne-Franche-Comté", "21 25 39 58 70 71 89 90"),
    "53": ("Bretagne", "22 29 35 56"),
    "24": ("Centre-Val de Loire", "18 28 36 37 41 45"),
    "94": ("Corse", "2A 2B"),
    "44": ("Grand Est", "08 10 51 52 54 55 57 67 68 88"),
    "32": ("Hauts-de-France", "02 59 60 62 80"),
    "11": ("Île-de-France", "75 77 78 91 92 93 94 95"),
    "28": ("Normandie", "14 27 50 61 76"),
    "75": ("Nouvelle-Aquitaine", "16 17 19 23 24 33 40 47 64 79 86 87"),
    "76": ("Occitanie", "09 11 12 30 31 32 34 46 48 65 66 81 82"),
    "52": ("Pays de la Loire", "44 49 53 72 85"),
    "93": ("Provence-Alpes-Côte d'Azur", "04 05 06 13 83 84"),
    "01": ("Guadeloupe", "971"),
    "02": ("Martinique", "972"),
    "03": ("Guyane", "973"),
    "04": ("La Réunion", "974"),
    "06": ("Mayotte", "976"),
}
COM = "COM"
NOM_COM = "Collectivités d'outre-mer (hors régions)"
REGION_DU_DEPARTEMENT = {d: r for r, (_, deps) in REGIONS.items() for d in deps.split()}


def region(dep: str | None) -> str | None:
    """Code de région d'un département ; COM pour 975, 977, 978 et 98x ; None si le département est inconnu."""
    if dep is None:
        return None
    if dep in REGION_DU_DEPARTEMENT:
        return REGION_DU_DEPARTEMENT[dep]
    return COM if dep in ("975", "977", "978") or dep.startswith("98") else None


MOTIFS = [  # (identifiant, règle publiée, le montant de la ligne est-il publié ?)
    ("nature_hors_champ", "Concessions et délégations de service public : hors du champ des marchés.", True),
    ("date_absente", "Date de notification absente : année inconnue.", True),
    ("date_impossible", f"Date de notification impossible (avant {ANNEE_PLANCHER} ou postérieure à la collecte).", True),
    ("hors_periode", f"Notification initiale hors de la période {ANNEES[0]}-{ANNEES[-1]}.", True),
    ("montant_non_renseigne", "Montant non renseigné : la ligne n'est pas comptée 0, elle est comptée à part.", False),
    ("montant_aberrant", "Montant marqué « aberrant » par le producteur du jeu (montant déclaré, publié à part).", True),
    ("montant_suspect", "Montant marqué « suspect » par le producteur du jeu (montant déclaré, publié à part).", True),
    ("montant_negatif", "Montant négatif.", True),
    ("montant_serie_repetee", f"Série de montants identiques : au moins {SERIE_MIN_MARCHES} marchés d'un même acheteur, "
                              f"notifiés la même année, déclarés au même montant d'au moins "
                              f"{SERIE_SEUIL_EUR // 1_000_000} millions d'euros HT (montant global vraisemblablement "
                              "repris sur chaque lot) ; montant déclaré publié à part.", True),
    ("siret_titulaire_invalide", "Identifiant du titulaire qui n'est pas un SIRET à 14 chiffres à clé de contrôle "
                                 "valide (identifiants étrangers, numéros de TVA, valeurs tronquées ou vides).", True),
]
MOTIFS_PAR_ANNEE = ("montant_non_renseigne", "montant_aberrant", "montant_suspect", "montant_negatif",
                    "montant_serie_repetee", "siret_titulaire_invalide")
RETENU = "retenu"


def motif_ligne(nature: str, annee, date_impossible: bool, montant, anomalie, siret_ok: bool,
                serie: bool = False) -> str:
    """Premier motif d'écart rencontré, dans l'ordre publié ; `retenu` sinon. (Même règle que la requête SQL.)"""
    if nature == NATURE_HORS_CHAMP:
        return "nature_hors_champ"
    if annee is None:
        return "date_absente"
    if date_impossible:
        return "date_impossible"
    if annee not in ANNEES:
        return "hors_periode"
    if montant is None:
        return "montant_non_renseigne"
    if anomalie == "aberrant":
        return "montant_aberrant"
    if anomalie == "suspect":
        return "montant_suspect"
    if montant < 0:
        return "montant_negatif"
    if serie:
        return "montant_serie_repetee"
    if not siret_ok:
        return "siret_titulaire_invalide"
    return RETENU


# --- Entrepôt ------------------------------------------------------------------------------------------------------


def _manifeste() -> dict:
    try:
        return json.loads((LAKE / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fichier_source(sid: str, dossier: Path) -> tuple[Path, dict]:
    """Fichier parquet d'une source collectée (chemin du manifeste, sinon seul parquet du dossier) et son entrée."""
    e = _manifeste().get(sid) or {}
    for f in e.get("fichiers") or []:
        p = ROOT / f.get("chemin", "")
        if p.suffix == ".parquet" and p.exists():
            return p, {**e, "fichier": f}
    trouves = sorted(dossier.glob("*.parquet")) if dossier.exists() else []
    if not trouves:
        raise SystemExit(f"{dossier.relative_to(ROOT)} absent : lancer `python pipeline/marches.py collecter`")
    return trouves[-1], e


def chemin_stock() -> Path:
    if not STOCK_SIRENE.exists():  # téléchargement unique, reprenable, par le module qui possède ce cache
        import local
        local.sirene_cj({CENTRALES_ACHAT[0]})
    return STOCK_SIRENE


# --- Calcul --------------------------------------------------------------------------------------------------------


def _table(con, nom: str, colonnes: str, lignes: list[tuple]) -> None:
    """Table DuckDB depuis des lignes Python ; `colonnes` : « nom type, ... » (varchar ou boolean)."""
    import pyarrow as pa
    types = {"varchar": pa.string(), "boolean": pa.bool_()}
    champs = [tuple(c.split()) for c in colonnes.split(",")]
    t = pa.table({n: pa.array([li[i] for li in lignes], type=types[ty]) for i, (n, ty) in enumerate(champs)})
    con.register("_t", t)
    con.execute(f"create table {nom} as select * from _t")
    con.unregister("_t")


def preparer(con, decp: Path, stock_path: Path, date_collecte: str) -> dict:
    """Charge les colonnes utiles, applique les règles 1 à 7 et crée la table `l` (une ligne par (uid, titulaire))."""
    presentes = {r[0] for r in con.execute(f"describe select * from read_parquet('{decp}')").fetchall()}
    manquantes = sorted(set(COLONNES) - presentes)
    if manquantes:
        raise SystemExit(f"colonnes absentes des DECP : {manquantes} (schéma de la source modifié)")
    con.execute(f"""create table brut as
        select uid, acheteur_id, titulaire_id, nature, type, montant, montant_anomalie ano, dateNotification dn,
               coalesce(modification_id, 0) mid, coalesce(donneesActuelles, false) da, acheteur_categorie cat,
               acheteur_departement_code dep, acheteur_departement_nom dep_nom, sourceDataset src, codeCPV cpv
        from read_parquet('{decp}')""")
    un = lambda q: con.execute(q).fetchone()[0]  # noqa: E731
    compte = {"lignes_source": un("select count(*) from brut"),
              "versions_anterieures": un("select count(*) from brut where not da"),
              "uid_absent": un("select count(*) from brut where da and uid is null")}
    inconnues = [r[0] for r in con.execute("select distinct ano from brut where ano is not null").fetchall()
                 if r[0] not in ("aberrant", "suspect")]
    if inconnues:
        raise SystemExit(f"valeurs inconnues de montant_anomalie : {inconnues}")
    # Règle 2 : une ligne par (uid, titulaire) ; ordre total, donc choix identique d'une production à l'autre.
    con.execute("""create table k as
        select * exclude (rg) from (
          select *, row_number() over (partition by uid, titulaire_id order by mid desc, montant desc nulls last,
                 dn desc nulls last, src, type, nature, dep, cat, ano, acheteur_id) rg
          from brut where da and uid is not null) where rg = 1""")
    compte["lignes_actuelles"] = un("select count(*) from brut where da")
    compte["lignes_dedoublonnees"] = un("select count(*) from k")
    compte["doublons_uid_titulaire"] = (compte["lignes_actuelles"] - compte["uid_absent"]
                                        - compte["lignes_dedoublonnees"])
    # Règle 4 : date de la notification initiale (plus petite modification publiée du marché).
    con.execute("""create table d0 as
        with m as (select uid, min(mid) mm from brut where dn is not null and uid is not null group by uid)
        select b.uid, min(b.dn) d0 from brut b join m on b.uid = m.uid and b.mid = m.mm
        where b.dn is not null group by b.uid""")
    con.execute("create table co as select uid, count(*) n from k group by uid")
    # Tables de correspondance calculées en Python (mêmes fonctions que les tests unitaires).
    _table(con, "nat", "nature varchar, nn varchar",
           [(r[0], nature_normalisee(r[0])) for r in con.execute("select distinct nature from k").fetchall()])
    _table(con, "typ", "type varchar, tn varchar",
           [(r[0], type_normalise(r[0])) for r in con.execute("select distinct type from k").fetchall()])
    tit = []
    for (t,) in con.execute("select distinct titulaire_id from k where titulaire_id is not null").fetchall():
        ok = siret_valide(t)
        tit.append((t, ok, t[:9] if ok else None))
    _table(con, "tit", "titulaire_id varchar, ok boolean, siren varchar", tit)
    ach = []
    for (a,) in con.execute("select distinct acheteur_id from k where acheteur_id is not null").fetchall():
        s = str(a)
        ach.append((a, s[:9] if re.fullmatch(r"\d{14}", s) and siren_valide(s[:9]) else None))
    _table(con, "ach", "acheteur_id varchar, siren varchar", ach)
    _table(con, "deps", "dep varchar, code varchar",
           [(r[0], departement(r[0])) for r in con.execute("select distinct dep from k").fetchall()])
    _table(con, "cpvs", "cpv varchar, division varchar",
           [(r[0], division_cpv(r[0])) for r in con.execute("select distinct cpv from k").fetchall()])
    annees = ", ".join(str(a) for a in ANNEES)
    con.execute(f"""create table l as
        select k.uid, a.siren ach, dp.code dep, t.siren tit, nat.nn nature, typ.tn type, k.ano, k.src, k.cat,
               year(d0.d0) an, co.n, cp.division cpv,
               case when k.montant is null or isnan(k.montant) or isinf(k.montant) or abs(k.montant) > 1e18 then null
                    else cast(round(k.montant * 100) as hugeint) end centimes,
               case when k.montant is null or isnan(k.montant) or isinf(k.montant) or abs(k.montant) > 1e18 then null
                    else (cast(round(k.montant * 100) as hugeint) * {MICRO // 100}) // co.n end part,
               case when nat.nn = '{NATURE_HORS_CHAMP}' then 'nature_hors_champ'
                    when d0.d0 is null then 'date_absente'
                    when year(d0.d0) < {ANNEE_PLANCHER} or d0.d0 > date '{date_collecte}' then 'date_impossible'
                    when year(d0.d0) not in ({annees}) then 'hors_periode'
                    when k.montant is null or isnan(k.montant) or isinf(k.montant) or abs(k.montant) > 1e18
                         then 'montant_non_renseigne'
                    when k.ano = 'aberrant' then 'montant_aberrant'
                    when k.ano = 'suspect' then 'montant_suspect'
                    when k.montant < 0 then 'montant_negatif'
                    when not coalesce(t.ok, false) then 'siret_titulaire_invalide'
                    else '{RETENU}' end motif
        from k join co using (uid) left join d0 using (uid)
             left join nat on nat.nature is not distinct from k.nature
             left join typ on typ.type is not distinct from k.type
             left join tit t on t.titulaire_id = k.titulaire_id
             left join ach a on a.acheteur_id = k.acheteur_id
             left join deps dp on dp.dep is not distinct from k.dep
             left join cpvs cp on cp.cpv is not distinct from k.cpv""")
    if un("select count(*) from l") != compte["lignes_dedoublonnees"]:
        raise SystemExit("jointure non conservatrice : le nombre de lignes a changé")
    # Règle 8 : séries de montants identiques (même acheteur, même année, même montant, au moins N marchés), parmi
    # les lignes qui passent les règles précédentes ; le motif « SIRET invalide » vient après.
    con.execute(f"""create table serie as
        select ach, an, centimes, count(distinct uid) marches from l
        where motif in ('{RETENU}', 'siret_titulaire_invalide') and ach is not null
              and centimes >= {SERIE_SEUIL_EUR * 100}
        group by 1, 2, 3 having count(distinct uid) >= {SERIE_MIN_MARCHES}""")
    con.execute(f"""update l set motif = 'montant_serie_repetee'
        from serie s where l.ach = s.ach and l.an = s.an and l.centimes = s.centimes
        and l.motif in ('{RETENU}', 'siret_titulaire_invalide')""")
    # Stock SIRENE des seuls SIREN rencontrés (catégorie juridique, dénomination, statut de diffusion).
    con.execute(f"""create table s as
        with q as (select ach siren from l where ach is not null union select tit from l where tit is not null)
        select u.siren, lpad(cast(u.categorieJuridiqueUniteLegale as varchar), 4, '0') cj,
               coalesce(u.denominationUniteLegale, u.denominationUsuelle1UniteLegale) nom,
               u.statutDiffusionUniteLegale diffusion
        from read_parquet('{stock_path}') u join q using (siren)""")
    return compte


def _lignes(con, q: str) -> list[dict]:
    cur = con.execute(q)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _serie(par_annee: dict, cle: str = "m") -> list:
    """Montants alignés sur ANNEES ; null pour une année sans ligne retenue (jamais 0 à la place d'une absence)."""
    return [eur(par_annee[a][cle]) if a in par_annee else None for a in ANNEES]


def produire(sortie: Path | None = None, decp: Path | None = None, stock_path: Path | None = None,
             doublons: Path | None = None) -> dict:
    """Écrit site/data/marches/ (ou `sortie`). Les chemins d'entrée ne sont passés que par les tests."""
    import duckdb
    sortie = sortie or SORTIE
    entree = {}
    if decp is None:
        decp, entree = fichier_source(ID_DECP, LAKE / "_restreint" / "beneficiaires" / ID_DECP)
    if doublons is None:
        try:
            doublons, _ = fichier_source(ID_DOUBLONS, LAKE / "marches" / ID_DOUBLONS)
        except SystemExit:
            doublons = None
    stock_path = stock_path or chemin_stock()
    collecte_le = date_sources("beneficiaires", "marches")
    version = str((entree.get("fichier") or {}).get("signature") or "").split("|")[0][:10] or None

    con = duckdb.connect()
    con.execute("set threads = 4")
    con.execute("set memory_limit = '1500MB'")
    con.execute(f"set temp_directory = '{LAKE / '_cache' / 'duckdb_marches'}'")
    con.execute("set preserve_insertion_order = false")
    compte = preparer(con, Path(decp), Path(stock_path), collecte_le)
    stock = {r[0]: (r[1] or "", r[2], r[3]) for r in con.execute("select siren, cj, nom, diffusion from s").fetchall()}

    # --- Acheteurs : catégorie (source, sinon SIRENE) et nom (SIRENE, personnes morales seulement) ------------------
    cat_source = {}
    for r in _lignes(con, """select ach, cat, count(*) n from l where ach is not null and cat is not null
                             group by 1, 2 order by ach, n desc, cat"""):
        cat_source.setdefault(r["ach"], r["cat"])
    acheteurs = {}
    for (a,) in con.execute(f"select distinct ach from l where ach is not null and motif = '{RETENU}'").fetchall():
        st, cj, nom = statut_siren(a, stock)
        categorie, origine = categorie_acheteur(cat_source.get(a), (stock.get(a) or ("",))[0])
        acheteurs[a] = {"categorie": categorie, "origine": origine, "nomme": st == "pm", "cj": cj, "nom": nom}
    _table(con, "cata", "ach varchar, categorie varchar", [(a, d["categorie"]) for a, d in acheteurs.items()])
    con.execute(f"""create table r as
        select l.*, coalesce(c.categorie, '{CAT_INCONNUE}') categorie from l left join cata c using (ach)
        where motif = '{RETENU}'""")
    titulaires = {}
    for (t,) in con.execute("select distinct tit from r").fetchall():
        titulaires[t] = statut_siren(t, stock)

    # --- Règles de qualité : compteurs globaux et par année -----------------------------------------------------------
    par_motif = {r["motif"]: r for r in _lignes(con, """
        select motif, count(*) lignes, count(distinct uid) marches, coalesce(sum(part), 0) m from l group by 1""")}
    total_dedoublonne = sum(int(v["m"]) for v in par_motif.values())
    retenu = par_motif.get(RETENU, {"lignes": 0, "marches": 0, "m": 0})
    regles = [
        {"id": "versions_anterieures", "regle": "Seules les lignes `donneesActuelles` sont lues (dernière version "
         "publiée de chaque marché) ; versions antérieures non lues.", "lignes": compte["versions_anterieures"],
         "montant_eur": None},
        {"id": "doublons_uid_titulaire", "regle": "Une seule ligne par couple (identifiant de marché `uid`, titulaire) ; "
         "la ligne de la modification la plus récente est gardée.",
         "lignes": compte["doublons_uid_titulaire"] + compte["uid_absent"], "montant_eur": None},
    ]
    for mid, regle, avec_montant in MOTIFS:
        v = par_motif.get(mid, {"lignes": 0, "m": 0})
        regles.append({"id": mid, "regle": regle, "lignes": v["lignes"],
                       "montant_eur": eur(v["m"]) if avec_montant else None})
    anomalies = {r["ano"]: r for r in _lignes(con, """
        select ano, count(*) lignes, count(distinct uid) marches, coalesce(sum(part), 0) m from l
        where ano is not null group by 1""")}
    ecartes_annee = defaultdict(dict)
    for r in _lignes(con, f"""select an, motif, count(*) lignes, coalesce(sum(part), 0) m from l
                              where motif in ({', '.join(repr(m) for m in MOTIFS_PAR_ANNEE)}) group by 1, 2"""):
        ecartes_annee[r["an"]][r["motif"]] = r

    # --- Par année, nature, type ------------------------------------------------------------------------------------
    annee = {r["an"]: r for r in _lignes(con, """
        select an, count(*) lignes, count(distinct uid) marches, count(distinct ach) acheteurs, sum(part) m
        from r group by 1""")}
    nature_annee, type_annee = defaultdict(dict), defaultdict(dict)
    for r in _lignes(con, "select an, nature, count(distinct uid) marches, sum(part) m from r group by 1, 2"):
        nature_annee[r["an"]][r["nature"]] = r
    for r in _lignes(con, "select an, type, count(distinct uid) marches, sum(part) m from r group by 1, 2"):
        type_annee[r["an"]][r["type"]] = r
    # Part nommée et part agrégée, par année (statut du titulaire dans le stock SIRENE).
    statut_annee = defaultdict(lambda: defaultdict(int))
    for r in _lignes(con, "select an, tit, sum(part) m from r group by 1, 2"):
        statut_annee[r["an"]][titulaires[r["tit"]][0]] += int(r["m"])

    def confidentialite(par_statut: dict, total: int) -> dict:
        agrege = sum(v for k, v in par_statut.items() if k != "pm")
        return {"montant_eur": eur(agrege), "part_pct": round(agrege / total * 100, 2) if total else None,
                "dont_personnes_physiques_eur": eur(par_statut.get("pp", 0)),
                "dont_diffusion_partielle_eur": eur(par_statut.get("nd", 0)),
                "dont_siren_introuvable_eur": eur(par_statut.get("in", 0))}

    par_annee = []
    for a in ANNEES:
        v = annee.get(a)
        if v is None:
            par_annee.append({"annee": a, "marches": 0, "lignes": 0, "acheteurs": 0, "total_eur": None})
            continue
        ec = {}
        for mid in MOTIFS_PAR_ANNEE:
            e = ecartes_annee.get(a, {}).get(mid, {"lignes": 0, "m": 0})
            ec[mid] = {"lignes": e["lignes"],
                       "montant_eur": None if mid == "montant_non_renseigne" else eur(e["m"])}
        par_annee.append({
            "annee": a, "marches": v["marches"], "lignes": v["lignes"], "acheteurs": v["acheteurs"],
            "total_eur": eur(v["m"]),
            "nommes_eur": eur(statut_annee[a].get("pm", 0)),
            "agrege_confidentialite": confidentialite(statut_annee[a], int(v["m"])),
            "par_nature": [{"nature": n, "marches": nature_annee[a][n]["marches"],
                            "montant_eur": eur(nature_annee[a][n]["m"])}
                           for n in ORDRE_NATURES if n in nature_annee[a]],
            "par_type": [{"type": t, "marches": type_annee[a][t]["marches"], "montant_eur": eur(type_annee[a][t]["m"])}
                         for t in list(TYPES.values()) + [TYPE_AUTRE] if t in type_annee[a]],
            "ecartes": ec})

    # --- Par catégorie d'acheteur -------------------------------------------------------------------------------------
    cat_tot = {r["categorie"]: r for r in _lignes(con, """
        select categorie, count(distinct uid) marches, count(distinct ach) acheteurs, sum(part) m from r group by 1""")}
    cat_an = defaultdict(dict)
    for r in _lignes(con, "select categorie, an, count(distinct uid) marches, sum(part) m from r group by 1, 2"):
        cat_an[r["categorie"]][r["an"]] = r
    categories = []
    for c in ORDRE_CATEGORIES:
        if c not in cat_tot:
            continue
        categories.append({
            "categorie": c, "origine": "decp" if c in CATEGORIES_SOURCE else "sirene",
            "definition": CATEGORIES_SOURCE.get(c) or CATEGORIES_SIRENE[c],
            "acheteurs": cat_tot[c]["acheteurs"], "marches": cat_tot[c]["marches"], "total_eur": eur(cat_tot[c]["m"]),
            "par_annee": [{"annee": a, "marches": cat_an[c][a]["marches"], "montant_eur": eur(cat_an[c][a]["m"])}
                          for a in ANNEES if a in cat_an[c]]})

    # --- Par département et par acheteur --------------------------------------------------------------------------------
    dep_noms = {r["code"]: propre(r["nom"]) for r in _lignes(con, """
        select d.code, min(b.dep_nom) nom from brut b join deps d on d.dep is not distinct from b.dep
        where d.code is not null and b.dep_nom is not null group by 1""")}
    dep_tot = {r["dep"]: r for r in _lignes(con, """
        select dep, count(distinct uid) marches, count(distinct ach) acheteurs, sum(part) m from r group by 1""")}
    dep_an = defaultdict(dict)
    for r in _lignes(con, "select dep, an, sum(part) m from r group by 1, 2"):
        dep_an[r["dep"]][r["an"]] = r
    dep_cat = defaultdict(list)
    for r in _lignes(con, """select dep, categorie, count(distinct uid) marches, sum(part) m from r
                             group by 1, 2 order by dep, m desc, categorie"""):
        dep_cat[r["dep"]].append({"categorie": r["categorie"], "marches": r["marches"], "montant_eur": eur(r["m"])})
    ach_tot = defaultdict(dict)
    for r in _lignes(con, "select dep, ach, count(distinct uid) marches, sum(part) m from r group by 1, 2"):
        ach_tot[r["dep"]][r["ach"]] = r
    ach_an = defaultdict(lambda: defaultdict(dict))
    for r in _lignes(con, "select dep, ach, an, sum(part) m from r group by 1, 2, 3"):
        ach_an[r["dep"]][r["ach"]][r["an"]] = r
    ach_tit = defaultdict(lambda: defaultdict(list))
    for r in _lignes(con, """select dep, ach, tit, count(distinct uid) marches, count(*) lignes, sum(part) m from r
                             group by 1, 2, 3 order by dep, ach, m desc, tit"""):
        ach_tit[r["dep"]][r["ach"]].append(r)

    entete = {"millesime": f"Marchés notifiés de {ANNEES[0]} à {ANNEES[-1]} (DECP consolidées"
                           + (f", version du {version}" if version else "") + ")",
              "source": SOURCE, "unite": UNITE, "collecte_le": collecte_le}
    ordre_acheteurs = ("Acheteurs par montant total décroissant, puis SIREN ; titulaires par montant décroissant, puis "
                       "SIREN. L'ordre ne porte aucune appréciation.")
    for f in (sortie / "departements").glob("*.json") if (sortie / "departements").exists() else []:
        f.unlink()
    departements, non_localise = [], None
    glob_statut = defaultdict(int)
    nommes_sirens = set()
    for dep in sorted(dep_tot, key=lambda d: (d is None, d or "")):
        fiches, non_nommes = [], {"nombre": 0, "marches": 0, "montant_eur": 0}
        nn_micro = 0
        for a, v in sorted(ach_tot[dep].items(), key=lambda kv: (-int(kv[1]["m"]), kv[0] or "")):
            info = acheteurs.get(a)
            par_statut = defaultdict(int)
            top, autres_n, autres_m, agrege_lignes = [], 0, 0, 0
            for t in ach_tit[dep][a]:
                st, cj, nom = titulaires[t["tit"]]
                par_statut[st] += int(t["m"])
                glob_statut[st] += int(t["m"])
                if st != "pm":
                    agrege_lignes += t["lignes"]
                elif len(top) < TOP_TITULAIRES:
                    nommes_sirens.add(t["tit"])
                    top.append({"siren": t["tit"], "denomination": nom, "categorie_juridique": cj,
                                "marches": t["marches"], "montant_eur": eur(t["m"])})
                else:
                    autres_n += 1
                    autres_m += int(t["m"])
            if info is None or not info["nomme"]:
                non_nommes["nombre"] += 1
                non_nommes["marches"] += v["marches"]
                nn_micro += int(v["m"])
                continue
            agrege = sum(m for k, m in par_statut.items() if k != "pm")
            fiches.append({
                "siren": a, "denomination": info["nom"], "categorie_juridique": info["cj"],
                "categorie": info["categorie"], "marches": v["marches"], "total_eur": eur(v["m"]),
                "montants_eur": _serie(ach_an[dep][a]),
                "titulaires": top,
                "autres_titulaires": {"nombre": autres_n, "montant_eur": eur(autres_m)},
                "agrege_confidentialite": {"montant_eur": eur(agrege), "lignes": agrege_lignes}})
        non_nommes["montant_eur"] = eur(nn_micro)
        tot = dep_tot[dep]
        resume = {"marches": tot["marches"], "acheteurs": tot["acheteurs"], "total_eur": eur(tot["m"]),
                  "montants_eur": _serie(dep_an[dep])}
        if dep is None:
            non_localise = {**resume, "par_categorie": dep_cat[dep],
                            "note": "Département de l'acheteur absent ou illisible dans la source : montants comptés "
                                    "dans les totaux, sans fichier départemental."}
            continue
        base = {**entete, "departement": dep, "nom": dep_noms.get(dep), "annees": ANNEES, **resume,
                "par_categorie": dep_cat[dep], "acheteurs_non_nommes": non_nommes, "ordre": ordre_acheteurs}
        # Découpage : un fichier, ou plusieurs parties si la taille approche de la limite.
        parties, courant, taille = [], [], 0
        for f in fiches:
            t = len(json.dumps(f, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
            if courant and taille + t > SEUIL_DECOUPE:
                parties.append(courant)
                courant, taille = [], 0
            courant.append(f)
            taille += t
        parties.append(courant)
        noms = [f"marches/departements/{dep}.json"] if len(parties) == 1 else [
            f"marches/departements/{dep}_{i}.json" for i in range(1, len(parties) + 1)]
        for i, (nom, bloc) in enumerate(zip(noms, parties), 1):
            doc = {**base, "acheteurs_total": tot["acheteurs"], "acheteurs": bloc}
            if len(parties) > 1:
                doc.update({"partie": i, "parties": len(parties)})
            dump(sortie / "departements" / Path(nom).name, doc)
        departements.append({"departement": dep, "nom": dep_noms.get(dep), **resume, "fichiers": noms})

    # --- Centrales d'achat ----------------------------------------------------------------------------------------------
    liste_c = ", ".join(repr(c) for c in CENTRALES_ACHAT)
    c_ach, c_tit = defaultdict(dict), defaultdict(dict)
    for r in _lignes(con, f"""select ach, an, count(distinct uid) marches, sum(part) m from r
                              where ach in ({liste_c}) group by 1, 2"""):
        c_ach[r["ach"]][r["an"]] = r
    for r in _lignes(con, f"""select tit, an, count(distinct uid) marches, sum(part) m from r
                              where tit in ({liste_c}) group by 1, 2"""):
        c_tit[r["tit"]][r["an"]] = r

    def cote(par_an: dict) -> dict:
        return {"marches": sum(v["marches"] for v in par_an.values()),
                "montant_eur": eur(sum(int(v["m"]) for v in par_an.values())),
                "montants_eur": _serie(par_an)}

    centrales = []
    for c in CENTRALES_ACHAT:
        st, cj, nom = statut_siren(c, stock)
        if st != "pm" or (c not in c_ach and c not in c_tit):
            continue
        centrales.append({"siren": c, "denomination": nom, "categorie_juridique": cj,
                          "categorie": acheteurs.get(c, {}).get("categorie"),
                          "comme_acheteur": cote(c_ach.get(c, {})), "comme_titulaire": cote(c_tit.get(c, {}))})

    # --- Doublons entre sources (fichier du producteur) ---------------------------------------------------------------
    src_lignes = {r["src"]: r["lignes"] for r in _lignes(con, "select src, count(*) lignes from r group by 1")}
    uniques = {}
    if doublons is not None:
        for s, u in con.execute(f"select sourceDataset, \"unique\" from read_parquet('{doublons}')").fetchall():
            uniques[s] = u
    doublons_sources = [{"source": s or "non renseignée", "lignes_retenues": n,
                         "part_unique_pct": round(uniques[s] * 100, 2) if uniques.get(s) is not None else None}
                        for s, n in sorted(src_lignes.items(), key=lambda kv: (-kv[1], kv[0] or ""))]

    # --- Recoupement avec les marchés de l'État déjà publiés (pipeline/beneficiaires.py) ---------------------------------
    recoupements = []
    etat = SITE / "beneficiaires" / "marches_etat.json"
    if etat.exists() and "État" in cat_an and 2024 in cat_an["État"]:
        e = json.loads(etat.read_text(encoding="utf-8")).get("ensemble") or {}
        recoupements.append({
            "fichier": "beneficiaires/marches_etat.json", "annee": 2024,
            "montant_autre_fichier_eur": e.get("total_eur"), "marches_autre_fichier": e.get("nombre_marches"),
            "montant_ici_eur": eur(cat_an["État"][2024]["m"]), "marches_ici": cat_an["État"][2024]["marches"],
            "lecture_ecart": ("Même source, règles différentes : `beneficiaires/marches_etat.json` date un marché par sa "
                              "dernière modification, garde les lignes « suspect » et les titulaires sans SIRET "
                              "(agrégés) et retient les acheteurs de catégorie juridique 71xx d'après l'API Recherche "
                              "d'entreprises ; ce fichier date un marché par sa notification initiale et écarte les "
                              "lignes « suspect » et les identifiants de titulaire invalides. Les deux montants sont "
                              "publiés, aucun n'est corrigé par l'autre.")})

    # --- Règle 8 : séries de montants identiques écartées --------------------------------------------------------------
    serie_an = {r["an"]: r for r in _lignes(con, """
        select an, count(*) series, sum(marches) marches from serie group by 1""")}
    serie_lignes = {r["an"]: r for r in _lignes(con, """
        select an, count(*) lignes, sum(part) m from l where motif = 'montant_serie_repetee' group by 1""")}
    principales = []
    for r in _lignes(con, f"""
            select s.ach, s.an, s.centimes, s.marches, sum(l.part) m from serie s
            join l on l.ach = s.ach and l.an = s.an and l.centimes = s.centimes and l.motif = 'montant_serie_repetee'
            group by 1, 2, 3, 4 order by m desc, s.ach, s.an, s.centimes limit {TOP_SERIES}"""):
        st, cj, nom = statut_siren(r["ach"], stock)
        info = acheteurs.get(r["ach"]) or {}
        principales.append({
            "annee": r["an"], "siren": r["ach"] if st == "pm" else None, "denomination": nom if st == "pm" else None,
            "categorie": info.get("categorie") or categorie_acheteur(cat_source.get(r["ach"]),
                                                                     (stock.get(r["ach"]) or ("",))[0])[0],
            "marches": r["marches"], "montant_unitaire_eur": round(int(r["centimes"]) / 100, 2),
            "montant_declare_eur": eur(r["m"])})
    series_repetees = {
        "regle": MOTIFS[[m[0] for m in MOTIFS].index("montant_serie_repetee")][1],
        "seuil_eur": SERIE_SEUIL_EUR, "marches_minimum": SERIE_MIN_MARCHES,
        "pourquoi": ("Quand un acheteur découpe un achat en lots, le montant global est parfois saisi sur chaque lot : "
                     "il est alors compté autant de fois qu'il y a de lots. Ces lignes ne sont pas marquées par le "
                     "producteur du jeu. Elles sont écartées des totaux, comptées, et leur montant déclaré est publié "
                     "ici, sans correction : la règle repère une forme de saisie, elle ne prouve pas une erreur."),
        "par_annee": [{"annee": a, "series": serie_an.get(a, {}).get("series", 0),
                       "marches": int(serie_an.get(a, {}).get("marches") or 0),
                       "lignes": serie_lignes.get(a, {}).get("lignes", 0),
                       "montant_declare_eur": eur(serie_lignes.get(a, {}).get("m") or 0)} for a in ANNEES],
        "principales": principales,
        "ordre": "Séries par montant déclaré décroissant, puis SIREN ; l'ordre ne porte aucune appréciation.",
    }

    # Plus gros montants unitaires conservés dans les totaux : publiés pour qu'un montant isolé douteux reste visible.
    gros = []
    for r in _lignes(con, f"""select uid, min(ach) ach, min(an) an, min(type) type, min(cpv) cpv, min(nature) nature,
                                     sum(part) m from r group by uid order by m desc, uid limit {TOP_GROS}"""):
        st, cj, nom = statut_siren(r["ach"], stock)
        gros.append({"annee": r["an"], "acheteur_siren": r["ach"] if st == "pm" else None,
                     "acheteur": nom if st == "pm" else None,
                     "categorie": (acheteurs.get(r["ach"]) or {}).get("categorie", CAT_INCONNUE),
                     "nature": r["nature"], "type": r["type"], "division_cpv": r["cpv"], "montant_eur": eur(r["m"])})
    plus_gros = {"note": ("Les plus gros montants unitaires retenus dans les totaux. Ils ne sont marqués ni par le "
                          "producteur du jeu ni par la règle des séries : ils sont comptés, sans vérification une à "
                          "une. Un montant d'accord-cadre est un maximum sur plusieurs années, pas une dépense."),
                 "marches": gros,
                 "ordre": "Marchés par montant décroissant, puis identifiant ; l'ordre ne porte aucune appréciation."}

    # --- Par région de l'acheteur (déduite du département) ------------------------------------------------------------
    _table(con, "regs", "dep varchar, reg varchar", [(d, region(d)) for (d,) in con.execute(
        "select distinct dep from r where dep is not null").fetchall()])
    con.execute("create table rr as select r.*, g.reg from r left join regs g using (dep)")
    reg_tot = {r["reg"]: r for r in _lignes(con, """
        select reg, count(distinct uid) marches, count(distinct ach) acheteurs, count(distinct dep) departements,
               sum(part) m from rr group by 1""")}
    reg_an = defaultdict(dict)
    for r in _lignes(con, "select reg, an, sum(part) m from rr group by 1, 2"):
        reg_an[r["reg"]][r["an"]] = r
    reg_type = defaultdict(list)
    for r in _lignes(con, """select reg, type, count(distinct uid) marches, sum(part) m from rr group by 1, 2"""):
        reg_type[r["reg"]].append(r)
    reg_deps = defaultdict(list)
    for (g, d) in con.execute("select distinct reg, dep from rr where dep is not null order by 1, 2").fetchall():
        reg_deps[g].append(d)
    ordre_types = list(TYPES.values()) + [TYPE_AUTRE]

    def fiche_region(g):
        v = reg_tot[g]
        return {"marches": v["marches"], "acheteurs": v["acheteurs"], "total_eur": eur(v["m"]),
                "montants_eur": _serie(reg_an[g]),
                "par_type": [{"type": t["type"], "marches": t["marches"], "montant_eur": eur(t["m"])}
                             for t in sorted(reg_type[g], key=lambda t: ordre_types.index(t["type"]))]}
    regions = [{"region": g, "nom": REGIONS[g][0] if g in REGIONS else NOM_COM, "departements": reg_deps[g],
                **fiche_region(g)} for g in sorted((g for g in reg_tot if g is not None),
                                                   key=lambda g: (g == COM, g))]
    reg_non_localise = fiche_region(None) if None in reg_tot else None

    # --- Par secteur (division CPV) -----------------------------------------------------------------------------------
    sec_tot = {r["cpv"]: r for r in _lignes(con, """
        select cpv, count(distinct uid) marches, count(distinct ach) acheteurs, sum(part) m from r group by 1""")}
    sec_an = defaultdict(dict)
    for r in _lignes(con, "select cpv, an, count(distinct uid) marches, sum(part) m from r group by 1, 2"):
        sec_an[r["cpv"]][r["an"]] = r
    sec_type = defaultdict(list)
    for r in _lignes(con, "select cpv, type, sum(part) m from r group by 1, 2"):
        sec_type[r["cpv"]].append(r)
    secteurs = []
    for c in list(CPV_DIVISIONS) + [CPV_ILLISIBLE]:
        if c not in sec_tot:
            continue
        v = sec_tot[c]
        secteurs.append({
            "division": c, "libelle": CPV_DIVISIONS.get(c, LIBELLE_CPV_ILLISIBLE),
            "marches": v["marches"], "acheteurs": v["acheteurs"], "total_eur": eur(v["m"]),
            "montants_eur": _serie(sec_an[c]),
            "marches_par_annee": [sec_an[c][a]["marches"] if a in sec_an[c] else 0 for a in ANNEES],
            "par_type": [{"type": t["type"], "montant_eur": eur(t["m"])}
                         for t in sorted(sec_type[c], key=lambda t: ordre_types.index(t["type"]))]})

    # --- Principaux titulaires nommés (personnes morales), sur la période et par année ----------------------------------
    tit_tot = _lignes(con, """select tit, count(distinct uid) marches, count(distinct ach) acheteurs, sum(part) m
                              from r group by 1 order by m desc, tit""")
    tit_an = defaultdict(dict)
    for r in _lignes(con, "select tit, an, count(distinct uid) marches, sum(part) m from r group by 1, 2"):
        tit_an[r["tit"]][r["an"]] = r
    top_tit, autres_pm = [], {"nombre": 0, "m": 0}
    for t in tit_tot:
        st, cj, nom = titulaires[t["tit"]]
        if st != "pm":
            continue
        if len(top_tit) < TOP_NATIONAL:
            top_tit.append({"siren": t["tit"], "denomination": nom, "categorie_juridique": cj,
                            "marches": t["marches"], "acheteurs": t["acheteurs"], "total_eur": eur(t["m"]),
                            "montants_eur": _serie(tit_an[t["tit"]])})
        else:
            autres_pm["nombre"] += 1
            autres_pm["m"] += int(t["m"])
    tit_par_annee = []
    for a in ANNEES:
        lst = sorted(((int(v[a]["m"]), s_) for s_, v in tit_an.items() if a in v and titulaires[s_][0] == "pm"),
                     key=lambda x: (-x[0], x[1]))
        tit_par_annee.append({"annee": a, "titulaires": [
            {"siren": s_, "denomination": titulaires[s_][2], "categorie_juridique": titulaires[s_][1],
             "marches": tit_an[s_][a]["marches"], "montant_eur": eur(m)} for m, s_ in lst[:TOP_ANNEE]],
            "autres_personnes_morales": {"nombre": max(0, len(lst) - TOP_ANNEE),
                                         "montant_eur": eur(sum(m for m, _ in lst[TOP_ANNEE:]))},
            "agrege_confidentialite": confidentialite(statut_annee[a], int(annee[a]["m"])) if a in annee else None})

    # --- Principaux acheteurs nommés, tous départements réunis -----------------------------------------------------------
    ach_nat = _lignes(con, """select ach, count(distinct uid) marches, count(distinct dep) departements, sum(part) m
                              from r where ach is not null group by 1 order by m desc, ach""")
    ach_nat_an = defaultdict(dict)
    for r in _lignes(con, "select ach, an, sum(part) m from r where ach is not null group by 1, 2"):
        ach_nat_an[r["ach"]][r["an"]] = r
    top_ach, ach_autres = [], {"nombre": 0, "m": 0}
    ach_non_nommes = {"nombre": 0, "marches": 0, "m": 0}
    for v in ach_nat:
        info = acheteurs.get(v["ach"])
        if info is None or not info["nomme"]:
            ach_non_nommes["nombre"] += 1
            ach_non_nommes["marches"] += v["marches"]
            ach_non_nommes["m"] += int(v["m"])
        elif len(top_ach) < TOP_NATIONAL:
            top_ach.append({"siren": v["ach"], "denomination": info["nom"], "categorie_juridique": info["cj"],
                            "categorie": info["categorie"], "marches": v["marches"],
                            "departements": v["departements"], "total_eur": eur(v["m"]),
                            "montants_eur": _serie(ach_nat_an[v["ach"]]),
                            "centrale_achat": v["ach"] in CENTRALES_ACHAT})
        else:
            ach_autres["nombre"] += 1
            ach_autres["m"] += int(v["m"])
    sans_ach = con.execute("select count(distinct uid), coalesce(sum(part), 0) from r where ach is null").fetchone()

    total = int(retenu["m"])
    acheteurs_retenus = con.execute("select count(distinct ach) from r").fetchone()[0]
    index = {
        **entete,
        "version_source": version,
        "annees": ANNEES,
        "sources": [
            {"id": ID_DECP, "titre": "Données essentielles de la commande publique consolidées (format tabulaire), "
                                     "fichier decp.parquet", "producteur": "Colmo (Colin Maudry)", "page": PAGE_JEU,
             "licence": "Licence Ouverte 2.0", "frequence": "quotidienne",
             "usage": "toutes les lignes de marchés ; arrêté du 22 décembre 2022 relatif aux données essentielles"},
            {"id": ID_DOUBLONS, "titre": "Même jeu, fichier statistiques-doublons-sources.parquet",
             "producteur": "Colmo (Colin Maudry)", "page": PAGE_JEU, "licence": "Licence Ouverte 2.0",
             "frequence": "quotidienne", "usage": "part des marchés de chaque source absents des autres sources"},
            {"id": "sirene_unites_legales", "titre": "Base SIRENE des unités légales (stock)", "producteur": "Insee",
             "page": "https://www.data.gouv.fr/datasets/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret",
             "licence": "Licence Ouverte 2.0", "frequence": "mensuelle",
             "usage": "catégorie juridique, dénomination et statut de diffusion des acheteurs et des titulaires"},
        ],
        "perimetre": ("Marchés publics et accords-cadres publiés au titre des données essentielles de la commande "
                      "publique, tous acheteurs (État, collectivités, hôpitaux, établissements publics, autres), "
                      f"notifiés de {ANNEES[0]} à {ANNEES[-1]}. Les concessions sont hors champ. Un marché non publié "
                      "par son acheteur est absent."),
        "methode": [
            "Montant : montant notifié hors taxes ; pour un accord-cadre, montant maximum estimé. Ce n'est pas le "
            "montant payé.",
            "Dernière version publiée de chaque marché (`donneesActuelles`), une ligne par couple (marché, titulaire).",
            "Marché à plusieurs titulaires : montant réparti à parts égales entre eux.",
            "Année : année de la notification initiale du marché, pas celle d'une modification.",
            "Lignes marquées « aberrant » ou « suspect » par le producteur du jeu : écartées, comptées, total publié "
            "à part (`regles_qualite`, `anomalies_source`, `annees.json`).",
            f"Séries de montants identiques (au moins {SERIE_MIN_MARCHES} marchés d'un même acheteur, la même année, "
            f"au même montant d'au moins {SERIE_SEUIL_EUR // 1_000_000} millions d'euros) : écartées, comptées, "
            "montant déclaré publié à part (`series_repetees`).",
            "Titulaire : SIRET à 14 chiffres à clé de contrôle valide ; sinon la ligne est écartée et comptée.",
            "Catégorie d'acheteur : celle du jeu (`origine` = decp) ; à défaut, dérivée de la catégorie juridique "
            "SIRENE (`origine` = sirene).",
            "Département : celui de l'établissement acheteur (SIRET), pas le lieu d'exécution ni celui du titulaire.",
            "Région : déduite du département de l'acheteur (régions en vigueur depuis 2016).",
            "Secteur : division du vocabulaire commun pour les marchés publics (CPV), deux premiers chiffres du code "
            "publié par l'acheteur.",
            "Chaque ligne écartée est comptée dans le premier motif rencontré, dans l'ordre de `regles_qualite`.",
        ],
        "regles_qualite": regles,
        "anomalies_source": {
            "note": "Toutes les lignes actuelles dédoublonnées marquées par le producteur, quelle que soit leur date : "
                    "montants déclarés, jamais ajoutés aux totaux.",
            "aberrant": {"lignes": anomalies.get("aberrant", {}).get("lignes", 0),
                         "marches": anomalies.get("aberrant", {}).get("marches", 0),
                         "montant_declare_eur": eur(anomalies.get("aberrant", {}).get("m", 0))},
            "suspect": {"lignes": anomalies.get("suspect", {}).get("lignes", 0),
                        "marches": anomalies.get("suspect", {}).get("marches", 0),
                        "montant_declare_eur": eur(anomalies.get("suspect", {}).get("m", 0))}},
        "totaux": {
            "lignes_source": compte["lignes_source"], "lignes_actuelles": compte["lignes_actuelles"],
            "lignes_dedoublonnees": compte["lignes_dedoublonnees"],
            "montant_dedoublonne_eur": eur(total_dedoublonne),
            "lignes_retenues": retenu["lignes"], "marches_retenus": retenu["marches"], "total_retenu_eur": eur(total),
            "acheteurs": acheteurs_retenus, "acheteurs_nommes": sum(1 for d in acheteurs.values() if d["nomme"]),
            "titulaires": len(titulaires), "titulaires_nommes": len(nommes_sirens),
            "titulaires_personnes_morales": sum(1 for v in titulaires.values() if v[0] == "pm"),
            "nommes_eur": eur(glob_statut.get("pm", 0)),
            "agrege_confidentialite": confidentialite(glob_statut, total)},
        "par_annee": [{"annee": p["annee"], "marches": p["marches"], "total_eur": p["total_eur"]} for p in par_annee],
        "repere_oecp": {
            **REPERE_OECP,
            "montant_ici_eur": next((p["total_eur"] for p in par_annee if p["annee"] == REPERE_OECP["annee"]), None),
            "marches_ici": next((p["marches"] for p in par_annee if p["annee"] == REPERE_OECP["annee"]), None),
            "lecture_ecart": ("Deux sources, deux périmètres : le recensement de l'OECP compte les marchés d'au moins "
                              "40 000 € HT déclarés par les acheteurs, marchés de défense ou de sécurité compris ; les "
                              "DECP comptent les marchés publiés en données ouvertes, sans seuil commun à toutes les "
                              "années, après les règles de qualité de ce fichier. Les deux montants sont publiés côte "
                              "à côte ; ils ne sont ni additionnés ni corrigés l'un par l'autre.")},
        "series_repetees": series_repetees,
        "plus_gros_marches": plus_gros,
        "recoupements": recoupements,
        "centrales_achat": {
            "note": ("Risque de double compte, non corrigé : une centrale d'achat (UGAP, Resah...) publie ses marchés "
                     "avec ses fournisseurs (`comme_acheteur`, le plus souvent des accords-cadres au montant maximum "
                     "estimé) ; l'acheteur qui commande à la centrale peut publier son propre marché, dont la centrale "
                     "est titulaire (`comme_titulaire`). Le même achat peut donc figurer deux fois dans les totaux. "
                     "Les deux montants sont publiés ; aucun n'est retranché."),
            "centrales": centrales},
        "doublons_entre_sources": {
            "source": f"{PAGE_JEU} (fichier statistiques-doublons-sources.parquet)",
            "note": ("Le producteur du jeu fusionne plus de 70 sources et retire les doublons entre elles avant "
                     "publication. `part_unique_pct` : part des marchés d'une source qui ne figurent dans aucune "
                     "autre source, d'après son fichier de statistiques ; null si la source n'y figure pas."),
            "sources": doublons_sources},
        "regle_personnes": ("Un acheteur ou un titulaire n'est nommé que si sa catégorie juridique SIRENE est celle "
                            "d'une personne morale (2xxx à 9xxx hors groupements de personnes physiques) et si sa "
                            "diffusion n'est pas partielle ; le nom publié est la dénomination SIRENE. Entrepreneurs "
                            "individuels, SIREN absents du stock, unités à diffusion partielle : montants agrégés "
                            "(`agrege_confidentialite`), jamais nommés. Les colonnes de nom, d'objet, de commune et de "
                            "coordonnées des DECP ne sont pas lues."),
        "limites": [
            "Les DECP ne couvrent que les marchés publiés par les acheteurs : la couverture varie selon les années, "
            "les catégories d'acheteur et les plateformes.",
            "Le montant d'un accord-cadre est un maximum estimé, et un marché subséquent passé sur cet accord-cadre "
            "peut être publié à part : les deux sont alors comptés (voir `par_nature` dans annees.json).",
            "La nature publiée dépend du format de déclaration : à partir de 2024, presque toutes les lignes portent "
            "la nature « Marché » ; la répartition par nature n'est pas comparable d'une année à l'autre.",
            "Les marques « aberrant » et « suspect » sont celles du producteur du jeu ; un montant erroné non marqué "
            "reste dans les totaux, un montant exact marqué en sort.",
            "Un acheteur présent dans plusieurs départements (services de l'État) apparaît dans chacun, pour les "
            "marchés de ses établissements du département.",
            "Les montants par année ne sont pas des dépenses de l'année : un marché pluriannuel est compté en entier "
            "l'année de sa notification.",
            "Un montant erroné isolé, non marqué par le producteur et hors série de montants identiques, reste dans "
            "les totaux : les plus gros montants unitaires ne sont pas vérifiés un à un.",
            "Le code CPV est choisi par l'acheteur pour l'ensemble du marché : un marché qui mêle travaux et services "
            "est classé dans une seule division.",
        ],
        "sources_inaccessibles": [
            {"source": REPERE_OECP["source_officielle"]["url"],
             "motif": "HTTP 403 aux scripts le 17/11/2026, non contourné ; total 2024 saisi d'après une page accessible "
                      "qui cite l'étude (repere_oecp.page_consultee)"}],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "fichiers": {"annees": "marches/annees.json", "categories": "marches/categories.json",
                     "departements": "marches/departements.json",
                     "departement": "marches/departements/<code>.json", "regions": "marches/regions.json",
                     "secteurs": "marches/secteurs.json", "titulaires": "marches/titulaires.json",
                     "acheteurs": "marches/acheteurs.json"},
    }
    dump(sortie / "index.json", index)
    dump(sortie / "annees.json", {**entete, "annees": ANNEES, "par_annee": par_annee,
                                  "note": "`ecartes` : lignes de l'année écartées par les règles de qualité, avec leur "
                                          "montant déclaré, jamais ajouté au total de l'année."})
    dump(sortie / "categories.json", {
        **entete, "annees": ANNEES, "categories": categories,
        "note": ("`origine` = decp : catégorie donnée par le jeu ; sirene : dérivée de la catégorie juridique SIRENE "
                 "pour les acheteurs que le jeu ne classe pas. L'UGAP, centrale d'achat, est un EPIC : voir "
                 "`centrales_achat` dans index.json."),
        "ordre": "Catégories du jeu, puis catégories dérivées de SIRENE, dans un ordre fixe sans rapport avec les "
                 "montants."})
    dump(sortie / "departements.json", {
        **entete, "annees": ANNEES, "departements": departements, "non_localise": non_localise,
        "note": "Département de l'établissement acheteur. `montants_eur` est aligné sur `annees` ; null : aucune ligne "
                "retenue cette année-là.",
        "ordre": "Départements par code."})
    dump(sortie / "regions.json", {
        **entete, "annees": ANNEES, "regions": regions, "non_localise": reg_non_localise,
        "note": ("Région déduite du département de l'établissement acheteur (régions en vigueur depuis 2016). "
                 "`montants_eur` est aligné sur `annees` ; null : aucune ligne retenue cette année-là. "
                 "`non_localise` : département absent ou illisible dans la source."),
        "ordre": "Régions par code officiel, collectivités d'outre-mer à la fin."})
    dump(sortie / "secteurs.json", {
        **entete, "annees": ANNEES, "secteurs": secteurs,
        "nomenclature": ("Vocabulaire commun pour les marchés publics (CPV), règlement (CE) n° 213/2008 : division = "
                         "deux premiers chiffres du code principal publié par l'acheteur. Code absent, de moins de "
                         "huit chiffres ou division inconnue : division « 00 »."),
        "note": "`montants_eur` et `marches_par_annee` sont alignés sur `annees` ; null : aucune ligne retenue.",
        "ordre": "Divisions par code, dans l'ordre de la nomenclature, sans rapport avec les montants."})
    dump(sortie / "titulaires.json", {
        **entete, "annees": ANNEES, "titulaires": top_tit,
        "autres_personnes_morales": {"nombre": autres_pm["nombre"], "montant_eur": eur(autres_pm["m"])},
        "agrege_confidentialite": confidentialite(glob_statut, total),
        "par_annee": tit_par_annee,
        "regle_personnes": index["regle_personnes"],
        "note": (f"Les {TOP_NATIONAL} premiers titulaires nommés sur la période, puis les {TOP_ANNEE} premiers de chaque "
                 "année. Montant d'un marché à plusieurs titulaires réparti à parts égales. Entrepreneurs individuels "
                 "et unités non diffusibles : agrégés (`agrege_confidentialite`), jamais nommés."),
        "ordre": "Titulaires par montant décroissant, puis SIREN ; l'ordre ne porte aucune appréciation."})
    dump(sortie / "acheteurs.json", {
        **entete, "annees": ANNEES, "acheteurs": top_ach,
        "autres_acheteurs_nommes": {"nombre": ach_autres["nombre"], "montant_eur": eur(ach_autres["m"])},
        "acheteurs_non_nommes": {"nombre": ach_non_nommes["nombre"], "marches": ach_non_nommes["marches"],
                                 "montant_eur": eur(ach_non_nommes["m"])},
        "acheteur_illisible": {"marches": sans_ach[0], "montant_eur": eur(sans_ach[1])},
        "note": (f"Les {TOP_NATIONAL} premiers acheteurs nommés, tous départements réunis. Une centrale d'achat "
                 "(`centrale_achat`) achète pour d'autres acheteurs : voir `centrales_achat` dans index.json."),
        "ordre": "Acheteurs par montant décroissant, puis SIREN ; l'ordre ne porte aucune appréciation."})
    con.close()
    return index


# --- Collecte --------------------------------------------------------------------------------------------------------


def collecter() -> int:
    """Collecte par collecte/collecte.py (manifeste, reprise, zone restreinte) ; le fichier principal est lourd."""
    sys.path.insert(0, str(ROOT / "collecte"))
    import collecte
    return collecte.main([ID_DECP, ID_DOUBLONS, "--lourd"])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("etapes", nargs="*", help="collecter, produire (défaut : les deux)")
    ap.add_argument("--sortie", type=Path, help="dossier de sortie (défaut : site/data/marches)")
    a = ap.parse_args(argv)
    etapes = a.etapes or ["collecter", "produire"]
    if set(etapes) - {"collecter", "produire"}:
        ap.error("étapes possibles : collecter, produire")
    if "collecter" in etapes:
        collecter()
    if "produire" in etapes:
        idx = produire(a.sortie)
        t = idx["totaux"]
        print(f"marchés : {t['marches_retenus']} marchés retenus, {t['total_retenu_eur'] / 1e9:.1f} Md€ "
              f"({ANNEES[0]}-{ANNEES[-1]}), {t['acheteurs']} acheteurs, {t['titulaires_nommes']} titulaires nommés, "
              f"{t['agrege_confidentialite']['part_pct']} % agrégés")


if __name__ == "__main__":
    main()
