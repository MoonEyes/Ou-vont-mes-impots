"""Agriculture : politique agricole commune par département, développement rural et cofinancements, budget de l'État.

Agrégats publiés seulement. Règle du projet pour la politique agricole commune : aucun bénéficiaire individuel, même
personne morale ; le module ne lit aucun fichier nominatif (la publication nominative de Telepac n'est pas collectée,
et une agrégation par département et par mesure serait la seule forme publiée si elle l'était un jour).

Entrées : entrepôt brut data/lake/agriculture/ (non versionné), collectées par `collecter` (collecte/collecte.py,
entrées `agriculture_*` de collecte/catalogue.json) :
    agriculture_pac_departements_2005_2009/*.csv   Agreste et ASP, aides de la PAC 2005-2009 par région et
                                                   département (bénéficiaires, montants en milliers d'euros)
    agriculture_feader_2014_2020_fr.json           Commission européenne, ESIF 2014-2020 Finance Implementation
                                                   Details, lignes France du FEADER (part UE, contrepartie nationale,
                                                   projets sélectionnés, dépenses déclarées ; cumuls par année)
    agriculture_feaga_paiements_2023_2027.json     Commission européenne, paiements du FEAGA par exercice financier
    agriculture_feader_paiements_2023_2027.json    Commission européenne, paiements du FEADER 2023-2027 (cumul)
et, en lecture seule dans site/data : realisations/<programme>.json, arbre/*_<programme>.json,
niches/programmes.json (dépenses fiscales : renvoi seulement, aucun montant recopié), ue/retours.json.
Sorties :
  site/data/agriculture/index.json                fichiers, repères, liens, sources, sources inaccessibles,
                                                  recherche préalable
  site/data/agriculture/pac_departements.json     aides PAC par département, année et type d'aide (2005-2009)
  site/data/agriculture/developpement_rural.json  FEADER 2014-2022 par programme (région) et par mesure, avec la
                                                  contrepartie nationale ; paiements FEAGA et FEADER 2023-2027
  site/data/agriculture/etat.json                 programmes 149, 206, 215, 381 (et leurs prédécesseurs), renvois

Commandes :
  python pipeline/agriculture.py collecter   # réseau, par collecte/collecte.py ; un refus 401/403/429 est noté
  python pipeline/agriculture.py produire    # sans réseau
  python pipeline/agriculture.py             # les deux

Règles :
  - une cellule « S » (secret statistique) ou vide à la source reste null, jamais 0, et la cellule secrète est listée ;
  - un total publié qui ne retombe pas sur la somme de ses lignes est publié avec son écart, jamais corrigé ;
  - les montants de sources différentes (Agreste, Commission, budget de l'État, annexe sur les relations avec l'UE)
    sont posés côte à côte, jamais additionnés ;
  - les données de la Commission sur le FEADER 2014-2020 sont des cumuls : les années ne s'additionnent pas ;
  - toute date écrite vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOMAINE = "agriculture"
BRUT = ROOT / "data" / "lake" / DOMAINE
SITE = ROOT / "site" / "data"
SORTIE = SITE / DOMAINE

LO1 = "Licence Ouverte 1.0"
CC0 = "CC0 1.0 (Commission européenne)"
COHESION = "https://cohesiondata.ec.europa.eu"

SOURCES = {
    "pac_departements": {
        "id_catalogue": "agriculture_pac_departements_2005_2009", "entrepot": "agriculture_pac_departements_2005_2009/",
        "titre": "Aides de la politique agricole commune (PAC) de 2005 à 2009 par région, département",
        "producteur": "Agreste (service statistique du ministère de l'Agriculture) et Agence de services et de paiement",
        "url": "https://static.data.gouv.fr/52/9810eab537f437b490ba43afa032a8c605e58c7edd11a8f1f24c35f003e124.csv",
        "page": "https://www.data.gouv.fr/datasets/aides-de-la-politique-agricole-commune-pac-30379066",
        "licence": LO1, "millesime": "2005 à 2009", "verdict": "réutilisable tel quel",
    },
    "feader_2014_2020": {
        "id_catalogue": "agriculture_feader_2014_2020_fr", "entrepot": "agriculture_feader_2014_2020_fr.json",
        "titre": "ESIF 2014-2020 Finance Implementation Details (lignes France, fonds FEADER)",
        "producteur": "Commission européenne (données des autorités de gestion des programmes)",
        "url": f"{COHESION}/resource/99js-gm52.json?%24limit=50000&ms=FR&fund=EAFRD",
        "page": f"{COHESION}/d/99js-gm52", "licence": CC0, "millesime": "programmation 2014-2022, situation 2014 à 2023",
        "verdict": "réutilisable tel quel",
    },
    "feaga_2023_2027": {
        "id_catalogue": "agriculture_feaga_paiements_2023_2027", "entrepot": "agriculture_feaga_paiements_2023_2027.json",
        "titre": "2023-2027 EAGF Payments", "producteur": "Commission européenne (direction générale de l'agriculture)",
        "url": f"{COHESION}/resource/qgpc-e9qr.json", "page": f"{COHESION}/d/qgpc-e9qr", "licence": CC0,
        "millesime": "exercices financiers 2023 à 2026", "verdict": "réutilisable tel quel",
    },
    "feader_2023_2027": {
        "id_catalogue": "agriculture_feader_paiements_2023_2027",
        "entrepot": "agriculture_feader_paiements_2023_2027.json",
        "titre": "2023-2027 EU Payments by MS - EAFRD", "producteur": "Commission européenne (direction générale de "
                                                                      "l'agriculture)",
        "url": f"{COHESION}/resource/7wr2-9vpr.json", "page": f"{COHESION}/d/7wr2-9vpr", "licence": CC0,
        "millesime": "programmation 2023-2027, cumul à la date de collecte", "verdict": "réutilisable tel quel",
    },
}

INACCESSIBLES = [
    {"source": "Telepac, transparence des bénéficiaires de la politique agricole commune",
     "url": "https://www.telepac.agriculture.gouv.fr/telepac/tbp/accueil/accueil.action",
     "constat": "réponse HTTP 503 « service temporairement indisponible » sur tout le site le 18/11/2026, après "
                "plusieurs essais espacés ; aucun contournement",
     "effet": "les montants par département après 2009 (premier pilier et développement rural, par mesure) ne sont "
              "pas repris ; cette publication est nominative : seule une agrégation par département et par mesure "
              "serait publiée ici"},
    {"source": "Agence de services et de paiement (asp-public.fr)", "url": "https://www.asp-public.fr/",
     "constat": "page de contrôle anti-robot (JavaScript et cookies exigés), constatée le 18/11/2026 ; non contournée",
     "effet": "aucun chiffre de paiement de l'agence n'est lu directement"},
    {"source": "budget.gouv.fr (documents budgétaires de la mission Agriculture)", "url": "https://www.budget.gouv.fr/",
     "constat": "page de contrôle anti-robot constatée le 18/11/2026 ; non contournée",
     "effet": "les crédits de l'État sont lus dans realisations/ et arbre/, produits à partir de data.economie.gouv.fr"},
    {"source": "Agreste, comptes de l'agriculture par département (subventions d'exploitation)",
     "url": "https://agreste.agriculture.gouv.fr/agreste-web/disaron/Comptes+de+l%2527agriculture/"
            "d1cbdec3-c6ec-4a23-bf1d-92b0851d70fd/search/",
     "constat": "séries consultables dans une application interactive, sans fichier de données stable à télécharger",
     "effet": "aucune série départementale récente des subventions d'exploitation n'est reprise"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "verdict": "aucun jeu ouvert récent de montants PAC agrégés par département ; reprise de la série Agreste et ASP "
               "2005-2009 (seule série départementale par type d'aide trouvée en fichier), des données de la "
               "Commission européenne pour le développement rural et les paiements 2023-2027, et des fichiers "
               "budgétaires déjà produits par le dépôt",
    "trouvailles": [
        {"nom": "Agreste et ASP, aides de la PAC 2005-2009 par région et département (data.gouv.fr)",
         "classement": "réutilisable tel quel", "licence": LO1, "derniere_mise_a_jour": "2014-01-06"},
        {"nom": "Commission européenne, cohesiondata.ec.europa.eu (FEADER 2014-2020 par programme, paiements "
                "FEAGA et FEADER 2023-2027)", "classement": "réutilisable tel quel", "licence": CC0,
         "derniere_mise_a_jour": "2026-11-17"},
        {"nom": "ASP, aides perçues par les personnes morales au titre de la PAC 2010-2012 (data.gouv.fr)",
         "classement": "écarté", "licence": LO1, "derniere_mise_a_jour": "2014-03-20",
         "motif": "fichier nominatif : la règle du projet exclut tout bénéficiaire individuel de la PAC"},
        {"nom": "farmsubsidy.org (dépôts okfde/farmsubsidy-store, simonwoerpel/farmsubsidy.org-next)",
         "classement": "inspiration", "licence": "MIT (code) ; données sous accès authentifié",
         "derniere_mise_a_jour": "2026-09-03",
         "motif": "données par bénéficiaire, accès authentifié : seule la chaîne de traitement inspire"},
        {"nom": "openspending/farmsubsidy-scrapers", "classement": "inspiration", "licence": "non précisée",
         "derniere_mise_a_jour": "2026-10-03", "motif": "collecteurs anciens par pays, aucun pour la publication "
                                                        "française actuelle"},
        {"nom": "Aides Agri (aides-agri.beta.gouv.fr, data.gouv.fr)", "classement": "écarté",
         "licence": "Licence Ouverte 2.0", "derniere_mise_a_jour": "2026-11-16",
         "motif": "catalogue de dispositifs d'aide, sans montants versés"},
        {"nom": "Ministère de l'Agriculture, subventions de plus de 23 000 euros (data.gouv.fr)",
         "classement": "à adapter", "licence": "non précisée (other-pd)", "derniere_mise_a_jour": "2026-07-08",
         "motif": "subventions aux associations et organismes privés, hors PAC : relève de l'axe des subventions"},
    ],
}

# --- Aides de la PAC 2005-2009 (Agreste, ASP) -------------------------------------------------------------------------

# libellé de la source (avant « : ») -> (identifiant, libellé, pilier)
AIDES = {
    "Droits à paiement unique DPU": ("dpu", "Droits à paiement unique", "premier_pilier"),
    "Aides couplées aux surfaces": ("aides_couplees_surfaces", "Aides couplées aux surfaces", "premier_pilier"),
    "Prime au maintien du troupeau de vaches allaitantes (PMTVA)":
        ("pmtva", "Prime au maintien du troupeau de vaches allaitantes", "premier_pilier"),
    "Prime à l'abattage (PAB)": ("pab", "Prime à l'abattage", "premier_pilier"),
    "Prime à la brebis et à la chèvre (PBC)": ("pbc", "Prime à la brebis et à la chèvre", "premier_pilier"),
    "Prime à la brebis (PB)": ("pb", "Prime à la brebis", "premier_pilier"),
    "Aide directe laitière (ADL)": ("adl", "Aide directe laitière", "premier_pilier"),
    "Prime spéciale aux bovins mâles": ("psbm", "Prime spéciale aux bovins mâles", "premier_pilier"),
    "Prime herbagère agroenvironnementale (PHAE)":
        ("phae", "Prime herbagère agroenvironnementale", "developpement_rural"),
    "Mesures agroenvironnementales (MAE) hors PHAE":
        ("mae_hors_phae", "Mesures agroenvironnementales hors prime herbagère", "developpement_rural"),
    "Indemnité compensatoire de handicaps naturels (ICHN)":
        ("ichn", "Indemnité compensatoire de handicaps naturels", "developpement_rural"),
    "Plan de modernisation des bâtiments d'élevage (PMBE)":
        ("pmbe", "Plan de modernisation des bâtiments d'élevage", "developpement_rural"),
    "Plan végétal pour l'environnement (PVE)": ("pve", "Plan végétal pour l'environnement", "developpement_rural"),
}
PILIERS = {
    "premier_pilier": "aides directes du premier pilier (Fonds européen agricole de garantie)",
    "developpement_rural": "aides du développement rural (second pilier : Fonds européen agricole pour le "
                           "développement rural et contrepartie nationale, non séparés dans cette source)",
}


def indicateur(libelle: str) -> tuple[str, str]:
    """Libellé d'indicateur de la source (après « : ») -> (identifiant, unité)."""
    t = libelle.strip()
    if t == "nombre de bénéficiaires":
        return "beneficiaires", "exploitations"
    if t == "animaux primés":
        return "animaux_primes", "animaux"
    if t.startswith("quotas déclarés"):
        return "quotas_t", "tonnes"
    if not t.endswith("(1000 euros)"):
        raise SystemExit(f"indicateur inconnu dans le fichier Agreste : {t!r} (mettre à jour pipeline/agriculture.py)")
    corps = t.removesuffix("(1000 euros)").strip()
    table = {
        "montant": "montant", "montant PMTVA": "montant", "montant y c. flexibilité": "montant",
        "montant des DPU": "montant", "montant total": "montant_total",
        "montant PBC": "montant_prime_de_base", "montant PB": "montant_prime_de_base",
        "montant PSBM": "montant_prime_de_base",
        "montant prime supplémentaire": "montant_prime_supplementaire",
        "montant flexibilité (paiement additionnel)": "montant_paiement_additionnel",
        "complément extensification": "complement_extensification",
        "flexibilité (veau label)": "flexibilite_veau_label",
        "montant des aides aux produits laitiers": "montant_aides_produits_laitiers",
        "montant paiement supplémentaire": "montant_paiement_supplementaire",
    }
    if corps not in table:
        raise SystemExit(f"indicateur de montant inconnu : {t!r} (mettre à jour pipeline/agriculture.py)")
    return table[corps] + "_eur", "euros"


def valeur(cellule: str):
    """(valeur, secret) : nombre de la source, ou None ; secret vrai pour « S » (secret statistique). Jamais 0 à la
    place d'une absence."""
    c = (cellule or "").strip().replace(" ", "").replace(" ", "")
    if c.upper() == "S":
        return None, True
    if not c:
        return None, False
    try:
        x = float(c.replace(",", "."))
    except ValueError:
        return None, False
    return (int(x) if x == int(x) else x), False


def territoire(libelle: str) -> tuple[str, str, str]:
    """« 02 - Aisne » -> (niveau, code, nom). Niveaux : france, ensemble, region, departement."""
    code, _, nom = libelle.partition(" - ")
    code, nom = code.strip(), nom.strip()
    if code == "FR":
        return "france", "FR", nom
    if code in ("DOM", "FR métro"):
        return "ensemble", "DOM" if code == "DOM" else "FR_METRO", nom
    if nom.startswith("Région"):
        return "region", code, nom
    return "departement", code, nom


def fichier_pac() -> Path:
    fichiers = sorted((BRUT / SOURCES["pac_departements"]["entrepot"]).glob("*.csv"))
    if not fichiers:
        raise SystemExit("aucun CSV dans data/lake/agriculture/agriculture_pac_departements_2005_2009/ : lancer "
                         "`python pipeline/agriculture.py collecter`")
    return fichiers[-1]


def lire_pac(chemin: Path) -> dict:
    """Tableau Agreste : en-têtes (années sur la ligne « Période », indicateurs « aide : indicateur »), puis une ligne
    par territoire. Rend colonnes, territoires (dans l'ordre de la source), valeurs et cellules secrètes."""
    lignes = list(csv.reader(chemin.read_text(encoding="latin-1").splitlines(), delimiter=";"))
    i_ind = next(i for i, l in enumerate(lignes) if l and l[0].strip() == "Géographie")
    i_an = next(i for i in range(i_ind) if lignes[i][1:] and re.fullmatch(r"\d{4}", (lignes[i][1] or "").strip()))
    annees, an = [], None
    for j in range(1, len(lignes[i_ind])):
        c = lignes[i_an][j].strip() if j < len(lignes[i_an]) else ""
        an = int(c) if c else an
        annees.append(an)
    colonnes = []
    for j, lib in enumerate(lignes[i_ind][1:], start=1):
        if not lib.strip():
            continue
        aide_src, _, ind_src = lib.partition(" : ")
        if aide_src.strip() not in AIDES:
            raise SystemExit(f"aide inconnue dans le fichier Agreste : {aide_src!r}")
        ind, unite = indicateur(ind_src)
        colonnes.append({"j": j, "annee": annees[j - 1], "aide": AIDES[aide_src.strip()][0], "indicateur": ind,
                         "unite": unite, "libelle_source": lib.strip()})
    territoires, region = [], None
    for l in lignes[i_ind + 1:]:
        if not l or not l[0].strip() or l[0].startswith("Source"):
            continue
        niveau, code, nom = territoire(l[0])
        if niveau == "region":
            region = code
        elif niveau != "departement":
            region = None
        vals, secrets = [], []
        for c in colonnes:
            v, s = valeur(l[c["j"]] if c["j"] < len(l) else "")
            if v is not None and c["unite"] == "euros":
                v = int(round(v * 1000))   # milliers d'euros -> euros
            vals.append(v)
            if s:
                secrets.append(c)
        territoires.append({"niveau": niveau, "code": code, "nom": nom, "region": region if niveau == "departement"
                            else None, "valeurs": vals, "secrets": secrets})
    return {"colonnes": colonnes, "territoires": territoires}


def montant_retenu(indicateurs: set[str]) -> str | None:
    """Montant qui représente l'aide dans une année : le total publié, sinon l'unique montant publié."""
    if "montant_total_eur" in indicateurs:
        return "montant_total_eur"
    if "montant_eur" in indicateurs:
        return "montant_eur"
    return None


def controles_pac(pac: dict) -> dict:
    """Région contre somme de ses départements, France métropolitaine contre somme des régions métropolitaines :
    écarts publiés tels quels (les cellules secrètes rendent la somme incomplète : écart non calculé)."""
    cols, terr = pac["colonnes"], pac["territoires"]
    ecarts, complets, incomplets = [], 0, 0

    def comparer(parent, enfants, objet):
        nonlocal complets, incomplets
        for k, c in enumerate(cols):
            v = parent["valeurs"][k]
            vals = [e["valeurs"][k] for e in enfants]
            if v is None or not vals:
                continue
            if any(x is None for x in vals):
                if any(c is s for e in enfants for s in e["secrets"]):
                    incomplets += 1
                continue
            complets += 1
            somme = sum(vals)
            if abs(somme - v) > (1000 if c["unite"] == "euros" else 0):   # arrondi au millier d'euros à la source
                ecarts.append({"objet": objet, "niveau": parent["niveau"], "territoire": parent["code"],
                               "annee": c["annee"], "aide": c["aide"],
                               "indicateur": c["indicateur"], "valeur_publiee": v, "somme_des_lignes": somme,
                               "ecart": somme - v})
    for r in (t for t in terr if t["niveau"] == "region"):
        comparer(r, [t for t in terr if t["region"] == r["code"] and t["niveau"] == "departement"],
                 "region_contre_departements")
    metro = next((t for t in terr if t["code"] == "FR_METRO"), None)
    if metro:
        i = terr.index(metro)
        regions = [t for t in terr[i + 1:] if t["niveau"] == "region"]
        comparer(metro, regions, "france_metropolitaine_contre_regions")
    return {"comparaisons_completes": complets, "comparaisons_avec_cellule_secrete": incomplets,
            "ecarts": ecarts,
            "regle": "un total publié qui ne retombe pas sur la somme de ses lignes (au millier d'euros près, "
                     "arrondi de la source) est publié avec son écart, jamais corrigé ; une somme qui contient une "
                     "cellule secrète n'est pas comparée"}


def doc_pac(pac: dict, date: str) -> dict:
    cols = pac["colonnes"]
    annees = sorted({c["annee"] for c in cols})
    secretes = []
    territoires = []
    for t in pac["territoires"]:
        par_annee = {}
        for a in annees:
            idx = {c["aide"]: {} for c in cols if c["annee"] == a}
            for k, c in enumerate(cols):
                if c["annee"] == a:
                    idx[c["aide"]][c["indicateur"]] = k
            retenus, manquantes = {}, []
            for aide, inds in sorted(idx.items()):
                m = montant_retenu(set(inds))
                v = t["valeurs"][inds[m]] if m else None
                if v is None:
                    manquantes.append(aide)
                else:
                    retenus[aide] = v
            par_annee[str(a)] = {
                "montants_retenus_eur": retenus,
                "somme_montants_retenus_eur": sum(retenus.values()) if retenus else None,
                "aides_sans_montant": manquantes,
            }
        for c in t["secrets"]:
            secretes.append({"niveau": t["niveau"], "territoire": t["code"], "annee": c["annee"], "aide": c["aide"],
                             "indicateur": c["indicateur"]})
        territoires.append({"niveau": t["niveau"], "code": t["code"], "nom": t["nom"], "region": t["region"],
                            "valeurs": t["valeurs"], "par_annee": par_annee})
    aides = {}
    for lib, (aid, nom, pilier) in AIDES.items():
        ans = sorted({c["annee"] for c in cols if c["aide"] == aid})
        if ans:
            retenu = {str(a): montant_retenu({c["indicateur"] for c in cols if c["aide"] == aid and c["annee"] == a})
                      for a in ans}
            aides[aid] = {"nom": nom, "libelle_source": lib, "pilier": pilier, "annees": ans,
                          "montant_retenu": retenu}
    return {
        "millesime": f"{annees[0]} à {annees[-1]}",
        "source": f"{SOURCES['pac_departements']['producteur']}, « {SOURCES['pac_departements']['titre']} » "
                  f"({SOURCES['pac_departements']['url']})",
        "url": SOURCES["pac_departements"]["page"],
        "licence": LO1,
        "date_sources": date,
        "unite": "euros (la source publie des milliers d'euros, convertis ici en euros) ; nombres d'exploitations, "
                 "d'animaux ; tonnes",
        "annees": annees,
        "piliers": PILIERS,
        "aides": aides,
        "colonnes": [{"annee": c["annee"], "aide": c["aide"], "indicateur": c["indicateur"], "unite": c["unite"],
                      "libelle_source": c["libelle_source"]} for c in cols],
        "territoires": territoires,
        "cellules_secretes": secretes,
        "controles": controles_pac(pac),
        "definitions": {
            "valeurs": "valeurs du territoire alignées sur `colonnes` (même ordre) ; null : cellule vide ou secrète",
            "montant_retenu": "par aide et par année, indicateur qui représente l'aide : « montant total » quand la "
                              "source le publie, sinon son unique montant ; les compléments publiés à part (par "
                              "exemple le complément extensification de la prime au maintien du troupeau de vaches "
                              "allaitantes en 2005) restent dans `valeurs` et ne sont pas ajoutés",
            "somme_montants_retenus_eur": "somme des montants retenus des aides publiées pour le territoire et "
                                          "l'année ; `aides_sans_montant` liste les aides absentes ou secrètes, non "
                                          "comptées",
            "region": "ancienne région (découpage d'avant 2016) dont relève le département dans la source",
            "code": "code de la source : un code de région peut être aussi un code de département (21 = Bourgogne "
                    "ou Côte-d'Or) ; un territoire se désigne donc par le couple `niveau` et `code`",
        },
        "limites": [
            "Série arrêtée en 2009 : c'est la dernière série départementale par type d'aide publiée en fichier "
            "ouvert trouvée ; la publication Telepac, seule source récente, était inaccessible lors de la collecte.",
            "Aucun bénéficiaire individuel : la source ne publie que des agrégats par département et par région.",
            "Cellules « S » (secret statistique) publiées null et listées dans `cellules_secretes`.",
            "Les aides du développement rural ne séparent pas la part européenne de la contrepartie nationale.",
            "Les aides de 2005 (avant les droits à paiement unique) et celles de 2006 à 2009 ne couvrent pas les "
            "mêmes dispositifs : `aides.<id>.annees` donne les années publiées de chaque aide.",
        ],
        "confidentialite": "agrégats par département et région seulement ; aucun bénéficiaire, même personne morale",
    }


# --- Développement rural (FEADER) et paiements 2023-2027 -------------------------------------------------------------

MESURES = {
    "M01": "Transfert de connaissances et actions d'information",
    "M02": "Services de conseil, d'aide à la gestion agricole et de remplacement",
    "M03": "Systèmes de qualité applicables aux produits agricoles et aux denrées alimentaires",
    "M04": "Investissements physiques",
    "M05": "Reconstitution du potentiel de production agricole après une catastrophe et prévention",
    "M06": "Développement des exploitations agricoles et des entreprises",
    "M07": "Services de base et rénovation des villages dans les zones rurales",
    "M08": "Investissements dans le développement des zones forestières",
    "M09": "Mise en place de groupements et d'organisations de producteurs",
    "M10": "Agroenvironnement et climat",
    "M11": "Agriculture biologique",
    "M12": "Paiements au titre de Natura 2000 et de la directive-cadre sur l'eau",
    "M13": "Paiements en faveur des zones soumises à des contraintes naturelles (indemnité compensatoire de "
           "handicaps naturels)",
    "M15": "Services forestiers, environnementaux et climatiques et conservation des forêts",
    "M16": "Coopération",
    "M17": "Gestion des risques",
    "M19": "Développement local LEADER",
    "M20": "Assistance technique",
    "M21": "Aide temporaire exceptionnelle liée à la crise de la COVID-19",
    "VOID": "non ventilé par mesure à la source",
}
# programme régional (code CCI) des départements et régions d'outre-mer -> code de territoire de la série Agreste
CCI_OUTREMER = {"001": "01", "002": "02", "003": "03", "004": "04", "006": "06"}
DEPARTEMENTS_HORS_AGRESTE = {"06": ["976"]}   # Mayotte : département depuis 2011, absent de la série 2005-2009


def _f(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _eur(x: float | None) -> int | None:
    return None if x is None else int(round(x))


def lire_json(cle: str) -> list[dict]:
    chemin = BRUT / SOURCES[cle]["entrepot"]
    if not chemin.exists():
        raise SystemExit(f"{chemin.relative_to(ROOT)} absent : lancer `python pipeline/agriculture.py collecter`")
    return json.loads(chemin.read_text(encoding="utf-8"))


def regions_departements(pac: dict) -> dict[str, dict]:
    """Ancienne région (code de la série Agreste) -> nom et départements, depuis la série elle-même."""
    out: dict[str, dict] = {}
    for t in pac["territoires"]:
        if t["niveau"] == "region":
            out[t["code"]] = {"nom": t["nom"].removeprefix("Région ").removeprefix("de la ").strip(),
                              "departements": []}
        elif t["niveau"] == "departement" and t["region"] in out:
            out[t["region"]]["departements"].append(t["code"])
    for r, deps in DEPARTEMENTS_HORS_AGRESTE.items():
        out.setdefault(r, {"nom": "Mayotte", "departements": []})["departements"].extend(deps)
    return out


def par_mesure_brut(lignes: list[dict], champs: dict, somme) -> list[dict]:
    """Sommes par mesure sur toutes les lignes données (un découpage du même programme, pas des sources différentes)."""
    out = []
    for m in sorted({r.get("eafrd_measure") or "VOID" for r in lignes}):
        rm = [r for r in lignes if (r.get("eafrd_measure") or "VOID") == m]
        out.append({"mesure": m, "nom": MESURES.get(m), "libelle_source": rm[0].get("measure_short_description"),
                    **{k: somme(rm, c) for k, c in champs.items()}})
    return out


def type_programme(cci: str) -> str:
    if "RDNP" in cci:
        return "national"
    if "RDRN" in cci:
        return "reseau_rural"
    return "regional"


def doc_developpement_rural(lignes: list[dict], feaga: list[dict], feader23: list[dict], regions: dict,
                            date: str) -> dict:
    if any(r.get("fund") != "EAFRD" or r.get("ms") != "FR" for r in lignes):
        raise SystemExit("le fichier FEADER 2014-2020 contient d'autres fonds ou pays que FEADER France")
    derniere = [r for r in lignes if r.get("latest_period") == "Y"]
    annee_situation = sorted({int(r["year"]) for r in derniere})
    if len(annee_situation) != 1:
        raise SystemExit(f"situation la plus récente ambiguë : {annee_situation}")
    champs = {"ue_eur": "eu_amount", "contrepartie_nationale_eur": "national_amount", "total_eur": "total_amount",
              "projets_selectionnes_eur": "total_eligible_cost", "depenses_declarees_eur": "total_eligible_expenditure"}

    def somme(rs, champ):
        vals = [_f(r.get(champ)) for r in rs]
        vals = [v for v in vals if v is not None]
        return _eur(sum(vals)) if vals else None

    programmes = []
    for cci in sorted({r["cci"] for r in derniere}):
        rs = [r for r in derniere if r["cci"] == cci]
        typ = type_programme(cci)
        region = None
        if typ == "regional":
            code = cci[-3:]
            code = CCI_OUTREMER.get(code, code[1:])
            reg = regions.get(code)
            region = {"code_ancienne_region": code, "nom": reg["nom"] if reg else None,
                      "departements": reg["departements"] if reg else []}
        mesures = par_mesure_brut(rs, champs, somme)
        maquette = {k: somme(rs, c) for k, c in champs.items()}
        programmes.append({
            "cci": cci, "titre_source": rs[0]["title"], "type": typ, "region": region,
            "version": sorted({r.get("ver") for r in rs})[-1],
            **maquette,
            "part_ue_pct": round(maquette["ue_eur"] / maquette["total_eur"] * 100, 1)
            if maquette["ue_eur"] is not None and maquette["total_eur"] else None,
            "par_mesure": mesures,
        })
    serie = []
    for a in sorted({int(r["year"]) for r in lignes}):
        rs = [r for r in lignes if int(r["year"]) == a]
        serie.append({"annee": a, "programmes": len({r["cci"] for r in rs}),
                      **{k: somme(rs, c) for k, c in champs.items()}})
    par_mesure = par_mesure_brut(derniere, champs, somme)
    national = {k: somme(derniere, c) for k, c in champs.items()}
    depassements = [{"mesure": m["mesure"], "projets_selectionnes_eur": m["projets_selectionnes_eur"],
                     "total_eur": m["total_eur"]} for m in par_mesure_brut(derniere, champs, somme)
                    if m["projets_selectionnes_eur"] and m["total_eur"] is not None
                    and m["projets_selectionnes_eur"] > m["total_eur"]]

    fr = [r for r in feaga if r.get("ms") == "FR"]
    if len(fr) != 1:
        raise SystemExit("paiements FEAGA 2023-2027 : ligne France absente ou en double")
    feaga_ex = [{"exercice_financier": int(k[3:]), "paiements_eur": _eur(_f(v))}
                for k, v in sorted(fr[0].items()) if re.fullmatch(r"fy_\d{4}", k) and _f(v) is not None]
    fr23 = [r for r in feader23 if r.get("fund") == "FR"]   # la colonne « fund » porte le code du pays à la source
    if len(fr23) != 1:
        raise SystemExit("paiements FEADER 2023-2027 : ligne France absente ou en double")
    f23 = fr23[0]
    retours = _charger("ue/retours.json")
    rubrique3 = [{"annee": a["annee"], "md": a["par_rubrique"]["3"]["md"], "nom": a["par_rubrique"]["3"]["nom"],
                  "source": a.get("source")}
                 for a in (retours or {}).get("annees", []) if (a.get("par_rubrique") or {}).get("3")]
    return {
        "millesime": f"FEADER 2014-2022 : situation {annee_situation[0]} ; FEAGA : exercices "
                     f"{feaga_ex[0]['exercice_financier']} à {feaga_ex[-1]['exercice_financier']} ; FEADER 2023-2027 : "
                     "cumul à la date de collecte",
        "source": f"Commission européenne, cohesiondata.ec.europa.eu : « {SOURCES['feader_2014_2020']['titre']} » "
                  f"({SOURCES['feader_2014_2020']['url']}), « {SOURCES['feaga_2023_2027']['titre']} » "
                  f"({SOURCES['feaga_2023_2027']['url']}), « {SOURCES['feader_2023_2027']['titre']} » "
                  f"({SOURCES['feader_2023_2027']['url']})",
        "url": SOURCES["feader_2014_2020"]["page"],
        "licence": CC0,
        "date_sources": date,
        "unite": "euros courants",
        "feader_2014_2022": {
            "annee_situation": annee_situation[0],
            "definitions": {
                "ue_eur": "montant prévu du FEADER (part de l'Union européenne) dans la dernière version adoptée du "
                          "programme",
                "contrepartie_nationale_eur": "cofinancement national prévu (financements publics et privés, non "
                                              "séparés à la source : État, régions, départements, autres)",
                "total_eur": "part de l'Union européenne + contrepartie nationale prévues",
                "projets_selectionnes_eur": "montant total (Union européenne et national) des projets retenus par "
                                            "l'autorité de gestion, cumulé",
                "depenses_declarees_eur": "dépenses éligibles déclarées par les bénéficiaires au programme, "
                                          "cumulées",
                "region": "ancienne région (avant 2016) du programme régional ; `departements` en donne les "
                          "départements, sans répartir les montants entre eux",
            },
            "national": national,
            "ecarts_total_source": {
                "programmes": [{"cci": p["cci"], "total_eur": p["total_eur"],
                                "ue_plus_contrepartie_eur": p["ue_eur"] + p["contrepartie_nationale_eur"],
                                "ecart": p["total_eur"] - p["ue_eur"] - p["contrepartie_nationale_eur"]}
                               for p in programmes if None not in (p["total_eur"], p["ue_eur"],
                                                                   p["contrepartie_nationale_eur"])
                               and abs(p["total_eur"] - p["ue_eur"] - p["contrepartie_nationale_eur"]) > 1000],
                "constat": "programmes dont le montant total publié par la source diffère de plus de 1 000 euros de "
                           "la somme de la part de l'Union européenne et de la contrepartie nationale publiées ; "
                           "montants publiés tels quels, sans correction",
            },
            "selection_superieure_a_la_maquette": {
                "mesures": depassements,
                "constat": "pour ces mesures, le montant des projets sélectionnés publié par la source dépasse le "
                           "montant total prévu ; il ne mesure pas une dépense (voir `depenses_declarees_eur`) et "
                           "n'est pas corrigé ici",
            },
            "programmes": programmes,
            "par_mesure": par_mesure,
            "serie": serie,
            "note_serie": "chaque année est une situation cumulée depuis 2014 : les années ne s'additionnent pas ; "
                          "la dernière année donne la situation la plus récente publiée",
        },
        "psn_2023_2027": {
            "feaga_paiements": feaga_ex,
            "feaga_note": "paiements du Fonds européen agricole de garantie (premier pilier) à la France par "
                          "exercice financier ; la source ne publie pas de contrepartie nationale pour ce fonds",
            "feader": {
                "maquette_ue_eur": _eur(_f(f23.get("actual_plan_eu_amt_latest_adop"))),
                "prefinancement_net_eur": _eur(_f(f23.get("net_pre_financing"))),
                "paiements_intermediaires_nets_eur": _eur(_f(f23.get("net_interim_payments"))),
                "paiements_nets_eur": _eur(_f(f23.get("total_net_payments"))),
                "taux_paiement_pct": round(_f(f23.get("eu_payment_rate_actual_plan_eu_amt")) * 100, 1)
                if _f(f23.get("eu_payment_rate_actual_plan_eu_amt")) is not None else None,
                "note": "part de l'Union européenne seulement, cumulée depuis 2023 ; la contrepartie nationale du "
                        "plan stratégique national n'est pas publiée dans ce jeu",
            },
        },
        "autre_vue_ue": {
            "fichier": "ue/retours.json",
            "rubrique": "3",
            "valeurs_md": rubrique3,
            "lecture": "dépenses de l'UE en France pour la rubrique « Agriculture et pêche » (premier pilier, "
                       "développement rural, pêche), année civile, en milliards d'euros : autre périmètre et autre "
                       "calendrier que les paiements par exercice financier ci-dessus ; posées côte à côte, jamais "
                       "additionnées",
        },
        "limites": [
            "Montants par programme de développement rural, donc par ancienne région, et non par département.",
            "Programmation 2014-2020 prolongée en 2021 et 2022 : les montants couvrent 2014-2022.",
            "Contrepartie nationale prévue seulement : son exécution par financeur n'est pas publiée dans ce jeu.",
            "Plan stratégique national 2023-2027 : paiements nationaux seulement, sans détail régional ni par "
            "mesure dans ces jeux.",
        ],
    }


# --- Budget de l'État -------------------------------------------------------------------------------------------------

PROGRAMMES_ETAT = ["149", "206", "215", "381"]
PERIMETRES = {
    "149": "jusqu'en 2014, le numéro 149 désignait le programme « Forêt » ; depuis la loi de finances pour 2015, il "
           "réunit l'ancien programme 154 (agriculture et territoires) et la forêt : les montants avant et après "
           "2015 ne portent pas sur le même périmètre ; l'intitulé est celui de realisations/149.json",
    "206": "sécurité et qualité sanitaires de l'alimentation",
    "215": "fonctions support du ministère chargé de l'agriculture",
    "381": "compensation des allègements de cotisations pour l'emploi de travailleurs occasionnels agricoles, "
           "programme créé en 2023",
}
PROGRAMMES_ABSENTS = [
    {"programme": "154", "nom": "Économie et développement durable de l'agriculture et des territoires",
     "periode": "jusqu'en 2014", "constat": "absent de realisations/ et de arbre/ : non repris ici, aucune "
                                            "estimation à la place"},
    {"programme": "775 et 776", "nom": "Compte d'affectation spéciale « Développement agricole et rural »",
     "periode": "depuis 2006", "constat": "absent de realisations/ et de arbre/ : non repris ici"},
]


def _charger(rel: str):
    p = SITE / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def fichier_arbre(programme: str) -> str | None:
    fs = sorted(p.name for p in (SITE / "arbre").glob(f"*_{programme}.json"))
    return f"arbre/{fs[0]}" if len(fs) == 1 else None


def doc_etat(date: str) -> dict:
    programmes = []
    for num in PROGRAMMES_ETAT:
        rel = f"realisations/{num}.json"
        r = _charger(rel)
        if r is None:
            raise SystemExit(f"site/data/{rel} absent : lancer d'abord l'étape realisations")
        annees = [{"annee": a["annee"], "vote_lfi_eur": _eur(a.get("vote_lfi_eur")),
                   "depense_constatee_eur": _eur(a.get("depense_constatee_eur")), "source": a.get("source")}
                  for a in r["prevu_depense"]["annees"]
                  if a.get("vote_lfi_eur") is not None or a.get("depense_constatee_eur") is not None]
        fa = fichier_arbre(num)
        arbre = None
        if fa:
            n = _charger(fa)
            arbre = {"fichier": fa, "id": n["id"], "millesime": n["millesime"], "md": n["md"],
                     "actions": [{"id": c["id"], "nom": c["nom"], "md": c["md"]} for c in n.get("enfants", [])]}
        programmes.append({"programme": num, "nom": r["libelle"], "mission": r["mission"],
                           "fichier_realisations": rel, "perimetre": PERIMETRES[num], "annees": annees,
                           "arbre": arbre})
    niches = _charger("niches/programmes.json")
    renvoi = None
    if niches:
        p = next((x for x in niches["programmes"] if x["programme"] == "149"), None)
        if p:
            renvoi = {"fichier": "niches/programmes.json", "programme": "149", "noeud": p["noeud"],
                      "mesures": sorted(p["mesures"]), "fichier_mesures": "niches/mesures.json",
                      "lecture": "dépenses fiscales rattachées au programme 149 dans le projet de loi de finances "
                                 "(réductions d'impôt ou exonérations pour l'agriculture) : identifiants seulement, "
                                 "les montants et leur méthode sont dans le fichier indiqué par `fichier`, non recopiés ici"}
    return {
        "millesime": "exécution 2010 à 2025 selon les années publiées ; actions : exécution 2024",
        "source": "fichiers du dépôt produits à partir de data.economie.gouv.fr (https://data.economie.gouv.fr) : "
                  "realisations/<programme>.json (prévu et dépensé), arbre/ (exécution 2024 par action), "
                  "niches/programmes.json (dépenses fiscales)",
        "unite": "euros (crédits de paiement) ; `md` en milliards d'euros",
        "date_sources": date,
        "programmes": programmes,
        "programmes_absents": PROGRAMMES_ABSENTS,
        "depenses_fiscales": renvoi,
        "cofinancement_feader": {"fichier": "agriculture/developpement_rural.json",
                                 "lecture": "contrepartie nationale prévue des programmes de développement rural "
                                            "2014-2022 (État, régions et autres financeurs, non séparés à la "
                                            "source)"},
        "limites": [
            "Années sans valeur dans realisations/ (2015 à 2017, 2021 notamment) : absentes ici, non estimées.",
            "Les crédits de l'État et les fonds européens sont deux sources distinctes : jamais additionnés.",
            "Les dépenses fiscales agricoles ne sont citées que par renvoi (`depenses_fiscales`), sans montant.",
        ],
    }


# --- Production -------------------------------------------------------------------------------------------------------

def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def produire(sortie: Path = SORTIE) -> dict:
    date = date_sources(DOMAINE)
    pac = lire_pac(fichier_pac())
    d_pac = doc_pac(pac, date)
    d_dr = doc_developpement_rural(lire_json("feader_2014_2020"), lire_json("feaga_2023_2027"),
                                   lire_json("feader_2023_2027"), regions_departements(pac), date)
    d_etat = doc_etat(date)

    fr = next(t for t in d_pac["territoires"] if t["code"] == "FR")
    dern = str(d_pac["annees"][-1])
    p149 = next(p for p in d_etat["programmes"] if p["programme"] == "149")
    dep149 = [a for a in p149["annees"] if a["depense_constatee_eur"] is not None]
    feader = d_dr["feader_2014_2022"]["national"]
    index = {
        "millesime": f"PAC par département {d_pac['millesime']} ; FEADER 2014-2022 ; paiements 2023-2026 ; budget de "
                     "l'État 2010-2025",
        "source": "Agreste et ASP (data.gouv.fr), Commission européenne (cohesiondata.ec.europa.eu), fichiers "
                  "budgétaires du dépôt (data.economie.gouv.fr) : https://www.data.gouv.fr/datasets/"
                  "aides-de-la-politique-agricole-commune-pac-30379066 ; https://cohesiondata.ec.europa.eu",
        "date_sources": date,
        "fichiers": [
            {"fichier": "agriculture/pac_departements.json", "contenu": "aides PAC par département, année et type "
                                                                        "d'aide (2005-2009)"},
            {"fichier": "agriculture/developpement_rural.json", "contenu": "FEADER 2014-2022 par programme et par "
                                                                           "mesure, contrepartie nationale ; "
                                                                           "paiements FEAGA et FEADER 2023-2027"},
            {"fichier": "agriculture/etat.json", "contenu": "budget de l'État pour l'agriculture (programmes 149, "
                                                            "206, 215, 381), renvois"},
        ],
        "reperes": {
            "pac_france_hors_tom": {"annee": int(dern),
                                    "somme_montants_retenus_eur": fr["par_annee"][dern]["somme_montants_retenus_eur"],
                                    "source": "Agreste et ASP"},
            "feader_2014_2022": {"ue_eur": feader["ue_eur"],
                                 "contrepartie_nationale_eur": feader["contrepartie_nationale_eur"],
                                 "depenses_declarees_eur": feader["depenses_declarees_eur"],
                                 "annee_situation": d_dr["feader_2014_2022"]["annee_situation"],
                                 "source": "Commission européenne"},
            "feaga_paiements": d_dr["psn_2023_2027"]["feaga_paiements"],
            "programme_149": {"annee": dep149[-1]["annee"], "depense_constatee_eur": dep149[-1]["depense_constatee_eur"],
                              "fichier": "realisations/149.json"},
            "lecture": "chiffres de sources et de périmètres différents, posés côte à côte, jamais additionnés",
        },
        "liens": [
            {"vue": "ue_retours", "fichier": "ue/retours.json", "lecture": "dépenses de l'UE en France, rubrique "
                                                                          "« Agriculture et pêche »"},
            {"vue": "realisations", "fichier": "realisations/149.json", "lecture": "prévu et dépensé du programme 149"},
            {"vue": "niches", "fichier": "niches/programmes.json", "lecture": "dépenses fiscales du programme 149"},
            {"vue": "retraites", "fichier": "retraites/index.json", "lecture": "retraites du régime agricole"},
        ],
        "confidentialite": "aucun bénéficiaire individuel de la politique agricole commune, même personne morale : "
                           "agrégats par département, région, programme ou pays seulement",
        "limites": [
            "Aucune série départementale ouverte des aides PAC après 2009 n'a pu être collectée (Telepac "
            "inaccessible lors de la collecte).",
            "Le développement rural 2014-2022 est publié par programme régional (anciennes régions), pas par "
            "département.",
            "Fonds européens, contrepartie nationale et budget de l'État : montants de sources distinctes, jamais "
            "additionnés.",
        ],
        "sources": {k: {c: v for c, v in s.items()} for k, s in sorted(SOURCES.items())},
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(sortie / "pac_departements.json", d_pac)
    dump(sortie / "developpement_rural.json", d_dr)
    dump(sortie / "etat.json", d_etat)
    dump(sortie / "index.json", index)
    print(f"agriculture : {len([t for t in d_pac['territoires'] if t['niveau'] == 'departement'])} départements "
          f"{d_pac['millesime']}, {len(d_pac['cellules_secretes'])} cellules secrètes, "
          f"{len(d_pac['controles']['ecarts'])} écarts ; {len(d_dr['feader_2014_2022']['programmes'])} programmes "
          f"FEADER ; {len(d_etat['programmes'])} programmes de l'État")
    return index


# --- Collecte ---------------------------------------------------------------------------------------------------------

def collecter() -> int:
    ids = [s["id_catalogue"] for s in SOURCES.values()]
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *ids, "--timeout", "560"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        code = collecter()
        if code and a.etape == "collecter":
            return code
    if a.etape in ("produire", "tout"):
        produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
