"""Eau et environnement : agences de l'eau, aides de l'ADEME, Fonds vert, programmes 113, 181 et 380.

Agrégats publiés seulement. Aucun bénéficiaire n'est nommé ici : les lauréats du Fonds vert et les bénéficiaires
des aides de l'ADEME qui sont des personnes morales sont nommés par la vue `subventions/` (filtre SIRENE commun) ;
cette vue y renvoie par des liens (fichier + chemin), sans recopier ni additionner leurs montants.

Entrées (data/lake, non versionné), collectées par `collecter` (collecte/collecte.py, catalogue) :
    eau_environnement/eau_jaune_agences_eau_plf2026.pdf   annexe au PLF 2026 « Agences de l'eau » (jaune) : par
                                                          agence, redevances encaissées par catégorie et autorisations
                                                          d'engagement par domaine, exécution 2019 à 2024
    eau_environnement/eau_jaune_agences_eau_plf2025.pdf   édition précédente (exécution 2019 à 2023), comparée ligne
                                                          à ligne : les écarts entre éditions sont publiés
    _restreint/subventions/subv_ademe_aides.csv           ADEME, « Les aides financières de l'ADEME » (SCDL)
    _restreint/subventions/subv_fonds_vert/*.csv          Fonds vert, liste des projets subventionnés 2023 à 2025
    (les deux dernières sont les entrées de pipeline/subventions.py : même fichier, autre lecture, aucun nom lu)
Fichiers versionnés lus : site/data/local/geo/<dep>.json (département -> région).

Sorties (site/data/eau_environnement/, contrat docs/contrat_interface.md, schémas docs/schemas/eau_environnement_*) :
    index.json        sources, liens vers les autres vues, plafond des redevances, limites, recherche publique
    agences_eau.json  six agences et ensemble : redevances par catégorie et par année, écrêtement reversé au budget
                      général, autorisations d'engagement par domaine, contrôles, écarts entre éditions du jaune
    ademe.json        aides de l'ADEME par année, par région, par dispositif ; dispositifs nommés « Fonds chaleur »
                      ou « Fonds économie circulaire » dans leur libellé
    fonds_vert.json   Fonds vert par année et programme, par région, par service instructeur, par forme juridique,
                      par démarche ; montants instruits par les agences de l'eau face aux lignes « Fonds vert » du jaune

Commandes :
    python pipeline/eau_environnement.py collecter   # réseau ; un refus 401/403/429 est noté, jamais contourné
    python pipeline/eau_environnement.py produire    # sans réseau (pdftotext, paquet poppler-utils)

Règles : une cellule vide ou une valeur non communiquée est null, jamais 0 ; deux sources sur le même argent ne sont
jamais additionnées (écart publié) ; libellés des sources gardés ; dates par pipeline/reproductible.py.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "eau_environnement"
LO = "Licence Ouverte 2.0"

# --- Sources -----------------------------------------------------------------------------------------------------------

SOURCES = {
    "eau_jaune_agences_eau_plf2026": {
        "titre": "Annexe au projet de loi de finances pour 2026, « Agences de l'eau » (jaune budgétaire) : tableaux "
                 "« Suivi des redevances encaissées » et « Suivi du plafond pluriannuel des dépenses (autorisations "
                 "d'engagement) », pour l'ensemble des six agences et pour chacune, exécution 2019 à 2024",
        "producteur": "Ministère de la Transition écologique (direction de l'eau et de la biodiversité), annexe au PLF",
        "url": "https://www.assemblee-nationale.fr/dyn/dyn/contenu/visualisation/1089974/file/1-Jaune2026_Agences_Eau.pdf",
        "page": "https://www.budget.gouv.fr/documentation/documents-budgetaires",
        "millesime": "PLF 2026 (exécution 2019 à 2024)", "licence": "document administratif public",
        "verdict": "à adapter (tableaux d'un PDF, relus par position de colonne ; contrôles de sommes publiés)",
    },
    "eau_jaune_agences_eau_plf2025": {
        "titre": "Annexe au projet de loi de finances pour 2025, « Agences de l'eau » (jaune budgétaire) : mêmes "
                 "tableaux, exécution 2019 à 2023 (colonnes « projection » écartées)",
        "producteur": "Ministère de la Transition écologique (direction de l'eau et de la biodiversité), annexe au PLF",
        "url": "https://www2.assemblee-nationale.fr/static/17/Annexes-DL/PLF2025-Jaunes/01-Jaune_Agences_eau.pdf",
        "page": "https://www.budget.gouv.fr/documentation/documents-budgetaires",
        "millesime": "PLF 2025 (exécution 2019 à 2023)", "licence": "document administratif public",
        "verdict": "à adapter (édition précédente, comparée à l'édition 2026)",
    },
    "subv_ademe_aides": {
        "titre": "ADEME, « Les aides financières de l'ADEME » (conventions de subvention au format SCDL, fichier enrichi "
                 "du département de l'établissement bénéficiaire)",
        "producteur": "ADEME", "url": "https://data.ademe.fr/data-fair/api/v1/datasets/les-aides-financieres-de-l%27ademe/full",
        "page": "https://data.ademe.fr/datasets/les-aides-financieres-de-l'ademe",
        "millesime": "conventions signées de 2021 à 2026", "licence": LO,
        "verdict": "réutilisable tel quel (même fichier que pipeline/subventions.py)",
    },
    "subv_fonds_vert": {
        "titre": "Ministère de la Transition écologique, « Fonds vert : liste des projets subventionnés » (fichiers "
                 "« fonds-vert-<année> » : programme 380 ; « fonds-vert-p113-<année> » : programme 113)",
        "producteur": "Ministère de la Transition écologique",
        "url": "https://www.data.gouv.fr/datasets/66a215a463a9da4fb801b8cf",
        "page": "https://www.data.gouv.fr/datasets/66a215a463a9da4fb801b8cf",
        "millesime": "montants engagés en 2023, 2024 et 2025", "licence": LO,
        "verdict": "réutilisable tel quel (même fichiers que pipeline/subventions.py)",
    },
}

AGENCES = [  # (id, nom affiché, nom dans les titres de tableaux du jaune)
    ("adour_garonne", "Agence de l'eau Adour-Garonne", "Adour-Garonne"),
    ("artois_picardie", "Agence de l'eau Artois-Picardie", "Artois-Picardie"),
    ("loire_bretagne", "Agence de l'eau Loire-Bretagne", "Loire-Bretagne"),
    ("rhin_meuse", "Agence de l'eau Rhin-Meuse", "Rhin-Meuse"),
    ("rhone_mediterranee_corse", "Agence de l'eau Rhône-Méditerranée-Corse", "Rhône-Méditerranée-Corse"),
    ("seine_normandie", "Agence de l'eau Seine-Normandie", "Seine-Normandie"),
]
ENSEMBLE = ("ensemble", "Ensemble des six agences de l'eau (tableaux de synthèse du jaune)")

# Lignes du tableau « Suivi des redevances encaissées » : (id, libellé, début du libellé normalisé de la source,
# niveau, catégorie parente). Les lignes de détail qui répètent leur total (pollution domestique, pollutions
# diffuses, stockage, obstacles, protection du milieu, cynégétique, écrêtement) ne sont lues qu'une fois.
REDEVANCES = [
    ("pollution_non_domestique_industries", "Pollution de l'eau d'origine non domestique : industries",
     "industries", "detail", "pollution_non_domestique"),
    ("pollution_non_domestique_elevage", "Pollution de l'eau d'origine non domestique : élevage",
     "elevage", "detail", "pollution_non_domestique"),
    ("pollution_non_domestique", "Pollution de l'eau d'origine non domestique",
     "total redevances pollution non domestique", "categorie", None),
    ("pollution_domestique", "Pollution de l'eau d'origine domestique",
     "total redevances pollution domestique", "categorie", None),
    ("modernisation_reseaux_non_domestique", "Modernisation des réseaux de collecte : assujettis à la redevance "
     "pollution non domestique", "assujettis a la redevance pollution non domestique", "detail", "modernisation_reseaux"),
    ("modernisation_reseaux_domestique", "Modernisation des réseaux de collecte : assujettis à la redevance pollution "
     "domestique", "assujettis a la redevance pollution domestique", "detail", "modernisation_reseaux"),
    ("modernisation_reseaux", "Modernisation des réseaux de collecte", "total redevances modernisation reseaux",
     "categorie", None),
    ("pollutions_diffuses", "Pollutions diffuses", "total redevances pollutions diffuses", "categorie", None),
    ("prelevement_irrigation", "Prélèvement sur la ressource en eau : irrigation", "irrigation", "detail",
     "prelevement"),
    ("prelevement_eau_potable", "Prélèvement sur la ressource en eau : alimentation en eau potable",
     "alimentation en eau potable", "detail", "prelevement"),
    ("prelevement_canal", "Prélèvement sur la ressource en eau : alimentation d'un canal", "alimentation d'un canal",
     "detail", "prelevement"),
    ("prelevement_hydroelectricite", "Prélèvement sur la ressource en eau : installations hydroélectriques",
     "installations hydroelectriques", "detail", "prelevement"),
    ("prelevement_refroidissement", "Prélèvement sur la ressource en eau : refroidissement industriel",
     "refroidissement industriel", "detail", "prelevement"),
    ("prelevement_autres_usages", "Prélèvement sur la ressource en eau : autres usages économiques",
     "autres usages economiques", "detail", "prelevement"),
    ("prelevement", "Prélèvement sur la ressource en eau", "total redevances prelevement", "categorie", None),
    ("stockage_etiage", "Stockage d'eau en période d'étiage", "total redevance stockage", "categorie", None),
    ("obstacles", "Obstacles sur les cours d'eau", "total redevance obstacles", "categorie", None),
    ("protection_milieu", "Protection du milieu aquatique", "total redevance protection milieu", "categorie", None),
    ("cynegetique", "Redevance cynégétique et droit de timbre", "total redevance cynegetique", "categorie", None),
    ("redevances_encaissees", "Sous-total des redevances encaissées (1)", "sous-total des redevances encaissees",
     "total", None),
    ("majorations_paiement", "Majorations pour retard ou défaut de paiement",
     "majorations de redevances pour retard / defaut de paiement", "detail", "majorations"),
    ("majorations_declaration", "Majorations pour retard ou défaut de déclaration",
     "majorations de redevances pour retard / defaut de declaration", "detail", "majorations"),
    ("majorations", "Sous-total des majorations de redevances (2)", "sous-total des majorations", "total", None),
    ("ecretement", "Écrêtement des redevances reversé au budget général de l'État (3)",
     "sous-total ecretement des redevances", "total", None),
    ("fiscalite_affectee", "Fiscalité affectée = (1) + (2) - (3)", "fiscalite affectee", "total", None),
]
CATEGORIES = [r[0] for r in REDEVANCES if r[3] == "categorie"]

# Plafond annuel des redevances (article 46 de la loi de finances pour 2012), d'après la note du jaune 2026. La
# citation est retrouvée dans le texte du document à chaque production (sinon : arrêt).
PLAFOND_CITATION = ("le plafond de taxes affectées aux agences de l'eau, instauré par l'article 46 de la loi de "
                    "finances pour 2012, était fixé à 2 105 M€ en loi de finances pour 2019. Il a été relevé à "
                    "2 156,62 M€ par la loi de finances pour 2020")
PLAFONDS = {2019: 2105.0, 2020: 2156.62, 2021: 2197.62, 2022: 2197.62, 2023: 2197.62, 2024: 2347.62}
PLAFOND_CITATIONS_COMPLEMENTAIRES = ["à 2 197,62 M€ en loi de finances pour 2021", "et à 2 347,62 M€ par la loi de "
                                     "finances pour 2024"]

INACCESSIBLES = [
    {"source": "Redevances et aides des agences de l'eau en jeu de données ouvert (par agence, par année)",
     "motif": "aucun jeu national trouvé sur data.gouv.fr, data.eaufrance.fr ni les portails des agences ; seules "
              "Artois-Picardie (conventions signées) et Loire-Bretagne (décisions d'aide des 10e et 11e programmes, "
              "jeu arrêté en 2024) publient leurs aides ligne à ligne : les montants par agence viennent du jaune "
              "budgétaire (PDF)"},
    {"source": "Montants annuels du Fonds chaleur et du Fonds économie circulaire de l'ADEME",
     "motif": "publiés dans les rapports d'activité et les documents budgétaires de l'ADEME (PDF), pas en jeu ouvert ; "
              "le fichier des aides de l'ADEME ne porte pas de champ « fonds » : seuls les dispositifs dont le "
              "libellé nomme le fonds sont repérés ici"},
    {"source": "ADEME, « data_aides_themes » (aides par thématique et région, data.ademe.fr)",
     "motif": "jeu sans licence ni description publiées, sans champ d'année : non repris"},
    {"source": "Prélèvements de l'État sur le fonds de roulement des agences de l'eau (années 2014 à 2018)",
     "motif": "antérieurs aux tableaux 2019 à 2024 du jaune ; décrits dans les lois de finances de ces années, sans "
              "jeu ouvert par agence ; non repris"},
    {"source": "Annexe au PLF 2024 « Agences de l'eau »",
     "motif": "les tableaux de redevances par agence y sont des images (texte non extractible) : non reprise ; les "
              "éditions 2025 et 2026 couvrent 2019 à 2024"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Aucun dépôt public ne publie les redevances et les aides des six agences de l'eau par année sous "
                  "forme de données : les tableaux du jaune budgétaire sont relus ici. Les aides de l'ADEME et du "
                  "Fonds vert sont des jeux officiels repris tels quels (déjà collectés par pipeline/subventions.py).",
    "trouvailles": [
        {"nom": "Annexes au PLF « Agences de l'eau » (jaunes 2025 et 2026)", "url": SOURCES[
            "eau_jaune_agences_eau_plf2026"]["url"], "licence": "document administratif public",
         "mise_a_jour": "2025-10", "verdict": "à adapter"},
        {"nom": "ADEME, Les aides financières de l'ADEME (data-fair)", "url": SOURCES["subv_ademe_aides"]["page"],
         "licence": LO, "mise_a_jour": "2026-11-18", "verdict": "réutilisable tel quel"},
        {"nom": "Fonds vert : liste des projets subventionnés (data.gouv.fr)", "url": SOURCES["subv_fonds_vert"]["page"],
         "licence": LO, "mise_a_jour": "2026-07-28", "verdict": "réutilisable tel quel"},
        {"nom": "Agence de l'eau Loire-Bretagne, décisions d'aide des 10e et 11e programmes (data.gouv.fr)",
         "url": "https://www.data.gouv.fr/datasets/5a1295cdc751df7acd724663", "licence": LO,
         "mise_a_jour": "2024-11-07", "verdict": "inspiration seulement (une agence sur six, jeu arrêté en 2024)"},
        {"nom": "Agence de l'eau Artois-Picardie, conventions de subvention signées (data.gouv.fr)",
         "url": "https://www.data.gouv.fr/datasets/5b9249d2634f411b8339f194", "licence": LO,
         "mise_a_jour": "2026-11-08", "verdict": "réutilisable tel quel (déjà publié par subventions/)"},
        {"nom": "Direction du budget, liste des taxes affectées (PLF 2023 et 2024, data.economie.gouv.fr)",
         "url": "https://data.economie.gouv.fr/explore/dataset/plf2024-v-and-m-t1-liste-des-taxes-affectees/",
         "licence": LO, "mise_a_jour": "2023-10", "verdict": "inspiration seulement (une ligne pour les six "
                                                              "agences ; plafond repris du jaune)"},
        {"nom": "ADEME, data_aides_themes (data.ademe.fr)", "url": "https://data.ademe.fr/datasets/5nipdvpqqfcupeozysjflnqp",
         "licence": "non précisée", "mise_a_jour": "2025-10-07", "verdict": "inspiration seulement"},
        {"nom": "brunocpu/fonds-vert-paca-carto", "url": "https://github.com/brunocpu/fonds-vert-paca-carto",
         "licence": "non précisée", "dernier_commit": "2026-09-27",
         "verdict": "inspiration seulement (une région, carte)"},
        {"nom": "pipeline/subventions.py (ce dépôt)", "url": "pipeline/subventions.py", "licence": "MIT (ce dépôt)",
         "dernier_commit": "2026-11-17", "verdict": "réutilisable tel quel (lauréats nommés, filtre SIRENE ; "
                                                     "cette vue y renvoie)"},
        {"nom": "Recherches GitHub « agences de l'eau redevances », « jaune agences eau », « fonds chaleur ademe "
                "open data »", "url": "https://github.com/search", "licence": None, "dernier_commit": None,
         "verdict": "aucun dépôt pertinent"},
    ],
}

LIENS = [
    {"vue": "programme", "fichier": "programmes/113.json", "id": "113",
     "lecture": "programme 113 « Paysages, eau et biodiversité » (PLF 2025, par action et par nature) : chef de file "
                "des agences de l'eau, qui n'en reçoivent pas de subvention pour charges de service public ; leurs "
                "ressources sont les redevances ci-dessous"},
    {"vue": "programme", "fichier": "programmes/181.json", "id": "181",
     "lecture": "programme 181 « Prévention des risques » : action 12, subvention à l'ADEME ; montant budgétaire, "
                "jamais additionné aux aides engagées par l'ADEME (même argent, autre étape)"},
    {"vue": "programme", "fichier": "programmes/380.json", "id": "380",
     "lecture": "programme 380 « Fonds d'accélération de la transition écologique dans les territoires » (Fonds vert)"},
    {"vue": "operateurs", "fichier": "operateurs/operateurs.json", "id": "agencesdeleau",
     "lecture": "agences de l'eau dans les jaunes « Opérateurs » : taxes affectées, ressources propres, emplois "
                "(une ligne pour les six agences)"},
    {"vue": "operateurs", "fichier": "operateurs/operateurs.json", "id": "ademe",
     "lecture": "ADEME dans les jaunes « Opérateurs » : financement de l'État, emplois"},
    {"vue": "subventions", "fichier": "subventions/attribuants/subv_fonds_vert.json", "id": "beneficiaires",
     "lecture": "lauréats du Fonds vert nommés quand ils sont des personnes morales (collectivités, établissements, "
                "entreprises, associations ; filtre SIRENE commun), montants par bénéficiaire"},
    {"vue": "subventions", "fichier": "subventions/attribuants/subv_ademe_aides.json", "id": "beneficiaires",
     "lecture": "bénéficiaires des aides de l'ADEME nommés quand ils sont des personnes morales, par département"},
    {"vue": "subventions", "fichier": "subventions/attribuants/subv_aeap.json", "id": "par_annee",
     "lecture": "conventions de subvention signées par l'agence de l'eau Artois-Picardie, ligne à ligne"},
]

LIMITES = [
    "Agences de l'eau : redevances encaissées dans l'année (pas les redevances dues de l'année) ; aides en "
    "autorisations d'engagement (engagements pris dans l'année, pas les paiements), en millions d'euros arrondis "
    "par la source (deux décimales dans l'édition 2026, une dans l'édition 2025).",
    "Les tableaux sont lus dans le texte du PDF par position de colonne ; chaque tableau est contrôlé (somme des "
    "catégories, identité (1) + (2) - (3), somme des domaines) et les contrôles sont publiés avec leur écart.",
    "Une cellule vide dans le tableau du jaune est publiée null, jamais 0 : la source ne distingue pas un montant nul "
    "d'une absence de montant.",
    "L'ensemble des six agences vient des tableaux de synthèse du jaune ; la somme des six agences est publiée à côté "
    "comme contrôle, sans remplacer la synthèse.",
    "ADEME et Fonds vert : montants engagés ou attribués, comptés l'année de la convention (ADEME) ou du fichier "
    "annuel (Fonds vert) ; une ligne sans montant est comptée dans `lignes_montant_non_communique`.",
    "Région des aides de l'ADEME : celle du département de l'établissement bénéficiaire (colonne enrichie par "
    "l'ADEME) ; région du Fonds vert : colonne « nom_region » de la source.",
    "Fonds vert : la forme juridique du bénéficiaire et le service instructeur (« opérateur ») ne sont publiés qu'à "
    "partir de 2024 ; le fichier du programme 113 de 2024 ne publie pas la forme juridique.",
    "Dernière année des aides de l'ADEME : conventions publiées à la date de la collecte (année incomplète).",
    "Fonds vert, liste et jaune côte à côte : quand la colonne « opérateur » est publiée et qu'aucun projet n'y est "
    "rattaché à une agence, `liste_fonds_vert_eur` est null et `liste_projets` vaut 0.",
]

REGLES = [
    "Aucun bénéficiaire nommé dans cette vue : les noms des personnes morales sont dans subventions/ (lien).",
    "Une valeur absente à la source est null, jamais 0.",
    "Deux sources sur le même argent (jaune et liste du Fonds vert, programme 181 et aides de l'ADEME) ne sont "
    "jamais additionnées : elles sont publiées côte à côte avec leur écart.",
    "Un dispositif de l'ADEME suivi par moins de 3 conventions est regroupé dans « autres dispositifs ».",
]

SEUIL_DISPOSITIF = 3
TOLERANCE_ARRONDI_MEUR = 0.3   # contrôle d'une somme de lignes arrondies à 0,1 M€
ECART_EDITIONS_MIN = 0.051     # en dessous : arrondi (deux décimales en 2026, une en 2025)


# --- Utilitaires -------------------------------------------------------------------------------------------------------

def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").replace("’", "'").replace(" ", " "))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s.replace("m ajorations", "majorations")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm(s)).strip("_")[:60]


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def arrondi(v, d=2):
    return None if v is None else round(v + 0.0, d)


def fichiers_source(sid: str) -> list[Path]:
    """Fichiers collectés d'une source, d'après le manifeste de l'entrepôt."""
    try:
        m = json.loads((LAKE / "manifest.json").read_text(encoding="utf-8")).get(sid) or {}
    except (OSError, ValueError):
        m = {}
    res = sorted({ROOT / f["chemin"] for f in m.get("fichiers", []) if (ROOT / f["chemin"]).exists()})
    if not res:
        raise FileNotFoundError(f"source absente de data/lake : {sid} (python pipeline/eau_environnement.py collecter)")
    return res


def lire_csv(chemin: Path) -> list[dict]:
    brut = chemin.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            texte = brut.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    premiere = texte.split("\n", 1)[0]
    sep = ";" if premiere.count(";") > premiere.count(",") else ","
    lecteur = csv.reader(io.StringIO(texte), delimiter=sep)
    entete = [norm(c).replace(" ", "_").replace('"', "") for c in next(lecteur)]
    return [dict(zip(entete, r)) for r in lecteur if any(x.strip() for x in r)]


def montant(v) -> float | None:
    s = str(v or "").strip().replace(" ", "").replace(" ", "").replace("€", "")
    if not s or s.lower() in ("nc", "n/a", "na", "null", "-"):
        return None
    if "," in s and "." in s:
        s = s.replace(",", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def regions_par_departement() -> dict[str, tuple[str, str]]:
    out = {}
    for f in sorted((SITE / "local" / "geo").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[d["departement"]["code"]] = (d["region"]["code"], d["region"]["nom"])
    if not out:
        raise FileNotFoundError("site/data/local/geo absent (étape « local »)")
    return out


# --- Jaune « Agences de l'eau » -------------------------------------------------------------------------------------

NOMBRE = re.compile(r"(?<![\d,])-?\d{1,3}(?: \d{3})*,\d+(?![\d,])")


def texte_pdf(chemin: Path) -> list[str]:
    if not shutil.which("pdftotext"):
        raise SystemExit("pdftotext absent (paquet poppler-utils)")
    r = subprocess.run(["pdftotext", "-layout", str(chemin), "-"], capture_output=True, check=True)
    return r.stdout.decode("utf-8", errors="replace").split("\n")


def _ancres(lignes: list[str]):
    """Années et centres des colonnes (une par colonne d'années + la colonne « Total »)."""
    annees = quals = total = None
    for ligne in lignes[:14]:
        ys = [(int(m.group()), m.start()) for m in re.finditer(r"\b20\d\d\b", ligne)]
        if len(ys) >= 4 and annees is None:
            annees = [y for y, _ in ys]
            continue
        qs = [(m.group(), (m.start() + m.end()) / 2) for m in re.finditer(r"\([^)]{2,20}\)", ligne)]
        if len(qs) >= 4 and quals is None:
            quals = qs
        aes = [(m.start() + m.end()) / 2 for m in re.finditer(r"\bAE\b", ligne)]
        if annees and quals and len(aes) == len(annees) + 1:
            return annees, [q for q, _ in quals], aes
        t = re.search(r"\b(?:TOTAL|Total)\b", ligne)
        if t and annees is not None and total is None:
            total = (t.start() + t.end()) / 2
    if not (annees and quals and total) or len(annees) != len(quals):
        raise ValueError("en-tête de tableau illisible")
    return annees, [q for q, _ in quals], [c for _, c in quals] + [total]


def lire_tableau(lignes: list[str], debut: int, fin_motif: re.Pattern) -> tuple[dict[int, int], list[tuple]]:
    """Lignes (libellé, {colonne: valeur}) d'un tableau ; colonnes gardées : « (exécution) » seulement."""
    annees, quals, ancres = _ancres(lignes[debut + 1:debut + 16])
    garde = {i: a for i, (a, q) in enumerate(zip(annees, quals)) if "ex" in norm(q)}
    out = []
    for ligne in lignes[debut + 1:debut + 260]:
        # un nombre à gauche des colonnes est un code de ligne mal extrait (« 0,00 ») : il reste dans le libellé
        nombres = [m for m in NOMBRE.finditer(ligne) if (m.start() + m.end()) / 2 >= ancres[0] - 15]
        if nombres:
            libelle = ligne[:nombres[0].start()].strip()
            vals = {}
            for m in nombres:
                c = (m.start() + m.end()) / 2
                k = min(range(len(ancres)), key=lambda i: abs(ancres[i] - c))
                vals[k] = float(m.group().replace(" ", "").replace(",", "."))
            out.append((libelle, {garde[k]: v for k, v in vals.items() if k in garde}))
        if fin_motif.search(norm(ligne)):
            return garde, out
    raise ValueError("fin de tableau introuvable")


def _cherche(lignes: list[str], motif: re.Pattern, apres: int = 0) -> int:
    for i in range(apres, len(lignes)):
        if motif.search(norm(lignes[i])):
            return i
    raise ValueError(f"tableau introuvable : {motif.pattern}")


def redevances(lignes: list[str], debut: int) -> tuple[list[int], dict[str, dict[int, float | None]]]:
    garde, tab = lire_tableau(lignes, debut, re.compile(r"^fiscalite affectee"))
    annees = sorted(set(garde.values()))
    series = {}
    for rid, _, motif, _, _ in REDEVANCES:
        trouve = [v for lib, v in tab if norm(lib).startswith(motif)]
        if rid == "ecretement" and not trouve:
            trouve = [v for lib, v in tab if norm(lib).startswith("ecretement des redevances")]
        vals = trouve[0] if trouve else {}
        series[rid] = {a: vals.get(a) for a in annees}
    return annees, series


def autorisations(lignes: list[str], debut: int, codes: dict[str, str] | None = None) -> tuple[list[int], list[dict]]:
    """Tableau 1 ; `codes` : code de destination par libellé normalisé (tableau de synthèse), pour les tableaux
    d'agence dont la colonne des codes est illisible dans le PDF (« 0,00 »)."""
    garde, tab = lire_tableau(lignes, debut, re.compile(r"^total des depenses budgetaires(?: [0-9 ,]*)?$"))
    annees = sorted(set(garde.values()))
    out, bloc, vus = [], "sous_plafond", {}
    for lib, vals in tab:
        lib = re.sub(r"^\s*0,00\s+", "", lib)
        n = norm(lib)
        m = re.match(r"^(d\d|xx\d*|yy\d*|zz\d*|\d{2,4})(?=\s)", n)
        code = m.group(1).upper() if m else None
        libelle = re.sub(r"^\s*(?:D\d|XX\d*|YY\d*|ZZ\d*|\d{2,4})\s+(?:-\s*)?", "", lib).strip() if code else lib.strip()
        if code is None and codes and norm(libelle) in codes:
            code = codes[norm(libelle)]
        if n.startswith("total des depenses budgetaires sous plafond"):
            type_, rid = "total", "total_sous_plafond"
        elif n.startswith("total des depenses budgetaires hors plafond"):
            type_, rid = "total", "total_hors_plafond"
        elif n.startswith("total des depenses budgetaires"):
            type_, rid = "total", "total_depenses"
        elif code and code.startswith("D"):
            type_, rid = "total_domaine", code.lower()
        elif n.startswith("dont "):
            type_, rid = "dont", "dont_" + slug(n[5:])
        elif code and re.fullmatch(r"\d{2}", code):
            type_, rid = "ligne", code
        elif n.startswith("primes mentionnees"):
            type_, rid = "dont", "primes_article_l213_9_2"
        else:
            detail = bool(code and re.fullmatch(r"(?:XX|YY|ZZ)\d+|\d{3,4}", code))
            type_, rid = ("detail" if detail else "ligne"), slug(lib)
        if rid in vus:   # même libellé répété (groupe et détail) : identifiant suffixé, ordre de la source
            vus[rid] += 1
            rid = f"{rid}_{vus[rid]}"
        else:
            vus[rid] = 1
        out.append({"id": rid, "code": code, "libelle": libelle, "type": type_, "bloc": bloc,
                    "valeurs_meur": {str(a): vals.get(a) for a in annees}})
        if rid == "total_sous_plafond":
            bloc = "hors_plafond"
        elif rid == "total_hors_plafond":
            bloc = "total"
    return annees, out


def lire_jaune(sid: str) -> dict:
    lignes = texte_pdf(fichiers_source(sid)[0])
    res = {"lignes": lignes, "agences": {}}
    i3 = _cherche(lignes, re.compile(r"^tableau 3 . suivi des redevances encaissees"))
    i1 = _cherche(lignes, re.compile(r"^tableau 1 . suivi du plafond pluriannuel"))
    res["agences"]["ensemble"] = {"redevances": redevances(lignes, i3), "ae": autorisations(lignes, i1 + 1)}
    codes = {norm(l["libelle"]): l["code"] for l in res["agences"]["ensemble"]["ae"][1]
             if l["code"] and re.fullmatch(r"\d{2}", l["code"])}
    for aid, _, titre in AGENCES:
        t = re.escape(norm(titre))
        ir = _cherche(lignes, re.compile(rf"^suivi des redevances encaissees de l'agence de l'eau {t}"))
        ia = _cherche(lignes, re.compile(rf"tableau 1 : suivi du plafond pluriannuel .* de l'agence de l'eau {t}"))
        res["agences"][aid] = {"redevances": redevances(lignes, ir), "ae": autorisations(lignes, ia + 1, codes)}
    return res


def _somme(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals), 2) if vals else None


def controles_agence(aid: str, annees: list[int], red: dict, ae: list[dict]) -> list[dict]:
    out = []
    par_id = {l["id"]: l for l in ae}
    for a in annees:
        s = _somme(red[c][a] for c in CATEGORIES)
        out.append({"agence": aid, "annee": a, "controle": "somme des catégories = sous-total (1)",
                    "calcule_meur": s, "publie_meur": red["redevances_encaissees"][a],
                    "ecart_meur": arrondi(s - red["redevances_encaissees"][a]) if s is not None and
                    red["redevances_encaissees"][a] is not None else None})
        f = [red["redevances_encaissees"][a], red["majorations"][a], red["ecretement"][a]]
        if f[0] is not None:
            calc = round(f[0] + (f[1] or 0) - (f[2] or 0), 2)
            out.append({"agence": aid, "annee": a, "controle": "(1) + (2) - (3) = fiscalité affectée",
                        "calcule_meur": calc, "publie_meur": red["fiscalite_affectee"][a],
                        "ecart_meur": arrondi(calc - red["fiscalite_affectee"][a])
                        if red["fiscalite_affectee"][a] is not None else None})
        dom = _somme(par_id[d]["valeurs_meur"][str(a)] for d in ("d0", "d1", "d2", "d3") if d in par_id)
        primes = par_id.get("17", {}).get("valeurs_meur", {}).get(str(a))
        tot = par_id.get("total_sous_plafond", {}).get("valeurs_meur", {}).get(str(a))
        if dom is not None and tot is not None:
            calc = round(dom + (primes or 0), 2)
            out.append({"agence": aid, "annee": a, "controle": "domaines 0 à 3 + primes (17) = total sous plafond",
                        "calcule_meur": calc, "publie_meur": tot, "ecart_meur": arrondi(calc - tot)})
    return out


def produire_agences(collecte_le: str) -> tuple[dict, list[str]]:
    j26 = lire_jaune("eau_jaune_agences_eau_plf2026")
    j25 = lire_jaune("eau_jaune_agences_eau_plf2025")
    texte = norm(" ".join(j26["lignes"]))
    citations = [PLAFOND_CITATION] + PLAFOND_CITATIONS_COMPLEMENTAIRES
    absentes = [c for c in citations if norm(c) not in texte]
    if absentes:
        raise SystemExit(f"citation du plafond introuvable dans le jaune 2026 : {absentes[0][:80]}")
    agences, controles, ecarts, compares = [], [], [], 0
    noms = {aid: nom for aid, nom, _ in AGENCES} | {ENSEMBLE[0]: ENSEMBLE[1]}
    for aid in [ENSEMBLE[0]] + [a for a, _, _ in AGENCES]:
        annees, red = j26["agences"][aid]["redevances"]
        annees_ae, ae = j26["agences"][aid]["ae"]
        controles += controles_agence(aid, annees, red, ae)
        lignes_red = [{"id": rid, "libelle": lib, "niveau": niv, "parent": par,
                       "valeurs_meur": {str(a): red[rid][a] for a in annees}} for rid, lib, _, niv, par in REDEVANCES]
        par_id = {l["id"]: l for l in ae}
        agences.append({
            "id": aid, "nom": noms[aid],
            "redevances": {"annees": annees, "lignes": lignes_red},
            "ecretement_meur": {str(a): red["ecretement"][a] for a in annees},
            "contribution_operateurs_meur": dict(par_id["50"]["valeurs_meur"]) if "50" in par_id else None,
            "autorisations_engagement": {"annees": annees_ae, "lignes": ae},
        })
        # écarts entre éditions (années communes, colonnes « exécution »)
        a25, red25 = j25["agences"][aid]["redevances"]
        for rid, lib, _, _, _ in REDEVANCES:
            for a in a25:
                v26, v25 = red.get(rid, {}).get(a), red25[rid].get(a)
                compares += a in annees and v26 is not None and v25 is not None
                if a in annees and v26 is not None and v25 is not None and abs(v26 - v25) >= ECART_EDITIONS_MIN:
                    ecarts.append({"agence": aid, "tableau": "redevances", "ligne": rid, "libelle": lib, "annee": a,
                                   "edition_2026_meur": v26, "edition_2025_meur": v25, "ecart_meur": arrondi(v26 - v25)})
        _, ae25 = j25["agences"][aid]["ae"]
        cle = lambda l: l["code"] or l["id"]  # noqa: E731
        par_code25 = {}
        for l in ae25:
            par_code25.setdefault(cle(l), l)
        for l in ae:
            if l["type"] not in ("ligne", "total_domaine", "total") or l["bloc"] == "hors_plafond":
                continue
            l25 = par_code25.get(cle(l))
            if not l25:
                continue
            for a, v26 in l["valeurs_meur"].items():
                v25 = l25["valeurs_meur"].get(a)
                compares += v26 is not None and v25 is not None
                if v26 is not None and v25 is not None and abs(v26 - v25) >= ECART_EDITIONS_MIN:
                    ecarts.append({"agence": aid, "tableau": "autorisations_engagement", "ligne": cle(l),
                                   "libelle": l["libelle"], "annee": int(a), "edition_2026_meur": v26,
                                   "edition_2025_meur": v25, "ecart_meur": arrondi(v26 - v25)})
    # contrôle de la synthèse : somme des six agences
    ens = agences[0]
    somme_agences = []
    for rid in ("redevances_encaissees", "fiscalite_affectee"):
        for a in ens["redevances"]["annees"]:
            vals = [next(l for l in ag["redevances"]["lignes"] if l["id"] == rid)["valeurs_meur"][str(a)]
                    for ag in agences[1:]]
            pub = next(l for l in ens["redevances"]["lignes"] if l["id"] == rid)["valeurs_meur"][str(a)]
            s = _somme(vals)
            somme_agences.append({"ligne": rid, "annee": a, "somme_six_agences_meur": s, "ensemble_publie_meur": pub,
                                  "ecart_meur": arrondi(s - pub) if s is not None and pub is not None else None})
    pire = max((abs(c["ecart_meur"]) for c in controles if c["ecart_meur"] is not None), default=0)
    if pire > 2:
        raise SystemExit(f"contrôle d'un tableau du jaune : écart de {pire} M€ (lecture des colonnes à revoir)")
    doc = {
        "millesime": "exécution 2019 à 2024 (annexe au PLF 2026) ; édition précédente comparée (PLF 2025)",
        "source": SOURCES["eau_jaune_agences_eau_plf2026"]["titre"],
        "source_url": SOURCES["eau_jaune_agences_eau_plf2026"]["url"],
        "collecte_le": collecte_le,
        "unite": "millions d'euros (arrondis par la source)",
        "definitions": {
            "redevances": "redevances encaissées par l'agence entre le 1er janvier et le 31 décembre (redevances de "
                          "l'année précédente, acomptes de l'année et rappels), par catégorie de redevance",
            "ecretement": "part des redevances encaissées au-delà du plafond annuel, reversée au budget général de "
                          "l'État (article 46 de la loi de finances pour 2012) : ligne (3) du tableau",
            "contribution_operateurs": "ligne 50 des autorisations d'engagement : contribution des agences à "
                                       "d'autres établissements publics (Office français de la biodiversité, "
                                       "auparavant Agence française pour la biodiversité et Office national de la chasse et de "
                                       "la faune sauvage ; établissement public du Marais poitevin), fixée "
                                       "par la loi ; hors plafond des dépenses d'intervention",
            "autorisations_engagement": "engagements juridiques pris dans l'année (aides attribuées, dépenses "
                                        "propres), par destination ; « sous plafond » : programme d'intervention ; "
                                        "« hors plafond » : crédits fléchés de l'État (France Relance, Fonds vert, "
                                        "fuites d'eau potable) et contributions",
        },
        "plafond_redevances": {
            "valeurs_meur": {str(a): v for a, v in sorted(PLAFONDS.items())},
            "citation": PLAFOND_CITATION + " ; " + " ; ".join(PLAFOND_CITATIONS_COMPLEMENTAIRES),
            "source": SOURCES["eau_jaune_agences_eau_plf2026"]["titre"] + ", note de bas de page de la partie "
                                                                          "« Recettes »",
            "lecture": "plafond des redevances des six agences ; au-delà, l'encaissement est reversé au budget "
                       "général (ligne écrêtement) ; le calcul porte sur une période d'encaissement propre "
                       "(fin décembre à fin décembre) et sur des montants retraités : il ne se refait pas avec les "
                       "lignes du tableau",
        },
        "agences": agences,
        "controles": controles,
        "somme_six_agences": somme_agences,
        "ecarts_editions": ecarts,
        "valeurs_comparees_editions": compares,
        "regle_ecarts": f"écart publié quand les deux éditions donnent une valeur et diffèrent d'au moins "
                        f"{ECART_EDITIONS_MIN} M€ (en dessous : arrondi) ; la valeur publiée dans `agences` est "
                        f"celle de l'édition 2026",
    }
    return doc, j26["lignes"]


# --- ADEME -------------------------------------------------------------------------------------------------------------

FONDS_ADEME = [("fonds_chaleur", "Fonds chaleur", re.compile(r"fonds chaleur")),
               ("fonds_economie_circulaire", "Fonds économie circulaire", re.compile(r"fonds economie circulaire"))]


def produire_ademe(regions: dict, collecte_le: str) -> dict:
    lignes = []
    for f in fichiers_source("subv_ademe_aides"):
        for r in lire_csv(f):
            d = (r.get("dateconvention") or "").strip()
            a = int(d[:4]) if re.match(r"^\d{4}", d) else None
            dep = (r.get("_siret_infos._infos_commune.code_departement") or "").strip().upper()
            dep = dep.zfill(2) if dep.isdigit() and len(dep) < 2 else dep
            lignes.append((a, montant(r.get("montant")), regions.get(dep), (r.get("dispositifaide") or "").strip()))
    annees = sorted({a for a, *_ in lignes if a is not None})

    def agrege(sel):
        out = {"montant_eur": 0.0, "conventions": 0, "lignes_montant_non_communique": 0}
        for _, m, _, _ in sel:
            out["conventions"] += 1
            if m is None:
                out["lignes_montant_non_communique"] += 1
            else:
                out["montant_eur"] += m
        out["montant_eur"] = round(out["montant_eur"], 2)
        return out

    par_annee = [{"annee": a, **agrege([l for l in lignes if l[0] == a])} for a in annees]
    sans_annee = [l for l in lignes if l[0] is None]
    regs = sorted({l[2] for l in lignes if l[2]}, key=lambda r: r[0])
    par_region = []
    for code, nom in regs:
        sel = [l for l in lignes if l[2] == (code, nom)]
        par_region.append({"region": code, "nom": nom, **agrege(sel),
                           "par_annee": [{"annee": a, **agrege([l for l in sel if l[0] == a])} for a in annees]})
    non_loc = [l for l in lignes if not l[2]]
    disp = {}
    for l in lignes:
        disp.setdefault(l[3] or "(dispositif non renseigné)", []).append(l)
    par_disp, autres = [], []
    for nom in sorted(disp, key=norm):
        sel = disp[nom]
        if len(sel) < SEUIL_DISPOSITIF:
            autres += sel
            continue
        par_disp.append({"dispositif": nom, **agrege(sel),
                         "par_annee": {str(a): round(sum(m for x, m, _, _ in sel if x == a and m is not None), 2)
                                       for a in annees if any(x == a for x, *_ in sel)}})
    fonds = []
    for fid, nom, motif in FONDS_ADEME:
        noms = [n for n in sorted(disp, key=norm) if motif.search(norm(n))]
        sel = [l for n in noms for l in disp[n]]
        fonds.append({"id": fid, "nom": nom, "regle": f"dispositifs dont le libellé contient « {nom} »",
                      "dispositifs": noms, **agrege(sel),
                      "par_annee": [{"annee": a, **agrege([l for l in sel if l[0] == a])} for a in annees
                                    if any(l[0] == a for l in sel)]})
    total = agrege(lignes)
    return {
        "millesime": f"conventions signées de {annees[0]} à {annees[-1]}",
        "source": SOURCES["subv_ademe_aides"]["titre"], "source_url": SOURCES["subv_ademe_aides"]["page"],
        "collecte_le": collecte_le, "unite": "euros (montants attribués par convention)",
        "total": total, "conventions_sans_annee": len(sans_annee),
        "par_annee": par_annee,
        "par_region": par_region,
        "non_localise": {**agrege(non_loc), "lecture": "conventions sans département d'établissement dans la source"},
        "par_dispositif": par_disp,
        "par_dispositif_autres": {**agrege(autres), "dispositifs": len({l[3] for l in autres}),
                                  "regle": f"dispositifs suivis par moins de {SEUIL_DISPOSITIF} conventions, regroupés"},
        "fonds_nommes": fonds,
        "avertissement": "Les libellés de dispositif ne portent pas tous le nom du fonds qui les finance (par exemple "
                         "les contrats de chaleur renouvelable) : `fonds_nommes` ne mesure pas l'ensemble du Fonds "
                         "chaleur ni du Fonds économie circulaire.",
        "liens": [l for l in LIENS if l["fichier"] in ("subventions/attribuants/subv_ademe_aides.json",
                                                       "programmes/181.json")],
    }


# --- Fonds vert --------------------------------------------------------------------------------------------------------

INSTRUCTEURS = {"": None, "ademe": "ademe", "agence de l'eau": "agence_eau_non_precisee",
                "aeag": "adour_garonne", "aeap": "artois_picardie", "aelb": "loire_bretagne", "aerm": "rhin_meuse",
                "aermc": "rhone_mediterranee_corse", "aesn": "seine_normandie"}


def _instructeur(v: str) -> str | None:
    n = norm(v)
    if n in INSTRUCTEURS:
        return INSTRUCTEURS[n]
    for aid, _, titre in AGENCES:
        if norm(titre) in n:
            return aid
    return "autre_" + slug(v)


def produire_fonds_vert(regions: dict, agences_doc: dict, collecte_le: str) -> dict:
    noms_regions = {norm(nom): code for code, nom in set(regions.values())}
    lignes = []
    for f in fichiers_source("subv_fonds_vert"):
        m = re.search(r"(20\d\d)", f.name)
        annee, prog = int(m.group(1)), ("113" if "p113" in f.name.lower() else "380")
        for r in lire_csv(f):
            reg = (r.get("nom_region") or "").strip() or None
            fj = r.get("forme_juridique_beneficiaire")
            demarche = (r.get("demarche") or r.get("nom_demarche_ds") or r.get("source") or "").strip() or None
            lignes.append({"annee": annee, "programme": prog, "montant": montant(r.get("montant_engage")),
                           "region": reg, "instructeur": _instructeur(r.get("operateur") or ""),
                           "instructeur_publie": "operateur" in r,
                           "forme": None if fj is None else (fj.strip() or "(non renseignée)"),
                           "forme_publiee": fj is not None, "demarche": demarche})
    annees = sorted({l["annee"] for l in lignes})

    def agrege(sel):
        ms = [l["montant"] for l in sel if l["montant"] is not None]
        return {"montant_eur": round(sum(ms), 2), "projets": len(sel),
                "lignes_montant_non_communique": len(sel) - len(ms)}

    par_annee = [{"annee": a, "programme": p, **agrege([l for l in lignes if l["annee"] == a and l["programme"] == p])}
                 for a in annees for p in ("380", "113") if any(l["annee"] == a and l["programme"] == p for l in lignes)]
    par_region = []
    for nom in sorted({l["region"] for l in lignes if l["region"]}, key=norm):
        sel = [l for l in lignes if l["region"] == nom]
        par_region.append({"nom": nom, "region": noms_regions.get(norm(nom)), **agrege(sel),
                           "par_annee": [{"annee": a, **agrege([l for l in sel if l["annee"] == a])} for a in annees
                                         if any(l["annee"] == a for l in sel)]})
    noms_instr = {"ademe": "ADEME", "agence_eau_non_precisee": "Agence de l'eau (agence non précisée par la source)"} \
        | {aid: nom for aid, nom, _ in AGENCES}
    par_instr = []
    for a in annees:
        sel = [l for l in lignes if l["annee"] == a]
        cles = sorted({l["instructeur"] for l in sel if l["instructeur"]})
        if not any(l["instructeur_publie"] for l in sel):
            par_instr.append({"annee": a, "publie": False, "non_renseigne": agrege(sel), "instructeurs": [],
                              "note": "colonne « opérateur » absente du fichier de cette année"})
            continue
        par_instr.append({"annee": a, "publie": True, "non_renseigne": agrege([l for l in sel if not l["instructeur"]]),
                          "instructeurs": [{"id": c, "nom": noms_instr.get(c, c[len("autre_"):].upper()),
                                            **agrege([l for l in sel if l["instructeur"] == c])} for c in cles]})
    for x in par_instr:
        for i in x["instructeurs"]:
            if i["id"].startswith("autre_"):
                i["nom"] += " (sigle publié par la source, non développé)"
    par_forme = []
    for a in annees:
        for p in ("380", "113"):
            sel = [l for l in lignes if l["annee"] == a and l["programme"] == p]
            if not sel:
                continue
            if not any(l["forme_publiee"] for l in sel):
                par_forme.append({"annee": a, "programme": p, "publie": False, "formes": None,
                                  "note": "forme juridique non publiée dans le fichier de cette année"})
                continue
            formes = sorted({l["forme"] for l in sel}, key=norm)
            par_forme.append({"annee": a, "programme": p, "publie": True,
                              "formes": [{"forme_juridique": fo, **agrege([l for l in sel if l["forme"] == fo])}
                                         for fo in formes]})
    par_demarche = []
    for a in annees:
        sel = [l for l in lignes if l["annee"] == a]
        ds = sorted({l["demarche"] or "(non renseignée)" for l in sel}, key=norm)
        par_demarche.append({"annee": a, "demarches": [
            {"demarche": d, **agrege([l for l in sel if (l["demarche"] or "(non renseignée)") == d])} for d in ds]})
    # Fonds vert instruit par les agences de l'eau : liste data.gouv.fr face aux lignes « Fonds vert » du jaune
    comparaison = []
    jaune = {ag["id"]: ag for ag in agences_doc["agences"]}
    for aid in ["ensemble"] + [a for a, _, _ in AGENCES]:
        lignes_fv = [l for l in jaune[aid]["autorisations_engagement"]["lignes"]
                     if l["bloc"] == "hors_plafond" and norm(l["libelle"]) == "fonds vert"]
        for a in annees:
            if aid == "ensemble":
                sel = [l for l in lignes if l["annee"] == a and l["instructeur"] and
                       (l["instructeur"] in {x for x, _, _ in AGENCES} or
                        l["instructeur"] == "agence_eau_non_precisee")]
            else:
                sel = [l for l in lignes if l["annee"] == a and l["instructeur"] == aid]
            ae = lignes_fv[0]["valeurs_meur"].get(str(a)) if lignes_fv else None
            liste = agrege(sel)
            publie = any(l["instructeur_publie"] for l in lignes if l["annee"] == a)
            comparaison.append({"agence": aid, "annee": a, "colonne_operateur_publiee": publie,
                                "liste_fonds_vert_eur": liste["montant_eur"] if liste["projets"] else None,
                                "liste_projets": liste["projets"] if publie else None,
                                "jaune_ae_fonds_vert_meur": ae})
    return {
        "millesime": f"montants engagés en {annees[0]} à {annees[-1]}",
        "source": SOURCES["subv_fonds_vert"]["titre"], "source_url": SOURCES["subv_fonds_vert"]["page"],
        "collecte_le": collecte_le, "unite": "euros (montants engagés)",
        "total": agrege(lignes),
        "par_annee": par_annee, "par_region": par_region,
        "region_non_publiee": agrege([l for l in lignes if not l["region"]]),
        "par_instructeur": par_instr,
        "par_forme_juridique": par_forme, "par_demarche": par_demarche,
        "agences_eau": {
            "comparaison": comparaison,
            "lecture": "Deux publications du même dispositif côte à côte, jamais additionnées : la liste du Fonds vert "
                       "(montants engagés par projet, colonne « opérateur ») et la ligne « Fonds vert » des "
                       "autorisations d'engagement de chaque agence dans le jaune (en millions d'euros). La liste "
                       "nomme souvent « Agence de l'eau » sans dire laquelle : ces projets ne comptent que dans la "
                       "ligne « ensemble ».",
        },
        "laureats": {"fichier": "subventions/attribuants/subv_fonds_vert.json", "chemin": "beneficiaires.top",
                     "lecture": "lauréats nommés quand ils sont des personnes morales (catégorie juridique SIRENE), "
                                "toutes années ; les autres sont agrégés dans cette vue de subventions/"},
        "liens": [l for l in LIENS if l["fichier"] in ("programmes/380.json", "programmes/113.json",
                                                       "subventions/attribuants/subv_fonds_vert.json")],
    }


# --- Production --------------------------------------------------------------------------------------------------------

def produire(sortie: Path = SORTIE) -> dict:
    collecte_le = date_sources("eau_environnement", "subventions")
    regions = regions_par_departement()
    agences_doc, _ = produire_agences(collecte_le)
    ademe = produire_ademe(regions, collecte_le)
    fv = produire_fonds_vert(regions, agences_doc, collecte_le)
    ens = agences_doc["agences"][0]
    red = {l["id"]: l for l in ens["redevances"]["lignes"]}
    derniere = str(ens["redevances"]["annees"][-1])
    index = {
        "millesime": f"agences de l'eau : exécution 2019 à {derniere} ; ADEME : {ademe['millesime']} ; Fonds vert : "
                     f"{fv['millesime']}",
        "source": "annexes au projet de loi de finances « Agences de l'eau » (2025, 2026) ; data.ademe.fr ; "
                  "data.gouv.fr (Fonds vert)",
        "collecte_le": collecte_le,
        "fichiers": [
            {"id": "agences_eau", "fichier": "eau_environnement/agences_eau.json",
             "lecture": "six agences de l'eau et ensemble : redevances, écrêtement, autorisations d'engagement"},
            {"id": "ademe", "fichier": "eau_environnement/ademe.json",
             "lecture": "aides de l'ADEME par année, région, dispositif"},
            {"id": "fonds_vert", "fichier": "eau_environnement/fonds_vert.json",
             "lecture": "Fonds vert par année, région, service instructeur, forme juridique, démarche"},
        ],
        "chiffres": {
            "annee_agences": int(derniere),
            "redevances_encaissees_meur": red["redevances_encaissees"]["valeurs_meur"][derniere],
            "ecretement_meur": red["ecretement"]["valeurs_meur"][derniere],
            "plafond_redevances_meur": agences_doc["plafond_redevances"]["valeurs_meur"].get(derniere),
            "contribution_operateurs_meur": (ens["contribution_operateurs_meur"] or {}).get(derniere),
            "ademe_total_eur": ademe["total"]["montant_eur"], "fonds_vert_total_eur": fv["total"]["montant_eur"],
            "note": "chiffres de sources différentes, à ne pas additionner",
        },
        "sources": {k: v for k, v in sorted(SOURCES.items())},
        "liens": LIENS,
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "limites": LIMITES,
        "regle": " ".join(REGLES),
    }
    dump(sortie / "agences_eau.json", agences_doc)
    dump(sortie / "ademe.json", ademe)
    dump(sortie / "fonds_vert.json", fv)
    dump(sortie / "index.json", index)
    print(f"eau_environnement : redevances {derniere} {index['chiffres']['redevances_encaissees_meur']} M€, "
          f"{len(agences_doc['ecarts_editions'])} écarts entre éditions, ADEME {ademe['total']['montant_eur'] / 1e9:.2f} "
          f"Md€, Fonds vert {fv['total']['montant_eur'] / 1e9:.2f} Md€")
    return index


# --- Collecte ----------------------------------------------------------------------------------------------------------

def collecter() -> int:
    """Collecte par collecte/collecte.py (manifeste, reprises, zone restreinte ; aucun contournement d'un refus)."""
    sys.path.insert(0, str(ROOT / "collecte"))
    import collecte
    return collecte.main(list(SOURCES))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter()
    if a.etape in ("produire", "tout"):
        produire(a.sortie)


if __name__ == "__main__":
    main()
