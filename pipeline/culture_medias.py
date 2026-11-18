"""Culture et médias : budget de la culture par programme et par action, audiovisuel public, aides à la presse,
soutiens du Centre national du cinéma et de l'image animée (CNC).

Uniquement des documents publiés, déclarés dans collecte/catalogue.json (entrées `culture_medias_*`) :
    - budget vert du PLF 2026 (data.economie.gouv.fr) : exécution 2024, LFI 2025 et PLF 2026 par action, dépenses
      fiscales et taxes affectées rattachées aux missions ;
    - annexes des projets de loi relatifs aux résultats de la gestion (PLRG) 2023, 2024 et 2025 : crédits par
      programme du budget général (2025), crédits et recouvrements des comptes spéciaux ;
    - tableaux du ministère de la Culture sur les aides à la presse (data.gouv.fr) ;
    - Bilan 2025 du CNC (PDF, pages 271 et 272).

Commandes :
    python pipeline/culture_medias.py collecter   (réseau, par collecte/collecte.py ; un refus 401/403/429 est
                                                  noté, jamais contourné)
    python pipeline/culture_medias.py produire [--sortie DOSSIER]   (sans réseau ; lit data/lake/culture_medias/)

Sorties (site/data/culture_medias/, contrat docs/contrat_interface.md, schémas docs/schemas/culture_medias_*) :
    index.json, budget.json, audiovisuel.json, presse.json, cnc.json

Règles : une cellule vide, « nc » ou « ε » à la source reste null avec sa mention, jamais 0 ; une somme faite ici
porte le statut « calculé » ; deux sources ou deux millésimes sont mis côte à côte, jamais additionnés ; un écart
entre sources est publié, jamais corrigé. Titres et groupes de presse : noms passés par local.objet_publiable
(nom masqué, montant conservé, si un nom de personne est possible). Dates par pipeline/reproductible.py : deux
productions sur le même entrepôt sont identiques octet pour octet.
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
LAKE = ROOT / "data" / "lake" / "culture_medias"
MANIFESTE = ROOT / "data" / "lake" / "manifest.json"
SORTIE = ROOT / "site" / "data" / "culture_medias"
DOMAINE = "culture_medias"
ODS = "https://data.economie.gouv.fr/explore/dataset"
DG = "https://www.data.gouv.fr/datasets"


class DonneeInattendue(RuntimeError):
    """La source ne ressemble plus à ce que le module sait lire : la production s'arrête."""


# ------------------------------------------------------------------------------------------------------ sources

SOURCES = {
    "budget_vert": {
        "id_catalogue": "culture_medias_budget_vert_plf2026",
        "titre": "PLF 2026, budget vert : exécution 2024, LFI 2025 et PLF 2026 par action, dépenses fiscales et taxes "
                 "affectées (direction du Budget)",
        "page": f"{ODS}/plf-2026-budget-vert/", "licence": "Licence Ouverte 2.0"},
    "plrg": {
        "id_catalogue": "culture_medias_plrg_annexes",
        "titre": "Projets de loi relatifs aux résultats de la gestion 2023, 2024 et 2025, annexes 1 et 2 (crédits de "
                 "paiement par programme, recouvrements des comptes spéciaux)",
        "page": f"{ODS}/projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-"
                "lannee-plrg-2025/", "licence": "Licence Ouverte 2.0"},
    "presse_titres": {
        "id_catalogue": "culture_medias_presse_titres",
        "titre": "Aides à la presse : classement des titres de presse aidés (ministère de la Culture)",
        "page": f"{DG}/5c5e558f06e3e7266c232bba", "licence": "Licence Ouverte 2.0"},
    "presse_groupes": {
        "id_catalogue": "culture_medias_presse_groupes",
        "titre": "Aides à la presse : classement des principaux groupes de presse aidés (ministère de la Culture)",
        "page": f"{DG}/5c5e55799ce2e76ae9b7f491", "licence": "Licence Ouverte 2.0"},
    "cnc": {
        "id_catalogue": "culture_medias_cnc_bilan_2025",
        "titre": "Bilan 2025 du Centre national du cinéma et de l'image animée, chapitre 7.1 « Les financements "
                 "publics » (pages 271 et 272)",
        "page": "https://www.cnc.fr/documents/36995/2559242/Bilan+2025+du+CNC.pdf/1611bc6c-9fe2-6706-2dd7-"
                "1febe12a05aa?t=1792077261957",
        "licence": "document administratif public (graphiques relus et vérifiés dans le texte du PDF)"},
}

# Tableaux par dispositif d'aide à la presse (ministère de la Culture, data.gouv.fr) : id, libellé, jeu, colonnes.
DISPOSITIFS_PRESSE = [
    ("pluralisme_regionale", "Aide au pluralisme de la presse périodique régionale et locale",
     "5af120e2a3a7295e54c41a11"),
    ("pluralisme_en_ligne", "Aide au pluralisme des services de presse tout en ligne", "64ffe26548c71b35f5bedb7a"),
    ("pluralisme_ultramarins", "Aide au pluralisme des titres ultramarins", "64ffe268165699ecb9ae9bff"),
    ("quotidiens_faibles_ressources_pa", "Aide aux quotidiens régionaux, départementaux et locaux à faibles "
     "ressources de petites annonces", "5af12104b595087cfabcde8e"),
    ("exemplaire_poste", "Aide à l'exemplaire des titres de presse postés", "6688c177f39a615a6b1cbe7f"),
    ("distribution_pqn", "Aide à la distribution de la presse quotidienne nationale", "5af120d9b595087cfabcde7a"),
    ("exemplaire_porte", "Aide à l'exemplaire des titres de presse portés (aide au portage avant 2023)",
     "5af12105a3a7295e54c41a1f"),
    ("publications_faibles_ressources_pub", "Aides aux publications nationales d'information politique et générale "
     "à faibles ressources publicitaires", "5af120f1a3a7295e54c41a17"),
    ("fseip", "Fonds de soutien à l'émergence et à l'innovation dans la presse", "5c67b11f06e3e727a17bb849"),
    ("fsdp", "Fonds stratégique pour le développement de la presse", "5890bf78a3a72974cbf0dc94"),
]
for _k, _lib, _ds in DISPOSITIFS_PRESSE:
    SOURCES[f"presse_{_k}"] = {"id_catalogue": f"culture_medias_presse_{_k}",
                               "titre": f"{_lib} : montant par titre et par année (ministère de la Culture)",
                               "page": f"{DG}/{_ds}", "licence": "Licence Ouverte 2.0"}

MISSIONS_BUDGET = ["Culture", "Médias, livre et industries culturelles"]
MISSION_AUDIOVISUEL = "Avances à l'audiovisuel public"
MISSION_AUDIOVISUEL_BG = "Audiovisuel public"   # budget général, PLF 2025 seulement (lignes de transfert)
SOCIETES = {841: "France Télévisions", 842: "ARTE France", 843: "Radio France", 844: "France Médias Monde",
            845: "Institut national de l'audiovisuel", 847: "TV5 Monde", 848: "Programme de transformation"}
ANNEES_PLRG = (2023, 2024, 2025)

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "conclusion": "Les producteurs publient déjà les montants voulus (budget vert du PLF 2026 par action, annexes "
                  "CSV des PLRG, tableaux CSV des aides à la presse) : ils sont repris tels quels. Le CNC ne publie "
                  "ses soutiens par dispositif que dans un graphique de son Bilan annuel (PDF), relu ici. Aucun dépôt "
                  "public trouvé ne consolide ces sources ; le module suit pipeline/justice_defense.py et "
                  "pipeline/retraites.py.",
    "trouvailles": [
        {"nom": "PLF 2026, budget vert (data.economie.gouv.fr)", "url": f"{ODS}/plf-2026-budget-vert/",
         "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2025-11-13"},
        {"nom": "PLRG 2023, 2024, 2025, annexes CSV (data.economie.gouv.fr)",
         "url": f"{ODS}/plrg-2024/", "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0",
         "mise_a_jour": "2026"},
        {"nom": "Aides à la presse : classement des titres et des groupes aidés, tableaux par dispositif "
                "(ministère de la Culture, data.gouv.fr et culture.data.gouv.fr)",
         "url": f"{DG}/565db6f2c751df2d32aad370", "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-11-09"},
        {"nom": "Bilan 2025 du CNC (PDF), chapitre 7.1", "url": SOURCES["cnc"]["page"], "verdict": "à adapter",
         "licence": "document administratif public (graphique relu et vérifié dans le texte)",
         "mise_a_jour": "2026"},
        {"nom": "Jeux du CNC sur data.gouv.fr (34 jeux : fréquentation, production, audiences)",
         "url": f"{DG}/?organization=534fff5fa3a7292c64a77d49", "verdict": "inspiration seulement",
         "licence": "Licence Ouverte 2.0 (aucun jeu des aides par dispositif)", "mise_a_jour": "2026-11-13"},
        {"nom": "Syndicat de la presse indépendante d'information en ligne, « Aides à la presse » (data.gouv.fr)",
         "url": f"{DG}/559bd138c751df0767390bd5", "verdict": "inspiration seulement",
         "licence": "non retenue (reprise des tableaux du ministère par un tiers)", "mise_a_jour": "2026-11-17"},
        {"nom": "collecte/collecte.py, pipeline/reproductible.py, pipeline/local.py (objet_publiable)",
         "url": "collecte/collecte.py", "verdict": "réutilisable tel quel", "licence": "MIT",
         "mise_a_jour": "2026-11-17"},
    ],
}

SOURCES_INACCESSIBLES = [
    {"source": "budget.gouv.fr, documents budgétaires du PLF et de la LFI 2026 (projets annuels de performances)",
     "url": "https://www.budget.gouv.fr/documentation/documents-budgetaires",
     "constat": "Page protégée par un dispositif anti-robot (réponse « Request unsuccessful », Incapsula) le "
                "2026-11-18 : non contourné. La LFI 2026 par action n'est donc pas reprise ; le PLF 2026 vient du "
                "budget vert.", "date": "2026-11-18"},
    {"source": "performance-publique.budget.gouv.fr (budget initial du CNC et des opérateurs, projets annuels)",
     "url": "https://www.performance-publique.budget.gouv.fr/",
     "constat": "Serveur indisponible (erreur 502 au proxy) le 2026-11-18.", "date": "2026-11-18"},
    {"source": "data.economie.gouv.fr, PLF 2026 et LFI 2026 selon la destination",
     "url": f"{ODS}/plf25-depenses-2025-selon-destination/",
     "constat": "Aucun jeu « selon destination » publié pour 2026 au 2026-11-18 (le plus récent porte sur le PLF "
                "2025).", "date": "2026-11-18"},
    {"source": "Ministère de la Culture, classement des titres de presse aidés pour 2024 et 2025",
     "url": f"{DG}/5c5e558f06e3e7266c232bba",
     "constat": "Le tableau consolidé s'arrête à 2023 au 2026-11-18 ; les tableaux par dispositif vont jusqu'à "
                "2025 (sans 2024).", "date": "2026-11-18"},
    {"source": "Centre national du cinéma et de l'image animée, aides par bénéficiaire en données ouvertes",
     "url": f"{DG}/?organization=534fff5fa3a7292c64a77d49",
     "constat": "Aucun jeu ouvert des aides par dispositif ou par bénéficiaire : seuls les agrégats du Bilan "
                "annuel (PDF) sont repris.", "date": "2026-11-18"},
]


# -------------------------------------------------------------------------------------------------- utilitaires

def nombre(x) -> float | None:
    """Nombre publié (« 1 234,5 », « 47451633.32 ») ; vide, « nc », « ε », tiret : None, jamais 0."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return None if x != x else float(x)
    s = str(x).strip().replace("\xa0", "").replace(" ", "").replace(" ", "").replace("€", "")
    s = s.replace(",", ".").replace("−", "-")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return None
    return float(s)


def euros(x) -> int | None:
    v = nombre(x)
    return None if v is None else int(round(v))


def _arrondi(v: float | None, n: int) -> float | None:
    return None if v is None else round(v, n)


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _propre(s) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(s or ""))).strip()


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


def _un_fichier(cle: str, suffixe: str) -> Path:
    f = _fichiers(cle, suffixe)
    if not f:
        raise FileNotFoundError(f"data/lake/culture_medias/{SOURCES[cle]['id_catalogue']} absent : lancer collecter")
    return f[0]


def lire_csv(chemin: Path) -> list[dict]:
    """CSV « ; » (BOM toléré) ; en-têtes ramenés à une ligne."""
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        lignes = list(csv.reader(f, delimiter=";"))
    if not lignes:
        return []
    entete = [_propre(c) for c in lignes[0]]
    return [dict(zip(entete, ligne)) for ligne in lignes[1:] if any(c.strip() for c in ligne)]


def _colonne(entete, *motifs: str) -> str:
    """Première colonne dont le nom normalisé contient tous les motifs."""
    for c in entete:
        n = _norm(c)
        if all(m in n for m in motifs):
            return c
    raise DonneeInattendue(f"colonne introuvable ({' + '.join(motifs)}) parmi {list(entete)}")


def _programme(libelle: str) -> tuple[str, int]:
    """« Création - 131 » -> (« Création », 131)."""
    m = re.match(r"^(.*?)\s*-\s*(\d{3})\s*$", _propre(libelle))
    if not m:
        raise DonneeInattendue(f"libellé de programme inattendu : {libelle!r}")
    return m.group(1), int(m.group(2))


# ------------------------------------------------------------------------------------------- budget vert (PLF 2026)

COLS_BV = {"execution_2024_eur": "execution_2024_cp", "lfi_2025_eur": "lfi_2025_cp_ou_prevision_2025_si_depense_fiscale",
           "plf_2026_eur": "plf_2026_cp_ou_prevision_2026_si_depense_fiscale"}
MENTION_DF = "depenses_fiscales_e_montant_inferieur_a_0_5_meur_nc_montant_non_calcule_en_prevision_2026"
MENTIONS = {"nc": "nc : montant non calculé en prévision 2026 (mention de la source)",
            "ε": "ε : montant inférieur à 0,5 M€ (mention de la source)"}
LECTURE_HORS_ACTION = {
    "FDC/ADP": "Ligne du budget vert qui retire de l'exécution 2024 les fonds de concours et attributions de "
               "produits : ce n'est pas une action du programme.",
    "T2_CAS": "Ligne du budget vert qui retire des dépenses de personnel la contribution au compte d'affectation "
              "spéciale Pensions : ce n'est pas une action du programme.",
    "MP/MT": "Mesure de périmètre ou de transfert entre programmes, inscrite par la source pour rendre les années "
             "comparables : ce n'est pas une action du programme.",
}


def lire_budget_vert() -> list[dict]:
    lignes = lire_csv(_un_fichier("budget_vert", ".csv"))
    if not lignes or "type_depense" not in lignes[0] or COLS_BV["plf_2026_eur"] not in lignes[0]:
        raise DonneeInattendue("budget vert : colonnes attendues absentes")
    return lignes


def _montants_bv(x: dict) -> dict:
    return {k: euros(x.get(c)) for k, c in COLS_BV.items()}


def _somme(valeurs) -> int | None:
    v = [x for x in valeurs if x is not None]
    return sum(v) if v else None


def _somme_brute(valeurs) -> float | None:
    v = [x for x in valeurs if x is not None]
    return sum(v) if v else None


def _nettoyer(x):
    """Retire les clés techniques (préfixe « _ ») avant écriture."""
    if isinstance(x, dict):
        return {k: _nettoyer(v) for k, v in x.items() if not k.startswith("_")}
    if isinstance(x, list):
        return [_nettoyer(v) for v in x]
    return x


def _cle_hors_action(code: str) -> str | None:
    for k in LECTURE_HORS_ACTION:
        if code.startswith(k):
            return k
    return None


def programmes_budget_vert(lignes: list[dict], missions: list[str]) -> dict[int, dict]:
    """Programmes des missions demandées : actions (lignes de la source sous chaque action) et lignes hors action."""
    progs: dict[int, dict] = {}
    for x in lignes:
        if x["type_depense"] != "Crédits budgétaires" or x["mission"] not in missions:
            continue
        num = int(nombre(x["numero_programme"]))
        p = progs.setdefault(num, {"programme": num, "libelle": _propre(x["programme"]), "mission": x["mission"],
                                   "actions": {}, "lignes_hors_action": []})
        code_action = _propre(x["code_action_si_credit_budgetaire"])
        hors = _cle_hors_action(code_action)
        m = _montants_bv(x)
        if hors:
            p["lignes_hors_action"].append({"code": code_action, "libelle": _propre(x["libelle"]), **m,
                                            "lecture": LECTURE_HORS_ACTION[hors]})
            continue
        if not re.fullmatch(r"\d{3}-\d{2}", code_action):
            raise DonneeInattendue(f"budget vert : code d'action inattendu {code_action!r}")
        a = p["actions"].setdefault(code_action, {"code": code_action,
                                                  "libelle": _propre(x["action_si_credit_budgetaire"]),
                                                  "lignes": []})
        a["lignes"].append({"code_depense": _propre(x["code_depense"]), "libelle": _propre(x["libelle"]), **m,
                            "_brut": {k: nombre(x.get(c)) for k, c in COLS_BV.items()}})
    for p in progs.values():
        actions = []
        for code in sorted(p["actions"]):
            a = p["actions"][code]
            a["lignes"].sort(key=lambda li: (li["code_depense"], li["libelle"]))
            for k in COLS_BV:
                a["_brut_" + k] = _somme_brute(li["_brut"][k] for li in a["lignes"])
                a[k] = euros(a["_brut_" + k])
            if len(a["lignes"]) == 1 and a["lignes"][0]["code_depense"] == code:
                a.pop("lignes")
            else:
                a["statut"] = "calculé"
                a["methode"] = ("Somme des lignes publiées sous l'action ; le budget vert découpe certaines actions "
                                "en lignes de dépense, parfois selon leur cotation environnementale.")
            actions.append(a)
        p["actions"] = actions
        p["lignes_hors_action"].sort(key=lambda h: (h["code"], h["libelle"]))
        p["somme_actions"] = {**{k: euros(_somme_brute(a["_brut_" + k] for a in actions)) for k in COLS_BV},
                              "statut": "calculé",
                              "methode": "Somme des actions du budget vert, hors lignes de retraitement de la source "
                                         "(fonds de concours, contribution au compte Pensions, mesures de périmètre)."}
    return dict(sorted(progs.items()))


def depenses_fiscales(lignes: list[dict], missions: list[str]) -> list[dict]:
    """Dépenses fiscales rattachées aux missions ; lignes de même code regroupées (somme marquée « calculé »)."""
    par_code: dict[tuple, dict] = {}
    for x in lignes:
        if x["type_depense"] != "Dépenses fiscales" or x["mission"] not in missions:
            continue
        cle = (x["mission"], _propre(x["code_depense"]))
        d = par_code.setdefault(cle, {"mission": x["mission"], "code": cle[1], "impot": _propre(x["impot_si_depense_fiscale"]),
                                      "libelle": _propre(x["libelle"]), "_lignes": []})
        d["_lignes"].append(x)
    out = []
    for cle in sorted(par_code):
        d = par_code[cle]
        ls = d.pop("_lignes")
        for k, c in COLS_BV.items():
            k2 = k.replace("lfi_2025", "chiffrage_2025").replace("plf_2026", "chiffrage_2026").replace(
                "execution_2024", "chiffrage_2024")
            d[k2] = _somme(euros(li.get(c)) for li in ls)
        mention = sorted({li.get(MENTION_DF, "").strip() for li in ls} - {""})
        d["mention_source"] = [MENTIONS.get(m, m) for m in mention]
        if all(d[k] is None for k in ("chiffrage_2024_eur", "chiffrage_2025_eur", "chiffrage_2026_eur")) \
                and not mention:
            d["mention_source"] = ["non chiffré à la source"]
        if len(ls) > 1:
            d["statut"] = "calculé"
            d["methode"] = (f"Somme des {len(ls)} lignes publiées sous ce code : le budget vert découpe la dépense "
                            "selon sa cotation environnementale.")
        out.append(d)
    return out


def taxes_affectees(lignes: list[dict], missions: list[str]) -> list[dict]:
    out = []
    for x in lignes:
        if x["type_depense"] != "Taxes affectées plafonnées" or x["mission"] not in missions:
            continue
        m = _montants_bv(x)
        out.append({"mission": x["mission"], "code": _propre(x["code_depense"]),
                    "affectataire": _propre(x["affectataire_si_taxe_affectee"]), "libelle": _propre(x["libelle"]),
                    "rendement_2024_eur": m["execution_2024_eur"], "plafond_ou_prevision_2025_eur": m["lfi_2025_eur"],
                    "plafond_ou_prevision_2026_eur": m["plf_2026_eur"]})
    return sorted(out, key=lambda t: (t["mission"], t["code"]))


# ----------------------------------------------------------------------------------------------------- PLRG

def lire_plrg(nom: str) -> list[dict]:
    f = LAKE / SOURCES["plrg"]["id_catalogue"] / nom
    if not f.exists():
        raise FileNotFoundError(f"data/lake/culture_medias/{SOURCES['plrg']['id_catalogue']}/{nom} absent : "
                                "lancer collecter")
    return lire_csv(f)


def plrg_bg_2025(missions: list[str]) -> dict[int, dict]:
    """LFI, crédits ouverts et dépenses constatées 2025 par programme (somme des deux lignes de titre)."""
    out: dict[int, dict] = {}
    for x in lire_plrg("plrg_2025_bg_cp.csv"):
        if x.get("Mission") not in missions:
            continue
        _, num = _programme(x["Programme"])
        p = out.setdefault(num, {"annee": 2025, "titres": []})
        p["titres"].append({"titre": _propre(x["Titre"]), "lfi_eur": euros(x["LFI"]),
                            "credits_ouverts_eur": euros(x["Total_CP_Ouverts"]),
                            "depenses_constatees_eur": euros(x["Depenses_constatees"])})
    for p in out.values():
        p["titres"].sort(key=lambda t: t["titre"])
        for k in ("lfi_eur", "credits_ouverts_eur", "depenses_constatees_eur"):
            p[k] = _somme(t[k] for t in p["titres"])
        p["statut"] = "calculé" if len(p["titres"]) > 1 else "publié"
        if len(p["titres"]) == 1:
            p.pop("titres")
    return out


def plrg_audiovisuel() -> tuple[dict, list[dict]]:
    """Crédits du compte de concours financiers par programme et année ; recouvrements du compte par année."""
    credits: dict[int, dict] = {}
    recettes = []
    for an in ANNEES_PLRG:
        vus = 0
        for x in lire_plrg(f"plrg_{an}_cs_cp.csv"):
            if x.get("Mission") != MISSION_AUDIOVISUEL:
                continue
            lib, num = _programme(x["Programme"])
            vus += 1
            credits.setdefault(num, {})[str(an)] = {
                "libelle_source": lib, "lfi_eur": euros(x["LFI"]), "credits_ouverts_eur": euros(x["Total_CP_Ouverts"]),
                "depenses_constatees_eur": euros(x["Depenses_constatees"])}
        if not vus:
            raise DonneeInattendue(f"PLRG {an} : aucune ligne « {MISSION_AUDIOVISUEL} »")
        lignes = [x for x in lire_plrg(f"plrg_{an}_cs_recouvrements.csv") if x.get("Compte") == MISSION_AUDIOVISUEL]
        if not lignes:
            raise DonneeInattendue(f"PLRG {an} : aucun recouvrement « {MISSION_AUDIOVISUEL} »")
        ev = _colonne(lignes[0].keys(), "evaluations")
        rec = _colonne(lignes[0].keys(), "recouvrements")
        exe = _colonne(lignes[0].keys(), "ligne", "execution")
        total = [x for x in lignes if _propre(x[exe]) in ("", "0")]
        detail = [x for x in lignes if _propre(x[exe]) not in ("", "0")]
        recettes.append({
            "annee": an, "compte": MISSION_AUDIOVISUEL, "section": _propre(lignes[0]["Section"]),
            "evaluation_eur": _somme(euros(x[ev]) for x in total),
            "lignes": sorted(({"ligne": _propre(x[exe]), "recouvrements_eur": euros(x[rec])} for x in detail),
                             key=lambda li: li["ligne"]),
            "recouvrements_eur": _somme(euros(x[rec]) for x in detail), "statut_total": "calculé"})
    return credits, recettes


# ------------------------------------------------------------------------------------------------------ budget

def construire_budget(bv: list[dict]) -> dict:
    progs = programmes_budget_vert(bv, MISSIONS_BUDGET)
    plrg = plrg_bg_2025(MISSIONS_BUDGET)
    if set(progs) != set(plrg):
        raise DonneeInattendue(f"programmes différents entre budget vert {sorted(progs)} et PLRG 2025 {sorted(plrg)}")
    ecarts = []
    for num, p in progs.items():
        p["plrg_2025"] = plrg[num]
        a, b = p["somme_actions"]["lfi_2025_eur"], plrg[num]["lfi_eur"]
        if a is not None and b is not None and a != b:
            ecarts.append({
                "programme": num, "grandeur": "LFI 2025, crédits de paiement",
                "source": "budget vert du PLF 2026, somme des actions", "montant_eur": a,
                "autre_source": "PLRG 2025, annexe 1, colonne LFI", "autre_montant_eur": b, "ecart_eur": a - b,
                "lecture_ecart": "Écart d'arrondi : la source publie certaines lignes avec des fractions d'euro."
                if abs(a - b) <= 1 else
                "Écart publié, pas corrigé : les deux documents ne retiennent pas exactement le même périmètre (le "
                "budget vert retraite certaines lignes pour rendre les années comparables)."})
    missions = []
    for nom in MISSIONS_BUDGET:
        ps = [p for p in progs.values() if p["mission"] == nom]
        missions.append({"mission": nom, "programmes": ps,
                         "somme_programmes": {
                             **{k: _somme(p["somme_actions"][k] for p in ps) for k in COLS_BV},
                             "plrg_2025_lfi_eur": _somme(p["plrg_2025"]["lfi_eur"] for p in ps),
                             "plrg_2025_depenses_constatees_eur": _somme(p["plrg_2025"]["depenses_constatees_eur"]
                                                                         for p in ps),
                             "statut": "calculé",
                             "methode": "Somme des programmes de la mission, colonne par colonne, chaque source "
                                        "séparément."}})
    return {
        "millesime": "Exécution 2024, LFI 2025 et PLF 2026 par action (budget vert du PLF 2026) ; LFI et exécution "
                     "2025 par programme (PLRG 2025)",
        "source": f"{SOURCES['budget_vert']['page']} ; {SOURCES['plrg']['page']}",
        "unite": "euros (crédits de paiement)",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Trois millésimes d'une même source (exécution 2024, loi de finances initiale 2025, projet de "
                         "loi de finances 2026) et l'exécution 2025 d'une autre source, côte à côte : ils ne "
                         "s'additionnent pas. Le PLF 2026 est un projet, pas le budget voté. L'audiovisuel public est "
                         "financé par un compte à part, décrit dans audiovisuel.json.",
        "missions": missions,
        "depenses_fiscales": {
            "lecture": "Dépenses fiscales rattachées aux deux missions par la source : une recette en moins pour "
                       "l'État, chiffrée par l'administration, pas un crédit. Elles ne s'additionnent pas aux crédits.",
            "lignes": depenses_fiscales(bv, MISSIONS_BUDGET)},
        "taxes_affectees": {
            "lecture": "Taxes affectées plafonnées rattachées aux deux missions : recette versée directement à un "
                       "organisme, hors crédits budgétaires. Les taxes affectées au CNC, non plafonnées, sont dans "
                       "cnc.json.",
            "lignes": taxes_affectees(bv, MISSIONS_BUDGET)},
        "ecarts": ecarts,
        "ordre": "Missions dans l'ordre du budget de l'État ; programmes et actions par numéro croissant.",
    }


# ------------------------------------------------------------------------------------------------- audiovisuel

def construire_audiovisuel(bv: list[dict]) -> dict:
    credits, recettes = plrg_audiovisuel()
    progs = programmes_budget_vert(bv, [MISSION_AUDIOVISUEL])
    societes = []
    for num in sorted(set(credits) | set(progs)):
        if num not in SOCIETES:
            raise DonneeInattendue(f"programme {num} inattendu dans « {MISSION_AUDIOVISUEL} »")
        p = progs.get(num, {})
        bvs = p.get("somme_actions", {})
        societes.append({
            "programme": num, "libelle": SOCIETES[num],
            "type": "programme" if num == 848 else "société",
            "plrg": {an: credits.get(num, {}).get(an) for an in map(str, ANNEES_PLRG)},
            "budget_vert": {"execution_2024_eur": bvs.get("execution_2024_eur"),
                            "lfi_2025_eur": bvs.get("lfi_2025_eur"), "plf_2026_eur": bvs.get("plf_2026_eur")},
            "actions_budget_vert": p.get("actions", []) if num == 848 else [],
            "lignes_hors_action": p.get("lignes_hors_action", []),
        })
    totaux = []
    for an in map(str, ANNEES_PLRG):
        vals = [s["plrg"][an] for s in societes if s["plrg"][an]]
        totaux.append({"annee": int(an), "lfi_eur": _somme(v["lfi_eur"] for v in vals),
                       "depenses_constatees_eur": _somme(v["depenses_constatees_eur"] for v in vals),
                       "programmes": len(vals), "statut": "calculé"})
    totaux.append({"annee": 2026, "plf_eur": _somme(s["budget_vert"]["plf_2026_eur"] for s in societes),
                   "programmes": sum(1 for s in societes if s["budget_vert"]["plf_2026_eur"] is not None),
                   "statut": "calculé", "source": "budget vert du PLF 2026 (projet)"})
    transferts = []
    for x in bv:
        if x["type_depense"] == "Crédits budgétaires" and x["mission"] == MISSION_AUDIOVISUEL_BG:
            transferts.append({"programme": int(nombre(x["numero_programme"])), "libelle": _propre(x["programme"]),
                               "code": _propre(x["code_depense"]), **_montants_bv(x)})
    transferts.sort(key=lambda t: (t["programme"], t["code"]))
    return {
        "millesime": "Exécution 2023, 2024 et 2025 (PLRG) ; LFI 2025 et PLF 2026 (budget vert du PLF 2026)",
        "source": f"{SOURCES['plrg']['page']} ; {SOURCES['budget_vert']['page']}",
        "unite": "euros (crédits de paiement)",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Dotations versées par l'État aux sociétés de l'audiovisuel public par le compte de concours "
                         "financiers « Avances à l'audiovisuel public ». Les ressources propres des sociétés "
                         "(publicité, ventes) ne sont pas dans ces montants. Le PLF 2026 est un projet, pas le budget "
                         "voté.",
        "societes": societes,
        "totaux": totaux,
        "financement": {
            "mode": "Depuis la suppression de la contribution à l'audiovisuel public par la loi de finances "
                    "rectificative pour 2022, le compte de concours financiers reçoit une part de la taxe sur la "
                    "valeur ajoutée, inscrite à la ligne de recette « TVA compensatrice de la suppression de la "
                    "contribution à l'audiovisuel public ». Il n'y a plus de contribution à part : cette part est "
                    "prise sur la TVA que tu verses déjà sur tes achats.",
            "recettes": recettes,
            "lecture": "Montants recouvrés par le compte chaque année, ligne par ligne, tels que publiés dans les "
                       "annexes des PLRG ; « evaluation_eur » est la prévision de la loi de finances.",
            "passage_par_le_budget_general_plf_2025": {
                "lecture": "Le PLF 2025 inscrivait ces dotations au budget général (mission « Audiovisuel public », "
                           "programmes 372 à 377 et 383) ; la loi de finances pour 2025 les a portées sur le compte "
                           "de concours financiers. Le budget vert le retrace par des lignes de mesure de périmètre "
                           "ou de transfert, reprises ici telles quelles.",
                "lignes": transferts},
        },
        "ordre": "Programmes par numéro croissant ; années croissantes.",
    }


# ------------------------------------------------------------------------------------------------------- presse

COLONNES_TITRES = [  # (clé de sortie, motifs du nom de colonne dans le classement des titres)
    ("aides_directes_eur", ("aides directes (1)",)),
    ("dont_pluralisme_eur", ("dont aides au pluralisme",)),
    ("dont_exemplaire_porte_eur", ("dont aide a l'exemplaire porte",)),
    ("dont_exemplaire_poste_eur", ("dont aide a l'exemplaire poste",)),
    ("dont_fsdp_eur", ("dont fsdp",)),
    ("dont_fseip_eur", ("dont fseip",)),
    ("aide_filiere_distribution_eur", ("aide filiere",)),
    ("aide_exceptionnelle_papier_eur", ("aide exceptionnelle papier",)),
    ("aide_modernisation_sociale_eur", ("modernisation sociale",)),
    ("aide_exceptionnelle_editeurs_eur", ("aide exceptionnelle au benefice de certains editeurs",)),
    ("aide_exceptionnelle_ultramarins_eur", ("aide exceptionnelle au benefice des titres de presse ultra",)),
    ("total_aides_eur", ("total des aides individuelles",)),
]
COLONNES_GROUPES = [
    ("aides_directes_eur", ("aides directes (1)",)),
    ("dont_pluralisme_eur", ("dont aides au pluralisme",)),
    ("dont_portage_titres_eur", ("dont aide au portage - titres",)),
    ("dont_portage_reseaux_eur", ("dont aide au portage - reseaux",)),
    ("dont_fsdp_eur", ("dont fsdp",)),
    ("dont_fseip_eur", ("dont fseip",)),
    ("aide_filiere_distribution_eur", ("aide filiere",)),
    ("aide_modernisation_sociale_eur", ("modernisation sociale",)),
    ("total_aides_eur", ("total des aides",)),
]
LIBELLES_COLONNES = {
    "aides_directes_eur": "Aides directes",
    "dont_pluralisme_eur": "dont aides au pluralisme",
    "dont_exemplaire_porte_eur": "dont aide à l'exemplaire porté (aide au portage avant 2023)",
    "dont_exemplaire_poste_eur": "dont aide à l'exemplaire posté",
    "dont_portage_titres_eur": "dont aide au portage, titres",
    "dont_portage_reseaux_eur": "dont aide au portage, réseaux",
    "dont_fsdp_eur": "dont Fonds stratégique pour le développement de la presse",
    "dont_fseip_eur": "dont Fonds de soutien à l'émergence et à l'innovation dans la presse",
    "aide_filiere_distribution_eur": "Aide à la filière (aide à la distribution, reversée à la messagerie)",
    "aide_exceptionnelle_papier_eur": "Aide exceptionnelle papier",
    "aide_modernisation_sociale_eur": "Aide à la modernisation sociale (au bénéfice d'anciens salariés)",
    "aide_exceptionnelle_editeurs_eur": "Aide exceptionnelle au bénéfice de certains éditeurs de presse",
    "aide_exceptionnelle_ultramarins_eur": "Aide exceptionnelle au bénéfice des titres de presse ultramarins",
    "total_aides_eur": "Total des aides",
}


def _filtre_noms():
    import local  # pipeline/local.py : filtre des noms de personnes (prénoms fréquents, civilités)
    liste = local.prenoms()
    return lambda texte: local.objet_publiable(texte, liste, longueur=200)


INITIALE_NOM = re.compile(r"(?<!\w)[A-Z]\.\s*[A-Z][A-Za-z'-]{1,}")
PARENTHESES = re.compile(r"\s*\([^)]*\)")


def _nom_publie(brut: str, publiable, groupe: bool = False) -> tuple[str | None, bool]:
    """Nom tel que publié, ou (None, True) s'il peut contenir un nom de personne. Pour un groupe, les précisions entre
    parenthèses (actionnaires, parts, anciens noms) sont retirées avant tout contrôle."""
    b = _propre(brut)
    if groupe:
        b = _propre(PARENTHESES.sub("", b))
    if not b:
        return None, False
    p = None if INITIALE_NOM.search(b) else publiable(b)
    return (p, False) if p else (None, True)


def lire_classement_titres(publiable) -> dict:
    lignes = lire_csv(_un_fichier("presse_titres", ".csv"))
    ent = list(lignes[0].keys())
    cols = {k: _colonne(ent, *m) for k, m in COLONNES_TITRES}
    c_titre, c_annee = _colonne(ent, "beneficiaires"), _colonne(ent, "annee")
    c_groupe, c_diff = _colonne(ent, "groupes ou societes"), _colonne(ent, "diffusion annuelle")
    c_parex = _colonne(ent, "aide par exemplaire")
    par_annee: dict[int, list[dict]] = {}
    for x in lignes:
        an = int(nombre(x[c_annee]))
        titre, masque = _nom_publie(x[c_titre], publiable)
        groupe, gmasque = _nom_publie(x[c_groupe], publiable, groupe=True)
        par_annee.setdefault(an, []).append({
            "titre": titre, "titre_masque": masque, "groupe": groupe, "groupe_masque": gmasque,
            **{k: euros(x[c]) for k, c in cols.items()},
            "diffusion_annuelle": euros(x[c_diff]), "aide_par_exemplaire_eur": _arrondi(nombre(x[c_parex]), 4)})
    series = []
    for an in sorted(par_annee):
        rows = par_annee[an]
        series.append({"annee": an, "titres": len(rows), **{k: _somme(r[k] for r in rows) for k, _ in COLONNES_TITRES},
                       "statut": "calculé"})
    derniere = max(par_annee)
    titres = sorted(par_annee[derniere], key=lambda r: (r["titre"] is None, _norm(r["titre"] or ""),
                                                         -(r["total_aides_eur"] or 0)))
    return {"annees": sorted(par_annee), "par_annee": series, "derniere_annee": derniere, "titres": titres,
            "masques": sum(1 for r in titres if r["titre_masque"])}


def lire_groupes(publiable) -> dict:
    lignes = lire_csv(_un_fichier("presse_groupes", ".csv"))
    ent = list(lignes[0].keys())
    cols = {k: _colonne(ent, *m) for k, m in COLONNES_GROUPES}
    c_nom, c_annee = _colonne(ent, "groupe ou societe"), _colonne(ent, "annee")
    out = []
    for x in lignes:
        nom, masque = _nom_publie(x[c_nom], publiable, groupe=True)
        out.append({"annee": int(nombre(x[c_annee])), "groupe": nom, "groupe_masque": masque,
                    **{k: euros(x[c]) for k, c in cols.items()}})
    out.sort(key=lambda r: (r["annee"], r["groupe"] is None, _norm(r["groupe"] or ""), -(r["total_aides_eur"] or 0)))
    return {"annees": sorted({r["annee"] for r in out}), "groupes": out}


def lire_dispositifs() -> list[dict]:
    out = []
    for k, lib, ds in DISPOSITIFS_PRESSE:
        lignes = lire_csv(_un_fichier(f"presse_{k}", ".csv"))
        ent = list(lignes[0].keys())
        c_m, c_a = _colonne(ent, "montant"), _colonne(ent, "annee")
        par: dict[int, list] = {}
        sans_montant = 0
        for x in lignes:
            m = euros(x[c_m])
            if m is None:
                sans_montant += 1
            par.setdefault(int(nombre(x[c_a])), []).append(m)
        out.append({"id": k, "libelle": lib, "source": SOURCES[f"presse_{k}"]["page"],
                    "par_annee": [{"annee": an, "lignes": len(v), "montant_eur": _somme(v), "statut": "calculé"}
                                  for an, v in sorted(par.items())],
                    "lignes_sans_montant": sans_montant})
    return out


def construire_presse(bv: list[dict]) -> dict:
    publiable = _filtre_noms()
    classement = lire_classement_titres(publiable)
    groupes = lire_groupes(publiable)
    dispositifs = lire_dispositifs()
    p180 = programmes_budget_vert(bv, ["Médias, livre et industries culturelles"]).get(180)
    if not p180:
        raise DonneeInattendue("budget vert : programme 180 absent")
    return {
        "millesime": f"Classement des titres {classement['annees'][0]} à {classement['derniere_annee']} ; groupes "
                     f"{groupes['annees'][0]} à {groupes['annees'][-1]} ; tableaux par dispositif jusqu'à "
                     f"{max(a['annee'] for d in dispositifs for a in d['par_annee'])}",
        "source": " ; ".join(SOURCES[k]["page"] for k in ("presse_titres", "presse_groupes"))
                  + " ; tableaux par dispositif du ministère de la Culture (data.gouv.fr)",
        "unite": "euros",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Aides directes versées par le ministère de la Culture aux éditeurs de presse, titre par titre, "
                         "telles que publiées. Les aides indirectes (taux réduit de TVA, tarifs postaux) ne sont pas "
                         "dans ces tableaux ; le taux de TVA de 2,10 % sur la presse figure parmi les dépenses fiscales "
                         "de budget.json. Les tableaux par dispositif et le classement consolidé ne couvrent pas les "
                         "mêmes années ni les mêmes aides : ils ne s'additionnent pas.",
        "colonnes": LIBELLES_COLONNES,
        "classement_titres": {
            "source": SOURCES["presse_titres"]["page"],
            "par_annee": classement["par_annee"],
            "derniere_annee": classement["derniere_annee"],
            "titres": classement["titres"],
            "titres_masques": classement["masques"],
            "lecture": "Une ligne par titre aidé : aides directes et leurs composantes, aide à la filière, aides "
                       "exceptionnelles, total, diffusion annuelle et aide par exemplaire publiés par le ministère. "
                       "Le total par année est une somme faite ici (« calculé »).",
            "regle_personnes": "Le nom d'un titre ou d'un groupe est publié tel que le ministère le publie, sauf s'il "
                               "peut contenir un nom de personne (prénom fréquent suivi d'un mot, civilité) : il est "
                               "alors masqué (null, « titre_masque » ou « groupe_masque » vrai) et le montant reste publié. Les "
                               "précisions entre parenthèses des noms de groupe (actionnaires, parts, anciens noms) ne "
                               "sont pas reprises.",
        },
        "groupes": {
            "source": SOURCES["presse_groupes"]["page"],
            "lignes": groupes["groupes"],
            "lecture": "Principaux groupes ou sociétés de presse aidés, par année, tels que publiés par le ministère "
                       "(sociétés éditrices, personnes morales). Les montants d'un groupe reprennent ceux de ses titres : "
                       "ils ne s'ajoutent pas au classement des titres.",
        },
        "dispositifs": {
            "lignes": dispositifs,
            "lecture": "Montant total par dispositif et par année, somme des lignes (titre et montant) des tableaux "
                       "publiés par le ministère. Une ligne sans montant reste comptée dans « lignes » et hors de la "
                       "somme.",
        },
        "budget_programme_180": {
            "lecture": "Crédits de l'action « Aides à la presse » du programme 180 (budget vert du PLF 2026) : même "
                       "argent vu depuis le budget de l'État, à ne pas additionner aux tableaux par titre.",
            "actions": [a for a in p180["actions"] if a["code"] == "180-02"],
        },
        "ordre": "Titres et groupes par ordre alphabétique (nom masqué en dernier) ; années et dispositifs dans "
                 "l'ordre des sources.",
    }


# --------------------------------------------------------------------------------------------------------- CNC

# Graphique « Soutiens du CNC en 2025 » (page 272) : relevé, puis chaque montant vérifié dans le texte de la page
# et chaque sous-total recalculé (tolérance d'arrondi : 0,15 M€).
CNC_SOUTIENS = {
    "page": 272, "total_meur": 772.4, "automatiques_meur": 421.7, "selectifs_meur": 350.7,
    "secteurs": [
        {"secteur": "cinéma", "total_meur": 315.5,
         "automatiques": {"total_meur": 185.9, "dispositifs": [("production", 72.7), ("distribution", 42.0),
                                                                ("exploitation", 71.3)]},
         "selectifs": {"total_meur": 129.5, "dispositifs": [("production et création", 51.9), ("distribution", 14.4),
                                                             ("exploitation", 29.0), ("diffusion du cinéma", 34.3)]}},
        {"secteur": "audiovisuel", "total_meur": 283.0,
         "automatiques": {"total_meur": 222.4, "dispositifs": [("production", 222.4)]},
         "selectifs": {"total_meur": 60.6, "dispositifs": [("production et création", 60.6)]}},
        {"secteur": "dispositifs transversaux", "total_meur": 173.9,
         "automatiques": {"total_meur": 13.3, "dispositifs": [("vidéo", 0.4), ("vidéo à la demande", 6.4),
                                                               ("exportation", 6.5)]},
         "selectifs": {"total_meur": 160.5, "dispositifs": [("industries techniques", 7.4),
                                                             ("vidéo et vidéo à la demande", 7.3),
                                                             ("innovation et jeux vidéo", 26.1),
                                                             ("promotion et exportation", 39.3),
                                                             ("fonds régionaux", 23.7),
                                                             ("autres soutiens", 56.7)]}},
    ],
    "dont": [("autres soutiens, dont plan numérique et patrimoine", 5.5)],
    "autofinances_meur": 67.7,
    "autofinances": [("avances sur le soutien automatique à l'exploitation (soutien sélectif pour le cinéma)", 54.3),
                     ("avances sur le soutien automatique à la production audiovisuelle (soutien sélectif pour "
                      "l'audiovisuel)", 13.4)],
}
# Graphique « Recettes du fonds de soutien géré par le CNC en 2025 » (page 271).
CNC_RECETTES = {
    "page": 271, "produit_brut_meur": 877.5, "prelevement_meur": 48.3, "total_net_meur": 829.2,
    "taxes": [("taxe sur les entrées en salles de cinéma", "TSA", 123.6),
              ("taxe sur les éditeurs de services de télévision", "TST-E", 259.5),
              ("taxe sur les distributeurs de services de télévision", "TST-D", 281.1),
              ("taxe sur les vidéogrammes", "TSV-V", 3.5),
              ("taxe sur les services d'accès à des contenus audiovisuels à la demande", "TSV-P", 151.5),
              ("taxe sur la publicité des vidéos en ligne", "TSV-G", 44.4),
              ("régularisations de taxe sur les services vidéo (sommes ne correspondant pas à une déclaration pour "
               "2025)", "TSV", 14.0)],
}
TOLERANCE_MEUR = 0.15


def _fr(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def _lignes_caracteres(page) -> list[str]:
    """Texte de la page reconstitué caractère par caractère, ligne par ligne (même ordonnée arrondie, abscisses
    croissantes, espace quand deux caractères sont écartés) : les étiquettes inclinées des graphiques y sont lisibles."""
    par_ligne: dict[int, list] = {}
    for c in page.chars:
        par_ligne.setdefault(round(c["top"]), []).append(c)
    out = []
    for top in sorted(par_ligne):
        s, prec = "", None
        for c in sorted(par_ligne[top], key=lambda c: (c["x0"], c["text"])):
            if prec is not None and c["x0"] - prec["x1"] > 1.0:
                s += " "
            s += c["text"]
            prec = c
        out.append(s)
    return out


def _texte_pages(pdf_chemin: Path, pages: list[int]) -> dict[int, list[str]]:
    import pdfplumber
    with pdfplumber.open(str(pdf_chemin)) as pdf:
        return {n: _lignes_caracteres(pdf.pages[n - 1]) for n in pages}


MONTANT_MEUR = re.compile(r"(?<![\d,])(\d{1,3},\d)\s?M€")


def _verifier_montants(lignes: list[str], montants: list[float], page: int) -> None:
    """Chaque montant relevé doit figurer dans le texte de la page, suivi de « M€ », au moins autant de fois qu'il est
    relevé."""
    compte: dict[str, int] = {}
    for li in lignes:
        for m in MONTANT_MEUR.findall(li):
            compte[m] = compte.get(m, 0) + 1
    besoin: dict[str, int] = {}
    for v in montants:
        besoin[_fr(v)] = besoin.get(_fr(v), 0) + 1
    manquants = [f"{k} ({n} relevé(s), {compte.get(k, 0)} trouvé(s))" for k, n in sorted(besoin.items())
                 if compte.get(k, 0) < n]
    if manquants:
        raise DonneeInattendue(f"Bilan du CNC, page {page} : montants introuvables dans le texte : {manquants}")


def construire_cnc() -> dict:
    pdf = _un_fichier("cnc", ".pdf")
    s, r = CNC_SOUTIENS, CNC_RECETTES
    textes = _texte_pages(pdf, [r["page"], s["page"]])
    titre_s = re.sub(r"\s+", "", " ".join(textes[s["page"]]))
    titre_r = re.sub(r"\s+", "", " ".join(textes[r["page"]]))
    if "SoutiensduCNCen2025" not in titre_s or "Recettesdufondsdesoutien" not in titre_r:
        raise DonneeInattendue("Bilan du CNC : graphiques attendus absents des pages 271 et 272")
    # Montants affichés une seule fois dans le graphique (le total « production » de l'audiovisuel automatique n'est
    # pas répété : il est égal au sous-total).
    releves = [s["total_meur"], s["automatiques_meur"], s["selectifs_meur"], s["autofinances_meur"]]
    for sec in s["secteurs"]:
        releves.append(sec["total_meur"])
        for nat in ("automatiques", "selectifs"):
            releves.append(sec[nat]["total_meur"])
            ds = sec[nat]["dispositifs"]
            if not (len(ds) == 1 and ds[0][1] == sec[nat]["total_meur"]):
                releves += [v for _, v in ds]
    releves += [v for _, v in s["dont"]] + [v for _, v in s["autofinances"]]
    _verifier_montants(textes[s["page"]], releves, s["page"])
    _verifier_montants(textes[r["page"]], [v for _, _, v in r["taxes"]] + [r["prelevement_meur"], r["total_net_meur"],
                                                                         r["produit_brut_meur"]], r["page"])
    controles = []

    def controle(niveau, somme, publie):
        ecart = round(somme - publie, 2)
        controles.append({"niveau": niveau, "somme_meur": round(somme, 1), "publie_meur": publie, "ecart_meur": ecart})
        if abs(ecart) > TOLERANCE_MEUR + 1e-9:
            raise DonneeInattendue(f"Bilan du CNC : {niveau} : somme {somme:.1f} contre {publie} publié")

    secteurs = []
    for sec in s["secteurs"]:
        out = {"secteur": sec["secteur"], "total_meur": sec["total_meur"]}
        for nat in ("automatiques", "selectifs"):
            ds = sec[nat]["dispositifs"]
            controle(f"{sec['secteur']}, {nat}", sum(v for _, v in ds), sec[nat]["total_meur"])
            out[nat] = {"total_meur": sec[nat]["total_meur"],
                        "dispositifs": [{"dispositif": d, "montant_meur": v} for d, v in ds]}
        controle(f"{sec['secteur']}, total", sec["automatiques"]["total_meur"] + sec["selectifs"]["total_meur"],
                 sec["total_meur"])
        secteurs.append(out)
    controle("ensemble des secteurs", sum(x["total_meur"] for x in s["secteurs"]), s["total_meur"])
    controle("ensemble des aides automatiques", sum(x["automatiques"]["total_meur"] for x in s["secteurs"]),
             s["automatiques_meur"])
    controle("ensemble des soutiens sélectifs", sum(x["selectifs"]["total_meur"] for x in s["secteurs"]),
             s["selectifs_meur"])
    controle("autofinancés", sum(v for _, v in s["autofinances"]), s["autofinances_meur"])
    brut = sum(v for _, _, v in r["taxes"])
    controle("recettes : produit des taxes", brut, r["produit_brut_meur"])
    controle("recettes : produit net", r["produit_brut_meur"] - r["prelevement_meur"], r["total_net_meur"])
    return {
        "millesime": "2025 (Bilan 2025 du CNC)",
        "source": SOURCES["cnc"]["page"],
        "unite": "millions d'euros, à une décimale, tels que publiés",
        "date_sources": date_sources(DOMAINE),
        "producteur": "Centre national du cinéma et de l'image animée (CNC), établissement public",
        "avertissement": "Le CNC est financé par des taxes affectées payées par les salles de cinéma, les chaînes et "
                         "distributeurs de télévision et les services de vidéo, pas par des crédits du budget de "
                         "l'État. Les aides par bénéficiaire ne sont pas publiées en données ouvertes : seuls les "
                         "agrégats par dispositif du Bilan sont repris.",
        "methode": "Montants relevés dans les graphiques des pages 271 (« Recettes du fonds de soutien géré par le CNC "
                   "en 2025 ») et 272 (« Soutiens du CNC en 2025 ») du Bilan 2025. À chaque production, chaque "
                   "montant est recherché dans le texte de la page et chaque sous-total est recalculé (écart "
                   "d'arrondi toléré : 0,15 M€) ; la production s'arrête sinon.",
        "definitions": {
            "selectifs": "Soutiens sélectifs : nouvelles aides engagées en 2025, attribuées sur projet (définition du "
                         "Bilan).",
            "automatiques": "Aides automatiques : droits générés en 2025, calculés d'après les résultats des œuvres "
                            "(définition du Bilan).",
            "diffusion du cinéma": "Principalement les subventions aux cinémathèques et les dispositifs d'éducation au "
                                   "cinéma et à l'image (définition du Bilan).",
        },
        "soutiens": {
            "annee": 2025, "page": s["page"], "total_meur": s["total_meur"], "automatiques_meur": s["automatiques_meur"],
            "selectifs_meur": s["selectifs_meur"], "secteurs": secteurs,
            "dont": [{"libelle": d, "montant_meur": v} for d, v in s["dont"]],
        },
        "dispositifs_autofinances": {
            "total_meur": s["autofinances_meur"],
            "lignes": [{"libelle": d, "montant_meur": v} for d, v in s["autofinances"]],
            "lecture": "Avances remboursées par les soutiens automatiques des années suivantes ; le Bilan les laisse "
                       "hors du total des soutiens pour ne pas compter deux fois les mêmes crédits.",
        },
        "recettes_fonds_de_soutien": {
            "annee": 2025, "page": r["page"],
            "taxes": [{"taxe": t, "sigle": sg, "montant_meur": v} for t, sg, v in r["taxes"]],
            "produit_brut_meur": r["produit_brut_meur"],
            "prelevement_budget_de_gestion_meur": r["prelevement_meur"],
            "total_net_meur": r["total_net_meur"],
            "lecture": "Produit des taxes affectées au fonds de soutien, puis prélèvement pour le budget de gestion du "
                       "CNC ; le reste finance les soutiens.",
        },
        "controles": controles,
    }


# ------------------------------------------------------------------------------------------------------- index

def _sources_index() -> list[dict]:
    man = _manifeste()
    out = []
    for cle, s in SOURCES.items():
        e = man.get(s["id_catalogue"], {}) if isinstance(man, dict) else {}
        out.append({"cle": cle, "id_catalogue": s["id_catalogue"], "titre": s["titre"], "page": s["page"],
                    "licence": s["licence"], "collecte_le": (e.get("collecte_le") or "")[:10] or None})
    return out


def construire_index(budget: dict, av: dict, presse: dict, cnc: dict, tailles: dict) -> dict:
    culture = next(m for m in budget["missions"] if m["mission"] == "Culture")["somme_programmes"]
    medias = next(m for m in budget["missions"] if m["mission"] != "Culture")["somme_programmes"]
    t25 = next(t for t in av["totaux"] if t["annee"] == 2025)
    rec25 = next(r for r in av["financement"]["recettes"] if r["annee"] == 2025)
    dern = presse["classement_titres"]["par_annee"][-1]
    return {
        "millesime": "Budget : exécution 2024 à PLF 2026 ; audiovisuel : 2023 à PLF 2026 ; presse : 2012 à 2025 ; "
                     "CNC : 2025",
        "source": "data.economie.gouv.fr (budget vert du PLF 2026, PLRG 2023 à 2025) ; data.gouv.fr (ministère de "
                  "la Culture, aides à la presse) ; cnc.fr (Bilan 2025)",
        "unite": "euros, sauf cnc.json (millions d'euros)",
        "date_sources": date_sources(DOMAINE),
        "avertissement": "Quatre vues de l'argent public de la culture et des médias, chacune avec sa source et son "
                         "année. Elles se recoupent (les aides à la presse sont aussi des crédits du programme 180) et "
                         "ne s'additionnent pas entre elles.",
        "fichiers": [
            {"fichier": "culture_medias/budget.json", "contenu": "missions Culture et Médias, livre et industries "
             "culturelles : programmes, actions, dépenses fiscales, taxes affectées", **tailles["budget"]},
            {"fichier": "culture_medias/audiovisuel.json", "contenu": "dotations aux sociétés de l'audiovisuel public "
             "et financement du compte de concours financiers", **tailles["audiovisuel"]},
            {"fichier": "culture_medias/presse.json", "contenu": "aides à la presse par titre, par groupe et par "
             "dispositif", **tailles["presse"]},
            {"fichier": "culture_medias/cnc.json", "contenu": "soutiens du CNC par dispositif et recettes de son fonds "
             "de soutien", **tailles["cnc"]},
        ],
        "reperes": {
            "budget": {"mission_culture_lfi_2025_eur": culture["lfi_2025_eur"],
                       "mission_culture_plf_2026_eur": culture["plf_2026_eur"],
                       "mission_culture_execution_2025_eur": culture["plrg_2025_depenses_constatees_eur"],
                       "mission_medias_lfi_2025_eur": medias["lfi_2025_eur"],
                       "mission_medias_plf_2026_eur": medias["plf_2026_eur"],
                       "mission_medias_execution_2025_eur": medias["plrg_2025_depenses_constatees_eur"],
                       "statut": "calculé"},
            "audiovisuel": {"annee": 2025, "depenses_constatees_eur": t25["depenses_constatees_eur"],
                            "recouvrements_eur": rec25["recouvrements_eur"], "statut": "calculé"},
            "presse": {"annee": dern["annee"], "titres": dern["titres"], "total_aides_eur": dern["total_aides_eur"],
                       "statut": "calculé"},
            "cnc": {"annee": 2025, "soutiens_meur": cnc["soutiens"]["total_meur"],
                    "recettes_nettes_meur": cnc["recettes_fonds_de_soutien"]["total_net_meur"], "statut": "publié"},
        },
        "limites": [
            "La loi de finances initiale 2026 par action n'est pas reprise : la seule source ouverte lisible est le "
            "budget vert du PLF 2026 (projet).",
            "Le classement consolidé des titres de presse aidés s'arrête à 2023 ; les tableaux par dispositif vont "
            "jusqu'à 2025, sans 2024.",
            "Les soutiens du CNC sont des agrégats relus dans un PDF ; aucune aide par bénéficiaire n'est publiée en "
            "données ouvertes.",
            "Les dépenses des collectivités pour la culture ne sont pas dans cette vue (voir les budgets locaux).",
        ],
        "sources": _sources_index(),
        "sources_inaccessibles": SOURCES_INACCESSIBLES,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }


# ----------------------------------------------------------------------------------------------------- sortie

def _ecrire(chemin: Path, doc: dict) -> dict:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(_nettoyer(doc), ensure_ascii=False, separators=(",", ":"))
    octets = len(texte.encode("utf-8"))
    if octets > 1_000_000:
        raise DonneeInattendue(f"{chemin.name} dépasse 1 Mo ({octets} octets)")
    chemin.write_text(texte, encoding="utf-8")
    return {"octets": octets}


def produire(sortie: Path = SORTIE) -> None:
    bv = lire_budget_vert()
    budget = construire_budget(bv)
    av = construire_audiovisuel(bv)
    presse = construire_presse(bv)
    cnc = construire_cnc()
    tailles = {"budget": _ecrire(sortie / "budget.json", budget),
               "audiovisuel": _ecrire(sortie / "audiovisuel.json", av),
               "presse": _ecrire(sortie / "presse.json", presse),
               "cnc": _ecrire(sortie / "cnc.json", cnc)}
    _ecrire(sortie / "index.json", construire_index(budget, av, presse, cnc, tailles))
    print(f"culture_medias : 5 fichiers écrits dans {sortie}", file=sys.stderr)


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
