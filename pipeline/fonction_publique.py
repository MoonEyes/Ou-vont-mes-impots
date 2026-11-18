"""Fonction publique : effectifs par versant, statut, ministère et territoire ; cabinets ministériels ; recours aux
conseils extérieurs ; barème légal des indemnités des élus locaux. Rapprochement avec les programmes et ministères du
budget de l'État (site/data/effectifs, site/data/arbre), sans double compte.

Entrées (data/lake/fonction_publique/, collectées par `python collecte/collecte.py --domaine fonction_publique`,
déclarées dans collecte/catalogue.json, tracées dans data/lake/manifest.json ; un refus 401/403/429 n'est jamais
contourné) :
  fp_insee_effectifs_versants.xlsx   Insee, effectifs par versant, statut, ministère, type d'employeur, 2011-2024 (Siasp)
  fp_insee_ip2094.xlsx               Insee Première n° 2094, l'emploi dans la fonction publique en 2024
  fp_insee_tcrd052.xlsx              Insee, effectifs par versant, par région et département, fin 2023
  fp_jaune_cabinets_plf<AAAA>.pdf    jaune « Personnels affectés dans les cabinets ministériels » (PLF 2025, 2026)
  fp_jaune_conseils_plf<AAAA>.pdf    jaune « Recours aux conseils extérieurs » (PLF 2024, 2025, 2026)
  fp_dgcl_indemnites_elus.pdf        DGCL, plafonds des indemnités de fonction des élus locaux
  fp_insee_ip210<0|1|2>.xlsx         Insee Première n° 2100 à 2102, salaires 2024 de l'État, territoriale, hospitalière
  fp_dgafp_ra2025_remu_niveaux.zip   DGAFP, rapport annuel 2025, rémunérations 2023 et dépenses de personnel des APU
  fp_eurostat_d1_apu.json            Eurostat gov_10a_exp, rémunération des salariés (D1) et dépenses totales des APU
  data/lake/etat/etat_etpt_lfi_2023.parquet   ministère de chaque programme (même source que site/data/effectifs)
  site/data/effectifs/<programme>.json, site/data/arbre/racine.json   ETPT, titre 2 et nœud de l'arbre (lus, jamais
                                     recalculés : un seul chiffre par programme dans tout le site)
Sorties (site/data/fonction_publique/, contrat docs/contrat_interface.md, schémas docs/schemas/fonction_publique_*) :
  index.json, effectifs_series.json, emploi.json, territoires.json, ministeres.json, cabinets.json, conseils.json,
  indemnites_elus.json, remunerations.json

Commande : python pipeline/fonction_publique.py produire [--sortie DOSSIER]   (sans réseau)
           python pipeline/fonction_publique.py remunerations [--sortie DOSSIER]   (remunerations.json seul)

Confidentialité : aucune personne physique. Cabinets : agrégats par pôle ministériel (les lignes par cabinet, qui
désignent un ministre par sa fonction, ne sont pas reprises). Prestataires de conseil : nommés seulement si la catégorie
juridique publiée dans le jaune est celle d'une personne morale (sirene.personne_morale) ; les listes détaillées de
prestations, qui peuvent citer des personnes exerçant à titre individuel, ne sont pas lues. Barème des élus : fonctions
et strates, aucun élu. Valeurs « nd », « /// », « / » de la source : null avec mention, jamais 0.
Lecture des PDF : pdfplumber, méthode de pipeline/operateurs.py (mots positionnés, colonnes par ancres).
Sorties reproductibles : aucune heure de passage (pipeline/reproductible.py), ordres explicites.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402
from sirene import personne_morale, siren_valide  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "fonction_publique"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "fonction_publique"
ETPT_PARQUET = ROOT / "data" / "lake" / "etat" / "etat_etpt_lfi_2023.parquet"
AN = "https://www.assemblee-nationale.fr/dyn/contenu/visualisation"
AN2 = "https://www2.assemblee-nationale.fr/static"

SOURCES = {
    "insee_series": ("fp_insee_effectifs_versants.xlsx",
                     "https://www.insee.fr/fr/statistiques/fichier/2493501/marc-empl-eff-fonc-pub.xlsx",
                     "Insee, « Effectifs dans la fonction publique par versant et par ministère », Siasp 2011 à 2024"),
    "insee_ip": ("fp_insee_ip2094.xlsx", "https://www.insee.fr/fr/statistiques/fichier/8732435/IP2094.xlsx",
                 "Insee Première n° 2094, « L'emploi dans la fonction publique en 2024 », données des figures"),
    "insee_tcrd": ("fp_insee_tcrd052.xlsx", "https://www.insee.fr/fr/statistiques/fichier/2012758/TCRD_052.xlsx",
                   "Insee, TCRD 052, « Effectifs de la fonction publique par versant : comparaisons régionales et "
                   "départementales »"),
    "cabinets_2026": ("fp_jaune_cabinets_plf2026.pdf", f"{AN}/1090016/file/20-Jaune2026_Cabinets.pdf",
                      "Annexe au projet de loi de finances pour 2026, « Personnels affectés dans les cabinets "
                      "ministériels », miroir Assemblée nationale"),
    "cabinets_2025": ("fp_jaune_cabinets_plf2025.pdf", f"{AN2}/17/Annexes-DL/PLF2025-Jaunes/20-Jaune_cabinets.pdf",
                      "Annexe au projet de loi de finances pour 2025, « Personnels affectés dans les cabinets "
                      "ministériels », miroir Assemblée nationale"),
    "conseils_2026": ("fp_jaune_conseils_plf2026.pdf", f"{AN}/1090037/file/27-Jaune2026_Recours_Conseils.pdf",
                      "Annexe au projet de loi de finances pour 2026, « Recours aux conseils extérieurs », miroir "
                      "Assemblée nationale"),
    "conseils_2025": ("fp_jaune_conseils_plf2025.pdf",
                      f"{AN2}/17/Annexes-DL/PLF2025-Jaunes/27-Jaune_recours_conseils.pdf",
                      "Annexe au projet de loi de finances pour 2025, « Recours aux conseils extérieurs », miroir "
                      "Assemblée nationale"),
    "conseils_2024": ("fp_jaune_conseils_plf2024.pdf",
                      f"{AN2}/16/pdf/Annexes_PLF/Recours_conseils_ext%C3%A9rieurs.pdf",
                      "Annexe au projet de loi de finances pour 2024, « Recours aux conseils extérieurs », miroir "
                      "Assemblée nationale"),
    "dgcl": ("fp_dgcl_indemnites_elus.pdf",
             "https://www.collectivites-locales.gouv.fr/files/files/1.%20Connaitre%20les%20acteurs%20et%20les%20"
             "institutions/3.%20Elus%20locaux/Montants%20plafonds%20indemnit%C3%A9s%20%C3%A9lus%20locaux%20Autom%20"
             "0723-1-2.pdf",
             "DGCL, « Indemnités de fonction brutes mensuelles des élus locaux » (plafonds légaux), "
             "collectivites-locales.gouv.fr"),
    "salaires_fpe": ("fp_insee_ip2100.xlsx", "https://www.insee.fr/fr/statistiques/fichier/8986474/ip2100.xlsx",
                     "Insee Première n° 2100, « Les salaires dans la fonction publique de l'État en 2024 », données "
                     "des figures (Siasp)"),
    "salaires_fpt": ("fp_insee_ip2101.xlsx", "https://www.insee.fr/fr/statistiques/fichier/8984823/IP2101.xlsx",
                     "Insee Première n° 2101, « Les salaires dans la fonction publique territoriale en 2024 », "
                     "données des figures (Siasp)"),
    "salaires_fph": ("fp_insee_ip2102.xlsx", "https://www.insee.fr/fr/statistiques/fichier/8986438/ip2102.xlsx",
                     "Insee Première n° 2102, « Les salaires dans la fonction publique hospitalière en 2024 », "
                     "données des figures (Siasp)"),
    "dgafp_remu": ("fp_dgafp_ra2025_remu_niveaux.zip",
                   "https://www.fonction-publique.gouv.fr/files/files/publications/vue-rapport-annuel/"
                   "ra_2025-remu_niveaux.zip",
                   "DGAFP, rapport annuel sur l'état de la fonction publique, édition 2025, vue « Les rémunérations "
                   "dans la fonction publique en 2023 », classeurs des figures et des dépenses de personnel"),
    "eurostat_d1": ("fp_eurostat_d1_apu.json",
                    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/gov_10a_exp?geo=FR&unit="
                    "MIO_EUR&unit=PC_GDP&cofog99=TOTAL&na_item=D1&na_item=TE&sector=S13&sector=S1311&sector=S1313"
                    "&sector=S1314&sinceTimePeriod=1995&lang=fr",
                    "Eurostat, gov_10a_exp, « Dépenses des administrations publiques par fonction (CFAP) » : "
                    "rémunération des salariés (D1) et total des dépenses (TE), France"),
}
SRC_ETPT = ("data.economie.gouv.fr/etpt-par-ministere-mission-programme-pour-le-bg-et-les-ba-lfi-2023 (ministère de "
            "chaque programme)")


def chemin(cle: str) -> Path:
    return LAKE / SOURCES[cle][0]


def src(*cles: str) -> str:
    return " ; ".join(f"{SOURCES[c][2]} : {SOURCES[c][1]}" for c in cles)


# --- Outils --------------------------------------------------------------------------------------------------------


def sans_accent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    """Clé de comparaison : minuscules, sans accent, sans ponctuation ni espace."""
    return re.sub(r"[^a-z0-9]", "", sans_accent(s or "").lower())


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", sans_accent(s or "").lower()).strip("_")


def propre(s) -> str:
    return re.sub(r"\s+", " ", str(s if s is not None else "").replace("\xa0", " ").replace("’", "'")).strip()


def sans_appel_de_note(s: str) -> str:
    """« Secteur communal4 », « (FPT)3 », « Catégorie C² » : retire l'appel de note collé au libellé."""
    return re.sub(r"(?<=[A-Za-zÀ-ÿ)])[0-9¹²³]$", "", propre(s))


ABSENT = {"nd": "nd", "n.d.": "nd", "///": "///", "/": "/", "nc": "nc", "s": "s", "": ""}
MENTIONS = {"nd": "« nd » dans la source : donnée non disponible", "///": "« /// » dans la source : absence de "
            "résultat due à la nature des choses", "/": "« / » dans la source : aucune dépense ou aucun crédit publié",
            "nc": "« nc » dans la source : non communiqué", "s": "« s » dans la source : secret statistique"}


def nombre(v):
    """(valeur, mention) : un nombre, ou None avec la mention de la source (« nd », « /// »...). Jamais 0 par défaut."""
    if v is None:
        return None, ""
    if isinstance(v, bool):
        return None, ""
    if isinstance(v, (int, float)):
        return float(v), None
    t = propre(v).replace(" ", "")
    if t.lower() in ABSENT:
        return None, ABSENT[t.lower()]
    t = t.replace(",", ".").replace("−", "-")
    try:
        return float(t), None
    except ValueError:
        return None, "texte"


def arrondi(x, n=3):
    if x is None:
        return None
    r = round(float(x), n)
    return int(r) if n == 0 else r


def feuille(chemin_xlsx: Path, nom: str) -> list[list]:
    """Lignes d'une feuille (cellules vides finales retirées). Lecture seule : les classeurs Insee ont parfois un
    dessin manquant qui fait échouer la lecture complète d'openpyxl."""
    import openpyxl
    wb = openpyxl.load_workbook(chemin_xlsx, data_only=True, read_only=True)
    ws = wb[nom]
    ws.reset_dimensions()
    lignes = []
    for row in ws.iter_rows(values_only=True):
        r = list(row[:200])
        while r and (r[-1] is None or propre(r[-1]) == ""):
            r.pop()
        lignes.append(r)
    wb.close()
    while lignes and not lignes[-1]:
        lignes.pop()
    return lignes


def feuilles(chemin_xlsx: Path) -> list[str]:
    import openpyxl
    wb = openpyxl.load_workbook(chemin_xlsx, read_only=True)
    noms = list(wb.sheetnames)
    wb.close()
    return noms


PIED = re.compile(r"^(Lecture|Champ|Source|Note|Notes|nd|r|p|///|\d\.)\s*[:.]?\s", re.I)


def pied_de_tableau(lignes: list[list]) -> tuple[int, list[str]]:
    """Indice de la première ligne de notes (bloc final de lignes à une seule cellule) et texte des notes."""
    i = len(lignes)
    while i > 0 and (not lignes[i - 1] or (len(lignes[i - 1]) == 1 and PIED.match(propre(lignes[i - 1][0]) + " "))):
        i -= 1
    return i, [propre(l[0]) for l in lignes[i:] if l]


# --- Insee : séries 2011-2024 par versant, statut, ministère et type d'employeur ------------------------------------

STATUTS = [("fonctionnaires_militaires", "Fonctionnaires et militaires"),
           ("contractuels", "Contractuels (hors contrats aidés)"),
           ("contrats_aides", "Bénéficiaires de contrats aidés"),
           ("autres", "Autres catégories et statuts"),
           ("ensemble", "Ensemble")]
NIVEAUX = ["versant", "type_employeur", "ministere", "detail_ministere"]  # + "ensemble" pour la ligne de total


def lire_series(lignes: list[list]) -> dict:
    """Feuille « Figure 3 » : une ligne par versant, type d'employeur ou ministère ; cinq colonnes de statut par année.
    Les années 2020 à 2023 existent en deux versions : publiée à l'époque, puis recalculée « (r) »."""
    i_ann = next(i for i, l in enumerate(lignes) if len(l) > 5 and re.match(r"^20\d\d", propre(l[1])))
    entete, sous = lignes[i_ann], lignes[i_ann + 1]
    series = []
    for j in range(1, len(sous), 5):
        t = propre(entete[j]) if j < len(entete) else ""
        m = re.match(r"^(20\d\d)", t)
        if not m:
            raise SystemExit(f"séries Insee : en-tête d'année inattendu colonne {j} : {t!r}")
        revisee = "(r)" in t
        noms = [norm(propre(x)) for x in sous[j:j + 5]]
        attendu = ["fonctionnaire", "contractuels", "beneficiaires", "autres", "ensemble"]
        if len(noms) != 5 or any(not n.startswith(a) for n, a in zip(noms, attendu)):
            raise SystemExit(f"séries Insee : statuts inattendus pour {t} : {sous[j:j + 5]}")
        series.append({"cle": m.group(1) + ("r" if revisee else ""), "annee": int(m.group(1)), "revisee": revisee,
                       "colonne": j})
    fin, notes = pied_de_tableau(lignes)
    out, parents = [], {}
    for l in lignes[i_ann + 2:fin]:
        if not l or l[0] is None:
            continue
        brut = str(l[0]).replace("\xa0", " ")
        retrait = len(brut) - len(brut.lstrip(" "))
        niveau = 0 if retrait == 0 else 1 if retrait <= 4 else 2 if retrait <= 7 else 3
        lib = sans_appel_de_note(brut)
        total = norm(lib).startswith("ensemble")
        if total:
            niveau = 0
        parents[niveau] = slug(lib)
        ligne = {"id": slug(lib), "libelle": lib, "niveau": "ensemble" if total else NIVEAUX[niveau],
                 "parent": parents.get(niveau - 1) if niveau else None, "valeurs": {s: [] for s, _ in STATUTS},
                 "non_disponible": []}
        for s in series:
            absent = False
            for k, (st, _) in enumerate(STATUTS):
                c = s["colonne"] + k
                v, mention = nombre(l[c] if c < len(l) else None)
                if v is None:
                    absent = True
                ligne["valeurs"][st].append(arrondi(v, 1))
            if absent:
                ligne["non_disponible"].append(s["cle"])
        out.append(ligne)
    return {"series": [{k: s[k] for k in ("cle", "annee", "revisee")} for s in series], "lignes": out,
            "notes_source": notes}


# --- Insee Première : tableaux de la publication ---------------------------------------------------------------------


def est_valeur(c) -> bool:
    v, m = nombre(c)
    return v is not None or m in MENTIONS


def lire_tableau(lignes: list[list], decimales: int = 1) -> dict:
    """Tableau générique d'une feuille Insee : titre, unité, colonnes (en-têtes fusionnés), rubriques, lignes, notes."""
    titre = propre(lignes[0][0]) if lignes and lignes[0] else ""
    fin, notes = pied_de_tableau(lignes)
    corps = [(i, l) for i, l in enumerate(lignes[1:fin], 1) if l]

    def seule(l):
        return l[0] is not None and propre(l[0]) and all(c is None or propre(c) == "" for c in l[1:])

    def donnee(l):
        reste = [c for c in l[1:] if c is not None and propre(c) != ""]
        return l[0] is not None and propre(l[0]) != "" and reste and all(est_valeur(c) for c in reste)

    def annees(l):  # ligne d'en-tête faite seulement d'années en texte (« 2023 », « 2024 »)
        reste = [c for c in l[1:] if c is not None and propre(c) != ""]
        return bool(reste) and all(isinstance(c, str) and re.fullmatch(r"(19|20)\d\d", propre(c)) for c in reste)

    entetes, k = [], 0
    while k < len(corps) and not seule(corps[k][1]) and (annees(corps[k][1]) or not donnee(corps[k][1])):
        entetes.append(corps[k][1])
        k += 1
    largeur = max(len(l) for _, l in corps)
    unite, niveaux = None, []
    for e in entetes:
        cellules = [(j, propre(c)) for j, c in enumerate(e) if c is not None and propre(c)]
        if (e[0] is None or not propre(e[0])) and len(cellules) == 1:
            unite = cellules[0][1]
            continue
        rempli, courant = [], ""
        for j in range(1, largeur):
            t = propre(e[j]) if j < len(e) and e[j] is not None else ""
            courant = t or courant
            rempli.append(courant)
        niveaux.append(rempli)
    colonnes = []
    for j in range(largeur - 1):
        parts = []
        for n in niveaux:
            if n[j] and n[j] not in parts:
                parts.append(re.sub(r"\s+", " ", n[j]))
        colonnes.append(" ; ".join(parts))
    out, rubrique = [], None
    for _, l in corps[k:]:
        if seule(l):
            rubrique = sans_appel_de_note(l[0])
            continue
        vals, absents = [], {}
        for j in range(1, largeur):
            v, mention = nombre(l[j] if j < len(l) else None)
            vals.append(arrondi(v, decimales))
            if v is None and mention in MENTIONS:
                absents[str(j - 1)] = mention
        ligne = {"rubrique": rubrique, "libelle": sans_appel_de_note(l[0]), "valeurs": vals}
        if absents:
            ligne["absences"] = absents
        out.append(ligne)
    return {"titre": re.sub(r"^(Figure|Tableau complémentaire) \d+ [–-] ", "", titre), "unite": unite,
            "colonnes": colonnes, "lignes": out, "notes_source": notes}


# --- Insee : régions et départements ---------------------------------------------------------------------------------

COLONNES_TERRITOIRES = [
    ("ensemble_hors_militaires_milliers", "ensemblehorsmilitaires"),
    ("part_femmes_pct", "partdesfemmes"),
    ("fpe_hors_militaires_milliers", "fonctionpubliquedeletathorsmilitaires"),
    ("fpt_milliers", "fonctionpubliqueterritoriale"),
    ("fph_milliers", "fonctionpubliquehospitaliere"),
    ("pour_100_habitants", "effectifsdelafonctionpubliquehorsmilitairespour100habitants"),
    ("pour_100_emplois_salaries", "effectifsdelafonctionpubliquehorsmilitairespour100emploissalaries"),
]


def lire_territoires(lignes: list[list]) -> dict:
    titre = propre(lignes[0][0])
    m = re.search(r"au 31 décembre (20\d\d)", titre)
    if not m:
        raise SystemExit(f"TCRD 052 : année introuvable dans « {titre} »")
    i_ent = next(i for i, l in enumerate(lignes) if len(l) > 5 and "ensemble" in norm(propre(l[2])))
    ent = [norm(propre(c)) for c in lignes[i_ent]]
    for k, (_, debut) in enumerate(COLONNES_TERRITOIRES):
        if not ent[2 + k].startswith(debut):
            raise SystemExit(f"TCRD 052 : colonne {k} inattendue : {lignes[i_ent][2 + k]!r}")
    fin, notes = pied_de_tableau(lignes)
    out = {}
    for l in lignes[i_ent + 1:fin]:
        if len(l) < 9 or l[0] is None:
            continue
        code = propre(l[0])
        vals = [arrondi(nombre(c)[0], 1) for c in l[2:9]]
        out[code] = {"libelle": propre(l[1]), "valeurs": vals}
    return {"annee": int(m.group(1)), "titre": titre, "lignes": out, "notes_source": notes}


# --- Lecture des PDF (pdfplumber), méthode de pipeline/operateurs.py -------------------------------------------------


def lignes_page(page) -> list[list[dict]]:
    mots = page.extract_words(x_tolerance=1.5, keep_blank_chars=False)
    par_top: dict[float, list] = {}
    for w in sorted(mots, key=lambda w: (round(w["top"]), w["x0"])):
        t = next((k for k in par_top if abs(k - w["top"]) <= 2.5), None)
        par_top.setdefault(t if t is not None else w["top"], []).append(w)
    return [sorted(v, key=lambda w: w["x0"]) for _, v in sorted(par_top.items())]


def texte(ws) -> str:
    return propre(" ".join(w["text"] for w in ws))


def groupes(ws, ecart: float = 8.0) -> list[list[dict]]:
    """Mots d'une ligne regroupés en cellules (un blanc de plus de `ecart` points sépare deux cellules)."""
    out: list[list[dict]] = []
    for w in ws:
        if out and w["x0"] - out[-1][-1]["x1"] <= ecart:
            out[-1].append(w)
        else:
            out.append([w])
    return out


VALEUR = re.compile(r"^(-?\d[\d,]*%?|€|%|/|-)$")


def montant(t: str):
    """« 2 628 066 € » -> 2628066.0 ; « 0,132 % » -> 0.132 ; « / » -> None (aucune dépense publiée)."""
    t = propre(t).replace("€", "").replace("%", "").replace(" ", "")
    if t in ("", "/", "-"):
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def bornes_colonnes(ws_entete: list[dict], x_min: float) -> list[float]:
    """Frontières entre colonnes de valeurs : milieu du blanc entre deux groupes de mots d'en-tête."""
    gs = groupes([w for w in ws_entete if w["x0"] >= x_min], 12.0)
    return [(a[-1]["x1"] + b[0]["x0"]) / 2 for a, b in zip(gs, gs[1:])]


def cellules(vals: list[dict]) -> list[dict]:
    """Mots numériques d'une ligne -> cellules. Une cellule finit à « € » ou « % », ou vaut « / » ; des chiffres sans
    symbole (table de nombres) sont séparés par les blancs de plus de 7 points."""
    out, cour = [], []

    def fermer():
        if cour:
            for g in groupes(cour, 7.0) if not any(w["text"] in ("€", "%") or w["text"].endswith("%") for w in cour) \
                    else [list(cour)]:
                out.append({"x0": g[0]["x0"], "x1": g[-1]["x1"], "t": " ".join(w["text"] for w in g)})
            cour.clear()

    for w in vals:
        if w["text"] in ("/", "-"):
            fermer()
            out.append({"x0": w["x0"], "x1": w["x1"], "t": "/"})
        else:
            cour.append(w)
            if w["text"] in ("€", "%") or w["text"].endswith("%"):
                fermer()
    fermer()
    return out


def ranger(rangees: list[list[dict]], n: int, bornes: list[float]) -> list[list[str | None]]:
    """Range les cellules de chaque rangée dans n colonnes. Rangée complète : dans l'ordre. Rangée incomplète : colonne
    dont l'ancre (bord droit médian des montants, centre médian des « / », appris sur les rangées complètes) est la
    plus proche ; à défaut d'ancre, colonne où tombe le centre de la cellule (frontières `bornes`)."""
    droite: list[list[float]] = [[] for _ in range(n)]
    centre: list[list[float]] = [[] for _ in range(n)]
    for cs in rangees:
        if len(cs) == n:
            for j, c in enumerate(cs):
                (centre if c["t"] == "/" else droite)[j].append((c["x0"] + c["x1"]) / 2 if c["t"] == "/" else c["x1"])

    def med(xs):
        return sorted(xs)[len(xs) // 2] if xs else None

    a_droite, a_centre = [med(x) for x in droite], [med(x) for x in centre]
    out = []
    for cs in rangees:
        ligne: list[str | None] = [None] * n
        if len(cs) == n:
            ligne = [c["t"] for c in cs]
        else:
            for c in cs:
                slash = c["t"] == "/"
                x = (c["x0"] + c["x1"]) / 2 if slash else c["x1"]
                ancres = a_centre if slash else a_droite
                if any(a is None for a in ancres):
                    j = min(sum(1 for b in bornes if (c["x0"] + c["x1"]) / 2 > b), n - 1)
                else:
                    j = min(range(n), key=lambda k: abs(ancres[k] - x))
                ligne[j] = c["t"] if ligne[j] is None else ligne[j] + " " + c["t"]
        out.append(ligne)
    return out


def lire_table(lignes: list[list[dict]], x_val: float, bornes: list[float], x_max: float = 1e9,
               x_lib: float = 0.0, portee: float = 14.0) -> list[tuple[str, list[str | None]]]:
    """Table à libellés sur plusieurs lignes : chaque ligne de valeurs (mots numériques à droite de x_val) forme une
    rangée ; chaque ligne de libellé rejoint la rangée la plus proche en hauteur (à moins de `portee` points)."""
    rangees, libelles = [], []
    for ws in lignes:
        ws = [w for w in ws if x_lib <= (w["x0"] + w["x1"]) / 2 < x_max]
        if not ws:
            continue
        vals = [w for w in ws if w["x0"] >= x_val and VALEUR.match(w["text"])]
        libs = [w for w in ws if w not in vals]
        y = ws[0]["top"]
        if vals:
            rangees.append({"y": y, "cells": cellules(vals), "libs": []})
        if libs:
            libelles.append((y, texte(libs)))
    for y, t in libelles:
        if not rangees:
            continue
        r = min(rangees, key=lambda r: abs(r["y"] - y))
        if abs(r["y"] - y) <= portee:
            r["libs"].append((y, t))
    rangs = ranger([r["cells"] for r in rangees], len(bornes) + 1, bornes)
    return [(propre(" ".join(t for _, t in sorted(r["libs"]))), c) for r, c in zip(rangees, rangs)]


DEBUT_PROGRAMME = re.compile(r"^P\.? ?(\d{3})\b")


def lire_table_programmes(lignes: list[tuple[list[dict], float]], x_val: float,
                          bornes: list[float]) -> list[tuple[str, list]]:
    """Table des programmes : une rangée commence à une ligne « P.NNN – » (ou « TOTAL ») et court jusqu'à la suivante ;
    les valeurs sont sur l'une de ses lignes. Un intertitre centré (nom de ministère) ferme la rangée en cours.
    `lignes` : (mots de la ligne, marge gauche de sa page), les pages paires et impaires n'ayant pas la même marge."""
    blocs, cour = [], None
    for ws, marge in lignes:
        vals = [w for w in ws if w["x0"] >= x_val and VALEUR.match(w["text"])]
        libs = [w for w in ws if w not in vals]
        t = texte(libs)
        if DEBUT_PROGRAMME.match(t) or t.upper() == "TOTAL":
            cour = {"lib": [t], "cells": cellules(vals)}
            blocs.append(cour)
            continue
        if libs and libs[0]["x0"] > marge + 15 and not vals:  # intertitre centré
            cour = None
            continue
        if cour is None:
            continue
        if t:
            cour["lib"].append(t)
        cour["cells"] += cellules(vals)
    rangs = ranger([b["cells"] for b in blocs], len(bornes) + 1, bornes)
    return [(propre(" ".join(b["lib"])), c) for b, c in zip(blocs, rangs)]


def ouvrir(cle: str):
    import pdfplumber
    return pdfplumber.open(chemin(cle))


# --- Cabinets ministériels ---------------------------------------------------------------------------------------------

POLES = ["Affaires étrangères", "Agriculture et alimentation", "Aménagement du territoire et de la décentralisation",
         "Armées", "Culture", "Ecologie", "Économie, Finances et Relance", "Éducation nationale",
         "Enseignement supérieur, recherche et innovation", "Fonction publique", "Intérieur", "Justice", "Outre-mer",
         "Services du Premier Ministre", "Services de la Première Ministre", "Solidarités et santé",
         "Travail, Solidarité, santé et familles", "Sports"]
# Pôle du jaune -> ministères du budget (nomenclature LFI 2023 de site/data/effectifs). Rapprochement du projet.
POLES_MINISTERES = {
    "affairesetrangeres": ["europe_et_affaires_etrangeres"],
    "agricultureetalimentation": ["agriculture_et_souverainete_alimentaire"],
    "amenagementduterritoireetdeladecentralisation": ["transition_ecologique_et_cohesion_des_territoires"],
    "armees": ["armees"], "culture": ["culture"],
    "ecologie": ["transition_ecologique_et_cohesion_des_territoires"],
    "economiefinancesetrelance": ["economie_finances_et_souverainete_industrielle_et_numerique"],
    "educationnationale": ["education_nationale_et_jeunesse"],
    "enseignementsuperieurrechercheetinnovation": ["enseignement_superieur_et_recherche"],
    "fonctionpublique": ["transformation_et_fonction_publiques"],
    "interieur": ["interieur_et_outre_mer"], "outremer": ["interieur_et_outre_mer"], "justice": ["justice"],
    "servicesdupremierministre": ["services_du_premier_ministre"],
    "servicesdelapremiereministre": ["services_du_premier_ministre"],
    "solidaritesetsante": ["solidarites_autonomie_et_personnes_handicapees", "travail_plein_emploi_et_insertion"],
    "travailsolidaritesanteetfamilles": ["solidarites_autonomie_et_personnes_handicapees",
                                         "travail_plein_emploi_et_insertion"],
    "sports": ["sports_et_jeux_olympiques_et_paralympiques"],
}
FONCTIONS_CABINET = [
    ("membres", "1. Membres du Cabinet"), ("directeur", "Directeur"), ("directeur_adjoint", "Directeur-adjoint"),
    ("chef_et_chef_adjoint", "Chef et chef-adjoint"), ("conseiller", "Conseiller et conseiller technique"),
    ("autres_collaborateurs", "Autres collaborateurs"),
    ("fonctions_support", "2. Personnels chargés des fonctions support"),
    ("protection", "Protection du ministre (dont officiers de sécurité)"),
    ("securite_batiments", "Sécurité des bâtiments (dont huissiers)"),
    ("assistance", "Assistance (administration, courrier, secrétariat)"),
    ("intendance", "Intendance (cuisinier, hôtellerie)"), ("logistique", "Logistique (chauffeur)"),
    ("total", "Total général des personnels (1+2)"),
]
POSITIONS = [("affectes_par_le_ministere", "Personnels affectés par le ministère"),
             ("mis_a_disposition", "Personnels mis à disposition"),
             ("fonctionnaires_detaches", "Fonctionnaires détachés"), ("sur_contrat", "Personnel sur contrat"),
             ("total", "Total")]


def decouper(jetons: list[str]):
    """Quatre nombres (total, membres, support, dotation) écrits avec des espaces de milliers : seule découpe où
    total = membres + support. None si aucune ou plusieurs."""
    n, sol = len(jetons), []

    def val(a, b):
        g = jetons[a:b]
        if not g or len(g[0]) > 3 or any(len(x) != 3 for x in g[1:]) or (len(g) > 1 and g[0].startswith("0")):
            return None
        return int("".join(g))

    for i in range(1, n - 2):
        for j in range(i + 1, n - 1):
            for k in range(j + 1, n):
                v = [val(0, i), val(i, j), val(j, k), val(k, n)]
                if None not in v and v[0] == v[1] + v[2]:
                    sol.append(v)
    return sol[0] if len(sol) == 1 else None


def lire_cabinets(pages_texte: list[str]) -> dict:
    """Note de présentation et tableau récapitulatif du jaune « cabinets ». Les lignes par pôle ministériel sont
    reconnues par l'arithmétique : une ligne de pôle égale la somme des lignes de cabinet qui la suivent."""
    tout = "\n".join(pages_texte)
    m = re.search(r"Cabinets ministériels au (1er|\d{1,2}) (\w+) (20\d\d)", tout)
    if not m:
        raise SystemExit("jaune cabinets : date de situation introuvable")
    annee = int(m.group(3))
    table = tout[m.start():]
    rangs, precedent = [], ""
    for l in table.split("\n"):
        mots = l.split()
        k = len(mots)
        while k > 0 and re.fullmatch(r"\d{1,3}", mots[k - 1]):
            k -= 1
        nums, lib = mots[k:], propre(" ".join(mots[:k]))
        v = decouper(nums) if len(nums) >= 4 else None
        if v is None:
            precedent = propre(l)
            continue
        rangs.append({"libelle": lib or precedent, "v": v})
        precedent = ""
    if not rangs or not norm(rangs[-1]["libelle"]).startswith("totalgeneral"):
        raise SystemExit("jaune cabinets : ligne « Total général » introuvable")
    total, rangs = rangs[-1]["v"], rangs[:-1]
    poles, i = [], 0
    while i < len(rangs):
        cible, somme, k = rangs[i]["v"], [0, 0, 0, 0], 0
        while i + k + 1 < len(rangs) and somme != cible:
            k += 1
            somme = [a + b for a, b in zip(somme, rangs[i + k]["v"])]
        if somme != cible:
            raise SystemExit(f"jaune cabinets {annee} : pôle « {rangs[i]['libelle']} » différent de la somme de ses "
                             "cabinets")
        lib, corrige = rangs[i]["libelle"], False
        if lib not in POLES:
            proche = [p for p in POLES if norm(p)[:10] == norm(lib)[:10]]
            if len(proche) == 1:  # libellé illisible dans le PDF (textes superposés) : libellé de référence
                lib, corrige = proche[0], True
        p = {"pole": lib, "nb_cabinets": k, "effectif_total": cible[0], "membres_cabinet": cible[1],
             "fonctions_support": cible[2], "dotation_isp_eur": cible[3],
             "ministeres_budget": POLES_MINISTERES.get(norm(lib), [])}
        if corrige:
            p["libelle_restitue"] = True
        poles.append(p)
        i += k + 1
    somme = [sum(p[c] for p in poles) for c in ("effectif_total", "membres_cabinet", "fonctions_support",
                                                "dotation_isp_eur")]
    if somme != total:
        raise SystemExit(f"jaune cabinets {annee} : somme des pôles {somme} différente du total {total}")

    def entier(lib: str, n: int = 1):
        mm = re.search(r"^" + re.escape(lib) + r" " + " ".join([r"(\d(?: ?\d)*)"] * n) + r"$", tout, re.M)
        if not mm:
            return [None] * n
        return [int(x.replace(" ", "")) for x in mm.groups()]

    fonctions = {c: entier(lib)[0] for c, lib in FONCTIONS_CABINET}
    positions = {}
    for c, lib in POSITIONS:
        a, b = entier(lib, 2)
        positions[c] = {"membres_cabinet": a, "fonctions_support": b}
    return {"annee": annee, "date_situation": f"{annee}-07-01" if m.group(1) == "1er" and m.group(2) == "juillet"
            else None, "total": dict(zip(("effectif_total", "membres_cabinet", "fonctions_support",
                                          "dotation_isp_eur"), total)),
            "nb_cabinets": sum(p["nb_cabinets"] for p in poles), "par_fonction": fonctions,
            "par_position_statutaire": positions, "poles": poles}


# --- Recours aux conseils extérieurs -----------------------------------------------------------------------------------


def page_de(textes: list[str], motif: str, debut: int = 0) -> int | None:
    return next((i for i in range(debut, len(textes)) if motif in textes[i]), None)


def lire_totaux_conseils(textes: list[str]) -> list[dict]:
    """Lignes « Consommation AE 2021 ... / Total ... » : une ou deux tables selon l'édition."""
    out = {}
    for t in textes[:25]:
        ls = t.split("\n")
        for i, l in enumerate(ls[:-1]):
            if not l.startswith("Consommation ") or not ls[i + 1].startswith("Total"):
                continue
            cols = re.findall(r"(AE|CP) (S1 )?(20\d\d)", l)
            vals = re.findall(r"(-?\d[\d ]*) €", ls[i + 1])
            if len(cols) != len(vals):
                continue
            for (typ, s1, an), v in zip(cols, vals):
                cle = an + ("_s1" if s1 else "")
                out.setdefault(cle, {"exercice": int(an), "semestre_1_seul": bool(s1), "ae_eur": None, "cp_eur": None})
                out[cle][typ.lower() + "_eur"] = float(v.replace(" ", ""))
    return [out[k] for k in sorted(out)]


def lire_ministeres_conseils(pdf, textes: list[str]) -> dict:
    """Table « Répartition des engagements par ministère » : deux blocs côte à côte (un exercice chacun)."""
    ip = page_de(textes, "Ministères (format LFI")
    if ip is None:
        return {}
    page = pdf.pages[ip]
    lignes = lignes_page(page)
    i_ent = next(i for i, ws in enumerate(lignes) if texte(ws).startswith("Ministères (format LFI"))
    ent = texte(lignes[i_ent])
    blocs = re.findall(r"Ministères \(format (LFI 20\d\d)\) (S1 )?(20\d\d)", ent)
    if len(blocs) != 2 or any(b[1] for b in blocs):
        return {}
    milieu = page.width / 2 + 5  # les montants de gauche finissent au milieu de la page, où commencent les libellés de droite
    fin = next((i for i, ws in enumerate(lignes) if i > i_ent and texte(ws).startswith("Répartition des engagements "
                                                                                         "par mission")), len(lignes))
    corps = [ws for ws in lignes[i_ent + 1:fin] if ws[0]["top"] < page.height - 45]
    out = {}
    for (nomen, _, an), (x0, x1) in zip(blocs, ((0, milieu), (milieu, 1e9))):
        x_val = (milieu - 65) if x0 == 0 else (page.width - 100)
        rangs = lire_table(corps, x_val, [], x_max=x1, x_lib=x0)
        ls, total = [], None
        for lib, cells in rangs:
            v = montant(cells[0] or "")
            if norm(lib) == "total":
                total = v
            elif lib and v is not None:
                ls.append({"ministere": lib, "ae_eur": v})
        somme = sum(x["ae_eur"] for x in ls)
        if total is None or abs(somme - total) > len(ls):  # chaque ligne est arrondie à l'euro par la source
            raise SystemExit(f"jaune conseils : ministères {an}, somme {somme} != total {total}")
        out[an] = {"nomenclature": "format " + nomen, "total_ae_eur": total, "somme_des_lignes_ae_eur": somme,
                   "lignes": sorted(ls, key=lambda x: (-x["ae_eur"], x["ministere"]))}
    return out


def lire_programmes_conseils(pdf, textes: list[str]) -> dict:
    """Table « Part des dépenses dans le total des crédits alloués au programme » : AE consommées, AE ouvertes en LFI
    et part, pour deux exercices. Les pages de suite n'ont pas d'en-tête : les colonnes de la page précédente servent."""
    i0 = page_de(textes, "Part des dépenses dans le total des crédits alloués au programme")
    i1 = page_de(textes, "Répartition des commandes de conseils extérieurs par titulaire")
    if i0 is None or i1 is None:
        return {}
    annees, bornes, x_val, flux = None, None, None, []
    for ip in range(i0, i1):
        page = pdf.pages[ip]
        lignes = lignes_page(page)
        ents = [i for i, ws in enumerate(lignes) if texte(ws).startswith("Programmes AE consommées")]
        debut = 0
        if ents:
            i_ent = ents[-1]
            vals = [w for w in lignes[i_ent] if w["text"] != "Programmes"]
            x_val = min(w["x0"] for w in vals) - 12
            bornes = bornes_colonnes(lignes[i_ent], x_val)
            a = re.findall(r"20\d\d", texte(lignes[i_ent + 1]))
            annees = [a[0], a[-1]]
            debut = i_ent + 2
        if bornes is None or len(bornes) != 5:
            continue
        corps = [ws for ws in lignes[debut:] if 70 < ws[0]["top"] < page.height - 45]
        marge = min((ws[0]["x0"] for ws in corps), default=0.0)
        flux += [(ws, marge) for ws in corps]
    if annees is None:
        return {}
    out, total = {}, None
    for lib, cells in lire_table_programmes(flux, x_val, bornes):
        if lib.upper() == "TOTAL":
            total = [montant(cells[0] or ""), montant(cells[3] or "")]
            continue
        m = re.match(r"^P\.? ?(\d{3}) ?[–-] ?(.+)$", lib)
        if not m:
            continue
        p = out.setdefault(m.group(1), {"programme": m.group(1), "libelle": propre(m.group(2)), "exercices": {}})
        for k, an in enumerate(annees):
            c = cells[3 * k:3 * k + 3]
            if an in p["exercices"] and all(x is None for x in c):
                continue  # programme cité sous deux ministères (un par exercice) : la rangée vide ne remplace rien
            p["exercices"][an] = {"ae_consommees_eur": montant(c[0] or ""),
                                  "ae_ouvertes_lfi_eur": montant(c[1] or ""),
                                  "part_pct": montant(c[2] or "")}
    if not out:
        return {}
    sommes = [sum(p["exercices"][an]["ae_consommees_eur"] or 0 for p in out.values() if an in p["exercices"])
              for an in annees]
    return {"annees": annees, "programmes": out, "total_ae_eur": dict(zip(annees, total or [None, None])),
            "somme_programmes_ae_eur": dict(zip(annees, sommes))}


def lire_missions_conseils(pdf, textes: list[str]) -> dict:
    """Table « Répartition des engagements par mission » : AE par mission, quatre exercices."""
    i0 = page_de(textes, "Répartition des engagements par mission du budget")
    if i0 is None:
        return {}
    annees, bornes, x_val, out, total = None, None, None, [], None
    for ip in range(i0, min(i0 + 4, len(textes))):
        page = pdf.pages[ip]
        lignes = lignes_page(page)
        ents = [i for i, ws in enumerate(lignes) if re.match(r"^Mission AE 20\d\d", texte(ws))]
        if not ents:
            if total is not None or annees is None:
                break
            continue
        i_ent = ents[-1]
        vals = [w for w in lignes[i_ent] if w["text"] != "Mission"]
        x_val = min(w["x0"] for w in vals) - 25
        bornes = bornes_colonnes(lignes[i_ent], x_val)
        annees = re.findall(r"20\d\d", texte(lignes[i_ent]))
        corps = [ws for ws in lignes[i_ent + 1:] if 70 < ws[0]["top"] < page.height - 45]
        for lib, cells in lire_table(corps, x_val, bornes):
            if len(cells) != len(annees):
                continue
            v = [montant(c or "") for c in cells]
            if norm(lib) == "total":
                total = v
                break
            if re.match(r"^(Mission|Nombre|d'engagements)", lib) or not lib:
                break
            out.append({"mission": lib, "ae_eur": v})
        if total is not None:
            break
    if not out or total is None:
        return {}
    for k, an in enumerate(annees):
        s = sum(x["ae_eur"][k] or 0 for x in out)
        if abs(s - total[k]) > len(out):  # chaque ligne est arrondie à l'euro par la source
            raise SystemExit(f"jaune conseils : missions {an}, somme {s} != total {total[k]}")
    return {"annees": [int(a) for a in annees], "total_ae_eur": total,
            "lignes": sorted(out, key=lambda x: sans_accent(x["mission"]).lower())}


def lire_prestataires(textes: list[str]) -> dict:
    """Vingt principaux prestataires : dénomination, SIREN et catégorie juridique publiés par le jaune, nombre de
    commandes, montant. Un prestataire n'est nommé que si sa catégorie juridique est celle d'une personne morale."""
    i0 = page_de(textes, "Répartition des commandes de conseils extérieurs par titulaire")
    if i0 is None:
        return {}
    t = "\n".join(textes[i0:i0 + 16])
    intro = propre(t[:t.find("\n1) ")] if "\n1) " in t else t[:800])
    m1 = re.search(r"En (20\d\d), l'État a passé commande", intro)
    m2 = re.search(r"Entre le 1er janvier (20\d\d) et le 31 décembre (20\d\d)", intro)
    periode = m1.group(1) if m1 else f"{m2.group(1)}-{m2.group(2)}" if m2 else None
    nb = re.search(r"à (\d[\d ]*) prestataires distincts", intro)
    part = re.search(r"représentent (\d+) % des engagements", intro)
    debuts, pos, rang = [], 0, 1
    while rang <= 20:
        m = re.compile(rf"^{rang}\) (.+)$", re.M).search(t, pos)
        if not m:
            break
        debuts.append((rang, m.start(), m.end(), m.group(1)))
        pos, rang = m.end(), rang + 1
    out = []
    for k, (rg, a, b, nom) in enumerate(debuts):
        bloc = t[b:debuts[k + 1][1]] if k + 1 < len(debuts) else t[b:b + 1500]
        plat = propre(bloc)
        siren = re.search(r"SIREN (\d{3}) ?(\d{3}) ?(\d{3})\b", plat)
        siren = "".join(siren.groups()) if siren else None
        cj = re.search(r"\b(\d{4}) - ", plat[:400])
        cj = cj.group(1) if cj else None
        n = re.search(r"a fait l'objet de (\d[\d ]*) commandes", plat)
        nb_cmd = int(n.group(1).replace(" ", "")) if n else 1 if "a fait l'objet d'une commande" in plat else None
        mt = re.search(r"montant\s+total\s+de\s+(\d+(?:,\d+)?)\s*M", plat)
        nommable = bool(siren_valide(siren) and personne_morale(cj)) and "ANONYMIS" not in nom.upper()
        e = {"rang": rg, "denomination": propre(nom) if nommable else None, "siren": siren if nommable else None,
             "categorie_juridique": cj if nommable else None, "nb_commandes": nb_cmd,
             "montant_meur": float(mt.group(1).replace(",", ".")) if mt else None}
        if not nommable:
            e["motif_non_nomme"] = ("anonymisé par la source" if "ANONYMIS" in nom.upper() else
                                    "catégorie juridique de personne morale non établie par la source")
        out.append(e)
    return {"periode": periode, "nb_prestataires_distincts": int(nb.group(1).replace(" ", "")) if nb else None,
            "part_des_vingt_premiers_pct": int(part.group(1)) if part else None, "lignes": out}


def lire_conseils(cle: str, complet: bool = True) -> dict:
    with ouvrir(cle) as pdf:
        textes = [propre_page(p.extract_text() or "") for p in pdf.pages[:60]]
        res = {"totaux": lire_totaux_conseils(textes)}
        if complet:
            res["ministeres"] = lire_ministeres_conseils(pdf, textes)
            res["missions"] = lire_missions_conseils(pdf, textes)
            res["programmes"] = lire_programmes_conseils(pdf, textes)
            res["prestataires"] = lire_prestataires(textes)
    return res


def propre_page(t: str) -> str:
    return "\n".join(propre(l) for l in t.split("\n"))


# --- Indemnités des élus locaux ----------------------------------------------------------------------------------------

TITRE_FONCTION = re.compile(r"^INDEMNITÉS DE FONCTION BRUTES MENSUELLES\s*(.*)$")
def rangee_bareme(ligne: str, base: float):
    """(libellé, taux, montant, vérifiée) d'une ligne « strate taux montant ». « De 3 500 à 9 999 22 904,32 » se lit
    de deux façons (montant « 904,32 » ou « 22 904,32 ») : on garde celle où montant = taux x indice ; sinon la
    première lecture, marquée non vérifiée. None si la ligne ne finit pas par un taux et un montant."""
    lectures = []
    for motif in (r"\d{1,3},\d{2}", r"\d{1,2} \d{3},\d{2}"):
        m = re.match(r"^(.*?) ?(?<![\d,])(\d{1,3}(?:,\d{1,2})?) (" + motif + r")$", ligne)
        if m:
            taux, eur = float(m.group(2).replace(",", ".")), float(m.group(3).replace(" ", "").replace(",", "."))
            lectures.append((propre(m.group(1)), taux, eur, abs(taux * base / 100 - eur) <= 0.011))
    bonnes = [x for x in lectures if x[3]]
    return bonnes[0] if bonnes else lectures[0] if lectures else None


def lire_bareme(pages_texte: list[str]) -> dict:
    """Tables « population, taux en % de l'indice brut 1027, indemnité brute mensuelle » par fonction. Chaque rangée
    est vérifiée : montant = taux x valeur mensuelle de l'indice brut 1027 (au centime près, sinon écartée)."""
    tout = "\n".join(pages_texte)
    m = re.search(r"indice brut 1027 au (1er \w+ 20\d\d) : (\d \d{3},\d{2}) €", tout)
    if not m:
        raise SystemExit("barème DGCL : valeur de l'indice brut 1027 introuvable")
    base = float(m.group(2).replace(" ", "").replace(",", "."))
    decret = re.search(r"Décret n° [\d-]+ du \d{1,2} \w+ 20\d\d", tout)
    out, ecartees = [], 0
    for t in pages_texte:
        ls = [propre(l) for l in t.split("\n")]
        annexe = next((l for l in ls if re.match(r"^ANNEXE \d+$", l)), None)
        i_titre = next((i for i, l in enumerate(ls) if TITRE_FONCTION.match(l)), len(ls))
        collectivite = propre(" ".join(l for l in ls[:i_titre] if not re.match(r"^ANNEXE \d+$", l))) or None
        fonction, article = None, None
        for i, l in enumerate(ls):
            mt = TITRE_FONCTION.match(l)
            if mt:
                reste = mt.group(1) or (ls[i + 1] if i + 1 < len(ls) else "")
                fonction, article = propre(re.sub(r"^DES ", "", reste)).capitalize(), None
                continue
            if fonction and re.match(r"^Art\. ", l):
                article = l
                continue
            if fonction is None:
                continue
            r = rangee_bareme(l, base)
            if r is None:
                continue
            strate, taux_f, eur_f, verifiee = r
            if not strate and 0 < i < len(ls) - 1:  # taux et montant seuls : le libellé entoure la ligne
                strate = propre(ls[i - 1] + " " + ls[i + 1])
            if not strate:
                continue
            if not verifiee:
                ecartees += 1
                continue
            out.append({"annexe": annexe, "collectivite": collectivite, "fonction": fonction, "strate": strate,
                        "taux_pct_ib1027": taux_f, "indemnite_brute_mensuelle_eur": eur_f, "base_legale": article})
    return {"date_valeur": m.group(1), "indice_brut_1027_mensuel_eur": base,
            "decret_valeur_du_point": decret.group(0) if decret else None, "lignes": out,
            "rangees_ecartees": ecartees}


# --- Rapprochement avec le budget de l'État ----------------------------------------------------------------------------

# Groupe de ministères de l'Insee (Insee Première, tableau complémentaire 2) -> ministères du budget (LFI 2023).
# (groupe, lignes de l'Insee qui le composent, ministères du budget). Un ministère du budget n'est que dans un groupe.
GROUPES_INSEE = [
    ("Éducation, enseignement supérieur et recherche", ["Éducation, enseignement supérieur et recherche"],
     ["education_nationale_et_jeunesse", "enseignement_superieur_et_recherche"]),
    ("Économie et finances", ["Économie et finances"],
     ["economie_finances_et_souverainete_industrielle_et_numerique"]),
    ("Intérieur", ["Intérieur"], ["interieur_et_outre_mer"]),
    ("Écologie et environnement", ["Écologie et environnement"], ["transition_ecologique_et_cohesion_des_territoires"]),
    ("Justice", ["Justice"], ["justice"]),
    ("Travail, santé et solidarités", ["Travail, santé et solidarités"],
     ["solidarites_autonomie_et_personnes_handicapees", "travail_plein_emploi_et_insertion"]),
    ("Armées (militaires et personnels civils)", ["Armées (militaires)", "Armées (personnels civils)"], ["armees"]),
    ("Autres ministères", ["Autres ministères"],
     ["agriculture_et_souverainete_alimentaire", "culture", "europe_et_affaires_etrangeres",
      "services_du_premier_ministre", "sports_et_jeux_olympiques_et_paralympiques",
      "transformation_et_fonction_publiques"]),
]


def programmes_de_l_arbre() -> dict[str, dict]:
    racine = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    out = {}

    def parcourir(n):
        if n.get("niveau") == "programme":
            out[n["id"].split("/")[-1]] = {"noeud": n["id"], "fichier": n.get("fichier")}
        for e in n.get("enfants", []):
            parcourir(e)

    parcourir(racine)
    return out


def ministeres_des_programmes() -> dict[str, str]:
    """Programme -> ministère, d'après le jeu des ETPT (LFI 2023) qui alimente site/data/effectifs."""
    import pandas as pd
    d = pd.read_parquet(ETPT_PARQUET, columns=["ministere", "code_programme"]).dropna()
    paires = sorted({(str(int(p)).zfill(3), propre(m)) for m, p in zip(d["ministere"], d["code_programme"])})
    out = {}
    for p, m in paires:
        if p in out and out[p] != m:
            raise SystemExit(f"programme {p} rattaché à deux ministères : double compte possible")
        out[p] = m
    return out


def rapprocher(ministere_de: dict[str, str], effectifs: dict[str, dict], arbre: dict[str, dict],
               conseils_prog: dict[str, dict], conseils_min: dict[str, dict], cabinets: list[dict],
               tableau_insee: dict | None) -> dict:
    """Un ministère = la liste de ses programmes ; chaque programme n'apparaît qu'une fois. ETPT et titre 2 viennent
    de site/data/effectifs (jamais recalculés). Les mesures de sources différentes sont posées côte à côte."""
    mins: dict[str, dict] = {}
    sans_ministere = []
    for p in sorted(effectifs):
        e = effectifs[p]
        ligne = {"programme": p, "libelle": e["libelle"], "etpt": e["etpt"], "titre2_eur": e["titre2_eur"],
                 "fichier_effectifs": f"effectifs/{p}.json", "fichier_arbre": (arbre.get(p) or {}).get("fichier"),
                 "noeud_arbre": (arbre.get(p) or {}).get("noeud")}
        cp = conseils_prog.get(p)
        if cp:
            ligne["conseils_ae_consommees_eur"] = {an: x["ae_consommees_eur"] for an, x in sorted(cp["exercices"].items())}
        m = ministere_de.get(p)
        if m is None:
            sans_ministere.append(ligne)
            continue
        mins.setdefault(slug(m), {"id": slug(m), "ministere": m, "programmes": []})["programmes"].append(ligne)
    conseils_par_cle: dict[str, dict] = {}
    for an, bloc in sorted(conseils_min.items()):
        for l in bloc["lignes"]:
            conseils_par_cle.setdefault(norm(l["ministere"]), {})[an] = l["ae_eur"]
    out = []
    for mid in sorted(mins):
        m = mins[mid]
        ps = m["programmes"]
        m["nb_programmes"] = len(ps)
        m["etpt"] = arrondi(sum(x["etpt"] or 0 for x in ps), 2)
        t2 = [x["titre2_eur"] for x in ps if x["titre2_eur"] is not None]
        m["titre2_eur"] = arrondi(sum(t2), 2) if t2 else None
        m["programmes_sans_titre2"] = [x["programme"] for x in ps if x["titre2_eur"] is None]
        m["conseils_ae_eur"] = conseils_par_cle.get(norm(m["ministere"])) or None
        m["poles_cabinets"] = {str(c["annee"]): [p["pole"] for p in c["poles"] if mid in p["ministeres_budget"]]
                               for c in cabinets}
        m["groupe_insee"] = next((g for g, _, ids in GROUPES_INSEE if mid in ids), None)
        out.append(m)
    groupes = []
    if tableau_insee:
        par_lib = {norm(l["libelle"]): l for l in tableau_insee["lignes"]}
        cols = tableau_insee["colonnes"]
        for g, libs, ids in GROUPES_INSEE:
            ls = [par_lib[norm(x)] for x in libs if norm(x) in par_lib]
            presents = [mins[i] for i in ids if i in mins]
            eff = None
            if len(ls) == len(libs):  # lignes d'un même tableau de l'Insee, sans recouvrement
                eff = {c: arrondi(sum(l["valeurs"][j] for l in ls), 1) for j, c in enumerate(cols)
                       if re.fullmatch(r"20\d\d", c) and all(l["valeurs"][j] is not None for l in ls)}
            groupes.append({
                "groupe_insee": g, "lignes_insee": libs, "ministeres_budget": ids, "effectif_milliers": eff,
                "etpt_ministeres_budget": arrondi(sum(m["etpt"] for m in presents), 2),
                "titre2_ministeres_budget_eur": arrondi(sum(m["titre2_eur"] or 0 for m in presents), 2)})
    return {"ministeres": out, "programmes_sans_ministere": sans_ministere, "groupes_insee": groupes,
            "conseils_hors_nomenclature": {
                an: [l for l in bloc["lignes"] if norm(l["ministere"]) not in {norm(m["ministere"]) for m in out}]
                for an, bloc in sorted(conseils_min.items())}}


# --- Rémunérations : salaires moyens (Insee, DGAFP) et rémunération des salariés des administrations publiques ----------

VERSANTS_SALAIRES = [("fpe", "salaires_fpe", "Fonction publique de l'État"),
                     ("fpt", "salaires_fpt", "Fonction publique territoriale"),
                     ("fph", "salaires_fph", "Fonction publique hospitalière")]
POINTS = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*pts?$")
CLES_DECILES = {"1erdeciled1": "d1", "2edecile": "d2", "3edecile": "d3", "4edecile": "d4", "mediane": "d5",
                "6edecile": "d6", "7edecile": "d7", "8edecile": "d8", "9edeciled9": "d9",
                "rapportinterdeciled9d1": "rapport_d9_d1", "moyenne": "moyenne"}


def sans_points(lignes: list[list]) -> list[list]:
    """« 0,03 pt » (évolution d'un rapport interdécile, en points) -> 0.03 ; l'unité est rappelée dans `notes`."""
    out = []
    for l in lignes:
        r = []
        for c in l:
            m = POINTS.match(propre(c)) if isinstance(c, str) else None
            r.append(float(m.group(1).replace(",", ".")) if m else c)
        out.append(r)
    return out


def tableau_salaires(cle: str, nom: str) -> dict:
    return lire_tableau(sans_points(feuille(chemin(cle), nom)), decimales=2)


def colonne(t: dict, *mots: str) -> int:
    """Indice de la colonne dont l'en-tête contient tous les mots (sans accent ni casse)."""
    cands = [j for j, c in enumerate(t["colonnes"]) if all(norm(m) in norm(c) for m in mots)]
    if len(cands) != 1:
        raise SystemExit(f"« {t['titre']} » : colonne {mots} introuvable ou ambiguë ({cands})")
    return cands[0]


def ligne_de(t: dict, libelle: str, rubrique: str | None = None) -> dict:
    cands = [l for l in t["lignes"] if norm(l["libelle"]) == norm(libelle)
             and (rubrique is None or norm(l["rubrique"] or "") == norm(rubrique))]
    if not cands:
        raise SystemExit(f"« {t['titre']} » : ligne « {libelle} » introuvable")
    return cands[0]


def deciles(t: dict, j_montant: int, j_evol: int | None) -> dict:
    out = {}
    for l in t["lignes"]:
        k = CLES_DECILES.get(norm(l["libelle"]))
        if k:
            out[k] = {"valeur": l["valeurs"][j_montant],
                      "evolution": l["valeurs"][j_evol] if j_evol is not None else None}
    manquants = [k for k in CLES_DECILES.values() if k not in out]
    if manquants:
        raise SystemExit(f"« {t['titre']} » : déciles absents {manquants}")
    return out


def lire_salaires_versant(cle: str) -> dict:
    """Insee Première sur les salaires d'un versant : moyennes brutes et nettes en EQTP (figure 1), série en euros
    constants (figure 2), catégories A, B, C des fonctionnaires (figure 4, tableaux complémentaires 1 et 5), déciles
    (figure 5). Contrôles bloquants : net moyen identique entre figure 4 et tableau complémentaire 5 ; moyenne des
    déciles égale au net moyen de la catégorie."""
    som = feuille(chemin(cle), "Sommaire")
    titre = propre(som[0][0]) if som and som[0] else ""
    m = re.search(r"en (20\d\d)", titre)
    if not m:
        raise SystemExit(f"{cle} : année introuvable dans « {titre} »")
    annee = int(m.group(1))
    f1, f2, f4, f5 = (tableau_salaires(cle, f"Figure {k}") for k in (1, 2, 4, 5))
    noms = feuilles(chemin(cle))
    tc1 = tableau_salaires(cle, next(n for n in noms if re.match(r"^(Tableau|Figure) complémentaire 1$", n)))
    tc5 = tableau_salaires(cle, next(n for n in noms if re.match(r"^(Tableau|Figure) complémentaire 5$", n)))
    jp = colonne(f1, "structure")
    jb, jbc, jbk = (colonne(f1, "brut", "montant"), colonne(f1, "brut", "courants"), colonne(f1, "brut", "constants"))
    jn, jnc, jnk = (colonne(f1, "net", "montant"), colonne(f1, "net", "courants"), colonne(f1, "net", "constants"))

    def moyennes(l):
        v = l["valeurs"]
        return {"rubrique": l["rubrique"], "libelle": re.sub(r",? dont\s*:?$", "", l["libelle"]).strip(),
                "part_eqtp_pct": v[jp], "brut_eur": v[jb], "brut_evolution_courants_pct": v[jbc],
                "brut_evolution_constants_pct": v[jbk], "net_eur": v[jn], "net_evolution_courants_pct": v[jnc],
                "net_evolution_constants_pct": v[jnk]}
    lignes = [moyennes(l) for l in f1["lignes"]]
    ens = [l for l in lignes if re.match(r"^ensemble de la fp[eth] y compris", l["libelle"], re.I)]
    fp_tout = [l for l in lignes if norm(l["libelle"]) == "ensembledelafonctionpublique"]
    if len(ens) != 1 or len(fp_tout) != 1:
        raise SystemExit(f"{cle} : ligne d'ensemble introuvable dans la figure 1")
    # Catégories des fonctionnaires
    j4p = next(j for j, c in enumerate(f4["colonnes"]) if norm(c).startswith(norm(f"Agents présents en {annee}"))
               and "structure" in norm(c))
    j4n = next(j for j, c in enumerate(f4["colonnes"]) if norm(c).startswith(norm(f"Agents présents en {annee}"))
               and "montant" in norm(c))
    j4k = next(j for j, c in enumerate(f4["colonnes"]) if norm(c).startswith(norm(f"Agents présents en {annee}"))
               and "constants" in norm(c) and "rmpp" not in norm(c))
    j5 = {k: colonne(tc5, "montant", k) for k in ("salaire brut", "traitement brut", "primes", "cotisations",
                                                    "salaire net")}
    jpp = next(j for j, c in enumerate(tc5["colonnes"]) if "partdesprimes" in norm(c))
    categories = []
    for cat in ("A", "B", "C"):
        l4 = ligne_de(f4, f"Catégorie {cat}")
        l5 = ligne_de(tc5, f"Catégorie {cat}")
        v5 = l5["valeurs"]
        if abs(v5[j5["salaire net"]] - l4["valeurs"][j4n]) > 1:
            raise SystemExit(f"{cle} : net moyen de la catégorie {cat} différent entre figure 4 et complément 5")
        jm = colonne(tc1, f"Catégorie {cat}", "montant")
        jk = colonne(tc1, f"Catégorie {cat}", "constants")
        dec = deciles(tc1, jm, jk)
        if abs(dec["moyenne"]["valeur"] - l4["valeurs"][j4n]) > 1:
            raise SystemExit(f"{cle} : moyenne des déciles de la catégorie {cat} différente du net moyen")
        categories.append({"categorie": cat, "population": f"fonctionnaires de catégorie {cat}",
                           "part_eqtp_pct": l4["valeurs"][j4p], "net_eur": l4["valeurs"][j4n],
                           "net_evolution_constants_pct": l4["valeurs"][j4k], "brut_eur": v5[j5["salaire brut"]],
                           "traitement_brut_eur": v5[j5["traitement brut"]],
                           "primes_et_remunerations_annexes_eur": v5[j5["primes"]],
                           "cotisations_csg_crds_eur": v5[j5["cotisations"]], "part_primes_dans_brut_pct": v5[jpp],
                           "deciles_net_eur": dec})
    # Série en euros constants
    serie = []
    for l in f2["lignes"]:
        if re.fullmatch(r"(19|20)\d\d", l["libelle"]):
            serie.append({"annee": int(l["libelle"]), "net_eur_constants": l["valeurs"][0],
                          "evolution_constants_pct": l["valeurs"][1]})
    ref = re.search(r"constants (20\d\d)", " ".join(f2["colonnes"]))
    if not serie or serie[-1]["annee"] != annee or abs(serie[-1]["net_eur_constants"] - ens[0]["net_eur"]) > 1:
        raise SystemExit(f"{cle} : série en euros constants incohérente avec la moyenne de {annee}")
    jd = colonne(f5, "ensemble", "montant")
    jdk = colonne(f5, "ensemble", "constants")
    dec_ens = deciles(f5, jd, jdk)
    tableaux = {slug(n): t for n, t in (("figure_1", f1), ("figure_2", f2), ("figure_4", f4), ("figure_5", f5),
                                        ("tableau_complementaire_1", tc1), ("tableau_complementaire_5", tc5))}
    return {"annee": annee, "publication": re.sub(r"^Données de l'Insee Première no \d+ ", "", titre).strip("« »"),
            "champ": next((n for n in f1["notes_source"] if n.startswith("Champ")), None),
            "ensemble": {k: v for k, v in ens[0].items() if k != "rubrique"},
            "lignes": lignes, "categories_fonctionnaires": categories,
            "deciles_net_eur": dec_ens,
            "serie_net_euros_constants": {"euros_constants_de": int(ref.group(1)) if ref else annee, "annees": serie},
            "fonction_publique": {k: v for k, v in fp_tout[0].items() if k not in ("rubrique", "part_eqtp_pct")},
            "tableaux": tableaux}


def classeur_du_zip(cle: str, motif: str):
    """Classeur xlsx d'une archive de l'entrepôt, en mémoire (BytesIO, lu par openpyxl)."""
    import io
    import zipfile
    with zipfile.ZipFile(chemin(cle)) as z:
        noms = [n for n in z.namelist() if re.search(motif, n)]
        if len(noms) != 1:
            raise SystemExit(f"{cle} : membre {motif!r} introuvable ou ambigu ({noms})")
        return io.BytesIO(z.read(noms[0])), noms[0]


def feuille_zip(cle: str, motif: str, nom: str) -> list[list]:
    import io
    b, _ = classeur_du_zip(cle, motif)
    return feuille(io.BytesIO(b.getvalue()), nom)


VERSANTS_DGAFP = {"FPE": "fpe", "FPT": "fpt", "FPH": "fph", "Fonction publique": "fonction_publique",
                  "Ensemble FP": "fonction_publique"}


def euro(x):
    return arrondi(x, 0) if isinstance(x, (int, float)) else None


def lire_dgafp_moyennes(lignes: list[list]) -> list[dict]:
    """Figure 3 : salaire net moyen par catégorie et statut (bloc) et par versant (une ligne par versant)."""
    out, bloc = [], None
    for l in lignes:
        cel = [propre(c) if isinstance(c, str) else c for c in l]
        if len(cel) < 4 or not isinstance(cel[3], (int, float)) or cel[2] not in VERSANTS_DGAFP:
            continue
        if cel[1]:
            bloc = {"population": sans_appel_de_note(re.sub(r"\s*\(\d\)$", "", cel[1])), "net_eur": {}}
            out.append(bloc)
        bloc["net_eur"][VERSANTS_DGAFP[cel[2]]] = euro(cel[3])
    for b in out:
        if set(b["net_eur"]) != {"fpe", "fpt", "fph", "fonction_publique"}:
            raise SystemExit(f"DGAFP figure 3 : versants incomplets pour « {b['population']} »")
    return out


def lire_dgafp_decomposition(lignes: list[list]) -> list[dict]:
    """Figure 9 : décomposition du salaire des fonctionnaires (brut, traitement, primes, cotisations, CSG et CRDS,
    net), par catégorie et par versant. Contrôle bloquant : brut - cotisations salariales - CSG et CRDS = net."""
    i_ent = next(i for i, l in enumerate(lignes) if "FPE" in [propre(c) for c in l if isinstance(c, str)])
    cols = {j: VERSANTS_DGAFP[propre(c)] for j, c in enumerate(lignes[i_ent]) if isinstance(c, str)
            and propre(c) in VERSANTS_DGAFP}
    fin, notes = pied_de_tableau([[c for c in l if c is not None] for l in lignes])
    out, bloc = [], None
    for l in lignes[i_ent + 1:]:
        cel = [propre(c) if isinstance(c, str) else c for c in l] + [None] * 8
        if not cel[2] or not isinstance(cel[2], str):
            if cel[1] and str(cel[1]).startswith(("Source", "Champ")):
                break
            continue
        if cel[1]:
            pop = {"Ensemble": "ensemble des fonctionnaires"}.get(cel[1], f"fonctionnaires de catégorie {cel[1]}")
            bloc = {"categorie": None if cel[1] == "Ensemble" else cel[1], "population": pop, "elements": []}
            out.append(bloc)
        lib = re.sub(r"^[-\s]+", "", cel[2])
        lib = re.sub(r"\((\d)\)", "", lib).replace("\n", " ")
        lib = re.sub(r"\s+", " ", lib).strip()
        vals = {v: (arrondi(cel[j], 1) if "%" in lib else euro(cel[j])) if isinstance(cel[j], (int, float)) else None
                for j, v in cols.items()}
        bloc["elements"].append({"id": slug(re.sub(r"\s*\([abc]\)|=.*$", "", lib)), "libelle": lib,
                                 "valeurs": vals, "non_publie": [v for v, x in vals.items() if x is None]})
    for b in out:
        e = {x["id"]: x["valeurs"] for x in b["elements"]}
        for v in cols.values():
            brut, cot, csg = e["salaire_brut"][v], e["cotisations_salariales"][v], e["csg_et_crds"][v]
            net = e["salaire_net_de_prelevements"][v]
            if abs(brut - cot - csg - net) > 2:
                raise SystemExit(f"DGAFP figure 9 : brut - cotisations - CSG différent du net ({b['population']}, {v})")
    return out


def lire_dgafp_distribution(lignes: list[list]) -> dict:
    """Figure 1 : salaire net moyen, médian, déciles et quartiles par versant, statut, sexe et âge."""
    i_ent = next(i for i, l in enumerate(lignes) if any(isinstance(c, str) and propre(c) == "Salaire médian" for c in l))
    ent = [propre(c) if isinstance(c, str) else "" for c in lignes[i_ent]]
    cles = {"structure": "part_eqtp_pct", "salairemoyen": "moyenne_eur", "salairemedian": "mediane_eur",
            "1erdecile": "d1_eur", "1erquartile": "q1_eur", "3equartile": "q3_eur", "9edecile": "d9_eur"}
    cols = {}
    for j, e in enumerate(ent):
        for k, v in cles.items():
            if norm(e).startswith(k):
                cols[j] = v
    if len(cols) != len(cles):
        raise SystemExit(f"DGAFP figure 1 : en-têtes inattendus {ent}")
    j_lib = min(cols) - 1
    out = []
    for l in lignes[i_ent + 1:]:
        if len(l) <= max(cols) or not isinstance(l[j_lib], str) or not isinstance(l[max(cols)], (int, float)):
            continue
        lib = sans_appel_de_note(re.sub(r"\(\d\)$", "", propre(l[j_lib])).strip())
        out.append({"population": re.sub(r"^dont ", "", lib),
                    **{v: (arrondi(l[j], 1) if v.endswith("pct") else euro(l[j])) for j, v in cols.items()}})
    return {"lignes": out, "notes_source": [propre(l[j_lib]) for l in lignes[i_ent + 1:]
                                             if len(l) > j_lib and isinstance(l[j_lib], str)
                                             and propre(l[j_lib]).startswith(("Source", "Champ", "("))]}


SECTIONS_DEPENSES = {"depensesderemunerationenmdeur": "remuneration_md_eur", "poidsdanslepibenpourcent": "part_pib_pct",
                     "poidsdesdepensesderemunerationdesapudansleurdepensetotaleenpourcent":
                         "part_depense_totale_pct", "depensestotalesenmdeur": "depenses_totales_md_eur"}
SECTEURS_DEPENSES = [("administrationspubliquescentrales", "apuc", "Administrations publiques centrales"),
                     ("dontetat", "etat", "dont État"),
                     ("administrationspubliqueslocales", "apul", "Administrations publiques locales"),
                     ("dontcollectiviteslocales", "collectivites_locales", "dont collectivités locales"),
                     ("administrationsdesecuritesociale", "asso", "Administrations de sécurité sociale"),
                     ("dontorganismesdependantdesassurancessociales", "odass",
                      "dont organismes dépendant des assurances sociales (hôpitaux notamment)"),
                     ("toutesadministrationspubliques", "apu", "Toutes administrations publiques"),
                     ("produitinterieurbrut", "pib", "Produit intérieur brut")]
STATUTS_COMPTES = {"*": "définitif actualisé", "**": "semi-définitif", "***": "provisoire"}


def lire_dgafp_depenses(lignes: list[list]) -> dict:
    """Figure 1 du classeur « dépenses » : rémunérations (D1) et dépenses totales des administrations publiques par
    sous-secteur, en comptabilité nationale (Insee, traitement DGAFP), 1978 à la dernière année."""
    i_an = next(i for i, l in enumerate(lignes) if sum(1 for c in l if re.fullmatch(r"(19|20)\d\d\**", propre(c))) >= 3)
    annees, statuts = {}, {}
    for j, c in enumerate(lignes[i_an]):
        m = re.fullmatch(r"((?:19|20)\d\d)(\**)", propre(c))
        if m:
            annees[j] = int(m.group(1))
            if m.group(2):
                statuts[int(m.group(1))] = STATUTS_COMPTES[m.group(2)]
    section, out = None, {v: {} for v in SECTIONS_DEPENSES.values()}
    for l in lignes[i_an + 1:]:
        if not l or not isinstance(l[0], str):
            continue
        k = norm(l[0].replace("%", " pourcent").replace("€", " eur"))
        if k in SECTIONS_DEPENSES and all(c is None for c in l[1:]):
            section = SECTIONS_DEPENSES[k]
            continue
        if section is None:
            continue
        k = re.sub(r"\d$", "", norm(re.sub(r"\(\d\)", "", l[0])))
        sid = next((s for n, s, _ in SECTEURS_DEPENSES if k == n), None)
        if sid is None:
            if k.startswith("source"):
                break
            continue
        if sid == "pib":
            section_pib = "pib_md_eur"
            out.setdefault(section_pib, {})[sid] = [arrondi(l[j], 4) if isinstance(l[j], (int, float)) else None
                                                    for j in sorted(annees)]
            continue
        d = 4 if section.endswith("md_eur") else 3
        out[section][sid] = [arrondi(l[j], d) if j < len(l) and isinstance(l[j], (int, float)) else None
                             for j in sorted(annees)]
    for s in ("remuneration_md_eur", "part_depense_totale_pct", "depenses_totales_md_eur"):
        if "apu" not in out[s]:
            raise SystemExit(f"DGAFP dépenses : section {s} incomplète")
    return {"annees": [annees[j] for j in sorted(annees)], "statut_des_comptes": statuts,
            "secteurs": [{"id": s, "libelle": l} for _, s, l in SECTEURS_DEPENSES if s != "pib"], **out}


SECTEURS_EUROSTAT = {"S13": ("apu", "Administrations publiques"),
                     "S1311": ("apuc", "Administration centrale (État et organismes divers d'administration centrale)"),
                     "S1313": ("apul", "Administrations locales"),
                     "S1314": ("asso", "Administrations de sécurité sociale")}


def lire_eurostat_d1() -> dict:
    """gov_10a_exp, France, fonction totale : D1 et TE par sous-secteur, en millions d'euros et en % du PIB, avec les
    indicateurs de statut d'Eurostat (« p » : provisoire). Contrôle bloquant : somme des D1 des sous-secteurs = D1 des
    administrations publiques (la rémunération des salariés n'est pas consolidée entre sous-secteurs)."""
    d = json.loads(chemin("eurostat_d1").read_text(encoding="utf-8"))
    ids, tailles = d["id"], d["size"]
    cats = [[c for c, _ in sorted(d["dimension"][k]["category"]["index"].items(), key=lambda kv: kv[1])] for k in ids]
    pas = [1] * len(ids)
    for i in range(len(ids) - 2, -1, -1):
        pas[i] = pas[i + 1] * tailles[i + 1]
    statut = d.get("status") or {}
    val: dict = {}
    for plat, v in d["value"].items():
        r = {k: cs[(int(plat) // p) % t] for k, cs, p, t in zip(ids, cats, pas, tailles)}
        val[(r["unit"], r["sector"], r["na_item"], int(r["time"]))] = (v, statut.get(plat))
    annees = sorted({k[3] for k in val})
    lignes = []
    for a in annees:
        e = {"annee": a, "provisoire": any(val.get((u, s, n, a), (None, None))[1] == "p" for u in ("MIO_EUR",)
                                           for s in SECTEURS_EUROSTAT for n in ("D1", "TE"))}
        for n, nom in (("D1", "remuneration_m_eur"), ("TE", "depenses_totales_m_eur")):
            e[nom] = {SECTEURS_EUROSTAT[s][0]: val.get(("MIO_EUR", s, n, a), (None,))[0] for s in SECTEURS_EUROSTAT}
        e["remuneration_pct_pib"] = {SECTEURS_EUROSTAT[s][0]: val.get(("PC_GDP", s, "D1", a), (None,))[0]
                                     for s in SECTEURS_EUROSTAT}
        r, t = e["remuneration_m_eur"], e["depenses_totales_m_eur"]
        if None not in r.values():
            if abs(r["apuc"] + r["apul"] + r["asso"] - r["apu"]) > 1:
                raise SystemExit(f"Eurostat {a} : la somme des D1 des sous-secteurs diffère du total")
        e["sur_100_eur_de_depense_publique"] = (arrondi(100 * r["apu"] / t["apu"], 2)
                                                if r["apu"] is not None and t["apu"] else None)
        e["repartition_remuneration_pct"] = ({k: arrondi(100 * r[k] / r["apu"], 1) for k in ("apuc", "apul", "asso")}
                                             if None not in r.values() else None)
        lignes.append(e)
    return {"mise_a_jour_eurostat": d.get("updated"), "secteurs": [{"id": v[0], "code": k, "libelle": v[1]}
                                                                    for k, v in SECTEURS_EUROSTAT.items()],
            "annees": lignes}


def remunerations(collecte: str, budget_etat: dict | None) -> dict:
    """Contenu de remunerations.json (sans écriture)."""
    versants = []
    for vid, cle, lib in VERSANTS_SALAIRES:
        v = lire_salaires_versant(cle)
        versants.append({"id": vid, "libelle": lib, "source": src(cle), **v})
    annee = {v["annee"] for v in versants}
    if len(annee) != 1:
        raise SystemExit(f"salaires Insee : années différentes selon le versant {annee}")
    annee = annee.pop()
    fp_tout = {json.dumps(v["fonction_publique"], sort_keys=True) for v in versants}
    if len(fp_tout) != 1:
        raise SystemExit("salaires Insee : l'ensemble de la fonction publique diffère entre les trois publications")
    xlsx_vue = r"vue_ren?umerations_niveaux\.xlsx$"
    dgafp_moy = lire_dgafp_moyennes(feuille_zip("dgafp_remu", xlsx_vue, "Figure 3"))
    dgafp_dec = lire_dgafp_decomposition(feuille_zip("dgafp_remu", xlsx_vue, "Figure 9"))
    dgafp_dis = lire_dgafp_distribution(feuille_zip("dgafp_remu", xlsx_vue, "Figure 1"))
    dep = lire_dgafp_depenses(feuille_zip("dgafp_remu", r"donnees_comp_depenses\.xlsx$", "Figure 1"))
    eu = lire_eurostat_d1()
    # Dernière année commune Eurostat / DGAFP
    eu_an = {e["annee"]: e for e in eu["annees"] if e["sur_100_eur_de_depense_publique"] is not None}
    k_dg = {a: i for i, a in enumerate(dep["annees"])}
    communes = sorted(set(eu_an) & {a for a in k_dg if dep["remuneration_md_eur"]["apu"][k_dg[a]] is not None})
    a = communes[-1]
    e, i = eu_an[a], k_dg[a]
    sur100 = {
        "annee": a,
        "valeurs": [
            {"producteur": "Eurostat", "source": src("eurostat_d1"), "valeur_eur": e["sur_100_eur_de_depense_publique"],
             "statut": "calculé", "provisoire": e["provisoire"],
             "formule": "100 x rémunération des salariés (D1) des administrations publiques / total des dépenses des "
                        "administrations publiques (TE), en millions d'euros, gov_10a_exp, fonction totale",
             "remuneration_m_eur": e["remuneration_m_eur"]["apu"],
             "depenses_totales_m_eur": e["depenses_totales_m_eur"]["apu"]},
            {"producteur": "DGAFP (comptes nationaux de l'Insee)", "source": src("dgafp_remu"),
             "valeur_eur": arrondi(dep["part_depense_totale_pct"]["apu"][i], 2), "statut": "publié",
             "statut_des_comptes": dep["statut_des_comptes"].get(a),
             "remuneration_md_eur": dep["remuneration_md_eur"]["apu"][i],
             "depenses_totales_md_eur": dep["depenses_totales_md_eur"]["apu"][i]}],
        "lecture": f"Sur 100 € de dépense de l'ensemble des administrations publiques (État, organismes centraux, "
                   f"collectivités locales, sécurité sociale et hôpitaux) en {a}, part qui rémunère leurs salariés "
                   f"(salaires bruts et cotisations des employeurs). Deux publications, posées côte à côte."}
    ecarts = [
        {"grandeur": f"rémunération des salariés des administrations publiques en {a}",
         "valeurs": [{"source": "Eurostat gov_10a_exp", "valeur": e["remuneration_m_eur"]["apu"], "unite": "M€"},
                     {"source": "DGAFP, rapport annuel 2025", "valeur": arrondi(dep["remuneration_md_eur"]["apu"][i] * 1000, 1),
                      "unite": "M€"}],
         "note": "Même agrégat des comptes nationaux (D1) ; valeurs publiées telles quelles."},
        {"grandeur": f"total des dépenses des administrations publiques en {a}",
         "valeurs": [{"source": "Eurostat gov_10a_exp", "valeur": e["depenses_totales_m_eur"]["apu"], "unite": "M€"},
                     {"source": "DGAFP, rapport annuel 2025",
                      "valeur": arrondi(dep["depenses_totales_md_eur"]["apu"][i] * 1000, 1), "unite": "M€"}],
         "note": f"Millésimes de comptes différents (mise à jour Eurostat du {(eu['mise_a_jour_eurostat'] or '')[:10]}, "
                 "édition 2025 du rapport de la DGAFP) : l'écart n'est pas arbitré."},
        {"grandeur": f"part de la rémunération des salariés dans la dépense publique en {a}, en %",
         "valeurs": [{"source": "Eurostat gov_10a_exp (calcul du site)", "valeur": e["sur_100_eur_de_depense_publique"]},
                     {"source": "DGAFP, rapport annuel 2025 (publié)",
                      "valeur": arrondi(dep["part_depense_totale_pct"]["apu"][i], 2)}],
         "note": "Les deux publications retiennent la même rémunération des salariés et un total des dépenses "
                 "différent (ligne précédente)."}]
    i_dg = len(dep["annees"]) - 1
    reperes_etat = {
        "lecture": "Deux mesures de périmètres différents, jamais additionnées ni soustraites : le titre 2 du budget "
                   "de l'État (crédits de personnel votés, y compris la contribution au compte d'affectation spéciale "
                   "Pensions) et la rémunération des salariés de l'État en comptabilité nationale (D1, sous-secteur "
                   "État, hors organismes divers d'administration centrale).",
        "titre2_budget_etat_eur": (budget_etat or {}).get("titre2_eur"),
        "millesime_titre2": (budget_etat or {}).get("millesime_titre2"),
        "remuneration_salaries_etat_md_eur": dep["remuneration_md_eur"]["etat"][i_dg],
        "annee_remuneration_salaries_etat": dep["annees"][i_dg], "source_remuneration": src("dgafp_remu")}
    return {
        "millesime": f"salaires {annee} (Insee) et 2023 (DGAFP) ; rémunération des salariés des administrations "
                     f"publiques {eu['annees'][0]['annee']} à {eu['annees'][-1]['annee']} (Eurostat) et "
                     f"{dep['annees'][0]} à {dep['annees'][-1]} (DGAFP)",
        "source": src(*(c for _, c, _ in VERSANTS_SALAIRES), "dgafp_remu", "eurostat_d1"), "collecte_le": collecte,
        "definitions": {
            "eqtp": "équivalent temps plein : un poste à mi-temps occupé toute l'année compte pour 0,5 ; les salaires "
                    "sont ramenés à ce qu'ils seraient pour un temps plein sur toute l'année, par mois",
            "salaire_brut": "traitement indiciaire, primes et rémunérations annexes, indemnité de résidence et "
                            "supplément familial, avant cotisations salariales, CSG et CRDS",
            "salaire_net": "salaire brut diminué des cotisations salariales, de la CSG et de la CRDS ; avant impôt sur "
                           "le revenu",
            "euros_constants": "montants corrigés de la hausse des prix à la consommation (y compris tabac), pour "
                               "comparer les années entre elles",
            "remuneration_des_salaries": "agrégat D1 des comptes nationaux : salaires et traitements bruts et "
                                         "cotisations sociales à la charge des employeurs (effectives et imputées, dont "
                                         "pensions des fonctionnaires de l'État), versés par les administrations "
                                         "publiques à leurs salariés, militaires compris",
            "depense_publique": "total des dépenses des administrations publiques (TE) : État, organismes divers "
                                "d'administration centrale, collectivités et organismes locaux, sécurité sociale et "
                                "hôpitaux publics, consolidé entre ces sous-secteurs"},
        "regle_personnes": "Moyennes, médianes et déciles publiés par l'Insee et la DGAFP sur des populations entières "
                           "(versant, catégorie, statut, sexe, âge) ; aucune rémunération individuelle, aucun nom. Les "
                           "hautes rémunérations nominatives publiées par certains employeurs ne sont pas lues.",
        "valeurs_absentes": "null : « /// » dans la source (absence de résultat due à la nature des choses), ou valeur "
                            "publiée pour un seul versant (`non_publie`)",
        "salaires": {
            "annee": annee, "unite": "euros par mois en équivalent temps plein (EQTP)",
            "producteur": "Insee (Siasp)",
            "fonction_publique": versants[0]["fonction_publique"],
            "versants": versants,
            "notes": ["Les évolutions sont en % d'une année sur l'autre ; celle du rapport interdécile est en points.",
                      "Catégories A, B, C : fonctionnaires seulement ; contractuels et personnels médicaux à part.",
                      "Champ : France hors Mayotte, hors militaires, apprentis, internes et externes médicaux, "
                      "assistants maternels et familiaux."]},
        "salaires_dgafp": {
            "annee": 2023, "unite": "euros par mois en équivalent temps plein (EQTP)", "producteur":
            "DGAFP (Siasp de l'Insee, traitements Drees, DGCL et DGAFP)", "source": src("dgafp_remu"),
            "moyennes_nettes": dgafp_moy, "decomposition_fonctionnaires": dgafp_dec,
            "distribution_nette": dgafp_dis["lignes"], "notes_source": dgafp_dis["notes_source"],
            "lecture": "Seule source de cette sélection qui publie, pour l'ensemble de la fonction publique, le salaire "
                       "brut et net moyen par catégorie ; millésime antérieur d'un an à celui de l'Insee : les deux ne "
                       "sont pas comparés."},
        "remuneration_salaries_apu": {
            "unite": "millions d'euros (Eurostat) ; milliards d'euros (DGAFP)",
            "sur_100_eur": sur100,
            "eurostat": {"source": src("eurostat_d1"), **eu},
            "dgafp": {"source": src("dgafp_remu"), **dep},
            "notes": ["Les dépenses des sous-secteurs ne s'additionnent pas : les transferts entre eux sont "
                      "consolidés dans le total des administrations publiques.",
                      "La rémunération des salariés n'est pas consolidée : la somme des sous-secteurs égale le total.",
                      "Dernières années provisoires ou semi-définitives (indicateurs `provisoire`, "
                      "`statut_des_comptes`)."]},
        "reperes_budget_etat": reperes_etat,
        "ecarts_entre_sources": ecarts,
        "regles": ["Les salaires moyens (par agent en EQTP, nets ou bruts, hors cotisations des employeurs) et la "
                   "rémunération des salariés des comptes nationaux (masse totale, cotisations des employeurs "
                   "comprises) sont deux mesures différentes : jamais multipliées l'une par l'autre ni additionnées.",
                   "Insee (2024) et DGAFP (2023) : millésimes différents, posés côte à côte.",
                   "La part sur 100 € de dépense publique porte sur toutes les administrations publiques, pas seulement "
                   "sur le budget de l'État."],
        "limites": ["Moyennes en EQTP : un agent à temps partiel est compté au prorata, son salaire est ramené à un "
                    "temps plein.",
                    "Militaires exclus des salaires de l'Insee et de la DGAFP ; ils sont compris dans la rémunération "
                    "des salariés des comptes nationaux.",
                    "L'Insee ne publie pas, dans les trois Insee Première de 2024, de moyenne par catégorie pour "
                    "l'ensemble des trois versants ; cette moyenne vient de la DGAFP pour 2023.",
                    "Insee, comptes des administrations publiques (Melodi DD_CNA_APU) : rémunération des salariés "
                    "concordante, mais total des dépenses à 75 % du PIB, incohérent avec le total publié (57 %) : non "
                    "retenu en attendant une explication du producteur."]}


def produire_remunerations(sortie: Path = SORTIE) -> dict:
    """Écrit remunerations.json seul (budget de l'État relu dans index.json s'il existe)."""
    manquants = [SOURCES[c][0] for c in ("salaires_fpe", "salaires_fpt", "salaires_fph", "dgafp_remu",
                                         "eurostat_d1") if not chemin(c).exists()]
    if manquants:
        raise SystemExit(f"sources absentes de {LAKE} : {manquants} (python collecte/collecte.py --domaine "
                         "fonction_publique)")
    idx = sortie / "index.json"
    be = json.loads(idx.read_text(encoding="utf-8"))["reperes"].get("budget_etat") if idx.exists() else None
    r = remunerations(date_sources("fonction_publique"), be)
    dump(sortie / "remunerations.json", r)
    return r


def reperes_remunerations(r: dict) -> dict:
    s100 = r["remuneration_salaries_apu"]["sur_100_eur"]
    return {"annee_salaires": r["salaires"]["annee"],
            "net_moyen_eur": {v["id"]: v["ensemble"]["net_eur"] for v in r["salaires"]["versants"]}
            | {"fonction_publique": r["salaires"]["fonction_publique"]["net_eur"]},
            "brut_moyen_eur": {v["id"]: v["ensemble"]["brut_eur"] for v in r["salaires"]["versants"]}
            | {"fonction_publique": r["salaires"]["fonction_publique"]["brut_eur"]},
            "sur_100_eur_depense_publique": {"annee": s100["annee"],
                                             "valeurs": [{"producteur": v["producteur"], "valeur_eur": v["valeur_eur"],
                                                          "statut": v["statut"]} for v in s100["valeurs"]]}}


# --- Production ----------------------------------------------------------------------------------------------------------

RECHERCHE_PREALABLE = [
    {"trouvaille": "Insee, fichiers des séries longues et de l'Insee Première n° 2094 (Siasp), TCRD 052",
     "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026 (millésime 2024)",
     "usage": "source des effectifs par versant, statut, ministère, type d'employeur, région et département"},
    {"trouvaille": "data.economie.gouv.fr et data.gouv.fr, jeux « jaune personnels affectés dans les cabinets "
     "ministériels » des PLF 2012 à 2018", "verdict": "à adapter", "licence": "Licence Ouverte 2.0",
     "mise_a_jour": "2018-12-13", "usage": "aucun jeu structuré après le PLF 2018 : non repris ici ; piste pour une "
     "série 2007-2017"},
    {"trouvaille": "jaunes « Personnels affectés dans les cabinets ministériels » PLF 2025 et 2026 (PDF, miroir "
     "Assemblée nationale)", "verdict": "à adapter", "licence": "document administratif public (réutilisation libre, "
     "article L. 321-1 CRPA)", "mise_a_jour": "PLF 2026 (octobre 2025)", "usage": "lus par pdfplumber, agrégats par "
     "pôle ministériel"},
    {"trouvaille": "jaunes « Recours aux conseils extérieurs » PLF 2024, 2025 et 2026 (PDF, miroir Assemblée "
     "nationale)", "verdict": "à adapter", "licence": "document administratif public (réutilisation libre, article "
     "L. 321-1 CRPA)", "mise_a_jour": "PLF 2026 (octobre 2025)", "usage": "aucun jeu structuré trouvé sur data.gouv.fr "
     "ni data.economie.gouv.fr : tables lues par pdfplumber"},
    {"trouvaille": "data.gouv.fr, indemnités de fonction publiées par des collectivités (Nantes, Tours, région "
     "Île-de-France...)", "verdict": "inspiration seulement", "licence": "Licence Ouverte 2.0",
     "mise_a_jour": "2026-09-24", "usage": "montants par élu nommé : hors périmètre ; seul le barème légal (DGCL) est "
     "repris"},
    {"trouvaille": "pipeline/operateurs.py du dépôt (lecture de jaunes PDF par mots positionnés et ancres de colonnes)",
     "verdict": "à adapter", "licence": "MIT", "mise_a_jour": "2026-11-17", "usage": "méthode de lecture des PDF"},
    {"trouvaille": "Insee Première n° 2100, 2101 et 2102 (salaires 2024 par versant), classeurs des figures",
     "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026 (millésime 2024)",
     "usage": "salaires bruts et nets moyens par versant et catégorie, déciles, série depuis 2010"},
    {"trouvaille": "DGAFP, rapport annuel 2025, archives xlsx des vues « rémunérations » (niveaux ; dépenses de "
     "personnel)", "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2025 "
     "(millésime 2023 ; comptes nationaux jusqu'en 2024)", "usage": "moyennes par catégorie pour l'ensemble de la "
     "fonction publique ; part de la rémunération des salariés dans la dépense publique, publiée"},
    {"trouvaille": "Eurostat gov_10a_exp (D1 et TE par sous-secteur) et décodeur JSON-stat de pipeline/transform.py",
     "verdict": "réutilisable tel quel", "licence": "CC BY 4.0 (Eurostat) ; MIT", "mise_a_jour": "2026-10-21",
     "usage": "rémunération des salariés de toutes les administrations publiques sur 100 € de dépense publique"},
    {"trouvaille": "Insee, Tableaux de l'économie française, « Salaires dans la fonction publique » (page 4277685)",
     "verdict": "inspiration seulement", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2020-02-27 (millésime "
     "2017)", "usage": "millésime trop ancien : remplacé par les Insee Première de 2024"},
    {"trouvaille": "Insee Melodi, comptes des administrations publiques (DD_CNA_APU, déjà dans l'entrepôt)",
     "verdict": "inspiration seulement", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026",
     "usage": "D1 concordant avec Eurostat, mais total des dépenses à 75 % du PIB, incohérent : non retenu"},
    {"trouvaille": "dépôts publics GitHub (recherches « cabinets ministériels », « conseils extérieurs jaune », "
     "« indemnités élus barème », « siasp »)", "verdict": "inspiration seulement", "licence": "sans objet",
     "mise_a_jour": "2026-11-17", "usage": "aucun dépôt réutilisable trouvé"},
]
REGLES_SANS_DOUBLE_COMPTE = [
    "Un programme appartient à un seul ministère (jeu des ETPT de la LFI 2023) ; le total d'un ministère est la somme "
    "de ses programmes, lus dans site/data/effectifs sans nouveau calcul.",
    "Les effectifs de l'Insee (personnes en poste au 31 décembre) et les ETPT du budget (plafond d'emplois voté, en "
    "équivalent temps plein travaillé) mesurent la même population de deux façons : ils sont posés côte à côte, jamais "
    "additionnés.",
    "Les agents des établissements publics administratifs sont comptés par l'Insee dans la fonction publique de "
    "l'État, hors ministères ; leurs emplois relèvent des plafonds des opérateurs (site/data/operateurs), pas des ETPT "
    "des programmes.",
    "Les personnels des cabinets ministériels sont déjà compris dans les effectifs des ministères : ils ne s'y "
    "ajoutent pas.",
    "Les dépenses de conseil sont des dépenses de fonctionnement, distinctes des dépenses de personnel (titre 2) : "
    "elles ne s'ajoutent pas à la masse salariale.",
    "Le titre 2 comprend les cotisations de l'employeur et la contribution au compte d'affectation spéciale Pensions.",
]


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(t.encode("utf-8")) > 5_000_000:
        raise SystemExit(f"{path} dépasse 5 Mo")
    path.write_text(t + "\n", encoding="utf-8")


def fusion_conseils(editions: dict[int, dict]) -> dict:
    """Assemble les éditions du jaune. Un exercice publié par plusieurs éditions : la plus récente fait foi, les
    valeurs des autres éditions sont publiées à côté (écarts jamais tranchés ni additionnés)."""
    totaux: dict[str, dict] = {}
    for plf in sorted(editions):
        for t in editions[plf]["totaux"]:
            cle = str(t["exercice"]) + ("_s1" if t["semestre_1_seul"] else "")
            e = totaux.setdefault(cle, {"exercice": t["exercice"], "semestre_1_seul": t["semestre_1_seul"],
                                        "editions": {}})
            e["editions"][f"PLF {plf}"] = {"ae_eur": t["ae_eur"], "cp_eur": t["cp_eur"]}
    lignes_tot = []
    for cle in sorted(totaux):
        e = totaux[cle]
        derniere = sorted(e["editions"])[-1]
        e.update({"edition_retenue": derniere, **e["editions"][derniere]})
        vals = {(v["ae_eur"], v["cp_eur"]) for v in e["editions"].values() if v["cp_eur"] is not None}
        e["editions_concordantes"] = len({v["ae_eur"] for v in e["editions"].values()}) == 1 and len(vals) <= 1
        lignes_tot.append(e)
    par_min, par_prog, prest = {}, {}, {}
    for plf in sorted(editions):
        ed = editions[plf]
        for an, bloc in (ed.get("ministeres") or {}).items():
            par_min[an] = {"edition": f"PLF {plf}", **bloc}
        pr = ed.get("programmes") or {}
        for p, x in (pr.get("programmes") or {}).items():
            cible = par_prog.setdefault(p, {"programme": p, "libelle": x["libelle"], "exercices": {}})
            cible["libelle"] = x["libelle"]
            for an, v in x["exercices"].items():
                ancien = cible["exercices"].get(an)
                cible["exercices"][an] = {**v, "edition": f"PLF {plf}"}
                if ancien and ancien["ae_consommees_eur"] != v["ae_consommees_eur"]:
                    cible["exercices"][an]["edition_precedente"] = {"edition": ancien["edition"],
                                                                    "ae_consommees_eur": ancien["ae_consommees_eur"]}
        ps = ed.get("prestataires") or {}
        if ps.get("lignes"):
            prest[ps["periode"] or f"PLF {plf}"] = {"edition": f"PLF {plf}", **ps}
    derniere = max(e for e in editions if editions[e].get("missions"))
    controle = {}
    for plf in sorted(editions):
        pr = editions[plf].get("programmes") or {}
        for an in pr.get("annees", []):
            controle[f"PLF {plf}, exercice {an}"] = {"total_publie_ae_eur": pr["total_ae_eur"].get(an),
                                                     "somme_des_programmes_lus_ae_eur": pr["somme_programmes_ae_eur"][an]}
    return {"totaux": lignes_tot, "par_ministere": dict(sorted(par_min.items())),
            "par_mission": {"edition": f"PLF {derniere}", **editions[derniere]["missions"]},
            "par_programme": [dict(par_prog[p], exercices=dict(sorted(par_prog[p]["exercices"].items())))
                              for p in sorted(par_prog)],
            "controle_programmes": controle, "prestataires": dict(sorted(prest.items()))}


def produire(sortie: Path = SORTIE) -> None:
    manquants = [SOURCES[c][0] for c in SOURCES if not chemin(c).exists()]
    if manquants:
        raise SystemExit(f"sources absentes de {LAKE} : {manquants} (python collecte/collecte.py --domaine "
                         "fonction_publique)")
    collecte = date_sources("fonction_publique")

    # Insee : séries
    series = lire_series(feuille(chemin("insee_series"), "Figure 3"))
    annees = [s["annee"] for s in series["series"]]
    derniere = max(annees)
    dump(sortie / "effectifs_series.json", {
        "millesime": f"{min(annees)} à {derniere} (postes principaux au 31 décembre)",
        "source": src("insee_series"), "collecte_le": collecte, "unite": "milliers de personnes",
        "statuts": [{"id": s, "libelle": l} for s, l in STATUTS],
        "valeurs_absentes": "null : « nd » dans la source (donnée non disponible) ; les séries concernées sont listées "
                            "dans `non_disponible`",
        "lecture": "Chaque ligne donne, par statut, une valeur par série, dans l'ordre de `series`. Les années 2020 à "
                   "2023 existent en deux versions : celle publiée à l'époque et celle recalculée par l'Insee "
                   "(`revisee`), comparable à l'année suivante.",
        **series})

    # Insee Première
    noms = feuilles(chemin("insee_ip"))
    titre_ip = propre(feuille(chemin("insee_ip"), "Sommaire")[0][0]) if "Sommaire" in noms else ""
    m = re.search(r"en (20\d\d)", titre_ip)
    annee_ip = int(m.group(1)) if m else derniere
    tableaux = {}
    for n in noms:
        if n == "Sommaire":
            continue
        tableaux[slug(n)] = lire_tableau(feuille(chemin("insee_ip"), n))
    dump(sortie / "emploi.json", {
        "millesime": f"{annee_ip} (Insee Première n° 2094)", "source": src("insee_ip"), "collecte_le": collecte,
        "annee": annee_ip, "publication": re.sub(r"^Données de l'Insee Première no \d+ ", "", titre_ip).strip("« »"),
        "valeurs_absentes": "null : « /// » dans la source (absence de résultat due à la nature des choses), détaillé "
                            "dans `absences` (indice de colonne -> mention)",
        "tableaux": tableaux})

    # Insee : territoires
    dep = lire_territoires(feuille(chemin("insee_tcrd"), "DEP"))
    reg = lire_territoires(feuille(chemin("insee_tcrd"), "REG"))
    agregats = {"P": "metropole_hors_ile_de_france", "M": "metropole", "F": "france_hors_mayotte"}
    dump(sortie / "territoires.json", {
        "millesime": f"31 décembre {dep['annee']}", "source": src("insee_tcrd"), "collecte_le": collecte,
        "annee": dep["annee"], "colonnes": [c for c, _ in COLONNES_TERRITOIRES],
        "champ": next((n for n in dep["notes_source"] if n.startswith("Champ")), None),
        "departements": {c: v for c, v in sorted(dep["lignes"].items()) if c not in agregats},
        "regions": {c: v for c, v in sorted(reg["lignes"].items()) if c not in agregats},
        "ensembles": {agregats[c]: v for c, v in sorted(dep["lignes"].items()) if c in agregats},
        "notes_source": dep["notes_source"]})

    # Cabinets
    cabinets = []
    for cle in ("cabinets_2025", "cabinets_2026"):
        with ouvrir(cle) as pdf:
            c = lire_cabinets([propre_page(p.extract_text() or "") for p in pdf.pages])
        c["edition"] = "PLF " + cle[-4:]
        c["source"] = src(cle)
        cabinets.append(c)
    cabinets.sort(key=lambda c: c["annee"])
    dump(sortie / "cabinets.json", {
        "millesime": " et ".join(f"1er juillet {c['annee']}" for c in cabinets),
        "source": src("cabinets_2025", "cabinets_2026"), "collecte_le": collecte,
        "unite": "effectifs physiques ; dotation annuelle d'indemnité pour sujétions particulières (ISP) en euros",
        "definitions": {
            "membres_cabinet": "membres des cabinets nommés au Journal officiel",
            "fonctions_support": "personnels chargés des fonctions support (protection, sécurité des bâtiments, "
                                 "assistance, intendance, logistique)",
            "dotation_isp_eur": "enveloppe annuelle d'indemnité pour sujétions particulières allouée au pôle, en année "
                                "pleine (décret n° 2001-1148 du 5 décembre 2001)"},
        "regle_personnes": "Agrégats par pôle ministériel uniquement. Les lignes par cabinet du jaune, qui désignent "
                           "un ministre par sa fonction, ne sont pas reprises ; aucun nom.",
        "methode": "Une ligne de pôle est reconnue quand elle égale la somme des lignes de cabinet qui la suivent ; la "
                   "somme des pôles égale le total général publié. `ministeres_budget` : rapprochement du projet avec "
                   "les ministères du budget (nomenclature LFI 2023), à titre de repère.",
        "limites": ["Situation à une date fixe : les effectifs des cabinets varient en cours d'année.",
                    "Les pôles suivent l'architecture du Gouvernement en fonction à la date de situation : ils ne sont "
                    "pas comparables terme à terme d'une année à l'autre.",
                    "Les rémunérations détaillées par cabinet ne figurent pas dans les éditions lues."],
        "situations": cabinets})

    # Conseils
    editions = {2024: lire_conseils("conseils_2024", complet=False), 2025: lire_conseils("conseils_2025"),
                2026: lire_conseils("conseils_2026")}
    conseils = fusion_conseils(editions)
    dump(sortie / "conseils.json", {
        "millesime": "exercices 2021 à 2024 (jaunes PLF 2024 à 2026)",
        "source": src("conseils_2024", "conseils_2025", "conseils_2026"), "collecte_le": collecte,
        "unite": "euros (autorisations d'engagement consommées, sauf mention)",
        "perimetre": "Prestations de conseil extérieur comptabilisées dans le système d'information financière de "
                     "l'État pour huit natures d'achat (communication, audit comptable et financier, stratégie et "
                     "organisation, recrutement, problématiques métiers, étude technique métier, expertise juridique, "
                     "assurance), budget général et comptes spéciaux dotés de crédits ; hors prestations de personnes "
                     "publiques et hors informations couvertes par un secret (défense, sécurité, affaires).",
        "regle_personnes": "Un prestataire n'est nommé que si le jaune publie pour lui un SIREN et une catégorie "
                           "juridique de personne morale ; sinon la ligne reste sans nom, avec son montant. Les listes "
                           "détaillées de prestations ne sont pas reprises.",
        "valeurs_absentes": "null : « / » dans la source (aucune dépense ou aucun crédit publié)",
        "limites": ["Un montant négatif correspond à des annulations de commandes d'exercices antérieurs (précision de "
                    "la source).",
                    "Les ministères sont ceux de la loi de finances de chaque exercice : la nomenclature change d'une "
                    "année à l'autre.",
                    "Prestataires : montants en millions d'euros, arrondis par la source à 0,1 ; l'édition PLF 2025 "
                    "cumule 2022 et 2023, l'édition PLF 2026 porte sur 2024.",
                    "Édition PLF 2024 : seuls les totaux sont repris (le détail porte sur le premier semestre 2023).",
                    "`controle_programmes` compare le total publié et la somme des programmes lus dans le PDF."],
        **conseils})

    # Indemnités des élus
    with ouvrir("dgcl") as pdf:
        bareme = lire_bareme([p.extract_text() or "" for p in pdf.pages])
    dump(sortie / "indemnites_elus.json", {
        "millesime": f"valeur du point d'indice au {bareme['date_valeur']}", "source": src("dgcl"),
        "collecte_le": collecte, "unite": "euros bruts par mois (plafond légal)",
        "definition": "Montant maximal de l'indemnité de fonction, exprimé en pourcentage du traitement correspondant "
                      "à l'indice brut 1027 de la fonction publique ; l'assemblée délibérante fixe le montant versé "
                      "dans cette limite.",
        "regle_personnes": "Barème par fonction et strate de population ; aucun élu, aucun montant versé à une "
                           "personne.",
        "limites": ["Plafonds légaux, pas montants versés : les indemnités votées par chaque collectivité ne sont pas "
                    "dans ce document.",
                    "Collectivités à statut particulier (Corse, Guyane, Martinique, Paris, métropole de Lyon, Grand "
                    "Paris, collectivités d'outre-mer) et majorations (présidents, vice-présidents des départements et "
                    "régions) : publiées en texte par la source, non reprises.",
                    "Une rangée dont le montant ne correspond pas au taux multiplié par la valeur de l'indice est "
                    "écartée et comptée dans `rangees_ecartees`."],
        **bareme})

    # Rapprochement avec le budget de l'État
    effectifs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((SITE / "effectifs").glob("*.json"))}
    rap = rapprocher(ministeres_des_programmes(), effectifs, programmes_de_l_arbre(),
                     {x["programme"]: x for x in conseils["par_programme"]}, conseils["par_ministere"], cabinets,
                     tableaux.get("tableau_complementaire_2"))
    ex = next(iter(effectifs.values()))
    dump(sortie / "ministeres.json", {
        "millesime": f"ETPT : {ex['millesime_etpt']} ; titre 2 : {ex['millesime_titre2']} ; effectifs Insee : fin "
                     f"{annee_ip} ; conseils : exercices {', '.join(sorted(conseils['par_ministere']))}",
        "source": f"site/data/effectifs ({ex['source']}) ; {SRC_ETPT} ; {src('insee_ip', 'conseils_2025', 'conseils_2026')}",
        "collecte_le": collecte,
        "unite": "ETPT (plafond d'emplois voté) ; euros (titre 2, conseils) ; milliers de personnes (Insee)",
        "valeurs_absentes": "null : ETPT ou titre 2 non publié par programme ; conseils : « / » dans la source (aucune "
                            "dépense publiée)",
        "regles": REGLES_SANS_DOUBLE_COMPTE,
        "methode": "Chaque programme est rattaché à son ministère d'après le jeu des ETPT de la LFI 2023 ; ETPT et "
                   "titre 2 sont repris de site/data/effectifs. `groupes_insee` rapproche les groupes de ministères de "
                   "l'Insee des ministères du budget : rapprochement du projet d'après les intitulés, l'Insee ne "
                   "publiant pas de table de passage. `conseils_ae_eur` n'est renseigné que si l'intitulé du ministère "
                   "est le même dans le jaune.",
        "limites": ["Millésimes différents selon la mesure (voir `millesime`) : un ministère réorganisé entre deux "
                    "années n'a pas le même contour.",
                    "Les groupes de l'Insee et les ministères du budget n'ont pas exactement le même contour : "
                    "effectifs et ETPT d'un groupe ne se comparent qu'en ordre de grandeur.",
                    "Programmes sans ETPT publié par programme dans la LFI 2023 : listés dans "
                    "`programmes_sans_ministere`, sans rattachement."],
        "totaux": {"etpt": arrondi(sum(m["etpt"] for m in rap["ministeres"]), 2),
                   "titre2_eur": arrondi(sum(m["titre2_eur"] or 0 for m in rap["ministeres"]), 2),
                   "nb_programmes": sum(m["nb_programmes"] for m in rap["ministeres"]),
                   "titre2_programmes_sans_ministere_eur": arrondi(
                       sum(p["titre2_eur"] or 0 for p in rap["programmes_sans_ministere"]), 2)},
        **rap})

    # Index
    ens = next(l for l in series["lignes"] if l["id"].startswith("ensemble"))
    k_der = max(i for i, s in enumerate(series["series"]) if s["annee"] == derniere)
    versants = {l["id"]: l["valeurs"]["ensemble"][k_der] for l in series["lignes"] if l["niveau"] == "versant"}
    if abs(sum(versants.values()) - ens["valeurs"]["ensemble"][k_der]) > 0.3:
        raise SystemExit("séries Insee : la somme des versants diffère de l'ensemble")
    fig1 = tableaux.get("figure_1")
    ecarts = []
    if fig1:
        col = next((j for j, c in enumerate(fig1["colonnes"]) if c.startswith(str(annee_ip)) and "Y compris" in c), None)
        l1 = next((l for l in fig1["lignes"] if norm(l["libelle"]).startswith("ensemble")
                   and "effectifs" in norm(l["rubrique"] or "")), None)
        if col is not None and l1 is not None and derniere == annee_ip:
            ecarts.append({"grandeur": f"effectif de l'ensemble de la fonction publique fin {annee_ip}, en milliers",
                           "valeurs": [{"source": SOURCES["insee_series"][2], "valeur": ens["valeurs"]["ensemble"][k_der]},
                                       {"source": SOURCES["insee_ip"][2], "valeur": l1["valeurs"][col]}],
                           "note": "Deux publications de l'Insee sur le même champ ; valeurs publiées telles quelles."})
    f_tot = dep["lignes"].get("F")
    if f_tot:
        k23 = [i for i, s in enumerate(series["series"]) if s["annee"] == dep["annee"]]
        ecarts.append({"grandeur": f"effectif de la fonction publique fin {dep['annee']}, en milliers",
                       "valeurs": [{"source": SOURCES["insee_tcrd"][2] + " (hors militaires)", "valeur": f_tot["valeurs"][0]}]
                       + [{"source": SOURCES["insee_series"][2] + (" (série recalculée)" if series["series"][i]["revisee"]
                                                                   else " (série publiée à l'époque)"),
                           "valeur": ens["valeurs"]["ensemble"][i]} for i in k23],
                       "note": "Champs différents : le tableau régional exclut les militaires ; la série nationale les "
                               "inclut."})
    dernier_cab = cabinets[-1]
    tot_cons = [t for t in conseils["totaux"] if not t["semestre_1_seul"]]
    budget_etat = {"etpt": arrondi(sum(m["etpt"] for m in rap["ministeres"]), 2),
                   "millesime_etpt": ex["millesime_etpt"],
                   "titre2_eur": arrondi(sum(m["titre2_eur"] or 0 for m in rap["ministeres"]), 2),
                   "millesime_titre2": ex["millesime_titre2"], "nb_ministeres": len(rap["ministeres"]),
                   "nb_programmes": sum(m["nb_programmes"] for m in rap["ministeres"])}

    # Rémunérations
    rem = remunerations(collecte, budget_etat)
    dump(sortie / "remunerations.json", rem)
    dump(sortie / "index.json", {
        "millesime": f"effectifs {min(annees)} à {derniere} ; cabinets {cabinets[0]['annee']} et {dernier_cab['annee']} ; "
                     f"conseils {tot_cons[0]['exercice']} à {tot_cons[-1]['exercice']} ; barème des élus au "
                     f"{bareme['date_valeur']} ; rémunérations : {rem['millesime']}",
        "source": src(*SOURCES), "collecte_le": collecte,
        "fichiers": [
            {"fichier": "fonction_publique/effectifs_series.json",
             "contenu": "effectifs par versant, statut, ministère et type d'employeur, par année"},
            {"fichier": "fonction_publique/emploi.json", "contenu": "tableaux de l'Insee Première sur l'emploi public"},
            {"fichier": "fonction_publique/territoires.json", "contenu": "effectifs par région et département"},
            {"fichier": "fonction_publique/ministeres.json",
             "contenu": "ministères du budget : programmes, ETPT, titre 2, conseils, repères Insee et cabinets"},
            {"fichier": "fonction_publique/cabinets.json", "contenu": "cabinets ministériels par pôle"},
            {"fichier": "fonction_publique/conseils.json",
             "contenu": "recours aux conseils extérieurs par ministère, mission, programme et prestataire"},
            {"fichier": "fonction_publique/indemnites_elus.json",
             "contenu": "plafonds légaux des indemnités de fonction des élus locaux"},
            {"fichier": "fonction_publique/remunerations.json",
             "contenu": "salaires moyens nets et bruts par versant et catégorie, distributions, évolutions ; "
                        "rémunération des salariés de toutes les administrations publiques sur 100 € de dépense "
                        "publique"}],
        "reperes": {
            "effectifs": {"annee": derniere, "unite": "milliers de personnes au 31 décembre",
                          "ensemble": ens["valeurs"]["ensemble"][k_der], "versants": versants},
            "budget_etat": budget_etat,
            "cabinets": {"annee": dernier_cab["annee"], **dernier_cab["total"], "nb_poles": len(dernier_cab["poles"])},
            "conseils": {"exercice": tot_cons[-1]["exercice"], "ae_eur": tot_cons[-1]["ae_eur"],
                         "cp_eur": tot_cons[-1]["cp_eur"], "edition": tot_cons[-1]["edition_retenue"]},
            "indemnites_elus": {"indice_brut_1027_mensuel_eur": bareme["indice_brut_1027_mensuel_eur"],
                                "nb_rangees": len(bareme["lignes"])},
            "remunerations": reperes_remunerations(rem)},
        "regles": REGLES_SANS_DOUBLE_COMPTE,
        "ecarts_entre_sources": ecarts,
        "regle_personnes": "Aucune personne physique nommée : effectifs et montants agrégés ; prestataires de conseil "
                           "nommés seulement s'ils sont des personnes morales ; barème des élus sans élu.",
        "recherche_prealable": RECHERCHE_PREALABLE,
        "limites": ["Effectifs de l'Insee : France hors Mayotte, postes principaux au 31 décembre ; les niveaux publiés "
                    "avant et après recalcul ne sont pas totalement comparables (note de la source).",
                    "Effectifs par ministère : regroupements de l'Insee, différents des ministères du budget.",
                    "Cabinets et conseils : documents en PDF sans jeu de données structuré ; lecture automatique "
                    "vérifiée par les totaux publiés.",
                    "Indemnités des élus : plafonds légaux, pas montants versés.",
                    "Rémunérations : moyennes et déciles agrégés (Insee 2024, DGAFP 2023) ; la part sur 100 € de "
                    "dépense publique porte sur toutes les administrations publiques (Eurostat et DGAFP, côte à "
                    "côte)."]})
    print(f"fonction_publique : {len(series['lignes'])} lignes Insee, {len(dep['lignes'])} lignes territoriales, "
          f"{len(rap['ministeres'])} ministères, {len(conseils['par_programme'])} programmes (conseils), "
          f"{len(bareme['lignes'])} rangées de barème", file=sys.stderr)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("commande", nargs="?", default="produire", choices=["produire", "remunerations"])
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.commande == "remunerations":
        produire_remunerations(a.sortie)
    else:
        produire(a.sortie)


if __name__ == "__main__":
    main()
