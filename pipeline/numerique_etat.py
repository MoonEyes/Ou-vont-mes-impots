"""Numérique de l'État : grands projets numériques (panorama DINUM) et fonds de transformation numérique.

Cinq jeux publics (data.gouv.fr, Licence Ouverte 2.0), sans jugement sur les projets :
  - panorama des grands projets numériques de l'État (DINUM), 22 éditions de novembre 2016 à décembre 2025 :
    pour chaque projet, le coût estimé publié, la durée prévisionnelle publiée, la date de début, la phase et les
    programmes LOLF cités, édition par édition (« évolution du coût estimé publié ») ;
  - France Relance, mise à niveau numérique de l'État et des territoires (enveloppe MTFP) : lauréats par dispositif,
    ministère, année de décision et département ;
  - France Relance, guichets de la DITP (fonds déconcentré ITN7 par département, appels FITN8) ;
  - guichets numériques du Fonds pour la transformation de l'action publique (FTAP) ;
  - Fonds d'accélération des startups d'État et de territoires (FAST).

Rapprochement des noms de projet d'une édition à l'autre (règles publiées dans panorama/projets.json) :
  R1  même nom une fois normalisé (majuscules, accents, ponctuation) ;
  R2  changement de nom déclaré dans RENOMMAGES, appliqué seulement si les critères sont vérifiés dans les données :
      aucune édition commune, même date de début à la jonction et, quand le nom ajoute ou retire une mention de
      version, de cycle, de phase ou de périmètre, même coût estimé publié à la jonction (à 0,1 M€ près) ;
  un changement déclaré dont un critère échoue est publié dans `non_rapproches` avec la raison, jamais fusionné.

Confidentialité : porteurs personnes morales seulement (ministères, directions, établissements, collectivités) ;
les jeux ne publient aucun SIREN, un porteur est donc nommé seulement s'il passe le filtre de noms de personnes de
pipeline/local.py (sinon null, compté dans `porteurs_non_publies`). Colonnes de description longue, de résumé et de
liens supprimées à la lecture (certaines contiennent des courriels ou des téléphones) ; titres passés par
local.objet_publiable. Un montant absent à la source est null, jamais 0.

Commandes :
    python collecte/collecte.py numerique_panorama_projets numerique_france_relance_mtfp numerique_ftap_guichets \
        numerique_fast numerique_ditp_guichets          (réseau ; sources déclarées dans collecte/catalogue.json)
    python pipeline/numerique_etat.py produire [--sortie DOSSIER]   (sans réseau)

Sorties (site/data/numerique_etat/, contrat docs/contrat_interface.md, schémas docs/schemas/numerique_etat_*.json) :
    index.json, annees.json,
    panorama/projets.json, panorama/editions.json, panorama/ministeres.json, panorama/programmes.json,
    fonds/france_relance.json, fonds/france_relance/<dep>.json, fonds/ditp.json, fonds/ditp_itn7/<dep>.json,
    fonds/ftap.json, fonds/fast.json

Sorties reproductibles : dates lues dans le manifeste de collecte (pipeline/reproductible.py), ordres explicites.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import shutil
import sys
import unicodedata
import warnings
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local  # noqa: E402  (filtre de noms de personnes, écriture compacte bornée à 5 Mo)
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "numerique_etat"
MANIFESTE = ROOT / "data" / "lake" / "manifest.json"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "numerique_etat"
DATAGOUV = "https://www.data.gouv.fr/fr/datasets/"

SOURCES = {
    "panorama": {"id": "numerique_panorama_projets", "jeu": "582e1e2888ee386b7ac65bb4",
                 "titre": "Panorama des grands projets numériques de l’État",
                 "producteur": "Direction interministérielle du numérique (DINUM)"},
    "france_relance": {"id": "numerique_france_relance_mtfp", "jeu": "604b41376268c26e7f983c50",
                       "titre": "France Relance, lauréats du volet « Mise à niveau numérique de l’État et des "
                                "territoires » (enveloppe MTFP), édition d'octobre 2022",
                       "producteur": "France Relance (ministère de la Transformation et de la Fonction publiques)"},
    "ditp": {"id": "numerique_ditp_guichets", "jeu": "63ca4ba359801bcd8e64bd98",
             "titre": "France Relance, lauréats des guichets de la DITP (ITN7 déconcentré, FITN8)",
             "producteur": "Direction interministérielle de la transformation publique (DITP)"},
    "ftap": {"id": "numerique_ftap_guichets", "jeu": "67190c3a47790f31885a4486",
             "titre": "Lauréats des guichets numériques du Fonds pour la transformation de l'action publique (FTAP), "
                      "conventions signées au 23/10/2024",
             "producteur": "Direction interministérielle du numérique (DINUM)"},
    "fast": {"id": "numerique_fast", "jeu": "67051ed2df66a794ed0f016a",
             "titre": "Fonds d'accélération des startups d'État et de territoires (FAST), tableau récapitulatif",
             "producteur": "beta.gouv.fr (DINUM)"},
}
LICENCE = "Licence Ouverte 2.0"

# Dispositif -> action de l'arbre État (site/data/arbre, exécution 2024) dont l'intitulé désigne le dispositif.
# Vérifié à chaque production : l'action doit exister avec cet intitulé (sinon la production échoue).
ACTIONS_ARBRE = {
    "france_relance": ("363", "363-04", "Mise à niveau numérique de l'État, des territoires et des entreprises"),
    "ditp": ("363", "363-04", "Mise à niveau numérique de l'État, des territoires et des entreprises"),
    "ftap": ("349", "349-01", "Fonds pour la transformation de l'action publique"),
    "fast": ("352", "352-01", "Fonds pour l'accélération du financement des start-up d'État"),
}

# Changements de nom déclarés (ancien nom, nouveau nom, type). « sigle » : même désignation écrite autrement (sigle,
# libellé développé, typographie) ; « version » : le nom ajoute ou retire une mention de version, de cycle, de phase,
# d'étape ou de périmètre. Les critères sont vérifiés dans les données (voir rapprocher) ; un échec = non rapproché.
RENOMMAGES = [
    ("3PA-S", "3-PAS-S_DAE", "sigle"),
    ("ARCHIPEL-NG", "ARCHIPEL", "version"),
    ("CASSIOPEE", "CASSIOPEE V2", "version"),
    ("Compte Personnel d'Activité", "CPA", "sigle"),
    ("Concentrateur DSN", "DSN FPE (concentrateur)", "sigle"),
    ("Déploiement de l'application RenoiRH et adaptations liées", "Dépl. PESE, Winpaie, RenoiRH + évol.SI connexes",
     "version"),
    ("Dépl. PESE, Winpaie, RenoiRH + évol.SI connexes", "Déploiement RenoiRH", "version"),
    ("Elire – élaboration des listes à partir du répertoire électoral", "ELIRE", "sigle"),
    ("Enrichissement du SI Harmonie et fusion des métiers RH", "HARMONIE", "version"),
    ("Espace numérique en Santé (ENS)", "Mon Espace Santé", "version"),
    ("FRANCE CONNECT", "FRANCECONNECT PHASE II", "version"),
    ("FRANCECONNECT PHASE II", "FRANCE CONNECT PHASE II", "sigle"),
    ("GENESIS", "GENESIS V2", "version"),
    ("Généralisation - Equipement numérique mobile du primo-intervenant NEOGEND/NEOPOL", "MOBILITE", "version"),
    ("Guichet entreprise", "Guichet_Entreprise_DGE", "sigle"),
    ("KIOSQUES", "KIOSQUES - PFSF", "version"),
    ("LSU du CP à la 3EME", "LSUN", "sigle"),
    ("MCIC²", "MCIC-2", "sigle"),
    ("MIGRATION SAP CHORUS", "Chorus – Projet S_4HANA", "version"),
    ("PIB/MISTRAL", "MISTR@L", "sigle"),
    ("MISTR@L", "Mistral", "sigle"),
    ("Modernisation de l'INPT (projets FH et IP)", "INPT", "version"),
    ("Montée de version du SIRH", "MONTEE DE VERSION SIRH", "sigle"),
    ("NEXSIS", "NexSIS Version 1", "version"),
    ("NSTI / DELT@ T", "NSTI", "sigle"),
    ("Paysage : Modernisation iso fonctionnelle de PAY", "PAYSAGE", "sigle"),
    ("PNIJ", "PNIJ NG (ANTENJ)", "version"),
    ("SYSTEME DE NOUVELLE GENERATION DES TECHNIQUES D'ENQUETES NUMERIQUES JUDICIAIRES", "PNIJ NG (ANTENJ)", "sigle"),
    ("PORTALIS", "PORTALIS 2", "version"),
    ("PPNG Plan Préfectures Nouvelle Génération", "PPNG", "sigle"),
    ("PROJET SOLDE GENDARMERIE", "SOLDE GENDARMERIE", "sigle"),
    ("Regroupement des centres informatiques", "Regroup. centres info.", "sigle"),
    ("RESYTAL CYCLE 1", "RESYTAL", "version"),
    ("Réseau Interministériel de l'Etat", "RIE", "sigle"),
    ("ROC", "ROC_PR35", "version"),
    ("SÉGUR-FONTENOY", "SEGUR", "version"),
    ("SGIN", "SGIN - France Identité Numérique", "version"),
    ("SI Paie des EPLE (OPERA)", "OPER@", "sigle"),
    ("SI-Samu (étape \"Construction & Pilote\")", "SI SAMU", "version"),
    ("SIRENA Cycle 1", "SIRENA", "version"),
    ("SIRH DIALOGUE 2", "DIALOGUE 2", "sigle"),
    ("SIRHIUS V1", "SIRHIUS", "version"),
    ("ANEF", "ANEF DEC AGDREF", "version"),
]
TOLERANCE_COUT_MEUR = 0.1

MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
MOIS_NOMS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "requetes": "réutilisations déclarées sur data.gouv.fr pour les cinq jeux ; recherche de dépôts GitHub "
                "(« panorama grands projets numériques État », « panorama grands projets SI »)",
    "trouvailles": [
        {"nom": "Classeurs officiels du panorama (data.gouv.fr, 22 éditions)", "url": DATAGOUV + SOURCES["panorama"]["jeu"],
         "verdict": "réutilisable tel quel", "licence": LICENCE, "mise_a_jour": "2026-02-03",
         "usage": "lus tels quels ; aucun fichier consolidé entre éditions n'est publié"},
        {"nom": "DISIC/panorama (dépôt GitHub de la DINUM)", "url": "https://github.com/DISIC/panorama",
         "verdict": "inspiration seulement", "licence": "MIT", "mise_a_jour": "2026-02-03",
         "usage": "dépôt de publication du panorama ; pas de code de rapprochement entre éditions repéré"},
        {"nom": "Carnets Observable « France Relance, mise à niveau numérique de l'État » (réutilisations data.gouv.fr)",
         "url": "https://observablehq.com/@pachevalier/francerelance-mise-a-niveau-numerique-de-letat-analyse-des",
         "verdict": "inspiration seulement", "licence": "non précisée", "mise_a_jour": "2022-04",
         "usage": "analyse d'une édition antérieure ; les agrégats sont recalculés ici sur l'édition d'octobre 2022"},
        {"nom": "Article de réutilisation sur neuf ans de panorama (réutilisation déclarée sur data.gouv.fr)",
         "url": "https://digital.one/ressources/gouvernance-projet",
         "verdict": "inspiration seulement", "licence": "non précisée", "mise_a_jour": "2026-08-29",
         "usage": "analyse éditoriale, non reprise : seules les valeurs publiées par la DINUM sont données ici"},
    ],
}


# --- Utilitaires ---------------------------------------------------------------------------------------------------


def propre(v) -> str:
    s = local.propre(v).replace("_x000D_", " ")
    return re.sub(r"\s+", " ", s).strip()


def sans_accent(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def cle_nom(nom: str) -> str:
    """Règle R1 : majuscules, sans accents, ponctuation et espaces multiples retirés (« ² » devient « 2 »)."""
    return re.sub(r"[^A-Z0-9@]+", " ", sans_accent(propre(nom)).upper()).strip()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sans_accent(s).lower().replace("@", "a")).strip("-") or "projet"


def arrondi(x, n=3):
    return None if x is None else round(float(x) + 0.0, n)


def feuille(chemin: Path, index: int = 0, nom: str | None = None) -> list[tuple]:
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
        ws = wb[nom] if nom else wb.worksheets[index]
        lignes = [r for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]
        wb.close()
    return lignes


def manifeste() -> dict:
    try:
        return json.loads(MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fichiers_source(sid: str) -> list[dict]:
    """Fichiers collectés d'une source : chemin local, URL publique, date de la ressource (manifeste de collecte)."""
    e = manifeste().get(sid) or {}
    out = []
    for f in e.get("fichiers", []):
        p = ROOT / f["chemin"]
        if p.exists():
            out.append({"chemin": p, "url": f.get("url"), "ressource_modifiee_le": str(f.get("signature") or "")[:10] or None})
    if not out:  # entrepôt sans manifeste : fichiers présents, URL inconnue
        out = [{"chemin": p, "url": None, "ressource_modifiee_le": None} for p in sorted((LAKE / sid).glob("*"))]
    return sorted(out, key=lambda x: x["chemin"].name)


def nombre(v) -> tuple[float | None, str | None]:
    """(valeur, mention). Mention = raison de l'absence telle que publiée : jamais 0 à la place d'une absence."""
    if isinstance(v, bool):
        return None, "non publié"
    if isinstance(v, (int, float)):
        return float(v), None
    s = propre(v)
    if not s:
        return None, "non publié"
    t = s.replace(" ", "").replace(" ", "").replace("€", "").replace(",", ".")
    if re.fullmatch(r"-?\d+(\.\d+)?", t):
        return float(t), None
    if re.search(r"cadrage", s, re.I):
        return None, "en cadrage"
    if re.fullmatch(r"n\.?a\.?|non communiqu.*|nc", s, re.I):
        return None, "non communiqué"
    return None, "non publié"


def mois_debut(v) -> str | None:
    """Date de début ramenée au mois (AAAA-MM) ; les éditions l'écrivent sous cinq formes."""
    if isinstance(v, (dt.datetime, dt.date)):
        return f"{v.year:04d}-{v.month:02d}"
    s = propre(v)
    m = re.match(r"^(\d{4})-(\d{2})-\d{2}", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"^\d{2}/(\d{2})/(\d{4})$", s)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    m = re.match(r"^([a-zéûè]+)\.?\s+(\d{2}|\d{4})$", s.lower())
    if m and sans_accent(m.group(1)) in MOIS:
        an = int(m.group(2))
        an = an if an > 99 else 2000 + an
        return f"{an:04d}-{MOIS[sans_accent(m.group(1))]:02d}"
    return None


CONTACT_RE = re.compile(r"@|https?://|www\.|\b0\d(?:[ .]?\d{2}){4}\b", re.I)
INSTITUTION_RE = re.compile(
    r"^(commune|ville|mairie|cc|ca|cu|communaut|metropole|métropole|syndicat|synd|si|sivom|sivu|sivos|sictom|smictom|"
    r"departement|département|conseil|region|région|prefecture|préfecture|minist|direction|service|agence|centre|"
    r"etablissement|établissement|gip|pole|pôle|collectivit|grand|pays|pnr|parc|institut|universit|ecole|école|caisse|"
    r"office|ccas|cias|sdis|eurometropole|agglomeration|agglomération|le grand|toulouse|bordeaux|nantes|rennes|"
    r"brest|rouen|dijon|tours|orleans|orléans|clermont|saint|sainte)\b", re.I)


def texte(v, prenoms: set, longueur: int = 200) -> str | None:
    """Texte libre court : publié seulement sans nom de personne possible ni coordonnée (courriel, téléphone, lien)."""
    s = propre(v)
    if not s or CONTACT_RE.search(s):
        return None
    return local.objet_publiable(s, prenoms, longueur)


def porteur(v, prenoms: set) -> str | None:
    """Nom du porteur (administration, établissement, collectivité). Le code postal et la commune du siège entre
    crochets sont retirés. Null si civilité, coordonnée, ou nom de personne possible hors forme institutionnelle."""
    s = re.sub(r"\s*\[[^\]]*\]\s*$", "", propre(v)).strip()
    if not s or CONTACT_RE.search(s) or local.CIVILITE_RE.search(s + " "):
        return None
    if local.contient_nom_de_personne(s, prenoms) and not INSTITUTION_RE.match(s):
        return None
    return s[:160]


def ecrire(chemin: Path, doc: dict) -> None:
    local.dump(chemin, doc)


# --- Arbre État ----------------------------------------------------------------------------------------------------


def programmes_arbre() -> dict:
    """Programmes de l'arbre État (exécution 2024) : numéro -> noeud, nom, fichier, actions."""
    out = {}
    for f in sorted((SITE / "arbre").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("niveau") != "programme":
            continue
        num = d["id"].rsplit("/", 1)[-1]
        out[num] = {"noeud": d["id"], "nom": d["nom"], "fichier": f"arbre/{f.name}", "md": d.get("md"),
                    "actions": {e["id"].rsplit("/", 1)[-1]: e["nom"] for e in d.get("enfants", [])}}
    return out


def lien_action(arbre: dict, cle: str) -> dict:
    prog, action, debut_intitule = ACTIONS_ARBRE[cle]
    p = arbre.get(prog)
    if not p or not cle_nom(p["actions"].get(action, "")).startswith(cle_nom(debut_intitule)):
        raise SystemExit(f"arbre État : action {action} « {debut_intitule} » introuvable (lien {cle} à revoir)")
    return {"programme": prog, "noeud": p["noeud"], "nom_programme": p["nom"], "fichier": p["fichier"],
            "action": action, "nom_action": p["actions"][action],
            "rattachement": "intitulé de l'action de l'arbre État (le jeu ne publie pas de numéro de programme)"
            if cle != "ditp" else "programme 363 publié dans l'en-tête du jeu (FITN8) ; action d'après son intitulé"}


NUM_PREFIXE_RE = re.compile(
    r"(?:\bP\s?|\bprog\.\s?|\bprogrammes?\s+(?:nationa(?:l|ux)\s+)?(?:n°\s*)?)(\d{3}(?:\s*(?:/|,|et|&|-|à)\s*P?\s?\d{3})*)", re.I)


def programmes_cites(financement: str, arbre: dict, par_nom: dict) -> list[dict]:
    """Programmes LOLF cités dans « Financement [programme(s)] » : numéros publiés, sinon intitulé identique à un
    programme de l'arbre État. Aucun numéro n'est déduit autrement."""
    s = propre(financement)
    if not s:
        return []
    nums: list[str] = []
    if re.fullmatch(r"[\d\s/,;&-]+|(?:\d{3}\s*(?:/|,|et|-)\s*)*\d{3}", s):
        nums = re.findall(r"(?<!\d)(\d{3})(?!\d)", s)
    else:
        for m in NUM_PREFIXE_RE.finditer(s):
            nums += re.findall(r"\d{3}", m.group(1))
        nums += re.findall(r"\(P?(\d{3})\)", s)
    out = [{"programme": n, "rattachement": "numéro publié"} for n in dict.fromkeys(nums)]
    if not out:
        for morceau in re.split(r"\s+/\s+|;|\n", re.sub(r"\([^)]*\)", "", s)):
            n = par_nom.get(cle_nom(morceau))
            if n and n not in [o["programme"] for o in out]:
                out.append({"programme": n, "rattachement": "intitulé identique à un programme de l'arbre État"})
    for o in out:
        o["dans_arbre"] = o["programme"] in arbre
    return sorted(out, key=lambda o: o["programme"])


# --- Panorama des grands projets -----------------------------------------------------------------------------------


def lire_panorama(prenoms: set, arbre: dict) -> tuple[list[dict], list[dict]]:
    """(éditions triées, relevés). Un relevé = un projet dans une édition, champs utiles seulement."""
    par_nom = {cle_nom(v["nom"]): k for k, v in arbre.items()}
    editions, releves = [], []
    for f in fichiers_source(SOURCES["panorama"]["id"]):
        if f["chemin"].suffix.lower() != ".xlsx":
            continue
        lignes = feuille(f["chemin"])
        entete = [propre(c) for c in lignes[0]]
        col = {n: i for i, n in enumerate(entete) if n}

        def champ(r, prefixe):
            i = next((i for n, i in col.items() if n.startswith(prefixe)), None)
            return r[i] if i is not None and i < len(r) else None

        dates = Counter()
        bruts = []
        for r in lignes[1:]:
            nom = propre(champ(r, "Nom du projet"))
            if not nom:
                continue
            d = champ(r, "Date de publication")
            if isinstance(d, (dt.datetime, dt.date)):
                dates[f"{d.year:04d}-{d.month:02d}"] += 1
            else:
                m = re.match(r"^(\d{4})-(\d{2})", propre(d))
                if m:
                    dates[f"{m.group(1)}-{m.group(2)}"] += 1
            bruts.append((nom, r))
        if not dates:
            raise SystemExit(f"{f['chemin'].name} : date de publication illisible")
        ed = sorted(dates.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        editions.append({"edition": ed, "url": f["url"], "fichier_source": f["chemin"].name, "lignes": len(bruts)})
        for nom, r in bruts:
            cout, cout_mention = nombre(champ(r, "Coût estimé"))
            if cout is not None and cout <= 0:
                cout, cout_mention = None, "non publié"
            duree, duree_mention = nombre(champ(r, "Durée prévisionnelle"))
            if duree is not None and duree <= 0:
                duree, duree_mention = None, "non publié"
            tranche = propre(champ(r, "Coût estimé par tranche")) or None
            inter = propre(champ(r, "Projet interministériel")).lower()
            fin = propre(champ(r, "Financement"))
            desc_col = next((i for n, i in col.items() if n.startswith("Description")), None)
            releves.append({
                "edition": ed, "nom": nom, "cle": cle_nom(nom),
                "ministere": propre(champ(r, "Ministère porteur")) or None,
                "ministere_nom": propre(champ(r, "Ministère nom complet")) or None,
                "interministeriel": True if inter == "oui" else False if inter == "non" else None,
                "debut": mois_debut(champ(r, "Début")),
                "duree_ans": arrondi(duree, 2), "duree_mention": duree_mention,
                "cout_meur": arrondi(cout, 3), "cout_mention": cout_mention,
                "tranche": tranche, "phase": propre(champ(r, "Phase du projet")) or None,
                "financement": fin[:200] or None, "programmes": programmes_cites(fin, arbre, par_nom),
                "description": texte(r[desc_col] if desc_col is not None and desc_col < len(r) else None, prenoms, 280),
            })
    editions.sort(key=lambda e: e["edition"])
    if len({e["edition"] for e in editions}) != len(editions):
        raise SystemExit("panorama : deux fichiers pour la même édition")
    for i, e in enumerate(editions, 1):
        e["numero"] = i
    releves.sort(key=lambda r: (r["edition"], r["cle"], r["ministere"] or ""))
    return editions, releves


def rapprocher(releves: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    """Lignées de projets : (clé -> identifiant de lignée, rapprochements appliqués, changements non rapprochés)."""
    par_cle: dict[str, list[dict]] = defaultdict(list)
    for r in releves:
        par_cle[r["cle"]].append(r)
    for cle, rs in par_cle.items():  # R1 ne doit jamais réunir deux lignes d'une même édition
        doubles = [e for e, n in Counter(r["edition"] for r in rs).items() if n > 1]
        if doubles:
            raise SystemExit(f"panorama : « {cle} » présent deux fois dans l'édition {doubles[0]}")
    lignee = {cle: cle for cle in par_cle}

    def racine(c):
        while lignee[c] != c:
            c = lignee[c]
        return c

    def editions_de(racine_):
        return {r["edition"] for c in par_cle if racine(c) == racine_ for r in par_cle[c]}

    appliques, refuses = [], []
    for cle, rs in sorted(par_cle.items()):
        noms = sorted({r["nom"] for r in rs})
        if len(noms) > 1:
            appliques.append({"regle": "R1", "noms": noms,
                              "critere": "même nom une fois normalisé (majuscules, accents, ponctuation)"})
    for ancien, nouveau, type_ in RENOMMAGES:
        a, b = cle_nom(ancien), cle_nom(nouveau)
        base = {"regle": "R2", "ancien_nom": ancien, "nouveau_nom": nouveau, "type": type_}
        if a not in par_cle or b not in par_cle:
            raise SystemExit(f"RENOMMAGES : nom absent des éditions ({ancien if a not in par_cle else nouveau})")
        ra, rb = racine(a), racine(b)
        if ra == rb:
            continue
        premier_a = min(r["edition"] for r in par_cle[a])
        suivants = sorted(r["edition"] for r in par_cle[b] if r["edition"] > premier_a)
        raisons = []
        commun = sorted(editions_de(ra) & editions_de(rb))
        if commun:
            raisons.append(f"les deux noms figurent dans une même édition ({commun[0]})")
        if not suivants:
            raisons.append("le nouveau nom ne paraît pas après l'ancien")
            refuses.append({**base, "raisons": raisons})
            continue
        eb = suivants[0]
        ea = max(r["edition"] for r in par_cle[a] if r["edition"] < eb)
        xa = next(r for r in par_cle[a] if r["edition"] == ea)
        xb = next(r for r in par_cle[b] if r["edition"] == eb)
        jonction = {"derniere_edition_ancien_nom": ea, "premiere_edition_nouveau_nom": eb,
                    "debut_ancien": xa["debut"], "debut_nouveau": xb["debut"],
                    "cout_meur_ancien": xa["cout_meur"], "cout_meur_nouveau": xb["cout_meur"]}
        if xa["debut"] is None or xb["debut"] is None:
            raisons.append("date de début non publiée à la jonction")
        elif xa["debut"] != xb["debut"]:
            raisons.append(f"dates de début différentes à la jonction ({xa['debut']} puis {xb['debut']})")
        if type_ == "version":
            if xa["cout_meur"] is None or xb["cout_meur"] is None:
                raisons.append("coût estimé non publié à la jonction : même périmètre non vérifiable")
            elif abs(xa["cout_meur"] - xb["cout_meur"]) > TOLERANCE_COUT_MEUR:
                raisons.append(f"coûts estimés publiés différents à la jonction ({xa['cout_meur']} puis "
                               f"{xb['cout_meur']} M€) : périmètre possiblement différent")
        if raisons:
            refuses.append({**base, "jonction": jonction, "raisons": raisons})
        else:
            lignee[rb] = ra
            appliques.append({**base, "jonction": jonction})
    return {c: racine(c) for c in par_cle}, appliques, refuses


def evolution(points: list[tuple[str, float]]) -> dict | None:
    """Première et dernière valeur publiées, écart, minimum et maximum. Null si moins de deux valeurs publiées."""
    if len(points) < 2:
        return None
    (e0, v0), (e1, v1) = points[0], points[-1]
    vals = [v for _, v in points]
    return {"premiere": {"edition": e0, "valeur": v0}, "derniere": {"edition": e1, "valeur": v1},
            "ecart": arrondi(v1 - v0, 3), "ecart_pct": arrondi((v1 - v0) / v0 * 100, 1) if v0 else None,
            "minimum": min(vals), "maximum": max(vals), "valeurs_publiees": len(points)}


def construire_panorama(prenoms: set, arbre: dict, collecte_le: str) -> dict:
    editions, releves = lire_panorama(prenoms, arbre)
    lignees, appliques, refuses = rapprocher(releves)
    derniere = editions[-1]["edition"]
    source = (f"DINUM, « {SOURCES['panorama']['titre']} », data.gouv.fr ({DATAGOUV}{SOURCES['panorama']['jeu']}), "
              f"{len(editions)} éditions de {editions[0]['edition']} à {derniere}")
    millesime = f"Éditions {editions[0]['edition']} à {derniere} du panorama ({len(editions)} éditions)"
    unite = "millions d'euros (coût estimé publié par la DINUM) ; durées en années"

    groupes: dict[str, list[dict]] = defaultdict(list)
    for r in releves:
        groupes[lignees[r["cle"]]].append(r)
    projets, ids = [], set()
    for racine_, rs in sorted(groupes.items()):
        rs.sort(key=lambda r: r["edition"])
        dern = rs[-1]
        pid = slug(dern["nom"])
        while pid in ids:
            pid += "-" + slug(dern["ministere"] or "x")
        ids.add(pid)
        couts = [(r["edition"], r["cout_meur"]) for r in rs if r["cout_meur"] is not None]
        durees = [(r["edition"], r["duree_ans"]) for r in rs if r["duree_ans"] is not None]
        debuts = list(dict.fromkeys(r["debut"] for r in rs if r["debut"]))
        progs = {}
        for r in rs:
            for p in r["programmes"]:
                progs[p["programme"]] = p
        projets.append({
            "id": pid, "nom": dern["nom"], "noms_publies": list(dict.fromkeys(r["nom"] for r in rs)),
            "ministere": dern["ministere"], "ministere_nom": dern["ministere_nom"],
            "interministeriel": next((r["interministeriel"] for r in reversed(rs) if r["interministeriel"] is not None), None),
            "description": dern["description"],
            "editions": {"nombre": len(rs), "premiere": rs[0]["edition"], "derniere": dern["edition"],
                         "dans_la_derniere_edition": dern["edition"] == derniere},
            "debuts_publies": debuts,
            "evolution_cout_meur": evolution(couts), "evolution_duree_ans": evolution(durees),
            "programmes": sorted(progs.values(), key=lambda p: p["programme"]),
            "releves": [{"edition": r["edition"], "nom": r["nom"], "ministere": r["ministere"], "debut": r["debut"],
                         "duree_ans": r["duree_ans"], "duree_mention": r["duree_mention"],
                         "cout_meur": r["cout_meur"], "cout_mention": r["cout_mention"], "tranche": r["tranche"],
                         "phase": r["phase"], "programmes": [p["programme"] for p in r["programmes"]]} for r in rs],
        })
        for r in rs:
            r["projet"] = pid
    projets.sort(key=lambda p: (cle_nom(p["nom"]), p["id"]))

    doc_projets = {
        "millesime": millesime, "source": source, "unite": unite, "collecte_le": collecte_le,
        "avertissement": "Évolution du coût estimé publié : valeurs déclarées par les ministères à la DINUM, reprises "
                         "telles que publiées dans chaque édition. Un écart entre deux éditions peut venir d'un "
                         "changement de périmètre, de calendrier ou de méthode d'estimation : la source ne le précise "
                         "pas. Un coût ou une durée « en cadrage » ou non communiqué est null, jamais 0.",
        "definitions": {
            "cout_meur": "coût estimé publié, en millions d'euros (colonne « Coût estimé »)",
            "duree_ans": "durée prévisionnelle publiée, en années (colonne « Durée prévisionnelle en année »)",
            "debut": "date de début publiée, ramenée au mois (AAAA-MM)",
            "evolution_cout_meur": "première et dernière valeur publiées du coût estimé, écart en millions d'euros "
                                   "et en pourcentage de la première valeur, minimum et maximum publiés",
            "evolution_duree_ans": "même lecture pour la durée prévisionnelle publiée",
            "debuts_publies": "dates de début publiées au fil des éditions, dans l'ordre de leur première apparition",
        },
        "methode": {
            "regles": [
                {"id": "R1", "regle": "Deux lignes de deux éditions sont le même projet si leur nom est identique "
                                      "une fois normalisé (majuscules, accents, ponctuation)."},
                {"id": "R2", "regle": "Un changement de nom déclaré dans le code (pipeline/numerique_etat.py, "
                                      "RENOMMAGES) est appliqué seulement si : aucune édition ne contient les deux "
                                      "noms ; la date de début publiée est la même dans la dernière édition de "
                                      "l'ancien nom et la première du nouveau ; et, quand le nom ajoute ou retire une "
                                      "mention de version, de cycle, de phase ou de périmètre, le coût estimé publié "
                                      f"y est le même à {TOLERANCE_COUT_MEUR} M€ près."},
                {"id": "R3", "regle": "Un changement déclaré dont un critère échoue reste non rapproché : les deux "
                                      "noms sont publiés comme deux projets, la raison est donnée dans "
                                      "non_rapproches."},
            ],
            "limites": "Les noms voisins non déclarés ne sont pas rapprochés. Un projet absent d'une édition puis de "
                       "retour sous le même nom reste un seul projet ; ses relevés donnent les éditions où il figure.",
        },
        "ordre": {"regle": "Projets par ordre alphabétique du dernier nom publié ; relevés par édition croissante.",
                  "cles": ["nom", "edition"]},
        "editions": [e["edition"] for e in editions],
        "projets": projets,
        "rapprochements": appliques, "non_rapproches": refuses,
    }

    # Par édition (et par année), par ministère tel que publié dans l'édition.
    par_ed: dict[str, list[dict]] = defaultdict(list)
    for r in releves:
        par_ed[r["edition"]].append(r)

    def agregat(rs):
        couts = [r["cout_meur"] for r in rs if r["cout_meur"] is not None]
        return {"projets": len(rs), "cout_publie_meur": arrondi(sum(couts), 3) if couts else None,
                "projets_sans_cout_publie": len(rs) - len(couts)}

    doc_ed, prec = [], None
    noms_min: dict[str, dict] = defaultdict(dict)
    series_min: dict[str, list] = defaultdict(list)
    for e in editions:
        rs = par_ed[e["edition"]]
        actuels = {r["projet"] for r in rs}
        mins = defaultdict(list)
        for r in rs:
            mins[r["ministere"] or "non publié"].append(r)
            if r["ministere"] and r["ministere_nom"]:
                noms_min[r["ministere"]].setdefault(r["ministere_nom"], e["edition"])
        par_min = []
        for sigle, lst in sorted(mins.items()):
            a = {"ministere": sigle, **agregat(lst)}
            par_min.append(a)
            series_min[sigle].append({"edition": e["edition"], **agregat(lst),
                                      "projets_ids": sorted(r["projet"] for r in lst)})
        doc_ed.append({
            "edition": e["edition"], "numero": e["numero"], "annee": int(e["edition"][:4]),
            "url": e["url"], **agregat(rs),
            "entrants": None if prec is None else sorted(actuels - prec),
            "sortants": None if prec is None else sorted(prec - actuels),
            "par_tranche": dict(sorted(Counter(r["tranche"] or "non publié" for r in rs).items())),
            "par_ministere": par_min,
        })
        prec = actuels
    annees = defaultdict(list)
    for e in doc_ed:
        annees[e["annee"]].append(e["edition"])
    doc_editions = {
        "millesime": millesime, "source": source, "unite": unite, "collecte_le": collecte_le,
        "avertissement": "Chaque édition est une photographie des projets suivis à sa date. Le total des coûts "
                         "estimés publiés d'une édition n'additionne que les projets dont le coût est publié ; il "
                         "n'est pas une dépense annuelle (les coûts portent sur toute la durée des projets) et deux "
                         "éditions ne s'additionnent pas.",
        "definitions": {"entrants": "projets présents dans l'édition et absents de la précédente (identifiants de "
                                    "panorama/projets.json) ; null pour la première édition",
                        "sortants": "projets présents dans l'édition précédente et absents de celle-ci",
                        "par_tranche": "nombre de projets par tranche de coût telle que publiée"},
        "editions": doc_ed,
        "annees": [{"annee": a, "editions": eds} for a, eds in sorted(annees.items())],
    }
    doc_ministeres = {
        "millesime": millesime, "source": source, "unite": unite, "collecte_le": collecte_le,
        "avertissement": "Ministère porteur tel que publié dans chaque édition (sigle). Les périmètres ministériels "
                         "changent avec les gouvernements : deux sigles successifs ne sont pas rapprochés ici, et la "
                         "série d'un sigle s'arrête quand il n'est plus publié.",
        "ordre": {"regle": "Ministères par ordre alphabétique du sigle publié ; éditions croissantes.",
                  "cles": ["ministere", "edition"]},
        "ministeres": [{"ministere": s,
                        "noms_publies": [n for n, _ in sorted(noms_min.get(s, {}).items(), key=lambda kv: (kv[1], kv[0]))],
                        "editions": serie} for s, serie in sorted(series_min.items())],
    }

    # Par programme LOLF cité : lien vers l'arbre État.
    par_prog: dict[str, dict] = defaultdict(dict)
    for p in projets:
        for cite in p["programmes"]:
            cits = [r for r in p["releves"] if cite["programme"] in r["programmes"]]
            cout = next((r["cout_meur"] for r in reversed(cits) if r["cout_meur"] is not None), None)
            par_prog[cite["programme"]][p["id"]] = {
                "id": p["id"], "nom": p["nom"], "rattachement": cite["rattachement"],
                "derniere_edition_citant_le_programme": cits[-1]["edition"],
                "dernier_cout_publie_meur": cout,
                "programmes_cites_ensemble": cits[-1]["programmes"]}
    doc_prog = {
        "millesime": millesime + " ; arbre État : Exécution 2024",
        "source": source + " (colonne « Financement [programme(s)] ») ; arbre État site/data/arbre/racine.json",
        "unite": unite, "collecte_le": collecte_le,
        "avertissement": "Un projet financé par plusieurs programmes figure sous chacun, avec son coût estimé publié "
                         "entier : la source ne répartit pas le coût entre programmes, les montants de deux "
                         "programmes ne s'additionnent donc pas. Le coût d'un projet porte sur toute sa durée ; il ne "
                         "se compare pas aux crédits annuels du programme.",
        "methode": "Numéros de programme lus dans la colonne « Financement [programme(s)] » (formes « P156 », "
                   "« Programme 156 », « (P156) », « 124 / 155 ») ; à défaut, intitulé strictement identique à celui "
                   "d'un programme de l'arbre État. Un financement publié sans numéro ni intitulé reconnu n'est relié "
                   "à aucun programme. `dans_arbre` : le programme existe dans l'arbre de l'exécution 2024.",
        "programmes": [{"programme": n, "dans_arbre": n in arbre,
                        "noeud": arbre[n]["noeud"] if n in arbre else None,
                        "nom": arbre[n]["nom"] if n in arbre else None,
                        "fichier": arbre[n]["fichier"] if n in arbre else None,
                        "projets": sorted(v.values(), key=lambda x: (cle_nom(x["nom"]), x["id"]))}
                       for n, v in sorted(par_prog.items())],
        "projets_sans_programme_relie": sorted(p["id"] for p in projets if not p["programmes"]),
    }
    return {"projets": doc_projets, "editions": doc_editions, "ministeres": doc_ministeres, "programmes": doc_prog,
            "meta": {"editions": editions, "source": source, "millesime": millesime}}


# --- Fonds ---------------------------------------------------------------------------------------------------------


def somme(lignes: list[dict], cle: str = "montant_eur") -> dict:
    vals = [x[cle] for x in lignes if x[cle] is not None]
    return {"projets": len(lignes), "montant_publie_eur": arrondi(sum(vals), 2) if vals else None,
            "projets_sans_montant_publie": len(lignes) - len(vals)}


def grouper(lignes: list[dict], cle: str, nom_cle: str | None = None) -> list[dict]:
    g = defaultdict(list)
    for x in lignes:
        g[x[cle]].append(x)
    return [{nom_cle or cle: k, **somme(v)} for k, v in sorted(g.items(), key=lambda kv: (kv[0] is None, str(kv[0])))]


def departements_ref() -> dict:
    """Code -> nom des départements (index déjà publié par pipeline/territoires.py, sinon libellés de la source)."""
    try:
        d = json.loads((SITE / "territoires" / "index.json").read_text(encoding="utf-8"))
        return {x["code"]: x["nom"] for x in d["departements"]}
    except (OSError, ValueError, KeyError):
        return {}


def construire_france_relance(prenoms: set, arbre: dict, collecte_le: str) -> tuple[dict, dict]:
    src = SOURCES["france_relance"]
    f = fichiers_source(src["id"])[0]
    lignes = feuille(f["chemin"])
    col = {propre(c): i for i, c in enumerate(lignes[0]) if c}
    ref = departements_ref()
    projets, non_publies, titres_retires = [], 0, 0
    for r in lignes[1:]:
        montant, _ = nombre(r[col["Montant accordé"]])
        d = r[col["Date de décision"]]
        date = d.date().isoformat() if isinstance(d, dt.datetime) else None
        m = re.search(r"^(.*?)\s*\((\d{2,3}|2A|2B)\)\s*$", propre(r[col["Département"]]))
        dep, dep_nom = (m.group(2), m.group(1)) if m else (None, None)
        ministere = re.sub(r"^\[\s*(.*?)\s*\]$", r"\1", propre(r[col["Ministère"]])) or None
        brut = propre(r[col["Direction ou opérateur"]])
        p = porteur(brut, prenoms)
        non_publies += bool(brut) and p is None
        titre_brut = propre(r[col["Titre du projet"]])
        titre = texte(titre_brut, prenoms, 200)
        titres_retires += bool(titre_brut) and titre is None
        projets.append({"dispositif": propre(r[col["Code dispositif"]]) or None,
                        "libelle_dispositif": propre(r[col["Libellé dispositif"]]) or None,
                        "ministere": ministere, "porteur": p, "titre": titre, "montant_eur": arrondi(montant, 2),
                        "date_decision": date, "annee": int(date[:4]) if date else None,
                        "departement": dep, "departement_nom": ref.get(dep, dep_nom) if dep else None})
    projets.sort(key=lambda x: (x["departement"] or "zz", x["date_decision"] or "", x["dispositif"] or "",
                                x["porteur"] or "", x["titre"] or "", x["montant_eur"] or 0))
    dates = sorted(x["date_decision"] for x in projets if x["date_decision"])
    millesime = f"Décisions du {dates[0]} au {dates[-1]} (édition d'octobre 2022 du jeu, dernière publiée)"
    source = f"{src['producteur']}, « {src['titre']} », data.gouv.fr ({DATAGOUV}{src['jeu']})"
    disp = defaultdict(list)
    for x in projets:
        disp[(x["dispositif"], x["libelle_dispositif"])].append(x)
    par_dep = defaultdict(list)
    for x in projets:
        par_dep[x["departement"]].append(x)
    deps, fichiers = [], {}
    for code, lst in sorted(par_dep.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
        if code is None:
            deps.append({"code": None, "nom": "département non publié", **somme(lst)})
            continue
        nom = lst[0]["departement_nom"]
        fichiers[code] = {
            "millesime": millesime, "source": source, "unite": "euros", "collecte_le": collecte_le,
            "departement": {"code": code, "nom": nom}, "total": somme(lst),
            "par_dispositif": [{"dispositif": k[0], "libelle_dispositif": k[1], **somme(v)}
                               for k, v in sorted(defaultdict(list, _grp(lst)).items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))],
            "ordre": {"regle": "Projets par date de décision, puis dispositif, porteur et titre.",
                      "cles": ["date_decision", "dispositif", "porteur", "titre"]},
            "projets": [{k: x[k] for k in ("dispositif", "libelle_dispositif", "ministere", "porteur", "titre",
                                           "montant_eur", "date_decision")} for x in lst],
        }
        deps.append({"code": code, "nom": nom, **somme(lst),
                     "fichier": f"numerique_etat/fonds/france_relance/{code}.json"})
    doc = {
        "millesime": millesime, "source": source, "unite": "euros", "collecte_le": collecte_le,
        "avertissement": "Montant accordé tel que publié, par projet. Le jeu ne publie aucun montant pour une partie "
                         "des lignes (fonds déconcentré ITN7 et programme Démat. ADS notamment) : ces lignes sont "
                         "comptées, leur montant est null, et les totaux n'additionnent que les montants publiés. "
                         "Le département est celui publié pour le porteur du projet (Paris pour la plupart des "
                         "administrations centrales) : il ne dit pas où le projet est utilisé.",
        "note": "Les montants du fonds déconcentré ITN7 par collectivité sont publiés dans un autre jeu (DITP, "
                "fonds/ditp.json) : les deux jeux se recoupent et ne s'additionnent pas.",
        "arbre_etat": lien_action(arbre, "france_relance"),
        "confidentialite": {"regle_personnes": "Porteurs : administrations, établissements et collectivités "
                            "(personnes morales) ; le jeu ne publie pas de SIREN. Un nom de porteur ou un titre "
                            "où un nom de personne ou une coordonnée est possible est remplacé par null ; le montant "
                            "reste publié. Les descriptifs longs ne sont pas repris.",
                            "porteurs_non_publies": non_publies, "titres_non_publies": titres_retires},
        "total": somme(projets),
        "par_dispositif": [{"dispositif": k[0], "libelle_dispositif": k[1], **somme(v)}
                           for k, v in sorted(disp.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))],
        "par_ministere": grouper(projets, "ministere"),
        "par_annee": grouper(projets, "annee"),
        "ordre": {"regle": "Départements par code ; dispositifs par code puis libellé ; ministères par ordre "
                           "alphabétique.", "cles": ["code"]},
        "departements": deps,
    }
    return doc, fichiers


def _grp(lst):
    g = defaultdict(list)
    for x in lst:
        g[(x["dispositif"], x["libelle_dispositif"])].append(x)
    return g


def construire_ditp(prenoms: set, arbre: dict, collecte_le: str) -> tuple[dict, dict]:
    src = SOURCES["ditp"]
    fs = {("itn7" if "itn7" in f["chemin"].name else "fitn8"): f for f in fichiers_source(src["id"])}
    source = f"{src['producteur']}, « {src['titre']} », data.gouv.fr ({DATAGOUV}{src['jeu']})"
    ref = departements_ref()
    # FITN8 : appels à projets nationaux
    lignes = feuille(fs["fitn8"]["chemin"])
    col = {propre(c): i for i, c in enumerate(lignes[0]) if c}
    c_montant = next(i for n, i in col.items() if n.startswith("Montant FITN8"))
    fitn8 = []
    for r in lignes[1:]:
        d = r[col["Année"]]
        montant, _ = nombre(r[c_montant])
        total, _ = nombre(r[col["Coût Total Projet"]])
        fitn8.append({"projet": texte(r[col["Projet"]], prenoms, 200),
                      "ministere": propre(r[col["Ministère(s) Porteur(s)"]]) or None,
                      "porteur": porteur(r[col["Direction(s) / Etabl."]], prenoms),
                      "date_decision": d.date().isoformat() if isinstance(d, dt.datetime) else None,
                      "annee": d.year if isinstance(d, dt.datetime) else None,
                      "cout_total_projet_eur": arrondi(total, 2), "montant_eur": arrondi(montant, 2)})
    fitn8.sort(key=lambda x: (x["date_decision"] or "9999", x["ministere"] or "", x["projet"] or "", x["montant_eur"] or 0))
    # ITN7, axe 3, volet 1 : fonds déconcentré, par collectivité
    lignes = feuille(fs["itn7"]["chemin"], nom="Volet 1")
    i0 = next(i for i, r in enumerate(lignes) if propre(r[0]) == "SGAR")
    ent = [propre(c) for c in lignes[i0]]

    def idx(prefixe):
        return next(i for i, n in enumerate(ent) if n.startswith(prefixe))

    c_dep, c_nom, c_coll, c_insee = idx("Nom du département"), idx("Nom du projet"), idx("Collectivité"), idx("Code INSEE")
    c_type, c_total, c_fin = idx("Type de projet"), idx("Montant total"), idx("Montant financé")
    itn7, non_publies = [], 0
    for r in lignes[i0 + 1:]:
        m = re.match(r"^(\d{2,3}|2A|2B)\s*-\s*(.+)$", propre(r[c_dep]))
        dep = m.group(1) if m else None
        montant, _ = nombre(r[c_fin])
        total, _ = nombre(r[c_total])
        brut = propre(r[c_coll])
        p = porteur(brut, prenoms)
        non_publies += bool(brut) and p is None
        insee = propre(r[c_insee])
        itn7.append({"region": propre(r[0]) or None, "departement": dep,
                     "departement_nom": ref.get(dep, m.group(2) if m else None) if dep else None,
                     "collectivite": p, "code_insee": insee if re.fullmatch(r"\d[\dAB]\d{3}|\d{9}", insee) else None,
                     "projet": texte(r[c_nom], prenoms, 200), "type": propre(r[c_type]) or None,
                     "cout_total_projet_eur": arrondi(total, 2), "montant_eur": arrondi(montant, 2)})
    itn7.sort(key=lambda x: (x["departement"] or "zz", x["collectivite"] or "", x["projet"] or "", x["montant_eur"] or 0))
    millesime = "Projets financés en 2021 et 2022 (jeu publié en janvier 2023)"
    par_dep = defaultdict(list)
    for x in itn7:
        par_dep[x["departement"]].append(x)
    deps, fichiers = [], {}
    for code, lst in sorted(par_dep.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
        if code is None:
            deps.append({"code": None, "nom": "département non publié", **somme(lst)})
            continue
        fichiers[code] = {
            "millesime": millesime, "source": source + ", classeur ITN7, feuille « Volet 1 »", "unite": "euros",
            "collecte_le": collecte_le, "departement": {"code": code, "nom": lst[0]["departement_nom"]},
            "total": somme(lst),
            "ordre": {"regle": "Projets par collectivité puis nom du projet.", "cles": ["collectivite", "projet"]},
            "projets": [{k: x[k] for k in ("collectivite", "code_insee", "projet", "type", "cout_total_projet_eur",
                                           "montant_eur")} for x in lst],
        }
        deps.append({"code": code, "nom": lst[0]["departement_nom"], **somme(lst),
                     "fichier": f"numerique_etat/fonds/ditp_itn7/{code}.json"})
    doc = {
        "millesime": millesime, "source": source, "unite": "euros", "collecte_le": collecte_le,
        "avertissement": "Deux classeurs : les appels à projets FITN8 (montant octroyé par projet, programme 363 "
                         "d'après l'en-tête du jeu) et le fonds déconcentré ITN7, axe 3, volet 1 (montant financé par "
                         "collectivité). Ces lignes recoupent en partie celles du jeu France Relance de l'enveloppe "
                         "MTFP (fonds/france_relance.json) : les deux jeux ne s'additionnent pas.",
        "arbre_etat": lien_action(arbre, "ditp"),
        "confidentialite": {"regle_personnes": "Porteurs : administrations et collectivités (personnes morales) ; "
                            "pas de SIREN publié. Nom de collectivité ou titre où un nom de personne ou une "
                            "coordonnée est possible : null, montant conservé. Descriptions non reprises.",
                            "porteurs_non_publies": non_publies},
        "fitn8": {"total": somme(fitn8), "par_ministere": grouper(fitn8, "ministere"),
                  "par_annee": grouper(fitn8, "annee"),
                  "ordre": {"regle": "Projets par date de décision (dates non publiées en dernier), puis ministère "
                                     "et nom.", "cles": ["date_decision", "ministere", "projet"]},
                  "projets": fitn8},
        "itn7_volet1": {"total": somme(itn7), "par_type": grouper(itn7, "type"), "par_region": grouper(itn7, "region"),
                        "ordre": {"regle": "Départements par code.", "cles": ["code"]},
                        "departements": deps},
    }
    return doc, fichiers


def construire_ftap(prenoms: set, arbre: dict, collecte_le: str) -> dict:
    src = SOURCES["ftap"]
    f = fichiers_source(src["id"])[0]
    with open(f["chemin"], encoding="utf-8-sig", newline="") as fh:
        lignes = list(csv.reader(fh, delimiter=";"))
    ent = [propre(c) for c in lignes[0]]

    def idx(mot):
        return next(i for i, n in enumerate(ent) if mot in n)

    c_g, c_p, c_prog, c_min, c_port, c_m = idx("Guichet"), idx("Projet"), idx("Programme"), idx("Ministère"), idx("Porteur"), idx("Montant")
    laureats = []
    for r in lignes[1:]:
        if not any(propre(c) for c in r):
            continue
        montant, _ = nombre(r[c_m])
        laureats.append({"guichet": propre(r[c_g]) or None, "projet": texte(r[c_p], prenoms, 200),
                         "incubateur": propre(r[c_prog]) or None, "ministere": propre(r[c_min]) or None,
                         "porteur": porteur(r[c_port], prenoms), "montant_eur": arrondi(montant, 2)})
    laureats.sort(key=lambda x: (x["guichet"] or "", x["ministere"] or "", x["porteur"] or "", x["projet"] or "",
                                 x["montant_eur"] or 0))
    return {
        "millesime": "Lauréats effectifs au 23/10/2024 (conventions de financement signées depuis 2023)",
        "source": f"{src['producteur']}, « {src['titre']} », data.gouv.fr ({DATAGOUV}{src['jeu']})",
        "unite": "euros", "collecte_le": collecte_le,
        "avertissement": "Montant attribué par convention, tel que publié. Le jeu ne donne pas la date de chaque "
                         "convention : aucune répartition par année n'est possible. Le ministère est publié en tant "
                         "que centre financier. Les résumés des projets ne sont pas repris.",
        "arbre_etat": lien_action(arbre, "ftap"),
        "definitions": {"incubateur": "colonne « Programme » du jeu : nom de l'incubateur ou du programme "
                                      "d'accompagnement (AllIAnce), quand il est publié ; ce n'est pas un programme "
                                      "budgétaire"},
        "total": somme(laureats),
        "par_guichet": grouper(laureats, "guichet"), "par_ministere": grouper(laureats, "ministere"),
        "par_annee": None, "par_annee_note": "date de convention non publiée dans le jeu",
        "ordre": {"regle": "Lauréats par guichet, puis ministère, porteur et projet (ordre alphabétique).",
                  "cles": ["guichet", "ministere", "porteur", "projet"]},
        "laureats": laureats,
    }


def construire_fast(prenoms: set, arbre: dict, collecte_le: str) -> dict:
    src = SOURCES["fast"]
    f = fichiers_source(src["id"])[0]
    lignes = feuille(f["chemin"])
    i0 = next(i for i, r in enumerate(lignes) if propre(r[0]).startswith("AAP"))
    note_source = next((propre(r[0]) for r in lignes[:i0] if propre(r[0]).startswith("NB")), None)
    projets, appel = [], None
    for rang, r in enumerate(lignes[i0 + 1:]):
        r = list(r) + [None] * 6
        if propre(r[0]):
            t = propre(r[0])
            m = re.match(r"^(\d+)", t)
            ma = re.search(r"([A-Za-zéûÉÛ]+)\s+(\d{4})\s*$", t)
            mois = MOIS.get(sans_accent(ma.group(1)).lower()) if ma else None
            appel = {"numero": int(m.group(1)) if m else None, "annee": int(ma.group(2)) if ma else None, "mois": mois,
                     "libelle": (f"{m.group(1)}{'er' if m.group(1) == '1' else 'e'} appel à projets" if m else t)
                     + (f", {MOIS_NOMS[mois - 1]} {ma.group(2)}" if ma and mois else "")}
        if not propre(r[2]) and not propre(r[1]):
            continue
        montant, _ = nombre(r[4])
        coaching, _ = nombre(r[5])
        coach_txt = propre(r[5])
        projets.append({"appel": appel["numero"] if appel else None, "annee": appel["annee"] if appel else None,
                        "rang_source": rang, "laureat": porteur(r[1], prenoms), "projet": texte(r[2], prenoms, 120),
                        "objet": texte(r[3], prenoms, 200), "montant_eur": arrondi(montant, 2),
                        "dont_coaching_eur": arrondi(coaching, 2),
                        "coaching_mention": coach_txt if coach_txt and coaching is None else None,
                        "_appel": appel})
    appels = []
    for num in sorted({p["appel"] for p in projets if p["appel"] is not None}):
        lst = [p for p in projets if p["appel"] == num]
        a = lst[0]["_appel"]
        appels.append({"numero": num, "annee": a["annee"], "mois": a["mois"], "libelle": a["libelle"], **somme(lst)})
    for p in projets:
        del p["_appel"], p["rang_source"]
    return {
        "millesime": f"Appels à projets {appels[0]['numero']} à {appels[-1]['numero']} "
                     f"({appels[0]['annee']} à {appels[-1]['annee']}), tableau mis à jour le 12/01/2026",
        "source": f"{src['producteur']}, « {src['titre']} », data.gouv.fr ({DATAGOUV}{src['jeu']})",
        "unite": "euros", "collecte_le": collecte_le,
        "avertissement": "Financement total octroyé par projet et par appel, tel que publié ; un même service "
                         "numérique peut être lauréat de plusieurs appels. Un montant publié à 0 est repris à 0 ; une "
                         "cellule vide est null.",
        "note": note_source,
        "arbre_etat": lien_action(arbre, "fast"),
        "definitions": {"dont_coaching_eur": "part du financement consacrée à l'accompagnement (coaching), quand un "
                                             "montant est publié ; `coaching_mention` reprend la mention publiée "
                                             "quand ce n'est pas un montant"},
        "total": somme(projets),
        "par_appel": appels, "par_annee": grouper(projets, "annee"),
        "ordre": {"regle": "Projets dans l'ordre des appels, puis dans l'ordre du tableau publié.",
                  "cles": ["appel"]},
        "projets": projets,
    }


# --- Production ----------------------------------------------------------------------------------------------------


def produire(sortie: Path) -> None:
    for s in SOURCES.values():
        if not fichiers_source(s["id"]):
            raise SystemExit(f"source absente de l'entrepôt : {s['id']} (python collecte/collecte.py {s['id']})")
    prenoms = local.prenoms()
    arbre = programmes_arbre()
    collecte_le = date_sources("numerique_etat")
    pano = construire_panorama(prenoms, arbre, collecte_le)
    fr, fr_deps = construire_france_relance(prenoms, arbre, collecte_le)
    ditp, ditp_deps = construire_ditp(prenoms, arbre, collecte_le)
    ftap = construire_ftap(prenoms, arbre, collecte_le)
    fast = construire_fast(prenoms, arbre, collecte_le)

    if sortie.exists():
        shutil.rmtree(sortie)
    ecrire(sortie / "panorama" / "projets.json", pano["projets"])
    ecrire(sortie / "panorama" / "editions.json", pano["editions"])
    ecrire(sortie / "panorama" / "ministeres.json", pano["ministeres"])
    ecrire(sortie / "panorama" / "programmes.json", pano["programmes"])
    ecrire(sortie / "fonds" / "france_relance.json", fr)
    for code, d in sorted(fr_deps.items()):
        ecrire(sortie / "fonds" / "france_relance" / f"{code}.json", d)
    ecrire(sortie / "fonds" / "ditp.json", ditp)
    for code, d in sorted(ditp_deps.items()):
        ecrire(sortie / "fonds" / "ditp_itn7" / f"{code}.json", d)
    ecrire(sortie / "fonds" / "ftap.json", ftap)
    ecrire(sortie / "fonds" / "fast.json", fast)

    # Par année : chaque source dans sa colonne, jamais additionnées entre elles.
    annees = defaultdict(dict)
    for e in pano["editions"]["editions"]:
        annees[e["annee"]].setdefault("panorama_editions", []).append(
            {k: e[k] for k in ("edition", "projets", "cout_publie_meur", "projets_sans_cout_publie")})
    for cle, lst in (("france_relance_decisions", fr["par_annee"]), ("ditp_fitn8_decisions", ditp["fitn8"]["par_annee"]),
                     ("fast_appels", fast["par_annee"])):
        for x in lst:
            if x["annee"] is not None:
                annees[x["annee"]][cle] = {k: v for k, v in x.items() if k != "annee"}
    doc_annees = {
        "millesime": f"{min(annees)} à {max(annees)} selon la source",
        "source": "panorama DINUM, France Relance (enveloppe MTFP), guichets DITP, FAST : voir numerique_etat/index.json",
        "unite": "millions d'euros pour le panorama (coût estimé publié) ; euros pour les fonds",
        "collecte_le": collecte_le,
        "avertissement": "Chaque source est donnée dans sa propre colonne. Les grandeurs ne sont pas de même nature "
                         "(coût estimé sur toute la durée d'un projet, montant accordé à une date de décision) et les "
                         "jeux se recoupent en partie : rien n'est additionné entre sources. Le FTAP n'a pas de date "
                         "par convention et n'apparaît pas ici.",
        "definitions": {"panorama_editions": "éditions du panorama parues dans l'année : projets suivis, somme des "
                                             "coûts estimés publiés, projets sans coût publié",
                        "france_relance_decisions": "projets par année de décision (enveloppe MTFP)",
                        "ditp_fitn8_decisions": "projets FITN8 par année de décision publiée",
                        "fast_appels": "projets lauréats du FAST par année de l'appel à projets"},
        "annees": [{"annee": a, **v} for a, v in sorted(annees.items())],
    }
    ecrire(sortie / "annees.json", doc_annees)

    m = manifeste()
    sources = []
    for cle, s in SOURCES.items():
        fs = fichiers_source(s["id"])
        sources.append({"id": s["id"], "titre": s["titre"], "producteur": s["producteur"], "licence": LICENCE,
                        "url": DATAGOUV + s["jeu"], "fichiers": len(fs),
                        "ressource_modifiee_le": max((f["ressource_modifiee_le"] or "" for f in fs), default="") or None,
                        "collecte_le": str((m.get(s["id"]) or {}).get("collecte_le") or "")[:10] or None})
    pr = pano["projets"]["projets"]
    avec = [p for p in pr if p["evolution_cout_meur"]]
    dern = pano["editions"]["editions"][-1]
    index = {
        "millesime": f"{pano['meta']['millesime']} ; fonds : décisions 2019 à 2025 selon la source",
        "source": "DINUM, France Relance, DITP, beta.gouv.fr via data.gouv.fr (détail dans `sources`)",
        "unite": "millions d'euros pour le panorama ; euros pour les fonds",
        "collecte_le": collecte_le,
        "avertissement": "Grands projets numériques de l'État et fonds de transformation numérique, tels que publiés. "
                         "Pour le panorama, le site donne l'évolution du coût estimé publié et de la durée "
                         "prévisionnelle publiée d'une édition à l'autre ; la source n'explique pas les écarts. "
                         "Les fonds sont donnés chacun avec son périmètre ; ils se recoupent en partie et ne "
                         "s'additionnent pas.",
        "sources": sources,
        "panorama": {
            "fichiers": {"projets": "numerique_etat/panorama/projets.json",
                         "editions": "numerique_etat/panorama/editions.json",
                         "ministeres": "numerique_etat/panorama/ministeres.json",
                         "programmes": "numerique_etat/panorama/programmes.json"},
            "editions": len(pano["meta"]["editions"]),
            "premiere_edition": pano["meta"]["editions"][0]["edition"], "derniere_edition": dern["edition"],
            "projets": len(pr), "projets_dans_la_derniere_edition": dern["projets"],
            "cout_publie_derniere_edition_meur": dern["cout_publie_meur"],
            "projets_sans_cout_publie_derniere_edition": dern["projets_sans_cout_publie"],
            "projets_avec_au_moins_deux_couts_publies": len(avec),
            "rapprochements_appliques": len(pano["projets"]["rapprochements"]),
            "changements_de_nom_non_rapproches": len(pano["projets"]["non_rapproches"]),
            "programmes_cites": len(pano["programmes"]["programmes"]),
            "programmes_cites_dans_arbre": sum(p["dans_arbre"] for p in pano["programmes"]["programmes"]),
        },
        "fonds": [
            {"id": "france_relance", "nom": "France Relance, mise à niveau numérique de l'État et des territoires "
                                            "(enveloppe MTFP)", "fichier": "numerique_etat/fonds/france_relance.json",
             "millesime": fr["millesime"], **fr["total"], "departements": len(fr_deps),
             "arbre_etat": fr["arbre_etat"]},
            {"id": "ditp", "nom": "France Relance, guichets de la DITP (FITN8 et ITN7 déconcentré)",
             "fichier": "numerique_etat/fonds/ditp.json", "millesime": ditp["millesime"],
             "fitn8": ditp["fitn8"]["total"], "itn7_volet1": ditp["itn7_volet1"]["total"],
             "departements": len(ditp_deps), "arbre_etat": ditp["arbre_etat"]},
            {"id": "ftap", "nom": "Guichets numériques du Fonds pour la transformation de l'action publique (FTAP)",
             "fichier": "numerique_etat/fonds/ftap.json", "millesime": ftap["millesime"], **ftap["total"],
             "arbre_etat": ftap["arbre_etat"]},
            {"id": "fast", "nom": "Fonds d'accélération des startups d'État et de territoires (FAST)",
             "fichier": "numerique_etat/fonds/fast.json", "millesime": fast["millesime"], **fast["total"],
             "arbre_etat": fast["arbre_etat"]},
        ],
        "annees": {"fichier": "numerique_etat/annees.json"},
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    ecrire(sortie / "index.json", index)
    n = len(list(sortie.rglob("*.json")))
    print(f"numerique_etat : {n} fichiers ; panorama {len(pr)} projets sur {len(pano['meta']['editions'])} éditions, "
          f"{len(pano['projets']['rapprochements'])} rapprochements, {len(pano['projets']['non_rapproches'])} non "
          f"rapprochés ; France Relance {fr['total']} ; FTAP {ftap['total']} ; FAST {fast['total']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("commande", choices=["produire"])
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args()
    produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
