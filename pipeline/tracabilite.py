"""Taux de traçabilité de chaque euro du budget de l'État (exécution 2024), du programme jusqu'au bénéficiaire.

Entrées (sans réseau) : site/data/arbre/racine.json (exécution 2024), site/data/nature/, site/data/beneficiaires/,
site/data/vie_politique/annees.json, site/data/operateurs/operateurs.json (produits par les autres modules), annexes
1 « état CP » des PLRG 2023 et 2024
(data/lake/etat/realisations/, lues par realisations.execution_plrg).

Sorties :
  site/data/tracabilite/programme_<n>.json   un fichier par programme de l'arbre (et noeud_psr_<x>.json pour les
                                              prélèvements sur recettes, feuilles de niveau mission)
  site/data/tracabilite/resume.json          global, par grand poste, par mission, tableau par programme

Commande : python pipeline/tracabilite.py

Modèle. Chaque euro d'un noeud est rangé dans une seule part (les parts somment à 100 %) :
  beneficiaire_identifie  bénéficiaire nommé par une source publique (entité) ou, à défaut, catégorie publique de
                          bénéficiaire désignée par la loi (collectivités pour les prélèvements et les dotations)
  nominatif_par_choix     rémunérations (titre 2) : la catégorie d'agents est publiée, pas les noms (choix légal)
  anonyme_par_nature      charge et amortissement de la dette : les porteurs de titres ne sont pas connus
  non_publie              le reste : la nature est connue (ou non), pas le destinataire
Les « maillons » sont des taux de couverture indépendants : programme (100 %), nature (titre/catégorie publiée),
destinataire connu (somme des trois premières parts), bénéficiaire nommé (entités seulement).

Millésimes : un taux est calculé avec des montants de la même année quand ils existent (statut « exact ») ; sinon il
est « approché » et porte l'écart de millésime en années (`ecart_millesime_ans`) et la raison.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import realisations  # noqa: E402

SITE = ROOT / "site" / "data"
SORTIE = SITE / "tracabilite"
ANNEE = 2024
PARTS = ["beneficiaire_identifie", "nominatif_par_choix", "anonyme_par_nature", "non_publie"]
LIB_PARTS = {
    "beneficiaire_identifie": "Bénéficiaire identifié",
    "nominatif_par_choix": "Nominatif par choix (catégorie d'agents publiée, pas les noms)",
    "anonyme_par_nature": "Anonyme par nature (porteurs de la dette)",
    "non_publie": "Destinataire non publié",
}

SRC_ARBRE = "site/data/arbre/racine.json (exécution 2024, budget vert PLF 2026, CP)"
SRC_NATURE = "data.economie.gouv.fr/plrg-2024, annexe 1 « état titre catégorie » (site/data/nature/)"
SRC_ASSO = ("data.economie.gouv.fr/plf25-donnees-de-l-annexe-jaune-effort-financier-de-l-etat-en-faveur-des-"
            "associations (crédits 2023, site/data/beneficiaires/programme_<n>.json)")
SRC_PLRG23 = "data.economie.gouv.fr, PLRG 2023, annexe 1 « état CP » (dépenses constatées 2023, dénominateur)"
SRC_MARCHES = "data.gouv.fr, DECP consolidées, marchés notifiés en 2024 (site/data/beneficiaires/marches_etat.json)"
SRC_F2030 = "data.gouv.fr, projets France 2030 décidés 2021-2025 (site/data/beneficiaires/france2030.json)"
SRC_VP = "CNCCFP (aide publique aux partis 2024, remboursements de campagne 2024) (site/data/vie_politique/annees.json)"
SRC_NOMENCLATURE = "nomenclature budgétaire LOLF : l'intitulé du programme désigne son unique bénéficiaire (PLF, PAP)"
SRC_PSR = "LFI et PLRG 2024 : prélèvements sur recettes de l'État (destinataire fixé par la loi de finances)"
SRC_OPERATEURS = ("jaune « Opérateurs de l'État » PLF 2026, financement 2022/2024 par le budget de l'État, "
                  "exécution 2024 (site/data/operateurs/operateurs.json)")

# Programmes dont l'intitulé désigne l'unique bénéficiaire (hors dépenses de personnel).
BENEFICIAIRE_NOMENCLATURE = {
    "841": "France Télévisions", "842": "ARTE France", "843": "Radio France", "844": "France Médias Monde",
    "845": "Institut national de l'audiovisuel", "847": "TV5 Monde",
    "511": "Assemblée nationale", "521": "Sénat", "501": "Présidence de la République",
    "541": "La Chaîne parlementaire", "531": "Conseil constitutionnel", "533": "Cour de justice de la République",
    "198": "Caisses de retraite SNCF et RATP (régimes spéciaux des transports terrestres)",
    "195": "Caisse autonome nationale de la sécurité sociale dans les mines et régimes fermés (SEITA...)",
    "197": "Établissement national des invalides de la marine (ENIM)",
}
# Programmes de dotations aux collectivités : la catégorie 63 a pour destinataire les collectivités (catégorie).
DOTATIONS_COLLECTIVITES = {"119", "122"}
# Dette : programme entier anonyme par nature (amortissement), en plus des catégories 41 à 43 partout.
DETTE_PROGRAMMES = {"369"}

# Mission (libellé de l'arbre) -> ministère acheteur des DECP (beneficiaires.MINISTERES).
MISSION_MINISTERE = {
    "Enseignement scolaire": "Éducation nationale, jeunesse et sports",
    "Sport, jeunesse et vie associative": "Éducation nationale, jeunesse et sports",
    "Recherche et enseignement supérieur": "Enseignement supérieur et recherche",
    "Défense": "Armées", "Monde combattant, mémoire et liens avec la Nation": "Armées",
    "Sécurités": "Intérieur et outre-mer", "Administration générale et territoriale de l'État": "Intérieur et outre-mer",
    "Outre-mer": "Intérieur et outre-mer", "Immigration, asile et intégration": "Intérieur et outre-mer",
    "Relations avec les collectivités territoriales": "Intérieur et outre-mer",
    "Solidarité, insertion et égalité des chances": "Travail, santé et solidarités",
    "Travail, emploi et administration des ministères sociaux": "Travail, santé et solidarités",
    "Santé": "Travail, santé et solidarités", "Régimes sociaux et de retraite": "Travail, santé et solidarités",
    "Cohésion des territoires": "Transition écologique et cohésion des territoires",
    "Écologie, développement et mobilité durables": "Transition écologique et cohésion des territoires",
    "Écologie, développement et mobilité durables - Plan de relance":
        "Transition écologique et cohésion des territoires",
    "Gestion des finances publiques": "Économie et finances", "Transformation et fonction publiques":
        "Économie et finances", "Économie": "Économie et finances", "Investir pour la France de 2030":
        "Économie et finances", "Plan de relance": "Économie et finances",
    "Engagements financiers de l'État": "Économie et finances",
    "Direction de l'action du Gouvernement": "Services du Premier ministre",
    "Conseil et contrôle de l'État": "Services du Premier ministre",
    "Agriculture, alimentation, forêt et affaires rurales": "Agriculture et alimentation",
    "Justice": "Justice",
    "Aide publique au développement": "Europe et affaires étrangères",
    "Action extérieure de l'État": "Europe et affaires étrangères",
    "Culture": "Culture", "Médias, livre et industries culturelles": "Culture",
}
POSTES_T2 = {"salaires", "cotisations", "prestations_employeur"}
POSTES_ACHATS = {"fonctionnement", "investissement"}


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 5_000_000:
        raise SystemExit(f"{path} dépasse 5 Mo : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def lire(rel: str):
    p = SITE / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def r2(x: float) -> float:
    return round(x, 2)


def pct(x: float, tot: float) -> float:
    return round(100 * x / tot, 3) if tot else 0.0


# --- Lecture des noeuds de l'arbre ------------------------------------------------------------------------------


def noeuds_arbre() -> tuple[dict, list[dict]]:
    """Racine et liste des feuilles de calcul (programmes, et missions sans programme : prélèvements sur recettes)."""
    racine = lire("arbre/racine.json")
    feuilles = []
    for g in racine["enfants"]:
        for m in g.get("enfants", []):
            progs = [p for p in m.get("enfants", []) if p["niveau"] == "programme"]
            if not progs:
                feuilles.append({"type": "psr", "code": "psr_" + ("union_europeenne" if "Union" in m["nom"]
                                                                  else "collectivites"),
                                 "nom": m["nom"], "mission": m["nom"], "grand_poste": g["nom"], "id_arbre": m["id"],
                                 "eur": m["md"] * 1e9})
            for p in progs:
                feuilles.append({"type": "programme", "code": p["id"].split("/")[-1], "nom": p["nom"],
                                 "mission": m["nom"], "grand_poste": g["nom"], "id_arbre": p["id"],
                                 "eur": p["md"] * 1e9})
    return racine, feuilles


# --- Sources de bénéficiaires -------------------------------------------------------------------------------------


def identifies_groupe(g: dict) -> float:
    """Montant attribué à des personnes morales identifiées (top + autres personnes morales) dans un groupe."""
    return sum(b["montant_eur"] for b in g["top"]) + g["autres_personnes_morales"]["montant_eur"]


def charger_sources() -> dict:
    marches = lire("beneficiaires/marches_etat.json")
    f2030 = lire("beneficiaires/france2030.json")
    vp = lire("vie_politique/annees.json")
    _, par_annee = realisations.execution_plrg()
    s = {"marches": marches, "f2030": f2030, "plrg": par_annee, "vp": None,
         "operateurs": lire("operateurs/operateurs.json")}
    if vp:
        s["vp"] = next((a for a in vp["annees"] if a["annee"] == ANNEE), None)
    return s


def achats_par_ministere(feuilles: list[dict]) -> dict:
    """Base des achats 2024 (catégories 31 et 51 à 53) par ministère, rapportée à l'arbre."""
    base = defaultdict(float)
    for f in feuilles:
        if f["type"] != "programme":
            continue
        m = MISSION_MINISTERE.get(f["mission"])
        nat = lire(f"nature/{f['code']}.json")
        if not m or not nat or not nat["total_eur"]:
            continue
        part = sum(p["eur"] for p in nat["postes"] if p["id"] in POSTES_ACHATS) / nat["total_eur"]
        base[m] += max(part, 0) * f["eur"]
    return base


def scsp_par_programme(feuilles: list[dict], operateurs: dict | None) -> dict[str, list[dict]]:
    """SCSP exécutée en 2024 (catégorie 32) par opérateur nommé, répartie entre ses programmes financeurs.

    Le jaune donne, par opérateur, la SCSP 2024 et la liste de ses programmes financeurs (toutes natures), pas la
    répartition. Ajustement proportionnel itératif (RAS) : la somme par opérateur tend vers sa SCSP (jaune), la somme par
    programme ne dépasse jamais sa catégorie 32 (PLRG). Un opérateur à un seul programme porteur de catégorie 32,
    retrouvé en entier, est exact ; une répartition entre plusieurs programmes est approchée.
    """
    if not operateurs:
        return {}
    cat32 = {}
    for f in feuilles:
        nat = lire(f"nature/{f['code']}.json") if f["type"] == "programme" else None
        if nat and nat["total_eur"] > 0:
            part = sum(p["eur"] for p in nat["postes"] if p["id"] == "subventions_operateurs") / nat["total_eur"]
            if part > 0:
                cat32[f["code"]] = part * f["eur"]
    lignes = []
    for o in operateurs["operateurs"]:
        d = o["annees"].get(str(ANNEE)) or {}
        scsp = ((d.get("financement_etat") or {}).get("scsp") or {}).get("cp_eur") or 0
        progs = [p for p in d.get("programmes_financeurs", []) if p in cat32]
        if d.get("nature") == "execution" and scsp > 0 and progs:
            lignes.append((o, scsp, progs))
    # 1) opérateurs à un seul programme possible : rattachés en entier (plafond : la catégorie 32 du programme)
    mono = defaultdict(float)
    for _, sc, ps in lignes:
        if len(ps) == 1:
            mono[ps[0]] += sc
    x, cap = {}, dict(cat32)
    for i, (_, sc, ps) in enumerate(lignes):
        if len(ps) == 1:
            p = ps[0]
            x[(i, p)] = sc * min(1.0, cat32[p] / mono[p])
    for p, v in mono.items():
        cap[p] = max(cat32[p] - v, 0.0)
    # 2) opérateurs à plusieurs programmes : ajustement proportionnel itératif sur la place restante
    multi = [i for i, (_, _, ps) in enumerate(lignes) if len(ps) > 1]
    y = {}
    for i in multi:
        _, sc, ps = lignes[i]
        poids = sum(cap[q] for q in ps)
        for p in ps:
            y[(i, p)] = sc * cap[p] / poids if poids else 0.0
    for _ in range(500):
        col = defaultdict(float)
        for (i, p), v in y.items():
            col[p] += v
        for k in y:  # programme : jamais plus que sa catégorie 32 restante
            if col[k[1]] > cap[k[1]]:
                y[k] *= cap[k[1]] / col[k[1]]
        lig = defaultdict(float)
        for (i, p), v in y.items():
            lig[i] += v
        if all(abs(lig[i] - lignes[i][1]) < 1 for i in multi if lig[i] > 0):
            break
        for k in y:  # opérateur : vers sa SCSP
            if lig[k[0]] > 0:
                y[k] *= lignes[k[0]][1] / lig[k[0]]
    col = defaultdict(float)
    for (i, p), v in y.items():
        col[p] += v
    for k in y:  # plafond final
        if col[k[1]] > cap[k[1]]:
            y[k] *= cap[k[1]] / col[k[1]]
    x.update(y)
    res = defaultdict(list)
    for (i, p), v in x.items():
        o, s, ps = lignes[i]
        if v > 0.5:
            res[p].append({"operateur": o["nom"], "niveau": "entite" if o["niveau"] == "operateur" else "categorie",
                           "eur": v, "exact": len(ps) == 1 and abs(v - s) < 1, "nb_programmes": len(ps),
                           "scsp_eur": s})
    for p in res:  # exacts d'abord, puis les plus gros montants
        res[p].sort(key=lambda r: (not r["exact"], -r["eur"]))
    return res


# --- Calcul pour une feuille -----------------------------------------------------------------------------------------


def composante(montant: float, source: list[str], millesime: str, ecart: int, raison: str | None, detail: str,
               niveau: str = "entite") -> dict:
    return {"eur": r2(montant), "sources": source, "millesime": millesime, "statut": "exact" if not raison else
            "approche", "ecart_millesime_ans": ecart, "raison_approche": raison, "detail": detail,
            "niveau_identification": niveau}


def calculer_feuille(f: dict, src: dict, achats_min: dict, scsp: dict | None = None) -> dict:
    A = f["eur"]
    code = f["code"]
    comp = {k: [] for k in PARTS}
    if A <= 0:  # programme net négatif (reversements supérieurs aux dépenses) : rien à tracer
        comp["non_publie"].append(composante(A, [SRC_ARBRE], "Exécution 2024", 0, None,
                                             "Montant net négatif (reversements ou annulations supérieurs aux "
                                             "dépenses) : aucun destinataire à tracer", "aucun"))
        return {"comp": comp, "nature_connue": A if lire(f"nature/{code}.json") else 0.0, "ecrete": 0.0, "A": A}
    nature_connue = 0.0
    shares = {}
    nat = lire(f"nature/{code}.json") if f["type"] == "programme" else None
    if nat and nat["total_eur"] > 0:
        nature_connue = A
        shares = {p["id"]: p["eur"] / nat["total_eur"] for p in nat["postes"]}
    if f["type"] == "psr":
        nature_connue = A  # transfert : la nature (prélèvement sur recettes) est fixée par la loi

    t2 = A * sum(v for k, v in shares.items() if k in POSTES_T2)
    dette = A * shares.get("dette", 0.0)
    if code in DETTE_PROGRAMMES:
        dette = A
    t2 = min(max(t2, 0.0), A)
    dette = min(max(dette, 0.0), A - t2)
    if t2 > 0:
        comp["nominatif_par_choix"].append(composante(
            t2, [SRC_NATURE, SRC_ARBRE], "Exécution 2024", 0, None,
            "Rémunérations, cotisations et prestations employeur (titre 2, catégories 21 à 23) : effectifs par "
            "catégorie d'emploi publiés, noms non publiés", "categorie"))
    if dette > 0:
        comp["anonyme_par_nature"].append(composante(
            dette, [SRC_NATURE if code not in DETTE_PROGRAMMES else SRC_NOMENCLATURE, SRC_ARBRE], "Exécution 2024",
            0, None, "Intérêts et amortissement de la dette négociable : détenteurs des titres non connus de l'État",
            "aucun"))

    dispo = A - t2 - dette
    achats = min(dispo, A * sum(v for k, v in shares.items() if k in POSTES_ACHATS)) if shares else 0.0
    achats = max(achats, 0.0)
    autres = dispo - achats  # interventions, opérateurs, opérations financières...
    ident = []  # (montant demandé, cap, composante)
    ecrete = 0.0

    def ajouter(montant, cap_restant, c):
        nonlocal ecrete
        m = min(montant, cap_restant)
        ecrete += max(montant - m, 0.0)
        if m > 0.005:
            c["eur"] = r2(m)
            comp["beneficiaire_identifie"].append(c)
        return m

    if f["type"] == "psr":
        ue = code == "psr_union_europeenne"
        ajouter(A, A, composante(
            A, [SRC_PSR, SRC_ARBRE], "Exécution 2024", 0, None,
            "Prélèvement sur recettes au profit de l'Union européenne (budget de l'Union)" if ue else
            "Prélèvements sur recettes au profit des collectivités territoriales (DGF, FCTVA, compensations) : "
            "catégorie de bénéficiaire fixée par la loi ; la répartition par collectivité 2024 n'est pas dans "
            "l'entrepôt", "entite" if ue else "categorie"))
        dispo = autres = 0.0
    elif code in BENEFICIAIRE_NOMENCLATURE:
        m = ajouter(dispo, dispo, composante(dispo, [SRC_NOMENCLATURE, SRC_ARBRE], "Exécution 2024", 0, None,
                                              f"Bénéficiaire unique désigné par le programme : "
                                              f"{BENEFICIAIRE_NOMENCLATURE[code]}"))
        autres -= m
        dispo -= m
    else:
        reste_autres, reste_achats = autres, achats
        # Vie politique : aide aux partis et remboursements de campagne, même année.
        if code == "232" and src["vp"]:
            vp = src["vp"]
            act = (vp.get("programme_232") or {}).get("actions_eur", {})
            aide = min(vp["aide_publique_partis"]["total_eur"], act.get("financement_des_partis", 0.0))
            remb = min(vp["remboursements_campagne_total_eur"], act.get("organisation_des_elections", 0.0))
            for montant, det in ((aide, f"Aide publique aux partis 2024 ({vp['aide_publique_partis']['nombre_partis']}"
                                         f" partis nommés, plafonnée à l'action 01)"),
                                 (remb, "Remboursements de campagne 2024 (européennes et législatives, candidats "
                                        "nommés par la CNCCFP)")):
                cap = reste_autres + reste_achats
                m = ajouter(montant, cap, composante(montant, [SRC_VP, SRC_ARBRE], "Exécution 2024", 0, None, det))
                d = min(m, reste_autres)
                reste_autres -= d
                reste_achats -= m - d
        # Dotations aux collectivités (catégorie 63).
        if code in DOTATIONS_COLLECTIVITES and shares:
            dot = A * shares.get("interventions_collectivites", 0.0)
            m = ajouter(dot, reste_autres, composante(
                dot, [SRC_NATURE, SRC_ARBRE], "Exécution 2024", 0, None,
                "Dotations aux collectivités (catégorie 63) : catégorie de bénéficiaire connue, répartition par "
                "collectivité non disponible dans l'entrepôt pour 2024", "categorie"))
            reste_autres -= m
        # Opérateurs de l'État : SCSP 2024 (catégorie 32) par opérateur nommé ou catégorie d'opérateurs (jaune).
        if scsp and code in scsp and shares:
            reste32 = min(A * shares.get("subventions_operateurs", 0.0), reste_autres)
            for x in scsp[code]:
                raison = None if x["exact"] else (
                    f"SCSP 2024 de l'opérateur ({round(x['scsp_eur'] / 1e6, 1)} M€) répartie entre ses "
                    f"{x['nb_programmes']} programmes financeurs par ajustement proportionnel sur la catégorie 32 de "
                    f"chaque programme (le jaune ne ventile pas la SCSP par programme)" if x["nb_programmes"] > 1 else
                    "SCSP 2024 de l'opérateur supérieure à la catégorie 32 restante du programme : plafonnée")
                m = ajouter(x["eur"], reste32, composante(
                    x["eur"], [SRC_OPERATEURS, SRC_NATURE, SRC_ARBRE], "Exécution 2024", 0, raison,
                    f"Subvention pour charges de service public 2024 : {x['operateur']}"
                    + (" (catégorie d'opérateurs, montant non publié par établissement)"
                       if x["niveau"] == "categorie" else ""), x["niveau"]))
                reste32 -= m
                reste_autres -= m
        # France 2030 : part des aides décidées allant à des personnes morales nommées.
        f2 = src["f2030"]
        if f2 and code in f2.get("par_programme", {}):
            ens = f2["ensemble"]
            part_nommee = identifies_groupe(ens) / ens["total_eur"] if ens["total_eur"] else 0.0
            base = reste_autres + reste_achats
            montant = base * part_nommee
            m = ajouter(montant, base, composante(
                montant, [SRC_F2030, SRC_ARBRE], "Projets décidés 2021-2025 appliqués à l'exécution 2024", 0,
                "Part des aides décidées (engagements cumulés 2021-2025) allant à des personnes morales nommées, "
                "appliquée aux paiements 2024 du programme",
                f"France 2030 : {round(100 * part_nommee, 1)} % des aides décidées vont à des personnes morales "
                f"nommées"))
            d = min(m, reste_autres)
            reste_autres -= d
            reste_achats -= m - d
        # Associations (crédits 2023) : taux calculé sur les dépenses 2023 du programme, appliqué à 2024.
        prog_b = lire(f"beneficiaires/programme_{code}.json")
        if prog_b and prog_b.get("associations"):
            a = prog_b["associations"]
            nommes_2023 = identifies_groupe(a)
            dep23 = (src["plrg"].get(2023, {}).get(code) or {}).get("depenses", 0.0)
            if dep23 > 0:
                taux = min(nommes_2023 / dep23, 1.0)
                sources = [SRC_ASSO, SRC_PLRG23, SRC_ARBRE]
                raison = ("Associations : crédits versés en 2023 rapportés aux dépenses 2023 du programme (même "
                          "année), taux appliqué à l'exécution 2024")
            else:
                taux = min(nommes_2023 / A, 1.0) if A else 0.0
                sources = [SRC_ASSO, SRC_ARBRE]
                raison = "Associations : crédits 2023 rapportés à l'exécution 2024 (programme absent du PLRG 2023)"
            montant = taux * A
            m = ajouter(montant, reste_autres, composante(
                montant, sources, "Crédits 2023, taux appliqué à 2024", 1, raison,
                f"Associations nommées (personnes morales, jaune PLF 2025) : {round(100 * taux, 2)} % des "
                f"dépenses du programme"))
            reste_autres -= m
        # Marchés de l'État notifiés en 2024, rattachés au ministère, appliqués aux achats du programme.
        mn = MISSION_MINISTERE.get(f["mission"])
        mar = src["marches"]
        if mar and mn and mn in mar["par_ministere"] and achats_min.get(mn) and reste_achats > 0:
            nommes = identifies_groupe(mar["par_ministere"][mn])
            taux = min(nommes / achats_min[mn], 1.0)
            montant = taux * achats
            m = ajouter(montant, reste_achats, composante(
                montant, [SRC_MARCHES, SRC_NATURE, SRC_ARBRE], "Marchés notifiés en 2024", 0,
                "Montants notifiés (valeur du marché, parfois pluriannuelle) et non payés ; rattachement au "
                "ministère acheteur (le programme n'existe pas dans les DECP), réparti au prorata des achats "
                "(catégories 31 et 51 à 53)",
                f"Marchés de l'État ({mn}) : titulaires nommés = {round(100 * taux, 1)} % des achats 2024 du "
                f"ministère"))
            reste_achats -= m

    total_ident = sum(c["eur"] for c in comp["beneficiaire_identifie"])
    non_pub = max(A - t2 - dette - total_ident, 0.0)
    if non_pub > 0.005:
        comp["non_publie"].append(composante(
            non_pub, [SRC_ARBRE] + ([SRC_NATURE] if nat else []), "Exécution 2024", 0, None,
            "Résidu : montant du noeud moins les parts tracées" + ("" if nat else " (nature non publiée)"),
            "aucun"))
    return {"comp": comp, "nature_connue": nature_connue, "ecrete": ecrete, "A": A}


# --- Agrégation ----------------------------------------------------------------------------------------------------


def synthese(A: float, comps: dict, nature_connue: float) -> dict:
    parts = {}
    for k in PARTS:
        lst = comps[k]
        eur = sum(c["eur"] for c in lst)
        approche = any(c["statut"] == "approche" for c in lst)
        sources = sorted({s for c in lst for s in c["sources"]})
        parts[k] = {"libelle": LIB_PARTS[k], "eur": r2(eur), "pct": pct(eur, A),
                    "statut": "approche" if approche else "exact",
                    "ecart_millesime_ans": max([c["ecart_millesime_ans"] for c in lst], default=0),
                    "sources": sources}
    # ajustement d'arrondi : la plus grande part absorbe l'écart pour sommer exactement à 100
    if A < 0:
        for k in PARTS:
            parts[k]["pct"] = 100.0 if k == "non_publie" else 0.0
    tot = round(sum(p["pct"] for p in parts.values()), 3)
    if A and abs(tot - 100) > 0:
        kmax = max(parts, key=lambda k: parts[k]["eur"])
        parts[kmax]["pct"] = round(parts[kmax]["pct"] + 100 - tot, 3)
    ident = comps["beneficiaire_identifie"]
    entite = sum(c["eur"] for c in ident if c["niveau_identification"] == "entite")
    destinataire = sum(parts[k]["eur"] for k in PARTS[:3])
    maillons = [
        {"maillon": "programme", "libelle": "Programme", "pct": 100.0 if A else 0.0, "statut": "exact",
         "sources": [SRC_ARBRE]},
        {"maillon": "nature", "libelle": "Nature (titre et catégorie)", "pct": pct(nature_connue, A),
         "statut": "exact", "sources": [SRC_NATURE] if nature_connue else []},
        {"maillon": "destinataire", "libelle": "Destinataire connu (bénéficiaire, catégorie d'agents ou dette)",
         "pct": pct(destinataire, A), "statut": "approche" if any(parts[k]["statut"] == "approche" for k in PARTS[:3])
         else "exact", "sources": sorted({s for k in PARTS[:3] for s in parts[k]["sources"]})},
        {"maillon": "beneficiaire_nomme", "libelle": "Bénéficiaire nommé (entité)", "pct": pct(entite, A),
         "statut": "approche" if any(c["statut"] == "approche" for c in ident if c["niveau_identification"] ==
                                     "entite") else "exact",
         "sources": sorted({s for c in ident if c["niveau_identification"] == "entite" for s in c["sources"]})},
    ]
    for m in maillons:
        if not m["pct"]:
            m["sources"] = m["sources"] or []
    return {"total_eur": r2(A), "parts": parts, "maillons": maillons,
            "taux_tracabilite_pct": pct(destinataire, A)}


def main() -> None:
    racine, feuilles = noeuds_arbre()
    src = charger_sources()
    achats_min = achats_par_ministere(feuilles)
    scsp = scsp_par_programme(feuilles, src["operateurs"])
    SORTIE.mkdir(parents=True, exist_ok=True)
    for f in SORTIE.glob("*.json"):
        f.unlink()
    agg = defaultdict(lambda: {"A": 0.0, "nat": 0.0, "comp": {k: [] for k in PARTS}, "ecrete": 0.0})
    lignes = []
    for f in feuilles:
        r = calculer_feuille(f, src, achats_min, scsp)
        syn = synthese(r["A"], r["comp"], r["nature_connue"])
        nom_fichier = (f"programme_{f['code']}.json" if f["type"] == "programme" else f"noeud_{f['code']}.json")
        dump(SORTIE / nom_fichier, {
            "annee": str(ANNEE), "millesime": "Exécution 2024", "unite": "euros (crédits de paiement)",
            "source": " ; ".join(sorted({s for k in PARTS for s in syn["parts"][k]["sources"]})) or SRC_ARBRE,
            "niveau": "programme" if f["type"] == "programme" else "mission",
            "programme": f["code"] if f["type"] == "programme" else None, "id_arbre": f["id_arbre"],
            "libelle": f["nom"], "mission": f["mission"], "grand_poste": f["grand_poste"], **syn,
            "composantes": {k: r["comp"][k] for k in PARTS}, "ecrete_eur": r2(r["ecrete"]),
            "note_ecrete": "montant des sources de bénéficiaires dépassant la place disponible dans le noeud (non "
                           "compté)" if r["ecrete"] else None})
        for cle in ("racine", "gp:" + f["grand_poste"], "m:" + f["grand_poste"] + "/" + f["mission"]):
            a = agg[cle]
            a["A"] += r["A"]
            a["nat"] += r["nature_connue"]
            a["ecrete"] += r["ecrete"]
            for k in PARTS:
                a["comp"][k].extend(r["comp"][k])
        lignes.append({"id": f["code"], "libelle": f["nom"], "mission": f["mission"], "grand_poste": f["grand_poste"],
                       "fichier": f"tracabilite/{nom_fichier}", "total_eur": syn["total_eur"],
                       "taux_tracabilite_pct": syn["taux_tracabilite_pct"],
                       **{f"{k}_pct": syn["parts"][k]["pct"] for k in PARTS},
                       "approche": any(syn["parts"][k]["statut"] == "approche" for k in PARTS)})

    def bloc(cle, **extra):
        a = agg[cle]
        return {**extra, **synthese(a["A"], a["comp"], a["nat"]), "ecrete_eur": r2(a["ecrete"])}

    gps = [bloc("gp:" + g["nom"], id=g["id"], nom=g["nom"], niveau="grand_poste") for g in racine["enfants"]]
    missions = [bloc("m:" + g["nom"] + "/" + m["nom"], id=m["id"], nom=m["nom"], niveau="mission",
                     grand_poste=g["nom"]) for g in racine["enfants"] for m in g.get("enfants", [])]
    glob = bloc("racine", id="racine", nom=racine["nom"], niveau="racine")
    if abs(glob["total_eur"] - racine["md"] * 1e9) > 1e6:
        raise SystemExit(f"Somme des feuilles {glob['total_eur']} != racine {racine['md'] * 1e9}")
    dump(SORTIE / "resume.json", {
        "annee": str(ANNEE), "millesime": "Exécution 2024", "unite": "euros (crédits de paiement)",
        "source": SRC_ARBRE, "parts": LIB_PARTS,
        "methode": ("Chaque euro d'un noeud est rangé dans une seule part (somme = 100 %). Ordre d'attribution : "
                    "titre 2 (nominatif par choix), dette (anonyme), puis bénéficiaires identifiés par source dans la "
                    "place restante (achats pour les marchés, autres dépenses pour associations, France 2030, partis, "
                    "dotations, subventions pour charges de service public aux opérateurs), le reste est non publié. Un taux est « exact » quand numérateur et dénominateur sont "
                    "de la même année et de même nature, sinon « approché » avec l'écart de millésime et la raison."),
        "limites": [
            "Associations : crédits 2023 (dernier jaune publié), taux 2023 appliqué à 2024.",
            "Marchés : montants notifiés en 2024 (valeur du marché), rattachés au ministère et non au programme.",
            "France 2030 : engagements cumulés 2021-2025, part nommée appliquée aux paiements 2024.",
            "Collectivités (prélèvements sur recettes, dotations 119 et 122) : catégorie de bénéficiaire ; "
            "répartition 2024 par collectivité absente de l'entrepôt.",
            "Subventions aux opérateurs (catégorie 32) : SCSP 2024 par opérateur (jaune « Opérateurs de l'État » "
            "PLF 2026) ; un opérateur financé par plusieurs programmes est réparti par ajustement proportionnel sur la "
            "catégorie 32 des programmes (approché) ; une catégorie d'opérateurs (universités, ARS...) est un "
            "bénéficiaire de niveau catégorie.",
        ],
        "global": glob, "grands_postes": gps, "missions": missions, "programmes": lignes})
    print(f"traçabilité globale {glob['taux_tracabilite_pct']} % ; fichiers {len(feuilles) + 1}", file=sys.stderr)
    for g in gps:
        print(f"  {g['nom']}: {g['taux_tracabilite_pct']} % (identifié {g['parts']['beneficiaire_identifie']['pct']})",
              file=sys.stderr)


if __name__ == "__main__":
    main()
