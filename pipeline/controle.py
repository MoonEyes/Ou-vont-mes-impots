"""Contrôle, influence, aides aux entreprises : ce que disent les juridictions financières, qui fait du lobbying
déclaré auprès de quel ministère, et combien représentent les aides publiques aux entreprises selon chaque étude.

Entrées :
  ccomptes.fr : plan du site des publications (sitemap_publication, ~38 500 pages) puis chaque page publique
                (métadonnées JSON-LD schema.org, données de la page : chambre, catégorie, thèmes, documents typés) ;
                pages modifiées depuis 2020 lues en premier, une requête par seconde au plus, collecte reprenable,
                cache data/lake/_cache/ccomptes/publications.jsonl (métadonnées seulement, jamais le texte des
                réponses) ; arrêt au premier 403 ou 429 (noté, jamais contourné)
  API Recherche d'entreprises : SIREN et catégorie juridique des organismes contrôlés hors communes et EPCI
                (cache data/lake/_cache/controle_rod_siren.json), une requête par seconde au plus
  site/data/controle/rod_crtc/<année>.json, publications/programmes.json, autres.json : pages déjà publiées
                (mémoire : un cache de collecte en retard, runner à froid ou cache purgé, ne les retire pas)
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
  publications/collectivites/<dep>.json  rapports d'observations définitives des CRC (2015-2019 data.gouv.fr,
                                 2020-2026 pages lues) reliés aux communes, EPCI, département, région
  publications/autres.json       publications non rattachées (comptes par juridiction et par type)
  rod_crtc/index.json, rod_crtc/<année>.json  rapports d'observations définitives des chambres régionales et
                                 territoriales publiés de 2020 à 2026 : organisme, codes COG, SIREN, date, chambre,
                                 thèmes, liens ccomptes.fr (métadonnées seulement)
  lobbying/organisations.json    organisations inscrites (personnes morales), dépenses déclarées, domaines, ministères
  lobbying/ministeres.json       actions déclarées par ministère ciblé et par domaine, missions LOLF rattachées
  aides_entreprises.json         estimations publiées (périmètre, année, type, source) et données du site reliées

Commandes :
  python pipeline/controle.py collecter --budget 1800   # réseau, reprenable (ccomptes.fr, SIRENE HATVP, SIREN ROD)
  python pipeline/controle.py collecter --budget 7000 --volets ccomptes --sans-anciennes   # pages depuis 2020
  python pipeline/controle.py produire                  # sans réseau

Personnes : aucune personne physique n'est nommée. Pages ccomptes.fr : on ne garde ni les titres des réponses
(« Réponse de M. ... »), ni un résumé contenant une civilité ; rapports des chambres : ni résumé ni texte, aucun
ordonnateur, comptable ou responsable, intitulé non publié si un nom de personne y est possible (civilité, prénom
courant suivi d'un nom en capitales). HATVP : vues dirigeants, collaborateurs, clients,
affiliations et observations jamais lues ; responsables publics visés réduits au ministère ou à l'institution ;
organisation nommée seulement si sa catégorie juridique est 2xxx à 9xxx (sirene.personne_morale), sinon agrégée.
Déclarations de patrimoine et d'intérêts de la HATVP : exclues.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
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
from reproductible import date_sources  # noqa: E402

def id_stable(texte: str) -> int:
    """Identifiant numérique stable d'une adresse (9 chiffres, SHA-256) : hash() varie d'un processus à l'autre."""
    return int(hashlib.sha256(texte.encode("utf-8")).hexdigest()[:15], 16) % 10**9


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


def _article_json_ld(t: str) -> dict:
    m = re.search(r'application/ld\+json[^>]*>(.*?)</script>', t, re.S)
    if not m:
        return {}
    try:
        g = json.loads(m.group(1)).get("@graph", [])
    except json.JSONDecodeError:
        return {}
    return next((x for x in g if isinstance(x, dict) and x.get("@type") == "Article"), {})


def _couche_donnees(t: str) -> dict:
    """Objet `dataLayer.push({...})` de la page : émetteur, institution, catégorie du document, thématique."""
    m = re.search(r"dataLayer\.push\((\{.*?\})\);", t, re.S)
    if not m:
        return {}
    try:
        x = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    return x if isinstance(x, dict) else {}


def _date_point(s: str) -> str | None:
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def extraire_page(url: str, t: str) -> dict:
    """Métadonnées d'une page publication : JSON-LD (titre, juridiction, date, résumé), couche de données de la page
    (institution, catégorie du document, thématique), thèmes complets du bloc principal (le JSON-LD coupe un libellé
    à la virgule), documents typés avec leurs mentions (date de séance, fondement). Titres de réponses écartés."""
    out = {"url": url, "statut": 200}
    art, dl = _article_json_ld(t), _couche_donnees(t)
    out["titre"] = propre(art.get("headline")) or propre(dl.get("titrePublication")) or None
    about = [propre(a) for a in art.get("about") or []]
    jur = [a for a in about if a.isupper() or re.match(r"^(CRC|CTC|CRTC|COUR )", a)]
    out["juridiction"] = propre(dl.get("emetteurPublication")) or (jur[-1] if jur else None)
    out["institution"] = propre(dl.get("institution")) or None
    out["document_publication"] = propre(dl.get("documentPublication")) or None
    i = t.find("left-side-elements")
    bloc = t[i:t.find("</article>", i)] if i >= 0 else ""
    themes = re.findall(r'thematic%3A(\d+)"[^>]*>.*?<div class="field__item">([^<]+)</div>', bloc, re.S)
    out["themes"] = [propre(x) for _, x in themes] if themes else [a for a in about if a not in jur]
    out["themes_id"] = [int(n) for n, _ in themes]
    out["date"] = (art.get("datePublished") or "")[:10] or None
    d = re.search(r'<time class="date section" datetime="(\d{4}-\d{2}-\d{2})"', bloc)
    out["date_affichee"] = d.group(1) if d else None
    out["resume"] = propre(art.get("description")) or None
    node = re.search(r'"currentPath":"node\\/(\d+)"', t)
    out["node"] = int(node.group(1)) if node else (int(dl["idPublication"]) if str(dl.get("idPublication", ""))
                                                    .isdigit() else None)
    docs = []
    for seg in t.split('class="links-with-buttons-inside"')[1:]:
        a = re.search(r'class="doc-type-icon">\s*<a href="([^"]+)"\s+title="([^"]+)"', seg)
        if not a:
            continue
        titre = propre(a.group(2))
        if norm(titre).startswith("reponse"):
            continue
        h2 = re.search(r'<h2 class="title">(.*?)</h2>', seg, re.S)
        infos = [propre(re.sub(r"<[^>]+>", " ", x)) for x in
                 re.findall(r'<div class="list-item">(.*?)</div>', seg.split('class="list-links-wrapper"')[0], re.S)]
        docs.append({"type": titre, "titre": propre(re.sub(r"<[^>]+>", " ", h2.group(1))) if h2 else None,
                     "url": a.group(1) if a.group(1).startswith("http") else CC + a.group(1),
                     "infos": [x for x in infos if x][:6]})
    if not docs:  # gabarit ancien : icônes seules
        for href, titre in re.findall(r'class="doc-type-icon">\s*<a href="([^"]+)"\s+title="([^"]+)"', t):
            titre = propre(titre)
            if not norm(titre).startswith("reponse"):
                docs.append({"type": titre, "url": href if href.startswith("http") else CC + href})
    out["documents"] = docs[:60]
    d = re.search(r"Date de communicabilit[ée]\s*:\s*(\d{2})\.(\d{2})\.(\d{4})", re.sub(r"<[^>]+>", " ", t))
    out["date_communicabilite"] = f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None
    return out


def _ecrire_atomique(chemin: Path, texte: str) -> None:
    """Écriture dans un fichier temporaire puis renommage : une coupure ne laisse jamais un fichier tronqué."""
    import os
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".part")
    tmp.write_text(texte, encoding="utf-8")
    os.replace(tmp, chemin)


def urls_sitemap(rafraichir: bool = False, age_max_s: float = 0) -> list[tuple[str, str]]:
    """(adresse, lastmod) des pages publications. `rafraichir` relit le plan du site, sauf si la copie locale a moins
    de `age_max_s` secondes (une reprise dans la journée ne retélécharge pas 13 Mo)."""
    if rafraichir and SITEMAP.exists() and age_max_s and time.time() - SITEMAP.stat().st_mtime < age_max_s:
        rafraichir = False
    if rafraichir or not SITEMAP.exists():
        try:
            r = http_get(f"{CC}/sitemap_publication/sitemap.xml", tries=2, timeout=120)
            # intégrité : réponse complète (balise fermante, taille annoncée) et jamais une page HTML
            ok = (r.status_code == 200 and "<urlset" in r.text[:2000] and r.text.rstrip().endswith("</urlset>")
                  and (not r.headers.get("Content-Length") or "gzip" in r.headers.get("Content-Encoding", "")
                       or int(r.headers["Content-Length"]) == len(r.content)))
        except RuntimeError:
            ok = False
        if ok:
            SITEMAP.parent.mkdir(parents=True, exist_ok=True)
            _ecrire_atomique(SITEMAP, r.text)
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


PAUSE_S = 1.0               # une requête par seconde au plus vers ccomptes.fr, reprises comprises
PLAN_DEPUIS = "2020-01-01"  # une page publiée en 2020 ou après a un `lastmod` postérieur à sa publication
ETAT_COLLECTE = CACHE_CC / "collecte_etat.json"
REFUS = CACHE_CC / "refus.json"
STATUTS_DEFINITIFS = (200, 404, 410)
# Début d'adresse d'une page au nom d'un organisme (rapports des chambres régionales) : lues en premier.
SLUG_ORGANISME = re.compile(
    r"^(commune|ville|communaute|metropole|syndicat|sivom|sivu|smi|departement|region|collectivite|centre|"
    r"etablissement|ehpad|hopital|groupement|gip|office|opac|oph|regie|societe|sem|spl|association|lycee|college|"
    r"ecole|universite|institut|caisse|chambre|maison|service|agence|conseil|comite|district|port|aeroport|parc|"
    r"pole|theatre|opera|orchestre|musee|epf|epa|sdis|ccas|cias|fondation|territoire|sictom|smictom|smirt|"
    r"pays|petr|eple|cfa)-")


def _quand(lastmod: str | None) -> datetime:
    try:
        d = datetime.fromisoformat(str(lastmod))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def ordre_de_lecture(plan: list[tuple[str, str]], deja: dict, depuis: str | None = PLAN_DEPUIS,
                     anciennes: bool = True, relire_memoire: bool = True) -> list[tuple[str, str]]:
    """Pages à lire, par priorité : (1) jamais lues, modifiées depuis `depuis`, au nom d'un organisme ; (2) les autres
    jamais lues depuis `depuis` ; (3) déjà lues mais modifiées depuis la lecture (`lastmod` du plan plus récent) ;
    (4) si `anciennes`, les pages jamais lues modifiées avant `depuis` ; (5) si `relire_memoire`, les pages connues par
    la seule mémoire publiée (déjà publiées, absentes du cache). Chaque groupe : la plus récente d'abord."""
    seuil = _quand(depuis + "T00:00:00+00:00") if depuis else None
    groupes = ([], [], [], [], [])
    for u, lm in plan:
        x = deja.get(u)
        recent = seuil is None or _quand(lm) >= seuil
        if x is None or x.get("statut") not in STATUTS_DEFINITIFS:
            if recent:
                groupes[0 if SLUG_ORGANISME.match(u.rsplit("/", 1)[-1]) else 1].append((u, lm))
            elif anciennes:
                groupes[3].append((u, lm))
        elif x.get("memoire"):
            if relire_memoire and (recent or anciennes):
                groupes[4].append((u, lm))
        elif recent and x.get("lastmod_plan") and _quand(lm) > _quand(x["lastmod_plan"]):
            groupes[2].append((u, lm))
    return [e for g in groupes for e in sorted(g, key=lambda e: _quand(e[1]), reverse=True)]


class Cadence:
    """Espacement global des requêtes (toutes tâches et toutes reprises confondues) ; `suspendre` décale la suivante."""

    def __init__(self, pause_s: float):
        import threading
        self.pause_s, self.verrou, self.prochain = pause_s, threading.Lock(), time.monotonic()

    def attendre(self) -> None:
        with self.verrou:
            maintenant = time.monotonic()
            attente = self.prochain - maintenant
            self.prochain = max(self.prochain, maintenant) + self.pause_s
        if attente > 0:
            time.sleep(attente)

    def suspendre(self, secondes: float) -> None:
        with self.verrou:
            self.prochain = max(self.prochain, time.monotonic() + secondes)


def collecter_ccomptes(budget_s: float, paralleles: int = 2, pause_s: float = PAUSE_S, depuis: str | None = None,
                       anciennes: bool = True, max_echecs: int = 5, max_pauses: int = 3, essais: int = 3,
                       pause_incident_s: float = 120, pause_essai_s: float = 5) -> dict:
    """Lit les pages de publication de ccomptes.fr dans l'ordre de `ordre_de_lecture`, au plus une requête par
    `pause_s` secondes. Reprenable : chaque page lue est ajoutée aussitôt au cache (une ligne JSON) ; une page déjà lue
    n'est relue que si le plan du site la dit modifiée depuis. Arrêts : budget écoulé ; premier 403 ou 429 (refus noté,
    jamais contourné) ; serveur indisponible (après `max_echecs` erreurs 5xx ou délais consécutifs, pause de 2, 4 puis
    6 minutes ; au-delà de `max_pauses` pauses sans succès, arrêt noté). Un verrou empêche deux collectes simultanées.
    Une page en erreur est retentée `essais` fois, chaque reprise passant par la même cadence."""
    import fcntl
    CACHE_CC.mkdir(parents=True, exist_ok=True)
    verrou_f = (CACHE_CC / "collecte.lock").open("a")
    try:
        fcntl.flock(verrou_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        verrou_f.close()
        print("  ccomptes.fr : une autre collecte est en cours, rien à faire", file=sys.stderr)
        return {"arret": "collecte déjà en cours"}
    try:
        return _collecter_ccomptes(budget_s, paralleles, pause_s, depuis, anciennes, max_echecs, max_pauses, essais,
                                   pause_incident_s, pause_essai_s)
    finally:
        verrou_f.close()  # libère le verrou


def _collecter_ccomptes(budget_s, paralleles, pause_s, depuis, anciennes, max_echecs, max_pauses, essais,
                        pause_incident_s, pause_essai_s) -> dict:
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import requests
    plan = urls_sitemap(rafraichir=True, age_max_s=12 * 3600)
    deja = pages_connues()
    a_faire = ordre_de_lecture(plan, deja, depuis or PLAN_DEPUIS, anciennes=anciennes)
    print(f"  ccomptes.fr : {len(plan)} pages au plan du site, {len(deja)} en cache, {len(a_faire)} à lire",
          file=sys.stderr)
    debut, verrou, cadence = time.monotonic(), threading.Lock(), Cadence(pause_s)
    etat = {"arret": None, "echecs": 0, "pauses": 0, "lues": 0, "codes": Counter()}
    f = PUBS.open("a", encoding="utf-8")

    def ecrire(x: dict) -> None:
        with verrou:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
            f.flush()
            etat["lues"] += 1
            if etat["lues"] % 100 == 0:
                os.fsync(f.fileno())
                print(f"  ccomptes.fr : {etat['lues']} pages lues ({time.monotonic() - debut:.0f} s)", file=sys.stderr)

    def tache(e):
        u, lastmod = e
        for essai in range(essais):
            if etat["arret"] or time.monotonic() - debut > budget_s:
                return
            cadence.attendre()
            if etat["arret"]:
                return
            try:
                r = requests.get(u, timeout=40, headers=UA, allow_redirects=True)
                code, err = r.status_code, None
            except requests.RequestException as exc:
                r, code, err = None, None, type(exc).__name__
            with verrou:
                etat["codes"][code or err] += 1
            if code in (403, 429):
                etat["arret"] = f"HTTP {code} sur {u} : collecte arrêtée, non contournée"
                return
            if code is not None and code < 500:
                with verrou:
                    etat["echecs"], etat["pauses"] = 0, 0
                x = extraire_page(u, r.text) if code == 200 else {"url": u, "statut": code}
                x["lastmod_plan"] = lastmod
                x["lu_le"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                ecrire(x)
                return
            with verrou:  # erreur serveur ou réseau
                etat["echecs"] += 1
                if etat["echecs"] >= max_echecs:
                    etat["echecs"] = 0
                    etat["pauses"] += 1
                    if etat["pauses"] > max_pauses:
                        etat["arret"] = (f"serveur indisponible : {max_echecs} erreurs consécutives après {max_pauses} "
                                         f"pauses (dernière : {code or err} sur {u}) ; collecte arrêtée")
                        return
                    print(f"  ccomptes.fr : {max_echecs} erreurs consécutives ({code or err}), pause de "
                          f"{pause_incident_s * etat['pauses']:.0f} s", file=sys.stderr)
                    cadence.suspendre(pause_incident_s * etat["pauses"])
            cadence.suspendre(pause_essai_s * (essai + 1))

    try:
        with ThreadPoolExecutor(paralleles) as ex:
            list(ex.map(tache, a_faire))
    finally:
        f.close()
    lues = charger_pubs()
    restantes = len(ordre_de_lecture(plan, pages_connues(), depuis or PLAN_DEPUIS, anciennes=anciennes,
                                     relire_memoire=False))
    bilan = {"le": datetime.now(timezone.utc).isoformat(timespec="seconds"), "duree_s": round(time.monotonic() - debut),
             "pause_s": pause_s, "paralleles": paralleles, "depuis": depuis or PLAN_DEPUIS, "anciennes": anciennes,
             "a_lire_au_depart": len(a_faire), "lues": etat["lues"], "restantes": restantes,
             "codes_http": {str(k): v for k, v in sorted(etat["codes"].items(), key=lambda kv: str(kv[0]))},
             "arret": etat["arret"]}
    _ecrire_atomique(ETAT_COLLECTE, json.dumps(bilan, ensure_ascii=False, indent=1))
    if etat["arret"]:
        print(f"  {etat['arret']}", file=sys.stderr)
        _ecrire_atomique(REFUS, json.dumps({"motif": etat["arret"], "le": bilan["le"]}, ensure_ascii=False))
    elif REFUS.exists():  # passage sans incident : le refus précédent n'est plus d'actualité
        REFUS.unlink()
    print(f"  ccomptes.fr : {len(lues)} pages en cache, {restantes} restent à lire", file=sys.stderr)
    return bilan


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


def resoudre_hatvp(budget_s: float, pause_s: float | None = None, paralleles: int = 10) -> None:
    """Catégorie juridique des SIREN du répertoire (cache du module) ; `pause_s` entre deux requêtes (défaut : celui
    de pipeline/sirene.py)."""
    sirens = [p["identifiantNational"] for p in charger_hatvp() if p.get("typeIdentifiantNational") == "SIREN"]
    ancien, ancienne_pause = sirene.CACHE, sirene.PAUSE_S
    sirene.CACHE, sirene.PAUSE_S = CACHE_SIRENE, (pause_s if pause_s is not None else sirene.PAUSE_S)
    try:
        cache, restants = sirene.resoudre(sirens, budget_s=budget_s, cache=charger_sirene(), paralleles=paralleles)
    finally:
        sirene.CACHE, sirene.PAUSE_S = ancien, ancienne_pause
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
    deps, regions, communes, epcis, noms_region, siege_epci = {}, {}, defaultdict(dict), defaultdict(dict), {}, {}
    for f in sorted((SITE / "local" / "geo").glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        d = g["departement"]
        deps[jeton(d["nom"])] = d["code"]
        if g.get("region"):
            regions[jeton(g["region"]["nom"])] = g["region"]["code"]
            noms_region[g["region"]["code"]] = g["region"]["nom"]
        for insee, c in g["communes"].items():
            communes[d["code"]].setdefault(jeton(c["nom"]), []).append(
                {"insee": insee, "epci": c.get("epci"), "region": c.get("region"), "siren": c.get("siren")})
        for siren, e in g.get("epci", {}).items():
            epcis[d["code"]][cle_epci(e["nom"])] = siren
            siege_epci[siren] = e.get("departement_siege")
    reg_dep = {}
    for f in sorted((SITE / "local" / "geo").glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        reg_dep[g["departement"]["code"]] = (g.get("region") or {}).get("code")
    return {"deps": deps, "regions": regions, "communes": communes, "epcis": epcis, "reg_dep": reg_dep,
            "noms_dep": {v: k for k, v in deps.items()}, "noms_region": noms_region, "siege_epci": siege_epci}


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


def memoire_pages_cour() -> dict:
    """Publications de la Cour lues sur ccomptes.fr et déjà publiées (publications/programmes.json, autres.json),
    remises sous la forme d'une page lue : même rôle que `memoire_rod` (un cache de collecte en retard ne les retire
    pas ; une page relue les remplace ; une page en 404 les retire)."""
    pages = {}
    for nom in ("programmes.json", "autres.json"):
        f = SORTIE / "publications" / nom
        try:
            d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            d = {}
        for e in d.get("publications", []):
            if e.get("source") != SRC_PAGES:
                continue
            m = re.match(r"^cc-(\d+)$", e["id"])
            pages[e["url"]] = {"url": e["url"], "statut": 200, "titre": e["titre"], "juridiction": e.get("juridiction"),
                               "date": e.get("date"), "node": int(m.group(1)) if m else None,
                               "documents": [{"type": e["type"], "url": e["url_document"]}] if e.get("url_document")
                               else [], "constats_memoire": e.get("constats_chiffres") or [], "memoire": True}
    return pages


def juridiction_lisible(j: str | None) -> str | None:
    """'COUR DES COMPTES' -> 'Cour des comptes' (forme en capitales des pages ccomptes.fr)."""
    j = propre(j)
    return (j.capitalize() if j.isupper() else j) or None


def lire_pages_ccomptes() -> list[dict]:
    """Pages lues de la Cour et des autres institutions, mémoire publiée comprise (les pages des chambres régionales
    et territoriales passent par `construire_rod`)."""
    pages = memoire_pages_cour()
    for u, x in charger_pubs().items():
        if x.get("statut") in (404, 410):
            pages.pop(u, None)
        elif x.get("statut") == 200:
            pages[u] = x
    out = []
    for u in sorted(pages):
        x = pages[u]
        if not x.get("titre") or est_page_crtc(x):
            continue
        docs = x.get("documents") or []
        principal = next((d for d in docs if TYPES_CONNUS.match(d["type"] or "")), None)
        constats = x["constats_memoire"] if "constats_memoire" in x else \
            constats_chiffres(texte_sans_personne(x.get("resume")))
        out.append({"id": f"cc-{x.get('node') or id_stable(x['url'])}", "titre": x["titre"],
                    "date": x.get("date"), "annee": int(x["date"][:4]) if x.get("date") else None,
                    "type": principal["type"] if principal else None,
                    "juridiction": juridiction_lisible(x.get("juridiction")),
                    "themes": x.get("themes") or [], "url": x["url"],
                    "url_document": principal["url"] if principal else None,
                    "constats_chiffres": constats, "lu_le": x.get("lu_le"), "source": SRC_PAGES})
    return out


def pages_connues() -> dict:
    """Pages lues (cache) et pages connues par la seule mémoire publiée (rapports des chambres, publications de la
    Cour) : ces dernières ne sont relues qu'en dernier (voir `ordre_de_lecture`)."""
    memoire = {**memoire_pages_cour(), **memoire_rod()[0]}
    return {**{u: {"url": u, "statut": 200, "memoire": True} for u in memoire}, **charger_pubs()}


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


def produire_controle(geo: dict, fiches_rod: list[dict]) -> dict:
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
                rss.append({"id": f"rss-{id_stable(u)}", "titre": propre(re.sub(r"<!\[CDATA\[|\]\]>", "",
                            ti.group(1))), "date": date, "annee": int(date[:4]) if date else None, "type": None,
                            "juridiction": None, "url": u, "source": "ccomptes.fr, flux RSS des publications"})
    # Collectivités : ROD des CRC 2015-2019 (métadonnées data.gouv) + ROD 2020-2026 (pages ccomptes.fr)
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
    pages_cour = pages
    for f in fiches_rod:
        e = {k: f[k] for k in ("id", "titre", "date", "annee", "type", "url", "url_document", "source",
                                "organisme_type", "niveau", "codes", "rattachement", "themes", "siren")
             if f.get(k) is not None}
        e["juridiction"] = f["chambre"]
        if f["organisme"]:
            e["organisme"] = f["organisme"]
        if f["codes"]["departement"]:
            par_dep[f["codes"]["departement"]].append(e); comptes_niveau[e["niveau"]] += 1
        elif f["codes"]["region"]:
            par_dep[f"region_{f['codes']['region']}"].append(e); comptes_niveau[e["niveau"]] += 1
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
        lst.sort(key=lambda x: (x.get("date") or "", x["id"]), reverse=True)
        nom = None
        f = SITE / "local" / "geo" / f"{dep}.json"
        if f.exists():
            nom = json.loads(f.read_text(encoding="utf-8"))["departement"]["nom"]
        elif dep.startswith("region_"):
            nom = geo["noms_region"].get(dep[7:])
        c = Counter(e["niveau"] for e in lst)
        chemin = f"publications/collectivites/{dep}.json"
        fichiers[chemin] = dump(SORTIE / chemin, {
            "millesime": "Rapports d'observations définitives : 2015 à 2019 (métadonnées data.gouv.fr), 2020 à 2026 "
                         "(pages ccomptes.fr lues)", "source": f"{SRC_META_ROD} ; {SRC_ROD} ; {SRC_GEO}",
            "departement": {"code": dep, "nom": nom},
            "comptes_par_niveau": dict(c), "publications": lst})
        index_deps.append({"code": dep, "nom": nom, "fichier": f"controle/{chemin}", "publications": len(lst),
                           "par_niveau": dict(c)})
    for f in sorted((SORTIE / "publications" / "collectivites").glob("*.json")):
        if f"publications/collectivites/{f.name}" not in fichiers:
            f.unlink()  # département sans rapport ce passage : fichier retiré
    autres_c = Counter((e.get("juridiction") or "inconnue", e.get("type") or "non précisé") for e in autres)
    fichiers["publications/autres.json"] = dump(SORTIE / "publications" / "autres.json", {
        **entete, "note": "Publications lues mais rattachées à aucun programme ni à aucune collectivité.",
        "comptes": [{"juridiction": j, "type": t, "publications": n} for (j, t), n in autres_c.most_common()],
        "publications": sorted(autres, key=lambda x: x.get("date") or "", reverse=True),
        "non_localisees": non_localises})
    plan = urls_sitemap() if SITEMAP.exists() else []
    lues = pages_connues()
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
                                "lecture": "les pages non lues ne sont pas publiées (aucune métadonnée devinée) ; "
                                           "les pages déjà publiées comptent comme lues (mémoire publiée)"}}


# --- 1 bis. Rapports d'observations définitives des chambres régionales et territoriales (2020 à 2026) -------------

ROD_DEBUT, ROD_FIN = "2020-01-01", "2026-12-31"
SORTIE_ROD = SORTIE / "rod_crtc"
CACHE_ROD_SIREN = LAKE / "_cache" / "controle_rod_siren.json"
API_ENTREPRISES = "https://recherche-entreprises.api.gouv.fr/search"
SRC_ROD = ("ccomptes.fr, pages des publications des chambres régionales et territoriales des comptes listées par le plan "
           "du site sitemap_publication (métadonnées schema.org et données de la page : chambre, catégorie, thèmes, "
           "documents)")
SRC_SIREN_ROD = ("API Recherche d'entreprises (recherche-entreprises.api.gouv.fr, répertoire SIRENE de l'Insee) : SIREN "
                 "et catégorie juridique")
SRC_GEO = "geo.api.gouv.fr, code officiel géographique en vigueur (site/data/local/geo)"
TYPE_ROD = re.compile(r"rapports? d.observations? d[ée]finitives?", re.I)
DOC_ANNEXE = re.compile(r"^(synth[eè]se|les [ée]l[ée]ments cl[ée]s|r[ée]ponses?|annexes?|fiche|communiqu)", re.I)
INSTITUTIONS_CRTC = ("CRC", "CTC", "CRTC")
TERRITOIRES_CTC = {"polynesie francaise": "Polynésie française", "nouvelle caledonie": "Nouvelle-Calédonie",
                   "saint pierre et miquelon": "Saint-Pierre-et-Miquelon", "saint barthelemy": "Saint-Barthélemy",
                   "saint martin": "Saint-Martin", "wallis et futuna": "Wallis-et-Futuna"}
SEPARATEUR_TITRE = re.compile(r"\s+[-\u2013\u2014]\s+|\s+:\s+|\s:\s|\.\s+(?=[A-ZÉÈ«])")
# Type d'organisme lu au début du nom (texte normalisé) : (motif, libellé, niveau de rattachement). Tous ces organismes
# sont des personnes morales (collectivités, établissements publics, sociétés, associations, groupements).
TYPES_ORGANISME = [
    (r"(commune nouvelle|commune|ville|mairie)", "commune", "commune"),
    (r"(communaute de communes|cc)", "communauté de communes", "epci"),
    (r"(communaute d agglomeration|ca)", "communauté d'agglomération", "epci"),
    (r"(communaute urbaine|cu)", "communauté urbaine", "epci"),
    (r"metropole", "métropole", "epci"),
    (r"(etablissement public territorial|ept)", "établissement public territorial", "autre_organisme"),
    (r"(departement|conseil departemental|conseil general|collectivite europeenne d alsace)", "département",
     "departement"),
    (r"(region|conseil regional)", "région", "region"),
    (r"collectivite (territoriale )?(de corse|de guyane|de martinique)", "collectivité territoriale unique", "region"),
    (r"(collectivite (de la |d |de )?(polynesie|nouvelle caledonie|saint|wallis)|pays de la nouvelle caledonie|"
     r"province|gouvernement de la polynesie|assemblee de la polynesie|polynesie francaise|nouvelle caledonie)",
     "collectivité d'outre-mer", "autre_organisme"),
    (r"(syndicat|sivom|sivu|sictom|smictom|smirtom|sitom|siaep|sdis?e|sde|sdee|siea|siaam|smi|sma|smb|sm|"
     r"pole d equilibre territorial|petr|parc naturel regional|pole metropolitain)",
     "syndicat ou groupement de collectivités",
     "autre_organisme"),
    (r"(centre communal d action sociale|centre intercommunal d action sociale|ccas|cias)",
     "centre d'action sociale", "autre_organisme"),
    (r"(centre hospitalier|groupe hospitalier|groupement hospitalier|hopital|hopitaux|assistance publique|chu|chr|"
     r"chi|chs|ehpad|etablissement d hebergement|maison de retraite|centre de soins|institut medico|"
     r"etablissement public de sante|etablissement public medico|centre departemental de l enfance)",
     "établissement de santé ou médico-social", "autre_organisme"),
    (r"(service departemental d incendie|service departemental et metropolitain d incendie|sdis|sdmis|"
     r"service territorial d incendie)", "service d'incendie et de secours", "autre_organisme"),
    (r"(office public de l habitat|office public d habitat|office public d hlm|oph|opac|office public d amenagement|"
     r"office public departemental de l habitat|office public departemental d habitat|office public territorial de "
     r"l habitat|office public intercommunal)",
     "office public de l'habitat", "autre_organisme"),
    (r"(societe d economie mixte|societe anonyme d economie mixte|sem|saem|semop|societe publique locale|spl|spla|"
     r"societe d amenagement|societe)", "société (économie mixte, publique locale ou autre)", "autre_organisme"),
    (r"(association|fondation)", "association ou fondation", "autre_organisme"),
    (r"(lycee|college|cite scolaire|etablissement public local d enseignement|eple)",
     "établissement public local d'enseignement", "autre_organisme"),
    (r"(universite|ecole|institut|conservatoire|centre de formation|cfa|crous|centre regional des oeuvres|"
     r"etablissement d enseignement superieur)",
     "établissement d'enseignement ou de formation", "autre_organisme"),
    (r"(groupement d interet public|gip|groupement de cooperation|groupement d interet economique|gie)",
     "groupement d'intérêt public ou de coopération", "autre_organisme"),
    (r"(office de tourisme|office du tourisme|office intercommunal de tourisme|office de tourisme intercommunal)",
     "office de tourisme", "autre_organisme"),
    (r"(chambre de commerce|chambre regionale de commerce|chambre d agriculture|chambre regionale d agriculture|"
     r"chambre de l agriculture|chambre de metiers|chambre des metiers|chambre regionale de metiers|"
     r"chambre regionale des metiers|cci|cma)", "chambre consulaire", "autre_organisme"),
    (r"(caisse des ecoles|caisse de credit municipal|credit municipal|caisse)", "caisse ou établissement public local",
     "autre_organisme"),
    (r"(centre de gestion|centre interdepartemental de gestion|centre departemental de gestion)",
     "centre de gestion de la fonction publique territoriale", "autre_organisme"),
    (r"(maison departementale des personnes handicapees|maison departementale des adolescents|maison des adolescents|"
     r"mdph)", "maison départementale (groupement d'intérêt public ou association)", "autre_organisme"),
    (r"(comite des oeuvres sociales|comite d action sociale|amicale du personnel)", "association ou fondation",
     "autre_organisme"),
    (r"(agence|comite departemental|comite regional)", "agence ou comité (association ou établissement public)",
     "autre_organisme"),
    (r"(orchestre|theatre|opera|maison de la culture|maison de la danse|musee|scene nationale|bibliotheque|"
     r"cite de la musique|centre dramatique|centre choregraphique|festival)", "établissement culturel (association, "
     r"régie ou établissement public)", "autre_organisme"),
    (r"(grand port maritime|port autonome|port|aeroport)", "établissement portuaire ou aéroportuaire",
     "autre_organisme"),
    (r"(regie|etablissement public|epic|epcc|epa|epf|epl|epcc)", "établissement public ou régie", "autre_organisme"),
]
TYPES_ORGANISME_RE = [(re.compile(rf"^{m}\b"), t, n) for m, t, n in TYPES_ORGANISME]
INTERCOMMUNALITE = re.compile(r"\b(communaute|agglomeration|agglo|metropole)\b")
# Département désigné autrement que par son nom (parenthèse ou titre).
ALIAS_DEP = {"metropole de lyon": "69", "region de lyon": "69"}
# Prénoms fréquents (majuscules sans accents) : « Prénom NOM » dans un intitulé = nom de personne possible.
PRENOMS_COURANTS = {
    "JEAN", "MARIE", "PIERRE", "MICHEL", "PHILIPPE", "ALAIN", "ANDRE", "BERNARD", "JACQUES", "NICOLAS", "CHRISTOPHE",
    "FRANCOIS", "DANIEL", "PATRICK", "CATHERINE", "NATHALIE", "ISABELLE", "SYLVIE", "MARTINE", "CHRISTINE", "FRANCOISE",
    "MONIQUE", "VALERIE", "SANDRINE", "STEPHANE", "PASCAL", "ERIC", "LAURENT", "FREDERIC", "OLIVIER", "THIERRY",
    "DAVID", "JULIEN", "SEBASTIEN", "GERARD", "CLAUDE", "SERGE", "DOMINIQUE", "YVES", "ROGER", "LOUIS", "PAUL",
    "HENRI", "GEORGES", "ROBERT", "RENE", "MARCEL", "JOSEPH", "ANNE", "SOPHIE", "CELINE", "AURELIE", "EMILIE",
    "JULIE", "CAROLINE", "SANDRA", "STEPHANIE", "VIRGINIE", "VERONIQUE", "BRIGITTE", "JACQUELINE", "NICOLE",
    "DENISE", "HELENE", "LAURENCE", "AGNES", "CORINNE", "PASCALE", "PATRICIA", "CHANTAL", "FLORENCE", "ELISABETH",
    "GUY", "JEROME", "FABRICE", "CEDRIC", "VINCENT", "BRUNO", "DIDIER", "FRANCK", "GILLES", "HERVE", "JOEL", "LUC",
    "MARC", "MATHIEU", "MAXIME", "REMI", "ROMAIN", "THOMAS", "XAVIER", "YANNICK", "ANTOINE", "ALEXANDRE", "ARNAUD"}


def nom_de_personne_possible(s: str | None) -> bool:
    """Civilité suivie d'une capitale, ou prénom fréquent suivi d'un nom en capitales (« Jean DUPONT »). Les sigles
    d'organismes en capitales (« Association AIDAPHI ») ne sont pas des noms de personne."""
    s = propre(s)
    if CIVILITE.search(s):
        return True
    for m in PRENOM_NOM.finditer(s):
        prenom = unicodedata.normalize("NFKD", m.group(0).split()[0]).encode("ascii", "ignore").decode().upper()
        if prenom.split("-")[0] in PRENOMS_COURANTS:
            return True
    return False


def _code_dep_alias(geo: dict, s: str | None) -> str | None:
    return code_departement(geo, s) or ALIAS_DEP.get(jeton(s or ""))


def chambre(geo: dict, juridiction: str | None) -> dict:
    """'CRC ÎLE-DE-FRANCE' -> nom lisible, régions et départements du ressort (code officiel géographique)."""
    j = propre(juridiction)
    m = re.match(r"(?i)^(CRTC|CRC|CTC)\s+(.+)$", j)
    if not m:
        return {"juridiction": j or None, "nom": j or None, "regions": [], "departements": [], "hors_cog": False}
    sigle, reste = m.group(1).upper(), m.group(2)
    if jeton(reste) in geo["regions"]:
        regions = [geo["regions"][jeton(reste)]]
    else:
        regions = list(dict.fromkeys(geo["regions"][jeton(x)] for x in re.split(r"\s*,\s*|\s+-\s+|\s+et\s+", reste)
                                     if jeton(x) in geo["regions"]))
    noms = [geo["noms_region"][r] for r in regions] or [TERRITOIRES_CTC.get(jeton(reste), reste.title())]
    nature = {"CRC": "régionale", "CTC": "territoriale"}.get(sigle, "régionale et territoriale")
    deps = sorted(d for d, r in geo["reg_dep"].items() if r in regions)
    return {"juridiction": j, "nom": f"Chambre {nature} des comptes " + ", ".join(noms), "regions": regions,
            "departements": deps, "hors_cog": not regions}


def est_page_crtc(x: dict) -> bool:
    return (x.get("institution") or "").upper() in INSTITUTIONS_CRTC or \
        bool(re.match(r"(?i)^(CRC|CTC|CRTC)\b", x.get("juridiction") or ""))


def est_rod(x: dict) -> bool:
    """Page d'une chambre régionale ou territoriale dont un document est un rapport d'observations définitives, ou de
    catégorie « Rapport » (gabarit des chambres territoriales : le document porte le titre du rapport)."""
    if x.get("statut") != 200 or not x.get("titre") or not est_page_crtc(x):
        return False
    types = [d.get("type") or "" for d in x.get("documents") or []]
    if any(TYPE_ROD.search(t) for t in types):
        return True
    return x.get("document_publication") == "Rapport" and any(t and not DOC_ANNEXE.match(t) for t in types)


def type_organisme(nom: str) -> tuple[str | None, str]:
    t = jeton(nom)
    for motif, libelle, niveau in TYPES_ORGANISME_RE:
        if motif.match(t):
            return libelle, niveau
    if INTERCOMMUNALITE.search(t):  # « Pays de Châteaugiron Communauté »
        return "intercommunalité", "epci"
    return None, "autre_organisme"


def _parentheses(s: str) -> list[str]:
    return re.findall(r"\(([^()]+)\)", s or "")


def _sans_parenthese_finale(s: str) -> str:
    return re.sub(r"\s*\([^()]*\)\s*$", "", s or "").strip()


def _commune_unique(geo: dict, nom: str, deps: list[str]) -> tuple[str, dict] | None:
    """(département, commune) si le nom désigne une seule commune des départements donnés (COG en vigueur)."""
    trouve = [(d, c) for d in deps for c in geo["communes"].get(d, {}).get(jeton(nom), [])]
    return trouve[0] if len(trouve) == 1 else None


def _noms_de_commune(organisme: str) -> list[str]:
    """'Commune de la Chapelle-sur-Erdre' -> ['la Chapelle-sur-Erdre', 'Chapelle-sur-Erdre'] : l'article du titre est
    gardé (« de la », « du », « des », « de l' » deviennent « la », « le », « les », « l' »)."""
    m = re.match(r"(?i)^(?:commune nouvelle|commune|ville|mairie)\s+(?:(de\s+la\b|de\s+l['’]|du\b|des\b)\s*|"
                 r"de\s+|d['’]\s*)?(.+)$", organisme)
    if not m:
        return []
    reste = m.group(2).strip()
    art = {"de la": "la ", "du": "le ", "des": "les "}.get(re.sub(r"\s+", " ", (m.group(1) or "").lower()),
                                                         "l'" if m.group(1) else "")
    noms = [reste]
    premier = re.split(r"\s+et\s+|\s*,\s*|\s+dans le cadre\b|\s*[-\u2013\u2014]\s+", reste, maxsplit=1)[0].strip()
    if premier and premier != reste:  # « Commune de Vichy et Vichy Communauté »
        noms.append(premier)
    return list(dict.fromkeys(x for n in noms for x in ([art + n, n] if art else [n])))


def analyser_rod(geo: dict, x: dict) -> dict:
    """Organisme contrôlé, type, codes COG (commune, EPCI, département, région) et méthode de rattachement, lus dans le
    titre et la chambre d'un rapport. Le département vient, dans l'ordre : d'une parenthèse du titre (nom ou numéro),
    du nom de la commune (organisme « commune »), du nom d'un département du ressort cité dans le titre, du ressort
    s'il ne compte qu'un département."""
    titre = propre(x["titre"])
    ch = chambre(geo, x.get("juridiction"))
    ressort = ch["departements"]
    tete = SEPARATEUR_TITRE.split(titre, maxsplit=1)[0].strip()
    for par in _parentheses(tete):  # « Commune de Marseille (Bouches-du-Rhône) cahier n° 2 »
        if _code_dep_alias(geo, par):
            tete = tete[:tete.index(f"({par})")].strip() or tete
            break
    tete = re.sub(r"[\s\-\u2013\u2014,;:.]+$", "", tete)
    base = tete
    while True:  # parenthèses finales : département ou sigle
        b = _sans_parenthese_finale(base)
        if b == base or not b:
            break
        base = b
    typ, niveau = type_organisme(base)
    dep, methodes = None, []

    def dans_ressort(code):  # chambre d'une collectivité d'outre-mer hors COG : aucun département
        return bool(code) and not ch["hors_cog"] and (not ressort or code in ressort)

    for par in _parentheses(titre):
        c = _code_dep_alias(geo, par)
        if dans_ressort(c):
            dep = c
            methodes.append("département entre parenthèses dans le titre")
            break
    commune = None
    if niveau == "commune" and not ch["hors_cog"]:
        trouve = None
        for nom_c in _noms_de_commune(base):
            trouve = _commune_unique(geo, nom_c, [dep] if dep else ressort)
            if trouve:
                break
        if trouve:
            if not dep:
                methodes.append("commune unique de ce nom dans le ressort de la chambre")
            dep, commune = trouve
    if not dep:
        for par in _parentheses(titre):
            for n in re.findall(r"\b(\d{2,3}|2[AB])\b", par):
                if n in geo["reg_dep"] and dans_ressort(n):
                    dep = n
                    methodes.append("numéro de département entre parenthèses dans le titre")
                    break
            if dep:
                break
    if not dep and ressort:
        t = " " + jeton(tete) + " "
        noms = [(n, d) for d in ressort for n in [geo["noms_dep"].get(d)] + [a for a, c in ALIAS_DEP.items() if c == d]
                if n]
        cands = [(len(n), d) for n, d in noms
                 if re.search(rf" (de|du|des|d|de la|de l|en|la|le|les|l) {re.escape(n)} ", t) or t.endswith(f" {n} ")]
        if not cands:  # « Association Sarthe tourisme » : nom seul, retenu s'il ne désigne qu'un département
            vus = [(n, d) for n, d in noms if len(n) >= 4 and f" {n} " in t]
            vus = [(n, d) for n, d in vus if not any(n != m and f" {n} " in f" {m} " for m, _ in vus)]
            if len({d for _, d in vus}) == 1:
                cands = [(len(vus[0][0]), vus[0][1])]
        if cands:
            dep = max(cands)[1]
            methodes.append("nom d'un département du ressort cité dans le titre")
    if not dep and len(ressort) == 1:
        dep = ressort[0]
        methodes.append("ressort de la chambre (un seul département)")
    region = geo["reg_dep"].get(dep) if dep else None
    if niveau == "region" or (typ == "collectivité territoriale unique"):
        r = geo["regions"].get(jeton(re.sub(r"(?i)^(r[ée]gion|conseil r[ée]gional|collectivit[ée]( territoriale)?)"
                                             r"\s+(de\s+la\s+|de\s+l['’]|de\s+|d['’]|du\s+|des\s+)?", "", base)))
        if r:
            region = r
            methodes.append("nom de la région dans le titre")
        elif len(ch["regions"]) == 1:
            region = ch["regions"][0]
            methodes.append("région du ressort de la chambre")
        if niveau == "region" and typ == "région":
            dep = None  # une région n'est pas rattachée à un département
            methodes = [m for m in methodes if "département" not in m and "commune" not in m]
    codes = {"commune": None, "epci": None, "departement": dep, "region": region}
    siren, siren_methode = None, None
    if commune:
        codes.update(commune=commune["insee"], epci=commune["epci"])
        siren, siren_methode = commune.get("siren"), "SIREN de la commune (code officiel géographique)"
        methodes.append("nom de la commune (COG en vigueur)")
    elif niveau == "commune":
        methodes.append("commune absente du COG en vigueur ou homonyme : département seul")
    elif niveau == "epci":
        cle = cle_epci(base)
        trouve = sorted({(s, d) for d in ([dep] if dep else []) + ressort for s in [geo["epcis"].get(d, {}).get(cle)]
                         if s})
        if len({s for s, _ in trouve}) == 1:
            codes["epci"] = siren = trouve[0][0]
            siren_methode = "SIREN de l'EPCI (code officiel géographique)"
            methodes.append("nom de l'EPCI (COG en vigueur)")
            if not dep:
                siege = geo["siege_epci"].get(siren)
                dep = siege if siege in geo["reg_dep"] else trouve[0][1] if len({d for _, d in trouve}) == 1 else None
                if dep:
                    codes.update(departement=dep, region=geo["reg_dep"].get(dep))
                    methodes.append("département du siège de l'EPCI (COG en vigueur)")
        else:
            methodes.append("EPCI absent du COG en vigueur (fusion, dissolution, autre intitulé) : département seul")
    elif niveau == "autre_organisme" and dep:
        # commune du siège : dernier « de X » du nom, s'il désigne une seule commune du département
        m = re.match(r"(?i)^.*(?:\s(de\s+la|de\s+l['’]|de|du|des|à)\s+|\s(d['’]|l['’]))\s*([^()]+)$", base)
        trouve = None
        if m and not re.search(r"\s(et|ou)\s", m.group(3)):
            art = {"de la": "la ", "du": "le ", "des": "les "}.get(re.sub(r"\s+", " ", (m.group(1) or "").lower()),
                                                                 "l'" if re.match(r"(?i)de\s+l", m.group(1) or "")
                                                                 else "")
            for nom_c in dict.fromkeys([art + m.group(3), m.group(3)] if art else [m.group(3)]):
                trouve = _commune_unique(geo, nom_c, [dep])
                if trouve:
                    break
            if trouve:
                codes.update(commune=trouve[1]["insee"], epci=trouve[1]["epci"])
                methodes.append("commune citée à la fin du nom de l'organisme (COG en vigueur)")
    if not dep and not codes["region"] and len(ch["regions"]) == 1:
        codes["region"] = ch["regions"][0]
        methodes.append("région du ressort de la chambre")
    if not dep and not codes["region"]:
        methodes.append("aucun département ni région lisible")
    region = codes["region"]
    return {"organisme": base, "organisme_type": typ, "niveau": niveau if (dep or region) else "autre_organisme",
            "codes": codes, "rattachement": methodes, "chambre": ch, "siren": siren, "siren_methode": siren_methode}


def _requete_siren(a: dict) -> dict | None:
    """Paramètres de recherche SIREN d'un organisme sans SIREN tiré du COG ; None si rien à chercher."""
    if a["siren"] or a["niveau"] in ("commune", "epci") and a["codes"]["commune" if a["niveau"] == "commune" else
                                                                         "epci"]:
        return None
    nom = re.sub(r"\s*\([^()]*\)", "", a["organisme"]).strip()
    if len(mots_cle(nom)) < 2:
        return None
    dep = a["codes"]["departement"]
    if a["organisme_type"] == "département" and dep:
        return {"cle": f"departement|{dep}", "q": "departement", "departement": dep, "nature_juridique": "7220"}
    if a["organisme_type"] == "région" and a["codes"]["region"]:
        return {"cle": f"region|{a['codes']['region']}", "q": nom, "nature_juridique": "7230"}
    if not dep:
        return None
    return {"cle": f"{jeton(nom)}|{dep}", "q": nom, "departement": dep}


def _choisir_siren(req: dict, resultats: list[dict]) -> dict:
    """Un seul résultat personne morale au nom identique (normalisé, sigle retiré), au siège dans le département ;
    départements et régions : un seul résultat de la catégorie juridique demandée."""
    def nom_r(x):
        return jeton(re.sub(r"\s*\([^()]*\)", "", x.get("nom_raison_sociale") or x.get("nom_complet") or ""))
    pm = [x for x in resultats if sirene.personne_morale(x.get("nature_juridique"))]
    if "nature_juridique" in req:
        ok = [x for x in pm if x.get("nature_juridique") == req["nature_juridique"]
              and (req.get("departement") is None or (x.get("siege") or {}).get("departement") == req["departement"])]
        if req["nature_juridique"] == "7230":
            ok = [x for x in ok if jeton(req["q"]).replace("region ", "") in nom_r(x)]
    else:
        ok = [x for x in pm if nom_r(x) == jeton(req["q"])
              and (x.get("siege") or {}).get("departement") == req["departement"]]
    if len(ok) > 1:
        actifs = [x for x in ok if x.get("etat_administratif") == "A"]
        ok = actifs if len(actifs) == 1 else ok
    if len(ok) != 1:
        return {"siren": None, "candidats": len(ok)}
    return {"siren": ok[0]["siren"], "cj": ok[0].get("nature_juridique"), "candidats": 1}


def charger_cache_siren_rod() -> dict:
    if CACHE_ROD_SIREN.exists():
        try:
            return json.loads(CACHE_ROD_SIREN.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    return {}


def resoudre_siren_rod(budget_s: float, pause_s: float = PAUSE_S) -> dict:
    """SIREN des organismes contrôlés hors communes et EPCI (API Recherche d'entreprises), au plus une requête par
    `pause_s` secondes, cache reprenable data/lake/_cache/controle_rod_siren.json ; arrêt sur 403 ou 429."""
    import requests
    geo = referentiel_geo()
    cache = charger_cache_siren_rod()
    reqs = {}
    for x in rapports_lus().values():
        if not ROD_DEBUT <= (x.get("date") or "") <= ROD_FIN or nom_de_personne_possible(x["titre"]):
            continue
        r = _requete_siren(analyser_rod(geo, x))
        if r and r["cle"] not in cache:
            reqs.setdefault(r["cle"], r)
    print(f"  SIREN des organismes contrôlés : {len(reqs)} recherches à faire, {len(cache)} en cache", file=sys.stderr)
    debut, cadence, arret, faites = time.monotonic(), Cadence(pause_s), None, 0
    for cle, r in sorted(reqs.items()):
        if time.monotonic() - debut > budget_s:
            break
        params = {k: v for k, v in r.items() if k in ("q", "departement", "nature_juridique")}
        params.update(per_page=10, page=1)
        res = None
        for essai in range(3):
            cadence.attendre()
            try:
                rep = requests.get(API_ENTREPRISES, params=params, headers=UA, timeout=30)
            except requests.RequestException:
                cadence.suspendre(5 * (essai + 1))
                continue
            if rep.status_code in (403, 429):
                arret = f"HTTP {rep.status_code} sur l'API Recherche d'entreprises : arrêt, non contourné"
                break
            if rep.status_code >= 500:
                cadence.suspendre(5 * (essai + 1))
                continue
            try:
                res = rep.json().get("results", []) if rep.status_code == 200 else []
            except ValueError:  # réponse illisible : recherche reprise au passage suivant
                res = None
            break
        if arret:
            break
        if res is None:
            continue
        cache[cle] = {**_choisir_siren(r, res), "le": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        faites += 1
        if faites % 50 == 0:
            _ecrire_atomique(CACHE_ROD_SIREN, json.dumps(cache, ensure_ascii=False, sort_keys=True))
    _ecrire_atomique(CACHE_ROD_SIREN, json.dumps(cache, ensure_ascii=False, sort_keys=True))
    bilan = {"le": datetime.now(timezone.utc).isoformat(timespec="seconds"), "faites": faites,
             "en_cache": len(cache), "restantes": len([c for c in reqs if c not in cache]), "arret": arret}
    _ecrire_atomique(CACHE_ROD_SIREN.with_suffix(".etat.json"), json.dumps(bilan, ensure_ascii=False))
    if arret:
        print(f"  {arret}", file=sys.stderr)
    print(f"  SIREN des organismes contrôlés : {faites} recherches faites, {len(cache)} en cache", file=sys.stderr)
    return bilan


def memoire_rod() -> tuple[dict, dict]:
    """Rapports déjà publiés (site/data/controle/rod_crtc/<année>.json), remis sous la forme d'une page lue : un passage
    dont le cache data/lake est en retard (runner à froid, cache purgé) les garde tels quels. Une page relue (cache) les
    remplace ; une page disparue (404) les retire. Renvoie (pages, SIREN publiés par clé de recherche)."""
    pages, sirens = {}, {}
    for f in sorted(SORTIE_ROD.glob("[0-9][0-9][0-9][0-9].json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for r in d.get("rapports", []):
            infos = [f"Date de communicabilité : {r['date_communicabilite'][8:10]}.{r['date_communicabilite'][5:7]}."
                     f"{r['date_communicabilite'][:4]}"] if r.get("date_communicabilite") else []
            if r.get("date_envoi"):
                infos.append(f"Date d'envoi : {r['date_envoi'][8:10]}.{r['date_envoi'][5:7]}.{r['date_envoi'][:4]}")
            docs = [{"type": r.get("type_document") or "Rapport d'observations définitives", "url": r["url_document"],
                     "infos": infos}] if r.get("url_document") else []
            if r.get("url_synthese"):
                docs.append({"type": "Synthèse", "url": r["url_synthese"], "infos": []})
            pages[r["url"]] = {"url": r["url"], "statut": 200, "titre": r["titre"], "juridiction": r["juridiction"],
                               "institution": r["juridiction"].split(" ")[0], "document_publication": "Rapport",
                               "themes": r.get("themes") or [], "date": r["date"], "node": r.get("node"),
                               "documents": docs, "memoire": True}
            if r.get("organisme") is None:  # intitulé non publié : la fiche publiée est reprise telle quelle
                pages[r["url"]]["fiche_publiee"] = r
            if r.get("siren") and (r.get("siren_methode") or "").startswith("API"):
                sirens[r["url"]] = {"siren": r["siren"], "cj": r.get("categorie_juridique"), "candidats": 1}
    return pages, sirens


def rapports_lus() -> dict:
    """Pages de rapports d'observations définitives des chambres régionales et territoriales : mémoire publiée, puis
    cache de collecte (le cache l'emporte ; une page en 404 dans le cache retire le rapport)."""
    pages = dict(memoire_rod()[0])
    for u, x in charger_pubs().items():
        if x.get("statut") in (404, 410):
            pages.pop(u, None)
        elif x.get("statut") == 200:
            if est_rod(x):
                pages[u] = x
            else:
                pages.pop(u, None)
    return {u: x for u, x in pages.items() if est_rod(x)}


def _iso(s: str | None) -> str | None:
    return _date_point(s) if s else None


def fiche_rod(geo: dict, x: dict, cache_siren: dict, sirens_publies: dict) -> dict:
    """Rapport publié : métadonnées seulement (aucun résumé, aucune réponse, aucune personne)."""
    if x.get("fiche_publiee"):
        return x["fiche_publiee"]
    a = analyser_rod(geo, x)
    docs = x.get("documents") or []
    principal = next((d for d in docs if TYPE_ROD.search(d.get("type") or "")), None) or \
        next((d for d in docs if not DOC_ANNEXE.match(d.get("type") or "")), None)
    synthese = next((d for d in docs if re.match(r"(?i)^(synth[eè]se|les [ée]l[ée]ments cl[ée]s)", d.get("type") or "")),
                    None)
    infos = " ; ".join((principal or {}).get("infos") or [])
    communic = re.search(r"(?i)communicabilit[ée]\s*:\s*(\d{2}\.\d{2}\.\d{4})", infos)
    envoi = re.search(r"(?i)date d.envoi\s*:\s*(\d{2}\.\d{2}\.\d{4})", infos)
    siren, cj, methode = a["siren"], None, a["siren_methode"]
    req = _requete_siren(a)
    if req:
        c = cache_siren.get(req["cle"]) or sirens_publies.get(x["url"])
        if c and c.get("siren"):
            siren, cj, methode = c["siren"], c.get("cj"), "API Recherche d'entreprises : nom identique, siège dans le " \
                                                         "département, personne morale"
    titre = propre(x["titre"])
    nomme = not nom_de_personne_possible(titre)
    if siren and cj and not sirene.personne_morale(cj):
        nomme = False
    if siren and cj:
        pm, preuve = True, f"catégorie juridique {cj} (répertoire SIRENE)"
    elif a["niveau"] in ("commune", "epci") and (a["codes"]["commune"] or a["codes"]["epci"]):
        pm, preuve = True, f"{a['organisme_type']} (code officiel géographique)"
    elif a["organisme_type"]:
        pm, preuve = True, f"type d'organisme lu dans le titre : {a['organisme_type']}"
    else:
        pm, preuve = None, None
    date = x.get("date")
    fiche = {"id": f"cc-{x.get('node') or id_stable(x['url'])}", "node": x.get("node"),
             "titre": titre if nomme else "intitulé non publié (nom de personne possible)",
             "organisme": a["organisme"] if nomme else None, "organisme_type": a["organisme_type"],
             "personne_morale": pm, "personne_morale_preuve": preuve,
             "siren": siren if nomme else None, "siren_methode": methode if (siren and nomme) else None,
             "categorie_juridique": cj if nomme else None,
             "niveau": a["niveau"], "codes": a["codes"], "rattachement": a["rattachement"],
             "date": date, "annee": int(date[:4]), "date_communicabilite": _iso(communic.group(1)) if communic else None,
             "date_envoi": _iso(envoi.group(1)) if envoi else None,
             "juridiction": a["chambre"]["juridiction"], "chambre": a["chambre"]["nom"],
             "themes": [t for t in x.get("themes") or [] if not nom_de_personne_possible(t)],
             "type": "Rapport d'observations définitives",
             "type_document": (principal or {}).get("type") if principal and not TYPE_ROD.search(principal["type"])
             else None,
             "url": x["url"], "url_document": (principal or {}).get("url"), "url_synthese": (synthese or {}).get("url"),
             "source": SRC_ROD}
    return fiche


def construire_rod(geo: dict) -> tuple[list[dict], dict]:
    """Fiches des rapports publiés du 1er janvier 2020 au 31 décembre 2026, triées (date décroissante, identifiant)."""
    lus = rapports_lus()
    _, sirens_publies = memoire_rod()
    cache_siren = charger_cache_siren_rod()
    fiches, hors = [], Counter()
    for u in sorted(lus):
        x = lus[u]
        if not x.get("date"):
            hors["date de publication absente"] += 1
            continue
        if not ROD_DEBUT <= x["date"] <= ROD_FIN:
            hors[f"publié avant {ROD_DEBUT[:4]}" if x["date"] < ROD_DEBUT else f"publié après {ROD_FIN[:4]}"] += 1
            continue
        fiches.append(fiche_rod(geo, x, cache_siren, sirens_publies))
    fiches.sort(key=lambda f: (f["date"], f["id"]), reverse=True)
    return fiches, {"hors_periode": dict(hors), "depuis_memoire": sum(1 for x in lus.values() if x.get("memoire"))}


def produire_rod(geo: dict, fiches: list[dict], hors: dict) -> dict:
    """site/data/controle/rod_crtc/index.json et <année>.json (un fichier par année de publication)."""
    plan = urls_sitemap() if SITEMAP.exists() else []
    lues = pages_connues()
    etat = json.loads(ETAT_COLLECTE.read_text(encoding="utf-8")) if ETAT_COLLECTE.exists() else None
    if etat and "reponses" in etat:  # ancien nom (codes HTTP du passage)
        etat["codes_http"] = etat.pop("reponses")
    candidats = [u for u, lm in plan if _quand(lm) >= _quand(ROD_DEBUT + "T00:00:00+00:00")]
    lues_candidats = sum(1 for u in candidats if (lues.get(u) or {}).get("statut") in STATUTS_DEFINITIFS)
    crtc_hors_rod = Counter((x.get("document_publication") or "non précisée") for x in lues.values()
                            if x.get("statut") == 200 and est_page_crtc(x) and not est_rod(x))
    fichiers = {}
    annees = sorted({f["annee"] for f in fiches})
    for f in sorted(SORTIE_ROD.glob("[0-9][0-9][0-9][0-9].json")):
        if int(f.stem) not in annees:
            f.unlink()  # année sans rapport : fichier retiré (aucun fichier vide publié)
    for an in annees:
        lst = [f for f in fiches if f["annee"] == an]
        chemin = f"rod_crtc/{an}.json"
        fichiers[chemin] = dump(SORTIE / chemin, {
            "millesime": f"Rapports d'observations définitives publiés en {an}",
            "source": f"{SRC_ROD} ; {SRC_GEO} ; {SRC_SIREN_ROD}", "annee": an,
            "comptes": {"rapports": len(lst), "par_chambre": dict(sorted(Counter(x["chambre"] for x in lst).items())),
                        "par_niveau": dict(sorted(Counter(x["niveau"] for x in lst).items()))},
            "rapports": lst})
    par_annee = Counter(f["annee"] for f in fiches)
    themes = Counter(t for f in fiches for t in f["themes"])
    comptes = {
        "rapports": len(fiches),
        "par_annee": {str(a): par_annee[a] for a in sorted(par_annee)},
        "par_chambre": dict(sorted(Counter(f["chambre"] for f in fiches).items())),
        "par_niveau": dict(sorted(Counter(f["niveau"] for f in fiches).items())),
        "par_type_organisme": dict(sorted(Counter(f["organisme_type"] or "non reconnu" for f in fiches).items())),
        "avec_code_commune": sum(1 for f in fiches if f["codes"]["commune"]),
        "avec_code_epci": sum(1 for f in fiches if f["codes"]["epci"]),
        "avec_departement": sum(1 for f in fiches if f["codes"]["departement"]),
        "avec_siren": sum(1 for f in fiches if f["siren"]),
        "siren_par_methode": dict(sorted(Counter(f["siren_methode"] for f in fiches if f["siren"]).items())),
        "personne_morale": {"etablie": sum(1 for f in fiches if f["personne_morale"]),
                            "par_preuve": dict(sorted(Counter(
                                "catégorie juridique (répertoire SIRENE)" if (f["personne_morale_preuve"] or "")
                                .startswith("catégorie") else "code officiel géographique" if "(code officiel" in
                                (f["personne_morale_preuve"] or "") else "type d'organisme lu dans le titre" if
                                f["personne_morale_preuve"] else "non établie" for f in fiches).items()))},
        "intitules_non_publies": sum(1 for f in fiches if f["organisme"] is None),
        "avec_document": sum(1 for f in fiches if f["url_document"]),
        "hors_periode": hors["hors_periode"], "repris_de_la_memoire_publiee": hors["depuis_memoire"]}
    index = {
        "millesime": f"Rapports d'observations définitives publiés du {ROD_DEBUT} au "
                     f"{max((f['date'] for f in fiches), default=ROD_DEBUT)} (pages ccomptes.fr)",
        "source": f"{SRC_ROD} ; {SRC_GEO} ; {SRC_SIREN_ROD}",
        "perimetre": "Rapports d'observations définitives des chambres régionales et territoriales des comptes, "
                     "publiés en ligne du 1er janvier 2020 au 31 décembre 2026 : métadonnées seulement (organisme "
                     "contrôlé, codes géographiques, SIREN, date, chambre, thèmes, liens vers ccomptes.fr), ni texte "
                     "du rapport, ni réponses des organismes.",
        "regle_personnes": "Aucune personne physique : ni ordonnateurs, ni comptables, ni responsables, ni auteurs des "
                           "réponses ; ni résumé ni texte des rapports. Un intitulé où un nom de personne est possible "
                           "(civilité, prénom suivi d'un nom en capitales) n'est pas publié et compté dans "
                           "`intitules_non_publies`. Organismes : personnes morales (catégorie juridique SIRENE 2xxx "
                           "à 9xxx, collectivité du code officiel géographique ou type d'organisme lu dans le titre).",
        "regles_rattachement": [
            "département : parenthèse du titre (nom ou numéro), sinon commune unique de ce nom dans le ressort de la "
            "chambre (organisme « commune »), sinon nom d'un département du ressort cité dans le titre, sinon ressort "
            "de la chambre s'il ne compte qu'un département",
            "commune : nom de la commune dans le département (code officiel géographique en vigueur) ; pour un autre "
            "organisme, commune citée à la fin de son nom si elle est la seule de ce nom dans le département",
            "EPCI : nom de l'EPCI (code officiel géographique en vigueur), abréviations CC, CA, CU développées",
            "SIREN : commune et EPCI par le code officiel géographique ; autres organismes par l'API Recherche "
            "d'entreprises, retenu seulement si un seul résultat personne morale porte le même nom (normalisé, sigle "
            "entre parenthèses retiré) avec son siège dans le département",
            "date : date de mise en ligne sur ccomptes.fr ; année du fichier = année de cette date"],
        "fichiers": [f"controle/{c}" for c in sorted(fichiers)],
        "comptes": comptes,
        "themes": [{"theme": t, "rapports": n} for t, n in sorted(themes.items(), key=lambda kv: (-kv[1], kv[0]))],
        "pages_crtc_hors_rapports": {"par_categorie": dict(sorted(crtc_hors_rod.items())),
                                     "note": "Pages des chambres lues mais hors rapports d'observations définitives "
                                             "(avis budgétaires, jugements...) : comptées, non listées."},
        "couverture": {
            "pages_au_plan_du_site": len(plan), "pages_modifiees_depuis_2020": len(candidats),
            "pages_modifiees_depuis_2020_lues": lues_candidats,
            "pages_modifiees_depuis_2020_restantes": len(candidats) - lues_candidats,
            "derniere_collecte": etat,
            "lecture": "Une page publiée en 2020 ou après a été modifiée au plus tôt le jour de sa publication : les "
                       "pages du plan du site modifiées depuis le 1er janvier 2020 contiennent tous les rapports de la "
                       "période. Les pages non lues ne sont pas publiées (aucune métadonnée devinée) ; la collecte "
                       "hebdomadaire reprend où la précédente s'est arrêtée."}}
    fichiers["rod_crtc/index.json"] = dump(SORTIE_ROD / "index.json", index)
    return {"fichiers": fichiers, "comptes": comptes, "couverture": {k: v for k, v in index["couverture"].items()
                                                                     if k not in ("lecture", "derniere_collecte")}}


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
# Titres réels des publications (`publication`) ; la variante de périmètre retenue est dans `variante`.
T_SENAT = ("Rapport sur l'utilisation des aides publiques aux grandes entreprises et à leurs sous-traitants "
           "(n° 808, 2024-2025)")
T_HCSP_2026 = "Les aides aux entreprises : définition, périmètres, cadre de suivi et d'évaluation"
T_HCSP_2025 = "Les aides aux entreprises en France : de quoi parle-t-on ?"
T_IGF = "Revue de dépenses : les aides aux entreprises (n° 2023-M-105-03)"
T_IRES = "Un capitalisme sous perfusion"
T_FS = "Les politiques industrielles en France : évolutions et comparaisons internationales"
# Chaque estimation : `preuve` = passages qui doivent figurer dans le rapport du HCSP (vérifié à chaque production).
ESTIMATIONS = [
    {"id": "senat_2025_large", "auteur": "Sénat, commission d'enquête", "annee_publication": 2025, "annee_donnees": 2023,
     "publication": T_SENAT, "variante": "estimation large", "md": 211,
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
     "annee_donnees": 2023, "publication": T_SENAT, "variante": "estimation restreinte", "md": 108,
     "perimetre": "estimation large moins les interventions de Bpifrance et 62 Md€ de dépenses fiscales déclassées "
                  "et liées à la TVA", "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations"],
     "exclut": ["prets_garanties", "depenses_fiscales_declassees", "collectivites", "europe"],
     "preuve": ["La seconde estimation, à 108 milliards"]},
    {"id": "hcsp_2026_p1", "auteur": "HCSP", "annee_publication": 2026, "annee_donnees": 2023,
     "publication": T_HCSP_2026, "variante": "périmètre 1",
     "md": 82, "perimetre": "aides directes et ciblées : dépenses budgétaires ciblées, dépenses fiscales classées, "
                            "exonérations ciblées de cotisations, prêts, garanties et participations en "
                            "équivalent-subvention, aides directes des collectivités",
     "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations", "prets_garanties", "collectivites"],
     "exclut": ["depenses_fiscales_declassees", "europe"], "preuve": ["estimé à 82 milliards"]},
    {"id": "hcsp_2026_p2", "auteur": "HCSP", "annee_publication": 2026, "annee_donnees": 2023,
     "publication": T_HCSP_2026, "variante": "périmètre 2", "md": 187,
     "perimetre": "périmètre 1 + exonérations générales de cotisations, taux réduits de TVA à finalité sectorielle, "
                  "interventions indirectes des collectivités",
     "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations", "prets_garanties", "collectivites"],
     "exclut": ["depenses_fiscales_declassees", "europe"], "preuve": ["Chiffré à 187 milliards"]},
    {"id": "hcsp_2026_agregat_large", "auteur": "HCSP", "annee_publication": 2026, "annee_donnees": 2023,
     "publication": T_HCSP_2026, "variante": "agrégat macroéconomique complémentaire", "md": 259,
     "perimetre": "mesure globale des soutiens publics en faveur des activités économiques",
     "inclut": None, "exclut": None, "preuve": ["est évalué à 259 milliards"]},
    {"id": "hcsp_2025_aides_etat", "auteur": "HCSP (note d'analyse n° 157)", "annee_publication": 2025,
     "annee_donnees": 2023, "publication": T_HCSP_2025, "variante": "aides d'État au sens européen", "md": 45,
     "perimetre": "aides d'État au sens du droit européen", "inclut": None, "exclut": None,
     "preuve": ["soit environ 45 milliards d’euros en France en 2023"]},
    {"id": "hcsp_2025", "auteur": "HCSP (note d'analyse n° 157)", "annee_publication": 2025, "annee_donnees": 2023,
     "publication": T_HCSP_2025, "variante": "second périmètre", "md": 112,
     "perimetre": "aides budgétaires, fiscales classées, financières en équivalent-subvention, exonérations ciblées ; "
                  "hors exonérations générales, dépenses fiscales déclassées, collectivités et Europe",
     "inclut": ["subventions", "depenses_fiscales", "prets_garanties", "exonerations_cotisations"],
     "exclut": ["depenses_fiscales_declassees", "collectivites", "europe"],
     "preuve": ["exonérations de cotisations ciblées (112 milliards)"]},
    {"id": "igf_2024", "auteur": "Inspection générale des finances", "annee_publication": 2024, "annee_donnees": 2022,
     "publication": T_IGF, "variante": "périmètre de la revue", "md": 88,
     "perimetre": "aides budgétaires et fiscales ciblées de l'État et de la sécurité sociale, hors allègements "
                  "généraux de cotisations et dépenses fiscales déclassées",
     "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations"],
     "exclut": ["depenses_fiscales_declassees", "collectivites", "europe"],
     "preuve": ["s’élèvent à 88 milliards d’euros"]},
    {"id": "igf_2024_elargi", "auteur": "Inspection générale des finances", "annee_publication": 2024,
     "annee_donnees": 2022, "publication": T_IGF, "variante": "périmètre élargi", "md": 105,
     "perimetre": "88 Md€ + aides budgétaires des collectivités (7 Md€, 2021) + une partie des aides européennes "
                  "(10 Md€)", "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations",
                                         "collectivites", "europe"], "exclut": ["depenses_fiscales_declassees"],
     "preuve": ["le total des aides aux entreprises estimé passe à 105 milliards d’euros"]},
    {"id": "ce_2024", "auteur": "Commission européenne (State Aid Scoreboard)", "annee_publication": 2024,
     "annee_donnees": 2022, "publication": "Données annuelles des aides d'État", "md": 45,
     "perimetre": "aides d'État au sens du droit européen (25 Md€ hors mesures Covid et Ukraine)", "inclut": None,
     "exclut": ["exonerations_cotisations"], "preuve": ["(45 milliards d’euros en 2022, 25 milliards"]},
    {"id": "ires_clerse_2022", "auteur": "Ires, équipe du Clersé (université de Lille)", "annee_publication": 2022,
     "annee_donnees": 2019, "publication": T_IRES, "variante": "périmètre principal", "md": 157,
     "perimetre": "aides budgétaires (comptabilité nationale), dépenses fiscales, exonérations de cotisations ; hors "
                  "prêts, garanties, participations et dépenses fiscales déclassées",
     "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations"],
     "exclut": ["prets_garanties", "depenses_fiscales_declassees"],
     "preuve": ["estime à 157 milliards d’euros le montant global des aides\npubliques aux entreprises en 2019"]},
    {"id": "ires_clerse_2022_large", "auteur": "Ires, équipe du Clersé (université de Lille)",
     "annee_publication": 2022, "annee_donnees": 2019, "publication": T_IRES, "variante": "périmètre large", "md": 205,
     "perimetre": "157 Md€ + dépenses fiscales déclassées",
     "inclut": ["subventions", "depenses_fiscales", "depenses_fiscales_declassees", "exonerations_cotisations"],
     "exclut": ["prets_garanties"], "preuve": ["le plus large, soit 205 milliards d’euros d’aides aux entreprises"]},
    {"id": "france_strategie_2020_restreint", "auteur": "France Stratégie", "annee_publication": 2020,
     "annee_donnees": 2019, "publication": T_FS, "variante": "périmètre le plus restreint", "md": 139,
     "perimetre": "hors dépenses fiscales déclassées, interventions financières, infrastructures de transport, aides "
                  "directes à certaines entreprises ou services publics",
     "inclut": ["subventions", "depenses_fiscales", "exonerations_cotisations", "collectivites", "europe"],
     "exclut": ["depenses_fiscales_declassees", "prets_garanties"],
     "preuve": ["139 milliards d’euros selon le périmètre le plus restreint"]},
    {"id": "france_strategie_2020_large", "auteur": "France Stratégie", "annee_publication": 2020,
     "annee_donnees": 2019, "publication": T_FS, "variante": "périmètre le plus large", "md": 223,
     "perimetre": "dépenses budgétaires, fiscales y compris déclassées et taxes affectées, exonérations de "
                  "cotisations, aides financières, aides régionales, aides européennes à la R & D",
     "inclut": ["subventions", "depenses_fiscales", "depenses_fiscales_declassees", "exonerations_cotisations",
                "prets_garanties", "collectivites", "europe"], "exclut": [],
     "preuve": ["s’élève à 223 milliards selon le périmètre le plus large"]},
    {"id": "cpo_2010", "auteur": "Conseil des prélèvements obligatoires (rattaché à la Cour des comptes)",
     "annee_publication": 2010, "annee_donnees": None,
     "annee_donnees_note": "année des données non précisée dans la synthèse du rapport (publié en 2010)",
     "publication": "Entreprises et « niches » fiscales et sociales", "md": 170, "md_haut": 200,
     "perimetre": "dépenses fiscales y compris TVA, TIPP et déclassées, exonérations de cotisations (souvent appelées "
                  "niches sociales) ; "
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
                                                     "exclu", "source": SRC_URSSAF,
                                            "renvoi": "niches/sociales.json (`urssaf`) publie l'autre jeu Urssaf, "
                                                      "par mesure, sur le champ des cotisations recouvrées par les "
                                                      "Urssaf : champ différent, totaux annuels voisins sans être "
                                                      "égaux (moins de 0,5 % d'écart) ; les deux séries ne "
                                                      "s'additionnent pas.",
                                            "annees": serie},
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
     "mise_a_jour": "2020-01-22", "usage": "rapports des CRC 2015 à 2019 reliés aux collectivités ; aucun jeu plus "
                                          "récent chez la Cour des comptes sur data.gouv.fr (237 jeux vérifiés le "
                                          "18/11/2026)"},
    {"nom": "data.ccomptes.fr (portail de données cité par api-ccomptes)", "url": "https://data.ccomptes.fr",
     "verdict": "inspiration seulement", "licence": "inconnue (hôte injoignable)", "mise_a_jour": "injoignable le "
     "2026-11-18", "usage": "aucun jeu lisible ; rapports 2020 à 2026 lus page par page sur ccomptes.fr"},
    {"nom": "a455bcd9/DataSessionCComptes (GitHub)", "url": "https://github.com/a455bcd9/DataSessionCComptes",
     "verdict": "inspiration seulement", "licence": "aucune déclarée", "mise_a_jour": "2016-05-28",
     "usage": "métadonnées XML et texte des ROD 2013 à 2015 (data session Etalab de 2016), hors période"},
    {"nom": "API Recherche d'entreprises (recherche-entreprises.api.gouv.fr)", "url": API_ENTREPRISES,
     "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "quotidienne",
     "usage": "SIREN et catégorie juridique des organismes contrôlés (nom identique, siège dans le département)"},
    {"nom": "data.gouv.fr, Publications de la Cour des comptes par type et date (2011-2016)", "url": URL_PUBS_2011_2016,
     "verdict": "réutilisable tel quel", "licence": "ODbL", "mise_a_jour": "2018-05-07",
     "usage": "publications de la Cour reliées aux programmes"},
    {"nom": "data.gouv.fr, Rapports publiés par la Cour des comptes (texte intégral 2013-2018)",
     "url": "https://www.data.gouv.fr/fr/datasets/rapports-publies-par-la-cour-des-comptes/",
     "verdict": "inspiration seulement", "licence": "ODbL", "mise_a_jour": "2018-09-27",
     "usage": "texte intégral (centaines de Mo), métadonnées déjà couvertes par les deux jeux ci-dessus"},
    {"nom": "ccomptes.fr, plan du site des publications et métadonnées schema.org des pages",
     "url": f"{CC}/sitemap_publication/sitemap.xml", "verdict": "à adapter", "licence": "Licence Ouverte 2.0",
     "mise_a_jour": "quotidienne", "usage": "rapports d'observations définitives 2020 à 2026 et publications de la "
                                            "Cour : collecte reprenable, une requête par seconde ; robots.txt exclut "
                                            "les adresses à paramètres (recherche, listes filtrées), non utilisées"},
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
    """Sources refusées ou injoignables. ccomptes.fr n'y figure que si le dernier passage de collecte s'est arrêté
    (403, 429 ou serveur indisponible) : le refus est noté, jamais contourné, et le passage suivant reprend."""
    out = []
    if REFUS.exists():
        refus = json.loads(REFUS.read_text(encoding="utf-8"))
        out.append({"source": "ccomptes.fr, pages des publications", "url": f"{CC}/fr/publications/",
                    "constat": f"{refus['motif']} (le {refus['le'][:10]})",
                    "effet": "seules les pages déjà lues sont publiées ; la collecte hebdomadaire reprend où elle "
                             "s'est arrêtée"})
    etat_siren = CACHE_ROD_SIREN.with_suffix(".etat.json")
    if etat_siren.exists() and (json.loads(etat_siren.read_text(encoding="utf-8")) or {}).get("arret"):
        e = json.loads(etat_siren.read_text(encoding="utf-8"))
        out.append({"source": "API Recherche d'entreprises (SIREN des organismes contrôlés)", "url": API_ENTREPRISES,
                    "constat": f"{e['arret']} (le {e['le'][:10]})",
                    "effet": "SIREN non recherchés publiés à null ; le passage suivant reprend"})
    out += [{"source": "data.ccomptes.fr", "url": "https://data.ccomptes.fr",
             "constat": "hôte injoignable le 18/11/2026 ; data.gouv.fr ne publie les métadonnées des rapports "
                        "d'observations définitives des chambres que jusqu'aux rapports de 2019",
             "effet": "rapports 2020 à 2026 lus page par page sur ccomptes.fr (plan du site)"},
            {"source": "Légifrance", "url": "https://www.legifrance.gouv.fr", "constat": "non utilisé",
             "effet": "aucun"},
            {"source": "HATVP, déclarations de patrimoine et d'intérêts", "url": "https://www.hatvp.fr",
             "constat": "exclues volontairement (données personnelles)", "effet": "hors périmètre"}]
    return out


def produire() -> dict:
    geo = referentiel_geo()
    fiches, hors = construire_rod(geo)
    c = produire_controle(geo, fiches)
    r = produire_rod(geo, fiches, hors)
    i = produire_influence()
    a = produire_aides()
    index = {
        "millesime": f"Sources collectées au {date_sources()}",
        "source": "pipeline/controle.py (voir chaque fichier)",
        "fichiers": {"controle": sorted(c["fichiers"]), "rod_crtc": sorted(r["fichiers"]),
                     "influence": sorted(i["fichiers"]), "aides": ["aides_entreprises.json"]},
        "controle": {**c["comptes"], "couverture_ccomptes": c["couverture_ccomptes"],
                     "departements": c["departements"]},
        "rod_crtc": {"fichier": "controle/rod_crtc/index.json",
                     **{k: r["comptes"][k] for k in ("rapports", "par_annee", "avec_code_commune", "avec_code_epci",
                                                     "avec_siren", "intitules_non_publies")},
                     "couverture": r["couverture"]},
        "influence": i["comptes"],
        "aides_entreprises": {"estimations": a["estimations"], "fourchette_md": a["fourchette_md"],
                              "verification": dict(a["verification"])},
        "regle_personnes": "Aucune personne physique nommée : ni dirigeants, ni collaborateurs, ni responsables "
                           "publics (fonction et ministère seulement), ni auteurs des réponses aux rapports, ni "
                           "ordonnateurs ou comptables des organismes contrôlés.",
        "sources_inaccessibles": sources_inaccessibles(),
        "recherche_publique": RECHERCHE_PUBLIQUE}
    dump(SORTIE / "index.json", index)
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collecter")
    c.add_argument("--budget", type=float, default=1800)
    c.add_argument("--volets", default="ccomptes,hatvp,siren_rod",
                   help="ccomptes (pages ccomptes.fr), hatvp (catégorie juridique des SIREN du répertoire), siren_rod "
                        "(SIREN des organismes contrôlés par les chambres régionales et territoriales)")
    c.add_argument("--depuis", default=PLAN_DEPUIS, help="pages modifiées depuis cette date lues en premier")
    c.add_argument("--sans-anciennes", action="store_true", help="ne pas lire les pages modifiées avant --depuis")
    c.add_argument("--paralleles", type=int, default=2)
    c.add_argument("--pause", type=float, default=None,
                   help="secondes entre deux requêtes (défaut : 1 pour ccomptes.fr et siren_rod, celui de sirene.py "
                        "pour hatvp)")
    sub.add_parser("produire")
    a = ap.parse_args()
    if a.cmd == "collecter":
        parts = {"ccomptes": 0.6, "hatvp": 0.2, "siren_rod": 0.2}
        volets = [v for v in parts if v in a.volets.split(",")]
        total = sum(parts[v] for v in volets) or 1
        if "ccomptes" in volets:
            collecter_ccomptes(a.budget * parts["ccomptes"] / total, paralleles=a.paralleles, depuis=a.depuis,
                               anciennes=not a.sans_anciennes, pause_s=max(a.pause or PAUSE_S, PAUSE_S))
        if "hatvp" in volets:
            resoudre_hatvp(a.budget * parts["hatvp"] / total, pause_s=a.pause)
        if "siren_rod" in volets:
            resoudre_siren_rod(a.budget * parts["siren_rod"] / total, pause_s=max(a.pause or PAUSE_S, PAUSE_S))
    else:
        idx = produire()
        print(json.dumps({k: idx[k] for k in ("controle", "influence", "aides_entreprises")}, ensure_ascii=False,
                         indent=1)[:3000])


if __name__ == "__main__":
    main()
