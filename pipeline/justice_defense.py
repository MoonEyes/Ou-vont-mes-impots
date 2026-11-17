"""Justice et défense : établissements pénitentiaires, budget de la justice, ressorts des juridictions,
exportations d'armement.

Uniquement des agrégats publiés : capacité et personnes détenues par établissement (aucun individu), budget par
programme, frais de justice, aide juridictionnelle, juridiction compétente par commune, prises de commandes,
livraisons et licences d'exportation par pays et par catégorie. Rien de classifié : seuls les documents publiés
déclarés dans collecte/catalogue.json (entrées `justice_defense_*`) sont lus.

Commandes :
    python pipeline/justice_defense.py collecter   (réseau, par collecte/collecte.py ; un refus 401/403/429 est
                                                   noté, jamais contourné)
    python pipeline/justice_defense.py produire [--sortie DOSSIER]   (sans réseau ; lit data/lake/justice_defense/
                                                   et site/data/realisations/107.json en lecture seule)

Sorties (site/data/justice_defense/, contrat docs/contrat_interface.md, schémas docs/schemas/justice_defense_*) :
    index.json, prisons.json, budget_justice.json, ressorts.json, armement.json

Règles : une valeur absente ou un tiret à la source reste null, jamais 0 ; un total publié qui ne retombe pas sur
la somme de ses lignes est publié avec son écart, jamais corrigé ; le montant par établissement est un calcul du
site, marqué « calculé » avec sa formule ; colonnes de voie, code postal, coordonnées, téléphone et courriel des
juridictions jamais lues. Dates par pipeline/reproductible.py : deux productions sur le même entrepôt sont
identiques octet pour octet.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import re
import subprocess
import sys
import unicodedata
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "justice_defense"
MANIFESTE = ROOT / "data" / "lake" / "manifest.json"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "justice_defense"
DOMAINE = "justice_defense"

SOURCES = {
    "population_ecrouee": {
        "id_catalogue": "justice_defense_population_ecrouee",
        "titre": "Statistique mensuelle de la population écrouée et détenue en France (ministère de la Justice, "
                 "direction de l'administration pénitentiaire)",
        "page": "https://www.data.gouv.fr/datasets/5369a048a3a729239d206322",
        "licence": "Licence Ouverte 2.0"},
    "ressorts": {
        "id_catalogue": "justice_defense_structures_justice",
        "titre": "Données géocodées des structures de la Justice : juridictions compétentes par commune "
                 "(ministère de la Justice)",
        "page": "https://www.data.gouv.fr/datasets/5369932fa3a729239d20410c",
        "licence": "Licence Ouverte 2.0"},
    "juridictions": {
        "id_catalogue": "justice_defense_juridictions",
        "titre": "Données géocodées des structures de la Justice : liste des juridictions et commune d'implantation "
                 "(ministère de la Justice)",
        "page": "https://www.data.gouv.fr/datasets/5369932fa3a729239d20410c",
        "licence": "Licence Ouverte 2.0"},
    "effectifs_defense": {
        "id_catalogue": "justice_defense_effectifs_defense_2025",
        "titre": "Répartition des effectifs militaires et civils par catégorie et BOP en 2025 (ministère des Armées)",
        "page": "https://www.data.gouv.fr/datasets/53699ef2a3a729239d205fea",
        "licence": "Licence Ouverte 2.0"},
    "chiffres_cles": {
        "id_catalogue": "justice_defense_chiffres_cles_justice_2026",
        "titre": "Les chiffres clés de la Justice, édition 2026 (ministère de la Justice)",
        "page": "https://www.justice.gouv.fr/sites/default/files/2026-10/Chiffres_cles_Justice_2026.pdf",
        "licence": "document administratif public"},
    "armement": {
        "id_catalogue": "justice_defense_rapport_exportations_armement_2025",
        "titre": "Rapport au Parlement 2025 sur les exportations d'armement de la France (ministère des Armées)",
        "page": "https://www.vie-publique.fr/files/rapport/pdf/300296.pdf",
        "licence": "document administratif public"},
}

# Constat du 17/11/2026 sur la ressource des effectifs (empreinte du fichier collecté) : une seule feuille,
# « new_metadonnees », sans aucune valeur chiffrée. Si l'empreinte change, l'index le signale (`a_relire`).
EFFECTIFS_CONSTAT = {
    "date": "2026-11-17",
    "sha256": "e26acf9c1148eb41190b6a712002f4913b040de3096cf7d8bf6590019b3e55aa",
    "constat": "La seule ressource publiée est un classeur de métadonnées (feuille « new_metadonnees » : titre, "
               "description, licence, couverture) ; il ne contient aucun effectif par catégorie ni par BOP. Le jeu "
               "renvoie au rapport social unique 2025, qui ne fait pas partie des documents retenus.",
}

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "conclusion": "Les producteurs publient déjà les agrégats (classeurs mensuels par établissement, table des "
                  "ressorts, tableaux des annexes du rapport au Parlement) : ils sont repris tels quels. Aucun dépôt "
                  "public trouvé ne lit ces documents français ; les dépôts sur les transferts d'armes lisent la base "
                  "du SIPRI, une autre source dans une autre unité. Module écrit pour le dépôt, sur le modèle de "
                  "pipeline/prestations.py et pipeline/europe_comparaison.py.",
    "trouvailles": [
        {"nom": "Statistique mensuelle de la population écrouée et détenue (data.gouv.fr, 106 classeurs xlsx)",
         "url": "https://www.data.gouv.fr/datasets/5369a048a3a729239d206322", "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-10-13"},
        {"nom": "Données géocodées des structures de la Justice (data.gouv.fr)",
         "url": "https://www.data.gouv.fr/datasets/5369932fa3a729239d20410c", "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-05-19"},
        {"nom": "Les chiffres clés de la Justice 2026 (PDF)",
         "url": "https://www.justice.gouv.fr/sites/default/files/2026-10/Chiffres_cles_Justice_2026.pdf",
         "verdict": "à adapter", "licence": "document administratif public (tableaux relus par position dans le PDF)",
         "mise_a_jour": "2026-10"},
        {"nom": "Rapport au Parlement 2025 sur les exportations d'armement (PDF, annexes 5, 6, 8 et 9)",
         "url": "https://www.vie-publique.fr/files/rapport/pdf/300296.pdf", "verdict": "à adapter",
         "licence": "document administratif public (tableaux relus par position dans le PDF)", "mise_a_jour": "2025"},
        {"nom": "collecte/collecte.py et pipeline/reproductible.py, dépôt du projet", "url": "collecte/collecte.py",
         "verdict": "réutilisable tel quel", "licence": "MIT", "mise_a_jour": "2026-11-17"},
        {"nom": "benryan58/sipri_arms (accès non officiel à la base SIPRI des transferts d'armes)",
         "url": "https://github.com/benryan58/sipri_arms", "verdict": "inspiration seulement",
         "licence": "MIT (source et unité différentes : indicateur TIV du SIPRI, non retenu)",
         "mise_a_jour": "2020-10-26"},
        {"nom": "justin-2028/Arms-Imports-Per-Country-1950-2020 (extraits SIPRI)",
         "url": "https://github.com/justin-2028/Arms-Imports-Per-Country-1950-2020",
         "verdict": "inspiration seulement", "licence": "MIT (source différente, non retenue)",
         "mise_a_jour": "2023-03-03"},
        {"nom": "Recherche GitHub « prisons france », « surpopulation carcerale », « armement exportations »",
         "url": "https://github.com/search?q=prisons+france&type=repositories", "verdict": "inspiration seulement",
         "licence": "sans objet (aucun dépôt lisant ces jeux)", "mise_a_jour": "2026-11-17"},
    ],
}

MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
PROGRAMMES_JUSTICE = [  # libellé abrégé du graphique des chiffres clés -> programme ; vérifié contre realisations/
    ("Justice judiciaire", "166"), ("Administration pénitentiaire", "107"),
    ("Protection judiciaire de la jeunesse", "182"), ("Accès au droit et à la justice", "101"),
    ("Conduite et pilotage de la politique de la justice", "310"), ("Conseil supérieur de la magistrature", "335")]


class DonneeInattendue(RuntimeError):
    """La source ne ressemble plus à ce que le module sait lire : on s'arrête plutôt que de publier un chiffre faux."""


# --------------------------------------------------------------------------------------------------------------------
# utilitaires

def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _cle_nom(s) -> str:
    """Capitales sans accents ni ponctuation ; ST et STE développés (libellés de communes et d'établissements)."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    mots = re.sub(r"[^A-Z0-9]+", " ", s).split()
    return " ".join({"ST": "SAINT", "STE": "SAINTE"}.get(m, m) for m in mots)


def nombre(x) -> float | None:
    """Nombre publié (« 1 187 », « 202,6 % », 2138.0) ; vide, tiret, « nd », « nc » : None, jamais 0."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(" ", "").replace("\xa0", "").replace(" ", "").replace("%", "").replace("+", "")
    s = s.replace(",", ".").replace("−", "-")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return None
    return float(s)


def _entier(x) -> int | None:
    v = nombre(x)
    return None if v is None else int(round(v))


def _manifeste() -> dict:
    try:
        return json.loads(MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fichiers(cle: str, suffixe: str) -> list[Path]:
    ident = SOURCES[cle]["id_catalogue"]
    seul = LAKE / f"{ident}{suffixe}"
    if seul.exists():
        return [seul]
    return sorted((LAKE / ident).glob(f"*{suffixe}"))


def _departement(insee: str) -> str:
    return insee[:3] if insee[:2] in ("97", "98") else insee[:2]


def _lignes_mots(page, tol: float = 3.0) -> list[list[dict]]:
    """Mots d'une page PDF regroupés par ligne (ordonnée proche), de gauche à droite."""
    lignes: list[list[dict]] = []
    mots = [w for w in page.extract_words(extra_attrs=["upright"]) if w.get("upright", True)]  # sans la marge verticale
    for m in sorted(mots, key=lambda w: (w["top"], w["x0"])):
        if lignes and abs(lignes[-1][0]["top"] - m["top"]) <= tol:
            lignes[-1].append(m)
        else:
            lignes.append([m])
    return [sorted(li, key=lambda w: w["x0"]) for li in lignes]


# --------------------------------------------------------------------------------------------------------------------
# établissements pénitentiaires

def _date_dans(cellules) -> str | None:
    for c in cellules:
        m = re.search(r"(?:1er|\b\d{1,2})\s+([a-zéû]+)\s+(\d{4})", _norm(c).replace("1er", "1er "))
        if m and m.group(1) in MOIS:
            return f"{m.group(2)}-{MOIS[m.group(1)]:02d}-01"
    return None


def _lignes_feuille(ws) -> list[list]:
    ws.reset_dimensions()  # certains classeurs déclarent une seule cellule : on relit la feuille entière
    return [list(r) for r in ws.iter_rows(values_only=True)]


def lire_classeur(chemin: Path) -> dict:
    """Date de situation, totaux nationaux (tableau 6) et lignes par établissement (format publié depuis 2023)."""
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    try:
        res = {"fichier": chemin.name, "date": None, "national": None, "metropole": None, "outre_mer": None,
               "etablissements": [], "totaux_disp": []}
        for nom in wb.sheetnames:
            n = _norm(nom).replace(" ", "")
            if re.match(r"tab6(?!\d)", n):
                lignes = _lignes_feuille(wb[nom])
                res["date"] = _date_dans(c for li in lignes[:10] for c in li if isinstance(c, str))
                for li in lignes:
                    vals = [c for c in li if c is not None and str(c).strip() != ""]
                    if not vals or not isinstance(vals[0], str):
                        continue
                    t = _norm(vals[0])
                    cle = ("national" if t.startswith(("ensemble des etablissements", "total france")) else
                           "metropole" if t == "metropole" else "outre_mer" if t.startswith("outre") else None)
                    nb = [nombre(v) for v in vals[1:5]]
                    if cle and len(nb) >= 4 and None not in nb[:3]:
                        res[cle] = {"capacite_norme": int(nb[0]), "capacite_operationnelle": int(nb[1]),
                                    "detenus": int(nb[2]), "densite_pct": None if nb[3] is None else round(nb[3], 1)}
            elif re.match(r"tab(1[4-9]|2[0-3])$", n):
                lignes = _lignes_feuille(wb[nom])
                titre = next((c for c in (lignes[0] if lignes else []) if isinstance(c, str)), "")
                m = re.search(r"par [ée]tablissement\s*-\s*(Direction[^(]*)", titre)
                if not m:
                    continue  # ancien format (2014-2019, par quartier, autres libellés) : non repris par établissement
                disp = re.sub(r"\s+", " ", m.group(1)).strip()
                i0 = next((i for i, li in enumerate(lignes) if li and _norm(li[0]) == "etablissement"), None)
                if i0 is None or _norm(lignes[i0][3]) != "capacite operationnelle":
                    raise DonneeInattendue(f"{chemin.name} / {nom} : en-tête du tableau par établissement non reconnu")
                for li in lignes[i0 + 1:]:
                    if not li or li[0] is None or str(li[0]).strip().startswith("("):
                        break
                    li = li + [None] * 6
                    ligne = {"etablissement": str(li[0]).strip(), "quartier": str(li[1] or "").strip(),
                             "disp": disp, "capacite_norme": _entier(li[2]), "capacite_operationnelle": _entier(li[3]),
                             "detenus": _entier(li[4]), "densite_pct": nombre(li[5])}
                    if _norm(li[0]) == "total":
                        continue  # sous-total par type de quartier : recalculable, non repris
                    if _norm(li[0]).startswith("direction"):
                        res["totaux_disp"].append(ligne | {"etablissement": None, "quartier": None})
                    else:
                        res["etablissements"].append(ligne)
        return res
    finally:
        wb.close()


def lire_ressorts() -> dict:
    """Table commune -> cour d'appel, tribunal judiciaire, tribunal de proximité, conseil de prud'hommes."""
    f = _fichiers("ressorts", ".csv")
    if not f:
        raise FileNotFoundError("table des ressorts absente : python pipeline/justice_defense.py collecter")
    lignes = list(csv.reader(io.StringIO(f[0].read_text(encoding="utf-8-sig")), delimiter=";"))
    attendu = ["Commune", "Libellé Commune", "Orig. CA", "N° CA", "Cour d'Appel compétente", "Orig. TJ", "N° TJ",
               "Tribunal judiciaire compétent", "Orig. TPRX", "N° TPRX", "Tribunal de proximité compétent",
               "Orig. CPH", "N° CPH", "Conseil de Prud'hommes compétent"]
    if lignes[0] != attendu:
        raise DonneeInattendue(f"colonnes de la table des ressorts modifiées : {lignes[0]}")
    tables = {"cours_appel": {}, "tribunaux_judiciaires": {}, "tribunaux_proximite": {}, "conseils_prudhommes": {}}
    colonnes = [("cours_appel", 3, 4), ("tribunaux_judiciaires", 6, 7), ("tribunaux_proximite", 9, 10),
                ("conseils_prudhommes", 12, 13)]
    communes = []
    for li in lignes[1:]:
        if len(li) < 14 or not re.fullmatch(r"[0-9AB]{5}", li[0]):
            continue
        ligne = [li[0]]
        for cle, i_num, i_nom in colonnes:
            num = li[i_num].strip()
            if num:
                tables[cle].setdefault(num, li[i_nom].strip())
            ligne.append(int(num) if num else None)
        communes.append(ligne)
    communes.sort(key=lambda x: x[0])
    return {"fichier": f[0].name, "communes": communes, "tables": tables}


def lire_juridictions() -> dict:
    """Liste des juridictions : type, numéro, nom et commune. Voie, code postal, coordonnées, téléphone, courriel :
    colonnes jamais lues."""
    f = _fichiers("juridictions", ".csv")
    if not f:
        raise FileNotFoundError("liste des juridictions absente : python pipeline/justice_defense.py collecter")
    garde = ("TYPE", "CODE_INSEE", "NUM", "NOM_ETABLISSEMENT")
    lecteur = csv.reader(io.StringIO(f[0].read_text(encoding="utf-8-sig")), delimiter=";")
    entete = next(lecteur)
    if not set(garde) <= set(entete):
        raise DonneeInattendue(f"colonnes de la liste des juridictions modifiées : {entete}")
    idx = [entete.index(c) for c in garde]
    juridictions = []
    for li in lecteur:
        if len(li) <= max(idx):
            continue
        typ, insee, num, nom = (li[i].strip() for i in idx)
        if not typ or not nom:
            continue
        ok = bool(re.fullmatch(r"[0-9AB]{5}", insee))
        juridictions.append({"type": typ, "numero": num or None, "nom": re.sub(r"\s+", " ", nom),
                             "commune_insee": insee if ok else None, "departement": _departement(insee) if ok else None})
    juridictions.sort(key=lambda j: (j["type"], _cle_nom(j["nom"]), j["numero"] or ""))
    return {"fichier": f[0].name, "juridictions": juridictions}


def _depense_107() -> dict:
    """Dépense constatée du programme 107 par année (site/data/realisations/107.json, déjà publié)."""
    f = SITE / "realisations" / "107.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    indic = [i for i in ((d.get("resultats_mesures") or {}).get("indicateurs") or [])
             if re.search(r"journee de detention", _norm(i.get("indicateur", "") + " " + i.get("sous_indicateur", "")))]
    annees = {int(a["annee"]): a for a in d["prevu_depense"]["annees"] if a.get("depense_constatee_eur") is not None}
    return {"annees": annees, "indicateur_journee": indic, "libelle": d.get("libelle")}


def construire_prisons() -> dict:
    fichiers = _fichiers("population_ecrouee", ".xlsx")
    if not fichiers:
        raise FileNotFoundError("classeurs mensuels absents : python pipeline/justice_defense.py collecter")
    manifeste = _manifeste().get(SOURCES["population_ecrouee"]["id_catalogue"], {})
    urls = {Path(f["chemin"]).name: f["url"] for f in manifeste.get("fichiers", [])}
    par_date: dict[str, dict] = {}
    illisibles, doublons = [], []
    for f in fichiers:
        c = lire_classeur(f)
        if not c["date"] or not c["national"]:
            illisibles.append({"fichier": f.name, "motif": "mise en page antérieure à juillet 2014 : date de situation ou tableau de "
                                                              "densité non reconnu"})
            continue
        if c["date"] in par_date:
            autre = par_date[c["date"]]
            doublons.append({"date": c["date"], "fichier_retenu": autre["fichier"], "fichier_ecarte": f.name,
                             "identiques": autre["national"] == c["national"]})
            continue
        par_date[c["date"]] = c
    if not par_date:
        raise DonneeInattendue("aucun classeur mensuel lisible")
    dates = sorted(par_date)
    serie = [{"date": d, **par_date[d]["national"],
              "metropole": par_date[d]["metropole"], "outre_mer": par_date[d]["outre_mer"]} for d in dates]
    for s in serie:
        calc = round(100 * s["detenus"] / s["capacite_operationnelle"], 1)
        if s["densite_pct"] is not None and abs(calc - s["densite_pct"]) > 0.15:
            raise DonneeInattendue(f"{s['date']} : densité publiée {s['densite_pct']} % ≠ détenus / places ({calc} %)")
    a0, m0 = int(dates[0][:4]), int(dates[0][5:7])
    a1, m1 = int(dates[-1][:4]), int(dates[-1][5:7])
    tous = [f"{a}-{m:02d}-01" for a in range(a0, a1 + 1) for m in range(1, 13)
            if (a, m) >= (a0, m0) and (a, m) <= (a1, m1)]
    absents = [d for d in tous if d not in par_date]

    avec_detail = [d for d in dates if par_date[d]["etablissements"]]
    if not avec_detail:
        raise DonneeInattendue("aucun classeur au format par établissement")
    ref = avec_detail[-1]
    janviers = [d for d in avec_detail if d[5:7] == "01"]

    # montant calculé : dépense du programme 107 de la dernière année complète, au prorata des journées estimées
    dep = _depense_107()
    cout = None
    journees_etab: dict[tuple, float] = {}
    for annee in sorted(dep["annees"], reverse=True):
        mois = [d for d in avec_detail if d[:4] == str(annee)]
        if len(mois) < 6:
            continue
        jours = 366 if calendar.isleap(annee) else 365
        moy_nat = sum(par_date[d]["national"]["detenus"] for d in mois) / len(mois)
        journees_nat = moy_nat * jours
        depense = float(dep["annees"][annee]["depense_constatee_eur"])
        par_jour = depense / journees_nat
        for d in mois:
            for e in par_date[d]["etablissements"]:
                if e["detenus"] is not None:
                    k = (e["etablissement"], e["quartier"])
                    journees_etab[k] = journees_etab.get(k, 0.0) + e["detenus"] / len(mois) * jours
        cout = {
            "statut": "calculé", "annee": annee, "producteur": "calcul du site, à partir de deux sources publiques",
            "depense_programme_107_eur": depense,
            "source_depense": "realisations/107.json, dépense constatée " + str(annee) + " (" +
                              str(dep["annees"][annee].get("source", "")) + ")",
            "mois_utilises": mois, "mois_absents": [f"{annee}-{m:02d}-01" for m in range(1, 13)
                                                    if f"{annee}-{m:02d}-01" not in mois],
            "detenus_moyens": round(moy_nat, 1), "jours": jours, "journees_estimees": round(journees_nat),
            "montant_par_journee_eur": round(par_jour, 2),
            "formule": "montant par journée = dépense constatée du programme 107 de l'année / (moyenne des personnes "
                       "détenues au 1er de chaque mois publié de l'année × nombre de jours de l'année) ; montant par "
                       "établissement ou quartier = montant par journée × moyenne de ses personnes détenues aux mêmes "
                       "dates × nombre de jours de l'année",
            "perimetre": "toute la dépense du programme 107 « Administration pénitentiaire » (crédits de paiement, "
                         "tous titres), rapportée aux seules personnes détenues en établissement",
            "methode": "prorata du nombre de personnes détenues, identique pour tous les établissements",
            "indicateur_publie": None,
            "limites": [
                "Aucun indicateur « coût d'une journée de détention » ne figure parmi les indicateurs de performance "
                "du programme 107 publiés dans realisations/107.json : le montant par journée est donc un calcul du "
                "site, pas une valeur publiée par l'administration.",
                "Le programme 107 comprend aussi le suivi en milieu ouvert, les services d'insertion et de probation, "
                "l'immobilier et l'investissement : le montant par journée calculé ici dépasse la seule dépense de "
                "fonctionnement d'une journée en établissement.",
                "Le même montant par journée est appliqué partout : le calcul ne tient compte ni du type "
                "d'établissement, ni de son ancienneté, ni de son mode de gestion. Il répartit une dépense, il ne "
                "mesure pas la dépense réelle de chaque établissement.",
                "Effectifs au 1er de chaque mois : la moyenne annuelle est une approximation du nombre de journées.",
            ],
        }
        break

    histo: dict[tuple, list] = {}
    for d in janviers:
        for e in par_date[d]["etablissements"]:
            histo.setdefault((e["etablissement"], e["quartier"]), []).append(
                {"date": d, "capacite_operationnelle": e["capacite_operationnelle"], "detenus": e["detenus"],
                 "densite_pct": e["densite_pct"]})
    etablissements = []
    for e in par_date[ref]["etablissements"]:
        k = (e["etablissement"], e["quartier"])
        ligne = dict(e)
        ligne["historique_1er_janvier"] = histo.get(k, [])
        ligne["montant_calcule_eur"] = (round(cout["montant_par_journee_eur"] * journees_etab[k])
                                        if cout and k in journees_etab else None)
        etablissements.append(ligne)
    etablissements.sort(key=lambda e: (_cle_nom(e["disp"]), _cle_nom(e["etablissement"]), e["quartier"]))

    ecarts = []
    for t in par_date[ref]["totaux_disp"]:
        lignes = [e for e in par_date[ref]["etablissements"] if e["disp"] == t["disp"]]
        for champ in ("capacite_operationnelle", "detenus"):
            somme = sum(e[champ] or 0 for e in lignes)
            if t[champ] is not None and somme != t[champ]:
                ecarts.append({"disp": t["disp"], "champ": champ, "source": "total publié de la direction",
                               "montant": t[champ], "autre_source": "somme des lignes publiées",
                               "autre_montant": somme, "ecart": somme - t[champ],
                               "lecture": "Le total publié et la somme des lignes publiées diffèrent ; les deux "
                                          "valeurs sont reprises telles quelles."})
    somme_ref = sum(e["detenus"] or 0 for e in par_date[ref]["etablissements"])
    nat_ref = par_date[ref]["national"]["detenus"]
    if abs(somme_ref - nat_ref) > 0.02 * nat_ref:
        raise DonneeInattendue(f"somme des établissements ({somme_ref}) trop éloignée du total national ({nat_ref})")
    return {
        "millesime": f"Situation au {ref} ; série nationale mensuelle de {dates[0]} à {dates[-1]} ; "
                     f"montant calculé sur {cout['annee'] if cout else 'aucune année'}",
        "source": f"{SOURCES['population_ecrouee']['titre']}, {SOURCES['population_ecrouee']['page']} ; dépense du "
                  "programme 107 : realisations/107.json",
        "unite": "places (capacité opérationnelle), personnes détenues, % (densité carcérale), euros (montant calculé)",
        "date_sources": date_sources(DOMAINE),
        "date_reference": ref,
        "avertissement": "Agrégats publiés par établissement ou quartier : aucune donnée individuelle. La densité "
                         "carcérale est le rapport publié entre personnes détenues et places opérationnelles. Le "
                         "montant par établissement est calculé par le site (voir `montant_calcule`), il n'est pas "
                         "publié par l'administration.",
        "definitions": {
            "capacite_operationnelle": "nombre de places effectivement disponibles, publié par l'administration "
                                       "pénitentiaire",
            "detenus": "personnes écrouées détenues (hébergées) à la date de situation",
            "quartier": "type de quartier publié (MA/QMA maison d'arrêt, CD/QCD centre de détention, MC/QMC maison "
                        "centrale, CSL/QSL semi-liberté, SAS structure d'accompagnement vers la sortie, etc.) ; un "
                        "établissement a une ligne par type de quartier",
        },
        "ordre": {"cles": ["disp", "etablissement", "quartier"],
                  "regle": "Direction interrégionale, puis établissement, puis quartier, par ordre alphabétique "
                           "(sans accents ni majuscules)."},
        "national": {"date": ref, **par_date[ref]["national"]},
        "etablissements": etablissements,
        "controles": {
            "lignes": len(etablissements), "somme_detenus_lignes": somme_ref, "detenus_total_national": nat_ref,
            "ecarts_totaux_directions": ecarts,
            "somme_montants_calcules_eur": sum(e["montant_calcule_eur"] or 0 for e in etablissements) if cout else None,
        },
        "montant_calcule": cout,
        "serie_nationale": serie,
        "couverture": {
            "classeurs_lus": len(par_date), "premiere_date": dates[0], "derniere_date": dates[-1],
            "dates_par_etablissement": avec_detail, "mois_absents": absents,
            "doublons": doublons, "illisibles": illisibles,
            "fichiers": [{"date": d, "url": urls.get(par_date[d]["fichier"])} for d in dates],
        },
        "limites": [
            "Seuls les classeurs xlsx sont lus : les mois publiés uniquement en PDF ou en ancien format xls "
            "(listés dans `couverture.mois_absents`) ne sont pas repris.",
            "Le détail par établissement est repris pour le format publié depuis 2023 ; de 2014 à 2019 les tableaux "
            "par quartier ont d'autres libellés et ne sont pas rapprochés : seule la série nationale les utilise.",
            "Aucune commune ni aucun département n'est attribué aux établissements : le jeu des structures de la "
            "Justice ne contient pas les établissements pénitentiaires, et un rapprochement par le nom a été écarté "
            "après essai (un établissement était rattaché à une commune homonyme d'une autre région). Le "
            "rattachement publié est la direction interrégionale.",
        ],
    }


# --------------------------------------------------------------------------------------------------------------------
# chiffres clés de la Justice

def _nombres_fr(texte: str) -> list[float]:
    return [float(x.replace(" ", "").replace(",", ".")) for x in
            re.findall(r"(?<![\d,])[+-]?\s?\d{1,3}(?: \d{3})*(?:,\d+)?(?![\d,])", texte)]


def construire_budget_justice() -> dict:
    import pdfplumber
    f = _fichiers("chiffres_cles", ".pdf")
    if not f:
        raise FileNotFoundError("chiffres clés absents : python pipeline/justice_defense.py collecter")
    with pdfplumber.open(f[0]) as pdf:
        textes = [(p.extract_text() or "") for p in pdf.pages]
        i_b = next((i for i, t in enumerate(textes) if "Le budget de la justice" in t and "Crédits de paiement" in t), None)
        i_f = next((i for i, t in enumerate(textes) if "Frais de justice - Aide juridictionnelle" in t), None)
        i_a = next((i for i, t in enumerate(textes) if "Montants versés aux avocats" in t), None)
        if None in (i_b, i_f, i_a):
            raise DonneeInattendue("chiffres clés : pages budget, frais de justice ou aide juridictionnelle introuvables")
        lignes_b = _lignes_mots(pdf.pages[i_b])

    def ligne(texte: str, debut: str, n: int, apres: str | None = None) -> list[float]:
        """Nombres de la première ligne commençant par `debut` (après le repère `apres` s'il est donné)."""
        if apres:
            texte = texte[texte.index(apres):]
        for li in texte.split("\n"):
            if li.startswith(debut):
                vals = _nombres_fr(li[len(debut):])
                if len(vals) >= n:
                    return vals[:n]
        raise DonneeInattendue(f"chiffres clés : ligne « {debut} » introuvable")

    tb = textes[i_b][textes[i_b].index("Le budget de la justice"):]
    annees_b = [int(x) for x in re.findall(r"\b(20\d\d) (20\d\d) \(en %\)", tb)[0]]
    cp = ligne(tb, "Crédits de paiement (en millions d’euros)", 2)
    personnel = ligne(tb, "dont dépenses de personnel", 2)
    ae = ligne(tb, "Autorisation d'engagements (en millions d'euros)", 2)

    # graphique par programme : chaque montant est rattaché au libellé dont le centre est le plus proche
    def centre(m):
        return (m["x0"] + m["x1"]) / 2
    y_titre = next(li[0]["top"] for li in lignes_b if " ".join(m["text"] for m in li).startswith("Répartition par programme"))
    y_lib = next(li[0]["top"] for li in lignes_b if li[0]["top"] > y_titre and li[0]["text"] == "Justice"
                 and any(m["text"] == "Administration" for m in li))
    libelles = next(li for li in lignes_b if li[0]["top"] == y_lib)
    premiers = ["Justice", "Administration", "Protection", "Accès", "Conduite", "Conseil"]
    ancres = []
    for i, p in enumerate(premiers):
        m = next((w for w in libelles if w["text"] == p), None)
        if m is None:
            raise DonneeInattendue(f"chiffres clés : libellé de programme « {p} » introuvable")
        ancres.append(m["x0"])
    bornes = ancres[1:] + [10 ** 6]
    centres = []
    for i, x0 in enumerate(ancres):
        mots = [w for w in libelles if x0 <= w["x0"] < bornes[i]]
        centres.append((min(w["x0"] for w in mots) + max(w["x1"] for w in mots)) / 2)
    montants: dict[int, float] = {}
    for li in lignes_b:
        if not (y_titre < li[0]["top"] < y_lib):
            continue
        groupes: list[list[dict]] = []
        for m in li:
            if groupes and m["x0"] - groupes[-1][-1]["x1"] < 6:
                groupes[-1].append(m)
            else:
                groupes.append([m])
        for g in groupes:
            v = nombre("".join(m["text"] for m in g))
            if v is None:
                continue
            c = (g[0]["x0"] + g[-1]["x1"]) / 2
            i = min(range(len(centres)), key=lambda k: abs(centres[k] - c))
            if i in montants:
                raise DonneeInattendue("chiffres clés : deux montants pour un même programme")
            montants[i] = v
    if len(montants) != 6 or abs(sum(montants.values()) - cp[1]) > 0.35:
        raise DonneeInattendue(f"chiffres clés : montants par programme ({montants}) ≠ crédits de paiement ({cp[1]})")
    programmes = []
    for i, (lib, code) in enumerate(PROGRAMMES_JUSTICE):
        attendu = json.loads((SITE / "realisations" / f"{code}.json").read_text(encoding="utf-8")).get("libelle", "")
        if _norm(attendu) != _norm(lib):
            raise DonneeInattendue(f"programme {code} : libellé « {attendu} » ≠ « {lib} »")
        programmes.append({"programme": code, "libelle": lib, "cp_meur": montants[i],
                           "part_pct": round(100 * montants[i] / cp[1], 1)})

    tf = textes[i_f][textes[i_f].index("Frais de justice - Aide juridictionnelle"):]
    annees_f = [int(x) for x in re.search(r"\b(20\d\d) (20\d\d) (20\d\d) \(en %\)", tf).groups()]
    frais = ligne(tf, "Frais de justice ", 3)
    civils = ligne(tf, "Frais de justice civile et commerciale", 3)
    penal = None
    for li in tf.split("\n"):
        v = _nombres_fr(li)
        if len(v) == 4 and re.match(r"^\d", li) and abs(v[0] + civils[0] - frais[0]) < 0.2:
            penal = v[:3]
    if penal is None:
        raise DonneeInattendue("chiffres clés : frais de justice pénale introuvables")
    aj = ligne(tf, "Dépenses effectives (RAP*)", 3)
    for k in range(3):
        if abs(civils[k] + penal[k] - frais[k]) > 0.2:
            raise DonneeInattendue("chiffres clés : frais civils + pénaux ≠ total des frais de justice")

    ta = textes[i_a][textes[i_a].index("Montants versés aux avocats"):]
    annee_a = int(re.search(r"en (20\d\d)", ta).group(1))
    avocats = {
        "total_meur": ligne(ta, "Total", 1)[0], "dont_aj_garantie_meur": ligne(ta, "dont AJ* garantie", 1)[0],
        "aide_juridictionnelle_meur": ligne(ta, "Aide juridictionnelle", 1, apres="dont AJ* garantie")[0],
        "civil_meur": ligne(ta, "En matière civile", 1)[0], "penal_meur": ligne(ta, "En matière pénale", 1)[0],
        "administratif_meur": ligne(ta, "En matière administrative", 1)[0],
        "aide_intervention_avocat_meur": ligne(ta, "Aide à l'intervention de l'avocat", 1)[0],
    }
    if abs(avocats["aide_juridictionnelle_meur"] + avocats["aide_intervention_avocat_meur"] - avocats["total_meur"]) > 0.25:
        raise DonneeInattendue("chiffres clés : aide juridictionnelle + aide à l'intervention ≠ total versé aux avocats")

    def serie(annees, valeurs):
        return [{"annee": a, "meur": v} for a, v in zip(annees, valeurs)]

    p107 = _depense_107()["annees"].get(annees_b[1])
    ecarts = []
    if p107:
        pub = next(p["cp_meur"] for p in programmes if p["programme"] == "107")
        autre = round(float(p107["depense_constatee_eur"]) / 1e6, 1)
        ecarts.append({"objet": f"programme 107, crédits de paiement {annees_b[1]}",
                       "source": "chiffres clés de la Justice", "montant": pub,
                       "autre_source": "realisations/107.json (dépense constatée)", "autre_montant": autre,
                       "ecart": round(autre - pub, 1), "unite": "M€",
                       "lecture": "Deux publications du même exercice ; les deux valeurs sont reprises telles quelles."})
    return {
        "millesime": f"Les chiffres clés de la Justice, édition 2026 : budget {annees_b[0]}-{annees_b[1]}, frais de "
                     f"justice et aide juridictionnelle {annees_f[0]}-{annees_f[-1]}",
        "source": f"{SOURCES['chiffres_cles']['titre']}, {SOURCES['chiffres_cles']['page']}, pages {i_b + 1}, "
                  f"{i_f + 1} et {i_a + 1} du PDF",
        "unite": "millions d'euros (M€)",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Montants repris des tableaux et du graphique du document, en millions d'euros. Le document "
                         "indique qu'ils viennent des rapports annuels de performance (crédits de paiement consommés).",
        "budget": {
            "credits_paiement": serie(annees_b, cp), "dont_personnel": serie(annees_b, personnel),
            "autorisations_engagement": serie(annees_b, ae), "annee_programmes": annees_b[1],
            "programmes": programmes,
            "controle": {"somme_programmes_meur": round(sum(montants.values()), 1), "credits_paiement_meur": cp[1]},
            "ordre": "Programmes dans l'ordre du graphique publié.",
        },
        "frais_de_justice": {
            "total": serie(annees_f, frais), "civile_et_commerciale": serie(annees_f, civils),
            "criminelle_correctionnelle_contraventionnelle": serie(annees_f, penal),
        },
        "aide_juridictionnelle": {
            "depenses_effectives": serie(annees_f, aj),
            "note": "Dépenses effectives : dotation annuelle des CARPA, huissiers, experts, enquêteurs (note du "
                    "document). Montants versés aux avocats : statistiques de l'UNCA, autre source et autre périmètre "
                    "que les dépenses effectives ; les deux séries ne s'additionnent pas.",
            "verse_aux_avocats": {"annee": annee_a, **avocats},
        },
        "ecarts": ecarts,
    }


# --------------------------------------------------------------------------------------------------------------------
# exportations d'armement

class _TextesPages:
    """Texte des pages d'un PDF, extrait à la demande (l'extraction complète du rapport prend plus d'une minute)."""

    def __init__(self, pdf):
        self.pdf, self.cache = pdf, {}

    def __getitem__(self, i: int) -> str:
        if i not in self.cache:
            self.cache[i] = self.pdf.pages[i].extract_text() or ""
        return self.cache[i]

    def annexes(self):
        """Indices des pages de la seconde moitié du document, où se trouvent les annexes."""
        return range(len(self.pdf.pages) // 2, len(self.pdf.pages))


def _table_pays(pdf, textes, marque_entete: str, marque_annexe: str, entier: bool) -> dict:
    """Tableau « pays × 2015..2024 + total » d'une annexe (lignes relues par position des colonnes)."""
    debut = next((i for i in textes.annexes() if marque_annexe in textes[i] and marque_entete in textes[i]), None)
    if debut is None:
        raise DonneeInattendue(f"rapport armement : {marque_annexe} introuvable")
    lignes_out, annees, fini = [], None, False
    pages = []
    for i in range(debut, min(debut + 8, len(pdf.pages))):
        page = pdf.pages[i]
        if marque_entete not in textes[i]:
            break
        pages.append(i + 1)
        lignes = _lignes_mots(page)
        i_ent = next(k for k, li in enumerate(lignes) if sum(bool(re.fullmatch(r"20\d\d", m["text"])) for m in li) >= 10)
        ent = lignes[i_ent]
        cols = [m for m in ent if re.fullmatch(r"20\d\d", m["text"])]
        total = next(m for m in ent if m["text"] == "TOTAL" and m["x0"] > cols[-1]["x1"])
        an = [int(m["text"]) for m in cols]
        if annees is None:
            annees = an
        elif an != annees:
            raise DonneeInattendue(f"rapport armement : années différentes page {i + 1}")
        droites = [m["x1"] for m in cols] + [total["x1"]]
        pas = (droites[-1] - droites[0]) / (len(droites) - 1)
        x_lib = droites[0] - pas * 0.95  # à gauche : libellé du pays
        brutes = []  # (ordonnée, libellé, cellules ou None)
        for li in lignes[i_ent + 1:]:
            def chiffre(m):
                return m["x1"] >= x_lib and re.fullmatch(r"[-–—]|\d[\d,]*", m["text"]) is not None
            i_num = next((k for k, m in enumerate(li) if chiffre(m)), len(li))
            lib = " ".join(m["text"] for m in li[:i_num])
            cellules: dict[int, str] = {}
            for m in li[i_num:]:
                k = min(range(len(droites)), key=lambda j: (m["x1"] > droites[j] + pas * 0.45, abs(droites[j] - m["x1"])))
                cellules[k] = cellules.get(k, "") + m["text"]
            if len(cellules) == len(droites):
                brutes.append((li[0]["top"], lib, cellules))
            elif lib and not cellules:
                brutes.append((li[0]["top"], lib, None))
        pleines = [b for b in brutes if b[2] is not None]
        prefixes: dict[int, list] = {}
        suffixes: dict[int, list] = {}
        for top, lib, cel in brutes:  # libellé sur plusieurs lignes : rattaché à la ligne chiffrée la plus proche
            if cel is not None or not pleines:
                continue
            k = min(range(len(pleines)), key=lambda j: abs(pleines[j][0] - top))
            if abs(pleines[k][0] - top) <= 9.5:
                (prefixes if top < pleines[k][0] else suffixes).setdefault(k, []).append(lib)
        for k, (top, lib, cellules) in enumerate(pleines):
            vals = []
            for c in range(len(droites)):
                t = cellules[c]
                vals.append(None if t in ("-", "–", "—") else nombre(t))
                if t not in ("-", "–", "—") and vals[-1] is None:
                    raise DonneeInattendue(f"rapport armement page {i + 1} : cellule illisible « {t} » ({lib})")
            libelle = " ".join(prefixes.get(k, []) + ([lib] if lib else []) + suffixes.get(k, []))
            libelle = re.sub(r"(?<=[A-ZÉ])- (?=[A-ZÉ]{2})", "", libelle)  # césure d'un libellé de région
            libelle = re.sub(r"(?<=\w)- (?=\w)", "-", libelle)  # nom composé coupé en fin de ligne
            libelle = re.sub(r"(?<=[a-zé\)])\s?\d$", "", libelle).strip()  # appel de note collé au nom
            if not libelle:
                raise DonneeInattendue(f"rapport armement page {i + 1} : ligne chiffrée sans libellé")
            lignes_out.append({"libelle": libelle, "valeurs": [int(v) if entier and v is not None else v for v in vals]})
            if _norm(libelle).replace(" ", "").startswith("totalgeneral"):
                fini = True
        if fini:
            break
    if not fini:
        raise DonneeInattendue(f"rapport armement : total général de {marque_annexe} introuvable")
    # régions : les pays précèdent le total de leur région
    pays, regions, hors_region, courant, general = [], [], [], [], None
    for li in lignes_out:
        nom, vals = li["libelle"], li["valeurs"]
        ligne = {"valeurs": vals[:-1], "total": vals[-1]}
        if _norm(nom).replace(" ", "").startswith("totalgeneral"):
            general = ligne
        elif nom.upper().startswith("TOTAL"):
            region = re.sub(r"^TOTAL\s+", "", nom, flags=re.I).strip()
            regions.append({"region": region, **ligne, "pays": len(courant)})
            for p in courant:
                p["region"] = region
            pays.extend(courant)
            courant = []
        else:
            courant.append({"pays": nom, "region": None, **ligne})
    hors_region = courant  # lignes après le dernier total régional : « Multi-pays », « Divers »
    tol = 0 if entier else 0.06

    def ecart_ligne(ligne):
        return abs(sum(v or 0 for v in ligne["valeurs"]) - (ligne["total"] or 0))
    hors_tol = [p["pays"] for p in pays + hors_region if ecart_ligne(p) > tol * len(annees) + 1e-9]
    ecarts_regions = []
    for r in regions:
        membres = [p for p in pays if p["region"] == r["region"]]
        for k, a in enumerate(annees):
            s = sum(p["valeurs"][k] or 0 for p in membres)
            if abs(s - (r["valeurs"][k] or 0)) > tol * max(1, len(membres)) + 1e-9:
                ecarts_regions.append({"region": r["region"], "annee": a, "source": "total régional publié",
                                       "montant": r["valeurs"][k], "autre_source": "somme des pays publiés",
                                       "autre_montant": round(s, 1), "ecart": round(s - (r["valeurs"][k] or 0), 1)})
    for k, a in enumerate(annees):
        s = sum(r["valeurs"][k] or 0 for r in regions) + sum(p["valeurs"][k] or 0 for p in hors_region)
        if abs(s - general["valeurs"][k]) > (0 if entier else 0.06 * (len(regions) + len(hors_region))) + 1e-9:
            raise DonneeInattendue(f"rapport armement {marque_annexe} {a} : régions + hors région ({s}) ≠ total général "
                                   f"({general['valeurs'][k]})")
    return {"annees": annees, "pages_pdf": pages, "pays": pays, "regions": regions, "hors_region": hors_region,
            "total_general": general,
            "controles": {"lignes_pays": len(pays), "regions_plus_hors_region_egal_total_general": True,
                          "pays_dont_le_total_differe_de_la_somme": hors_tol, "ecarts_regions": ecarts_regions}}


def _licences_par_categorie(pdf, textes) -> dict:
    """Ligne « TOTAL GÉNÉRAL » de l'annexe 8 : nombre (a) et montant (b) des licences par catégorie ML et AMA."""
    page = next((pdf.pages[i] for i in textes.annexes() if "TOTAL GÉNÉRAL" in textes[i] and "ML22" in textes[i]
                 and max(w["x1"] for w in pdf.pages[i].extract_words()) > 700), None)
    if page is None:
        raise DonneeInattendue("rapport armement : total général de l'annexe 8 introuvable")
    numero = page.page_number
    mots = page.extract_words()
    ent = sorted((m for m in mots if re.fullmatch(r"ML\d{1,2}|AUTRES\*|TOTAL", m["text"]) and m["top"] < 120),
                 key=lambda m: m["x0"])
    noms = [m["text"].rstrip("*") for m in ent]
    if noms != [f"ML{i}" for i in range(1, 23)] + ["AUTRES", "TOTAL"]:
        raise DonneeInattendue(f"rapport armement : en-tête de l'annexe 8 non reconnu ({noms})")
    droites = [m["x1"] for m in ent]
    y_gen = next(m["top"] for m in mots if m["text"] == "GÉNÉRAL")
    marques = sorted((m for m in mots if m["text"] in ("a", "b") and m["x0"] < droites[0] - 20), key=lambda m: m["top"])
    y_a = max(m["top"] for m in marques if m["text"] == "a" and m["top"] < y_gen)
    y_b = min(m["top"] for m in marques if m["text"] == "b" and m["top"] > y_gen)
    x_autres = (droites[21] + droites[22]) / 2 - 22  # la colonne « AUTRES » commence après ML22

    def ligne(y):
        mots_l = sorted((m for m in mots if abs(m["top"] - y) <= 2.5 and m["x0"] > marques[0]["x1"]), key=lambda m: m["x0"])
        groupes: list[list[dict]] = []
        for m in mots_l:
            if groupes and m["x0"] - groupes[-1][-1]["x1"] < 4.5:
                groupes[-1].append(m)
            else:
                groupes.append([m])
        vals = {}
        for g in groupes:
            v = nombre("".join(m["text"] for m in g))
            if v is None:
                continue
            k = min(range(len(droites)), key=lambda j: abs(droites[j] + 12 - g[-1]["x1"]))
            if noms[k] == "AUTRES" or k in vals:
                raise DonneeInattendue("rapport armement : annexe 8, colonne ambiguë dans le total général")
            vals[k] = v
        return vals

    def ama(y):
        res = {}
        zone = sorted((m for m in mots if abs(m["top"] - y) <= 16 and m["x0"] > droites[21] + 8 and m["x1"] < droites[22] + 14),
                      key=lambda m: (round(m["top"]), m["x0"]))
        texte = " ".join(m["text"] for m in zone)
        for nom, val in re.findall(r"(AMA\d)\s*:\s*([\d ]+?)(?=\s*(?:,|AMA|$))", texte):
            res[nom] = int(val.replace(" ", ""))
        return res

    na, nb, ama_a, ama_b = ligne(y_a), ligne(y_b), ama(y_a), ama(y_b)
    categories = []
    for k in range(22):
        categories.append({"categorie": noms[k], "licences": int(na[k]) if k in na else None,
                           "montant_eur": int(nb[k]) if k in nb else None})
    for nom in sorted(set(ama_a) | set(ama_b)):
        categories.append({"categorie": nom, "licences": ama_a.get(nom), "montant_eur": ama_b.get(nom)})
    tot_a, tot_b = na.get(23), nb.get(23)
    if tot_a is None or tot_b is None:
        raise DonneeInattendue("rapport armement : annexe 8, total général illisible")
    if sum(c["licences"] or 0 for c in categories) != tot_a or sum(c["montant_eur"] or 0 for c in categories) != tot_b:
        raise DonneeInattendue(f"rapport armement : annexe 8, somme des catégories ≠ total ({tot_a}, {tot_b})")
    return {"annee": 2024, "page_pdf": numero, "categories": categories,
            "total": {"licences": int(tot_a), "montant_eur": int(tot_b)},
            "controle": "somme des catégories = total général publié (nombre et montant)"}


def construire_armement() -> dict:
    import pdfplumber
    f = _fichiers("armement", ".pdf")
    if not f:
        raise FileNotFoundError("rapport armement absent : python pipeline/justice_defense.py collecter")
    with pdfplumber.open(f[0]) as pdf:
        textes = _TextesPages(pdf)
        if "exportations" not in textes[0] + textes[1] or "2025" not in textes[0] + textes[1]:
            raise DonneeInattendue("rapport armement : page de titre non reconnue")
        commandes = _table_pays(pdf, textes, "CD 2015", "Annexe 5", entier=False)
        licences = _table_pays(pdf, textes, "PAYS DESTINATAIRE", "Annexe 6", entier=True)
        livraisons = _table_pays(pdf, textes, "LV 2015", "Annexe 9", entier=False)
        t8 = next((textes[i] for i in textes.annexes() if "Annexe 8" in textes[i] and "Military List" in textes[i]), "")
        if "délivrées en 2024" not in t8:
            raise DonneeInattendue("rapport armement : l'annexe 8 ne porte plus sur 2024")
        categories = _licences_par_categorie(pdf, textes)
    ordre = "Pays dans l'ordre du tableau publié (par région, puis alphabétique dans la région)."
    return {
        "millesime": f"Rapport au Parlement 2025 : prises de commandes, livraisons et licences {commandes['annees'][0]}-"
                     f"{commandes['annees'][-1]} ; licences par catégorie {categories['annee']}",
        "source": f"{SOURCES['armement']['titre']}, {SOURCES['armement']['page']}, annexes 5, 6, 8 et 9",
        "unite": "millions d'euros courants (prises de commandes, livraisons) ; nombre de licences ; euros courants "
                 "(montant des licences par catégorie)",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Tableaux repris des annexes du rapport publié. Une prise de commande, une livraison et une "
                         "licence sont trois mesures différentes, qui ne s'additionnent pas : le montant d'une licence "
                         "est un plafond autorisé, pas une vente réalisée.",
        "notes": {
            "tiret": "Un tiret dans le tableau publié est repris null (aucune valeur publiée), jamais 0.",
            "zero": "« 0,0 » signifie un montant inférieur à 50 000 € (note du rapport).",
            "hors_region": "« Multi-pays » : contrats ou licences à destination finale de plusieurs pays ; « Divers » : "
                           "organisations internationales, États non membres de l'ONU (notes du rapport).",
            "categorie": "Lorsqu'une licence couvre plusieurs catégories, le rapport retient la catégorie "
                         "prépondérante sur le plan financier et lui attribue le montant entier de la licence.",
        },
        "ordre": ordre,
        "prises_de_commandes": {"annexe": 5, "unite": "M€ courants", **commandes},
        "livraisons": {"annexe": 9, "unite": "M€ courants", **livraisons},
        "licences": {"annexe": 6, "unite": "nombre de licences acceptées", **licences},
        "licences_par_categorie": {"annexe": 8, **categories},
    }


# --------------------------------------------------------------------------------------------------------------------
# ressorts et index

SEUIL_INCOHERENCE = 0.05  # part maximale de communes dont la juridiction siège dans un autre département


def construire_ressorts(ressorts: dict, juridictions: dict) -> dict:
    liste = juridictions["juridictions"]
    par_dep: dict[str, dict[str, int]] = {}
    types: dict[str, dict] = {}
    for j in liste:
        d = par_dep.setdefault(j["departement"] or "non_localise", {})
        d[j["type"]] = d.get(j["type"], 0) + 1
        t = types.setdefault(j["type"], {"type": j["type"], "nombre": 0, "exemple": j["nom"]})
        t["nombre"] += 1
    # cohérence interne : le siège de la juridiction indiquée est-il dans le département de la commune ?
    sieges = {(j["type"], _norm(j["nom"])): j["departement"] for j in liste}
    colonnes = [("tribunal_judiciaire", 2, "tribunaux_judiciaires", "TGI"),
                ("tribunal_proximite", 3, "tribunaux_proximite", "TPRX"),
                ("conseil_prudhommes", 4, "conseils_prudhommes", "CPH")]
    coherence = {}
    for nom, i, table, typ in colonnes:
        meme = autre = inconnu = 0
        exemples = []
        for c in ressorts["communes"]:
            if c[i] is None:
                continue
            nom_jur = ressorts["tables"][table][str(c[i])]
            dep = sieges.get((typ, _norm(nom_jur)))
            if dep is None:
                inconnu += 1
            elif dep == _departement(c[0]):
                meme += 1
            else:
                autre += 1
                if len(exemples) < 5 and c[0] in ("33063", "35238", "44109", "67482", "75056", "64445", "47001"):
                    exemples.append({"commune_insee": c[0], "juridiction_indiquee": nom_jur})
        total = meme + autre
        coherence[nom] = {"communes_meme_departement": meme, "communes_autre_departement": autre,
                          "siege_non_retrouve": inconnu, "part_autre_departement_pct": round(100 * autre / total, 1) if total else None,
                          "exemples": exemples}
    tj_fiable = (coherence["tribunal_judiciaire"]["part_autre_departement_pct"] or 0) <= 100 * SEUIL_INCOHERENCE
    # cour d'appel et tribunal judiciaire sont publiés ensemble dans la source et se décalent ensemble
    garde = [0] + ([1, 2] if tj_fiable else []) + [3, 4]
    noms_col = ["insee", "cour_appel", "tribunal_judiciaire", "tribunal_proximite", "conseil_prudhommes"]
    doc = {
        "millesime": "Structures de la Justice : ressorts publiés en mai 2026, liste des juridictions publiée en avril 2026",
        "source": f"{SOURCES['ressorts']['titre']}, {SOURCES['ressorts']['page']} (fichiers {ressorts['fichier']} et "
                  f"{juridictions['fichier']})",
        "unite": "identifiants de juridiction publiés ; codes Insee des communes",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Commune d'implantation de chaque juridiction, et juridiction compétente pour chaque commune "
                         "quand la colonne publiée est cohérente (voir `coherence_source`). Les colonnes de voie, de "
                         "code postal, de coordonnées, de téléphone et de courriel ne sont pas reprises. Les "
                         "établissements pénitentiaires ne figurent pas dans ce jeu.",
        "coherence_source": {
            "methode": "pour chaque commune, le siège de la juridiction indiquée (liste des juridictions du même jeu) "
                       "est comparé au département de la commune ; une colonne est reprise si au plus "
                       f"{round(100 * SEUIL_INCOHERENCE)} % des communes renvoient à un autre département",
            "colonnes": coherence,
            "colonnes_non_reprises": [] if tj_fiable else ["cour_appel", "tribunal_judiciaire"],
            "constat": None if tj_fiable else
                "Dans le fichier publié, le tribunal judiciaire et la cour d'appel indiqués ne correspondent pas à la "
                "commune de la ligne pour la plupart des communes (voir `colonnes.tribunal_judiciaire` et ses "
                "exemples) : ces deux colonnes ne sont pas reprises. La cour d'appel est publiée avec le tribunal "
                "judiciaire et suit le même décalage. Le contrôle est refait à chaque production.",
        },
        "tribunaux_proximite": ressorts["tables"]["tribunaux_proximite"],
        "conseils_prudhommes": ressorts["tables"]["conseils_prudhommes"],
        "colonnes": [noms_col[i] for i in garde],
        "communes": [[c[i] for i in garde] for c in ressorts["communes"]],
        "juridictions": liste,
        "types": sorted(types.values(), key=lambda t: t["type"]),
        "par_departement": {d: dict(sorted(v.items())) for d, v in sorted(par_dep.items())},
        "ordre": "Communes par code Insee ; juridictions par type, puis par nom (sans accents ni majuscules).",
        "controles": {"communes": len(ressorts["communes"]), "juridictions": len(liste),
                      "communes_sans_tribunal_de_proximite": sum(1 for c in ressorts["communes"] if c[3] is None)},
    }
    if tj_fiable:
        doc["cours_appel"] = ressorts["tables"]["cours_appel"]
        doc["tribunaux_judiciaires"] = ressorts["tables"]["tribunaux_judiciaires"]
    return doc


def _constat_effectifs() -> dict:
    entree = _manifeste().get(SOURCES["effectifs_defense"]["id_catalogue"], {})
    fichiers = entree.get("fichiers") or [{}]
    sha = fichiers[0].get("sha256")
    return {"sha256": sha, "octets": fichiers[0].get("octets"), "url": fichiers[0].get("url"),
            "a_relire": sha != EFFECTIFS_CONSTAT["sha256"]}


def construire_index(prisons: dict, budget: dict, ressorts: dict, armement: dict, tailles: dict) -> dict:
    manifeste = _manifeste()
    sources = []
    for cle, s in SOURCES.items():
        e = manifeste.get(s["id_catalogue"], {})
        sources.append({"id": cle, "id_catalogue": s["id_catalogue"], "titre": s["titre"], "page": s["page"],
                        "licence": s["licence"], "collecte_le": e.get("collecte_le"),
                        "fichiers_collectes": len(e.get("fichiers", [])) or None,
                        "statut": "repris" if cle != "effectifs_defense" else "collecté, aucune donnée à reprendre"})
    eff = _constat_effectifs()
    cout = prisons["montant_calcule"]
    cmd, liv = armement["prises_de_commandes"], armement["livraisons"]
    return {
        "millesime": f"Établissements pénitentiaires au {prisons['date_reference']} ; budget de la justice "
                     f"{budget['budget']['annee_programmes']} ; exportations d'armement {cmd['annees'][0]}-{cmd['annees'][-1]}",
        "source": " ; ".join(s["page"] for s in SOURCES.values() if s["page"] not in ("",)),
        "unite": "voir chaque fichier",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Présentation factuelle de documents publiés : aucun document classifié, aucune donnée "
                         "individuelle. Chaque fichier donne sa source, son millésime et ses contrôles.",
        "fichiers": [
            {"fichier": "justice_defense/prisons.json", "contenu": "capacité, personnes détenues et densité par "
             "établissement ou quartier ; série nationale mensuelle ; montant calculé par établissement", **tailles["prisons"]},
            {"fichier": "justice_defense/budget_justice.json", "contenu": "budget de la justice par programme, frais de "
             "justice, aide juridictionnelle", **tailles["budget_justice"]},
            {"fichier": "justice_defense/ressorts.json", "contenu": "juridiction compétente par commune ; juridictions "
             "par commune et par département", **tailles["ressorts"]},
            {"fichier": "justice_defense/armement.json", "contenu": "prises de commandes, livraisons et licences "
             "d'exportation d'armement par pays ; licences par catégorie", **tailles["armement"]},
        ],
        "reperes": {
            "prisons": {"date": prisons["date_reference"], **{k: prisons["national"][k] for k in
                        ("capacite_operationnelle", "detenus", "densite_pct")},
                        "lignes": prisons["controles"]["lignes"],
                        "montant_par_journee_calcule_eur": cout["montant_par_journee_eur"] if cout else None,
                        "annee_montant_calcule": cout["annee"] if cout else None, "statut_montant": "calculé"},
            "budget_justice": {"annee": budget["budget"]["annee_programmes"],
                               "credits_paiement_meur": budget["budget"]["credits_paiement"][-1]["meur"],
                               "frais_de_justice_meur": budget["frais_de_justice"]["total"][-1]["meur"],
                               "aide_juridictionnelle_depenses_effectives_meur":
                                   budget["aide_juridictionnelle"]["depenses_effectives"][-1]["meur"]},
            "ressorts": {"communes": ressorts["controles"]["communes"], "juridictions": ressorts["controles"]["juridictions"]},
            "armement": {"annee": cmd["annees"][-1], "prises_de_commandes_meur": cmd["total_general"]["valeurs"][-1],
                         "livraisons_meur": liv["total_general"]["valeurs"][-1],
                         "licences_acceptees": armement["licences"]["total_general"]["valeurs"][-1],
                         "licences_par_categorie": armement["licences_par_categorie"]["total"]},
        },
        "effectifs_defense": {
            "statut": "donnee_absente_a_la_source", "constat_le": EFFECTIFS_CONSTAT["date"],
            "constat": EFFECTIFS_CONSTAT["constat"], "fichier_sha256": eff["sha256"], "fichier_octets": eff["octets"],
            "fichier_url": eff["url"], "a_relire": eff["a_relire"],
            "voir_aussi": "effectifs/178.json et effectifs/212.json (ETPT par programme, autre source)",
        },
        "limites": [
            "Effectifs militaires et civils par catégorie et BOP : la ressource publiée ne contient que des "
            "métadonnées, aucun effectif n'est repris (`effectifs_defense`).",
            "Établissements pénitentiaires : mois publiés seulement en PDF ou en xls non repris ; aucune commune "
            "attribuée (les établissements ne figurent pas dans le jeu des structures de la Justice).",
            "Ressorts : colonnes cour d'appel et tribunal judiciaire non reprises tant que le fichier publié les "
            "décale par rapport aux communes (`coherence_source` de ressorts.json).",
            "Montant par établissement : calcul du site à partir de la dépense du programme 107, aucun indicateur "
            "publié de montant par journée de détention dans realisations/107.json.",
            "Chiffres clés et rapport au Parlement : tableaux relus dans des PDF, contrôlés par leurs totaux publiés ; "
            "un tableau qui ne retombe plus sur son total arrête la production.",
        ],
        "sources": sources,
        "sources_inaccessibles": [
            {"source": SOURCES["effectifs_defense"]["titre"] + ", " + SOURCES["effectifs_defense"]["page"],
             "motif": "ressource téléchargée sans refus, mais elle ne contient que la fiche de métadonnées du jeu : "
                      "aucune donnée chiffrée à reprendre (constat du 17/11/2026)"},
            {"source": "Statistique mensuelle de la population écrouée : mois publiés en PDF (2019 à 2022) ou en xls "
                       "(avant juillet 2014)",
             "motif": "formats non lus par ce module ; mois listés dans prisons.json (`couverture.mois_absents`)"},
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }


def _ecrire(chemin: Path, doc: dict) -> dict:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    chemin.write_text(texte, encoding="utf-8")
    octets = len(texte.encode("utf-8"))
    if octets > 5_000_000:
        raise DonneeInattendue(f"{chemin.name} dépasse 5 Mo ({octets} octets)")
    return {"octets": octets}


def _nettoyer(x):
    """Retire les clés techniques (préfixe « _ ») avant écriture."""
    if isinstance(x, dict):
        return {k: _nettoyer(v) for k, v in x.items() if not k.startswith("_")}
    if isinstance(x, list):
        return [_nettoyer(v) for v in x]
    return x


def produire(sortie: Path = SORTIE) -> None:
    ressorts, juridictions = lire_ressorts(), lire_juridictions()
    prisons = construire_prisons()
    budget = construire_budget_justice()
    doc_ressorts = construire_ressorts(ressorts, juridictions)
    armement = _nettoyer(construire_armement())
    tailles = {"prisons": _ecrire(sortie / "prisons.json", prisons),
               "budget_justice": _ecrire(sortie / "budget_justice.json", budget),
               "ressorts": _ecrire(sortie / "ressorts.json", doc_ressorts),
               "armement": _ecrire(sortie / "armement.json", armement)}
    _ecrire(sortie / "index.json", construire_index(prisons, budget, doc_ressorts, armement, tailles))
    print(f"justice_defense : 5 fichiers écrits dans {sortie}", file=sys.stderr)


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
