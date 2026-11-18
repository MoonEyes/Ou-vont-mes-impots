"""Immobilier de l'État : parc (biens, surfaces, valeur), loyers payés, cessions, compte « Gestion du patrimoine
immobilier de l'État ».

Le parc est décrit par deux sources qui ne se recoupent pas : les tableaux du document de politique transversale
« Politique immobilière de l'État » (annexe au PLF 2026, données au 31 décembre 2024, inventaire Chorus RE-FX de la
direction de l'immobilier de l'État) et les jeux ouverts « Parc de l'immobilier de l'État » (data.economie.gouv.fr ;
au 31/12/2021 pour tout le parc publié, réactualisés en 2022 et 2023 pour quelques ministères). Les loyers payés par
l'État et les grandes prises à bail viennent du même document ; les cessions, du document (outil de suivi des
cessions, comptabilité de l'État) et du jeu ouvert « Cessions immobilières de l'État » (2013 à 2017) ; le compte
d'affectation spéciale, du projet annuel de performances 2026 et des annexes CSV des PLRG 2023 à 2025. Deux sources
pour un même objet sont publiées côte à côte, jamais additionnées ni départagées.

Commandes :
    python pipeline/immobilier_etat.py collecter   (réseau : collecte/collecte.py sur les entrées immobilier_etat_* du
        catalogue ; un refus 401/403/429 n'est jamais contourné)
    python pipeline/immobilier_etat.py produire [--sortie DOSSIER]   (sans réseau)

Sorties (site/data/immobilier_etat/, contrat docs/contrat_interface.md 2.41, schémas
docs/schemas/immobilier_etat_*.schema.json) : index.json, parc.json, loyers.json, cessions.json, compte.json

Confidentialité : les jeux du parc et des cessions sont lus sans leurs colonnes de désignation, d'adresse, de
coordonnées et de libellé du gestionnaire ou du propriétaire (jamais demandées à l'export) ; les propriétaires et
les acquéreurs ne sont comptés que par catégorie juridique publiée, jamais nommés. Les sources ne nomment aucun
bailleur : aucun bailleur n'est publié. Les occupants des grandes prises à bail sont des services de l'État ou des
organismes publics nommés par le document budgétaire.
Sorties reproductibles : date = dernière collecte (pipeline/reproductible.py) ; ordres explicites.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "immobilier_etat"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "immobilier_etat"
DOCS = LAKE / "immobilier_etat_documents"
PLRG = LAKE / "immobilier_etat_plrg_annexes"
ODS = "https://data.economie.gouv.fr/explore/dataset"
COMPTE = "Gestion du patrimoine immobilier de l'État"
ANNEES_EXECUTION = [2023, 2024, 2025]
SOURCES_CATALOGUE = ["immobilier_etat_parc_2021", "immobilier_etat_parc_2022", "immobilier_etat_parc_2023",
                     "immobilier_etat_cessions_2013_2018", "immobilier_etat_plrg_annexes", "immobilier_etat_documents"]

DPT = {"fichier": "dpt2026_politique_immobiliere.pdf",
       "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1090100/file/12-DPT2026_Politique_immobiliere.pdf",
       "titre": "Document de politique transversale « Politique immobilière de l'État », annexe au projet de loi de "
                "finances pour 2026 (données au 31 décembre 2024)"}
PAP = {"fichier": "pap2026_cas_immobilier.pdf",
       "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1088065/file/"
              "PAP2026_CS_CAS_Gestion_patrimoine_immobilier_Etat_YB.pdf",
       "titre": "Projet annuel de performances 2026 du compte d'affectation spéciale « Gestion du patrimoine "
                "immobilier de l'État » (annexe au projet de loi de finances pour 2026)"}
JEUX_PARC = {
    2021: {"id": "immobilier_etat_parc_2021", "dataset": "parc_immobilier_etat_20211231",
           "page": "https://www.data.gouv.fr/datasets/parc-de-limmobilier-de-letat-au-31-12-2021"},
    2022: {"id": "immobilier_etat_parc_2022", "dataset": "parc_immobilier_etat_20221231",
           "page": "https://www.data.gouv.fr/datasets/parc-de-limmobilier-de-letat-au-31-12-2022"},
    2023: {"id": "immobilier_etat_parc_2023", "dataset": "parc_immobilier_etat_20231231",
           "page": "https://www.data.gouv.fr/datasets/parc-de-limmobilier-de-letat-au-31-12-2023"},
}
JEU_CESSIONS = {"id": "immobilier_etat_cessions_2013_2018", "dataset": "cessions-immobilieres-de-letat-copie",
                "page": "https://www.data.gouv.fr/datasets/cessions-immobilieres-de-letat-depuis-2013"}

# Colonnes lues dans les jeux ouverts (les autres ne sont jamais demandées à l'export : voir collecte/catalogue.json).
COLONNES_PARC = ["code_chorus", "type", "fonction", "dept", "code_insee", "libelle_nouvelle_region", "pays",
                 "ministere", "type_gestionnaire", "type_proprietaire", "surface_m2", "date_de_reference"]
COLONNES_CESSIONS = ["annee_cession", "pays", "dep_code", "nature", "ministere_occupant",
                     "type_procedure_ayant_mene_a_la_vente", "nature_juridique_acquereur", "nb_procedure"]
COLONNES_INTERDITES = {"adresse", "latitude", "longitude", "point_geo", "geom", "designation_site",
                       "designation_batiment_terrain", "libelle_gestionnaire", "libelle_proprietaire", "voie",
                       "numero", "lieu_dit", "adresse_complete", "service_occupant"}

# Types du jeu « Parc » regroupés pour les surfaces : la colonne « Surface (m²) » mêle surfaces bâties et emprises.
TYPES_BATIMENTS = ["Bureau", "Logement", "Bâtiment technique", "Bâtiment d'enseignement ou de sport",
                   "Bâtiment sanitaire ou social", "Bâtiment culturel", "Bâtiment agricole ou d'élevage",
                   "Édifice du culte", "Monument et mémorial", "Commerce"]
TYPES_EMPRISES = ["Espace aménagé", "Espace naturel", "Ouvrage d'art des réseaux et voiries", "Réseaux et voirie"]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "requetes": ["data.gouv.fr : inventaire immobilier de l'État, immobilier de l'État, cessions immobilières, "
                 "direction de l'immobilier de l'État, baux et loyers de l'État, patrimoine immobilier de l'État",
                 "data.economie.gouv.fr : jeux du parc immobilier, des cessions, annexes des PLRG",
                 "GitHub : immobilier etat ; inventaire immobilier etat ; parc immobilier etat ; cessions immobilieres "
                 "etat ; patrimoine immobilier etat ; code « parc_immobilier_etat »"],
    "trouvailles": [
        {"nom": "Parc de l'immobilier de l'État au 31/12/2021 (direction de l'immobilier de l'État)",
         "url": JEUX_PARC[2021]["page"], "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0",
         "date": "2023-01-19", "usage": "biens par ministère, par département, par type, par catégorie de propriétaire"},
        {"nom": "Parc de l'immobilier de l'État au 31/12/2022 et au 31/12/2023 (réactualisation de quelques ministères)",
         "url": JEUX_PARC[2023]["page"], "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0",
         "date": "2024-12-20", "usage": "biens des ministères réactualisés, sans total national"},
        {"nom": "Inventaire immobilier de l'État (ministères économiques et financiers)",
         "url": "https://www.data.gouv.fr/datasets/inventaire-immobilier-de-letat", "verdict": "inspiration seulement",
         "licence": "Licence Ouverte 2.0", "date": "2022-02-09",
         "usage": "non repris : jeu arrêté (« ne fera plus l'objet de mise à jour »), sans surface ni valeur"},
        {"nom": "Cessions immobilières de l'État depuis 2013", "url": JEU_CESSIONS["page"], "verdict": "à adapter",
         "licence": "Licence Ouverte 2.0", "date": "2018-12-13",
         "usage": "nombre de biens cédés 2013 à 2017 par nature, procédure, catégorie d'acquéreur et département ; "
                  "le jeu ne publie aucun prix"},
        {"nom": "data.economie.gouv.fr, annexes CSV des PLRG 2023, 2024 et 2025",
         "url": f"{ODS}/plrg-2024/", "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0",
         "date": "2026-04 (PLRG 2025)", "usage": "recettes et dépenses exécutées du compte d'affectation spéciale"},
        {"nom": DPT["titre"], "url": DPT["url"], "verdict": "à adapter", "licence": "document budgétaire public",
         "date": "2025-10 (PLF 2026)", "usage": "tableaux relus dans le PDF : parc, valeur, loyers, prises à bail, cessions"},
        {"nom": "Inventaire immobilier de l'État, extrait Île-de-France (Région Île-de-France)",
         "url": "https://www.data.gouv.fr/datasets/inventaire-immobilier-de-letat-1", "verdict": "inspiration seulement",
         "licence": "Licence Ouverte 2.0", "date": "2017-08-04", "usage": "non repris : extrait régional de 2017"},
        {"nom": "GitHub, betagouv/france-chaleur-urbaine (scripts qui croisent le jeu du parc au 31/12/2021 avec les "
                "réseaux de chaleur)", "url": "https://github.com/betagouv/france-chaleur-urbaine",
         "verdict": "inspiration seulement", "licence": "non relevée (accès à l'API GitHub refusé pour ce dépôt)",
         "date": "non relevée", "usage": "non repris : usage énergétique du jeu, sans agrégat budgétaire"},
        {"nom": "GitHub, dépôts consacrés à l'immobilier de l'État", "url": "https://github.com/search",
         "verdict": "aucun dépôt trouvé", "licence": "sans objet", "date": "2026-11-18",
         "usage": "cinq requêtes sans dépôt pertinent"},
    ],
}


# --- Outils ----------------------------------------------------------------------------------------------------------

def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).replace("’", "'").replace("‘", "'")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _espaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ").replace(" ", " ")).strip()


_NOMBRE = re.compile(r"^-?(?:\d{1,3}(?: \d{3})+|\d+)(?:[,.]\d+)?\*?(?: ?(?:ha|€|M€))?$")


def nombre(v) -> float | None:
    """Montant d'une cellule ; vide, « nc », « s » ou tiret : None (jamais 0)."""
    t = str(v if v is not None else "").replace("\xa0", "").replace(" ", "").replace(" ", "").strip()
    t = re.sub(r"(ha|M€|€|\*)$", "", t).strip()
    if t == "" or t.lower() in ("nc", "s", "nd", "-", "n/a"):
        return None
    return round(float(t.replace(",", ".")), 4)


def _entier(v) -> int | float | None:
    x = nombre(v)
    return int(x) if x is not None and x == int(x) else x


def _somme(valeurs) -> float | None:
    vs = [v for v in valeurs if v is not None]
    return round(sum(vs), 2) if vs else None


def lire_csv(chemin: Path, sep: str | None = None) -> list[dict]:
    texte = chemin.read_text(encoding="utf-8-sig")
    premiere = texte.split("\n", 1)[0]
    sep = sep or ("," if premiere.count(",") > premiere.count(";") else ";")
    lignes = list(csv.reader(texte.splitlines(), delimiter=sep))
    entete = [_norm(c).replace(" ", "_").replace("'", "_") for c in lignes[0]]
    return [dict(zip(entete, l)) for l in lignes[1:] if any(c.strip() for c in l)]


def _col(ligne: dict, *motifs: str):
    for m in motifs:
        for k, v in ligne.items():
            if all(f in k for f in m.split("+")):
                return v
    return None


def _code_libelle(texte: str) -> tuple[str | None, str]:
    """« Libellé - 76101 » ou « 76101 - Libellé » -> (code, libellé)."""
    t = _espaces(texte)
    m = re.match(r"^(.+?) - (\d{3,6})\s*$", t)
    if m:
        return m.group(2), m.group(1)
    m = re.match(r"^(\d{3,6}) - (.+)$", t)
    if m:
        return m.group(1), m.group(2)
    return None, t


# --- Lecture des PDF (mots positionnés, pdfplumber) -------------------------------------------------------------------

class Document:
    """Pages d'un PDF en lignes de mots positionnés. Deux lectures : mots fusionnés (un montant « 1 579 » reste un seul
    mot) et mots séparés (pour les cellules de texte)."""

    def __init__(self, nom: str, pages: range | None = None):
        import pdfplumber
        self.nom = nom
        self.pages: dict[int, dict] = {}
        try:
            pdf = pdfplumber.open(DOCS / nom)
        except Exception as e:  # PDF tronqué : le serveur ne donne pas toujours la taille, relancer la collecte
            raise SystemExit(f"{nom} illisible ({e}) : relancer « python collecte/collecte.py --force "
                             f"immobilier_etat_documents »")
        with pdf:
            for i in (pages or range(len(pdf.pages))):
                if i >= len(pdf.pages):
                    break
                p = pdf.pages[i]
                self.pages[i + 1] = {
                    "texte": _espaces(p.extract_text() or ""),
                    "fusion": _grouper(p.extract_words(keep_blank_chars=True, x_tolerance=2.5)),
                    "mots": p.extract_words(keep_blank_chars=False, x_tolerance=2),
                    "filets": [{"top": e["top"]} for e in p.horizontal_edges if e["x1"] - e["x0"] > 40],
                }

    def page_de(self, motif: str, debut: int = 1) -> int:
        for n in sorted(self.pages):
            if n >= debut and motif in self.pages[n]["texte"]:
                return n
        raise SystemExit(f"{self.nom} : texte « {motif} » introuvable (le document a changé ?)")

    def lignes(self, page: int, nb_pages: int = 1) -> list[list[dict]]:
        out = []
        for n in range(page, page + nb_pages):
            out += [l for l in self.pages[n]["fusion"]
                    if "Annexe au projet de loi de finances" not in " ".join(w["text"] for w in l)
                    and not re.match(r"^PLF – PAP", " ".join(w["text"] for w in l))]
        return out


def _grouper(mots: list[dict]) -> list[list[dict]]:
    """Mots regroupés en lignes (écart vertical de 2,5 points au plus), chaque ligne triée de gauche à droite."""
    lignes: list[list[dict]] = []
    for w in sorted((w for w in mots if w["text"].strip()), key=lambda w: (w["top"], w["x0"])):
        w = {**w, "text": _espaces(w["text"])}
        if lignes and abs(w["top"] - lignes[-1][0]["top"]) <= 2.5:
            lignes[-1].append(w)
        else:
            lignes.append([w])
    return [sorted(l, key=lambda w: w["x0"]) for l in lignes]


def _texte(ligne: list[dict]) -> str:
    return " ".join(w["text"] for w in ligne)


def tableau(lignes: list[list[dict]], ancre: str, entete: str, nb_col: int, libelles: list[str]) -> dict[str, list]:
    """Lignes de chiffres d'un tableau, dans l'ordre, sous la première ligne d'en-tête qui suit `ancre`.

    Chaque montant est rangé dans la colonne d'en-tête la plus proche (centre à centre) : une cellule vide reste None.
    Les libellés, souvent coupés sur plusieurs lignes dans le PDF, sont déclarés par l'appelant dans l'ordre du tableau.
    Une ligne d'en-tête répétée (tableau sur deux pages) recale les colonnes.
    """
    debut = next((i for i, l in enumerate(lignes) if ancre in _texte(l)), None)
    if debut is None:
        raise SystemExit(f"tableau introuvable : « {ancre} »")
    cols, lus = None, []
    for l in lignes[debut:]:
        tete = [w for w in l if re.fullmatch(entete, w["text"])]
        if len(tete) == nb_col:
            cols = [(w["x0"] + w["x1"]) / 2 for w in tete]
            continue
        if cols is None:
            continue
        nums = [w for w in l if _NOMBRE.match(w["text"])]
        if not nums:
            continue
        vals: list = [None] * nb_col
        for w in nums:
            c = (w["x0"] + w["x1"]) / 2
            k = min(range(nb_col), key=lambda j: abs(cols[j] - c))
            if vals[k] is not None:
                raise SystemExit(f"tableau « {ancre} » : deux montants dans une même colonne ({_texte(l)})")
            vals[k] = nombre(w["text"])
        lus.append(vals)
        if len(lus) == len(libelles):
            break
    if len(lus) != len(libelles):
        raise SystemExit(f"tableau « {ancre} » : {len(lus)} lignes lues pour {len(libelles)} attendues")
    return dict(zip(libelles, lus))


def _controle_total(t: dict[str, list], total: str, parties: list[str], tolerance: float, objet: str,
                    controles: list, en_echec: bool = True) -> None:
    """Somme des lignes = ligne de total, colonne par colonne. Écart au-delà de la tolérance : arrêt (relecture fausse)
    ou, si en_echec est faux, écart publié dans `controles` (total publié tel quel, jamais corrigé)."""
    for j, tot in enumerate(t[total]):
        vals = [t[p][j] for p in parties]
        if tot is None or all(v is None for v in vals):
            continue
        s = round(sum(v for v in vals if v is not None), 4)
        ecart = round(tot - s, 4)
        if abs(ecart) > tolerance:
            if en_echec:
                raise SystemExit(f"{objet}, colonne {j + 1} : total {tot} pour une somme des lignes de {s}")
            controles.append({"objet": objet, "colonne": j, "total_publie": tot, "somme_des_lignes": s, "ecart": ecart})


# --- Document de politique transversale 2026 --------------------------------------------------------------------------

INVENTAIRES = [  # (id, ancre du paragraphe, libellé, unité des terrains)
    ("global", "inventaire immobilier global",
     "inventaire global : biens dont l'État et ses établissements publics sont propriétaires ou occupants",
     "millions d'hectares"),
    ("occupes_etat_et_operateurs", "inventaire des seuls biens occupés",
     "biens occupés par l'État et ses établissements publics ou opérateurs", "millions d'hectares"),
    ("occupes_etat", "stricto sensu (y compris",
     "biens occupés par l'État au sens strict, y compris en qualité de locataire", "hectares"),
    ("comptable", "inventaire comptable de l",
     "inventaire comptable : biens inscrits à l'actif du bilan de l'État, qu'il utilise et dont il assume le rôle "
     "de propriétaire", "hectares"),
]
ANNEES_INVENTAIRE = [2019, 2020, 2021, 2022, 2023, 2024]
TYPES_DPT = ["Bureaux", "Logements", "Bâtiments d'enseignement", "Locaux d'activité", "Bâtiments culturels",
             "Culte et monuments", "Infrastructures"]
VNC_MINISTERES = ["Affaires étrangères", "Affaires sociales, travail", "Agriculture", "Armées", "Culture",
                  "Économie et finances", "Éducation nationale, enseignement supérieur", "Intérieur", "Justice",
                  "Services du Premier ministre", "Transition écologique", "Biens remis au Domaine", "Multi-occupation",
                  "Tiers"]
NATURES_EP = ["Biens domaniaux (propriété de l'État)", "Biens propres (et assimilés)",
              "Supports juridiques divers (collectivité territoriale, autres, multipropriété)"]
DEPENSES = ["Immobilisations, y compris entretien lourd", "Fluides", "Matériaux, outillage", "Loyers",
            "Entretien (hors entretien lourd)", "Assurance", "Nettoyage, déchets", "Taxes", "Autres"]
NATURES_CESSION = ["Terrains", "Logements", "Locaux d'activité", "Infrastructures", "Bureaux", "Cultes et monuments"]
ADMINISTRATIONS_CESSION = ["Affaires étrangères", "Agriculture", "Culture", "Armées", "Écologie", "Économie, budget",
                           "Éducation nationale, enseignement supérieur", "Intérieur", "Justice",
                           "Services du Premier ministre", "Affaires sociales (logement, travail, jeunesse et sports)",
                           "Biens non affectés"]


def _serie(annees: list[int], valeurs: list) -> dict[str, object]:
    return {str(a): v for a, v in zip(annees, valeurs)}


def lire_dpt() -> dict:
    doc = Document(DPT["fichier"], range(0, 40))
    out: dict = {"pages": {}, "controles": []}
    ctl = out["controles"]

    # 1. Inventaire : quatre périmètres, nombre de biens et surfaces, 2019 à 2024
    p = doc.page_de("inventaire immobilier global")
    out["pages"]["inventaires"] = p
    lignes = doc.lignes(p, 3)
    inventaires = []
    for ident, ancre, libelle, unite_terrains in INVENTAIRES:
        t = tableau(lignes, ancre, r"Nombre|Surface", 12, ["batiments", "terrains", "total"])
        bat, ter, tot = t["batiments"], t["terrains"], [v for v in t["total"] if v is not None]
        assert len(tot) == 6, (ident, t["total"])
        for k, a in enumerate(ANNEES_INVENTAIRE):  # total publié tel quel ; un écart avec la somme est signalé
            if abs(bat[2 * k] + ter[2 * k] - tot[k]) >= 1:
                ctl.append({"objet": f"inventaire « {ident} », nombre de biens", "colonne": k, "annee": a,
                            "total_publie": tot[k], "somme_des_lignes": bat[2 * k] + ter[2 * k],
                            "ecart": round(tot[k] - bat[2 * k] - ter[2 * k], 4)})
        inventaires.append({
            "id": ident, "libelle": libelle,
            "annees": ANNEES_INVENTAIRE,
            "batiments_nombre": [_int(bat[2 * k]) for k in range(6)],
            "batiments_surface_millions_m2": [bat[2 * k + 1] for k in range(6)],
            "terrains_nombre": [_int(ter[2 * k]) for k in range(6)],
            "terrains_surface": [ter[2 * k + 1] for k in range(6)], "terrains_unite": unite_terrains,
            "total_nombre": [_int(v) for v in tot]})
    out["inventaires"] = inventaires

    # 2. Surfaces bâties occupées par l'État et au total (2018-2024) ; par type de bâtiment (2017-2024)
    t = tableau(doc.lignes(p, 4), "Pour les bâtiments :", r"31-?\s?d[ée]c.*", 7, ["etat", "total"])
    out["surfaces_etat_total"] = {"annees": list(range(2018, 2025)), "etat_m2": t["etat"], "total_m2": t["total"]}
    pt = doc.page_de("par types de bâtiments")
    t = tableau(doc.lignes(pt), "par types de bâtiments", r"31-déc-\d\d", 8, TYPES_DPT + ["Total"])
    _controle_total(t, "Total", TYPES_DPT, 2, "surfaces par type de bâtiment", ctl, en_echec=False)
    out["surfaces_par_type"] = {"annees": list(range(2017, 2025)), "page": pt,
                                "types": [{"type": k, "m2": t[k]} for k in TYPES_DPT], "total_m2": t["Total"]}

    # 3. Valeur comptable du patrimoine contrôlé (2016-2024) et valeur nette comptable par ministère (2017-2024)
    pv = doc.page_de("Biens immobiliers figurant au bilan de l’État")
    t = tableau(doc.lignes(pv), "Biens immobiliers figurant au bilan de l’État", r"31-déc\d\d", 9, ["valeur"])
    out["valeur_controlee"] = {"annees": list(range(2016, 2025)), "millions_eur": t["valeur"], "page": pv}
    pm = doc.page_de("VNC par ministère")
    t = tableau(doc.lignes(pm, 2), "VNC par ministère", r"31/12/20\d\d", 8, VNC_MINISTERES + ["Total"])
    _controle_total(t, "Total", VNC_MINISTERES, 2, "valeur nette comptable par ministère", ctl, en_echec=False)
    out["vnc_par_ministere"] = {"annees": list(range(2017, 2025)), "page": pm,
                                "ministeres": [{"ministere": k, "millions_eur": t[k]} for k in VNC_MINISTERES],
                                "total_millions_eur": t["Total"]}
    citation = "La valeur comptable du patrimoine immobilier contrôlé par l’État est de 73,7 Md€ au 31 décembre 2023"
    out["citation_valeur"] = {"texte": citation, "page": doc.page_de(citation), "milliards_eur": 73.7, "annee": 2023}
    citation_concession = "La valeur comptable des biens concédés passe de 1 258 M€ au 31 décembre 2023 à 1 264 M€ au 31 décembre 2024"
    out["citation_concession"] = {"texte": citation_concession, "page": doc.page_de(citation_concession),
                                  "millions_eur": {"2023": 1258.0, "2024": 1264.0}}

    # 4. Établissements publics et opérateurs : nature de propriété des biens occupés (2019-2024)
    pe = doc.page_de("Nature de propriété des biens")
    t = tableau(doc.lignes(pe), "Nature de propriété des biens", r"20\d\d", 6,
                [f"b{k}" for k in range(4)] + [f"t{k}" for k in range(4)])
    for pre in ("b", "t"):
        _controle_total(t, f"{pre}3", [f"{pre}{k}" for k in range(3)], 2, "nature de propriété (établissements publics)", ctl)
    out["operateurs_nature_propriete"] = {
        "annees": list(range(2019, 2025)), "page": pe,
        "batiments_m2": [{"nature": n, "m2": t[f"b{k}"]} for k, n in enumerate(NATURES_EP)], "batiments_total_m2": t["b3"],
        "terrains_m2": [{"nature": n, "m2": t[f"t{k}"]} for k, n in enumerate(NATURES_EP)], "terrains_total_m2": t["t3"]}

    # 5. Dépenses immobilières (décaissements 2018-2024) et loyers payés (2014-2024)
    pd_ = doc.page_de("Dépenses immobilières de l")
    t = tableau(doc.lignes(pd_, 2), "Dépenses immobilières de l", r"20\d\d", 7, DEPENSES + ["Total"])
    _controle_total(t, "Total", DEPENSES, 3, "dépenses immobilières de l'État", ctl, en_echec=False)
    out["depenses"] = {"annees": list(range(2018, 2025)), "page": pd_,
                       "natures": [{"nature": k, "millions_eur": t[k]} for k in DEPENSES], "total_millions_eur": t["Total"]}
    pl = doc.page_de("Montant des loyers payés")
    t = tableau(doc.lignes(pl), "Montant des loyers payés", r"20\d\d", 11, ["loyers", "indice"])
    out["loyers"] = {"annees": list(range(2014, 2025)), "millions_eur": t["loyers"], "indice_2014": t["indice"], "page": pl}
    pb = doc.page_de("Prises à bail (flux)")
    t = tableau(doc.lignes(pb), "Prises à bail (flux)", r"20\d\d", 6, ["nombre"])
    out["prises_a_bail"] = {"annees": list(range(2019, 2025)), "nombre": [_int(v) for v in t["nombre"]], "page": pb}
    out["grandes_prises_a_bail"] = lire_grandes_prises_a_bail(doc)
    pe2 = doc.page_de("Emphytéoses et baux à construction dont l’État est titulaire")
    t = tableau(doc.lignes(pe2), "Emphytéoses et baux à construction dont l’État est titulaire", r"20\d\d", 8,
                ["nombre", "valeur"])
    out["emphyteoses"] = {"annees": list(range(2017, 2025)), "nombre": [_int(v) for v in t["nombre"]],
                          "valeur_comptable_millions_eur": t["valeur"], "page": pe2}

    # 6. Cessions
    pc = doc.page_de("constatés dans les actes")
    t = tableau(doc.lignes(pc), "Produits de cessions constatés dans les actes", r"20\d\d", 11, ["montant"])
    out["cessions_actes"] = {"annees": list(range(2014, 2025)), "millions_eur": t["montant"], "page": pc}
    citation_nb = "En 2024, 549 biens ont été cédés pour un prix de vente moyen de 404 959 € (432 922 € en 2023)."
    out["citation_nombre_2024"] = {"texte": citation_nb, "page": doc.page_de(citation_nb)}
    pn = doc.page_de("par type de biens (en valeur")
    t = tableau(doc.lignes(pn), "par type de biens (en valeur", r"cédés|vente \(M€\)", 6, NATURES_CESSION + ["Total"])
    _controle_total(t, "Total", NATURES_CESSION, 1.5, "cessions par nature", ctl, en_echec=False)
    out["cessions_par_nature"] = {
        "annees": [2022, 2023, 2024], "page": pn,
        "natures": [{"nature": k, "nombre": [_int(t[k][0]), _int(t[k][2]), _int(t[k][4])],
                     "millions_eur": [t[k][1], t[k][3], t[k][5]]} for k in NATURES_CESSION],
        "total_nombre": [_int(t["Total"][0]), _int(t["Total"][2]), _int(t["Total"][4])],
        "total_millions_eur": [t["Total"][1], t["Total"][3], t["Total"][5]]}
    out["grandes_cessions"] = lire_grandes_cessions(doc)
    pa = doc.page_de("répartition du parc immobilier cédé par l’État par administration")
    t = tableau(doc.lignes(pa), "répartition du parc immobilier cédé", r"20\d\d", 8, ADMINISTRATIONS_CESSION + ["Total"])
    _controle_total(t, "Total", ADMINISTRATIONS_CESSION, 2, "cessions par administration occupante", ctl, en_echec=False)
    out["cessions_par_administration"] = {
        "annees": list(range(2017, 2025)), "page": pa,
        "administrations": [{"administration": k, "eur": t[k]} for k in ADMINISTRATIONS_CESSION], "total_eur": t["Total"]}
    out["cessions_outre_mer"] = _liste_simple(doc, "Département DOM-COM-TOM", 2)
    out["cessions_etranger"] = _liste_simple(doc, "Pays / ville", 1)
    pk = doc.page_de("Produits de cessions encaissés")
    t = tableau(doc.lignes(pk), "Produits de cessions encaissés", r"20\d\d", 12, ["encaissements"])
    out["cessions_encaissees"] = {"annees": list(range(2013, 2025)), "millions_eur": t["encaissements"], "page": pk}
    return out


def _int(v):
    return int(v) if isinstance(v, float) and v == int(v) else v


def _liste_simple(doc: Document, entete: str, nb_nombres: int) -> dict:
    """Petit tableau « libellé, [nombre,] montant en euros » terminé par une ligne Total."""
    p = doc.page_de(entete)
    lignes = doc.lignes(p)
    debut = next(i for i, l in enumerate(lignes) if entete in _texte(l))
    rangs, total = [], None
    for l in lignes[debut + 1:]:
        nums = [w["text"] for w in l if _NOMBRE.match(w["text"])]
        lib = " ".join(w["text"] for w in l if not _NOMBRE.match(w["text"]))
        if len(nums) != nb_nombres or not lib:
            if rangs:
                break
            continue
        vals = [nombre(x) for x in nums]
        if lib == "Total":
            total = vals
            break
        rangs.append({"libelle": lib, **({"nombre": _int(vals[0])} if nb_nombres == 2 else {}), "eur": vals[-1]})
    if total is None:
        raise SystemExit(f"liste « {entete} » : ligne Total introuvable")
    if abs(sum(r["eur"] for r in rangs) - total[-1]) > 2:
        raise SystemExit(f"liste « {entete} » : somme {sum(r['eur'] for r in rangs)} pour un total de {total[-1]}")
    return {"page": p, "lignes": rangs, "total_eur": total[-1],
            **({"total_nombre": _int(total[0])} if nb_nombres == 2 else {})}


_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_MONTANT_EUR = re.compile(r"^\d{1,3}(?: \d{3})*,\d{2} €$")


def _lignes_mots(doc: Document, page: int, haut: float, bas: float) -> list[list[dict]]:
    return _grouper([w for w in doc.pages[page]["mots"] if haut < w["top"] < bas])


def lire_grandes_prises_a_bail(doc: Document) -> dict:
    """Prises à bail signées en 2024 dont le loyer dépasse 1 M€ (Île-de-France) ou 0,5 M€ (autres régions).

    Une ligne du tableau = une date d'effet ; ministère et occupant, écrits sur plusieurs lignes du PDF, sont lus dans
    les colonnes situées à gauche de la date (ministère) et entre la surface et le loyer (occupant)."""
    p0 = doc.page_de("Prises à bail dont le loyer est supérieur")
    baux = []
    for p in (p0, p0 + 1):
        mots = doc.pages[p]["mots"]
        tetes = [w for w in mots if w["text"] == "Ministère"]
        if not tetes:
            continue
        fin = [w["top"] for w in mots if w["text"] in ("Source", "Emphytéoses") and w["top"] > tetes[0]["top"]]
        haut, bas = tetes[0]["top"] + 12, (min(fin) if fin else 10_000)
        lignes = _lignes_mots(doc, p, haut, bas)
        ancres = [i for i, l in enumerate(lignes) if any(_DATE.match(w["text"]) for w in l)]
        # Lignes du tableau : filets horizontaux du PDF (une cellule de texte peut déborder au-dessus de la date)
        filets: list[float] = []
        for y in sorted(e["top"] for e in doc.pages[p]["filets"]):
            if not filets or y - filets[-1] > 1.5:
                filets.append(y)
        blocs: dict[int, list] = {i: [] for i in ancres}
        for i, l in enumerate(lignes):
            if i in blocs:
                continue
            y = l[0]["top"]
            haut_l = max((f for f in filets if f < y), default=None)
            bas_l = min((f for f in filets if f > y), default=None)
            dans = [a for a in ancres if haut_l is not None and bas_l is not None
                    and haut_l < lignes[a][0]["top"] < bas_l]
            proche = dans[0] if len(dans) == 1 else min(ancres, key=lambda a: abs(lignes[a][0]["top"] - y))
            blocs[proche].append(l)
        for a in ancres:
            l = lignes[a]
            date = next(w for w in l if _DATE.match(w["text"]))
            k = l.index(date)
            surface = l[k + 1]
            reste = l[k + 2:]
            # loyer : mots « 13 193 000,00 € » ; le premier mot du loyer suit l'occupant éventuel
            j = next(j for j in range(len(reste)) if re.fullmatch(r"\d{1,3}", reste[j]["text"])
                     and _MONTANT_EUR.match(" ".join(w["text"] for w in reste[j:j + 1 + next(
                         n for n in range(len(reste) - j) if reste[j + n]["text"] == "€")])))
            fin_loyer = j + next(n for n in range(len(reste) - j) if reste[j + n]["text"] == "€")
            loyer = nombre(" ".join(w["text"] for w in reste[j:fin_loyer + 1]))
            occ_ligne = reste[:j]
            apres = reste[fin_loyer + 1:]
            prix = nombre(apres[-1]["text"])
            dept = " ".join(w["text"] for w in apres[:-1])
            x_min_occ, x_max_occ = surface["x1"] + 2, reste[j]["x0"] - 2
            ministere = [w for w in l[:k]]
            occupant = list(occ_ligne)
            for bl in blocs[a]:
                ministere += [w for w in bl if w["x1"] <= date["x0"]]
                occupant += [w for w in bl if w["x0"] >= x_min_occ and w["x1"] <= x_max_occ]
            ministere.sort(key=lambda w: (w["top"], w["x0"]))
            occupant.sort(key=lambda w: (w["top"], w["x0"]))
            surf = nombre(surface["text"])
            calc = round(loyer / surf, 2) if surf else None
            if calc is None or abs(calc - prix) > 0.02:
                raise SystemExit(f"prise à bail du {date['text']} : prix au m² {prix} pour un loyer / surface de {calc}")
            j, m, an = date["text"].split("/")
            baux.append({"ministere": " ".join(w["text"] for w in ministere), "date_effet": f"{an}-{m}-{j}",
                         "surface_m2": surf, "occupant": " ".join(w["text"] for w in occupant) or None,
                         "loyer_annuel_ht_eur": loyer, "departement": dept, "prix_m2_eur": prix})
    if not baux or any(not b["ministere"] or not b["occupant"] for b in baux):
        raise SystemExit("prises à bail : ministère ou occupant non relu")
    return {"page": p0, "baux": baux}


def lire_grandes_cessions(doc: Document) -> dict:
    """Cessions de 2024 de plus de 2 M€ : région, département, commune, ministère occupant, prix (colonnes lues par la
    position horizontale de leurs mots ; les cellules de texte sont alignées à gauche, un peu avant leur en-tête)."""
    p = doc.page_de("Les cessions 2024 dont les montants sont supérieurs à 2 M€")
    mots = doc.pages[p]["mots"]
    tete = {w["text"]: w for w in mots if w["text"] in ("Région", "Département", "Commune", "Ministère", "Prix")}
    assert len(tete) == 5, sorted(tete)
    noms = ["region", "departement", "commune", "ministere_occupant", "prix"]
    bornes = [tete[k]["x0"] - 30 for k in ("Région", "Département", "Commune", "Ministère", "Prix")]
    bornes[0] = 0
    total_mot = next(w for w in mots if w["text"] == "Total" and w["top"] > tete["Région"]["top"])
    lignes = _lignes_mots(doc, p, tete["Région"]["top"] + 5, total_mot["top"] - 2)
    ancres = [i for i, l in enumerate(lignes) if l[-1]["text"] == "€"]
    blocs: dict[int, list] = {i: [lignes[i]] for i in ancres}
    for i, l in enumerate(lignes):
        if i not in blocs:
            blocs[min(ancres, key=lambda a: abs(lignes[a][0]["top"] - l[0]["top"]))].append(l)
    cessions = []
    for a in ancres:
        cellules: dict[str, list] = {n: [] for n in noms}
        for w in sorted((w for l in blocs[a] for w in l), key=lambda w: (round(w["top"] / 5), w["x0"])):
            k = max(i for i, b in enumerate(bornes) if w["x0"] >= b)
            cellules[noms[k]].append(w["text"])
        c = {n: " ".join(v) or None for n, v in cellules.items()}
        c["prix_eur"] = nombre(c.pop("prix"))
        c["region"] = re.sub(r"\s*-\s*", "-", c["region"] or "") or None
        cessions.append(c)
    total = nombre(" ".join(w["text"] for w in _lignes_mots(doc, p, total_mot["top"] - 2, total_mot["top"] + 3)[0]
                            if _NOMBRE.match(w["text"]) or w["text"] == "€"))
    if abs(sum(c["prix_eur"] for c in cessions) - total) > 1:
        raise SystemExit(f"cessions de plus de 2 M€ : somme {sum(c['prix_eur'] for c in cessions)} pour un total de {total}")
    return {"page": p, "cessions": cessions, "total_eur": total}


# --- Projet annuel de performances 2026 du compte ---------------------------------------------------------------------

def lire_pap() -> dict:
    doc = Document(PAP["fichier"])
    p = doc.page_de("ÉVALUATION ET JUSTIFICATION DES RECETTES")
    recettes, total = [], None
    for l in doc.lignes(p):
        t = _texte(l)
        nums = [nombre(w["text"]) for w in l if _NOMBRE.match(w["text"])]
        if re.match(r"^0\d - ", t) and len(nums) == 4:
            code, lib = re.match(r"^(0\d) - (.+?)$", " ".join(w["text"] for w in l if not _NOMBRE.match(w["text"]))).groups()
            recettes.append({"code": code, "libelle": lib, "lfi_2025_eur": nums[0], "prevision_2026_eur": nums[1],
                             "prevision_2027_eur": nums[2], "prevision_2028_eur": nums[3]})
        elif t.startswith("Total") and len(nums) == 4 and recettes:
            total = nums
            break
    assert recettes and total, "PAP : recettes non relues"
    for j, cle in enumerate(("lfi_2025_eur", "prevision_2026_eur", "prevision_2027_eur", "prevision_2028_eur")):
        assert abs(sum(r[cle] for r in recettes) - total[j]) < 1, cle
    # Crédits du programme 723 par action, LFI 2025 et PLF 2026 (tableau « par action et titre »)
    titre = "PRESENTATION DES CREDITS PAR ACTION ET TITRE POUR 2025 ET 2026"
    pa = next(n for n in sorted(doc.pages) if titre in doc.pages[n]["texte"]
              and "11 – Opérations structurantes" in doc.pages[n]["texte"])  # programme 723 (le 721 est vide)
    lignes = doc.lignes(pa)
    actions: dict[str, dict] = {}
    bloc = None
    k = 0
    while k < len(lignes):
        t = _texte(lignes[k])
        if t.startswith("AUTORISATIONS D'ENGAGEMENT"):
            bloc = "ae"
        elif t.startswith("CREDITS DE PAIEMENTS"):
            bloc = "cp"
        m = re.match(r"^(1\d) – (.+)$", " ".join(w["text"] for w in lignes[k] if not _NOMBRE.match(w["text"])))
        nums = [nombre(w["text"]) for w in lignes[k] if _NOMBRE.match(w["text"])]
        if bloc and (m or t.startswith("Totaux")) and len(nums) == 4:
            suite = [nombre(w["text"]) for w in lignes[k + 1] if _NOMBRE.match(w["text"])]
            assert len(suite) == 4, (t, _texte(lignes[k + 1]))
            code = m.group(1) if m else "total"
            a = actions.setdefault(code, {"code": code, "libelle": m.group(2) if m else "Total"})
            a[f"{bloc}_lfi_2025_eur"] = nums[2]
            a[f"{bloc}_plf_2026_eur"] = suite[2]
            k += 1
        k += 1
    tot = actions.pop("total")
    assert len(actions) == 4, sorted(actions)
    for cle in ("ae_lfi_2025_eur", "ae_plf_2026_eur", "cp_lfi_2025_eur", "cp_plf_2026_eur"):
        assert abs(sum(a[cle] for a in actions.values()) - tot[cle]) < 1, cle
    return {"recettes": recettes, "total_recettes": dict(zip(("lfi_2025_eur", "prevision_2026_eur", "prevision_2027_eur",
                                                              "prevision_2028_eur"), total)),
            "actions_723": [actions[c] for c in sorted(actions)], "total_723": {k: v for k, v in tot.items()
                                                                                 if k.endswith("_eur")},
            "pages": {"recettes": p, "actions": pa}}


# --- Annexes du PLRG ---------------------------------------------------------------------------------------------------

def _est_compte(v) -> bool:
    return _norm(v) == _norm(COMPTE)


def plrg_recettes(annee: int) -> dict:
    """{ligne de prévision: {"libelle", "evaluation_eur", "detail": [(code, libellé, montant)], "execution_eur"}}."""
    out: dict[str, dict] = {}
    for l in lire_csv(PLRG / f"plrg_{annee}_cs_recouvrements.csv"):
        if not _est_compte(l.get("compte")):
            continue
        code, lib = _code_libelle(_col(l, "ligne_de_prevision") or "")
        assert code and code.startswith("761"), l
        d = out.setdefault(code, {"libelle": lib, "evaluation_eur": None, "detail": []})
        ex = _espaces(_col(l, "ligne_d_execution", "ligne+execution") or "")
        if ex in ("", "0"):
            d["evaluation_eur"] = nombre(_col(l, "evaluation"))
        else:
            c_ex, lib_ex = _code_libelle(ex)
            d["detail"].append((c_ex, lib_ex, nombre(_col(l, "recouvrement"))))
    for d in out.values():
        d["detail"].sort(key=lambda x: x[0] or "")
        d["execution_eur"] = _somme(v for _, _, v in d["detail"])
    return out


def plrg_depenses(annee: int) -> dict:
    """{programme: mesures} du compte (crédits de paiement, tous titres confondus)."""
    champs = (("lfi_eur", "lfi"), ("lfr_eur", "lfr"), ("report_entrant_eur", "report_n-1"),
              ("fonds_concours_eur", "fdc_et_adp"), ("credits_ouverts_eur", "total_cp_ouverts"),
              ("execution_eur", "depenses_constatees"), ("report_sortant_eur", "report_n+1"))
    out: dict[str, dict] = {}
    for l in lire_csv(PLRG / f"plrg_{annee}_cs_cp.csv"):
        if not _est_compte(l.get("mission")):
            continue
        m = re.search(r"- (\d{3})\s*$", l.get("programme", ""))
        d = out.setdefault(m.group(1), {})
        for cle, col in champs:
            v = nombre(l.get(col))
            if v is not None:
                d[cle] = round(d.get(cle, 0.0) + v, 2)
    return out


def plrg_solde(annee: int) -> dict:
    for l in lire_csv(PLRG / f"plrg_{annee}_cs_comptable.csv"):
        if _est_compte(l.get("mission")):
            return {"debut_eur": nombre(l["be_credit"]), "recettes_eur": nombre(l["op_recettes"]),
                    "depenses_eur": nombre(l["op_depenses"]), "fin_eur": nombre(l["bs_credit"])}
    raise SystemExit(f"compte « {COMPTE} » absent de la situation comptable {annee}")


# --- Jeux ouverts du parc et des cessions ------------------------------------------------------------------------------

def _groupe_type(t: str) -> str:
    if t in TYPES_BATIMENTS:
        return "batiments"
    if t in TYPES_EMPRISES:
        return "emprises"
    return "non_renseigne"


def lire_parc(annee: int) -> list[dict]:
    lignes = lire_csv(LAKE / f"{JEUX_PARC[annee]['id']}.csv", sep=";")
    if lignes and (set(lignes[0]) & COLONNES_INTERDITES):
        raise SystemExit(f"jeu du parc {annee} : colonnes interdites présentes {sorted(set(lignes[0]) & COLONNES_INTERDITES)}")
    return lignes


def _agreger(lignes: list[dict], cle) -> list[dict]:
    acc: dict[str, dict] = {}
    for l in lignes:
        k = cle(l)
        a = acc.setdefault(k, {"cle": k, "biens": 0, "batiments": 0, "batiments_surface_m2": 0.0, "emprises": 0,
                               "type_non_renseigne": 0, "batiments_surface_non_renseignee": 0})
        a["biens"] += 1
        g = _groupe_type(l.get("type", ""))
        s = nombre(l.get("surface_m2"))
        if g == "non_renseigne":
            a["type_non_renseigne"] += 1
            continue
        a[g] += 1
        if g == "batiments":
            if s is None:
                a["batiments_surface_non_renseignee"] += 1
            else:
                a["batiments_surface_m2"] += s
    for a in acc.values():
        a["batiments_surface_m2"] = round(a["batiments_surface_m2"])
    return sorted(acc.values(), key=lambda a: (-a["biens"], a["cle"]))


def _dept(l: dict) -> str:
    d = (l.get("dept") or "").strip()
    return d.zfill(2) if d.isdigit() and len(d) < 2 else (d or "non renseigné")


def parc_ouvert() -> dict:
    jeux = {}
    for annee in (2021, 2022, 2023):
        lignes = lire_parc(annee)
        france = [l for l in lignes if (l.get("pays") or "") == "France"]
        dates = sorted({l.get("date_de_reference") or "" for l in lignes})
        j = {"annee": annee, "jeu": JEUX_PARC[annee]["dataset"], "url": JEUX_PARC[annee]["page"],
             "date_de_reference_publiee": dates, "biens": len(lignes), "biens_france": len(france),
             "biens_hors_france": len(lignes) - len(france),
             "par_ministere": _renommer(_agreger(lignes, lambda l: l.get("ministere") or "non renseigné"), "ministere")}
        if annee == 2021:
            j["par_departement"] = _renommer(sorted(_agreger(france, _dept), key=lambda a: a["cle"]), "departement")
            j["par_type"] = [{"type": a["cle"], "groupe": _groupe_type(a["cle"]), "biens": a["biens"],
                              "surface_m2": a["batiments_surface_m2"] if _groupe_type(a["cle"]) == "batiments" else None}
                             for a in _agreger(lignes, lambda l: l.get("type") or "")]
            j["par_type_proprietaire"] = _compter(lignes, "type_proprietaire")
            j["par_type_gestionnaire"] = _compter(lignes, "type_gestionnaire")
            j["par_pays_hors_france"] = _compter([l for l in lignes if l not in france], "pays")
        jeux[str(annee)] = j
    return jeux


def _renommer(agregats: list[dict], nom: str) -> list[dict]:
    return [{nom: a.pop("cle"), **a} for a in agregats]


def _compter(lignes: list[dict], col: str) -> list[dict]:
    acc: dict[str, int] = {}
    for l in lignes:
        k = (l.get(col) or "").strip() or "non renseigné"
        acc[k] = acc.get(k, 0) + 1
    return [{"categorie": k, "biens": v} for k, v in sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))]


def cessions_ouvertes() -> dict:
    lignes = lire_csv(LAKE / f"{JEU_CESSIONS['id']}.csv", sep=";")
    if lignes and (set(lignes[0]) & COLONNES_INTERDITES):
        raise SystemExit("jeu des cessions : colonnes interdites présentes")
    annees = sorted({l["annee_cession"][:4] for l in lignes if l.get("annee_cession")})
    par_annee = []
    for a in annees:
        la = [l for l in lignes if (l.get("annee_cession") or "")[:4] == a]
        par_annee.append({"annee": int(a), "biens": len(la),
                          "par_nature": _compter(la, "nature"),
                          "par_procedure": _compter(la, "type_procedure_ayant_mene_a_la_vente"),
                          "par_categorie_acquereur": _compter(la, "nature_juridique_acquereur"),
                          "par_ministere_occupant": _compter(la, "ministere_occupant")})
    france = [l for l in lignes if (l.get("pays") or "").upper() == "FRANCE"]
    return {"jeu": JEU_CESSIONS["dataset"], "url": JEU_CESSIONS["page"], "annees": [int(a) for a in annees],
            "biens": len(lignes), "biens_sans_annee": sum(1 for l in lignes if not l.get("annee_cession")),
            "par_annee": par_annee,
            "par_departement": sorted(_compter(france, "dep_code"), key=lambda c: c["categorie"]),
            "hors_france": len(lignes) - len(france)}


# --- Production --------------------------------------------------------------------------------------------------------

def _serie_m(annees, valeurs, facteur=1.0):
    return [None if v is None else round(v * facteur, 2) for v in valeurs]


def produire(sortie: Path = SORTIE) -> None:
    collecte_le = date_sources("immobilier_etat")
    dpt = lire_dpt()
    pap = lire_pap()
    parc_j = parc_ouvert()
    ces_j = cessions_ouvertes()
    ecarts: list[dict] = []
    lecture = "Les deux montants sont publiés ; aucun n'est retenu de préférence."
    src_dpt = f"{DPT['titre']}"

    def ref(cle):
        return f"{src_dpt}, page {dpt['pages'].get(cle) or dpt[cle]['page']}"

    # Parc
    val = dpt["valeur_controlee"]
    vnc = dpt["vnc_par_ministere"]
    i23 = val["annees"].index(2023)
    ecarts.append({"objet": "valeur comptable du patrimoine immobilier contrôlé par l'État au 31 décembre 2023",
                   "annee": 2023,
                   "valeurs": [{"source": f"{src_dpt}, page {dpt['citation_valeur']['page']} (texte)",
                                "montant_eur": dpt["citation_valeur"]["milliards_eur"] * 1e9},
                               {"source": f"{src_dpt}, page {val['page']} (tableau)",
                                "montant_eur": val["millions_eur"][i23] * 1e6}],
                   "ecart_eur": round((val["millions_eur"][i23] - dpt["citation_valeur"]["milliards_eur"] * 1000) * 1e6, 2),
                   "lecture": "Le tableau inclut les logements concédés par le ministère des armées (1 258 M€ au 31 "
                              "décembre 2023, page " + str(dpt["citation_concession"]["page"]) + ") ; le montant du texte "
                              "et le total par ministère ne les incluent pas. " + lecture})
    for a in ("2023", "2024"):
        k = vnc["annees"].index(int(a))
        kv = val["annees"].index(int(a))
        diff = round(val["millions_eur"][kv] - vnc["total_millions_eur"][k], 2)
        if abs(diff - dpt["citation_concession"]["millions_eur"][a]) > 1:
            ecarts.append({"objet": f"valeur du parc contrôlé contre total par ministère, {a}", "annee": int(a),
                           "valeurs": [{"source": ref("valeur_controlee"), "montant_eur": val["millions_eur"][kv] * 1e6},
                                       {"source": ref("vnc_par_ministere"), "montant_eur": vnc["total_millions_eur"][k] * 1e6}],
                           "ecart_eur": diff * 1e6, "lecture": lecture})
    glob = next(i for i in dpt["inventaires"] if i["id"] == "global")
    j21 = parc_j["2021"]
    ecarts.append({"objet": "nombre de biens du parc au 31 décembre 2021", "annee": 2021,
                   "valeurs": [{"source": f"{ref('inventaires')} (inventaire global, bâtiments et terrains)",
                                "nombre": glob["total_nombre"][glob["annees"].index(2021)]},
                               {"source": f"jeu « Parc de l'immobilier de l'État au 31/12/2021 » ({j21['url']})",
                                "nombre": j21["biens"]}],
                   "lecture": "Le jeu ouvert exclut les données confidentielles et ne compte pas les mêmes objets "
                              "(bâtiments, terrains, espaces et réseaux) ; plusieurs ministères n'y figurent pas. Les "
                              "deux nombres sont publiés ; aucun n'est retenu de préférence."})
    parc = {
        "millesime": "Inventaire au 31 décembre 2019 à 2024 (document de politique transversale 2026) ; jeux ouverts au "
                     "31/12/2021 (parc publié) et au 31/12/2022, 31/12/2023 (ministères réactualisés)",
        "source": f"{DPT['titre']} ({DPT['url']}) ; direction de l'immobilier de l'État, jeux « Parc de l'immobilier "
                  "de l'État » (data.economie.gouv.fr, data.gouv.fr)",
        "unite": "nombre de biens, m² de surface utile brute (SUB), hectares, millions d'euros (valeur comptable)",
        "avertissement": "Le parc décrit les biens dont l'État et ses établissements publics sont propriétaires ou "
                         "occupants. La valeur est une valeur comptable inscrite au bilan, pas un prix de marché ; ses "
                         "méthodes ont changé (valeur vénale jusqu'en 2017 pour la plupart des biens, puis coût "
                         "amorti, bureaux et logements compris à partir de 2025). Les tableaux du document budgétaire "
                         "et le jeu ouvert ne couvrent pas le même périmètre et ne s'additionnent pas.",
        "collecte_le": collecte_le,
        "inventaire": {"source": ref("inventaires"),
                       "note": "Surfaces des bâtiments en millions de m² de surface utile brute ; surfaces des terrains "
                               "dans l'unité indiquée par périmètre, telle que publiée. Un même bien peut figurer dans "
                               "plusieurs périmètres : ils ne s'additionnent pas.",
                       "perimetres": dpt["inventaires"]},
        "surfaces_batiments": {"source": ref("surfaces_par_type"),
                               "etat_et_total": dpt["surfaces_etat_total"], "par_type": dpt["surfaces_par_type"],
                               "note": "Total 2020 : biens atypiques (infrastructures, monuments, mémoriaux) exclus de la "
                                       "mesure en m², selon le document (environ 2,4 millions de m²)."},
        "valeur": {"source": ref("valeur_controlee"), "controlee": val,
                   "par_ministere": vnc,
                   "concession_logements_armees": dpt["citation_concession"],
                   "note": "Valeur comptable du patrimoine contrôlé par l'État, hors routes, autoroutes, concessions et "
                           "ouvrages hydrauliques. Le total par ministère ne comprend pas les logements concédés par le "
                           "ministère des armées. Depuis 2023, le tableau par ministère distingue les biens remis au "
                           "Domaine, la multi-occupation et les tiers."},
        "operateurs": {"source": ref("operateurs_nature_propriete"), **dpt["operateurs_nature_propriete"]},
        "jeu_ouvert": {
            "note": "Agrégats calculés par le site à partir des lignes du jeu (une ligne = un bâtiment, terrain, espace "
                    "ou réseau). La colonne « Surface (m²) » n'est additionnée que pour les bâtiments ; pour les emprises "
                    "(espaces aménagés ou naturels, ouvrages d'art, réseaux et voirie), seul le nombre est publié : "
                    "leurs surfaces, dont l'unité n'est pas documentée de façon homogène, ne sont pas additionnées "
                    "(surface null). Le jeu exclut les données confidentielles. Les jeux au "
                    "31/12/2022 et au 31/12/2023 ne réactualisent que quelques ministères : ils ne donnent pas de total "
                    "national et leur colonne « Date de référence » porte la valeur publiée, sans correction.",
            "types_batiments": TYPES_BATIMENTS, "types_emprises": TYPES_EMPRISES,
            "jeux": parc_j},
        "ordre": {"regle": "Tableaux du document : ordre du document. Jeux ouverts : ministères et catégories par nombre "
                           "de biens décroissant puis nom ; départements par code.", "cles": ["biens", "departement"]},
    }

    # Loyers
    rec = {a: plrg_recettes(a) for a in ANNEES_EXECUTION}
    loyers_percus = []
    for a in ANNEES_EXECUTION:
        for c, lib, v in rec[a].get("76102", {}).get("detail", []):
            loyers_percus.append({"annee": a, "code": c, "libelle": lib, "execution_eur": v})
    loyers = {
        "millesime": "Loyers payés 2014 à 2024 ; prises à bail 2019 à 2024 ; grandes prises à bail signées en 2024",
        "source": f"{DPT['titre']} ({DPT['url']}) ; annexes des PLRG 2023 à 2025 (redevances domaniales)",
        "unite": "millions d'euros (séries), euros (prises à bail), m²",
        "avertissement": "Loyers payés par l'État pour les biens qu'il loue, en décaissements, tous ministères confondus "
                         "(annuités de crédit-bail conclues avant 2018 comprises). Le document ne publie ni le détail "
                         "par ministère ni le nom des bailleurs : aucun bailleur n'est nommé ici. Les grandes prises à "
                         "bail sont celles que le document publie, au-delà de 1 M€ de loyer annuel en Île-de-France et "
                         "de 0,5 M€ hors taxe ailleurs.",
        "collecte_le": collecte_le,
        "loyers_payes": {"source": ref("loyers"), **dpt["loyers"]},
        "depenses_immobilieres": {"source": ref("depenses"), **dpt["depenses"],
                                  "note": "Décaissements de l'État par nature (comptabilité générale), arrondis au "
                                          "million d'euros ; la ligne « Loyers » reprend la série des loyers payés."},
        "prises_a_bail": {"source": ref("prises_a_bail"), **dpt["prises_a_bail"],
                          "note": "Prises à bail initiales, renouvellements et avenants (baux de bureaux, mixtes et de "
                                  "logements), selon l'application de suivi des baux."},
        "grandes_prises_a_bail": {"source": ref("grandes_prises_a_bail"), **dpt["grandes_prises_a_bail"],
                                  "note": "Signées en 2024 selon le document ; la date est celle de la prise d'effet du "
                                          "bail. « État » : service de l'État ; sinon, établissement ou autorité occupant "
                                          "les locaux, tel que nommé par le document. Le prix au m² est celui du document "
                                          "(loyer annuel divisé par la surface, contrôlé à la production)."},
        "emphyteoses": {"source": ref("emphyteoses"), **dpt["emphyteoses"],
                        "note": "Emphytéoses et baux à construction dont l'État est titulaire : il contrôle le bien sans "
                                "pouvoir le céder."},
        "loyers_percus_par_l_etat": {
            "source": "annexes des PLRG 2023 à 2025, recouvrements du compte « Gestion du patrimoine immobilier de l'État », "
                      "ligne 76102 « Produits de redevances domaniales »",
            "note": "Sens inverse : sommes encaissées par l'État pour ses propres biens (redevances, loyers, indemnités "
                    "d'occupation). Elles ne se comparent pas aux loyers payés et ne s'en déduisent pas.",
            "lignes": loyers_percus},
        "ordre": {"regle": "Séries par année croissante ; grandes prises à bail dans l'ordre du document (loyer "
                           "décroissant).", "cles": ["annee"]},
    }

    # Cessions
    ex76101 = {str(a): rec[a].get("76101", {}).get("execution_eur") for a in ANNEES_EXECUTION}
    act = dpt["cessions_actes"]
    enc = dpt["cessions_encaissees"]
    comparaison = []
    for a in range(2013, 2026):
        comparaison.append({"annee": a,
                            "prix_actes_millions_eur": act["millions_eur"][act["annees"].index(a)] if a in act["annees"] else None,
                            "encaissements_millions_eur": enc["millions_eur"][enc["annees"].index(a)] if a in enc["annees"] else None,
                            "recouvrements_ligne_76101_eur": ex76101.get(str(a))})
    for a in (2023, 2024):
        e = enc["millions_eur"][enc["annees"].index(a)] * 1e6
        r = ex76101[str(a)]
        if r is not None and abs(e - r) > 1e6:
            ecarts.append({"objet": f"produits de cessions encaissés en {a}", "annee": a,
                           "valeurs": [{"source": f"{ref('cessions_encaissees')} (comptabilité de l'État, millions arrondis)",
                                        "montant_eur": e},
                                       {"source": f"PLRG {a}, recouvrements du compte, ligne 76101", "montant_eur": r}],
                           "ecart_eur": round(r - e, 2),
                           "lecture": "La ligne 76101 du compte comprend aussi des versements de ministères et des "
                                      "contributions d'organismes extérieurs. " + lecture})
    cessions = {
        "millesime": "Cessions 2013 à 2024 (document de politique transversale 2026) ; recouvrements 2023 à 2025 (PLRG) ; "
                     "jeu ouvert 2013 à 2017",
        "source": f"{DPT['titre']} ({DPT['url']}) ; annexes des PLRG 2023 à 2025 ; jeu « Cessions immobilières de l'État "
                  f"depuis 2013 » ({JEU_CESSIONS['page']})",
        "unite": "nombre de biens, euros, millions d'euros",
        "avertissement": "Trois mesures différentes d'une même activité : prix inscrits dans les actes de vente signés "
                         "dans l'année (outil de suivi des cessions), encaissements de l'année (comptabilité de l'État), "
                         "recouvrements de la ligne de recette du compte. Elles ne s'additionnent pas. Aucun acquéreur "
                         "n'est nommé ; le jeu ouvert ne les décrit que par catégorie juridique.",
        "collecte_le": collecte_le,
        "comparaison_par_annee": {"note": "Une valeur absente n'est pas publiée par la source pour cette année.",
                                  "lignes": comparaison},
        "prix_actes": {"source": ref("cessions_actes"), **act, "nombre_2024": dpt["citation_nombre_2024"]},
        "par_nature": {"source": ref("cessions_par_nature"), **dpt["cessions_par_nature"]},
        "par_administration_occupante": {"source": ref("cessions_par_administration"), **dpt["cessions_par_administration"],
                                         "note": "Prix de cession en euros par administration qui occupait le bien. "
                                                 "Une cellule vide du document reste null."},
        "plus_de_2_millions_2024": {"source": ref("grandes_cessions"), **dpt["grandes_cessions"],
                                    "note": "Cessions de 2024 de plus de 2 M€ publiées par le document (lieu du bien, "
                                            "ministère occupant, prix inscrit dans l'acte). Le document précise que la "
                                            "première est réglée en trois échéances (2024, 2025, 2026)."},
        "outre_mer_2024": {"source": f"{src_dpt}, page {dpt['cessions_outre_mer']['page']}", **dpt["cessions_outre_mer"]},
        "etranger_2024": {"source": f"{src_dpt}, page {dpt['cessions_etranger']['page']}", **dpt["cessions_etranger"]},
        "encaissements": {"source": ref("cessions_encaissees"), **enc},
        "jeu_ouvert_2013_2017": {**ces_j,
                                 "note": "Nombre de biens cédés par année civile, sans prix (le jeu n'en publie pas). "
                                         "Les acquéreurs sont comptés par catégorie juridique publiée, jamais nommés. "
                                         "Libellés de ministère tels que publiés (anciennes dénominations)."},
        "ordre": {"regle": "Années croissantes ; tableaux du document dans son ordre ; catégories du jeu ouvert par "
                           "nombre décroissant puis nom ; départements par code.", "cles": ["annee"]},
    }

    # Compte d'affectation spéciale
    dep = {a: plrg_depenses(a) for a in ANNEES_EXECUTION}
    soldes = {a: plrg_solde(a) for a in ANNEES_EXECUTION}
    lignes_rec = []
    for code in sorted({c for a in ANNEES_EXECUTION for c in rec[a]}):
        lib = next(rec[a][code]["libelle"] for a in reversed(ANNEES_EXECUTION) if code in rec[a])
        par_annee = {str(a): {"evaluation_eur": rec[a][code]["evaluation_eur"], "execution_eur": rec[a][code]["execution_eur"]}
                     for a in ANNEES_EXECUTION if code in rec[a]}
        detail = {str(a): [{"code": c, "libelle": l, "execution_eur": v} for c, l, v in rec[a][code]["detail"]]
                  for a in ANNEES_EXECUTION if code in rec[a]}
        lignes_rec.append({"code": code, "libelle": lib, "par_annee": par_annee, "detail_execution": detail})
    for a in ANNEES_EXECUTION:
        s = _somme(rec[a][c]["execution_eur"] for c in rec[a])
        if abs(s - soldes[a]["recettes_eur"]) > 1:
            raise SystemExit(f"PLRG {a} : recettes du compte {s} pour {soldes[a]['recettes_eur']} à la situation comptable")
        s = _somme(d.get("execution_eur") for d in dep[a].values())
        if abs(s - soldes[a]["depenses_eur"]) > 1:
            raise SystemExit(f"PLRG {a} : dépenses du compte {s} pour {soldes[a]['depenses_eur']} à la situation comptable")
    programmes = [{"code": p, "libelle": "Opérations immobilières et entretien des bâtiments de l'État" if p == "723"
                   else "Contribution des cessions immobilières au désendettement de l'État",
                   "par_annee": {str(a): dep[a][p] for a in ANNEES_EXECUTION if p in dep[a]}}
                  for p in ("721", "723")]
    compte = {
        "millesime": "Exécution 2023 à 2025 (PLRG) ; LFI 2025, PLF 2026, prévisions 2027 et 2028 (projet annuel de "
                     "performances 2026)",
        "source": f"data.economie.gouv.fr, annexes des PLRG 2023, 2024 et 2025 ; {PAP['titre']} ({PAP['url']})",
        "unite": "euros",
        "avertissement": "Le compte d'affectation spéciale « Gestion du patrimoine immobilier de l'État » reçoit les "
                         "produits de cessions et les redevances domaniales et finance des opérations immobilières "
                         "(programme 723). Il ne retrace qu'une partie des dépenses immobilières de l'État : les loyers, "
                         "l'entretien courant et la plupart des investissements sont payés par les programmes des "
                         "ministères.",
        "collecte_le": collecte_le,
        "nom": COMPTE, "type": "compte d'affectation spéciale",
        "recettes": {"lignes": lignes_rec,
                     "note": "Évaluation (prévision) et recouvrements par ligne de recette, avec le détail par ligne "
                             "d'exécution (libellés de la nomenclature, parfois anciens). Un recouvrement publié sans "
                             "montant reste null."},
        "depenses": {"programmes": programmes,
                     "note": "Crédits de paiement par programme : loi de finances initiale, lois rectificatives, reports, "
                             "fonds de concours, crédits ouverts, dépenses constatées (PLRG)."},
        "solde": {"definition": "solde en début d'année, recettes et dépenses de l'année, solde en fin d'année "
                                "(situation comptable des comptes spéciaux, PLRG)",
                  "par_annee": {str(a): soldes[a] for a in ANNEES_EXECUTION}},
        "prevision": {"source": f"{PAP['titre']}, pages {pap['pages']['recettes']} et {pap['pages']['actions']}",
                      "recettes": pap["recettes"], "total_recettes": pap["total_recettes"],
                      "actions_723": pap["actions_723"], "total_723": pap["total_723"]},
        "ordre": {"regle": "Lignes de recette et programmes par code ; détail par code de ligne d'exécution.",
                  "cles": ["code"]},
    }

    # Index
    def dernier(serie: dict, annee: int):
        return serie["millions_eur"][serie["annees"].index(annee)] if annee in serie["annees"] else None

    i24 = glob["annees"].index(2024)
    index = {
        "millesime": "Parc au 31 décembre 2024, loyers et cessions 2024, compte exécuté en 2025",
        "source": f"{DPT['titre']} ; {PAP['titre']} ; annexes des PLRG 2023 à 2025 ; direction de l'immobilier de "
                  "l'État, jeux ouverts du parc et des cessions",
        "unite": "voir chaque fichier",
        "avertissement": "Le parc immobilier de l'État, ce qu'il paie pour les biens qu'il loue, ce qu'il vend et le "
                         "compte qui reçoit les produits de cession. Chiffres publiés par l'administration, présentés sans "
                         "qualification ; deux sources pour un même objet sont montrées côte à côte.",
        "collecte_le": collecte_le,
        "definitions": {
            "parc": "biens (bâtiments et terrains) dont l'État et ses établissements publics sont propriétaires ou "
                    "occupants, inscrits à l'inventaire tenu par la direction de l'immobilier de l'État",
            "surface_utile_brute": "surface de plancher d'un bâtiment, murs extérieurs exclus (m² SUB)",
            "valeur_comptable": "valeur inscrite au bilan de l'État selon ses normes comptables, pas un prix de marché",
            "loyers": "sommes payées par l'État aux propriétaires des biens qu'il loue",
            "cessions": "ventes de biens de l'État ; prix des actes, encaissements et recouvrements sont trois mesures "
                        "distinctes",
            "compte": "compte d'affectation spéciale « Gestion du patrimoine immobilier de l'État » : produits de "
                      "cessions et redevances en recettes, programme 723 en dépenses",
        },
        "fichiers": [
            {"fichier": "immobilier_etat/parc.json", "contenu": "biens, surfaces, valeur comptable par ministère, "
                                                                 "jeu ouvert par ministère et par département"},
            {"fichier": "immobilier_etat/loyers.json", "contenu": "loyers payés, dépenses immobilières, prises à bail, "
                                                                   "grandes prises à bail 2024"},
            {"fichier": "immobilier_etat/cessions.json", "contenu": "prix des actes, encaissements, recouvrements, "
                                                                     "cessions par nature, administration, lieu"},
            {"fichier": "immobilier_etat/compte.json", "contenu": "recettes, dépenses et solde du compte d'affectation "
                                                                   "spéciale, prévisions 2025 à 2028"},
        ],
        "chiffres_cles": {
            "annee": 2024,
            "biens_inventaire_global": glob["total_nombre"][i24],
            "surface_batiments_millions_m2": glob["batiments_surface_millions_m2"][i24],
            "valeur_controlee_millions_eur": dernier(val, 2024),
            "loyers_payes_millions_eur": dernier(dpt["loyers"], 2024),
            "cessions_prix_actes_millions_eur": dernier(act, 2024),
            "cessions_encaissees_millions_eur": dernier(enc, 2024),
            "compte_depenses_2025_eur": soldes[2025]["depenses_eur"],
            "compte_recettes_2025_eur": soldes[2025]["recettes_eur"],
            "compte_solde_fin_2025_eur": soldes[2025]["fin_eur"],
        },
        "ecarts_entre_sources": ecarts,
        "controles_totaux": dpt["controles"],
        "sources": [
            {"id": "immobilier_etat_documents", "titre": DPT["titre"], "url": DPT["url"], "licence": "document budgétaire public"},
            {"id": "immobilier_etat_documents", "titre": PAP["titre"], "url": PAP["url"], "licence": "document budgétaire public"},
            {"id": "immobilier_etat_plrg_annexes", "titre": "PLRG 2023, 2024 et 2025, annexes des comptes spéciaux",
             "url": f"{ODS}/projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-lannee-plrg-2025/",
             "licence": "Licence Ouverte 2.0"},
            *[{"id": j["id"], "titre": f"Parc de l'immobilier de l'État au 31/12/{a}", "url": j["page"],
               "licence": "Licence Ouverte 2.0"} for a, j in JEUX_PARC.items()],
            {"id": JEU_CESSIONS["id"], "titre": "Cessions immobilières de l'État depuis 2013", "url": JEU_CESSIONS["page"],
             "licence": "Licence Ouverte 2.0"},
        ],
        "sources_inaccessibles": [
            {"source": "immobilier-etat.gouv.fr, site de la direction de l'immobilier de l'État",
             "motif": "certificat du serveur non vérifiable par le client (chaîne de certification incomplète) : "
                      "connexion refusée, non contournée", "constate_le": "2026-11-18"}],
        "limites": [
            "Loyers payés : publiés tous ministères confondus ; le détail par ministère et les bailleurs ne sont pas "
            "publiés en données ouvertes.",
            "Jeu ouvert du parc : dernière publication complète au 31/12/2021, hors données confidentielles ; les "
            "ministères de l'intérieur et de la transition écologique n'y figurent pas en tant que tels.",
            "Jeu ouvert des cessions : 2013 à 2017, sans prix ; les cessions récentes ne sont publiées que dans les "
            "tableaux du document budgétaire.",
            "Plusieurs tableaux du document budgétaire sont des images (surfaces par ministère, nombre de cessions par "
            "ministère, cartes) : ils ne sont pas repris.",
            "Valeur du parc : comptable, avec des méthodes qui ont changé en 2018 et en 2025.",
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }

    for nom, doc in (("parc.json", parc), ("loyers.json", loyers), ("cessions.json", cessions),
                     ("compte.json", compte), ("index.json", index)):
        _ecrire(sortie / nom, doc)
    print(f"immobilier_etat : 5 fichiers dans {sortie} ; {len(ecarts)} écart(s) entre sources ; "
          f"{len(dpt['controles'])} total(aux) publié(s) avec écart")


def _ecrire(chemin: Path, doc: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def collecter() -> int:
    r = subprocess.run([sys.executable, str(ROOT / "collecte" / "collecte.py"), *SOURCES_CATALOGUE])
    return r.returncode


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
