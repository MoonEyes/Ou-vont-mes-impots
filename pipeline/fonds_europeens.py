"""Fonds européens en France : ce que l'Union européenne finance par les fonds structurels et d'investissement.

Programmations 2014-2020 et 2021-2027 : FEDER, FSE et FSE+, Initiative pour l'emploi des jeunes, FEADER (développement
rural ; aucune aide individuelle de la PAC, aucun exploitant nommé), FEAMP et FEAMPA, Fonds pour une transition juste ;
Facilité pour la reprise et la résilience (FRR) telle que publiée par Eurostat. Montants de l'UE et cofinancements
nationaux, par programme, région, fonds, thème et année ; listes d'opérations publiées par six autorités de gestion
(bénéficiaire nommé seulement si sa catégorie juridique SIRENE est celle d'une personne morale).

Ce que la France verse au budget de l'UE, les retours par rubrique et les bénéficiaires nommés de Kohesio, du FTS et
d'Horizon Europe sont produits par pipeline/ue.py (site/data/ue/) : cet axe y renvoie par des liens, sans les recopier.

Entrées (collecte/catalogue.json, entrées fe_*, collectées par collecte/collecte.py, tracées dans data/lake/manifest.json) :
  data/lake/europe/fe_cohesion_*.json          jeux cohesiondata.ec.europa.eu filtrés sur la France (API SODA, CC0)
  data/lake/europe/fe_eurostat_frr_*.json      Eurostat gov_rrf_fa et gov_rrf_use (CC BY 4.0)
  data/lake/_restreint/europe/fe_ops_*         listes d'opérations des autorités de gestion (noms de bénéficiaires bruts)
  data/lake/_cache/local/sirene_unite_legale.parquet   stock SIRENE des unités légales (téléchargé par pipeline/local.py)
Cache : data/lake/_cache/fonds_europeens/rapprochement.json (empreintes des noms, jamais un nom de personne physique).

Sorties (site/data/fonds_europeens/, contrat docs/contrat_interface.md, schémas docs/schemas/fonds_europeens_*.json) :
  index.json, programmes.json, themes.json, regions.json, annees.json, frr.json,
  operations.json (index des listes), operations/<liste>.json

Commandes :
  python pipeline/fonds_europeens.py collecter   # réseau (collecte/collecte.py ; un refus 401/403/429 n'est jamais
                                                 # contourné), puis rapprochement SIRENE local (resoudre)
  python pipeline/fonds_europeens.py resoudre    # sans réseau : noms et SIRET des listes -> SIREN, catégorie juridique
  python pipeline/fonds_europeens.py produire [--sortie DOSSIER]   # sans réseau, sorties reproductibles
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
MANIFESTE = LAKE / "manifest.json"
CACHE = LAKE / "_cache" / "fonds_europeens"
CACHE_RAPPROCHEMENT = CACHE / "rapprochement.json"
STOCK_SIRENE = LAKE / "_cache" / "local" / "sirene_unite_legale.parquet"
SORTIE = ROOT / "site" / "data" / "fonds_europeens"
MAX_OCTETS = 1_000_000

# --- Sources --------------------------------------------------------------------------------------------------------

COHESION = "https://cohesiondata.ec.europa.eu"
JEUX = {   # identifiant du catalogue -> (jeu cohesiondata, titre court)
    "fe_cohesion_1420_prevu": ("e4v6-qrrq", "ESIF 2014-2020 Finances Planned Details"),
    "fe_cohesion_1420_execution": ("99js-gm52", "ESIF 2014-2020 Finance Implementation Details"),
    "fe_cohesion_1420_paiements": ("gayr-92qh", "ESIF 2014-2020 EU payments (daily update) timeseries"),
    "fe_cohesion_1420_plans_annuels": ("rmer-4wcy", "ESIF 2014-2020 Financial plans (daily update)"),
    "fe_cohesion_2127_prevu": ("hgyj-gyin", "2021-2027 Planned finances detailed (categorisation, multi funds)"),
    "fe_cohesion_2127_execution": ("3git-md5z", "2021-2027 Finances Detailed Planned vs Implemented (timeseries)"),
    "fe_cohesion_2127_paiements": ("pbbz-hmfu", "2021-2027 EU payment details (timeseries)"),
    "fe_cohesion_2127_plans_annuels": ("9qee-iv7c", "2021-2027 Financial Plan details by year (All CPR funds)"),
    "fe_cohesion_feader_2327": ("7wr2-9vpr", "2023-2027 EU Payments by MS - EAFRD"),
    "fe_cohesion_psp_2327": ("vvmb-dsbj", "2023-2027 - CAP specific objectives"),
    "fe_cohesion_programmes": ("f5vn-zy5i", "Programme Lookup Table 14-20 + 21-27"),
}
LICENCE_COHESION = "CC0 1.0 (Commission européenne)"
EUROSTAT = {"fe_eurostat_frr_flux": "gov_rrf_fa", "fe_eurostat_frr_emplois": "gov_rrf_use"}

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "trouvailles": [
        {"nom": "Cohesion Open Data Platform (API SODA) : jeux e4v6-qrrq, 99js-gm52, gayr-92qh, rmer-4wcy, hgyj-gyin, "
                "3git-md5z, pbbz-hmfu, 9qee-iv7c, 7wr2-9vpr, vvmb-dsbj, f5vn-zy5i", "url": COHESION,
         "verdict": "réutilisable tel quel", "licence": "CC0 1.0 (Commission européenne)",
         "mise_a_jour": "données mises à jour entre le 2026-09-23 et le 2026-11-17 selon le jeu"},
        {"nom": "Eurostat gov_rrf_fa et gov_rrf_use (facilité pour la reprise et la résilience)",
         "url": "https://ec.europa.eu/eurostat/databrowser/view/gov_rrf_fa/default/table",
         "verdict": "réutilisable tel quel", "licence": "CC BY 4.0 (Eurostat)", "mise_a_jour": "2026-11-10"},
        {"nom": "Listes d'opérations des régions Bretagne, Pays de la Loire, Normandie, Île-de-France et La Réunion "
                "(data.gouv.fr et portails régionaux)", "url": "https://www.data.gouv.fr/fr/datasets/?q=FEDER",
         "verdict": "à adapter", "licence": "Licence Ouverte 2.0 ; ODbL (Pays de la Loire)",
         "mise_a_jour": "listes publiées entre le 2022-05-24 et le 2026-06-16"},
        {"nom": "collecte/collecte.py, pipeline/sirene.py (personne_morale), pipeline/local.py (objet_publiable, stock "
                "SIRENE), pipeline/ue.py (jetons de nom), pipeline/transform.py (jsonstat_records), dépôt du projet",
         "url": "pipeline/ue.py", "verdict": "réutilisable tel quel", "licence": "MIT (ce dépôt)",
         "mise_a_jour": "2026-11-18"},
        {"nom": "gunout/Dashboard-FEDER_Europe-DROM-COM (tableaux de bord Streamlit sur cohesiondata, outre-mer)",
         "url": "https://github.com/gunout/Dashboard-FEDER_Europe-DROM-COM", "verdict": "inspiration seulement",
         "licence": "MIT", "mise_a_jour": "2026-09-23 (scores, prévisions et classements : non repris)"},
        {"nom": "echapelier/eu-cohesionpolicy (graphiques sur les fonds européens en France 2014-2020)",
         "url": "https://github.com/echapelier/eu-cohesionpolicy", "verdict": "inspiration seulement",
         "licence": "aucune licence déclarée (non réutilisable)", "mise_a_jour": "2021-03-01"},
        {"nom": "os-data/eu-structural-funds (listes de bénéficiaires 2007-2013, Subsidystories)",
         "url": "https://github.com/os-data/eu-structural-funds", "verdict": "inspiration seulement",
         "licence": "aucune licence déclarée sur GitHub", "mise_a_jour": "2023-05-31 (période 2007-2013, hors champ)"},
        {"nom": "clementlefevre/Kohesio (exports Kohesio, déjà repris par pipeline/ue.py)",
         "url": "https://github.com/clementlefevre/Kohesio", "verdict": "inspiration seulement", "licence": "MIT",
         "mise_a_jour": "2026-05-14"},
    ],
}

INACCESSIBLES = [
    {"source": "Europe en France (europe-en-france.gouv.fr) : listes des opérations et pages des programmes",
     "url": "https://www.europe-en-france.gouv.fr/fr",
     "constat": "page de vérification anti-robot (calcul de preuve de travail en JavaScript) renvoyée à toute requête "
                "automatique le 18/11/2026 ; non contourné",
     "effet": "listes d'opérations des autres autorités de gestion non reprises ; les bénéficiaires nommés de toutes "
              "les régions restent consultables dans ue/beneficiaires (Kohesio)"},
    {"source": "Tableau de bord de la facilité pour la reprise et la résilience (Commission, recovery-and-resilience-"
               "scoreboard)", "url": "https://ec.europa.eu/economy_finance/recovery-and-resilience-scoreboard/",
     "constat": "application Qlik sans fichier téléchargeable (versements, cent plus grands bénéficiaires finaux) ; "
                "non repris",
     "effet": "FRR décrite par les tables Eurostat (fonds reçus et emploi des fonds par année), sans bénéficiaires"},
]

# --- Nomenclatures ------------------------------------------------------------------------------------------------

FONDS = {  # code de la source -> (code publié, libellé)
    "ERDF": ("FEDER", "Fonds européen de développement régional (FEDER)"),
    "ESF": ("FSE", "Fonds social européen (FSE)"),
    "ESF+": ("FSE+", "Fonds social européen plus (FSE+)"),
    "YEI": ("IEJ", "Initiative pour l'emploi des jeunes (IEJ)"),
    "EAFRD": ("FEADER", "Fonds européen agricole pour le développement rural (FEADER)"),
    "EMFF": ("FEAMP", "Fonds européen pour les affaires maritimes et la pêche (FEAMP)"),
    "EMFAF": ("FEAMPA", "Fonds européen pour les affaires maritimes, la pêche et l'aquaculture (FEAMPA)"),
    "JTF": ("FTJ", "Fonds pour une transition juste (FTJ)"),
    "CF": ("FC", "Fonds de cohésion"),
}
ORDRE_FONDS = ["FEDER", "FSE", "FSE+", "IEJ", "FTJ", "FEADER", "FEAMP", "FEAMPA", "FC"]
HORS_PERIMETRE = {
    "FEAD": ("Fonds européen d'aide aux plus démunis (FEAD)",
             "fonds régi par un règlement distinct en 2014-2020, intégré au FSE+ en 2021-2027 (objectif spécifique de "
             "lutte contre la privation matérielle, repris ici avec le FSE+)"),
    "AMIF": ("Fonds Asile, migration et intégration (AMIF)",
             "fonds des affaires intérieures, présent dans les mêmes jeux mais hors fonds structurels et d'investissement"),
    "BMVI": ("Instrument de soutien financier à la gestion des frontières et à la politique des visas (BMVI)",
             "fonds des affaires intérieures, présent dans les mêmes jeux mais hors fonds structurels et d'investissement"),
    "ISF": ("Fonds pour la sécurité intérieure (ISF)",
            "fonds des affaires intérieures, présent dans les mêmes jeux mais hors fonds structurels et d'investissement"),
}
COMPOSANTES_IEJ = {"YEI ESF Matching Component", "YEI Specific Allocation"}  # détail de « YEI » : jamais additionnés

PERIODES = ["2014-2020", "2021-2027", "2023-2027"]   # 2023-2027 : FEADER du plan stratégique PAC


def periode_de(cci: str) -> str:
    return "2014-2020" if cci.startswith("2014") else "2023-2027" if cci.startswith("2023") else "2021-2027"

OBJECTIFS_THEMATIQUES = {  # 2014-2020, règlement (UE) n° 1303/2013, article 9 (libellés courts)
    "1": "Recherche, développement technologique et innovation",
    "2": "Technologies de l'information et de la communication",
    "3": "Compétitivité des PME, du secteur agricole et du secteur de la pêche",
    "4": "Économie à faible émission de carbone",
    "5": "Adaptation au changement climatique, prévention et gestion des risques",
    "6": "Protection de l'environnement et utilisation rationnelle des ressources",
    "7": "Transport durable et infrastructures de réseaux",
    "8": "Emploi durable et de qualité, mobilité de la main-d'œuvre",
    "9": "Inclusion sociale, lutte contre la pauvreté et les discriminations",
    "10": "Éducation, formation et formation professionnelle",
    "11": "Capacités institutionnelles et efficacité de l'administration publique",
    "12": "Dotation supplémentaire des régions ultrapériphériques et faiblement peuplées",
    "13": "Soutien à la réparation des dommages de la crise et à la résilience (REACT-EU)",
    "TA": "Assistance technique",
    "DM": "Mesures du FEADER interrompues",
    "MULTI": "Plusieurs objectifs thématiques",
}
OBJECTIFS_STRATEGIQUES = {  # 2021-2027, règlement (UE) 2021/1060, article 5
    "1": "Une Europe plus compétitive et plus intelligente",
    "2": "Une Europe plus verte",
    "3": "Une Europe plus connectée",
    "4": "Une Europe plus sociale et inclusive",
    "5": "Une Europe plus proche des citoyens",
    "8": "Objectif spécifique du Fonds pour une transition juste",
    "TA": "Assistance technique",
}
OBJECTIFS_SPECIFIQUES = {  # libellés courts traduits par le projet depuis les libellés courts de la Commission
    "RSO1.1": "Recherche et innovation", "RSO1.2": "Numérisation au bénéfice des citoyens, des entreprises et des "
    "administrations", "RSO1.3": "Croissance et compétitivité des PME", "RSO1.4": "Compétences pour la "
    "spécialisation intelligente et la transition", "RSO1.5": "Connectivité numérique",
    "RSO1.6": "Développement ou fabrication de technologies critiques",
    "RSO1.7": "Capacités industrielles de défense",
    "RSO2.1": "Efficacité énergétique", "RSO2.2": "Énergies renouvelables", "RSO2.3": "Systèmes énergétiques "
    "intelligents", "RSO2.4": "Adaptation au changement climatique", "RSO2.5": "Gestion durable de l'eau",
    "RSO2.6": "Économie circulaire", "RSO2.7": "Protection de la nature et biodiversité",
    "RSO2.8": "Mobilité urbaine durable", "RSO2.9": "Technologies propres",
    "RSO2.10": "Reconstruction après des catastrophes naturelles", "RSO2.11": "Logement abordable",
    "RSO3.1": "Réseau transeuropéen de transport durable", "RSO3.2": "Transport durable",
    "RSO3.3": "Mobilité militaire", "RSO4.1": "Marché du travail et emploi (infrastructures)",
    "RSO4.2": "Infrastructures d'éducation et de formation", "RSO4.3": "Intégration des communautés marginalisées",
    "RSO4.4": "Intégration des ressortissants de pays tiers", "RSO4.5": "Accès aux soins de santé",
    "RSO4.6": "Culture et tourisme durable", "RSO4.7": "Logement abordable",
    "RSO5.1": "Développement intégré des zones urbaines", "RSO5.2": "Développement intégré des zones rurales et côtières",
    "ESO4.1": "Accès à l'emploi et mesures d'activation", "ESO4.2": "Institutions et services du marché du travail",
    "ESO4.3": "Participation équilibrée des femmes et des hommes au marché du travail",
    "ESO4.4": "Adaptation des travailleurs et des entreprises au changement",
    "ESO4.5": "Amélioration des systèmes d'éducation et de formation",
    "ESO4.6": "Éducation et formation inclusives et de qualité",
    "ESO4.7": "Apprentissage tout au long de la vie et transitions professionnelles",
    "ESO4.8": "Inclusion active et employabilité", "ESO4.9": "Intégration des ressortissants de pays tiers",
    "ESO4.10": "Intégration des communautés marginalisées",
    "ESO4.11": "Accès égal à des services sociaux et de santé de qualité",
    "ESO4.12": "Intégration sociale des personnes exposées au risque de pauvreté",
    "ESO4.13": "Lutte contre la privation matérielle", "JSO8.1": "Fonds pour une transition juste",
    "MSO1.1": "Activités de pêche durables", "MSO1.2": "Remplacement et modernisation des moteurs",
    "MSO1.3": "Arrêt définitif ou temporaire des activités de pêche", "MSO1.4": "Contrôle et collecte de données",
    "MSO1.5": "Régions ultrapériphériques (pêche et aquaculture)",
    "MSO1.6": "Protection et restauration de la biodiversité aquatique", "MSO2.1": "Aquaculture durable",
    "MSO2.2": "Commercialisation et transformation des produits de la pêche et de l'aquaculture",
    "MSO3.1": "Économie bleue durable", "MSO4.1": "Gouvernance internationale des océans",
}
MESURES_FEADER = {  # règlement (UE) n° 1305/2013 et règlement d'exécution n° 808/2014 (libellés courts)
    "M01": "Transfert de connaissances et actions d'information", "M02": "Services de conseil",
    "M03": "Systèmes de qualité des produits agricoles et des denrées alimentaires", "M04": "Investissements physiques",
    "M05": "Reconstitution du potentiel de production agricole", "M06": "Développement des exploitations agricoles et "
    "des entreprises", "M07": "Services de base et rénovation des villages en zone rurale",
    "M08": "Investissements dans les zones forestières", "M09": "Groupements et organisations de producteurs",
    "M10": "Agroenvironnement et climat", "M11": "Agriculture biologique",
    "M12": "Paiements Natura 2000 et directive-cadre sur l'eau",
    "M13": "Zones soumises à des contraintes naturelles ou spécifiques", "M14": "Bien-être des animaux",
    "M15": "Services forestiers, environnementaux et climatiques", "M16": "Coopération", "M17": "Gestion des risques",
    "M19": "LEADER (développement local mené par les acteurs locaux)", "M20": "Assistance technique",
    "M21": "Aide temporaire exceptionnelle liée à la COVID-19",
    "M22": "Aide temporaire exceptionnelle liée à l'invasion de l'Ukraine",
    "M23": "Aide exceptionnelle à la suite de catastrophes naturelles",
}

REGIONS = {
    "01": "Guadeloupe", "02": "Martinique", "03": "Guyane", "04": "La Réunion", "06": "Mayotte",
    "11": "Île-de-France", "24": "Centre-Val de Loire", "27": "Bourgogne-Franche-Comté", "28": "Normandie",
    "32": "Hauts-de-France", "44": "Grand Est", "52": "Pays de la Loire", "53": "Bretagne",
    "75": "Nouvelle-Aquitaine", "76": "Occitanie", "84": "Auvergne-Rhône-Alpes", "93": "Provence-Alpes-Côte d'Azur",
    "94": "Corse", "977": "Saint-Martin",
}
GROUPES = {"national": "Programmes nationaux", "interregional": "Programmes interrégionaux (massifs et fleuves)"}
# Intitulé du programme -> région (codes Insee des régions depuis 2016 ; Saint-Martin : collectivité d'outre-mer 977).
# Les programmes 2014-2020 portent sur les régions d'avant 2016 : elles sont rattachées à la région qui les contient.
MOTIFS_REGIONS = [
    (r"\binterregional\b|interr[ée]gional", "interregional"),
    (r"guadeloupe", "01"), (r"martinique", "02"), (r"guyane", "03"), (r"r[ée]union", "04"), (r"mayotte", "06"),
    (r"\b(?:saint|st)[- ]martin\b", "977"),
    (r"[îi]le-de-france", "11"), (r"\bcentre\b", "24"), (r"bourgogne|franche-comt", "27"), (r"normandie", "28"),
    (r"nord-pas[- ]de[- ]calais|picardie|hauts[- ]de[- ]france", "32"),
    (r"champagne|lorraine|alsace|grand[- ]est", "44"), (r"pays de la loire", "52"), (r"bretagne", "53"),
    (r"aquitaine|limousin|poitou", "75"), (r"languedoc|midi-pyr|occitanie", "76"),
    (r"auvergne|rh[ôo]?ne-alpes|rhne-alpes", "84"), (r"provence|\bsud\b", "93"), (r"\bcorse\b", "94"),
]
ANCIENNES_REGIONS = ["Alsace", "Aquitaine", "Auvergne", "Basse-Normandie", "Bourgogne", "Bretagne", "Centre",
                     "Champagne-Ardenne", "Corse", "Franche-Comté", "Guadeloupe", "Guyane", "Haute-Normandie",
                     "Île-de-France", "Languedoc-Roussillon", "Limousin", "Lorraine", "Martinique", "Mayotte",
                     "Midi-Pyrénées", "Nord-Pas de Calais", "Pays de la Loire", "Picardie", "Poitou-Charentes",
                     "Provence-Alpes-Côte d'Azur", "Réunion", "Rhône-Alpes"]

# --- Outils ----------------------------------------------------------------------------------------------------------


def cents(v) -> int:
    """Montant de la source -> centimes entiers (sommes exactes et indépendantes de l'ordre). Vide -> 0."""
    if v is None or v == "" or v == "VOID":
        return 0
    try:
        return round(float(str(v).replace(" ", "").replace(",", ".")) * 100)
    except ValueError:
        return 0


def eur(c: int | None) -> float | None:
    return None if c is None else round(c / 100, 2)


def propre(v) -> str:
    if v is None:
        return ""
    s = unicodedata.normalize("NFC", str(v)).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def ascii_min(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


def manifeste() -> dict:
    try:
        return json.loads(MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fichiers(sid: str) -> list[Path]:
    """Fichiers collectés d'une source (manifeste), présents sur disque, dans l'ordre du manifeste."""
    e = manifeste().get(sid) or {}
    return [ROOT / f["chemin"] for f in e.get("fichiers", []) if (ROOT / f["chemin"]).exists()]


def entree(sid: str) -> dict:
    return manifeste().get(sid) or {}


def lire_json_source(sid: str):
    fs = fichiers(sid)
    if not fs:
        raise SystemExit(f"source {sid} absente de data/lake : lancer `python pipeline/fonds_europeens.py collecter`")
    return json.loads(fs[0].read_text(encoding="utf-8"))


def maj_jeu(jeu: str) -> str | None:
    """Date de dernière mise à jour publiée par cohesiondata (métadonnées collectées), AAAA-MM-JJ."""
    for f in fichiers("fe_cohesion_metadonnees"):
        if f.name == f"{jeu}.json":
            d = json.loads(f.read_text(encoding="utf-8"))
            t = d.get("rowsUpdatedAt") or d.get("viewLastModified")
            return datetime.fromtimestamp(int(t), timezone.utc).date().isoformat() if t else None
    return None


def url_jeu(jeu: str) -> str:
    return f"{COHESION}/d/{jeu}"


def fonds_code(f: str) -> str | None:
    return FONDS[f][0] if f in FONDS else None


def dump(chemin: Path, doc) -> int:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{chemin} dépasse 1 Mo ({n} octets) : découper")
    tmp = chemin.with_suffix(".part")
    tmp.write_text(texte + "\n", encoding="utf-8")
    tmp.replace(chemin)
    return n


# --- Référentiel des programmes ---------------------------------------------------------------------------------------


def region_du_titre(titre: str) -> str | None:
    t = ascii_min(titre).replace("ã´", "o")
    for motif, code in MOTIFS_REGIONS:
        if re.search(ascii_min(motif), t) or re.search(motif, titre.lower()):
            return code
    return None


def territoire_du_titre(titre: str) -> str | None:
    """Région d'avant 2016 (ou région actuelle) citée dans l'intitulé, pour les programmes 2014-2020."""
    t = ascii_min(titre)
    for nom in sorted(ANCIENNES_REGIONS, key=len, reverse=True):
        if ascii_min(nom) in t:
            return nom
    return None


def programmes_ref(lignes_titres: dict[str, str]) -> dict[str, dict]:
    """CCI -> {periode, titre, portee, region} ; référentiel de la Commission, complété par les titres des jeux."""
    lookup = lire_json_source("fe_cohesion_programmes")
    ref: dict[str, dict] = {}
    for r in lookup:
        cci = r.get("cci")
        if not cci or cci.startswith(("2014TC", "2021TC")):
            continue
        ref[cci] = {"titre": propre(r.get("op_short_title")).replace("CÃ´te", "Côte"), "portee": r.get("scope")}
    for cci, titre in lignes_titres.items():
        ref.setdefault(cci, {"titre": propre(titre), "portee": None})
    out = {}
    for cci, e in ref.items():
        periode = periode_de(cci)
        titre = e["titre"]
        portee = e["portee"]
        code = region_du_titre(titre)
        if code == "interregional":
            groupe, type_ = "interregional", "interrégional"
        elif portee == "National" or (code is None and re.search(r"\b(?:france|fr)\b", ascii_min(titre))):
            groupe, type_ = "national", "national"
        elif code:
            groupe, type_ = code, "régional"
        else:
            groupe, type_ = "non_rattache", "non rattaché"
        out[cci] = {"cci": cci, "periode": periode, "titre": titre, "portee": type_, "groupe": groupe,
                    "territoire": territoire_du_titre(titre) if type_ == "régional" else None}
    return out


# --- Lecture des jeux cohesiondata -----------------------------------------------------------------------------------


class Agregat:
    """Sommes en centimes par clé ; champs nommés."""

    def __init__(self):
        self.d: dict = defaultdict(lambda: defaultdict(int))

    def ajouter(self, cle, **montants):
        for k, v in montants.items():
            self.d[cle][k] += v

    def get(self, cle) -> dict:
        return self.d.get(cle, {})


def lire_1420() -> dict:
    """Montants prévus, exécution cumulée par année, paiements cumulés, plans annuels (2014-2020)."""
    prevu = lire_json_source("fe_cohesion_1420_prevu")
    execu = lire_json_source("fe_cohesion_1420_execution")
    paie = lire_json_source("fe_cohesion_1420_paiements")
    plans = lire_json_source("fe_cohesion_1420_plans_annuels")
    titres = {r["cci"]: r.get("title") or "" for r in prevu + execu + paie if r.get("cci")}
    return {"prevu": prevu, "execution": execu, "paiements": paie, "plans": plans, "titres": titres}


def lire_2127() -> dict:
    prevu = lire_json_source("fe_cohesion_2127_prevu")
    execu = lire_json_source("fe_cohesion_2127_execution")
    paie = lire_json_source("fe_cohesion_2127_paiements")
    plans = lire_json_source("fe_cohesion_2127_plans_annuels")
    titres = {}
    for r in prevu:
        titres.setdefault(r["cci"], r.get("programme_title_short") or "")
    for r in execu:
        titres.setdefault(r["cci"], r.get("programme_short_title") or "")
    for r in paie:
        titres.setdefault(r["cci"], r.get("title") or "")
    return {"prevu": prevu, "execution": execu, "paiements": paie, "plans": plans, "titres": titres}


DIMENSION = {"EMFAF": "Intervention Type"}   # sinon « Intervention Field » : une seule dimension par fonds


def dimension_retenue(r: dict) -> bool:
    return r.get("dimension_type") == DIMENSION.get(r.get("fund"), "Intervention Field")


def code_os(r: dict, champ_code: str, champ_nom: str) -> str:
    """Code d'objectif spécifique homogène (RSO1.1, ESO4.8, JSO8.1, MSO1.1)."""
    c = propre(r.get(champ_code))
    if re.match(r"^[A-Z]{3}\d", c):
        return c
    m = re.match(r"^(MSO\d+\.\d+)", propre(r.get(champ_nom)))
    if m:
        return m.group(1)
    return ("MSO" + c) if r.get("fund") == "EMFAF" and re.match(r"^\d+\.\d+$", c) else c


def cycle_date(cycle: str) -> str:
    c = str(cycle)
    return f"{c[:4]}-{c[4:6]}" if re.match(r"^\d{6}$", c) else c


# --- Agrégats par programme ----------------------------------------------------------------------------------------


def construire(ref: dict, d14: dict, d21: dict) -> dict:
    """Agrégats par (cci, fonds) : prévu, exécution (dernière date et séries), paiements (dernière année et séries)."""
    hors = defaultdict(lambda: defaultdict(int))     # (periode, fonds hors périmètre) -> montants
    prevu = Agregat()            # (cci, fonds) -> ue, nat, tot
    prevu_theme = Agregat()      # (periode, code_theme, fonds) -> ue, nat, tot
    prevu_mesure = Agregat()     # mesure FEADER -> ue, nat, tot
    exec_theme = Agregat()       # (periode, code_theme, fonds) -> decide, depense
    exec_mesure = Agregat()
    exec_ref = {}                # cci -> date de référence de la dernière exécution
    exec_fin = Agregat()         # (cci, fonds) -> prevu_tot, decide, depense (dernière date)
    exec_serie = Agregat()       # (cci, fonds, annee) -> decide, depense (cumuls)
    paie_fin = Agregat()         # (cci, fonds) -> plan_ue, pf, ip, total
    paie_serie = Agregat()       # (cci, fonds, annee) -> total (cumul)
    paie_annee_fin = {}
    plans = Agregat()            # (periode, fonds, annee) -> engagement ue
    theme_libelle_source = {}
    so_libelle_source = {}
    domaines = Agregat()         # (fonds, code domaine) -> prevu ue, tot, decide, depense, operations
    domaine_libelle = {}
    so_par_po = defaultdict(set)
    nb_ops = Agregat()           # (cci, fonds) -> operations (2021-2027, dernière date)

    # 2014-2020 : prévu
    for r in d14["prevu"]:
        f = fonds_code(r["fund"])
        ue, nat, tot = cents(r["eu_amount"]), cents(r["national_amount"]), cents(r["total_amount"])
        if f is None:
            hors[("2014-2020", r["fund"])]["prevu_ue"] += ue
            continue
        prevu.ajouter((r["cci"], f), ue=ue, nat=nat, tot=tot)
        to = propre(r.get("to")) or "non précisé"
        theme_libelle_source[("2014-2020", to)] = propre(r.get("to_short"))
        prevu_theme.ajouter(("2014-2020", to, f), ue=ue, nat=nat, tot=tot)
        m = propre(r.get("eafrd_measure_code"))
        if f == "FEADER" and m and m != "VOID":
            prevu_mesure.ajouter(m, ue=ue, nat=nat, tot=tot)
            theme_libelle_source[("mesure", m)] = propre(r.get("measure_short_description"))
    # 2014-2020 : exécution cumulée par année
    for r in d14["execution"]:
        f = fonds_code(r["fund"])
        if f is None:
            continue
        an = int(r["year"])
        dec, dep = cents(r.get("total_eligible_cost")), cents(r.get("total_eligible_expenditure"))
        exec_serie.ajouter((r["cci"], f, an), decide=dec, depense=dep, prevu_tot=cents(r.get("total_amount")))
        if r.get("latest_period") in ("Y", "Yes"):
            exec_fin.ajouter((r["cci"], f), decide=dec, depense=dep, prevu_tot=cents(r.get("total_amount")),
                             prevu_ue=cents(r.get("eu_amount")))
            exec_ref[r["cci"]] = max(exec_ref.get(r["cci"], ""), (r.get("reference_date") or str(an))[:10])
            to = propre(r.get("to")) or "non précisé"
            theme_libelle_source.setdefault(("2014-2020", to), propre(r.get("to_short")) or None)
            exec_theme.ajouter(("2014-2020", to, f), decide=dec, depense=dep)
            m = propre(r.get("eafrd_measure"))
            if f == "FEADER" and m and m != "VOID":
                exec_mesure.ajouter(m, decide=dec, depense=dep)
    # 2014-2020 : paiements cumulés
    for r in d14["paiements"]:
        if r["fund"] in COMPOSANTES_IEJ:
            continue
        f = fonds_code(r["fund"])
        an = int(r["year"])
        if f is None:
            if r.get("is_latest_period") == "Y":
                hors[("2014-2020", r["fund"])]["paye_ue"] += cents(r.get("total_net_payments"))
                hors[("2014-2020", r["fund"])]["prevu_ue_paiements"] += cents(r.get("net_planned_eu_amount"))
            continue
        paie_serie.ajouter((r["cci"], f, an), total=cents(r.get("total_net_payments")))
        if r.get("is_latest_period") == "Y":
            paie_fin.ajouter((r["cci"], f), plan_ue=cents(r.get("net_planned_eu_amount")),
                             pf=cents(r.get("net_pre_financing")), ip=cents(r.get("net_interim_payments")),
                             total=cents(r.get("total_net_payments")))
            paie_annee_fin[periode_de(r["cci"])] = max(paie_annee_fin.get(periode_de(r["cci"]), 0), an)
    # 2014-2020 : plans financiers annuels (crédits d'engagement de l'UE)
    for r in d14["plans"]:
        f = fonds_code(r["fund"])
        if f is None:
            continue
        for an in range(2014, 2023):
            v = cents(r.get(f"y{an}_main_allocation")) + cents(r.get(f"y{an}_performance_reserve"))
            plans.ajouter(("2014-2020", f, an), ue=v)

    # 2021-2027 : prévu
    for r in d21["prevu"]:
        if not dimension_retenue(r):
            continue
        f = fonds_code(r["fund"])
        ue, tot = cents(r["eu_amount"]), cents(r["total_amount"])
        if f is None:
            hors[("2021-2027", r["fund"])]["prevu_ue"] += ue
            continue
        prevu.ajouter((r["cci"], f), ue=ue, nat=tot - ue, tot=tot)
        po = propre(r.get("policy_objective_code")) or "non précisé"
        so = code_os(r, "specific_objective_code", "specific_objective_short_name")
        theme_libelle_source[("2021-2027", po)] = re.sub(r"^PO\d+\s*", "", propre(r.get("policy_objective_short_name")))
        so_libelle_source.setdefault(so, re.sub(r"^[A-Z]{3}\d+\.\d+\s*", "", propre(r.get("specific_objective_short_name"))))
        so_par_po[po].add(so)
        prevu_theme.ajouter(("2021-2027", po, f), ue=ue, nat=tot - ue, tot=tot)
        prevu_theme.ajouter(("2021-2027-os", so, f), ue=ue, nat=tot - ue, tot=tot)
        dom = propre(r.get("category_code"))
        domaines.ajouter((f, dom), prevu_ue=ue, prevu_tot=tot)
        domaine_libelle.setdefault((f, dom), propre(r.get("category_name")))
    # 2021-2027 : exécution (cycles de transmission)
    par_prog_cycle = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in d21["execution"]:
        if not dimension_retenue(r):
            continue
        f = fonds_code(r["fund"])
        if f is None:
            continue
        cyc = str(r.get("tod_cycle"))
        dec = cents(r.get("total_eligiblecost_of_selectedoperations"))
        dep = cents(r.get("totalspendeligibleexpenditure_declared"))
        e = par_prog_cycle[(r["cci"], f)][cyc]
        e["decide"] += dec
        e["depense"] += dep
        e["prevu_tot"] += cents(r.get("total_amount"))
        e["prevu_ue"] += cents(r.get("eu_amount"))
        e["operations"] += int(float(r.get("number_of_operations") or 0))
        if r.get("is_latest_tod_cycle") == "Y":
            exec_ref[r["cci"]] = max(exec_ref.get(r["cci"], ""), cycle_date(cyc))
            po = propre(r.get("pol_obj_code")) or "non précisé"
            so = code_os(r, "spec_obj_code", "spec_obj_short_name")
            exec_theme.ajouter(("2021-2027", po, f), decide=dec, depense=dep)
            exec_theme.ajouter(("2021-2027-os", so, f), decide=dec, depense=dep)
            domaines.ajouter((f, propre(r.get("category_code"))), decide=dec, depense=dep,
                             operations=int(float(r.get("number_of_operations") or 0)))
    for (cci, f), cycles in par_prog_cycle.items():
        ordre_c = sorted(cycles)
        dernier = cycles[ordre_c[-1]]
        exec_fin.ajouter((cci, f), decide=dernier["decide"], depense=dernier["depense"],
                         prevu_tot=dernier["prevu_tot"], prevu_ue=dernier["prevu_ue"])
        nb_ops.ajouter((cci, f), operations=dernier["operations"])
        # série annuelle : dernier cycle de chaque année, reporté les années sans transmission
        annees_c = sorted({int(c[:4]) for c in ordre_c})
        for an in range(annees_c[0], annees_c[-1] + 1):
            dans = [c for c in ordre_c if int(c[:4]) <= an]
            v = cycles[dans[-1]]
            exec_serie.ajouter((cci, f, an), decide=v["decide"], depense=v["depense"], prevu_tot=v["prevu_tot"])
    # 2021-2027 : paiements cumulés
    for r in d21["paiements"]:
        f = fonds_code(r["fund"])
        an = int(r["year"])
        if f is None:
            if r.get("is_latest_period") == "Y":
                hors[("2021-2027", r["fund"])]["paye_ue"] += cents(r.get("total_net_payments"))
                hors[("2021-2027", r["fund"])]["prevu_ue_paiements"] += cents(r.get("actual_plan_eu_amt_latest_adop"))
            continue
        paie_serie.ajouter((r["cci"], f, an), total=cents(r.get("total_net_payments")))
        if r.get("is_latest_period") == "Y":
            paie_fin.ajouter((r["cci"], f), plan_ue=cents(r.get("actual_plan_eu_amt_latest_adop")),
                             pf=cents(r.get("net_pre_financing")), ip=cents(r.get("net_interim_payments")),
                             total=cents(r.get("total_net_payments")))
            paie_annee_fin[periode_de(r["cci"])] = max(paie_annee_fin.get(periode_de(r["cci"]), 0), an)
    # 2021-2027 : plans financiers annuels (« ESF » du jeu = FSE+)
    for r in d21["plans"]:
        f = {"ESF": "FSE+"}.get(r["fund"]) or fonds_code(r["fund"])
        if f is None:
            continue
        for an in range(2021, 2028):
            plans.ajouter(("2021-2027", f, an), ue=cents(r.get(f"y{an}")))

    return {"hors": hors, "prevu": prevu, "prevu_theme": prevu_theme, "prevu_mesure": prevu_mesure,
            "exec_theme": exec_theme, "exec_mesure": exec_mesure, "exec_ref": exec_ref, "exec_fin": exec_fin,
            "exec_serie": exec_serie, "paie_fin": paie_fin, "paie_serie": paie_serie,
            "paie_annee_fin": paie_annee_fin, "plans": plans, "theme_libelle_source": theme_libelle_source,
            "so_libelle_source": so_libelle_source, "so_par_po": so_par_po, "domaines": domaines,
            "domaine_libelle": domaine_libelle, "nb_ops": nb_ops}


def bloc_montants(prevu: dict | None, exe: dict | None, paie: dict | None) -> dict:
    """Bloc normalisé d'un (programme, fonds) ou d'un groupe : null quand la source ne publie pas la grandeur."""
    return {
        "prevu_ue_eur": eur(prevu["ue"]) if prevu else None,
        "prevu_national_eur": eur(prevu["nat"]) if prevu else None,
        "prevu_total_eur": eur(prevu["tot"]) if prevu else None,
        "decide_eur": eur(exe["decide"]) if exe else None,
        "depense_eur": eur(exe["depense"]) if exe else None,
        "paye_ue_eur": eur(paie["total"]) if paie else None,
    }


def somme_blocs(blocs: list[dict]) -> dict:
    """Somme de blocs ; une grandeur reste null si aucun bloc ne la publie."""
    out = {}
    for k in ("prevu_ue_eur", "prevu_national_eur", "prevu_total_eur", "decide_eur", "depense_eur", "paye_ue_eur"):
        vals = [b[k] for b in blocs if b.get(k) is not None]
        out[k] = eur(sum(round(v * 100) for v in vals)) if vals else None
    return out


# --- Production -------------------------------------------------------------------------------------------------------


def cles_fonds(fs) -> list[str]:
    return sorted(fs, key=lambda f: (ORDRE_FONDS.index(f) if f in ORDRE_FONDS else 99, f))


def produire_programmes(ref: dict, a: dict, entete: dict) -> tuple[dict, dict]:
    """programmes.json et blocs par (cci, fonds) réutilisés par regions et index."""
    cles = set(a["prevu"].d) | set(a["exec_fin"].d) | set(a["paie_fin"].d)
    par_cci = defaultdict(dict)
    for cci, f in cles:
        p = a["prevu"].get((cci, f)) or None
        e = a["exec_fin"].get((cci, f)) or None
        pa = a["paie_fin"].get((cci, f)) or None
        if cci == "2023FR06AFSP001" and pa and not p:   # FEADER du plan stratégique PAC : montant UE prévu des paiements
            p = {"ue": pa["plan_ue"], "nat": None, "tot": None}
        b = bloc_montants(p if p else None, e if e else None, pa if pa else None)
        if p and p.get("nat") is None:
            b["prevu_national_eur"] = b["prevu_total_eur"] = None
        par_cci[cci][f] = b
    progs = []
    for cci in sorted(par_cci):
        info = ref.get(cci) or {"cci": cci, "periode": periode_de(cci),
                                "titre": cci, "portee": "non rattaché", "groupe": "non_rattache", "territoire": None}
        fonds = cles_fonds(par_cci[cci])
        pa_tot = [a["paie_fin"].get((cci, f)) for f in fonds if a["paie_fin"].get((cci, f))]
        e_tot = [a["exec_fin"].get((cci, f)) for f in fonds if a["exec_fin"].get((cci, f))]
        progs.append({
            "cci": cci, "periode": info["periode"], "titre": info["titre"], "portee": info["portee"],
            "region": info["groupe"] if info["groupe"] in REGIONS else None,
            "groupe": info["groupe"], "territoire": info.get("territoire"), "fonds": fonds,
            "total": somme_blocs([par_cci[cci][f] for f in fonds]),
            "par_fonds": {f: par_cci[cci][f] for f in fonds},
            "execution": ({"date_reference": a["exec_ref"].get(cci),
                           "prevu_total_eur": eur(sum(x["prevu_tot"] for x in e_tot))} if e_tot else None),
            "paiements": ({"annee": a["paie_annee_fin"].get(info["periode"]),
                           "prevu_ue_eur": eur(sum(x["plan_ue"] for x in pa_tot)),
                           "prefinancement_net_eur": eur(sum(x["pf"] for x in pa_tot)),
                           "paiements_intermediaires_nets_eur": eur(sum(x["ip"] for x in pa_tot)),
                           "total_net_eur": eur(sum(x["total"] for x in pa_tot))} if pa_tot else None),
        })
    progs.sort(key=lambda p: (p["periode"], p["groupe"] if p["groupe"] in REGIONS else "~" + p["groupe"], p["cci"]))
    doc = {**entete,
           "ordre": {"regle": "Programmes par période, puis par code Insee de région (programmes nationaux, interrégionaux "
                              "et non rattachés ensuite), puis par identifiant CCI. Aucun classement par montant.",
                     "cles": ["periode", "groupe", "cci"]},
           "programmes": progs}
    return doc, par_cci


def produire_regions(ref: dict, a: dict, par_cci: dict, entete: dict) -> dict:
    groupes = defaultdict(lambda: {"programmes": set(), "blocs": defaultdict(lambda: defaultdict(list)),
                                   "series": defaultdict(lambda: defaultdict(lambda: defaultdict(int)))})
    for cci, fs in par_cci.items():
        info = ref.get(cci) or {"periode": periode_de(cci), "groupe": "non_rattache"}
        g = groupes[info["groupe"]]
        g["programmes"].add(cci)
        for f, b in fs.items():
            g["blocs"][info["periode"]][f].append(b)
    for (cci, f, an), v in a["exec_serie"].d.items():
        info = ref.get(cci) or {"periode": periode_de(cci), "groupe": "non_rattache"}
        s = groupes[info["groupe"]]["series"][info["periode"]][an]
        s["decide"] += v["decide"]
        s["depense"] += v["depense"]
        s["n_exec"] += 1
    for (cci, f, an), v in a["paie_serie"].d.items():
        info = ref.get(cci) or {"periode": periode_de(cci), "groupe": "non_rattache"}
        s = groupes[info["groupe"]]["series"][info["periode"]][an]
        s["paye"] += v["total"]
        s["n_paie"] += 1
    sortie = []
    ordre = list(REGIONS) + ["national", "interregional", "non_rattache"]
    for code in sorted(groupes, key=lambda c: ordre.index(c) if c in ordre else 99):
        g = groupes[code]
        periodes = []
        for per in PERIODES:
            if per not in g["blocs"]:
                continue
            par_fonds = {f: somme_blocs(g["blocs"][per][f]) for f in cles_fonds(g["blocs"][per])}
            annees = []
            for an in sorted(g["series"][per]):
                s = g["series"][per][an]
                annees.append({"annee": an, "decide_cumule_eur": eur(s["decide"]) if s["n_exec"] else None,
                               "depense_cumulee_eur": eur(s["depense"]) if s["n_exec"] else None,
                               "paye_ue_cumule_eur": eur(s["paye"]) if s["n_paie"] else None})
            periodes.append({"periode": per, "par_fonds": par_fonds, "total": somme_blocs(list(par_fonds.values())),
                             "annees": annees})
        sortie.append({"code": code, "nom": REGIONS.get(code) or GROUPES.get(code) or "Non rattaché",
                       "type": ("collectivité d'outre-mer" if code == "977" else "région" if code in REGIONS
                                else "groupe de programmes"),
                       "programmes": sorted(g["programmes"]), "periodes": periodes})
    return {**entete,
            "ordre": {"regle": "Régions par code Insee (Saint-Martin, collectivité d'outre-mer, ensuite), puis programmes "
                               "nationaux et interrégionaux. Aucun classement par montant.", "cles": ["code"]},
            "regions": sortie}


def produire_themes(a: dict, entete: dict) -> dict:
    def ligne(per, code, libelle, libelle_src):
        par_fonds = {}
        for (p, c, f), v in sorted(a["prevu_theme"].d.items()):
            if p == per and c == code:
                e = a["exec_theme"].get((per, c, f)) or None
                par_fonds[f] = bloc_montants(v, e, None)
                del par_fonds[f]["paye_ue_eur"]
        for (p, c, f), e in sorted(a["exec_theme"].d.items()):
            if p == per and c == code and f not in par_fonds:
                par_fonds[f] = {**bloc_montants(None, e, None)}
                del par_fonds[f]["paye_ue_eur"]
        par_fonds = {f: par_fonds[f] for f in cles_fonds(par_fonds)}
        tot = somme_blocs(list(par_fonds.values()))
        del tot["paye_ue_eur"]
        return {"code": code, "libelle": libelle, "libelle_source": libelle_src or None, "par_fonds": par_fonds,
                "total": tot}

    def tri_code(c):
        m = re.match(r"^\d+$", c)
        return (0, int(c), "") if m else (1, 0, c)

    ot = sorted({c for (p, c, f) in a["prevu_theme"].d if p == "2014-2020"} |
                {c for (p, c, f) in a["exec_theme"].d if p == "2014-2020"}, key=tri_code)
    lignes14 = [ligne("2014-2020", c, OBJECTIFS_THEMATIQUES.get(c, a["theme_libelle_source"].get(("2014-2020", c))),
                      a["theme_libelle_source"].get(("2014-2020", c))) for c in ot]
    mesures = []
    for m in sorted(set(a["prevu_mesure"].d) | set(a["exec_mesure"].d)):
        p = a["prevu_mesure"].get(m) or None
        e = a["exec_mesure"].get(m) or None
        b = bloc_montants(p, e, None)
        del b["paye_ue_eur"]
        mesures.append({"code": m, "libelle": MESURES_FEADER.get(m) or a["theme_libelle_source"].get(("mesure", m)),
                        "libelle_source": a["theme_libelle_source"].get(("mesure", m)), **b})
    po = sorted({c for (p, c, f) in a["prevu_theme"].d if p == "2021-2027"}, key=tri_code)
    lignes21 = []
    for c in po:
        l = ligne("2021-2027", c, OBJECTIFS_STRATEGIQUES.get(c, a["theme_libelle_source"].get(("2021-2027", c))),
                  a["theme_libelle_source"].get(("2021-2027", c)))
        sos = sorted(a["so_par_po"].get(c, set()), key=lambda s: [int(x) if x.isdigit() else x
                                                                   for x in re.split(r"(\d+)", s)])
        l["objectifs_specifiques"] = [ligne("2021-2027-os", s, OBJECTIFS_SPECIFIQUES.get(s), a["so_libelle_source"].get(s))
                                      for s in sos]
        for o in l["objectifs_specifiques"]:
            o["libelle"] = o["libelle"] or o["libelle_source"]
        lignes21.append(l)
    doms = []
    for (f, dom) in sorted(a["domaines"].d, key=lambda k: (ORDRE_FONDS.index(k[0]) if k[0] in ORDRE_FONDS else 99, k[1])):
        v = a["domaines"].get((f, dom))
        doms.append({"fonds": f, "code": dom, "libelle_source": a["domaine_libelle"].get((f, dom)) or None,
                     "prevu_ue_eur": eur(v.get("prevu_ue", 0)), "prevu_total_eur": eur(v.get("prevu_tot", 0)),
                     "decide_eur": eur(v["decide"]) if "decide" in v else None,
                     "depense_eur": eur(v["depense"]) if "depense" in v else None,
                     "operations": v.get("operations")})
    return {**entete,
            "ordre": {"regle": "Objectifs et mesures par code croissant ; domaines d'intervention par fonds puis par code. "
                               "Aucun classement par montant.", "cles": ["code"]},
            "periodes": [
                {"periode": "2014-2020", "nomenclature": "objectifs thématiques (règlement (UE) n° 1303/2013, article 9)",
                 "themes": lignes14,
                 "mesures_feader": mesures},
                {"periode": "2021-2027", "nomenclature": "objectifs stratégiques et spécifiques (règlement (UE) 2021/1060, "
                                                        "article 5 ; règlements par fonds)",
                 "themes": lignes21,
                 "domaines_intervention": doms}]}


def serie_annuelle(cumuls: list[int | None]) -> list[float | None]:
    """Flux de l'année = cumul de l'année - cumul de l'année précédente (calcul du projet)."""
    out, prec = [], 0
    for c in cumuls:
        if c is None:
            out.append(None)
            continue
        out.append(eur(c - prec))
        prec = c
    return out


def produire_annees(a: dict, frr_doc: dict, entete: dict) -> dict:
    periodes = []
    for per in PERIODES:
        # crédits d'engagement annuels
        ans_plan = sorted({an for (p, f, an) in a["plans"].d if p == per})
        fonds_plan = cles_fonds({f for (p, f, an) in a["plans"].d if p == per})
        par_fonds_plan = {f: [eur(a["plans"].get((per, f, an)).get("ue", 0)) for an in ans_plan] for f in fonds_plan}
        total_plan = [eur(sum(a["plans"].get((per, f, an)).get("ue", 0) for f in fonds_plan)) for an in ans_plan]
        # paiements cumulés par fonds
        cum = defaultdict(lambda: defaultdict(int))
        for (cci, f, an), v in a["paie_serie"].d.items():
            if periode_de(cci) == per:
                cum[f][an] += v["total"]
        ans_p = sorted({an for f in cum for an in cum[f]})
        fonds_p = cles_fonds(cum)
        cumul_fonds = {f: [cum[f].get(an) if an in cum[f] else None for an in ans_p] for f in fonds_p}
        cumul_total = [sum(cum[f].get(an, 0) for f in fonds_p) for an in ans_p]
        # exécution cumulée
        ex = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for (cci, f, an), v in a["exec_serie"].d.items():
            if periode_de(cci) == per:
                ex[f][an][0] += v["decide"]
                ex[f][an][1] += v["depense"]
        ans_e = sorted({an for f in ex for an in ex[f]})
        fonds_e = cles_fonds(ex)
        periodes.append({
            "periode": per,
            "engagements_ue": {"annees": ans_plan, "par_fonds_eur": par_fonds_plan, "total_eur": total_plan},
            "paiements_ue": {"annees": ans_p, "annee_partielle": a["paie_annee_fin"].get(per),
                             "cumul_par_fonds_eur": {f: [eur(x) if x is not None else None for x in v]
                                                     for f, v in cumul_fonds.items()},
                             "cumul_total_eur": [eur(x) for x in cumul_total],
                             "annuel_total_eur": serie_annuelle(cumul_total),
                             "annuel_par_fonds_eur": {f: serie_annuelle(v) for f, v in cumul_fonds.items()}},
            "execution": {"annees": ans_e,
                          "decide_cumule_par_fonds_eur": {f: [eur(ex[f][an][0]) if an in ex[f] else None for an in ans_e]
                                                          for f in fonds_e},
                          "depense_cumulee_par_fonds_eur": {f: [eur(ex[f][an][1]) if an in ex[f] else None
                                                                for an in ans_e] for f in fonds_e}},
        })
    return {**entete, "periodes": periodes,
            "frr": {"annees": frr_doc["annees"], "fonds_recus_eur": frr_doc["fonds_recus"]["total_eur"],
                    "fichier": "fonds_europeens/frr.json"}}


def produire_frr() -> dict:
    from transform import jsonstat_records
    flux = lire_json_source("fe_eurostat_frr_flux")
    emplois = lire_json_source("fe_eurostat_frr_emplois")
    rf = jsonstat_records(flux)
    ru = jsonstat_records(emplois)
    annees = sorted({int(r["time"]) for r in rf + ru})

    def serie(recs, **filtre):
        vals = {int(r["time"]): r["valeur"] for r in recs if all(r.get(k) == v for k, v in filtre.items())}
        return [None if vals.get(an) is None else round(vals[an] * 1e6, 2) for an in annees], vals

    def pct(recs, **filtre):
        vals = {int(r["time"]): r["valeur"] for r in recs if all(r.get(k) == v for k, v in filtre.items())}
        return [vals.get(an) for an in annees]

    recus_tot, _ = serie(rf, finpos="NET", na_item="F2R_F4R", fin_typ="TOTAL", stk_flow="TRN", unit="MIO_EUR")
    recus_sub, _ = serie(rf, finpos="NET", na_item="F2R_F4R", fin_typ="GRNT", stk_flow="TRN", unit="MIO_EUR")
    recus_pret, _ = serie(rf, finpos="NET", na_item="F2R_F4R", fin_typ="LOAN", stk_flow="TRN", unit="MIO_EUR")
    recus_ap, _ = serie(rf, finpos="NET", na_item="F2R_F4R_AP", fin_typ="TOTAL", stk_flow="TRN", unit="MIO_EUR")
    libelles = {}
    for r in ru:
        libelles[r["na_item"]] = r["libelles"]["na_item"]
    categories = []
    for code in ("TOTAL", "CUR", "CAP", "P51G", "D9", "CAP_OTH", "OTH"):
        if code not in libelles:
            continue
        s, _ = serie(ru, na_item=code, fin_typ="TOTAL", unit="MIO_EUR")
        categories.append({"code": code, "libelle": libelles[code],
                           "parent": None if code in ("TOTAL",) else ("CAP" if code in ("P51G", "D9", "CAP_OTH")
                                                                      else "TOTAL"),
                           "montants_eur": s, "pct_pib": pct(ru, na_item=code, fin_typ="TOTAL", unit="PC_GDP")})
    maj = str(flux.get("updated", ""))[:10]
    cumul = sum(round(x * 100) for x in recus_tot if x is not None)
    return {
        "millesime": f"Eurostat, {annees[0]}-{annees[-1]} (mise à jour du {maj})",
        "source": f"Eurostat gov_rrf_fa (flux financiers de la FRR) et gov_rrf_use (emploi des fonds de la FRR), "
                  f"France, mise à jour {maj}",
        "collecte_le": (entree("fe_eurostat_frr_flux").get("collecte_le") or "")[:10] or None,
        "unite": "euros (millions d'euros publiés × 1 000 000) ; % du PIB",
        "avertissement": "Montants publiés par Eurostat en comptabilité nationale : fonds effectivement reçus par les "
                         "administrations publiques françaises au titre de la facilité pour la reprise et la résilience, "
                         "et emploi de ces fonds par nature de dépense. La FRR est financée par l'emprunt commun de "
                         "l'Union (NextGenerationEU), pas par le prélèvement sur recettes au profit de l'UE.",
        "annees": annees,
        "fonds_recus": {"total_eur": recus_tot, "subventions_eur": recus_sub, "prets_eur": recus_pret,
                        "dont_paiements_anticipes_eur": recus_ap,
                        "pct_pib": pct(rf, finpos="NET", na_item="F2R_F4R", fin_typ="TOTAL", stk_flow="TRN",
                                       unit="PC_GDP"),
                        "cumul_eur": eur(cumul),
                        "cumul_methode": "somme des montants annuels publiés (calcul du projet)"},
        "emplois": {"categories": categories,
                    "lecture": "Dépenses des administrations publiques financées par les subventions de la FRR, par "
                               "nature (Eurostat) : dépenses courantes et dépenses en capital, dont formation brute de "
                               "capital fixe et transferts en capital. Les fonds reçus une année peuvent financer des "
                               "dépenses d'une autre année : les deux séries ne se comparent pas année par année."},
        "liens": [
            {"fichier": "ue/contribution.json", "lecture": "NextGenerationEU dans le budget de l'UE (montant total, "
                                                          "rubriques)"},
            {"fichier": "ue/beneficiaires/index.json", "lecture": "engagements de la FRR enregistrés dans le système de "
                                                                  "transparence financière de la Commission (FTS, "
                                                                  "programme 2.2.21), hors total des bénéficiaires "
                                                                  "nommés : même argent, autre notion (engagement)"},
            {"fichier": "numerique_etat/fonds/france_relance.json",
             "lecture": "France Relance, plan national financé en partie par la FRR : vue des mesures numériques"}],
        "sources_inaccessibles": [x for x in INACCESSIBLES if "facilité" in x["source"]],
    }


# --- Listes d'opérations --------------------------------------------------------------------------------------------

LISTES = {  # identifiant -> description de la source et règles de lecture
    "bretagne": {"sid": "fe_ops_bretagne", "region": "53", "autorite": "Région Bretagne",
                 "jeu": "https://data.bretagne.bzh/explore/dataset/feder-fse_beneficiaires/",
                 "licence": "Licence Ouverte 2.0", "programmes": {"2014-2020": "2014FR16M2OP003",
                                                                  "2021-2027": "2021FR16FFPR016"}},
    "paysdelaloire": {"sid": "fe_ops_paysdelaloire", "region": "52", "autorite": "Région des Pays de la Loire",
                      "jeu": "https://data.paysdelaloire.fr/explore/dataset/234400034_024-001_fonds_europeens/",
                      "licence": "ODbL", "programmes": {"2014-2020": "2014FR16M2OP008"}},
    "normandie_2127": {"sid": "fe_ops_normandie_2127", "region": "28", "autorite": "Région Normandie",
                       "jeu": "https://www.data.gouv.fr/fr/datasets/6a9a8313a850fcd699b349b8/",
                       "licence": "Licence Ouverte 2.0", "programmes": {"2021-2027": "2021FR16FFPR006"}},
    "iledefrance_1420": {"sid": "fe_ops_iledefrance_1420", "region": "11", "autorite": "Région Île-de-France",
                         "jeu": "https://data.iledefrance.fr/explore/dataset/gestion-des-fonds-europeens-liste-des-"
                                "operations/", "licence": "Licence Ouverte 2.0",
                         "programmes": {"2014-2020": "2014FR05M0OP001"}},
    "iledefrance_2127": {"sid": "fe_ops_iledefrance_2127", "region": "11", "autorite": "Région Île-de-France",
                         "jeu": "https://data.iledefrance.fr/explore/dataset/gestion-des-fonds-europeens-en-ile-de-"
                                "france-liste-des-operations-2021-2027/", "licence": "Licence Ouverte 2.0",
                         "programmes": {"2021-2027": "2021FR05FFPR001"}},
    "reunion_1420": {"sid": "fe_ops_reunion_1420", "region": "04", "autorite": "Région Réunion",
                     "jeu": "https://data.regionreunion.com/explore/dataset/liste_des_operations_31/",
                     "licence": "Licence Ouverte 2.0", "programmes": {"2014-2020": "2014FR16RFOP007"}},
}
FONDS_LISTES = [(r"initiative pour l.emploi des jeunes|\biej\b|\byei\b", "IEJ"), (r"fse\s*\+|fse\+|esf\+", "FSE+"),
                (r"\bftj\b|transition juste", "FTJ"), (r"\bfse\b|social europ", "FSE"),
                (r"\bfeder\b|d.veloppement r.gional", "FEDER"), (r"feampa", "FEAMPA")]


def lire_csv(p: Path) -> list[dict]:
    texte = p.read_text(encoding="utf-8-sig", errors="replace")
    premiere = texte.split("\n", 1)[0]
    sep = max([";", ",", "\t"], key=premiere.count)
    csv.field_size_limit(10 ** 8)
    return list(csv.DictReader(io.StringIO(texte), delimiter=sep))


def nombre(v) -> float | None:
    s = propre(v).replace(" ", "").replace("%", "").replace("€", "")
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def taux(v) -> float | None:
    x = nombre(v)
    if x is None:
        return None
    return round(x / 100, 6) if x > 1.0001 else round(x, 6)


def annee_de(v) -> int | None:
    m = re.search(r"(19|20)\d{2}", propre(v))
    return int(m.group(0)) if m else None


def date_iso(v) -> str | None:
    s = propre(v)
    m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", s)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def insee(v) -> str | None:
    s = propre(v)
    s = re.sub(r"\.0$", "", s)
    if re.fullmatch(r"\d{4}", s):
        s = "0" + s
    return s if re.fullmatch(r"(?:\d{5}|2[AB]\d{3})", s) else None


def dep_de_insee(code: str | None) -> str | None:
    if not code:
        return None
    return code[:3] if code.startswith("97") else code[:2]


def fonds_liste(v, defaut: str | None = None) -> str | None:
    t = ascii_min(propre(v))
    for motif, code in FONDS_LISTES:
        if re.search(motif, t):
            return code
    return defaut


def lire_liste(nom: str) -> tuple[list[dict], dict]:
    """Opérations d'une liste ramenées à un enregistrement commun (aucune colonne d'adresse ni de personne lue)."""
    conf = LISTES[nom]
    fs = [f for f in fichiers(conf["sid"]) if f.suffix.lower() in (".csv", ".txt")]
    if not fs:
        raise SystemExit(f"liste {nom} absente de data/lake : lancer `python pipeline/fonds_europeens.py collecter`")
    lignes = lire_csv(fs[0])
    ops, ctl = [], {"lignes_source": len(lignes), "sans_montant": 0}
    for r in lignes:
        o = {"id": None, "periode": None, "fonds": None, "annee_debut": None, "date_fin": None, "nom_source": "",
             "siret": None, "type_source": "", "intitule_source": "", "commune_insee": None, "departement": None,
             "theme": None, "cout": None, "ue": None, "ue_mode": "publié", "taux": None, "financeurs": None}
        if nom == "bretagne":
            o.update(id=propre(r.get("no_dossier")) or None, periode=propre(r.get("periode")) or None,
                     fonds=fonds_liste(r.get("fonds")), annee_debut=annee_de(r.get("date_de_debut_de_l_operation")),
                     date_fin=date_iso(r.get("date_de_fin_de_l_operation")), nom_source=propre(r.get("beneficiaire")),
                     intitule_source=propre(r.get("nom_de_l_operation")), commune_insee=insee(r.get("code_insee")),
                     theme=propre(r.get("domaine_d_intervention")) or None,
                     cout=nombre(r.get("cout_total_de_l_operation")),
                     taux=taux(r.get("taux_de_cofinancement_par_l_ue")))
            o["ue"] = round(o["cout"] * o["taux"], 2) if o["cout"] is not None and o["taux"] is not None else None
            o["ue_mode"] = "calculé : coût total × taux de cofinancement publié"
        elif nom == "paysdelaloire":
            fin = {k: nombre(r.get(c)) for k, c in (("etat_eur", "etat"), ("region_eur", "region"),
                                                    ("departement_eur", "departement0"), ("prives_eur", "prives"),
                                                    ("autofinancement_eur", "auto_financement"))}
            o.update(id=propre(r.get("ndeg_du_dossier")) or None, periode="2014-2020", fonds=fonds_liste(r.get("fonds")),
                     annee_debut=annee_de(r.get("dp_prem_annee")), nom_source=propre(r.get("raison_sociale_du_beneficiaire")),
                     siret=re.sub(r"\D", "", propre(r.get("ndeg_siret_du_beneficiaire"))) or None,
                     type_source=propre(r.get("type_de_beneficiaire_libelle")),
                     intitule_source=propre(r.get("libelle_du_dossier")), commune_insee=insee(r.get("insee")),
                     theme=propre(r.get("objectif_thematique_libelle")) or None, cout=nombre(r.get("cout_total")),
                     ue=nombre(r.get("ue")), financeurs=fin)
            o["taux"] = round(o["ue"] / o["cout"], 6) if o["ue"] is not None and o["cout"] else None
        elif nom == "normandie_2127":
            di, os_ = propre(r.get("di")), propre(r.get("os"))
            o.update(id=propre(r.get("neda")) or None, periode="2021-2027", fonds=fonds_liste(r.get("fonds")),
                     annee_debut=annee_de(r.get("date_de_debut_de_realisation")),
                     date_fin=date_iso(r.get("date_de_fin_de_realisation")), nom_source=propre(r.get("beneficiaire")),
                     type_source=propre(r.get("type_de_beneficiaire")),
                     intitule_source=propre(r.get("libelle_de_l_operation")), commune_insee=insee(r.get("code_insee")),
                     theme=(f"objectif spécifique {os_}, domaine d'intervention {di}" if os_ or di else None),
                     cout=nombre(r.get("cout_total")), ue=nombre(r.get("montant_ue")),
                     taux=taux(r.get("taux_d_intervention")))
        elif nom == "iledefrance_1420":
            k = "total_des_depenses_eligibles_attribue_a_l_operation_total_eligible_expenditure_allocated_to_the_oper"
            o.update(periode="2014-2020", fonds=fonds_liste(r.get("fonds_funds")),
                     annee_debut=annee_de(r.get("date_du_debut_de_l_operation_operation_start_date")),
                     date_fin=date_iso(r.get("date_de_fin_de_l_operation_operation_end_date")),
                     nom_source=propre(r.get("nom_du_beneficiaire_beneficiary_name")),
                     intitule_source=propre(r.get("nom_de_l_operation_operation_name")),
                     departement=dep_unique(r.get("departement_territory")),
                     theme=propre(r.get("denomination_de_la_categorie_d_intervention_dont_releve_l_operation_category_"
                                        "of_intervention")) or None,
                     cout=nombre(r.get(k)),
                     taux=taux(r.get("taux_de_cofinancement_par_l_union_europeenne_union_co_financing_rate")))
            o["ue"] = round(o["cout"] * o["taux"], 2) if o["cout"] is not None and o["taux"] is not None else None
            o["ue_mode"] = "calculé : dépenses éligibles × taux de cofinancement publié"
        elif nom == "iledefrance_2127":
            lieu = propre(r.get("indicateur_d_emplacement_ou_geolocalisation_de_l_operation_location_indicator_or_"
                                "geolocalisation_for_the"))
            codes = sorted(set(re.findall(r"\b0?(\d{2})\b(?=\s+[A-ZÉÈa-zé])", lieu)))
            o.update(id=propre(r.get("code_de_l_operation_file_number")) or None, periode="2021-2027",
                     fonds=fonds_liste(r.get("fonds_fund")),
                     annee_debut=annee_de(r.get("date_du_debut_de_l_operation_start_date_of_the_operation")),
                     date_fin=date_iso(r.get("date_d_achevement")),
                     nom_source=propre(r.get("nom_du_beneficiaire_dans_le_cas_de_marches_publics_nom_du_contractant_"
                                             "beneficiary_name")),
                     intitule_source=propre(r.get("nom_de_l_operation_name_of_the_operation")),
                     departement=codes[0] if len(codes) == 1 else None,
                     theme=propre(r.get("type_d_intervention")) or None,
                     cout=nombre(r.get("cout_total_de_l_operation_total_cost_of_the_operation")),
                     taux=taux(r.get("taux_de_cofinancement_par_l_union_europeenne_eu_cofinancing_rate")))
            o["ue"] = round(o["cout"] * o["taux"], 2) if o["cout"] is not None and o["taux"] is not None else None
            o["ue_mode"] = "calculé : coût total × taux de cofinancement publié"
        elif nom == "reunion_1420":
            o.update(periode="2014-2020", fonds="FEDER",
                     annee_debut=annee_de(r.get("date_de_debut_de_l_operation_start_date")),
                     date_fin=date_iso(r.get("date_de_fin_de_l_operation_end_date")),
                     nom_source=propre(r.get("nom_du_beneficiaire_beneficiary")),
                     intitule_source=propre(r.get("nom_de_l_operation_operation")),
                     departement="974" if propre(r.get("cp")).startswith("974") else None,   # code postal ou Insee
                     theme=propre(r.get("categorie_d_intervention_category_of_intervention")) or None,
                     cout=nombre(r.get("total_des_depenses_eligibles_total_eligible_expenditure")),
                     ue=nombre(r.get("ue")), taux=taux(r.get("empty")))
        if o["departement"] is None:
            o["departement"] = dep_de_insee(o["commune_insee"])
        if o["departement"] and re.fullmatch(r"\d", o["departement"]):
            o["departement"] = "0" + o["departement"]
        if o["cout"] is None and o["ue"] is None:
            ctl["sans_montant"] += 1
        ops.append(o)
    return ops, ctl


# --- Rapprochement SIRENE (stock local, sans réseau) -------------------------------------------------------------------


def cle_nom(nom: str) -> str:
    """Mots du nom, triés, sans mots vides ni forme juridique (même règle que pipeline/ue.py)."""
    import ue
    return " ".join(sorted(ue.jetons(nom)))


def empreinte(cle: str) -> str:
    return hashlib.sha256(cle.encode("utf-8")).hexdigest()[:24]


def nom_de_personne_possible(nom: str) -> bool:
    import local
    try:
        return local.contient_nom_de_personne(nom)
    except Exception:
        return True


TYPES_PERSONNE_PHYSIQUE = re.compile(r"personne physique|entrepreneur individuel|exploitant individuel|"
                                     r"micro-?entrepreneur|auto-?entrepreneur", re.I)


def resoudre() -> dict:
    """Noms et SIRET des listes -> SIREN, catégorie juridique, dénomination (personnes morales seulement).

    Lit le stock SIRENE des unités légales déposé par pipeline/local.py (data/lake/_cache/local/), sans réseau. Le cache
    ne contient que des empreintes de noms (sha256), jamais un nom de la source ; une dénomination n'y est gardée que
    pour une personne morale."""
    cles, sirens = set(), set()
    for nom in LISTES:
        try:
            ops, _ = lire_liste(nom)
        except SystemExit:
            continue
        for o in ops:
            if o["siret"] and len(o["siret"]) >= 9:
                sirens.add(o["siret"][:9])
            elif o["nom_source"] and not TYPES_PERSONNE_PHYSIQUE.search(o["type_source"]):
                k = cle_nom(o["nom_source"])
                if k:
                    cles.add(k)
    if not STOCK_SIRENE.exists():
        print(f"stock SIRENE absent ({STOCK_SIRENE.relative_to(ROOT)}) : rapprochement non fait, bénéficiaires agrégés",
              file=sys.stderr)
        return {}
    import duckdb
    import ue
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET memory_limit='1200MB'")
    con.execute("create temp table q(k varchar)")
    con.executemany("insert into q values (?)", [(k,) for k in sorted(cles)])
    con.execute("create temp table s(siren varchar)")
    con.executemany("insert into s values (?)", [(x,) for x in sorted(sirens)])
    vides = ", ".join(f"'{m}'" for m in sorted(ue.MOTS_VIDES))
    equiv = ", ".join(f"'{a}': '{b}'" for a, b in sorted(ue.EQUIVALENCES.items()))
    sql = f"""
      with base as (
        select siren, cast(categorieJuridiqueUniteLegale as varchar) cj, denominationUniteLegale d
        from read_parquet('{STOCK_SIRENE}')
        where denominationUniteLegale is not null and categorieJuridiqueUniteLegale is not null
          and cast(categorieJuridiqueUniteLegale as varchar) not like '1%'),
      n as (
        select siren, cj, d,
          regexp_replace(regexp_replace(regexp_replace(regexp_replace(upper(strip_accents(d)), '\\([^)]*\\)', ' ', 'g'),
            '[^A-Z0-9]+', ' ', 'g'), '\\bCONSEIL REGIONAL\\b', 'REGION', 'g'), '\\bCONSEIL DEPARTEMENTAL\\b',
            'DEPARTEMENT', 'g') x from base),
      k as (
        select siren, cj, d, array_to_string(list_sort(list_distinct(list_filter(
          list_transform(string_split(x, ' '), lambda t: coalesce(map {{{equiv}}}[t], t)),
          lambda t: t <> '' and not list_contains([{vides}], t)))), ' ') k from n)
      select siren, cj, d, k from k where k in (select k from q)"""
    candidats = defaultdict(dict)
    for siren, cj, d, k in con.execute(sql).fetchall():
        if cle_nom(d) != k:   # garde-fou : même règle que le côté Python, sinon le candidat est ignoré
            continue
        candidats[k][siren] = ((cj or "").zfill(4), d)
    par_siren = {}
    for siren, cj, d in con.execute(f"""select u.siren, cast(u.categorieJuridiqueUniteLegale as varchar),
              coalesce(u.denominationUniteLegale, u.denominationUsuelle1UniteLegale)
              from read_parquet('{STOCK_SIRENE}') u join s using (siren)""").fetchall():
        cj = (cj or "").zfill(4) if cj else ""
        par_siren[siren] = {"cj": cj or None, "denomination": propre(d) if sirene.personne_morale(cj) else None}
    noms = {}
    for k in sorted(cles):
        c = candidats.get(k, {})
        if len(c) == 1:
            siren, (cj, d) = next(iter(c.items()))
            noms[empreinte(k)] = {"candidats": 1, "siren": siren, "cj": cj,
                                  "denomination": propre(d) if sirene.personne_morale(cj) else None}
        else:
            noms[empreinte(k)] = {"candidats": len(c)}
    st = STOCK_SIRENE.stat()
    cache = {"stock_sirene": {"chemin": str(STOCK_SIRENE.relative_to(ROOT)), "octets": st.st_size,
                              "modifie_le": datetime.fromtimestamp(st.st_mtime, timezone.utc).date().isoformat()},
             "methode": "mots du nom triés (pipeline/ue.py, jetons) identiques à ceux de la dénomination SIRENE d'une "
                        "seule unité légale de catégorie 2xxx à 9xxx ; plusieurs unités : ambigu, agrégé",
             "noms": noms, "sirens": {s: par_siren[s] for s in sorted(par_siren)}}
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_RAPPROCHEMENT.with_suffix(".part")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(CACHE_RAPPROCHEMENT)
    uniques = sum(1 for v in noms.values() if v.get("candidats") == 1)
    print(f"rapprochement : {len(cles)} noms ({uniques} uniques), {len(sirens)} SIREN ({len(par_siren)} trouvés)",
          file=sys.stderr)
    return cache


def charger_rapprochement() -> dict:
    try:
        return json.loads(CACHE_RAPPROCHEMENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def identifier(o: dict, rap: dict, cache_api: dict) -> tuple[str | None, str | None, str | None, str]:
    """-> (siren, catégorie, dénomination SIRENE, motif) ; motif = « nommé » ou raison de l'agrégation."""
    if TYPES_PERSONNE_PHYSIQUE.search(o["type_source"] or ""):
        return None, None, None, "personne_physique"
    if o["siret"]:
        s = o["siret"][:9]
        e = (rap.get("sirens") or {}).get(s)
        if e is None and s in cache_api:   # cache partagé de l'API Recherche d'entreprises (pipeline/sirene.py)
            x = cache_api[s]
            e = {"cj": x.get("cj"), "denomination": x.get("nom") if sirene.personne_morale(x.get("cj")) else None}
        if e is None:
            return None, None, None, "siren_inconnu"
        if not sirene.personne_morale(e.get("cj")):
            return None, None, None, "personne_physique"
        return s, e["cj"], e.get("denomination"), "nommé" if e.get("denomination") else "siren_inconnu"
    if not o["nom_source"]:
        return None, None, None, "sans_nom"
    if nom_de_personne_possible(o["nom_source"]):
        return None, None, None, "nom_de_personne_possible"
    k = cle_nom(o["nom_source"])
    e = (rap.get("noms") or {}).get(empreinte(k)) if k else None
    if e is None:
        return None, None, None, "non_rapproche"
    if e.get("candidats") != 1:
        return None, None, None, "non_rapproche" if not e.get("candidats") else "ambigu"
    if not sirene.personne_morale(e.get("cj")) or not e.get("denomination"):
        return None, None, None, "personne_physique"
    return e["siren"], e["cj"], e["denomination"], "nommé"


MOTIFS = {
    "personne_physique": "personne physique ou groupement de personnes physiques (type publié ou catégorie SIRENE)",
    "siren_inconnu": "SIRET publié absent du stock SIRENE",
    "sans_nom": "bénéficiaire non publié",
    "nom_de_personne_possible": "nom pouvant désigner une personne (prénom fréquent, civilité) : jamais rapproché",
    "non_rapproche": "aucune unité légale SIRENE de même nom",
    "ambigu": "plusieurs unités légales SIRENE de même nom",
}


def dep_unique(v) -> str | None:
    """Département publié : un seul code à deux chiffres (ou 2A, 2B, 97x), sinon null (plusieurs départements)."""
    codes = [c.strip() for c in re.split(r"[,;/]", propre(v)) if c.strip()]
    if len(codes) != 1:
        return None
    return codes[0] if re.fullmatch(r"\d{2}|2[AB]|97\d", codes[0]) else None


REGLE_INTITULES = ("Intitulé d'opération publié tel que l'autorité de gestion l'écrit, sauf s'il peut contenir un nom "
                   "de personne (motif « nom_de_personne_possible », filtre de prénoms de pipeline/local.py) ou une "
                   "adresse précise, numéro suivi d'un type de voie (motif « adresse_precise ») : il est alors retiré "
                   "(null), l'opération et ses montants restent publiés et comptés.")


def intitule_publiable(texte, prenoms) -> tuple[str | None, str | None]:
    """Intitulé publiable et motif du retrait : nom de personne possible, ou adresse précise (« … du site 165 rue de
    Paris … » désigne un lieu d'habitation et ses occupants) ; filtre d'adresse partagé (local.objet_avec_adresse)."""
    import local
    if not texte:
        return None, None
    t = local.objet_publiable(texte, prenoms, 200)
    if t is None:
        return None, ("nom_de_personne_possible" if local.contient_nom_de_personne(local.propre(texte), prenoms)
                      else None)
    if local.objet_avec_adresse(texte):
        return None, "adresse_precise"
    return t, None


def produire_listes(ref: dict, a: dict, sortie: Path, par_cci: dict) -> dict:
    import local
    rap = charger_rapprochement()
    cache_api = sirene.charger_cache()
    prenoms = local.prenoms()
    resume = []
    intitules_retires = 0
    motifs_intitules: dict[str, int] = defaultdict(int)
    for nom, conf in LISTES.items():
        ops, ctl = lire_liste(nom)
        e_src = entree(conf["sid"])
        lignes, non_nommes, totaux = [], defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0, 0, 0, 0, 0])
        motifs = defaultdict(int)
        avec_financeurs = nom == "paysdelaloire"
        for o in ops:
            siren, cj, denom, motif = identifier(o, rap, cache_api)
            c_cout = round((o["cout"] or 0) * 100)
            c_ue = round((o["ue"] or 0) * 100)
            t = totaux[(o["periode"] or "non précisée", o["fonds"] or "non précisé")]
            t[0] += 1
            t[1] += c_cout
            t[2] += c_ue
            motifs[motif] += 1
            if motif != "nommé":
                n = non_nommes[(o["periode"] or "non précisée", o["fonds"] or "non précisé", o["annee_debut"], motif)]
                n[0] += 1
                n[1] += c_cout
                n[2] += c_ue
                continue
            t[3] += 1
            t[4] += c_cout
            t[5] += c_ue
            intitule, motif_intitule = intitule_publiable(o["intitule_source"], prenoms)
            if motif_intitule:
                intitules_retires += 1
                motifs_intitules[motif_intitule] += 1
            hors_ue = (round(o["cout"] - o["ue"], 2) if o["cout"] is not None and o["ue"] is not None else None)
            ligne = [o["id"], o["periode"], o["fonds"], o["annee_debut"], o["date_fin"], siren, denom, cj, intitule,
                     o["departement"], o["commune_insee"], o["theme"], o["cout"], o["ue"], hors_ue, o["taux"]]
            if avec_financeurs:
                f = o["financeurs"] or {}
                ligne += [f.get("etat_eur"), f.get("region_eur"), f.get("departement_eur"), f.get("prives_eur"),
                          f.get("autofinancement_eur")]
            lignes.append(ligne)
        colonnes = ["id", "periode", "fonds", "annee_debut", "date_fin", "siren", "denomination", "categorie_juridique",
                    "intitule", "departement", "commune_insee", "theme", "cout_total_eur", "montant_ue_eur",
                    "hors_ue_eur", "taux_ue"]
        if avec_financeurs:
            colonnes += ["etat_eur", "region_eur", "departement_eur", "prives_eur", "autofinancement_eur"]
        lignes.sort(key=lambda l: (l[1] or "", l[2] or "", -(l[13] or 0), l[6] or "", l[0] or "", l[8] or ""))
        comparaisons = []
        for per, cci in conf["programmes"].items():
            for f in sorted({k[1] for k in totaux if k[0] == per}):
                ex = a["exec_fin"].get((cci, f))
                t = totaux[(per, f)]
                if not ex:
                    continue
                ecart = t[1] - ex["decide"]
                comparaisons.append({
                    "periode": per, "fonds": f, "cci": cci,
                    "source": f"liste publiée par l'autorité de gestion ({conf['autorite']}), coût total des opérations",
                    "montant_eur": eur(t[1]),
                    "autre_source": "Commission européenne, cohesiondata 99js-gm52 ou 3git-md5z : coût éligible total des "
                                    "opérations sélectionnées, dernière transmission",
                    "autre_montant_eur": eur(ex["decide"]), "date_reference": a["exec_ref"].get(cci),
                    "ecart_eur": eur(ecart), "ecart_pct": round(100 * ecart / ex["decide"], 1) if ex["decide"] else None,
                    "lecture_ecart": "La liste publiée et la transmission à la Commission n'ont ni la même date ni "
                                     "forcément le même périmètre (coût total ou coût éligible, opérations en cours ou "
                                     "achevées, parts du programme gérées par d'autres services) : les deux montants sont "
                                     "publiés côte à côte, sans être additionnés."})
        periodes = sorted({k[0] for k in totaux})
        doc = {
            "millesime": f"Liste publiée par {conf['autorite']} ({', '.join(periodes)}), collectée le "
                         f"{(e_src.get('collecte_le') or '')[:10] or 'date inconnue'}",
            "source": f"{conf['autorite']}, liste des opérations cofinancées par l'Union européenne ({conf['jeu']}) ; "
                      f"catégorie juridique : stock SIRENE (Insee) ; programmes : cohesiondata.ec.europa.eu",
            "unite": "euros",
            "autorite_de_gestion": conf["autorite"],
            "region": {"code": conf["region"], "nom": REGIONS[conf["region"]]},
            "url": conf["jeu"], "licence": conf["licence"],
            "collecte_le": (e_src.get("collecte_le") or "")[:10] or None,
            "programmes": [{"periode": p, "cci": c, "titre": (ref.get(c) or {}).get("titre")}
                           for p, c in conf["programmes"].items()],
            "regle_personnes_physiques": "Un bénéficiaire est nommé seulement si sa catégorie juridique SIRENE est celle "
                                         "d'une personne morale (2xxx à 9xxx, hors groupements de personnes physiques), "
                                         "sous sa dénomination SIRENE. Les autres opérations sont agrégées par période, "
                                         "fonds, année et motif, sans nom ni intitulé. Intitulé publié seulement s'il ne "
                                         "peut pas contenir un nom de personne. Adresses, descriptions longues et "
                                         "coordonnées ne sont jamais lues.",
            "colonnes": colonnes,
            "definitions": {
                "cout_total_eur": "coût total ou dépenses éligibles de l'opération, tel que publié par l'autorité de gestion",
                "montant_ue_eur": "contribution de l'Union : publiée, ou calculée (coût × taux publié) selon "
                                  "`montant_ue_mode`",
                "hors_ue_eur": "coût total - contribution de l'Union (calcul du projet) : cofinancements nationaux publics "
                               "et privés, autofinancement compris",
                "taux_ue": "taux de cofinancement de l'Union, entre 0 et 1"},
            "montant_ue_mode": ops[0]["ue_mode"] if ops else "publié",
            "operations": lignes,
            "non_nommes": [{"periode": p, "fonds": f, "annee_debut": an, "motif": m, "nombre": v[0],
                            "cout_total_eur": eur(v[1]), "montant_ue_eur": eur(v[2])}
                           for (p, f, an, m), v in sorted(non_nommes.items(),
                                                          key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or 0, kv[0][3]))],
            "motifs": {m: MOTIFS[m] for m in sorted(motifs) if m in MOTIFS},
            "totaux": [{"periode": p, "fonds": f, "operations": v[0], "cout_total_eur": eur(v[1]),
                        "montant_ue_eur": eur(v[2]), "operations_nommees": v[3], "cout_total_nomme_eur": eur(v[4]),
                        "montant_ue_nomme_eur": eur(v[5])} for (p, f), v in sorted(totaux.items())],
            "comparaison_commission": comparaisons,
            "controles": {**ctl, "operations": len(ops), "nommees": len(lignes),
                          "par_motif": {m: motifs[m] for m in sorted(motifs)}},
            "ordre": {"regle": "Opérations nommées par période, fonds, contribution de l'Union décroissante, puis "
                               "dénomination et identifiant ; agrégats par période, fonds, année et motif.",
                      "cles": ["periode", "fonds", "-montant_ue_eur", "denomination", "id"]},
        }
        if avec_financeurs:
            doc["definitions"]["financeurs"] = ("etat_eur, region_eur, departement_eur, prives_eur, autofinancement_eur : "
                                                "montants publiés par financeur (Pays de la Loire seulement)")
        n = dump(sortie / "operations" / f"{nom}.json", doc)
        tc = sum(v[1] for v in totaux.values())
        tn = sum(v[4] for v in totaux.values())
        resume.append({"id": nom, "fichier": f"fonds_europeens/operations/{nom}.json", "autorite_de_gestion": conf["autorite"],
                       "region": conf["region"], "periodes": periodes,
                       "fonds": sorted({k[1] for k in totaux}, key=lambda f: ORDRE_FONDS.index(f) if f in ORDRE_FONDS else 99),
                       "operations": len(ops), "operations_nommees": len(lignes),
                       "cout_total_eur": eur(tc), "montant_ue_eur": eur(sum(v[2] for v in totaux.values())),
                       "part_cout_nommee": round(tn / tc, 4) if tc else None, "url": conf["jeu"],
                       "licence": conf["licence"], "collecte_le": (e_src.get("collecte_le") or "")[:10] or None,
                       "octets": n})
    regionaux = sorted(c for c, v in ref.items() if v["portee"] == "régional" and v["groupe"] in REGIONS
                       and set(par_cci.get(c, {})) & {"FEDER", "FSE", "FSE+", "IEJ", "FTJ"})
    couverts = sorted({c for conf in LISTES.values() for c in conf["programmes"].values()})
    index = {
        "millesime": "Listes d'opérations publiées par six autorités de gestion (programmations 2014-2020 et 2021-2027)",
        "source": "Régions Bretagne, Pays de la Loire, Normandie, Île-de-France et La Réunion (data.gouv.fr et portails "
                  "régionaux) ; stock SIRENE des unités légales (Insee)",
        "unite": "euros",
        "avertissement": "Listes publiées par les autorités de gestion, chacune avec ses colonnes et sa date : elles ne "
                         "couvrent qu'une partie des programmes. Les bénéficiaires nommés de toutes les régions, d'après "
                         "les exports Kohesio de la Commission, sont dans ue/beneficiaires (même argent, autre source : "
                         "ne pas additionner).",
        "regle_personnes_physiques": "Bénéficiaire nommé seulement si sa catégorie juridique SIRENE est celle d'une "
                                     "personne morale ; aucun agriculteur ni entrepreneur individuel nommé ; listes "
                                     "brutes conservées hors du site (data/lake/_restreint).",
        "listes": resume,
        "couverture": {"programmes_couverts": couverts, "programmes_regionaux": len(regionaux),
                       "lecture": f"{len(couverts)} programmes régionaux de la politique de cohésion (FEDER, FSE, FSE+, "
                                  f"IEJ, FTJ) sur {len(regionaux)} ont une liste reprise ici ; les programmes de "
                                  f"développement rural (FEADER) n'ont volontairement aucune liste."},
        "rapprochement": {"methode": (rap.get("methode") or "stock SIRENE absent au dernier rapprochement : opérations "
                                                            "sans SIRET agrégées"),
                          "stock_sirene": rap.get("stock_sirene", {}).get("modifie_le"),
                          "intitules_retires": intitules_retires,
                          "intitules_retires_par_motif": {k: motifs_intitules[k] for k in sorted(motifs_intitules)},
                          "regle_intitules": REGLE_INTITULES},
        "liens": [{"fichier": "ue/beneficiaires/index.json",
                   "lecture": "bénéficiaires nommés de toutes les régions (Kohesio, FTS, Horizon Europe), par département"}],
        "sources_inaccessibles": [x for x in INACCESSIBLES if "Europe en France" in x["source"]],
        "ordre": {"regle": "Listes dans l'ordre alphabétique de leur identifiant.", "cles": ["id"]},
    }
    index["listes"].sort(key=lambda x: x["id"])
    dump(sortie / "operations.json", index)
    return index


# --- Index ------------------------------------------------------------------------------------------------------------


def produire_index(ref, a, par_cci, frr_doc, ops_index, psp, feader_ms, entete_src) -> dict:
    totaux = []
    for per in PERIODES:
        blocs = defaultdict(list)
        for cci, fs in par_cci.items():
            if periode_de(cci) != per:
                continue
            for f, b in fs.items():
                blocs[f].append(b)
        par_fonds = {f: somme_blocs(blocs[f]) for f in cles_fonds(blocs)}
        totaux.append({"periode": per, "par_fonds": par_fonds, "total": somme_blocs(list(par_fonds.values())),
                       "date_execution": max((a["exec_ref"].get(c, "") for c in par_cci
                                              if periode_de(c) == per), default=None) or None,
                       "annee_paiements": a["paie_annee_fin"].get(per)})
    hors = [{"periode": p, "fonds": f, "libelle": HORS_PERIMETRE.get(f, (f, ""))[0],
             "raison": HORS_PERIMETRE.get(f, ("", "hors du périmètre de l'axe"))[1],
             "prevu_ue_eur": eur(v.get("prevu_ue_paiements")) if v.get("prevu_ue_paiements") else None,
             "paye_ue_eur": eur(v.get("paye_ue")) if "paye_ue" in v else None}
            for (p, f), v in sorted(a["hors"].items())]
    # écarts entre sources (jamais tranchés)
    ecarts = []
    for per in PERIODES:
        for f in ORDRE_FONDS:
            p_det = sum(v["ue"] for (c, ff), v in a["prevu"].d.items() if ff == f and periode_de(c) == per)
            p_pai = sum(v["plan_ue"] for (c, ff), v in a["paie_fin"].d.items()
                        if ff == f and periode_de(c) == per and c != "2023FR06AFSP001")
            p_exe = sum(v["prevu_ue"] for (c, ff), v in a["exec_fin"].d.items()
                        if ff == f and periode_de(c) == per)
            if p_det and p_pai and abs(p_det - p_pai) >= 100:
                ecarts.append({"periode": per, "fonds": f, "grandeur": "montant UE prévu",
                               "source": "montants prévus détaillés", "montant_eur": eur(p_det),
                               "autre_source": "jeu des paiements (montant UE prévu net)", "autre_montant_eur": eur(p_pai),
                               "ecart_eur": eur(p_det - p_pai),
                               "lecture_ecart": "versions de programme ou dates d'extraction différentes ; le jeu des "
                                                "paiements retient le montant net des dégagements"})
            if p_det and p_exe and abs(p_det - p_exe) >= 100:
                ecarts.append({"periode": per, "fonds": f, "grandeur": "montant UE prévu",
                               "source": "montants prévus détaillés", "montant_eur": eur(p_det),
                               "autre_source": "jeu d'exécution (montant UE prévu à la dernière transmission)",
                               "autre_montant_eur": eur(p_exe), "ecart_eur": eur(p_det - p_exe),
                               "lecture_ecart": "le jeu d'exécution reprend le plan en vigueur à la date de la "
                                                "transmission, le jeu des montants prévus la dernière version adoptée"})
        for t in totaux:
            if t["periode"] != per:
                continue
            for f, b in t["par_fonds"].items():
                if b["decide_eur"] is not None and b["prevu_total_eur"] and b["decide_eur"] > b["prevu_total_eur"]:
                    ecarts.append({"periode": per, "fonds": f, "grandeur": "décidé et prévu",
                                   "source": "coût éligible des opérations sélectionnées (décidé)",
                                   "montant_eur": b["decide_eur"], "autre_source": "montant total prévu (UE et national)",
                                   "autre_montant_eur": b["prevu_total_eur"],
                                   "ecart_eur": eur(round(b["decide_eur"] * 100) - round(b["prevu_total_eur"] * 100)),
                                   "lecture_ecart": "le décidé publié dépasse le prévu ; la source n'en donne "
                                                    "pas la raison : écart publié tel quel, sans interprétation"})
    pa = a["paie_fin"].get(("2023FR06AFSP001", "FEADER"))
    if pa and feader_ms:
        for grandeur, x, y in (("montant UE prévu", pa["plan_ue"], feader_ms.get("prevu_ue_eur")),
                               ("paiements nets cumulés", pa["total"], feader_ms.get("paye_ue_eur"))):
            if y is not None and abs(x - round(y * 100)) >= 100:
                ecarts.append({"periode": "2023-2027", "fonds": "FEADER", "grandeur": grandeur,
                               "source": "cohesiondata pbbz-hmfu (paiements 2021-2027 par programme)",
                               "montant_eur": eur(x), "autre_source": "cohesiondata 7wr2-9vpr (FEADER par État membre)",
                               "autre_montant_eur": y, "ecart_eur": eur(x - round(y * 100)),
                               "lecture_ecart": "deux jeux de la Commission mis à jour à des dates différentes"})
    feader = None
    if psp or feader_ms:
        feader = {
            "periode": "2023-2027 (plan stratégique PAC)",
            "prevu_ue_feader_eur": feader_ms.get("prevu_ue_eur") if feader_ms else None,
            "paye_ue_feader_eur": feader_ms.get("paye_ue_eur") if feader_ms else None,
            "source_feader": "cohesiondata 7wr2-9vpr (paiements du FEADER par État membre)",
            "plan_strategique_pac": psp,
            "lecture": "Le plan stratégique PAC regroupe le FEAGA (paiements directs aux exploitants : aides individuelles, "
                       "non reprises ici) et le FEADER. La source publie le financement national obligatoire et le "
                       "financement national additionnel pour l'ensemble du plan, sans les rattacher à un fonds : ils "
                       "sont présentés à côté de la part UE du FEADER, sans être additionnés. Les années 2021 et 2022 du "
                       "FEADER sont rattachées aux programmes de développement rural 2014-2020 (période de transition)."}
    return {
        **entete_src,
        "avertissement": "Ce que l'Union européenne finance en France par ses fonds structurels et d'investissement, avec "
                         "les cofinancements nationaux prévus. Quatre grandeurs, jamais additionnées entre elles : prévu "
                         "(plan des programmes), décidé (coût des opérations sélectionnées), dépensé (dépenses déclarées "
                         "par les bénéficiaires) et payé par l'UE (versements de la Commission). Ce que la France verse "
                         "au budget de l'UE est dans ue/contribution.json.",
        "collecte_le": date_sources("europe"),
        "periodes": PERIODES,
        "fonds": [{"code": FONDS[k][0], "libelle": FONDS[k][1], "code_source": k}
                  for k in sorted(FONDS, key=lambda k: ORDRE_FONDS.index(FONDS[k][0]))
                  if any(FONDS[k][0] in t["par_fonds"] for t in totaux)],
        "definitions": {
            "prevu_ue_eur": "contribution de l'Union inscrite au plan financier du programme (dernière version adoptée)",
            "prevu_national_eur": "cofinancement national prévu, public et privé ; 2014-2020 : publié ; 2021-2027 : total "
                                  "prévu - contribution de l'Union (calcul du projet)",
            "prevu_total_eur": "contribution de l'Union + cofinancement national prévu",
            "decide_eur": "coût éligible total (Union, national, privé) des opérations sélectionnées, cumulé à la dernière "
                          "transmission",
            "depense_eur": "dépenses éligibles déclarées par les bénéficiaires, cumulées à la dernière transmission",
            "paye_ue_eur": "paiements nets de la Commission (préfinancements et paiements intermédiaires, moins les "
                           "recouvrements), cumulés depuis le début de la période",
            "engagements_ue": "crédits d'engagement de l'Union inscrits au plan financier, par année budgétaire"},
        "perimetre": {
            "fonds_retenus": "FEDER, FSE, FSE+, IEJ, FTJ, FEADER (développement rural), FEAMP, FEAMPA",
            "hors_perimetre": hors,
            "interreg": "Programmes de coopération territoriale (Interreg) : multi-pays, non ventilés par pays dans la "
                        "source ; non repris.",
            "feader": "FEADER publié par programme et par mesure (montants agrégés) ; aucune liste de bénéficiaires du "
                      "FEADER ni des aides de la PAC n'est collectée.",
            "frr": "Facilité pour la reprise et la résilience : fonds reçus et emploi par année (Eurostat), frr.json."},
        "totaux": totaux,
        "feader_psp_2023_2027": feader,
        "frr": {"fichier": "fonds_europeens/frr.json", "annees": frr_doc["annees"],
                "fonds_recus_cumul_eur": frr_doc["fonds_recus"]["cumul_eur"]},
        "operations": {"fichier": "fonds_europeens/operations.json", "listes": len(ops_index["listes"]),
                       "operations": sum(x["operations"] for x in ops_index["listes"]),
                       "operations_nommees": sum(x["operations_nommees"] for x in ops_index["listes"])},
        "ecarts": ecarts,
        "fichiers": [
            {"fichier": "fonds_europeens/programmes.json", "contenu": "un programme par ligne : prévu, décidé, dépensé, "
                                                                      "payé, par fonds"},
            {"fichier": "fonds_europeens/regions.json", "contenu": "par région et groupe de programmes, par période, "
                                                                   "fonds et année"},
            {"fichier": "fonds_europeens/themes.json", "contenu": "objectifs thématiques (2014-2020), mesures du FEADER, "
                                                                  "objectifs stratégiques et spécifiques, domaines "
                                                                  "d'intervention (2021-2027)"},
            {"fichier": "fonds_europeens/annees.json", "contenu": "engagements annuels, paiements et exécution cumulés "
                                                                  "par année"},
            {"fichier": "fonds_europeens/frr.json", "contenu": "facilité pour la reprise et la résilience (Eurostat)"},
            {"fichier": "fonds_europeens/operations.json", "contenu": "listes d'opérations des autorités de "
                                                                     "gestion"}],
        "liens": [
            {"fichier": "ue/contribution.json", "lecture": "ce que la France verse au budget de l'UE (prélèvement sur "
                                                           "recettes) et son usage par rubrique"},
            {"fichier": "ue/retours.json", "lecture": "dépenses de l'UE en France par année et par rubrique, solde net"},
            {"fichier": "ue/beneficiaires/index.json", "lecture": "bénéficiaires nommés des fonds européens (Kohesio, "
                                                                  "FTS, Horizon Europe), par département"}],
        "sources": sources_publiees(),
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "limites": [
            "Les montants prévus, décidés, dépensés et payés ont des dates de référence différentes (dernière "
            "transmission de chaque programme, dernière année de paiements) : ils se lisent côte à côte.",
            "2021-2027 : le décidé et le dépensé sont publiés en coût total seulement, sans part de l'Union ; pour les "
            "programmes à assistance technique forfaitaire, le prévu comprend ce forfait, le décidé et le dépensé non.",
            "Les programmes 2014-2020 portent sur les régions d'avant 2016 : ils sont rattachés à la région actuelle qui "
            "les contient (champ `territoire` de programmes.json).",
            "Les programmes interrégionaux (massifs, fleuves) et nationaux ne sont pas répartis entre régions.",
            "Le cofinancement national 2021-2027 est déduit (total prévu - part de l'Union) ; il comprend les "
            "financements publics et privés prévus."],
        "confidentialite": "Aucune personne physique : montants agrégés par programme, fonds, thème, région et année ; "
                           "listes d'opérations avec bénéficiaires nommés seulement s'ils sont des personnes morales.",
        "ordre": {"regle": "Fonds dans l'ordre FEDER, FSE, FSE+, IEJ, FTJ, FEADER, FEAMP, FEAMPA ; périodes dans l'ordre "
                           "chronologique. Aucun classement par montant.", "cles": ["periode", "fonds"]},
    }


def sources_publiees() -> list[dict]:
    out = []
    for sid, (jeu, titre) in JEUX.items():
        e = entree(sid)
        out.append({"id": sid, "titre": titre, "producteur": "Commission européenne", "url": url_jeu(jeu),
                    "licence": LICENCE_COHESION, "mise_a_jour_source": maj_jeu(jeu),
                    "collecte_le": (e.get("collecte_le") or "")[:10] or None})
    for sid, ds in EUROSTAT.items():
        e = entree(sid)
        out.append({"id": sid, "titre": f"Eurostat {ds}", "producteur": "Eurostat",
                    "url": f"https://ec.europa.eu/eurostat/databrowser/view/{ds}/default/table",
                    "licence": "CC BY 4.0 (Eurostat)", "mise_a_jour_source": None,
                    "collecte_le": (e.get("collecte_le") or "")[:10] or None})
    for nom, conf in LISTES.items():
        e = entree(conf["sid"])
        out.append({"id": conf["sid"], "titre": f"Liste des opérations, {conf['autorite']}", "producteur": conf["autorite"],
                    "url": conf["jeu"], "licence": conf["licence"], "mise_a_jour_source": None,
                    "collecte_le": (e.get("collecte_le") or "")[:10] or None})
    return out


def lire_psp() -> tuple[dict | None, dict | None]:
    """Plan stratégique PAC 2023-2027 (totaux publiés) et FEADER 2023-2027 de la France (prévu UE, paiements)."""
    psp = None
    for r in lire_json_source("fe_cohesion_psp_2327"):
        if r.get("csp_version_status") == "Total CAP budget" or propre(r.get("so_short_and_total_budget")) == "Total CAP budget":
            psp = {"cci": r.get("cci"), "version": r.get("csp_version"),
                   "budget_total_plan_eur": eur(cents(r.get("cap_budget_2023_2027_including_additional_national_financing"))),
                   "financement_ue_plan_eur": eur(cents(r.get("eu_funding_in_eur"))),
                   "financement_national_obligatoire_eur": eur(cents(r.get("compulsory_member_state_funding_in_eur"))),
                   "financement_national_additionnel_eur": eur(cents(r.get("optional_additional_national_financing_in_eur"))),
                   "source": "cohesiondata vvmb-dsbj, ligne « Total CAP budget » (ensemble du plan : FEAGA et FEADER)"}
    fe = None
    for r in lire_json_source("fe_cohesion_feader_2327"):
        if r.get("fund") == "FR":   # colonne « fund » du jeu : code de l'État membre
            fe = {"prevu_ue_eur": eur(cents(r.get("actual_plan_eu_amt_latest_adop"))),
                  "paye_ue_eur": eur(cents(r.get("total_net_payments")))}
    return psp, fe


def verifier_licences() -> dict:
    """Licence publiée par cohesiondata pour chaque jeu utilisé (métadonnées collectées)."""
    out = {}
    for f in fichiers("fe_cohesion_metadonnees"):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[f.stem] = (d.get("license") or {}).get("name")
    return out


def produire(sortie: Path = SORTIE) -> dict:
    d14, d21 = lire_1420(), lire_2127()
    ref = programmes_ref({**d14["titres"], **d21["titres"]})
    a = construire(ref, d14, d21)
    maj = sorted(x for x in (maj_jeu(j) for j, _ in JEUX.values()) if x)
    entete = {
        "millesime": f"Programmations 2014-2020 et 2021-2027 ; données de la Commission mises à jour du {maj[0]} au "
                     f"{maj[-1]}" if maj else "Programmations 2014-2020 et 2021-2027",
        "source": "Commission européenne, Cohesion Open Data Platform (cohesiondata.ec.europa.eu : e4v6-qrrq, 99js-gm52, "
                  "gayr-92qh, rmer-4wcy, hgyj-gyin, 3git-md5z, pbbz-hmfu, 9qee-iv7c, f5vn-zy5i), France",
        "unite": "euros",
    }
    frr_doc = produire_frr()
    psp, feader_ms = lire_psp()
    sortie.mkdir(parents=True, exist_ok=True)
    prog_doc, par_cci = produire_programmes(ref, a, {**entete, "avertissement": "Un programme par ligne. Prévu, décidé, "
                                                     "dépensé et payé n'ont pas la même date de référence ; ils ne "
                                                     "s'additionnent pas entre eux."})
    dump(sortie / "programmes.json", prog_doc)
    dump(sortie / "regions.json", produire_regions(ref, a, par_cci, {**entete, "avertissement": "Régions actuelles ; les "
         "programmes 2014-2020 des régions d'avant 2016 sont rattachés à la région qui les contient. Les programmes "
         "nationaux et interrégionaux forment des groupes à part : ils ne sont pas répartis entre régions. Séries "
         "annuelles : montants cumulés depuis le début de la période."}))
    dump(sortie / "themes.json", produire_themes(a, {**entete, "avertissement": "Montants par thème tels que déclarés "
         "dans les plans des programmes. 2021-2027 : un fonds n'est compté que dans une dimension (domaine "
         "d'intervention, ou type d'intervention pour le FEAMPA) ; libellés des objectifs spécifiques traduits par le "
         "projet depuis les libellés courts de la Commission (`libelle_source`)."}))
    dump(sortie / "annees.json", produire_annees(a, frr_doc, {**entete, "avertissement": "Paiements et exécution : "
         "montants cumulés publiés ; les montants annuels sont la différence entre deux cumuls (calcul du projet). "
         "L'année la plus récente des paiements est partielle (`annee_partielle`)."}))
    dump(sortie / "frr.json", frr_doc)
    ops_index = produire_listes(ref, a, sortie, par_cci)
    index = produire_index(ref, a, par_cci, frr_doc, ops_index, psp, feader_ms,
                           {**entete, "source": entete["source"] + " ; Eurostat gov_rrf_fa, gov_rrf_use ; listes "
                                                                  "d'opérations de six autorités de gestion"})
    index["verification"] = {"licences_cohesiondata": verifier_licences(),
                             "programmes_non_rattaches": sorted(c for c, v in ref.items() if v["groupe"] == "non_rattache"
                                                                and c in par_cci)}
    dump(sortie / "index.json", index)
    bilan = {per["periode"]: per["total"] for per in index["totaux"]}
    print(json.dumps(bilan, ensure_ascii=False), file=sys.stderr)
    return index


def collecter() -> int:
    ids = sorted(set(JEUX) | set(EUROSTAT) | {"fe_cohesion_metadonnees"} | {c["sid"] for c in LISTES.values()})
    r = subprocess.run([sys.executable, str(ROOT / "collecte" / "collecte.py"), *ids], cwd=ROOT)
    resoudre()
    return r.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("collecter")
    sp.add_parser("resoudre")
    p = sp.add_parser("produire")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.cmd == "collecter":
        return collecter()
    if a.cmd == "resoudre":
        resoudre()
        return 0
    produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
