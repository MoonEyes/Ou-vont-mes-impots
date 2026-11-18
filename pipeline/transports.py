"""Transports : budget de l'AFITF, concours publics au ferroviaire, programmes budgétaires, versement mobilité.

Agrégats publiés seulement (aucune personne, aucun bénéficiaire individuel). Le module reprend ce que publient les
producteurs, sans recalculer les totaux : un total publié qui ne retombe pas sur la somme de ses lignes est publié
avec son écart ; deux sources qui décrivent le même argent sont montrées côte à côte, jamais additionnées.

Entrées (data/lake/, non versionné, déclarées dans collecte/catalogue.json) :
    transports/transports_sdes_bilan_2024_activite.xlsx
        SDES, Bilan annuel des transports en 2024, données « A - Transports et activité économique » : recettes et
        dépenses de l'AFITF (A7.2-a, A7.2-b), transferts publics à SNCF Réseau (A5.2-a, A5.2-b), à SNCF Voyageurs
        (A5.1-a, A5.1-b, A5.1-c), dépenses de l'État et de l'AFITF par mode (A4.a), produit du versement
        transport (A6.c)
    transports/transports_afitf_budgets/budget_execute_<an>.pdf, budget_initial_2026.pdf
        AFIT France, budgets exécutés 2022 à 2025 et budget initial 2026 (une page : dépenses par mode en AE et CP,
        recettes par ligne)
    etat/etat_budget_vert_2026.parquet
        Direction du budget, « PLF 2026 - Budget vert » : exécution 2024, LFI 2025, PLF 2026 en CP par action ;
        taxes affectées plafonnées par affectataire (AFITF, VNF, Société des grands projets)
Lecture seule de site/data/arbre/, realisations/, programmes/ (liens, jamais de montant recopié) et de
site/data/local_satellites/index.json (taux de versement mobilité par commune, autre axe).

Sorties (site/data/transports/, contrat docs/contrat_interface.md 2.41, schémas docs/schemas/transports_*) :
    index.json, afitf.json, ferroviaire.json, programmes.json, versement_mobilite.json

Commandes :
    python pipeline/transports.py collecter   # réseau, par collecte/collecte.py ; un refus 401/403/429 est noté,
                                              # jamais contourné
    python pipeline/transports.py produire [--sortie DOSSIER]   # sans réseau

Règles : un tiret, « nd » ou une cellule vide à la source restent null, jamais 0 ; la production s'arrête si une
ligne d'un tableau n'est pas reconnue ou si un budget de l'AFITF relu dans un PDF ne retombe plus sur ses totaux ;
toute date écrite vient de pipeline/reproductible.py : deux productions sur le même entrepôt sont identiques octet
pour octet.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "transports"
CATALOGUE = ROOT / "collecte" / "catalogue.json"
DOMAINES = ("transports", "etat")
LO = "Licence Ouverte 2.0"

SDES_PAGE = "https://www.statistiques.developpement-durable.gouv.fr/bilan-annuel-des-transports-en-2024"
AFITF_PAGE = "https://www.afit-france.fr/budget-simplifie-37"
ECO = "https://data.economie.gouv.fr"

SOURCES = {
    "sdes": {
        "id_catalogue": "transports_sdes_bilan_2024_activite",
        "entrepot": "transports/transports_sdes_bilan_2024_activite.xlsx",
        "titre": "SDES (service statistique du ministère chargé des transports), Bilan annuel des transports en 2024, "
                 "données « A - Transports et activité économique » (données arrêtées au 25 novembre 2025)",
        "producteur": "SDES ; données d'AFIT France, SNCF Réseau, SNCF Voyageurs, DGFiP, Insee, Île-de-France "
                      "Mobilités, Gart, UTP, Cerema, DGITM selon les tableaux",
        "page": SDES_PAGE, "licence": LO, "millesime": "séries jusqu'en 2024",
        "verdict": "réutilisable tel quel (classeur xlsx, un tableau par onglet)",
    },
    "afitf": {
        "id_catalogue": "transports_afitf_budgets",
        "entrepot": "transports/transports_afitf_budgets/",
        "titre": "AFIT France (Agence de financement des infrastructures de transport de France), budgets exécutés "
                 "2022 à 2025 et budget initial 2026, présentation simplifiée (PDF d'une page)",
        "producteur": "AFIT France", "page": AFITF_PAGE,
        "licence": "Licence Ouverte (mentions légales du site afit-france.fr)", "millesime": "2022 à 2026",
        "verdict": "à adapter (PDF lu par position des colonnes, totaux contrôlés)",
    },
    "budget_vert": {
        "id_catalogue": "etat_budget_vert_2026",
        "entrepot": "etat/etat_budget_vert_2026.parquet",
        "titre": "Direction du budget, « PLF 2026 - Budget vert » : crédits de paiement par action (exécution 2024, "
                 "LFI 2025, PLF 2026) et taxes affectées plafonnées par affectataire",
        "producteur": "Direction du budget", "page": f"{ECO}/explore/dataset/plf-2026-budget-vert/",
        "licence": LO, "millesime": "exécution 2024, LFI 2025, PLF 2026",
        "verdict": "réutilisable tel quel (export de l'API Opendatasoft, déjà collecté pour le budget de l'État)",
    },
}

AFITF_FICHIERS = {"2022": ("execute", "budget_execute_2022.pdf"), "2023": ("execute", "budget_execute_2023.pdf"),
                  "2024": ("execute", "budget_execute_2024.pdf"), "2025": ("execute", "budget_execute_2025.pdf"),
                  "2026": ("initial", "budget_initial_2026.pdf")}

INACCESSIBLES = [
    {"source": "Contrats de plan État-région 2021-2027, volet mobilité : montants par région et par cofinanceur",
     "motif": "aucun jeu national ouvert trouvé (data.gouv.fr, data.economie.gouv.fr) ; quatre régions publient leur "
              "maquette sous des formats différents (Hauts-de-France, Provence-Alpes-Côte d'Azur, Normandie, Pays de "
              "la Loire pour 2015-2020) : non assemblées ici ; la part de l'État versée par l'AFITF est publiée "
              "(lignes « CPER » de afitf.json)"},
    {"source": "Programme 355, charge de la dette de SNCF Réseau reprise par l'État",
     "motif": "absent du jeu « Budget vert » ; l'exécution par année est publiée par la vue « prévu et dépensé » "
              "(lien vers realisations/355.json quand le fichier existe)"},
    {"source": "Compensations versées par chaque région pour ses TER, convention par convention",
     "motif": "pas de jeu ouvert national ; seuls les agrégats publiés par le SDES (données SNCF Voyageurs) sont repris"},
    {"source": "Versement mobilité perçu par chaque autorité organisatrice",
     "motif": "pas de jeu ouvert national des montants ; l'Urssaf publie les taux par commune (repris par la vue "
              "« satellites locaux ») et le SDES l'agrégat national par catégorie d'autorité"},
    {"source": "Portail de données de SNCF (ressources.data.sncf.com)",
     "motif": "connexions interrompues pendant la recherche du 18/11/2026 (aucun refus explicite) ; les jeux de "
              "comptes de SNCF Réseau publiés en 2022 s'arrêtent en 2021 : non repris, le SDES publie les transferts "
              "publics jusqu'en 2024"},
]

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Les producteurs publient déjà les agrégats (SDES pour les comptes des transports, AFIT France pour "
                  "son budget, direction du budget pour les programmes et les taxes affectées) : ils sont repris tels "
                  "quels. Aucun dépôt public ne rassemble ces séries avec leurs écarts : module écrit pour le dépôt, "
                  "sur le modèle de pipeline/retraites.py.",
    "trouvailles": [
        {"nom": "SDES, Bilan annuel des transports en 2024 (sept classeurs de données)", "url": SDES_PAGE,
         "licence": LO, "mise_a_jour": "2025-11-25", "verdict": "réutilisable tel quel (classeur A repris)"},
        {"nom": "AFIT France, budgets simplifiés (initial, rectificatifs, exécuté) depuis 2020", "url": AFITF_PAGE,
         "licence": "Licence Ouverte (mentions légales)", "mise_a_jour": "2026-11",
         "verdict": "à adapter (PDF ; exécutés 2022 à 2025 et initial 2026 repris ; 2020 et 2021 sous une autre "
                    "présentation, couverts par la série du SDES)"},
        {"nom": "Direction du budget, PLF 2026 - Budget vert", "url": SOURCES["budget_vert"]["page"], "licence": LO,
         "mise_a_jour": "2025-11-13", "verdict": "réutilisable tel quel"},
        {"nom": "Urssaf, taux de versement mobilité (table_taux_vmrr)",
         "url": "https://open.urssaf.fr/explore/dataset/table_taux_vmrr/", "licence": "ODbL 1.0",
         "mise_a_jour": "2026", "verdict": "déjà repris par la vue « satellites locaux » (taux, pas de montant)"},
        {"nom": "Emet Expertise, taux de versement mobilité par commune avec la zone et l'autorité (data.gouv.fr)",
         "url": "https://www.data.gouv.fr/datasets/6ac1639302460b7e273a4e30", "licence": "ODbL 1.0",
         "mise_a_jour": "2026-11-12", "verdict": "inspiration seulement (taux, déjà couverts par l'Urssaf)"},
        {"nom": "SNCF, comptes de SNCF Réseau (subventions d'investissement, emprunts) depuis 2015",
         "url": "https://www.data.gouv.fr/datasets/5b2201afa3a7297ffee6cc26", "licence": "ODbL 1.0",
         "mise_a_jour": "2022-03-24", "verdict": "inspiration seulement (série arrêtée en 2021)"},
        {"nom": "Régions Hauts-de-France, Provence-Alpes-Côte d'Azur, Normandie : maquettes des CPER 2021-2027",
         "url": "https://www.data.gouv.fr/datasets/69c1d5cebeef6529e5e62cd8", "licence": "variable selon la région",
         "mise_a_jour": "2026-09-26", "verdict": "inspiration seulement (couverture partielle, formats différents)"},
        {"nom": "Dépôts publics GitHub (recherche « AFITF », « comptes des transports », « versement mobilité »)",
         "url": "https://github.com/search?q=AFITF&type=repositories", "licence": "sans objet",
         "dernier_commit": "sans objet", "verdict": "aucun dépôt réutilisable trouvé"},
    ],
}

# --- Utilitaires ------------------------------------------------------------------------------------------------------


def norm(texte) -> str:
    """Libellé normalisé : minuscules, sans accents ni renvois « (1) », espaces et apostrophes unifiés."""
    t = str(texte or "").replace("’", "'").replace("`", "'")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\(\d\)|\*", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def nombre(v):
    """Nombre de la source, ou None (tiret, « nd », vide, texte) : jamais 0 à la place d'une absence."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return None if v != v else v  # NaN
    s = str(v).strip().replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def arrondi(v, d: int = 3):
    n = nombre(v)
    if n is None:
        return None
    r = round(n, d)
    return int(r) if r == int(r) else r


def ecart(objet: str, annee, source: str, valeur, autre_source: str, autre_valeur, lecture: str, d: int = 3,
          tolerance: float = 0.0):
    """Écart entre deux sources, ou None si une valeur manque ou si la différence tient à l'arrondi (`tolerance`)."""
    if valeur is None or autre_valeur is None:
        return None
    diff = valeur - autre_valeur
    if abs(diff) <= tolerance:
        return None
    return {"objet": objet, "annee": annee, "source": source, "valeur": arrondi(valeur, d),
            "autre_source": autre_source, "autre_valeur": arrondi(autre_valeur, d), "ecart": arrondi(diff, d),
            "ecart_pct": round(diff / autre_valeur * 100, 1) if autre_valeur else None, "lecture_ecart": lecture}


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 1_000_000:
        raise SystemExit(f"{path} dépasse 1 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def url_catalogue() -> dict[str, list[str]]:
    """URL de chaque source déclarée au catalogue (une seule vérité pour les adresses)."""
    out = {}
    for s in json.loads(CATALOGUE.read_text(encoding="utf-8"))["sources"]:
        if s["id"] in {v["id_catalogue"] for v in SOURCES.values()}:
            if s["type"] == "urls":
                out[s["id"]] = [u["url"] for u in s["urls"]]
            elif s["type"] == "url":
                out[s["id"]] = [s["url"]]
            else:
                out[s["id"]] = [f"{ECO}/api/explore/v2.1/catalog/datasets/{s['dataset']}/exports/parquet"]
    return out


# --- SDES : tableaux du classeur A -------------------------------------------------------------------------------------

# (id, motif du libellé normalisé) dans l'ordre du tableau ; un libellé inattendu arrête la production.
SPEC_SDES: dict[str, list[tuple[str, str]]] = {
    "A7.2-a": [("ressources", r"^ressources"), ("dotation_capital", r"^dotation en capital"),
               ("avance_tresor", r"^avance du tresor"), ("dividendes_sca", r"^dividendes"),
               ("redevance_domaniale", r"^redevance domaniale"), ("tat", r"^taxe d'amenagement"),
               ("teitld", r"^taxe sur l'exploitation"), ("billets_avion", r"^contribution solidaire"),
               ("amendes_radar", r"^produit des amendes"), ("contribution_sca", r"^contribution exceptionnelle"),
               ("accises_carburants", r"^taxe interieure de consommation"), ("produits_financiers", r"^produits fin"),
               ("produits_exceptionnels", r"^produits exceptionnels"), ("subvention_etat", r"^subvention d'inv"),
               ("emplois", r"^emplois$"), ("charges_courantes", r"^charges courantes"),
               ("depenses_intervention", r"^depenses d'intervention"), ("resultat", r"^resultat d'exploitation"),
               ("depenses_investissement", r"^depenses d'investissement")],
    "A7.2-b": [("hors_cper", r"^operations hors cper"), ("hors_cper.routier", r"^routier$"),
               ("hors_cper.ferroviaire", r"^ferroviaire$"), ("hors_cper.fluvial", r"^fluvial$"),
               ("hors_cper.maritime", r"^maritime$"), ("hors_cper.tca", r"^tca$"),
               ("cper", r"^cper et assimile"), ("cper.routier", r"^routier$"), ("cper.ferroviaire", r"^ferroviaire$"),
               ("cper.fluvial", r"^fluvial$"), ("cper.maritime", r"^maritime$"), ("cper.tca", r"^tca$"),
               ("divers", r"^divers$"), ("total", r"^total$"), ("total.routier", r"^total routier"),
               ("total.ferroviaire", r"^total ferroviaire"), ("total.fluvial", r"^total fluvial"),
               ("total.maritime", r"^total maritime"), ("total.tca", r"^total tca")],
    "A5.2-a": [("union_europeenne", r"^union europeenne"), ("etat_afitf", r"^etat \+ afitf"),
               ("etat_hors_afitf", r"^etat \(hors afitf\)"), ("afitf", r"^afitf$"),
               ("collectivites_autres", r"^collectivites territoriales"), ("regions", r"^regions$"),
               ("departements", r"^departements$"), ("communes", r"^communes$"), ("autres", r"^autres$"),
               ("total", r"^subventions d'investissement$")],
    "A5.2-b": [("reseau_principal", r"^reseau ferre principal"), ("lgv", r"^reseau grande vitesse"),
               ("principal_hors_lgv", r"^reseau principal hors lgv"), ("ile_de_france", r"^reseau ferre ile"),
               ("total", r"^investissements totaux"), ("dont_ppp", r"^dont partenariats")],
    "A5.1-a": [(f"{g}.{r}", m) for g, gm in (("exploitation", r"^exploitation$"),
                                              ("investissement", r"^investissement$"), ("total", r"^total$"))
               for r, m in ((None, gm), ("intercites", r"^sncf-intercites"), ("ter", r"^sncf-ter"),
                            ("transilien", r"^sncf-transilien"), ("ratp", r"^ratp$"), ("tcup", r"^tcup"))],
    "A5.1-b": [("exploitation", r"^contributions liees a l'exploitation"), ("exploitation.etat", r"^versees par l'etat"),
               ("exploitation.regions", r"^versees par les regions"),
               ("exploitation.idfm", r"^versees par .le-de-france"),
               ("fonctionnement_etat", r"^subventions de fonctionnement de l'etat"),
               ("saad", r"^\"?service annexe"), ("dotation_fret", r"^dotation en capital"),
               ("investissement", r"^subventions d'investissement"), ("investissement.etat", r"^versees par l'etat"),
               ("investissement.regions", r"^versees par les regions"),
               ("investissement.idfm", r"^versees par .le-de-france"), ("total", r"^total hors retraites")],
    "A5.1-c": [("tarifs_militaires", r"^versements de l'etat"), ("regions", r"^versements des regions"),
               ("regions.exploitation", r"^contributions d'exploitation"),
               ("regions.exploitation.services", r"^exploitation des services"),
               ("regions.exploitation.tarifs_sociaux", r"^compensation tarifs sociaux"),
               ("regions.investissement", r"^subventions d'investissement"), ("total", r"^total recu")],
    "A6.c": [("province", r"^province$"), ("province.tcsp", r"^autorites organisatrices a tcsp"),
             ("province.plus_100000", r"^autres autorites organisatrices de 100 000"),
             ("province.moins_100000", r"^autorites organisatrices de moins"),
             ("ile_de_france", r"^ile-de-france"), ("ensemble", r"^ensemble$")],
    "A4.a": [(f"{g}{'' if r is None else '.' + r}", m)
             for g, gm in (("fonctionnement", r"^fonctionnement"), ("investissement", r"^investissement"),
                           ("total", r"^total \(hors charges"))
             for r, m in ((None, gm), ("route", r"^route$"), ("fer", r"^fer"),
                          ("tcu", r"^transports collectifs urbains"), ("voies_navigables", r"^voies navigables"),
                          ("maritime", r"^transport maritime"), ("aerien", r"^transport aerien"),
                          ("services_communs", r"^services communs"))]
            + [("retraites", r"^charges de retraites$"), ("retraites.carcept_fongecfa", r"^carcept"),
               ("retraites.sncf", r"^charges de retraites de la sncf"),
               ("retraites.ratp", r"^charges de retraites de la ratp"), ("retraites.enim", r"^enim"),
               ("total_avec_retraites", r"^total \(yc charges")],
}
SPEC_SDES["A5.1-a"] = [((i.removesuffix(".None")), m) for i, m in SPEC_SDES["A5.1-a"]]

TITRES_SDES = {}  # rempli à la lecture (titre de l'onglet)
STATUTS_ANNEE = {"sd": "semi-définitif", "p": "provisoire", "d": "définitif"}


def _annee(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 1990 <= v <= 2100 and v == int(v):
        return int(v), None
    m = re.fullmatch(r"\s*((?:19|20)\d{2})\s*(sd|p|d)?\s*", str(v or ""))
    return (int(m.group(1)), STATUTS_ANNEE.get(m.group(2))) if m else (None, None)


def lire_onglet(wb, nom: str) -> dict:
    """Tableau SDES : années (en-tête), lignes reconnues par SPEC_SDES dans l'ordre, renvois de bas de tableau."""
    lignes = [list(r) for r in wb[nom].iter_rows(values_only=True)]
    titre = next(str(c) for c in lignes[0] if c)
    entete = next(i for i, r in enumerate(lignes) if sum(_annee(c)[0] is not None for c in r[1:]) >= 3)
    cols = [(j, *_annee(c)) for j, c in enumerate(lignes[entete]) if j > 0 and _annee(c)[0] is not None]
    unite = next((str(c).strip() for r in lignes[:entete + 1] for c in r if isinstance(c, str) and "euros" in c), None)
    spec = list(SPEC_SDES[nom])
    out, renvois, absences = {}, [], {}
    for r in lignes[entete + 1:]:
        lib = r[0]
        if lib is None or not str(lib).strip():
            continue
        vals = r[1:]
        if not any(nombre(v) is not None or str(v).strip() == "-" for v in vals if v is not None):
            renvois.append(str(lib).strip())
            continue
        if not spec:
            raise SystemExit(f"SDES {nom} : ligne en trop « {lib} »")
        ident, motif = spec.pop(0)
        if not re.search(motif, norm(lib)):
            raise SystemExit(f"SDES {nom} : ligne « {lib} » inattendue (attendu {ident} : {motif})")
        valeurs = []
        for j, an, _ in cols:
            v = r[j] if j < len(r) else None
            n = nombre(v)
            if n is None:
                absences.setdefault(ident, []).append(
                    {"annee": an, "a_la_source": "-" if str(v).strip() == "-" else ("nd" if str(v).strip() == "nd"
                                                                                     else "cellule vide")})
            valeurs.append(arrondi(n))
        out[ident] = {"libelle": str(lib).strip(), "valeurs": valeurs}
    if spec:
        raise SystemExit(f"SDES {nom} : lignes manquantes {[i for i, _ in spec]}")
    return {"onglet": nom, "titre": titre, "unite": unite, "annees": [an for _, an, _ in cols],
            "statut_annees": {str(an): s for _, an, s in cols if s},
            "lignes": out, "absences": absences, "renvois_source": renvois}


def lire_sdes() -> dict[str, dict]:
    import openpyxl
    wb = openpyxl.load_workbook(LAKE / SOURCES["sdes"]["entrepot"], read_only=True, data_only=True)
    try:
        return {nom: lire_onglet(wb, nom) for nom in SPEC_SDES}
    finally:
        wb.close()


def serie(t: dict, ident: str) -> dict[int, object]:
    return dict(zip(t["annees"], t["lignes"][ident]["valeurs"]))


def tableau_publie(t: dict, ids: list[str] | None = None) -> dict:
    """Forme publiée d'un tableau SDES : lignes alignées sur `annees`."""
    ids = ids or list(t["lignes"])
    return {"onglet": t["onglet"], "titre": t["titre"], "unite": t["unite"], "annees": t["annees"],
            "statut_annees": t["statut_annees"],
            "lignes": [{"id": i, "libelle": t["lignes"][i]["libelle"], "valeurs": t["lignes"][i]["valeurs"]}
                       for i in ids],
            "absences": [{"ligne": i, **a} for i in ids for a in t["absences"].get(i, [])],
            "renvois_source": t["renvois_source"]}


def controle_somme(t: dict, total: str, parties: list[str], objet: str, tol: float = 0.15) -> list[dict]:
    """Écarts (au-delà de l'arrondi) entre un total publié et la somme de ses lignes ; rien n'est corrigé."""
    out = []
    for k, an in enumerate(t["annees"]):
        tv = t["lignes"][total]["valeurs"][k]
        vs = [t["lignes"][p]["valeurs"][k] for p in parties]
        if tv is None or all(v is None for v in vs):
            continue
        s = sum(v for v in vs if v is not None)
        if abs(s - tv) > tol:
            out.append({"objet": objet, "tableau": t["onglet"], "annee": an, "total_publie": tv,
                        "somme_des_lignes": arrondi(s), "ecart": arrondi(tv - s),
                        "lignes": parties, "lignes_vides": [p for p, v in zip(parties, vs) if v is None]})
    return out


# --- AFIT France : budgets en PDF --------------------------------------------------------------------------------------

MODES_AFITF = [("ferroviaire", r"^transport ferroviaire"), ("routier", r"^infrastructures routieres"),
               ("tca", r"^transports collectifs et mobilites"), ("fluvial", r"^voies navigables"),
               ("maritime", r"^ports maritimes"), ("exceptionnels", r"^programmes exceptionnels et littoral"),
               ("support", r"^support$")]
LIGNES_AFITF = {
    "ferroviaire": [("cper", r"^cper ferroviaires"), ("reseau_existant", r"^interventions sur le reseau existant"),
                    ("fret", r"^operations orientees fret"), ("lgv_ciadt", r"^lgv et operations ciadt"),
                    ("materiel_tet", r"^materiels? roulants? tet"), ("traversees_alpines", r"^traversees alpines")],
    "routier": [("cper", r"^cper routiers"), ("operations_particulieres", r"^operations particulieres"),
                ("reseau_existant", r"^interventions sur le reseau existant")],
    "tca": [("cper", r"^cper transports collectifs"), ("appels_a_projets", r"^tca appels a projets"),
            ("mobilites_actives", r"^mobilites actives")],
    "fluvial": [("cper", r"^cper fluvia"), ("seine_nord_europe", r"^canal seine-nord-europe"),
                ("hors_cper", r"^operations hcper")],
    "maritime": [("cper", r"^cper portuaire"), ("hors_cper", r"^operations hcper")],
    "exceptionnels": [("littoral", r"^littoral$"), ("programmes_exceptionnels", r"^programmes exceptionnels$")],
    "support": [],
}
RECETTES_AFITF = [("accises_carburants", r"^(fraction d'accises|ticpe)"), ("tat", r"^taxe d'amenagement"),
                  ("redevances_domaniales", r"^redevances? domaniales?"), ("plan_autoroutier", r"^plan autoroutier"),
                  ("amendes_radars", r"^produit des amendes"), ("secteur_aerien", r"^contribution du secteur aerien"),
                  ("teitld", r"^taxe sur l'exploitation des infrastructures"),
                  ("dotation_relance", r"^dotation budgetaire plan de relance"),
                  ("dotations_budgetaires", r"^dotations budgetaires"), ("total", r"^total$"),
                  ("recettes_diverses", r"^recettes diverses")]
NOMBRE_PDF = re.compile(r"^\d+([,.]\d{2})?$")


def _lignes_pdf(chemin: Path) -> tuple[list[tuple[str, list[tuple[float, float | None]]]], float]:
    """Lignes du PDF : (texte, [(x1, nombre)]) ; un « - » isolé compte comme cellule vide. Seuil AE/CP en x."""
    import pdfplumber
    with pdfplumber.open(chemin) as pdf:
        if len(pdf.pages) != 1:
            raise SystemExit(f"{chemin.name} : {len(pdf.pages)} pages, une seule attendue")
        mots = pdf.pages[0].extract_words()
    groupes: list[list[dict]] = []
    for m in sorted(mots, key=lambda w: (round(w["top"]), w["x0"])):
        if groupes and abs(groupes[-1][0]["top"] - m["top"]) <= 3:
            groupes[-1].append(m)
        else:
            groupes.append([m])
    seuil = None
    out = []
    for g in groupes:
        g.sort(key=lambda w: w["x0"])
        textes = [w["text"] for w in g]
        if "AE" in textes and "CP" in textes and seuil is None:
            cp = g[textes.index("CP")]
            seuil = (cp["x0"] + cp["x1"]) / 2 - 10
            out.append(("<AE CP>", []))
            continue
        texte, nombres, courant = [], [], []
        for w in g:
            t = w["text"]
            if NOMBRE_PDF.match(t):
                courant.append(w)
                if re.search(r"[,.]\d{2}$", t):
                    nombres.append((courant[-1]["x1"], float("".join(x["text"] for x in courant).replace(",", "."))))
                    courant = []
                continue
            if courant:  # chiffres sans décimales : faisaient partie du libellé
                texte += [x["text"] for x in courant]
                courant = []
            if t == "-":
                nombres.append((w["x1"], None))
            elif t != "€":
                texte.append(t)
        texte += [x["text"] for x in courant]
        out.append((" ".join(texte).strip(), nombres))
    if seuil is None:
        raise SystemExit(f"{chemin.name} : en-tête AE / CP introuvable")
    return out, seuil


def _reconnaitre(libelle: str, motifs: list[tuple[str, str]]) -> str | None:
    n = norm(libelle)
    return next((i for i, m in motifs if re.search(m, n)), None)


def lire_budget_afitf(chemin: Path) -> dict:
    """Budget d'une page : dépenses (AE, CP) par mode et par ligne, recettes par ligne ; totaux contrôlés."""
    lignes, seuil = _lignes_pdf(chemin)
    debut = next(i for i, (t, _) in enumerate(lignes) if t == "<AE CP>")
    fin_dep = next(i for i, (t, _) in enumerate(lignes) if i > debut and re.match(r"^(BE )?(RECETTES|RESSOURCES)", t))
    # 1. Recoller les libellés coupés sur deux lignes (texte seul / nombres seuls / texte seul).
    items, i = [], debut + 1
    zone = lignes[debut + 1:fin_dep]
    tous_motifs = MODES_AFITF + [m for v in LIGNES_AFITF.values() for m in v] + [("relance", r"^dont plan de relance"),
                                                                                  ("total", r"^total$")]
    i = 0
    while i < len(zone):
        t, ns = zone[i]
        suivant = zone[i + 1] if i + 1 < len(zone) else None
        if not ns and suivant and suivant[1] and not suivant[0]:   # texte / nombres seuls / texte
            suite = zone[i + 2][0] if i + 2 < len(zone) and not zone[i + 2][1] else ""
            items.append((f"{t} {suite}".strip(), suivant[1]))
            i += 3 if suite else 2
            continue
        if not ns and suivant and suivant[1] and _reconnaitre(t, tous_motifs) is None:   # libellé sur deux lignes
            items.append((f"{t} {suivant[0]}", suivant[1]))
            i += 2
            continue
        items.append((t, ns))
        i += 1
    # 2. Affecter chaque nombre à sa colonne (AE à gauche du seuil, CP à droite).
    def colonnes(ns):
        ae = cp = None
        for x1, v in ns:
            if x1 < seuil:
                ae = v
            else:
                cp = v
        return ae, cp
    modes, mode, total, relance_total = {}, None, None, None
    for lib, ns in items:
        if not lib and not ns:
            continue
        ae, cp = colonnes(ns)
        m = _reconnaitre(lib, MODES_AFITF)
        if m:
            mode = {"libelle": lib, "ae": ae, "cp": cp, "lignes": [], "dont_plan_de_relance": None}
            modes[m] = mode
            continue
        if re.search(r"^total$", norm(lib)):
            total = {"ae": ae, "cp": cp}
            mode = None
            continue
        if re.search(r"^dont plan de relance", norm(lib)):
            if mode is None:
                relance_total = {"ae": ae, "cp": cp}
            else:
                mode["dont_plan_de_relance"] = {"ae": ae, "cp": cp}
            continue
        if mode is None:
            if not ns:
                continue   # titres et mentions hors tableau
            raise SystemExit(f"{chemin.name} : ligne « {lib} » hors d'un mode")
        mid = next(k for k, v in modes.items() if v is mode)
        lid = _reconnaitre(lib, LIGNES_AFITF[mid])
        if lid is None:
            raise SystemExit(f"{chemin.name} : ligne « {lib} » non reconnue dans le mode {mid}")
        mode["lignes"].append({"id": lid, "libelle": lib, "ae": ae, "cp": cp})
    if [k for k, _ in MODES_AFITF] != list(modes) or total is None:
        raise SystemExit(f"{chemin.name} : modes lus {list(modes)}, total {'absent' if total is None else 'lu'}")
    # 3. Recettes.
    recettes, total_recettes = [], None
    attente = ""
    for t, ns in lignes[fin_dep + 1:]:
        if not ns:
            attente = t   # libellé coupé sur deux lignes
            continue
        rid = _reconnaitre(t, RECETTES_AFITF)
        if rid is None and attente:
            t = f"{attente} {t}"
            rid = _reconnaitre(t, RECETTES_AFITF)
        attente = ""
        if rid is None:
            raise SystemExit(f"{chemin.name} : recette « {t} » non reconnue")
        if rid == "total":
            total_recettes = ns[-1][1]
            break
        recettes.append({"id": rid, "libelle": t, "montant": ns[-1][1]})
    # 4. Contrôles : la production s'arrête si un total ne retombe plus sur ses lignes (sauf écart égal au plan de
    #    relance du mode, publié dans `controles`).
    controles = []
    for col in ("ae", "cp"):
        s = sum(v[col] or 0 for v in modes.values())
        if total[col] is not None and abs(s - total[col]) > 1:
            raise SystemExit(f"{chemin.name} : total {col} {total[col]} ≠ somme des modes {s}")
        for mid, v in modes.items():
            if v["lignes"] and v[col] is not None:
                sl = sum(x[col] or 0 for x in v["lignes"])
                if abs(sl - v[col]) > 1:
                    relance = (v["dont_plan_de_relance"] or {}).get(col)
                    if relance is None or abs(v[col] - sl - relance) > 1:
                        raise SystemExit(f"{chemin.name} : mode {mid} {col} {v[col]} ≠ somme des lignes {sl}")
                    controles.append({"mode": mid, "colonne": col, "total_publie": v[col],
                                      "somme_des_lignes": round(sl, 2), "ecart": round(v[col] - sl, 2),
                                      "lecture": "l'écart est égal à la ligne « dont plan de relance » du mode : "
                                                 "dans ce budget, le plan de relance est compté dans le total du "
                                                 "mode sans être réparti entre ses lignes"})
    if total_recettes is None or abs(sum(r["montant"] or 0 for r in recettes) - total_recettes) > 1:
        raise SystemExit(f"{chemin.name} : total des recettes non retrouvé")
    return {"modes": [{"id": k, **v} for k, v in modes.items()], "total": total,
            "dont_plan_de_relance": relance_total, "recettes": recettes, "total_recettes": total_recettes,
            "controles": controles}


# --- Budget vert : programmes et taxes affectées -----------------------------------------------------------------------

PROGRAMMES = [(203, "Infrastructures et services de transports"), (205, "Affaires maritimes, pêche et aquaculture"),
              (612, "Navigation aérienne"), (613, "Soutien aux prestations de l'aviation civile"),
              (614, "Transports aériens, surveillance et certification"),
              (751, "Structures et dispositifs de sécurité routière"),
              (753, "Contrôle et modernisation de la politique de la circulation et du stationnement routiers"),
              (754, "Contribution à l'équipement des collectivités territoriales pour l'amélioration des transports "
                    "en commun, de la sécurité et de la circulation routières")]
AFFECTATAIRES = ["Agence de financement des infrastructures de transport de France (AFITF)",
                 "Voies navigables de France (VNF)", "Société des Grands Projets (SGP)",
                 "Personnes publiques ou privées exploitant des aérodromes"]
COLS_BV = {"execution_2024": "execution_2024_cp", "lfi_2025": "lfi_2025_cp_ou_prevision_2025_si_depense_fiscale",
           "plf_2026": "plf_2026_cp_ou_prevision_2026_si_depense_fiscale"}


def lire_budget_vert() -> list[dict]:
    import pandas as pd
    df = pd.read_parquet(LAKE / SOURCES["budget_vert"]["entrepot"])
    df = df.astype(object).where(df.notna(), None)
    return df.to_dict("records")


def _fichier_existant(motif: str) -> str | None:
    trouves = sorted(SITE.glob(motif))
    return str(trouves[0].relative_to(SITE)) if trouves else None


def liens_programme(num: int) -> list[dict]:
    out = []
    for vue, motif, lecture in (
            ("arbre_etat", f"arbre/*_{num}.json", "exécution 2024 par action, vue du budget de l'État"),
            ("realisations", f"realisations/{num}.json", "prévu et dépensé par année"),
            ("programmes", f"programmes/{num}.json", "fiche du programme")):
        f = _fichier_existant(motif)
        if f:
            out.append({"vue": vue, "fichier": f, "lecture": lecture})
    return out


def programmes_budget_vert(lignes: list[dict]) -> tuple[list[dict], list[dict]]:
    progs = []
    for num, nom in PROGRAMMES:
        rs = [r for r in lignes if r["type_depense"] == "Crédits budgétaires" and nombre(r["numero_programme"]) == num]
        if not rs:
            continue
        actions, autres = {}, {}
        for r in rs:
            code = r["code_action_si_credit_budgetaire"] or ""
            cible = actions if re.fullmatch(rf"{num}-\d+", code) else autres
            e = cible.setdefault(code, {"code": code, "libelle": r["action_si_credit_budgetaire"],
                                        **{k: None for k in COLS_BV}})
            for k, c in COLS_BV.items():
                v = nombre(r[c])
                if v is not None:
                    e[k] = (e[k] or 0) + v
        for e in list(actions.values()) + list(autres.values()):
            for k in COLS_BV:
                e[k] = arrondi(e[k], 0)
        tri = sorted(actions.values(), key=lambda a: a["code"])
        tot = {k: arrondi(sum(a[k] for a in tri if a[k] is not None), 0) for k in COLS_BV}
        progs.append({"numero": num, "nom": rs[0]["programme"] or nom, "mission": rs[0]["mission"],
                      "actions": tri, "total_actions_eur": tot,
                      "lignes_hors_action": sorted(autres.values(), key=lambda a: a["code"]),
                      "liens": liens_programme(num)})
    taxes = []
    for aff in AFFECTATAIRES:
        rs = [r for r in lignes if r["type_depense"] == "Taxes affectées plafonnées"
              and r["affectataire_si_taxe_affectee"] == aff]
        if not rs:
            continue
        ls = [{"libelle": r["libelle"], **{k: arrondi(r[c], 0) for k, c in COLS_BV.items()}} for r in rs]
        taxes.append({"affectataire": aff, "programme": nombre(rs[0]["numero_programme"]) and int(rs[0]["numero_programme"]),
                      "lignes": ls,
                      "total_eur": {k: arrondi(sum(x[k] for x in ls if x[k] is not None), 0) for k in COLS_BV}})
    return progs, taxes


def montant_arbre(num: int) -> float | None:
    f = _fichier_existant(f"arbre/*_{num}.json")
    if not f:
        return None
    md = json.loads((SITE / f).read_text(encoding="utf-8")).get("md")
    return None if md is None else md * 1e9


def lien_local_satellites() -> dict | None:
    if (SITE / "local_satellites" / "index.json").exists():
        return {"vue": "local_satellites", "fichier": "local_satellites/index.json",
                "lecture": "taux de versement mobilité en vigueur par commune et autorité organisatrice (Urssaf, "
                           "Cerema) : un taux, jamais converti en montant par commune"}
    return None


# --- Production -------------------------------------------------------------------------------------------------------

LECTURES = {
    "afitf_sdes_pdf": "même agence, deux publications : la série du SDES reprend les données d'AFIT France (dépenses "
                      "d'intervention mandatées), le PDF de l'agence donne les crédits de paiement exécutés ; les "
                      "deux valeurs sont montrées, aucune n'est retenue à la place de l'autre",
    "taxes_affectees": "le budget vert ne compte que les taxes affectées plafonnées, réparties par destination ; les "
                       "ressources publiées par l'agence comprennent aussi les dotations budgétaires et les recettes "
                       "exceptionnelles : périmètres différents",
    "ter": "deux tableaux du SDES sur les versements des régions pour le TER (données SNCF Voyageurs) : l'un compte les "
           "contributions d'exploitation, l'autre l'ensemble des versements de l'activité TER ; périmètres différents",
    "arbre": "même programme, deux lectures du même jeu : la vue du budget de l'État somme les actions, ici la somme "
             "des actions est aussi donnée sans les lignes hors action (fonds de concours, mesures de périmètre) ; "
             "un écart inférieur à 1 000 euros tient à l'arrondi de la vue du budget de l'État et n'est pas listé",
}


def produire(sortie: Path = SORTIE) -> dict:
    date = date_sources(*DOMAINES)
    urls = url_catalogue()
    sdes = lire_sdes()
    budgets = {}
    for an, (nature, f) in AFITF_FICHIERS.items():
        b = lire_budget_afitf(LAKE / SOURCES["afitf"]["entrepot"] / f)
        budgets[an] = {"annee": int(an), "nature": "budget exécuté" if nature == "execute" else "budget initial",
                       "url": next((u for u in urls.get("transports_afitf_budgets", []) if f"{an}.pdf" in u), None),
                       **b}
    bv = lire_budget_vert()
    progs, taxes = programmes_budget_vert(bv)
    a72a, a72b = sdes["A7.2-a"], sdes["A7.2-b"]

    # Écarts entre sources (montrés, jamais tranchés).
    ecarts = []
    for an, b in budgets.items():
        if b["nature"] != "budget exécuté":
            continue
        a = int(an)
        e = ecart("AFITF, dépenses (M€)", a, "afitf_pdf (CP exécutés)", b["total"]["cp"] / 1e6,
                  "sdes A7.2-b (dépenses d'intervention)", serie(a72b, "total").get(a), LECTURES["afitf_sdes_pdf"])
        e2 = ecart("AFITF, recettes (M€)", a, "afitf_pdf (recettes)", b["total_recettes"] / 1e6,
                    "sdes A7.2-a (ressources hors dotation en capital)", serie(a72a, "ressources").get(a),
                   LECTURES["afitf_sdes_pdf"], tolerance=0.001)
        ecarts += [x for x in (e, e2) if x]
    taxe_afitf = next((t for t in taxes if "AFITF" in t["affectataire"]), None)
    if taxe_afitf:
        e = ecart("AFITF, taxes affectées et ressources 2024 (M€)", 2024, "budget_vert (taxes affectées plafonnées)",
                  (taxe_afitf["total_eur"]["execution_2024"] or 0) / 1e6, "afitf_pdf (total des recettes)",
                  budgets["2024"]["total_recettes"] / 1e6, LECTURES["taxes_affectees"])
        ecarts += [e] if e else []
    a51b, a51c = sdes["A5.1-b"], sdes["A5.1-c"]
    for a in a51b["annees"]:
        e = ecart("Régions, versements pour le TER, exploitation (M€)", a, "sdes A5.1-b (versées par les régions)",
                  serie(a51b, "exploitation.regions").get(a), "sdes A5.1-c (contributions d'exploitation)",
                  serie(a51c, "regions.exploitation").get(a), LECTURES["ter"], tolerance=0.001)
        if e:
            ecarts.append(e)
    for p in progs:
        m = montant_arbre(p["numero"])
        e = ecart(f"Programme {p['numero']}, exécution 2024 (euros)", 2024, "budget_vert (somme des actions)",
                  p["total_actions_eur"]["execution_2024"], "arbre (vue du budget de l'État)", m, LECTURES["arbre"], 0, tolerance=1000)
        if e:
            ecarts.append(e)

    controles = (controle_somme(a72a, "ressources", ["dotation_capital", "avance_tresor", "dividendes_sca",
                                                     "redevance_domaniale", "tat", "teitld", "billets_avion",
                                                     "amendes_radar", "contribution_sca", "accises_carburants",
                                                     "produits_financiers", "produits_exceptionnels",
                                                     "subvention_etat"], "AFITF, ressources")
                 + controle_somme(a72a, "emplois", ["charges_courantes", "depenses_intervention",
                                                    "depenses_investissement"], "AFITF, emplois")
                 + controle_somme(a72b, "total", ["hors_cper", "cper", "divers"], "AFITF, interventions")
                 + controle_somme(sdes["A5.2-a"], "total", ["union_europeenne", "etat_afitf", "collectivites_autres"],
                                  "SNCF Réseau, subventions d'investissement")
                 + controle_somme(sdes["A6.c"], "ensemble", ["province", "ile_de_france"], "Versement transport"))

    entete = lambda cles, millesime, unite: {  # noqa: E731
        "millesime": millesime,
        "source": " ; ".join(f"{SOURCES[c]['titre']} ({SOURCES[c]['page']})" for c in cles),
        "unite": unite, "date_sources": date,
        "sources_url": sorted({u for c in cles for u in urls.get(SOURCES[c]["id_catalogue"], [])})}

    derniere = max(int(a) for a, b in budgets.items() if b["nature"] == "budget exécuté")
    afitf = {
        **entete(["afitf", "sdes", "budget_vert"], f"budgets 2022 à {derniere} exécutés, 2026 initial ; série SDES "
                 f"{a72b['annees'][0]} à {a72b['annees'][-1]}", "euros (budgets de l'agence, budget vert) ; millions "
                 "d'euros (séries du SDES)"),
        "definitions": {
            "ae": "autorisations d'engagement : montants que l'agence s'engage à verser, parfois sur plusieurs années",
            "cp": "crédits de paiement : montants versés dans l'année",
            "cper": "contrats de plan État-région : opérations cofinancées par l'État (ici par l'AFITF) et les "
                    "collectivités ; seule la part versée par l'AFITF figure ici",
            "hors_cper": "opérations décidées hors des contrats de plan (grands projets, appels à projets)",
            "tca": "transports collectifs urbains et mobilités actives (vélo, marche)",
        },
        "modes": {k: m for k, m in (("ferroviaire", "transport ferroviaire"), ("routier", "routes"),
                                    ("tca", "transports collectifs et mobilités actives"),
                                    ("fluvial", "voies navigables"), ("maritime", "ports maritimes"),
                                    ("exceptionnels", "programmes exceptionnels et littoral"),
                                    ("support", "fonctionnement de l'agence"))},
        "budgets": [budgets[a] for a in sorted(budgets)],
        "serie_recettes_depenses": tableau_publie(a72a),
        "serie_interventions_par_mode": tableau_publie(a72b),
        "cper": {
            "lecture": "part des contrats de plan État-région versée par l'AFITF, par mode (série du SDES) et lignes "
                       "« CPER » des budgets de l'agence ; les parts des régions et des autres cofinanceurs ne sont "
                       "pas publiées en données ouvertes nationales",
            "serie": tableau_publie(a72b, ["cper", "cper.routier", "cper.ferroviaire", "cper.fluvial",
                                           "cper.maritime", "cper.tca"]),
            "budgets": [{"annee": b["annee"], "nature": b["nature"],
                         "lignes": [{"mode": m["id"], **{k: x[k] for k in ("libelle", "ae", "cp")}}
                                    for m in b["modes"] for x in m["lignes"] if x["id"] == "cper"]}
                        for b in (budgets[a] for a in sorted(budgets))],
        },
        "taxes_affectees": taxe_afitf,
        "controles": [c for c in controles if c["objet"].startswith("AFITF")],
        "ecarts": [e for e in ecarts if e["objet"].startswith("AFITF")],
    }

    ferro = {
        **entete(["sdes"], f"{sdes['A5.2-a']['annees'][0]} à {sdes['A5.2-a']['annees'][-1]}",
                 "millions d'euros courants (hors taxe pour SNCF Voyageurs)"),
        "sncf_reseau": {
            "subventions_investissement": tableau_publie(sdes["A5.2-a"]),
            "investissements": tableau_publie(sdes["A5.2-b"]),
            "lecture": "subventions d'investissement reçues par SNCF Réseau selon le financeur ; les redevances "
                       "d'accès payées par l'État pour les trains qu'il conventionne figurent dans l'action 41 "
                       "« Ferroviaire » du programme 203 (programmes.json), autre lecture du même argent",
        },
        "sncf_voyageurs": tableau_publie(a51b),
        "ter": tableau_publie(a51c),
        "operateurs_voyageurs": tableau_publie(sdes["A5.1-a"]),
        "trains_equilibre_territoire": {
            "lecture": "les trains d'équilibre du territoire (Intercités) sont conventionnés par l'État : la ligne "
                       "« SNCF-Intercités » du tableau A5.1-a donne les transferts publics reçus pour leur "
                       "exploitation et leur matériel ; la ligne « Matériel roulant TET » des budgets de l'AFITF en "
                       "donne la part versée par l'agence",
            "exploitation": dict(zip(map(str, sdes["A5.1-a"]["annees"]),
                                     sdes["A5.1-a"]["lignes"]["exploitation.intercites"]["valeurs"])),
            "investissement": dict(zip(map(str, sdes["A5.1-a"]["annees"]),
                                       sdes["A5.1-a"]["lignes"]["investissement.intercites"]["valeurs"])),
            "materiel_tet_afitf_cp_eur": {a: next((x["cp"] for m in b["modes"] for x in m["lignes"]
                                                   if x["id"] == "materiel_tet"), None) for a, b in budgets.items()},
        },
        "controles": [c for c in controles if c["objet"].startswith("SNCF")],
        "ecarts": [e for e in ecarts if e["objet"].startswith("Régions")],
        "regle": "les tableaux ne s'additionnent pas entre eux : un même versement peut figurer dans plusieurs "
                 "tableaux (par financeur, par activité, par opérateur) ; les charges de retraite sont exclues par le "
                 "producteur",
    }

    programmes = {
        **entete(["budget_vert", "sdes"], "exécution 2024, LFI 2025, PLF 2026 ; dépenses par mode "
                 f"{sdes['A4.a']['annees'][0]} à {sdes['A4.a']['annees'][-1]}",
                 "euros (crédits de paiement) ; millions d'euros courants (dépenses par mode)"),
        "programmes": progs,
        "programmes_sans_donnee_ici": [
            {"numero": 355, "nom": "Charge de la dette de SNCF Réseau reprise par l'État (crédits évaluatifs)",
             "liens": liens_programme(355),
             "lecture": "absent du jeu « Budget vert » ; exécution par année dans la vue « prévu et dépensé »"},
            {"numero": 198, "nom": "Régimes sociaux et de retraite des transports terrestres",
             "liens": liens_programme(198) + ([{"vue": "retraites", "fichier": "retraites/etat.json",
                                                 "lecture": "crédits de l'État aux régimes spéciaux, par action"}]
                                               if (SITE / "retraites" / "etat.json").exists() else []),
             "lecture": "retraites des agents des transports terrestres : publiées par la vue des retraites"}],
        "colonnes": {"execution_2024": "Exécution 2024 (CP)", "lfi_2025": "LFI 2025 (CP)",
                     "plf_2026": "PLF 2026 (CP)"},
        "taxes_affectees": taxes,
        "depenses_etat_afitf_par_mode": tableau_publie(sdes["A4.a"]),
        "ecarts": [e for e in ecarts if e["objet"].startswith("Programme")],
        "regle": "trois millésimes côte à côte (exécuté, voté, proposé), jamais additionnés ; les lignes hors action "
                 "(fonds de concours, mesures de périmètre) sont publiées à part ; les taxes affectées ne "
                 "s'ajoutent pas aux crédits des programmes",
    }

    a6c = sdes["A6.c"]
    vm = {
        **entete(["sdes"], f"{a6c['annees'][0]} à {a6c['annees'][-1]}", "millions d'euros courants"),
        "serie": tableau_publie(a6c),
        "definition": "contribution des employeurs de 11 salariés et plus, assise sur la masse salariale, perçue par "
                      "les autorités organisatrices de la mobilité (appelée versement transport jusqu'en 2019)",
        "perimetre": "versement perçu par 226 autorités organisatrices (note du producteur) ; Île-de-France "
                     "Mobilités à part ; les autres autorités sont regroupées selon leur taille et leurs réseaux",
        "taux_par_commune": lien_local_satellites(),
        "controles": [c for c in controles if c["objet"].startswith("Versement")],
    }

    def dernier(t, ident):
        return next(((a, v) for a, v in reversed(list(zip(t["annees"], t["lignes"][ident]["valeurs"])))
                    if v is not None), (None, None))

    p203 = next((p for p in progs if p["numero"] == 203), None)
    reperes = [
        {"id": "afitf_depenses_cp", "libelle": "AFITF, dépenses (crédits de paiement exécutés)", "annee": derniere,
         "valeur": budgets[str(derniere)]["total"]["cp"], "unite": "euros", "source": "afitf",
         "fichier": "transports/afitf.json"},
        {"id": "afitf_recettes", "libelle": "AFITF, recettes encaissées", "annee": derniere,
         "valeur": budgets[str(derniere)]["total_recettes"], "unite": "euros", "source": "afitf",
         "fichier": "transports/afitf.json"},
        {"id": "sncf_reseau_subventions", "libelle": "SNCF Réseau, subventions d'investissement publiques reçues",
         **dict(zip(("annee", "valeur"), dernier(sdes["A5.2-a"], "total"))), "unite": "millions d'euros",
         "source": "sdes", "fichier": "transports/ferroviaire.json"},
        {"id": "ter_total_recu", "libelle": "SNCF, versements reçus pour le TER (régions et État)",
         **dict(zip(("annee", "valeur"), dernier(a51c, "total"))), "unite": "millions d'euros",
         "source": "sdes", "fichier": "transports/ferroviaire.json"},
        {"id": "intercites_exploitation", "libelle": "Trains d'équilibre du territoire (Intercités), transferts "
         "publics pour l'exploitation", **dict(zip(("annee", "valeur"), dernier(sdes["A5.1-a"],
                                                                                 "exploitation.intercites"))),
         "unite": "millions d'euros", "source": "sdes", "fichier": "transports/ferroviaire.json"},
        {"id": "programme_203", "libelle": "Programme 203, Infrastructures et services de transports (PLF 2026)",
         "annee": 2026, "valeur": p203["total_actions_eur"]["plf_2026"] if p203 else None, "unite": "euros",
         "source": "budget_vert", "fichier": "transports/programmes.json"},
        {"id": "versement_mobilite", "libelle": "Versement mobilité perçu par les autorités organisatrices",
         **dict(zip(("annee", "valeur"), dernier(a6c, "ensemble"))), "unite": "millions d'euros",
         "statut": a6c["statut_annees"].get(str(dernier(a6c, "ensemble")[0])), "source": "sdes",
         "fichier": "transports/versement_mobilite.json"},
    ]
    index = {
        "millesime": f"2005 à 2026 selon les séries (SDES jusqu'en 2024, AFIT France jusqu'au budget initial 2026, "
                     f"budget vert PLF 2026)",
        "source": "SDES, Bilan annuel des transports en 2024 ; AFIT France, budgets ; direction du budget, budget vert "
                  "PLF 2026",
        "unite": "selon le repère : euros ou millions d'euros courants (champ `unite` de chaque repère)",
        "date_sources": date,
        "fichiers": {"afitf": "transports/afitf.json", "ferroviaire": "transports/ferroviaire.json",
                     "programmes": "transports/programmes.json",
                     "versement_mobilite": "transports/versement_mobilite.json"},
        "reperes": reperes,
        "ecarts": ecarts,
        "controles": controles,
        "regle": "agrégats publiés seulement, aucun bénéficiaire individuel ; une valeur absente, un tiret ou « nd » "
                 "à la source restent null, jamais 0 ; un total publié qui ne retombe pas sur ses lignes est publié "
                 "avec son écart ; deux sources sur le même argent sont montrées côte à côte, jamais additionnées ; "
                 "les tableaux de financeurs et d'opérateurs ne s'additionnent pas entre eux",
        "limites": [
            "séries du SDES arrêtées en 2024, dernière année provisoire selon les tableaux (`statut_annees`)",
            "budgets de l'AFITF lus dans des PDF d'une page : 2022 à 2025 exécutés, 2026 initial ; les budgets "
            "rectificatifs ne sont pas repris",
            "contrats de plan État-région : seule la part versée par l'AFITF est publiée",
            "versement mobilité : agrégat national par catégorie d'autorité, aucun montant par autorité",
            "programmes : crédits de paiement par action du budget vert (exécution 2024, LFI 2025, PLF 2026) ; le "
            "programme 355 n'y figure pas",
        ],
        "liens": [x for x in [lien_local_satellites()] if x],
        "sources": {k: {c: v for c, v in s.items()} for k, s in sorted(SOURCES.items())},
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    dump(sortie / "afitf.json", afitf)
    dump(sortie / "ferroviaire.json", ferro)
    dump(sortie / "programmes.json", programmes)
    dump(sortie / "versement_mobilite.json", vm)
    dump(sortie / "index.json", index)
    print(f"transports : {len(budgets)} budgets AFITF, {len(progs)} programmes, {len(taxes)} affectataires, "
          f"{len(ecarts)} écarts, {len(controles)} écarts de totaux SDES")
    return index


# --- Collecte ---------------------------------------------------------------------------------------------------------

def collecter() -> int:
    ids = [s["id_catalogue"] for s in SOURCES.values()]
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), *ids, "--timeout", "300"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = ap.add_subparsers(dest="cmd")
    sp.add_parser("collecter")
    p = sp.add_parser("produire")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.cmd in ("collecter", None):
        code = collecter()
        if a.cmd == "collecter":
            return code
    produire(getattr(a, "sortie", SORTIE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
