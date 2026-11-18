"""Pouvoirs publics : dotations de la Présidence de la République, des assemblées, des chaînes parlementaires, du
Conseil constitutionnel et de la Cour de justice de la République ; budgets publiés de ces institutions (grandes
masses) ; barèmes des indemnités par fonction.

Uniquement des documents publiés, déclarés dans collecte/catalogue.json (entrées `pouvoirs_publics_*`) : annexes
« Pouvoirs publics » aux projets de loi de finances (2022 à 2026) et au projet de loi relatif aux résultats de la
gestion 2025, note de présentation de la commission des finances du Sénat pour le PLF 2027, budget et réalisé de
l'Assemblée nationale 2012-2017 (open data de l'Assemblée), rapport sur les comptes 2025 de l'Assemblée, pages du
Sénat (budget, indemnité, moyens), fiche « Situation matérielle du député », réponse du Gouvernement à la question
écrite n° 24217 (règle de calcul du traitement du Président de la République). Aucune personne n'est nommée : les
montants sont donnés par fonction ; aucun texte libre des documents n'est recopié, seuls des montants sont lus.

Commandes :
    python pipeline/pouvoirs_publics.py collecter   (réseau, par collecte/collecte.py ; un refus 401/403/429 ou une
                                                    page anti-robot est noté, jamais contourné)
    python pipeline/pouvoirs_publics.py produire [--sortie DOSSIER]   (sans réseau ; lit data/lake/pouvoirs_publics/
                                                    et site/data/realisations/5*.json en lecture seule)

Sorties (site/data/pouvoirs_publics/, contrat docs/contrat_interface.md 2.41, schémas
docs/schemas/pouvoirs_publics_*) : index.json, dotations.json, budgets.json, indemnites.json

Règles : une valeur absente reste null avec sa mention, jamais 0 ; deux sources qui donnent un montant différent
pour la même grandeur sont publiées côte à côte (`ecarts`), jamais tranchées ni additionnées ; un total publié qui
ne retombe pas sur la somme de ses lignes est publié avec son écart ; la production s'arrête si un tableau relu
dans un PDF ne retombe plus sur ses propres totaux (le document a changé de forme). Dates par
pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques octet pour octet.
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
import unicodedata
import zipfile
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "pouvoirs_publics"
MANIFESTE = ROOT / "data" / "lake" / "manifest.json"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "pouvoirs_publics"
DOMAINE = "pouvoirs_publics"

PAP = {2022: "pouvoirs_publics_pap_2022", 2023: "pouvoirs_publics_pap_2023", 2024: "pouvoirs_publics_pap_2024",
       2025: "pouvoirs_publics_pap_2025", 2026: "pouvoirs_publics_pap_2026"}
SOURCES = {
    **{ident: {"titre": f"Annexe « Pouvoirs publics » au projet de loi de finances pour {annee} (crédits ouverts en "
                        f"loi de finances initiale {annee - 1}, crédits demandés pour {annee}, budgets des "
                        "institutions)", "producteur": "Direction du budget, documents budgétaires (miroir de "
                                                     "l'Assemblée nationale)"}
       for annee, ident in PAP.items()},
    "pouvoirs_publics_rap_2025": {
        "titre": "Rapport annuel de performances 2025, mission « Pouvoirs publics » (crédits prévus et consommés "
                 "2024 et 2025), annexe au projet de loi relatif aux résultats de la gestion 2025",
        "producteur": "Direction du budget (miroir de l'Assemblée nationale)"},
    "pouvoirs_publics_np_senat_plf2027": {
        "titre": "Note de présentation de la mission « Pouvoirs publics », projet de loi de finances pour 2027 "
                 "(crédits ouverts en loi de finances initiale 2026, crédits demandés pour 2027, équilibre "
                 "budgétaire de la Présidence de la République)",
        "producteur": "Sénat, commission des finances"},
    "pouvoirs_publics_an_budgets_2012_2017": {
        "titre": "Le budget de l'Assemblée nationale 2012-2017 : budget et réalisé par compte (CSV)",
        "producteur": "Assemblée nationale (data.assemblee-nationale.fr, jeu repris sur data.gouv.fr)"},
    "pouvoirs_publics_an_rapport_comptes_2025": {
        "titre": "Rapport de la commission spéciale chargée de vérifier et d'apurer les comptes : comptes de "
                 "l'Assemblée nationale de l'exercice 2025",
        "producteur": "Assemblée nationale"},
    "pouvoirs_publics_an_situation_materielle": {
        "titre": "Fiche de synthèse n° 7 : situation matérielle du député (actualisée le 8 janvier 2026)",
        "producteur": "Assemblée nationale"},
    "pouvoirs_publics_senat_indemnite": {"titre": "L'indemnité parlementaire (page du Sénat)", "producteur": "Sénat"},
    "pouvoirs_publics_senat_moyens": {"titre": "Les moyens mis à la disposition des sénateurs (page du Sénat)",
                                      "producteur": "Sénat"},
    "pouvoirs_publics_senat_budget": {"titre": "Le budget du Sénat (page du Sénat)", "producteur": "Sénat"},
    "pouvoirs_publics_qe_traitement_president": {
        "titre": "Question écrite n° 24217 (XVe législature) et réponse du Gouvernement : règle de calcul du "
                 "traitement du Président de la République (décret n° 2012-983 du 23 août 2012)",
        "producteur": "Assemblée nationale, réponse du ministère de l'action et des comptes publics"},
}

INACCESSIBLES = [
    {"source": "Annexe « Pouvoirs publics » au PLF 2015 et précédentes (budget.gouv.fr, archives des documents "
               "budgétaires)",
     "url": "https://www.budget.gouv.fr/sites/performance_publique/files/farandole/ressources/2015/pap/pdf/"
            "PAP_2015_BG_Pouvoirs_publics.pdf",
     "motif": "le serveur renvoie une page de vérification anti-robot au collecteur (18/11/2026) : non contourné",
     "consequence": "crédits votés 2015 à 2017 absents de dotations.json (null), faute aussi de jeu ouvert lisible "
                    "pour ces années"},
    {"source": "Annexes « Pouvoirs publics » aux PLF 2016 à 2021",
     "url": "https://www.budget.gouv.fr/documentation/documents-budgetaires",
     "motif": "aucune adresse stable trouvée sur le miroir de l'Assemblée nationale ; archives de budget.gouv.fr "
              "derrière la même vérification anti-robot",
     "consequence": "budgets détaillés de l'Assemblée nationale 2018 à 2020 non repris"},
    {"source": "Décret n° 2012-983 du 23 août 2012 relatif au traitement du Président de la République et des "
               "membres du Gouvernement (Légifrance)",
     "url": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000026317711",
     "motif": "HTTP 403 (vérification anti-robot) : non contourné",
     "consequence": "traitement des membres du Gouvernement autres que le Premier ministre : null ; seule la règle "
                    "du Président de la République et du Premier ministre, citée par le Gouvernement dans une "
                    "réponse publiée au Journal officiel, est reprise"},
    {"source": "Tableaux du budget du Sénat dans l'annexe « Pouvoirs publics » (dépenses et ressources par "
               "action, série depuis 2012)",
     "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1088014/file/PAP2026_BG_Pouvoirs_publics_PB.pdf",
     "motif": "publiés sous forme d'images dans le PDF, sans texte lisible ; non relus par reconnaissance de "
              "caractères",
     "consequence": "budget du Sénat limité aux montants de la page « Le budget du Sénat »"},
    {"source": "Rapports de la Cour des comptes sur les comptes et la gestion des services de la Présidence de la "
               "République",
     "url": "https://www.ccomptes.fr",
     "motif": "non collectés dans cette version (rapports PDF sans tableau stable d'une année sur l'autre)",
     "consequence": "équilibre budgétaire de la Présidence repris de la note de la commission des finances du Sénat "
                    "et de l'annexe au PLF 2026"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Aucun jeu ouvert ne donne la série des dotations des pouvoirs publics ni les barèmes des "
                  "indemnités ; seule l'Assemblée nationale publie son budget détaillé en CSV, pour 2012-2017. Les "
                  "documents budgétaires (annexes « Pouvoirs publics ») sont donc relus en PDF ; les montants "
                  "d'exécution déjà produits par le dépôt (site/data/realisations/) sont repris et comparés.",
    "trouvailles": [
        {"nom": "Le budget de l'Assemblée nationale 2012-2017 (CSV, data.assemblee-nationale.fr)",
         "url": "https://www.data.gouv.fr/datasets/5b1e5e26c751df50d162459c", "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte (fr-lo)", "mise_a_jour": "2018-06-08"},
        {"nom": "Annexes « Pouvoirs publics » aux PLF 2022 à 2026 et RAP 2025 (PDF)",
         "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1088014/file/PAP2026_BG_Pouvoirs_publics_PB.pdf",
         "verdict": "à adapter", "licence": "document administratif public (tableaux relus par position)",
         "mise_a_jour": "2026"},
        {"nom": "site/data/realisations/5*.json (dépense constatée et crédits votés par programme, 2010-2025)",
         "url": "pipeline/realisations.py", "verdict": "réutilisable tel quel", "licence": "MIT (dépôt du projet)",
         "mise_a_jour": "2026-11-17"},
        {"nom": "Jeux « loi de finances initiale » 2016 à 2022 sur data.economie.gouv.fr (pièces jointes)",
         "url": "https://data.economie.gouv.fr/explore/dataset/loi-de-finances-initiale-pour-2016-lfi-2016/",
         "verdict": "inspiration seulement",
         "licence": "Licence Ouverte 2.0 (API des pièces jointes instable lors de la recherche, non retenu)",
         "mise_a_jour": "2018-12-13"},
        {"nom": "regardscitoyens/nosdeputes.fr (activité des députés, par personne)",
         "url": "https://github.com/regardscitoyens/nosdeputes.fr", "verdict": "inspiration seulement",
         "licence": "AGPL-3.0 (données par personne nommée, hors périmètre)", "mise_a_jour": "2024-11-14"},
        {"nom": "Recherche data.gouv.fr « pouvoirs publics », « indemnité parlementaire », « comptes du Sénat » et "
                "GitHub « dotations pouvoirs publics », « budget assemblée nationale »",
         "url": "https://www.data.gouv.fr/api/1/datasets/?q=pouvoirs+publics", "verdict": "inspiration seulement",
         "licence": "sans objet (aucun autre jeu ni dépôt trouvé)", "mise_a_jour": "2026-11-18"},
    ],
}

AVERTISSEMENT = ("Les pouvoirs publics fixent eux-mêmes leur budget (autonomie financière des pouvoirs publics "
                 "constitutionnels) ; l'État leur verse une dotation, inscrite dans la mission « Pouvoirs publics ». "
                 "La dotation n'est pas la dépense de l'institution : l'écart est couvert par des recettes propres "
                 "ou par un prélèvement sur les disponibilités. Montants en euros courants, crédits de paiement.")


class DonneeInattendue(RuntimeError):
    """La source ne ressemble plus à ce que le module sait lire : on s'arrête plutôt que de publier un chiffre faux."""


# ----------------------------------------------------------------------------------------------------------------
# Lecture des documents
# ----------------------------------------------------------------------------------------------------------------

MONTANT = re.compile(r"^([-–−]?)\s?(\d{1,3}(?: \d{3})+|\d+)$")
ESPACES = re.compile(r"[   ]")


def _manifeste() -> dict:
    try:
        return json.loads(MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fichier(ident: str) -> Path:
    for p in sorted(LAKE.glob(f"{ident}.*")):
        return p
    raise DonneeInattendue(f"source absente de l'entrepôt : {ident} (lancer `collecter`)")


def montant(cellule: str) -> int | None:
    m = MONTANT.match(ESPACES.sub(" ", cellule.strip()))
    if not m:
        return None
    v = int(m.group(2).replace(" ", ""))
    return -v if m.group(1) else v


def euros(texte: str) -> float:
    """« 5 931,95 » -> 5931.95"""
    return float(ESPACES.sub(" ", texte).replace(" ", "").replace(",", "."))


@lru_cache(maxsize=None)
def lignes_pdf(ident: str) -> tuple[tuple[int, tuple[str, ...]], ...]:
    """Lignes du PDF (numéro de page, cellules). Une cellule regroupe les mots séparés de moins de 3,2 points : les
    espaces des milliers (environ 2 points) restent dans la cellule, les colonnes (5 points et plus) la coupent."""
    import pdfplumber
    sortie = []
    with pdfplumber.open(_fichier(ident)) as pdf:
        for num, page in enumerate(pdf.pages, start=1):
            mots = [w for w in page.extract_words(extra_attrs=["upright"]) if w.get("upright", True)]
            lignes: list[list[dict]] = []
            for w in sorted(mots, key=lambda w: (round(w["top"], 1), w["x0"])):
                if lignes and abs(lignes[-1][0]["top"] - w["top"]) <= 2.5:
                    lignes[-1].append(w)
                else:
                    lignes.append([w])
            for ligne in lignes:
                cellules: list[list[dict]] = []
                for w in sorted(ligne, key=lambda w: w["x0"]):
                    if cellules and w["x0"] - cellules[-1][-1]["x1"] < 3.2:
                        cellules[-1].append(w)
                    else:
                        cellules.append([w])
                sortie.append((num, tuple(ESPACES.sub(" ", " ".join(x["text"] for x in c)) for c in cellules)))
    return tuple(sortie)


@lru_cache(maxsize=None)
def texte_pdf(ident: str) -> str:
    """Texte continu du PDF, espaces normalisés (pour les montants cités dans une phrase)."""
    import pdfplumber
    with pdfplumber.open(_fichier(ident)) as pdf:
        t = "\n".join(p.extract_text() or "" for p in pdf.pages)
    return re.sub(r"\s+", " ", ESPACES.sub(" ", t))


@lru_cache(maxsize=None)
def texte_html(ident: str) -> str:
    t = _fichier(ident).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"<main.*?</main>", t, re.S)
    t = m.group(0) if m else t
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", ESPACES.sub(" ", t))


def _cherche(texte: str, motif: str, ident: str) -> re.Match:
    m = re.search(motif, texte)
    if not m:
        raise DonneeInattendue(f"{ident} : motif introuvable « {motif} »")
    return m


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


# ----------------------------------------------------------------------------------------------------------------
# Dotations : récapitulatifs des annexes, du RAP et de la note du Sénat
# ----------------------------------------------------------------------------------------------------------------

LIBELLE = re.compile(r"^(\d{3}|\d{2}) ?[–-] ?(.*)$")


def _recap(ident: str, debut: str, n_montants: tuple[int, ...], total_requis: bool = True) -> list[dict]:
    """Lignes du premier tableau récapitulatif après la ligne contenant `debut`, jusqu'à la ligne des totaux.

    Chaque entrée : code (programme sur 3 chiffres, action sur 2, « total »), libellé, liste des montants de la
    ligne du libellé et, quand le document met la seconde année sur la ligne suivante, ceux de cette ligne."""
    lignes = lignes_pdf(ident)
    i0 = next((i for i, (_, c) in enumerate(lignes) if debut in _norm(" ".join(c))), None)
    if i0 is None:
        raise DonneeInattendue(f"{ident} : tableau « {debut} » introuvable")
    sortie: list[dict] = []
    page0 = lignes[i0][0]
    for page, cellules in lignes[i0 + 1:]:
        if not total_requis and page != page0:
            break                                              # tableau sans ligne de total : fin de la page
        tete = cellules[0]
        montants = [v for v in (montant(c) for c in cellules[1:]) if v is not None]
        m = LIBELLE.match(tete)
        est_total = re.match(r"tota(?:l|ux)\b", _norm(tete)) is not None
        if m or est_total:
            if len(montants) not in n_montants:
                raise DonneeInattendue(f"{ident} : ligne « {tete} » avec {len(montants)} montants")
            sortie.append({"code": "total" if est_total else m.group(1),
                           "libelle": "Total" if est_total else m.group(2).strip(), "montants": montants,
                           "suite": None})
            if est_total and len(montants) == max(n_montants):
                break
        elif sortie and sortie[-1]["suite"] is None and montant(tete) is not None and \
                len(montants) + 1 == len(sortie[-1]["montants"]):
            sortie[-1]["suite"] = [montant(tete)] + montants
            if sortie[-1]["code"] == "total":
                break
        elif sortie and sortie[-1]["suite"] is None and montant(tete) is None and montants and \
                len(montants) == len(sortie[-1]["montants"]):
            sortie[-1]["libelle"] += " " + tete           # fin du libellé, puis les montants de la seconde année
            sortie[-1]["suite"] = montants
        elif sortie and not montants and montant(tete) is None and sortie[-1]["suite"] is None \
                and not _norm(tete).startswith(("plf", "lfi")):
            sortie[-1]["libelle"] += " " + " ".join(cellules).strip()   # libellé sur deux lignes
    if not sortie or (total_requis and sortie[-1]["code"] != "total"):
        raise DonneeInattendue(f"{ident} : ligne des totaux introuvable")
    return sortie


def recap_pap(annee: int) -> dict:
    """{code: {libelle, lfi, plf}} en crédits de paiement : LFI de l'année précédente, PLF de l'année."""
    ident = PAP[annee]
    entete = " ".join(" ".join(c) for _, c in lignes_pdf(ident)[:400])
    if f"LFI {annee - 1}" not in entete and f"pour {annee - 1}" not in entete:
        raise DonneeInattendue(f"{ident} : en-tête LFI {annee - 1} introuvable")
    lignes = []
    for e in _recap(ident, "par programme et action", (2, 4)):
        if len(e["montants"]) == 4:          # une ligne : AE LFI, AE PLF, CP LFI, CP PLF
            lfi, plf = e["montants"][2], e["montants"][3]
        else:                                # deux lignes : AE et CP de la LFI, puis AE et CP du PLF
            if e["suite"] is None or len(e["suite"]) != 2:
                raise DonneeInattendue(f"{ident} : seconde ligne absente pour « {e['libelle']} »")
            lfi, plf = e["montants"][1], e["suite"][1]
        lignes.append({"code": e["code"], "libelle": e["libelle"], "lfi": lfi, "plf": plf})
    return _arborescence(lignes, ident)


def _arborescence(lignes: list[dict], ident: str) -> dict:
    """Rattache chaque action (2 chiffres) au programme qui la précède et vérifie programmes = total."""
    programmes: dict[str, dict] = {}
    total = None
    courant = None
    for e in lignes:
        if e["code"] == "total":
            total = e
        elif len(e["code"]) == 3:
            courant = {**e, "actions": []}
            programmes[e["code"]] = courant
        elif courant is not None:
            courant["actions"].append(e)
    modele = total or next(iter(programmes.values()))
    cles = [k for k in modele if k not in ("code", "libelle", "suite", "montants", "actions")]
    for k in cles:
        s = sum(p[k] for p in programmes.values())
        if total is not None and s != total[k]:
            raise DonneeInattendue(f"{ident} : somme des programmes ({k}) {s} ≠ total {total[k]}")
        for p in programmes.values():
            if p["actions"] and sum(a[k] for a in p["actions"]) != p[k]:
                raise DonneeInattendue(f"{ident} : actions du programme {p['code']} ≠ programme ({k})")
    return {"programmes": programmes, "total": None if total is None else {k: total[k] for k in cles}}


def recap_rap() -> dict:
    """RAP 2025 : crédits de paiement prévus (LFI y.c. fonds de concours) et consommés, 2024 et 2025."""
    ident = "pouvoirs_publics_rap_2025"
    lignes = []
    for e in _recap(ident, "par programme et action", (4,), total_requis=False):
        if e["suite"] is None or len(e["suite"]) != 4:
            raise DonneeInattendue(f"{ident} : ligne de consommation absente pour « {e['libelle']} »")
        lignes.append({"code": e["code"], "libelle": e["libelle"],
                       "prevu_2024": e["montants"][2], "prevu_2025": e["montants"][3],
                       "consomme_2024": e["suite"][2], "consomme_2025": e["suite"][3]})
    return _arborescence(lignes, ident)


def recap_np2027() -> dict:
    ident = "pouvoirs_publics_np_senat_plf2027"
    lignes = []
    for e in _recap(ident, "recapitulation des dotations", (2,)):
        lignes.append({"code": e["code"], "libelle": e["libelle"], "lfi": e["montants"][0],
                       "plf": e["montants"][1]})
    return _arborescence(lignes, ident)


INSTITUTIONS = {"501": "presidence", "511": "assemblee_nationale", "521": "senat", "541": "chaine_parlementaire",
                "542": "representants_parlement_europeen", "531": "conseil_constitutionnel", "532": "haute_cour",
                "533": "cour_justice_republique"}


def _realisations(code: str) -> dict[int, dict]:
    p = SITE / "realisations" / f"{code}.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    annees = ((d.get("prevu_depense") or {}).get("annees")) or []
    return {a["annee"]: a for a in annees}


def dotations() -> dict:
    paps = {a: recap_pap(a) for a in sorted(PAP)}
    rap = recap_rap()
    np27 = recap_np2027()
    ordre: list[str] = []
    libelles: dict[str, str] = {}
    for doc in [*[paps[a] for a in sorted(paps, reverse=True)], rap, np27]:   # libellés de l'annexe la plus récente
        for code, p in doc["programmes"].items():
            if code not in ordre:
                ordre.append(code)
            libelles.setdefault(code, p["libelle"])
    # valeurs[(code, annee, grandeur)] = [(montant, source, detail)]
    valeurs: dict[tuple, list] = {}

    def ajoute(code, annee, grandeur, v, source, detail=None):
        if v is None:
            return
        valeurs.setdefault((code, annee, grandeur), []).append((v, source, detail))

    for a, doc in paps.items():
        for code, p in doc["programmes"].items():
            ajoute(code, a - 1, "lfi", p["lfi"], PAP[a])
            ajoute(code, a, "plf", p["plf"], PAP[a])
    for code, p in np27["programmes"].items():
        ajoute(code, 2026, "lfi", p["lfi"], "pouvoirs_publics_np_senat_plf2027")
        ajoute(code, 2027, "plf", p["plf"], "pouvoirs_publics_np_senat_plf2027")
    for code, p in rap["programmes"].items():
        for an in (2024, 2025):
            ajoute(code, an, "prevu", p[f"prevu_{an}"], "pouvoirs_publics_rap_2025")
            ajoute(code, an, "execute", p[f"consomme_{an}"], "pouvoirs_publics_rap_2025")
    for code in ordre:
        for an, r in sorted(_realisations(code).items()):
            ajoute(code, an, "lfi", r.get("vote_lfi_eur"), "realisations", r.get("source"))
            ajoute(code, an, "execute", r.get("depense_constatee_eur"), "realisations", r.get("source"))

    connues = {k[1] for k in valeurs}
    annees = list(range(min(connues), max(connues) + 1))   # années sans document : présentes, à null
    ecarts = []
    programmes = []
    sans_credits = []
    for code in ordre:
        if all(v[0] == 0 for k, vs in valeurs.items() if k[0] == code for v in vs):
            sans_credits.append({"programme": code, "libelle": libelles[code],
                                 "annees_lues": sorted({k[1] for k in valeurs if k[0] == code})})
            continue
        serie = []
        for an in annees:
            ligne = {"annee": an}
            for g in ("lfi", "plf", "execute"):
                vs = valeurs.get((code, an, g), [])
                if not vs:
                    ligne[g] = None
                    ligne[f"source_{g}"] = None
                    continue
                # priorité aux documents budgétaires relus ici ; le dépôt (realisations) complète les années
                v, src, detail = next((x for x in vs if x[1] != "realisations"), vs[0])
                ligne[g] = float(v)
                ligne[f"source_{g}"] = src if src != "realisations" else "realisations : " + (detail or "")
                for v2, src2, detail2 in vs:
                    if float(v2) != float(v):
                        ecarts.append({"programme": code, "annee": an, "grandeur": g, "source": src,
                                       "montant_eur": float(v), "autre_source": src2 if src2 != "realisations"
                                       else "realisations : " + (detail2 or ""), "autre_montant_eur": float(v2),
                                       "ecart_eur": float(v2) - float(v)})
            serie.append(ligne)
        actions = {}
        for a in sorted(paps):
            for act in paps[a]["programmes"].get(code, {}).get("actions", []):
                e = actions.setdefault(act["code"], {"code": act["code"], "libelle": act["libelle"], "annees": {}})
                e["annees"].setdefault(a - 1, {})["lfi"] = float(act["lfi"])
                e["annees"].setdefault(a, {})["plf"] = float(act["plf"])
        programmes.append({
            "programme": code, "libelle": libelles[code], "institution": INSTITUTIONS.get(code),
            "annees": serie,
            "actions": [{"code": e["code"], "libelle": e["libelle"],
                         "annees": [{"annee": an, "lfi": v.get("lfi"), "plf": v.get("plf")}
                                    for an, v in sorted(e["annees"].items())]}
                        for e in actions.values() if len(code) == 3 and len(actions) > 1],
        })
    totaux = []
    for a, doc in sorted(paps.items()):
        totaux.append({"annee": a - 1, "grandeur": "lfi", "montant_eur": float(doc["total"]["lfi"]),
                       "source": PAP[a]})
        totaux.append({"annee": a, "grandeur": "plf", "montant_eur": float(doc["total"]["plf"]), "source": PAP[a]})
    totaux.append({"annee": 2026, "grandeur": "lfi", "montant_eur": float(np27["total"]["lfi"]),
                   "source": "pouvoirs_publics_np_senat_plf2027"})
    totaux.append({"annee": 2027, "grandeur": "plf", "montant_eur": float(np27["total"]["plf"]),
                   "source": "pouvoirs_publics_np_senat_plf2027"})
    vus = {}
    for t in totaux:   # même total publié par deux documents : on garde les deux s'ils diffèrent
        vus.setdefault((t["annee"], t["grandeur"]), []).append(t)
    totaux_publies = []
    for (an, g), ts in sorted(vus.items()):
        base = ts[0]
        totaux_publies.append(base)
        for t in ts[1:]:
            if t["montant_eur"] != base["montant_eur"]:
                ecarts.append({"programme": "total", "annee": an, "grandeur": g, "source": base["source"],
                               "montant_eur": base["montant_eur"], "autre_source": t["source"],
                               "autre_montant_eur": t["montant_eur"],
                               "ecart_eur": t["montant_eur"] - base["montant_eur"]})
    manquantes = [{"programme": p["programme"], "annee": l["annee"], "grandeur": g}
                  for p in programmes for l in p["annees"] for g in ("lfi", "execute")
                  if l[g] is None and l["annee"] <= (2026 if g == "lfi" else 2025)]
    return {
        "unite": "euros courants, crédits de paiement",
        "grandeurs": {
            "lfi": "crédits ouverts en loi de finances initiale (dotation votée)",
            "plf": "crédits demandés dans le projet de loi de finances (avant vote)",
            "prevu": "crédits prévus en loi de finances initiale, y compris fonds de concours et attributions de "
                     "produits (rapport annuel de performances)",
            "execute": "crédits consommés (dépense constatée de l'État : dotation versée à l'institution)"},
        "lecture": "Chaque montant porte son document source. Les années 2010 à 2025 de `execute` et les crédits "
                   "votés absents des annexes relues viennent de site/data/realisations/ (dépense constatée et "
                   "crédits votés du budget de l'État). Une année sans document lisible reste null.",
        "programmes": programmes,
        "programmes_sans_credits": sans_credits,
        "note_sans_credits": "Programmes de la mission dotés de 0 € dans toutes les années lues (montant publié, "
                             "pas une valeur absente) : listés à part.",
        "totaux_publies": totaux_publies,
        "ecarts": ecarts,
        "valeurs_absentes": manquantes,
        "note_absentes": "Années sans montant dans les documents relus ni dans site/data/realisations/ : null, "
                         "jamais 0 (voir index.json, sources_inaccessibles).",
    }


# ----------------------------------------------------------------------------------------------------------------
# Budgets des institutions
# ----------------------------------------------------------------------------------------------------------------

LIGNES_AN = [  # (code, poste, niveau) dans l'ordre du tableau de synthèse de l'annexe
    ("A", "Section de fonctionnement", 0), ("60", "Achats de biens et fournitures", 1),
    ("61-62", "Services extérieurs", 1), ("63", "Impôts et taxes", 1), ("64", "Charges de personnel", 1),
    ("64a", "dont charges de rémunération", 2), ("64b", "dont charges sociales et diverses", 2),
    ("65", "Charges parlementaires", 1), ("65a", "dont indemnités parlementaires", 2),
    ("65b", "dont charges sociales", 2), ("65c", "dont secrétariat parlementaire", 2),
    ("65d", "dont voyages et déplacements", 2), ("65e", "dont charges de représentation", 2),
    ("65f", "dont autres charges", 2), ("67-69", "Charges exceptionnelles et imprévues", 1),
    ("B", "Section d'investissement", 0), ("Ba", "Investissements immobiliers", 1),
    ("Bb", "Investissements informatiques", 1), ("Bc", "Autres investissements", 1),
    ("C", "Dépenses budgétaires totales (A+B)", 0), ("D", "Recettes budgétaires propres", 0),
    ("E", "Dotation de l'État", 0), ("F", "Solde budgétaire (D+E-C)", 0)]


def synthese_an(annee: int) -> dict:
    """Tableau « Budget <année> de l'Assemblée nationale (synthèse) » de l'annexe au PLF <année>."""
    ident = PAP[annee]
    lignes = lignes_pdf(ident)
    i0 = next((i for i, (_, c) in enumerate(lignes)
               if f"budget {annee} de l" in _norm(" ".join(c)) and "synthese" in _norm(" ".join(c))), None)
    if i0 is None:
        raise DonneeInattendue(f"{ident} : synthèse du budget de l'Assemblée introuvable")
    if annee <= 2024:
        colonnes = [("budget", annee - 2), ("realise", annee - 2), ("budget", annee - 1), ("budget", annee)]
    elif annee == 2025:
        colonnes = [("realise", annee - 2), ("budget", annee - 1), ("budget", annee)]
    else:
        colonnes = [("budget", annee - 1), ("budget", annee)]
    donnees = []
    for _, cellules in lignes[i0 + 1:]:
        if _norm(" ".join(cellules)).startswith("source"):
            break
        ms = [v for v in (montant(c) for c in cellules) if v is not None and abs(v) >= 1000]
        if sum(abs(v) >= 10000 for v in ms) >= 2:
            donnees.append(ms)
    if len(donnees) != len(LIGNES_AN):
        raise DonneeInattendue(f"{ident} : {len(donnees)} lignes chiffrées dans la synthèse, {len(LIGNES_AN)} attendues")
    table = {}
    for (code, poste, niveau), ms in zip(LIGNES_AN, donnees):
        if len(ms) < len(colonnes):
            raise DonneeInattendue(f"{ident} : ligne {code} incomplète")
        table[code] = dict(zip([f"{t}_{a}" for t, a in colonnes], ms[:len(colonnes)]))
    cols = list(table["A"])
    for c in cols:   # contrôles internes du tableau publié
        t = {k: v[c] for k, v in table.items()}
        controles = [("A", ["60", "61-62", "63", "64", "65", "67-69"]), ("64", ["64a", "64b"]),
                     ("65", ["65a", "65b", "65c", "65d", "65e", "65f"]), ("B", ["Ba", "Bb", "Bc"]), ("C", ["A", "B"])]
        for tot, parts in controles:
            if abs(sum(t[p] for p in parts) - t[tot]) > 2:
                raise DonneeInattendue(f"{ident} : {tot} ≠ somme {parts} ({c})")
        if abs(t["D"] + t["E"] - t["C"] - t["F"]) > 2:
            raise DonneeInattendue(f"{ident} : solde F incohérent ({c})")
    return {"document": ident,
            "colonnes": [{"cle": f"{t}_{a}", "nature": "budget initial" if t == "budget" else "réalisé", "annee": a}
                         for t, a in colonnes],
            "lignes": [{"code": code, "poste": poste, "niveau": niveau,
                        "valeurs_eur": {c: float(v) for c, v in table[code].items()}}
                       for code, poste, niveau in LIGNES_AN]}


def _ecarts_syntheses(syntheses: list[dict]) -> list[dict]:
    vus: dict[tuple, tuple] = {}
    ecarts = []
    for s in syntheses:
        for l in s["lignes"]:
            for cle, v in l["valeurs_eur"].items():
                k = (l["code"], cle)
                if k in vus and vus[k][0] != v:
                    ecarts.append({"code": l["code"], "poste": l["poste"], "colonne": cle, "document": vus[k][1],
                                   "montant_eur": vus[k][0], "autre_document": s["document"], "autre_montant_eur": v,
                                   "ecart_eur": v - vus[k][0]})
                vus.setdefault(k, (v, s["document"]))
    return ecarts


def an_2012_2017() -> dict:
    ident = "pouvoirs_publics_an_budgets_2012_2017"
    with zipfile.ZipFile(_fichier(ident)) as z:
        nom = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        brut = z.read(nom).decode("utf-8-sig")
    lecteur = list(csv.reader(io.StringIO(brut), delimiter=";"))
    entete = lecteur[0]
    colonnes = []
    for i, h in enumerate(entete[2:], start=2):
        m = re.search(r"(Budget|Réalisé) (\d{4})", h)
        if not m:
            raise DonneeInattendue(f"{ident} : colonne inattendue « {h} »")
        colonnes.append((i, ("budget" if m.group(1) == "Budget" else "realise") + "_" + m.group(2), h))
    lignes = []
    for r in lecteur[1:]:
        if len(r) < len(entete):
            continue
        code, libelle = r[0].strip(), r[1].strip()
        if not (re.fullmatch(r"\d{2}(?:/\d{2})?", code) or (not code and libelle)):
            continue
        vals = {}
        for i, cle, _ in colonnes:
            v = montant(r[i])
            if v is None and r[i].strip():
                raise DonneeInattendue(f"{ident} : montant illisible « {r[i]} »")
            vals[cle] = None if v is None else float(v)
        lignes.append({"code": code or None, "poste": re.sub(r"\s+", " ", libelle), "total": not code,
                       "valeurs_eur": vals})
    par = {l["poste"].strip().upper(): l for l in lignes if l["total"]}
    for cle in (c for _, c, _ in colonnes):
        inv = par["TOTAL SECTION D'INVESTISSEMENT"]["valeurs_eur"][cle]
        fon = par["TOTAL DES DEPENSES DE FONCTIONNEMENT"]["valeurs_eur"][cle]
        tot = par["DEPENSES TOTALES"]["valeurs_eur"][cle]
        if abs(inv + fon - tot) > 2:
            raise DonneeInattendue(f"{ident} : investissement + fonctionnement ≠ dépenses totales ({cle})")
    return {"document": ident,
            "colonnes": [{"cle": c, "nature": "budget" if c.startswith("budget") else "réalisé",
                          "annee": int(c[-4:]), "libelle_source": h} for _, c, h in colonnes],
            "lignes": lignes,
            "lecture": "Comptes à deux chiffres et totaux tels que publiés par l'Assemblée ; le détail des comptes à "
                       "trois et quatre chiffres reste dans le fichier source."}


def an_execution_2025() -> dict:
    ident = "pouvoirs_publics_an_rapport_comptes_2025"
    t = texte_pdf(ident)
    dep = _cherche(t, r"dépenses exécutées en 2025 s.élève à ([\d ,]+) M€", ident)
    rec = _cherche(t, r"recettes propres perçues, hors dotation, atteint ([\d ,]+) M€", ident)
    sol = _cherche(t, r"solde budgétaire déficitaire de ([–-]) ?([\d ,]+) M€", ident)
    inv = _cherche(t, r"s.établir à ([\d ,]+) M€, soit une baisse de [\d ,]+ % par rapport à l.exercice précédent",
                   ident)
    return {"document": ident, "annee": 2025, "nature": "exécution", "unite": "millions d'euros (arrondis du document)",
            "depenses_executees_meur": euros(dep.group(1)), "dont_investissement_meur": euros(inv.group(1)),
            "recettes_propres_meur": euros(rec.group(1)), "solde_budgetaire_meur": -euros(sol.group(2)),
            "lecture": "Montants cités dans le rapport de la commission spéciale (chiffres arrondis au million "
                       "d'euros près, deux décimales) ; la dotation de l'État 2025 est dans dotations.json."}


def senat_2025() -> dict:
    ident = "pouvoirs_publics_senat_budget"
    t = texte_html(ident)
    annee = int(_cherche(t, r"Les dépenses et les ressources du Sénat en (\d{4})", ident).group(1))
    entites = []
    for nom in ("Sénat", "Jardin du Luxembourg", "Musée du Luxembourg"):
        m = _cherche(t, re.escape(nom) + r" ?: ?([\d,]+) M€,? répartis en ([\d,]+) M€ de charges de fonctionnement "
                     r"et ([\d,]+) M€ d.investissement", ident)
        entites.append({"entite": nom, "depenses_meur": euros(m.group(1)),
                        "fonctionnement_meur": euros(m.group(2)), "investissement_meur": euros(m.group(3))})
    dot = euros(_cherche(t, r"La dotation de l.État ?: ?Elle s.élève à ([\d,]+) M€", ident).group(1))
    m = _cherche(t, r"Elles représentent ([\d,]+) M€, réparties entre le Sénat \(pour ([\d,]+) M€\), le Jardin "
                    r"\(pour ([\d,]+) M€\) et le Musée du Luxembourg \(pour ([\d,]+) M€\)", ident)
    sol = _cherche(t, r"Il ressort un (excédent|déficit) de ([\d,]+) M€", ident)
    ps = euros(_cherche(t, r"Public Sénat d.un montant stable de ([\d,]+) M€", ident).group(1))
    solde = euros(sol.group(2)) * (1 if sol.group(1) == "excédent" else -1)
    calcule = round(dot + euros(m.group(1)) - sum(e["depenses_meur"] for e in entites), 3)
    return {"document": ident, "annee": annee, "unite": "millions d'euros (arrondis de la page)",
            "nature": "montants publiés pour l'année ; la page ne précise pas s'il s'agit du budget ou de l'exécution",
            "entites": entites, "dotation_etat_meur": dot,
            "ressources_propres_meur": euros(m.group(1)),
            "ressources_propres_par_entite_meur": {"Sénat": euros(m.group(2)), "Jardin du Luxembourg": euros(m.group(3)),
                                                   "Musée du Luxembourg": euros(m.group(4))},
            "solde_publie_meur": solde,
            "solde_recalcule_meur": calcule,
            "ecart_solde_meur": round(solde - calcule, 3),
            "lecture_ecart": "Solde publié par la page face à dotation + ressources propres - dépenses recalculé "
                             "ici à partir des montants arrondis de la même page ; l'écart n'est pas corrigé.",
            "dotation_public_senat_meur": ps}


def presidence() -> dict:
    ident = "pouvoirs_publics_np_senat_plf2027"
    lignes = lignes_pdf(ident)
    i0 = next((i for i, (_, c) in enumerate(lignes) if "equilibre budgetaire de la presidence" in _norm(" ".join(c))),
              None)
    if i0 is None:
        raise DonneeInattendue(f"{ident} : tableau de l'équilibre de la Présidence introuvable")
    postes = {}
    for _, cellules in lignes[i0 + 1:i0 + 30]:
        nom = _norm(cellules[0])
        vals = [c for c in cellules[1:] if re.fullmatch(r"[+−–-]? ?\d+(?:,\d+)?", c.strip())]
        for cle, motif in (("dotation", "dotation"), ("produits_propres", "produits propres"),
                           ("depenses", "depenses"), ("solde", "solde")):
            if nom.startswith(motif) and len(vals) == 3 and cle not in postes:
                postes[cle] = [float(v.replace("−", "-").replace("–", "-").replace(" ", "").replace(",", "."))
                               for v in vals]
    if len(postes) != 4:
        raise DonneeInattendue(f"{ident} : équilibre de la Présidence incomplet ({sorted(postes)})")
    colonnes = [("execute_2025", "exécuté", 2025), ("budget_initial_2026", "budget initial", 2026),
                ("budget_2027", "budget proposé", 2027)]
    equilibre = {"document": ident, "unite": "millions d'euros (arrondis du document)",
                 "colonnes": [{"cle": c, "nature": n, "annee": a} for c, n, a in colonnes],
                 "lignes": [{"poste": lib, "valeurs_meur": dict(zip([c for c, _, _ in colonnes], postes[cle]))}
                            for cle, lib in (("dotation", "Dotation de l'État"), ("produits_propres", "Produits propres"),
                                             ("depenses", "Dépenses"), ("solde", "Solde"))]}
    for i, (c, _, _) in enumerate(colonnes):
        if abs(postes["dotation"][i] + postes["produits_propres"][i] - postes["depenses"][i] - postes["solde"][i]) > 0.06:
            raise DonneeInattendue(f"{ident} : équilibre de la Présidence incohérent ({c})")
    # Dépenses par grande destination : titres de l'annexe au PLF 2026
    ident2 = PAP[2026]
    t = texte_pdf(ident2)
    coupe = t.find("L’ÉLABORATION BUDGÉTAIRE 2026")
    if coupe < 0:
        coupe = t.find("L'ÉLABORATION BUDGÉTAIRE 2026")
    if coupe < 0:
        raise DonneeInattendue(f"{ident2} : partie « élaboration budgétaire 2026 » introuvable")
    fin = t.find("Assemblées parlementaires", coupe)

    def destinations(bloc: str) -> list[dict]:
        sortie = []
        for cle, motif in (("personnel", r"LES DÉPENSES DE PERSONNEL"),
                           ("hors_activite_presidentielle", r"LES DÉPENSES HORS ACTIVITÉS? PRÉSIDENTIELLES?"),
                           ("activite_presidentielle", r"LES DÉPENSES LIÉES À L.ACTIVIT[ÉE] PR[ÉE]SIDENTIELLE")):
            m = re.search(motif + r" \(([\d ]+) € EN AE(?:/CP| ET ([\d ]+) € EN CP)\)", bloc)
            if not m:
                raise DonneeInattendue(f"{ident2} : titre « {motif} » introuvable")
            ae = montant(m.group(1).strip())
            cp = montant(m.group(2).strip()) if m.group(2) else ae
            sortie.append({"destination": cle, "ae_eur": float(ae), "cp_eur": float(cp)})
        return sortie

    av = destinations(t[:coupe])
    ap = destinations(t[coupe:fin if fin > 0 else None])
    tot_av = sum(d["cp_eur"] for d in av)
    tot_ap = sum(d["cp_eur"] for d in ap)
    cite_av = euros(_cherche(t, r"prévisions d.exécution 2025 \(([\d,]+) M€\)", ident2).group(1))
    cite_ap = euros(_cherche(t, r"projet de budget 2026 s.établit à hauteur de ([\d,]+) M€", ident2).group(1))
    if round(tot_av / 1e6, 2) != cite_av or round(tot_ap / 1e6, 2) != cite_ap:
        raise DonneeInattendue(f"{ident2} : destinations de la Présidence ≠ totaux cités")
    libelles = {"personnel": "Dépenses de personnel",
                "hors_activite_presidentielle": "Dépenses hors activités présidentielles (administration, immobilier, "
                                                "investissement)",
                "activite_presidentielle": "Dépenses liées à l'activité présidentielle (déplacements, réceptions)"}
    for d in av + ap:
        d["libelle"] = libelles[d["destination"]]
    return {"equilibre": equilibre,
            "destinations": {"document": ident2, "unite": "euros",
                             "prevision_execution_2025": av, "budget_2026": ap,
                             "total_cp_prevision_execution_2025_eur": float(tot_av),
                             "total_cp_budget_2026_eur": float(tot_ap)}}


def conseil_constitutionnel() -> dict:
    ident = PAP[2026]
    lignes = lignes_pdf(ident)
    i0 = next((i for i, (_, c) in enumerate(lignes) if "repartition du budget 2026 entre les 4 actions"
               in _norm(" ".join(c))), None)
    if i0 is None:
        raise DonneeInattendue(f"{ident} : répartition du budget du Conseil constitutionnel introuvable")
    for _, cellules in lignes[i0 + 1:i0 + 40]:
        if _norm(cellules[0]) == "total":
            ms = [montant(c) for c in cellules[1:]]
            if len(ms) == 5 and None not in ms and sum(ms[:4]) == ms[4]:
                return {"document": ident, "annee": 2026, "nature": "budget prévisionnel", "unite": "euros",
                        "par_nature": [{"poste": p, "montant_eur": float(v)} for p, v in
                                       zip(("Membres", "Personnel", "Fonctionnement", "Investissement"), ms[:4])],
                        "total_eur": float(ms[4])}
    raise DonneeInattendue(f"{ident} : ligne Total du Conseil constitutionnel introuvable")


def cour_justice() -> dict:
    ident = PAP[2026]
    lignes = lignes_pdf(ident)
    i0 = next((i for i, (_, c) in enumerate(lignes) if _norm(" ".join(c)).startswith("dotation demandee (en")), None)
    if i0 is None:
        raise DonneeInattendue(f"{ident} : tableau de la Cour de justice de la République introuvable")
    postes, total = [], None
    for _, cellules in lignes[i0 + 1:i0 + 12]:
        if len(cellules) != 3:
            continue
        lib, a, b = cellules
        v1, v2 = montant(a), montant(b)
        if _norm(lib) == "total":
            total = (v1, v2)
            break
        postes.append({"poste": lib, "plf_2025_eur": None if v1 is None else float(v1),
                       "plf_2026_eur": None if v2 is None else float(v2),
                       **({"valeur_source_illisible": {"plf_2025": a}} if v1 is None else {}),
                       **({"valeur_source_illisible": {"plf_2026": b}} if v2 is None else {})})
    if total is None or len(postes) < 4:
        raise DonneeInattendue(f"{ident} : tableau de la Cour de justice de la République incomplet")
    controles = {}
    for i, cle in enumerate(("plf_2025", "plf_2026")):
        s = sum(p[f"{cle}_eur"] or 0 for p in postes)
        controles[cle] = {"total_publie_eur": float(total[i]), "somme_des_lignes_lisibles_eur": float(s),
                          "ecart_eur": float(total[i] - s)}
    return {"document": ident, "unite": "euros", "nature": "dotation demandée par poste", "postes": postes,
            "controles": controles,
            "lecture": "Une cellule que la source écrit de façon illisible (par exemple « 530 00 ») reste null, avec le "
                       "texte de la source ; l'écart au total publié est montré, jamais corrigé."}


def budgets() -> dict:
    return {
        "unite": "euros courants sauf mention (millions d'euros quand le document ne donne que des arrondis)",
        "lecture": "Budgets propres des institutions (dépenses, recettes propres, dotation de l'État, solde), tels que "
                   "publiés. Les tableaux ne s'additionnent pas entre eux : documents, années et natures (budget "
                   "initial, réalisé, exécuté) diffèrent.",
        "assemblee_nationale": {
            "syntheses": (syntheses := [synthese_an(a) for a in sorted(PAP)]),
            "ecarts_entre_annexes": _ecarts_syntheses(syntheses),
            "lecture_ecarts": "Même colonne (par exemple le budget 2025) publiée par deux annexes successives avec "
                              "des montants différents (budget révisé entre-temps) : les deux montants sont gardés.",
            "comptes_2012_2017": an_2012_2017(),
            "execution_2025": an_execution_2025(),
        },
        "senat": {"montants_2025": senat_2025()},
        "presidence": presidence(),
        "conseil_constitutionnel": conseil_constitutionnel(),
        "cour_justice_republique": cour_justice(),
    }


# ----------------------------------------------------------------------------------------------------------------
# Indemnités par fonction
# ----------------------------------------------------------------------------------------------------------------

MOIS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}


def _date_iso(texte: str | None) -> str | None:
    """« 1er janvier 2024 » -> « 2024-01-01 »"""
    if not texte:
        return None
    m = re.fullmatch(r"(\d{1,2})(?:er)? (\w+) (\d{4})", texte)
    if not m or m.group(2) not in MOIS:
        raise DonneeInattendue(f"date illisible « {texte} »")
    return f"{m.group(3)}-{MOIS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def _montant_cite(texte: str, motif: str, ident: str) -> float:
    return euros(_cherche(texte, motif + r" ?:? ?([\d ]+,\d{2}) ?€", ident).group(1))


def indemnites() -> dict:
    an, se, sm, qe = ("pouvoirs_publics_an_situation_materielle", "pouvoirs_publics_senat_indemnite",
                      "pouvoirs_publics_senat_moyens", "pouvoirs_publics_qe_traitement_president")
    ta, ts, tm, tq = texte_pdf(an), texte_html(se), texte_html(sm), texte_pdf(qe)
    date_an = _cherche(ta, r"Depuis le (1er janvier \d{4}), les indemnités mensuelles brutes", an).group(1)
    date_se = _cherche(ts, r"Au (1er janvier \d{4}), après prise en compte", se).group(1)
    lignes = []

    def ligne(institution, fonction, composante, v, source, date, nature="publié", montant_net=False, **extra):
        lignes.append({"institution": institution, "fonction": fonction, "composante": composante,
                       "montant_mensuel_eur": v, "brut_ou_net": "net" if montant_net else "brut", "statut": nature,
                       "source": source, "en_vigueur": _date_iso(date), "en_vigueur_texte": date, **extra})

    base = _montant_cite(ta, r"indemnité de base", an)
    for composante, motif in (("indemnité parlementaire de base", r"indemnité de base"),
                              ("indemnité de résidence (3 %)", r"indemnité de résidence \(3 %\)"),
                              ("indemnité de fonction (25 %)", r"indemnité de fonction \(25 % du total\)"),
                              ("total brut mensuel", r"Soit brut mensuel")):
        ligne("Assemblée nationale", "Député", composante, _montant_cite(ta, motif, an), an, date_an)
    ligne("Assemblée nationale", "Député", "net mensuel après retenues (avant impôt sur le revenu)",
          _montant_cite(ta, r"Soit un montant net mensuel de", an), an, date_an, montant_net=True)
    for fonction, motif in (("Président de l'Assemblée nationale", r"– Président"), ("Questeur", r"– Questeurs"),
                            ("Vice-président", r"– Vice-présidents"),
                            ("Président de commission ou rapporteur général", r"Présidents de commission et rapporteurs "
                             r"généraux de la commission des finances et de la commission des affaires sociales"),
                            ("Président de la commission spéciale chargée d'apurer les comptes",
                             r"Président de la commission spéciale chargée d.apurer les comptes"),
                            ("Président de l'Office d'évaluation des choix scientifiques et technologiques",
                             r"Président de l.Office d.évaluation des choix scientifiques et technologiques"),
                            ("Secrétaire du Bureau", r"Secrétaires du Bureau")):
        ligne("Assemblée nationale", fonction, "indemnité spéciale de fonction, en plus de l'indemnité de député",
              _montant_cite(ta, motif, an), an, date_an)
    date_dfp = _cherche(ta, r"Depuis le (1er janvier \d{4}), pour faire face aux diverses dépenses", an).group(1)
    ligne("Assemblée nationale", "Député", "dotation de fonctionnement parlementaire (frais de mandat, élu en "
          "métropole) : enveloppe, pas une rémunération",
          _montant_cite(ta, r"montant mensuel de cette dotation est de", an), an, date_dfp, enveloppe=True)
    credit = euros(_cherche(ta, r"rémunération de collaborateurs qui s.élève à ([\d ]+) € par mois", an).group(1))
    ligne("Assemblée nationale", "Député", "crédit collaborateurs (rémunération des collaborateurs) : enveloppe, pas "
          "une rémunération", credit, an, None, enveloppe=True)

    for composante, motif in (("indemnité parlementaire de base", r"indemnité parlementaire de base"),
                              ("indemnité de résidence (3 %)", r"indemnité de résidence"),
                              ("indemnité de fonction (25 %)", r"indemnité de fonction")):
        ligne("Sénat", "Sénateur", composante, _montant_cite(ts, r"se décompose de la façon suivante.*?" + motif
                                                             if composante.startswith("indemnité parlementaire")
                                                             else motif + r"(?= ?: ?[\d ]+,\d{2} ?€ ?[;.])", se),
              se, date_se)
    ligne("Sénat", "Sénateur", "total brut mensuel",
          _montant_cite(ts, r"le montant brut mensuel de l.indemnité parlementaire s.élève à", se), se, date_se)
    ligne("Sénat", "Sénateur", "net mensuel après retenues (avant impôt sur le revenu)",
          _montant_cite(ts, r"impôt sur le revenu s.élève en conséquence à", se), se, date_se, montant_net=True)
    ligne("Sénat", "Président du Sénat", "indemnité de fonction, en plus de l'indemnité de sénateur",
          _montant_cite(ts, r"une indemnité de fonction de", se), se, date_se)
    for fonction, motif in (("Vice-président du Bureau", "pour les vice-présidents du Bureau"),
                            ("Questeur", "pour les questeurs"), ("Secrétaire du Bureau", "pour les secrétaires du Bureau"),
                            ("Président de groupe politique", "pour les présidents de groupe politique"),
                            ("Président de commission ou rapporteur général",
                             "pour les présidents de commission et les rapporteurs généraux"),
                            ("Président de délégation", "pour les présidents de délégation"),
                            ("Président de l'Office parlementaire d'évaluation des choix scientifiques et technologiques",
                             "pour le président de l.Office parlementaire")):
        m = _cherche(ts, r"([\d ]+,\d{2}) ?€ " + motif, se)
        ligne("Sénat", fonction, "indemnité de fonction, en plus de l'indemnité de sénateur", euros(m.group(1)), se,
              date_se)
    m = _cherche(tm, r"crédit mensuel de ([\d ]+,\d{2}) ?€ bruts \(au (1er \w+ \d{4})\)", sm)
    ligne("Sénat", "Sénateur", "crédit collaborateurs (rémunération brute de base de l'équipe) : enveloppe, pas une "
          "rémunération", euros(m.group(1)), sm, m.group(2), enveloppe=True)

    # Président de la République et Premier ministre : règle citée par le Gouvernement, montant calculé ici
    for motif in (r"au double de la moyenne du traitement le plus bas et du traitement le plus élevé",
                  r"indemnité de résidence égale à 3 % de son montant",
                  r"indemnité de fonction égale à 25 % de la somme du traitement brut et de l.indemnité de résidence",
                  r"est majoré de 5 %"):
        _cherche(tq, motif, qe)
    base_se = _cherche(ts, r"équivalente à la moyenne du traitement le plus bas \(lettre A\) et du traitement le plus "
                           r"haut \(lettre G\)", se)
    del base_se
    traitement = 2 * base
    residence = traitement * 0.03
    fonction = (traitement + residence) * 0.25
    total = round((traitement + residence + fonction) * 1.05, 2)
    for fonc in ("Président de la République",):
        ligne("Exécutif", fonc, "traitement brut mensuel avec indemnités de résidence et de fonction, majoré de 5 %",
              total, qe, date_an, nature="calculé",
              formule="2 × indemnité parlementaire de base (moyenne du traitement le plus bas et du plus élevé de la "
                      "catégorie hors échelle) = traitement ; + 3 % (résidence) ; + 25 % de la somme (fonction) ; "
                      "ensemble majoré de 5 %",
              entrees={"indemnite_parlementaire_de_base_eur": base, "source_base": an},
              limite="Le décret fixe un plafond (« au plus égal ») ; le montant effectivement versé n'est pas publié "
                     "dans les documents lus. Calcul du site, sans arrondi intermédiaire.")
    for fonc in ("Premier ministre", "Ministre, ministre délégué ou secrétaire d'État"):
        ligne("Exécutif", fonc, "traitement brut mensuel", None, None, None, nature="non publié dans les sources lues",
              mention="Montant fixé par le décret n° 2012-983 du 23 août 2012, inaccessible au collecteur "
                      "(Légifrance, HTTP 403) ; la réponse du Gouvernement lue ne décrit que le traitement du "
                      "Président de la République : null, jamais estimé.")
    return {"unite": "euros par mois (brut sauf `brut_ou_net` = net)",
            "lecture": "Barèmes par fonction, jamais par personne. Une indemnité spéciale ou de fonction s'ajoute à "
                       "l'indemnité de base du parlementaire. Les enveloppes (frais de mandat, crédit collaborateurs) "
                       "ne sont pas une rémunération de l'élu et ne s'additionnent pas aux indemnités.",
            "lignes": lignes}


# ----------------------------------------------------------------------------------------------------------------
# Production
# ----------------------------------------------------------------------------------------------------------------

def _ecrire(chemin: Path, doc: dict) -> int:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    octets = len(texte.encode("utf-8"))
    if octets > 1_000_000:
        raise DonneeInattendue(f"{chemin.name} dépasse 1 Mo ({octets} octets)")
    chemin.write_text(texte, encoding="utf-8")
    return octets


def _sources(ids: list[str]) -> list[dict]:
    man = _manifeste()
    sortie = []
    for ident in ids:
        e = man.get(ident, {})
        f = (e.get("fichiers") or [{}])[0]
        sortie.append({"id": ident, **SOURCES[ident], "url": f.get("url"), "licence": e.get("licence"),
                       "collecte_le": (e.get("collecte_le") or "")[:10] or None, "sha256": f.get("sha256")})
    return sortie


def produire(sortie: Path = SORTIE) -> None:
    jour = date_sources(DOMAINE)
    entete = {"millesime": "LFI 2011 à 2026, PLF 2027, exécution 2010 à 2025 ; barèmes publiés, lus en novembre 2026",
              "date_sources": jour}
    docs = {
        "dotations.json": ("Dotations de la mission « Pouvoirs publics » par programme et par année (voté, demandé, "
                           "exécuté), actions, totaux publiés, écarts entre sources", dotations()),
        "budgets.json": ("Budgets publiés de l'Assemblée nationale, du Sénat, de la Présidence de la République, du "
                         "Conseil constitutionnel et de la Cour de justice de la République (grandes masses)",
                         budgets()),
        "indemnites.json": ("Barèmes des indemnités par fonction (députés, sénateurs, Président de la République, "
                            "Premier ministre)", indemnites()),
    }
    ids_par_fichier = {
        "dotations.json": [*PAP.values(), "pouvoirs_publics_rap_2025", "pouvoirs_publics_np_senat_plf2027"],
        "budgets.json": [*PAP.values(), "pouvoirs_publics_np_senat_plf2027", "pouvoirs_publics_an_budgets_2012_2017",
                         "pouvoirs_publics_an_rapport_comptes_2025", "pouvoirs_publics_senat_budget"],
        "indemnites.json": ["pouvoirs_publics_an_situation_materielle", "pouvoirs_publics_senat_indemnite",
                            "pouvoirs_publics_senat_moyens", "pouvoirs_publics_qe_traitement_president"],
    }
    fichiers = []
    for nom, (contenu, doc) in docs.items():
        srcs = _sources(ids_par_fichier[nom])
        corps = {**entete, "source": " ; ".join(s["url"] or s["id"] for s in srcs)
                 + (" ; site/data/realisations/5*.json" if nom == "dotations.json" else ""),
                 "avertissement": AVERTISSEMENT, **doc, "sources": srcs}
        fichiers.append({"fichier": f"pouvoirs_publics/{nom}", "contenu": contenu,
                         "octets": _ecrire(sortie / nom, corps)})
    dot = docs["dotations.json"][1]
    tot = {(t["annee"], t["grandeur"]): t["montant_eur"] for t in dot["totaux_publies"]}
    reperes = {
        "total_mission_lfi_2026_eur": tot.get((2026, "lfi")),
        "total_mission_plf_2027_eur": tot.get((2027, "plf")),
        "dotations_lfi_2026": [{"programme": p["programme"], "libelle": p["libelle"],
                                "montant_eur": next((l["lfi"] for l in p["annees"] if l["annee"] == 2026), None)}
                               for p in dot["programmes"] if len(p["programme"]) == 3],
        "lecture": "Repères de la dernière loi de finances initiale (2026) et du projet pour 2027 (totaux publiés) ; "
                   "détail et exécution dans dotations.json.",
    }
    index = {**entete, "source": "documents budgétaires « Pouvoirs publics », Assemblée nationale, Sénat (voir "
                                 "sources[])", "avertissement": AVERTISSEMENT,
             "fichiers": fichiers, "reperes": reperes,
             "limites": [
                 "Crédits votés 2015 à 2017 : absents (annexes de ces années inaccessibles, absentes de "
                 "site/data/realisations/).",
                 "Budget détaillé de l'Assemblée nationale : 2012 à 2017 (open data) puis tableaux de synthèse des "
                 "annexes 2022 à 2026 (réalisé 2020 à 2023, budgets 2020 à 2026) et exécution 2025 du rapport "
                 "sur les comptes ; 2018 et 2019 absents.",
                 "Budget du Sénat : montants de la page du Sénat, année 2025 (tableaux de l'annexe publiés "
                 "en images).",
                 "Indemnités : barèmes en vigueur à la date des pages lues ; traitement des membres du Gouvernement "
                 "autres que le Premier ministre non repris.",
                 "La Cour de justice de la République et le Conseil constitutionnel n'ont pas de barème "
                 "d'indemnité par fonction dans les documents lus."],
             "sources": _sources(list(SOURCES)), "sources_inaccessibles": INACCESSIBLES,
             "recherche_publique": RECHERCHE_PUBLIQUE}
    _ecrire(sortie / "index.json", index)


def collecter() -> int:
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *SOURCES, "--timeout", "560"])


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
