"""Énergie et climat : charges de service public de l'énergie, boucliers tarifaires, chèque énergie.

Agrégats publiés seulement. Trois familles de sources, jamais additionnées entre elles :
  - Commission de régulation de l'énergie (CRE), délibérations annuelles d'évaluation des charges de service public
    de l'énergie (juillet 2024, 2025, 2026) : tableau récapitulatif des charges par action (charges constatées des
    deux années passées, mise à jour de la prévision de l'année en cours, prévision de l'année suivante), en M€ ;
  - Direction du budget, budget vert des PLF 2024, 2025 et 2026 (data.economie.gouv.fr) : crédits budgétaires des
    programmes 345 « Service public de l'énergie » et 174 « Énergie, climat et après-mines » par action et par ligne
    de dépense (exécution 2022 à 2024, LFI 2023 à 2025, PLF 2024 à 2026), en euros ;
  - aucune source ouverte trouvée pour le chèque énergie par département : publié null, avec la liste des sources
    examinées (`sources_inaccessibles`).

Les montants par action du programme 345 dans le budget de l'État (exécution 2024, LFI 2025, PLF 2025) sont déjà
publiés par `arbre/` et `programmes/` : cette vue y renvoie par des liens (fichier + identifiant). Le budget vert n'est
utilisé ici que pour ses colonnes de montants (exécution, LFI, PLF) ; les cotations environnementales ne sont pas
reprises. Les dépenses fiscales rattachées au programme 174 restent dans `niches/`.

Entrées : data/lake/energie_climat/ (non versionné), collectées par `collecter` :
    energie_climat_cre_cspe_<2024|2025|2026>.pdf       délibérations de la CRE (n° 2024-139, 2025-180, 2026-149)
    energie_climat_budget_vert_plf<2024|2025|2026>.json export filtré (programmes 174 et 345) du budget vert
Sorties (site/data/energie_climat/, contrat docs/contrat_interface.md 2.52) :
    index.json, charges_service_public.json, boucliers.json, budget.json, cheque_energie.json

Commandes :
    python pipeline/energie_climat.py collecter   # réseau ; un refus 401/403/429 est noté, jamais contourné
    python pipeline/energie_climat.py produire    # sans réseau (pdftotext de poppler-utils pour lire les PDF)
    python pipeline/energie_climat.py             # les deux

Règles :
  - un tableau de la CRE n'est retenu que si ses sous-totaux et son total se recalculent à 0,15 M€ près ;
  - une même année évaluée par plusieurs délibérations garde chaque évaluation, côte à côte (révisions visibles) ;
  - charges de la CRE et crédits budgétaires ne mesurent pas la même chose (charges au titre d'une année contre
    crédits payés dans l'année) : ils sont présentés côte à côte, l'écart est calculé, jamais tranché ;
  - une valeur absente à la source est null, jamais 0 ; aucune date du jour n'est écrite (dates des délibérations).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRUT = ROOT / "data" / "lake" / "energie_climat"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "energie_climat"

LO = "Licence Ouverte 2.0"
CRE = "https://www.cre.fr"
ECO = "https://data.economie.gouv.fr"
PAGE_CSPE = f"{CRE}/electricite/soutien-a-la-production/charges-de-services-public-de-lenergie.html"

# --- Sources -----------------------------------------------------------------------------------------------------------

DELIBERATIONS = {
    2024: {"numero": "2024-139", "date": "2024-07-11",
           "url": f"{CRE}/fileadmin/Documents/Deliberations/2024/240711_2024-139_CSPE_2024-2025.pdf",
           "page": f"{CRE}/documents/deliberations/evaluation-des-charges-de-service-public-de-lenergie-pour-2025-et-a-"
                   "la-reevaluation-des-charges-de-service-public-de-lenergie-pour-2024.html",
           "note": "la colonne 2022 reprend les charges constatées établies par la délibération n° 2023-200 du 13 "
                   "juillet 2023, hors reliquats au titre de 2022 (renvoi (1) du tableau de la délibération)"},
    2025: {"numero": "2025-180", "date": "2025-07-10",
           "url": f"{CRE}/fileadmin/Documents/Deliberations/2025/250710_2025-180_CSPE_2025-2026.pdf",
           "page": f"{CRE}/documents/deliberations/evaluation-des-charges-de-service-public-de-lenergie-a-compenser-en-"
                   "2026-et-a-la-reevaluation-des-charges-de-service-public-de-lenergie-a-compenser-en-2025.html",
           "note": None},
    2026: {"numero": "2026-149", "date": "2026-07-15",
           "url": f"{CRE}/fileadmin/Documents/Deliberations/2026/260715_2026-149_CSPE_2026-2027.pdf",
           "page": f"{CRE}/documents/deliberations/evaluation-des-charges-de-service-public-de-lenergie-a-compenser-en-"
                   "2027-et-a-la-reevaluation-des-charges-de-service-public-de-lenergie-a-compenser-en-2026.html",
           "note": "selon la délibération, les charges au titre de 2024 reposent sur des prix de marché plus élevés que "
                   "ceux des années suivantes, du fait des volumes vendus à terme pendant la crise des prix de l'énergie"},
}

BUDGET_VERT = {  # PLF -> jeu Opendatasoft (budget vert : crédits budgétaires par action et par ligne de dépense)
    2024: "budgetvert_plf2024_opendata_vf",
    2025: "plf25-budget-vert",
    2026: "plf-2026-budget-vert",
}
FILTRE_PROGRAMMES = "numero_programme=174 or numero_programme=345"


def url_budget_vert(jeu: str) -> str:
    from urllib.parse import quote
    return f"{ECO}/api/explore/v2.1/catalog/datasets/{jeu}/exports/json?where={quote(FILTRE_PROGRAMMES)}"


SOURCES = {
    **{f"cre_cspe_{a}": {
        "entrepot": f"energie_climat_cre_cspe_{a}.pdf", "url": d["url"], "page": d["page"],
        "titre": f"Commission de régulation de l'énergie, délibération n° {d['numero']} du {d['date']} relative à "
                 f"l'évaluation des charges de service public de l'énergie à compenser en {a + 1} et à leur "
                 f"réévaluation pour {a} : tableau récapitulatif des charges par action ({a - 2} à {a + 1})",
        "producteur": "Commission de régulation de l'énergie (CRE)", "millesime": f"délibération du {d['date']}",
        "licence": "document administratif public (réutilisation libre, article L. 321-1 du code des relations entre "
                   "le public et l'administration)",
        "verdict": "à adapter : tableau lu dans le PDF (pdftotext), contrôlé par recalcul des sous-totaux et du total",
    } for a, d in DELIBERATIONS.items()},
    **{f"budget_vert_plf{a}": {
        "entrepot": f"energie_climat_budget_vert_plf{a}.json", "url": url_budget_vert(jeu),
        "page": f"{ECO}/explore/dataset/{jeu}/",
        "titre": f"Direction du budget, budget vert du PLF {a} (rapport sur l'impact environnemental du budget) : "
                 f"lignes des programmes 174 et 345, colonnes exécution {a - 2}, LFI {a - 1} et PLF {a} en crédits de "
                 "paiement",
        "producteur": "Direction du budget", "millesime": f"PLF {a}", "licence": LO,
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft filtré sur deux programmes)",
    } for a, jeu in BUDGET_VERT.items()},
}

INACCESSIBLES = [
    {"source": "Chèque énergie par département (nombre de chèques émis, montants, taux d'utilisation)",
     "motif": "aucun jeu ouvert trouvé sur data.gouv.fr, data.economie.gouv.fr ni le portail de la DREES ; les "
              "répartitions départementales ne sont publiées que sous forme de cartes dans des documents PDF "
              "(tableau de bord de l'Observatoire national de la précarité énergétique, fiche « Le chèque énergie » "
              "du panorama « Minima sociaux et prestations sociales » de la DREES) ou de pages régionales des DREAL",
     "examine": ["https://www.data.gouv.fr/datasets/le-cheque-energie",
                 "https://www.precarite-energie.org/wp-content/uploads/2026/06/"
                 "onpe-tableau-de-bord-de-la-precarite-energetique-2025-v2.pdf"]},
    {"source": "DREES, données associées au panorama « Minima sociaux et prestations sociales » (fiche chèque "
               "énergie)",
     "motif": "site drees.solidarites-sante.gouv.fr inaccessible depuis l'environnement de collecte (robots.txt "
              "interdit la lecture automatique ; connexion refusée) : aucun contournement",
     "examine": ["https://drees.solidarites-sante.gouv.fr/publications-communique-de-presse/panoramas-de-la-drees/"
                 "251204-minima-sociaux-et-prestations-de-solidarite"]},
    {"source": "Nombre de chèques énergie émis et utilisés par année",
     "motif": "publié par la direction générale de l'énergie et du climat dans des documents (graphiques des "
              "rapports de l'ONPE, fiches de la DREES), pas en données ouvertes",
     "examine": []},
]

RECHERCHE_PUBLIQUE = [
    {"nom": "CRE, « Charges de service public de l'énergie par opérateur » (data.gouv.fr)",
     "url": "https://www.data.gouv.fr/datasets/charges-de-service-public-de-lenergie-par-operateur/",
     "licence": "non précisée", "dernier_depot": "2024-03-14",
     "verdict": "inspiration : un seul millésime (délibération de juillet 2018, charges pour 2019), détail par opérateur"},
    {"nom": "Cour des comptes, « Le chèque énergie » (données du rapport de 2022)",
     "url": "https://www.data.gouv.fr/datasets/le-cheque-energie", "licence": "ODbL", "dernier_depot": "2022-05-25",
     "verdict": "inspiration : tableaux nationaux par tranche de revenu, aucune donnée par département"},
    {"nom": "Direction du budget, budget vert des PLF 2024 à 2026 (data.economie.gouv.fr)",
     "url": f"{ECO}/explore/dataset/plf-2026-budget-vert/", "licence": LO, "dernier_depot": "2025-11-13",
     "verdict": "réutilisable tel quel (montants par ligne de dépense ; déjà lu par `realisations/` pour l'exécution "
                "2022 par programme, et par `arbre/` pour l'exécution 2024 par action)"},
    {"nom": "Dépôts publics sur GitHub (recherche « charges de service public energie CRE », « cheque energie », "
            "« bouclier tarifaire »)",
     "url": "https://github.com/search?q=cheque+energie&type=repositories", "licence": None, "dernier_depot": None,
     "verdict": "aucun dépôt réutilisable : un seul résultat, sans rapport avec les montants (dates d'envoi)"},
]

# --- Nomenclature du tableau récapitulatif de la CRE (ordre des lignes du tableau) ----------------------------------

# (clé, libellé, parent, action du programme 345)
LIGNES_CRE = [
    ("eolien_terrestre", "Éolien terrestre", "enr_electriques", "345-09"),
    ("eolien_mer", "Éolien en mer", "enr_electriques", "345-09"),
    ("photovoltaique", "Photovoltaïque", "enr_electriques", "345-09"),
    ("bioenergies", "Bio-énergies", "enr_electriques", "345-09"),
    ("autres_energies", "Autres énergies", "enr_electriques", "345-09"),
    ("enr_electriques", "Soutien aux énergies renouvelables électriques en métropole continentale", None, "345-09"),
    ("biomethane", "Injection de biométhane", None, "345-10"),
    ("zni_transition", "Zones non interconnectées : transition énergétique", "zni", "345-11"),
    ("zni_solidarite", "Zones non interconnectées : mécanismes de solidarité (péréquation tarifaire)", "zni", "345-11"),
    ("zni", "Soutien dans les zones non interconnectées au réseau métropolitain", None, "345-11"),
    ("cogeneration", "Cogénération au gaz naturel et autres moyens thermiques", None, "345-12"),
    ("effacement", "Effacements de consommation", None, "345-13"),
    ("fsl", "Compensation des versements au fonds de solidarité pour le logement", "dispositifs_sociaux", "345-14"),
    ("afficheur", "Afficheur déporté de la consommation", "dispositifs_sociaux", "345-14"),
    ("autres_sociaux", "Autres dispositifs sociaux", "dispositifs_sociaux", "345-14"),
    ("dispositifs_sociaux", "Dispositifs sociaux", None, "345-14"),
    ("frais_gestion", "Frais de gestion", None, "345-15"),
    ("sous_total_hors_mesures", "Sous-total hors boucliers tarifaires et amortisseurs", None, None),
    ("mesures_electricite", "Mesures exceptionnelles : consommateurs d'électricité (boucliers tarifaires, "
                            "amortisseurs)", "mesures_exceptionnelles", "345-17"),
    ("mesures_gaz", "Mesures exceptionnelles : consommateurs de gaz (boucliers tarifaires)",
     "mesures_exceptionnelles", "345-17"),
    ("mesures_exceptionnelles", "Mesures exceptionnelles de protection des consommateurs", None, "345-17"),
    ("total", "Total des charges de service public de l'énergie", None, None),
]
CLES_CRE = [c for c, *_ in LIGNES_CRE]
SOUS_TOTAUX = {"enr_electriques": ["eolien_terrestre", "eolien_mer", "photovoltaique", "bioenergies", "autres_energies"],
               "zni": ["zni_transition", "zni_solidarite"],
               "dispositifs_sociaux": ["fsl", "afficheur", "autres_sociaux"],
               "mesures_exceptionnelles": ["mesures_electricite", "mesures_gaz"]}
HORS_MESURES = ["enr_electriques", "biomethane", "zni", "cogeneration", "effacement", "dispositifs_sociaux",
                "frais_gestion"]
TOLERANCE_M_EUR = 0.15
NATURES = ["constatees", "constatees", "prevision_mise_a_jour", "previsionnelles"]
LIBELLES_NATURES = {
    "constatees": "charges constatées au titre de l'année",
    "prevision_mise_a_jour": "mise à jour de la prévision au titre de l'année",
    "previsionnelles": "charges prévisionnelles au titre de l'année",
}

NOMBRE = re.compile(r"(?<![\d,])-?\d{1,3}(?: \d{3})*,\d(?![\d,])|(?<![\d,])-?\d{4,},\d(?![\d,])")
TITRE_TABLEAU = re.compile(r"capitulatif des charges par action au titre des ann[ée]es (\d{4}) [àa] (\d{4})")


def _nombre(texte: str) -> float:
    return float(texte.replace(" ", "").replace(",", "."))


def lire_tableau_cre(texte: str) -> dict:
    """Tableau récapitulatif des charges par action d'une délibération (texte de pdftotext -layout).

    Renvoie {"annees": [a, a+1, a+2, a+3], "lignes": {clé: [4 valeurs en M€]}}. Les lignes sont reconnues par leur
    ordre (nomenclature fixe du programme 345) ; le tableau finit sur deux lignes « total » consécutives (mesures
    exceptionnelles, puis total général) ; le sous-total hors mesures exceptionnelles n'existe qu'à partir de
    2025 et est recalculé sinon. Lève ValueError si la forme ou un total ne se recalcule pas."""
    lignes = texte.replace(" ", " ").replace(" ", " ").splitlines()
    debut = [i for i, l in enumerate(lignes) if TITRE_TABLEAU.search(l)]
    if not debut:
        raise ValueError("tableau récapitulatif des charges par action introuvable")
    i0 = debut[-1]
    a, b = (int(x) for x in TITRE_TABLEAU.search(lignes[i0]).groups())
    if b - a != 3:
        raise ValueError(f"années inattendues : {a} à {b}")
    rangs: list[tuple[str, list[float]]] = []
    for l in lignes[i0 + 1:i0 + 90]:
        nums = NOMBRE.findall(l)
        if len(nums) != 4:
            continue
        libelle = l[:l.find(nums[0])].strip()
        rangs.append((libelle, [_nombre(n) for n in nums]))
        # fin du tableau : total général, juste après le total des mesures exceptionnelles
        if len(rangs) >= 2 and all(re.fullmatch(r"(?i)total", x) for x, _ in rangs[-2:]):
            break
    if len(rangs) == len(CLES_CRE):
        cles = CLES_CRE
    elif len(rangs) == len(CLES_CRE) - 1:
        cles = [c for c in CLES_CRE if c != "sous_total_hors_mesures"]
    else:
        raise ValueError(f"{len(rangs)} lignes chiffrées lues, {len(CLES_CRE) - 1} ou {len(CLES_CRE)} attendues")
    out = dict(zip(cles, (v for _, v in rangs)))
    if not re.fullmatch(r"(?i)total", rangs[-1][0]):
        raise ValueError("dernière ligne lue autre que le total")
    calcule = "sous_total_hors_mesures" not in out
    if calcule:
        out["sous_total_hors_mesures"] = [round(sum(out[k][j] for k in HORS_MESURES), 1) for j in range(4)]
    for tot, parts in [*SOUS_TOTAUX.items(), ("sous_total_hors_mesures", HORS_MESURES),
                       ("total", ["sous_total_hors_mesures", "mesures_exceptionnelles"])]:
        for j in range(4):
            if abs(sum(out[k][j] for k in parts) - out[tot][j]) > TOLERANCE_M_EUR + 0.05 * (len(parts) - 1):
                raise ValueError(f"{tot} {a + j} : {out[tot][j]} ne se recalcule pas ({parts})")
    return {"annees": list(range(a, b + 1)), "lignes": out, "sous_total_recalcule": calcule}


def texte_pdf(chemin: Path) -> str:
    if not shutil.which("pdftotext"):
        raise SystemExit("pdftotext (poppler-utils) requis pour lire les délibérations de la CRE")
    return subprocess.run(["pdftotext", "-layout", str(chemin), "-"], capture_output=True, text=True,
                          check=True).stdout


# --- Budget vert ----------------------------------------------------------------------------------------------------

def _colonne(ligne: dict, prefixe: str) -> tuple[int, str] | None:
    for k in ligne:
        m = re.fullmatch(rf"{prefixe}_(\d{{4}})_cp(?:_.*)?", k)
        if m:
            return int(m.group(1)), k
    return None


def _eur(v) -> float | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def lire_budget_vert(plf: int, lignes: list[dict]) -> list[dict]:
    """Lignes de crédits budgétaires des programmes 174 et 345 : une entrée par ligne de dépense, trois colonnes."""
    out = []
    for r in lignes:
        if r.get("type_depense") != "Crédits budgétaires":
            continue
        prog = r.get("numero_programme")
        if prog is None or int(float(prog)) not in (174, 345):
            continue
        cols = {nature: _colonne(r, prefixe) for nature, prefixe in
                (("execution", "execution"), ("lfi", "lfi"), ("plf", "plf"))}
        if any(c is None for c in cols.values()):
            raise ValueError(f"PLF {plf} : colonnes exécution, LFI ou PLF introuvables")
        action = r.get("code_action") or r.get("code_action_si_credit_budgetaire")
        code = r.get("code_depense")
        retraitement = not re.fullmatch(r"\d{3}-\d{2}", str(action or ""))
        out.append({
            "source_plf": plf, "programme": str(int(float(prog))), "action": action, "code": code,
            "action_libelle": r.get("action_si_credit_budgetaire"), "libelle": r.get("libelle"),
            "retraitement": retraitement,
            **{nature: {"annee": an, "eur": _eur(r.get(k))} for nature, (an, k) in cols.items()},
        })
    out.sort(key=lambda x: (x["programme"], x["retraitement"], str(x["action"]), str(x["code"]), str(x["libelle"])))
    return out


def est_cheque_energie(ligne: dict) -> bool:
    return bool(re.search(r"ch[eè]que[s]? [ée]nergie", str(ligne.get("libelle") or ""), re.I))


def est_mesure_exceptionnelle(ligne: dict) -> bool:
    return str(ligne.get("action") or "") == "345-17"


def est_carburant(ligne: dict) -> bool:
    """Remise sur les carburants (2022) : portée par l'action 345-17 mais hors des charges évaluées par la CRE."""
    return bool(re.search(r"carburant", str(ligne.get("libelle") or ""), re.I))


# --- Liens vers les autres vues ---------------------------------------------------------------------------------------

def _arbre(programme: str) -> str | None:
    for p in sorted((SITE / "arbre").glob(f"*_{programme}.json")):
        return p.relative_to(SITE).as_posix()
    return None


def liens() -> list[dict]:
    out = []
    for prog, nom in (("345", "Service public de l'énergie"), ("174", "Énergie, climat et après-mines")):
        f = _arbre(prog)
        if f:
            doc = json.loads((SITE / f).read_text(encoding="utf-8"))
            out.append({"vue": "arbre_etat", "fichier": f, "id": doc.get("id"), "programme": prog, "nom": nom,
                        "lecture": f"programme {prog} par action dans le budget de l'État ({doc.get('millesime')}) : "
                                   "même argent que les lignes de `budget.json`, non additionné"})
        for vue, rel, lecture in (
                ("programmes", f"programmes/{prog}.json", "répartition par nature et par action (PLF 2025)"),
                ("realisations", f"realisations/{prog}.json", "prévu et dépensé par année, indicateurs de performance"),
                ("tracabilite", f"tracabilite/programme_{prog}.json", "bénéficiaires identifiés ou non")):
            if (SITE / rel).exists():
                out.append({"vue": vue, "fichier": rel, "id": prog, "programme": prog, "nom": nom, "lecture": lecture})
    return out


# --- Production -------------------------------------------------------------------------------------------------------

AVERTISSEMENT = ("Montants publiés par la Commission de régulation de l'énergie (charges au titre d'une année) et par la "
                 "direction du budget (crédits payés dans l'année) : deux mesures différentes, présentées côte à côte, "
                 "jamais additionnées.")


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def _ecart(a: float | None, b: float | None) -> dict | None:
    if a is None or b is None:
        return None
    d = round(a - b, 1)
    return {"ecart_m_eur": d, "ecart_pct": round(d / b * 100, 1) if b else None}


def charger_cre() -> dict[int, dict]:
    tableaux = {}
    for annee in sorted(DELIBERATIONS):
        f = BRUT / SOURCES[f"cre_cspe_{annee}"]["entrepot"]
        if not f.exists():
            raise SystemExit(f"{f.relative_to(ROOT)} absent : lancer `python pipeline/energie_climat.py collecter`")
        tableaux[annee] = lire_tableau_cre(texte_pdf(f))
    return tableaux


def charger_budget() -> list[dict]:
    lignes = []
    for plf in sorted(BUDGET_VERT):
        f = BRUT / SOURCES[f"budget_vert_plf{plf}"]["entrepot"]
        if not f.exists():
            raise SystemExit(f"{f.relative_to(ROOT)} absent : lancer `python pipeline/energie_climat.py collecter`")
        lignes += lire_budget_vert(plf, json.loads(f.read_text(encoding="utf-8")))
    return lignes


def produire() -> dict:
    tableaux = charger_cre()
    budget = charger_budget()
    delibs = sorted(tableaux)
    annees_cre = sorted({a for t in tableaux.values() for a in t["annees"]})

    # --- charges de service public : chaque délibération, puis chaque année avec toutes ses évaluations ---
    evaluations = []
    for d in delibs:
        t = tableaux[d]
        meta = DELIBERATIONS[d]
        evaluations.append({
            "deliberation": meta["numero"], "date": meta["date"], "source": f"cre_cspe_{d}",
            "colonnes": [{"annee": an, "nature": NATURES[j]} for j, an in enumerate(t["annees"])],
            "sous_total_recalcule": t["sous_total_recalcule"], "note": meta["note"],
            "lignes": {k: t["lignes"][k] for k in CLES_CRE},
        })
    series = {}
    for an in annees_cre:
        par_ligne = {}
        for k in CLES_CRE:
            vals = []
            for d in delibs:
                t = tableaux[d]
                if an in t["annees"]:
                    j = t["annees"].index(an)
                    vals.append({"deliberation": DELIBERATIONS[d]["numero"], "date": DELIBERATIONS[d]["date"],
                                 "nature": NATURES[j], "m_eur": t["lignes"][k][j]})
            par_ligne[k] = vals
        derniere = par_ligne["total"][-1]
        series[str(an)] = {"derniere_evaluation": {"deliberation": derniere["deliberation"],
                                                   "nature": derniere["nature"]},
                           "lignes": par_ligne}
    doc_charges = {
        "millesime": f"délibérations de la CRE de juillet {delibs[0]} à juillet {delibs[-1]}",
        "source": " ; ".join(f"CRE, délibération n° {DELIBERATIONS[d]['numero']} du {DELIBERATIONS[d]['date']}"
                             for d in delibs) + f" ({PAGE_CSPE})",
        "unite": "millions d'euros (M€), tels que publiés (une décimale)",
        "avertissement": AVERTISSEMENT,
        "annees": annees_cre,
        "nomenclature": [{"cle": c, "libelle": lib, "parent": par, "action_programme_345": act}
                         for c, lib, par, act in LIGNES_CRE],
        "natures": LIBELLES_NATURES,
        "definitions": {
            "charges_service_public": "surcoûts supportés par les opérateurs (producteur historique, entreprises locales de "
                                      "distribution, fournisseurs, acheteurs de biométhane) au titre des missions de "
                                      "service public fixées par le code de l'énergie (article L. 121-6 et suivants) "
                                      "et compensés par l'État ; évalués chaque année par la CRE",
            "valeur_negative": "une charge négative signifie que les installations soutenues ont reversé davantage "
                               "qu'elles n'ont reçu, quand les prix de marché dépassent le tarif d'achat ou le prix "
                               "de référence du contrat (cas de 2022 et 2023 pour l'éolien selon la CRE)",
            "zni_solidarite": "mécanismes de solidarité avec les zones non interconnectées (Corse, outre-mer, îles) : "
                              "compensation de l'écart entre le coût de production local et le tarif réglementé "
                              "identique à celui de la métropole (péréquation tarifaire)",
        },
        "evaluations": evaluations,
        "series": series,
        "regle": "tableau retenu seulement si ses sous-totaux et son total se recalculent à 0,15 M€ près (plus 0,05 M€ "
                 "par terme d'arrondi) ; une année évaluée par plusieurs délibérations garde chaque évaluation, sans "
                 "choisir ; aucune somme entre années ni entre délibérations",
    }

    # --- budget : lignes des programmes 345 et 174 ---
    annees_budget = sorted({l[n]["annee"] for l in budget for n in ("execution", "lfi", "plf")})
    doc_budget = {
        "millesime": f"budget vert des PLF {min(BUDGET_VERT)} à {max(BUDGET_VERT)} (exécution "
                     f"{min(BUDGET_VERT) - 2} à {max(BUDGET_VERT) - 2})",
        "source": " ; ".join(f"data.economie.gouv.fr/{jeu} (PLF {a})" for a, jeu in sorted(BUDGET_VERT.items())),
        "unite": "euros (crédits de paiement)",
        "avertissement": "Colonnes de montants du budget vert seulement (cotations environnementales non reprises). "
                         "Chaque PLF présente ses montants au périmètre de ce PLF : une même année n'apparaît qu'une "
                         "fois par nature (exécution, LFI ou PLF).",
        "annees": annees_budget,
        "programmes": {"345": "Service public de l'énergie", "174": "Énergie, climat et après-mines"},
        "lignes": budget,
        "totaux": totaux_budget(budget),
        "note_perimetre": "lignes « Crédits budgétaires » des programmes 174 et 345 ; lignes de retraitement publiées "
                          "par la direction du budget (mesures de périmètre ou de transfert « MP/MT », fonds de "
                          "concours « FDC/ADP ») gardées à part (`retraitement` vrai) et comptées dans `avec_"
                          "retraitements_eur` seulement ; dépenses fiscales rattachées au programme 174 publiées par la "
                          "vue des dépenses fiscales, non reprises",
    }

    # --- boucliers : CRE (charges au titre de l'année) et budget (action 345-17, crédits de l'année) ---
    bouclier_budget = {}
    for l in budget:
        if est_mesure_exceptionnelle(l):
            for n in ("execution", "lfi", "plf"):
                c = l[n]
                if c["eur"] is not None:
                    e = bouclier_budget.setdefault((c["annee"], n), {
                        "annee": c["annee"], "nature": n, "source_plf": l["source_plf"], "lignes": [],
                        "total_eur": 0.0, "hors_carburants_eur": 0.0})
                    carburant = est_carburant(l)
                    e["lignes"].append({"code": l["code"], "libelle": l["libelle"], "eur": c["eur"],
                                        "champ_cre": not carburant})
                    e["total_eur"] = round(e["total_eur"] + c["eur"], 2)
                    if not carburant:
                        e["hors_carburants_eur"] = round(e["hors_carburants_eur"] + c["eur"], 2)
    cre_mesures = {an: series[str(an)]["lignes"] for an in annees_cre}
    comparaison = []
    for an in sorted({a for a, n in bouclier_budget if n == "execution"} | set(annees_cre)):
        cre = [v for v in (cre_mesures.get(an) or {}).get("mesures_exceptionnelles", [])]
        dern = cre[-1] if cre else None
        exe = bouclier_budget.get((an, "execution"))
        m_exe = round(exe["hors_carburants_eur"] / 1e6, 1) if exe else None
        e = _ecart(dern["m_eur"] if dern else None, m_exe)
        comparaison.append({
            "annee": an,
            "cre_m_eur": dern["m_eur"] if dern else None,
            "cre_deliberation": dern["deliberation"] if dern else None,
            "cre_nature": dern["nature"] if dern else None,
            "budget_execution_m_eur": m_exe,
            "budget_source_plf": exe["source_plf"] if exe else None,
            **(e or {"ecart_m_eur": None, "ecart_pct": None}),
        })
    doc_boucliers = {
        "millesime": f"délibérations de la CRE de juillet {delibs[0]} à juillet {delibs[-1]} ; budget vert des PLF "
                     f"{min(BUDGET_VERT)} à {max(BUDGET_VERT)}",
        "source": doc_charges["source"] + " ; " + doc_budget["source"],
        "unite": "millions d'euros (CRE) ; euros (budget)",
        "avertissement": AVERTISSEMENT,
        "perimetre": "boucliers tarifaires et amortisseurs compensés aux fournisseurs d'électricité et de gaz comme "
                     "charges de service public de l'énergie (lois de finances pour 2022 à 2024) ; la baisse de "
                     "l'accise sur l'électricité décidée en 2022 est une moindre recette fiscale, pas une charge de "
                     "service public : elle n'est pas comptée ici",
        "cre": {str(an): {"electricite": cre_mesures[an]["mesures_electricite"],
                          "gaz": cre_mesures[an]["mesures_gaz"],
                          "total": cre_mesures[an]["mesures_exceptionnelles"]} for an in annees_cre},
        "budget_action_345_17": [bouclier_budget[k] for k in sorted(bouclier_budget, key=lambda x: (x[0], x[1]))],
        "comparaison": comparaison,
        "note": "comparaison sur les lignes électricité et gaz de l'action 345-17 (`hors_carburants_eur`) ; la "
                "remise sur les carburants de 2022, portée par la même action, n'est pas une charge de service public "
                "de l'énergie (`champ_cre` faux) ; pour 2024 le budget vert ne publie que le total de l'action",
        "lecture_ecart": "la CRE évalue les pertes des fournisseurs au titre d'une année ; le budget paie les "
                         "compensations dans l'année où elles sont versées, y compris des acomptes et des reliquats "
                         "d'années antérieures : l'écart reflète ce décalage, il n'est pas une erreur de l'une ou "
                         "l'autre source",
    }

    # --- chèque énergie : budget national par année, départements non publiés ---
    cheque = [l for l in budget if est_cheque_energie(l)]
    par_annee = {}
    for l in cheque:
        for n in ("execution", "lfi", "plf"):
            c = l[n]
            par_annee.setdefault(str(c["annee"]), []).append({"nature": n, "source_plf": l["source_plf"], "code": l["code"],
                                                              "libelle": l["libelle"], "eur": c["eur"]})
    doc_cheque = {
        "millesime": doc_budget["millesime"],
        "source": doc_budget["source"],
        "unite": "euros (crédits de paiement du programme 174)",
        "national": {an: par_annee[an] for an in sorted(par_annee)},
        "departements": None,
        "departements_mention": "non publié en données ouvertes : aucun jeu par département (nombre de chèques, "
                                "montants) trouvé ; voir `sources_inaccessibles`",
        "nombre_cheques": None,
        "nombre_cheques_mention": "non publié en données ouvertes par la direction générale de l'énergie et du climat",
        "sources_inaccessibles": INACCESSIBLES,
        "note": "le chèque énergie est financé par le programme 174 depuis la suppression du compte d'affectation "
                "spéciale Transition énergétique ; il ne fait pas partie des charges de service public de l'énergie "
                "évaluées par la CRE (les dispositifs sociaux de la CRE sont la compensation des versements au fonds "
                "de solidarité pour le logement, l'afficheur déporté et d'autres dispositifs)",
    }

    fichiers = {"charges_service_public": "energie_climat/charges_service_public.json",
                "boucliers": "energie_climat/boucliers.json", "budget": "energie_climat/budget.json",
                "cheque_energie": "energie_climat/cheque_energie.json"}
    dernier = DELIBERATIONS[delibs[-1]]
    t_dernier = tableaux[delibs[-1]]
    index = {
        "millesime": f"délibérations de la CRE {delibs[0]} à {delibs[-1]} ; budget vert des PLF {min(BUDGET_VERT)} à "
                     f"{max(BUDGET_VERT)}",
        "source": "Commission de régulation de l'énergie (cre.fr) ; direction du budget (data.economie.gouv.fr)",
        "avertissement": AVERTISSEMENT,
        "fichiers": fichiers,
        "chiffres_cles": [
            {"id": f"charges_{an}", "annee": an, "m_eur": t_dernier["lignes"]["total"][j],
             "nature": NATURES[j], "deliberation": dernier["numero"],
             "libelle": f"Charges de service public de l'énergie, {LIBELLES_NATURES[NATURES[j]]} {an}"}
            for j, an in enumerate(t_dernier["annees"])],
        "liens": liens(),
        "cas_transition_energetique": {
            "applicable": False,
            "lecture": "le compte d'affectation spéciale Transition énergétique (programmes 764 et 765) a été supprimé "
                       "au 1er janvier 2021 par la loi de finances pour 2021 ; les charges de service public de "
                       "l'énergie sont depuis portées par le programme 345 du budget général. Son exécution 2016-2020 "
                       "n'est pas reprise ici.",
        },
        "regle": "agrégats publiés seulement ; aucun opérateur ni fournisseur nommé ; une valeur absente à la source est "
                 "null, jamais 0 ; les évaluations successives de la CRE et les crédits budgétaires sont présentés "
                 "côte à côte, jamais additionnés",
        "limites": [
            "délibérations de juillet 2024 à juillet 2026 lues : charges constatées de 2022 à 2025, prévisions "
            "jusqu'à 2027 ; les délibérations antérieures (tableaux d'une autre forme) ne sont pas lues",
            "boucliers tarifaires de 2021 (gaz) : compris par la CRE dans les reliquats, sans colonne propre dans les "
            "tableaux lus",
            "chèque énergie : montants nationaux du budget seulement ; ni département, ni nombre de chèques en "
            "données ouvertes",
            "budget vert : chaque PLF présente ses montants au périmètre de ce PLF (lignes de retraitement publiées à "
            "part)",
        ],
        "sources": {k: v for k, v in sorted(SOURCES.items())},
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(SORTIE / "charges_service_public.json", doc_charges)
    dump(SORTIE / "budget.json", doc_budget)
    dump(SORTIE / "boucliers.json", doc_boucliers)
    dump(SORTIE / "cheque_energie.json", doc_cheque)
    dump(SORTIE / "index.json", index)
    print(f"energie_climat : {len(delibs)} délibérations ({annees_cre[0]}-{annees_cre[-1]}), {len(budget)} lignes "
          f"budgétaires, {len(cheque)} ligne(s) chèque énergie")
    return index


def totaux_budget(budget: list[dict]) -> list[dict]:
    """Par programme, année et nature : somme des lignes hors retraitement, et avec retraitements."""
    acc = {}
    for l in budget:
        for n in ("execution", "lfi", "plf"):
            c = l[n]
            e = acc.setdefault((l["programme"], c["annee"], n), {"programme": l["programme"], "annee": c["annee"],
                                                                 "nature": n, "source_plf": l["source_plf"],
                                                                 "hors_retraitements_eur": 0.0,
                                                                 "avec_retraitements_eur": 0.0, "lignes_null": 0})
            if c["eur"] is None:
                e["lignes_null"] += 1
                continue
            e["avec_retraitements_eur"] = round(e["avec_retraitements_eur"] + c["eur"], 2)
            if not l["retraitement"]:
                e["hors_retraitements_eur"] = round(e["hors_retraitements_eur"] + c["eur"], 2)
    return [acc[k] for k in sorted(acc)]


# --- Collecte ---------------------------------------------------------------------------------------------------------

def telecharger(url: str, dest: Path, essais: int = 5) -> str:
    import requests
    derniere = ""
    for i in range(essais):
        try:
            r = requests.get(url, timeout=(20, 300), headers={"User-Agent": "ou-vont-mes-impots/pipeline"})
            if r.status_code in (401, 403, 429, 451):
                return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
            r.raise_for_status()
            debut = r.content[:5]
            if (dest.suffix == ".pdf" and debut != b"%PDF-") or (dest.suffix == ".json" and debut[:1] != b"["):
                return "contenu inattendu (page HTML au lieu du fichier) : aucun contournement"
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(r.content)
            import fetch  # contrôle d'intégrité (collecte/integrite.py) avant le renommage atomique
            fetch.remplacer_si_valide(tmp, dest, nom=dest.name, octets_attendus=fetch.octets_annonces(r))
            return "ok"
        except Exception as e:  # reprise réseau
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(5 * (i + 1))
    return f"échec après {essais} essais : {derniere}"


def collecter(forcer: bool = False) -> dict:
    etat = {}
    BRUT.mkdir(parents=True, exist_ok=True)
    for cle, s in sorted(SOURCES.items()):
        dest = BRUT / s["entrepot"]
        if dest.exists() and dest.stat().st_size > 0 and not forcer:
            etat[cle] = "présent"
        else:
            etat[cle] = telecharger(s["url"], dest)
        print(f"{cle}: {etat[cle]}")
    return etat


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true", help="retélécharger les sources déjà présentes")
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter(a.forcer)
    if a.etape in ("produire", "tout"):
        produire()


if __name__ == "__main__":
    main()
