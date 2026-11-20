"""Budgets des universités et des autres opérateurs de l'enseignement supérieur et de la recherche, par établissement.

Source : ministère de l'Enseignement supérieur et de la Recherche (SIES), jeu « Indicateurs financiers des opérateurs
de l'enseignement supérieur et de la recherche » (data.enseignementsup-recherche.gouv.fr,
fr-esr-operateurs-indicateurs-financiers, Licence Ouverte 2.0) : comptes financiers de chaque établissement depuis
2010 et budget initial de l'année en cours. Identifiant `etat_esr_operateurs_financiers` de collecte/catalogue.json
(contrôle collecte/integrite.py).

Ce qui est publié : les montants de chaque établissement tels que la source les écrit (euros), et les ratios que la
source publie elle-même, à lire « sur 100 € de produits encaissables » (charges de personnel, ressources propres).
Aucun total, aucune moyenne, aucun montant par étudiant n'est calculé par le site (règle 13). Les établissements sont
des personnes morales de droit public (universités, écoles, grands établissements : opérateurs de l'État) ; aucune
personne physique n'apparaît dans le jeu. Une cellule vide de la source reste null (jamais 0).

Ce qui manque à la source : la subvention pour charges de service public versée par l'État à chaque établissement
n'est pas une colonne du jeu (publiée par établissement dans les annexes budgétaires, non reprises ici). Le site ne la
déduit pas des autres colonnes.

Commandes :
  python pipeline/universites.py collecter   # réseau : collecte/collecte.py etat_esr_operateurs_financiers
  python pipeline/universites.py produire    # sans réseau -> site/data/universites/ ; --sortie DOSSIER
Sorties identiques octet pour octet sur le même entrepôt (tris explicites, date par pipeline/reproductible.py).
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SORTIE_DEFAUT = ROOT / "site" / "data" / "universites"
ID = "etat_esr_operateurs_financiers"
PARQUET = LAKE / "etat" / f"{ID}.parquet"
MAX_OCTETS = 1_000_000

PAGE = "https://data.enseignementsup-recherche.gouv.fr/explore/dataset/fr-esr-operateurs-indicateurs-financiers/"
SOURCE = ("Ministère de l'Enseignement supérieur et de la Recherche (SIES), « Indicateurs financiers des opérateurs "
          "de l'enseignement supérieur et de la recherche », data.enseignementsup-recherche.gouv.fr, jeu "
          "fr-esr-operateurs-indicateurs-financiers, Licence Ouverte 2.0 : " + PAGE)
LICENCE = "Licence Ouverte 2.0"

# (clé publiée, colonne de la source, libellé, unité). Ordre = ordre des valeurs dans etablissements.json.
INDICATEURS = [
    ("produits_encaissables", "produits_de_fonctionnement_encaissables",
     "Produits de fonctionnement encaissables (recettes de fonctionnement, hors écritures sans flux de trésorerie)",
     "euros"),
    ("charges_decaissables", "charges_de_fonctionnement_decaissables",
     "Charges de fonctionnement décaissables (dépenses de fonctionnement, hors écritures sans flux de trésorerie)",
     "euros"),
    ("charges_personnel", "charges_de_personnel", "Charges de personnel", "euros"),
    ("ressources_propres", "ressources_propres_encaissables", "Ressources propres encaissables", "euros"),
    ("droits_inscription", "droits_d_inscription", "Droits d'inscription", "euros"),
    ("formation_continue", "formation_continue_diplomes_propres_et_vae",
     "Formation continue, diplômes propres et validation des acquis de l'expérience", "euros"),
    ("contrats_recherche", "contrats_et_prestations_de_recherche_hors_anr",
     "Contrats et prestations de recherche (hors Agence nationale de la recherche)", "euros"),
    ("anr", "anr_hors_investissements_d_avenir",
     "Agence nationale de la recherche, hors investissements d'avenir", "euros"),
    ("anr_investissements_avenir", "anr_investissements_d_avenir",
     "Agence nationale de la recherche, investissements d'avenir", "euros"),
    ("subventions_region", "subventions_de_la_region", "Subventions de la région", "euros"),
    ("subventions_ue", "subventions_union_europeenne", "Subventions de l'Union européenne", "euros"),
    ("autres_subventions", "autres_subventions", "Autres subventions", "euros"),
    ("taxe_apprentissage", "taxe_d_apprentissage", "Taxe d'apprentissage", "euros"),
    ("investissements", "acquisitions_d_immobilisations", "Acquisitions d'immobilisations (investissements)",
     "euros"),
    ("resultat_net", "resultat_net_comptable", "Résultat net comptable", "euros"),
    ("capacite_autofinancement", "capacite_d_autofinancement", "Capacité d'autofinancement", "euros"),
    ("solde_budgetaire", "solde_budgetaire", "Solde budgétaire", "euros"),
    ("fonds_roulement", "fonds_de_roulement_net_global", "Fonds de roulement net global", "euros"),
    ("tresorerie", "tresorerie", "Trésorerie", "euros"),
    ("personnel_sur_100", "charges_de_personnel_produits_encaissables",
     "Charges de personnel sur 100 € de produits encaissables (ratio publié par la source)", "euros sur 100 €"),
    ("ressources_propres_sur_100", "ressources_propres_produits_encaissables",
     "Ressources propres sur 100 € de produits encaissables (ratio publié par la source)", "euros sur 100 €"),
    ("fonds_roulement_jours", "fonds_de_roulement_en_jours_de_fonctionnement",
     "Fonds de roulement en jours de fonctionnement (publié par la source)", "jours"),
    ("tresorerie_jours", "tresorerie_en_jours_de_fonctionnement",
     "Trésorerie en jours de fonctionnement (publié par la source)", "jours"),
]
DECIMALES = {"euros": 0, "euros sur 100 €": 1, "jours": 1}

RECHERCHE_PUBLIQUE = [
    {"trouvaille": "MESR, Indicateurs financiers des opérateurs de l'enseignement supérieur et de la recherche "
                   "(fr-esr-operateurs-indicateurs-financiers)", "verdict": "réutilisable tel quel",
     "licence": LICENCE, "date": "jeu mis à jour en 2026 (budget initial 2026 compris)"},
    {"trouvaille": "MESR, tableau de bord financier des universités (dataESR, application en ligne)",
     "verdict": "inspiration seulement", "licence": LICENCE,
     "date": "mêmes chiffres, présentation par établissement ; pas de code réutilisable"},
    {"trouvaille": "Jaune budgétaire « Opérateurs de l'État » (subvention pour charges de service public par "
                   "opérateur, déjà lu par pipeline/operateurs.py)", "verdict": "à adapter",
     "licence": LICENCE, "date": "PLF 2024 à 2026 ; rapprochement établissement par établissement non fait ici"},
    {"trouvaille": "site/data/education_recherche (effectifs étudiants, ANR) et pipeline/education_recherche.py",
     "verdict": "inspiration seulement", "licence": "MIT (code), Licence Ouverte 2.0 (données)",
     "date": "dépôt ; aucun montant par étudiant calculé ici (règle 13)"},
]


def valeur(v, decimales: int):
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    if decimales == 0:
        return int(round(x))
    return round(x, decimales)


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(txt.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets : à découper")
    path.write_text(txt + "\n", encoding="utf-8")
    return n


def lire() -> list[dict]:
    if not PARQUET.exists():
        raise SystemExit(f"{PARQUET} absent : lancer python pipeline/universites.py collecter")
    import pyarrow.parquet as pq
    return pq.read_table(PARQUET).to_pylist()


def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    lignes = lire()
    date = date_sources("etat")
    etabs: dict[str, dict] = {}
    exercices: dict[int, str] = {}
    vides = {k: 0 for k, *_ in INDICATEURS}
    for r in sorted(lignes, key=lambda r: (str(r["uai_identifiant"]), int(r["exercice"]))):
        uai = str(r["uai_identifiant"]).strip()
        an = int(r["exercice"])
        nature = "budget_initial" if str(r.get("source") or "").lower().startswith("budget") else "compte_financier"
        exercices[an] = nature
        e = etabs.setdefault(uai, {"uai": uai, "noms": {}, "valeurs": {}})
        e["noms"][an] = str(r["etablissement_lib"]).strip()
        e.update({"commune": r.get("commune"), "code_commune": r.get("code_de_la_commune"),
                  "region": r.get("region"), "academie": r.get("academie"),
                  "rce": int(r["rce"]) if str(r.get("rce") or "").isdigit() else None,
                  "paysage": r.get("etablissement_id_paysage")})
        vals = []
        for k, col, _lib, unite in INDICATEURS:
            v = valeur(r.get(col), DECIMALES[unite])
            if v is None:
                vides[k] += 1
            vals.append(v)
        e["valeurs"][str(an)] = [nature, *vals]
    sortie_etabs = []
    def cle(u: str) -> tuple:
        nom = sorted(etabs[u]["noms"].items())[-1][1]
        return ("".join(c for c in unicodedata.normalize("NFD", nom.lower()) if unicodedata.category(c) != "Mn"), u)

    for uai in sorted(etabs, key=cle):
        e = etabs[uai]
        noms = sorted(e["noms"].items())
        nom = noms[-1][1]
        anciens = sorted({n for _a, n in noms if n != nom})
        sortie_etabs.append({
            "uai": uai, "nom": nom, "noms_anterieurs": anciens, "commune": e["commune"],
            "code_commune": e["code_commune"], "region": e["region"], "academie": e["academie"],
            "responsabilites_elargies_depuis": e["rce"], "id_paysage": e["paysage"],
            "exercices": dict(sorted(e["valeurs"].items())),
        })
    annees = sorted(exercices)
    derniers_comptes = max(a for a in annees if exercices[a] == "compte_financier")
    entete = {"millesime": f"comptes financiers {annees[0]} à {derniers_comptes}"
                           + (f", budget initial {annees[-1]}" if exercices[annees[-1]] == "budget_initial" else ""),
              "source": SOURCE, "date_sources": date}
    colonnes = ["nature", *[k for k, *_ in INDICATEURS]]
    fichier_etabs = {**entete, "unite": "euros, sauf ratios (euros sur 100 €) et jours", "colonnes": colonnes,
                     "etablissements": sortie_etabs}
    n_etabs = dump(sortie / "etablissements.json", fichier_etabs)
    par_annee = {str(a): sum(1 for e in sortie_etabs if str(a) in e["exercices"]) for a in annees}
    index = {
        **entete,
        "licence": LICENCE,
        "page_source": PAGE,
        "presentation": "Budget de chaque université, école et grand établissement de l'enseignement supérieur et "
                        "de la recherche (opérateurs de l'État) : recettes, dépenses, charges de personnel, "
                        "ressources propres, investissements et situation financière, tels que publiés par le "
                        "ministère, exercice par exercice.",
        "indicateurs": [{"cle": k, "colonne_source": col, "libelle": lib, "unite": unite,
                         "statut": "publié par la source", "valeurs_absentes": vides[k]}
                        for k, col, lib, unite in INDICATEURS],
        "natures": {"compte_financier": "compte financier (exécution) de l'exercice",
                    "budget_initial": "budget initial (prévision) de l'exercice, voté par le conseil "
                                      "d'administration ; à ne pas comparer à un compte financier"},
        "exercices": [{"annee": a, "nature": exercices[a], "etablissements": par_annee[str(a)]} for a in annees],
        "couverture": {"etablissements": len(sortie_etabs), "lignes_lues": len(lignes),
                       "premier_exercice": annees[0], "dernier_compte_financier": derniers_comptes,
                       "dernier_exercice": annees[-1]},
        "fichiers": {"etablissements": {"chemin": "universites/etablissements.json", "octets": n_etabs}},
        "manques": [{
            "quoi": "La subvention pour charges de service public versée par l'État à chaque établissement.",
            "pourquoi": "Le jeu du ministère ne publie pas cette subvention dans une colonne à part : elle est "
                        "comprise dans les produits encaissables. Le site ne la déduit pas des autres colonnes.",
            "depuis": f"Constat de la collecte du {date} (toutes les années du jeu).",
            "source": {"libelle": "Indicateurs financiers des opérateurs de l'ESR", "url": PAGE},
        }],
        "regles": [
            "Montants repris tels que la source les publie, en euros, sans arrondi autre que l'euro.",
            "Ratios « sur 100 € » : publiés par la source (charges de personnel ou ressources propres rapportées "
            "aux produits encaissables, en pourcentage), jamais calculés par le site.",
            "Une cellule vide de la source est publiée null, jamais 0.",
            "Aucun total, aucune moyenne et aucun montant par étudiant n'est calculé par le site.",
            "Nom affiché : celui du dernier exercice ; les noms antérieurs du même établissement (même code UAI) "
            "sont listés à part.",
        ],
        "limites": [
            "Le dernier exercice est un budget initial (prévision) : il n'est pas comparable aux comptes financiers "
            "des années précédentes.",
            "Les charges de personnel ne sont publiées qu'à partir de l'exercice 2018 dans ce jeu.",
            "Les établissements changent de périmètre (fusions, créations d'établissements expérimentaux) : une "
            "évolution d'une année sur l'autre peut venir d'un changement de périmètre.",
            "Les organismes de recherche (CNRS, Inserm...) ne sont pas dans ce jeu.",
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "ordre": "établissements par ordre alphabétique du nom ; exercices par année croissante ; aucun classement "
                 "par montant",
    }
    dump(sortie / "index.json", index)
    return index


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
        i = produire(a.sortie)
        c = i["couverture"]
        print(f"universites : {c['etablissements']} établissements, exercices {c['premier_exercice']} à "
              f"{c['dernier_exercice']}", file=sys.stderr)


if __name__ == "__main__":
    main()
