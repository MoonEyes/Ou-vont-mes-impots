"""Activité partielle (chômage partiel) en 2020 : demandes déposées par les employeurs, par région et secteur.

Source : Etalab, tableau de bord des aides aux entreprises, ressource « activite-partielle-regional-nace17-latest »
(data.gouv.fr, ressource cb195a3c-d8a1-4887-a464-d0497842d069, Licence Ouverte 2.0 ; données du ministère du Travail),
identifiant `aides_activite_partielle` de collecte/catalogue.json. Fichier arrêté au 27/10/2020 (date_maj publiée).

Ce sont des demandes d'autorisation préalable déposées par les employeurs (nombre de demandes, salariés concernés,
heures demandées), pas des heures réellement indemnisées ni des montants versés : les montants et heures indemnisées
publiés par l'Unédic, l'Urssaf et la Dares sont dans site/data/emploi/activite_partielle.json (pipeline/emploi.py),
jamais additionnés ni comparés par différence à ces demandes. Agrégats seulement : aucun employeur nommé.

Commandes :
  python pipeline/activite_partielle_demandes.py collecter   # réseau : collecte/collecte.py aides_activite_partielle
  python pipeline/activite_partielle_demandes.py produire    # sans réseau -> site/data/activite_partielle_demandes/
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "data" / "lake" / "aides_entreprises" / "aides_activite_partielle"
SORTIE_DEFAUT = ROOT / "site" / "data" / "activite_partielle_demandes"
ID = "aides_activite_partielle"
LICENCE = "Licence Ouverte 2.0"
PAGE = "https://www.data.gouv.fr/fr/datasets/r/cb195a3c-d8a1-4887-a464-d0497842d069"
URL = ("https://raw.githubusercontent.com/etalab/dashboard-aides-entreprises/master/published-data/"
       "activite-partielle-regional-nace17-latest.csv")
SOURCE = ("Etalab et ministère du Travail, demandes d'activité partielle par région et secteur (NACE en 17 postes), "
          "tableau de bord des aides aux entreprises, ressource data.gouv.fr, Licence Ouverte 2.0 : " + PAGE)

RECHERCHE_PUBLIQUE = [
    {"trouvaille": "Etalab, activite-partielle-regional-nace17-latest (ressource data.gouv.fr)",
     "verdict": "réutilisable tel quel", "licence": LICENCE, "date": "fichier arrêté au 27/10/2020, dépôt figé en 2022"},
    {"trouvaille": "Dares, séries mensuelles de l'activité partielle (heures indemnisées, montants)",
     "verdict": "inspiration seulement", "licence": LICENCE,
     "date": "déjà noté dans pipeline/emploi.py ; autre mesure (indemnisé), non mêlée"},
    {"trouvaille": "site/data/emploi/activite_partielle.json (Unédic, Urssaf)", "verdict": "réutilisable tel quel",
     "licence": "Licence Ouverte 2.0, ODbL", "date": "dépôt ; publié à part, lien depuis l'écran"},
]


def nombre(v):
    s = (v or "").strip().replace(",", ".")
    if s == "" or s.lower() in ("nan", "nc", "s"):
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def fichier() -> Path:
    c = sorted(DOSSIER.glob("activite-partielle-regional-nace17-latest*.csv"))
    if not c:
        raise SystemExit(f"{DOSSIER} vide : lancer python pipeline/activite_partielle_demandes.py collecter")
    return c[-1]


def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    lignes = list(csv.DictReader(io.StringIO(fichier().read_bytes().decode("utf-8-sig"))))
    regions, secteurs, dates = {}, {}, set()
    sortie_l = []
    for r in lignes:
        regions[r["reg"]] = r["libelle_region"]
        secteurs[r["code_section_nace17"]] = r["libelle_section_nace17"].strip()
        dates.add(r["date_maj"])
        sortie_l.append([r["reg"], r["code_section_nace17"], nombre(r["nombre_demandes_deposees"]),
                         nombre(r["nombre_salaries_concernes"]), nombre(r["nombre_heures_demandees"])])
    sortie_l.sort(key=lambda x: (x[0], x[1]))
    date_maj = max(dates)
    obj = {
        "millesime": f"demandes déposées en 2020, fichier arrêté au {date_maj}",
        "source": SOURCE, "date_sources": date_sources("aides_entreprises"), "licence": LICENCE, "page_source": PAGE,
        "date_maj": date_maj,
        "presentation": "Demandes d'autorisation d'activité partielle (chômage partiel) déposées par les employeurs "
                        "en 2020, par région et secteur : nombre de demandes, salariés concernés et heures demandées.",
        "definitions": {
            "demande": "demande d'autorisation préalable déposée par un employeur ; une demande peut ne pas être "
                       "autorisée, et les heures autorisées peuvent ne pas être toutes utilisées",
            "heures_demandees": "heures chômées demandées, pas heures indemnisées",
        },
        "regions": dict(sorted(regions.items())), "secteurs": dict(sorted(secteurs.items())),
        "colonnes": ["region", "secteur", "demandes", "salaries_concernes", "heures_demandees"],
        "lignes": sortie_l,
        "regles": [
            "Agrégats repris tels quels ; aucun employeur nommé.",
            "Des demandes ne sont pas des heures indemnisées ni des montants versés : les montants publiés par "
            "l'Unédic et l'Urssaf (page Emploi) ne sont ni additionnés ni comparés par différence à ces demandes.",
            "Une valeur absente est publiée null, jamais 0.",
        ],
        "limites": ["Fichier arrêté au 27/10/2020 : il ne couvre pas les demandes déposées ensuite.",
                    "Un même salarié peut être concerné par plusieurs demandes."],
        "manques": [{
            "quoi": "Les demandes d'activité partielle après octobre 2020 et par département.",
            "pourquoi": "Le fichier publié avec le tableau de bord des aides aux entreprises s'arrête au 27/10/2020 "
                        "et n'est publié que par région.",
            "depuis": f"Fichier arrêté au {date_maj}.",
            "source": {"libelle": "Aides aux entreprises, data.gouv.fr", "url": PAGE},
        }],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "ordre": "régions puis secteurs par code",
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
        print(f"activite_partielle_demandes : {len(o['lignes'])} lignes", file=sys.stderr)


if __name__ == "__main__":
    main()
