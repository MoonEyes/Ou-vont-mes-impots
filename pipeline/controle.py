"""Contrôle, influence, aides aux entreprises : ce que disent les juridictions financières, qui fait du lobbying
déclaré auprès de quel ministère, et combien représentent les aides publiques aux entreprises selon chaque étude.

Entrées :
  ccomptes.fr : plan du site des publications (sitemap_publication, ~38 500 pages) puis chaque page publique
                (métadonnées JSON-LD schema.org, type et lien PDF du document principal) ; collecte reprenable, cache
                data/lake/_cache/ccomptes/publications.jsonl (métadonnées seulement, jamais le texte des réponses)
  data/lake/_cache/ccomptes/budget_etat_<annee>.html (pipeline/realisations.py) : notes d'exécution budgétaire (NEB)
  data/lake/_restreint/politique/politique_hatvp_lobbying_csv.zip : répertoire des représentants d'intérêts (HATVP,
                vues séparées CSV) ; seules les vues sans personne physique sont lues (1, 7, 9, 10, 13, 15)
  site/data/realisations/index.json + realisations/<programme>.json (programmes, missions, NEB vérifiées)
  site/data/beneficiaires/programme_<n>.json (opérateurs), site/data/local/geo/<dep>.json (communes, EPCI)
  site/data/beneficiaires/index.json, france2030.json (rapprochement des aides nommées, sans copie)
  data/lake/aides_entreprises/aides_urssaf_exos_champ_large_par_grandes_categories.parquet (exonérations Urssaf)
  API Recherche d'entreprises (pipeline/sirene.py) : catégorie juridique des organisations HATVP

Sorties (site/data/controle/, chaque fichier < 5 Mo) :
  index.json                     comptes, couverture, sources, sources inaccessibles, recherche publique
  publications/programmes.json   publications de la Cour reliées aux programmes LOLF (titre, mission, opérateur), NEB
  publications/collectivites/<dep>.json  publications des CRC reliées aux communes, EPCI, département, région
  publications/autres.json       publications non rattachées (comptes par juridiction et par type)
  lobbying/organisations.json    organisations inscrites (personnes morales), dépenses déclarées, domaines, ministères
  lobbying/ministeres.json       actions déclarées par ministère ciblé et par domaine, missions LOLF rattachées
  aides_entreprises.json         estimations publiées (périmètre, année, type, source) et données du site reliées

Commandes :
  python pipeline/controle.py collecter --budget 1800   # réseau, reprenable (ccomptes.fr puis SIRENE HATVP)
  python pipeline/controle.py produire                  # sans réseau

Personnes : aucune personne physique n'est nommée. Pages ccomptes.fr : on ne garde ni les titres des réponses
(« Réponse de M. ... »), ni un résumé contenant une civilité. HATVP : vues dirigeants, collaborateurs, clients,
affiliations et observations jamais lues ; responsables publics visés réduits au ministère ou à l'institution ;
organisation nommée seulement si sa catégorie juridique est 2xxx à 9xxx (sirene.personne_morale), sinon agrégée.
Déclarations de patrimoine et d'intérêts de la HATVP : exclues.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import sys
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402

LAKE = ROOT / "data" / "lake"
CACHE_CC = LAKE / "_cache" / "ccomptes"
PUBS = CACHE_CC / "publications.jsonl"
SITEMAP = CACHE_CC / "sitemap_publication.xml"
HATVP_ZIP = LAKE / "_restreint" / "politique" / "politique_hatvp_lobbying_csv.zip"
URSSAF_EXOS = LAKE / "aides_entreprises" / "aides_urssaf_exos_champ_large_par_grandes_categories.parquet"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "controle"
CC = "https://www.ccomptes.fr"
UA = {"User-Agent": "ou-vont-mes-impots/0.1 (projet citoyen open source)"}
MAX_OCTETS = 5_000_000


# --- Utilitaires ---------------------------------------------------------------------------------------------------


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse 5 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")
    return n


def propre(v) -> str:
    if v is None:
        return ""
    s = html.unescape(str(v))
    s = unicodedata.normalize("NFC", s).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def norm(s) -> str:
    s = propre(s).lower().replace("’", "'").replace("œ", "oe")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def contient(texte_norm: str, nom: str) -> bool:
    n = norm(nom)
    return bool(n) and re.search(rf"(^| ){re.escape(n)}( |$)", texte_norm) is not None


# Civilité, ou prénom + NOM en capitales : le texte est écarté (jamais publié).
CIVILITE = re.compile(r"(?<![\w.])(M\.|MM\.|Mme|Mmes|Mlle|Monsieur|Madame|Mademoiselle|Dr\.?|Me)\s+[A-ZÉÈÀ]")
PRENOM_NOM = re.compile(r"\b[A-ZÉ][a-zéèëï\-]+\s+[A-ZÉÈ]{2,}(?:[\s\-][A-ZÉÈ]{2,})*\b")


def texte_sans_personne(s: str | None) -> str | None:
    s = propre(s)
    if not s:
        return None
    if CIVILITE.search(s) or PRENOM_NOM.search(s):
        return None
    return s


def http_get(url: str, tries: int = 4, timeout: int = 60):
    """GET poli. Un 403 ou un 429 n'est jamais contourné : il est renvoyé tel quel à l'appelant."""
    import requests
    err = None
    for i in range(tries):
        try:
            r = requests.get(url, timeout=timeout, headers=UA, allow_redirects=True)
            if r.status_code in (403, 429):
                return r
            if r.status_code < 500:
                return r
            err = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001 (réseau)
            err = type(exc).__name__
        time.sleep(min(2 ** i, 20))
    raise RuntimeError(f"{url} injoignable : {err}")


# --- 1. Contrôle : collecte ccomptes.fr ----------------------------------------------------------------------------

TYPES_CONNUS = re.compile(
    r"^(rapport|synth[eè]se|r[ée]f[ée]r[ée]|avis|jugement|arr[eê]t|note|communication|insertion|observations|lettre|"
    r"certification|enqu[eê]te|cahier|contr[ôo]le|recommandation|d[ée]lib[ée]r|ordonnance|r[ée]quisitoire|audit|"
    r"[ée]valuation|analyse|fascicule|annexe|tome|chapitre|d[ée]cision|rod|rapport d'observations)", re.I)


def extraire_page(url: str, t: str) -> dict:
    """Métadonnées d'une page publication : JSON-LD (titre, thèmes, juridiction, date, résumé), documents PDF typés."""
    out = {"url": url, "statut": 200}
    m = re.search(r'application/ld\+json[^>]*>(.*?)</script>', t, re.S)
    art = {}
    if m:
        try:
            g = json.loads(m.group(1)).get("@graph", [])
            art = next((x for x in g if x.get("@type") == "Article"), {})
        except json.JSONDecodeError:
            art = {}
    out["titre"] = propre(art.get("headline")) or None
    about = [propre(a) for a in art.get("about") or []]
    jur = [a for a in about if a.isupper() or re.match(r"^(CRC|CTC|CRTC|COUR )", a)]
    out["juridiction"] = jur[-1] if jur else None
    out["themes"] = [a for a in about if a not in jur]
    out["date"] = (art.get("datePublished") or "")[:10] or None
    out["resume"] = propre(art.get("description")) or None
    node = re.search(r'"currentPath":"node\\/(\d+)"', t)
    out["node"] = int(node.group(1)) if node else None
    docs = []
    for href, titre in re.findall(r'class="doc-type-icon"><a href="([^"]+)" title="([^"]+)"', t):
        titre = propre(titre)
        if titre.lower().startswith("réponse") or titre.lower().startswith("reponse"):
            continue
        docs.append({"type": titre, "url": href if href.startswith("http") else CC + href})
    out["documents"] = docs[:60]
    d = re.search(r"Date de communicabilit[ée]\s*:\s*(\d{2})\.(\d{2})\.(\d{4})", re.sub(r"<[^>]+>", " ", t))
    out["date_communicabilite"] = f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None
    return out


def urls_sitemap(rafraichir: bool = False) -> list[tuple[str, str]]:
    if rafraichir or not SITEMAP.exists():
        try:
            r = http_get(f"{CC}/sitemap_publication/sitemap.xml", tries=2, timeout=120)
            ok = r.status_code == 200 and "<urlset" in r.text[:2000]
        except RuntimeError:
            ok = False
        if ok:
            SITEMAP.parent.mkdir(parents=True, exist_ok=True)
            SITEMAP.write_text(r.text, encoding="utf-8")
        elif not SITEMAP.exists():
            raise RuntimeError("plan du site ccomptes.fr indisponible (non contourné)")
    t = SITEMAP.read_text(encoding="utf-8")
    return re.findall(r"<loc>([^<]+)</loc>\s*(?:<xhtml:link[^>]*/>\s*)*<lastmod>([^<]+)</lastmod>", t)


def charger_pubs() -> dict:
    out = {}
    if PUBS.exists():
        for ligne in PUBS.read_text(encoding="utf-8").splitlines():
            if ligne.strip():
                try:
                    x = json.loads(ligne)
                except json.JSONDecodeError:
                    continue
                out[x["url"]] = x
    return out


def collecter_ccomptes(budget_s: float, paralleles: int = 2, pause_s: float = 1.0, max_echecs: int = 5) -> None:
    """Pages de publication, les plus récemment modifiées d'abord ; s'arrête au budget, au premier 403/429 ou après
    `max_echecs` erreurs serveur (5xx, délai dépassé) consécutives : serveur indisponible, on n'insiste pas."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    urls = urls_sitemap(rafraichir=True)
    deja = charger_pubs()
    a_faire = [u for u, _ in sorted(urls, key=lambda x: x[1], reverse=True)
               if u not in deja or deja[u].get("statut") not in (200, 404)]
    print(f"  ccomptes.fr : {len(urls)} pages au plan du site, {len(deja)} en cache, {len(a_faire)} à lire",
          file=sys.stderr)
    debut, verrou, prochain, arret = time.monotonic(), threading.Lock(), [time.monotonic()], [None]
    echecs = [0]
    f = PUBS.open("a", encoding="utf-8")

    def tache(u):
        if arret[0] or time.monotonic() - debut > budget_s:
            return
        with verrou:
            attente = prochain[0] - time.monotonic()
            prochain[0] = max(prochain[0], time.monotonic()) + pause_s
        if attente > 0:
            time.sleep(attente)
        try:
            r = http_get(u, tries=2, timeout=30)
        except RuntimeError as exc:
            with verrou:
                echecs[0] += 1
                if echecs[0] >= max_echecs:
                    arret[0] = f"{max_echecs} erreurs serveur consécutives ({exc}) : collecte arrêtée"
            return
        echecs[0] = 0
        if r.status_code in (403, 429):
            arret[0] = f"HTTP {r.status_code} sur {u} : collecte arrêtée, non contournée"
            return
        x = extraire_page(u, r.text) if r.status_code == 200 else {"url": u, "statut": r.status_code}
        x["lu_le"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with verrou:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
            f.flush()

    with ThreadPoolExecutor(paralleles) as ex:
        list(ex.map(tache, a_faire))
    f.close()
    if arret[0]:
        print(f"  {arret[0]}", file=sys.stderr)
        (CACHE_CC / "refus.json").write_text(json.dumps({"motif": arret[0], "le": datetime.now(timezone.utc)
                                                         .isoformat()}, ensure_ascii=False), encoding="utf-8")
    print(f"  ccomptes.fr : {len(charger_pubs())} pages en cache", file=sys.stderr)


# --- 2. Influence : collecte (catégorie juridique des organisations HATVP) ----------------------------------------

HATVP_JSON = LAKE / "_restreint" / "politique" / "politique_hatvp_lobbying_json.json"
CACHE_SIRENE = LAKE / "_cache" / "recherche_entreprises_controle.json"


def charger_sirene() -> dict:
    """Cache propre à ce module (évite d'écraser le cache partagé écrit en parallèle par d'autres modules), complété
    par le cache partagé de pipeline/sirene.py en lecture seule."""
    c = sirene.charger_cache()
    if CACHE_SIRENE.exists():
        c.update(json.loads(CACHE_SIRENE.read_text(encoding="utf-8")))
    return c


def charger_hatvp() -> list[dict]:
    return json.loads(HATVP_JSON.read_text(encoding="utf-8"))["publications"]


def resoudre_hatvp(budget_s: float) -> None:
    sirens = [p["identifiantNational"] for p in charger_hatvp() if p.get("typeIdentifiantNational") == "SIREN"]
    ancien = sirene.CACHE
    sirene.CACHE = CACHE_SIRENE
    try:
        cache, restants = sirene.resoudre(sirens, budget_s=budget_s, cache=charger_sirene())
    finally:
        sirene.CACHE = ancien
    print(f"  HATVP : {len(set(sirens)) - restants}/{len(set(sirens))} SIREN résolus, {restants} restants",
          file=sys.stderr)


# --- 1. Contrôle : production ----------------------------------------------------------------------------------------

META_ROD = LAKE / "controle" / "controle_crc_rod_metadonnees.xlsx"
PUBS_2011_2016 = LAKE / "controle" / "controle_ccomptes_publications_2011_2016.csv"
URL_META_ROD = ("https://www.data.gouv.fr/fr/datasets/rapports-dobservations-definitives-des-chambres-regionales-"
                "des-comptes-crc-et-reponses-associees-1/")
URL_ROD_ZIP = ("https://static.data.gouv.fr/resources/rapports-dobservations-definitives-des-chambres-regionales-des-"
               "comptes-crc-et-reponses-associees-1/{horo}/rod-{annee}.zip")
HORO_ROD = {2015: "20200122-192632", 2016: "20200122-192703", 2017: "20200122-192732", 2018: "20200122-192759",
            2019: "20200122-192823"}
URL_PUBS_2011_2016 = ("https://www.data.gouv.fr/fr/datasets/publications-de-la-cour-des-comptes-par-type-et-date-de-"
                      "publication-2011-2016/")
SRC_META_ROD = ("data.gouv.fr, Cour des comptes, « Rapports d'observations définitives des chambres régionales des "
                "comptes (CRC) et réponses associées », métadonnées meta-rod-datasession.xlsx (rapports 2015 à 2019)")
SRC_PUBS = ("data.gouv.fr, Cour des comptes, « Publications de la Cour des comptes, par type et date de publication "
            "(2011-2016) »")
SRC_PAGES = "ccomptes.fr, pages des publications (métadonnées schema.org) listées par sitemap_publication"
SRC_NEB = ("ccomptes.fr, pages « Le budget de l'État en <année> », notes d'exécution budgétaire vérifiées (HTTP 200) par "
           "pipeline/realisations.py (site/data/realisations/<programme>.json, bloc evaluations)")
MOIS = {m: i for i, m in enumerate(["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
                                     "septembre", "octobre", "novembre", "decembre"], 1)}
MONTANT_RE = re.compile(r"(\d{1,3}(?:[   ]\d{3})*(?:[,.]\d+)?)\s*(Md€|M€|k€|milliards? d['’]euros|"
                        r"millions? d['’]euros|€)", re.I)
MOTS_VIDES = {"de", "des", "du", "la", "le", "les", "l", "d", "et", "en", "a", "au", "aux", "sur"}


def jeton(s: str) -> str:
    s = norm(s)
    s = re.sub(r"\bst\b", "saint", s)
    s = re.sub(r"\bste\b", "sainte", s)
    return s


def mots_cle(s: str) -> frozenset:
    return frozenset(w for w in jeton(s).split() if w not in MOTS_VIDES)


ABREV_EPCI = [(r"^cc ", "communaute de communes "), (r"^ca ", "communaute d agglomeration "),
              (r"^cu ", "communaute urbaine "), (r"^ccom ", "communaute de communes ")]


def cle_epci(nom: str) -> frozenset:
    s = jeton(nom)
    for a, b in ABREV_EPCI:
        s = re.sub(a, b, s)
    return frozenset(w for w in s.split() if w not in MOTS_VIDES)


def referentiel_geo() -> dict:
    """Départements, régions, communes et EPCI de site/data/local/geo (COG en vigueur)."""
    deps, regions, communes, epcis, noms_region = {}, {}, defaultdict(dict), defaultdict(dict), {}
    for f in sorted((SITE / "local" / "geo").glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        d = g["departement"]
        deps[jeton(d["nom"])] = d["code"]
        if g.get("region"):
            regions[jeton(g["region"]["nom"])] = g["region"]["code"]
            noms_region[g["region"]["code"]] = g["region"]["nom"]
        for insee, c in g["communes"].items():
            communes[d["code"]].setdefault(jeton(c["nom"]), []).append(
                {"insee": insee, "epci": c.get("epci"), "region": c.get("region")})
        for siren, e in g.get("epci", {}).items():
            epcis[d["code"]][cle_epci(e["nom"])] = siren
    reg_dep = {}
    for f in sorted((SITE / "local" / "geo").glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        reg_dep[g["departement"]["code"]] = (g.get("region") or {}).get("code")
    return {"deps": deps, "regions": regions, "communes": communes, "epcis": epcis, "reg_dep": reg_dep,
            "noms_dep": {v: k for k, v in deps.items()}, "noms_region": noms_region}


TYPES_EPCI = ("communaute de communes", "communaute d agglomeration", "communaute urbaine", "metropole")


def code_departement(geo: dict, nom: str | None) -> str | None:
    """'LOIRE-ATLANTIQUE, FRANCE', 'SAVOIE (FRANCE)', 'LOIRET (45)', 'REUNION' -> code du département."""
    if not nom:
        return None
    m = re.search(r"(?:^|\()(\d[\dAB]|\d{3})(?:\)|$)", nom.strip())
    if m and m.group(1).zfill(2) in geo["reg_dep"]:
        return m.group(1).zfill(2)
    s = jeton(re.sub(r"(?i),?\s*\(?france\)?\s*$", "", nom))
    s = re.sub(r"\s*\d+$", "", s).strip()
    for cand in (s, re.sub(r"^(la|le|les|l) ", "", s), "la " + s):
        if cand in geo["deps"]:
            return geo["deps"][cand]
    return None


def rattacher_collectivite(geo: dict, type_org: str, nom: str, lieu_commune: str | None, dep_nom: str | None) -> dict:
    """Codes commune / EPCI / département / région d'un organisme contrôlé par une CRC.
    `niveau` = commune, epci, departement, region (la collectivité elle-même) ou autre_organisme (rattaché au lieu)."""
    t = jeton(type_org or "")
    dep = code_departement(geo, dep_nom)
    codes = {"commune": None, "epci": None, "departement": dep, "region": geo["reg_dep"].get(dep) if dep else None}
    if t == "region" or t.startswith("region") or t == "collectivite territoriale" and "region" in jeton(nom):
        r = geo["regions"].get(jeton(re.sub(r"(?i)^r[ée]gion\s*", "", nom or "")))
        return {"niveau": "region", "codes": {**codes, "region": r or codes["region"]},
                "methode": "nom de la région" if r else "département du lieu"}
    if t.startswith("departement"):
        return {"niveau": "departement", "codes": codes, "methode": "département du lieu"}
    if any(t.startswith(x) for x in TYPES_EPCI) and dep:
        siren = geo["epcis"].get(dep, {}).get(cle_epci(nom))
        return {"niveau": "epci", "codes": {**codes, "epci": siren},
                "methode": "nom de l'EPCI (référentiel COG en vigueur)" if siren else
                "EPCI absent du référentiel en vigueur (fusion ou dissolution) : département seul"}
    commune = lieu_commune or (nom if t == "commune" else None)
    if commune and dep:
        c = geo["communes"].get(dep, {}).get(jeton(commune))
        if c and len(c) == 1:
            codes.update(commune=c[0]["insee"], epci=c[0]["epci"])
    niveau = "commune" if t == "commune" else "autre_organisme"
    meth = ("nom de la commune dans le département (COG en vigueur)" if codes["commune"] else
            "commune absente du COG en vigueur ou ambiguë : département seul" if commune else "département du lieu")
    return {"niveau": niveau, "codes": codes, "methode": meth}


def lire_meta_rod() -> list[dict]:
    import openpyxl
    if not META_ROD.exists():
        return []
    ws = openpyxl.load_workbook(META_ROD, read_only=True).active
    lignes = list(ws.iter_rows(values_only=True))
    entete = lignes[0]
    out = []
    for r in lignes[1:]:
        x = dict(zip(entete, r))
        if not x.get("cle") or not (propre(x.get("doc_titre")) or propre(x.get("organisme_controle"))):
            continue
        date = x["doc_dt"].strftime("%Y-%m-%d") if hasattr(x.get("doc_dt"), "strftime") else None
        lieu = (x.get("organisme_lieu") or "").split("**")
        annee = int(x["annee_fichier"])
        out.append({"id": f"rod-{x['cle']}", "cle": int(x["cle"]), "titre": propre(x.get("doc_titre")) or propre(x.get("organisme_controle")), "date": date, "annee": int(date[:4]) if date else annee,
                    "type": "Rapport d'observations définitives",
                    "nature_controle": propre(x.get("controle_type")).capitalize() or None,
                    "juridiction": propre(x.get("entite")) or None, "organisme": propre(x.get("organisme_controle")),
                    "organisme_type": propre(x.get("organisme_type")) or None,
                    "lieu_commune": propre(lieu[0]) or None if lieu else None,
                    "lieu_departement": propre(lieu[1]) if len(lieu) > 1 else None,
                    "url": URL_META_ROD, "url_document": URL_ROD_ZIP.format(horo=HORO_ROD.get(annee, ""), annee=annee)
                    if annee in HORO_ROD else None,
                    "document": f"fichier « {x['cle']}_*.pdf.txt » de l'archive rod-{annee}.zip",
                    "source": SRC_META_ROD})
    return out


def lire_pubs_2011_2016() -> list[dict]:
    if not PUBS_2011_2016.exists():
        return []
    rows = list(csv.reader(io.StringIO(PUBS_2011_2016.read_bytes().decode("cp1252")), delimiter=";"))
    out = []
    for i, r in enumerate(rows[1:]):
        if len(r) < 9 or not propre(r[6]):
            continue
        annee = int(r[2]) if r[2].isdigit() else None
        mois = MOIS.get(norm(r[3]))
        out.append({"id": f"cdc-2011-2016-{i}", "titre": propre(r[6]), "date": f"{annee}-{mois:02d}" if annee and mois
                    else None, "annee": annee, "type": propre(r[1]) or None, "famille": propre(r[8]) or None,
                    "fondement": propre(r[0]) or None, "juridiction": "Cour des comptes",
                    "url": URL_PUBS_2011_2016, "source": SRC_PUBS})
    return out


def constats_chiffres(texte: str | None) -> list[dict]:
    """Phrases du résumé publié qui contiennent un montant : montant lu, unité, valeur en euros, extrait."""
    if not texte:
        return []
    out = []
    for phrase in re.split(r"(?<=[.;])\s+", texte):
        for m in MONTANT_RE.finditer(phrase):
            v = float(re.sub(r"[   ]", "", m.group(1)).replace(",", "."))
            u = m.group(2).lower()
            mult = 1e9 if u.startswith(("md", "milliard")) else 1e6 if u.startswith(("m€", "million")) else \
                1e3 if u.startswith("k") else 1
            out.append({"montant": m.group(0), "valeur_eur": round(v * mult, 2), "extrait": phrase[:300]})
    return out[:10]


def lire_pages_ccomptes() -> list[dict]:
    out = []
    for x in charger_pubs().values():
        if x.get("statut") != 200 or not x.get("titre"):
            continue
        docs = x.get("documents") or []
        principal = next((d for d in docs if TYPES_CONNUS.match(d["type"])), None)
        resume = texte_sans_personne(x.get("resume"))
        jur = x.get("juridiction") or ""
        out.append({"id": f"cc-{x.get('node') or abs(hash(x['url'])) % 10**9}", "titre": x["titre"],
                    "date": x.get("date"), "annee": int(x["date"][:4]) if x.get("date") else None,
                    "type": principal["type"] if principal else None,
                    "juridiction": jur.title() if jur.isupper() else jur or None,
                    "themes": x.get("themes") or [], "url": x["url"],
                    "url_document": principal["url"] if principal else None,
                    "constats_chiffres": constats_chiffres(resume), "lu_le": x.get("lu_le"), "source": SRC_PAGES})
    return out


def neb_par_mission() -> dict:
    """NEB vérifiées par pipeline/realisations.py (reprises par lien, sans nouvelle vérification)."""
    out = defaultdict(dict)
    for f in sorted((SITE / "realisations").glob("[0-9]*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        for l in (p.get("evaluations") or {}).get("liens", []):
            if l.get("type", "").startswith("note d'exécution"):
                out[p["mission"]][l["annee_execution"]] = {"annee_execution": l["annee_execution"], "url": l["url"],
                                                            "page": l.get("page"), "verifie_le": l.get("verifie_le")}
    return {m: sorted(v.values(), key=lambda x: -x["annee_execution"]) for m, v in out.items()}


def programmes_ref() -> dict:
    progs = {}
    for f in sorted((SITE / "realisations").glob("[0-9]*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        progs[p["programme"]] = {"libelle": p["libelle"], "mission": p["mission"], "operateurs": []}
    for f in sorted((SITE / "beneficiaires").glob("programme_*.json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        if b.get("programme") in progs:
            for o in (b.get("operateurs") or {}).get("liste", []):
                nom = propre(o.get("operateur"))
                nom_court = nom.split(" - ")[-1] if " - " in nom else nom
                if len(mots_cle(nom_court)) >= 3:  # nom assez long pour un rattachement par titre sans ambiguïté
                    progs[b["programme"]]["operateurs"].append(nom_court)
    return progs


DEMANDEUR = re.compile(r"\s*\((?:Assembl[ée]e nationale|S[ée]nat)\)\s*\*?\s*$", re.I)


def rattacher_programmes(titre: str, progs: dict) -> tuple[list, list, list]:
    t = norm(DEMANDEUR.sub("", titre))
    t = re.sub(r"fonction publique (territoriale|hospitaliere)", r"fp \1", t)
    ps, ops, regles = [], [], set()
    for p, m in progs.items():
        if contient(t, m["libelle"]) and len(mots_cle(m["libelle"])) >= 2:
            ps.append(p); regles.add("nom exact du programme")
        elif len(norm(m["mission"]).split()) >= 3 and contient(t, m["mission"]):
            ps.append(p); regles.add("nom exact de la mission (au moins trois mots)")
        for o in m["operateurs"]:
            if contient(t, o):
                ops.append({"operateur": o, "programme": p}); regles.add("nom exact d'un opérateur du programme")
    return sorted(set(ps) | {o["programme"] for o in ops}), ops, sorted(regles)


def produire_controle(geo: dict) -> dict:
    progs = programmes_ref()
    rod = lire_meta_rod()
    pubs = lire_pubs_2011_2016()
    pages = lire_pages_ccomptes()
    rss = []
    rss_f = CACHE_CC / "rss_publications.xml"
    if rss_f.exists():
        for it in re.findall(r"<item>(.*?)</item>", rss_f.read_text(encoding="utf-8"), re.S):
            ti = re.search(r"<title>(.*?)</title>", it, re.S)
            li = re.search(r"<link>(.*?)</link>", it, re.S)
            da = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
            if ti and li:
                date = None
                if da:
                    try:
                        date = datetime.strptime(da.group(1).strip()[:25].strip(), "%a, %d %b %Y %H:%M:%S").strftime(
                            "%Y-%m-%d")
                    except ValueError:
                        date = None
                u = li.group(1).strip()
                if any(p["url"] == u for p in pages):
                    continue
                rss.append({"id": f"rss-{abs(hash(u)) % 10**9}", "titre": propre(re.sub(r"<!\[CDATA\[|\]\]>", "",
                            ti.group(1))), "date": date, "annee": int(date[:4]) if date else None, "type": None,
                            "juridiction": None, "url": u, "source": "ccomptes.fr, flux RSS des publications"})
    # Collectivités : ROD des CRC (métadonnées data.gouv) + pages CRC lues sur ccomptes.fr
    par_dep, comptes_niveau, non_localises = defaultdict(list), Counter(), []
    for r in rod:
        dep_nom = r["lieu_departement"]
        if not code_departement(geo, dep_nom):
            m = re.search(r"\(([^()]+)\)\s*$", r["titre"] or "")
            dep_nom = m.group(1) if m and code_departement(geo, m.group(1)) else dep_nom
        rat = rattacher_collectivite(geo, r["organisme_type"] or "", r["organisme"], r["lieu_commune"], dep_nom)
        e = {k: r[k] for k in ("id", "titre", "date", "annee", "type", "nature_controle", "juridiction", "organisme",
                               "organisme_type", "url", "url_document", "document", "source")}
        e.update(niveau=rat["niveau"], codes=rat["codes"], rattachement=rat["methode"])
        if rat["codes"]["departement"]:
            par_dep[rat["codes"]["departement"]].append(e)
            comptes_niveau[rat["niveau"]] += 1
        elif rat["codes"]["region"]:
            par_dep[f"region_{rat['codes']['region']}"].append(e)
            comptes_niveau[rat["niveau"]] += 1
        else:
            non_localises.append(e)
    pages_crc, pages_cour = [], []
    for p in pages:
        if p["juridiction"] and re.match(r"(?i)^(crc|ctc|crtc|chambre)", p["juridiction"]):
            pages_crc.append(p)
        else:
            pages_cour.append(p)
    for p in pages_crc:
        m = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", p["titre"].split(" - ")[0])
        nom, dep_nom = (m.group(1), m.group(2)) if m else (p["titre"].split(" - ")[0], None)
        tt = jeton(nom)
        type_org = next((x for x in ("commune", "region", "departement") + TYPES_EPCI if tt.startswith(x)), "")
        nom_org = re.sub(r"(?i)^(commune|ville)\s+(de|d['’]|du|des)\s*", "", nom) if type_org == "commune" else nom
        if type_org == "region":
            dep_nom = None
        rat = rattacher_collectivite(geo, type_org, nom_org, None, dep_nom)
        if type_org == "region":
            r = geo["regions"].get(jeton(re.sub(r"(?i)^r[ée]gion\s*", "", nom)))
            rat["codes"]["region"] = r
        e = {k: p.get(k) for k in ("id", "titre", "date", "annee", "type", "juridiction", "url", "url_document",
                                     "constats_chiffres", "source")}
        e.update(organisme=nom, niveau=rat["niveau"] if type_org else "autre_organisme", codes=rat["codes"],
                 rattachement=rat["methode"] if type_org or dep_nom else "aucun département lisible dans le titre")
        dep = rat["codes"]["departement"]
        if dep:
            par_dep[dep].append(e); comptes_niveau[e["niveau"]] += 1
        elif rat["codes"]["region"]:
            par_dep[f"region_{rat['codes']['region']}"].append(e); comptes_niveau["region"] += 1
        else:
            non_localises.append(e)
    # Programmes : publications de la Cour (2011-2016, pages lues, flux RSS)
    rattachees, autres = [], []
    for p in pubs + pages_cour + rss:
        ps, ops, regles = rattacher_programmes(p["titre"], progs)
        e = {k: p.get(k) for k in ("id", "titre", "date", "annee", "type", "famille", "juridiction", "url",
                                     "url_document", "constats_chiffres", "source") if p.get(k) is not None}
        if ps:
            e.update(programmes=ps, operateurs=ops, rattachement=regles)
            rattachees.append(e)
        else:
            autres.append(e)
    neb = neb_par_mission()
    par_programme = {}
    for p, m in sorted(progs.items()):
        ids = [e["id"] for e in rattachees if p in e["programmes"]]
        par_programme[p] = {"libelle": m["libelle"], "mission": m["mission"], "publications": ids,
                            "neb_mission": len(neb.get(m["mission"], []))}
    entete = {"millesime": "Publications 2011 à 2026 selon la source (voir chaque publication)",
              "source": " ; ".join([SRC_PUBS, SRC_PAGES, "ccomptes.fr, flux RSS des publications", SRC_NEB]),
              "avertissement": "Rattachement par le titre : une publication peut concerner un programme sans le "
                               "nommer ; l'absence de lien ne signifie pas l'absence de contrôle."}
    taille = dump(SORTIE / "publications" / "programmes.json", {
        **entete, "regles_rattachement": [
            "le titre contient le nom exact du programme (au moins deux mots significatifs)",
            "le titre contient le nom exact de la mission (au moins trois mots)",
            "le titre contient le nom exact d'un opérateur dont le programme est chef de file (au moins trois mots)"],
        "programmes": par_programme,
        "neb_par_mission": {m: {"programmes": sorted(p for p, x in progs.items() if x["mission"] == m), "notes": v}
                            for m, v in sorted(neb.items())},
        "publications": sorted(rattachees, key=lambda x: x.get("date") or "", reverse=True)})
    fichiers = {"publications/programmes.json": taille}
    index_deps = []
    for dep, lst in sorted(par_dep.items()):
        lst.sort(key=lambda x: x.get("date") or "", reverse=True)
        nom = None
        f = SITE / "local" / "geo" / f"{dep}.json"
        if f.exists():
            nom = json.loads(f.read_text(encoding="utf-8"))["departement"]["nom"]
        elif dep.startswith("region_"):
            nom = geo["noms_region"].get(dep[7:])
        c = Counter(e["niveau"] for e in lst)
        chemin = f"publications/collectivites/{dep}.json"
        fichiers[chemin] = dump(SORTIE / chemin, {
            "millesime": "Rapports d'observations définitives 2015 à 2019 (métadonnées data.gouv.fr) et pages "
                         "ccomptes.fr lues", "source": f"{SRC_META_ROD} ; {SRC_PAGES} ; référentiel geo.api.gouv.fr "
                         "(site/data/local/geo)", "departement": {"code": dep, "nom": nom},
            "comptes_par_niveau": dict(c), "publications": lst})
        index_deps.append({"code": dep, "nom": nom, "fichier": f"controle/{chemin}", "publications": len(lst),
                           "par_niveau": dict(c)})
    autres_c = Counter((e.get("juridiction") or "inconnue", e.get("type") or "non précisé") for e in autres)
    fichiers["publications/autres.json"] = dump(SORTIE / "publications" / "autres.json", {
        **entete, "note": "Publications lues mais rattachées à aucun programme ni à aucune collectivité.",
        "comptes": [{"juridiction": j, "type": t, "publications": n} for (j, t), n in autres_c.most_common()],
        "publications": sorted(autres, key=lambda x: x.get("date") or "", reverse=True),
        "non_localisees": non_localises})
    plan = urls_sitemap() if SITEMAP.exists() else []
    lues = charger_pubs()
    return {"fichiers": fichiers, "departements": index_deps, "comptes": {
        "programmes": {"publications_rattachees": len(rattachees),
                       "programmes_avec_publication": sum(1 for v in par_programme.values() if v["publications"]),
                       "missions_avec_neb": len(neb), "neb": sum(len(v) for v in neb.values()),
                       "par_regle": dict(Counter(r for e in rattachees for r in e["rattachement"]))},
        "collectivites": {"publications_rattachees": sum(comptes_niveau.values()), "par_niveau": dict(comptes_niveau),
                          "avec_code_commune": sum(1 for l in par_dep.values() for e in l if e["codes"]["commune"]),
                          "avec_code_epci": sum(1 for l in par_dep.values() for e in l if e["codes"]["epci"]),
                          "non_localisees": len(non_localises)},
        "non_rattachees": len(autres)},
        "couverture_ccomptes": {"pages_au_plan_du_site": len(plan),
                                "pages_lues": sum(1 for x in lues.values() if x.get("statut") == 200),
                                "pages_en_erreur": sum(1 for x in lues.values() if x.get("statut") != 200),
                                "lecture": "les pages non lues ne sont pas publiées (aucune métadonnée devinée)"}}


# --- 2. Influence : production -------------------------------------------------------------------------------------

SRC_HATVP = ("HATVP, répertoire des représentants d'intérêts (hatvp.fr/agora/opendata/agora_repertoire_opendata.json, "
             "Licence Ouverte 2.0) ; API Recherche d'entreprises (catégorie juridique)")
CATEGORIES_INDEPENDANTS = {"TRAIND", "COIND", "AVIND"}  # travailleur, consultant, avocat indépendants
FONCTION_GOUV = "Membre du Gouvernement ou membre de cabinet ministériel"
# Correspondance conventionnelle (établie par le projet) entre les intitulés de ministère du répertoire et les missions
# du budget de l'État. Un ministère sans correspondance n'est rattaché à aucune mission.
MINISTERE_MISSIONS = {
    "Economie et finances": ["Économie", "Gestion des finances publiques"],
    "Environnement, énergie et mer": ["Écologie, développement et mobilité durables"],
    "Affaires sociales et santé": ["Santé", "Solidarité, insertion et égalité des chances",
                                   "Régimes sociaux et de retraite"],
    "Agriculture, agroalimentaire et forêt": ["Agriculture, alimentation, forêt et affaires rurales"],
    "Premier ministre": ["Direction de l'action du Gouvernement"],
    "Travail, emploi, formation professionnelle et dialogue social": [
        "Travail, emploi et administration des ministères sociaux"],
    "Logement": ["Cohésion des territoires"],
    "Culture et communication": ["Culture", "Médias, livre et industries culturelles"],
    "Affaires étrangères et développement international": ["Action extérieure de l'État",
                                                            "Aide publique au développement"],
    "Education nationale, enseignement supérieur et recherche": ["Enseignement scolaire",
                                                                 "Recherche et enseignement supérieur"],
    "Intérieur": ["Sécurités", "Administration générale et territoriale de l'État", "Immigration, asile et intégration"],
    "Justice": ["Justice"],
    "Aménagement du territoire, ruralité et collectivités territoriales": [
        "Cohésion des territoires", "Relations avec les collectivités territoriales"],
    "Ville, jeunesse et sport": ["Sport, jeunesse et vie associative", "Cohésion des territoires"],
    "Fonction publique": ["Transformation et fonction publiques"],
    "Outre-mer": ["Outre-Mer"],
    "Défense": ["Défense", "Anciens combattants, mémoire et liens avec la Nation"],
    "Famille, enfance et droits des femmes": ["Solidarité, insertion et égalité des chances"],
}


def tranche_depense(s: str | None) -> tuple[float | None, float | None] | None:
    """'< 10 000 euros' -> (0, 10000) ; '> = 100 000 euros et < 200 000 euros' -> (100000, 200000) ;
    '> = 10 000 000 euros' -> (10000000, None)."""
    if not s:
        return None
    nombres = [float(x.replace(" ", "").replace(" ", "")) for x in re.findall(r"\d[\d  ]*", s)]
    if s.strip().startswith("<") and nombres:
        return 0.0, nombres[0]
    if len(nombres) >= 2:
        return nombres[0], nombres[1]
    if nombres:
        return nombres[0], None
    return None


def annee_exercice(pc: dict) -> int | None:
    d = pc.get("dateFin") or pc.get("dateDebut") or ""
    m = re.search(r"(\d{4})$", d)
    return int(m.group(1)) if m else None


def labels_ministeres(publications: list[dict]) -> set:
    """Intitulés de ministère tels que le répertoire les écrit seuls (une seule cible), pour découper les listes."""
    out = Counter()
    for p in publications:
        for e in p.get("exercices", []):
            for a in e["publicationCourante"].get("activites", []) or []:
                for r in a["publicationCourante"].get("actionsRepresentationInteret", []):
                    for z in r.get("reponsablesPublics", []):
                        if " - " in z:
                            f, cible = z.split(" - ", 1)
                            out[(f, cible)] += 1
    return {c for (f, c), n in out.items()}


def decouper_cibles(cible: str, connus: list[str]) -> list[str]:
    """'Premier ministre, Economie et finances, Autres : à préciser' -> 3 intitulés (les plus longs d'abord)."""
    res, reste = [], cible
    while reste:
        reste = reste.lstrip(", ").strip()
        if not reste:
            break
        m = next((c for c in connus if reste.startswith(c) and (len(reste) == len(c) or reste[len(c):].startswith(","))),
                 None)
        if m is None:
            m = reste.split(", ")[0]
        res.append(m)
        reste = reste[len(m):]
    return res


def cible_publiable(c: str) -> str:
    return c if texte_sans_personne(c) and not re.search(r"\d{2}[ .]\d{2}[ .]\d{2}", c) else "texte libre non publié"


def produire_influence() -> dict:
    pubs = charger_hatvp()
    cache = charger_sirene()
    connus_bruts = labels_ministeres(pubs)
    simples = sorted({c for c in connus_bruts if "," not in c} | set(MINISTERE_MISSIONS), key=len, reverse=True)
    orgs, exclus = [], {"organisations": 0, "motifs": Counter(), "actions": 0}
    par_cible = defaultdict(lambda: {"actions": 0, "orgs": set(), "domaines": Counter(), "annees": Counter(),
                                     "fonction": None})
    par_domaine = defaultdict(lambda: {"activites": 0, "orgs": set()})
    totaux_annee = defaultdict(lambda: {"organisations_declarantes": 0, "depense_min_eur": 0.0, "depense_max_eur": 0.0,
                                        "tranches_ouvertes": 0, "activites": 0})
    for p in pubs:
        tid, ident = p.get("typeIdentifiantNational"), p.get("identifiantNational")
        cat = p.get("categorieOrganisation") or {}
        motif = None
        if cat.get("code") in CATEGORIES_INDEPENDANTS:
            motif = "catégorie « indépendant » (personne physique possible)"
        elif tid == "SIREN":
            e = cache.get(ident)
            if e is None:
                motif = "catégorie juridique non encore vérifiée"
            elif not sirene.personne_morale(e.get("cj")):
                motif = "catégorie juridique hors personnes morales (1000, groupement de personnes physiques, inconnue)"
        elif tid not in ("RNA", "HATVP"):
            motif = "identifiant absent"
        if motif is None and not texte_sans_personne(p.get("denomination")):
            motif = "dénomination contenant une civilité"
        depenses, domaines, cibles, n_act, n_activites = [], Counter(), Counter(), 0, 0
        for e in p.get("exercices", []):
            pc = e["publicationCourante"]
            an = annee_exercice(pc)
            tr = tranche_depense(pc.get("montantDepense"))
            acts = pc.get("activites") or []
            if an and tr:
                depenses.append([an, tr[0], tr[1]])
            for a in acts:
                ac = a["publicationCourante"]
                n_activites += 1
                for d in ac.get("domainesIntervention", []):
                    domaines[d] += 1
                for r in ac.get("actionsRepresentationInteret", []):
                    n_act += 1
                    for z in r.get("reponsablesPublics", []):
                        f, cible = (z.split(" - ", 1) + [""])[:2] if " - " in z else (z, "")
                        noms = decouper_cibles(cible, simples) if cible else [f]
                        for c in noms:
                            c = cible_publiable(c)
                            cibles[c] += 1
                            if motif is None:
                                k = par_cible[(f, c)]
                                k["actions"] += 1; k["orgs"].add(ident); k["fonction"] = f
                                k["annees"][an] += 1
                                for d in ac.get("domainesIntervention", []):
                                    k["domaines"][d] += 1
            if motif is None and an:
                t = totaux_annee[an]
                t["activites"] += len(acts)
                if tr:
                    t["organisations_declarantes"] += 1
                    t["depense_min_eur"] += tr[0]
                    if tr[1] is None:
                        t["tranches_ouvertes"] += 1
                    else:
                        t["depense_max_eur"] += tr[1]
        if motif:
            exclus["organisations"] += 1; exclus["motifs"][motif] += 1; exclus["actions"] += n_act
            continue
        for d in domaines:
            par_domaine[d]["activites"] += domaines[d]; par_domaine[d]["orgs"].add(ident)
        missions = sorted({m for c in cibles for m in MINISTERE_MISSIONS.get(c, [])})
        orgs.append([ident, tid, propre(p.get("denomination")), cat.get("label"),
                     [s["label"] for s in (p.get("activites") or {}).get("listSecteursActivites", [])],
                     sorted(depenses), n_activites, n_act, [[d, n] for d, n in domaines.most_common(5)],
                     [[c, n] for c, n in cibles.most_common(5)], missions])
    orgs.sort(key=lambda o: norm(o[2]))
    entete = {"millesime": "Exercices déclarés 2018 à 2026 (répertoire publié le "
                           f"{datetime.fromtimestamp(HATVP_JSON.stat().st_mtime, timezone.utc):%Y-%m-%d})",
              "source": SRC_HATVP,
              "regle_personnes": "Organisations seulement. Aucun dirigeant, collaborateur ni responsable public n'est "
                                 "nommé : la cible est réduite à la fonction et au ministère ou à l'institution. "
                                 "Indépendants et SIREN hors catégories 2xxx à 9xxx : agrégés dans `exclus`. "
                                 "Déclarations de patrimoine et d'intérêts : hors périmètre.",
              "avertissement": "Montants déclarés par les organisations, par tranche ; la dépense réelle de chaque "
                               "organisation est comprise entre les bornes de sa tranche."}
    fichiers = {}
    fichiers["lobbying/organisations.json"] = dump(SORTIE / "lobbying" / "organisations.json", {
        **entete, "unite": "euros (bornes de tranche)",
        "colonnes": ["identifiant", "type_identifiant", "denomination", "categorie", "secteurs",
                     "depenses_declarees", "activites", "actions", "domaines", "cibles", "missions_lolf"],
        "colonnes_depenses": ["annee", "borne_basse_eur", "borne_haute_eur (null : tranche ouverte)"],
        "organisations": orgs,
        "totaux_par_annee": {str(a): {**v, "depense_max_eur": v["depense_max_eur"] if not v["tranches_ouvertes"]
                                      else None, "depense_max_hors_tranches_ouvertes_eur": v["depense_max_eur"]}
                             for a, v in sorted(totaux_annee.items()) if v["organisations_declarantes"]},
        "exclus": {"organisations": exclus["organisations"], "actions": exclus["actions"],
                   "motifs": dict(exclus["motifs"])}})
    cibles_out = []
    for (f, c), k in sorted(par_cible.items(), key=lambda x: -x[1]["actions"]):
        cibles_out.append({"fonction": f, "cible": c if c != f else None, "actions": k["actions"],
                           "organisations": len(k["orgs"]),
                           "par_annee": {str(a): n for a, n in sorted(k["annees"].items()) if a},
                           "domaines": [[d, n] for d, n in k["domaines"].most_common(10)],
                           "missions_lolf": MINISTERE_MISSIONS.get(c, []) if f == FONCTION_GOUV else []})
    progs = programmes_ref()
    fichiers["lobbying/ministeres.json"] = dump(SORTIE / "lobbying" / "ministeres.json", {
        **entete, "unite": "nombre d'actions déclarées (une action peut viser plusieurs cibles)",
        "cibles": cibles_out,
        "domaines": sorted(({"domaine": d, "activites": v["activites"], "organisations": len(v["orgs"])}
                            for d, v in par_domaine.items()), key=lambda x: -x["activites"]),
        "correspondance_ministere_missions": {
            m: {"missions": ms, "programmes": sorted(p for p, x in progs.items() if x["mission"] in ms)}
            for m, ms in MINISTERE_MISSIONS.items()},
        "correspondance_note": "Correspondance conventionnelle établie par le projet entre les intitulés de ministère "
                               "du répertoire (nomenclature HATVP) et les missions du budget de l'État ; un intitulé "
                               "absent n'est rattaché à aucune mission."})
    # année de référence : la plus récente qui compte au moins 90 % du maximum d'organisations déclarantes
    # (l'exercice en cours, déclaré l'année suivante, est incomplet)
    plein = max((v["organisations_declarantes"] for v in totaux_annee.values()), default=0)
    derniere = max((a for a, v in totaux_annee.items() if v["organisations_declarantes"] >= 0.9 * plein), default=None)
    return {"fichiers": fichiers, "comptes": {
        "inscrits": len(pubs), "organisations_publiees": len(orgs), "exclus": exclus["organisations"],
        "exclus_motifs": dict(exclus["motifs"]),
        "annee_reference": derniere,
        "depenses_annee_reference": ({**totaux_annee[derniere], "depense_max_eur": None,
                                      "depense_max_hors_tranches_ouvertes_eur": totaux_annee[derniere]["depense_max_eur"]}
                                     if derniere and totaux_annee[derniere]["tranches_ouvertes"] else
                                     totaux_annee.get(derniere)),
        "cibles": len(cibles_out)}}


# --- 3. Aides aux entreprises : estimations publiées --------------------------------------------------------------

HCSP_PDF = LAKE / "controle" / "controle_hcsp_2026_aides_entreprises.pdf"
URL_HCSP = ("https://www.strategie-plan.gouv.fr/files/files/Publications/2026/2026-07-16%20-%20Rapport%20Aides%20aux"
            "%20entreprises/HCSP-2026-RAPPORT-AIDES-ENTREPRISES.pdf")
SRC_HCSP = ("Haut-commissariat à la stratégie et au plan (HCSP), « Les aides aux entreprises : définition, périmètres, "
            "cadre de suivi et d'évaluation », rapport, juillet 2026 (tableau 1, partie 3, annexe 4)")
SRC_URSSAF = "open.urssaf.fr, « Exonérations de cotisations, champ large, par grandes catégories » (ODbL)"
TYPES_AIDE = {
    "subventions": "dépenses budgétaires (subventions) versées aux entreprises",
    "depenses_fiscales": "dépenses fiscales classées (crédits et réductions d'impôt, taux réduits...)",
    "depenses_fiscales_declassees": "dépenses fiscales déclassées par l'administration (dont certains taux de TVA)",
    "exonerations_cotisations": "exonérations et allègements de cotisations sociales",
    "prets_garanties": "prêts, garanties et participations (montant ou équivalent-subvention selon l'étude)",
    "collectivites": "aides des collectivités territoriales",
    "europe": "aides de l'Union européenne",
}
# Chaque estimation : `preuve` = passages qui doivent figurer dans le rapport du HCSP (vérifié à chaque production).
ESTIMATIONS = [
    {"id": "senat_2025_large", "auteur": "Sénat, commission d'enquête", "annee_publication": 2025, "annee_donnees": 2023,
     "publication": "Rapport sur l'utilisation des aides publiques aux grandes entreprises et à leurs sous-traitants "
                    "(n° 808, 2024-2025)", "md": 211,
     "perimetre": "subventions de l'État hors compensations de service public, interventions de Bpifrance, dépenses "
                  "fiscales y compris TVA et déclassées, allègements de cotisations sociales",
     "inclut": ["subventions", "prets_garanties", "depenses_fiscales", "depenses_fiscales_declassees",
                "exonerations_cotisations"], "exclut": ["collectivites", "europe"],
     "composantes_md": {"subventions": 7, "prets_garanties": 41, "depenses_fiscales": 88,
                        "exonerations_cotisations": 75},
     "composantes_note": "88 Md€ = dépenses fiscales au sens large (classées, TVA et déclassées) ; 41 Md€ = montant "
                         "des interventions de Bpifrance (prêts, garanties), pas un équivalent-subvention",
     "preuve": ["La première, à 211 milliards", "par Bpifrance (41 milliards)", "sociales (75 milliards)"]},
    {"id": "senat_2025_strict", "auteur": "Sénat, commission d'enquête", "annee_publication": 2025,
     "annee_donnees": 2023, "publication": "idem, estimation restreinte", "md": 108,
     "perimetre": "estimation large moins les interventions de Bpifrance et 62 Md€ de dépenses fiscales déclassées "
                  "et liées à la TVA", "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations"],
     "exclut": ["prets_garanties", "depenses_fiscales_declassees", "collectivites", "europe"],
     "preuve": ["La seconde estimation, à 108 milliards"]},
    {"id": "hcsp_2026_p1", "auteur": "HCSP", "annee_publication": 2026, "annee_donnees": 2023,
     "publication": "Les aides aux entreprises : définition, périmètres, cadre de suivi et d'évaluation, périmètre 1",
     "md": 82, "perimetre": "aides directes et ciblées : dépenses budgétaires ciblées, dépenses fiscales classées, "
                            "exonérations ciblées de cotisations, prêts, garanties et participations en "
                            "équivalent-subvention, aides directes des collectivités",
     "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations", "prets_garanties", "collectivites"],
     "exclut": ["depenses_fiscales_declassees", "europe"], "preuve": ["estimé à 82 milliards"]},
    {"id": "hcsp_2026_p2", "auteur": "HCSP", "annee_publication": 2026, "annee_donnees": 2023,
     "publication": "idem, périmètre 2", "md": 187,
     "perimetre": "périmètre 1 + exonérations générales de cotisations, taux réduits de TVA à finalité sectorielle, "
                  "interventions indirectes des collectivités",
     "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations", "prets_garanties", "collectivites"],
     "exclut": ["depenses_fiscales_declassees", "europe"], "preuve": ["Chiffré à 187 milliards"]},
    {"id": "hcsp_2026_agregat_large", "auteur": "HCSP", "annee_publication": 2026, "annee_donnees": 2023,
     "publication": "idem, agrégat macroéconomique complémentaire", "md": 259,
     "perimetre": "mesure globale des soutiens publics en faveur des activités économiques",
     "inclut": None, "exclut": None, "preuve": ["est évalué à 259 milliards"]},
    {"id": "hcsp_2025_aides_etat", "auteur": "HCSP (note d'analyse n° 157)", "annee_publication": 2025,
     "annee_donnees": 2023, "publication": "Les aides aux entreprises en France : de quoi parle-t-on ?", "md": 45,
     "perimetre": "aides d'État au sens du droit européen", "inclut": None, "exclut": None,
     "preuve": ["soit environ 45 milliards d’euros en France en 2023"]},
    {"id": "hcsp_2025", "auteur": "HCSP (note d'analyse n° 157)", "annee_publication": 2025, "annee_donnees": 2023,
     "publication": "idem, second périmètre", "md": 112,
     "perimetre": "aides budgétaires, fiscales classées, financières en équivalent-subvention, exonérations ciblées ; "
                  "hors exonérations générales, dépenses fiscales déclassées, collectivités et Europe",
     "inclut": ["subventions", "depenses_fiscales", "prets_garanties", "exonerations_cotisations"],
     "exclut": ["depenses_fiscales_declassees", "collectivites", "europe"],
     "preuve": ["exonérations de cotisations ciblées (112 milliards)"]},
    {"id": "igf_2024", "auteur": "Inspection générale des finances", "annee_publication": 2024, "annee_donnees": 2022,
     "publication": "Revue de dépenses : les aides aux entreprises (n° 2023-M-105-03)", "md": 88,
     "perimetre": "aides budgétaires et fiscales ciblées de l'État et de la sécurité sociale, hors allègements "
                  "généraux de cotisations et dépenses fiscales déclassées",
     "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations"],
     "exclut": ["depenses_fiscales_declassees", "collectivites", "europe"],
     "preuve": ["s’élèvent à 88 milliards d’euros"]},
    {"id": "igf_2024_elargi", "auteur": "Inspection générale des finances", "annee_publication": 2024,
     "annee_donnees": 2022, "publication": "idem, élargi", "md": 105,
     "perimetre": "88 Md€ + aides budgétaires des collectivités (7 Md€, 2021) + une partie des aides européennes "
                  "(10 Md€)", "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations",
                                         "collectivites", "europe"], "exclut": ["depenses_fiscales_declassees"],
     "preuve": ["le total des aides aux entreprises estimé passe à 105 milliards d’euros"]},
    {"id": "ce_2024", "auteur": "Commission européenne (State Aid Scoreboard)", "annee_publication": 2024,
     "annee_donnees": 2022, "publication": "Données annuelles des aides d'État", "md": 45,
     "perimetre": "aides d'État au sens du droit européen (25 Md€ hors mesures Covid et Ukraine)", "inclut": None,
     "exclut": ["exonerations_cotisations"], "preuve": ["(45 milliards d’euros en 2022, 25 milliards"]},
    {"id": "ires_clerse_2022", "auteur": "Ires, équipe du Clersé (université de Lille)", "annee_publication": 2022,
     "annee_donnees": 2019, "publication": "Un capitalisme sous perfusion", "md": 157,
     "perimetre": "aides budgétaires (comptabilité nationale), dépenses fiscales, exonérations de cotisations ; hors "
                  "prêts, garanties, participations et dépenses fiscales déclassées",
     "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations"],
     "exclut": ["prets_garanties", "depenses_fiscales_declassees"],
     "preuve": ["estime à 157 milliards d’euros le montant global des aides\npubliques aux entreprises en 2019"]},
    {"id": "ires_clerse_2022_large", "auteur": "Ires, équipe du Clersé (université de Lille)",
     "annee_publication": 2022, "annee_donnees": 2019, "publication": "idem, périmètre large", "md": 205,
     "perimetre": "157 Md€ + dépenses fiscales déclassées",
     "inclut": ["subventions", "depenses_fiscales", "depenses_fiscales_declassees", "exonerations_cotisations"],
     "exclut": ["prets_garanties"], "preuve": ["le plus large, soit 205 milliards d’euros d’aides aux entreprises"]},
    {"id": "france_strategie_2020_restreint", "auteur": "France Stratégie", "annee_publication": 2020,
     "annee_donnees": 2019, "publication": "Les politiques industrielles en France : évolutions et comparaisons "
                                           "internationales, périmètre le plus restreint", "md": 139,
     "perimetre": "hors dépenses fiscales déclassées, interventions financières, infrastructures de transport, aides "
                  "directes à certaines entreprises ou services publics",
     "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations", "collectivites", "europe"],
     "exclut": ["depenses_fiscales_declassees", "prets_garanties"],
     "preuve": ["139 milliards d’euros selon le périmètre le plus restreint"]},
    {"id": "france_strategie_2020_large", "auteur": "France Stratégie", "annee_publication": 2020,
     "annee_donnees": 2019, "publication": "idem, périmètre le plus large", "md": 223,
     "perimetre": "dépenses budgétaires, fiscales y compris déclassées et taxes affectées, exonérations de "
                  "cotisations, aides financières, aides régionales, aides européennes à la R & D",
     "inclut": ["subventions", "depenses_fiscales", "depenses_fiscales_declassees", "exonerations_cotisations",
                "prets_garanties", "collectivites", "europe"], "exclut": [],
     "preuve": ["s’élève à 223 milliards selon le périmètre le plus large"]},
    {"id": "cpo_2010", "auteur": "Conseil des prélèvements obligatoires (rattaché à la Cour des comptes)",
     "annee_publication": 2010, "annee_donnees": None, "publication": "Entreprises et niches fiscales et sociales",
     "md": 170, "md_haut": 200, "perimetre": "dépenses fiscales y compris TVA, TIPP et déclassées, niches sociales ; "
                                             "hors interventions financières, agriculture, Europe",
     "inclut": ["depenses_fiscales", "depenses_fiscales_declassees", "exonerations_cotisations"],
     "exclut": ["prets_garanties", "europe"], "preuve": ["170-200"]},
]


def texte_pdf(chemin: Path) -> str:
    import shutil
    import subprocess
    if not chemin.exists():
        return ""
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(chemin), "-"], capture_output=True, check=True)
        return r.stdout.decode("utf-8", errors="replace")
    import pdfplumber
    with pdfplumber.open(chemin) as doc:
        return "\n".join(p.extract_text() or "" for p in doc.pages)


def produire_aides() -> dict:
    texte = re.sub(r"[ \t]+", " ", texte_pdf(HCSP_PDF))
    verif, estimations = {}, []
    for e in ESTIMATIONS:
        trouve = bool(texte) and all(re.sub(r"\s+", " ", p) in re.sub(r"\s+", " ", texte) for p in e["preuve"])
        verif[e["id"]] = "vérifié" if trouve else ("document absent" if not texte else "passage introuvable")
        if texte and not trouve:
            raise SystemExit(f"aides : passage introuvable dans le rapport HCSP pour {e['id']} : {e['preuve']}")
        x = {k: v for k, v in e.items() if k != "preuve"}
        x["source"] = SRC_HCSP + " ; publication d'origine citée dans `publication`"
        estimations.append(x)
    hautes = [e.get("md_haut") or e["md"] for e in estimations]
    basses = [e["md"] for e in estimations]
    # Exonérations de cotisations (Urssaf), secteur privé, par grande catégorie et par année
    serie = []
    if URSSAF_EXOS.exists():
        import duckdb
        rows = duckdb.sql(f"select year(annee) a, grande_categorie_de_mesures c, sum(montant_des_exonerations) m "
                          f"from '{URSSAF_EXOS}' where champ like 'Secteur privé%' group by 1, 2 order by 1, 2"
                          ).fetchall()
        par = defaultdict(dict)
        for a, c, m in rows:
            par[a][re.sub(r"^\d+_", "", c)] = round(m, 2)
        serie = [{"annee": a, "total_eur": round(sum(v.values()), 2), "par_categorie_eur": v}
                 for a, v in sorted(par.items())]
    lies = []
    f2030 = SITE / "beneficiaires" / "france2030.json"
    if f2030.exists():
        f = json.loads(f2030.read_text(encoding="utf-8"))
        lies.append({"fichier": "beneficiaires/france2030.json", "champ": "ensemble.total_eur",
                     "type": "subventions", "type_detail": f.get("unite"), "millesime": f.get("millesime"),
                     "montant_eur": f["ensemble"]["total_eur"], "beneficiaires_nommes": "par SIREN, dans le fichier",
                     "note": "montants engagés sur plusieurs années : non annuels, non additionnables aux estimations"})
    for chemin, champ, typ, note in [
        ("niches/index.json", "totaux", "depenses_fiscales",
         "toutes les dépenses fiscales, ménages compris : seule une partie bénéficie aux entreprises"),
        ("niches/sociales.json", None, "exonerations_cotisations", "détail par mesure des exonérations de cotisations"),
        ("beneficiaires/index.json", "fichiers.programmes", "subventions",
         "associations subventionnées et opérateurs par programme (pas d'aides aux entreprises nommées hors France "
         "2030)"),
        ("ue/beneficiaires/index.json", None, "europe", "bénéficiaires des fonds européens en France (FEDER, FSE+, "
                                                        "Horizon...)")]:
        if (SITE / chemin).exists():
            lies.append({"fichier": chemin, "champ": champ, "type": typ, "note": note})
    dump(SORTIE / "aides_entreprises.json", {
        "millesime": "Estimations publiées de 2010 à 2026 (données 2019 à 2023) ; exonérations Urssaf 2004 à 2025",
        "source": f"{SRC_HCSP} ({URL_HCSP}) ; {SRC_URSSAF}",
        "unite": "milliards d'euros (md) ; euros (*_eur)",
        "avertissement": "Chaque estimation a son périmètre et son année : elles ne s'additionnent pas et ne se "
                         "remplacent pas. Elles sont publiées côte à côte, avec ce que chacune inclut et exclut.",
        "types": TYPES_AIDE, "estimations": sorted(estimations, key=lambda e: e["md"]),
        "fourchette": {"basse_md": min(basses), "haute_md": max(hautes),
                       "basse": [e["id"] for e in estimations if e["md"] == min(basses)],
                       "haute": [e["id"] for e in estimations if (e.get("md_haut") or e["md"]) == max(hautes)],
                       "note": "écart dû au périmètre retenu (aides d'État au sens européen jusqu'à l'agrégat "
                               "macroéconomique), pas à une divergence de mesure sur un même périmètre"},
        "exonerations_cotisations_urssaf": {"champ": "secteur privé (champ des ETE et hors champ), secteur public "
                                                     "exclu", "source": SRC_URSSAF, "annees": serie},
        "donnees_du_site": lies,
        "verification_documents": {"document": str(HCSP_PDF.relative_to(ROOT)), "url": URL_HCSP, "estimations": verif}})
    return {"estimations": len(estimations), "fourchette_md": [min(basses), max(hautes)],
            "verification": Counter(verif.values())}


# --- Index -----------------------------------------------------------------------------------------------------------

RECHERCHE_PUBLIQUE = [
    {"nom": "HATVP, répertoire des représentants d'intérêts (JSON complet et vues séparées CSV)",
     "url": "https://www.hatvp.fr/agora/opendata/agora_repertoire_opendata.json", "verdict": "réutilisable tel quel",
     "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-11-16", "usage": "source unique du volet influence"},
    {"nom": "data.gouv.fr, Cour des comptes : métadonnées des ROD des CRC 2015-2019",
     "url": URL_META_ROD, "verdict": "réutilisable tel quel", "licence": "non précisée sur data.gouv.fr",
     "mise_a_jour": "2020-01-22", "usage": "rapports des CRC reliés aux collectivités"},
    {"nom": "data.gouv.fr, Publications de la Cour des comptes par type et date (2011-2016)", "url": URL_PUBS_2011_2016,
     "verdict": "réutilisable tel quel", "licence": "ODbL", "mise_a_jour": "2018-05-07",
     "usage": "publications de la Cour reliées aux programmes"},
    {"nom": "data.gouv.fr, Rapports publiés par la Cour des comptes (texte intégral 2013-2018)",
     "url": "https://www.data.gouv.fr/fr/datasets/rapports-publies-par-la-cour-des-comptes/",
     "verdict": "inspiration seulement", "licence": "ODbL", "mise_a_jour": "2018-09-27",
     "usage": "texte intégral (centaines de Mo), métadonnées déjà couvertes par les deux jeux ci-dessus"},
    {"nom": "ccomptes.fr, plan du site des publications et métadonnées schema.org des pages",
     "url": f"{CC}/sitemap_publication/sitemap.xml", "verdict": "à adapter", "licence": "Licence Ouverte 2.0",
     "mise_a_jour": "quotidienne", "usage": "collecte reprenable des pages (lecture lente, serveur souvent en 5xx)"},
    {"nom": "entrepreneur-interet-general/api-ccomptes (GitHub)",
     "url": "https://github.com/entrepreneur-interet-general/api-ccomptes", "verdict": "inspiration seulement",
     "licence": "AGPL-3.0", "mise_a_jour": "2018-09-26", "usage": "ancien site ccomptes.fr, non transposable"},
    {"nom": "juliengossa/hatvp (GitHub)", "url": "https://github.com/juliengossa/hatvp",
     "verdict": "inspiration seulement", "licence": "aucune déclarée", "mise_a_jour": "2024-07-14",
     "usage": "fouille du répertoire HATVP"},
    {"nom": "plexigraf/lobbys-HATVP (GitHub)", "url": "https://github.com/plexigraf/lobbys-HATVP",
     "verdict": "inspiration seulement", "licence": "aucune déclarée", "mise_a_jour": "2025-04-02",
     "usage": "statistiques du registre"},
    {"nom": "koutakou/france-transparence (GitHub)", "url": "https://github.com/koutakou/france-transparence",
     "verdict": "inspiration seulement", "licence": "AGPL-3.0", "mise_a_jour": "2026-11-11",
     "usage": "tableau de bord vie politique (TypeScript) ; licence incompatible avec une reprise du code sous MIT"},
    {"nom": "accelaire/CLAIR (GitHub)", "url": "https://github.com/accelaire/CLAIR", "verdict": "inspiration seulement",
     "licence": "AGPL-3.0", "mise_a_jour": "2026-11-11", "usage": "client HATVP en TypeScript"},
    {"nom": "dataresearchcenter/datasets, fr_hatvp (GitHub)", "url": "https://github.com/dataresearchcenter/datasets",
     "verdict": "inspiration seulement", "licence": "AGPL-3.0", "mise_a_jour": "2026-11-11",
     "usage": "configuration de collecte HATVP (FollowTheMoney)"},
    {"nom": "QtnClst/oraclemarin-donnees-ouvertes, lobbying.py (GitHub)",
     "url": "https://github.com/QtnClst/oraclemarin-donnees-ouvertes", "verdict": "inspiration seulement",
     "licence": "MIT", "mise_a_jour": "2026-11-16", "usage": "lecture du répertoire HATVP"},
    {"nom": "etalab/dashboard-aides-entreprises (GitHub)", "url": "https://github.com/etalab/dashboard-aides-entreprises",
     "verdict": "inspiration seulement", "licence": "MIT", "mise_a_jour": "2026-08-29",
     "usage": "aides de crise Covid (fonds de solidarité, PGE...), déjà présentes dans data/lake/aides_entreprises"},
    {"nom": "HCSP, rapport « Les aides aux entreprises » (juillet 2026), tableau 1 et annexe 4", "url": URL_HCSP,
     "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-07-17",
     "usage": "recension des estimations publiées, chaque montant revérifié dans le PDF"},
]


def sources_inaccessibles() -> list[dict]:
    out = [{"source": "ccomptes.fr, pages des publications", "url": f"{CC}/fr/publications/",
            "constat": "réponses 502 et 504 et délais dépassés le 17/11/2026 ; collecte arrêtée après 5 erreurs "
                       "consécutives, reprise à chaque `collecter`",
            "effet": "seules les pages lues sont publiées ; ROD des CRC 2020-2026 et référés récents non couverts tant "
                     "que les pages ne sont pas lues"},
           {"source": "Légifrance", "url": "https://www.legifrance.gouv.fr", "constat": "non utilisé",
            "effet": "aucun"},
           {"source": "HATVP, déclarations de patrimoine et d'intérêts", "url": "https://www.hatvp.fr",
            "constat": "exclues volontairement (données personnelles)", "effet": "hors périmètre"}]
    refus = CACHE_CC / "refus.json"
    if refus.exists():
        out[0]["dernier_refus"] = json.loads(refus.read_text(encoding="utf-8"))
    return out


def produire() -> dict:
    geo = referentiel_geo()
    c = produire_controle(geo)
    i = produire_influence()
    a = produire_aides()
    index = {
        "millesime": f"Généré le {datetime.now(timezone.utc):%Y-%m-%d}",
        "source": "pipeline/controle.py (voir chaque fichier)",
        "fichiers": {"controle": sorted(c["fichiers"]), "influence": sorted(i["fichiers"]),
                     "aides": ["aides_entreprises.json"]},
        "controle": {**c["comptes"], "couverture_ccomptes": c["couverture_ccomptes"],
                     "departements": c["departements"]},
        "influence": i["comptes"],
        "aides_entreprises": {"estimations": a["estimations"], "fourchette_md": a["fourchette_md"],
                              "verification": dict(a["verification"])},
        "regle_personnes": "Aucune personne physique nommée : ni dirigeants, ni collaborateurs, ni responsables "
                           "publics (fonction et ministère seulement), ni auteurs des réponses aux rapports.",
        "sources_inaccessibles": sources_inaccessibles(),
        "recherche_publique": RECHERCHE_PUBLIQUE}
    dump(SORTIE / "index.json", index)
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collecter")
    c.add_argument("--budget", type=float, default=1800)
    sub.add_parser("produire")
    a = ap.parse_args()
    if a.cmd == "collecter":
        collecter_ccomptes(a.budget * 0.7)
        resoudre_hatvp(a.budget * 0.3)
    else:
        idx = produire()
        print(json.dumps({k: idx[k] for k in ("controle", "influence", "aides_entreprises")}, ensure_ascii=False,
                         indent=1)[:3000])


if __name__ == "__main__":
    main()
