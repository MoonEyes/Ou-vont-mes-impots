"""Entrepôt des entrées du pipeline : inventaire, diagnostic, copie distante (bucket public OVH) et lignée.

    python pipeline/entrepot_distant.py diagnostic [--markdown]   # par étape : où sont les entrées (local, URL, VPS)
    python pipeline/entrepot_distant.py lignee [--etapes a,b]      # écrit pipeline/lignee.json (versions des entrées)
    python pipeline/entrepot_distant.py restaurer [--etapes a,b]   # CI, LECTURE SEULE : bucket public -> data/lake
    python pipeline/entrepot_distant.py envoyer                    # VPS, écriture : data/lake -> bucket public
    python pipeline/entrepot_distant.py verifier [--journal J]     # reconstruction complète : code 6 si incomplet

Pourquoi un dossier à part dans le bucket. La collecte du VPS (collecte/stockage.py) range chaque source convertie en
Parquet : l'original CSV ou XLSX n'est pas gardé, alors que les modules du pipeline lisent les fichiers d'origine et
que leurs sorties dépendent des octets lus. Les seules entrées du pipeline (pipeline/entrees_lac.json, quelques Go)
sont donc aussi rangées telles quelles, adressées par leur contenu :

    s3://<bucket public>/_entrees/objets/<sha256[:2]>/<sha256>     octets d'origine, jamais réécrits
    s3://<bucket public>/_entrees/index.json                       chemin -> sha256, octets, source, collecte_le

Un objet n'est jamais remplacé (sa clé est son empreinte) : l'historique est gratuit et une version publiée reste
retrouvable tant que pipeline/lignee.json la nomme.

Règles :
  - la zone data/lake/_restreint (personnes physiques) n'entre jamais dans l'index public ni dans un objet public ;
    `restaurer` refuse toute entrée de cette zone et tout chemin hors de data/lake ;
  - `restaurer` ne fait que des GET : anonyme si le bucket est lisible publiquement (OVMI_LAC_URL), sinon signé
    (AWS SigV4, bibliothèque standard) avec une clé en lecture seule passée par des secrets GitHub
    (OVMI_S3_LECTURE_ID, OVMI_S3_LECTURE_SECRET) ; chaque objet est vérifié (sha256) avant d'être mis en place ;
  - `restaurer` remet aussi dans data/lake/manifest.json la date de collecte de chaque source restaurée : les dates
    écrites par pipeline/reproductible.py sont celles de la version collectée, pas celles de la restauration ;
  - `envoyer` réutilise collecte/stockage.py (rclone, configuration /etc/ovmi/stockage.env) ; il ne tourne que là où
    les clés d'écriture existent (VPS), jamais en CI.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
ENTREES = ROOT / "pipeline" / "entrees_lac.json"
LIGNEE = ROOT / "pipeline" / "lignee.json"
MANIFESTE = LAKE / "manifest.json"
PREFIXE = "_entrees"
RESTREINT = "data/lake/_restreint"
CODE_INCOMPLET = 6
# journaux de collecte écrits par les modules à côté des bruts, jamais lus par la production (horodatés)
JOURNAUX = {"collecte.json"}


# --- Inventaire des entrées --------------------------------------------------------------------------------------

def charger_entrees() -> dict:
    return json.loads(ENTREES.read_text(encoding="utf-8"))


def est_restreint(chemin: str) -> bool:
    return chemin == RESTREINT or chemin.startswith(RESTREINT + "/")


def chemin_sur(chemin: str) -> bool:
    """Chemin relatif sous data/lake, sans remontée ni lien absolu."""
    p = Path(chemin)
    return (not p.is_absolute() and chemin.startswith("data/lake/") and ".." not in p.parts
            and "\\" not in chemin and "\0" not in chemin)


def _fichiers_sous(rel: str) -> list[str]:
    p = ROOT / rel
    if p.is_file():
        return [rel]
    if p.is_dir():
        return sorted(str(f.relative_to(ROOT)) for f in p.rglob("*")
                      if f.is_file() and not f.name.endswith((".part", ".lock", ".tmp")) and f.name not in JOURNAUX)
    return []


def entrees_etape(etape: str, entrees: dict | None = None) -> list[dict]:
    """Entrées déclarées d'une étape : {chemin, type (catalogue, hors_catalogue, cache), source, url}."""
    entrees = entrees or charger_entrees()
    e = entrees["etapes"].get(etape, {})
    urls = entrees.get("urls", {})
    out = []
    for sid, chemins in sorted(e.get("sources", {}).items()):
        for c in chemins:
            out.append({"chemin": c, "type": "catalogue", "source": sid, "url": urls.get(c)})
    for c in e.get("hors_catalogue", []):
        out.append({"chemin": c, "type": "hors_catalogue", "source": None, "url": urls.get(c)})
    for c in e.get("caches", []):
        out.append({"chemin": c, "type": "cache", "source": None, "url": None})
    return out


def sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _manifeste() -> dict:
    try:
        m = json.loads(MANIFESTE.read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def _proprietaires(man: dict) -> dict[str, str]:
    return {f["chemin"]: sid for sid, ent in man.items() if isinstance(ent, dict)
            for f in ent.get("fichiers", []) if isinstance(f, dict) and f.get("chemin")}


# --- Diagnostic --------------------------------------------------------------------------------------------------

def diagnostic(index_distant: dict | None = None, collecteurs: dict[str, bool] | None = None) -> dict:
    """Pour chaque étape de pipeline/tout.py : entrées, présence locale, zone, possibilité de recollecte, présence
    dans l'index distant. `collecteurs` : étape -> a une commande « collecter » (défaut : lu dans pipeline/tout.py)."""
    entrees = charger_entrees()
    if collecteurs is None:
        sys.path.insert(0, str(ROOT / "pipeline"))
        import tout   # noqa: E402  (bibliothèque standard seulement)
        # une étape recollecte ses entrées hors catalogue par sa commande « collecter », par une production en
        # réseau (local : reprenable) ou par celles d'une étape amont qui dépose les fichiers qu'elle lit
        propre = {e.id: bool(e.collecter) or e.a_relancer is not None for e in tout.ETAPES}
        collecteurs = {}
        for e in tout.ordre():
            collecteurs[e.id] = propre[e.id] or any(collecteurs.get(d) for d in e.deps)
        ordre = [e.id for e in tout.ordre()]
    else:
        ordre = list(collecteurs)
    distants = set((index_distant or {}).get("fichiers", {}))
    urls_manifeste = {f["chemin"]: f.get("url") for ent in _manifeste().values() if isinstance(ent, dict)
                      for f in ent.get("fichiers", []) if isinstance(f, dict) and f.get("chemin")}
    sortie = {}
    for eid in ordre:
        lignes = entrees_etape(eid, entrees)
        detail = []
        for x in lignes:
            local = (ROOT / x["chemin"]).exists() and bool(_fichiers_sous(x["chemin"]))
            restreint = est_restreint(x["chemin"])
            if restreint:
                recollecte = "VPS seulement (zone restreinte, jamais en CI)"
            elif x["url"]:
                recollecte = "tout.py entrepot (URL publique relevée)"
            elif any(u and (c == x["chemin"] or c.startswith(x["chemin"] + "/")) for c, u in urls_manifeste.items()):
                recollecte = "collecte/collecte.py (sources du catalogue rangées dans ce dossier)"
            elif collecteurs.get(eid):
                recollecte = "commande collecter du module ou d'une étape amont"
            else:
                recollecte = "aucune (ni URL relevée ni commande collecter)"
            fichiers_distants = [f for f in distants if f == x["chemin"] or f.startswith(x["chemin"] + "/")]
            detail.append({**x, "local": local, "restreint": restreint, "recollecte": recollecte,
                           "distant": bool(fichiers_distants)})
        manquantes_ci = [d for d in detail if not d["restreint"] and not d["distant"]]
        sans_recollecte = [d for d in detail if d["recollecte"].startswith("aucune")]
        if not detail:
            verdict = "aucune entrée de data/lake déclarée (lit seulement des fichiers versionnés ou le réseau)"
        elif sans_recollecte:
            verdict = "non régénérable : entrée sans URL ni collecteur"
        elif any(d["restreint"] for d in detail) and not manquantes_ci:
            verdict = "régénérable en CI hors zone restreinte (VPS pour le reste)"
        elif manquantes_ci:
            verdict = "régénérable seulement par recollecte à la source (aucune copie durable des entrées)"
        else:
            verdict = "régénérable depuis le bucket"
        sortie[eid] = {"entrees": detail, "verdict": verdict, "n": len(detail),
                       "local": sum(d["local"] for d in detail), "restreintes": sum(d["restreint"] for d in detail),
                       "distantes": sum(d["distant"] for d in detail),
                       "sans_url": sum(1 for d in detail if not d["url"] and not d["restreint"])}
    return sortie


def markdown(diag: dict) -> str:
    l = ["| Étape | Entrées | Présentes en local (poste agents) | Zone restreinte | Sans URL (collecteur du module) "
         "| Dans le bucket | Verdict |", "|---|---:|---:|---:|---:|---:|---|"]
    for eid, d in diag.items():
        l.append(f"| {eid} | {d['n']} | {d['local']} | {d['restreintes']} | {d['sans_url']} | {d['distantes']} "
                 f"| {d['verdict']} |")
    return "\n".join(l) + "\n"


# --- Lignée : versions des entrées des sorties publiées ------------------------------------------------------------

def lignee(etapes: list[str], date_sources: dict[str, str] | None = None) -> dict:
    """Relève sha256, taille et date de collecte de chaque fichier d'entrée présent ; fusionne avec la lignée
    existante (les autres étapes gardent leur relevé). `date_sources` : date injectée (SOURCE_DATE_EPOCH) par étape
    pour rejouer la production publiée."""
    doc = json.loads(LIGNEE.read_text(encoding="utf-8")) if LIGNEE.exists() else {}
    doc.setdefault("note", "Versions des entrées (data/lake) avec lesquelles les sorties publiées de site/data ont "
                           "été produites (python pipeline/entrepot_distant.py lignee). Les tests de "
                           "reproductibilité ne comparent aux sorties publiées que si l'entrepôt local contient "
                           "exactement ces versions ; `restaurer` les retrouve dans le bucket par leur sha256.")
    doc.setdefault("etapes", {})
    man = _manifeste()
    proprio = _proprietaires(man)
    for eid in etapes:
        fichiers = {}
        for x in entrees_etape(eid):
            for f in _fichiers_sous(x["chemin"]):
                sid = x["source"] or proprio.get(f)
                fichiers[f] = {"sha256": sha256(ROOT / f), "octets": (ROOT / f).stat().st_size,
                               "source": sid, "collecte_le": (man.get(sid) or {}).get("collecte_le") if sid else None}
        ancien = doc["etapes"].get(eid, {})
        doc["etapes"][eid] = {"fichiers": dict(sorted(fichiers.items())),
                              "date_sources": (date_sources or {}).get(eid, ancien.get("date_sources"))}
    doc["etapes"] = dict(sorted(doc["etapes"].items()))
    LIGNEE.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


def etat_lignee(etape: str, racine: Path = ROOT) -> tuple[bool, str]:
    """(True, motif) si l'entrepôt local contient exactement les versions enregistrées pour l'étape."""
    if not LIGNEE.exists():
        return False, "pipeline/lignee.json absent"
    e = json.loads(LIGNEE.read_text(encoding="utf-8")).get("etapes", {}).get(etape)
    if not e or not e.get("fichiers"):
        return False, f"aucune version enregistrée pour {etape} dans pipeline/lignee.json"
    absents, differents = [], []
    for c, info in e["fichiers"].items():
        p = racine / c
        if not p.is_file():
            absents.append(c)
        elif p.stat().st_size != info["octets"] or sha256(p) != info["sha256"]:
            differents.append(c)
    if absents or differents:
        return False, (f"entrepôt local différent de la version publiée de {etape} : {len(absents)} absent(s), "
                       f"{len(differents)} autre(s) version(s) (ex. {(absents + differents)[0]}) ; "
                       "python pipeline/entrepot_distant.py restaurer --etapes " + etape)
    return True, "versions enregistrées présentes"


def env_lignee(etape: str) -> dict[str, str]:
    """Environnement de production rejouant la version publiée : SOURCE_DATE_EPOCH = date enregistrée."""
    e = json.loads(LIGNEE.read_text(encoding="utf-8")).get("etapes", {}).get(etape, {})
    d = e.get("date_sources")
    if not d:
        return {}
    t = dt.datetime.fromisoformat(d.replace("Z", "+00:00"))
    return {"SOURCE_DATE_EPOCH": str(int((t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)).timestamp()))}


# --- Lecture distante (CI) : GET anonyme ou signé SigV4, rien d'autre ----------------------------------------------

class ConfigLecture:
    """Variables : OVMI_LAC_ENDPOINT (ex. s3.gra.io.cloud.ovh.net), OVMI_LAC_REGION (gra), OVMI_LAC_BUCKET (nom du
    bucket PUBLIC). Facultatives : OVMI_S3_LECTURE_ID / OVMI_S3_LECTURE_SECRET (clé en lecture seule, secrets
    GitHub) ; sans elles, lecture anonyme (bucket ouvert en lecture). OVMI_LAC_URL remplace endpoint et bucket par
    une URL de base (https://<bucket>.s3.<région>.io.cloud.ovh.net)."""

    def __init__(self, env: dict | None = None):
        env = os.environ if env is None else env
        self.base = (env.get("OVMI_LAC_URL") or "").strip().rstrip("/")
        endpoint = (env.get("OVMI_LAC_ENDPOINT") or "").strip().removeprefix("https://").rstrip("/")
        self.bucket = (env.get("OVMI_LAC_BUCKET") or "").strip().strip("/")
        self.region = (env.get("OVMI_LAC_REGION") or "gra").strip()
        if not self.base and endpoint and self.bucket:
            self.base = f"https://{endpoint}/{self.bucket}"
        self.cle = (env.get("OVMI_S3_LECTURE_ID") or "").strip()
        self.secret = (env.get("OVMI_S3_LECTURE_SECRET") or "").strip()
        prive = (env.get("OVMI_BUCKET_PRIVE") or "").strip().strip("/")
        if prive and self.bucket and (self.bucket == prive or self.bucket.startswith(prive + "/")):
            raise SystemExit("OVMI_LAC_BUCKET désigne le bucket privé : lecture refusée (zone restreinte jamais en CI)")
        if self.base and not self.base.startswith("https://"):
            raise SystemExit("OVMI_LAC_URL doit être en https://")

    @property
    def configuree(self) -> bool:
        return bool(self.base)

    @property
    def mode(self) -> str:
        return "signé (clé en lecture seule)" if self.cle and self.secret else "anonyme (bucket public)"

    def url(self, cle: str) -> str:
        return f"{self.base}/{urllib.parse.quote(cle)}"

    def entetes(self, url: str, maintenant: dt.datetime | None = None) -> dict[str, str]:
        if not (self.cle and self.secret):
            return {}
        return signer_get(url, self.cle, self.secret, self.region, maintenant)


def signer_get(url: str, cle: str, secret: str, region: str, maintenant: dt.datetime | None = None) -> dict[str, str]:
    """En-têtes AWS Signature V4 d'un GET sans corps (service s3)."""
    t = (maintenant or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    jour = t[:8]
    u = urllib.parse.urlsplit(url)
    vide = hashlib.sha256(b"").hexdigest()
    entetes = {"host": u.netloc, "x-amz-content-sha256": vide, "x-amz-date": t}
    noms = ";".join(sorted(entetes))
    canon = "\n".join(["GET", u.path or "/", u.query, *(f"{k}:{entetes[k]}" for k in sorted(entetes)), "", noms, vide])
    portee = f"{jour}/{region}/s3/aws4_request"
    a_signer = "\n".join(["AWS4-HMAC-SHA256", t, portee, hashlib.sha256(canon.encode()).hexdigest()])
    k = ("AWS4" + secret).encode()
    for m in (jour, region, "s3", "aws4_request"):
        k = hmac.new(k, m.encode(), hashlib.sha256).digest()
    signature = hmac.new(k, a_signer.encode(), hashlib.sha256).hexdigest()
    return {"x-amz-content-sha256": vide, "x-amz-date": t,
            "Authorization": f"AWS4-HMAC-SHA256 Credential={cle}/{portee}, SignedHeaders={noms}, Signature={signature}"}


def _get(cfg: ConfigLecture, cle: str, cible: Path | None = None, essais: int = 4, nom: str | None = None):
    """GET (anonyme ou signé). Avec `cible` : écrit dans ce temporaire puis contrôle d'intégrité (taille annoncée,
    format complet d'après `nom`, collecte/integrite.py) ; l'appelant vérifie ensuite le sha256 et renomme."""
    import requests
    from fetch import _integrite as fetch_integrite, octets_annonces
    integrite = fetch_integrite()
    erreur = None
    for n in range(essais):
        url = cfg.url(cle)
        try:
            with requests.get(url, headers=cfg.entetes(url), stream=True, timeout=(20, 300)) as r:
                if r.status_code in (401, 403, 404):
                    raise PermissionError(f"HTTP {r.status_code} pour {cle}")
                r.raise_for_status()
                if cible is None:
                    return r.content
                attendu = octets_annonces(r)
                with cible.open("wb") as f:
                    for bloc in r.iter_content(1 << 20):
                        f.write(bloc)
            if attendu is not None and cible.stat().st_size != attendu:
                raise requests.ConnectionError(f"transfert tronqué ({cible.stat().st_size} octets sur {attendu})")
            integrite.verifier_fichier(cible, nom=nom or cible.name)
            return cible
        except PermissionError:
            raise
        except integrite.IntegriteInvalide as exc:
            raise ConnectionError(f"{cle} : fichier incomplet ou invalide ({exc})") from exc
        except requests.RequestException as exc:
            erreur = exc
            time.sleep(2 ** (n + 1))
    raise ConnectionError(f"{cle} : {erreur}")


def objet(sha: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError(f"empreinte invalide : {sha!r}")
    return f"{PREFIXE}/objets/{sha[:2]}/{sha}"


def restaurer(cfg: ConfigLecture, etapes: list[str] | None, lignee_seule: bool = False) -> dict:
    """Complète data/lake depuis le bucket public. Fichier absent ou d'une autre version : objet téléchargé, vérifié
    (sha256), mis en place ; présent et identique : rien. Avec `lignee_seule`, les versions de pipeline/lignee.json
    sont visées ; sinon celles de l'index distant (dernières versions envoyées par le VPS)."""
    index = json.loads(_get(cfg, f"{PREFIXE}/index.json"))
    cibles: dict[str, dict] = {}
    voulus = set(etapes or [])
    if lignee_seule and LIGNEE.exists():
        for eid, e in json.loads(LIGNEE.read_text(encoding="utf-8")).get("etapes", {}).items():
            if not voulus or eid in voulus:
                cibles.update(e.get("fichiers", {}))
    else:
        prefixes = None
        if voulus:
            prefixes = [x["chemin"] for eid in voulus for x in entrees_etape(eid)]
        for c, info in index.get("fichiers", {}).items():
            if prefixes is None or any(c == p or c.startswith(p + "/") for p in prefixes):
                cibles[c] = info
    bilan = {"restaures": 0, "deja_presents": 0, "refuses": [], "absents_distants": [], "octets": 0}
    man_maj = {}
    for c, info in sorted(cibles.items()):
        if est_restreint(c) or not chemin_sur(c) or info.get("zone") == "restreinte":
            bilan["refuses"].append(c)
            continue
        p = ROOT / c
        if p.is_file() and p.stat().st_size == info["octets"] and sha256(p) == info["sha256"]:
            bilan["deja_presents"] += 1
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=p.parent, prefix=".restaure_", delete=False) as t:
                tmp = Path(t.name)
            try:
                _get(cfg, objet(info["sha256"]), tmp, nom=p.name)
            except (PermissionError, ConnectionError) as exc:
                tmp.unlink(missing_ok=True)
                bilan["absents_distants"].append(f"{c} : {exc}")
                continue
            if sha256(tmp) != info["sha256"]:
                tmp.unlink()
                bilan["absents_distants"].append(f"{c} : empreinte différente après téléchargement")
                continue
            os.replace(tmp, p)
            bilan["restaures"] += 1
            bilan["octets"] += info["octets"]
        if info.get("source") and info.get("collecte_le"):
            man_maj.setdefault(info["source"], {"collecte_le": info["collecte_le"], "domaine": info.get("domaine"),
                                                "fichiers": []})["fichiers"].append(
                {"chemin": c, "sha256": info["sha256"], "octets": info["octets"], "url": info.get("url"),
                 "origine": "pipeline/entrepot_distant.py restaurer"})
    if man_maj:
        ecrire_manifeste(man_maj)
    return bilan


def ecrire_manifeste(maj: dict) -> None:
    import fcntl
    LAKE.mkdir(parents=True, exist_ok=True)
    with open(LAKE / "manifest.json.lock", "w") as verrou:
        fcntl.flock(verrou, fcntl.LOCK_EX)
        man = _manifeste()
        for sid, m in maj.items():
            e = man.setdefault(sid, {"statut": "ok", "fichiers": [], "zone": "publique"})
            e["collecte_le"] = m["collecte_le"]
            if m.get("domaine") and not e.get("domaine"):
                e["domaine"] = m["domaine"]
            chemins = {f["chemin"] for f in m["fichiers"]}
            e["fichiers"] = [f for f in e.get("fichiers", []) if f.get("chemin") not in chemins] + m["fichiers"]
        tmp = MANIFESTE.with_name("manifest.json.tmp")
        tmp.write_text(json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, MANIFESTE)


# --- Écriture (VPS) : réutilise collecte/stockage.py --------------------------------------------------------------

def index_local(etapes: list[str] | None = None) -> dict:
    """Index des entrées présentes en local, zone publique seulement."""
    entrees = charger_entrees()
    man = _manifeste()
    proprio = _proprietaires(man)
    fichiers = {}
    for eid in etapes or list(entrees["etapes"]):
        for x in entrees_etape(eid, entrees):
            for f in _fichiers_sous(x["chemin"]):
                if est_restreint(f) or not chemin_sur(f):
                    continue
                sid = x["source"] or proprio.get(f)
                ent = man.get(sid) or {} if sid else {}
                fichiers[f] = {"sha256": sha256(ROOT / f), "octets": (ROOT / f).stat().st_size, "source": sid,
                               "domaine": ent.get("domaine"), "collecte_le": ent.get("collecte_le"),
                               "url": entrees.get("urls", {}).get(f), "zone": "publique"}
    return {"note": "Entrées du pipeline rangées telles quelles, adressées par sha256 (_entrees/objets/). "
                    "Zone restreinte exclue.", "fichiers": dict(sorted(fichiers.items()))}


def envoyer(essai: bool = False) -> int:
    sys.path.insert(0, str(ROOT / "collecte"))
    from stockage import Config, Rclone   # rclone, sommes de contrôle, reprises (collecte/stockage.py)
    cfg = Config.depuis_env()
    index = index_local()
    t = Rclone(cfg)
    envoyes = 0
    for c, info in index["fichiers"].items():
        cle = f"{cfg.bucket_public}/{objet(info['sha256'])}"
        if t.info(cle) is not None:
            continue
        if essai:
            print(f"enverrait {c} ({info['octets']} octets)")
        else:
            t.envoyer(ROOT / c, cle)
        envoyes += 1
    if not essai:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "index.json"
            p.write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            t.envoyer(p, f"{cfg.bucket_public}/{PREFIXE}/index.json")
            jour = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
            t.envoyer(p, f"{cfg.bucket_public}/{PREFIXE}/historique/index-{jour}.json")
    print(f"entrées : {len(index['fichiers'])} fichiers indexés, {envoyes} objet(s) {'à envoyer' if essai else 'envoyés'}")
    return 0


# --- Reconstruction complète : tous les axes produits ? -----------------------------------------------------------

def verifier(journal: Path, hors_ci_restreint: bool = True) -> tuple[int, list[str]]:
    """Code 0 si chaque étape du passage est « produit » ; sinon CODE_INCOMPLET et la liste. Une étape dont une
    entrée est en zone restreinte peut rester « conserve » en CI (hors_ci_restreint) : elle est comptée à part."""
    j = json.loads(journal.read_text(encoding="utf-8"))
    entrees = charger_entrees()
    incompletes, hors_ci = [], []
    for x in j.get("etapes", []):
        if x.get("statut") == "produit":
            continue
        restreinte = any(est_restreint(d["chemin"]) for d in entrees_etape(x["etape"], entrees))
        ligne = f"{x['etape']} : {x.get('statut')} ({(x.get('motif') or '')[:200]})"
        (hors_ci if restreinte and hors_ci_restreint and x.get("statut") == "conserve" else incompletes).append(ligne)
    for l in hors_ci:
        print(f"hors CI (entrée en zone restreinte, régénérée sur le VPS seulement) : {l}")
    return (CODE_INCOMPLET if incompletes else 0), incompletes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("commande", choices=["diagnostic", "lignee", "restaurer", "envoyer", "verifier", "index"])
    ap.add_argument("--etapes")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--lignee", action="store_true", help="restaurer : versions de pipeline/lignee.json")
    ap.add_argument("--essai", action="store_true", help="envoyer : liste sans rien envoyer")
    ap.add_argument("--journal", default=str(LAKE / "_cache" / "tout" / "journal.json"))
    ap.add_argument("--date-sources", help="lignee : date injectée (AAAA-MM-JJTHH:MM:SSZ) pour les étapes données")
    ap.add_argument("--strict-restreint", action="store_true", help="verifier : la zone restreinte compte aussi")
    a = ap.parse_args(argv)
    ids = [s for s in (a.etapes or "").split(",") if s] or None
    if a.commande == "diagnostic":
        cfg = ConfigLecture()
        index = None
        if cfg.configuree:
            try:
                index = json.loads(_get(cfg, f"{PREFIXE}/index.json"))
            except (PermissionError, ConnectionError) as exc:
                print(f"index distant illisible ({cfg.mode}) : {exc}", file=sys.stderr)
        d = diagnostic(index)
        print(markdown(d) if a.markdown else json.dumps(d, ensure_ascii=False, indent=1))
        return 0
    if a.commande == "lignee":
        if not ids:
            raise SystemExit("--etapes requis (la lignée se relève étape par étape, après vérification)")
        lignee(ids, {i: a.date_sources for i in ids} if a.date_sources else None)
        print(f"{LIGNEE.relative_to(ROOT)} : {', '.join(ids)}")
        return 0
    if a.commande == "index":
        print(json.dumps(index_local(ids), ensure_ascii=False, indent=1))
        return 0
    if a.commande == "restaurer":
        cfg = ConfigLecture()
        if not cfg.configuree:
            print("entrepôt distant non configuré (OVMI_LAC_URL ou OVMI_LAC_ENDPOINT + OVMI_LAC_BUCKET) : "
                  "rien à restaurer, le cache GitHub et la recollecte restent seuls")
            return 0
        try:
            b = restaurer(cfg, ids, a.lignee)
        except (PermissionError, ConnectionError) as exc:
            print(f"::warning::entrepôt distant illisible ({cfg.mode}) : {exc}")
            return 0
        print(f"entrepôt distant ({cfg.mode}) : {b['restaures']} restauré(s) ({b['octets'] / 1e6:.1f} Mo), "
              f"{b['deja_presents']} déjà présent(s), {len(b['refuses'])} refusé(s) (zone restreinte ou chemin), "
              f"{len(b['absents_distants'])} absent(s) du bucket")
        for x in b["absents_distants"][:20]:
            print(f"  absent : {x}")
        return 0
    if a.commande == "envoyer":
        return envoyer(a.essai)
    code, incompletes = verifier(Path(a.journal), not a.strict_restreint)
    for l in incompletes:
        print(f"::error::axe incomplet : {l}")
    print("reconstruction complète : " + ("tous les axes produits" if code == 0 else
                                          f"{len(incompletes)} axe(s) incomplet(s), publication bloquée"))
    return code


if __name__ == "__main__":
    sys.exit(main())
