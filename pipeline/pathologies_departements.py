"""Patients pris en charge par pathologie et par département (Assurance maladie, tous régimes), effectifs agrégés.

Entrée (réseau, `collecter`) : data.ameli.fr, jeu `effectifs` (Cnam, « Pathologies : effectif de patients par
pathologie, sexe, classe d'âge et territoire », base sous licence ODbL 1.0, fiche data.gouv.fr
pathologies-effectif-de-patients-par-pathologie-sexe-classe-dage-et-territoire-departement-region), export Parquet
filtré côté serveur (tous âges, tous sexes, groupes de pathologies de niveaux 1 et 2), contrôlé par
collecte/integrite.py -> data/lake/pathologies_departements/effectifs.parquet, meta.json.
Lecture seule : site/data/local/geo/<dep>.json (noms des départements).
Sortie (site/data/pathologies_departements/, sous ODbL 1.0, partage à l'identique) :
  index.json           pathologies (libellés et ordre de la source), définitions, licence, couverture, sources
  departements.json    par département et par année : [patients, prévalence en %] pour chaque groupe de
                       pathologies (première ligne : population de référence, prévalence null)

Règles : effectifs, population et prévalence publiés par la Cnam, repris tels quels (aucun calcul du site) ; ordre
d'affichage = colonne `tri` de la source (ordre de présentation de la Cnam, pas un classement) ; jamais rapprochés
par le site des dépenses par pathologie (nationales) déjà publiées : aucun montant par département n'est déduit.

Commandes :
  python pipeline/pathologies_departements.py collecter
  python pipeline/pathologies_departements.py produire [--sortie DOSSIER]
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
LAKE = ROOT / "data" / "lake" / "pathologies_departements"
GEO = ROOT / "site" / "data" / "local" / "geo"
OUT = ROOT / "site" / "data" / "pathologies_departements"
API = "https://data.ameli.fr/api/explore/v2.1/catalog/datasets/effectifs"
PAGE = "https://data.ameli.fr/explore/dataset/effectifs/"
FICHE = ("https://www.data.gouv.fr/datasets/pathologies-effectif-de-patients-par-pathologie-sexe-classe-dage-et-"
         "territoire-departement-region")
MAX_OCTETS = 1_000_000
PARAMS = {"select": "annee,dept,patho_niv1,patho_niv2,patho_niv3,top,ntop,npop,prev,niveau_prioritaire,tri",
          "where": 'cla_age_5="tsage" and sexe="9" and dept != "999"'}
LICENCE = {"licence": "ODbL 1.0", "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
           "mention": ("Contient des données de la Caisse nationale de l'Assurance maladie (data.ameli.fr), mises à "
                       "disposition sous licence ODbL 1.0 ; ce fichier dérivé est diffusé sous la même licence "
                       "(mention de la source, partage à l'identique).")}
DEFINITIONS = {
    "patients": "Nombre de patients pris en charge pour la pathologie, le traitement ou l'épisode de soins dans l'année (tous régimes)",
    "population": "Population de référence : personnes ayant consommé des soins remboursés dans l'année (pour certains groupes, un seul sexe)",
    "prevalence": "Prévalence publiée par la Cnam : patients rapportés à la population de référence, en %",
}
RECHERCHE_PUBLIQUE = [
    {"trouvaille": "data.ameli.fr, jeu effectifs (API Explore)", "classement": "réutilisable tel quel", "licence": "ODbL 1.0",
     "dernier_commit": None, "note": "même hôte que pipeline/assurance_maladie_territoires.py"},
    {"trouvaille": "Cnam, application « Data pathologies »", "classement": "inspiration seulement", "licence": "ODbL 1.0",
     "dernier_commit": None},
]


def collecter(forcer: bool = False) -> dict:
    import local_satellites
    import requests
    LAKE.mkdir(parents=True, exist_ok=True)
    dest = LAKE / "effectifs.parquet"
    etat = "présent" if dest.exists() and dest.stat().st_size and not forcer else \
        local_satellites.telecharger(f"{API}/exports/parquet", dest, PARAMS, essais=8)
    for i in range(6):
        try:
            r = requests.get(API, timeout=60, headers=local_satellites.ENTETE_HTTP)
            if r.status_code in (401, 403, 429):
                break
            m = r.json()["metas"]["default"]
            (LAKE / "meta.json").write_text(json.dumps({"licence": m.get("license"), "modifie": (m.get("modified") or "")[:10],
                                                        "lignes": m.get("records_count"),
                                                        "collecte_le": time.strftime("%Y-%m-%d", time.gmtime())},
                                                       sort_keys=True), encoding="utf-8")
            break
        except Exception:
            time.sleep(4 * (i + 1))
    return {"effectifs": etat}


def num(v, chiffres=3):
    if v is None:
        return None
    f = float(v)
    if f != f:
        return None
    r = round(f, chiffres)
    return int(r) if r == int(r) else r


def produire(sortie: Path = OUT) -> dict:
    import duckdb
    p = LAKE / "effectifs.parquet"
    if not p.exists():
        raise SystemExit(f"{p} absent : lancer `python pipeline/pathologies_departements.py collecter`")
    deps = {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        deps[d["departement"]["code"]] = d["departement"]["nom"]
    lignes = duckdb.connect().execute(f"""select year(cast(annee as date)), dept, patho_niv1, patho_niv2, patho_niv3, top,
        ntop, npop, prev, cast(niveau_prioritaire as varchar), tri from '{p}' order by 1, 2, 11, 6""").fetchall()
    pathologies, valeurs, annees, hors = {}, defaultdict(lambda: defaultdict(dict)), set(), set()
    for an, dep, n1, n2, n3, top, ntop, npop, prev, niv, tri in lignes:
        niveaux = niv or ""
        if top == "POP_TOT_IND":
            niveau = 0
        elif "1" in niveaux and (n2 is None or n2 == n1):
            niveau = 1
        elif "2" in niveaux and (n3 is None or n3 == n2):
            niveau = 2
        else:
            continue
        dep = str(dep)
        if dep not in deps:
            hors.add(dep)
            continue
        libelle = n1 if niveau <= 1 else n2
        pathologies.setdefault(top, {"libelle": libelle, "groupe": n1, "niveau": niveau, "ordre": num(tri, 0)})
        annees.add(str(an))
        valeurs[dep][str(an)][top] = [num(ntop, 0), num(prev)] if niveau else [num(ntop, 0), None]
    if not annees:
        raise SystemExit("aucune ligne lue dans effectifs.parquet")
    ordre = sorted(pathologies, key=lambda t: (pathologies[t]["niveau"] != 0, pathologies[t]["ordre"] if pathologies[t]["ordre"] is not None else 999, t))
    try:
        meta = json.loads((LAKE / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    date = meta.get("collecte_le") or date_sources()
    a = sorted(annees)
    entete = {"millesime": f"années {a[0]} à {a[-1]} (cartographie des pathologies) ; collecte du {date}",
              "source": f"Cnam, data.ameli.fr, « Pathologies : effectif de patients » : {PAGE} ({FICHE})", **LICENCE}
    out = {dep: {"nom": deps[dep], "annees": {an: [valeurs[dep][an].get(t) for t in ordre] for an in sorted(valeurs[dep])}}
           for dep in sorted(valeurs)}
    sortie.mkdir(parents=True, exist_ok=True)
    texte = json.dumps({**entete, "pathologies": ordre, "colonnes": ["patients", "prevalence"],
                        "departements": out}, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > MAX_OCTETS:
        raise SystemExit(f"departements.json dépasse {MAX_OCTETS} octets ({len(texte.encode())})")
    (sortie / "departements.json").write_text(texte + "\n", encoding="utf-8")
    index = {**entete, "presentation": ("Combien de personnes de ton département sont soignées pour un diabète, un cancer, "
                                        "une maladie cardiovasculaire..., telles que publiées par l'Assurance maladie."),
             "annees": a, "pathologies": {t: pathologies[t] for t in ordre}, "ordre": ordre, "definitions": DEFINITIONS,
             "regle": ("Aucun montant par département n'est déduit des dépenses nationales par pathologie : la source "
                       "ne les publie pas à cette échelle."),
             "sources": [{"titre": "Cnam, « Pathologies : effectif de patients par pathologie, sexe, classe d'âge et territoire »",
                          "page": PAGE, "fiche": FICHE, "url": f"{API}/exports/parquet", "licence": "ODbL 1.0",
                          "mise_a_jour_source": meta.get("modifie"), "lignes_source": meta.get("lignes")}],
             "couverture": {"departements": len(out), "codes_hors_cog": sorted(hors), "pathologies": len(ordre)},
             "recherche_publique": RECHERCHE_PUBLIQUE, "fichiers": {"departements": "departements.json"}}
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
