"""Aides aux entreprises : registre européen de transparence des aides d'État (TAM), lauréats de France 2030 et de
France Relance, prêts garantis par l'État (PGE). Montants par année, par dispositif, par secteur (NAF) et par région ;
écarts entre sources publiés, jamais additionnés ni tranchés.

Complète, sans les recopier :
  controle/aides_entreprises.json (pipeline/controle.py) : estimations publiées de l'ensemble des aides (HCSP, Sénat,
      IGF, Commission européenne...) et exonérations de cotisations Urssaf ;
  beneficiaires/france2030.json (pipeline/beneficiaires.py) : bénéficiaires nommés de France 2030 par opérateur.
Ce module ajoute : le registre TAM (aides individuelles que la France publie auprès de la Commission européenne),
France 2030 par année, région, secteur et stratégie, France Relance (lauréats industriels, montants agrégés par
mesure, filière, type d'entreprise et territoire), PGE par secteur, région et année.

Entrées (entrepôt data/lake, non versionné) :
  aides_entreprises/tam/fr_AAAA-MM.csv   registre TAM, France, une ligne par aide (collecte de ce module : pages
        publiques de la recherche, 100 résultats par page, une requête à la fois ; le nom du bénéficiaire n'est jamais
        enregistré, seul l'identifiant national l'est) ; tam/manifeste.json ; tam/secteurs_nace.json (nomenclature
        NACE de la recherche publique)
  aides_entreprises/aides_france2030_projets.csv         France 2030 (catalogue : aides_france2030_projets)
  beneficiaires/benef_plan_de_relance.parquet            France Relance, projets industriels lauréats
  aides_entreprises/aides_relance_*.parquet              France Relance, montants agrégés (data.economie.gouv.fr)
  aides_entreprises/aides_pge/, aides_pge_historique/    PGE (Etalab), situations au 1er janvier et au 31 décembre 2021
  _cache/recherche_entreprises.json (pipeline/sirene.py) : catégorie juridique (seules les personnes morales sont
        nommées) ; _cache/aides_entreprises_sirene.json : catégorie juridique, code et section NAF (API Recherche d'entreprises ; nom des seules personnes morales)
  site/data/local/geo/*.json (départements, régions), site/data/controle/aides_entreprises.json et
  site/data/beneficiaires/france2030.json (rapprochements, lecture seule)
Sorties (site/data/aides_entreprises/, chaque fichier < 5 Mo) :
  index.json, tam.json, france2030.json, france_relance.json, pge.json

Commandes :
  python pipeline/aides_entreprises.py collecter [--budget 1800] [--rafraichir]   # réseau : catalogue, TAM, SIRENE
  python pipeline/aides_entreprises.py produire [--sortie DOSSIER]                 # sans réseau

Règles : une personne morale (catégorie juridique 2xxx à 9xxx, sirene.personne_morale) peut être nommée ; tout autre
bénéficiaire (entrepreneur individuel, exploitant agricole, identifiant absent ou non vérifié) est agrégé. Une valeur
absente à la source reste null, jamais 0. Chaque source garde ses totaux : aucune somme entre le registre TAM, France
2030, France Relance et les PGE (périmètres et notions différents : élément d'aide, montant engagé, participation de
l'État, principal du prêt garanti). Un refus 401, 403 ou 429 est noté, jamais contourné. Dates par
pipeline/reproductible.py et par les manifestes de collecte : deux productions sur le même entrepôt sont identiques
octet pour octet.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "aides_entreprises"
TAM_DIR = BRUT / "tam"
TAM_MANIFESTE = TAM_DIR / "manifeste.json"
TAM_SECTEURS = TAM_DIR / "secteurs_nace.json"
CACHE_SIRENE = LAKE / "_cache" / "aides_entreprises_sirene.json"
STOCK_SIRENE = LAKE / "_cache" / "local" / "sirene_unite_legale.parquet"   # stock INSEE (pipeline/local.py)
SITE = ROOT / "site" / "data"
SORTIE = SITE / "aides_entreprises"
MAX_OCTETS = 5_000_000
UA = "ou-vont-mes-impots/0.1 (projet citoyen open source)"

API_ENTREPRISES = "https://recherche-entreprises.api.gouv.fr/search"
PAUSE_API_S = 0.34             # environ 3 appels par seconde (limite de l'API : 7), plusieurs modules la partagent
TAM_BASE = "https://webgate.ec.europa.eu/competition/transparency/public"
TAM_PAGE = f"{TAM_BASE}?lang=fr"
TAM_DEBUT = (2016, 1)          # le registre couvre les aides octroyées depuis le 1er juillet 2016
TAM_PAR_PAGE = 100
TAM_PAUSE_S = 1.0

# --- Sources -------------------------------------------------------------------------------------------------------

SOURCES = {
    "tam": {
        "titre": "Commission européenne, State Aid Transparency (Transparency Award Module), recherche publique, "
                 "France : aides individuelles octroyées publiées par les autorités françaises",
        "producteur": "Commission européenne (DG Concurrence), données saisies par les autorités françaises",
        "url": TAM_PAGE, "licence": "réutilisation autorisée avec mention de la source (décision 2011/833/UE)",
        "collecte": "pipeline/aides_entreprises.py collecter (pages publiques de 100 résultats, par mois d'octroi)",
    },
    "france2030": {
        "titre": "France 2030, projets lauréats (outil de gestion financière « Budget »), data.gouv.fr (Préfecture de "
                 "région Bretagne, geobretagne.fr, france2030_projets.csv)",
        "producteur": "Secrétariat général pour l'investissement (SGPI) et opérateurs", "catalogue":
            "aides_france2030_projets", "url": "https://www.data.gouv.fr/datasets/france-2030",
        "licence": "Licence Ouverte 2.0 (fiche data.gouv.fr : licence non précisée)",
        "chemin": BRUT / "aides_france2030_projets.csv",
    },
    "relance_laureats": {
        "titre": "Plan de relance, projets industriels : liste, géolocalisation et description synthétique des projets",
        "producteur": "Ministères économiques et financiers", "catalogue": "benef_plan_de_relance",
        "url": "https://www.data.gouv.fr/datasets/plan-de-relance-projets-industriels-liste-geolocalisation-et-"
               "description-synthetique-des-projets", "licence": "Licence Ouverte 2.0",
        "chemin": LAKE / "beneficiaires" / "benef_plan_de_relance.parquet",
    },
    "relance_mesure_filiere": {
        "titre": "Plan de relance, projets industriels : montant des investissements industriels et des aides de l'État "
                 "par mesure et par filière (annonces au 18 décembre)",
        "producteur": "Ministères économiques et financiers", "catalogue": "aides_relance_industrie_mesure_filiere",
        "url": "https://www.data.gouv.fr/datasets/plan-de-relance-projets-industriels-montant-des-investissements-"
               "industriels-et-des-aides-etat-par-mesure-et-par-filiere", "licence": "Licence Ouverte 2.0",
        "chemin": BRUT / "aides_relance_industrie_mesure_filiere.parquet",
    },
    "relance_region_departement": {
        "titre": "Plan de relance, projets industriels : montant des investissements industriels et des aides de l'État "
                 "par région et par département (annonces au 18 décembre)",
        "producteur": "Ministères économiques et financiers",
        "catalogue": "aides_relance_industrie_region_departement",
        "url": "https://www.data.gouv.fr/datasets/plan-de-relance-projets-industriels-montant-des-investissements-"
               "industriels-et-des-aides-etat-par-region-et-par-departement", "licence": "Licence Ouverte 2.0",
        "chemin": BRUT / "aides_relance_industrie_region_departement.parquet",
    },
    "relance_type_entreprise": {
        "titre": "Plan de relance, projets industriels : montant des investissements industriels et des aides de l'État "
                 "par mesure et par type d'entreprise (annonces au 18 décembre)",
        "producteur": "Ministères économiques et financiers", "catalogue": "aides_relance_industrie_type_entreprise",
        "url": "https://www.data.gouv.fr/datasets/plan-de-relance-projets-industriels-montant-des-investissements-"
               "industriels-et-des-aides-etat-par-mesure-et-par-type-dentreprise", "licence": "Licence Ouverte 2.0",
        "chemin": BRUT / "aides_relance_industrie_type_entreprise.parquet",
    },
    "relance_industrie_futur": {
        "titre": "Plan de relance, Industrie du futur : nombre de bénéficiaires et montants par département",
        "producteur": "France Relance", "catalogue": "aides_relance_industrie_du_futur",
        "url": "https://www.data.gouv.fr/datasets/plan-de-relance-industrie-du-futur-nombre-de-beneficiaires-et-"
               "montants-par-departement", "licence": "Licence Ouverte 2.0",
        "chemin": BRUT / "aides_relance_industrie_du_futur.parquet",
    },
    "relance_france_num": {
        "titre": "Plan de relance, chèque France Num : nombre de bénéficiaires et montants par département",
        "producteur": "France Relance", "catalogue": "aides_relance_cheque_france_num",
        "url": "https://www.data.gouv.fr/datasets/plan-de-relance-cheque-france-num-nombre-de-beneficiaires-et-"
               "montants-par-departement", "licence": "Licence Ouverte 2.0",
        "chemin": BRUT / "aides_relance_cheque_france_num.parquet",
    },
    "pge": {
        "titre": "Données relatives aux prêts garantis par l'État dans le cadre de l'épidémie de Covid-19 (tableau de "
                 "bord des aides aux entreprises, Etalab) : nombre et montant des PGE par région, département et "
                 "section NAF",
        "producteur": "Ministère de l'économie (données Bpifrance), Etalab", "catalogue": "aides_pge",
        "url": "https://www.data.gouv.fr/datasets/donnees-relatives-aux-prets-garantis-par-letat-dans-le-cadre-de-"
               "lepidemie-de-covid-19", "licence": "Licence Ouverte 2.0",
        "chemin": BRUT / "aides_pge",
    },
    "pge_historique": {
        "titre": "Historique des données du PGE (dépôt etalab/dashboard-aides-entreprises, published-data/pge/"
                 "pge-2021-01-01, version a62d6da)",
        "producteur": "Etalab", "catalogue": "aides_pge_historique",
        "url": "https://github.com/etalab/dashboard-aides-entreprises/tree/master/published-data/pge",
        "licence": "Licence Ouverte 2.0 (fiche data.gouv.fr)",
        "chemin": BRUT / "aides_pge_historique",
    },
}
CATALOGUE_IDS = sorted({s["catalogue"] for s in SOURCES.values() if s.get("catalogue")})


# --- Utilitaires ------------------------------------------------------------------------------------------------------

def propre(v) -> str:
    if v is None:
        return ""
    s = html.unescape(str(v))
    s = unicodedata.normalize("NFC", s).replace("\xa0", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def sans_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", propre(s).lower().replace("’", "'").replace("œ", "oe"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def ecrire_atomique(chemin: Path, texte: str) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=chemin.name + ".", suffix=".part", dir=chemin.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(texte)
        os.replace(tmp, chemin)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def dump(chemin: Path, obj) -> int:
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{chemin} dépasse 5 Mo ({n} octets) : découper")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte + "\n", encoding="utf-8")
    return n


def eur(x) -> float | None:
    return None if x is None else round(float(x), 2)


# --- Registre TAM : collecte (pages publiques de la recherche) ---------------------------------------------------------

# En-têtes français du tableau de résultats -> clés du fichier brut. « Nom du bénéficiaire » n'est jamais lu : un
# exploitant agricole ou un entrepreneur individuel y figure sous son nom ; les personnes morales sont nommées à partir
# du répertoire SIRENE (pipeline/sirene.py), jamais à partir de ce champ.
TAM_COLONNES = {
    "Pays": "pays", "Intitulé de la mesure d'aide": "mesure", "Numéro SA": "sa", "Numéro de référence": "ref",
    "ID national": "id_national", "Type de bénéficiaire": "type_beneficiaire", "Région": "region",
    "Secteur (NACE)": "secteur", "Instrument d'aide": "instrument", "Objectif de l’aide": "objectif",
    "Montant nominal, exprimé en montant total": "montant_nominal",
    "Élément d'aide, exprimé en montant total": "element_aide", "Date d'octroi": "date_octroi",
    "Nom de l'autorité chargée de l'octroi de l'aide": "autorite", "Entité en charge": "entite",
    "Intermédiaires financiers": "intermediaires", "Date de publication": "date_publication",
    "Benéficiaire dans un autre État membre": "autre_etat_membre", "Pays tiers hors UE": "pays_tiers",
}
TAM_CHAMPS = ["ref", "sa", "mesure", "type_id", "id_national", "type_beneficiaire", "region", "secteur", "instrument",
              "objectif", "montant_nominal", "element_aide", "date_octroi", "autorite", "entite", "intermediaires",
              "date_publication", "autre_etat_membre", "pays_tiers"]
NON_LU = {"Nom du bénéficiaire"}


class Refus(RuntimeError):
    """Refus d'accès (401, 403, 429) : la collecte s'arrête, rien n'est contourné."""


def _texte_cellule(td) -> str:
    for span in td.xpath(".//span[contains(@class,'translationTooltip')]"):
        span.drop_tree()
    return propre(td.text_content())


def lire_page_tam(texte: str) -> tuple[list[dict], int | None]:
    """Lignes du tableau de résultats (valeur complète lue dans l'attribut title quand la cellule est tronquée) et
    dernier décalage annoncé par la pagination (None : une seule page)."""
    from lxml.html import fromstring
    arbre = fromstring(texte)
    entetes = [propre(th.text_content()) for th in arbre.xpath("//table[@id='resultsTable']/thead/tr/th")]
    inconnus = [e for e in entetes if e not in TAM_COLONNES and e not in NON_LU]
    if inconnus:
        raise RuntimeError(f"TAM : colonnes inattendues {inconnus}")
    lignes = []
    for tr in arbre.xpath("//table[@id='resultsTable']/tbody/tr"):
        x = {}
        for entete, td in zip(entetes, tr.xpath("./td")):
            cle = TAM_COLONNES.get(entete)
            if cle is None:
                continue
            titre = propre(td.get("title"))
            if cle == "id_national":
                x["type_id"] = titre or None
                x["id_national"] = _texte_cellule(td) or None
                continue
            valeur = titre if titre else _texte_cellule(td)
            if cle in ("montant_nominal", "element_aide"):
                valeur = valeur or _texte_cellule(td)
            x[cle] = valeur or None
        if x.get("ref"):
            lignes.append(x)
    decalages = [int(d) for d in re.findall(r"offset=(\d+)&(?:amp;)?max=\d+", texte)]
    return lignes, (max(decalages) if decalages else None)


class SessionTam:
    """Session de la recherche publique : cookie de répartition de charge, jeton CSRF du formulaire, pays France."""

    def __init__(self, pause: float = TAM_PAUSE_S):
        import requests
        self.requests = requests
        self.pause = pause
        self.dernier = 0.0
        self.s = None
        self.jeton = None
        self.requetes = 0

    def _attendre(self):
        reste = self.pause - (time.monotonic() - self.dernier)
        if reste > 0:
            time.sleep(reste)
        self.dernier = time.monotonic()

    def _cookie(self, r):
        for c in r.raw.headers.getlist("Set-Cookie") if hasattr(r.raw.headers, "getlist") else []:
            m = re.match(r"LB_TRANSPARENCY=([^;]+)", c)
            if m:   # attribut domain vide refusé par requests : posé tel que le navigateur le garde
                self.s.cookies.set("LB_TRANSPARENCY", m.group(1), domain="webgate.ec.europa.eu",
                                   path="/competition/transparency")

    def _requete(self, methode: str, url: str, **kw):
        derniere = None
        for essai in range(5):
            self._attendre()
            try:
                r = self.s.request(methode, url, timeout=(30, 180), **kw)
            except (self.requests.ConnectionError, self.requests.Timeout) as exc:
                derniere = f"{type(exc).__name__}: {str(exc)[:160]}"
                time.sleep(10 * (essai + 1))
                continue
            self.requetes += 1
            self._cookie(r)
            if r.status_code in (401, 403, 429, 451):
                raise Refus(f"HTTP {r.status_code} sur {url} : accès refusé, non contourné")
            if r.status_code >= 500:
                derniere = f"HTTP {r.status_code}"
                time.sleep(20 * (essai + 1))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code} sur {url}")
            if "currently unable to handle the request" in r.text:
                derniere = "serveur indisponible (page d'attente)"
                time.sleep(30 * (essai + 1))
                continue
            return r
        raise RuntimeError(f"{url} injoignable après 5 essais : {derniere}")

    def ouvrir(self):
        self.s = self.requests.Session()
        self.s.headers["User-Agent"] = UA
        r = self._requete("GET", TAM_BASE, params={"lang": "fr"})
        jeton = re.search(r'name="CSRFTOKEN" value="([^"]+)"', r.text)
        if not jeton:
            raise RuntimeError("TAM : formulaire de recherche sans jeton (page modifiée)")
        r = self._requete("POST", f"{TAM_BASE}/search", data=[
            ("CSRFTOKEN", jeton.group(1)), ("resetSearch", "true"), ("_countries", ""), ("countries", "CountryFRA")])
        jeton = re.search(r'name="CSRFTOKEN" value="([^"]+)"', r.text)
        if not jeton or "[CountryFRA]" not in r.text:
            raise RuntimeError("TAM : critère pays non retenu par le formulaire (page modifiée)")
        self.jeton = jeton.group(1)

    def page(self, debut: date, fin: date, decalage: int) -> tuple[list[dict], int | None]:
        if self.s is None:
            self.ouvrir()
        donnees = {"CSRFTOKEN": self.jeton, "resetSearch": "false", "currency": "EUR",
                   "dateGrantedFrom": debut.strftime("%d/%m/%Y"), "dateGrantedTo": fin.strftime("%d/%m/%Y"),
                   "offset": decalage, "max": TAM_PAR_PAGE}
        for _ in range(3):
            r = self._requete("POST", f"{TAM_BASE}/search/results?sort=serverReference&order=asc", data=donnees)
            jeton = re.search(r'name="CSRFTOKEN" value="([^"]+)"', r.text)
            if jeton:
                self.jeton = jeton.group(1)
            if 'id="resultsTable"' in r.text:
                return lire_page_tam(r.text)
            if "Aucun résultat trouvé" in r.text or "No results found" in r.text:
                return [], None
            self.ouvrir()          # session expirée (page d'accueil renvoyée) : nouvelle session, même critère
            donnees["CSRFTOKEN"] = self.jeton
        raise RuntimeError("TAM : session non rétablie après trois tentatives")


def _mois(debut: tuple[int, int], fin: tuple[int, int]):
    a, m = debut
    while (a, m) <= fin:
        yield a, m
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)


def _fin_mois(a: int, m: int) -> date:
    from calendar import monthrange
    return date(a, m, monthrange(a, m)[1])


def lire_manifeste_tam() -> dict:
    try:
        return json.loads(TAM_MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"mois": {}}


def collecter_mois(session: SessionTam, a: int, m: int) -> dict:
    """Toutes les pages d'un mois d'octroi ; le fichier du mois n'est écrit qu'une fois complet."""
    debut, fin = date(a, m, 1), _fin_mois(a, m)
    lignes, vus, decalage, dernier = [], set(), 0, None
    while True:
        page, d = session.page(debut, fin, decalage)
        if decalage == 0:
            dernier = d if d is not None else 0
        for x in page:
            if x["ref"] in vus:
                continue
            octroi = x.get("date_octroi") or ""
            if not re.fullmatch(rf"\d\d/{m:02d}/{a}", octroi):
                raise RuntimeError(f"TAM {a}-{m:02d} : date d'octroi hors du mois demandé ({octroi})")
            vus.add(x["ref"])
            lignes.append(x)
        if len(page) < TAM_PAR_PAGE or decalage >= (dernier or 0):
            break
        decalage += TAM_PAR_PAGE
    if dernier and len(lignes) <= dernier:
        raise RuntimeError(f"TAM {a}-{m:02d} : {len(lignes)} lignes lues, pagination annoncée jusqu'à {dernier}")
    tampon = io.StringIO()
    w = csv.DictWriter(tampon, fieldnames=TAM_CHAMPS, lineterminator="\n")
    w.writeheader()
    for x in sorted(lignes, key=lambda y: y["ref"]):
        w.writerow({k: x.get(k) for k in TAM_CHAMPS})
    texte = tampon.getvalue()
    ecrire_atomique(TAM_DIR / f"fr_{a}-{m:02d}.csv", texte)
    return {"lignes": len(lignes), "sha256": hashlib.sha256(texte.encode("utf-8")).hexdigest(),
            "collecte_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def collecter_secteurs(session: SessionTam) -> None:
    if session.s is None:
        session.ouvrir()
    r = session._requete("GET", f"{TAM_BASE}/sectors", params={"lang": "fr"})
    d = r.json()
    if not isinstance(d, dict) or len(d) < 500:
        raise RuntimeError("TAM : nomenclature des secteurs inattendue")
    ecrire_atomique(TAM_SECTEURS, json.dumps(d, ensure_ascii=False, sort_keys=True, indent=0) + "\n")


def a_rafraichir(info: dict | None, a: int, m: int, aujourd_hui: date, rafraichir: bool) -> bool:
    """Mois absent, ou (avec --rafraichir) mois récent collecté depuis longtemps : les autorités publient jusqu'à un an
    après l'octroi. Six derniers mois : relus après 6 jours ; mois 7 à 18 : après 30 jours."""
    if not info or not (TAM_DIR / f"fr_{a}-{m:02d}.csv").exists():
        return True
    if not rafraichir:
        return False
    age_mois = (aujourd_hui.year - a) * 12 + aujourd_hui.month - m
    if age_mois > 18:
        return False
    collecte = datetime.fromisoformat(info["collecte_le"]).date()
    return (aujourd_hui - collecte).days >= (6 if age_mois <= 6 else 30)


def collecter_tam(budget_s: float, rafraichir: bool = False, pause: float = TAM_PAUSE_S) -> dict:
    debut_chrono = time.monotonic()
    man = lire_manifeste_tam()
    man.setdefault("mois", {})
    man["source"] = TAM_PAGE
    aujourd_hui = datetime.now(timezone.utc).date()
    session = SessionTam(pause)
    bilan = {"mois_collectes": 0, "lignes": 0, "refus": None, "erreurs": []}
    try:
        if not TAM_SECTEURS.exists():
            collecter_secteurs(session)
        for a, m in _mois(TAM_DEBUT, (aujourd_hui.year, aujourd_hui.month)):
            cle = f"{a}-{m:02d}"
            if not a_rafraichir(man["mois"].get(cle), a, m, aujourd_hui, rafraichir):
                continue
            if time.monotonic() - debut_chrono > budget_s:
                bilan["reporte"] = f"budget de {int(budget_s)} s épuisé avant {cle}"
                break
            try:
                info = collecter_mois(session, a, m)
            except Refus:
                raise
            except RuntimeError as exc:
                bilan["erreurs"].append(f"{cle} : {exc}"[:300])
                if len(bilan["erreurs"]) >= 5:
                    bilan["arret"] = "cinq mois en erreur : collecte arrêtée, reprise au prochain passage"
                    break
                continue
            man["mois"][cle] = info
            bilan["mois_collectes"] += 1
            bilan["lignes"] += info["lignes"]
            ecrire_atomique(TAM_MANIFESTE, json.dumps(man, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
            print(f"TAM {cle} : {info['lignes']} aides ({session.requetes} requêtes)", flush=True)
    except Refus as exc:
        bilan["refus"] = str(exc)
        man["dernier_refus"] = {"constat": str(exc), "le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        ecrire_atomique(TAM_MANIFESTE, json.dumps(man, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
        print(f"TAM : {exc}", flush=True)
    bilan["requetes"] = session.requetes
    return bilan


# --- Répertoire SIRENE : catégorie juridique et section NAF ------------------------------------------------------------

def charger_cache_sirene() -> dict:
    try:
        d = json.loads(CACHE_SIRENE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _sauver_cache_sirene(cache: dict) -> None:
    """Écriture sous verrou, fusionnée avec le disque (une collecte concurrente n'est jamais perdue), atomique."""
    import fcntl
    CACHE_SIRENE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_SIRENE.with_name(CACHE_SIRENE.name + ".lock"), "a") as verrou:
        fcntl.flock(verrou, fcntl.LOCK_EX)
        try:
            disque = charger_cache_sirene()
            fusion = {**disque, **{s: e for s, e in cache.items() if e.get("trouve") or s not in disque}}
            ecrire_atomique(CACHE_SIRENE, json.dumps(fusion, ensure_ascii=False, sort_keys=True))
        finally:
            fcntl.flock(verrou, fcntl.LOCK_UN)
    cache.update(fusion)


def _interroger_api(siren: str) -> dict | None:
    """Entrée de cache (jamais de nom pour une personne physique), ou None si l'API est injoignable."""
    import requests
    for essai in range(5):
        try:
            r = requests.get(API_ENTREPRISES, params={"q": siren, "page": 1, "per_page": 1},
                             headers={"User-Agent": UA}, timeout=30)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(2 ** essai)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** (essai + 1))
            continue
        if r.status_code >= 400:
            return {"trouve": False}
        res = [x for x in r.json().get("results", []) if x.get("siren") == siren]
        if not res:
            return {"trouve": False}
        x = res[0]
        cj = x.get("nature_juridique")
        e = {"trouve": True, "cj": cj, "naf": x.get("activite_principale"),
             "section": x.get("section_activite_principale")}
        if sirene.personne_morale(cj):
            e["nom"] = propre(x.get("nom_complet")) or None
        return e
    return None


def resoudre_sirene(sirens, budget_s: float, paralleles: int = 4) -> tuple[int, int]:
    """Complète le cache du module pour les SIREN donnés (dans l'ordre fourni). Renvoie (résolus, restants)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    cache = charger_cache_sirene()
    a_faire = [s for s in dict.fromkeys(sirens) if sirene.siren_valide(s) and s not in cache]
    debut, verrou, prochain, faits = time.monotonic(), threading.Lock(), [time.monotonic()], [0]

    def tache(s):
        if time.monotonic() - debut > budget_s:
            return
        with verrou:
            attente = prochain[0] - time.monotonic()
            prochain[0] = max(prochain[0], time.monotonic()) + PAUSE_API_S
        if attente > 0:
            time.sleep(attente)
        e = _interroger_api(s)
        if e is not None:
            with verrou:
                cache[s] = e
                faits[0] += 1
                if faits[0] % 250 == 0:
                    _sauver_cache_sirene(dict(cache))
                    print(f"  SIRENE : {faits[0]}/{len(a_faire)}", flush=True)

    with ThreadPoolExecutor(paralleles) as ex:
        list(ex.map(tache, a_faire))
    _sauver_cache_sirene(cache)
    return faits[0], len([s for s in a_faire if s not in cache])


def siren_de(v) -> str:
    """SIREN à 9 chiffres d'un identifiant publié (SIREN, SIRET, nombre écrit en flottant) ; chaîne vide sinon."""
    v = propre(v).replace(" ", "")
    if re.fullmatch(r"\d+\.0", v):
        v = v[:-2]
    if re.fullmatch(r"\d{14}", v):
        v = v[:9]
    if re.fullmatch(r"\d{1,9}", v) and v.strip("0"):
        v = v.zfill(9)
    return v if sirene.siren_valide(v) else ""


def extraire_stock_sirene(sirens) -> int:
    """Catégorie juridique, activité principale et dénomination (personnes morales seulement) lues dans le stock
    SIRENE des unités légales partagé par les modules (colonnes de nom et prénom jamais lues). Renvoie le nombre de
    SIREN ajoutés au cache du module."""
    import duckdb
    if not STOCK_SIRENE.exists():
        print(f"stock SIRENE absent ({STOCK_SIRENE.relative_to(ROOT)}) : API seulement", flush=True)
        return 0
    cache = charger_cache_sirene()
    manquants = sorted({s for s in sirens if sirene.siren_valide(s)} - {s for s, e in cache.items() if e.get("trouve")})
    if not manquants:
        return 0
    con = duckdb.connect()
    con.execute("create table q as select unnest(?::varchar[]) siren", [manquants])
    lignes = con.execute(f"""select u.siren, cast(u.categorieJuridiqueUniteLegale as varchar),
                                    u.activitePrincipaleUniteLegale, u.nomenclatureActivitePrincipaleUniteLegale,
                                    u.activitePrincipaleNAF25UniteLegale,
                                    coalesce(u.denominationUniteLegale, u.denominationUsuelle1UniteLegale,
                                             u.sigleUniteLegale)
                             from '{STOCK_SIRENE}' u join q using (siren) order by 1""").fetchall()
    for siren, cj, naf, nomenclature, naf25, denom in lignes:
        cj = str(cj or "").split(".")[0].zfill(4) if cj else None
        code = naf if (nomenclature or "") == "NAFRev2" else (naf25 or None)
        e = {"trouve": True, "cj": cj, "naf": code,
             "section": SECTION_DE_DIVISION.get(str(code or "")[:2]), "source": "stock SIRENE"}
        if sirene.personne_morale(cj):
            e["nom"] = propre(denom) or None
        cache[siren] = e
    _sauver_cache_sirene(cache)
    return len(lignes)


def sirens_a_resoudre(limite_tam: int | None = None) -> list[str]:
    """Ordre : plus gros bénéficiaires du registre TAM (classement nommé), lauréats de France Relance (nommés s'ils
    sont des personnes morales), bénéficiaires de France 2030 par montant décroissant (section NAF)."""
    import duckdb
    totaux = defaultdict(float)
    for x in lire_tam():
        s = siren_de(x["id_national"]) if x.get("type_id") == "SIREN Number" else ""
        if s:
            totaux[s] += montant_tam(x.get("element_aide"))[0] or 0
    sortie = [s for s, _ in sorted(totaux.items(), key=lambda kv: (-kv[1], kv[0]))[:limite_tam]]
    p = SOURCES["relance_laureats"]["chemin"]
    if p.exists():
        sortie += [siren_de(r[0]) for r in duckdb.sql(f"select siren from '{p}' order by siren").fetchall()]
    p = SOURCES["france2030"]["chemin"]
    if p.exists():
        sortie += [siren_de(r[0]) for r in duckdb.sql(
            f"select siren, sum(try_cast(montant_aide as double)) m from read_csv_auto('{p}', all_varchar=true) "
            f"group by 1 order by m desc nulls last, 1").fetchall()]
    return [s for s in dict.fromkeys(sortie) if s]


def collecter(budget_s: float = 1800, rafraichir: bool = False) -> int:
    """Catalogue (collecte/collecte.py), puis registre TAM, puis SIRENE ; chaque étape a sa part du budget."""
    debut = time.monotonic()
    code = subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *CATALOGUE_IDS,
                            "--timeout", "300"])
    bilan = collecter_tam(max(60.0, budget_s * 0.75 - (time.monotonic() - debut)), rafraichir)
    print(json.dumps({"tam": bilan}, ensure_ascii=False), flush=True)
    reste = max(30.0, budget_s - (time.monotonic() - debut))
    a_resoudre = sirens_a_resoudre()
    print(f"SIRENE : {extraire_stock_sirene(a_resoudre)} SIREN lus dans le stock", flush=True)
    faits, restants = resoudre_sirene(a_resoudre, reste)
    print(f"SIRENE : {faits} résolus, {restants} restants (relancer collecter pour continuer)", flush=True)
    if code not in (0, 1):
        print(f"collecte/collecte.py : code {code} (sources du catalogue gardées telles quelles)", flush=True)
    return 0


# --- Référentiels : régions, départements, sections NAF ----------------------------------------------------------------

SECTIONS_NAF = {
    "A": "Agriculture, sylviculture et pêche", "B": "Industries extractives", "C": "Industrie manufacturière",
    "D": "Production et distribution d'électricité, de gaz, de vapeur et d'air conditionné",
    "E": "Production et distribution d'eau ; assainissement, gestion des déchets et dépollution",
    "F": "Construction", "G": "Commerce ; réparation d'automobiles et de motocycles",
    "H": "Transports et entreposage", "I": "Hébergement et restauration", "J": "Information et communication",
    "K": "Activités financières et d'assurance", "L": "Activités immobilières",
    "M": "Activités spécialisées, scientifiques et techniques",
    "N": "Activités de services administratifs et de soutien", "O": "Administration publique",
    "P": "Enseignement", "Q": "Santé humaine et action sociale", "R": "Arts, spectacles et activités récréatives",
    "S": "Autres activités de services",
    "T": "Activités des ménages en tant qu'employeurs ; activités indifférenciées des ménages en tant que producteurs "
         "de biens et services pour usage propre", "U": "Activités extra-territoriales",
}
# Division (deux chiffres) -> section de la NAF rév. 2 (identique à la NACE rév. 2 au niveau des sections et divisions).
_BORNES = [("A", 1, 3), ("B", 5, 9), ("C", 10, 33), ("D", 35, 35), ("E", 36, 39), ("F", 41, 43), ("G", 45, 47),
           ("H", 49, 53), ("I", 55, 56), ("J", 58, 63), ("K", 64, 66), ("L", 68, 68), ("M", 69, 75), ("N", 77, 82),
           ("O", 84, 84), ("P", 85, 85), ("Q", 86, 88), ("R", 90, 93), ("S", 94, 96), ("T", 97, 98), ("U", 99, 99)]
SECTION_DE_DIVISION = {f"{d:02d}": s for s, a, b in _BORNES for d in range(a, b + 1)}
# Sections de la NACE rév. 2.1 (2025) sans division publiée -> section de la NAF rév. 2 de même contenu.
SECTIONS_NACE21 = {"A": "A", "B": "B", "C": "C", "D": "D", "E": "E", "F": "F", "G": "G", "H": "H", "I": "I", "J": "J",
                   "K": "J", "L": "K", "M": "L", "N": "M", "O": "N", "P": "O", "Q": "P", "R": "Q", "S": "R", "T": "S",
                   "U": "T", "V": "U"}
# Régions d'avant 2016 (libellés encore employés par le registre TAM) -> région actuelle (code COG).
ANCIENNES_REGIONS = {
    "alsace": "44", "lorraine": "44", "champagne ardenne": "44", "alsace champagne ardenne lorraine": "44",
    "aquitaine": "75", "limousin": "75", "poitou charentes": "75", "aquitaine limousin poitou charentes": "75",
    "auvergne": "84", "rhone alpes": "84", "bourgogne": "27", "franche comte": "27", "basse normandie": "28",
    "haute normandie": "28", "nord pas de calais": "32", "picardie": "32", "nord pas de calais picardie": "32",
    "languedoc roussillon": "76", "midi pyrenees": "76", "languedoc roussillon midi pyrenees": "76", "centre": "24",
    "reunion": "04", "provence alpes cote d azur": "93",
}
# Grandes zones statistiques (NUTS 1 de 2013 et 2016) : plusieurs régions, jamais réparties entre elles.
ZONES_PLURIREGIONALES = {"bassin parisien", "ouest", "sud ouest", "centre est", "est", "nord est", "mediterranee",
                         "sud est", "departements d outre mer", "regions ultraperipheriques francaises",
                         "ultraperipheriques francaises", "rup fr regions ultraperipheriques francaises",
                         "extra regio nuts 1", "extra regio nuts 2", "extra regio nuts 3"}
NIVEAUX_REGION = {
    "region": "région (libellé de la source : région actuelle)",
    "ancienne_region": "région d'avant 2016 rattachée à la région actuelle qui la contient",
    "departement": "département rattaché à sa région",
    "zone_pluriregionale": "grande zone statistique couvrant plusieurs régions (NUTS 1) : non répartie",
    "national": "France entière, sans localisation plus fine",
    "hors_france": "bénéficiaire établi dans un autre État membre (aide octroyée par une autorité française)",
    "non_rattache": "libellé sans correspondance établie : publié tel quel",
}


def referentiel_geo() -> tuple[dict, dict]:
    """(départements, régions) du code officiel géographique, lus dans site/data/local/geo (versionné)."""
    deps, regs = {}, {}
    for f in sorted((SITE / "local" / "geo").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        dep, reg = d.get("departement") or {}, d.get("region") or {}
        if dep.get("code") and reg.get("code"):
            deps[dep["code"]] = {"nom": dep["nom"], "region": reg["code"]}
            regs[reg["code"]] = reg["nom"]
    if len(deps) < 96 or len(regs) < 13:
        raise SystemExit("site/data/local/geo absent ou incomplet (départements et régions) : produire l'étape local")
    return deps, regs


class Territoires:
    """Rattachement d'un libellé de lieu (région, ancienne région, département, zone) à une région actuelle."""

    def __init__(self):
        self.deps, self.regs = referentiel_geo()
        self.par_nom = {}
        for code, nom in self.regs.items():
            self.par_nom[sans_accents(nom)] = ("region", code)
        self.par_nom["la reunion"] = ("region", "04")
        for nom, code in ANCIENNES_REGIONS.items():
            self.par_nom.setdefault(nom, ("ancienne_region", code))
        for code, d in self.deps.items():
            self.par_nom.setdefault(sans_accents(d["nom"]), ("departement", d["region"]))

    def region(self, libelle) -> tuple[str, str | None]:
        n = sans_accents(libelle)
        if not n:
            return "non_rattache", None
        if n == "france":
            return "national", None
        if n in ZONES_PLURIREGIONALES:
            return "zone_pluriregionale", None
        if n in self.par_nom:
            return self.par_nom[n]
        return "non_rattache", None

    def region_de_departement(self, code) -> str | None:
        c = propre(code)
        if re.fullmatch(r"\d+(\.0)?", c):
            c = str(int(float(c)))
            c = c.zfill(2) if len(c) < 3 else c
        return (self.deps.get(c) or {}).get("region")

    def nom(self, code: str | None) -> str | None:
        return self.regs.get(code) if code else None


def referentiel_nace() -> dict[str, tuple[str, str | None]]:
    """Libellé normalisé -> (section de la NAF rév. 2, division ou None), d'après la nomenclature de la recherche
    publique du registre, qui mêle la NACE rév. 2 (2008) et la NACE rév. 2.1 (2025). Une division garde son numéro
    d'une version à l'autre : la section NAF rév. 2 est celle de ce numéro ; un libellé de section seule de la
    version 2.1 est rattaché à la section de même contenu (SECTIONS_NACE21). Libellé présent dans les deux versions :
    la version 2008 l'emporte."""
    if not TAM_SECTEURS.exists():
        return {}
    candidats = {}
    for v in json.loads(TAM_SECTEURS.read_text(encoding="utf-8")).values():
        m = re.match(r"NACE Rev(2|2\.1) (?:2008|2025) - ([A-V])(?:\.(\d{2})(?:\.\d{1,2})?)? - (.+)$",
                     propre((v or {}).get("value")))
        if not m:
            continue
        version, lettre, division, lib = m.group(1), m.group(2), m.group(3), m.group(4)
        lib = sans_accents(re.sub(r"^SECTION [A-V]\s*[—-]\s*", "", lib, flags=re.I))
        if division:
            section = SECTION_DE_DIVISION.get(division)
        else:
            section = lettre if version == "2" else SECTIONS_NACE21.get(lettre)
        if not section:
            continue
        rang = (0 if version == "2" else 1, 0 if division is None else 1, division or "")
        if lib not in candidats or rang < candidats[lib][0]:
            candidats[lib] = (rang, (section, division))
    return {lib: v for lib, (_, v) in candidats.items()}


# --- Registre TAM : lecture et agrégats -------------------------------------------------------------------------------

def lire_tam():
    """Aides publiées (fichiers mensuels de l'entrepôt), dans l'ordre des mois puis des références."""
    for f in sorted(TAM_DIR.glob("fr_*.csv")):
        with f.open(encoding="utf-8", newline="") as fh:
            yield from csv.DictReader(fh)


def montant_tam(v) -> tuple[float | None, float | None, float | None]:
    """(montant, borne basse, borne haute) en euros. Fourchette publiée (« 500,001 à 1,000,000 EUR ») : montant None,
    bornes renseignées ; valeur absente ou illisible : (None, None, None)."""
    v = propre(v)
    nombre = r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)"
    m = re.fullmatch(nombre + r"\s*EUR", v)
    if m:
        x = float(m.group(1).replace(",", ""))
        return x, x, x
    m = re.fullmatch(nombre + r"\s*(?:à|-|to)\s*" + nombre + r"\s*EUR", v)
    if m:
        return None, float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
    m = re.fullmatch(r"(?:plus de|more than|>)\s*" + nombre + r"\s*EUR", v, re.I) or \
        re.fullmatch(nombre + r"\s*EUR\s*(?:ou plus|et plus|or more)", v, re.I) or \
        re.fullmatch(nombre + r"\s*(?:à|-|to)\s*EUR", v)
    if m:
        return None, float(m.group(1).replace(",", "")), None
    return None, None, None


def date_tam(v) -> str | None:
    m = re.fullmatch(r"(\d\d)/(\d\d)/(\d{4})", propre(v))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


TRANCHES = [(None, 100_000, "moins de 100 000 €"), (100_000, 500_000, "de 100 000 € à moins de 500 000 €"),
            (500_000, 1_000_000, "de 500 000 € à moins de 1 M€"), (1_000_000, 10_000_000, "de 1 M€ à moins de 10 M€"),
            (10_000_000, None, "10 M€ et plus")]


def tranche(x: float) -> str:
    for bas, haut, lib in TRANCHES:
        if (bas is None or x >= bas) and (haut is None or x < haut):
            return lib
    raise AssertionError(x)


class Agregat:
    """Compteurs d'un regroupement : aides, montant (élément d'aide publié), fourchettes, montants absents."""
    __slots__ = ("nombre", "montant", "avec_montant", "fourchettes", "basse", "haute", "haute_ouverte", "sans_montant",
                 "nominal", "avec_nominal")

    def __init__(self):
        self.nombre = self.avec_montant = self.fourchettes = self.haute_ouverte = self.sans_montant = 0
        self.avec_nominal = 0
        self.montant = self.basse = self.haute = self.nominal = 0.0

    def ajouter(self, montant, basse, haute, nominal=None):
        self.nombre += 1
        if montant is not None:
            self.avec_montant += 1
            self.montant += montant
        elif basse is not None:
            self.fourchettes += 1
            self.basse += basse
            if haute is None:
                self.haute_ouverte += 1
            else:
                self.haute += haute
        else:
            self.sans_montant += 1
        if nominal is not None:
            self.avec_nominal += 1
            self.nominal += nominal

    def sortie(self, nominal: bool = False) -> dict:
        x = {"aides": self.nombre, "element_aide_eur": eur(self.montant), "aides_avec_montant": self.avec_montant}
        if self.fourchettes:
            x["fourchettes"] = {"aides": self.fourchettes, "borne_basse_eur": eur(self.basse),
                                "borne_haute_eur": None if self.haute_ouverte else eur(self.haute)}
        if self.sans_montant:
            x["aides_sans_montant"] = self.sans_montant
        if nominal and self.avec_nominal:
            x["montant_nominal_eur"] = eur(self.nominal)
            x["aides_avec_montant_nominal"] = self.avec_nominal
        return x


def _texte_publiable(t, longueur: int = 400) -> str | None:
    """Texte saisi par une autorité (intitulé de mesure, nom d'autorité) : retiré s'il peut contenir un nom de
    personne (pipeline/local.py, objet_publiable) ; l'identifiant (numéro SA) reste publié."""
    import local
    return local.objet_publiable(t, longueur=longueur)


def classement(d: dict, cle_tri=lambda kv: (-kv[1].montant, kv[0])) -> list:
    return sorted(d.items(), key=cle_tri)


# --- Bénéficiaires nommés (personnes morales) et agrégés ---------------------------------------------------------------

NOTE_NON_VERIFIES = ("SIREN valide dont la catégorie juridique n'a pas encore été vérifiée dans le répertoire SIRENE : "
                     "agrégés, jamais nommés")


class Identites:
    """Catégorie juridique et nom (personnes morales seulement) : cache du module, puis cache partagé de sirene.py."""

    def __init__(self):
        self.module = charger_cache_sirene()
        self.partage = sirene.charger_cache()

    def entree(self, siren: str) -> dict | None:
        e = self.module.get(siren)
        if e and e.get("trouve"):
            return e
        p = self.partage.get(siren)
        if p and p.get("cj"):
            return {"trouve": True, "cj": p["cj"], "nom": p.get("nom")}
        return e or p

    def statut(self, siren: str, cj_source=None) -> tuple[str, str | None]:
        """('pm', cj) personne morale publiable ; ('pp', cj) personne physique ; ('ni', None) non identifiée ;
        ('nv', None) SIREN valide dont la catégorie n'est pas encore vérifiée."""
        if not sirene.siren_valide(siren):
            return "ni", None
        cj = propre(cj_source).split(".")[0] if cj_source not in (None, "") else ""
        if not sirene.CJ_RE.match(cj) or cj == "0000":
            e = self.entree(siren)
            if e is None:
                return "nv", None
            cj = propre(e.get("cj"))
        if sirene.personne_morale(cj):
            return "pm", cj
        if cj.startswith("1") or cj in sirene.CJ_PERSONNES_PHYSIQUES:
            return "pp", cj
        return "ni", None

    def nom(self, siren: str) -> str | None:
        e = self.entree(siren) or {}
        return propre(e.get("nom")) or None

    def section(self, siren: str) -> str | None:
        s = propre((self.module.get(siren) or {}).get("section"))
        return s if s in SECTIONS_NAF else None


class Groupe:
    """Groupe de bénéficiaires (commun.schema.json#/$defs/groupe_beneficiaires) : top nommé, autres, agrégés."""

    def __init__(self):
        self.total = 0.0
        self.pm = {}
        self.nv_montant, self.nv = 0.0, set()
        self.nv_par = defaultdict(float)
        self.exclus = {"montant_eur": 0.0, "lignes": 0, "dont_personnes_physiques_eur": 0.0,
                       "dont_sans_siren_eur": 0.0, "dont_categorie_inconnue_eur": 0.0}

    def ajouter(self, siren: str, st: str, cj: str | None, montant: float, extra: dict | None = None):
        self.total += montant
        if st == "pm":
            b = self.pm.setdefault(siren, {"categorie_juridique": cj, "montant": 0.0, "aides": 0, "annees": Counter()})
            b["montant"] += montant
            b["aides"] += 1
            for k, v in (extra or {}).items():
                b["annees"][k] += v
        elif st == "nv":
            self.nv_montant += montant
            self.nv.add(siren)
            self.nv_par[siren] += montant
        else:
            x = self.exclus
            x["montant_eur"] += montant
            x["lignes"] += 1
            cle = ("dont_sans_siren_eur" if not siren else "dont_personnes_physiques_eur" if st == "pp"
                   else "dont_categorie_inconnue_eur")
            x[cle] += montant

    def sortie(self, ident: Identites, top: int = 50) -> dict:
        tries = sorted(self.pm.items(), key=lambda kv: (-kv[1]["montant"], kv[0]))
        haut = []
        for s, b in tries[:top]:
            haut.append({"siren": s, "denomination": ident.nom(s) or f"SIREN {s}",
                         "categorie_juridique": b["categorie_juridique"], "montant_eur": eur(b["montant"]),
                         "aides": b["aides"],
                         "par_annee_eur": {str(a): eur(v) for a, v in sorted(b["annees"].items())}})
        reste = tries[top:]
        somme = sum(b["montant"] for _, b in tries) + self.nv_montant + self.exclus["montant_eur"]
        if abs(somme - self.total) > 1:
            raise SystemExit(f"conservation rompue : {somme} != {self.total}")
        seuil = tries[top - 1][1]["montant"] if len(tries) >= top else 0.0
        au_dessus = sorted(m for m in self.nv_par.values() if m >= seuil)
        verification = {"seuil_eur": eur(seuil), "non_verifies_au_dessus_du_seuil": len(au_dessus),
                        "montant_non_verifie_au_dessus_du_seuil_eur": eur(sum(au_dessus)),
                        "classement_complet": not au_dessus,
                        "note": "le classement nommé ne vaut que si aucun SIREN non vérifié n'a reçu au moins le "
                                "montant du dernier nommé (seuil) ; sinon relancer la collecte (répertoire SIRENE)"}
        return {"total_eur": eur(self.total), "top": haut, "verification_classement": verification,
                "autres_personnes_morales": {"nombre": len(reste), "montant_eur": eur(sum(b["montant"]
                                                                                          for _, b in reste))},
                "autres_non_verifies": {"nombre": len(self.nv), "montant_eur": eur(self.nv_montant),
                                        "note": NOTE_NON_VERIFIES},
                "exclus_personnes_physiques_ou_non_identifies": {k: (eur(v) if k != "lignes" else v)
                                                                 for k, v in self.exclus.items()}}


# --- Registre TAM : production -----------------------------------------------------------------------------------------

def manifeste_tam_lu() -> dict:
    man = lire_manifeste_tam()
    mois = man.get("mois", {})
    dates = sorted(v["collecte_le"][:10] for v in mois.values() if v.get("collecte_le"))
    return {"mois": len(mois), "premier_mois": min(mois) if mois else None, "dernier_mois": max(mois) if mois else None,
            "collecte_du": dates[0] if dates else None, "collecte_au": dates[-1] if dates else None,
            "dernier_refus": man.get("dernier_refus")}


def produire_tam(terr: Territoires, ident: Identites) -> dict:
    if not any(TAM_DIR.glob("fr_*.csv")):
        raise SystemExit("data/lake/aides_entreprises/tam absent : lancer `python pipeline/aides_entreprises.py "
                         "collecter`")
    nace = referentiel_nace()
    total = Agregat()
    par_annee, par_mesure, par_objectif, par_instrument = (defaultdict(Agregat) for _ in range(4))
    par_type, par_section, par_division, par_region, par_niveau = (defaultdict(Agregat) for _ in range(5))
    par_tranche, annee_section, annee_region, annee_tranche = (defaultdict(Agregat) for _ in range(4))
    titres, autorites_mesure, montants_mesure = {}, defaultdict(Counter), defaultdict(list)
    secteurs_non_rattaches, regions_non_rattachees, illisibles = Counter(), Counter(), Counter()
    publication_delai = []
    groupe = Groupe()
    vues = set()
    for x in lire_tam():
        if x["ref"] in vues:
            continue
        vues.add(x["ref"])
        octroi = date_tam(x.get("date_octroi"))
        annee = int(octroi[:4]) if octroi else None
        montant, basse, haute = montant_tam(x.get("element_aide"))
        nominal = montant_tam(x.get("montant_nominal"))[0]
        if montant is None and basse is None and propre(x.get("element_aide")):
            illisibles[propre(x.get("element_aide"))] += 1
        args = (montant, basse, haute)
        total.ajouter(*args, nominal)
        par_annee[annee].ajouter(*args, nominal)
        sa = propre(x.get("sa")) or "sans numéro"
        par_mesure[sa].ajouter(*args, nominal)
        if montant is not None:
            montants_mesure[sa].append((montant, x["ref"], annee))
        titres.setdefault(sa, Counter())[propre(x.get("mesure"))] += 1
        autorites_mesure[sa][propre(x.get("autorite"))] += 1
        par_objectif[propre(x.get("objectif")) or "non renseigné"].ajouter(*args)
        par_instrument[propre(x.get("instrument")) or "non renseigné"].ajouter(*args, nominal)
        par_type[propre(x.get("type_beneficiaire")) or "non renseigné"].ajouter(*args)
        section, division = nace.get(sans_accents(re.sub(r"^SECTION [A-V]\s*[—-]\s*", "", propre(x.get("secteur")),
                                                         flags=re.I)), (None, None))
        if not section and propre(x.get("secteur")):
            secteurs_non_rattaches[propre(x.get("secteur"))] += 1
        par_section[section or "non_rattache"].ajouter(*args)
        if division:
            par_division[(section, division)].ajouter(*args)
        niveau, region = terr.region(x.get("region"))
        if sans_accents(x.get("autre_etat_membre")) not in ("", "france"):
            niveau, region = "hors_france", None
        par_niveau[niveau].ajouter(*args)
        cle_region = region or niveau
        par_region[cle_region].ajouter(*args)
        if niveau == "non_rattache" and propre(x.get("region")):
            regions_non_rattachees[propre(x.get("region"))] += 1
        lib_tranche = tranche(montant) if montant is not None else ("fourchette publiée" if basse is not None
                                                                     else "montant non publié")
        par_tranche[lib_tranche].ajouter(*args)
        if annee is not None:
            annee_section[(annee, section or "non_rattache")].ajouter(*args)
            annee_region[(annee, cle_region)].ajouter(*args)
            annee_tranche[(annee, lib_tranche)].ajouter(*args)
        publie = date_tam(x.get("date_publication"))
        if octroi and publie:
            publication_delai.append((date.fromisoformat(publie) - date.fromisoformat(octroi)).days)
        siren = siren_de(x.get("id_national")) if x.get("type_id") == "SIREN Number" else ""
        st, cj = ident.statut(siren) if siren else ("ni", None)
        if montant is not None:
            groupe.ajouter(siren, st, cj, montant, {annee: montant} if annee else None)

    def liste(d: dict, cle: str, libelles=None, nominal=False) -> list:
        out = []
        for k, a in sorted(d.items(), key=lambda kv: (-kv[1].montant, str(kv[0]))):
            ligne = {cle: k, **({"libelle": libelles(k)} if libelles else {}), **a.sortie(nominal)}
            out.append(ligne)
        return out

    mesures = []
    for sa, a in sorted(par_mesure.items(), key=lambda kv: (-kv[1].montant, kv[0])):
        titre = titres[sa].most_common(1)[0][0] if titres[sa] else ""
        mesures.append({"sa": sa, "titre": _texte_publiable(titre), "titres_differents": len(titres[sa]),
                        "autorites": [_texte_publiable(n, 160) for n, _ in
                                      sorted(autorites_mesure[sa].items(), key=lambda kv: (-kv[1], kv[0]))[:3] if n],
                        **a.sortie(nominal=True)})
    regions = []
    for k, a in sorted(par_region.items(), key=lambda kv: (-kv[1].montant, kv[0])):
        est_code = k in terr.regs
        regions.append({"code": k if est_code else None, "nom": terr.nom(k) if est_code else NIVEAUX_REGION[k],
                        "rattachement": "region" if est_code else k, **a.sortie()})
    sections = []
    for s, a in sorted(par_section.items(), key=lambda kv: (-kv[1].montant, kv[0])):
        divisions = [{"division": d, **b.sortie()} for (s2, d), b in
                     sorted(par_division.items(), key=lambda kv: (-kv[1].montant, kv[0])) if s2 == s]
        sections.append({"section": None if s == "non_rattache" else s,
                         "libelle": SECTIONS_NAF.get(s, "secteur sans correspondance établie dans la nomenclature"),
                         **a.sortie(), "divisions": divisions})
    annees = sorted(a for a in par_annee if a is not None)

    def croiser(d: dict, codes: list) -> dict:
        return {str(an): {c: d[(an, c)].sortie() for c in codes if (an, c) in d} for an in annees}

    codes_sections = [s for s, _ in sorted(par_section.items(), key=lambda kv: kv[0])]
    codes_regions = [k for k, _ in sorted(par_region.items(), key=lambda kv: kv[0])]
    isoles = []
    for sa, lst in sorted(montants_mesure.items()):
        valeurs = sorted(m for m, _, _ in lst)
        mediane = valeurs[len(valeurs) // 2]
        for m, ref, an in sorted(lst, key=lambda v: (-v[0], v[1])):
            if m >= 100e6 and mediane > 0 and m >= 1000 * mediane:
                isoles.append({"ref": ref, "sa": sa, "annee": an, "element_aide_eur": eur(m),
                               "mediane_mesure_eur": eur(mediane), "aides_mesure": len(lst)})
    delais = sorted(publication_delai)
    man = manifeste_tam_lu()
    obj = {
        "millesime": f"Aides octroyées de {annees[0]} à {annees[-1]}, registre consulté du {man['collecte_du']} au "
                     f"{man['collecte_au']}" if annees else "registre vide",
        "source": f"{SOURCES['tam']['titre']} ({SOURCES['tam']['url']})",
        "unite": "euros (élément d'aide publié, exprimé en montant total)",
        "avertissement": "Le registre ne contient que les aides individuelles au-dessus des seuils de publication "
                         "européens : il ne mesure pas l'ensemble des aides aux entreprises. Les autorités publient "
                         "jusqu'à un an après l'octroi : les dernières années sont incomplètes.",
        "definitions": {
            "element_aide": "avantage accordé au bénéficiaire en équivalent-subvention, tel que publié : égal au "
                            "montant pour une subvention, inférieur au montant prêté ou garanti pour un prêt ou une "
                            "garantie",
            "montant_nominal": "montant du prêt, de la garantie ou de l'avance, quand l'autorité le publie",
            "fourchette": "aide publiée sous forme de tranche (avantages fiscaux notamment) : bornes additionnées à "
                          "part, jamais ajoutées à l'élément d'aide",
            "seuils": "la Commission européenne indique que, dans la plupart des cas, chaque aide individuelle de "
                      "plus de 100 000 € doit être publiée (obligation en vigueur depuis 2016) et que certaines "
                      "bases juridiques fixent d'autres seuils ; pour les aides exemptées de notification, le seuil "
                      "est passé de 500 000 € à 100 000 € avec la révision de 2023 du règlement général "
                      "d'exemption par catégorie. Le registre contient donc aussi des aides de moins de 100 000 €.",
        },
        "annees": annees,
        "total": total.sortie(nominal=True),
        "par_annee": {str(a): par_annee[a].sortie(nominal=True) for a in annees},
        "sans_date_octroi": par_annee[None].sortie() if None in par_annee else None,
        "par_mesure": mesures,
        "par_objectif": liste(par_objectif, "objectif"),
        "par_instrument": liste(par_instrument, "instrument", nominal=True),
        "par_type_beneficiaire": liste(par_type, "type"),
        "par_secteur": sections,
        "par_region": regions,
        "rattachement_regions": {k: {"definition": NIVEAUX_REGION[k], **par_niveau[k].sortie()}
                                 for k in NIVEAUX_REGION if k in par_niveau},
        "par_tranche": [{"tranche": lib, **par_tranche[lib].sortie()} for lib in
                        [t[2] for t in TRANCHES] + ["fourchette publiée", "montant non publié"] if lib in par_tranche],
        "croisements": {"annee_secteur": croiser(annee_section, codes_sections),
                        "annee_region": croiser(annee_region, codes_regions),
                        "annee_tranche": croiser(annee_tranche, [t[2] for t in TRANCHES]
                                                 + ["fourchette publiée", "montant non publié"])},
        "delai_publication_jours": {"mediane": delais[len(delais) // 2] if delais else None,
                                    "neuf_sur_dix_sous": delais[int(len(delais) * 0.9)] if delais else None,
                                    "aides": len(delais)},
        "non_rattaches": {
            "secteurs": [{"libelle": k, "aides": n} for k, n in sorted(secteurs_non_rattaches.items(),
                                                                         key=lambda kv: (-kv[1], kv[0]))],
            "regions": [{"libelle": k, "aides": n} for k, n in sorted(regions_non_rattachees.items(),
                                                                        key=lambda kv: (-kv[1], kv[0]))],
            "montants_illisibles": [{"valeur": k, "aides": n} for k, n in sorted(illisibles.items(),
                                                                                  key=lambda kv: (-kv[1], kv[0]))]},
        "montants_isoles": {"aides": isoles,
                            "regle": "aide d'au moins 100 M€ et au moins mille fois la médiane des aides de sa mesure : "
                                     "signalée comme montant à vérifier auprès de l'autorité, gardée telle que publiée "
                                     "dans tous les totaux"},
        "beneficiaires": groupe.sortie(ident),
        "ordre": {"regle": "listes par élément d'aide décroissant, puis identifiant ; années croissantes",
                  "cles": ["-element_aide_eur", "identifiant"]},
        "collecte": {**man, "methode": SOURCES["tam"]["collecte"], "url": SOURCES["tam"]["url"],
                     "champ_non_lu": "nom du bénéficiaire (jamais enregistré : les personnes morales sont nommées "
                                     "d'après le répertoire SIRENE)"},
    }
    return obj


# --- France 2030 -------------------------------------------------------------------------------------------------------

OPERATEURS_F2030 = {"BPI": "Bpifrance", "ANR": "ANR", "ADEME": "ADEME", "CDC": "Caisse des Dépôts", "DGAC": "DGAC",
                    "CNES": "CNES"}
REGIONS_F2030 = {"IDF": "11", "AURA": "84", "OCCITANIE": "76", "NOUVELLE-AQUITAINE": "75", "PACA": "93", "HDF": "32",
                 "GRAND-EST": "44", "BRETAGNE": "53", "PDL": "52", "BFC": "27", "CVL": "24", "NORMANDIE": "28",
                 "CORSE": "94"}
ZONES_F2030 = {"DROM-COM": "outre-mer (départements, régions et collectivités d'outre-mer), non réparti par la source",
               "PLURIRÉGIONS": "plusieurs régions, non réparti par la source"}


def _num(v) -> float | None:
    v = propre(v).replace(",", ".")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def lignes_france2030() -> tuple[list[dict], int]:
    import duckdb
    p = SOURCES["france2030"]["chemin"]
    if not p.exists():
        raise SystemExit(f"{p.relative_to(ROOT)} absent : lancer la collecte (aides_france2030_projets)")
    con = duckdb.connect()
    brut = con.sql(f"select count(*) from read_csv_auto('{p}', all_varchar=true)").fetchall()[0][0]
    rel = con.sql(f"select distinct * from read_csv_auto('{p}', all_varchar=true)")
    cols = rel.columns
    rows = [dict(zip(cols, r)) for r in rel.fetchall()]
    rows.sort(key=lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True, default=str))
    return rows, brut


class Somme:
    __slots__ = ("montant", "projets", "sirens")

    def __init__(self):
        self.montant, self.projets, self.sirens = 0.0, 0, set()

    def ajouter(self, montant: float, siren: str):
        self.montant += montant
        self.projets += 1
        if siren:
            self.sirens.add(siren)

    def sortie(self) -> dict:
        return {"montant_eur": eur(self.montant), "projets": self.projets, "beneficiaires": len(self.sirens)}


def produire_france2030(terr: Territoires, ident: Identites) -> dict:
    rows, brut = lignes_france2030()
    tot = Somme()
    composantes = defaultdict(float)
    par = {k: defaultdict(Somme) for k in ("annee", "operateur", "region_financement", "region_beneficiaire",
                                          "section", "typologie", "objectif", "strategie", "programme")}
    croise = {k: defaultdict(Somme) for k in ("annee_region", "annee_section", "annee_operateur")}
    sections_resolues = Somme()
    for r in rows:
        m = _num(r.get("montant_aide")) or 0.0
        siren = siren_de(r.get("siren"))
        an = propre(r.get("annee")) or "non renseignée"
        op = OPERATEURS_F2030.get(propre(r.get("operateur")).upper(), propre(r.get("operateur")) or "non renseigné")
        rf = propre(r.get("region_finances")).upper()
        reg_f = REGIONS_F2030.get(rf) or (rf if rf in ZONES_F2030 else "non renseignée")
        cr = propre(r.get("code_region"))
        reg_b = cr if cr in terr.regs else "non renseignée"
        sec = ident.section(siren) if siren else None
        if sec:
            sections_resolues.ajouter(m, siren)
        sec = sec or ("sans SIREN" if not siren else "non résolue")
        typ = " / ".join(x for x in (propre(r.get("categorie_typologie")), propre(r.get("typologie"))) if x) \
            or "non renseignée"
        prog = (re.match(r"\s*(\d{3})", propre(r.get("actions"))) or [None, None])[1] or "autre code d'action"
        tot.ajouter(m, siren)
        for k in ("montant_subvention", "montant_avance_remboursable", "montant_interet_dnc"):
            composantes[k] += _num(r.get(k)) or 0.0
        for k, v in (("annee", an), ("operateur", op), ("region_financement", reg_f), ("region_beneficiaire", reg_b),
                     ("section", sec), ("typologie", typ), ("objectif", propre(r.get("nomenclature")) or
                                                            "non renseigné"),
                     ("strategie", propre(r.get("nom_strategie")) or "non renseignée"), ("programme", prog)):
            par[k][v].ajouter(m, siren)
        croise["annee_region"][(an, reg_f)].ajouter(m, siren)
        croise["annee_section"][(an, sec)].ajouter(m, siren)
        croise["annee_operateur"][(an, op)].ajouter(m, siren)

    def liste(k: str, nom=None) -> list:
        return [{"cle": c, **({"libelle": nom(c)} if nom else {}), **s.sortie()}
                for c, s in sorted(par[k].items(), key=lambda kv: (-kv[1].montant, kv[0]))]

    def nom_region(c):
        return terr.nom(c) or ZONES_F2030.get(c) or c

    def croiser(k):
        out = defaultdict(dict)
        for (an, c), s in sorted(croise[k].items()):
            out[an][c] = s.sortie()
        return dict(out)

    f2030 = SITE / "beneficiaires" / "france2030.json"
    rapprochement = None
    if f2030.exists():
        b = json.loads(f2030.read_text(encoding="utf-8"))
        autre = b.get("ensemble", {}).get("total_eur")
        rapprochement = {"fichier": "beneficiaires/france2030.json", "champ": "ensemble.total_eur",
                         "montant_eur": eur(tot.montant), "autre_montant_eur": autre,
                         "ecart_eur": eur(tot.montant - autre) if autre is not None else None,
                         "lecture": "même fichier source, mêmes doublons exacts retirés : l'écart attendu est nul ; "
                                    "les bénéficiaires nommés (personnes morales) sont dans ce fichier, pas ici"}
    somme_comp = sum(composantes.values())
    return {
        "millesime": f"Projets France 2030 décidés de {min(par['annee'])} à {max(par['annee'])} (montants d'aide "
                     "engagés, cumulés par année de décision)",
        "source": f"{SOURCES['france2030']['titre']} ; section NAF : API Recherche d'entreprises "
                  "(recherche-entreprises.api.gouv.fr)",
        "unite": "euros (montant d'aide engagé : subvention et avance remboursable)",
        "avertissement": "Montants engagés au moment de la décision, versés sur plusieurs années : ils ne se comparent "
                         "pas à une dépense annuelle. Les bénéficiaires ne sont pas tous des entreprises (organismes "
                         "de recherche, établissements publics, collectivités, associations).",
        "lignes_source": brut, "doublons_exacts_retires": brut - len(rows),
        "total": tot.sortie(),
        "composantes_eur": {"subvention": eur(composantes["montant_subvention"]),
                            "avance_remboursable": eur(composantes["montant_avance_remboursable"]),
                            "interets": eur(composantes["montant_interet_dnc"]),
                            "ecart_au_montant_aide": eur(tot.montant - somme_comp),
                            "note": "colonnes publiées par la source ; leur somme ne retombe pas exactement sur le "
                                    "montant d'aide (écart publié tel quel)"},
        "par_annee": {k: s.sortie() for k, s in sorted(par["annee"].items())},
        "par_operateur": liste("operateur"),
        "par_region_financement": liste("region_financement", nom_region),
        "par_region_beneficiaire": liste("region_beneficiaire", nom_region),
        "par_secteur": [{"section": c if c in SECTIONS_NAF else None,
                         "libelle": SECTIONS_NAF.get(c, c), **s.sortie()} for c, s in
                        sorted(par["section"].items(), key=lambda kv: (-kv[1].montant, kv[0]))],
        "par_typologie": liste("typologie"),
        "par_objectif": liste("objectif"),
        "par_strategie": liste("strategie"),
        "par_programme": liste("programme"),
        "croisements": {"annee_region_financement": croiser("annee_region"), "annee_secteur": croiser("annee_section"),
                        "annee_operateur": croiser("annee_operateur")},
        "couverture_secteur": {"montant_eur": eur(sections_resolues.montant),
                               "part": round(sections_resolues.montant / tot.montant, 4) if tot.montant else None,
                               "beneficiaires": len(sections_resolues.sirens),
                               "beneficiaires_avec_siren": len(tot.sirens),
                               "methode": "section NAF de l'unité légale (activité principale) dans le répertoire "
                                          "SIRENE ; SIREN non encore résolu : « non résolue », relancer collecter"},
        "regions": {"region_financement": "colonne region_finances de la source (région du projet financé)",
                    "region_beneficiaire": "colonnes code_region et label_region de la source (localisation du "
                                           "bénéficiaire), absentes pour une partie des lignes"},
        "rapprochement": rapprochement,
        "beneficiaires_nommes": {"fichier": "beneficiaires/france2030.json",
                                 "note": "bénéficiaires nommés (personnes morales) par opérateur : non recopiés ici"},
        "ordre": {"regle": "listes par montant décroissant, puis clé ; années croissantes",
                  "cles": ["-montant_eur", "cle"]},
    }


# --- France Relance -----------------------------------------------------------------------------------------------------

def _duck_lignes(p: Path, requete: str = "select * from '{p}'") -> list[dict]:
    import duckdb
    if not p.exists():
        raise SystemExit(f"{p.relative_to(ROOT)} absent : lancer `python pipeline/aides_entreprises.py collecter`")
    rel = duckdb.sql(requete.format(p=p))
    cols = rel.columns
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _code_dep(v) -> str | None:
    c = propre(v)
    if re.fullmatch(r"\d+(\.0)?", c):
        c = str(int(float(c)))
        return c.zfill(2) if len(c) < 3 else c
    return c.upper() or None


def produire_france_relance(terr: Territoires, ident: Identites) -> dict:
    # 1. Lauréats publiés (projets industriels) : sans montant par projet à la source.
    projets = _duck_lignes(SOURCES["relance_laureats"]["chemin"],
                           "select siren, entreprise, type_entreprise, mesure, mesure_light, volet_relance, filiere, "
                           "code_departement, nom_region, mise_a_jour from '{p}'")
    projets.sort(key=lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True, default=str))
    colonnes = ["siren", "denomination", "categorie_juridique", "mesure", "filiere", "type_entreprise", "departement",
                "region", "mise_a_jour"]
    nommes, agreges = [], Counter()
    comptes = {k: Counter() for k in ("mesure", "filiere", "type_entreprise", "region")}
    dates = []
    for r in projets:
        siren = siren_de(r.get("siren"))
        dep = _code_dep(r.get("code_departement"))
        reg = terr.region_de_departement(dep) if dep else None
        mesure, filiere = propre(r.get("mesure")) or "non renseignée", propre(r.get("filiere")) or "non renseignée"
        typ = propre(r.get("type_entreprise")) or "non renseigné"
        for k, v in (("mesure", mesure), ("filiere", filiere), ("type_entreprise", typ), ("region", reg or
                                                                                          "non renseignée")):
            comptes[k][v] += 1
        maj = str(r.get("mise_a_jour"))[:10] if r.get("mise_a_jour") else None
        if maj:
            dates.append(maj)
        st, cj = ident.statut(siren) if siren else ("ni", None)
        if st == "pm":
            nom = ident.nom(siren) or propre(r.get("entreprise")) or None
            nommes.append([siren, nom, cj, mesure, filiere, typ, dep, reg, maj])
        else:
            agreges[{"pp": "personnes_physiques", "nv": "categorie_non_verifiee"}.get(st, "sans_siren_valide"
                     if not siren else "categorie_inconnue")] += 1
    nommes.sort(key=lambda l: (l[3], l[1] or "", l[0]))

    def compte(k):
        return [{"cle": c, "projets": n, **({"libelle": terr.nom(c)} if k == "region" and terr.nom(c) else {})}
                for c, n in sorted(comptes[k].items(), key=lambda kv: (-kv[1], kv[0]))]

    # 2. Montants agrégés (mêmes appels à projets industriels, autre publication).
    mf = _duck_lignes(SOURCES["relance_mesure_filiere"]["chemin"])
    te = _duck_lignes(SOURCES["relance_type_entreprise"]["chemin"])
    rd = _duck_lignes(SOURCES["relance_region_departement"]["chemin"])
    fut = _duck_lignes(SOURCES["relance_industrie_futur"]["chemin"])
    num = _duck_lignes(SOURCES["relance_france_num"]["chemin"])

    par_mf = sorted(({"mesure": propre(x["mesure"]), "filiere": propre(x["filiere"]) or "non renseignée",
                      "investissement_eur": eur(x["somme_de_montant_investissement"]),
                      "participation_etat_eur": eur(x["somme_de_montant_participation_etat"])} for x in mf),
                    key=lambda x: (-(x["participation_etat_eur"] or 0), x["mesure"], x["filiere"]))
    par_te = sorted(({"mesure": propre(x["mesure"]), "type_entreprise": propre(x["type_entreprise"]) or "non renseigné",
                      "investissement_eur": eur(x["somme_de_montant_investissement"]),
                      "participation_etat_eur": eur(x["somme_de_montant_participation_etat"])} for x in te),
                    key=lambda x: (-(x["participation_etat_eur"] or 0), x["mesure"], x["type_entreprise"]))
    par_rd = sorted(({"departement": _code_dep(x["code_departement"]), "nom": propre(x["nom_departement"]),
                      "region": terr.region_de_departement(_code_dep(x["code_departement"])),
                      "investissement_eur": eur(x["montant_investissement"]),
                      "participation_etat_eur": eur(x["montant_participation_etat"])} for x in rd),
                    key=lambda x: (-(x["participation_etat_eur"] or 0), x["departement"] or ""))
    par_fut = sorted(({"departement": _code_dep(x["code_departement"]), "nom": propre(x["nom_departement"]),
                       "region": terr.region_de_departement(_code_dep(x["code_departement"])),
                       "beneficiaires": int(x["nombre_beneficiaires"]) if x["nombre_beneficiaires"] is not None
                       else None, "investissement_eur": eur(x["montant_investissement"]),
                       "participation_etat_eur": eur(x["montant_participation_etat"])} for x in fut),
                     key=lambda x: (-(x["participation_etat_eur"] or 0), x["departement"] or ""))
    par_num = sorted(({"departement": _code_dep(x["code_departement"]), "nom": propre(x["nom_departement"]),
                       "region": terr.region_de_departement(_code_dep(x["code_departement"])),
                       "beneficiaires": int(x["nombre_beneficiaires"]) if x["nombre_beneficiaires"] is not None
                       else None, "participation_etat_eur": eur(x["montant_participation_etat"])} for x in num),
                     key=lambda x: (-(x["participation_etat_eur"] or 0), x["departement"] or ""))

    def somme(lignes, cle):
        vals = [x[cle] for x in lignes if x.get(cle) is not None]
        return eur(sum(vals)) if vals else None

    def par_mesure(lignes):
        d = defaultdict(lambda: [0.0, 0.0])
        for x in lignes:
            d[x["mesure"]][0] += x["participation_etat_eur"] or 0
            d[x["mesure"]][1] += x["investissement_eur"] or 0
        return {k: {"participation_etat_eur": eur(v[0]), "investissement_eur": eur(v[1])} for k, v in sorted(d.items())}

    def par_region(lignes, *cles):
        d = defaultdict(lambda: defaultdict(float))
        for x in lignes:
            for c in cles:
                if x.get(c) is not None:
                    d[x["region"] or "non rattaché"][c] += x[c]
        return [{"code": k if k in terr.regs else None, "nom": terr.nom(k) or k,
                 **{c: (int(v[c]) if c == "beneficiaires" else eur(v[c])) for c in cles}}
                for k, v in sorted(d.items(), key=lambda kv: (-kv[1][cles[-1]], kv[0]))]

    totaux = {"mesure_filiere": somme(par_mf, "participation_etat_eur"),
              "type_entreprise": somme(par_te, "participation_etat_eur"),
              "region_departement": somme(par_rd, "participation_etat_eur")}
    tables = {"mesure_filiere": "table par mesure et par filière",
              "type_entreprise": "table par mesure et par type d'entreprise",
              "region_departement": "table par région et par département"}
    ecarts, pm = [], par_mesure(par_mf)
    for a, b in (("mesure_filiere", "type_entreprise"), ("mesure_filiere", "region_departement")):
        if totaux[a] is None or totaux[b] is None:
            continue
        ecart = totaux[a] - totaux[b]
        e = {"objet": "participation de l'État aux projets industriels lauréats (mêmes appels à projets, même date)",
             "source": tables[a], "montant_eur": totaux[a], "autre_source": tables[b], "autre_montant_eur": totaux[b],
             "ecart_eur": eur(ecart), "ecart_pct": round(100 * ecart / totaux[a], 2) if totaux[a] else None}
        if abs(ecart) <= 1:
            e["lecture_ecart"] = "les deux tables ventilent le même total"
        else:
            from itertools import combinations
            combis = [list(c) for k in (1, 2, 3) for c in combinations(sorted(pm), k)
                      if abs(sum(pm[n]["participation_etat_eur"] for n in c) - ecart) <= 1_000_000]
            e["lecture_ecart"] = ("les deux tables ne ventilent pas le même total et la source ne donne pas "
                                  "d'explication" + (" ; constat arithmétique : l'écart est égal, à 1 M€ près, à la "
                                                     "participation de l'État des mesures « " + " » et « ".join(
                                                         combis[0]) + " » de la table par mesure"
                                                     if len(combis) == 1 else ""))
        ecarts.append(e)
    return {
        "millesime": f"Lauréats publiés du {min(dates)} au {max(dates)} ; montants agrégés publiés le 8 avril 2022 "
                     "(projets industriels, annonces arrêtées au 18 décembre, année non précisée par la source) ; "
                     "Industrie du futur et chèque France Num par département (données 2021 et 2022)"
                     if dates else "France Relance",
        "source": " ; ".join(SOURCES[k]["titre"] for k in ("relance_laureats", "relance_mesure_filiere",
                                                          "relance_type_entreprise", "relance_region_departement",
                                                          "relance_industrie_futur", "relance_france_num")),
        "unite": "euros ; projets ; entreprises bénéficiaires",
        "avertissement": "Les montants sont la participation de l'État annoncée (subventions et avances des appels à "
                         "projets), à côté de l'investissement total des entreprises ; la source ne publie aucun "
                         "montant par lauréat. Les lauréats et les montants sont deux publications distinctes.",
        "laureats": {"colonnes": colonnes, "lignes": nommes,
                     "projets_publies": len(projets), "projets_nommes": len(nommes),
                     "projets_agreges": dict(sorted(agreges.items())),
                     "regle": "seuls les lauréats dont la catégorie juridique SIRENE est celle d'une personne morale "
                              "(2xxx à 9xxx) sont nommés, d'après le répertoire SIRENE ; les autres sont comptés"},
        "projets_par": {k: compte(k) for k in ("mesure", "filiere", "type_entreprise", "region")},
        "montants": {
            "par_mesure_et_filiere": par_mf, "par_mesure_et_type_entreprise": par_te,
            "par_departement": par_rd, "par_region": par_region(par_rd, "investissement_eur", "participation_etat_eur"),
            "par_mesure": par_mesure(par_mf), "totaux_participation_etat_eur": totaux,
            "industrie_du_futur": {"departements": par_fut,
                                   "regions": par_region(par_fut, "beneficiaires", "investissement_eur",
                                                         "participation_etat_eur"),
                                   "total": {"beneficiaires": int(sum(x["beneficiaires"] or 0 for x in par_fut)),
                                             "investissement_eur": somme(par_fut, "investissement_eur"),
                                             "participation_etat_eur": somme(par_fut, "participation_etat_eur")}},
            "cheque_france_num": {"departements": par_num,
                                  "regions": par_region(par_num, "beneficiaires", "participation_etat_eur"),
                                  "total": {"beneficiaires": int(sum(x["beneficiaires"] or 0 for x in par_num)),
                                            "participation_etat_eur": somme(par_num, "participation_etat_eur")}},
        },
        "ecarts": ecarts,
        "ordre": {"regle": "lauréats par mesure puis dénomination ; montants par participation de l'État décroissante",
                  "cles": ["mesure", "denomination", "-participation_etat_eur"]},
    }


# --- Prêts garantis par l'État ------------------------------------------------------------------------------------------

TRESOR_PGE = {"source": "Direction générale du Trésor, « Analysis of France's State-Guaranteed Loan Scheme at "
                        "End-2021 », 3 mars 2022",
              "url": "https://www.tresor.economie.gouv.fr/Articles/2022/03/03/analysis-of-france-s-state-guaranteed-"
                     "loan-scheme-at-end-2021",
              "citation": "some €145bn had been lent out to more than 700,000 firms", "montant_eur": 145e9,
              "precision": "montant arrondi par la source (« some »), nombre d'entreprises et non de prêts"}


def lire_pge() -> dict:
    """{date de mise à jour: {"regional": [...], "departemental": [...]}} pour chaque fichier PGE de l'entrepôt."""
    import duckdb
    situations = defaultdict(dict)
    for dossier in (SOURCES["pge"]["chemin"], SOURCES["pge_historique"]["chemin"]):
        for f in sorted(dossier.glob("*.csv")):
            maille = "departemental" if "departemental" in f.name else "regional" if "regional" in f.name else None
            if maille is None:
                continue
            rel = duckdb.sql(f"select * from read_csv_auto('{f}', all_varchar=true)")
            cols = rel.columns
            lignes = [dict(zip(cols, r)) for r in rel.fetchall()]
            dates = {propre(x.get("date_maj")) for x in lignes} - {""}
            if len(dates) != 1:
                raise SystemExit(f"{f} : date de mise à jour absente ou multiple ({sorted(dates)})")
            situations[dates.pop()][maille] = sorted(lignes, key=lambda x: json.dumps(x, sort_keys=True))
    if not situations:
        raise SystemExit("data/lake/aides_entreprises/aides_pge absent : lancer la collecte (aides_pge, "
                         "aides_pge_historique)")
    return dict(sorted(situations.items()))


def produire_pge(terr: Territoires) -> dict:
    situations = lire_pge()
    dates = list(situations)
    agg = {k: defaultdict(lambda: defaultdict(lambda: [0, 0.0])) for k in ("total", "section", "region", "departement")}
    noms_sections, noms_deps = {}, {}
    for d, mailles in situations.items():
        for x in mailles.get("regional", []):
            n, m = _num(x.get("nombre_pge")) or 0, _num(x.get("montant_total")) or 0.0
            sec = propre(x.get("code_section")) or "Z"
            noms_sections[sec] = propre(x.get("libelle_section"))
            reg = propre(x.get("reg")) or "non renseignée"
            reg = reg if reg in terr.regs else ("non renseignée" if reg == "non renseignée" else reg)
            for k, c in (("total", "France"), ("section", sec), ("region", reg)):
                agg[k][c][d][0] += n
                agg[k][c][d][1] += m
        for x in mailles.get("departemental", []):
            n, m = _num(x.get("nombre_pge")) or 0, _num(x.get("montant_total")) or 0.0
            dep = _code_dep(x.get("dep")) or "non renseigné"
            noms_deps[dep] = propre(x.get("libelle_departement")) or None
            agg["departement"][dep][d][0] += n
            agg["departement"][dep][d][1] += m

    def series(v: dict) -> dict:
        out = {"situations": {d: {"prets": int(round(v[d][0])), "montant_eur": eur(v[d][1])} for d in dates if d in v}}
        if len(dates) == 2 and all(d in v for d in dates):
            premier, dernier = dates
            out["par_annee"] = {
                "2020": {"prets": int(round(v[premier][0])), "montant_eur": eur(v[premier][1])},
                "2021": {"prets": int(round(v[dernier][0] - v[premier][0])),
                         "montant_eur": eur(v[dernier][1] - v[premier][1])}}
        return out

    sections = [{"section": None if s == "Z" else s, "libelle": SECTIONS_NAF.get(s) or noms_sections.get(s),
                 "libelle_source": noms_sections.get(s), **series(v)}
                for s, v in sorted(agg["section"].items(), key=lambda kv: (-kv[1][dates[-1]][1], kv[0]))]
    regions = [{"code": c if c in terr.regs else None, "nom": terr.nom(c) or c, **series(v)}
               for c, v in sorted(agg["region"].items(), key=lambda kv: (-kv[1][dates[-1]][1], kv[0]))]
    deps = [{"code": c, "nom": noms_deps.get(c), "region": terr.region_de_departement(c), **series(v)}
            for c, v in sorted(agg["departement"].items(), key=lambda kv: (-kv[1][dates[-1]][1], kv[0]))]
    total = series(agg["total"]["France"])
    negatifs = []
    for maille, lst, cle in (("section", sections, "section"), ("region", regions, "code"),
                             ("departement", deps, "code")):
        for x in lst:
            an = (x.get("par_annee") or {}).get("2021")
            if an and (an["montant_eur"] < 0 or an["prets"] < 0):
                negatifs.append({"maille": maille, "cle": x[cle] or "non connu", "montant_eur": an["montant_eur"],
                                 "prets": an["prets"]})
    ecarts = []
    for d in dates:
        reg = agg["total"]["France"][d][1]
        dep = sum(v[d][1] for v in agg["departement"].values() if d in v)
        ecarts.append({"objet": f"montant des PGE, situation au {d}", "source": "fichier par région et section NAF",
                       "montant_eur": eur(reg), "autre_source": "fichier par département et section NAF",
                       "autre_montant_eur": eur(dep), "ecart_eur": eur(reg - dep),
                       "ecart_pct": round(100 * (reg - dep) / reg, 4) if reg else None,
                       "lecture_ecart": "les deux fichiers ventilent le même total" if abs(reg - dep) <= 1 else
                       "les deux fichiers ne retombent pas sur le même total ; écart publié tel quel"})
    dernier = dates[-1]
    ecarts.append({"objet": "montant des PGE accordés fin 2021", "source": f"{SOURCES['pge']['titre']}, situation au "
                                                                         f"{dernier}",
                   "montant_eur": eur(agg["total"]["France"][dernier][1]), "autre_source": TRESOR_PGE["source"],
                   "autre_montant_eur": TRESOR_PGE["montant_eur"], "autre_url": TRESOR_PGE["url"],
                   "citation": TRESOR_PGE["citation"],
                   "ecart_eur": eur(agg["total"]["France"][dernier][1] - TRESOR_PGE["montant_eur"]),
                   "ecart_pct": round(100 * (agg["total"]["France"][dernier][1] - TRESOR_PGE["montant_eur"])
                                      / TRESOR_PGE["montant_eur"], 2),
                   "lecture_ecart": "montant arrondi par le Trésor, dont la date d'arrêté et les données ne sont pas "
                                    "précisées ; l'article compte des entreprises, le fichier des prêts"})
    return {
        "millesime": f"Situations au {dates[0]} et au {dates[-1]} (dates de mise à jour des fichiers)",
        "source": f"{SOURCES['pge']['titre']} ; {SOURCES['pge_historique']['titre']}",
        "unite": "euros (montant des prêts garantis) ; nombre de prêts",
        "avertissement": "Montant prêté par les banques avec la garantie de l'État, pas une dépense de l'État : une "
                         "dépense n'apparaît que si la garantie est appelée après un défaut. Les fichiers publiés "
                         "s'arrêtent au 31 décembre 2021 ; le dispositif est resté ouvert jusqu'au 30 juin 2022.",
        "dates": dates,
        "methode_par_annee": {"2020": f"situation au {dates[0]} (premiers prêts en mars 2020)",
                              "2021": f"différence entre les situations du {dates[-1]} et du {dates[0]}"}
        if len(dates) == 2 else None,
        "total": total,
        "par_secteur": sections,
        "par_region": regions,
        "par_departement": deps,
        "differences_negatives": {"cellules": negatifs,
                                  "note": "une différence négative entre deux situations (prêt annulé, reclassement "
                                          "de secteur ou de lieu) est publiée telle quelle, jamais corrigée"},
        "ecarts": ecarts,
        "ordre": {"regle": "par montant décroissant à la dernière situation, puis code", "cles": ["-montant_eur",
                                                                                                 "code"]},
    }


# --- Index ----------------------------------------------------------------------------------------------------------------

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Aucun jeu ouvert ne publie le registre européen des aides d'État pour la France en fichier : la "
                  "Commission envoie ses exports par courriel après saisie d'un nom, et le seul dépôt public qui le "
                  "lit (pages de résultats) ne déclare pas de licence. Le module reprend la méthode des pages "
                  "publiques sans reprendre de code. France 2030, France Relance et les PGE sont repris tels que "
                  "publiés (data.gouv.fr, data.economie.gouv.fr, Etalab).",
    "trouvailles": [
        {"nom": "Commission européenne, State Aid Transparency, recherche publique", "url": TAM_PAGE,
         "verdict": "réutilisable tel quel (pages publiques de résultats ; export par courriel non utilisé)",
         "licence": "réutilisation autorisée avec mention de la source (décision 2011/833/UE)",
         "mise_a_jour": "quotidienne (version 2.18.1 de l'application)"},
        {"nom": "DataFrosch/scraper-stateaid (lecture paginée du registre, Python et PostgreSQL)",
         "url": "https://github.com/DataFrosch/scraper-stateaid", "verdict": "inspiration seulement",
         "licence": "aucune licence déclarée", "mise_a_jour": "2026-03-11"},
        {"nom": "jfjelstul/eusa (paquet R, aides d'État et aides individuelles 2016-2020)",
         "url": "https://github.com/jfjelstul/eusa", "verdict": "inspiration seulement (arrêté en 2020)",
         "licence": "MIT", "mise_a_jour": "2021-09-15"},
        {"nom": "AsktheEU, demande d'extraction en masse du registre (réponse de la DG Concurrence, 23 juillet "
                "2024)", "url": "https://www.asktheeu.org/request/state_aid_bulk_data_for_poland_s",
         "verdict": "inspiration seulement (aucune extraction en masse publiée)", "licence": "sans objet",
         "mise_a_jour": "2024-07-23"},
        {"nom": "etalab/dashboard-aides-entreprises (fichiers publiés : PGE, fonds de solidarité, historique)",
         "url": "https://github.com/etalab/dashboard-aides-entreprises", "verdict": "réutilisable tel quel (données)",
         "licence": "MIT (code), Licence Ouverte 2.0 (données)", "mise_a_jour": "2022-06-29"},
        {"nom": "data.gouv.fr, France 2030 (Préfecture de région Bretagne)", "url": SOURCES["france2030"]["url"],
         "verdict": "réutilisable tel quel (déjà lu par pipeline/beneficiaires.py)",
         "licence": "non précisée sur la fiche data.gouv.fr", "mise_a_jour": "2026-06-17"},
        {"nom": "data.economie.gouv.fr, Plan de relance : projets industriels, Industrie du futur, chèque France Num",
         "url": SOURCES["relance_laureats"]["url"], "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2022-04-08"},
        {"nom": "data.economie.gouv.fr, France Relance : données agrégées (indicateurs d'avancement par territoire)",
         "url": "https://www.data.gouv.fr/datasets/france-relance-donnees-agregees",
         "verdict": "à adapter, non repris (indicateurs hétérogènes : nombres, montants cumulés, effets de levier)",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2021-09-06"},
        {"nom": "data.economie.gouv.fr, Registre public des aides de minimis (octroyées depuis 2026)",
         "url": "https://www.data.gouv.fr/datasets/registre-public-des-aides-de-minimis",
         "verdict": "à adapter, non repris dans cette version (bénéficiaires personnes physiques nommés à la source)",
         "licence": "non précisée sur la fiche data.gouv.fr", "mise_a_jour": "2026-11-17"},
        {"nom": "data.gouv.fr, Base de données des aides aux entreprises (aides-entreprises.fr, DGE)",
         "url": "https://www.data.gouv.fr/datasets/base-de-donnees-des-aides-aux-entreprises",
         "verdict": "inspiration seulement (catalogue de dispositifs, sans montants octroyés)",
         "licence": "Licence Ouverte", "mise_a_jour": "2026-10-23"},
        {"nom": "Recherche GitHub « state aid transparency », « aides entreprises france relance france 2030 PGE »",
         "url": "https://github.com/search?q=state+aid+transparency&type=repositories",
         "verdict": "aucun autre dépôt pertinent", "licence": "sans objet", "mise_a_jour": "2026-11-18"},
    ],
}

INACCESSIBLES = [
    {"source": "Registre TAM, export CSV ou XLSX", "url": TAM_PAGE,
     "constat": "l'export demande un nom et une adresse de courriel et part par courriel (100 000 lignes au plus)",
     "effet": "non utilisé : lecture des pages publiques de résultats, mois par mois"},
    {"source": "Registre TAM, mention Covid-19 de chaque aide", "url": TAM_PAGE,
     "constat": "critère de recherche sans colonne dans les résultats", "effet": "aides Covid-19 non isolées"},
    {"source": "PGE accordés en 2022", "url": SOURCES["pge"]["url"],
     "constat": "les fichiers publiés s'arrêtent au 31 décembre 2021", "effet": "année 2022 non couverte"},
    {"source": "France Relance, montant par lauréat", "url": SOURCES["relance_laureats"]["url"],
     "constat": "la liste des lauréats ne donne aucun montant", "effet": "montants agrégés seulement"},
]


def _date_collecte(ids) -> str | None:
    """Date (AAAA-MM-JJ) de la collecte la plus récente des sources du catalogue lues ; SOURCE_DATE_EPOCH prioritaire."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), timezone.utc).date().isoformat()
    try:
        man = json.loads((LAKE / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    dates = [str(man[i]["collecte_le"])[:10] for i in ids if isinstance(man.get(i), dict) and man[i].get("collecte_le")]
    return max(dates) if dates else None


def _estimation(id_: str) -> dict | None:
    p = SITE / "controle" / "aides_entreprises.json"
    if not p.exists():
        return None
    for e in json.loads(p.read_text(encoding="utf-8")).get("estimations", []):
        if e.get("id") == id_:
            return e
    return None


def construire_index(tam: dict, f30: dict, rel: dict, pge: dict, terr: Territoires) -> dict:
    dispositifs = [
        {"id": "tam", "nom": "Registre européen de transparence des aides d'État (aides individuelles publiées par "
                             "les autorités françaises)",
         "notion": "élément d'aide (équivalent-subvention) des aides octroyées au-dessus des seuils de publication",
         "fichier": "aides_entreprises/tam.json", "annees": tam["annees"],
         "par_annee_eur": {a: v["element_aide_eur"] for a, v in tam["par_annee"].items()},
         "total_eur": tam["total"]["element_aide_eur"], "aides": tam["total"]["aides"]},
        {"id": "france2030", "nom": "France 2030 (projets lauréats)",
         "notion": "montant d'aide engagé à la décision (subvention et avance remboursable), versé sur plusieurs "
                   "années", "fichier": "aides_entreprises/france2030.json",
         "annees": [int(a) for a in f30["par_annee"] if re.fullmatch(r"\d{4}", a)],
         "par_annee_eur": {a: v["montant_eur"] for a, v in f30["par_annee"].items()},
         "total_eur": f30["total"]["montant_eur"], "projets": f30["total"]["projets"]},
        {"id": "france_relance_industrie", "nom": "France Relance, appels à projets et guichets industriels",
         "notion": "participation de l'État annoncée aux projets lauréats", "fichier":
             "aides_entreprises/france_relance.json", "annees": None, "par_annee_eur": None,
         "total_eur": rel["montants"]["totaux_participation_etat_eur"]["mesure_filiere"],
         "projets": rel["laureats"]["projets_publies"],
         "note": "la source ne ventile pas les montants par année"},
        {"id": "france_relance_industrie_du_futur", "nom": "France Relance, guichet Industrie du futur",
         "notion": "participation de l'État (subventions)", "fichier": "aides_entreprises/france_relance.json",
         "annees": None, "par_annee_eur": None,
         "total_eur": rel["montants"]["industrie_du_futur"]["total"]["participation_etat_eur"],
         "beneficiaires": rel["montants"]["industrie_du_futur"]["total"]["beneficiaires"]},
        {"id": "france_relance_cheque_france_num", "nom": "France Relance, chèque France Num",
         "notion": "chèques versés aux entreprises", "fichier": "aides_entreprises/france_relance.json",
         "annees": None, "par_annee_eur": None,
         "total_eur": rel["montants"]["cheque_france_num"]["total"]["participation_etat_eur"],
         "beneficiaires": rel["montants"]["cheque_france_num"]["total"]["beneficiaires"]},
        {"id": "pge", "nom": "Prêts garantis par l'État (Covid-19)",
         "notion": "montant des prêts accordés par les banques avec la garantie de l'État (pas une dépense de l'État)",
         "fichier": "aides_entreprises/pge.json", "annees": [2020, 2021] if pge.get("methode_par_annee") else None,
         "par_annee_eur": {a: v["montant_eur"] for a, v in (pge["total"].get("par_annee") or {}).items()} or None,
         "total_eur": pge["total"]["situations"][pge["dates"][-1]]["montant_eur"],
         "prets": pge["total"]["situations"][pge["dates"][-1]]["prets"]},
    ]
    annees = sorted({a for d in dispositifs for a in (d["par_annee_eur"] or {}) if re.fullmatch(r"\d{4}", a)})
    par_annee = {a: {d["id"]: d["par_annee_eur"][a] for d in dispositifs if (d["par_annee_eur"] or {}).get(a)
                     is not None} for a in annees}
    secteurs = defaultdict(dict)
    for x in tam["par_secteur"]:
        if x["section"]:
            secteurs[x["section"]]["tam"] = x["element_aide_eur"]
    for x in f30["par_secteur"]:
        if x["section"]:
            secteurs[x["section"]]["france2030"] = x["montant_eur"]
    for x in pge["par_secteur"]:
        if x["section"]:
            secteurs[x["section"]]["pge"] = x["situations"][pge["dates"][-1]]["montant_eur"]
    regions = defaultdict(dict)
    for x in tam["par_region"]:
        if x["code"]:
            regions[x["code"]]["tam"] = x["element_aide_eur"]
    for x in f30["par_region_financement"]:
        if x["cle"] in terr.regs:
            regions[x["cle"]]["france2030"] = x["montant_eur"]
    for x in rel["montants"]["par_region"]:
        if x["code"]:
            regions[x["code"]]["france_relance_industrie"] = x["participation_etat_eur"]
    for x in pge["par_region"]:
        if x["code"]:
            regions[x["code"]]["pge"] = x["situations"][pge["dates"][-1]]["montant_eur"]
    ecarts = list(rel["ecarts"]) + list(pge["ecarts"])
    for id_, an in (("ce_2024", "2022"), ("hcsp_2025_aides_etat", "2023")):
        e = _estimation(id_)
        if e and an in tam["par_annee"] and e.get("md") is not None:
            t = tam["par_annee"][an]["element_aide_eur"]
            ecarts.append({
                "objet": f"aides d'État en France, {an}", "source": f"registre TAM, aides octroyées en {an}",
                "montant_eur": t, "autre_source": f"{e['auteur']}, « {e['publication']} » ({e['annee_publication']})",
                "autre_montant_eur": e["md"] * 1e9, "autre_fichier": "controle/aides_entreprises.json",
                "autre_id": id_, "ecart_eur": eur(t - e["md"] * 1e9),
                "ecart_pct": round(100 * (t - e["md"] * 1e9) / (e["md"] * 1e9), 2),
                "lecture_ecart": "notions différentes : le registre ne contient que les aides individuelles publiées "
                                 "au-dessus des seuils, comptées l'année de leur octroi pour leur montant total ; "
                                 "l'estimation porte sur l'ensemble des aides d'État de l'année, régimes fiscaux "
                                 "compris. Les deux montants sont publiés côte à côte, sans être départagés."})
    liens = [
        {"fichier": "controle/aides_entreprises.json", "objet": "estimations publiées de l'ensemble des aides aux "
                                                                 "entreprises (périmètres, années) et exonérations de "
                                                                 "cotisations Urssaf"},
        {"fichier": "beneficiaires/france2030.json", "objet": "bénéficiaires nommés de France 2030 par opérateur"},
        {"fichier": "niches/index.json", "objet": "dépenses fiscales (souvent appelées niches fiscales), ménages "
                                                   "compris"},
        {"fichier": "ue/beneficiaires/index.json", "objet": "bénéficiaires des fonds européens en France"},
        {"fichier": "prestations/index.json", "objet": "sommes versées aux ménages (prestations sociales), même "
                                                       "format"},
    ]
    liens = [l for l in liens if (SITE / l["fichier"]).exists()]
    top = tam["beneficiaires"]
    return {
        "millesime": f"Registre TAM consulté au {tam['collecte']['collecte_au']} ; autres sources collectées au "
                     f"{_date_collecte(CATALOGUE_IDS)}",
        "source": "pipeline/aides_entreprises.py : Commission européenne (registre TAM), SGPI (France 2030), "
                  "ministère de l'économie (France Relance), Etalab (PGE) ; voir `sources`",
        "unite": "euros",
        "avertissement": "Chaque dispositif a sa notion de montant (élément d'aide, montant engagé, participation "
                         "annoncée, prêt garanti) : les montants sont publiés côte à côte et ne s'additionnent pas. "
                         "Une même aide peut figurer dans plusieurs sources (une aide France 2030 de plus de "
                         "100 000 € est aussi publiée dans le registre européen).",
        "dispositifs": dispositifs,
        "par_annee": {"regle": "un montant par source et par année, jamais additionnés", "annees": par_annee},
        "par_secteur": {"regle": "section NAF (nomenclature d'activités, identique à la NACE au niveau des "
                                 "sections) ; un montant par source, jamais additionnés ; PGE : situation au "
                                 f"{pge['dates'][-1]}",
                        "sections": {s: {"libelle": SECTIONS_NAF[s], **secteurs[s]} for s in sorted(secteurs)}},
        "par_region": {"regle": "région actuelle ; registre TAM : libellés rattachés (région, ancienne région, "
                                "département) ; France 2030 : région de financement ; France Relance : département "
                                "du projet ; PGE : région du fichier ; un montant par source, jamais additionnés",
                       "regions": {c: {"nom": terr.nom(c), **regions[c]} for c in sorted(regions)}},
        "ecarts": ecarts,
        "liens": liens,
        "confidentialite": {
            "regle": "Seules les personnes morales (catégorie juridique 2xxx à 9xxx dans le répertoire SIRENE) sont "
                     "nommées. Entrepreneurs individuels, exploitants agricoles, identifiants absents ou non vérifiés : "
                     "agrégés. Le nom du bénéficiaire publié dans le registre européen n'est jamais lu.",
            "tam": {"beneficiaires_nommes": len(top["top"]),
                    "montant_nomme_eur": eur(sum(x["montant_eur"] for x in top["top"])),
                    "autres_personnes_morales_eur": top["autres_personnes_morales"]["montant_eur"],
                    "non_verifies_eur": top["autres_non_verifies"]["montant_eur"],
                    "agreges_eur": top["exclus_personnes_physiques_ou_non_identifies"]["montant_eur"]},
            "france_relance": {"projets_nommes": rel["laureats"]["projets_nommes"],
                               "projets_agreges": rel["laureats"]["projets_agreges"]}},
        "limites": [
            "Le registre européen ne couvre que les aides individuelles au-dessus des seuils de publication : ni les "
            "petites aides, ni la plupart des avantages fiscaux généraux, ni les exonérations générales de "
            "cotisations.",
            "Les autorités publient jusqu'à un an après l'octroi : les années récentes du registre sont incomplètes "
            "et changent d'une collecte à l'autre.",
            "France 2030 compte des montants engagés à la décision, France Relance des participations annoncées, le "
            "registre européen des éléments d'aide, les PGE des prêts garantis : quatre notions différentes.",
            "Le secteur d'une aide du registre est celui que déclare l'autorité ; celui d'un bénéficiaire de France "
            "2030 est l'activité principale de l'unité légale dans le répertoire SIRENE.",
            "Les montants de France Relance ne sont pas ventilés par année ; ceux des PGE s'arrêtent à fin 2021.",
        ],
        "sources": [{"id": k, **{c: v for c, v in s.items() if c != "chemin"}} for k, s in SOURCES.items()],
        "sources_inaccessibles": INACCESSIBLES + ([{"source": "Registre TAM", "url": TAM_PAGE,
                                                    "constat": tam["collecte"]["dernier_refus"]["constat"],
                                                    "effet": "mois non relus conservés tels quels"}]
                                                  if tam["collecte"].get("dernier_refus") else []),
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "fichiers": ["aides_entreprises/index.json", "aides_entreprises/tam.json", "aides_entreprises/france2030.json",
                     "aides_entreprises/france_relance.json", "aides_entreprises/pge.json"],
    }


def produire(sortie: Path = SORTIE) -> dict:
    terr, ident = Territoires(), Identites()
    tam = produire_tam(terr, ident)
    f30 = produire_france2030(terr, ident)
    rel = produire_france_relance(terr, ident)
    pge = produire_pge(terr)
    tailles = {}
    for nom, obj in (("tam.json", tam), ("france2030.json", f30), ("france_relance.json", rel), ("pge.json", pge)):
        tailles[nom] = dump(sortie / nom, obj)
    index = construire_index(tam, f30, rel, pge, terr)
    tailles["index.json"] = dump(sortie / "index.json", index)
    print(json.dumps({"tailles": tailles, "tam": tam["total"], "france2030": f30["total"],
                      "relance": rel["montants"]["totaux_participation_etat_eur"],
                      "pge": pge["total"]["situations"]}, ensure_ascii=False))
    return index


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("collecter", help="réseau : catalogue, registre TAM, répertoire SIRENE")
    c.add_argument("--budget", type=float, default=1800, help="secondes (reprenable)")
    c.add_argument("--rafraichir", action="store_true", help="relire les mois récents du registre TAM")
    p = sp.add_parser("produire", help="sans réseau")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.cmd == "collecter":
        return collecter(a.budget, a.rafraichir)
    produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
