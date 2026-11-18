"""Séries longues des impôts locaux par commune : taux et produits de 2010 à la dernière année publiée (REI, DGFiP).

Taxe foncière sur les propriétés bâties (part de la commune, de l'intercommunalité et, jusqu'en 2020, du
département), taxe foncière sur les propriétés non bâties, taxe d'habitation (toutes résidences jusqu'en 2022, puis
résidences secondaires et logements vacants), cotisation foncière des entreprises (commune et intercommunalité) et
taxe d'enlèvement des ordures ménagères : taux nets appliqués et produits, tels que publiés chaque année par la
DGFiP dans le fichier de recensement des éléments d'imposition à la fiscalité directe locale (REI).

Complète site/data/local/taux/ (pipeline/local.py) sans le dupliquer : pour un département et un exercice déjà
publiés dans local/taux/<dep>.json, les taux qui y figurent (colonne équivalente déclarée dans index.json) ne sont
pas repris ici (null) ; les produits, la cotisation foncière des entreprises, la part départementale et l'ancienne
taxe d'habitation n'y figurent pas et sont publiés pour tous les exercices.

Commandes :
    python pipeline/fiscalite_locale_series.py collecter [--annees 2010 2011 ...]
        (réseau ; fichiers REI lourds, de 60 à 130 Mo : traités année par année, seules les colonnes utiles sont
        gardées dans data/lake/fiscalite_locale_series/extraits/rei_<annee>.csv.gz, le brut est supprimé aussitôt ;
        un refus 401/403/429/451 est noté, jamais contourné)
    python pipeline/fiscalite_locale_series.py produire [--sortie DOSSIER]   (sans réseau)

Sorties (site/data/fiscalite_locale_series/, contrat docs/contrat_interface.md, schémas
docs/schemas/fiscalite_locale_series_*.schema.json) :
    index.json, taux/<dep>.json, produits/<dep>.json

Sorties reproductibles : aucune heure de passage, ordres explicites (départements, communes, années triés).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "fiscalite_locale_series"
BRUTS = LAKE / "fiscalite_locale_series_rei"
EXTRAITS = LAKE / "extraits"
SORTIE = ROOT / "site" / "data" / "fiscalite_locale_series"
LOCAL_TAUX = ROOT / "site" / "data" / "local" / "taux"

ANNEE_DEBUT = 2010
DATASET = "impots-locaux-fichier-de-recensement-des-elements-dimposition-a-la-fiscalite-dir"
API = f"https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/{DATASET}"
PAGE = f"https://data.economie.gouv.fr/explore/dataset/{DATASET}/"
SOURCE = ("DGFiP, fichier de recensement des éléments d'imposition à la fiscalité directe locale (REI), un fichier par "
          "année, data.economie.gouv.fr : " + PAGE)
LICENCE = "Licence Ouverte 2.0"
MAX_OCTETS = 1_000_000
UA = {"User-Agent": "ou-vont-mes-impots/pipeline (projet citoyen open source)"}

# Colonnes gardées dans les extraits : identité de la commune + taux (x2) et montants (x3) des taxes suivies.
IDENTITE = ["DEP", "DIR", "COM", "IDCOM", "LIBCOM", "SIREPCI", "OPTEPCI"]
GARDER = re.compile(r"^(?:[EBHP][1-4][23]|F[1-8][23]|F13)(?:VOTE|THS|LV|_[123][UZ]?(?:VOTE)?)?$", re.I)

# (clé publiée, libellé, codes REI par ordre de priorité, exercices concernés ou None)
TAUX = [
    ("tfb_commune", "Taxe foncière sur les propriétés bâties, taux de la commune", ["E12"]),
    ("tfb_intercommunalite", "Taxe foncière sur les propriétés bâties, taux de l'intercommunalité", ["E32"]),
    ("tfb_departement", "Taxe foncière sur les propriétés bâties, taux du département (jusqu'en 2020)", ["E42"]),
    ("tfnb_commune", "Taxe foncière sur les propriétés non bâties, taux de la commune", ["B12"]),
    ("tfnb_intercommunalite", "Taxe foncière sur les propriétés non bâties, taux de l'intercommunalité", ["B32"]),
    ("th_commune", "Taxe d'habitation, taux de la commune", ["H12"]),
    ("th_intercommunalite", "Taxe d'habitation, taux de l'intercommunalité", ["H32"]),
    ("cfe_commune", "Cotisation foncière des entreprises, taux de la commune", ["P12"]),
    ("cfe_intercommunalite_additionnelle", "Cotisation foncière des entreprises, taux additionnel de "
     "l'intercommunalité (fiscalité additionnelle, ou hors zone d'activité)", ["P32_1"]),
    ("cfe_intercommunalite_unique", "Cotisation foncière des entreprises, taux de l'intercommunalité à fiscalité "
     "professionnelle unique (ou en zone d'activité)", ["P32_2"]),
    ("teom_taux_plein", "Taxe d'enlèvement des ordures ménagères, taux plein", ["F22"]),
]
PRODUITS = [
    ("tfb_commune", "Taxe foncière sur les propriétés bâties, produit de la commune", ["E13"]),
    ("tfb_intercommunalite", "Taxe foncière sur les propriétés bâties, produit de l'intercommunalité", ["E33"]),
    ("tfb_departement", "Taxe foncière sur les propriétés bâties, produit du département (jusqu'en 2020)", ["E43"]),
    ("tfnb_commune", "Taxe foncière sur les propriétés non bâties, produit de la commune", ["B13"]),
    ("tfnb_intercommunalite", "Taxe foncière sur les propriétés non bâties, produit de l'intercommunalité", ["B33"]),
    ("th_commune", "Taxe d'habitation, produit de la commune", ["H13", "H13THS"]),
    ("th_intercommunalite", "Taxe d'habitation, produit de l'intercommunalité", ["H33", "H33THS"]),
    ("cfe_commune", "Cotisation foncière des entreprises, produit de la commune", ["P13"]),
    ("cfe_intercommunalite_additionnelle", "Cotisation foncière des entreprises, produit additionnel de "
     "l'intercommunalité", ["P33_1"]),
    ("cfe_intercommunalite_unique", "Cotisation foncière des entreprises, produit de l'intercommunalité à "
     "fiscalité professionnelle unique (ou en zone d'activité)", ["P33_2"]),
    ("teom", "Taxe d'enlèvement des ordures ménagères, produit", ["F13", "F23"]),
]


# --- Collecte ---------------------------------------------------------------------------------------------------------


def url_annee(annee: int) -> str:
    """URL de la pièce jointe REI d'une année (nommage publié : 2010 sans notice, 2025 sans « _ » final)."""
    if annee == 2010:
        return f"{API}/attachments/rei_2010_fichier_trace_zip"
    if annee == 2025:
        return f"{API}/attachments/rei_2025_fichier_notice_tracezip"
    return f"{API}/attachments/rei_{annee}_fichier_notice_trace_zip"


def annees_publiees() -> list[int]:
    """Années REI publiées (liste des pièces jointes), à partir de ANNEE_DEBUT."""
    import requests
    for i in range(5):
        try:
            r = requests.get(f"{API}/attachments", headers=UA, timeout=(20, 120))
            if r.status_code in (401, 403, 429, 451):
                raise SystemExit(f"liste des pièces jointes : accès refusé (HTTP {r.status_code}), aucun contournement")
            r.raise_for_status()
            ans = set()
            for a in r.json().get("attachments", []):
                m = re.search(r"rei_(\d{4})_", a.get("href", "") + "_")
                if m and int(m.group(1)) >= ANNEE_DEBUT:
                    ans.add(int(m.group(1)))
            return sorted(ans)
        except (OSError, ValueError) as e:  # reprise réseau
            print(f"  liste des pièces jointes : {type(e).__name__}, reprise", file=sys.stderr)
            time.sleep(10 * (i + 1))
    raise SystemExit("liste des pièces jointes REI : réseau indisponible après 5 essais")


def telecharger(url: str, dest: Path, essais: int = 8) -> str:
    """Téléchargement en flux, reprenable (Range). Retourne « ok » ou la raison de l'échec."""
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    derniere = ""
    for i in range(essais):
        deja = tmp.stat().st_size if tmp.exists() else 0
        h = dict(UA, **({"Range": f"bytes={deja}-"} if deja else {}))
        try:
            with requests.get(url, headers=h, timeout=(20, 300), stream=True) as r:
                if r.status_code in (401, 403, 429, 451):
                    return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
                if r.status_code == 416:
                    break
                r.raise_for_status()
                mode = "ab" if deja and r.status_code == 206 else "wb"
                with open(tmp, mode) as f:
                    for bloc in r.iter_content(1 << 20):
                        f.write(bloc)
            break
        except (OSError, ValueError) as e:  # requests.RequestException hérite d'OSError
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(6 * (i + 1))
    else:
        return f"échec après {essais} essais : {derniere}"
    with open(tmp, "rb") as f:
        if f.read(4) != b"PK\x03\x04":
            tmp.unlink()
            return "contenu inattendu (pas une archive zip) : aucun contournement"
    tmp.replace(dest)
    return "ok"


NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NSR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch) - 64
    return n - 1


def lignes_xlsx(chemin: Path):
    """Lignes (listes de chaînes) de la plus grande feuille d'un classeur xlsx, lues en flux (mémoire bornée)."""
    from lxml import etree
    with zipfile.ZipFile(chemin) as z:
        partages = []
        if "xl/sharedStrings.xml" in z.namelist():
            with z.open("xl/sharedStrings.xml") as f:
                for _, el in etree.iterparse(f, tag=NS + "si"):
                    partages.append(_xesc("".join(el.itertext())))
                    el.clear()
        feuilles = [i for i in z.infolist() if i.filename.startswith("xl/worksheets/sheet")]
        feuille = max(feuilles, key=lambda i: i.file_size).filename
        with z.open(feuille) as f:
            for _, el in etree.iterparse(f, tag=NS + "row"):
                cellules = {}
                for c in el.iterchildren(NS + "c"):
                    v = c.find(NS + "v")
                    if v is None:
                        t = c.find(NS + "is")
                        if t is not None:
                            cellules[_col(c.get("r"))] = _xesc("".join(t.itertext()))
                        continue
                    cellules[_col(c.get("r"))] = partages[int(v.text)] if c.get("t") == "s" else _xesc(v.text or "")
                el.clear()
                while el.getprevious() is not None:
                    del el.getparent()[0]
                if cellules:
                    n = max(cellules) + 1
                    yield [cellules.get(i, "") for i in range(n)]


def codes_trace(z: zipfile.ZipFile) -> list[str]:
    """Codes des variables (ordre des numéros) lus dans le fichier de tracé xlsx d'une archive REI."""
    traces = [i for i in z.infolist() if re.search(r"trace.*\.xlsx$", i.filename.rsplit("/", 1)[-1], re.I)]
    if not traces:
        return []
    tmp = BRUTS / "_trace.xlsx"
    tmp.write_bytes(z.read(traces[0]))
    try:
        lignes = list(lignes_xlsx(tmp))
    finally:
        tmp.unlink()
    tete = [x.upper() for x in lignes[0]]
    i_num = next(i for i, h in enumerate(tete) if h.startswith("NUM"))
    i_nom = next(i for i, h in enumerate(tete) if h.startswith("NOM"))
    vars_ = sorted((int(float(r[i_num])), r[i_nom].strip().upper()) for r in lignes[1:]
                   if len(r) > i_nom and r[i_num].strip() and r[i_nom].strip())
    return [nom for _, nom in vars_]


XESC = re.compile(r"_x([0-9A-Fa-f]{4})_")


def _xesc(t: str) -> str:
    """Décodage des échappements OOXML (« _x0020_ » = espace) présents dans certains millésimes."""
    return XESC.sub(lambda m: chr(int(m.group(1), 16)), t) if "_x" in t else t


def lignes_csv(z: zipfile.ZipFile, nom: str):
    with z.open(nom) as f:
        brut = f.read(200_000)
    try:
        brut.decode("utf-8")
        enc = "utf-8-sig"
    except UnicodeDecodeError:
        enc = "latin-1"
    sep = ";" if brut.split(b"\n", 1)[0].count(b";") > brut.split(b"\n", 1)[0].count(b",") else ","
    with z.open(nom) as f:
        yield from csv.reader(io.TextIOWrapper(f, encoding=enc, newline=""), delimiter=sep)


def extraire(annee: int, archive: Path) -> dict:
    """Garde les colonnes utiles du fichier REI d'une année dans extraits/rei_<annee>.csv.gz (trié par commune)."""
    with zipfile.ZipFile(archive) as z:
        donnees = [i for i in z.infolist() if re.search(r"\.(xlsx|csv|txt)$", i.filename, re.I)
                   and not re.search(r"trace|notice|variable", i.filename.rsplit("/", 1)[-1], re.I)]
        if not donnees:
            raise SystemExit(f"{annee} : aucun fichier de données dans l'archive")
        donnee = max(donnees, key=lambda i: i.file_size)
        if donnee.filename.lower().endswith(".xlsx"):
            tmp = BRUTS / f"REI_{annee}.xlsx"
            with z.open(donnee) as src, open(tmp, "wb") as dst:
                while bloc := src.read(1 << 20):
                    dst.write(bloc)
            lignes = lignes_xlsx(tmp)
        else:
            tmp = None
            lignes = lignes_csv(z, donnee.filename)
        entete = [h.strip().upper() for h in next(lignes)]
        if not {"DEP", "COM", "E12"} <= set(entete):
            # Fichiers « REI_COMPLET » (2019 et suivants en xlsx) : en-têtes en libellés longs ; les codes des
            # variables sont pris dans le fichier de tracé joint, dans l'ordre des numéros de variable.
            noms_trace = codes_trace(z)
            if len(noms_trace) != len(entete):
                raise SystemExit(f"{annee} : en-tête REI non reconnu ({len(entete)} colonnes, tracé : "
                                 f"{len(noms_trace)} variables)")
            entete = noms_trace
        garde = [i for i, h in enumerate(entete) if h in IDENTITE or GARDER.match(h)]
        noms = [entete[i] for i in garde]
        sortie = []
        for ligne in lignes:
            if not any(x.strip() for x in ligne):
                continue
            sortie.append([(ligne[i].strip() if i < len(ligne) else "") for i in garde])
        if tmp is not None:
            tmp.unlink()
    cle = [noms.index(c) for c in ("DEP", "DIR", "COM") if c in noms]
    sortie.sort(key=lambda r: tuple(r[i] for i in cle))
    EXTRAITS.mkdir(parents=True, exist_ok=True)
    dest = EXTRAITS / f"rei_{annee}.csv.gz"
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(noms)
    w.writerows(sortie)
    with open(dest.with_suffix(".part"), "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as g:
        g.write(buf.getvalue().encode("utf-8"))
    dest.with_suffix(".part").replace(dest)
    return {"fichier_source": donnee.filename, "lignes": len(sortie), "colonnes": len(noms)}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while bloc := f.read(1 << 20):
            h.update(bloc)
    return h.hexdigest()


def collecter(annees: list[int] | None = None, forcer: bool = False) -> dict:
    from datetime import datetime, timezone
    annees = annees or annees_publiees()
    etat = {}
    for annee in annees:
        dest = EXTRAITS / f"rei_{annee}.csv.gz"
        meta_p = EXTRAITS / f"rei_{annee}.meta.json"
        if dest.exists() and meta_p.exists() and not forcer:
            etat[annee] = "présent"
            print(f"{annee}: présent")
            continue
        archive = BRUTS / f"REI-{annee}.zip"
        url = url_annee(annee)
        res = "ok" if archive.exists() else telecharger(url, archive)
        if res != "ok":
            etat[annee] = res
            print(f"{annee}: {res}", file=sys.stderr)
            continue
        meta = {"annee": annee, "url": url, "page": PAGE, "licence": LICENCE, "octets_brut": archive.stat().st_size,
                "sha256_brut": sha256(archive),
                "collecte_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        try:
            meta.update(extraire(annee, archive))
        except (zipfile.BadZipFile, StopIteration) as e:
            archive.unlink(missing_ok=True)
            etat[annee] = f"archive illisible ({type(e).__name__}) : supprimée, relancer la collecte"
            print(f"{annee}: {etat[annee]}", file=sys.stderr)
            continue
        archive.unlink()  # brut supprimé après traitement (fichiers lourds)
        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        etat[annee] = f"ok ({meta['lignes']} communes, {meta['colonnes']} colonnes)"
        print(f"{annee}: {etat[annee]}", flush=True)
    return etat


# --- Production -------------------------------------------------------------------------------------------------------

# Colonnes de site/data/local/taux/<dep>.json équivalentes à nos taux (même taxe, même niveau de collectivité).
EQUIVALENTS_LOCAL = {"tfb_commune": "tfb_commune", "tfb_intercommunalite": "tfb_intercommunalite",
                     "tfnb_commune": "tfnb_commune", "tfnb_intercommunalite": "tfnb_intercommunalite",
                     "th_commune": "thrs_commune", "th_intercommunalite": "thrs_intercommunalite",
                     "teom_taux_plein": "teom_taux_plein"}

NOTES = [
    ("taux_nets", "Taux nets appliqués sur le territoire de la commune, tels que publiés par la DGFiP (colonnes « taux "
     "net » du REI). Ils peuvent différer du taux voté par l'assemblée pendant une période d'harmonisation des taux "
     "d'une intercommunalité ou en zone d'activité."),
    ("produits", "Produits : montants réels (montants nets avant 2020 selon la notice) émis au titre de l'année sur le "
     "territoire de la commune, en euros courants, sans correction de l'inflation. Ils ne comprennent ni les frais de "
     "gestion perçus par l'État, ni les compensations d'exonération, ni les dégrèvements pris en charge par l'État."),
    ("foncier_bati_2021", "Depuis 2021, le département ne vote plus de taux de taxe foncière sur les propriétés bâties : "
     "sa part a été transférée aux communes pour compenser la suppression de la taxe d'habitation sur les résidences "
     "principales. Le taux communal de 2021 additionne donc l'ancien taux communal et l'ancien taux départemental ; "
     "la série « tfb_departement » s'arrête en 2020."),
    ("taxe_habitation", "Taxe d'habitation : jusqu'en 2020, toutes les résidences (principales et secondaires) ; en 2021 "
     "et 2022, la part sur les résidences principales encore payée par une partie des foyers est perçue par l'État et "
     "non par la commune ; depuis 2023, seules subsistent la taxe sur les résidences secondaires et autres locaux "
     "meublés non affectés à l'habitation principale et, là où elle est instituée, la taxe sur les logements vacants "
     "(non comprise ici). Le produit change donc de périmètre en 2021 et en 2023."),
    ("cfe", "Cotisation foncière des entreprises : créée en 2010 (remplacement de la taxe professionnelle). Dans une "
     "intercommunalité à fiscalité professionnelle unique, la commune ne vote plus de taux : seul celui de "
     "l'intercommunalité s'applique. En fiscalité additionnelle, les deux s'additionnent."),
    ("teom", "Taxe d'enlèvement des ordures ménagères : instituée par la commune, l'intercommunalité ou un syndicat ; le "
     "produit est celui émis sur le territoire de la commune, quel que soit l'organisme qui le perçoit. Taux plein "
     "uniquement (des taux réduits existent par zone). Le produit est le montant réel total quand le fichier le publie, "
     "sinon la somme des montants des zones de taux (taux plein et taux réduits)."),
    ("communes", "Une commune est suivie par son code officiel géographique tel que publié chaque année : une commune "
     "nouvelle apparaît sous son code à partir de sa création, les communes fusionnées s'arrêtent l'année précédente. "
     "Aucun raccordement entre anciens et nouveaux codes n'est fait ici."),
    ("zero_null", "0 : valeur publiée égale à zéro (taxe non instituée ou aucun taux voté à ce niveau). null : cellule "
     "vide dans le fichier, exercice hors de la période de la taxe, ou taux déjà publié dans local/taux (voir "
     "« complement_local_taux »). Une variable absente d'une commune vaut 0 ou null sur toute la période."),
]


# Règle n°0 : existant recherché avant d'écrire ce module (relevé du 18/11/2026).
RECHERCHE_PUBLIQUE = {
    "date": "2026-11-18",
    "trouvailles": [
        {"nom": "DGFiP, fichiers REI annuels (1982 à 2025)", "url": PAGE, "licence": LICENCE,
         "mise_a_jour": "pièce jointe 2025 publiée en 2025", "verdict": "réutilisable tel quel",
         "usage": "source unique de ce module, colonnes relevées sans transformation"},
        {"nom": "DGFiP, fiscalite-locale-des-particuliers et fiscalite-locale-des-entreprises (data.economie.gouv.fr)",
         "url": "https://data.economie.gouv.fr/explore/dataset/fiscalite-locale-des-particuliers/",
         "licence": LICENCE, "mise_a_jour": "exercices 2021 à 2025", "verdict": "à adapter",
         "usage": "taux uniquement, depuis 2021 : déjà repris par pipeline/local.py (local/taux), non dupliqué ici"},
        {"nom": "OFGL, jeu « rei » (REI 2024 et 2025 en format long, lignes à 0 retirées)",
         "url": "https://data.ofgl.fr/explore/dataset/rei/", "licence": "Licence Ouverte 2.0 (OFGL)",
         "mise_a_jour": "2026-05-29", "verdict": "inspiration seulement",
         "usage": "deux exercices ; présentation des destinataires de chaque taxe reprise dans les notes"},
        {"nom": "Dépôts publics GitHub lisant le REI (AbstractsMachine/qipu-pipeline, Vcitordosgor/labuse, "
                "vigie-civique/vigie-commune, maximedns5/Impots)", "url": "https://github.com/search?q=E12VOTE&type=code",
         "licence": "non vérifiée (accès à l'API GitHub refusé pour cette session)",
         "mise_a_jour": "non vérifiée", "verdict": "inspiration seulement",
         "usage": "lecture d'un exercice récent ; aucune série 2010 et plus publiée en données ouvertes"},
    ],
}


def _num(v: str):
    v = (v or "").strip().replace(",", ".").replace(" ", "")
    if v == "":
        return None
    try:
        x = float(v)
    except ValueError:
        return None
    return None if x != x else x


def insee(r: dict) -> str:
    idc = (r.get("IDCOM") or "").strip()
    if len(idc) == 5:
        return idc
    dep, com = r["DEP"].strip(), r["COM"].strip()
    if dep.isdigit() and len(dep) < 2:  # certains millésimes publient le département sans zéro initial (« 2 »)
        dep = dep.zfill(2)
    return dep + com.zfill(5 - len(dep))


def departement(code: str) -> str:
    return code[:3] if code.startswith("97") else code[:2]


def lire_extrait(annee: int):
    with gzip.open(EXTRAITS / f"rei_{annee}.csv.gz", "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):  # extraits 2019-2020 : échappements OOXML gardés tels quels
            yield {k: _xesc(v or "") for k, v in r.items()}


def _valeur(r: dict, codes: list[str], somme_teom: bool = False):
    for c in codes:
        if c in r:
            if c == "F23" and somme_teom:  # pas de montant total publié : somme des zones de taux
                vals = [_num(r[k]) for k in sorted(r) if re.fullmatch(r"F[2-8]3", k)]
                vals = [v for v in vals if v is not None]
                return sum(vals) if vals else None
            return _num(r[c])
    return None


def code_utilise(entete: list[str], codes: list[str]) -> str | None:
    for c in codes:
        if c in entete:
            return c
    return None


def lire_local_taux() -> dict[str, dict]:
    """Exercices et colonnes déjà publiés par pipeline/local.py, par département (site/data/local/taux/<dep>.json)."""
    sortie = {}
    for p in sorted(LOCAL_TAUX.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sortie[p.stem] = {"exercices": [int(e) for e in d.get("exercices", [])], "colonnes": d.get("colonnes", []),
                          "communes": d.get("communes", {})}
    return sortie


def ecrire(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(texte.encode("utf-8")) + 1
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse 1 Mo ({n} octets) : découper")
    tmp = path.with_suffix(".part")
    tmp.write_text(texte + "\n", encoding="utf-8")
    tmp.replace(path)
    return n


def _arrondi(v, taux: bool):
    if v is None:
        return None
    if taux:
        r = round(v, 3)
        return int(r) if r == int(r) else r
    return int(round(v))


PART_OCTETS = 850_000  # au-delà, le département est publié en plusieurs parties (communes dans l'ordre des codes)


def decouper(communes: dict) -> list[dict]:
    """Parties successives (ordre des codes) dont le JSON reste sous PART_OCTETS."""
    parts, courant, taille = [], {}, 2000
    for code, c in communes.items():
        t = len(json.dumps({code: c}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if courant and taille + t > PART_OCTETS:
            parts.append(courant)
            courant, taille = {}, 2000
        courant[code] = c
        taille += t
    if courant:
        parts.append(courant)
    return parts


def produire(sortie: Path = SORTIE) -> dict:
    annees = sorted(int(m.group(1)) for p in EXTRAITS.glob("rei_*.csv.gz")
                    if (m := re.fullmatch(r"rei_(\d{4})\.csv\.gz", p.name)) and int(m.group(1)) >= ANNEE_DEBUT)
    if not annees:
        raise SystemExit("extraits REI absents de data/lake/fiscalite_locale_series/extraits : lancer collecter")
    attendues = list(range(annees[0], annees[-1] + 1))
    if annees != attendues:
        manque = sorted(set(attendues) - set(annees))
        raise SystemExit(f"extraits REI absents pour {manque} : lancer collecter")
    metas = {a: json.loads((EXTRAITS / f"rei_{a}.meta.json").read_text(encoding="utf-8")) for a in annees}
    local = lire_local_taux()
    n_a = len(annees)
    rang = {a: i for i, a in enumerate(annees)}
    # communes[dep][insee] = {"nom", "annee_nom", "taux": {var: [..]}, "produits": {var: [..]}}
    communes: dict[str, dict[str, dict]] = {}
    codes_rei = {"taux": {k: {} for k, _, _ in TAUX}, "produits": {k: {} for k, _, _ in PRODUITS}}
    totaux = {k: [None] * n_a for k, _, _ in PRODUITS}
    nb_communes = {}
    for a in annees:
        lignes = lire_extrait(a)
        n = 0
        entete = None
        for r in lignes:
            if entete is None:
                entete = list(r)
                somme_teom = "F13" not in entete
                for groupe, defs in (("taux", TAUX), ("produits", PRODUITS)):
                    for k, _, codes in defs:
                        c = code_utilise(entete, codes)
                        if c == "F23" and somme_teom:
                            c = "+".join(x for x in sorted(entete) if re.fullmatch(r"F[2-8]3", x))
                        codes_rei[groupe][k][str(a)] = c
            code = insee(r)
            dep = departement(code)
            c = communes.setdefault(dep, {}).setdefault(code, {"nom": None, "taux": {}, "produits": {}})
            c["nom"] = " ".join((r.get("LIBCOM") or "").split()) or c["nom"]
            for groupe, defs in (("taux", TAUX), ("produits", PRODUITS)):
                for k, _, codes in defs:
                    v = _arrondi(_valeur(r, codes, somme_teom), groupe == "taux")
                    if v is None:
                        continue
                    c[groupe].setdefault(k, [None] * n_a)[rang[a]] = v
                    if groupe == "produits":
                        totaux[k][rang[a]] = (totaux[k][rang[a]] or 0) + v
            n += 1
        nb_communes[str(a)] = n

    # Taux déjà publiés par local/taux : retirés (null) pour les exercices concernés ; écarts mesurés, non tranchés.
    ecarts = {"comparaisons": 0, "egales": 0, "differentes": 0, "absentes_de_local": 0}
    complement = {}
    for dep, cs in communes.items():
        lt = local.get(dep)
        if not lt:
            continue
        ex = [e for e in lt["exercices"] if e in rang]
        complement[dep] = ex
        idx_local = {k: lt["colonnes"].index(v) for k, v in EQUIVALENTS_LOCAL.items() if v in lt["colonnes"]}
        for code, c in cs.items():
            lc = lt["communes"].get(code, {})
            for k, j in idx_local.items():
                serie = c["taux"].get(k)
                if serie is None:
                    continue
                for e in ex:
                    v = serie[rang[e]]
                    if v is None:
                        continue
                    lv = (lc.get(str(e)) or [None] * (j + 1))[j]
                    if lv is None:  # absent de local/taux : gardé ici (pas de doublon)
                        ecarts["absentes_de_local"] += 1
                        continue
                    ecarts["comparaisons"] += 1
                    ecarts["egales" if abs(lv - v) < 0.0005 else "differentes"] += 1
                    serie[rang[e]] = None

    millesime = f"Exercices {annees[0]} à {annees[-1]}"
    deps = sorted(communes)
    fichiers = []
    tailles = {}
    for dep in deps:
        cs = communes[dep]
        entree = {"departement": dep, "communes": len(cs)}
        for groupe, defs, unite in (("taux", TAUX, "%"), ("produits", PRODUITS, "euros")):
            sortie_c = {}
            for code in sorted(cs):
                # série omise si elle ne contient que 0 ou null sur toute la période (taxe non instituée à ce niveau)
                series = {k: cs[code][groupe][k] for k, _, _ in defs
                          if k in cs[code][groupe] and any(v not in (None, 0) for v in cs[code][groupe][k])}
                sortie_c[code] = {"nom": cs[code]["nom"], "series": series}
            parts = decouper(sortie_c)
            entree[groupe] = []
            for i, part in enumerate(parts, 1):
                nom = f"{groupe}/{dep}.json" if len(parts) == 1 else f"{groupe}/{dep}-{i}.json"
                obj = {"millesime": millesime, "source": SOURCE, "licence": LICENCE, "departement": dep,
                       "unite": unite, "annees": annees, "variables": [k for k, _, _ in defs], "communes": part}
                if groupe == "taux" and dep in complement:  # local/taux/<dep>.json publié
                    obj["complement_local_taux"] = {
                        "fichier": f"local/taux/{dep}.json", "exercices": complement.get(dep, []),
                        "colonnes": dict(EQUIVALENTS_LOCAL) if complement.get(dep) else {}}
                tailles[nom] = ecrire(sortie / nom, obj)
                codes = list(part)
                entree[groupe].append({"fichier": nom, "premiere_commune": codes[0], "derniere_commune": codes[-1]})
        fichiers.append(entree)

    index = {
        "millesime": millesime, "source": SOURCE, "licence": LICENCE,
        "producteur": "Direction générale des finances publiques (DGFiP)",
        "perimetre": "Toutes les communes de France (métropole et départements d'outre-mer) présentes dans le REI de "
                     "chaque année ; taux et produits des taxes directes locales votées par la commune, son "
                     "intercommunalité à fiscalité propre et, jusqu'en 2020, le département pour le foncier bâti.",
        "methode": "Colonnes du REI relevées telles quelles, une année après l'autre (codes par variable et par année "
                   "dans « codes_rei ») ; taux arrondis à 3 décimales, produits à l'euro ; aucune estimation.",
        "annees": annees,
        "variables": {
            "taux": [{"cle": k, "libelle": lib, "unite": "%"} for k, lib, _ in TAUX],
            "produits": [{"cle": k, "libelle": lib, "unite": "euros"} for k, lib, _ in PRODUITS],
        },
        "codes_rei": codes_rei,
        "notes": [{"cle": k, "texte": t} for k, t in NOTES],
        "complement_local_taux": {
            "principe": "Pour les exercices déjà publiés dans local/taux/<dep>.json (taux votés, pipeline/local.py), "
                        "les taux équivalents que local/taux publie (valeur non nulle) valent null ici : lire la colonne "
                        "indiquée dans ce fichier. Un taux absent de local/taux reste publié ici. Les produits et les "
                        "autres taux sont publiés pour tous les exercices.",
            "colonnes": EQUIVALENTS_LOCAL,
            "exercices_par_departement": {d: complement[d] for d in sorted(complement)},
            "ecarts_taux_nets_votes": {**ecarts, "lecture": "Comparaison, sur ces exercices, de nos taux nets (REI) "
                                       "et des taux votés de local/taux : nombre de valeurs égales et différentes, "
                                       "montré sans trancher."},
        },
        "communes_par_annee": nb_communes,
        "totaux_nationaux_produits": {
            "unite": "euros",
            "lecture": "Somme, sur toutes les communes du fichier de l'année, des produits de chaque taxe et de chaque "
                       "niveau (même source, même année) ; les niveaux ne sont pas additionnés entre eux.",
            "series": totaux},
        "sources_par_annee": [{"annee": a, "url": metas[a]["url"], "fichier": metas[a].get("fichier_source"),
                               "octets": metas[a].get("octets_brut"), "sha256": metas[a].get("sha256_brut")}
                              for a in annees],
        "departements": fichiers,
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    ecrire(sortie / "index.json", index)
    plus_gros = max(tailles.items(), key=lambda kv: kv[1])
    print(f"fiscalite_locale_series : {len(deps)} départements, {sum(len(c) for c in communes.values())} communes, "
          f"{annees[0]}-{annees[-1]} ; plus gros fichier {plus_gros[0]} ({plus_gros[1]} octets) ; écarts {ecarts}")
    return index


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="produire", choices=["collecter", "produire", "tout"])
    ap.add_argument("--annees", nargs="*", type=int, help="années REI à collecter (défaut : toutes depuis 2010)")
    ap.add_argument("--forcer", action="store_true", help="recollecter les années déjà extraites")
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter(a.annees, a.forcer)
    if a.etape in ("produire", "tout"):
        produire(a.sortie)


if __name__ == "__main__":
    main()
