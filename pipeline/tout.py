"""Orchestrateur de la mise à jour hebdomadaire : régénère tout site/data dans l'ordre des dépendances.

    python pipeline/tout.py                       # tout : collecte (réseau) puis production, étape par étape
    python pipeline/tout.py --sans-reseau         # production seule, sur l'entrepôt et les caches présents
    python pipeline/tout.py --etapes secu,dette   # quelques étapes (leurs dépendances sont supposées à jour)
    python pipeline/tout.py --reprendre           # saute les étapes réussies au passage précédent (même code)
    python pipeline/tout.py --plan                # affiche le graphe et l'ordre, n'exécute rien
    python pipeline/tout.py entrepot [--rafraichir]   # complète data/lake avec les seuls fichiers lus par les
                                                  # étapes (pipeline/entrees_lac.json : chemin et URL publique)
    python pipeline/tout.py inventorier           # (strace requis) relève les fichiers de data/lake lus par
                                                  # chaque étape et réécrit pipeline/entrees_lac.json
    python pipeline/tout.py changements           # code 0 si une donnée a changé (hors genere_le), 1 sinon

Pourquoi un script Python plutôt qu'un Makefile : make décide sur les dates de modification (sans valeur après un
git clone ou une restauration de cache), ne sait ni distinguer une source inaccessible d'une erreur de code, ni
restaurer la dernière version publiée d'une étape en échec, ni relancer une commande reprenable (local.py, code 3)
dans un budget de temps. Bibliothèque standard seulement : il tourne avant même l'installation des dépendances.

Règles :
  - ordre topologique fixe (ETAPES, une ligne par axe : un module absent du dépôt est ignoré) ; une étape ne lit
    que des fichiers produits par ses dépendances ou versionnés ; « datapackage » (docs/datapackage/) vient en dernier ;
  - chaque commande est idempotente (les modules écrivent des sorties reproductibles, tests/test_reproductibilite.py) ;
  - avant une étape, ses sorties sont copiées ; si elle échoue, elles sont restaurées : site/data garde la dernière
    version publiée de cette étape, et les étapes suivantes tournent quand même sur cette version ;
  - une collecte qui échoue sur une source inaccessible (401, 403, 429, 5xx, délai, page Cloudflare) n'est pas une
    erreur : elle est notée et la production tourne sur le cache ; aucun contournement (ni autre User-Agent, ni
    miroir non officiel) ;
  - une production qui échoue faute d'entrée dans data/lake (runner sans entrepôt) est notée « conservée », pas une
    erreur ; toute autre erreur rend la sortie non nulle (code 1), après que toutes les étapes possibles ont tourné ;
  - rapport public déterministe : site/data/mise_a_jour.json (contrat 2.22, aucune durée, seul `genere_le` change
    à chaque passage) ; journal détaillé avec durées : data/lake/_cache/tout/journal.json (et résumé GitHub).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
LAKE = ROOT / "data" / "lake"
ETAT_DIR = LAKE / "_cache" / "tout"
ENTREES = Path(__file__).resolve().parent / "entrees_lac.json"
RAPPORT = SITE / "mise_a_jour.json"
PY = sys.executable

TRANSFORM = ("site/data/meta.json", "site/data/arbre", "site/data/arbre_lfi2025", "site/data/arbre_plf2025_nature",
             "site/data/arbre_administrations", "site/data/sankey_etat.json", "site/data/sankey_etat_lfi2025.json",
             "site/data/nature_etat.json", "site/data/programmes", "site/data/communes", "site/data/cofog.json",
             "site/data/administrations.json", "site/data/recettes.json", "site/data/deficit.json",
             "data/raw", "data/processed")


@dataclass(frozen=True)
class Etape:
    id: str
    titre: str
    deps: tuple[str, ...]
    sorties: tuple[str, ...]                      # chemins versionnés écrits par l'étape (relatifs à la racine)
    collecter: tuple[tuple[str, ...], ...] = ()   # commandes réseau (reprenables, sans contournement)
    produire: tuple[tuple[str, ...], ...] = ()    # commandes de production (sans réseau sauf `local`)
    a_relancer: int | None = None                 # code de sortie « passage partiel, relancer » (local.py : 3)
    duree_estimee_s: int = 60                     # collecte comprise, cache chaud ; mesurée le 17/11/2026
    duree_max_s: int = 3600                       # garde-fou par commande


def axe(id_: str, titre: str, deps: tuple[str, ...], collecte: bool = True, duree_s: int = 300) -> "Etape":
    """Déclaration d'un axe en une ligne : pipeline/<id>.py [collecter] produire -> site/data/<id>/."""
    return Etape(id_, titre, deps, (f"site/data/{id_}",), collecter=(m(id_, "collecter"),) if collecte else (),
                 produire=(m(id_, "produire"),), duree_estimee_s=duree_s)


TOUTES = "*"   # dépendance spéciale : toutes les étapes déclarées avant (étape finale « datapackage »)


def m(module: str, *args: str) -> tuple[str, ...]:
    return (f"pipeline/{module}.py", *args)


ETAPES: tuple[Etape, ...] = (
    Etape("base", "Budget de l'État, Eurostat, communes (data/raw)", (), TRANSFORM,
          collecter=(m("fetch"),), produire=(m("check_schema"), m("transform")), duree_estimee_s=270),
    Etape("beneficiaires", "Nature, effectifs, bénéficiaires par programme", ("base",),
          ("site/data/nature", "site/data/effectifs", "site/data/beneficiaires"),
          collecter=tuple(m("beneficiaires", "resoudre", c, "--budget", "300")
                          for c in ("associations", "france2030", "acheteurs", "titulaires")),
          produire=(m("beneficiaires", "tout"),), duree_estimee_s=30),
    Etape("operateurs", "Opérateurs de l'État (jaunes PLF)", ("base",), ("site/data/operateurs",),
          collecter=(m("operateurs", "collecter"), m("operateurs", "siren")), produire=(m("operateurs", "produire"),),
          duree_estimee_s=30),
    Etape("vie_politique", "Vie politique (CNCCFP, programme 232)", ("base",), ("site/data/vie_politique",),
          collecter=(m("vie_politique", "collecte", "tout"),), produire=(m("vie_politique", "produire"),),
          duree_estimee_s=240),
    Etape("realisations", "Prévu / dépensé, performance, évaluations", ("base", "beneficiaires"),
          ("site/data/realisations",), collecter=(m("realisations", "collecter", "--budget", "420"),),
          produire=(m("realisations", "produire"),), duree_estimee_s=450),
    Etape("decisions", "Décisions sur les crédits (AN, Sénat, JORF)", ("base", "vie_politique"),
          ("site/data/decisions",), collecter=(m("decisions", "jorf", "--budget", "540"),),
          produire=(m("decisions", "produire"),), duree_estimee_s=600),
    Etape("prelevements", "Prélèvements et affectation", ("base",), ("site/data/prelevements",),
          collecter=(m("prelevements", "collecter"),), produire=(m("prelevements", "produire"),),
          duree_estimee_s=15),
    Etape("secu", "Sécurité sociale (OCR des tableaux en image, en cache)", ("prelevements",), ("site/data/secu",),
          collecter=(m("secu", "collecter"),), produire=(m("secu", "produire"),), duree_estimee_s=15),
    Etape("niches", "Dépenses fiscales et niches sociales (PDF tome II)", ("base",), ("site/data/niches",),
          collecter=(m("niches", "collecter"),), produire=(m("niches", "produire"),), duree_estimee_s=15),
    Etape("ue", "Union européenne (Kohesio, FTS, Horizon)", ("base",), ("site/data/ue",),
          collecter=(m("ue", "collecter"), m("ue", "resoudre", "--budget", "480")), produire=(m("ue", "produire"),),
          duree_estimee_s=500),
    Etape("dette", "Dette publique", ("base", "realisations", "secu"), ("site/data/dette",),
          collecter=(m("dette", "collecter"),), produire=(m("dette", "produire"),), duree_estimee_s=30),
    Etape("tracabilite", "Traçabilité de chaque euro", ("base", "beneficiaires", "vie_politique", "operateurs",
                                                         "realisations"),
          ("site/data/tracabilite",), produire=(m("tracabilite"),), duree_estimee_s=5),
    Etape("local", "Près de chez moi (OFGL, API géo ; reprenable par passages de 480 s)", ("base",),
          ("site/data/local",), produire=(m("local", "tout", "--tous", "--budget", "480"),), a_relancer=3,
          duree_estimee_s=120, duree_max_s=900),
    Etape("controle", "Juridictions financières, lobbying, aides aux entreprises",
          ("base", "realisations", "beneficiaires", "local", "niches", "ue"), ("site/data/controle",),
          collecter=(m("controle", "collecter", "--budget", "1800"),), produire=(m("controle", "produire"),),
          duree_estimee_s=1900),
    Etape("local_fonctions", "Dépenses par fonction des collectivités (balances DGFiP)", ("local",),
          ("site/data/local/fonctions",), produire=(m("local_fonctions"),), duree_estimee_s=300),
    Etape("subventions", "Subventions par convention (attribuants nationaux)", ("local",), ("site/data/subventions",),
          collecter=(m("subventions", "collecter"),), produire=(m("subventions", "produire"),), duree_estimee_s=300),
    Etape("territoires", "Territoires : DETR/DSIL/DPV/DSID, SRU, aide sociale départementale", ("local",),
          ("site/data/territoires",), collecter=(m("territoires", "collecter"),),
          produire=(m("territoires", "produire"),), duree_estimee_s=300),
    Etape("prestations", "Prestations sociales (séries nationales et départementales)", ("secu",),
          ("site/data/prestations",), collecter=(m("prestations", "collecter"),),
          produire=(m("prestations", "produire"),), duree_estimee_s=120),
    Etape("europe_comparaison", "Comparaison européenne (Eurostat)", ("base",), ("site/data/comparaison",),
          produire=(m("europe_comparaison", "produire"),), duree_estimee_s=120),
    # Axes : sorties site/data/<id>/, commandes « collecter » (réseau, si collecte) et « produire ».
    axe("aide_developpement", "Aide publique au développement", ("base",), collecte=False),
    axe("associations", "Associations subventionnées (RNA, SIRENE)", ("beneficiaires",), collecte=False),
    axe("education_recherche", "Éducation et recherche", ("beneficiaires",)),
    axe("etat_actionnaire", "État actionnaire", ("base",)),
    axe("fonction_publique", "Fonction publique", ("base", "beneficiaires"), collecte=False),
    axe("formation", "Formation professionnelle", ("operateurs",)),
    axe("justice_defense", "Justice et défense", ("realisations",)),
    axe("local_satellites", "Satellites des collectivités", ("local",)),
    axe("marches", "Marchés publics", ("beneficiaires",)),
    axe("numerique_etat", "Numérique de l'État", ("base", "territoires"), collecte=False),
    axe("outremer", "Outre-mer", ("base",)),
    axe("recouvrement", "Recouvrement", ("base",), collecte=False),
    axe("retraites", "Retraites par régime", ("base", "secu", "prestations"), duree_s=30),
    axe("sante_etablissements", "Établissements de santé", ("secu", "subventions")),
    axe("sport", "Sport : programmes 219 et 350, Agence nationale du sport, CNDS, coût public des Jeux (Cour des comptes)",
        ("base", "realisations", "operateurs", "associations", "local"), duree_s=60),
    # Nouvel axe : une ligne ici (avant « datapackage »). Une étape dont le module est absent du dépôt est ignorée,
    # une dépendance vers une étape absente aussi.
    Etape("datapackage", "Métadonnées de réutilisation (Data Package, DCAT-AP, schema.org)", (TOUTES,),
          ("docs/datapackage",), produire=(m("datapackage"),), duree_estimee_s=30),
)


def _presentes() -> tuple[Etape, ...]:
    """Étapes dont le module existe dans le dépôt ; dépendances vers des étapes absentes retirées, TOUTES développé."""
    garde = [e for e in ETAPES if all((ROOT / c[0]).exists() for c in e.collecter + e.produire)]
    ids = [e.id for e in garde]
    sortie = []
    for e in garde:
        deps = []
        for d in e.deps:
            deps += ids[:ids.index(e.id)] if d == TOUTES else [d] if d in ids else []
        sortie.append(Etape(**{**e.__dict__, "deps": tuple(dict.fromkeys(deps))}))
    return tuple(sortie)


ETAPES = _presentes()
PAR_ID = {e.id: e for e in ETAPES}

# Refus ou indisponibilité d'une source (jamais contournés). Formats : requests (« 403 Client Error »), messages des
# modules (« HTTP 429 », « accès refusé »), urllib3 (« Max retries exceeded »), DNS, délais.
RESEAU = re.compile(
    r"\b(?:HTTP|statut|status|code)\W{0,3}(?:401|403|429|451|5\d\d)\b|\b(?:401|403|429|5\d\d) (?:Client|Server) Error"
    r"|acc[eè]s refus[eé]|serveur indisponible|erreurs serveur cons[eé]cutives|cloudflare|ConnectionError"
    r"|Connect(?:ion)?Timeout|ReadTimeout|timed out|Max retries exceeded|Temporary failure in name resolution"
    r"|Name or service not known|Connection (?:reset|refused|aborted)|RemoteDisconnected|ChunkedEncodingError"
    r"|IncompleteRead|SSLError|ProxyError", re.I)
# Entrée absente de l'entrepôt (runner sans data/lake ou source non collectée).
ENTREE_ABSENTE = re.compile(r"FileNotFoundError|No such file or directory|sources? absentes? de data/lake"
                            r"|aucun jaune dans data/lake|No files found that match|data/lake/\S+ (?:absent|introuvable)"
                            r"|lancer .?collecter|absente? : lancer|cache \S+ absent|lancer la collecte", re.I)


def maintenant() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ordre(ids: list[str] | None = None) -> list[Etape]:
    """Ordre topologique (stable : ordre de déclaration à égalité) ; erreur si cycle ou dépendance inconnue."""
    vus, sortie, en_cours = set(), [], set()

    def visiter(e: Etape) -> None:
        if e.id in vus:
            return
        if e.id in en_cours:
            raise SystemExit(f"cycle de dépendances autour de {e.id}")
        en_cours.add(e.id)
        for d in e.deps:
            if d not in PAR_ID:
                raise SystemExit(f"{e.id} dépend de {d}, étape inconnue")
            visiter(PAR_ID[d])
        en_cours.discard(e.id)
        vus.add(e.id)
        sortie.append(e)

    for e in ETAPES:
        visiter(e)
    if ids:
        inconnues = set(ids) - set(PAR_ID)
        if inconnues:
            raise SystemExit(f"étapes inconnues : {sorted(inconnues)} ; connues : {list(PAR_ID)}")
        sortie = [e for e in sortie if e.id in ids]
    return sortie


def empreinte_code(e: Etape) -> str:
    """Empreinte du code de l'étape (modules appelés et modules importés du dossier pipeline/) : la reprise ne saute
    une étape réussie que si ce code n'a pas changé."""
    h = hashlib.sha256()
    for f in sorted({c[0] for c in e.collecter + e.produire} | {"pipeline/reproductible.py", "pipeline/sirene.py",
                                                               "pipeline/arbre.py", "pipeline/fetch.py"}):
        p = ROOT / f
        if p.exists():
            h.update(f.encode() + b"\0" + p.read_bytes())
    h.update(json.dumps([e.collecter, e.produire, e.deps]).encode())
    return h.hexdigest()[:16]


# --- Sauvegarde et restauration des sorties d'une étape ---------------------------------------------------------

def sauvegarder(e: Etape, dossier: Path) -> None:
    for rel in e.sorties:
        src, dst = ROOT / rel, dossier / rel
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("_restreint", "__pycache__"))
        elif src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def restaurer(e: Etape, dossier: Path) -> None:
    """Remet les sorties dans l'état d'avant l'étape (fichiers ajoutés par l'étape supprimés)."""
    for rel in e.sorties:
        cible, copie = ROOT / rel, dossier / rel
        if cible.is_dir():
            garde = cible / "_restreint"
            for x in cible.iterdir():
                if x != garde:
                    shutil.rmtree(x) if x.is_dir() else x.unlink()
            if copie.is_dir():
                shutil.copytree(copie, cible, dirs_exist_ok=True)
        else:
            if cible.exists():
                cible.unlink()
            if copie.exists():
                cible.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(copie, cible)


# --- Exécution d'une commande ------------------------------------------------------------------------------------

@dataclass
class Resultat:
    code: int
    duree_s: float
    reseau: list[str] = field(default_factory=list)
    entree_absente: list[str] = field(default_factory=list)
    fin: list[str] = field(default_factory=list)


def executer(cmd: tuple[str, ...], duree_max_s: float, prefixe: str, trace: Path | None = None) -> Resultat:
    argv = [PY, "-u", *cmd]
    if trace is not None:
        argv = ["strace", "-f", "-qq", "-e", "trace=open,openat,execve", "-o", str(trace), *argv]
    debut = time.monotonic()
    fin, reseau, absente = deque(maxlen=40), [], []
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    with subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace", env=env) as p:
        assert p.stdout is not None
        import threading
        minuteur = threading.Timer(duree_max_s, p.kill)
        minuteur.start()
        try:
            for ligne in p.stdout:
                ligne = ligne.rstrip("\n")
                print(f"{prefixe} {ligne}", flush=True)
                fin.append(ligne)
                if RESEAU.search(ligne) and len(reseau) < 20:
                    reseau.append(ligne.strip()[:300])
                if ENTREE_ABSENTE.search(ligne) and len(absente) < 20:
                    absente.append(ligne.strip()[:300])
            code = p.wait()
        finally:
            minuteur.cancel()
    duree = time.monotonic() - debut
    if code < 0 or duree >= duree_max_s:
        reseau.append(f"commande arrêtée après {int(duree)} s (délai maximal {int(duree_max_s)} s)")
    return Resultat(code, round(duree, 1), reseau, absente, list(fin))


# --- Une étape ---------------------------------------------------------------------------------------------------

def lancer_etape(e: Etape, a: argparse.Namespace, fin_budget: float, trace_dir: Path | None) -> dict:
    """Statuts : produit, partiel (passage reprenable non terminé), conserve (sorties précédentes gardées : source
    inaccessible ou entrée absente), echec (erreur de code ou de donnée : sortie non nulle), reporte (budget)."""
    r = {"etape": e.id, "titre": e.titre, "statut": None, "motif": None, "sources_inaccessibles": [],
         "commandes": [], "duree_s": 0.0}
    debut = time.monotonic()
    if time.monotonic() + min(e.duree_estimee_s, 600) > fin_budget:
        r.update(statut="reporte", motif="budget de temps du passage épuisé : sorties précédentes conservées")
        return r
    with tempfile.TemporaryDirectory(prefix=f"tout_{e.id}_") as tmp:
        copie = Path(tmp)
        sauvegarder(e, copie)
        # 1. Collecte (réseau). Une source inaccessible n'arrête pas l'étape : la production tourne sur le cache.
        if not a.sans_reseau:
            for cmd in e.collecter:
                res = executer(cmd, min(e.duree_max_s, max(60.0, fin_budget - time.monotonic())), f"[{e.id}]")
                r["commandes"].append({"commande": " ".join(cmd), "code": res.code, "duree_s": res.duree_s})
                if res.code == 0:
                    for l in res.reseau:   # refus noté par le module sans échec (ex. niches : budget.gouv.fr 403)
                        if re.search(r"refus|403|429|inaccessible|non contourn", l, re.I):
                            r["sources_inaccessibles"].append({"commande": " ".join(cmd), "constat": l})
                    continue
                if res.reseau or res.code < 0:
                    constat = (res.reseau or res.fin[-1:] or ["?"])[-1]
                    r["sources_inaccessibles"].append({"commande": " ".join(cmd), "constat": constat})
                    continue
                r.update(statut="echec", motif=f"collecte en erreur ({' '.join(cmd)}, code {res.code}) : "
                                               f"{(res.fin[-1:] or ['?'])[-1][:300]}")
                break
        # 2. Production (reprenable pour `local` : on relance tant que le code dit « à relancer » et qu'il reste du temps)
        if r["statut"] is None:
            for cmd in e.produire:
                while True:
                    trace = trace_dir / f"{e.id}.{len(r['commandes'])}.strace" if trace_dir else None
                    reste = fin_budget - time.monotonic()
                    res = executer(cmd, min(e.duree_max_s, max(60.0, reste)), f"[{e.id}]", trace)
                    r["commandes"].append({"commande": " ".join(cmd), "code": res.code, "duree_s": res.duree_s})
                    if e.a_relancer is not None and res.code == e.a_relancer:
                        if a.sans_reseau or fin_budget - time.monotonic() < e.duree_max_s:
                            r.update(statut="partiel", motif="passage reprenable non terminé (sorties cumulées "
                                                             "gardées ; le passage suivant continue)")
                            break
                        continue
                    break
                if r["statut"] == "partiel":
                    break
                if res.code != 0:
                    if res.entree_absente and not res.reseau:
                        r.update(statut="conserve", motif="entrée absente de l'entrepôt data/lake : "
                                                          + res.entree_absente[-1][:300])
                    elif res.reseau:
                        r.update(statut="conserve", motif="source inaccessible pendant la production : "
                                                          + res.reseau[-1][:300])
                        r["sources_inaccessibles"].append({"commande": " ".join(cmd), "constat": res.reseau[-1]})
                    else:
                        r.update(statut="echec", motif=f"production en erreur ({' '.join(cmd)}, code {res.code}) : "
                                                       f"{(res.fin[-1:] or ['?'])[-1][:300]}")
                    break
        if r["statut"] in ("echec", "conserve"):
            restaurer(e, copie)
            r["motif"] += " ; dernière version publiée conservée"
        elif r["statut"] is None:
            r["statut"] = "produit"
    r["duree_s"] = round(time.monotonic() - debut, 1)
    return r


# --- Rapport -------------------------------------------------------------------------------------------------------

def ecrire_rapport(resultats: list[dict], a: argparse.Namespace) -> None:
    """site/data/mise_a_jour.json : déterministe hors `genere_le` (ni durée ni code de sortie)."""
    precedent = {}
    if RAPPORT.exists():
        try:
            precedent = {x["etape"]: x for x in json.loads(RAPPORT.read_text(encoding="utf-8"))["etapes"]}
        except (ValueError, KeyError):
            precedent = {}
    faits = {x["etape"]: x for x in resultats}
    etapes = []
    for e in ordre():
        x = faits.get(e.id)
        if x is None:   # étape non lancée ce passage (--etapes) : ligne précédente gardée
            if e.id in precedent:
                etapes.append(precedent[e.id])
            continue
        sources = sorted({(s["commande"], s["constat"]) for s in x["sources_inaccessibles"]})
        etapes.append({"etape": e.id, "titre": e.titre, "dependances": list(e.deps),
                       "sorties": [s.removeprefix("site/data/") for s in e.sorties if s.startswith("site/data/")],
                       "statut": x["statut"], "motif": x["motif"],
                       "sources_inaccessibles": [{"commande": c, "constat": k} for c, k in sources]})
    doc = {"millesime": "Dernier passage de la mise à jour automatique",
           "source": "pipeline/tout.py (workflow .github/workflows/data.yml)",
           "genere_le": maintenant(), "mode": "sans réseau" if a.sans_reseau else "complet",
           "statuts": {"produit": "sorties régénérées ce passage",
                       "partiel": "passage reprenable non terminé ; sorties déjà produites gardées",
                       "conserve": "source inaccessible ou entrée absente : dernière version publiée gardée",
                       "echec": "erreur : dernière version publiée gardée, le passage sort en erreur",
                       "reporte": "budget de temps épuisé : dernière version publiée gardée"},
           "etapes": etapes}
    RAPPORT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def resume_markdown(resultats: list[dict], total_s: float) -> str:
    l = ["| Étape | Statut | Durée | Motif |", "|---|---|---:|---|"]
    for x in resultats:
        motif = (x["motif"] or "").replace("|", "/")[:160]
        if x["sources_inaccessibles"]:
            motif += f" ({len(x['sources_inaccessibles'])} source(s) inaccessible(s))"
        l.append(f"| {x['etape']} | {x['statut']} | {x['duree_s']:.0f} s | {motif} |")
    return f"### Mise à jour des données : {total_s / 60:.1f} min\n\n" + "\n".join(l) + "\n"


def passage(a: argparse.Namespace) -> int:
    ids = [s for s in (a.etapes or "").split(",") if s] or None
    etapes = ordre(ids)
    ETAT_DIR.mkdir(parents=True, exist_ok=True)
    etat_path = ETAT_DIR / "etat.json"
    etat = json.loads(etat_path.read_text(encoding="utf-8")) if a.reprendre and etat_path.exists() else {}
    debut = time.monotonic()
    fin_budget = debut + a.budget
    trace_dir = None
    if a.tracer:
        trace_dir = Path(a.tracer)
        trace_dir.mkdir(parents=True, exist_ok=True)
    resultats, en_echec = [], set()
    for e in etapes:
        emp = empreinte_code(e)
        if a.reprendre and etat.get(e.id, {}).get("empreinte") == emp and etat[e.id].get("statut") == "produit":
            print(f"== {e.id} : déjà produit au passage précédent (reprise), sauté", flush=True)
            continue
        print(f"== {e.id} : {e.titre}", flush=True)
        r = lancer_etape(e, a, fin_budget, trace_dir)
        bloquantes = [d for d in e.deps if d in en_echec]
        if bloquantes:
            r["motif"] = ((r["motif"] or "") + f" (dépendance en échec : {', '.join(bloquantes)}, "
                                               "version publiée utilisée)").strip()
        if r["statut"] == "echec":
            en_echec.add(e.id)
        print(f"== {e.id} : {r['statut']} en {r['duree_s']:.0f} s" + (f" ; {r['motif']}" if r["motif"] else ""),
              flush=True)
        resultats.append(r)
        etat[e.id] = {"statut": r["statut"], "empreinte": emp, "le": maintenant()}
        etat_path.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    total = time.monotonic() - debut
    ecrire_rapport(resultats, a)
    journal = {"debut": maintenant(), "duree_s": round(total, 1), "mode": "sans réseau" if a.sans_reseau else "complet",
               "etapes": resultats}
    (ETAT_DIR / "journal.json").write_text(json.dumps(journal, ensure_ascii=False, indent=1), encoding="utf-8")
    md = resume_markdown(resultats, total)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md)
    return 1 if en_echec else 0


# --- Entrepôt : sources du catalogue lues par les étapes ----------------------------------------------------------

UA = "ou-vont-mes-impots-collecte/0.3 (projet citoyen open source, collecte de donnees ouvertes)"


def entrepot(a: argparse.Namespace) -> int:
    """Complète data/lake avec les seuls fichiers lus par les étapes (pipeline/entrees_lac.json : chemin et URL
    publique relevés dans le manifeste de collecte), pas des sources entières : une source comme le REI publie vingt
    millésimes, le pipeline n'en lit qu'un. --rafraichir : retélécharge aussi les fichiers présents ; un contenu
    identique (sha256) est gardé tel quel et sa date de collecte ne bouge pas (sorties reproductibles, pas de commit).
    Un refus (401, 403, 429, 451) ou une indisponibilité est noté, jamais contourné : l'étape concernée sera
    « conservée ». La taille réelle de data/lake est bornée (--plafond-go)."""
    import fcntl
    import requests
    entrees = json.loads(ENTREES.read_text(encoding="utf-8"))
    ids = [s for s in (a.etapes or "").split(",") if s] or list(entrees["etapes"])
    fichiers = {}   # chemin -> identifiant de source
    for eid in ids:
        for sid, chemins in entrees["etapes"].get(eid, {}).get("sources", {}).items():
            for c in chemins:
                fichiers[c] = sid
    urls = entrees.get("urls", {})
    cibles = sorted(c for c in fichiers if a.rafraichir or not (ROOT / c).exists())
    print(f"entrepôt : {len(fichiers)} fichiers lus par les étapes, "
          f"{sum(1 for c in fichiers if not (ROOT / c).exists())} absents, {len(cibles)} à télécharger", flush=True)
    debut, faits, refus = time.monotonic(), {}, []
    taille = [sum(f.stat().st_size for f in LAKE.rglob("*") if f.is_file()) if LAKE.exists() else 0]
    import threading
    from concurrent.futures import ThreadPoolExecutor
    verrou = threading.Lock()

    def telecharger(n: int, c: str) -> None:
        url = urls.get(c)
        if not url:
            refus.append(f"{c} : aucune URL relevée")
            return
        if time.monotonic() - debut > a.budget:
            refus.append(f"{c} : budget de temps épuisé")
            return
        if taille[0] > a.plafond_go * 1e9:
            refus.append(f"{c} : entrepôt à {taille[0] / 1e9:.1f} Go, plafond {a.plafond_go} Go")
            return
        cible = ROOT / c
        part = cible.with_name(cible.name + ".part")
        cible.parent.mkdir(parents=True, exist_ok=True)
        h, octets, erreur = hashlib.sha256(), 0, None
        for essai in range(4):
            try:
                with requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=(30, 300)) as r:
                    if r.status_code in (401, 403, 429, 451):
                        erreur = f"HTTP {r.status_code} (accès refusé, non contourné)"
                        break
                    r.raise_for_status()
                    attendu = int(r.headers.get("Content-Length") or 0) if not r.headers.get("Content-Encoding") else 0
                    h, octets = hashlib.sha256(), 0
                    with part.open("wb") as f:
                        for bloc in r.iter_content(1 << 20):
                            f.write(bloc)
                            h.update(bloc)
                            octets += len(bloc)
                if attendu and octets != attendu:   # transfert tronqué : on recommence, rien n'est publié
                    raise requests.ConnectionError(f"transfert tronqué ({octets} octets sur {attendu})")
                erreur = None
                break
            except requests.RequestException as exc:
                erreur = f"{type(exc).__name__} : {str(exc)[:200]}"
                time.sleep(2 ** (essai + 1))
        if erreur:
            part.unlink(missing_ok=True)
            refus.append(f"{c} : {url} : {erreur}")
            print(f"[entrepot] REFUS {c} : {erreur}", flush=True)
            return
        sha = h.hexdigest()
        if cible.exists() and hashlib.sha256(cible.read_bytes()).hexdigest() == sha:
            part.unlink()
            print(f"[entrepot] {n}/{len(cibles)} inchangé {c}", flush=True)
            return
        with verrou:
            taille[0] += octets - (cible.stat().st_size if cible.exists() else 0)
            faits[c] = {"url": url, "sha256": sha, "octets": octets}
        os.replace(part, cible)
        print(f"[entrepot] {n}/{len(cibles)} {octets / 1e6:8.1f} Mo {c}", flush=True)

    # Quatre téléchargements en parallèle, au plus un par serveur à la fois (les exports ODS sont lents à générer
    # et un portail public ne doit pas recevoir de rafale) : un fil par hôte, quatre hôtes en même temps.
    from urllib.parse import urlsplit
    par_hote: dict[str, list[tuple[int, str]]] = {}
    for n, c in enumerate(cibles, 1):
        par_hote.setdefault(urlsplit(urls.get(c) or "").netloc, []).append((n, c))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda lot: [telecharger(n, c) for n, c in lot], par_hote.values()))
    # Manifeste : date de collecte des seules sources dont un fichier a changé (pipeline/reproductible.py la lit).
    if faits:
        LAKE.mkdir(parents=True, exist_ok=True)
        with open(LAKE / "manifest.json.lock", "w") as verrou:
            fcntl.flock(verrou, fcntl.LOCK_EX)
            mpath = LAKE / "manifest.json"
            man = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
            for c, info in faits.items():
                sid = fichiers[c]
                e = man.setdefault(sid, {"domaine": c.split("/")[3 if c.startswith("data/lake/_restreint/") else 2],
                                         "statut": "ok", "fichiers": []})
                e["collecte_le"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                e["zone"] = "restreinte" if c.startswith("data/lake/_restreint/") else "publique"
                e["fichiers"] = [f for f in e.get("fichiers", []) if f.get("chemin") != c] + [
                    {"chemin": c, "change": True, "origine": "pipeline/tout.py entrepot", **info}]
            tmp = mpath.with_name("manifest.json.tmp")
            tmp.write_text(json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, mpath)
    print(f"entrepôt : {len(faits)} fichiers écrits, {len(refus)} non obtenus ({time.monotonic() - debut:.0f} s)",
          flush=True)
    for x in refus[:30]:
        print(f"  non obtenu : {x}", flush=True)
    return 0


def inventorier(a: argparse.Namespace) -> int:
    """Relève, sous strace, les fichiers de data/lake ouverts par la production de chaque étape (sans réseau), puis
    les rattache aux sources du manifeste. Les caches de modules (data/lake/_cache) sont listés par dossier."""
    if not shutil.which("strace"):
        raise SystemExit("strace requis pour inventorier")
    a.sans_reseau, a.reprendre = True, False
    tmp = Path(tempfile.mkdtemp(prefix="tout_strace_"))
    a.tracer = str(tmp)
    code = passage(a)
    manifeste = json.loads((LAKE / "manifest.json").read_text(encoding="utf-8"))
    par_chemin = {f["chemin"]: sid for sid, ent in manifeste.items() if isinstance(ent, dict)
                  for f in ent.get("fichiers", []) if f.get("chemin")}
    urls_manifeste = {f["chemin"]: f.get("url") for ent in manifeste.values() if isinstance(ent, dict)
                      for f in ent.get("fichiers", []) if f.get("chemin")}
    motif = re.compile(r'"(' + re.escape(str(LAKE)) + r'/[^"]+)"')
    sortie = {"note": "Fichiers de data/lake lus par la production de chaque étape (python pipeline/tout.py "
                      "inventorier, sous strace). `sources` : identifiants du catalogue (collecte/collecte.py) et "
                      "chemins ; `caches` : dossiers remplis par les commandes de collecte des modules ; "
                      "`hors_catalogue` : fichiers déposés par la collecte d'un module.",
              "releve_le": maintenant()[:10], "etapes": {}}
    if ENTREES.exists():   # relevé partiel (--etapes) : les autres étapes gardent leur relevé précédent
        sortie["etapes"] = json.loads(ENTREES.read_text(encoding="utf-8")).get("etapes", {})
    for e in ordre([s for s in (a.etapes or "").split(",") if s] or None):
        lus = set()
        for f in tmp.glob(f"{e.id}.*.strace"):
            for ligne in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if "ENOENT" in ligne or "O_DIRECTORY" in ligne:
                    continue
                for x in motif.findall(ligne):
                    p = Path(x)
                    if p.is_file():
                        lus.add(str(p.relative_to(ROOT)))
        sources, caches, hors = {}, set(), set()
        for c in sorted(lus):
            if c.endswith((".lock", "manifest.json")):
                continue
            if c in par_chemin:
                sources.setdefault(par_chemin[c], []).append(c)
            elif c.startswith("data/lake/_cache/"):
                caches.add("/".join(c.split("/")[:4]) if c.count("/") > 3 else c)
            else:
                hors.add(c if "/" not in c[len("data/lake/"):] else "/".join(c.split("/")[:4]))
        octets = sum((ROOT / c).stat().st_size for v in sources.values() for c in v)
        sortie["etapes"][e.id] = {"sources": sources, "caches": sorted(caches), "hors_catalogue": sorted(hors),
                                  "octets_sources": octets}
        for v in sources.values():
            for c in v:
                sortie.setdefault("urls", {})[c] = urls_manifeste.get(c)
    sortie["etapes"] = {e.id: sortie["etapes"][e.id] for e in ordre() if e.id in sortie["etapes"]}
    sortie["urls"] = {**json.loads(ENTREES.read_text(encoding="utf-8")).get("urls", {}), **sortie.get("urls", {})} \
        if ENTREES.exists() else sortie.get("urls", {})
    sortie["urls"] = dict(sorted(sortie["urls"].items()))
    ENTREES.write_text(json.dumps(sortie, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{ENTREES.relative_to(ROOT)} écrit")
    return code


# --- Changements publiables ---------------------------------------------------------------------------------------

def changements(a: argparse.Namespace) -> int:
    """Code 0 (et liste) si une donnée versionnée a changé ; 1 si rien, ou seulement `genere_le` de meta.json et de
    mise_a_jour.json (ni l'horodatage ni le rapport de passage ne déclenchent un commit à eux seuls)."""
    chemins = ["data/raw", "data/processed", "site/data"]   # docs/datapackage suit les données, jamais seul
    sortie = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", *chemins], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.splitlines()
    fichiers = sorted(l[3:].strip('"') for l in sortie if l.strip())
    reels = []
    for f in fichiers:
        if f in ("site/data/meta.json", "site/data/mise_a_jour.json"):
            avant = subprocess.run(["git", "show", f"HEAD:{f}"], cwd=ROOT, capture_output=True, text=True)
            if avant.returncode == 0:
                try:
                    x, y = json.loads(avant.stdout), json.loads((ROOT / f).read_text(encoding="utf-8"))
                except ValueError:
                    reels.append(f)
                    continue
                x.pop("genere_le", None)
                y.pop("genere_le", None)
                if f == "site/data/mise_a_jour.json" or x == y:
                    continue   # rapport de passage : jamais à lui seul une raison de committer
            reels.append(f)
        else:
            reels.append(f)
    for f in reels:
        print(f)
    return 0 if reels else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("commande", nargs="?", default="passage",
                    choices=["passage", "entrepot", "inventorier", "changements"])
    ap.add_argument("--etapes", help="identifiants séparés par des virgules (défaut : toutes)")
    ap.add_argument("--sans-reseau", action="store_true", help="ne lance pas les commandes de collecte")
    ap.add_argument("--reprendre", action="store_true", help="saute les étapes produites au passage précédent")
    ap.add_argument("--budget", type=float, default=5 * 3600, help="durée maximale du passage, en secondes")
    ap.add_argument("--rafraichir", action="store_true", help="entrepot : recollecter toutes les sources lues")
    ap.add_argument("--plafond-go", type=float, default=10, help="entrepot : taille maximale de data/lake sur disque")
    ap.add_argument("--plan", action="store_true", help="affiche l'ordre et les dépendances, sans rien lancer")
    ap.add_argument("--tracer", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.plan:
        total = 0
        for e in ordre([s for s in (a.etapes or "").split(",") if s] or None):
            total += e.duree_estimee_s
            print(f"{e.id:14} <- {', '.join(e.deps) or '(aucune)':55} ~{e.duree_estimee_s / 60:4.0f} min")
        print(f"durée estimée, cache chaud : {total / 60:.0f} min")
        return 0
    return {"passage": passage, "entrepot": entrepot, "inventorier": inventorier, "changements": changements}[
        a.commande](a)


if __name__ == "__main__":
    sys.exit(main())
