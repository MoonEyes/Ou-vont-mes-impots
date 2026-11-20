"""Emploi dans les territoires : assurance chômage par département (Unédic) et inscrits à France Travail par commune
(Dares), effectifs agrégés tels que publiés.

Entrées (réseau, `collecter`) : exports des API Explore v2.1, contrôlés par collecte/integrite.py
  - data.unedic.org `evolution_indicateurs_cles_ac` (Unédic, « Indicateurs de suivi de l'Assurance chômage - par
    département », Licence Ouverte 2.0, fiche data.gouv.fr 63a4384ab7505d95e39dde9a) : lignes départementales ;
  - data.dares.travail-emploi.gouv.fr `dares_defm_communales-brutes` (Dares, « Inscrits à France Travail - Données
    communales », Licence Ouverte 2.0, fiche data.gouv.fr 66df098924d76afbdd70938a) : catégories A, B, C, tous sexes
    et âges, 4e trimestre de chaque année, filtré côté serveur
  -> data/lake/emploi_territoires/unedic.parquet, dares.parquet, meta_*.json.
Lecture seule : site/data/local/geo/<dep>.json.
Sorties (site/data/emploi_territoires/) :
  index.json            définitions, secret statistique, couverture, sources
  departements.json     Unédic : par département, mois de décembre de chaque année et dernier mois publié
  communes/<dep>.json   Dares : inscrits en catégories A, B, C au 4e trimestre, par commune et par année

Règles : valeurs reprises telles quelles (effectifs Dares arrondis à 5 par la source, petits effectifs non diffusés :
null, jamais 0) ; montants moyens et dépense mensuelle de l'Unédic publiés par la source, aucun cumul annuel ni ratio
calculé par le site (règle 13).

Commandes :
  python pipeline/emploi_territoires.py collecter
  python pipeline/emploi_territoires.py produire [--sortie DOSSIER]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "emploi_territoires"
GEO = ROOT / "site" / "data" / "local" / "geo"
OUT = ROOT / "site" / "data" / "emploi_territoires"
MAX_OCTETS = 1_000_000
UNEDIC_COLS = {"nb_alloc": "Allocataires pris en charge par l'Assurance chômage dans le mois",
               "nb_indemnises": "Allocataires indemnisés dans le mois",
               "montant_indemnisation_net_tous": "Montant moyen d'indemnisation mensuel net, en euros",
               "depense": "Dépense d'allocations du mois, en euros",
               "part_travail": "Part des allocataires ayant travaillé dans le mois, en %"}
JEUX = {
    "unedic": {"api": "https://data.unedic.org/api/explore/v2.1/catalog/datasets/evolution_indicateurs_cles_ac",
               "page": "https://data.unedic.org/explore/dataset/evolution_indicateurs_cles_ac/",
               "fiche": "https://www.data.gouv.fr/datasets/63a4384ab7505d95e39dde9a",
               "titre": "Unédic, « Indicateurs de suivi de l'Assurance chômage - par département »",
               "params": {"select": "code_departement,departement,annee_mois," + ",".join(UNEDIC_COLS),
                          "where": "code_departement is not null"}},
    "dares": {"api": "https://data.dares.travail-emploi.gouv.fr/api/explore/v2.1/catalog/datasets/dares_defm_communales-brutes",
              "page": "https://data.dares.travail-emploi.gouv.fr/explore/dataset/dares_defm_communales-brutes/",
              "fiche": "https://www.data.gouv.fr/datasets/66df098924d76afbdd70938a",
              "titre": "Dares, « Inscrits à France Travail - Données communales (trimestrielles, brutes) »",
              "params": {"select": "date,code_commune,nombre_de_demandeurs_d_emploi",
                         "where": 'categorie="ABC" and sexe="Total" and tranche_d_age="Total"'}},
}
DEFINITIONS = {
    "inscrits_abc": ("Demandeurs d'emploi inscrits à France Travail en catégories A, B et C (sans emploi, ou en activité "
                     "réduite), moyenne du 4e trimestre, domiciliés dans la commune (code géographique au 1er janvier "
                     "2024 selon la Dares). Ce n'est pas un flux d'argent : contexte des dépenses pour l'emploi."),
    **UNEDIC_COLS,
}
SECRET = ("Inscrits : effectifs bruts arrondis au multiple de 5 par la Dares ; sur les petites communes l'arrondi pèse "
          "lourd sur les évolutions ; valeur non diffusée : null, jamais 0.")
RECHERCHE_PUBLIQUE = [
    {"trouvaille": "data.unedic.org (API Explore)", "classement": "réutilisable tel quel", "licence": "Licence Ouverte 2.0",
     "dernier_commit": None, "note": "même hôte que pipeline/prestations.py et pipeline/emploi.py (vue nationale)"},
    {"trouvaille": "data.dares.travail-emploi.gouv.fr (API Explore)", "classement": "réutilisable tel quel",
     "licence": "Licence Ouverte 2.0", "dernier_commit": None},
    {"trouvaille": "fgeerolf.com, pages Dares communes", "classement": "inspiration seulement", "licence": "non précisée",
     "dernier_commit": None},
]


def collecter(forcer: bool = False) -> dict:
    import local_satellites
    import requests
    LAKE.mkdir(parents=True, exist_ok=True)
    etat = {}
    for cle, j in JEUX.items():
        dest = LAKE / f"{cle}.parquet"
        if dest.exists() and dest.stat().st_size and not forcer:
            etat[cle] = "présent"
        else:
            etat[cle] = local_satellites.telecharger(f"{j['api']}/exports/parquet", dest, j["params"], essais=8)
        for i in range(6):
            try:
                r = requests.get(j["api"], timeout=60, headers=local_satellites.ENTETE_HTTP)
                if r.status_code in (401, 403, 429):
                    break
                m = r.json()["metas"]["default"]
                (LAKE / f"meta_{cle}.json").write_text(json.dumps(
                    {"licence": m.get("license"), "modifie": (m.get("modified") or "")[:10], "lignes": m.get("records_count")},
                    sort_keys=True), encoding="utf-8")
                break
            except Exception:
                time.sleep(4 * (i + 1))
        print(f"{cle}: {etat[cle]}", flush=True)
    if any(v == "ok" for v in etat.values()) or not (LAKE / "collecte.json").exists():
        (LAKE / "collecte.json").write_text(json.dumps({"collecte_le": time.strftime("%Y-%m-%d", time.gmtime())}), encoding="utf-8")
    return etat


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets ({n})")
    path.write_text(texte + "\n", encoding="utf-8")
    return n


def num(v, chiffres=1):
    if v is None:
        return None
    f = float(v)
    if f != f:
        return None
    r = round(f, chiffres)
    return int(r) if r == int(r) else r


def lire(cle: str, sql: str) -> list[tuple]:
    import duckdb
    p = LAKE / f"{cle}.parquet"
    if not p.exists():
        raise SystemExit(f"{p} absent : lancer `python pipeline/emploi_territoires.py collecter`")
    return duckdb.connect().execute(sql.replace("{f}", f"'{p}'")).fetchall()


def meta(cle):
    try:
        return json.loads((LAKE / f"meta_{cle}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def produire(sortie: Path = OUT) -> dict:
    communes, deps = {}, {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        deps[d["departement"]["code"]] = d["departement"]["nom"]
        for code in d["communes"]:
            communes[code] = d["departement"]["code"]
    try:
        date = json.loads((LAKE / "collecte.json").read_text(encoding="utf-8"))["collecte_le"]
    except (OSError, ValueError, KeyError):
        date = date_sources()

    # Unédic : décembre de chaque année et dernier mois publié
    cols = list(UNEDIC_COLS)
    mois = defaultdict(dict)
    for dep, nom, am, *v in lire("unedic", f"select code_departement, departement, cast(annee_mois as varchar), {', '.join(cols)} from {{f}} order by 1, 3"):
        dep = str(dep).zfill(2) if str(dep).isdigit() and len(str(dep)) < 2 else str(dep)
        mois[dep][am[:7]] = [num(x, 0) if i < 2 or cols[i] == "depense" else num(x) for i, x in enumerate(v)]
    dernier = max(m for d in mois.values() for m in d)
    unedic = {}
    for dep in sorted(mois):
        if dep not in deps:   # lignes « Total », collectivités d'outre-mer : comptées dans index.json
            continue
        garde = {m: v for m, v in sorted(mois[dep].items()) if m.endswith("-12") or m == dernier}
        unedic[dep] = {"nom": deps.get(dep), "mois": garde}
    hors_unedic = sorted(set(mois) - set(deps))
    entete_u = {"millesime": f"mois de décembre 2018 à {int(dernier[:4]) - (0 if dernier.endswith('-12') else 1)}, et {dernier} ; collecte du {date}",
                "source": f"{JEUX['unedic']['page']} ({JEUX['unedic']['fiche']})"}
    sortie.mkdir(parents=True, exist_ok=True)
    dump(sortie / "departements.json", {**entete_u, "colonnes": cols, "dernier_mois": dernier, "departements": unedic})

    # Dares : inscrits ABC au 4e trimestre par commune
    par_dep = defaultdict(dict)
    annees, hors = set(), 0
    for trimestre, code, n in lire("dares", "select date, code_commune, nombre_de_demandeurs_d_emploi from {f} order by 2, 1"):
        if code not in communes:
            hors += 1
            continue
        a = str(trimestre)[:4]
        annees.add(a)
        par_dep[communes[code]].setdefault(code, {})[a] = num(n, 0)
    a = sorted(annees)
    entete_d = {"millesime": f"4e trimestre {a[0]} à {a[-1]} ; collecte du {date}",
                "source": f"{JEUX['dares']['page']} ({JEUX['dares']['fiche']})"}
    if (sortie / "communes").exists():
        for f in sorted((sortie / "communes").glob("*.json")):
            f.unlink()
    tailles = [dump(sortie / "communes" / f"{dep}.json", {**entete_d, "departement": dep, "annees": a,
                                                          "communes": {c: [v.get(x) for x in a] for c, v in sorted(par_dep[dep].items())}})
               for dep in sorted(deps)]
    sources = [{"id": k, "titre": j["titre"], "page": j["page"], "fiche": j["fiche"], "url": f"{j['api']}/exports/parquet",
                "licence": meta(k).get("licence") or "Licence Ouverte 2.0", "mise_a_jour_source": meta(k).get("modifie"),
                "lignes_source": meta(k).get("lignes")} for k, j in JEUX.items()]
    index = {"millesime": f"Unédic jusqu'à {dernier}, Dares 4e trimestre {a[0]} à {a[-1]} ; collecte du {date}",
             "source": " ; ".join(j["page"] for j in JEUX.values()),
             "presentation": ("Assurance chômage dans ton département et demandeurs d'emploi inscrits dans ta commune, "
                              "tels que publiés par l'Unédic et la Dares."),
             "definitions": DEFINITIONS, "colonnes_unedic": cols, "annees_dares": a, "dernier_mois_unedic": dernier,
             "secret_statistique": SECRET, "licence": "Licence Ouverte 2.0", "sources": sources,
             "couverture": {"departements_unedic": len(unedic), "departements_hors_cog": hors_unedic,
                            "communes_dares": sum(len(v) for v in par_dep.values()), "communes_cog": len(communes),
                            "lignes_dares_hors_cog": hors},
             "recherche_publique": RECHERCHE_PUBLIQUE,
             "fichiers": {"departements": "departements.json", "communes": "communes/<dep>.json"},
             "taille_max_octets": max(tailles)}
    dump(sortie / "index.json", index)
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
