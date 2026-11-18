"""Satellites locaux : syndicats, CCAS et CIAS, autorités organisatrices de la mobilité, services d'eau, par commune.

Pour chaque commune (code Insee), par département : quels syndicats, centres d'action sociale, autorité organisatrice
de la mobilité (AOM) et services d'eau et d'assainissement la concernent, leurs dépenses (total, et par habitant
quand une population est publiée), le taux de versement mobilité et le prix de l'eau.

Entrées : entrepôt brut data/lake/collectivites/local_satellites/ (non versionné), rempli par `collecter` :
    ofgl_syndicats_<AAAA>.parquet   OFGL, comptes des syndicats 2018-2025 (agrégats retenus, un export par exercice)
    ofgl_ccas_<AAAA>.parquet        OFGL, comptes des CCAS-CIAS 2018-2025 (agrégats retenus, un export par exercice)
    banatic_france.xlsx             DGCL, BANATIC : groupements, membres, compétences (export France entière)
    aom_base_rt_2026.ods            Cerema, liste et composition des AOM au 1er janvier 2026 (ODbL)
    urssaf_taux_vmrr.csv            Urssaf, taux de versement mobilité par commune et période (ODbL)
    sispea_2024_{AEP,AC,ANC}.7z     OFB, SISPEA : services d'eau potable, d'assainissement collectif et non collectif
    extraits/*.json                 colonnes utiles de ces fichiers (liste blanche : ni adresse, ni courriel, ni
                                    téléphone, ni nom de président), commune du siège et catégorie juridique SIRENE
  et, en lecture seule, site/data/local/geo/<dep>.json et site/data/local/index.json (pipeline/local.py).
Sorties (site/data/local_satellites/) :
    index.json                 blocs disponibles par commune (masque de bits), totaux, flux croisés, sources
    syndicats/<dep>.json       syndicats concernant chaque commune, compétences, dépenses et recettes 2018-2025
    ccas/<dep>.json            CCAS de chaque commune et CIAS de son intercommunalité, dépenses 2018-2025
    mobilite/<dep>.json        AOM de chaque commune, taux de versement mobilité (base de données sous ODbL)
    eau/<dep>.json             services d'eau et d'assainissement : mode de gestion, prix au m³, population desservie

Commandes :
    python pipeline/local_satellites.py collecter   # réseau ; un refus 401/403/429 est noté, jamais contourné
    python pipeline/local_satellites.py produire    # sans réseau
    python pipeline/local_satellites.py             # les deux

Règles :
  - aucune dépense d'un satellite n'est ajoutée au budget d'une commune, d'une intercommunalité ou d'un autre
    satellite : les contributions des membres figurent déjà dans les budgets publiés (local/budgets/) ; chaque flux
    croisé est décrit dans index.json (`flux_croises`) et les recettes venant des membres sont publiées à part ;
  - un organisme n'est nommé que si sa catégorie juridique SIRENE est celle d'une personne morale ; les textes libres
    passent par local.objet_publiable ; le nom de l'opérateur d'un service d'eau (sans SIREN publié) n'est pas repris ;
  - valeur absente ou non saisie à la source : null, jamais 0 ;
  - toute date écrite vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import sys
import tempfile
import time
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "collectivites" / "local_satellites"
EXTRAITS = BRUT / "extraits"
SITE = ROOT / "site" / "data"
GEO = SITE / "local" / "geo"
SORTIE = SITE / "local_satellites"
MAX_OCTETS = 4_800_000
ANNEES = list(range(2018, 2026))
ANNEE_EAU = 2024
ANNEE_AOM = 2026
DATE_REFERENCE_VM = f"{ANNEE_AOM}0101"
ENTETE_HTTP = {"User-Agent": "ou-vont-mes-impots/pipeline"}

OFGL = "https://data.ofgl.fr/api/explore/v2.1/catalog/datasets"
DATAGOUV_SIRENE = ("https://www.data.gouv.fr/api/1/datasets/"
                   "base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/")
OFB = "https://data.ofb.fr/catalogue/srv/api/records"

# clé publiée -> libellé de l'agrégat OFGL (repris tel quel, y compris sa graphie)
AGREGATS_SYNDICATS = {
    "depenses_totales_hors_remb": "Dépenses totales hors remb",
    "depenses_fonctionnement": "Dépenses de fonctionnement",
    "depenses_investissement_hors_remb": "Dépenses d'investissement hors remb",
    "subventions_participations_recues": "Subventions reçues et participations",
    "ventes_biens_services": "Ventes de biens et services",
    "impots_taxes": "Impôts et taxes",
    "versement_mobilite": "Versement transport",
    "teom": "Taxe d'enlévement des ordures ménagères",
}
AGREGATS_CCAS = {
    "depenses_totales_hors_remb": "Dépenses totales hors remb",
    "depenses_fonctionnement": "Dépenses de fonctionnement",
    "depenses_investissement_hors_remb": "Dépenses d'investissement hors remb",
    "participations_communes": "Participations des communes",
    "subventions_participations_recues": "Subventions reçues et participations",
    "ventes_biens_services": "Ventes de biens et services",
}
CATEGORIES_SYNDICATS = {
    "Syndicat (SIVU, SIVOM, SMF, SMO), entente et commission syndicale": "syndicat",
    "Pôle d'équilibre territorial et rural (PETR)": "petr",
    "Pôle métropolitain": "pole_metropolitain",
    "Maison départementale des personnes handicapées (MDPH)": "mdph",
}
NATURES_SYNDICATS = {"SIVU", "SIVOM", "SMF", "SMO", "PETR", "POLEM"}
NATURES_LIBELLES = {
    "SIVU": "syndicat intercommunal à vocation unique", "SIVOM": "syndicat intercommunal à vocation multiple",
    "SMF": "syndicat mixte fermé", "SMO": "syndicat mixte ouvert", "PETR": "pôle d'équilibre territorial et rural",
    "POLEM": "pôle métropolitain",
}

SOURCES = {
    "ofgl_syndicats": {
        "titre": "OFGL, « Comptes des syndicats 2018-2025 » (ofgl-base-syndicats) : agrégats calculés par l'OFGL à "
                 "partir des balances comptables publiées par la DGFiP, budgets principaux et annexes",
        "url": f"{OFGL}/ofgl-base-syndicats/exports/parquet",
        "page": "https://data.ofgl.fr/explore/dataset/ofgl-base-syndicats/",
        "producteur": "OFGL (données DGFiP)", "millesime": "exercices 2018 à 2025", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (export par exercice, agrégats retenus filtrés côté serveur)",
    },
    "ofgl_ccas": {
        "titre": "OFGL, « Comptes des CCAS-CIAS 2018-2025 » (ofgl-base-ccas-cias) : agrégats calculés par l'OFGL à "
                 "partir des balances comptables publiées par la DGFiP, budgets principaux et annexes",
        "url": f"{OFGL}/ofgl-base-ccas-cias/exports/parquet",
        "page": "https://data.ofgl.fr/explore/dataset/ofgl-base-ccas-cias/",
        "producteur": "OFGL (données DGFiP)", "millesime": "exercices 2018 à 2025", "licence": "Licence Ouverte 2.0",
        "verdict": "à adapter (la commune du centre n'est pas publiée : rattachement par la commune du siège SIRENE)",
    },
    "banatic": {
        "titre": "DGCL, BANATIC, export « France entière » : groupements, membres, population, compétences exercées",
        "url": "https://www.banatic.interieur.gouv.fr/consultation/api/export/pregenere/telecharger/France",
        "page": "https://www.banatic.interieur.gouv.fr/", "fichier": "banatic_france.xlsx",
        "producteur": "DGCL (ministère de l'Intérieur)", "millesime": "périmètres en vigueur à la date de collecte",
        "licence": "Licence Ouverte 2.0",
        "verdict": "à adapter (classeur de 1,5 Go décompressé lu en flux ; colonnes d'adresse, de téléphone, de "
                   "courriel et de président jamais lues)",
    },
    "cerema_aom": {
        "titre": "Cerema, « Liste et composition des autorités organisatrices de la mobilité (AOM) au 1er janvier "
                 "2026 » (base-rt-2026.ods)",
        "url": "https://static.data.gouv.fr/resources/liste-et-composition-des-autorites-organisatrices-de-la-"
               "mobilite-aom/20260716-092939/base-rt-2026.ods",
        "page": "https://www.data.gouv.fr/datasets/5b90e9338b4c413448c4b22a/", "fichier": "aom_base_rt_2026.ods",
        "producteur": "Cerema", "millesime": "1er janvier 2026", "licence": "ODbL 1.0",
        "verdict": "réutilisable tel quel (colonne de courriel jamais lue)",
    },
    "urssaf_vm": {
        "titre": "Urssaf, « Table des taux de versement mobilité, versement mobilité additionnel et versement "
                 "mobilité régional et rural » (table_taux_vmrr) : taux par commune et période d'effet",
        "url": "https://open.urssaf.fr/api/explore/v2.1/catalog/datasets/table_taux_vmrr/exports/csv?delimiter=%3B",
        "page": "https://open.urssaf.fr/explore/dataset/table_taux_vmrr/", "fichier": "urssaf_taux_vmrr.csv",
        "producteur": "Urssaf Caisse nationale", "millesime": "taux en vigueur au 1er janvier 2026 et période suivante",
        "licence": "ODbL 1.0", "verdict": "réutilisable tel quel",
    },
    "sispea": {
        "titre": "OFB, SISPEA, « Données annuelles sur le prix et la performance des services publics d'eau potable, "
                 "d'assainissement collectif et d'assainissement non collectif », exercice 2024, par entité de gestion",
        "url": f"{OFB}/<fiche>/attachments/SISPEA_extraction_2024_<AEP|AC|ANC>.7z",
        "page": "https://www.services.eaufrance.fr/",
        "producteur": "Office français de la biodiversité, collectivités, directions départementales des territoires",
        "millesime": "exercice 2024", "licence": "Licence Ouverte 2.0",
        "verdict": "à adapter (la liste des communes de chaque service n'est pas dans le fichier : rattachement par "
                   "la collectivité organisatrice)",
    },
    "sirene": {
        "titre": "Insee, base SIRENE : catégorie juridique des unités légales et commune de l'établissement siège "
                 "(stock mensuel, format parquet)",
        "url": DATAGOUV_SIRENE, "page": "https://www.data.gouv.fr/datasets/5b7ffc618b4c4169d30727e0/",
        "producteur": "Insee", "millesime": "stock mensuel à la date de collecte", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (deux colonnes lues à distance : SIREN et code commune du siège)",
    },
}
SISPEA_FICHES = {"AEP": "7d6a3010-cf19-42c3-8a38-9823074185ce", "AC": "5feec4e9-03a6-409a-a522-d51346d5f4c9",
                 "ANC": "96f91c3e-cc33-4f7a-a0fa-6620ff79d168"}
SISPEA_COMPETENCES = {"AEP": "eau_potable", "AC": "assainissement_collectif", "ANC": "assainissement_non_collectif"}
# indicateurs SISPEA repris : population desservie et prix TTC au m³ pour 120 m³
SISPEA_INDICATEURS = {"AEP": ("D101.0", "D102.0"), "AC": ("D201.0", "D204.0"), "ANC": ("D301.0", None)}
SISPEA_MISSIONS = {"AEP": ["Production", "Transfert", "Distribution"], "AC": ["Collecte", "Transport", "Dépollution"],
                   "ANC": []}

INACCESSIBLES = [
    {"source": "Hub'Eau, API « Indicateurs des services » (hubeau.eaufrance.fr/api/v0/indicateurs_services)",
     "constat": "HTTP 410 (ressource retirée) le 17/11/2026 ; versions v1 et v2 : HTTP 404",
     "consequence": "la liste des communes de chaque service d'eau n'est pas reprise de cette API : rattachement "
                    "par la collectivité organisatrice (commune, intercommunalité, membres BANATIC du syndicat)"},
    {"source": "Île-de-France Mobilités (comptes)",
     "constat": "absent du jeu OFGL des syndicats (mention de l'OFGL)",
     "consequence": "l'AOM est citée sans montant"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "verdict": "aucun dépôt public ne rattache à la fois syndicats, CCAS, AOM et services d'eau à chaque commune ; "
               "les jeux officiels sont réutilisés tels quels ou adaptés, le code de rattachement est écrit ici",
    "trouvailles": [
        {"nom": "OFGL, jeux ofgl-base-syndicats et ofgl-base-ccas-cias", "url": "https://data.ofgl.fr/",
         "classement": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "dernier_commit": None,
         "note": "jeux officiels, dernière modification en juillet 2026"},
        {"nom": "BANATIC, export pré-généré France entière", "url": "https://www.banatic.interieur.gouv.fr/",
         "classement": "à adapter", "licence": "Licence Ouverte 2.0", "dernier_commit": None,
         "note": "une ligne par groupement et membre ; lecture en flux nécessaire"},
        {"nom": "Cerema, base des AOM", "url": "https://www.data.gouv.fr/datasets/5b90e9338b4c413448c4b22a/",
         "classement": "réutilisable tel quel", "licence": "ODbL 1.0", "dernier_commit": None,
         "note": "composition communale au 1er janvier 2026"},
        {"nom": "Urssaf, table_taux_vmrr", "url": "https://open.urssaf.fr/explore/dataset/table_taux_vmrr/",
         "classement": "réutilisable tel quel", "licence": "ODbL 1.0", "dernier_commit": None,
         "note": "partage à l'identique : mobilite/<dep>.json est publié sous ODbL"},
        {"nom": "SISPEA, extractions annuelles", "url": "https://www.services.eaufrance.fr/",
         "classement": "à adapter", "licence": "Licence Ouverte 2.0", "dernier_commit": None,
         "note": "classeurs .xls dans des archives 7z ; pas de liste de communes par service"},
    ],
}

FLUX_CROISES = [
    {"id": "contributions_aux_syndicats", "de": "commune ou intercommunalité membre", "vers": "syndicat",
     "nature": "contributions et participations des membres",
     "deja_publie": "dépenses de fonctionnement de la commune (local/budgets/communes/) et de l'intercommunalité "
                    "(local/budgets/epci/)",
     "ici": "agrégat OFGL « Subventions reçues et participations » du syndicat (`subventions_participations_recues`), "
            "qui réunit ces contributions et les subventions d'autres organismes",
     "regle": "les dépenses d'un syndicat ne sont jamais ajoutées à celles de ses membres"},
    {"id": "adhesions_entre_syndicats", "de": "syndicat membre", "vers": "syndicat",
     "nature": "contributions d'un syndicat à un autre syndicat dont il est membre",
     "deja_publie": "dépenses du syndicat membre (même fichier)",
     "ici": "`via` = `syndicat` dans la liste d'une commune",
     "regle": "les totaux nationaux par exercice sont des sommes non consolidées, déclarées comme telles"},
    {"id": "budgets_d_un_meme_organisme", "de": "budget principal", "vers": "budgets annexes du même organisme",
     "nature": "subventions et remboursements entre budgets",
     "deja_publie": "non", "ici": "chaque montant est la somme des budgets publiés par l'OFGL pour l'organisme "
                                  "(`budgets` en donne le nombre)",
     "regle": "les flux entre budgets d'un même organisme ne sont pas retirés par le pipeline"},
    {"id": "subvention_au_ccas", "de": "commune", "vers": "CCAS",
     "nature": "subvention de la commune à son centre communal d'action sociale",
     "deja_publie": "dépenses de fonctionnement de la commune (local/budgets/communes/)",
     "ici": "agrégat OFGL « Participations des communes » du centre (`participations_communes`)",
     "regle": "les dépenses d'un CCAS ne sont jamais ajoutées à celles de la commune"},
    {"id": "subvention_au_cias", "de": "intercommunalité ou communes", "vers": "CIAS",
     "nature": "subvention au centre intercommunal d'action sociale",
     "deja_publie": "dépenses de fonctionnement de l'intercommunalité (local/budgets/epci/) ou des communes",
     "ici": "`participations_communes` et `subventions_participations_recues` du centre",
     "regle": "les dépenses d'un CIAS ne sont jamais ajoutées à celles de l'intercommunalité"},
    {"id": "aom_deja_publiee", "de": "intercommunalité, région ou syndicat", "vers": "autorité organisatrice",
     "nature": "l'AOM est le plus souvent une collectivité dont le budget est déjà publié",
     "deja_publie": "local/budgets/epci/, local/budgets/regions.json ou syndicats/<dep>.json",
     "ici": "`comptes` de chaque AOM : lien vers le fichier où lire son budget, sans montant recopié",
     "regle": "aucune dépense de mobilité n'est ajoutée : le lien suffit"},
    {"id": "versement_mobilite", "de": "employeurs de 11 salariés et plus (collecte Urssaf)", "vers": "AOM",
     "nature": "versement mobilité, en pourcentage de la masse salariale",
     "deja_publie": "recettes de l'AOM (budget de l'intercommunalité ou du syndicat)",
     "ici": "taux par commune ; produit perçu par les syndicats : agrégat OFGL « Versement transport » "
            "(`versement_mobilite`)",
     "regle": "le taux n'est pas converti en montant par commune"},
    {"id": "services_d_eau", "de": "abonnés (factures d'eau)", "vers": "service d'eau ou d'assainissement",
     "nature": "redevances des usagers, sur un budget annexe équilibré par ces recettes",
     "deja_publie": "comptes de la commune, de l'intercommunalité ou du syndicat organisateur (budgets annexes)",
     "ici": "prix TTC au m³ et mode de gestion ; SISPEA ne publie pas de dépenses",
     "regle": "aucune dépense d'eau n'est ajoutée ; le SIREN de la collectivité organisatrice permet de retrouver "
              "ses comptes"},
]

BLOCS = ["syndicats", "organismes_departementaux", "ccas", "cias", "aom", "versement_mobilite", "eau_potable",
         "assainissement_collectif", "assainissement_non_collectif"]

DEFINITIONS = {
    "depenses_totales_hors_remb": "agrégat OFGL « Dépenses totales hors remb » : dépenses de fonctionnement et "
                                  "d'investissement, hors remboursements d'emprunts",
    "eur_hab": "dépenses totales hors remboursements du dernier exercice publié, divisées par la population publiée "
               "(BANATIC pour un syndicat, geo.api.gouv.fr pour un CCAS ou un CIAS) ; null si l'une des deux manque",
    "via": "`commune` : la commune est membre du syndicat ; `epci` : son intercommunalité en est membre ; `syndicat` : "
           "un syndicat dont la commune ou son intercommunalité est membre en est lui-même membre",
    "versement_mobilite": "contribution des employeurs de 11 salariés et plus, en pourcentage de la masse salariale, "
                          "affectée à l'autorité organisatrice de la mobilité ; taux_vma : versement additionnel d'un "
                          "syndicat mixte de transport ; taux_vmr : versement mobilité régional et rural",
    "prix_m3_ttc": "indicateurs SISPEA D102.0 (eau potable) et D204.0 (assainissement collectif) : prix TTC du "
                   "service au m³ pour une consommation de 120 m³, au 1er janvier suivant l'exercice",
    "population_desservie": "indicateurs SISPEA D101.0, D201.0 et D301.0 : estimation du nombre d'habitants desservis",
}

LIMITES = [
    "Syndicats : une intercommunalité peut n'adhérer à un syndicat que pour une partie de ses communes ; BANATIC ne "
    "publie pas ce détail dans l'export utilisé : une commune rattachée `via` `epci` ou `syndicat` peut ne pas être "
    "desservie.",
    "Syndicats : les membres autres que communes, intercommunalités et syndicats (départements, régions, chambres "
    "consulaires) ne rattachent aucune commune ; ces syndicats figurent dans `non_rattaches`.",
    "Syndicats : la population est celle du périmètre BANATIC à la date de collecte ; le montant par habitant n'est "
    "calculé que pour le dernier exercice publié.",
    "CCAS et CIAS : l'OFGL ne publie pas la commune du centre ; elle est lue dans SIRENE (commune de l'établissement "
    "siège). Un CIAS est rattaché aux communes de l'intercommunalité de sa commune siège (communauté de communes, "
    "d'agglomération ou urbaine) ; `competence_cias_banatic` dit si BANATIC indique que cette intercommunalité "
    "exerce la compétence « Centre intercommunal d'action sociale ». Dans une métropole, le CIAS n'est rattaché que "
    "si BANATIC l'indique ; sinon il figure dans `non_rattaches`. Un CIAS peut ne couvrir qu'une partie de "
    "l'intercommunalité.",
    "CCAS et CIAS : l'OFGL ne garde que les centres ayant des dépenses, des recettes ou une dette ; une commune sans "
    "centre dans le fichier n'a pas de bloc `ccas`.",
    "Services d'eau : le fichier SISPEA ne liste pas les communes de chaque entité de gestion ; une commune est "
    "rattachée aux collectivités organisatrices (sa commune, son intercommunalité, les syndicats dont elle ou son "
    "intercommunalité est membre selon BANATIC), chacune avec la liste de ses entités de gestion. Une entité peut ne "
    "couvrir qu'une partie du territoire : le prix applicable à une commune n'est pas désigné quand la collectivité "
    "a plusieurs entités.",
    "Services d'eau : un prix non saisi par la collectivité est null ; `statut_saisie` donne l'état de la saisie.",
    "Versement mobilité : une commune sans ligne en vigueur dans la table de l'Urssaf a des taux null.",
]


# --- Outils -----------------------------------------------------------------------------------------------------------

def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets ({n}) : découper")
    path.write_text(texte + "\n", encoding="utf-8")
    return n


def propre(v) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()


def nombre(v):
    """Nombre publié (virgule décimale admise) ; vide, texte ou valeur illisible : None, jamais 0."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if v != v else v
    s = propre(v).replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def entier(v):
    n = nombre(v)
    return None if n is None else int(round(n))


def euros(v):
    return None if v is None else round(v)


def par_habitant(montant, population):
    if montant is None or not population or population <= 0:
        return None
    return round(montant / population, 2)


def siren_valide(v) -> str | None:
    s = propre(v).split(".")[0]
    return s if sirene.siren_valide(s) else None


def code_dep(insee: str) -> str:
    return insee[:3] if insee.startswith("97") else insee[:2]


def commune_de(code: str) -> str:
    """Code Insee de la commune : les arrondissements de Paris, Lyon et Marseille sont ramenés à leur commune."""
    code = propre(code).zfill(5)
    if "75101" <= code <= "75120":
        return "75056"
    if "69381" <= code <= "69389":
        return "69123"
    if "13201" <= code <= "13216":
        return "13055"
    return code


def arrondi_centimes(centimes: int) -> int:
    """Euros entiers à partir d'un total en centimes (arithmétique entière : résultat indépendant de l'ordre de somme)."""
    return (abs(centimes) + 50) // 100 * (1 if centimes >= 0 else -1)


def nommable(cj) -> bool:
    return sirene.personne_morale(cj)


def taux_en_vigueur(periodes: list[tuple], reference: str = DATE_REFERENCE_VM):
    """(période en vigueur à la date de référence, première période qui la suit) parmi (debut, fin, vm, vma, vmr)."""
    en_cours = [p for p in periodes if p[0] <= reference and (not p[1] or p[1] >= reference)]
    apres = [p for p in periodes if p[0] > reference]
    return (max(en_cours, key=lambda p: (p[0], p[1] or "9")) if en_cours else None,
            min(apres, key=lambda p: (p[0], p[1] or "9")) if apres else None)


# --- Géographie (lecture seule des sorties de pipeline/local.py) -----------------------------------------------------

def geographie() -> dict:
    communes, epci, deps, siren_commune = {}, {}, {}, {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        deps[d["departement"]["code"]] = d["departement"]["nom"]
        for code, c in d["communes"].items():
            communes[code] = c
            if c.get("siren"):
                siren_commune[c["siren"]] = code
        for s, e in d["epci"].items():
            epci.setdefault(s, {"nom": e["nom"], "population": e.get("population"),
                                "departement_siege": e.get("departement_siege"), "communes": []})
    for code, c in communes.items():
        if c.get("epci") in epci:
            epci[c["epci"]]["communes"].append(code)
    idx = json.loads((SITE / "local" / "index.json").read_text(encoding="utf-8"))
    regions = {s: code for code, s in idx["sirens"]["regions"].items()}
    departements = {s: code for code, s in idx["sirens"]["departements"].items()}
    return {"communes": communes, "epci": epci, "deps": deps, "siren_commune": siren_commune, "regions": regions,
            "departements": departements}


# --- Lecture en flux des classeurs ------------------------------------------------------------------------------------

_CELLULE = re.compile(r'<c r="([A-Z]+)\d+"[^>]*?(?:/>|>(?:<is><t[^>]*>(.*?)</t></is>|<v>(.*?)</v>)?</c>)', re.S)


def _colonne(lettres: str) -> int:
    n = 0
    for ch in lettres:
        n = n * 26 + ord(ch) - 64
    return n - 1


def lignes_xlsx_flux(chemin: Path, garder=None):
    """Lignes de la première feuille d'un classeur à chaînes en ligne, lues en flux : {indice de colonne: texte}.

    `garder(indice)` limite les colonnes lues ; l'en-tête (première ligne) est toujours lu en entier.
    """
    with zipfile.ZipFile(chemin) as z, z.open("xl/worksheets/sheet1.xml") as f:
        reste, premiere = "", True
        while True:
            bloc = f.read(8 << 20)
            if not bloc:
                break
            parts = (reste + bloc.decode("utf-8", "replace")).split("</row>")
            reste = parts.pop()
            for r in parts:
                ligne = {}
                for m in _CELLULE.finditer(r):
                    i = _colonne(m.group(1))
                    if premiere or garder is None or garder(i):
                        ligne[i] = html.unescape(m.group(2) or m.group(3) or "")
                premiere = False
                yield ligne


def lignes_ods_flux(chemin: Path):
    """(feuille, cellules) pour chaque ligne d'un tableur ODS, lu en flux (cellules répétées développées, 200 au plus)."""
    from xml.etree.ElementTree import iterparse
    t, x = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}", "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    with zipfile.ZipFile(chemin) as z, z.open("content.xml") as f:
        feuille = None
        for ev, el in iterparse(f, events=("start", "end")):
            if ev == "start" and el.tag == t + "table":
                feuille = el.get(t + "name")
            elif ev == "end" and el.tag == t + "table-row":
                ligne = []
                for c in el:
                    if c.tag not in (t + "table-cell", t + "covered-table-cell"):
                        continue
                    texte = " ".join("".join(p.itertext()) for p in c.iter(x + "p"))
                    rep = int(c.get(t + "number-columns-repeated", "1"))
                    ligne.extend([texte] * min(rep, 200 - len(ligne)))
                    if len(ligne) >= 200:
                        break
                yield feuille, ligne
                el.clear()


# --- Extraits (liste blanche de colonnes) ----------------------------------------------------------------------------

BANATIC_COLONNES = {"N° SIREN": "siren", "Nom du groupement": "nom", "Nature juridique": "nature",
                    "Syndicat à la carte": "a_la_carte", "Population totale": "population",
                    "Nombre de membres": "nb_membres", "Siren membre": "membre",
                    "Catégorie des membres du groupement": "categorie_membre", "Département": "departement"}
BANATIC_PREMIERE_COMPETENCE = "Concession de la distribution publique d'électricité"
BANATIC_DERNIERE_COMPETENCE = "Autres"


def extraire_banatic(source: Path) -> dict:
    """Groupements (nature, population, compétences) et membres (SIREN, catégorie). Adresses, téléphones, courriels et
    noms de présidents ne sont jamais lus : seules les colonnes de BANATIC_COLONNES et les compétences le sont."""
    it = lignes_xlsx_flux(source, garder=lambda i: i in utiles)
    utiles: set[int] = set()
    entete = next(it)
    par_nom = {propre(v): i for i, v in entete.items()}
    col = {cle: par_nom[lib] for lib, cle in BANATIC_COLONNES.items()}
    c0, c1 = par_nom[BANATIC_PREMIERE_COMPETENCE], par_nom[BANATIC_DERNIERE_COMPETENCE]
    competences = [propre(entete[i]) for i in range(c0, c1 + 1)]
    utiles.update(col.values())
    utiles.update(range(c0, c1 + 1))
    groupements, membres = {}, defaultdict(list)
    for l in it:
        s = siren_valide(l.get(col["siren"]))
        if not s:
            continue
        if s not in groupements:
            groupements[s] = {
                "nom": propre(l.get(col["nom"])), "nature": propre(l.get(col["nature"])),
                "a_la_carte": propre(l.get(col["a_la_carte"])).upper() == "OUI",
                "population": entier(l.get(col["population"])), "nb_membres": entier(l.get(col["nb_membres"])),
                "departement": propre(l.get(col["departement"])).split(" - ")[0],
                "competences": [i - c0 for i in range(c0, c1 + 1) if propre(l.get(i)).upper() == "OUI"],
            }
        m = siren_valide(l.get(col["membre"]))
        if m:
            membres[s].append([m, propre(l.get(col["categorie_membre"]))])
    for s in groupements:
        groupements[s]["membres"] = sorted(map(tuple, {tuple(x) for x in membres.get(s, [])}))
    return {"competences": competences, "groupements": dict(sorted(groupements.items()))}


AOM_COLONNES = {"N° SIREN AOM": "siren", "Nom de l’AOM": "nom", "Forme juridique De l’AOM": "forme",
                "Nombre de commune De l’AOM": "nb_communes", "Population totale de L’AOM 2026 (DGCL)": "population",
                "VM_Taux_max": "vm_taux_max"}
COMPO_COLONNES = {"N° INSEE": "insee", "N° SIREN AOM": "aom", "N° SIREN Groupement": "groupement",
                  "SM_SRU": "sm_sru", "VM (URSAFF 2026)": "vm_cerema"}


def extraire_aom(source: Path) -> dict:
    """AOM et composition communale (Cerema). La colonne « Adresse mail » n'est jamais lue."""
    aom, communes, entetes = {}, {}, {}
    for feuille, ligne in lignes_ods_flux(source):
        if feuille not in entetes:
            entetes[feuille] = {propre(v): i for i, v in reversed(list(enumerate(ligne))) if propre(v)}
            continue
        e = entetes[feuille]

        def val(lib):
            i = e.get(lib)
            return propre(ligne[i]) if i is not None and i < len(ligne) else ""

        if feuille.endswith("_AOM"):
            s = siren_valide(val("N° SIREN AOM"))
            if s:
                aom[s] = {"nom": val("Nom de l’AOM"), "forme": val("Forme juridique De l’AOM"),
                          "nb_communes": entier(val("Nombre de commune De l’AOM")),
                          "population": entier(val("Population totale de L’AOM 2026 (DGCL)")),
                          "vm_taux_max": nombre(val("VM_Taux_max"))}
        elif feuille.endswith("_composition_communale"):
            insee = val("N° INSEE").split(".")[0].zfill(5)  # le tableur perd le zéro initial (01 à 09)
            if re.fullmatch(r"[0-9AB]{5}", insee) and insee != "00000":
                communes[insee] = {"aom": siren_valide(val("N° SIREN AOM")), "aom_nom": val("Nom de l’AOM"),
                                   "aom_forme": val("Forme juridique De l’AOM"),
                                   "groupement": siren_valide(val("N° SIREN Groupement")),
                                   "sm_sru": val("SM_SRU") or None, "vm_cerema": nombre(val("VM (URSAFF 2026)"))}
    return {"aom": dict(sorted(aom.items())), "communes": dict(sorted(communes.items()))}


SISPEA_COLONNES = ["Id SISPEA de l'entité de gestion", "Id SISPEA de la collectivité", "Nom collectivité", "Type collectivité", "N° SIREN",
                   "N° INSEE si commune", "DPT du siège de la coll.", "Nom de l'entité de gestion",
                   "Communes adhérentes de l'entité de gestion", "Mode de gestion", "Statut de l'opérateur", "Statut"]


def extraire_sispea(dossier: Path) -> dict:
    """Entités de gestion SISPEA. Courriels et nom de l'opérateur ne sont jamais lus (liste blanche de colonnes)."""
    try:
        import py7zr
        import xlrd
    except ImportError as e:  # dépendances de collecte seulement
        raise SystemExit(f"collecte SISPEA : installer py7zr et xlrd ({e})")
    services = {}
    for code, competence in SISPEA_COMPETENCES.items():
        with tempfile.TemporaryDirectory(prefix="sispea_") as tmp:
            with py7zr.SevenZipFile(dossier / f"sispea_{ANNEE_EAU}_{code}.7z") as z:
                z.extractall(tmp)
            xls = sorted(Path(tmp).rglob("*.xls"))
            feuille = xlrd.open_workbook(str(xls[0])).sheet_by_name("Entités de gestion")
            entete = [propre(v) for v in feuille.row_values(0)]
            pop, prix = SISPEA_INDICATEURS[code]
            col = {c: entete.index(c) for c in SISPEA_COLONNES + SISPEA_MISSIONS[code] + [pop] + ([prix] if prix else [])}
            for i in range(1, feuille.nrows):
                r = feuille.row_values(i)
                ident = propre(r[col[SISPEA_COLONNES[0]]]).split(".")[0]
                if not ident:
                    continue
                insee = propre(r[col["N° INSEE si commune"]]).split(".")[0]
                services[f"{code}{ident}"] = {
                    "competence": competence, "collectivite": propre(r[col["Nom collectivité"]]),
                    "collectivite_id": propre(r[col["Id SISPEA de la collectivité"]]).split(".")[0],
                    "type_collectivite": propre(r[col["Type collectivité"]]) or None,
                    "siren": siren_valide(r[col["N° SIREN"]]),
                    "insee": insee.zfill(5) if insee else None,
                    "departement_siege": propre(r[col["DPT du siège de la coll."]]).split(".")[0],
                    "entite": propre(r[col["Nom de l'entité de gestion"]]),
                    "communes_adherentes": entier(r[col["Communes adhérentes de l'entité de gestion"]]),
                    "mode_gestion": propre(r[col["Mode de gestion"]]) or None,
                    "statut_operateur": propre(r[col["Statut de l'opérateur"]]) or None,
                    "statut_saisie": propre(r[col["Statut"]]) or None,
                    "missions": [m.lower() for m in SISPEA_MISSIONS[code] if nombre(r[col[m]]) == 1],
                    "population": entier(r[col[pop]]),
                    "prix_m3_ttc": nombre(r[col[prix]]) if prix else None,
                }
    return {"exercice": ANNEE_EAU, "services": dict(sorted(services.items()))}


def lire_extrait(nom: str) -> dict:
    p = EXTRAITS / f"{nom}.json"
    if not p.exists():
        raise SystemExit(f"{p} absent : lancer `python pipeline/local_satellites.py collecter`")
    return json.loads(p.read_text(encoding="utf-8"))


def ecrire_extrait(nom: str, obj) -> None:
    EXTRAITS.mkdir(parents=True, exist_ok=True)
    (EXTRAITS / f"{nom}.json").write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True), encoding="utf-8")


# --- Comptes OFGL -----------------------------------------------------------------------------------------------------

def _duck():
    import duckdb
    return duckdb.connect()


def lire_comptes(prefixe: str, agregats: dict, col_nom: str, col_dep: str, col_type: str) -> dict:
    """siren -> {nom, dep, type, budgets, serie{clé: [montant par exercice]}} : somme des budgets publiés par SIREN."""
    par_lib = {v: k for k, v in agregats.items()}
    con = _duck()
    out = {}
    for i, annee in enumerate(ANNEES):
        p = BRUT / f"{prefixe}_{annee}.parquet"
        if not p.exists():
            continue
        lignes = con.execute(f"""select siren, agregat, sum(cast(round(montant * 100) as hugeint)) m,
                                 count(distinct ident) nb,
                                 max({col_nom}) nom, max({col_dep}) dep, max({col_type}) typ
                                 from read_parquet('{p}') where siren is not null and montant is not null
                                 group by siren, agregat order by siren, agregat""").fetchall()
        for s, agregat, m, nb, nom, dep, typ in lignes:
            cle = par_lib.get(agregat)
            if cle is None or not sirene.siren_valide(s):
                continue
            e = out.setdefault(s, {"nom": None, "dep": None, "type": None, "budgets": None,
                                   "serie": {k: [None] * len(ANNEES) for k in agregats}})
            e["serie"][cle][i] = arrondi_centimes(int(m))
            e.update(nom=propre(nom), dep=propre(dep), type=propre(typ))  # dernier exercice lu
            if cle == "depenses_totales_hors_remb":
                e["budgets"] = nb
    return dict(sorted(out.items()))


def dernier_montant(serie: list):
    """(exercice, montant) du dernier exercice publié, limité aux deux derniers exercices de la période."""
    for i in (len(ANNEES) - 1, len(ANNEES) - 2):
        if serie[i] is not None:
            return ANNEES[i], serie[i]
    return None, None


# --- Production -------------------------------------------------------------------------------------------------------

def rattacher_syndicats(banatic: dict, g: dict) -> tuple[dict, dict]:
    """commune -> {siren du syndicat: via} ; syndicat -> ensemble des communes rattachées."""
    groupements = banatic["groupements"]
    syndicats = {s for s, v in groupements.items() if v["nature"] in NATURES_SYNDICATS}
    membres_de = defaultdict(set)  # membre -> syndicats dont il est membre
    for s in syndicats:
        for m, _cat in groupements[s]["membres"]:
            membres_de[m].add(s)
    par_commune = defaultdict(dict)
    ordre = {"commune": 0, "epci": 1, "syndicat": 2}

    def ajouter(code, s, via):
        if s not in par_commune[code] or ordre[via] < ordre[par_commune[code][s]]:
            par_commune[code][s] = via

    for code, c in g["communes"].items():
        directs = set(membres_de.get(c.get("siren"), ()))
        par_epci = set(membres_de.get(c.get("epci"), ())) if c.get("epci") else set()
        for s in directs:
            ajouter(code, s, "commune")
        for s in par_epci:
            ajouter(code, s, "epci")
        for s in directs | par_epci:
            for s2 in membres_de.get(s, ()):
                ajouter(code, s2, "syndicat")
    communes_de = defaultdict(set)
    for code, d in par_commune.items():
        for s in d:
            communes_de[s].add(code)
    return par_commune, communes_de


def entete(source_cles: list[str], annees_txt: str, date: str, licence: str = "Licence Ouverte 2.0") -> dict:
    return {"millesime": f"{annees_txt} ; sources collectées au {date}",
            "source": " ; ".join(SOURCES[k]["page"] for k in source_cles),
            "licence": licence}


def produire() -> dict:
    g = geographie()
    date = date_sources("collectivites")
    banatic = lire_extrait("banatic")
    aom_x = lire_extrait("aom")
    sispea = lire_extrait("sispea")
    sieges = lire_extrait("sieges_ccas")
    cj = lire_extrait("categories_juridiques")
    from local import objet_publiable  # lecture seule : filtre des textes libres

    non_nommes = defaultdict(int)

    def nom_publie(siren, nom, bloc):
        if nommable(cj.get(siren)):
            return nom or None
        non_nommes[bloc] += 1
        return None

    deps = sorted(g["deps"])
    communes_dep = defaultdict(list)
    for code in sorted(g["communes"]):
        communes_dep[g["communes"][code]["departement"]].append(code)
    masque = defaultdict(int)

    def marquer(code, bloc):
        masque[code] |= 1 << BLOCS.index(bloc)

    for d in ("syndicats", "ccas", "mobilite", "eau"):
        if (SORTIE / d).exists():
            shutil.rmtree(SORTIE / d)

    # ---- Syndicats ------------------------------------------------------------------------------------------------
    comptes_s = lire_comptes("ofgl_syndicats", AGREGATS_SYNDICATS, "synd_name", "dep_current_code", "categorie_synd")
    par_commune, communes_de = rattacher_syndicats(banatic, g)
    gb = banatic["groupements"]
    syndicats_banatic = {s for s, v in gb.items() if v["nature"] in NATURES_SYNDICATS}
    cles_s = list(AGREGATS_SYNDICATS)

    def fiche_syndicat(s: str) -> dict:
        b, c = gb.get(s) if s in syndicats_banatic else None, comptes_s.get(s)
        categorie = CATEGORIES_SYNDICATS.get(c["type"], "syndicat") if c else "syndicat"
        f = {"nom": nom_publie(s, (b or {}).get("nom") or (c or {}).get("nom"), "syndicats"),
             "nature": b["nature"] if b else None, "categorie": categorie,
             "competences": b["competences"] if b else None,
             "a_la_carte": b["a_la_carte"] if b else None,
             "population": b["population"] if b else None,
             "membres": len(b["membres"]) if b else None,
             "departement": (c["dep"] if c else None) or (b["departement"] if b else None),
             "perimetre": "banatic" if b else None,
             "comptes": bool(c), "budgets": c["budgets"] if c else None,
             "serie": c["serie"] if c else None, "eur_hab": None, "eur_hab_exercice": None}
        if b and c:
            an, m = dernier_montant(c["serie"]["depenses_totales_hors_remb"])
            v = par_habitant(m, b["population"])
            if v is not None:
                f["eur_hab"], f["eur_hab_exercice"] = v, an
        return f

    tous_syndicats = sorted(syndicats_banatic | set(comptes_s))
    non_rattaches_dep = defaultdict(list)
    departementaux = defaultdict(list)
    for s in tous_syndicats:
        if communes_de.get(s):
            continue
        c = comptes_s.get(s)
        dep = (c["dep"] if c else None) or gb.get(s, {}).get("departement")
        if dep not in g["deps"]:
            dep = None
        if c and CATEGORIES_SYNDICATS.get(c["type"]) == "mdph" and dep:
            departementaux[dep].append(s)
        else:
            motif = ("absent_de_banatic" if s not in syndicats_banatic else "membres_hors_communes")
            non_rattaches_dep[dep or "hors_departement"].append([s, motif])

    ent_s = entete(["ofgl_syndicats", "banatic"], "Comptes 2018 à 2025, périmètres BANATIC", date)
    bilan_s = {"fichiers": 0, "rattaches": 0}
    for dep in deps:
        liste = {code: sorted(([s, via] for s, via in par_commune.get(code, {}).items()))
                 for code in communes_dep[dep]}
        sir = sorted({s for l in liste.values() for s, _ in l} | set(departementaux.get(dep, []))
                     | {s for s, _ in non_rattaches_dep.get(dep, [])})
        for code, l in liste.items():
            if l:
                marquer(code, "syndicats")
            if departementaux.get(dep):
                marquer(code, "organismes_departementaux")
        dump(SORTIE / "syndicats" / f"{dep}.json", {
            **ent_s, "departement": {"code": dep, "nom": g["deps"][dep]}, "annees": ANNEES, "colonnes": cles_s,
            "unite": "euros", "competences": "index.json (competences[i])",
            "syndicats": {s: fiche_syndicat(s) for s in sir},
            "organismes_departementaux": sorted(departementaux.get(dep, [])),
            "non_rattaches": sorted(non_rattaches_dep.get(dep, [])),
            "communes": liste,
        })
        bilan_s["fichiers"] += 1
    hors_s = {s: {**fiche_syndicat(s), "motif": motif}
              for s, motif in sorted(non_rattaches_dep.get("hors_departement", []))}

    def totaux(comptes: dict, cles: list[str], categorie_de) -> dict:
        t = defaultdict(lambda: {"organismes": [0] * len(ANNEES), **{k: [None] * len(ANNEES) for k in cles}})
        for s, c in comptes.items():
            cat = categorie_de(c)
            for i in range(len(ANNEES)):
                if c["serie"]["depenses_totales_hors_remb"][i] is None:
                    continue
                t[cat]["organismes"][i] += 1
                for k in cles:
                    v = c["serie"][k][i]
                    if v is not None:
                        t[cat][k][i] = (t[cat][k][i] or 0) + v
        return {k: t[k] for k in sorted(t)}

    totaux_s = totaux(comptes_s, cles_s, lambda c: CATEGORIES_SYNDICATS.get(c["type"], "syndicat"))

    # ---- CCAS et CIAS ---------------------------------------------------------------------------------------------
    comptes_c = lire_comptes("ofgl_ccas", AGREGATS_CCAS, "nom_ccas", "code_dep", "type")
    cles_c = list(AGREGATS_CCAS)
    i_cias = banatic["competences"].index("Centre intercommunal d'action sociale")
    epci_cias = {s for s, v in gb.items() if i_cias in v["competences"]}  # intercommunalités exerçant la compétence
    ccas_dep = defaultdict(dict)       # dep -> siren -> fiche
    ccas_commune = defaultdict(list)   # insee -> [siren]
    ccas_non_rattaches = defaultdict(list)
    for s, c in comptes_c.items():
        siege = commune_de(sieges[s]) if sieges.get(s) else None
        commune = g["communes"].get(siege) if siege else None
        typ = "cias" if c["type"] == "CIAS" else "ccas"
        f = {"nom": nom_publie(s, c["nom"], "ccas"), "type": typ, "commune_siege": siege if commune else None,
             "rattachement": None, "epci": None, "competence_cias_banatic": None, "population": None,
             "budgets": c["budgets"], "serie": c["serie"],
             "eur_hab": None, "eur_hab_exercice": None}
        cibles = []
        if commune and typ == "ccas":
            f["rattachement"], f["population"], cibles = "commune_siege", commune.get("population"), [siege]
        elif commune and commune.get("epci") in g["epci"] and (
                commune["epci"] in epci_cias or gb.get(commune["epci"], {}).get("nature") in ("CC", "CA", "CU")):
            e = g["epci"][commune["epci"]]
            f.update(rattachement="epci_de_la_commune_siege", epci=commune["epci"], population=e.get("population"),
                     competence_cias_banatic=commune["epci"] in epci_cias)
            cibles = e["communes"]
        an, m = dernier_montant(c["serie"]["depenses_totales_hors_remb"])
        v = par_habitant(m, f["population"])
        if v is not None:
            f["eur_hab"], f["eur_hab_exercice"] = v, an
        if not cibles:
            dep = c["dep"] if c["dep"] in g["deps"] else "hors_departement"
            ccas_non_rattaches[dep].append(s)
            ccas_dep[dep][s] = f
        for code in cibles:
            ccas_commune[code].append(s)
            ccas_dep[g["communes"][code]["departement"]][s] = f
            marquer(code, typ)
    ent_c = entete(["ofgl_ccas", "sirene"], "Comptes 2018 à 2025", date)
    for dep in deps:
        dump(SORTIE / "ccas" / f"{dep}.json", {
            **ent_c, "departement": {"code": dep, "nom": g["deps"][dep]}, "annees": ANNEES, "colonnes": cles_c,
            "unite": "euros", "population_source": "geo.api.gouv.fr (local/geo/), population municipale en vigueur",
            "centres": dict(sorted(ccas_dep.get(dep, {}).items())),
            "non_rattaches": sorted(ccas_non_rattaches.get(dep, [])),
            "communes": {code: sorted(ccas_commune[code]) for code in communes_dep[dep] if ccas_commune.get(code)},
        })
    totaux_c = totaux(comptes_c, cles_c, lambda c: "cias" if c["type"] == "CIAS" else "ccas")

    # ---- Mobilité ---------------------------------------------------------------------------------------------------
    periodes = defaultdict(list)
    with (BRUT / SOURCES["urssaf_vm"]["fichier"]).open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            code = commune_de(r["code_commune"])
            if propre(r["date_debut"]):
                periodes[code].append((propre(r["date_debut"]), propre(r["date_fin"]), nombre(r["taux_vm"]),
                                       nombre(r["taux_vma"]), nombre(r["taux_vmr"])))
    ent_m = entete(["cerema_aom", "urssaf_vm"], "AOM au 1er janvier 2026, taux en vigueur au 1er janvier 2026", date,
                   licence="ODbL 1.0")
    odbl = {"licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
            "mention": "Contient des données de l'Urssaf (table_taux_vmrr) et du Cerema (base des AOM), mises à "
                       "disposition sous licence ODbL 1.0.",
            "partage_a_l_identique": "Ce fichier est une base de données dérivée : il est mis à disposition sous la "
                                     "même licence ODbL 1.0 (mention de la source, partage à l'identique, pas de "
                                     "restriction technique)."}
    ecarts_vm = {"communes_comparees": 0, "ecarts": 0, "exemples": []}
    aom_fichiers, communes_avec_taux = defaultdict(set), 0
    aom_sans_comptes = set()

    def lien_comptes(s: str, forme: str):
        if s in g["epci"]:
            return {"vue": "local_budget_epci", "fichier": f"local/budgets/epci/{g['epci'][s]['departement_siege']}.json"}
        if s in g["regions"]:
            return {"vue": "local_budget_region", "fichier": "local/budgets/regions.json"}
        if s in g["siren_commune"]:
            return {"vue": "local_budget_commune",
                    "fichier": f"local/budgets/communes/{code_dep(g['siren_commune'][s])}.json"}
        if s in comptes_s and comptes_s[s]["dep"] in g["deps"]:
            return {"vue": "local_satellites_syndicats", "fichier": f"local_satellites/syndicats/{comptes_s[s]['dep']}.json"}
        aom_sans_comptes.add(s)
        return None

    for dep in deps:
        lignes, sru, vus = {}, [], set()
        for code in communes_dep[dep]:
            c = aom_x["communes"].get(code)
            cours, suivant = taux_en_vigueur(periodes.get(code, []))
            if not c and not cours and not suivant:
                continue
            a = c["aom"] if c else None
            if a:
                vus.add(a)
                marquer(code, "aom")
            if cours:
                marquer(code, "versement_mobilite")
                communes_avec_taux += 1
            nom_sru = c["sm_sru"] if c else None
            if nom_sru and nom_sru not in sru:
                sru.append(nom_sru)
            if c and c["vm_cerema"] is not None and cours and cours[2] is not None:
                ecarts_vm["communes_comparees"] += 1
                if abs(c["vm_cerema"] - cours[2]) > 1e-9:
                    ecarts_vm["ecarts"] += 1
                    if len(ecarts_vm["exemples"]) < 10:
                        ecarts_vm["exemples"].append({"commune": code, "urssaf": cours[2], "cerema": c["vm_cerema"]})
            lignes[code] = [a, cours[2] if cours else None, cours[3] if cours else None, cours[4] if cours else None,
                            cours[0] if cours else None, sru.index(nom_sru) if nom_sru else None,
                            [suivant[0], suivant[2], suivant[3], suivant[4]] if suivant else None]
        fiches = {}
        for s in sorted(vus):
            a = aom_x["aom"].get(s)
            exemple = next(c for c in aom_x["communes"].values() if c["aom"] == s) if not a else None
            nom = a["nom"] if a else exemple["aom_nom"]
            forme = a["forme"] if a else exemple["aom_forme"]
            fiches[s] = {"nom": nom_publie(s, nom, "aom"), "forme": forme or None,
                         "population": a["population"] if a else None,
                         "communes": a["nb_communes"] if a else None,
                         "vm_taux_max_cerema": a["vm_taux_max"] if a else None,
                         "comptes": lien_comptes(s, forme),
                         "versement_mobilite_eur": comptes_s[s]["serie"]["versement_mobilite"] if s in comptes_s else None}
            aom_fichiers[s].add(dep)
        dump(SORTIE / "mobilite" / f"{dep}.json", {
            **ent_m, **odbl, "departement": {"code": dep, "nom": g["deps"][dep]},
            "date_reference": f"{ANNEE_AOM}-01-01", "annees": ANNEES, "unite_taux": "pourcentage de la masse salariale",
            "colonnes": ["aom", "taux_vm", "taux_vma", "taux_vmr", "date_debut", "syndicat_sru", "periode_suivante"],
            "colonnes_periode_suivante": ["date_debut", "taux_vm", "taux_vma", "taux_vmr"],
            "syndicats_sru": sru, "aom": fiches, "communes": lignes,
        })

    # ---- Eau et assainissement ------------------------------------------------------------------------------------
    # Une commune est rattachée à la collectivité organisatrice (jamais à une entité de gestion précise : SISPEA ne
    # publie pas les communes de chaque entité) ; la collectivité porte la liste de ses entités de gestion.
    membres_syndicat = defaultdict(dict)  # syndicat -> commune -> rattachement
    for code, d in par_commune.items():
        for s, via in d.items():
            if via in ("commune", "epci"):
                membres_syndicat[s][code] = "syndicat_via_commune" if via == "commune" else "syndicat_via_epci"
    collectivites = {}                  # clé -> fiche
    cibles_coll = {}                    # clé -> {commune: rattachement}
    bilan_eau = {k: {"entites": 0, "avec_prix": 0 if SISPEA_INDICATEURS[c][1] else None, "rattachees": 0}
                 for c, k in SISPEA_COMPETENCES.items()}
    cles_eau = ["competence", "entite", "mode_gestion", "statut_operateur", "missions", "population_desservie",
                "prix_m3_ttc", "statut_saisie", "communes_adherentes"]
    services = {}
    for ident, sv in sispea["services"].items():
        s = sv["siren"]
        cle = s or f"sispea{sv['collectivite_id']}"
        if cle not in collectivites:
            cibles = {}
            if sv["insee"] in g["communes"]:
                cibles = {sv["insee"]: "commune"}
            elif s in g["siren_commune"]:
                cibles = {g["siren_commune"][s]: "commune"}
            elif s in g["epci"]:
                cibles = {code: "epci" for code in g["epci"][s]["communes"]}
            elif s in membres_syndicat:
                cibles = dict(membres_syndicat[s])
            est_commune = bool(cibles) and set(cibles.values()) == {"commune"}
            dep = sv["departement_siege"][-2:] if sv["departement_siege"][:1] == "0" else sv["departement_siege"]
            collectivites[cle] = {
                "nom": g["communes"][next(iter(cibles))]["nom"] if est_commune else nom_publie(s, sv["collectivite"], "eau"),
                "type": sv["type_collectivite"], "siren": s, "comptes": lien_comptes(s, "") if s else None,
                "departement_siege": dep if dep in g["deps"] else None, "services": []}
            cibles_coll[cle] = cibles
        collectivites[cle]["services"].append(ident)
        services[ident] = (cle, [sv["competence"], objet_publiable(sv["entite"]) if sv["entite"] else None,
                                 sv["mode_gestion"], sv["statut_operateur"], sv["missions"], sv["population"],
                                 sv["prix_m3_ttc"], sv["statut_saisie"], sv["communes_adherentes"]])
        b = bilan_eau[sv["competence"]]
        b["entites"] += 1
        if b["avec_prix"] is not None:
            b["avec_prix"] += sv["prix_m3_ttc"] is not None
        b["rattachees"] += bool(cibles_coll[cle])
    eau_dep = defaultdict(set)          # dep -> clés de collectivités
    eau_commune = defaultdict(list)
    eau_non_rattaches = defaultdict(list)
    for cle, cibles in cibles_coll.items():
        f = collectivites[cle]
        if not cibles:
            dep = f["departement_siege"] or "hors_departement"
            eau_non_rattaches[dep].append(cle)
            eau_dep[dep].add(cle)
        competences = {services[i][1][0] for i in f["services"]}
        for code, via in cibles.items():
            eau_commune[code].append([cle, via])
            eau_dep[g["communes"][code]["departement"]].add(cle)
            for comp in competences:
                marquer(code, comp)
    ent_e = entete(["sispea", "banatic"], f"Exercice {ANNEE_EAU}", date)
    for dep in deps:
        cles = sorted(eau_dep.get(dep, ()))
        dump(SORTIE / "eau" / f"{dep}.json", {
            **ent_e, "departement": {"code": dep, "nom": g["deps"][dep]}, "exercice": ANNEE_EAU,
            "colonnes": cles_eau, "unite_prix": "euros TTC par m³, pour 120 m³",
            "collectivites": {c: {k: v for k, v in collectivites[c].items() if k != "departement_siege"} for c in cles},
            "services": {i: services[i][1] for c in cles for i in sorted(collectivites[c]["services"])},
            "non_rattaches": sorted(eau_non_rattaches.get(dep, [])),
            "communes": {code: sorted(eau_commune[code]) for code in communes_dep[dep] if eau_commune.get(code)},
        })
    hors_e = {c: {**{k: v for k, v in collectivites[c].items() if k != "departement_siege"},
                  "lignes": {i: services[i][1] for i in sorted(collectivites[c]["services"])}}
              for c in sorted(eau_non_rattaches.get("hors_departement", []))}

    # ---- Index --------------------------------------------------------------------------------------------------------
    dernier = len(ANNEES) - 1

    def part(a, b):
        return None if a is None or not b else round(a / b * 100, 1)

    t_ccas = totaux_c.get("ccas", {})
    t_synd = totaux_s.get("syndicat", {})
    couverture = {b: sum(1 for c in g["communes"] if masque.get(c, 0) >> i & 1) for i, b in enumerate(BLOCS)}
    index = {
        "millesime": f"Comptes 2018 à 2025 ; AOM et taux au 1er janvier {ANNEE_AOM} ; services d'eau {ANNEE_EAU} ; "
                     f"sources collectées au {date}",
        "source": "pipeline/local_satellites.py (voir `sources` et chaque fichier)",
        "licence": "Licence Ouverte 2.0, sauf mobilite/<dep>.json : ODbL 1.0 (Urssaf, Cerema)",
        "licences": {"syndicats": "Licence Ouverte 2.0", "ccas": "Licence Ouverte 2.0", "eau": "Licence Ouverte 2.0",
                     "mobilite": {"licence": "ODbL 1.0", **odbl}},
        "blocs": BLOCS,
        "format": "communes.<insee> = masque de bits : le bloc blocs[i] est disponible si (valeur >> i) & 1",
        "fichiers": {"syndicats": "syndicats/<dep>.json", "organismes_departementaux": "syndicats/<dep>.json",
                     "ccas": "ccas/<dep>.json", "cias": "ccas/<dep>.json", "aom": "mobilite/<dep>.json",
                     "versement_mobilite": "mobilite/<dep>.json", "eau_potable": "eau/<dep>.json",
                     "assainissement_collectif": "eau/<dep>.json", "assainissement_non_collectif": "eau/<dep>.json"},
        "annees": ANNEES,
        "departements": deps,
        "competences": banatic["competences"],
        "natures": NATURES_LIBELLES,
        "definitions": DEFINITIONS,
        "flux_croises": FLUX_CROISES,
        "limites": LIMITES,
        "couverture": {"communes": len(g["communes"]), "par_bloc": couverture},
        "totaux": {
            "note": "sommes par exercice des organismes publiés par l'OFGL, non consolidées : les contributions entre "
                    "organismes et avec les communes et intercommunalités ne sont pas retirées ; ces totaux ne "
                    "s'ajoutent ni entre eux ni aux budgets locaux",
            "syndicats": totaux_s, "ccas_cias": totaux_c,
        },
        "reperes": {
            "exercice": ANNEES[dernier],
            "syndicats_avec_comptes": t_synd.get("organismes", [None] * len(ANNEES))[dernier],
            "syndicats_banatic": len(syndicats_banatic),
            "syndicats_sans_commune_rattachee": sum(len(v) for v in non_rattaches_dep.values()),
            "ccas_avec_comptes": t_ccas.get("organismes", [None] * len(ANNEES))[dernier],
            "ccas_part_participations_communes_pct": part(
                (t_ccas.get("participations_communes") or [None] * len(ANNEES))[dernier],
                (t_ccas.get("depenses_fonctionnement") or [None] * len(ANNEES))[dernier]),
            "syndicats_part_subventions_participations_pct": part(
                (t_synd.get("subventions_participations_recues") or [None] * len(ANNEES))[dernier],
                (t_synd.get("depenses_totales_hors_remb") or [None] * len(ANNEES))[dernier]),
            "aom": len(aom_fichiers), "aom_sans_comptes_publies": sorted(aom_sans_comptes & set(aom_fichiers)),
            "communes_avec_taux_vm": communes_avec_taux,
            "services_eau": bilan_eau,
        },
        "hors_departement": {
            "note": "organismes sans commune rattachée dont le département publié n'est pas dans le référentiel "
                    "(local/geo/) : publiés ici, dans aucun fichier départemental",
            "syndicats": hors_s,
            "ccas": {s: ccas_dep["hors_departement"][s] for s in sorted(ccas_non_rattaches.get("hors_departement", []))},
            "eau": hors_e},
        "ecarts": {"versement_mobilite_urssaf_cerema": {
            **ecarts_vm, "lecture_ecart": "taux_vm de l'Urssaf en vigueur au 1er janvier 2026 comparé à la colonne "
                                          "« VM (URSAFF 2026) » du Cerema ; le fichier publie le taux de l'Urssaf, "
                                          "l'écart est signalé sans être tranché"}},
        "non_nommes": {"regle": "organisme dont la catégorie juridique SIRENE n'est pas celle d'une personne morale "
                                "ou est inconnue : `nom` null, montants conservés",
                       "par_bloc": dict(sorted(non_nommes.items())),
                       "operateurs_eau": "le nom de l'opérateur d'un service d'eau n'est pas repris (aucun SIREN "
                                         "publié) ; `statut_operateur` reste publié"},
        "sources": [{"id": k, **{c: v[c] for c in ("titre", "page", "url", "producteur", "millesime", "licence",
                                                     "verdict")}} for k, v in SOURCES.items()],
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "communes": {c: masque.get(c, 0) for c in sorted(g["communes"])},
    }
    dump(SORTIE / "index.json", index)
    return index


# --- Collecte ---------------------------------------------------------------------------------------------------------

def telecharger(url: str, dest: Path, params: dict | None = None, essais: int = 5) -> str:
    """Téléchargement en flux avec reprises espacées. Un refus (401, 403, 429, 451) est noté, jamais contourné."""
    import requests
    derniere = ""
    for i in range(essais):
        try:
            with requests.get(url, params=params, timeout=(30, 600), headers=ENTETE_HTTP, stream=True) as r:
                if r.status_code in (401, 403, 429, 451):
                    return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
                if r.status_code in (404, 410):
                    return f"source retirée (HTTP {r.status_code})"
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as fh:
                    for bloc in r.iter_content(1 << 20):
                        fh.write(bloc)
            with tmp.open("rb") as fh:
                debut = fh.read(6)
            attendu = {".parquet": b"PAR1", ".xlsx": b"PK\x03\x04", ".ods": b"PK\x03\x04", ".7z": b"7z\xbc\xaf"}
            if dest.suffix in attendu and not debut.startswith(attendu[dest.suffix]):
                tmp.unlink()
                return "contenu inattendu (page HTML au lieu du fichier) : aucun contournement"
            from fetch import octets_annonces, remplacer_si_valide  # controle collecte/integrite.py
            remplacer_si_valide(tmp, dest, octets_attendus=octets_annonces(r))  # invalide : dest conserve
            return "ok"
        except Exception as e:  # reprise réseau
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(5 * (i + 1))
    return f"échec après {essais} essais : {derniere}"


def _odsql_liste(valeurs) -> str:
    return ", ".join('"' + v.replace('"', '\\"') + '"' for v in valeurs)


def url_stock_etablissements() -> str | None:
    import requests
    for i in range(4):
        try:
            d = requests.get(DATAGOUV_SIRENE, timeout=60, headers=ENTETE_HTTP).json()
            for r in d["resources"]:
                t = r["title"]
                if "StockEtablissement " in t and "parquet" in t.lower() and "Historique" not in t:
                    return r["url"]
            return None
        except Exception:
            time.sleep(5 * (i + 1))
    return None


def collecter_sieges(sirens: list[str]) -> dict | str:
    """SIREN -> code commune de l'établissement siège (lecture distante de deux colonnes du stock SIRENE)."""
    url = url_stock_etablissements()
    if not url:
        return "stock SIRENE des établissements introuvable"
    for i in range(4):
        try:
            con = _duck()
            con.execute("install httpfs; load httpfs; set http_timeout=120000; set http_retries=5")
            con.execute("create temp table q(siren varchar)")
            con.executemany("insert into q values (?)", [(s,) for s in sirens])
            lignes = con.execute(f"""select e.siren, min(e.codeCommuneEtablissement)
                from read_parquet('{url}') e join q using (siren)
                where e.siren between '{min(sirens)}' and '{max(sirens)}' and e.etablissementSiege
                group by e.siren order by e.siren""").fetchall()
            return {s: c for s, c in lignes if c}
        except Exception as e:
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(10 * (i + 1))
    return f"échec : {derniere}"


def collecter_categories(sirens: set[str]) -> dict:
    """SIREN -> catégorie juridique (stock SIRENE des unités légales partagé avec pipeline/local.py)."""
    import local
    return {s: cj for s, (cj, _nom) in sorted(local.sirene_cj(sirens).items())}


def collecter(forcer: bool = False) -> dict:
    BRUT.mkdir(parents=True, exist_ok=True)
    etat = {}

    def obtenir(cle: str, dest: Path, url: str, params: dict | None = None):
        if dest.exists() and dest.stat().st_size > 0 and not forcer:
            etat[cle] = "présent"
        else:
            etat[cle] = telecharger(url, dest, params)
        print(f"{cle}: {etat[cle]}", flush=True)
        return etat[cle] in ("ok", "présent")

    for annee in ANNEES:
        obtenir(f"ofgl_syndicats_{annee}", BRUT / f"ofgl_syndicats_{annee}.parquet", SOURCES["ofgl_syndicats"]["url"], {
            "select": "siren,synd_name,categorie_synd,dep_current_code,ident,type_de_budget,agregat,montant",
            "where": f"year(exer)={annee} and agregat in ({_odsql_liste(AGREGATS_SYNDICATS.values())})"})
        obtenir(f"ofgl_ccas_{annee}", BRUT / f"ofgl_ccas_{annee}.parquet", SOURCES["ofgl_ccas"]["url"], {
            "select": "siren,nom_ccas,type,code_dep,ident,type_de_budget,agregat,montant",
            "where": f"year(exer)={annee} and agregat in ({_odsql_liste(AGREGATS_CCAS.values())})"})
    for cle in ("banatic", "cerema_aom", "urssaf_vm"):
        obtenir(cle, BRUT / SOURCES[cle]["fichier"], SOURCES[cle]["url"])
    for code, fiche in SISPEA_FICHES.items():
        obtenir(f"sispea_{code}", BRUT / f"sispea_{ANNEE_EAU}_{code}.7z",
                f"{OFB}/{fiche}/attachments/SISPEA_extraction_{ANNEE_EAU}_{code}.7z")

    def extrait(nom: str, fabrique):
        if (EXTRAITS / f"{nom}.json").exists() and not forcer:
            etat[f"extrait_{nom}"] = "présent"
        else:
            res = fabrique()
            if isinstance(res, str):
                etat[f"extrait_{nom}"] = res
            else:
                ecrire_extrait(nom, res)
                etat[f"extrait_{nom}"] = "ok"
        print(f"extrait_{nom}: {etat[f'extrait_{nom}']}", flush=True)

    extrait("banatic", lambda: extraire_banatic(BRUT / SOURCES["banatic"]["fichier"]))
    extrait("aom", lambda: extraire_aom(BRUT / SOURCES["cerema_aom"]["fichier"]))
    extrait("sispea", lambda: extraire_sispea(BRUT))

    def sirens_parquets(prefixe: str) -> list[str]:
        con = _duck()
        motif = str(BRUT / f"{prefixe}_*.parquet")
        return sorted(s for (s,) in con.execute(f"select distinct siren from read_parquet('{motif}')").fetchall()
                      if sirene.siren_valide(s))

    extrait("sieges_ccas", lambda: collecter_sieges(sirens_parquets("ofgl_ccas")))

    def categories():
        b, a, sp = lire_extrait("banatic"), lire_extrait("aom"), lire_extrait("sispea")
        sirens = set(sirens_parquets("ofgl_ccas")) | set(sirens_parquets("ofgl_syndicats")) | set(b["groupements"])
        sirens |= set(a["aom"]) | {c["aom"] for c in a["communes"].values() if c["aom"]}
        sirens |= {s["siren"] for s in sp["services"].values() if s["siren"]}
        return collecter_categories(sirens)

    extrait("categories_juridiques", categories)
    return etat


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true", help="retélécharger les sources et refaire les extraits")
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter(a.forcer)
    if a.etape in ("produire", "tout"):
        idx = produire()
        print(json.dumps({"couverture": idx["couverture"], "reperes": {k: v for k, v in idx["reperes"].items()
                                                                       if not isinstance(v, (list, dict))}},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
