"""Associations : crédits de l'État par association et par programme (jaunes 2012 à 2025), fonds et fondations (RNF),
réserve parlementaire (Assemblée nationale 2013-2016, Sénat 2014-2017).

Entrées (entrepôt brut, déclarées dans collecte/catalogue.json, `python collecte/collecte.py <id>`) :
  data/lake/associations/assoc_jaune_plf<AAAA>[.csv|/]   jaunes « Effort financier de l'État en faveur des associations »
                                                         PLF 2012 à 2024 (colonnes différentes chaque année)
  data/lake/beneficiaires/benef_associations_plf25.parquet  jaune PLF 2025 (lu par pipeline/beneficiaires.py)
  data/lake/associations/assoc_rnf_fonds_fondations/      Registre national des fonds et fondations (csv zippé)
  data/lake/_restreint/associations/assoc_reserve_{an,senat}/  réserve parlementaire (adresses : zone restreinte)
  data/lake/associations/assoc_banatic_siren_insee/, assoc_departements.json   appariement des communes
  data/lake/_cache/local/sirene_unite_legale.parquet      stock SIRENE des unités légales (lecture seule ; partagé
                                                          avec pipeline/local.py, téléchargé par lui)
Caches (data/lake/_cache/associations/, non versionnés) : extrait SIRENE (catégorie juridique ; dénomination et RNA
des personnes morales seulement), prénoms fréquents, appariements par l'API Recherche d'entreprises.

Commandes :
  python pipeline/associations.py sirene                 # extrait SIRENE des SIREN lus (sans réseau si le stock est là)
  python pipeline/associations.py apparier [--budget 600]   # réseau, reprenable : API pour les bénéficiaires restants
  python pipeline/associations.py produire [--sortie DOSSIER]   # sans réseau, reproductible
  python pipeline/associations.py tout                   # sirene + produire

Sorties (site/data/associations/, < 5 Mo par fichier, `millesime` et `source` partout) :
  index.json                       années, totaux par année et par programme, fichiers, règles, sources inaccessibles
  programmes/<p>[_<k>].json        série par association (personnes morales) x année, programme <p>
  fonds_fondations.json            RNF : titre, type, objet social filtré, SIRET, années de subventions publiques
  reserve/<an|senat>_<annee>.json  réserve parlementaire par parlementaire ; bénéficiaires nommés si appariés à une
                                   personne morale, sinon agrégés

Règles : seules les personnes morales sont nommées (catégorie juridique 2xxx à 9xxx, hors groupements de personnes
physiques, `sirene.personne_morale`). Parlementaires nommés dans leur rôle public (attribution de la réserve, publiée
par chaque assemblée), comme les élus de pipeline/vie_politique.py ; aucune adresse lue en sortie. « nc » = source
non publiée ou inexploitable pour l'année : jamais 0.
"""
from __future__ import annotations

import argparse
import csv
import functools
import io
import json
import re
import sys
import time
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path

import beneficiaires as B
import sirene
from reproductible import date_sources

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
ASSO = LAKE / "associations"
RESTREINT = LAKE / "_restreint" / "associations"
CACHE = LAKE / "_cache" / "associations"
STOCK_SIRENE = LAKE / "_cache" / "local" / "sirene_unite_legale.parquet"
SITE = ROOT / "site" / "data"
MAX_OCTETS = 4_800_000
NC = "nc"

ANNEES = list(range(2012, 2026))  # année du PLF ; crédits versés deux ans avant (PLF 2025 : crédits 2023)
DATAGOUV = {2012: "53699ccba3a729239d205a72", 2013: "53699cdaa3a729239d205a9a", 2014: "53699ce1a3a729239d205ab2",
            2015: "5447dad5c751df10d05d0572", 2016: "56a8dd2ac751df2657ceae1f", 2017: "58078e78c751df2d1a79df72",
            2018: "5a059001c751df32ef55cf4a", 2019: "5dfc120e06e3e74107fac9cf", 2020: "5dfc123adee7e76b998c3ede",
            2021: "5fa09eb4558b3893be1963e6", 2022: "616f5d20176269415b2f28a0", 2023: "640bc79dfffaae3af367de74",
            2024: "655d44fd721472836cd2b6a4", 2025: "67884ef83b74bb8c78133b6d"}
INEXPLOITABLES = {
    2024: ("Le jeu publié pour le PLF 2024 (data.economie.gouv.fr plf24-donnees-de-l-annexe-jaune-effort-financier-"
           "de-l-etat-en-faveur-des-associa, repris sur data.gouv.fr 655d44fd) ne contient qu'une colonne de 111 "
           "nombres, sans association ni programme : année non couverte (« nc »)."),
}
SOURCE_JAUNES = ("data.gouv.fr et data.economie.gouv.fr, annexes jaunes « Effort financier de l'État en faveur des "
                 "associations » des PLF 2012 à 2025 (listes des subventions versées deux ans avant)")
SOURCE_SIRENE = ("Insee, stock SIRENE des unités légales (data.gouv.fr, catégorie juridique, dénomination et RNA des "
                 "personnes morales)")
SOURCE_RNF = ("data.gouv.fr, ministère de l'Intérieur, « Fichiers relatifs au Registre national des fonds et "
              "fondations (RNF) », données fonds/fondations (csv/zip) du 01/11/2026")
SOURCE_AN = ("data.assemblee-nationale.fr, réserve parlementaire (RESERVE_PARLEMENTAIRE/<année>_reserve_parlementaire.csv)")
SOURCE_SENAT = "data.senat.fr, réserve parlementaire (data/reserve/reserve<année>.csv)"
SOURCE_API = "API Recherche d'entreprises (recherche-entreprises.api.gouv.fr), recherche par nom et département"

ORDRE_SERIE = {"regle": "montant total reçu sur les années couvertes, du plus élevé au plus faible ; à égalité, SIREN "
                        "croissant",
               "cles": ["-total_eur", "siren"]}
ORDRE_RNF = {"regle": "ordre alphabétique du titre (capitales sans accents), puis numéro RNF", "cles": ["titre", "numero_rnf"]}
ORDRE_RESERVE = {"regle": "parlementaires par ordre alphabétique de nom_tri (nom puis prénom, capitales sans accents) ; "
                          "bénéficiaires nommés de chaque parlementaire par montant décroissant, puis dénomination",
                 "cles": ["nom_tri", "-montant_eur", "denomination"]}
REGLE_PERSONNES = ("Seules les personnes morales sont nommées (catégorie juridique SIRENE 2xxx à 9xxx, hors groupements "
                   "de personnes physiques). Entrepreneurs individuels, lignes sans SIREN valide et bénéficiaires de la "
                   "réserve non appariés à une personne morale : montants agrégés, jamais nommés. Aucune adresse n'est "
                   "publiée.")
REGLE_PARLEMENTAIRES = ("Les parlementaires sont nommés dans leur rôle public (attribution de la réserve parlementaire, "
                        "listes publiées par l'Assemblée nationale et le Sénat), comme les élus et candidats des comptes "
                        "de campagne : nom, groupe, département, montants. Ni adresse ni autre donnée personnelle. Un "
                        "parlementaire par ailleurs candidat à un scrutin national n'est pas nommé ici "
                        "(parlementaires_non_nommes) ; une association de financement de campagne non plus.")
RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "trouvailles": [
        {"nom": "regardscitoyens/reserveparlementaire_parser (GitHub)", "verdict": "inspiration seulement",
         "licence": "GPL-3.0", "dernier_commit": "2021-01-22",
         "note": "analyse des pages HTML de l'Assemblée (2013) ; les CSV officiels 2013-2016 suffisent"},
        {"nom": "Regards Citoyens, réserve parlementaire 2011 et 2013 compilée (data.gouv.fr 541eafe3)",
         "verdict": "inspiration seulement", "licence": "ODbL", "dernier_commit": "2014-09-21",
         "note": "licence à partage à l'identique incompatible avec la Licence Ouverte des sorties ; années hors champ"},
        {"nom": "regardscitoyens/reserveparlementaire_carto (GitHub)", "verdict": "inspiration seulement",
         "licence": "non précisée", "dernier_commit": "2015-03-18", "note": "cartographie, pas d'appariement"},
        {"nom": "nigiord/Reserve_parlementaire, KudoL/ReserveParlementaire (GitHub)", "verdict": "inspiration seulement",
         "licence": "non précisée", "dernier_commit": "2017-02-01", "note": "analyses ponctuelles d'une année"},
        {"nom": "pipeline/beneficiaires.py, pipeline/sirene.py, pipeline/local.py (ce dépôt)",
         "verdict": "réutilisable tel quel", "licence": "MIT", "dernier_commit": "2026-11-17",
         "note": "lecture du jaune PLF 2025, statut personne morale, filtre de noms dans les textes libres, stock SIRENE"},
        {"nom": "API Recherche d'entreprises (DINUM)", "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "dernier_commit": "service en ligne",
         "note": "appariement des bénéficiaires restants par nom et département"},
    ],
}


# --- Utilitaires -----------------------------------------------------------------------------------------------------


def propre(v) -> str:
    return B.propre(v)


def sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))


def norm(s) -> str:
    """Capitales sans accents ni ponctuation ; « ST » et « STE » développés."""
    t = re.sub(r"[^A-Z0-9]+", " ", sans_accents(propre(s)).upper().replace("’", "'")).strip()
    t = re.sub(r"\bSTE\b", "SAINTE", re.sub(r"\bST\b", "SAINT", t))
    return re.sub(r"\s+", " ", t)


MOTS_VIDES = {"DE", "DU", "DES", "LA", "LE", "LES", "ET", "A", "AU", "AUX", "EN", "POUR", "SUR", "D", "L", "ASSOCIATION",
              "ASSO", "ASS", "ASSOC", "THE", "OF", "PAR", "DANS", "UN", "UNE"}


def jetons(s) -> frozenset:
    return frozenset(t for t in norm(s).split() if t not in MOTS_VIDES)


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def montant(v) -> float | None:
    """Montant publié (nombre, « 1 190,00 » avec espaces insécables, « 71070.0 ») ; None si illisible ou vide."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[\s  €]", "", str(v)).replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def code_programme(v) -> str | None:
    s = propre(v)
    m = re.match(r"^P?(\d{1,3})(?:\.0+)?(?!\d)", s) or re.search(r"(?<!\d)(\d{3})\s*-", s)
    return m.group(1).zfill(3) if m else None


def libelle_programme(v) -> str | None:
    m = re.match(r"^P?\d{3}\s*-\s*(.+)$", propre(v))
    return m.group(1).strip() if m else None


def siren_de(v) -> str:
    if isinstance(v, (int, float)):
        return str(int(v)).zfill(9)
    s = re.sub(r"\s", "", propre(v))
    if re.match(r"^\d{8,9}(\.0)?$", s):
        return s.split(".")[0].zfill(9)
    return s


def ecrire(chemin: Path, obj) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > 5_000_000:
        raise SystemExit(f"{chemin} dépasse 5 Mo : découper")
    chemin.write_text(texte + "\n", encoding="utf-8")


def lire_cache(nom: str) -> dict:
    p = CACHE / nom
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def sauver_cache(nom: str, obj: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / (nom + ".part")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(CACHE / nom)


# --- 1. Jaunes -------------------------------------------------------------------------------------------------------


def _csv(chemin: Path) -> list[dict]:
    raw = chemin.read_bytes()
    try:
        t = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        t = raw.decode("cp1252")
    return list(csv.DictReader(io.StringIO(t), delimiter=";"))


def _xlsx(chemin: Path) -> list[dict]:
    """Première feuille ; l'en-tête est la première ligne qui contient « SIREN »."""
    import openpyxl
    wb = openpyxl.load_workbook(chemin, read_only=True)
    ws = wb.worksheets[0]
    entete, out = None, []
    for row in ws.iter_rows(values_only=True):
        if entete is None:
            if any(str(x or "").strip().upper() == "SIREN" for x in row):
                entete = [propre(x) for x in row]
            continue
        if any(x not in (None, "") for x in row):
            out.append(dict(zip(entete, row)))
    wb.close()
    if entete is None:
        raise SystemExit(f"{chemin} : en-tête introuvable")
    return out


def fichier_jaune(annee: int) -> Path | None:
    p = ASSO / f"assoc_jaune_plf{annee}.csv"
    if p.exists():
        return p
    d = ASSO / f"assoc_jaune_plf{annee}"
    if d.is_dir():
        xs = sorted(d.glob("*.xlsx"))
        return xs[0] if xs else None
    return None


def _colonne(cols, *motifs, exclure=()) -> str | None:
    for m in motifs:
        for c in cols:
            n = norm(c)
            if re.search(m, n) and not any(re.search(x, n) for x in exclure):
                return c
    return None


def lire_jaune(annee: int) -> dict:
    """Lignes normalisées {programme, libelle, siren, denomination, montant, cj, departement} d'un jaune.

    PLF 2012 : une ligne « total » par association et, quand la source les détaille, des lignes par programme
    (imputation) : le détail est retenu, le total seul (sans programme) sinon.
    """
    if annee == 2025:
        lignes = [{"programme": code_programme(p), "libelle": None, "siren": siren_de(s), "denomination": propre(d),
                   "montant": float(m or 0), "cj": propre(cj), "departement": None}
                  for p, s, d, m, _, cj in B._assoc_lignes()]
        return {"lignes": lignes, "annee_credits": 2023, "fichier": str(B.SRC["associations"]["chemin"].relative_to(ROOT))}
    f = fichier_jaune(annee)
    if f is None:
        raise FileNotFoundError(f"jaune PLF {annee} absent de l'entrepôt (python collecte/collecte.py assoc_jaune_plf{annee})")
    rows = _xlsx(f) if f.suffix == ".xlsx" else _csv(f)
    cols = list(rows[0]) if rows else []
    out = []
    if annee == 2012:
        detail = defaultdict(list)
        totaux = {}
        total_publie = None
        for r in rows:
            s = siren_de(r.get("siren"))
            if re.match(r"^total", s, re.I):  # ligne « Total des subventions versées en 2010 » : contrôle, pas une association
                total_publie = montant(r.get("total_des_subventions")) or montant(r.get("detail_des_subventions"))
                continue
            imp = propre(r.get("imputation"))
            if imp:
                detail[s].append(r)
            elif montant(r.get("total_des_subventions")) is not None:
                totaux[s] = r
        for s, rs in detail.items():
            for r in rs:
                out.append({"programme": code_programme(re.sub(r"^[^:]*:\s*", "", propre(r["imputation"]))),
                            "libelle": libelle_programme(re.sub(r"^[^:]*:\s*", "", propre(r["imputation"]))),
                            "siren": s, "denomination": re.sub(r"\s+-\s+\d[\dAB]\s+.*$", "", propre(r["association"])),
                            "montant": montant(r.get("detail_des_subventions")) or 0.0, "cj": "", "departement": None})
        for s, r in totaux.items():
            if s not in detail:
                out.append({"programme": None, "libelle": None, "siren": s,
                            "denomination": re.sub(r"\s+-\s+\d[\dAB]\s+.*$", "", propre(r["association"])),
                            "montant": montant(r.get("total_des_subventions")) or 0.0, "cj": "", "departement": None})
        somme = sum(l["montant"] for l in out)
        if total_publie is None or abs(somme - total_publie) > 1:
            raise SystemExit(f"PLF 2012 : somme des lignes {somme} != total publié {total_publie}")
        return {"lignes": out, "annee_credits": 2010, "fichier": str(f.relative_to(ROOT)), "total_publie": total_publie}
    c_prog = _colonne(cols, r"^PROGRAMME")
    c_siren = _colonne(cols, r"^SIREN$")
    c_nom = _colonne(cols, r"^DENOMINATION$", r"^ASSOCIATION$")
    c_mt = _colonne(cols, r"^MONTANT$", r"^SUBVENTION", r"^\d{4}$")
    c_cj = _colonne(cols, r"NOMENCLATURE JURIDIQUE", r"CATEGORIE JURIDIQUE")
    c_dep = _colonne(cols, r"DEPARTEMENT", exclure=(r"MINISTERE",))
    c_cog = _colonne(cols, r"^COG CODE$")
    c_mill = _colonne(cols, r"^MILLESIME$")
    if not (c_prog and c_siren and c_nom and c_mt):
        raise SystemExit(f"PLF {annee} : colonnes inattendues {cols}")
    annee_credits = annee - 2
    if c_mill and rows:
        m = re.search(r"(?:Subventions?|en)\s+(20\d\d)", propre(rows[0][c_mill]))
        if m:
            annee_credits = int(m.group(1))
    for r in rows:
        mt = montant(r.get(c_mt))
        if mt is None:
            continue
        dep = propre(r.get(c_dep)) if c_dep else ""
        if not dep and c_cog:
            cog = propre(r.get(c_cog))
            dep = cog[:3] if cog.startswith("97") else cog[:2]
        out.append({"programme": code_programme(r.get(c_prog)), "libelle": libelle_programme(r.get(c_prog)),
                    "siren": siren_de(r.get(c_siren)), "denomination": propre(r.get(c_nom)), "montant": mt,
                    "cj": propre(r.get(c_cj)).split(".")[0] if c_cj else "",
                    "departement": dep.split(".")[0].zfill(2) if re.match(r"^\d", dep) else (dep or None)})
    return {"lignes": out, "annee_credits": annee_credits, "fichier": str(f.relative_to(ROOT))}


# PLF 2013 : l'export publié multiplie chaque montant par 10 (contrôlé à chaque production, sinon arrêt).
CORRECTIONS = {2013: {"facteur": 0.1, "comparee_a": (2012, 2014)}}


def controle_correction(js: dict, annee: int) -> dict:
    """Preuve publiée de la correction : part des montants multiples de 10 et rapport médian avec les mêmes couples
    (SIREN, programme) des années voisines. Arrêt si la preuve ne tient plus (source corrigée en amont)."""
    import statistics

    def couples(a):
        d = defaultdict(float)
        for l in js[a]["lignes"]:
            d[(l["siren"], l["programme"])] += l["montant"]
        return d

    c = CORRECTIONS[annee]
    brut = couples(annee)
    lignes = js[annee]["lignes"]
    part10 = sum(1 for l in lignes if l["montant"] % 10 == 0) / len(lignes)
    rapports = {}
    for b in c["comparee_a"]:
        v = couples(b)
        r = [brut[k] / v[k] for k in brut if v.get(k)]
        rapports[str(b)] = {"couples": len(r), "rapport_median": round(statistics.median(r), 4)}
    if part10 < 0.99 or any(abs(x["rapport_median"] - 1 / c["facteur"]) > 0.05 for x in rapports.values()):
        raise SystemExit(f"PLF {annee} : la correction x{c['facteur']} n'est plus justifiée ({part10}, {rapports}) : "
                         "revoir CORRECTIONS")
    return {"facteur": c["facteur"], "part_montants_multiples_de_10": round(part10, 4),
            "comparaison_annees_voisines": rapports,
            "raison": (f"Dans l'export publié du PLF {annee}, tous les montants sont des multiples de 10 et le rapport "
                       "médian avec les mêmes association et programme des années voisines vaut 10 (par exemple, un "
                       "poste FONJEP publié 71 070 € pour un montant unitaire de 7 107 €) : montants divisés par 10. "
                       "Les montants bruts restent dans l'entrepôt.")}


def jaunes() -> dict[int, dict]:
    res = {}
    for a in ANNEES:
        if a in INEXPLOITABLES:
            continue
        res[a] = lire_jaune(a)
    for a in CORRECTIONS:
        preuve = controle_correction(res, a)
        for l in res[a]["lignes"]:
            l["montant"] = l["montant"] * preuve["facteur"]
        res[a]["correction"] = preuve
    return res


# --- 2. SIRENE (extrait local) ---------------------------------------------------------------------------------------


def sirens_a_verifier(js: dict, rnf: list[dict], communes: dict) -> set[str]:
    s = {l["siren"] for j in js.values() for l in j["lignes"] if sirene.siren_valide(l["siren"])}
    s |= {r["siret"][:9] for r in rnf if r.get("siret")}
    s |= set(communes.values())
    s |= {v["siren"] for v in lire_cache("api_reserve.json").values() if v and v.get("siren")}
    return {x for x in s if sirene.siren_valide(x)}


def extrait_sirene(sirens: set[str]) -> dict:
    """Complète data/lake/_cache/associations/sirene_extrait.json depuis le stock SIRENE local.

    Personne physique : seule la catégorie juridique est gardée (ni nom ni prénom)."""
    import duckdb
    ext = lire_cache("sirene_extrait.json")
    manquants = sorted(sirens - set(ext))
    if not manquants:
        return ext
    if not STOCK_SIRENE.exists():
        print(f"  stock SIRENE absent ({STOCK_SIRENE.relative_to(ROOT)}) : {len(manquants)} SIREN non vérifiés "
              "(python pipeline/local.py le télécharge)", file=sys.stderr)
        return ext
    con = duckdb.connect()
    con.execute("create table s as select unnest(?::varchar[]) siren", [manquants])
    rows = con.execute(f"""select u.siren, u.categorieJuridiqueUniteLegale, u.denominationUniteLegale,
                                  u.sigleUniteLegale, u.identifiantAssociationUniteLegale
                           from '{STOCK_SIRENE}' u join s using (siren)""").fetchall()
    trouves = set()
    for siren, cj, denom, sigle, rna in rows:
        cj = str(cj or "").split(".")[0]
        e = {"cj": cj or None, "trouve": True}
        if sirene.personne_morale(cj):
            e["nom"] = propre(denom) or propre(sigle) or None
            if rna:
                e["rna"] = propre(rna)
        ext[siren] = e
        trouves.add(siren)
    for s in manquants:
        if s not in trouves:
            ext[s] = {"cj": None, "trouve": False}
    sauver_cache("sirene_extrait.json", ext)
    return ext


@functools.lru_cache(maxsize=1)
def prenoms() -> frozenset:
    """Prénoms du filtre de noms : la liste versionnée de pipeline/local.py (Insee, pipeline/donnees_ref/prenoms.txt),
    sans cache ni stock SIRENE."""
    import local
    return frozenset(local.prenoms())


ADRESSE_RE = re.compile(r"\b\d{1,4}\s*(?:bis|ter)?\s*,?\s+(?:rue|avenue|av\.?|bd|boulevard|place|chemin|route|all[ée]e|"
                        r"impasse|quai|cours|square|lotissement|lieu-dit|voie)\b", re.I)


def texte_publiable(o, liste: set, longueur: int = 140) -> str | None:
    """Texte libre publié seulement sans nom de personne possible (filtre de pipeline/local.py) ni adresse postale
    (numéro suivi d'un type de voie) ; sinon null."""
    import local
    o = propre(o)
    if not o or ADRESSE_RE.search(o) or cite_candidat(o):
        return None
    t = local.objet_publiable(o, liste, longueur=10 ** 6)
    if t is None:
        return None
    return t if len(t) <= longueur else t[:longueur - 1].rstrip() + "…"


_CANDIDATS: set | None = None
FINANCEMENT_ELECTORAL_RE = re.compile(r"\b(?:FINANCEMENT|MANDATAIRE|COMPTES?)\b.*\b(?:CAMPAGNE|ELECTORALE?S?|ELECTIONS?|"
                                      r"PRESIDENTIELLES?|LEGISLATIVES?|MUNICIPALES?|CANDIDATE?S?)\b")


def _cle_candidat(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", sans_accents(str(s)).lower()).strip()


def candidats_nationaux() -> set:
    """Noms des candidats aux scrutins nationaux (présidentielles, têtes de liste européennes) publiés dans
    site/data/vie_politique/candidats/ : la règle du projet ne les nomme que là (tests/test_vie_politique.py)."""
    global _CANDIDATS
    if _CANDIDATS is None:
        _CANDIDATS = set()
        d = SITE / "vie_politique" / "candidats"
        for f in sorted(d.glob("*.json")) if d.is_dir() else []:
            if not f.name.startswith(("presidentielle_", "europeennes_")):
                continue
            for c in json.loads(f.read_text(encoding="utf-8"))["candidats"]:
                for morceau in re.split(r"\bet\b", c["candidat"]):
                    n = _cle_candidat(morceau)
                    if len(n.split()) >= 2 and len(n) >= 8:
                        _CANDIDATS.add(n)
    return _CANDIDATS


def cite_candidat(texte) -> bool:
    """Vrai si le texte contient le nom d'un candidat national (suite de 2 à 5 mots)."""
    noms = candidats_nationaux()
    if not noms or not texte:
        return False
    t = _cle_candidat(texte).split()
    return any(" ".join(t[i:i + n]) in noms for n in range(2, 6) for i in range(len(t) - n + 1))


# Mots qui désignent un organisme : une dénomination qui en contient un n'est pas un nom de personne seul.
MOTS_ORGANISME = frozenset("""
ASSOCIATION ASSOC ASSO FONDATION FOUNDATION FONDS ENDOWMENT COMITE CLUB AMIS AMICALE INSTITUT ACADEMIE ECOLE CENTRE
FEDERATION UNION SOCIETE OFFICE GROUPE GROUPEMENT COMPAGNIE CIE THEATRE MUSEE MAISON FOYER CERCLE ENSEMBLE ORCHESTRE
CHOEUR CHORALE LYCEE COLLEGE UNIVERSITE SYNDICAT MUTUELLE COOPERATIVE CAISSE HOPITAL CLINIQUE RESIDENCE ATELIER
ATELIERS STUDIO FESTIVAL PRODUCTIONS PRODUCTION FILMS EDITIONS GALERIE OEUVRE OEUVRES ACTION AIDE SECOURS MECENAT
SOLIDARITE SPORT SPORTS SPORTIF SPORTIVE RUGBY FOOTBALL BASKET TENNIS HANDBALL VOLLEY JUDO CYCLISTE OLYMPIQUE ETOILE
AVENIR ENTENTE RESEAU COLLECTIF PROJET COMPANY ORCHESTRA FESTIVAL
""".split())


def nom_de_personne_seul(nom) -> bool:
    """Dénomination faite d'un prénom fréquent suivi d'un nom (deux ou trois mots, aucun mot d'organisme), par exemple
    « Prénom Nom » ou « Prénom Nom, président » : elle désigne peut-être une personne physique. Prudence : non publiée,
    le montant reste dans les totaux (filtre de prénoms de pipeline/local.py, comme pour les textes libres)."""
    if not nom:
        return False
    import local
    mots = re.findall(r"[A-Z]+", unicodedata.normalize("NFKD", str(nom).upper()).encode("ascii", "ignore").decode())
    if not 2 <= len(mots) <= 3 or any(m in MOTS_ORGANISME or m in local.EQUIPEMENTS_ET_VOIES for m in mots):
        return False
    liste = prenoms()
    return mots[0] in liste and local.contient_nom_de_personne(str(nom), liste)


DOMICILIATION_RE = re.compile(r"\s*CHEZ\s*(?:M|MME|MLLE|MR|MONSIEUR|MADAME|MADEMOISELLE)\b\.?[^-–(]*", re.I)


def sans_domiciliation(nom):
    """Dénomination sans sa domiciliation chez une personne (« ASSOCIATION X CHEZ M. Prénom Nom - 28 » devient
    « ASSOCIATION X - 28 ») : le nom de la personne qui héberge le siège n'est jamais publié."""
    if not nom or not DOMICILIATION_RE.search(str(nom)):
        return nom
    return re.sub(r"\s{2,}", " ", DOMICILIATION_RE.sub(" ", str(nom))).strip(" -") or None


def denomination_nominative(nom) -> bool:
    """Dénomination jamais publiée : association de financement ou mandataire d'une campagne électorale (elle porte
    le nom du candidat), nom d'un candidat national, ou nom de personne seul (nom_de_personne_seul)."""
    return bool(nom) and (bool(FINANCEMENT_ELECTORAL_RE.search(norm(nom))) or cite_candidat(nom)
                          or nom_de_personne_seul(nom))


# --- 3. Série par association x programme x année ---------------------------------------------------------------------


def serie(js: dict, ext: dict) -> dict:
    """{programme: {libelle, assoc: {siren: {annee: montant}}, annees: {annee: compteurs}}} et totaux par année."""
    progs = defaultdict(lambda: {"libelle": None, "assoc": defaultdict(lambda: defaultdict(float)),
                                 "annees": defaultdict(lambda: {"total": 0.0, "lignes": 0, "nommes": 0.0,
                                                                "pp": 0.0, "ni": 0.0, "nv": 0.0, "nom": 0.0})})
    noms_source = {}
    totaux = {}
    nominatifs = {l["siren"] for j in js.values() for l in j["lignes"] if denomination_nominative(l["denomination"])}
    nominatifs |= {s for s, e in ext.items() if e.get("nom") and denomination_nominative(e["nom"])}
    # Décision du 19/11/2026 (option B) : nom rétabli si le stock SIRENE confirme une personne morale ; c'est alors la
    # dénomination de l'unité légale (raison sociale) qui est publiée, pas celle de la source.
    retablis = {s: n for s in sorted(nominatifs)
                if (n := sirene.nom_publiable_personne_morale(s, (ext.get(s) or {}).get("cj"),
                                                              (ext.get(s) or {}).get("nom")))}
    nominatifs -= set(retablis)
    for a in sorted(js):
        j = js[a]
        t = {"total": 0.0, "lignes": 0, "nommes": 0.0, "pp": 0.0, "ni": 0.0, "nv": 0.0, "nom": 0.0, "assoc": set(),
             "sans_programme": 0.0}
        for l in j["lignes"]:
            p = l["programme"] or "sans_programme"
            g = progs[p]
            if l.get("libelle"):
                g["libelle"] = l["libelle"]
            c = g["annees"][a]
            c["total"] += l["montant"]
            c["lignes"] += 1
            t["total"] += l["montant"]
            t["lignes"] += 1
            if p == "sans_programme":
                t["sans_programme"] += l["montant"]
            st, cj = B.statut(l["siren"], l["cj"], ext)
            if st == "pm" and l["siren"] in nominatifs:
                c["nom"] += l["montant"]
                t["nom"] += l["montant"]
            elif st == "pm":
                g["assoc"][l["siren"]][a] += l["montant"]
                c["nommes"] += l["montant"]
                t["nommes"] += l["montant"]
                t["assoc"].add(l["siren"])
                noms_source[l["siren"]] = (a, l["denomination"], cj)
            else:
                cle = {"pp": "pp", "nv": "nv"}.get(st, "ni")
                c[cle] += l["montant"]
                t[cle] += l["montant"]
        totaux[a] = t
    return {"programmes": progs, "totaux": totaux, "noms_source": noms_source, "retablis": retablis}


def _parts(lignes: list, entete_octets: int) -> list[list]:
    """Découpe une liste de lignes en parts dont le JSON reste sous MAX_OCTETS."""
    parts, cur, taille = [], [], entete_octets
    for l in lignes:
        n = len(json.dumps(l, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        if cur and taille + n > MAX_OCTETS:
            parts.append(cur)
            cur, taille = [], entete_octets
        cur.append(l)
        taille += n
    parts.append(cur)
    return parts


def produire_serie(js: dict, ext: dict, sortie: Path) -> dict:
    s = serie(js, ext)
    annees = ANNEES
    credits = {a: (js[a]["annee_credits"] if a in js else a - 2) for a in annees}
    d = sortie / "programmes"
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.json"):
        f.unlink()
    index_progs = []
    nommees = set()
    for p in sorted(s["programmes"], key=lambda x: (x == "sans_programme", x)):
        g = s["programmes"][p]
        lignes = []
        for siren, par_an in g["assoc"].items():
            e = ext.get(siren) or {}
            # dénomination la plus récente ; raison sociale SIRENE pour un nom rétabli (option B du 19/11/2026)
            nom = s["retablis"].get(siren) or sans_domiciliation(s["noms_source"][siren][1] or e.get("nom") or None)
            cj = s["noms_source"][siren][2]
            vals = [NC if a in INEXPLOITABLES else (B.eur(par_an[a]) if a in par_an else None) for a in annees]
            lignes.append([siren, nom, cj, B.eur(sum(par_an.values())), vals])
            nommees.add(siren)
        lignes.sort(key=lambda l: (-l[3], l[0]))
        par_annee = []
        for a in annees:
            if a in INEXPLOITABLES:
                par_annee.append({"annee": a, "annee_credits": credits[a], "statut": NC, "total_source_eur": NC,
                                  "nommes_eur": NC, "exclus_personnes_physiques_ou_non_identifies_eur": NC,
                                  "non_verifies_eur": NC, "lignes_source": NC})
                continue
            c = g["annees"].get(a)
            if c is None:
                par_annee.append({"annee": a, "annee_credits": credits[a], "statut": "absent_de_la_source",
                                  "total_source_eur": None, "nommes_eur": None,
                                  "exclus_personnes_physiques_ou_non_identifies_eur": None, "non_verifies_eur": None,
                                  "lignes_source": 0})
                continue
            par_annee.append({"annee": a, "annee_credits": credits[a], "statut": "publie",
                              **({"facteur_correction": js[a]["correction"]["facteur"]} if "correction" in js[a] else {}),
                              "total_source_eur": B.eur(c["total"]), "nommes_eur": B.eur(c["nommes"]),
                              "exclus_personnes_physiques_ou_non_identifies_eur": B.eur(c["pp"] + c["ni"] + c["nom"]),
                              "dont_personnes_physiques_eur": B.eur(c["pp"]),
                              "dont_denomination_nominative_eur": B.eur(c["nom"]), "non_verifies_eur": B.eur(c["nv"]),
                              "lignes_source": c["lignes"]})
        entete = {
            "millesime": f"Jaunes associations PLF {annees[0]} à PLF {annees[-1]} (crédits versés de "
                         f"{credits[annees[0]]} à {credits[annees[-1]]})",
            "source": f"{SOURCE_JAUNES} ; {SOURCE_SIRENE}",
            "unite": "euros (crédits versés l'année annee_credits, tels que publiés)",
            "programme": None if p == "sans_programme" else p, "libelle": g["libelle"],
            "annees": annees, "annees_credits": [credits[a] for a in annees],
            "colonnes": ["siren", "denomination", "categorie_juridique", "total_eur", "montants_eur"],
            "lecture": ("montants_eur suit annees : nombre = montant publié ; null = association absente de la liste "
                        "de cette année pour ce programme ; « nc » = liste de l'année non publiée ou inexploitable. "
                        "facteur_correction (par_annee) : montants de l'année corrigés, raison dans associations/index.json."),
            "regle": REGLE_PERSONNES, "ordre": ORDRE_SERIE, "par_annee": par_annee,
            "associations_nommees": len(lignes),
        }
        if p == "sans_programme":
            entete["note"] = ("PLF 2012 : associations dont la source ne donne que le total, sans programme d'imputation.")
        octets = len(json.dumps(entete, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 200
        parts = _parts(lignes, octets)
        fichiers = []
        for k, part in enumerate(parts, 1):
            nom = f"{p}.json" if len(parts) == 1 else f"{p}_{k}.json"
            obj = dict(entete, partie=k, parties=len(parts), lignes=part)
            ecrire(d / nom, obj)
            fichiers.append(f"associations/programmes/{nom}")
        index_progs.append({"programme": entete["programme"], "libelle": g["libelle"], "fichiers": fichiers,
                            "associations_nommees": len(lignes),
                            "totaux_eur": [x["total_source_eur"] for x in par_annee]})
    return {"programmes": index_progs, "totaux": s["totaux"], "credits": credits, "nommees": nommees}


# --- 4. RNF : fonds et fondations --------------------------------------------------------------------------------------


def lire_rnf() -> list[dict]:
    d = ASSO / "assoc_rnf_fonds_fondations"
    zs = sorted(d.glob("*.zip")) if d.is_dir() else []
    if not zs:
        raise FileNotFoundError("RNF absent de l'entrepôt (python collecte/collecte.py assoc_rnf_fonds_fondations)")
    with zipfile.ZipFile(zs[-1]) as z:
        nom = [n for n in z.namelist() if n.endswith(".csv") and "donnees" in n][0]
        texte = z.read(nom).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(texte), delimiter=";" if texte.split("\n")[0].count(";") else ","))
    if not rows or "numero_rnf" not in rows[0]:
        raise SystemExit(f"RNF : colonnes inattendues {list(rows[0]) if rows else []}")
    out = []
    for r in rows:
        siret = re.sub(r"\D", "", propre(r.get("siret")))
        out.append({**{k: (None if propre(v) in ("", "None", "null") else propre(v)) for k, v in r.items()},
                    "siret": siret if len(siret) == 14 else None})
    return out


def annees_liste(v) -> list[int] | None:
    if not v:
        return None
    xs = sorted({int(x) for x in re.findall(r"(?<!\d)(?:19|20)\d\d(?!\d)", v)})
    return xs or None


TYPES_RNF = {"FDD": "fonds de dotation", "FE": "fondation d'entreprise", "FRUP": "fondation reconnue d'utilité publique"}


def produire_rnf(rnf: list[dict], ext: dict, liste: set, sortie: Path) -> dict:
    import vie_politique as vp
    lignes, filtres, titres_retires = [], 0, 0
    for r in rnf:
        objet = texte_publiable(r.get("objet_social"), liste, longueur=400)
        if r.get("objet_social") and objet is None:
            filtres += 1
        siren = (r["siret"] or "")[:9]
        e = ext.get(siren) or {}
        titre = r.get("titre")
        if denomination_nominative(titre):
            titre = sirene.nom_publiable_personne_morale(siren, e.get("cj"), e.get("nom"))  # option B, 19/11/2026
            titres_retires += titre is None
        lignes.append([r["numero_rnf"], titre, r.get("type_organisme"), objet,
                       (r.get("date_creation") or "")[:10] or None, r.get("domaine_interet_general"), r.get("etat"),
                       r.get("prefecture"), r["siret"], e.get("cj") if sirene.personne_morale(e.get("cj")) else None,
                       annees_liste(r.get("subventions_publiques")), annees_liste(r.get("appel_generosite_publique")),
                       r.get("etat_transmission_comptes")])
    lignes.sort(key=lambda l: (vp.cle_alpha(norm(l[1] or "")), l[0]))
    avec = [l for l in lignes if l[10]]
    obj = {"millesime": "Registre national des fonds et fondations, état au 01/11/2026",
           "source": f"{SOURCE_RNF} ; {SOURCE_SIRENE}",
           "colonnes": ["numero_rnf", "titre", "type", "objet_social", "date_creation", "domaine_interet_general",
                        "etat", "prefecture", "siret", "categorie_juridique", "annees_subventions_publiques",
                        "annees_appel_generosite_publique", "etat_transmission_comptes"],
           "types": TYPES_RNF,
           "lecture": ("annees_subventions_publiques : exercices pour lesquels l'organisme a déclaré avoir reçu des "
                       "subventions publiques (le registre ne publie pas de montant) ; null = rien de déclaré au "
                       "registre."),
           "regle": ("Ni adresse, ni code postal, ni ville, ni dirigeant : seules les données de l'organisme sont "
                     "reprises. L'objet social passe un filtre de noms de personnes (civilité, prénom fréquent suivi "
                     "d'un nom) et d'adresses (numéro suivi d'un type de voie) : s'il en contient un possible, il est "
                     "remplacé par null ; il est coupé à 400 caractères."),
           "ordre": ORDRE_RNF, "nombre": len(lignes),
           "nombre_avec_subventions_publiques_declarees": len(avec),
           "objets_retires_par_le_filtre": filtres, "titres_retires_candidat_national": titres_retires,
           "par_type": {t: sum(1 for l in lignes if l[2] == t) for t in sorted({l[2] for l in lignes if l[2]})},
           "lignes": lignes}
    ecrire(sortie / "fonds_fondations.json", obj)
    return {"nombre": len(lignes), "avec_subventions_publiques": len(avec), "objets_filtres": filtres}


# --- 5. Réserve parlementaire ------------------------------------------------------------------------------------------


def _lire_texte(p: Path) -> str:
    raw = p.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def departements() -> dict:
    p = ASSO / "assoc_departements.json"
    if not p.exists():
        raise FileNotFoundError("liste des départements absente (python collecte/collecte.py assoc_departements)")
    return {norm(d["nom"]): d["code"] for d in json.loads(p.read_text(encoding="utf-8"))}


# Colonnes lues (les colonnes d'adresse ne sont jamais lues).
COL_RESERVE = {
    "beneficiaire": (r"^BENEFICIAIRE$", r"^DESIGNATION DU DESTINATAIRE"),
    "montant": (r"^MONTANT$",),
    "descriptif": (r"^DESCRIPTIF$", r"^NATURE$"),
    "programme": (r"^PROGRAMME",),
    "groupe": (r"^GROUPE$",),
    "nom": (r"^NOM$",),
    "prenom": (r"^PRENOM$",),
    "senateur": (r"^SENATEUR$",),
    "departement": (r"^DEPARTEMENT$", r"^DPT"),
}


def lire_reserve(assemblee: str, annee: int) -> list[dict]:
    d = RESTREINT / ("assoc_reserve_an" if assemblee == "an" else "assoc_reserve_senat")
    p = d / (f"{annee}_reserve_parlementaire.csv" if assemblee == "an" else f"reserve{annee}.csv")
    if not p.exists():
        raise FileNotFoundError(f"{p.relative_to(ROOT)} absent (python collecte/collecte.py assoc_reserve_{assemblee})")
    t = _lire_texte(p)
    l1 = t.split("\n", 1)[0]
    rows = list(csv.reader(io.StringIO(t), delimiter=";" if l1.count(";") > l1.count(",") else ","))
    entete = [norm(c) for c in rows[0]]
    idx = {}
    for k, motifs in COL_RESERVE.items():
        for m in motifs:
            i = next((i for i, c in enumerate(entete) if re.search(m, c)), None)
            if i is not None:
                idx[k] = i
                break
    if not {"beneficiaire", "montant", "programme"} <= set(idx):
        raise SystemExit(f"{p.name} : colonnes inattendues {rows[0]}")
    out = []
    for r in rows[1:]:
        if len(r) < len(entete) - 1 or not any(x.strip() for x in r):
            continue
        g = {k: propre(r[i]) if i < len(r) else "" for k, i in idx.items()}
        mt = montant(g["montant"])
        if mt is None:
            continue
        if assemblee == "an":
            parl = f"{g.get('prenom', '')} {g.get('nom', '')}".strip()
            tri = sans_accents(f"{g.get('nom', '')} {g.get('prenom', '')}").upper().strip()
        else:
            parl = g.get("senateur", "")
            tri = sans_accents(parl).upper().strip()
        out.append({"beneficiaire": g["beneficiaire"], "montant": mt, "descriptif": g.get("descriptif"),
                    "programme": code_programme(g["programme"]), "programme_action": g["programme"] or None,
                    "groupe": g.get("groupe") or None, "parlementaire": parl, "nom_tri": re.sub(r"\s+", " ", tri),
                    "cle_parl": norm(f"{g.get('nom', '')} {g.get('prenom', '')}") if assemblee == "an" else norm(parl),
                    "departement_nom": g.get("departement") or None})
    return out


RESERVES = [("an", a) for a in range(2013, 2017)] + [("senat", a) for a in range(2014, 2018)]


def reserves() -> dict:
    res = {(ass, a): lire_reserve(ass, a) for ass, a in RESERVES}
    # AN 2016 : pas de colonne département ; repris des années précédentes pour le même député
    deps = {}
    for a in (2013, 2014, 2015):
        for l in res[("an", a)]:
            if l["departement_nom"]:
                deps[l["cle_parl"]] = l["departement_nom"]
    for l in res[("an", 2016)]:
        if not l["departement_nom"]:
            l["departement_nom"] = deps.get(l["cle_parl"])
    codes = departements()
    for ls in res.values():
        for l in ls:
            l["dep"] = codes.get(norm(l["departement_nom"] or ""))
    return res


def communes_par_departement() -> tuple[dict, dict]:
    """(dep, nom normalisé) -> SIREN de la commune (table Banatic) ; et SIREN -> code Insee."""
    d = ASSO / "assoc_banatic_siren_insee"
    fs = sorted(d.glob("*.csv")) if d.is_dir() else []
    if not fs:
        raise FileNotFoundError("table SIREN / Insee absente (python collecte/collecte.py assoc_banatic_siren_insee)")
    rows = list(csv.DictReader(io.StringIO(_lire_texte(fs[0])), delimiter=";"))
    idx, ambigus = {}, set()
    for r in rows:
        k = (r["dep_com"].zfill(2), norm(r["nom_com"]))
        if k in idx and idx[k] != r["siren"]:
            ambigus.add(k)
        idx[k] = r["siren"]
    for k in ambigus:
        idx.pop(k, None)
    return idx, {r["siren"]: r["insee"] for r in rows}


PREFIXE_COMMUNE = re.compile(r"^(?:COMMUNE|MAIRIE|VILLE|MUNICIPALITE)(?: DE LA| DE L| DES| DU| DE| D)? (.+)$")


def nom_commune(benef: str) -> str | None:
    n = norm(benef)
    m = PREFIXE_COMMUNE.match(n)
    return m.group(1) if m else n


def index_jaunes(js: dict) -> dict:
    """(année de crédits, programme, montant arrondi à l'euro) -> [(siren, jetons du nom, département)]."""
    idx = defaultdict(list)
    for j in js.values():
        for l in j["lignes"]:
            if l["programme"] and sirene.siren_valide(l["siren"]):
                idx[(j["annee_credits"], l["programme"], round(l["montant"]))].append(
                    (l["siren"], jetons(l["denomination"]), l["departement"]))
    return idx


def apparier_hors_ligne(l: dict, annee: int, communes: dict, ij: dict) -> tuple[str | None, str | None]:
    """(siren, méthode) : commune du département (Banatic), sinon même montant et programme dans le jaune de
    l'année (association), avec un nom proche (indice de Jaccard sur les mots >= 0,5, meilleur candidat unique)."""
    if l["dep"]:
        n = nom_commune(l["beneficiaire"])
        s = communes.get((l["dep"], n))
        if s:
            return s, "commune_banatic"
    cands = ij.get((annee, l["programme"], round(l["montant"])), [])
    if l["dep"]:
        cands = [c for c in cands if not c[2] or c[2] == l["dep"]]
    jb = jetons(l["beneficiaire"])
    scores = sorted(((jaccard(jb, c[1]), c[0]) for c in cands), reverse=True)
    scores = [x for x in scores if x[0] >= 0.5]
    if scores and (len(scores) == 1 or scores[0][0] > scores[1][0] or scores[0][1] == scores[1][1]):
        return scores[0][1], "jaune_meme_montant_programme"
    return None, None


def cle_api(l: dict) -> str:
    return f"{l['dep'] or ''}|{norm(l['beneficiaire'])}"


def _api_chercher(nom: str, dep: str | None) -> dict | None:
    """Résultat retenu : nom identique (après normalisation) ou indice de Jaccard >= 0,75, candidat unique.
    None si l'API est injoignable (on réessaiera) ; {} si rien de sûr."""
    import requests
    params = {"q": nom[:200], "page": 1, "per_page": 10}
    if dep:
        params["departement"] = dep
    for tentative in range(6):
        try:
            r = requests.get(sirene.API, params=params, headers=sirene.HEADERS, timeout=30)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(2 ** tentative)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** tentative)
            continue
        if r.status_code in (401, 403):
            raise SystemExit(f"API Recherche d'entreprises : accès refusé ({r.status_code}), jamais contourné")
        if r.status_code >= 400:
            return {}
        cible = norm(nom)
        jc = jetons(nom)
        cn = nom_commune(nom)
        bons = []
        for x in r.json().get("results", []):
            cj = str(x.get("nature_juridique") or "")
            noms = {norm(x.get("nom_complet")), norm(x.get("nom_raison_sociale")), norm(x.get("sigle"))} - {""}
            if cj == "7210":
                noms |= {nom_commune(n) for n in noms}
            score = 1.0 if (cible in noms or (cj == "7210" and cn in noms)) else \
                max((jaccard(jc, jetons(n)) for n in noms), default=0)
            if score >= 0.75:
                bons.append((score, x["siren"], cj))
        bons.sort(reverse=True)
        if bons and (len(bons) == 1 or bons[0][0] > bons[1][0]):
            s, cj = bons[0][1], bons[0][2]
            return {"siren": s, "cj": cj}
        return {}
    return None


def apparier(budget_s: float = 600) -> None:
    """Bénéficiaires de la réserve non appariés hors ligne, par montant décroissant : API (réseau, reprenable)."""
    js = jaunes()
    res = reserves()
    communes, _ = communes_par_departement()
    ij = index_jaunes(js)
    cache = lire_cache("api_reserve.json")
    a_faire = defaultdict(float)
    for (ass, a), ls in res.items():
        for l in ls:
            if apparier_hors_ligne(l, a, communes, ij)[0] is None:
                a_faire[cle_api(l)] += l["montant"]
    restants = [k for k, _ in sorted(a_faire.items(), key=lambda kv: (-kv[1], kv[0])) if k not in cache]
    print(f"{len(a_faire)} bénéficiaires à apparier par l'API, {len(restants)} pas encore interrogés", file=sys.stderr)
    import threading
    from concurrent.futures import ThreadPoolExecutor
    debut = time.monotonic()
    verrou = threading.Lock()
    prochain = [time.monotonic()]
    faits = [0]

    def tache(k):
        if time.monotonic() - debut > budget_s:
            return
        with verrou:  # espacement global des appels (limite de l'API : 7 par seconde)
            attente = prochain[0] - time.monotonic()
            prochain[0] = max(prochain[0], time.monotonic()) + sirene.PAUSE_S
        if attente > 0:
            time.sleep(attente)
        dep, nom = k.split("|", 1)
        e = _api_chercher(nom, dep or None)
        if e is None:
            return
        with verrou:
            cache[k] = e
            faits[0] += 1
            if faits[0] % 500 == 0:
                sauver_cache("api_reserve.json", dict(cache))
                print(f"  {faits[0]} interrogés", file=sys.stderr)

    with ThreadPoolExecutor(8) as ex:
        list(ex.map(tache, restants))
    sauver_cache("api_reserve.json", cache)
    reste = len([k for k in a_faire if k not in cache])
    print(f"apparier : {faits[0]} interrogés, {reste} restant(s)")


def produire_reserve(res: dict, js: dict, ext: dict, liste: set, sortie: Path) -> dict:
    communes, _ = communes_par_departement()
    ij = index_jaunes(js)
    api = lire_cache("api_reserve.json")
    d = sortie / "reserve"
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.json"):
        f.unlink()
    stats = {}
    for (ass, a), ls in sorted(res.items()):
        parls = {}
        progs = defaultdict(lambda: {"total": 0.0, "nommes": 0.0, "lignes": 0})
        methodes = defaultdict(int)
        tot = {"total": 0.0, "nommes": 0.0, "non_apparies": 0.0, "pp": 0.0, "non_verifies": 0.0, "lignes": 0,
               "lignes_nommees": 0}
        non_nommes = {"cles": set(), "total": 0.0, "lignes": 0}
        for l in ls:
            if cite_candidat(l["parlementaire"]) or cite_candidat(l["nom_tri"]):
                non_nommes["cles"].add(l["cle_parl"])
                non_nommes["total"] += l["montant"]
                non_nommes["lignes"] += 1
                tot["total"] += l["montant"]
                tot["lignes"] += 1
                g = progs[l["programme"] or "inconnu"]
                g["total"] += l["montant"]
                g["lignes"] += 1
                continue
            p = parls.setdefault(l["cle_parl"], {"parlementaire": l["parlementaire"], "nom_tri": l["nom_tri"],
                                                 "groupe": l["groupe"], "departement": l["departement_nom"],
                                                 "total": 0.0, "lignes": 0, "nommes": [],
                                                 "agreges": {"lignes": 0, "montant": 0.0, "pp": 0.0}})
            p["groupe"] = p["groupe"] or l["groupe"]
            p["total"] += l["montant"]
            p["lignes"] += 1
            tot["total"] += l["montant"]
            tot["lignes"] += 1
            g = progs[l["programme"] or "inconnu"]
            g["total"] += l["montant"]
            g["lignes"] += 1
            siren, methode = apparier_hors_ligne(l, a, communes, ij)
            if siren is None:
                e = api.get(cle_api(l)) or {}
                cj_api = str((ext.get(e.get("siren")) or {}).get("cj") or "")
                # par l'API, seulement des organismes publics, associations, fondations (7xxx à 9xxx) : une
                # société homonyme du département n'est jamais retenue
                siren, methode = ((e["siren"], "api_nom_departement") if e.get("siren") and cj_api[:1] in ("7", "8", "9")
                                  else (None, None))
            st, cj = B.statut(siren, None, ext) if siren else ("ni", None)
            e = ext.get(siren) or {}
            if st == "pm" and e.get("trouve") and (not denomination_nominative(e.get("nom")) or
                                                   sirene.nom_publiable_personne_morale(siren, e.get("cj"),
                                                                                        e.get("nom"))):
                p["nommes"].append([siren, e.get("nom") or None, cj, e.get("rna"), l["programme"],
                                    B.eur(l["montant"]), texte_publiable(l["descriptif"], liste), methode])
                g["nommes"] += l["montant"]
                tot["nommes"] += l["montant"]
                tot["lignes_nommees"] += 1
                methodes[methode] += 1
                continue
            p["agreges"]["lignes"] += 1
            p["agreges"]["montant"] += l["montant"]
            if st == "pp":
                p["agreges"]["pp"] += l["montant"]
                tot["pp"] += l["montant"]
            elif st == "nv":
                tot["non_verifies"] += l["montant"]
            else:
                tot["non_apparies"] += l["montant"]
        sortie_parls = []
        for p in parls.values():
            p["nommes"].sort(key=lambda x: (-x[5], norm(x[1] or ""), x[0]))
            sortie_parls.append({"parlementaire": p["parlementaire"], "nom_tri": p["nom_tri"], "groupe": p["groupe"],
                                 "departement": p["departement"], "total_eur": B.eur(p["total"]),
                                 "lignes": p["lignes"], "beneficiaires_nommes": p["nommes"],
                                 "agreges": {"lignes": p["agreges"]["lignes"],
                                             "montant_eur": B.eur(p["agreges"]["montant"]),
                                             "dont_personnes_physiques_eur": B.eur(p["agreges"]["pp"])}})
        import vie_politique as vp
        sortie_parls.sort(key=lambda p: (vp.cle_alpha(p["nom_tri"]), vp.cle_alpha(p["parlementaire"])))
        agrege = tot["total"] - tot["nommes"]
        obj = {"millesime": f"Réserve parlementaire {a}",
               "source": " ; ".join([SOURCE_AN if ass == "an" else SOURCE_SENAT, "data.gouv.fr DGCL table SIREN / "
                                     "code Insee des communes", SOURCE_JAUNES, SOURCE_SIRENE, SOURCE_API]),
               "assemblee": "Assemblée nationale" if ass == "an" else "Sénat", "annee": a,
               "unite": "euros (subventions attribuées au titre de la réserve parlementaire)",
               "regle": REGLE_PERSONNES, "regle_parlementaires": REGLE_PARLEMENTAIRES, "ordre": ORDRE_RESERVE,
               "methode": ("Bénéficiaire nommé seulement s'il est apparié à une personne morale : commune du département "
                           "du parlementaire (table SIREN / Insee de la DGCL, nom identique), ou même programme et même "
                           "montant dans le jaune associations de l'année avec un nom proche (indice de Jaccard sur les "
                           "mots au moins 0,5, candidat unique), ou API Recherche d'entreprises (nom identique ou indice "
                           "au moins 0,75 dans le département, candidat unique, catégorie juridique 7xxx à 9xxx : "
                           "organismes publics, associations, fondations). Le descriptif passe le filtre de noms de "
                           "personnes et d'adresses (null s'il en contient un possible)."),
               "colonnes_beneficiaires": ["siren", "denomination", "categorie_juridique", "rna", "programme",
                                          "montant_eur", "descriptif", "methode_appariement"],
               "total_eur": B.eur(tot["total"]), "lignes": tot["lignes"],
               "nommes_eur": B.eur(tot["nommes"]), "lignes_nommees": tot["lignes_nommees"],
               "agreges_eur": B.eur(agrege),
               "agreges": {"non_apparies_eur": B.eur(tot["non_apparies"]),
                           "dont_personnes_physiques_eur": B.eur(tot["pp"]),
                           "non_verifies_eur": B.eur(tot["non_verifies"]),
                           "parlementaires_non_nommes_eur": B.eur(non_nommes["total"])},
               "part_agregee_pct": round(agrege / tot["total"] * 100, 2) if tot["total"] else None,
               "appariements": dict(sorted(methodes.items())),
               "par_programme": [{"programme": None if k == "inconnu" else k, "total_eur": B.eur(v["total"]),
                                  "nommes_eur": B.eur(v["nommes"]), "lignes": v["lignes"]}
                                 for k, v in sorted(progs.items())],
               "parlementaires_non_nommes": {
                   "nombre": len(non_nommes["cles"]), "total_eur": B.eur(non_nommes["total"]),
                   "lignes": non_nommes["lignes"],
                   "raison": ("Parlementaires par ailleurs candidats à un scrutin national (présidentielle, tête de "
                              "liste européenne) : la règle du site ne nomme ces candidats que dans les comptes de "
                              "campagne (vie_politique/candidats/). Leurs attributions restent comptées dans les "
                              "totaux et par programme, sans détail.")},
               "parlementaires": sortie_parls}
        nom = f"{ass}_{a}.json"
        ecrire(d / nom, obj)
        stats[nom] = {"assemblee": obj["assemblee"], "annee": a, "total_eur": obj["total_eur"],
                      "nommes_eur": obj["nommes_eur"], "agreges_eur": obj["agreges_eur"],
                      "part_agregee_pct": obj["part_agregee_pct"], "parlementaires": len(sortie_parls),
                      "parlementaires_non_nommes": len(non_nommes["cles"]),
                      "fichier": f"associations/reserve/{nom}"}
    return stats


# --- 6. Production -----------------------------------------------------------------------------------------------------


def preparer_sirene() -> dict:
    js = jaunes()
    rnf = lire_rnf()
    communes, _ = communes_par_departement()
    ext = extrait_sirene(sirens_a_verifier(js, rnf, communes))
    prenoms()
    return ext


def produire(sortie: Path = SITE / "associations") -> dict:
    js = jaunes()
    rnf = lire_rnf()
    communes, _ = communes_par_departement()
    ext = extrait_sirene(sirens_a_verifier(js, rnf, communes))
    liste = prenoms()
    sortie.mkdir(parents=True, exist_ok=True)
    ser = produire_serie(js, ext, sortie)
    st_rnf = produire_rnf(rnf, ext, liste, sortie)
    st_res = produire_reserve(reserves(), js, ext, liste, sortie)
    annees = []
    for a in ANNEES:
        if a in INEXPLOITABLES:
            annees.append({"annee": a, "annee_credits": ser["credits"][a], "statut": NC, "total_source_eur": NC,
                           "nommes_eur": NC, "exclus_personnes_physiques_ou_non_identifies_eur": NC,
                           "non_verifies_eur": NC, "associations_nommees": NC, "lignes_source": NC,
                           "raison": INEXPLOITABLES[a], "jeu_datagouv": DATAGOUV[a]})
            continue
        t = ser["totaux"][a]
        annees.append({"annee": a, "annee_credits": ser["credits"][a], "statut": "publie",
                       **({"correction": js[a]["correction"]} if "correction" in js[a] else {}),
                       **({"total_publie_par_la_source_eur": B.eur(js[a]["total_publie"])} if "total_publie" in js[a]
                          else {}),
                       "total_source_eur": B.eur(t["total"]), "nommes_eur": B.eur(t["nommes"]),
                       "exclus_personnes_physiques_ou_non_identifies_eur": B.eur(t["pp"] + t["ni"] + t["nom"]),
                       "dont_personnes_physiques_eur": B.eur(t["pp"]),
                       "dont_denomination_nominative_eur": B.eur(t["nom"]), "non_verifies_eur": B.eur(t["nv"]),
                       "sans_programme_eur": B.eur(t["sans_programme"]),
                       "associations_nommees": len(t["assoc"]), "lignes_source": t["lignes"],
                       "jeu_datagouv": DATAGOUV[a]})
    collecte = date_sources("associations")
    ecrire(sortie / "index.json", {
        "millesime": f"Jaunes associations PLF 2012 à 2025 ; RNF au 01/11/2026 ; réserve parlementaire 2013-2017",
        "source": "pipeline/associations.py ; " + " ; ".join([SOURCE_JAUNES, SOURCE_RNF, SOURCE_AN, SOURCE_SENAT,
                                                               SOURCE_SIRENE, SOURCE_API]),
        "collecte_le": collecte,
        "unite": "euros",
        "regle": REGLE_PERSONNES, "regle_parlementaires": REGLE_PARLEMENTAIRES,
        "note": ("Année = année du projet de loi de finances (PLF) ; les crédits listés ont été versés deux ans avant "
                 "(annee_credits). Les listes des jaunes ne sont pas homogènes d'une année à l'autre (périmètre, "
                 "colonnes, programmes renumérotés) : la série juxtapose les montants publiés, sans retraitement."),
        "annees": annees,
        "associations_nommees": len(ser["nommees"]),
        "programmes": ser["programmes"],
        "fonds_fondations": {"fichier": "associations/fonds_fondations.json", **st_rnf},
        "reserve": sorted(st_res.values(), key=lambda x: (x["assemblee"], x["annee"])),
        "sources_inaccessibles": [{"annee": a, "constat": r} for a, r in sorted(INEXPLOITABLES.items())],
        "recherche_publique": RECHERCHE_PUBLIQUE,
    })
    return {"annees": {x["annee"]: x["total_source_eur"] for x in annees}, "nommees": len(ser["nommees"]),
            "rnf": st_rnf, "reserve": st_res}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", choices=["sirene", "apparier", "produire", "tout"])
    ap.add_argument("--budget", type=float, default=600, help="durée max des appels API (s)")
    ap.add_argument("--sortie", type=Path, default=SITE / "associations")
    args = ap.parse_args()
    if args.etape == "sirene":
        ext = preparer_sirene()
        print(f"extrait SIRENE : {len(ext)} SIREN")
    elif args.etape == "apparier":
        apparier(args.budget)
    else:
        if args.etape == "tout":
            preparer_sirene()
        r = produire(args.sortie)
        print(json.dumps(r, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main()
