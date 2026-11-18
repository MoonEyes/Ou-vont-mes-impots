"""Séries longues (site/data/series/) : indice des prix, PIB et dépenses par fonction depuis 2005.

Petit axe au service de l'écran /explorer/series, qui montre l'évolution des grandes masses (recettes, dépenses,
solde, dette, intérêts) en euros courants, en euros constants et en part du PIB. Les montants eux-mêmes sont repris
des fichiers déjà publiés, sans les modifier ni les recopier :

    recettes.json (Eurostat gov_10a_taxag), administrations.json (Eurostat gov_10a_main), dette/encours.json,
    dette/interets.json

Ce module n'ajoute que ce qui manque pour les lire sur longue période :
- l'indice annuel des prix à la consommation de l'Insee (base 2025), pour passer en euros constants ;
- le PIB annuel à prix courants de l'Insee (comptes nationaux base 2020), pour la part du PIB ;
- les dépenses des administrations publiques par fonction (Eurostat gov_10a_exp, COFOG niveau 1) depuis 2005,
  le fichier cofog.json n'en publiant que la dernière année.

    python pipeline/series.py collecter   # réseau : Insee BDM, Eurostat -> data/lake/series/_api/
    python pipeline/series.py produire    # sans réseau : data/lake/series/_api + site/data -> site/data/series/

Règles : chaque série porte sa source, son millésime et sa date de mise à jour (lue dans le fichier source, jamais la
date du jour) ; un refus d'accès (401, 403, 429, page anti-robot) est noté et jamais contourné ; les écarts entre
sources (PIB Insee et Eurostat, total COFOG et dépenses totales) sont publiés tels quels ; une valeur absente est
null, jamais 0.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
SORTIE = SITE / "series"
API = ROOT / "data" / "lake" / "series" / "_api"

ANNEE_DEBUT = 2005

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
INSEE_BDM = "https://bdm.insee.fr/series/sdmx/data/SERIES_BDM"

IDBANK_IPC = "011814639"   # Indice annuel des prix à la consommation, base 2025, ensemble des ménages, France, ensemble
IDBANK_PIB = "011779992"   # Comptes nationaux annuels base 2020, PIB, total, prix courants (millions d'euros)

FONCTIONS = ("GF01", "GF02", "GF03", "GF04", "GF05", "GF06", "GF07", "GF08", "GF09", "GF10")

# Téléchargements : identifiant -> (url, extension, titre, licence)
RESEAU = {
    "insee_ipc": (f"{INSEE_BDM}/{IDBANK_IPC}", "xml",
                  "Insee, indice annuel des prix à la consommation, base 2025, ensemble des ménages, France, "
                  "ensemble des produits (série " + IDBANK_IPC + ")", "Licence Ouverte 2.0"),
    "insee_pib": (f"{INSEE_BDM}/{IDBANK_PIB}", "xml",
                  "Insee, comptes nationaux annuels base 2020, produit intérieur brut à prix courants (série "
                  + IDBANK_PIB + ")", "Licence Ouverte 2.0"),
    "eurostat_nama_10_gdp": (f"{EUROSTAT}/nama_10_gdp?geo=FR&lang=fr&na_item=B1GQ&unit=CP_MEUR"
                             f"&sinceTimePeriod={ANNEE_DEBUT}", "json",
                             "Eurostat nama_10_gdp, PIB à prix courants (comparaison avec l'Insee)",
                             "Eurostat, réutilisation libre avec mention"),
    "eurostat_gov_10a_exp": (f"{EUROSTAT}/gov_10a_exp?geo=FR&lang=fr&na_item=TE&sector=S13&unit=MIO_EUR"
                             + "".join(f"&cofog99={c}" for c in ("TOTAL",) + FONCTIONS)
                             + f"&sinceTimePeriod={ANNEE_DEBUT}", "json",
                             "Eurostat gov_10a_exp, dépenses des administrations publiques (S13) par fonction COFOG",
                             "Eurostat, réutilisation libre avec mention"),
}

# Libellés publics des fonctions (nomenclature COFOG des Nations unies, niveau 1, intitulés Eurostat en français).
NOMS_FONCTIONS = {
    "GF01": "Services généraux des administrations publiques",
    "GF02": "Défense",
    "GF03": "Ordre et sécurité publics",
    "GF04": "Affaires économiques",
    "GF05": "Protection de l'environnement",
    "GF06": "Logements et équipements collectifs",
    "GF07": "Santé",
    "GF08": "Loisirs, culture et culte",
    "GF09": "Enseignement",
    "GF10": "Protection sociale",
}

# Fichiers déjà publiés que l'écran lit tels quels (ce module ne les modifie pas).
REPRIS = {
    "recettes": "recettes.json",
    "administrations": "administrations.json",
    "dette_encours": "dette/encours.json",
    "dette_interets": "dette/interets.json",
}

INACCESSIBLES: list[dict] = []

# Recherche publique (règle n° 0) : verdict, licence, date du dernier commit ou de mise à jour.
RECHERCHE_PUBLIQUE = [
    {"nom": "API Insee BDM (SDMX), séries 011814639 (indice des prix base 2025) et 011779992 (PIB base 2020)",
     "url": "https://bdm.insee.fr/series/sdmx", "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0",
     "mise_a_jour": "2026-02-27 (indice des prix) ; 2026-05-29 (PIB)"},
    {"nom": "API Eurostat (JSON-stat) gov_10a_exp et nama_10_gdp", "url": EUROSTAT, "verdict": "réutilisable tel quel",
     "licence": "Eurostat, réutilisation libre avec mention", "mise_a_jour": "2026-10-21"},
    {"nom": "site/data recettes.json, administrations.json, dette/encours.json, dette/interets.json (pipelines du dépôt)",
     "url": "site/data", "verdict": "réutilisable tel quel", "licence": "MIT (code), Licence Ouverte 2.0 (données)",
     "mise_a_jour": "dépôt"},
    {"nom": "pipeline/transform.py : jsonstat_records (décodage JSON-stat)", "url": "pipeline/transform.py",
     "verdict": "réutilisable tel quel", "licence": "MIT", "mise_a_jour": "dépôt"},
    {"nom": "Insee, convertisseur franc-euro (pouvoir d'achat de l'euro et du franc)",
     "url": "https://www.insee.fr/fr/information/2417794", "verdict": "inspiration seulement",
     "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026 (même indice des prix ; outil en ligne, pas de série)"},
    {"nom": "fipeco.fr, fiches de séries longues des finances publiques (tableaux, sans dépôt de code)",
     "url": "https://www.fipeco.fr", "verdict": "inspiration seulement", "licence": "non indiquée",
     "mise_a_jour": "2026 (reprend Insee et Eurostat : sources primaires préférées)"},
]


# --------------------------------------------------------------------------------------------------------------
# Collecte (réseau)
# --------------------------------------------------------------------------------------------------------------

def _telecharger(url: str, essais: int = 5) -> tuple[int, bytes]:
    import requests
    erreur = None
    for i in range(1, essais + 1):
        try:
            r = requests.get(url, timeout=180, headers={"User-Agent": "ou-vont-mes-impots (collecte open data)"})
        except (requests.ConnectionError, requests.Timeout) as exc:
            erreur = exc
        else:
            corps = r.content
            if r.status_code in (401, 403, 429) or b"Just a moment..." in corps[:3000]:
                return r.status_code or 403, b""  # refus : on s'arrête, jamais de contournement
            if r.status_code < 400:
                return r.status_code, corps
            erreur = f"HTTP {r.status_code}"
            if r.status_code < 500:
                break
        if i < essais:
            time.sleep(2 ** i)
    raise RuntimeError(f"{url} : {erreur}")


def collecter() -> None:
    API.mkdir(parents=True, exist_ok=True)
    journal = {}
    for cle, (url, ext, _titre, _lic) in RESEAU.items():
        try:
            code, corps = _telecharger(url)
        except RuntimeError as exc:
            journal[cle] = {"statut": "echec", "motif": str(exc)[:300]}
            print(f"  {cle} : ECHEC {exc}", file=sys.stderr)
            continue
        if not corps:
            journal[cle] = {"statut": "refus", "motif": f"HTTP {code}, non contourné"}
            print(f"  {cle} : refus HTTP {code} (non contourné)")
            continue
        (API / f"{cle}.{ext}").write_bytes(corps)
        journal[cle] = {"statut": "ok", "octets": len(corps),
                        "date": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        print(f"  {cle} : {len(corps)} octets")
    (API / "_journal.json").write_text(json.dumps(journal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------------------------------
# Lecture des sources
# --------------------------------------------------------------------------------------------------------------

def _api(cle: str) -> Path:
    p = API / f"{cle}.{RESEAU[cle][1]}"
    if not p.exists():
        raise SystemExit(f"{p} absent : lancer `python pipeline/series.py collecter`")
    return p


def lire_bdm(contenu: bytes) -> dict:
    """Une série d'un message SDMX StructureSpecific de l'Insee : {idbank, titre, maj, obs {période: valeur}}."""
    racine = ET.fromstring(contenu)
    for s in racine.iter():
        if not s.tag.endswith("Series"):
            continue
        obs = {}
        for o in s:
            v = o.attrib.get("OBS_VALUE")
            if v not in (None, "", "NaN"):
                obs[o.attrib["TIME_PERIOD"]] = float(v)
        return {"idbank": s.attrib.get("IDBANK", ""), "titre": s.attrib.get("TITLE_FR", ""),
                "maj": s.attrib.get("LAST_UPDATE", ""), "obs": dict(sorted(obs.items()))}
    raise SystemExit("message SDMX sans série")


def lire_jsonstat(data: dict) -> tuple[list[dict], dict[int, str]]:
    """Lignes JSON-stat (décodeur du dépôt) et statuts par position (p : provisoire, b : rupture, e : estimé...)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from transform import jsonstat_records  # noqa: E402
    statuts = {int(k): v for k, v in (data.get("status") or {}).items()}
    lignes = []
    ids, tailles = data["id"], data["size"]
    pas = [1] * len(ids)
    for i in range(len(ids) - 2, -1, -1):
        pas[i] = pas[i + 1] * tailles[i + 1]
    index = {d: data["dimension"][d]["category"]["index"] for d in ids}
    for ligne in jsonstat_records(data):
        position = sum(index[d][ligne[d]] * p for d, p in zip(ids, pas))
        ligne["statut"] = statuts.get(position)
        lignes.append(ligne)
    return lignes, statuts


def _r(x: float | None, n: int = 3) -> float | None:
    return None if x is None else round(x, n)


def _annuel(obs: dict[str, float]) -> dict[str, float]:
    return {a: v for a, v in obs.items() if re.fullmatch(r"\d{4}", a) and int(a) >= ANNEE_DEBUT}


# --------------------------------------------------------------------------------------------------------------
# Production
# --------------------------------------------------------------------------------------------------------------

def prix(ipc: dict) -> dict:
    """Indice des prix et coefficient de passage en euros constants de la dernière année publiée."""
    valeurs = _annuel(ipc["obs"])
    if not valeurs:
        raise SystemExit("indice des prix vide")
    ref = max(valeurs)
    coef = {a: _r(valeurs[ref] / v, 6) for a, v in valeurs.items()}
    url, _ext, titre, licence = RESEAU["insee_ipc"]
    return {
        "source": {"titre": titre, "url": url, "licence": licence, "maj": ipc["maj"], "idbank": ipc["idbank"],
                   "intitule_source": ipc["titre"]},
        "base": "2025 = 100",
        "annee_reference": ref,
        "indice": {a: _r(v, 2) for a, v in valeurs.items()},
        "coefficient": coef,
        "methode": f"Montant en euros constants de {ref} = montant en euros courants de l'année × indice {ref} / "
                   "indice de l'année (moyenne annuelle de l'indice des prix à la consommation, ensemble des ménages, "
                   "France). Corrige la hausse moyenne des prix payés par les ménages, pas celle des prix des "
                   "dépenses publiques elles-mêmes.",
    }


def pib(pib_insee: dict, gdp_eurostat: list[dict], maj_es: str) -> dict:
    md = {a: _r(v / 1000, 1) for a, v in _annuel(pib_insee["obs"]).items()}
    es = {l["time"]: _r(l["valeur"] / 1000, 1) for l in gdp_eurostat if int(l["time"]) >= ANNEE_DEBUT}
    ecarts = []
    for a in sorted(set(md) & set(es)):
        if md[a] is not None and es[a] is not None and abs(md[a] - es[a]) >= 0.1:
            ecarts.append({"annee": a, "insee_md": md[a], "eurostat_md": es[a], "ecart_md": _r(md[a] - es[a], 1),
                           "explication": "Les deux organismes publient le même agrégat de la comptabilité nationale "
                                          "française ; un écart vient d'un décalage de mise à jour entre les deux "
                                          "bases de données. Écart montré, non corrigé."})
    url, _ext, titre, licence = RESEAU["insee_pib"]
    es_url, _e, es_titre, es_lic = RESEAU["eurostat_nama_10_gdp"]
    return {
        "source": {"titre": titre, "url": url, "licence": licence, "maj": pib_insee["maj"],
                   "idbank": pib_insee["idbank"], "intitule_source": pib_insee["titre"]},
        "definition": "Produit intérieur brut à prix courants : valeur de ce qui est produit en France en un an.",
        "md": md,
        "comparaison": {"source": {"titre": es_titre, "url": es_url, "licence": es_lic, "maj": maj_es}, "md": es,
                        "ecarts": ecarts},
        "methode": "Part du PIB = montant de l'année / PIB de la même année × 100, les deux en euros courants.",
        "annees_baisse": [{"annee": a, "variation_pct": _r((md[a] / md[p] - 1) * 100, 1)}
                          for p, a in zip(sorted(md), sorted(md)[1:]) if md[a] < md[p]],
    }


def fonctions(lignes: list[dict], maj: str, administrations: dict | None) -> dict:
    series: dict[str, dict] = {}
    provisoires: dict[str, list[str]] = {}
    ruptures: dict[str, list[str]] = {}
    for l in sorted(lignes, key=lambda x: (x["cofog99"], x["time"])):
        if int(l["time"]) < ANNEE_DEBUT:
            continue
        series.setdefault(l["cofog99"], {})[l["time"]] = _r(l["valeur"] / 1000, 3)
        if l["statut"] and "p" in l["statut"]:
            provisoires.setdefault(l["cofog99"], []).append(l["time"])
        if l["statut"] and "b" in l["statut"]:
            ruptures.setdefault(l["cofog99"], []).append(l["time"])
    manquantes = [c for c in ("TOTAL",) + FONCTIONS if c not in series]
    if manquantes:
        raise SystemExit(f"gov_10a_exp : fonctions absentes de la source : {manquantes}")
    annees = sorted({a for s in series.values() for a in s})
    ecarts = []
    te = (administrations or {}).get("annees", {})
    for a in annees:
        total, autre = series["TOTAL"].get(a), te.get(a, {}).get("Ensemble", {}).get("TE")
        if total is not None and autre is not None and abs(total - autre) >= 0.1:
            ecarts.append({"annee": a, "total_cofog_md": _r(total, 1), "depenses_totales_md": autre,
                           "ecart_md": _r(total - autre, 1),
                           "explication": "Même grandeur (dépenses totales des administrations publiques) publiée "
                                          "dans deux tables Eurostat, gov_10a_exp (par fonction) et gov_10a_main "
                                          "(comptes principaux), qui ne coïncident pas exactement cette année-là. "
                                          "Écart montré, non corrigé."})
    url, _ext, titre, licence = RESEAU["eurostat_gov_10a_exp"]
    return {
        "millesime": f"{annees[0]}-{annees[-1]}",
        "source": f"Eurostat gov_10a_exp (COFOG niveau 1, S13, transaction TE), mise à jour {maj}",
        "unite": "milliards d'euros courants (md)",
        "definition": "Dépenses de l'ensemble des administrations publiques (État et organismes nationaux, Sécurité "
                      "sociale, collectivités locales), consolidées, réparties par fonction selon la nomenclature "
                      "COFOG des Nations unies.",
        "avertissement": "Une même dépense n'est rangée que dans une fonction ; les dix fonctions s'additionnent pour "
                         "donner le total. Les valeurs marquées provisoires peuvent être révisées par Eurostat.",
        "sources": {"eurostat": {"titre": titre, "url": url, "licence": licence, "maj": maj}},
        "annees": annees,
        "total": {"nom": "Ensemble des fonctions", "md": series["TOTAL"],
                  "provisoire": provisoires.get("TOTAL", []), "rupture": ruptures.get("TOTAL", [])},
        "fonctions": [{"code": c, "nom": NOMS_FONCTIONS[c], "md": series[c], "provisoire": provisoires.get(c, []),
                       "rupture": ruptures.get(c, [])} for c in FONCTIONS],
        "ecarts": ecarts,
    }


def ruptures(prix_doc: dict, pib_doc: dict, fct: dict) -> list[dict]:
    """Changements de méthode ou de périmètre à signaler sous les graphiques (écrits ici, jamais lissés)."""
    out = [
        {"serie": "prix", "annee": "2026", "type": "changement de base",
         "lecture": "L'Insee publie depuis 2026 l'indice des prix à la consommation en base 2025, qui remplace la "
                    "base 2015 (série arrêtée). Les années passées sont recalculées par l'Insee dans la nouvelle base : "
                    "la série utilisée ici est continue."},
        {"serie": "pib", "annee": "2024", "type": "changement de base",
         "lecture": "Les comptes nationaux sont publiés en base 2020 depuis 2024 : PIB, recettes, dépenses, solde, "
                    "dette et intérêts de toute la période ont été recalculés dans cette base. Les montants peuvent "
                    "différer de ceux publiés à l'époque."},
        {"serie": "comptes", "annee": max(pib_doc["md"]), "type": "valeurs provisoires",
         "lecture": "Les comptes de l'année la plus récente sont provisoires : l'Insee et Eurostat les révisent les "
                    "années suivantes."},
        {"serie": "depenses_administration", "annee": None, "type": "périmètre",
         "lecture": "« État » désigne ici l'administration centrale au sens d'Eurostat : l'État et les organismes "
                    "divers d'administration centrale (universités, agences, opérateurs). Les dépenses de chaque "
                    "administration comptent l'argent versé aux autres : leur somme dépasse le total consolidé."},
    ]
    for p in pib_doc["annees_baisse"]:
        out.append({"serie": "pib", "annee": p["annee"], "type": "lecture",
                    "lecture": f"En {p['annee']}, le PIB en euros courants baisse ({str(p['variation_pct']).replace('.', ',')} % sur un an) : "
                               "une part du PIB peut alors monter sans que le montant augmente."})
    for f in [fct["total"]] + fct["fonctions"]:
        for a in f["rupture"]:
            out.append({"serie": "fonctions", "annee": a, "type": "rupture de série (Eurostat)",
                        "lecture": f"{f['nom']} : rupture de série signalée par Eurostat en {a}."})
    prov = sorted({a for f in [fct["total"]] + fct["fonctions"] for a in f["provisoire"]})
    if prov:
        out.append({"serie": "fonctions", "annee": prov[-1], "type": "valeurs provisoires",
                    "lecture": "Dépenses par fonction : valeurs signalées provisoires par Eurostat pour "
                               + ", ".join(prov) + "."})
    return out


def produire() -> None:
    ipc = lire_bdm(_api("insee_ipc").read_bytes())
    pib_insee = lire_bdm(_api("insee_pib").read_bytes())
    gdp_raw = json.loads(_api("eurostat_nama_10_gdp").read_text(encoding="utf-8"))
    gdp, _ = lire_jsonstat(gdp_raw)
    exp_raw = json.loads(_api("eurostat_gov_10a_exp").read_text(encoding="utf-8"))
    exp, _ = lire_jsonstat(exp_raw)
    admin_p = SITE / REPRIS["administrations"]
    administrations = json.loads(admin_p.read_text(encoding="utf-8")) if admin_p.exists() else None

    prix_doc = prix(ipc)
    pib_doc = pib(pib_insee, gdp, gdp_raw.get("updated", "")[:10])
    fct = fonctions(exp, exp_raw.get("updated", "")[:10], administrations)
    ref = prix_doc["annee_reference"]
    derniere = max(pib_doc["md"])

    index = {
        "millesime": f"Indice des prix {min(prix_doc['indice'])}-{ref} (base 2025) ; PIB {min(pib_doc['md'])}-{derniere} "
                     f"(base 2020) ; dépenses par fonction {fct['millesime']}",
        "source": f"Insee BDM (indice des prix {IDBANK_IPC}, mise à jour {ipc['maj']} ; PIB {IDBANK_PIB}, mise à jour "
                  f"{pib_insee['maj']}) ; Eurostat gov_10a_exp et nama_10_gdp",
        "unite": "indice base 2025 = 100 ; milliards d'euros courants (md)",
        "avertissement": "Trois façons de lire un même montant : en euros courants (tel que publié), en euros constants "
                         f"de {ref} (corrigés de la hausse des prix à la consommation) et en part du PIB. Aucune "
                         "n'est retenue par défaut comme la bonne ; les trois sont proposées côte à côte.",
        "annee_debut": str(ANNEE_DEBUT),
        "annee_reference": ref,
        "prix": prix_doc,
        "pib": pib_doc,
        "fichiers": {"fonctions": "series/fonctions.json", **REPRIS},
        "ruptures": ruptures(prix_doc, pib_doc, fct),
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": {"date": "2026-11-18", "trouvailles": RECHERCHE_PUBLIQUE},
    }

    SORTIE.mkdir(parents=True, exist_ok=True)
    for vieux in SORTIE.glob("*.json"):
        vieux.unlink()
    for nom, doc in (("index.json", index), ("fonctions.json", fct)):
        (SORTIE / nom).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"site/data/series : 2 fichiers ; indice des prix {min(prix_doc['indice'])}-{ref} ; PIB {derniere} = "
          f"{pib_doc['md'][derniere]} Md€ ; dépenses par fonction {fct['millesime']}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "produire"
    if cmd == "collecter":
        collecter()
    elif cmd == "produire":
        produire()
    else:
        raise SystemExit("usage : python pipeline/series.py [collecter|produire]")
