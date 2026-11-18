"""Sécurité intérieure : police nationale (programme 176), gendarmerie nationale (152), sécurité civile (161),
sécurité et éducation routières (207), compte d'affectation spéciale « Contrôle de la circulation et du
stationnement routiers » (recettes des amendes et leur affectation, programmes 751, 753, 754 et 755).

Uniquement des montants budgétaires publiés : crédits votés, ouverts et consommés par programme et par titre
(personnel, fonctionnement, investissement, intervention, opérations financières), crédits par action et
sous-action, plafonds d'emplois en équivalents temps plein travaillé (ETPT), recettes et dépenses du compte des
amendes. Aucune statistique de délinquance (hors du sujet du site), aucune donnée individuelle.

Commandes :
    python pipeline/securite_interieure.py collecter   (réseau, par collecte/collecte.py ; un refus 401/403/429 est
                                                       noté, jamais contourné)
    python pipeline/securite_interieure.py produire [--sortie DOSSIER]   (sans réseau ; lit
                                                       data/lake/securite_interieure/ et, en lecture seule,
                                                       site/data/realisations/<programme>.json)

Sorties (site/data/securite_interieure/, contrat docs/contrat_interface.md, schémas
docs/schemas/securite_interieure_*) : index.json, budget.json, effectifs.json, amendes.json

Règles : une valeur absente à la source reste null, jamais 0 ; les sources ne sont jamais additionnées entre elles
(exécution, loi de finances, projet de loi : côte à côte) ; un total qui ne retombe pas sur la somme de ses lignes
est publié avec son écart, jamais corrigé ; toute somme faite par le site porte `statut: "calculé"` et sa
formule. Dates par pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques octet pour
octet.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "securite_interieure"
MANIFESTE = ROOT / "data" / "lake" / "manifest.json"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "securite_interieure"
DOMAINE = "securite_interieure"

ECO = "https://data.economie.gouv.fr/explore/dataset/"
SOURCES = {
    "plrg": {
        "id_catalogue": "securite_interieure_plrg_annexes",
        "titre": "Projets de loi relatifs aux résultats de la gestion et portant approbation des comptes (PLRG) 2023, "
                 "2024 et 2025, annexes 1 et 2 en CSV (ministère de l'Économie et des Finances)",
        "page": ECO + "projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-lannee-plrg-2025/",
        "licence": "Licence Ouverte 2.0"},
    "budget_vert": {
        "id_catalogue": "securite_interieure_budget_vert_2026",
        "titre": "PLF 2026, budget vert : crédits par sous-action, exécution 2024, LFI 2025 et PLF 2026 "
                 "(ministère de l'Économie et des Finances)",
        "page": ECO + "plf-2026-budget-vert/",
        "licence": "Licence Ouverte 2.0"},
    "plf25_nature": {
        "id_catalogue": "securite_interieure_plf25_destination_nature",
        "titre": "PLF 2025, dépenses selon les nomenclatures de destination et de nature (ministère de l'Économie et "
                 "des Finances)",
        "page": ECO + "plf25-depenses-2025-du-bg-et-des-ba-selon-nomenclatures-destination-et-nature/",
        "licence": "Licence Ouverte 2.0"},
    "etpt_2019": {
        "id_catalogue": "securite_interieure_etpt_lfi_2019",
        "titre": "Loi de finances initiale 2019, crédits et emplois (ETPT) par programme",
        "page": ECO + "loi-de-finances-initiale-pour-2019-lfi-2019/",
        "licence": "Licence Ouverte 2.0"},
    "etpt_2020_2022": {
        "id_catalogue": "securite_interieure_etpt_lfi_2020_2022",
        "titre": "Lois de finances initiales 2020, 2021 et 2022, emplois (ETPT) par programme, pièces jointes CSV",
        "page": ECO + "projet-de-loi-de-finances-initiale-pour-2022-lfi-2022/",
        "licence": "Licence Ouverte 2.0"},
    "etpt_2023": {
        "id_catalogue": "securite_interieure_etpt_lfi_2023",
        "titre": "ETPT par ministère, mission et programme pour le budget général et les budgets annexes, LFI 2023",
        "page": ECO + "etpt-par-ministere-mission-programme-pour-le-bg-et-les-ba-lfi-2023/",
        "licence": "Licence Ouverte 2.0"},
}

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Les crédits par programme, titre, catégorie, action et sous-action, les emplois votés et les "
                  "recettes du compte des amendes sont publiés en CSV par le ministère de l'Économie et des Finances : "
                  "ils sont repris tels quels. Les projets et rapports annuels de performances (PDF de budget.gouv.fr) "
                  "ne sont pas accessibles aux scripts. Aucun dépôt public trouvé ne publie ces jeux pour la mission "
                  "Sécurités ; module écrit pour le dépôt, sur le modèle de pipeline/justice_defense.py.",
    "trouvailles": [
        {"nom": "PLRG 2023, 2024 et 2025, annexes CSV (data.economie.gouv.fr)",
         "url": SOURCES["plrg"]["page"], "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0",
         "mise_a_jour": "2026"},
        {"nom": "PLF 2026, budget vert (crédits par sous-action, exécution 2024, LFI 2025, PLF 2026)",
         "url": SOURCES["budget_vert"]["page"], "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0",
         "mise_a_jour": "2025-11-13"},
        {"nom": "PLF 2025, dépenses selon destination et nature", "url": SOURCES["plf25_nature"]["page"],
         "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2024-10"},
        {"nom": "Emplois (ETPT) par programme, LFI 2019 à 2023", "url": SOURCES["etpt_2023"]["page"],
         "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2023-03-10"},
        {"nom": "site/data/realisations/<programme>.json du dépôt (prévu et dépensé 2010-2025)",
         "url": "pipeline/realisations.py", "verdict": "réutilisable tel quel", "licence": "MIT",
         "mise_a_jour": "2026-11-17"},
        {"nom": "cturkieh/france-budget-simulateur (simulateur du budget de l'État)",
         "url": "https://github.com/cturkieh/france-budget-simulateur", "verdict": "inspiration seulement",
         "licence": "AGPL-3.0 (ne lit pas ces jeux par programme)", "mise_a_jour": "2026-11-14"},
        {"nom": "CornierQuentin/budgetcitoyen-api (API du budget de l'État)",
         "url": "https://github.com/CornierQuentin/budgetcitoyen-api", "verdict": "inspiration seulement",
         "licence": "AGPL-3.0 (licence incompatible avec une reprise du code sous MIT)", "mise_a_jour": "2026-08-18"},
        {"nom": "Recherche GitHub « budget police gendarmerie », « amendes radars budget »",
         "url": "https://github.com/search?q=budget+police+gendarmerie&type=repositories",
         "verdict": "inspiration seulement", "licence": "sans objet (aucun dépôt trouvé)", "mise_a_jour": "2026-11-18"},
    ],
}

PROGRAMMES = [("176", "Police nationale"), ("152", "Gendarmerie nationale"), ("161", "Sécurité civile"),
              ("207", "Sécurité et éducation routières")]
ANNEES_PLRG = (2023, 2024, 2025)
COMPTE_AMENDES = "Contrôle de la circulation et du stationnement routiers"
PROGRAMMES_COMPTE = ("751", "753", "754", "755")
# Structure du compte (loi n° 2005-1719 de finances pour 2006, article 49) : section « Contrôle automatisé »
# -> programme 751 ; section « Circulation et stationnement routiers » -> programmes 753, 754, 755.
SECTIONS_COMPTE = {"746": {"libelle": "Contrôle automatisé", "programmes": ["751"]},
                   "747": {"libelle": "Circulation et stationnement routiers", "programmes": ["753", "754", "755"]}}

TITRES = {"2": ("personnel", "Dépenses de personnel"), "3": ("fonctionnement", "Dépenses de fonctionnement"),
          "5": ("investissement", "Dépenses d'investissement"), "6": ("intervention", "Dépenses d'intervention"),
          "7": ("operations_financieres", "Dépenses d'opérations financières")}
CATEGORIES = {
    "21": "Rémunérations d'activité", "22": "Cotisations et contributions sociales",
    "23": "Prestations sociales et allocations diverses", "31": "Dépenses de fonctionnement autres que celles de personnel",
    "32": "Subventions pour charges de service public", "51": "Dépenses pour immobilisations corporelles de l'État",
    "52": "Dépenses pour immobilisations incorporelles de l'État", "53": "Subventions pour charges d'investissement",
    "61": "Transferts aux ménages", "62": "Transferts aux entreprises", "63": "Transferts aux collectivités territoriales",
    "64": "Transferts aux autres collectivités", "65": "Appels en garantie", "71": "Prêts et avances",
    "72": "Dotations en fonds propres", "73": "Dépenses de participations financières"}


class DonneeInattendue(RuntimeError):
    """La source ne ressemble plus à ce que le module sait lire : on s'arrête plutôt que de publier un chiffre faux."""


# --------------------------------------------------------------------------------------------------------------------
# utilitaires

def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def nombre(x) -> float | None:
    """Nombre publié (« 1 187 », « 8 069,00 », « 336340107 », 2138.0) ; vide, tiret, « nc » : None, jamais 0."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace("\xa0", "").replace(" ", "").replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return None
    return float(s)


def _eur(x) -> float | None:
    v = nombre(x)
    return None if v is None else round(v, 2)


def code_programme(libelle: str) -> str | None:
    """« Police nationale - 176 » -> « 176 »."""
    m = re.search(r"-\s*(\d{3})\s*$", str(libelle or ""))
    return m.group(1) if m else None


def _sans_code(libelle: str) -> str:
    return re.sub(r"\s*-\s*\d{3,6}\s*$", "", str(libelle or "")).strip()


def _code_fin(libelle: str) -> str | None:
    m = re.search(r"-\s*(\d{3,6})\s*$", str(libelle or ""))
    return m.group(1) if m else None


def lire_csv(chemin: Path) -> list[dict]:
    """CSV à point-virgule, UTF-8 avec ou sans BOM, éventuellement compressé (gzip) tel que servi par le portail."""
    brut = chemin.read_bytes()
    if brut[:2] == b"\x1f\x8b":
        brut = gzip.decompress(brut)
    texte = brut.decode("utf-8-sig")
    lignes = list(csv.DictReader(io.StringIO(texte), delimiter=";"))
    return [{(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in li.items()} for li in lignes]


def _fichier(cle: str, nom: str | None = None) -> Path:
    ident = SOURCES[cle]["id_catalogue"]
    f = LAKE / ident / nom if nom else LAKE / f"{ident}.csv"
    if not f.exists():
        raise FileNotFoundError(f"{f.relative_to(ROOT)} absent : lancer python pipeline/securite_interieure.py collecter")
    return f


def _manifeste() -> dict:
    try:
        return json.loads(MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _url_plrg(nom: str) -> str | None:
    for f in _manifeste().get(SOURCES["plrg"]["id_catalogue"], {}).get("fichiers", []):
        if Path(f.get("chemin", "")).name == nom:
            return f.get("url")
    return None


# --------------------------------------------------------------------------------------------------------------------
# budget : exécution (PLRG), nature, actions (budget vert), nature par action (PLF 2025)

COLONNES_CP = ("LFI", "LFR", "Report_N-1", "Mvts_reglementaires", "FDC_et_ADP", "Fongibilite_asymetrique",
               "Total_CP_Ouverts", "Depenses_constatees", "Modif_Ouvertures", "Modif_Annulations", "Report_N+1")


def lire_execution(annee: int, fichier: str) -> dict[str, dict]:
    """Annexe « état CP » : par programme, ligne « Titre 2 » et ligne « Autres titres »."""
    lignes = lire_csv(_fichier("plrg", fichier))
    if not lignes or not set(("Programme", "Titre") + COLONNES_CP) <= set(lignes[0]):
        raise DonneeInattendue(f"{fichier} : colonnes non reconnues")
    res: dict[str, dict] = {}
    for li in lignes:
        p = code_programme(li["Programme"])
        if not p:
            continue
        t = _norm(li["Titre"])
        cle = "personnel" if t.startswith("titre 2") else "autres_titres" if t.startswith("autres titres") else None
        if cle is None:
            raise DonneeInattendue(f"{fichier} : titre « {li['Titre']} » non reconnu")
        d = res.setdefault(p, {"libelle": _sans_code(li["Programme"]), "mission": li.get("Mission")})
        if cle in d:
            raise DonneeInattendue(f"{fichier} : deux lignes {cle} pour le programme {p}")
        d[cle] = {"lfi_eur": _eur(li["LFI"]), "lfr_eur": _eur(li["LFR"]),
                  "credits_ouverts_eur": _eur(li["Total_CP_Ouverts"]),
                  "depenses_constatees_eur": _eur(li["Depenses_constatees"])}
    return res


def lire_titre_categorie(fichier: str) -> dict[str, dict[str, float]]:
    lignes = lire_csv(_fichier("plrg", fichier))
    if not lignes or not {"Programme", "Titre", "Categorie", "Depenses"} <= set(lignes[0]):
        raise DonneeInattendue(f"{fichier} : colonnes non reconnues")
    res: dict[str, dict[str, float]] = {}
    for li in lignes:
        p = code_programme(li["Programme"])
        cat = str(li["Categorie"]).strip()
        if not p or not re.fullmatch(r"\d{2}", cat):
            continue
        titre = re.sub(r"\D", "", li["Titre"])
        if titre != cat[0]:
            raise DonneeInattendue(f"{fichier} : catégorie {cat} rangée sous « {li['Titre']} »")
        v = _eur(li["Depenses"])
        if v is None:
            continue
        res.setdefault(p, {})
        res[p][cat] = round(res[p].get(cat, 0.0) + v, 2)
    return res


def _somme(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals), 2) if vals else None


def construire_execution(code: str, executions: dict, natures: dict) -> tuple[list, list, list]:
    execution, nature, ecarts = [], [], []
    for annee in ANNEES_PLRG:
        e = executions[annee].get(code)
        if e is None:
            raise DonneeInattendue(f"PLRG {annee} : programme {code} absent")
        perso = e.get("personnel")
        autres = e.get("autres_titres")
        total = {k: _somme([(perso or {}).get(k), (autres or {}).get(k)])
                 for k in ("lfi_eur", "lfr_eur", "credits_ouverts_eur", "depenses_constatees_eur")}
        execution.append({"annee": annee, "personnel": perso, "autres_titres": autres, "total": total,
                          "source": f"PLRG {annee}, annexe 1, état CP ({_url_plrg(f'plrg_{annee}_bg_cp.csv') or SOURCES['plrg']['page']})"})
        cats = natures[annee].get(code, {})
        titres = []
        for t, (groupe, lib) in TITRES.items():
            lignes = [{"categorie": c, "libelle": CATEGORIES.get(c, c), "eur": v}
                      for c, v in sorted(cats.items()) if c[0] == t]
            if not lignes:
                continue
            titres.append({"titre": t, "groupe": groupe, "libelle": lib,
                           "eur": round(sum(x["eur"] for x in lignes), 2), "categories": lignes})
        somme = round(sum(x["eur"] for x in titres), 2)
        for x in titres:
            x["part_pct"] = round(100 * x["eur"] / somme, 2) if somme else None
        dep = total["depenses_constatees_eur"]
        controle = {"somme_categories_eur": somme, "depenses_constatees_etat_cp_eur": dep,
                    "ecart_eur": None if dep is None else round(somme - dep, 2)}
        if dep is not None and abs(somme - dep) > 1.0:
            ecarts.append({"objet": f"programme {code}, dépenses {annee}", "source": "annexe état titre catégorie",
                           "montant": somme, "autre_source": "annexe état CP (dépenses constatées)",
                           "autre_montant": dep, "ecart": round(somme - dep, 2), "unite": "euros",
                           "lecture": "Deux annexes du même projet de loi ; les deux valeurs sont reprises telles quelles."})
        t2 = next((x["eur"] for x in titres if x["titre"] == "2"), None)
        if perso and t2 is not None and perso["depenses_constatees_eur"] is not None \
                and abs(t2 - perso["depenses_constatees_eur"]) > 1.0:
            ecarts.append({"objet": f"programme {code}, dépenses de personnel {annee}",
                           "source": "annexe état titre catégorie", "montant": t2,
                           "autre_source": "annexe état CP (titre 2)", "autre_montant": perso["depenses_constatees_eur"],
                           "ecart": round(t2 - perso["depenses_constatees_eur"], 2), "unite": "euros",
                           "lecture": "Deux annexes du même projet de loi ; les deux valeurs sont reprises telles quelles."})
        nature.append({"annee": annee, "titres": titres, "controle": controle})
    return execution, nature, ecarts


def lire_budget_vert() -> list[dict]:
    lignes = lire_csv(_fichier("budget_vert"))
    attendu = {"type_depense", "numero_programme", "code_action_si_credit_budgetaire", "action_si_credit_budgetaire",
               "code_depense", "libelle", "execution_2024_cp", "lfi_2025_cp_ou_prevision_2025_si_depense_fiscale",
               "plf_2026_cp_ou_prevision_2026_si_depense_fiscale"}
    if not lignes or not attendu <= set(lignes[0]):
        raise DonneeInattendue("budget vert : colonnes non reconnues")
    sortie = []
    for li in lignes:
        if _norm(li["type_depense"]) != "credits budgetaires":
            continue  # dépenses fiscales : hors du périmètre des crédits
        p = str(int(float(li["numero_programme"])))
        sortie.append({"programme": p, "action": li["code_action_si_credit_budgetaire"],
                       "libelle_action": li["action_si_credit_budgetaire"], "code": li["code_depense"],
                       "libelle": li["libelle"],
                       "execution_2024_eur": _eur(li["execution_2024_cp"]),
                       "lfi_2025_eur": _eur(li["lfi_2025_cp_ou_prevision_2025_si_depense_fiscale"]),
                       "plf_2026_eur": _eur(li["plf_2026_cp_ou_prevision_2026_si_depense_fiscale"])})
    sortie.sort(key=lambda x: (x["programme"], x["code"]))
    return sortie


COLS_BV = ("execution_2024_eur", "lfi_2025_eur", "plf_2026_eur")


def construire_actions(code: str, bv: list[dict]) -> tuple[list, list]:
    """Actions et sous-actions du programme ; lignes techniques du budget vert (contribution au compte Pensions,
    fonds de concours, mesures de périmètre) à part, jamais ajoutées aux actions."""
    actions: dict[str, dict] = {}
    techniques = []
    for x in (y for y in bv if y["programme"] == code):
        if not re.fullmatch(rf"{code}-\d{{2}}", x["action"] or ""):
            techniques.append({"code": x["code"], "libelle": x["libelle"], **{k: x[k] for k in COLS_BV}})
            continue
        a = actions.setdefault(x["action"], {"code": x["action"], "libelle": x["libelle_action"], "sous_actions": []})
        a["sous_actions"].append({"code": x["code"], "libelle": x["libelle"], **{k: x[k] for k in COLS_BV}})
    sortie = []
    for c in sorted(actions):
        a = actions[c]
        for k in COLS_BV:
            a[k] = _somme(s[k] for s in a["sous_actions"])
        sortie.append({"code": a["code"], "libelle": a["libelle"], **{k: a[k] for k in COLS_BV},
                       "sous_actions": a["sous_actions"]})
    return sortie, techniques


def lire_nature_plf25() -> dict[str, dict]:
    lignes = lire_csv(_fichier("plf25_nature"))
    if not lignes or not {"programme", "action", "libelle_action", "code_titre", "categorie", "cp_plf"} <= set(lignes[0]):
        raise DonneeInattendue("PLF 2025 destination et nature : colonnes non reconnues")
    res: dict[str, dict] = {}
    for li in lignes:
        p = str(int(float(li["programme"])))
        a = f"{p}-{li['action']}"
        t = str(li["code_titre"]).strip()
        v = _eur(li["cp_plf"])
        if v is None:
            continue
        act = res.setdefault(p, {}).setdefault(a, {"code": a, "libelle": li["libelle_action"], "titres": {}})
        act["titres"][t] = round(act["titres"].get(t, 0.0) + v, 2)
    return res


def _realisations(code: str) -> dict:
    f = SITE / "realisations" / f"{code}.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    serie = [{"annee": int(a["annee"]), "vote_lfi_eur": a.get("vote_lfi_eur"),
              "depense_constatee_eur": a.get("depense_constatee_eur")}
             for a in d["prevu_depense"]["annees"]]
    return {"libelle": d.get("libelle"), "serie": sorted(serie, key=lambda x: x["annee"])}


def construire_budget() -> dict:
    executions = {a: lire_execution(a, f"plrg_{a}_bg_cp.csv") for a in ANNEES_PLRG}
    natures = {a: lire_titre_categorie(f"plrg_{a}_bg_titre_categorie.csv") for a in ANNEES_PLRG}
    bv = lire_budget_vert()
    plf25 = lire_nature_plf25()
    programmes, ecarts = [], []
    for code, libelle in PROGRAMMES:
        lib_source = executions[ANNEES_PLRG[-1]][code]["libelle"]
        if _norm(lib_source) != _norm(libelle):
            raise DonneeInattendue(f"programme {code} : libellé « {lib_source} » ≠ « {libelle} »")
        execution, nature, ec = construire_execution(code, executions, natures)
        ecarts += ec
        actions, techniques = construire_actions(code, bv)
        if not actions:
            raise DonneeInattendue(f"budget vert : aucune action pour le programme {code}")
        som24 = _somme(a["execution_2024_eur"] for a in actions)
        dep24 = next(e["total"]["depenses_constatees_eur"] for e in execution if e["annee"] == 2024)
        controle_actions = {"somme_actions_execution_2024_eur": som24, "depenses_constatees_2024_plrg_eur": dep24,
                            "ecart_eur": None if None in (som24, dep24) else round(som24 - dep24, 2),
                            "lecture": "Somme des sous-actions du budget vert pour 2024 face aux dépenses constatées "
                                       "2024 du PLRG : deux publications, reprises telles quelles."}
        nat_act = []
        for a in sorted(plf25.get(code, {}).values(), key=lambda x: x["code"]):
            titres = [{"titre": t, "groupe": TITRES[t][0], "eur": v} for t, v in sorted(a["titres"].items())]
            nat_act.append({"code": a["code"], "libelle": a["libelle"], "titres": titres,
                            "total_eur": round(sum(x["eur"] for x in titres), 2)})
        real = _realisations(code)
        programmes.append({
            "programme": code, "libelle": libelle, "mission": "Sécurités",
            "execution": execution, "nature": nature,
            "actions": actions, "lignes_techniques_budget_vert": techniques, "controle_actions": controle_actions,
            "nature_par_action_plf2025": nat_act,
            "serie_longue": real["serie"],
        })
    # mission : somme calculée des quatre programmes (même source, même année)
    mission = []
    for annee in ANNEES_PLRG:
        tot = [next(e for e in p["execution"] if e["annee"] == annee)["total"]["depenses_constatees_eur"]
               for p in programmes]
        perso = [(next(e for e in p["execution"] if e["annee"] == annee)["personnel"] or {}).get("depenses_constatees_eur")
                 for p in programmes]
        mission.append({"annee": annee, "depenses_constatees_eur": _somme(tot), "dont_personnel_eur": _somme(perso)})
    routiere = []
    for x in bv:
        if x["programme"] == "207" and re.fullmatch(r"207-\d{2}", x["action"] or ""):
            routiere.append({"programme": "207", "action": x["action"], "libelle": x["libelle"],
                             **{k: x[k] for k in COLS_BV}})
        elif x["action"] in ("176-03", "152-02"):
            routiere.append({"programme": x["programme"], "action": x["action"],
                             "libelle": f"{x['libelle_action']} ({x['libelle']})", **{k: x[k] for k in COLS_BV}})
        elif x["programme"] == "751" and re.fullmatch(r"751-\d{2}", x["action"] or ""):
            routiere.append({"programme": "751", "action": x["action"], "libelle": x["libelle"],
                             **{k: x[k] for k in COLS_BV}})
    return {
        "millesime": f"Exécution {ANNEES_PLRG[0]} à {ANNEES_PLRG[-1]} (PLRG) ; actions : exécution 2024, LFI 2025, "
                     "PLF 2026 (budget vert) ; nature par action : PLF 2025",
        "source": " ; ".join(SOURCES[k]["page"] for k in ("plrg", "budget_vert", "plf25_nature")) +
                  " ; série longue : realisations/<programme>.json",
        "unite": "euros (crédits de paiement)",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Crédits de paiement de la mission Sécurités, hors statistiques de délinquance. Les dépenses "
                         "de personnel (titre 2) comprennent les cotisations de l'employeur, dont la contribution au "
                         "compte d'affectation spéciale Pensions. Exécution, loi de finances et projet de loi sont "
                         "présentés côte à côte, jamais additionnés.",
        "definitions": {
            "lfi_eur": "crédits votés en loi de finances initiale",
            "lfr_eur": "crédits ouverts ou annulés en loi de finances rectificative",
            "credits_ouverts_eur": "total des crédits ouverts dans l'année (loi de finances, reports, mouvements, fonds "
                                   "de concours et attributions de produits)",
            "depenses_constatees_eur": "dépenses exécutées dans l'année, publiées dans le projet de loi relatif aux "
                                       "résultats de la gestion (PLRG)",
            "titres": "nomenclature par nature de la loi organique : titre 2 personnel, titre 3 fonctionnement, titre 5 "
                      "investissement, titre 6 intervention, titre 7 opérations financières",
            "lignes_techniques_budget_vert": "lignes propres au budget vert (contribution au compte Pensions déduite, "
                                             "fonds de concours, mesures de périmètre) : publiées à part, jamais "
                                             "ajoutées aux actions",
        },
        "programmes": programmes,
        "mission": {"statut": "calculé", "formule": "somme des dépenses constatées des programmes 176, 152, 161 et "
                    "207 de la même annexe du PLRG", "annees": mission},
        "securite_routiere": {
            "lecture": "Crédits rattachés à la sécurité routière dans plusieurs programmes : programme 207, action "
                       "« Sécurité routière » des programmes 176 et 152, programme 751 du compte des amendes. Lignes "
                       "côte à côte, sans total : les périmètres diffèrent.",
            "source": SOURCES["budget_vert"]["page"],
            "lignes": routiere,
        },
        "ecarts": ecarts,
        "ordre": {"regle": "Programmes dans l'ordre 176, 152, 161, 207 ; actions et sous-actions par code ; années "
                           "croissantes."},
    }


# --------------------------------------------------------------------------------------------------------------------
# effectifs : plafonds d'emplois votés (ETPT)

def lire_etpt() -> tuple[dict, dict]:
    codes = {c for c, _ in PROGRAMMES}
    par_annee: dict[int, dict[str, float]] = {}
    l19 = lire_csv(_fichier("etpt_2019"))
    if not l19 or not {"code_programme", "etpt_lfi_2019"} <= set(l19[0]):
        raise DonneeInattendue("LFI 2019 : colonnes non reconnues")
    for li in l19:
        p = str(li["code_programme"]).strip()
        if p in codes:
            par_annee.setdefault(2019, {})[p] = nombre(li["etpt_lfi_2019"])
    for a in (2020, 2021, 2022):
        lignes = lire_csv(_fichier("etpt_2020_2022", f"lfi_{a}_emplois.csv"))
        col = f"ETPT LFI {a}"
        if not lignes or not {"programme", col} <= set(lignes[0]):
            raise DonneeInattendue(f"LFI {a} emplois : colonnes non reconnues")
        for li in lignes:
            p = str(li["programme"]).strip()
            if p in codes:
                par_annee.setdefault(a, {})[p] = nombre(li[col])
    l23 = lire_csv(_fichier("etpt_2023"))
    if not l23 or not {"code_programme", "code_categorie_d_emploi0", "etpt_lfi_2023"} <= set(l23[0]):
        raise DonneeInattendue("LFI 2023 : colonnes non reconnues")
    categories: dict[str, list] = {}
    for li in l23:
        p = str(int(float(li["code_programme"])))
        if p not in codes:
            continue
        v = nombre(li["etpt_lfi_2023"])
        categories.setdefault(p, []).append({"categorie_emploi": li["code_categorie_d_emploi0"], "etpt": v})
        par_annee.setdefault(2023, {})
        par_annee[2023][p] = round(par_annee[2023].get(p, 0.0) + (v or 0.0), 2)
    for p in categories:
        categories[p].sort(key=lambda x: (-(x["etpt"] or 0), _norm(x["categorie_emploi"])))
    return par_annee, categories


def construire_effectifs(budget: dict) -> dict:
    par_annee, categories = lire_etpt()
    annees = sorted(par_annee)
    programmes = []
    for code, libelle in PROGRAMMES:
        serie = [{"annee": a, "etpt": par_annee[a].get(code), "nature": "plafond d'emplois voté en loi de finances "
                  "initiale"} for a in annees]
        prog = next(p for p in budget["programmes"] if p["programme"] == code)
        perso = [{"annee": e["annee"], "depenses_constatees_eur": (e["personnel"] or {}).get("depenses_constatees_eur"),
                  "lfi_eur": (e["personnel"] or {}).get("lfi_eur")} for e in prog["execution"]]
        evolution = []
        for i in range(1, len(serie)):
            a, b = serie[i - 1], serie[i]
            if a["etpt"] is not None and b["etpt"] is not None:
                evolution.append({"de": a["annee"], "a": b["annee"], "etpt": round(b["etpt"] - a["etpt"], 2)})
        programmes.append({"programme": code, "libelle": libelle, "etpt_lfi": serie, "evolution_etpt": evolution,
                           "categories_lfi_2023": categories.get(code, []),
                           "depenses_personnel": perso})
    return {
        "millesime": f"Plafonds d'emplois des lois de finances initiales {annees[0]} à {annees[-1]} ; dépenses de "
                     f"personnel exécutées {ANNEES_PLRG[0]} à {ANNEES_PLRG[-1]}",
        "source": " ; ".join(SOURCES[k]["page"] for k in ("etpt_2019", "etpt_2020_2022", "etpt_2023", "plrg")),
        "unite": "équivalents temps plein travaillé (ETPT) ; euros pour les dépenses de personnel",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Emplois votés (plafonds de la loi de finances initiale), pas les effectifs réellement "
                         "présents. Dernier millésime publié en données ouvertes par programme : LFI 2023. Les "
                         "dépenses de personnel sont un autre millésime et une autre grandeur : aucun ratio n'est "
                         "calculé ici.",
        "definitions": {
            "etpt": "équivalent temps plein travaillé : un agent à temps plein présent toute l'année compte pour 1",
            "evolution_etpt": "différence entre deux plafonds votés successifs, calculée par le site ; un transfert "
                              "d'emplois entre programmes ou une modification de périmètre change aussi ce chiffre",
            "categories_lfi_2023": "catégories d'emplois publiées pour la LFI 2023, libellés de la source",
        },
        "programmes": programmes,
        "annees": annees,
        "limites": [
            "Les plafonds d'emplois 2024, 2025 et 2026 figurent dans les projets annuels de performances (PDF de "
            "budget.gouv.fr), non accessibles aux scripts : ils ne sont pas repris.",
            "Chaque année reprend sa propre source (présentations différentes d'une loi de finances à l'autre), sans "
            "correction de périmètre : une évolution peut venir d'un transfert d'emplois entre programmes.",
            "Le programme 207 n'a pas de plafond d'emplois propre : ses agents relèvent d'autres programmes du "
            "ministère de l'Intérieur.",
        ],
        "ordre": {"regle": "Programmes dans l'ordre 176, 152, 161, 207 ; catégories d'emplois par ETPT décroissant."},
    }


# --------------------------------------------------------------------------------------------------------------------
# compte d'affectation spéciale des amendes

def lire_recettes_compte(annee: int) -> list[dict]:
    lignes = lire_csv(_fichier("plrg", f"plrg_{annee}_cs_recouvrements.csv"))
    if not lignes or not {"Compte", "Section", "Ligne_de_prevision", "Ligne_d'execution", "Total_des_evaluations",
                          "Recouvrements_effectues"} <= set(lignes[0]):
        raise DonneeInattendue(f"recouvrements {annee} : colonnes non reconnues")
    sortie = []
    for li in lignes:
        if _norm(li["Compte"]) != _norm(COMPTE_AMENDES):
            continue
        sec = _code_fin(li["Section"])
        if sec not in SECTIONS_COMPTE:
            raise DonneeInattendue(f"recouvrements {annee} : section « {li['Section']} » inconnue")
        detail = li["Ligne_d'execution"]
        if detail in ("", "0", None):
            # ligne de prévision : porte l'évaluation ; le recouvrement est publié sur les lignes d'exécution
            sortie.append({"section": sec, "ligne": _code_fin(li["Ligne_de_prevision"]),
                           "libelle": _sans_code(li["Ligne_de_prevision"]), "niveau": "prevision",
                           "evaluation_eur": _eur(li["Total_des_evaluations"]),
                           "recouvrement_publie_eur": _eur(li["Recouvrements_effectues"])})
        else:
            sortie.append({"section": sec, "ligne": _code_fin(detail), "ligne_prevision": _code_fin(li["Ligne_de_prevision"]),
                           "libelle": _sans_code(detail), "niveau": "execution",
                           "evaluation_eur": _eur(li["Total_des_evaluations"]),
                           "recouvrement_eur": _eur(li["Recouvrements_effectues"])})
    if not sortie:
        raise DonneeInattendue(f"recouvrements {annee} : compte des amendes absent")
    return sortie


def lire_depenses_compte(annee: int) -> list[dict]:
    lignes = lire_csv(_fichier("plrg", f"plrg_{annee}_cs_cp.csv"))
    if not lignes or not set(("Mission", "Programme") + COLONNES_CP) <= set(lignes[0]):
        raise DonneeInattendue(f"comptes spéciaux {annee} : colonnes non reconnues")
    sortie = []
    for li in lignes:
        if _norm(li["Mission"]) != _norm(COMPTE_AMENDES):
            continue
        p = code_programme(li["Programme"])
        if p not in PROGRAMMES_COMPTE:
            raise DonneeInattendue(f"comptes spéciaux {annee} : programme « {li['Programme']} » inattendu")
        sortie.append({"programme": p, "libelle": _sans_code(li["Programme"]), "lfi_eur": _eur(li["LFI"]),
                       "lfr_eur": _eur(li["LFR"]), "credits_ouverts_eur": _eur(li["Total_CP_Ouverts"]),
                       "depenses_constatees_eur": _eur(li["Depenses_constatees"])})
    sortie.sort(key=lambda x: x["programme"])
    if [x["programme"] for x in sortie] != list(PROGRAMMES_COMPTE):
        raise DonneeInattendue(f"comptes spéciaux {annee} : programmes du compte {[x['programme'] for x in sortie]}")
    return sortie


def lire_situation_compte(annee: int) -> dict:
    lignes = lire_csv(_fichier("plrg", f"plrg_{annee}_cs_comptable.csv"))
    li = next((x for x in lignes if _norm(x.get("Mission")) == _norm(COMPTE_AMENDES)), None)
    if li is None:
        raise DonneeInattendue(f"situation comptable {annee} : compte des amendes absent")
    be = (nombre(li["BE_Credit"]) or 0.0) - (nombre(li["BE_Debit"]) or 0.0)
    bs = (nombre(li["BS_Credit"]) or 0.0) - (nombre(li["BS_Debit"]) or 0.0)
    return {"annee": annee, "solde_entree_eur": round(be, 2), "recettes_eur": _eur(li["OP_Recettes"]),
            "depenses_eur": _eur(li["OP_Depenses"]), "solde_sortie_eur": round(bs, 2)}


def construire_amendes(bv: list[dict]) -> dict:
    annees = []
    for annee in ANNEES_PLRG:
        recettes = lire_recettes_compte(annee)
        depenses = lire_depenses_compte(annee)
        situation = lire_situation_compte(annee)
        execution = [r for r in recettes if r["niveau"] == "execution"]
        par_section = []
        for sec, info in SECTIONS_COMPTE.items():
            prev = [r for r in recettes if r["section"] == sec and r["niveau"] == "prevision"]
            ex = [r for r in execution if r["section"] == sec]
            deps = [d for d in depenses if d["programme"] in info["programmes"]]
            par_section.append({
                "section": sec, "libelle": info["libelle"], "programmes": info["programmes"],
                "evaluation_eur": _somme(r["evaluation_eur"] for r in prev),
                "recouvrement_eur": _somme(r["recouvrement_eur"] for r in ex),
                "depenses_constatees_programmes_eur": _somme(d["depenses_constatees_eur"] for d in deps)})
        tot_rec = _somme(r["recouvrement_eur"] for r in execution)
        tot_dep = _somme(d["depenses_constatees_eur"] for d in depenses)
        for d in depenses:
            d["part_depenses_pct"] = round(100 * d["depenses_constatees_eur"] / tot_dep, 2) \
                if d["depenses_constatees_eur"] is not None and tot_dep else None
        controles = {
            "recettes_lignes_eur": tot_rec, "recettes_situation_comptable_eur": situation["recettes_eur"],
            "ecart_recettes_eur": None if None in (tot_rec, situation["recettes_eur"]) else round(tot_rec - situation["recettes_eur"], 2),
            "depenses_programmes_eur": tot_dep, "depenses_situation_comptable_eur": situation["depenses_eur"],
            "ecart_depenses_eur": None if None in (tot_dep, situation["depenses_eur"]) else round(tot_dep - situation["depenses_eur"], 2),
        }
        annees.append({"annee": annee, "recettes": recettes, "recettes_par_section": par_section,
                       "recouvrements_total_eur": tot_rec, "depenses": depenses, "depenses_total_eur": tot_dep,
                       "situation": situation, "controles": controles,
                       "source": f"PLRG {annee}, annexe 2 (recouvrements, état CP, situation comptable des comptes spéciaux)"})
    actions = [{"programme": x["programme"], "code": x["code"], "libelle": x["libelle"], **{k: x[k] for k in COLS_BV}}
               for x in bv if x["programme"] in PROGRAMMES_COMPTE]
    return {
        "millesime": f"Exécution {ANNEES_PLRG[0]} à {ANNEES_PLRG[-1]} (PLRG) ; actions : exécution 2024, LFI 2025, "
                     "PLF 2026 (budget vert)",
        "source": f"{SOURCES['plrg']['page']} ; {SOURCES['budget_vert']['page']}",
        "unite": "euros",
        "date_sources": date_sources(DOMAINE),
        "compte": COMPTE_AMENDES,
        "avertissement": "Recettes et dépenses du compte d'affectation spéciale qui reçoit une partie du produit des "
                         "amendes de la circulation et du stationnement. Les recettes d'une année ne correspondent pas "
                         "une à une aux dépenses de la même année : l'écart passe par le solde du compte.",
        "structure": {
            "texte": "loi n° 2005-1719 du 30 décembre 2005 de finances pour 2006, article 49 (modifié)",
            "sections": [{"section": s, **v} for s, v in SECTIONS_COMPTE.items()],
            "lecture": "La section « Contrôle automatisé » finance le programme 751 ; la section « Circulation et "
                       "stationnement routiers » finance les programmes 753, 754 et 755.",
        },
        "definitions": {
            "evaluation_eur": "recette prévue en loi de finances (total des évaluations)",
            "recouvrement_eur": "recette effectivement encaissée dans l'année",
            "recouvrement_publie_eur": "valeur publiée sur la ligne de prévision ; le montant encaissé figure sur les "
                                       "lignes d'exécution qui la détaillent",
            "solde": "situation comptable du compte : solde créditeur en début et en fin d'année",
            "part_depenses_pct": "part de chaque programme dans les dépenses constatées du compte, calculée par le site",
        },
        "programmes": [
            {"programme": "751", "libelle": "Structures et dispositifs de sécurité routière"},
            {"programme": "753", "libelle": "Contrôle et modernisation de la politique de la circulation et du "
                                            "stationnement routiers"},
            {"programme": "754", "libelle": "Contribution à l'équipement des collectivités territoriales pour "
                                            "l'amélioration des transports en commun, de la sécurité et de la "
                                            "circulation routières"},
            {"programme": "755", "libelle": "Désendettement de l'État"}],
        "annees": annees,
        "actions_budget_vert": actions,
        "limites": [
            "Seule la part des amendes versée à ce compte figure ici. La part du produit des radars versée "
            "directement à l'Agence de financement des infrastructures de transport de France et les amendes "
            "rattachées au budget général ne sont pas dans les annexes lues.",
            "Le programme 755 « Désendettement de l'État » reverse des recettes au budget général : il ne finance "
            "pas d'action de sécurité routière.",
        ],
        "ordre": {"regle": "Années croissantes ; sections et programmes par code ; recettes dans l'ordre de l'annexe."},
    }


# --------------------------------------------------------------------------------------------------------------------
# index

def construire_index(budget: dict, effectifs: dict, amendes: dict, tailles: dict) -> dict:
    manifeste = _manifeste()
    sources = []
    for cle, s in SOURCES.items():
        e = manifeste.get(s["id_catalogue"], {})
        sources.append({"id": cle, "id_catalogue": s["id_catalogue"], "titre": s["titre"], "page": s["page"],
                        "licence": s["licence"], "collecte_le": e.get("collecte_le"),
                        "fichiers_collectes": len(e.get("fichiers", [])) or None})
    dernier = ANNEES_PLRG[-1]
    reperes_prog = []
    for p in budget["programmes"]:
        e = next(x for x in p["execution"] if x["annee"] == dernier)
        n = next(x for x in p["nature"] if x["annee"] == dernier)
        eff = next(x for x in effectifs["programmes"] if x["programme"] == p["programme"])
        reperes_prog.append({
            "programme": p["programme"], "libelle": p["libelle"], "annee": dernier,
            "depenses_constatees_eur": e["total"]["depenses_constatees_eur"],
            "par_titre": [{"titre": t["titre"], "groupe": t["groupe"], "eur": t["eur"], "part_pct": t["part_pct"]}
                          for t in n["titres"]],
            "etpt_lfi": eff["etpt_lfi"][-1]["etpt"], "annee_etpt": eff["etpt_lfi"][-1]["annee"]})
    a = next(x for x in amendes["annees"] if x["annee"] == dernier)
    return {
        "millesime": f"Exécution {ANNEES_PLRG[0]} à {dernier} ; actions jusqu'au PLF 2026 ; emplois LFI "
                     f"{effectifs['annees'][0]} à {effectifs['annees'][-1]}",
        "source": " ; ".join(s["page"] for s in SOURCES.values()),
        "unite": "voir chaque fichier",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Crédits publiés de la police nationale, de la gendarmerie nationale, de la sécurité civile, "
                         "de la sécurité routière et du compte des amendes. Aucune statistique de délinquance, aucune "
                         "donnée individuelle. Chaque fichier donne sa source, son millésime et ses contrôles.",
        "fichiers": [
            {"fichier": "securite_interieure/budget.json", "contenu": "crédits par programme, par titre et "
             "catégorie, par action et sous-action ; série longue ; sécurité routière", **tailles["budget"]},
            {"fichier": "securite_interieure/effectifs.json", "contenu": "plafonds d'emplois votés (ETPT) par "
             "programme, catégories d'emplois, dépenses de personnel", **tailles["effectifs"]},
            {"fichier": "securite_interieure/amendes.json", "contenu": "recettes des amendes versées au compte "
             "Contrôle de la circulation et du stationnement routiers, dépenses par programme, solde", **tailles["amendes"]},
        ],
        "reperes": {
            "programmes": reperes_prog,
            "mission": next(m for m in budget["mission"]["annees"] if m["annee"] == dernier) | {"statut": "calculé"},
            "amendes": {"annee": dernier, "recouvrements_eur": a["recouvrements_total_eur"],
                        "depenses_eur": a["depenses_total_eur"], "solde_fin_eur": a["situation"]["solde_sortie_eur"]},
        },
        "limites": [
            "Projets et rapports annuels de performances (PDF de budget.gouv.fr) : page de protection contre les "
            "robots, non contournée ; les indicateurs de performance des programmes sont dans "
            "realisations/<programme>.json.",
            "Emplois : plafonds votés de la LFI 2019 à la LFI 2023 (le jeu ouvert par programme le plus récent est "
            "celui de la LFI 2023).",
            "Amendes : seule la part versée au compte d'affectation spéciale est couverte.",
            "Aucune statistique de délinquance : hors du sujet du site.",
        ],
        "voir_aussi": ["realisations/176.json", "realisations/152.json", "realisations/161.json",
                       "realisations/207.json", "nature/176.json", "effectifs/176.json", "programmes/176.json"],
        "sources": sources,
        "sources_inaccessibles": [
            {"source": "budget.gouv.fr, projets et rapports annuels de performances 2026 de la mission Sécurités",
             "motif": "page de protection contre les robots (Incapsula) constatée le 18/11/2026 : non contournée"},
            {"source": "Plafonds d'emplois par programme des LFI 2024, 2025 et 2026",
             "motif": "aucun jeu ouvert trouvé sur data.economie.gouv.fr ni sur data.gouv.fr (recherche du 18/11/2026)"},
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }


def _ecrire(chemin: Path, doc: dict) -> dict:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    octets = len(texte.encode("utf-8"))
    if octets > 1_000_000:
        raise DonneeInattendue(f"{chemin.name} dépasse 1 Mo ({octets} octets)")
    chemin.write_text(texte, encoding="utf-8")
    return {"octets": octets}


def produire(sortie: Path = SORTIE) -> None:
    budget = construire_budget()
    effectifs = construire_effectifs(budget)
    amendes = construire_amendes(lire_budget_vert())
    tailles = {"budget": _ecrire(sortie / "budget.json", budget),
               "effectifs": _ecrire(sortie / "effectifs.json", effectifs),
               "amendes": _ecrire(sortie / "amendes.json", amendes)}
    _ecrire(sortie / "index.json", construire_index(budget, effectifs, amendes, tailles))
    print(f"securite_interieure : 4 fichiers écrits dans {sortie}", file=sys.stderr)


def collecter() -> int:
    ids = [s["id_catalogue"] for s in SOURCES.values()]
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *ids, "--timeout", "560"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("collecter")
    p = sp.add_parser("produire")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.cmd == "collecter":
        return collecter()
    produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
