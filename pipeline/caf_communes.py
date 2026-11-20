"""Prestations de la CAF par commune, intercommunalité, quartier (IRIS) et quartier prioritaire (QPV) : foyers
allocataires et montant versé au titre de décembre, par grande prestation, tels que publiés par la CNAF.

Entrées (réseau, `collecter`) : API Explore v2.1 de data.caf.fr (CNAF, Licence Ouverte 2.0), exports Parquet des
jeux « Toutes prestations - Répartition des allocataires selon la prestation » aux échelles communale (s_ben_com_f),
intercommunale (s_ben_epci_f), IRIS (s_ben_iris_f) et QPV (s_ben_qpv_f), colonnes retenues seulement, contrôlés par
collecte/integrite.py -> data/lake/caf_communes/<jeu>.parquet, meta_<jeu>.json.
Lecture seule : site/data/local/geo/<dep>.json (code officiel géographique en vigueur).
Sorties (site/data/caf_communes/, chaque fichier < 1 Mo) :
  index.json           prestations, définitions, secret statistique, couverture, sources
  communes/<dep>.json  par commune : [foyers, montant] par prestation et par année (Paris, Lyon, Marseille : par
                       arrondissement municipal, tel que publié, jamais additionnés) ; IRIS et QPV de la commune
                       (dernière année publiée) ; intercommunalités dont le siège est dans le département (dont
                       bénéficiaires de l'allocation aux adultes handicapés, publiés à cette échelle seulement)

Secret statistique de la source, respecté tel quel : foyers et personnes arrondis à 5 par la CNAF (7 devient 5),
petits effectifs non diffusés (valeur absente : null, jamais 0) ; la somme des communes ne redonne pas le total
départemental (écrit à l'écran). Montants : total versé au titre du mois de décembre (pas l'année), en euros, tels que
publiés. Aucun montant par foyer ni par habitant n'est calculé (règle 13).

Commandes :
  python pipeline/caf_communes.py collecter
  python pipeline/caf_communes.py produire [--sortie DOSSIER]
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
LAKE = ROOT / "data" / "lake" / "caf_communes"
GEO = ROOT / "site" / "data" / "local" / "geo"
OUT = ROOT / "site" / "data" / "caf_communes"
API = "https://data.caf.fr/api/explore/v2.1/catalog/datasets"
PAGE = "https://data.caf.fr/explore/dataset/{}/"
MAX_OCTETS = 1_000_000

PRESTATIONS = {
    "ndur": "Au moins une prestation légale (hors allocation de rentrée scolaire et aides ponctuelles)",
    "rsa": "Revenu de solidarité active (RSA)",
    "ppa": "Prime d'activité",
    "ndural": "Aides au logement (APL, ALF, ALS)",
    "apl": "Aide personnalisée au logement (APL)",
    "af": "Allocations familiales",
    "ndurpaje": "Prestation d'accueil du jeune enfant (PAJE)",
}
CHAMPS = [f"ind{t}_{p}" for p in PRESTATIONS for t in ("foy", "mtt")]
JEUX = {
    "com": {"id": "s_ben_com_f", "titre": "CNAF, « Toutes prestations - Répartition des allocataires selon la prestation [Communal] »",
            "select": "dtreffre,numcomdo," + ",".join(CHAMPS)},
    "epci": {"id": "s_ben_epci_f", "titre": "CNAF, « Toutes prestations - Répartition des allocataires selon la prestation [EPCI] »",
             "select": "dtreffre,numepci," + ",".join(CHAMPS) + ",indben_aah,indben_aeeh"},
    "iris": {"id": "s_ben_iris_f", "titre": "CNAF, « Toutes prestations - Répartition des allocataires selon la prestation [IRIS] »",
             "select": "dtreffre,numcomdo,numirisd,nomiris," + ",".join(CHAMPS)},
    "qpv": {"id": "s_ben_qpv_f", "titre": "CNAF, « Toutes prestations - Répartition des allocataires selon la prestation [QPV] »",
            "select": "dtreffre,numcomdo,numqp24,nomqpv," + ",".join(CHAMPS)},
}
SECRET = ("Foyers et personnes arrondis à 5 par la CNAF (7 devient 5, 12 devient 10) ; petits effectifs non "
          "diffusés (marqués « non diffusé », jamais remplacés par 0) ; la somme des communes ne redonne donc pas le total du département. Foyers "
          "localisés selon la géographie du 1er janvier suivant, sans recalcul des années antérieures.")
MONTANT = ("Montant total versé au titre du mois de décembre de l'année (et non sur l'année entière), en euros, tel "
           "que publié par la CNAF.")
AAH = ("L'allocation aux adultes handicapés (AAH) et l'allocation d'éducation de l'enfant handicapé (AEEH) ne sont "
       "publiées par la CNAF qu'à l'échelle de l'intercommunalité et au-dessus (nombre de bénéficiaires, sans montant) "
       ": rien par commune.")
RECHERCHE_PUBLIQUE = [
    {"trouvaille": "API Explore de data.caf.fr (jeux s_ben_* communal, EPCI, IRIS, QPV)", "classement": "réutilisable tel quel",
     "licence": "Licence Ouverte 2.0", "dernier_commit": None, "note": "client déjà utilisé par pipeline/prestations.py"},
    {"trouvaille": "rouages-de-la-france/rouages.fr (foyers CAF par commune)", "classement": "inspiration seulement",
     "licence": "non relevée", "dernier_commit": "2026-11-16"},
    {"trouvaille": "tawiza/tawiza (collecteur data.caf.fr)", "classement": "inspiration seulement",
     "licence": "non relevée", "dernier_commit": None},
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
            etat[cle] = local_satellites.telecharger(f"{API}/{j['id']}/exports/parquet", dest, {"select": j["select"]}, essais=8)
        for i in range(6):
            try:
                r = requests.get(f"{API}/{j['id']}", timeout=60, headers=local_satellites.ENTETE_HTTP)
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


def entier(v) -> int | None:
    if v is None:
        return None
    f = float(v)
    return None if f != f else int(round(f))


def lire(cle: str, sql: str) -> list[tuple]:
    import duckdb
    p = LAKE / f"{cle}.parquet"
    if not p.exists():
        raise SystemExit(f"{p} absent : lancer `python pipeline/caf_communes.py collecter`")
    return duckdb.connect().execute(sql.replace("{f}", f"'{p}'")).fetchall()


PLM = {"751": "75056", "6938": "69123", "132": "13055"}


def commune_mere(code: str) -> str | None:
    """Arrondissement municipal de Paris, Lyon ou Marseille -> commune (la CNAF publie par arrondissement)."""
    return next((m for pre, m in PLM.items() if code.startswith(pre) and code != m), None)


def valeurs(row) -> list:
    return [entier(x) for x in row]


def produire(sortie: Path = OUT) -> dict:
    import local
    communes, epci_dep = {}, {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for code, c in d["communes"].items():
            communes[code] = d["departement"]["code"]
        for s, e in d["epci"].items():
            epci_dep[s] = e.get("departement_siege")
    cols = ", ".join(CHAMPS)
    par_dep = defaultdict(lambda: {"communes": {}, "epci": {}})
    annees, hors = set(), defaultdict(int)
    for an, insee, *v in lire("com", f"select substr(cast(dtreffre as varchar), 1, 4), numcomdo, {cols} from {{f}} order by 1, 2"):
        mere = commune_mere(insee) if insee else None
        if mere:
            annees.add(an)
            c = par_dep[communes[mere]]["communes"].setdefault(mere, {"annees": {}})
            c.setdefault("arrondissements", {}).setdefault(insee, {})[an] = valeurs(v)
            continue
        if insee not in communes:
            hors["communes"] += 1
            continue
        annees.add(an)
        par_dep[communes[insee]]["communes"].setdefault(insee, {"annees": {}})["annees"][an] = valeurs(v)
    annees_epci = set()
    for an, siren, *v in lire("epci", f"select substr(cast(dtreffre as varchar), 1, 4), numepci, {cols}, indben_aah, indben_aeeh from {{f}} order by 1, 2"):
        dep = epci_dep.get(str(siren))
        if not dep:
            hors["epci"] += 1
            continue
        annees_epci.add(an)
        e = par_dep[dep]["epci"].setdefault(str(siren), {"annees": {}, "aah_aeeh": {}})
        e["annees"][an] = valeurs(v[:-2])
        e["aah_aeeh"][an] = valeurs(v[-2:])
    annees_iris, n_iris, noms_retires = set(), 0, 0
    for niveau, code_col, nom_col in (("iris", "numirisd", "nomiris"), ("qpv", "numqp24", "nomqpv")):
        for an, insee, code, nom, *v in lire(niveau, f"select substr(cast(dtreffre as varchar), 1, 4), numcomdo, {code_col}, {nom_col}, {cols} from {{f}} order by 1, 2, 3"):
            code = f"{insee}{code}" if niveau == "iris" and insee and len(str(code)) == 4 else code   # code IRIS complet
            insee = (commune_mere(insee) or insee) if insee else None
            if insee not in communes:
                hors[niveau] += 1
                continue
            annees_iris.add(an)
            nom_pub = local.objet_publiable(nom.title() if nom and nom.isupper() else nom) if nom else None
            noms_retires += bool(nom and not nom_pub)
            c = par_dep[communes[insee]]["communes"].setdefault(insee, {"annees": {}})
            c.setdefault(niveau, []).append([str(code), nom_pub, an, valeurs(v)])
            n_iris += niveau == "iris"
    try:
        date = json.loads((LAKE / "collecte.json").read_text(encoding="utf-8"))["collecte_le"]
    except (OSError, ValueError, KeyError):
        date = date_sources()
    a = sorted(annees)
    entete = {"millesime": f"décembre {a[0]} à décembre {a[-1]} (communes), décembre {max(annees_iris)} (IRIS, QPV) ; "
                           f"collecte du {date}",
              "source": " ; ".join(PAGE.format(j["id"]) for j in JEUX.values())}
    colonnes = [f"{p}_{t}" for p in PRESTATIONS for t in ("foyers", "montant_decembre")]
    if sortie.exists():
        for f in sorted((sortie / "communes").glob("*.json")):
            f.unlink()
    tailles = []
    for dep in sorted(set(communes.values())):
        p = par_dep.get(dep, {"communes": {}, "epci": {}})
        com = {}
        for insee in sorted(p["communes"]):
            c = p["communes"][insee]
            com[insee] = {"annees": dict(sorted(c["annees"].items())),
                          **{k: sorted(c[k], key=lambda x: (x[0], x[2])) for k in ("iris", "qpv") if k in c}}
            if "arrondissements" in c:
                com[insee]["arrondissements"] = {k: dict(sorted(v.items())) for k, v in sorted(c["arrondissements"].items())}
        epci = {s: {"annees": dict(sorted(e["annees"].items())), "aah_aeeh": dict(sorted(e["aah_aeeh"].items()))}
                for s, e in sorted(p["epci"].items())}
        tailles.append(dump(sortie / "communes" / f"{dep}.json", {**entete, "departement": dep, "colonnes": colonnes,
                                                                   "colonnes_quartier": ["code", "nom", "annee", "valeurs"],
                                                                   "colonnes_aah_aeeh": ["aah_beneficiaires", "aeeh_beneficiaires"],
                                                                   "communes": com, "epci": epci}))
    sources = []
    for k, j in JEUX.items():
        try:
            m = json.loads((LAKE / f"meta_{k}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            m = {}
        sources.append({"id": k, "jeu": j["id"], "titre": j["titre"], "page": PAGE.format(j["id"]),
                        "url": f"{API}/{j['id']}/exports/parquet", "licence": m.get("licence") or "Licence Ouverte 2.0",
                        "mise_a_jour_source": m.get("modifie"), "lignes_source": m.get("lignes")})
    n_com = sum(len(p["communes"]) for p in par_dep.values())
    index = {**entete, "presentation": ("Combien de foyers de la commune touchent une prestation de la CAF, et le montant "
                                        "versé au titre de décembre, tels que publiés par la CNAF."),
             "annees": a, "annees_epci": sorted(annees_epci), "annees_quartiers": sorted(annees_iris),
             "prestations": PRESTATIONS, "colonnes": colonnes, "secret_statistique": SECRET, "montant": MONTANT,
             "aah": AAH, "licence": "Licence Ouverte 2.0", "sources": sources,
             "couverture": {"communes_cog": len(communes), "communes_publiees": n_com, "iris": n_iris,
                            "noms_quartier_retires": noms_retires, "hors_cog": dict(sorted(hors.items()))},
             "recherche_publique": RECHERCHE_PUBLIQUE, "fichiers": {"communes": "communes/<dep>.json"},
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
