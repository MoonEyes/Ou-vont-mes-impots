"""Transforme data/raw en fichiers compacts pour le site et en tables validables.

Chaque fichier JSON du site porte `millesime` et `source`.
Sorties :
  site/data/arbre/                 arbre Etat, execution 2024 (vue par defaut) : grand poste > mission > programme > action
  site/data/arbre_lfi2025/         meme arbre, LFI 2025
  site/data/sankey_etat*.json      Etat > grand poste > mission > programme (Md EUR), un fichier par millesime
  site/data/arbre_plf2025_nature/  vue separee "repartition par nature d'apres le PLF 2025" (sous-action, titre, categorie)
  site/data/programmes/<n>.json    idem par programme (PLF 2025) ; site/data/nature_etat.json : titres et categories
  site/data/communes/<dep>.json    {"communes": {code INSEE: [nom, taux TFB %, taux TEOM % ou null]}}
  site/data/cofog.json, administrations.json, recettes.json, arbre_administrations/ (Eurostat)
  site/data/deficit.json           part empruntee : Etat (comptabilite budgetaire) et APU (B9 Eurostat), separees
  site/data/meta.json              sources, dates, conventions (remboursements retires) et totaux de controle
  data/processed/*.csv             tables validees par Frictionless (datapackage.json)
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import arbre

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SITE = ROOT / "site" / "data"
POSTES = json.loads((Path(__file__).parent / "grands_postes.json").read_text(encoding="utf-8"))
NIVEAUX = json.loads((Path(__file__).parent / "niveaux.json").read_text(encoding="utf-8"))
NATURE = json.loads((Path(__file__).parent / "nomenclature_nature.json").read_text(encoding="utf-8"))

COFOG_FR = {
    "GF01": "Services publics generaux", "GF02": "Defense", "GF03": "Ordre et securite publics",
    "GF04": "Affaires economiques", "GF05": "Environnement", "GF06": "Logement et equipements collectifs",
    "GF07": "Sante", "GF08": "Loisirs, culture et culte", "GF09": "Enseignement", "GF10": "Protection sociale",
}


def load(name: str):
    return json.loads((RAW / f"{name}.json").read_text(encoding="utf-8"))


def dump(path: Path, obj, compact: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":") if compact else None,
                      indent=None if compact else 1, sort_keys=not compact)
    path.write_text(text + "\n", encoding="utf-8")


def md(euros: float) -> float:
    return round(euros / 1e9, 4)


# --- Budget de l'Etat -------------------------------------------------------------------------
# Base : jeu "PLF 2026 - Budget vert" (direction du budget), credits budgetaires par action,
# execution 2024 et LFI 2025 retraitees au format PLF 2026. Complements traces :
#   - programmes du budget general absents du budget vert (charge de la dette...) : annexe 1 du PLRG ;
#   - controles des prelevements sur recettes, remboursements et solde : situation mensuelle budgetaire.

MILLESIMES = [
    {"id": "execution_2024", "nom": "Exécution 2024", "annee": "2024", "nature": "execution",
     "col_vert": "execution_2024_cp", "plrg": "plrg_2024_cp", "col_plrg": "Depenses_constatees",
     "source_plrg": "PLRG 2024, annexe 1 (dépenses constatées)",
     "dossier": "arbre", "sankey": "sankey_etat.json", "defaut": True},
    {"id": "lfi_2025", "nom": "LFI 2025", "annee": "2025", "nature": "lfi",
     "col_vert": "lfi_2025_cp_ou_prevision_2025_si_depense_fiscale", "plrg": "plrg_2025_cp", "col_plrg": "LFI",
     "source_plrg": "PLRG 2025, annexe 1 (colonne LFI)",
     "dossier": "arbre_lfi2025", "sankey": "sankey_etat_lfi2025.json", "defaut": False},
]
SOURCE_VERT = ("data.economie.gouv.fr/plf-2026-budget-vert (crédits budgétaires, CP, retraités au format PLF 2026 "
               "par la direction du budget)")


def num(v) -> float:
    """Nombre publie en texte francais ('1 234,5') ou deja numerique."""
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace("\u00a0", "").replace(" ", "").replace(",", "."))


def neutralisation(r: dict) -> str | None:
    """Ligne de retraitement du budget vert a ecarter (voir _neutralisations_budget_vert), ou None."""
    for prefixe in POSTES["_neutralisations_budget_vert"]:
        if prefixe.startswith("_"):
            continue
        if any((r.get(k) or "").startswith(prefixe) for k in ("code_action_si_credit_budgetaire", "code_depense")):
            return prefixe
    return None


def agregats(m: dict) -> dict:
    """Agregats budgetaires de l'Etat pour un millesime, en euros, cle = ligne d'information.

    Execution : situation mensuelle budgetaire au 31 decembre (jeu ODS). LFI : piece jointe
    'textes legislatifs' du meme jeu, ligne 'LFI'.
    """
    out = {}
    if m["nature"] == "execution":
        col = f"31_12_{m['annee']}"
        for r in load("situation_budgetaire"):
            if r.get(col) is not None:
                out[r["ligne_d_information"].strip()] = num(r[col])
    else:
        for r in load("situation_budgetaire_lois"):
            if r["Texte législatif"] == "LFI" and r.get(m["annee"]):
                out[r["Ligne d'information"].strip()] = num(r[m["annee"]])
    return out


PSR_LIGNES = {"PSRCT": "PSR au profit des collectivités territoriales",
              "PSRUE": "PSR au profit de l'Union européenne"}


def lignes_etat(m: dict) -> tuple[list[dict], dict]:
    """Lignes plates du perimetre Etat retenu pour un millesime + ecarts documentes."""
    vert = load("budget_etat_vert")
    speciales = POSTES["_lignes_speciales"]
    complements_ok = POSTES["_complements_plrg"]
    inconnues = sorted({r["mission"] for r in vert} - set(POSTES))
    if inconnues:
        raise SystemExit(f"Missions sans grand poste, a ajouter dans grands_postes.json : {inconnues}")

    libelles_action = {r["code_action_si_credit_budgetaire"]: r["action_si_credit_budgetaire"]
                       for r in vert if r.get("action_si_credit_budgetaire")}
    libelles_prog = {str(r["numero_programme"]): r["programme"] for r in vert
                     if r.get("numero_programme") and r.get("programme")}

    def code_action(r: dict) -> str:
        return r.get("code_action_si_credit_budgetaire") or "-".join((r.get("code_depense") or "").split("-")[:2])

    # Action sans libelle officiel (ligne PLF 2026 sans code action) : libelles de ses lignes, joints.
    sans_libelle = defaultdict(set)
    for r in vert:
        if code_action(r) not in libelles_action and r.get("libelle"):
            sans_libelle[code_action(r)].add(r["libelle"].strip())
    for code, libs in sans_libelle.items():
        libelles_action[code] = " / ".join(sorted(libs))
    lignes = []
    ecarts = {"neutralisations": defaultdict(float), "hors_perimetre": defaultdict(float),
              "remboursements_plrg": defaultdict(float)}
    col = m["col_vert"]
    for r in vert:
        v = r.get(col) or 0.0
        poste = POSTES[r["mission"]]
        neutre = neutralisation(r)
        if neutre:
            ecarts["neutralisations"][neutre] += v
            continue
        if poste == "hors_perimetre":
            ecarts["hors_perimetre"][r["mission"]] += v
            continue
        if poste == "exclu":
            raise SystemExit(f"Mission exclue inattendue dans le budget vert : {r['mission']}")
        base = {"millesime": m["nom"], "grand_poste": poste, "eur": v, "source": "budget vert PLF 2026"}
        if r["mission"] in speciales:
            sp = speciales[r["mission"]]
            prog = sp["programme"]
            lignes.append({**base, "mission": sp["mission"],
                           "programme": str(prog) if prog else None,
                           "libelle_programme": libelles_prog.get(str(prog)) if prog else None,
                           "action": r["mission"] if prog else None,
                           "libelle_action": sp["libelle"] if prog else None})
            continue
        if r.get("numero_programme") is None:
            raise SystemExit(f"Ligne sans programme non prevue : {r['mission']} / {r.get('code_depense')}")
        action = code_action(r)
        lignes.append({**base, "mission": r["mission"], "programme": str(r["numero_programme"]),
                       "libelle_programme": libelles_prog.get(str(r["numero_programme"]), str(r["numero_programme"])),
                       "action": action, "libelle_action": libelles_action.get(action, action)})

    # Programmes du budget general absents du budget vert : montant du PLRG, au niveau programme.
    progs_vert = {str(r["numero_programme"]) for r in vert if r.get("numero_programme")}
    ecarts["plrg_budget_general_hors_rd"] = 0.0
    for r in load(m["plrg"]):
        trouve = re.search(r"(\d{3})\s*$", r["Programme"])
        if not trouve:
            raise SystemExit(f"Programme illisible dans {m['plrg']} : {r['Programme']}")
        prog = trouve.group(1)
        v = num(r[m["col_plrg"]])
        poste = POSTES.get(r["Mission"])
        if poste is None:
            raise SystemExit(f"Mission sans grand poste, a ajouter dans grands_postes.json : {r['Mission']}")
        if poste == "exclu":
            ecarts["remboursements_plrg"][prog] += v
            continue
        ecarts["plrg_budget_general_hors_rd"] += v
        if prog in progs_vert or not v:
            continue
        if prog not in complements_ok:
            raise SystemExit(f"Programme {prog} ({r['Programme']}) absent du budget vert et non prevu dans "
                             f"_complements_plrg : verifier qu'il ne s'agit pas d'un programme fusionne (double compte)")
        lignes.append({"millesime": m["nom"], "grand_poste": poste, "mission": r["Mission"], "programme": prog,
                       "libelle_programme": re.sub(r"\s*-\s*\d{3}\s*$", "", r["Programme"]).strip(),
                       "action": None, "libelle_action": None, "eur": v, "source": m["source_plrg"]})
    return lignes, ecarts


def est_budget_general(ligne: dict) -> bool:
    return (ligne["grand_poste"] != "Prelevements sur recettes"
            and ligne["mission"] not in POSTES["_hors_budget_general_inclus"])


def budget_etat() -> dict:
    controle = {}
    PROCESSED.mkdir(parents=True, exist_ok=True)
    tableau = defaultdict(float)
    for m in MILLESIMES:
        lignes, ecarts = lignes_etat(m)
        ag = agregats(m)
        entete = {"millesime": m["nom"], "source": SOURCE_VERT + " ; complément " + m["source_plrg"],
                  "unite": "milliards d'euros (crédits de paiement)"}
        stats = arbre.ecrire(arbre.construire(lignes, NIVEAUX["niveaux"], "eur"), NIVEAUX["racine"],
                             NIVEAUX["decoupe_apres"], SITE / m["dossier"], entete)
        total = sum(l["eur"] for l in lignes)
        psr = {l["mission"]: 0.0 for l in lignes if l["grand_poste"] == "Prelevements sur recettes"}
        for l in lignes:
            if l["grand_poste"] == "Prelevements sur recettes":
                psr[l["mission"]] += l["eur"]
        sankey_etat(lignes, entete, SITE / m["sankey"])
        for l in lignes:
            tableau[(l["millesime"], l["grand_poste"], l["mission"], l["programme"] or "", l["libelle_programme"] or "",
                     l["action"] or "", l["libelle_action"] or "", l["source"])] += l["eur"]
        rd = {k: ag.get(k, 0.0) for k in ("Remboursements et dégrèvements d'impôts d'Etat",
                                         "Remboursements et dégrèvements d'impôts locaux")}
        controle[m["id"]] = {
            "millesime": m["nom"], "defaut": m["defaut"], "dossier_arbre": m["dossier"],
            "total_md": md(total), "total_hors_psr_md": md(total - sum(psr.values())),
            "prelevements_sur_recettes_md": {k: md(v) for k, v in psr.items()},
            "complements_plrg_md": {l["programme"]: md(l["eur"]) for l in lignes if l["source"] != "budget vert PLF 2026"},
            "lignes_budget_vert_ecartees_md": {k: md(v) for k, v in sorted(ecarts["neutralisations"].items())},
            "hors_perimetre_md": {k: md(v) for k, v in sorted(ecarts["hors_perimetre"].items())},
            "remboursements_et_degrevements": {
                "traitement": "retirés par convention",
                "motif": "Restitutions et dégrèvements d'impôts : de l'argent rendu ou non perçu, pas une dépense "
                         "financée par l'impôt.",
                "montant_md": md(sum(rd.values())),
                "detail_md": {k: md(v) for k, v in rd.items()},
                "source": ("situation mensuelle budgétaire au 31/12 (data.economie.gouv.fr/"
                           "situations-mensuelles-budgetaires-series-longues)" if m["nature"] == "execution" else
                           "situations-mensuelles-budgetaires-series-longues, pièce jointe textes législatifs, ligne LFI"),
                "controle_plrg_md": md(sum(ecarts["remboursements_plrg"].values())),
            },
            "reference_depenses_nettes_budget_general_md": md(ag.get("Total dépenses nettes du budget général", 0)),
            "rapprochement_plrg": {
                "lecture": "Budget general de l'arbre (hors PSR et hors comptes speciaux) face au PLRG (budget general "
                           "hors remboursements et degrevements). L'ecart vient du retraitement au format PLF 2026 "
                           "fait par la direction du budget dans le jeu budget vert.",
                "arbre_budget_general_md": md(sum(l["eur"] for l in lignes if est_budget_general(l))),
                "plrg_budget_general_hors_rd_md": md(ecarts["plrg_budget_general_hors_rd"]),
                "ecart_md": md(ecarts["plrg_budget_general_hors_rd"]
                               - sum(l["eur"] for l in lignes if est_budget_general(l))),
                "source": m["source_plrg"],
            },
            "arbre": stats,
        }

    with (PROCESSED / "budget_etat.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cle", "millesime", "grand_poste", "mission", "programme", "libelle_programme", "action",
                    "libelle_action", "cp_euros", "source"])
        for (mil, poste, mission, prog, lprog, act, lact, src), v in sorted(tableau.items()):
            if v:
                w.writerow([f"{mil}|{mission}|{prog}|{act}|{src}", mil, poste, mission, prog, lprog, act, lact,
                            round(v, 2), src])

    controle["nature_plf2025"] = vue_nature_plf2025()
    return {"etat": controle}


def sankey_etat(lignes: list[dict], entete: dict, chemin: Path) -> None:
    """Sankey Etat > grand poste > mission > programme. Les PSR (sans programme) ont un noeud terminal propre."""
    speciales = POSTES["_lignes_speciales"]
    prog = defaultdict(float)
    for l in lignes:
        if l["programme"]:
            key = (l["grand_poste"], l["mission"], f"g:{l['programme']}", f"{l['libelle_programme']} (P{l['programme']})")
        else:
            lib = next((sp["libelle"] for sp in speciales.values() if isinstance(sp, dict)
                        and sp.get("mission") == l["mission"]), l["mission"])
            key = (l["grand_poste"], l["mission"], f"psr:{l['mission']}", lib)
        prog[key] += l["eur"]
    # Un flux negatif ne se dessine pas : programme a montant net negatif (publie tel quel par la source)
    # retire du sankey et liste a part ; l'arbre, lui, le conserve.
    negatifs = {k: v for k, v in prog.items() if v < 0}
    for k in negatifs:
        del prog[k]

    nodes, index, links = [], {}, defaultdict(float)

    def node(nid: str, label: str, level: int) -> int:
        if nid not in index:
            index[nid] = len(nodes)
            nodes.append({"id": nid, "name": label, "level": level})
        return index[nid]

    root = node("etat", "Budget de l'Etat", 0)
    for (poste, mission, gid, lib), cp in prog.items():
        p = node(f"p:{poste}", poste, 1)
        mm = node(f"m:{mission}", mission, 2)
        g = node(gid, lib, 3)
        links[(root, p)] += cp
        links[(p, mm)] += cp
        links[(mm, g)] += cp
    dump(chemin, {**entete, "total": md(sum(prog.values())),
                  "total_net_arbre": md(sum(prog.values()) + sum(negatifs.values())),
                  "programmes_negatifs_hors_sankey": [{"programme": k[3], "mission": k[1], "md": md(v)}
                                                      for k, v in sorted(negatifs.items())],
                  "nodes": nodes,
                  "links": [{"source": s, "target": t, "value": md(v)} for (s, t), v in sorted(links.items()) if v > 0]})


def vue_nature_plf2025() -> dict:
    """Vue separee 'repartition par nature d'apres le PLF 2025' (sous-action x titre x categorie)."""
    rows = load("budget_etat_plf")
    inconnues = sorted({r["mission"] for r in rows} - set(POSTES))
    if inconnues:
        raise SystemExit(f"Missions sans grand poste, a ajouter dans grands_postes.json : {inconnues}")
    retenues = [r for r in rows if POSTES[r["mission"]] not in ("exclu", "hors_perimetre")]
    exclu = sum(r["cp_plf"] or 0.0 for r in rows if POSTES[r["mission"]] == "exclu")
    budget_detail(retenues)
    vue = NIVEAUX["vue_nature_plf2025"]
    enrichies = [{**r, "grand_poste": POSTES[r["mission"]], "categorie": code_cat(r),
                  "libelle_titre": NATURE["titres"][r["code_titre"]],
                  "libelle_categorie": NATURE["categories"][code_cat(r)]} for r in retenues]
    stats = arbre.ecrire(arbre.construire(enrichies, vue["niveaux"], "cp_plf"), vue["racine"], vue["decoupe_apres"],
                         SITE / "arbre_plf2025_nature", ENTETE_PLF2025)
    return {"total_md": md(sum(r["cp_plf"] or 0.0 for r in retenues)), "exclu_remboursements_md": md(exclu),
            "arbre": stats}


ENTETE_PLF2025 = {
    "millesime": "PLF 2025",
    "source": "data.economie.gouv.fr/plf25-depenses-2025-du-bg-et-des-ba-selon-nomenclatures-destination-et-nature",
    "libelle": "répartition par nature d'après le PLF 2025",
    "avertissement": "Projet de loi de finances, pas le budget voté ni exécuté. Vue séparée : aucun prorata appliqué "
                     "aux montants de l'exécution 2024 ou de la LFI 2025.",
    "unite": "milliards d'euros (crédits de paiement)",
}


def code_cat(r: dict) -> str:
    return str(int(r["categorie"])) if r.get("categorie") is not None else "?"


def budget_detail(rows: list[dict]) -> None:
    """Niveau le plus fin : sous-action x nature, plus un fichier par programme pour le site."""
    titres, cats = NATURE["titres"], NATURE["categories"]
    inconnus = sorted({code_cat(r) for r in rows} - set(cats)) + sorted({r["code_titre"] for r in rows} - set(titres))
    if inconnus:
        raise SystemExit(f"Codes de nature inconnus, a ajouter dans nomenclature_nature.json : {inconnus}")

    detail = defaultdict(float)
    for r in rows:
        key = (int(r["programme"]), r["action"], r["libelle_action"], r["sous_action"], r["libelle_sousaction"],
               r["code_titre"], code_cat(r))
        detail[key] += r["cp_plf"] or 0.0

    with (PROCESSED / "budget_etat_detail.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["programme", "action", "libelle_action", "sous_action", "libelle_sous_action",
                    "titre", "libelle_titre", "categorie", "libelle_categorie", "cp_euros"])
        for (num, act, lact, sact, lsact, t, c), cp in sorted(detail.items()):
            w.writerow([num, act, lact, sact, lsact, t, titres[t], c, cats[c], round(cp, 2)])

    # Un fichier par programme : actions > sous-actions, et repartition par nature.
    par_prog = defaultdict(lambda: {"actions": defaultdict(lambda: {"cp": 0.0, "sous_actions": defaultdict(float)}),
                                    "nature": defaultdict(float)})
    nature_totale = defaultdict(float)
    for (num, act, lact, sact, lsact, t, c), cp in detail.items():
        p = par_prog[num]
        a = p["actions"][(act, lact)]
        a["cp"] += cp
        a["sous_actions"][(sact, lsact)] += cp
        p["nature"][c] += cp
        nature_totale[(t, c)] += cp

    out_dir = SITE / "programmes"
    for old in out_dir.glob("*.json"):
        old.unlink()
    for num, p in par_prog.items():
        dump(out_dir / f"{num}.json", {
            **ENTETE_PLF2025,
            "programme": num,
            "actions": [{"code": code, "nom": nom, "md": md(a["cp"]),
                         "sous_actions": [{"code": sc, "nom": sn, "md": md(v)}
                                          for (sc, sn), v in sorted(a["sous_actions"].items()) if v]}
                        for (code, nom), a in sorted(p["actions"].items()) if a["cp"]],
            "nature": {cats[c]: md(v) for c, v in sorted(p["nature"].items()) if v},
        })

    dump(SITE / "nature_etat.json", {
        **ENTETE_PLF2025,
        "titres": [{"titre": t, "nom": titres[t],
                    "md": md(sum(v for (tt, _), v in nature_totale.items() if tt == t)),
                    "categories": [{"code": c, "nom": cats[c], "md": md(v)}
                                   for (tt, c), v in sorted(nature_totale.items()) if tt == t and v]}
                   for t in sorted({t for t, _ in nature_totale})],
    })


def communes() -> dict:
    rows = load("taux_communes")
    out = defaultdict(dict)
    with (PROCESSED / "communes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code_insee", "nom", "taux_tfb", "taux_teom"])
        for r in sorted(rows, key=lambda r: r["dep"] + r["com"]):
            code = r["dep"] + r["com"]  # 2+3 en metropole, 3+2 en outre-mer : toujours 5 caracteres
            w.writerow([code, r["libcom"], r["taux_global_tfb"], r["taux_plein_teom"]])
            out[r["dep"]][code] = [r["libcom"], r["taux_global_tfb"], r["taux_plein_teom"]]
    # Un fichier par departement : le mobile ne charge que quelques Ko.
    for old in (SITE / "communes").glob("*.json"):
        old.unlink()
    entete = {"millesime": f"Exercice {rows[0]['exercice']}",
              "source": "data.economie.gouv.fr/fiscalite-locale-des-particuliers (DGFiP, REI)",
              "format": "communes : {code INSEE: [nom, taux TFB %, taux TEOM % ou null]}"}
    for dep, communes_dep in out.items():
        dump(SITE / "communes" / f"{dep}.json", {**entete, "communes": communes_dep})
    return {"communes": sum(len(v) for v in out.values()), "departements": len(out), "exercice": rows[0]["exercice"]}


def jsonstat_series(data: dict, dim: str) -> dict:
    """Extrait {categorie: {annee: valeur}} d'un JSON-stat Eurostat ou seules `dim` et `time` varient."""
    ids, sizes = data["id"], data["size"]
    for d, s in zip(ids, sizes):
        if d not in (dim, "time") and s != 1:
            raise SystemExit(f"Dimension inattendue {d} de taille {s}")
    cats = data["dimension"][dim]["category"]["index"]
    years = data["dimension"]["time"]["category"]["index"]
    stride_time = 1
    for d, s in zip(reversed(ids), reversed(sizes)):
        if d == "time":
            break
        stride_time *= s
    stride_dim = 1
    for d, s in zip(reversed(ids), reversed(sizes)):
        if d == dim:
            break
        stride_dim *= s
    out = defaultdict(dict)
    for c, ci in cats.items():
        for y, yi in years.items():
            v = data["value"].get(str(ci * stride_dim + yi * stride_time))
            if v is not None:
                out[c][y] = v
    return out


ADMINS = {"S1311": "Etat", "S1313": "Collectivites locales", "S1314": "Securite sociale", "S13": "Ensemble"}


def jsonstat_records(data: dict) -> list[dict]:
    """JSON-stat Eurostat a N dimensions -> lignes {dim: code, ..., 'libelles': {dim: libelle}, 'valeur': v}."""
    ids, sizes = data["id"], data["size"]
    cats = []
    for d in ids:
        index = data["dimension"][d]["category"]["index"]
        par_pos = sorted(index.items(), key=lambda kv: kv[1])
        cats.append([code for code, _ in par_pos])
    strides = [1] * len(ids)
    for i in range(len(ids) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]
    lignes = []
    for flat, v in data["value"].items():
        flat = int(flat)
        ligne = {}
        for d, cs, st, sz in zip(ids, cats, strides, sizes):
            ligne[d] = cs[(flat // st) % sz]
        ligne["libelles"] = {d: data["dimension"][d]["category"]["label"].get(ligne[d], ligne[d]) for d in ids}
        ligne["valeur"] = v
        lignes.append(ligne)
    return lignes


def administrations() -> dict:
    """Recettes, depenses et solde de chaque administration, par annee (Md EUR)."""
    out = defaultdict(lambda: defaultdict(dict))
    for r in jsonstat_records(load("comptes_administrations")):
        out[r["time"]][ADMINS[r["sector"]]][r["na_item"]] = round(r["valeur"] / 1000, 1)
    dump(SITE / "administrations.json", {"millesime": f"{min(out)}-{max(out)}",
                                         "source": "Eurostat gov_10a_main (comptabilite nationale)",
                                         "unite": "milliards d'euros", "TR": "recettes", "TE": "depenses",
                                         "B9": "solde (negatif = deficit)", "annees": dict(sorted(out.items()))})
    derniere = max(out)
    return {"administrations_derniere_annee": derniere}


def recettes() -> dict:
    """Chaque impot, par administration beneficiaire et par annee (Md EUR)."""
    impots = {}
    for r in jsonstat_records(load("recettes_impots")):
        imp = impots.setdefault(r["na_item"], {"nom": r["libelles"]["na_item"], "par_administration": defaultdict(dict)})
        imp["par_administration"][ADMINS[r["sector"]]][r["time"]] = round(r["valeur"] / 1000, 2)
    annees = sorted({a for i in impots.values() for s in i["par_administration"].values() for a in s})
    dump(SITE / "recettes.json", {"millesime": f"{annees[0]}-{annees[-1]}",
                                  "source": "Eurostat gov_10a_taxag (comptabilite nationale)",
                                  "unite": "milliards d'euros", "annees": annees, "impots": impots})
    tva = impots["D211"]["par_administration"]
    a = max(tva["Ensemble"])
    return {"recettes_annees": f"{annees[0]}-{annees[-1]}",
            "tva_derniere_annee": {k: v.get(a) for k, v in tva.items()}, "tva_annee": a}


def arbre_administrations() -> dict:
    """Arbre Depenses publiques > administration > fonction > sous-fonction (COFOG niveau 2).

    La sous-fonction GF0108 (transferts generaux entre administrations) est retiree :
    c'est de l'argent qu'une administration verse a une autre, qui le depense ensuite.
    """
    lignes = [r for r in jsonstat_records(load("cofog_administrations")) if r["sector"] != "S13"]
    niv2 = [r for r in lignes if len(r["cofog99"]) == 6]
    annees_completes = [a for a in sorted({r["time"] for r in niv2})
                        if {r["sector"] for r in niv2 if r["time"] == a} == {"S1311", "S1313", "S1314"}]
    annee = annees_completes[-1]
    libelle_niv1 = {r["cofog99"]: r["libelles"]["cofog99"] for r in lignes if len(r["cofog99"]) == 4}
    rows = [{"admin": r["sector"], "admin_nom": ADMINS[r["sector"]],
             "f1": r["cofog99"][:4], "f1_nom": libelle_niv1.get(r["cofog99"][:4], r["cofog99"][:4]),
             "f2": r["cofog99"], "f2_nom": r["libelles"]["cofog99"], "eur": r["valeur"] * 1e6}
            for r in niv2 if r["time"] == annee and r["cofog99"] != "GF0108"]
    niveaux = [{"id": "administration", "cle": "admin", "libelle": "admin_nom"},
               {"id": "fonction", "cle": "f1", "libelle": "f1_nom"},
               {"id": "sous_fonction", "cle": "f2", "libelle": "f2_nom"}]
    entete = {"millesime": annee, "source": "Eurostat gov_10a_exp (COFOG niveau 2, S1311/S1313/S1314)",
              "unite": "milliards d'euros"}
    stats = arbre.ecrire(arbre.construire(rows, niveaux, "eur"), f"Depenses publiques {annee}", "aucun",
                         SITE / "arbre_administrations", entete)
    # Controle : somme des administrations hors transferts vs total consolide publie (S13).
    total_s13 = sum(r["valeur"] for r in jsonstat_records(load("cofog_administrations"))
                    if r["sector"] == "S13" and r["cofog99"] == "TOTAL" and r["time"] == annee) / 1000
    somme = sum(r["eur"] for r in rows) / 1e9
    comptes = jsonstat_records(load("comptes_administrations"))
    te = {r["sector"]: r["valeur"] / 1000 for r in comptes if r["na_item"] == "TE" and r["time"] == annee}
    d73 = sum(r["valeur"] for r in comptes if r["na_item"] == "D73PAY" and r["time"] == annee
              and r["sector"] != "S13") / 1000
    # Deux ecarts distincts, jamais confondus :
    # - ecart_consolidation : difference des deux montants publies ci-dessous (somme de l'arbre, GF0108 retiree,
    #   moins total consolide COFOG), calculee sur les valeurs arrondies pour que la soustraction affichee soit exacte ;
    # - ecart_depenses_totales : meme difference sur les depenses totales (TE) de gov_10a_main, transferts compris.
    ecart_consolidation = round(round(somme, 1) - round(total_s13, 1), 1)
    ecart_te = te["S1311"] + te["S1313"] + te["S1314"] - te["S13"]
    dump(SITE / "arbre_administrations" / "methode.json", {
        **entete, "source": "Eurostat gov_10a_exp et gov_10a_main", "annee": annee,
        "lecture": "Chaque administration est montree avec ses depenses propres. Une partie est reversee a une autre "
                   "administration, qui la depense a son tour : la vue nationale utilise donc le total consolide.",
        "somme_administrations_md": round(somme, 1), "total_consolide_md": round(total_s13, 1),
        "transferts_courants_entre_administrations_md": round(d73, 1),
        "ecart_consolidation_md": ecart_consolidation,
        "ecart_depenses_totales_md": round(ecart_te, 1),
        "depenses_totales_ensemble_md": round(te["S13"], 1),
        "ecart_tables_eurostat_md": round(round(te["S13"], 1) - round(total_s13, 1), 1),
        "definitions": {
            "ecart_tables_eurostat_md": "depenses_totales_ensemble_md (TE de l'ensemble des administrations, Eurostat "
                                        "gov_10a_main) - total_consolide_md (total COFOG, Eurostat gov_10a_exp) : deux "
                                        "tables Eurostat distinctes, ecart publie tel quel",
            "ecart_consolidation_md": "somme_administrations_md - total_consolide_md (Eurostat gov_10a_exp) : "
                                      "transferts entre administrations restant dans l'arbre apres retrait de la "
                                      "sous-fonction GF0108",
            "ecart_depenses_totales_md": "depenses totales (TE) de l'Etat, des collectivites locales et de la "
                                         "Securite sociale, moins celles de l'ensemble des administrations "
                                         "(Eurostat gov_10a_main) : tous les transferts entre administrations"}})
    return {"arbre_administrations": {**stats, "annee": annee, "somme_md": round(somme, 1),
                                      "total_consolide_s13_md": round(total_s13, 1),
                                      "ecart_consolidation_md": ecart_consolidation,
                                      "ecart_depenses_totales_md": round(ecart_te, 1),
                                      "transferts_d73_md": round(d73, 1)}}


def cofog() -> dict:
    series = jsonstat_series(load("cofog_france"), "cofog99")
    annees = sorted({y for c in COFOG_FR for y in series.get(c, {})})
    # Derniere annee ou les 10 fonctions sont renseignees.
    annee = max(y for y in annees if all(y in series.get(c, {}) for c in COFOG_FR))
    fonctions = [{"code": c, "nom": n, "md": round(series[c][annee] / 1000, 2)} for c, n in COFOG_FR.items()]
    dump(SITE / "cofog.json", {"millesime": annee, "source": "Eurostat gov_10a_exp (COFOG niveau 1, S13)",
                               "annee": annee, "unite": "milliards d'euros", "fonctions": fonctions,
                               "total": round(sum(f["md"] for f in fonctions), 2)})
    return {"annee_cofog": annee}


def deficit() -> dict:
    """Part empruntee : deux definitions, deux comptabilites, jamais melangees.

    Etat (comptabilite budgetaire, situation mensuelle budgetaire) :
      solde = recettes nettes BG (+ fonds de concours en execution) - depenses nettes BG - PSR
              + solde des comptes speciaux + solde des budgets annexes
      part empruntee = -solde / (depenses nettes BG + PSR)
    Administrations publiques (comptabilite nationale, Eurostat, S13) :
      part empruntee = -B9 / TE
    """
    etat = {}
    for m in MILLESIMES + [{"id": "execution_2025", "nom": "Exécution 2025", "annee": "2025", "nature": "execution"},
                           {"id": "lfi_2024", "nom": "LFI 2024", "annee": "2024", "nature": "lfi"}]:
        ag = agregats(m)
        if "Solde budgétaire" not in ag:
            continue
        r = ag["Total recettes nettes du budget général"]
        fdc = ag.get("Fonds de concours et attribution de produits", 0.0) if m["nature"] == "execution" else 0.0
        d = ag["Total dépenses nettes du budget général"]
        psr = ag["Total prélèvements sur recettes"]
        cs, ba = ag["Solde des comptes spéciaux"], ag["Solde des Budgets annexes"]
        solde = ag["Solde budgétaire"]
        recalcule = r + fdc - d - psr + cs + ba
        if abs(recalcule - solde) > 5e6:
            raise SystemExit(f"Solde budgetaire {m['nom']} non reconstitue : {recalcule} vs {solde}")
        etat[m["nom"]] = {
            "solde_budgetaire_md": md(solde), "recettes_nettes_bg_md": md(r), "fonds_de_concours_md": md(fdc),
            "depenses_nettes_bg_md": md(d), "prelevements_sur_recettes_md": md(psr),
            "solde_comptes_speciaux_md": md(cs), "solde_budgets_annexes_md": md(ba),
            "part_empruntee": round(-solde / (d + psr), 4),
        }
    serie = jsonstat_series(load("deficit_france"), "na_item")["B9"]
    out = {y: round(v / 1000, 1) for y, v in sorted(serie.items())}
    comptes = jsonstat_records(load("comptes_administrations"))
    s13 = defaultdict(dict)
    for r in comptes:
        if r["sector"] == "S13" and r["na_item"] in ("B9", "TE"):
            s13[r["time"]][r["na_item"]] = r["valeur"] / 1000
    apu = {a: {"B9_md": round(v["B9"], 1), "TE_md": round(v["TE"], 1), "part_empruntee": round(-v["B9"] / v["TE"], 4)}
           for a, v in sorted(s13.items()) if "B9" in v and "TE" in v and a >= "2015"}
    dump(SITE / "deficit.json", {
        "millesime": f"Etat : {', '.join(etat)} ; administrations publiques : {min(apu)}-{max(apu)}",
        "source": "Etat : data.economie.gouv.fr/situations-mensuelles-budgetaires-series-longues (DGFiP) ; "
                  "administrations publiques : Eurostat gov_10a_main et gov_10dd_edpt1",
        "unite": "milliards d'euros (negatif = deficit) ; part_empruntee = fraction de 1 euro de depense",
        "avertissement": "Deux comptabilites differentes : ne jamais additionner ni comparer directement les deux parts.",
        "etat": {
            "comptabilite": "budgetaire (encaissements-decaissements de l'annee)",
            "formule_solde": "solde_budgetaire = recettes_nettes_bg + fonds_de_concours (execution seulement) "
                             "- depenses_nettes_bg - prelevements_sur_recettes + solde_comptes_speciaux "
                             "+ solde_budgets_annexes",
            "formule_part_empruntee": "part_empruntee = -solde_budgetaire / (depenses_nettes_bg + prelevements_sur_recettes)",
            "lecture": "Sur 1 euro depense par l'Etat (budget general net des remboursements d'impots d'Etat, plus "
                       "prelevements sur recettes), part financee par l'emprunt cette annee-la.",
            "perimetre": "Les depenses nettes du budget general comptent les degrevements d'impots locaux, retires "
                         "par convention de l'arbre Etat : la part est a appliquer a l'arbre comme ordre de grandeur.",
            "annees": etat,
        },
        "administrations_publiques": {
            "comptabilite": "nationale (SEC 2010, droits constates), secteur S13 consolide",
            "formule_part_empruntee": "part_empruntee = -B9 / TE (B9 = capacite ou besoin de financement, "
                                      "TE = depenses totales des administrations publiques)",
            "annees": apu,
        },
        "solde_public": out,
    })
    return {"deficit_derniere_annee": list(out.items())[-1],
            "part_empruntee_etat": {k: v["part_empruntee"] for k, v in etat.items()},
            "part_empruntee_apu_derniere_annee": [max(apu), apu[max(apu)]["part_empruntee"]]}


def main() -> None:
    controle = {**budget_etat(), **communes(), **cofog(), **deficit(), **administrations(), **recettes(),
                **arbre_administrations()}
    sources = {p.stem.replace(".schema", ""): json.loads(p.read_text(encoding="utf-8"))
               for p in sorted(RAW.glob("*.schema.json"))}
    dump(SITE / "meta.json", {
        "millesime": {"etat_defaut": next(m["nom"] for m in MILLESIMES if m["defaut"]),
                      "etat_disponibles": [m["nom"] for m in MILLESIMES], "nature_etat": "PLF 2025 (vue separee)"},
        "source": "voir 'sources' (une entree par jeu telecharge)",
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {k: {"source": v["source"], "maj_source": v["modified"]} for k, v in sources.items()},
        "controle": controle,
    }, compact=False)
    print(json.dumps(controle, ensure_ascii=False))


if __name__ == "__main__":
    main()
