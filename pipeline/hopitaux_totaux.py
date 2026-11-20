"""Comptes des hôpitaux publics et privés à but non lucratif : totaux publiés par l'ATIH (2020 à 2024).

Source : ATIH, indicateurs de suivi financier, jeu « isf-finance-ebnl-public-tot » (data-essentiel.atih.sante.fr,
ODbL 1.0), identifiant `secu_atih_finances_ebnl_tot` de collecte/catalogue.json. Le jeu donne, pour chaque exercice,
les lignes par secteur, catégorie et activité principale déjà publiées par pipeline/sante_etablissements.py
(sante_etablissements/finances_agregees.json, jeu « isf-finance-ebnl-public ») et, en plus, les totaux calculés par
l'ATIH (secteur, catégorie ou activité « TOT »). Ce module ne publie que ces lignes de total : ce sont des totaux de
la source, le site n'additionne rien (règle 13). Le taux de capacité d'autofinancement est celui de l'ATIH.

Agrégats : aucun établissement identifié. Licence ODbL : les données dérivées gardent cette licence et la mention de
l'ATIH. Une valeur absente reste null, jamais 0.

Commandes :
  python pipeline/hopitaux_totaux.py collecter   # réseau : collecte/collecte.py secu_atih_finances_ebnl_tot
  python pipeline/hopitaux_totaux.py produire    # sans réseau -> site/data/hopitaux_totaux/
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ID = "secu_atih_finances_ebnl_tot"
PARQUET = ROOT / "data" / "lake" / "secu" / f"{ID}.parquet"
SORTIE_DEFAUT = ROOT / "site" / "data" / "hopitaux_totaux"
PAGE = "https://data-essentiel.atih.sante.fr/explore/dataset/isf-finance-ebnl-public-tot/"
LICENCE = "ODbL 1.0"
SOURCE = ("ATIH, indicateurs de suivi financier : données financières des établissements publics ou à but non "
          "lucratif, totaux (data-essentiel.atih.sante.fr, isf-finance-ebnl-public-tot), ODbL 1.0 : " + PAGE)

MESURES = [  # (clé publiée, colonne ATIH, libellé)
    ("etablissements", "nb_es", "Nombre d'établissements"),
    ("produits_eur", "realn_prtot", "Total des produits"),
    ("charges_eur", "realtot_chtot", "Total des charges du compte de résultat principal"),
    ("charges_personnel_eur", "realtot_ct1", "Titre 1 : charges de personnel du compte de résultat principal"),
    ("resultat_principal_eur", "realn_excdef", "Résultat principal"),
    ("capacite_autofinancement_eur", "realn_ciaf", "Capacité d'autofinancement"),
    ("encours_dette_eur", "exercn_encoursdette", "Encours de la dette"),
    ("taux_caf_pct", "tx_caf", "Taux de capacité d'autofinancement (en % des produits, calculé par l'ATIH)"),
]
SECTEURS = {"TOT": "Ensemble (public et privé à but non lucratif)", "public": "Public",
            "privé à but non lucratif": "Privé à but non lucratif"}

RECHERCHE_PUBLIQUE = [
    {"trouvaille": "ATIH, isf-finance-ebnl-public-tot", "verdict": "réutilisable tel quel", "licence": LICENCE,
     "date": "exercices 2020 à 2024"},
    {"trouvaille": "ATIH, isf-finance-ebnl-public (déjà repris : sante_etablissements/finances_agregees.json)",
     "verdict": "réutilisable tel quel", "licence": LICENCE, "date": "mêmes lignes de détail, sans les totaux"},
    {"trouvaille": "ATIH, Hospi Diag (déjà repris jusqu'en 2015)", "verdict": "inspiration seulement",
     "licence": "Licence Ouverte 2.0", "date": "par établissement, arrêté en 2015"},
]


def valeur(v, cle: str):
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x):
        return None
    return round(x, 2) if cle == "taux_caf_pct" else int(round(x))


def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    if not PARQUET.exists():
        raise SystemExit(f"{PARQUET} absent : lancer python pipeline/hopitaux_totaux.py collecter")
    import pyarrow.parquet as pq
    lignes = pq.read_table(PARQUET).to_pylist()
    garde = []
    for r in lignes:
        if "TOT" not in (r["secteur"], r["categorie"], r["activite_principale"]):
            continue   # ligne de détail : déjà publiée par sante_etablissements
        garde.append([int(r["annee"]), r["secteur"], r["categorie"], r["activite_principale"],
                      *[valeur(r.get(col), k) for k, col, _ in MESURES]])
    garde.sort(key=lambda x: (x[0], x[1] != "TOT", x[1], x[2] != "TOT", x[2], x[3] != "TOT", x[3]))
    annees = sorted({x[0] for x in garde})
    obj = {
        "millesime": f"exercices {annees[0]} à {annees[-1]}", "source": SOURCE,
        "date_sources": date_sources("secu"), "licence": LICENCE, "page_source": PAGE,
        "presentation": "Comptes des hôpitaux publics et des établissements privés à but non lucratif : totaux par "
                        "secteur, par catégorie et par activité, tels que l'ATIH les publie.",
        "unite": "euros, sauf nombre d'établissements et taux (%)",
        "definitions": {k: lib for k, _c, lib in MESURES} | {
            "TOT": "total publié par l'ATIH pour cette dimension",
            "activite_principale": "champ d'activité principale (au moins 80 % de l'activité, sinon « mixte ») : "
                                   "mco médecine, chirurgie, obstétrique ; smr soins médicaux et de réadaptation ; "
                                   "psy psychiatrie ; had hospitalisation à domicile"},
        "secteurs": SECTEURS,
        "colonnes": ["annee", "secteur", "categorie", "activite_principale", *[k for k, *_ in MESURES]],
        "lignes": garde,
        "regles": ["Seules les lignes de total publiées par l'ATIH sont reprises ; le site n'additionne aucune ligne.",
                   "Le détail par secteur, catégorie et activité est publié dans sante_etablissements, à part.",
                   "Une valeur absente est publiée null, jamais 0."],
        "limites": ["Les cliniques privées à but lucratif ne sont pas dans ce jeu.",
                    "Aucun établissement n'est identifié : agrégats seulement."],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "ordre": "année, puis total avant le détail de chaque dimension",
    }
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "index.json").write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n",
                                       encoding="utf-8")
    return obj


def collecter() -> int:
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), ID])


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
        o = produire(a.sortie)
        print(f"hopitaux_totaux : {len(o['lignes'])} lignes de total", file=sys.stderr)


if __name__ == "__main__":
    main()
