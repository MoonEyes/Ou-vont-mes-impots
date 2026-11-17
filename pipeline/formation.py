"""Formation professionnelle : compte personnel de formation (CPF), formation des élus locaux, FIPHFP.

Ce que la Caisse des dépôts publie en données ouvertes sur les dispositifs qu'elle gère : montants engagés au titre
du CPF par mois, département, certification et financeur ; entrées en formation par organisme ; profil des usagers ;
droit individuel à la formation des élus locaux (agrégats seulement, aucun élu nommé) ; aides et conventions du
FIPHFP aux employeurs publics. Agrégats publiés seulement, aucune donnée individuelle.

Entrées : entrepôt brut data/lake/formation/ (non versionné), rempli par `collecter` :
    mcf_engagees_mois.csv      CPF, formations engagées : année x mois x statut du dossier (agrégé côté serveur)
    mcf_engagees_dep.csv       idem, année x département du lieu de formation x statut
    mcf_engagees_modalite.csv  idem, année x modalité (présentiel, à distance, mixte) x statut
    mcf_engagees_certif.csv    idem, année x certification x groupe de statut
    mcf_entrees_of.csv         CPF, entrées et sorties : année x SIRET de l'organisme x certification (sans raison sociale)
    mcf_usagers.csv            CPF, usagers : année x statut x région x sexe x âge x situation
    elus_of.csv                formation des élus : année x SIRET de l'organisme x type de mandat x dispositif x statut
                               (nom, prénom et lieu de mandat des élus ne sont jamais demandés au portail)
    fiphfp_aides_dep.csv, fiphfp_conv_reg.csv   FIPHFP : aides par département, conventions par région
    ruf_cpf_2025.pdf           France compétences, rapport sur l'usage des fonds, fiche CPF (édition 2025)
  et data/lake/_cache/recherche_entreprises.json (catégorie juridique des organismes, pipeline/sirene.py).
Sorties (site/data/formation/, contrat docs/contrat_interface.md, schémas docs/schemas/formation_*.schema.json) :
    index.json, cpf_mois.json, cpf_departements.json, cpf_certifications.json, cpf_organismes.json, cpf_usagers.json,
    elus.json, fiphfp.json

Commandes :
    python pipeline/formation.py collecter [--forcer] [--budget-siren SECONDES]
        (réseau ; le portail coupe souvent : reprises espacées ; un refus 401/403/429 est noté, jamais contourné)
    python pipeline/formation.py produire      (sans réseau)

Règles :
  - le jeu des formations engagées compte 2,2 millions de lignes : il n'est jamais exporté en entier, seulement des
    agrégats calculés par le portail (API Explore v2.1, `group_by`) ;
  - un organisme n'est nommé que si sirene.personne_morale(catégorie juridique) est vrai ; le nom publié est celui du
    répertoire Sirene, jamais la raison sociale saisie sur la plateforme ; entrepreneurs individuels, SIREN invalides,
    absents du répertoire ou non vérifiés : agrégés ;
  - aucun élu nommé : les colonnes nom, prénom, genre et lieu de mandat ne sont pas téléchargées ; une cellule de
    moins de SEUIL_ELUS dossiers n'est jamais publiée seule (fondue avec d'autres types de mandat) ;
  - le montant par organisme n'est pas publié par la source : l'estimation (entrées x prix moyen de la certification
    la même année) est marquée « approché », avec sa méthode ;
  - les écarts entre sources (Caisse des dépôts, France compétences) sont publiés, jamais tranchés ni additionnés ;
  - toute date écrite vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BRUT = ROOT / "data" / "lake" / "formation"
MANIFESTE = ROOT / "data" / "lake" / "manifest.json"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "formation"
CDC = "https://opendata.caissedesdepots.fr"
API = f"{CDC}/api/explore/v2.1/catalog/datasets"
LICENCE = "Licence Ouverte 2.0"
UA = {"User-Agent": "ou-vont-mes-impots/pipeline (projet citoyen open source)"}

SEUIL_ELUS = 5          # cellule de moins de 5 dossiers d'élus : jamais publiée seule
NB_ORGANISMES = 1500    # organismes nommés publiés (par entrées cumulées), le reste agrégé
NB_CERTIFICATIONS = 400  # certifications publiées (par montant engagé cumulé), le reste agrégé
MIN_DOSSIERS_PRIX = 10  # prix moyen d'une certification retenu à partir de 10 dossiers la même année

FINANCEURS = [  # (clé publiée, colonne de montant, colonne du nombre de dossiers, libellé)
    ("france_competences", "part_france_competences", None,
     "Droits CPF mobilisés (financés par France compétences), nets des dotations des entreprises"),
    ("titulaire", "part_titulaire", "nb_dossiers_finances_par_titulaires", "Titulaire du compte (reste à charge)"),
    ("etat", "part_etat", "nb_dossiers_finances_par_etat", "État (abondement du plan de relance)"),
    ("france_travail", "part_pole_emploi", "nb_dossiers_finances_par_pole_emploi", "France Travail"),
    ("regions", "part_region", "nb_dossiers_finances_par_regions", "Régions (abondements automatisés)"),
    ("opco", "part_opco", "nb_dossiers_finances_par_opco", "Opérateurs de compétences (OPCO)"),
    ("entreprises", "part_entreprise", "nb_dossiers_finances_par_entreprises",
     "Entreprises (dotations et abondements automatisés)"),
    ("cec", "part_cec", "nb_dossiers_finances_par_cec", "Compte d'engagement citoyen (CEC)"),
]
SOMMES_ENGAGEES = ("sum(nb_dossiers) as nb_dossiers,sum(montant_engage) as montant_engage,"
                   + ",".join(f"sum({c}) as {c}" for _, c, _, _ in FINANCEURS) + ","
                   + ",".join(f"sum({n}) as {n}" for _, _, n, _ in FINANCEURS if n))

# Statuts du dossier (libellés de la source) regroupés ; « retenu » = dossier validé et non annulé.
STATUTS = {
    "Clos - Réalisation Totale": "realise",
    "Clos - Réalisation Partielle": "realise_partiellement",
    "Entrée en formation": "en_cours",
    "Sortie de formation": "en_cours",
    "Validé": "en_cours",
    "Clos - Non Réalisé annulé OF": "annule",
    "Clos - Non Réalisé annulé titulaire": "annule",
    "Clos - Non Réalisée": "annule",
    "Dossier annulé gestionnaire": "annule",
    "Rejeté": "annule",
}
GROUPES = {
    "realise": "Formation réalisée en totalité (dossier clos)",
    "realise_partiellement": "Formation réalisée en partie (dossier clos)",
    "en_cours": "Dossier validé, formation à venir, en cours ou terminée non close",
    "annule": "Dossier annulé ou rejeté (par l'organisme, le titulaire ou le gestionnaire), formation non réalisée",
}
RETENUS = ("realise", "realise_partiellement", "en_cours")
WHERE_RETENUS = "statut_dossier in (" + ",".join(f'"{s}"' for s, g in STATUTS.items() if g != "annule") + ")"

SOURCES = {
    "mcf_engagees_mois": {
        "dataset": "moncompteformation_formations_engagees", "fichier": "mcf_engagees_mois.csv",
        "params": {"select": SOMMES_ENGAGEES, "group_by": "annee_validation,mois_vali2,statut_dossier"}},
    "mcf_engagees_dep": {
        "dataset": "moncompteformation_formations_engagees", "fichier": "mcf_engagees_dep.csv",
        "params": {"select": SOMMES_ENGAGEES, "group_by": "annee_validation,dep_code,statut_dossier"}},
    "mcf_engagees_modalite": {
        "dataset": "moncompteformation_formations_engagees", "fichier": "mcf_engagees_modalite.csv",
        "params": {"select": SOMMES_ENGAGEES, "group_by": "annee_validation,modalite_presence,statut_dossier"}},
    "mcf_engagees_certif": {
        "dataset": "moncompteformation_formations_engagees", "fichier": "mcf_engagees_certif.csv",
        "params": {"select": "sum(nb_dossiers) as nb_dossiers,sum(montant_engage) as montant_engage,"
                             "sum(part_france_competences) as part_france_competences",
                   "group_by": "annee_validation,type_formation,code_rs,code_rncp,intitule_certification",
                   "where": WHERE_RETENUS}},
    "mcf_entrees_of": {
        "dataset": "entree_sortie_formation", "fichier": "mcf_entrees_of.csv",
        "params": {"select": "sum(entrees_formation) as entrees,sum(sorties_realisation_totale) as sorties_totales,"
                             "sum(sorties_realisation_partielle) as sorties_partielles",
                   "group_by": "annee,siret_of_contractant,type_referentiel,code_rs,code_rncp"}},
    "mcf_usagers": {
        "dataset": "moncompteformation-les-usagers", "fichier": "mcf_usagers.csv",
        "params": {"select": SOMMES_ENGAGEES,
                   "group_by": "annee_entree_formation,statut_dossier,code_region_domiciliation,region_domiciliation,"
                               "sexe_titulaire,classe_age,situation_titulaire"}},
    "elus_of": {
        "dataset": "moncompteelu-formations-elus", "fichier": "elus_of.csv",
        "params": {"select": "count(*) as nb_dossiers,sum(montant_engage) as montant_engage,"
                             "sum(financement_elu) as financement_elu,sum(nombre_heures_total) as heures",
                   "group_by": "year(date_validation) as annee,siret_of,type_mandat,dispositif_principal,"
                               "statut_dossier,statut_facture"}},
    "fiphfp_aides_dep": {   # petits jeux sans donnée personnelle : export ligne à ligne (les vides restent vides)
        "dataset": "fiphfp_financement_aidesplateforme_dpt", "fichier": "fiphfp_aides_dep.csv",
        "params": {"select": "year(annee_financement) as annee,code_departement,nom_departement,nom_region,"
                             "aides_fpe,aides_fph,aides_fpt",
                   "order_by": "annee_financement,code_departement,nom_departement"}},
    "fiphfp_conv_reg": {
        "dataset": "fiphfp_financement_conv_employeur_reg", "fichier": "fiphfp_conv_reg.csv",
        "params": {"select": "year(annee_financement) as annee,code_region,nom_region,conventions_fpe,"
                             "conventions_fph,conventions_fpt",
                   "order_by": "annee_financement,code_region"}},
}
RUF_URL = "https://www.francecompetences.fr/app/uploads/2026/02/RUF25_ComptePersonnelFormation.pdf"
RUF_FICHIER = "ruf_cpf_2025.pdf"


def page(dataset: str) -> str:
    return f"{CDC}/explore/dataset/{dataset}/"


# --- Collecte ---------------------------------------------------------------------------------------------------------

def _get(url: str, params: dict | None = None, essais: int = 6):
    """GET avec reprises espacées (le portail coupe souvent la connexion). Un refus n'est jamais contourné."""
    import requests
    derniere = ""
    for i in range(essais):
        try:
            r = requests.get(url, params=params, timeout=(20, 600), headers=UA)
            if r.status_code in (401, 403, 429, 451):
                return None, f"accès refusé (HTTP {r.status_code}) : aucun contournement"
            r.raise_for_status()
            return r, "ok"
        except Exception as e:  # coupure réseau : reprise
            derniere = f"{type(e).__name__}: {e}"[:160]
            time.sleep(5 * (i + 1))
    return None, f"échec après {essais} essais : {derniere}"


def _manifeste(sid: str, entree: dict) -> None:
    """Entrée du manifeste de l'entrepôt, sous le même verrou que collecte/collecte.py, écriture atomique."""
    MANIFESTE.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFESTE.with_name(MANIFESTE.name + ".lock"), "w") as v:
        fcntl.flock(v, fcntl.LOCK_EX)
        try:
            m = json.loads(MANIFESTE.read_text(encoding="utf-8")) if MANIFESTE.exists() else {}
            m[sid] = entree
            tmp = MANIFESTE.with_name(MANIFESTE.name + ".tmp")
            tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, MANIFESTE)
        finally:
            fcntl.flock(v, fcntl.LOCK_UN)


def _deposer(sid: str, dest: Path, contenu: bytes, url: str, extra: dict) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(contenu)
    tmp.replace(dest)
    _manifeste(f"formation__{sid}", {
        "collecte_le": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"), "domaine": "formation",
        "licence": LICENCE, "origine": "pipeline/formation.py", "personnes_physiques": False, "statut": "ok",
        "fichiers": [{"chemin": str(dest.relative_to(ROOT)), "octets": len(contenu),
                      "sha256": hashlib.sha256(contenu).hexdigest(), "url": url}], **extra})


def collecter(forcer: bool = False, budget_siren: float = 900) -> dict:
    BRUT.mkdir(parents=True, exist_ok=True)
    etat = {}
    for sid, s in SOURCES.items():
        dest = BRUT / s["fichier"]
        if dest.exists() and dest.stat().st_size > 0 and not forcer:
            etat[sid] = "présent"
        else:
            meta, msg = _get(f"{API}/{s['dataset']}")
            if meta is not None:
                d = meta.json()["metas"]["default"]
                url = f"{API}/{s['dataset']}/exports/csv"
                r, msg = _get(url, {**s["params"], "delimiter": ";"})
                if r is not None and r.content.strip():
                    _deposer(sid, dest, r.content, r.url, {
                        "dataset": s["dataset"], "portail": "cdc", "producteur": d.get("publisher"),
                        "source_modifiee_le": d.get("modified"), "lignes_source": d.get("records_count"),
                        "requete": s["params"]})
                elif r is not None:
                    msg = "réponse vide"
            etat[sid] = msg
        print(f"{sid}: {etat[sid]}")
    dest = BRUT / RUF_FICHIER
    if dest.exists() and not forcer:
        etat["ruf_cpf"] = "présent"
    else:
        r, msg = _get(RUF_URL)
        if r is not None and r.content[:4] != b"%PDF":
            r, msg = None, "contenu inattendu (pas un PDF) : aucun contournement"
        if r is not None:
            _deposer("ruf_cpf", dest, r.content, RUF_URL, {"producteur": "France compétences",
                                                             "licence": "document public, citation avec source"})
        etat["ruf_cpf"] = msg
    print(f"ruf_cpf: {etat['ruf_cpf']}")
    # Catégorie juridique des organismes (API Recherche d'entreprises), par entrées décroissantes, durée bornée.
    sirens = sirens_a_resoudre()
    if sirens:
        etat["sirene"] = resoudre_organismes(sirens, budget_siren)
        print("sirene:", etat["sirene"])
    return etat


def resoudre_organismes(sirens: list[str], budget_s: float, tranche_s: float = 240) -> str:
    """Résolution par tranches : le résultat de chaque tranche est figé dans l'entrepôt du module, sans dépendre du
    cache partagé (que d'autres collectes réécrivent en même temps)."""
    debut = time.monotonic()
    restants = len(sirens)
    while restants and time.monotonic() - debut < budget_s:
        cache = {**sirene.charger_cache(), **_figes()}
        cache, restants = sirene.resoudre(sirens, budget_s=min(tranche_s, budget_s), cache=cache)
        figer_sirene(cache)
    return f"{len(sirens) - restants} SIREN résolus ou déjà connus, {restants} restants (agrégés)"


# --- Lecture ----------------------------------------------------------------------------------------------------------

def lire(sid: str) -> list[dict]:
    p = BRUT / SOURCES[sid]["fichier"]
    return list(csv.DictReader(io.StringIO(p.read_bytes().decode("utf-8-sig")), delimiter=";"))


def num(v) -> float | None:
    """Nombre de la source ; vide, « nc » ou secret statistique : None (jamais 0)."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("nc", "nd", "n.c.", "s", "secret", "null", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def entier(v) -> int | None:
    x = num(v)
    return None if x is None else int(round(x))


def siren_de(siret) -> str | None:
    s = re.sub(r"\D", "", str(siret or ""))
    return s[:9] if len(s) == 14 else None


def sirens_a_resoudre() -> list[str]:
    """SIREN des organismes, par entrées CPF cumulées décroissantes, puis par dossiers d'élus (ordre déterministe)."""
    poids = defaultdict(float)
    if (BRUT / SOURCES["mcf_entrees_of"]["fichier"]).exists():
        for r in lire("mcf_entrees_of"):
            s = siren_de(r["siret_of_contractant"])
            if s:
                poids[s] += num(r["entrees"]) or 0
    elus = defaultdict(float)
    if (BRUT / SOURCES["elus_of"]["fichier"]).exists():
        for r in lire("elus_of"):
            s = siren_de(r["siret_of"])
            if s:
                elus[s] += num(r["nb_dossiers"]) or 0
    ordre = sorted(poids, key=lambda s: (-poids[s], s))
    ordre_elus = [s for s in sorted(elus, key=lambda s: (-elus[s], s)) if elus[s] >= SEUIL_ELUS]
    # organismes d'élus intercalés tôt : peu nombreux
    return list(dict.fromkeys(ordre[:NB_ORGANISMES] + ordre_elus + ordre))


# --- Production -------------------------------------------------------------------------------------------------------

ORGANISMES_SIRENE = "organismes_sirene.json"   # extrait du cache Sirene pour les organismes de ce module


def nom_sirene(nom: str) -> str:
    """Dénomination du répertoire Sirene ; le sigle entre parenthèses est retiré s'il répète la dénomination."""
    m = re.match(r"^(.*\S)\s*\(([^()]*)\)$", nom.strip())
    if m and _norm(m.group(1)) == _norm(m.group(2)):
        return m.group(1)
    return nom.strip()


def _figes() -> dict:
    p = BRUT / ORGANISMES_SIRENE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def figer_sirene(cache: dict | None = None) -> dict:
    """Copie dans l'entrepôt du module la catégorie juridique (et le nom Sirene des seules personnes morales) des
    organismes : la production ne dépend plus du cache partagé. Aucun nom n'est gardé pour une personne physique."""
    cache = sirene.charger_cache() if cache is None else cache
    p = BRUT / ORGANISMES_SIRENE
    ancien = _figes()
    for s in sirens_a_resoudre():
        e = cache.get(s)
        if e is not None:
            g = {"cj": e.get("cj"), "trouve": bool(e.get("trouve"))}
            if sirene.personne_morale(e.get("cj")) and e.get("nom"):
                g["nom"] = nom_sirene(e["nom"])
            if g["trouve"] or s not in ancien:   # une réponse « introuvable » n'efface pas une réponse trouvée
                ancien[s] = g
    contenu = json.dumps(ancien, ensure_ascii=False, sort_keys=True).encode("utf-8")
    _deposer("organismes_sirene", p, contenu, sirene.API, {
        "producteur": "Insee, répertoire Sirene (API Recherche d'entreprises)", "organismes": len(ancien)})
    return ancien


def _r(v, n: int = 0):
    if v is None:
        return None
    x = round(v, n)
    return int(x) if n == 0 else x


def _pct(a, b):
    return None if not b or a is None else round(a / b * 100, 1)


def _plus(d: dict, cle: str, v) -> None:
    """Somme qui garde l'absence : None + None = None."""
    if v is not None:
        d[cle] = (d.get(cle) or 0) + v
    else:
        d.setdefault(cle, None)


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    if len(texte.encode("utf-8")) > 5_000_000:
        raise SystemExit(f"{path} dépasse 5 Mo")
    path.write_text(texte, encoding="utf-8")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]", "", s)


def _groupe(statut: str) -> str:
    if statut not in STATUTS:
        raise SystemExit(f"statut de dossier inconnu à la source : {statut!r} (compléter STATUTS)")
    return STATUTS[statut]


def _cumul_engagees(lignes: list[dict], cle) -> dict:
    """{clé: {groupe de statut: {dossiers, montant, financeurs...}}} à partir d'un extrait des formations engagées."""
    res = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for r in lignes:
        g = res[cle(r)][_groupe(r["statut_dossier"])]
        g["dossiers"] += num(r["nb_dossiers"]) or 0
        g["montant"] += num(r["montant_engage"]) or 0
        for k, col, nb, _ in FINANCEURS:
            g[k] += num(r[col]) or 0
            if nb:
                g["nb_" + k] += num(r[nb]) or 0
    return res


def _retenu(par_groupe: dict, champ: str) -> float:
    return sum(par_groupe[g][champ] for g in RETENUS if g in par_groupe)


def _bloc(par_groupe: dict) -> dict:
    """Bloc publié pour une clé : dossiers et montants retenus, financeurs, détail par groupe de statut."""
    m = _retenu(par_groupe, "montant")
    return {
        "dossiers": _r(_retenu(par_groupe, "dossiers")), "montant_eur": _r(m),
        "financeurs_eur": {k: _r(_retenu(par_groupe, k)) for k, *_ in FINANCEURS},
        "financeurs_pct": {k: _pct(_retenu(par_groupe, k), m) for k, *_ in FINANCEURS},
        "dossiers_cofinances": {k: _r(_retenu(par_groupe, "nb_" + k)) for k, _, nb, _ in FINANCEURS if nb},
        "par_statut": {g: {"dossiers": _r(par_groupe[g]["dossiers"]), "montant_eur": _r(par_groupe[g]["montant"])}
                       for g in GROUPES if g in par_groupe},
    }


RUF = {  # France compétences, rapport sur l'usage des fonds, édition 2025, fiche CPF, graphique 1 (page 5)
    "document": "France compétences, Rapport sur l'usage des fonds de la formation professionnelle et du conseil en "
                "évolution professionnelle, édition 2025, fiche « Le compte personnel de formation », graphique 1",
    "url": RUF_URL,
    "champ": "Ensemble des dossiers validés, nets des annulations ; sources citées par le document : comptes annuels "
             "2020 à 2024 de la CDC (calculs France compétences) et jeu ouvert des formations engagées.",
    "valeurs": {  # année : (montant publié, dossiers publiés), tels qu'imprimés
        "2021": ("2,851 Md€", "2,099 M"), "2022": ("2,598 Md€", "1,805 M"),
        "2023": ("2,091 Md€", "1,340 M"), "2024": ("2,215 Md€", "1,391 M"),
    },
    "non_compare": {"periode": "novembre 2019 à 2020", "montant": "1,287 Md€", "dossiers": "1,042 M",
                    "raison": "le document regroupe novembre 2019 et l'année 2020 ; le jeu ouvert commence en 2020"},
}


def _nombre_fr(s: str) -> float:
    v, u = s.split(" ")
    return float(v.replace(",", ".")) * {"Md€": 1e9, "M": 1e6}[u]


def verifier_ruf() -> dict | None:
    """Chaque valeur citée est retrouvée dans le texte du document collecté (None si le document est absent)."""
    p = BRUT / RUF_FICHIER
    if not p.exists():
        return None
    import pdfplumber
    with pdfplumber.open(p) as doc:
        texte = re.sub(r"\s+", " ", " ".join((pg.extract_text() or "") for pg in doc.pages))
    valeurs = [v for paire in RUF["valeurs"].values() for v in paire]
    absents = [v for v in valeurs if v not in texte]
    if absents:
        raise SystemExit(f"valeurs citées absentes du document France compétences collecté : {absents}")
    return {"valeurs": len(valeurs), "retrouvees": len(valeurs) - len(absents)}


RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "conclusion": "La Caisse des dépôts publie déjà les agrégats nécessaires sur son portail (API Opendatasoft, "
                  "agrégation côté serveur) : ils sont repris tels quels. Aucun dépôt public trouvé ne relie ces jeux "
                  "aux financeurs du budget de l'État ni ne traite la confidentialité des organismes : module écrit "
                  "pour le dépôt, sur le modèle de pipeline/prestations.py et de pipeline/local_fonctions.py.",
    "trouvailles": [
        {"nom": "Caisse des dépôts, Moncompteformation, les formations engagées",
         "url": page("moncompteformation_formations_engagees"), "licence": LICENCE, "mise_a_jour": "2026-11-04",
         "verdict": "réutilisable tel quel (agrégats demandés au portail)"},
        {"nom": "Caisse des dépôts, Moncompteformation, entrées et sorties de formation",
         "url": page("entree_sortie_formation"), "licence": LICENCE, "mise_a_jour": "2026-11-05",
         "verdict": "à adapter (raison sociale saisie non reprise ; catégorie juridique vérifiée au répertoire Sirene)"},
        {"nom": "Caisse des dépôts, Moncompteformation, les usagers", "url": page("moncompteformation-les-usagers"),
         "licence": LICENCE, "mise_a_jour": "2026-10-04", "verdict": "réutilisable tel quel"},
        {"nom": "Caisse des dépôts, Moncompteelu, les formations réalisées par les élus",
         "url": page("moncompteelu-formations-elus"), "licence": LICENCE, "mise_a_jour": "2026-07-06",
         "verdict": "à adapter (le jeu nomme les élus : seuls des agrégats sans nom sont demandés)"},
        {"nom": "Caisse des dépôts, FIPHFP, aides de la plateforme et conventions employeurs",
         "url": page("fiphfp_financement_aidesplateforme_dpt"), "licence": LICENCE, "mise_a_jour": "2026-03-06",
         "verdict": "à adapter (libellés de départements et de régions hétérogènes, codes absents en 2019)"},
        {"nom": "France compétences, rapport sur l'usage des fonds, fiche CPF (édition 2025)", "url": RUF_URL,
         "licence": "document public, citation avec source", "mise_a_jour": "2026-02",
         "verdict": "inspiration seulement (PDF : montants nets annuels cités pour l'écart entre sources)"},
        {"nom": "evilgenius786/moncompteformation.gouv.fr_scraper (GitHub)",
         "url": "https://github.com/evilgenius786/moncompteformation.gouv.fr_scraper",
         "licence": "aucune licence publiée", "mise_a_jour": "2022-04-22",
         "verdict": "inspiration seulement (aspiration du site, sans licence ; le jeu officiel suffit)"},
    ],
}

SOURCES_INACCESSIBLES = [
    {"source": "DARES (data.dares.travail-emploi.gouv.fr, dares.travail-emploi.gouv.fr)",
     "motif": "protection contre les robots signalée pour cette source : non collectée, non contournée ; les séries "
              "de la DARES sur le CPF ne sont pas reprises"},
    {"source": "Montant versé à chaque organisme de formation",
     "motif": "non publié : le jeu des entrées et sorties ne donne que des effectifs par organisme, le jeu des "
              "formations engagées ne donne pas l'organisme"},
    {"source": "Formations engagées avant 2020, entrées par organisme avant 2022",
     "motif": "absentes des jeux ouverts (Mon compte formation a ouvert le 21 novembre 2019)"},
]


def _annee_complete(annee: str, mois_presents: set[str], date: str) -> bool:
    return len(mois_presents) == 12 and int(annee) < int(date[:4])


def produire_cpf(date: str) -> dict:
    # 1. par mois et par année
    par_mois = _cumul_engagees(lire("mcf_engagees_mois"), lambda r: (r["annee_validation"], r["mois_vali2"]))
    annees = sorted({a for a, _ in par_mois})
    par_an = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for (a, _), groupes in par_mois.items():
        for g, v in groupes.items():
            for k, x in v.items():
                par_an[a][g][k] += x
    mois = {f"{a}-{m}": _bloc(par_mois[(a, m)]) for a, m in sorted(par_mois)}
    for v in mois.values():
        del v["financeurs_pct"], v["dossiers_cofinances"]
    cpf_annees = {}
    for a in annees:
        b = _bloc(par_an[a])
        b["complete"] = _annee_complete(a, {m for x, m in par_mois if x == a}, date)
        b["prix_moyen_eur"] = _r(b["montant_eur"] / b["dossiers"]) if b["dossiers"] else None
        cpf_annees[a] = b
    entete = {
        "millesime": f"Dossiers validés de {annees[0]} à {annees[-1]} (année {annees[-1]} en cours ; données "
                     f"collectées le {date})",
        "source": f"Caisse des dépôts et DGEFP, Moncompteformation, les formations engagées "
                  f"({page('moncompteformation_formations_engagees')}), agrégats calculés par le portail ; {LICENCE}",
        "unite": "euros (montant engagé : somme des prix des formations des dossiers), dossiers",
        "collecte_le": date,
    }
    dump(SORTIE / "cpf_mois.json", {
        **entete,
        "avertissement": "Montants engagés à la validation du dossier par le titulaire, pas montants payés aux "
                         "organismes ; le mois est celui de la validation. Les dossiers annulés ou rejetés sont "
                         "publiés à part et ne sont pas comptés dans « dossiers » ni « montant_eur ».",
        "statuts": GROUPES, "retenus": list(RETENUS), "mois": mois})

    # 2. par département du lieu de formation, par modalité
    par_dep = _cumul_engagees(lire("mcf_engagees_dep"), lambda r: (r["annee_validation"], r["dep_code"]))
    cols = ["dossiers", "montant_eur", "france_competences_eur", "titulaire_eur", "autres_financeurs_eur",
            "dossiers_annules", "montant_annule_eur"]

    def ligne(g):
        m, fc, ti = _retenu(g, "montant"), _retenu(g, "france_competences"), _retenu(g, "titulaire")
        autres = sum(_retenu(g, k) for k, *_ in FINANCEURS if k not in ("france_competences", "titulaire"))
        an = g.get("annule", {})
        return [_r(_retenu(g, "dossiers")), _r(m), _r(fc), _r(ti), _r(autres), _r(an.get("dossiers", 0)),
                _r(an.get("montant", 0))]
    deps = {a: {d: ligne(par_dep[(x, d)]) for x, d in sorted(par_dep) if x == a and d} for a in annees}
    sans_lieu = {a: ligne(par_dep[(a, "")]) for a in annees if (a, "") in par_dep}
    par_mod = _cumul_engagees(lire("mcf_engagees_modalite"), lambda r: (r["annee_validation"], r["modalite_presence"]))
    modalites = {a: {m: ligne(par_mod[(x, m)])[:2] for x, m in sorted(par_mod) if x == a} for a in annees}
    dump(SORTIE / "cpf_departements.json", {
        **entete,
        "avertissement": "Département du lieu de formation déclaré par l'organisme, pas du domicile du titulaire. "
                         "Le lieu n'est pas communiqué pour une part des dossiers, dont les formations à distance : "
                         "ils sont publiés dans « lieu_non_communique » et ne sont rattachés à aucun département.",
        "colonnes": cols, "departements": deps, "lieu_non_communique": sans_lieu,
        "modalites": {"colonnes": cols[:2], "annees": modalites},
        "note": "autres_financeurs_eur = État, France Travail, régions, OPCO, entreprises et compte d'engagement "
                "citoyen ; le détail national par financeur est dans formation/index.json."})

    # 3. par certification (dossiers retenus seulement)
    certifs = defaultdict(lambda: {"annees": defaultdict(lambda: [0.0, 0.0, 0.0]), "noms": defaultdict(float)})
    for r in lire("mcf_engagees_certif"):
        t = r["type_formation"]
        code = r["code_rs"] if t == "RS" else r["code_rncp"] if t == "RNCP" else None
        cle = (t, code) if code and not code.startswith("-") else ("Autre", _norm(r["intitule_certification"]))
        c = certifs[cle]
        v = c["annees"][r["annee_validation"]]
        v[0] += num(r["nb_dossiers"]) or 0
        v[1] += num(r["montant_engage"]) or 0
        v[2] += num(r["part_france_competences"]) or 0
        c["noms"][r["intitule_certification"].strip()] += num(r["montant_engage"]) or 0
    total_c = {k: sum(v[1] for v in c["annees"].values()) for k, c in certifs.items()}
    ordre = sorted(certifs, key=lambda k: (-total_c[k], k[0], str(k[1])))
    liste = []
    for k in ordre[:NB_CERTIFICATIONS]:
        c = certifs[k]
        nom = sorted(c["noms"], key=lambda n: (-c["noms"][n], n))[0]
        liste.append({
            "referentiel": k[0], "code": k[1] if k[0] != "Autre" else None, "intitule": nom,
            "montant_cumule_eur": _r(total_c[k]),
            "annees": {a: [_r(v[0]), _r(v[1]), _r(v[2]), _r(v[1] / v[0]) if v[0] else None]
                       for a, v in sorted(c["annees"].items())}})
    reste = defaultdict(lambda: [0.0, 0.0, 0.0])
    for k in ordre[NB_CERTIFICATIONS:]:
        for a, v in certifs[k]["annees"].items():
            for i in range(3):
                reste[a][i] += v[i]
    par_ref = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for k, c in certifs.items():
        for a, v in c["annees"].items():
            par_ref[k[0]][a][0] += v[0]
            par_ref[k[0]][a][1] += v[1]
    dump(SORTIE / "cpf_certifications.json", {
        **entete,
        "avertissement": "Dossiers validés et non annulés. Le référentiel « Autre » regroupe les formations hors "
                         "répertoires de France compétences (permis de conduire, bilan de compétences, validation des "
                         "acquis de l'expérience, création d'entreprise), identifiées par leur intitulé.",
        "ordre": {"regle": f"Les {NB_CERTIFICATIONS} certifications au montant engagé cumulé le plus élevé, par "
                           "montant cumulé décroissant puis référentiel et code ; les autres sont additionnées dans "
                           "« autres_certifications ».", "cles": ["-montant_cumule_eur", "referentiel", "code"]},
        "colonnes": ["dossiers", "montant_eur", "france_competences_eur", "prix_moyen_eur"],
        "referentiels": {"RNCP": "Répertoire national des certifications professionnelles",
                         "RS": "Répertoire spécifique", "Autre": "Hors répertoires"},
        "par_referentiel": {t: {a: [_r(v[0]), _r(v[1])] for a, v in sorted(x.items())}
                            for t, x in sorted(par_ref.items())},
        "nombre_certifications": len(certifs), "certifications": liste,
        "autres_certifications": {"nombre": max(0, len(certifs) - NB_CERTIFICATIONS),
                                  "annees": {a: [_r(v[0]), _r(v[1]), _r(v[2])] for a, v in sorted(reste.items())}}})

    # 4. usagers (dossiers entrés en formation, par année d'entrée)
    dims = {"region": lambda r: r["region_domiciliation"], "sexe": lambda r: r["sexe_titulaire"],
            "age": lambda r: r["classe_age"], "situation": lambda r: r["situation_titulaire"]}
    us = {d: defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])) for d in dims}
    tot_us = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for r in lire("mcf_usagers"):
        vals = [num(r["nb_dossiers"]) or 0, num(r["montant_engage"]) or 0, num(r["part_france_competences"]) or 0,
                num(r["part_titulaire"]) or 0]
        a = r["annee_entree_formation"]
        for i, x in enumerate(vals):
            tot_us[a][i] += x
            for d, f in dims.items():
                us[d][a][f(r) or "NC"][i] += x
    lib = {"NC": "non communiqué", "DOM-TOM": "Outre-mer (regroupé par la source)", "F": "Femmes", "M": "Hommes"}
    dump(SORTIE / "cpf_usagers.json", {
        "millesime": f"Entrées en formation de {min(tot_us)} à {max(tot_us)} (année {max(tot_us)} en cours ; données "
                     f"collectées le {date})",
        "source": f"Caisse des dépôts et DGEFP, Moncompteformation, les usagers "
                  f"({page('moncompteformation-les-usagers')}), agrégats calculés par le portail ; {LICENCE}",
        "unite": "dossiers, euros", "collecte_le": date,
        "avertissement": "Dossiers entrés en formation, classés par année d'entrée et par région de domicile du "
                         "titulaire : champ différent des formations engagées (année de validation, tous dossiers "
                         "non annulés). Une personne qui a plusieurs dossiers est comptée plusieurs fois.",
        "colonnes": ["dossiers", "montant_eur", "france_competences_eur", "titulaire_eur"],
        "libelles": lib,
        "annees": {a: {"total": [_r(x) for x in tot_us[a]],
                       **{d: {k: [_r(x) for x in v] for k, v in sorted(us[d][a].items()) if v[0]} for d in dims}}
                   for a in sorted(tot_us)}})
    return {"annees": cpf_annees, "entete": entete, "certifs": certifs}


def produire_organismes(date: str, certifs: dict) -> dict:
    """Entrées en formation par organisme (SIREN) ; montant approché = entrées x prix moyen de la certification."""
    cj = json.loads((BRUT / ORGANISMES_SIRENE).read_text(encoding="utf-8")) if (BRUT / ORGANISMES_SIRENE).exists() \
        else {}
    # prix moyen : certification et année ; à défaut certification toutes années ; à défaut référentiel et année
    prix_ca, prix_c, prix_ra = {}, {}, {}
    cumul_c, cumul_ra = defaultdict(lambda: [0.0, 0.0]), defaultdict(lambda: [0.0, 0.0])
    for (t, code), c in certifs.items():
        if t == "Autre":
            continue
        for a, v in c["annees"].items():
            if v[0] >= MIN_DOSSIERS_PRIX:
                prix_ca[(t, code, a)] = v[1] / v[0]
            cumul_c[(t, code)][0] += v[0]
            cumul_c[(t, code)][1] += v[1]
            cumul_ra[(t, a)][0] += v[0]
            cumul_ra[(t, a)][1] += v[1]
    prix_c = {k: v[1] / v[0] for k, v in cumul_c.items() if v[0] >= MIN_DOSSIERS_PRIX}
    prix_ra = {k: v[1] / v[0] for k, v in cumul_ra.items() if v[0]}

    org = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))   # siren -> année -> entrées, st, sp, €
    niveau = defaultdict(lambda: defaultdict(float))                        # année -> niveau de prix -> entrées
    invalides = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    etablissements = defaultdict(set)
    for r in lire("mcf_entrees_of"):
        a, t = r["annee"], r["type_referentiel"]
        code = r["code_rs"] if t == "RS" else r["code_rncp"]
        e = num(r["entrees"]) or 0
        if (t, code, a) in prix_ca:
            p, n = prix_ca[(t, code, a)], "certification_annee"
        elif (t, code) in prix_c:
            p, n = prix_c[(t, code)], "certification_toutes_annees"
        elif (t, a) in prix_ra:
            p, n = prix_ra[(t, a)], "referentiel_annee"
        else:
            p, n = None, "sans_prix"
        niveau[a][n] += e
        s = siren_de(r["siret_of_contractant"])
        cible = org[s][a] if s else invalides[a]
        cible[0] += e
        cible[1] += num(r["sorties_totales"]) or 0
        cible[2] += num(r["sorties_partielles"]) or 0
        if p is not None:
            cible[3] += e * p
        if s:
            etablissements[s].add(r["siret_of_contractant"])
    annees = sorted({a for v in org.values() for a in v} | set(invalides))

    def categorie(s):
        e = cj.get(s)
        if e is None:
            return "non_verifie"
        if not e.get("trouve"):
            return "absent_du_repertoire"
        return "personne_morale" if sirene.personne_morale(e.get("cj")) and e.get("nom") else "personne_physique"
    cumul = {s: sum(v[0] for v in x.values()) for s, x in org.items()}
    morales = sorted((s for s in org if categorie(s) == "personne_morale"), key=lambda s: (-cumul[s], s))
    nommes = morales[:NB_ORGANISMES]
    liste = [{"siren": s, "nom": cj[s]["nom"], "categorie_juridique": cj[s]["cj"],
              "etablissements": len(etablissements[s]), "entrees_cumulees": _r(cumul[s]),
              "annees": {a: [_r(v[0]), _r(v[1]), _r(v[2]), _r(v[3])] for a, v in sorted(org[s].items())}}
             for s in nommes]
    groupes = {
        "personnes_morales_non_listees": [s for s in morales[NB_ORGANISMES:]],
        "entrepreneurs_individuels_et_groupements_de_personnes": [s for s in org if categorie(s) == "personne_physique"],
        "absents_du_repertoire_sirene": [s for s in org if categorie(s) == "absent_du_repertoire"],
        "categorie_juridique_non_verifiee": [s for s in org if categorie(s) == "non_verifie"],
    }
    agreges = {}
    for g, sirens in groupes.items():
        an = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])
        for s in sirens:
            for a, v in org[s].items():
                for i in range(4):
                    an[a][i] += v[i]
                an[a][4] += 1
        agreges[g] = {"organismes": len(sirens),
                      "annees": {a: [_r(x) for x in an[a][:4]] + [an[a][4]] for a in sorted(an)}}
    if any(invalides.values()):
        agreges["siret_invalide"] = {"organismes": None, "annees": {a: [_r(x) for x in v] + [None]
                                                                     for a, v in sorted(invalides.items())}}
    totaux = {}
    for a in annees:
        t = [sum(x[a][i] for x in org.values() if a in x) + invalides.get(a, [0, 0, 0, 0])[i] for i in range(4)]
        nomm = [sum(org[s][a][i] for s in nommes if a in org[s]) for i in range(4)]
        ref = sum(v[1] for k, v in cumul_ra.items() if k[1] == a)
        totaux[a] = {"entrees": _r(t[0]), "sorties_totales": _r(t[1]), "sorties_partielles": _r(t[2]),
                     "montant_approche_eur": _r(t[3]), "organismes": sum(1 for x in org.values() if a in x),
                     "entrees_nommees": _r(nomm[0]), "entrees_nommees_pct": _pct(nomm[0], t[0]),
                     "entrees_par_niveau_de_prix": {n: _r(v) for n, v in sorted(niveau[a].items())},
                     "controle_estimation": {
                         "montant_engage_rncp_rs_eur": _r(ref), "ecart_eur": _r(t[3] - ref),
                         "ecart_pct": _pct(t[3] - ref, ref)}}
    dump(SORTIE / "cpf_organismes.json", {
        "millesime": f"Entrées en formation de {annees[0]} à {annees[-1]} (année {annees[-1]} en cours ; données "
                     f"collectées le {date})",
        "source": f"Caisse des dépôts et DGEFP, Moncompteformation, entrées et sorties de formation "
                  f"({page('entree_sortie_formation')}), agrégats par SIRET calculés par le portail ; prix moyens : "
                  f"les formations engagées ({page('moncompteformation_formations_engagees')}) ; catégorie juridique "
                  f"et dénomination : Insee, répertoire Sirene (recherche-entreprises.api.gouv.fr) ; {LICENCE}",
        "unite": "entrées et sorties de formation (stagiaires), euros approchés", "collecte_le": date,
        "avertissement": "La source publie des effectifs par organisme, pas des montants. « montant_approche_eur » est "
                         "une estimation du projet, pas un montant versé ni un chiffre d'affaires : elle ne doit pas "
                         "être citée comme une donnée de la Caisse des dépôts.",
        "estimation": {
            "statut": "approché", "producteur": "projet Où vont mes impôts (calcul du pipeline)",
            "perimetre": "Entrées en formation sur des certifications du RNCP et du répertoire spécifique ; les "
                         "formations hors répertoires (permis de conduire, bilan de compétences, VAE, création "
                         "d'entreprise) sont absentes du jeu des entrées par organisme.",
            "methode": "Pour chaque organisme, certification et année : entrées en formation x prix moyen de la "
                       "certification (montant engagé / dossiers validés non annulés la même année, tous organismes "
                       f"confondus, si au moins {MIN_DOSSIERS_PRIX} dossiers) ; à défaut prix moyen de la "
                       "certification toutes années ; à défaut prix moyen du référentiel la même année.",
            "limites": ["Le prix réel de chaque organisme n'est pas publié : un organisme dont les prix s'écartent de "
                        "la moyenne de la certification est mal estimé.",
                        "L'année d'entrée en formation n'est pas toujours l'année de validation du dossier.",
                        "Une entrée en formation n'est pas un paiement : la Caisse des dépôts paie l'organisme après "
                        "service fait, en tout ou partie selon la réalisation.",
                        "« controle_estimation » compare, par année, la somme des estimations au montant engagé des "
                        "certifications RNCP et RS : l'écart mesure la différence de champ et de calendrier."]},
        "regle_personnes": "Un organisme est nommé seulement si sa catégorie juridique au répertoire Sirene est celle "
                           "d'une personne morale (2xxx à 9xxx, hors groupements de personnes physiques). Le nom "
                           "publié est la dénomination du répertoire Sirene ; la raison sociale saisie sur la "
                           "plateforme n'est pas téléchargée. Entrepreneurs individuels, organismes absents du "
                           "répertoire ou non vérifiés : additionnés, jamais nommés.",
        "ordre": {"regle": f"Les {NB_ORGANISMES} personnes morales aux entrées en formation cumulées les plus "
                           "nombreuses, par entrées cumulées décroissantes puis SIREN ; les autres sont additionnées "
                           "dans « agreges ».", "cles": ["-entrees_cumulees", "siren"]},
        "colonnes": ["entrees", "sorties_totales", "sorties_partielles", "montant_approche_eur"],
        "colonnes_agreges": ["entrees", "sorties_totales", "sorties_partielles", "montant_approche_eur", "organismes"],
        "annees": annees, "totaux": totaux, "organismes": liste, "agreges": agreges})
    return {"annees": annees, "totaux": totaux, "nommes": len(liste),
            "agreges": {g: v["organismes"] for g, v in agreges.items()}}


MANDATS = {"Municipal": "municipal", "Départemental": "departemental", "Régional": "regional", "Autres": "autres"}
DISPOSITIFS = {"DIF Elu pour exercice du mandat": "exercice_du_mandat",
               "DIF Elu en vue d'une reconversion": "reconversion"}


def regrouper(cellules: dict) -> list[dict]:
    """Cellules {mandat: [dossiers, ...]} d'une année et d'un dispositif : toute cellule de moins de SEUIL_ELUS
    dossiers est fondue avec d'autres (des plus petites aux plus grandes) jusqu'à atteindre le seuil. Chaque cellule
    publiée liste les mandats qu'elle contient : rien n'est masqué ni déductible par soustraction."""
    ordre = sorted(cellules, key=lambda m: (cellules[m][0], m))
    petites = [m for m in ordre if cellules[m][0] < SEUIL_ELUS]
    grandes = [m for m in ordre if cellules[m][0] >= SEUIL_ELUS]
    res = []
    if petites:
        lot = list(petites)
        while sum(cellules[m][0] for m in lot) < SEUIL_ELUS and grandes:
            lot.append(grandes.pop(0))
        res.append(lot)
    res += [[m] for m in grandes]
    return [{"mandats": sorted(lot), "valeurs": [_r(sum(cellules[m][i] for m in lot)) for i in range(4)]}
            for lot in sorted(res, key=lambda lot: sorted(lot))]


def produire_elus(date: str) -> dict:
    cj = json.loads((BRUT / ORGANISMES_SIRENE).read_text(encoding="utf-8")) if (BRUT / ORGANISMES_SIRENE).exists() \
        else {}
    nat = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))    # année -> (mandat, dispositif)
    factures = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    org = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))
    tot = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    annules = 0
    for r in lire("elus_of"):
        vals = [num(r["nb_dossiers"]) or 0, num(r["montant_engage"]) or 0, num(r["financement_elu"]) or 0,
                num(r["heures"]) or 0]
        if _groupe(r["statut_dossier"]) == "annule":
            annules += int(vals[0])
            continue
        a = r["annee"]
        types = r["type_mandat"].split()
        mandat = MANDATS.get(types[0], "autres") if len(types) == 1 else "plusieurs_mandats"
        disp = DISPOSITIFS.get(r["dispositif_principal"])
        if disp is None:
            raise SystemExit(f"dispositif inconnu : {r['dispositif_principal']!r}")
        s = siren_de(r["siret_of"])
        for i, x in enumerate(vals):
            nat[a][(mandat, disp)][i] += x
            tot[a][i] += x
            org[s][a][i] += x
        factures[a][r["statut_facture"]][0] += vals[0]
        factures[a][r["statut_facture"]][1] += vals[1]
    annees = sorted(tot)
    arr = lambda v: [_r(v[0]), _r(v[1]), _r(v[2]), _r(v[3])]  # noqa: E731
    cumul = {s: [sum(x[a][i] for a in x) for i in range(4)] for s, x in org.items()}

    def nommable(s):
        e = cj.get(s) if s else None
        return bool(e and e.get("trouve") and sirene.personne_morale(e.get("cj")) and e.get("nom")
                    and cumul[s][0] >= SEUIL_ELUS)
    nommes = sorted((s for s in org if nommable(s)), key=lambda s: (-cumul[s][0], s))
    liste = [{"siren": s, "nom": cj[s]["nom"], "categorie_juridique": cj[s]["cj"], "cumul": arr(cumul[s])}
             for s in nommes]
    reste = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for s in org:
        if s not in set(nommes):
            for a, v in org[s].items():
                for i in range(4):
                    reste[a][i] += v[i]
    par_mandat = {a: {d: regrouper({m: v for (m, x), v in nat[a].items() if x == d})
                      for d in DISPOSITIFS.values() if any(x == d for _, x in nat[a])} for a in annees}
    regroupees = sum(1 for a in par_mandat for lots in par_mandat[a].values() for c in lots if len(c["mandats"]) > 1)
    dump(SORTIE / "elus.json", {
        "millesime": f"Dossiers validés de {annees[0]} à {annees[-1]} (année {annees[-1]} en cours ; données "
                     f"collectées le {date})",
        "source": f"Caisse des dépôts et DGEFP, Moncompteelu, les formations réalisées par les élus "
                  f"({page('moncompteelu-formations-elus')}), agrégats calculés par le portail ; catégorie juridique "
                  f"et dénomination des organismes : Insee, répertoire Sirene ; {LICENCE}",
        "unite": "dossiers, euros, heures", "collecte_le": date,
        "avertissement": "Droit individuel à la formation des élus locaux, géré par la Caisse des dépôts. Agrégats "
                         "seulement : le site ne publie le nom d'aucun élu, ni sa commune, ni un dossier isolé.",
        "regle_personnes": "Le jeu d'origine nomme chaque élu : les colonnes nom, prénom, genre et lieu de mandat ne "
                           "sont jamais téléchargées, le portail ne renvoie que des sommes. Une cellule de moins de "
                           f"{SEUIL_ELUS} dossiers n'est jamais publiée seule : elle est fondue avec d'autres types "
                           f"de mandat (champ « mandats »). Un organisme est nommé s'il est une personne morale au "
                           f"répertoire Sirene et compte au moins {SEUIL_ELUS} dossiers cumulés, sans détail par "
                           "année ; les autres sont additionnés.",
        "definitions": {
            "montant_engage_eur": "Montant facturé à l'organisme, ou prévisionnel tant que la facture n'est pas payée",
            "droits_elu_eur": "Part financée par les droits de l'élu (champ financement_elu de la source)",
            "mandats": {"municipal": "Mandat municipal", "departemental": "Mandat départemental",
                        "regional": "Mandat régional", "autres": "Autre mandat (libellé de la source)",
                        "plusieurs_mandats": "Plusieurs types de mandat pour le même dossier"},
            "dispositifs": {"exercice_du_mandat": "Formation liée à l'exercice du mandat",
                            "reconversion": "Formation en vue d'une reconversion"}},
        "colonnes": ["dossiers", "montant_engage_eur", "droits_elu_eur", "heures"],
        "annees": annees,
        "totaux": {a: arr(tot[a]) for a in annees},
        "par_mandat": par_mandat,
        "cellules_regroupees": regroupees,
        "factures": {"colonnes": ["dossiers", "montant_engage_eur"],
                     "annees": {a: {k: [_r(v[0]), _r(v[1])] for k, v in sorted(factures[a].items())} for a in annees}},
        "dossiers_annules_exclus": annules,
        "ordre": {"regle": "Organismes par nombre de dossiers cumulés décroissant, puis SIREN.",
                  "cles": ["-dossiers_cumules", "siren"]},
        "organismes": liste,
        "autres_organismes": {"organismes": len(org) - len(nommes),
                              "annees": {a: arr(reste[a]) for a in sorted(reste)}}})
    return {"annees": annees, "totaux": {a: arr(tot[a]) for a in annees}, "organismes_nommes": len(liste),
            "organismes_agreges": len(org) - len(nommes), "cellules_regroupees": regroupees}


VERSANTS = {"fpe": "Fonction publique de l'État", "fph": "Fonction publique hospitalière",
            "fpt": "Fonction publique territoriale"}


def produire_fiphfp(date: str) -> dict:
    aides = lire("fiphfp_aides_dep")
    codes = {}   # nom normalisé -> code, appris sur les lignes qui portent un code
    for r in aides:
        c = r["code_departement"].strip()
        if c:
            codes.setdefault(_norm(r["nom_departement"]), c.zfill(2))
    par = defaultdict(lambda: defaultdict(dict))
    sans_annee, non_rattachees = 0, defaultdict(dict)
    noms = {}
    for r in aides:
        if not r["annee"]:
            sans_annee += 1
            continue
        code = r["code_departement"].strip().zfill(2) if r["code_departement"].strip() \
            else codes.get(_norm(r["nom_departement"]))
        nationaux = _norm(r["nom_region"]) == "EMPLOYEURSNATIONAUX"
        cible = par[r["annee"]][code] if code else non_rattachees[r["annee"]]
        if code:
            noms.setdefault(code, r["nom_departement"].strip())
        for v in VERSANTS:
            x = num(r[f"aides_{v}"])
            _plus(cible, "employeurs_nationaux" if nationaux else v, x)
    cols = ["fpe", "fph", "fpt", "employeurs_nationaux"]
    annees = sorted(par)
    deps = {a: {c: [_r(par[a][c].get(k)) for k in cols] for c in sorted(par[a])} for a in annees}

    def somme(vals):
        vals = [v for v in vals if v is not None]
        return _r(sum(vals)) if vals else None
    tot_aides = {a: {k: somme(par[a][c].get(k) for c in par[a]) for k in cols} for a in annees}
    for a in annees:
        tot_aides[a]["non_localise"] = somme(non_rattachees.get(a, {}).values())
        tot_aides[a]["total"] = somme(tot_aides[a].values())
    conv = defaultdict(dict)
    regions = {}
    for r in lire("fiphfp_conv_reg"):
        if not r["annee"]:
            continue
        regions.setdefault(r["code_region"], r["nom_region"].strip())
        conv[r["annee"]][r["code_region"]] = [_r(num(r[f"conventions_{v}"])) for v in VERSANTS]
    tot_conv = {a: {**{v: somme(x[i] for x in conv[a].values()) for i, v in enumerate(VERSANTS)}} for a in sorted(conv)}
    for a in tot_conv:
        tot_conv[a]["total"] = somme(tot_conv[a].values())
    dump(SORTIE / "fiphfp.json", {
        "millesime": f"Aides {annees[0]} à {annees[-1]} ; conventions {min(conv)} à {max(conv)} (données collectées "
                     f"le {date})",
        "source": f"Caisse des dépôts, FIPHFP : aides financières attribuées aux employeurs publics "
                  f"({page('fiphfp_financement_aidesplateforme_dpt')}) ; masses attribuées par conventions aux "
                  f"employeurs publics ({page('fiphfp_financement_conv_employeur_reg')}) ; {LICENCE}",
        "unite": "euros courants", "collecte_le": date,
        "avertissement": "Fonds pour l'insertion des personnes handicapées dans la fonction publique (FIPHFP), géré "
                         "par la Caisse des dépôts : aides ponctuelles demandées par les employeurs publics sur la "
                         "plateforme et montants attribués par convention pluriannuelle. Les deux séries sont "
                         "publiées côte à côte et ne sont pas additionnées ici. Aucun employeur n'est nommé par la "
                         "source.",
        "versants": VERSANTS,
        "aides": {
            "colonnes": cols, "annees": annees, "departements": deps, "noms_departements": dict(sorted(noms.items())),
            "totaux": tot_aides,
            "note": "Une valeur absente à la source reste null, jamais 0. « employeurs_nationaux » : aides aux "
                    "employeurs nationaux localisées dans le département (tous versants). « non_localise » (totaux) : "
                    "lignes sans département reconnu, pour l'essentiel les employeurs nationaux avant 2019 et en "
                    "2022. Les lignes de 2019 n'ont pas de code de département à la source : il est retrouvé par le "
                    "nom. Codes et noms de département repris de la source.",
            "lignes_sans_annee_ni_montant": sans_annee},
        "conventions": {"colonnes": list(VERSANTS), "annees": sorted(conv),
                        "regions": {a: dict(sorted(conv[a].items())) for a in sorted(conv)},
                        "noms_regions": dict(sorted(regions.items())), "totaux": tot_conv,
                        "note": "Code « 00 » : employeurs nationaux."}})
    return {"aides": tot_aides, "conventions": tot_conv}


def _liens() -> list[dict]:
    """Même argent vu du côté des financeurs déjà publiés : liens, jamais additionnés."""
    liens = []
    p = SITE / "operateurs" / "operateurs.json"
    if p.exists():
        op = next((o for o in json.loads(p.read_text(encoding="utf-8"))["operateurs"]
                   if o.get("id") == "francecompetences"), None)
        if op:
            liens.append({
                "vue": "operateurs", "fichier": "operateurs/operateurs.json", "id": "francecompetences",
                "nom": op["nom"], "siren": op.get("siren"), "programme_chef_de_file": op.get("programme_chef_de_file"),
                "annees": {a: {"financement_etat_cp_eur": v.get("financement_etat_total_cp_eur"),
                               "taxes_affectees_eur": v.get("taxes_affectees_eur")}
                           for a, v in sorted(op["annees"].items()) if v.get("nature") == "execution"},
                "lecture": "France compétences répartit les contributions des employeurs à la formation "
                           "professionnelle et à l'apprentissage et reçoit des crédits de l'État ; elle verse à la "
                           "Caisse des dépôts la dotation qui finance les droits CPF. Ses ressources couvrent aussi "
                           "l'apprentissage et d'autres dispositifs : elles ne sont pas comparables au montant CPF "
                           "et ne lui sont pas additionnées."})
    f = "arbre/Solidarite-travail-et-sante_Travail-emploi-et-administration-des-minist-res-sociaux_103.json"
    if (SITE / f).exists():
        n = json.loads((SITE / f).read_text(encoding="utf-8"))
        liens.append({
            "vue": "arbre_etat", "fichier": f, "id": n["id"], "nom": n["nom"], "programme": "103", "md": n["md"],
            "millesime": n["millesime"],
            "lecture": "Programme 103 du budget de l'État, chef de file de France compétences : il porte les "
                       "crédits de l'État versés à France compétences, avec d'autres dépenses (alternance, "
                       "formation des demandeurs d'emploi). Montant du programme entier, jamais additionné au CPF."})
    return liens


def produire() -> dict:
    manquants = [s["fichier"] for s in SOURCES.values() if not (BRUT / s["fichier"]).exists()]
    if manquants:
        raise SystemExit(f"entrepôt incomplet (python pipeline/formation.py collecter) : {manquants}")
    date = date_sources("formation")
    cpf = produire_cpf(date)
    orga = produire_organismes(date, cpf["certifs"])
    elus = produire_elus(date)
    fiph = produire_fiphfp(date)
    annees = cpf["annees"]
    ecarts = []
    for a, (montant, dossiers) in RUF["valeurs"].items():
        if a in annees:
            ref, ici = _nombre_fr(montant), annees[a]["montant_eur"]
            ecarts.append({
                "annee": int(a), "source": "cdc_formations_engagees", "montant": ici,
                "autre_source": "france_competences_ruf_2025", "autre_montant": _r(ref), "autre_publie": montant,
                "ecart": _r(ici - ref), "ecart_pct": _pct(ici - ref, ref),
                "dossiers": annees[a]["dossiers"], "autre_dossiers": _r(_nombre_fr(dossiers)),
                "lecture_ecart": "Le jeu ouvert est une photographie à la date de collecte (des dossiers validés "
                                 "sont annulés ensuite) ; France compétences calcule un montant net à partir des "
                                 "comptes annuels de la Caisse des dépôts. Les deux chiffres sont publiés, aucun "
                                 "n'est retenu contre l'autre."})
    index = {
        "millesime": cpf["entete"]["millesime"] + f" ; élus {elus['annees'][0]} à {elus['annees'][-1]} ; FIPHFP "
                     f"{min(fiph['aides'])} à {max(fiph['aides'])}",
        "source": "Caisse des dépôts (opendata.caissedesdepots.fr) : Moncompteformation (formations engagées, "
                  "entrées et sorties, usagers), Moncompteelu, FIPHFP ; France compétences, rapport sur l'usage des "
                  f"fonds (édition 2025) ; Insee, répertoire Sirene ; {LICENCE}",
        "unite": "euros, dossiers, entrées en formation", "collecte_le": date, "date_sources": date,
        "avertissement": "Montants engagés (prix des formations des dossiers validés), pas montants payés. Trois "
                         "dispositifs gérés par la Caisse des dépôts, publiés séparément et jamais additionnés : "
                         "compte personnel de formation, formation des élus locaux, FIPHFP. Site citoyen non "
                         "officiel : les sources font foi.",
        "fichiers": {"cpf_mois": "formation/cpf_mois.json", "cpf_departements": "formation/cpf_departements.json",
                     "cpf_certifications": "formation/cpf_certifications.json",
                     "cpf_organismes": "formation/cpf_organismes.json", "cpf_usagers": "formation/cpf_usagers.json",
                     "elus": "formation/elus.json", "fiphfp": "formation/fiphfp.json"},
        "cpf": {
            "definition": "Compte personnel de formation : droits en euros acquis par chaque actif, mobilisés sur "
                          "Mon compte formation ; la Caisse des dépôts gère les comptes et paie les organismes.",
            "statuts": GROUPES, "retenus": list(RETENUS),
            "regle": "« dossiers » et « montant_eur » comptent les dossiers validés non annulés (réalisés, réalisés "
                     "en partie, en cours) ; les dossiers annulés ou rejetés sont publiés dans « par_statut ».",
            "financeurs": {k: lib for k, _, _, lib in FINANCEURS},
            "note_financeurs": "La somme des parts des financeurs peut différer du montant engagé de quelques euros "
                               "(arrondis de la source).",
            "annees": annees,
            "organismes": {"fichier": "formation/cpf_organismes.json", "nommes": orga["nommes"],
                           "agreges": orga["agreges"], "totaux": orga["totaux"], "estimation": "approché"},
        },
        "elus": {"fichier": "formation/elus.json", **elus},
        "fiphfp": {"fichier": "formation/fiphfp.json", "aides_totaux": fiph["aides"],
                   "conventions_totaux": fiph["conventions"]},
        "liens": _liens(),
        "ecarts": ecarts,
        "ecarts_source": {k: RUF[k] for k in ("document", "url", "champ", "non_compare")},
        "verification_documents": verifier_ruf(),
        "confidentialite": {
            "regle": "Aucune personne physique nommée. Organismes : personnes morales seulement (catégorie juridique "
                     "Sirene), les autres additionnés. Élus : agrégats sans nom ni commune, cellules de moins de "
                     f"{SEUIL_ELUS} dossiers regroupées. Usagers du CPF : agrégats par région, âge, sexe et situation "
                     "publiés par la source.",
            "organismes_agreges": orga["agreges"]},
        "limites": [
            "Le montant engagé n'est pas le montant payé : un dossier réalisé en partie est payé en partie.",
            "L'année en cours est incomplète (« complete » : false) et ses dossiers récents peuvent encore être "
            "annulés.",
            "Le montant par organisme n'est pas publié par la source ; l'estimation du fichier des organismes est "
            "approchée et sa méthode est écrite dans le fichier.",
            "Les rémunérations versées pendant les formations ne sont pas dans ces jeux.",
        ],
        "sources": {sid: {"jeu": s["dataset"], "page": page(s["dataset"]), "requete": s["params"].get("group_by")
                          or "export ligne à ligne", "licence": LICENCE} for sid, s in SOURCES.items()},
        "sources_inaccessibles": SOURCES_INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(SORTIE / "index.json", index)
    der = [a for a in annees if annees[a]["complete"]][-1]
    print(f"formation : CPF {der} {annees[der]['montant_eur'] / 1e9:.3f} Md€ engagés ({annees[der]['dossiers']} "
          f"dossiers), {orga['nommes']} organismes nommés, élus {elus['organismes_nommes']} organismes nommés, "
          f"{len(ecarts)} écarts publiés")
    return index




def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true", help="retélécharger les sources déjà présentes")
    ap.add_argument("--budget-siren", type=float, default=900, help="durée maximale de résolution des SIREN (s)")
    ap.add_argument("--sortie", type=Path, help="dossier de sortie (défaut : site/data/formation)")
    a = ap.parse_args(argv)
    if a.sortie:
        global SORTIE
        SORTIE = a.sortie
    if a.etape in ("collecter", "tout"):
        collecter(a.forcer, a.budget_siren)
    if a.etape in ("produire", "tout"):
        produire()


if __name__ == "__main__":
    main()
