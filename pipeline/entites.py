"""Relier les bénéficiaires : une même organisation (personne morale) retrouvée dans toutes les sources du site.

Ce module ne télécharge rien : il relit les fichiers déjà publiés dans site/data par les autres axes (subventions,
associations, bénéficiaires, marchés, aides aux entreprises, fonds européens, contrôle, État actionnaire, opérateurs,
établissements de santé, éducation et recherche) et range chaque apparition d'une organisation sous son SIREN.

Méthode (recherche publique du 18/11/2026, docs/contrat_interface.md) :
  1. jointure exacte par SIREN (un SIRET est ramené à ses 9 premiers chiffres) : décision « même » ;
  2. lignes publiées sans SIREN mais avec un nom et un département (rapports des chambres régionales des comptes,
     établissements d'enseignement supérieur) : nom normalisé et département passés à Splink (MIT, moteur DuckDB),
     modèle de Fellegi et Sunter à paramètres fixés et publiés (aucun apprentissage, résultat reproductible) ;
     décision « probable » (score au moins SEUIL_PROBABLE et candidat unique), « incertain » ou « différent », à la
     manière des jugements de nomenklatura (OpenSanctions) ; un rapprochement probable n'est JAMAIS fusionné ni
     additionné : il est affiché à part, avec son score ;
  3. modèle de données inspiré de FollowTheMoney (LegalEntity, Payment, Contract ; jamais Person) : une fiche par
     organisation, ses apparitions par canal (source), année et montant tel que publié, avec la notion du montant.

Règle 13 (chiffre calculé par le site) : une somme n'est publiée que pour des lignes de la même année, de la même
notion de montant et du même périmètre (même canal, même groupe), avec la mention « calculé par le site » ; deux
canaux ne sont additionnés que si leur notion est déclarée cumulable entre canaux (aucune aujourd'hui) ; une période
pluriannuelle n'est jamais additionnée à une année.

Confidentialité : seules les personnes morales sont reprises (sirene.personne_morale sur la catégorie juridique du
stock SIRENE, à défaut celle de la source) ; un nom qui ressemble à celui d'une personne (local.contient_nom_de_personne)
ou une unité à diffusion partielle n'est jamais repris. Les colonnes de nom et de prénom du stock SIRENE ne sont pas
lues.

Entrées : site/data/<axes ci-dessus> (lecture seule) ; stock SIRENE des unités légales partagé avec local.py
          (data/lake/_cache/local/sirene_unite_legale.parquet, facultatif : catégorie juridique et dénomination) ;
          prénoms fréquents de local.py.
Sorties : site/data/entites/index.json            méthode, canaux, notions, comptes, découpage, recherche publique
          site/data/entites/fiches/<préfixe>.json  fiches des organisations dont le SIREN commence par le préfixe
          site/data/entites/recherche/<clé>.json   index de recherche par début de mot du nom
          site/data/entites/recherche_globale.json organisations présentes dans plusieurs canaux (recherche du site)

Commandes :
  python pipeline/entites.py produire [--sortie DOSSIER]   # sans réseau, sorties reproductibles octet pour octet
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
from urllib.parse import quote
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
SORTIE = SITE / "entites"
STOCK = ROOT / "data" / "lake" / "_cache" / "local" / "sirene_unite_legale.parquet"

TAILLE_MAX = 1_000_000          # octets par fichier chargé par le navigateur
TAILLE_VISEE = 900_000          # au-delà, un découpage plus fin est utilisé
LIGNES_MAX_PAR_BLOC = 120       # lignes affichées par canal et par fiche (les suivantes sont comptées à part)
SEUIL_PROBABLE = 0.9            # probabilité de Splink à partir de laquelle un rapprochement est « probable »
SEUIL_INCERTAIN = 0.5           # en dessous : « différent »
RECHERCHE_GLOBALE_MAX = 400     # organisations ajoutées à la recherche du site (plusieurs canaux)
MIN_CANAUX = 2                  # une fiche relie au moins deux canaux

COLONNES_VALEUR = ["annee_ou_periode", "montant_eur"]

# --- Notions de montant -------------------------------------------------------------------------------------------
# sens : « recoit » (argent public reçu par l'organisation), « verse » (montant versé ou dépensé par elle),
# « mention » (apparition sans flux reçu). somme_canal : lignes d'un même canal additionnables pour une même année
# (même notion, même groupe). cumulable : groupe de notions additionnables entre canaux pour une même année (None :
# jamais ; aucune notion ne l'est aujourd'hui, les canaux se recouvrent ou n'ont pas la même définition du montant).
NOTIONS = {
    "credits_etat_verses": {
        "libelle": "crédits de l'État versés, listés dans le jaune budgétaire « effort financier de l'État en faveur "
                   "des associations » (année de versement ; liste publiée deux ans plus tard)", "sens": "recoit",
        "somme_canal": True, "cumulable": None},
    "reserve_attribuee": {
        "libelle": "subvention attribuée au titre de la réserve parlementaire", "sens": "recoit",
        "somme_canal": True, "cumulable": None},
    "subvention_attribuee": {
        "libelle": "subventions engagées ou attribuées par convention, cumulées sur la période de la source",
        "sens": "recoit", "somme_canal": False, "cumulable": None},
    "aide_engagee_france2030": {
        "libelle": "aide France 2030 engagée à la décision (subvention et avance remboursable), cumulée",
        "sens": "recoit", "somme_canal": False, "cumulable": None},
    "marche_notifie_ht": {
        "libelle": "montant notifié des marchés dont elle est titulaire (euros hors taxes ; maximum estimé pour un "
                   "accord-cadre ; pas un montant payé)", "sens": "recoit", "somme_canal": True, "cumulable": None},
    "marche_notifie_ht_acheteur": {
        "libelle": "montant notifié des marchés qu'elle a passés comme acheteur (euros hors taxes)", "sens": "verse",
        "somme_canal": False, "cumulable": None},
    "element_aide": {
        "libelle": "élément d'aide d'État publié au registre européen de transparence (équivalent-subvention, "
                   "année d'octroi)", "sens": "recoit", "somme_canal": False, "cumulable": None},
    "laureat_sans_montant": {
        "libelle": "lauréat publié, montant par lauréat non publié par la source", "sens": "recoit",
        "somme_canal": False, "cumulable": None},
    "contribution_ue_programmee": {
        "libelle": "contribution de l'Union européenne programmée pour l'opération (année de début)", "sens": "recoit",
        "somme_canal": True, "cumulable": None},
    "rapport_chambre": {
        "libelle": "rapport d'observations définitives d'une chambre régionale ou territoriale des comptes",
        "sens": "mention", "somme_canal": False, "cumulable": None},
    "exercice_declare_hatvp": {
        "libelle": "exercice déclaré au répertoire des représentants d'intérêts de la HATVP (dépenses de "
                   "l'organisation, pas de l'argent public)", "sens": "mention", "somme_canal": False,
        "cumulable": None},
    "dividendes_verses_etat": {
        "libelle": "dividendes et recettes assimilées versés au budget de l'État (exécution)", "sens": "verse",
        "somme_canal": False, "cumulable": None},
    "operation_capital_citee": {
        "libelle": "opération en capital de l'État citée par le rapport du Sénat (montant cité, plusieurs citations "
                   "peuvent viser la même opération)", "sens": "recoit", "somme_canal": False, "cumulable": None},
    "financement_etat_execution": {
        "libelle": "financement de l'État à l'opérateur, crédits de paiement exécutés (subvention pour charges de "
                   "service public, transferts, dotations)", "sens": "recoit", "somme_canal": False,
        "cumulable": None},
    "taxes_affectees_execution": {
        "libelle": "taxes affectées à l'opérateur, exécution", "sens": "recoit", "somme_canal": False,
        "cumulable": None},
    "membre_categorie_operateurs": {
        "libelle": "établissement membre d'une catégorie d'opérateurs de l'État (montants publiés pour la catégorie "
                   "entière)", "sens": "mention", "somme_canal": False, "cumulable": None},
    "recettes_t2a_declarees": {
        "libelle": "recettes de l'activité (tarification à l'activité) déclarées par l'établissement de santé",
        "sens": "recoit", "somme_canal": True, "cumulable": None},
    "recettes_migac_declarees": {
        "libelle": "dotations d'intérêt général et d'aide à la contractualisation déclarées par l'établissement",
        "sens": "recoit", "somme_canal": True, "cumulable": None},
    "etablissements_finess": {
        "libelle": "établissements de santé ou médico-sociaux gérés, listés au répertoire FINESS", "sens": "mention",
        "somme_canal": False, "cumulable": None},
    "aide_projets_coordonnes": {
        "libelle": "aide des projets de l'Agence nationale de la recherche qu'elle coordonne (pas la somme qu'elle "
                   "reçoit)", "sens": "mention", "somme_canal": False, "cumulable": None},
    "aide_anr_allouee": {
        "libelle": "aide de l'Agence nationale de la recherche allouée au partenaire, cumulée", "sens": "recoit",
        "somme_canal": False, "cumulable": None},
    "lycees_subventions_votees": {
        "libelle": "subventions votées par la Région Île-de-France (affectations nettes, année de la décision)",
        "sens": "recoit", "somme_canal": False, "cumulable": None},
    "lycees_dotations_versees": {
        "libelle": "dotations de fonctionnement versées par la Région Centre-Val de Loire (année de versement)",
        "sens": "recoit", "somme_canal": False, "cumulable": None},
    "lycees_aides_actions": {
        "libelle": "aides aux actions éducatives de la Région des Pays de la Loire (année de début de campagne)",
        "sens": "recoit", "somme_canal": False, "cumulable": None},
    "effectifs_etudiants": {
        "libelle": "inscriptions principales d'étudiants publiées pour l'établissement", "sens": "mention",
        "somme_canal": False, "cumulable": None},
}

# --- Canaux (une source du site) ------------------------------------------------------------------------------------
# page : route du site qui présente la source (le site vérifie qu'elle existe, sinon il renvoie au fichier).
CANAUX = {
    "associations_jaunes": {"titre": "Crédits de l'État aux associations (jaunes budgétaires, PLF 2012 à 2025)",
                            "fichiers": "associations/programmes/*.json", "page": "/beneficiaires/programme",
                            "axe": "associations"},
    "reserve_parlementaire": {"titre": "Réserve parlementaire (Assemblée nationale 2013-2016, Sénat 2014-2017)",
                              "fichiers": "associations/reserve/*.json", "page": None, "axe": "associations"},
    "subventions": {"titre": "Subventions par convention (données essentielles des conventions)",
                    "fichiers": "subventions/attribuants/*.json", "page": None, "axe": "subventions"},
    "france2030": {"titre": "France 2030, bénéficiaires nommés", "fichiers": "beneficiaires/france2030.json",
                   "page": "/beneficiaires", "axe": "beneficiaires"},
    "marches_etat": {"titre": "Marchés publics des services de l'État", "fichiers": "beneficiaires/marches_etat.json",
                     "page": "/beneficiaires", "axe": "beneficiaires"},
    "marches_titulaire": {"titre": "Marchés publics de tous les acheteurs, comme titulaire (10 premiers titulaires "
                                   "de chaque acheteur)", "fichiers": "marches/departements/*.json", "page": None,
                          "axe": "marches"},
    "marches_acheteur": {"titre": "Marchés publics de tous les acheteurs, comme acheteur",
                         "fichiers": "marches/departements/*.json", "page": None, "axe": "marches"},
    "aides_registre_europeen": {"titre": "Registre européen de transparence des aides d'État (50 premiers "
                                         "bénéficiaires)", "fichiers": "aides_entreprises/tam.json", "page": None,
                                "axe": "aides_entreprises"},
    "france_relance": {"titre": "France Relance, lauréats industriels", "fichiers": "aides_entreprises/france_relance.json",
                       "page": None, "axe": "aides_entreprises"},
    "fonds_europeens": {"titre": "Fonds européens, listes d'opérations des autorités de gestion",
                        "fichiers": "fonds_europeens/operations/*.json", "page": "/explorer/fonds-europeens",
                        "axe": "fonds_europeens"},
    "chambres_regionales": {"titre": "Rapports des chambres régionales et territoriales des comptes, 2020 à 2026",
                            "fichiers": "controle/rod_crtc/*.json", "page": "/decisions/controle", "axe": "controle"},
    "representants_interets": {"titre": "Répertoire des représentants d'intérêts (HATVP)",
                               "fichiers": "controle/lobbying/organisations.json", "page": "/decisions/controle",
                               "axe": "controle"},
    "etat_actionnaire": {"titre": "État actionnaire : dividendes et opérations en capital",
                         "fichiers": "etat_actionnaire/entites.json", "page": "/explorer/etat-actionnaire",
                         "axe": "etat_actionnaire"},
    "operateurs": {"titre": "Opérateurs de l'État (jaunes PLF 2024 à 2026)", "fichiers": "operateurs/operateurs.json",
                   "page": "/explorer/operateurs", "axe": "operateurs"},
    "hospi_diag": {"titre": "Comptes des établissements de santé 2011 à 2015 (Hospi Diag)",
                   "fichiers": "sante_etablissements/hospi_diag.json", "page": "/explorer/hopitaux",
                   "axe": "sante_etablissements"},
    "finess": {"titre": "Établissements de santé et médico-sociaux (FINESS)",
               "fichiers": "sante_etablissements/departements/*.json", "page": "/explorer/hopitaux",
               "axe": "sante_etablissements"},
    "anr": {"titre": "Agence nationale de la recherche (investissements d'avenir et France 2030 ; projets 2005-2009)",
            "fichiers": "education_recherche/anr_etablissements.json", "page": "/explorer/education-recherche",
            "axe": "education_recherche"},
    "lycees": {"titre": "Subventions et dotations de trois régions aux lycées",
               "fichiers": "education_recherche/lycees/*.json", "page": "/explorer/education-recherche",
               "axe": "education_recherche"},
    "etudiants": {"titre": "Effectifs étudiants par établissement d'enseignement supérieur",
                  "fichiers": "education_recherche/etudiants.json", "page": "/explorer/education-recherche",
                  "axe": "education_recherche"},
}

# Fichier volontairement non relu : il reprend une source déjà relue (jamais deux fois la même ligne).
NON_RELUS = [
    {"chemins_source": "beneficiaires/programme_*.json", "raison": "associations du jaune PLF 2025 (crédits 2023) : même "
     "source que associations/programmes, relue par le canal associations_jaunes"},
    {"chemins_source": "subventions/beneficiaires.json", "raison": "somme des sources de subventions faite par l'axe "
     "subventions : les sources sont relues une à une"},
    {"chemins_source": "ue/", "raison": "hors du périmètre demandé pour cette version (bénéficiaires Kohesio, FTS, Horizon "
     "Europe) ; à relier dans une version suivante"},
]

ROUTES_CONNUES = {"/beneficiaires", "/beneficiaires/programme", "/explorer/fonds-europeens", "/decisions/controle",
                  "/explorer/etat-actionnaire", "/explorer/operateurs", "/explorer/hopitaux",
                  "/explorer/education-recherche"}

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "trouvailles": [
        {"nom": "Splink (Ministry of Justice, Royaume-Uni)", "url": "https://github.com/moj-analytical-services/splink",
         "licence": "MIT", "version": "5.0.0", "derniere_publication": "2026-09-28", "verdict": "réutilisable tel quel",
         "usage": "moteur de rapprochement probabiliste (Fellegi et Sunter) sur DuckDB, paramètres fixés par le projet"},
        {"nom": "FollowTheMoney (OpenSanctions)", "url": "https://github.com/opensanctions/followthemoney",
         "licence": "MIT", "version": "4.11.3", "derniere_publication": "2026-11-07", "verdict": "inspiration seulement",
         "usage": "modèle de données : organisation (LegalEntity), paiement (Payment), marché (Contract) ; aucune "
                  "personne (Person)"},
        {"nom": "nomenklatura (OpenSanctions)", "url": "https://github.com/opensanctions/nomenklatura",
         "licence": "MIT", "version": "4.18.0", "derniere_publication": "2026-11-16", "verdict": "inspiration seulement",
         "usage": "décisions de rapprochement « même », « différent », « incertain », jamais de fusion implicite"},
        {"nom": "API Recherche d'entreprises et stock SIRENE (Insee, data.gouv.fr)",
         "url": "https://www.data.gouv.fr/fr/datasets/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/",
         "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel",
         "usage": "catégorie juridique et dénomination, déjà partagés par local.py (aucun appel réseau ici)"},
    ],
}


# --- Utilitaires ---------------------------------------------------------------------------------------------------

def lire(rel: str):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


def fichiers(motif: str) -> list[str]:
    return sorted(str(p.relative_to(SITE)) for p in SITE.glob(motif) if p.is_file())


def siren_de(x) -> str | None:
    """SIREN à 9 chiffres, ou SIRET ramené à son SIREN ; None sinon."""
    if x is None:
        return None
    s = re.sub(r"\s", "", str(x))
    if re.fullmatch(r"\d{14}", s):
        s = s[:9]
    return s if re.fullmatch(r"\d{9}", s) else None


def annees_du_texte(t: str) -> list[int]:
    return sorted({int(a) for a in re.findall(r"\b(20[0-3]\d|199\d)\b", t or "")})


def periode_de(annees) -> str | None:
    a = sorted({int(x) for x in annees if x is not None})
    if not a:
        return None
    return str(a[0]) if a[0] == a[-1] else f"{a[0]}-{a[-1]}"


MOTS_VIDES = {"DE", "DU", "DES", "LA", "LE", "LES", "L", "D", "ET", "A", "AU", "AUX", "EN", "POUR", "SUR", "SUR",
              "THE", "OF"}
ABREVIATIONS = {"ST": "SAINT", "STE": "SAINTE", "CNE": "COMMUNE", "CC": "COMMUNAUTE COMMUNES",
                "CA": "COMMUNAUTE AGGLOMERATION", "CH": "CENTRE HOSPITALIER", "CHU": "CENTRE HOSPITALIER UNIVERSITAIRE",
                "CHR": "CENTRE HOSPITALIER REGIONAL", "CCAS": "CENTRE COMMUNAL ACTION SOCIALE",
                "SDIS": "SERVICE DEPARTEMENTAL INCENDIE SECOURS", "OPH": "OFFICE PUBLIC HABITAT",
                "GIP": "GROUPEMENT INTERET PUBLIC", "SEM": "SOCIETE ECONOMIE MIXTE", "SPL": "SOCIETE PUBLIQUE LOCALE",
                "CONSEIL DEPARTEMENTAL": "DEPARTEMENT", "CONSEIL REGIONAL": "REGION"}


def normaliser(nom: str) -> str:
    """Majuscules sans accents ni ponctuation, parenthèses finales (sigle) retirées, abréviations développées,
    mots vides retirés."""
    t = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode().upper()
    t = re.sub(r"\([^)]*\)\s*$", " ", t)
    t = re.sub(r"[^A-Z0-9]+", " ", t)
    t = f" {t} "
    for court, long in ABREVIATIONS.items():
        t = t.replace(f" {court} ", f" {long} ")
    return " ".join(m for m in t.split() if m not in MOTS_VIDES)


def mots_recherche(nom: str) -> list[str]:
    """Mots du nom pour la recherche du site : minuscules sans accents (même règle que web/src/composants)."""
    t = (nom or "").lower().replace("œ", "oe").replace("æ", "ae").replace("ß", "ss")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return [m for m in re.split(r"[^a-z0-9]+", t) if m]


def r2(x):
    return None if x is None else round(float(x), 2)


# --- Lecture des canaux --------------------------------------------------------------------------------------------
# Une apparition : dict(siren, nom, cj, canal, notion, annee, periode, montant, precision, statut, lien, groupe,
#                       fichier, departement)

def A(siren, nom, cj, canal, notion, fichier, annee=None, periode=None, montant=None, precision="", statut="trace",
      lien=None, groupe=None, departement=None):
    return {"siren": siren, "nom": (nom or "").strip(), "cj": str(cj) if cj not in (None, "") else None,
            "canal": canal, "notion": notion, "annee": annee, "periode": periode,
            "montant": r2(montant) if isinstance(montant, (int, float)) and not isinstance(montant, bool) else None,
            "precision": precision, "statut": statut, "lien": lien, "groupe": groupe or canal, "fichier": fichier,
            "departement": departement}


def lire_associations(stats):
    for rel in fichiers(CANAUX["associations_jaunes"]["fichiers"]):
        d = lire(rel)
        col = d["colonnes"]
        i_s, i_n, i_c, i_m = (col.index(c) for c in ("siren", "denomination", "categorie_juridique", "montants_eur"))
        p = d.get("programme")
        for ligne in d.get("lignes", []):
            s = siren_de(ligne[i_s])
            for k, v in enumerate(ligne[i_m]):
                if v == "nc":
                    stats["valeurs_nc"] += 1
                    continue
                if not isinstance(v, (int, float)):
                    continue
                prog = f"programme {p}" if p and p != "sans_programme" else "sans programme publié"
                yield A(s, ligne[i_n], ligne[i_c], "associations_jaunes", "credits_etat_verses", rel,
                        annee=d["annees_credits"][k], montant=v,
                        precision=prog,
                        lien=f"/beneficiaires/programme?p={p}" if p and re.fullmatch(r"\d{3}", str(p)) else None)


def lire_reserve(stats):
    for rel in fichiers(CANAUX["reserve_parlementaire"]["fichiers"]):
        d = lire(rel)
        col = d["colonnes_beneficiaires"]
        idx = {c: col.index(c) for c in ("siren", "denomination", "categorie_juridique", "programme", "montant_eur")}
        for parl in d.get("parlementaires", []):
            for b in parl.get("beneficiaires_nommes", []):
                yield A(siren_de(b[idx["siren"]]), b[idx["denomination"]], b[idx["categorie_juridique"]],
                        "reserve_parlementaire", "reserve_attribuee", rel, annee=d["annee"],
                        montant=b[idx["montant_eur"]],
                        precision=f"{d['assemblee']}, programme {b[idx['programme']]}" if b[idx["programme"]]
                        else d["assemblee"])


def lire_subventions(stats):
    for rel in fichiers(CANAUX["subventions"]["fichiers"]):
        d = lire(rel)
        b = d.get("beneficiaires")
        if not isinstance(b, dict):
            continue
        per = periode_de(x.get("annee") for x in d.get("par_annee", []) if isinstance(x.get("annee"), int))
        note = f", déjà comptée dans {d['inclus_dans']}" if d.get("inclus_dans") else ""
        for t in b.get("top", []):
            yield A(siren_de(t.get("siren")), t.get("denomination"), t.get("categorie_juridique"), "subventions",
                    "subvention_attribuee", rel, periode=per, montant=t.get("montant_eur"),
                    precision=f"{d.get('attribuant') or d.get('id')}{note} ; {t.get('conventions', 0)} conventions",
                    groupe=d.get("id"))


def lire_france2030(stats):
    rel = CANAUX["france2030"]["fichiers"]
    d = lire(rel)
    per = periode_de(annees_du_texte(d.get("millesime", "")))
    for t in d["ensemble"].get("top", []):
        ops = ", ".join(t.get("operateurs") or [])
        yield A(siren_de(t.get("siren")), t.get("denomination"), t.get("categorie_juridique"), "france2030",
                "aide_engagee_france2030", rel, periode=per, montant=t.get("montant_eur"),
                precision=f"{t.get('projets', 0)} projets ; opérateur : {ops}" if ops else f"{t.get('projets', 0)} projets")


def lire_marches_etat(stats):
    rel = CANAUX["marches_etat"]["fichiers"]
    d = lire(rel)
    an = annees_du_texte(d.get("millesime", ""))
    for t in d["ensemble"].get("top", []):
        yield A(siren_de(t.get("siren")), t.get("denomination"), t.get("categorie_juridique"), "marches_etat",
                "marche_notifie_ht", rel, annee=an[-1] if len(an) == 1 else None,
                periode=None if len(an) == 1 else periode_de(an), montant=t.get("montant_eur"),
                precision=f"{t.get('nombre_marches', 0)} marchés notifiés par les services de l'État")


def lire_marches(stats):
    for rel in fichiers(CANAUX["marches_titulaire"]["fichiers"]):
        d = lire(rel)
        dep = d.get("departement")
        annees = d.get("annees", [])
        per = periode_de(annees)
        for a in d.get("acheteurs", []):
            for k, v in enumerate(a.get("montants_eur") or []):
                if isinstance(v, (int, float)):
                    yield A(siren_de(a.get("siren")), a.get("denomination"), a.get("categorie_juridique"),
                            "marches_acheteur", "marche_notifie_ht_acheteur", rel, annee=annees[k], montant=v,
                            precision=f"acheteur ({a.get('categorie') or 'catégorie non publiée'}), département {dep}",
                            departement=dep)
            for t in a.get("titulaires", []):
                yield A(siren_de(t.get("siren")), t.get("denomination"), t.get("categorie_juridique"),
                        "marches_titulaire", "marche_notifie_ht", rel, periode=per, montant=t.get("montant_eur"),
                        precision=f"{t.get('marches', 0)} marchés avec {a.get('denomination')} (département {dep})")


def lire_tam(stats):
    rel = CANAUX["aides_registre_europeen"]["fichiers"]
    d = lire(rel)
    for t in d.get("beneficiaires", {}).get("top", []):
        for an, v in sorted((t.get("par_annee_eur") or {}).items()):
            yield A(siren_de(t.get("siren")), t.get("denomination"), t.get("categorie_juridique"),
                    "aides_registre_europeen", "element_aide", rel, annee=int(an), montant=v,
                    precision="élément d'aide, année d'octroi")


def lire_france_relance(stats):
    rel = CANAUX["france_relance"]["fichiers"]
    d = lire(rel)
    lau = d.get("laureats", {})
    col = lau.get("colonnes", [])
    if not col:
        return
    i = {c: col.index(c) for c in col}
    per = periode_de(annees_du_texte(d.get("millesime", ""))[:2])
    for l in lau.get("lignes", []):
        dep = l[i["departement"]] if "departement" in i else None
        prec = " ; ".join(str(l[i[c]]) for c in ("mesure", "filiere") if c in i and l[i[c]])
        yield A(siren_de(l[i["siren"]]), l[i["denomination"]], l[i["categorie_juridique"]], "france_relance",
                "laureat_sans_montant", rel, periode=per, precision=prec, departement=dep)


def lire_fonds_europeens(stats):
    for rel in fichiers(CANAUX["fonds_europeens"]["fichiers"]):
        d = lire(rel)
        col = d.get("colonnes", [])
        if "siren" not in col:
            continue
        i = {c: col.index(c) for c in col}
        liste = Path(rel).stem
        statut = "approche" if d.get("montant_ue_mode") == "calculé" else "trace"
        for o in d.get("operations", []):
            s = siren_de(o[i["siren"]])
            if not s:
                continue
            yield A(s, o[i["denomination"]], o[i["categorie_juridique"]], "fonds_europeens",
                    "contribution_ue_programmee", rel, annee=o[i["annee_debut"]], montant=o[i["montant_ue_eur"]],
                    precision=f"{o[i['fonds']]} {o[i['periode']]}"
                              + (f", opération {o[i['id']]}" if o[i["id"]] else ", opération sans identifiant publié")
                              + f" ({d.get('autorite_de_gestion') or liste})",
                    statut=statut, lien=f"/explorer/fonds-europeens?liste={liste}",
                    groupe=f"{d.get('autorite_de_gestion') or liste}, {o[i['fonds']]} {o[i['periode']]}",
                    departement=o[i["departement"]] if "departement" in i else None)


def lire_chambres(stats, sans_siren):
    for rel in fichiers("controle/rod_crtc/20*.json"):
        d = lire(rel)
        for r in d.get("rapports", []):
            dep = (r.get("codes") or {}).get("departement")
            prec = f"{r.get('type_document') or r.get('type') or 'rapport'}, {r.get('chambre') or r.get('juridiction')}, {r.get('date')}"
            s = siren_de(r.get("siren"))
            if s:
                yield A(s, r.get("organisme"), r.get("categorie_juridique"), "chambres_regionales", "rapport_chambre",
                        rel, annee=r.get("annee"), precision=prec, lien=r.get("url"), departement=dep)
            elif r.get("personne_morale") and r.get("organisme"):
                sans_siren.append({"canal": "chambres_regionales", "notion": "rapport_chambre", "fichier": rel,
                                   "nom": r["organisme"], "departement": dep, "annee": r.get("annee"),
                                   "precision": prec, "lien": r.get("url"), "cle": r.get("id")})
            else:
                stats["chambres_sans_organisme"] += 1


def lire_representants(stats):
    rel = CANAUX["representants_interets"]["fichiers"]
    d = lire(rel)
    col = d["colonnes"]
    i = {c: col.index(c) for c in col}
    for o in d.get("organisations", []):
        if o[i["type_identifiant"]] != "SIREN":
            stats["representants_sans_siren"] += 1
            continue
        for dep in o[i["depenses_declarees"]] or []:
            yield A(siren_de(o[i["identifiant"]]), o[i["denomination"]], None, "representants_interets",
                    "exercice_declare_hatvp", rel, annee=dep[0], precision="exercice déclaré")


def lire_etat_actionnaire(stats):
    rel = CANAUX["etat_actionnaire"]["fichiers"]
    d = lire(rel)
    for l in d.get("dividendes_par_ligne_d_execution", []):
        e = l.get("entite")
        if not e:
            continue
        for an, v in sorted((l.get("execution_eur") or {}).items()):
            if isinstance(v, (int, float)):
                yield A(siren_de(e["siren"]), e["denomination"], e["categorie_juridique"], "etat_actionnaire",
                        "dividendes_verses_etat", rel, annee=int(an), montant=v,
                        precision=f"ligne d'exécution {l.get('code_execution')}")
    for op in d.get("operations_citees", {}).get("operations", []):
        e = op.get("entite") or {}
        for m in op.get("mentions", []):
            yield A(siren_de(e.get("siren")), e.get("denomination"), e.get("categorie_juridique"), "etat_actionnaire",
                    "operation_capital_citee", rel, annee=op.get("annee"), montant=m.get("montant_eur"),
                    precision=f"{m.get('nature')}, citation page {m.get('page')}")


def lire_operateurs(stats):
    rel = CANAUX["operateurs"]["fichiers"]
    d = lire(rel)
    for o in d.get("operateurs", []):
        s = siren_de(o.get("siren"))
        if o.get("niveau") == "operateur" and s:
            for an, x in sorted((o.get("annees") or {}).items()):
                if x.get("nature") != "execution":
                    continue
                src = x.get("sources") or {}
                if isinstance(x.get("financement_etat_total_cp_eur"), (int, float)):
                    yield A(s, o.get("nom"), o.get("categorie_juridique"), "operateurs", "financement_etat_execution",
                            rel, annee=int(an), montant=x["financement_etat_total_cp_eur"],
                            precision=f"{src.get('financement_etat') or 'jaune'} ; programme chef de file "
                                      f"{o.get('programme_chef_de_file')}",
                            lien="/explorer/operateurs?q=" + quote(o.get("nom") or ""))
                if isinstance(x.get("taxes_affectees_eur"), (int, float)):
                    yield A(s, o.get("nom"), o.get("categorie_juridique"), "operateurs", "taxes_affectees_execution",
                            rel, annee=int(an), montant=x["taxes_affectees_eur"],
                            precision=src.get("taxes_affectees_eur") or "jaune",
                            lien="/explorer/operateurs?q=" + quote(o.get("nom") or ""))
        elif o.get("niveau") == "operateur":
            stats["operateurs_sans_siren"] += 1
        for m in o.get("membres", []) or []:
            sm = siren_de(m.get("siren"))
            if sm:
                yield A(sm, m.get("nom"), m.get("categorie_juridique"), "operateurs", "membre_categorie_operateurs",
                        rel, periode="2024-2026", precision=f"catégorie « {o.get('nom')} »",
                        lien="/explorer/operateurs?q=" + quote(o.get("nom") or ""))


def lire_hospi(stats):
    rel = CANAUX["hospi_diag"]["fichiers"]
    d = lire(rel)
    col = d["colonnes"]
    i = {c: col.index(c) for c in col}
    for l in d.get("lignes", []):
        s = siren_de(l[i["siren"]])
        ref = l[i["referentiel"]]
        for cle, notion in (("recettes_t2a_eur", "recettes_t2a_declarees"),
                            ("recettes_migac_eur", "recettes_migac_declarees")):
            v = l[i[cle]]
            if isinstance(v, (int, float)):
                yield A(s, None, None, "hospi_diag", notion, rel, annee=l[i["annee"]], montant=v,
                        precision=f"établissement FINESS {l[i['finess']]}, référentiel {ref}",
                        groupe=f"référentiel {ref} ({'comptes financiers' if ref == 'D' else 'liasses fiscales' if ref == 'O' else 'non précisé'})",
                        departement=l[i["departement"]])


def lire_finess(stats):
    comptes = defaultdict(lambda: [None, None, 0])
    for rel in fichiers(CANAUX["finess"]["fichiers"]):
        d = lire(rel)
        e = d.get("etablissements") or {}
        col = e.get("colonnes", [])
        if "siren" not in col:
            continue
        i = {c: col.index(c) for c in col}
        dep = d.get("departement")
        for l in e.get("lignes", []):
            s = siren_de(l[i["siren"]])
            if s:
                c = comptes[(s, dep, rel)]
                c[0] = l[i["entite_juridique"]]
                c[2] += 1
    for (s, dep, rel), (nom, _, n) in sorted(comptes.items()):
        yield A(s, nom, None, "finess", "etablissements_finess", rel,
                precision=f"{n} établissement{'s' if n > 1 else ''} listé{'s' if n > 1 else ''} dans le département {dep}",
                lien=f"/explorer/hopitaux?dep={dep}", departement=dep)


def lire_anr(stats):
    rel = CANAUX["anr"]["fichiers"]
    d = lire(rel)
    for bloc, notion, cle in (("pia_france2030", "aide_projets_coordonnes", "aide_projets_coordonnes_eur"),
                              ("anr_2005_2009", "aide_anr_allouee", "aide_allouee_eur")):
        b = d.get(bloc) or {}
        col = b.get("colonnes", [])
        i = {c: col.index(c) for c in col}
        for l in b.get("etablissements", []):
            per = periode_de([l[i["premiere_edition"]], l[i["derniere_edition"]]])
            yield A(siren_de(l[i["siren"]]), l[i["denomination"]], l[i["categorie_juridique"]], "anr", notion, rel,
                    periode=per, montant=l[i[cle]],
                    precision=f"{l[i['participations']]} participations, {l[i['projets_coordonnes']]} projets coordonnés"
                              f" ({'investissements d’avenir et France 2030' if bloc == 'pia_france2030' else 'projets 2005-2009'})")


NOTION_LYCEES = {"11": "lycees_subventions_votees", "24": "lycees_dotations_versees", "52": "lycees_aides_actions"}


def lire_lycees(stats):
    for rel in fichiers(CANAUX["lycees"]["fichiers"]):
        d = lire(rel)
        reg = Path(rel).stem
        notion = NOTION_LYCEES.get(reg)
        if not notion:
            stats["lycees_region_inconnue"] += 1
            continue
        col = d["colonnes"]
        i = {c: col.index(c) for c in col}
        annees = d["annees"]
        for l in d.get("etablissements", []):
            s = siren_de(l[i["siren"]])
            for k, v in enumerate(l[i["montants_eur"]] or []):
                if isinstance(v, (int, float)):
                    yield A(s, l[i["nom"]], l[i["categorie_juridique"]], "lycees", notion, rel, annee=annees[k],
                            montant=v, precision=f"{d.get('attribuant', {}).get('nom', 'région')}, UAI {l[i['uai']]}",
                            lien=f"/explorer/education-recherche?region={reg}",
                            groupe=d.get("attribuant", {}).get("nom") or f"région {reg}",
                            departement=l[i["departement"]])


def lire_etudiants(stats, sans_siren):
    rel = CANAUX["etudiants"]["fichiers"]
    d = lire(rel)
    col = d["colonnes"]
    i = {c: col.index(c) for c in col}
    annees = d.get("annees", [])
    for l in d.get("etablissements", []):
        serie = l[i["etudiants"]] or []
        der = max((k for k, v in enumerate(serie) if isinstance(v, (int, float))), default=None)
        prec = (f"{int(serie[der])} inscriptions principales en {annees[der]}" if der is not None
                else "effectifs non publiés")
        s = siren_de(l[i["siren"]])
        if s:
            yield A(s, l[i["nom"]], l[i["categorie_juridique"]], "etudiants", "effectifs_etudiants", rel,
                    annee=annees[der] if der is not None else None, precision=prec, departement=l[i["departement"]])
        elif l[i["nom"]]:
            sans_siren.append({"canal": "etudiants", "notion": "effectifs_etudiants", "fichier": rel, "nom": l[i["nom"]],
                               "departement": l[i["departement"]], "annee": annees[der] if der is not None else None,
                               "precision": prec, "lien": None, "cle": l[i["id_paysage"]]})


# --- Référentiel SIRENE ----------------------------------------------------------------------------------------------

def referentiel_sirene(sirens: set[str]) -> dict[str, dict]:
    """Catégorie juridique, dénomination, sigle et diffusion des SIREN demandés, lus dans le stock (colonnes de nom et
    de prénom jamais lues). Vide si le stock est absent : la catégorie de la source sert alors seule."""
    if not STOCK.exists() or not sirens:
        return {}
    import duckdb
    import pyarrow as pa
    con = duckdb.connect()
    con.execute("set memory_limit='1GB'; set threads=1")
    con.register("demandes", pa.table({"siren": sorted(sirens)}))
    lignes = con.execute(f"""
        select u.siren, u.categorieJuridiqueUniteLegale, u.denominationUniteLegale, u.sigleUniteLegale,
               u.statutDiffusionUniteLegale
        from read_parquet('{STOCK}') u join demandes d using (siren)""").fetchall()
    con.close()
    return {s: {"cj": str(cj) if cj is not None else None, "nom": nom, "sigle": sigle, "diffusion": diff}
            for s, cj, nom, sigle, diff in lignes}


# --- Rapprochement des lignes sans SIREN (Splink) -------------------------------------------------------------------

PARAMETRES_SPLINK = {
    "probabilite_a_priori": 1 / 300,
    "blocage": "même département",
    "niveaux": [
        {"niveau": "nom normalisé identique", "m": 0.60, "u": 0.0001},
        {"niveau": "mêmes mots du nom, dans un autre ordre", "m": 0.10, "u": 0.0002},
        {"niveau": "similarité de Jaro-Winkler du nom au moins 0,95", "m": 0.15, "u": 0.0003},
        {"niveau": "similarité de Jaro-Winkler du nom au moins 0,88", "m": 0.08, "u": 0.01},
        {"niveau": "autre", "m": 0.07, "u": 0.9895},
    ],
}


def rapprocher(gauche: list[dict], droite: list[dict]) -> list[dict]:
    """Splink (link_only) : pour chaque ligne de gauche, candidats de droite du même département avec leur
    probabilité. Renvoie [{cle_g, siren, probabilite}] triés."""
    if not gauche or not droite:
        return []
    import logging

    import pandas as pd
    import splink.comparison_level_library as cll
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on
    logging.getLogger("splink").setLevel(logging.ERROR)
    n = PARAMETRES_SPLINK["niveaux"]
    comp = cl.CustomComparison(output_column_name="nom", comparison_levels=[
        cll.NullLevel("nom"),
        cll.ExactMatchLevel("nom").configure(m_probability=n[0]["m"], u_probability=n[0]["u"]),
        cll.ExactMatchLevel("nom_tri").configure(m_probability=n[1]["m"], u_probability=n[1]["u"]),
        cll.JaroWinklerLevel("nom", 0.95).configure(m_probability=n[2]["m"], u_probability=n[2]["u"]),
        cll.JaroWinklerLevel("nom", 0.88).configure(m_probability=n[3]["m"], u_probability=n[3]["u"]),
        cll.ElseLevel().configure(m_probability=n[4]["m"], u_probability=n[4]["u"]),
    ])
    reglages = SettingsCreator(link_type="link_only", comparisons=[comp],
                               blocking_rules_to_generate_predictions=[block_on("departement")],
                               probability_two_random_records_match=PARAMETRES_SPLINK["probabilite_a_priori"],
                               retain_intermediate_calculation_columns=False, retain_matching_columns=False)

    def table(lignes):
        return pd.DataFrame([{"unique_id": x["id"], "nom": x["nom_norm"], "nom_tri": " ".join(sorted(x["nom_norm"].split())),
                              "departement": x["departement"]} for x in lignes])
    db = DuckDBAPI()
    db.duckdb_con.execute("set threads=1")
    linker = Linker([db.register(table(gauche), dataset_display_name="sans_siren"),
                     db.register(table(droite), dataset_display_name="avec_siren")], reglages, log_level=None)
    p = linker.inference.predict(threshold_match_probability=SEUIL_INCERTAIN).as_pandas_dataframe()
    out = []
    for _, r in p.iterrows():
        if r["source_dataset_l"] == "sans_siren":
            g, dd = r["unique_id_l"], r["unique_id_r"]
        else:
            g, dd = r["unique_id_r"], r["unique_id_l"]
        out.append({"cle_g": g, "cle_d": dd, "probabilite": round(float(r["match_probability"]), 4)})
    return sorted(out, key=lambda x: (x["cle_g"], -x["probabilite"], x["cle_d"]))


# --- Production -------------------------------------------------------------------------------------------------

def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > TAILLE_MAX:
        raise SystemExit(f"{path} dépasse 1 Mo ({n} octets) : découper")
    path.write_text(texte + "\n", encoding="utf-8")
    return n


def taille(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


LECTEURS = [lire_associations, lire_reserve, lire_subventions, lire_france2030, lire_marches_etat, lire_marches,
            lire_tam, lire_france_relance, lire_fonds_europeens, lire_representants, lire_etat_actionnaire,
            lire_operateurs, lire_hospi, lire_finess, lire_anr, lire_lycees]


def collecter_apparitions():
    stats = Counter()
    sans_siren: list[dict] = []
    app: list[dict] = []
    absents = []
    for lecteur in LECTEURS:
        try:
            app.extend(lecteur(stats))
        except FileNotFoundError as e:
            absents.append(str(Path(e.filename).relative_to(SITE)) if e.filename else lecteur.__name__)
    for lecteur in (lire_chambres, lire_etudiants):
        try:
            app.extend(lecteur(stats, sans_siren))
        except FileNotFoundError as e:
            absents.append(str(Path(e.filename).relative_to(SITE)) if e.filename else lecteur.__name__)
    return app, sans_siren, stats, absents


def date_des_sources(rels: set[str]) -> str:
    """Date la plus récente écrite dans les fichiers relus (collecte_le, date_sources) : déterministe."""
    dates = []
    for rel in sorted(rels):
        try:
            d = lire(rel)
        except (OSError, ValueError):
            continue
        for cle in ("collecte_le", "date_sources", "genere_le"):
            v = d.get(cle) if isinstance(d, dict) else None
            if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
                dates.append(v[:10])
            elif isinstance(v, dict):
                dates += [x[:10] for x in v.values() if isinstance(x, str) and re.match(r"\d{4}-\d{2}-\d{2}", x)]
    return max(dates) if dates else "inconnue"


def cle_valeur(v):
    """Ordre d'une valeur [année ou période, montant] : années croissantes, périodes ensuite, montant décroissant."""
    t, m = v[0], v[1]
    return (isinstance(t, str), t if isinstance(t, int) else 0, t if isinstance(t, str) else "", -(m or 0))


def blocs_de(apps: list[dict]) -> list[dict]:
    """Regroupe les apparitions d'une organisation par canal et notion, puis en séries de même précision (une
    série : précision, lien, statut, valeurs [année ou période, montant tel que publié]) ; sommes du canal par année
    (règle 13 : même canal, même notion, même groupe, même année)."""
    par = defaultdict(list)
    for a in apps:
        par[(a["canal"], a["notion"])].append(a)
    blocs = []
    for (canal, notion), ls in sorted(par.items()):
        series = defaultdict(list)
        for l in ls:
            series[(l["precision"], l["lien"], l["statut"])].append(
                [l["annee"] if l["annee"] is not None else l["periode"], l["montant"]])
        liste = []
        for (prec, lien, statut), vals in series.items():
            x = {"precision": prec, "valeurs": sorted(vals, key=cle_valeur)}
            if lien:
                x["lien"] = lien
            if statut != "trace":
                x["statut"] = statut
            liste.append(x)
        liste.sort(key=lambda x: (cle_valeur(x["valeurs"][0]), x["precision"]))
        bloc = {"canal": canal, "notion": notion, "fichiers": sorted({l["fichier"] for l in ls})[:3],
                "nombre_lignes": len(ls)}
        if NOTIONS[notion]["somme_canal"]:
            g = defaultdict(list)
            for l in ls:
                if l["annee"] is not None and l["montant"] is not None:
                    g[(l["annee"], l["groupe"])].append(l["montant"])
            plusieurs = len({k[1] for k in g}) > 1
            sommes = [[an, round(sum(v), 2), len(v)] + ([grp] if plusieurs else [])
                      for (an, grp), v in sorted(g.items()) if len(v) > 1]
            if sommes:
                bloc["sommes_par_annee"] = sommes
        if len(liste) > LIGNES_MAX_PAR_BLOC:
            # séries conservées : celles dont le montant publié le plus élevé l'est le plus, puis dans l'ordre
            def maxi(x):
                return max((v[1] or 0) for v in x["valeurs"])
            garde = set(sorted(range(len(liste)), key=lambda k: (-maxi(liste[k]), k))[:LIGNES_MAX_PAR_BLOC])
            bloc["series_non_affichees"] = {
                "nombre": len(liste) - len(garde),
                "regle": f"seules les {LIGNES_MAX_PAR_BLOC} séries au montant publié le plus élevé sont affichées ; "
                         "les autres sont dans le fichier source"}
            liste = [x for k, x in enumerate(liste) if k in garde]
        bloc["series"] = liste
        blocs.append(bloc)
    return blocs


def sommes_entre_canaux(blocs: list[dict]) -> list[dict]:
    """Somme de canaux différents pour une même année et une même notion cumulable (règle 13). Aucune notion n'est
    cumulable aujourd'hui : la fonction ne publie rien tant que ce n'est pas le cas."""
    g = defaultdict(lambda: defaultdict(float))
    for b in blocs:
        grp = NOTIONS[b["notion"]]["cumulable"]
        if not grp:
            continue
        for x in b["series"]:
            for t, m in x["valeurs"]:
                if isinstance(t, int) and m is not None:
                    g[(t, grp)][b["canal"]] += m
    out = []
    for (an, grp), canaux in sorted(g.items()):
        if len(canaux) > 1:
            out.append({"annee": an, "groupe": grp, "montant_eur": round(sum(canaux.values()), 2),
                        "canaux": sorted(canaux), "statut": "calculé par le site"})
    return out


def produire(sortie: Path = SORTIE) -> dict:
    app, sans_siren, stats, absents = collecter_apparitions()
    rels = {a["fichier"] for a in app} | {x["fichier"] for x in sans_siren}

    # 1. jointure exacte par SIREN
    sirens = {a["siren"] for a in app if a["siren"]}
    ref = referentiel_sirene(sirens)
    exclus = Counter()
    exclus_montant = Counter()
    from local import contient_nom_de_personne, prenoms
    liste_prenoms = prenoms()
    par_siren: dict[str, list[dict]] = defaultdict(list)
    for a in app:
        if not a["siren"]:
            exclus["sans_siren_valide"] += 1
            continue
        par_siren[a["siren"]].append(a)
    orgs = {}
    for s in sorted(par_siren):
        apps = par_siren[s]
        r = ref.get(s, {})
        cjs_source = sorted(Counter(a["cj"] for a in apps if a["cj"]).items(), key=lambda x: (-x[1], x[0]))
        cj = r.get("cj") or (cjs_source[0][0] if cjs_source else None)
        motif = None
        if not cj:
            motif = "categorie_inconnue"
        elif not sirene.personne_morale(cj):
            motif = "personne_physique_ou_groupement"
        elif r.get("diffusion") == "P":
            motif = "diffusion_partielle"
        noms = Counter(a["nom"] for a in apps if a["nom"])
        nom = (r.get("nom") or "").strip() or (sorted(noms.items(), key=lambda x: (-x[1], x[0]))[0][0] if noms else "")
        if r.get("sigle") and r["sigle"].strip() and r["sigle"].strip().upper() not in nom.upper():
            nom = f"{nom} ({r['sigle'].strip()})"
        if not motif and not nom:
            motif = "sans_denomination"
        if not motif and contient_nom_de_personne(nom, liste_prenoms):
            motif = "nom_de_personne_possible"
        if motif:
            exclus[motif] += 1
            continue
        deps = sorted({a["departement"] for a in apps if a.get("departement")})
        orgs[s] = {"siren": s, "denomination": nom, "categorie_juridique": cj, "departements": deps, "apps": apps}

    # 2. lignes sans SIREN : Splink sur nom normalisé et département
    droite = []
    for s, o in orgs.items():
        for dep in o["departements"]:
            droite.append({"id": f"{s}|{dep}", "nom_norm": normaliser(o["denomination"]), "departement": dep})
    gauche = []
    non_rapprochables = 0
    for k, x in enumerate(sans_siren):
        x["id"] = f"g{k:05d}"
        if not x.get("departement") or contient_nom_de_personne(x["nom"], liste_prenoms):
            non_rapprochables += 1
            x["decision"] = "non_rapprochable"
            continue
        x["nom_norm"] = normaliser(x["nom"])
        gauche.append(x)
    paires = rapprocher(gauche, droite)
    cand = defaultdict(list)
    for p in paires:
        cand[p["cle_g"]].append(p)
    decisions = Counter()
    probables_par_siren = defaultdict(list)
    for x in gauche:
        c = cand.get(x["id"], [])
        forts = [p for p in c if p["probabilite"] >= SEUIL_PROBABLE]
        if len({p["cle_d"].split("|")[0] for p in forts}) == 1:
            p = forts[0]
            s = p["cle_d"].split("|")[0]
            x["decision"] = "probable"
            probables_par_siren[s].append({"canal": x["canal"], "notion": x["notion"], "nom_publie": x["nom"],
                                           "departement": x["departement"], "score": p["probabilite"],
                                           "decision": "probable",
                                           "precision": x["precision"], "lien": x["lien"], "annee": x["annee"]})
        elif forts or c:
            x["decision"] = "incertain"
        else:
            x["decision"] = "different"
        decisions[x["decision"]] += 1
    decisions["non_rapprochable"] = non_rapprochables

    # 3. fiches
    date = date_des_sources(rels)
    entete = {"millesime": f"Sources du site relues le {date} (millésime propre à chaque source, écrit sur chaque "
                           f"ligne)",
              "source": "site/data : fichiers des axes subventions, associations, beneficiaires, marches, "
                        "aides_entreprises, fonds_europeens, controle, etat_actionnaire, operateurs, "
                        "sante_etablissements, education_recherche ; Insee, stock SIRENE des unités légales "
                        "(catégorie juridique, dénomination)"}
    fiches = {}
    toutes = {}
    for s, o in orgs.items():
        blocs = blocs_de(o["apps"])
        recoit = [b for b in blocs if NOTIONS[b["notion"]]["sens"] == "recoit"]
        autres = [b for b in blocs if NOTIONS[b["notion"]]["sens"] != "recoit"]
        f = {"siren": s, "denomination": o["denomination"], "categorie_juridique": o["categorie_juridique"],
             "departements": o["departements"], "canaux": sorted({b["canal"] for b in blocs}),
             "recoit": recoit, "autres": autres}
        se = sommes_entre_canaux(recoit)
        if se:
            f["sommes_entre_canaux"] = se
        if probables_par_siren.get(s):
            f["probables"] = sorted(probables_par_siren[s], key=lambda p: (-p["score"], p["canal"], p["nom_publie"], str(p["annee"])))
        toutes[s] = len(f["canaux"])
        # Une fiche relie au moins deux canaux (ou un canal et un rapprochement probable) : une organisation présente
        # dans un seul canal est déjà sur la page de ce canal.
        if len(f["canaux"]) >= MIN_CANAUX or f.get("probables"):
            fiches[s] = f

    if sortie.exists():
        shutil.rmtree(sortie)
    (sortie / "fiches").mkdir(parents=True)
    (sortie / "recherche").mkdir(parents=True)

    # découpage des fiches par préfixe du SIREN (3 chiffres, 4 si le fichier dépasse la taille visée)
    def grouper(cles, n):
        g = defaultdict(list)
        for k in cles:
            g[k[:n]].append(k)
        return g
    decoupage = {}
    tailles = []
    attente = [(p, ks) for p, ks in sorted(grouper(fiches, 3).items())]
    while attente:
        p, ks = attente.pop(0)
        contenu = {**entete, "prefixe": p, "colonnes_valeurs": COLONNES_VALEUR,
                   "fiches": {k: fiches[k] for k in sorted(ks)}}
        if taille(contenu) > TAILLE_VISEE and len(p) < 9:
            attente = [(q, kk) for q, kk in sorted(grouper(ks, len(p) + 1).items())] + attente
            continue
        decoupage[p] = f"entites/fiches/{p}.json"
        tailles.append(dump(sortie / "fiches" / f"{p}.json", contenu))

    # index de recherche par début de mot (2 lettres, 3 ou plus si le fichier dépasse la taille visée)
    entrees = {s: [s, f["denomination"], len(f["canaux"]), f["departements"][0] if f["departements"] else None]
               for s, f in fiches.items()}
    mots_par_siren = {s: sorted({m for m in mots_recherche(f["denomination"]) if len(m) >= 2 and m.upper() not in MOTS_VIDES})
                      for s, f in fiches.items()}
    cles_recherche = {}

    mots_frequents = []
    entrees_recherche = {}

    def ecrire_recherche(prefixe, sirens_):
        exact = prefixe.endswith("_")
        contenu = {**entete, "cle": prefixe, "colonnes": ["siren", "denomination", "canaux", "departement"],
                   "entrees": [entrees[s] for s in sorted(sirens_, key=lambda x: (entrees[x][1], x))]}
        if taille(contenu) > TAILLE_VISEE:
            if exact:  # mot trop fréquent pour un fichier : la recherche demande un autre mot
                mots_frequents.append({"mot": prefixe[:-1], "organisations": len(sirens_)})
                return
            g = defaultdict(set)
            for s in sirens_:
                for m in mots_par_siren[s]:
                    if m.startswith(prefixe):
                        g[m[:len(prefixe) + 1] if len(m) > len(prefixe) else prefixe + "_"].add(s)
            for q in sorted(g):
                ecrire_recherche(q, g[q])
            return
        cles_recherche[prefixe] = f"entites/recherche/{prefixe}.json"
        entrees_recherche[prefixe] = len(sirens_)
        dump(sortie / "recherche" / f"{prefixe}.json", contenu)

    g2 = defaultdict(set)
    for s, ms in mots_par_siren.items():
        for m in ms:
            g2[m[:2]].add(s)
    for p in sorted(g2):
        ecrire_recherche(p, g2[p])

    # recherche du site : organisations présentes dans plusieurs canaux (les plus nombreux canaux d'abord)
    multi = sorted((f for f in fiches.values() if len(f["canaux"]) >= 2),
                   key=lambda f: (-len(f["canaux"]), f["denomination"], f["siren"]))
    globale = {**entete, "colonnes": ["siren", "denomination", "canaux"],
               "regle": f"organisations présentes dans au moins deux canaux, les {RECHERCHE_GLOBALE_MAX} présentes "
                        "dans le plus grand nombre de canaux, puis par dénomination",
               "entrees": [[f["siren"], f["denomination"], len(f["canaux"])] for f in multi[:RECHERCHE_GLOBALE_MAX]]}
    dump(sortie / "recherche_globale.json", globale)

    # index
    par_canal = defaultdict(lambda: {"organisations": set(), "avec_fiche": set(), "lignes": 0, "notions": set()})
    for s_, o in orgs.items():
        for a in o["apps"]:
            c = par_canal[a["canal"]]
            c["organisations"].add(s_)
            if s_ in fiches:
                c["avec_fiche"].add(s_)
            c["lignes"] += 1
            c["notions"].add(a["notion"])
    canaux_idx = []
    for cid, c in CANAUX.items():
        x = par_canal.get(cid)
        canaux_idx.append({"id": cid, "titre": c["titre"], "chemins_source": c["fichiers"], "axe": c["axe"],
                           "page": c["page"], "organisations": len(x["organisations"]) if x else 0,
                           "organisations_avec_fiche": len(x["avec_fiche"]) if x else 0,
                           "lignes": x["lignes"] if x else 0, "notions": sorted(x["notions"]) if x else []})
    nb_canaux = Counter(toutes.values())
    index = {
        **entete,
        "unite": "euros, tels que publiés par chaque source (notion propre à chaque canal)",
        "avertissement": "Une organisation est reliée d'une source à l'autre par son SIREN. Les montants de canaux "
                         "différents n'ont ni la même définition, ni la même période : ils sont montrés côte à côte, "
                         "jamais additionnés. Une ligne publiée sans SIREN n'est rattachée qu'à titre probable, avec "
                         "son score, et n'est jamais fusionnée ni ajoutée.",
        "methode": {
            "etapes": [
                "1. Jointure exacte par SIREN (un SIRET est ramené à son SIREN) : décision « même ».",
                "2. Lignes publiées sans SIREN, avec un nom et un département (rapports des chambres régionales et "
                "territoriales des comptes, établissements d'enseignement supérieur) : nom normalisé (majuscules sans "
                "accents, mots vides retirés, abréviations courantes développées) comparé, dans le même département, "
                "aux organisations déjà reliées par SIREN, par Splink (modèle de Fellegi et Sunter à paramètres "
                "fixés, publiés ci-dessous, sans apprentissage).",
                f"3. Décision : « probable » si la probabilité est au moins {str(SEUIL_PROBABLE).replace('.', ',')} et "
                f"qu'un seul SIREN l'atteint ; « incertain » entre {str(SEUIL_INCERTAIN).replace('.', ',')} et ce seuil ou si plusieurs SIREN l'atteignent ; "
                "« différent » en dessous. Un rapprochement probable est affiché à part sur la fiche, avec son score, "
                "jamais fusionné ni additionné ; un rapprochement incertain n'est pas affiché.",
                "4. Sommes (règle du chiffre calculé par le site) : seulement pour des lignes d'un même canal, de la "
                "même année, de la même notion de montant et du même groupe (même liste, même référentiel, même "
                "région), avec la mention « calculé par le site » ; jamais entre canaux, jamais entre une période et "
                "une année.",
            ],
            "splink": {**PARAMETRES_SPLINK, "seuil_probable": SEUIL_PROBABLE, "seuil_incertain": SEUIL_INCERTAIN,
                       "version": _version_splink()},
            "modele": "inspiré de FollowTheMoney : organisation (LegalEntity) identifiée par son SIREN ; ses "
                      "apparitions sont des paiements (Payment), des marchés (Contract) ou des mentions ; aucune "
                      "personne (Person).",
        },
        "regle_personnes": "Seules les personnes morales sont reprises : catégorie juridique du stock SIRENE (à "
                           "défaut, celle de la source) de 2xxx à 9xxx hors groupements de personnes physiques "
                           "(sirene.personne_morale) ; unité à diffusion partielle exclue ; dénomination qui peut "
                           "contenir le nom d'une personne (civilité, prénom fréquent suivi d'un nom) exclue. Les "
                           "exclusions sont seulement comptées.",
        "notions": {k: {"libelle": v["libelle"], "sens": v["sens"], "somme_canal": v["somme_canal"],
                        "cumulable_entre_canaux": v["cumulable"]} for k, v in NOTIONS.items()},
        "canaux": canaux_idx,
        "non_relus": NON_RELUS,
        "fichiers_absents": sorted(set(absents)),
        "comptes": {
            "organisations_reliees_par_siren": len(toutes),
            "organisations_avec_fiche": len(fiches),
            "regle_fiche": "une fiche est publiée pour une organisation présente dans au moins deux canaux, ou dans "
                           "un canal avec un rapprochement probable ; une organisation présente dans un seul canal "
                           "figure sur la page de ce canal",
            "par_nombre_de_canaux": {str(k): v for k, v in sorted(nb_canaux.items())},
            "apparitions": sum(len(o["apps"]) for o in orgs.values()),
            "sirens_lus": len(sirens),
            "referentiel_sirene": {"sirens_trouves": len(ref), "stock_present": bool(ref)},
            "exclusions": dict(sorted(exclus.items())),
            "lignes_sans_siren": {"total": len(sans_siren), "par_canal": dict(sorted(Counter(x["canal"] for x in
                                                                                             sans_siren).items())),
                                  "decisions": dict(sorted(decisions.items()))},
            "autres": dict(sorted(stats.items())),
        },
        "fichiers": {"fiches": dict(sorted(decoupage.items())), "recherche": dict(sorted(cles_recherche.items())),
                     "mots_frequents": mots_frequents,
                     "recherche_entrees": dict(sorted(entrees_recherche.items())),
                     "recherche_globale": "entites/recherche_globale.json",
                     "regle_fiches": "fiche d'une organisation : fichier dont le préfixe est le plus long début de "
                                     "son SIREN présent dans `fiches`",
                     "regle_recherche": "mot cherché (minuscules sans accents) : fichier dont la clé est le plus long "
                                        "début du mot présent dans `recherche` ; « _ » final : mot exactement égal à "
                                        "la clé ; un mot de `mots_frequents` n'a pas de fichier (trop "
                                        "d'organisations) : la recherche s'appuie sur un autre mot"},
        "colonnes_valeurs": COLONNES_VALEUR,
        "ordre": {"regle": "fiches par SIREN ; dans une fiche, canaux par identifiant puis notion ; lignes par année "
                           "(ou période) croissante puis montant publié décroissant ; recherche par dénomination puis "
                           "SIREN", "cles": ["siren", "canal", "notion", "annee", "-montant_eur"]},
        "limites": [
            "Seules les organisations nommées par les fichiers du site sont reprises : pour plusieurs sources, ce sont "
            "les 50 premiers bénéficiaires (subventions par convention, France 2030, marchés de l'État, registre "
            "européen) ou les 10 premiers titulaires de chaque acheteur (marchés) ; une absence ne veut pas dire "
            "qu'aucun montant n'a été reçu.",
            "Les montants n'ont pas la même définition d'un canal à l'autre (engagé, attribué, notifié, versé, "
            "programmé, déclaré) : ils ne s'additionnent pas.",
            "Une même aide peut figurer dans deux canaux (aide France 2030 aussi publiée au registre européen, "
            "marché des services de l'État aussi compté parmi les marchés de tous les acheteurs, réserve "
            "parlementaire aussi comptée dans les jaunes budgétaires).",
            "Le rapprochement probable repose sur le nom et le département : un homonyme du même département peut "
            "être retenu à tort ; c'est pourquoi il n'est jamais fusionné.",
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(sortie / "index.json", index)
    return {"organisations": len(fiches), "fichiers_fiches": len(decoupage), "fichiers_recherche": len(cles_recherche),
            "taille_max_fiches": max(tailles) if tailles else 0, "decisions": dict(decisions),
            "exclusions": dict(exclus), "par_nombre_de_canaux": dict(nb_canaux)}


def _version_splink() -> str:
    try:
        from importlib.metadata import version
        return version("splink")
    except Exception:  # noqa: BLE001
        return "inconnue"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="produire", choices=["produire", "tout"])
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    print(json.dumps(produire(a.sortie), ensure_ascii=False))


if __name__ == "__main__":
    main()
