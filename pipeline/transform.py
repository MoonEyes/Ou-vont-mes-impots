"""Transforme data/raw en fichiers compacts pour le site et en tables validables.

Sorties :
  site/data/sankey_etat.json   noeuds/liens : Etat > grand poste > mission > programme (Md EUR)
  site/data/communes/<dep>.json {code INSEE: [nom, taux TFB %, taux TEOM % ou null]}
  site/data/cofog.json         depenses publiques par fonction (toutes administrations)
  site/data/deficit.json       solde public (B9) des dernieres annees
  site/data/meta.json          sources, dates, totaux de controle
  data/processed/*.csv         tables validees par Frictionless (datapackage.json)
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import arbre

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SITE = ROOT / "site" / "data"
POSTES = json.loads((Path(__file__).parent / "grands_postes.json").read_text(encoding="utf-8"))
NIVEAUX = json.loads((Path(__file__).parent / "niveaux.json").read_text(encoding="utf-8"))
NATURE = json.loads((Path(__file__).parent / "nomenclature_nature.json").read_text(encoding="utf-8"))

COFOG_FR = {
    "GF01": "Services publics generaux", "GF02": "Defense", "GF03": "Ordre et securite publics",
    "GF04": "Affaires economiques", "GF05": "Environnement", "GF06": "Logement et equipements collectifs",
    "GF07": "Sante", "GF08": "Loisirs, culture et culte", "GF09": "Enseignement", "GF10": "Protection sociale",
}


def load(name: str):
    return json.loads((RAW / f"{name}.json").read_text(encoding="utf-8"))


def dump(path: Path, obj, compact: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":") if compact else None,
                      indent=None if compact else 1, sort_keys=not compact)
    path.write_text(text + "\n", encoding="utf-8")


def md(euros: float) -> float:
    return round(euros / 1e9, 4)


def budget_etat() -> dict:
    rows = load("budget_etat_plf")
    inconnues = sorted({r["mission"] for r in rows} - set(POSTES))
    if inconnues:
        raise SystemExit(f"Missions sans grand poste, a ajouter dans grands_postes.json : {inconnues}")

    prog = defaultdict(float)
    exclu = 0.0
    for r in rows:
        cp = r["cp_plf"] or 0.0
        poste = POSTES[r["mission"]]
        if poste == "exclu":
            exclu += cp
            continue
        key = (poste, r["mission"], int(r["programme"]), r["libelle_programme"])
        prog[key] += cp

    PROCESSED.mkdir(parents=True, exist_ok=True)
    with (PROCESSED / "budget_etat.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["grand_poste", "mission", "programme", "libelle_programme", "cp_euros"])
        for (poste, mission, num, lib), cp in sorted(prog.items()):
            w.writerow([poste, mission, num, lib, round(cp, 2)])

    retenues = [r for r in rows if POSTES[r["mission"]] != "exclu"]
    budget_detail(retenues)

    # Arbre a profondeur libre (niveaux definis dans niveaux.json).
    enrichies = [{**r, "grand_poste": POSTES[r["mission"]], "categorie": code_cat(r),
                  "libelle_titre": NATURE["titres"][r["code_titre"]],
                  "libelle_categorie": NATURE["categories"][code_cat(r)]} for r in retenues]
    stats_arbre = arbre.ecrire(arbre.construire(enrichies, NIVEAUX["niveaux"], "cp_plf"),
                               NIVEAUX["racine"], NIVEAUX["decoupe_apres"], SITE / "arbre")

    # Sankey : un noeud par niveau, identifiants prefixes pour eviter les collisions de noms.
    nodes, index, links = [], {}, defaultdict(float)

    def node(nid: str, label: str, level: int) -> int:
        if nid not in index:
            index[nid] = len(nodes)
            nodes.append({"id": nid, "name": label, "level": level})
        return index[nid]

    root = node("etat", "Budget de l'Etat", 0)
    for (poste, mission, num, lib), cp in prog.items():
        p = node(f"p:{poste}", poste, 1)
        m = node(f"m:{mission}", mission, 2)
        g = node(f"g:{num}", f"{lib} (P{num})", 3)
        links[(root, p)] += cp
        links[(p, m)] += cp
        links[(m, g)] += cp

    total = sum(prog.values())
    sankey = {
        "unite": "milliards d'euros (credits de paiement)",
        "total": md(total),
        "nodes": nodes,
        "links": [{"source": s, "target": t, "value": md(v)} for (s, t), v in sorted(links.items()) if v > 0],
    }
    dump(SITE / "sankey_etat.json", sankey)
    return {"total_md": md(total), "exclu_remboursements_md": md(exclu), "arbre": stats_arbre,
            "postes": len({k[0] for k in prog}), "missions": len({k[1] for k in prog}), "programmes": len(prog)}


def code_cat(r: dict) -> str:
    return str(int(r["categorie"])) if r.get("categorie") is not None else "?"


def budget_detail(rows: list[dict]) -> None:
    """Niveau le plus fin : sous-action x nature, plus un fichier par programme pour le site."""
    titres, cats = NATURE["titres"], NATURE["categories"]
    inconnus = sorted({code_cat(r) for r in rows} - set(cats)) + sorted({r["code_titre"] for r in rows} - set(titres))
    if inconnus:
        raise SystemExit(f"Codes de nature inconnus, a ajouter dans nomenclature_nature.json : {inconnus}")

    detail = defaultdict(float)
    for r in rows:
        key = (int(r["programme"]), r["action"], r["libelle_action"], r["sous_action"], r["libelle_sousaction"],
               r["code_titre"], code_cat(r))
        detail[key] += r["cp_plf"] or 0.0

    with (PROCESSED / "budget_etat_detail.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["programme", "action", "libelle_action", "sous_action", "libelle_sous_action",
                    "titre", "libelle_titre", "categorie", "libelle_categorie", "cp_euros"])
        for (num, act, lact, sact, lsact, t, c), cp in sorted(detail.items()):
            w.writerow([num, act, lact, sact, lsact, t, titres[t], c, cats[c], round(cp, 2)])

    # Un fichier par programme : actions > sous-actions, et repartition par nature.
    par_prog = defaultdict(lambda: {"actions": defaultdict(lambda: {"cp": 0.0, "sous_actions": defaultdict(float)}),
                                    "nature": defaultdict(float)})
    nature_totale = defaultdict(float)
    for (num, act, lact, sact, lsact, t, c), cp in detail.items():
        p = par_prog[num]
        a = p["actions"][(act, lact)]
        a["cp"] += cp
        a["sous_actions"][(sact, lsact)] += cp
        p["nature"][c] += cp
        nature_totale[(t, c)] += cp

    out_dir = SITE / "programmes"
    for old in out_dir.glob("*.json"):
        old.unlink()
    for num, p in par_prog.items():
        dump(out_dir / f"{num}.json", {
            "programme": num,
            "actions": [{"code": code, "nom": nom, "md": md(a["cp"]),
                         "sous_actions": [{"code": sc, "nom": sn, "md": md(v)}
                                          for (sc, sn), v in sorted(a["sous_actions"].items()) if v]}
                        for (code, nom), a in sorted(p["actions"].items()) if a["cp"]],
            "nature": {cats[c]: md(v) for c, v in sorted(p["nature"].items()) if v},
        })

    dump(SITE / "nature_etat.json", {
        "unite": "milliards d'euros (credits de paiement)",
        "titres": [{"titre": t, "nom": titres[t],
                    "md": md(sum(v for (tt, _), v in nature_totale.items() if tt == t)),
                    "categories": [{"code": c, "nom": cats[c], "md": md(v)}
                                   for (tt, c), v in sorted(nature_totale.items()) if tt == t and v]}
                   for t in sorted({t for t, _ in nature_totale})],
    })


def communes() -> dict:
    rows = load("taux_communes")
    out = defaultdict(dict)
    with (PROCESSED / "communes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code_insee", "nom", "taux_tfb", "taux_teom"])
        for r in sorted(rows, key=lambda r: r["dep"] + r["com"]):
            code = r["dep"] + r["com"]  # 2+3 en metropole, 3+2 en outre-mer : toujours 5 caracteres
            w.writerow([code, r["libcom"], r["taux_global_tfb"], r["taux_plein_teom"]])
            out[r["dep"]][code] = [r["libcom"], r["taux_global_tfb"], r["taux_plein_teom"]]
    # Un fichier par departement : le mobile ne charge que quelques Ko.
    for old in (SITE / "communes").glob("*.json"):
        old.unlink()
    for dep, communes_dep in out.items():
        dump(SITE / "communes" / f"{dep}.json", communes_dep)
    return {"communes": sum(len(v) for v in out.values()), "departements": len(out), "exercice": rows[0]["exercice"]}


def jsonstat_series(data: dict, dim: str) -> dict:
    """Extrait {categorie: {annee: valeur}} d'un JSON-stat Eurostat ou seules `dim` et `time` varient."""
    ids, sizes = data["id"], data["size"]
    for d, s in zip(ids, sizes):
        if d not in (dim, "time") and s != 1:
            raise SystemExit(f"Dimension inattendue {d} de taille {s}")
    cats = data["dimension"][dim]["category"]["index"]
    years = data["dimension"]["time"]["category"]["index"]
    stride_time = 1
    for d, s in zip(reversed(ids), reversed(sizes)):
        if d == "time":
            break
        stride_time *= s
    stride_dim = 1
    for d, s in zip(reversed(ids), reversed(sizes)):
        if d == dim:
            break
        stride_dim *= s
    out = defaultdict(dict)
    for c, ci in cats.items():
        for y, yi in years.items():
            v = data["value"].get(str(ci * stride_dim + yi * stride_time))
            if v is not None:
                out[c][y] = v
    return out


def cofog() -> dict:
    series = jsonstat_series(load("cofog_france"), "cofog99")
    annees = sorted({y for c in COFOG_FR for y in series.get(c, {})})
    # Derniere annee ou les 10 fonctions sont renseignees.
    annee = max(y for y in annees if all(y in series.get(c, {}) for c in COFOG_FR))
    fonctions = [{"code": c, "nom": n, "md": round(series[c][annee] / 1000, 2)} for c, n in COFOG_FR.items()]
    dump(SITE / "cofog.json", {"annee": annee, "unite": "milliards d'euros", "fonctions": fonctions,
                               "total": round(sum(f["md"] for f in fonctions), 2)})
    return {"annee_cofog": annee}


def deficit() -> dict:
    serie = jsonstat_series(load("deficit_france"), "na_item")["B9"]
    out = {y: round(v / 1000, 1) for y, v in sorted(serie.items())}
    dump(SITE / "deficit.json", {"unite": "milliards d'euros (negatif = deficit)", "solde_public": out})
    return {"deficit_derniere_annee": list(out.items())[-1]}


def main() -> None:
    controle = {**budget_etat(), **communes(), **cofog(), **deficit()}
    sources = {p.stem.replace(".schema", ""): json.loads(p.read_text(encoding="utf-8"))
               for p in sorted(RAW.glob("*.schema.json"))}
    dump(SITE / "meta.json", {
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {k: {"source": v["source"], "maj_source": v["modified"]} for k, v in sources.items()},
        "controle": controle,
    }, compact=False)
    print(json.dumps(controle, ensure_ascii=False))


if __name__ == "__main__":
    main()
