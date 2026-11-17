"""Collecteur generique : remplit l'entrepot brut data/lake/ a partir de collecte/catalogue.json
et, sur demande, de collecte/decouvertes.json (jeux trouves par decouverte.py).

Principe : tout prendre tel que publie, sans transformation, et tracer chaque fichier
(URL, date, empreinte sha256, taille, lignes, colonnes, licence, validateurs HTTP) dans
data/lake/manifest.json. Une source en erreur ou trop longue n'arrete pas les autres.

Reprise : une source deja collectee n'est pas retelechargee si sa signature amont n'a pas
change (date de modification ODS, date de ressource data.gouv.fr) ou si le serveur repond
304 a une requete conditionnelle (ETag / Last-Modified). Un telechargement coupe reprend
la ou il s'est arrete (en-tete Range + If-Range) quand le serveur le permet.

Usage :
  python collecte/collecte.py                       # toutes les sources non lourdes du catalogue
  python collecte/collecte.py --lourd               # y compris les sources lourdes (> 100 Mo)
  python collecte/collecte.py --domaine etat        # un domaine
  python collecte/collecte.py id1 id2               # des sources precises
  python collecte/collecte.py --liste               # affiche le catalogue
  python collecte/collecte.py --decouvertes --score-min 4 --limite 50
  python collecte/collecte.py --timeout 300 --force
"""
from __future__ import annotations

import argparse
import contextlib
try:
    import fcntl  # Linux, macOS
except ImportError:  # Windows
    fcntl = None
    import msvcrt
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

ICI = Path(__file__).resolve().parent
ROOT = ICI.parent
LAKE = ROOT / "data" / "lake"
MANIFEST = LAKE / "manifest.json"
CATALOGUE_PATH = ICI / "catalogue.json"
DECOUVERTES_PATH = ICI / "decouvertes.json"
PORTAILS_SUPP_PATH = ICI / "portails_ods.json"
TAILLE_MAX_DEPOT = 10 * 10**6  # au-dela, decouvertes.json est ecrit compresse (.json.gz)
USER_AGENT = "ou-vont-mes-impots-collecte/0.3 (projet citoyen open source, collecte de donnees ouvertes)"
DATAGOUV_API = "https://www.data.gouv.fr/api/1"
TIMEOUT_DEFAUT_S = 900          # budget par source (non lourde)
TIMEOUT_LOURD_S = 3600          # budget par source lourde
SEUIL_LOURD_OCTETS = 100 * 10**6
# Mode flux (collecte/stockage.py, option --flux) : les fichiers partent dans le stockage objet et
# sont effaces en local ; un fichier deja stocke compte alors comme present pour la reprise.
STOCKE_A_DISTANCE = False
FORMATS_IGNORES = {"html", "htm", "api", "url", "web page", "ogc:wms", "ogc:wfs", "esri rest", "php"}


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def charger_catalogue(chemin: Path = CATALOGUE_PATH) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))


def charger_portails(catalogue: dict | None = None) -> dict:
    """Portails du catalogue + portails Opendatasoft supplementaires (collectivites...) de portails_ods.json."""
    portails = dict((catalogue or charger_catalogue())["portails"])
    if PORTAILS_SUPP_PATH.exists():
        for cle, p in json.loads(PORTAILS_SUPP_PATH.read_text(encoding="utf-8"))["portails"].items():
            portails.setdefault(cle, p["base"])
    return portails


def lire_decouvertes(chemin: Path | None = None) -> dict | None:
    import gzip
    chemin = chemin or DECOUVERTES_PATH
    gz = chemin.with_name(chemin.name + ".gz")
    if gz.exists():
        return json.loads(gzip.decompress(gz.read_bytes()).decode("utf-8"))
    if chemin.exists():
        return json.loads(chemin.read_text(encoding="utf-8"))
    return None


def ecrire_decouvertes(res: dict, chemin: Path | None = None) -> Path:
    """Ecrit en clair si < 10 Mo, sinon en .json.gz (jamais de fichier > 10 Mo dans le depot)."""
    import gzip
    chemin = chemin or DECOUVERTES_PATH
    gz = chemin.with_name(chemin.name + ".gz")
    texte = json.dumps(res, ensure_ascii=False, indent=None, separators=(",", ":")) + "\n"
    if len(texte.encode("utf-8")) <= TAILLE_MAX_DEPOT:
        chemin.write_text(texte, encoding="utf-8")
        gz.unlink(missing_ok=True)
        return chemin
    gz.write_bytes(gzip.compress(texte.encode("utf-8"), 9, mtime=0))
    chemin.unlink(missing_ok=True)
    return gz


# ---------------------------------------------------------------- reseau

class DelaiDepasse(RuntimeError):
    """Le budget de temps de la source est epuise."""


class SansRessource(RuntimeError):
    """Le jeu ne publie aucun fichier telechargeable (jeu vide, page web, API) : pas une erreur de collecte."""


class TropLourd(RuntimeError):
    """Le fichier depasse la taille maximale autorisee pour une source non lourde."""


class Client:
    """Client HTTP poli : User-Agent explicite, pause entre appels, reprises avec attente
    exponentielle, respect de Retry-After, budget de temps (deadline) par appel."""

    def __init__(self, pause: float = 0.5, session: requests.Session | None = None,
                 connect_timeout: float = 20, read_timeout: float = 120, essais: int = 6):
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.pause = pause
        self.timeouts = (connect_timeout, read_timeout)
        self.essais = essais
        self._dernier = 0.0
        self.echecs_hote: dict[str, int] = {}  # hotes injoignables dans ce passage : on cesse d'insister

    SEUIL_HOTE_MORT = 3

    def _attendre_tour(self):
        reste = self.pause - (time.time() - self._dernier)
        if reste > 0:
            time.sleep(reste)
        self._dernier = time.time()

    def get(self, url: str, *, stream: bool = False, headers: dict | None = None,
            deadline: float | None = None, essais: int | None = None, params: dict | None = None) -> requests.Response:
        essais = essais or self.essais
        erreur = None
        hote = url.split("/")[2] if "//" in url else url
        if self.echecs_hote.get(hote, 0) >= self.SEUIL_HOTE_MORT:
            raise RuntimeError(f"hote {hote} injoignable a plusieurs reprises dans ce passage, source reportee")
        try:
            return self._get(url, stream, headers, deadline, essais, params)
        except DelaiDepasse as exc:
            if "Error" in str(exc) or "Timeout" in str(exc):
                self.echecs_hote[hote] = self.echecs_hote.get(hote, 0) + 1
            raise
        except RuntimeError as exc:
            if "injoignable" in str(exc):
                self.echecs_hote[hote] = self.echecs_hote.get(hote, 0) + 1
            raise

    def _get(self, url, stream, headers, deadline, essais, params) -> requests.Response:
        erreur = None
        for tentative in range(1, essais + 1):
            if deadline and time.time() > deadline:
                raise DelaiDepasse(f"budget de temps epuise avant {url}")
            self._attendre_tour()
            attente = min(2 ** tentative, 30)
            try:
                timeouts = self.timeouts
                if deadline:
                    reste = max(5.0, deadline - time.time())
                    timeouts = (min(self.timeouts[0], reste), min(self.timeouts[1], reste))
                r = self.s.get(url, headers=headers, stream=stream, timeout=timeouts, params=params)
            except (requests.ConnectionError, requests.Timeout) as exc:
                erreur = f"{type(exc).__name__}: {str(exc)[:150]}"
            else:
                if r.status_code < 400:
                    return r
                if r.status_code in (401, 403):
                    # refus d'acces : on ne contourne jamais
                    raise RuntimeError(f"acces refuse HTTP {r.status_code} sur {url}")
                if r.status_code != 429 and r.status_code < 500:
                    raise RuntimeError(f"HTTP {r.status_code} sur {url} : {r.text[:200]}")
                erreur = f"HTTP {r.status_code}"
                ra = r.headers.get("Retry-After", "")
                if ra.isdigit():
                    attente = min(int(ra), 120)
                r.close()
            if tentative < essais:
                if deadline and time.time() + attente > deadline:
                    raise DelaiDepasse(f"budget de temps epuise sur {url} ({erreur})")
                time.sleep(attente)
        raise RuntimeError(f"{url} injoignable apres {essais} tentatives : {erreur}")

    def json(self, url: str, **kw):
        return self.get(url, **kw).json()


def _hash_fichier(chemin: Path) -> tuple[hashlib._Hash, int]:
    h, n = hashlib.sha256(), 0
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
            n += len(bloc)
    return h, n


def telecharger(client: Client, url: str, cible: Path, *, deadline: float | None = None,
                ancien: dict | None = None, essais_flux: int = 6, max_octets: int | None = None) -> dict:
    """Telecharge url vers cible (fichier .part puis renommage atomique).

    - requete conditionnelle si `ancien` (entree de fichier du manifeste) porte etag/last_modified
      et que le fichier existe : un 304 renvoie {"inchange": True} sans rien ecrire ;
    - reprise d'un .part interrompu par Range + If-Range (validateur memorise a cote du .part) ;
    - le budget de temps est verifie a chaque bloc."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_name(cible.name + ".part")
    meta_tmp = cible.with_name(cible.name + ".part.json")
    for tentative in range(1, essais_flux + 1):
        headers = {}
        if ancien and (cible.exists() or STOCKE_A_DISTANCE) and not tmp.exists():
            if ancien.get("etag"):
                headers["If-None-Match"] = ancien["etag"]
            if ancien.get("last_modified"):
                headers["If-Modified-Since"] = ancien["last_modified"]
        reprise = 0
        if tmp.exists() and tmp.stat().st_size > 0 and meta_tmp.exists():
            validateur = json.loads(meta_tmp.read_text()).get("validateur")
            if validateur:
                reprise = tmp.stat().st_size
                headers = {"Range": f"bytes={reprise}-", "If-Range": validateur}
        try:
            with client.get(url, stream=True, headers=headers, deadline=deadline) as r:
                if r.status_code == 304:
                    return {"inchange": True}
                etag, lm = r.headers.get("ETag"), r.headers.get("Last-Modified")
                validateur = etag if etag and not etag.startswith("W/") else lm
                if r.status_code == 206 and reprise:
                    h, n = _hash_fichier(tmp)
                    mode = "ab"
                else:
                    h, n, mode = hashlib.sha256(), 0, "wb"
                meta_tmp.write_text(json.dumps({"url": url, "validateur": validateur}))
                with tmp.open(mode) as f:
                    for bloc in r.iter_content(1 << 20):
                        if deadline and time.time() > deadline:
                            raise DelaiDepasse(f"budget de temps epuise pendant le telechargement ({n / 1e6:.0f} Mo recus)")
                        f.write(bloc)
                        h.update(bloc)
                        n += len(bloc)
                        if max_octets and n > max_octets:
                            raise TropLourd(f"plus de {max_octets / 1e6:.0f} Mo")
                attendu = r.headers.get("Content-Length")
                if attendu and r.status_code == 200 and int(attendu) != n and "gzip" not in r.headers.get("Content-Encoding", ""):
                    raise requests.exceptions.ChunkedEncodingError(f"transfert tronque {n}/{attendu}")
            break
        except TropLourd:
            tmp.unlink(missing_ok=True)
            meta_tmp.unlink(missing_ok=True)
            raise
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as exc:
            if tentative == essais_flux:
                raise RuntimeError(f"transfert interrompu {essais_flux} fois : {exc}") from exc
            if deadline and time.time() + 5 * tentative > deadline:
                raise DelaiDepasse("budget de temps epuise apres coupure") from exc
            time.sleep(5 * tentative)
    if n == 0:
        tmp.unlink(missing_ok=True)
        meta_tmp.unlink(missing_ok=True)
        raise RuntimeError("fichier vide")
    tmp.replace(cible)
    meta_tmp.unlink(missing_ok=True)
    return {"octets": n, "sha256": h.hexdigest(), "etag": etag, "last_modified": lm}


def telecharger_ted(client: Client, src: dict, cible: Path, deadline=None, par_page: int = 250) -> dict:
    """Recherche TED (API v3, sans cle, POST, pagination par jeton d'iteration) ecrite en NDJSON."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_name(cible.name + ".part")
    h, n, lignes, jeton = hashlib.sha256(), 0, 0, None
    with tmp.open("wb") as f:
        while True:
            if deadline and time.time() > deadline:
                raise DelaiDepasse(f"budget de temps epuise ({lignes} avis recus)")
            corps = {"query": src["requete"], "fields": src["champs"], "limit": par_page, "paginationMode": "ITERATION"}
            if jeton:
                corps["iterationNextToken"] = jeton
            for essai in range(1, 7):
                client._attendre_tour()
                try:
                    r = client.s.post("https://api.ted.europa.eu/v3/notices/search", json=corps, timeout=client.timeouts)
                except (requests.ConnectionError, requests.Timeout):
                    time.sleep(min(2 ** essai, 30))
                    continue
                if r.status_code in (401, 403):
                    raise RuntimeError(f"acces refuse HTTP {r.status_code} (TED)")
                if r.status_code == 429 or r.status_code >= 500:
                    time.sleep(min(2 ** essai, 60))
                    continue
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code} TED : {r.text[:200]}")
                break
            else:
                raise RuntimeError("TED injoignable apres 6 tentatives")
            d = r.json()
            for avis in d.get("notices", []):
                avis.pop("links", None)
                b = (json.dumps(avis, ensure_ascii=False) + "\n").encode("utf-8")
                f.write(b)
                h.update(b)
                n += len(b)
                lignes += 1
            jeton = d.get("iterationNextToken")
            if not d.get("notices") or not jeton:
                break
    if n == 0:
        tmp.unlink(missing_ok=True)
        raise SansRessource("aucun avis TED pour cette requete")
    tmp.replace(cible)
    return {"octets": n, "sha256": h.hexdigest(), "lignes": lignes, "etag": None, "last_modified": None}


def decrire_parquet(chemin: Path) -> dict:
    try:
        import pyarrow.parquet as pq
        meta = pq.ParquetFile(chemin)
        return {"lignes": meta.metadata.num_rows, "colonnes": meta.schema_arrow.names}
    except Exception as exc:  # fichier non parquet ou illisible : on le garde quand meme
        return {"lecture": f"illisible en parquet : {exc}"[:200]}


def decrire_csv(chemin: Path) -> dict:
    """Compte les lignes (hors en-tete) et lit l'en-tete d'un CSV, sans interpretation."""
    try:
        with chemin.open("rb") as f:
            entete = f.readline().decode("utf-8-sig", errors="replace").strip()
            n = sum(1 for _ in f)
        sep = max([";", ",", "\t", "|"], key=entete.count)
        return {"lignes": n, "colonnes": [c.strip().strip('"') for c in entete.split(sep)][:500]}
    except Exception as exc:
        return {"lecture": f"illisible en csv : {exc}"[:200]}


def decrire(chemin: Path) -> dict:
    suf = chemin.suffix.lower()
    if suf == ".parquet":
        return decrire_parquet(chemin)
    if suf in (".csv", ".tsv", ".txt"):
        return decrire_csv(chemin)
    return {}


# ---------------------------------------------------------------- manifeste

@contextlib.contextmanager
def _verrou(chemin: Path):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin.with_name(chemin.name + ".lock"), "w") as v:
        if fcntl:
            fcntl.flock(v, fcntl.LOCK_EX)
        else:
            v.write("0"); v.flush(); v.seek(0)
            msvcrt.locking(v.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(v, fcntl.LOCK_UN)
            else:
                v.seek(0)
                msvcrt.locking(v.fileno(), msvcrt.LK_UNLCK, 1)


def lire_manifeste(chemin: Path | None = None) -> dict:
    chemin = chemin or MANIFEST
    if not chemin.exists():
        return {}
    return json.loads(chemin.read_text(encoding="utf-8"))


def maj_manifeste(sid: str, entree: dict, chemin: Path | None = None) -> dict:
    """Met a jour une entree sous verrou (plusieurs collectes peuvent tourner en parallele)
    et ecrit de facon atomique."""
    chemin = chemin or MANIFEST
    with _verrou(chemin):
        m = lire_manifeste(chemin)
        m[sid] = entree
        tmp = chemin.with_name(chemin.name + ".tmp")
        tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, chemin)
    return m


# ---------------------------------------------------------------- sources

def nom_sur(texte: str, longueur: int = 80) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", texte).strip("._")
    return (s or "fichier")[:longueur]


def _meta_ods(client: Client, base: str, dataset: str, deadline) -> dict:
    return client.json(f"{base}/api/explore/v2.1/catalog/datasets/{dataset}", deadline=deadline)


def _signature_ods(meta: dict) -> str:
    d = meta.get("metas", {}).get("default", {})
    return f"{d.get('modified')}|{d.get('data_processed')}|{d.get('metadata_processed')}"


def plan_source(client: Client, src: dict, portails: dict, deadline=None, max_octets: int | None = None) -> dict:
    """Renvoie {"fichiers": [{url, nom, signature, taille?}], "ignores": [...], "signature_source": ...}."""
    t = src["type"]
    if t in ("ods_export", "ods_pieces_jointes"):
        base = portails[src["portail"]]
        meta = _meta_ods(client, base, src["dataset"], deadline)
        sig = _signature_ods(meta)
        api = f"{base}/api/explore/v2.1/catalog/datasets/{src['dataset']}"
        if t == "ods_export":
            if meta.get("has_records") is False:
                raise RuntimeError("jeu sans enregistrements (pieces jointes seulement ?) : utiliser ods_pieces_jointes")
            params = {k: src[k] for k in ("where", "select") if src.get(k)}
            q = f"?{urlencode(params)}" if params else ""
            fmt = src.get("format_export", "parquet")  # csv en repli quand l'export parquet est coupe en route
            return {"signature_source": sig,
                    "fichiers": [{"url": f"{api}/exports/{fmt}{q}", "nom": f"{src['id']}.{fmt}", "signature": sig + q}]}
        # Forme reelle ODS v2.1 : {"links": [...], "attachments": [{"href": URL, "metas": {"id", "title", "mimetype", "url"}}]}
        liste = client.json(f"{api}/attachments", deadline=deadline)
        fichiers = []
        for a in liste.get("attachments", []):
            m = a.get("metas", {})
            aid = m.get("id") or a.get("id")
            url = a.get("href") or m.get("url") or f"{api}/attachments/{aid}"
            titre = m.get("title") or aid
            ext = Path(titre).suffix.lower() or ".bin"
            fichiers.append({"url": url, "nom": f"{src['id']}/{nom_sur(Path(titre).stem)}{ext}", "signature": sig})
        if not fichiers:
            raise RuntimeError("aucune piece jointe")
        return {"signature_source": sig, "fichiers": fichiers}
    if t == "datagouv":
        ds = client.json(f"{DATAGOUV_API}/datasets/{src['dataset']}/", deadline=deadline)
        ressources = [r for r in ds.get("resources", [])
                      if (not src.get("format") or (r.get("format") or "").lower() == src["format"].lower())
                      and (not src.get("titre_contient") or src["titre_contient"].lower() in (r.get("title") or "").lower())
                      and (r.get("format") or "").lower() not in FORMATS_IGNORES
                      and r.get("type", "main") in ("main", "update", "documentation", "other")]
        if src.get("types_ressource"):
            ressources = [r for r in ressources if r.get("type") in src["types_ressource"]]
        if not ressources:
            raise SansRessource(f"aucune ressource telechargeable ({len(ds.get('resources', []))} ressource(s) publiee(s), "
                                "aucune en fichier)")
        if not src.get("toutes"):
            ressources = ressources[:1]
        fichiers, ignores, noms = [], [], set()
        for r in ressources[: src.get("max_ressources", 200)]:
            fmt = (r.get("format") or Path(r["url"]).suffix.lstrip(".") or "bin").lower()
            nom = f"{src['id']}/{nom_sur(Path(r.get('title') or r['id']).stem, 60)}_{r['id'][:8]}.{nom_sur(fmt, 10)}"
            taille = r.get("filesize")
            if max_octets and taille and taille > max_octets:
                ignores.append({"url": r["url"], "titre": r.get("title"), "octets": taille, "motif": "lourd"})
                continue
            if nom in noms:
                continue
            noms.add(nom)
            fichiers.append({"url": r["url"], "nom": nom, "taille": taille,
                             "signature": f"{r.get('last_modified')}|{(r.get('checksum') or {}).get('value')}"})
        return {"signature_source": ds.get("last_update"), "fichiers": fichiers, "ignores": ignores}
    if t == "datagouv_ressources":
        # ressources precises par identifiant (rid) ; la date de la ressource sert de signature
        fichiers, ignores = [], []
        for rid in src["ressources"]:
            d = client.json(f"https://www.data.gouv.fr/api/2/datasets/resources/{rid}/", deadline=deadline)
            r = d["resource"]
            fmt = (r.get("format") or Path(r["url"]).suffix.lstrip(".") or "bin").lower()
            if max_octets and r.get("filesize") and r["filesize"] > max_octets and not src.get("lourd"):
                ignores.append({"url": r["url"], "titre": r.get("title"), "octets": r["filesize"], "motif": "lourd"})
                continue
            fichiers.append({"url": r["url"], "nom": f"{src['id']}/{nom_sur(Path(r.get('title') or rid).stem, 60)}_{rid[:8]}.{nom_sur(fmt, 10)}",
                             "taille": r.get("filesize"),
                             "signature": f"{r.get('last_modified')}|{(r.get('checksum') or {}).get('value')}"})
        return {"fichiers": fichiers, "ignores": ignores}
    if t == "index_http":
        # repertoire de fichiers (index Apache) : fichiers dont le nom correspond au motif, les plus recents en dernier
        fichiers = lister_index_http(client, src["url"], re.compile(src.get("motif", ".")), src.get("profondeur", 0), deadline)
        fichiers = sorted(fichiers, key=lambda f: f[0])
        if src.get("max_fichiers"):
            fichiers = fichiers[-src["max_fichiers"]:]
        if not fichiers:
            raise SansRessource("aucun fichier correspondant dans le repertoire")
        return {"fichiers": [{"url": u, "nom": f"{src['id']}/{nom_sur(nom, 120)}", "signature": f"{date}|{taille}", "taille": taille}
                             for nom, u, date, taille in fichiers]}
    if t == "ted_recherche":
        return {"fichiers": [{"url": "https://api.ted.europa.eu/v3/notices/search", "nom": f"{src['id']}.ndjson",
                              "signature": None, "ted": True}]}
    if t == "eurostat":
        params = urlencode(src.get("params", {}), doseq=True)
        return {"fichiers": [{"url": f"{portails['eurostat']}/{src['dataset']}?{params}", "nom": f"{src['id']}.json", "signature": None}]}
    if t == "url":
        return {"fichiers": [{"url": src["url"], "nom": f"{src['id']}.{src.get('format', 'bin')}", "signature": None}]}
    if t == "urls":
        return {"fichiers": [{"url": u["url"], "nom": f"{src['id']}/{u['nom']}", "signature": None} for u in src["urls"]]}
    raise RuntimeError(f"type inconnu : {t}")


def dossier_source(src: dict) -> Path:
    """Les sources contenant des donnees de personnes physiques vont dans une zone separee."""
    if src.get("personnes_physiques"):
        return LAKE / "_restreint" / src["domaine"]
    return LAKE / src["domaine"]


_LIGNE_INDEX = re.compile(r'<a href="([^"?/][^"]*)">[^<]*</a>\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s+([\d.]+[KMG]?|-)')


def _octets_index(t: str) -> int | None:
    if t == "-":
        return None
    mult = {"K": 1e3, "M": 1e6, "G": 1e9}.get(t[-1], 1)
    return int(float(t.rstrip("KMG")) * mult)


def lister_index_http(client: Client, url: str, motif: re.Pattern, profondeur: int = 0, deadline=None) -> list[tuple]:
    """Lit un index de repertoire HTTP (format Apache) : [(nom, url, date, octets)]."""
    url = url if url.endswith("/") else url + "/"
    html = client.get(url, deadline=deadline).text
    sortie = []
    for nom, date, taille in _LIGNE_INDEX.findall(html):
        if nom.endswith("/"):
            if profondeur > 0:
                sortie += lister_index_http(client, url + nom, motif, profondeur - 1, deadline)
        elif motif.search(nom):
            sortie.append((nom, url + nom, date, _octets_index(taille)))
    return sortie


def _fichier_reutilisable(ancien_f: dict | None, signature) -> bool:
    if not ancien_f or signature is None or ancien_f.get("signature") != signature:
        return False
    p = ROOT / ancien_f["chemin"]
    if p.exists() and p.stat().st_size == ancien_f.get("octets"):
        return True
    return STOCKE_A_DISTANCE and bool(ancien_f.get("stockage")) and not ancien_f.get("envoi_en_attente")


def collecter(client: Client, src: dict, ancien: dict, portails: dict, *, timeout_s: float,
              force: bool = False, max_octets: int | None = None) -> dict:
    debut = time.time()
    deadline = debut + timeout_s
    entree = {k: src.get(k) for k in ("titre", "domaine", "licence", "producteur", "portail", "dataset", "origine")
              if src.get(k) is not None}
    entree["personnes_physiques"] = bool(src.get("personnes_physiques", False))
    entree["zone"] = "restreinte" if entree["personnes_physiques"] else "publique"
    if src.get("elus_nommes"):
        entree["elus_nommes"] = True  # elus nommes dans leur role public (votes, amendements) : zone publique, marque
    entree["collecte_le"] = maintenant()
    entree["fichiers"] = []
    anciens = {f["chemin"]: f for f in ancien.get("fichiers", [])} if not force else {}
    try:
        plan = plan_source(client, src, portails, deadline, max_octets)
        entree["signature_source"] = plan.get("signature_source")
        if plan.get("ignores"):
            entree["ignores"] = plan["ignores"]
        inchanges = 0
        racine = dossier_source(src)
        for spec in plan["fichiers"]:
            cible = racine / spec["nom"]
            chemin = str(cible.relative_to(ROOT))
            vieux = anciens.get(chemin)
            if _fichier_reutilisable(vieux, spec.get("signature")):
                entree["fichiers"].append({**vieux, "change": False, "verifie_le": maintenant()})
                inchanges += 1
                continue
            if spec.get("ted"):
                res = telecharger_ted(client, src, cible, deadline)
                entree["fichiers"].append({"url": spec["url"], "chemin": chemin, "requete": src["requete"], **res,
                                           "change": (vieux or {}).get("sha256") != res["sha256"]})
                continue
            try:
                present = cible.exists() or (STOCKE_A_DISTANCE and bool((vieux or {}).get("stockage")))
                res = telecharger(client, spec["url"], cible, deadline=deadline,
                                  ancien=vieux if vieux and present else None, max_octets=max_octets)
            except TropLourd as exc:
                entree.setdefault("ignores", []).append({"url": spec["url"], "titre": spec["nom"], "motif": f"lourd ({exc})"})
                continue
            except DelaiDepasse:
                raise
            except Exception as exc:
                if len(plan["fichiers"]) == 1:
                    raise
                # une ressource en echec (lien mort, page web, refus) n'annule pas les autres
                entree.setdefault("erreurs_fichiers", []).append({"url": spec["url"], "erreur": str(exc)[:300]})
                continue
            if res.get("inchange"):
                entree["fichiers"].append({**vieux, "change": False, "verifie_le": maintenant(),
                                           "signature": spec.get("signature")})
                inchanges += 1
                continue
            info = {"url": spec["url"], "chemin": chemin, "signature": spec.get("signature"), **res}
            info.update(decrire(cible))
            if cible.suffix == ".parquet" and "lecture" in info:
                cible.unlink(missing_ok=True)
                raise RuntimeError("parquet incomplet (transfert tronque en cours de route), a reprendre")
            info["change"] = (vieux or {}).get("sha256") != info["sha256"]
            entree["fichiers"].append(info)
        if not entree["fichiers"]:
            if entree.get("erreurs_fichiers"):
                raise RuntimeError("toutes les ressources en echec, ex. " + entree["erreurs_fichiers"][0]["erreur"])
            if entree.get("ignores"):
                entree["statut"] = "lourd_ignore"
                entree["erreur"] = f"{len(entree['ignores'])} ressource(s) > seuil, a prendre avec --lourd"
                entree["duree_s"] = round(time.time() - debut, 1)
                return entree
            raise RuntimeError("aucun fichier collecte")
        entree["statut"] = "partiel" if entree.get("erreurs_fichiers") else "ok"
        entree["inchange"] = inchanges == len(entree["fichiers"])
    except SansRessource as exc:
        entree["statut"] = "sans_ressource"
        entree["erreur"] = str(exc)[:500]
    except DelaiDepasse as exc:
        entree["statut"] = "delai_depasse"
        entree["erreur"] = f"{exc} (budget {int(timeout_s)} s)"
    except Exception as exc:
        entree["statut"] = "erreur"
        entree["erreur"] = str(exc)[:500]
    if entree["statut"] not in ("ok", "partiel") and ancien.get("statut") in ("ok", "partiel") and not entree["fichiers"]:
        # les fichiers d'une collecte precedente restent sur disque : on garde leur trace
        entree["fichiers"] = [{**f, "donnees_anterieures": True} for f in ancien.get("fichiers", [])]
    entree["duree_s"] = round(time.time() - debut, 1)
    return entree


# ---------------------------------------------------------------- decouvertes -> sources

def sources_depuis_decouvertes(decouvertes: list[dict], catalogue: list[dict], score_min: float,
                               portails_inclus: list[str] | None = None) -> list[dict]:
    """Transforme les jeux decouverts en entrees de collecte, sans doublon avec le catalogue manuel."""
    deja = {(s.get("portail") or ("datagouv" if s["type"] == "datagouv" else None), s.get("dataset")) for s in catalogue}
    sorties = []
    for d in decouvertes:
        if d.get("score", 0) < score_min or d.get("doublon_de") or exclu(d.get("titre")):
            continue
        if portails_inclus and d["portail"] not in portails_inclus:
            continue
        if (d["portail"], d["dataset"]) in deja:
            continue
        base = {"id": d["id"], "domaine": d.get("domaine", "divers"), "titre": d.get("titre"),
                "licence": d.get("licence"), "producteur": d.get("producteur"), "dataset": d["dataset"],
                "personnes_physiques": bool(d.get("personnes_physiques")), "origine": "decouverte",
                "lourd": bool(d.get("lourd"))}
        if d["portail"] == "datagouv":
            if d.get("nb_ressources") == 0:
                continue
            sorties.append({**base, "type": "datagouv", "portail": "datagouv", "toutes": True, "types_ressource": ["main"]})
        elif d.get("nb_lignes"):
            sorties.append({**base, "type": "ods_export", "portail": d["portail"]})
        elif d.get("nb_pieces_jointes"):
            sorties.append({**base, "type": "ods_pieces_jointes", "portail": d["portail"]})
    rang = {d["id"]: (priorite_producteur(d), d.get("score", 0)) for d in decouvertes}
    return sorted(sorties, key=lambda s: (-rang[s["id"]][0], -rang[s["id"]][1], s["id"]))


# exclusions volontaires : aides PAC et registre parcellaire (publication legale limitee, donnees agricoles
# nominatives), declarations de patrimoine des elus (HATVP, hors objet)
# + jeux hors sujet ramenes par la decouverte (sante, transports, equipements, etat civil...)
EXCLUSIONS = re.compile(r"registre parcellaire|\brpg\b|politique agricole commune|\bpac\b|ilots culturaux|"
                        r"declarations? de (situation )?patrimoine|"
                        r"vaccin|catalogue (de|des) formations?|\bgtfs\b|horaires|arr[eê]ts? de (bus|tram)|"
                        r"stationnement|v[eé]los? en libre|qualit[eé] de l.air|pollens?|toilettes publiques|"
                        r"d[eé]fibrillateur|wifi|pr[eé]noms|[eé]tat civil|bornes? de recharge|"
                        r"r[eé]sultats? (des |d.)?[eé]lections?|candidatures?|bureaux de vote|"
                        r"jurisprudence et d[eé]cisions d.opposition|m[eé]tadonn[eé]es des rapports", re.I)


def exclu(titre: str | None) -> bool:
    return bool(EXCLUSIONS.search(titre or ""))


def purger_exclus() -> list[str]:
    """Supprime de l'entrepot les sources decouvertes dont le titre tombe sous les exclusions."""
    import shutil
    retires = []
    with _verrou(MANIFEST):
        m = lire_manifeste()
        for sid in list(m):
            e = m[sid]
            if e.get("origine") != "decouverte" or not exclu(e.get("titre")):
                continue
            for f in e.get("fichiers", []):
                (ROOT / f["chemin"]).unlink(missing_ok=True)
            d = dossier_source(e) / sid
            if d.is_dir():
                shutil.rmtree(d)
            retires.append(sid)
            del m[sid]
        tmp = MANIFEST.with_name(MANIFEST.name + ".tmp")
        tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, MANIFEST)
    return retires

PORTAILS_FINANCIERS = {"economie", "ofgl", "urssaf", "cdc"}
PRODUCTEURS_FINANCIERS = re.compile(r"dgfip|finances publiques|budget|\bdb\b|dgcl|ofgl|urssaf|cnccfp|hatvp|cour des comptes|"
                                    r"tresor|economiques et financiers|bpifrance|caisse des depots|agence de services", re.I)
PRODUCTEURS_LOCAUX = re.compile(r"r[ée]gion|d[ée]partement|m[ée]tropole|ville de|mairie|commune|agglom|conseil", re.I)


def priorite_producteur(d: dict) -> int:
    """3 = producteur public financier, 2 = ministere ou collectivite, 1 = autre."""
    prod = d.get("producteur") or ""
    if d["portail"] in PORTAILS_FINANCIERS or PRODUCTEURS_FINANCIERS.search(prod):
        return 3
    if d["portail"].startswith("ods_") or re.search(r"minist", prod, re.I) or PRODUCTEURS_LOCAUX.search(prod):
        return 2
    return 1


def reclasser(decouvertes: list[dict]) -> int:
    """Aligne le domaine (et donc le dossier) des sources decouvertes deja collectees sur le domaine
    presume de la derniere decouverte : deplace les fichiers et met a jour le manifeste. A lancer
    quand aucune collecte ne tourne."""
    domaines = {d["id"]: d.get("domaine", "divers") for d in decouvertes}
    n = 0
    with _verrou(MANIFEST):
        m = lire_manifeste()
        for sid, e in m.items():
            nouveau = domaines.get(sid)
            if e.get("origine") != "decouverte" or not nouveau or nouveau == e.get("domaine"):
                continue
            racine = dossier_source({"domaine": nouveau, "personnes_physiques": e.get("personnes_physiques")})
            ancienne = dossier_source({"domaine": e["domaine"], "personnes_physiques": e.get("personnes_physiques")})
            for f in e.get("fichiers", []):
                src = ROOT / f["chemin"]
                dst = racine / src.relative_to(ancienne)
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(src, dst)
                f["chemin"] = str(dst.relative_to(ROOT))
            vieux_dossier = ancienne / sid
            if vieux_dossier.is_dir() and not any(vieux_dossier.iterdir()):
                vieux_dossier.rmdir()
            e["domaine"] = nouveau
            n += 1
        tmp = MANIFEST.with_name(MANIFEST.name + ".tmp")
        tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, MANIFEST)
    return n


# ---------------------------------------------------------------- programme

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--lourd", action="store_true", help="inclure les sources lourdes (> 100 Mo)")
    ap.add_argument("--domaine")
    ap.add_argument("--liste", action="store_true")
    ap.add_argument("--timeout", type=float, help=f"budget en secondes par source (defaut {TIMEOUT_DEFAUT_S}, lourdes {TIMEOUT_LOURD_S})")
    ap.add_argument("--force", action="store_true", help="retelecharger meme si inchange")
    ap.add_argument("--pause", type=float, default=0.5, help="pause minimale entre deux appels (s)")
    ap.add_argument("--decouvertes", action="store_true", help="collecter les jeux de decouvertes.json au lieu du catalogue")
    ap.add_argument("--score-min", type=float, default=4)
    ap.add_argument("--portail", action="append", help="limiter les decouvertes a un portail (repetable)")
    ap.add_argument("--limite", type=int, help="nombre maximal de sources dans ce lot")
    ap.add_argument("--tranche", help="i/n : ne traiter qu'une source sur n (decalage i), pour paralleliser")
    ap.add_argument("--sauter-traites", action="store_true", help="ignorer toute source deja presente dans le manifeste")
    ap.add_argument("--sauter-ok", action="store_true", help="ignorer les sources deja ok dans le manifeste (sans verifier l'amont)")
    ap.add_argument("--reserve-go", type=float, default=4, help="espace disque libre a preserver (Go) : en dessous, les sources sont sautees")
    ap.add_argument("--plafond-go", type=float, default=25, help="taille maximale de l'entrepot (Go, d'apres le manifeste)")
    ap.add_argument("--purger-exclus", action="store_true", help="retirer de l'entrepot les decouvertes hors sujet (EXCLUSIONS)")
    ap.add_argument("--reclasser", action="store_true", help="aligner les domaines des sources decouvertes sur decouvertes.json")
    ap.add_argument("--max-mo", type=float, default=100, help="taille max par fichier data.gouv.fr sans --lourd (Mo)")
    ap.add_argument("--flux", action="store_true",
                    help="mode flux (collecte/stockage.py) : convertir, envoyer au stockage objet, verifier, effacer en local")
    a = ap.parse_args(argv)

    cat = charger_catalogue()
    portails = charger_portails(cat)
    if a.purger_exclus:
        r = purger_exclus()
        print(f"{len(r)} sources hors sujet retirees de l'entrepot")
        return 0
    if a.reclasser:
        print(f"{reclasser(lire_decouvertes()['jeux'])} sources decouvertes reclassees")
        return 0
    if a.decouvertes:
        dec = lire_decouvertes()["jeux"]
        sources = sources_depuis_decouvertes(dec, cat["sources"], a.score_min, a.portail)
    else:
        sources = cat["sources"]
    if a.liste:
        for s in sources:
            print(f"{s['domaine']:<14} {s['id']:<48} {'LOURD ' if s.get('lourd') else ''}{s['titre']}")
        print(f"{len(sources)} sources")
        return 0
    choix = [s for s in sources
             if (not a.ids or s["id"] in a.ids)
             and (not a.domaine or s["domaine"] == a.domaine)
             and (a.lourd or a.ids or not s.get("lourd"))]
    flux = None
    if a.flux:
        global STOCKE_A_DISTANCE
        import stockage  # collecte/ est dans sys.path (script) : branchement optionnel
        try:
            flux = stockage.Flux.depuis_env()
        except stockage.ErreurConfig as exc:
            print(f"CONFIGURATION : {exc}", file=sys.stderr)
            return 78
        STOCKE_A_DISTANCE = True
        if stockage.restaurer_manifeste(flux):
            print("manifeste recupere depuis le stockage objet", flush=True)
    manifeste = lire_manifeste()
    if a.sauter_traites:
        choix = [s for s in choix if s["id"] not in manifeste]
    if a.sauter_ok:
        choix = [s for s in choix if manifeste.get(s["id"], {}).get("statut") not in ("ok", "partiel")]
    if a.tranche:
        i, n = (int(x) for x in a.tranche.split("/"))
        choix = [s for k, s in enumerate(choix) if k % n == i]
    if a.limite:
        choix = choix[: a.limite]
    client = Client(pause=a.pause)
    erreurs = 0
    import shutil
    for s in choix:
        libre = shutil.disk_usage(LAKE if LAKE.exists() else ROOT).free
        volume = sum(f.get("octets", 0) for e in manifeste.values() for f in e.get("fichiers", []))
        if volume > a.plafond_go * 1e9 and not flux:
            print(f"PLAFOND  {s['id']:<48} saute : entrepot {volume / 1e9:.1f} Go > plafond {a.plafond_go} Go", flush=True)
            erreurs += 1
            continue
        if libre < a.reserve_go * 1e9:
            print(f"ESPACE   {s['id']:<48} saute : {libre / 1e9:.1f} Go libres < reserve {a.reserve_go} Go", flush=True)
            erreurs += 1
            continue
        budget = a.timeout or s.get("timeout_s") or (TIMEOUT_LOURD_S if s.get("lourd") else TIMEOUT_DEFAUT_S)
        max_octets = None if (a.lourd or s.get("lourd") is True and a.ids) else int(a.max_mo * 1e6)
        e = collecter(client, s, manifeste.get(s["id"], {}), portails, timeout_s=budget, force=a.force,
                      max_octets=max_octets)
        if flux:
            e = flux.apres_collecte(s["id"], e, manifeste.get(s["id"], {}))
        manifeste = maj_manifeste(s["id"], e)
        if flux:
            flux.peut_etre_sauver()
        if e["statut"] in ("ok", "partiel"):
            mo = sum(f.get("octets", 0) for f in e["fichiers"]) / 1e6
            lignes = sum(f.get("lignes", 0) or 0 for f in e["fichiers"])
            etat = "INCHANGE" if e.get("inchange") else e["statut"].upper()
            print(f"{etat:<8} {s['id']:<48} {mo:9.1f} Mo {lignes:>11,} lignes  {e['duree_s']}s", flush=True)
        else:
            erreurs += 1
            print(f"{e['statut'].upper():<8} {s['id']:<48} {e['erreur'][:140]}", flush=True)
    print(f"\n{len(choix) - erreurs}/{len(choix)} sources collectees, manifeste : {MANIFEST.relative_to(ROOT)}")
    if flux:
        flux.peut_etre_sauver(force=True)
        print(f"stockage : {flux.envoyes} fichier(s) envoye(s), {flux.dedupliques} inchange(s), "
              f"{flux.echecs} echec(s) d'envoi ; {flux.octets_avant / 1e6:.0f} Mo -> {flux.octets_apres / 1e6:.0f} Mo")
        if flux.echecs:
            return 2
    return 1 if choix and erreurs == len(choix) else 0


if __name__ == "__main__":
    sys.exit(main())
