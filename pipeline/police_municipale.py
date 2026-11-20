"""Polices municipales : effectifs par commune (agents de police municipale, agents de surveillance de la voie publique,
gardes champêtres), enquête annuelle du ministère de l'Intérieur.

Entrées (réseau, `collecter`) : fichiers annuels (ods, xlsx) de la fiche data.gouv.fr « Police municipale : Effectifs
par commune » (ministère de l'Intérieur, Licence Ouverte), années 2019 à 2024, liste lue par l'API data.gouv.fr,
contrôlés par collecte/integrite.py -> data/lake/police_municipale/pm_<année>.<ext>, ressources.json.
Lecture seule : site/data/local/geo/<dep>.json (communes en vigueur, noms).
Sorties (site/data/police_municipale/) :
  index.json       années, définitions, rapprochement des noms, couverture, sources
  communes.json    par commune (code Insee) : [agents de police municipale, ASVP, gardes champêtres] par année

Rapprochement : la source ne donne pas de code Insee, seulement le département et le nom de la commune (ou de
l'intercommunalité) qui a un service. Le nom est normalisé (accents, tirets, « St » en « Saint ») et cherché parmi les
communes en vigueur du même département ; une ligne sans correspondance unique (intercommunalité, ancienne commune,
graphie différente) n'est rattachée à aucune commune et comptée dans index.json. Une commune absente d'une année n'a
pas déclaré de service cette année-là (ou n'a pas été rapprochée) : rien n'est publié, jamais 0. Effectifs repris
tels quels (des demi-postes existent dans la source).

Commandes :
  python pipeline/police_municipale.py collecter
  python pipeline/police_municipale.py produire [--sortie DOSSIER]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "police_municipale"
GEO = ROOT / "site" / "data" / "local" / "geo"
OUT = ROOT / "site" / "data" / "police_municipale"
FICHE = "https://www.data.gouv.fr/datasets/police-municipale-effectifs-par-commune"
API = "https://www.data.gouv.fr/api/1/datasets/police-municipale-effectifs-par-commune/"
ANNEES = [str(a) for a in range(2019, 2025)]
COLONNES = ["agents_police_municipale", "asvp", "gardes_champetres"]
DEFINITIONS = {
    "agents_police_municipale": "Agents de police municipale de la commune (y compris ceux mis en commun, tels que déclarés)",
    "asvp": "Agents de surveillance de la voie publique (à Paris : agents de surveillance de Paris)",
    "gardes_champetres": "Gardes champêtres",
}
RECHERCHE_PUBLIQUE = [
    {"trouvaille": "Fiche data.gouv.fr « Police municipale : Effectifs par commune » (ministère de l'Intérieur)",
     "classement": "réutilisable tel quel", "licence": "Licence Ouverte", "dernier_commit": "2026-02-12"},
    {"trouvaille": "Reprise communautaire 2013-2024 sur data.gouv.fr (producteur particulier)", "classement": "à adapter",
     "licence": "Licence Ouverte 2.0", "dernier_commit": "2026-07-15",
     "note": "contrôle croisé seulement ; la source reste le ministère"},
]


def collecter(forcer: bool = False) -> dict:
    import fetch
    import local
    LAKE.mkdir(parents=True, exist_ok=True)
    d = local.http_get(API, essais=8, timeout=60).json()
    ressources, etat = {}, {}
    for r in d["resources"]:
        m = re.search(r"(20\d\d)", r["title"] + " " + r["url"].rsplit("/", 1)[-1])
        if m and m.group(1) in ANNEES and m.group(1) not in ressources:
            ressources[m.group(1)] = {"url": r["url"], "titre": r["title"], "mise_a_jour": (r.get("last_modified") or "")[:10]}
    for a, r in sorted(ressources.items()):
        dest = LAKE / f"pm_{a}{Path(r['url']).suffix.lower()}"
        if dest.exists() and not forcer:
            etat[a] = "présent"
            continue
        try:
            rep = local.http_get(r["url"], essais=6, timeout=120)
        except (RuntimeError, SystemExit) as exc:
            etat[a] = f"inaccessible : {exc}"[:200]
            continue
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(rep.content)
        fetch.remplacer_si_valide(tmp, dest, nom=dest.name, octets_attendus=fetch.octets_annonces(rep))
        etat[a] = "ok"
    (LAKE / "ressources.json").write_text(json.dumps({"licence": d.get("license"), "ressources": ressources,
                                                      "collecte_le": time.strftime("%Y-%m-%d", time.gmtime())},
                                                     ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    return etat


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower().replace("œ", "oe").replace("æ", "ae")
    m = re.search(r"\((l|la|le|les)\)", s)   # « Foret-Fouesnant (la) » -> « la Foret-Fouesnant »
    s = re.sub(r"\(.*?\)", " ", s)
    if m:
        s = f"{m.group(1)} {s}"
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    mots = [{"st": "saint", "ste": "sainte"}.get(m, m) for m in s.split()]
    return " ".join(mots)


def cle_dep(v) -> str | None:
    s = str(v if v is not None else "").strip()
    if re.fullmatch(r"\d+(\.0)?", s):
        n = int(float(s))
        return f"{n:02d}" if n < 100 else str(n)
    s = s.upper().replace(" ", "")
    return s if re.fullmatch(r"2[AB]|97\d", s) else None


def lignes(p: Path) -> tuple[list, dict]:
    import pandas as pd
    feuilles = pd.read_excel(p, header=None, sheet_name=None, dtype=object)
    df = next(v for k, v in feuilles.items() if "ommune" in k)
    rows = [[None if (isinstance(x, float) and x != x) else x for x in r] for r in df.itertuples(index=False)]
    i_ent = next(i for i, r in enumerate(rows[:20]) if any(isinstance(x, str) and "Nom des communes" in x for x in r))
    ent = [str(x or "") for x in rows[i_ent]]
    col = {"nom": next(i for i, x in enumerate(ent) if "Nom des communes" in x),
           "pm": next(i for i, x in enumerate(ent) if "agents de police municipale" in x and "Mise en commun" not in x),
           "asvp": next(i for i, x in enumerate(ent) if "ASVP" in x),
           "gc": next(i for i, x in enumerate(ent) if "gardes" in x.lower())}
    return rows[i_ent + 1:], col


def valeur(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else round(f, 1)


def produire(sortie: Path = OUT) -> dict:
    noms = defaultdict(lambda: defaultdict(list))
    deps = set()
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        dep = d["departement"]["code"]
        deps.add(dep)
        for code, c in d["communes"].items():
            noms[dep][norm(c["nom"])].append(code)
    out, stats, annees, non_rapproches = defaultdict(dict), {}, [], {}
    for a in ANNEES:
        p = next(iter(sorted(LAKE.glob(f"pm_{a}.*"))), None)
        if not p or p.suffix == ".part":
            continue
        rows, col = lignes(p)
        annees.append(a)
        c = Counter()
        sans = []
        for r in rows:
            dep = cle_dep(r[0])
            nom = r[col["nom"]]
            if not dep or not isinstance(nom, str) or not nom.strip() or str(r[0]).startswith("TOTAL"):
                continue
            if dep not in deps:
                c["departement_inconnu"] += 1
                continue
            v = [valeur(r[col["pm"]]), valeur(r[col["asvp"]]), valeur(r[col["gc"]])]
            if all(x is None for x in v):
                continue
            c["lignes"] += 1
            cand = noms[dep].get(norm(nom), [])
            if len(cand) == 1 and a not in out[cand[0]]:
                out[cand[0]][a] = v
                c["rapprochees"] += 1
            else:
                c["non_rapprochees"] += 1
                sans.append(f"{dep} {nom.strip()}")
        stats[a] = dict(c)
        non_rapproches[a] = len(sans)
    if not annees:
        raise SystemExit("aucun fichier : lancer `python pipeline/police_municipale.py collecter`")
    try:
        meta = json.loads((LAKE / "ressources.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    date = meta.get("collecte_le") or date_sources()
    entete = {"millesime": f"enquêtes {annees[0]} à {annees[-1]} ; collecte du {date}",
              "source": f"Ministère de l'Intérieur, « Police municipale : Effectifs par commune », data.gouv.fr : {FICHE}"}
    sortie.mkdir(parents=True, exist_ok=True)
    doc = {**entete, "colonnes": COLONNES, "communes": {k: dict(sorted(v.items())) for k, v in sorted(out.items())}}
    (sortie / "communes.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    index = {**entete, "presentation": "Combien d'agents de police municipale, d'ASVP et de gardes champêtres la commune "
                                       "déclare à l'enquête annuelle du ministère de l'Intérieur.",
             "annees": annees, "colonnes": COLONNES, "definitions": DEFINITIONS,
             "rapprochement": ("Source sans code Insee : nom normalisé cherché parmi les communes en vigueur du même "
                               "département ; sans correspondance unique (intercommunalité, ancienne commune, graphie), "
                               "la ligne n'est rattachée à aucune commune."),
             "absence": ("Commune absente une année : pas de service déclaré cette année-là, ou ligne non rapprochée ; "
                         "rien n'est publié, jamais 0."),
             "licence": meta.get("licence") or "Licence Ouverte", "fiche": FICHE,
             "sources": [{"annee": k, **v} for k, v in sorted((meta.get("ressources") or {}).items())],
             "couverture": {"communes_publiees": len(out), "par_annee": stats},
             "recherche_publique": RECHERCHE_PUBLIQUE, "fichiers": {"communes": "communes.json"}}
    (sortie / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return index


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true")
    ap.add_argument("--sortie", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        print(json.dumps(collecter(a.forcer), ensure_ascii=False))
    if a.etape in ("produire", "tout"):
        print(json.dumps(produire(a.sortie)["couverture"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
