"""Pouvoirs publics : dotations de la mission en série longue, budgets des assemblées et de la Présidence (grandes
masses), barèmes des indemnités par fonction (parlementaires, membres du Gouvernement).

La mission « Pouvoirs publics » regroupe les dotations de la Présidence de la République (501), de l'Assemblée
nationale (511), du Sénat (521), de La Chaîne parlementaire (541 : LCP-AN et Public Sénat), du Conseil
constitutionnel (531), de la Haute Cour (532) et de la Cour de justice de la République (533). En vertu de
l'autonomie financière de ces institutions, la dotation votée leur est intégralement versée : la « dépense
constatée » du budget de l'État est égale aux crédits ouverts (rapport annuel de performances 2025). Les
institutions ont en plus leurs propres budgets (recettes propres, prélèvements sur leurs disponibilités).

Commandes :
    python pipeline/pouvoirs_publics.py collecter   (réseau : python collecte/collecte.py pouvoirs_publics_documents,
                                                     contrôle d'intégrité collecte/integrite.py, refus jamais contournés)
    python pipeline/pouvoirs_publics.py produire [--sortie DOSSIER]   (sans réseau)

Entrées :
  data/lake/pouvoirs_publics/pouvoirs_publics_documents/
      pap2026_pouvoirs_publics.pdf      projet annuel de performances 2026 de la mission (miroir Assemblée nationale)
      rap2025_pouvoirs_publics.pdf      rapport annuel de performances 2025 de la mission (miroir Assemblée nationale)
      an_fiche7_situation_materielle_depute.pdf   Assemblée nationale, fiche n° 7 (barèmes, actualisée en janvier 2026)
      senat_recueil_pouvoirs_publics_traitement_gouvernement.html   Sénat, recueil des textes relatifs aux pouvoirs
                                        publics (décrets n° 2012-983 et n° 2014-425)
      plf2016_bg_msn_dest.csv           PLF 2016, budget général par mission et destination (LFI 2015 et LFI 2016)
  data/lake/etat/ (déjà collecté par d'autres étapes, lu seulement) :
      economie__projet-de-loi-de-finances-pour-2021-plf-2021-.../PLF_2021_credits.csv           (PLF 2021)
      economie__projet-de-loi-de-finances-pour-2022-plf-2022-.../PLF_2022_Credits_Destination_Nature.csv  (PLF 2022)
      etat_budget_vert_2026.parquet     (exécution 2024, LFI 2025, PLF 2026)
  site/data/realisations/<programme>.json (étape realisations, lu seulement) : voté et dépensé 2010 à 2025
  site/data/fonction_publique/indemnites_elus.json (lu seulement, jamais recopié) : barème des élus locaux

Sorties (site/data/pouvoirs_publics/, contrat docs/contrat_interface.md, schémas docs/schemas/pouvoirs_publics_*) :
  index.json, dotations.json, budgets_institutions.json, indemnites.json

Personnes : barèmes par fonction seulement, aucun montant versé à une personne nommée ; les noms cités dans les
documents (magistrats, présidents, questeurs) ne sont jamais lus.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
DOCS = LAKE / "pouvoirs_publics" / "pouvoirs_publics_documents"
SORTIE = ROOT / "site" / "data" / "pouvoirs_publics"
SITE = ROOT / "site" / "data"
ID_COLLECTE = "pouvoirs_publics_documents"

URL_PAP = "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1088014/file/PAP2026_BG_Pouvoirs_publics_PB.pdf"
URL_RAP = "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1109910/file/Pouvoirs_publics_PB.pdf"
URL_FICHE7 = ("https://www.assemblee-nationale.fr/dyn/contenu/telechargement/631144/file/Fiche%207%20corrig%C3%A9e%20-%20"
              "Situation%20mat%C3%A9rielle%20du%20d%C3%A9put%C3%A9_actualis%C3%A9e%20080126.pdf")
URL_SENAT = "https://www.senat.fr/reglement/pouvoirs_publics22.html"
URL_PLF2016 = ("https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/projet-de-loi-de-finances-pour-2016-plf-2016/"
               "attachments/plf2016_bg_msn_dest_csv")
URL_PLF2021 = "https://data.economie.gouv.fr/explore/dataset/projet-de-loi-de-finances-pour-2021-plf-2021-donnees-du-plf-et-des-annexes-proje/"
URL_PLF2022 = "https://data.economie.gouv.fr/explore/dataset/projet-de-loi-de-finances-pour-2022-plf-2022-donnees-du-plf-et-des-annexes-proje/"
URL_BV2026 = "https://data.economie.gouv.fr/explore/dataset/plf-2026-budget-vert/"

DOCUMENTS = {
    "pap2026": ("pap2026_pouvoirs_publics.pdf", "Projet annuel de performances 2026, mission « Pouvoirs publics » "
                "(annexe au projet de loi de finances pour 2026)", URL_PAP),
    "rap2025": ("rap2025_pouvoirs_publics.pdf", "Rapport annuel de performances 2025, mission « Pouvoirs publics » "
                "(annexe au projet de loi relatif aux résultats de la gestion 2025)", URL_RAP),
    "fiche7": ("an_fiche7_situation_materielle_depute.pdf", "Assemblée nationale, fiche n° 7 « La situation "
               "matérielle du député » (actualisée le 8 janvier 2026)", URL_FICHE7),
    "senat": ("senat_recueil_pouvoirs_publics_traitement_gouvernement.html", "Sénat, recueil des textes relatifs aux "
              "pouvoirs publics : décret n° 2012-983 du 23 août 2012 et décret n° 2014-425 du 25 avril 2014", URL_SENAT),
}

PROGRAMMES = [  # (code, libellé, institution)
    ("501", "Présidence de la République", "presidence"),
    ("511", "Assemblée nationale", "assemblee_nationale"),
    ("521", "Sénat", "senat"),
    ("541", "La Chaîne parlementaire", "chaines_parlementaires"),
    ("531", "Conseil constitutionnel", "conseil_constitutionnel"),
    ("532", "Haute Cour", "haute_cour"),
    ("533", "Cour de justice de la République", "cour_de_justice_de_la_republique"),
]
LIBELLES = {c: l for c, l, _ in PROGRAMMES}
INSTITUTIONS = {c: i for c, _, i in PROGRAMMES}
ANNEE_DEBUT, ANNEE_FIN = 2010, 2026
NATURES = {"lfi": "budget voté (loi de finances initiale)", "plf": "projet de loi de finances (avant le vote)",
           "execution": "dépense constatée (exécution)"}

NB = r"[–\-+]?\s?\d{1,3}(?:[   ]\d{3})*(?:,\d+)?"


class LectureImpossible(RuntimeError):
    """Un motif attendu est absent du document : la production s'arrête plutôt que de publier une valeur fausse."""


# --- nombres --------------------------------------------------------------------------------------------------------

def nombre(texte: str | None) -> float | None:
    """« 1 234,5 » -> 1234.5 ; « – 12 » -> -12 ; vide, « N.D. », « nc » -> None (jamais 0)."""
    if texte is None:
        return None
    t = str(texte).strip().replace(" ", " ").replace("\xa0", " ").replace("–", "-").replace("−", "-")
    t = re.sub(r"(?<=[-+])\s+", "", t).replace(" ", "")
    if not re.fullmatch(r"[-+]?\d+(?:,\d+)?", t):
        return None
    return float(t.replace(",", "."))


def euros(texte: str, unite: str) -> float:
    v = nombre(texte)
    if v is None:
        raise LectureImpossible(f"montant illisible : {texte!r}")
    return round(v * {"€": 1, "M€": 1e6, "Md€": 1e9}[unite], 2)


def _jetons_nombres(jetons: list[str]) -> list[list[int]]:
    """Toutes les façons de découper des groupes de chiffres en nombres (1 à 3 chiffres, puis groupes de 3)."""
    if not jetons:
        return [[]]
    sorties = []
    signe = 1
    if jetons[0] in ("–", "-"):
        signe, jetons = -1, jetons[1:]
    if not jetons or not re.fullmatch(r"\d{1,3}", jetons[0]):
        return []
    for k in range(1, len(jetons) + 1):
        tete = jetons[:k]
        if any(not re.fullmatch(r"\d{3}", j) for j in tete[1:]):
            break
        valeur = signe * int("".join(tete))
        for suite in _jetons_nombres(jetons[k:]):
            sorties.append([valeur] + suite)
    return sorties


def trois_montants(jetons: list[str]) -> tuple[int, int, int]:
    """(budget N-1, budget N, écart) dont l'écart publié vérifie N - (N-1) ; découpage unique exigé."""
    sol = [d for d in _jetons_nombres(jetons) if len(d) == 3 and d[1] - d[0] == d[2]]
    if len(sol) != 1:
        raise LectureImpossible(f"découpage ambigu ou impossible : {' '.join(jetons)} ({len(sol)} solutions)")
    return tuple(sol[0])


def deux_egaux(jetons: list[str]) -> int:
    """Autorisations d'engagement et crédits de paiement égaux (cas de toutes les dotations) : « a a »."""
    sol = [d for d in _jetons_nombres(jetons) if len(d) == 2 and d[0] == d[1]]
    if len(sol) != 1:
        raise LectureImpossible(f"AE et CP différents ou illisibles : {' '.join(jetons)}")
    return sol[0][0]


# --- documents ------------------------------------------------------------------------------------------------------

def chemin(cle: str) -> Path:
    return DOCS / DOCUMENTS[cle][0]


_PAGES: dict[str, list[str]] = {}


def pages(cle: str) -> list[str]:
    """Texte de chaque page (pdfplumber), espaces normalisés ligne par ligne."""
    if cle not in _PAGES:
        import pdfplumber
        with pdfplumber.open(chemin(cle)) as pdf:
            _PAGES[cle] = [(p.extract_text() or "").replace(" ", " ").replace("\xa0", " ") for p in pdf.pages]
    return _PAGES[cle]


def chercher(cle: str, motif: str) -> tuple[re.Match, int]:
    """Premier passage correspondant (espaces et sauts de ligne confondus) ; renvoie (correspondance, page)."""
    rx = re.compile(motif)
    trouves = []
    for i, p in enumerate(pages(cle), 1):
        m = rx.search(re.sub(r"\s+", " ", p))
        if m:
            trouves.append((m, i))
    if not trouves:
        raise LectureImpossible(f"{DOCUMENTS[cle][0]} : motif absent : {motif}")
    return trouves[0]


def source_doc(cle: str, page: int | None = None) -> str:
    _, titre, url = DOCUMENTS[cle]
    return f"{titre}{f', page {page}' if page else ''} : {url}"


# --- 1. dotations en série longue -----------------------------------------------------------------------------------

def _lire_csv_latin1(p: Path) -> list[list[str]]:
    texte = p.read_bytes().decode("cp1252")
    return list(csv.reader(io.StringIO(texte), delimiter=";"))


def lire_plf2016() -> dict:
    """PLF 2016 par mission et destination : CP LFI 2015, CP PLF 2016, CP LFI 2016 (somme des actions)."""
    p = DOCS / "plf2016_bg_msn_dest.csv"
    lignes = _lire_csv_latin1(p)
    entete = next(i for i, l in enumerate(lignes) if l[:2] == ["Mission", "Programme"])
    cols = [c.strip() for c in lignes[entete]]
    i_lfi15, i_plf16, i_lfi16 = cols.index("CPLF 2015"), cols.index("CPPLF"), len(cols) - 1 - cols[::-1].index("CPLF")
    out: dict = {}
    for l in lignes[entete + 1:]:
        if len(l) <= i_lfi16 or l[0].strip() != "Pouvoirs publics":
            continue
        prog = l[1].strip()
        for annee, nature, i in ((2015, "lfi", i_lfi15), (2016, "plf", i_plf16), (2016, "lfi", i_lfi16)):
            v = nombre(l[i])
            if v is not None:
                out[(prog, annee, nature)] = out.get((prog, annee, nature), 0) + v
    src = ("data.economie.gouv.fr, projet de loi de finances pour 2016, budget général par mission et destination "
           f"(colonnes CP LFI 2015, CP PLF et CP LFI 2016) : {URL_PLF2016}")
    return {k: (v, src) for k, v in out.items()}


def lire_plf_annee(annee: int) -> dict:
    """PLF 2021 et PLF 2022 (déjà dans data/lake/etat) : crédits de paiement du projet, par programme."""
    base = LAKE / "etat"
    motif = {2021: "economie__projet-de-loi-de-finances-pour-2021-*/PLF_2021_credits.csv",
             2022: "economie__projet-de-loi-de-finances-pour-2022-*/PLF_2022_Credits_Destination_Nature.csv"}[annee]
    fichiers = sorted(base.glob(motif))
    if not fichiers:
        return {}
    brut = fichiers[0].read_bytes()
    try:
        texte = brut.decode("utf-8-sig")
    except UnicodeDecodeError:
        texte = brut.decode("cp1252")
    lignes = list(csv.reader(io.StringIO(texte), delimiter=";"))
    cols = [c.strip().lower() for c in lignes[0]]
    i_mis, i_prog = cols.index("mission"), cols.index("programme")
    i_cp = next(i for i, c in enumerate(cols) if c in ("cp plf", "cp"))
    out: dict = {}
    for l in lignes[1:]:
        if len(l) > i_cp and l[i_mis].strip() == "PB":
            v = nombre(l[i_cp])
            if v is not None:
                out[(l[i_prog].strip(), annee, "plf")] = out.get((l[i_prog].strip(), annee, "plf"), 0) + v
    url = URL_PLF2021 if annee == 2021 else URL_PLF2022
    src = f"data.economie.gouv.fr, données du projet de loi de finances pour {annee} (crédits de paiement, mission PB) : {url}"
    return {k: (v, src) for k, v in out.items()}


def lire_budget_vert_2026() -> dict:
    p = LAKE / "etat" / "etat_budget_vert_2026.parquet"
    if not p.exists():
        return {}
    import pandas as pd
    d = pd.read_parquet(p)
    d = d[(d["mission"] == "Pouvoirs publics") & (d["type_depense"] == "Crédits budgétaires")]
    out: dict = {}
    for _, r in d.iterrows():
        prog = str(int(r["numero_programme"]))
        for col, annee, nature in (("execution_2024_cp", 2024, "execution"),
                                   ("lfi_2025_cp_ou_prevision_2025_si_depense_fiscale", 2025, "lfi"),
                                   ("plf_2026_cp_ou_prevision_2026_si_depense_fiscale", 2026, "plf")):
            v = r[col]
            if v == v and v is not None:
                out[(prog, annee, nature)] = out.get((prog, annee, nature), 0) + float(v)
    src = ("data.economie.gouv.fr, budget vert du PLF 2026 (crédits budgétaires : exécution 2024, LFI 2025, PLF 2026, "
           f"crédits de paiement) : {URL_BV2026}")
    return {k: (v, src) for k, v in out.items()}


def lire_recapitulation_pap() -> dict:
    """PAP 2026, « Récapitulation des crédits par programme et action » : LFI 2025 puis PLF 2026 (CP = AE)."""
    out: dict = {}
    for i, page in enumerate(pages("pap2026"), 1):
        if "RECAPITULATION DES CREDITS PAR PROGRAMME ET ACTION" not in page:
            continue
        lignes = page.splitlines()
        for j, l in enumerate(lignes):
            m = re.match(r"^(5\d\d) – [^\d]+?((?:\d{1,3}(?: \d{3})*\s?)+)$", l.strip())
            if not m or j + 1 >= len(lignes):
                continue
            prog = m.group(1)
            lfi = deux_egaux(m.group(2).split())
            suite = re.sub(r"[+\-–]\d+,\d+ %", " ", lignes[j + 1]).split()
            plf = deux_egaux(suite)
            src = source_doc("pap2026", i) + " (récapitulation des crédits, crédits de paiement)"
            out[(prog, 2025, "lfi")] = (float(lfi), src)
            out[(prog, 2026, "plf")] = (float(plf), src)
        break
    if not out:
        raise LectureImpossible("PAP 2026 : récapitulation des crédits introuvable")
    return out


def lire_realisations() -> dict:
    """Voté (LFI) et dépense constatée de site/data/realisations/<programme>.json (étape realisations)."""
    out: dict = {}
    for prog in LIBELLES:
        p = SITE / "realisations" / f"{prog}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for a in (d.get("prevu_depense") or {}).get("annees", []):
            src = f"site/data/realisations/{prog}.json (étape « realisations ») : {a.get('source')}"
            if a.get("vote_lfi_eur") is not None:
                out[(prog, int(a["annee"]), "lfi")] = (float(a["vote_lfi_eur"]), src)
            if a.get("depense_constatee_eur") is not None:
                out[(prog, int(a["annee"]), "execution")] = (float(a["depense_constatee_eur"]), src)
    return out


def fusionner(*jeux: dict) -> dict:
    """{(programme, année, nature): [(valeur, source), ...]} sans doublon de source."""
    tout: dict = {}
    for jeu in jeux:
        for k, (v, s) in jeu.items():
            tout.setdefault(k, [])
            if all(s != s2 for _, s2 in tout[k]):
                tout[k].append((round(v, 2), s))
    return tout


def construire_dotations(valeurs: dict, millesime: str, collecte_le: str) -> dict:
    ecarts, series = [], []
    annees = list(range(ANNEE_DEBUT, ANNEE_FIN + 1))
    totaux = {a: {n: 0.0 for n in NATURES} for a in annees}
    manquants = {a: {n: [] for n in NATURES} for a in annees}
    for prog, libelle, inst in PROGRAMMES:
        lignes = []
        for a in annees:
            ligne = {"annee": a}
            for nature in NATURES:
                cand = valeurs.get((prog, a, nature), [])
                distincts = sorted({v for v, _ in cand})
                if len(distincts) == 1:
                    ligne[f"{nature}_eur"] = distincts[0]
                    ligne[f"{nature}_sources"] = [s for _, s in cand]
                    totaux[a][nature] += distincts[0]
                else:
                    ligne[f"{nature}_eur"] = None
                    ligne[f"{nature}_sources"] = [s for _, s in cand]
                    manquants[a][nature].append(prog)
                    if len(distincts) > 1:
                        ecarts.append({"programme": prog, "annee": a, "nature": nature,
                                       "valeurs": [{"eur": v, "source": s} for v, s in cand],
                                       "lecture": "Valeurs différentes selon la source : publiées côte à côte, "
                                                  "aucune n'est retenue à la place de l'autre."})
            lignes.append(ligne)
        series.append({"programme": prog, "libelle": libelle, "institution": inst, "annees": lignes})
    mission = []
    for a in annees:
        e = {"annee": a}
        for nature in NATURES:
            # la Haute Cour (532) n'a aucune dotation publiée : son absence ne bloque pas le total
            bloquants = [p for p in manquants[a][nature] if p != "532"]
            e[f"{nature}_eur"] = round(totaux[a][nature], 2) if not bloquants else None
            e[f"{nature}_programmes_manquants"] = bloquants
        mission.append(e)
    return {
        "millesime": millesime, "collecte_le": collecte_le,
        "source": "Lois de finances et documents budgétaires (data.economie.gouv.fr ; projet annuel de performances "
                  f"2026 de la mission : {URL_PAP}) ; voté et dépensé 2010 à 2025 repris de site/data/realisations",
        "unite": "euros (crédits de paiement)",
        "definition": "Dotation de chaque pouvoir public inscrite au budget de l'État. « lfi » : budget voté (loi de "
                      "finances initiale) ; « plf » : projet de loi de finances, avant le vote ; « execution » : dépense "
                      "constatée. La dotation est intégralement versée à l'institution (autonomie financière) : la "
                      "dépense constatée est égale aux crédits ouverts, dotations complémentaires de fin d'année "
                      "comprises (par exemple Assemblée nationale 2024).",
        "natures": NATURES,
        "annees": annees,
        "series": series,
        "mission": mission,
        "ecarts_entre_sources": ecarts,
        "lecture": "Chaque montant porte la liste de ses sources. Une valeur est null quand aucune source collectée ne "
                   "la publie ; le total de la mission est null tant qu'un programme manque (Haute Cour exceptée, "
                   "sans dotation publiée).",
    }


# --- 2. budgets propres des institutions (grandes masses) -----------------------------------------------------------

# (id, document, institution, année, nature, grandeur, motif, unité, précision)
FAITS = [
    ("presidence_2024_depenses", "pap2026", "presidence", 2024, "exécution", "depenses_totales",
     r"rapport au réalisé 2024 \((" + NB + r") M€\)", "M€", "au 100 000 € près"),
    ("presidence_2025_atterrissage", "pap2026", "presidence", 2025, "prévision d'exécution (été 2025)", "depenses_totales",
     r"devraient donc atterrir à (" + NB + r") M€ en 2025", "M€", "au 10 000 € près"),
    ("presidence_2025_budget_initial", "rap2025", "presidence", 2025, "budget initial", "depenses_totales",
     r"Le budget initial 2025 de la présidence s.élevait à (" + NB + r") M€", "M€", "au 100 000 € près"),
    ("presidence_2025_recettes_propres_prevues", "rap2025", "presidence", 2025, "budget initial", "recettes_propres",
     r"dont une dotation de " + NB + r" M€, (" + NB + r") M€ de recettes propres", "M€", "au million d'euros près"),
    ("presidence_2025_depenses", "rap2025", "presidence", 2025, "exécution", "depenses_totales",
     r"les dépenses réalisées s.élèvent au total à (" + NB + r") M€", "M€", "au 10 000 € près"),
    ("presidence_2025_recettes_propres", "rap2025", "presidence", 2025, "exécution", "recettes_propres",
     r"les recettes propres réalisées en 2025, s.élèvent à (" + NB + r") M€", "M€", "au 100 000 € près"),
    ("presidence_2025_recettes_totales", "rap2025", "presidence", 2025, "exécution", "recettes_totales",
     r"l.exécution des recettes : (" + NB + r") M€", "M€", "au 10 000 € près"),
    ("presidence_2025_solde", "rap2025", "presidence", 2025, "exécution", "solde_budgetaire",
     r"excédent budgétaire à hauteur de (" + NB + r") M€ en 2025", "M€", "au 100 000 € près"),
    ("presidence_2026_dotation", "pap2026", "presidence", 2026, "projet de budget", "dotation_etat",
     r"reconduite pour 2026 à hauteur de (" + NB + r") €", "€", "à l'euro"),
    ("an_2023_depenses", "pap2026", "assemblee_nationale", 2023, "exécution", "depenses_totales",
     r"par rapport à l.exécution 2023 \((" + NB + r") M€\)", "M€", "au 100 000 € près"),
    ("an_2024_depenses", "pap2026", "assemblee_nationale", 2024, "exécution", "depenses_totales",
     r"En 2024, les dépenses de l.Assemblée nationale se sont établies à (" + NB + r") M€", "M€", "au 10 000 € près"),
    ("an_2024_fonctionnement", "pap2026", "assemblee_nationale", 2024, "exécution", "depenses_fonctionnement",
     r"Les dépenses de fonctionnement se sont élevées à (" + NB + r") M€ en 2024", "M€", "au 10 000 € près"),
    ("an_2024_investissement", "pap2026", "assemblee_nationale", 2024, "exécution", "depenses_investissement",
     r"passés de " + NB + r" M€ en 2023 à (" + NB + r") M€ en 2024", "M€", "au 10 000 € près"),
    ("an_2024_recettes_propres", "pap2026", "assemblee_nationale", 2024, "exécution", "recettes_propres",
     r"Les recettes budgétaires propres, par nature irrégulières, se sont élevées à (" + NB + r") M€", "M€",
     "au 10 000 € près"),
    ("an_2024_dotation", "rap2025", "assemblee_nationale", 2024, "exécution", "dotation_etat",
     r"le montant total de la dotation versée à l.Assemblée nationale s.est élevé à (" + NB + r") M€", "M€",
     "au 10 000 € près"),
    ("an_2024_solde", "pap2026", "assemblee_nationale", 2024, "exécution", "solde_budgetaire",
     r"conduisant à un solde budgétaire positif de (" + NB + r") €", "€", "à l'euro"),
    ("senat_2023_depenses", "pap2026", "senat", 2023, "exécution", "depenses_totales",
     r"\(" + NB + r" M€ contre (" + NB + r") M€\) ou", "M€", "au 10 000 € près"),
    ("senat_2024_depenses", "pap2026", "senat", 2024, "exécution", "depenses_totales",
     r"baisse de la dépense de " + NB + r" M€ \((" + NB + r") M€ contre", "M€", "au 10 000 € près"),
    ("senat_2024_fonctionnement", "pap2026", "senat", 2024, "exécution", "depenses_fonctionnement",
     r"Les dépenses de fonctionnement se sont élevées à (" + NB + r") M€, en hausse", "M€", "au 10 000 € près"),
    ("senat_2024_investissement", "pap2026", "senat", 2024, "exécution", "depenses_investissement",
     r"pour ne plus s.élever qu.à (" + NB + r") M€", "M€", "au 10 000 € près"),
    ("senat_2024_recettes_propres", "pap2026", "senat", 2024, "exécution", "recettes_propres",
     r"produits budgétaires, qui s.élèvent à (" + NB + r") M€", "M€", "au 10 000 € près"),
    ("senat_2024_solde", "pap2026", "senat", 2024, "exécution", "solde_budgetaire",
     r"\(l.exécution s.est traduite par un excédent de (" + NB + r") M€\)", "M€", "au 10 000 € près"),
    ("senat_2024_budget", "pap2026", "senat", 2024, "budget initial", "depenses_totales",
     r"contre (" + NB + r") M€ en 2024 et " + NB + r" M€ en 2023\)", "M€", "au 10 000 € près"),
    ("senat_2025_budget", "pap2026", "senat", 2025, "budget réparti", "depenses_totales",
     r"Le budget 2025 s.élève à (" + NB + r") M€", "M€", "au 10 000 € près"),
    ("senat_2025_prelevement", "pap2026", "senat", 2025, "budget réparti", "prelevement_disponibilites",
     r"avec (" + NB + r") M€ inscrits en 2025", "M€", "au 10 000 € près"),
    ("senat_2025_recettes_propres", "pap2026", "senat", 2025, "budget réparti", "recettes_propres",
     r"Les produits attendus s.élèvent à (" + NB + r") M€", "M€", "au 10 000 € près"),
    ("senat_2026_depenses", "pap2026", "senat", 2026, "projet de budget", "depenses_totales",
     r"Le budget du Sénat pour 2026 prévoit un total de dépenses de (" + NB + r") €", "€", "à l'euro"),
    ("senat_2026_fonctionnement", "pap2026", "senat", 2026, "projet de budget", "depenses_fonctionnement",
     r"ne parviendrait plus à couvrir les dépenses de fonctionnement \((" + NB + r") M€\)", "M€", "au 10 000 € près"),
    ("senat_2026_investissement", "pap2026", "senat", 2026, "projet de budget", "depenses_investissement",
     r"financerait l.intégralité des dépenses d.investissement \((" + NB + r") M€\)", "M€", "au 10 000 € près"),
    ("senat_2026_dotation", "pap2026", "senat", 2026, "projet de budget", "dotation_etat",
     r"la somme de la dotation \((" + NB + r") M€\)", "M€", "au 10 000 € près"),
    ("senat_2026_recettes_propres", "pap2026", "senat", 2026, "projet de budget", "recettes_propres",
     r"et des produits \((" + NB + r") M€\)", "M€", "au 10 000 € près"),
    ("senat_2026_prelevement", "pap2026", "senat", 2026, "projet de budget", "prelevement_disponibilites",
     r"le prélèvement sur les disponibilités du Sénat \((" + NB + r") M€\)", "M€", "au 10 000 € près"),
    ("lcp_an_2026_dotation", "pap2026", "lcp_an", 2026, "projet de budget", "dotation_etat",
     r"le montant de dotation demandé s.établit à (" + NB + r") euros", "€", "à l'euro"),
    ("public_senat_2026_depenses", "pap2026", "public_senat", 2026, "projet de budget", "depenses_totales",
     r"Le projet de budget total de la chaîne augmente légèrement \(\+1 %\) et s.élève à (" + NB + r") €", "€",
     "à l'euro"),
    ("conseil_constitutionnel_2025_depenses", "rap2025", "conseil_constitutionnel", 2025, "exécution",
     "depenses_totales", r"Les dépenses mandatées se sont élevées (" + NB + r") €", "€", "à l'euro"),
    ("cjr_2025_fonctionnement", "rap2025", "cour_de_justice_de_la_republique", 2025, "exécution",
     "depenses_fonctionnement", r"Les dépenses se sont élevées à la somme de (" + NB + r") €", "€", "à l'euro"),
]

GRANDEURS = {
    "depenses_totales": "dépenses totales", "depenses_fonctionnement": "dépenses de fonctionnement",
    "depenses_investissement": "dépenses d'investissement", "recettes_propres": "recettes propres",
    "recettes_totales": "recettes totales (dotation et recettes propres)", "dotation_etat": "dotation de l'État",
    "prelevement_disponibilites": "prélèvement sur les disponibilités", "solde_budgetaire": "solde budgétaire",
    "charges_parlementaires": "charges parlementaires", "indemnites_parlementaires": "indemnités parlementaires",
    "secretariat_parlementaire": "secrétariat parlementaire (crédit collaborateurs)",
    "charges_personnel": "charges de personnel",
}

INSTITUTIONS_LIBELLES = {
    "presidence": "Présidence de la République", "assemblee_nationale": "Assemblée nationale", "senat": "Sénat",
    "lcp_an": "La Chaîne parlementaire - Assemblée nationale", "public_senat": "Public Sénat",
    "conseil_constitutionnel": "Conseil constitutionnel", "cour_de_justice_de_la_republique":
        "Cour de justice de la République",
}

LIGNES_TABLEAU_AN = [  # (début de ligne dans le tableau de synthèse, grandeur)
    ("A – SECTION DE FONCTIONNEMENT", "depenses_fonctionnement"),
    ("64 Charges de personnel", "charges_personnel"),
    ("65 Charges parlementaires", "charges_parlementaires"),
    ("Dont indemnités parlementaires", "indemnites_parlementaires"),
    ("Dont secrétariat parlementaire", "secretariat_parlementaire"),
    ("B – SECTION D’INVESTISSEMENT", "depenses_investissement"),
    ("C – DÉPENSES BUDGÉTAIRES TOTALES (A+B)", "depenses_totales"),
    ("D – RECETTES BUDGÉTAIRES PROPRES", "recettes_propres"),
    ("E– DOTATION DE L’ÉTAT", "dotation_etat"),
    ("F – SOLDE BUDGÉTAIRE (D+E– C)", "solde_budgetaire"),
]


def _fait(id_, cle, inst, annee, nature, grandeur, valeur, page, extrait, precision, methode="lu dans le texte"):
    return {"id": id_, "institution": inst, "annee": annee, "nature": nature, "grandeur": grandeur,
            "libelle": GRANDEURS[grandeur], "valeur_eur": valeur, "precision": precision, "statut": "tracé",
            "methode": methode, "extrait": extrait[:240], "source": source_doc(cle, page)}


def lire_faits() -> list[dict]:
    faits = []
    for id_, cle, inst, annee, nature, grandeur, motif, unite, precision in FAITS:
        m, page = chercher(cle, motif)
        faits.append(_fait(id_, cle, inst, annee, nature, grandeur, euros(m.group(1), unite), page, m.group(0),
                           precision))
    return faits


def lire_tableau_an() -> list[dict]:
    """Tableau « Budget 2026 de l'Assemblée nationale (synthèse) » : budget révisé 2025 et budget 2026.

    Chaque ligne est découpée de sorte que l'écart publié soit égal à la différence des deux budgets."""
    for i, page in enumerate(pages("pap2026"), 1):
        if "Budget 2026 de l’Assemblée nationale (synthèse)" not in page:
            continue
        faits = []
        lignes = [l.strip() for l in page.splitlines()]
        for debut, grandeur in LIGNES_TABLEAU_AN:
            l = next((x for x in lignes if x.startswith(debut)), None)
            if l is None:
                raise LectureImpossible(f"PAP 2026, tableau de l'Assemblée nationale : ligne absente : {debut}")
            reste = re.sub(r"[–\-+]?\s?\d+,\d+\s?%\s*$", "", l[len(debut):])  # retire la variation en %
            jetons = reste.split()
            b25, b26, _ = trois_montants(jetons)
            for annee, v, nature in ((2025, b25, "budget révisé"), (2026, b26, "projet de budget")):
                faits.append(_fait(f"an_{annee}_{grandeur}", "pap2026", "assemblee_nationale", annee, nature, grandeur,
                                   float(v), i, l, "à l'euro",
                                   "lu dans le tableau de synthèse (écart publié = différence des deux colonnes)"))
        return faits
    raise LectureImpossible("PAP 2026 : tableau de synthèse du budget de l'Assemblée nationale introuvable")


def lire_resultats_an() -> list[dict]:
    """Résultat budgétaire de l'Assemblée nationale, budget initial et exécution 2021 à 2025 (millions d'euros)."""
    m, page = chercher("pap2026", r"Budget initial ((?:[-+]?\d+,\d+ ){5})Exécution ((?:[-+]?\d+,\d+ ){4})N\.D\.")
    initial = [nombre(x) for x in m.group(1).split()]
    execu = [nombre(x) for x in m.group(2).split()]
    out = []
    for k, annee in enumerate(range(2021, 2026)):
        out.append({"annee": annee, "budget_initial_eur": round(initial[k] * 1e6), "execution_eur":
                    round(execu[k] * 1e6) if k < len(execu) else None,
                    "note": "budget rectifié adopté le 17 septembre 2024" if annee == 2024 else None})
    return [{"institution": "assemblee_nationale", "grandeur": "solde_budgetaire", "precision": "au 10 000 € près",
             "annees": out, "source": source_doc("pap2026", page)}]


def controles(faits: list[dict]) -> list[dict]:
    """Identités comptables vérifiées sur les montants lus (écart toléré : la précision publiée)."""
    v = {(f["institution"], f["annee"], f["nature"], f["grandeur"]): f["valeur_eur"] for f in faits}
    regles = [
        ("Assemblée nationale, budget {a} : fonctionnement + investissement = dépenses totales",
         lambda a, n: v[("assemblee_nationale", a, n, "depenses_fonctionnement")]
         + v[("assemblee_nationale", a, n, "depenses_investissement")]
         - v[("assemblee_nationale", a, n, "depenses_totales")], 0.5,
         [(2025, "budget révisé"), (2026, "projet de budget")]),
        ("Assemblée nationale, budget {a} : recettes propres + dotation - dépenses = solde",
         lambda a, n: v[("assemblee_nationale", a, n, "recettes_propres")] + v[("assemblee_nationale", a, n, "dotation_etat")]
         - v[("assemblee_nationale", a, n, "depenses_totales")] - v[("assemblee_nationale", a, n, "solde_budgetaire")],
         0.5, [(2025, "budget révisé"), (2026, "projet de budget")]),
        ("Assemblée nationale, exécution {a} : dotation + recettes propres - dépenses = solde publié",
         lambda a, n: v[("assemblee_nationale", a, n, "dotation_etat")] + v[("assemblee_nationale", a, n, "recettes_propres")]
         - v[("assemblee_nationale", a, n, "depenses_totales")] - v[("assemblee_nationale", a, n, "solde_budgetaire")],
         30_000, [(2024, "exécution")]),
        ("Assemblée nationale, exécution {a} : fonctionnement + investissement = dépenses totales",
         lambda a, n: v[("assemblee_nationale", a, n, "depenses_fonctionnement")]
         + v[("assemblee_nationale", a, n, "depenses_investissement")] - v[("assemblee_nationale", a, n, "depenses_totales")],
         20_000, [(2024, "exécution")]),
        ("Sénat, exécution {a} : fonctionnement + investissement = dépenses totales",
         lambda a, n: v[("senat", a, n, "depenses_fonctionnement")] + v[("senat", a, n, "depenses_investissement")]
         - v[("senat", a, n, "depenses_totales")], 20_000, [(2024, "exécution")]),
        ("Sénat, projet {a} : dotation + produits + prélèvement = dépenses totales",
         lambda a, n: v[("senat", a, n, "dotation_etat")] + v[("senat", a, n, "recettes_propres")]
         + v[("senat", a, n, "prelevement_disponibilites")] - v[("senat", a, n, "depenses_totales")], 20_000,
         [(2026, "projet de budget")]),
        ("Sénat, projet {a} : fonctionnement + investissement = dépenses totales",
         lambda a, n: v[("senat", a, n, "depenses_fonctionnement")] + v[("senat", a, n, "depenses_investissement")]
         - v[("senat", a, n, "depenses_totales")], 20_000, [(2026, "projet de budget")]),
    ]
    out = []
    for libelle, f, tol, cas in regles:
        for annee, nature in cas:
            ecart = round(f(annee, nature), 2)
            ok = abs(ecart) <= tol
            out.append({"controle": libelle.format(a=annee), "ecart_eur": ecart, "tolerance_eur": tol, "ok": ok})
            if not ok:
                raise LectureImpossible(f"contrôle en échec : {libelle.format(a=annee)} (écart {ecart} €)")
    return out


def construire_budgets(millesime: str, collecte_le: str) -> dict:
    faits = lire_faits() + lire_tableau_an()
    ids = [f["id"] for f in faits]
    assert len(ids) == len(set(ids)), "identifiants de faits en double"
    ordre = list(INSTITUTIONS_LIBELLES)
    faits.sort(key=lambda f: (ordre.index(f["institution"]), f["annee"], f["nature"], list(GRANDEURS).index(f["grandeur"])))
    return {
        "millesime": "Exécution 2023 à 2025, budgets 2025 et 2026 selon l'institution",
        "collecte_le": collecte_le,
        "source": f"{DOCUMENTS['pap2026'][1]} : {URL_PAP} ; {DOCUMENTS['rap2025'][1]} : {URL_RAP}",
        "unite": "euros",
        "definition": "Budget propre de chaque institution, distinct de la dotation inscrite au budget de l'État : "
                      "dépenses, recettes propres, dotation de l'État et, selon le cas, prélèvement sur les "
                      "disponibilités (réserves) de l'institution ou solde budgétaire. Les comptes des deux assemblées "
                      "sont certifiés par la Cour des comptes ; les budgets sont arrêtés par une commission commune des "
                      "questeurs des deux assemblées.",
        "institutions": INSTITUTIONS_LIBELLES,
        "grandeurs": GRANDEURS,
        "faits": faits,
        "resultats_budgetaires": lire_resultats_an(),
        "controles": controles(faits),
        "lecture": "Chaque montant est lu dans le document cité (page et extrait), avec la précision publiée (une "
                   "valeur en millions d'euros à deux décimales est arrondie à 10 000 € près). « budget initial », "
                   "« budget révisé », « budget réparti » et « projet de budget » sont des prévisions ; seule "
                   "« exécution » décrit une dépense réalisée. Les périmètres diffèrent d'une institution à l'autre : "
                   "les montants ne s'additionnent pas entre institutions.",
        "limites": [
            "Grandes masses lues dans les documents budgétaires de l'État ; les comptes certifiés détaillés publiés par "
            "chaque assemblée (rapports des questeurs, rapport de la commission spéciale du Sénat) ne sont pas lus.",
            "Budget du Sénat : ensemble Sénat, Jardin et Musée du Luxembourg ; tableaux en image dans le document, "
            "seuls les montants écrits dans le texte sont repris.",
            "Rapport de la Cour des comptes sur les comptes de la Présidence non lu : les montants de la Présidence "
            "viennent du projet et du rapport annuels de performances.",
        ],
    }


# --- 3. barèmes des indemnités par fonction -------------------------------------------------------------------------

def _texte_html(p: Path) -> str:
    t = p.read_text(encoding="utf-8", errors="replace")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def lire_fiche7() -> dict:
    def montant(motif):
        m, page = chercher("fiche7", motif)
        return euros(m.group(1), "€"), page, m.group(0)
    base = {}
    for cle, motif in (("indemnite_de_base", r"indemnité de base : (" + NB + r") €"),
                       ("indemnite_de_residence", r"indemnité de résidence \(3 %\) : (" + NB + r") €"),
                       ("indemnite_de_fonction", r"indemnité de fonction \(25 % du total\) : (" + NB + r") €"),
                       ("brut_mensuel", r"Soit brut mensuel : (" + NB + r") €"),
                       ("net_mensuel", r"Soit un montant net mensuel de (" + NB + r") €")):
        base[cle] = montant(motif)
    m, page = chercher("fiche7", r"Depuis le (1er janvier \d{4}), les indemnités mensuelles brutes")
    date_valeur = m.group(1)
    speciales = []
    for fonction, motif in (
            ("Président de l'Assemblée nationale", r"– Président : (" + NB + r") €"),
            ("Questeur", r"– Questeurs : (" + NB + r") €"),
            ("Vice-président", r"– Vice-présidents : (" + NB + r") €"),
            ("Président de commission, rapporteur général (finances, affaires sociales)",
             r"rapporteurs généraux de la commission des finances et de la commission des affaires sociales : (" + NB + r") €"),
            ("Secrétaire du Bureau", r"– Secrétaires du Bureau : (" + NB + r") €")):
        speciales.append((fonction,) + montant(motif))
    moyens = []
    for libelle, motif in (
            ("Dotation de fonctionnement parlementaire (frais de mandat, député élu en métropole)",
             r"Le montant mensuel de cette dotation est de (" + NB + r") €"),
            ("Crédit affecté à la rémunération des collaborateurs", r"collaborateurs qui s.élève à (" + NB + r") € par mois")):
        moyens.append((libelle,) + montant(motif))
    return {"base": base, "date_valeur": date_valeur, "speciales": speciales, "moyens": moyens}


def lire_decrets_gouvernement() -> dict:
    t = _texte_html(chemin("senat"))
    def trouver(motif):
        m = re.search(motif, t)
        if not m:
            raise LectureImpossible(f"recueil du Sénat : motif absent : {motif}")
        return m
    double = trouver(r"Il est au plus égal au (double) de la moyenne du traitement le plus bas et du traitement le plus élevé")
    ministres = trouver(r"pour les ministres et les ministres délégués, à (\d+,\d+) fois la moyenne")
    majoration = trouver(r"du Président de la République et du Premier ministre sont égaux aux montants les plus élevés "
                         r"définis à l'article 1 er ci-dessus majorés de (\d+) %")
    se = trouver(r"Le traitement brut mensuel des secrétaires d'État est égal à (\d+,\d+) fois la moyenne")
    residence = trouver(r"indemnité de résidence égale à (\d+) % de son montant")
    fonction = trouver(r"indemnité de fonction égale à (\d+) % de la somme du traitement brut et de l'indemnité de résidence")
    assert double.group(1) == "double"
    return {"coef_president_pm": 2.0, "coef_ministre": nombre(ministres.group(1)), "majoration_pct": nombre(majoration.group(1)),
            "coef_secretaire_etat": nombre(se.group(1)), "residence_pct": nombre(residence.group(1)),
            "fonction_pct": nombre(fonction.group(1))}


def bareme_gouvernement(moyenne_he: float, d: dict) -> list[dict]:
    """Traitement, indemnité de résidence et de fonction de chaque fonction, à partir de la moyenne hors échelle."""
    def calcul(coef: float, majoration: float):
        traitement = moyenne_he * coef
        residence = traitement * d["residence_pct"] / 100
        fonction = (traitement + residence) * d["fonction_pct"] / 100
        k = 1 + majoration / 100
        t, r, f = round(traitement * k, 2), round(residence * k, 2), round(fonction * k, 2)
        return t, r, f, round(t + r + f, 2)
    lignes = []
    for fonction, coef, maj, texte in (
            ("Président de la République", d["coef_president_pm"], d["majoration_pct"],
             "décret n° 2012-983, articles 1er et 3 : double de la moyenne hors échelle, majoré de 5 %"),
            ("Premier ministre", d["coef_president_pm"], d["majoration_pct"],
             "décret n° 2012-983, articles 1er et 3 : double de la moyenne hors échelle, majoré de 5 %"),
            ("Ministre et ministre délégué", d["coef_ministre"], 0.0,
             "décret n° 2012-983, article 2 : 1,4 fois la moyenne hors échelle"),
            ("Secrétaire d'État", d["coef_secretaire_etat"], 0.0,
             "décret n° 2014-425, article 2 : 1,33 fois la moyenne hors échelle")):
        t, r, f, total = calcul(coef, maj)
        lignes.append({"fonction": fonction, "coefficient_moyenne_hors_echelle": coef, "majoration_pct": maj,
                       "traitement_brut_mensuel_eur": t, "indemnite_residence_eur": r, "indemnite_fonction_eur": f,
                       "total_brut_mensuel_eur": total, "base_legale": texte, "statut": "approché",
                       "methode": "calculé par le site : moyenne hors échelle x coefficient ; résidence 3 % ; fonction "
                                  "25 % de (traitement + résidence) ; majoration éventuelle sur les trois éléments ; "
                                  "arrondi au centime. Aucun barème chiffré officiel n'a été trouvé en données ouvertes."})
    return lignes


def construire_indemnites(millesime: str, collecte_le: str) -> dict:
    f7 = lire_fiche7()
    d = lire_decrets_gouvernement()
    base = f7["base"]
    moyenne_he = base["indemnite_de_base"][0]
    # contrôle : résidence = 3 % de la base, fonction = 25 % de (base + résidence), brut = somme
    b, r, fo, brut = (base[k][0] for k in ("indemnite_de_base", "indemnite_de_residence", "indemnite_de_fonction",
                                            "brut_mensuel"))
    for libelle, ecart in (("résidence = 3 % de la base", r - round(b * 0.03, 2)),
                           ("fonction = 25 % de (base + résidence)", fo - round((b + r) * 0.25, 2)),
                           ("brut = base + résidence + fonction", brut - (b + r + fo))):
        if abs(ecart) > 0.02:
            raise LectureImpossible(f"fiche n° 7 : contrôle « {libelle} » en échec ({ecart:.2f} €)")
    src7 = lambda p: source_doc("fiche7", p)  # noqa: E731
    parlementaires = [
        {"fonction": "Député", "element": e, "montant_brut_mensuel_eur": base[k][0], "statut": "tracé",
         "base_legale": "ordonnance n° 58-1210 du 13 décembre 1958 portant loi organique relative à l'indemnité des "
                        "membres du Parlement", "source": src7(base[k][1])}
        for k, e in (("indemnite_de_base", "indemnité parlementaire de base"),
                     ("indemnite_de_residence", "indemnité de résidence (3 %)"),
                     ("indemnite_de_fonction", "indemnité de fonction (25 %)"),
                     ("brut_mensuel", "total brut mensuel"))]
    parlementaires.append({"fonction": "Député", "element": "total net mensuel (après cotisations, CSG et CRDS)",
                           "montant_brut_mensuel_eur": None, "montant_net_mensuel_eur": base["net_mensuel"][0],
                           "statut": "tracé", "base_legale": None, "source": src7(base["net_mensuel"][1])})
    parlementaires.append({
        "fonction": "Sénateur", "element": "total brut mensuel (indemnités de base, de résidence et de fonction)",
        "montant_brut_mensuel_eur": brut, "statut": "approché",
        "base_legale": "ordonnance n° 58-1210 du 13 décembre 1958 (même texte pour les deux assemblées)",
        "methode": "montant de l'Assemblée nationale repris : l'ordonnance fixe la même indemnité pour tous les membres "
                   "du Parlement ; le Sénat ne publie pas de barème chiffré dans les documents collectés.",
        "source": f"{src7(base['brut_mensuel'][1])} ; {source_doc('pap2026')}"})
    speciales = [{"fonction": fct, "assemblee": "Assemblée nationale", "montant_brut_mensuel_eur": v,
                  "statut": "tracé", "source": src7(p)} for fct, v, p, _ in f7["speciales"]]
    moyens = [{"libelle": lib, "montant_mensuel_eur": v, "statut": "tracé", "source": src7(p)}
              for lib, v, p, _ in f7["moyens"]]
    elus = SITE / "fonction_publique" / "indemnites_elus.json"
    renvoi = None
    if elus.exists():
        e = json.loads(elus.read_text(encoding="utf-8"))
        renvoi = {"fichier": "fonction_publique/indemnites_elus.json", "millesime": e.get("millesime"),
                  "nombre_de_lignes": len(e.get("lignes", [])), "unite": e.get("unite"),
                  "lecture": "Barème légal des élus locaux (maires, adjoints, conseillers, présidents) publié par "
                             "l'axe fonction publique : non recopié ici."}
    return {
        "millesime": f"barèmes en vigueur depuis le {f7['date_valeur']} (valeur du point d'indice inchangée), fiche "
                     "actualisée le 8 janvier 2026",
        "collecte_le": collecte_le,
        "source": f"{source_doc('fiche7')} ; {source_doc('senat')}",
        "unite": "euros par mois",
        "regle_personnes": "Barèmes par fonction : aucun montant versé à une personne nommée, aucun nom lu.",
        "definition": "Indemnité des membres du Parlement : indemnité de base égale à la moyenne du traitement le plus "
                      "bas et du plus élevé des fonctionnaires « hors échelle », indemnité de résidence de 3 % et "
                      "indemnité de fonction de 25 %. Traitement du Président de la République et des membres du "
                      "Gouvernement : multiple de cette même moyenne fixé par décret.",
        "moyenne_hors_echelle_mensuelle_eur": moyenne_he,
        "parlementaires": parlementaires,
        "indemnites_speciales": speciales,
        "moyens_du_mandat": moyens,
        "moyens_du_mandat_lecture": "Moyens versés pour exercer le mandat (frais, rémunération des collaborateurs) : "
                                    "ce ne sont pas des revenus personnels, ils ne s'ajoutent pas à l'indemnité.",
        "gouvernement": bareme_gouvernement(moyenne_he, d),
        "coefficients_decrets": d,
        "elus_locaux": renvoi,
        "limites": [
            "Indemnités spéciales du Sénat (président, questeurs, etc.) non publiées dans les documents collectés.",
            "Membres du Gouvernement : barème calculé à partir des décrets, pas lu dans un tableau officiel ; un "
            "montant peut différer de quelques centimes d'un bulletin réel (arrondis).",
            "Montants bruts avant impôt sur le revenu ; seul le net du député est publié par la source.",
        ],
    }


# --- index ----------------------------------------------------------------------------------------------------------

RECHERCHE_PREALABLE = [
    {"trouvaille": "site/data/realisations/<programme>.json (dépôt, étape realisations) : voté et dépensé 2010-2025",
     "classement": "réutilisable tel quel", "licence": "Licence Ouverte 2.0 (données) ; code du dépôt",
     "dernier_commit": "dépôt courant", "usage": "base de la série longue, jamais recalculée"},
    {"trouvaille": "site/data/fonction_publique/indemnites_elus.json (dépôt) : barème des élus locaux",
     "classement": "réutilisable tel quel", "licence": "document administratif public", "dernier_commit": "dépôt courant",
     "usage": "renvoi dans indemnites.json, sans recopie"},
    {"trouvaille": "data.economie.gouv.fr, jeux PLF et LFI (2016, 2021, 2022, budget vert 2026)",
     "classement": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "dernier_commit": "jeux publiés de 2016 à 2025",
     "usage": "compléments de la série (LFI 2015 et 2016, PLF 2021, 2022 et 2026)"},
    {"trouvaille": "Projet et rapport annuels de performances « Pouvoirs publics » (PDF, budget.gouv.fr, miroir AN)",
     "classement": "à adapter", "licence": "documents administratifs publics", "dernier_commit": "PAP octobre 2025, RAP 2026",
     "usage": "grandes masses des budgets des institutions, lues par motifs et contrôlées"},
    {"trouvaille": "Assemblée nationale, fiche n° 7 « situation matérielle du député »", "classement": "à adapter",
     "licence": "document administratif public", "dernier_commit": "actualisée le 8 janvier 2026",
     "usage": "barème des indemnités parlementaires et indemnités spéciales"},
    {"trouvaille": "Sénat, recueil des textes relatifs aux pouvoirs publics (décrets 2012-983 et 2014-425)",
     "classement": "à adapter", "licence": "document administratif public", "dernier_commit": "page en ligne en 2026",
     "usage": "coefficients du traitement des membres du Gouvernement"},
    {"trouvaille": "data.assemblee-nationale.fr et data.senat.fr (données ouvertes des assemblées)",
     "classement": "inspiration seulement", "licence": "Licence Ouverte", "dernier_commit": "mises à jour continues",
     "usage": "aucun jeu de comptes ou de barèmes trouvé ; activité parlementaire seulement"},
    {"trouvaille": "Regards citoyens (NosDéputés.fr, dépôts GitHub regardscitoyens)", "classement": "inspiration seulement",
     "licence": "AGPL (code), ODbL (données)", "dernier_commit": "activité réduite depuis 2023",
     "usage": "données nominatives sur les parlementaires : hors périmètre (aucune personne nommée)"},
]


def construire_index(dot: dict, bud: dict, ind: dict, collecte_le: str) -> dict:
    derniere_lfi = max(m["annee"] for m in dot["mission"] if m["lfi_eur"] is not None)
    plf = next((m for m in dot["mission"] if m["annee"] == ANNEE_FIN and m["plf_eur"] is not None), None)
    m_lfi = next(m for m in dot["mission"] if m["annee"] == derniere_lfi)
    pres = next(g for g in ind["gouvernement"] if g["fonction"] == "Président de la République")
    dep = next(p for p in ind["parlementaires"] if p["fonction"] == "Député" and p["element"] == "total brut mensuel")
    return {
        "millesime": f"dotations {ANNEE_DEBUT} à {ANNEE_FIN} ; budgets des institutions 2023 à 2026 ; barèmes 2026",
        "collecte_le": collecte_le,
        "source": f"{DOCUMENTS['pap2026'][1]} : {URL_PAP} ; data.economie.gouv.fr (lois de finances) ; "
                  f"{DOCUMENTS['fiche7'][1]} : {URL_FICHE7} ; {DOCUMENTS['senat'][1]} : {URL_SENAT}",
        "presentation": "Ce que reçoivent la Présidence de la République, l'Assemblée nationale, le Sénat, les chaînes "
                        "parlementaires, le Conseil constitutionnel et la Cour de justice de la République sur le budget "
                        "de l'État, comment chacun l'emploie (grandes masses de son budget) et les barèmes des "
                        "indemnités par fonction. Aucun montant versé à une personne nommée.",
        "fichiers": [
            {"fichier": "pouvoirs_publics/dotations.json", "contenu": "dotations par programme et par année "
             f"({ANNEE_DEBUT} à {ANNEE_FIN}) : budget voté, projet, dépense constatée, total de la mission"},
            {"fichier": "pouvoirs_publics/budgets_institutions.json", "contenu": "budgets propres des institutions "
             "(dépenses, recettes propres, dotation, prélèvements sur réserves, solde), lus et contrôlés"},
            {"fichier": "pouvoirs_publics/indemnites.json", "contenu": "barèmes mensuels par fonction : parlementaires, "
             "indemnités spéciales, moyens du mandat, membres du Gouvernement ; renvoi au barème des élus locaux"},
        ],
        "reperes": {
            "mission_lfi": {"annee": derniere_lfi, "eur": m_lfi["lfi_eur"], "statut": "tracé"},
            "mission_plf": {"annee": ANNEE_FIN, "eur": plf["plf_eur"] if plf else None, "statut": "tracé"},
            "depute_brut_mensuel_eur": dep["montant_brut_mensuel_eur"],
            "president_brut_mensuel_eur": pres["total_brut_mensuel_eur"],
            "president_statut": pres["statut"],
        },
        "regles": [
            "La dotation inscrite au budget de l'État et le budget propre d'une institution sont deux grandeurs "
            "différentes : jamais additionnées (la dotation est une ressource du budget propre).",
            "Montants par programme et par institution ; aucun classement entre institutions.",
            "Valeur absente : null, jamais 0.",
        ],
        "ecarts_entre_sources": dot["ecarts_entre_sources"],
        "regle_personnes": ind["regle_personnes"],
        "recherche_prealable": RECHERCHE_PREALABLE,
        "limites": [
            "Série des dotations, années sans valeur dans les jeux collectés (null) : budget voté "
            + ", ".join(str(m["annee"]) for m in dot["mission"] if m["lfi_eur"] is None and m["annee"] < ANNEE_FIN)
            + " ; dépense constatée "
            + ", ".join(str(m["annee"]) for m in dot["mission"] if m["execution_eur"] is None and m["annee"] < ANNEE_FIN)
            + ".",
            "Haute Cour (programme 532) : aucune dotation publiée.",
            "Budgets propres : grandes masses des documents budgétaires de l'État ; comptes certifiés détaillés des "
            "assemblées et rapport de la Cour des comptes sur la Présidence non lus.",
        ] + ind["limites"],
    }


# --- commandes ------------------------------------------------------------------------------------------------------

def ecrire(dossier: Path, nom: str, donnees: dict) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(donnees, ensure_ascii=False, indent=1) + "\n"
    if len(texte.encode("utf-8")) > 5_000_000:
        raise SystemExit(f"{nom} dépasse 5 Mo")
    (dossier / nom).write_text(texte, encoding="utf-8")


def produire(sortie: Path = SORTIE) -> dict:
    manquants = [DOCUMENTS[k][0] for k in DOCUMENTS if not chemin(k).exists()]
    if manquants or not (DOCS / "plf2016_bg_msn_dest.csv").exists():
        raise SystemExit(f"entrées absentes ({manquants}) : lancer `python pipeline/pouvoirs_publics.py collecter`")
    collecte_le = date_sources("pouvoirs_publics")
    valeurs = fusionner(lire_realisations(), lire_plf2016(), lire_plf_annee(2021), lire_plf_annee(2022),
                        lire_budget_vert_2026(), lire_recapitulation_pap())
    dot = construire_dotations(valeurs, f"lois de finances {ANNEE_DEBUT} à {ANNEE_FIN}", collecte_le)
    bud = construire_budgets("", collecte_le)
    ind = construire_indemnites("", collecte_le)
    idx = construire_index(dot, bud, ind, collecte_le)
    for nom, d in (("index.json", idx), ("dotations.json", dot), ("budgets_institutions.json", bud),
                   ("indemnites.json", ind)):
        ecrire(sortie, nom, d)
    return idx


def collecter() -> int:
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), ID_COLLECTE], cwd=ROOT)


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
    print(json.dumps(idx["reperes"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
