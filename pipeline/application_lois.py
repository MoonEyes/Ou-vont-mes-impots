"""Application des lois : pour chaque loi promulguée depuis 2002, les mesures d'application prévues et publiées.

Source unique : « Données du baromètre de l'application des lois » (Assemblée nationale et LexImpact, data.gouv.fr,
Licence Ouverte 2.0, mise à jour quotidienne), construit sur les échéanciers de mise en application des lois publiés
par Légifrance (DILA). Deux fichiers CSV :
  - liste des lois : date de publication, titre, identifiants Légifrance, commission de l'Assemblée saisie au fond,
    législature, type de loi, nombre de mesures à appliquer et appliquées, taux d'application (calcul de LexImpact) ;
  - liste des mesures : numéro d'ordre dans l'échéancier, article, base légale, objet, observations de la DILA,
    identifiant du décret publié, date prévue, état (déduit par LexImpact des observations de la DILA), délai
    d'application en jours (calcul de LexImpact).

Ce qui est repris : les valeurs publiées, telles quelles, avec leur producteur. Le taux d'application et le délai par
mesure sont des calculs de LexImpact présents dans la source : ils sont repris et attribués à LexImpact, jamais
recalculés. Le site calcule seulement, avec la mention « calculé par le site » et la méthode écrite à côté :
  - par loi : délai minimal, médian et maximal des mesures appliquées (même loi, délais publiés par LexImpact) ;
  - par année de publication des lois : nombre de lois et somme des mesures prévues, appliquées, en attente et sans
    objet (même année, même périmètre : les lois publiées cette année-là).
Aucun taux par année, aucun classement des lois ni des ministères, aucun qualificatif. Une loi sans mesure à appliquer
n'a pas de taux (le baromètre y écrit 1, soit 100 % : non repris, null avec motif).

Lois de finances et de financement de la Sécurité sociale en priorité : catégorie lue dans le titre officiel (loi de
finances initiale, rectificative, de fin de gestion, loi spéciale, loi de règlement ou relative aux résultats de la
gestion, loi de financement de la sécurité sociale initiale ou rectificative, loi d'approbation des comptes de la
sécurité sociale, loi de programmation des finances publiques), liste dédiée lois_finances.json.

Confidentialité : les colonnes « Présidence » et « Gouvernement » (noms de personnes) et « Mots-clés » sont supprimées
à la lecture. L'objet, la base légale et les observations de chaque mesure sont des textes libres : publiés seulement
s'ils passent le filtre de noms de personnes du site (local.objet_publiable), sinon null avec motif. Les titres de lois
sont des intitulés officiels publiés au Journal officiel ; un titre comportant une civilité (M., Mme…) serait remplacé
par sa référence (numéro et date).

Commandes :
    python pipeline/application_lois.py collecter    (réseau : python collecte/collecte.py application_lois_barometre,
                                                       contrôle d'intégrité collecte/integrite.py)
    python pipeline/application_lois.py produire [--sortie DOSSIER]   (sans réseau)

Sorties (site/data/application_lois/, contrat docs/contrat_interface.md, schémas docs/schemas/application_lois_*) :
    index.json                 présentation, sources, définitions, comptes par année (calculés par le site), fichiers
    lois_finances.json         lois de finances et de financement de la Sécurité sociale, du plus récent au plus ancien
    lois/<annee>.json          lois publiées dans l'année, du plus récent au plus ancien
    mesures/<identifiant>.json mesures d'application d'une loi (lois ayant au moins une mesure dans l'échéancier)

Sorties reproductibles : dates lues dans le manifeste de collecte (pipeline/reproductible.py), ordres explicites.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local  # noqa: E402  (filtre de noms de personnes, écriture compacte bornée à 5 Mo)
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "application_lois"
MANIFESTE = ROOT / "data" / "lake" / "manifest.json"
SORTIE = ROOT / "site" / "data" / "application_lois"
ID_SOURCE = "application_lois_barometre"
JEU = "6825af1382d4b7afed51de59"
URL_JEU = f"https://www.data.gouv.fr/fr/datasets/{JEU}/"
LICENCE = "Licence Ouverte 2.0"
PRODUCTEUR = "Assemblée nationale et LexImpact, d’après les échéanciers de Légifrance (DILA)"
TITRE_JEU = "Données du baromètre de l’application des lois"
LEGIFRANCE = "https://www.legifrance.gouv.fr/jorf/id/"
DOSSIER_LEGIFRANCE = "https://www.legifrance.gouv.fr/dossierlegislatif/"
LONGUEUR_TEXTE = 4000

COL_LOIS = {
    "date": "Date de publication de la loi", "titre": "Titre de la loi", "id": "Identifiant Légifrance de la loi",
    "dossier": "Identifiant Légifrance du dossier législatif",
    "commission": "Libellé de la commission de l'Assemblée saisie au fond", "legislature": "Législature",
    "sans_echeancier": "Loi sans échéancier", "application_directe": "Loi d'application directe",
    "ratification_accords": "Loi autorisant la ratification d'accords internationaux",
    "habilitation": "Loi d'habilitation (ordonnances)", "ratification_ordonnances": "Loi de ratification (ordonnances)",
    "a_appliquer": "Nombre de mesures à appliquer", "appliquees": "Nombre de mesures appliquées",
    "taux": "Taux d'application des mesures",
}
COL_MESURES = {
    "loi": "Identifiant loi", "ordre": "N° ordre", "articles": "Articles", "base": "Base légale", "objet": "Objet",
    "observations": "Objectif initial de publication, observations", "decret": "Identifiant décret",
    "date_prevue": "Date prévue", "etat": "État", "delai": "Délai d'application (en jours)",
}
# Colonnes supprimées à la lecture : noms de personnes (présidence, gouvernement) et mots-clés (non utilisés).
COLONNES_SUPPRIMEES = ["Présidence", "Gouvernement", "Mots-clés"]
ETATS = ("appliqué", "en attente d'application", "sans objet")

# Catégories de lois financières, lues dans le titre officiel après « LOI [n° …] [du …] ». Ordre = priorité de lecture.
CATEGORIES = [
    ("lfss_rectificative", "loi de financement rectificative de la sécurité sociale",
     r"de financement rectificative de la s[ée]curit[ée] sociale"),
    ("lfss", "loi de financement de la sécurité sociale", r"de financement de la s[ée]curit[ée] sociale pour"),
    ("approbation_comptes_secu", "loi d’approbation des comptes de la sécurité sociale",
     r"d'approbation des comptes de la s[ée]curit[ée] sociale"),
    ("lf_rectificative", "loi de finances rectificative", r"de finances rectificative"),
    ("lf_fin_de_gestion", "loi de finances de fin de gestion", r"de finances de fin de gestion"),
    ("lf_initiale", "loi de finances (budget voté pour l’année)", r"de finances pour"),
    ("loi_speciale", "loi spéciale (article 45 de la loi organique relative aux lois de finances)",
     r"sp[ée]ciale pr[ée]vue par l'article 45"),
    ("reglement", "loi de règlement ou relative aux résultats de la gestion",
     r"(?:portant )?r[èe]glement (?:d[ée]finitif )?du budget|de r[èe]glement (?:du budget|des comptes)"
     r"|relative aux r[ée]sultats de la gestion"),
    ("programmation_finances_publiques", "loi de programmation des finances publiques",
     r"de programmation des finances publiques"),
]
TETE_TITRE = re.compile(r"^\s*loi\s+(?:n°\s*\S+\s+)?(?:du\s+\d{1,2}(?:er)?\s+\S+\s+\d{4}\s+)?", re.I)
CIVILITE = re.compile(r"\b(M\.|MM\.|Mme|Mlle|Monsieur|Madame|Mademoiselle)\s", re.I)
REFERENCE = re.compile(r"\bn°\s*\d{2,4}-\d+\s+du\s+\d{1,2}(?:er)?\s+\S+\s+\d{4}", re.I)

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "requetes": "data.gouv.fr (« application des lois », « échéancier », « décrets d'application ») ; dépôts GitHub et "
                "GitLab (« barometre application des lois », « leximpact application lois », « echeancier legifrance ») ; "
                "API Légifrance (PISTE)",
    "trouvailles": [
        {"nom": "Données du baromètre de l’application des lois (Assemblée nationale, LexImpact)", "url": URL_JEU,
         "verdict": "réutilisable tel quel", "licence": LICENCE, "mise_a_jour": "quotidienne (ressources du 2026-11-15)",
         "usage": "lu tel quel : lois, mesures, états, délais et taux publiés ; seuls les comptes par année et les "
                  "délais par loi sont calculés par le site"},
        {"nom": "Baromètre de l’application des lois (site de l’Assemblée nationale)",
         "url": "https://www.assemblee-nationale.fr/dyn/taux-application-lois/",
         "verdict": "inspiration seulement", "licence": "non précisée (site institutionnel)", "mise_a_jour": "2026-11",
         "usage": "définitions des états et du taux ; ses tableaux et filtres ne sont pas repris"},
        {"nom": "Échéanciers de mise en application des lois (Légifrance, DILA, API PISTE)",
         "url": "https://www.legifrance.gouv.fr/liste/dossierslegislatifs",
         "verdict": "à adapter", "licence": LICENCE, "mise_a_jour": "continue",
         "usage": "source primaire du baromètre ; non relue ici (API sous compte, observations en texte libre déjà "
                  "structurées par LexImpact)"},
        {"nom": "Dépôts publics de LexImpact (git.leximpact.dev)", "url": "https://git.leximpact.dev/leximpact",
         "verdict": "inspiration seulement", "licence": "AGPL-3.0 (dépôts consultés)", "mise_a_jour": "2026",
         "usage": "aucun code de baromètre publié repéré ; les fichiers du jeu data.gouv.fr suffisent"},
    ],
}


# --- Lecture -------------------------------------------------------------------------------------------------------


def propre(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def oui_non(v) -> bool | None:
    v = propre(v).lower()
    return True if v == "oui" else False if v == "non" else None


def entier(v) -> int | None:
    v = propre(v)
    return int(v) if re.fullmatch(r"-?\d+", v) else None


def flottant(v) -> float | None:
    v = propre(v).replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def date_iso(v) -> str | None:
    """« 24/10/2024 » ou « 2024-10-24 » -> « 2024-10-24 » ; autre forme : None."""
    v = propre(v)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None


def categorie(titre: str) -> tuple[str, str] | None:
    """(identifiant, libellé) de la catégorie financière lue dans le titre officiel, sinon None."""
    corps = TETE_TITRE.sub("", propre(titre)).replace("’", "'")
    if re.match(r"organique\b", corps, re.I):
        return None
    for cid, lib, motif in CATEGORIES:
        if re.match(motif, corps, re.I):
            return cid, lib
    return None


def titre_publiable(titre: str) -> str:
    """Intitulé officiel ; s'il comporte une civilité, sa seule référence (« Loi n° … du … »)."""
    t = propre(titre)
    if not CIVILITE.search(t):
        return t
    m = REFERENCE.search(t)
    return f"Loi {m.group(0)}" if m else "Loi (intitulé non repris : il comporte un nom de personne)"


def texte_publiable(v, prenoms: set) -> tuple[str | None, str | None]:
    """(texte, motif) : texte libre publié s'il passe le filtre de noms de personnes, sinon null et motif."""
    s = propre(v)
    if not s:
        return None, None
    t = local.objet_publiable(s, prenoms, LONGUEUR_TEXTE)
    return (t, None) if t else (None, "texte non repris : le filtre de noms de personnes du site l’a retenu par prudence")


def manifeste() -> dict:
    try:
        return json.loads(MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fichiers_source() -> dict:
    """{'lois'|'mesures': {'chemin', 'url', 'ressource_modifiee_le'}} d'après le manifeste de collecte."""
    out = {}
    for f in (manifeste().get(ID_SOURCE) or {}).get("fichiers", []):
        p = ROOT / f["chemin"]
        cols = f.get("colonnes") or []
        cle = "lois" if COL_LOIS["date"] in cols else "mesures" if COL_MESURES["ordre"] in cols else None
        if cle and p.exists():
            out[cle] = {"chemin": p, "url": f.get("url"),
                        "ressource_modifiee_le": str(f.get("signature") or "")[:10] or None}
    if len(out) < 2:  # entrepôt sans manifeste : fichiers présents, reconnus par leur en-tête
        for p in sorted((LAKE / ID_SOURCE).glob("*.csv")):
            entete = p.open(encoding="utf-8-sig").readline()
            cle = "lois" if COL_LOIS["date"] in entete else "mesures" if COL_MESURES["ordre"] in entete else None
            if cle and cle not in out:
                out[cle] = {"chemin": p, "url": None, "ressource_modifiee_le": None}
    if len(out) < 2:
        raise SystemExit("application_lois : fichiers du baromètre absents (python pipeline/application_lois.py collecter)")
    return out


def lire_csv(chemin: Path, colonnes: dict) -> list[dict]:
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        lecteur = csv.DictReader(f, delimiter=";")
        manquantes = [c for c in colonnes.values() if c not in (lecteur.fieldnames or [])]
        if manquantes:
            raise SystemExit(f"{chemin.name} : colonnes absentes {manquantes}")
        out = []
        for r in lecteur:
            for c in COLONNES_SUPPRIMEES:
                r.pop(c, None)
            out.append({k: r.get(c) for k, c in colonnes.items()})
    return out


# --- Construction ----------------------------------------------------------------------------------------------------


def mesure(r: dict, prenoms: set) -> dict:
    objet, m_objet = texte_publiable(r["objet"], prenoms)
    obs, m_obs = texte_publiable(r["observations"], prenoms)
    base, m_base = texte_publiable(r["base"], prenoms)
    decret = propre(r["decret"]) or None
    etat = propre(r["etat"]) or None
    out = {
        "numero": entier(r["ordre"]),
        "articles": propre(r["articles"]) or None,
        "base_legale": base,
        "objet": objet,
        "observations": obs,
        "etat": etat,
        "date_prevue": date_iso(r["date_prevue"]),
        "decret": decret,
        "decret_url": LEGIFRANCE + decret if decret and decret.startswith("JORFTEXT") else None,
        "delai_jours": entier(r["delai"]),
    }
    motifs = {k: v for k, v in (("objet", m_objet), ("observations", m_obs), ("base_legale", m_base)) if v}
    if motifs:
        out["textes_non_repris"] = motifs
    return out


def delais(mesures: list[dict]) -> dict | None:
    """Délai minimal, médian et maximal des mesures appliquées dont LexImpact publie le délai (calculé par le site)."""
    v = sorted(m["delai_jours"] for m in mesures if m["etat"] == "appliqué" and m["delai_jours"] is not None)
    if not v:
        return None
    return {"mesures": len(v), "minimum_jours": v[0], "mediane_jours": round(float(statistics.median(v)), 1),
            "maximum_jours": v[-1], "calcule_par_le_site": True,
            "methode": "délais publiés par LexImpact pour les mesures appliquées de cette loi (jours entre la "
                       "publication de la loi et celle du texte d’application) : plus petit, médian et plus grand"}


def loi(r: dict, ms: list[dict]) -> dict:
    lid = propre(r["id"])
    a_appliquer, appliquees = entier(r["a_appliquer"]), entier(r["appliquees"])
    etats = Counter(m["etat"] for m in ms)
    cat = categorie(r["titre"])
    taux = flottant(r["taux"])
    sans_mesure = not a_appliquer
    dossier = propre(r["dossier"]) or None
    out = {
        "id": lid,
        "titre": titre_publiable(r["titre"]),
        "date_publication": date_iso(r["date"]),
        "annee": int(date_iso(r["date"])[:4]),
        "legislature": entier(r["legislature"]),
        "categorie": cat[0] if cat else None,
        "categorie_libelle": cat[1] if cat else None,
        "commission_saisie_au_fond": propre(r["commission"]) or None,
        "application_directe": oui_non(r["application_directe"]),
        "sans_echeancier": oui_non(r["sans_echeancier"]),
        "ratification_accords": oui_non(r["ratification_accords"]),
        "habilitation_ordonnances": oui_non(r["habilitation"]),
        "ratification_ordonnances": oui_non(r["ratification_ordonnances"]),
        "mesures_a_appliquer": a_appliquer,
        "mesures_appliquees": appliquees,
        "mesures_en_attente": etats.get("en attente d'application", 0),
        "mesures_sans_objet": etats.get("sans objet", 0),
        "mesures_dans_l_echeancier": len(ms),
        "taux_application_publie": None if sans_mesure else taux,
        "taux_note": ("aucune mesure à appliquer : le baromètre écrit 1 (100 %), valeur non reprise"
                      if sans_mesure else "taux calculé et publié par LexImpact : mesures appliquées divisées par "
                                          "mesures à appliquer (les mesures « sans objet » n’y entrent pas)"),
        "comptes_coherents": (a_appliquer == etats.get("appliqué", 0) + etats.get("en attente d'application", 0)
                              and appliquees == etats.get("appliqué", 0)),
        "delais": delais(ms),
        "url_legifrance": LEGIFRANCE + lid,
        "url_dossier_legislatif": DOSSIER_LEGIFRANCE + dossier if dossier and dossier.startswith("JORFDOLE") else None,
        "fichier_mesures": f"application_lois/mesures/{lid}.json" if ms else None,
    }
    return out


def entete(src: dict, collecte_le: str, millesime: str) -> dict:
    return {
        "millesime": millesime,
        "source": f"{PRODUCTEUR}, « {TITRE_JEU} », data.gouv.fr ({URL_JEU}), {LICENCE}, ressources du "
                  f"{src['ressource_modifiee_le'] or 'non précisé'}",
        "unite": "nombre de mesures ; délais en jours ; taux en proportion (0 à 1) tel que publié",
        "collecte_le": collecte_le,
    }


ORDRE_LOIS = {"regle": "Lois de la plus récente à la plus ancienne (date de publication au Journal officiel), puis par "
                       "identifiant Légifrance. Aucun classement par taux ni par délai.",
              "cles": ["-date_publication", "id"]}
AVERTISSEMENT = ("Le baromètre suit les mesures réglementaires (décrets, arrêtés) que chaque loi renvoie à un texte "
                 "d’application, d’après l’échéancier publié par Légifrance. Une loi d’application directe n’attend "
                 "aucune mesure. L’état de chaque mesure est déduit par LexImpact des observations de la DILA ; le "
                 "délai et le taux sont des calculs de LexImpact, repris tels quels. Une mesure « sans objet » n’a "
                 "plus besoin de texte d’application.")
DEFINITIONS = {
    "mesures_a_appliquer": "mesures de l’échéancier qui attendent ou ont reçu un texte d’application (appliquées et "
                           "en attente), nombre publié par le baromètre",
    "mesures_appliquees": "mesures dont le texte d’application est publié, nombre publié par le baromètre",
    "mesures_en_attente": "mesures à l’état « en attente d’application » dans la liste des mesures",
    "mesures_sans_objet": "mesures à l’état « sans objet » : plus aucun texte d’application n’est nécessaire",
    "taux_application_publie": "taux publié par le baromètre (calcul de LexImpact), en proportion",
    "delai_jours": "délai d’application publié par LexImpact pour une mesure appliquée, en jours",
    "date_prevue": "date de publication prévue du texte d’application, quand l’échéancier la donne",
    "application_directe": "loi qui ne renvoie à aucun texte d’application (mention du baromètre)",
    "sans_echeancier": "loi pour laquelle Légifrance ne publie pas d’échéancier (mention du baromètre)",
    "categorie": "catégorie de loi financière lue dans le titre officiel (null pour les autres lois)",
}


def produire(sortie: Path = SORTIE) -> dict:
    src = fichiers_source()
    prenoms = local.prenoms()
    collecte_le = date_sources("application_lois")
    lois_brutes = lire_csv(src["lois"]["chemin"], COL_LOIS)
    mesures_brutes = lire_csv(src["mesures"]["chemin"], COL_MESURES)

    par_loi: dict[str, list[dict]] = defaultdict(list)
    for r in mesures_brutes:
        par_loi[propre(r["loi"])].append(mesure(r, prenoms))
    for ms in par_loi.values():
        ms.sort(key=lambda m: (m["numero"] is None, m["numero"] or 0))
    ids = [propre(r["id"]) for r in lois_brutes]
    if len(set(ids)) != len(ids):
        raise SystemExit("application_lois : identifiant de loi en double dans la liste des lois")
    orphelines = sorted(set(par_loi) - set(ids))

    lois = [loi(r, par_loi.get(propre(r["id"]), [])) for r in lois_brutes]
    lois.sort(key=lambda x: x["id"])
    lois.sort(key=lambda x: x["date_publication"], reverse=True)
    premiere = min(x["date_publication"] for x in lois)
    derniere = max(x["date_publication"] for x in lois)
    millesime = (f"Lois publiées du {premiere} au {derniere}, baromètre au "
                 f"{src['lois']['ressource_modifiee_le'] or 'non précisé'}")
    tete = entete(src["lois"], collecte_le, millesime)

    for d in ("lois", "mesures"):
        shutil.rmtree(sortie / d, ignore_errors=True)
    sortie.mkdir(parents=True, exist_ok=True)

    # mesures/<id>.json
    for x in lois:
        ms = par_loi.get(x["id"])
        if not ms:
            continue
        local.dump(sortie / "mesures" / f"{x['id']}.json", {
            **tete, "loi": {k: x[k] for k in ("id", "titre", "date_publication", "categorie", "categorie_libelle",
                                               "mesures_a_appliquer", "mesures_appliquees", "taux_application_publie",
                                               "taux_note", "delais", "url_legifrance", "url_dossier_legislatif")},
            "ordre": {"regle": "Mesures dans l’ordre de l’échéancier (numéro d’ordre publié).", "cles": ["numero"]},
            "definitions": {k: DEFINITIONS[k] for k in ("delai_jours", "date_prevue")},
            "etats_publies": list(ETATS),
            "mesures": ms,
        })

    # lois/<annee>.json
    par_annee: dict[int, list[dict]] = defaultdict(list)
    for x in lois:
        par_annee[x["annee"]].append(x)
    annees = []
    for a in sorted(par_annee, reverse=True):
        lx = par_annee[a]
        local.dump(sortie / "lois" / f"{a}.json", {**tete, "annee": a, "ordre": ORDRE_LOIS,
                                                    "avertissement": AVERTISSEMENT, "lois": lx})
        annees.append({
            "annee": a, "fichier": f"application_lois/lois/{a}.json", "lois": len(lx),
            "lois_application_directe": sum(1 for x in lx if x["application_directe"]),
            "lois_sans_echeancier": sum(1 for x in lx if x["sans_echeancier"]),
            "lois_avec_mesures": sum(1 for x in lx if x["mesures_a_appliquer"] or x["mesures_sans_objet"]),
            "mesures_a_appliquer": sum(x["mesures_a_appliquer"] or 0 for x in lx),
            "mesures_appliquees": sum(x["mesures_appliquees"] or 0 for x in lx),
            "mesures_en_attente": sum(x["mesures_en_attente"] for x in lx),
            "mesures_sans_objet": sum(x["mesures_sans_objet"] for x in lx),
        })

    # lois_finances.json
    fin = [x for x in lois if x["categorie"]]
    cats = Counter(x["categorie"] for x in fin)
    local.dump(sortie / "lois_finances.json", {
        **tete, "ordre": ORDRE_LOIS, "avertissement": AVERTISSEMENT,
        "methode": "Catégorie lue dans le titre officiel de la loi, après « LOI n° … du … » : « de finances pour », "
                   "« de finances rectificative », « de finances de fin de gestion », « spéciale prévue par l'article "
                   "45 », « portant règlement du budget », « de règlement », « relative aux résultats de la gestion », "
                   "« de financement de la sécurité sociale pour », « de financement rectificative de la sécurité "
                   "sociale », « d'approbation des comptes de la sécurité sociale », « de programmation des finances "
                   "publiques ». Les lois organiques (règles des lois de finances elles-mêmes) n’en font pas partie.",
        "categories": [{"categorie": cid, "libelle": lib, "lois": cats.get(cid, 0)} for cid, lib, _ in CATEGORIES],
        "lois": fin,
    })

    comptes = {
        "lois": len(lois), "mesures": len(mesures_brutes), "lois_avec_fichier_mesures": sum(1 for x in lois if x["fichier_mesures"]),
        "lois_finances": len(fin),
        "etats": {e: sum(1 for ms in par_loi.values() for m in ms if m["etat"] == e) for e in ETATS},
        "textes_non_repris": sum(len(m.get("textes_non_repris", {})) for ms in par_loi.values() for m in ms),
        "lois_comptes_incoherents": sum(1 for x in lois if not x["comptes_coherents"]),
        "mesures_sans_loi_connue": sum(len(par_loi[k]) for k in orphelines),
        "titres_remplaces": sum(1 for r in lois_brutes if CIVILITE.search(propre(r["titre"]))),
    }
    idx = {
        **tete,
        "avertissement": AVERTISSEMENT,
        "definitions": DEFINITIONS,
        "sources": [{"id": ID_SOURCE, "titre": TITRE_JEU, "producteur": PRODUCTEUR, "licence": LICENCE,
                     "url": URL_JEU, "fichier": k, "url_fichier": v["url"],
                     "ressource_modifiee_le": v["ressource_modifiee_le"], "collecte_le": collecte_le}
                    for k, v in sorted(src.items())],
        "confidentialite": "Colonnes « Présidence » et « Gouvernement » (noms de personnes) supprimées à la lecture. "
                           "Objet, base légale et observations de chaque mesure publiés seulement s’ils passent le "
                           "filtre de noms de personnes du site ; sinon null avec motif.",
        "comptes": comptes,
        "par_annee": {
            "calcule_par_le_site": True,
            "methode": "pour les lois publiées une même année : nombre de lois, puis somme des nombres de mesures "
                       "publiés loi par loi par le baromètre (à appliquer, appliquées) et nombre de mesures de la "
                       "liste des mesures à l’état « en attente d’application » ou « sans objet ». Aucun taux par "
                       "année n’est calculé.",
            "annees": annees,
        },
        "lois_finances": {"fichier": "application_lois/lois_finances.json", "lois": len(fin),
                          "categories": [{"categorie": cid, "libelle": lib, "lois": cats.get(cid, 0)}
                                         for cid, lib, _ in CATEGORIES]},
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    local.dump(sortie / "index.json", idx)
    return idx


def collecter() -> int:
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), ID_SOURCE], cwd=ROOT)


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
