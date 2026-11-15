"""Collecteur generique : remplit l'entrepot brut data/lake/ a partir de collecte/catalogue.json.

Principe : tout prendre tel que publie, sans transformation, et tracer chaque fichier
(URL, date, empreinte sha256, taille, lignes, colonnes, licence) dans data/lake/manifest.json.
Une source en erreur n'arrete pas les autres : l'erreur est notee dans le manifeste.

Usage :
  python collecte/collecte.py                  # toutes les sources non lourdes
  python collecte/collecte.py --lourd          # y compris les sources lourdes (> 100 Mo)
  python collecte/collecte.py --domaine etat   # un domaine
  python collecte/collecte.py id1 id2          # des sources precises
  python collecte/collecte.py --liste          # affiche le catalogue
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
MANIFEST = LAKE / "manifest.json"
CATALOGUE = json.loads((Path(__file__).parent / "catalogue.json").read_text(encoding="utf-8"))
PORTAILS = CATALOGUE["portails"]
HEADERS = {"User-Agent": "ou-vont-mes-impots-collecte/0.2 (projet citoyen open source)"}


def requete(url: str, stream: bool = False, tries: int = 6, timeout: int = 300) -> requests.Response:
    erreur = None
    for tentative in range(1, tries + 1):
        try:
            r = requests.get(url, headers=HEADERS, stream=stream, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            erreur = exc
        else:
            if r.status_code < 400:
                return r
            if r.status_code != 429 and r.status_code < 500:
                raise RuntimeError(f"HTTP {r.status_code} sur {url} : {r.text[:200]}")
            erreur = f"HTTP {r.status_code}"
        if tentative < tries:
            time.sleep(min(2 ** tentative, 60))
    raise RuntimeError(f"{url} injoignable apres {tries} tentatives : {erreur}")


def telecharger(url: str, cible: Path) -> dict:
    """Telechargement en flux vers un fichier temporaire, puis renommage atomique."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_suffix(cible.suffix + ".part")
    h, n = hashlib.sha256(), 0
    for tentative in range(1, 4):
        try:
            with requete(url, stream=True) as r, tmp.open("wb") as f:
                for bloc in r.iter_content(1 << 20):
                    f.write(bloc)
                    h.update(bloc)
                    n += len(bloc)
            break
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError):
            h, n = hashlib.sha256(), 0  # coupure en cours de transfert : on recommence
            if tentative == 3:
                raise
            time.sleep(5 * tentative)
    if n == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("fichier vide")
    tmp.replace(cible)
    return {"octets": n, "sha256": h.hexdigest()}


def decrire_parquet(chemin: Path) -> dict:
    try:
        import pyarrow.parquet as pq
        meta = pq.ParquetFile(chemin)
        return {"lignes": meta.metadata.num_rows, "colonnes": meta.schema_arrow.names}
    except Exception as exc:  # fichier non parquet ou illisible : on le garde quand meme
        return {"lecture": f"illisible en parquet : {exc}"[:200]}


def urls_source(src: dict) -> list[tuple[str, str]]:
    """Renvoie [(url, nom_de_fichier)] a telecharger pour une entree du catalogue."""
    t = src["type"]
    if t == "ods_export":
        base = PORTAILS[src["portail"]]
        params = {k: src[k] for k in ("where", "select") if src.get(k)}
        q = f"?{urlencode(params)}" if params else ""
        return [(f"{base}/api/explore/v2.1/catalog/datasets/{src['dataset']}/exports/parquet{q}", f"{src['id']}.parquet")]
    if t == "ods_pieces_jointes":
        base = PORTAILS[src["portail"]]
        liste = requete(f"{base}/api/explore/v2.1/catalog/datasets/{src['dataset']}/attachments").json()
        pj = liste.get("attachments", liste if isinstance(liste, list) else [])
        sorties = []
        for a in pj:
            nom = a.get("metas", {}).get("title") or a.get("id")
            url = a.get("href") or f"{base}/api/explore/v2.1/catalog/datasets/{src['dataset']}/attachments/{a['id']}"
            ext = Path(a.get("metas", {}).get("url", "") or nom).suffix or ".bin"
            sorties.append((url, f"{src['id']}/{a.get('id', nom)}{ext if not str(a.get('id','')).endswith(ext) else ''}"))
        if not sorties:
            raise RuntimeError("aucune piece jointe")
        return sorties
    if t == "datagouv":
        ds = requete(f"https://www.data.gouv.fr/api/1/datasets/{src['dataset']}/").json()
        ressources = [r for r in ds["resources"]
                      if (not src.get("format") or (r.get("format") or "").lower() == src["format"].lower())
                      and (not src.get("titre_contient") or src["titre_contient"].lower() in (r.get("title") or "").lower())]
        if not ressources:
            raise RuntimeError("aucune ressource correspondante")
        if not src.get("toutes"):
            ressources = ressources[:1]
        return [(r["url"], f"{src['id']}/{Path(r.get('title') or r['id']).stem}.{(r.get('format') or 'bin').lower()}")
                for r in ressources]
    if t == "eurostat":
        params = urlencode(src.get("params", {}), doseq=True)
        return [(f"{PORTAILS['eurostat']}/{src['dataset']}?{params}", f"{src['id']}.json")]
    if t == "url":
        return [(src["url"], f"{src['id']}.{src.get('format', 'bin')}")]
    raise RuntimeError(f"type inconnu : {t}")


def collecter(src: dict, ancien: dict) -> dict:
    debut = time.time()
    entree = {"titre": src["titre"], "domaine": src["domaine"], "licence": src.get("licence"),
              "personnes_physiques": src.get("personnes_physiques", False),
              "collecte_le": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fichiers": []}
    try:
        for url, nom in urls_source(src):
            cible = LAKE / src["domaine"] / nom
            info = {"url": url, "chemin": str(cible.relative_to(ROOT)), **telecharger(url, cible)}
            if cible.suffix == ".parquet":
                info.update(decrire_parquet(cible))
            precedent = {f["chemin"]: f.get("sha256") for f in ancien.get("fichiers", [])}
            info["change"] = precedent.get(info["chemin"]) != info["sha256"]
            entree["fichiers"].append(info)
        entree["statut"] = "ok"
    except Exception as exc:
        entree["statut"] = "erreur"
        entree["erreur"] = str(exc)[:500]
    entree["duree_s"] = round(time.time() - debut, 1)
    return entree


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--lourd", action="store_true")
    ap.add_argument("--domaine")
    ap.add_argument("--liste", action="store_true")
    a = ap.parse_args()

    sources = CATALOGUE["sources"]
    if a.liste:
        for s in sources:
            print(f"{s['domaine']:<14} {s['id']:<40} {'LOURD ' if s.get('lourd') else ''}{s['titre']}")
        return 0
    choix = [s for s in sources
             if (not a.ids or s["id"] in a.ids)
             and (not a.domaine or s["domaine"] == a.domaine)
             and (a.lourd or a.ids or not s.get("lourd"))]
    manifeste = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    erreurs = 0
    for s in choix:
        e = collecter(s, manifeste.get(s["id"], {}))
        manifeste[s["id"]] = e
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(manifeste, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        if e["statut"] == "ok":
            mo = sum(f["octets"] for f in e["fichiers"]) / 1e6
            lignes = sum(f.get("lignes", 0) for f in e["fichiers"])
            print(f"OK      {s['id']:<40} {mo:9.1f} Mo {lignes:>11,} lignes  {e['duree_s']}s")
        else:
            erreurs += 1
            print(f"ERREUR  {s['id']:<40} {e['erreur'][:120]}")
    print(f"\n{len(choix) - erreurs}/{len(choix)} sources collectees, manifeste : {MANIFEST.relative_to(ROOT)}")
    return 1 if choix and erreurs == len(choix) else 0


if __name__ == "__main__":
    sys.exit(main())
