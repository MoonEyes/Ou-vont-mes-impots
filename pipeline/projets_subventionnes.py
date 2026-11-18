"""Projets subventionnés par l'État, par commune : Fonds vert (montants engagés) et renvoi vers les projets des
dotations d'investissement (DETR, DSIL, DPV, DSID, subventions attribuées), badges Action cœur de ville et Petites
villes de demain.

Ce module ne republie pas ce qu'un autre axe publie déjà ; il relie :
  - DETR, DSIL, DPV, DSID par projet (DGCL, 2018-2025) : déjà publiés par pipeline/territoires.py dans
    site/data/territoires/<dep>.json (`investissement_etat`, bénéficiaires et `par_commune`) ; ici, seulement le lien
    par département (`liens.dgcl`) et le libellé de chaque dispositif ;
  - Fonds vert : pipeline/subventions.py en publie les totaux et les principaux bénéficiaires, l'axe
    eau_environnement des agrégats (région, instructeur, démarche) ; aucun ne donne la liste par commune. Ici, chaque
    projet localisé dans une commune (liste publiée, montant engagé), mêmes fichiers bruts, avec un contrôle des
    totaux par année contre site/data/subventions/attribuants/subv_fonds_vert.json ;
  - Action cœur de ville et Petites villes de demain (ANCT) : listes de communes, publiées en badge, sans montant.

Entrées (data/lake, collectées par collecte/collecte.py ; identifiants déclarés dans collecte/catalogue.json) :
  _restreint/subventions/subv_fonds_vert/*.csv          Fonds vert 2023 à 2025 (programmes 380 et 113)
  projets_subventionnes/projets_subv_acv/*.csv          Action cœur de ville, villes du programme
  projets_subventionnes/projets_subv_pvd/*.csv          Petites villes de demain, communes (COG 2026)
  _cache/local/sirene_unite_legale.parquet, prenoms.json (stock SIRENE et prénoms, pipeline/local.py)
  lecture seule : site/data/local/geo/<dep>.json, site/data/territoires/<dep>.json,
                  site/data/subventions/attribuants/subv_fonds_vert.json
Sorties (site/data/projets_subventionnes/, chaque fichier < 1 Mo, avec `millesime` et `source`) :
  index.json        dispositifs et statut publié, totaux par année, départements, contrôles, sources, limites
  <dep>.json        par commune : projets du Fonds vert, badges ; liens vers territoires/<dep>.json

Commandes :
  python pipeline/projets_subventionnes.py collecter     # réseau : collecte/collecte.py
  python pipeline/projets_subventionnes.py produire      # sans réseau ; --sortie DOSSIER pour une copie de contrôle
  python pipeline/projets_subventionnes.py               # les deux

Règles :
  - statut tel que publié : « subvention attribuée » (DGCL), « montant engagé » (Fonds vert) ; jamais « réalisé »
    ni « livré » : la source ne dit pas si le projet est terminé ;
  - bénéficiaire nommé seulement si personne morale (sirene.personne_morale, stock SIRENE) ; dénomination d'un
    organisme non public passée au filtre de noms de personnes de local.py ; sinon projet agrégé, sans nom ni
    intitulé ; intitulé passé par local.objet_publiable (null s'il peut contenir un nom de personne) ;
  - montant vide ou illisible : null avec mention, jamais 0, hors des sommes ;
  - sommes (par année, même dispositif, même liste publiée) : « calculé par le site », méthode écrite à côté ;
    Fonds vert et dotations ne sont jamais additionnés ;
  - commune sans projet : « aucun projet publié pour ces dispositifs » ;
  - dates par pipeline/reproductible.py ; tris explicites : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
GEO = SITE / "local" / "geo"
TERRITOIRES = SITE / "territoires"
SUBV_FV = SITE / "subventions" / "attribuants" / "subv_fonds_vert.json"
SORTIE_DEFAUT = SITE / "projets_subventionnes"
MAX_OCTETS = 1_000_000
DATAGOUV = "https://www.data.gouv.fr/datasets/"

ID_FV = "subv_fonds_vert"
ID_ACV = "projets_subv_acv"
ID_PVD = "projets_subv_pvd"
ID_DGCL = "datagouv__projets-finances-par-les-dotations-de-soutien-a-linvestissement-des-collectivites-territoriales"

STATUT_DGCL = "subvention attribuée"
STATUT_FV = "montant engagé"
STATUT_CALCULE = "calculé par le site"
SANS_PROJET = "aucun projet publié pour ces dispositifs"
METHODE_SOMME = ("somme des montants publiés ligne par ligne, pour une même année et une même liste (Fonds vert) ; "
                 "lignes au montant non communiqué hors de la somme ; jamais additionnée aux dotations de l'État")

SOURCES = {
    "dgcl": {
        "id_catalogue": ID_DGCL,
        "titre": "DGCL, « Projets financés par les dotations de soutien à l'investissement des collectivités "
                 "territoriales » (DETR, DSIL, DPV, DSID), un CSV par exercice",
        "page": DATAGOUV + "6176785207139a929a2776fe", "producteur": "Direction générale des collectivités locales",
        "licence": "Licence Ouverte 2.0", "millesime": "Exercices 2018 à 2025",
        "statut": STATUT_DGCL,
        "publie_par": "pipeline/territoires.py, site/data/territoires/<dep>.json (investissement_etat)",
        "verdict": "réutilisable tel quel : déjà lu et publié par l'axe territoires, relié ici sans copie",
    },
    "fonds_vert": {
        "id_catalogue": ID_FV,
        "titre": "Ministère de la Transition écologique, « Fonds vert : liste des projets subventionnés » (2023, 2024, "
                 "2025 ; programmes 380 et 113)",
        "page": DATAGOUV + "66a215a463a9da4fb801b8cf", "producteur": "Ministère de la Transition écologique",
        "licence": "Licence Ouverte 2.0", "millesime": "Montants engagés des listes 2023, 2024 et 2025",
        "statut": STATUT_FV,
        "publie_par": "ce module (projets par commune) ; totaux et principaux bénéficiaires : pipeline/subventions.py ; "
                      "agrégats par région et instructeur : pipeline/eau_environnement.py",
        "verdict": "réutilisable tel quel : mêmes fichiers que pipeline/subventions.py (lecteur réutilisé)",
    },
    "acv": {
        "id_catalogue": ID_ACV,
        "titre": "Agence nationale de la cohésion des territoires, « Listes des villes Action cœur de ville » (export "
                 "de la Caisse des dépôts)",
        "page": DATAGOUV + "5fa9901c66cff095591963e8", "producteur": "ANCT, Caisse des dépôts",
        "licence": "Licence Ouverte 2.0", "millesime": "Liste publiée le 2026-10-20",
        "statut": "commune du programme",
        "verdict": "réutilisable tel quel : CSV « ; », code Insee de chaque commune",
    },
    "pvd": {
        "id_catalogue": ID_PVD,
        "titre": "Agence nationale de la cohésion des territoires, « Programme Petites villes de demain », liste des "
                 "communes bénéficiaires (COG 2026)",
        "page": DATAGOUV + "5fc1259b703620ed60a49d97", "producteur": "ANCT",
        "licence": "Licence Ouverte 2.0", "millesime": "Liste publiée le 2026-08-19 (COG 2026)",
        "statut": "commune du programme",
        "verdict": "réutilisable tel quel : CSV « , », code Insee et date de signature",
    },
}

# Libellés des dispositifs tels que publiés dans la colonne « dispositif » de la DGCL (territoires), en clair.
DISPOSITIFS = [
    {"id": "DETR", "libelle": "Dotation d'équipement des territoires ruraux (DETR)", "source": "dgcl",
     "programme": "119", "statut": STATUT_DGCL},
    {"id": "DSIL", "libelle": "Dotation de soutien à l'investissement local (DSIL)", "source": "dgcl",
     "programme": "119", "statut": STATUT_DGCL},
    {"id": "DSIL Exceptionnelle", "libelle": "Dotation de soutien à l'investissement local, part exceptionnelle "
     "(DSIL exceptionnelle)", "source": "dgcl", "programme": "119", "statut": STATUT_DGCL},
    {"id": "DSIL RT", "libelle": "Dotation de soutien à l'investissement local, rénovation thermique (DSIL RT)",
     "source": "dgcl", "programme": "119", "statut": STATUT_DGCL},
    {"id": "DPV", "libelle": "Dotation politique de la ville (DPV)", "source": "dgcl", "programme": "119",
     "statut": STATUT_DGCL},
    {"id": "DSID", "libelle": "Dotation de soutien à l'investissement des départements (DSID)", "source": "dgcl",
     "programme": "119", "statut": STATUT_DGCL},
    {"id": "DSID RT", "libelle": "Dotation de soutien à l'investissement des départements, rénovation thermique "
     "(DSID RT)", "source": "dgcl", "programme": "119", "statut": STATUT_DGCL},
    {"id": "Fonds vert", "libelle": "Fonds d'accélération de la transition écologique dans les territoires (Fonds "
     "vert)", "source": "fonds_vert", "programme": "380 ; 113 pour les listes « p113 »", "statut": STATUT_FV},
]

BADGES = {
    "acv": {"libelle": "Action cœur de ville", "source": "acv",
            "definition": "programme national de revitalisation des centres des villes moyennes (ANCT) ; la liste "
                          "nomme les communes du programme, sans montant"},
    "pvd": {"libelle": "Petites villes de demain", "source": "pvd",
            "definition": "programme national d'appui aux communes de moins de 20 000 habitants exerçant des fonctions "
                          "de centralité (ANCT) ; la liste nomme les communes, sans montant"},
}

LIMITES = [
    "Les listes publiées donnent des subventions attribuées (dotations) ou des montants engagés (Fonds vert) : elles "
    "ne disent pas si le projet est réalisé, ni ce qui a été payé.",
    "Une commune sans ligne n'a aucun projet publié pour ces dispositifs : d'autres financements de l'État, de "
    "l'Europe ou des collectivités ne figurent pas dans ces listes.",
    "Fonds vert : la commune est celle publiée dans la liste ; un projet porté par une intercommunalité ou un "
    "syndicat est rattaché à cette seule commune.",
    "Dotations (DETR, DSIL, DPV, DSID) : projets rattachés au bénéficiaire (la commune ou son intercommunalité), "
    "publiés par l'axe territoires.",
    "Fonds vert, liste « p113 » 2024 : ni commune, ni SIREN publiés ; ses lignes sont comptées dans les totaux "
    "nationaux, sans rattachement à une commune.",
    "Action cœur de ville et Petites villes de demain : listes de communes ; aucun montant n'est publié avec ces "
    "listes.",
]

METHODE = [
    "Fonds vert : une ligne de la liste publiée = un projet ; année = année de la liste (nom du fichier) ; "
    "programme 113 pour les listes « p113 », 380 sinon.",
    "Commune : code publié (colonne code_commune), complété à cinq caractères ; un code absent du code officiel "
    "géographique en vigueur reste rattaché au département publié (`communes_hors_cog`).",
    "Bénéficiaire : SIREN lu dans la colonne SIREN ou SIRET, catégorie juridique lue dans le stock SIRENE ; "
    "dénomination du stock SIRENE.",
    "Sommes par année, par commune et par département : " + METHODE_SOMME + ".",
    "Contrôle : totaux par année comparés à ceux de l'axe subventions (mêmes fichiers) ; l'écart est publié.",
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "requetes": ["data.gouv.fr projets DETR DSIL DPV DSID", "Fonds vert liste des projets subventionnés",
                 "Action cœur de ville liste des villes", "Petites villes de demain liste des communes",
                 "github DETR DSIL projets subventionnés carte communes Fonds vert"],
    "trouvailles": [
        {"nom": "DGCL, projets financés par les dotations de soutien à l'investissement (data.gouv.fr)",
         "url": DATAGOUV + "6176785207139a929a2776fe", "licence": "Licence Ouverte 2.0",
         "derniere_modification": "2026-07-24", "verdict": "réutilisable tel quel",
         "usage": "déjà publié par pipeline/territoires.py : relié, pas recopié"},
        {"nom": "Fonds vert, liste des projets subventionnés (data.gouv.fr)", "url": DATAGOUV + "66a215a463a9da4fb801b8cf",
         "licence": "Licence Ouverte 2.0", "derniere_modification": "2026-08-11", "verdict": "réutilisable tel quel",
         "usage": "projets par commune ; lecteur de pipeline/subventions.py"},
        {"nom": "Action cœur de ville, listes des villes (data.gouv.fr)", "url": DATAGOUV + "5fa9901c66cff095591963e8",
         "licence": "Licence Ouverte 2.0", "derniere_modification": "2026-10-20", "verdict": "réutilisable tel quel",
         "usage": "badge par commune"},
        {"nom": "Petites villes de demain, communes bénéficiaires (data.gouv.fr)",
         "url": DATAGOUV + "5fc1259b703620ed60a49d97", "licence": "Licence Ouverte 2.0",
         "derniere_modification": "2026-08-19", "verdict": "réutilisable tel quel", "usage": "badge par commune"},
        {"nom": "pipeline/territoires.py, pipeline/subventions.py, pipeline/local.py (ce dépôt)",
         "url": "pipeline/territoires.py", "licence": "MIT", "derniere_modification": "dépôt courant",
         "verdict": "réutilisable tel quel",
         "usage": "projets des dotations par bénéficiaire, lecteur CSV du Fonds vert, stock SIRENE, filtre de noms"},
        {"nom": "anct-carto, carte des dotations d'investissement 2019", "url":
         "https://anct-carto.github.io/dotations_investissement_2019", "licence": "non indiquée",
         "derniere_modification": "non vérifiée (API GitHub non accessible depuis la session)",
         "verdict": "inspiration seulement", "usage": "carte d'une seule année, sans données réutilisables en flux"},
    ],
}


# --- Utilitaires ---------------------------------------------------------------------------------------------------


def _sv():
    import subventions
    return subventions


def _local():
    import local
    return local


def propre(v) -> str:
    return _local().propre(v)


def code5(v) -> str | None:
    """Code commune publié -> code Insee à cinq caractères ; None si absent ou illisible (« NULL », vide)."""
    s = propre(v).upper()
    if not s or s in ("NULL", "NONE", "NAN", "-"):
        return None
    if re.match(r"^\d{4}$", s):
        s = "0" + s
    return s if re.match(r"^(\d{5}|2[AB]\d{3})$", s) else None


def dep_de(insee: str) -> str:
    return insee[:3] if insee.startswith("97") else insee[:2]


def eur(x: float) -> float:
    return round(float(x), 2)


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    n = len(txt.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets : à découper")
    path.write_text(txt + "\n", encoding="utf-8")
    return n


def charger_geo() -> tuple[dict, dict]:
    """(départements code -> nom, communes insee -> (nom, dep)) du code officiel géographique de site/data/local."""
    deps, communes = {}, {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        code = (d.get("departement") or {}).get("code")
        if not code:
            continue
        deps[code] = d["departement"]["nom"]
        for insee, c in (d.get("communes") or {}).items():
            communes[insee] = (c.get("nom"), code)
    if len(deps) != 101:
        raise SystemExit(f"site/data/local/geo : {len(deps)} départements au lieu de 101 (lancer pipeline/local.py)")
    return deps, communes


def fichiers_source(sid: str, motif: str = "*.csv") -> list[Path]:
    """Fichiers d'une source d'après le manifeste de l'entrepôt ; sinon recherche dans le dossier du domaine."""
    if sid == ID_FV:
        return _sv().fichiers(sid)
    try:
        m = json.loads((LAKE / "manifest.json").read_text(encoding="utf-8")).get(sid) or {}
    except (OSError, ValueError):
        m = {}
    res = [ROOT / f["chemin"] for f in m.get("fichiers", []) if (ROOT / f["chemin"]).exists()]
    if not res:
        res = sorted((LAKE / "projets_subventionnes" / sid).glob(motif))
    return sorted(p for p in set(res) if p.suffix.lower() == ".csv")


def lire_csv(chemin: Path) -> list[dict]:
    """CSV (UTF-8 avec ou sans BOM, sinon Windows-1252), séparateur détecté, en-têtes nettoyés."""
    return _sv().lignes_csv(chemin)


# --- Badges : Action cœur de ville, Petites villes de demain -----------------------------------------------------------


def date_iso(v) -> str | None:
    s = propre(v)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def lire_badges(lignes: list[dict], cle: str) -> dict[str, dict]:
    """insee -> {id, programme?, date_signature} (première ligne par commune, dans l'ordre du code Insee)."""
    res = {}
    for r in lignes:
        insee = code5(r.get("insee_com"))
        if not insee:
            continue
        e = {"id": propre(r.get(f"id_{cle}")) or None, "date_signature": date_iso(r.get("date_signature"))}
        if cle == "acv":
            e["programme"] = propre(r.get("lib_acv")) or None
        if insee not in res or (e["id"] or "") < (res[insee]["id"] or ""):
            res[insee] = e
    return dict(sorted(res.items()))


# --- Fonds vert ------------------------------------------------------------------------------------------------------


def lire_fonds_vert(fichiers: list[Path]) -> list[dict]:
    """Une ligne publiée -> enregistrement : annee, programme, insee, dep publié, siren, intitulé brut, démarche,
    montant (None si non communiqué), numéro d'engagement juridique."""
    sv = _sv()
    res = []
    for f in fichiers:
        a = sv.annee(f.name)
        p113 = "p113" in f.name.lower()
        for r in sv.lignes_csv(f, ","):
            c_sir = sv.col(r, "siretbeneficiaire", "siren")
            c_dem = sv.col(r, "demarche", "nomdemarcheds", "source")
            c_ej = sv.col(r, "numeroej")
            res.append({
                "annee": a, "programme": "113" if p113 else "380",
                "insee": code5(r.get("code_commune")), "dep": sv.dep_code(r.get("code_departement")),
                "siren": sv.siren(r.get(c_sir)) if c_sir else "",
                "intitule": r.get("nom_du_projet"), "demarche": (propre(r.get(c_dem)) or None) if c_dem else None,
                "montant": sv.montant(r.get("montant_engage")),
                "ej": (re.sub(r"\D", "", propre(r.get(c_ej))) or None) if c_ej else None,
            })
    return res


def classer(sirens: set[str]) -> tuple[dict, dict]:
    """SIREN -> (catégorie juridique, dénomination publiable ou None) ; et la fonction de statut de subventions.py."""
    loc = _local()
    stock = loc.sirene_cj(sirens) if sirens else {}
    liste = loc.prenoms()
    res = {}
    for s, (cj, denom) in stock.items():
        nom = None
        if denom:
            # Organisme public (catégorie 7xxx) : dénomination officielle ; sinon filtre de noms de personnes.
            nom = denom if (cj or "").startswith("7") else loc.objet_publiable(denom, liste, 200)
        res[s] = (cj, nom)
    return res, stock


def statut_beneficiaire(s: str, stock: dict, publiables: dict) -> str:
    """'pm' nommable, 'pp' personne physique, 'ni' sans SIREN, 'in' absent du stock, 'np' nom de personne possible."""
    st, _ = _sv().statut(s, stock)
    if st == "pm" and not publiables.get(s, (None, None))[1]:
        return "np"
    return st


EXCLUS = {"pp": "dont_personnes_physiques", "ni": "dont_sans_siren", "in": "dont_siren_introuvable",
          "np": "dont_nom_de_personne_possible"}


def exclus_vide() -> dict:
    return {"projets": 0, "montant_eur": 0.0, **{k: 0 for k in EXCLUS.values()}}


def ajouter_exclus(e: dict, statut: str, montant: float | None) -> None:
    e["projets"] += 1
    e[EXCLUS[statut]] += 1
    if montant is not None:
        e["montant_eur"] = eur(e["montant_eur"] + montant)


def produire_fonds_vert(lignes: list[dict], communes: dict, deps: dict, publiables: dict, stock: dict,
                        prenoms: set) -> tuple[dict, dict]:
    """(par département : communes, communes hors COG, exclus, totaux ; national : totaux, non localisés)."""
    loc = _local()
    par_dep = {d: {"communes": defaultdict(list), "hors_cog": defaultdict(list), "exclus": defaultdict(exclus_vide),
                   "beneficiaires": {}, "demarches": set()} for d in deps}
    nat = defaultdict(lambda: {"lignes": 0, "montant_eur": 0.0, "lignes_montant_non_communique": 0,
                               "projets_publies": 0, "montant_publie_eur": 0.0, "exclus": exclus_vide(),
                               "non_localises": {"projets": 0, "montant_eur": 0.0}})
    intitules_retires = 0
    for r in lignes:
        a = str(r["annee"])
        n = nat[a]
        n["lignes"] += 1
        if r["montant"] is None:
            n["lignes_montant_non_communique"] += 1
        else:
            n["montant_eur"] = eur(n["montant_eur"] + r["montant"])
        insee = r["insee"]
        dep = communes[insee][1] if insee in communes else (r["dep"] if insee and r["dep"] in deps else None)
        if dep is None:
            n["non_localises"]["projets"] += 1
            if r["montant"] is not None:
                n["non_localises"]["montant_eur"] = eur(n["non_localises"]["montant_eur"] + r["montant"])
            continue
        st = statut_beneficiaire(r["siren"], stock, publiables)
        cible = par_dep[dep]
        if st != "pm":
            ajouter_exclus(cible["exclus"][a], st, r["montant"])
            ajouter_exclus(n["exclus"], st, r["montant"])
            continue
        titre = loc.objet_publiable(r["intitule"], prenoms, 300)
        if titre is None and propre(r["intitule"]):
            intitules_retires += 1
        cj, nom = publiables[r["siren"]]
        cible["beneficiaires"][r["siren"]] = {"nom": nom, "cj": cj}
        if r["demarche"]:
            cible["demarches"].add(r["demarche"])
        ligne = (r["annee"], r["programme"], r["demarche"], titre, None if r["montant"] is None else eur(r["montant"]),
                 r["siren"], r["ej"])
        (cible["communes"] if insee in communes else cible["hors_cog"])[insee].append(ligne)
        n["projets_publies"] += 1
        if r["montant"] is not None:
            n["montant_publie_eur"] = eur(n["montant_publie_eur"] + r["montant"])
    return par_dep, {"par_annee": dict(sorted(nat.items())), "intitules_retires": intitules_retires}


def tri_projets(lignes: list[tuple]) -> list[tuple]:
    return sorted(lignes, key=lambda x: (-x[0], -(x[4] if x[4] is not None else -1), x[6] or "", x[3] or "", x[5]))


def totaux_par_annee(lignes: list[tuple]) -> dict:
    t = defaultdict(lambda: {"projets": 0, "montant_eur": 0.0, "lignes_montant_non_communique": 0})
    for x in lignes:
        e = t[str(x[0])]
        e["projets"] += 1
        if x[4] is None:
            e["lignes_montant_non_communique"] += 1
        else:
            e["montant_eur"] = eur(e["montant_eur"] + x[4])
    return dict(sorted(t.items()))


# --- Contrôles -------------------------------------------------------------------------------------------------------


def controle_subventions(par_annee: dict) -> list[dict]:
    """Totaux par année contre ceux publiés par l'axe subventions (mêmes fichiers) : écart publié, jamais tranché."""
    try:
        sv = json.loads(SUBV_FV.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    res = []
    for e in sv.get("par_annee", []):
        a = str(e.get("annee"))
        if a not in par_annee:
            continue
        m, autre = par_annee[a]["montant_eur"], e.get("montant_eur")
        res.append({"annee": int(a), "source": "projets_subventionnes", "montant_eur": m,
                    "lignes": par_annee[a]["lignes"], "autre_source": "subventions/attribuants/subv_fonds_vert.json",
                    "autre_montant_eur": autre, "autres_lignes": e.get("conventions"),
                    "ecart_eur": None if autre is None else eur(m - autre),
                    "lecture": "mêmes fichiers lus par deux axes : un écart signale une différence de lecture"})
    return res


# --- Production ------------------------------------------------------------------------------------------------------


def entete(date: str) -> dict:
    return {
        "millesime": f"Fonds vert : listes 2023 à 2025 (montants engagés) ; Action cœur de ville et Petites villes de "
                     f"demain : listes 2026 ; sources collectées au {date}",
        "source": "Ministère de la Transition écologique (Fonds vert, data.gouv.fr 66a215a463a9da4fb801b8cf), ANCT "
                  "(Action cœur de ville, Petites villes de demain), DGCL via site/data/territoires (dotations), "
                  "stock SIRENE (catégorie juridique)",
        "unite": "€",
        "date_sources": date,
    }


def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    deps, communes = charger_geo()
    fv_fichiers = fichiers_source(ID_FV)
    acv_f, pvd_f = fichiers_source(ID_ACV), fichiers_source(ID_PVD)
    absents = [n for n, f in (("Fonds vert", fv_fichiers), ("Action cœur de ville", acv_f),
                              ("Petites villes de demain", pvd_f)) if not f]
    if absents:
        raise SystemExit(f"sources absentes de data/lake : {', '.join(absents)} ; lancer la collecte "
                         "(python pipeline/projets_subventionnes.py collecter)")
    date = date_sources("subventions", "projets_subventionnes")
    lignes = lire_fonds_vert(fv_fichiers)
    sirens = {r["siren"] for r in lignes if r["siren"]}
    publiables, stock = classer(sirens)
    prenoms = _local().prenoms()
    par_dep, nat = produire_fonds_vert(lignes, communes, deps, publiables, stock, prenoms)
    acv = lire_badges([r for f in acv_f for r in lire_csv(f)], "acv")
    pvd = lire_badges([r for f in pvd_f for r in lire_csv(f)], "pvd")
    badges_hors_cog = [{"badge": b, "insee": i} for b, liste in (("acv", acv), ("pvd", pvd))
                       for i in liste if i not in communes]

    sortie.mkdir(parents=True, exist_ok=True)
    for vieux in sortie.glob("*.json"):
        vieux.unlink()
    tailles, resume_deps = {}, []
    for dep in sorted(deps):
        d = par_dep[dep]
        dem = sorted(d["demarches"])
        idx = {x: i for i, x in enumerate(dem)}
        coms = {}
        insees = sorted(set(d["communes"]) | {i for i in acv if communes.get(i, (None, None))[1] == dep}
                        | {i for i in pvd if communes.get(i, (None, None))[1] == dep})
        tous = []
        for insee in insees:
            c = {"nom": communes[insee][0]}
            b = {}
            if insee in acv:
                b["acv"] = acv[insee]
            if insee in pvd:
                b["pvd"] = pvd[insee]
            if b:
                c["badges"] = b
            proj = tri_projets(d["communes"].get(insee, []))
            tous += proj
            if proj:
                c["fonds_vert"] = [[x[0], x[1], idx.get(x[2]) if x[2] else None, x[3], x[4], x[5], x[6]] for x in proj]
                c["fonds_vert_totaux"] = totaux_par_annee(proj)
            coms[insee] = c
        hors = {}
        for insee in sorted(d["hors_cog"]):
            proj = tri_projets(d["hors_cog"][insee])
            tous += proj
            hors[insee] = [[x[0], x[1], idx.get(x[2]) if x[2] else None, x[3], x[4], x[5], x[6]] for x in proj]
        benef = {s: {"nom": v["nom"], "categorie_juridique": v["cj"]} for s, v in sorted(d["beneficiaires"].items())}
        totaux = totaux_par_annee(tous)
        lien = f"territoires/{dep}.json"
        obj = {
            **entete(date), "departement": {"code": dep, "nom": deps[dep]},
            "liens": {"dgcl": lien if (TERRITOIRES / f"{dep}.json").exists() else None,
                      "geo": f"local/geo/{dep}.json", "index": "projets_subventionnes/index.json"},
            "statuts": {"dgcl": STATUT_DGCL, "fonds_vert": STATUT_FV},
            "sans_projet": SANS_PROJET,
            "format_fonds_vert": ["annee", "programme", "demarche", "intitule", "montant_engage_eur",
                                  "beneficiaire_siren", "numero_engagement_juridique"],
            "demarches": dem,
            "beneficiaires": benef,
            "communes": coms,
            "communes_hors_cog": hors,
            "fonds_vert_totaux": {"statut": STATUT_CALCULE, "methode": METHODE_SOMME, "par_annee": totaux},
            "exclus_personnes_physiques_ou_non_identifies": {
                "note": "projets du Fonds vert sans bénéficiaire personne morale identifiable : comptés ici, sans nom "
                        "ni intitulé", "par_annee": {a: d["exclus"][a] for a in sorted(d["exclus"])}},
            "ordre": "communes par code Insee ; projets par année décroissante, puis montant décroissant, puis numéro "
                     "d'engagement juridique",
        }
        tailles[dep] = dump(sortie / f"{dep}.json", obj)
        resume_deps.append({
            "code": dep, "nom": deps[dep], "fichier": f"projets_subventionnes/{dep}.json",
            "fichier_dgcl": obj["liens"]["dgcl"],
            "fonds_vert_projets": sum(v["projets"] for v in totaux.values()),
            "communes_avec_fonds_vert": sum(1 for c in coms.values() if c.get("fonds_vert")),
            "communes_acv": sum(1 for c in coms.values() if "acv" in c.get("badges", {})),
            "communes_pvd": sum(1 for c in coms.values() if "pvd" in c.get("badges", {})),
        })

    par_annee = nat["par_annee"]
    index = {
        **entete(date),
        "statuts": {"dgcl": STATUT_DGCL, "fonds_vert": STATUT_FV,
                    "regle": "statut affiché tel que publié par la source ; la source ne dit pas si le projet est "
                             "réalisé"},
        "sans_projet": SANS_PROJET,
        "dispositifs": DISPOSITIFS,
        "badges": BADGES,
        "liens": [
            {"vue": "dotations", "fichier": "territoires/index.json", "lecture": "projets DETR, DSIL, DPV, DSID par "
             "bénéficiaire, un fichier par département (territoires/<dep>.json, investissement_etat)"},
            {"vue": "fonds_vert_beneficiaires", "fichier": "subventions/attribuants/subv_fonds_vert.json",
             "lecture": "totaux et principaux bénéficiaires du Fonds vert"},
        ] + ([{"vue": "fonds_vert_agregats", "fichier": "eau_environnement/fonds_vert.json",
               "lecture": "Fonds vert par région, instructeur, démarche (axe eau et environnement)"}]
             if (SITE / "eau_environnement" / "fonds_vert.json").exists() else []),
        "fonds_vert": {
            "statut": STATUT_CALCULE, "methode": METHODE_SOMME, "par_annee": par_annee,
            "intitules_retires": nat["intitules_retires"],
            "note": "montant_eur : toutes les lignes publiées ; montant_publie_eur : projets localisés et nommés ; "
                    "le reste est dans exclus (bénéficiaire non identifiable) et non_localises (sans commune)",
        },
        "badges_totaux": {"acv": len(acv), "pvd": len(pvd)},
        "badges_hors_cog": badges_hors_cog,
        "departements": resume_deps,
        "controles": {"fonds_vert_subventions": controle_subventions(par_annee)},
        "methode": METHODE, "limites": LIMITES,
        "sources": [{"id": k, **v} for k, v in SOURCES.items()],
        "sources_inaccessibles": [],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "tailles_octets": {"max": max(tailles.values()), "departements": len(tailles)},
        "ordre": "départements par code ; dispositifs dans l'ordre de la DGCL puis Fonds vert ; aucun classement",
    }
    dump(sortie / "index.json", index)
    return index


def collecter() -> int:
    ids = [ID_ACV, ID_PVD, ID_FV]
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *ids])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter()
    if a.etape in ("produire", "tout"):
        i = produire(a.sortie)
        fv = i["fonds_vert"]["par_annee"]
        print(f"projets_subventionnes : {len(i['departements'])} départements, Fonds vert "
              + ", ".join(f"{a} {v['lignes']} lignes" for a, v in fv.items())
              + f", {i['badges_totaux']['acv']} communes Action cœur de ville, "
                f"{i['badges_totaux']['pvd']} Petites villes de demain", file=sys.stderr)


if __name__ == "__main__":
    main()
