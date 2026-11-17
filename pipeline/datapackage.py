"""Métadonnées de réutilisation des données publiées dans site/data (docs/REUTILISER.md).

Écrit dans docs/datapackage/ :
  datapackage.json   Frictionless Data Package v2 : une ressource par famille de fichiers du contrat d'interface
                     (motifs de docs/valider_contrat.py), schéma JSON référencé (docs/schemas), licence des données
                     dérivées, sources d'origine et leur licence, millésimes lus dans l'en-tête des fichiers ;
                     les trois tables CSV reprennent les schémas Frictionless du datapackage.json racine
  fichiers.csv       inventaire : chaque fichier versionné de site/data, sa ressource, son schéma, ses URL
  sources.csv        lignée : chaque jeu d'origine lu par une étape du pipeline (pipeline/entrees_lac.json,
                     pipeline/sources.json), éditeur, URL, licence telle que publiée et licence normalisée
  dcat.jsonld        description DCAT-AP (moissonnage data.gouv.fr et portails européens)
  schemaorg.jsonld   description schema.org Dataset (moteurs de recherche de jeux de données)

Le datapackage.json racine reste celui des contrôles Frictionless du pipeline (tables CSV) ; il n'est pas modifié.

Reproductible : même dépôt, même sortie octet pour octet. Fichiers lus via `git ls-files` ; date = dernière collecte
de l'entrepôt (pipeline/reproductible.py) ; sans entrepôt (clone sans data/lake), la lignée et la date reprennent
les fichiers déjà écrits dans docs/datapackage/.

Usage :
    python pipeline/datapackage.py              # écrit docs/datapackage/
    python pipeline/datapackage.py --controle   # code 1 si docs/datapackage/ n'est pas à jour
    python pipeline/datapackage.py --verifier   # validation Frictionless (descripteur et tables CSV locales)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
SORTIE = ROOT / "docs" / "datapackage"
SCHEMAS = ROOT / "docs" / "schemas"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import reproductible  # noqa: E402
import tout  # noqa: E402
import valider_contrat  # noqa: E402

# URL stables : le site publie site/data (JSON seulement) sous /data/ ; les CSV et docs/ sont lus dans le dépôt.
SITE_WEB = "https://mooneyes.github.io/Ou-vont-mes-impots/"
PAGES_DATA = SITE_WEB + "data/"
DEPOT = "https://github.com/MoonEyes/Ou-vont-mes-impots"
BRUT = "https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/"
PROJET = "Projet citoyen Où vont mes impôts"
TITRE = "Où vont mes impôts : données publiques retraitées sur les dépenses et recettes publiques"
DESCRIPTION = (
    "Budget de l'État, Sécurité sociale, collectivités, prélèvements, dette, bénéficiaires nommés (personnes morales), "
    "décisions et contrôle, retraités à partir de jeux publics ouverts (data.economie.gouv.fr, data.gouv.fr, Eurostat, "
    "Insee, DGFiP, OFGL, Assemblée nationale, Sénat, DILA, CNCCFP, HATVP, Cour des comptes). Site citoyen, non "
    "officiel. Chaque fichier JSON porte son millésime et sa source ; un montant écarté est publié avec sa raison. "
    "Précautions de lecture et exemples : docs/REUTILISER.md.")
MOTS_CLES = ["budget de l'État", "finances publiques", "impôts", "dépense publique", "Sécurité sociale",
             "collectivités territoriales", "prélèvements obligatoires", "dette publique", "subventions",
             "marchés publics", "COFOG", "LOLF"]

LICENCES = {
    "etalab-2.0": {"name": "etalab-2.0", "path": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
                   "title": "Licence Ouverte 2.0 (Etalab)"},
    "ODbL-1.0": {"name": "ODbL-1.0", "path": "https://opendatacommons.org/licenses/odbl/1-0/",
                 "title": "Open Database License 1.0"},
    "MIT": {"name": "MIT", "path": DEPOT + "/blob/main/LICENSE", "title": "Licence MIT (code)"},
}
# Libellés des licences d'origine une fois normalisées (sources.csv, colonne licence_normalisee).
LIBELLES_LICENCE = {
    "etalab-2.0": "Licence Ouverte 2.0",
    "etalab-1.0": "Licence Ouverte 1.0",
    "ODbL-1.0": "ODbL 1.0 (partage à l'identique)",
    "CC0-1.0": "CC0 / domaine public",
    "eurostat": "Eurostat, réutilisation libre avec mention de la source",
    "ue-2011-833": "Union européenne, réutilisation autorisée (décision 2011/833/UE)",
    "document-administratif": "document administratif public, réutilisation libre avec mention (CRPA, art. L321-1)",
    "non-precisee": "licence non précisée par l'éditeur",
}
PORTAILS_LIBELLE = {"economie": "data.economie.gouv.fr", "datagouv": "data.gouv.fr", "ofgl": "data.ofgl.fr",
                    "esr": "data.enseignementsup-recherche.gouv.fr", "eurostat": "Eurostat"}


def normaliser_licence(brut: str | None) -> str:
    t = (brut or "").lower()
    if "odbl" in t or "open database" in t:
        return "ODbL-1.0"
    if "eurostat" in t:
        return "eurostat"
    if "2011/833" in t:
        return "ue-2011-833"
    if "cc0" in t or "other-pd" in t or "domaine public" in t:
        return "CC0-1.0"
    if "v1.0" in t and ("ouverte" in t or "open license" in t):
        return "etalab-1.0"
    if any(k in t for k in ("ouverte", "fr-lo", "lov2", "open license", "etalab")):
        return "etalab-2.0"
    if "document" in t and "administratif" in t:
        return "document-administratif"
    return "non-precisee"


# --- Fichiers et familles ----------------------------------------------------------------------------------------

def fichiers_versionnes() -> list[str]:
    """Fichiers suivis de site/data (chemins relatifs à site/data), triés ; parcours du dossier hors dépôt git."""
    r = subprocess.run(["git", "ls-files", "-z", "site/data"], cwd=ROOT, capture_output=True)
    if r.returncode == 0:
        liste = [p.decode("utf-8").removeprefix("site/data/") for p in r.stdout.split(b"\0") if p]
    else:
        liste = [p.relative_to(SITE).as_posix() for p in SITE.rglob("*") if p.is_file()]
    return sorted(p for p in liste if (SITE / p).is_file())


def correspond(chemin: str, motif: str) -> bool:
    """Motif glob segment par segment (« * » ne traverse pas « / », comme glob.glob dans valider_contrat)."""
    a, b = chemin.split("/"), motif.split("/")
    return len(a) == len(b) and all(fnmatchcase(x, y) for x, y in zip(a, b))


def nom_ressource(motif: str, court: bool = True) -> str:
    """« local/decisions/*/[0-9]*.json » -> « local-decisions-x-n » ; « arbre/*.json » -> « arbre » (court)."""
    s = motif.removesuffix(".json").replace("[0-9n]*", "-n").replace("[0-9]*", "-n").replace("*", "-x")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    if court:
        s = re.sub(r"(-x)+$", "", s)
    return s or "racine"


def familles(fichiers: list[str]) -> tuple[list[dict], list[str]]:
    """Une famille par motif du contrat portant au moins un fichier versionné ; fichiers JSON hors motif à part."""
    restants = [f for f in fichiers if f.endswith(".json")]
    out, noms = [], set()
    for schema, motif, _etat in valider_contrat.FICHIERS:
        pris = [f for f in restants if correspond(f, motif)]
        if not pris:
            continue
        restants = [f for f in restants if f not in set(pris)]
        nom = nom_ressource(motif)
        if nom in noms:
            nom = nom_ressource(motif, court=False)
        while nom in noms:
            nom += "-bis"
        noms.add(nom)
        out.append({"nom": nom, "motif": motif, "schema": schema, "fichiers": pris})
    return out, restants


def etape_de(chemin_site: str) -> str | None:
    rel = "site/data/" + chemin_site
    meilleure = None
    for e in tout.ETAPES:
        for s in e.sorties:
            if rel == s or rel.startswith(s + "/"):
                if meilleure is None or len(s) > meilleure[0]:
                    meilleure = (len(s), e.id)
    return meilleure[1] if meilleure else None


def entetes(fichiers: list[str]) -> tuple[list[str], list[tuple[str, int]]]:
    """Millésimes et sources déclarés dans l'en-tête des fichiers (règle commune du contrat)."""
    millesimes, sources = set(), Counter()
    for f in fichiers:
        try:
            doc = json.loads((SITE / f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        m = doc.get("millesime")
        if isinstance(m, str):
            millesimes.add(m)
        elif isinstance(m, dict):
            millesimes.update(str(v) for v in m.values() if isinstance(v, (str, int)))
        if isinstance(doc.get("source"), str):
            sources[doc["source"]] += 1
    return sorted(millesimes), sorted(sources.items(), key=lambda kv: (-kv[1], kv[0]))


# --- Lignée des sources ------------------------------------------------------------------------------------------

COLONNES_SOURCES = ["etape", "source_id", "editeur", "titre", "url", "licence_source", "licence_normalisee"]


def _url_jeu(entree: dict, portails: dict) -> str:
    portail, jeu = entree.get("portail"), entree.get("dataset")
    if portail == "datagouv" and jeu:
        return f"https://www.data.gouv.fr/fr/datasets/{jeu}/"
    if portail and jeu and portails.get(portail.removeprefix("ods_")):
        return f"{portails[portail.removeprefix('ods_')].rstrip('/')}/explore/dataset/{jeu}/"
    if portail and jeu and portails.get(portail):
        return f"{portails[portail].rstrip('/')}/explore/dataset/{jeu}/"
    for f in entree.get("fichiers") or []:
        if isinstance(f, dict) and str(f.get("url", "")).startswith("http"):
            return f["url"]
    u = entree.get("url")
    return u if isinstance(u, str) and u.startswith("http") else ""


def lignee() -> list[dict]:
    """Jeux d'origine par étape. Exige l'entrepôt (data/lake/manifest.json) ; sinon relit docs/datapackage/sources.csv."""
    if not reproductible.MANIFESTE.exists():
        chemin = SORTIE / "sources.csv"
        if chemin.exists():
            with chemin.open(encoding="utf-8", newline="") as fh:
                return list(csv.DictReader(fh))
        return []
    manifeste = json.loads(reproductible.MANIFESTE.read_text(encoding="utf-8"))
    catalogue = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    portails = dict(catalogue.get("portails", {}))
    cat = {s["id"]: s for s in catalogue.get("sources", [])}
    lignes = []
    # étape base : pipeline/sources.json (data/raw, hors entrepôt)
    cfg = json.loads((ROOT / "pipeline" / "sources.json").read_text(encoding="utf-8"))
    for s in cfg.get("ods", []) + cfg.get("ods_pieces_jointes", []):
        lignes.append({"etape": "base", "source_id": s["id"], "editeur": "data.economie.gouv.fr",
                       "titre": s.get("description", ""),
                       "url": f"https://data.economie.gouv.fr/explore/dataset/{s['dataset']}/",
                       "licence_source": "Licence Ouverte 2.0"})
    for s in cfg.get("eurostat", []):
        lignes.append({"etape": "base", "source_id": s["id"], "editeur": "Eurostat",
                       "titre": s.get("description", ""),
                       "url": f"https://ec.europa.eu/eurostat/databrowser/view/{s['dataset']}/default/table",
                       "licence_source": "Eurostat, reutilisation libre avec mention"})
    entrees = json.loads((ROOT / "pipeline" / "entrees_lac.json").read_text(encoding="utf-8"))
    for etape, d in entrees.get("etapes", {}).items():
        for sid in sorted(d.get("sources", {})):
            e = {**cat.get(sid, {}), **(manifeste.get(sid) or {})}
            portail = e.get("portail") or ""
            editeur = e.get("producteur") or PORTAILS_LIBELLE.get(portail) or portail.removeprefix("ods_") or ""
            if not editeur:
                u = _url_jeu(e, portails)
                editeur = re.sub(r"^https?://([^/]+).*$", r"\1", u) if u else (e.get("domaine") or "")
            lignes.append({"etape": etape, "source_id": sid, "editeur": editeur,
                           "titre": (e.get("titre") or "").split(" ; collecte par ")[0],
                           "url": _url_jeu(e, portails), "licence_source": e.get("licence") or ""})
    for ligne in lignes:
        ligne["licence_normalisee"] = normaliser_licence(ligne["licence_source"])
    return sorted(lignes, key=lambda x: (x["etape"], x["source_id"]))


# --- Construction ------------------------------------------------------------------------------------------------

def _schema_desc(nom: str) -> tuple[str, str]:
    try:
        s = json.loads((SCHEMAS / nom).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    titre = str(s.get("title") or "")
    return titre, (titre.split(" : ", 1)[1] if " : " in titre else titre)


def _sources_ressource(lignes: list[dict], declarees: list[tuple[str, int]]) -> list[dict]:
    """Sources groupées par éditeur et licence (détail par jeu : sources.csv) ; à défaut, sources de l'en-tête."""
    groupes = defaultdict(list)
    for li in lignes:
        groupes[(li["editeur"] or "éditeur non renseigné", li["licence_normalisee"])].append(li)
    if len(groupes) > MAX_GROUPES:  # beaucoup d'éditeurs (étape local) : un groupe par licence
        par_licence = defaultdict(list)
        for li in lignes:
            par_licence[li["licence_normalisee"]].append(li)
        return [{"title": f"{len(jeux)} jeux de {len({j['editeur'] for j in jeux})} éditeurs (dont "
                          + ", ".join(sorted({j['editeur'] for j in jeux if j['editeur']})[:5])
                          + f") ; détail par jeu : sources.csv, étape {jeux[0]['etape']}",
                 "licence": LIBELLES_LICENCE[lic], "licence_normalisee": lic}
                for lic, jeux in sorted(par_licence.items())]
    out = []
    for (editeur, lic), jeux in sorted(groupes.items()):
        s = {"title": f"{editeur} ({len(jeux)} jeu{'x' if len(jeux) > 1 else ''})" if len(jeux) > 1
             else f"{editeur} : {jeux[0]['titre']}".rstrip(" :"),
             "licence": LIBELLES_LICENCE[lic], "licence_normalisee": lic}
        if len(jeux) == 1 and jeux[0]["url"]:
            s["path"] = jeux[0]["url"]
        out.append(s)
    if not out:
        out = [{"title": t, "licence": "voir la source citée", "licence_normalisee": "non-precisee"}
               for t, _n in declarees[:10]]
    return out


MAX_GROUPES = 12


def _motif_licence(lignes: list[dict]) -> str:
    odbl = sorted({li["editeur"] for li in lignes if li["licence_normalisee"] == "ODbL-1.0"})
    if odbl:
        return ("ODbL par prudence : l'étape du pipeline qui produit ces fichiers lit au moins un jeu sous ODbL ("
                + ", ".join(odbl[:5]) + (", ..." if len(odbl) > 5 else "") + ") ; la lignée est connue par étape, "
                "pas par fichier.")
    if not lignes:
        return "Licence Ouverte 2.0 ; lignée non relevée pour cette étape : voir le champ source de chaque fichier."
    return "Licence Ouverte 2.0 : aucune source de l'étape n'impose de partage à l'identique ; mentionner les sources."


def _licence_derivee(lignes: list[dict]) -> list[dict]:
    """ODbL dès qu'une source de l'étape est sous ODbL (partage à l'identique) ; sinon Licence Ouverte 2.0."""
    if any(li["licence_normalisee"] == "ODbL-1.0" for li in lignes):
        return [LICENCES["ODbL-1.0"]]
    return [LICENCES["etalab-2.0"]]


def construire() -> dict[str, str]:
    """Contenu de chaque fichier de docs/datapackage/ (nom -> texte)."""
    fichiers = fichiers_versionnes()
    fams, orphelins = familles(fichiers)
    lignes = lignee()
    par_etape = defaultdict(list)
    for li in lignes:
        par_etape[li["etape"]].append(li)
    racine = json.loads((ROOT / "datapackage.json").read_text(encoding="utf-8"))
    tables = {r["path"].removeprefix("site/data/"): r for r in racine.get("resources", [])
              if str(r.get("path", "")).startswith("site/data/")}

    ressources, inventaire, annees = [], [], set()
    for fam in fams:
        etape = etape_de(fam["fichiers"][0])
        millesimes, declarees = entetes(fam["fichiers"])
        annees.update(int(a) for m in millesimes
                      for a in re.findall(r"\b(19[89]\d|20[0-4]\d)\b", m.replace("France 2030", "")))
        lin = par_etape.get(etape or "", [])
        titre_schema, desc = _schema_desc(fam["schema"])
        exemple = fam["fichiers"][0]
        n = len(fam["fichiers"])
        r = {
            "name": fam["nom"],
            "title": desc or fam["motif"],
            "description": (f"{titre_schema}. " if titre_schema else "")
            + (f"Famille de {n} fichiers (motif site/data/{fam['motif']}) ; `path` désigne le premier, liste complète "
               f"dans la ressource `inventaire`." if n > 1 else f"Fichier site/data/{exemple}."),
            "path": PAGES_DATA + exemple,
            "format": "json",
            "mediatype": "application/json",
            "encoding": "utf-8",
            "jsonSchema": BRUT + "docs/schemas/" + fam["schema"],
            "licenses": _licence_derivee(lin),
            "licence_motif": _motif_licence(lin),
            "sources": _sources_ressource(lin, declarees),
            "motif": "site/data/" + fam["motif"],
            "nombre_fichiers": n,
            "etape_pipeline": etape or "non rattachée",
            "millesimes": millesimes[:40],
            "sources_declarees": [t for t, _ in declarees[:10]],
        }
        ressources.append(r)
        for f in fam["fichiers"]:
            inventaire.append((f, fam["nom"], fam["schema"]))
    # fichiers JSON hors motif (ne devrait pas arriver : tests/test_contrat.py l'interdit)
    for f in orphelins:
        inventaire.append((f, "hors-contrat", ""))
    # tables CSV : schémas Frictionless du datapackage.json racine
    for f in fichiers:
        if f.endswith(".json"):
            continue
        t = tables.get(f)
        etape = etape_de(f)
        lin = par_etape.get(etape or "", [])
        nom = (t or {}).get("name") or nom_ressource(f.rsplit(".", 1)[0])
        r = {"name": nom, "type": "table", "title": (t or {}).get("description", f),
             "description": ((t or {}).get("description", "") + " Table CSV (non publiée sur le site, lue dans le dépôt).").strip(),
             "path": BRUT + "site/data/" + f, "format": f.rsplit(".", 1)[-1], "mediatype": "text/csv",
             "encoding": "utf-8", "licenses": _licence_derivee(lin), "licence_motif": _motif_licence(lin),
             "sources": _sources_ressource(lin, []),
             "etape_pipeline": etape or "non rattachée"}
        if t and t.get("schema"):
            r["schema"] = t["schema"]
        if not r["sources"]:
            r["sources"] = [{"title": "voir site/data/" + f.rsplit("/", 1)[0] + "/ (fichiers JSON de la même étape)",
                             "licence": "voir la source citée", "licence_normalisee": "non-precisee"}]
        ressources.append(r)
        inventaire.append((f, nom, ""))

    # inventaire et lignée : ressources tabulaires locales (chemins relatifs au descripteur)
    ressources.append({
        "name": "inventaire", "type": "table", "title": "Inventaire des fichiers de site/data",
        "description": "Chaque fichier versionné de site/data : ressource (famille), schéma du contrat, URL de "
                       "téléchargement (site pour les JSON, dépôt pour les CSV).",
        "path": "fichiers.csv", "format": "csv", "mediatype": "text/csv", "encoding": "utf-8",
        "licenses": [LICENCES["etalab-2.0"]],
        "sources": [{"title": PROJET, "path": DEPOT}],
        "schema": {"fields": [
            {"name": "chemin", "type": "string", "constraints": {"required": True, "unique": True}},
            {"name": "ressource", "type": "string", "constraints": {"required": True}},
            {"name": "schema", "type": "string"},
            {"name": "url", "type": "string", "constraints": {"required": True}}],
            "primaryKey": ["chemin"]}})
    ressources.append({
        "name": "sources", "type": "table", "title": "Lignée : jeux d'origine par étape du pipeline",
        "description": "Jeux publics lus par chaque étape (pipeline/entrees_lac.json et pipeline/sources.json), avec "
                       "l'éditeur, l'URL, la licence telle que publiée et sa forme normalisée.",
        "path": "sources.csv", "format": "csv", "mediatype": "text/csv", "encoding": "utf-8",
        "licenses": [LICENCES["etalab-2.0"]],
        "sources": [{"title": PROJET, "path": DEPOT}],
        "schema": {"fields": [{"name": c, "type": "string"} for c in COLONNES_SOURCES],
                   "primaryKey": ["etape", "source_id"]}})

    date = _date()
    version = _version_contrat()
    toutes = sorted({(li["editeur"], li["licence_normalisee"]) for li in lignes})
    editeurs = defaultdict(set)
    for ed, lic in toutes:
        editeurs[ed or "éditeur non renseigné"].add(lic)
    package = {
        "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
        "name": "ou-vont-mes-impots",
        "id": DEPOT,
        "title": TITRE,
        "description": DESCRIPTION,
        "homepage": SITE_WEB,
        "version": version,
        "created": date,
        "keywords": MOTS_CLES,
        "image": SITE_WEB + "favicon.svg",
        "licenses": [LICENCES["etalab-2.0"], LICENCES["ODbL-1.0"]],
        "licence_donnees": "Licence Ouverte 2.0, sauf ressources dont une source est sous ODbL (licence ODbL indiquée "
                           "dans la ressource). Mention de chaque source d'origine requise (champ sources).",
        "licence_code": LICENCES["MIT"],
        "contributors": [{"title": PROJET, "path": DEPOT, "roles": ["creator", "publisher", "maintainer"]}],
        "sources": [{"title": ed, "licence": " ; ".join(LIBELLES_LICENCE[x] for x in sorted(lics))}
                    for ed, lics in sorted(editeurs.items())],
        "couverture_temporelle": f"{min(annees)}/{max(annees)}" if annees else None,
        "signaler_une_erreur": DEPOT + "/issues",
        "resources": ressources,
    }
    if package["couverture_temporelle"] is None:
        del package["couverture_temporelle"]

    out = {
        "datapackage.json": json.dumps(package, ensure_ascii=False, indent=1) + "\n",
        "fichiers.csv": _csv(["chemin", "ressource", "schema", "url"],
                             [[f, nom, sch, (PAGES_DATA if f.endswith(".json") else BRUT + "site/data/") + f]
                              for f, nom, sch in sorted(inventaire)]),
        "sources.csv": _csv(COLONNES_SOURCES, [[li[c] for c in COLONNES_SOURCES] for li in lignes]),
        "dcat.jsonld": json.dumps(_dcat(package, date), ensure_ascii=False, indent=1) + "\n",
        "schemaorg.jsonld": json.dumps(_schemaorg(package, lignes, date), ensure_ascii=False, indent=1) + "\n",
    }
    return out


def _csv(entete: list[str], lignes: list[list[str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(entete)
    w.writerows(lignes)
    return buf.getvalue()


def _date() -> str:
    """Date de la dernière collecte ; sans entrepôt ni SOURCE_DATE_EPOCH, celle déjà écrite (sinon maintenant)."""
    if reproductible.MANIFESTE.exists() or os.environ.get("SOURCE_DATE_EPOCH"):
        return reproductible.date_sources(avec_heure=True)
    try:
        return json.loads((SORTIE / "datapackage.json").read_text(encoding="utf-8"))["created"]
    except (OSError, ValueError, KeyError):
        return reproductible.date_sources(avec_heure=True)


def _version_contrat() -> str:
    texte = (ROOT / "docs" / "contrat_interface.md").read_text(encoding="utf-8")
    m = re.search(r"Version du contrat : \*\*([0-9.]+)\*\*", texte)
    v = m.group(1) if m else "0"
    return v if v.count(".") >= 2 else v + ".0"


def _distribution(r: dict) -> dict:
    url = r["path"] if r["path"].startswith("http") else BRUT + "docs/datapackage/" + r["path"]
    d = {"@type": "dcat:Distribution", "dct:title": r["title"], "dct:description": r["description"],
         "dcat:accessURL": {"@id": url}, "dcat:downloadURL": {"@id": url},
         "dct:format": r["format"].upper(), "dcat:mediaType": r["mediatype"],
         "dct:license": {"@id": r["licenses"][0]["path"]}}
    if r.get("jsonSchema"):
        d["dct:conformsTo"] = {"@id": r["jsonSchema"]}
    return d


def _dcat(p: dict, date: str) -> dict:
    """DCAT-AP 2 (JSON-LD) : le jeu, une distribution par ressource, le descripteur Frictionless en distribution."""
    sources = sorted({s["path"] for r in p["resources"] for s in r.get("sources", []) if s.get("path", "").startswith("http")})
    dp = BRUT + "docs/datapackage/datapackage.json"
    return {
        "@context": {"dcat": "http://www.w3.org/ns/dcat#", "dct": "http://purl.org/dc/terms/",
                     "foaf": "http://xmlns.com/foaf/0.1/", "vcard": "http://www.w3.org/2006/vcard/ns#",
                     "xsd": "http://www.w3.org/2001/XMLSchema#"},
        "@id": DEPOT + "#jeu",
        "@type": "dcat:Dataset",
        "dct:identifier": DEPOT,
        "dct:title": p["title"],
        "dct:description": p["description"],
        "dcat:keyword": p["keywords"],
        "dct:language": {"@id": "http://publications.europa.eu/resource/authority/language/FRA"},
        "dct:spatial": {"@id": "http://publications.europa.eu/resource/authority/country/FRA"},
        "dct:accrualPeriodicity": {"@id": "http://publications.europa.eu/resource/authority/frequency/WEEKLY"},
        "dct:modified": {"@value": date, "@type": "xsd:dateTime"},
        "dct:temporal": ({"@type": "dct:PeriodOfTime",
                          "dcat:startDate": {"@value": p["couverture_temporelle"].split("/")[0], "@type": "xsd:gYear"},
                          "dcat:endDate": {"@value": p["couverture_temporelle"].split("/")[1], "@type": "xsd:gYear"}}
                         if p.get("couverture_temporelle") else None),
        "dcat:landingPage": {"@id": SITE_WEB},
        "dct:publisher": {"@type": "foaf:Agent", "foaf:name": PROJET, "foaf:homepage": {"@id": DEPOT}},
        "dcat:contactPoint": {"@type": "vcard:Kind", "vcard:fn": PROJET,
                              "vcard:hasURL": {"@id": p["signaler_une_erreur"]}},
        "dct:license": {"@id": LICENCES["etalab-2.0"]["path"]},
        "dct:rights": p["licence_donnees"],
        "dct:conformsTo": {"@id": "https://datapackage.org/standard/data-package/"},
        "dct:source": [{"@id": u} for u in sources],
        "dcat:distribution": [{"@type": "dcat:Distribution", "dct:title": "Descripteur Frictionless Data Package v2",
                               "dcat:accessURL": {"@id": dp}, "dcat:downloadURL": {"@id": dp},
                               "dct:format": "JSON", "dcat:mediaType": "application/json",
                               "dct:license": {"@id": LICENCES["etalab-2.0"]["path"]}}]
        + [_distribution(r) for r in p["resources"]],
    }


def _schemaorg(p: dict, lignes: list[dict], date: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "@id": DEPOT + "#jeu",
        "name": p["title"],
        "description": p["description"],
        "url": SITE_WEB,
        "sameAs": DEPOT,
        "identifier": DEPOT,
        "keywords": p["keywords"],
        "inLanguage": "fr",
        "isAccessibleForFree": True,
        "license": LICENCES["etalab-2.0"]["path"],
        "creator": {"@type": "Organization", "name": PROJET, "url": DEPOT},
        "publisher": {"@type": "Organization", "name": PROJET, "url": DEPOT},
        "version": p["version"],
        "dateModified": date,
        "temporalCoverage": p.get("couverture_temporelle"),
        "spatialCoverage": {"@type": "Place", "name": "France"},
        "isBasedOn": sorted({li["url"] for li in lignes if li["url"].startswith("http")})[:200],
        "distribution": [{"@type": "DataDownload", "name": r["title"],
                          "encodingFormat": r["mediatype"],
                          "contentUrl": r["path"] if r["path"].startswith("http") else BRUT + "docs/datapackage/" + r["path"]}
                         for r in p["resources"]],
    }


# --- Commandes ---------------------------------------------------------------------------------------------------

def ecrire(contenus: dict[str, str]) -> None:
    SORTIE.mkdir(parents=True, exist_ok=True)
    for nom, texte in contenus.items():
        (SORTIE / nom).write_text(texte, encoding="utf-8")


def differences(contenus: dict[str, str]) -> list[str]:
    out = []
    for nom, texte in contenus.items():
        p = SORTIE / nom
        if not p.exists() or p.read_text(encoding="utf-8") != texte:
            out.append(nom)
    return out


def verifier() -> int:
    """Validation Frictionless : descripteur (profil v2) puis tables CSV lues localement (sans réseau)."""
    try:
        from frictionless import Package, Resource, Schema
    except ImportError:
        print("frictionless absent : pip install frictionless (requirements.txt)")
        return 0
    desc = json.loads((SORTIE / "datapackage.json").read_text(encoding="utf-8"))
    erreurs = []
    try:
        rapport = Package.validate_descriptor(desc)
        erreurs += [f"descripteur : {m[0]}" for m in rapport.flatten(["message"])]
    except Exception as exc:  # noqa: BLE001 (versions de frictionless)
        erreurs.append(f"descripteur : {exc}")
    for r in desc["resources"]:
        if r.get("type") != "table" or not r.get("schema"):
            continue
        local = (SORTIE / r["path"]) if not r["path"].startswith("http") else ROOT / r["path"].removeprefix(BRUT)
        res = Resource(path=local.name, basepath=str(local.parent), schema=Schema.from_descriptor(r["schema"]))
        rep = res.validate()
        if not rep.valid:
            erreurs += [f"{r['name']} : {m[0]}" for m in rep.flatten(["message"])[:5]]
    for e in erreurs:
        print("ERREUR", e)
    print(f"Frictionless : {len(desc['resources'])} ressources, {len(erreurs)} erreur(s)")
    return 1 if erreurs else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--controle", action="store_true", help="code 1 si docs/datapackage/ n'est pas à jour")
    ap.add_argument("--verifier", action="store_true", help="validation Frictionless du descripteur et des CSV")
    a = ap.parse_args(argv)
    if a.verifier:
        return verifier()
    contenus = construire()
    if a.controle:
        diff = differences(contenus)
        print("à jour" if not diff else "à régénérer : " + ", ".join(diff))
        return 1 if diff else 0
    ecrire(contenus)
    dp = json.loads(contenus["datapackage.json"])
    print(f"docs/datapackage/ : {len(dp['resources'])} ressources, "
          f"{contenus['fichiers.csv'].count(chr(10)) - 1} fichiers inventoriés, "
          f"{contenus['sources.csv'].count(chr(10)) - 1} jeux d'origine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
