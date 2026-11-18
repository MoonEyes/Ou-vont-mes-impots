"""Investissement réalisé par commune : dépenses d'équipement réellement mandatées, d'après les balances comptables
de la DGFiP, exercices 2010 à 2025, à côté des crédits votés quand la commune publie son budget au format national.

Entrées (réseau, `collecter`, reprenable) :
  - data.economie.gouv.fr, jeux « Balances comptables des communes en <exercice> » (DGFiP, Licence Ouverte 2.0 ;
    jeu 2025 référencé sur data.gouv.fr : https://www.data.gouv.fr/datasets/6a557e9cae224f3addc27619). Rien n'est
    téléchargé en entier (7 millions de lignes par exercice) : exports agrégés côté serveur (API Explore v2.1,
    `group_by` siren, budget principal), quelques Mo chacun, contrôlés par collecte/integrite.py
    -> data/lake/investissement_communes/<exercice>_<extrait>.csv et meta_<exercice>.json ;
  - crédits votés : extraits des jeux au schéma national « Budget » (pipeline/deliberations.py, `votes_equipement`).
Lecture seule : site/data/local/geo/<dep>.json (communes en vigueur, SIREN, noms).
Sorties (site/data/investissement_communes/, `produire`, sans réseau, chaque fichier < 1 Mo) :
  index.json             exercices, définitions, méthode, couverture par exercice, rapprochements, sources
  communes/<dep>.json    par commune : dépenses d'équipement mandatées par exercice (total et comptes 20 hors 204,
                         21, 23 ; 204 à part) et, quand ils sont publiés, crédits votés au budget primitif et crédits
                         ouverts au compte administratif pour les mêmes comptes et le même budget

Méthode : dépense réelle mandatée d'un compte = OBNETDEB - OOBDEB (opérations budgétaires débit nettes des
annulations, moins les opérations d'ordre budgétaires, définitions de la DGFiP « Structure du fichier de
balances »), budget principal seulement (CBUDG = 1 ; BUDGET = BP avant 2016), tous les sous-comptes du préfixe.
Équipement = 20 (hors 204) + 21 + 23 ; 204 (subventions d'équipement versées à d'autres) publié à part, jamais
ajouté. Rattachement d'une balance à une commune par son SIREN, égal à celui de la commune en vigueur
(site/data/local/geo) : une commune nouvelle n'a pas de série avant sa création (motif `absente`), les balances des
anciennes communes sont comptées dans l'index et jamais attribuées.

Règle 13 : aucun taux de réalisation n'est calculé. Les crédits votés au budget primitif ne comprennent ni les
reports ni les décisions modificatives, et un compte administratif publié au format national peut ne couvrir qu'une
partie des articles : les montants sont montrés côte à côte, avec leur source, sans rapport ni différence.

Commandes :
  python pipeline/investissement_communes.py collecter
  python pipeline/investissement_communes.py produire [--sortie DOSSIER]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliberations  # noqa: E402
import fetch  # noqa: E402
import local  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "investissement_communes"
OUT = ROOT / "site" / "data" / "investissement_communes"
GEO = ROOT / "site" / "data" / "local" / "geo"
ECO = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
JEU = "balances-comptables-des-communes-en-{a}"
DATAGOUV_2025 = "https://www.data.gouv.fr/datasets/6a557e9cae224f3addc27619"
ANNEES = [str(a) for a in range(2010, 2026)]
MAX_OCTETS = 1_000_000

# Extraits par exercice : (nom, filtre sur le compte). Le filtre « budget principal » est ajouté selon l'exercice.
EXTRAITS = {
    "c20": 'startswith(compte,"20") and not startswith(compte,"204")',
    "c204": 'startswith(compte,"204")',
    "c21": 'startswith(compte,"21")',
    "c23": 'startswith(compte,"23")',
}
COLONNES = ["equipement", "c20_hors_204", "c21", "c23", "c204"]
DEFINITIONS = {
    "equipement": "Dépenses d'équipement mandatées : comptes 20 (hors 204), 21 et 23, opérations réelles",
    "c20_hors_204": "Compte 20 hors 204 : immobilisations incorporelles (études, logiciels, frais d'urbanisme)",
    "c21": "Compte 21 : immobilisations corporelles (terrains, bâtiments, voirie, matériel) acquises ou achevées",
    "c23": "Compte 23 : immobilisations en cours (travaux non terminés, avances versées sur commandes)",
    "c204": "Compte 204 : subventions d'équipement versées à d'autres organismes (publiées à part, non incluses "
            "dans l'équipement de la commune)",
}
SOURCE = ("data.economie.gouv.fr, DGFiP « Balances comptables des communes » {debut} à {fin} (budget principal, "
          "agrégé côté serveur), Licence Ouverte 2.0")
METHODE = (
    "Dépense réelle mandatée d'un compte = OBNETDEB - OOBDEB : opérations budgétaires au débit, nettes des "
    "annulations, moins les opérations d'ordre budgétaires (définitions de la DGFiP, « Structure du fichier de "
    "balances »). Budget principal seulement (CBUDG = 1, ou BUDGET = BP pour les exercices 2010 à 2015), tous les "
    "sous-comptes du préfixe. Équipement = 20 hors 204 + 21 + 23 (somme publiée par le site, même balance, même "
    "exercice). Le 204 est publié à part et jamais ajouté. Les crédits des comptes 236, 237 et 238 (avances "
    "récupérées) ne sont pas déduits : l'agrégat « dépenses d'équipement » de l'OFGL (page commune, budget principal "
    "et budgets annexes) suit une autre définition et un autre périmètre ; les deux ne se comparent pas directement.")
METHODE_VOTE = (
    "Crédits votés : jeux au schéma national « Budget » publiés par la commune (data.gouv.fr), dépenses réelles des "
    "mêmes comptes. Budget primitif : propositions nouvelles votées (BGT_MTPROPNOUV) ; compte administratif : "
    "crédits ouverts dans l'exercice (BGT_CREDOUV), qui comprennent budget primitif, budget supplémentaire, décisions "
    "modificatives et reports. Rapprochés de la balance seulement si le SIRET du document est celui du budget "
    "principal dans la balance du même exercice (même périmètre). Aucun taux ni écart n'est calculé : les reports "
    "et décisions modificatives ne figurent pas au budget primitif.")
REGLE_NULL = ("Exercice absent de `m` : aucune balance publiée sous le SIREN de la commune en vigueur (commune créée "
              "plus tard, fusion, ou balance non publiée) ; jamais 0. Un 0 publié est un compte sans dépense réelle "
              "dans une balance publiée.")


# --- Collecte ---------------------------------------------------------------------------------------------------------


def meta(annee: str, rafraichir: bool = False) -> dict | None:
    p = LAKE / f"meta_{annee}.json"
    if p.exists() and not rafraichir:
        return json.loads(p.read_text(encoding="utf-8"))
    try:
        d = local.http_get(f"{ECO}/{JEU.format(a=annee)}", essais=8, timeout=120).json()
    except (RuntimeError, SystemExit) as exc:
        print(f"  {annee} : métadonnées inaccessibles ({exc})", file=sys.stderr)
        return None
    m = {"dataset": d["dataset_id"], "champs": sorted(f["name"] for f in d["fields"]),
         "modifie": (d["metas"]["default"].get("modified") or "")[:10],
         "lignes": d["metas"]["default"].get("records_count"),
         "licence": d["metas"]["default"].get("license") or ""}
    LAKE.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".part")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    fetch.remplacer_si_valide(tmp, p, nom=p.name)
    return m


def filtre_bp(m: dict) -> str:
    if "cbudg" in m["champs"]:
        return 'cbudg="1"'
    if "budget" in m["champs"]:
        return 'budget="BP"'
    raise SystemExit(f"{m['dataset']} : ni CBUDG ni BUDGET, budget principal non identifiable")


def extrait(annee: str, nom: str, m: dict, rafraichir: bool = False) -> Path:
    """Export CSV agrégé côté serveur (quelques Mo), contrôlé par collecte/integrite.py avant renommage."""
    p = LAKE / f"{annee}_{nom}.csv"
    if p.exists() and not rafraichir:
        return p
    if nom == "presence":
        params = {"select": "siren,ident,ndept,insee,count(*) as n", "where": filtre_bp(m),
                  "group_by": "siren,ident,ndept,insee"}
    else:
        params = {"select": "siren,ident,sum(obnetdeb) as d,sum(oobdeb) as o",
                  "where": f"{filtre_bp(m)} and {EXTRAITS[nom]}", "group_by": "siren,ident"}
    r = local.http_get(f"{ECO}/{m['dataset']}/exports/csv", {**params, "delimiter": ";"}, essais=10, timeout=600)
    tmp = p.with_name(p.name + ".part")
    tmp.write_bytes(r.content)
    fetch.remplacer_si_valide(tmp, p, nom=p.name, octets_attendus=fetch.octets_annonces(r))
    return p


def collecter(rafraichir: bool = False) -> dict:
    LAKE.mkdir(parents=True, exist_ok=True)
    stats = {}
    for a in ANNEES:
        m = meta(a, rafraichir)
        if not m:
            stats[a] = "inaccessible"
            continue
        for nom in ["presence", *EXTRAITS]:
            extrait(a, nom, m, rafraichir)
        stats[a] = m["modifie"]
        print(f"  {a} : extraits en cache", file=sys.stderr)
    return stats


# --- Production -------------------------------------------------------------------------------------------------------


def lire(p: Path) -> list[dict]:
    texte = p.read_bytes().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(texte), delimiter=";"))


def euros(v) -> int | None:
    x = local.num(v)
    return None if x is None else int(round(x))


def communes_geo() -> tuple[dict, dict]:
    """SIREN -> (insee, dep) ; dep -> {insee: nom} (communes en vigueur, site/data/local/geo)."""
    par_siren, par_dep = {}, {}
    for p in sorted(GEO.glob("*.json")):
        g = json.loads(p.read_text(encoding="utf-8"))
        dep = g["departement"]["code"]
        par_dep[dep] = {}
        for insee, c in g["communes"].items():
            par_dep[dep][insee] = c["nom"]
            if c.get("siren"):
                par_siren[c["siren"]] = (insee, dep)
    return par_siren, par_dep


def montants_annee(a: str) -> tuple[dict, dict, Counter]:
    """SIREN -> [equipement, c20, c21, c23, c204] (euros arrondis) ; SIREN -> SIRET du budget principal."""
    pres = lire(LAKE / f"{a}_presence.csv")
    ident, n_ident = {}, Counter()
    for r in pres:
        n_ident[r["siren"]] += 1
        ident.setdefault(r["siren"], set()).add(r["ident"])
    val = {s: {k: 0.0 for k in EXTRAITS} for s in ident}
    for nom in EXTRAITS:
        for r in lire(LAKE / f"{a}_{nom}.csv"):
            if r["siren"] in val:
                val[r["siren"]][nom] += (local.num(r["d"]) or 0.0) - (local.num(r["o"]) or 0.0)
    res = {}
    for s, v in val.items():
        c20, c204, c21, c23 = (int(round(v[k])) for k in ("c20", "c204", "c21", "c23"))
        res[s] = [c20 + c21 + c23, c20, c21, c23, c204]
    siret = {s: sorted(i)[0] for s, i in ident.items() if len(i) == 1}
    return res, siret, Counter({"sirets_multiples": sum(1 for s, i in ident.items() if len(i) > 1)})


def bloc_vote(postes: dict, champ: str) -> tuple[list | None, list]:
    """{poste: sommes} -> [equipement, c20, c21, c23, c204] pour un champ ; None si le champ n'est jamais renseigné."""
    vals = {p: (postes.get(p) or {}).get(champ) for p in ("c20", "c21", "c23", "c204")}
    if all(v is None for v in vals.values()):
        return None, []
    e = [int(round(vals[p] or 0.0)) for p in ("c20", "c21", "c23", "c204")]
    jeux = sorted({j for p in postes.values() for j in p.get("jeux", [])})
    return [e[0] + e[1] + e[2], e[0], e[1], e[2], e[3]], jeux


def produire(sortie: Path = OUT) -> dict:
    metas = {a: json.loads((LAKE / f"meta_{a}.json").read_text(encoding="utf-8")) for a in ANNEES
             if (LAKE / f"meta_{a}.json").exists() and all((LAKE / f"{a}_{n}.csv").exists()
                                                            for n in ["presence", *EXTRAITS])}
    if not metas:
        raise SystemExit("data/lake/investissement_communes vide : lancer « collecter »")
    annees = sorted(metas)
    par_siren, par_dep = communes_geo()
    votes = deliberations.votes_equipement()
    sorties = defaultdict(dict)
    couverture, vote_couv = {}, Counter()
    for a in annees:
        res, siret_bp, ctrl = montants_annee(a)
        hors = [s for s in res if s not in par_siren]
        couverture[a] = {"balances": len(res), "communes_rattachees": len(res) - len(hors),
                         "balances_sans_commune_en_vigueur": len(hors),
                         "sirets_multiples": ctrl["sirets_multiples"],
                         "jeu": metas[a]["dataset"], "publie_le": metas[a]["modifie"]}
        for s, v in res.items():
            if s not in par_siren:
                continue
            insee, dep = par_siren[s]
            c = sorties[dep].setdefault(insee, {"nom": par_dep[dep][insee], "siren": s, "m": {}})
            c["m"][a] = v
            sb = siret_bp.get(s)
            if sb and sb in votes and a in votes[sb]:
                docs = votes[sb][a]
                for etape, champ, cle in (("budget_primitif", "propnouv", "budget_primitif"),
                                          ("compte_administratif", "credouv", "credits_ouverts")):
                    b, jeux = bloc_vote(docs.get(etape) or {}, champ)
                    if b is not None:
                        c.setdefault("vote", {}).setdefault(a, {})[cle] = b
                        c["vote"][a].setdefault("jeux", [])
                        c["vote"][a]["jeux"] = sorted(set(c["vote"][a]["jeux"]) | set(jeux))
                        vote_couv[cle + ":" + a] += 1
    debut, fin = annees[0], annees[-1]
    source = SOURCE.format(debut=debut, fin=fin)
    mill = f"Balances {debut} à {fin} (exercice {fin} publié le {metas[fin]['modifie']})"
    deliberations.vider(sortie / "communes")
    tailles = {}
    for dep in sorted(sorties):
        doc = {"millesime": mill, "source": source, "departement": dep, "annees": annees, "colonnes": COLONNES,
               "unite": "euros courants, arrondis à l'euro", "regle_null": REGLE_NULL,
               "communes": dict(sorted(sorties[dep].items()))}
        tailles[dep] = deliberations.dump(sortie / "communes" / f"{dep}.json", doc)
    jeux_vote = sorted({j for d in sorties.values() for c in d.values() for v in (c.get("vote") or {}).values()
                        for j in v["jeux"]})
    index = {
        "millesime": mill, "source": source, "annees": annees, "colonnes": COLONNES, "definitions": DEFINITIONS,
        "presentation": ("Ce que chaque commune a réellement payé pour ses équipements (travaux, bâtiments, voirie, "
                         "matériel), année par année, d'après ses comptes tenus par la DGFiP. À côté, quand la commune "
                         "publie son budget au format national, les crédits qu'elle avait votés. La page ne montre "
                         "pas les projets un par un ni les budgets annexes (eau, assainissement...)."),
        "methode": METHODE, "methode_vote": METHODE_VOTE, "regle_null": REGLE_NULL,
        "statut": {"montants": "tracé (balance DGFiP)", "equipement": "calculé par le site (somme de trois comptes "
                   "d'une même balance)", "vote": "tracé (document budgétaire publié par la commune)"},
        "couverture": couverture,
        "vote_couverture": {k: vote_couv[k] for k in sorted(vote_couv)},
        "jeux": {a: {"dataset": metas[a]["dataset"], "url": f"https://data.economie.gouv.fr/explore/dataset/"
                     f"{metas[a]['dataset']}/", "publie_le": metas[a]["modifie"], "licence": metas[a]["licence"],
                     "lignes": metas[a]["lignes"]} for a in annees},
        "jeux_vote": [{"id": j, "url": deliberations.PAGE_JEU + j + "/"} for j in jeux_vote],
        "reference_datagouv": DATAGOUV_2025,
        "departements": sorted(sorties),
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    deliberations.dump(sortie / "index.json", index)
    return {"annees": annees, "communes": sum(len(d) for d in sorties.values()),
            "fichiers": len(tailles), "plus_gros": max(tailles.values()) if tailles else 0,
            "votes": dict(vote_couv)}


RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "trouvailles": [
        {"nom": "data.economie.gouv.fr, balances comptables des communes 2010 à 2025 (API Explore v2.1)",
         "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "note": "agrégation côté serveur"},
        {"nom": "OFGL, agrégat « Dépenses d'équipement » (data.ofgl.fr)", "verdict": "à adapter",
         "licence": "Licence Ouverte 2.0", "note": "budget principal et annexes consolidés : autre périmètre, déjà "
                                                   "publié sur la page commune (pipeline/local.py)"},
        {"nom": "pipeline/local_fonctions.py (exports agrégés des balances par fonction, 2023 à 2025)",
         "verdict": "à adapter", "licence": "dépôt", "note": "même méthode d'export, comptes et années différents"},
        {"nom": "Datafin / Regards citoyens « Comptes des collectivités »", "verdict": "inspiration seulement",
         "licence": "non vérifiée", "note": "aucune mise à jour récente trouvée"},
    ],
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("etape", nargs="?", choices=["collecter", "produire"], default=None)
    ap.add_argument("--rafraichir", action="store_true")
    ap.add_argument("--sortie", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if a.etape in (None, "collecter"):
        print(json.dumps(collecter(a.rafraichir), ensure_ascii=False, indent=1))
    if a.etape in (None, "produire"):
        print(json.dumps(produire(a.sortie), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
