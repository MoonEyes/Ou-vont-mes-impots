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
import fcntl
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
USER_AGENT = "ou-vont-mes-impots-collecte/0.3 (projet citoyen open source, collecte de donnees ouvertes)"
DATAGOUV_API = "https://www.data.gouv.fr/api/1"
TIMEOUT_DEFAUT_S = 900          # budget par source (non lourde)
TIMEOUT_LOURD_S = 3600          # budget par source lourde
SEUIL_LOURD_OCTETS = 100 * 10**6
FORMATS_IGNORES = {"html", "htm", "api", "url", "web page", "ogc:wms", "ogc:wfs", "esri rest", "php"}


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def charger_catalogue(chemin: Path = CATALOGUE_PATH) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- reseau

class DelaiDepasse(RuntimeError):
    """Le budget de temps de la source est epuise."""


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

    def _attendre_tour(self):
        reste = self.pause - (time.time() - self._dernier)
        if reste > 0:
            time.sleep(reste)
        self._dernier = time.time()

    def get(self, url: str, *, stream: bool = False, headers: dict | None = None,
            deadline: float | None = None, essais: int | None = None, params: dict | None = None) -> requests.Response:
        essais = essais or self.essais
        erreur = None
        for tentative in range(1, essais + 1):
            if deadline and time.time() > deadline:
                raise DelaiDepasse(f"budget de temps epuise avant {url}")
            self._attendre_tour()
            attente = min(2 ** tentative, 30)
            try:
                r = self.s.get(url, headers=headers, stream=stream, timeout=self.timeouts, params=params)
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
                ancien: dict | None = None, essais_flux: int = 6) -> dict:
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
        if ancien and cible.exists() and not tmp.exists():
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
                attendu = r.headers.get("Content-Length")
                if attendu and r.status_code == 200 and int(attendu) != n and "gzip" not in r.headers.get("Content-Encoding", ""):
                    raise requests.exceptions.ChunkedEncodingError(f"transfert tronque {n}/{attendu}")
            break
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
        fcntl.flock(v, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(v, fcntl.LOCK_UN)


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
            return {"signature_source": sig,
                    "fichiers": [{"url": f"{api}/exports/parquet{q}", "nom": f"{src['id']}.parquet", "signature": sig + q}]}
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
            raise RuntimeError("aucune ressource telechargeable correspondante")
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


def _fichier_reutilisable(ancien_f: dict | None, signature) -> bool:
    if not ancien_f or signature is None or ancien_f.get("signature") != signature:
        return False
    p = ROOT / ancien_f["chemin"]
    return p.exists() and p.stat().st_size == ancien_f.get("octets")


def collecter(client: Client, src: dict, ancien: dict, portails: dict, *, timeout_s: float,
              force: bool = False, max_octets: int | None = None) -> dict:
    debut = time.time()
    deadline = debut + timeout_s
    entree = {k: src.get(k) for k in ("titre", "domaine", "licence", "producteur", "portail", "dataset", "origine")
              if src.get(k) is not None}
    entree["personnes_physiques"] = bool(src.get("personnes_physiques", False))
    entree["zone"] = "restreinte" if entree["personnes_physiques"] else "publique"
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
            res = telecharger(client, spec["url"], cible, deadline=deadline,
                              ancien=vieux if vieux and cible.exists() else None)
            if res.get("inchange"):
                entree["fichiers"].append({**vieux, "change": False, "verifie_le": maintenant(),
                                           "signature": spec.get("signature")})
                inchanges += 1
                continue
            info = {"url": spec["url"], "chemin": chemin, "signature": spec.get("signature"), **res}
            info.update(decrire(cible))
            info["change"] = (vieux or {}).get("sha256") != info["sha256"]
            entree["fichiers"].append(info)
        if not entree["fichiers"]:
            raise RuntimeError("aucun fichier collecte (toutes les ressources ignorees ?)")
        entree["statut"] = "ok"
        entree["inchange"] = inchanges == len(entree["fichiers"])
    except DelaiDepasse as exc:
        entree["statut"] = "delai_depasse"
        entree["erreur"] = f"{exc} (budget {int(timeout_s)} s)"
    except Exception as exc:
        entree["statut"] = "erreur"
        entree["erreur"] = str(exc)[:500]
    if entree["statut"] != "ok" and ancien.get("statut") == "ok" and not entree["fichiers"]:
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
        if d.get("score", 0) < score_min or d.get("doublon_de"):
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
            sorties.append({**base, "type": "datagouv", "portail": "datagouv", "toutes": True, "types_ressource": ["main"]})
        elif d.get("nb_lignes"):
            sorties.append({**base, "type": "ods_export", "portail": d["portail"]})
        elif d.get("nb_pieces_jointes"):
            sorties.append({**base, "type": "ods_pieces_jointes", "portail": d["portail"]})
    return sorties


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
    ap.add_argument("--sauter-ok", action="store_true", help="ignorer les sources deja ok dans le manifeste (sans verifier l'amont)")
    ap.add_argument("--max-mo", type=float, default=100, help="taille max par fichier data.gouv.fr sans --lourd (Mo)")
    a = ap.parse_args(argv)

    cat = charger_catalogue()
    portails = cat["portails"]
    if a.decouvertes:
        dec = json.loads(DECOUVERTES_PATH.read_text(encoding="utf-8"))["jeux"]
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
    manifeste = lire_manifeste()
    if a.sauter_ok:
        choix = [s for s in choix if manifeste.get(s["id"], {}).get("statut") != "ok"]
    if a.limite:
        choix = choix[: a.limite]
    client = Client(pause=a.pause)
    erreurs = 0
    for s in choix:
        budget = a.timeout or s.get("timeout_s") or (TIMEOUT_LOURD_S if s.get("lourd") else TIMEOUT_DEFAUT_S)
        max_octets = None if (a.lourd or s.get("lourd") is True and a.ids) else int(a.max_mo * 1e6)
        e = collecter(client, s, manifeste.get(s["id"], {}), portails, timeout_s=budget, force=a.force,
                      max_octets=max_octets)
        manifeste = maj_manifeste(s["id"], e)
        if e["statut"] == "ok":
            mo = sum(f.get("octets", 0) for f in e["fichiers"]) / 1e6
            lignes = sum(f.get("lignes", 0) or 0 for f in e["fichiers"])
            etat = "INCHANGE" if e.get("inchange") else "OK"
            print(f"{etat:<8} {s['id']:<48} {mo:9.1f} Mo {lignes:>11,} lignes  {e['duree_s']}s", flush=True)
        else:
            erreurs += 1
            print(f"{e['statut'].upper():<8} {s['id']:<48} {e['erreur'][:140]}", flush=True)
    print(f"\n{len(choix) - erreurs}/{len(choix)} sources collectees, manifeste : {MANIFEST.relative_to(ROOT)}")
    return 1 if choix and erreurs == len(choix) else 0


if __name__ == "__main__":
    sys.exit(main())
