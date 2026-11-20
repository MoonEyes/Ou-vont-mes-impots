"""Compléments OFGL pour « Ma commune » : solidarité entre territoires (FPIC), flux entre communes et
intercommunalité, comptes des services d'incendie et de secours (SDIS), patrimoine réévalué, établissements publics
locaux (EPA, régies personnalisées, GIP).

Entrées (réseau, `collecter`, reprenable) : exports Parquet de l'API Explore v2.1 de data.ofgl.fr, filtrés côté
serveur (colonnes et agrégats retenus seulement), contrôlés par collecte/integrite.py (fetch.remplacer_si_valide)
  -> data/lake/ofgl_complements/<jeu>.parquet, meta_<jeu>.json (licence, date de mise à jour lues sur la fiche)
  et, pour les établissements publics locaux, la catégorie juridique SIRENE de chaque SIREN (pipeline/sirene.py,
  cache partagé data/lake/_cache/recherche_entreprises.json).
Lecture seule : site/data/local/geo/<dep>.json (code officiel géographique en vigueur, SIREN des communes et EPCI).
Sorties (site/data/ofgl_complements/, chaque fichier < 1 Mo, `millesime` et `source` partout) :
  index.json           jeux, licences, définitions, règles, couverture, recherche publique
  communes/<dep>.json  par commune : flux avec l'intercommunalité (2025) et patrimoine (2025) ; par intercommunalité
                       (département du siège) : FPIC 2018-2026, flux 2019-2025, patrimoine 2025 ; SDIS du département ;
                       établissements publics locaux du département (personnes morales seulement)
  sdis.json            tous les SDIS, exercices 2012-2025 (écran Explorer « Collectivités »)

Règles :
  - aucune somme entre ces montants et les budgets publiés ailleurs (local/budgets) : les flux, contributions au SDIS
    et dépenses des établissements rattachés figurent déjà dans les comptes des collectivités ; publiés à part ;
  - montants publiés tels que l'OFGL les écrit (euros, euros par habitant quand l'OFGL les publie) ; valeur absente :
    null, jamais 0 ; aucun ratio calculé par le site (règle 13) ;
  - FPIC et flux : licence non renseignée sur le portail OFGL, même traitement que `dotations-communes` déjà repris
    par pipeline/local.py (données publiques de la DGCL et de la DGFiP diffusées par l'OFGL), noté dans index.json ;
  - établissement public local nommé seulement si sirene.personne_morale(catégorie juridique) ; nom passé par
    local.objet_publiable ; sinon compté sans nom ;
  - dates : date de collecte écrite par `collecter` dans data/lake/ofgl_complements/collecte.json, sinon
    pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques octet pour octet.

Commandes :
  python pipeline/ofgl_complements.py collecter   # réseau ; un refus 401/403/429 est noté, jamais contourné
  python pipeline/ofgl_complements.py produire    # sans réseau ; --sortie DOSSIER pour une copie de contrôle
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "ofgl_complements"
SITE = ROOT / "site" / "data"
GEO = SITE / "local" / "geo"
SORTIE = SITE / "ofgl_complements"
MAX_OCTETS = 1_000_000
OFGL = "https://data.ofgl.fr/api/explore/v2.1/catalog/datasets"
PAGE = "https://data.ofgl.fr/explore/dataset/{}/"
ENTETE_HTTP = {"User-Agent": "ou-vont-mes-impots/pipeline"}

FPIC = {"prelevement": "Montant FPIC - Prélèvement", "versement": "Montant FPIC - Versement",
        "solde": "Montant FPIC - Solde", "garantie": "Montant de la garantie de reversement"}
FLUX_COM = ["ac_recettes_reelles_com", "ac_depenses_reelles_com", "ac_inv_recettes_reelles_com",
            "ac_inv_depenses_reelles_com", "dsc_recettes_reelles_com", "dsc_depenses_reelles_com"]
FLUX_EPCI = {
    "ac_fonct": "Attribution de compensation en fonctionnement",
    "ac_inv": "Attribution de compensation en investissement",
    "dsc": "Dotation de solidarité communautaire",
    "dotation_equilibre": "Dotation équilibre",
    "fcct": "Fonds de compensation des charges territoriales",
    "remb_frais": "Remboursements de frais",
    "remb_personnel": "Remboursements de frais de personnel",
    "subv_fonct": "Subventions de fonctionnement",
    "subv_equip": "Subventions équipement",
}
SUFFIXES_EPCI = {"Subventions de fonctionnement": ("reçues - recettes", "versées - dépenses"),
                 "Subventions équipement": ("reçues - recettes", "versées - dépenses")}
PATRIMOINE = {"actif_brut": "Actif brut", "actif_net": "Actif net", "actif_brut_hab": "Actif brut par habitant",
              "actif_net_hab": "Actif net par habitant", "taux_vetuste": "Taux de vétusté",
              "dotation_amortissements": "Dotation aux amortissements",
              "duree_vie_moyenne": "Durée de vie moyenne (DVM)"}
SDIS = {"depenses_totales_hors_remb": "Dépenses totales hors remb", "depenses_fonctionnement": "Dépenses de fonctionnement",
        "depenses_investissement_hors_remb": "Dépenses d'investissement hors remb", "frais_personnel": "Frais de personnel",
        "participations_departements": "Participations des départements",
        "participations_communes": "Participations des communes",
        "participations_gfp": "Participations des groupements à fiscalité propre", "encours_dette": "Encours de dette"}
EPL = {"depenses_totales_hors_remb": "Dépenses totales hors remb", "depenses_fonctionnement": "Dépenses de fonctionnement",
       "frais_personnel": "Frais de personnel", "subventions_participations_recues": "Subventions reçues et participations",
       "encours_dette": "Encours de dette"}
ANNEES_SDIS = list(range(2012, 2026))
ANNEES_EPL = list(range(2018, 2026))


def _liste(valeurs) -> str:
    return ", ".join('"' + v.replace('"', '\\"') + '"' for v in valeurs)


def _flux_epci_libelles() -> list[str]:
    out = []
    for lib in FLUX_EPCI.values():
        rec, dep = SUFFIXES_EPCI.get(lib, ("recettes", "dépenses"))
        if lib in SUFFIXES_EPCI:
            base = "Subventions de fonctionnement" if "fonctionnement" in lib else "Subventions équipement"
            out += [f"{base} {rec}", f"{base} {dep}"]
        else:
            out += [f"{lib} - {rec}", f"{lib} - {dep}"]
    return out


JEUX = {
    "fpic": {"id": "fpic-ensembles-intercommunaux", "titre": "OFGL, « FPIC des ensembles intercommunaux » (données DGCL)",
             "select": "exercice,siren,nom_epci,code_departement,nature_juridique,variable,valeur",
             "where": f"categorie=\"FPIC\" and unite=\"euros\" and variable in ({_liste(FPIC.values())})"},
    "flux_communes": {"id": "base-communale-flux-financiers",
                      "titre": "OFGL, « Flux financiers entre communes et intercommunalités, base communale » (comptes de gestion 2025)",
                      "select": "exer,insee,siren_com,siren_epci," + ",".join(FLUX_COM),
                      "where": "type_de_budget=\"Budget principal\""},
    "flux_epci": {"id": "base-intercommunale-flux-financiers",
                  "titre": "OFGL, « Flux financiers entre communes et intercommunalités, base intercommunale » (comptes de gestion 2019-2025)",
                  "select": "exer,siren,epci_name,dep_code,agregat,montant",
                  "where": f"type_de_budget=\"Budget principal\" and agregat in ({_liste(_flux_epci_libelles())})"},
    "sdis": {"id": "ofgl-base-sdis", "titre": "OFGL, « Comptes des SDIS 2012-2025 » (données DGFiP)",
             "select": "exer,code_dep,nom_dep,siren,agregat,montant,euros_par_habitant,population_totale",
             "where": f"cbudg=\"1\" and agregat in ({_liste(SDIS.values())})"},
    "actifs_communes": {"id": "actifs_communes", "titre": "OFGL, « Patrimoine réévalué des communes » (2025)",
                        "select": "insee,siren,variable,valeur,annee",
                        "where": f"variable in ({_liste(PATRIMOINE.values())})"},
    "actifs_gfp": {"id": "actifs-gfp", "titre": "OFGL, « Patrimoine réévalué des groupements à fiscalité propre » (2025)",
                   "select": "siren,variable,valeur,annee",
                   "where": f"variable in ({_liste(PATRIMOINE.values())})"},
    "epl": {"id": "ofgl-base-epl", "titre": "OFGL, « Comptes des établissements publics locaux 2018-2025 » (EPA, régies personnalisées, GIP ; données DGFiP)",
            "select": "exer,siren,nom_epl,dep_code,categorie_epl_abr,libelle_cacti_simplifie,type_de_budget,agregat,montant",
            "where": f"agregat in ({_liste(EPL.values())})"},
}
LICENCE_DEFAUT = "Licence Ouverte 2.0"
NOTE_LICENCE = ("licence non renseignée sur la fiche du portail OFGL au moment de la collecte : même traitement que le "
                "jeu `dotations-communes` déjà repris par le site (données publiques de la DGCL et de la DGFiP diffusées "
                "par l'OFGL, réutilisées avec mention de la source)")

DEFINITIONS = {
    "fpic": ("Fonds national de péréquation des ressources intercommunales et communales : les ensembles "
             "intercommunaux (intercommunalité et ses communes) dont le potentiel financier est élevé versent un "
             "prélèvement, ceux qui remplissent les critères (potentiel financier, revenu, effort fiscal) reçoivent un "
             "reversement. Montants de l'ensemble intercommunal, avant répartition entre l'intercommunalité et ses "
             "communes. Solde = reversement moins prélèvement, publié par la DGCL."),
    "flux_communes": ("Flux entre la commune et son intercommunalité, comptes de gestion 2025, budget principal : "
                      "attribution de compensation (fonctionnement, investissement) reçue ou versée par la commune, "
                      "dotation de solidarité communautaire reçue ou versée. Seuls indicateurs dont les montants "
                      "concordent assez entre comptes des communes et des intercommunalités selon l'OFGL."),
    "flux_epci": ("Mêmes flux vus du côté de l'intercommunalité, budget principal, 2019 à 2025 : recettes et dépenses "
                  "pour l'attribution de compensation, la dotation de solidarité communautaire, la dotation "
                  "d'équilibre, le fonds de compensation des charges territoriales, les remboursements de frais et de "
                  "personnel, les subventions de fonctionnement et d'équipement (comptes listés par l'OFGL)."),
    "patrimoine": ("Patrimoine réévalué au 31 décembre 2025 par l'OFGL à partir des comptes de gestion : actif brut "
                   "(valeur d'acquisition des immobilisations), actif net (après amortissements), taux de vétusté, "
                   "dotation aux amortissements, durée de vie moyenne. Méthode de réévaluation propre à l'OFGL."),
    "sdis": ("Comptes du service départemental d'incendie et de secours, budget principal : dépenses, frais de "
             "personnel, participations reçues des départements, des communes et des intercommunalités, encours de "
             "dette ; euros par habitant tels que publiés par l'OFGL."),
    "epl": ("Établissements publics locaux rattachés aux collectivités : établissements publics administratifs (EPA), "
            "régies personnalisées (EPIC, établissements publics de coopération culturelle), groupements d'intérêt "
            "public (dont maisons départementales des personnes handicapées). Tous budgets de l'établissement "
            "additionnés par l'OFGL (budget principal et annexes) quand il en publie plusieurs lignes, sinon budget "
            "publié."),
}
REGLES = [
    "Montants repris tels que l'OFGL les publie ; valeur absente à la source : null, jamais 0.",
    "Jamais additionnés aux budgets des collectivités publiés ailleurs sur le site : les flux, les contributions "
    "au SDIS et les dépenses des établissements rattachés y figurent déjà.",
    "Aucun ratio ni écart calculé par le site ; les montants par habitant sont ceux de l'OFGL.",
    "Établissement public local nommé seulement si le répertoire SIRENE le classe comme personne morale.",
]
RECHERCHE_PUBLIQUE = [
    {"trouvaille": "API Explore v2.1 de data.ofgl.fr (exports Parquet filtrés côté serveur)",
     "classement": "réutilisable tel quel", "licence": "Licence Ouverte 2.0 (sauf FPIC et flux : non renseignée)",
     "dernier_commit": None, "note": "client déjà écrit dans pipeline/local_satellites.py (telecharger)"},
    {"trouvaille": "pipeline/local.py (dotations-communes, même portail, même traitement de licence)",
     "classement": "réutilisable tel quel", "licence": "celle du dépôt", "dernier_commit": None},
    {"trouvaille": "podolskyDavid/h-genai (analyse des données OFGL)", "classement": "inspiration seulement",
     "licence": "aucune déclarée", "dernier_commit": "2025-12-07"},
    {"trouvaille": "OFGL, étude « Cap sur les flux financiers entre communes et intercommunalités »",
     "classement": "inspiration seulement", "licence": "non précisée", "dernier_commit": None,
     "note": "méthode des trois indicateurs concordants reprise telle quelle"},
]


# --- Collecte ---------------------------------------------------------------------------------------------------------

def meta_jeu(cle: str) -> dict | None:
    import requests
    jid = JEUX[cle]["id"]
    for i in range(6):
        try:
            r = requests.get(f"{OFGL}/{jid}", timeout=60, headers=ENTETE_HTTP)
            if r.status_code in (401, 403, 429, 451):
                return None
            r.raise_for_status()
            d = r.json()
            m = d["metas"]["default"]
            return {"id": jid, "licence": m.get("license"), "modifie": (m.get("modified") or "")[:10],
                    "lignes": m.get("records_count")}
        except Exception:
            time.sleep(4 * (i + 1))
    return None


def collecter(forcer: bool = False) -> dict:
    import local_satellites
    LAKE.mkdir(parents=True, exist_ok=True)
    etat = {}
    for cle, j in JEUX.items():
        dest = LAKE / f"{cle}.parquet"
        if dest.exists() and dest.stat().st_size and not forcer:
            etat[cle] = "présent"
        else:
            etat[cle] = local_satellites.telecharger(f"{OFGL}/{j['id']}/exports/parquet", dest,
                                                     {"select": j["select"], "where": j["where"]}, essais=8)
            m = meta_jeu(cle)
            if m:
                (LAKE / f"meta_{cle}.json").write_text(json.dumps(m, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        print(f"{cle}: {etat[cle]}", flush=True)
    # catégories juridiques des établissements publics locaux
    if (LAKE / "epl.parquet").exists():
        import sirene
        con = _duck()
        sirens = sorted({s for (s,) in con.execute(f"select distinct siren from '{LAKE / 'epl.parquet'}'").fetchall()
                         if sirene.siren_valide(s)})
        cache, restants = sirene.resoudre(sirens, budget_s=1800)
        cj = {s: (cache.get(s) or {}).get("cj") for s in sirens}
        (LAKE / "epl_categories.json").write_text(json.dumps(cj, sort_keys=True), encoding="utf-8")
        etat["epl_categories"] = f"{len(sirens) - restants} SIREN résolus, {restants} restants"
    if any(v == "ok" for v in etat.values()) or not (LAKE / "collecte.json").exists():
        (LAKE / "collecte.json").write_text(json.dumps({"collecte_le": time.strftime("%Y-%m-%d", time.gmtime())}),
                                            encoding="utf-8")
    return etat


# --- Production -------------------------------------------------------------------------------------------------------

def _duck():
    import duckdb
    return duckdb.connect()


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets ({n}) : découper")
    path.write_text(texte + "\n", encoding="utf-8")
    return n


def date_collecte() -> str:
    try:
        return json.loads((LAKE / "collecte.json").read_text(encoding="utf-8"))["collecte_le"]
    except (OSError, ValueError, KeyError):
        return date_sources()


def meta(cle: str) -> dict:
    try:
        return json.loads((LAKE / f"meta_{cle}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def euros(v) -> int | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return int(round(f))


def nombre(v, chiffres: int = 2):
    if v is None:
        return None
    f = float(v)
    if f != f:
        return None
    r = round(f, chiffres)
    return int(r) if r == int(r) else r


def valeur_patrimoine(variable: str, valeur):
    """Montants en euros arrondis à l'euro ; montants par habitant, taux et durées à deux décimales (tels que publiés)."""
    return euros(valeur) if variable in ("Actif brut", "Actif net", "Dotation aux amortissements") else nombre(valeur)


def geographie() -> tuple[dict, dict, dict]:
    """communes (insee -> info), epci (siren -> info), siren de commune -> insee."""
    communes, epci, siren_com = {}, {}, {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for code, c in d["communes"].items():
            communes[code] = {**c, "departement": d["departement"]["code"]}
            if c.get("siren"):
                siren_com[c["siren"]] = code
        for s, e in d["epci"].items():
            epci.setdefault(s, {"nom": e["nom"], "departement_siege": e.get("departement_siege")})
    return communes, epci, siren_com


def lire(cle: str, sql: str) -> list[tuple]:
    p = LAKE / f"{cle}.parquet"
    if not p.exists():
        raise SystemExit(f"{p} absent : lancer `python pipeline/ofgl_complements.py collecter`")
    return _duck().execute(sql.replace("{f}", f"'{p}'")).fetchall()


def propre(v) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()


def produire(sortie: Path = SORTIE) -> dict:
    import local
    import sirene
    communes, epci, siren_com = geographie()
    date = date_collecte()
    stats = defaultdict(int)

    # FPIC par ensemble intercommunal (SIREN de l'EPCI, ou de la commune isolée)
    fpic = defaultdict(lambda: defaultdict(lambda: [None] * len(FPIC)))
    cles_fpic = list(FPIC)
    par_lib = {v: cles_fpic.index(k) for k, v in FPIC.items()}
    for ex, siren, variable, valeur in lire("fpic", "select year(cast(exercice as date)), lpad(cast(siren as varchar), 9, '0'), variable, sum(valeur) from {f} group by all order by all"):
        fpic[siren][str(ex)][par_lib[variable]] = euros(valeur)
    annees_fpic = sorted({a for s in fpic.values() for a in s})

    # Flux, base communale 2025
    flux_com = {}
    for row in lire("flux_communes", "select cast(exer as varchar), insee, " + ", ".join(f"sum({c})" for c in FLUX_COM) + " from {f} group by all order by all"):
        an, insee = str(row[0])[:4], row[1]
        if insee in communes:
            flux_com[insee] = {"annee": an, "v": [euros(x) for x in row[2:]]}
        else:
            stats["flux_communes_hors_cog"] += 1
    annee_flux_com = sorted({v["annee"] for v in flux_com.values()})

    # Flux, base intercommunale 2019-2025 : clé -> [recettes, dépenses]
    flux_epci = defaultdict(lambda: defaultdict(lambda: [None] * (2 * len(FLUX_EPCI))))
    libs = _flux_epci_libelles()
    for ex, siren, agregat, montant in lire("flux_epci", "select cast(exer as varchar), siren, agregat, sum(montant) from {f} group by all order by all"):
        flux_epci[str(siren)][str(ex)[:4]][libs.index(agregat)] = euros(montant)
    annees_flux_epci = sorted({a for s in flux_epci.values() for a in s})

    # Patrimoine 2025
    cles_pat = list(PATRIMOINE)
    lib_pat = {v: cles_pat.index(k) for k, v in PATRIMOINE.items()}
    pat_com, pat_gfp, annees_pat = {}, {}, set()
    for insee, variable, valeur, annee in lire("actifs_communes", "select insee, variable, valeur, annee from {f} order by all"):
        if insee not in communes:
            stats["patrimoine_hors_cog"] += 1
            continue
        annees_pat.add(str(annee))
        pat_com.setdefault(insee, [None] * len(cles_pat))[lib_pat[variable]] = valeur_patrimoine(variable, valeur)
    for siren, variable, valeur, annee in lire("actifs_gfp", "select siren, variable, valeur, annee from {f} order by all"):
        annees_pat.add(str(annee))
        pat_gfp.setdefault(str(siren), [None] * len(cles_pat))[lib_pat[variable]] = valeur_patrimoine(variable, valeur)

    # SDIS (budget principal), par département
    cles_sdis = list(SDIS)
    lib_sdis = {v: cles_sdis.index(k) for k, v in SDIS.items()}
    sdis = {}
    for ex, dep, nom_dep, siren, agregat, montant, eph, pop in lire("sdis", "select year(cast(exer as date)), code_dep, nom_dep, siren, agregat, sum(montant), sum(euros_par_habitant), max(population_totale) from {f} group by all order by all"):
        s = sdis.setdefault(dep, {"departement": nom_dep, "siren": siren, "annees": {}, "par_habitant": {}, "population": {}})
        a = str(ex)
        s["annees"].setdefault(a, [None] * len(cles_sdis))[lib_sdis[agregat]] = euros(montant)
        s["par_habitant"].setdefault(a, [None] * len(cles_sdis))[lib_sdis[agregat]] = nombre(eph)
        if pop:
            s["population"][a] = int(pop)
    annees_sdis = sorted({a for s in sdis.values() for a in s["annees"]})

    # Établissements publics locaux : tous budgets publiés pour un SIREN additionnés par exercice (même source)
    try:
        cj_epl = json.loads((LAKE / "epl_categories.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cj_epl = {}
    cles_epl = list(EPL)
    lib_epl = {v: cles_epl.index(k) for k, v in EPL.items()}
    budgets_epl = {t for (t,) in lire("epl", "select distinct type_de_budget from {f}")}
    filtre_budget = ("type_de_budget = 'Budget principal + Budget(s) annexe(s)'"
                     if "Budget principal + Budget(s) annexe(s)" in budgets_epl else "true")
    epl = {}
    for ex, siren, nom, dep, cat, activite, agregat, montant in lire(
            "epl", "select year(cast(exer as date)), siren, max(nom_epl), max(dep_code), max(categorie_epl_abr), "
                   "max(libelle_cacti_simplifie), agregat, sum(montant) from {f} where " + filtre_budget
                   + " group by year(cast(exer as date)), siren, agregat order by all"):
        siren = str(siren)
        e = epl.setdefault(siren, {"dep": dep, "nom": nom, "categorie": cat, "activite": activite, "annees": {}})
        e["annees"].setdefault(str(ex), [None] * len(cles_epl))[lib_epl[agregat]] = euros(montant)
    annees_epl = sorted({a for e in epl.values() for a in e["annees"]})

    # Assemblage par département
    par_dep = defaultdict(lambda: {"communes": {}, "epci": {}, "organismes": []})
    for insee, c in communes.items():
        d = {}
        if insee in flux_com:
            d["flux"] = flux_com[insee]["v"]
        if insee in pat_com:
            d["patrimoine"] = pat_com[insee]
        siren_c = c.get("siren")
        if not c.get("epci") and siren_c in fpic:
            d["fpic"] = {a: fpic[siren_c][a] for a in sorted(fpic[siren_c])}
        if d:
            par_dep[c["departement"]]["communes"][insee] = d
    for s, e in epci.items():
        d = {}
        if s in fpic:
            d["fpic"] = {a: fpic[s][a] for a in sorted(fpic[s])}
        if s in flux_epci:
            d["flux"] = {a: flux_epci[s][a] for a in sorted(flux_epci[s])}
        if s in pat_gfp:
            d["patrimoine"] = pat_gfp[s]
        if d and e.get("departement_siege"):
            par_dep[e["departement_siege"]]["epci"][s] = {"nom": e["nom"], **d}
    fpic_non_rattache = sorted(set(fpic) - set(epci) - {c.get("siren") for c in communes.values()})
    stats["fpic_ensembles"] = len(fpic)
    stats["fpic_non_rattaches"] = len(fpic_non_rattache)

    nommes = sans_nom = 0
    for siren, e in sorted(epl.items()):
        dep = e["dep"]
        if not dep:
            continue
        cj = cj_epl.get(siren)
        nom = local.objet_publiable(propre(e["nom"])) if sirene.personne_morale(cj) else None
        if nom:
            nommes += 1
        else:
            sans_nom += 1
        par_dep[dep]["organismes"].append([siren if nom else None, nom, e["categorie"], local.objet_publiable(propre(e["activite"])) if e["activite"] else None,
                                           {a: e["annees"][a] for a in sorted(e["annees"])}])
    stats["epl_nommes"], stats["epl_sans_nom"] = nommes, sans_nom

    entete = {"millesime": f"FPIC {annees_fpic[0]}-{annees_fpic[-1]}, flux {annees_flux_epci[0]}-{annees_flux_epci[-1]}, "
                           f"patrimoine {'-'.join(sorted(annees_pat))}, SDIS {annees_sdis[0]}-{annees_sdis[-1]}, "
                           f"établissements publics locaux {annees_epl[0]}-{annees_epl[-1]} ; collecte du {date}",
              "source": " ; ".join(PAGE.format(JEUX[k]["id"]) for k in JEUX)}
    colonnes = {"fpic": cles_fpic, "flux_communes": FLUX_COM,
                "flux_epci": [f"{k}_{s}" for k in FLUX_EPCI for s in ("recettes", "depenses")],
                "patrimoine": cles_pat, "sdis": cles_sdis, "organismes": ["siren", "nom", "categorie", "activite", "annees"],
                "epl": cles_epl}

    if sortie.exists():
        for f in sorted((sortie / "communes").glob("*.json")):
            f.unlink()
    deps = sorted({c["departement"] for c in communes.values()})
    tailles = []
    for dep in deps:
        p = par_dep.get(dep, {"communes": {}, "epci": {}, "organismes": []})
        org = sorted(p["organismes"], key=lambda o: (o[1] is None, o[1] or "", o[0] or ""))
        doc = {**entete, "departement": dep, "colonnes": colonnes,
               "annee_flux_communes": annee_flux_com[-1] if annee_flux_com else None,
               "annee_patrimoine": max(annees_pat) if annees_pat else None,
               "communes": dict(sorted(p["communes"].items())), "epci": dict(sorted(p["epci"].items())),
               "sdis": sdis.get(dep), "organismes": org}
        tailles.append(dump(sortie / "communes" / f"{dep}.json", doc))
    dump(sortie / "sdis.json", {**entete, "source": PAGE.format(JEUX["sdis"]["id"]), "colonnes": cles_sdis,
                                "definition": DEFINITIONS["sdis"], "annees": annees_sdis,
                                "sdis": dict(sorted(sdis.items()))})

    sources = []
    for k, j in JEUX.items():
        m = meta(k)
        lic = m.get("licence")
        sources.append({"id": k, "jeu": j["id"], "titre": j["titre"], "page": PAGE.format(j["id"]),
                        "url": f"{OFGL}/{j['id']}/exports/parquet", "licence": lic or LICENCE_DEFAUT,
                        "licence_note": None if lic else NOTE_LICENCE, "mise_a_jour_source": m.get("modifie") or None,
                        "lignes_source": m.get("lignes")})
    n_com = len(communes)
    couverture = {
        "communes_cog": n_com,
        "communes_flux": len(flux_com), "communes_patrimoine": len(pat_com),
        "epci_cog": len(epci), "epci_fpic": len(set(fpic) & set(epci)), "epci_flux": len(set(flux_epci) & set(epci)),
        "epci_patrimoine": len(set(pat_gfp) & set(epci)), "sdis": len(sdis), "organismes": nommes + sans_nom,
        "organismes_nommes": nommes, "organismes_sans_nom": sans_nom,
        "fpic_ensembles_non_rattaches": len(fpic_non_rattache),
        "flux_communes_hors_cog": stats["flux_communes_hors_cog"], "patrimoine_hors_cog": stats["patrimoine_hors_cog"],
    }
    index = {**entete, "presentation": ("Compléments des comptes des collectivités publiés par l'OFGL : solidarité "
                                        "financière entre territoires, flux entre communes et intercommunalité, "
                                        "services d'incendie et de secours, patrimoine, établissements publics "
                                        "locaux. Rien n'est additionné aux budgets déjà publiés."),
             "annees": {"fpic": annees_fpic, "flux_communes": annee_flux_com, "flux_epci": annees_flux_epci,
                        "patrimoine": sorted(annees_pat), "sdis": annees_sdis, "epl": annees_epl},
             "colonnes": colonnes, "definitions": DEFINITIONS, "regles": REGLES, "sources": sources,
             "couverture": couverture, "recherche_publique": RECHERCHE_PUBLIQUE,
             "fichiers": {"communes": "communes/<dep>.json", "sdis": "sdis.json"},
             "taille_max_octets": max(tailles)}
    dump(sortie / "index.json", index)
    return index


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true")
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        print(json.dumps(collecter(a.forcer), ensure_ascii=False, indent=1))
    if a.etape in ("produire", "tout"):
        idx = produire(a.sortie)
        print(json.dumps(idx["couverture"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
