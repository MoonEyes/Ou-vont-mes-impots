"""Délibérations et budgets publiés en données ouvertes par les collectivités (schémas nationaux SCDL).

Collecteur générique : tous les jeux de data.gouv.fr déclarés conformes au schéma « Délibérations »
(schema=scdl/deliberations) ou « Budget » (schema=scdl/budget), listés par l'API de data.gouv.fr. Seules des
métadonnées sont publiées : collectivité (SIREN), date, objet (filtré), thème (matière de la nomenclature ACTES),
lien vers l'acte sur le site de la collectivité. Jamais le texte des actes, jamais les PDF, jamais les votes (ni
nominatifs ni décomptes), jamais un nom d'élu, d'agent ou de particulier.

Entrées (réseau, `collecter`, reprenable ; chaque fichier contrôlé par collecte/integrite.py avant renommage) :
  - API data.gouv.fr /api/1/datasets/?schema=scdl/deliberations et ?schema=scdl/budget (liste des jeux et ressources)
      -> data/lake/deliberations/jeux_<schema>.json
  - ressources « Délibérations » (CSV ou JSON) -> data/lake/_restreint/deliberations/<jeu>/<ressource>.<ext>
    (les objets peuvent contenir des noms : entrepôt restreint, jamais publié tel quel). Les fichiers Mégalis déjà
    collectés par l'entrée `decisions_megalis_deliberations` (data/lake/_restreint/decisions/) sont réutilisés quand
    leur taille est celle annoncée par data.gouv.fr.
  - ressources « Budget » : téléchargées une à une, réduites tout de suite à un extrait agrégé (documents publiés par
    SIRET, exercice et étape ; dépenses réelles d'équipement des comptes 20 hors 204, 204, 21, 23), le brut est
    supprimé -> data/lake/deliberations/budgets/<jeu>/<ressource>.extrait.csv (les budgets Mégalis font 1,7 Go).
Sorties (site/data/deliberations/, `produire`, sans réseau, chaque fichier < 1 Mo, avec `millesime` et `source`) :
  index.json                     couverture (collectivités et part de la population), jeux lus, règles, exclusions
  collectivites/<siren>.json     par collectivité : comptes par année et par matière, délibérations récentes
                                 publiables par matière (date, matière, objet, lien), exclusions comptées
  budgets.json                   documents budgétaires publiés au format national, par collectivité
Fonction lue par pipeline/investissement_communes.py : `votes_equipement()` (crédits votés d'équipement).

Règles de confidentialité (bloquantes) :
  - objet publié seulement s'il passe local.objet_publiable (civilités, prénoms fréquents suivis d'un nom) et ne
    contient pas d'adresse (numéro et voie) ;
  - urbanisme, domaine et patrimoine, préemption et foncier (matières 2 et 3 de la nomenclature ACTES, ou mots du
    foncier dans l'objet) : délibération exclue (seulement comptée) dès que l'objet peut désigner un particulier :
    adresse, référence cadastrale, mot en capitales hors sigles connus (nom de famille), « consorts »,
    « succession », « propriété de »... ; dans le doute, exclue ;
  - un lien dont le chemin contient un nom possible n'est pas publié (la délibération reste, sans lien) ;
  - auteur hors sphère publique (SIREN absent ou catégorie juridique privée) : ligne exclue et comptée.

Commandes :
  python pipeline/deliberations.py collecter     # réseau
  python pipeline/deliberations.py produire      # sans réseau
  python pipeline/deliberations.py               # les deux
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch  # noqa: E402
import local  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "deliberations"
RESTREINT = ROOT / "data" / "lake" / "_restreint" / "deliberations"
MEGALIS_DEJA = ROOT / "data" / "lake" / "_restreint" / "decisions" / "decisions_megalis_deliberations"
OUT = ROOT / "site" / "data" / "deliberations"
GEO = ROOT / "site" / "data" / "local" / "geo"
API = "https://www.data.gouv.fr/api/1/datasets/"
PAGE_JEU = "https://www.data.gouv.fr/datasets/"
SCHEMAS = {"deliberations": "scdl/deliberations", "budget": "scdl/budget"}
DOC_SCHEMA = {"deliberations": "https://schema.data.gouv.fr/scdl/deliberations.html",
              "budget": "https://schema.data.gouv.fr/scdl/budget.html"}
MAX_OCTETS = 1_000_000
MAX_RESSOURCE = 600_000_000      # au-delà : ressource notée « trop volumineuse », non lue
PAR_MATIERE = 12                 # délibérations récentes publiées par matière et par collectivité
LONGUEUR_OBJET = 140

MATIERES = {"1": "Commande publique", "2": "Urbanisme", "3": "Domaine et patrimoine", "4": "Fonction publique",
            "5": "Institutions et vie politique", "6": "Libertés publiques et pouvoirs de police",
            "7": "Finances locales", "8": "Domaines de compétences par thèmes", "9": "Autres domaines de compétences",
            "0": "Matière non renseignée"}
# Catégories juridiques (INSEE) -> type publié
CJ_TYPES = {"7210": "commune", "7220": "departement", "7230": "region", "7229": "collectivite_territoriale",
            "7225": "collectivite_territoriale", "7343": "epci", "7344": "epci", "7346": "epci",
            "7348": "epci"}
LIB_TYPES = {"commune": "communes", "epci": "intercommunalités", "departement": "départements", "region": "régions",
             "collectivite_territoriale": "collectivités territoriales à statut particulier",
             "autre_public": "autres organismes publics (CCAS, syndicats, établissements publics)"}
TOTAUX_REFERENCE = {"departement": 101, "region": 18}
ABSENCE = "ne publie pas ses délibérations en données ouvertes"

MOTIFS = {"nom_possible": "objet pouvant contenir un nom de personne (civilité, prénom suivi d'un nom)",
          "foncier_particulier": "urbanisme, préemption ou foncier : objet pouvant désigner un particulier (nom, "
                                 "adresse, référence cadastrale)",
          "adresse_possible": "objet contenant une adresse (numéro et voie)",
          "objet_vide": "objet absent",
          "date_invalide": "date d'adoption absente ou illisible (comptée à part dans `sans_date`)",
          "auteur_non_public": "auteur sans SIREN valide ou hors sphère publique (catégorie juridique)"}

FONCIER_RE = re.compile(
    r"preempt|cession|acqui|vente|echange|bail|baux|servitude|parcelle|cadastr|indivision|succession|consorts"
    r"|propriet|expropri|alignement|declassement|retrocession|portage|sans maitre|vacant|alienation|\bdia\b"
    r"|terrain|immeuble|maison|logement|lot\b|lotissement|bornage|droit de passage")
ADRESSE_RE = re.compile(
    r"\b(rue|avenue|av|bd|boulevard|chemin|impasse|allee|route|quai|cours|lieu[- ]?dit|hameau|lotissement"
    r"|residence|square|passage|sentier|faubourg|voie|ruelle|venelle|carrefour|rond[- ]point|cite|chez)\b")
ADRESSE_NUMERO_RE = re.compile(r"\b\d{1,4}\s*(bis|ter)?\s*,?\s*(rue|avenue|av|bd|boulevard|chemin|impasse|allee"
                               r"|route|quai|place|lieu[- ]?dit|hameau|residence|square|passage|sentier|faubourg)\b")
PARCELLE_RE = re.compile(r"\b(section|parcelles?|cadastr\w*|n°|no)\b|\b[A-Z]{1,2}\s?\d{1,4}\b")
PERSONNE_RE = re.compile(
    r"\b(consorts?|succession|indivision|heritiers?|epoux|epouse|veuve|famille|proprietaires?|propriete de"
    r"|propriete|appartenant|monsieur|madame|mme|mlle|mr|m\.|sci|gfa|earl|gaec)\b")
# Mots à majuscule initiale admis dans un objet foncier (institutions) ; tout autre mot à majuscule après le premier
# peut être un nom de famille ou un lieu-dit : objet exclu.
MAJUSCULES_ADMISES = {"Commune", "Communes", "Ville", "Département", "Departement", "Région", "Region", "État", "Etat",
                      "Métropole", "Metropole", "Communauté", "Communaute", "Conseil", "Établissement",
                      "Etablissement", "Office", "Syndicat", "Société", "Societe", "Agence"}
SIGLES = {"PLU", "PLUI", "PLUIH", "PLH", "PLUM", "SCOT", "ZAC", "ZAE", "ZA", "ZI", "SAFER", "EPF", "EPFL", "EPFR",
          "SPL", "SEM", "DPU", "DIA", "OAP", "PADD", "RLP", "RLPI", "ENS", "DUP", "SNCF", "EDF", "ENEDIS", "GRDF",
          "SDIS", "CCAS", "CIAS", "EHPAD", "ONF", "CAUE", "DDTM", "DDT", "ANRU", "OPAH", "ORT", "PVD", "ACV", "TVA",
          "HT", "TTC", "RD", "RN", "VC", "CR", "AFU", "AFUL", "PUP", "TA", "PAE", "ZAD", "ZPPAUP", "AVAP", "SPR",
          "PSMV", "SRU", "ALUR", "ELAN", "OPH", "SA", "HLM", "SPA", "SIVU", "SIVOM", "EPCI", "CC", "CA", "CU",
          "PPRI", "PPR", "PPRN", "SDAGE", "SAGE", "GEMAPI", "DSP", "AMO", "MOE", "BP", "BS", "DM", "CA", "CFE",
          "TFPB", "TFNB", "TEOM", "TLPE", "DETR", "DSIL", "FCTVA", "FEDER", "FEADER", "LEADER", "CAF", "ARS",
          "CNAS", "CDG", "CNFPT", "RIFSEEP", "IFSE", "CIA", "NBI", "CET", "ATSEM", "ALSH", "RAM", "RPE", "EAJE",
          "PEDT", "CTG", "CEJ", "ADS", "ERP", "PMR", "LED", "VRD", "AEP", "STEP", "SPANC", "SAUR", "SIAEP", "SDE",
          "SYDEV", "SYDELA", "SDEF", "SDE22", "SDE35", "SDEM", "FIC", "SAS", "SARL", "SCIC", "SCOP", "II", "III",
          "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "ER", "RER", "TER", "TGV", "BHNS", "PEM", "PDU", "PDM",
          "PCAET", "TEPOS", "CRTE", "PETR", "CDC", "DGF", "DSR", "DSU", "DNP", "FPIC", "AC", "DSC", "AP", "CP",
          "APCP", "PPI", "ZNIEFF", "SIG", "MAPA", "AO", "BOAMP", "JOUE", "DCE", "CCAP", "CCTP"}

# Mots courants écrits en capitales dans les objets (rubriques, mots de liaison) : ni noms ni lieux. Relevés parmi les
# mots en capitales les plus fréquents des objets fonciers lus le 18/11/2026, noms de famille et de lieux écartés.
GENERIQUES = {
    "AFFAIRE", "AFFAIRES", "DCM", "URBANISME", "LOT", "LOTS", "TRAVAUX", "VEFA", "GROUPES", "GROUPE", "APPROBATION",
    "LES", "DES", "DU", "DE", "LA", "LE", "FONCIER", "FONCIERE", "FONCIERES", "MONTANTS", "CRAC", "TOTAL", "POUR",
    "ANNUELS", "ANNUEL", "HABITAT", "DECLARATION", "COMMUNE", "ETAT", "ECOLE", "ECOLES", "DELIBERATION", "LOGEMENT",
    "LOGEMENTS", "VILLE", "UNANIMITE", "MAM", "CONVENTION", "FINANCES", "INTITULES", "SERVICE", "SERVICES",
    "MAJORITE", "DELIB", "PLAFONDS", "VIE", "FONCTIONS", "AMENAGEMENT", "AMENAGEMENTS", "DEL", "CADRE", "BUDGET",
    "DOMAINE", "PLAI", "PUBLIC", "PUBLICS", "PUBLIQUE", "CGCT", "SUR", "OPAC", "ANNULE", "REMPLACE", "PLS",
    "CONSTRUCTION", "GIP", "GPA", "DEPENSES", "PLUS", "OPAH-RU", "SANS", "CFU", "CONSIDERANT", "CODIR",
    "DEVELOPPEMENT", "EPFB", "RECETTES", "FSL", "REUNION", "AUX", "ELEMENTAIRE", "RAR", "ECONOMIE", "MISE",
    "COMMUNAL", "COMMUNALE", "COMMUNAUX", "COMMUNALES", "LOCAL", "PROJET", "SCCV", "PAR", "MARCHES", "MARCHE",
    "MODIFICATION", "ECONOMIQUE", "ANAH", "PATRIMOINE", "LYCEES", "FOURNITURE", "ADMINISTRATION", "GENERALE",
    "BATIMENTS", "BATIMENT", "VOIRIE", "ENVIRONNEMENT", "SCOLAIRES", "SCOLAIRE", "SPORTS", "SPORT", "CULTURE",
    "ENFANCE", "JEUNESSE", "RESSOURCES", "HUMAINES", "INTERCOMMUNALITE", "ACQUISITION", "ACQUISITIONS", "CESSION",
    "CESSIONS", "VENTE", "TERRAIN", "TERRAINS", "MAISON", "TRANSITION", "ECOLOGIQUE", "MOBILITES", "EAU",
    "ASSAINISSEMENT", "RESEAUX", "ESPACES", "VERTS", "DROIT", "PREEMPTION", "URBAIN", "RURAL", "ZONE", "ZONES",
    "SECTEUR", "QUARTIER", "CENTRE", "BOURG", "PROGRAMME", "OPERATION", "OPERATIONS", "AVENANT", "MODIFICATIF",
    "PRECISION", "RECTIFICATIF", "RECTIFICATION", "ERREUR", "MATERIELLE", "ETUDE", "ETUDES", "SOCIAL", "SOCIAUX",
    "SOLIDARITE", "CITOYENNETE", "TOURISME", "NUMERIQUE", "ENERGIE", "AGRICULTURE", "ECONOMIQUES", "POLITIQUE",
    "PLAN", "SCHEMA", "DIRECTEUR", "LOCALE", "LOCAUX", "AIDE", "AIDES", "SUBVENTION", "SUBVENTIONS", "NOUVEAU",
    "NOUVELLE", "ANNEE", "PREMIER", "SECOND", "TRANCHE", "PHASE", "MAIRIE", "EGLISE", "SALLE", "SALLES",
    "CIMETIERE", "STADE", "GYMNASE", "MEDIATHEQUE", "BIBLIOTHEQUE", "CANTINE", "RESTAURANT", "PISCINE", "CRECHE",
    "PARKING", "PARC", "JARDIN", "JARDINS", "ESPACE", "ROUTE", "CHEMINS", "RURAUX", "DEPARTEMENTALE", "NATIONALE",
    "DEPARTEMENT", "REGION", "METROPOLE", "AGGLOMERATION", "COMMUNAUTE", "COMMUNES", "SYNDICAT", "OFFICE",
}
LEGENDE_RECENTES = ["date", "matiere", "objet", "lien", "jeu"]


# --- Utilitaires -----------------------------------------------------------------------------------------------------


def sans_accents(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()


def dump(path: Path, obj) -> int:
    """JSON compact et trié (sorties identiques octet pour octet), renommage atomique ; garde-fou < 1 Mo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    n = len(texte.encode("utf-8"))
    if n >= MAX_OCTETS:
        raise SystemExit(f"{path} : {n} octets, au-delà de {MAX_OCTETS}")
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(texte, encoding="utf-8")
    tmp.replace(path)
    return n


def lire_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def telecharger(url: str, dest: Path, octets_attendus: int | None = None, essais: int = 8) -> Path:
    """Téléchargement en flux vers .part avec reprise (Range), contrôle d'intégrité, renommage atomique.
    401/403 : arrêt sans contournement (local.http_get) ; 429 et coupures : reprises espacées."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    erreur = None
    for i in range(essais):
        debut = tmp.stat().st_size if tmp.exists() else 0
        entetes = {**fetch.HEADERS, **({"Range": f"bytes={debut}-"} if debut else {})}
        try:
            with requests.get(url, headers=entetes, stream=True, timeout=300) as r:
                if r.status_code in (401, 403):
                    raise SystemExit(f"{url} : accès refusé (HTTP {r.status_code}), source ignorée sans contournement")
                if r.status_code == 416:  # déjà complet
                    break
                if r.status_code >= 400:
                    erreur = f"HTTP {r.status_code}"
                    if r.status_code != 429 and r.status_code < 500:
                        raise SystemExit(f"{url} -> HTTP {r.status_code}")
                    time.sleep(min(60, 5 + 5 * i))
                    continue
                mode = "ab" if debut and r.status_code == 206 else "wb"
                with tmp.open(mode) as fh:
                    for bloc in r.iter_content(1 << 20):
                        fh.write(bloc)
                if octets_attendus is None:
                    octets_attendus = fetch.octets_annonces(r) if mode == "wb" else None
            break
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as exc:
            erreur = exc.__class__.__name__
            time.sleep(min(60, 5 + 5 * i))
    else:
        raise RuntimeError(f"{url} injoignable après {essais} essais ({erreur})")
    fetch.remplacer_si_valide(tmp, dest, nom=dest.name, octets_attendus=octets_attendus)
    return dest


def get_json(url: str, params: dict | None = None):
    return local.http_get(url, params=params, essais=8, timeout=120).json()


# --- Liste des jeux (API data.gouv.fr) ----------------------------------------------------------------------------


def siret_organisation(org_id: str, cache: dict) -> str | None:
    """SIRET déclaré par l'organisation qui publie le jeu (data.gouv.fr, champ business_number_id)."""
    if org_id not in cache:
        try:
            d = get_json(f"https://www.data.gouv.fr/api/1/organizations/{org_id}/")
            s = re.sub(r"\D", "", str(d.get("business_number_id") or ""))
            cache[org_id] = s if len(s) == 14 else None
        except (RuntimeError, SystemExit):
            cache[org_id] = None
    return cache[org_id]


def lister_jeux(cle: str) -> list[dict]:
    """Jeux déclarés au schéma, réduits aux champs utiles, triés par identifiant."""
    jeux, url, params, orgs = [], API, {"schema": SCHEMAS[cle], "page_size": 100}, {}
    while url:
        d = get_json(url, params)
        for ds in d["data"]:
            res = []
            for r in ds.get("resources") or []:
                if ((r.get("schema") or {}).get("name") or "") != SCHEMAS[cle]:
                    continue
                res.append({"id": r["id"], "titre": r.get("title") or "", "format": (r.get("format") or "").lower(),
                            "url": r.get("url") or "", "octets": r.get("filesize"),
                            "modifie": (r.get("last_modified") or "")[:10]})
            jeux.append({"id": ds["id"], "titre": ds.get("title") or "", "slug": ds.get("slug") or "",
                         "organisation": (ds.get("organization") or {}).get("name") or "",
                         "organisation_siret": siret_organisation(ds["organization"]["id"], orgs)
                         if ds.get("organization") else None,
                         "licence": ds.get("license") or "", "modifie": (ds.get("last_modified") or "")[:10],
                         "ressources": sorted(res, key=lambda x: x["id"])})
        url, params = d.get("next_page"), None
    return sorted(jeux, key=lambda x: x["id"])


def extension(r: dict) -> str | None:
    f = r["format"]
    chemin = urlparse(r["url"]).path.lower()
    if f in ("csv", "json") or chemin.endswith((".csv", ".json")):
        return "json" if (f == "json" or chemin.endswith(".json")) and not chemin.endswith(".csv") else "csv"
    return None


# --- Budgets : extrait agrégé ---------------------------------------------------------------------------------------


def _col(cols, *motifs):
    return local.colonne(cols, *motifs)


def _nombre_sql(c: str) -> str:
    return (f"try_cast(replace(replace(replace(trim(cast(\"{c}\" as varchar)), ' ', ''), chr(160), ''), ',', '.') "
            f"as double)")


def extraire_budget(brut: Path, dest: Path, fmt: str) -> dict:
    """Brut SCDL Budget -> extrait CSV : siret, annee, etape, poste, lignes, sommes des montants. Lu par DuckDB."""
    con = local.ddb()
    con.execute("SET memory_limit='1GB'; SET threads=1; SET preserve_insertion_order=false")
    if fmt == "json":
        q = f"read_json_auto('{brut}', format='auto', maximum_object_size=200000000)"
    else:
        q = f"read_csv('{brut}', all_varchar=true, header=true, ignore_errors=true, sample_size=-1)"
    try:
        cols = [d[0] for d in con.execute(f"select * from {q} limit 0").description]
    except Exception as exc:  # fichier illisible : noté
        return {"etat": "illisible", "detail": exc.__class__.__name__}
    c = {k: _col(cols, *m) for k, m in {
        "natdec": ("bgtnatdec",), "annee": ("bgtannee",), "siret": ("bgtsiret",), "nom": ("bgtnom",),
        "nature": ("bgtnature",), "contnat": ("bgtcontnat",), "opbudg": ("bgtopbudg",), "codrd": ("bgtcodrd",),
        "propnouv": ("bgtmtpropnouv",), "prev": ("bgtmtprev",), "credouv": ("bgtcredouv",), "real": ("bgtmtreal",),
        "rarprec": ("bgtmtrarprec",)}.items()}
    if not (c["natdec"] and c["annee"] and c["siret"] and c["nature"]):
        return {"etat": "non_conforme", "detail": "colonnes BGT_NATDEC, BGT_ANNEE, BGT_SIRET ou BGT_NATURE absentes"}
    nat = f"regexp_replace(cast(\"{c['nature']}\" as varchar), '[^0-9]', '', 'g')"
    if c["contnat"]:  # certains producteurs mettent l'article dans BGT_CONTNAT
        nat = (f"case when length({nat}) >= 3 then {nat} else regexp_replace(cast(\"{c['contnat']}\" as varchar), "
               f"'[^0-9]', '', 'g') end")
    poste = (f"case when {nat} like '204%' then 'c204' when {nat} like '20%' then 'c20' when {nat} like '21%' "
             f"then 'c21' when {nat} like '23%' then 'c23' else 'autre' end")
    sens = f"lower(strip_accents(cast(\"{c['codrd']}\" as varchar)))" if c["codrd"] else "'depense'"
    op = f"lower(strip_accents(cast(\"{c['opbudg']}\" as varchar)))" if c["opbudg"] else "'reel'"
    somme = lambda k: f"sum({_nombre_sql(c[k])})" if c[k] else "null"  # noqa: E731
    sql = f"""
        select regexp_replace(cast("{c['siret']}" as varchar), '[^0-9]', '', 'g') siret,
               substr(cast("{c['annee']}" as varchar), 1, 4) annee,
               lower(strip_accents(trim(cast("{c['natdec']}" as varchar)))) etape,
               case when {sens} in ('depense', '1', 'd') and {op} in ('reel', '0', 'r', 'reelle') then {poste}
                    else 'hors' end poste,
               count(*) lignes, {somme('propnouv')} propnouv, {somme('prev')} prev, {somme('credouv')} credouv,
               {somme('real')} reel, {somme('rarprec')} rarprec
        from {q} group by all order by all"""
    try:
        lignes = con.execute(sql).fetchall()
    except Exception as exc:
        return {"etat": "illisible", "detail": exc.__class__.__name__}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";", lineterminator="\n")
        w.writerow(["siret", "annee", "etape", "poste", "lignes", "propnouv", "prev", "credouv", "reel", "rarprec"])
        for r in lignes:
            w.writerow(["" if v is None else (round(v, 2) if isinstance(v, float) else v) for v in r])
    fetch.remplacer_si_valide(tmp, dest, nom=dest.name)
    return {"etat": "lu", "lignes": sum(r[4] for r in lignes)}


# --- Collecte ---------------------------------------------------------------------------------------------------------


def collecter(rafraichir: bool = False) -> dict:
    stats = {"jeux": {}, "ressources": Counter()}
    LAKE.mkdir(parents=True, exist_ok=True)
    for cle in SCHEMAS:
        jeux = lister_jeux(cle)
        p = LAKE / f"jeux_{cle}.json"
        tmp = p.with_name(p.name + ".part")
        tmp.write_text(json.dumps({"schema": SCHEMAS[cle], "liste": API + "?schema=" + SCHEMAS[cle],
                                   "releve_le": date.today().isoformat(), "jeux": jeux},
                                  ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        fetch.remplacer_si_valide(tmp, p, nom=p.name)
        stats["jeux"][cle] = len(jeux)
        etat_p = LAKE / f"etat_{cle}.json"
        etat = (lire_json(etat_p) or {}) if not rafraichir else {}
        for j in jeux:
            for r in j["ressources"]:
                ext = extension(r)
                cle_r = f"{j['id']}/{r['id']}"
                if not ext:
                    etat[cle_r] = {"etat": "format_non_lu", "format": r["format"], "modifie": r["modifie"]}
                    stats["ressources"]["format_non_lu"] += 1
                    continue
                if r["octets"] and r["octets"] > MAX_RESSOURCE:
                    etat[cle_r] = {"etat": "trop_volumineuse", "octets": r["octets"], "modifie": r["modifie"]}
                    continue
                connu = etat.get(cle_r) or {}
                if cle == "deliberations":
                    dest = RESTREINT / j["id"] / f"{r['id']}.{ext}"
                    if dest.exists() and connu.get("modifie") == r["modifie"] and connu.get("etat") == "lu":
                        continue
                    deja = None
                    if j["id"] == "60645c94e2bfd21cdc16c0be" and r["octets"] and MEGALIS_DEJA.exists():
                        deja = next((f for f in sorted(MEGALIS_DEJA.glob("*.csv"))
                                     if f.stat().st_size == r["octets"]
                                     and f.name.startswith(Path(r["titre"]).stem)), None)
                    try:
                        if deja:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(deja, dest)
                        else:
                            telecharger(r["url"], dest, r["octets"] if r["url"].startswith(
                                "https://static.data.gouv.fr") else None)
                        etat[cle_r] = {"etat": "lu", "modifie": r["modifie"], "fichier": str(dest.relative_to(ROOT))}
                    except (RuntimeError, SystemExit) as exc:
                        etat[cle_r] = {"etat": "inaccessible", "detail": str(exc)[:200], "modifie": r["modifie"]}
                else:
                    dest = LAKE / "budgets" / j["id"] / f"{r['id']}.extrait.csv"
                    if dest.exists() and connu.get("modifie") == r["modifie"] and connu.get("etat") == "lu":
                        continue
                    brut = LAKE / "_brut" / f"{r['id']}.{ext}"
                    try:
                        telecharger(r["url"], brut, r["octets"] if r["url"].startswith(
                            "https://static.data.gouv.fr") else None)
                        etat[cle_r] = {**extraire_budget(brut, dest, ext), "modifie": r["modifie"]}
                    except (RuntimeError, SystemExit) as exc:
                        etat[cle_r] = {"etat": "inaccessible", "detail": str(exc)[:200], "modifie": r["modifie"]}
                    finally:
                        brut.unlink(missing_ok=True)
                        brut.with_name(brut.name + ".part").unlink(missing_ok=True)
                stats["ressources"][etat[cle_r]["etat"]] += 1
                etat_p.write_text(json.dumps(etat, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
                print(f"  {cle} {cle_r} : {etat[cle_r]['etat']}", file=sys.stderr)
        etat_p.write_text(json.dumps(etat, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    shutil.rmtree(LAKE / "_brut", ignore_errors=True)
    stats["ressources"] = dict(stats["ressources"])
    return stats


# --- Lecture des délibérations --------------------------------------------------------------------------------------


def decoder(octets: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return octets.decode(enc)
        except UnicodeDecodeError:
            continue
    return octets.decode("utf-8", errors="replace")


def lignes_fichier(p: Path) -> tuple[list[str], list[dict]]:
    """CSV (séparateur détecté sur l'en-tête) ou JSON (liste d'objets, ou objet avec une liste)."""
    texte = decoder(p.read_bytes())
    if p.suffix == ".json":
        try:
            d = json.loads(texte)
        except ValueError:
            return [], []
        if isinstance(d, dict):
            d = next((v for v in d.values() if isinstance(v, list)), [])
        d = [x for x in d if isinstance(x, dict)]
        cols = sorted({k for x in d for k in x})
        return cols, d
    entete = texte.split("\n", 1)[0]
    sep = max([";", ",", "\t", "|"], key=entete.count)
    r = csv.DictReader(io.StringIO(texte), delimiter=sep)
    return list(r.fieldnames or []), list(r)


def date_iso(v) -> str | None:
    t = local.propre(v)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", t) or re.match(r"^(\d{4})/(\d{2})/(\d{2})", t)
    if m:
        a, mo, j = m.groups()
    else:
        m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", t)
        if not m:
            return None
        j, mo, a = m.groups()
    try:
        d = date(int(a), int(mo), int(j))
    except ValueError:
        return None
    return d.isoformat() if 1800 <= d.year <= 2100 else None


def matiere(code) -> str:
    """Code de matière ACTES (« 7.5 », « 7-5 ») -> chiffre de niveau 1 ; « 0 » si absent ou illisible."""
    m = re.match(r"^\s*([1-9])(?:\D|$)", local.propre(code))
    return m.group(1) if m else "0"


def code_matiere(code) -> str:
    t = re.sub(r"[^0-9.]", "", local.propre(code).replace("-", ".").replace(",", "."))
    return t[:7] if re.match(r"^[1-9](\.\d+)*$", t) else ""


def objet_foncier(objet: str, mat: str) -> bool:
    return mat in ("2", "3") or bool(FONCIER_RE.search(sans_accents(objet.lower())))


NUMERO_RE = re.compile(r"(?<![\w°/.,_-])(\d{1,4})\s*(?:bis|ter)?\s+([a-z']+)")
UNITES = {"euros", "euro", "eur", "m2", "ans", "an", "mois", "jours", "jour", "ha", "hectares", "hectare", "km", "m",
          "logements", "logement", "lots", "lot", "places", "place", "et", "a", "au", "aux", "heures", "h", "ml",
          "metres", "lineaires", "pieces", "nuits", "personnes", "agents", "postes", "poste", "classes", "salles",
          "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre",
          "decembre", "er", "eme", "e", "tranche", "tranches", "x", "sur", "ou", "pour"}


def numero_de_voie(bas: str) -> bool:
    """« 5 les champs », « 12 bis grande rue » : un numéro suivi d'un mot qui n'est ni une unité ni un mois."""
    for num, mot in NUMERO_RE.findall(bas):
        if not (1900 <= int(num) <= 2099) and mot not in UNITES:
            return True
    return False


def designe_particulier(objet: str) -> bool:
    """Objet foncier : vrai dès qu'un particulier peut être reconnu (adresse, parcelle, nom en capitales...)."""
    bas = sans_accents(objet.lower())
    if ADRESSE_RE.search(bas) or PERSONNE_RE.search(bas) or numero_de_voie(bas):
        return True
    if PARCELLE_RE.search(sans_accents(objet)) or re.search(r"\b(section|parcelle|cadastr)", bas):
        return True
    if not re.search(r"[a-zà-ÿ]", objet):  # tout en capitales : impossible de distinguer un nom, prudence
        return True
    for mot in re.findall(r"\b[A-ZÀ-Ý][A-ZÀ-Ý'-]{2,}\b", objet):
        m = sans_accents(mot)
        if m.replace("'", "").replace("-", "") not in SIGLES and m not in GENERIQUES:
            return True
    for segment in re.split(r"\s[-–—:]\s|[:;.()]\s*|\s-\s*|^\s*-", objet):  # 1er mot d'un segment : début de phrase
        for mot in re.findall(r"[A-Za-zÀ-ÿ]+", segment)[1:]:
            if re.match(r"^[A-ZÀ-Ý][a-zà-ÿ]+$", mot) and mot not in MAJUSCULES_ADMISES:
                return True
    return False


def classer(objet_brut, mat: str) -> tuple[str | None, str | None]:
    """-> (objet publiable, None) ou (None, motif d'exclusion)."""
    o = local.propre(objet_brut)
    if not o or o.lower() in ("none", "null", "non disponible", "-"):
        return None, "objet_vide"
    pub = local.objet_publiable(o, longueur=LONGUEUR_OBJET)
    if pub is None:
        return None, "nom_possible"
    if objet_foncier(o, mat) and designe_particulier(o):
        return None, "foncier_particulier"
    if ADRESSE_NUMERO_RE.search(sans_accents(o.lower())):
        return None, "adresse_possible"
    return pub, None


def lien_publiable(url) -> str | None:
    u = local.propre(url)
    if not re.match(r"^https?://[^\s]+$", u) or len(u) > 400:
        return None
    chemin = unquote(urlparse(u).path)
    mots = " ".join(re.findall(r"[A-Za-zÀ-ÿ]+", chemin))
    if local.CIVILITE_RE.search(chemin.replace("_", " ").replace("-", " ") + " ") or \
            local.contient_nom_de_personne(mots):
        return None
    return u


# --- Références : collectivités ---------------------------------------------------------------------------------------


def references() -> dict:
    """SIREN -> commune ou EPCI (site/data/local/geo, lecture seule) ; populations pour la couverture."""
    communes, epci = {}, {}
    for p in sorted(GEO.glob("*.json")):
        g = lire_json(p)
        for insee, c in g["communes"].items():
            if c.get("siren"):
                communes[c["siren"]] = {"code": insee, "nom": c["nom"], "population": c.get("population")}
        for s, e in g["epci"].items():
            epci[s] = {"code": s, "nom": e["nom"], "population": e.get("population")}
    return {"communes": communes, "epci": epci}


def typer(sirens: set[str], refs: dict) -> dict:
    """SIREN -> (type, catégorie juridique) ; SIRENE local (pipeline/local.py) pour les autres organismes."""
    res = {}
    autres = {s for s in sirens if s not in refs["communes"] and s not in refs["epci"]}
    cj = local.sirene_cj(autres) if autres else {}
    for s in sirens:
        if s in refs["communes"]:
            res[s] = ("commune", "7210")
        elif s in refs["epci"]:
            res[s] = ("epci", "7346")
        else:
            c = (cj.get(s) or ("", None))[0]
            if c in CJ_TYPES:
                res[s] = (CJ_TYPES[c], c)
            elif c.startswith(("71", "72", "73", "74", "41")):
                res[s] = ("autre_public", c)
            else:
                res[s] = (None, c)
    return res


# --- Production -------------------------------------------------------------------------------------------------------


def lire_deliberations(jeux: list[dict], etat: dict) -> tuple[list[dict], list[dict], Counter]:
    """Toutes les lignes lues (une par délibération, dédoublonnées) et le bilan par ressource."""
    vues, lignes, bilan, exclus = set(), [], [], Counter()
    for j in jeux:
        for r in j["ressources"]:
            cle_r = f"{j['id']}/{r['id']}"
            e = etat.get(cle_r) or {}
            b = {"jeu": j["id"], "ressource": r["id"], "etat": e.get("etat", "non_collecte"), "lignes": 0,
                 "siret_organisation": j.get("organisation_siret")}
            p = ROOT / e["fichier"] if e.get("fichier") else None
            if e.get("etat") == "lu" and p and p.exists():
                cols, rows = lignes_fichier(p)
                c = {k: local.colonne(cols, *m) for k, m in {
                    "siret": ("collsiret",), "nom": ("collnom",), "id": ("delibid",), "date": ("delibdate",),
                    "code": ("delibmatierecode",), "objet": ("delibobjet",), "url": ("deliburl",)}.items()}
                if not (c["siret"] and c["date"] and c["objet"]):
                    b["etat"] = "non_conforme"
                    b["detail"] = "colonnes COLL_SIRET, DELIB_DATE ou DELIB_OBJET absentes"
                else:
                    for x in rows:
                        siren = local.siren_de(x.get(c["siret"]))
                        d = date_iso(x.get(c["date"]))
                        ident = local.propre(x.get(c["id"]))[:60] if c["id"] else ""
                        cle = (siren, ident or local.propre(x.get(c["objet"]))[:80], d)
                        if cle in vues:
                            continue
                        vues.add(cle)
                        b["lignes"] += 1
                        lignes.append({"siren": siren, "date": d, "code": code_matiere(x.get(c["code"])) if c["code"]
                                       else "", "objet": x.get(c["objet"]), "url": x.get(c["url"]) if c["url"]
                                       else None, "nom": local.propre(x.get(c["nom"]))[:120] if c["nom"] else "",
                                       "jeu": j["id"], "ressource": r["id"], "siren_source": "colonne"})
            bilan.append(b)
    return lignes, bilan, exclus


def produire(sortie: Path = OUT) -> dict:
    jd = lire_json(LAKE / "jeux_deliberations.json")
    jb = lire_json(LAKE / "jeux_budget.json")
    if not jd:
        raise SystemExit("data/lake/deliberations/jeux_deliberations.json absent : lancer « collecter »")
    etat_d = lire_json(LAKE / "etat_deliberations.json") or {}
    refs = references()
    lignes, bilan, _ = lire_deliberations(jd["jeux"], etat_d)
    types = typer({x["siren"] for x in lignes if x["siren"]}, refs)
    # Ressource dont aucune ligne ne porte un SIREN d'organisme public (COLL_SIRET vide ou inconnu de SIRENE) :
    # rattachée au SIRET que l'organisation qui publie le jeu déclare sur data.gouv.fr (jamais pour un jeu dont
    # une ligne au moins porte un SIREN valide : agrégateurs comme Mégalis).
    orga = {(b["jeu"], b["ressource"]): b.get("siret_organisation") for b in bilan}
    valides = {(x["jeu"], x["ressource"]) for x in lignes if x["siren"] and types.get(x["siren"], (None,))[0]}
    repli = {k: v[:9] for k, v in orga.items() if v and k not in valides}
    for x in lignes:
        k = (x["jeu"], x["ressource"])
        if k in repli:
            x["siren"], x["siren_source"] = repli[k], "organisation"
    types.update(typer(set(repli.values()) - set(types), refs))
    jeux_idx = {j["id"]: i for i, j in enumerate(jd["jeux"])}

    par = defaultdict(lambda: {"comptes": defaultdict(Counter), "exclus": defaultdict(Counter), "sans_date": Counter(),
                               "recentes": defaultdict(list), "jeux": set(), "noms": Counter()})
    exclus_globaux = Counter()
    for x in lignes:
        typ = types.get(x["siren"], (None, ""))[0] if x["siren"] else None
        if not x["siren"] or typ is None:
            exclus_globaux["auteur_non_public"] += 1
            continue
        mat = x["code"][:1] if x["code"] else "0"
        c = par[x["siren"]]
        if not x["date"]:  # date d'adoption non publiée : comptée à part, jamais déduite d'un autre champ
            c["sans_date"][mat] += 1
            c["jeux"].add(x["jeu"])
            exclus_globaux["date_invalide"] += 1
            continue
        a = x["date"][:4]
        c["comptes"][a][mat] += 1
        c["jeux"].add(x["jeu"])
        if x["nom"]:
            c["noms"][x["nom"]] += 1
        o, motif = classer(x["objet"], mat)
        if motif:
            c["exclus"][a][motif] += 1
            exclus_globaux[motif] += 1
            continue
        c["recentes"][mat].append([x["date"], x["code"] or None, o, lien_publiable(x["url"]), jeux_idx[x["jeu"]]])

    mill = f"Jeux publiés sur data.gouv.fr relevés le {jd['releve_le']}"
    source = (f"data.gouv.fr, jeux déclarés au schéma national « Délibérations » ({DOC_SCHEMA['deliberations']}), "
              f"liste {jd['liste']}")
    vider(sortie / "collectivites")
    collectivites, autres = {}, Counter()
    for s in sorted(par):
        c = par[s]
        typ, cj = types[s]
        # Un fichier par collectivité affichable (commune ou intercommunalité en vigueur, département, région) ;
        # les autres organismes publics (CCAS, syndicats, anciennes communes) sont comptés, sans fichier : la limite
        # de fichiers de l'hébergement est commune à tout le site.
        if not ((typ == "commune" and s in refs["communes"]) or (typ == "epci" and s in refs["epci"])
                or typ in ("departement", "region", "collectivite_territoriale")):
            autres["commune_hors_geographie" if typ == "commune" else typ] += 1
            continue
        ref = refs["communes"].get(s) or refs["epci"].get(s) or {}
        nom = ref.get("nom") or (c["noms"].most_common(1)[0][0] if c["noms"] else s)
        recentes = {m: sorted(v, key=lambda r: (r[0], r[1] or "", r[2]), reverse=True)[:PAR_MATIERE]
                    for m, v in sorted(c["recentes"].items())}
        total = sum(sum(v.values()) for v in c["comptes"].values()) + sum(c["sans_date"].values())
        annees = sorted(c["comptes"])
        doc = {"millesime": mill, "source": source, "siren": s, "nom": nom, "type": typ, "code": ref.get("code"),
               "jeux": [{"id": j, "titre": jd["jeux"][jeux_idx[j]]["titre"], "url": PAGE_JEU + j + "/",
                         "licence": jd["jeux"][jeux_idx[j]]["licence"]} for j in sorted(c["jeux"])],
               "matieres": {m: MATIERES[m] for m in sorted({m for v in c["comptes"].values() for m in v}
                                                          | set(c["sans_date"]))},
               "comptes": {a: dict(sorted(v.items())) for a, v in sorted(c["comptes"].items())},
               "sans_date": dict(sorted(c["sans_date"].items())),
               "exclus": {a: dict(sorted(v.items())) for a, v in sorted(c["exclus"].items())},
               "motifs": {k: MOTIFS[k] for k in sorted({k for v in c["exclus"].values() for k in v})},
               "colonnes_recentes": LEGENDE_RECENTES, "par_matiere": PAR_MATIERE, "recentes": recentes,
               "regle": ("Métadonnées seulement : date, matière, objet, lien vers l'acte publié par la collectivité. "
                         "Ni texte, ni vote, ni nom de personne ; délibérations dont l'objet peut désigner une "
                         "personne exclues et comptées (`exclus`).")}
        dump(sortie / "collectivites" / f"{s}.json", doc)
        collectivites[s] = {"nom": nom, "type": typ, "code": ref.get("code"), "total": total,
                            "annees": [annees[0], annees[-1]] if annees else []}

    # Couverture (rapports calculés par le site, même source de population : site/data/local/geo)
    couv = {}
    pop_c = sum((v["population"] or 0) for v in refs["communes"].values())
    pub_c = [s for s, v in collectivites.items() if v["type"] == "commune" and s in refs["communes"]]
    couv["commune"] = {"publient": len(pub_c), "total": len(refs["communes"]),
                       "population_couverte": sum(refs["communes"][s]["population"] or 0 for s in pub_c),
                       "population_totale": pop_c}
    pub_e = [s for s, v in collectivites.items() if v["type"] == "epci" and s in refs["epci"]]
    couv["epci"] = {"publient": len(pub_e), "total": len(refs["epci"]),
                    "population_couverte": sum(refs["epci"][s]["population"] or 0 for s in pub_e),
                    "population_totale": sum((v["population"] or 0) for v in refs["epci"].values())}
    for t in ("departement", "region", "collectivite_territoriale"):
        couv[t] = {"publient": sum(1 for v in collectivites.values() if v["type"] == t),
                   "total": TOTAUX_REFERENCE.get(t)}
    couv["autre_public"] = {"publient": autres["autre_public"], "total": None}
    for t, v in couv.items():
        v["libelle"] = LIB_TYPES[t]
        v["part_nombre"] = round(v["publient"] / v["total"], 6) if v.get("total") else None
        if v.get("population_totale"):
            v["part_population"] = round(v["population_couverte"] / v["population_totale"], 6)

    lus = [b for b in bilan if b["etat"] == "lu"]
    index = {
        "millesime": mill, "source": source, "date_releve": jd["releve_le"],
        "presentation": ("Les délibérations que les collectivités publient elles-mêmes en données ouvertes au format "
                         "national : date, thème (matière), objet et lien vers l'acte. La page ne montre ni le texte "
                         "des actes, ni les votes, ni aucun nom de personne."),
        "absence": ABSENCE,
        "absence_detail": (f"aucun jeu au schéma national « Délibérations » trouvé sur data.gouv.fr le "
                           f"{jd['releve_le']} ; la collectivité peut publier ses actes autrement (site, recueil des "
                           "actes administratifs)."),
        "couverture": couv,
        "methode": ("Couverture calculée par le site : nombre de collectivités dont au moins une délibération est "
                    "lue dans un jeu au schéma national, rapporté au nombre de collectivités (communes et "
                    "intercommunalités de site/data/local/geo, 101 départements, 18 régions) ; part de la population "
                    "= population municipale des communes couvertes / population de toutes les communes (même "
                    "fichier, même année). Rattachement par SIREN (COLL_SIRET) ; pour une ressource dont aucune ligne ne porte de SIREN "
                    "d'organisme public, SIRET déclaré sur data.gouv.fr par l'organisation qui publie le jeu ; type "
                    "par la catégorie juridique "
                    "SIRENE pour les organismes autres que communes et intercommunalités."),
        "statut_couverture": "calculé par le site",
        "regle": ("Objet publié seulement s'il ne peut pas contenir de nom de personne (civilité, prénom suivi d'un "
                  "nom) ni d'adresse (numéro et voie). Urbanisme, domaine et patrimoine, préemption et foncier : délibération exclue dès que "
                  "l'objet peut désigner un particulier (nom, adresse, référence cadastrale, mot en capitales hors "
                  "sigles connus) ; exclusions comptées, jamais montrées. Votes et texte des actes jamais repris."),
        "motifs": MOTIFS, "exclus": dict(sorted(exclus_globaux.items())),
        "matieres": MATIERES, "colonnes_recentes": LEGENDE_RECENTES,
        "jeux": [{"id": j["id"], "titre": j["titre"], "organisation": j["organisation"], "licence": j["licence"],
                  "modifie": j["modifie"], "url": PAGE_JEU + j["id"] + "/",
                  "ressources": len(j["ressources"]),
                  "lues": sum(1 for b in bilan if b["jeu"] == j["id"] and b["etat"] == "lu"),
                  "lignes": sum(b["lignes"] for b in bilan if b["jeu"] == j["id"]),
                  "etats": dict(sorted(Counter(b["etat"] for b in bilan if b["jeu"] == j["id"]).items()))}
                 for j in jd["jeux"]],
        "lignes_lues": sum(b["lignes"] for b in lus),
        "collectivites": dict(sorted(collectivites.items())),
        "sans_fichier": dict(sorted(autres.items())),
        "sans_fichier_note": ("Organismes qui publient des délibérations au format national sans être une commune ou "
                              "une intercommunalité en vigueur, un département ou une région (CCAS, syndicats, "
                              "établissements publics, anciennes communes) : comptés, sans page."),
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(sortie / "index.json", index)
    stats = {"collectivites": len(collectivites), "lignes": index["lignes_lues"], "exclus": dict(exclus_globaux),
             "couverture": {t: (v["publient"], v.get("total")) for t, v in couv.items()}}
    if jb:
        stats["budgets"] = produire_budgets(jb, refs, sortie)
    return stats


ETAPES = {"budget primitif": "budget_primitif", "budget supplementaire": "budget_supplementaire",
          "decision modificative": "decision_modificative", "compte administratif": "compte_administratif",
          "compte financier unique": "compte_financier_unique", "bp": "budget_primitif", "bs": "budget_supplementaire",
          "dm": "decision_modificative", "ca": "compte_administratif", "cfu": "compte_financier_unique"}
LIB_ETAPES = {"budget_primitif": "budget primitif", "budget_supplementaire": "budget supplémentaire",
              "decision_modificative": "décision modificative", "compte_administratif": "compte administratif",
              "compte_financier_unique": "compte financier unique", "autre": "autre étape"}


def etape(t: str) -> str:
    t = sans_accents((t or "").lower()).strip()
    for k, v in ETAPES.items():
        if t == k or t.startswith(k):
            return v
    return "autre"


def extraits_budget(jb: dict) -> list[tuple[str, dict]]:
    etat = lire_json(LAKE / "etat_budget.json") or {}
    res = []
    for j in jb["jeux"]:
        for r in j["ressources"]:
            p = LAKE / "budgets" / j["id"] / f"{r['id']}.extrait.csv"
            if (etat.get(f"{j['id']}/{r['id']}") or {}).get("etat") == "lu" and p.exists():
                with p.open(encoding="utf-8") as fh:
                    for x in csv.DictReader(fh, delimiter=";"):
                        res.append((j["id"], x))
    return res


def votes_equipement() -> dict:
    """SIRET -> {annee: {etape: {poste: {propnouv, prev, credouv, reel, rarprec}}}} (dépenses réelles 20/204/21/23),
    pour pipeline/investissement_communes.py. Jeux au schéma « Budget » collectés ; vide si rien n'est collecté."""
    jb = lire_json(LAKE / "jeux_budget.json")
    if not jb:
        return {}
    res: dict = {}
    for jeu, x in extraits_budget(jb):
        if x["poste"] not in ("c20", "c204", "c21", "c23") or not re.match(r"^\d{14}$", x["siret"] or "") \
                or not re.match(r"^20\d\d$", x["annee"] or ""):
            continue
        e = res.setdefault(x["siret"], {}).setdefault(x["annee"], {}).setdefault(etape(x["etape"]), {})
        p = e.setdefault(x["poste"], {"propnouv": None, "prev": None, "credouv": None, "reel": None,
                                      "rarprec": None, "jeux": []})
        for k in ("propnouv", "prev", "credouv", "reel", "rarprec"):
            v = local.num(x[k])
            if v is not None:
                p[k] = (p[k] or 0.0) + v
        if jeu not in p["jeux"]:
            p["jeux"].append(jeu)
    return res


def produire_budgets(jb: dict, refs: dict, sortie: Path) -> dict:
    docs = defaultdict(set)
    for jeu, x in extraits_budget(jb):
        s = (x["siret"] or "")[:9]
        if re.match(r"^\d{9}$", s) and re.match(r"^20\d\d$", x["annee"] or ""):
            docs[s].add((x["annee"], etape(x["etape"]), jeu))
    types = typer(set(docs), refs)
    ids = sorted({j for v in docs.values() for (_, _, j) in v})
    rang = {j: i for i, j in enumerate(ids)}
    coll = {}
    for s in sorted(docs):
        typ = types[s][0]
        if typ is None:
            continue
        ref = refs["communes"].get(s) or refs["epci"].get(s) or {}
        coll[s] = {"nom": ref.get("nom"), "type": typ, "code": ref.get("code"),
                   "documents": [[a, e, rang[j]] for a, e, j in sorted(docs[s])]}
    orga = {j["id"]: j["organisation"] for j in jb["jeux"]}
    for s, c in coll.items():
        if not c["nom"]:
            c["nom"] = orga.get(ids[c["documents"][0][2]]) or s
    doc = {"millesime": f"Jeux publiés sur data.gouv.fr relevés le {jb['releve_le']}",
           "source": f"data.gouv.fr, jeux déclarés au schéma national « Budget » ({DOC_SCHEMA['budget']}), liste "
                     f"{jb['liste']}",
           "presentation": ("Documents budgétaires (budget primitif, décisions modificatives, compte administratif) "
                            "publiés par les collectivités au format national, par exercice."),
           "colonnes_documents": ["annee", "etape", "jeu"], "etapes": LIB_ETAPES,
           "jeux": [{"id": j["id"], "titre": j["titre"], "organisation": j["organisation"], "licence": j["licence"],
                     "url": PAGE_JEU + j["id"] + "/"} for j in jb["jeux"] if j["id"] in rang],
           "couverture": {t: sum(1 for c in coll.values() if c["type"] == t) for t in LIB_TYPES},
           "collectivites": coll}
    dump(sortie / "budgets.json", doc)
    return {"collectivites": len(coll)}


def vider(d: Path) -> None:
    if d.exists():
        for f in d.glob("*.json"):
            f.unlink()


RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "trouvailles": [
        {"nom": "API data.gouv.fr, filtre schema=scdl/deliberations et scdl/budget", "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0 (données)", "note": "liste des jeux déclarés conformes, utilisée ici"},
        {"nom": "schema.data.gouv.fr, schémas SCDL Délibérations 2.1 et Budget 0.8", "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "note": "noms de colonnes et nomenclature ACTES"},
        {"nom": "etalab/schema-scdl-deliberations (GitHub)", "verdict": "inspiration seulement",
         "licence": "MIT", "note": "dépôt du schéma ; aucun collecteur fourni"},
        {"nom": "Validata (validation des jeux au schéma)", "verdict": "inspiration seulement",
         "licence": "AGPL-3.0", "note": "validation complète non nécessaire : contrôle des colonnes utiles"},
        {"nom": "pipeline/local.py (objet_publiable, deliberations_subventions, sirene_cj)",
         "verdict": "réutilisable tel quel", "licence": "dépôt", "note": "filtre des objets et typage par SIRENE"},
    ],
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("etape", nargs="?", choices=["collecter", "produire"], default=None)
    ap.add_argument("--rafraichir", action="store_true")
    ap.add_argument("--sortie", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if a.etape in (None, "collecter"):
        print(json.dumps(collecter(a.rafraichir), ensure_ascii=False, indent=1))
    if a.etape in (None, "produire"):
        print(json.dumps(produire(a.sortie), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
