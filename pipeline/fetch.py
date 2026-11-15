"""Telecharge les donnees brutes (pattern git scraping).

Chaque source est ecrite dans data/raw/<id>.json, avec son schema declare
dans data/raw/<id>.schema.json (sert a detecter les changements de schema).
Aucune ecriture si le telechargement echoue : le job s'arrete en erreur.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CONFIG = json.loads((Path(__file__).parent / "sources.json").read_text(encoding="utf-8"))
HEADERS = {"User-Agent": "ou-vont-mes-impots/0.1 (projet citoyen open source)"}


def get(url: str, params: dict | None = None, tries: int = 6) -> requests.Response:
    """GET avec reprises exponentielles (les API publiques coupent parfois)."""
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=120)
        except (requests.ConnectionError, requests.Timeout) as exc:
            error = exc
        else:
            if r.status_code < 400:
                return r
            if r.status_code != 429 and r.status_code < 500:
                # Erreur client (requete invalide) : inutile de reessayer.
                raise SystemExit(f"{url} -> HTTP {r.status_code} : {r.text[:300]}")
            error = f"HTTP {r.status_code}"
        if attempt < tries:
            wait = 2 ** attempt
            print(f"  tentative {attempt} echouee ({error}), nouvel essai dans {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise SystemExit(f"{url} injoignable apres {tries} tentatives : {error}")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Tri des cles et indentation : diffs git lisibles et stables.
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def fetch_ods(src: dict) -> None:
    base = f"{CONFIG['ods_base']}/{src['dataset']}"
    meta = get(base).json()
    fields = {f["name"]: f["type"] for f in meta["fields"]}
    wanted = [f.strip("`") for f in src["select"].split(",")]
    missing = [f for f in wanted if f not in fields]
    if missing:
        raise SystemExit(f"[{src['id']}] champs disparus a la source : {missing}")

    where = src.get("where")
    if src.get("latest_of"):
        col = src["latest_of"]
        groups = get(f"{base}/records", {"select": col, "group_by": col, "order_by": f"{col} desc", "limit": 1}).json()
        latest = groups["results"][0][col]
        where = where.format(latest=latest)
        print(f"  {src['id']} : dernier {col} = {latest}")

    params = {"select": src["select"]}
    if where:
        params["where"] = where
    rows = get(f"{base}/exports/json", params).json()
    if not rows:
        raise SystemExit(f"[{src['id']}] export vide")
    # Ordre deterministe : un diff git n'apparait que si les donnees changent vraiment.
    rows.sort(key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))

    write_json(RAW / f"{src['id']}.json", rows)
    write_json(RAW / f"{src['id']}.schema.json", {
        "source": f"data.economie.gouv.fr/{src['dataset']}",
        "modified": meta["metas"]["default"].get("modified"),
        "fields": {k: fields[k] for k in wanted},
    })
    print(f"  {src['id']} : {len(rows)} lignes")


def decode_csv(contenu: bytes) -> str:
    """Les pieces jointes publiees melangent UTF-8 (avec ou sans BOM) et UTF-16."""
    if contenu[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return contenu.decode("utf-16")
    return contenu.decode("utf-8-sig")


def fetch_ods_attachment(src: dict) -> None:
    """Piece jointe CSV d'un jeu Opendatasoft (annexes PLRG, series SMB), convertie en lignes JSON."""
    base = f"{CONFIG['ods_base']}/{src['dataset']}"
    meta = get(base).json()
    texte = decode_csv(get(f"{base}/attachments/{src['piece_jointe']}").content)
    lecteur = csv.DictReader(io.StringIO(texte.replace("\r\n", "\n")), delimiter=";")
    colonnes = [c.strip() for c in (lecteur.fieldnames or [])]
    manquantes = [c for c in src["colonnes"] if c not in colonnes]
    if manquantes:
        raise SystemExit(f"[{src['id']}] colonnes disparues dans la piece jointe : {manquantes}")
    rows = [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in lecteur]
    rows = [r for r in rows if any(r.values())]
    if not rows:
        raise SystemExit(f"[{src['id']}] piece jointe vide")
    rows.sort(key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))
    write_json(RAW / f"{src['id']}.json", rows)
    write_json(RAW / f"{src['id']}.schema.json", {
        "source": f"data.economie.gouv.fr/{src['dataset']}/attachments/{src['piece_jointe']}",
        "modified": meta["metas"]["default"].get("modified"),
        "fields": {c: "csv" for c in colonnes},
    })
    print(f"  {src['id']} : {len(rows)} lignes")


def fetch_eurostat(src: dict) -> None:
    data = get(f"{CONFIG['eurostat_base']}/{src['dataset']}", src["params"]).json()
    if not data.get("value"):
        raise SystemExit(f"[{src['id']}] reponse Eurostat vide")
    dims = data["id"]
    write_json(RAW / f"{src['id']}.json", data)
    write_json(RAW / f"{src['id']}.schema.json", {
        "source": f"eurostat/{src['dataset']}",
        "modified": data.get("updated"),
        "fields": {d: "dimension" for d in dims},
    })
    print(f"  {src['id']} : {len(data['value'])} valeurs")


def main() -> None:
    only = set(sys.argv[1:])
    for src in CONFIG["ods"]:
        if not only or src["id"] in only:
            fetch_ods(src)
    for src in CONFIG.get("ods_pieces_jointes", []):
        if not only or src["id"] in only:
            fetch_ods_attachment(src)
    for src in CONFIG["eurostat"]:
        if not only or src["id"] in only:
            fetch_eurostat(src)


if __name__ == "__main__":
    main()
