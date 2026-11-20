"""Salaires dans la fonction publique (Insee, Melodi) : séries longues depuis 1995 et détail annuel par métier.

Sources (Insee, base Siasp, Licence Ouverte 2.0), déjà déclarées dans collecte/catalogue.json :
  etat_insee_salaires_fonction_publique   DS_DERA_PUBLIC_SERIES_LONGUES : salaire net mensuel moyen en équivalent
                                          temps plein (EQTP), en euros constants, depuis 1995, par versant, statut et
                                          catégorie, sexe, âge, centiles ; évolutions et indice publiés par l'Insee
  insee_ds_dera_public_annuel             DS_DERA_PUBLIC_ANNUEL_2023 : salaire net mensuel moyen en EQTP (euros
                                          courants) et effectifs en EQTP, par versant, statut, métier (PCS-ESE),
                                          sexe, âge et temps de travail
Ce module reprend les agrégats tels que l'Insee les publie : aucun salaire individuel, aucun calcul par personne,
aucune moyenne ni évolution recalculée par le site. Une modalité absente de la source n'est pas reconstituée.

Commandes :
  python pipeline/salaires_fonction_publique.py collecter   # réseau : collecte/collecte.py (deux identifiants)
  python pipeline/salaires_fonction_publique.py produire    # sans réseau -> site/data/salaires_fonction_publique/
Sorties identiques octet pour octet sur le même entrepôt (tris explicites, date par pipeline/reproductible.py).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "etat"
SORTIE_DEFAUT = ROOT / "site" / "data" / "salaires_fonction_publique"
MAX_OCTETS = 1_000_000
LICENCE = "Licence Ouverte 2.0"

JEUX = {
    "series_longues": {
        "id": "etat_insee_salaires_fonction_publique",
        "zip": LAKE / "etat_insee_salaires_fonction_publique.zip",
        "url": "https://api.insee.fr/melodi/file/DS_DERA_PUBLIC_SERIES_LONGUES/DS_DERA_PUBLIC_SERIES_LONGUES_CSV_FR",
        "page": "https://catalogue-donnees.insee.fr/fr/catalogue/recherche/DS_DERA_PUBLIC_SERIES_LONGUES",
        "titre": "Insee, « Salaires dans la fonction publique : séries longues » (DS_DERA_PUBLIC_SERIES_LONGUES, "
                 "Siasp)",
        "dimensions": ["DERA_MEASURE", "PUBLIC_LEGAL_FORM", "CIVILSERVANT_STATUS", "SEX", "AGE", "QUANTILE",
                       "UNIT_MEASURE"],
    },
    "annuel": {
        "id": "insee_ds_dera_public_annuel",
        "zip": LAKE / "insee_ds_dera_public_annuel.zip",
        "url": "https://api.insee.fr/melodi/file/DS_DERA_PUBLIC_ANNUEL/DS_DERA_PUBLIC_ANNUEL_2023_CSV_FR",
        "page": "https://catalogue-donnees.insee.fr/fr/catalogue/recherche/DS_DERA_PUBLIC_ANNUEL",
        "titre": "Insee, « Salaires dans la fonction publique par catégorie socioprofessionnelle détaillée » "
                 "(DS_DERA_PUBLIC_ANNUEL, 2023, Siasp)",
        "dimensions": ["DERA_MEASURE", "PUBLIC_LEGAL_FORM", "CIVILSERVANT_STATUS", "PCS_ESE", "SEX", "AGE", "WKTIME",
                       "UNIT_MEASURE"],
    },
}
CONSTANTES = {"FREQ": "A", "GEO": "F", "GEO_OBJECT": "FRANCE"}   # une seule modalité dans les deux jeux

RECHERCHE_PUBLIQUE = [
    {"trouvaille": "Insee Melodi, DS_DERA_PUBLIC_SERIES_LONGUES et DS_DERA_PUBLIC_ANNUEL (fichiers CSV)",
     "verdict": "réutilisable tel quel", "licence": LICENCE, "date": "fichiers du 04/12/2025 (données 2023)"},
    {"trouvaille": "Insee Première n° 2100 à 2102 (salaires 2024 par versant, déjà repris par "
                   "pipeline/fonction_publique.py dans fonction_publique/remunerations.json)",
     "verdict": "réutilisable tel quel", "licence": LICENCE,
     "date": "2025 ; année plus récente, autre présentation : les deux sont publiés séparément, jamais fusionnés"},
    {"trouvaille": "DGAFP, rapport annuel sur l'état de la fonction publique (rémunérations)",
     "verdict": "inspiration seulement", "licence": LICENCE, "date": "édition 2025 ; déjà repris par fonction_publique"},
    {"trouvaille": "API Melodi de l'Insee (requêtes par dimension)", "verdict": "à adapter", "licence": LICENCE,
     "date": "fichiers complets préférés : moins de 400 Ko, sans compte"},
]


def lire_zip(chemin: Path) -> tuple[list[dict], dict[str, dict[str, str]], dict[str, str]]:
    """(observations, libellés des modalités par variable, libellés des variables)"""
    if not chemin.exists():
        raise SystemExit(f"{chemin} absent : lancer python pipeline/salaires_fonction_publique.py collecter")
    with zipfile.ZipFile(chemin) as z:
        noms = z.namelist()
        data = next(n for n in noms if n.endswith("_data.csv"))
        meta = next(n for n in noms if n.endswith("_metadata.csv"))
        lignes = list(csv.DictReader(io.StringIO(z.read(data).decode("utf-8-sig")), delimiter=";"))
        libelles: dict[str, dict[str, str]] = {}
        variables: dict[str, str] = {}
        for r in csv.DictReader(io.StringIO(z.read(meta).decode("utf-8-sig")), delimiter=";"):
            libelles.setdefault(r["COD_VAR"], {})[r["COD_MOD"]] = r["LIB_MOD"]
            variables[r["COD_VAR"]] = r["LIB_VAR"]
    return lignes, libelles, variables


def valeur(v: str):
    s = (v or "").strip().replace(",", ".")
    if s == "" or s.lower() in ("nan", "nc", "s", "nd"):
        return None
    try:
        return round(float(s), 3)
    except ValueError:
        return None


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(txt.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets : à découper")
    path.write_text(txt + "\n", encoding="utf-8")
    return n


def table(cle: str) -> tuple[dict, dict]:
    j = JEUX[cle]
    lignes, libelles, variables = lire_zip(j["zip"])
    dims = j["dimensions"]
    obs, absents, annees = [], 0, set()
    for r in lignes:
        for k, v in CONSTANTES.items():
            if r.get(k, v) != v:
                raise SystemExit(f"{cle} : modalité inattendue {k}={r.get(k)} (géographie ou fréquence)")
        if cle == "series_longues" and r.get("WKTIME", "_T") != "_T":
            raise SystemExit(f"{cle} : temps de travail inattendu {r.get('WKTIME')}")
        if cle == "annuel" and r.get("QUANTILE", "_T") != "_T":
            raise SystemExit(f"{cle} : quantile inattendu {r.get('QUANTILE')}")
        v = valeur(r["OBS_VALUE"])
        if v is None:
            absents += 1
        an = int(r["TIME_PERIOD"])
        annees.add(an)
        obs.append([an, *[r[d] for d in dims], v])
    obs.sort(key=lambda x: tuple(str(c) for c in x[:-1]))
    nomenclatures = {d: {"libelle": variables.get(d, d),
                         "modalites": dict(sorted({m: libelles.get(d, {}).get(m, m)
                                                   for m in {o[i + 1] for o in obs}}.items()))}
                     for i, d in enumerate(dims)}
    fichier = {"colonnes": ["annee", *dims, "valeur"], "observations": obs}
    meta = {"nomenclatures": nomenclatures, "annees": sorted(annees), "observations": len(obs),
            "valeurs_absentes": absents}
    return fichier, meta


def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    date = date_sources("etat")
    fichiers, metas = {}, {}
    for cle, j in JEUX.items():
        f, meta = table(cle)
        a0, a1 = meta["annees"][0], meta["annees"][-1]
        entete = {"millesime": f"{a0} à {a1}" if a0 != a1 else str(a0),
                  "source": f"{j['titre']}, Licence Ouverte 2.0 : {j['url']}", "date_sources": date}
        fichiers[cle] = dump(sortie / f"{cle}.json", {**entete, "unite": "voir UNIT_MEASURE (XDC : euros ; PT : "
                                                                       "pourcentage ; IX : indice ; FT : EQTP)", **f})
        metas[cle] = {**meta, **entete, "identifiant_catalogue": j["id"], "url": j["url"], "page": j["page"],
                      "chemin": f"salaires_fonction_publique/{cle}.json", "octets": fichiers[cle]}
    sl = metas["series_longues"]
    index = {
        "millesime": f"séries longues {sl['annees'][0]} à {sl['annees'][-1]} ; détail par métier "
                     f"{metas['annuel']['annees'][-1]}",
        "source": " ; ".join(m["source"] for m in metas.values()),
        "date_sources": date,
        "licence": LICENCE,
        "presentation": "Salaire net mensuel moyen des agents de la fonction publique (État, territoriale, "
                        "hospitalière), tel que l'Insee le publie : depuis 1995 en euros constants, par statut, "
                        "catégorie, sexe, âge et centiles, et pour la dernière année par métier, avec les effectifs "
                        "en équivalent temps plein.",
        "jeux": metas,
        "definitions": {
            "eqtp": "équivalent temps plein : un poste occupé à mi-temps toute l'année compte pour 0,5 ; le salaire "
                    "est ramené à ce qu'il serait pour un temps plein sur toute l'année, par mois",
            "salaire_net": "salaire brut diminué des cotisations salariales, de la CSG et de la CRDS ; avant impôt "
                           "sur le revenu",
            "euros_constants": "montants corrigés de la hausse des prix à la consommation, pour comparer les années "
                               "entre elles (méthode et année de référence de l'Insee)",
            "centile": "valeur sous laquelle se situe une part donnée des agents (centile 10 : 10 % des agents "
                       "gagnent moins) ; le centile 50 est le salaire médian",
        },
        "regles": [
            "Agrégats de l'Insee repris tels quels : aucun salaire individuel, aucun calcul par personne.",
            "Aucune moyenne, évolution ou différence n'est recalculée par le site : les évolutions et l'indice "
            "affichés sont ceux que l'Insee publie.",
            "Les séries longues (euros constants) et le détail annuel (euros courants) ne sont jamais comparés "
            "entre eux.",
            "Les chiffres 2024 publiés par l'Insee dans ses Insee Première (fonction_publique/remunerations.json) "
            "restent publiés à part, sans fusion.",
        ],
        "limites": [
            "Champ, sources et méthode : ceux de l'Insee (base Siasp), décrits sur la page de chaque jeu ; le site "
            "ne les modifie pas.",
            "Un salaire moyen ne dit rien d'un agent en particulier : l'écart entre centiles le montre.",
            "Le détail par métier n'est publié que pour la dernière année disponible.",
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "ordre": "observations triées par année puis par code de chaque dimension ; aucun classement par montant",
    }
    dump(sortie / "index.json", index)
    return index


def collecter() -> int:
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"),
                            *[j["id"] for j in JEUX.values()]])


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
        print("salaires_fonction_publique : " + ", ".join(f"{k} {m['observations']} observations"
                                                          for k, m in i["jeux"].items()), file=sys.stderr)


if __name__ == "__main__":
    main()
