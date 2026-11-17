"""Éducation et recherche : projets de l'ANR, subventions des régions aux lycées, budgets des collectivités pour la
recherche et l'enseignement supérieur, effectifs étudiants et coût par étudiant calculé.

Entrées (entrepôt brut, non versionné ; sources déclarées dans collecte/catalogue.json, entrées `edrech_*`) :
  data/lake/_restreint/education_recherche/edrech_anr_pia/*_51cba202.csv, *_aca6972b.csv
      ANR, programmes d'investissements d'avenir et France 2030 : partenaires et projets (ODbL)
  data/lake/_restreint/education_recherche/edrech_anr_2005_2009/*_0d691519.csv, *_74a59cc0.csv
      ANR, projets financés 2005-2009 : partenaires et projets (ODbL)
  data/lake/education_recherche/edrech_annuaire_education.parquet     UAI, SIRET, commune, académie
  data/lake/education_recherche/edrech_budget_collectivites_esr.parquet
  data/lake/education_recherche/edrech_effectifs_etudiants.parquet
  data/lake/education_recherche/edrech_lycees_idf.parquet, edrech_lycees_pdl.parquet, edrech_lycees_cvl_<année>.parquet
  data/lake/_cache/local/sirene_unite_legale.parquet                  stock SIRENE (catégorie juridique), partagé
  site/data/beneficiaires/france2030.json                              lecture seule : lien, jamais recopié
Sorties (site/data/education_recherche/, chacune < 5 Mo) :
  index.json               sources, licences (ODbL), totaux par source, écarts, liens, limites, recherche préalable
  anr_etablissements.json  ANR par établissement (SIREN) ; organismes non appariés agrégés par catégorie
  anr_projets.json         ANR par année, action ou programme, catégorie d'organisme, région publiée
  lycees/<région>.json     subventions et dotations par lycée (UAI, SIREN), commune, département, année, dispositif
  collectivites_esr.json   budgets des collectivités (recherche, enseignement supérieur) par région, type, année
  etudiants.json           effectifs par établissement, commune, département, région ; coût par étudiant « calculé »

Commandes :
  python pipeline/education_recherche.py collecter   # réseau, par collecte/collecte.py ; un refus est noté, jamais contourné
  python pipeline/education_recherche.py produire [--sortie DOSSIER]   # sans réseau
  python pipeline/education_recherche.py             # les deux

Règles :
  - personnes physiques : les colonnes nom, prénom et ORCID du responsable scientifique, la ville du partenaire, le
    tiers, l'intitulé du dossier et l'appellation saisie ne sont jamais lus (COLONNES_LUES fait foi) ; un bénéficiaire
    n'est nommé que si sirene.personne_morale(catégorie juridique) est vrai, sinon il est agrégé ;
  - l'ANR ne publie aucun SIREN : un organisme est rattaché à une unité légale seulement si sa dénomination est
    identique (après normalisation) à celle d'une seule personne morale du stock SIRENE, ou par une règle écrite pour
    les délégations de sept organismes nationaux ; le nom publié est la dénomination SIRENE ;
  - deux sources ne sont jamais additionnées ; les écarts sont publiés tels quels ;
  - une valeur absente à la source reste null, jamais 0 ; un 0 publié reste 0 et il est compté (lignes_montant_zero) ;
  - toute date vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
DOMAINE = "education_recherche"
BRUT = LAKE / DOMAINE
RESTREINT = LAKE / "_restreint" / DOMAINE
STOCK_SIRENE = LAKE / "_cache" / "local" / "sirene_unite_legale.parquet"
CACHE_APPARIEMENT = LAKE / "_cache" / DOMAINE / "appariement_sirene.json"
SITE = ROOT / "site" / "data"
SORTIE_DEFAUT = SITE / DOMAINE
MAX_OCTETS = 5_000_000
STATUT_CALCULE = "calculé"

# --- Sources ---------------------------------------------------------------------------------------------------------

DATAGOUV = "https://www.data.gouv.fr/datasets/"
ODS = "/explore/dataset/"
ODBL = "ODbL 1.0"
LO = "Licence Ouverte 2.0"
CVL_JEUX = {
    2017: "dotations-de-fonctionnement-versees-aux-lycees-de-la-region-centre-val-de-loire-",
    2018: "dotations-de-fonctionnement-aux-lycees-de-la-region-centre-val-de-loire-2018",
    2019: "dotations-de-fonctionnement-aux-lycees-de-la-region-centre-val-de-loire-2019",
    2020: "dotations-de-fonctionnement-aux-lycees-region-centre-val-de-loire-2020",
    2021: "dotations-de-fonctionnement-aux-lycees-de-la-region-centre-val-de-loire-2021",
    2022: "dotations-de-fonctionnement-aux-lycees-de-la-region-centre-val-de-loire-2022",
    2023: "dotations-de-fonctionnement-aux-lycees-de-la-region-centre-val-de-loire-2023",
    2024: "dotations-de-fonctionnement-versees-aux-lycees-de-la-region-centre-val-de-loire-en-2024",
    2025: "dotations-de-fonctionnement-versees-aux-lycees-de-la-region-centre-val-de-loire-en-2025",
}
SOURCES = {
    "anr_pia": {
        "catalogue": ["edrech_anr_pia"], "producteur": "Agence nationale de la recherche", "licence": ODBL,
        "page": DATAGOUV + "60ca244980d5c4f0aecd07d1",
        "titre": "ANR, « ANR_02 Projets ANR DGPIE : détail des projets et des partenaires » : projets des programmes "
                 "d'investissements d'avenir et de France 2030 opérés par l'ANR, partenaires et aide allouée par projet",
        "millesime": "éditions 2006 à 2026 (fichier du 2 novembre 2026)",
        "verdict": "à adapter (aucun SIREN ni montant par partenaire : appariement par dénomination)"},
    "anr_2005_2009": {
        "catalogue": ["edrech_anr_2005_2009"], "producteur": "Agence nationale de la recherche", "licence": ODBL,
        "page": DATAGOUV + "60ca2086030c7b7e52e2c02e",
        "titre": "ANR, « ANR_01 Projets ANR DOS et DGDS : détail des projets et des partenaires », fichiers 2005-2009 : "
                 "projets, partenaires et aide allouée par partenaire",
        "millesime": "éditions 2005 à 2009 (fichier du 2 octobre 2026)",
        "verdict": "à adapter (aucun SIREN : appariement par dénomination)"},
    "annuaire": {
        "catalogue": ["edrech_annuaire_education"], "producteur": "Ministère de l'Éducation nationale", "licence": LO,
        "page": "https://data.education.gouv.fr" + ODS + "fr-en-annuaire-education/",
        "titre": "Annuaire de l'éducation : table UAI vers SIRET, commune, département, académie (établissements "
                 "ouverts ; export sans adresse, téléphone, courriel ni site web)",
        "millesime": "état au 17 novembre 2026", "verdict": "réutilisable tel quel (export de l'API Opendatasoft)"},
    "budget_collectivites": {
        "catalogue": ["edrech_budget_collectivites_esr"], "licence": LO,
        "producteur": "Ministère chargé de l'enseignement supérieur et de la recherche (SIES)",
        "page": "https://data.enseignementsup-recherche.gouv.fr" + ODS
                + "fr-esr-budget-collectivites-recherche-technologie-enseignement-superieur/",
        "titre": "SIES, « Budgets des collectivités territoriales en faveur de la recherche et du transfert de "
                 "technologie, de l'enseignement supérieur et de la vie étudiante » (enquête auprès des collectivités)",
        "millesime": "2006 à 2025 (2024 semi-définitif, 2025 prévisionnel)",
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft)"},
    "effectifs": {
        "catalogue": ["edrech_effectifs_etudiants"], "licence": LO,
        "producteur": "Ministère chargé de l'enseignement supérieur et de la recherche",
        "page": "https://data.enseignementsup-recherche.gouv.fr" + ODS
                + "fr-esr-statistiques-sur-les-effectifs-d-etudiants-inscrits-par-etablissement/",
        "titre": "« Statistiques sur les effectifs d'étudiants inscrits par établissement public sous tutelle du "
                 "ministère en charge de l'Enseignement supérieur » : inscriptions principales",
        "millesime": "années universitaires 2006-07 à 2024-25",
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft)"},
    "lycees_idf": {
        "catalogue": ["edrech_lycees_idf"], "producteur": "Région Île-de-France", "licence": LO,
        "page": "https://data.iledefrance.fr" + ODS + "subventions-votees-pour-les-lycees/",
        "titre": "Région Île-de-France, « Données budgétaires des lycées : subventions votées »",
        "millesime": "décisions de 2021 à 2023", "verdict": "réutilisable tel quel (export de l'API Opendatasoft)"},
    "lycees_cvl": {
        "catalogue": [f"edrech_lycees_cvl_{an}" for an in CVL_JEUX], "producteur": "Région Centre-Val de Loire",
        "licence": ODBL,
        "page": "https://data.centrevaldeloire.fr" + ODS + CVL_JEUX[2025] + "/",
        "pages": {str(an): "https://data.centrevaldeloire.fr" + ODS + jeu + "/" for an, jeu in CVL_JEUX.items()},
        "titre": "Région Centre-Val de Loire, « Dotations de fonctionnement versées aux lycées » (un jeu par année)",
        "millesime": "2017 à 2025", "verdict": "à adapter (un format par année : colonnes ramenées à une seule forme)"},
    "lycees_pdl": {
        "catalogue": ["edrech_lycees_pdl"], "producteur": "Région des Pays de la Loire", "licence": ODBL,
        "page": "https://data.paysdelaloire.fr" + ODS
                + "234400034_012-001_actions-educatives-lycees-publics-et-prives-rpdl/",
        "titre": "Région des Pays de la Loire, « Actions éducatives conduites dans les lycées publics et privés » "
                 "(export sans adresse ni géolocalisation)",
        "millesime": "campagnes 2017-2018 à 2020-2021",
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft)"},
}
SOURCE_SIRENE = ("Insee, base SIRENE des unités légales (stock, Licence Ouverte 2.0) : catégorie juridique et "
                 "dénomination")
URL_ODBL = "https://opendatacommons.org/licenses/odbl/1-0/"

# Colonnes lues, et elles seules. Aucune ne porte de nom de personne, d'adresse, de courriel ni de téléphone.
COLONNES_LUES = {
    "anr_pia_partenaires": ["Projet.Code_Decision", "Action.Edition", "Projet.Partenaire.Est_coordinateur",
                            "Projet.Partenaire.Nom_organisme", "Projet.Partenaire.Categorie_organisme",
                            "Projet.Partenaire.Adresse.Region"],
    "anr_pia_projets": ["Projet.Code_Decision", "Action.Edition", "Action.Titre.Francais", "Projet.Aide_allouee"],
    "anr_0509_partenaires": ["Projet.Code_Decision", "Projet.Partenaire.Est_coordinateur",
                             "Projet.Partenaire.Nom_organisme", "Projet.Partenaire.Categorie_organisme",
                             "Projet.Partenaire.Aide_allouee.ANR"],
    "anr_0509_projets": ["Projet.Code_Decision", "AAP.Edition", "Programme.Acronyme",
                         "Projet.Montant.AF.Aide_allouee.ANR"],
    "annuaire": ["identifiant_de_l_etablissement", "nom_etablissement", "type_etablissement", "statut_public_prive",
                 "code_commune", "nom_commune", "libelle_departement", "libelle_academie", "siren_siret"],
    "lycees_idf": ["annee_de_la_decision", "code_siret", "code_uai_ex_rne", "type_de_tiers", "procedure_du_dossier",
                   "montant_vote"],
    "lycees_pdl": ["dmdc_campagne_nom", "uai", "ref_action", "mtaide", "code_commune"],
    "budget_collectivites": ["millesime", "qualite", "groupe_reg", "code_reg", "lib_reg", "type_co", "lib_type_co",
                             "cat_depenses", "code_var", "lib_var", "montant"],
    "effectifs": ["annee_universitaire", "annee", "attention", "etablissement_type", "etablissement_typologie",
                  "etablissement_id_paysage", "etablissement_lib", "etablissement_id_uai", "effectif",
                  "effectif_sans_cpge", "etablissement_id_region", "etablissement_region",
                  "etablissement_id_departement", "etablissement_departement", "etablissement_academie",
                  "etablissement_code_commune", "etablissement_commune"],
}
COLONNES_INTERDITES = re.compile(r"(?i)responsable|pr[eé]nom|orcid|adresse_|\.ville|telephone|mail|courriel|fax|"
                                 r"^tiers$|^dossier$|appellation|nom_complet")

# Délégations et centres d'un même organisme national : la dénomination de l'ANR commence par le nom ou le sigle de
# l'organisme. La dénomination cible doit exister une seule fois dans le stock SIRENE, sinon l'organisme reste agrégé.
REGLES_ORGANISMES = [
    (r"^(CENTRE NATIONAL DE LA RECHERCHE SCIENTIFIQUE|CNRS)\b", "CENTRE NATIONAL DE LA RECHERCHE SCIENTIFIQUE"),
    (r"^(INSTITUT NATIONAL DE LA SANTE ET DE LA RECHERCHE MEDICALE|INSERM)\b",
     "INSTITUT NATIONAL DE LA SANTE ET DE LA RECHERCHE MEDICALE"),
    (r"^(INSTITUT NATIONAL DE RECHERCHE EN INFORMATIQUE ET EN AUTOMATIQUE|INRIA)\b",
     "INSTITUT NATIONAL DE RECHERCHE EN INFORMATIQUE ET EN AUTOMATIQUE"),
    (r"^(COMMISSARIAT A L ENERGIE ATOMIQUE|CEA)\b",
     "COMMISSARIAT A L ENERGIE ATOMIQUE ET AUX ENERGIES ALTERNATIVES"),
    (r"^(INSTITUT NATIONAL DE RECHERCHE POUR L AGRICULTURE L ALIMENTATION ET L ENVIRONNEMENT|INRAE)\b",
     "INSTITUT NATIONAL DE RECHERCHE POUR L AGRICULTURE L ALIMENTATION ET L ENVIRONNEMENT"),
    (r"^(INSTITUT DE RECHERCHE POUR LE DEVELOPPEMENT( IRD\b|$)|IRD\b)", "INSTITUT DE RECHERCHE POUR LE DEVELOPPEMENT"),
    (r"^(ASSISTANCE PUBLIQUE HOPITAUX DE PARIS|AP HP|APHP)\b", "ASSISTANCE PUBLIQUE HOPITAUX DE PARIS"),
]
METHODES = {
    "denomination_identique": "dénomination de l'ANR identique, après normalisation (capitales, sans accent ni "
                              "ponctuation), à celle d'une seule personne morale du stock SIRENE (une seule unité "
                              "active, ou une seule unité s'il n'en reste aucune active)",
    "regle_organisme_national": "délégation ou centre d'un organisme national : la dénomination de l'ANR commence "
                                "par le nom ou le sigle de l'organisme (CNRS, Inserm, Inria, CEA, INRAE, IRD, AP-HP), "
                                "rattaché à l'unité légale de l'organisme",
}

REGIONS_LYCEES = {
    "11": {"nom": "Île-de-France", "source": "lycees_idf", "attribuant": "237500079",
           "nature": "subventions votées (affectations, nettes des désaffectations), année de la décision"},
    "24": {"nom": "Centre-Val de Loire", "source": "lycees_cvl", "attribuant": "234500023",
           "nature": "dotations de fonctionnement versées, année de versement"},
    "52": {"nom": "Pays de la Loire", "source": "lycees_pdl", "attribuant": "234400034",
           "nature": "aides aux actions éducatives, année de début de la campagne (année scolaire)"},
}
CVL_2017 = {"dgf_2017": "DGF", "travaux_du_proprietaire": "Travaux du propriétaire",
            "complement_dgf": "Complément DGF", "charges_particulieres": "Charges particulières",
            "transport_des_eleves": "Transport des élèves", "location_eps": "Location EPS",
            "transport_eps": "Transport EPS"}
MAX_DISPOSITIFS = 60

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "conclusion": "Les producteurs publient déjà les jeux nécessaires (data.gouv.fr pour l'ANR, API Opendatasoft des "
                  "ministères et des régions) : ils sont repris tels quels ou adaptés. Aucun dépôt public trouvé ne "
                  "relie ces jeux entre eux (UAI, SIREN, commune) ni n'applique la règle des personnes morales : "
                  "module écrit pour le dépôt, sur le modèle de pipeline/prestations.py et de pipeline/territoires.py.",
    "trouvailles": [
        {"nom": "ANR, jeux « ANR_01 » et « ANR_02 » (data.gouv.fr)", "url": SOURCES["anr_pia"]["page"],
         "licence": ODBL, "mise_a_jour": "2026-11-01", "verdict": "à adapter"},
        {"nom": "Annuaire de l'éducation (data.education.gouv.fr)", "url": SOURCES["annuaire"]["page"],
         "licence": LO, "mise_a_jour": "2026-11-17", "verdict": "réutilisable tel quel"},
        {"nom": "SIES, budgets des collectivités pour la recherche et l'enseignement supérieur",
         "url": SOURCES["budget_collectivites"]["page"], "licence": LO, "mise_a_jour": "2026-09-09",
         "verdict": "réutilisable tel quel"},
        {"nom": "Effectifs d'étudiants inscrits par établissement", "url": SOURCES["effectifs"]["page"],
         "licence": LO, "mise_a_jour": "2025-11-07", "verdict": "réutilisable tel quel"},
        {"nom": "Région Île-de-France, subventions votées pour les lycées", "url": SOURCES["lycees_idf"]["page"],
         "licence": LO, "mise_a_jour": "2024-03-20", "verdict": "réutilisable tel quel"},
        {"nom": "Région Centre-Val de Loire, dotations de fonctionnement aux lycées 2017 à 2025",
         "url": SOURCES["lycees_cvl"]["page"], "licence": ODBL, "mise_a_jour": "2026-01-27", "verdict": "à adapter"},
        {"nom": "Région des Pays de la Loire, actions éducatives dans les lycées", "url": SOURCES["lycees_pdl"]["page"],
         "licence": ODBL, "mise_a_jour": "2026-10-31", "verdict": "réutilisable tel quel"},
        {"nom": "pipeline/sirene.py, pipeline/local.py (ce dépôt) : personne_morale, objet_publiable, stock SIRENE",
         "url": "https://github.com/MoonEyes/Ou-vont-mes-impots", "licence": "MIT", "dernier_commit": "2026-11-17",
         "verdict": "réutilisable tel quel"},
        {"nom": "Recherches web « ANR projets financés data.gouv dépôt analyse partenaires », « annuaire éducation "
                "UAI SIRET dotations lycées région script »", "url": "https://www.data.gouv.fr/", "licence": None,
         "dernier_commit": None,
         "verdict": "aucun dépôt réutilisable trouvé ; seules les fiches des jeux officiels et leurs réutilisations "
                    "déclarées ressortent (inspiration seulement)"},
    ],
}


# --- Outils ----------------------------------------------------------------------------------------------------------

def norme(s) -> str:
    """Capitales sans accent ni ponctuation, espaces simples : clé de comparaison d'une dénomination."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


FILIALES = re.compile(r"\b(TRANSFERT|INNOVATION|VALORISATION|FILIALE|ENTREPRISES)\b")


def cles_organisme(nom) -> list[tuple[str, str]]:
    """[(clé de recherche dans SIRENE, méthode)] pour une dénomination de l'ANR : dénomination identique d'abord,
    puis règle des organismes nationaux (jamais pour une filiale de valorisation, qui est une autre personne morale)."""
    k = norme(nom)
    out = [(k, "denomination_identique")] if k else []
    if not FILIALES.search(k):
        for motif, cible in REGLES_ORGANISMES:
            if re.match(motif, k) and k != cible:
                out.append((cible, "regle_organisme_national"))
                break
    return out


def arrondi(x):
    return None if x is None else round(x + 0.0, 2)


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse 5 Mo ({n} octets) : découper")
    tmp = path.with_suffix(".part")
    tmp.write_text(texte + "\n", encoding="utf-8")
    tmp.replace(path)
    return n


def _duck():
    import duckdb
    return duckdb.connect()


def _cols(cle: str) -> str:
    cols = COLONNES_LUES[cle]
    assert not [c for c in cols if COLONNES_INTERDITES.search(c)], cle
    return ", ".join(f'"{c}"' for c in cols)


def lire(con, cle: str, chemin: Path, csv: bool = False) -> list[dict]:
    """Lit les seules colonnes de COLONNES_LUES[cle] ; les autres colonnes de la source ne quittent pas le fichier."""
    if not chemin.exists():
        raise SystemExit(f"source absente : {chemin} (python pipeline/education_recherche.py collecter)")
    src = (f"read_csv('{chemin}', delim=';', header=true, all_varchar=true, quote='\"')" if csv else f"'{chemin}'")
    cur = con.execute(f"select {_cols(cle)} from {src}")
    noms = [d[0] for d in cur.description]
    return [dict(zip(noms, r)) for r in cur.fetchall()]


def fichier_anr(dossier: str, rid: str) -> Path:
    trouves = sorted((RESTREINT / dossier).glob(f"*_{rid}.csv"))
    if not trouves:
        raise SystemExit(f"source absente : {RESTREINT / dossier}/*_{rid}.csv "
                         "(python pipeline/education_recherche.py collecter)")
    return trouves[-1]


def nombre(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def texte_publiable(t, longueur: int = 160):
    """Libellé de dispositif publié seulement s'il ne peut pas contenir un nom de personne (règle de local.py)."""
    import local  # lecture seule
    return local.objet_publiable(t, local.prenoms(), longueur)


# --- SIRENE ------------------------------------------------------------------------------------------------------

def _signature_stock() -> str:
    st = STOCK_SIRENE.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def candidats_sirene(cles: set[str]) -> dict[str, list]:
    """clé normalisée -> [[siren, catégorie juridique, état, dénomination], ...] (personnes morales du stock)."""
    if not STOCK_SIRENE.exists():
        raise SystemExit(f"stock SIRENE absent : {STOCK_SIRENE} (python pipeline/local.py le télécharge)")
    cles = {k for k in cles if k}
    empreinte = hashlib.sha256(("\n".join(sorted(cles)) + _signature_stock()).encode()).hexdigest()
    if CACHE_APPARIEMENT.exists():
        cache = json.loads(CACHE_APPARIEMENT.read_text(encoding="utf-8"))
        if cache.get("empreinte") == empreinte:
            return cache["candidats"]
    con = _duck()
    con.execute("create table cles(k varchar)")
    con.executemany("insert into cles values (?)", [[k] for k in sorted(cles)])
    lignes = con.execute(f"""
        select s.k, s.siren, s.cj, s.etat, s.den from (
            select siren, cast(categorieJuridiqueUniteLegale as varchar) cj, etatAdministratifUniteLegale etat,
                   denominationUniteLegale den,
                   trim(regexp_replace(upper(strip_accents(denominationUniteLegale)), '[^A-Z0-9]+', ' ', 'g')) k
            from '{STOCK_SIRENE}'
            where denominationUniteLegale is not null and categorieJuridiqueUniteLegale >= 2000) s
        semi join cles on cles.k = s.k order by 1, 2""").fetchall()
    candidats: dict[str, list] = {}
    for k, siren, cj, etat, den in lignes:
        candidats.setdefault(k, []).append([siren, cj, etat, den])
    CACHE_APPARIEMENT.parent.mkdir(parents=True, exist_ok=True)
    CACHE_APPARIEMENT.write_text(json.dumps({"empreinte": empreinte, "candidats": candidats}, ensure_ascii=False,
                                            sort_keys=True), encoding="utf-8")
    return candidats


def choisir(candidats: list | None) -> tuple[dict | None, str | None]:
    """(unité légale retenue, motif de non-rattachement). Une seule unité active, sinon une seule unité."""
    if not candidats:
        return None, "aucune_denomination_identique"
    actifs = [c for c in candidats if c[2] == "A"]
    retenus = actifs if actifs else candidats
    if len(retenus) != 1:
        return None, "plusieurs_unites_legales"
    siren, cj, _etat, den = retenus[0]
    if not (sirene.siren_valide(siren) and sirene.personne_morale(cj) and den):
        return None, "non_personne_morale"
    return {"siren": siren, "categorie_juridique": str(cj), "denomination": den.strip()}, None


def apparier(noms: set[str], candidats: dict | None = None) -> dict[str, dict]:
    """dénomination ANR -> {siren, categorie_juridique, denomination, methode} ou {motif}."""
    cles = {n: cles_organisme(n) for n in noms}
    if candidats is None:
        candidats = candidats_sirene({k for essais in cles.values() for k, _ in essais})
    out = {}
    for n, essais in cles.items():
        out[n] = {"motif": "aucune_denomination_identique"}
        for rang, (k, methode) in enumerate(essais):
            unite, motif = choisir(candidats.get(k))
            if unite:
                out[n] = dict(unite, methode=methode)
                break
            if rang == 0:
                out[n] = {"motif": motif}
    return out


def unites_legales(sirens: set[str]) -> dict[str, tuple]:
    """SIREN -> (catégorie juridique, dénomination) lus dans le stock SIRENE."""
    sirens = sorted(s for s in sirens if sirene.siren_valide(s))
    if not sirens:
        return {}
    if not STOCK_SIRENE.exists():
        raise SystemExit(f"stock SIRENE absent : {STOCK_SIRENE} (python pipeline/local.py le télécharge)")
    con = _duck()
    con.execute("create table s(siren varchar)")
    con.executemany("insert into s values (?)", [[x] for x in sirens])
    return {r[0]: (r[1], r[2]) for r in con.execute(
        f"select u.siren, cast(u.categorieJuridiqueUniteLegale as varchar), u.denominationUniteLegale "
        f"from '{STOCK_SIRENE}' u semi join s on s.siren = u.siren order by 1").fetchall()}


# --- ANR -------------------------------------------------------------------------------------------------------------

def _vrai(v) -> bool:
    return str(v or "").strip().lower() == "true"


def agreger_anr(partenaires: list[dict], aide_coordonnee: dict[str, float | None], rattachement: dict[str, dict],
                champ_aide: str, france2030: set[str] | None = None) -> dict:
    """Agrège des lignes {projet, nom, categorie, coordinateur, edition, aide} par unité légale ou par catégorie.

    `champ_aide` : nom du montant publié (aide des projets coordonnés pour les PIA, aide allouée au partenaire pour
    2005-2009). Conservation : nommés + non nommés = total de la source (contrôlé par les tests).
    """
    nommes: dict[str, dict] = {}
    agreges: dict[str, dict] = {}
    motifs: dict[str, int] = defaultdict(int)
    total = {"participations": 0, "projets_coordonnes": 0, champ_aide: 0.0, "lignes_sans_montant": 0}
    for p in partenaires:
        aide = p["aide"]
        r = rattachement.get(p["nom"]) or {"motif": "denomination_absente"}
        if "siren" in r:
            e = nommes.setdefault(r["siren"], {
                "siren": r["siren"], "denomination": r["denomination"],
                "categorie_juridique": r["categorie_juridique"], "methodes": set(), "categories": set(),
                "participations": 0, "projets_coordonnes": 0, champ_aide: 0.0, "lignes_sans_montant": 0,
                "editions": set()})
            e["methodes"].add(r["methode"])
        else:
            cat = p["categorie"] or "Non renseigné"
            e = agreges.setdefault(cat, {"categorie": cat, "organismes": set(), "participations": 0,
                                         "projets_coordonnes": 0, champ_aide: 0.0, "lignes_sans_montant": 0,
                                         "categories": set(), "editions": set()})
            e["organismes"].add(norme(p["nom"]))
            motifs[r["motif"]] += 1
        e["categories"].add(p["categorie"] or "Non renseigné")
        if p.get("edition"):
            e["editions"].add(p["edition"])
        for cible in (e, total):
            cible["participations"] += 1
            cible["projets_coordonnes"] += 1 if p["coordinateur"] else 0
            if aide is None:
                cible["lignes_sans_montant"] += 1 if p["compte_montant"] else 0
            else:
                cible[champ_aide] += aide
    lignes = []
    for e in sorted(nommes.values(), key=lambda e: (-e[champ_aide], -e["participations"], e["denomination"],
                                                     e["siren"])):
        ed = sorted(e["editions"])
        lignes.append([e["siren"], e["denomination"], e["categorie_juridique"],
                       "regle_organisme_national" if "regle_organisme_national" in e["methodes"]
                       else "denomination_identique",
                       sorted(e["categories"]), e["participations"], e["projets_coordonnes"], arrondi(e[champ_aide]),
                       e["lignes_sans_montant"], ed[0] if ed else None, ed[-1] if ed else None,
                       bool(france2030 and e["siren"] in france2030)])
    non_nommes = [{"categorie": a["categorie"], "organismes": len(a["organismes"]),
                   "participations": a["participations"], "projets_coordonnes": a["projets_coordonnes"],
                   champ_aide: arrondi(a[champ_aide]), "lignes_sans_montant": a["lignes_sans_montant"]}
                  for a in sorted(agreges.values(), key=lambda a: (-a["participations"], a["categorie"]))]
    somme = lambda xs, c: sum(x[c] for x in xs)  # noqa: E731
    return {
        "colonnes": ["siren", "denomination", "categorie_juridique", "methode_appariement", "categories_source",
                     "participations", "projets_coordonnes", champ_aide, "lignes_sans_montant", "premiere_edition",
                     "derniere_edition", "lien_france2030"],
        "etablissements": lignes,
        "ordre": {"cles": [f"-{champ_aide}", "-participations", "denomination", "siren"],
                  "regle": "montant décroissant, puis nombre de participations décroissant, puis dénomination"},
        "nommes": {"nombre": len(lignes), "participations": sum(x[5] for x in lignes),
                   "projets_coordonnes": sum(x[6] for x in lignes), champ_aide: arrondi(sum(x[7] for x in lignes))},
        "non_nommes": {"organismes": sum(len(a["organismes"]) for a in agreges.values()),
                       "participations": somme(non_nommes, "participations"),
                       "projets_coordonnes": somme(non_nommes, "projets_coordonnes"),
                       champ_aide: arrondi(sum(a[champ_aide] for a in agreges.values())),
                       "motifs": dict(sorted(motifs.items())), "par_categorie": non_nommes},
        "total": {"participations": total["participations"], "projets_coordonnes": total["projets_coordonnes"],
                  champ_aide: arrondi(total[champ_aide]), "lignes_sans_montant": total["lignes_sans_montant"]},
    }


def series(lignes: list[dict], cle: str, champs: list[str], limite: int | None = None) -> list[dict]:
    """Regroupe par `cle` en sommant `champs` (None ignoré) ; ordre : clé croissante (null en dernier)."""
    acc: dict = {}
    for li in lignes:
        a = acc.setdefault(li[cle], {cle: li[cle], **{c: 0 for c in champs}})
        for c in champs:
            if li.get(c) is not None:
                a[c] += li[c]
    out = sorted(acc.values(), key=lambda a: (a[cle] is None, a[cle] if a[cle] is not None else 0))
    for a in out:
        for c in champs:
            if isinstance(a[c], float):
                a[c] = arrondi(a[c])
    return out[:limite] if limite else out


def lire_anr(con) -> dict:
    pia_p = lire(con, "anr_pia_partenaires", fichier_anr("edrech_anr_pia", "51cba202"), csv=True)
    pia_j = lire(con, "anr_pia_projets", fichier_anr("edrech_anr_pia", "aca6972b"), csv=True)
    a_p = lire(con, "anr_0509_partenaires", fichier_anr("edrech_anr_2005_2009", "0d691519"), csv=True)
    a_j = lire(con, "anr_0509_projets", fichier_anr("edrech_anr_2005_2009", "74a59cc0"), csv=True)
    return {"pia_partenaires": pia_p, "pia_projets": pia_j, "a_partenaires": a_p, "a_projets": a_j}


def _annee(v):
    v = str(v or "").strip()
    return int(v) if re.match(r"^(19|20)\d\d$", v) else None


def construire_anr(brut: dict, rattachement: dict[str, dict], france2030: dict | None) -> tuple[dict, dict, dict]:
    """(anr_etablissements, anr_projets, résumé pour l'index) à partir des lignes lues et de l'appariement."""
    f2030_anr = (france2030 or {}).get("par_operateur", {}).get("ANR", {})
    sirens_f2030 = {b["siren"] for b in f2030_anr.get("top", [])}

    # PIA et France 2030 : l'aide est publiée par projet ; elle est rattachée au coordinateur du projet.
    projets = {}
    for j in brut["pia_projets"]:
        projets[j["Projet.Code_Decision"]] = {"annee": _annee(j["Action.Edition"]),
                                               "action": (j["Action.Titre.Francais"] or "").strip() or None,
                                               "aide": nombre(j["Projet.Aide_allouee"])}
    pia = []
    for p in brut["pia_partenaires"]:
        code = p["Projet.Code_Decision"]
        coord = _vrai(p["Projet.Partenaire.Est_coordinateur"])
        pj = projets.get(code, {})
        pia.append({"projet": code, "nom": p["Projet.Partenaire.Nom_organisme"],
                    "categorie": (p["Projet.Partenaire.Categorie_organisme"] or "").strip() or None,
                    "coordinateur": coord, "edition": pj.get("annee") or _annee(p["Action.Edition"]),
                    "aide": pj.get("aide") if coord else None, "compte_montant": coord,
                    "region": (p["Projet.Partenaire.Adresse.Region"] or "").strip() or None})
    bloc_pia = agreger_anr(pia, {}, rattachement, "aide_projets_coordonnes_eur", sirens_f2030)
    total_pia = sum(v["aide"] or 0 for v in projets.values())
    sans_coord = sorted(set(projets) - {p["projet"] for p in pia if p["coordinateur"]})
    aide_sans_coord = sum(projets[c]["aide"] or 0 for c in sans_coord)

    lignes_proj = [{"annee": v["annee"], "action": v["action"], "projets": 1, "aide_eur": v["aide"]}
                   for v in projets.values()]
    part_annee = defaultdict(int)
    for p in pia:
        part_annee[p["edition"]] += 1
    par_annee = series(lignes_proj, "annee", ["projets", "aide_eur"])
    for a in par_annee:
        a["participations"] = part_annee.get(a["annee"], 0)
    actions: dict = {}
    for li in lignes_proj:
        a = actions.setdefault(li["action"], {"action": li["action"], "projets": 0, "aide_eur": 0.0, "annees": set()})
        a["projets"] += 1
        a["aide_eur"] += li["aide_eur"] or 0
        if li["annee"]:
            a["annees"].add(li["annee"])
    par_action = [{"action": a["action"], "projets": a["projets"], "aide_eur": arrondi(a["aide_eur"]),
                   "premiere_edition": min(a["annees"]) if a["annees"] else None,
                   "derniere_edition": max(a["annees"]) if a["annees"] else None}
                  for a in sorted(actions.values(), key=lambda a: (-a["aide_eur"], str(a["action"])))]
    regions: dict = {}
    for p in pia:
        r = regions.setdefault(p["region"], {"region": p["region"], "participations": 0, "projets_coordonnes": 0,
                                             "aide_projets_coordonnes_eur": 0.0})
        r["participations"] += 1
        if p["coordinateur"]:
            r["projets_coordonnes"] += 1
            r["aide_projets_coordonnes_eur"] += p["aide"] or 0
    par_region = sorted(regions.values(), key=lambda r: (r["region"] is None, norme(r["region"])))
    for r in par_region:
        r["aide_projets_coordonnes_eur"] = arrondi(r["aide_projets_coordonnes_eur"])

    # 2005-2009 : l'aide est publiée par partenaire.
    proj_a = {j["Projet.Code_Decision"]: {"annee": _annee(j["AAP.Edition"]),
                                           "programme": (j["Programme.Acronyme"] or "").strip() or None,
                                           "aide": nombre(j["Projet.Montant.AF.Aide_allouee.ANR"])}
              for j in brut["a_projets"]}
    anc = [{"projet": p["Projet.Code_Decision"], "nom": p["Projet.Partenaire.Nom_organisme"],
            "categorie": (p["Projet.Partenaire.Categorie_organisme"] or "").strip() or None,
            "coordinateur": _vrai(p["Projet.Partenaire.Est_coordinateur"]),
            "edition": proj_a.get(p["Projet.Code_Decision"], {}).get("annee"),
            "aide": nombre(p["Projet.Partenaire.Aide_allouee.ANR"]), "compte_montant": True}
           for p in brut["a_partenaires"]]
    bloc_anc = agreger_anr(anc, {}, rattachement, "aide_allouee_eur")
    lignes_a = [{"annee": v["annee"], "programme": v["programme"], "projets": 1, "aide_projets_eur": v["aide"]}
                for v in proj_a.values()]
    par_annee_a = series(lignes_a, "annee", ["projets", "aide_projets_eur"])
    part_a = defaultdict(lambda: [0, 0.0])
    for p in anc:
        part_a[p["edition"]][0] += 1
        part_a[p["edition"]][1] += p["aide"] or 0
    for a in par_annee_a:
        a["participations"], a["aide_partenaires_eur"] = part_a[a["annee"]][0], arrondi(part_a[a["annee"]][1])
    progs: dict = {}
    for li in lignes_a:
        g = progs.setdefault(li["programme"], {"programme": li["programme"], "projets": 0, "aide_projets_eur": 0.0})
        g["projets"] += 1
        g["aide_projets_eur"] += li["aide_projets_eur"] or 0
    tries = sorted(progs.values(), key=lambda g: (-g["aide_projets_eur"], str(g["programme"])))
    par_programme = [dict(g, aide_projets_eur=arrondi(g["aide_projets_eur"])) for g in tries[:MAX_DISPOSITIFS]]
    autres = tries[MAX_DISPOSITIFS:]
    total_proj_a = sum(v["aide"] or 0 for v in proj_a.values())
    total_part_a = bloc_anc["total"]["aide_allouee_eur"]

    source_pia = f"{SOURCES['anr_pia']['titre']} ({SOURCES['anr_pia']['page']}) ; {SOURCE_SIRENE}"
    source_anc = f"{SOURCES['anr_2005_2009']['titre']} ({SOURCES['anr_2005_2009']['page']}) ; {SOURCE_SIRENE}"
    etablissements = {
        "millesime": "ANR : programmes d'investissements d'avenir et France 2030, éditions 2006 à 2026 ; projets "
                     "financés, éditions 2005 à 2009",
        "source": source_pia + " ; " + SOURCES["anr_2005_2009"]["titre"] + f" ({SOURCES['anr_2005_2009']['page']})",
        "unite": "euros (aide allouée)", "licence": ODBL, "date_sources": date_sources(DOMAINE),
        "regle_personnes": "L'ANR ne publie pas de SIREN. Un organisme est nommé seulement s'il est rattaché à une "
                           "personne morale du stock SIRENE (catégorie juridique 2xxx à 9xxx hors groupements de "
                           "personnes physiques) ; le nom publié est la dénomination SIRENE. Les autres organismes "
                           "(laboratoires, unités sans personnalité morale, dénominations sans équivalent unique) "
                           "sont agrégés par catégorie d'organisme. Les colonnes nom, prénom et ORCID du "
                           "responsable scientifique et la ville du partenaire ne sont jamais lues.",
        "methodes_appariement": METHODES,
        "pia_france2030": dict(
            {"millesime": SOURCES["anr_pia"]["millesime"], "source": source_pia,
             "lecture": "aide_projets_coordonnes_eur : aide allouée aux projets dont l'établissement est le "
                        "coordinateur. La source publie l'aide par projet, pas sa répartition entre partenaires : "
                        "ce montant n'est pas la somme reçue par l'établissement.",
             "lien_france2030": {
                 "fichier": "beneficiaires/france2030.json", "id": "par_operateur.ANR",
                 "lecture": "lien_france2030 vaut vrai quand le SIREN figure parmi les bénéficiaires nommés de "
                            "l'opérateur ANR dans ce fichier (autre source, montants par bénéficiaire) ; les deux "
                            "montants décrivent en partie les mêmes projets et ne s'additionnent pas."}},
            **bloc_pia,
            total_projets={"projets": len(projets), "aide_eur": arrondi(total_pia),
                           "projets_sans_coordinateur": len(sans_coord),
                           "aide_projets_sans_coordinateur_eur": arrondi(aide_sans_coord)}),
        "anr_2005_2009": dict(
            {"millesime": SOURCES["anr_2005_2009"]["millesime"], "source": source_anc,
             "lecture": "aide_allouee_eur : aide allouée par l'ANR au partenaire, telle que publiée ; "
                        "lignes_sans_montant compte les partenaires sans aide publiée (financement autre que "
                        "l'ANR, fonds propres ou montant absent), jamais comptés 0."},
            **bloc_anc,
            total_projets={"projets": len(proj_a), "aide_eur": arrondi(total_proj_a)}),
    }
    ecarts = [{
        "objet": "ANR 2005-2009 : aide par projet et aide par partenaire", "annee": None,
        "source": "fichier des projets (aide allouée par projet)", "montant": arrondi(total_proj_a),
        "autre_source": "fichier des partenaires (somme des aides allouées aux partenaires)",
        "autre_montant": arrondi(total_part_a), "ecart": arrondi(total_proj_a - total_part_a),
        "ecart_pct": round((total_proj_a - total_part_a) / total_part_a * 100, 3) if total_part_a else None,
        "lecture": "deux fichiers du même jeu ; l'écart est publié tel quel"}]
    if f2030_anr:
        annees_f = [a for a in par_annee if a["annee"] and 2021 <= a["annee"] <= 2025]
        m = sum(a["aide_eur"] for a in annees_f)
        ecarts.append({
            "objet": "France 2030 opéré par l'ANR", "annee": None,
            "source": "ANR, projets des éditions 2021 à 2025 (aide allouée par projet)", "montant": arrondi(m),
            "autre_source": "beneficiaires/france2030.json, opérateur ANR (projets décidés de 2021 à 2025, "
                            "subvention et avance remboursable par bénéficiaire)",
            "autre_montant": f2030_anr.get("total_eur"),
            "ecart": arrondi(m - f2030_anr["total_eur"]),
            "ecart_pct": round((m - f2030_anr["total_eur"]) / f2030_anr["total_eur"] * 100, 2),
            "lecture": "champs différents : année d'édition de l'action et aide par projet pour l'ANR (les actions "
                       "du programme d'investissements d'avenir encore ouvertes y figurent) ; date de décision et "
                       "montant par bénéficiaire pour le jeu France 2030. Les deux montants ne s'additionnent pas."})
    projets_json = {
        "millesime": etablissements["millesime"], "source": etablissements["source"],
        "unite": "euros (aide allouée)", "licence": ODBL, "date_sources": date_sources(DOMAINE),
        "pia_france2030": {
            "millesime": SOURCES["anr_pia"]["millesime"], "source": source_pia,
            "par_annee": par_annee, "par_action": par_action, "par_region": par_region,
            "ordre": {"cles": ["annee", "-aide_eur puis action", "region"],
                      "regle": "années croissantes ; actions par aide décroissante puis libellé ; régions par ordre "
                               "alphabétique du libellé publié"},
            "note": "Année : édition de l'action. Région : celle du partenaire, libellé publié par l'ANR (dont « Non "
                    "renseigné », « Etranger », « DROM-COM ») ; la source ne publie ni commune codée ni département.",
            "total": {"projets": len(projets), "aide_eur": arrondi(total_pia), "participations": len(pia)}},
        "anr_2005_2009": {
            "millesime": SOURCES["anr_2005_2009"]["millesime"], "source": source_anc,
            "par_annee": par_annee_a, "par_programme": par_programme,
            "par_programme_autres": {"programmes": len(autres),
                                     "projets": sum(g["projets"] for g in autres),
                                     "aide_projets_eur": arrondi(sum(g["aide_projets_eur"] for g in autres))},
            "ordre": {"cles": ["annee", "-aide_projets_eur puis programme"],
                      "regle": "années croissantes ; programmes par aide décroissante puis sigle"},
            "note": "Année : édition de l'appel à projets. La source ne publie ni région ni commune pour la plupart "
                    "des partenaires de cette période : aucune répartition territoriale.",
            "total": {"projets": len(proj_a), "aide_projets_eur": arrondi(total_proj_a),
                      "participations": len(anc), "aide_partenaires_eur": arrondi(total_part_a)}},
        "ecarts": ecarts,
    }
    resume = {
        "pia": {"projets": len(projets), "aide_eur": arrondi(total_pia), "participations": len(pia),
                "etablissements_nommes": bloc_pia["nommes"]["nombre"],
                "participations_nommees": bloc_pia["nommes"]["participations"],
                "aide_projets_coordonnes_nommes_eur": bloc_pia["nommes"]["aide_projets_coordonnes_eur"],
                "aide_projets_coordonnes_non_nommes_eur": bloc_pia["non_nommes"]["aide_projets_coordonnes_eur"]},
        "anr_2005_2009": {"projets": len(proj_a), "aide_projets_eur": arrondi(total_proj_a),
                          "participations": len(anc), "aide_partenaires_eur": arrondi(total_part_a),
                          "etablissements_nommes": bloc_anc["nommes"]["nombre"],
                          "aide_nommes_eur": bloc_anc["nommes"]["aide_allouee_eur"],
                          "aide_non_nommes_eur": bloc_anc["non_nommes"]["aide_allouee_eur"]},
        "ecarts": ecarts,
        "lien": {"fichier": "beneficiaires/france2030.json", "id": "par_operateur.ANR",
                 "total_eur": f2030_anr.get("total_eur"), "projets": f2030_anr.get("projets")} if f2030_anr else None,
    }
    return etablissements, projets_json, resume


# --- Lycées ----------------------------------------------------------------------------------------------------------

def dep_de_commune(code: str | None) -> str | None:
    code = (code or "").strip()
    if len(code) != 5:
        return None
    return code[:3] if code[:2] in ("97", "98") else code[:2]


def dep_de_uai(uai: str | None) -> str | None:
    u = uai_propre(uai)
    if not u:
        return None
    d = u[:3]
    return {"620": "2A", "720": "2B"}.get(d, d[1:] if d[0] == "0" else d)


UAI_RE = re.compile(r"^\d{7}[A-Z]$")


def uai_propre(v) -> str | None:
    """UAI en capitales ; un identifiant mal formé à la source est traité comme absent."""
    u = (v or "").strip().upper()
    return u if UAI_RE.match(u) else None


def lire_annuaire(con) -> dict[str, dict]:
    """UAI -> fiche (première ligne par UAI dans l'ordre du SIRET : choix déterministe pour les UAI répétés)."""
    lignes = lire(con, "annuaire", BRUT / "edrech_annuaire_education.parquet")
    out: dict[str, dict] = {}
    for r in sorted(lignes, key=lambda r: (r["identifiant_de_l_etablissement"] or "", r["siren_siret"] or "~",
                                           r["nom_etablissement"] or "")):
        uai = (r["identifiant_de_l_etablissement"] or "").strip().upper()
        if uai and uai not in out:
            siret = re.sub(r"\D", "", r["siren_siret"] or "")
            out[uai] = {"nom": (r["nom_etablissement"] or "").strip() or None,
                        "type": r["type_etablissement"], "secteur": r["statut_public_prive"],
                        "code_commune": r["code_commune"], "commune": r["nom_commune"],
                        "departement_nom": r["libelle_departement"], "academie": r["libelle_academie"],
                        "siren": siret[:9] if len(siret) in (9, 14) else None}
    return out


def lignes_idf(con) -> list[dict]:
    out = []
    for r in lire(con, "lycees_idf", BRUT / "edrech_lycees_idf.parquet"):
        siret = re.sub(r"\D", "", r["code_siret"] or "")
        out.append({"annee": _annee(r["annee_de_la_decision"]), "uai": uai_propre(r["code_uai_ex_rne"]),
                    "siren": siret[:9] if len(siret) == 14 else None, "dispositif": r["procedure_du_dossier"],
                    "montant": r["montant_vote"], "type_tiers": r["type_de_tiers"], "code_commune": None})
    return out


def lignes_cvl(con) -> tuple[list[dict], list[dict]]:
    """(lignes, contrôles). 2017 : une colonne par dotation ; ensuite : une ligne par dotation."""
    out, controles = [], []
    for an in sorted(CVL_JEUX):
        chemin = BRUT / f"edrech_lycees_cvl_{an}.parquet"
        if not chemin.exists():
            raise SystemExit(f"source absente : {chemin} (python pipeline/education_recherche.py collecter)")
        cur = con.execute(f"select * from '{chemin}'")
        cols = [d[0] for d in cur.description]
        c_uai = next(c for c in cols if c in ("code_uai", "code_rne"))
        lignes = [dict(zip(cols, r)) for r in cur.fetchall()]
        if "type_dotations" in cols:
            c_mt = next(c for c in cols if re.match(r"^montant_20\d\d$", c))
            for r in lignes:
                disp = re.sub(r"\s*20\d\d$", "", (r["type_dotations"] or "").strip()) or None
                out.append({"annee": an, "uai": uai_propre(r[c_uai]), "siren": None,
                            "dispositif": disp, "montant": r[c_mt], "type_tiers": None, "code_commune": None})
        else:
            c_total = next((c for c in cols if c.startswith("total_verse")), None)
            somme = total = 0.0
            for r in lignes:
                for c, lib in CVL_2017.items():
                    if c in r and r[c] is not None:   # cellule vide : dotation absente, pas un 0
                        somme += r[c]
                        out.append({"annee": an, "uai": uai_propre(r[c_uai]), "siren": None,
                                    "dispositif": lib, "montant": float(r[c]), "type_tiers": None,
                                    "code_commune": None})
                total += (r.get(c_total) or 0) if c_total else 0
            if c_total:
                controles.append({"annee": an, "somme_des_dotations_eur": arrondi(somme),
                                  "total_publie_eur": arrondi(total), "ecart_eur": arrondi(somme - total)})
    return out, controles


def lignes_pdl(con) -> list[dict]:
    out = []
    for r in lire(con, "lycees_pdl", BRUT / "edrech_lycees_pdl.parquet"):
        out.append({"annee": _annee((r["dmdc_campagne_nom"] or "")[:4]), "uai": uai_propre(r["uai"]),
                    "siren": None, "dispositif": re.sub(r"^Z-\s*", "", (r["ref_action"] or "").strip()) or None,
                    "montant": r["mtaide"], "type_tiers": None, "code_commune": r["code_commune"]})
    return out


def construire_lycees(code: str, lignes: list[dict], annuaire: dict[str, dict], unites: dict[str, tuple],
                      publiable=texte_publiable, controles: list | None = None) -> dict:
    """Fichier d'une région. Clé d'un bénéficiaire : UAI, sinon SIREN ; nommé seulement si personne morale."""
    reg = REGIONS_LYCEES[code]
    src = SOURCES[reg["source"]]
    annees = sorted({li["annee"] for li in lignes if li["annee"]})
    rang = {a: i for i, a in enumerate(annees)}
    benef: dict = {}
    disp: dict = {}
    par_annee = {a: {"annee": a, "total_eur": 0.0, "nommes_eur": 0.0, "non_nommes_eur": 0.0, "lignes": 0,
                     "lignes_montant_absent": 0, "lignes_montant_zero": 0, "beneficiaires": set()} for a in annees}
    hors_annee = {"lignes": 0, "montant_eur": 0.0}
    for li in lignes:
        if li["annee"] is None:
            hors_annee["lignes"] += 1
            hors_annee["montant_eur"] += li["montant"] or 0
            continue
        pa = par_annee[li["annee"]]
        pa["lignes"] += 1
        if li["montant"] is None:
            pa["lignes_montant_absent"] += 1
            continue
        if li["montant"] == 0:
            pa["lignes_montant_zero"] += 1
        cle = li["uai"] or (f"siren:{li['siren']}" if li["siren"] else f"type:{li['type_tiers'] or 'non renseigné'}")
        b = benef.setdefault(cle, {"uai": li["uai"], "sirens": defaultdict(float), "type_tiers": li["type_tiers"],
                                   "montants": [None] * len(annees), "code_commune": li["code_commune"]})
        fiche = annuaire.get(li["uai"] or "", {})
        siren = li["siren"] or fiche.get("siren")
        if siren:
            b["sirens"][siren] += li["montant"]
        else:
            b["sans_siren"] = True
        i = rang[li["annee"]]
        b["montants"][i] = (b["montants"][i] or 0.0) + li["montant"]
        pa["total_eur"] += li["montant"]
        pa["beneficiaires"].add(cle)
        d = disp.setdefault(li["dispositif"], {"montants": [None] * len(annees), "total": 0.0})
        d["montants"][i] = (d["montants"][i] or 0.0) + li["montant"]
        d["total"] += li["montant"]

    lignes_nommees, motifs = [], defaultdict(lambda: {"nombre": 0, "montant_eur": 0.0})
    non_nommes_annee = [0.0] * len(annees)
    communes: dict = {}
    deps: dict = {}
    for cle, b in benef.items():
        total = sum(m for m in b["montants"] if m is not None)
        fiche = annuaire.get(b["uai"] or "", {})
        sirens = sorted(b["sirens"], key=lambda s: (-b["sirens"][s], s))
        motif = None
        if not sirens or b.get("sans_siren"):
            motif = "uai_absent_de_l_annuaire_ou_sans_siret" if b["uai"] else "sans_identifiant"
        elif any(s not in unites for s in sirens):
            motif = "siren_absent_du_stock_sirene"
        elif not all(sirene.personne_morale(unites[s][0]) for s in sirens):
            motif = "personne_physique_ou_groupement"
        nom = fiche.get("nom") or (unites[sirens[0]][1] if sirens and sirens[0] in unites else None)
        if not motif and not nom:
            motif = "denomination_absente"
        code_commune = fiche.get("code_commune") or b["code_commune"]
        dep = dep_de_commune(code_commune) or dep_de_uai(b["uai"])
        for registre, k in ((communes, code_commune), (deps, dep)):
            g = registre.setdefault(k, {"montants": [None] * len(annees), "beneficiaires": 0, "total": 0.0,
                                        "nom": None})
            g["beneficiaires"] += 1
            g["total"] += total
            for i, m in enumerate(b["montants"]):
                if m is not None:
                    g["montants"][i] = (g["montants"][i] or 0.0) + m
            if registre is communes and fiche.get("commune"):
                g["nom"], g["departement"] = fiche["commune"], dep
            if registre is deps and fiche.get("departement_nom"):
                g["nom"] = fiche["departement_nom"]
        if motif:
            motifs[motif]["nombre"] += 1
            motifs[motif]["montant_eur"] += total
            for i, m in enumerate(b["montants"]):
                non_nommes_annee[i] += m or 0
            continue
        lignes_nommees.append([b["uai"], sirens[0], nom, str(unites[sirens[0]][0]), fiche.get("secteur"),
                               fiche.get("type") or b["type_tiers"], code_commune, dep, fiche.get("academie"),
                               arrondi(total), [arrondi(m) for m in b["montants"]]])
    lignes_nommees.sort(key=lambda r: (-r[9], r[2], r[0] or "", r[1]))
    for i, a in enumerate(annees):
        pa = par_annee[a]
        pa["non_nommes_eur"] = non_nommes_annee[i]
        pa["nommes_eur"] = pa["total_eur"] - non_nommes_annee[i]
    total = sum(pa["total_eur"] for pa in par_annee.values())
    total_non_nommes = sum(m["montant_eur"] for m in motifs.values())

    tri_disp = sorted(disp.items(), key=lambda kv: (-kv[1]["total"], str(kv[0])))
    par_dispositif = []
    autres = {"dispositifs": 0, "total_eur": 0.0, "libelles_non_publies": 0}
    for lib, d in tri_disp:
        pub = publiable(lib) if lib else None
        if len(par_dispositif) < MAX_DISPOSITIFS and pub:
            par_dispositif.append({"dispositif": pub, "total_eur": arrondi(d["total"]),
                                   "montants_eur": [arrondi(m) for m in d["montants"]]})
        else:
            autres["dispositifs"] += 1
            autres["total_eur"] += d["total"]
            autres["libelles_non_publies"] += 0 if pub else 1
    autres["total_eur"] = arrondi(autres["total_eur"])

    def groupes(registre, cle):
        out = []
        for k, g in sorted(registre.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
            e = {cle: k, "nom": g["nom"], "beneficiaires": g["beneficiaires"], "total_eur": arrondi(g["total"]),
                 "montants_eur": [arrondi(m) for m in g["montants"]]}
            if cle == "code_commune":
                e["departement"] = g.get("departement") or dep_de_commune(k)
            out.append(e)
        return out

    doc = {
        "millesime": f"{reg['nom']} : {src['millesime']}",
        "source": f"{src['titre']} ({src['page']}) ; {SOURCES['annuaire']['titre']} "
                  f"({SOURCES['annuaire']['page']}) ; {SOURCE_SIRENE}",
        "unite": "euros", "licence": src["licence"], "date_sources": date_sources(DOMAINE),
        "region": {"code": code, "nom": reg["nom"]}, "attribuant": {"siren": reg["attribuant"],
                                                                       "nom": src["producteur"]},
        "nature_des_montants": reg["nature"], "annees": annees,
        "colonnes": ["uai", "siren", "nom", "categorie_juridique", "secteur", "type", "code_commune", "departement",
                     "academie", "total_eur", "montants_eur"],
        "etablissements": lignes_nommees,
        "ordre": {"cles": ["-total_eur", "nom", "uai", "siren"],
                  "regle": "montant total décroissant, puis nom, puis identifiant"},
        "nommes": {"nombre": len(lignes_nommees), "montant_eur": arrondi(total - total_non_nommes)},
        "non_nommes": {"nombre": sum(m["nombre"] for m in motifs.values()), "montant_eur": arrondi(total_non_nommes),
                       "part_pct": round(total_non_nommes / total * 100, 2) if total else None,
                       "motifs": {k: {"nombre": v["nombre"], "montant_eur": arrondi(v["montant_eur"])}
                                  for k, v in sorted(motifs.items())}},
        "par_annee": [{"annee": a, "total_eur": arrondi(pa["total_eur"]), "nommes_eur": arrondi(pa["nommes_eur"]),
                       "non_nommes_eur": arrondi(pa["non_nommes_eur"]), "beneficiaires": len(pa["beneficiaires"]),
                       "lignes": pa["lignes"], "lignes_montant_absent": pa["lignes_montant_absent"],
                       "lignes_montant_zero": pa["lignes_montant_zero"]} for a, pa in sorted(par_annee.items())],
        "par_dispositif": par_dispositif, "par_dispositif_autres": autres,
        "par_commune": groupes(communes, "code_commune"), "par_departement": groupes(deps, "departement"),
        "total_eur": arrondi(total), "lignes_sans_annee": {"lignes": hors_annee["lignes"],
                                                           "montant_eur": arrondi(hors_annee["montant_eur"])},
        "regle_personnes": "Un bénéficiaire est nommé seulement si son SIREN (SIRET de la source ou de l'annuaire de "
                           "l'éducation) est celui d'une personne morale du stock SIRENE ; le nom est celui de "
                           "l'annuaire, à défaut la dénomination SIRENE. Les autres bénéficiaires sont agrégés dans "
                           "non_nommes avec leur motif. Tiers, intitulé du dossier et appellation saisie ne sont "
                           "jamais lus.",
        "note": "par_commune et par_departement comptent tous les bénéficiaires, nommés ou non ; code_commune null : "
                "bénéficiaire sans UAI ou absent de l'annuaire (établissement fermé ou organisme sans UAI). "
                "Commune et académie : annuaire de l'éducation (établissements ouverts).",
    }
    if controles:
        doc["controles"] = controles
    return doc


# --- Collectivités : recherche et enseignement supérieur ---------------------------------------------------------

CATEGORIES_ESR = {"Recherche et transfert de technologie": "rt", "Enseignement supérieur et vie étudiante": "esve"}


def construire_collectivites(lignes: list[dict]) -> dict:
    annees = sorted({_annee(r["millesime"]) for r in lignes if _annee(r["millesime"])})
    rang = {a: i for i, a in enumerate(annees)}
    qualite = {}
    types = {}
    natures = {}
    regions: dict = {}
    nat = [{"annee": a, "qualite": None, "total_eur": 0.0, "rt_eur": 0.0, "esve_eur": 0.0, "par_type": {},
            "par_nature": {}} for a in annees]
    sans_montant = 0
    for r in lignes:
        a = _annee(r["millesime"])
        cat = CATEGORIES_ESR.get(r["cat_depenses"])
        if a is None or cat is None:
            raise SystemExit(f"budgets des collectivités : ligne inattendue {r['millesime']!r}, {r['cat_depenses']!r}")
        i = rang[a]
        qualite[a] = r["qualite"]
        types[r["type_co"]] = r["lib_type_co"]
        natures[r["code_var"]] = {"code": r["code_var"], "libelle": r["lib_var"], "categorie": cat}
        if r["montant"] is None:
            sans_montant += 1
            continue
        m = float(r["montant"])
        n = nat[i]
        n["qualite"] = r["qualite"]
        n["total_eur"] += m
        n[f"{cat}_eur"] += m
        n["par_type"][r["type_co"]] = n["par_type"].get(r["type_co"], 0.0) + m
        n["par_nature"][r["code_var"]] = n["par_nature"].get(r["code_var"], 0.0) + m
        g = regions.setdefault(r["code_reg"], {"code": r["code_reg"], "nom": r["lib_reg"], "groupe": r["groupe_reg"],
                                               "rt_eur": [None] * len(annees), "esve_eur": [None] * len(annees),
                                               "par_type": {}})
        g[f"{cat}_eur"][i] = (g[f"{cat}_eur"][i] or 0.0) + m
        t = g["par_type"].setdefault(r["type_co"], [None] * len(annees))
        t[i] = (t[i] or 0.0) + m
    for n in nat:
        for k in ("total_eur", "rt_eur", "esve_eur"):
            n[k] = arrondi(n[k])
        n["par_type"] = {k: arrondi(v) for k, v in sorted(n["par_type"].items())}
        n["par_nature"] = {k: arrondi(v) for k, v in sorted(n["par_nature"].items())}
    liste = []
    for g in sorted(regions.values(), key=lambda g: g["code"]):
        liste.append({"code": g["code"], "nom": g["nom"], "groupe": g["groupe"],
                      "rt_eur": [arrondi(v) for v in g["rt_eur"]], "esve_eur": [arrondi(v) for v in g["esve_eur"]],
                      "par_type": {k: [arrondi(v) for v in vals] for k, vals in sorted(g["par_type"].items())}})
    s = SOURCES["budget_collectivites"]
    return {
        "millesime": "Budgets des collectivités " + s["millesime"],
        "source": f"{s['titre']} ({s['page']})", "unite": "euros", "licence": s["licence"],
        "date_sources": date_sources(DOMAINE), "annees": annees,
        "qualite": {str(a): qualite[a] for a in annees},
        "categories": {"rt": "Recherche et transfert de technologie", "esve": "Enseignement supérieur et vie étudiante"},
        "types_collectivite": dict(sorted(types.items())),
        "natures": sorted(natures.values(), key=lambda n: n["code"]),
        "national": nat, "regions": liste,
        "ordre": {"cles": ["code"], "regle": "régions par code officiel croissant ; années croissantes"},
        "lignes_sans_montant": sans_montant,
        "note": "Montants déclarés par les collectivités à l'enquête du SIES, par région de la collectivité. Une "
                "valeur null signale l'absence de ligne à la source pour la région et l'année, pas un montant nul. "
                "Les années semi-définitives et prévisionnelles sont révisées par le producteur.",
    }


# --- Étudiants et coût par étudiant ----------------------------------------------------------------------------------

FORMULE_COUT = ("cout_par_etudiant_eur = budget_esve_eur / etudiants ; budget_esve_eur : dépenses des collectivités "
                "de la région pour l'enseignement supérieur et la vie étudiante, année N (collectivites_esr.json) ; "
                "etudiants : inscriptions principales hors doubles inscriptions en CPGE, année universitaire N-1/N "
                "(colonne « annee » de la source), dans les établissements publics sous tutelle du ministère dont "
                "le siège est dans la région, hors établissements-composantes déjà comptés dans leur établissement")


def _code(v, prefixe: str):
    """Code officiel sans le préfixe du référentiel du ministère (« R11 » -> « 11 », « D093 » -> « 093 »)."""
    v = (v or "").strip()
    return v[len(prefixe):] if v.startswith(prefixe) else (v or None)


# Régions d'outre-mer : code Insee de la région (effectifs) -> code publié dans les budgets des collectivités.
REGIONS_OUTRE_MER = {"01": "971", "02": "972", "03": "973", "04": "974", "06": "976"}


def construire_etudiants(lignes: list[dict], collectivites: dict, rattachement: dict[str, dict]) -> dict:
    annees = sorted({_annee(r["annee"]) for r in lignes if _annee(r["annee"])})
    rang = {a: i for i, a in enumerate(annees)}
    libelle_annee = {}
    etab: dict = {}
    reg, dep, com = {}, {}, {}
    for r in sorted(lignes, key=lambda r: (r["annee"] or "", r["etablissement_id_paysage"] or "")):
        a = _annee(r["annee"])
        if a is None:
            continue
        i = rang[a]
        libelle_annee[a] = r["annee_universitaire"]
        double = "doubles comptes" in (r["attention"] or "")
        code_dep = _code(r["etablissement_id_departement"], "D")
        code_dep = code_dep[1:] if code_dep and len(code_dep) == 3 and code_dep[0] == "0" else code_dep
        code_reg = _code(r["etablissement_id_region"], "R")
        e = etab.setdefault(r["etablissement_id_paysage"], {"eff": [None] * len(annees), "sans": [None] * len(annees),
                                                            "double": [None] * len(annees)})
        e.update({"id": r["etablissement_id_paysage"], "uai": sorted(u for u in (r["etablissement_id_uai"] or "").split(",") if u),
                  "nom": r["etablissement_lib"], "type": r["etablissement_type"],
                  "typologie": r["etablissement_typologie"], "code_commune": r["etablissement_code_commune"],
                  "commune": r["etablissement_commune"], "departement": code_dep,
                  "academie": r["etablissement_academie"], "region": code_reg})   # dernière année connue
        e["eff"][i], e["sans"][i], e["double"][i] = r["effectif"], r["effectif_sans_cpge"], double
        if double:
            continue
        for registre, k, nom in ((reg, code_reg, r["etablissement_region"]), (dep, code_dep, r["etablissement_departement"]),
                                 (com, r["etablissement_code_commune"], r["etablissement_commune"])):
            g = registre.setdefault(k, {"nom": nom, "eff": [None] * len(annees), "etabs": [0] * len(annees)})
            g["nom"] = nom or g["nom"]
            if r["effectif_sans_cpge"] is not None:
                g["eff"][i] = (g["eff"][i] or 0) + r["effectif_sans_cpge"]
            g["etabs"][i] += 1
            if registre is com:
                g["departement"] = code_dep
    lignes_etab = []
    for e in sorted(etab.values(), key=lambda e: (norme(e["nom"]), e["id"])):
        r = rattachement.get(e["nom"]) or {}
        lignes_etab.append([e["id"], e["uai"], r.get("siren"), r.get("categorie_juridique"), e["nom"], e["type"],
                            e["typologie"], e["code_commune"], e["commune"], e["departement"], e["academie"],
                            e["region"], any(d for d in e["double"] if d), e["eff"], e["sans"]])

    def groupes(registre, cle):
        out = []
        for k, g in sorted(registre.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
            x = {cle: k, "nom": g["nom"], "etablissements": g["etabs"], "etudiants": g["eff"]}
            if cle == "code_commune":
                x["departement"] = g.get("departement")
            out.append(x)
        return out

    # Coût par étudiant, calculé : budget ES&VE des collectivités de la région / étudiants de la région.
    c_annees = collectivites["annees"]
    qualite = collectivites["qualite"]
    cout_regions = []
    codes_budget = {g["code"]: g for g in collectivites["regions"]}
    reg_budget = {REGIONS_OUTRE_MER.get(k, k): e for k, e in reg.items() if k}
    for code in sorted(set(codes_budget) | set(reg_budget)):
        g, e = codes_budget.get(code), reg_budget.get(code)
        valeurs = []
        for a in sorted(set(c_annees) & set(annees)):
            budget = g["esve_eur"][c_annees.index(a)] if g else None
            n = e["eff"][rang[a]] if e else None
            valeurs.append({"annee": a, "qualite_budget": qualite[str(a)], "budget_esve_eur": budget, "etudiants": n,
                            "cout_par_etudiant_eur": round(budget / n, 2) if budget is not None and n else None,
                            "statut": STATUT_CALCULE if budget is not None and n else None})
        cout_regions.append({"code": code, "nom": (g or {}).get("nom") or (e or {}).get("nom"), "valeurs": valeurs})
    national = []
    for a in sorted(set(c_annees) & set(annees)):
        budget = collectivites["national"][c_annees.index(a)]["esve_eur"]
        n = sum(g["eff"][rang[a]] or 0 for g in reg.values())
        national.append({"annee": a, "qualite_budget": qualite[str(a)], "budget_esve_eur": budget, "etudiants": n,
                         "cout_par_etudiant_eur": round(budget / n, 2) if n else None,
                         "statut": STATUT_CALCULE if n else None})
    s = SOURCES["effectifs"]
    return {
        "millesime": "Effectifs étudiants " + s["millesime"] + " ; coût par étudiant calculé, 2007 à 2025",
        "source": f"{s['titre']} ({s['page']}) ; {SOURCES['budget_collectivites']['titre']} "
                  f"({SOURCES['budget_collectivites']['page']})",
        "unite": "étudiants inscrits (inscriptions principales) ; euros pour le coût par étudiant",
        "licence": s["licence"], "date_sources": date_sources(DOMAINE),
        "annees": annees, "annees_universitaires": [libelle_annee[a] for a in annees],
        "colonnes": ["id_paysage", "uai", "siren", "categorie_juridique", "nom", "type", "typologie", "code_commune",
                     "commune",
                     "departement", "academie", "region", "double_compte", "etudiants", "etudiants_hors_cpge"],
        "etablissements": lignes_etab,
        "ordre": {"cles": ["nom", "id_paysage"], "regle": "ordre alphabétique du nom, puis identifiant"},
        "par_commune": groupes(com, "code_commune"), "par_departement": groupes(dep, "departement"),
        "par_region": groupes(reg, "region"),
        "regle_personnes": "Le jeu ne contient que des établissements publics sous tutelle du ministère (personnes "
                           "morales de droit public), nommés avec leur identifiant UAI ; siren et "
                           "categorie_juridique : unité légale du stock SIRENE dont la dénomination est identique "
                           "au nom publié (une seule personne morale), sinon null. Aucune donnée individuelle.",
        "note": "annee = seconde année civile de l'année universitaire (2025 pour 2024-25), comme dans la source. "
                "etudiants : y compris doubles inscriptions en CPGE ; etudiants_hors_cpge : hors ces doubles "
                "inscriptions. double_compte : établissement-composante dont les étudiants sont déjà comptés dans "
                "son établissement de rattachement pour au moins une année ; ces lignes sont exclues de "
                "par_commune, par_departement et par_region. Commune, département et région : siège de "
                "l'établissement, pas le lieu d'études.",
        "cout_par_etudiant": {
            "statut": STATUT_CALCULE, "formule": FORMULE_COUT,
            "producteur": "calcul du site à partir de deux jeux du ministère chargé de l'enseignement supérieur",
            "perimetre": "Numérateur : dépenses des régions, départements, communes et intercommunalités pour "
                         "l'enseignement supérieur et la vie étudiante (enquête du SIES). Dénominateur : étudiants "
                         "des établissements publics sous tutelle du ministère, comptés au siège de l'établissement.",
            "limites": [
                "Ce montant ne comprend pas les dépenses de l'État, des établissements eux-mêmes ni des ménages : "
                "ce n'est pas la dépense totale par étudiant.",
                "Le dénominateur ne compte ni les sections de techniciens supérieurs, ni les classes préparatoires "
                "des lycées, ni les établissements privés ou relevant d'autres ministères, que les collectivités "
                "peuvent aussi soutenir.",
                "Les étudiants sont comptés dans la région du siège de leur établissement, même s'ils étudient sur "
                "un site d'une autre région.",
                "Outre-mer : les effectifs portent le code Insee de la région (01, 02, 03, 04, 06), les budgets le "
                "code 971 à 976 ; le rapprochement est écrit dans correspondance_regions. Les collectivités "
                "d'outre-mer (code 00 des effectifs ; 987 et 988 des budgets) ne sont pas rapprochées.",
                "Budgets 2024 semi-définitifs et 2025 prévisionnels : valeurs révisées par le producteur.",
                "Valeur null quand le budget ou l'effectif manque pour la région et l'année.",
            ],
            "fichier": "education_recherche/collectivites_esr.json",
            "correspondance_regions": REGIONS_OUTRE_MER, "national": national, "regions": cout_regions,
            "ordre": {"cles": ["code", "annee"], "regle": "régions par code officiel croissant, années croissantes"}},
    }


# --- Index -----------------------------------------------------------------------------------------------------------

def construire_index(resume_anr: dict, lycees: dict[str, dict], collectivites: dict, etudiants: dict) -> dict:
    sources = []
    for cle, s in SOURCES.items():
        sources.append({"id": cle, "titre": s["titre"], "producteur": s["producteur"], "page": s["page"],
                        "licence": s["licence"], "millesime": s["millesime"], "verdict": s["verdict"],
                        "catalogue": s["catalogue"]})
    odbl = [{"source": cle, "producteur": s["producteur"], "page": s["page"], "licence": ODBL, "url_licence": URL_ODBL}
            for cle, s in SOURCES.items() if s["licence"] == ODBL]
    dern = collectivites["national"][-1]
    cout = etudiants["cout_par_etudiant"]["national"]
    totaux_lycees = {code: {"region": d["region"]["nom"], "annees": d["annees"], "total_eur": d["total_eur"],
                            "nommes": d["nommes"], "non_nommes": {"nombre": d["non_nommes"]["nombre"],
                                                                 "montant_eur": d["non_nommes"]["montant_eur"],
                                                                 "part_pct": d["non_nommes"]["part_pct"]},
                            "nature_des_montants": d["nature_des_montants"],
                            "fichier": f"{DOMAINE}/lycees/{code}.json"} for code, d in sorted(lycees.items())}
    return {
        "millesime": "ANR 2005-2009 et programmes d'investissements d'avenir 2006-2026 ; lycées : Île-de-France "
                     "2021-2023, Centre-Val de Loire 2017-2025, Pays de la Loire 2017-2020 ; budgets des "
                     "collectivités 2006-2025 ; effectifs étudiants 2006-07 à 2024-25",
        "source": " ; ".join(f"{s['producteur']} ({s['page']})" for s in SOURCES.values()),
        "unite": "euros, sauf effectifs (étudiants inscrits)", "date_sources": date_sources(DOMAINE),
        "fichiers": {"anr_etablissements": f"{DOMAINE}/anr_etablissements.json",
                     "anr_projets": f"{DOMAINE}/anr_projets.json",
                     "lycees": {code: f"{DOMAINE}/lycees/{code}.json" for code in sorted(lycees)},
                     "collectivites_esr": f"{DOMAINE}/collectivites_esr.json",
                     "etudiants": f"{DOMAINE}/etudiants.json"},
        "sorties": {
            "par_etablissement": ["anr_etablissements.json (SIREN)", "lycees/<région>.json (UAI, SIREN)",
                                  "etudiants.json (UAI)"],
            "par_commune_et_departement": ["lycees/<région>.json (par_commune, par_departement)",
                                           "etudiants.json (par_commune, par_departement, par_region)"],
            "par_annee": ["anr_projets.json", "lycees/<région>.json (par_annee)", "collectivites_esr.json",
                          "etudiants.json"]},
        "sources": sources,
        "licences": {
            "odbl": odbl,
            "note": "Les fichiers anr_etablissements.json, anr_projets.json, lycees/24.json et lycees/52.json "
                    "dérivent de bases publiées sous ODbL 1.0 : mention du producteur, et partage à l'identique de "
                    "toute base dérivée. Les autres fichiers dérivent de jeux sous Licence Ouverte 2.0. index.json "
                    "cite les deux ensembles et suit la licence ODbL."},
        "totaux": {
            "note": "Un total par source ; aucune somme entre sources (champs, années et natures de montants "
                    "différents).",
            "anr_pia_france2030": resume_anr["pia"], "anr_2005_2009": resume_anr["anr_2005_2009"],
            "lycees": totaux_lycees,
            "collectivites_esr": {"annee": dern["annee"], "qualite": dern["qualite"], "total_eur": dern["total_eur"],
                                  "rt_eur": dern["rt_eur"], "esve_eur": dern["esve_eur"]},
            "etudiants": {"annee": etudiants["annees"][-1],
                          "annee_universitaire": etudiants["annees_universitaires"][-1],
                          "etudiants_hors_cpge": cout[-1]["etudiants"] if cout else None}},
        "cout_par_etudiant": {"statut": STATUT_CALCULE, "formule": FORMULE_COUT,
                              "fichier": f"{DOMAINE}/etudiants.json", "national": cout},
        "ecarts": resume_anr["ecarts"],
        "liens": [dict(resume_anr["lien"], vue="beneficiaires_france2030",
                       lecture="France 2030 par bénéficiaire, opérateur ANR : fichier déjà publié, relié et non "
                               "recopié ; ses montants ne s'ajoutent pas à ceux de l'ANR")] if resume_anr["lien"] else [],
        "limites": [
            "ANR, programmes d'investissements d'avenir et France 2030 : l'aide est publiée par projet ; aucun "
            "montant par partenaire, aucune commune ni département codés.",
            "ANR : aucun SIREN publié ; les organismes sans équivalent unique dans le stock SIRENE restent agrégés "
            "par catégorie d'organisme.",
            "Lycées : trois régions publient un jeu exploitable ; les montants n'ont pas la même nature d'une région "
            "à l'autre (votés, versés, aides à des actions) et ne se comparent pas.",
            "Annuaire de l'éducation : établissements ouverts au jour de la collecte ; un établissement fermé depuis "
            "n'a ni commune ni SIRET.",
            "Aucun effectif d'élèves par lycée dans ces sources : aucun montant par élève n'est calculé.",
            "Le coût par étudiant est un calcul du site, à lire avec sa formule et ses limites (etudiants.json).",
        ],
        "sources_inaccessibles": [
            {"source": "ANR, aide par partenaire des programmes d'investissements d'avenir et de France 2030",
             "motif": "non publiée dans le jeu : seule l'aide par projet est disponible"},
            {"source": "ANR, projets financés depuis 2010 hors investissements d'avenir (fichiers « depuis 2010 »)",
             "motif": "hors des ressources demandées pour cet axe (fichier des projets de 142 Mo) : non repris"},
            {"source": "Subventions et dotations aux lycées des autres régions",
             "motif": "non recherchées pour cet axe : trois jeux régionaux désignés"},
            {"source": "Pays de la Loire, actions éducatives après la campagne 2020-2021",
             "motif": "le jeu publié s'arrête à la campagne 2020-2021"},
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }


# --- Production ------------------------------------------------------------------------------------------------------

def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    con = _duck()
    f2030_p = SITE / "beneficiaires" / "france2030.json"
    france2030 = json.loads(f2030_p.read_text(encoding="utf-8")) if f2030_p.exists() else None

    brut = lire_anr(con)
    eff = lire(con, "effectifs", BRUT / "edrech_effectifs_etudiants.parquet")
    noms = {p["Projet.Partenaire.Nom_organisme"] for p in brut["pia_partenaires"] + brut["a_partenaires"]
            if p["Projet.Partenaire.Nom_organisme"]}
    noms |= {r["etablissement_lib"] for r in eff if r["etablissement_lib"]}
    rattachement = apparier(noms)
    anr_etab, anr_proj, resume = construire_anr(brut, rattachement, france2030)

    annuaire = lire_annuaire(con)
    idf = lignes_idf(con)
    cvl, controles_cvl = lignes_cvl(con)
    pdl = lignes_pdl(con)
    sirens = {li["siren"] for li in idf if li["siren"]}
    sirens |= {annuaire[u]["siren"] for u in {li["uai"] for li in idf + cvl + pdl}
               if u in annuaire and annuaire[u].get("siren")}
    unites = unites_legales(sirens)
    lycees = {"11": construire_lycees("11", idf, annuaire, unites),
              "24": construire_lycees("24", cvl, annuaire, unites, controles=controles_cvl),
              "52": construire_lycees("52", pdl, annuaire, unites)}
    collectivites = construire_collectivites(lire(con, "budget_collectivites",
                                                  BRUT / "edrech_budget_collectivites_esr.parquet"))
    etudiants = construire_etudiants(eff, collectivites, rattachement)
    index = construire_index(resume, lycees, collectivites, etudiants)

    tailles = {"anr_etablissements.json": dump(sortie / "anr_etablissements.json", anr_etab),
               "anr_projets.json": dump(sortie / "anr_projets.json", anr_proj),
               "collectivites_esr.json": dump(sortie / "collectivites_esr.json", collectivites),
               "etudiants.json": dump(sortie / "etudiants.json", etudiants)}
    for code, doc in lycees.items():
        tailles[f"lycees/{code}.json"] = dump(sortie / "lycees" / f"{code}.json", doc)
    tailles["index.json"] = dump(sortie / "index.json", index)
    for nom, n in sorted(tailles.items()):
        print(f"{nom}: {n} octets")
    return index


def collecter() -> int:
    ids = [i for s in SOURCES.values() for i in s["catalogue"]]
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *ids])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter()
    if a.etape in ("produire", "tout"):
        produire(a.sortie)


if __name__ == "__main__":
    main()
