"""Sport : budget de l'État pour le sport (programme 219 et programme 350 des Jeux), Agence nationale du sport,
subventions aux fédérations, subventions territoriales du CNDS (prédécesseur de l'Agence), coût public des Jeux
olympiques et paralympiques de Paris 2024 tel qu'évalué par la Cour des comptes.

Recherche préalable (Règle n°0) : les séries budgétaires, le financement de l'Agence nationale du sport et les
subventions de l'État aux associations sont déjà produits par d'autres étapes du dépôt (site/data/realisations,
site/data/operateurs, site/data/associations) : ils sont repris tels quels, avec un lien vers le fichier d'origine,
sans recalcul. Aucun dépôt public ne réunit ces sources ; aucune donnée ouverte de l'Agence nationale du sport
(subventions par fédération et par région depuis 2019) n'est publiée sur data.gouv.fr, et agencedusport.fr refuse la
connexion (noté, jamais contourné). Le dernier jeu ouvert de subventions par fédération et par région est celui du
CNDS pour 2015 (data.gouv.fr, ministère chargé des sports).

Entrées :
  data/lake/sport/sport/ccomptes_jop2024_rapport.pdf                  Cour des comptes, rapport de septembre 2025
  data/lake/_restreint/sport/sport_cnds/cnds_part_*_2015.xlsx         CNDS 2015 (noms de bénéficiaires sans SIREN :
                                                                      zone restreinte, colonnes jamais lues)
  site/data/realisations/219.json, 350.json                           prévu et dépensé par année (étape realisations)
  site/data/programmes/219.json                                       actions du programme 219 (PLF 2025, étape base)
  site/data/operateurs/operateurs.json                                Agence nationale du sport (étape operateurs)
  site/data/associations/programmes/219.json                          subventions du programme 219 (étape associations)
  site/data/local/geo/*.json                                          départements et régions (étape local)
Sorties (site/data/sport/, chacune < 1 Mo, avec `millesime` et `source`) :
  index.json            blocs et statut, sources, sources inaccessibles, recherche préalable, limites
  budget.json           programmes 219 et 350 par année, actions du 219, financement de l'Agence par l'État
  federations.json      subventions du programme 219 aux associations nommées « fédération », 2010 à 2023
  cnds_2015.json        CNDS 2015 : part territoriale par fédération, par service instructeur et par région ;
                        part nationale par type ; part équipement par département et par région (agrégats seuls)
  jop.json              dépenses publiques liées aux Jeux de Paris 2024 (Cour des comptes) : par poste, par acteur,
                        recettes, dépenses nettes, estimation antérieure ; crédits du programme 350 à côté

Commandes :
  python pipeline/sport.py collecter   # réseau, par collecte/collecte.py (entrées sport et sport_cnds)
  python pipeline/sport.py produire    # sans réseau, reproductible octet pour octet
  python pipeline/sport.py             # les deux

Règles :
  - aucun bénéficiaire du CNDS n'est nommé (les fichiers ne donnent pas de SIREN : la catégorie juridique ne peut
    pas être vérifiée) ; les colonnes bénéficiaire, siège, code postal, porteur, commune et projet ne sont pas lues ;
  - une fédération n'est nommée que si sa catégorie juridique est une personne morale (sirene.personne_morale) ;
  - les montants de la Cour des comptes sont repris tels que publiés (millions d'euros, une décimale) et ne sont
    publiés que si la somme des postes redonne chaque total à 0,2 M€ près ; chaque autre chiffre n'est repris que si
    la phrase qui le porte est retrouvée dans le rapport ;
  - deux sources ne sont jamais additionnées : crédits du programme 350 et évaluation de la Cour, CNDS 2015 et
    subventions du programme 219, financement de l'Agence et dépense du programme 219 restent côte à côte ;
  - une valeur absente à la source est null, jamais 0.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sirene  # noqa: E402
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
BRUT = LAKE / "sport" / "sport"
BRUT_CNDS = LAKE / "_restreint" / "sport" / "sport_cnds"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "sport"
IDS_CATALOGUE = ("sport", "sport_cnds")
MAX_OCTETS = 1_000_000
PUBLIE = "publié"
NON_PUBLIE = "non publié en données ouvertes"

PDF_JOP = BRUT / "ccomptes_jop2024_rapport.pdf"
CNDS = {
    "territoriale": BRUT_CNDS / "cnds_part_territoriale_2015.xlsx",
    "nationale": BRUT_CNDS / "cnds_part_nationale_2015.xlsx",
    "equipement": BRUT_CNDS / "cnds_part_equipement_2015.xlsx",
}

# --- Sources ---------------------------------------------------------------------------------------------------------

DG = "https://www.data.gouv.fr/fr/datasets"
SOURCES = {
    "cour_des_comptes_jop": {
        "titre": "Cour des comptes, « Les Jeux olympiques et paralympiques de Paris 2024 », rapport au Parlement "
                 "(septembre 2025, article 20 de la loi du 19 mai 2023) : tableau n° 5, annexe n° 1 et synthèse",
        "producteur": "Cour des comptes",
        "url": "https://www.ccomptes.fr/sites/default/files/2025-09/20240929-rapport-JOP-2024_0.pdf",
        "page": "https://www.ccomptes.fr/fr/publications/les-jeux-olympiques-et-paralympiques-de-paris-2024",
        "licence": "publication de la Cour des comptes (réutilisation avec mention de la source)",
        "verdict": "à adapter (PDF : tableau lu ligne à ligne et contrôlé par ses totaux ; phrases citées)",
    },
    "cnds_2015": {
        "titre": "Ministère chargé des sports, « Subventions allouées en 2015 par le Centre national pour le "
                 "développement du sport (CNDS) » : part territoriale, part nationale, part équipement",
        "producteur": "Centre national pour le développement du sport (CNDS), ministère chargé des sports",
        "url": f"{DG}/57d579a4c751df4d2a97bae5/",
        "page": f"{DG}/subventions-allouees-en-2015-par-le-centre-national-pour-le-developpement-du-sport-cnds/",
        "licence": "Licence Ouverte 1.0", "modifie_le": "2016-10-08",
        "verdict": "à adapter (agrégats par fédération, service, région, type et département ; bénéficiaires "
                   "jamais nommés faute de SIREN)",
    },
    "realisations": {
        "titre": "Prévu et dépensé par programme (étape realisations du dépôt : lois de finances initiales, lois "
                 "de règlement et d'approbation des comptes, data.economie.gouv.fr)",
        "producteur": "Direction du budget, repris par pipeline/realisations.py",
        "url": "site/data/realisations/219.json ; site/data/realisations/350.json",
        "page": "https://data.economie.gouv.fr/", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (fichiers du dépôt)",
    },
    "programmes": {
        "titre": "Programme 219 par action et par nature, projet de loi de finances 2025 (étape base du dépôt)",
        "producteur": "Direction du budget, repris par pipeline/transform.py",
        "url": "site/data/programmes/219.json", "page": "https://data.economie.gouv.fr/",
        "licence": "Licence Ouverte 2.0", "verdict": "réutilisable tel quel (fichier du dépôt)",
    },
    "operateurs": {
        "titre": "Agence nationale du sport dans les annexes « Opérateurs de l'État » des projets de loi de finances "
                 "2024 à 2026 (étape operateurs du dépôt)",
        "producteur": "Direction du budget, repris par pipeline/operateurs.py",
        "url": "site/data/operateurs/operateurs.json", "page": "https://www.budget.gouv.fr/",
        "licence": "document budgétaire public", "verdict": "réutilisable tel quel (fichier du dépôt)",
    },
    "associations": {
        "titre": "Subventions du programme 219 aux associations, annexes « Effort financier de l'État en faveur des "
                 "associations » des projets de loi de finances 2012 à 2025 (étape associations du dépôt)",
        "producteur": "Direction du budget, repris par pipeline/associations.py",
        "url": "site/data/associations/programmes/219.json", "page": "https://data.economie.gouv.fr/",
        "licence": "Licence Ouverte 2.0",
        "verdict": "à adapter (fédérations retenues par leur dénomination ; personnes morales seulement)",
    },
    "geo": {
        "titre": "Départements et régions du code officiel géographique (étape local du dépôt, geo.api.gouv.fr)",
        "producteur": "Insee, DINUM, repris par pipeline/local.py", "url": "site/data/local/geo/",
        "page": "https://geo.api.gouv.fr/", "licence": "Licence Ouverte 2.0",
        "verdict": "réutilisable tel quel (fichiers du dépôt)",
    },
}

INACCESSIBLES = [
    {"source": "Agence nationale du sport, agencedusport.fr (subventions par fédération, par région et par "
               "bénéficiaire depuis 2019 : projets sportifs fédéraux, part territoriale, équipements)",
     "motif": "connexion refusée par le serveur (réinitialisée) à cinq essais espacés le 2026-11-18 ; aucune "
              "copie de ces listes sur data.gouv.fr ; non contourné"},
    {"source": "Agence nationale du sport, subventions par fédération et par région de 2016 à 2018 (CNDS)",
     "motif": "aucun jeu ouvert après celui de 2015 sur data.gouv.fr"},
    {"source": "Cour des comptes, données du rapport sur les Jeux (archive 20240929-donnees-rapport-JOP-2024.zip)",
     "motif": "l'archive ne contient que les graphiques de comparaison internationale (G1, G2) : le tableau des "
              "dépenses publiques est lu dans le PDF"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Les montants budgétaires et le financement de l'Agence nationale du sport sont déjà produits par "
                  "le dépôt (realisations, operateurs, associations) : repris tels quels. Pour les subventions par "
                  "fédération et par région, le seul jeu ouvert est celui du CNDS pour 2015. Pour les Jeux, la Cour "
                  "des comptes publie son évaluation en PDF ; l'archive de données jointe ne porte pas sur les "
                  "dépenses publiques. Aucun dépôt public réutilisable trouvé (recherche GitHub : « agence nationale "
                  "du sport », « CNDS subventions », « jeux olympiques dépenses publiques », « programme 219 »).",
    "trouvailles": [
        {"nom": "data.gouv.fr, « Subventions allouées en 2015 par le CNDS »", "url": SOURCES["cnds_2015"]["page"],
         "licence": "Licence Ouverte 1.0", "mise_a_jour": "2016-10-08", "verdict": "à adapter"},
        {"nom": "Cour des comptes, rapport « Les Jeux olympiques et paralympiques de Paris 2024 » et archive de "
                "données", "url": SOURCES["cour_des_comptes_jop"]["page"],
         "licence": "publication de la Cour des comptes", "mise_a_jour": "2025-10-28",
         "verdict": "à adapter (rapport) ; inspiration seulement (archive : graphiques internationaux)"},
        {"nom": "data.gouv.fr, organisation « Ministère chargé des Sports » (61 jeux : équipements, Paris 2024 "
                "logistique, empreinte carbone)", "url": "https://www.data.gouv.fr/fr/organizations/"
                                                         "ministere-charge-des-sports/",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-11-17",
         "verdict": "inspiration (aucun jeu de dépenses ou de subventions après 2015)"},
        {"nom": "Dépôt, étapes realisations, operateurs et associations", "url": "pipeline/",
         "licence": "MIT (ce dépôt)", "mise_a_jour": "2026-11-17", "verdict": "réutilisable tel quel"},
        {"nom": "GitHub, recherche de dépôts publics sur l'Agence nationale du sport, le CNDS et le coût des Jeux",
         "url": "https://github.com/search", "licence": "sans objet", "mise_a_jour": "2026-11-18",
         "verdict": "aucun dépôt trouvé"},
    ],
}

# --- Outils ----------------------------------------------------------------------------------------------------------


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse 1 Mo ({n} octets) : découper")
    tmp = path.with_suffix(".part")
    tmp.write_text(texte + "\n", encoding="utf-8")
    tmp.replace(path)
    return n


def lire_site(rel: str):
    p = SITE / rel
    if not p.exists():
        raise SystemExit(f"site/data/{rel} absent : lancer d'abord l'étape qui le produit (pipeline/tout.py --plan)")
    return json.loads(p.read_text(encoding="utf-8"))


def cle(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def montant(v):
    """Nombre publié, ou None (cellule vide, texte) : jamais 0 par défaut."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def arrondi(x: float) -> float:
    return round(x, 2)


# --- Budget de l'État ------------------------------------------------------------------------------------------------

def budget() -> dict:
    programmes = {}
    for p in ("219", "350"):
        r = lire_site(f"realisations/{p}.json")
        annees = []
        for a in r["prevu_depense"]["annees"]:
            og = a.get("ouvert_en_gestion")
            e = {"annee": a["annee"], "vote_lfi_eur": a.get("vote_lfi_eur"),
                 "ouvert_en_gestion_eur": og.get("total_eur") if isinstance(og, dict) else None,
                 "depense_constatee_eur": a.get("depense_constatee_eur"), "source": a.get("source")}
            if a.get("trou"):
                e["trou"] = a["trou"]
            annees.append(e)
        programmes[p] = {"programme": p, "libelle": r["libelle"], "mission": r["mission"],
                         "unite": r["unite_montants"], "fichier": f"realisations/{p}.json", "annees": annees}
    prog = lire_site("programmes/219.json")
    actions = [{"code": a["code"], "nom": a["nom"], "md": a["md"]} for a in prog["actions"]]
    ops = lire_site("operateurs/operateurs.json")
    ans = next(o for o in ops["operateurs"] if o["id"] == "ans")
    ans_annees = []
    for a in sorted(ans["annees"]):
        v = ans["annees"][a]
        fe, lfi = v.get("financement_etat") or {}, v.get("credits_votes_lfi") or {}
        ans_annees.append({
            "annee": int(a), "nature": v.get("nature"),
            "programmes_financeurs": v.get("programmes_financeurs", []),
            "financement_etat_scsp_cp_eur": (fe.get("scsp") or {}).get("cp_eur"),
            "financement_etat_transferts_cp_eur": (fe.get("transferts") or {}).get("cp_eur"),
            "financement_etat_total_cp_eur": v.get("financement_etat_total_cp_eur"),
            "credits_votes_lfi_total_cp_eur": v.get("credits_votes_lfi_total_cp_eur"),
            "taxes_affectees_eur": v.get("taxes_affectees_eur"),
            "taxes_affectees_prevision_eur": v.get("taxes_affectees_prevision_eur"),
            "sources": v.get("sources", {}),
        })
    return {
        "millesime": f"{r['millesime']} ; actions du programme 219 : {prog['millesime']} ; Agence nationale du "
                     f"sport : {ops['millesime']}",
        "source": "site/data/realisations/219.json et 350.json ; site/data/programmes/219.json ; "
                  "site/data/operateurs/operateurs.json (fichiers du dépôt, sources citées dans chacun)",
        "unite": "euros (crédits de paiement), sauf actions_219 : milliards d'euros",
        "programmes": programmes,
        "actions_219": {"millesime": prog["millesime"], "source": prog["source"], "unite": prog["unite"],
                        "avertissement": prog["avertissement"], "fichier": "programmes/219.json",
                        "actions": actions},
        "agence_nationale_du_sport": {
            "nom": ans["nom"], "siren": ans["siren"], "statut": ans["statut"],
            "programme_chef_de_file": ans["programme_chef_de_file"], "fichier": "operateurs/operateurs.json",
            "id": "ans", "annees": ans_annees,
            "definitions": {
                "financement_etat_scsp_cp_eur": "subvention pour charges de service public versée par l'État",
                "financement_etat_transferts_cp_eur": "transferts de l'État que l'Agence redistribue (subventions "
                                                      "aux fédérations, aux clubs, aux équipements)",
                "taxes_affectees_eur": "taxes affectées à l'Agence (prélèvements sur les jeux et les paris, "
                                       "contribution sur les droits de diffusion), hors budget de l'État",
                "nature": "« execution » : montants exécutés ; « lfi » : crédits votés en loi de finances initiale",
            },
        },
        "lecture": "Le programme 219 finance notamment l'Agence nationale du sport : les montants de l'Agence sont "
                   "une partie des crédits du programme, ils ne s'y ajoutent pas. Les taxes affectées à l'Agence ne "
                   "passent pas par le budget de l'État. Le programme 350 a porté les crédits de l'État pour les "
                   "Jeux de 2018 à 2025 ; l'évaluation de la Cour des comptes (jop.json) couvre un périmètre plus "
                   "large.",
    }


# --- Fédérations (programme 219, jaunes associations) ----------------------------------------------------------------

FEDERATION = re.compile(r"\b(?:F[EÉ]D[EÉ]RATIONS?|F[EÉ]DER|F[EÉ]DE|F[EÉ]D)\b\.?", re.I)


def est_federation(denomination: str) -> bool:
    return bool(FEDERATION.search(denomination or ""))


def federations() -> dict:
    a = lire_site("associations/programmes/219.json")
    i = {c: k for k, c in enumerate(a["colonnes"])}
    annees, annees_credits = a["annees"], a["annees_credits"]
    lignes, totaux = [], [0.0] * len(annees)
    non_publies = {annees[k] for k, st in enumerate(a["par_annee"]) if st.get("statut") != "publie"}
    for l in a["lignes"]:
        if not est_federation(l[i["denomination"]]) or not sirene.personne_morale(l[i["categorie_juridique"]]):
            continue
        m = [None if v == "nc" else v for v in l[i["montants_eur"]]]
        for k, v in enumerate(m):
            if isinstance(v, (int, float)):
                totaux[k] += v
        lignes.append({"siren": l[i["siren"]], "denomination": l[i["denomination"]],
                       "categorie_juridique": l[i["categorie_juridique"]],
                       "total_eur": l[i["total_eur"]], "montants_eur": m})
    lignes.sort(key=lambda x: (-x["total_eur"], x["siren"]))
    par_annee = []
    for k, (an, ac) in enumerate(zip(annees, annees_credits)):
        pa = next((x for x in a["par_annee"] if x["annee"] == an), {})
        par_annee.append({"annee_plf": an, "annee_credits": ac, "statut": pa.get("statut"),
                          "federations_eur": arrondi(totaux[k]) if pa.get("statut") == "publie" else None,
                          "programme_219_total_source_eur": pa.get("total_source_eur")})
    return {
        "millesime": a["millesime"],
        "source": a["source"] + " ; sélection des fédérations par pipeline/sport.py",
        "unite": "euros (crédits versés l'année annee_credits, tels que publiés)",
        "fichier": "associations/programmes/219.json",
        "annees_plf": annees, "annees_credits": annees_credits,
        "regle": "Retenue : toute association subventionnée par le programme 219 dont la dénomination contient "
                 "« fédération » ou une de ses abréviations publiées (FEDE, FEDER, FED) : fédérations sportives "
                 "nationales, mais aussi leurs comités et ligues, et des fédérations d'éducation populaire ou de "
                 "pêche. Seules les personnes morales sont nommées (catégorie juridique SIRENE 2xxx à 9xxx, hors "
                 "groupements de personnes physiques).",
        "lecture": "montants_eur suit annees_plf : montant publié ; null = fédération absente de la liste de "
                   "l'année pour ce programme, ou liste de l'année non publiée. Depuis 2019, l'essentiel des "
                   "subventions aux fédérations est versé par l'Agence nationale du sport, hors de ces listes de "
                   "l'État.",
        "ordre": {"regle": "montant total sur les années couvertes, du plus élevé au plus faible ; à égalité, SIREN "
                           "croissant", "cles": ["-total_eur", "siren"]},
        "par_annee": par_annee,
        "federations": lignes,
        "non_publie_annees": sorted(non_publies),
    }


# --- CNDS 2015 -------------------------------------------------------------------------------------------------------

# Services régionaux du CNDS en 2015 (anciennes régions) -> région actuelle (code officiel géographique).
REGIONS_2015 = {
    "alsace": "44", "aquitaine": "75", "auvergne": "84", "basse normandie": "28", "bourgogne": "27",
    "bretagne": "53", "centre": "24", "champagne ardenne": "44", "corse": "94", "franche comte": "27",
    "guadeloupe": "01", "guyane": "03", "haute normandie": "28", "ile de france": "11", "la reunion": "04",
    "languedoc roussillon": "76", "limousin": "75", "lorraine": "44", "martinique": "02", "mayotte": "06",
    "midi pyrenees": "76", "midi pyrennes": "76", "nord pas de calais": "32", "pays de la loire": "52",
    "picardie": "32", "poitou charentes": "75", "provence alpes cote d azur": "93", "paca": "93",
    "rhone alpes": "84",
}
# Collectivités d'outre-mer : pas de région ; publiées sous leur code.
COM = {"saint pierre et miquelon": ("975", "Saint-Pierre-et-Miquelon"), "nouvelle caledonie": ("988", "Nouvelle-Calédonie"),
       "wallis et futuna": ("986", "Wallis-et-Futuna")}
CODES_COM = {"975": "Saint-Pierre-et-Miquelon", "986": "Wallis-et-Futuna", "988": "Nouvelle-Calédonie"}


def referentiel_geo() -> tuple[dict, dict, dict]:
    """(département par clé de nom, département par code, nom de région par code) d'après site/data/local/geo."""
    par_nom, par_code, regions = {}, {}, {}
    dossier = SITE / "local" / "geo"
    fichiers = sorted(dossier.glob("*.json"))
    if not fichiers:
        raise SystemExit("site/data/local/geo absent : lancer d'abord l'étape local")
    for f in fichiers:
        g = json.loads(f.read_text(encoding="utf-8"))
        d, r = g.get("departement"), g.get("region")
        if not d or not r:
            continue
        e = {"code": d["code"], "nom": d["nom"], "region_code": r["code"]}
        par_nom[cle(d["nom"])] = e
        par_code[d["code"]] = e
        regions[r["code"]] = r["nom"]
    return par_nom, par_code, regions


def lire_xlsx(chemin: Path, colonnes: tuple[str, ...]) -> list[dict]:
    """Lignes de la première feuille, réduites aux colonnes demandées (les autres ne sont jamais lues)."""
    import openpyxl
    if not chemin.exists():
        raise SystemExit(f"source absente : {chemin} (lancer `python pipeline/sport.py collecter`)")
    wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    try:
        lignes = wb.worksheets[0].iter_rows(values_only=True)
        tete = [str(c).strip() if c is not None else "" for c in next(lignes)]
        manque = [c for c in colonnes if c not in tete]
        if manque:
            raise SystemExit(f"{chemin.name} : colonnes absentes {manque} (format de la source changé)")
        idx = [tete.index(c) for c in colonnes]
        return [{c: r[k] if k < len(r) else None for c, k in zip(colonnes, idx)} for r in lignes
                if any(v is not None for v in r)]
    finally:
        wb.close()


def code_departement(v) -> str | None:
    s = str(v).strip().upper() if v is not None else ""
    if not s:
        return None
    if s == "985":   # ancien code de Mayotte
        return "976"
    return s.zfill(2) if s.isdigit() and len(s) < 2 else s


def cnds_2015() -> dict:
    par_nom, par_code, regions = referentiel_geo()

    def region_de(code_reg: str | None, com: tuple[str, str] | None = None) -> dict | None:
        if com:
            return {"code": com[0], "nom": com[1], "type": "collectivité d'outre-mer"}
        if code_reg:
            return {"code": code_reg, "nom": regions.get(code_reg), "type": "région"}
        return None

    # Part territoriale : par fédération, service instructeur, région actuelle, objectif.
    ter = lire_xlsx(CNDS["territoriale"], ("FedeCode", "FedeNom", "Subvention", "Objectif", "Service"))
    fed, serv, reg, obj, fed_reg = {}, {}, {}, {}, defaultdict(lambda: defaultdict(float))
    sans_montant, non_rattaches = 0, set()
    total = 0.0
    for r in ter:
        m = montant(r["Subvention"])
        if m is None:
            sans_montant += 1
            continue
        total += m
        code_f = str(r["FedeCode"]).strip()
        f = fed.setdefault(code_f, {"code": code_f, "nom": str(r["FedeNom"]).strip(), "montant_eur": 0.0, "lignes": 0})
        f["montant_eur"] += m
        f["lignes"] += 1
        s_nom = str(r["Service"]).strip()
        s = serv.get(s_nom)
        if s is None:
            k = cle(s_nom)
            if s_nom.isupper() and k in REGIONS_2015:
                rg = region_de(REGIONS_2015[k])
                s = {"service": s_nom, "niveau": "régional", "departement": None, "region": rg}
            elif s_nom.isupper() and k in COM:
                s = {"service": s_nom, "niveau": "collectivité d'outre-mer", "departement": None,
                     "region": region_de(None, COM[k])}
            elif k in par_nom:
                d = par_nom[k]
                s = {"service": s_nom, "niveau": "départemental", "departement": {"code": d["code"], "nom": d["nom"]},
                     "region": region_de(d["region_code"])}
            else:
                s = {"service": s_nom, "niveau": None, "departement": None, "region": None}
                non_rattaches.add(s_nom)
            s.update({"montant_eur": 0.0, "lignes": 0})
            serv[s_nom] = s
        s["montant_eur"] += m
        s["lignes"] += 1
        rg = s["region"]
        rk = rg["code"] if rg else "sans_region"
        e = reg.setdefault(rk, {"code": rg["code"] if rg else None, "nom": rg["nom"] if rg else None,
                                "type": rg["type"] if rg else None, "montant_eur": 0.0, "lignes": 0,
                                "services_regionaux_eur": 0.0, "services_departementaux_eur": 0.0})
        e["montant_eur"] += m
        e["lignes"] += 1
        if s["niveau"] == "départemental":
            e["services_departementaux_eur"] += m
        else:
            e["services_regionaux_eur"] += m
        o = str(r["Objectif"]).strip()
        x = obj.setdefault(o, {"objectif": o, "montant_eur": 0.0, "lignes": 0})
        x["montant_eur"] += m
        x["lignes"] += 1
        fed_reg[code_f][rk] += m

    def fini(lst, cles=("montant_eur", "services_regionaux_eur", "services_departementaux_eur")):
        for e in lst:
            for c in cles:
                if c in e:
                    e[c] = arrondi(e[c])
        return lst

    federations_l = fini(sorted(fed.values(), key=lambda e: (-e["montant_eur"], e["code"])))
    services_l = fini(sorted(serv.values(), key=lambda e: (e["niveau"] or "~", cle(e["service"]))))
    regions_l = fini(sorted(reg.values(), key=lambda e: (e["code"] is None, e["code"] or "")))
    objectifs_l = fini(sorted(obj.values(), key=lambda e: cle(e["objectif"])))
    matrice = {f: {r: arrondi(v) for r, v in sorted(d.items())} for f, d in sorted(fed_reg.items())}

    # Part nationale : par type d'aide (porteurs et projets non lus).
    nat = lire_xlsx(CNDS["nationale"], ("Montant_acc", "Type"))
    types, nat_total, nat_sans = {}, 0.0, 0
    for r in nat:
        m = montant(r["Montant_acc"])
        if m is None:
            nat_sans += 1
            continue
        t = str(r["Type"]).strip()
        e = types.setdefault(t, {"type": t, "montant_eur": 0.0, "lignes": 0})
        e["montant_eur"] += m
        e["lignes"] += 1
        nat_total += m

    # Part équipement : par département et par région actuelle (porteur, commune, projet non lus).
    equ = lire_xlsx(CNDS["equipement"], ("Dep", "Montant_op", "Montant_acc", "Objectifs"))
    deps, regs_e, objs_e, equ_total, equ_sans = {}, {}, {}, 0.0, 0
    for r in equ:
        m = montant(r["Montant_acc"])
        if m is None:
            equ_sans += 1
            continue
        mo = montant(r["Montant_op"])
        c = code_departement(r["Dep"])
        d = par_code.get(c)
        if d:
            dep = {"code": d["code"], "nom": d["nom"]}
            rg = region_de(d["region_code"])
        elif c in CODES_COM:
            dep, rg = {"code": c, "nom": CODES_COM[c]}, region_de(None, (c, CODES_COM[c]))
        else:
            dep, rg = {"code": c, "nom": None}, None
        e = deps.setdefault(dep["code"], {**dep, "region_code": rg["code"] if rg else None, "operations": 0,
                                          "montant_accorde_eur": 0.0, "montant_operations_eur": 0.0,
                                          "operations_sans_montant_total": 0})
        e["operations"] += 1
        e["montant_accorde_eur"] += m
        if mo is None:
            e["operations_sans_montant_total"] += 1
        else:
            e["montant_operations_eur"] += mo
        rk = rg["code"] if rg else "sans_region"
        x = regs_e.setdefault(rk, {"code": rg["code"] if rg else None, "nom": rg["nom"] if rg else None,
                                   "type": rg["type"] if rg else None, "operations": 0, "montant_accorde_eur": 0.0})
        x["operations"] += 1
        x["montant_accorde_eur"] += m
        o = str(r["Objectifs"]).strip()
        y = objs_e.setdefault(o, {"objectif": o, "operations": 0, "montant_accorde_eur": 0.0})
        y["operations"] += 1
        y["montant_accorde_eur"] += m
        equ_total += m
    cles_e = ("montant_accorde_eur", "montant_operations_eur")

    return {
        "millesime": "Subventions allouées en 2015 (CNDS) ; jeu publié le 2016-10-08",
        "source": f"{SOURCES['cnds_2015']['titre']} ({SOURCES['cnds_2015']['page']})",
        "annee": 2015,
        "unite": "euros (montants accordés)",
        "attribuant": "Centre national pour le développement du sport (CNDS), établissement public remplacé en 2019 "
                      "par l'Agence nationale du sport",
        "regle": "Aucun bénéficiaire n'est nommé : les fichiers ne donnent pas de SIREN, la catégorie juridique ne "
                 "peut donc pas être vérifiée. Les colonnes bénéficiaire, siège, code postal, porteur de projet, "
                 "commune et intitulé du projet ne sont pas lues ; seuls des totaux sont publiés.",
        "part_territoriale": {
            "definition": "subventions aux clubs, comités et ligues instruites par les services de l'État en région "
                          "et en département ; la fédération est celle de rattachement du bénéficiaire, telle que "
                          "codée dans la source",
            "total_eur": arrondi(total), "lignes": len(ter) - sans_montant, "lignes_sans_montant": sans_montant,
            "services_non_rattaches": sorted(non_rattaches),
            "par_federation": federations_l,
            "par_service": services_l,
            "par_region": regions_l,
            "par_objectif": objectifs_l,
            "federation_par_region": {"lecture": "code de fédération -> code de région actuelle ou de collectivité "
                                                 "d'outre-mer -> montant en euros",
                                      "valeurs": matrice},
            "methode_region": "service régional (ancienne région de 2015) rattaché à la région actuelle qui "
                              "l'englobe ; service départemental rattaché à la région actuelle de son département "
                              "(code officiel géographique)",
        },
        "part_nationale": {
            "definition": "subventions attribuées au niveau national (projets innovants, grands événements "
                          "sportifs internationaux, fonds de soutien à la production audiovisuelle)",
            "total_eur": arrondi(nat_total), "lignes": len(nat) - nat_sans, "lignes_sans_montant": nat_sans,
            "par_type": fini(sorted(types.values(), key=lambda e: cle(e["type"]))),
        },
        "part_equipement": {
            "definition": "subventions d'équipements sportifs ; montant accordé par le CNDS et coût total de "
                          "l'opération tel que déclaré",
            "total_accorde_eur": arrondi(equ_total), "operations": len(equ) - equ_sans,
            "lignes_sans_montant": equ_sans,
            "par_departement": fini(sorted(deps.values(), key=lambda e: e["code"]), cles_e),
            "par_region": fini(sorted(regs_e.values(), key=lambda e: (e["code"] is None, e["code"] or "")), cles_e),
            "par_objectif": fini(sorted(objs_e.values(), key=lambda e: cle(e["objectif"])), cles_e),
        },
        "lecture": "Trois parts distinctes, non additionnées entre elles ici ; le montant d'une opération "
                   "d'équipement est son coût total, financé par plusieurs acteurs.",
    }


# --- Jeux olympiques et paralympiques (Cour des comptes) -------------------------------------------------------------

NOMBRE = re.compile(r"^(.*?)\s*([+-]?\s?\d{1,3}(?: \d{3})*,\d)$")
TABLEAU5 = "Tableau n° 5 : les dépenses publiques liées aux Jeux"
ACTEURS = [
    ("etat_operateurs", "État et ses opérateurs",
     "renvoient pour 2 Md€ à des dépenses d'organisation et pour 1,88 Md€ à des dépenses d'infrastructures",
     2000.0, 1880.0),
    ("collectivites", "Collectivités territoriales et leurs établissements publics",
     "renvoient pour 730,7 M€ à des dépenses d'organisation et pour 1,63 Md€ à des dépenses d'infrastructures",
     730.7, 1630.0),
    ("entreprises_service_public", "Entreprises chargées d'une mission de service public",
     "renvoient pour 278,5 M€ à des dépenses d'organisation et pour 116,2 M€ à des dépenses d'infrastructures",
     278.5, 116.2),
]
AUTRES = [
    ("recettes_publiques_organisation_meur", 293.6,
     "Les Jeux ont aussi généré des recettes publiques de nature fiscale et commerciale (293,6 M€)",
     "recettes publiques liées à l'organisation (fiscales et commerciales) ; aucune recette n'est identifiée pour "
     "les infrastructures"),
    ("depenses_nettes_organisation_meur", 2730.0,
     "les dépenses publiques nettes sur le volet de l'organisation de l'évènement sont estimées à 2,73 Md€",
     "dépenses d'organisation moins recettes publiques, calcul de la Cour (infrastructures non comprises)"),
    ("depenses_fiscales_meur", 250.3,
     "les dépenses fiscales s'élèvent à 250,3 M€",
     "exonérations fiscales dont a bénéficié l'organisation, y compris le taux réduit de TVA sur la billetterie ; "
     "la Cour indique qu'elles n'ont pu être recensées de manière exhaustive"),
    ("cojop_recettes_meur", 4494.2, "Total recettes (A) 4 494,2",
     "recettes du comité d'organisation (Cojop), budget arrêté en juin 2025, subventions publiques comprises"),
    ("cojop_depenses_meur", 4418.5, "Total dépenses (B) 4 418,5",
     "dépenses du comité d'organisation (Cojop), budget arrêté en juin 2025"),
    ("cojop_solde_meur", 75.7, "Solde (C) = (A) – (B) + 75,7",
     "solde du comité d'organisation (Cojop) : recettes moins dépenses"),
]
ANTERIEURE = ("Estimées alors à 2,77 Md€ pour les dépenses d'organisation et à 3,19 Md€ pour les dépenses "
              "d'infrastructures", 2770.0, 3190.0)


def norm_texte(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("’", "'").replace(" ", " ")).strip()


def lire_pdf_jop() -> tuple[list[str], str, int | None]:
    """(lignes de la page du tableau n° 5, texte normalisé de tout le rapport, numéro de page du tableau)."""
    import logging
    import pdfplumber
    if not PDF_JOP.exists():
        raise SystemExit(f"source absente : {PDF_JOP} (lancer `python pipeline/sport.py collecter`)")
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    pages, lignes, page_t5 = [], [], None
    with pdfplumber.open(PDF_JOP) as pdf:
        for k, p in enumerate(pdf.pages):
            t = p.extract_text() or ""
            pages.append(t)
            if page_t5 is None and TABLEAU5 in t:
                page_t5, lignes = k + 1, t.splitlines()
    return lignes, norm_texte("\n".join(pages)), page_t5


def nombre_fr(s: str) -> float:
    return float(s.replace(" ", "").replace(",", "."))


def tableau5(lignes: list[str]) -> tuple[list[dict], dict, list[str]]:
    """Postes du tableau n° 5 (libellés sur plusieurs lignes recollés), totaux, fautes de contrôle."""
    try:
        debut = next(k for k, l in enumerate(lignes) if l.startswith(TABLEAU5))
        fin = next(k for k, l in enumerate(lignes) if k > debut and l.startswith("Source : Cour des comptes"))
    except StopIteration:
        return [], {}, ["tableau n° 5 introuvable dans le rapport"]
    corps = [l.strip() for l in lignes[debut + 1:fin]]
    # en-tête : « Montant évalué au 30 juin », « En M€ », « 2025 »
    while corps and not NOMBRE.match(corps[0]):
        corps.pop(0)
    postes, totaux, volet, attente, suffixe = [], {}, "organisation", "", None
    for l in corps:
        m = NOMBRE.match(l)
        if not m:
            if suffixe is not None:
                suffixe["poste"] = (suffixe["poste"] + " " + l).strip()
                suffixe = None
            else:
                attente = (attente + " " + l).strip()
            continue
        lib, val = (attente + " " + m.group(1)).strip(), nombre_fr(m.group(2))
        attente, suffixe = "", None
        if lib.startswith("Total dépenses d"):
            totaux[volet] = val
            volet = "infrastructures"
            continue
        e = {"volet": volet, "poste": lib, "montant_meur": val}
        postes.append(e)
        if not m.group(1):
            suffixe = e
    fautes = []
    for v in ("organisation", "infrastructures"):
        s = round(sum(p["montant_meur"] for p in postes if p["volet"] == v), 1)
        if v not in totaux:
            fautes.append(f"total {v} absent")
        elif abs(s - totaux[v]) > 0.2:
            fautes.append(f"somme des postes {v} {s} ≠ total publié {totaux[v]}")
    return postes, totaux, fautes


def jop(budget_: dict) -> tuple[dict, list[str]]:
    lignes, texte, page = lire_pdf_jop()
    postes, totaux, fautes = tableau5(lignes)
    non_retrouves = []

    def cite(phrase: str) -> bool:
        ok = norm_texte(phrase) in texte
        if not ok:
            non_retrouves.append(phrase)
        return ok

    acteurs = [{"id": i, "acteur": nom, "organisation_meur": o, "infrastructures_meur": inf, "citation": ph}
               for i, nom, ph, o, inf in ACTEURS if cite(ph)]
    autres = {k: {"montant_meur": v, "definition": d, "citation": ph} for k, v, ph, d in AUTRES if cite(ph)}
    anterieure = None
    if cite(ANTERIEURE[0]):
        anterieure = {"date": "2025-06-23", "document": "note d'étape de la Cour des comptes",
                      "organisation_meur": ANTERIEURE[1], "infrastructures_meur": ANTERIEURE[2],
                      "citation": ANTERIEURE[0],
                      "lecture": "première évaluation, avant les contrôles des chambres régionales des comptes "
                                 "d'Île-de-France et de Provence-Alpes-Côte d'Azur et avant l'estimation des "
                                 "dépenses de baignade dans la Seine ; remplacée par l'évaluation de septembre 2025"}
    p350 = budget_["programmes"]["350"]
    s = SOURCES["cour_des_comptes_jop"]
    publie = not fautes
    sortie = {
        "millesime": "Cour des comptes, rapport de septembre 2025 (montants évalués au 30 juin 2025) ; programme "
                     "350 : exécution 2018 à 2025 selon disponibilité",
        "source": f"{s['titre']} ({s['url']})",
        "statut": PUBLIE if publie else NON_PUBLIE,
        "unite": "millions d'euros (une décimale, tels que publiés)",
        "producteur": s["producteur"],
        "document": {"titre": "Les Jeux olympiques et paralympiques de Paris 2024", "date": "2025-09",
                     "url": s["url"], "page": s["page"], "page_tableau": page},
        "perimetre": "Dépenses de l'État et de ses opérateurs, des collectivités territoriales et de leurs "
                     "établissements publics, et des entreprises chargées d'une mission de service public, engagées "
                     "pour la préparation et le déroulement des Jeux : organisation (sécurité, transports, "
                     "mobilisation populaire, subventions au comité d'organisation, etc.) et infrastructures "
                     "(équipements sportifs, aménagements urbains, transports, baignade). Les dépenses privées du "
                     "comité d'organisation (Cojop) ne sont pas comprises, hormis les subventions publiques qu'il a "
                     "reçues.",
        "methode": "Méthode de la Cour (rapport, encadré « principes méthodologiques ») : sont comptées les "
                   "opérations nécessaires à l'évènement, celles qui contribuent à sa réussite populaire et les "
                   "investissements réalisés dans une logique d'héritage ; pas de calcul par différence avec une "
                   "situation où les Jeux auraient eu lieu ailleurs ; les investissements sont comptés pour leur coût "
                   "entier, pas pour la part de leur durée d'usage pendant les Jeux. Le tableau n° 5 est lu ligne à "
                   "ligne ; les autres montants sont repris de phrases du rapport, citées.",
        "controle": "somme des postes = total publié, pour chaque volet, à 0,2 M€ près ; chaque citation retrouvée "
                    "dans le texte du rapport",
        "fautes_controle": fautes,
        "citations_non_retrouvees": non_retrouves,
    }
    if publie:
        sortie.update({
            "postes": postes,
            "totaux_meur": totaux,
            "par_acteur": {"lecture": "montants arrondis par la Cour dans l'annexe n° 1 (par exemple 2 Md€) : leur "
                                      "somme peut différer du total du tableau",
                           "acteurs": acteurs},
            "autres_montants": autres,
            "estimation_anterieure": anterieure,
            "note_source": "Le poste « Subventions au Cojop » comprend 20 M€ de financements de la Métropole du "
                           "Grand Paris pour des actions d'héritage (note du tableau n° 5).",
        })
    else:
        sortie["motif"] = "tableau non repris : " + " ; ".join(fautes)
    sortie["programme_350"] = {
        "libelle": p350["libelle"], "fichier": p350["fichier"],
        "annees": [{k: a.get(k) for k in ("annee", "vote_lfi_eur", "depense_constatee_eur", "source")}
                   for a in p350["annees"] if a.get("depense_constatee_eur") is not None
                   or a.get("vote_lfi_eur") is not None],
        "unite": "euros (crédits de paiement)",
        "lecture": "crédits du budget de l'État au programme 350 « Jeux olympiques et paralympiques 2024 », tels "
                   "que publiés (une valeur négative est une annulation ou un rétablissement de crédits) : une "
                   "partie seulement des dépenses de l'État évaluées par la Cour, jamais additionnée aux montants "
                   "de la Cour",
    }
    return sortie, fautes + [f"citation non retrouvée : {p}" for p in non_retrouves]


# --- Production ------------------------------------------------------------------------------------------------------

def _manifeste() -> dict:
    try:
        m = json.loads((LAKE / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {i: m.get(i, {}) for i in IDS_CATALOGUE}


def produire() -> dict:
    for p in (PDF_JOP, *CNDS.values()):
        if not p.exists():
            raise SystemExit(f"source absente : {p} (lancer `python pipeline/sport.py collecter`)")
    date = date_sources("sport")
    b = budget()
    f = federations()
    c = cnds_2015()
    j, fautes_jop = jop(b)
    dump(SORTIE / "budget.json", b)
    dump(SORTIE / "federations.json", f)
    dump(SORTIE / "cnds_2015.json", c)
    dump(SORTIE / "jop.json", j)

    inaccessibles = list(INACCESSIBLES)
    for i, m in _manifeste().items():
        if m and m.get("statut") not in (None, "ok"):
            inaccessibles.append({"source": f"entrée « {i} » du catalogue",
                                  "motif": f"collecte incomplète (statut {m.get('statut')})"})
    if fautes_jop:
        inaccessibles.append({"source": SOURCES["cour_des_comptes_jop"]["titre"],
                              "motif": "lecture du PDF incomplète : " + " ; ".join(fautes_jop[:3])})
    sources = {k: {**{x: s[x] for x in ("titre", "producteur", "url", "page", "licence", "verdict")},
                   "collecte_le": date, **({"modifie_le": s["modifie_le"]} if "modifie_le" in s else {})}
               for k, s in SOURCES.items()}
    blocs = {
        "budget_programme_219": {"statut": PUBLIE, "fichier": "sport/budget.json", "source": "realisations",
                                 "description": "programme 219 « Sport » : voté, ouvert, dépensé par année ; "
                                                "actions du projet de loi de finances 2025"},
        "budget_programme_350": {"statut": PUBLIE, "fichier": "sport/budget.json", "source": "realisations",
                                 "description": "programme 350 « Jeux olympiques et paralympiques 2024 », 2018 à "
                                                "2025"},
        "agence_nationale_du_sport_financement": {
            "statut": PUBLIE, "fichier": "sport/budget.json", "source": "operateurs",
            "description": "financement de l'Agence nationale du sport par l'État et taxes affectées, 2020 à 2025"},
        "federations_etat": {"statut": PUBLIE, "fichier": "sport/federations.json", "source": "associations",
                             "description": "subventions du programme 219 aux associations dont la dénomination "
                                            "contient « fédération », crédits 2010 à 2023"},
        "cnds_2015": {"statut": PUBLIE, "fichier": "sport/cnds_2015.json", "source": "cnds_2015",
                      "description": "subventions du CNDS en 2015 par fédération, par région, par département"},
        "agence_nationale_du_sport_subventions": {
            "statut": NON_PUBLIE,
            "motif": "l'Agence nationale du sport ne publie pas ses subventions (par fédération, par région ou par "
                     "bénéficiaire) en données ouvertes sur data.gouv.fr, et son site a refusé la connexion à la "
                     "date de collecte ; aucune valeur n'est estimée"},
        "jop_cour_des_comptes": {
            "statut": j["statut"], "fichier": "sport/jop.json", "source": "cour_des_comptes_jop",
            "description": "dépenses publiques liées aux Jeux de Paris 2024, évaluées par la Cour des comptes",
            **({"motif": j["motif"]} if j["statut"] == NON_PUBLIE else {})},
    }
    tot_jop = j.get("totaux_meur", {})
    index = {
        "millesime": f"sources collectées le {date} ; budget 2010 à 2025 ; fédérations : crédits 2010 à 2023 ; "
                     "CNDS 2015 ; Jeux : évaluation de la Cour des comptes au 30 juin 2025",
        "source": "pipeline/sport.py (voir `sources` et chaque fichier)",
        "collecte_le": date,
        "fichiers": {"budget": "sport/budget.json", "federations": "sport/federations.json",
                     "cnds_2015": "sport/cnds_2015.json", "jop": "sport/jop.json"},
        "blocs": blocs,
        "statuts": {PUBLIE: "le bloc est repris d'une source citée",
                    NON_PUBLIE: "aucune source ouverte ne publie ce bloc à la date de collecte : cela décrit l'état "
                                "de la publication, pas l'usage de l'argent ; aucune valeur n'est estimée"},
        "chiffres_cles": {
            "programme_219_depense_constatee": next(
                ({"annee": a["annee"], "eur": a["depense_constatee_eur"]}
                 for a in reversed(b["programmes"]["219"]["annees"]) if a["depense_constatee_eur"] is not None),
                None),
            "jop_organisation_meur": tot_jop.get("organisation"),
            "jop_infrastructures_meur": tot_jop.get("infrastructures"),
            "cnds_2015_part_territoriale_eur": c["part_territoriale"]["total_eur"],
            "lecture": "montants de sources et de périmètres différents, présentés côte à côte, jamais additionnés",
        },
        "liens": [
            {"fichier": "realisations/219.json", "lecture": "prévu et dépensé du programme 219, indicateurs"},
            {"fichier": "realisations/350.json", "lecture": "prévu et dépensé du programme 350"},
            {"fichier": "operateurs/operateurs.json", "id": "ans",
             "lecture": "Agence nationale du sport, toutes les grandeurs des annexes « Opérateurs »"},
            {"fichier": "associations/programmes/219.json",
             "lecture": "toutes les associations subventionnées par le programme 219, pas seulement les fédérations"},
            {"fichier": "beneficiaires/programme_219.json", "lecture": "bénéficiaires du programme 219"},
        ],
        "limites": [
            "Les subventions de l'Agence nationale du sport depuis 2019 (projets sportifs fédéraux, part "
            "territoriale, équipements) ne sont pas publiées en données ouvertes : les montants par fédération et "
            "par région sont ceux du CNDS pour 2015, dernier jeu ouvert.",
            "Les listes de subventions de l'État (jaunes « associations ») ne comprennent pas les subventions "
            "versées par l'Agence : la baisse visible après 2019 dans federations.json traduit ce changement "
            "d'attribuant.",
            "Le coût des Jeux est l'évaluation de la Cour des comptes au 30 juin 2025, selon sa méthode ; d'autres "
            "évaluations, sur d'autres périmètres, existent (crédits du programme 350, budget du comité "
            "d'organisation) et ne sont pas additionnées.",
            "Le rattachement d'un service régional du CNDS de 2015 à une région actuelle suit le découpage de 2016 "
            "(fusion des régions) : aucune répartition n'est estimée.",
        ],
        "sources": sources,
        "sources_inaccessibles": inaccessibles,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(SORTIE / "index.json", index)
    print(f"sport : programme 219 ({len(b['programmes']['219']['annees'])} années), {len(f['federations'])} "
          f"fédérations, CNDS 2015 {c['part_territoriale']['total_eur']:.0f} €, Jeux {j['statut']} "
          f"-> {SORTIE.relative_to(ROOT)}")
    return index


# --- Collecte --------------------------------------------------------------------------------------------------------

def collecter(forcer: bool = False) -> int:
    """Collecte par collecte/collecte.py (reprises, manifeste, aucun contournement d'un refus d'accès)."""
    cmd = [sys.executable, str(ROOT / "collecte" / "collecte.py"), *IDS_CATALOGUE]
    return subprocess.call(cmd + (["--force"] if forcer else []))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true", help="retélécharger les sources déjà présentes")
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter(a.forcer)
    if a.etape in ("produire", "tout"):
        produire()


if __name__ == "__main__":
    main()
