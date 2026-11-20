"""Jurisprudence administrative (DILA, base JADE) : nombres de décisions, jamais leur texte.

La base JADE de la DILA publie les décisions du Conseil d'État, des cours administratives d'appel et du Tribunal des
conflits. Ce module n'en garde que des métadonnées de classement, puis publie des comptes :

  - par juridiction et par année de décision ;
  - par matière, d'après le plan de classement du Conseil d'État (code « SCT » des décisions analysées, publiées au
    Recueil Lebon ou mentionnées dans ses tables) : matière fiscale (« 19 Contributions et taxes ») et matière
    budgétaire et comptable (« 18 Comptabilité publique et budget »), avec les autres matières pour comparaison ;
  - pour les décisions analysées en matière fiscale ou budgétaire : juridiction, date, numéro et lien vers la décision
    sur Légifrance, rien d'autre.

Confidentialité. Les décisions sont pseudonymisées par la DILA, mais leur texte peut encore citer des personnes
(parties, avocats, magistrats). Aucun texte n'est lu au-delà de l'en-tête de classement : ni le contenu, ni les
champs PRESIDENT, AVOCATS, RAPPORTEUR, COMMISSAIRE_GVT, DEMANDEUR, DEFENDEUR, ni le texte des analyses (seul le code
de classement, par exemple « 19-04-02-01 », est gardé). Le titre officiel d'une décision (juridiction, formation, date,
numéro) ne contient aucun nom.

Entrées (data/lake/jurisprudence/, hors git) :
  jade_meta.csv.gz   une ligne par décision : identifiant, juridiction, date, numéro, type de recours, solution,
                     formation, publication au Recueil, codes de classement (sans libellé ni texte) ;
                     extrait en flux de l'archive complète Freemium_jade_global_<date>.tar.gz (1,2 Go, jamais écrite
                     sur disque) puis des flux quotidiens JADE_<date>.tar.gz qui la suivent (entrée
                     `decisions_jade_increments` du catalogue), suppressions de la DILA appliquées.
  jade_plan.json     libellés des deux premiers niveaux du plan de classement, lus dans les analyses.

Commandes :
  python pipeline/jurisprudence.py collecter   # réseau : https://echanges.dila.gouv.fr/OPENDATA/JADE/
  python pipeline/jurisprudence.py produire    # sans réseau -> site/data/jurisprudence/
Sorties reproductibles octet pour octet (tris explicites, date de collecte lue dans le manifeste de l'entrepôt).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import tarfile
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "collecte"))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake" / "jurisprudence"
SITE = ROOT / "site" / "data"
SORTIE_DEFAUT = SITE / "jurisprudence"
META = LAKE / "jade_meta.csv.gz"
PLAN = LAKE / "jade_plan.json"
JOURNAL = LAKE / "collecte.json"
MANIFESTE = ROOT / "data" / "lake" / "manifest.json"

BASE = "https://echanges.dila.gouv.fr/OPENDATA/JADE/"
PAGE = "https://www.data.gouv.fr/datasets/jade/"
LEGIFRANCE = "https://www.legifrance.gouv.fr/ceta/id/"
LICENCE = "Licence Ouverte 2.0"
MAX_OCTETS = 1_000_000
ANNEE_MIN = 1965   # avant 1965, la base ne compte que quelques décisions par an (reprises au cas par cas)

COLONNES = ["id", "origine", "juridiction", "date", "numero", "type_recours", "solution", "formation", "recueil",
            "codes"]

# Matières suivies (premier niveau du plan de classement de la jurisprudence administrative du Conseil d'État).
MATIERES = {
    "19": "fiscale",
    "18": "budgetaire",
}
LIBELLES_MATIERES = {
    "fiscale": "Matière fiscale : « Contributions et taxes » (rubrique 19 du plan de classement)",
    "budgetaire": "Matière budgétaire et comptable : « Comptabilité publique et budget » (rubrique 18 du plan de "
                  "classement)",
}

RECHERCHE_PUBLIQUE = [
    {"trouvaille": "DILA, base JADE (echanges.dila.gouv.fr/OPENDATA/JADE, fiche data.gouv.fr « JADE »)",
     "verdict": "réutilisable tel quel", "licence": LICENCE,
     "date": "archive complète du 08/11/2026 et flux quotidiens jusqu'au 19/11/2026"},
    {"trouvaille": "Judilibre (API de la Cour de cassation)", "verdict": "inspiration seulement",
     "licence": LICENCE, "date": "juridictions judiciaires seulement ; compte d'accès requis (PISTE)"},
    {"trouvaille": "Conseil d'État, open data des décisions des juridictions administratives "
                   "(opendata.justice-administrative.fr)", "verdict": "à adapter",
     "licence": LICENCE, "date": "inclut les tribunaux administratifs ; non repris ici (volume, mêmes règles de "
                                 "pseudonymisation) : piste pour une version suivante"},
    {"trouvaille": "pylegifrance, dépôts GitHub d'analyse de JADE (scripts XML vers CSV)",
     "verdict": "inspiration seulement", "licence": "variable (MIT, GPL)",
     "date": "lecture de l'en-tête XML réécrite ici en bibliothèque standard, sans texte de décision"},
]

_CHAMPS = {
    "id": re.compile(r"<ID>([^<]*)</ID>"),
    "origine": re.compile(r"<ORIGINE>([^<]*)</ORIGINE>"),
    "juridiction": re.compile(r"<JURIDICTION>([^<]*)</JURIDICTION>"),
    "date": re.compile(r"<DATE_DEC>([^<]*)</DATE_DEC>"),
    "numero": re.compile(r"<NUMERO>([^<]*)</NUMERO>"),
    "type_recours": re.compile(r"<TYPE_REC>([^<]*)</TYPE_REC>"),
    "solution": re.compile(r"<SOLUTION>([^<]*)</SOLUTION>"),
    "formation": re.compile(r"<FORMATION>([^<]*)</FORMATION>"),
    "recueil": re.compile(r"<PUBLI_RECUEIL>([^<]*)</PUBLI_RECUEIL>"),
}
_SCT = re.compile(r"<SCT\b[^>]*>\s*(\d{2,3}(?:-\d{2,3})*)\s+([^<]{0,400})")


def _propre(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def lire_xml(octets: bytes) -> tuple[dict, list[tuple[str, str]]]:
    """En-tête de classement d'une décision ; renvoie aussi (code, libellé) des deux premiers niveaux du plan.

    Seuls les champs listés dans _CHAMPS sont lus ; le texte de la décision et les noms (président, avocats,
    rapporteur, commissaire du Gouvernement, parties) ne le sont jamais.
    """
    tete = octets.split(b"</META>", 1)[0].decode("utf-8", "replace")
    ligne = {k: _propre(m.group(1)) if (m := r.search(tete)) else "" for k, r in _CHAMPS.items()}
    codes, plan = [], []
    for m in _SCT.finditer(octets.decode("utf-8", "replace")):
        code = m.group(1)
        codes.append(code)
        segments = [s.strip(" .") for s in re.split(r"\s+-\s*|\.\s+-\s*", m.group(2))]
        parties = code.split("-")
        for niveau in (1, 2):
            if len(parties) >= niveau and len(segments) >= niveau:
                lib = segments[niveau - 1]
                # libellé du plan : capitales seulement (au-delà commence le résumé, jamais repris)
                if lib and lib == lib.upper() and len(lib) <= 120 and not re.search(r"\d{4}", lib):
                    plan.append(("-".join(parties[:niveau]), lib))
    ligne["codes"] = "|".join(dict.fromkeys(codes))
    return ligne, plan


# --------------------------------------------------------------------------------------------------------------
# Collecte (réseau)
# --------------------------------------------------------------------------------------------------------------

def _get(url: str, stream: bool = False, essais: int = 4):
    import requests
    erreur = None
    for i in range(1, essais + 1):
        try:
            r = requests.get(url, timeout=300, stream=stream,
                             headers={"User-Agent": "ou-vont-mes-impots (collecte open data)"})
        except (requests.ConnectionError, requests.Timeout) as exc:
            erreur = exc
        else:
            if r.status_code in (401, 403, 429):
                raise RuntimeError(f"accès refusé HTTP {r.status_code} sur {url} (non contourné)")
            if r.status_code < 400:
                return r
            erreur = f"HTTP {r.status_code}"
        if i < essais:
            time.sleep(5 * i)
    raise RuntimeError(f"{url} : {erreur}")


def lister() -> tuple[str, list[str]]:
    page = _get(BASE).text
    noms = sorted(set(re.findall(r'href="([^"?/]+\.tar\.gz)"', page)))
    globales = [n for n in noms if n.startswith("Freemium_jade_global_")]
    if not globales:
        raise RuntimeError("archive complète Freemium_jade_global absente de l'index DILA")
    globale = globales[-1]
    date_g = re.search(r"(\d{8}-\d{6})", globale).group(1)
    increments = [n for n in noms if n.startswith("JADE_") and re.search(r"(\d{8}-\d{6})", n).group(1) > date_g]
    return globale, increments


class _Compteur(io.RawIOBase):
    """Flux de réponse qui compte les octets lus (contrôle de complétude contre Content-Length)."""

    def __init__(self, brut):
        self.brut, self.n = brut, 0

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        d = self.brut.read(len(b))
        n = len(d)
        b[:n] = d
        self.n += n
        return n


def extraire_archive(url: str, lignes: dict, plan: Counter, suppressions: set) -> int:
    """Lit une archive .tar.gz en flux (jamais écrite sur disque) ; renvoie le nombre de décisions lues."""
    from integrite import IntegriteInvalide
    r = _get(url, stream=True)
    attendu = int(r.headers.get("Content-Length") or 0) or None
    flux = _Compteur(r.raw)
    n = 0
    with tarfile.open(fileobj=io.BufferedReader(flux, 1 << 20), mode="r|gz") as tar:
        for membre in tar:
            if not membre.isfile():
                continue
            nom = membre.name
            if nom.endswith(".dat") and "suppression" in nom:
                for l in tar.extractfile(membre).read().decode("utf-8", "replace").splitlines():
                    m = re.search(r"([A-Z]+TEXT\d{12})", l)
                    if m:
                        suppressions.add(m.group(1))
                continue
            if not nom.endswith(".xml"):
                continue
            ligne, p = lire_xml(tar.extractfile(membre).read())
            if not ligne["id"]:
                continue
            lignes[ligne["id"]] = ligne
            plan.update(p)
            n += 1
            if n % 50000 == 0:
                print(f"    {n} décisions lues", file=sys.stderr, flush=True)
    if attendu and flux.n != attendu:
        raise IntegriteInvalide(f"{url} : {flux.n} octets reçus pour {attendu} annoncés (archive tronquée)")
    return n


def collecter() -> None:
    from integrite import remplacer_si_valide
    LAKE.mkdir(parents=True, exist_ok=True)
    globale, increments = lister()
    lignes: dict[str, dict] = {}
    plan: Counter = Counter()
    suppressions: set[str] = set()
    journal = {"archive_complete": BASE + globale, "increments": [], "collecte_le": None}
    print(f"  {globale} (flux)", file=sys.stderr)
    journal["decisions_archive_complete"] = extraire_archive(BASE + globale, lignes, plan, suppressions)
    for nom in increments:
        n = extraire_archive(BASE + nom, lignes, plan, suppressions)
        journal["increments"].append({"fichier": BASE + nom, "decisions": n})
    for i in suppressions:
        lignes.pop(i, None)
    journal["suppressions_appliquees"] = len(suppressions)
    journal["decisions"] = len(lignes)
    tmp = META.with_suffix(".gz.part")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES, lineterminator="\n")
        w.writeheader()
        for k in sorted(lignes):
            w.writerow(lignes[k])
    remplacer_si_valide(tmp, META, nom=META.name)
    libelles: dict[str, str] = {}
    for (code, lib), _n in sorted(plan.items(), key=lambda kv: (kv[0][0], -kv[1], kv[0][1])):
        libelles.setdefault(code, lib)
    PLAN.write_text(json.dumps(libelles, ensure_ascii=False, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    journal["collecte_le"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    JOURNAL.write_text(json.dumps(journal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    _manifeste(journal)
    print(f"  {len(lignes)} décisions, {len(libelles)} rubriques du plan", file=sys.stderr)


def _manifeste(journal: dict) -> None:
    """Trace la collecte dans data/lake/manifest.json (entrée `jurisprudence_jade`, date relue par reproductible)."""
    import fcntl
    MANIFESTE.parent.mkdir(parents=True, exist_ok=True)
    with open(str(MANIFESTE) + ".lock", "w") as verrou:
        fcntl.flock(verrou, fcntl.LOCK_EX)
        try:
            m = json.loads(MANIFESTE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            m = {}
        m["jurisprudence_jade"] = {
            "collecte_le": journal["collecte_le"], "domaine": "jurisprudence", "statut": "ok",
            "titre": "Jurisprudence administrative (DILA JADE), métadonnées de classement extraites en flux",
            "licence": LICENCE, "personnes_physiques": False,
            "fichiers": [{"chemin": str(META.relative_to(ROOT)), "url": journal["archive_complete"],
                          "lignes": journal["decisions"]}],
        }
        MANIFESTE.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------------------------------
# Production (sans réseau)
# --------------------------------------------------------------------------------------------------------------

def _sans_accent(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


CORRECTIONS_VILLES = {"versailless": "versailles"}   # coquille de la base relevée le 20/11/2026


def juridiction(brut: str) -> str:
    """Nom normalisé : les variantes d'écriture de la base (« CAA de PARIS », « COUR ADMINISTRATIVE D'APPEL DE
    LYON », « Conseil d'Etat ») ramenées à une seule forme."""
    t = _propre(brut)
    b = _sans_accent(t).lower().replace("’", "'")
    if b.startswith("conseil d'etat"):
        return "Conseil d'État"
    if b.startswith("tribunal des conflits"):
        return "Tribunal des conflits"
    m = re.match(r"^(?:caa|cour administrative d'appel)(?: de | d')?\s*(.*)$", b)
    if m:
        ville = CORRECTIONS_VILLES.get(m.group(1).strip(), m.group(1).strip())
        if not ville:
            return "Cour administrative d'appel (ville non précisée)"
        return "Cour administrative d'appel de " + "-".join(x[:1].upper() + x[1:] for x in ville.split("-"))
    m = re.match(r"^tribunal administratif (?:de |d'|du )?\s*(.*)$", t, re.I)
    if m and m.group(1):
        ville = re.split(r"\s+ordonnance\b", m.group(1).strip(), flags=re.I)[0]
        ville = ville.title().replace(" De ", " de ").replace(" La ", " la ").replace("-En-", "-en-")
        return "Tribunal administratif " + ("d'" if _sans_accent(ville[:1]).lower() in "aeiouy" else "de ") + ville
    return t or "juridiction non précisée"


def matieres(codes: str, type_recours: str) -> dict:
    liste = [c for c in codes.split("|") if c]
    premiers = {c.split("-")[0] for c in liste}
    return {"classee": bool(liste), "fiscale_classement": "19" in premiers, "budgetaire_classement": "18" in premiers,
            "fiscale_type_recours": "fiscal" in _sans_accent(type_recours).lower(), "rubriques": premiers}


def _lire_meta() -> list[dict]:
    if not META.exists():
        raise SystemExit(f"{META} absent : lancer python pipeline/jurisprudence.py collecter")
    with gzip.open(META, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _date_collecte() -> str:
    try:
        return json.loads(JOURNAL.read_text(encoding="utf-8"))["collecte_le"][:10]
    except (OSError, ValueError, KeyError, TypeError):
        return date_sources("jurisprudence")


def dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    n = len(txt.encode("utf-8"))
    if n > MAX_OCTETS:
        raise SystemExit(f"{path} dépasse {MAX_OCTETS} octets : à découper")
    path.write_text(txt + "\n", encoding="utf-8")
    return n


def produire(sortie: Path = SORTIE_DEFAUT) -> dict:
    lignes = _lire_meta()
    date = date_sources("jurisprudence")
    collecte = json.loads(JOURNAL.read_text(encoding="utf-8")) if JOURNAL.exists() else {}
    plan = json.loads(PLAN.read_text(encoding="utf-8")) if PLAN.exists() else {}
    annee_max = int(date[:4])
    comptes: dict[tuple, Counter] = defaultdict(Counter)
    rubriques: dict[tuple, int] = Counter()
    liens: dict[int, list] = defaultdict(list)
    hors_periode, sans_date = 0, 0
    juridictions = set()
    for r in lignes:
        an = int(r["date"][:4]) if re.match(r"^\d{4}-\d{2}-\d{2}$", r["date"] or "") else None
        if an is None or an > annee_max:
            sans_date += 1
            continue
        if an < ANNEE_MIN:
            hors_periode += 1
            continue
        j = juridiction(r["juridiction"])
        juridictions.add(j)
        m = matieres(r["codes"], r["type_recours"])
        c = comptes[(an, j)]
        c["decisions"] += 1
        c["classees"] += m["classee"]
        c["fiscale_classement"] += m["fiscale_classement"]
        c["fiscale_type_recours"] += m["fiscale_type_recours"]
        c["budgetaire_classement"] += m["budgetaire_classement"]
        for rub in m["rubriques"]:
            rubriques[(an, rub)] += 1
        if m["fiscale_classement"] or m["budgetaire_classement"]:
            sous = sorted({"-".join(c.split("-")[:2]) for c in r["codes"].split("|")
                           if c.split("-")[0] in ("18", "19")})
            liens[an].append([r["id"], j, r["date"], _propre(r["numero"]) or None,
                              "fiscale" if m["fiscale_classement"] else "budgetaire", r["recueil"] or None, sous])
    noms_j = sorted(juridictions, key=lambda x: (0 if x.startswith("Conseil") else 2 if x.startswith("Tribunal des")
                                                 else 1, _sans_accent(x).lower()))
    colonnes = ["annee", "juridiction", "decisions", "classees", "fiscale_classement", "fiscale_type_recours",
                "budgetaire_classement"]
    lignes_c = [[an, j, *[comptes[(an, j)][k] for k in colonnes[2:]]] for (an, j) in sorted(comptes)]
    entete = {"millesime": f"décisions de {ANNEE_MIN} à {annee_max}, base JADE au {_date_collecte()}",
              "source": f"DILA, base JADE (jurisprudence administrative), {LICENCE} : {BASE} ; fiche {PAGE}",
              "date_sources": date}
    n_comptes = dump(sortie / "comptes.json", {**entete, "unite": "nombre de décisions", "colonnes": colonnes,
                                               "lignes": lignes_c})
    rub_noms = {k: re.sub(r"^[-\s]+", "", v).capitalize() for k, v in plan.items() if "-" not in k}
    sous_noms = {k: re.sub(r"^[-\s]+", "", v).capitalize() for k, v in plan.items()
                 if k.count("-") == 1 and k.split("-")[0] in ("18", "19")}
    n_rub = dump(sortie / "rubriques.json", {**entete, "unite": "nombre de décisions classées",
                                             "colonnes": ["annee", "rubrique", "decisions"],
                                             "lignes": [[an, rub, n] for (an, rub), n in sorted(rubriques.items())]})
    fichiers_liens = {}
    rang = {j: i for i, j in enumerate(noms_j)}
    for an in sorted(liens):
        l = sorted(([x[0], rang[x[1]], *x[2:]] for x in liens[an]), key=lambda x: (x[2], x[1], x[0]))
        nom = f"decisions/{an}.json"
        fichiers_liens[str(an)] = {"chemin": f"jurisprudence/{nom}", "decisions": len(l),
                                   "octets": dump(sortie / nom, {
                                       **entete, "millesime": f"décisions de {an} classées en matière fiscale ou "
                                                              f"budgétaire, base JADE au {_date_collecte()}",
                                       "annee": an, "lien_modele": LEGIFRANCE + "{id}",
                                       "colonnes": ["id", "juridiction", "date", "numero", "matiere", "recueil",
                                                    "sous_rubriques"],
                                       "juridiction": "rang dans la liste `juridictions` de jurisprudence/index.json",
                                       "decisions": l})}
    index = {
        **entete,
        "licence": LICENCE, "page_source": PAGE, "lien_modele": LEGIFRANCE + "{id}",
        "presentation": "Nombre de décisions de la justice administrative (Conseil d'État, cours administratives "
                        "d'appel, Tribunal des conflits) publiées par la DILA dans la base JADE, par juridiction et "
                        "par année, et nombre de celles qui portent sur l'impôt ou sur le budget et la comptabilité "
                        "publique. Chaque décision fiscale ou budgétaire classée renvoie à son texte sur Légifrance ; "
                        "le site n'en reprend aucun extrait.",
        "matieres": LIBELLES_MATIERES,
        "criteres": {
            "classees": "décisions qui portent au moins un code du plan de classement de la jurisprudence "
                        "administrative (décisions analysées : publiées au Recueil Lebon, mentionnées dans ses "
                        "tables, ou classées par la juridiction)",
            "fiscale_classement": "au moins un code de la rubrique 19 « Contributions et taxes »",
            "budgetaire_classement": "au moins un code de la rubrique 18 « Comptabilité publique et budget »",
            "fiscale_type_recours": "type de recours écrit par la juridiction contenant « fiscal » (par exemple "
                                    "« plein contentieux fiscal ») ; critère publié à côté, jamais additionné au "
                                    "classement",
        },
        "rubriques": dict(sorted(rub_noms.items())),
        "sous_rubriques": dict(sorted(sous_noms.items())),
        "juridictions": noms_j,
        "couverture": {"decisions_lues": len(lignes), "decisions_publiees": sum(x[2] for x in lignes_c),
                       "avant_annee_min": hors_periode, "date_absente_ou_invalide": sans_date,
                       "annee_min": ANNEE_MIN, "annee_max": max(a for a, _ in comptes),
                       "archive_complete": collecte.get("archive_complete"),
                       "increments": len(collecte.get("increments", [])),
                       "suppressions_appliquees": collecte.get("suppressions_appliquees"),
                       "collecte_le": _date_collecte()},
        "fichiers": {"comptes": {"chemin": "jurisprudence/comptes.json", "octets": n_comptes},
                     "rubriques": {"chemin": "jurisprudence/rubriques.json", "octets": n_rub},
                     "decisions": fichiers_liens},
        "manques": [{
            "quoi": "Les décisions des tribunaux administratifs (premier degré) et le texte des décisions.",
            "pourquoi": "La base JADE reprend surtout le Conseil d'État et les cours administratives d'appel. Le texte "
                        "des décisions peut encore citer des personnes malgré la pseudonymisation : le site ne publie "
                        "que des nombres et des liens vers Légifrance.",
            "depuis": f"Constat de la collecte du {_date_collecte()}.",
            "source": {"libelle": "Base JADE (DILA)", "url": PAGE},
        }],
        "regles": [
            "Aucun texte de décision, aucun nom de partie, d'avocat ou de magistrat : seuls l'identifiant, la "
            "juridiction, la date, le numéro et les codes de classement sont lus.",
            "Un nombre est un comptage de décisions publiées dans la base, pas un nombre d'affaires ni de litiges.",
            "Les deux critères de la matière fiscale (classement et type de recours) sont publiés côte à côte, "
            "jamais additionnés.",
            "Les variantes d'écriture d'une même juridiction dans la base sont ramenées à un seul nom.",
        ],
        "limites": [
            "Toutes les décisions ne sont pas classées : la part classée varie selon la juridiction et l'année ; une "
            "baisse du nombre de décisions classées peut venir de la pratique de classement.",
            "La base est complétée au fil des publications : la dernière année est partielle.",
            f"Les décisions antérieures à {ANNEE_MIN} sont peu nombreuses dans la base et ne sont pas comptées ici.",
        ],
        "recherche_publique": RECHERCHE_PUBLIQUE,
        "ordre": "juridictions : Conseil d'État, cours administratives d'appel par ordre alphabétique, Tribunal des "
                 "conflits ; années croissantes ; décisions par date",
    }
    dump(sortie / "index.json", index)
    return index


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="produire", choices=["collecter", "produire", "tout"])
    ap.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT)
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        collecter()
    if a.etape in ("produire", "tout"):
        i = produire(a.sortie)
        c = i["couverture"]
        print(f"jurisprudence : {c['decisions_publiees']} décisions comptées ({c['annee_min']} à {c['annee_max']}), "
              f"{len(i['fichiers']['decisions'])} fichiers de liens", file=sys.stderr)


if __name__ == "__main__":
    main()
