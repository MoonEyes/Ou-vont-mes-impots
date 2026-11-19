"""« Ma commune » : retrouver sa commune par son code postal ou son nom, sans requête réseau externe.

Table de correspondance code postal -> commune (code Insee) et index des noms, découpés en petits fichiers chargés à
la demande par l'écran /local/ma-commune (web/src/ecrans/ma_commune.ts). Aucun montant ici : la page de synthèse
assemble les fichiers déjà publiés (local/, local/fonctions/, typologies/, deliberations/, local/decisions/,
fonds_europeens/, projets_subventionnes/, territoires/).

Entrées :
  data/lake/ma_commune/ma_commune_codes_postaux.csv   La Poste, base officielle des codes postaux (HexaSmal),
                                                       Licence Ouverte 2.0, collectée par collecte/collecte.py
                                                       (identifiant `ma_commune_codes_postaux` du catalogue,
                                                       contrôle collecte/integrite.py)
  lecture seule : site/data/local/geo/<dep>.json (code officiel géographique en vigueur, population municipale)
Sorties (site/data/ma_commune/, chaque fichier < 1 Mo, avec `millesime` et `source`) :
  index.json            couverture, règles de normalisation, liste des fichiers, arrondissements, hors périmètre
  cp/<2 chiffres>.json  par code postal : communes desservies [insee, nom, département, population, précision]
  noms/<clé>.json       par première lettre (ou deux premières lettres si la lettre est très fournie) du nom
                        normalisé : [clé, insee, nom affiché, département, population, codes postaux, type]

Cas particuliers :
  - code postal partagé par plusieurs communes : toutes listées (l'écran demande de choisir) ;
  - commune avec plusieurs codes postaux : tous listés sur l'entrée de nom ;
  - communes nouvelles : la ligne 5 de La Poste porte souvent le nom d'une commune déléguée (ancienne commune) ou
    d'un lieu-dit ; publié comme « localité » rattachée à la commune actuelle (jamais comme une commune) ;
  - Paris, Lyon, Marseille : La Poste donne le code de l'arrondissement municipal (75101 à 75120, 69381 à 69389,
    13201 à 13216) ; ramené à la commune (75056, 69123, 13055), seule à publier des comptes, avec l'arrondissement
    en précision ;
  - collectivités d'outre-mer, Clipperton et Monaco : hors du code géographique de site/data/local, comptés à part.

Commandes :
  python pipeline/ma_commune.py collecter   # réseau : collecte/collecte.py ma_commune_codes_postaux
  python pipeline/ma_commune.py produire    # sans réseau ; --sortie DOSSIER pour une copie de contrôle
  python pipeline/ma_commune.py             # les deux

Sorties identiques octet pour octet sur le même entrepôt (tris explicites, date par pipeline/reproductible.py).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
SITE = ROOT / "site" / "data"
GEO = SITE / "local" / "geo"
SORTIE_DEFAUT = SITE / "ma_commune"
ID_CP = "ma_commune_codes_postaux"
F_CP = LAKE / "ma_commune" / f"{ID_CP}.csv"
MAX_OCTETS = 1_000_000
SEUIL_DECOUPE = 2500   # au-delà, une lettre est découpée en clés de deux lettres

URL_JEU = "https://www.data.gouv.fr/datasets/base-officielle-des-codes-postaux/"
URL_CSV = "https://data.laposte.fr/data-fair/api/v1/datasets/laposte-hexasmal/raw"
SOURCE = ("La Poste, base officielle des codes postaux (data.laposte.fr, jeu laposte-hexasmal, Licence Ouverte 2.0) ; "
          "Insee, code officiel géographique et population municipale (site/data/local/geo, geo.api.gouv.fr)")

PLM = {  # commune -> (préfixe des codes d'arrondissement, nombre)
    "75056": ("751", 20, "Paris"),
    "69123": ("6938", 9, "Lyon"),
    "13055": ("132", 16, "Marseille"),
}
COM = {"975": "Saint-Pierre-et-Miquelon", "977": "Saint-Barthélemy", "978": "Saint-Martin",
       "986": "Wallis-et-Futuna", "987": "Polynésie française", "988": "Nouvelle-Calédonie", "989": "Clipperton"}
MOTIF_HORS = ("collectivités d'outre-mer, Clipperton et Monaco : hors du code officiel géographique des communes "
              "dont les comptes sont publiés par la DGFiP et l'OFGL (site/data/local)")

PARTICULES = {"de", "du", "des", "la", "le", "les", "l", "d", "en", "sur", "sous", "et", "aux", "au", "lès", "les"}

RECHERCHE_PUBLIQUE = [
    {"trouvaille": "La Poste, base officielle des codes postaux (data.gouv.fr base-officielle-des-codes-postaux, "
                   "data.laposte.fr laposte-hexasmal)", "verdict": "réutilisable tel quel",
     "licence": "Licence Ouverte 2.0", "date": "fichier mis à jour le 2026-11-17"},
    {"trouvaille": "geo.api.gouv.fr (/communes?codePostal=, champ codesPostaux)", "verdict": "inspiration seulement",
     "licence": "Licence Ouverte 2.0 (données) ; dépôt etalab/decoupage-administratif MIT",
     "date": "dérivé de la même base de La Poste ; non retenu : requête réseau externe à chaque frappe"},
    {"trouvaille": "BaseAdresseNationale/codes-postaux (paquet npm codes-postaux)", "verdict": "inspiration seulement",
     "licence": "MIT (code), Licence Ouverte (données)",
     "date": "même base de La Poste embarquée en un seul fichier (environ 2 Mo) : trop lourd pour une page"},
    {"trouvaille": "site/data/local/geo (déjà publié : communes, intercommunalités, départements, régions)",
     "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "date": "versionné dans le dépôt"},
]


def norm(s: str) -> str:
    """Clé de recherche : sans accents, minuscules, ponctuation en espaces, « st »/« ste » développés.
    Même règle dans web/src/ecrans/ma_commune.ts (normaliser)."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().replace("œ", "oe").replace("æ", "ae")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    mots = [{"st": "saint", "ste": "sainte"}.get(m, m) for m in s.split()]
    return " ".join(mots)


def joli(brut: str) -> str:
    """« ST GEORGES DES GARDES » -> « Saint Georges des Gardes » (nom écrit par La Poste, en capitales sans accents)."""
    mots = norm(brut).split()
    out = []
    for i, m in enumerate(mots):
        out.append(m if i and m in PARTICULES else m[:1].upper() + m[1:])
    return " ".join(out)


def ordinal(n: int) -> str:
    return "1er" if n == 1 else f"{n}e"


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(txt.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets : à découper")
    path.write_text(txt + "\n", encoding="utf-8")
    return n


def fichier_cp() -> Path:
    try:
        m = json.loads((LAKE / "manifest.json").read_text(encoding="utf-8")).get(ID_CP) or {}
    except (OSError, ValueError):
        m = {}
    for f in m.get("fichiers", []):
        if (ROOT / f["chemin"]).exists():
            return ROOT / f["chemin"]
    if F_CP.exists():
        return F_CP
    raise SystemExit(f"{F_CP} absent : lancer python pipeline/ma_commune.py collecter")


def version_source() -> str | None:
    """Date de mise à jour du fichier par La Poste (en-tête Last-Modified relevé par la collecte)."""
    try:
        m = json.loads((LAKE / "manifest.json").read_text(encoding="utf-8")).get(ID_CP) or {}
    except (OSError, ValueError):
        return None
    from email.utils import parsedate_to_datetime
    for f in m.get("fichiers", []):
        if f.get("last_modified"):
            try:
                return parsedate_to_datetime(f["last_modified"]).date().isoformat()
            except (TypeError, ValueError):
                return None
    return None


def lire_cp(chemin: Path) -> list[tuple[str, str, str, str, str]]:
    """Lignes (insee, nom La Poste, code postal, libellé d'acheminement, ligne 5). Fichier en Latin-1, « ; »."""
    octets = chemin.read_bytes()
    try:
        texte = octets.decode("utf-8")
    except UnicodeDecodeError:
        texte = octets.decode("latin-1")
    lignes = []
    lecteur = csv.reader(io.StringIO(texte), delimiter=";")
    entete = next(lecteur)
    if len(entete) < 5 or "insee" not in entete[0].lower():
        raise SystemExit(f"{chemin} : en-tête inattendu {entete}")
    for r in lecteur:
        if len(r) < 5 or not r[0].strip():
            continue
        insee, nom, cp, ach, l5 = (x.strip() for x in r[:5])
        if not re.fullmatch(r"\d{5}", cp) or not re.fullmatch(r"(\d{5}|2[AB]\d{3})", insee):
            continue
        lignes.append((insee, nom, cp, ach, l5))
    return lignes


def lire_geo() -> dict[str, dict]:
    communes = {}
    for f in sorted(GEO.glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        for insee, c in g["communes"].items():
            communes[insee] = {"nom": c["nom"], "dep": c["departement"], "population": c.get("population")}
    if len(communes) < 30000:
        raise SystemExit(f"site/data/local/geo : {len(communes)} communes seulement (lancer pipeline/local.py)")
    return communes


def vers_commune(insee: str) -> tuple[str, str | None]:
    """Code d'arrondissement municipal -> (commune, « 11e arrondissement ») ; sinon (insee, None)."""
    for commune, (prefixe, n, _) in PLM.items():
        if insee.startswith(prefixe) and len(insee) == 5:
            num = int(insee[len(prefixe):]) if commune != "13055" else int(insee[3:])
            if 1 <= num <= n:
                return commune, f"{ordinal(num)} arrondissement"
    return insee, None


def compacte(cle: str) -> str:
    """Clé sans espaces : sert à nommer les fichiers de noms (« l abergement » -> « labergement »)."""
    return cle.replace(" ", "")


def decouper(entrees: list[list]) -> dict[str, list]:
    """Groupes par préfixe de la clé compacte : une lettre, allongée d'un caractère tant que le groupe dépasse
    SEUIL_DECOUPE entrées (un nom plus court que le préfixe reste dans un groupe à son nom exact)."""
    groupes: dict[str, list] = {}

    def ranger(prefixe: str, liste: list[list]) -> None:
        if len(liste) <= SEUIL_DECOUPE or all(len(compacte(e[0])) <= len(prefixe) for e in liste):
            groupes[prefixe] = liste
            return
        sous: dict[str, list] = defaultdict(list)
        for e in liste:
            c = compacte(e[0])
            sous[c[:len(prefixe) + 1]].append(e)
        for p, l in sous.items():
            ranger(p, l)

    racine: dict[str, list] = defaultdict(list)
    for e in entrees:
        racine[compacte(e[0])[:1]].append(e)
    for p, l in racine.items():
        ranger(p, l)
    return groupes


def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    geo = lire_geo()
    lignes = lire_cp(fichier_cp())
    date = date_sources("ma_commune")
    version = version_source()
    millesime = (f"Base officielle des codes postaux de La Poste{f' (version du {version})' if version else ''} ; "
                 "code officiel géographique en vigueur (site/data/local/geo)")

    par_cp: dict[str, dict[str, dict]] = defaultdict(dict)      # cp -> insee -> {arr, localites}
    cps_commune: dict[str, set[str]] = defaultdict(set)
    localites: dict[tuple[str, str], dict] = {}                 # (insee, clé) -> {nom, cps}
    hors: dict[str, set[str]] = defaultdict(set)                # motif -> codes postaux
    inconnus: set[str] = set()
    for insee_brut, nom_lp, cp, ach, l5 in lignes:
        if insee_brut[:3] in COM or insee_brut.startswith("99"):
            hors[COM.get(insee_brut[:3], "Monaco")].add(cp)
            continue
        insee, arr = vers_commune(insee_brut)
        if insee not in geo:
            inconnus.add(insee_brut)
            continue
        e = par_cp[cp].setdefault(insee, {"arr": set(), "loc": set()})
        cps_commune[insee].add(cp)
        if arr:
            e["arr"].add(arr)
        c = geo[insee]
        cle_commune = norm(c["nom"])
        for brut in (l5,):
            if not brut:
                continue
            k = norm(brut)
            if not k or k == cle_commune:
                continue
            e["loc"].add(joli(brut))
            loc = localites.setdefault((insee, k), {"nom": joli(brut), "cps": set(), "type": "localite"})
            loc["cps"].add(cp)
        if arr:
            k = norm(f"{PLM[insee][2]} {arr}")
            loc = localites.setdefault((insee, k), {"nom": f"{PLM[insee][2]} {arr}", "cps": set(),
                                                    "type": "arrondissement"})
            loc["cps"].add(cp)
    if inconnus:
        raise SystemExit(f"codes Insee de La Poste absents du code géographique : {sorted(inconnus)[:20]} "
                         "(relancer pipeline/local.py ou vérifier la version de la base)")

    # --- codes postaux, par deux premiers chiffres -------------------------------------------------------------------
    fichiers_cp: dict[str, dict] = defaultdict(dict)
    for cp in sorted(par_cp):
        entrees = []
        for insee in sorted(par_cp[cp]):
            e, c = par_cp[cp][insee], geo[insee]
            precision = None
            if e["arr"]:
                precision = ", ".join(sorted(e["arr"], key=lambda a: int(re.match(r"\d+", a).group())))
            elif e["loc"]:
                precision = ", ".join(sorted(e["loc"]))
            entrees.append([insee, c["nom"], c["dep"], c["population"], precision])
        fichiers_cp[cp[:2]][cp] = entrees
    tailles = {}
    for prefixe, contenu in sorted(fichiers_cp.items()):
        tailles[f"cp/{prefixe}.json"] = dump(sortie / "cp" / f"{prefixe}.json", {
            "millesime": millesime, "source": SOURCE, "date_sources": date, "prefixe": prefixe,
            "colonnes": ["insee", "nom", "departement", "population", "precision"],
            "codes_postaux": contenu})

    # --- noms -----------------------------------------------------------------------------------------------------
    entrees_noms = []
    for insee, c in geo.items():
        cps = " ".join(sorted(cps_commune.get(insee, ())))
        entrees_noms.append([norm(c["nom"]), insee, c["nom"], c["dep"], c["population"], cps, "commune"])
    for (insee, k), loc in localites.items():
        c = geo[insee]
        entrees_noms.append([k, insee, loc["nom"], c["dep"], c["population"], " ".join(sorted(loc["cps"])),
                             loc["type"]])
    entrees_noms.sort(key=lambda e: (e[0], e[6], e[3], e[1]))
    groupes = decouper(entrees_noms)
    for cle, contenu in sorted(groupes.items()):
        tailles[f"noms/{cle}.json"] = dump(sortie / "noms" / f"{cle}.json", {
            "millesime": millesime, "source": SOURCE, "date_sources": date, "cle": cle,
            "colonnes": ["insee", "nom", "departement", "population", "codes_postaux", "type"],
            "noms": [e[1:] for e in contenu]})

    communes_multi_cp = sum(1 for v in cps_commune.values() if len(v) > 1)
    partages = {cp: len(v) for cp, v in par_cp.items() if len(v) > 1}
    index = {
        "millesime": millesime,
        "source": SOURCE,
        "url": URL_JEU,
        "url_fichier": URL_CSV,
        "licence": "Licence Ouverte 2.0",
        "date_sources": date,
        "version_source": version,
        "presentation": ("Retrouver sa commune par son code postal ou son nom. La correspondance vient de la base "
                         "officielle des codes postaux de La Poste ; les communes, leur département et leur "
                         "population viennent du code officiel géographique de l'Insee."),
        "normalisation": ("nom sans accents, en minuscules, ponctuation et traits d'union remplacés par des espaces, "
                          "« st » et « ste » écrits « saint » et « sainte » ; même règle à l'écran"),
        "fichiers": {"cp": "ma_commune/cp/<deux premiers chiffres du code postal>.json",
                     "noms": "ma_commune/noms/<préfixe de la clé compacte>.json"},
        "prefixes_cp": sorted(fichiers_cp),
        "cles_noms": sorted(groupes),
        "regle_cles": ("fichier de noms = plus long préfixe de la clé compacte (clé normalisée sans espaces) présent "
                       "dans `cles_noms` ; une saisie plus courte que ce préfixe attend une lettre de plus"),
        "couverture": {
            "communes_cog": len(geo),
            "communes_avec_code_postal": len(cps_commune),
            "communes_sans_code_postal": sorted(set(geo) - set(cps_commune)),
            "codes_postaux": len(par_cp),
            "codes_postaux_partages": len(partages),
            "communes_max_par_code_postal": max(partages.values()) if partages else 1,
            "communes_plusieurs_codes_postaux": communes_multi_cp,
            "localites": sum(1 for v in localites.values() if v["type"] == "localite"),
            "arrondissements": sum(1 for v in localites.values() if v["type"] == "arrondissement"),
            "lignes_source": len(lignes),
        },
        "arrondissements": {
            c: {"nom": nom, "arrondissements": n,
                "note": (f"La Poste rattache chaque code postal de {nom} à un arrondissement municipal ; seule la "
                         f"commune de {nom} publie des comptes (les arrondissements n'ont pas de budget propre "
                         "publié en données ouvertes) : le code postal mène à la commune, l'arrondissement est "
                         "indiqué en précision.")}
            for c, (_, n, nom) in sorted(PLM.items())},
        "hors_perimetre": {
            "motif": MOTIF_HORS,
            "territoires": {t: sorted(v) for t, v in sorted(hors.items())},
            "codes_postaux": sum(len(v) for v in hors.values()),
        },
        "regles": [
            "Code postal partagé par plusieurs communes : toutes sont proposées, l'écran demande de choisir.",
            "Localité (ligne 5 de La Poste) : nom d'une commune déléguée, d'une ancienne commune ou d'un lieu-dit ; "
            "proposée sous son nom écrit par La Poste (capitales sans accents remises en minuscules) et rattachée à "
            "la commune actuelle, jamais présentée comme une commune.",
            "Ordre des propositions à l'écran : nom identique, puis nom qui commence par la saisie, puis nom qui la "
            "contient ; dans chaque groupe, ordre alphabétique puis numéro du département. Aucun classement.",
            "Aucune requête réseau hors du site : les fichiers sont lus dans data/ma_commune/ au fil de la saisie.",
        ],
        "limites": [
            "Un code postal ne suit pas les limites des communes : il désigne une zone de distribution du courrier.",
            "La base de La Poste peut avoir quelques semaines de décalage avec le code officiel géographique après "
            "une fusion de communes ; une commune absente de la base de La Poste reste trouvable par son nom.",
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "tailles_octets": {"max": max(tailles.values()), "fichiers": len(tailles)},
        "ordre": "codes postaux et clés par ordre croissant ; communes par code Insee ; noms par clé, type, "
                 "département, code Insee",
    }
    dump(sortie / "index.json", index)
    return index


def collecter() -> int:
    return subprocess.call([sys.executable, str(ROOT / "collecte" / "collecte.py"), ID_CP])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        rc = collecter()
        if rc:
            raise SystemExit(rc)
    if a.etape in ("produire", "tout"):
        i = produire(a.sortie)
        c = i["couverture"]
        print(f"ma_commune : {c['communes_avec_code_postal']}/{c['communes_cog']} communes, {c['codes_postaux']} codes "
              f"postaux ({c['codes_postaux_partages']} partagés), {c['localites']} localités, "
              f"{i['hors_perimetre']['codes_postaux']} codes hors périmètre", file=sys.stderr)


if __name__ == "__main__":
    main()
