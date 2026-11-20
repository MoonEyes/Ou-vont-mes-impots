"""Indemnités des élus par commune, en total seulement : compte 653 des balances comptables de la DGFiP.

Montant global du budget principal de chaque commune, jamais par élu : le jeu ne nomme personne et le site non plus.

Entrées (réseau, `collecter`, reprenable) : data.economie.gouv.fr, jeux « Balances comptables des communes en
<exercice> » (DGFiP, Licence Ouverte 2.0), déjà interrogés par pipeline/investissement_communes.py. Rien n'est
téléchargé en entier : exports agrégés côté serveur (API Explore v2.1, `group_by` siren, budget principal), contrôlés
par collecte/integrite.py -> data/lake/elus_indemnites/<exercice>_<extrait>.csv. La présence d'une balance (budget
principal publié) est lue dans les extraits `presence` de pipeline/investissement_communes.py (même jeu, même filtre).
Lecture seule : site/data/local/geo/<dep>.json (communes en vigueur, SIREN).
Sorties (site/data/elus_indemnites/, chaque fichier < 1 Mo) :
  index.json           exercices, définitions, méthode, couverture, sources
  communes/<dep>.json  par commune : [compte 653] par exercice, euros

Méthode : dépense réelle mandatée d'un compte = OBNETDEB - OOBDEB (opérations budgétaires débit nettes des annulations,
moins les opérations d'ordre budgétaires), budget principal seulement, tous les sous-comptes du préfixe ; même méthode
que pipeline/investissement_communes.py. 653 = indemnités, frais de mission et de formation, cotisations de retraite
et de sécurité sociale des élus (intitulé du compte en M14 et en M57 ; les sous-comptes diffèrent, seul le total est publié). Aucun montant par
élu ni par habitant n'est calculé (règle 13 : le nombre d'élus indemnisés n'est pas publié par la source).

Commandes :
  python pipeline/elus_indemnites.py collecter
  python pipeline/elus_indemnites.py produire [--sortie DOSSIER]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "elus_indemnites"
LAKE_INV = ROOT / "data" / "lake" / "investissement_communes"
GEO = ROOT / "site" / "data" / "local" / "geo"
OUT = ROOT / "site" / "data" / "elus_indemnites"
ECO = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
PAGE = "https://data.economie.gouv.fr/explore/dataset/balances-comptables-des-communes-en-{a}/"
ANNEES = [str(a) for a in range(2010, 2026)]
MAX_OCTETS = 1_000_000
EXTRAITS = {"c653": 'startswith(compte,"653")'}
COLONNES = ["c653"]
DEFINITIONS = {
    "c653": ("Compte 653 : indemnités, frais de mission et de formation des élus, et cotisations de retraite et de "
             "sécurité sociale versées pour eux (compte 653 des nomenclatures M14 et M57), budget principal. Le "
             "découpage des sous-comptes diffère entre M14 et M57 (en M57, tout est regroupé sous le 6531) : seul le "
             "total du 653 est publié, comparable d'une nomenclature à l'autre au plus près de ce que publie la DGFiP."),
}
METHODE = ("Dépense réelle mandatée d'un compte = OBNETDEB - OOBDEB : opérations budgétaires au débit, nettes des "
           "annulations, moins les opérations d'ordre budgétaires (définitions de la DGFiP, « Structure du fichier de "
           "balances »). Budget principal seulement (CBUDG = 1, ou BUDGET = BP pour les exercices 2010 à 2015), tous "
           "les sous-comptes du préfixe. Montant global de la commune : la source ne publie ni le nombre d'élus "
           "indemnisés ni le montant de chacun, le site n'en calcule aucun.")
REGLE_NULL = ("Exercice absent : aucune balance du budget principal publiée sous le SIREN de la commune en vigueur "
              "(commune créée plus tard, fusion, balance non publiée), jamais 0. Un 0 publié est un compte sans "
              "dépense réelle dans une balance publiée (élus non indemnisés, ou indemnités portées par un autre budget).")
PLAFOND = ("Les montants maximaux des indemnités par fonction et par taille de commune sont fixés par le code général "
           "des collectivités territoriales (articles L2123-23 et L2123-24) ; le site ne les compare pas aux montants "
           "mandatés, faute du nombre d'élus indemnisés.")
RECHERCHE_PUBLIQUE = [
    {"trouvaille": "pipeline/investissement_communes.py (mêmes jeux, même méthode, extraits `presence` réutilisés)",
     "classement": "réutilisable tel quel", "licence": "celle du dépôt", "dernier_commit": None},
    {"trouvaille": "data.economie.gouv.fr, balances comptables des communes 2010-2025 (DGFiP)",
     "classement": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "dernier_commit": None},
    {"trouvaille": "OFGL, agrégat « Frais de personnel » des communes (déjà publié par pipeline/local.py)",
     "classement": "inspiration seulement", "licence": "Licence Ouverte 2.0", "dernier_commit": None,
     "note": "ne distingue pas les indemnités des élus"},
]


def collecter(rafraichir: bool = False) -> dict:
    import fetch
    import investissement_communes as ic
    import local
    LAKE.mkdir(parents=True, exist_ok=True)
    stats = {}
    for a in ANNEES:
        m = ic.meta(a, rafraichir)
        if not m:
            stats[a] = "inaccessible"
            continue
        ic.extrait(a, "presence", m, rafraichir)
        for nom, filtre in EXTRAITS.items():
            p = LAKE / f"{a}_{nom}.csv"
            if p.exists() and not rafraichir:
                continue
            params = {"select": "siren,ident,sum(obnetdeb) as d,sum(oobdeb) as o",
                      "where": f"{ic.filtre_bp(m)} and {filtre}", "group_by": "siren,ident", "delimiter": ";"}
            r = local.http_get(f"{ECO}/{m['dataset']}/exports/csv", params, essais=10, timeout=600)
            tmp = p.with_name(p.name + ".part")
            tmp.write_bytes(r.content)
            fetch.remplacer_si_valide(tmp, p, nom=p.name, octets_attendus=fetch.octets_annonces(r))
        stats[a] = m["modifie"]
        print(f"  {a} : extraits en cache", file=sys.stderr, flush=True)
    (LAKE / "collecte.json").write_text(json.dumps({"collecte_le": time.strftime("%Y-%m-%d", time.gmtime()),
                                                    "exercices": stats}, sort_keys=True), encoding="utf-8")
    return stats


def lire(p: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig")), delimiter=";"))


def euros(v) -> int | None:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets")
    path.write_text(texte + "\n", encoding="utf-8")
    return n


def produire(sortie: Path = OUT) -> dict:
    communes = {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for code, c in d["communes"].items():
            communes[code] = {"siren": c.get("siren"), "dep": d["departement"]["code"]}
    par_siren = {c["siren"]: code for code, c in communes.items() if c["siren"]}
    serie: dict[str, dict[str, list]] = defaultdict(dict)
    couverture, annees = {}, []
    for a in ANNEES:
        pres = LAKE_INV / f"{a}_presence.csv"
        if not pres.exists() or not all((LAKE / f"{a}_{n}.csv").exists() for n in EXTRAITS):
            continue
        annees.append(a)
        presents = {r["siren"] for r in lire(pres) if r["siren"] in par_siren}
        montants = {}
        for i, nom in enumerate(COLONNES):
            for r in lire(LAKE / f"{a}_{nom}.csv"):
                if r["siren"] in presents:
                    montants.setdefault(r["siren"], [0.0] * len(COLONNES))[i] += float(r["d"] or 0) - float(r["o"] or 0)
        c = Counter()
        for s in presents:
            v = montants.get(s, [0.0] * len(COLONNES))
            serie[par_siren[s]][a] = [euros(x) for x in v]
            c["avec_balance"] += 1
            c["montant_non_nul"] += v[0] > 0.5
        couverture[a] = dict(c)
    if not annees:
        raise SystemExit("aucun extrait : lancer `python pipeline/elus_indemnites.py collecter`")
    try:
        date = json.loads((LAKE / "collecte.json").read_text(encoding="utf-8"))["collecte_le"]
    except (OSError, ValueError, KeyError):
        date = date_sources()
    entete = {"millesime": f"exercices {annees[0]} à {annees[-1]} ; collecte du {date}",
              "source": f"data.economie.gouv.fr, DGFiP « Balances comptables des communes » {annees[0]} à {annees[-1]} "
                        f"(budget principal, agrégé côté serveur), Licence Ouverte 2.0 : {PAGE.format(a=annees[-1])}"}
    if sortie.exists():
        for f in sorted((sortie / "communes").glob("*.json")):
            f.unlink()
    par_dep = defaultdict(dict)
    for code in sorted(serie):
        par_dep[communes[code]["dep"]][code] = {a: serie[code][a] for a in sorted(serie[code])}
    tailles = [dump(sortie / "communes" / f"{dep}.json", {**entete, "departement": dep, "colonnes": COLONNES,
                                                          "unite": "euros", "communes": par_dep[dep]})
               for dep in sorted({c["dep"] for c in communes.values()})]
    index = {**entete, "presentation": ("Ce que chaque commune a dépensé pour ses élus (indemnités, frais, cotisations), "
                                        "en total pour la commune, d'après ses comptes de gestion. Aucun montant par élu."),
             "annees": annees, "colonnes": COLONNES, "definitions": DEFINITIONS, "methode": METHODE,
             "regle_null": REGLE_NULL, "plafond": PLAFOND, "licence": "Licence Ouverte 2.0",
             "couverture": {"communes_cog": len(communes), "communes_avec_serie": len(serie), "par_exercice": couverture},
             "recherche_publique": RECHERCHE_PUBLIQUE, "fichiers": {"communes": "communes/<dep>.json"},
             "taille_max_octets": max(tailles)}
    dump(sortie / "index.json", index)
    return index


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--rafraichir", action="store_true")
    ap.add_argument("--sortie", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        print(json.dumps(collecter(a.rafraichir), ensure_ascii=False))
    if a.etape in ("produire", "tout"):
        print(json.dumps(produire(a.sortie)["couverture"]["par_exercice"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
