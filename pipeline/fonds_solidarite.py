"""Fonds de solidarité aux entreprises (Covid-19, 2020 à 2022) : agrégats par département, région, secteur et mois.

Source : Etalab et DGFiP, jeu « Données relatives au fonds de solidarité mis en place dans le cadre de l'épidémie de
COVID-19 » (data.gouv.fr 5e9dbdbe71589194c8f7b42f, Licence Ouverte 2.0), identifiant `aides_fonds_solidarite` de
collecte/catalogue.json. Les fichiers « latest » donnent le dernier état publié (instantané du 24/06/2022 pour le volet
1, du 10/12/2021 pour le volet 2) ; l'historique quotidien publié par Etalab avec le jeu (ressource « Historique des
données du fonds de solidarité », dépôt etalab/dashboard-aides-entreprises, dossier published-data/fonds-solidarite,
dépôt figé depuis juin 2022) donne l'instantané de la fin de chaque mois.

Ce qui est publié (aucun bénéficiaire nommé : la source n'en publie pas) :
  - par département et section d'activité (NAF), par catégorie juridique, par classe d'effectif : nombre d'aides,
    nombre d'entreprises, montant cumulé, au dernier instantané du volet 1 ;
  - par région et section d'activité, pour chaque fin de mois : les cumuls tels que publiés à cette date (volet 1 et
    volet 2). Ce sont des cumuls depuis le début du dispositif ; le site ne calcule pas de montant par mois (règle 13).
Beaucoup de bénéficiaires sont des entrepreneurs individuels (catégorie juridique 1000) : ils ne sont jamais nommés ;
la source ne publie que des agrégats, repris tels quels. Une valeur absente reste null, jamais 0.

Ce qui manque à la source : le détail par commune et la liste des bénéficiaires ne sont pas publiés ; le volet 2
(aide des régions) n'est publié que par région.

Commandes :
  python pipeline/fonds_solidarite.py collecter   # réseau : collecte/collecte.py aides_fonds_solidarite, puis
                                                  # instantanés de fin de mois (raw.githubusercontent.com)
  python pipeline/fonds_solidarite.py produire    # sans réseau -> site/data/fonds_solidarite/
Sorties identiques octet pour octet sur le même entrepôt (tris explicites, date par pipeline/reproductible.py).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "collecte"))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
DOSSIER_LATEST = LAKE / "aides_entreprises" / "aides_fonds_solidarite"
HISTO = LAKE / "fonds_solidarite" / "historique"
SORTIE_DEFAUT = ROOT / "site" / "data" / "fonds_solidarite"
ID = "aides_fonds_solidarite"
MAX_OCTETS = 1_000_000
LICENCE = "Licence Ouverte 2.0"

PAGE = ("https://www.data.gouv.fr/datasets/donnees-relatives-au-fonds-de-solidarite-mis-en-place-dans-le-cadre-de-"
        "lepidemie-de-covid-19")
DEPOT = "https://github.com/etalab/dashboard-aides-entreprises/tree/master/published-data/fonds-solidarite"
RAW = "https://raw.githubusercontent.com/etalab/dashboard-aides-entreprises/master/published-data/fonds-solidarite"
SOURCE = ("Etalab et DGFiP, « Données relatives au fonds de solidarité mis en place dans le cadre de l'épidémie de "
          "COVID-19 », data.gouv.fr (Licence Ouverte 2.0), fichiers « latest » et ressource « Historique des données "
          "du fonds de solidarité » : " + PAGE)

# Dernier instantané quotidien de chaque mois dans l'historique Etalab (relevé de l'arborescence du dépôt le
# 20/11/2026 ; dépôt figé depuis le 29/06/2022). Le dernier est celui des fichiers « latest » du volet 1.
INSTANTANES = [
    "2020-05-31", "2020-06-30", "2020-07-31", "2020-08-31", "2020-09-30", "2020-10-31", "2020-11-30", "2020-12-31",
    "2021-01-31", "2021-02-28", "2021-03-31", "2021-04-30", "2021-05-31", "2021-06-30", "2021-07-30", "2021-08-30",
    "2021-09-30", "2021-10-29", "2021-11-30", "2021-12-31", "2022-01-31", "2022-02-28", "2022-03-31", "2022-04-21",
    "2022-05-31", "2022-06-24",
]
DERNIER_VOLET1 = "2022-06-24"
DERNIER_VOLET2 = "2021-12-10"
HISTO_FICHIERS = {"1": "fonds-solidarite-volet-1-regional-naf-latest.csv",
                  "2": "fonds-solidarite-volet-2-regional-naf-latest.csv"}
LATEST = {  # préfixe du fichier collecté -> clé
    "departements_naf": "fonds-solidarite-volet-1-departemental-naf-latest",
    "departements_categorie": "fonds-solidarite-volet-1-departemental-categorie-juridique",
    "departements_effectif": "fonds-solidarite-volet-1-departemental-classe-effectif",
}

RECHERCHE_PUBLIQUE = [
    {"trouvaille": "Etalab et DGFiP, jeu data.gouv.fr du fonds de solidarité (fichiers « latest »)",
     "verdict": "réutilisable tel quel", "licence": LICENCE, "date": "dernier instantané : 24/06/2022 (volet 1)"},
    {"trouvaille": "etalab/dashboard-aides-entreprises, dossier published-data/fonds-solidarite (historique "
                   "quotidien, ressource du même jeu)", "verdict": "réutilisable tel quel",
     "licence": "Licence Ouverte 2.0 (ressource du jeu data.gouv.fr)", "date": "dernier commit le 29/06/2022"},
    {"trouvaille": "etalab/dashboard-aides-entreprises (code du tableau de bord aides-entreprises.data.gouv.fr)",
     "verdict": "inspiration seulement", "licence": "MIT", "date": "dernier commit le 29/06/2022 ; Nuxt, non repris"},
    {"trouvaille": "Cour des comptes, rapports sur le fonds de solidarité (2021, 2023)", "verdict": "inspiration seulement",
     "licence": "réutilisation libre avec mention", "date": "chiffres en PDF, non repris"},
]


def nombre(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")
    if s == "" or s.lower() in ("nan", "nc", "s"):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return int(round(x))


NON_RENSEIGNE = ("NR", "Non renseigné dans la source")


def lire_csv(octets_ou_chemin) -> list[dict]:
    if isinstance(octets_ou_chemin, Path):
        octets = octets_ou_chemin.read_bytes()
    else:
        octets = octets_ou_chemin
    txt = octets.decode("utf-8-sig", "replace")
    lignes = list(csv.DictReader(io.StringIO(txt)))
    for r in lignes:   # code de section, catégorie ou classe vide dans la source : « NR », jamais reclassé
        for code, lib in (("code_section", "libelle_section"), ("code_categorie_juridique", "libelle_categorie_juridique"),
                          ("classe_effectif", "libelle_classe_effectif")):
            if code in r and not (r[code] or "").strip():
                r[code], r[lib] = NON_RENSEIGNE
    return lignes


def fichier_latest(prefixe: str) -> Path:
    c = sorted(DOSSIER_LATEST.glob(prefixe + "*.csv"))
    if not c:
        raise SystemExit(f"{DOSSIER_LATEST}/{prefixe}*.csv absent : lancer python pipeline/fonds_solidarite.py collecter")
    return c[-1]


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(txt.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets : à découper")
    path.write_text(txt + "\n", encoding="utf-8")
    return n


# --------------------------------------------------------------------------------------------------------------
# Collecte (réseau)
# --------------------------------------------------------------------------------------------------------------

def telecharger_instantane(date: str, volet: str) -> str:
    """Un fichier de l'historique ; contrôle d'intégrité avant le renommage. Renvoie le statut."""
    import requests
    from integrite import remplacer_si_valide
    dest = HISTO / date / HISTO_FICHIERS[volet]
    if dest.exists():
        return "present"
    url = f"{RAW}/fds-{date}/{HISTO_FICHIERS[volet]}"
    for i in range(1, 5):
        try:
            r = requests.get(url, timeout=120, headers={"User-Agent": "ou-vont-mes-impots (collecte open data)"})
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(3 * i)
            continue
        if r.status_code in (401, 403, 429):
            return f"refus HTTP {r.status_code} (non contourné)"
        if r.status_code == 404:
            return "absent de l'instantané"
        if r.status_code >= 400:
            time.sleep(3 * i)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".csv.part")
        tmp.write_bytes(r.content)
        remplacer_si_valide(tmp, dest, nom=dest.name)
        return "ok"
    return "échec réseau"


def collecter() -> int:
    rc = subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), ID])
    journal = {}
    for d in INSTANTANES:
        for v in HISTO_FICHIERS:
            journal[f"{d}/volet{v}"] = telecharger_instantane(d, v)
    HISTO.mkdir(parents=True, exist_ok=True)
    (HISTO / "journal.json").write_text(json.dumps(journal, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                        encoding="utf-8")
    print(f"  instantanés : {sum(1 for x in journal.values() if x in ('ok', 'present'))}/{len(journal)}",
          file=sys.stderr)
    return rc


# --------------------------------------------------------------------------------------------------------------
# Production (sans réseau)
# --------------------------------------------------------------------------------------------------------------

def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    date = date_sources("aides_entreprises", "fonds_solidarite")
    sections, regions, departements, categories, classes, region_de = {}, {}, {}, {}, {}, {}

    def ligne(r, cle_code, cle_lib, dico):
        dico[r[cle_code]] = r[cle_lib]
        return [nombre(r.get("nombre_aides")), nombre(r.get("nombre_entreprises")), nombre(r.get("montant_total"))]

    def geo(r):
        regions[r["reg"]] = r["libelle_region"]
        if r.get("dep"):
            departements[r["dep"]] = r["libelle_departement"]
            region_de[r["dep"]] = r["reg"]

    naf, cat, eff = [], [], []
    for r in lire_csv(fichier_latest(LATEST["departements_naf"])):
        geo(r)
        naf.append([r["dep"], r["code_section"], *ligne(r, "code_section", "libelle_section", sections)])
    for r in lire_csv(fichier_latest(LATEST["departements_categorie"])):
        geo(r)
        cat.append([r["dep"], r["code_categorie_juridique"],
                    *ligne(r, "code_categorie_juridique", "libelle_categorie_juridique", categories)])
    for r in lire_csv(fichier_latest(LATEST["departements_effectif"])):
        geo(r)
        eff.append([r["dep"], r["classe_effectif"], *ligne(r, "classe_effectif", "libelle_classe_effectif", classes)])
    for t in (naf, cat, eff):
        t.sort(key=lambda x: (x[0], x[1]))

    mois, manquants = [], []
    for d in INSTANTANES:
        for v, nom in HISTO_FICHIERS.items():
            f = HISTO / d / nom
            if not f.exists():
                manquants.append(f"{d} volet {v}")
                continue
            for r in lire_csv(f):
                geo(r)
                mois.append([d, int(v), r["reg"], r["code_section"],
                             *ligne(r, "code_section", "libelle_section", sections)])
    mois.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    colonnes = ["nombre_aides", "nombre_entreprises", "montant_eur"]
    entete = {"millesime": f"fonds de solidarité 2020 à 2022, volet 1 au {DERNIER_VOLET1}",
              "source": SOURCE, "date_sources": date}
    n_dep = dump(sortie / "departements.json", {
        **entete, "unite": "euros (montants cumulés depuis le début du dispositif)", "instantane": DERNIER_VOLET1,
        "volet": 1,
        "par_section": {"colonnes": ["departement", "section", *colonnes], "lignes": naf},
        "par_categorie_juridique": {"colonnes": ["departement", "categorie_juridique", *colonnes], "lignes": cat},
        "par_classe_effectif": {"colonnes": ["departement", "classe_effectif", *colonnes], "lignes": eff},
    })
    n_mois = dump(sortie / "regions_mois.json", {
        **entete, "millesime": f"fonds de solidarité, instantanés de fin de mois du {INSTANTANES[0]} au "
                              f"{INSTANTANES[-1]}",
        "unite": "euros (cumuls publiés à chaque date, depuis le début du dispositif)",
        "colonnes": ["instantane", "volet", "region", "section", *colonnes], "lignes": mois,
    })
    index = {
        **entete,
        "licence": LICENCE, "page_source": PAGE, "historique": DEPOT,
        "presentation": "Aides du fonds de solidarité versées aux petites entreprises, indépendants et "
                        "micro-entrepreneurs touchés par la crise sanitaire (2020 à 2022) : nombre d'aides, nombre "
                        "d'entreprises aidées et montants, par département, secteur d'activité, forme juridique, "
                        "taille et fin de mois, tels que publiés par l'État.",
        "volets": {"1": "volet 1 : aide versée par la DGFiP (État), publiée par département",
                   "2": "volet 2 : aide complémentaire instruite par les régions, publiée par région"},
        "instantanes": {"volet1_dernier": DERNIER_VOLET1, "volet2_dernier": DERNIER_VOLET2,
                        "fins_de_mois": INSTANTANES, "manquants": manquants},
        "sections": dict(sorted(sections.items())),
        "categories_juridiques": dict(sorted(categories.items())),
        "classes_effectif": dict(sorted(classes.items())),
        "regions": dict(sorted(regions.items())),
        "departements": dict(sorted(departements.items())),
        "region_des_departements": dict(sorted(region_de.items())),
        "couverture": {"lignes_departement_section": len(naf), "lignes_departement_categorie": len(cat),
                       "lignes_departement_effectif": len(eff), "lignes_regions_mois": len(mois),
                       "departements": len({x[0] for x in naf})},
        "fichiers": {"departements": {"chemin": "fonds_solidarite/departements.json", "octets": n_dep},
                     "regions_mois": {"chemin": "fonds_solidarite/regions_mois.json", "octets": n_mois}},
        "manques": [{
            "quoi": "Les aides du fonds de solidarité par commune et par entreprise aidée.",
            "pourquoi": "L'État publie ce dispositif seulement en agrégats par département ou par région. Beaucoup "
                        "d'entreprises aidées sont des entrepreneurs individuels : le site ne nomme aucune entreprise "
                        "et ne reconstitue pas de liste.",
            "depuis": f"Toute la durée du dispositif (2020 à 2022) ; constat de la collecte du {date}.",
            "source": {"libelle": "Fonds de solidarité, data.gouv.fr", "url": PAGE},
        }, {
            "quoi": "Le montant versé au cours de chaque mois.",
            "pourquoi": "Les fichiers publiés donnent des cumuls depuis le début du dispositif, à la date de chaque "
                        "fichier. Le site publie ces cumuls à la fin de chaque mois et ne calcule pas de différence "
                        "entre deux dates.",
            "depuis": f"Historique quotidien publié du {INSTANTANES[0]} au {INSTANTANES[-1]}.",
            "source": {"libelle": "Historique des données du fonds de solidarité, data.gouv.fr", "url": PAGE},
        }],
        "regles": [
            "Montants, nombres d'aides et d'entreprises repris tels que publiés (euros), à la date de chaque fichier.",
            "Aucune entreprise n'est nommée : la source ne publie que des agrégats.",
            "Deux fichiers de dates différentes ne sont jamais additionnés ni comparés par différence.",
            "Le volet 1 (État) et le volet 2 (régions) sont publiés séparément, jamais additionnés.",
            "Une valeur absente est publiée null, jamais 0 (les premiers fichiers ne donnent pas le nombre "
            "d'entreprises).",
        ],
        "limites": [
            "Le département est celui de l'entreprise aidée tel que retenu par la DGFiP ; une entreprise à "
            "plusieurs établissements est comptée une fois.",
            "Une même entreprise a pu recevoir plusieurs aides (une par mois éligible) : le nombre d'aides dépasse "
            "le nombre d'entreprises.",
            "Le volet 2 n'est publié que jusqu'au 10/12/2021 et seulement par région.",
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "ordre": "départements par code ; sections, catégories et classes par code ; instantanés par date",
    }
    dump(sortie / "index.json", index)
    return index


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        rc = collecter()
        if rc:
            raise SystemExit(rc)
    if a.etape in ("produire", "tout"):
        i = produire(a.sortie)
        c = i["couverture"]
        print(f"fonds_solidarite : {c['departements']} départements, {c['lignes_regions_mois']} lignes région x mois",
              file=sys.stderr)


if __name__ == "__main__":
    main()
