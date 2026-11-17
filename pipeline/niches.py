"""Dépenses fiscales et niches sociales : l'argent que l'État et la Sécurité sociale renoncent à percevoir.

Entrées : entrepôt brut data/lake/ (non versionné) et site/data/arbre/racine.json (arbre État, exécution 2024).
Sorties (chaque fichier porte `millesime` et `source`) :
  site/data/niches/mesures.json      chaque dépense fiscale : identifiant, libellé, impôt, programme LOLF, coût par
                                     année 2019 à 2026 (constaté ou estimé, « nc », « ε » et « - » gardés tels quels),
                                     bénéficiaires (nombre, nature), méthode de chiffrage, création, extinction,
                                     note du comité d'évaluation de 2011
  site/data/niches/programmes.json   dépense budgétaire + dépense fiscale par programme, mission et grand poste
  site/data/niches/sociales.json     niches sociales : exonérations et exemptions d'assiette (PLFSS 2026 annexe 4),
                                     série Urssaf par mesure 2019-2025
  site/data/niches/index.json        totaux par année, top, par impôt, couverture du rattachement, sources,
                                     sources inaccessibles, bénéficiaires nommés, recherche préalable

Sources (annexe « Évaluation des voies et moyens, tome II » de chaque PLF, une édition par année) :
  - PLF 2021, 2022, 2023 : classeurs de la DGFiP publiés sur data.economie.gouv.fr (onglets Chiffrages,
    Bénéficiaires, Méthodologie, Références juridiques, Echéances, Programme de rattachement) ;
  - PLF 2024, 2025, 2026 : PDF de l'annexe, miroirs de l'Assemblée nationale (budget.gouv.fr répond 403 aux scripts :
    noté, jamais contourné) ; une fiche par mesure, lue avec `pdftotext -layout` (poppler-utils).
Une année est lue dans l'édition la plus récente qui la couvre : réalisation N-2 (« constaté »), prévisions N-1 et N
(« estimé »). Les montants sont en millions d'euros comme à la source ; « nc » (non chiffré), « ε » (moins de 0,5 M€)
et « - » (aucun effet budgétaire) restent des chaînes, avec `meur` à null : jamais 0.

Bénéficiaires nommés : aucun. Les montants par entreprise d'une dépense fiscale (crédit d'impôt recherche compris)
relèvent du secret professionnel en matière fiscale et ne sont pas publiés ; seuls les agrégats (nombre de bénéficiaires
par mesure, publiés dans le tome II) le sont. Aucune personne physique n'est nommée.

Commandes :
  python pipeline/niches.py collecter     # réseau : documents manquants (un refus 401/403/429 est noté, jamais contourné)
  python pipeline/niches.py produire      # sans réseau : écrit site/data/niches/
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "fiscalite" / "niches_vm"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "niches"
ARBRE = SITE / "arbre" / "racine.json"
HEADERS = {"User-Agent": "ou-vont-mes-impots/0.1 (projet citoyen open source)"}
ANNEES = list(range(2019, 2027))
TAILLE_MAX = 5_000_000
JETONS = ("nc", "ε", "-")
SENS_JETONS = {"nc": "non chiffré", "ε": "inférieur à 0,5 M€, non chiffré", "-": "aucun effet budgétaire"}

AN = "https://www.assemblee-nationale.fr/dyn/contenu/visualisation"
# --- Sources ----------------------------------------------------------------------------------------------------
EDITIONS = {
    2021: {"type": "xlsx",
           "chemin": LAKE / "etat" / "economie__projet-de-loi-de-finances-pour-2021-plf-2021-donnees-du-plf-et-des-annexes-proje"
           / "PLF_2021_Liste_des_depenses_fiscales.xlsx",
           "url": "https://data.economie.gouv.fr/explore/dataset/projet-de-loi-de-finances-pour-2021-plf-2021-donnees-du-plf-et-des-annexes-proje/",
           "titre": "PLF 2021, Voies et moyens tome II, liste des dépenses fiscales (classeur DGFiP)",
           "producteur": "DGFiP / direction du budget, data.economie.gouv.fr", "licence": "Licence Ouverte 2.0"},
    2022: {"type": "xlsx",
           "chemin": LAKE / "etat" / "economie__projet-de-loi-de-finances-pour-2022-plf-2022-donnees-du-plf-et-des-annexes-proje"
           / "PLF_2022_Liste_depenses_fiscales.xlsx",
           "url": "https://data.economie.gouv.fr/explore/dataset/projet-de-loi-de-finances-pour-2022-plf-2022-donnees-du-plf-et-des-annexes-proje/",
           "titre": "PLF 2022, Voies et moyens tome II, liste des dépenses fiscales (classeur DGFiP)",
           "producteur": "DGFiP / direction du budget, data.economie.gouv.fr", "licence": "Licence Ouverte 2.0"},
    2023: {"type": "xlsx",
           "chemin": LAKE / "fiscalite" / "economie__plf2023_voies_et_moyens_t2_liste_des_depenses_fiscales"
           / "PLF2023_voies_et_moyens_t2_liste_des_depenses_fiscales.xlsx",
           "url": "https://data.economie.gouv.fr/explore/dataset/plf2023_voies_et_moyens_t2_liste_des_depenses_fiscales/",
           "titre": "PLF 2023, Voies et moyens tome II, liste des dépenses fiscales (classeur DGFiP)",
           "producteur": "DGFiP / direction du budget, data.economie.gouv.fr", "licence": "Licence Ouverte 2.0"},
    2024: {"type": "pdf", "chemin": BRUT / "vm2_plf2024.pdf",
           "url": f"{AN}/705208/file/Evaluation%20des%20voies%20et%20moyens%20-%20Tome%20II.pdf",
           "titre": "PLF 2024, Évaluation des voies et moyens tome II : les dépenses fiscales (PDF, 251 p.)",
           "producteur": "direction du budget / DGFiP, miroir Assemblée nationale",
           "licence": "document administratif public (CRPA L. 321-1), réutilisation libre avec mention"},
    2025: {"type": "pdf", "chemin": BRUT / "vm2_plf2025.pdf",
           "url": "https://www2.assemblee-nationale.fr/static/17/Annexes-DL/PLF-2025/Voies_et_moyens_Tome_2_2025.pdf",
           "titre": "PLF 2025, Évaluation des voies et moyens tome II : dépenses fiscales (PDF, 247 p.)",
           "producteur": "direction du budget / DGFiP, miroir Assemblée nationale",
           "licence": "document administratif public (CRPA L. 321-1), réutilisation libre avec mention"},
    2026: {"type": "pdf", "chemin": BRUT / "vm2_plf2026.pdf",
           "url": f"{AN}/1087933/file/Voies_et_moyens_Tome_2_2026.pdf",
           "titre": "PLF 2026, Évaluation des voies et moyens tome II : dépenses fiscales (PDF, 252 p.)",
           "producteur": "direction du budget / DGFiP, miroir Assemblée nationale",
           "licence": "document administratif public (CRPA L. 321-1), réutilisation libre avec mention"},
}
AUTRES = {
    "plfss2026_annexe4": {
        "chemin": BRUT / "plfss2026_annexe4.pdf",
        "url": f"{AN}/1088679/file/PLFSS2026-Annexe4-20251014-183718-59-11_avec%20couverture-2.pdf",
        "titre": "PLFSS 2026, annexe 4 : présentation des mesures de réduction et d'exonération de cotisations et "
                 "contributions et de leur compensation (ex-annexe 5) : tableaux 9, 13 et 14",
        "producteur": "direction de la sécurité sociale, miroir Assemblée nationale",
        "licence": "document administratif public (CRPA L. 321-1), réutilisation libre avec mention"},
    "urssaf_exos": {
        "chemin": LAKE / "aides_entreprises" / "aides_urssaf_exos_secteur_prive_france_entiere_par_me.parquet",
        "url": "https://open.urssaf.fr/explore/dataset/exos-secteur-prive-france-entiere-par-mesures/",
        "titre": "Urssaf Caisse nationale, montants des exonérations de cotisations, secteur privé, France entière, "
                 "par mesure (collecte/catalogue.json)",
        "producteur": "Urssaf Caisse nationale", "licence": "Licence Ouverte 2.0"},
    "igf2011": {
        "chemin": BRUT / "igf2011_scores.csv",
        "url": "https://raw.githubusercontent.com/michalkolb01/tax-expenditures-france-thesis/"
               "bea78166fe5064cefa3ca37b24fd4574af19c0ee/data/intermediate/guillaume_all.csv",
        "titre": "Comité d'évaluation des dépenses fiscales et des niches sociales (rapport Guillaume, IGF, juin 2011), "
                 "note de 0 à 3 de chaque mesure (annexe IV), relevé par M. Kolb (mémoire Sciences Po, dépôt MIT, "
                 "commit bea7816 du 13/11/2026), vérifié contre les totaux du rapport : 125 / 99 / 46 / 69 notées, "
                 "131 non évaluées",
        "producteur": "IGF (rapport) ; relevé M. Kolb", "licence": "rapport public ; relevé sous licence MIT"},
}

SOURCES_INACCESSIBLES = [
    {"source": "budget.gouv.fr (documents budgétaires, Voies et moyens tome II, classeurs PLF 2024 à 2026)",
     "url": "https://www.budget.gouv.fr/documentation/documents-budgetaires-lois",
     "constat": "HTTP 403 le 17/11/2026 (protection anti-robots)",
     "effet": "PDF lus sur les miroirs de l'Assemblée nationale ; classeurs PLF 2024-2026 non publiés sur data.economie"},
    {"source": "performance-publique.budget.gouv.fr",
     "url": "https://www.performance-publique.budget.gouv.fr/",
     "constat": "hôte injoignable depuis le proxy de collecte le 17/11/2026", "effet": "aucun"},
    {"source": "data.economie.gouv.fr, jeu plf-2024-vm-tome-2_depenses-fiscales",
     "url": "https://data.economie.gouv.fr/explore/dataset/plf-2024-vm-tome-2_depenses-fiscales/",
     "constat": "seul l'onglet « Explication détaillée » est publié (ni chiffrages, ni bénéficiaires)",
     "effet": "PLF 2024 lu dans le PDF de l'annexe"},
]

RECHERCHE_PUBLIQUE = [
    {"nom": "data.economie.gouv.fr / data.gouv.fr : classeurs Voies et moyens tome II (PLF 2020 à 2023)",
     "url": "https://data.economie.gouv.fr/explore/?q=depenses+fiscales",
     "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0",
     "date": "mises à jour 2019-10-02 à 2023-03-10",
     "usage": "éditions PLF 2021, 2022, 2023 (2019 à 2023)"},
    {"nom": "data.economie.gouv.fr : plf-2024-vm-tome-2_depenses-fiscales",
     "url": "https://data.economie.gouv.fr/explore/dataset/plf-2024-vm-tome-2_depenses-fiscales/",
     "verdict": "inspiration seulement", "licence": "Licence Ouverte 2.0", "date": "2023-10-03",
     "usage": "libellés seulement : chiffrages absents"},
    {"nom": "michalkolb01/tax-expenditures-france-thesis (panel Voies et moyens 2009-2026, notes IGF 2011)",
     "url": "https://github.com/michalkolb01/tax-expenditures-france-thesis",
     "verdict": "à adapter", "licence": "MIT", "date": "dernier commit 2026-11-13 (bea7816)",
     "usage": "notes du comité de 2011 reprises telles quelles (guillaume_all.csv) ; son panel 2020-2026 convertit "
              "« nc » et « ε » en valeurs manquantes et ne garde ni programme ni méthode : relu à la source ; sa "
              "structure des classeurs DGFiP (4 onglets joints sur le numéro) a servi de modèle"},
    {"nom": "maximedns5/Impots (microsimulation, agrégats CIR)",
     "url": "https://github.com/maximedns5/Impots", "verdict": "inspiration seulement", "licence": "AGPL-3.0",
     "date": "dernier commit 2026-11-16",
     "usage": "rappel : la créance de CIR d'un millésime n'est pas la dépense fiscale d'une année (avertissement repris)"},
    {"nom": "TGagneDube/depenses_fiscales", "url": "https://github.com/TGagneDube/depenses_fiscales",
     "verdict": "inspiration seulement", "licence": "aucune déclarée", "date": "dernier commit 2026-09-01",
     "usage": "outil Québec et Canada (CFFP) : hors champ"},
    {"nom": "Fipeco, fiches « niches fiscales et sociales »", "url": "https://fipeco.fr/pdf/Niches2023.pdf",
     "verdict": "inspiration seulement", "licence": "droits réservés", "date": "2023",
     "usage": "présentation (dépense fiscale et niche sociale côte à côte) ; aucun chiffre repris"},
    {"nom": "IPP, barèmes IPP (data.gouv.fr)", "url": "https://www.ipp.eu/baremes-ipp/",
     "verdict": "inspiration seulement", "licence": "Licence Ouverte 2.0", "date": "collecte du 15/11/2026",
     "usage": "barèmes, pas de coût des mesures"},
    {"nom": "Cour des comptes, « La gestion des dépenses fiscales en faveur du logement » (2019) et « L'efficience "
            "des dépenses fiscales relatives au développement durable » (2016), données sur data.gouv.fr",
     "url": "https://www.data.gouv.fr/fr/datasets/5c99ef89634f41459dedda50/",
     "verdict": "inspiration seulement", "licence": "Licence Ouverte 2.0", "date": "2019-03-26 ; 2017-09-05",
     "usage": "graphiques des rapports (archives zip) : citées comme évaluations, pas de chiffre par mesure repris"},
    {"nom": "MESR, liste des organismes agréés au crédit d'impôt recherche (data.gouv.fr)",
     "url": "https://www.data.gouv.fr/fr/datasets/63aa5fcc55fdea38a39dde9a/",
     "verdict": "inspiration seulement", "licence": "Licence Ouverte 2.0", "date": "2026-06-18",
     "usage": "prestataires agréés, pas les bénéficiaires du crédit : non publié ici"},
]

BENEFICIAIRES_NOMMES = {
    "nommes": 0,
    "constat": "Aucune liste de bénéficiaires nommés n'est publiée pour les dépenses fiscales : le montant d'un "
               "crédit ou d'une réduction d'impôt par entreprise est couvert par le secret professionnel en matière "
               "fiscale (réponse ministérielle à la question écrite n° 26147, JO AN du 14/04/2020, pour le CICE ; même "
               "régime pour le crédit d'impôt recherche). Le MESR publie des agrégats du CIR (bilans annuels par "
               "taille et secteur) ; le tome II publie le nombre de bénéficiaires par mesure, repris ici.",
    "credit_impot_recherche": {"mesure": "200302", "liste_publiee": False,
                               "agregats": "nombre d'entreprises bénéficiaires par édition (champ beneficiaires)",
                               "source_agregats": "https://www.enseignementsup-recherche.gouv.fr/ (bilans du CIR)"},
    "reference": "https://www.assemblee-nationale.fr/dyn/15/questions/QANR5L15QE26147",
}

# Totaux publiés dans les tomes II (M€, tableau par impôt de la sous-partie « Chiffres clés »), revérifiés à chaque
# production contre le texte du PDF. Constaté : la somme des fiches doit les retrouver à 1 M€ près. Estimé : la DGFiP
# y impute une prévision aux mesures dont la fiche porte « nc » ; l'écart est publié, jamais lissé.
TOTAUX_PUBLIES = {
    2022: (2024, "Le montant des dépenses fiscales s’est élevé à 85,6 Md€ en 2022", 85616),
    2023: (2025, "Le montant des dépenses fiscales s’est élevé à 82,9 Md€ en 2023", 82923),
    2024: (2026, "Le montant des dépenses fiscales s’est élevé à 89,4 Md€ en 2024", 89406),
    2025: (2026, "s’élèverait à 91,8 Md€ en 2025", 91834),
    2026: (2026, "et 88,3 Md€ en 2026", 88269),
}
TABLEAUX_TOTAUX = {2024: "Total 85 616 81 344 78 741", 2025: "Total 82 923 83 292 85 098",
                   2026: "Total 89 406 91 834 88 269"}
TOTAL_MISSIONS_2026 = ("Total                                                           88 269           465", 88269, 465)
TEXTES_PLFSS = [
    "Total                                                 74,7             71,8              -3,8%        71,5",
    "TOTAL EXEMPTIONS D'ASSIETTE",
]

# --- Utilitaires ----------------------------------------------------------------------------------------------


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def espaces(s) -> str:
    s = unicodedata.normalize("NFC", str(s)).replace(" ", " ").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > TAILLE_MAX:
        raise SystemExit(f"{path} dépasse 5 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def code6(v) -> str | None:
    s = espaces(v).split(".")[0] if v is not None else ""
    return s.zfill(6) if re.fullmatch(r"\d{4,6}", s) else None


def valeur(v) -> dict | None:
    """Cellule de chiffrage -> {"brut", "meur"}. « nc », « ε », « - » gardés (meur null) ; absent -> None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return {"brut": str(int(v)) if float(v).is_integer() else str(v), "meur": float(v)}
    s = espaces(v)
    if s == "":
        return None
    s2 = s.replace(" ", "")
    if s2 in ("ε", "e", "€"):  # « ε » mal encodé dans certains classeurs
        return {"brut": "ε", "meur": None}
    if s2.lower() == "nc":
        return {"brut": "nc", "meur": None}
    if s2 in ("-", "–", "—"):
        return {"brut": "-", "meur": None}
    m = re.fullmatch(r"-?\d+(?:,\d+)?", s2)
    if m:
        x = float(s2.replace(",", "."))
        return {"brut": s2, "meur": x}
    return {"brut": s, "meur": None}


def nombre_beneficiaires(nature, nombre) -> dict:
    n = espaces(nombre) if nombre is not None else ""
    nat = espaces(nature) if nature is not None else ""
    n2 = n.replace(" ", "")
    out = {"nombre": int(n2) if re.fullmatch(r"\d+", n2) else None, "nature": nat or None}
    if out["nombre"] is None and n:
        out["brut"] = n
    return out


def annee_texte(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = espaces(v)
    return s or None


# --- Lecture des classeurs DGFiP (PLF 2021 à 2023) --------------------------------------------------------------


def _lignes(ws):
    for r in ws.iter_rows(values_only=True):
        r = list(r)
        c = code6(r[3]) if len(r) > 3 else None
        if c:
            yield c, r


def lire_xlsx(chemin: Path, plf: int) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    feuilles = {espaces(ws.title).lower(): ws for ws in wb.worksheets}

    def f(prefixe):
        for k, ws in feuilles.items():
            if k.startswith(prefixe):
                return ws
        raise KeyError(f"{chemin.name} : onglet {prefixe} absent")

    mes: dict[str, dict] = {}
    annees = [plf - 2, plf - 1, plf]
    for c, r in _lignes(f("chiffrages")):
        mes[c] = {"code": c, "impot": espaces(r[0]) or None, "sous_categorie": espaces(r[1]) or None,
                  "libelle": espaces(r[4]),
                  "couts": {str(a): valeur(r[5 + i]) for i, a in enumerate(annees)}}
    for c, r in _lignes(f("explication")):
        if c in mes and r[5]:
            mes[c]["finalite"] = re.sub(r"^Finalit[ée]\s*:\s*", "", espaces(r[5])) or None
    for c, r in _lignes(f("bénéficiaires")):
        if c in mes:
            mes[c]["beneficiaires"] = nombre_beneficiaires(r[5], r[6])
    for c, r in _lignes(f("méthodologie")):
        if c in mes:
            mes[c]["fiabilite"] = espaces(r[5]) or None if r[5] else None
            mes[c]["methode"] = espaces(r[6]) or None if r[6] else None
    for c, r in _lignes(f("références")):
        if c in mes:
            mes[c]["norme"] = espaces(r[5]) if r[5] else None
            ref = " ".join(espaces(x) for x in r[6:8] if x)
            mes[c]["reference"] = ref or None
    for c, r in _lignes(f("echéances") if any(k.startswith("echéances") for k in feuilles) else f("échéances")):
        if c in mes:
            mes[c].update({"creation": annee_texte(r[5]), "modification": annee_texte(r[6]),
                           "fin_fait_generateur": annee_texte(r[7]), "fin_incidence": annee_texte(r[8]),
                           "suppression": annee_texte(r[9])})
    for c, r in _lignes(f("programme")):
        if c not in mes:
            continue
        p = espaces(r[5]).split(".")[0] if r[5] is not None else ""
        if not re.fullmatch(r"\d{1,3}", p):
            continue
        p = str(int(p))
        principal = "principal" in espaces(r[7] or "").lower()
        entree = {"code": p, "libelle": espaces(r[6]) if r[6] else None}
        if principal and "programme" not in mes[c]:
            mes[c]["programme"] = entree
        elif not principal:
            mes[c].setdefault("programmes_subsidiaires", []).append(entree)
    return mes


# --- Lecture des PDF (PLF 2024 à 2026) --------------------------------------------------------------------------


def texte_pdf(chemin: Path) -> str:
    if not shutil.which("pdftotext"):
        raise SystemExit("pdftotext (poppler-utils) requis pour lire les tomes II en PDF")
    r = subprocess.run(["pdftotext", "-layout", str(chemin), "-"], capture_output=True, check=True)
    return r.stdout.decode("utf-8", "replace")


ENTETE_FICHE = re.compile(r"^\s{0,20}(\d{6})\s+[–-]\s+(\S.*)$")
LIGNE_PARASITE = re.compile(r"(Annexe au PLF|Voies et moyens tome II|Liste des dépenses fiscales|^\s*PLF 20\d\d\s+\d+\s*$|"
                            r"^\s*\d{1,3}\s+Annexe au PLF|^\s*\d{1,3}\s*$)")
CHAMPS = [("Bénéficiaires", "beneficiaires"), ("Fiabilité du réalisé", "fiabilite"),
          ("Norme fiscale de référence", "norme"), ("Méthode de chiffrage", "methode"),
          ("Référence", "reference"), ("Mission et programme", "mission_programme")]


def categories_toc(texte: str) -> list[str]:
    lignes = texte.splitlines()
    for i, l in enumerate(lignes[:200]):
        if l.strip().startswith("Liste des dépenses fiscales"):
            cats = []
            for l2 in lignes[i + 1:i + 20]:
                m = re.match(r"^\s{2,}(\S.*?)\s{3,}\d+\s*$", l2)
                if not m:
                    break
                cats.append(espaces(m.group(1)))
            return cats
    return []


def separer_colonnes(s: str) -> list[str]:
    return [x for x in re.split(r"\s{2,}", s.strip()) if x]


def lire_fiche(code: str, lignes: list[str], plf: int) -> dict:
    """Une fiche du tome II (lignes de pdftotext -layout) -> enregistrement."""
    titre = [ENTETE_FICHE.match(lignes[0]).group(2)]
    i = 1
    while i < len(lignes) and not lignes[i].strip().startswith(("Finalité", "Impact budgétaire")):
        if lignes[i].strip() and not LIGNE_PARASITE.search(lignes[i]):
            titre.append(lignes[i].strip())
        i += 1
    rec = {"code": code, "libelle": espaces(" ".join(titre)), "couts": {}}
    corps = [l for l in lignes[i:] if not LIGNE_PARASITE.search(l)]
    annees = None
    for l in corps:
        s = l.strip()
        if s.startswith("Finalité"):
            rec["finalite"] = espaces(re.sub(r"^Finalité\s*:\s*", "", s)) or None
        m = re.match(r"^\s*(?:Réalisation\s+)?.*?Création\s+(\S.*)$", l)
        if "Création" in l and m:
            rec["creation"] = espaces(m.group(1))
        if re.search(r"\bModification\b", l):
            m = re.search(r"Modification\s+(\S.*)$", l)
            rec["modification"] = espaces(m.group(1)) if m else None
        if "Fin du fait générateur" in l:
            gauche, droite = l.split("Fin du fait générateur", 1)
            annees = [int(x) for x in re.findall(r"\b(20\d\d)\b", gauche)]
            rec["fin_fait_generateur"] = espaces(droite) or None
        if "Fin d'incidence budgétaire" in l or "Fin d’incidence budgétaire" in l:
            gauche, droite = re.split(r"Fin d.incidence budgétaire", l, maxsplit=1)
            rec["fin_incidence"] = espaces(droite) or None
            vals = separer_colonnes(gauche)
            if annees is None or len(annees) != 3:
                raise ValueError(f"PLF {plf}, {code} : années de chiffrage illisibles")
            if len(vals) != 3:
                raise ValueError(f"PLF {plf}, {code} : {len(vals)} montants lus ({vals!r})")
            if annees != [plf - 2, plf - 1, plf]:
                raise ValueError(f"PLF {plf}, {code} : années {annees}")
            rec["couts"] = {str(a): valeur(v) for a, v in zip(annees, vals)}
    # champs étiquetés (valeur à droite, suite éventuelle sur les lignes sans étiquette)
    courant = None
    vals: dict[str, list[str]] = {}
    for l in corps:
        s = l.strip()
        trouve = False
        for etiquette, cle in CHAMPS:
            if s.startswith(etiquette) and (len(s) == len(etiquette) or s[len(etiquette)] in " \t"):
                if cle == "reference" and s.startswith("Référence") and not re.match(r"^Référence(\s|$)", s):
                    continue
                courant = cle
                vals[cle] = [s[len(etiquette):].strip()]
                trouve = True
                break
        if trouve:
            continue
        if courant and s and l.startswith(" " * 20) and not ENTETE_FICHE.match(l):
            vals[courant].append(s)
        elif s:
            courant = None if not l.startswith(" " * 20) else courant
    for cle, morceaux in vals.items():
        v = espaces(" ".join(morceaux))
        if cle == "beneficiaires":
            m = re.match(r"^([\d ]+?)\s+(\D.*)$", v)
            if m and re.fullmatch(r"[\d ]+", m.group(1)):
                rec["beneficiaires"] = nombre_beneficiaires(m.group(2), m.group(1))
            else:
                rec["beneficiaires"] = {"nombre": None, "nature": None, "brut": v} if v else {"nombre": None,
                                                                                               "nature": None}
        elif cle == "mission_programme":
            progs = re.findall(r"\bP\s?(\d{3})\b\s*([^/]*?)(?=\s+\S+[^/]*/\s*P\s?\d{3}|$)", v)
            mission = espaces(v.split("/")[0]) if "/" in v else None
            rec["mission_vm"] = mission
            if progs:
                rec["programme"] = {"code": str(int(progs[0][0])), "libelle": espaces(progs[0][1]) or None}
                if len(progs) > 1:
                    rec["programmes_subsidiaires"] = [{"code": str(int(p)), "libelle": espaces(lib) or None}
                                                      for p, lib in progs[1:]]
        else:
            rec[cle] = v or None
    return rec


def lire_pdf(chemin: Path, plf: int, texte: str | None = None) -> dict:
    texte = texte if texte is not None else texte_pdf(chemin)
    cats = categories_toc(texte)
    lignes = texte.splitlines()
    debut = next(i for i, l in enumerate(lignes) if i > 200 and l.strip() == "Liste des dépenses fiscales")
    fin = next((i for i, l in enumerate(lignes) if i > debut and l.strip() == "Annexes"), len(lignes))
    mes: dict[str, dict] = {}
    categorie = None
    blocs: list[tuple[str, str | None, list[str]]] = []
    for l in lignes[debut:fin]:
        s = espaces(re.sub(r"\s{3,}Voies et moyens tome II\s*$", "", l))
        if s in cats:
            categorie = s
            continue
        m = ENTETE_FICHE.match(l)
        if m:
            blocs.append((m.group(1), categorie, [l]))
        elif blocs:
            blocs[-1][2].append(l)
    for code, cat, bl in blocs:
        rec = lire_fiche(code, bl, plf)
        if not rec["couts"]:
            raise ValueError(f"PLF {plf}, {code} : chiffrage absent")
        rec["impot"] = cat
        if code in mes:
            raise ValueError(f"PLF {plf} : {code} en double")
        mes[code] = rec
    return mes


def lire_edition(plf: int) -> dict:
    e = EDITIONS[plf]
    if not e["chemin"].exists():
        raise SystemExit(f"{e['chemin']} absent : python pipeline/niches.py collecter (ou collecte/collecte.py)")
    return lire_xlsx(e["chemin"], plf) if e["type"] == "xlsx" else lire_pdf(e["chemin"], plf)


# --- Assemblage -------------------------------------------------------------------------------------------------


def edition_reference(annee: int) -> int:
    """Édition la plus récente qui chiffre l'année : PLF N+2 (réalisation), plafonnée à la dernière édition lue."""
    return min(annee + 2, max(EDITIONS))


def assembler(editions: dict[int, dict]) -> dict[str, dict]:
    codes = sorted({c for e in editions.values() for c in e})
    mesures = {}
    for c in codes:
        presentes = sorted(p for p, e in editions.items() if c in e)
        derniere = editions[presentes[-1]][c]
        m = {"id": c, "libelle": derniere["libelle"], "impot": None, "editions": presentes}
        for p in reversed(presentes):  # impôt : dernière édition qui le donne
            if editions[p][c].get("impot"):
                m["impot"] = editions[p][c]["impot"]
                break
        for k in ("sous_categorie", "finalite", "norme", "reference", "methode", "fiabilite"):
            for p in reversed(presentes):
                if editions[p][c].get(k):
                    m[k] = editions[p][c][k]
                    break
        m["programme"] = None
        for p in reversed(presentes):
            if editions[p][c].get("programme"):
                m["programme"] = {**editions[p][c]["programme"], "plf": p}
                if editions[p][c].get("programmes_subsidiaires"):
                    m["programmes_subsidiaires"] = editions[p][c]["programmes_subsidiaires"]
                break
        b = derniere.get("beneficiaires")
        m["beneficiaires"] = {**b, "plf": presentes[-1]} if b else None
        m["dates"] = {k: derniere.get(k) for k in ("creation", "modification", "fin_fait_generateur",
                                                     "fin_incidence", "suppression") if derniere.get(k)}
        m["dates"]["plf"] = presentes[-1]
        couts = {}
        for a in ANNEES:
            ref = edition_reference(a)
            cands = [ref] if ref in presentes else [p for p in reversed(presentes) if str(a) in editions[p][c]["couts"]]
            for p in cands:
                v = editions[p][c]["couts"].get(str(a))
                if v is None:
                    continue
                couts[str(a)] = {**v, "statut": "constaté" if a == p - 2 else "estimé", "plf": p,
                                 **({"hors_reference": True} if p != ref else {})}
                break
        m["couts"] = couts
        mesures[c] = m
    return mesures


def lire_igf() -> dict:
    ch = AUTRES["igf2011"]["chemin"]
    if not ch.exists():
        return {}
    out = {}
    with ch.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            c = code6(r["code"])
            if not c:
                continue
            s = r["score"].strip()
            out[c] = {"note": int(s) if s in "0123" and s else None,
                      "brut": s, "cout_2011": r["cost_2011"].strip() or None}
    return out


# --- Arbre État et rattachement ---------------------------------------------------------------------------------


def programmes_arbre() -> tuple[dict, dict]:
    r = json.loads(ARBRE.read_text(encoding="utf-8"))
    progs = {}

    def walk(n, chemin):
        if n.get("niveau") == "programme":
            gp, mission = chemin[1]["nom"], chemin[2]["nom"]
            progs[str(n["id"].split("/")[-1])] = {"noeud": n["id"], "nom": n["nom"], "mission": mission,
                                                  "grand_poste": gp, "budget_md": n["md"]}
            return
        for e in n.get("enfants", []):
            walk(e, chemin + [n])
    walk(r, [])
    return progs, {"millesime": r["millesime"], "total_md": r["md"]}


def par_programme(mesures: dict, progs: dict, entete_arbre: dict) -> dict:
    annees = ["2024", "2025", "2026"]
    agg = {}
    hors = defaultdict(lambda: {"mesures": [], **{a: 0.0 for a in annees}})
    for m in mesures.values():
        p = (m.get("programme") or {}).get("code")
        if not any(a in m["couts"] for a in annees):
            continue
        if p and p in progs:
            g = agg.setdefault(p, {"programme": p, **progs[p], "mesures": [],
                                   "fiscal_meur": {a: 0.0 for a in annees},
                                   "non_chiffrees": {a: 0 for a in annees}})
        else:
            g = hors[p or "aucun"]
        for a in annees:
            v = m["couts"].get(a)
            if v is None:
                continue
            if v["meur"] is not None:
                (g["fiscal_meur"] if "fiscal_meur" in g else g)[a] = \
                    (g["fiscal_meur"] if "fiscal_meur" in g else g)[a] + v["meur"]
            elif "non_chiffrees" in g and v["brut"] in ("nc", "ε"):
                g["non_chiffrees"][a] += 1
        g["mesures"].append(m["id"])
    liste = []
    for p, g in sorted(agg.items(), key=lambda kv: -kv[1]["fiscal_meur"]["2024"]):
        f24 = g["fiscal_meur"]["2024"]
        liste.append({**g, "fiscal_meur": {a: round(x, 1) for a, x in g["fiscal_meur"].items()},
                      "budget_meur": round(g["budget_md"] * 1000, 1),
                      "total_2024_meur": round(g["budget_md"] * 1000 + f24, 1),
                      "part_fiscale_2024": round(f24 / (g["budget_md"] * 1000 + f24), 4)
                      if g["budget_md"] * 1000 + f24 > 0 else None})
    for e in liste:
        del e["budget_md"]

    def regrouper(cle):
        out = {}
        for e in liste:
            k = e[cle]
            o = out.setdefault(k, {"nom": k, "budget_meur": 0.0, "fiscal_2024_meur": 0.0, "fiscal_2025_meur": 0.0,
                                   "fiscal_2026_meur": 0.0, "mesures": 0, "programmes": 0,
                                   **({"grand_poste": e["grand_poste"]} if cle == "mission" else {})})
            o["budget_meur"] += e["budget_meur"]
            o["fiscal_2024_meur"] += e["fiscal_meur"]["2024"]
            o["fiscal_2025_meur"] += e["fiscal_meur"]["2025"]
            o["fiscal_2026_meur"] += e["fiscal_meur"]["2026"]
            o["mesures"] += len(e["mesures"])
            o["programmes"] += 1
        res = []
        for o in out.values():
            for k in ("budget_meur", "fiscal_2024_meur", "fiscal_2025_meur", "fiscal_2026_meur"):
                o[k] = round(o[k], 1)
            t = o["budget_meur"] + o["fiscal_2024_meur"]
            o["part_fiscale_2024"] = round(o["fiscal_2024_meur"] / t, 4) if t > 0 else None
            res.append(o)
        return sorted(res, key=lambda o: -o["fiscal_2024_meur"])

    hors_liste = [{"programme": None if k == "aucun" else k, "mesures": v["mesures"],
                   "fiscal_meur": {a: round(v[a], 1) for a in annees}}
                  for k, v in sorted(hors.items(), key=lambda kv: -kv[1]["2024"])]
    return {"programmes": liste, "missions": regrouper("mission"), "grands_postes": regrouper("grand_poste"),
            "hors_arbre": hors_liste, "arbre": entete_arbre}


# --- Niches sociales (PLFSS 2026 annexe 4, Urssaf) --------------------------------------------------------------


def _nombre_fr(s: str) -> float | None:
    s = s.replace(" ", "").replace(" ", "").replace(" ", "")
    if s in ("-", "–", ""):
        return None
    return float(s.replace(",", "."))


_N = r"(-?\d{1,3}(?: \d{3})*|-)"
LIGNE_TABLEAU = re.compile(r"^\s*(\S.*?)\s{2,}" + _N + r"\s{2,}" + _N + r"\s+(-?[\d,]+%)\s+" + _N + r"\s+(-?[\d,]+%|-)\s*$")


def lire_tableau_exonerations(lignes: list[str], titre: str) -> list[dict]:
    i = next(k for k, l in enumerate(lignes) if l.strip().startswith(titre))
    out, mission = [], None
    for l in lignes[i + 1:]:
        if l.strip().startswith(("SOURCE", "Tableau", "**")):
            break
        m = LIGNE_TABLEAU.match(l)
        if not m:
            continue
        lib = espaces(m.group(1))
        v = [m.group(2), m.group(3), m.group(5)]
        vals = {a: (None if x.strip() in ("-",) else _nombre_fr(x)) for a, x in zip(("2024", "2025", "2026"), v)}
        brut = {a: x.strip() for a, x in zip(("2024", "2025", "2026"), v)}
        niveau = "mesure"
        if lib.isupper() or lib.upper() == lib:
            niveau = "groupe"
            if lib.startswith("MISSION"):
                mission = lib.replace("MISSION ", "").capitalize()
        elif lib.lower().startswith("dont "):
            niveau = "dont"
        out.append({"libelle": lib, "niveau": niveau, "mission": mission if niveau != "groupe" or
                    lib.startswith("MISSION") else None, "meur": vals,
                    "brut": {a: b for a, b in brut.items() if b == "-"} or None,
                    "statut": {"2024": "constaté", "2025": "estimé", "2026": "estimé"}})
    for e in out:
        if not e["brut"]:
            del e["brut"]
    return out


def lire_exemptions(lignes: list[str]) -> list[dict]:
    i = next(k for k, l in enumerate(lignes) if l.strip().startswith("Tableau 9"))
    out = []
    for l in lignes[i + 1:]:
        if l.strip().startswith("Note"):
            break
        m = re.match(r"^\s*(\S.*?)\s{2,}((?:[\d,]+\s+){11}[\d,]+)\s*$", l)
        if not m:
            continue
        nb = [float(x.replace(",", ".")) for x in m.group(2).split()]
        lib = espaces(m.group(1))
        par = {}
        for k, a in enumerate(("2023", "2024", "2025", "2026")):
            par[a] = {"assiette_md": nb[3 * k], "brutes_md": nb[3 * k + 1], "nettes_md": nb[3 * k + 2]}
        niveau = "total" if lib.upper().startswith("TOTAL") else ("groupe" if re.match(r"^[IVX]+\.", lib) else "mesure")
        out.append({"libelle": lib, "niveau": niveau, "annees": par})
    return out


def lire_urssaf() -> dict | None:
    ch = AUTRES["urssaf_exos"]["chemin"]
    if not ch.exists():
        return None
    import pandas as pd
    d = pd.read_parquet(ch)
    d["annee"] = pd.to_datetime(d["annee"].astype(str)).dt.year
    d = d[d["annee"].between(2019, 2025)]
    mesures = {}
    for r in d.itertuples(index=False):
        k = r.code_mesure_d_exoneration
        e = mesures.setdefault(k, {"code": k, "libelle": espaces(r.mesure_d_exoneration),
                                   "categorie": espaces(r.categorie_de_mesures),
                                   "grande_categorie": espaces(r.grande_categorie_de_mesures), "meur": {}})
        if r.montant_des_exonerations == r.montant_des_exonerations:  # pas NaN
            e["meur"][str(r.annee)] = round(float(r.montant_des_exonerations) / 1e6, 1)
    for e in mesures.values():
        e["meur"] = dict(sorted(e["meur"].items()))
    liste = sorted(mesures.values(), key=lambda e: -max(e["meur"].values() or [0]))
    totaux = {str(a): round(float(d[d["annee"] == a]["montant_des_exonerations"].sum()) / 1e6, 1)
              for a in range(2019, 2026)}
    return {"source": AUTRES["urssaf_exos"]["titre"], "url": AUTRES["urssaf_exos"]["url"],
            "champ": "secteur privé, cotisations recouvrées par les Urssaf (hors MSA, hors régimes spéciaux) : "
                     "exonérations et allègements, pas les exemptions d'assiette",
            "totaux_meur": totaux, "mesures": liste}


def sociales() -> dict:
    ch = AUTRES["plfss2026_annexe4"]["chemin"]
    if not ch.exists():
        raise SystemExit(f"{ch} absent : python pipeline/niches.py collecter")
    t = texte_pdf(ch)
    lignes = t.splitlines()
    for attendu in TEXTES_PLFSS:
        if attendu not in t:
            raise SystemExit(f"PLFSS 2026 annexe 4 : « {attendu[:60]} » introuvable, document modifié ?")
    comp = lire_tableau_exonerations(lignes, "Tableau 13")
    non_comp = lire_tableau_exonerations(lignes, "Tableau 14")
    exo = lire_exemptions(lignes)
    # contrôles : la somme des mesures retrouve chaque groupe publié
    for nom, tab in (("Tableau 14", non_comp),):
        tot = tab[0]["meur"]
        for a in ("2024", "2025", "2026"):
            s = sum(e["meur"][a] or 0 for e in tab if e["niveau"] == "mesure")
            if abs(s - tot[a]) > 3:
                raise SystemExit(f"{nom} {a} : somme {s} != total {tot[a]}")
    total_exo = next(e for e in exo if e["niveau"] == "total")
    for a in ("2023", "2024", "2025", "2026"):
        s = sum(e["annees"][a]["nettes_md"] for e in exo if e["niveau"] == "groupe")
        if abs(s - total_exo["annees"][a]["nettes_md"]) > 0.25:
            raise SystemExit(f"Tableau 9 {a} : somme des groupes {s} != total {total_exo['annees'][a]['nettes_md']}")
    synthese = {"2024": 74.7, "2025": 71.8, "2026": 71.5}
    return {
        "millesime": "PLFSS 2026 (constaté 2024, prévisions 2025 et 2026) ; Urssaf 2019-2025",
        "source": AUTRES["plfss2026_annexe4"]["titre"] + " ; " + AUTRES["urssaf_exos"]["titre"],
        "url": AUTRES["plfss2026_annexe4"]["url"],
        "unite": "millions d'euros (exonérations), milliards d'euros (exemptions d'assiette, synthèse)",
        "avertissement": "Les exonérations de cotisations (souvent appelées niches sociales) sont l'équivalent, pour la "
                         "Sécurité sociale, des dépenses fiscales de "
                         "l'État. Les exonérations ciblées compensées sont remboursées par l'État (crédits des missions "
                         "indiquées) : elles figurent aussi dans la dépense budgétaire et ne s'ajoutent pas aux "
                         "dépenses fiscales. Les allègements généraux sont compensés par des recettes fiscales "
                         "affectées. Les chiffres 2026 sont avant mesures du PLFSS 2026.",
        "synthese_exonerations_md": {"champ": "régimes obligatoires de base (ROBSS), compensées ou non",
                                     "annees": synthese, "statut": {"2024": "constaté", "2025": "estimé",
                                                                    "2026": "estimé"},
                                     "ref": "annexe 4, tableau 6"},
        "allegements_et_exonerations_compensees": {"ref": "annexe 4, tableau 13", "lignes": comp},
        "exonerations_non_compensees": {"ref": "annexe 4, tableau 14", "lignes": non_comp},
        "exemptions_assiette": {"ref": "annexe 4, tableau 9",
                                "note": "assiette exemptée, cotisations équivalentes brutes et nettes (nettes des "
                                        "prélèvements spécifiques : forfait social, CSG), en Md€ ; 2023 constaté, "
                                        "2024 à 2026 prévisionnels selon les assiettes",
                                "lignes": exo},
        "urssaf": lire_urssaf(),
    }


# --- Vérification des totaux publiés ----------------------------------------------------------------------------


def verifier_documents(textes: dict[int, str]) -> dict:
    out = {}
    for annee, (plf, phrase, _) in TOTAUX_PUBLIES.items():
        t = espaces(textes[plf]).replace("'", "’")
        if espaces(phrase) not in t:
            raise SystemExit(f"PLF {plf} : « {phrase} » introuvable, document modifié ?")
        out[f"total_{annee}"] = {"plf": plf, "phrase": phrase, "verdict": "vérifié"}
    for plf, ligne in TABLEAUX_TOTAUX.items():
        if ligne not in espaces(textes[plf]):
            raise SystemExit(f"PLF {plf} : « {ligne} » introuvable, document modifié ?")
        out[f"tableau_par_impot_plf{plf}"] = {"plf": plf, "phrase": ligne, "verdict": "vérifié"}
    if TOTAL_MISSIONS_2026[0] not in textes[2026]:
        raise SystemExit("PLF 2026 : total du tableau par mission introuvable")
    out["total_missions_2026"] = {"plf": 2026, "phrase": espaces(TOTAL_MISSIONS_2026[0]), "verdict": "vérifié"}
    return out


# --- Production -------------------------------------------------------------------------------------------------


def totaux(mesures: dict) -> dict:
    out = {}
    for a in ANNEES:
        ref = edition_reference(a)
        t = {"plf_reference": ref, "statut": "constaté" if a == ref - 2 else "estimé", "chiffre_meur": 0.0,
             "mesures": 0, "chiffrees": 0, "nc": 0, "epsilon": 0, "sans_effet": 0,
             "hors_reference": {"mesures": 0, "chiffre_meur": 0.0}}
        for m in mesures.values():
            v = m["couts"].get(str(a))
            if v is None:
                continue
            if v.get("hors_reference"):
                t["hors_reference"]["mesures"] += 1
                t["hors_reference"]["chiffre_meur"] += v["meur"] or 0.0
                continue
            t["mesures"] += 1
            if v["meur"] is not None:
                t["chiffrees"] += 1
                t["chiffre_meur"] += v["meur"]
            else:
                t[{"nc": "nc", "ε": "epsilon", "-": "sans_effet"}.get(v["brut"], "nc")] += 1
        t["chiffre_meur"] = round(t["chiffre_meur"], 1)
        t["hors_reference"]["chiffre_meur"] = round(t["hors_reference"]["chiffre_meur"], 1)
        pub = TOTAUX_PUBLIES.get(a)
        if pub and pub[0] == ref:
            t["total_publie_meur"] = pub[2]
            t["ecart_meur"] = round(pub[2] - t["chiffre_meur"], 1)
            t["ecart_explication"] = ("aucun : somme des fiches = total publié" if abs(t["ecart_meur"]) <= 1 else
                                      "le total publié impute une prévision aux mesures dont la fiche porte « nc »")
        else:
            t["total_publie_meur"] = None
        out[str(a)] = t
    return out


def produire() -> dict:
    editions, textes = {}, {}
    for plf, e in EDITIONS.items():
        if e["type"] == "pdf":
            if not e["chemin"].exists():
                raise SystemExit(f"{e['chemin']} absent : python pipeline/niches.py collecter")
            textes[plf] = texte_pdf(e["chemin"])
            editions[plf] = lire_pdf(e["chemin"], plf, textes[plf])
        else:
            editions[plf] = lire_edition(plf)
        print(f"PLF {plf} : {len(editions[plf])} mesures", file=sys.stderr)
    verif = verifier_documents(textes)
    mesures = assembler(editions)
    igf = lire_igf()
    for c, m in mesures.items():
        if c in igf:
            m["evaluation_2011"] = igf[c]
    progs, entete_arbre = programmes_arbre()
    for m in mesures.values():
        if m.get("programme"):
            m["programme"]["noeud_arbre"] = (progs.get(m["programme"]["code"]) or {}).get("noeud")
    tot = totaux(mesures)
    for a in ("2022", "2023", "2024"):  # constaté : la somme des fiches retrouve le total publié
        if tot[a]["total_publie_meur"] is None or abs(tot[a]["ecart_meur"]) > 1:
            raise SystemExit(f"total {a} : {tot[a]['chiffre_meur']} M€ calculés, {tot[a]['total_publie_meur']} publiés")
    pp = par_programme(mesures, progs, entete_arbre)
    # couverture du rattachement (2024, constaté)
    total24 = sum(m["couts"]["2024"]["meur"] or 0 for m in mesures.values()
                  if "2024" in m["couts"] and not m["couts"]["2024"].get("hors_reference"))
    rattache24 = sum(p["fiscal_meur"]["2024"] for p in pp["programmes"])
    rattache_ref = sum(m["couts"]["2024"]["meur"] or 0 for m in mesures.values()
                       if "2024" in m["couts"] and not m["couts"]["2024"].get("hors_reference")
                       and (m.get("programme") or {}).get("code") in progs)
    couverture = {"annee": 2024, "chiffre_meur": round(total24, 1), "rattache_arbre_meur": round(rattache_ref, 1),
                  "part_rattachee": round(rattache_ref / total24, 4) if total24 else None,
                  "mesures_avec_programme": sum(1 for m in mesures.values() if m.get("programme")),
                  "mesures_programme_dans_arbre": sum(1 for m in mesures.values()
                                                      if (m.get("programme") or {}).get("code") in progs),
                  "mesures": len(mesures)}
    del rattache24

    sources = {f"plf{p}": {k: (str(v) if isinstance(v, Path) else v) for k, v in e.items() if k != "chemin"}
               for p, e in EDITIONS.items()}
    sources.update({k: {kk: vv for kk, vv in v.items() if kk != "chemin"} for k, v in AUTRES.items()})
    source_txt = ("Évaluation des voies et moyens tome II, PLF 2021 à 2026 (classeurs DGFiP data.economie.gouv.fr "
                  "pour 2021-2023, PDF miroirs Assemblée nationale pour 2024-2026)")
    entete = {"millesime": "PLF 2021 à PLF 2026 : coûts 2019 à 2026 (constaté jusqu'en 2024, estimé 2025 et 2026)",
              "source": source_txt, "unite": "millions d'euros (meur), comme à la source"}

    liste = sorted(mesures.values(), key=lambda m: m["id"])
    dump(SORTIE / "mesures.json", {
        **entete,
        "avertissement": "Coût d'une dépense fiscale = perte de recettes à comportement inchangé ; les coûts ne "
                         "s'additionnent qu'à titre indicatif (interactions entre mesures). « nc » = non chiffré, "
                         "« ε » = moins de 0,5 M€, « - » = aucun effet budgétaire : `meur` est alors null, jamais 0. "
                         "Une année est lue dans l'édition la plus récente qui la chiffre (`plf`) ; `hors_reference` "
                         "signale une mesure absente de l'édition de référence de l'année (supprimée ou renumérotée) "
                         "dont la dernière prévision est gardée. Pour le crédit d'impôt recherche, la dépense fiscale "
                         "d'une année n'est pas la créance d'un millésime (imputation sur plusieurs années).",
        "jetons": SENS_JETONS,
        "annees": [str(a) for a in ANNEES],
        "mesures": liste})

    dump(SORTIE / "programmes.json", {
        "millesime": "dépense fiscale 2024 constatée (PLF 2026), 2025 et 2026 estimées ; dépense budgétaire : "
                     f"{entete_arbre['millesime']}",
        "source": source_txt + " ; arbre État site/data/arbre/racine.json (" + entete_arbre["millesime"] + ")",
        "unite": "millions d'euros",
        "avertissement": "Chaque dépense fiscale est rattachée à son programme principal (tome II) ; la dépense "
                         "fiscale et la dépense budgétaire d'un programme s'additionnent pour lire l'effort de l'État "
                         "par politique, mais la première est une perte de recettes estimée, la seconde un décaissement "
                         "constaté. Les mesures non chiffrées (« nc », « ε ») sont comptées à part (non_chiffrees).",
        **pp, "couverture": couverture})

    soc = sociales()
    dump(SORTIE / "sociales.json", soc)

    top25 = sorted((m for m in liste if (m["couts"].get("2025") or {}).get("meur") is not None),
                   key=lambda m: -m["couts"]["2025"]["meur"])[:20]
    par_impot = defaultdict(lambda: {"mesures": 0, "chiffre_2024_meur": 0.0, "chiffre_2025_meur": 0.0})
    for m in liste:
        if "2025" not in m["couts"] or m["couts"]["2025"].get("hors_reference"):
            continue
        g = par_impot[m["impot"] or "non classé"]
        g["mesures"] += 1
        for a in ("2024", "2025"):
            v = m["couts"].get(a)
            if v and v["meur"] is not None and not v.get("hors_reference"):
                g[f"chiffre_{a}_meur"] += v["meur"]
    idx = {
        **entete,
        "vue": {"mesures": "niches/mesures.json", "programmes": "niches/programmes.json",
                "sociales": "niches/sociales.json"},
        "mesures": len(liste),
        "mesures_par_edition": {str(p): len(e) for p, e in editions.items()},
        "totaux": tot,
        "top_2025": [{"id": m["id"], "libelle": m["libelle"], "impot": m["impot"],
                      "meur": m["couts"]["2025"]["meur"], "statut": m["couts"]["2025"]["statut"],
                      "programme": (m.get("programme") or {}).get("code")} for m in top25],
        "par_impot_2025": [{"impot": k, **{kk: (round(vv, 1) if isinstance(vv, float) else vv)
                                          for kk, vv in v.items()}}
                           for k, v in sorted(par_impot.items(), key=lambda kv: -kv[1]["chiffre_2025_meur"])],
        "couverture_programmes": couverture,
        "niches_sociales": {"exonerations_robss_md": soc["synthese_exonerations_md"]["annees"],
                            "exemptions_assiette_nettes_md": {
                                a: next(e for e in soc["exemptions_assiette"]["lignes"] if e["niveau"] == "total")
                                ["annees"][a]["nettes_md"] for a in ("2023", "2024", "2025", "2026")}},
        "beneficiaires_nommes": BENEFICIAIRES_NOMMES,
        "verification_documents": verif,
        "sources": sources,
        "sources_inaccessibles": SOURCES_INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "genere_le": maintenant()[:10],
    }
    dump(SORTIE / "index.json", idx)
    bilan = {"mesures": len(liste), "totaux_md": {a: round(t["chiffre_meur"] / 1000, 2) for a, t in tot.items()},
             "part_rattachee_2024": couverture["part_rattachee"],
             "top5_2025": [(m["id"], m["libelle"][:50], m["couts"]["2025"]["meur"]) for m in top25[:5]]}
    print(json.dumps(bilan, ensure_ascii=False, indent=1), file=sys.stderr)
    return bilan


# --- Collecte ---------------------------------------------------------------------------------------------------


def telecharger(url: str, dest: Path) -> str:
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    derniere = ""
    for i in range(3):
        try:
            r = requests.get(url, timeout=(20, 600), headers=HEADERS)
            if r.status_code in (401, 403, 429, 451):
                return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
            r.raise_for_status()
            if r.content[:200].lstrip().lower().startswith((b"<html", b"<!doctype")):
                return "page HTML renvoyée à la place du fichier : aucun contournement"
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(r.content)
            tmp.replace(dest)
            return "ok"
        except Exception as e:  # reprise réseau
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(3 * (i + 1))
    return f"échec après 3 essais : {derniere}"


def collecter() -> dict:
    etat = {}
    a_collecter = {f"plf{p}": e for p, e in EDITIONS.items() if e["type"] == "pdf"}
    a_collecter.update({k: v for k, v in AUTRES.items() if k != "urssaf_exos"})
    for cle, s in a_collecter.items():
        dest = s["chemin"]
        if dest.exists() and dest.stat().st_size > 0:
            etat[cle] = {"statut": "présent", "octets": dest.stat().st_size}
            continue
        res = telecharger(s["url"], dest)
        etat[cle] = {"statut": res, "collecte_le": maintenant()}
        print(f"{cle}: {res}", file=sys.stderr)
    for p, e in EDITIONS.items():
        if e["type"] == "xlsx" and not e["chemin"].exists():
            etat[f"plf{p}"] = {"statut": "absent : collecté par collecte/collecte.py (catalogue data.economie)"}
    for k in ("urssaf_exos",):
        if not AUTRES[k]["chemin"].exists():
            etat[k] = {"statut": "absent : collecté par collecte/collecte.py (catalogue Urssaf)"}
    BRUT.mkdir(parents=True, exist_ok=True)
    (BRUT / "collecte.json").write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    return etat


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("commande", nargs="*", default=["collecter", "produire"], choices=["collecter", "produire"])
    args = ap.parse_args(argv)
    for cmd in args.commande:
        if cmd == "collecter":
            collecter()
        elif cmd == "produire":
            produire()


if __name__ == "__main__":
    main()
