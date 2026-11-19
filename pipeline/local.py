"""Axe geographique « Pres de chez moi » : ce que depensent la commune, l'intercommunalite, le departement et la region.

Entrees :
  - entrepot data/lake/ (non versionne) : comptes OFGL des GFP, ensembles intercommunaux, departements (et par
    fonction), regions ; dotations des departements ; taux REI (DGFiP) ; projets DETR/DSIL (DGCL) ; subventions
    SCDL (Region Pays de la Loire, Departement 44, Nantes Metropole, Region Bretagne, autres) ; deliberations
    (Region PdL, CD44, Nantes Metropole, Megalis) ; budgets Megalis Bretagne ; CA de Nantes Metropole.
  - API (filtrees, cache data/lake/_cache/local/, reprises sur coupure) : geo.api.gouv.fr (communes, EPCI,
    departements, regions), OFGL ofgl-base-communes-consolidee et dotations-communes par departement,
    dotations-gfp et dotations-regions, stock SIRENE des unites legales (categorie juridique).
Sorties (site/data/local/, chaque fichier porte `millesime` et `source`) :
  geo/<dep>.json                       commune -> population, EPCI, departement, region
  budgets/communes/<dep>.json          grands agregats OFGL par commune (euros et euros par habitant)
  budgets/epci/<dep>.json              idem par EPCI (siege dans le departement) + bloc communal consolide
  budgets/departements.json            idem par departement
  budgets/regions.json                 idem par region
  budgets/fonctions/departements.json  depenses des departements par fonction (OFGL)
  budgets/fonctions/<siren>.json       detail par fonction (pilote 44 et Bretagne : Megalis, CA Nantes Metropole)
  dotations/communes/<dep>.json        DGF et autres dotations de l'Etat par commune (+ DETR/DSIL/DPV/DSID)
  dotations/epci.json, dotations/departements.json, dotations/regions.json
  taux/<dep>.json                      taux d'impots locaux votes (commune, EPCI, syndicats, TSE, GEMAPI, TEOM)
  decisions/<siren>/<annee>.json       subventions votees par collectivite (personnes morales seulement)
  decisions/<siren>/index.json         totaux, exclus agreges, deliberations « subventions », programmes (Region PdL)
  decisions/index.json                 couverture publiee (collectivites couvertes / total)
  index.json                           pour chaque commune, blocs disponibles (masque de bits)

Commandes :
  python pipeline/local.py tout --deps 44,22,29,35,56     # mode departement
  python pipeline/local.py tout --tous                    # France entiere, reprenable (code 3 = a relancer)
  until python pipeline/local.py tout --tous; do sleep 1; done   # une ligne : tout regenerer
Chaque passage est borne par --budget (secondes) ; les telechargements sont mis en cache, on relance pour continuer.

Regle personnes physiques (bloquante) : un beneficiaire n'est nomme que si son SIREN a une categorie juridique 2xxx
a 9xxx dans le stock SIRENE. Le reste (entrepreneurs individuels, personnes physiques, SIREN absent ou inconnu)
est agrege dans `exclus_personnes_physiques_ou_non_identifies`, sans nom.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import requests

import fetch
import sirene
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
OUT = SITE / "local"
CACHE = LAKE / "_cache" / "local"
COLL = LAKE / "collectivites"

OFGL = "https://data.ofgl.fr/api/explore/v2.1/catalog/datasets"
GEO = "https://geo.api.gouv.fr"
SIRENE_URL = ("https://static.data.gouv.fr/resources/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/"
              "20261103-095402/stock-stockunitelegale-parquet.parquet")
SIRENE_PAGE = "https://www.data.gouv.fr/api/1/datasets/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/"

PILOTE = ["44", "22", "29", "35", "56"]
# Pilote + departements de tailles variees (Lozere, Creuse : petits ; Nord, Bouches-du-Rhone : grands ; Paris ; outre-mer)
DEPS_DEFAUT = PILOTE + ["01", "13", "23", "48", "59", "75", "971"]
NB_ANNEES = 4
MAX_OCTETS = 5_000_000
LIGNES_PAR_FICHIER = 10_000

SRC = {
    "ofgl_communes": "data.ofgl.fr ofgl-base-communes-consolidee (OFGL, comptes de gestion DGFiP, budget principal "
                     "+ budgets annexes, flux internes neutralises)",
    "ofgl_gfp": "data.ofgl.fr ofgl-base-gfp-consolidee (OFGL)",
    "ofgl_ei": "data.ofgl.fr ofgl-base-ei (OFGL, ensembles intercommunaux : GFP + communes membres, flux croises elimines)",
    "ofgl_dep": "data.ofgl.fr ofgl-base-departements-consolidee (OFGL)",
    "ofgl_dep_fonction": "data.ofgl.fr ofgl-base-departements-fonctionnelle (OFGL, presentation fonctionnelle)",
    "ofgl_reg": "data.ofgl.fr ofgl-base-regions-consolidee (OFGL)",
    "geo": "geo.api.gouv.fr (INSEE, COG et populations legales ; rattachement communes > EPCI > departement > region)",
    "dot_communes": "data.ofgl.fr dotations-communes (DGCL, montants notifies)",
    "dot_gfp": "data.ofgl.fr dotations-gfp (DGCL, montants notifies)",
    "dot_dep": "data.ofgl.fr dotations-departements (DGCL, montants notifies)",
    "dot_reg": "data.ofgl.fr dotations-regions (DGCL, montants notifies)",
    "dgcl_invest": "data.gouv.fr DGCL « Projets finances par les dotations de soutien a l'investissement des "
                   "collectivites territoriales » (DETR, DSIL, DPV, DSID)",
    "rei": "data.economie.gouv.fr fiscalite-locale-des-particuliers (DGFiP, REI : taux votes par les deliberations "
           "de fiscalite locale)",
    "sirene": "INSEE, stock SIRENE des unites legales (data.gouv.fr), categorie juridique",
    "megalis_budgets": "data.gouv.fr « Budgets des organismes adherents de Megalis Bretagne » (SCDL budget)",
    "megalis_delib": "data.gouv.fr « Deliberations des organismes adherents de Megalis Bretagne » (SCDL deliberations)",
    "nm_ca": "data.nantesmetropole.fr comptes administratifs de Nantes Metropole",
    "nm_bp": "data.nantesmetropole.fr budgets primitifs de la Ville de Nantes",
    "pdl_sub": "data.paysdelaloire.fr subventions de la Region Pays de la Loire (vote et mandatements, avec SIRET)",
    "pdl_delib": "data.paysdelaloire.fr deliberations de la Region Pays de la Loire",
    "d44_delib": "data.loire-atlantique.fr deliberations du Conseil departemental de Loire-Atlantique",
    "nm_delib": "data.nantesmetropole.fr deliberations des instances de Nantes Metropole",
}

# Grands agregats OFGL retenus (cle publiee, libelle OFGL exact). Memes definitions pour les quatre niveaux.
AGREGATS = [
    ("depenses_fonctionnement", "Dépenses de fonctionnement"),
    ("frais_personnel", "Frais de personnel"),
    ("achats_charges_externes", "Achats et charges externes"),
    ("depenses_intervention", "Dépenses d'intervention"),
    ("subventions_versees_fonctionnement", "Subventions aux personnes de droit privé"),
    ("charges_financieres", "Charges financières"),
    ("depenses_investissement", "Dépenses d'investissement hors remb"),
    ("depenses_equipement", "Dépenses d'équipement"),
    ("subventions_versees_equipement", "Subventions d'équipement versées"),
    ("remboursement_dette", "Remboursements d'emprunts hors GAD"),
    ("depenses_totales", "Dépenses totales"),
    ("recettes_fonctionnement", "Recettes de fonctionnement"),
    ("impots_taxes", "Impôts et taxes"),
    ("impots_locaux", "Impôts locaux"),
    ("fiscalite_reversee", "Fiscalité reversée"),
    ("concours_etat", "Concours de l'Etat"),
    ("dgf", "Dotation globale de fonctionnement"),
    ("subventions_recues", "Subventions reçues et participations"),
    ("ventes_biens_services", "Ventes de biens et services"),
    ("epargne_brute", "Epargne brute"),
    ("encours_dette", "Encours de dette"),
]
CLES = [k for k, _ in AGREGATS]
LIB = dict(AGREGATS)
PAR_LIB = {v: k for k, v in AGREGATS}

METHODE_BLOC = (
    "Bloc communal consolide (commune + intercommunalite) : on ne fait jamais la somme des comptes de la commune et "
    "de son EPCI. On publie l'« ensemble intercommunal » de l'OFGL (ofgl-base-ei) : comptes du groupement a fiscalite "
    "propre + comptes de toutes ses communes membres, dont l'OFGL retire les flux croises (montant = montant_gfp + "
    "montant_communes - montant_flux) : attributions de compensation et dotation de solidarite communautaire "
    "(« fiscalite reversee », qui devient quasi nulle), subventions et participations entre la commune et l'EPCI, "
    "remboursements de frais et mises a disposition. Les euros par habitant du bloc sont rapportes a la population "
    "de tout le territoire intercommunal. Les comptes du departement et de la region sont publies a part et ne sont "
    "jamais additionnes au bloc communal : leurs subventions aux communes seraient comptees deux fois."
)

FONCTIONS_M57 = {"0": "Services généraux", "1": "Sécurité", "2": "Enseignement, formation professionnelle et apprentissage",
                 "3": "Culture, vie sociale, jeunesse, sports et loisirs", "4": "Santé et action sociale",
                 "5": "Aménagement des territoires et habitat", "6": "Action économique", "7": "Environnement",
                 "8": "Transports", "9": "Fonds européens"}

# Masque de bits de index.json
BLOCS = ["geo", "budget_commune", "budget_epci", "bloc_communal", "budget_departement", "budget_region",
         "fonctions_commune", "fonctions_epci", "fonctions_departement", "fonctions_region", "dotations_commune",
         "dotations_epci", "dotations_departement", "investissement_etat_commune", "taux",
         "decisions_commune", "decisions_epci", "decisions_departement", "decisions_region"]

CIVILITE_RE = re.compile(r"\b(M\.|MM\.|Mme|Mlle|Mr|Monsieur|Madame|Mademoiselle|Messieurs)\s", re.I)


# --- Utilitaires ---------------------------------------------------------------------------------------------------


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} depasse 5 Mo ({n} octets) : decouper")
    tmp = path.with_suffix(".part")
    tmp.write_text(texte + "\n", encoding="utf-8")
    tmp.replace(path)
    return n


def propre(v) -> str:
    if v is None:
        return ""
    s = unicodedata.normalize("NFC", str(v)).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)  # NaN -> None
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def euros(v):
    return None if v is None else round(v)


def par_hab(montant, pop):
    """Euros par habitant = montant / population, 2 decimales ; None si l'un manque."""
    if montant is None or not pop:
        return None
    return round(montant / pop, 2)


def dep_de_insee(code: str) -> str:
    return code[:3] if code.startswith("97") else code[:2]


def siren_de(v) -> str:
    s = re.sub(r"\D", "", str(v or ""))
    return s[:9] if len(s) in (9, 14) else ""


def http_get(url: str, params: dict | None = None, essais: int = 12, timeout: int = 300) -> requests.Response:
    """GET avec reprises (coupures frequentes). 401/403 : arret, jamais de contournement d'un refus d'acces."""
    erreur = None
    for i in range(essais):
        try:
            r = requests.get(url, params=params, headers=fetch.HEADERS, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as exc:
            erreur = exc.__class__.__name__
        else:
            if r.status_code in (401, 403):
                raise SystemExit(f"{url} : acces refuse (HTTP {r.status_code}), source ignoree sans contournement")
            if r.status_code < 400:
                return r
            if r.status_code != 429 and r.status_code < 500:
                raise SystemExit(f"{url} -> HTTP {r.status_code} : {r.text[:300]}")
            erreur = f"HTTP {r.status_code}"
        time.sleep(min(30, 2 + 2 * i))
    raise RuntimeError(f"{url} injoignable apres {essais} essais ({erreur})")


def en_cache(nom: str, url: str, params: dict | None = None, rafraichir: bool = False) -> Path:
    p = CACHE / nom
    if p.exists() and not rafraichir:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    r = http_get(url, params)
    tmp = p.with_suffix(p.suffix + ".part")
    tmp.write_bytes(r.content)
    fetch.remplacer_si_valide(tmp, p, octets_attendus=fetch.octets_annonces(r))  # collecte/integrite.py
    return p


def lire_csv(p: Path) -> list[dict]:
    texte = p.read_bytes().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(texte), delimiter=";"))


def ddb():
    import duckdb
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    return con


def rows(con, sql: str, params=None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def annees_ofgl(con) -> list[str]:
    """Les NB_ANNEES derniers exercices presents dans les comptes des departements (OFGL)."""
    a = [r["a"] for r in rows(con, f"select distinct year(exer) a from '{COLL / 'local_departements.parquet'}' order by 1")]
    return [str(x) for x in a[-NB_ANNEES:]]


def in_odsql(valeurs) -> str:
    return "(" + ",".join('"' + v.replace('"', '\\"') + '"' for v in valeurs) + ")"


# --- 1. Geographie -------------------------------------------------------------------------------------------------


def geo_brut(rafraichir=False) -> dict:
    f = "nom,code,population,siren,codeEpci,codeDepartement,codeRegion"
    com = json.loads(en_cache("geo_communes.json", f"{GEO}/communes", {"fields": f, "type": "commune-actuelle"},
                              rafraichir).read_text(encoding="utf-8"))
    epci = json.loads(en_cache("geo_epcis.json", f"{GEO}/epcis", {"fields": "nom,code,population"},
                               rafraichir).read_text(encoding="utf-8"))
    deps = json.loads(en_cache("geo_departements.json", f"{GEO}/departements", None, rafraichir).read_text(encoding="utf-8"))
    regs = json.loads(en_cache("geo_regions.json", f"{GEO}/regions", None, rafraichir).read_text(encoding="utf-8"))
    return {"communes": com, "epcis": {e["code"]: e for e in epci}, "departements": {d["code"]: d for d in deps},
            "regions": {r["code"]: r for r in regs}}


def sirens_collectivites(con, g: dict) -> dict:
    """SIREN -> (type, code) pour les quatre niveaux (rattachement des attribuants de subventions)."""
    res = {}
    for c in g["communes"]:
        if c.get("siren"):
            res[c["siren"]] = ("commune", c["code"])
    for code in g["epcis"]:
        res[code] = ("epci", code)
    for r in rows(con, f"select distinct dep_code, siren from '{COLL / 'local_departements.parquet'}'"):
        if r["siren"]:
            res[str(r["siren"])[:9]] = ("departement", r["dep_code"])
    for r in rows(con, f"select distinct reg_code, siren from '{COLL / 'local_regions.parquet'}'"):
        if r["siren"]:
            res[str(r["siren"])[:9]] = ("region", r["reg_code"])
    return res


def epci_siege(con) -> dict:
    """SIREN EPCI -> departement du siege (OFGL, dernier exercice)."""
    out = {}
    for r in rows(con, f"select siren, dep_code, year(exer) a from '{COLL / 'local_intercos.parquet'}' "
                       f"where agregat='Dépenses totales' order by a"):
        out[str(r["siren"])] = r["dep_code"]
    return out


def ecrire_geo(g: dict, siege: dict, deps: list[str]) -> dict:
    par_dep = defaultdict(list)
    for c in g["communes"]:
        par_dep[c["codeDepartement"]].append(c)
    stats = {"communes": 0, "sans_epci": 0}
    for dep in deps:
        d = g["departements"].get(dep)
        if not d:
            continue
        reg = g["regions"][d["codeRegion"]]
        communes, epcis = {}, {}
        for c in sorted(par_dep.get(dep, []), key=lambda c: c["code"]):
            e = c.get("codeEpci")
            communes[c["code"]] = {"nom": c["nom"], "population": c.get("population"), "siren": c.get("siren"),
                                   "epci": e, "departement": dep, "region": reg["code"]}
            if e:
                ge = g["epcis"].get(e, {})
                epcis[e] = {"nom": ge.get("nom"), "population": ge.get("population"),
                            "departement_siege": siege.get(e) or dep}
            else:
                stats["sans_epci"] += 1
        stats["communes"] += len(communes)
        dump(OUT / "geo" / f"{dep}.json", {
            "millesime": "Code officiel geographique en vigueur (geo.api.gouv.fr), population municipale INSEE",
            "source": SRC["geo"], "departement": {"code": dep, "nom": d["nom"]},
            "region": {"code": reg["code"], "nom": reg["nom"]}, "communes": communes, "epci": epcis,
            "note": "budgets/epci/<departement_siege>.json contient les comptes de l'EPCI (siege selon l'OFGL)."})
    return stats


# --- 2. Budgets ---------------------------------------------------------------------------------------------------


def serie(lignes, cle_id, annees) -> dict:
    """lignes : dicts {id, nom, siren?, annee, agregat, montant, pop} -> {id: {nom, population, eur, eur_hab}}."""
    res = {}
    for r in lignes:
        k = PAR_LIB.get(r["agregat"])
        if k is None:
            continue
        a = str(r["annee"])
        if a not in annees:
            continue
        x = res.setdefault(r[cle_id], {"nom": r.get("nom"), "population": {}, "eur": {}, "eur_hab": {}})
        if r.get("siren"):
            x["siren"] = str(r["siren"])
        if r.get("pop"):
            x["population"][a] = int(r["pop"])
        x["eur"].setdefault(a, [None] * len(CLES))[CLES.index(k)] = euros(num(r["montant"]))
    for x in res.values():
        for a, vals in x["eur"].items():
            pop = x["population"].get(a)
            x["eur_hab"][a] = [par_hab(v, pop) for v in vals]
    return res


def entete_budget(annees, source, extra=None) -> dict:
    e = {"millesime": f"Comptes {annees[0]} a {annees[-1]} (exercices clos, comptes de gestion)", "source": source,
         "unite": "eur : euros ; eur_hab : euros par habitant = eur / population de l'exercice (population totale OFGL)",
         "annees": annees, "agregats": CLES, "libelles_ofgl": LIB,
         "format": "collectivites.<code>.eur.<annee> : valeurs alignees sur `agregats` ; null = absent a la source"}
    if extra:
        e.update(extra)
    return e


def ofgl_communes_dep(dep: str, annees: list[str], rafraichir=False) -> Path:
    where = f"dep_code='{dep}' and year(exer)>={annees[0]} and agregat in {in_odsql(LIB.values())}"
    return en_cache(f"ofgl_communes_{dep}.csv", f"{OFGL}/ofgl-base-communes-consolidee/exports/csv",
                    {"select": "exer,com_code,com_name,siren,agregat,montant,ptot", "where": where, "delimiter": ";"},
                    rafraichir)


def budgets_communes(dep: str, annees: list[str]) -> int:
    p = ofgl_communes_dep(dep, annees)
    lignes = [{"id": r["com_code"], "nom": r["com_name"], "siren": r["siren"], "annee": r["exer"][:4],
               "agregat": r["agregat"], "montant": r["montant"], "pop": num(r["ptot"])} for r in lire_csv(p)]
    s = serie(lignes, "id", annees)
    dump(OUT / "budgets" / "communes" / f"{dep}.json", {**entete_budget(annees, SRC["ofgl_communes"]),
                                                         "departement": dep, "collectivites": s})
    return len(s)


def budgets_epci_tous(con, annees: list[str]) -> dict:
    """EPCI et ensembles intercommunaux, regroupes par departement du siege."""
    a0 = annees[0]
    gfp = rows(con, f"select siren id, epci_name nom, siren, year(exer) annee, agregat, montant, ptot pop, dep_code "
                    f"from '{COLL / 'local_intercos.parquet'}' where year(exer)>={a0}")
    ei = rows(con, f"select siren id, epci_name nom, year(exer) annee, agregat, montant, ptot pop, dep_code "
                   f"from '{COLL / 'local_ensembles_intercommunaux.parquet'}' where year(exer)>={a0}")
    dep_de = {}
    for r in gfp + ei:
        dep_de[r["id"]] = r["dep_code"]
    s_gfp, s_ei = serie(gfp, "id", annees), serie(ei, "id", annees)
    par_dep = defaultdict(lambda: ({}, {}))
    for k, v in s_gfp.items():
        par_dep[dep_de[k]][0][k] = v
    for k, v in s_ei.items():
        par_dep[dep_de[k]][1][k] = v
    return par_dep


def ecrire_budgets_epci(par_dep, deps, annees) -> int:
    n = 0
    for dep in deps:
        gfp, ei = par_dep.get(dep, ({}, {}))
        dump(OUT / "budgets" / "epci" / f"{dep}.json", {
            **entete_budget(annees, SRC["ofgl_gfp"] + " ; " + SRC["ofgl_ei"]), "departement_siege": dep,
            "collectivites": gfp, "bloc_communal_consolide": ei, "methode_bloc_communal": METHODE_BLOC})
        n += len(gfp)
    return n


def budgets_departements_regions(con, annees) -> dict:
    a0 = annees[0]
    dep = rows(con, f"select dep_code id, dep_name nom, siren, year(exer) annee, agregat, montant, ptot pop "
                    f"from '{COLL / 'local_departements.parquet'}' where year(exer)>={a0}")
    reg = rows(con, f"select reg_code id, reg_name nom, siren, year(exer) annee, agregat, montant, ptot pop "
                    f"from '{COLL / 'local_regions.parquet'}' where year(exer)>={a0}")
    sd, sr = serie(dep, "id", annees), serie(reg, "id", annees)
    dump(OUT / "budgets" / "departements.json", {**entete_budget(annees, SRC["ofgl_dep"]), "collectivites": sd})
    dump(OUT / "budgets" / "regions.json", {**entete_budget(annees, SRC["ofgl_reg"]), "collectivites": sr,
                                            "note": "Collectivites a statut particulier (Corse, Martinique, Guyane) "
                                                    "et Mayotte selon le rattachement de l'OFGL."})
    return {"departements": len(sd), "regions": len(sr)}


def fonctions_departements(con, annees) -> int:
    """Depenses (fonctionnement, investissement hors remboursements) par fonction de niveau 1, tous budgets."""
    a0 = annees[0]
    lignes = rows(con, f"""select dep_code, dep_name, year(exer) annee, fonction, nom_fonction, agregat,
                           sum(montant) m, max(ptot) pop
                           from '{COLL / 'local_departements_fonction.parquet'}'
                           where year(exer)>={a0} and niveau_hierarchique=1 and agregat in
                           ('Dépenses de fonctionnement', 'Dépenses d''investissement hors remb')
                           group by all order by all""")
    res = {}
    for r in lignes:
        d = res.setdefault(r["dep_code"], {"nom": r["dep_name"], "population": {}, "fonctions": {}})
        a = str(r["annee"])
        d["population"][a] = int(r["pop"])
        f = d["fonctions"].setdefault(r["fonction"], {"libelle": r["nom_fonction"], "eur": {}, "eur_hab": {}})
        i = 0 if r["agregat"] == "Dépenses de fonctionnement" else 1
        v = euros(r["m"])
        f["eur"].setdefault(a, [None, None])[i] = v
        f["eur_hab"].setdefault(a, [None, None])[i] = par_hab(v, int(r["pop"]))
    dump(OUT / "budgets" / "fonctions" / "departements.json", {
        "millesime": f"Comptes {annees[0]} a {annees[-1]}", "source": SRC["ofgl_dep_fonction"], "annees": annees,
        "colonnes": ["depenses_fonctionnement", "depenses_investissement_hors_remboursements"],
        "unite": "euros ; eur_hab = eur / population de l'exercice",
        "note": "Presentation fonctionnelle de l'OFGL, niveau 1, budget principal et budgets annexes additionnes "
                "(flux entre budgets non retires) ; APA, RSA et PCH sont dans la fonction 4.",
        "departements": res})
    return len(res)


def megalis_fonctions(con, rafraichir=False) -> Path:
    """Agrege une fois les budgets Megalis (1,9 Go) : comptes administratifs, depenses reelles, par fonction (M57)."""
    p = CACHE / "megalis_fonctions.parquet"
    if p.exists() and not rafraichir:
        return p
    src = COLL / "collectivites_megalis_budgets" / "budget-*.csv"
    CACHE.mkdir(parents=True, exist_ok=True)
    con.execute(f"""copy (
        select BGT_ANNEE annee, substr(BGT_SIRET,1,9) siren, min(BGT_NOM) nom_budget,
               lower(BGT_SECTION) section, substr(BGT_FONCTION,1,1) fonction,
               sum(try_cast(BGT_MTREAL as double)) montant
        from read_csv('{src}', all_varchar=true, header=true, union_by_name=true)
        where lower(BGT_NATDEC)='compte administratif' and BGT_OPBUDG='réel' and BGT_CODRD='dépense'
          and BGT_FONCTION is not null and BGT_FONCTION <> ''
          and coalesce(BGT_NATURE,'') not like '16%' and coalesce(BGT_NATURE,'') not in ('001','002')
        group by all) to '{p}' (format parquet)""")
    return p


def fonctions_pilote(con, annees, g: dict, sirens_coll: dict) -> dict:
    """Detail par fonction : Bretagne (Megalis, collectivites qui votent par fonction) et Nantes (CA, BP)."""
    stats = {"megalis_collectivites": 0, "nantes": 0}
    pop_com = {c["siren"]: c.get("population") for c in g["communes"] if c.get("siren")}
    pop_epci = {k: v.get("population") for k, v in g["epcis"].items()}
    vider(OUT / "budgets" / "fonctions", garder={"departements.json"})
    # Megalis : M57 generalisee au 1er janvier 2024 ; avant, M14 (codes de fonction differents) : on ne garde que >= 2024
    if (COLL / "collectivites_megalis_budgets").exists():
        p = megalis_fonctions(con)
        par = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0.0, 0.0])))
        for r in rows(con, f"select * from '{p}' where annee >= '2024'"):
            t = sirens_coll.get(r["siren"])
            if not t or not r["section"]:
                continue
            i = 0 if r["section"].startswith("fonct") else 1
            par[r["siren"]][r["annee"]][r["fonction"]][i] += r["montant"] or 0
        for siren, ans in par.items():
            if max(len(fs) for fs in ans.values()) < 3:  # pas une vraie presentation fonctionnelle
                continue
            typ, code = sirens_coll[siren]
            pop = pop_com.get(siren) if typ == "commune" else pop_epci.get(code) if typ == "epci" else None
            if typ == "departement":
                pop = None
            fonctions = {}
            for a, fs in ans.items():
                for f, (fo, inv) in fs.items():
                    x = fonctions.setdefault(f, {"libelle": FONCTIONS_M57.get(f, f), "eur": {}, "eur_hab": {}})
                    x["eur"][a] = [euros(fo), euros(inv)]
                    x["eur_hab"][a] = [par_hab(euros(fo), pop), par_hab(euros(inv), pop)]
            dump(OUT / "budgets" / "fonctions" / f"{siren}.json", {
                "millesime": "Comptes administratifs " + ", ".join(sorted(ans)), "source": SRC["megalis_budgets"],
                "collectivite": {"type": typ, "code": code, "siren": siren}, "population": pop,
                "population_source": "geo.api.gouv.fr (population municipale INSEE la plus recente)",
                "colonnes": ["depenses_fonctionnement", "depenses_investissement_hors_remboursements"],
                "unite": "euros reels (mandats), hors remboursement d'emprunts (chapitre 16)",
                "nomenclature": "M57, fonctions de niveau 1 (budgets votes par fonction seulement)",
                "fonctions": fonctions})
            stats["megalis_collectivites"] += 1
    # Nantes Metropole : comptes administratifs (lake) ; Ville de Nantes : budgets primitifs (credits votes)
    for siren, motif, src, nature, pop in [
            ("244400404", "dette/datagouv__compte-administratif-ca-20*-de-nantes-metropole*/*.csv", "nm_ca",
             "Compte administratif (depenses realisees)", pop_epci.get("244400404")),
            ("214401093", "etat/ods_nantesmetropole__244400404_budget-primitif-bp-20*-nantes.parquet", "nm_bp",
             "Budget primitif (credits votes, pas des depenses realisees)", pop_com.get("214401093"))]:
        fichiers = sorted(LAKE.glob(motif))
        if not fichiers:
            continue
        fonctions = {}
        for f in fichiers:
            q = f"read_csv('{f}', all_varchar=true, header=true)" if f.suffix == ".csv" else f"'{f}'"
            noms = [d[0] for d in con.execute(f"select * from {q} limit 0").description]
            cols = [colonne(noms, "exercice"), colonne(noms, "depensesrecettes", "depenserecette", "dr"),
                    colonne(noms, "imputationdordre", "ordreon", "ordre"),
                    colonne(noms, "investissementfonctionnement", "if"), colonne(noms, "codechapitre"),
                    colonne(noms, "codesousfonction", "codessfonction"), colonne(noms, "montant")]
            if None in cols:
                print(f"  {f.name} : colonnes inattendues {noms}", file=sys.stderr)
                continue
            c = [f'"{x}"' for x in cols]
            for r in rows(con, f"""select cast({c[0]} as varchar) a, cast({c[3]} as varchar) s,
                    substr(cast({c[5]} as varchar),1,1) f, sum(try_cast(replace(cast({c[6]} as varchar),',','.') as double)) m
                    from {q} where {c[1]}='D' and {c[2]}='N' and cast({c[4]} as varchar) not in ('16','020','022')
                    group by all"""):
                if not r["f"] or r["a"] is None or int(r["a"]) < int(annees[0]) - 1:
                    continue
                x = fonctions.setdefault(r["f"], {"libelle": FONCTIONS_M57.get(r["f"], r["f"]), "eur": {}, "eur_hab": {}})
                v = x["eur"].setdefault(r["a"], [0, 0])
                v[0 if r["s"] == "F" else 1] += euros(r["m"] or 0)
        for x in fonctions.values():
            for a, v in x["eur"].items():
                x["eur_hab"][a] = [par_hab(v[0], pop), par_hab(v[1], pop)]
        if fonctions:
            typ, code = sirens_coll.get(siren, ("?", siren))
            dump(OUT / "budgets" / "fonctions" / f"{siren}.json", {
                "millesime": nature + " " + ", ".join(sorted({a for x in fonctions.values() for a in x["eur"]})),
                "source": SRC[src], "collectivite": {"type": typ, "code": code, "siren": siren}, "population": pop,
                "population_source": "geo.api.gouv.fr (population municipale INSEE la plus recente)",
                "colonnes": ["depenses_fonctionnement", "depenses_investissement_hors_remboursements"],
                "unite": "euros, operations reelles, hors chapitre 16 (emprunts) et depenses imprevues",
                "nomenclature": "M57, fonctions de niveau 1", "fonctions": fonctions})
            stats["nantes"] += 1
    return stats


def vider(dossier: Path, garder=frozenset()) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    for f in dossier.glob("*.json"):
        if f.name not in garder:
            f.unlink()


# --- 3. Dotations ---------------------------------------------------------------------------------------------------

DOT_COMMUNES = {  # variable OFGL -> cle publiee (montants notifies, euros)
    "Montant Dotation DGF": "dgf_totale", "Montant Dotation forfaitaire": "dgf_forfaitaire",
    "Montant Dotation DSU": "dgf_dsu", "Montant Dotation DSR": "dgf_dsr", "Montant Dotation DNP": "dgf_dnp",
    "Montant Dotation Commune nouvelle": "dgf_commune_nouvelle", "Montant Dotation DACOM": "dgf_dacom",
    "Montant dotation biodiversité et aménités rurales": "dotation_biodiversite",
    "Montant de DCRTP de la commune": "dcrtp", "Montant du prélèvement DILICO": "dilico_prelevement",
    "Montant du reversement DILICO N-1": "dilico_reversement"}
DOT_GFP = {"Montant DGF": "dgf_totale", "Montant Dotation intercommunalité": "dgf_intercommunalite",
           "Montant Dotation de compensation": "dgf_compensation", "Montant de la DCTP des EPCI": "dctp",
           "Montant du prélèvement DILICO": "dilico_prelevement", "Montant de reversement DILICO N-1": "dilico_reversement"}
DOT_DEP = {"Montant DGF notifiée totale": "dgf_totale", "Montant Dotation forfaitaire": "dgf_forfaitaire",
           "Montant Dotation de compensation": "dgf_compensation",
           "Montant Dotation de péréquation urbaine": "dgf_perequation_urbaine",
           "Montant Dotation de fonctionnement minimale": "dgf_fonctionnement_minimale",
           "Montant de la DCRTP": "dcrtp", "Montant du prélèvement DILICO": "dilico_prelevement",
           "Montant du reversement DILICO N-1": "dilico_reversement"}
DOT_REG = {"Montant Fonds de péréquation des régions - Solde": "fonds_perequation_regions_solde",
           "Montant Fonds de solidarité régional - Solde": "fonds_solidarite_regional_solde",
           "Montant prélèvement DILICO": "dilico_prelevement", "Montant reversement DILICO N-1": "dilico_reversement"}
NOTE_DILICO = ("DILICO : dispositif de lissage conjoncturel des recettes fiscales (loi de finances 2025) ; le prelevement "
               "est un montant retenu, publie en valeur positive, a deduire.")


# Constat M5 de docs/QUALITE.md : la dotation des communes nouvelles n'est jamais comprise dans le total notifie.
NOTE_DGF_COMMUNES = ("dgf_totale = forfaitaire + DSU + DSR + DNP, plus la DACOM outre-mer (dgf_dacom). La dotation des "
                     "communes nouvelles (dgf_commune_nouvelle) est publiee a part : elle n'est pas comprise dans "
                     "dgf_totale.")
NOTE_DGF_GFP = ("dgf_totale = dotation d'intercommunalite + dotation de compensation. Quand le total notifie differe "
                "de la somme de ces deux composantes de plus de 2 euros, la difference est publiee dans "
                "dgf_ecart_composantes (ecart calcule : la source ne le detaille pas).")


def completer_dgf_gfp(tg: dict) -> int:
    """Ajoute dgf_ecart_composantes = dgf_totale - intercommunalite - compensation quand il depasse 2 euros."""
    n = 0
    for x in tg.values():
        for v in x["eur"].values():
            v.pop("dgf_ecart_composantes", None)
            if v.get("dgf_totale") is None:
                continue
            ecart = v["dgf_totale"] - (v.get("dgf_intercommunalite") or 0) - (v.get("dgf_compensation") or 0)
            if abs(ecart) > 2:
                v["dgf_ecart_composantes"] = ecart
                n += 1
    return n


def annee_dot(v: str) -> str:
    return str(v)[:4]


def table_dot(lignes, cle, mapping) -> tuple[dict, list[str]]:
    res, annees = {}, set()
    for r in lignes:
        k = mapping.get(r["variable"])
        v = num(r["valeur"])
        if k is None or v is None:
            continue
        a = annee_dot(r["exercice"])
        annees.add(a)
        x = res.setdefault(str(r[cle]), {"nom": r.get("nom"), "eur": {}})
        x["eur"].setdefault(a, {})[k] = euros(v)
    return res, sorted(annees)


def dotations_communes_dep(dep: str, a0: str, rafraichir=False) -> Path:
    where = (f"code_departement='{dep}' and year(exercice)>={a0} and unite='euros' "
             f"and variable in {in_odsql(DOT_COMMUNES)}")
    return en_cache(f"dotations_communes_{dep}.csv", f"{OFGL}/dotations-communes/exports/csv",
                    {"select": "exercice,code_insee,commune,variable,valeur", "where": where, "delimiter": ";"},
                    rafraichir)


def investissement_etat() -> dict:
    """Subventions d'investissement de l'Etat (DETR, DSIL, DPV, DSID) par beneficiaire, toutes annees."""
    d = COLL / ("datagouv__projets-finances-par-les-dotations-de-soutien-a-linvestissement-des-collectivites-"
                "territoriales")
    res = defaultdict(lambda: defaultdict(lambda: {"total": 0, "par_dispositif": defaultdict(int), "projets": []}))
    for f in sorted(d.glob("*.csv")):
        for r in csv.DictReader(io.StringIO(f.read_bytes().decode("utf-8-sig")), delimiter=";"):
            s = siren_de(r.get("beneficiaire_siren"))
            v = num(r.get("subvention"))
            if not s or v is None:
                continue
            a = propre(r.get("exercice"))[:4]
            x = res[s][a]
            x["total"] += round(v)
            x["par_dispositif"][propre(r.get("dispositif"))] += round(v)
            x["projets"].append([propre(r.get("dispositif")), objet_publiable(r.get("intitule"), None, 160), round(v),
                                 euros(num(r.get("cout_ht")))])
    for s in res.values():
        for x in s.values():
            x["projets"].sort(key=lambda p: -p[2])
            x["nb_projets"] = len(x["projets"])
            x["projets"] = x["projets"][:15]
            x["par_dispositif"] = dict(x["par_dispositif"])
    return res


def ecrire_dotations_communes(dep: str, a0: str, invest: dict, siren_insee: dict) -> int:
    p = dotations_communes_dep(dep, a0)
    lignes = [{"exercice": r["exercice"], "code_insee": r["code_insee"], "nom": r["commune"],
               "variable": r["variable"], "valeur": r["valeur"]} for r in lire_csv(p)]
    t, annees = table_dot(lignes, "code_insee", DOT_COMMUNES)
    inv = {}
    for insee, siren in siren_insee.items():
        if dep_de_insee(insee) == dep and siren in invest:
            inv[insee] = invest[siren]
    dump(OUT / "dotations" / "communes" / f"{dep}.json", {
        "millesime": f"Dotations notifiees {annees[0] if annees else '?'} a {annees[-1] if annees else '?'} ; "
                     f"projets d'investissement 2018 a 2025",
        "source": SRC["dot_communes"] + " ; " + SRC["dgcl_invest"], "unite": "euros", "annees": annees,
        "cles": sorted(set(DOT_COMMUNES.values())),
        "note": NOTE_DGF_COMMUNES + " " + NOTE_DILICO,
        "communes": t, "investissement_etat": inv,
        "format_investissement": "investissement_etat.<insee>.<annee> = {total, par_dispositif, nb_projets, "
                                 "projets: [[dispositif, intitule, subvention, cout_ht], 15 plus gros]}"})
    return len(t)


def ecrire_dotations_nationales(con, a0: str, invest: dict) -> dict:
    where = f"year(exercice)>={a0} and unite='euros' and variable in "
    pg = en_cache("dotations_gfp.csv", f"{OFGL}/dotations-gfp/exports/csv",
                  {"select": "exercice,siren,nom_epci,variable,valeur", "where": where + in_odsql(DOT_GFP),
                   "delimiter": ";"})
    pr = en_cache("dotations_regions.csv", f"{OFGL}/dotations-regions/exports/csv",
                  {"select": "exercice,code_region,nom_region,variable,valeur", "where": where + in_odsql(DOT_REG),
                   "delimiter": ";"})
    tg, ag = table_dot([{**r, "nom": r["nom_epci"]} for r in lire_csv(pg)], "siren", DOT_GFP)
    for s, x in tg.items():
        if s in invest:
            x["investissement_etat"] = invest[s]
    completer_dgf_gfp(tg)
    tr, ar = table_dot([{**r, "nom": r["nom_region"]} for r in lire_csv(pr)], "code_region", DOT_REG)
    dl = rows(con, f"select cast(exercice as varchar) exercice, code_departement, nom_departement nom, variable, valeur "
                   f"from '{COLL / 'local_dotations_departements.parquet'}' where year(exercice)>={a0} and unite='euros'")
    td, ad = table_dot(dl, "code_departement", DOT_DEP)
    dump(OUT / "dotations" / "epci.json", {"millesime": f"Dotations notifiees {ag[0]} a {ag[-1]}",
                                           "source": SRC["dot_gfp"] + " ; " + SRC["dgcl_invest"], "unite": "euros",
                                           "annees": ag, "note": NOTE_DGF_GFP + " " + NOTE_DILICO, "epci": tg})
    dump(OUT / "dotations" / "departements.json", {"millesime": f"Dotations notifiees {ad[0]} a {ad[-1]}",
                                                   "source": SRC["dot_dep"], "unite": "euros", "annees": ad,
                                                   "note": NOTE_DILICO, "departements": td})
    dump(OUT / "dotations" / "regions.json", {
        "millesime": f"{ar[0]} a {ar[-1]}", "source": SRC["dot_reg"], "unite": "euros", "annees": ar,
        "note": "Depuis 2018, la DGF des regions est remplacee par une fraction de TVA (recette fiscale, voir "
                "budgets/regions.json, agregat impots_taxes) : seuls les fonds de perequation regionaux restent "
                "publies ici. " + NOTE_DILICO, "regions": tr})
    return {"epci": len(tg), "departements": len(td), "regions": len(tr)}


# --- 4. Taux --------------------------------------------------------------------------------------------------------

TAUX_COLS = [("tfb_commune", "e12vote"), ("tfb_syndicats", "e22"), ("tfb_intercommunalite", "e32vote"),
             ("tfb_taxe_speciale_equipement", "e52"), ("tfb_gemapi", "e52ggemapi"), ("tfb_global", "taux_global_tfb"),
             ("tfnb_commune", "b12vote"), ("tfnb_intercommunalite", "b32vote"), ("tfnb_global", "taux_global_tfnb"),
             ("thrs_commune", "h12vote"), ("thrs_intercommunalite", "h32vote"), ("thrs_global", "taux_global_th"),
             ("teom_taux_plein", "taux_plein_teom")]


def ecrire_taux(con, deps) -> int:
    p = COLL / "local_fiscalite_particuliers.parquet"
    ex = [r["e"] for r in rows(con, f"select distinct exercice e from '{p}' order by 1")][-3:]
    cols = ", ".join(c for _, c in TAUX_COLS)
    n = 0
    lignes = rows(con, f"select exercice, dep, insee_com, libcom, sirepci, {cols} from '{p}' where exercice in "
                       f"({','.join(repr(e) for e in ex)})")
    par = defaultdict(dict)
    for r in lignes:
        dep = r["dep"] if len(r["dep"] or "") >= 2 else dep_de_insee(r["insee_com"])
        par[dep].setdefault(r["insee_com"], {})[r["exercice"]] = [
            None if r[c] is None else round(r[c], 3) for _, c in TAUX_COLS]
    for dep in deps:
        d = par.get(dep) or par.get(dep.lstrip("0"))
        if not d:
            continue
        dump(OUT / "taux" / f"{dep}.json", {
            "millesime": "Exercices " + ", ".join(ex), "source": SRC["rei"], "unite": "%", "exercices": ex,
            "colonnes": [k for k, _ in TAUX_COLS],
            "note": "Taux votes (REI). La taxe d'habitation ne subsiste que sur les residences secondaires (THRS). "
                    "Le departement ne vote plus de taux de foncier bati depuis 2021 (part transferee aux communes).",
            "communes": d})
        n += len(d)
    return n


# --- 5. Decisions (subventions votees) ----------------------------------------------------------------------------


def sirene_cj(sirens: set[str]) -> dict:
    """SIREN -> (categorie juridique, denomination si personne morale). Stock SIRENE local (telecharge si absent)."""
    p = CACHE / "sirene_unite_legale.parquet"
    if not p.exists():
        print("  telechargement du stock SIRENE (~720 Mo, reprenable)", file=sys.stderr)
        tmp = p.with_suffix(".part")
        for _ in range(30):
            debut = tmp.stat().st_size if tmp.exists() else 0
            try:
                with requests.get(SIRENE_URL, headers={**fetch.HEADERS, "Range": f"bytes={debut}-"}, stream=True,
                                  timeout=300) as r:
                    if r.status_code in (401, 403):
                        raise SystemExit("stock SIRENE : acces refuse")
                    with tmp.open("ab") as fh:
                        for bloc in r.iter_content(1 << 20):
                            fh.write(bloc)
                break
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError):
                time.sleep(5)
        fetch._integrite().verifier_fichier(tmp, nom=p.name)  # parquet complet ; sinon .part garde pour reprise
        tmp.replace(p)
    con = ddb()
    con.execute("create temp table q(siren varchar)")
    con.executemany("insert into q values (?)", [(s,) for s in sirens])
    res = {}
    for r in rows(con, f"""select u.siren, cast(u.categorieJuridiqueUniteLegale as varchar) cj,
                          coalesce(u.denominationUniteLegale, u.denominationUsuelle1UniteLegale) denom
                          from '{p}' u join q using (siren)"""):
        cj = (r["cj"] or "").zfill(4) if r["cj"] else ""
        res[r["siren"]] = (cj, propre(r["denom"]) if sirene.personne_morale(cj) else None)
    return res


def norm_col(c: str) -> str:
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", c.lower()).encode("ascii", "ignore").decode())


def colonne(cols, *motifs):
    n = {norm_col(c): c for c in cols}
    for m in motifs:
        for k, c in n.items():
            if k == m:
                return c
    for m in motifs:
        for k, c in n.items():
            if m in k:
                return c
    return None


def sources_scdl() -> list[tuple[str, Path]]:
    """Fichiers de l'entrepot au format SCDL subventions (colonne idBeneficiaire), hors Region PdL (traitee a part)."""
    m = json.loads((LAKE / "manifest.json").read_text(encoding="utf-8"))
    res = []
    for k, v in m.items():
        for f in v.get("fichiers") or []:
            cols = [norm_col(c) for c in (f.get("colonnes") or [])]
            p = ROOT / f["chemin"]
            if any(c == "idbeneficiaire" for c in cols) and p.suffix in (".parquet", ".csv") and p.exists():
                res.append((k, p))
    return res


def lire_scdl(con, p: Path, cle: str = "") -> list[dict]:
    q = f"'{p}'" if p.suffix == ".parquet" else f"read_csv('{p}', all_varchar=true, header=true, ignore_errors=true)"
    try:
        cur = con.execute(f"select columns(*)::varchar from {q}")
    except Exception as exc:  # fichier mal forme : ignore et signale
        print(f"  ignore {p.name} : {exc.__class__.__name__}", file=sys.stderr)
        return []
    cols = [d[0] for d in cur.description]
    c_att, c_natt = colonne(cols, "idattribuant"), colonne(cols, "nomattribuant")
    c_ben, c_nben = colonne(cols, "idbeneficiaire"), colonne(cols, "nombeneficiaire")
    c_mt = colonne(cols, "montant")
    c_date = colonne(cols, "dateconvention", "datedelaconventiondesubvention", "datededecision", "datedecision",
                     "convention")
    c_an = colonne(cols, "anneedecision", "annee", "exercice")
    c_ref = colonne(cols, "referencedecision", "referencedeliberation", "decision")
    c_obj = colonne(cols, "objet")
    if not (c_att and c_ben and c_mt):
        return []
    annee_fichier = re.search(r"(20[12]\d)", p.name) or re.search(r"(20[12]\d)", cle)
    res = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        date = propre(d.get(c_date))[:10] if c_date else ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", date)
            date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""
        an_col = propre(d.get(c_an))[:4] if c_an else ""
        annee = date[:4] if date else (an_col if re.match(r"^20\d\d$", an_col) else
                                       annee_fichier.group(1) if annee_fichier else "")
        res.append({"attribuant": siren_de(d.get(c_att)), "nom_attribuant": propre(d.get(c_natt)),
                    "beneficiaire": siren_de(d.get(c_ben)), "montant": num(d.get(c_mt)), "date": date or None,
                    "annee": annee, "reference": propre(d.get(c_ref))[:60] if c_ref else "",
                    "objet": propre(d.get(c_obj)) if c_obj else ""})
    return res


# Échantillon de prénoms très fréquents : sert aux tests seulement, jamais de repli du filtre (voir prenoms()).
PRENOMS_MINIMAUX = {"JEAN", "MARIE", "PIERRE", "MICHEL", "PHILIPPE", "ALAIN", "ANDRE", "BERNARD", "JACQUES",
                    "NICOLAS", "CHRISTOPHE", "FRANCOIS", "DANIEL", "PATRICK", "CATHERINE", "NATHALIE", "ISABELLE"}
MOTS_OUTILS = {"DE", "DU", "DES", "LA", "LE", "LES", "ET", "A", "AU", "AUX", "EN", "POUR", "SUR", "D", "L", "ST",
               "STE", "SAINT", "SAINTE"}
# Prénoms de la liste Insee qui sont d'abord un nom de lieu ou de rivière, un mois, un sigle, une marque ou un mot
# courant des objets et dénominations publiés (« Ile-de-France », « fête du 1er mai », « don de matériel », « Espérance
# sportive », « Fleury-Mérogis », « Les Lilas », « ADA » accueil des demandeurs d'asile, « ALEC » agence locale de
# l'énergie et du climat, « ALMA » réseau Allô maltraitance) : ils ne déclenchent pas le filtre. Choisis parmi les mots
# qui retiraient le plus de textes et de dénominations d'organismes sur les données publiées le 19/11/2026 ; aucun ne
# figure dans le complément SIRENE (la liste de production précédente), sauf FRANCE, exclu depuis l'origine : les
# retirer ne publie aucun texte que la production retirait.
NON_PRENOMS = {"FRANCE", "MAI", "DON", "CONCEPTION", "FRANC", "ESPERANCE", "LOUP", "NEO", "CANNELLE", "DIVINE", "ALIZE",
               "ALEC", "ALMA", "ADA", "ARIA", "ANES", "ASSA", "ROSAIRE", "BELLA", "LORETTE", "FLEURY", "ROHAN",
               "LILAS", "ARON", "SUZON", "GILLETTE"}
# Listes versionnées (pipeline/prenoms_ref.py) : Insee, Fichier des prénoms (prénoms donnés au moins 1 000 fois
# depuis 1900), et complément du stock SIRENE (prénoms d'au moins 300 entrepreneurs individuels, la liste de production
# d'origine). Aucun cache, aucun stock hors dépôt : une machine neuve filtre exactement comme la production.
FICHIER_PRENOMS = Path(__file__).resolve().parent / "donnees_ref" / "prenoms.txt"
FICHIER_PRENOMS_SIRENE = FICHIER_PRENOMS.with_name("prenoms_sirene.txt")
_PRENOMS: set | None = None
APOSTROPHES_RE = re.compile("[\u2019\u2018\u02bc\u00b4`]")


def lire_liste_prenoms(chemin: Path = FICHIER_PRENOMS) -> set:
    """Prénoms du fichier versionné (lignes « # » = en-tête). Fichier absent ou vide : erreur, jamais de repli."""
    if not chemin.exists():
        raise RuntimeError(f"{chemin} absent : la liste de prénoms du filtre est versionnée dans le dépôt "
                           "(python pipeline/prenoms_ref.py pour la régénérer) ; aucun repli")
    liste = {l.strip() for l in chemin.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")}
    if not liste:
        raise RuntimeError(f"{chemin} vide : aucun repli")
    return liste


def prenoms() -> set:
    """Prénoms fréquents en majuscules sans accent : union des deux listes versionnées de pipeline/donnees_ref/."""
    global _PRENOMS
    if _PRENOMS is not None:
        return _PRENOMS
    tous = lire_liste_prenoms(FICHIER_PRENOMS) | lire_liste_prenoms(FICHIER_PRENOMS_SIRENE)
    _PRENOMS = {x for x in tous if len(x) >= 3} - NON_PRENOMS - MOTS_OUTILS
    return _PRENOMS


# Equipement, etablissement ou voie : un nom qui suit l'un de ces mots (« ecole Victor Hugo », « rue Jean Jaures »,
# « groupe scolaire Jules Ferry ») est le nom d'un lieu, pas celui d'une personne. Regarde jusqu'a trois mots avant.
EQUIPEMENTS_ET_VOIES = frozenset("""
ECOLE ECOLES GROUPE SCOLAIRE COLLEGE LYCEE MATERNELLE ELEMENTAIRE PRIMAIRE SALLE SALLES GYMNASE STADE PISCINE
MEDIATHEQUE BIBLIOTHEQUE LUDOTHEQUE CENTRE MAISON ESPACE FOYER CRECHE HALLE COMPLEXE THEATRE CINEMA MUSEE
AUDITORIUM HOPITAL EHPAD RESIDENCE CITE QUARTIER JARDIN JARDINS RUE PLACE AVENUE AV BOULEVARD BD ALLEE ALLEES QUAI
PARC SQUARE PONT CHEMIN ROUTE IMPASSE PASSAGE PROMENADE ESPLANADE PARVIS COURS RONDPOINT GIRATOIRE ZAC ZONE
INSTITUT INTERNAT DOJO BOULODROME VELODROME HIPPODROME PATINOIRE TERRAIN TERRAINS PALAIS CHAPELLE EGLISE
""".split())


def contient_nom_de_personne(o: str, liste: set | None = None) -> bool:
    """Civilite, ou prenom frequent suivi d'un mot (hors « Saint-Jean », « Sainte-Marie » et hors nom de lieu qui suit
    un mot d'equipement ou de voie, EQUIPEMENTS_ET_VOIES) : prudence, objet retire."""
    if CIVILITE_RE.search(o):
        return True
    liste = prenoms() if liste is None else liste
    # Apostrophe typographique ramenée à « ' » avant la translittération, qui la supprimerait (« d’une » ne doit pas
    # devenir le mot « DUNE », prénom de la liste Insee).
    t = re.findall(r"[A-Z]+", unicodedata.normalize("NFKD", APOSTROPHES_RE.sub("'", o).upper())
                   .encode("ascii", "ignore").decode())
    for i, m in enumerate(t):
        if m not in liste or i + 1 >= len(t):
            continue
        if i > 0 and t[i - 1] in ("SAINT", "SAINTE", "ST", "STE"):
            continue
        if any(m in EQUIPEMENTS_ET_VOIES for m in t[max(0, i - 3):i]):
            continue
        if len(t[i + 1]) >= 2 and t[i + 1] not in MOTS_OUTILS:
            return True
        # Particule de nom (« Marie de Kergariou », « Jean du Bois ») : prudence, le mot suivant est un nom.
        if t[i + 1] in ("DE", "DU", "DES", "D") and i + 2 < len(t) and len(t[i + 2]) >= 2 \
                and t[i + 2] not in MOTS_OUTILS:
            return True
    return False


def objet_publiable(o: str, liste: set | None = None, longueur: int = 140) -> str | None:
    """Texte libre publie seulement sans nom de personne possible ; sinon null (le montant reste publie)."""
    o = propre(o)
    if not o or o.lower() in ("non disponible", "none", "null") or contient_nom_de_personne(o, liste):
        return None
    return o[:longueur]


def lignes_pdl(con) -> tuple[list[dict], dict]:
    """Region Pays de la Loire : une ligne par operation (vote a jour, somme des mandatements).

    Regles deterministes (documentees dans docs/contrat_interface.md) :
    - beneficiaire d'une operation a plusieurs tiers : le SIRET qui a recu le plus de mandatements sur l'operation ;
      a egalite, le plus petit SIRET (tri explicite, jamais un choix arbitraire du moteur) ;
    - une operation est exclue des noms (personnes physiques) des qu'un de ses tiers est une personne physique ;
    - mandatements publies sans numero d'operation : regroupes par (SIRET, annee de la date d'execution), sans vote
      (vote non publie), annee = annee d'execution ;
    - annee : prefixe du numero d'operation ; a defaut, annee de la date d'execution ; a defaut, « inconnue ».
    """
    p = LAKE / "beneficiaires" / "decisions_pdl_subventions.parquet"
    if not p.exists():
        return [], {}
    ops = rows(con, f"""
        with src as (select *, coalesce(id_operation, 'sans-operation:' || coalesce(tgen_siret_numero, '?') || ':'
                                        || coalesce(cast(year(date_execution) as varchar), '?')) cle
                     from '{p}'),
        tiers as (select cle, tgen_siret_numero siret, sum(coalesce(mandat_valeur, 0)) m from src group by 1, 2),
        choix as (select cle, siret from (select cle, siret, row_number() over (
                      partition by cle order by m desc, siret asc nulls last) rang from tiers) where rang = 1)
        select s.cle, any_value(s.id_operation) id_operation, max(s.vote_a_jour) vote, sum(s.mandat_valeur) mandat,
               min(s.date_execution) d1, c.siret,
               bool_or(coalesce(s.nature_tiers, '') like '%PERSONNES PHYSIQUES%') pp,
               min(s.code_dossier) dossier, min(s.libelle_operation) objet, min(s.numero_programme) prog,
               min(s.libelle_programme) lib_prog
        from src s join choix c using (cle) group by s.cle, c.siret order by s.cle""")
    res = []
    for r in ops:
        op = r["id_operation"]
        an = ("20" + op[:2] if op and re.match(r"^\d{2}", op) else
              str(r["d1"])[:4] if r["d1"] else None)
        res.append({"attribuant": "234400034", "nom_attribuant": "Région des Pays de la Loire",
                    "beneficiaire": siren_de(r["siret"]), "montant": r["vote"] if r["vote"] is not None else 0.0,
                    "vote_absent": r["vote"] is None, "mandate": r["mandat"] or 0.0,
                    "date": None, "annee": an, "reference": r["dossier"] or op,
                    "objet": r["objet"] or "", "programme": r["prog"], "lib_programme": r["lib_prog"],
                    "pp_source": bool(r["pp"]), "sans_operation": op is None})
    # programme -> deliberations (l'objet des deliberations commence par le code programme, ex. « S101 - ... »)
    progs = {}
    pd = LAKE / "_restreint" / "decisions" / "decisions_pdl_deliberations.csv"
    if pd.exists():
        for d in rows(con, f"select delib_date, delib_objet, delib_url from read_csv('{pd}', all_varchar=true, "
                           f"header=true, delim=';')"):
            m = re.match(r"^\s*([A-Z]\d{3})\b", d["delib_objet"] or "")
            if m:
                progs.setdefault(m.group(1), []).append({"date": d["delib_date"], "url": d["delib_url"]})
    for r in res:
        if r["programme"]:
            progs.setdefault(r["programme"], [])
    libs = {r["programme"]: r["lib_programme"] for r in res if r["programme"]}
    programmes = {k: {"libelle": libs.get(k), "deliberations": sorted(v, key=lambda x: x["date"] or "", reverse=True)[:30],
                      "nb_deliberations": len(v)} for k, v in progs.items()}
    return res, programmes


def objet_avec_adresse(o: str) -> bool:
    """Objet qui contient une adresse (numéro suivi d'un type de voie) : il peut désigner le bien d'un particulier
    (« restauration du patrimoine immobilier privé - dossier 1 rue … »). Filtre partagé avec pipeline/deliberations.py
    (ADRESSE_NUMERO_RE, motif « adresse_possible ») ; import tardif car deliberations importe local."""
    import deliberations
    return bool(deliberations.ADRESSE_NUMERO_RE.search(deliberations.sans_accents(o.lower())))


def deliberations_subventions(con) -> dict:
    """SIREN collectivite -> {annee: [[date, id, objet, url]]} pour la matiere 7.5 (subventions), 3 dernieres annees."""
    res = defaultdict(lambda: defaultdict(list))
    comptes = defaultdict(lambda: defaultdict(int))
    sources = [(LAKE / "_restreint" / "decisions" / "decisions_nantes_metropole_deliberations.parquet", "parquet"),
               (LAKE / "_restreint" / "decisions" / "decisions_d44_deliberations.parquet", "parquet")]
    sources += [(p, "csv") for p in sorted((LAKE / "_restreint" / "decisions" / "decisions_megalis_deliberations")
                                          .glob("deliberation-*.csv"))]
    pd = LAKE / "_restreint" / "decisions" / "decisions_pdl_deliberations.csv"
    if pd.exists():
        sources.append((pd, "csv"))
    for p, fmt in sources:
        if not p.exists():
            continue
        q = f"'{p}'" if fmt == "parquet" else f"read_csv('{p}', all_varchar=true, header=true, ignore_errors=true)"
        cur = con.execute(f"select columns(*)::varchar from {q}")
        cols = [d[0] for d in cur.description]
        cs, cd, ci = colonne(cols, "collsiret"), colonne(cols, "delibdate"), colonne(cols, "delibid")
        cm, co, cu = colonne(cols, "delibmatierecode"), colonne(cols, "delibobjet"), colonne(cols, "deliburl")
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            s = siren_de(d.get(cs))
            date = propre(d.get(cd))[:10]
            if not s or not date:
                continue
            a = date[:4]
            comptes[s][a] += 1
            if not propre(d.get(cm)).startswith("7.5"):
                continue
            o = objet_publiable(d.get(co))
            if o and objet_avec_adresse(o):
                o = None  # même règle que pipeline/deliberations.py (motif « adresse_possible »)
            if o:
                res[s][a].append([date, propre(d.get(ci))[:40], o, propre(d.get(cu)) or None])
    return {"subventions": res, "comptes": comptes}


def decisions(con, sirens_coll: dict, g: dict) -> dict:
    vider_arbre(OUT / "decisions")
    brutes, vus = [], set()
    for cle, p in sources_scdl():
        for r in lire_scdl(con, p, cle):
            k = (r["attribuant"], r["beneficiaire"], r["montant"], r["date"], r["reference"], r["objet"])
            if k in vus:
                continue
            vus.add(k)
            r["source"] = cle
            brutes.append(r)
    pdl, programmes = lignes_pdl(con)
    brutes += pdl
    lignes = [r for r in brutes if r["attribuant"] in sirens_coll and r["montant"] is not None]
    ignores = defaultdict(float)
    for r in brutes:
        if r["attribuant"] not in sirens_coll:
            ignores[r["nom_attribuant"] or r["attribuant"] or "?"] += 1
    cj = sirene_cj({r["beneficiaire"] for r in lignes if r["beneficiaire"]})
    delib = deliberations_subventions(con)
    par_att = defaultdict(list)
    for r in lignes:
        par_att[r["attribuant"]].append(r)
    couverts = {"commune": set(), "epci": set(), "departement": set(), "region": set()}
    resume = {}
    for att, ls in par_att.items():
        typ, code = sirens_coll[att]
        couverts[typ].add(code)
        est_pdl = att == "234400034"
        par_an = defaultdict(list)
        exclus = {"montant_eur": 0.0, "lignes": 0, "dont_personnes_physiques_eur": 0.0, "dont_sans_siren_eur": 0.0,
                  "dont_categorie_inconnue_eur": 0.0}
        top = defaultdict(lambda: {"montant": 0.0, "lignes": 0})
        total = 0.0
        total_mandate = 0.0
        for r in ls:
            total += r["montant"]
            total_mandate += r.get("mandate") or 0.0
            s = r["beneficiaire"]
            c, denom = cj.get(s, ("", None)) if s else ("", None)
            if r.get("pp_source") or not sirene.personne_morale(c):
                exclus["montant_eur"] += r["montant"]
                exclus["lignes"] += 1
                if r.get("pp_source") or c.startswith("1") or c in sirene.CJ_PERSONNES_PHYSIQUES:
                    exclus["dont_personnes_physiques_eur"] += r["montant"]
                elif not s:
                    exclus["dont_sans_siren_eur"] += r["montant"]
                else:
                    exclus["dont_categorie_inconnue_eur"] += r["montant"]
                continue
            nom = denom or "?"
            ligne = [r["date"], r["reference"] or None, s, c, nom, round(r["montant"], 2), objet_publiable(r["objet"])]
            if est_pdl:
                ligne += [round(r.get("mandate") or 0.0, 2), r.get("programme")]
            par_an[r["annee"] or "inconnue"].append(ligne)
            t = top[s]
            t.update(denomination=nom, categorie_juridique=c)
            t["montant"] += r["montant"]
            t["lignes"] += 1
        colonnes = ["date_decision", "reference_decision", "siren", "categorie_juridique", "denomination",
                    "montant_eur", "objet"] + (["mandate_eur", "programme"] if est_pdl else [])
        base = OUT / "decisions" / att
        entete = {"collectivite": {"type": typ, "code": code, "siren": att, "nom": ls[0]["nom_attribuant"]},
                  "source": SRC["pdl_sub"] if est_pdl else "data.gouv.fr et portails ODS, jeux SCDL subventions : "
                  + ", ".join(sorted({r.get("source", "") for r in ls if r.get("source")}))[:400]}
        annees = {}
        for a, lgn in sorted(par_an.items()):
            lgn.sort(key=lambda x: (-(x[5] or 0), x[2]))
            morceaux = [lgn[i:i + LIGNES_PAR_FICHIER] for i in range(0, len(lgn), LIGNES_PAR_FICHIER)]
            noms = [f"{a}.json"] if len(morceaux) == 1 else [f"{a}-{i + 1}.json" for i in range(len(morceaux))]
            for nom, m in zip(noms, morceaux):
                dump(base / nom, {**entete, "millesime": f"Subventions {a}" + (
                    " (annee de l'operation, prefixe du numero d'operation ; a defaut, annee d'execution du mandatement)" if est_pdl else " (date de la decision "
                    "ou de la convention ; a defaut, colonne annee, puis annee du jeu ; sinon « inconnue »)"), "annee": a, "colonnes": colonnes, "lignes": m,
                    "unite": "euros" + (" ; montant_eur = vote a jour, mandate_eur = somme des mandatements"
                                        if est_pdl else "")})
            annees[a] = {"lignes": len(lgn), "montant_eur": round(sum(x[5] for x in lgn), 2), "fichiers": noms}
            if est_pdl:
                annees[a]["mandate_eur"] = round(sum(x[7] for x in lgn), 2)
        for x in ("montant_eur", "dont_personnes_physiques_eur", "dont_sans_siren_eur", "dont_categorie_inconnue_eur"):
            exclus[x] = round(exclus[x], 2)
        tops = sorted(top.items(), key=lambda kv: -kv[1]["montant"])[:50]
        somme_pm = sum(v["montant"] for v in top.values())
        if abs(somme_pm + exclus["montant_eur"] - total) > 1:
            raise SystemExit(f"Conservation rompue pour {att}")
        idx = {**entete, "millesime": "Toutes annees publiees : " + ", ".join(sorted(annees)),
               "total_source_eur": round(total, 2), "lignes_source": len(ls), "annees": annees,
               "top_beneficiaires": [{"siren": s, "denomination": v["denomination"],
                                      "categorie_juridique": v["categorie_juridique"],
                                      "montant_eur": round(v["montant"], 2), "lignes": v["lignes"]} for s, v in tops],
               "personnes_morales": len(top),
               "exclus_personnes_physiques_ou_non_identifies": exclus,
               "regle": "Seules les personnes morales (categorie juridique SIRENE 2xxx a 9xxx) sont nommees.",
               "deliberations_subventions": {a: v for a, v in sorted(delib["subventions"].get(att, {}).items())[-3:]},
               "deliberations_par_annee": dict(sorted(delib["comptes"].get(att, {}).items()))}
        if est_pdl:
            idx["total_mandate_eur"] = round(total_mandate, 2)
            idx["operations_sans_vote_publie"] = sum(1 for r in ls if r.get("vote_absent"))
            idx["note_vote"] = ("Vote a jour = montant vote, ajuste des avenants ; mandate = somme des paiements. Une "
                                "operation sans vote publie compte 0 en vote, ses mandatements sont gardes. Les "
                                "mandatements publies sans numero d'operation sont regroupes par SIRET et annee "
                                "d'execution. Operation a plusieurs tiers : beneficiaire = SIRET le plus mandate "
                                "(a egalite, le plus petit SIRET) ; exclue des noms si un tiers est une personne "
                                "physique.")
            idx["mandatements_sans_operation"] = sum(1 for r in ls if r.get("sans_operation"))
            idx["programmes"] = programmes
            idx["source_deliberations"] = SRC["pdl_delib"]
        dump(base / "index.json", idx)
        resume[att] = {"type": typ, "code": code, "nom": ls[0]["nom_attribuant"], "lignes": len(ls),
                       "annees": sorted(annees), "total_eur": round(total, 2)}
    # Collectivites avec deliberations publiees mais sans subventions SCDL : index seul (deliberations)
    for att, ans in delib["comptes"].items():
        if att in par_att or att not in sirens_coll:
            continue
        typ, code = sirens_coll[att]
        dump(OUT / "decisions" / att / "index.json", {
            "collectivite": {"type": typ, "code": code, "siren": att}, "source": SRC["megalis_delib"] + " ; "
            + SRC["d44_delib"] + " ; " + SRC["nm_delib"] + " ; " + SRC["pdl_delib"],
            "millesime": "Deliberations " + ", ".join(sorted(ans)), "annees": {},
            "deliberations_subventions": {a: v for a, v in sorted(delib["subventions"].get(att, {}).items())[-3:]},
            "deliberations_par_annee": dict(sorted(ans.items()))})
        resume.setdefault(att, {"type": typ, "code": code, "lignes": 0, "annees": [], "total_eur": 0.0,
                                "deliberations_seulement": True})
    # Denominateur = communes des 101 departements couverts (hors collectivites d'outre-mer 975 a 989, sans budget publie ici).
    totaux = {"commune": sum(1 for c in g["communes"] if c.get("codeDepartement") in g["departements"]), "epci": len(g["epcis"]), "departement": len(g["departements"]),
              "region": len(g["regions"])}
    couv = {t: {"couvertes_subventions": len(couverts[t]), "total": totaux[t],
                "part_pct": round(100 * len(couverts[t]) / totaux[t], 2) if totaux[t] else 0} for t in totaux}
    for t in totaux:
        couv[t]["couvertes_deliberations"] = sum(1 for s in delib["comptes"] if sirens_coll.get(s, ("",))[0] == t)
    dump(OUT / "decisions" / "index.json", {
        "millesime": "Jeux publies au " + date_sources(),
        "source": "SCDL subventions (data.gouv.fr, portails ODS) ; " + SRC["pdl_sub"] + " ; " + SRC["sirene"],
        "couverture": couv, "collectivites": resume,
        "attribuants_hors_collectivites": {"nombre": len(ignores), "lignes": int(sum(ignores.values())),
                                           "note": "organismes publiant au format SCDL qui ne sont ni commune, ni "
                                                   "EPCI, ni departement, ni region (GIP, ecoles, syndicats...)"},
        "regle": "Beneficiaires nommes : personnes morales seulement (SIRENE). Personnes physiques, entrepreneurs "
                 "individuels et lignes sans SIREN de personne morale : montants agreges, jamais nommes.",
        "limites": limites_decisions(couv)})
    return {"attribuants": len(par_att), **{t: couv[t]["couvertes_subventions"] for t in couv}}


def _milliers(n: int) -> str:
    return f"{n:,}".replace(",", "\u00a0")


def limites_decisions(couv: dict) -> str:
    """Limite de couverture écrite avec les chiffres, sans appréciation (charte docs/NEUTRALITE.md, règle 2)."""
    noms = {"commune": "communes", "epci": "intercommunalités", "departement": "départements", "region": "régions"}
    parts = [f"{_milliers(couv[t]['couvertes_subventions'])} {noms[t]} sur {_milliers(couv[t]['total'])}"
             for t in noms if t in couv]
    return ("La publication des subventions au format SCDL n'est obligatoire qu'au-dessus de 23 000 euros par "
            "bénéficiaire. Listes publiées et collectées : " + ", ".join(parts) + ". Une collectivité absente de "
            "ces listes n'a pas forcément versé moins.")


def vider_arbre(d: Path) -> None:
    if d.exists():
        for f in sorted(d.rglob("*"), reverse=True):
            if f.is_file():
                f.unlink()
            else:
                f.rmdir()
    d.mkdir(parents=True, exist_ok=True)


# --- 6. Index -------------------------------------------------------------------------------------------------------


def charger(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def ecrire_index(g: dict, annees) -> dict:
    deps_b = charger(OUT / "budgets" / "departements.json") or {"collectivites": {}}
    regs_b = charger(OUT / "budgets" / "regions.json") or {"collectivites": {}}
    fdep = (charger(OUT / "budgets" / "fonctions" / "departements.json") or {"departements": {}})["departements"]
    dot_dep = (charger(OUT / "dotations" / "departements.json") or {"departements": {}})["departements"]
    dot_epci = (charger(OUT / "dotations" / "epci.json") or {"epci": {}})["epci"]
    fonctions = {p.stem for p in (OUT / "budgets" / "fonctions").glob("*.json")}
    decisions_ = {p.name for p in (OUT / "decisions").iterdir() if p.is_dir()} if (OUT / "decisions").exists() else set()
    sir_dep = {v["siren"]: k for k, v in deps_b["collectivites"].items() if v.get("siren")}
    sir_reg = {v["siren"]: k for k, v in regs_b["collectivites"].items() if v.get("siren")}
    dep_siren = {v: k for k, v in sir_dep.items()}
    reg_siren = {v: k for k, v in sir_reg.items()}
    epci_cache, out, stats = {}, {}, defaultdict(int)
    for dep in sorted({c["codeDepartement"] for c in g["communes"]}):
        geo = charger(OUT / "geo" / f"{dep}.json")
        if not geo:
            continue
        bc = (charger(OUT / "budgets" / "communes" / f"{dep}.json") or {"collectivites": {}})["collectivites"]
        dc = charger(OUT / "dotations" / "communes" / f"{dep}.json") or {"communes": {}, "investissement_etat": {}}
        tx = (charger(OUT / "taux" / f"{dep}.json") or {"communes": {}})["communes"]
        for insee, c in geo["communes"].items():
            e = c.get("epci")
            if e and e not in epci_cache and c.get("epci"):
                ds = geo["epci"][e]["departement_siege"]
                f = charger(OUT / "budgets" / "epci" / f"{ds}.json") or {"collectivites": {}, "bloc_communal_consolide": {}}
                for k in f["collectivites"]:
                    epci_cache.setdefault(k, [False, False])[0] = True
                for k in f["bloc_communal_consolide"]:
                    epci_cache.setdefault(k, [False, False])[1] = True
                epci_cache.setdefault(e, [False, False])
            ok = {"geo": True, "budget_commune": insee in bc, "budget_epci": bool(e and epci_cache[e][0]),
                  "bloc_communal": bool(e and epci_cache[e][1]), "budget_departement": dep in deps_b["collectivites"],
                  "budget_region": c["region"] in regs_b["collectivites"],
                  "fonctions_commune": (c.get("siren") or "") in fonctions, "fonctions_epci": (e or "") in fonctions,
                  "fonctions_departement": dep in fdep or dep_siren.get(dep, "-") in fonctions,
                  "fonctions_region": reg_siren.get(c["region"], "-") in fonctions,
                  "dotations_commune": insee in dc["communes"], "dotations_epci": (e or "") in dot_epci,
                  "dotations_departement": dep in dot_dep,
                  "investissement_etat_commune": insee in dc.get("investissement_etat", {}), "taux": insee in tx,
                  "decisions_commune": (c.get("siren") or "") in decisions_, "decisions_epci": (e or "") in decisions_,
                  "decisions_departement": dep_siren.get(dep, "-") in decisions_,
                  "decisions_region": reg_siren.get(c["region"], "-") in decisions_}
            out[insee] = sum(1 << i for i, b in enumerate(BLOCS) if ok[b])
            for b in BLOCS:
                stats[b] += ok[b]
    dump(OUT / "index.json", {
        "millesime": f"Sources collectees au {date_sources()} ; comptes {annees[0]} a {annees[-1]}",
        "source": "pipeline/local.py (voir chaque fichier)", "blocs": BLOCS,
        "format": "communes.<insee> = masque de bits : le bloc blocs[i] est disponible si (valeur >> i) & 1",
        "fichiers": {"geo": "geo/<dep>.json", "budget_commune": "budgets/communes/<dep>.json",
                     "budget_epci": "budgets/epci/<departement_siege>.json (collectivites)",
                     "bloc_communal": "budgets/epci/<departement_siege>.json (bloc_communal_consolide)",
                     "budget_departement": "budgets/departements.json", "budget_region": "budgets/regions.json",
                     "fonctions_departement": "budgets/fonctions/departements.json ou budgets/fonctions/<siren>.json",
                     "fonctions_commune": "budgets/fonctions/<siren commune>.json",
                     "fonctions_epci": "budgets/fonctions/<siren epci>.json",
                     "fonctions_region": "budgets/fonctions/<siren region>.json",
                     "dotations_commune": "dotations/communes/<dep>.json", "dotations_epci": "dotations/epci.json",
                     "dotations_departement": "dotations/departements.json",
                     "investissement_etat_commune": "dotations/communes/<dep>.json (investissement_etat)",
                     "taux": "taux/<dep>.json", "decisions_*": "decisions/<siren>/index.json et <annee>.json"},
        "sirens": {"departements": dep_siren, "regions": reg_siren},
        "communes": out, "comptes": dict(stats)})
    return dict(stats)


# --- Orchestration --------------------------------------------------------------------------------------------------


def prefetch(deps, annees, echeance: float, paralleles: int = 6) -> None:
    """Telecharge en parallele les extraits OFGL par departement (l'export filtre prend 30 a 120 s par appel).
    Fils demons : a l'echeance on n'attend plus (un telechargement interrompu n'ecrit qu'un fichier .part)."""
    import queue
    import threading

    a_faire = queue.Queue()
    for d in deps:
        if not (CACHE / f"ofgl_communes_{d}.csv").exists() or not (CACHE / f"dotations_communes_{d}.csv").exists():
            a_faire.put(d)

    def ouvrier():
        while time.monotonic() < echeance:
            try:
                dep = a_faire.get_nowait()
            except queue.Empty:
                return
            try:
                ofgl_communes_dep(dep, annees)
                dotations_communes_dep(dep, annees[0])
            except (RuntimeError, SystemExit) as exc:
                print(f"  {dep} : {exc}", file=sys.stderr)

    fils = [threading.Thread(target=ouvrier, daemon=True) for _ in range(paralleles)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(max(0.0, echeance - time.monotonic()))


def taille(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("etape", choices=["tout", "decisions", "index", "fonctions"])
    ap.add_argument("--deps", default=",".join(DEPS_DEFAUT), help="departements (mode departement)")
    ap.add_argument("--tous", action="store_true", help="tous les departements (reprenable)")
    ap.add_argument("--budget", type=float, default=480, help="duree max d'un passage, en secondes")
    a = ap.parse_args()
    if a.etape == "fonctions":  # depenses par fonction de toutes les communes, EPCI et regions (balances DGFiP)
        import local_fonctions
        local_fonctions.main([])
        return
    debut = time.monotonic()
    con = ddb()
    annees = annees_ofgl(con)
    g = geo_brut()
    sirens_coll = sirens_collectivites(con, g)
    tous = sorted(g["departements"])
    deps = tous if a.tous else [d.strip().zfill(2) for d in a.deps.split(",") if d.strip()]
    stats = {"annees": annees}
    if a.etape == "tout":
        siege = epci_siege(con)
        # Geographie, EPCI, departements, regions, taux : nationaux (entrepot). Communes : par departement (API),
        # les departements deja produits par un passage precedent sont conserves (mode cumulatif).
        stats["geo"] = ecrire_geo(g, siege, tous)
        par_dep_epci = budgets_epci_tous(con, annees)
        stats.update(budgets_departements_regions(con, annees))
        stats["fonctions_departements"] = fonctions_departements(con, annees)
        stats["fonctions_pilote"] = fonctions_pilote(con, annees, g, sirens_coll)
        invest = investissement_etat()
        stats["dotations_nationales"] = ecrire_dotations_nationales(con, annees[0], invest)
        siren_insee = {c["code"]: c["siren"] for c in g["communes"] if c.get("siren")}
        prefetch(deps, annees, debut + a.budget * 0.8)
        faits, restants = [], []
        for dep in deps:  # traitement local et rapide : tout departement dont les extraits sont en cache
            if not (CACHE / f"ofgl_communes_{dep}.csv").exists() or not (CACHE / f"dotations_communes_{dep}.csv").exists():
                restants.append(dep)
                continue
            try:
                budgets_communes(dep, annees)
                ecrire_dotations_communes(dep, annees[0], invest, siren_insee)
                faits.append(dep)
            except RuntimeError as exc:  # reseau : on reessaiera au prochain passage
                print(f"  {dep} reporte : {exc}", file=sys.stderr)
                restants.append(dep)
        stats["epci"] = ecrire_budgets_epci(par_dep_epci, sorted(par_dep_epci), annees)
        stats["taux_communes"] = ecrire_taux(con, tous)
        stats["departements_faits_ce_passage"] = faits
        stats["departements_restants"] = restants
        stats["decisions"] = decisions(con, sirens_coll, g)
    elif a.etape == "decisions":
        stats["decisions"] = decisions(con, sirens_coll, g)
    stats["index"] = ecrire_index(g, annees)
    stats["taille_octets"] = taille(OUT)
    stats["duree_s"] = round(time.monotonic() - debut)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    if stats.get("departements_restants"):
        print(f"{len(stats['departements_restants'])} departements restants : relancer la meme commande", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
