"""Listes de référence des prénoms du filtre des noms de personnes (pipeline/local.py, pipeline/associations.py).

Les listes sont VERSIONNÉES dans le dépôt (pipeline/donnees_ref/) : le filtre ne dépend d'aucun cache ni d'aucun
fichier hors dépôt, et une machine neuve (mise à jour hebdomadaire) filtre exactement comme la production. Le filtre
charge l'union des deux fichiers :
  - prenoms.txt         Insee, Fichier des prénoms (état civil, naissances en France), seuil ci-dessous ;
  - prenoms_sirene.txt  Insee, stock SIRENE des unités légales : premier prénom d'au moins 300 entrepreneurs
                        individuels (règle de production depuis l'origine). Il couvre les prénoms d'adultes nés hors
                        de France, peu présents dans l'état civil (« Iryna », « Krzysztof », « Abdelmajid »).

Source : Insee, « Fichier des prénoms » (état civil), fichier national, naissances en France de 1900 à 2024, édition
du 9 juillet 2025, https://www.insee.fr/fr/statistiques/8894961 ; Licence Ouverte 2.0 (Etalab), jeu « Fichier des
prénoms depuis 1900 » de data.gouv.fr. Variables lues : sexe, prénom (premier prénom), année, effectif (arrondi par
l'Insee au multiple de 5 le plus proche).

Règle de dérivation (déterministe) :
  - prénom mis en majuscules sans accent, comme le filtre ;
  - effectif additionné sur toutes les années et les deux sexes ;
  - gardé si ce total est au moins SEUIL (1 000 naissances depuis 1900) et si le prénom est fait de lettres seules (au
    moins 3), la forme que le filtre compare mot à mot ; un prénom composé (« JEAN-PIERRE ») est couvert par ses
    parties, qui sont dans la liste ;
  - liste triée, un prénom par ligne, précédée d'un en-tête « # » (source, édition, seuil, nombre, empreinte SHA-256
    du fichier source).
  Complément SIRENE : prénom1UniteLegale en majuscules sans accent, au moins SEUIL_SIRENE unités légales, lettres et
  traits d'union ; recalculé seulement si le stock (data/lake/_cache/local/sirene_unite_legale.parquet, collecté par
  pipeline/local.py) est présent, sinon le fichier versionné est conservé tel quel.
Les mots courants et noms de lieux qui sont aussi des prénoms restent dans la liste (prudence : un texte libre qui les
contient suivis d'un mot est retiré, le montant reste publié) ; seules les exceptions de pipeline/local.py
(NON_PRENOMS, MOTS_OUTILS) sont appliquées au chargement.

Commandes :
  python pipeline/prenoms_ref.py collecter   # réseau : fichier Insee dans data/lake/_ref/prenoms/ (contrôle
                                             # d'intégrité collecte/integrite.py) ; un refus 401/403/429 est noté
  python pipeline/prenoms_ref.py produire    # sans réseau : réécrit pipeline/donnees_ref/prenoms.txt (et
                                             # prenoms_sirene.txt si le stock SIRENE est présent)
  python pipeline/prenoms_ref.py             # les deux
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import re
import sys
import time
import unicodedata
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
BRUT = ROOT / "data" / "lake" / "_ref" / "prenoms"
SORTIE = Path(__file__).resolve().parent / "donnees_ref" / "prenoms.txt"
SORTIE_SIRENE = SORTIE.with_name("prenoms_sirene.txt")
STOCK_SIRENE = ROOT / "data" / "lake" / "_cache" / "local" / "sirene_unite_legale.parquet"
SEUIL_SIRENE = 300
SOURCE_SIRENE = {
    "titre": "Insee, stock SIRENE des unités légales (base Sirene des entreprises et de leurs établissements)",
    "page": "https://www.data.gouv.fr/fr/datasets/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/",
    "licence": "Licence Ouverte 2.0 (Etalab)",
}
SOURCE = {
    "fichier": "prenoms-2024-nat_csv.zip",
    "url": "https://www.insee.fr/fr/statistiques/fichier/8894961/prenoms-2024-nat_csv.zip",
    "page": "https://www.insee.fr/fr/statistiques/8894961",
    "titre": "Insee, Fichier des prénoms, fichier national (naissances en France de 1900 à 2024)",
    "edition": "9 juillet 2025",
    "millesime": "1900 à 2024",
    "licence": "Licence Ouverte 2.0 (Etalab)",
}
SEUIL = 1000
MINIMUM_ATTENDU = 2500  # garde-fou : une liste plus courte signale un fichier source tronqué ou mal lu


def normaliser(p: str) -> str:
    return unicodedata.normalize("NFKD", (p or "").strip().upper()).encode("ascii", "ignore").decode()


def deriver(octets_zip: bytes, seuil: int = SEUIL) -> list[str]:
    """Prénoms (majuscules sans accent, lettres seules, au moins 3) donnés au moins `seuil` fois depuis 1900."""
    with zipfile.ZipFile(io.BytesIO(octets_zip)) as z:
        nom = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        texte = z.read(nom).decode("utf-8-sig")
    total: collections.Counter = collections.Counter()
    lecteur = csv.DictReader(io.StringIO(texte), delimiter=";")
    champs = {c.lower(): c for c in lecteur.fieldnames or []}
    if not {"prenom", "valeur"} <= set(champs):
        raise ValueError(f"colonnes inattendues dans {nom} : {lecteur.fieldnames}")
    for r in lecteur:
        v = (r[champs["valeur"]] or "").strip()
        if v.isdigit():
            total[normaliser(r[champs["prenom"]])] += int(v)
    return sorted(p for p, n in total.items() if n >= seuil and re.fullmatch(r"[A-Z]{3,}", p))


def produire() -> list[str]:
    zp = BRUT / SOURCE["fichier"]
    if not zp.exists():
        raise SystemExit(f"{zp} absent : lancer d'abord « python pipeline/prenoms_ref.py collecter »")
    octets = zp.read_bytes()
    liste = deriver(octets)
    if len(liste) < MINIMUM_ATTENDU:
        raise SystemExit(f"{len(liste)} prénoms seulement (au moins {MINIMUM_ATTENDU} attendus) : rien n'est écrit")
    entete = [
        f"# Prénoms du filtre des noms de personnes (pipeline/local.py), dérivés par pipeline/prenoms_ref.py",
        f"# Source : {SOURCE['titre']}, édition du {SOURCE['edition']}, {SOURCE['page']}",
        f"# Fichier : {SOURCE['url']} (SHA-256 {hashlib.sha256(octets).hexdigest()})",
        f"# Licence : {SOURCE['licence']}",
        f"# Millésime : {SOURCE['millesime']}",
        f"# Règle : prénom en majuscules sans accent, lettres seules (au moins 3), donné au moins {SEUIL} fois "
        f"depuis 1900 (deux sexes additionnés)",
        f"# Nombre : {len(liste)}",
    ]
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text("\n".join(entete + liste) + "\n", encoding="utf-8")
    print(f"prenoms_ref : {len(liste)} prénoms (seuil {SEUIL}) -> {SORTIE.relative_to(ROOT)}")
    return liste


def produire_sirene() -> list[str] | None:
    """Complément SIRENE (prénoms d'au moins SEUIL_SIRENE unités légales) ; stock absent : fichier versionné conservé."""
    if not STOCK_SIRENE.exists():
        print(f"prenoms_ref : stock SIRENE absent, {SORTIE_SIRENE.name} versionné conservé")
        return None
    import duckdb
    r = duckdb.sql(f"""select upper(strip_accents(prenom1UniteLegale)) p, count(*) n from '{STOCK_SIRENE}'
                       where prenom1UniteLegale is not null group by 1 having count(*) >= {SEUIL_SIRENE}""").fetchall()
    liste = sorted({x[0] for x in r if re.fullmatch(r"[A-Z][A-Z-]+", x[0] or "")})
    if len(liste) < 1000:
        raise SystemExit(f"complément SIRENE : {len(liste)} prénoms seulement : rien n'est écrit")
    entete = [
        "# Complément du filtre des noms de personnes (pipeline/local.py), dérivé par pipeline/prenoms_ref.py",
        f"# Source : {SOURCE_SIRENE['titre']}, {SOURCE_SIRENE['page']}",
        f"# Licence : {SOURCE_SIRENE['licence']}",
        f"# Règle : premier prénom (prenom1UniteLegale) en majuscules sans accent, porté par au moins {SEUIL_SIRENE} "
        "unités légales (entrepreneurs individuels) ; couvre les prénoms d'adultes nés hors de France",
        f"# Nombre : {len(liste)}",
    ]
    SORTIE_SIRENE.write_text("\n".join(entete + liste) + "\n", encoding="utf-8")
    print(f"prenoms_ref : complément SIRENE {len(liste)} prénoms (seuil {SEUIL_SIRENE}) -> "
          f"{SORTIE_SIRENE.relative_to(ROOT)}")
    return liste


def collecter(forcer: bool = False, essais: int = 5) -> str:
    dest = BRUT / SOURCE["fichier"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not forcer:
        return "présent"
    import requests
    from fetch import octets_annonces, remplacer_si_valide  # contrôle collecte/integrite.py
    derniere = ""
    for i in range(essais):
        try:
            r = requests.get(SOURCE["url"], timeout=(20, 300), headers={"User-Agent": "ou-vont-mes-impots/pipeline"})
            if r.status_code in (401, 403, 429, 451):
                return f"accès refusé (HTTP {r.status_code}) : aucun contournement"
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(r.content)
            remplacer_si_valide(tmp, dest, octets_attendus=octets_annonces(r))  # invalide : dest conservé
            return "ok"
        except Exception as e:  # reprise réseau
            derniere = f"{type(e).__name__}: {e}"[:200]
            time.sleep(4 * (i + 1))
    return f"échec après {essais} essais : {derniere}"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etape", nargs="?", default="tout", choices=["collecter", "produire", "tout"])
    ap.add_argument("--forcer", action="store_true", help="retélécharger le fichier source déjà présent")
    a = ap.parse_args(argv)
    if a.etape in ("collecter", "tout"):
        print(f"collecte : {collecter(a.forcer)}")
    if a.etape in ("produire", "tout"):
        produire()
        produire_sirene()


if __name__ == "__main__":
    main()
