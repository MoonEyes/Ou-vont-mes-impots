"""Assurance maladie : dépenses remboursées par grand poste de soins, montants par département, exécution de l'ONDAM.

Trois vues, jamais additionnées entre elles (champs différents, écarts publiés) :
  1. dépenses remboursées par l'ensemble des régimes d'assurance maladie, par grand poste de soins (soins de ville :
     médecins, médicaments, infirmiers... ; hospitalisations ; prestations en espèces : indemnités journalières,
     invalidité...), France entière, 2015 à 2024 (Cnam, cartographie des pathologies et des dépenses, data.ameli.fr) ;
  2. par département et par année, 2010 à 2025 : montants des prescriptions des médecins libéraux par poste
     (médicaments, indemnités journalières, biologie, transports...) et honoraires des professionnels libéraux
     (médecins, chirurgiens-dentistes, auxiliaires médicaux, sages-femmes), sans et avec dépassements
     (Cnam, data.ameli.fr, statistiques publiques labellisées) ;
  3. exécution de l'objectif national de dépenses d'assurance maladie (ONDAM) par sous-objectif : objectif voté,
     objectif rectifié, constat (annexe 3 des projets de loi d'approbation des comptes de la sécurité sociale 2024 et
     2025). Le détail de l'ONDAM constaté 2024 dans l'arbre de la sécurité sociale reste dans `secu/` (renvoi).

Entrées (data/lake, collectées par collecte/collecte.py, identifiants de collecte/catalogue.json) :
    secu_ameli_depenses            data/lake/secu/secu_ameli_depenses.parquet (jeu « depenses », entier)
    amt_ameli_prescriptions        data/lake/assurance_maladie_territoires/amt_ameli_prescriptions.parquet
    amt_ameli_honoraires           data/lake/assurance_maladie_territoires/amt_ameli_honoraires.parquet
    secu_placss2024_annexe3        data/lake/secu/secu_placss2024_annexe3.pdf
    secu_placss2025_annexe3        data/lake/secu/secu_placss2025_annexe3.pdf
Sorties (site/data/assurance_maladie_territoires/, schémas docs/schemas/assurance_maladie_territoires_*.schema.json) :
    index.json          présentation, totaux nationaux, ONDAM résumé, écarts entre champs, liens, méthode, sources
    postes.json         dépenses remboursées par grand poste et sous-poste, France entière, par année
    departements.json   prescriptions par poste et honoraires par profession, par département et par année
    ondam.json          ONDAM par sous-objectif : objectif voté, rectifié, constaté, écarts publiés

Commandes :
    python pipeline/assurance_maladie_territoires.py collecter   # réseau : collecte/collecte.py (contrôle d'intégrité
                                                                 # collecte/integrite.py), 401/403/429 notés
    python pipeline/assurance_maladie_territoires.py produire    # sans réseau
    python pipeline/assurance_maladie_territoires.py             # les deux

Règles :
  - agrégats seulement : aucune donnée de patient ni de professionnel nommé ; la Cnam masque (« NS ») tout montant
    calculé sur moins de 5 professionnels, ce masque reste null, jamais 0 ;
  - Open Damir (remboursements mensuels détaillés, plusieurs centaines de Mo par mois, ventilés par région et non par
    département) n'est pas téléchargé : les agrégats publiés par la Cnam suffisent (voir `recherche_publique`) ;
  - un montant de l'ONDAM est lu dans le texte du document (pdftotext) à chaque production : si le tableau a changé,
    la production échoue au lieu de publier un chiffre périmé ;
  - toute date écrite vient de pipeline/reproductible.py ; ordres explicites : deux productions sur le même
    entrepôt sont identiques octet pour octet.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
AXE = "assurance_maladie_territoires"
SORTIE = SITE / AXE
MANIFESTE = LAKE / "manifest.json"
MAX_OCTETS = 1_000_000

COLLECTABLES = ("secu_ameli_depenses", "amt_ameli_prescriptions", "amt_ameli_honoraires",
                "secu_placss2024_annexe3", "secu_placss2025_annexe3")

AMELI = "https://data.ameli.fr/explore/dataset"
SOURCES = {
    "secu_ameli_depenses": {
        "fichier": "secu/secu_ameli_depenses.parquet",
        "url": f"{AMELI}/depenses/",
        "titre": "Pathologies : dépenses remboursées affectées à chaque pathologie (cartographie des pathologies et "
                 "des dépenses de l'Assurance maladie), ligne « Total consommants tous régimes »",
        "producteur": "Caisse nationale de l'assurance maladie (Cnam), à partir du système national des données de "
                      "santé (SNDS)",
        "millesime": "2015 à 2024 (version de juillet 2026)",
        "licence": "ODbL (Open Database License)", "verdict": "réutilisable tel quel",
    },
    "amt_ameli_prescriptions": {
        "fichier": f"{AXE}/amt_ameli_prescriptions.parquet",
        "url": f"{AMELI}/prescriptions/",
        "titre": "Professionnels de santé libéraux : montants des prescriptions par poste et par territoire "
                 "(département, région), ensemble des médecins libéraux",
        "producteur": "Cnam (SNDS), statistique publique labellisée par l'Autorité de la statistique publique",
        "millesime": "2010 à 2025 (mise à jour d'octobre 2026)",
        "licence": "ODbL (Open Database License)", "verdict": "réutilisable tel quel",
    },
    "amt_ameli_honoraires": {
        "fichier": f"{AXE}/amt_ameli_honoraires.parquet",
        "url": f"{AMELI}/honoraires/",
        "titre": "Professionnels de santé libéraux : montants des honoraires par territoire (département, région)",
        "producteur": "Cnam (SNDS), statistique publique labellisée par l'Autorité de la statistique publique",
        "millesime": "2010 à 2025 (mise à jour d'octobre 2026)",
        "licence": "ODbL (Open Database License)", "verdict": "réutilisable tel quel",
    },
    "secu_placss2024_annexe3": {
        "fichier": "secu/secu_placss2024_annexe3.pdf",
        "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/922636/file/PLACSS2024-Annexe3.pdf",
        "titre": "Projet de loi d'approbation des comptes de la sécurité sociale 2024, annexe 3 « ONDAM et dépenses "
                 "de santé » (texte des pages 7 à 9 ; les tableaux de cette annexe sont publiés en image)",
        "producteur": "Direction de la sécurité sociale (DSS)",
        "millesime": "Exécution 2024 (constat de mars 2025)",
        "licence": "document administratif public (CRPA L. 321-1)", "verdict": "réutilisable tel quel",
    },
    "secu_placss2025_annexe3": {
        "fichier": "secu/secu_placss2025_annexe3.pdf",
        "url": "https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1112982/file/PLACSS2025-Annexe%203.pdf",
        "titre": "Projet de loi d'approbation des comptes de la sécurité sociale 2025, annexe 3 « ONDAM et dépenses "
                 "de santé », tableau 3 (réalisations 2024) et tableau 5 (premier constat 2025)",
        "producteur": "Direction de la sécurité sociale (DSS)",
        "millesime": "Exécution 2025 (constat de mars 2026)",
        "licence": "document administratif public (CRPA L. 321-1)", "verdict": "réutilisable tel quel",
    },
}

SOURCES_INACCESSIBLES = [
    {"nom": "Serveur de téléchargement open-data-assurance-maladie.ameli.fr (pages d'index)",
     "url": "https://open-data-assurance-maladie.ameli.fr/depenses/",
     "motif": "page de vérification de sécurité (HTTP 403) sur la racine du serveur, non contournée ; les fichiers "
              "mensuels restent listés par download.php mais ne sont pas nécessaires ici (agrégats publiés suffisants)"},
    {"nom": "Tableaux 3 à 6 de l'annexe 3 du PLACSS 2024 (ONDAM 2023 et 2024 par sous-objectif)",
     "url": SOURCES["secu_placss2024_annexe3"]["url"],
     "motif": "tableaux publiés en image ; une reconnaissance de caractères donne des nombres ambigus (virgules "
              "perdues) : seuls les totaux écrits dans le texte sont repris pour 2023 et 2024"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "requetes": ["data.ameli.fr : catalogue complet (51 jeux), jeux « depenses », « prescriptions », « honoraires », "
                 "« honoraires-detailles »",
                 "data.gouv.fr : jeux de la Cnam (Open Damir, données nationales soins de ville, données par CPAM des "
                 "établissements de santé privés, Open Medic, Open Bio, Open LPP)",
                 "web : « ONDAM réalisé par sous-objectif série », « Open Damir agrégé par département »",
                 "GitHub et sites de chercheurs : « open damir », « ondam », « cartographie des pathologies »"],
    "conclusion": "La Cnam publie elle-même les agrégats utiles (dépenses remboursées par poste, prescriptions et "
                  "honoraires par département) : ils sont repris tels quels. L'exécution de l'ONDAM par "
                  "sous-objectif n'existe pas en jeu ouvert : elle est lue dans l'annexe 3 du projet de loi "
                  "d'approbation des comptes. Aucun dépôt public ne rapproche ces vues : module écrit pour le dépôt, "
                  "sur le modèle de pipeline/solidarites_departements.py.",
    "trouvailles": [
        {"nom": "Cnam, Pathologies : dépenses remboursées affectées à chaque pathologie",
         "url": f"{AMELI}/depenses/", "licence": "ODbL", "mise_a_jour": "2026-07-06",
         "verdict": "réutilisable tel quel"},
        {"nom": "Cnam, Professionnels de santé libéraux : montants des prescriptions par poste et par territoire",
         "url": f"{AMELI}/prescriptions/", "licence": "ODbL", "mise_a_jour": "2026-10-28",
         "verdict": "réutilisable tel quel"},
        {"nom": "Cnam, Professionnels de santé libéraux : montants des honoraires par territoire",
         "url": f"{AMELI}/honoraires/", "licence": "ODbL", "mise_a_jour": "2026-10-28",
         "verdict": "réutilisable tel quel"},
        {"nom": "Cnam, Open Damir : base complète sur les dépenses d'assurance maladie interrégimes",
         "url": "https://www.data.gouv.fr/datasets/open-damir-base-complete-sur-les-depenses-dassurance-maladie-"
                "interregimes/",
         "licence": "Licence Ouverte", "mise_a_jour": "2026-11-18",
         "verdict": "inspiration seulement (fichiers mensuels de plusieurs centaines de Mo, région et non département)"},
        {"nom": "Cnam, Données nationales sur les dépenses d'assurance maladie relatives aux soins de ville "
                "(régime général, mensuel)",
         "url": "https://www.data.gouv.fr/datasets/donnees-nationales-sur-les-depenses-dassurance-maladie-relatives-"
                "aux-soins-de-ville/",
         "licence": "Licence Ouverte", "mise_a_jour": "2026-11-18",
         "verdict": "à adapter (régime général seul, sans département ; non repris)"},
        {"nom": "Cnam, Données par CPAM sur les dépenses relatives aux établissements de santé privés",
         "url": "https://www.data.gouv.fr/datasets/donnees-par-cpam-sur-les-depenses-dassurance-maladie-relatives-aux-"
                "etablissements-de-sante-prives/",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-11-18",
         "verdict": "à adapter (cliniques privées seulement, régime général ; non repris dans cette version)"},
        {"nom": "François Geerolf, pages d'analyse des données de la Cnam (fgeerolf.com/data/cnam)",
         "url": "https://fgeerolf.com/data/cnam/", "licence": "non précisée", "mise_a_jour": "2026",
         "verdict": "inspiration seulement"},
        {"nom": "pipeline/secu.py (ce dépôt) : ONDAM constaté 2024 dans l'arbre des branches",
         "url": "pipeline/secu.py", "licence": "celle du dépôt", "mise_a_jour": "2026-11-18",
         "verdict": "réutilisé par renvoi (secu/), sans recopie"},
    ],
}

# --- lecture -------------------------------------------------------------------------------------------------------

NON_PUBLIE = {"NS": "secret statistique (moins de 5 professionnels)", "NC": "non calculé par la source"}


def montant(v) -> int | None:
    """Montant en euros publié par la Cnam ; « NS », « NC », vide : None (jamais 0)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return None
    return int(round(float(s)))


def annee(v) -> int:
    return int(str(v)[:4]) if not hasattr(v, "year") else int(v.year)


def md(s: str) -> float:
    """« 113,2 » -> 113.2 ; « -0,5 » -> -0.5."""
    return float(s.replace("−", "-").replace(",", "."))


def pct(s: str) -> float:
    return md(s.rstrip("%"))


def lire_parquet(rel: str) -> list[dict]:
    import pyarrow.parquet as pq
    chemin = LAKE / rel
    if not chemin.exists():
        raise FileNotFoundError(f"{chemin} absent : lancer `python pipeline/{AXE}.py collecter`")
    return pq.read_table(chemin).to_pylist()


def texte_pdf(rel: str) -> str:
    chemin = LAKE / rel
    if not chemin.exists():
        raise FileNotFoundError(f"{chemin} absent : lancer `python pipeline/{AXE}.py collecter`")
    r = subprocess.run(["pdftotext", "-layout", str(chemin), "-"], capture_output=True, text=True, check=True)
    return r.stdout


def collecte_le(sid: str) -> str | None:
    try:
        e = json.loads(MANIFESTE.read_text(encoding="utf-8")).get(sid) or {}
    except (OSError, ValueError):
        return None
    c = e.get("collecte_le")
    return str(c)[:10] if c else None


# --- 1. postes nationaux -------------------------------------------------------------------------------------------

GRANDS_POSTES = [  # (id, libellé de la source au niveau 1, libellé du site)
    ("soins_de_ville", "Soins de ville", "Soins de ville (médecins, médicaments, infirmiers, kinésithérapie, "
                                          "biologie, transports...)"),
    ("hospitalisations", "Hospitalisations (tous secteurs)", "Hospitalisations (hôpitaux publics et cliniques "
                                                              "privées)"),
    ("prestations_en_especes", "Prestations en espèces", "Prestations en espèces (indemnités journalières, "
                                                          "invalidité, rentes d'accident du travail)"),
]
TOTAL_NIV1 = "Dépenses"
# Libellés du site pour les sous-postes de la source (sans sigle seul) ; un libellé inconnu arrête la production.
LIBELLES_SOUS_POSTES = {
    "Autres dépenses de soins de ville remboursés": "Autres soins de ville",
    "Autres produits de santé remboursés": "Autres produits de santé (dispositifs médicaux, pansements, appareillage...)",
    "Biologie remboursée": "Biologie (analyses de laboratoire)",
    "Médicaments remboursés": "Médicaments",
    "Soins autres spécialistes remboursés": "Soins de médecins spécialistes",
    "Soins d'autres paramédicaux remboursés": "Soins d'autres paramédicaux (orthophonistes, orthoptistes, "
                                              "pédicures-podologues)",
    "Soins de généralistes remboursés": "Soins de médecins généralistes",
    "Soins de kinésithérapie remboursés": "Kinésithérapie",
    "Soins de sages-femmes remboursés": "Soins de sages-femmes",
    "Soins dentaires remboursés": "Soins dentaires",
    "Soins infirmiers remboursés": "Soins infirmiers",
    "Transports remboursés": "Transports de malades",
    "Actes et consultations externes MCO secteur public remboursés": "Consultations et actes externes à l'hôpital "
                                                                     "public",
    "Hospitalisations en HAD secteur privé remboursées": "Hospitalisation à domicile, secteur privé",
    "Hospitalisations en HAD secteur public remboursées": "Hospitalisation à domicile, secteur public",
    "Hospitalisations en SSR secteur privé remboursées": "Soins de suite et de réadaptation, secteur privé",
    "Hospitalisations en SSR secteur public remboursées": "Soins de suite et de réadaptation, secteur public",
    "Hospitalisations en psychiatrie secteur privé remboursées": "Psychiatrie, secteur privé",
    "Hospitalisations en psychiatrie secteur public remboursées": "Psychiatrie, secteur public",
    "Hospitalisations liste en sus MCO secteur privé remboursées": "Médicaments et dispositifs facturés en "
                                                                   "plus du séjour (médecine, chirurgie, "
                                                                   "obstétrique), secteur privé",
    "Hospitalisations liste en sus MCO secteur public remboursées": "Médicaments et dispositifs facturés en "
                                                                    "plus du séjour (médecine, chirurgie, "
                                                                    "obstétrique), secteur public",
    "Hospitalisations séjour MCO secteur privé remboursées": "Séjours en médecine, chirurgie, obstétrique, secteur "
                                                             "privé",
    "Hospitalisations séjour MCO secteur public remboursées": "Séjours en médecine, chirurgie, obstétrique, secteur "
                                                              "public",
    "Indemnités journalières maladie et AT/MP remboursées": "Indemnités journalières maladie, accidents du travail "
                                                            "et maladies professionnelles",
    "Indemnités journalières maternité et autres prestations remboursées": "Indemnités journalières maternité et "
                                                                           "autres prestations",
    "Prestations d'invalidité remboursées": "Pensions d'invalidité",
    "Rentes de victimes ATMP remboursées": "Rentes des victimes d'accidents du travail et de maladies "
                                           "professionnelles",
}


def sous_poste_id(libelle: str) -> str:
    s = libelle.lower()
    for a, b in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("ô", "o"), ("ç", "c"), ("'", " "), ("/", " ")):
        s = s.replace(a, b)
    s = re.sub(r"\b(rembourse(e|es|s)?)\b", "", s)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def lire_postes(lignes: list[dict]) -> dict:
    tot = [r for r in lignes if r.get("patho_niv1") == "Total consommants tous régimes"]
    if not tot:
        raise SystemExit("ligne « Total consommants tous régimes » absente du jeu depenses : la source a changé")
    annees = sorted({annee(r["annee"]) for r in tot})
    val: dict[tuple, int | None] = {}
    libelles: dict[tuple, tuple] = {}
    for r in tot:
        cle = (r["dep_niv_1"], r["dep_niv_2"])
        val[cle + (annee(r["annee"]),)] = montant(r["montant"])
        libelles[cle] = (r.get("type_somme"), r.get("tri"))
    connus = {g[1] for g in GRANDS_POSTES} | {TOTAL_NIV1}
    inconnus = sorted({k[0] for k in libelles} - connus)
    if inconnus:
        raise SystemExit(f"postes de niveau 1 inconnus dans la source : {inconnus}")
    postes = []
    total_lib = [k for k in libelles if k[0] == TOTAL_NIV1]
    if len(total_lib) != 1:
        raise SystemExit("total général des dépenses remboursées introuvable ou ambigu")
    postes.append({"id": "total", "niveau": 0, "parent": None, "libelle": "Total des dépenses remboursées",
                   "libelle_source": total_lib[0][1],
                   "montants_eur": [val.get(total_lib[0] + (a,)) for a in annees]})
    for gid, niv1, lib in GRANDS_POSTES:
        cles = sorted((k for k in libelles if k[0] == niv1), key=lambda k: k[1])
        totaux = [k for k in cles if libelles[k][0] == "Total"]
        if len(totaux) != 1:
            raise SystemExit(f"total du poste « {niv1} » introuvable ou ambigu")
        postes.append({"id": gid, "niveau": 1, "parent": "total", "libelle": lib, "libelle_source": totaux[0][1],
                       "montants_eur": [val.get(totaux[0] + (a,)) for a in annees]})
        for k in cles:
            if libelles[k][0] == "Total":
                continue
            if k[1] not in LIBELLES_SOUS_POSTES:
                raise SystemExit(f"sous-poste nouveau dans la source, libellé à écrire : {k[1]}")
            postes.append({"id": f"{gid}.{sous_poste_id(k[1])}", "niveau": 2, "parent": gid,
                           "libelle": LIBELLES_SOUS_POSTES[k[1]], "libelle_source": k[1],
                           "montants_eur": [val.get(k + (a,)) for a in annees]})
    ids = [p["id"] for p in postes]
    if len(ids) != len(set(ids)):
        raise SystemExit("identifiants de sous-postes en double")
    # contrôle : la somme des sous-postes publiés est égale au total publié du poste (à l'euro près, arrondis)
    controles = []
    for gid, _, _ in GRANDS_POSTES:
        p = next(x for x in postes if x["id"] == gid)
        enfants = [x for x in postes if x["parent"] == gid]
        for i, a in enumerate(annees):
            vals = [e["montants_eur"][i] for e in enfants]
            if p["montants_eur"][i] is None or any(v is None for v in vals):
                continue
            ecart = p["montants_eur"][i] - sum(vals)
            controles.append({"poste": gid, "annee": a, "ecart_eur": ecart})
            if abs(ecart) > max(1000, abs(p["montants_eur"][i]) * 1e-6):
                raise SystemExit(f"sous-postes de {gid} {a} : somme différente du total publié ({ecart} €)")
    return {"annees": annees, "postes": postes, "controles": controles}


# --- 2. départements -----------------------------------------------------------------------------------------------

POSTES_PRESCRIPTION = [  # (code source, id, libellé du site)
    ("total", "total", "Ensemble des prescriptions"),
    ("1", "medicaments", "Médicaments"),
    ("2", "dispositifs_medicaux", "Dispositifs médicaux (liste des produits et prestations)"),
    ("3", "biologie", "Biologie (analyses)"),
    ("4", "soins_infirmiers", "Soins infirmiers"),
    ("5", "kinesitherapie", "Kinésithérapie"),
    ("6", "transports", "Transports de malades"),
    ("7", "indemnites_journalieres", "Indemnités journalières (arrêts de travail)"),
    ("8", "autres", "Autres (pédicurie, orthophonie, orthoptie, vaccination, cures thermales...)"),
]
PROFESSIONS = [  # (libellé source, id, libellé du site)
    ("Ensemble des médecins", "medecins", "Médecins"),
    ("Ensemble des chirurgiens-dentistes", "chirurgiens_dentistes", "Chirurgiens-dentistes"),
    ("Ensemble des auxiliaires médicaux", "auxiliaires_medicaux",
     "Auxiliaires médicaux (infirmiers, kinésithérapeutes, orthophonistes, orthoptistes, pédicures-podologues)"),
    ("Sages-femmes", "sages_femmes", "Sages-femmes"),
]
FRANCE = ("999", "99")  # code département, code région de la ligne France entière


def est_departement(code: str) -> bool:
    return bool(re.fullmatch(r"(0[1-9]|1\d|2[1-9]|[3-8]\d|9[0-5]|2A|2B|97[1-46])", code or ""))


def lire_departements(prescriptions: list[dict], honoraires: list[dict]) -> dict:
    annees = sorted({annee(r["annee"]) for r in prescriptions} | {annee(r["annee"]) for r in honoraires})
    idx = {a: i for i, a in enumerate(annees)}
    code_poste = {c: i for c, i, _ in POSTES_PRESCRIPTION}
    code_prof = {c: i for c, i, _ in PROFESSIONS}
    deps: dict[str, dict] = {}
    france = {"prescriptions": {i: [None] * len(annees) for _, i, _ in POSTES_PRESCRIPTION},
              "honoraires": {i: {"sans_depassement": [None] * len(annees), "depassements": [None] * len(annees)}
                             for _, i, _ in PROFESSIONS}}
    masques = {"prescriptions": 0, "honoraires": 0}

    def fiche(r) -> dict | None:
        code = str(r["departement"])
        if code == FRANCE[0]:
            return france if str(r["region"]) == FRANCE[1] else None  # « Tout département » d'une région : ignoré
        if not est_departement(code):
            raise SystemExit(f"code de département inattendu : {code}")
        if code not in deps:
            deps[code] = {"nom": r["libelle_departement"], "region": str(r["region"]),
                          "region_nom": r["libelle_region"],
                          "prescriptions": {i: [None] * len(annees) for _, i, _ in POSTES_PRESCRIPTION},
                          "honoraires": {i: {"sans_depassement": [None] * len(annees),
                                             "depassements": [None] * len(annees)} for _, i, _ in PROFESSIONS}}
        return deps[code]

    for r in prescriptions:
        f = fiche(r)
        if f is None:
            continue
        p = code_poste.get(str(r["poste_prescription"]))
        if p is None:
            raise SystemExit(f"poste de prescription inconnu : {r['poste_prescription']} {r['libelle_poste_prescription']}")
        v = montant(r["montant_total_prescription"])
        masques["prescriptions"] += v is None
        f["prescriptions"][p][idx[annee(r["annee"])]] = v
    for r in honoraires:
        f = fiche(r)
        if f is None:
            continue
        p = code_prof.get(r["profession_sante"])
        if p is None:
            raise SystemExit(f"profession inattendue : {r['profession_sante']}")
        i = idx[annee(r["annee"])]
        for col, cle in (("hono_sans_depassement_totaux", "sans_depassement"), ("depassements_totaux", "depassements")):
            v = montant(r[col])
            masques["honoraires"] += v is None
            f["honoraires"][p][cle][i] = v
    if len(deps) < 100:
        raise SystemExit(f"{len(deps)} départements lus seulement")
    # contrôle publié : somme des départements face à la ligne France entière (jamais substituée)
    ecarts = []
    for _, pid, _ in POSTES_PRESCRIPTION:
        for a in annees:
            i = idx[a]
            vals = [d["prescriptions"][pid][i] for d in deps.values()]
            fr = france["prescriptions"][pid][i]
            if fr is None or not any(v is not None for v in vals):
                continue
            s = sum(v for v in vals if v is not None)
            ecarts.append({"grandeur": f"prescriptions.{pid}", "annee": a, "france_eur": fr,
                           "somme_departements_eur": s, "ecart_eur": fr - s,
                           "departements_masques": sum(v is None for v in vals)})
    for _, pid, _ in PROFESSIONS:
        for cle in ("sans_depassement", "depassements"):
            for a in annees:
                i = idx[a]
                vals = [d["honoraires"][pid][cle][i] for d in deps.values()]
                fr = france["honoraires"][pid][cle][i]
                if fr is None or not any(v is not None for v in vals):
                    continue
                s = sum(v for v in vals if v is not None)
                ecarts.append({"grandeur": f"honoraires.{pid}.{cle}", "annee": a, "france_eur": fr,
                               "somme_departements_eur": s, "ecart_eur": fr - s,
                               "departements_masques": sum(v is None for v in vals)})
    return {"annees": annees, "departements": dict(sorted(deps.items(), key=lambda kv: cle_dep(kv[0]))),
            "france": france, "masques": masques, "ecarts": ecarts}


def cle_dep(code: str) -> tuple:
    """Ordre usuel : 01..19, 2A, 2B, 21..95, 971..976."""
    if code in ("2A", "2B"):
        return (20, code)
    return (int(code), "")


# --- 3. ONDAM ------------------------------------------------------------------------------------------------------

SOUS_OBJECTIFS = [  # (id, libellé du site, niveau, parent)
    ("total", "ONDAM total", 0, None),
    ("soins_de_ville", "Soins de ville", 1, "total"),
    ("etablissements_sante", "Établissements de santé (hôpitaux, cliniques)", 1, "total"),
    ("medico_social", "Établissements et services médico-sociaux", 1, "total"),
    ("medico_social_personnes_agees", "dont personnes âgées (Ehpad, services à domicile...)", 2, "medico_social"),
    ("medico_social_handicap", "dont personnes en situation de handicap", 2, "medico_social"),
    ("fir_sni", "Fonds d'intervention régional et soutien national à l'investissement", 1, "total"),
    ("autres", "Autres prises en charge (soins des Français à l'étranger, dotations à des agences...)", 1, "total"),
]

N = r"(-?\d+,\d)"
P = r"(-?\d+,\d%)"
# Tableau 5 de l'annexe 3 du PLACSS 2025 : objectif LFSS 2025, objectif rectifié LFSS 2026, constat 2025, taux,
# écart à l'objectif initial, écart à l'objectif rectifié.
MOTIFS_T5 = {
    "total": rf"ONDAM TOTAL\s+{N}\s+{N}\s+{N}\s+{P}\s+{N}\s+{N}",
    "soins_de_ville": rf"Soins de ville\s+{N}\s+{N}\s+{N}\s+{P}\s+{N}\s+{N}",
    "etablissements_sante": rf"Etablissements de santé\s+{N}\s+{N}\s+{N}\s+{P}\s+{N}\s+{N}",
    "medico_social": rf"Etablissements et services médico-sociaux\s+{N}\s+{N}\s+{N}\s+{P}\s+{N}\s+{N}",
    "medico_social_personnes_agees": rf"services pour\s+{N}\s+{N}\s+{N}\s+{P}\s+{N}\s+{N}\s*\n\s*personnes âgées",
    "medico_social_handicap": rf"services\s+{N}\s+{N}\s+{N}\s+{P}\s+{N}\s+{N}\s*\n\s*pour personnes handicapées",
    "fir_sni": rf"Fonds d'intervention régional et\s+{N}\s+{N}\s+{N}\s+{P}\s+{N}\s+{N}",
    "autres": rf"Autres prises en charges\s+{N}\s+{N}\s+{N}\s+{P}\s+{N}\s+{N}",
}
# Tableau 3 : base 2024 (mars 2026), constaté 2024 en mars 2025, constaté 2024 en mars 2026, écart, évolution.
MOTIFS_T3 = {
    "total": rf"ONDAM Total\s+{N}\s+{N}\s+{N}\s+{N}\s+{P}",
    "soins_de_ville": rf"Soins de ville\s+{N}\s+{N}\s+{N}\s+{N}\s+{P}",
    "etablissements_sante": rf"Établissements de santé\s+{N}\s+{N}\s+{N}\s+{N}\s+{P}",
    "medico_social": rf"Etablissements et services médico-sociaux\s+{N}\s+{N}\s+{N}\s+{N}\s+{P}",
    "medico_social_personnes_agees": rf"Établissements médico-sociaux\s*\n\s+{N}\s+{N}\s+{N}\s+{N}\s+{P}\s*\n\s*"
                                     r"Personnes âgées",
    "medico_social_handicap": rf"Établissements médico-sociaux\s*\n\s+{N}\s+{N}\s+{N}\s+{N}\s+{P}\s*\n\s*"
                              r"Personnes handicapées",
    "fir_sni": rf"FIR et SNI\s+{N}\s+{N}\s+{N}\s+{N}\s+{P}",
    "autres": rf"Autres prises en charge\s+{N}\s+{N}\s+{N}\s+{N}\s+{P}",
}
# Totaux écrits dans le texte de l'annexe 3 du PLACSS 2024 (les tableaux y sont des images).
PHRASES_2024 = {
    "objectif_2024_lfss2024": (r"l’ONDAM pour 2024 ont été fixées à (\d+,\d) Md€ dans la LFSS 2024", "p. 8"),
    "objectif_2024_rectifie_lfss2025": (r"L’ONDAM 2024 rectifié en LFSS 2025 s’établit à (\d+,\d) Md€", "p. 8"),
    "constat_2024_mars2025": (r"niveau dépenses au périmètre de\s+l’ONDAM à (\d+,\d) Md€", "p. 9"),
    "constat_2023_mars2025": (r"L’ONDAM 2023 s’établit à (\d+,\d) Md€", "p. 7"),
}


def bloc(texte: str, debut: str, fin: str = "Source") -> str:
    i = texte.find(debut)
    if i < 0:
        raise SystemExit(f"« {debut} » introuvable dans le document : la source a changé")
    j = texte.find(fin, i + len(debut))
    return texte[i: j if j > 0 else None]


def lire_ondam(t2025: str, t2024: str) -> dict:
    t5 = bloc(t2025, "Tableau 5 ● Premier constat de l’ONDAM 2025")
    t3 = bloc(t2025, "Tableau 3 – Réalisations dans le champ de l’ONDAM en 2024")
    lignes = []
    for sid, lib, niv, parent in SOUS_OBJECTIFS:
        m5 = re.search(MOTIFS_T5[sid], t5)
        m3 = list(re.finditer(MOTIFS_T3[sid], t3))
        if not m5:
            raise SystemExit(f"ONDAM 2025, ligne {sid} introuvable dans le tableau 5 (PLACSS 2025, annexe 3)")
        if sid in ("medico_social_personnes_agees", "medico_social_handicap"):
            m3 = [m for m in m3 if (("âgées" in m.group(0)) == (sid == "medico_social_personnes_agees"))]
        if len(m3) != 1:
            raise SystemExit(f"ONDAM 2024, ligne {sid} introuvable ou ambiguë dans le tableau 3 (PLACSS 2025, annexe 3)")
        g5, g3 = m5.groups(), m3[0].groups()
        lignes.append({
            "id": sid, "libelle": lib, "niveau": niv, "parent": parent,
            "annees": {
                "2025": {"objectif_initial_md": md(g5[0]), "objectif_rectifie_md": md(g5[1]), "constat_md": md(g5[2]),
                         "evolution_pct": pct(g5[3]), "ecart_objectif_initial_md": md(g5[4]),
                         "ecart_objectif_rectifie_md": md(g5[5]), "source": "secu_placss2025_annexe3",
                         "reference": "PLACSS 2025, annexe 3, tableau 5 (p. 9)"},
                "2024": {"objectif_initial_md": None, "objectif_rectifie_md": None,
                         "constat_md": md(g3[2]), "constat_precedent_md": md(g3[1]),
                         "revision_constat_md": md(g3[3]), "evolution_pct": pct(g3[4]),
                         "source": "secu_placss2025_annexe3",
                         "reference": "PLACSS 2025, annexe 3, tableau 3 (p. 7) : constaté en mars 2026 "
                                      "(constat_md) et en mars 2025 (constat_precedent_md)"},
            },
        })
    # totaux 2023-2024 écrits dans le texte du PLACSS 2024
    lus = {}
    for cle, (motif, page) in PHRASES_2024.items():
        m = re.search(motif, t2024)
        if not m:
            raise SystemExit(f"phrase « {cle} » introuvable dans l'annexe 3 du PLACSS 2024 : la source a changé")
        lus[cle] = (md(m.group(1)), page)
    tot = lignes[0]["annees"]
    tot["2024"]["objectif_initial_md"] = lus["objectif_2024_lfss2024"][0]
    tot["2024"]["objectif_rectifie_md"] = lus["objectif_2024_rectifie_lfss2025"][0]
    tot["2024"]["reference_objectifs"] = ("PLACSS 2024, annexe 3, texte p. 8 (objectif voté en LFSS 2024, y compris "
                                          "provision pour la crise sanitaire, et objectif rectifié en LFSS 2025)")
    if abs(lus["constat_2024_mars2025"][0] - tot["2024"]["constat_precedent_md"]) > 0.05:
        raise SystemExit("constat 2024 de mars 2025 différent entre le PLACSS 2024 et le PLACSS 2025")
    tot["2023"] = {"objectif_initial_md": None, "objectif_rectifie_md": None,
                   "constat_md": lus["constat_2023_mars2025"][0], "source": "secu_placss2024_annexe3",
                   "reference": "PLACSS 2024, annexe 3, texte p. 7 (constat de mars 2025)"}
    # contrôle : somme des sous-objectifs de niveau 1 = total publié (arrondis à 0,1 Md€ près)
    controles = []
    for a in ("2025", "2024"):
        for cle in ("constat_md",) + (("objectif_initial_md", "objectif_rectifie_md") if a == "2025" else ()):
            s = round(sum(l["annees"][a][cle] for l in lignes if l["niveau"] == 1), 1)
            e = round(tot[a][cle] - s, 1)
            controles.append({"annee": int(a), "grandeur": cle, "total_publie_md": tot[a][cle],
                              "somme_sous_objectifs_md": s, "ecart_arrondi_md": e})
            if abs(e) > 0.35:
                raise SystemExit(f"ONDAM {a} {cle} : somme des sous-objectifs éloignée du total publié ({e})")
    return {"lignes": lignes, "controles": controles}


# --- production ----------------------------------------------------------------------------------------------------

def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets ({n}) : découper")
    tmp = path.with_suffix(".part")
    tmp.write_text(texte + "\n", encoding="utf-8")
    tmp.replace(path)
    return n


def sources_de(cles) -> dict:
    out = {}
    for k in cles:
        s = dict(SOURCES[k])
        s["entrepot"] = "data/lake/" + s.pop("fichier")
        s["collecte_le"] = collecte_le(k)
        out[k] = s
    return out


def produire(sortie: Path = SORTIE) -> dict:
    date = date_sources(AXE, "secu")
    postes = lire_postes(lire_parquet(SOURCES["secu_ameli_depenses"]["fichier"]))
    dep = lire_departements(lire_parquet(SOURCES["amt_ameli_prescriptions"]["fichier"]),
                            lire_parquet(SOURCES["amt_ameli_honoraires"]["fichier"]))
    ondam = lire_ondam(texte_pdf(SOURCES["secu_placss2025_annexe3"]["fichier"]),
                       texte_pdf(SOURCES["secu_placss2024_annexe3"]["fichier"]))

    a_post, a_dep = postes["annees"], dep["annees"]
    src_postes = SOURCES["secu_ameli_depenses"]["url"]
    src_dep = f"{SOURCES['amt_ameli_prescriptions']['url']} ; {SOURCES['amt_ameli_honoraires']['url']}"
    src_ondam = f"{SOURCES['secu_placss2025_annexe3']['url']} ; {SOURCES['secu_placss2024_annexe3']['url']}"

    doc_postes = {
        "millesime": f"{a_post[0]} à {a_post[-1]}", "source": src_postes, "unite": "euros (montants remboursés)",
        "date_sources": date, "statut": "tracé",
        "producteur": SOURCES["secu_ameli_depenses"]["producteur"],
        "perimetre": "Dépenses remboursées par l'ensemble des régimes d'assurance maladie aux 67,6 millions de "
                     "bénéficiaires ayant eu au moins un soin remboursé (population de la cartographie des "
                     "pathologies, 2024), France entière. Hors établissements médico-sociaux, fonds d'intervention "
                     "régional et dotations non rattachables à un patient.",
        "annees": a_post, "postes": postes["postes"], "controles": postes["controles"],
        "definitions": {"montants_eur": "montants remboursés par l'assurance maladie obligatoire (hors part des "
                                        "complémentaires et des patients), alignés sur `annees`",
                        "niveau": "0 total, 1 grand poste, 2 sous-poste publié par la source",
                        "controles": "écart entre le total publié d'un grand poste et la somme de ses sous-postes "
                                     "publiés (arrondis de la source)"},
        "ordre": "postes dans l'ordre total, soins de ville, hospitalisations, prestations en espèces ; sous-postes "
                 "par libellé de la source",
    }

    doc_dep = {
        "millesime": f"{a_dep[0]} à {a_dep[-1]}", "source": src_dep, "unite": "euros", "date_sources": date,
        "statut": "tracé",
        "producteur": SOURCES["amt_ameli_prescriptions"]["producteur"],
        "annees": a_dep,
        "postes_prescription": [{"id": i, "libelle": l, "code_source": c} for c, i, l in POSTES_PRESCRIPTION],
        "professions": [{"id": i, "libelle": l, "libelle_source": c} for c, i, l in PROFESSIONS],
        "departements": dep["departements"], "france": dep["france"],
        "ecarts_somme_france": {
            "colonnes": ["grandeur", "annee", "france_eur", "somme_departements_eur", "ecart_eur",
                         "departements_masques"],
            "lignes": [[e[c] for c in ("grandeur", "annee", "france_eur", "somme_departements_eur", "ecart_eur",
                                       "departements_masques")] for e in dep["ecarts"]],
            "lecture_ecart": "ligne France entière publiée par la Cnam moins la somme des départements publiés ; "
                             "un écart vient des arrondis ou des montants masqués par le secret statistique. "
                             "Les deux valeurs sont publiées, aucune n'est corrigée.",
        },
        "masques": {"prescriptions": dep["masques"]["prescriptions"], "honoraires": dep["masques"]["honoraires"],
                    "regle": "montant calculé sur moins de 5 professionnels : « NS » à la source, null ici, jamais 0"},
        "definitions": {
            "prescriptions": "montants des prescriptions des médecins libéraux du département, par poste "
                             "(médicaments, arrêts de travail indemnisés, analyses, transports...), alignés sur "
                             "`annees` ; c'est ce que les soins prescrits ont donné lieu à rembourser, rattaché au "
                             "département d'exercice du médecin prescripteur, pas au lieu de vie du patient",
            "honoraires.sans_depassement": "honoraires des professionnels libéraux du département hors "
                                           "dépassements (payés par l'assurance maladie, les complémentaires et les "
                                           "patients selon le taux de remboursement)",
            "honoraires.depassements": "dépassements d'honoraires facturés au-delà des tarifs de l'assurance "
                                       "maladie (non remboursés par l'assurance maladie obligatoire)",
            "region": "code de région de la source (Insee)",
        },
        "perimetre": "Professionnels de santé libéraux actifs au 31 décembre, France métropolitaine, Guadeloupe, "
                     "Martinique, Guyane, La Réunion et Mayotte. Hôpitaux, cliniques et établissements médico-sociaux "
                     "hors champ (voir `sante_etablissements/` et `secu/`).",
        "ordre": "départements dans l'ordre 01 à 19, 2A, 2B, 21 à 95, 971 à 976 ; postes et professions dans l'ordre "
                 "de `postes_prescription` et `professions`",
    }

    doc_ondam = {
        "millesime": "Exécution 2023 à 2025", "source": src_ondam, "unite": "milliards d'euros (Md€)",
        "date_sources": date, "statut": "tracé",
        "producteur": "Direction de la sécurité sociale (DSS), annexe 3 des projets de loi d'approbation des comptes "
                      "de la sécurité sociale",
        "sous_objectifs": [{"id": s, "libelle": l, "niveau": n, "parent": p} for s, l, n, p in SOUS_OBJECTIFS],
        "lignes": ondam["lignes"], "controles": ondam["controles"],
        "definitions": {
            "objectif_initial_md": "objectif voté dans la loi de financement de la sécurité sociale de l'année "
                                   "(loi de financement initiale)",
            "objectif_rectifie_md": "objectif rectifié par la loi de financement de l'année suivante",
            "constat_md": "dépenses constatées dans le champ de l'ONDAM (dernier constat publié)",
            "constat_precedent_md": "constat publié un an plus tôt (mars 2025 pour 2024)",
            "revision_constat_md": "différence entre les deux constats, publiée par la source",
            "ecart_objectif_initial_md": "constat moins objectif voté, publié par la source",
            "ecart_objectif_rectifie_md": "constat moins objectif rectifié, publié par la source",
            "evolution_pct": "évolution sur un an publiée par la source (à champ constant pour 2025)",
        },
        "limites": "Pour 2024, les objectifs par sous-objectif figurent dans des tableaux publiés en image (annexe 3 du "
                   "PLACSS 2024) : seuls les totaux écrits dans le texte sont repris (objectif voté 254,9 Md€ y "
                   "compris provision pour la crise sanitaire, objectif rectifié 256,9 Md€). Pour 2023, seul le "
                   "constat total est repris. Les sous-objectifs 2024 sont au périmètre de la base 2025 (après "
                   "transferts entre sous-objectifs).",
        "regle": "valeurs saisies relues dans le texte du document à chaque production ; écarts et évolutions repris "
                 "tels que publiés, jamais recalculés",
        "liens": {"secu": "secu/index.json (ONDAM constaté 2024 dans l'arbre des branches de la sécurité sociale)"},
        "ordre": "sous-objectifs dans l'ordre de la nomenclature de l'ONDAM",
    }

    p = {x["id"]: x for x in postes["postes"]}
    i24 = a_post.index(2024) if 2024 in a_post else len(a_post) - 1
    an_ref = a_post[i24]
    tot_ondam = ondam["lignes"][0]["annees"]
    totaux = {str(a): {g: p[g]["montants_eur"][i] for g in ("total", "soins_de_ville", "hospitalisations",
                                                            "prestations_en_especes")}
              for i, a in enumerate(a_post)}
    ecarts = [{
        "grandeur": "dépenses d'assurance maladie, toutes branches de soins",
        "annee": an_ref,
        "valeur_md": round(p["total"]["montants_eur"][i24] / 1e9, 1) if p["total"]["montants_eur"][i24] else None,
        "source": "secu_ameli_depenses",
        "autre_valeur_md": tot_ondam.get(str(an_ref), {}).get("constat_md"),
        "autre_source": "secu_placss2025_annexe3",
        "lecture_ecart": "Champs différents, aucun n'est corrigé : la cartographie de la Cnam compte les "
                         "remboursements rattachés à un patient (y compris indemnités journalières de maternité, "
                         "invalidité et rentes d'accident du travail, hors ONDAM) ; l'ONDAM compte aussi les "
                         "établissements médico-sociaux, le fonds d'intervention régional, les dotations hospitalières "
                         "non rattachées à un patient et les soins des Français à l'étranger.",
    }]

    index = {
        "millesime": f"Dépenses {a_post[0]} à {a_post[-1]}, départements {a_dep[0]} à {a_dep[-1]}, ONDAM 2023 à 2025",
        "source": f"{src_postes} ; {src_dep} ; {src_ondam}",
        "unite": "euros (postes, départements) ; milliards d'euros (ONDAM)",
        "date_sources": date,
        "presentation": "Ce que l'assurance maladie rembourse, par grand poste de soins (médecins, médicaments, "
                        "hôpital, indemnités journalières...) et par année ; ce que les médecins libéraux de chaque "
                        "département prescrivent et ce que les professionnels libéraux y perçoivent en honoraires ; "
                        "et l'objectif national de dépenses d'assurance maladie (ONDAM) voté, rectifié puis constaté, "
                        "par sous-objectif. Ne montre pas les dépenses par hôpital ni par patient, et ne rattache pas "
                        "les dépenses hospitalières à un département.",
        "fichiers": {"postes": f"{AXE}/postes.json", "departements": f"{AXE}/departements.json",
                     "ondam": f"{AXE}/ondam.json"},
        "annees_postes": a_post, "annees_departements": a_dep, "annees_ondam": [2023, 2024, 2025],
        "nombre_departements": len(dep["departements"]),
        "totaux_nationaux": {"unite": "euros remboursés, tous régimes", "source": "secu_ameli_depenses",
                             "annees": totaux},
        "ondam": {"annee": 2025, "objectif_initial_md": tot_ondam["2025"]["objectif_initial_md"],
                  "objectif_rectifie_md": tot_ondam["2025"]["objectif_rectifie_md"],
                  "constat_md": tot_ondam["2025"]["constat_md"], "source": "secu_placss2025_annexe3"},
        "ecarts": ecarts,
        "liens": {
            "secu": "secu/index.json : comptes des branches de la sécurité sociale, ONDAM constaté 2024 dans l'arbre",
            "sante_etablissements": "sante_etablissements/index.json : établissements de santé, activité, prix des "
                                    "Ehpad",
            "territoires": "territoires/<dep>.json : autres dépenses publiques par département",
            "prestations": "prestations/ : prestations sociales nationales et départementales",
        },
        "methode": "Montants repris tels que publiés par la Cnam (data.ameli.fr) et la DSS, sans redressement. "
                   "Les trois vues ont des champs différents et ne sont jamais additionnées ; leurs écarts sont "
                   "publiés. Contrôles publiés : sous-postes face au total de chaque grand poste, somme des "
                   "départements face à la ligne France entière, sous-objectifs face au total de l'ONDAM.",
        "limites": "Les montants par département sont ceux des professionnels libéraux (département d'exercice) : "
                   "ils n'incluent ni l'hôpital ni les cliniques et ne disent pas où vivent les patients. Les "
                   "honoraires comprennent la part payée par les complémentaires et les patients. Aucun montant par "
                   "habitant n'est calculé ici (populations dans `local/geo/`).",
        "confidentialite": "Agrégats seulement. La Cnam masque (« NS ») les montants calculés sur moins de 5 "
                           f"professionnels : {dep['masques']['honoraires']} valeurs d'honoraires et "
                           f"{dep['masques']['prescriptions']} valeurs de prescriptions masquées, publiées null. "
                           "Aucun professionnel ni patient n'est nommé.",
        "regle": "une valeur absente ou masquée reste null, jamais 0 ; un écart entre sources est publié, jamais "
                 "tranché",
        "ordre": "clés dans l'ordre d'écriture ; listes ordonnées comme indiqué dans chaque fichier",
        "sources": sources_de(SOURCES),
        "sources_inaccessibles": SOURCES_INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }

    sortie.mkdir(parents=True, exist_ok=True)
    tailles = {"postes.json": dump(sortie / "postes.json", doc_postes),
               "departements.json": dump(sortie / "departements.json", doc_dep),
               "ondam.json": dump(sortie / "ondam.json", doc_ondam)}
    tailles["index.json"] = dump(sortie / "index.json", index)
    print(f"{AXE} : {len(postes['postes'])} postes ({a_post[0]}-{a_post[-1]}), {len(dep['departements'])} "
          f"départements ({a_dep[0]}-{a_dep[-1]}), ONDAM {len(ondam['lignes'])} lignes, fichier max "
          f"{max(tailles.values())} octets")
    return index


def collecter() -> int:
    """Réseau : collecte/collecte.py (téléchargement contrôlé par collecte/integrite.py) ; refus 401/403/429 notés."""
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *COLLECTABLES])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("commande", nargs="?", choices=("collecter", "produire"))
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    code = 0
    if a.commande in (None, "collecter"):
        code = collecter()
    if a.commande in (None, "produire"):
        produire(a.sortie)
    return code


if __name__ == "__main__":
    sys.exit(main())
