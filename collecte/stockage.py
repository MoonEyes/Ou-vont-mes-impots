"""Stockage objet de l'entrepot brut (OVH Object Storage, S3 compatible) : la colle entre
collecte.py (telechargement), conversion.py (Parquet zstd via DuckDB) et rclone (transfert).

Mode flux, source par source : collecter -> convertir -> envoyer (rclone) -> verifier (somme de
controle) -> effacer en local. Le manifeste (data/lake/manifest.json) garde par fichier l'empreinte
sha256 du fichier brut, les URL objet (s3://bucket/domaine/source/AAAA-MM-JJ/fichier) et les tailles
avant et apres conversion.

- Pas de doublon : si le sha256 du fichier brut est celui de la version deja stockee, rien n'est
  renvoye (seule la date de verification change).
- Historique : une nouvelle version (nouveau dossier date) n'est creee que si le contenu change.
- Reprise : un envoi en echec laisse le fichier brut en local, marque `envoi_en_attente` ; il est
  renvoye au passage suivant.
- Donnees de personnes physiques (zone restreinte, data/lake/_restreint/) : bucket (ou prefixe)
  prive uniquement, jamais le bucket public. Sans bucket prive configure, elles restent en local.
- Le manifeste est sauvegarde dans le bucket apres chaque lot (complet dans le prive, filtre sans
  la zone restreinte dans le public).

Configuration par variables d'environnement uniquement (voir deploy/env.exemple) :
  OVMI_REMOTE            nom du remote rclone (defaut : ovh), configure par RCLONE_CONFIG_<REMOTE>_*
                         ou par un fichier designe par RCLONE_CONFIG
  OVMI_BUCKET_PUBLIC     bucket (ou bucket/prefixe) des donnees publiques
  OVMI_BUCKET_PRIVE      bucket (ou bucket/prefixe) des donnees de personnes physiques
  OVMI_BWLIMIT           limite de bande passante rclone (ex. 8M, "08:00,4M 23:00,off")
  OVMI_RCLONE            binaire rclone (defaut : rclone)

Usage :
  python collecte/stockage.py config                       # verifie la configuration (sans secret affiche)
  python collecte/stockage.py flux [options collecte.py]    # = collecte.py --flux ...
  python collecte/stockage.py migrer [--domaine D] [--limite N] [--garder-local] [--essai]
  python collecte/stockage.py sauver-manifeste | restaurer-manifeste [--force]
  python collecte/stockage.py restaurer SOURCE [--date AAAA-MM-JJ] [--dest DOSSIER]
  python collecte/stockage.py requete deploy/requete_exemple.sql
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import string
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ICI = Path(__file__).resolve().parent
if str(ICI) not in sys.path:
    sys.path.insert(0, str(ICI))

import collecte as C  # noqa: E402
import conversion  # noqa: E402

DOSSIER_MANIFESTE = "_manifeste"
LOT_MANIFESTE = 25  # sauvegarde distante du manifeste toutes les N sources (et en fin de lot)


class ErreurConfig(RuntimeError):
    pass


class ErreurEnvoi(RuntimeError):
    pass


def aujourdhui() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- configuration

@dataclass
class Config:
    remote: str
    bucket_public: str
    bucket_prive: str | None = None
    rclone: str = "rclone"
    bwlimit: str | None = None
    options: list[str] = field(default_factory=list)

    @classmethod
    def depuis_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        pub = (env.get("OVMI_BUCKET_PUBLIC") or "").strip().rstrip("/")
        prive = (env.get("OVMI_BUCKET_PRIVE") or "").strip().rstrip("/") or None
        if not pub:
            raise ErreurConfig("OVMI_BUCKET_PUBLIC non defini (voir deploy/env.exemple)")
        if prive and (prive == pub or pub.startswith(prive + "/")):
            raise ErreurConfig("OVMI_BUCKET_PRIVE doit etre distinct du bucket public et ne pas le contenir")
        return cls(remote=(env.get("OVMI_REMOTE") or "ovh").strip(), bucket_public=pub, bucket_prive=prive,
                   rclone=env.get("OVMI_RCLONE") or "rclone", bwlimit=(env.get("OVMI_BWLIMIT") or "").strip() or None,
                   options=(env.get("OVMI_RCLONE_OPTIONS") or "").split())

    def bucket(self, prive: bool) -> str:
        if not prive:
            return self.bucket_public
        if not self.bucket_prive:
            raise ErreurConfig("donnees de personnes physiques et OVMI_BUCKET_PRIVE non defini : envoi refuse")
        return self.bucket_prive


def url_objet(bucket: str, cle: str) -> str:
    return f"s3://{bucket}/{cle}"


def decouper_url(url: str) -> str:
    """s3://bucket/cle -> bucket/cle (chemin rclone apres le remote)."""
    return url.split("://", 1)[1] if "://" in url else url


# ---------------------------------------------------------------- transfert (rclone)

def md5_fichier(chemin: Path) -> str:
    h = hashlib.md5()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


class Rclone:
    """Transfert par rclone : reprises integrees, verification par somme de controle (MD5 calcule
    en local, compare a celui que rendent le remote ou les metadonnees S3), bande passante limitee."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        if not shutil.which(cfg.rclone):
            raise ErreurConfig(f"rclone introuvable ({cfg.rclone}) : voir deploy/installer_vps.sh")

    def _cmd(self, *args: str) -> list[str]:
        cmd = [self.cfg.rclone, *args, "--retries", "5", "--low-level-retries", "20", "--retries-sleep", "10s",
               "--stats", "0"]
        if self.cfg.bwlimit:
            cmd += ["--bwlimit", self.cfg.bwlimit]
        return cmd + self.cfg.options

    def _run(self, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
        p = subprocess.run(self._cmd(*args), capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise ErreurEnvoi(f"rclone {args[0]} : code {p.returncode} : {p.stderr.strip()[-400:]}")
        return p

    def _chemin(self, distant: str) -> str:
        return f"{self.cfg.remote}:{distant}"

    def envoyer(self, local: Path, distant: str) -> dict:
        """Envoie local vers remote:distant puis verifie. Renvoie {"octets", "md5", "verification"}."""
        md5 = md5_fichier(local)
        taille = local.stat().st_size
        self._run("copyto", str(local), self._chemin(distant), "--checksum")
        info = self.info(distant)
        if info is None:
            raise ErreurEnvoi(f"objet absent apres envoi : {distant}")
        if int(info.get("Size", -1)) != taille:
            raise ErreurEnvoi(f"taille distante {info.get('Size')} != {taille} pour {distant}")
        distant_md5 = (info.get("Hashes") or {}).get("md5") or (info.get("Hashes") or {}).get("MD5")
        if distant_md5 and distant_md5.lower() != md5:
            raise ErreurEnvoi(f"somme de controle differente pour {distant}")
        return {"octets": taille, "md5": md5, "verification": "md5" if distant_md5 else "taille"}

    def info(self, distant: str) -> dict | None:
        p = subprocess.run(self._cmd("lsjson", "--stat", "--hash", "--hash-type", "md5", self._chemin(distant)),
                           capture_output=True, text=True)
        if p.returncode != 0:
            return None
        return json.loads(p.stdout or "null")

    def supprimer(self, distant: str):
        subprocess.run(self._cmd("deletefile", self._chemin(distant)), capture_output=True, text=True)

    def recuperer(self, distant: str, local: Path):
        local.parent.mkdir(parents=True, exist_ok=True)
        self._run("copyto", self._chemin(distant), str(local), "--checksum")


# ---------------------------------------------------------------- traitement d'une source

def est_restreint(entree: dict, f: dict | None = None) -> bool:
    if entree.get("zone") == "restreinte" or entree.get("personnes_physiques"):
        return True
    chemin = (f or {}).get("chemin", "")
    return "/_restreint/" in f"/{chemin}"


def dossier_travail() -> Path:
    return C.LAKE / "_envoi"


@dataclass
class Flux:
    cfg: Config
    transfert: object
    garder_local: bool = False
    echecs: int = 0
    envoyes: int = 0
    dedupliques: int = 0
    octets_avant: int = 0
    octets_apres: int = 0
    _depuis_sauvegarde: int = 0

    @classmethod
    def depuis_env(cls, transfert=None, env=None, **kw) -> "Flux":
        cfg = Config.depuis_env(env)
        return cls(cfg, transfert or Rclone(cfg), **kw)

    # -- un fichier
    def _traiter_fichier(self, sid: str, entree: dict, f: dict, vieux: dict | None, date: str) -> str:
        local = C.ROOT / f["chemin"]
        prec = (vieux or {}).get("stockage") or f.get("stockage")
        restreint = est_restreint(entree, f)
        if prec and prec.get("sha256_brut") == f.get("sha256") and not f.get("envoi_en_attente"):
            f["stockage"] = {**prec, "verifie_le": C.maintenant()}
            f["objet"] = prec["objets"][0]["url"] if prec.get("objets") else f.get("objet")
            f.pop("erreur_envoi", None)
            if local.exists() and not self.garder_local:
                local.unlink()
            self.dedupliques += 1
            return "inchange"
        if not local.exists():
            if prec:
                f["stockage"] = prec
                f["objet"] = prec["objets"][0]["url"]
                return "inchange"
            f["erreur_envoi"] = "fichier local absent et aucune version stockee"
            return "echec"
        try:
            bucket = self.cfg.bucket(restreint)
        except ErreurConfig as exc:
            f["envoi_en_attente"] = True
            f["erreur_envoi"] = str(exc)
            if prec:
                f["stockage"] = prec
            return "echec"
        if restreint and bucket == self.cfg.bucket_public:  # garde-fou, ne doit jamais arriver
            raise ErreurConfig("tentative d'envoi de donnees restreintes dans le bucket public")
        versions = list((prec or {}).get("versions", []))
        dossier_date = date
        if any(v.get("date_version") == date and v.get("sha256_brut") != f.get("sha256") for v in versions):
            dossier_date = f"{date}-{(f.get('sha256') or '')[:8]}"  # deux versions le meme jour
        travail = dossier_travail() / sid
        res = conversion.convertir(local, travail)
        envoyes: list[dict] = []
        try:
            for s in res.sorties:
                cle = f"{entree.get('domaine') or 'divers'}/{sid}/{dossier_date}/{s.nom}"
                info = self.transfert.envoyer(s.chemin, f"{bucket}/{cle}")
                envoyes.append({"url": url_objet(bucket, cle), "nom": s.nom, "octets": info["octets"],
                                "md5": info["md5"], "converti": s.converti, "lignes": s.lignes,
                                "verification": info.get("verification", "md5")})
        except Exception as exc:
            for o in envoyes:  # pas d'objet orphelin d'une version incomplete
                try:
                    self.transfert.supprimer(decouper_url(o["url"]))
                except Exception:
                    pass
            conversion.nettoyer_resultat(res)
            shutil.rmtree(travail, ignore_errors=True)
            f["envoi_en_attente"] = True
            f["erreur_envoi"] = f"{type(exc).__name__}: {exc}"[:400]
            if prec:
                f["stockage"] = prec
            return "echec"
        maintenant = C.maintenant()
        resume = res.resume()
        stock = {"sha256_brut": f.get("sha256"), "date_version": dossier_date, "zone": "privee" if restreint else "publique",
                 "format": resume["format"], "converti": resume["converti"],
                 "octets_avant": res.octets_avant, "octets_apres": sum(o["octets"] for o in envoyes),
                 "objets": envoyes, "envoye_le": maintenant, "verifie_le": maintenant}
        if resume.get("conversion_erreurs"):
            stock["conversion_erreurs"] = resume["conversion_erreurs"]
        versions.append({"date_version": dossier_date, "sha256_brut": f.get("sha256"),
                         "octets_apres": stock["octets_apres"], "objets": [o["url"] for o in envoyes]})
        stock["versions"] = versions
        f["stockage"] = stock
        f["objet"] = envoyes[0]["url"]
        f.pop("envoi_en_attente", None)
        f.pop("erreur_envoi", None)
        conversion.nettoyer_resultat(res)
        shutil.rmtree(travail, ignore_errors=True)
        if not self.garder_local:
            local.unlink(missing_ok=True)
        self.octets_avant += res.octets_avant
        self.octets_apres += stock["octets_apres"]
        self.envoyes += 1
        return "envoye"

    def traiter_source(self, sid: str, entree: dict, ancien: dict | None = None, date: str | None = None) -> dict:
        """Envoie les fichiers d'une entree de manifeste (mutee et renvoyee)."""
        date = date or aujourdhui()
        anciens = {f["chemin"]: f for f in (ancien or {}).get("fichiers", [])}
        etats = []
        for f in entree.get("fichiers", []):
            if not f.get("chemin") or not f.get("sha256"):
                continue
            vieux = anciens.get(f["chemin"])
            if f.get("donnees_anterieures") and (vieux or f).get("stockage"):
                f["stockage"] = (vieux or f)["stockage"]
                continue
            try:
                etats.append(self._traiter_fichier(sid, entree, f, vieux, date))
            except ErreurConfig:
                raise
            except Exception as exc:  # conversion ou disque : le fichier brut reste en local
                f["envoi_en_attente"] = True
                f["erreur_envoi"] = f"{type(exc).__name__}: {exc}"[:400]
                etats.append("echec")
        if etats:
            entree["stockage_statut"] = ("echec" if all(e == "echec" for e in etats)
                                         else "partiel" if "echec" in etats else "ok")
            self.echecs += etats.count("echec")
        return entree

    def apres_collecte(self, sid: str, entree: dict, ancien: dict | None) -> dict:
        """Branchement de collecte.py --flux, appele apres collecter() et avant l'ecriture du manifeste."""
        e = self.traiter_source(sid, entree, ancien)
        self._depuis_sauvegarde += 1
        return e

    def peut_etre_sauver(self, force: bool = False):
        if force or self._depuis_sauvegarde >= LOT_MANIFESTE:
            sauver_manifeste(self)
            self._depuis_sauvegarde = 0


# ---------------------------------------------------------------- manifeste distant

def manifeste_public(m: dict) -> dict:
    """Copie du manifeste sans aucune entree de la zone restreinte."""
    return {sid: e for sid, e in m.items()
            if not est_restreint(e) and not any(est_restreint(e, f) for f in e.get("fichiers", []))}


def sauver_manifeste(flux: Flux, chemin: Path | None = None):
    chemin = chemin or C.MANIFEST
    if not chemin.exists():
        return
    m = C.lire_manifeste(chemin)
    travail = dossier_travail()
    travail.mkdir(parents=True, exist_ok=True)
    horodate = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    pub = travail / "manifest.public.json"
    pub.write_text(json.dumps(manifeste_public(m), ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    try:
        flux.transfert.envoyer(pub, f"{flux.cfg.bucket_public}/{DOSSIER_MANIFESTE}/manifest.json")
        if flux.cfg.bucket_prive:
            complet = travail / "manifest.json.gz"
            complet.write_bytes(gzip.compress(chemin.read_bytes(), 6, mtime=0))
            flux.transfert.envoyer(chemin, f"{flux.cfg.bucket_prive}/{DOSSIER_MANIFESTE}/manifest.json")
            flux.transfert.envoyer(complet, f"{flux.cfg.bucket_prive}/{DOSSIER_MANIFESTE}/historique/manifest-{horodate}.json.gz")
            complet.unlink(missing_ok=True)
    finally:
        pub.unlink(missing_ok=True)


def restaurer_manifeste(flux: Flux, force: bool = False, chemin: Path | None = None) -> bool:
    """Recupere le manifeste distant (prive s'il existe, sinon public) si absent en local."""
    chemin = chemin or C.MANIFEST
    if chemin.exists() and not force:
        return False
    bucket = flux.cfg.bucket_prive or flux.cfg.bucket_public
    distant = f"{bucket}/{DOSSIER_MANIFESTE}/manifest.json"
    if flux.transfert.info(distant) is None:
        return False
    tmp = chemin.with_name(chemin.name + ".distant")
    flux.transfert.recuperer(distant, tmp)
    json.loads(tmp.read_text(encoding="utf-8"))  # doit etre un JSON valide avant de remplacer
    os.replace(tmp, chemin)
    return True


# ---------------------------------------------------------------- migration de l'entrepot local

def migrer(flux: Flux, *, domaine: str | None = None, ids: list[str] | None = None, limite: int | None = None,
           essai: bool = False, journal=print) -> dict:
    """Envoie l'entrepot local existant (meme logique que le flux), source par source. La date de
    version est la date de collecte de la source. Reprise : relancer la commande, les fichiers deja
    stockes (meme sha256) sont sautes."""
    m = C.lire_manifeste()
    total = {"sources": 0, "fichiers": 0, "octets": 0}
    for sid in sorted(m):
        e = m[sid]
        if (ids and sid not in ids) or (domaine and e.get("domaine") != domaine):
            continue
        a_faire = [f for f in e.get("fichiers", []) if f.get("sha256") and (C.ROOT / f["chemin"]).exists()
                   and not (flux.garder_local and not f.get("envoi_en_attente")
                            and (f.get("stockage") or {}).get("sha256_brut") == f.get("sha256"))]
        if not a_faire:
            continue
        if limite is not None and total["sources"] >= limite:
            break
        total["sources"] += 1
        total["fichiers"] += len(a_faire)
        total["octets"] += sum((C.ROOT / f["chemin"]).stat().st_size for f in a_faire)
        if essai:
            journal(f"ESSAI    {sid:<60} {len(a_faire)} fichier(s) {'(prive)' if est_restreint(e) else ''}")
            continue
        avant = flux.echecs
        date = (e.get("collecte_le") or C.maintenant())[:10]
        e = flux.traiter_source(sid, e, ancien=e, date=date)
        C.maj_manifeste(sid, e)
        journal(f"{'ECHEC' if flux.echecs > avant else 'OK':<8} {sid:<60} {e.get('stockage_statut', '')}")
        flux._depuis_sauvegarde += 1
        flux.peut_etre_sauver()
    if not essai and total["sources"]:
        flux.peut_etre_sauver(force=True)
    return total


# ---------------------------------------------------------------- restauration

def restaurer_source(flux: Flux, sid: str, dest: Path, date: str | None = None) -> list[Path]:
    """Recupere les objets d'une source (version courante ou celle d'une date) dans dest/domaine/source/."""
    e = C.lire_manifeste().get(sid)
    if not e:
        raise SystemExit(f"source inconnue du manifeste : {sid}")
    sortis = []
    for f in e.get("fichiers", []):
        st = f.get("stockage")
        if not st:
            continue
        urls = [o["url"] for o in st.get("objets", [])]
        if date:
            urls = next((v["objets"] for v in st.get("versions", []) if v["date_version"].startswith(date)), [])
        for url in urls:
            rel = url.split(f"/{sid}/", 1)[1].split("/", 1)[1]
            cible = dest / (e.get("domaine") or "divers") / sid / rel
            flux.transfert.recuperer(decouper_url(url), cible)
            sortis.append(cible)
    return sortis


# ---------------------------------------------------------------- interrogation (DuckDB sur S3)

def identifiants_s3(env=None, cfg: Config | None = None) -> dict:
    """Cles et point d'acces du remote rclone : variables RCLONE_CONFIG_<REMOTE>_* sinon
    `rclone config dump` (fichier RCLONE_CONFIG). Rien n'est ecrit sur disque."""
    env = os.environ if env is None else env
    remote = (cfg.remote if cfg else env.get("OVMI_REMOTE") or "ovh")
    pre = f"RCLONE_CONFIG_{remote.upper().replace('-', '_')}_"
    d = {k[len(pre):].lower(): v for k, v in env.items() if k.startswith(pre)}
    if not d.get("access_key_id"):
        try:
            dump = json.loads(subprocess.run([(cfg.rclone if cfg else env.get("OVMI_RCLONE") or "rclone"),
                                              "config", "dump"], capture_output=True, text=True, check=True).stdout)
            d = {k.lower(): v for k, v in dump.get(remote, {}).items()}
        except (OSError, subprocess.CalledProcessError, ValueError):
            pass
    if not d.get("access_key_id"):
        raise ErreurConfig(f"identifiants S3 introuvables pour le remote {remote}")
    region = d.get("region") or "gra"
    endpoint = (d.get("endpoint") or f"s3.{region}.io.cloud.ovh.net").replace("https://", "").replace("http://", "")
    return {"key_id": d["access_key_id"], "secret": d.get("secret_access_key", ""), "region": region,
            "endpoint": endpoint.rstrip("/")}


def session_duckdb(env=None, memoire: str | None = None, threads: int | None = None):
    """Session DuckDB qui lit directement les Parquet du stockage objet :
        con = session_duckdb()
        con.sql("SELECT count(*) FROM read_parquet('s3://mon-bucket/etat/*/*/*.parquet')")
    Necessite l'extension httpfs (installee par deploy/installer_vps.sh)."""
    s = identifiants_s3(env)
    con = conversion.connexion(memoire, threads)
    con.execute("LOAD httpfs") if _extension_installee(con, "httpfs") else con.execute("INSTALL httpfs; LOAD httpfs")
    q = conversion._sql
    con.execute(f"CREATE OR REPLACE SECRET ovmi_s3 (TYPE s3, KEY_ID '{q(s['key_id'])}', SECRET '{q(s['secret'])}', "
                f"REGION '{q(s['region'])}', ENDPOINT '{q(s['endpoint'])}', URL_STYLE 'path')")
    return con


def _extension_installee(con, nom: str) -> bool:
    return bool(con.execute("SELECT installed FROM duckdb_extensions() WHERE extension_name = ?", [nom]).fetchone()[0])


def executer_requete(fichier: Path, env=None):
    env = os.environ if env is None else env
    sql = string.Template(fichier.read_text(encoding="utf-8")).safe_substitute(env)
    con = session_duckdb(env)
    for instruction in (i.strip() for i in sql.split(";\n")):
        if not instruction or all(l.strip().startswith("--") or not l.strip() for l in instruction.splitlines()):
            continue
        rel = con.sql(instruction)
        if rel is not None:
            rel.show(max_rows=50)


# ---------------------------------------------------------------- ligne de commande

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "flux":
        return C.main(["--flux", *argv[1:]])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("config")
    mg = sp.add_parser("migrer")
    mg.add_argument("ids", nargs="*")
    mg.add_argument("--domaine")
    mg.add_argument("--limite", type=int)
    mg.add_argument("--garder-local", action="store_true", help="ne pas effacer les fichiers locaux apres envoi")
    mg.add_argument("--essai", action="store_true", help="liste ce qui serait envoye, sans rien envoyer")
    sp.add_parser("sauver-manifeste")
    rm = sp.add_parser("restaurer-manifeste")
    rm.add_argument("--force", action="store_true")
    rs = sp.add_parser("restaurer")
    rs.add_argument("source")
    rs.add_argument("--date")
    rs.add_argument("--dest", type=Path, default=C.ROOT / "data" / "restauration")
    rq = sp.add_parser("requete")
    rq.add_argument("fichier", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "requete":
            executer_requete(a.fichier)
            return 0
        flux = Flux.depuis_env(garder_local=getattr(a, "garder_local", False))
        if a.cmd == "config":
            cfg = flux.cfg
            print(f"remote {cfg.remote} ; public {cfg.bucket_public} ; prive {cfg.bucket_prive or 'NON CONFIGURE'} ; "
                  f"bande passante {cfg.bwlimit or 'illimitee'}")
            for b in filter(None, [cfg.bucket_public, cfg.bucket_prive]):
                p = subprocess.run(flux.transfert._cmd("lsf", "--max-depth", "1", f"{cfg.remote}:{b}"),
                                   capture_output=True, text=True)
                print(f"  {b} : {'accessible' if p.returncode == 0 else 'INACCESSIBLE ' + p.stderr.strip()[-200:]}")
            return 0
        if a.cmd == "migrer":
            debut = time.time()
            if not a.essai:
                restaurer_manifeste(flux)
            t = migrer(flux, domaine=a.domaine, ids=a.ids or None, limite=a.limite, essai=a.essai)
            gain = f", {flux.octets_avant / 1e9:.2f} Go -> {flux.octets_apres / 1e9:.2f} Go" if flux.octets_avant else ""
            print(f"\n{t['sources']} sources, {t['fichiers']} fichiers, {t['octets'] / 1e9:.2f} Go locaux ; "
                  f"envoyes {flux.envoyes}, inchanges {flux.dedupliques}, echecs {flux.echecs}{gain} "
                  f"({time.time() - debut:.0f} s)")
            return 2 if flux.echecs else 0
        if a.cmd == "sauver-manifeste":
            sauver_manifeste(flux)
            return 0
        if a.cmd == "restaurer-manifeste":
            print("manifeste restaure" if restaurer_manifeste(flux, a.force) else "rien a restaurer")
            return 0
        if a.cmd == "restaurer":
            for p in restaurer_source(flux, a.source, a.dest, a.date):
                print(p)
            return 0
    except ErreurConfig as exc:
        print(f"CONFIGURATION : {exc}", file=sys.stderr)
        return 78
    return 1


if __name__ == "__main__":
    sys.exit(main())
