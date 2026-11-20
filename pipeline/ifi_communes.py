"""Impôt sur la fortune immobilière (IFI) par commune : nombre de foyers redevables, patrimoine moyen et impôt moyen,
tels que publiés par la DGFiP pour les villes de plus de 20 000 habitants ayant plus de 50 redevables.

Entrées (réseau, `collecter`) : classeurs annuels de la fiche data.gouv.fr « Impôt de solidarité sur la fortune -
Impôt sur la fortune immobilière par collectivité territoriale » (DGFiP, Licence Ouverte), années 2018 à 2025, liste
des ressources lue par l'API data.gouv.fr, fichiers contrôlés par collecte/integrite.py
  -> data/lake/ifi_communes/ifi_<année>.<xlsx|xls>, ressources.json.
Lecture seule : site/data/local/geo/<dep>.json (communes en vigueur).
Sorties (site/data/ifi_communes/) :
  index.json      années, définitions, seuils de diffusion, rupture ISF/IFI, couverture, sources
  communes.json   par commune : [redevables, patrimoine moyen, impôt moyen] par année ; Paris : par arrondissement

Règles : moyennes publiées par la DGFiP, reprises telles quelles (arrondies à l'euro ; le classeur 2020 les écrit en
millions et en milliers d'euros : converties en euros, unité lue dans l'en-tête) ; aucune somme ni moyenne recalculée
par le site (Paris : arrondissements montrés un par un, jamais additionnés) ; commune absente du classeur d'une année :
sous les seuils de diffusion (20 000 habitants, 50 redevables), rien n'est publié, jamais 0. Monaco et les codes hors du
code officiel géographique sont comptés à part.

Commandes :
  python pipeline/ifi_communes.py collecter
  python pipeline/ifi_communes.py produire [--sortie DOSSIER]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "ifi_communes"
GEO = ROOT / "site" / "data" / "local" / "geo"
OUT = ROOT / "site" / "data" / "ifi_communes"
FICHE = "https://www.data.gouv.fr/datasets/5369965ea3a729239d204992"
API = "https://www.data.gouv.fr/api/1/datasets/5369965ea3a729239d204992/"
ANNEES = [str(a) for a in range(2018, 2026)]
COLONNES = ["redevables", "patrimoine_moyen_eur", "impot_moyen_eur"]
PLM = {"751": "75056", "6938": "69123", "132": "13055"}
SEUIL = ("Publié par la DGFiP pour les villes de plus de 20 000 habitants ayant plus de 50 foyers redevables (secret "
         "fiscal) : une commune absente une année est sous ces seuils, rien n'est publié pour elle.")
RUPTURE = ("L'impôt sur la fortune immobilière (IFI) remplace l'impôt de solidarité sur la fortune (ISF) depuis 2018 : "
           "seul le patrimoine immobilier est taxé ; les séries ISF (2002-2017) ne se comparent pas à l'IFI.")
DEFINITIONS = {
    "redevables": "Nombre de foyers redevables de l'IFI domiciliés dans la commune",
    "patrimoine_moyen_eur": "Patrimoine immobilier net taxable moyen des redevables, en euros, publié par la DGFiP",
    "impot_moyen_eur": "Impôt moyen payé par redevable, en euros, publié par la DGFiP",
}
RECHERCHE_PUBLIQUE = [
    {"trouvaille": "Fiche data.gouv.fr 5369965ea3a729239d204992 (classeurs annuels DGFiP)", "classement": "réutilisable tel quel",
     "licence": "Licence Ouverte", "dernier_commit": "2026-04-14"},
    {"trouvaille": "fgeerolf.com, pages IFI par commune", "classement": "inspiration seulement",
     "licence": "non précisée", "dernier_commit": None, "note": "contrôle des chiffres"},
]


def collecter(forcer: bool = False) -> dict:
    import fetch
    import local
    LAKE.mkdir(parents=True, exist_ok=True)
    d = local.http_get(API, essais=8, timeout=60).json()
    ressources = {}
    for r in d["resources"]:
        m = re.search(r"IFI (\d{4})", r["title"])
        if m and m.group(1) in ANNEES:
            ressources[m.group(1)] = {"url": r["url"], "titre": r["title"], "mise_a_jour": (r.get("last_modified") or "")[:10]}
    etat = {}
    for a, r in sorted(ressources.items()):
        ext = Path(r["url"].split("?")[0]).suffix.lower()
        dest = LAKE / f"ifi_{a}{ext}"
        if dest.exists() and not forcer:
            etat[a] = "présent"
            continue
        try:
            rep = local.http_get(r["url"], essais=6, timeout=120)
        except (RuntimeError, SystemExit) as exc:
            etat[a] = f"inaccessible : {exc}"[:200]
            continue
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(rep.content)
        fetch.remplacer_si_valide(tmp, dest, nom=dest.name, octets_attendus=fetch.octets_annonces(rep))
        etat[a] = "ok"
    (LAKE / "ressources.json").write_text(json.dumps({"licence": d.get("license"), "mise_a_jour_fiche": (d.get("last_modified") or "")[:10],
                                                      "ressources": ressources, "collecte_le": time.strftime("%Y-%m-%d", time.gmtime())},
                                                     ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    return etat


def lignes_classeur(p: Path) -> list[tuple]:
    """Lignes du premier onglet qui porte l'en-tête « Code commune » (l'onglet « Avertissement » est ignoré)."""
    if p.suffix == ".xls":
        import pandas as pd
        feuilles = [[tuple(None if (isinstance(v, float) and v != v) else v for v in row)
                     for row in df.itertuples(index=False)] for df in pd.read_excel(p, header=None, sheet_name=None, dtype=object).values()]
    else:
        import openpyxl
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        feuilles = [list(ws.iter_rows(values_only=True)) for ws in wb.worksheets]
    for rows in feuilles:
        for i, row in enumerate(rows[:10]):
            if any(isinstance(v, str) and "code" in v.lower() and "commune" in v.lower() for v in row):
                return rows[i:]
    raise SystemExit(f"{p.name} : en-tête « Code commune » introuvable")


def facteur(entete: str) -> int:
    e = (entete or "").lower()
    return 1_000_000 if "million" in e else 1_000 if "millier" in e else 1


def code_insee(v) -> str | None:
    s = re.sub(r"\D", "", str(v if v is not None else ""))
    if isinstance(v, (int, float)) and len(s) < 5:
        s = s.zfill(5)
    return s if len(s) == 5 else (str(v).replace(" ", "") if re.fullmatch(r"2[AB] ?\d{3}", str(v or "")) else None)


def produire(sortie: Path = OUT) -> dict:
    communes = {}
    for f in sorted(GEO.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for code, c in d["communes"].items():
            communes[code] = c["nom"]
    out, arrondissements, hors, annees = {}, {}, {}, []
    for a in ANNEES:
        p = next((q for q in (LAKE / f"ifi_{a}.xlsx", LAKE / f"ifi_{a}.xls") if q.exists()), None)
        if not p:
            continue
        rows = lignes_classeur(p)
        entete = [str(x or "") for x in rows[0]]
        i_code = next(i for i, x in enumerate(entete) if "code" in x.lower())
        i_nom = i_code + 1
        i_red = next(i for i, x in enumerate(entete) if "redevable" in x.lower())
        i_pat = next(i for i, x in enumerate(entete) if "patrimoine" in x.lower())
        i_imp = next(i for i, x in enumerate(entete) if "impôt" in x.lower() or "impot" in x.lower())
        f_pat, f_imp = facteur(entete[i_pat]), facteur(entete[i_imp])
        annees.append(a)
        for row in rows[1:]:
            if len(row) <= i_imp or row[i_red] is None:
                continue
            code = code_insee(row[i_code])
            try:
                v = [int(row[i_red]), int(round(float(row[i_pat]) * f_pat)), int(round(float(row[i_imp]) * f_imp))]
            except (TypeError, ValueError):
                continue
            mere = next((m for pre, m in PLM.items() if code and code.startswith(pre) and code != m), None)
            if mere:
                x = arrondissements.setdefault(mere, {}).setdefault(code, {"annees": {}})
                x["nom_source"] = str(row[i_nom] or "").strip()   # libellé de la dernière année lue
                x["annees"][a] = v
            elif code in communes:
                out.setdefault(code, {})[a] = v
            else:
                hors.setdefault(a, []).append(code or str(row[i_code]))
    if not annees:
        raise SystemExit("aucun classeur : lancer `python pipeline/ifi_communes.py collecter`")
    try:
        meta = json.loads((LAKE / "ressources.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    date = meta.get("collecte_le") or date_sources()
    entete_doc = {"millesime": f"IFI {annees[0]} à {annees[-1]} (classeurs DGFiP) ; collecte du {date}",
                  "source": f"DGFiP, « Impôt sur la fortune immobilière par collectivité territoriale », data.gouv.fr : {FICHE}"}
    ifi = {code: {"nom": communes[code], "annees": dict(sorted(v.items()))} for code, v in sorted(out.items())}
    for mere, arr in sorted(arrondissements.items()):
        ifi.setdefault(mere, {"nom": communes.get(mere, mere), "annees": {}})["arrondissements"] = {
            c: {"nom_source": x["nom_source"], "annees": dict(sorted(x["annees"].items()))} for c, x in sorted(arr.items())}
    sortie.mkdir(parents=True, exist_ok=True)
    doc = {**entete_doc, "colonnes": COLONNES, "communes": ifi}
    (sortie / "communes.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    sources = [{"annee": a, "url": r["url"], "titre": r["titre"], "mise_a_jour_source": r["mise_a_jour"]}
               for a, r in sorted((meta.get("ressources") or {}).items())]
    index = {**entete_doc, "presentation": ("Combien de foyers de la commune paient l'impôt sur la fortune immobilière, "
                                            "leur patrimoine moyen et leur impôt moyen, tels que publiés par la DGFiP."),
             "annees": annees, "colonnes": COLONNES, "definitions": DEFINITIONS, "seuil": SEUIL, "rupture": RUPTURE,
             "conversion": "Classeur 2020 : patrimoine en millions et impôt en milliers d'euros dans la source, convertis en euros.",
             "licence": meta.get("licence") or "Licence Ouverte", "fiche": FICHE, "sources": sources,
             "couverture": {"communes_publiees": len(ifi), "par_annee": {a: sum(1 for v in out.values() if a in v) for a in annees},
                            "hors_cog": {a: sorted(set(h)) for a, h in sorted(hors.items())}},
             "recherche_publique": RECHERCHE_PUBLIQUE, "fichiers": {"communes": "communes.json"}}
    (sortie / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return index


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true")
    ap.add_argument("--sortie", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        print(json.dumps(collecter(a.forcer), ensure_ascii=False))
    if a.etape in ("produire", "tout"):
        print(json.dumps(produire(a.sortie)["couverture"], ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
