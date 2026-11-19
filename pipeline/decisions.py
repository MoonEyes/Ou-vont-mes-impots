"""Décisions qui ont voté ou modifié les crédits de chaque programme du budget de l'État.

Entrées (entrepôt local data/lake/, non versionné) :
  decisions/decisions_an_l17_amendements.zip, _scrutins.zip, _dossiers.zip, _deputes.zip   Assemblée nationale (L17)
  decisions/decisions_senat_ameli.zip                                                       Sénat, base Ameli (dump SQL)
  decisions/decisions_jorf_global/*.tar.gz, decisions_jorf_increments/*.tar.gz              Journal officiel (DILA)
  etat/realisations/annexe1_etat_cp_2023.csv, _2024.csv, etat/etat_plrg_2025/              PLRG (annexe 1 état CP)
  etat/*budget*vert*.parquet                                                                nomenclature des programmes
Sorties (site/data/decisions/, chaque fichier < 5 Mo) :
  programme_<n>.json      chronologie par année : LFI votée, amendements adoptés, décrets et arrêtés en gestion, LFR,
                          reports, exécution, contrôle JO / PLRG
  amendements_resume.json par programme et par année : déposés, adoptés, montant net adopté (AN, Sénat)
  scrutins.json           scrutins publics de l'Assemblée sur les lois de finances (ensemble, parties, articles,
                          crédits, amendements de crédits)
  mouvements_<annee>.json décrets et arrêtés de mouvements de crédits publiés au JO (2021 à 2026), lignes par programme
  coherence_plrg.json     somme des mouvements publiés au JO comparée aux colonnes du PLRG (écart publié)
  index.json              programmes, fichiers, sources, comptes, tolérance, limites

Commandes (chacune < 9 min) :
  python pipeline/decisions.py jorf       # lit l'archive JORF en flux, garde les textes de mouvements de crédits
                                          # (filtre sur le titre) dans data/lake/_cache/decisions_jorf/
  python pipeline/decisions.py produire   # sans réseau : écrit site/data/decisions/
  python pipeline/decisions.py plrg       # sans réseau, sans archive JORF : recale les seuls champs tirés du PLRG
                                          # dans les fiches publiées (régénération ciblée)
  python pipeline/decisions.py auteurs    # sans réseau, sans archive JORF : rétablit les noms d'auteurs et les
                                          # objets de scrutins effacés avant le 19/11/2026 (régénération ciblée)

Montants : une cellule vide vaut 0 ; une valeur non vide illisible devient null avec sa raison
(`valeurs_illisibles_plrg`), jamais 0 ; une valeur en notation scientifique (PLRG 2023, programme 200) est lue et
signalée (`precision_plrg`). `produire` et `plrg` s'arrêtent si LFI, crédits ouverts ou dépenses diffèrent de
site/data/realisations/<n>.json de plus de 1 €.

Personnes : seuls les élus (députés, sénateurs) et le Gouvernement sont nommés comme auteurs ; aucune autre donnée
personnelle n'est lue ni écrite (pas de date de naissance, d'adresse, de profession). Décision du propriétaire du
19/11/2026 : un élu qui a été candidat à une élection nationale est nommé comme les autres (auteur, objet du scrutin
tel que publié) ; rien d'autre n'est écrit sur lui.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import html
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
DEC = LAKE / "decisions"
ETAT = LAKE / "etat"
CACHE_JORF = LAKE / "_cache" / "decisions_jorf"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "decisions"

AN_AMDTS = DEC / "decisions_an_l17_amendements.zip"
AN_SCRUTINS = DEC / "decisions_an_l17_scrutins.zip"
AN_DOSSIERS = DEC / "decisions_an_l17_dossiers.zip"
AN_DEPUTES = DEC / "decisions_an_l17_deputes.zip"
SENAT_AMELI = DEC / "decisions_senat_ameli.zip"
JORF_GLOBAL = DEC / "decisions_jorf_global"
JORF_INCR = DEC / "decisions_jorf_increments"

SRC_AN = "data.assemblee-nationale.fr, 17e législature : amendements, scrutins, dossiers législatifs, acteurs"
SRC_SENAT = "data.senat.fr, base Ameli (amendements, dump SQL lu sans PostgreSQL : blocs COPY)"
SRC_AMDT = f"{SRC_AN} ; {SRC_SENAT}"
SRC_JORF = "DILA, archive JORF (echanges.dila.gouv.fr, Freemium_jorf_global et incréments)"
SRC_PLRG = "data.economie.gouv.fr, PLRG {a} (annexe 1 « état CP » : LFI, LFR, reports, mouvements réglementaires, dépenses)"

ANNEES_MOUVEMENTS = range(2021, 2027)
TOLERANCE_PCT = 1.0  # écart toléré entre JO et PLRG, en % de la somme des valeurs absolues des mouvements de l'année
TOLERANCE_EUR = 1_000.0  # par programme : écart d'arrondi accepté

# --- Utilitaires ---------------------------------------------------------------------------------------------------


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 5_000_000:
        raise SystemExit(f"{path} dépasse 5 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def propre(v) -> str:
    if v is None:
        return ""
    s = html.unescape(str(v))
    s = unicodedata.normalize("NFC", s).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def norm(s) -> str:
    """Clé de comparaison de libellés : minuscules, sans accents ni ponctuation ni mentions entre parenthèses."""
    s = propre(s).lower().replace("’", "'").replace("œ", "oe")
    s = re.sub(r"\((?:cr[ée]dits [ée]valuatifs|libell[ée] modifi[ée]|nouveau|ligne nouvelle)\)", " ", s)
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


SCI_RE = re.compile(r"^[+]?(-?\d+(?:\.\d+)?)[eE]([+-]?\d+)$")


def lecture_montant(v) -> tuple[float | None, str | None]:
    """(valeur en euros ou None, remarque ou None).

    Cellule vide ou absente : 0.0 (aucun montant publié sur la ligne). Valeur non vide illisible : None et la raison,
    jamais 0. Notation scientifique d'un tableur (« 1,27055E+11 ») : lue, avec la remarque d'arrondi (la source ne
    garde que les chiffres significatifs écrits)."""
    if v is None or nil(v):
        return 0.0, None
    if isinstance(v, bool):
        return None, f"valeur illisible dans la source : « {v} »"
    if isinstance(v, (int, float)):
        return (float(v), None) if v == v else (None, "valeur illisible dans la source : « NaN »")
    s = re.sub(r"[\s\u00a0\u202f\u2009]", "", propre(v)).replace(",", ".")
    s = s.replace("−", "-").replace("–", "-")
    if s == "":
        return 0.0, None
    m = re.search(r"^[+]?(-?\d+(?:\.\d+)?)$", s)
    if m:
        return float(m.group(1)), None
    m = SCI_RE.search(s)
    if m:
        chiffres = len(m.group(1).replace("-", "").replace(".", "").lstrip("0")) or 1
        return float(f"{m.group(1)}e{m.group(2)}"), (f"valeur publiée en notation scientifique (« {propre(v)} ») : "
                                                     f"arrondie à {chiffres} chiffres significatifs dans la source")
    return None, f"valeur illisible dans la source : « {propre(v)[:40]} »"


def montant(v) -> float | None:
    """'89 753 974', '-3000000', '+ 1 000', '1,27055E+11' -> nombre (euros) ; '' ou None -> 0.0 (cellule vide) ;
    valeur non vide illisible -> None, jamais 0 (la raison est donnée par `lecture_montant`)."""
    return lecture_montant(v)[0]


def montant_strict(v, contexte: str) -> float:
    """Montant d'une ligne qui entre dans une somme : une valeur illisible arrête la production (jamais 0)."""
    x, raison = lecture_montant(v)
    if x is None:
        raise SystemExit(f"{contexte} : {raison}")
    return x


def nil(v) -> bool:
    return v is None or (isinstance(v, dict) and v.get("@xsi:nil") == "true")


def listify(v) -> list:
    if nil(v):
        return []
    return v if isinstance(v, list) else [v]


# --- Nomenclature des programmes (libellé -> code) -----------------------------------------------------------------


def _plrg_fichiers() -> dict[int, Path]:
    return {2023: ETAT / "realisations" / "annexe1_etat_cp_2023.csv",
            2024: ETAT / "realisations" / "annexe1_etat_cp_2024.csv",
            2025: ETAT / "etat_plrg_2025" / "Annexe1-Etat_CP-2025.csv"}


PLRG_COLS = {"LFI": "lfi", "LFR": "lfr", "Report_N-1": "reports_entrants",
             "Mvts_reglementaires": "mouvements_reglementaires", "FDC_et_ADP": "fonds_de_concours",
             "Total_CP_Ouverts": "ouverts", "Depenses_constatees": "depenses"}


def lire_plrg() -> dict[int, dict[str, dict]]:
    """{annee: {programme: {lfi, lfr, reports, mouvements, fdc, ouverts, depenses, libelle, mission, illisibles,
    precision}}}. Un montant illisible sur une ligne rend la colonne du programme None (`illisibles[colonne]` dit
    pourquoi) ; un montant en notation scientifique est lu et signalé dans `precision[colonne]`."""
    out = {}
    for a, f in _plrg_fichiers().items():
        if not f.exists():
            continue
        d = {}
        lignes = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8-sig")), delimiter=";"))
        manquantes = (set(PLRG_COLS) | {"Mission", "Programme"}) - set(lignes[0] if lignes else [])
        if manquantes:
            raise SystemExit(f"{f} : colonnes manquantes {sorted(manquantes)}")
        for r in lignes:
            m = re.search(r"(\d{3})\s*$", r["Programme"])
            if not m:
                continue
            p = m.group(1)
            e = d.setdefault(p, {**{k: 0.0 for k in PLRG_COLS.values()}, "illisibles": {}, "precision": {}})
            e["libelle"] = propre(re.sub(r"\s*-\s*\d{3}\s*$", "", r["Programme"]))
            e["mission"] = propre(r["Mission"])
            for c, k in PLRG_COLS.items():
                x, remarque = lecture_montant(r.get(c))
                if x is None:
                    e[k] = None
                    e["illisibles"][k] = remarque
                    continue
                if remarque:
                    e["precision"][k] = remarque
                if e[k] is not None:
                    e[k] += x
        out[a] = d
    return out


CHAMPS_PLRG = (("lfi_cp", "lfi"), ("lfr_cp", "lfr"), ("reports_entrants_cp", "reports_entrants"),
               ("mouvements_reglementaires_plrg_cp", "mouvements_reglementaires"),
               ("fonds_de_concours_plrg_cp", "fonds_de_concours"), ("ouverts_cp", "ouverts"),
               ("depenses_cp", "depenses"))
ETAPE_LFI, ETAPE_LFR, ETAPE_EXEC = "LFI votée", "Loi de finances rectificative ou de fin de gestion", "Exécution"


def bloc_plrg(x: dict, a: int) -> dict:
    """Champs PLRG d'une année de la fiche programme ; un montant illisible est null avec sa raison."""
    e = {champ: x[k] for champ, k in CHAMPS_PLRG}
    e["source_plrg"] = SRC_PLRG.format(a=a)
    illisibles = {champ: x["illisibles"][k] for champ, k in CHAMPS_PLRG if k in x["illisibles"]}
    if illisibles:
        e["valeurs_illisibles_plrg"] = illisibles
    precision = {champ: x["precision"][k] for champ, k in CHAMPS_PLRG if k in x["precision"] and x[k] is not None}
    if precision:
        e["precision_plrg"] = precision
    return e


def etapes_plrg(x: dict, a: int) -> list[dict]:
    """Étapes de la chronologie tirées du PLRG : LFI votée, LFR (si non nulle), exécution."""
    def etape(date: str, nom: str, k: str) -> dict:
        c = {"date": date, "annee": a, "etape": nom, "cp": x[k], "source": SRC_PLRG.format(a=a)}
        if x[k] is None:
            c["raison"] = x["illisibles"][k]
        elif k in x["precision"]:
            c["precision"] = x["precision"][k]
        return c
    out = [etape(f"{a}-01-01", ETAPE_LFI, "lfi")]
    if x["lfr"] or x["lfr"] is None:
        out.append(etape(f"{a}-12-01", ETAPE_LFR, "lfr"))
    out.append(etape(f"{a}-12-31", ETAPE_EXEC, "depenses"))
    return out


def nomenclature() -> dict:
    """Entrées (mission, libellé, code) de toutes les sources disponibles (PLRG 2023-2025, budgets verts, arbres).

    Ordre de priorité déterministe : PLRG du plus récent au plus ancien, puis budgets verts (fichiers du plus récent
    au plus ancien), puis arbres du site, puis alias. Pour un même code ou un même (mission, libellé), la première
    entrée gagne : jamais l'ordre d'itération d'un ensemble, qui varie d'un processus à l'autre."""
    entrees: list[tuple] = []
    plrg = lire_plrg()
    for a in sorted(plrg, reverse=True):
        for p, e in sorted(plrg[a].items()):
            entrees.append((e["mission"], e["libelle"], p))
    try:
        import duckdb
        for f in sorted(set(ETAT.glob("*budget*vert*.parquet")) | set(ETAT.glob("*budgetvert*.parquet")), reverse=True):
            try:
                rows = duckdb.sql(f"select distinct mission, numero_programme, programme from '{f}' "
                                  "where numero_programme is not null order by all").fetchall()
            except Exception:  # noqa: BLE001 (colonnes différentes selon le millésime)
                continue
            for mi, num, lib in rows:
                if lib:
                    entrees.append((propre(mi), propre(re.sub(r"^\s*\d{3}\s*[-–]\s*", "", str(lib))),
                                    str(int(num)).zfill(3)))
    except ImportError:
        pass
    for arbre in ("arbre", "arbre_lfi2025"):
        f = SITE / arbre / "racine.json"
        if not f.exists():
            continue
        for g in json.loads(f.read_text(encoding="utf-8"))["enfants"]:
            for m in g.get("enfants", []):
                for p in m.get("enfants", []):
                    if p["niveau"] == "programme":
                        entrees.append((m["nom"], p["nom"], p["id"].split("/")[-1]))
    entrees += sorted(ALIAS)
    par_mission = defaultdict(dict)
    par_lib = defaultdict(set)
    libelles = {}
    for mi, lib, code in dict.fromkeys(entrees):  # dédoublonné, ordre de priorité conservé
        par_mission[norm(mi)].setdefault(norm(lib), code)
        par_lib[norm(lib)].add(code)
        libelles.setdefault(code, lib)
    return {"par_mission": par_mission, "par_lib": par_lib, "libelles": libelles}


# Programmes absents des sources de nomenclature du lac (missions hors budget général étudiées ici, intitulés connus).
ALIAS = {("Pouvoirs publics", "Haute Cour", "532"),
         ("Pouvoirs publics", "Indemnités des représentants français au Parlement européen", "542")}


def resoudre(nomen: dict, libelle: str, mission: str | None) -> tuple[str | None, str]:
    """Code programme d'un libellé d'amendement : exact dans la mission, exact unique, puis approché (difflib)."""
    lib = norm(libelle)
    mi = norm(mission or "")
    if not lib:
        return None, "vide"
    if mi and lib in nomen["par_mission"].get(mi, {}):
        return nomen["par_mission"][mi][lib], "exact"
    if len(nomen["par_lib"].get(lib, ())) == 1:
        return next(iter(nomen["par_lib"][lib])), "exact"
    cands = nomen["par_mission"].get(mi, {}) if mi else {}
    if not cands and mi:  # mission renommée : missions proches
        proches = difflib.get_close_matches(mi, list(nomen["par_mission"]), n=1, cutoff=0.8)
        cands = nomen["par_mission"].get(proches[0], {}) if proches else {}
    best = difflib.get_close_matches(lib, list(cands), n=1, cutoff=0.85)
    if best:
        return cands[best[0]], "approche"
    best = difflib.get_close_matches(lib, list(nomen["par_lib"]), n=2, cutoff=0.92)
    if best and len(nomen["par_lib"][best[0]]) == 1:
        return next(iter(nomen["par_lib"][best[0]])), "approche"
    return None, "introuvable"


# --- a. Amendements de l'Assemblée nationale -------------------------------------------------------------------------

AN_TEXTE_RE = re.compile(r"^(?:Projet de loi de finances (pour \d{4})|Projet de loi de finances (de fin de gestion pour "
                         r"\d{4})|Projet de loi de finances (rectificative pour \d{4}))", re.I)


def dossiers_an() -> dict:
    """Dossiers des lois de finances de la législature : {dossier_uid: {texte, annee, type}}."""
    out = {}
    with zipfile.ZipFile(AN_DOSSIERS) as z:
        for n in z.namelist():
            if "dossierParlementaire" not in n:
                continue
            d = json.loads(z.read(n))["dossierParlementaire"]
            t = propre(d["titreDossier"]["titre"])
            proc = propre((d.get("procedureParlementaire") or {}).get("libelle"))
            m = re.match(r"^Projet de loi de finances (?:(de fin de gestion|rectificative) )?pour (\d{4})$", t, re.I)
            if not m or proc.startswith("Rapport") or proc.startswith("Mission"):
                continue
            typ = "PLFG" if m.group(1) and "fin" in m.group(1).lower() else ("PLFR" if m.group(1) else "PLF")
            out[d["uid"]] = {"texte": f"{typ} {m.group(2)}", "annee": int(m.group(2)), "type": typ, "titre": t}
    return out


def acteurs_an() -> tuple[dict, dict]:
    """Noms des députés ({PA: 'Prénom Nom'}) et libellés des groupes ({PO: libellé}). Rien d'autre n'est lu."""
    noms, groupes = {}, {}
    with zipfile.ZipFile(AN_DEPUTES) as z:
        for n in z.namelist():
            if "/acteur/" in n:
                a = json.loads(z.read(n))["acteur"]
                i = a["etatCivil"]["ident"]
                noms[a["uid"]["#text"] if isinstance(a["uid"], dict) else a["uid"]] = propre(f"{i['prenom']} {i['nom']}")
            elif "/organe/" in n:
                o = json.loads(z.read(n))["organe"]
                if o.get("codeType") == "GP":
                    groupes[o["uid"]] = propre(o["libelle"])
    return noms, groupes


def ae_cp(p: dict, cle: str) -> float:
    """Montant signé d'une ligne : PLF (`creditPaiement`) ou PLFR (`creditPaiementSupplementaire` + `...Annule`, négatif)."""
    ctx = f"amendement, {cle} du programme « {propre(p.get('libelle'))[:60]} »"
    if cle in p:
        return montant_strict(p.get(cle), ctx)
    return montant_strict(p.get(cle + "Supplementaire"), ctx) - abs(montant_strict(p.get(cle + "Annule"), ctx))


LIEUX_AN = {"AN": "séance", "CION_FIN": "commission des finances"}


def sort_an(a: dict) -> str:
    cv = a["cycleDeVie"]
    s = cv.get("sort")
    if isinstance(s, str) and s:
        return s
    etat = propre(((cv.get("etatDesTraitements") or {}).get("etat") or {}).get("libelle"))
    if etat.startswith("Retir"):
        return "Retiré"
    if etat.lower() in ("irrecevable", "irrecevable 40"):
        return "Irrecevable"
    return "Non examiné"


def amendements_an(nomen: dict) -> list[dict]:
    dossiers = dossiers_an()
    noms, groupes = acteurs_an()
    out = []
    with zipfile.ZipFile(AN_AMDTS) as z:
        for n in z.namelist():
            parts = n.split("/")
            if len(parts) < 4 or parts[1] not in dossiers:
                continue
            brut = z.read(n)
            if b"dispositifAmdtCreditPLF" not in brut:
                continue
            a = json.loads(brut)["amendement"]
            contenu = a["corps"]["contenuAuteur"]
            disp = contenu.get("dispositifAmdtCreditPLF")
            if nil(disp):
                disp = contenu.get("dispositifAmdtCreditPLFR")
            if nil(disp):
                continue
            dos = dossiers[parts[1]]
            mission = propre(((a.get("pointeurFragmentTexte") or {}).get("missionVisee") or {}).get("libelleMission"))
            lignes = []
            for p in listify((disp.get("listeProgrammes") or {}).get("programme")):
                lib = propre(p.get("libelle"))
                code, qualite = resoudre(nomen, lib, mission)
                creation = propre(p.get("action")).lower().startswith("cr")
                lignes.append({"programme": None if creation else code, "libelle": lib,
                               "rapprochement": "programme créé par l'amendement" if creation else qualite,
                               "ae": ae_cp(p, "autorisationEngagement"), "cp": ae_cp(p, "creditPaiement")})
            if not lignes:
                continue
            sig = a["signataires"]
            aut = sig["auteur"]
            typ = propre(aut.get("typeAuteur"))
            if typ == "Député":
                auteur = {"type": "député", "nom": noms.get(aut.get("acteurRef")),
                          "groupe": groupes.get(aut.get("groupePolitiqueRef"))}
            elif typ == "Gouvernement":
                auteur = {"type": "gouvernement", "nom": "Gouvernement", "groupe": None}
            else:  # rapporteur, commission : l'élu rapporteur est nommable
                auteur = {"type": typ.lower() or "autre", "nom": noms.get(aut.get("acteurRef")),
                          "groupe": groupes.get(aut.get("groupePolitiqueRef"))}
            cos = listify((sig.get("cosignataires") or {}).get("acteurRef"))
            ident = a["identification"]
            organe = ident.get("prefixeOrganeExamen")
            cv = a["cycleDeVie"]
            texte_num = re.search(r"B(TC)?(\d+)$", a["texteLegislatifRef"])
            out.append({
                "id": a["uid"], "chambre": "AN", "texte": dos["texte"], "annee": dos["annee"],
                "texte_ref": a["texteLegislatifRef"],
                "lecture": "commission mixte paritaire" if texte_num and texte_num.group(1) else None,
                "numero": propre(ident.get("numeroLong")), "lieu": LIEUX_AN.get(organe, "commission saisie pour avis"
                                                                                  if organe else None),
                "organe": organe, "sort": sort_an(a), "date_depot": cv.get("dateDepot"),
                "date_sort": (cv.get("dateSort") or "")[:10] if isinstance(cv.get("dateSort"), str) else None,
                "auteur": auteur, "cosignataires": len(cos), "mission": mission or None, "lignes": lignes,
                "net_ae": sum(l["ae"] for l in lignes), "net_cp": sum(l["cp"] for l in lignes),
                "url": f"https://www.assemblee-nationale.fr/dyn/17/amendements/{a['uid']}"})
    # lecture : premier texte du dossier = première lecture, suivant = nouvelle lecture
    textes = defaultdict(set)
    for x in out:
        if not x["lecture"]:
            textes[x["texte"]].add(x["texte_ref"])
    for x in out:
        if not x["lecture"]:
            refs = sorted(textes[x["texte"]], key=lambda r: int(re.search(r"(\d+)$", r).group(1)))
            x["lecture"] = "première lecture" if refs.index(x["texte_ref"]) == 0 else "nouvelle lecture"
    return out


# --- a bis. Amendements du Sénat (Ameli, blocs COPY) ----------------------------------------------------------------


def _unesc(s: str):
    if s == "\\N":
        return None
    return re.sub(r"\\(.)", lambda m: {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}.get(m.group(1), m.group(1)), s)


def lire_copy(flux, tables: set[str], filtre=None) -> dict[str, list[dict]]:
    """Lit les blocs `COPY table (cols) FROM stdin;` d'un dump PostgreSQL texte. `filtre(table, ligne_brute)` peut
    écarter une ligne avant décodage."""
    data = {t: [] for t in tables}
    cur = cols = None
    for line in flux:
        if line.startswith("COPY "):
            t = line.split()[1]
            cur = t if t in tables else None
            if cur:
                cols = [c.strip().strip('"') for c in line[line.index("(") + 1:line.index(")")].split(",")]
            continue
        if cur is None:
            continue
        if line.startswith("\\."):
            cur = None
            continue
        if filtre and not filtre(cur, line):
            continue
        data[cur].append(dict(zip(cols, [_unesc(x) for x in line.rstrip("\n").split("\t")])))
    return data


class _Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lignes, self._ligne, self._cell, self._in = [], None, None, False

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br", "div") and self._cell is not None:
            self._cell.append(" | ")
        if tag == "tr":
            self._ligne = []
        elif tag in ("td", "th") and self._ligne is not None:
            self._cell = []
            span = dict(attrs).get("colspan")
            self._span = int(span) if span and span.isdigit() else 1

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._ligne is not None:
            self._ligne.append(re.sub(r"^(?:\s*\|\s*)+|(?:\s*\|\s*)+$", "", propre(" ".join(self._cell))))
            self._ligne.extend([""] * (self._span - 1))
            self._cell = None
        elif tag == "tr" and self._ligne is not None:
            self.lignes.append(self._ligne)
            self._ligne = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


NOMBRE_RE = re.compile(r"-?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:,\d+)?|-?\d+(?:,\d+)?")


def premier_nombre(cellule: str) -> float:
    """Premier montant d'une cellule (une cellule peut porter le montant puis « dont titre 2 » sur une 2e ligne)."""
    morceau = next((x for x in (cellule or "").split("|") if re.search(r"\d", x)), "")
    m = NOMBRE_RE.search(morceau)
    return montant_strict(re.sub(r"[ \u00a0\u202f]", "", m.group(0)).replace(",", "."), "cellule de tableau") if m else 0.0


def lignes_tableau_credits(dis_html: str) -> list[dict]:
    """Tableau « Programmes | AE + | AE - | CP + | CP - » d'un dispositif d'amendement (Sénat) -> lignes signées."""
    t = _Table()
    t.feed(dis_html or "")
    out = []
    for r in t.lignes:
        if len(r) < 5:
            continue
        lib = propre(r[0].split("|")[0])
        if not lib or norm(lib) in ("programmes", "programme", "total", "totaux", "solde") or lib.startswith("dont"):
            continue
        vals = r[1:5]
        if not any(re.search(r"\d", v) for v in vals):
            continue
        aep, aem, cpp, cpm = (premier_nombre(v) for v in vals)
        lib = re.sub(r"(?i)\s*dont (?:titre 2|t2)\s*$", "", lib)
        out.append({"libelle": lib, "ae": abs(aep) - abs(aem), "cp": abs(cpp) - abs(cpm)})
    return out


def amendements_senat(nomen: dict) -> list[dict]:
    with zipfile.ZipFile(SENAT_AMELI) as z:
        nom = next(n for n in z.namelist() if n.endswith(".sql"))
        with z.open(nom) as fb:
            flux = io.TextIOWrapper(fb, encoding="latin-1")
            data = lire_copy(flux, {"txt_ameli", "ses", "sor", "sub", "amd", "amdsen", "grppol_ameli", "gvt",
                                    "com_ameli", "ent"},
                             filtre=lambda t, l: t != "amd" or "rogramme" in l)
    ses = {s["id"]: s for s in data["ses"]}
    sor = {s["id"]: s for s in data["sor"]}
    sub = {s["id"]: s for s in data["sub"]}
    grp = {g["entid"]: propre(g["libcou"]) for g in data["grppol_ameli"]}
    gvt = {g["entid"] for g in data["gvt"]} | {e["id"] for e in data["ent"] if e.get("typ") == "B"}
    com = {c["entid"]: propre(c["lib"]) for c in data["com_ameli"]}
    textes = {}
    for t in data["txt_ameli"]:
        intit = propre(t.get("int"))
        m = re.search(r"finances (?:(de fin d?e? ?gestion|rectificative) )?pour (\d{4})", intit, re.I)
        if not m or not (t.get("loifin") == "O" or "finances" in intit.lower()):
            continue
        an = int(m.group(2))
        if an < 2025:  # législature 17 de l'Assemblée : PLF 2025 et suivants, fin de gestion 2024 et suivants
            if not (m.group(1) and an == 2024):
                continue
        typ = "PLFG" if m.group(1) and "fin" in m.group(1).lower() else ("PLFR" if m.group(1) else "PLF")
        textes[t["id"]] = {"texte": f"{typ} {an}", "annee": an, "num": t.get("num"),
                           "session": (ses.get(t.get("sesinsid")) or {}).get("lil"), "lecid": t.get("lecid")}
    auteurs = defaultdict(list)
    for r in data["amdsen"]:
        auteurs[r["amdid"]].append(r)
    out = []
    for a in data["amd"]:
        tx = textes.get(a["txtid"])
        if not tx or not a.get("dis"):
            continue
        brutes = lignes_tableau_credits(a["dis"])
        if not brutes:
            continue
        s = sub.get(a.get("subid")) or {}
        mission = propre(re.sub(r"(?i)^.*?mission\s*", "", propre(s.get("lib")))) if "ission" in propre(
            s.get("lib")) else None
        lignes = []
        for l in brutes:
            code, qualite = resoudre(nomen, l["libelle"], mission)
            lignes.append({"programme": code, "libelle": l["libelle"], "rapprochement": qualite, "ae": l["ae"],
                           "cp": l["cp"]})
        so = sor.get(a.get("sorid")) or {}
        lib_sort = propre(so.get("lib")).replace("Adopté avec modification", "Adopté") or "Non examiné"
        lieu = "séance" if so.get("typ") == "S" else ("commission" if so.get("typ") == "C" else None)
        aus = sorted(auteurs.get(a["id"], []), key=lambda r: int(r.get("rng") or 99))
        if aus:
            r = aus[0]
            auteur = {"type": "sénateur", "nom": propre(f"{r.get('prenomuse') or ''} {r.get('nomuse') or ''}"),
                      "groupe": grp.get(r.get("grpid"))}
        elif a.get("nomentid") in gvt:
            auteur = {"type": "gouvernement", "nom": "Gouvernement", "groupe": None}
        elif a.get("nomentid") in com:
            auteur = {"type": "commission", "nom": com[a["nomentid"]], "groupe": None}
        else:
            auteur = {"type": "autre", "nom": None, "groupe": None}
        url = (f"https://www.senat.fr/amendements/{tx['session']}/{tx['num']}/Amdt_{a['num']}.html"
               if tx["session"] and tx["num"] and lieu == "séance" else None)
        out.append({"id": f"SENAT-{a['id']}", "chambre": "Sénat", "texte": tx["texte"], "annee": tx["annee"],
                    "texte_ref": f"Sénat n° {tx['num']} ({tx['session']})", "lecture": None,
                    "numero": a.get("num"), "lieu": lieu, "organe": None, "sort": lib_sort,
                    "date_depot": (a.get("datdep") or "")[:10] or None, "date_sort": None, "auteur": auteur,
                    "cosignataires": max(len(aus) - 1, 0), "mission": mission, "lignes": lignes,
                    "net_ae": sum(l["ae"] for l in lignes), "net_cp": sum(l["cp"] for l in lignes), "url": url})
    return out


# --- b. Scrutins de l'Assemblée sur les lois de finances --------------------------------------------------------------

SCRUTIN_RE = re.compile(r"loi de finances (?:(?:de fin de gestion|de fin des gestion|rectificative) )?pour (\d{4})", re.I)


def type_scrutin(titre: str) -> str:
    t = titre.lower()
    if "amende" in t or "sous-amendement" in t:
        return "amendement"
    if "motion" in t:
        return "motion"
    if "ensemble de la première partie" in t or "première partie" in t and "ensemble" in t:
        return "premiere_partie"
    if "ensemble de la seconde partie" in t or "seconde partie" in t and "ensemble" in t:
        return "seconde_partie"
    if t.startswith("l'ensemble") or "l'ensemble du projet" in t:
        return "ensemble"
    if "crédits de la mission" in t or "mission" in t:
        return "credits_mission"
    if "équilibre" in t:
        return "article_equilibre"
    if "article" in t:
        return "article"
    return "autre"


def scrutins_an(amendements: list[dict]) -> list[dict]:
    index_amdt = {}
    for x in amendements:
        if x["chambre"] != "AN":
            continue
        num = re.sub(r"^[IVX]+-", "", x["numero"] or "")
        index_amdt[(x["annee"], x["texte"].split()[0], num)] = x["id"]
    out = []
    with zipfile.ZipFile(AN_SCRUTINS) as z:
        for n in z.namelist():
            s = json.loads(z.read(n))["scrutin"]
            titre = propre((s.get("objet") or {}).get("libelle") or s.get("titre"))
            m = SCRUTIN_RE.search(titre)
            if not m:
                continue
            typ = type_scrutin(titre)
            texte = ("PLFG" if "fin de" in titre.lower() or "fin des" in titre.lower() else
                     "PLFR" if "rectificative" in titre.lower() else "PLF") + f" {m.group(1)}"
            amdt = None
            if typ == "amendement":
                ma = re.search(r"n[°o]\s*([A-Z]*-?\d+)", titre)
                if ma:
                    amdt = index_amdt.get((int(m.group(1)), texte.split()[0], ma.group(1)))
                if not amdt:
                    continue  # on ne garde que les scrutins sur des amendements de crédits
            dec = s["syntheseVote"]["decompte"]
            out.append({"id": s["uid"], "numero": int(s["numero"]), "date": s["dateScrutin"], "texte": texte,
                        "annee": int(m.group(1)), "type": typ, "objet": titre,
                        "resultat": propre(s["sort"]["code"]), "pour": int(dec.get("pour") or 0),
                        "contre": int(dec.get("contre") or 0), "abstentions": int(dec.get("abstentions") or 0),
                        "votants": int(s["syntheseVote"].get("nombreVotants") or 0), "amendement": amdt,
                        "url": f"https://www.assemblee-nationale.fr/dyn/17/scrutins/{s['numero']}"})
    return sorted(out, key=lambda x: x["numero"])


# --- c. Mouvements de crédits en gestion (Journal officiel, archive DILA) ---------------------------------------------

# Titres retenus : décrets d'avance, d'annulation, de virement, de transfert, de répartition, arrêtés de report et
# d'annulation. Les arrêtés d'ouverture de fonds de concours et d'attributions de produits sont hors champ (colonne
# « FDC et ADP » du PLRG, distincte des mouvements réglementaires).
TITRE_MVT = re.compile(rb"portant (?:ouverture et )?annulation de cr\xc3\xa9dits|cr\xc3\xa9dits \xc3\xa0 titre "
                       rb"d(?:'|\xe2\x80\x99)avance|portant virement de cr\xc3\xa9dits|portant transfert de cr"
                       rb"\xc3\xa9dits|portant reports? de cr\xc3\xa9dits|portant r\xc3\xa9partition de cr"
                       rb"\xc3\xa9dits|portant ouverture de cr\xc3\xa9dits", re.I)
ID_MIN_2021 = 42_700_000  # identifiants JORF (TEXT, ARTI) attribués à partir de fin 2020 (séquence commune)
ID_RE = re.compile(rb"JORF(TEXT|ARTI)(\d{12})\.xml$")


def _tar_flux(fb, garder):
    """Lecteur tar minimal en flux (ustar, noms longs GNU et pax) : `garder(nom)` décide de lire le contenu."""
    nom_long = None
    while True:
        h = fb.read(512)
        if len(h) < 512 or h == b"\0" * 512:
            return
        taille = int(h[124:136].split(b"\0")[0].strip() or b"0", 8) if h[124] < 0x80 else int.from_bytes(
            h[125:136], "big")
        typ = h[156:157]
        nom = nom_long or (h[345:500].split(b"\0")[0] + b"/" + h[0:100].split(b"\0")[0]
                           if h[257:262] == b"ustar" and h[345] else h[0:100].split(b"\0")[0])
        nom_long = None
        bloc = (taille + 511) // 512 * 512
        if typ in (b"L", b"x"):
            data = fb.read(bloc)[:taille]
            if typ == b"L":
                nom_long = data.split(b"\0")[0]
            else:
                m = re.search(rb"\d+ path=([^\n]+)\n", data)
                nom_long = m.group(1) if m else None
            continue
        if typ in (b"0", b"\0") and garder(nom):
            yield nom, fb.read(bloc)[:taille]
        else:
            restant = bloc
            while restant:
                restant -= len(fb.read(min(restant, 1 << 20)))


def scanner_jorf(archives: list[Path], budget_s: float = 540.0) -> dict:
    """Lit chaque archive JORF en flux (gzip -dc en parallèle) et garde, parmi les textes et articles publiés depuis
    2021 (identifiant >= ID_MIN_2021), ceux dont le contenu porte un titre de mouvement de crédits."""
    CACHE_JORF.mkdir(parents=True, exist_ok=True)
    etat_f = CACHE_JORF / "etat.json"
    etat = json.loads(etat_f.read_text(encoding="utf-8")) if etat_f.exists() else {"archives": {}}
    debut = time.time()

    def garder(nom: bytes) -> bool:
        m = ID_RE.search(nom)
        return bool(m) and int(m.group(2)) >= ID_MIN_2021 and (b"/texte/version/" in nom or b"/article/" in nom)

    for arch in archives:
        cle = arch.name
        if etat["archives"].get(cle, {}).get("termine"):
            continue
        n = gardes = 0
        p = subprocess.Popen(["gzip", "-dc", str(arch)], stdout=subprocess.PIPE, bufsize=1 << 22)
        try:
            for nom, data in _tar_flux(p.stdout, garder):
                n += 1
                if TITRE_MVT.search(data):
                    gardes += 1
                    m = ID_RE.search(nom)
                    sous = CACHE_JORF / ("textes" if m.group(1) == b"TEXT" else "articles")
                    sous.mkdir(exist_ok=True)
                    (sous / f"JORF{m.group(1).decode()}{m.group(2).decode()}.xml").write_bytes(data)
                if time.time() - debut > budget_s:
                    raise TimeoutError
        except TimeoutError:
            p.kill()
            print(f"  budget de temps atteint dans {cle} : relancer `jorf`", file=sys.stderr)
            etat_f.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
            return etat
        p.wait()
        etat["archives"][cle] = {"termine": True, "lus": n, "gardes": gardes,
                                 "le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        etat_f.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {cle} : {n} fichiers récents lus, {gardes} gardés ({round(time.time() - debut)} s)", file=sys.stderr)
    return etat


def archives_jorf() -> list[Path]:
    return sorted(JORF_GLOBAL.glob("*.tar.gz")) + sorted(JORF_INCR.glob("*.tar.gz"))


TYPES_MVT = [  # (motif du titre, type, catégorie de comparaison au PLRG)
    (r"titre d'avance", "decret_avance", "mouvements_reglementaires"),
    (r"report(?:s)? de cr[ée]dits de fonds de concours", "report_fonds_de_concours", "reports_entrants"),
    (r"report(?:s)? de cr[ée]dits", "report", "reports_entrants"),
    (r"ouverture de cr[ée]dits (?:de fonds de concours|d'attributions? de produits)", "fonds_de_concours",
     "fonds_de_concours"),
    (r"ouverture et annulation de cr[ée]dits", "ouverture_annulation", "mouvements_reglementaires"),
    (r"annulation de cr[ée]dits", "annulation", "mouvements_reglementaires"),
    (r"virement de cr[ée]dits?", "virement", "mouvements_reglementaires"),
    (r"transfert de cr[ée]dits", "transfert", "mouvements_reglementaires"),
    (r"r[ée]partition de cr[ée]dits", "repartition", "mouvements_reglementaires"),
    (r"ouverture de cr[ée]dits", "ouverture", "mouvements_reglementaires"),
]
LIB_TYPES = {"decret_avance": "Décret d'avance (ouverture et annulation)", "report": "Arrêté de report",
             "report_fonds_de_concours": "Arrêté de report (fonds de concours)",
             "fonds_de_concours": "Arrêté d'ouverture (fonds de concours, attributions de produits)",
             "ouverture_annulation": "Ouverture et annulation", "annulation": "Annulation", "virement": "Virement",
             "transfert": "Transfert", "repartition": "Répartition de crédits globaux", "ouverture": "Ouverture"}


def type_mouvement(titre: str) -> tuple[str | None, str | None]:
    for motif, typ, cat in TYPES_MVT:
        if re.search(r"portant (?:[a-zé ]+ )?" + motif, titre, re.I) or re.search(motif, titre, re.I) and \
                typ == "decret_avance":
            return typ, cat
    return None, None


class _Tables(HTMLParser):
    """Tables d'un contenu JORF : [(texte précédant la table, [lignes de cellules])]."""

    def __init__(self):
        super().__init__()
        self.tables, self._avant, self._lignes, self._ligne, self._cell, self._prof = [], [], None, None, None, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br", "div") and self._cell is not None:
            self._cell.append(" | ")
        if tag == "table":
            self._prof += 1
            if self._prof == 1:
                self._lignes = []
        elif tag == "tr" and self._lignes is not None:
            self._ligne = []
        elif tag in ("td", "th") and self._ligne is not None:
            self._cell = []
            span = dict(attrs).get("colspan")
            self._span = int(span) if span and span.isdigit() else 1

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._ligne.append(re.sub(r"^(?:\s*\|\s*)+|(?:\s*\|\s*)+$", "", propre(" ".join(self._cell))))
            self._ligne.extend([""] * (self._span - 1))
            self._cell = None
        elif tag == "tr" and self._ligne is not None:
            self._lignes.append(self._ligne)
            self._ligne = None
        elif tag == "table":
            self._prof -= 1
            if self._prof == 0 and self._lignes is not None:
                self.tables.append((propre(" ".join(self._avant[-40:])), self._lignes))
                self._lignes, self._avant = None, []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        elif self._lignes is None:
            self._avant.append(data)


def _signe(entete: str, contexte: str, typ: str) -> int | None:
    e = entete.lower()
    if "annul" in e:
        return -1
    if any(k in e for k in ("ouvert", "report", "major", "rattach")):
        return 1
    c = contexte.lower()
    a, o = c.rfind("annul"), max(c.rfind("ouvert"), c.rfind("report"))
    if a >= 0 or o >= 0:
        return -1 if a > o else 1
    if typ == "annulation":
        return -1
    if typ in ("report", "report_fonds_de_concours", "fonds_de_concours", "ouverture"):
        return 1
    return None


def lignes_tableaux_jorf(contenu_html: str, typ: str, nomen: dict | None = None) -> tuple[list[dict], int]:
    """Lignes {programme, ae, cp} des tableaux d'un article JORF (montants signés : annulation < 0).
    Renvoie aussi le nombre de lignes chiffrées non rattachées à un programme."""
    t = _Tables()
    t.feed(contenu_html)
    out, perdues = [], 0
    for contexte, lignes in t.tables:
        if not lignes:
            continue
        # en-tête : premières lignes sans montant
        i = 0
        entetes = []
        while i < len(lignes) and not any(re.fullmatch(r"[\d  .,]+", c.replace(" ", " ")) and
                                          re.search(r"\d{3}", c) for c in lignes[i][1:]):
            entetes.append(lignes[i])
            i += 1
        if not entetes:
            continue
        ncol = max(len(r) for r in lignes)
        tete = [" ".join(r[j] if j < len(r) else "" for r in entetes) for j in range(ncol)]
        col_num = next((j for j, h in enumerate(tete) if re.search(r"num[ée]ro|code", h, re.I)), None)
        cols = []  # (indice, 'ae'|'cp', signe)
        for j, h in enumerate(tete):
            hl = h.lower()
            if "engagement" in hl or re.search(r"\bae\b", hl):
                cols.append((j, "ae", _signe(h, contexte, typ)))
            elif "paiement" in hl or re.search(r"\bcp\b", hl):
                cols.append((j, "cp", _signe(h, contexte, typ)))
        if not cols:
            continue
        for r in lignes[i:]:
            if r:
                r = [propre(r[0].replace("|", " "))] + r[1:]
            if not r or re.match(r"(?i)\s*(dont|totaux?|total)\b", r[0] or ""):
                continue
            code = None
            if col_num is not None and col_num < len(r):
                m = re.fullmatch(r"\s*(\d{3})\s*", r[col_num] or "")
                code = m.group(1) if m else None
            if code is None:
                m = re.search(r"(?:^|\(|-\s?|n°\s?)(\d{3})(?:\)|\s?-|$)", r[0] or "")
                code = m.group(1) if m else None
            vals = {"ae": 0.0, "cp": 0.0}
            chiffre = False
            for j, k, s in cols:
                if j < len(r) and re.search(r"\d", r[j] or ""):
                    if s is None:
                        continue
                    v = premier_nombre(r[j].replace(".", ""))
                    vals[k] += s * abs(v)
                    chiffre = True
            if not chiffre:
                continue
            if code is None and nomen is not None and col_num is None:
                code, _ = resoudre(nomen, r[0], None)
            if code is None:
                perdues += 1  # ligne de mission (sous-total) ou programme non reconnu
                continue
            out.append({"programme": code, **vals})
    return out, perdues


def _xml_champ(xml: str, balise: str) -> str | None:
    m = re.search(rf"<{balise}[^>]*>(.*?)</{balise}>", xml, re.S)
    return propre(re.sub(r"<[^>]+>", " ", m.group(1))) if m else None


def mouvements_jorf(nomen: dict) -> tuple[list[dict], dict]:
    """Textes de mouvements de crédits 2021-2026 avec leurs lignes par programme (montants signés)."""
    textes = {}
    for f in sorted((CACHE_JORF / "textes").glob("*.xml")):
        x = f.read_text(encoding="utf-8")
        titre = _xml_champ(x, "TITREFULL") or ""
        typ, cat = type_mouvement(titre)
        if not typ:
            continue
        date = _xml_champ(x, "DATE_TEXTE") or _xml_champ(x, "DATE_PUBLI")
        visas = _xml_champ(x, "VISAS") or ""
        m = re.search(r"cr[ée]dits pour (\d{4})", visas) or re.search(r"(?:pour|de l'ann[ée]e) (\d{4})", titre)
        annee = int(m.group(1)) if m else int(date[:4])
        if typ in ("report", "report_fonds_de_concours"):
            # un arrêté de report ouvre en N des crédits non consommés en N-1 : année de gestion = année de l'arrêté
            annee = int(date[:4])
        cid = _xml_champ(x, "CID") or f.stem
        textes[cid] = {"id": cid, "titre": titre, "type": typ, "categorie_plrg": cat, "date": date,
                       "date_publication": _xml_champ(x, "DATE_PUBLI"), "nor": _xml_champ(x, "NOR"),
                       "annee_gestion": annee, "rectificatif": "rectificatif" in titre.lower(),
                       "url": f"https://www.legifrance.gouv.fr/jorf/id/{cid}", "lignes": [], "lignes_perdues": 0}
    for f in sorted((CACHE_JORF / "articles").glob("*.xml")):
        x = f.read_text(encoding="utf-8")
        m = re.search(r'<TEXTE cid="(JORFTEXT\d+)"', x)
        if not m or m.group(1) not in textes:
            continue
        t = textes[m.group(1)]
        contenu = re.search(r"<BLOC_TEXTUEL>(.*?)</BLOC_TEXTUEL>", x, re.S)
        if not contenu or "<table" not in contenu.group(1):
            continue
        lignes, perdues = lignes_tableaux_jorf(contenu.group(1), t["type"], nomen)
        t["lignes"].extend(lignes)
        t["lignes_perdues"] += perdues
    out = [t for t in textes.values() if t["annee_gestion"] in ANNEES_MOUVEMENTS]
    stats = {"textes": len(out), "textes_avec_lignes": sum(1 for t in out if t["lignes"]),
             "lignes": sum(len(t["lignes"]) for t in out)}
    return sorted(out, key=lambda t: (t["date"] or "", t["id"])), stats


# --- Contrôle JO / PLRG ----------------------------------------------------------------------------------------------

# Composition des colonnes du PLRG, vérifiée sur 2023-2025 : « mouvements réglementaires » = virements, transferts,
# répartitions et décrets d'ouverture et annulation (dépenses accidentelles), de somme nulle ; « reports » = parts
# ouvertes en N des arrêtés de report (tableau 2), fonds de concours compris ; « FDC et ADP » = arrêtés d'ouverture
# de fonds de concours et d'attributions de produits. Les décrets d'annulation et d'avance n'ont pas de colonne
# distincte dans l'annexe : ils sont publiés sans comparaison.
COMPARAISON = {
    "mouvements_reglementaires": {"virement", "transfert", "repartition", "ouverture_annulation", "ouverture"},
    "reports_entrants": {"report", "report_fonds_de_concours"},
    "fonds_de_concours": {"fonds_de_concours"},
}
LIB_COMPARAISON = {"mouvements_reglementaires": "Mouvements réglementaires (virements, transferts, répartitions)",
                   "reports_entrants": "Reports de crédits entrants", "fonds_de_concours": "Fonds de concours et "
                   "attributions de produits"}


def montant_compare(texte: dict, ligne: dict, colonne: str) -> float:
    """Part d'une ligne JO comparable à la colonne du PLRG (reports : seules les ouvertures de l'année comptent ;
    les annulations du tableau 1 portent sur les crédits de l'année précédente)."""
    if colonne == "reports_entrants":
        return max(ligne["cp"], 0.0)
    return ligne["cp"]


def coherence(mouvements: list[dict], plrg: dict) -> dict:
    out = {}
    for annee, P in sorted(plrg.items()):
        res = {}
        for col, types in COMPARAISON.items():
            jo = defaultdict(float)
            for t in mouvements:
                if t["annee_gestion"] == annee and t["type"] in types:
                    for l in t["lignes"]:
                        jo[l["programme"]] += montant_compare(t, l, col)
            progs = []
            for p, e in sorted(P.items()):
                if e[col] is None:  # colonne illisible au PLRG : pas de comparaison, jamais 0
                    progs.append({"programme": p, "jo_cp": round(jo.get(p, 0.0), 2), "plrg_cp": None,
                                  "ecart_cp": None, "conforme": None, "raison": e["illisibles"][col]})
                    continue
                ecart = jo.get(p, 0.0) - e[col]
                progs.append({"programme": p, "jo_cp": round(jo.get(p, 0.0), 2), "plrg_cp": round(e[col], 2),
                              "ecart_cp": round(ecart, 2), "conforme": abs(ecart) <= TOLERANCE_EUR})
            base = sum(abs(x["plrg_cp"]) for x in progs if x["plrg_cp"] is not None)
            ecart_abs = sum(abs(x["ecart_cp"]) for x in progs if x["ecart_cp"] is not None)
            ecart_pct = round(100 * ecart_abs / base, 3) if base else None
            res[col] = {"libelle": LIB_COMPARAISON[col], "total_jo_cp": round(sum(x["jo_cp"] for x in progs), 2),
                        "total_plrg_cp": round(sum(x["plrg_cp"] for x in progs if x["plrg_cp"] is not None), 2),
                        "somme_valeurs_absolues_plrg_cp": round(base, 2), "ecart_absolu_cp": round(ecart_abs, 2),
                        "ecart_pct": ecart_pct, "conforme": ecart_pct is not None and ecart_pct <= TOLERANCE_PCT,
                        "programmes_conformes": sum(x["conforme"] is True for x in progs), "programmes": len(progs),
                        "ecarts": [x for x in progs if x["conforme"] is not True]}
        out[str(annee)] = res
    return out


# --- d. Production ----------------------------------------------------------------------------------------------------

ADOPTE = "Adopté"


def controle_jo_plrg(coh: dict, a: int, p: str) -> dict:
    return {col: next((z for z in coh[str(a)][col]["ecarts"] if z["programme"] == p), None) or {"conforme": True}
            for col in COMPARAISON}


def controler_realisations() -> int:
    """Contrôle bloquant : LFI, crédits ouverts et dépenses de decisions/programme_<n>.json égaux à ceux de
    realisations/<n>.json (même PLRG) à 1 € près, pour chaque programme et chaque année. Renvoie le nombre de
    valeurs comparées. Un null de decisions/ doit porter sa raison (`valeurs_illisibles_plrg`)."""
    ecarts, n = [], 0
    for f in sorted(SORTIE.glob("programme_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        rf = SITE / "realisations" / f"{d['programme']}.json"
        R = {}
        if rf.exists():
            R = {x["annee"]: x for x in json.loads(rf.read_text(encoding="utf-8"))["prevu_depense"]["annees"]}
        for y, e in d["annees"].items():
            if "source_plrg" not in e:
                continue
            for champ, _ in CHAMPS_PLRG:
                if e[champ] is None and champ not in e.get("valeurs_illisibles_plrg", {}):
                    ecarts.append((d["programme"], y, champ, "null sans raison"))
            r = R.get(int(y))
            if not r:
                continue
            for champ, v in (("depenses_cp", r.get("depense_constatee_eur")), ("lfi_cp", r.get("vote_lfi_eur")),
                             ("ouverts_cp", (r.get("ouvert_en_gestion") or {}).get("total_eur"))):
                if v is None or e[champ] is None:
                    continue
                n += 1
                if abs(v - e[champ]) > 1:
                    ecarts.append((d["programme"], y, champ, e[champ], v))
    if ecarts:
        raise SystemExit(f"decisions/ et realisations/ divergent sur le même PLRG ({len(ecarts)} valeurs) : {ecarts[:10]}")
    return n


def recaler_plrg() -> None:
    """Régénération ciblée, sans archive JORF ni amendements : relit les annexes 1 du PLRG et réécrit, dans les
    fiches publiées, les seuls champs qui en viennent (montants, étapes LFI / LFR / exécution, contrôle JO / PLRG
    recalculé sur les mouvements publiés). Les fichiers dont le contenu ne change pas ne sont pas réécrits."""
    plrg = lire_plrg()
    absents = [str(f) for f in _plrg_fichiers().values() if not f.exists()]
    if absents:
        raise SystemExit(f"annexes PLRG absentes : {absents} (python pipeline/realisations.py collecter)")
    mvts = [t for f in sorted(SORTIE.glob("mouvements_*.json"))
            for t in json.loads(f.read_text(encoding="utf-8"))["textes"]]
    coh = coherence(mvts, plrg)
    fc = SORTIE / "coherence_plrg.json"
    publie = json.loads(fc.read_text(encoding="utf-8"))
    if publie["annees"] != coh:
        raise SystemExit("coherence_plrg.json diffère du recalcul sur les mouvements publiés : lancer `jorf` puis "
                         "`produire` (régénération complète)")
    fiches = {f.stem.split("_")[1]: f for f in SORTIE.glob("programme_*.json")}
    sans_fiche = sorted({p for d in plrg.values() for p in d} - set(fiches))
    if sans_fiche:
        raise SystemExit(f"programmes du PLRG sans fiche publiée : {sans_fiche} (régénération complète nécessaire)")
    modifies = []
    for p, f in sorted(fiches.items()):
        texte = f.read_text(encoding="utf-8")
        d = json.loads(texte)
        chrono = [c for c in d["chronologie"] if not (c["etape"] in (ETAPE_LFI, ETAPE_LFR, ETAPE_EXEC)
                                                      and "url" not in c)]
        for a in sorted(plrg):
            if p not in plrg[a]:
                continue
            x = plrg[a][p]
            ancien = d["annees"].get(str(a), {})
            reste = {k: v for k, v in ancien.items() if k not in bloc_plrg(x, a) and k not in (
                "controle_jo_plrg", "valeurs_illisibles_plrg", "precision_plrg")}
            d["annees"][str(a)] = {**bloc_plrg(x, a), "controle_jo_plrg": controle_jo_plrg(coh, a, p), **reste}
            chrono.extend(etapes_plrg(x, a))
        d["annees"] = dict(sorted(d["annees"].items()))
        chrono.sort(key=lambda c: (c["date"] or "", c["etape"]))
        d["chronologie"] = chrono
        nouveau = json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n"
        if nouveau != texte:
            dump(f, d)
            modifies.append(p)
    n = controler_realisations()
    print(f"PLRG recalé : {len(modifies)} fiche(s) réécrite(s) {modifies} ; {n} valeurs égales à realisations/",
          file=sys.stderr)


def ecrire_amendements_et_scrutins(amdts: list[dict], scr: list[dict], genere: str,
                                   sortie: Path = SORTIE) -> tuple[dict, dict]:
    """Écrit amendements_resume.json et scrutins.json ; rend (résumé par programme et année, adoptés par programme)."""
    par_amdt_scrutin = defaultdict(list)
    for s in scr:
        if s["amendement"]:
            par_amdt_scrutin[s["amendement"]].append({"numero": s["numero"], "resultat": s["resultat"],
                                                      "pour": s["pour"], "contre": s["contre"], "url": s["url"]})
    # amendements : par programme et par année
    resume = defaultdict(lambda: defaultdict(lambda: {"deposes_an": 0, "deposes_senat": 0, "adoptes_seance_an": 0,
                                                       "adoptes_seance_senat": 0, "adoptes_commission_an": 0,
                                                       "net_ae_adopte_seance": 0.0, "net_cp_adopte_seance": 0.0,
                                                       "net_cp_adopte_commission_an": 0.0}))
    adoptes_prog = defaultdict(list)
    non_rattaches = defaultdict(int)
    for a in amdts:
        for l in a["lignes"]:
            if not (l["ae"] or l["cp"]):
                continue
            if not l["programme"]:
                non_rattaches[l["rapprochement"]] += 1
                continue
            r = resume[l["programme"]][str(a["annee"])]
            r["deposes_an" if a["chambre"] == "AN" else "deposes_senat"] += 1
            if a["sort"] != ADOPTE:
                continue
            if a["lieu"] == "séance":
                r["adoptes_seance_an" if a["chambre"] == "AN" else "adoptes_seance_senat"] += 1
                r["net_ae_adopte_seance"] += l["ae"]
                r["net_cp_adopte_seance"] += l["cp"]
            elif a["chambre"] == "AN":
                r["adoptes_commission_an"] += 1
                r["net_cp_adopte_commission_an"] += l["cp"]
            adoptes_prog[l["programme"]].append({
                "id": a["id"], "chambre": a["chambre"], "texte": a["texte"], "annee": a["annee"],
                "lecture": a["lecture"], "lieu": a["lieu"], "numero": a["numero"], "sort": a["sort"],
                "date": a["date_sort"] or a["date_depot"], "auteur": a["auteur"], "cosignataires": a["cosignataires"],
                "ae": l["ae"], "cp": l["cp"], "net_cp_amendement": a["net_cp"], "rapprochement": l["rapprochement"],
                "scrutins": par_amdt_scrutin.get(a["id"], []), "url": a["url"]})
    dump(sortie / "amendements_resume.json", {
        "millesime": "Lois de finances examinées pendant la 17e législature (PLF 2025 à 2027, fin de gestion 2024 à "
                     "2026)", "source": SRC_AMDT, "genere_le": genere, "unite": "euros",
        "methode": ("Un amendement de crédits est compté pour chaque programme dont il modifie les AE ou les CP. "
                    "« Adopté en séance » modifie le texte de la chambre ; « adopté en commission » (Assemblée) "
                    "n'est qu'une proposition au texte examiné en séance. Montant net = somme signée des lignes."),
        "amendements_credits": {"an": sum(1 for a in amdts if a["chambre"] == "AN"),
                                "senat": sum(1 for a in amdts if a["chambre"] == "Sénat")},
        "lignes_non_rattachees": dict(non_rattaches),
        "par_programme": {p: dict(sorted(v.items())) for p, v in sorted(resume.items())}})

    dump(sortie / "scrutins.json", {
        "millesime": "Scrutins publics de la 17e législature sur les lois de finances", "source": SRC_AN,
        "genere_le": genere, "types": ["ensemble", "premiere_partie", "seconde_partie", "credits_mission",
                                       "article_equilibre", "article", "motion", "amendement", "autre"],
        "note": "Les scrutins sur amendements ne sont gardés que pour les amendements de crédits.",
        "scrutins": scr})
    return resume, adoptes_prog


def etapes_amendements(am: list[dict], a: int) -> list[dict]:
    return [{"date": x["date"], "annee": a, "etape": f"Amendement adopté ({x['chambre']}, {x['lieu']})",
             "cp": x["cp"], "ae": x["ae"], "auteur": x["auteur"]["nom"], "url": x["url"]} for x in am]


def produire() -> None:
    if not (CACHE_JORF / "textes").exists():
        raise SystemExit("cache JORF absent : lancer d'abord `python pipeline/decisions.py jorf`")
    nomen = nomenclature()
    plrg = lire_plrg()
    amdts = amendements_an(nomen) + amendements_senat(nomen)
    scr = scrutins_an(amdts)
    mvts, stats_mvt = mouvements_jorf(nomen)
    coh = coherence(mvts, plrg)
    genere = date_sources(avec_heure=True)
    SORTIE.mkdir(parents=True, exist_ok=True)
    for f in SORTIE.glob("*.json"):
        f.unlink()

    resume, adoptes_prog = ecrire_amendements_et_scrutins(amdts, scr, genere)

    par_annee = defaultdict(list)
    lignes_prog = defaultdict(list)
    for t in mvts:
        if t["type"] == "fonds_de_concours" and not t["lignes"]:
            continue
        e = {k: t[k] for k in ("id", "titre", "type", "categorie_plrg", "date", "date_publication", "nor",
                               "annee_gestion", "rectificatif", "url", "lignes_perdues")}
        e["libelle_type"] = LIB_TYPES[t["type"]]
        e["lignes"] = [{"programme": l["programme"], "ae": round(l["ae"], 2), "cp": round(l["cp"], 2)}
                       for l in t["lignes"]]
        e["total_cp"] = round(sum(l["cp"] for l in t["lignes"]), 2)
        par_annee[t["annee_gestion"]].append(e)
        for l in t["lignes"]:
            lignes_prog[l["programme"]].append({"id": t["id"], "date": t["date"], "annee": t["annee_gestion"],
                                                "type": t["type"], "titre": t["titre"], "ae": round(l["ae"], 2),
                                                "cp": round(l["cp"], 2), "url": t["url"]})
    for a, lst in sorted(par_annee.items()):
        dump(SORTIE / f"mouvements_{a}.json", {
            "millesime": f"Gestion {a}", "source": SRC_JORF, "genere_le": genere, "annee": str(a), "unite": "euros",
            "note": ("Montants signés : ouverture > 0, annulation < 0. Arrêtés de report : le tableau 1 annule les "
                     "crédits non consommés de l'année précédente, le tableau 2 les ouvre sur l'année."),
            "textes": lst})
    dump(SORTIE / "coherence_plrg.json", {
        "millesime": "Gestions 2023 à 2025 (PLRG publiés)", "source": f"{SRC_JORF} ; " + SRC_PLRG.format(a="2023-2025"),
        "genere_le": genere, "unite": "euros (crédits de paiement)",
        "tolerance": {"pct_par_annee": TOLERANCE_PCT, "eur_par_programme": TOLERANCE_EUR,
                      "definition": "écart absolu cumulé sur les programmes, en % de la somme des valeurs absolues "
                                    "de la colonne du PLRG"},
        "composition": {k: sorted(v) for k, v in COMPARAISON.items()},
        "hors_comparaison": "décrets d'annulation et décrets d'avance (pas de colonne distincte dans l'annexe 1)",
        "annees": coh})

    # fiches par programme
    arbre_progs = set()
    racine = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    for g in racine["enfants"]:
        for m in g.get("enfants", []):
            for p in m.get("enfants", []):
                if p["niveau"] == "programme":
                    arbre_progs.add(p["id"].split("/")[-1])
    tous = sorted(arbre_progs | set(adoptes_prog) | set(lignes_prog) | {p for d in plrg.values() for p in d})
    fichiers = []
    for p in tous:
        meta = next((plrg[a][p] for a in sorted(plrg, reverse=True) if p in plrg[a]), None)
        annees = {}
        chrono = []
        for a in sorted({*range(2021, 2028)}):
            e = {}
            if a in plrg and p in plrg[a]:
                x = plrg[a][p]
                e.update(bloc_plrg(x, a))
                chrono.extend(etapes_plrg(x, a))
                e["controle_jo_plrg"] = controle_jo_plrg(coh, a, p)
            r = resume.get(p, {}).get(str(a))
            if r:
                e["amendements"] = r
            am = [x for x in adoptes_prog.get(p, []) if x["annee"] == a]
            if am:
                e["amendements_adoptes"] = am
                chrono.extend(etapes_amendements(am, a))
            mv = [x for x in lignes_prog.get(p, []) if x["annee"] == a]
            if mv:
                e["mouvements_jo"] = mv
                e["mouvements_jo_total_cp"] = round(sum(x["cp"] for x in mv), 2)
                for x in mv:
                    chrono.append({"date": x["date"], "annee": a, "etape": LIB_TYPES[x["type"]], "cp": x["cp"],
                                   "ae": x["ae"], "url": x["url"]})
            if e:
                annees[str(a)] = e
        if not annees:
            continue
        chrono.sort(key=lambda c: (c["date"] or "", c["etape"]))
        nom = f"programme_{p}.json"
        dump(SORTIE / nom, {
            "millesime": "2021 à 2027 (selon les sources disponibles par année)",
            "source": f"{SRC_AMDT} ; {SRC_JORF} ; " + SRC_PLRG.format(a="2023-2025"), "genere_le": genere,
            "programme": p, "libelle": (meta or {}).get("libelle") or nomen["libelles"].get(p),
            "mission": (meta or {}).get("mission"), "dans_arbre_2024": p in arbre_progs, "unite": "euros",
            "annees": annees, "chronologie": chrono})
        fichiers.append(f"decisions/{nom}")

    adoptes = [a for a in amdts if a["sort"] == ADOPTE]
    dump(SORTIE / "index.json", {
        "millesime": "17e législature (juillet 2024 à novembre 2026) ; mouvements en gestion 2021 à 2026",
        "source": f"{SRC_AMDT} ; {SRC_JORF} ; " + SRC_PLRG.format(a="2023-2025"), "genere_le": genere,
        "programmes": [f.split("_")[-1][:-5] for f in fichiers], "fichiers": fichiers + [
            "decisions/amendements_resume.json", "decisions/scrutins.json", "decisions/coherence_plrg.json"] + [
            f"decisions/mouvements_{a}.json" for a in sorted(par_annee)],
        "comptes": {"amendements_credits_an": sum(1 for a in amdts if a["chambre"] == "AN"),
                    "amendements_credits_senat": sum(1 for a in amdts if a["chambre"] == "Sénat"),
                    "adoptes_seance_an": sum(1 for a in adoptes if a["chambre"] == "AN" and a["lieu"] == "séance"),
                    "adoptes_seance_senat": sum(1 for a in adoptes if a["chambre"] == "Sénat" and
                                                a["lieu"] == "séance"),
                    "adoptes_commission_an": sum(1 for a in adoptes if a["chambre"] == "AN" and a["lieu"] != "séance"),
                    "scrutins": len(scr), "mouvements": stats_mvt},
        "coherence_plrg": {a: {c: {"ecart_pct": v["ecart_pct"], "conforme": v["conforme"]} for c, v in r.items()}
                           for a, r in coh.items()},
        "regle_personnes": "Seuls les élus (députés, sénateurs), le Gouvernement et les commissions sont nommés "
                           "comme auteurs ; aucune autre donnée personnelle.",
        "limites": [
            "PLF 2025 et 2026 : l'Assemblée a rejeté la première partie ou le Gouvernement a engagé sa responsabilité ; "
            "les amendements de crédits déposés en séance n'y ont pas été examinés (sort « Non examiné »).",
            "Le texte retenu par le Gouvernement (article 49.3) et les conclusions de CMP ne sont pas rapprochés "
            "amendement par amendement : seul le sort publié est utilisé.",
            "Libellés de programmes : rapprochés de la nomenclature (PLRG 2023-2025, budgets verts) ; les programmes "
            "créés ou renommés après 2026 et ceux des comptes spéciaux peuvent rester non rattachés.",
            "Sénat : sort en séance publié, date de décision absente du dump.",
            "Décrets d'annulation et d'avance : publiés, sans colonne de comparaison dans l'annexe 1 du PLRG.",
        ]})
    controler_realisations()
    print(f"amendements {len(amdts)} (adoptés {len(adoptes)}), scrutins {len(scr)}, textes JO {stats_mvt}, "
          f"fiches {len(fichiers)}", file=sys.stderr)
    for a, r in coh.items():
        print(f"  {a} : " + ", ".join(f"{c} écart {v['ecart_pct']} %" for c, v in r.items()), file=sys.stderr)


# Objet de scrutin tel que publié avant la décision du 19/11/2026 : auteur effacé (« de M. … »), et pour un candidat
# national tout ce qui suivait « de ». Sert seulement au contrôle de `auteurs` (rien d'autre ne doit changer).
_AUTEUR_OBJET_ANCIEN = r" (?:de|du) (?:M\.|Mme|MM\.|Mmes)\s.*?(?= (?:à|après|avant|au|aux) |\s*\(|$)"


def _objet_ancien_possible(nouveau: str, ancien: str) -> bool:
    sans = re.sub(_AUTEUR_OBJET_ANCIEN, "", nouveau)
    return ancien in (nouveau, sans, re.sub(r"\s+de\s.*$", "", sans))


def _meme_hors_noms(nouveau, ancien, compte: dict, cle: str = "") -> bool:
    """Vrai si `nouveau` ne diffère d'`ancien` que par un nom d'auteur auparavant effacé (null, `masque`) ou par
    l'objet d'un scrutin dont l'auteur était effacé. Un nom déjà publié ne doit pas changer."""
    if cle == "auteur":
        if isinstance(ancien, dict) and isinstance(nouveau, dict):
            if {k: v for k, v in ancien.items() if k not in ("nom", "masque")} != \
                    {k: v for k, v in nouveau.items() if k != "nom"}:
                return False
            ancien, nouveau = ancien.get("nom"), nouveau.get("nom")
        if ancien is None and nouveau is not None:
            compte["auteurs"] += 1
            return True
        return ancien == nouveau
    if cle == "objet" and isinstance(nouveau, str) and isinstance(ancien, str):
        if nouveau != ancien:
            compte["objets"] += 1
        return _objet_ancien_possible(nouveau, ancien)
    if isinstance(nouveau, dict) and isinstance(ancien, dict):
        return set(nouveau) == set(ancien) and all(_meme_hors_noms(nouveau[k], ancien[k], compte, k) for k in nouveau)
    if isinstance(nouveau, list) and isinstance(ancien, list):
        return len(nouveau) == len(ancien) and all(_meme_hors_noms(n, a, compte) for n, a in zip(nouveau, ancien))
    return nouveau == ancien


def recaler_auteurs() -> None:
    """Régénération ciblée (sans archive JORF) après la décision du 19/11/2026 : rétablit, dans les fichiers publiés,
    le nom des auteurs d'amendements effacés (`masque`) et l'objet des scrutins tel que publié par l'Assemblée. Les
    nouveaux noms et objets sont relus dans les zips de l'Assemblée et du Sénat, par identifiant d'amendement et de
    scrutin. Rien d'autre n'est réécrit (comptes, montants, mouvements) : s'arrête sans rien écrire si un
    identifiant manque, si le type ou le groupe d'un auteur diffère, ou si un nom déjà publié changerait."""
    if not (SORTIE / "index.json").exists():
        raise SystemExit("site/data/decisions/ absent : lancer `python pipeline/decisions.py produire`")
    nomen = nomenclature()
    amdts = amendements_an(nomen) + amendements_senat(nomen)
    auteurs = {a["id"]: a["auteur"] for a in amdts}
    scrutins = {s["id"]: s for s in scrutins_an(amdts)}
    lire = lambda f: json.loads(f.read_text(encoding="utf-8"))  # noqa: E731
    compte = {"auteurs": 0, "objets": 0}
    a_ecrire: dict[Path, dict] = {}

    def controler(f: Path, nouveau: dict, ancien: dict) -> None:
        if not _meme_hors_noms(nouveau, ancien, compte):
            raise SystemExit(f"{f.name} : écart autre qu'un nom d'auteur ou un objet de scrutin ; lancer produire")
        if nouveau != ancien:
            a_ecrire[f] = nouveau

    f = SORTIE / "scrutins.json"
    ancien = lire(f)
    nouveau = json.loads(json.dumps(ancien))
    for s in nouveau["scrutins"]:
        if s["id"] not in scrutins:
            raise SystemExit(f"scrutin {s['id']} absent du zip de l'Assemblée ; lancer produire")
        s["objet"] = scrutins[s["id"]]["objet"]
    controler(f, nouveau, ancien)
    for f in sorted(SORTIE.glob("programme_*.json")):
        ancien = lire(f)
        nouveau = json.loads(json.dumps(ancien))
        par_url = {}
        for e in nouveau["annees"].values():
            for x in e.get("amendements_adoptes", []):
                if x["id"] not in auteurs:
                    raise SystemExit(f"{f.name} : amendement {x['id']} absent des sources ; lancer produire")
                x["auteur"] = dict(auteurs[x["id"]])
                par_url[x["url"]] = x["auteur"]["nom"]
        for c in nouveau["chronologie"]:
            if c["etape"].startswith("Amendement adopté"):
                c["auteur"] = par_url[c["url"]]
        controler(f, nouveau, ancien)
    f = SORTIE / "index.json"
    ancien = lire(f)
    nouveau = {**ancien, "comptes": {k: v for k, v in ancien["comptes"].items() if k != "noms_masques"}}
    if nouveau != ancien:
        a_ecrire[f] = nouveau
    for f, d in a_ecrire.items():
        dump(f, d)
    print(f"auteurs : {compte['auteurs']} nom(s) d'auteur rétabli(s), {compte['objets']} objet(s) de scrutin "
          f"rétabli(s), {len(a_ecrire)} fichier(s) réécrit(s)", file=sys.stderr)

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("etape", choices=["jorf", "produire", "plrg", "auteurs"])
    ap.add_argument("--budget", type=float, default=540.0, help="secondes (étape jorf)")
    args = ap.parse_args()
    if args.etape == "jorf":
        scanner_jorf(archives_jorf(), args.budget)
    elif args.etape == "plrg":
        recaler_plrg()
    elif args.etape == "auteurs":
        recaler_auteurs()
    else:
        produire()


if __name__ == "__main__":
    main()
