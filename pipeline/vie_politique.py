"""Argent public et vie politique : campagnes electorales, partis, programme 232 « Vie politique ».

Collecte (reseau, reprenable, chaque commande < 9 min) :
  python pipeline/vie_politique.py collecte cnccfp         # 26 jeux de l'organisation CNCCFP sur data.gouv.fr
  python pipeline/vie_politique.py collecte presidentielles # decisions CNCCFP publiees au JO (PDF) 2012, 2017, 2022
  python pipeline/vie_politique.py collecte budget          # budget vert PLF 2023 (execution 2021) et PLF 2027 (2025)
Production (sans reseau) :
  python pipeline/vie_politique.py produire

Entrees brutes : data/lake/_restreint/politique/ (tout ce qui nomme un candidat) et data/lake/politique/ (partis,
personnes morales). Sorties (chaque fichier porte `millesime` et `source`, montants en euros) :
  site/data/vie_politique/annees.json                 par annee : programme 232 par action, aide aux partis,
                                                      remboursements de campagne par scrutin, part en € sur 100 €
  site/data/vie_politique/partis/<annee>.json         aide publique par parti (1re et 2de fraction)
  site/data/vie_politique/scrutins/<scrutin>_<annee>.json   agregats par scrutin, par nuance quand la source la donne
  site/data/vie_politique/candidats/<scrutin>_<annee>.json  detail par candidat si AFFICHER_CANDIDATS
  data/processed/_restreint/vie_politique/<scrutin>_<annee>.json  detail par candidat (toujours, non versionne)

Regle personnes physiques : exception limitee aux candidats et elus, pour les comptes de campagne publies par la
CNCCFP ou au Journal officiel. Liste blanche de champs (CHAMPS_CANDIDAT) : ni adresse, ni date de naissance, ni
donateur, ni mandataire financier.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
LAKE_R = LAKE / "_restreint" / "politique"
LAKE_P = LAKE / "politique"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "vie_politique"
RESTREINT = ROOT / "data" / "processed" / "_restreint" / "vie_politique"

# Decision de l'utilisateur (16/11/2026) : les candidats sont nommes sur le site, dans la limite de la liste blanche.
AFFICHER_CANDIDATS = True
CHAMPS_CANDIDAT = ("candidat", "nuance", "parti", "circonscription", "tour", "elu", "depenses_eur", "recettes_eur",
                   "apport_personnel_eur", "dons_eur", "remboursement_eur", "decision", "reference")

HEADERS = {"User-Agent": "ou-vont-mes-impots/0.1 (projet citoyen open source)"}
ORG_CNCCFP = "534fff63a3a7292c64a77d67"
DATAGOUV = "https://www.data.gouv.fr/api/1"
ODS = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
TAILLE_MAX_SITE = 5 * 1024 * 1024
XPF_EUR = 1000 / 119.33  # parite fixe : 1 000 F CFP = 8,38 EUR


# --------------------------------------------------------------------------------------------------------------------
# Reseau : reprises exponentielles, aucun contournement d'un refus d'acces (401, 403, 451, defi Cloudflare)
# --------------------------------------------------------------------------------------------------------------------

class AccesRefuse(Exception):
    pass


def get(url: str, params: dict | None = None, tries: int = 5, timeout: int = 120, stream: bool = False):
    erreur = None
    for tentative in range(1, tries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout, stream=stream)
        except (requests.ConnectionError, requests.Timeout) as exc:
            erreur = exc
        else:
            if r.status_code < 400:
                return r
            if r.status_code in (401, 403, 451) or "cf-mitigated" in r.headers:
                raise AccesRefuse(f"HTTP {r.status_code}")
            if r.status_code != 429 and r.status_code < 500:
                raise AccesRefuse(f"HTTP {r.status_code}")
            if r.status_code == 429 and tentative >= 2:
                raise AccesRefuse("HTTP 429 (limite de debit, pas d'insistance)")
            erreur = f"HTTP {r.status_code}"
        if tentative < tries:
            time.sleep(min(2 ** tentative, 30))
    raise AccesRefuse(f"injoignable apres {tries} tentatives : {erreur}")


def telecharger(url: str, chemin: Path, taille_attendue: int | None = None) -> dict:
    """Telecharge vers chemin (ecriture atomique). Ne retelecharge pas un fichier present de meme taille."""
    if chemin.exists() and chemin.stat().st_size > 0 and (taille_attendue is None or chemin.stat().st_size == taille_attendue):
        return {"statut": "deja_present", "octets": chemin.stat().st_size, "sha256": _sha(chemin)}
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".part")
    for tentative in range(1, 6):  # coupures en cours de transfert : on recommence le fichier
        try:
            r = get(url, stream=True, timeout=300)
            ctype = r.headers.get("content-type", "")
            with open(tmp, "wb") as f:
                for bloc in r.iter_content(1 << 16):
                    f.write(bloc)
            break
        except (requests.exceptions.ChunkedEncodingError, requests.ConnectionError, requests.Timeout) as exc:
            if tentative == 5:
                raise AccesRefuse(f"transfert interrompu 5 fois : {exc}") from exc
            time.sleep(2 ** tentative)
    if "text/html" in ctype and chemin.suffix.lower() in (".pdf", ".csv", ".xlsx", ".ods", ".xls"):
        tmp.unlink()
        raise AccesRefuse(f"page HTML recue au lieu d'un fichier ({ctype})")
    tmp.replace(chemin)
    return {"statut": "telecharge", "octets": chemin.stat().st_size, "sha256": _sha(chemin)}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _nom_fichier(url: str, titre: str, fmt: str | None) -> str:
    base = url.rstrip("/").split("/")[-1].split("?")[0]
    if "download/pdf" in url or not re.search(r"\.[A-Za-z0-9]{2,4}$", base):
        base = re.sub(r"[^A-Za-z0-9]+", "_", _sans_accents(titre))[:80].strip("_") + "." + (fmt or "bin")
    return requests.utils.unquote(base)


def _ecrire_manifeste(dossier: Path, entrees: list[dict]) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "_manifeste.json").write_text(json.dumps(entrees, ensure_ascii=False, indent=1), encoding="utf-8")


def collecte_cnccfp(budget_s: int = 480) -> None:
    """Toutes les ressources des jeux de l'organisation CNCCFP. Comptes de campagne -> _restreint ; partis -> lake."""
    debut = time.time()
    jeux = get(f"{DATAGOUV}/organizations/{ORG_CNCCFP}/datasets/", {"page_size": 100}).json()["data"]
    print(f"{len(jeux)} jeux dans l'organisation CNCCFP")
    for jeu in jeux:
        partis = "partis" in jeu["slug"]
        dossier = (LAKE_P / "cnccfp_partis") if partis else (LAKE_R / "cnccfp" / jeu["slug"][:90])
        entrees = []
        for res in jeu["resources"]:
            if time.time() - debut > budget_s:
                print("budget de temps atteint : relancer la commande pour reprendre")
                _ecrire_manifeste(dossier, entrees)
                return
            nom = _nom_fichier(res["url"], res["title"], res.get("format"))
            e = {"jeu": jeu["slug"], "jeu_id": jeu["id"], "ressource": res["title"], "ressource_id": res["id"],
                 "url": res["url"], "fichier": nom, "modifie_amont": res.get("last_modified"),
                 "collecte_le": date.today().isoformat()}
            try:
                e.update(telecharger(res["url"], dossier / nom, res.get("filesize")))
            except AccesRefuse as exc:
                e.update({"statut": "refus_ou_echec", "detail": str(exc)})
            print(f"  [{e['statut']}] {jeu['slug'][:50]} / {nom}")
            entrees.append(e)
        if jeu["resources"]:
            _ecrire_manifeste(dossier, entrees)


PRESIDENTIELLES = {
    2012: {"url": "https://cnccfp.fr/wp-content/uploads/2022/04/cnccfp_presidentielle_2012_jo_20130130.pdf",
           "document": "JORF du 30 janvier 2013, textes 94 à 103 : publication des décisions de la CNCCFP du "
                       "19 décembre 2012 relatives aux comptes de campagne de l'élection présidentielle des 22 avril "
                       "et 6 mai 2012 (NOR CCCX1300001S), copie cnccfp.fr"},
    2017: {"url": "https://cnccfp.fr/wp-content/uploads/2022/04/De%CC%81cisions_pre%CC%81sidentielle_2017.pdf",
           "document": "JORF du 13 février 2018, textes 34 et suivants : publication des décisions de la CNCCFP du "
                       "21 décembre 2017 relatives aux comptes de campagne de l'élection présidentielle des 23 avril "
                       "et 7 mai 2017 (NOR CCCJ1803328V), copie cnccfp.fr"},
    2022: {"url": "https://cnccfp.fr/wp-content/uploads/2023/02/cnccfp-decisions-presidentielle-2022.pdf",
           "document": "JORF du 27 janvier 2023, textes 80 et suivants : décisions de la CNCCFP du 14 décembre 2022 "
                       "relatives aux comptes de campagne de l'élection présidentielle des 10 et 24 avril 2022, "
                       "copie cnccfp.fr"},
}
# Pages consultees pour trouver les PDF (traçabilite) ; la publication simplifiee au JO du 19/07/2022 est sur
# Legifrance, qui renvoie HTTP 403 aux clients automatises : non contourne.
PAGES_CNCCFP = [
    "https://cnccfp.fr/election-presidentielle-des-10-et-24-avril-2022-publication-au-journal-officiel-des-decisions-de-la-commission/",
    "https://cnccfp.fr/election-presidentielle-2022-publication-des-comptes-de-campagne-des-candidats/",
    "https://cnccfp.fr/?s=pr%C3%A9sidentielle",
]


def collecte_presidentielles() -> None:
    dossier = LAKE_R / "presidentielles"
    entrees = []
    for annee, d in PRESIDENTIELLES.items():
        e = {"annee": annee, "url": d["url"], "document": d["document"], "fichier": f"presidentielle_{annee}_decisions.pdf",
             "collecte_le": date.today().isoformat()}
        try:
            e.update(telecharger(d["url"], dossier / e["fichier"]))
        except AccesRefuse as exc:
            e.update({"statut": "refus_ou_echec", "detail": str(exc)})
        print(f"  [{e['statut']}] presidentielle {annee}")
        entrees.append(e)
    for url in PAGES_CNCCFP:
        nom = "page_" + hashlib.sha1(url.encode()).hexdigest()[:10] + ".html"
        e = {"url": url, "fichier": nom, "collecte_le": date.today().isoformat()}
        try:
            e.update(telecharger(url, dossier / nom))
        except AccesRefuse as exc:
            e.update({"statut": "refus_ou_echec", "detail": str(exc)})
        entrees.append(e)
    # Publication simplifiee 2022 (JO du 19 juillet 2022) : lien Legifrance donne par cnccfp.fr.
    url = "https://www.legifrance.gouv.fr/download/pdf?id=WEMso1qOCZh2qhuXAXmImQKF4sRY5i5EOB0AH67mhps="
    e = {"url": url, "fichier": "presidentielle_2022_publication_simplifiee_jo_20220719.pdf"}
    try:
        e.update(telecharger(url, dossier / e["fichier"]))
    except AccesRefuse as exc:
        e.update({"statut": "refus_ou_echec", "detail": str(exc) + " (Legifrance, non contourne)"})
    entrees.append(e)
    _ecrire_manifeste(dossier, entrees)
    for e in entrees:
        print(f"  [{e.get('statut')}] {e['url'][:100]}")


DOCS_P232 = {  # documents budgetaires publics qui comblent les trous de l'open data par action (2021, 2025)
    "an_plr2021_tome2.pdf": {
        "url": "https://www.assemblee-nationale.fr/dyn/16/rapports/cion_fin/l16b0016-tii_rapport-fond.pdf",
        "document": "Assemblée nationale, rapport n° 16 (XVIe lég.), tome II, sur le projet de loi de règlement 2021 "
                    "(commission des finances, 7 juillet 2022), mission AGTE"},
    "an_fiche_execution_agte_2022.pdf": {
        "url": "https://www.assemblee-nationale.fr/dyn/content/download/614170/file/Fiche%20ex%C3%A9cution%20-%20AGTE.pdf?version=1",
        "document": "Assemblée nationale, commission des finances, fiche d'exécution 2022 de la mission AGTE (PLR 2022)"},
    "rap2025_agte.pdf": {
        "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1109796/file/Administration_generale_territoriale_Etat_AB.pdf",
        "document": "Rapport annuel de performances 2025, mission « Administration générale et territoriale de l'État », "
                    "annexe au projet de loi relative aux résultats de la gestion 2025 (PLRG 2025)"},
}


def collecte_budget() -> None:
    """Execution du programme 232 par action absente de l'open data : 2021 (aucun PLR 2021 ni budget vert PLF 2023
    publie en donnees) et 2025 (PLRG 2025 publie par programme seulement). Documents parlementaires publics."""
    dossier = LAKE_P / "p232"
    entrees = []
    for nom, d in DOCS_P232.items():
        e = {"url": d["url"], "document": d["document"], "fichier": nom, "collecte_le": date.today().isoformat()}
        try:
            e.update(telecharger(d["url"], dossier / nom))
        except AccesRefuse as exc:
            e.update({"statut": "refus_ou_echec", "detail": str(exc)})
        print(f"  [{e['statut']}] {nom}")
        entrees.append(e)
    _ecrire_manifeste(dossier, entrees)


# --------------------------------------------------------------------------------------------------------------------
# Outils de lecture
# --------------------------------------------------------------------------------------------------------------------

def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))


def _cle(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _sans_accents(str(s)).lower()).strip()


def nombre(v) -> float | None:
    """'1 234,56', '1234.56', 1234, '' -> float ou None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "").replace(" ", "").replace("€", "")
    if s in ("", "-", "nan", "NaN", "None", "NC", "nc"):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def ecrire(chemin: Path, obj) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    if chemin.is_relative_to(SITE) and len(txt.encode()) > TAILLE_MAX_SITE:
        raise SystemExit(f"{chemin} depasse 5 Mo : decouper")
    chemin.write_text(txt, encoding="utf-8")


def arrondi(x):
    return None if x is None else round(float(x), 2)



def _texte_pdf(chemin: Path) -> list[str]:
    """Texte page par page (index 0 = page 1). Necessite pdfplumber."""
    import pdfplumber
    with pdfplumber.open(chemin) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def _decoder(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    raise ValueError("encodage inconnu")


def _lignes_tableau(chemin: Path) -> list[list[str]]:
    if chemin.suffix.lower() == ".csv":
        return [[c.strip() for c in r] for r in csv.reader(io.StringIO(_decoder(chemin.read_bytes())), delimiter=";")]
    import pandas as pd
    x = pd.read_excel(chemin, header=None, dtype=str)
    return [[("" if v is None or v != v else str(v)).strip() for v in r] for r in x.values.tolist()]


# --------------------------------------------------------------------------------------------------------------------
# Comptes de campagne : jeux CNCCFP (format commun « candidat ; nom ; scrutin ; ... ; RFE ; decision »)
# --------------------------------------------------------------------------------------------------------------------

D_CNCCFP = LAKE_R / "cnccfp"
SCRUTINS = [  # (cle, annee, libelle, dossier du jeu, fichiers ; [] = tous)
    ("legislatives", 2012, "Élections législatives des 10 et 17 juin 2012",
     "tableau-general-des-elections-legislatives-des-10-et-17-juin-2012", []),
    ("municipales", 2014, "Élections municipales des 23 et 30 mars 2014",
     "comptes-de-campagne-elections-municipales-des-23-et-30-mars-2014", []),
    ("europeennes", 2014, "Élection des représentants au Parlement européen du 25 mai 2014",
     "comptes-de-campagne-election-des-representants-au-parlement-europeen-du-25-mai-2014", []),
    ("senatoriales", 2014, "Élections sénatoriales du 28 septembre 2014",
     "comptes-de-campagne-elections-senatoriales-du-28-septembre-2014", []),
    ("departementales", 2015, "Élections départementales des 22 et 29 mars 2015",
     "comptes-de-campagne-elections-departementales-des-22-et-29-mars-2015-1", []),
    ("regionales", 2015, "Élections régionales des 6 et 13 décembre 2015",
     "elections-regionales-des-6-et-13-decembre-2015", []),
    ("partielles", 2016, "Élections partielles de 2016 (législatives, départementales, municipales)",
     None, ["comptes-de-campagne-elections-partielles-pour-lannee-2016", "comptes-de-campagne-elections-partielles-pour-lannee-2016-1",
            "comptes-de-campagne-elections-partielles-pour-lannee-2016-2"]),
    ("legislatives", 2017, "Élections législatives des 11 et 18 juin 2017",
     "comptes-de-campagne-elections-legislatives-des-11-et-18-juin-2017", []),
    ("senatoriales", 2017, "Élections sénatoriales du 24 septembre 2017",
     "comptes-de-campagne-elections-senatoriales-du-24-septembre-2017", []),
    ("territoriales_corse", 2017, "Élection des conseillers à l'Assemblée de Corse (décembre 2017)",
     "comptes-de-campagne-election-des-conseillers-a-lassemblee-de-corse-generale", []),
    ("europeennes", 2019, "Élection des représentants au Parlement européen du 26 mai 2019",
     "comptes-de-campagne-election-des-representants-au-parlement-europeen-du-26-mai-2019", []),
    ("municipales", 2020, "Élections municipales des 15 mars et 28 juin 2020",
     "comptes-de-campagne-elections-municipales-generales-des-15-mars-et-28-juin-2020", []),
    ("senatoriales", 2020, "Élections sénatoriales du 27 septembre 2020",
     "elections-senatoriales-des-27-septembre-2020-et-26-septembre-2021", ["sgmaj20.xlsx", "sgprop20.xlsx"]),
    ("senatoriales", 2021, "Élections sénatoriales partielles du 26 septembre 2021",
     "elections-senatoriales-des-27-septembre-2020-et-26-septembre-2021", ["sg21.xlsx"]),
    ("departementales", 2021, "Élections départementales des 20 et 27 juin 2021",
     "comptes-de-campagne-elections-aux-elections-departementales-des-20-et-27-juin-2021", []),
    ("regionales", 2021, "Élections régionales et assemblées de Corse, Guyane, Martinique des 20 et 27 juin 2021",
     "comptes-de-campagne-elections-aux-elections-regionales-et-des-conseillers-aux-assemblees-d", []),
    ("legislatives", 2022, "Élections législatives des 12 et 19 juin 2022",
     "comptes-de-campagne-elections-legislatives-generales-des-12-et-19-juin-2022", []),
    ("territoriales_saint_martin_saint_barthelemy", 2022, "Élections territoriales de Saint-Martin et Saint-Barthélemy (mars 2022)",
     "comptes-de-campagne-elections-territoriales-de-saint-martin-et-saint-barthelemy-des-20-et-", ["publications-2022-territoriales-v3.csv"]),
    ("partielles", 2022, "Élections partielles de 2022 (municipales, législatives, départementales)",
     "comptes-de-campagne-elections-territoriales-de-saint-martin-et-saint-barthelemy-des-20-et-",
     ["publications-2022-mp.csv", "publications-2022-lp.csv", "publications-2022-dp.csv"]),
    ("senatoriales", 2023, "Élections sénatoriales du 24 septembre 2023",
     "comptes-de-campagne-elections-senatoriales-generales-du-24-septembre-2023", []),
    ("europeennes", 2024, "Élection des représentants au Parlement européen du 9 juin 2024",
     "comptes-de-campagne-election-des-representants-au-parlement-europeen-des-8-et-9-juin-2024", []),
    ("legislatives", 2024, "Élections législatives anticipées des 30 juin et 7 juillet 2024",
     "elections-legislatives-generales-des-30-juin-et-7-juillet-2024", []),
]

DECISIONS = {  # codes publies par la CNCCFP ; les variantes (ARR, ARRR, *) sont conservees telles quelles
    "A": "approuvé", "AR": "approuvé après réformation", "AM": "approuvé, remboursement minoré",
    "ARM": "approuvé après réformation, remboursement minoré", "R": "rejeté", "AD": "absence de dépôt",
    "HD": "dépôt hors délai", "DD": "dispense de dépôt", "---": "non renseigné dans la source",
}


def libelle_decision(code: str) -> str:
    c = (code or "").replace("*", "").strip()
    if c in DECISIONS:
        return DECISIONS[c]
    if re.fullmatch(r"AR+M?", c):
        return "approuvé après réformation (variante de code de la source)" + (", remboursement minoré" if c.endswith("M") else "")
    return "code source non documenté" if c else "non renseigné"


def _categorie_decision(code: str) -> str:
    c = (code or "").replace("*", "").strip()
    if c.startswith("R"):
        return "rejete"
    if c == "AD":
        return "non_depose"
    if c == "HD":
        return "hors_delai"
    if c == "DD":
        return "dispense"
    if c.startswith("A"):
        return "approuve"
    return "autre"


def nom_candidat(brut: str, prenom: str = "") -> str:
    """Retire la civilite (donnee non necessaire) ; binomes « X et et Y » -> « X et Y »."""
    s = re.sub(r"\s+", " ", f"{brut} {prenom}".replace("\n", " ")).strip()
    s = re.sub(r"\b(MM|Mme|Mmes|Mlle|M)\.?\s+", "", s)
    s = re.sub(r"\bet( et)+\b", "et", s)
    return s.strip(" ,")


def _montant(v, monnaie: str = "EUR") -> float | None:
    x = nombre(v)
    if x is None:
        return None
    return x * XPF_EUR / 1000 if re.search(r"XPF|CFP", monnaie, re.I) else x


def lire_comptes_standard(chemin: Path) -> list[dict]:
    lignes = _lignes_tableau(chemin)
    h = next(i for i, r in enumerate(lignes[:25]) if any(c.strip().lower() == "candidat" for c in r))
    cols = [_cle(c) for c in lignes[h]]

    def idx(*noms):
        for n in noms:
            if n in cols:
                return cols.index(n)
        return None
    i = {k: idx(*v) for k, v in {
        "id": ["candidat"], "nom": ["nom"], "prenom": ["prenom"], "circ": ["circonscription"],
        "dep": ["departement"], "nuance": ["nuance"], "monnaie": ["monnaie"],
        "depenses": ["depenses totales retenues"], "recettes": ["recettes totales retenues"],
        "dons": ["dons retenus"], "apport_partis": ["apport retenu"], "apport_perso": ["apport personnel retenu"],
        "depenses_decl": ["depenses totales declarees"], "rfe": ["rfe"], "decision": ["decision"]}.items()}
    out = []
    for r in lignes[h + 1:]:
        if len(r) <= max(v for v in i.values() if v is not None) or not r[i["nom"]].strip():
            continue
        g = lambda k: r[i[k]] if i[k] is not None else ""  # noqa: E731
        monnaie = g("monnaie") or "EUR"
        circ = g("circ")
        dep = g("dep")
        if dep and _cle(dep) not in _cle(circ):
            circ = f"{circ} ({dep})"
        out.append({
            "candidat": nom_candidat(g("nom"), g("prenom")),
            "nuance": g("nuance") or None,
            "circonscription": circ or None,
            "depenses_eur": arrondi(_montant(g("depenses"), monnaie)),
            "recettes_eur": arrondi(_montant(g("recettes"), monnaie)),
            "apport_personnel_eur": arrondi(_montant(g("apport_perso"), monnaie)),
            "dons_eur": arrondi(_montant(g("dons"), monnaie)),
            "remboursement_eur": arrondi(_montant(g("rfe"), monnaie)),
            "decision": g("decision") or None,
            "_monnaie": monnaie,
        })
    return out


def lire_europeennes_2024(chemin: Path) -> list[dict]:
    """Tableau JO : une ligne « declare » nommee, suivie le cas echeant d'une ligne « retenu » sans nom."""
    lignes = _lignes_tableau(chemin)
    debut = next(i for i, r in enumerate(lignes) if r[0] and re.match(r"^[A-ZÀ-Ý][A-ZÀ-Ý' -]+ [A-ZÀ-Ýa-zà-ÿ]", r[0])
                 and i > 3)
    cands = []
    for r in lignes[debut:]:
        if len(r) < 18:
            continue
        if r[0].strip():
            cands.append([r])
        elif cands and any(x.strip() for x in r[1:]):
            cands[-1].append(r)
    out = []
    for groupe in cands:
        r = groupe[-1]
        nom = groupe[0][0].split("\n")[0]
        if not re.search(r"[a-zà-ÿ]", nom) or len(nom) > 60:
            continue  # notes de bas de tableau
        out.append({"candidat": nom_candidat(nom), "nuance": None, "circonscription": "Nationale",
                    "depenses_eur": arrondi(nombre(r[1])), "recettes_eur": arrondi(nombre(r[2])),
                    "dons_eur": arrondi(nombre(r[3])), "apport_personnel_eur": arrondi(nombre(r[7])),
                    "remboursement_eur": arrondi(nombre(r[16])), "decision": r[17] or None, "_monnaie": "EUR"})
    return out


def comptes_scrutin(cle: str, annee: int, dossier: str | None, fichiers: list[str]) -> tuple[list[dict], list[str]]:
    chemins: list[Path] = []
    if dossier is None:
        for d in fichiers:
            chemins += sorted(p for p in (D_CNCCFP / d).glob("*") if p.suffix.lower() in (".csv", ".xlsx"))
    else:
        base = D_CNCCFP / dossier
        chemins = [base / f for f in fichiers] if fichiers else sorted(
            p for p in base.glob("*") if p.suffix.lower() in (".csv", ".xlsx"))
    lus, sources = [], []
    for c in chemins:
        if not c.exists():
            continue
        lus += lire_europeennes_2024(c) if (cle == "europeennes" and annee == 2024) else lire_comptes_standard(c)
        sources.append(f"data.gouv.fr, organisation CNCCFP, jeu « {c.parent.name} », fichier {c.name}")
    return lus, sources


# --------------------------------------------------------------------------------------------------------------------
# Presidentielles : decisions de la CNCCFP publiees au Journal officiel (PDF)
# --------------------------------------------------------------------------------------------------------------------

NB = r"(\d[\d   ]*\d|\d)"


def _n(s: str) -> float:
    return float(re.sub(r"\D", "", s))


def _deux_nombres(jetons: list[str]) -> tuple[float, float] | None:
    """Colonnes « declare | retenu » fusionnees par l'extraction : '470 371 470 371', '449313 449371'."""
    if len(jetons) == 2:
        return _n(jetons[0]), _n(jetons[1])
    if len(jetons) % 2 == 0 and jetons[:len(jetons) // 2] == jetons[len(jetons) // 2:]:
        v = _n("".join(jetons[:len(jetons) // 2]))
        return v, v
    i = 1
    while i < len(jetons) - 1 and len(jetons[i]) == 3:
        i += 1
    if 0 < i < len(jetons) and all(len(t) == 3 for t in jetons[i + 1:]):
        return _n("".join(jetons[:i])), _n("".join(jetons[i:]))
    return None


def _apport_et_dons(avant: str, bloc: str) -> tuple[float | None, float | None]:
    apport = dons = None
    m = re.search(r"apport personnel pris en compte pour le remboursement forfaitaire par l.[ÉE]tat s.établit (?:ainsi )?à "
                  + NB + " euros", avant)
    segs = [x.start() for x in re.finditer(r"s.établit en recettes à", avant)]
    seg = avant[segs[-1]:segs[-1] + 700] if segs else ""
    if m:
        apport = _n(m.group(1))
    else:
        m = re.search(r"(?<![\d,])" + NB + r" euros d.apport personnel", seg)
        m2 = re.search(NB + r" euros de recettes perçues par l[ea] mandataire[^;]{0,40}correspondant en totalité à l.apport", seg)
        apport = _n(m.group(1)) if m else (_n(m2.group(1)) if m2 else None)
    m = re.search(r"(?<![\d,])" + NB + r" euros de dons", seg) or re.search(r"montant des dons s.élève à " + NB + " euros", avant)
    if m:
        dons = _n(m.group(1))
    else:
        t = re.search(r"dons des personnes (?:physiques)?[ .]*((?:\d+ )*\d+)", bloc)
        paire = _deux_nombres(t.group(1).split()) if t else None
        dons = paire[1] if paire else None
    return apport, dons


def lire_presidentielle(annee: int) -> tuple[list[dict], list[str]]:
    chemin = LAKE_R / "presidentielles" / f"presidentielle_{annee}_decisions.pdf"
    if not chemin.exists():
        return [], [f"PDF absent : {chemin.name} (lancer `collecte presidentielles`)"]
    pages = _texte_pdf(chemin)
    doc = PRESIDENTIELLES[annee]["document"]
    texte, debut_page = "", []
    for no, t in enumerate(pages, 1):
        debut_page.append((len(texte), no))
        texte += "\n" + t
    page_de = lambda pos: max(no for d, no in debut_page if d <= pos)  # noqa: E731
    plat = re.sub(r"\s+", " ", texte)
    # index de correspondance texte -> texte aplati (pour retrouver la page)
    blocs = list(re.finditer(r"Décision du (\d{1,2}\w* \w+ \d{4}) relative au compte de campagne de\s+(.+?)(?:,|\s+candidat)", texte, re.S))
    out, avert = [], []
    for k, m in enumerate(blocs):
        fin = blocs[k + 1].start() if k + 1 < len(blocs) else len(texte)
        b = re.sub(r"\s+", " ", texte[m.start():fin])
        nom = nom_candidat(re.sub(r"\s+", " ", m.group(2)))
        p_debut = page_de(m.start())
        art1 = re.search(r"Art\. 1er\.? ?[–−-] ?Le compte de campagne de .{0,80}? est (approuvé après réformation|approuvé|rejeté|réformé)(.{0,300})", b)
        decision = art1.group(1) if art1 else None
        dep = rec = None
        if art1:
            m1 = re.search(r"recettes à " + NB + r" euros et en dépenses à " + NB + " euros", art1.group(2))
            m2 = re.search(r"dépenses à " + NB + r" euros et en recettes à " + NB + " euros", art1.group(2))
            if m1:
                rec, dep = _n(m1.group(1)), _n(m1.group(2))
            elif m2:
                dep, rec = _n(m2.group(1)), _n(m2.group(2))
        a2 = re.search(r"Art\. 2\.? ?[–−-] ?Le montant (?:du remboursement )?dû par l.[ÉE]tat est arrêté à la somme (?:de )?" + NB + " euros", b)
        rembt = _n(a2.group(1)) if a2 else None
        avant = b[:art1.start()] if art1 else b
        apport, dons = _apport_et_dons(avant, b)
        pos_a2 = (texte.find("Art. 2", m.start()) if a2 else m.start())
        ref = f"{doc}, PDF {chemin.name}, décision p. {p_debut}" + (f", article 2 p. {page_de(pos_a2)}" if a2 else "")
        if decision is None or rembt is None or dep is None:
            avert.append(f"{annee} {nom} : extraction partielle (décision={decision}, dépenses={dep}, remboursement={rembt})")
        out.append({"candidat": nom, "nuance": None, "circonscription": "France entière",
                    "depenses_eur": dep, "recettes_eur": rec,
                    "apport_personnel_eur": apport, "dons_eur": dons,
                    "remboursement_eur": rembt, "decision": decision, "reference": ref})
    if annee == 2012 and "SARKOZY" in plat:
        avert.append("2012 : un dixième compte, rejeté par la CNCCFP le 19 décembre 2012 puis objet d'un recours, "
                     "n'est pas publié dans ce document (décision du Conseil constitutionnel n° 2013-156 PDR du "
                     "4 juillet 2013 : rejet confirmé, aucun remboursement). Non chiffré ici.")
    if annee == 2022:
        avert.append("2022 : une candidate a formé un recours devant le Conseil constitutionnel contre la décision de "
                     "la CNCCFP du 14 décembre 2022 la concernant ; le montant retenu ici est celui de la décision de la "
                     "CNCCFP (seule décision publiée séparément, d'après cnccfp.fr).")
    return out, avert


# --------------------------------------------------------------------------------------------------------------------
# Agregats par scrutin
# --------------------------------------------------------------------------------------------------------------------

def _somme(lignes, champ):
    v = [x[champ] for x in lignes if x.get(champ) is not None]
    return round(sum(v), 2) if v else None


def agreger(lignes: list[dict]) -> dict:
    cat = defaultdict(int)
    codes = defaultdict(int)
    for x in lignes:
        cat[_categorie_decision(x.get("decision") or "")] += 1
        codes[(x.get("decision") or "").strip() or "(vide)"] += 1
    return {
        "nombre_candidats": len(lignes),
        "nombre_comptes_avec_depenses": sum(1 for x in lignes if (x.get("depenses_eur") or 0) > 0),
        "depenses_totales_eur": _somme(lignes, "depenses_eur"),
        "recettes_totales_eur": _somme(lignes, "recettes_eur"),
        "apport_personnel_total_eur": _somme(lignes, "apport_personnel_eur"),
        "dons_totaux_eur": _somme(lignes, "dons_eur"),
        "remboursement_etat_total_eur": _somme(lignes, "remboursement_eur"),
        "comptes_rejetes": cat["rejete"],
        "comptes_non_deposes": cat["non_depose"],
        "comptes_hors_delai": cat["hors_delai"],
        "dispenses_de_depot": cat["dispense"],
        "decisions": {c: {"nombre": n, "libelle": libelle_decision(c)} for c, n in sorted(codes.items())},
    }


def tous_les_scrutins() -> list[dict]:
    res = []
    for cle, annee, libelle, dossier, fichiers in SCRUTINS:
        lignes, sources = comptes_scrutin(cle, annee, dossier, fichiers)
        if not lignes:
            print(f"  [absent] {cle} {annee}")
            continue
        res.append({"cle": cle, "annee": annee, "libelle": libelle, "lignes": lignes, "sources": sources,
                    "avertissements": [], "format": "CSV/XLSX CNCCFP (data.gouv.fr)"})
    for annee in sorted(PRESIDENTIELLES):
        lignes, avert = lire_presidentielle(annee)
        res.append({"cle": "presidentielle", "annee": annee,
                    "libelle": f"Élection présidentielle de {annee}", "lignes": lignes,
                    "sources": [PRESIDENTIELLES[annee]["document"] + " : " + PRESIDENTIELLES[annee]["url"]],
                    "avertissements": avert, "format": "PDF (Journal officiel), tableaux extraits par pdfplumber"})
    return res


# --------------------------------------------------------------------------------------------------------------------
# Aide publique aux partis (comptes des partis deposes a la CNCCFP)
# --------------------------------------------------------------------------------------------------------------------

D_PARTIS = LAKE_P / "cnccfp_partis"


def _fichier_partis(annee: int) -> Path | None:
    for p in sorted(D_PARTIS.glob("*")):
        if p.suffix.lower() in (".csv", ".xlsx", ".ods") and re.search(rf"exercice[-_]{annee}\b", p.name, re.I):
            return p
    return None


def aide_partis(annee: int) -> dict | None:
    """Aide publique de l'Etat (1re et 2de fraction) par parti, telle que portee dans les comptes deposes."""
    f = _fichier_partis(annee)
    if f is None:
        return None
    if f.suffix == ".csv":
        lignes = [[c.strip() for c in r] for r in csv.reader(io.StringIO(_decoder(f.read_bytes())), delimiter=";")]
        h = 0
        cols = [_cle(c) for c in lignes[0]]
    else:
        import pandas as pd
        x = pd.read_excel(f, header=None, dtype=str).fillna("")
        lignes = [[str(v).strip() for v in r] for r in x.values.tolist()]
        h = next(i for i, r in enumerate(lignes[:6]) if any(_cle(c) in ("nom parti", "nom du parti") for c in r))
        cols = [_cle(c) for c in lignes[h]]
        if annee <= 2017:  # libelles d'aide sur la ligne suivante
            cols = [_cle(a) or _cle(b) for a, b in zip(lignes[h], lignes[h + 1])]
            sous = [_cle(c) for c in lignes[h + 1]]
            cols = [s if ("fraction" in s or "financement public" in s) else c for c, s in zip(cols, sous)]
            h += 1
    i_code = next(i for i, c in enumerate(cols) if c in ("code cnccfp", "num parti", "n du parti", "n"))
    i_nom = next(i for i, c in enumerate(cols) if c in ("nom du parti", "nom parti"))
    i_unite = next((i for i, c in enumerate(cols) if c.startswith("unite monetaire")), None)
    i_f1 = next(i for i, c in enumerate(cols) if ("1ere fraction" in c or "premiere fraction" in c))
    i_f2 = next(i for i, c in enumerate(cols) if ("2nde fraction" in c or "deuxieme fraction" in c))
    i_tot = next((i for i, c in enumerate(cols) if c.startswith("financement public")), None)
    partis, ecarts = [], 0
    for r in lignes[h + 1:]:
        if len(r) <= max(i_f1, i_f2) or not r[i_nom].strip() or not re.match(r"^\d", r[i_code].strip() or "x"):
            continue
        conv = XPF_EUR / 1000 if i_unite is not None and re.search(r"cfp|xpf", r[i_unite], re.I) else 1.0
        f1, f2 = nombre(r[i_f1]) or 0.0, nombre(r[i_f2]) or 0.0
        tot_src = nombre(r[i_tot]) if i_tot is not None else None
        if tot_src and not (f1 or f2):
            f1 = tot_src  # anciens fichiers : total sans ventilation -> conserve en 1re fraction, signale
            ecarts += 1
        if f1 == 0 and f2 == 0:
            continue
        partis.append({"code_cnccfp": r[i_code].strip().split(".")[0], "nom": re.sub(r"\s+", " ", r[i_nom]).strip(),
                       "premiere_fraction_eur": round(f1 * conv, 2), "seconde_fraction_eur": round(f2 * conv, 2),
                       "total_eur": round((f1 + f2) * conv, 2)})
    partis.sort(key=lambda p: -p["total_eur"])
    return {"fichier": f.name, "partis": partis, "non_ventiles": ecarts}


# --------------------------------------------------------------------------------------------------------------------
# Programme 232 par action et par annee
# --------------------------------------------------------------------------------------------------------------------

ACTIONS = {"01": "financement_des_partis", "02": "organisation_des_elections", "03": "cnccfp"}
LIB_ACTIONS = {"financement_des_partis": "Financement des partis", "organisation_des_elections": "Organisation des élections",
               "cnccfp": "Commission nationale des comptes de campagne et des financements politiques"}
E = LAKE / "etat"


def _p232_parquet_2018() -> dict:
    import pandas as pd
    d = pd.read_parquet(E / "etat_plr_2018.parquet")
    bg = d[d.type_de_budget_hors_budgets_annexes == "BG"]
    s = bg[bg.code_programme.astype(str) == "232"].groupby("code_action")["exec_cp_2018_rap_2018"].sum()
    hors_rd = bg[~bg.mission.str.contains("Remboursements et dégrèvements", na=False)]["exec_cp_2018_rap_2018"].sum()
    return {"actions": {ACTIONS[k]: float(v) for k, v in s.items() if k in ACTIONS},
            "hors_perimetre": {"cultes_eur": float(s.get("04", 0)), "vie_associative_eur": float(s.get("05", 0))},
            "budget_general_cp_hors_rd_eur": float(hors_rd),
            "source": "data.economie.gouv.fr, PLR 2018, exécution par action (lac : etat/etat_plr_2018.parquet)",
            "millesime": "Exécution 2018 (PLR 2018)"}


def _p232_xls(annee: int) -> dict:
    import pandas as pd
    f = E / f"etat_plr_{annee}" / f"PLR{annee}-Credits_Destination_Nature.xls"
    d = pd.read_excel(f, dtype={"programme": str, "action": str, "mission": str})
    bg = d[d.typeBudget == "BG"]
    p = bg[bg.programme.astype(str).str.replace(".0", "", regex=False) == "232"]
    s = p.groupby(p.action.astype(str).str[-2:])["CP EXEC"].sum()
    hors_rd = bg[bg.mission.astype(str) != "RD"]["CP EXEC"].sum()
    return {"actions": {ACTIONS[k]: float(v) for k, v in s.items() if k in ACTIONS},
            "hors_perimetre": {"cultes_eur": float(s.get("04", 0)), "vie_associative_eur": float(s.get("05", 0))},
            "budget_general_cp_hors_rd_eur": float(hors_rd),
            "source": f"data.economie.gouv.fr, PLR {annee}, crédits par destination et nature (lac : etat/etat_plr_{annee}/{f.name})",
            "millesime": f"Exécution {annee} (PLR {annee})"}


BUDGETS_VERTS = {2022: ("economie__budgetvert_plf2024_opendata_vf.parquet", "execution_2022_cp", "code_action", "PLF 2024"),
                 2023: ("economie__plf25-budget-vert.parquet", "execution_2023_cp", "code_action", "PLF 2025"),
                 2024: ("etat_budget_vert_2026.parquet", "execution_2024_cp", "code_action_si_credit_budgetaire", "PLF 2026")}


def _p232_budget_vert(annee: int) -> dict:
    import pandas as pd
    f, col, col_action, plf = BUDGETS_VERTS[annee]
    d = pd.read_parquet(E / f)
    cb = d[d.type_depense == "Crédits budgétaires"]
    p = cb[cb.numero_programme == 232]
    s = p.groupby(p[col_action].astype(str))[col].sum()
    hors_rd = cb[~cb.mission.astype(str).str.contains("Remboursements et dégrèvements", na=False)][col].sum()
    non_ventile = float(p[~p[col_action].astype(str).str.match(r"232-0[1-3]")][col].sum())
    return {"actions": {ACTIONS[k[-2:]]: float(v) for k, v in s.items() if re.fullmatch(r"232-0[1-3]", k)},
            "non_ventile_par_action_eur": non_ventile,
            "budget_general_cp_hors_rd_eur": float(hors_rd),
            "source": f"data.economie.gouv.fr, budget vert {plf} (crédits budgétaires, CP exécutés {annee}, "
                      f"retraités au format {plf}) (lac : etat/{f})",
            "millesime": f"Exécution {annee} (budget vert {plf})"}


# Valeurs tirees de documents parlementaires (PDF) : chaque extrait est verifie dans le texte de la page citee.
FAITS_P232 = {
    2021: {"fichier": "an_plr2021_tome2.pdf", "page": 22,
           "verifier": ["L’aide publique aux partis a coûté 66,06 millions d’euros en 2021",
                        "10,1 millions d’euros en CP"],
           "actions": {"financement_des_partis": 66.06e6, "cnccfp": 10.1e6},
           "programme_total_eur": 366e6, "page_total": 21,
           "verifier_total": "371 millions d’euros en AE et 366 millions d’euros en CP",
           "cultes_eur": 2.1e6,
           "note": "Aucune exécution 2021 par action en open data (pas de jeu PLR 2021, pas de budget vert PLF 2023). "
                   "Programme (366 M€ CP, cultes compris), partis et CNCCFP lus dans le rapport ; « Organisation des "
                   "élections » estimée par différence (366 - 66,06 - 10,1 - 2,1 de cultes), arrondis du rapport."},
    2025: {"fichier": "rap2025_agte.pdf", "page": 106,
           "verifier": ["Total des crédits consommés 6 707 666 105 432 054 112 139 720 6 707 666 102 331 414 109 039 080",
                        "64 210 439 64 210 439 64 203 439 64 203 439",
                        "1 820 457 39 203 293 41 023 750 1 820 457 34 782 426 36 602 883",
                        "4 887 209 2 018 322 6 905 531 4 887 209 3 345 549 8 232 758"],
           "actions": {"financement_des_partis": 64203439.0, "organisation_des_elections": 36602883.0,
                       "cnccfp": 8232758.0},
           "note": "PLRG 2025 publié en open data par programme seulement : exécution par action lue dans le RAP 2025."},
}


def _verifie(fichier: str, page: int, extraits: list[str]) -> bool:
    chemin = LAKE_P / "p232" / fichier
    if not chemin.exists():
        return False
    t = re.sub(r"\s+", " ", _texte_pdf(chemin)[page - 1])
    return all(re.sub(r"\s+", " ", x) in t for x in extraits)


def p232_par_annee() -> dict[int, dict]:
    res: dict[int, dict] = {}
    for annee, fn in [(2018, _p232_parquet_2018), (2019, lambda: _p232_xls(2019)), (2020, lambda: _p232_xls(2020))]:
        try:
            res[annee] = fn()
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"  p232 {annee} indisponible : {exc}")
    for annee in BUDGETS_VERTS:
        try:
            res[annee] = _p232_budget_vert(annee)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"  p232 {annee} indisponible : {exc}")
    docs = {k: v["document"] for k, v in DOCS_P232.items()}
    f = FAITS_P232[2021]
    if _verifie(f["fichier"], f["page"], f["verifier"]) and _verifie(f["fichier"], f["page_total"], [f["verifier_total"]]):
        a = dict(f["actions"])
        a["organisation_des_elections"] = round(f["programme_total_eur"] - sum(a.values()) - f["cultes_eur"], 2)
        res[2021] = {"actions": a, "estimations": ["organisation_des_elections"],
                     "programme_total_publie_eur": f["programme_total_eur"],
                     "hors_perimetre": {"cultes_eur": f["cultes_eur"]},
                     "source": f"{docs[f['fichier']]}, p. {f['page_total']} et {f['page']}",
                     "millesime": "Exécution 2021 (PLR 2021, rapport parlementaire)", "note": f["note"]}
    f = FAITS_P232[2025]
    if _verifie(f["fichier"], f["page"], f["verifier"]):
        res[2025] = {"actions": dict(f["actions"]), "source": f"{docs[f['fichier']]}, p. {f['page']}",
                     "millesime": "Exécution 2025 (PLRG 2025, RAP)", "note": f["note"]}
        try:
            plrg = (E / "etat_plrg_2025" / "Annexe1-Etat_CP-2025.csv").read_bytes()
            rows = list(csv.DictReader(io.StringIO(_decoder(plrg)), delimiter=";"))
            res[2025]["budget_general_cp_hors_rd_eur"] = sum(
                nombre(r["Depenses_constatees"]) or 0 for r in rows if "Remboursements et dégrèvements" not in r["Mission"])
            p232 = sum(nombre(r["Depenses_constatees"]) or 0 for r in rows if r["Programme"].endswith("- 232"))
            res[2025]["controle_plrg_programme_eur"] = round(p232, 2)
        except (FileNotFoundError, KeyError):
            pass
    for a, d in res.items():
        d["programme_232_actions_01_03_eur"] = round(sum(d["actions"].values()), 2)
        d["actions"] = {k: round(v, 2) for k, v in d["actions"].items()}
    return res


# --------------------------------------------------------------------------------------------------------------------
# Production des fichiers
# --------------------------------------------------------------------------------------------------------------------

ANNEES = range(2012, 2026)
CHAMPS_PUBLIES = ("candidat", "nuance", "circonscription", "depenses_eur", "recettes_eur", "apport_personnel_eur",
                  "dons_eur", "remboursement_eur", "decision", "reference")


def _ligne_publiee(x: dict) -> dict:
    """Liste blanche stricte : rien d'autre que nom, nuance, circonscription, montants, decision (et la reference
    documentaire des chiffres extraits d'un PDF)."""
    return {k: x.get(k) for k in CHAMPS_PUBLIES if x.get(k) is not None}


def _par_nuance(lignes: list[dict]) -> list[dict] | None:
    if not any(x.get("nuance") for x in lignes):
        return None
    g = defaultdict(list)
    for x in lignes:
        g[x.get("nuance") or "(non renseignée)"].append(x)
    res = []
    for n, ls in g.items():
        a = agreger(ls)
        res.append({"nuance": n, **{k: a[k] for k in ("nombre_candidats", "depenses_totales_eur", "apport_personnel_total_eur",
                                                     "dons_totaux_eur", "remboursement_etat_total_eur", "comptes_rejetes")}})
    res.sort(key=lambda r: -(r["remboursement_etat_total_eur"] or 0))
    return res


def produire() -> None:
    aujourd_hui = date.today().isoformat()
    SORTIE.mkdir(parents=True, exist_ok=True)
    for sous in ("scrutins", "partis", "candidats"):
        for f in (SORTIE / sous).glob("*.json"):
            f.unlink()
    for f in RESTREINT.glob("*.json"):
        f.unlink()

    # 1. Scrutins
    scrutins = tous_les_scrutins()
    index_scrutins = []
    for s in scrutins:
        cle_f = f"{s['cle']}_{s['annee']}"
        a = agreger(s["lignes"])
        obj = {"millesime": f"{s['libelle']} (comptes arrêtés par la CNCCFP)",
               "source": " ; ".join(s["sources"]), "format_source": s["format"], "collecte_le": aujourd_hui,
               "unite": "euros", "scrutin": s["cle"], "annee": s["annee"], "libelle": s["libelle"], **a,
               "par_nuance": _par_nuance(s["lignes"]),
               "definitions": {"depenses_totales_eur": "dépenses retenues par la CNCCFP",
                               "remboursement_etat_total_eur": "remboursement forfaitaire de l'État (RFE) arrêté par la CNCCFP",
                               "apport_personnel_total_eur": "apport personnel des candidats retenu par la CNCCFP"},
               "avertissements": s["avertissements"] + [
                   "Montants arrêtés par scrutin ; le paiement par l'État intervient l'année du scrutin ou la suivante.",
                   *(["Montants en francs CFP convertis en euros (1 000 F CFP = 8,38 €)."]
                     if any(re.search("XPF|CFP", x.get("_monnaie", "")) for x in s["lignes"]) else [])]}
        if obj["par_nuance"] is None:
            obj.pop("par_nuance")
            obj["avertissements"].append("La source ne donne ni nuance ni parti pour ce scrutin.")
        ecrire(SORTIE / "scrutins" / f"{cle_f}.json", obj)
        detail = {"millesime": obj["millesime"], "source": obj["source"], "unite": "euros", "scrutin": s["cle"],
                  "annee": s["annee"], "champs": list(CHAMPS_PUBLIES),
                  "candidats": [_ligne_publiee(x) for x in s["lignes"]]}
        RESTREINT.mkdir(parents=True, exist_ok=True)
        (RESTREINT / f"{cle_f}.json").write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
        if AFFICHER_CANDIDATS:
            detail["regle"] = ("Exception limitée aux candidats, pour les comptes de campagne publiés par la CNCCFP ou "
                               "au Journal officiel : nom, nuance, circonscription, montants, décision. Ni adresse, ni "
                               "date de naissance, ni donateur, ni mandataire financier.")
            ecrire(SORTIE / "candidats" / f"{cle_f}.json", detail)
        index_scrutins.append({"fichier": f"scrutins/{cle_f}.json", "scrutin": s["cle"], "annee": s["annee"],
                               "libelle": s["libelle"], "nombre_candidats": a["nombre_candidats"],
                               "remboursement_etat_total_eur": a["remboursement_etat_total_eur"],
                               "depenses_totales_eur": a["depenses_totales_eur"]})

    # 2. Partis
    partis_annee = {}
    for annee in range(2008, 2026):
        r = aide_partis(annee)
        if not r or not r["partis"]:
            continue
        tot1 = round(sum(p["premiere_fraction_eur"] for p in r["partis"]), 2)
        tot2 = round(sum(p["seconde_fraction_eur"] for p in r["partis"]), 2)
        obj = {"millesime": f"Comptes des partis, exercice {annee}",
               "source": f"data.gouv.fr, organisation CNCCFP, jeu « comptes-des-partis-et-groupements-politiques », "
                         f"fichier {r['fichier']}", "collecte_le": aujourd_hui, "unite": "euros", "exercice": annee,
               "definition": "Aide publique de l'État (1re fraction : résultats aux législatives ; 2de fraction : "
                             "parlementaires rattachés), telle que portée dans les comptes déposés par chaque parti. "
                             "Personnes morales.",
               "nombre_partis_beneficiaires": len(r["partis"]),
               "total_premiere_fraction_eur": tot1, "total_seconde_fraction_eur": tot2,
               "total_eur": round(tot1 + tot2, 2), "partis": r["partis"], "avertissements": []}
        if r["non_ventiles"]:
            obj["avertissements"].append(f"{r['non_ventiles']} parti(s) sans ventilation par fraction dans la source : "
                                         "total porté en 1re fraction.")
        ecrire(SORTIE / "partis" / f"{annee}.json", obj)
        partis_annee[annee] = obj

    # 3. Annees
    p232 = p232_par_annee()
    rembt = defaultdict(list)
    for s in index_scrutins:
        rembt[s["annee"]].append({"scrutin": s["scrutin"], "libelle": s["libelle"],
                                  "remboursement_etat_total_eur": s["remboursement_etat_total_eur"],
                                  "fichier": s["fichier"]})
    annees, controles = [], []
    for annee in ANNEES:
        a = {"annee": annee}
        d = p232.get(annee)
        if d:
            total = d["programme_232_actions_01_03_eur"]
            a["programme_232"] = {"millesime": d["millesime"], "source": d["source"],
                                  "actions_eur": d["actions"], "total_actions_01_a_03_eur": total,
                                  **({"estimations": d["estimations"]} if d.get("estimations") else {}),
                                  **({"note": d["note"]} if d.get("note") else {}),
                                  **({"hors_perimetre_eur": d["hors_perimetre"]} if d.get("hors_perimetre") else {}),
                                  **({"non_ventile_par_action_eur": round(d["non_ventile_par_action_eur"], 2)}
                                     if d.get("non_ventile_par_action_eur") else {}),
                                  **({"controle_plrg_programme_eur": d["controle_plrg_programme_eur"]}
                                     if d.get("controle_plrg_programme_eur") else {})}
            den = d.get("budget_general_cp_hors_rd_eur")
            if den:
                a["programme_232"]["euros_sur_100_euros_etat"] = round(100 * total / den, 4)
                a["programme_232"]["denominateur_eur"] = round(den, 2)
                a["programme_232"]["denominateur"] = ("dépenses du budget général, CP exécutés, hors mission "
                                                      "« Remboursements et dégrèvements », même source que l'année")
        else:
            a["programme_232"] = None
            a["programme_232_manquant"] = ("aucune exécution par action en open data pour cette année" if annee < 2018
                                           else "source absente du lac")
        pa = partis_annee.get(annee)
        a["aide_publique_partis"] = ({"total_eur": pa["total_eur"], "premiere_fraction_eur": pa["total_premiere_fraction_eur"],
                                      "seconde_fraction_eur": pa["total_seconde_fraction_eur"],
                                      "nombre_partis": pa["nombre_partis_beneficiaires"], "fichier": f"partis/{annee}.json",
                                      "source": pa["source"]} if pa else None)
        a["remboursements_campagne"] = rembt.get(annee, [])
        a["remboursements_campagne_total_eur"] = round(sum(r["remboursement_etat_total_eur"] or 0 for r in rembt.get(annee, [])), 2)
        org = (d or {}).get("actions", {}).get("organisation_des_elections")
        if org is not None and a["remboursements_campagne"]:
            ok = a["remboursements_campagne_total_eur"] <= org
            controles.append({"annee": annee, "remboursements_eur": a["remboursements_campagne_total_eur"],
                              "organisation_des_elections_eur": org, "coherent": ok})
        elif a["remboursements_campagne"]:
            controles.append({"annee": annee, "remboursements_eur": a["remboursements_campagne_total_eur"],
                              "organisation_des_elections_eur": None, "coherent": None,
                              "note": "exécution de l'action « Organisation des élections » indisponible pour cette année"})
        if pa and d and d["actions"].get("financement_des_partis"):
            a["ecart_aide_partis_comptes_vs_budget_eur"] = round(pa["total_eur"] - d["actions"]["financement_des_partis"], 2)
        annees.append(a)
    obj = {"millesime": f"Exécutions 2018 à 2025 ; comptes de campagne 2012 à 2024 ; comptes des partis 2012 à 2024",
           "source": "Programme 232 « Vie politique » : PLR 2018 à 2020 et budgets verts PLF 2024 à 2026 "
                     "(data.economie.gouv.fr), rapports parlementaires pour 2021 et 2025 ; comptes de campagne et comptes "
                     "des partis : CNCCFP (data.gouv.fr) ; présidentielles : décisions CNCCFP publiées au Journal officiel",
           "collecte_le": aujourd_hui, "unite": "euros",
           "perimetre": "Actions 01 à 03 du programme 232 (les cultes et la vie associative, rattachés au programme "
                        "jusqu'en 2021, sont exclus et signalés).",
           "annees": annees, "controle_remboursements_vs_organisation_des_elections": controles,
           "trous": ["Programme 232 par action avant 2018 : pas de données d'exécution par action collectées.",
                     "2021 : pas de PLR 2021 ni de budget vert PLF 2023 en open data ; valeurs lues dans le rapport "
                     "de l'Assemblée nationale sur le PLR 2021, « Organisation des élections » estimée par différence.",
                     "2022 : PLR 2022 absent de l'open data ; exécution prise dans le budget vert du PLF 2024.",
                     "2025 : PLRG 2025 publié par programme seulement ; actions lues dans le RAP 2025.",
                     "Présidentielle 2012 : le compte rejeté (recours, Conseil constitutionnel n° 2013-156 PDR) est "
                     "absent du document publié au JO ; 9 candidats sur 10 chiffrés.",
                     "Publication simplifiée des comptes présidentiels 2022 (JO du 19 juillet 2022) : Legifrance "
                     "refuse l'accès automatisé (HTTP 403), non contourné ; les décisions CNCCFP suffisent."],
           "scrutins": index_scrutins}
    ecrire(SORTIE / "annees.json", obj)
    print(f"{len(index_scrutins)} scrutins, {len(partis_annee)} exercices de partis, {len(annees)} années")
    for c in controles:
        print("  controle", c)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("collecte")
    c.add_argument("quoi", choices=["cnccfp", "presidentielles", "budget", "tout"])
    sp.add_parser("produire")
    a = ap.parse_args()
    if a.cmd == "collecte":
        for q in (["cnccfp", "presidentielles", "budget"] if a.quoi == "tout" else [a.quoi]):
            {"cnccfp": collecte_cnccfp, "presidentielles": collecte_presidentielles, "budget": collecte_budget}[q]()
    else:
        produire()


if __name__ == "__main__":
    main()
