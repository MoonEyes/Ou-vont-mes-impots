"""Performance : ce que l'État s'était fixé (cibles) et ce qui a été mesuré (réalisé), relié aux crédits dépensés.

Deux familles de données, jamais mélangées :
  1. Indicateurs de performance du budget de l'État, par programme : objectif, indicateur, unité, cible, réalisé,
     année par année, choisis par chaque ministère dans ses projets annuels de performances (PAP, annexes au projet
     de loi de finances) et rapports annuels de performances (RAP, annexes à la loi relative aux résultats de la
     gestion). Reliés par numéro de programme et année aux crédits déjà publiés par le site (voté, dépensé).
  2. Baromètre des résultats de l'action publique (DITP) : indicateurs des politiques prioritaires du Gouvernement,
     valeur initiale, valeurs successives et cible, par département et pour la France.

Règle n° 0 (recherche préalable) : les jeux « Performance de la dépense » (RAP 2025 et antérieurs) et « PLF 2025 -
Performance de la dépense (PAP) » publiés sur data.gouv.fr sont moissonnés depuis data.economie.gouv.fr ; ils sont
déjà lus, nettoyés et rapprochés en séries par pipeline/realisations.py (site/data/realisations/<programme>.json) :
réutilisés tels quels, sans seconde extraction. Le baromètre est lu dans le dépôt public de la DITP, désigné comme
« Fichiers indicateurs » par le jeu data.gouv.fr (déjà utilisé pour un seul indicateur par pipeline/logement.py).

Commandes :
    python pipeline/performance.py collecter    (réseau : python collecte/collecte.py performance_ditp_barometre,
                                                 contrôle d'intégrité collecte/integrite.py, refus jamais contournés)
    python pipeline/performance.py produire [--sortie DOSSIER]   (sans réseau)

Entrées :
  site/data/realisations/index.json et <programme>.json (étape realisations, lecture seule)
  site/data/arbre/racine.json (exécution 2024 retraitée, étape base) et site/data/millesimes/execution2025/racine.json
      (exécution 2025, étape millesimes) : lecture seule, autres montants publiés pour la même année
  data/lake/etat/etat_performance_rap_2025.parquet (collecté par l'étape realisations, lecture seule) : intitulés
      publiés au RAP 2025 sous le code d'un indicateur absent des documents 2025
  data/lake/performance/performance_ditp_barometre/ : meta_indicateurs.csv, meta_chantiers.csv, dict-territoires.csv,
      ind-<n>.csv (un fichier par indicateur)

Sorties (site/data/performance/, contrat docs/contrat_interface.md, schémas docs/schemas/performance_*) :
  index.json                      présentation, sources, missions et programmes, règles, limites
  programmes/<programme>.json     table (année, mission, programme, objectif, indicateur, unité, cible, réalisé,
                                  source), crédits du programme par année, correspondance des indicateurs renommés
                                  ou absents des documents 2025
  correspondance.json             méthode et comptes de la correspondance, par programme
  barometre/index.json            indicateurs du baromètre (chantier, intitulé, sens publié), départements
  barometre/<code>.json           valeurs d'un département (ou FR pour la France)

Règles : aucun ratio « montant par résultat », aucune note ; aucune différence entre cible et réalisé calculée ; le
« taux d'avancement » du baromètre (calcul de la DITP) n'est pas repris ; valeurs absentes ou non chiffrées : null avec
le texte publié, jamais 0. Aucune personne n'est nommée par ces sources.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
SORTIE = SITE / "performance"
DOMAINE = "performance"
ID_DITP = "performance_ditp_barometre"
LAKE_DITP = ROOT / "data" / "lake" / DOMAINE / ID_DITP
RAP2025 = ROOT / "data" / "lake" / "etat" / "etat_performance_rap_2025.parquet"   # collecté par l'étape realisations
LO = "Licence Ouverte 2.0"

ODS = "https://data.economie.gouv.fr/explore/dataset"
URL_RAP2025_DG = "https://www.data.gouv.fr/datasets/performance-de-la-depense-rap-2025/"
URL_PAP2025_DG = "https://www.data.gouv.fr/datasets/plf-2025-performance-de-la-depense-pap/"
URL_DITP_DG = "https://www.data.gouv.fr/datasets/barometre-des-resultats-de-laction-publique-1/"
URL_DITP_DEPOT = "https://github.com/DITP-pilotage/barometre-resultats"
URL_DITP_RAW = "https://raw.githubusercontent.com/DITP-pilotage/barometre-resultats/prod"
URL_REPSS = ("https://www.data.gouv.fr/datasets/projet-de-loi-de-financement-de-la-securite-sociale-donnees-des-"
             "rapports-devaluation-des-politiques-de-securite-sociale-repss/")
DOCUMENTS_RECENTS = ("RAP 2025", "PAP 2025")   # documents de performance les plus récents lus par realisations.py

PRESENTATION = (
    "Pour chaque programme du budget de l'État : les objectifs et indicateurs que le ministère s'était fixés, la "
    "cible annoncée et la valeur mesurée, année par année, à côté des crédits votés et dépensés la même année. Et, "
    "par département, les indicateurs du baromètre des résultats de l'action publique. La page ne dit pas si "
    "l'argent a produit le résultat : elle met côte à côte ce qui est publié.")
AVERTISSEMENTS = [
    "Les indicateurs, leurs cibles et leurs unités sont choisis par les ministères eux-mêmes, dans les documents "
    "budgétaires qu'ils rédigent ; le site les reprend tels quels.",
    "L'écart entre une cible et la valeur mesurée n'est ni un succès ni un échec en soi : une cible peut être "
    "révisée, un indicateur peut dépendre de facteurs extérieurs au programme, et le sens souhaité n'est pas "
    "toujours publié.",
    "Crédits et indicateurs d'une même année sont posés côte à côte, sans lien de cause publié : le site ne calcule "
    "ni montant par résultat, ni note, ni classement.",
]
REGLES = [
    "Table reprise des séries d'indicateurs de site/data/realisations (pipeline/realisations.py), sans nouvelle "
    "lecture des sources : une ligne par indicateur et par année où une cible ou une valeur réalisée est publiée.",
    "Valeur non chiffrée (« Non déterminé », « nd », vide) : null, avec le texte publié dans `cible_publiee` ou "
    "`realise_publie` ; jamais 0.",
    "Aucune différence entre cible et réalisé n'est calculée ni publiée par ce module ; aucun ratio entre crédits et "
    "indicateurs.",
    "Crédits : voté (loi de finances initiale) et dépense constatée de site/data/realisations pour la même année et le "
    "même programme ; les autres montants publiés pour la même année (exécution 2024 retraitée de l'arbre du site, "
    "exécution 2025 préparée) sont listés à part avec leur périmètre, jamais additionnés ni arbitrés.",
    "Baromètre : valeur initiale, valeurs successives et cible telles que publiées par la DITP, avec leur date ; le "
    "taux d'avancement calculé par la DITP n'est pas repris.",
]
LIMITES = [
    "Les indicateurs changent d'une année à l'autre (libellé, périmètre, mode de calcul) : le rapprochement en séries "
    "est celui de pipeline/realisations.py (code de l'indicateur, libellé au moins à moitié commun, sinon libellé "
    "exact) ; correspondance.json liste les libellés changés et les indicateurs absents des documents 2025.",
    "Un indicateur absent des documents 2025 a pu être supprimé, remplacé par un autre ou renuméroté sans que le "
    "rapprochement le retrouve : la source ne publie pas de table de passage.",
    "Les documents de performance ouverts en données couvrent 2012 à 2027 avec des trous (pas de jeu ouvert pour "
    "certaines éditions) ; les crédits par programme manquent pour 2015 à 2017 et 2021 (voir site/data/realisations).",
    "Sécurité sociale : les rapports d'évaluation des politiques de sécurité sociale sont publiés en PDF ; le jeu "
    "data.gouv.fr associé (classeurs des graphiques, dernière édition PLFSS 2022) n'a pas de colonnes cible et "
    "réalisé normalisées : non exploité.",
    "Baromètre : indicateurs des seules politiques prioritaires retenues par le Gouvernement, sans lien publié avec un "
    "programme budgétaire ni avec des crédits ; les valeurs départementales n'existent pas pour tous les indicateurs.",
]
RECHERCHE_PUBLIQUE = [
    {"trouvaille": "site/data/realisations (pipeline/realisations.py) : séries d'indicateurs RAP et PAP 2015 à 2025 "
                   "rapprochées, crédits votés et dépensés 2010 à 2025",
     "url": "pipeline/realisations.py", "verdict": "réutilisable tel quel", "licence": "MIT (code), " + LO,
     "dernier_commit": "2026-11-17", "usage": "table et crédits de ce module"},
    {"trouvaille": "Performance de la dépense (RAP) 2025, data.gouv.fr (moissonné depuis data.economie.gouv.fr)",
     "url": URL_RAP2025_DG, "verdict": "réutilisable tel quel (déjà lu par realisations.py)", "licence": LO,
     "dernier_commit": "2026-06-04", "usage": "cibles et réalisés 2023 à 2026"},
    {"trouvaille": "PLF 2025, Performance de la dépense (PAP), data.gouv.fr (moissonné depuis data.economie.gouv.fr)",
     "url": URL_PAP2025_DG, "verdict": "réutilisable tel quel (déjà lu par realisations.py)", "licence": LO,
     "dernier_commit": "2026-01-26", "usage": "cibles 2025 à 2027"},
    {"trouvaille": "DITP-pilotage/barometre-resultats : fichiers indicateurs du baromètre (CSV par indicateur, "
                   "métadonnées), désignés par le jeu data.gouv.fr « Baromètre des résultats de l'action publique »",
     "url": URL_DITP_DEPOT, "verdict": "réutilisable tel quel", "licence": LO,
     "dernier_commit": "non lu (API GitHub non accessible depuis la collecte) ; jeu data.gouv.fr modifié le 2024-06-11",
     "usage": "baromètre par département"},
    {"trouvaille": "Rapports d'évaluation des politiques de sécurité sociale (REPSS), données des graphiques",
     "url": URL_REPSS, "verdict": "inspiration seulement (non structuré : un onglet par graphique, sans colonnes "
                                     "cible et réalisé ; dernière édition PLFSS 2022)",
     "licence": "Licence Ouverte 2.0 (other-pd sur data.gouv.fr)", "dernier_commit": "2022-01-06",
     "usage": "non exploité"},
]

# --- utilitaires ---------------------------------------------------------------------------------------------------


def lire_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def url_source(s: str) -> str:
    """« data.economie.gouv.fr/<jeu> (précision) » -> URL du jeu sur data.economie.gouv.fr ; sinon texte inchangé."""
    m = re.match(r"data\.economie\.gouv\.fr/([a-z0-9\-]+)(.*)$", s)
    if not m:
        return s
    return f"{ODS}/{m.group(1)}/{m.group(2)}".rstrip() if m.group(2) else f"{ODS}/{m.group(1)}/"


def nombre_ditp(texte: str | None) -> float | None:
    """« 55.6 » -> 55.6 ; vide -> None (jamais 0)."""
    t = (texte or "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def ecrire(dossier: Path, nom: str, donnees: dict) -> None:
    p = dossier / nom
    p.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(donnees, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{nom} dépasse 1 Mo : découper")
    p.write_text(texte, encoding="utf-8")


# --- crédits déjà publiés ------------------------------------------------------------------------------------------


def _programmes_arbre(racine: dict) -> dict[str, float]:
    """{programme: milliards d'euros} pour les nœuds de niveau programme d'un arbre du site."""
    out: dict[str, float] = {}

    def walk(n: dict) -> None:
        if n.get("niveau") == "programme":
            m = re.search(r"(\d{3})$", str(n.get("id", "")))
            if m and isinstance(n.get("md"), (int, float)):
                out[m.group(1)] = n["md"]
            return
        for e in n.get("enfants", []) or []:
            walk(e)

    walk(racine)
    return out


def autres_credits() -> dict[tuple[str, int], list[dict]]:
    """Montants publiés ailleurs sur le site pour un programme et une année (arbre 2024, exécution 2025 préparée)."""
    out: dict[tuple[str, int], list[dict]] = {}
    for rel, annee, perimetre in (
        ("arbre/racine.json", 2024, "exécution 2024 retraitée au format du PLF 2026 par la direction du budget "
                                    "(arbre affiché par défaut sur le site)"),
        ("millesimes/execution2025/racine.json", 2025, "exécution 2025 préparée (PLRG 2025, annexe 1), non affichée "
                                                       "par défaut"),
    ):
        p = SITE / rel
        if not p.exists():
            continue
        r = lire_json(p)
        for prog, md in _programmes_arbre(r).items():
            out.setdefault((prog, annee), []).append({
                "montant_eur": round(md * 1e9), "fichier": rel, "source": r.get("source", ""),
                "millesime": r.get("millesime", ""), "perimetre": perimetre,
                "precision": "publié en milliards d'euros à 6 décimales (arrondi au millier d'euros)"})
    return out


def credits_programme(r: dict, autres: dict) -> list[dict]:
    """Crédits par année du programme : voté et dépense constatée (realisations), autres montants listés à part."""
    out = []
    for a in r["prevu_depense"]["annees"]:
        ann = a["annee"]
        dep = a.get("depense_constatee_eur")
        aut = []
        for x in autres.get((r["programme"], ann), []):
            # écart de plus d'un million d'euros : autre montant publié (périmètre différent), jamais arbitré
            egal = dep is not None and abs(x["montant_eur"] - dep) < 1_000_000
            aut.append({**x, "egal_a_la_depense_constatee": egal})
        out.append({
            "annee": ann, "vote_lfi_eur": a.get("vote_lfi_eur"), "depense_constatee_eur": dep,
            "source": a.get("source"), "trou": a.get("trou"), "autres_montants_publies": aut})
    return out


# --- table des indicateurs -----------------------------------------------------------------------------------------


def lignes_indicateur(i: dict) -> list[dict]:
    """Une ligne par année où une cible ou une valeur réalisée est publiée (valeurs non chiffrées : null + texte)."""
    vals = {v["annee"]: v for v in i["valeurs"]}
    cibs = {c["annee"]: c for c in i["cibles"]}
    lignes = []
    for a in sorted(set(vals) | set(cibs)):
        v, c = vals.get(a), cibs.get(a)
        l: dict = {"annee": a}
        if c:   # clé absente : aucune cible publiée pour cette année
            l.update({"cible": c["valeur"], "cible_publiee": c["brut"], "source_cible": c["source"]})
            if c.get("note"):
                l["cible_note"] = c["note"]
        if v:   # clé absente : aucune valeur réalisée publiée pour cette année
            l.update({"realise": v["valeur"], "realise_publie": v["brut"], "source_realise": v["source"]})
        lignes.append(l)
    return lignes


def rap2025_par_code() -> dict[tuple[str, str], list[str]] | None:
    """{(programme, code d'indicateur): sous-indicateurs publiés au RAP 2025} (entrepôt de l'étape realisations)."""
    p = RAP2025
    if not p.exists():
        return None
    import pyarrow.parquet as pq
    t = pq.read_table(p, columns=["code_programme", "code_externe_indicateur", "libelle_indicateur",
                                  "libelle_sous_indicateur"]).to_pylist()
    out: dict[tuple[str, str], list[str]] = {}
    for r in t:
        if r["code_programme"] is None or not r["code_externe_indicateur"]:
            continue
        cle = (str(int(float(r["code_programme"]))).zfill(3), str(r["code_externe_indicateur"]).strip())
        lib = (r["libelle_sous_indicateur"] or r["libelle_indicateur"] or "").strip()
        if lib and lib not in out.setdefault(cle, []):
            out[cle].append(lib)
    return out


def correspondance_serie(i: dict, programme: str, ordre_sources: list[str], rap: dict | None) -> dict | None:
    """Ligne de la table de correspondance si le libellé a changé ou si l'indicateur manque aux documents 2025."""
    srcs = {x["source"] for x in i["valeurs"] + i["cibles"]}
    recent = any(s in DOCUMENTS_RECENTS for s in srcs)
    anciens = i.get("libelles_anterieurs") or []
    if recent and not anciens:
        return None
    statuts = []
    if anciens:
        statuts.append("libellé modifié")
    if not recent:
        statuts.append("absent des documents 2025")
    rang = {s: k for k, s in enumerate(ordre_sources)}
    derniere = min(srcs, key=lambda s: rang.get(s, len(rang))) if srcs else None
    annees = sorted({x["annee"] for x in i["valeurs"] + i["cibles"]})
    code = i.get("code_indicateur")
    meme_code = None
    if not recent and rap is not None and code:
        meme_code = rap.get((programme, str(code)), [])
    return {
        "serie": i["id"], "code_indicateur": code, "indicateur": i["indicateur"],
        "sous_indicateur": i["sous_indicateur"], "statuts": statuts, "libelles_anterieurs": anciens,
        "derniere_source": derniere, "premiere_annee": annees[0] if annees else None,
        "derniere_annee": annees[-1] if annees else None,
        "meme_code_au_rap_2025": meme_code,
        "rapprochement": i.get("rapprochement") or {}}


CORR_METHODE = (
    "Séries de site/data/realisations : une ligne est rattachée à une série par le code de l'indicateur si les "
    "libellés sont au moins à moitié communs (mots), sinon par libellé exact d'indicateur et de sous-indicateur ; "
    "sinon une série est créée. « Libellé modifié » : la série porte d'autres libellés d'indicateur dans des documents "
    "plus anciens (`libelles_anterieurs`). « Absent des documents 2025 » : aucune cible ni valeur de la série ne vient "
    "du RAP 2025 ni du PAP 2025 (dernière source dans `derniere_source`). `meme_code_au_rap_2025` : intitulés publiés "
    "au RAP 2025 sous le même code d'indicateur et le même programme (liste vide : code absent du RAP 2025 ; null : "
    "pas de code ou série encore publiée) ; un même code peut désigner un autre indicateur : le site ne dit pas qu'il "
    "y a remplacement. `rapprochement` compte les lignes rattachées par chaque méthode.")


def construire_programmes(collecte_le: str) -> tuple[dict, dict, dict]:
    """(fichiers programmes, correspondance (résumé), résumé pour l'index)."""
    idx = lire_json(SITE / "realisations" / "index.json")
    sources_perf = idx["sources_performance"]
    ordre = [v["libelle"] for v in sources_perf.values()]
    url_par_lib = {v["libelle"]: url_source(v["source"]) for v in sources_perf.values()}
    autres = autres_credits()
    rap = rap2025_par_code()
    fichiers, resume, par_prog = {}, [], []
    comptes = {"series": 0, "libelle_modifie": 0, "absent_des_documents_2025": 0, "code_encore_au_rap_2025": 0}
    for prog in sorted(idx["programmes"]):
        r = lire_json(SITE / "realisations" / f"{prog}.json")
        tous = r["resultats_mesures"]["indicateurs"]
        inds = [i for i in tous if i["valeurs"] or i["cibles"]]   # séries sans aucune valeur ni cible : comptées
        comptes["series"] += len(inds)
        series = [{"serie": i["id"], "objectif": i["objectif"], "indicateur": i["indicateur"],
                   "sous_indicateur": i["sous_indicateur"], "unite": i["unite"],
                   "indicateur_de_contexte": i["indicateur_de_contexte"], "lignes": lignes_indicateur(i)}
                  for i in inds]
        corr = [c for i in inds if (c := correspondance_serie(i, prog, ordre, rap))]
        for c in corr:
            comptes["libelle_modifie"] += "libellé modifié" in c["statuts"]
            comptes["absent_des_documents_2025"] += "absent des documents 2025" in c["statuts"]
            comptes["code_encore_au_rap_2025"] += bool(c["meme_code_au_rap_2025"])
        utilisees = sorted({l[k] for s in series for l in s["lignes"] for k in ("source_cible", "source_realise")
                            if l.get(k)}, key=lambda s: ordre.index(s) if s in ordre else len(ordre))
        annees_ind = sorted({l["annee"] for s in series for l in s["lignes"]})
        n_lignes = sum(len(s["lignes"]) for s in series)
        fichiers[prog] = {
            "millesime": f"indicateurs {annees_ind[0]}-{annees_ind[-1]}" if annees_ind else "aucun indicateur publié",
            "source": " ; ".join(f"{s} : {url_par_lib.get(s, s)}" for s in utilisees)
                      or "site/data/realisations (aucun indicateur publié)",
            "collecte_le": collecte_le, "programme": prog, "libelle": r["libelle"], "mission": r["mission"],
            "avertissement": AVERTISSEMENTS[0] + " " + AVERTISSEMENTS[1],
            "sources": {s: url_par_lib.get(s, s) for s in utilisees},
            "credits": credits_programme(r, autres), "credits_lecture": (
                "Voté : budget voté (loi de finances initiale) ; dépensé : dépense constatée en fin d'année "
                "(crédits de paiement), tous deux repris de site/data/realisations. Les crédits et les indicateurs "
                "d'une même année sont posés côte à côte, sans lien de cause publié."),
            "credits_source": f"site/data/realisations/{prog}.json ({r['millesime']})",
            "nombre_indicateurs": len(inds), "nombre_lignes": n_lignes,
            "series_sans_valeur_publiee": len(tous) - len(inds),
            "lecture": ("Table : année, mission, programme, objectif, indicateur, unité, cible, réalisé, source ; "
                        "mission et programme sont en tête du fichier, objectif, indicateur et unité en tête de "
                        "chaque série, une ligne par année. `cible_publiee` et `realise_publie` : texte publié "
                        "(une valeur non chiffrée y reste, la valeur numérique est alors null) ; une clé absente : "
                        "rien de publié pour cette année."),
            "series": series,
            "correspondance": corr,
            "note": None if inds else (r["resultats_mesures"].get("note") or
                                        "Aucun indicateur de performance publié pour ce programme."),
        }
        resume.append({"programme": prog, "libelle": r["libelle"], "mission": r["mission"],
                       "nombre_indicateurs": len(inds), "nombre_lignes": n_lignes,
                       "annees": annees_ind, "fichier": f"performance/programmes/{prog}.json"})
        if corr:
            par_prog.append({"programme": prog, "libelle": r["libelle"], "mission": r["mission"],
                             "libelle_modifie": sum("libellé modifié" in c["statuts"] for c in corr),
                             "absent_des_documents_2025": sum("absent des documents 2025" in c["statuts"]
                                                              for c in corr),
                             "fichier": f"performance/programmes/{prog}.json"})
    correspondance = {
        "millesime": "documents de performance 2015 à 2025 (RAP et PAP)",
        "source": " ; ".join(f"{k} : {v}" for k, v in url_par_lib.items()),
        "collecte_le": collecte_le,
        "documents_recents": list(DOCUMENTS_RECENTS),
        "methode": CORR_METHODE,
        "emplacement": "table complète par programme : champ `correspondance` de performance/programmes/<programme>.json",
        "limites": [LIMITES[0], LIMITES[1],
                    "La source retenue pour une année est la plus récente qui la publie : une série reprise à "
                    "l'identique dans un document 2025 mais sans aucune valeur ni cible lisible y serait comptée "
                    "absente."] + ([] if rap is not None else
                                   ["RAP 2025 brut absent de l'entrepôt : `meme_code_au_rap_2025` non renseigné."]),
        "comptes": comptes,
        "programmes": par_prog,
    }
    return fichiers, correspondance, {"programmes": resume, "sources": url_par_lib, "ordre_sources": ordre,
                                      "comptes": comptes}


# --- baromètre de la DITP ------------------------------------------------------------------------------------------


def _csv(p: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig"))))


def code_departement(zone: str) -> str:
    """« D01 » -> « 01 », « D2A » -> « 2A », « D971 » -> « 971 »."""
    if not re.fullmatch(r"D(\d{2,3}|2[AB])", zone):
        raise ValueError(f"code de département inattendu : {zone}")
    return zone[1:]


def lire_barometre() -> dict:
    meta_p, ch_p, terr_p = LAKE_DITP / "meta_indicateurs.csv", LAKE_DITP / "meta_chantiers.csv", \
        LAKE_DITP / "dict-territoires.csv"
    if not meta_p.exists() or not ch_p.exists() or not terr_p.exists():
        raise SystemExit(f"{LAKE_DITP} incomplet : lancer `python pipeline/performance.py collecter`")
    chantiers = {r["chantier_id"]: r for r in _csv(ch_p)}
    territoires = {r["territoire_code"]: r["territoire_nom"] for r in _csv(terr_p)}
    meta = sorted(_csv(meta_p), key=lambda r: int(re.sub(r"\D", "", r["indic_id"]) or 0))
    indicateurs, absents, zones = [], [], {}
    for m in meta:
        iid = m["indic_id"]
        p = LAKE_DITP / f"{iid.lower()}.csv"
        if not p.exists():
            absents.append(iid)
            continue
        ch = chantiers.get(m["indic_parent_ch"], {})
        nb = 0
        for r in _csv(p):
            if r["indic_id"] != iid or not r["metric_enforce_date"]:
                continue
            if r["maille"] == "DEPT":
                zone = code_departement(r["enforce_zone_id"])
            elif r["maille"] == "NAT":
                zone = "FR"
            else:
                continue   # régions : non reprises (la page est départementale)
            date = r["metric_enforce_date"]
            z = zones.setdefault(zone, {}).setdefault(iid, {"initiale": [], "valeurs": [], "cibles": []})
            for col, cle in (("indic_vi", "initiale"), ("indic_va", "valeurs"), ("indic_vc", "cibles")):
                v = nombre_ditp(r[col])
                if v is not None:
                    z[cle].append([date, v])
                    nb += 1
        indicateurs.append({
            "id": iid, "chantier_id": m["indic_parent_ch"], "chantier": ch.get("ch_nom"),
            "engagement": ch.get("engagement_short"), "intitule": m["indic_nom_baro"] or m["indic_nom"],
            "description_publiee": m["indic_descr_baro"] or m["indic_descr"] or None,
            "sens_publie": m["tendance"] or None, "categorie_evolution_publiee": m["indic_categorie_evolution"] or None,
            "nombre_valeurs": nb})
    for zone in zones.values():
        for z in zone.values():
            for cle in z:
                z[cle].sort(key=lambda x: x[0])
    return {"indicateurs": indicateurs, "absents": absents, "zones": zones, "territoires": territoires}


def construire_barometre(b: dict, collecte_le: str) -> dict[str, dict]:
    src = (f"Direction interministérielle de la transformation publique (DITP), « Baromètre des résultats de "
           f"l'action publique » : {URL_DITP_DG} ; fichiers indicateurs : {URL_DITP_DEPOT}")
    dates = sorted({x[0] for zone in b["zones"].values() for z in zone.values() for k in z for x in z[k]})
    millesime = f"valeurs datées de {dates[0][:7]} à {dates[-1][:7]}" if dates else "aucune valeur"
    sortie = {}
    deps = []
    for code in sorted(b["zones"], key=lambda c: (c == "FR", c.zfill(3))):
        zone = b["zones"][code]
        nom = "France" if code == "FR" else b["territoires"].get(f"D{code}")
        if nom is None:
            raise SystemExit(f"baromètre : département {code} absent du dictionnaire des territoires")
        inds = [{"id": iid, **zone[iid]} for iid in sorted(zone, key=lambda x: int(re.sub(r"\D", "", x)))
                if any(zone[iid].values())]
        sortie[f"barometre/{code}.json"] = {
            "millesime": millesime, "source": src, "collecte_le": collecte_le, "code": code, "nom": nom,
            "lecture": ("Pour chaque indicateur : valeur initiale (situation de départ choisie par la DITP), "
                        "valeurs publiées successivement et cible, chacune sous la forme [date, valeur], telles que "
                        "publiées."),
            "indicateurs": inds}
        if code != "FR":
            deps.append({"code": code, "nom": nom, "nombre_indicateurs": len(inds)})
    sortie["barometre/index.json"] = {
        "millesime": millesime, "source": src, "collecte_le": collecte_le,
        "presentation": ("Le baromètre des résultats de l'action publique suit les politiques prioritaires du "
                         "Gouvernement : pour chaque indicateur, une valeur initiale, les valeurs successives et une "
                         "cible, en France et par département. Il n'est pas relié par la source à un programme du "
                         "budget ni à des crédits."),
        "avertissement": ("Indicateurs et cibles choisis par le Gouvernement ; l'écart à la cible n'est ni un succès "
                          "ni un échec en soi."),
        "regle": ("Valeurs reprises telles que publiées (colonnes valeur initiale, valeur actuelle, valeur cible) ; "
                  "le taux d'avancement calculé par la DITP n'est pas repris ; valeurs régionales non reprises ; "
                  "aucune valeur absente remplacée par 0."),
        "sens_publie_lecture": ("« hausse » ou « baisse » : sens d'évolution recherché publié par la DITP pour "
                                "l'indicateur (colonne tendance)."),
        "licence": LO, "indicateurs": b["indicateurs"], "indicateurs_non_collectes": b["absents"],
        "departements": deps, "france": "performance/barometre/FR.json",
        "fichier_departement": "performance/barometre/<code>.json"}
    return sortie


# --- index ---------------------------------------------------------------------------------------------------------


def construire_index(res: dict, corr: dict, baro: dict, collecte_le: str) -> dict:
    missions: dict[str, list] = {}
    for p in res["programmes"]:
        missions.setdefault(p["mission"], []).append(p)
    bi = baro["barometre/index.json"]
    n_lignes = sum(p["nombre_lignes"] for p in res["programmes"])
    annees = sorted({a for p in res["programmes"] for a in p["annees"]})
    return {
        "millesime": f"indicateurs de performance {annees[0]} à {annees[-1]} (documents de performance ouverts "
                     f"2015 à 2025) ; baromètre DITP " + bi["millesime"],
        "source": (f"RAP 2025 : {URL_RAP2025_DG} ; PAP 2025 : {URL_PAP2025_DG} ; éditions antérieures : "
                   "data.economie.gouv.fr (voir sources_performance) ; baromètre : " + URL_DITP_DG),
        "collecte_le": collecte_le, "presentation": PRESENTATION, "avertissements": AVERTISSEMENTS,
        "regles": REGLES, "limites": LIMITES, "recherche_publique": RECHERCHE_PUBLIQUE,
        "sources_performance": res["sources"],
        "miroirs_data_gouv": {"RAP 2025": URL_RAP2025_DG, "PAP 2025": URL_PAP2025_DG},
        "non_exploites": [
            {"source": "Rapports d'évaluation des politiques de sécurité sociale (REPSS)", "url": URL_REPSS,
             "motif": "rapports en PDF ; données des graphiques en classeurs (un onglet par graphique, sans colonnes "
                      "cible et réalisé), dernière édition PLFSS 2022 : non exploitable sans lecture au cas par cas"},
            {"source": "Baromètre de la DITP, colonne « taux d'avancement »", "url": URL_DITP_DG,
             "motif": "calcul de la DITP rapportant la valeur à la cible : assimilable à une note, non repris"}],
        "comptes": {"programmes": len(res["programmes"]),
                    "programmes_avec_indicateurs": sum(1 for p in res["programmes"] if p["nombre_indicateurs"]),
                    "series": corr["comptes"]["series"], "lignes": n_lignes,
                    "code_encore_au_rap_2025": corr["comptes"]["code_encore_au_rap_2025"],
                    "libelle_modifie": corr["comptes"]["libelle_modifie"],
                    "absent_des_documents_2025": corr["comptes"]["absent_des_documents_2025"],
                    "indicateurs_barometre": len(bi["indicateurs"]),
                    "departements_barometre": len(bi["departements"])},
        "missions": [{"mission": m, "programmes": sorted(ps, key=lambda p: p["programme"])}
                     for m, ps in sorted(missions.items())],
        "fichiers": {"programme": "performance/programmes/<programme>.json",
                     "correspondance": "performance/correspondance.json",
                     "barometre": "performance/barometre/index.json"},
        "liens": {"realisations": "realisations/<programme>.json", "arbre": "arbre/racine.json",
                  "millesimes": "millesimes/execution2025/racine.json"},
        "ordre": "Missions dans l'ordre alphabétique, programmes par numéro ; aucun classement par résultat.",
    }


def produire(sortie: Path = SORTIE) -> dict:
    if not (SITE / "realisations" / "index.json").exists():
        raise SystemExit("site/data/realisations absent : lancer `python pipeline/realisations.py produire`")
    collecte_le = date_sources(DOMAINE, "etat")
    fichiers, corr, res = construire_programmes(collecte_le)
    baro = construire_barometre(lire_barometre(), collecte_le)
    idx = construire_index(res, corr, baro, collecte_le)
    # nettoyage des anciennes sorties de ce module seulement
    for p in sorted(sortie.glob("programmes/*.json")) + sorted(sortie.glob("barometre/*.json")):
        p.unlink()
    for prog, d in fichiers.items():
        ecrire(sortie, f"programmes/{prog}.json", d)
    for nom, d in baro.items():
        ecrire(sortie, nom, d)
    ecrire(sortie, "correspondance.json", corr)
    ecrire(sortie, "index.json", idx)
    return idx


def collecter() -> int:
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), ID_DITP], cwd=ROOT)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = ap.add_subparsers(dest="commande", required=True)
    sous.add_parser("collecter")
    p = sous.add_parser("produire")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.commande == "collecter":
        return collecter()
    idx = produire(a.sortie)
    print(json.dumps(idx["comptes"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
