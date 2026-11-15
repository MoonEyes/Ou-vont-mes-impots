"""Precision de l'arbre Etat : nature reelle, effectifs et beneficiaires nommes, par programme.

Entrees : entrepot brut data/lake/ (non versionne) et site/data/arbre/racine.json (arbre Etat, execution 2024).
Sorties (chaque fichier porte `millesime` et `source`) :
  site/data/nature/<programme>.json            nature reelle de la depense 2024 (PLRG 2024, annexe 1, titre x categorie)
  site/data/effectifs/<programme>.json         ETPT (dernier millesime publie par programme) et cout moyen par ETPT
  site/data/beneficiaires/programme_<n>.json   associations subventionnees (jaune) et operateurs rattaches
  site/data/beneficiaires/france2030.json      France 2030 par operateur et par beneficiaire
  site/data/beneficiaires/marches_etat.json    marches publics des services de l'Etat, par ministere et titulaire
  site/data/beneficiaires/index.json           index des fichiers et totaux de controle

Regle personnes physiques (bloquante) : seules les personnes morales (categorie juridique 2xxx a 9xxx, lue dans
la source ou via l'API Recherche d'entreprises, cache disque) sont nommees. Le reste est agrege dans
`exclus_personnes_physiques_ou_non_identifies`.

Commandes (chacune courte ; les resolutions SIREN sont reprenables) :
  python pipeline/beneficiaires.py resoudre {associations|france2030|acheteurs|titulaires} [--budget 480]
  python pipeline/beneficiaires.py nature effectifs associations operateurs france2030 marches index
  python pipeline/beneficiaires.py tout          # toutes les sorties, sans appel reseau (cache seul)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import sirene

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
TOP = 50
TOLERANCE_NATURE_PCT = 3.0  # ecart tolere, au total, entre la nature (PLRG brut) et l arbre (budget vert retraite)

SRC = {
    "plrg_titre_cat": {
        "chemin": LAKE / "etat" / "plrg_2024" / "annexe1_etat_titre_cat_2024.csv",
        "dataset": "plrg-2024", "piece_jointe": "annexe1_etat_titre_cat_2024_csv",
        "source": "data.economie.gouv.fr/plrg-2024, annexe 1 « état titre catégorie » (dépenses constatées 2024)"},
    "etpt": {
        "chemin": LAKE / "etat" / "etat_etpt_lfi_2023.parquet",
        "source": "data.economie.gouv.fr/etpt-par-ministere-mission-programme-pour-le-bg-et-les-ba-lfi-2023"},
    "associations": {
        "chemin": LAKE / "beneficiaires" / "benef_associations_plf25.parquet",
        "source": "data.economie.gouv.fr/plf25-donnees-de-l-annexe-jaune-effort-financier-de-l-etat-en-faveur-des-"
                  "associations (jaune PLF 2025, crédits versés en 2023)"},
    "operateurs": {
        "chemin": LAKE / "etat" / ("datagouv__projet-de-loi-de-finances-pour-2025-plf-2025-jaune-operateurs-de-letat-"
                                   "liste-des-operateurs-et-categories"),
        "source": "data.gouv.fr, PLF 2025, jaune « Opérateurs de l'État », liste des opérateurs et catégories"},
    "france2030": {
        "chemin": LAKE / "aides_entreprises" / "aides_france2030_projets.csv",
        "source": "data.gouv.fr « France 2030 » (Préfecture de région Bretagne, geobretagne.fr, france2030_projets.csv), "
                  "projets lauréats décidés de 2021 à 2025"},
    "decp": {
        "chemin": LAKE / "_restreint" / "beneficiaires" / "benef_decp" / "decp_11cea8e8.parquet",
        "source": "data.gouv.fr, données essentielles de la commande publique consolidées (DECP, format tabulaire)"},
}
SOURCE_API = "API Recherche d'entreprises (recherche-entreprises.api.gouv.fr), catégorie juridique"

# --- Utilitaires ------------------------------------------------------------------------------------------------


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 5_000_000:
        raise SystemExit(f"{path} depasse 5 Mo : decouper")
    path.write_text(texte + "\n", encoding="utf-8")


def vider(dossier: Path, motif: str = "*.json") -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    for f in dossier.glob(motif):
        f.unlink()


def propre(v) -> str:
    """Espaces insecables, retours a la ligne et espaces multiples -> un espace."""
    if v is None:
        return ""
    s = unicodedata.normalize("NFC", str(v)).replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def num(v) -> float:
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))


def dicts(rel) -> list[dict]:
    """Lignes d'une requete DuckDB en dictionnaires (None pour les valeurs absentes, jamais NaN)."""
    cols = rel.columns
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def eur(v: float) -> float:
    return round(v, 2)


def telecharger_piece_jointe(cle: str) -> None:
    """Piece jointe ODS manquante dans l'entrepot : telechargee comme dans fetch.py (reprises sur coupure)."""
    import fetch
    s = SRC[cle]
    url = f"{fetch.CONFIG['ods_base']}/{s['dataset']}/attachments/{s['piece_jointe']}"
    print(f"  telechargement {url}", file=sys.stderr)
    contenu = fetch.decode_csv(fetch.get(url).content)
    s["chemin"].parent.mkdir(parents=True, exist_ok=True)
    s["chemin"].write_text(contenu, encoding="utf-8")


# --- Arbre Etat (reference des montants et du « sur 100 € ») ------------------------------------------------------


def arbre_programmes() -> tuple[dict, dict]:
    racine = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    progs = {}

    def walk(n, chemin):
        if n["niveau"] == "programme":
            num_p = n["id"].split("/")[-1]
            if num_p in progs:  # programme scinde entre deux branches : on cumule
                progs[num_p]["eur"] += n["md"] * 1e9
            else:
                progs[num_p] = {"programme": num_p, "nom": n["nom"], "mission": chemin[-1] if chemin else None,
                                "grand_poste": chemin[0] if chemin else None, "eur": n["md"] * 1e9,
                                "id_arbre": n["id"], "fichier_arbre": n.get("fichier")}
            return
        for e in n.get("enfants", []):
            walk(e, chemin + [e["nom"]] if e["niveau"] in ("grand_poste", "mission") else chemin)

    walk(racine, [])
    entete = {"millesime": racine["millesime"], "total_eur": racine["md"] * 1e9}
    return progs, entete


def sur_100(montant: float, total: float) -> float:
    return round(montant / total * 100, 6) if total else None


# --- 1. Nature reelle --------------------------------------------------------------------------------------------

POSTES_NATURE = [
    ("salaires", "Salaires (rémunérations d'activité)", ["21"]),
    ("cotisations", "Cotisations et contributions sociales (dont pensions des fonctionnaires)", ["22"]),
    ("prestations_employeur", "Prestations sociales versées par l'employeur", ["23"]),
    ("fonctionnement", "Fonctionnement courant (achats, loyers, informatique...)", ["31"]),
    ("subventions_operateurs", "Subventions de fonctionnement aux opérateurs de l'État", ["32"]),
    ("interventions_menages", "Aides versées aux ménages", ["61"]),
    ("interventions_entreprises", "Aides versées aux entreprises", ["62"]),
    ("interventions_collectivites", "Versements aux collectivités territoriales", ["63"]),
    ("interventions_autres", "Versements à d'autres organismes (associations, Sécurité sociale, international...)",
     ["64"]),
    ("appels_garantie", "Appels en garantie", ["65"]),
    ("investissement", "Investissement (bâtiments, équipements, subventions d'investissement)", ["51", "52", "53"]),
    ("dette", "Charges de la dette", ["41", "42", "43"]),
    ("pouvoirs_publics", "Dotations des pouvoirs publics", ["10"]),
    ("operations_financieres", "Prêts, avances et prises de participation", ["71", "72", "73"]),
]
LIB_CAT = {
    "10": "Dotations des pouvoirs publics", "21": "Rémunérations d'activité",
    "22": "Cotisations et contributions sociales", "23": "Prestations sociales et allocations diverses",
    "31": "Dépenses de fonctionnement autres que celles de personnel",
    "32": "Subventions pour charges de service public", "41": "Intérêts de la dette financière négociable",
    "42": "Intérêts de la dette financière non négociable", "43": "Charges financières diverses",
    "51": "Dépenses pour immobilisations corporelles de l'État",
    "52": "Dépenses pour immobilisations incorporelles de l'État", "53": "Subventions pour charges d'investissement",
    "61": "Transferts aux ménages", "62": "Transferts aux entreprises", "63": "Transferts aux collectivités territoriales",
    "64": "Transferts aux autres collectivités", "65": "Appels en garantie", "71": "Prêts et avances",
    "72": "Dotations en fonds propres", "73": "Dépenses de participations financières",
}


def lire_titre_cat() -> dict:
    s = SRC["plrg_titre_cat"]
    if not s["chemin"].exists():
        telecharger_piece_jointe("plrg_titre_cat")
    lignes = list(csv.DictReader(io.StringIO(s["chemin"].read_text(encoding="utf-8-sig")), delimiter=";"))
    attendu = {"Mission", "Programme", "Titre", "Categorie", "Depenses"}
    if not lignes or not attendu <= set(lignes[0]):
        raise SystemExit(f"Colonnes inattendues dans {s['chemin']} : {list(lignes[0]) if lignes else []}")
    out = {}
    for r in lignes:
        m = re.search(r"(\d{3})\s*$", r["Programme"])
        if not m:
            raise SystemExit(f"Programme illisible : {r['Programme']}")
        p = m.group(1)
        d = out.setdefault(p, {"mission": propre(r["Mission"]),
                               "libelle": re.sub(r"\s*-\s*\d{3}\s*$", "", propre(r["Programme"])),
                               "categories": defaultdict(float)})
        d["categories"][r["Categorie"].strip()] += num(r["Depenses"])
    return out


def nature() -> dict:
    progs, ent = arbre_programmes()
    data = lire_titre_cat()
    vider(SITE / "nature")
    vider(SITE / "nature", "*.csv")
    cat_vers_poste = {c: (pid, lib) for pid, lib, cats in POSTES_NATURE for c in cats}
    inconnues = {c for d in data.values() for c in d["categories"]} - set(cat_vers_poste)
    if inconnues:
        raise SystemExit(f"Categories LOLF inconnues : {inconnues}")
    total_nature_arbre, total_arbre_couvert, n = 0.0, 0.0, 0
    hors_arbre = []
    for p, d in sorted(data.items()):
        total = sum(d["categories"].values())
        a = progs.get(p)
        if a is None:
            hors_arbre.append(p)
        postes = defaultdict(float)
        for c, v in d["categories"].items():
            postes[cat_vers_poste[c][0]] += v
        sortie_postes = [{"id": pid, "libelle": lib, "categories": cats, "eur": eur(postes[pid]),
                          "part_programme_pct": round(postes[pid] / total * 100, 2) if total else None,
                          "eur_sur_100": sur_100(postes[pid], ent["total_eur"])}
                         for pid, lib, cats in POSTES_NATURE if postes.get(pid)]
        sortie_postes.sort(key=lambda x: -x["eur"])
        ecart = (total - a["eur"]) if a else None
        obj = {
            "millesime": "Exécution 2024", "source": SRC["plrg_titre_cat"]["source"],
            "unite": "euros (crédits de paiement, dépenses constatées)",
            "programme": p, "libelle": d["libelle"], "mission": d["mission"],
            "total_eur": eur(total),
            "eur_sur_100": sur_100(total, ent["total_eur"]),
            "postes": sortie_postes,
            "categories": sorted([{"code": c, "libelle": LIB_CAT[c], "eur": eur(v)}
                                  for c, v in d["categories"].items() if v], key=lambda x: -x["eur"]),
            "controle_arbre": {
                "millesime_arbre": ent["millesime"], "total_arbre_eur": eur(a["eur"]) if a else None,
                "ecart_eur": eur(ecart) if a else None,
                "ecart_pct": round(ecart / a["eur"] * 100, 2) if a and a["eur"] else None,
                "explication": ("L'arbre suit le budget vert du PLF 2026 (exécution 2024 retraitée au périmètre 2026, "
                                "hors fonds de concours et mesures de périmètre) ; la nature suit le PLRG 2024 (dépenses "
                                "constatées brutes). Un écart signale ces retraitements."
                                if a else "Programme absent de l'arbre (remboursements et dégrèvements, ou fusionné).")},
        }
        dump(SITE / "nature" / f"{p}.json", obj)
        n += 1
        if a:
            total_nature_arbre += total
            total_arbre_couvert += a["eur"]
    absents = sorted(set(progs) - set(data))
    ecart_global = (total_nature_arbre - total_arbre_couvert) / total_arbre_couvert * 100
    stats = {"fichiers": n, "programmes_hors_arbre": hors_arbre, "programmes_arbre_sans_nature": absents,
             "total_nature_programmes_arbre_eur": eur(total_nature_arbre),
             "total_arbre_meme_programmes_eur": eur(total_arbre_couvert),
             "ecart_global_pct": round(ecart_global, 3), "tolerance_pct": TOLERANCE_NATURE_PCT}
    if abs(ecart_global) > TOLERANCE_NATURE_PCT:
        raise SystemExit(f"Nature et arbre divergent de {ecart_global:.2f} % (tolerance {TOLERANCE_NATURE_PCT} %)")
    return stats


# --- 2. Effectifs ------------------------------------------------------------------------------------------------


def effectifs() -> dict:
    import duckdb
    progs, ent = arbre_programmes()
    nat = lire_titre_cat()
    s = SRC["etpt"]
    rows = duckdb.sql(f"""select cast(cast(code_programme as int) as varchar) p, programme, budget,
                                 code_categorie_d_emploi0 cat, sum(etpt_lfi_2023) etpt
                          from '{s['chemin']}' group by all""").fetchall()
    par_p = defaultdict(lambda: {"libelle": None, "budget": None, "categories": []})
    for p, lib, budget, cat, etpt in rows:
        p = p.zfill(3)
        par_p[p]["libelle"] = propre(lib)
        par_p[p]["budget"] = budget
        par_p[p]["categories"].append({"categorie_emploi": propre(cat), "etpt": round(etpt, 2)})
    vider(SITE / "effectifs")
    vider(SITE / "effectifs", "*.csv")
    n = 0
    for p in sorted(set(par_p) | {k for k, d in nat.items() if any(c in d["categories"] for c in ("21", "22", "23"))}):
        e = par_p.get(p)
        t2 = sum(v for c, v in nat.get(p, {"categories": {}})["categories"].items() if c in ("21", "22", "23"))
        etpt = round(sum(c["etpt"] for c in e["categories"]), 2) if e else None
        cout = round(t2 / etpt) if etpt and t2 else None
        obj = {
            "millesime": "ETPT : LFI 2023 (dernier millésime publié par programme) ; titre 2 : exécution 2024",
            "source": f"{s['source']} ; {SRC['plrg_titre_cat']['source']}",
            "programme": p, "libelle": (e or {}).get("libelle") or nat.get(p, {}).get("libelle"),
            "etpt": etpt, "millesime_etpt": "LFI 2023" if e else None,
            "nature_etpt": "plafond d'emplois voté (LFI), pas l'effectif réellement consommé",
            "categories_emploi": sorted((e or {}).get("categories", []), key=lambda c: -c["etpt"]),
            "titre2_eur": eur(t2) if t2 else None, "millesime_titre2": "Exécution 2024",
            "eur_sur_100_titre2": sur_100(t2, ent["total_eur"]) if t2 else None,
            "cout_moyen_par_etpt_eur": cout,
            "avertissement": ("Millésimes différents : dépenses de personnel 2024 (PLRG 2024) divisées par les ETPT "
                              "votés en LFI 2023. Le titre 2 inclut les cotisations employeur et la contribution au "
                              "compte d'affectation spéciale Pensions : c'est un coût complet employeur, pas un salaire. "
                              "Un programme réorganisé entre 2023 et 2024 peut donner un ratio faux."
                              if cout else ("Pas d'ETPT publié pour ce programme en LFI 2023 (programme créé ou "
                                            "renuméroté depuis)." if t2 and not e else None)),
        }
        dump(SITE / "effectifs" / f"{p}.json", obj)
        n += 1
    return {"fichiers": n, "millesime_etpt": "LFI 2023",
            "etpt_total_lfi_2023": round(sum(c["etpt"] for e in par_p.values() for c in e["categories"]), 1)}


# --- Classement personne morale / exclus ---------------------------------------------------------------------------


def statut(siren: str, cj_source, cache: dict) -> tuple[str, str | None]:
    """('pm', cj) personne morale publiable ; ('pp', cj) personne physique ; ('ni', None) non identifiee ;
    ('nv', None) SIREN valide dont la categorie n'est pas encore verifiee (agrege, jamais nomme)."""
    if not sirene.siren_valide(siren):
        return "ni", None
    cj = str(cj_source).split(".")[0] if cj_source not in (None, "") else ""
    if not sirene.CJ_RE.match(cj) or cj == "0000":
        c = cache.get(siren)
        if c is None:
            return "nv", None
        cj = c.get("cj") or ""
    if sirene.personne_morale(cj):
        return "pm", cj
    if cj.startswith("1"):
        return "pp", cj
    return "ni", None


NOTE_NV = "SIREN valide dont la catégorie juridique n'a pas encore été vérifiée : agrégés, jamais nommés"


def non_verifies() -> dict:
    return {"montant": 0.0, "sirens": set()}


def sortie_nv(nv: dict) -> dict:
    return {"montant_eur": eur(nv["montant"]), "nombre": len(nv["sirens"]), "note": NOTE_NV}


def top_et_autres(par_siren: dict, total_source: float, exclus: dict, nv: dict) -> dict:
    """par_siren : siren -> {montant, ...} (personnes morales seulement).
    Conservation : top + autres + non verifies + exclus = total de la source."""
    tries = sorted(par_siren.items(), key=lambda kv: (-kv[1]["montant"], kv[0]))
    top = [{"siren": s, **{k: v for k, v in d.items() if k != "montant"}, "montant_eur": eur(d["montant"])}
           for s, d in tries[:TOP]]
    reste = tries[TOP:]
    autres = {"nombre": len(reste), "montant_eur": eur(sum(d["montant"] for _, d in reste))}
    somme = sum(d["montant"] for _, d in tries) + exclus["montant_eur"] + nv["montant"]
    if abs(somme - total_source) > 1:
        raise SystemExit(f"Conservation rompue : {somme} != {total_source}")
    return {"top": top, "autres": autres, "non_verifies": sortie_nv(nv)}


# --- 3a. Associations ----------------------------------------------------------------------------------------------


def _assoc_lignes():
    import duckdb
    s = SRC["associations"]
    return duckdb.sql(f"select programme, siren, denomination, montant, objet_2023, categorie_juridique "
                      f"from '{s['chemin']}'").fetchall()


def tour_de_role(groupes) -> list[str]:
    """SIREN par montant decroissant, chaque groupe a tour de role (les top 50 de chaque groupe d'abord)."""
    rangs = [sorted(g, key=lambda s: -g[s]) for g in groupes if g]
    ordre = []
    for i in range(max((len(r) for r in rangs), default=0)):
        ordre += [r[i] for r in rangs if i < len(r)]
    return list(dict.fromkeys(ordre))


def sirens_associations() -> list[str]:
    """SIREN dont la categorie n'est pas lisible dans la source, a verifier via l'API."""
    par_prog = defaultdict(lambda: defaultdict(float))
    for prog, siren, _, montant, _, cj in _assoc_lignes():
        siren = propre(siren)
        if sirene.siren_valide(siren):
            par_prog[prog][siren] += montant or 0
    lisibles = {propre(s) for _, s, _, _, _, cj in _assoc_lignes() if sirene.CJ_RE.match(str(cj or "")) and cj != "0000"}
    return [s for s in tour_de_role(par_prog.values()) if s not in lisibles]


def associations() -> dict:
    cache = sirene.charger_cache()
    progs, ent = arbre_programmes()
    par_prog = defaultdict(lambda: {"total": 0.0, "lignes": 0, "pm": {}, "nv": non_verifies(), "exclus": {"montant_eur": 0.0, "lignes": 0,
                                                                                    "dont_siren_nr_chorus_eur": 0.0,
                                                                                    "dont_personnes_physiques_eur": 0.0,
                                                                                    "dont_categorie_inconnue_eur": 0.0}})
    lignes = _assoc_lignes()
    cj_lisible = {propre(si): cj for _, si, _, _, _, cj in lignes if sirene.CJ_RE.match(str(cj or "")) and cj != "0000"}
    for prog, siren, denom, montant, objet, cj in lignes:
        prog = propre(prog).zfill(3)
        siren = propre(siren)
        montant = float(montant or 0)
        d = par_prog[prog]
        d["total"] += montant
        d["lignes"] += 1
        st, cj_ok = statut(siren, cj_lisible.get(siren, cj), cache)
        if st == "nv":
            d["nv"]["montant"] += montant
            d["nv"]["sirens"].add(siren)
            continue
        if st != "pm":
            x = d["exclus"]
            x["montant_eur"] += montant
            x["lignes"] += 1
            if "CHORUS" in siren.upper():
                x["dont_siren_nr_chorus_eur"] += montant
            elif st == "pp":
                x["dont_personnes_physiques_eur"] += montant
            else:
                x["dont_categorie_inconnue_eur"] += montant
            continue
        a = d["pm"].setdefault(siren, {"denomination": propre(denom) or (cache.get(siren) or {}).get("nom"),
                                       "categorie_juridique": cj_ok, "objets": [], "montant": 0.0, "lignes": 0})
        a["montant"] += montant
        a["lignes"] += 1
        o = propre(objet)
        if o and o not in a["objets"] and len(a["objets"]) < 3:
            a["objets"].append(o)
    res = {}
    for prog, d in par_prog.items():
        for x in ("montant_eur", "dont_siren_nr_chorus_eur", "dont_personnes_physiques_eur",
                  "dont_categorie_inconnue_eur"):
            d["exclus"][x] = eur(d["exclus"][x])
        for a in d["pm"].values():
            a["objet"] = " ; ".join(a.pop("objets")) or None
        ta = top_et_autres(d["pm"], d["total"], d["exclus"], d["nv"])
        for b in ta["top"]:
            b["eur_sur_100"] = sur_100(b["montant_eur"], ent["total_eur"])
        res[prog] = {"autres_non_verifies": ta["non_verifies"], "millesime": "Crédits versés en 2023 (jaune PLF 2025)", "source": SRC["associations"]["source"]
                     + " ; " + SOURCE_API, "total_source_eur": eur(d["total"]), "lignes_source": d["lignes"],
                     "personnes_morales": len(d["pm"]), "top": ta["top"],
                     "autres_personnes_morales": ta["autres"],
                     "exclus_personnes_physiques_ou_non_identifies": d["exclus"],
                     "eur_sur_100": sur_100(d["total"], ent["total_eur"])}
    return res


# --- 3b. Operateurs ----------------------------------------------------------------------------------------------


def operateurs() -> dict:
    s = SRC["operateurs"]
    fichier = sorted(s["chemin"].glob("*.csv"))[0]
    texte = fichier.read_bytes().decode("cp1252")
    lignes = list(csv.reader(io.StringIO(texte), delimiter=";"))
    entete = [propre(c) for c in lignes[0]]
    if entete[:4] != ["Opérateur ou catégorie d'opérateurs", "Opérateur de la catégorie", "Statut",
                      "Mission et Programme chefs de file"]:
        raise SystemExit(f"Colonnes inattendues dans {fichier} : {entete}")
    res = defaultdict(list)
    for r in lignes[1:]:
        if len(r) < 4 or not propre(r[0]):
            continue
        m = re.search(r"\n\s*(\d{3})\b", r[3]) or re.search(r"\b(\d{3})\b", r[3])
        if not m:
            continue
        res[m.group(1)].append({"operateur": propre(r[1]) or propre(r[0]),
                                "categorie": propre(r[0]) if propre(r[1]) else None, "statut": propre(r[2]) or None})
    millesime = propre(lignes[1][4]) if len(lignes[1]) > 4 else "2025"
    return {p: {"millesime": f"PLF {millesime}", "source": s["source"],
                "note": "Liste des opérateurs dont ce programme est chef de file. La source ne donne pas de montant "
                        "par opérateur ; leurs subventions figurent dans la nature du programme (catégories 32 et 53).",
                "nombre": len(v), "liste": sorted(v, key=lambda x: (x["categorie"] or "", x["operateur"]))}
            for p, v in res.items()}


# --- 3c. France 2030 -------------------------------------------------------------------------------------------------

OPERATEURS_F2030 = {"BPI": "Bpifrance", "ANR": "ANR", "ADEME": "ADEME", "CDC": "Caisse des Dépôts", "DGAC": "DGAC",
                    "CNES": "CNES"}


def _siren_f2030(v) -> str:
    v = (v or "").strip()
    if not v or v in ("0", "0.0"):
        return ""
    try:
        return str(int(float(v))).zfill(9)
    except ValueError:
        return ""


def _f2030_lignes():
    import duckdb
    s = SRC["france2030"]
    rows = dicts(duckdb.sql(f"select distinct * from read_csv_auto('{s['chemin']}', all_varchar=true)"))
    total_brut = duckdb.sql(f"select count(*) from read_csv_auto('{s['chemin']}', all_varchar=true)").fetchall()[0][0]
    return rows, total_brut


def sirens_france2030() -> list[str]:
    rows, _ = _f2030_lignes()
    glob, par_op = defaultdict(float), defaultdict(lambda: defaultdict(float))
    for r in rows:
        s = _siren_f2030(r["siren"])
        if s and not sirene.CJ_RE.match(str(r.get("categorie_juridique") or "").split(".")[0]):
            glob[s] += num(r["montant_aide"])
            par_op[propre(r["operateur"]).upper()][s] += num(r["montant_aide"])
    return tour_de_role([glob] + list(par_op.values()))


def france2030() -> dict:
    cache = sirene.charger_cache()
    progs, ent = arbre_programmes()
    rows, total_brut = _f2030_lignes()

    def vide():
        return {"total": 0.0, "projets": 0, "pm": {}, "nv": non_verifies(),
                "exclus": {"montant_eur": 0.0, "lignes": 0, "dont_personnes_physiques_eur": 0.0,
                           "dont_sans_siren_eur": 0.0, "dont_categorie_inconnue_eur": 0.0}}

    groupes = {"tous": vide()}
    par_op, par_prog = defaultdict(vide), defaultdict(vide)
    for r in rows:
        montant = num(r["montant_aide"])
        op = OPERATEURS_F2030.get(propre(r["operateur"]).upper(), propre(r["operateur"]))
        prog = (re.match(r"\s*(\d{3})", str(r.get("actions") or "")) or [None, None])[1]
        siren = _siren_f2030(r["siren"])
        st, cj = statut(siren, r.get("categorie_juridique"), cache)
        cibles = [groupes["tous"], par_op[op]] + ([par_prog[prog]] if prog else [])
        for g in cibles:
            g["total"] += montant
            g["projets"] += 1
            if st == "nv":
                g["nv"]["montant"] += montant
                g["nv"]["sirens"].add(siren)
                continue
            if st != "pm":
                x = g["exclus"]
                x["montant_eur"] += montant
                x["lignes"] += 1
                cle = ("dont_sans_siren_eur" if not siren else
                       "dont_personnes_physiques_eur" if st == "pp" else "dont_categorie_inconnue_eur")
                x[cle] += montant
                continue
            nom = propre(r.get("denomination")) or (cache.get(siren) or {}).get("nom")
            b = g["pm"].setdefault(siren, {"denomination": nom, "categorie_juridique": cj, "typologie": None,
                                           "operateurs": [], "montant": 0.0, "projets": 0})
            b["montant"] += montant
            b["projets"] += 1
            b["typologie"] = b["typologie"] or propre(r.get("typologie")) or None
            if op not in b["operateurs"]:
                b["operateurs"].append(op)

    def sortie(g):
        for k in list(g["exclus"]):
            g["exclus"][k] = eur(g["exclus"][k]) if k != "lignes" else g["exclus"][k]
        ta = top_et_autres(g["pm"], g["total"], g["exclus"], g["nv"])
        for b in ta["top"]:
            b["eur_sur_100"] = sur_100(b["montant_eur"], ent["total_eur"])
        return {"total_eur": eur(g["total"]), "projets": g["projets"], "beneficiaires_personnes_morales": len(g["pm"]),
                "top": ta["top"], "autres_personnes_morales": ta["autres"], "autres_non_verifies": ta["non_verifies"],
                "exclus_personnes_physiques_ou_non_identifies": g["exclus"]}

    obj = {"millesime": "Projets France 2030 décidés de 2021 à 2025 (montants d'aide engagés, cumulés)",
           "source": SRC["france2030"]["source"] + " ; " + SOURCE_API,
           "unite": "euros (subvention + avance remboursable)",
           "note": ("Montants engagés sur plusieurs années, à ne pas comparer à la dépense 2024. Les noms affichés sont "
                    "les dénominations officielles (SIRENE) des personnes morales ; les lignes sans SIREN valide ou "
                    "d'entrepreneurs individuels sont agrégées."),
           "lignes_source": total_brut, "doublons_exacts_retires": total_brut - len(rows),
           "ensemble": sortie(groupes["tous"]),
           "par_operateur": {op: sortie(g) for op, g in sorted(par_op.items(), key=lambda kv: -kv[1]["total"])},
           "par_programme": {p: {"total_eur": eur(g["total"]), "projets": g["projets"],
                                 "libelle": (progs.get(p) or {}).get("nom")}
                             for p, g in sorted(par_prog.items())}}
    dump(SITE / "beneficiaires" / "france2030.json", obj)
    return {"total_eur": obj["ensemble"]["total_eur"],
            "exclus_eur": obj["ensemble"]["exclus_personnes_physiques_ou_non_identifies"]["montant_eur"]}


# --- 3d. Marches publics des services de l'Etat -----------------------------------------------------------------------

ANNEE_MARCHES = 2024
MINISTERES = [  # (motif dans le nom SIRENE ou DECP de l'acheteur, ministere) ; premier motif trouve
    (r"ARMEE|DEFENSE|MARINE NATIONALE|AIR ET DE L'ESPACE|DGA\b|ARMEMENT|COMMISSARIAT DES ARMEES|SERVICE DE SANTE DES "
     r"ARMEES|SID\b|INFRASTRUCTURE DE LA DEFENSE|LEGION|GENIE", "Armées"),
    (r"GENDARMERIE|POLICE|PREFECTURE|PREFET|INTERIEUR|SECURITE CIVILE|DEPAFI|EVALUATION DE LA PERFORMANCE ET DES "
     r"AFFAIRES FINANCIERES|SGAMI|SECRETARIAT GENERAL POUR L'ADMINISTRATION|SGAR|AFFAIRES REGIONALES|"
     r"DIRECTION DEPARTEMENTALE|OUTRE-MER|DDETS|DDPP|DDT", "Intérieur et outre-mer"),
    (r"JUSTICE|PENITENTIAIRE|JUDICIAIRE|PROTECTION JUDICIAIRE|TRIBUNAL|COUR D'APPEL|GARDE DES SCEAUX", "Justice"),
    (r"EDUCATION NATIONALE|RECTORAT|ACADEMIE|JEUNESSE|SPORT", "Éducation nationale, jeunesse et sports"),
    (r"ENSEIGNEMENT SUPERIEUR|RECHERCHE", "Enseignement supérieur et recherche"),
    (r"FINANCES PUBLIQUES|DGFIP|DOUANE|ECONOMI|BUDGET|ACHATS DE L'ETAT|AIFE|INFORMATIQUE FINANCIERE|"
     r"FACTURATION ELECTRONIQUE|INSEE|TRESOR|CONCURRENCE|DGCCRF|COMPTES PUBLICS|IMMOBILIERE DE L'ETAT", "Économie et finances"),
    (r"AGRICULTURE|ALIMENTATION|FORET|DRAAF|DAAF", "Agriculture et alimentation"),
    (r"ECOLOGI|TRANSITION|ENVIRONNEMENT|AMENAGEMENT ET DU LOGEMENT|DREAL|DEAL\b|DRIEAT|DRIEA|EQUIPEMENT|"
     r"AVIATION CIVILE|DGAC|ROUTES|DIR\b|MER\b|AFFAIRES MARITIMES|TERRITOIRES|LOGEMENT|TRANSPORTS|METEO",
     "Transition écologique et cohésion des territoires"),
    (r"TRAVAIL|EMPLOI|SOLIDARIT|SANTE|DREETS|DIECCTE|AFFAIRES SOCIALES|COHESION SOCIALE", "Travail, santé et solidarités"),
    (r"CULTURE|DRAC|PATRIMOINE|ARCHIVES", "Culture"),
    (r"EUROPE ET DES AFFAIRES ETRANGERES|AFFAIRES ETRANGERES|AMBASSADE|CONSULAT", "Europe et affaires étrangères"),
    (r"PREMIER MINISTRE|INFORMATION LEGALE|DILA|GOUVERNEMENT|SGDSN|NUMERIQUE|DINUM", "Services du Premier ministre"),
]


def _sans_accent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.upper()) if unicodedata.category(c) != "Mn")


def ministere(nom_sirene: str | None, nom_decp: str | None) -> str:
    for nom in (nom_sirene, nom_decp):
        t = _sans_accent(propre(nom))
        if not t:
            continue
        for motif, m in MINISTERES:
            if re.search(motif, t):
                return m
    return "État, ministère non identifié"


def _decp():
    import duckdb
    c = duckdb.connect()
    c.sql(f"create view d as select * from '{SRC['decp']['chemin']}'")
    return c


def sirens_acheteurs() -> list[str]:
    c = _decp()
    return [r[0] for r in c.sql("""select left(acheteur_id, 9) s, sum(montant) m from d
                                   where acheteur_categorie = 'État' or left(acheteur_id, 2) = '11'
                                   group by 1 order by m desc nulls last""").fetchall()]


def _marches_etat(cache: dict):
    """Lignes (uid, titulaire) de marches notifies en ANNEE_MARCHES par un service de l'Etat (categorie 71xx)."""
    c = _decp()
    acheteurs = [s for s in sirens_acheteurs() if str((cache.get(s) or {}).get("cj") or "").startswith("71")]
    c.execute("create table ach as select unnest(?::varchar[]) s", [acheteurs])
    return dicts(c.sql(f"""
        with base as (
          select uid, left(acheteur_id, 9) acheteur_siren, acheteur_nom, titulaire_id, titulaire_typeIdentifiant tid,
                 coalesce(montant_rationalise, montant) montant, montant_anomalie, modification_id
          from d where left(acheteur_id, 9) in (select s from ach)
            and year(dateNotification) = {ANNEE_MARCHES} and coalesce(donneesActuelles, true)),
        dedup as (
          select * from base qualify row_number() over (partition by uid, titulaire_id
                                                        order by modification_id desc nulls last) = 1),
        co as (select uid, count(*) n from dedup group by uid)
        select dedup.*, co.n co_titulaires from dedup join co using (uid)"""))


def sirens_titulaires() -> list[str]:
    """Titulaires a resoudre, par montant decroissant, chaque ministere a tour de role (top 50 garantis d'abord)."""
    cache = sirene.charger_cache()
    lignes = _marches_etat(cache)
    par_min = defaultdict(lambda: defaultdict(float))
    glob = defaultdict(float)
    for r in lignes:
        if r["tid"] == "SIRET" and r["montant_anomalie"] != "aberrant":
            s = str(r["titulaire_id"] or "")[:9]
            m = ministere((cache.get(r["acheteur_siren"]) or {}).get("nom"), r["acheteur_nom"])
            par_min[m][s] += (r["montant"] or 0) / r["co_titulaires"]
            glob[s] += (r["montant"] or 0) / r["co_titulaires"]
    return tour_de_role([glob] + list(par_min.values()))


def marches() -> dict:
    cache = sirene.charger_cache()
    lignes = _marches_etat(cache)

    def vide():
        return {"total": 0.0, "marches": set(), "pm": {}, "nv": non_verifies(),
                "exclus": {"montant_eur": 0.0, "lignes": 0, "dont_personnes_physiques_eur": 0.0,
                           "dont_identifiant_non_siret_eur": 0.0, "dont_categorie_inconnue_eur": 0.0}}

    tous, par_min = vide(), defaultdict(vide)
    ecartes = {"montant_aberrant_eur": 0.0, "lignes": 0}
    for r in lignes:
        montant = (r["montant"] or 0) / r["co_titulaires"]
        if r["montant_anomalie"] == "aberrant":
            ecartes["montant_aberrant_eur"] += montant
            ecartes["lignes"] += 1
            continue
        m = ministere((cache.get(r["acheteur_siren"]) or {}).get("nom"), r["acheteur_nom"])
        s = str(r["titulaire_id"] or "")[:9] if r["tid"] == "SIRET" else ""
        entree = cache.get(s) if s else None
        for g in (tous, par_min[m]):
            g["total"] += montant
            g["marches"].add(r["uid"])
            st, cj = statut(s, None, cache) if s else ("ni", None)
            if st == "nv":  # categorie juridique pas encore verifiee : jamais nomme
                g["nv"]["montant"] += montant
                g["nv"]["sirens"].add(s)
                continue
            if st != "pm":
                x = g["exclus"]
                x["montant_eur"] += montant
                x["lignes"] += 1
                cle = ("dont_identifiant_non_siret_eur" if not s else
                       "dont_personnes_physiques_eur" if st == "pp" else "dont_categorie_inconnue_eur")
                x[cle] += montant
                continue
            b = g["pm"].setdefault(s, {"denomination": entree.get("nom"), "categorie_juridique": cj,
                                       "marches": set(), "montant": 0.0})
            b["montant"] += montant
            b["marches"].add(r["uid"])

    def sortie(g):
        for k in list(g["exclus"]):
            g["exclus"][k] = eur(g["exclus"][k]) if k != "lignes" else g["exclus"][k]
        for b in g["pm"].values():
            b["nombre_marches"] = len(b.pop("marches"))
        nv = sortie_nv(g["nv"])
        tries = sorted(g["pm"].items(), key=lambda kv: (-kv[1]["montant"], kv[0]))
        top = [{"siren": s, "denomination": d["denomination"], "categorie_juridique": d["categorie_juridique"],
                "nombre_marches": d["nombre_marches"], "montant_eur": eur(d["montant"])} for s, d in tries[:TOP]]
        reste = tries[TOP:]
        autres = {"nombre": len(reste), "montant_eur": eur(sum(d["montant"] for _, d in reste))}
        somme = sum(d["montant"] for _, d in tries) + g["exclus"]["montant_eur"] + nv["montant_eur"]
        if abs(somme - g["total"]) > 1:
            raise SystemExit(f"Conservation rompue (marches) : {somme} != {g['total']}")
        return {"total_eur": eur(g["total"]), "nombre_marches": len(g["marches"]), "top": top,
                "autres_personnes_morales": autres,
                "autres_non_verifies": nv,
                "exclus_personnes_physiques_ou_non_identifies": g["exclus"]}

    obj = {"millesime": f"Marchés notifiés en {ANNEE_MARCHES}",
           "source": SRC["decp"]["source"] + " ; " + SOURCE_API,
           "unite": "euros HT (montant notifié ; pour un accord-cadre, montant maximum estimé)",
           "perimetre": ("Acheteurs dont la catégorie juridique SIRENE est 71xx (services de l'État : ministères, "
                         "services centraux, déconcentrés et à compétence nationale). Les opérateurs et "
                         "établissements publics sont hors périmètre. Le rattachement à un programme n'existe pas "
                         "dans les DECP : rattachement au ministère acheteur d'après son nom SIRENE."),
           "methode": ("Dernière version de chaque marché ; montant rationalisé quand il existe ; montant d'un marché "
                       "à plusieurs titulaires réparti à parts égales ; montants signalés « aberrant » écartés."),
           "ecartes_montants_aberrants": {"montant_eur": eur(ecartes["montant_aberrant_eur"]), "lignes": ecartes["lignes"]},
           "ensemble": sortie(tous),
           "par_ministere": {m: sortie(g) for m, g in sorted(par_min.items(), key=lambda kv: -kv[1]["total"])}}
    dump(SITE / "beneficiaires" / "marches_etat.json", obj)
    e = obj["ensemble"]
    return {"total_eur": e["total_eur"], "exclus_eur": e["exclus_personnes_physiques_ou_non_identifies"]["montant_eur"],
            "non_verifies_eur": e["autres_non_verifies"]["montant_eur"]}


# --- Fichiers par programme et index -----------------------------------------------------------------------------


def programmes_beneficiaires() -> dict:
    progs, ent = arbre_programmes()
    assoc = associations()
    ops = operateurs()
    vider(SITE / "beneficiaires", "programme_*.json")
    n, total_assoc, exclus_assoc = 0, 0.0, 0.0
    for p in sorted(set(assoc) | set(ops)):
        a = progs.get(p)
        obj = {"millesime": "Associations : crédits 2023 (jaune PLF 2025) ; opérateurs : PLF 2025 ; "
                            f"arbre de référence : {ent['millesime']}",
               "source": " ; ".join([SRC["associations"]["source"], SRC["operateurs"]["source"], SOURCE_API]),
               "programme": p, "libelle": (a or {}).get("nom"), "mission": (a or {}).get("mission"),
               "dans_arbre": a is not None,
               "programme_arbre_eur": eur(a["eur"]) if a else None,
               "programme_eur_sur_100": sur_100(a["eur"], ent["total_eur"]) if a else None,
               "associations": assoc.get(p), "operateurs": ops.get(p)}
        if p in assoc:
            total_assoc += assoc[p]["total_source_eur"]
            exclus_assoc += assoc[p]["exclus_personnes_physiques_ou_non_identifies"]["montant_eur"]
        dump(SITE / "beneficiaires" / f"programme_{p}.json", obj)
        n += 1
    return {"fichiers": n, "associations_total_eur": eur(total_assoc), "associations_exclus_eur": eur(exclus_assoc),
            "programmes_avec_associations": len(assoc), "programmes_avec_operateurs": len(ops)}


def index(stats: dict) -> None:
    fichiers = sorted(f.name for f in (SITE / "beneficiaires").glob("programme_*.json"))
    dump(SITE / "beneficiaires" / "index.json", {
        "millesime": "voir chaque fichier (associations 2023, opérateurs PLF 2025, France 2030 2021-2025, "
                     f"marchés {ANNEE_MARCHES})",
        "source": "pipeline/beneficiaires.py ; " + " ; ".join(s["source"] for s in SRC.values()) + " ; " + SOURCE_API,
        "regle_personnes_physiques": ("Seules les personnes morales (catégorie juridique 2xxx à 9xxx) sont nommées. "
                                      "Entrepreneurs individuels (1000) et lignes sans SIREN valide : montants agrégés."),
        "programmes": [f.removeprefix("programme_").removesuffix(".json") for f in fichiers],
        "fichiers": {"programmes": [f"beneficiaires/{f}" for f in fichiers],
                     "france2030": "beneficiaires/france2030.json", "marches_etat": "beneficiaires/marches_etat.json",
                     "nature": "nature/<programme>.json", "effectifs": "effectifs/<programme>.json"},
        "controle": stats})


def tables() -> dict:
    """Tables plates validees par Frictionless (datapackage.json) : contraintes SIREN et categorie juridique."""
    publies = []
    for f in sorted((SITE / "beneficiaires").glob("programme_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for b in (d.get("associations") or {}).get("top", []):
            publies.append(["associations", f"programme {d['programme']}", b["siren"], b["denomination"],
                            b["categorie_juridique"], b["montant_eur"]])
    f2030 = json.loads((SITE / "beneficiaires" / "france2030.json").read_text(encoding="utf-8"))
    for op, g in [("ensemble", f2030["ensemble"])] + list(f2030["par_operateur"].items()):
        for b in g["top"]:
            publies.append(["france2030", op, b["siren"], b["denomination"], b["categorie_juridique"], b["montant_eur"]])
    marches = json.loads((SITE / "beneficiaires" / "marches_etat.json").read_text(encoding="utf-8"))
    for m, g in [("ensemble", marches["ensemble"])] + list(marches["par_ministere"].items()):
        for b in g["top"]:
            publies.append(["marches_etat", m, b["siren"], b["denomination"], b["categorie_juridique"], b["montant_eur"]])
    with open(SITE / "beneficiaires" / "beneficiaires_publies.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "groupe", "siren", "denomination", "categorie_juridique", "montant_eur"])
        w.writerows(publies)
    lignes = []
    for f in sorted((SITE / "nature").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        lignes += [[d["programme"], c["code"], c["libelle"], c["eur"]] for c in d["categories"]]
    with open(SITE / "nature" / "nature_2024.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["programme", "categorie", "libelle_categorie", "eur"])
        w.writerows(lignes)
    eff = []
    for f in sorted((SITE / "effectifs").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        eff.append([d["programme"], d["etpt"], d["titre2_eur"], d["cout_moyen_par_etpt_eur"]])
    with open(SITE / "effectifs" / "effectifs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["programme", "etpt_lfi_2023", "titre2_execution_2024_eur", "cout_moyen_par_etpt_eur"])
        w.writerows(eff)
    return {"beneficiaires_publies": len(publies), "nature_lignes": len(lignes), "effectifs_lignes": len(eff)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("etapes", nargs="+")
    ap.add_argument("--budget", type=float, default=480, help="duree max des appels API, en secondes")
    ap.add_argument("--max", type=int, default=None, help="ne resoudre que les N premiers SIREN (ordre de priorite)")
    args = ap.parse_args()
    if args.etapes[0] == "resoudre":
        listes = {"associations": sirens_associations, "france2030": sirens_france2030,
                  "acheteurs": sirens_acheteurs, "titulaires": sirens_titulaires}
        for cible in args.etapes[1:]:
            sirens = listes[cible]()[:args.max]
            _, restants = sirene.resoudre(sirens, budget_s=args.budget)
            print(f"{cible} : {len(sirens)} SIREN, {restants} restant(s) a resoudre")
        return
    etapes = args.etapes
    if etapes == ["tout"]:
        etapes = ["nature", "effectifs", "programmes", "france2030", "marches", "tables", "index"]
    stats_path = LAKE / "_cache" / "beneficiaires_stats.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}
    fonctions = {"nature": nature, "effectifs": effectifs, "programmes": programmes_beneficiaires,
                 "france2030": france2030, "marches": marches, "tables": tables}
    for e in etapes:
        if e == "index":
            index(stats)
        else:
            stats[e] = fonctions[e]()
            print(e, json.dumps(stats[e], ensure_ascii=False)[:400])
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
