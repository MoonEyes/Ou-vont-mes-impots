"""Opérateurs de l'État et agences : financement par l'État, ressources, emplois, par année (exécution 2020 à 2024,
crédits votés 2023 à 2025).

Source : annexe « Opérateurs de l'État » (« jaune ») aux projets de loi de finances 2024, 2025 et 2026, en PDF. Le site
budget.gouv.fr refuse les scripts (403) : les PDF sont lus sur le miroir officiel de l'Assemblée nationale (dépôt des
annexes au Parlement). Chaque jaune donne l'exécution des trois derniers exercices connus (saisie des RAP) et les crédits
de l'année en cours (LFI) ; l'exécution la plus récente d'un même exercice fait foi.

Entrées :
  data/lake/etat/an__jaune_operateurs_plf<AAAA>/jaune_operateurs_plf<AAAA>.pdf   (commande « collecter », réseau)
  data/lake/etat/datagouv__...-jaune-operateurs-de-letat-liste-des-operateurs-et-categories/  (liste et chefs de file)
  API Recherche d'entreprises (SIREN par dénomination, cache data/lake/_cache/operateurs_siren.json)
Sorties :
  site/data/operateurs/operateurs.json   un objet par opérateur ou catégorie d'opérateurs du jaune, années 2020 à 2025
  site/data/operateurs/index.json        totaux par année, couverture, sources, recherche préalable, limites

Commandes :
  python pipeline/operateurs.py collecter   télécharge les jaunes (miroir Assemblée nationale), sans contournement
  python pipeline/operateurs.py siren       complète le cache SIREN (réseau, API Recherche d'entreprises)
  python pipeline/operateurs.py produire    sans réseau (cache d'analyse des PDF : data/lake/_cache/operateurs/)

Montants publiés en euros. Le jaune les donne en milliers d'euros, sauf la table d'exécution des taxes affectées
(millions d'euros, malgré l'en-tête « milliers » : France Compétences 11 250 = 11,25 Md€) et la table de prévision des
taxes affectées (euros). Aucune personne physique : la rémunération des dirigeants n'est publiée qu'en agrégat (somme
des dix plus hautes rémunérations brutes de chaque opérateur, article 179 de la loi de finances pour 2020) ; les
commentaires libres de cette table, qui peuvent décrire des situations individuelles, ne sont jamais repris.
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "operateurs"
CACHE = LAKE / "_cache" / "operateurs"
CACHE_SIREN = LAKE / "_cache" / "operateurs_siren.json"
VERSION_ANALYSE = 6  # à incrémenter quand l'analyse des PDF change (invalide le cache)

MIROIR = "Assemblée nationale (dépôt des annexes au Parlement)"
JAUNES = {
    2024: {"url": "https://www2.assemblee-nationale.fr/static/16/pdf/Annexes_PLF/Op%C3%A9rateurs_%C3%89tat.pdf",
           "titre": "Annexe au projet de loi de finances pour 2024, « Opérateurs de l'État »"},
    2025: {"url": "https://www2.assemblee-nationale.fr/static/17/Annexes-DL/PLF2025-Jaunes/22-Jaune_operateurs.pdf",
           "titre": "Annexe au projet de loi de finances pour 2025, « Opérateurs de l'État »"},
    2026: {"url": "https://www2.assemblee-nationale.fr/static/17/Annexes-DL/PLF-2026/22-Jaune2026_Operateurs.pdf",
           "titre": "Annexe au projet de loi de finances pour 2026, « Opérateurs de l'État »"},
}
LISTES = {a: LAKE / "etat" / (f"datagouv__projet-de-loi-de-finances-pour-{a}-plf-{a}-jaune-operateurs-de-letat-"
                              "liste-des-operateurs-et-categories") for a in (2024, 2025, 2026)}
SRC_LISTE = "data.gouv.fr, PLF {a}, jaune « Opérateurs de l'État », liste des opérateurs et catégories"
SRC_API = "API Recherche d'entreprises (recherche-entreprises.api.gouv.fr), SIREN par dénomination"
ANNEES = list(range(2019, 2026))
HEADERS = {"User-Agent": "ou-vont-mes-impots/0.1 (projet citoyen open source)"}


def chemin_pdf(plf: int) -> Path:
    return LAKE / "etat" / f"an__jaune_operateurs_plf{plf}" / f"jaune_operateurs_plf{plf}.pdf"


def src_jaune(plf: int) -> str:
    return f"{JAUNES[plf]['titre']}, miroir {MIROIR} : {JAUNES[plf]['url']}"


# --- Normalisation des noms ------------------------------------------------------------------------------------------


def sans_accent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    """Clé de comparaison : minuscules, sans accent, sans ponctuation ni espace."""
    return re.sub(r"[^a-z0-9]", "", sans_accent(s or "").lower())


def propre(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("’", "'")).strip()


def sigle(nom: str) -> str | None:
    m = re.match(r"^([A-Za-zÀ-ÿ0-9'’&\-]{2,15}) [-–] ", nom)
    return m.group(1) if m else None


def cle(nom: str) -> str:
    """Identifiant stable d'une ligne du jaune d'une année à l'autre : le sigle s'il existe, sinon le nom."""
    nom = ALIAS.get(norm(nom), nom)
    s = sigle(nom) or (nom.split(" - ")[0] if " - " in nom else None)
    return norm(ALIAS.get(norm(s or ""), s or nom))


# Changements de nom entre jaunes (même opérateur).
ALIAS = {norm("Pôle emploi"): "France Travail", norm("SGP - Société du Grand Paris"): "SGP",
         norm("ENSTA Paris"): "ENSTA",
         norm("Conseil national des communes « Compagnon de la Libération »"): "Ordre de la Libération"}


# --- Lecture des PDF (pdfplumber) ------------------------------------------------------------------------------------

NOMBRE = re.compile(r"^-?\d{1,3}$|^-?\d+$")
GROUPE = re.compile(r"^\d{3}$")


def lignes_page(page) -> list[list[dict]]:
    mots = page.extract_words(x_tolerance=1.5, keep_blank_chars=False)
    par_top: dict[int, list] = {}
    for w in sorted(mots, key=lambda w: (round(w["top"]), w["x0"])):
        t = next((k for k in par_top if abs(k - w["top"]) <= 2.5), None)
        par_top.setdefault(t if t is not None else w["top"], []).append(w)
    return [sorted(v, key=lambda w: w["x0"]) for _, v in sorted(par_top.items())]


def texte(ws) -> str:
    return propre(" ".join(w["text"] for w in ws))


def separer(ws, x_min: float) -> tuple[list[dict], list[tuple[float, float, float]]]:
    """Sépare une ligne en mots de texte et nombres (valeur, x0, x1) à droite de x_min.

    Un nombre du jaune s'écrit avec des espaces de milliers (« 1 000 883 ») : des mots numériques séparés par moins de
    4 points, le suivant à trois chiffres, forment un seul nombre.
    """
    txt, nums = [], []
    i = 0
    while i < len(ws):
        w = ws[i]
        if w["x0"] >= x_min and NOMBRE.match(w["text"]):
            v, x0, x1 = w["text"], w["x0"], w["x1"]
            while i + 1 < len(ws) and GROUPE.match(ws[i + 1]["text"]) and ws[i + 1]["x0"] - x1 < 4.0 \
                    and len(v.lstrip("-").split(" ")[-1]) <= 3:
                i += 1
                v, x1 = v + " " + ws[i]["text"], ws[i]["x1"]
            nums.append((float(v.replace(" ", "")), x0, x1))
        else:
            txt.append(w)
        i += 1
    return txt, nums


def colonnes(nums, ancres: list[float], cote: str = "x1") -> dict[int, float]:
    """Range chaque nombre dans la colonne d'ancre la plus proche (bord droit des nombres alignés à droite)."""
    res = {}
    for v, x0, x1 in nums:
        x = x1 if cote == "x1" else (x0 + x1) / 2
        j = min(range(len(ancres)), key=lambda k: abs(ancres[k] - x))
        if abs(ancres[j] - x) < 40:
            res[j] = res.get(j, 0.0) + v
    return res


def sommaire(pdf) -> dict[str, int]:
    """Titre de section -> index de page (0) d'après le sommaire et le décalage page imprimée / index."""
    entrees = {}
    for i in range(min(6, len(pdf.pages))):
        for ws in lignes_page(pdf.pages[i]):
            t = texte(ws)
            m = re.match(r"^(.*?[A-Za-zéÉ)])[\s.]+(\d{1,3})$", t)
            if m and len(m.group(1)) > 8:
                entrees.setdefault(propre(m.group(1).rstrip(". ")), int(m.group(2)))
    res = {}
    for titre, num in entrees.items():
        for d in (-1, 0, -2, 1):
            i = num + d
            if 0 <= i < len(pdf.pages):
                t = norm(" ".join(w["text"] for w in pdf.pages[i].extract_words()[:80]))
                if norm(titre)[:40] in t:
                    res[titre] = i
                    break
    return res


def bornes(som: dict[str, int], debut: str, n_pages: int) -> tuple[int, int] | None:
    k = next((t for t in som if t.startswith(debut)), None)
    if k is None:
        return None
    i = som[k]
    suivants = sorted(v for v in som.values() if v > i)
    return i, (suivants[0] if suivants else n_pages)


ENTETE_MOTS = {"Opérateurs", "Opérateur", "Programmes", "Titres", "Autorisations", "d'engagement", "Exécution",
               "Intitulé"}


def zone_donnees(lignes: list[list[dict]], marqueur) -> int:
    """Indice de la première ligne de données (après la dernière ligne d'en-tête du tableau)."""
    dernier = -1
    for i, ws in enumerate(lignes[:40]):
        if marqueur(ws):
            dernier = i
    return dernier + 1


def est_pied(ws, page) -> bool:
    t = texte(ws)
    return ws[0]["top"] < 75 or ws[0]["top"] > page.height - 40 or t.startswith("Annexe au projet de loi") \
        or t in ("PLF 2024", "Opérateurs de l’État", "Opérateurs de l'État") or re.fullmatch(r"\d{1,3}", t) is not None


CATEGORIES = [("Subventions pour charges de service public", "32", "scsp"),
              ("Subvention pour charges d'investissement", "53", "sci"),
              ("Dotations en fonds propres", "72", "dfp"),
              ("Transferts", "6", "transferts")]


def lire_financement(pdf, pages: tuple[int, int], nb_col: int) -> tuple[list[dict], dict]:
    """Tableau « Financement ... des opérateurs par le budget de l'État » : nom, programmes financeurs, montants par
    catégorie (AE et CP pour chaque année, en milliers d'euros)."""
    res, total = [], {}
    cour = None
    attente_nom = []
    mode = None
    for ip in range(*pages):
        page = pdf.pages[ip]
        lignes = lignes_page(page)
        debut = zone_donnees(lignes, lambda ws: texte(ws).startswith("Titres et catégories"))
        ancres = sorted(w["x1"] for ws in lignes[:debut] for w in ws if w["text"] in ("d'engagement", "paiement"))
        if len(ancres) != nb_col:
            continue
        x_min = min(ancres) - 70
        marge = min((ws[0]["x0"] for ws in lignes[debut:] if not est_pied(ws, page)), default=0)
        for ws in lignes[debut:]:
            if est_pied(ws, page):
                continue
            txt, nums = separer(ws, x_min)
            t = texte(txt)
            if re.match(r"^P\d{3}\b", t) or (mode == "prog" and not nums and ws[0]["x0"] - marge < 2):
                if mode != "prog" and attente_nom:
                    cour = {"nom": propre(" ".join(attente_nom)), "programmes": [], "montants": {}}
                    res.append(cour)
                    attente_nom = []
                if cour is not None:
                    cour["programmes"] += [p for p in re.findall(r"\bP(\d{3})\b", t) if p not in cour["programmes"]]
                mode = "prog"
                continue
            if t.startswith("(titre"):
                continue
            if t.startswith("Total") and nums:
                total = {j: v for j, v in colonnes(nums, ancres).items()}
                mode = None
                continue
            lib = next((c for c in CATEGORIES if t.startswith(c[0][:18])), None)
            if lib and ws[0]["x0"] - marge >= 2:
                if cour is not None:
                    cols = colonnes(nums, ancres)
                    m = cour["montants"].setdefault(lib[2], {})
                    for j, v in cols.items():
                        m[j] = m.get(j, 0.0) + v
                mode = "cat"
                continue
            if ws[0]["x0"] - marge < 2 and t and not nums:
                if mode in ("prog", "cat", None) and attente_nom and mode != "nom":
                    attente_nom = []
                attente_nom.append(t)
                mode = "nom"
    return res, total


def lire_simple(pdf, pages: tuple[int, int], ancre, nb_col: int, noms_connus: set[str],
                cote: str = "x1") -> tuple[list[dict], dict]:
    """Tableau à une ligne par opérateur : nom puis nb_col nombres. `ancre(lignes)` renvoie les abscisses des
    colonnes de la page. Les noms coupés sur deux lignes sont recollés (nom connu ou suite en minuscule)."""
    res, total = [], {}
    prefixes = {k[:i] for k in noms_connus for i in range(8, len(k) + 1)}
    for ip in range(*pages):
        page = pdf.pages[ip]
        lignes = lignes_page(page)
        r = ancre(lignes)
        if not r or len(r[0]) != nb_col:
            continue
        anc, haut = r
        x_min = min(anc) - 60
        debut = next((i for i, ws in enumerate(lignes) if ws[0]["top"] > haut + 2), len(lignes))
        for ws in lignes[debut:]:
            if est_pied(ws, page) or texte(ws) in ("aidés", "(1)", "(1) (1)", "(1) (1) (1) (1)"):
                continue
            txt, nums = separer(ws, x_min)
            t = texte(txt)
            if not t and nums and res:  # nombres seuls sur la ligne (nom long au-dessus)
                cols = colonnes(nums, anc, cote)
                for j, v in cols.items():
                    res[-1]["valeurs"].setdefault(j, v)
                continue
            if not t:
                continue
            if t.startswith("Total"):
                total = colonnes(nums, anc, cote)
                continue
            precedent = res[-1] if res else None
            joint = norm((precedent["nom"] + " " + t) if precedent else t)
            suite = precedent is not None and not nums and (
                joint in prefixes or joint in noms_connus
                or (norm(precedent["nom"]) not in noms_connus and (t[:1].islower() or t[:1] in "(-–")))
            if suite and precedent.get("ouvert", True):
                precedent["nom"] = propre(precedent["nom"] + " " + t)
                if norm(precedent["nom"]) in noms_connus:
                    precedent["ouvert"] = False
                continue
            res.append({"nom": t, "valeurs": colonnes(nums, anc, cote), "ouvert": norm(t) not in noms_connus})
    for r in res:
        r.pop("ouvert", None)
    return res, total


def ancres_mots(mots: tuple[str, ...], n: int, cote: str = "x1"):
    """Abscisses des colonnes d'après des mots d'en-tête ; renvoie (abscisses, top de la dernière ligne d'en-tête)."""
    def f(lignes):
        ws_ = [w for ws in lignes[:30] for w in ws if w["text"] in mots]
        xs = sorted((w[cote] if cote != "c" else (w["x0"] + w["x1"]) / 2) for w in ws_)
        return (xs, max(w["top"] for w in ws_)) if len(xs) == n else None
    return f


def ancres_annees(n: int):
    def f(lignes):
        for ws in lignes[:30]:
            ans = [w for w in ws if re.fullmatch(r"20\d\d", w["text"])]
            if len(ans) == n and not any(w["text"] == "Exécution" for w in ws):
                return [w["x1"] for w in ans], ans[0]["top"]
        return None
    return f


def lire_remunerations(pdf, pages: tuple[int, int]) -> dict[str, dict[str, float]]:
    """Somme des dix plus hautes rémunérations brutes (k€) par entité ; commentaires jamais repris."""
    res: dict[str, dict[str, float]] = {}
    entite = None
    attente: list[str] = []
    for ip in range(*pages):
        page = pdf.pages[ip]
        lignes = lignes_page(page)
        anc = [w["x1"] for ws in lignes[:30] for w in ws if w["text"] == "k€"]
        if not anc:
            continue
        for ws in lignes:
            if est_pied(ws, page):
                continue
            t = texte(ws)
            if re.match(r"^20\d\d\b", t) and entite:
                txt, nums = separer(ws[1:], 0)
                vals = [v for v, x0, x1 in nums if abs(x1 - anc[0]) < 30]
                if vals:
                    res[entite][ws[0]["text"]] = vals[0]
                continue
            m = re.match(r"^(.+?) [–-] (EPA|EPIC|EPSCP|EPSCT|GIP|EPST|EPCSCP|EPCS|EP|SA|association|Association|"
                         r"Autre|sui generis|Sui generis|Fondation|EPN|GIE|SAS|AAI|API|[A-Za-z ]{2,30})$", t)
            if m and t.upper()[:20] == t[:20].upper() and not t.startswith("Opérateur"):
                entite = propre(" ".join(attente + [m.group(1)]))
                res.setdefault(entite, {})
                attente = []
            elif t.upper() == t and len(t) > 6 and not re.search(r"\d", t) and ws[0]["x0"] < 80:
                attente.append(t)  # dénomination coupée : la ligne suivante porte la fin et le statut
            else:
                attente = []
    return res


def lire_budgets_initiaux(pdf, pages: tuple[int, int]) -> dict[str, dict[str, float]]:
    """Pages « Budgets initiaux » : par opérateur, total des charges et des produits du compte de résultat (k€),
    subventions de l'État et fiscalité affectée."""
    res: dict[str, dict] = {}
    nom = None
    attente = False
    for ip in range(*pages):
        page = pdf.pages[ip]
        for ws in lignes_page(page):
            if est_pied(ws, page):
                continue
            t = texte(ws)
            if t in ("OPÉRATEUR", "OPERATEUR", "CATÉGORIE D'OPÉRATEURS", "CATÉGORIE"):
                attente, nom = True, None
                continue
            if attente:
                nom, attente = t, False
                res.setdefault(nom, {})
                continue
            if nom is None:
                continue
            if t.startswith("Total des charges") and "charges" not in res[nom]:
                _, nums = separer(ws, ws[0]["x0"] + 60)
                if nums:
                    res[nom]["charges"] = nums[0][0]
                if len(nums) >= 2 and "Total des produits" in t:
                    res[nom]["produits"] = nums[1][0]
    return res


def analyser(plf: int) -> dict:
    """Analyse un jaune (lente : ~1 à 3 min) ; résultat mis en cache."""
    import pdfplumber
    src = chemin_pdf(plf)
    cache = CACHE / f"jaune_plf{plf}.json"
    if cache.exists():
        c = json.loads(cache.read_text(encoding="utf-8"))
        if c.get("version") == VERSION_ANALYSE and c.get("taille_pdf") == src.stat().st_size:
            return c
    t0 = time.time()
    pdf = pdfplumber.open(src)
    n = len(pdf.pages)
    som = sommaire(pdf)
    ex = [plf - 4, plf - 3, plf - 2]
    out = {"version": VERSION_ANALYSE, "taille_pdf": src.stat().st_size, "plf": plf, "pages": n,
           "exercices": ex, "sommaire": som}
    b = bornes(som, f"Financement {ex[0]}/{ex[2]} des opérateurs par le budget", n)
    out["financement_execution"], out["financement_execution_total"] = lire_financement(pdf, b, 6)
    b = bornes(som, f"Financement {plf - 1}/{plf} des opérateurs par le budget", n)
    out["financement_lfi"], out["financement_lfi_total"] = lire_financement(pdf, b, 4)
    connus = {norm(r["nom"]) for r in out["financement_execution"] + out["financement_lfi"]}
    connus |= {norm(x) for x in noms_liste(plf)}
    out["noms_connus"] = sorted(connus)
    for cle_, titre, anc, nb, cote in (
            ("taxes_execution", f"Financement {ex[0]}/{ex[2]} des opérateurs par les taxes", ancres_annees(3), 3, "x1"),
            ("ressources_propres", f"Ressources propres {ex[0]}/{ex[2]}", ancres_annees(3), 3, "x1"),
            ("masse_salariale", f"Masse salariale {ex[0]}/{ex[2]}", ancres_annees(3), 3, "x1"),
            ("emplois_execution", f"Emplois {ex[0]}/{ex[2]}", ancres_mots(("plafond",), 6), 6, "x1"),
            ("emplois_lfi", f"Emplois {plf - 1}/{plf}",
             ancres_mots(("(1)", "plafond", "contrats", "apprentis"), 12, "c"), 12, "c"),
            ("taxes_lfi", f"Financement {plf - 1}/{plf} des opérateurs par les taxes", None, 2, "x1")):
        b = bornes(som, titre, n)
        if b is None:
            out[cle_], out[cle_ + "_total"] = [], {}
            continue
        if anc is None:  # prévision des taxes affectées : colonnes déduites des nombres
            anc = ancres_taxes_lfi(pdf, b)
        out[cle_], out[cle_ + "_total"] = lire_simple(pdf, b, anc, nb, connus, cote)
    b = bornes(som, "Somme des dix plus importantes", n)
    out["remunerations"] = lire_remunerations(pdf, b) if b else {}
    b = next(((v, n) for t, v in som.items() if t.startswith("Budget initiaux") or t.startswith("Budgets initiaux")),
             None)
    out["budgets_initiaux"] = lire_budgets_initiaux(pdf, b) if b else {}
    out["duree_s"] = round(time.time() - t0, 1)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def ancres_taxes_lfi(pdf, b):
    xs = []
    for ip in range(*b):
        for ws in lignes_page(pdf.pages[ip]):
            _, nums = separer(ws, 300)
            if len(nums) == 2:
                xs.append([x1 for _, _, x1 in nums])
    if not xs:
        return lambda lignes: None
    a = [sorted(c)[len(c) // 2] for c in zip(*xs)]

    def f(lignes):
        haut = max((ws[0]["top"] for ws in lignes[:30] if any("opérateur" in w["text"] for w in ws)), default=0)
        return a, haut
    return f


def noms_liste(plf: int) -> list[str]:
    """Libellés « opérateur ou catégorie » de la liste data.gouv du même PLF."""
    return [r["ligne"] for r in lire_liste(plf)]


def lire_liste(plf: int) -> list[dict]:
    import csv
    import io
    d = LISTES.get(plf)
    if not d or not d.exists():
        return []
    f = sorted(d.glob("*.csv"))[0]
    lignes = list(csv.reader(io.StringIO(f.read_bytes().decode("cp1252")), delimiter=";"))
    i0 = next(i for i, r in enumerate(lignes) if r and propre(r[0]).startswith("Opérateur ou catégorie"))
    res = []
    for r in lignes[i0 + 1:]:
        if len(r) < 4 or not propre(r[0]):
            continue
        m = re.search(r"(\d{3})\s*[–-]\s*(.+)$", r[3].replace("\n", " "))
        mission = propre(r[3].split("\n")[0]) if "\n" in r[3] else None
        res.append({"ligne": propre(r[0]), "membre": propre(r[1]) or None, "statut": propre(r[2]) or None,
                    "programme": m.group(1) if m else None, "programme_libelle": propre(m.group(2)) if m else None,
                    "mission": mission})
    return res


# --- Assemblage par opérateur et par année -------------------------------------------------------------------------

UNITE = {"financement": 1e3, "taxes_execution": 1e6, "taxes_lfi": 1.0, "ressources_propres": 1e3,
         "masse_salariale": 1e3, "budgets_initiaux": 1e3, "remunerations": 1e3}
CATS = [c[2] for c in CATEGORIES]


def r0(x):
    return None if x is None else round(x, 0)


def construire(jaunes: dict[int, dict]) -> dict:
    """Fusionne les jaunes : pour chaque exercice, le jaune le plus récent qui en donne l'exécution fait foi."""
    ops: dict[str, dict] = {}
    non_reconnus: list = []
    listes = {plf: lire_liste(plf) for plf in jaunes}

    bruts = {}
    for plf in sorted(jaunes):
        bruts.update({norm(r["nom"]): r["nom"] for r in jaunes[plf]["financement_execution"]
                      + jaunes[plf]["financement_lfi"]})
        bruts.update({norm(r["ligne"]): r["ligne"] for r in listes[plf]})

    def complet(nom: str) -> str | None:
        """Nom complet connu dont `nom` (ligne coupée d'un tableau) est le début ; None si inconnu ou ambigu."""
        n = norm(nom)
        if n in bruts:
            return bruts[n]
        c = {v for k, v in bruts.items() if k.startswith(n)} if len(n) >= 12 else set()
        return c.pop() if len(c) == 1 else (nom if sigle(nom) else None)

    def op(nom: str) -> dict:
        nom = complet(nom) or nom
        k = cle(nom)
        if k not in ops:
            ops[k] = {"id": k, "nom": nom, "annees": {}, "noms_sources": set()}
        ops[k]["noms_sources"].add(nom)
        return ops[k]

    def annee(o, a):
        return o["annees"].setdefault(str(a), {})

    for plf in sorted(jaunes):  # du plus ancien au plus récent : le plus récent écrase
        j = jaunes[plf]
        ex = j["exercices"]
        src = f"jaune PLF {plf}"
        for r in j["financement_execution"]:
            o = op(r["nom"])
            o["nom"] = r["nom"]
            for i, a in enumerate(ex):
                fin = {c: {"ae_eur": r0(m.get(str(2 * i), m.get(2 * i)) * UNITE["financement"])
                           if (m.get(str(2 * i), m.get(2 * i))) is not None else None,
                           "cp_eur": r0(m.get(str(2 * i + 1), m.get(2 * i + 1)) * UNITE["financement"])
                           if (m.get(str(2 * i + 1), m.get(2 * i + 1))) is not None else None}
                       for c, m in r["montants"].items()}
                fin = {c: v for c, v in fin.items() if v["ae_eur"] is not None or v["cp_eur"] is not None}
                if not fin:
                    continue
                d = annee(o, a)
                d["financement_etat"] = fin
                d["programmes_financeurs"] = r["programmes"]
                d.setdefault("sources", {})["financement_etat"] = src
                d["nature"] = "execution"
        for r in j["financement_lfi"]:
            o = op(r["nom"])
            fin = {c: {"ae_eur": r0(m[k0] * 1e3) if (k0 := next((x for x in ("0", 0) if x in m), None)) is not None
                       else None,
                       "cp_eur": r0(m[k1] * 1e3) if (k1 := next((x for x in ("1", 1) if x in m), None)) is not None
                       else None} for c, m in r["montants"].items()}
            fin = {c: v for c, v in fin.items() if v["ae_eur"] is not None or v["cp_eur"] is not None}
            if fin:
                d = annee(o, plf - 1)
                d["credits_votes_lfi"] = fin
                d.setdefault("programmes_financeurs", r["programmes"])
                d.setdefault("sources", {})["credits_votes_lfi"] = src
                d.setdefault("nature", "lfi")
        for cle_tab, champ, unite in (("taxes_execution", "taxes_affectees_eur", UNITE["taxes_execution"]),
                                      ("ressources_propres", "ressources_propres_eur", 1e3),
                                      ("masse_salariale", "masse_salariale_eur", 1e3)):
            for r in j[cle_tab]:
                if not r["valeurs"] or complet(r["nom"]) is None:
                    non_reconnus.append((plf, cle_tab, r["nom"]))
                    continue
                o = op(r["nom"])
                for i, a in enumerate(ex):
                    v = r["valeurs"].get(str(i), r["valeurs"].get(i))
                    if v is not None:
                        d = annee(o, a)
                        d[champ] = r0(v * unite)
                        d.setdefault("sources", {})[champ] = src
                        d.setdefault("nature", "execution")
        for r in j["emplois_execution"]:
            if not r["valeurs"] or complet(r["nom"]) is None:
                non_reconnus.append((plf, "emplois_execution", r["nom"]))
                continue
            o = op(r["nom"])
            for i, a in enumerate(ex):
                sp, hp = (r["valeurs"].get(str(2 * i), r["valeurs"].get(2 * i)),
                          r["valeurs"].get(str(2 * i + 1), r["valeurs"].get(2 * i + 1)))
                if sp is not None or hp is not None:
                    d = annee(o, a)
                    d["etpt_sous_plafond"], d["etpt_hors_plafond"] = sp, hp
                    d.setdefault("sources", {})["etpt"] = src
                    d.setdefault("nature", "execution")
        for r in j["emplois_lfi"]:
            v = r["valeurs"]
            if not v or complet(r["nom"]) is None:
                continue
            pl = v.get("2", v.get(2))
            if pl is not None:
                o = op(r["nom"])
                d = annee(o, plf - 1)
                d["plafond_emplois_lfi"] = pl
                d.setdefault("sources", {})["plafond_emplois_lfi"] = src
                d.setdefault("nature", "lfi")
        for r in j["taxes_lfi"]:
            v = r["valeurs"].get("0", r["valeurs"].get(0))
            if v is not None and plf - 1 == 2025:  # seule prévision publiée sans exécution : 2025
                o = op(r["nom"])
                d = annee(o, 2025)
                d["taxes_affectees_prevision_eur"] = r0(v)
                d.setdefault("sources", {})["taxes_affectees_prevision_eur"] = src
        for nom, b in j["budgets_initiaux"].items():
            if not b.get("charges"):
                continue
            o = ops.get(cle(nom))
            if o is None:
                continue
            d = annee(o, plf - 1)
            d["budget_initial"] = {"charges_eur": r0(b["charges"] * 1e3),
                                   "produits_eur": r0(b["produits"] * 1e3) if b.get("produits") else None}
            d.setdefault("sources", {})["budget_initial"] = src
    # Référentiel (liste data.gouv du PLF le plus récent qui cite l'opérateur) : chef de file, statut, membres
    for plf in sorted(listes):
        for r in listes[plf]:
            o = ops.get(cle(r["ligne"]))
            if o is None:
                o = op(r["ligne"])
            o["programme_chef_de_file"] = r["programme"]
            o["programme_chef_de_file_libelle"] = r["programme_libelle"]
            o["mission_chef_de_file"] = r["mission"]
            o["source_referentiel"] = SRC_LISTE.format(a=plf)
            o["plf_liste"] = plf
            if r["membre"]:
                o.setdefault("membres_par_plf", {}).setdefault(plf, []).append(
                    {"nom": r["membre"], "statut": r["statut"]})
            else:
                o["statut"] = r["statut"]
    for o in ops.values():
        mp = o.pop("membres_par_plf", None)
        if mp:
            o["niveau"] = "categorie"
            o["membres"] = mp[max(mp)]
            o["statut"] = sorted({m["statut"] for m in o["membres"] if m["statut"]})[0] if o["membres"] else None
        else:
            o["niveau"] = "operateur"
            o.setdefault("statut", None)
        o["noms_sources"] = sorted(o["noms_sources"])
        o["sigle"] = sigle(o["nom"])
    # Rémunérations (somme des dix plus hautes) : rattachées à l'opérateur ou au membre de catégorie
    index_noms = {}
    for o in ops.values():
        for n in o["noms_sources"]:
            index_noms[norm(n.split(" - ", 1)[1] if " - " in n else n)] = (o, None)
            index_noms[norm(n)] = (o, None)
        for m in o.get("membres", []):
            index_noms[norm(m["nom"])] = (o, m)
    non_rattachees = {}
    for plf in sorted(jaunes):
        for ent, val in jaunes[plf]["remunerations"].items():
            if not ent[:1].isupper():  # fin de dénomination coupée sans son début : non attribuable
                continue
            cible = index_noms.get(norm(ent))  # dénomination identique seulement (pas d'à-peu-près)
            for a, v in val.items():
                eur = r0(v * 1e3)
                if cible is None:
                    non_rattachees.setdefault(ent, {})[a] = eur
                elif cible[1] is not None:
                    cible[1].setdefault("dix_plus_hautes_remunerations_eur", {})[a] = eur
                else:
                    d = annee(cible[0], int(a))
                    d["dix_plus_hautes_remunerations_eur"] = eur
                    d.setdefault("sources", {})["dix_plus_hautes_remunerations_eur"] = f"jaune PLF {plf}"
    for o in ops.values():
        for a, d in o["annees"].items():
            fin = d.get("financement_etat")
            if fin:
                d["financement_etat_total_cp_eur"] = r0(sum((v["cp_eur"] or 0) for v in fin.values()))
            lfi = d.get("credits_votes_lfi")
            if lfi:
                d["credits_votes_lfi_total_cp_eur"] = r0(sum((v["cp_eur"] or 0) for v in lfi.values()))
        o["annees"] = {a: o["annees"][a] for a in sorted(o["annees"]) if int(a) in ANNEES}
    return {"operateurs": ops, "remunerations_non_rattachees": non_rattachees, "non_reconnus": non_reconnus}


# --- SIREN (API Recherche d'entreprises, par dénomination) ---------------------------------------------------------

API = "https://recherche-entreprises.api.gouv.fr/search"


def requete_siren(nom: str) -> str:
    return nom.split(" - ", 1)[1] if " - " in nom and sigle(nom) else nom


def choisir(nom: str, resultats: list[dict]) -> dict | None:
    """Résultat retenu : personne morale de droit public ou EPIC (catégorie 4xxx ou 7xxx), dénomination ou sigle
    identique au nom du jaune (comparaison sans accent ni ponctuation)."""
    import sirene
    q = norm(requete_siren(nom))
    sg = norm(sigle(nom) or "")
    for x in resultats:
        cj = str(x.get("nature_juridique") or "")
        if not sirene.personne_morale(cj) or cj[:1] not in "47":
            continue
        noms = {norm(x.get("nom_complet") or ""), norm(x.get("nom_raison_sociale") or "")}
        sig = norm(x.get("sigle") or "")
        noms |= {norm(re.sub(r"\s*\(.*?\)\s*$", "", x.get("nom_complet") or ""))}
        if q in noms or (sg and sg == sig and any(q[:20] in n or n[:20] in q for n in noms if n)):
            return {"siren": x["siren"], "categorie_juridique": cj,
                    "methode": "dénomination identique" if q in noms else "sigle et début de dénomination"}
    return None


def completer_siren(noms: list[str], budget_s: float = 900, paralleles: int = 6) -> dict:
    """Complète le cache SIREN ; appels en parallèle, jamais plus de 4 par seconde au total (limite de l'API : 7)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import requests
    sys.path.insert(0, str(ROOT / "pipeline"))
    cache = json.loads(CACHE_SIREN.read_text(encoding="utf-8")) if CACHE_SIREN.exists() else {}
    debut = time.monotonic()
    verrou = threading.Lock()
    prochain = [time.monotonic()]

    def tache(nom):
        for essai in range(4):
            if time.monotonic() - debut > budget_s:
                return
            with verrou:
                attente = prochain[0] - time.monotonic()
                prochain[0] = max(prochain[0], time.monotonic()) + 0.25
            if attente > 0:
                time.sleep(attente)
            try:
                r = requests.get(API, params={"q": requete_siren(nom), "per_page": 10}, headers=HEADERS, timeout=30)
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(2 ** essai)
                continue
            if r.status_code == 429 or r.status_code >= 500:  # quota : on attend, on ne contourne pas
                time.sleep(2 ** essai + 1)
                continue
            with verrou:
                cache[nom] = None if r.status_code >= 400 else choisir(nom, r.json().get("results", []))
            return

    with ThreadPoolExecutor(paralleles) as ex:
        list(ex.map(tache, [n for n in noms if n not in cache]))
    CACHE_SIREN.parent.mkdir(parents=True, exist_ok=True)
    CACHE_SIREN.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return cache


def entites_siren(ops: dict) -> list[str]:
    noms = []
    for o in ops.values():
        if o["niveau"] == "operateur":
            noms.append(o["nom"])
        for m in o.get("membres", []):
            noms.append(m["nom"])
    return sorted(set(noms))


# --- Sorties -------------------------------------------------------------------------------------------------------


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(t.encode("utf-8")) > 5_000_000:
        raise SystemExit(f"{path} dépasse 5 Mo")
    path.write_text(t + "\n", encoding="utf-8")


RECHERCHE_PREALABLE = [
    {"trouvaille": "data.gouv.fr, listes « jaune opérateurs » PLF 2024 à 2026 (data/lake)", "verdict": "réutilisable "
     "tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-01-13",
     "usage": "référentiel : opérateurs, catégories, statut, programme chef de file ; aucun montant"},
    {"trouvaille": "data.economie.gouv.fr et data.gouv.fr, crédits versés aux opérateurs (PLF 2012, PLF 2014), "
     "budgets des opérateurs (PLF 2019, BI 2018)", "verdict": "inspiration seulement", "licence": "Licence Ouverte 2.0",
     "mise_a_jour": "2018-12-13", "usage": "aucun jeu structuré par opérateur pour 2019 à 2025"},
    {"trouvaille": "data.enseignementsup-recherche.gouv.fr, indicateurs financiers des opérateurs de l'enseignement "
     "supérieur (comptes financiers)", "verdict": "à adapter", "licence": "Licence Ouverte 2.0",
     "mise_a_jour": "2026-07-10", "usage": "pas de ligne SCSP : non retenu pour la traçabilité, piste pour détailler "
     "la catégorie « Universités et assimilés »"},
    {"trouvaille": "Cour des comptes, « Les relations entre l'État et ses opérateurs » (données 2010-2020, "
     "data.gouv.fr)", "verdict": "inspiration seulement", "licence": "Licence Ouverte 2.0",
     "mise_a_jour": "2021-03-23", "usage": "agrégats seulement, ordre de grandeur"},
    {"trouvaille": "GitHub koutakou/france-transparence (docs/SOURCES.md, source S39)", "verdict": "inspiration "
     "seulement", "licence": "non précisée", "mise_a_jour": "2026-08-20",
     "usage": "même constat : le volet budgétaire des opérateurs n'existe pas en données structurées"},
    {"trouvaille": "jaunes « Opérateurs de l'État » PLF 2024, 2025, 2026 (PDF, miroir Assemblée nationale)",
     "verdict": "à adapter", "licence": "document administratif public (réutilisation libre, article L. 321-1 CRPA)",
     "mise_a_jour": "PLF 2026 (octobre 2025)", "usage": "source de ce module, lue par pdfplumber"},
]
LIMITES = [
    "2019 : exécution absente. Elle figure dans les jaunes PLF 2021 à 2023, introuvables sur un miroir officiel ; "
    "budget.gouv.fr refuse les scripts (403), non contourné.",
    "2025 : crédits votés (LFI 2025), pas d'exécution ; taxes affectées en prévision.",
    "Le jaune ne ventile pas la SCSP d'un opérateur entre ses programmes financeurs : seule la liste des programmes est "
    "publiée.",
    "Catégories d'opérateurs (universités, agences de l'eau, ARS, écoles...) : montants publiés pour la catégorie, pas "
    "par établissement.",
    "Budget initial : total des charges et des produits du compte de résultat prévisionnel (comptabilité générale) ; "
    "les comptes financiers exécutés ne sont pas dans le jaune.",
    "Rémunérations : somme des dix plus hautes rémunérations brutes par opérateur, seule donnée publiée ; aucune "
    "rémunération individuelle, commentaires de la source non repris.",
    "SIREN : rapproché par dénomination exacte (API Recherche d'entreprises), null si aucun résultat sûr.",
]


def produire() -> None:
    jaunes = {plf: analyser(plf) for plf in sorted(JAUNES) if chemin_pdf(plf).exists()}
    if not jaunes:
        raise SystemExit("aucun jaune dans data/lake : lancer « collecter »")
    res = construire(jaunes)
    ops = res["operateurs"]
    cache = json.loads(CACHE_SIREN.read_text(encoding="utf-8")) if CACHE_SIREN.exists() else {}
    for o in ops.values():
        e = cache.get(o["nom"]) if o["niveau"] == "operateur" else None
        o["siren"], o["categorie_juridique"], o["siren_methode"] = ((e["siren"], e["categorie_juridique"],
                                                                     e["methode"]) if e else (None, None, None))
        for m in o.get("membres", []):
            e = cache.get(m["nom"])
            m["siren"], m["categorie_juridique"] = (e["siren"], e["categorie_juridique"]) if e else (None, None)
    liste = sorted(ops.values(), key=lambda o: norm(o["nom"]))
    totaux = {}
    for a in map(str, ANNEES):
        t = defaultdict(float)
        n = 0
        for o in liste:
            d = o["annees"].get(a)
            if not d:
                continue
            n += 1
            for c, v in (d.get("financement_etat") or {}).items():
                t[f"{c}_cp_eur"] += v["cp_eur"] or 0
            for c, v in (d.get("credits_votes_lfi") or {}).items():
                t[f"lfi_{c}_cp_eur"] += v["cp_eur"] or 0
            for k in ("taxes_affectees_eur", "ressources_propres_eur", "masse_salariale_eur", "etpt_sous_plafond",
                      "etpt_hors_plafond", "plafond_emplois_lfi", "taxes_affectees_prevision_eur"):
                if d.get(k) is not None:
                    t[k] += d[k]
        totaux[a] = {"lignes": n, **{k: r0(v) for k, v in sorted(t.items())}}
    nb_membres = sum(len(o.get("membres", [])) for o in liste) + sum(1 for o in liste if o["niveau"] == "operateur"
                                                                         and o.get("plf_liste") == 2026)
    sources = {f"jaune PLF {plf}": src_jaune(plf) for plf in jaunes}
    sources.update({f"liste PLF {plf}": SRC_LISTE.format(a=plf) for plf in LISTES})
    sources["siren"] = SRC_API
    entete = {"millesime": "Exécution 2020 à 2024, crédits votés 2023 à 2025 (jaunes PLF 2024 à 2026)",
              "source": " ; ".join(src_jaune(p) for p in jaunes) + " ; " + SRC_LISTE.format(a=2026) + " ; " + SRC_API,
              "unite": "euros (crédits de paiement et autorisations d'engagement) ; emplois en ETPT"}
    for o in liste:
        o.pop("plf_liste", None)
    dump(SORTIE / "operateurs.json", {**entete, "annees": ANNEES, "operateurs": liste,
                                      "remunerations_non_rattachees": [
                                          {"entite": k, "dix_plus_hautes_remunerations_eur": v}
                                          for k, v in sorted(res["remunerations_non_rattachees"].items())]})
    resolus = sum(1 for o in liste if o["siren"]) + sum(1 for o in liste for m in o.get("membres", []) if m["siren"])
    a_resoudre = sum(1 for o in liste if o["niveau"] == "operateur") + sum(len(o.get("membres", [])) for o in liste)
    dump(SORTIE / "index.json", {
        **entete, "fichier": "operateurs/operateurs.json", "annees": ANNEES,
        "couverture": {"lignes_jaune": len(liste), "categories": sum(1 for o in liste if o["niveau"] == "categorie"),
                       "operateurs_liste_plf2026": nb_membres, "siren_resolus": resolus,
                       "siren_a_resoudre": a_resoudre,
                       "annees_execution": [2020, 2021, 2022, 2023, 2024], "annees_lfi": [2023, 2024, 2025],
                       "annees_absentes": {"2019": LIMITES[0]}},
        "totaux": totaux, "sources": sources, "recherche_prealable": RECHERCHE_PREALABLE, "limites": LIMITES,
        "lignes_non_reconnues": len(res["non_reconnus"]),
        "unites_source": {"financement": "milliers d'euros", "taxes_affectees_execution": "millions d'euros (en-tête "
                          "de la source erroné : « milliers »)", "taxes_affectees_prevision": "euros",
                          "ressources_propres": "milliers d'euros", "masse_salariale": "milliers d'euros",
                          "remunerations": "milliers d'euros"}})
    t24 = totaux["2024"]
    print(f"opérateurs : {len(liste)} lignes du jaune ({nb_membres} opérateurs au PLF 2026), SIREN {resolus}/"
          f"{a_resoudre} ; SCSP 2024 {t24.get('scsp_cp_eur', 0) / 1e9:.2f} Md€", file=sys.stderr)


def collecter() -> None:
    import requests
    for plf, j in JAUNES.items():
        p = chemin_pdf(plf)
        if p.exists():
            continue
        r = requests.get(j["url"], headers=HEADERS, timeout=300)
        if r.status_code in (401, 403, 429):
            print(f"PLF {plf} : refus {r.status_code}, non contourné", file=sys.stderr)
            continue
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            raise SystemExit(f"PLF {plf} : réponse non PDF")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
        print(f"PLF {plf} : {len(r.content)} octets", file=sys.stderr)


def main(argv: list[str]) -> None:
    cmd = argv[1] if len(argv) > 1 else "produire"
    if cmd == "collecter":
        collecter()
    elif cmd == "siren":
        jaunes = {plf: analyser(plf) for plf in sorted(JAUNES) if chemin_pdf(plf).exists()}
        ops = construire(jaunes)["operateurs"]
        noms = entites_siren(ops)
        cache = completer_siren(noms)
        print(f"SIREN : {sum(1 for n in noms if cache.get(n))}/{len(noms)} résolus", file=sys.stderr)
    elif cmd == "produire":
        produire()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
