"""La France et ses voisins : dépenses publiques par fonction (COFOG) et prélèvements obligatoires dans l'UE.

Donne du contexte sans juger : mêmes séries pour la France, l'UE à 27, la zone euro et les 27 pays, en % du PIB,
en euros par habitant et en part du total, de 2000 à la dernière année publiée par Eurostat. Aucun qualificatif
de niveau : un rang, une médiane, un écart en points, une évolution, et les avertissements de comparabilité
publiés par Eurostat (cités mot pour mot, vérifiés dans les documents collectés à chaque production).

Commandes :
    python collecte/collecte.py eu_comparaison_cofog_pib eu_comparaison_cofog_part eu_comparaison_cofog_meur \
        eu_comparaison_taxag eu_comparaison_population eu_comparaison_pib eu_comparaison_documents
        (réseau, collecteur du dépôt : un refus 401/403 n'est jamais contourné ; sources déclarées dans
        collecte/catalogue.json, tracées dans data/lake/manifest.json)
    python pipeline/europe_comparaison.py produire [--sortie DOSSIER]   (sans réseau)

Sorties (site/data/comparaison/, contrat docs/contrat_interface.md, schémas docs/schemas/comparaison_*.json) :
    index.json, depenses/<TOTAL|GF01..GF10>.json, prelevements.json, fiches.json

Sorties reproductibles : aucune heure de passage ; dates = mise à jour publiée par Eurostat et date de collecte
(pipeline/reproductible.py) ; ordres explicites.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402
from transform import jsonstat_records  # noqa: E402  (décodeur JSON-stat déjà présent dans le dépôt)

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "europe"
SORTIE = ROOT / "site" / "data" / "comparaison"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

PAYS = ["AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE", "IT", "LT", "LU",
        "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"]
AGREGATS = ["EU27_2020", "EA20"]
ANNEE_DEBUT = 2000
MIN_PAYS = 25  # une année n'est retenue comme « dernière année » que si au moins 25 des 27 pays l'ont publiée

SOURCES = {
    "cofog_pib": ("eu_comparaison_cofog_pib", "gov_10a_exp", "PC_GDP"),
    "cofog_part": ("eu_comparaison_cofog_part", "gov_10a_exp", "PC_TOT"),
    "cofog_meur": ("eu_comparaison_cofog_meur", "gov_10a_exp", "MIO_EUR"),
    "taxag": ("eu_comparaison_taxag", "gov_10a_taxag", "PC_GDP, MIO_EUR"),
    "population": ("eu_comparaison_population", "nama_10_pe", "THS_PER"),
    "pib": ("eu_comparaison_pib", "nama_10_gdp", "CP_MEUR"),
}
DOCS = LAKE / "eu_comparaison_documents"

TOTAL_PO = "D2_D5_D91_D61_M_D611V_D612_M_M_D613V_D614_M_D995"
PRELEVEMENTS = [  # (code, libellé, signe dans l'identité du total, parent)
    (TOTAL_PO, "Impôts et cotisations sociales obligatoires (total)", None, None),
    ("D2", "Impôts sur la production et les importations", 1, None),
    ("D211", "dont taxes du type TVA", None, "D2"),
    ("D5", "Impôts courants sur le revenu et le patrimoine", 1, None),
    ("D51A_C1", "dont impôts sur le revenu des ménages", None, "D5"),
    ("D51B_C2", "dont impôts sur le revenu des sociétés", None, "D5"),
    ("D91", "Impôts en capital", 1, None),
    ("D611C", "Cotisations sociales obligatoires à la charge des employeurs", 1, None),
    ("D613C", "Cotisations sociales obligatoires à la charge des ménages", 1, None),
    ("D995", "Montants dus non recouvrables (déduits)", -1, None),
]

# Grands postes du site -> codes COFOG (somme des codes si plusieurs) ; « voir_aussi » : codes voisins publiés à part.
FICHES = [
    ("sante", "Santé", ["GF07"], [], ["perimetres", "provisoire", "ruptures"]),
    ("retraites", "Retraites (vieillesse)", ["GF1002"], ["GF1003"],
     ["perimetres", "niveau_2", "provisoire", "ruptures", "prestations_brutes", "prestations_nettes_ue",
      "systemes_retraite", "vieillesse_pensions"]),
    ("education", "Éducation", ["GF09"], [], ["perimetres", "provisoire", "ruptures"]),
    ("defense", "Défense", ["GF02"], [], ["perimetres", "provisoire", "ruptures", "defense_otan", "defense_otan_raisons"]),
    ("ordre_public", "Ordre et sécurité publics", ["GF03"], [],
     ["perimetres", "provisoire", "ruptures", "defense_otan_raisons"]),
    ("transports", "Transports", ["GF0405"], [], ["perimetres", "niveau_2", "provisoire", "ruptures"]),
    ("logement", "Logement", ["GF0601", "GF1006"], [],
     ["perimetres", "niveau_2", "provisoire", "ruptures", "logement_social", "prestations_brutes", "prestations_nettes_ue"]),
    ("environnement", "Protection de l'environnement", ["GF05"], [], ["perimetres", "provisoire", "ruptures"]),
    ("interets_dette", "Intérêts de la dette (opérations concernant la dette publique)", ["GF0107"], [],
     ["perimetres", "niveau_2", "provisoire", "ruptures", "dette_interets"]),
]

# Avertissements de comparabilité publiés par Eurostat : citation exacte retrouvée dans le document collecté.
AVERTISSEMENTS = [
    ("perimetres", "périmètres", "gov_10a_exp_esms.htm",
     "https://ec.europa.eu/eurostat/cache/metadata/en/gov_10a_exp_esms.htm",
     "Eurostat indique que les comparaisons entre pays doivent tenir compte des différences de composition du secteur "
     "des administrations publiques et d'organisation institutionnelle d'un pays à l'autre.",
     "COFOG data can be used for analysing the quality of public expenditure, especially trends in government "
     "expenditure on particular functions or purposes over time and inter-country comparisons (allowing however for "
     "the differences in the composition of government sector and in the institutional arrangements in different "
     "countries)."),
    ("niveau_2", "périmètres", "gov_10a_exp_esms.htm",
     "https://ec.europa.eu/eurostat/cache/metadata/en/gov_10a_exp_esms.htm",
     "Le détail par groupe (niveau 2) n'est obligatoire qu'à partir de 2001, avec des dérogations : certaines années "
     "ou certains pays n'ont pas de valeur (null).",
     "The provision of COFOG level II (group level) data is compulsory for general government only, subject to "
     "derogations, from 2001 onwards."),
    ("provisoire", "révisions", "gov_10a_exp_esms.htm",
     "https://ec.europa.eu/eurostat/cache/metadata/en/gov_10a_exp_esms.htm",
     "Données provisoires publiées par Eurostat, dont la France pour 2023 et 2024 ; chaque valeur provisoire porte "
     "l'indicateur « p » dans les séries.",
     "Data for the EU and euro area aggregates (2024), Belgium (2024), Germany (2022-2024), Spain (2024), France "
     "(2023-2024) and Portugal (2024), Slovakia (all years) is provisional."),
    ("ruptures", "révisions", "gov_10a_exp_esms.htm",
     "https://ec.europa.eu/eurostat/cache/metadata/en/gov_10a_exp_esms.htm",
     "Des ruptures de méthode peuvent affecter les séries de certains pays ; elles portent l'indicateur « b ».",
     "In some countries, methodological breaks can affect time series (normally on a temporary basis)."),
    ("prestations_brutes", "prestations fiscalisées", "se_social_protection.htm",
     "https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Government_expenditure_on_social_protection",
     "Les prestations sociales forment l'essentiel de la protection sociale ; elles y sont comptées avant les impôts et "
     "cotisations prélevés sur ces prestations, que seul le module de prestations nettes d'Eurostat déduit (avertissement "
     "suivant). À prestation nette égale, un pays qui impose davantage les pensions ou allocations affiche une dépense "
     "plus haute (lecture du projet).",
     "In 2024 in the EU, social benefits and social transfers in kind (purchased market production) made up around "
     "89% of expenditure in the social protection COFOG division."),
    ("prestations_nettes_ue", "prestations fiscalisées", "social_protection_information_data.htm",
     "https://ec.europa.eu/eurostat/web/social-protection/information-data",
     "Eurostat publie à part un module de prestations nettes (prestations moins impôts et cotisations payés sur ces "
     "prestations), présenté comme plus fiable pour comparer les pays ; il n'est pas repris ici.",
     "This is done by measuring expenditure on social protection benefits less taxes and social contributions paid on "
     "these benefits. This module estimates the amount that is actually disbursed in a country for social protection "
     "benefits. This leads to a more reliable cross-country comparability of expenditure on social protection."),
    ("systemes_retraite", "systèmes de retraite", "nasa_10_pens_esms.htm",
     "https://ec.europa.eu/eurostat/cache/metadata/en/nasa_10_pens_esms.htm",
     "Selon les pays, les retraites reposent surtout sur des régimes publics de sécurité sociale (comptés dans les "
     "dépenses publiques) ou sur des régimes privés (hors dépenses publiques) : la dépense publique de vieillesse ne "
     "mesure donc pas l'ensemble des pensions versées.",
     "In some countries pension insurance traditionally relies rather on state social security schemes (not in core "
     "accounts), whereas in other countries biggest share of entitlements is accumulated in private pension schemes "
     "(in core accounts)."),
    ("vieillesse_pensions", "systèmes de retraite", "se_social_protection.htm",
     "https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Government_expenditure_on_social_protection",
     "Le groupe « vieillesse » contient surtout des pensions ; les pensions de réversion sont dans le groupe "
     "« survivants » (GF1003), publié à part.",
     "The group 'survivors' contains mainly pension payments to survivors of a deceased insured person."),
    ("defense_otan", "périmètres", "se_cofog.htm",
     "https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Government_expenditure_by_function_%E2%80%93_COFOG",
     "La fonction « défense » de COFOG ne se compare pas directement aux dépenses de défense au sens de l'OTAN.",
     "Moreover, COFOG division 'defence' cannot be easily compared with NATO measures of defence expenditure."),
    ("defense_otan_raisons", "périmètres", "se_cofog.htm",
     "https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Government_expenditure_by_function_%E2%80%93_COFOG",
     "Raisons publiées : classement par finalité principale (une partie de l'ordre public peut relever de la défense "
     "au sens de l'OTAN), pensions des militaires classées en protection sociale, moment d'enregistrement différent.",
     "The main reasons are: COFOG is a classification by main purpose implying that some expenditure within COFOG "
     "'public order and safety' might be counted under NATO methodology; the treatment of pensions in COFOG is within "
     "division 'social protection' and the COFOG treatment of employers' social contributions follows ESA 2010 and the "
     "time of recording may be different."),
    ("dette_interets", "périmètres", "se_general_public_services.htm",
     "https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Government_expenditure_on_general_public_services",
     "Le groupe « opérations concernant la dette publique » contient presque uniquement les intérêts de la dette "
     "publique et des services d'intermédiation financière (SIFIM) ; il ne contient pas les remboursements du capital.",
     "This COFOG group contains almost exclusively interest payments to service government gross debt as well as "
     "indirectly measured financial intermediation service charges (FISIM)."),
    ("logement_social", "périmètres", "se_social_protection.htm",
     "https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Government_expenditure_on_social_protection",
     "Les aides au logement versées aux ménages sont classées en protection sociale (GF1006) et non dans la division "
     "« logement » (GF06) : le poste logement additionne ici GF0601 et GF1006.",
     "'Housing', comprising mainly social protection payments to households to help with the cost of housing as well "
     "as the operation of social housing schemes, accounted for 0.4% of GDP or 0.7% of total expenditure at the level "
     "of the EU in 2024."),
    ("prelevements_comparabilite", "périmètres", "gov_10a_taxag_esms.htm",
     "https://ec.europa.eu/eurostat/cache/metadata/en/gov_10a_taxag_esms.htm",
     "Les recettes fiscales suivent le cadre commun SEC 2010 ; des ruptures de méthode peuvent toucher les séries de "
     "certains pays.",
     "Comparability - over time EU Member States: In some countries, methodological breaks can affect time series "
     "(normally on a temporary basis)."),
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "trouvailles": [
        {"nom": "API Eurostat (JSON-stat) gov_10a_exp, gov_10a_taxag, nama_10_pe, nama_10_gdp", "url": EUROSTAT,
         "verdict": "réutilisable tel quel", "licence": "Eurostat, réutilisation libre avec mention",
         "mise_a_jour": "données mises à jour le 2026-10-21 (COFOG) et le 2026-11-05 (impôts)"},
        {"nom": "collecte/collecte.py et pipeline/transform.py (jsonstat_records), dépôt du projet",
         "url": "collecte/collecte.py", "verdict": "réutilisable tel quel", "licence": "MIT",
         "mise_a_jour": "2026-11-17"},
        {"nom": "OCDE SDMX DSD_NASEC10@DF_TABLE11 (dépenses par fonction)",
         "url": "https://db.nomics.world/OECD/DSD_NASEC10@DF_TABLE11", "verdict": "inspiration seulement",
         "licence": "conditions de l'OCDE (non retenues : 22 pays de l'UE seulement, mêmes transmissions nationales "
                    "qu'Eurostat)", "mise_a_jour": "non relevée"},
        {"nom": "DBnomics, miroir Eurostat gov_10a_exp", "url": "https://db.nomics.world/Eurostat/gov_10a_exp",
         "verdict": "inspiration seulement", "licence": "données sous conditions Eurostat ; source primaire préférée",
         "mise_a_jour": "non relevée"},
        {"nom": "datasets/cofog (nomenclature COFOG)", "url": "https://github.com/datasets/cofog",
         "verdict": "inspiration seulement", "licence": "non déclarée sur GitHub ; libellés repris de l'API Eurostat",
         "mise_a_jour": "2026-07-27"},
        {"nom": "trongtin142/cofog-panel", "url": "https://github.com/trongtin142/cofog-panel",
         "verdict": "inspiration seulement", "licence": "MIT", "mise_a_jour": "2026-11-17"},
        {"nom": "jenarvaezg/cuentas-publicas (tableau de bord espagnol COFOG)",
         "url": "https://github.com/jenarvaezg/cuentas-publicas", "verdict": "inspiration seulement",
         "licence": "aucune licence déclarée (non réutilisable)", "mise_a_jour": "2026-09-07"},
        {"nom": "oliverjwroberts/cofog (analyse de la nomenclature)", "url": "https://github.com/oliverjwroberts/cofog",
         "verdict": "inspiration seulement", "licence": "MIT", "mise_a_jour": "2023-03-02 (archivé)"},
        {"nom": "paquet PyPI eurostat 1.1.1", "url": "https://pypi.org/project/eurostat/", "verdict": "à adapter",
         "licence": "MIT", "mise_a_jour": "2024-06-13 (non utilisé : décodeur déjà présent dans le dépôt)"},
    ],
}

ORDRE_ALPHA = "Pays par ordre alphabétique de leur nom en français (sans accents ni majuscules) ; UE à 27 et zone euro à part."
ORDRE_VALEUR = ("Pays par valeur décroissante en % du PIB, puis par ordre alphabétique en cas d'égalité ; rang 1 = "
                "valeur la plus haute ; des valeurs égales ont le même rang. Un rang décrit une position, pas un jugement.")


def _norm(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = s.replace("’", "'").replace("‘", "'").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip()


def _texte_document(nom: str) -> str:
    t = (DOCS / nom).read_text(encoding="utf-8", errors="replace")
    t = re.sub(r"(?s)<(script|style)\b.*?</\1>", " ", t)
    return _norm(t)


def nom_tri(nom: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", nom) if unicodedata.category(c) != "Mn").lower()


def _r(x: float | None, n: int = 1) -> float | None:
    return None if x is None else round(x + 0.0, n)


def charger(cle: str) -> tuple[list[dict], dict, dict]:
    """Lignes JSON-stat, libellés géo et méta (mise à jour Eurostat, statuts)."""
    sid, dataset, unite = SOURCES[cle]
    d = json.loads((LAKE / f"{sid}.json").read_text(encoding="utf-8"))
    lignes = jsonstat_records(d)
    ids, sizes = d["id"], d["size"]
    strides = [1] * len(ids)
    for i in range(len(ids) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]
    cats = [[c for c, _ in sorted(d["dimension"][x]["category"]["index"].items(), key=lambda kv: kv[1])] for x in ids]
    statuts = {}
    for flat, s in d.get("status", {}).items():
        if s in ("p", "b") and flat in d["value"]:
            f = int(flat)
            statuts[tuple(cs[(f // st) % sz] for cs, st, sz in zip(cats, strides, sizes))] = s
    for l in lignes:
        l["statut"] = statuts.get(tuple(l[x] for x in ids))
    geo = d["dimension"]["geo"]["category"]["label"]
    cof = d["dimension"].get("cofog99", {}).get("category", {}).get("label", {})
    nai = d["dimension"].get("na_item", {}).get("category", {}).get("label", {})
    return lignes, {"geo": geo, "cofog": cof, "na_item": nai}, {
        "id_collecte": sid, "dataset": dataset, "unite": unite, "maj_eurostat": str(d.get("updated", ""))[:10],
        "url": f"{EUROSTAT}/{dataset}"}


def verifier_citations() -> dict:
    textes, manquantes = {}, []
    for aid, _, doc, _, _, citation in AVERTISSEMENTS:
        if doc not in textes:
            textes[doc] = _texte_document(doc)
        if _norm(citation) not in textes[doc]:
            manquantes.append(aid)
    if manquantes:
        raise SystemExit(f"citation Eurostat introuvable dans le document collecté : {manquantes}")
    return {"citations": len(AVERTISSEMENTS), "retrouvees": len(AVERTISSEMENTS),
            "methode": "chaque citation est recherchée mot pour mot dans le document collecté "
                       "(data/lake/europe/eu_comparaison_documents/) ; la production échoue sinon"}


def produire(sortie: Path = SORTIE) -> None:
    verification = verifier_citations()
    pib_l, lab, meta_pib = charger("cofog_pib")
    part_l, _, meta_part = charger("cofog_part")
    meur_l, _, meta_meur = charger("cofog_meur")
    tax_l, lab_tax, meta_tax = charger("taxag")
    pop_l, _, meta_pop = charger("population")
    gdp_l, _, meta_gdp = charger("pib")
    geos = AGREGATS + sorted(PAYS, key=lambda g: nom_tri(lab["geo"][g]))
    nom_geo = {g: lab["geo"][g] for g in geos}

    pop = {(l["geo"], int(l["time"])): l["valeur"] * 1000 for l in pop_l}
    gdp = {(l["geo"], int(l["time"])): l["valeur"] for l in gdp_l}

    def table(lignes, cle):
        return {(l["geo"], l[cle], int(l["time"])): l for l in lignes}

    t_pib, t_part, t_meur = table(pib_l, "cofog99"), table(part_l, "cofog99"), table(meur_l, "cofog99")
    annees_exp = sorted({a for (g, c, a) in t_pib if c == "TOTAL" and a >= ANNEE_DEBUT
                         and sum((p, "TOTAL", a) in t_pib for p in PAYS) >= MIN_PAYS})
    annees_exp = list(range(annees_exp[0], annees_exp[-1] + 1))
    codes = [c for c, _ in sorted(json.loads((LAKE / "eu_comparaison_cofog_pib.json").read_text(encoding="utf-8"))
                                  ["dimension"]["cofog99"]["category"]["index"].items(), key=lambda kv: kv[1])]
    nom_code = {c: lab["cofog"][c] for c in codes}

    def val(t, g, c, a):
        l = t.get((g, c, a))
        return None if l is None else l["valeur"]

    def eur_hab(meur, g, a):
        p = pop.get((g, a))
        return None if meur is None or not p else _r(meur * 1e6 / p, 1)

    def serie_exp(g, c):
        return {"pct_pib": [val(t_pib, g, c, a) for a in annees_exp],
                "part_total": [val(t_part, g, c, a) for a in annees_exp],
                "eur_hab": [eur_hab(val(t_meur, g, c, a), g, a) for a in annees_exp]}

    def statuts_exp(g, c):
        out = {}
        for a in annees_exp:
            l = t_pib.get((g, c, a))
            if l and l["statut"]:
                out.setdefault(l["statut"], []).append(a)
        return out

    entete_commun = {
        "unite": "pct_pib : % du PIB (publié) ; part_total : % du total des dépenses publiques (publié) ; eur_hab : "
                 "euros courants par habitant (calculé : millions d'euros / population)",
    }
    source_exp = ("Eurostat gov_10a_exp (dépenses des administrations publiques S13 par fonction COFOG, transaction TE), "
                  f"mise à jour {meta_pib['maj_eurostat']} ; population Eurostat nama_10_pe (POP_NC), "
                  f"mise à jour {meta_pop['maj_eurostat']}")
    millesime_exp = f"Eurostat, {annees_exp[0]}-{annees_exp[-1]}"
    avert_series = ("Valeurs publiées par Eurostat, arrondies à 0,1 ; null = valeur non publiée. Euros courants, sans "
                    "correction des écarts de prix entre pays. Indicateurs « p » (provisoire) et « b » (rupture de "
                    "série) repris dans `statuts`. Voir index.json pour les avertissements de comparabilité.")

    (sortie / "depenses").mkdir(parents=True, exist_ok=True)
    fichiers_dep = []
    controle_somme = 0.0
    for div in ["TOTAL"] + [c for c in codes if len(c) == 4]:
        sous = [c for c in codes if div != "TOTAL" and len(c) == 6 and c.startswith(div)]
        doc = {"millesime": millesime_exp, "source": source_exp, **entete_commun, "avertissement": avert_series,
               "fonction": {"code": div, "nom": nom_code[div], "niveau": 0 if div == "TOTAL" else 1},
               "sous_fonctions": [{"code": c, "nom": nom_code[c], "niveau": 2} for c in sous],
               "annees": annees_exp, "geos": geos, "series": {}, "statuts": {}}
        for g in geos:
            doc["series"][g] = {c: serie_exp(g, c) for c in [div] + sous}
            st = {c: s for c in [div] + sous if (s := statuts_exp(g, c))}
            if st:
                doc["statuts"][g] = st
        nom_f = f"depenses/{div}.json"
        _ecrire(sortie / nom_f, doc)
        fichiers_dep.append({"code": div, "nom": nom_code[div], "fichier": f"comparaison/{nom_f}"})
    # contrôle : somme des 10 divisions = total (millions d'euros), écart maximal relevé
    for g in geos:
        for a in annees_exp:
            tot = val(t_meur, g, "TOTAL", a)
            parts = [val(t_meur, g, c, a) for c in codes if len(c) == 4]
            if tot and all(p is not None for p in parts):
                controle_somme = max(controle_somme, abs(sum(parts) - tot) / tot * 100)

    # prélèvements obligatoires
    t_tax = {(l["geo"], l["na_item"], l["unit"], int(l["time"])): l for l in tax_l}
    annees_tax = sorted({a for (g, c, u, a) in t_tax if c == TOTAL_PO and sum((p, TOTAL_PO, "MIO_EUR", a) in t_tax
                                                                                for p in PAYS) >= MIN_PAYS})
    annees_tax = list(range(max(ANNEE_DEBUT, annees_tax[0]), annees_tax[-1] + 1))

    def tv(g, c, u, a):
        l = t_tax.get((g, c, u, a))
        return None if l is None else l["valeur"]

    ecart_identite = 0.0
    for g in geos:
        for a in annees_tax:
            tot = tv(g, TOTAL_PO, "MIO_EUR", a)
            comp = [(s, tv(g, c, "MIO_EUR", a)) for c, _, s, _ in PRELEVEMENTS if s]
            if tot and all(v is not None for _, v in comp):
                ecart_identite = max(ecart_identite, abs(sum(s * v for s, v in comp) - tot) / tot * 100)
    series_tax, statuts_tax = {}, {}
    for g in geos:
        series_tax[g] = {}
        for c, *_ in PRELEVEMENTS:
            parts = []
            for a in annees_tax:
                v, tot = tv(g, c, "MIO_EUR", a), tv(g, TOTAL_PO, "MIO_EUR", a)
                parts.append(_r(v / tot * 100, 2) if v is not None and tot else None)
            series_tax[g][c] = {"pct_pib": [tv(g, c, "PC_GDP", a) for a in annees_tax], "part_total": parts,
                                "eur_hab": [eur_hab(tv(g, c, "MIO_EUR", a), g, a) for a in annees_tax]}
            st = {}
            for a in annees_tax:
                l = t_tax.get((g, c, "PC_GDP", a))
                if l and l["statut"]:
                    st.setdefault(l["statut"], []).append(a)
            if st:
                statuts_tax.setdefault(g, {})[c] = st
    source_tax = (f"Eurostat gov_10a_taxag (secteur S13_S212 : administrations publiques et institutions de l'UE), "
                  f"mise à jour {meta_tax['maj_eurostat']} ; population Eurostat nama_10_pe")
    prelev = {
        "millesime": f"Eurostat, {annees_tax[0]}-{annees_tax[-1]}", "source": source_tax,
        "unite": "pct_pib : % du PIB (publié) ; part_total : % du total des prélèvements obligatoires (calculé) ; "
                 "eur_hab : euros courants par habitant (calculé)",
        "avertissement": avert_series,
        "note": "Total au sens d'Eurostat : impôts et cotisations sociales obligatoires après déduction des montants dus "
                "non recouvrables, y compris les impôts versés aux institutions de l'UE (secteur S13_S212). Il diffère du "
                "taux de prélèvements obligatoires publié par l'Insee (périmètre national). Cotisations volontaires et "
                "imputées exclues.",
        "identite": {"formule": "total = D2 + D5 + D91 + D611C + D613C - D995",
                     "ecart_max_pct_du_total": _r(ecart_identite, 3)},
        "categories": [{"code": c, "nom": n, "signe": s, "parent": p} for c, n, s, p in PRELEVEMENTS],
        "annees": annees_tax, "geos": geos, "series": series_tax, "statuts": statuts_tax,
    }
    _ecrire(sortie / "prelevements.json", prelev)

    # fiches « La France et ses voisins »
    def mesure(cs, a):
        """{geo: (pct_pib, eur_hab, part_total)} pour une liste de codes ; somme calculée si plusieurs codes."""
        out = {}
        for g in geos:
            if len(cs) == 1:
                out[g] = (val(t_pib, g, cs[0], a), eur_hab(val(t_meur, g, cs[0], a), g, a), val(t_part, g, cs[0], a))
                continue
            ms = [val(t_meur, g, c, a) for c in cs]
            tot, p = val(t_meur, g, "TOTAL", a), gdp.get((g, a))
            if any(m is None for m in ms):
                out[g] = (None, None, None)
            else:
                s = sum(ms)
                out[g] = (_r(s / p * 100, 2) if p else None, eur_hab(s, g, a), _r(s / tot * 100, 2) if tot else None)
        return out

    def fiche_stats(get, annees):
        """get(a) -> {geo: (pct_pib, eur_hab, part_total)} ; dernière année = FR publiée et >= MIN_PAYS pays."""
        retenue = None
        for a in reversed(annees):
            m = get(a)
            if m["FR"][0] is not None and sum(m[p][0] is not None for p in PAYS) >= MIN_PAYS:
                retenue, mes = a, m
                break
        vals = {p: mes[p][0] for p in PAYS if mes[p][0] is not None}
        med = statistics.median(vals.values())
        rang = 1 + sum(v > vals["FR"] for v in vals.values())
        ordre = sorted(vals, key=lambda p: (-vals[p], nom_tri(nom_geo[p])))
        avant = retenue - 10
        evol = None
        if avant in annees:
            m0 = get(avant)
            v0 = {p: m0[p][0] for p in PAYS if m0[p][0] is not None}
            if "FR" in v0:
                communs = [p for p in vals if p in v0]
                evol = {"annee_depart": avant, "annee_arrivee": retenue,
                        "france_points_pib": _r(vals["FR"] - v0["FR"], 2),
                        "mediane_ue_points_pib": _r(statistics.median([vals[p] - v0[p] for p in communs]), 2),
                        "ue27_points_pib": (None if mes["EU27_2020"][0] is None or m0["EU27_2020"][0] is None
                                            else _r(mes["EU27_2020"][0] - m0["EU27_2020"][0], 2)),
                        "pays_compares": len(communs),
                        "france_depart_pct_pib": v0["FR"]}
        return {
            "annee": retenue, "pays_publies": len(vals),
            "france": {"pct_pib": mes["FR"][0], "eur_hab": mes["FR"][1], "part_total": mes["FR"][2]},
            "ue27": {"pct_pib": mes["EU27_2020"][0], "eur_hab": mes["EU27_2020"][1], "part_total": mes["EU27_2020"][2]},
            "zone_euro": {"pct_pib": mes["EA20"][0], "eur_hab": mes["EA20"][1], "part_total": mes["EA20"][2]},
            "mediane_ue_pct_pib": _r(med, 2),
            "ecart_mediane_points_pib": _r(vals["FR"] - med, 2),
            "rang": rang, "rang_sur": len(vals),
            "evolution_10_ans": evol,
            "pays_par_valeur": [{"geo": p, "nom": nom_geo[p], "pct_pib": vals[p], "eur_hab": mes[p][1],
                                 "part_total": mes[p][2]} for p in ordre],
        }

    avert_par_id = {a[0]: a for a in AVERTISSEMENTS}
    fiches = []
    for fid, titre, cs, voir, avs in FICHES:
        st = fiche_stats(lambda a, cs=cs: mesure(cs, a), annees_exp)
        f = {"id": fid, "titre": titre, "type": "depense",
             "codes": [{"code": c, "nom": nom_code[c]} for c in cs],
             "mode": "publié par Eurostat" if len(cs) == 1 else "calculé : somme des millions d'euros des codes / PIB "
                                                                "(nama_10_gdp) et / total des dépenses",
             "fichier": f"comparaison/depenses/{cs[0][:4]}.json", **st,
             "voir_aussi": [{"code": c, "nom": nom_code[c], **{k: v for k, v in fiche_stats(
                 lambda a, c=c: mesure([c], a), annees_exp).items() if k != "pays_par_valeur"}} for c in voir],
             "avertissements": [aid for aid in avs if aid in avert_par_id]}
        fiches.append(f)
    # repères de contexte : dépenses totales et prélèvements obligatoires
    fiches.append({"id": "depenses_totales", "titre": "Dépenses publiques totales", "type": "contexte",
                   "codes": [{"code": "TOTAL", "nom": nom_code["TOTAL"]}], "mode": "publié par Eurostat",
                   "fichier": "comparaison/depenses/TOTAL.json",
                   **fiche_stats(lambda a: mesure(["TOTAL"], a), annees_exp), "voir_aussi": [],
                   "avertissements": ["perimetres", "provisoire", "ruptures"]})

    def mesure_tax(a):
        return {g: (tv(g, TOTAL_PO, "PC_GDP", a), eur_hab(tv(g, TOTAL_PO, "MIO_EUR", a), g, a), 100.0 if
                    tv(g, TOTAL_PO, "MIO_EUR", a) else None) for g in geos}
    fiches.append({"id": "prelevements_obligatoires", "titre": "Impôts et cotisations sociales obligatoires",
                   "type": "contexte", "codes": [{"code": TOTAL_PO, "nom": PRELEVEMENTS[0][1]}],
                   "mode": "publié par Eurostat", "fichier": "comparaison/prelevements.json",
                   **fiche_stats(mesure_tax, annees_tax), "voir_aussi": [],
                   "avertissements": ["perimetres", "prelevements_comparabilite"]})
    _ecrire(sortie / "fiches.json", {
        "millesime": f"Eurostat, dépenses {annees_exp[-1]}, prélèvements {annees_tax[-1]} (dernière année publiée "
                     f"par la France et au moins {MIN_PAYS} pays)",
        "source": f"{source_exp} ; {source_tax} ; PIB Eurostat nama_10_gdp (B1GQ)",
        "unite": "% du PIB, points de PIB, euros courants par habitant, % du total",
        "avertissement": "Médiane : médiane des 27 valeurs nationales publiées (non pondérée) ; UE27 et zone euro : "
                         "agrégats publiés par Eurostat (pondérés). Écart et évolution en points de PIB, calculés sur "
                         "les valeurs publiées. Chaque fiche renvoie à ses avertissements de comparabilité (index.json).",
        "ordre": {"regle": ORDRE_VALEUR, "cles": ["-pct_pib", "nom_tri"]},
        "definitions": {
            "rang": "position de la France parmi les pays publiés, valeurs décroissantes en % du PIB (1 = la plus haute)",
            "mediane_ue_pct_pib": "valeur du milieu des pays publiés, rangés par valeur",
            "ecart_mediane_points_pib": "valeur de la France moins médiane, en points de PIB",
            "evolution_10_ans": "valeur de l'année retenue moins valeur dix ans avant, en points de PIB"},
        "fiches": fiches})

    sources = {k: {**m} for k, m in (("cofog_pib", meta_pib), ("cofog_part", meta_part), ("cofog_meur", meta_meur),
                                       ("taxag", meta_tax), ("population", meta_pop), ("pib", meta_gdp))}
    index = {
        "millesime": f"Eurostat, dépenses {annees_exp[0]}-{annees_exp[-1]}, prélèvements {annees_tax[0]}-{annees_tax[-1]}",
        "source": "Eurostat gov_10a_exp, gov_10a_taxag, nama_10_pe, nama_10_gdp ; métadonnées et articles Eurostat",
        "unite": "% du PIB, euros courants par habitant, % du total",
        "avertissement": "Mêmes séries et même format pour chaque pays. Aucune valeur n'est qualifiée : les écarts "
                         "décrivent des différences de niveau, sans dire s'ils sont souhaitables. Les comparaisons "
                         "dépendent des avertissements publiés par Eurostat, listés ici.",
        "collecte_le": date_sources("europe"),
        "sources": sources,
        "agregats": [{"geo": g, "nom": nom_geo[g]} for g in AGREGATS],
        "pays": [{"geo": g, "nom": nom_geo[g], "nom_tri": nom_tri(nom_geo[g])} for g in geos if g in PAYS],
        "ordre": {"regle": ORDRE_ALPHA, "cles": ["nom_tri"]},
        "unites": {"pct_pib": "% du PIB à prix courants, publié par Eurostat",
                   "part_total": "% du total des dépenses publiques (publié) ou des prélèvements (calculé)",
                   "eur_hab": "euros courants par habitant : millions d'euros / population moyenne (nama_10_pe), "
                              "sans correction des écarts de prix entre pays"},
        "depenses": {"annees": [annees_exp[0], annees_exp[-1]], "fichiers": fichiers_dep,
                     "controle_somme_divisions": {"ecart_max_pct_du_total": _r(controle_somme, 3),
                                                  "definition": "écart entre la somme des 10 divisions et le total, "
                                                                "millions d'euros, tous pays et années"}},
        "prelevements": {"annees": [annees_tax[0], annees_tax[-1]], "fichier": "comparaison/prelevements.json"},
        "fiches": {"fichier": "comparaison/fiches.json", "ids": [f["id"] for f in fiches]},
        "avertissements": [{"id": a, "theme": th, "texte": tx, "citation": ci, "langue_citation": "en",
                            "source": {"url": url, "document": f"data/lake/europe/eu_comparaison_documents/{doc}"}}
                           for a, th, doc, url, tx, ci in AVERTISSEMENTS],
        "verification_documents": verification,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    _ecrire(sortie / "index.json", index)


def _ecrire(chemin: Path, doc: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("produire")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
