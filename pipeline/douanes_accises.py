"""Douane et accises : ce que la douane perçoit, le produit de chaque accise en série, et à qui il est affecté.

Détaille, sans les recopier, deux contenus déjà publiés par le site :
  - site/data/recettes.json (Eurostat) donne les grands agrégats (D2, D214A « droits d'accise et impôts de
    consommation ») par administration : ici, le produit de chaque accise et des droits de douane, en série ;
  - site/data/prelevements/affectation.json donne la ventilation 2025 de l'accise sur les produits énergétiques,
    du droit de consommation sur les tabacs et des droits sur les alcools : ici, les autres années publiées.

Entrées (data/lake/douanes_accises, collectées par collecte/collecte.py ; identifiants dans collecte/catalogue.json) :
  douanes_insee_t3217          Insee, comptes nationaux base 2020, tableau 3.217 « Principaux impôts par catégorie »
  douanes_dgddi_recettes_2010_2015  DGDDI, données ouvertes « Recettes fiscales perçues et montants redressés 2010-2015 »
  douanes_bilan_2020 ... 2025  DGDDI, bilans annuels de la douane (tableau « Recettes douanières en millions d'euros »)
  douanes_vm1_plf2024 ... 2026 PLF, « Évaluation des voies et moyens » tome I (accise sur les produits énergétiques,
                               ligne 2301 : frais de perception des droits de douane conservés par l'État)
  douanes_plfss2026_annexe3    PLFSS 2026, annexe 3, tableau 31 (répartition des impositions affectées à la
                               sécurité sociale, 2018 à 2026)

Commandes :
  python pipeline/douanes_accises.py collecter            # réseau (collecte/collecte.py, contrôle d'intégrité)
  python pipeline/douanes_accises.py produire [--sortie DOSSIER]   # sans réseau ; xlrd, openpyxl, pdfplumber

Les montants lus dans un PDF sont écrits dans ce module (tables LECTURES_*) puis vérifiés à chaque production
contre le texte du document collecté : une valeur introuvable à sa ligne arrête la production. Rien n'est estimé :
une case absente ou marquée « * » ou « - » par la source vaut null, avec sa raison.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from reproductible import date_sources  # noqa: E402

LAKE = ROOT / "data" / "lake" / "douanes_accises"
SORTIE = ROOT / "site" / "data" / "douanes_accises"
DOMAINE = "douanes_accises"

# --------------------------------------------------------------------------------------------------------------
# Sources (une entrée par identifiant du catalogue)
# --------------------------------------------------------------------------------------------------------------
SOURCES = {
    "douanes_insee_t3217": {
        "fichier": "douanes_insee_t3217.xlsx",
        "url": "https://www.insee.fr/fr/statistiques/fichier/8988845/t_3217_fr.xlsx",
        "page": "https://www.insee.fr/fr/statistiques/8988845",
        "titre": "Comptes nationaux annuels, base 2020 : tableau 3.217 « Principaux impôts par catégorie » (1995 à "
                 "2025), publication « Dépenses et recettes des administrations publiques en 2025 »",
        "producteur": "Insee", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel",
    },
    "douanes_dgddi_recettes_2010_2015": {
        "fichier": "douanes_dgddi_recettes_2010_2015.xls",
        "url": "https://www.douane.gouv.fr/sites/default/files/openData/files/"
               "dgddi-2010-2015-recettes-fiscales-montants-redresses.xls",
        "page": "https://www.douane.gouv.fr/la-douane/opendata/auteurs/bureau-de-la-communication",
        "titre": "DGDDI, données ouvertes : « Recettes fiscales perçues et montants redressés 2010-2015 » (feuille "
                 "« recettes douanieres »)",
        "producteur": "Direction générale des douanes et droits indirects (DGDDI)", "licence": "Licence Ouverte",
        "verdict": "réutilisable tel quel (jeu non prolongé après 2015)",
    },
    "douanes_bilan_2020": {
        "fichier": "douanes_bilan_2020.pdf", "page_pdf": 25,
        "url": "https://www.douane.gouv.fr/sites/default/files/2021-04/02/Bilan-annuel-de-la-douane-2020.pdf",
        "titre": "Bilan annuel de la douane 2020, « Recettes douanières en millions d'euros (détail) », 2019 et 2020",
        "producteur": "DGDDI", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié à chaque production)",
    },
    "douanes_bilan_2022": {
        "fichier": "douanes_bilan_2022.pdf", "page_pdf": 25,
        "url": "https://Douane.gouv.fr/sites/default/files/2023-02/22/bilan-annuel-de-la-douane-2022.pdf",
        "titre": "Bilan annuel de la douane 2022, « Recettes douanières en millions d'euros (détail) », 2021 et 2022",
        "producteur": "DGDDI", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié à chaque production)",
    },
    "douanes_bilan_2023": {
        "fichier": "douanes_bilan_2023.pdf", "page_pdf": 60,
        "url": "https://Douane.gouv.fr/sites/default/files/2024-05/09/bilan-annuel-de-la-douane-2023.pdf",
        "titre": "Bilan annuel de la douane 2023, « Évolution des recettes douanières en millions d'euros (détail) », "
                 "2023",
        "producteur": "DGDDI", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié à chaque production)",
    },
    "douanes_bilan_2024": {
        "fichier": "douanes_bilan_2024.pdf", "page_pdf": 25, "page_chiffres_cles": 4,
        "url": "https://douane.gouv.fr/sites/default/files/2025-03/24/Bilan_DGDDI_2024.pdf",
        "titre": "Bilan de la douane 2024, « Recettes douanières en millions d'euros (détail) » et chiffres clés "
                 "(destination des recettes)",
        "producteur": "DGDDI", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié à chaque production)",
    },
    "douanes_bilan_2025": {
        "fichier": "douanes_bilan_2025.pdf", "page_pdf": 26, "page_chiffres_cles": 4,
        "url": "https://www.douane.gouv.fr/sites/default/files/2026-02/19/Bilan_Douane_2025.pdf",
        "titre": "Bilan de la douane 2025, « Recettes douanières en millions d'euros (détail) » et chiffres clés "
                 "(destination et provenance des recettes), 19 février 2026",
        "producteur": "DGDDI", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié à chaque production)",
    },
    "douanes_vm1_plf2024": {
        "fichier": "douanes_vm1_plf2024.pdf",
        "url": "https://questions.assemblee-nationale.fr/dyn/contenu/visualisation/705205/file/"
               "Evaluation%20des%20voies%20et%20moyens%20-%20Tome%20I",
        "titre": "PLF 2024, Évaluation des voies et moyens tome I : TICPE nette (p. 29), ligne 2301 (p. 50)",
        "producteur": "Direction du budget / DGFiP", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié à chaque production)",
    },
    "douanes_vm1_plf2025": {
        "fichier": "douanes_vm1_plf2025.pdf",
        "url": "https://www2.assemblee-nationale.fr/static/17/Annexes-DL/PLF-2025/Voies_et_moyens_Tome_1_2025.pdf",
        "titre": "PLF 2025, Évaluation des voies et moyens tome I : TICPE nette (p. 27), ligne 2301 (p. 48)",
        "producteur": "Direction du budget / DGFiP", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié à chaque production)",
    },
    "douanes_vm1_plf2026": {
        "fichier": "douanes_vm1_plf2026.pdf",
        "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1087930/file/"
               "PLF%202026%20-%20V%26M%20TI%20-%20Evaluations%20des%20recettes.pdf",
        "titre": "PLF 2026, Évaluation des voies et moyens tome I : accise sur les produits énergétiques (p. 28), "
                 "ligne 2301 (p. 54), octobre 2025",
        "producteur": "Direction du budget / DGFiP", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (tableau lu dans le PDF, vérifié à chaque production)",
    },
    "douanes_plfss2026_annexe3": {
        "fichier": "douanes_plfss2026_annexe3.pdf", "page_pdf": 44,
        "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1089896/file/"
               "PLFSS2026-Annexe3-20251015-103900-55-4.pdf",
        "titre": "PLFSS 2026, annexe 3, tableau 31 « Répartition des impositions affectées à la sécurité sociale "
                 "entre 2018 et 2025 » (p. 44), octobre 2025",
        "producteur": "Direction de la sécurité sociale", "licence": "document administratif public (CRPA L. 321-1)",
        "verdict": "à adapter (clés lues dans le tableau, vérifiées à chaque production)",
    },
}

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "verdict": "Aucun jeu ouvert récent de la douane ne publie ses recettes par produit (le seul jeu ouvert de la "
               "DGDDI couvre 2010 à 2015) et aucun dépôt public ne les rassemble : les séries sont reprises du "
               "tableau 3.217 de l'Insee (réutilisable tel quel) et les années récentes lues dans les bilans de la "
               "douane, les voies et moyens et l'annexe 3 du PLFSS (à adapter). La ventilation 2025 du site "
               "(prelevements/affectation.json) est réutilisée par renvoi, sans copie de ses totaux.",
    "trouvailles": [
        {"nom": "Insee, comptes nationaux base 2020, tableau 3.217", "url": SOURCES["douanes_insee_t3217"]["page"],
         "classement": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "derniere_mise_a_jour": "2026-05"},
        {"nom": "DGDDI, « Recettes fiscales perçues et montants redressés 2010-2015 » (data.douane)",
         "url": SOURCES["douanes_dgddi_recettes_2010_2015"]["url"], "classement": "réutilisable tel quel",
         "licence": "Licence Ouverte", "derniere_mise_a_jour": "jeu non prolongé après 2015"},
        {"nom": "DGDDI, bilans annuels de la douane (PDF)", "url": SOURCES["douanes_bilan_2025"]["url"],
         "classement": "à adapter", "licence": "document administratif public", "derniere_mise_a_jour": "2026-02-19"},
        {"nom": "DGDDI, données ouvertes « Droits et taxes applicables aux produits énergétiques » (tarifs, pas de "
                "montants perçus)", "url": "https://www.douane.gouv.fr/la-douane/opendata/auteurs/"
                                        "energie-environnement-et-lois-de-finances",
         "classement": "inspiration seulement", "licence": "Licence Ouverte", "derniere_mise_a_jour": "2026-09-30"},
        {"nom": "Évaluation des voies et moyens tome I (PLF 2024 à 2026)", "url": SOURCES["douanes_vm1_plf2026"]["url"],
         "classement": "à adapter", "licence": "document administratif public", "derniere_mise_a_jour": "2025-10"},
        {"nom": "PLFSS 2026, annexe 3", "url": SOURCES["douanes_plfss2026_annexe3"]["url"], "classement": "à adapter",
         "licence": "document administratif public", "derniere_mise_a_jour": "2025-10-15"},
        {"nom": "fgeerolf.com, republication du tableau Insee 3.217", "url": "https://fgeerolf.com/data/insee/t_3217.html",
         "classement": "inspiration seulement", "licence": "non précisée", "derniere_mise_a_jour": "non datée"},
        {"nom": "pipeline/prelevements.py (ce dépôt) : affectation 2025", "url": "pipeline/prelevements.py",
         "classement": "réutilisable tel quel (renvoi)", "licence": "MIT", "derniere_mise_a_jour": "2026-11"},
        {"nom": "data.gouv.fr et GitHub (recherches « recettes douane », « accises », « DGDDI », « TICPE »)",
         "url": "https://www.data.gouv.fr/", "classement": "aucun jeu ni dépôt pertinent trouvé",
         "licence": "sans objet", "derniere_mise_a_jour": "2026-11-18"},
    ],
}

DESTINATAIRES = {
    "etat": {"nom": "État (budget général)", "administration": "Etat"},
    "collectivites_territoriales": {"nom": "Collectivités territoriales (régions, départements)",
                                    "administration": "Collectivites locales"},
    "afitf": {"nom": "Agence de financement des infrastructures de transport de France (AFITF)",
              "administration": "Etat"},
    "idfm": {"nom": "Île-de-France Mobilités", "administration": "Collectivites locales"},
    "zni_cspe": {"nom": "Fractions ZNI et CSPE (péréquation tarifaire, énergies renouvelables)",
                 "administration": "Etat"},
    "autres": {"nom": "Autres (ligne « Autres » de la source)", "administration": None},
    "cnam": {"nom": "Assurance maladie (CNAM)", "administration": "Securite sociale"},
    "ravgdt": {"nom": "Régime d'allocations viagères des gérants de débits de tabac (RAVGDT)",
               "administration": "Securite sociale"},
    "msa_maladie": {"nom": "MSA, non-salariés agricoles, maladie", "administration": "Securite sociale"},
    "msa_vieillesse": {"nom": "MSA, non-salariés agricoles, vieillesse", "administration": "Securite sociale"},
    "msa_rco": {"nom": "MSA, retraite complémentaire obligatoire des non-salariés agricoles",
                "administration": "Securite sociale"},
    "union_europeenne": {"nom": "Union européenne (ressources propres traditionnelles)",
                         "administration": "Union europeenne"},
    "collectivites_et_organismes_sociaux": {"nom": "Collectivités locales et organismes sociaux (regroupés par la "
                                                   "source)", "administration": None},
}


# --------------------------------------------------------------------------------------------------------------
# Outils
# --------------------------------------------------------------------------------------------------------------
def _norm(s: str) -> str:
    """Texte comparable : sans accents, sans espaces, en minuscules, apostrophes unifiées."""
    s = unicodedata.normalize("NFKD", str(s).replace("’", "'")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", "", s).lower()


def _espaces(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).replace("’", "'")).strip()


class Verification:
    """Compte les motifs retrouvés par document ; un motif manquant arrête la production."""

    def __init__(self):
        self.par_doc: dict[str, dict] = {}

    def ok(self, doc: str, n: int = 1):
        self.par_doc.setdefault(doc, {"statut": "vérifié", "motifs": 0, "manquants": []})["motifs"] += n

    def manque(self, doc: str, motif: str):
        self.par_doc.setdefault(doc, {"statut": "vérifié", "motifs": 0, "manquants": []})["manquants"].append(motif)

    def bilan(self) -> dict:
        out = {}
        for k in sorted(self.par_doc):
            v = self.par_doc[k]
            out[k] = {"statut": "vérifié" if not v["manquants"] else "écart", "motifs": v["motifs"],
                      "manquants": v["manquants"]}
        return out

    def exiger(self):
        fautes = [f"{k} : {m}" for k, v in self.par_doc.items() for m in v["manquants"]]
        if fautes:
            raise SystemExit("Lecture non vérifiée dans les documents collectés :\n  " + "\n  ".join(fautes[:30]))


def _pdf(sid: str) -> Path:
    p = LAKE / SOURCES[sid]["fichier"]
    if not p.exists():
        raise FileNotFoundError(f"{p} absent : lancer « python pipeline/douanes_accises.py collecter »")
    return p


def _texte_page(sid: str, page: int) -> str:
    import pdfplumber
    with pdfplumber.open(_pdf(sid)) as d:
        return d.pages[page - 1].extract_text() or ""


def _lignes_tableau_bilan(sid: str) -> tuple[list[dict], list[float]]:
    """Lignes du tableau « Recettes douanières » d'un bilan : mots regroupés par ligne, colonnes des années."""
    import pdfplumber
    with pdfplumber.open(_pdf(sid)) as d:
        mots = d.pages[SOURCES[sid]["page_pdf"] - 1].extract_words()
    ded = next(w for w in mots if w["text"].startswith("DÉDOUANEMENT"))
    tot = next(w for w in mots if w["text"] == "TOTAL" and w["top"] > ded["top"] and abs(w["x0"] - ded["x0"]) < 400)
    annees_hdr = sorted((w for w in mots if re.fullmatch(r"20\d\d", w["text"]) and ded["top"] - 45 < w["top"] < ded["top"]
                         and ded["x0"] < w["x0"] < tot["x1"] + 120), key=lambda w: w["x0"])
    cols = [w["x0"] for w in annees_hdr]
    xmax = cols[-1] + 45
    sel = sorted((w for w in mots if ded["top"] - 5 <= w["top"] <= tot["bottom"] + 2 and ded["x0"] - 15 <= w["x0"] < xmax),
                 key=lambda w: (w["top"], w["x0"]))
    lignes, y = [], None
    for w in sel:
        if y is None or abs(w["top"] - y) > 2.5:
            lignes.append([])
            y = w["top"]
        lignes[-1].append(w)
    out = []
    for ligne in lignes:
        lib = "".join(w["text"] for w in ligne if w["x0"] < cols[0] - 25)
        vals = []
        for c in cols:
            vals.append("".join(w["text"] for w in sorted(ligne, key=lambda w: w["x0"]) if c - 25 <= w["x0"] < c + 38))
        out.append({"libelle": _norm(lib), "valeurs": vals})
    return out, [int(w["text"]) for w in annees_hdr]


def _fmt_source(v: float | None) -> str | None:
    """Écriture de la valeur telle que la source l'imprime (sans espaces) : 31284, 598,76, 0,0000576."""
    if v is None:
        return None
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.10f}".rstrip("0").replace(".", ",")


# --------------------------------------------------------------------------------------------------------------
# 1. Séries par produit (Insee, comptabilité nationale)
# --------------------------------------------------------------------------------------------------------------
PRODUITS_INSEE = [
    # id, libellé du site, libellé exact de la source, famille
    ("accise_produits_energetiques", "Accise sur les produits énergétiques (ex-TICPE : carburants, fioul)",
     "Accises sur les produits énergétiques (TICPE)", "energie"),
    ("accise_electricite", "Accise sur l'électricité (ex-TICFE)", "Accises sur l'électricité (TICFE)", "energie"),
    ("accise_gaz_naturel", "Accise sur le gaz naturel (ex-TICGN)", "Accises sur le gaz naturel (TICGN)", "energie"),
    ("autres_taxes_energie", "Autres taxes sur l'énergie", "Autres taxes sur l'énergie", "energie"),
    ("accises_tabacs", "Accises sur les tabacs", "Accises sur les tabacs", "tabacs"),
    ("accises_alcools_boissons", "Accises sur les alcools et autres boissons",
     "Accises sur les alcools et autres boissons", "alcools_boissons"),
    ("droits_importation_ue", "Droits de douane (droits d'importation au profit de l'Union européenne)",
     "Droits d'importation au profit de l'Union Européenne", "douane_union_europeenne"),
    ("octroi_de_mer", "Octroi de mer (départements d'outre-mer)", "Octroi de mer des départements d'outre-mer",
     "outre_mer"),
    ("tgap", "Taxe générale sur les activités polluantes (TGAP)", "Taxe générale sur les activités polluantes",
     "environnement"),
]


def _nombre(v):
    if v is None or (isinstance(v, str) and (not v.strip() or v.strip().upper() in {"N.D.", "ND", "NC", "-"})):
        return None
    return round(float(v), 4)


def lire_insee(verif: Verification) -> dict:
    import openpyxl
    sid = "douanes_insee_t3217"
    wb = openpyxl.load_workbook(LAKE / SOURCES[sid]["fichier"], read_only=True, data_only=True)
    lignes = list(wb.worksheets[0].iter_rows(values_only=True))
    titre = str(lignes[0][0] or "")
    if not titre.startswith("3.217"):
        raise SystemExit(f"{sid} : titre inattendu {titre!r}")
    entete = lignes[2]
    cols = [(j, int(v)) for j, v in enumerate(entete) if v is not None and re.fullmatch(r"(19|20)\d\d", str(v).split(".")[0])]
    annees = [a for _, a in cols]
    if annees != list(range(annees[0], annees[-1] + 1)):
        raise SystemExit(f"{sid} : années non contiguës {annees}")
    par_lib = {}
    for r in lignes[3:]:
        if r[1] is not None:
            par_lib.setdefault(_espaces(r[1]), r)
    produits = []
    for pid, lib, lib_src, fam in PRODUITS_INSEE:
        r = par_lib.get(_espaces(lib_src))
        if r is None:
            raise SystemExit(f"{sid} : ligne disparue {lib_src!r}")
        verif.ok(sid)
        vals = [_nombre(r[j]) for j, _ in cols]
        produits.append({"id": pid, "libelle": lib, "libelle_source": lib_src, "famille": fam, "valeurs_md": vals,
                         "statut": "trace"})
    notes = [_espaces(r[1]) for r in lignes if r[1] and str(r[1]).lstrip().startswith("Source")]
    return {"annees": annees, "produits": produits, "notes_source": notes, "titre_source": titre}


# --------------------------------------------------------------------------------------------------------------
# 2. Recettes perçues par la douane (DGDDI : données ouvertes 2010-2015 et bilans annuels)
# --------------------------------------------------------------------------------------------------------------
POSTES = [
    # id, libellé du site, groupe
    ("dedouanement", "Dédouanement (total du groupe)", "dedouanement"),
    ("droits_de_douane", "Droits de douane", "dedouanement"),
    ("tva_import", "TVA à l'importation", "dedouanement"),
    ("dedouanement_autres", "Autres recettes du dédouanement", "dedouanement"),
    ("energie_environnement", "Énergie et environnement (total du groupe)", "energie_environnement"),
    ("accise_produits_energetiques", "Accise sur les produits énergétiques (ex-TICPE)", "energie_environnement"),
    ("tsc_dom", "Taxe spéciale de consommation dans les départements d'outre-mer (TSC)", "energie_environnement"),
    ("tva_petrole", "TVA sur les produits pétroliers", "energie_environnement"),
    ("ticgn_ticfe_tichlc", "Accises sur le gaz naturel, l'électricité et le charbon (regroupées par la source)",
     "energie_environnement"),
    ("ticgn", "Accise sur le gaz naturel (ex-TICGN)", "energie_environnement"),
    ("ticfe", "Accise sur l'électricité (ex-TICFE)", "energie_environnement"),
    ("tichlc", "Accise sur le charbon (ex-TICHLC)", "energie_environnement"),
    ("contribution_exceptionnelle_petrole", "Contribution exceptionnelle sur la valeur des stocks pétroliers",
     "energie_environnement"),
    ("taxes_professionnels_petrole", "Taxes et rémunérations pour le compte de professionnels du pétrole",
     "energie_environnement"),
    ("tgap", "Taxe générale sur les activités polluantes (TGAP)", "energie_environnement"),
    ("contributions_indirectes", "Contributions indirectes (total du groupe)", "contributions_indirectes"),
    ("alcools_boissons", "Alcools et boissons", "contributions_indirectes"),
    ("tabacs", "Tabacs", "contributions_indirectes"),
    ("autres_ci", "Autres contributions indirectes", "contributions_indirectes"),
    ("octroi_mer_maritime", "Octroi de mer et activités maritimes (total du groupe)", "octroi_mer_maritime"),
    ("octroi_de_mer", "Octroi de mer", "octroi_mer_maritime"),
    ("droits_de_ports", "Droits de ports", "octroi_mer_maritime"),
    ("dafn", "Droit annuel de francisation et de navigation (DAFN)", "octroi_mer_maritime"),
    ("tsvr", "Taxe spéciale sur certains véhicules routiers (taxe à l'essieu)", "tsvr"),
    ("autres_taxes", "Autres taxes et perceptions diverses", "autres"),
    ("total", "Total des recettes perçues par la douane", "total"),
]
GROUPES = ["dedouanement", "energie_environnement", "contributions_indirectes", "octroi_mer_maritime", "tsvr",
           "autres_taxes"]

# Libellés du classeur 2010-2015 (feuille « recettes douanieres »), lus par début de libellé exact.
XLS_LIGNES = {
    "dedouanement": "1.   Dédouanement",
    "droits_de_douane": "Droits de douane et assimilés",
    "tva_import": "TVA Import",
    "dedouanement_autres": "Autres recettes liées au dédouanement",
    "accise_produits_energetiques": "TIC",
    "tsc_dom": "TSC DOM",
    "tva_petrole": "TVA Pétrole",
    "ticgn": "TICGN",
    "ticfe": "TICFE",
    "tichlc": "TICHLC",
    "contribution_exceptionnelle_petrole": "Contribution exceptionnelle sur la valeu",
    "taxes_professionnels_petrole": "Taxes et rémunérations pour le compte de",
    "tgap": "TGAP",
    "contributions_indirectes": "D. Contributions indirectes",
    "alcools_boissons": "3a. Alcools et boissons",
    "tabacs": "3b. Tabacs",
    "autres_ci": "3c.  Autres CI",
    "octroi_de_mer": "Octroi de mer",
    "droits_de_ports": "Droits de ports",
    "dafn": "DAFN",
    "tsvr": "TSVR",
    "autres_taxes": "Divers",
    "total": "Total général",
}
XLS_GROUPES_SOURCE = {"B": "B. Fiscalité énergétique", "C": "C. Fiscalité environnementale",
                      "F": "F. Fiscalité outre-mer"}

# Montants lus dans les bilans (M€), vérifiés contre le PDF : (poste, libellé normalisé de la ligne, valeurs par
# colonne d'année). None = case « * » (transfert de taxe), « - » ou ligne absente ; la raison est dans NULLS_BILANS.
LECTURES_BILANS = {
    "douanes_bilan_2020": {
        "annees": [2019, 2020],
        "lignes": [
            ("dedouanement", "dedouanement", [8568, 7556]), ("droits_de_douane", "droitsdedouane", [2248, 2087]),
            ("tva_import", "tvaimport", [6292, 5450]), ("dedouanement_autres", "autres", [28, 19]),
            ("energie_environnement", "energieetenvironnement", [56276, 47009]),
            ("accise_produits_energetiques", "ticpe", [33321, 28451]), ("tsc_dom", "tscdom", [554, 502]),
            ("tva_petrole", "tvapetrole", [11407, 8021]), ("ticgn_ticfe_tichlc", "ticgn+ticfe+tichlc", [10263, 9555]),
            ("taxes_professionnels_petrole", "taxesetremunerationspourlecompte", [9, 9]),
            ("tgap", "tgap", [722, 471]),
            ("contributions_indirectes", "contributionsindirectes(ci)", [17638, 19340]),
            ("alcools_boissons", "alcoolsetboissons", [4125, 4004]), ("tabacs", "tabacs", [13485, 15328]),
            ("autres_ci", "autresci", [28, 8]),
            ("octroi_mer_maritime", "octroidemeretactivitesmaritimes", [1972, 1833]),
            ("octroi_de_mer", "octroidemer", [1372, 1313]), ("droits_de_ports", "droitsdeports", [556, 475]),
            ("dafn", "dafn", [45, 45]), ("tsvr", "tsvr-taxesurcertainsvehicules", [181, 175]),
            ("autres_taxes", "autrestaxes", [466, 362]), ("total", "total", [85101, 76275]),
        ],
    },
    "douanes_bilan_2022": {
        "annees": [2021, 2022],
        "lignes": [
            ("dedouanement", "dedouanement", [9334, 3722]), ("droits_de_douane", "droitsdedouane", [2408, 3062]),
            ("tva_import", "tvaimport", [6875, 593]), ("dedouanement_autres", "autres", [51, 67]),
            ("energie_environnement", "energieetenvironnement", [42512, 34697]),
            ("accise_produits_energetiques", "ticpe", [31991, 32507]), ("tsc_dom", "tscdom", [533, 550]),
            ("tva_petrole", "tvapetrole", [259, None]), ("ticgn_ticfe_tichlc", "ticgn+ticfe+tichlc", [9690, 1633]),
            ("taxes_professionnels_petrole", "taxesetremunerationspourlecompte", [8, 8]),
            ("tgap", "tgap", [32, None]),
            ("contributions_indirectes", "contributionsindirectes(ci)", [19339, 18713]),
            ("alcools_boissons", "alcoolsetboissons", [4130, 4290]), ("tabacs", "tabacs", [15204, 14414]),
            ("autres_ci", "autresci", [5, 9]),
            ("octroi_mer_maritime", "octroidemeretactivitesmaritimes", [2027, 2263]),
            ("octroi_de_mer", "octroidemer", [1485, 1696]), ("droits_de_ports", "droitsdeports", [492, 563]),
            ("dafn", "dafn", [49, 4]), ("tsvr", "routiers(ditetaxeal'essieu)", [11, None]),
            ("autres_taxes", "autrestaxes", [325, 293]), ("total", "total", [73548, 59688]),
        ],
    },
    "douanes_bilan_2023": {
        "annees": [2023],
        "lignes": [
            ("dedouanement", "dedouanement", [3045]), ("droits_de_douane", "droitsdedouane", [2653]),
            ("tva_import", "tvaimport", [331]), ("dedouanement_autres", "autres", [62]),
            ("energie_environnement", "energieetenvironnement", [32899]),
            ("accise_produits_energetiques", "ticpe", [31721]), ("tsc_dom", "tscdom", [583]),
            ("tva_petrole", "tvapetrole*", [0.18]), ("ticgn_ticfe_tichlc", "ticgn+ticfe+tichlc*", [35]),
            ("taxes_professionnels_petrole", "taxesetremunerationspourlecompte", [11]),
            ("tgap", "tgap*", [549]),
            ("contributions_indirectes", "contributionsindirectes(ci)", [18437]),
            ("alcools_boissons", "alcoolsetboissons", [4211]), ("tabacs", "tabacs", [14214]),
            ("autres_ci", "autresci", [11]),
            ("octroi_mer_maritime", "octroidemeretactivitesmaritimes", [2263]),
            ("octroi_de_mer", "octroidemer", [1696]), ("droits_de_ports", "droitsdeports", [604]),
            ("dafn", "dafn*", [3]), ("tsvr", "tsvr-taxesurcertainsvehicules", [None]),
            ("autres_taxes", "autrestaxes", [245]), ("total", "total", [56924]),
        ],
    },
    "douanes_bilan_2024": {
        "annees": [2024],
        "lignes": [
            ("dedouanement", "dedouanement", [3124]), ("droits_de_douane", "droitsdedouane", [2693]),
            ("tva_import", "tvaimport", [369]), ("dedouanement_autres", "autres", [62]),
            ("energie_environnement", "energieetenvironnement", [32278]),
            ("accise_produits_energetiques", "dontticpe", [31660]), ("tsc_dom", "tscdom", [596.05]),
            ("tva_petrole", "tvapetrole*", [0.97]), ("ticgn_ticfe_tichlc", "ticgn+ticfe+tichlc*", [0.0000576]),
            ("taxes_professionnels_petrole", "taxesetremunerationspourlecompte", [12.49]),
            ("tgap", "tgap*", [8.59]),
            ("contributions_indirectes", "contributionsindirectes(ci)", [2932.16]),
            ("alcools_boissons", "alcoolsetboissons", [725.14]), ("tabacs", "tabacs", [2197.30]),
            ("autres_ci", "autresci", [9.72]),
            ("octroi_mer_maritime", "octroidemeretactivitesmaritimes", [2323.17]),
            ("octroi_de_mer", "octroidemer", [1706.92]), ("droits_de_ports", "droitsdeports", [614.88]),
            ("dafn", "dafn*", [1.37]), ("tsvr", "tsvr-taxesurcertainsvehicules", [None]),
            ("autres_taxes", "autrestaxes", [220.86]), ("total", "total", [40878]),
        ],
    },
    "douanes_bilan_2025": {
        "annees": [2025],
        "lignes": [
            ("dedouanement", "dedouanement", [3317]), ("droits_de_douane", "droitsdedouane", [2893]),
            ("tva_import", "tvaimport", [360]), ("dedouanement_autres", "autres", [64]),
            ("energie_environnement", "energie&environnement", [31905]),
            ("accise_produits_energetiques", "dontaccisesurlesproduitsenergetiques", [31284]),
            ("tsc_dom", "tscdrom", [598.76]), ("tva_petrole", "tvapetrole*", [0.20]),
            ("taxes_professionnels_petrole", "taxesetremunerationspourlecompte", [10.77]),
            ("tgap", "tgap*", [11.29]),
            ("contributions_indirectes", "contributionsindirectes(ci)", [156.75]),
            ("alcools_boissons", "alcoolsetboissons", [57.99]), ("tabacs", "tabacs", [85.09]),
            ("autres_ci", "autresci", [13.67]),
            ("octroi_mer_maritime", "octroidemer&activitesmaritimes", [2372.58]),
            ("octroi_de_mer", "octroidemer", [1740.74]), ("droits_de_ports", "droitsdeports", [631.81]),
            ("dafn", "dafn*", [0.03]), ("autres_taxes", "autrestaxes", [267.53]), ("total", "total", [37919.49]),
        ],
    },
}
NULLS_BILANS = {
    ("douanes_bilan_2022", "tva_petrole", 2022): "case « * » de la source : « Transfert de taxe au 1er janvier 2021 »",
    ("douanes_bilan_2022", "tgap", 2022): "case « * » de la source : « Transfert de taxe au 1er janvier 2021 »",
    ("douanes_bilan_2022", "tsvr", 2022): "case « * » de la source : « Transfert de taxe au 1er janvier 2021 »",
    ("douanes_bilan_2023", "tsvr", 2023): "case « - » de la source",
    ("douanes_bilan_2024", "tsvr", 2024): "case « - » de la source",
}
# Citations retrouvées sur la page du tableau (ruptures de série et lecture des « * »).
CITATIONS_BILANS = {
    "douanes_bilan_2020": ["Une baisse des recettes en 2020 est une conséquence directe", "de la crise sanitaire."],
    "douanes_bilan_2022": ["*Transfert de taxe au 1er janvier 2021"],
    "douanes_bilan_2023": ["*Transfert de taxe entre 2021 et 2023"],
    "douanes_bilan_2024": ["Transfert de taxe entre 2021 et 2023",
                           "Nb : diminutions des perceptions liées au transfert des missions fiscales"],
    "douanes_bilan_2025": ["Transfert de taxe", "Diminution des perceptions liées au transfert des missions fiscales"],
}
# Destination des recettes (chiffres clés, page 4 des bilans 2024 et 2025).
DESTINATION = {
    "douanes_bilan_2024": {
        "annee": 2024, "motifs": ["52%", "7%", "41%", "40,88 Mds €", "Organismes sociaux", "et collectivités locales",
                                  "UE", "État"],
        "parts": [("etat", 52.0), ("collectivites_et_organismes_sociaux", 41.0), ("union_europeenne", 7.0)],
        "statut": "trace",
        "lecture": "Parts publiées sur le graphique « La douane contribue à la perception des recettes de l'État et "
                   "de l'UE », chacune écrite à côté de son destinataire.",
    },
    "douanes_bilan_2025": {
        "annee": 2025, "motifs": ["54,5 %", "37,9 %", "7,6 %", "37,92 Mds €", "Destination des recettes",
                                  "collectivités locales", "& organismes sociaux", "UE", "État"],
        # Règle « chiffre calculé par le site » (docs/NEUTRALITE.md) : les trois parts publiées ne sont pas écrites à
        # côté de leur destinataire ; leur attribution par déduction n'est pas publiée.
        "parts": [], "statut": "non_publie",
        "lecture": "Les trois parts du graphique « Destination des recettes » (54,5 %, 37,9 % et 7,6 %) sont publiées "
                   "sans être écrites à côté de leur destinataire : le site ne les attribue pas par déduction. À "
                   "reprendre si la douane publie le détail.",
    },
}


def lire_xls_2010_2015(verif: Verification) -> dict:
    import xlrd
    sid = "douanes_dgddi_recettes_2010_2015"
    b = xlrd.open_workbook(str(LAKE / SOURCES[sid]["fichier"]))
    s = b.sheet_by_name("recettes douanieres")
    entete = s.row_values(0)
    annees = [int(v) for v in entete[1:] if v != ""]
    if annees != list(range(2010, 2016)):
        raise SystemExit(f"{sid} : années inattendues {annees}")
    lignes = [(str(s.cell_value(r, 0)), [s.cell_value(r, c) for c in range(1, 1 + len(annees))]) for r in range(1, s.nrows)]

    def ligne(debut: str, exacte: bool):
        for lib, vals in lignes:
            if (_espaces(lib) == _espaces(debut)) if exacte else lib.startswith(debut):
                return [round(float(v), 3) if v != "" else None for v in vals]
        raise SystemExit(f"{sid} : ligne disparue {debut!r}")

    postes = {}
    for pid, lib in XLS_LIGNES.items():
        exacte = pid not in {"contribution_exceptionnelle_petrole", "taxes_professionnels_petrole"}
        postes[pid] = ligne(lib, exacte)
        verif.ok(sid)
    src = {k: ligne(v, True) for k, v in XLS_GROUPES_SOURCE.items()}
    verif.ok(sid, len(src))
    calculs = []
    postes["energie_environnement"] = [round(a + b_, 3) for a, b_ in zip(src["B"], src["C"])]
    calculs.append({"poste": "energie_environnement", "annees": annees,
                    "formule": "somme des groupes « B. Fiscalité énergétique » et « C. Fiscalité environnementale » "
                               "du classeur, pour suivre le regroupement des bilans"})
    postes["octroi_mer_maritime"] = [round(a + b_ + c, 3) for a, b_, c in
                                     zip(src["F"], postes["droits_de_ports"], postes["dafn"])]
    calculs.append({"poste": "octroi_mer_maritime", "annees": annees,
                    "formule": "somme de « F. Fiscalité outre-mer », « Droits de ports » et « DAFN » du classeur, "
                               "pour suivre le regroupement des bilans"})
    return {"annees": annees, "postes": postes, "calculs": calculs}


def lire_bilans(verif: Verification) -> dict:
    out = {}
    for sid, spec in LECTURES_BILANS.items():
        lignes, annees = _lignes_tableau_bilan(sid)
        if annees != spec["annees"]:
            raise SystemExit(f"{sid} : colonnes {annees}, attendues {spec['annees']}")
        postes = {}
        for pid, lib, vals in spec["lignes"]:
            idx = [i for i, ln in enumerate(lignes) if ln["libelle"].startswith(lib)]
            if pid == "dedouanement_autres":
                idx = [i for i in idx if lignes[i]["libelle"].rstrip("*") == "autres"]
            if pid == "octroi_de_mer":
                idx = [i for i in idx if not lignes[i]["libelle"].startswith(("octroidemeret", "octroidemer&"))]
            if not idx:
                verif.manque(sid, f"ligne {lib}")
                continue
            i = idx[0]
            voisins = [lignes[j]["valeurs"] for j in (i - 1, i, i + 1) if 0 <= j < len(lignes)]
            for k, v in enumerate(vals):
                if v is None:
                    if (sid, pid, annees[k]) not in NULLS_BILANS:
                        raise SystemExit(f"{sid} : null sans raison pour {pid} {annees[k]}")
                    verif.ok(sid)
                    continue
                attendu = _fmt_source(v)
                if any(attendu in vv[k].rstrip("*").replace(" ", "") for vv in voisins):
                    verif.ok(sid)
                else:
                    verif.manque(sid, f"{pid} {annees[k]} = {attendu} (lu : {[vv[k] for vv in voisins]})")
            postes[pid] = vals
        texte = _espaces(_texte_page(sid, SOURCES[sid]["page_pdf"]))
        for c in CITATIONS_BILANS[sid]:
            (verif.ok if _espaces(c) in texte else lambda d, m=c: verif.manque(d, f"citation « {m} »"))(sid)
        out[sid] = {"annees": annees, "postes": postes}
    return out


def lire_destination(verif: Verification) -> list[dict]:
    out = []
    for sid, spec in DESTINATION.items():
        texte = _espaces(_texte_page(sid, SOURCES[sid]["page_chiffres_cles"]))
        for m in spec["motifs"]:
            if _espaces(m) in texte:
                verif.ok(sid)
            else:
                verif.manque(sid, f"chiffres clés « {m} »")
        out.append({"annee": spec["annee"], "document": sid, "page_pdf": SOURCES[sid]["page_chiffres_cles"],
                    "parts": [{"destinataire": d, "pct": p} for d, p in spec["parts"]], "statut": spec["statut"],
                    "lecture": spec["lecture"]})
    return out


def assembler_collecte(xls: dict, bilans: dict) -> dict:
    editions = [{"document": "douanes_dgddi_recettes_2010_2015", "annees": xls["annees"]}]
    editions += [{"document": sid, "annees": b["annees"], "page_pdf": SOURCES[sid]["page_pdf"]} for sid, b in bilans.items()]
    annees = sorted({a for e in editions for a in e["annees"]})
    if len(annees) != sum(len(e["annees"]) for e in editions):
        raise SystemExit("deux éditions couvrent la même année : publier les deux valeurs (non prévu ici)")
    doc_annee = {a: e["document"] for e in editions for a in e["annees"]}
    postes = []
    for pid, lib, groupe in POSTES:
        vals, absent = [], []
        for a in annees:
            sid = doc_annee[a]
            if sid == "douanes_dgddi_recettes_2010_2015":
                serie = xls["postes"].get(pid)
                vals.append(serie[xls["annees"].index(a)] if serie else None)
                if not serie:
                    absent.append(a)
            else:
                b = bilans[sid]
                serie = b["postes"].get(pid)
                v = serie[b["annees"].index(a)] if serie else None
                vals.append(v)
                if not serie:
                    absent.append(a)
        if all(v is None for v in vals):
            continue
        p = {"id": pid, "libelle": lib, "groupe": groupe, "valeurs_m": vals}
        raisons = {str(a): r for (sid, q, a), r in sorted(NULLS_BILANS.items()) if q == pid}
        for a in absent:
            raisons.setdefault(str(a), "ligne absente de l'édition qui publie cette année")
        if raisons:
            p["null_raisons"] = dict(sorted(raisons.items()))
        postes.append(p)
    par_id = {p["id"]: p["valeurs_m"] for p in postes}
    coherence = []
    for i, a in enumerate(annees):
        total = par_id["total"][i]
        somme = round(sum(par_id[g][i] for g in GROUPES if par_id.get(g) and par_id[g][i] is not None), 2)
        coherence.append({"annee": a, "total_publie_m": total, "somme_groupes_m": somme,
                          "ecart_m": round(total - somme, 2)})
    return {"annees": annees, "editions": editions, "postes": postes, "calculs": xls["calculs"],
            "coherence": coherence}


# --------------------------------------------------------------------------------------------------------------
# 3. Affectation par produit
# --------------------------------------------------------------------------------------------------------------
# Accise sur les produits énergétiques (ex-TICPE) : tableau des voies et moyens, Md€ (signe de la source).
LECTURES_VM_ENERGIE = {
    "douanes_vm1_plf2024": {
        "page": 29, "annees": [2022, 2023, 2024], "statuts": ["execution", "prevision", "prevision"],
        "lignes": [
            ("brute_totale", "TICPE brute totale", None, "32,5 31,4 31,7"),
            ("collectivites_territoriales", "Transfert aux collectivités territoriales", "collectivites_territoriales",
             "-11,3 -11,1 -11,1"),
            ("afitf", "Transfert à l'AFITF", "afitf", "-1,2 -1,9 -2,1"),
            ("idfm", "Transfert Île-de-France Mobilités (ex-STIF)", "idfm", "-0,1 -0,1 -0,1"),
            ("autres", "Autres", "autres", "0,2 - -"),
            ("brute_etat", "TICPE brute État", "etat", "20,1 18,3 18,4"),
            ("remboursements", "Remboursements et dégrèvements de TICPE", None, "-2,2 -1,9 -2,0"),
            ("nette_etat", "TICPE nette État", None, "18,0 16,4 16,4"),
        ],
    },
    "douanes_vm1_plf2025": {
        "page": 27, "annees": [2023, 2024, 2025], "statuts": ["execution", "prevision", "prevision"],
        "lignes": [
            ("brute_totale", "TICPE brute totale", None, "31,7 31,5 31,2"),
            ("collectivites_territoriales", "Transfert aux collectivités territoriales", "collectivites_territoriales",
             "-11,2 -12,2 -12,2"),
            ("afitf", "Transfert à l'AFITF", "afitf", "-1,9 -2,0 -1,3"),
            ("idfm", "Transfert Île-de-France Mobilités (ex-STIF)", "idfm", "-0,1 -0,1 -0,1"),
            ("autres", "Autres", "autres", "0,2 0,4 0,4"),
            ("brute_etat", "TICPE brute État", "etat", "18,7 17,6 18,1"),
            ("remboursements", "Remboursements et dégrèvements de TICPE", None, "-1,9 -2,1 -1,6"),
            ("nette_etat", "TICPE nette État", None, "16,8 15,5 16,5"),
        ],
    },
    "douanes_vm1_plf2026": {
        "page": 28, "annees": [2024, 2025, 2026], "statuts": ["execution", "prevision_revisee", "prevision"],
        "lignes": [
            ("brute_totale", "Accise sur les produits énergétiques (ex-TICPE) brute totale", None, "31,6 31,4 31,5"),
            ("collectivites_territoriales", "Transfert aux collectivités territoriales", "collectivites_territoriales",
             "-11,9 -12,0 -11,7"),
            ("afitf", "Transfert à l'AFITF", "afitf", "-1,7 -1,2 -1,6"),
            ("idfm", "Transfert Île-de-France Mobilités (ex-STIF)", "idfm", "-0,1 -0,1 -"),
            ("zni_cspe", "Fraction ZNI & Fraction CSPE", "zni_cspe", " -0,1 -1,6"),
            ("autres", "Autres", "autres", "0,0 0,2 0,2"),
            ("brute_etat", "Accise sur les produits énergétiques (ex-TICPE) brute État", "etat", "18,1 18,1 16,8"),
            ("remboursements", "Remboursements et dégrèvements de l'ex-TICPE", None, "-2,0 -1,6 -1,5"),
            ("nette_etat", "Accise sur les produits énergétiques (ex-TICPE) nette État", None, "16,0 16,5 15,3"),
        ],
    },
}
# Frais de perception des droits de douane conservés par l'État (ligne 2301 des voies et moyens), M€.
LECTURES_2301 = [
    (2021, 595, "execution", "douanes_vm1_plf2024", 50, "L'exécution 2021 s'établissait à 595 M€."),
    (2022, 760, "execution", "douanes_vm1_plf2024", 50, "Finalement, l'exécution 2022 s'établit à 760 M€."),
    (2023, 654, "execution", "douanes_vm1_plf2025", 48, "Finalement, l'exécution 2023 s'établit à 654 M€."),
    (2024, 665, "execution", "douanes_vm1_plf2026", 54, "Finalement, l'exécution 2024 s'établit à 665 M€."),
    (2025, 657, "prevision_revisee", "douanes_vm1_plf2026", 54, "Le PLF pour 2026 révise cette prévision à 657 M€"),
    (2026, 677, "prevision", "douanes_vm1_plf2026", 54, "prévoit un montant de 677 M€"),
]
REGLE_2301 = ("Chaque État membre bénéficie du remboursement des frais de perception des ressources propres "
              "traditionnelles qu'il recouvre au profit de l'Union européenne (droits de douane uniquement à "
              "compter de 2018, les cotisations sur le sucre étant supprimées à cette date).")
TAUX_2301 = ("le taux de remboursement était fixé à 20 % du produit collecté. Ce taux a été réhaussé à 25 % par la "
             "décision du Conseil du 14 décembre 2020")
RPT_HORS_PSR = ("Depuis la loi de finances pour 2010, le PSR-UE n'intègre plus les ressources propres "
                "traditionnelles.")

# PLFSS 2026, annexe 3, tableau 31 (p. 44) : colonnes 2026, 2025, ..., 2018.
ANNEES_PLFSS = [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018]
CLES_TABACS = {"cnam": [100, 100, 99.5, 99.5, 99.5, 99.5, 99.3, 99.56, 99.75],
               "ravgdt": [None, None, 0.5, 0.5, 0.5, 0.5, 0.7, 0.44, 0.25]}
MOTIFS_TABACS = ("Droit de consommation sur les tabacs CNAM : 100% CNAM : 100% CNAM : 99,5% CNAM : 99,5% CNAM : 99,5% "
                 "CNAM : 99,5% CNAM : 99,3% CNAM : 99,56% CNAMTS : 99,75 %",
                 "RAVGDT : 0,5 % RAVGDT : 0,5 % RAVGDT : 0,5 % RAVGDT : 0,5 % RAVGDT : 0,7 % RAVGDT : 0,44 % "
                 "RAVGDT : 0,25 %",
                 "DGDDI/DGFIP 11 423 12 086")
CLES_ALCOOLS = {"msa_maladie": [46.60, 46.60, 46.60, 46.60, 46.60, 46.60, 46.60, 53.08, 55.77],
                "msa_vieillesse": [24.51, 24.51, 24.51, 26.02, 26.67, 39.59, 39.59, 40.05, 40.05],
                "msa_rco": [28.89, 28.89, 28.89, 27.38, 26.73, 13.81, 13.81, 6.87, 4.18]}
MOTIFS_ALCOOLS = ("maladie : 46,60 % maladie : 46,60 % maladie : 46,60 % maladie : 46,60 % maladie : 46,60 % "
                  "maladie : 46,60 % maladie : 46,60 % maladie : 53,08 % maladie : 55,77 %",
                  "vieillesse : 24,51 % vieillesse : 24,51 % vieillesse : 24,51 % vieillesse : 26,02 % vieillesse : "
                  "26,67 % vieillesse : 39,59 % vieillesse : 39,59 % vieillesse : 40,05 % vieillesse : 40,05 %",
                  "RCO : 28,89% RCO : 28,89% RCO : 28,89% RCO : 27,38 % RCO : 26,73 % RCO : 13,81 % RCO : 13,81 % "
                  "RCO : 6,87% RCO : 4,18 %")
# Montants des prévisions (M€) : (id, libellé, recouvrement, 2026, 2025, motif)
MONTANTS_PLFSS = [
    ("tabacs_droit_consommation", "Droit de consommation sur les tabacs (art. 575 CGI)", "DGDDI/DGFIP", 11423, 12086,
     "DGDDI/DGFIP 11 423 12 086"),
    ("tabacs_droit_licence", "Droit de licence sur la rémunération des débitants de tabacs (art. 568 CGI)",
     "DGDDI/DGFIP", 330, 340, "débitants de tabacs DGDDI/DGFIP 330 340"),
    ("alcools_droit_consommation", "Droit de consommation sur les alcools (art. 403 CGI)", "DGDDI", 2173, 2175,
     "DGDDI 2 173 2 175"),
    ("alcools_circulation_vins", "Droit de circulation sur les vins, poirés, cidres et hydromels (art. 438 CGI)",
     "DGDDI", 98, 101, "hydromels DGDDI 98 101"),
    ("alcools_cotisation_18", "Cotisation sur les alcools de plus de 18° (art. L 245-7 à L 245-11 CSS)", "DGDDI",
     734, 732, "DGDDI 734 732"),
    ("alcools_circulation_bieres", "Droit de circulation sur les bières", "DGDDI", 1081, 1067,
     "Droit de circulation sur les bières DGDDI 1 081 1 067"),
    ("alcools_produits_intermediaires", "Droit de consommation sur les produits intermédiaires (art. 402 bis CGI)",
     "DGDDI", 54, 56, "intermédiaires DGDDI 54 56"),
]


def lire_affectation(verif: Verification) -> dict:
    # Accise sur les produits énergétiques
    editions = []
    for sid, spec in LECTURES_VM_ENERGIE.items():
        texte = _espaces(_texte_page(sid, spec["page"]))
        if _espaces(" ".join(str(a) for a in spec["annees"])) in texte:
            verif.ok(sid)
        else:
            verif.manque(sid, f"en-tête {spec['annees']}")
        lignes = []
        for lid, lib, dest, motif in spec["lignes"]:
            m = _espaces(motif)
            if m in texte:
                verif.ok(sid)
            else:
                verif.manque(sid, f"{lid} « {motif} »")
            jetons = motif.split(" ") if not motif.startswith(" ") else [None] + motif.strip().split(" ")
            vals = [None if (t is None or t == "-") else float(t.replace(",", ".")) for t in jetons]
            if len(vals) != 3:
                raise SystemExit(f"{sid} {lid} : trois valeurs attendues")
            ligne = {"id": lid, "libelle_source": lib, "valeurs_md": vals}
            if dest:
                ligne["destinataire"] = dest
            lignes.append(ligne)
        editions.append({"document": sid, "page_pdf": spec["page"], "annees": spec["annees"],
                         "statuts": spec["statuts"], "lignes": lignes})
    serie_annees = [ed["annees"][0] for ed in editions]
    if any(ed["statuts"][0] != "execution" for ed in editions):
        raise SystemExit("la première colonne de chaque édition doit être l'exécution")
    serie: dict[str, list] = {}
    for i, ed in enumerate(editions):
        for ln in ed["lignes"]:
            serie.setdefault(ln["id"], [None] * len(editions))[i] = ln["valeurs_md"][0]
    energie = {
        "libelle": "Accise sur les produits énergétiques (ex-TICPE)",
        "unite": "milliards d'euros",
        "lecture_signes": "Signe de la source : un transfert vers un affectataire est négatif (il diminue la part de "
                          "l'État), « brute État » = brute totale moins les transferts ; « nette État » = brute État "
                          "moins les remboursements et dégrèvements.",
        "editions": editions,
        "executions": {"annees": serie_annees,
                       "lignes": [{"id": k, "valeurs_md": v} for k, v in serie.items()],
                       "source_par_annee": {str(ed["annees"][0]): ed["document"] for ed in editions}},
        "deja_dans_le_site": {"fichier": "prelevements/affectation.json", "cle": "prelevements.ticpe",
                              "annee": 2025, "note": "La colonne 2025 du PLF 2026 (prévision révisée) est la "
                                                     "ventilation 2025 déjà publiée par le site : elle n'est pas "
                                                     "reprise dans « executions »."},
    }
    # Tabacs et alcools : clés de répartition 2018 à 2026 et montants 2025 et 2026.
    sid = "douanes_plfss2026_annexe3"
    texte = _espaces(_texte_page(sid, SOURCES[sid]["page_pdf"]))
    for m in MOTIFS_TABACS + MOTIFS_ALCOOLS + tuple(x[5] for x in MONTANTS_PLFSS):
        if _espaces(m) in texte:
            verif.ok(sid)
        else:
            verif.manque(sid, f"« {m} »")
    for cles in (CLES_TABACS, CLES_ALCOOLS):
        for i in range(len(ANNEES_PLFSS)):
            if abs(sum(v[i] or 0 for v in cles.values()) - 100) > 0.011:
                raise SystemExit(f"{sid} : clés de {ANNEES_PLFSS[i]} ne somment pas à 100")
    ordre = sorted(range(len(ANNEES_PLFSS)), key=lambda i: ANNEES_PLFSS[i])
    annees = [ANNEES_PLFSS[i] for i in ordre]

    def cles_json(cles):
        return [{"destinataire": d, "pct": [v[i] for i in ordre]} for d, v in cles.items()]

    montants = [{"id": i, "libelle_source": lib, "recouvrement": rec, "prevision_2025_m": m25, "prevision_2026_m": m26}
                for i, lib, rec, m26, m25, _ in MONTANTS_PLFSS]
    tabacs = {
        "libelle": "Droit de consommation sur les tabacs",
        "document": sid, "page_pdf": SOURCES[sid]["page_pdf"],
        "cles": {"annees": annees, "parts": cles_json(CLES_TABACS)},
        "lecture": "Part du produit attribuée à chaque organisme, en pourcentage, telle que l'écrit le tableau 31. En "
                   "2025 et 2026 la case du RAVGDT est vide (null) et le tableau écrit « CNAM : 100% ».",
        "autres_droits": "Droit de licence sur la rémunération des débitants de tabacs : CNAM toutes les années "
                         "(CNAMTS en 2018).",
        "deja_dans_le_site": {"fichier": "prelevements/affectation.json", "cle": "prelevements.tabac", "annee": 2025},
    }
    alcools = {
        "libelle": "Droit de consommation sur les alcools",
        "document": sid, "page_pdf": SOURCES[sid]["page_pdf"],
        "cles": {"annees": annees, "parts": cles_json(CLES_ALCOOLS)},
        "lecture": "Part du droit de consommation attribuée à chaque branche de la MSA des non-salariés agricoles, "
                   "en pourcentage ; la cotisation sur les alcools de plus de 18°, les droits de circulation sur les "
                   "bières et sur les vins et le droit sur les produits intermédiaires vont à la MSA vieillesse "
                   "(cellule fusionnée du tableau, même lecture que prelevements/affectation.json).",
        "deja_dans_le_site": {"fichier": "prelevements/affectation.json", "cle": "prelevements.alcool", "annee": 2025},
    }
    # Droits de douane : règle et frais de perception (ligne 2301).
    lignes_2301 = []
    pages = {}
    for a, v, st, sid2, page, cit in LECTURES_2301:
        t = pages.setdefault((sid2, page), _espaces(_texte_page(sid2, page)))
        (verif.ok if _espaces(cit) in t else (lambda d, c=cit: verif.manque(d, f"citation « {c} »")))(sid2)
        lignes_2301.append({"annee": a, "frais_perception_etat_m": v, "statut": st, "document": sid2, "page_pdf": page,
                            "citation": cit})
    t54 = pages[("douanes_vm1_plf2026", 54)]
    for c in (REGLE_2301, TAUX_2301):
        (verif.ok if _espaces(c) in t54 else (lambda d, c=c: verif.manque(d, f"citation « {c[:50]} »")))(
            "douanes_vm1_plf2026")
    t_psr = _espaces(_texte_page("douanes_vm1_plf2026", 89))
    (verif.ok if _espaces(RPT_HORS_PSR) in t_psr else (lambda d: verif.manque(d, "citation RPT hors PSR")))(
        "douanes_vm1_plf2026")
    droits = {
        "libelle": "Droits de douane (ressources propres traditionnelles de l'Union européenne)",
        "regle": {"citations": [REGLE_2301, TAUX_2301, RPT_HORS_PSR], "document": "douanes_vm1_plf2026",
                  "pages_pdf": [54, 89],
                  "taux_frais_perception": [{"de": 2014, "a": 2020, "pct": 20}, {"de": 2021, "a": None, "pct": 25}]},
        "destinataires": ["union_europeenne", "etat"],
        "frais_perception": lignes_2301,
        "lecture": "Les droits de douane appartiennent au budget de l'Union européenne ; l'État en conserve une part "
                   "au titre des frais de perception (ligne 2301 de ses recettes non fiscales). Ces montants ne "
                   "transitent pas par le prélèvement sur recettes au profit de l'Union (site/data/ue/). Les droits "
                   "perçus par la douane (collecte.json) et les frais de perception (année de rattachement des "
                   "voies et moyens) ne sont pas rapprochés ici : leurs calendriers diffèrent.",
    }
    return {"energie": energie, "tabacs": tabacs, "alcools": alcools, "montants_plfss": montants,
            "droits_de_douane": droits}


# --------------------------------------------------------------------------------------------------------------
# 4. Écarts entre sources (mêmes produits, même année, notions différentes) : publiés, jamais tranchés
# --------------------------------------------------------------------------------------------------------------
def ecarts(produits: dict, collecte: dict, affectation: dict) -> list[dict]:
    insee = {p["id"]: dict(zip(produits["annees"], p["valeurs_md"])) for p in produits["produits"]}
    perc = {p["id"]: dict(zip(collecte["annees"], p["valeurs_m"])) for p in collecte["postes"]}
    vm = {}
    for ed in affectation["energie"]["editions"]:
        a = ed["annees"][0]
        vm[a] = next(ln["valeurs_md"][0] for ln in ed["lignes"] if ln["id"] == "brute_totale")
    out = []
    comparaisons = [
        ("accise_produits_energetiques", "accise_produits_energetiques", True),
        ("accises_tabacs", "tabacs", False),
        ("accises_alcools_boissons", "alcools_boissons", False),
        ("droits_importation_ue", "droits_de_douane", False),
        ("octroi_de_mer", "octroi_de_mer", False),
    ]
    for pid_insee, pid_douane, avec_vm in comparaisons:
        lignes = []
        for a in sorted(set(insee[pid_insee]) & set(perc.get(pid_douane, {}))):
            vi, vd = insee[pid_insee][a], perc[pid_douane][a]
            if vi is None or vd is None:
                continue
            ln = {"annee": a, "comptes_nationaux_md": vi, "percu_douane_md": round(vd / 1000, 3),
                  "ecart_md": round(vi - vd / 1000, 3)}
            if avec_vm and a in vm:
                ln["voies_et_moyens_brute_totale_md"] = vm[a]
            lignes.append(ln)
        out.append({"produit_insee": pid_insee, "poste_douane": pid_douane, "lignes": lignes})
    return out


LECTURE_ECARTS = ("Trois notions pour un même produit : le produit en comptabilité nationale (Insee, droits "
                  "constatés, toutes administrations), les sommes perçues par la douane dans l'année (bilans de la "
                  "DGDDI, encaissements de la seule douane) et, pour l'accise sur les produits énergétiques, le "
                  "produit brut des voies et moyens (comptabilité budgétaire). Les écarts viennent des dates "
                  "d'enregistrement, du périmètre de collecte (une taxe dont la perception passe à la DGFiP sort des "
                  "bilans de la douane) et des remboursements. Les montants sont montrés côte à côte, aucun n'est "
                  "retenu à la place des autres.")

RUPTURES = [
    {"annees": "2021-2022", "postes": ["tva_import", "dedouanement"],
     "constat": "TVA à l'importation : 6 875 M€ en 2021, 593 M€ en 2022 dans les bilans de la douane.",
     "lecture": "La loi de finances pour 2020 (article 181) prévoit qu'à partir du 1er janvier 2022 les entreprises "
                "assujetties déclarent la TVA à l'importation auprès de la DGFiP (autoliquidation) : le bilan de la "
                "douane ne retient plus que la part qu'elle perçoit encore.", "documents": ["douanes_bilan_2022"]},
    {"annees": "2021-2023", "postes": ["tva_petrole", "tgap", "ticgn_ticfe_tichlc", "tsvr", "dafn"],
     "constat": "Cases « * » et notes « Transfert de taxe au 1er janvier 2021 » (bilan 2022) et « Transfert de taxe "
                "entre 2021 et 2023 » (bilans 2023 et 2024).",
     "lecture": "La perception de ces taxes est transférée à la DGFiP : leur montant dans les bilans de la douane "
                "baisse ou disparaît sans que le produit de la taxe change d'autant.",
     "documents": ["douanes_bilan_2022", "douanes_bilan_2023", "douanes_bilan_2024"]},
    {"annees": "2024-2025", "postes": ["tabacs", "alcools_boissons", "contributions_indirectes"],
     "constat": "Tabacs : 14 214 M€ en 2023, 2 197,30 M€ en 2024, 85,09 M€ en 2025 ; alcools et boissons : 4 211, "
                "725,14 puis 57,99 M€. Notes de la source : « diminutions des perceptions liées au transfert des "
                "missions fiscales ».",
     "lecture": "La source attribue la baisse au transfert des missions fiscales. L'annexe 3 du PLFSS 2026 indique "
                "« DGDDI/DGFIP » comme organisme en charge du recouvrement du droit de consommation sur les tabacs et "
                "« DGDDI » pour les droits sur les alcools. Le produit de ces accises reste suivi dans produits.json "
                "(Insee), qui ne dépend pas du service qui perçoit.",
     "documents": ["douanes_bilan_2024", "douanes_bilan_2025", "douanes_plfss2026_annexe3"]},
    {"annees": "2020", "postes": ["total"],
     "constat": "Bilan 2020 : « Une baisse des recettes en 2020 est une conséquence directe de la crise sanitaire. »",
     "lecture": "Note de la source, reprise telle quelle.", "documents": ["douanes_bilan_2020"]},
    {"annees": "2016-2018", "postes": [],
     "constat": "Années absentes : le jeu ouvert de la douane s'arrête en 2015 et les bilans retenus publient à "
                "partir de 2019.",
     "lecture": "Aucune valeur n'est interpolée ; les années manquent de la liste « annees ».", "documents": []},
]


# --------------------------------------------------------------------------------------------------------------
# Production
# --------------------------------------------------------------------------------------------------------------
def _ecrire(chemin: Path, obj) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".part")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(chemin)


def _source_doc(sid: str) -> dict:
    s = SOURCES[sid]
    d = {"id": sid, "titre": s["titre"], "producteur": s["producteur"], "url": s["url"], "licence": s["licence"],
         "verdict": s["verdict"], "fichier_collecte": f"data/lake/{DOMAINE}/{s['fichier']}"}
    if s.get("page"):
        d["page"] = s["page"]
    return d


def produire(sortie: Path = SORTIE) -> None:
    verif = Verification()
    produits = lire_insee(verif)
    xls = lire_xls_2010_2015(verif)
    bilans = lire_bilans(verif)
    collecte = assembler_collecte(xls, bilans)
    collecte["destination"] = lire_destination(verif)
    affectation = lire_affectation(verif)
    verif.exiger()
    date = date_sources(DOMAINE)
    a0, a1 = produits["annees"][0], produits["annees"][-1]

    produits_json = {
        "millesime": f"{a0}-{a1} (comptes nationaux annuels, base 2020)",
        "source": SOURCES["douanes_insee_t3217"]["url"],
        "producteur": "Insee", "titre_source": produits["titre_source"],
        "unite": "milliards d'euros", "notion": "produit",
        "perimetre": "Produit de chaque impôt pour l'ensemble des administrations publiques et l'Union européenne, "
                     "quel que soit le service qui le perçoit (douane ou DGFiP).",
        "methode": "Lignes du tableau 3.217 reprises telles quelles, une valeur par année ; « N.D. » et cases vides "
                   "valent null.",
        "annees": produits["annees"], "produits": produits["produits"], "notes_source": produits["notes_source"],
        "familles": {"energie": "Énergie", "tabacs": "Tabacs", "alcools_boissons": "Alcools et boissons",
                     "douane_union_europeenne": "Droits de douane (Union européenne)", "outre_mer": "Outre-mer",
                     "environnement": "Environnement"},
        "renvoi_agregats": {"fichier": "recettes.json", "cles": ["impots.D214A", "impots.D2"],
                            "note": "Les agrégats « droits d'accise et impôts de consommation » (D214A) et « impôts "
                                    "sur la production et les importations » (D2), par administration, sont dans "
                                    "recettes.json (Eurostat) ; ce fichier ne les recopie pas."},
        "ordre": "Produits dans l'ordre des lignes du tableau de l'Insee.",
        "statut": "trace", "date_collecte": date,
    }
    collecte_json = {
        "millesime": f"{collecte['annees'][0]}-{collecte['annees'][-1]} (années publiées, voir « annees »)",
        "source": "DGDDI : " + " ; ".join(SOURCES[e["document"]]["url"] for e in collecte["editions"]),
        "producteur": "DGDDI", "unite": "millions d'euros", "notion": "percu_douane",
        "perimetre": "Sommes perçues par la douane dans l'année, tous destinataires confondus (État, collectivités, "
                     "sécurité sociale, Union européenne). Une taxe dont la perception passe à la DGFiP sort de ce "
                     "périmètre (voir « ruptures » dans index.json).",
        "methode": "2010 à 2015 : classeur ouvert de la DGDDI, lu ligne à ligne. 2019 à 2025 : tableau « Recettes "
                   "douanières en millions d'euros (détail) » des bilans annuels, montants écrits dans "
                   "pipeline/douanes_accises.py et retrouvés à leur ligne dans le PDF à chaque production. Une "
                   "case « * », « - » ou absente vaut null avec sa raison (« null_raisons »).",
        "annees": collecte["annees"], "editions": collecte["editions"], "postes": collecte["postes"],
        "calculs": collecte["calculs"], "coherence": collecte["coherence"],
        "coherence_lecture": "Total publié comparé à la somme des totaux de groupe publiés (dédouanement, énergie et "
                             "environnement, contributions indirectes, octroi de mer et activités maritimes, taxe à "
                             "l'essieu, autres taxes). Un écart non nul vient de la source (arrondis ou ligne non "
                             "détaillée) ; il est montré, aucune valeur n'est corrigée.",
        "destination": collecte["destination"], "destinataires": {k: DESTINATAIRES[k] for k in
                                                                  ("etat", "collectivites_et_organismes_sociaux",
                                                                   "union_europeenne")},
        "groupes": GROUPES,
        "ordre": "Postes dans l'ordre des bilans de la douane ; années croissantes.",
        "date_collecte": date,
    }
    affectation_json = {
        "millesime": "2018-2026 (clés de la sécurité sociale) ; exécutions 2022 à 2024 et prévisions 2025-2026 "
                     "(accise sur les produits énergétiques) ; frais de perception 2021 à 2026",
        "source": " ; ".join(SOURCES[s]["url"] for s in ("douanes_vm1_plf2024", "douanes_vm1_plf2025",
                                                         "douanes_vm1_plf2026", "douanes_plfss2026_annexe3")),
        "notion": "affecte",
        "methode": "Chaque montant ou clé est lu dans le tableau de la source et retrouvé dans le texte du document "
                   "collecté à chaque production. Les éditions successives des voies et moyens sont toutes publiées "
                   "(une prévision puis l'exécution de la même année) ; « executions » ne retient que la colonne "
                   "« Exécution » de chaque édition.",
        "destinataires": DESTINATAIRES,
        "energie": affectation["energie"], "tabacs": affectation["tabacs"], "alcools": affectation["alcools"],
        "montants_plfss": {"unite": "millions d'euros", "document": "douanes_plfss2026_annexe3",
                           "lignes": affectation["montants_plfss"],
                           "note": "Montants des prévisions 2025 et 2026 écrits dans le tableau 31 ; le montant 2025 "
                                   "du droit sur les tabacs et des droits sur les alcools sert déjà à "
                                   "prelevements/affectation.json."},
        "droits_de_douane": affectation["droits_de_douane"],
        "ordre": "Produits : énergie, tabacs, alcools, droits de douane ; années croissantes.",
        "date_collecte": date,
    }
    ecarts_lignes = ecarts(produits_json, collecte_json, affectation_json)
    index = {
        "millesime": f"{a0}-{a1}",
        "source": "Insee (comptes nationaux, tableau 3.217) ; DGDDI (données ouvertes 2010-2015, bilans annuels "
                  "2020 à 2025) ; PLF 2024 à 2026, Évaluation des voies et moyens tome I ; PLFSS 2026 annexe 3",
        "presentation": "Ce que rapportent les accises (énergie, tabacs, alcools) et les droits de douane, année "
                        "après année, ce que la douane perçoit elle-même, et à qui chaque produit est attribué. Ne "
                        "montre pas ce qu'une personne verse : le calcul personnel est ailleurs sur le site.",
        "notions": {
            "produit": "Montant d'un impôt en comptabilité nationale (Insee), quel que soit le service qui le perçoit.",
            "percu_douane": "Sommes encaissées par la douane dans l'année (bilans de la DGDDI).",
            "affecte": "Part du produit attribuée à un destinataire (État, collectivités, sécurité sociale, Union "
                       "européenne), selon la loi de finances ou de financement de la sécurité sociale.",
        },
        "fichiers": [
            {"fichier": "douanes_accises/produits.json", "contenu": "produit de chaque accise et des droits de "
                                                                    "douane, 1995 à 2025 (Insee)"},
            {"fichier": "douanes_accises/collecte.json", "contenu": "recettes perçues par la douane par poste, "
                                                                    "2010 à 2015 et 2019 à 2025, et destination des "
                                                                    "recettes 2024 et 2025 (DGDDI)"},
            {"fichier": "douanes_accises/affectation.json", "contenu": "affectation : accise sur les produits "
                                                                       "énergétiques, tabacs, alcools, droits de "
                                                                       "douane"},
        ],
        "renvois": [
            {"fichier": "recettes.json", "objet": "agrégats Eurostat par administration (D214A, D2) : non recopiés"},
            {"fichier": "prelevements/affectation.json", "objet": "ventilation 2025 de l'ex-TICPE, des tabacs et des "
                                                                  "alcools : non recopiée, citée par "
                                                                  "« deja_dans_le_site »"},
            {"fichier": "ue/contribution.json", "objet": "prélèvement sur recettes au profit de l'Union européenne "
                                                         "(qui n'inclut pas les droits de douane)"},
        ],
        "ecarts_entre_sources": ecarts_lignes, "lecture_ecart": LECTURE_ECARTS,
        "ruptures": RUPTURES,
        "chiffres_cles": {
            "percu_douane_total_m": {str(a): v for a, v in zip(collecte["annees"],
                                                               next(p["valeurs_m"] for p in collecte["postes"]
                                                                    if p["id"] == "total")) if a >= 2023},
            "accise_produits_energetiques_insee_md": {str(a): v for a, v in
                                                      zip(produits["annees"], produits["produits"][0]["valeurs_md"])
                                                      if a >= 2023},
        },
        "sources": [_source_doc(s) for s in SOURCES],
        "sources_inaccessibles": [
            {"source": "Bilans annuels de la douane 2016 à 2019 et 2021 (tableau des recettes)",
             "motif": "non retenus : les éditions 2020 et 2022 couvrent 2019 à 2022 ; 2016 à 2018 restent sans "
                      "valeur"},
            {"source": "Recettes de la douane par produit en données ouvertes après 2015",
             "motif": "non publiées en données ouvertes à la date de la collecte (constat du 18/11/2026)"},
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "confidentialite": "Agrégats nationaux publiés par l'administration : aucune personne, aucune entreprise.",
        "limites": [
            "Les bilans de la douane ne publient pas la destination par produit : seule la répartition d'ensemble "
            "2024 et 2025 est donnée (« destination » de collecte.json).",
            "L'affectation des accises sur l'électricité et le gaz et de l'octroi de mer n'est pas détaillée ici.",
            "La répartition de l'ex-TICPE entre régions et départements n'est pas publiée dans les voies et moyens.",
            "Les montants des bilans sont lus dans des PDF : la production s'arrête si une valeur n'est plus "
            "retrouvée à sa ligne.",
        ],
        "verification_documents": verif.bilan(),
        "ordre": "Fichiers, renvois et sources dans l'ordre de lecture ; écarts par produit dans l'ordre du "
                 "tableau de l'Insee.",
        "date_collecte": date,
    }
    for nom, obj in (("index.json", index), ("produits.json", produits_json), ("collecte.json", collecte_json),
                     ("affectation.json", affectation_json)):
        _ecrire(sortie / nom, obj)
        print(f"  {sortie / nom}")


def collecter() -> int:
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *SOURCES])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
