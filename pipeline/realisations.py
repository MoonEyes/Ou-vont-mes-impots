"""Bloc « Ce qui a été fait » par programme du budget de l'État.

Entrées : entrepôt brut data/lake/ (non versionné), site/data/arbre/racine.json, site/data/beneficiaires/.
Sorties (chaque fichier porte `millesime`, `source` et `avertissement`) :
  site/data/realisations/<programme>.json   prévu / dépensé, résultats mesurés, réalisations concrètes, évaluations
  site/data/realisations/index.json         couverture, sources, trous de série, fiabilité des règles

Commandes (chacune < 9 min) :
  python pipeline/realisations.py collecter [--budget 480]   # réseau : annexes PLRG manquantes, pages et flux de la
                                                              # Cour des comptes, vérification des liens (reprenable)
  python pipeline/realisations.py produire                   # sans réseau : écrit site/data/realisations/

Règles :
  - écart = dépensé - voté (LFI), en euros et en % du voté, calculé sur les montants arrondis au centime publiés.
  - sens souhaité d'un indicateur : colonne `evolution` du RAP 2025 (Hausse / Baisse / Stabilité) ; à défaut, position
    des cibles par rapport au réalisé connu avant chaque cible (toutes les comparaisons doivent concorder) ; sinon
    « sens inconnu ». `facteur_de_performance` (Citoyen, Usager, Contribuable) ne dit rien du sens : non utilisé.
  - un lien d'évaluation n'est publié que s'il a été vérifié par un appel HTTP (statut 200) lors de `collecter`.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
ETAT = LAKE / "etat"
BRUT = ETAT / "realisations"
CACHE_CC = LAKE / "_cache" / "ccomptes"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "realisations"
ODS = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
CC = "https://www.ccomptes.fr"

AVERTISSEMENT = "Les indicateurs sont choisis par l'administration ; une évolution ne prouve pas l'effet de la dépense."
MAX_REALISATIONS = 10
SEUIL_STABLE_PCT = 1.0  # variation relative en dessous de laquelle un indicateur est dit « stable »
SEUIL_SIMILARITE = 0.5  # rapprochement par code : libellés d'indicateur au moins à moitié communs (mots)
ANNEES_CC = list(range(2015, 2026))

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
    s = unicodedata.normalize("NFC", str(v)).replace(" ", " ").replace(" ", " ")
    s = s.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


def norm(s) -> str:
    """Minuscules sans accents ni ponctuation : clé de rapprochement des libellés."""
    s = unicodedata.normalize("NFKD", propre(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("’", "'").replace("œ", "oe")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


MOTS_VIDES = {"de", "des", "du", "la", "le", "les", "l", "d", "et", "en", "a", "au", "aux", "un", "une", "par", "pour",
              "sur", "dans", "ou", "s", "the"}


def mots(s) -> set:
    return {m for m in norm(s).split() if m not in MOTS_VIDES}


def similarite(a, b) -> float:
    x, y = mots(a), mots(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def montant(v) -> float:
    """Montant d'une annexe (virgule décimale, espaces de milliers) ; vide = 0."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return 0.0 if v != v else float(v)
    s = re.sub(r"[\s  ]", "", str(v)).replace(",", ".")
    return float(s) if s not in ("", "-") else 0.0


NUM_RE = re.compile(r"^(?:[<>≤≥~]|env\.?)?\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:%|‰)?\s*(?:\(.*\))?$")
VIDES = {"", "nd", "n.d", "n.d.", "nc", "n.c", "n.c.", "so", "s.o", "s.o.", "sans objet", "non connu", "non determine",
         "non déterminé", "non disponible", "-", "--", "ns", "nr", "na", "n/a"}


def valeur(brut):
    """(valeur numérique ou None, brut texte ou None). Les décimales à virgule et les espaces de milliers sont nettoyés ;
    « nd », « sans objet », intervalles et textes restent None mais le brut est conservé."""
    if brut is None:
        return None, None
    if isinstance(brut, (int, float)):
        if brut != brut:
            return None, None
        return float(brut), propre(brut if not float(brut).is_integer() else int(brut))
    b = propre(brut)
    if not b:
        return None, None
    if b.lower() in VIDES:
        return None, b
    s = re.sub(r"(?<=\d)[\s  ](?=\d{3}\b)", "", b)
    s = re.sub(r"(?<=\d) (?=\d{3}\b)", "", s)
    m = NUM_RE.match(s)
    if not m:
        return None, b
    return float(m.group(1).replace(",", ".")), b


def prog3(v) -> str | None:
    if v is None:
        return None
    m = re.search(r"(\d{1,3})(?:\.0)?\s*$", propre(v)) or re.search(r"P?(\d{3})", propre(v))
    return m.group(1).zfill(3) if m else None


def code_ind(v) -> str | None:
    """P141.1.2, 141-1-2, P141-1-2 -> P141-1-2."""
    s = propre(v).upper().replace(".", "-").replace(" ", "")
    m = re.match(r"^P?(\d{3})-(\d+)-(\d+)$", s)
    return f"P{m.group(1)}-{int(m.group(2))}-{int(m.group(3))}" if m else None


def duck(path: Path, sql: str = "select * from t") -> list[dict]:
    import duckdb
    con = duckdb.connect()
    con.execute(f"create view t as select * from '{path}'")
    rel = con.sql(sql)
    cols = rel.columns
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def http_get(url: str, tries: int = 8, stream: bool = False, timeout: int = 90):
    """GET avec reprises (connexions coupées fréquentes vers les portails publics), comme pipeline/fetch.py."""
    import requests
    err = None
    for i in range(tries):
        try:
            r = requests.get(url, timeout=timeout, stream=stream, allow_redirects=True,
                             headers={"User-Agent": "ou-vont-mes-impots/0.1 (projet citoyen open source)"})
            if r.status_code < 500 and r.status_code != 429:
                return r
            err = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001 (reseau)
            err = type(exc).__name__
        if i < tries - 1:
            time.sleep(min(2 ** i, 20))
    raise RuntimeError(f"{url} injoignable après {tries} tentatives : {err}")


# --- Sources ---------------------------------------------------------------------------------------------------------

PLRG = {
    2023: {"chemin": BRUT / "annexe1_etat_cp_2023.csv",
           "dataset": "projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-lannee-"
                      "plrg-2023", "piece_jointe": "annexe1_etat_cp_2023_csv"},
    2024: {"chemin": BRUT / "annexe1_etat_cp_2024.csv", "dataset": "plrg-2024", "piece_jointe": "annexe1_etat_cp_2024_csv"},
    2025: {"chemin": ETAT / "etat_plrg_2025" / "Annexe1-Etat_CP-2025.csv",
           "dataset": "projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-lannee-"
                      "plrg-2025", "piece_jointe": None},
}
for _a, _s in PLRG.items():
    _s["source"] = f"data.economie.gouv.fr/{_s['dataset']}, annexe 1 « état CP » {_a} (PLRG {_a})"

RAP_XLS = {2019: ETAT / "etat_plr_2019" / "RAP_synthese_2019.xls", 2020: ETAT / "etat_plr_2020" / "RAP2020_synthese.xls"}
SRC_RAP_XLS = {2019: "data.economie.gouv.fr/projet-de-loi-de-reglement-2019-plr-20192, RAP_synthese_2019.xls",
               2020: "data.economie.gouv.fr/projet-de-loi-de-reglement-2020-plr-2020, RAP2020_synthese.xls"}
BUDGET_VERT_2024 = ETAT / "economie__budgetvert_plf2024_opendata_vf.parquet"
EXEC_ANCIENS = {
    2010: (ETAT / "economie__execution-2010-du-budget-general-en-cp.parquet", "execution-2010-du-budget-general-en-cp"),
    2011: (ETAT / "economie__execution-2011-du-budget-general-en-cp.parquet", "execution-2011-du-budget-general-en-cp"),
    2012: (ETAT / "economie__execution-2012-du-budget-de-letat-en-cp-suivant-la-nomenclature-mission-programm.parquet",
           "execution-2012-du-budget-de-letat-en-cp-suivant-la-nomenclature-mission-programm"),
    2013: (ETAT / "economie__execution-2013-du-budget-de-letat-en-cp-et-ae-" /
           "Ex_cution_2013_du_budget_de_l_Etat_en_CP_suivant_la_nomenclature_Mission_Program.bin",
           "execution-2013-du-budget-de-letat-en-cp-et-ae-"),
    2014: (ETAT / "economie__plr-2014-donnees-de-lexecution-2015-publiees-dans-les-annexes-rap-du-projet-de-l" /
           "PLR2014-Exec-Msn_CP.csv", "plr-2014-donnees-de-lexecution-2015-publiees-dans-les-annexes-rap-du-projet-de-l"),
}
LFI_ANCIENNES = {  # annee -> (fichier, colonne CP)
    2011: (ETAT / "economie__lfi-2012-dotation-bg-en-ae-cp-par-mission-programme-action-et-titre.parquet", "cplf_2011"),
    2012: (ETAT / "economie__lfi-2012-dotation-bg-en-ae-cp-par-mission-programme-action-et-titre.parquet", "cplf"),
    2013: (ETAT / "economie__lfi-2013-dotation-bg-en-ae-cp-par-mission-programme-action-et-categorie.parquet", "cplf"),
    2014: (ETAT / "economie__lfi-2014-dotation-bg-en-ae-cp-par-action-titre.parquet", "cplf"),
}
TROUS_EXECUTION = {
    2015: "Aucune donnée d'exécution par programme publiée sur data.economie.gouv.fr pour 2015 (PLR 2015).",
    2016: "Aucune donnée d'exécution par programme publiée sur data.economie.gouv.fr pour 2016 (PLR 2016).",
    2017: "Aucune donnée d'exécution par programme publiée sur data.economie.gouv.fr pour 2017 (PLR 2017).",
    2021: "Trou 2021 : ni PLR 2021 ni RAP 2021 de synthèse publiés en données ouvertes sur data.economie.gouv.fr.",
}

# Sources de performance, de la plus récente (prioritaire pour une même année) à la plus ancienne.
PERF = [
    ("rap2025", "RAP 2025", ETAT / "etat_performance_rap_2025.parquet",
     "data.economie.gouv.fr/performance-de-la-depense-rap-2025"),
    ("perf_atteinte", "Performance : exécution et atteinte de la cible (2022-2024)",
     ETAT / "economie__performance-execution-et-atteinte-de-la-cible-du-budget-de-l-etat-jusqu-au-niveau-sous-"
            "indicateur.parquet",
     "data.economie.gouv.fr/performance-execution-et-atteinte-de-la-cible-du-budget-de-l-etat-jusqu-au-niveau-sous-"
     "indicateur"),
    ("rap2024", "RAP 2024", ETAT / "economie__performance-de-la-depense.parquet",
     "data.economie.gouv.fr/performance-de-la-depense (RAP 2024)"),
    ("pap2025", "PAP 2025", ETAT / "economie__plf-2025-performance.parquet", "data.economie.gouv.fr/plf-2025-performance"),
    ("pap2023", "PAP 2023", ETAT / "economie__pap-2023-objectifs-et-indicateurs-de-performance.parquet",
     "data.economie.gouv.fr/pap-2023-objectifs-et-indicateurs-de-performance"),
    ("rap2020", "RAP 2020", RAP_XLS[2020], SRC_RAP_XLS[2020]),
    ("rap2019", "RAP 2019", RAP_XLS[2019], SRC_RAP_XLS[2019]),
    ("pap2019", "PAP 2019", ETAT / "economie__projet-de-loi-de-finances-pour-2019-plf-2019-annexe-projet-annuel-de-"
                                   "performance.parquet",
     "data.economie.gouv.fr/projet-de-loi-de-finances-pour-2019-plf-2019-annexe-projet-annuel-de-performance"),
    ("pap2018", "PAP 2018", ETAT / "economie__projet-de-loi-de-finances-pour-2018-plf-2018-donnees-du-du-volet-"
                                   "performance-des.parquet",
     "data.economie.gouv.fr/projet-de-loi-de-finances-pour-2018-plf-2018-donnees-du-du-volet-performance-des"),
    ("rap2016", "RAP 2016 (PLR 2016)", ETAT / "economie__plr-2016-projet-de-loi-de-reglement-pour-2016-donnees-du-"
                                              "volet-performance-prese.parquet",
     "data.economie.gouv.fr/plr-2016-projet-de-loi-de-reglement-pour-2016-donnees-du-volet-performance-prese"),
    ("pap2017", "PAP 2017", ETAT / "economie__projet-de-loi-de-finances-pour-2017-plf-2017-donnees-du-volet-"
                                   "performance.parquet",
     "data.economie.gouv.fr/projet-de-loi-de-finances-pour-2017-plf-2017-donnees-du-volet-performance"),
    ("rap2015", "RAP 2015 (PLR 2015)", ETAT / "economie__plr-2015-projet-de-loi-de-reglement-pour-2015-donnees-du-"
                                              "volet-performance-prese.parquet",
     "data.economie.gouv.fr/plr-2015-projet-de-loi-de-reglement-pour-2015-donnees-du-volet-performance-prese"),
    ("pap2016", "PAP 2016", ETAT / "economie__plf-2016-donnees-du-volet-performance.parquet",
     "data.economie.gouv.fr/plf-2016-donnees-du-volet-performance"),
    ("pap2015", "PAP 2015", ETAT / "economie__plf-2015-donnees-du-volet-performance.parquet",
     "data.economie.gouv.fr/plf-2015-donnees-du-volet-performance"),
]
PERF_LIB = {k: lib for k, lib, _, _ in PERF}
PERF_SRC = {k: s for k, _, _, s in PERF}

# --- Collecte (réseau) -------------------------------------------------------------------------------------------


def collecter_plrg() -> None:
    for annee, s in PLRG.items():
        if s["chemin"].exists() or not s["piece_jointe"]:
            continue
        url = f"{ODS}/{s['dataset']}/attachments/{s['piece_jointe']}"
        print(f"  téléchargement {url}", file=sys.stderr)
        contenu = http_get(url).content
        if contenu[:2] in (b"\xff\xfe", b"\xfe\xff"):
            texte = contenu.decode("utf-16")
        else:
            texte = contenu.decode("utf-8-sig")
        if "Depenses_constatees" not in texte.splitlines()[0]:
            raise SystemExit(f"{url} : colonnes inattendues : {texte.splitlines()[0][:200]}")
        s["chemin"].parent.mkdir(parents=True, exist_ok=True)
        s["chemin"].write_text(texte, encoding="utf-8")


def page_cc(annee: int) -> Path:
    return CACHE_CC / f"budget_etat_{annee}.html"


def collecter_cc_pages() -> None:
    CACHE_CC.mkdir(parents=True, exist_ok=True)
    for a in ANNEES_CC:
        p = page_cc(a)
        if p.exists() and p.stat().st_size > 10_000:
            continue
        url = f"{CC}/fr/publications/le-budget-de-letat-en-{a}-resultats-et-gestion"
        try:
            r = http_get(url)
        except RuntimeError as exc:
            print(f"  {exc}", file=sys.stderr)
            continue
        if r.status_code == 200:
            p.write_text(r.text, encoding="utf-8")
        print(f"  {url} -> {r.status_code}", file=sys.stderr)
    r = http_get(f"{CC}/fr/rss/publications")
    if r.status_code == 200 and "<rss" in r.text[:500]:
        (CACHE_CC / "rss_publications.xml").write_text(r.text, encoding="utf-8")


def fichier_verifications() -> Path:
    return CACHE_CC / "verifications.json"


def charger_verifications() -> dict:
    f = fichier_verifications()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def verifier_liens(urls: list[str], budget_s: float) -> dict:
    """Appel HTTP sur chaque lien (lecture des premiers octets) ; reprenable, résultats en cache disque."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    verifs = charger_verifications()
    a_faire = [u for u in urls if verifs.get(u, {}).get("statut") != 200]
    debut = time.time()

    def un(u):
        try:
            r = http_get(u, tries=4, stream=True, timeout=60)
            tete = next(r.iter_content(8), b"")
            r.close()
            return u, {"statut": r.status_code, "type": r.headers.get("content-type", ""),
                       "pdf": tete.startswith(b"%PDF"), "url_finale": r.url,
                       "verifie_le": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        except RuntimeError as exc:
            return u, {"statut": None, "erreur": str(exc)[:200],
                       "verifie_le": datetime.now(timezone.utc).strftime("%Y-%m-%d")}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = []
        for u in a_faire:
            futs.append(ex.submit(un, u))
        for i, f in enumerate(as_completed(futs)):
            u, v = f.result()
            verifs[u] = v
            if i % 25 == 0:
                fichier_verifications().write_text(json.dumps(verifs, ensure_ascii=False, indent=0), encoding="utf-8")
            if time.time() - debut > budget_s:
                print("  budget de temps atteint : relancer `collecter` pour finir", file=sys.stderr)
                for g in futs:
                    g.cancel()
                break
    fichier_verifications().write_text(json.dumps(verifs, ensure_ascii=False, indent=0), encoding="utf-8")
    ok = sum(1 for u in urls if verifs.get(u, {}).get("statut") == 200)
    print(f"  liens vérifiés : {ok}/{len(urls)}", file=sys.stderr)
    return verifs


def fichier_documents() -> Path:
    return CACHE_CC / "documents.json"


def resoudre_documents(urls: list[str]) -> None:
    """Pages /fr/documents/<n> (notes 2020 à 2022) : on lit la page et on garde l'unique PDF NEB qu'elle contient."""
    from concurrent.futures import ThreadPoolExecutor
    f = fichier_documents()
    docs = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def un(u):
        try:
            r = http_get(u, tries=4, timeout=60)
        except RuntimeError:
            return u, None
        pdfs = sorted(set(re.findall(r'href="([^"]*/NEB-[^"/]*\.pdf)"', r.text)))
        return u, (pdfs[0] if pdfs[0].startswith("http") else CC + pdfs[0]) if len(pdfs) == 1 else None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for u, pdf in ex.map(un, [u for u in urls if not docs.get(u)]):
            docs[u] = pdf
    f.write_text(json.dumps(docs, ensure_ascii=False, indent=0), encoding="utf-8")


def collecter(budget_s: float) -> None:
    collecter_plrg()
    collecter_cc_pages()
    resoudre_documents([n["url"] for n in notes_execution(resoudre=False) if "/fr/documents/" in n["url"]])
    neb = notes_execution()
    rss = publications_rss()
    programmes, _ = execution_plrg()
    urls = sorted({n["url"] for n in neb} | {p["url"] for p in rss_rattachees(rss, programmes)})
    verifier_liens(urls, budget_s)


# --- 1. Prévu / dépensé --------------------------------------------------------------------------------------------


def execution_plrg() -> tuple[dict, dict]:
    """{programme: {libelle, mission}}, {annee: {programme: {lfi, lfr, ...}}} depuis les annexes 1 « état CP »."""
    meta, par_annee = {}, {}
    cols = {"LFI": "lfi", "LFR": "lfr", "Report_N-1": "reports_entrants", "Mvts_reglementaires": "mouvements_reglementaires",
            "FDC_et_ADP": "fonds_de_concours_et_attributions_de_produits",
            "Fongibilite_asymetrique": "fongibilite_asymetrique", "Total_CP_Ouverts": "ouverts",
            "Depenses_constatees": "depenses"}
    for annee in sorted(PLRG):
        s = PLRG[annee]
        if not s["chemin"].exists():
            print(f"  absent : {s['chemin']} (lancer `collecter`)", file=sys.stderr)
            continue
        lignes = list(csv.DictReader(io.StringIO(s["chemin"].read_text(encoding="utf-8-sig")), delimiter=";"))
        manquantes = set(cols) | {"Mission", "Programme"} - set(lignes[0])
        if not lignes or manquantes - set(lignes[0]):
            raise SystemExit(f"{s['chemin']} : colonnes manquantes {manquantes - set(lignes[0])}")
        d = defaultdict(lambda: defaultdict(float))
        for r in lignes:
            m = re.search(r"-\s*(\d{3})\s*$", r["Programme"]) or re.search(r"(\d{3})\s*$", r["Programme"])
            if not m:
                raise SystemExit(f"Programme illisible ({annee}) : {r['Programme']}")
            p = m.group(1)
            for c, k in cols.items():
                d[p][k] += montant(r[c])
            meta[p] = {"libelle": re.sub(r"\s*-\s*\d{3}\s*$", "", propre(r["Programme"])), "mission": propre(r["Mission"])}
        par_annee[annee] = d
    return meta, par_annee


def execution_rap_xls() -> dict:
    """RAP de synthèse 2019 et 2020, feuille Crédits : CP consommés N-1, CP LFI N, CP consommés N."""
    import pandas as pd
    out = defaultdict(dict)  # annee -> programme -> {lfi?, depenses}
    for annee, f in RAP_XLS.items():
        if not f.exists():
            continue
        df = pd.read_excel(f, sheet_name="Crédits", header=None)
        entete = [propre(x) for x in df.iloc[2].tolist()]
        if entete[9] != f"CP {annee - 1}" or entete[15] != f"CP {annee}" or entete[21] != f"CP {annee}":
            raise SystemExit(f"{f} : en-têtes inattendus {entete}")
        for _, r in df.iterrows():
            if propre(r[0]) != "Programme":
                continue
            p = prog3(r[2])
            src = SRC_RAP_XLS[annee]
            out[annee][p] = {"lfi": montant(r[15]), "depenses": montant(r[21]), "source": src}
            out[annee - 1].setdefault(p, {"depenses": montant(r[9]), "source": src + f" (consommation {annee - 1})"})
    return out


def execution_budget_vert_2022() -> dict:
    rows = duck(BUDGET_VERT_2024, "select numero_programme p, sum(execution_2022_cp) e from t "
                                  "where type_depense = 'Crédits budgétaires' group by 1")
    src = "data.economie.gouv.fr/budgetvert_plf2024_opendata_vf (PLF 2024, budget vert : exécution 2022 en CP)"
    return {prog3(r["p"]): {"depenses": float(r["e"] or 0), "source": src} for r in rows if r["p"] is not None}


def _csv_ancien(path: Path) -> list[dict]:
    brut = path.read_bytes()
    texte = brut.decode("cp1252", errors="replace")
    lignes = texte.replace("\r\n", "\n").split("\n")
    i = next(k for k, l in enumerate(lignes) if l.startswith("Mission;Programme"))
    return list(csv.DictReader(io.StringIO("\n".join(lignes[i:])), delimiter=";"))


def execution_anciennes() -> dict:
    out = defaultdict(dict)
    for annee, (f, ds) in EXEC_ANCIENS.items():
        if not f.exists():
            continue
        src = f"data.economie.gouv.fr/{ds} (budget général, exécution {annee} en CP)"
        tot = defaultdict(float)
        if f.suffix == ".parquet":
            rows = duck(f)
            for r in rows:
                p = prog3(r.get("pgm") or r.get("programme"))
                if r.get("total_general") is not None:
                    tot[p] += montant(r["total_general"])
                else:
                    tot[p] += sum(montant(r.get(f"t{k}")) for k in range(1, 8))
        else:
            for r in _csv_ancien(f):
                p = prog3(r["Programme"])
                if p:
                    tot[p] += montant(r["Total général"])
        for p, v in tot.items():
            out[annee][p] = {"depenses": v, "source": src}
    for annee, (f, col) in LFI_ANCIENNES.items():
        if not f.exists():
            continue
        rows = duck(f, f"select programme p, sum({col}) v from t group by 1")
        src = f"data.economie.gouv.fr/{f.stem.removeprefix('economie__')} (LFI {annee}, budget général, CP)"
        for r in rows:
            p = prog3(r["p"])
            if p in out.get(annee, {}):
                out[annee][p]["lfi"] = float(r["v"] or 0)
                out[annee][p]["source"] += " ; " + src
    return out


def r2(v):
    return None if v is None else round(v, 2)


def bloc_prevu_depense(p: str, plrg: dict, autres: dict, total_arbre: float) -> dict:
    annees = []
    for annee in sorted(set(plrg) | set(autres) | set(TROUS_EXECUTION)):
        if annee in plrg:
            d = plrg[annee].get(p)
            if not d:
                continue
            vote, dep = r2(d["lfi"]), r2(d["depenses"])
            ouverts = r2(d["ouverts"])
            e = {"annee": annee, "source": PLRG[annee]["source"], "vote_lfi_eur": vote,
                 "ouvert_en_gestion": {"total_eur": ouverts, "lfr_eur": r2(d["lfr"]),
                                       "reports_entrants_eur": r2(d["reports_entrants"]),
                                       "mouvements_reglementaires_eur": r2(d["mouvements_reglementaires"]),
                                       "fonds_de_concours_et_attributions_de_produits_eur":
                                           r2(d["fonds_de_concours_et_attributions_de_produits"]),
                                       "fongibilite_asymetrique_eur": r2(d["fongibilite_asymetrique"])},
                 "depense_constatee_eur": dep}
        elif annee in autres and p in autres[annee]:
            d = autres[annee][p]
            vote, dep = r2(d.get("lfi")), r2(d["depenses"])
            e = {"annee": annee, "source": d["source"], "vote_lfi_eur": vote, "ouvert_en_gestion": None,
                 "depense_constatee_eur": dep}
        elif annee in TROUS_EXECUTION:
            annees.append({"annee": annee, "source": None, "vote_lfi_eur": None, "ouvert_en_gestion": None,
                           "depense_constatee_eur": None, "ecart_eur": None, "ecart_pct": None,
                           "trou": TROUS_EXECUTION[annee]})
            continue
        else:
            continue
        e["ecart_eur"] = r2(dep - vote) if vote is not None and dep is not None else None
        e["ecart_pct"] = round((dep - vote) / vote * 100, 2) if vote and dep is not None else None
        if e["ouvert_en_gestion"] and e["ouvert_en_gestion"]["total_eur"] is not None:
            e["ecart_ouvert_eur"] = r2(dep - e["ouvert_en_gestion"]["total_eur"])
        if annee == 2024 and dep is not None and total_arbre:
            e["eur_sur_100"] = round(dep / total_arbre * 100, 6)
        annees.append(e)
    # Les trous ne sont signalés que si le programme a au moins une année réelle.
    if not any(a.get("depense_constatee_eur") is not None for a in annees):
        return {"annees": [], "note": "Programme absent des annexes d'exécution."}
    return {"annees": annees,
            "lecture": "Voté = loi de finances initiale (LFI). Ouvert en gestion = LFI + lois de finances rectificatives "
                       "+ reports de l'année précédente + mouvements réglementaires + fonds de concours et attributions "
                       "de produits. Écart = dépensé - voté (en % du voté). Crédits de paiement (CP).",
            "note_perimetre": "Avant 2018 et en 2022 : budget général seulement et nomenclature de l'année ; un même "
                              "numéro de programme peut avoir changé de périmètre."}


# --- 2. Résultats mesurés -----------------------------------------------------------------------------------------


def _ligne(src, prog, code, obj, ind, ssi, unite, realises=None, cibles=None, atteinte=None, evolution=None,
           contexte=None, annee_cible=None, valeur_cible=None):
    return {"src": src, "prog": prog, "code": code_ind(code) if code else None, "objectif": propre(obj),
            "indicateur": propre(ind), "sous_indicateur": propre(ssi) or None, "unite": propre(unite) or None,
            "realises": realises or {}, "cibles": cibles or {}, "atteinte": atteinte or {},
            "evolution": propre(evolution) or None, "contexte": propre(contexte) or None,
            "annee_cible": annee_cible, "valeur_cible": valeur_cible}


def _abs(v, a):
    return v if v not in (None, "") else a


def lignes_perf() -> list[dict]:
    out = []
    for cle, _, f, _ in PERF:
        if not f.exists():
            print(f"  source de performance absente : {f}", file=sys.stderr)
            continue
        if cle == "rap2025":
            for r in duck(f, "select * from t where type_de_secteur = 'Programme'"):
                out.append(_ligne(cle, prog3(r["code_programme"]), r["code_externe_indicateur"], r["libelle_objectif"],
                                  r["libelle_indicateur"], r["libelle_sous_indicateur"], r["unite"],
                                  {2023: _abs(r["exec_2023"], r["absexec_2023"]),
                                   2024: _abs(r["exec_2024"], r["absexec_2024"]),
                                   2025: _abs(r["exec_2025"], r["abs_exec_2025"])},
                                  {2025: _abs(r["2025_cible"], r["abs_2025_cible"]),
                                   2026: _abs(r["2026_cible"], r["abs_2026_cible"])},
                                  {2025: r["atteinte_de_la_cible_2025"]}, r["evolution"], r["contexte"]))
        elif cle == "perf_atteinte":
            for r in duck(f, "select * from t where type_de_secteur = 'Programme'"):
                a = int(r["annee"])
                out.append(_ligne(cle, prog3(r["code_programme"]), r["code_externe_indicateur"], r["libelle_objectif"],
                                  r["libelle_indicateur"], r["libelle_sous_indicateur"], r["unite"],
                                  {a: r["execution"]}, {a: r["cible"]}, {a: r["atteinte_de_la_cible"]}))
        elif cle == "rap2024":
            for r in duck(f, "select * from t where type_de_secteur = 'Programme'"):
                out.append(_ligne(cle, prog3(r["code_programme"]), r["code_indicateur"], r["libelle_objectif"],
                                  r["libelle_indicateur"], r["libelle_sous_indicateur"], r["unite"],
                                  {2022: r["exec_2022"], 2023: r["exec_2023"], 2024: r["exec_2024"]},
                                  {2024: r["2024_cible"], 2025: r["2025_cible"]},
                                  {2024: r["atteinte_de_la_cible_2024"]}))
        elif cle == "pap2025":
            for r in duck(f, "select * from t where type_de_secteur = 'Programme'"):
                out.append(_ligne(cle, prog3(r["code_programme"]), r["code_indicateur"], r["libelle_objectif"],
                                  r["libelle_indicateur"], r["libelle_sous_indicateur"], r["unite"],
                                  {2022: r["2022_realisation"], 2023: r["2023_realisation"]},
                                  {2024: r["2024_cible_pap_2024"], 2025: r["2025_cible"], 2026: r["2026_cible"],
                                   2027: r["2027_cible"]}))
        elif cle == "pap2023":
            for r in duck(f, "select * from t where type_de_secteur = 'Programme'"):
                out.append(_ligne(cle, prog3(r["code_programme"]), r["code_externe_indicateur"], r["libelle_objectif"],
                                  r["libelle_indicateur"], r["libelle_sous_indicateur"], r["unite"],
                                  {2020: _abs(r["2020"], r["abs_2020"]), 2021: _abs(r["2021"], r["abs_2021"])},
                                  {2022: _abs(r["2022_x000d_cible_pap_2022"], r["abs_2022_x000d_cible_pap_2022"]),
                                   2023: _abs(r["2023_x000d_cible"], r["abs_2023_x000d_cible"]),
                                   2024: _abs(r["2024_x000d_cible"], r["abs_2024_x000d_cible"]),
                                   2025: _abs(r["2025_x000d_cible"], r["abs_2025_x000d_cible"])}))
        elif cle in ("rap2020", "rap2019"):
            out.extend(_lignes_rap_xls(cle, f, int(cle[-4:])))
        else:
            out.extend(_lignes_anciennes(cle, f))
    return out


def _lignes_rap_xls(cle: str, f: Path, annee: int) -> list[dict]:
    import pandas as pd
    df = pd.read_excel(f, sheet_name="Performance", header=None)
    ent = [propre(x) for x in df.iloc[2].tolist()]
    if ent[8] != str(annee - 2) or ent[9] != str(annee - 1) or ent[12] != str(annee):
        raise SystemExit(f"{f} : en-têtes de performance inattendus {ent}")
    out, prog, obj, ind, ind_code, ind_annee_cible, ind_fact = [], None, "", "", None, None, None
    for _, r in df.iloc[3:].iterrows():
        nature = propre(r[0])
        if nature == "Mission":
            prog = None
        elif nature == "Programme":
            prog = prog3(r[3])
        elif nature == "Objectif":
            obj = propre(r[4])
        elif nature == "Indicateur":
            ind, ind_code = propre(r[4]), propre(r[3])
            m = re.match(r"^\d{4}$", propre(r[13]).split(".")[0])
            ind_annee_cible = int(m.group(0)) if m else None
        elif nature == "Sous indicateur" and prog:
            vc = r[13] if ind_annee_cible else None
            out.append(_ligne(cle, prog, ind_code if propre(ind_code).startswith(prog) else None, obj, ind, r[4], r[7],
                              {annee - 2: r[8], annee - 1: r[9], annee: r[12]}, {annee: r[10]},
                              annee_cible=ind_annee_cible, valeur_cible=vc))
    return out


def _lignes_anciennes(cle: str, f: Path) -> list[dict]:
    rows = duck(f)
    out = []
    cols = list(rows[0]) if rows else []
    reals = sorted(int(c.split("_")[1]) for c in cols if re.match(r"^realisation_\d{4}$", c))
    pap_meme = [c for c in cols if re.match(r"^prevision_(\d{4})_pap_\1$", c)]
    for r in rows:
        p = prog3(r["cod_pgm"])
        out.append(_ligne(cle, p, r.get("identifiant_indicateur") or r.get("numero_indicateur"), r["objectif"],
                          r["indicateur"], r["sous_indicateur"], r["unite"],
                          {a: r[f"realisation_{a}"] for a in reals},
                          {int(c.split("_")[1]): r[c] for c in pap_meme},
                          annee_cible=int(str(r["annee_cible"])[:4]) if re.match(r"^\d{4}", str(r["annee_cible"] or ""))
                          else None, valeur_cible=r["valeur_cible"]))
    # PLF 2018 et 2019 : `identifiant_indicateur` est un identifiant interne, le code externe est `numero_indicateur`.
    for o, r in zip(out, rows):
        if r.get("numero_indicateur"):
            o["code"] = code_ind(r["numero_indicateur"])
    return out


def series_indicateurs(lignes: list[dict]) -> tuple[dict, dict]:
    """Rapproche les lignes en séries : par code externe d'indicateur (libellé d'indicateur au moins à moitié commun,
    pour écarter les renumérotations) puis par libellé exact d'indicateur et de sous-indicateur."""
    series, par_code, par_lib = {}, defaultdict(list), {}
    stats = defaultdict(int)
    ordre = {k: i for i, (k, *_r) in enumerate(PERF)}
    lignes = sorted(lignes, key=lambda l: ordre[l["src"]])
    n_par_code_src = defaultdict(int)
    for l in lignes:
        n_par_code_src[(l["src"], l["prog"], l["code"])] += 1
    for l in lignes:
        if not l["prog"]:
            continue
        ssi = norm(l["sous_indicateur"])
        cle_lib = (l["prog"], norm(l["indicateur"]), ssi)
        sid, methode = None, None
        if l["code"]:
            cands = [s for s in par_code[(l["prog"], l["code"])]
                     if similarite(series[s]["indicateur"], l["indicateur"]) >= SEUIL_SIMILARITE
                     or norm(series[s]["indicateur"]) == norm(l["indicateur"])]
            exact = [s for s in cands if norm(series[s]["sous_indicateur"]) == ssi]
            if exact:
                sid, methode = exact[0], "code"
            elif len(cands) == 1 and n_par_code_src[(l["src"], l["prog"], l["code"])] == 1 \
                    and len(par_code[(l["prog"], l["code"])]) == 1:
                sid, methode = cands[0], "code (sous-indicateur unique)"
        if sid is None and cle_lib in par_lib:
            sid, methode = par_lib[cle_lib], "libellé"
        if sid is None:
            sid = f"{l['prog']}-{len([s for s in series if s.startswith(l['prog'] + '-')]) + 1}"
            series[sid] = {"id": sid, "prog": l["prog"], "code": l["code"], "objectif": l["objectif"],
                           "indicateur": l["indicateur"], "sous_indicateur": l["sous_indicateur"], "unite": l["unite"],
                           "realises": {}, "cibles": {}, "atteinte": {}, "evolution": None, "contexte": None,
                           "libelles_anterieurs": set(), "sources": [], "rapprochements": defaultdict(int)}
            methode = "création"
            if l["code"]:
                par_code[(l["prog"], l["code"])].append(sid)
        s = series[sid]
        stats[methode] += 1
        s["rapprochements"][methode] += 1
        par_lib.setdefault(cle_lib, sid)
        if norm(l["indicateur"]) != norm(s["indicateur"]):
            s["libelles_anterieurs"].add(l["indicateur"])
        if l["src"] not in s["sources"]:
            s["sources"].append(l["src"])
        s["evolution"] = s["evolution"] or l["evolution"]
        s["contexte"] = s["contexte"] or l["contexte"]
        s["unite"] = s["unite"] or l["unite"]
        for a, b in l["realises"].items():
            v, brut = valeur(b)
            if brut is None:
                continue
            cur = s["realises"].get(a)
            if cur is None or (cur["valeur"] is None and v is not None):
                s["realises"][a] = {"valeur": v, "brut": brut, "source": l["src"]}
        for a, b in l["cibles"].items():
            v, brut = valeur(b)
            if brut is None:
                continue
            cur = s["cibles"].get(a)
            if cur is None or (cur["valeur"] is None and v is not None):
                s["cibles"][a] = {"valeur": v, "brut": brut, "source": l["src"]}
        if l["annee_cible"]:
            v, brut = valeur(l["valeur_cible"])
            if brut is not None and l["annee_cible"] not in s["cibles"]:
                s["cibles"][l["annee_cible"]] = {"valeur": v, "brut": brut, "source": l["src"],
                                                 "note": "cible de moyen terme"}
        for a, t in l["atteinte"].items():
            if propre(t) and a not in s["atteinte"]:
                s["atteinte"][a] = {"texte": propre(t), "source": l["src"]}
    return series, dict(stats)


def sens_souhaite(s: dict) -> dict:
    ev = (s["evolution"] or "").lower()
    if ev in ("hausse", "baisse"):
        return {"valeur": ev, "methode": "colonne evolution", "source": PERF_SRC["rap2025"],
                "justification": f"Sens d'évolution « {s['evolution']} » publié dans le RAP 2025."}
    if ev == "stabilité":
        return {"valeur": "stabilité", "methode": "colonne evolution", "source": PERF_SRC["rap2025"],
                "justification": "Sens d'évolution « Stabilité » publié dans le RAP 2025 : ni la hausse ni la baisse "
                                 "ne sont souhaitées."}
    comparaisons = []
    reals = {a: r["valeur"] for a, r in s["realises"].items() if r["valeur"] is not None}
    for a, c in sorted(s["cibles"].items()):
        if c["valeur"] is None:
            continue
        avant = [x for x in reals if x < a]
        if not avant:
            continue
        ref = max(avant)
        if c["valeur"] == reals[ref]:
            continue
        comparaisons.append({"cible_annee": a, "cible": c["valeur"], "realise_annee": ref, "realise": reals[ref],
                             "sens": "hausse" if c["valeur"] > reals[ref] else "baisse",
                             "source_cible": PERF_SRC[c["source"]]})
    sens = {c["sens"] for c in comparaisons}
    if len(sens) == 1:
        v = sens.pop()
        return {"valeur": v, "methode": "position des cibles", "source": comparaisons[-1]["source_cible"],
                "justification": f"Toutes les cibles publiées ({len(comparaisons)}) sont "
                                 f"{'au-dessus' if v == 'hausse' else 'en dessous'} du dernier réalisé connu avant "
                                 f"elles.", "comparaisons": comparaisons}
    return {"valeur": "inconnu", "methode": None, "source": None,
            "justification": ("Cibles contradictoires avec le réalisé" if comparaisons else
                              "Ni sens d'évolution publié, ni cible comparable au réalisé") + " : sens inconnu."}


def tendance(s: dict, sens: dict) -> dict:
    reals = sorted((a, r["valeur"]) for a, r in s["realises"].items() if r["valeur"] is not None)
    if len(reals) < 2:
        return {"valeur": "sens inconnu", "raison": "moins de deux valeurs réalisées"}
    (a0, v0), (a1, v1) = reals[-2], reals[-1]
    delta = v1 - v0
    rel = (delta / abs(v0) * 100) if v0 else None
    base = {"de_annee": a0, "a_annee": a1, "de": v0, "a": v1, "variation": round(delta, 6),
            "variation_relative_pct": round(rel, 2) if rel is not None else None}
    if delta == 0 or (rel is not None and abs(rel) <= SEUIL_STABLE_PCT):
        return {"valeur": "stable", **base, "raison": f"variation inférieure ou égale à {SEUIL_STABLE_PCT} %"}
    if sens["valeur"] in ("hausse", "baisse"):
        bon = (delta > 0) == (sens["valeur"] == "hausse")
        return {"valeur": "en progrès" if bon else "en recul", **base,
                "justification": {"sens_souhaite": sens["valeur"], "methode": sens["methode"],
                                  "source": sens["source"]}}
    return {"valeur": "sens inconnu", **base, "raison": sens["justification"]}


def sortie_serie(s: dict) -> dict:
    sens = sens_souhaite(s)
    ecarts = []
    for a in sorted(set(s["realises"]) & set(s["cibles"])):
        r, c = s["realises"][a]["valeur"], s["cibles"][a]["valeur"]
        if r is not None and c is not None:
            ecarts.append({"annee": a, "realise": r, "cible": c, "ecart": round(r - c, 6),
                           "atteinte_publiee": (s["atteinte"].get(a) or {}).get("texte")})
    return {
        "id": s["id"], "code_indicateur": s["code"], "objectif": s["objectif"], "indicateur": s["indicateur"],
        "sous_indicateur": s["sous_indicateur"], "unite": s["unite"],
        "indicateur_de_contexte": {"Oui": True, "Non": False}.get(s["contexte"]),
        "libelles_anterieurs": sorted(s["libelles_anterieurs"]) or None,
        "valeurs": [{"annee": a, "valeur": v["valeur"], "brut": v["brut"], "source": PERF_LIB[v["source"]]}
                    for a, v in sorted(s["realises"].items())],
        "cibles": [{"annee": a, "valeur": v["valeur"], "brut": v["brut"], "source": PERF_LIB[v["source"]],
                    **({"note": v["note"]} if v.get("note") else {})} for a, v in sorted(s["cibles"].items())],
        "ecarts_a_la_cible": ecarts,
        "sens_souhaite": sens,
        "tendance": tendance(s, sens),
        "rapprochement": dict(s["rapprochements"]),
    }


def fiabilite_position_cibles(series: dict) -> dict:
    """Mesure : la règle « position des cibles » appliquée aux séries dont le RAP 2025 publie le sens."""
    ok = ko = 0
    for s in series.values():
        ev = (s["evolution"] or "").lower()
        if ev not in ("hausse", "baisse"):
            continue
        r = sens_souhaite({**s, "evolution": None})
        if r["valeur"] in ("hausse", "baisse"):
            ok += r["valeur"] == ev
            ko += r["valeur"] != ev
    return {"series_testees": ok + ko, "concordantes": ok,
            "taux_concordance_pct": round(ok / (ok + ko) * 100, 1) if ok + ko else None,
            "note": "Règle de repli testée sur les séries dont le sens est publié dans le RAP 2025 : une cible "
                    "inférieure au réalisé peut aussi signifier une cible déjà dépassée."}


# --- 3. Réalisations concrètes --------------------------------------------------------------------------------------


def bloc_realisations(p: str, f2030: dict | None) -> dict:
    f = SITE / "beneficiaires" / f"programme_{p}.json"
    items, src, mill, fichier = [], [], [], None
    if f.exists():
        b = json.loads(f.read_text(encoding="utf-8"))
        fichier = f"beneficiaires/programme_{p}.json"
        a = b.get("associations")
        if a and a.get("top"):
            for t in a["top"][:MAX_REALISATIONS]:
                items.append({"objet": t.get("objet"), "beneficiaire": t["denomination"], "siren": t["siren"],
                              "montant_eur": t["montant_eur"], "eur_sur_100": t.get("eur_sur_100"),
                              "type": "subvention à une association"})
            src.append(a["source"])
            mill.append(a["millesime"])
    fr = None
    if f2030 and p in (f2030.get("par_programme") or {}):
        g = f2030["par_programme"][p]
        fr = {"total_eur": g["total_eur"], "projets": g["projets"], "millesime": f2030["millesime"],
              "source": f2030["source"], "fichier": "beneficiaires/france2030.json",
              "note": "Montants engagés cumulés 2021-2025 ; le détail par bénéficiaire est publié pour l'ensemble de "
                      "France 2030 et par opérateur, pas par programme."}
    if not items and not fr:
        return {"liste": [], "fichier_beneficiaires": fichier, "france2030": None,
                "note": "Aucun objet de dépense nommé disponible pour ce programme dans site/data/beneficiaires/."}
    return {"liste": items, "fichier_beneficiaires": fichier, "millesime": " ; ".join(mill) or None,
            "source": " ; ".join(src) or None, "france2030": fr,
            "note": "Les plus gros objets nommés connus, pas l'ensemble de la dépense du programme."}


# --- 4. Évaluations (Cour des comptes) ------------------------------------------------------------------------------


NON_NEB = re.compile(r"^(rapport|synthese|communique|reponses?|discours|livret|annexes?|conference|cahier|presentation"
                     r"|video|dossier)\b")


def sans_annee(titre: str) -> str:
    return re.sub(r"\s*\(?\b(19|20)\d{2}\)?\s*$", "", propre(titre))


def notes_execution(resoudre: bool = True) -> list[dict]:
    """Notes d'exécution budgétaire (NEB) des pages « Le budget de l'État en <année> » : boutons portant le titre de
    la note (`data-document`) ; pour 2015 et 2016, pages sans titre, le titre vient de la note d'une autre année au même
    nom de fichier (NEB-<année>-<mission>.pdf)."""
    titres_slug, brutes = {}, []
    for a in ANNEES_CC:
        p = page_cc(a)
        if not p.exists():
            continue
        page = f"{CC}/fr/publications/le-budget-de-letat-en-{a}-resultats-et-gestion"
        t = p.read_text(encoding="utf-8")
        for m in re.finditer(r'<a ([^>]*)>', t):
            attrs = m.group(1)
            href = re.search(r'href="([^"]+)"', attrs)
            if not href:
                continue
            url = href.group(1)
            neb = re.search(r"NEB-\d{4}-([^/]*?)(?:_\d)?\.pdf$", url)
            if not (neb or re.match(r"^/fr/documents/\d+$", url)):
                continue
            titre = re.search(r'data-document="([^"]*)"', attrs)
            titre = propre(html.unescape(titre.group(1))) if titre else None
            if titre and NON_NEB.match(norm(titre)):
                continue
            if not neb and not titre:
                continue
            url = url if url.startswith("http") else CC + url
            slug = neb.group(1) if neb else None
            brutes.append({"annee": a, "slug": slug, "url": url, "titre": titre, "page": page})
            if titre and slug:
                titres_slug.setdefault(slug, (titre, a))
    par_url = {}
    for b in brutes:  # une note est souvent liée deux fois (icône puis bouton) : on garde la version titrée
        if b["url"] not in par_url or (b["titre"] and not par_url[b["url"]]["titre"]):
            par_url[b["url"]] = b
    out = []
    docs = json.loads(fichier_documents().read_text(encoding="utf-8")) if fichier_documents().exists() else {}
    for b in par_url.values():
        if "/fr/documents/" in b["url"] and resoudre:
            if not docs.get(b["url"]):
                continue  # page document non résolue en PDF : non publiée
            an = re.search(r"NEB-(\d{4})-", docs[b["url"]])
            if not an or int(an.group(1)) not in (b["annee"], b["annee"] + 1):
                continue  # PDF d'une autre année : rattachement douteux, écarté
            b["page_document"], b["url"] = b["url"], docs[b["url"]]
        if not b["titre"] and b["slug"] in titres_slug:
            b["titre"], ref = titres_slug[b["slug"]]
            b["titre_origine"] = f"titre de la note {ref} au même nom de fichier (page {b['annee']} sans titre)"
        if b["titre"]:
            out.append(b)
    return out


def publications_rss() -> list[dict]:
    f = CACHE_CC / "rss_publications.xml"
    if not f.exists():
        return []
    t = f.read_text(encoding="utf-8")
    out = []
    for it in re.findall(r"<item>(.*?)</item>", t, re.S):
        ti = re.search(r"<title>(.*?)</title>", it, re.S)
        li = re.search(r"<link>(.*?)</link>", it, re.S)
        if ti and li:
            out.append({"titre": html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", ti.group(1))).strip(),
                        "url": li.group(1).strip()})
    return out


def contient(titre: str, nom: str) -> bool:
    return bool(nom) and re.search(rf"(^| ){re.escape(norm(nom))}( |$)", norm(titre)) is not None


def rss_rattachees(rss: list[dict], programmes: dict) -> list[dict]:
    """Publication du flux dont le titre contient le nom exact d'un programme, ou d'une mission d'au moins trois mots
    (un nom d'un mot comme « Culture » ou « Santé » se retrouve dans des titres sans rapport)."""
    out = []
    for r in rss:
        for p, m in programmes.items():
            if contient(r["titre"], m["libelle"]) or (len(norm(m["mission"]).split()) >= 3
                                                       and contient(r["titre"], m["mission"])):
                out.append({**r, "programme": p})
    return out


def bloc_evaluations(p: str, meta: dict, neb: list[dict], rss: list[dict], verifs: dict) -> dict:
    liens, non_verifies = [], 0
    for n in neb:
        if norm(sans_annee(n["titre"])) == norm(meta["mission"]):
            v = verifs.get(n["url"], {})
            if v.get("statut") != 200 or not v.get("pdf"):
                non_verifies += 1
                continue
            liens.append({"type": "note d'exécution budgétaire (NEB)", "annee_execution": n["annee"],
                          "titre": f"Note d'exécution budgétaire {n['annee']} : {meta['mission']}",
                          "titre_publie": n["titre"], "url": n["url"],
                          "page": n["page"], "rattachement": "mission (titre de la note, sans l'année, = nom exact de la mission)"
                          + (f" ; {n['titre_origine']}" if n.get("titre_origine") else ""),
                          "verifie": True, "verifie_le": v["verifie_le"], "statut_http": 200})
    for r in rss:
        if r.get("programme") != p:
            continue
        v = verifs.get(r["url"], {})
        if v.get("statut") != 200:
            non_verifies += 1
            continue
        liens.append({"type": "publication", "titre": r["titre"], "url": r["url"],
                      "rattachement": "titre contenant le nom exact du programme ou de la mission",
                      "verifie": True, "verifie_le": v["verifie_le"], "statut_http": 200})
    liens.sort(key=lambda x: -(x.get("annee_execution") or 0))
    return {"liens": liens, "source": f"{CC} (pages « Le budget de l'État en <année> », flux {CC}/fr/rss/publications)",
            "liens_ecartes_non_verifies": non_verifies,
            "note": None if liens else (
                f"Aucune publication de la Cour des comptes rattachable de façon fiable à la mission « {meta['mission']} »"
                " ou au programme (titre contenant le nom exact) : champ vide.")}


# --- Production -----------------------------------------------------------------------------------------------------


def produire() -> dict:
    racine = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    total_arbre = racine["md"] * 1e9
    meta, plrg = execution_plrg()
    if 2024 not in plrg:
        raise SystemExit("Annexe 1 « état CP » 2024 absente : lancer `python pipeline/realisations.py collecter`")
    autres = defaultdict(dict)
    for a, d in execution_anciennes().items():
        autres[a].update(d)
    for a, d in execution_rap_xls().items():
        autres[a].update(d)
    autres[2022].update(execution_budget_vert_2022())
    lignes = lignes_perf()
    series, stats_rappr = series_indicateurs(lignes)
    par_prog = defaultdict(list)
    for s in series.values():
        par_prog[s["prog"]].append(s)
    f2030p = SITE / "beneficiaires" / "france2030.json"
    f2030 = json.loads(f2030p.read_text(encoding="utf-8")) if f2030p.exists() else None
    neb = notes_execution()
    rss = rss_rattachees(publications_rss(), meta)
    verifs = charger_verifications()

    SORTIE.mkdir(parents=True, exist_ok=True)
    for f in SORTIE.glob("*.json"):
        f.unlink()
    couverture = defaultdict(int)
    reculs = []
    sens_stats = defaultdict(int)
    annees_perf = set()
    for p in sorted(meta):
        prevu = bloc_prevu_depense(p, plrg, autres, total_arbre)
        ind = [sortie_serie(s) for s in sorted(par_prog.get(p, []), key=lambda s: (
            -max([a for a, v in s["realises"].items() if v["valeur"] is not None] or [0]), s["code"] or "~",
            int(s["id"].split("-")[1])))]
        for i in ind:
            sens_stats[i["tendance"]["valeur"]] += 1
            annees_perf |= {v["annee"] for v in i["valeurs"] if v["valeur"] is not None}
            t = i["tendance"]
            if (t["valeur"] == "en recul" and i["sens_souhaite"]["methode"] == "colonne evolution"
                    and propre(i["unite"]) == "%" and not i["indicateur_de_contexte"] and t["a_annee"] >= 2024
                    and 0 <= t["de"] <= 100 and 0 <= t["a"] <= 100):
                reculs.append({"programme": p, "indicateur": i["indicateur"], "sous_indicateur": i["sous_indicateur"],
                               "unite": i["unite"], **{k: t[k] for k in ("de_annee", "a_annee", "de", "a", "variation",
                                                                        "variation_relative_pct")},
                               "sens_souhaite": i["sens_souhaite"]["valeur"],
                               "methode": i["sens_souhaite"]["methode"]})
        real = bloc_realisations(p, f2030)
        ev = bloc_evaluations(p, meta[p], neb, rss, verifs)
        obj = {
            "millesime": "Exécution 2010-2025 selon disponibilité (voir chaque année) ; performance : RAP et PAP 2015 à 2025",
            "source": " ; ".join(sorted({PLRG[a]["source"] for a in plrg} | {PERF_SRC[k] for k, *_ in PERF})),
            "avertissement": AVERTISSEMENT,
            "programme": p, "libelle": meta[p]["libelle"], "mission": meta[p]["mission"],
            "unite_montants": "euros (crédits de paiement)",
            "prevu_depense": prevu,
            "resultats_mesures": {
                "indicateurs": ind,
                "note": None if ind else "Aucun indicateur de performance publié pour ce programme dans les RAP et PAP "
                                         "collectés.",
                "lecture": "Valeurs réalisées et cibles par année ; « brut » = valeur publiée avant nettoyage. Le sens "
                           "souhaité vient de la colonne `evolution` du RAP 2025, sinon de la position des cibles par "
                           f"rapport au réalisé, sinon il est inconnu. « Stable » : variation de {SEUIL_STABLE_PCT} % "
                           "ou moins entre les deux dernières valeurs.",
            },
            "realisations_concretes": real,
            "evaluations": ev,
        }
        dump(SORTIE / f"{p}.json", obj)
        couverture["programmes"] += 1
        couverture["prevu_depense"] += bool(prevu["annees"])
        couverture["prevu_depense_2024"] += any(a["annee"] == 2024 and a["depense_constatee_eur"] is not None
                                                for a in prevu["annees"])
        couverture["resultats_mesures"] += bool(ind)
        couverture["realisations_concretes"] += bool(real["liste"] or real["france2030"])
        couverture["evaluations"] += bool(ev["liens"])
    reculs.sort(key=lambda r: -abs(r["variation"]))
    index = {
        "millesime": "Exécution 2010-2025, performance 2012-2025 (selon disponibilité)",
        "source": "data.economie.gouv.fr (PLRG 2023-2025, RAP de synthèse 2019-2020, budget vert PLF 2024, exécution "
                  "2010-2014, LFI 2011-2014, RAP/PAP 2015-2025) ; ccomptes.fr (notes d'exécution budgétaire)",
        "avertissement": AVERTISSEMENT,
        "programmes": sorted(meta), "fichiers": {p: f"realisations/{p}.json" for p in sorted(meta)},
        "couverture": dict(couverture),
        "trous_execution": TROUS_EXECUTION,
        "annees_execution": sorted(set(plrg) | {a for a in autres if autres[a]}),
        "annees_performance": sorted(annees_perf),
        "sources_performance": {k: {"libelle": lib, "source": s} for k, lib, _, s in PERF},
        "rapprochement_indicateurs": stats_rappr,
        "tendances": dict(sens_stats),
        "fiabilite_regle_position_cibles": fiabilite_position_cibles(series),
        "reculs_les_plus_marques": reculs[:20],
        "reculs_criteres": "Indicateurs en %, valeurs entre 0 et 100, hors indicateurs de contexte, dernière valeur 2024 "
                           "ou 2025, sens souhaité publié (colonne evolution du RAP 2025), classés par baisse en points.",
        "evaluations": {"notes_execution_trouvees": len(neb),
                        "annees": sorted({n["annee"] for n in neb}),
                        "liens_verifies": sum(1 for v in verifs.values() if v.get("statut") == 200)},
    }
    dump(SORTIE / "index.json", index)
    return index["couverture"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("etape", choices=["collecter", "produire"])
    ap.add_argument("--budget", type=float, default=420, help="secondes allouées à la vérification des liens")
    a = ap.parse_args()
    if a.etape == "collecter":
        collecter(a.budget)
    else:
        print(json.dumps(produire(), ensure_ascii=False))


if __name__ == "__main__":
    main()
