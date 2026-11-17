"""Dette publique : encours, charge d'interets, detenteurs, emissions, dette sociale (site/data/dette/).

Deux temps, comme les autres modules de precision :

    python pipeline/dette.py collecter   # reseau : API publiques -> data/lake/dette/_api/ (reprenable)
    python pipeline/dette.py produire    # sans reseau : data/lake + site/data -> site/data/dette/*.json

Regles :
- chaque serie porte sa source, son millesime et sa definition (Maastricht, comptabilite budgetaire,
  comptabilite nationale) ; deux comptabilites ne sont jamais additionnees ;
- les ecarts entre sources sont publies tels quels (`ecarts`), jamais lisses ;
- un refus d'acces (401, 403, 429, page Cloudflare) est note dans `sources_inaccessibles` et n'est jamais
  contourne ;
- les chiffres repris d'un document (rapport du Senat, PLACSS) sont verifies dans le document telecharge :
  la production echoue si une citation n'y est plus.
"""
from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
SORTIE = SITE / "dette"
LAKE = ROOT / "data" / "lake"
API = LAKE / "dette" / "_api"
RAW = ROOT / "data" / "raw"

ANNEE_DEBUT = 2000
ANNEE_FIN = 2026  # borne de la mission ; la derniere annee publiee est lue dans les donnees

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
INSEE_BDM = "https://bdm.insee.fr/series/sdmx/data"
BCE = "https://data-api.ecb.europa.eu/service/data/GFS"

# Telechargements : identifiant -> (url, extension, titre, licence)
RESEAU = {
    "eurostat_gov_10dd_ggd": (f"{EUROSTAT}/gov_10dd_ggd?geo=FR&lang=fr&sinceTimePeriod={ANNEE_DEBUT}", "json",
                              "Eurostat gov_10dd_ggd, dette des administrations publiques par sous-secteur et par detenteur",
                              "Eurostat, reutilisation libre avec mention"),
    "eurostat_gov_10dd_edpt1": (f"{EUROSTAT}/gov_10dd_edpt1?geo=FR&lang=fr&na_item=GD&sinceTimePeriod={ANNEE_DEBUT}", "json",
                                "Eurostat gov_10dd_edpt1, dette de Maastricht par sous-secteur (notification PDE)",
                                "Eurostat, reutilisation libre avec mention"),
    "eurostat_gov_10a_main": (f"{EUROSTAT}/gov_10a_main?geo=FR&lang=fr&na_item=D41PAY&na_item=TE&sector=S13&sector=S1311"
                              f"&sector=S1313&sector=S1314&unit=MIO_EUR&unit=PC_GDP&sinceTimePeriod={ANNEE_DEBUT}", "json",
                              "Eurostat gov_10a_main, interets dus (D41PAY) et depenses totales (TE) des administrations publiques",
                              "Eurostat, reutilisation libre avec mention"),
    "eurostat_nama_10_gdp": (f"{EUROSTAT}/nama_10_gdp?geo=FR&lang=fr&na_item=B1GQ&unit=CP_MEUR&sinceTimePeriod={ANNEE_DEBUT}",
                             "json", "Eurostat nama_10_gdp, PIB a prix courants", "Eurostat, reutilisation libre avec mention"),
    "insee_dette_trim_apu_2020": (f"{INSEE_BDM}/DETTE-TRIM-APU-2020?startPeriod={ANNEE_DEBUT}", "xml",
                                  "Insee BDM DETTE-TRIM-APU-2020, dette trimestrielle de Maastricht des APU par sous-secteur (base 2020)",
                                  "Licence Ouverte 2.0"),
    "insee_dette_negociable_etat": (f"{INSEE_BDM}/DETTE-NEGOCIABLE-ETAT?startPeriod={ANNEE_DEBUT}", "xml",
                                    "Insee BDM DETTE-NEGOCIABLE-ETAT, encours mensuel de la dette negociable de l'Etat (donnees AFT)",
                                    "Licence Ouverte 2.0"),
    "bce_gfs_detenteurs": (f"{BCE}/A.N.FR.W0+W1+W2.S13+S1311+S1313+S1314.S1+S121+S12K+S12P+S12T+S1U.C.L.LE.GD.T._Z.XDC"
                           f"._T.F.V.N._T?format=csvdata&startPeriod={ANNEE_DEBUT}", "csv",
                           "BCE, statistiques de finances publiques (GFS), dette de Maastricht par secteur detenteur",
                           "BCE, reutilisation libre avec mention"),
    "bce_gfs_emissions": (f"{BCE}/M.N.FR.W0.S13.S1.N.LI.F.F3.T._Z.EUR._T.F.V.N._T?format=csvdata&startPeriod={ANNEE_DEBUT}-01",
                          "csv", "BCE GFS, emissions brutes mensuelles de titres de dette des APU", "BCE, reutilisation libre avec mention"),
    "bce_gfs_remboursements": (f"{BCE}/M.N.FR.W0.S13.S1.N.LD.F.F3.T._Z.EUR._T.F.V.N._T?format=csvdata&startPeriod={ANNEE_DEBUT}-01",
                               "csv", "BCE GFS, remboursements bruts mensuels de titres de dette des APU", "BCE, reutilisation libre avec mention"),
    "bce_gfs_maturite": (f"{BCE}/M.N.FR.W0.S13.S1.N.L.LE.F3.TT+T._Z.YR._T.F.V.A1._T"
                         f"?format=csvdata&startPeriod={ANNEE_DEBUT}-01", "csv",
                         "BCE GFS, maturite moyenne (residuelle et d'origine) des titres de dette des APU",
                         "BCE, reutilisation libre avec mention"),
    "bce_gfs_rendements": (f"{BCE}/M.N.FR.W0.S13.S1.N.L+LI.LE+LX.F3.T._Z.RT._T.F.V.A1+A12._T"
                           f"?format=csvdata&startPeriod={ANNEE_DEBUT}-01", "csv",
                           "BCE GFS, rendement nominal moyen de l'encours et des emissions des 12 derniers mois",
                           "BCE, reutilisation libre avec mention"),
    "bce_pspp": ("https://www.ecb.europa.eu/mopo/pdf/PSPP_breakdown_history.csv", "csv",
                 "BCE, PSPP : achats nets mensuels par juridiction de l'emetteur", "BCE, reutilisation libre avec mention"),
    "bce_pepp": ("https://www.ecb.europa.eu/mopo/pdf/PEPP_public_sector_securities_breakdown_history.csv", "csv",
                 "BCE, PEPP (titres du secteur public) : achats nets mensuels par juridiction", "BCE, reutilisation libre avec mention"),
    "senat_plf2026_efe": ("https://www.senat.fr/rap/l25-139-312/l25-139-312_mono.html", "html",
                          "Senat, rapport general PLF 2026, mission Engagements financiers de l'Etat (n° 139, tome III, annexe 12)",
                          "document parlementaire public"),
    "senat_plf2027_efe": ("https://www.senat.fr/fileadmin/cru-1792598966/Commissions/Finances/2026-2027/PLF_2027/Essentiels/"
                          "Essentiel_EFE_PLF_2027_post-commission.pdf", "pdf",
                          "Senat, L'essentiel PLF 2027, mission Engagements financiers de l'Etat", "document parlementaire public"),
    "senat_r902": ("https://www.senat.fr/rap/r24-902/r24-902-syn.pdf", "pdf",
                   "Senat, rapport d'information n° 902 (2024-2025) sur la structure de detention de la dette de l'Etat, synthese",
                   "document parlementaire public"),
}

# Sources connues mais non collectees (refus d'acces ou acces sous cle) : jamais contournees.
INACCESSIBLES = [
    {"source": "Agence France Tresor (aft.gouv.fr : bulletin mensuel, programme d'emission, detention)",
     "motif": "refus d'acces (page Cloudflare, HTTP 403) le 17/11/2026, deja note au catalogue de collecte ; non contourne. "
              "Les memes chiffres sont repris ici par l'Insee (dette negociable) et par les rapports du Senat (programme de financement)."},
    {"source": "Banque de France Webstat (series DET.Q.FR.1315.F33000.M.Z9.8.F, detention par les non-residents de la dette negociable de l'Etat)",
     "motif": "API Webstat : cle client exigee (HTTP 401 sans cle) ; portail ODS : series publiees sans enregistrements. "
              "Chiffres Banque de France repris via le rapport du Senat n° 902 (2024-2025)."},
]

# Recherche publique (regle n° 0) : verdict, licence, date du dernier commit ou de mise a jour.
RECHERCHE_PUBLIQUE = [
    {"nom": "API Insee BDM (SDMX), jeux DETTE-TRIM-APU-2020 et DETTE-NEGOCIABLE-ETAT", "url": "https://bdm.insee.fr/series/sdmx",
     "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-09 (dette négociable), 2026-T2 (Maastricht)"},
    {"nom": "API Eurostat (JSON-stat) gov_10dd_ggd, gov_10a_main, nama_10_gdp", "url": EUROSTAT,
     "verdict": "réutilisable tel quel", "licence": "Eurostat, réutilisation libre avec mention", "mise_a_jour": "2026-11-16"},
    {"nom": "API BCE (data-api.ecb.europa.eu), jeu GFS ; fichiers PSPP et PEPP par juridiction", "url": "https://data.ecb.europa.eu",
     "verdict": "réutilisable tel quel", "licence": "BCE, réutilisation libre avec mention", "mise_a_jour": "2026-11"},
    {"nom": "Insee Melodi DD_CNA_APU (comptes des APU, déjà dans data/lake)", "url": "https://api.insee.fr/melodi/file/DD_CNA_APU/DD_CNA_APU_CSV_FR",
     "verdict": "réutilisable tel quel", "licence": "Licence Ouverte 2.0", "mise_a_jour": "2026-08-31"},
    {"nom": "site/data/realisations/117.json (pipeline/realisations.py, exécution du programme 117 2010-2025)",
     "url": "site/data/realisations/117.json", "verdict": "réutilisable tel quel", "licence": "MIT (code), Licence Ouverte 2.0 (données)",
     "mise_a_jour": "dépôt"},
    {"nom": "pipeline/transform.py : jsonstat_records (décodage JSON-stat)", "url": "pipeline/transform.py",
     "verdict": "réutilisable tel quel", "licence": "MIT", "mise_a_jour": "dépôt"},
    {"nom": "web/src/calcul (moteur.ts, hors-bulletin.ts, repartition.ts) : répartition par administration du cas 2 100 € net",
     "url": "web/src/calcul", "verdict": "réutilisable tel quel", "licence": "MIT", "mise_a_jour": "dépôt"},
    {"nom": "dettedelafrance.fr, API publique", "url": "https://dettedelafrance.fr/api-publique", "verdict": "inspiration seulement",
     "licence": "CC BY 4.0", "mise_a_jour": "2026-11-17 (pas de dépôt de code ; agrège Insee, AFT, Eurostat : sources primaires préférées)"},
    {"nom": "fgeerolf.com, pages de données dette publique (code R cité, sans dépôt ni licence)", "url": "https://fgeerolf.com/data/dette-publique.html",
     "verdict": "inspiration seulement", "licence": "non indiquée", "mise_a_jour": "2026 (identifiants de séries Banque de France)"},
    {"nom": "GitHub ProjectPulse-source/dette-publique-france (compteur, mêmes idbanks Insee)", "url": "https://github.com/ProjectPulse-source/dette-publique-france",
     "verdict": "inspiration seulement", "licence": "aucune", "mise_a_jour": "dernier commit 2026-11-08"},
    {"nom": "GitHub gunout/Dette-Publique-France (page HTML, dette trimestrielle)", "url": "https://github.com/gunout/Dette-Publique-France",
     "verdict": "inspiration seulement", "licence": "MIT", "mise_a_jour": "dernier commit 2026-09-13"},
]


# --------------------------------------------------------------------------------------------------------------
# Collecte (reseau)
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
                return r.status_code or 403, b""  # refus : on s'arrete, jamais de contournement
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
    for cle, (url, ext, titre, _lic) in RESEAU.items():
        cible = API / f"{cle}.{ext}"
        try:
            code, corps = _telecharger(url)
        except RuntimeError as exc:
            journal[cle] = {"statut": "echec", "motif": str(exc)[:300]}
            print(f"  {cle} : ECHEC {exc}", file=sys.stderr)
            continue
        if not corps:
            journal[cle] = {"statut": "refus", "motif": f"HTTP {code}, non contourne"}
            print(f"  {cle} : refus HTTP {code} (non contourne)")
            continue
        cible.write_bytes(corps)
        journal[cle] = {"statut": "ok", "octets": len(corps), "date": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        print(f"  {cle} : {len(corps)} octets")
    (API / "_journal.json").write_text(json.dumps(journal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------------------------------
# Lecture des sources
# --------------------------------------------------------------------------------------------------------------

def _api(cle: str) -> Path:
    ext = RESEAU[cle][1]
    p = API / f"{cle}.{ext}"
    if not p.exists():
        raise SystemExit(f"{p} absent : lancer `python pipeline/dette.py collecter`")
    return p


def eurostat(cle: str) -> tuple[list[dict], str]:
    """Lignes {dim: code, ..., valeur} et date de mise a jour d'un JSON-stat Eurostat."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from transform import jsonstat_records  # noqa: E402  (decodeur deja present dans le depot)
    data = json.loads(_api(cle).read_text(encoding="utf-8"))
    return jsonstat_records(data), data.get("updated", "")[:10]


def insee_bdm(cle: str) -> dict[str, dict]:
    """{idbank: {"titre", "freq", "obs": {periode: valeur}}} d'un message SDMX StructureSpecific de l'Insee."""
    racine = ET.parse(_api(cle)).getroot()
    out = {}
    for s in racine.iter():
        if not s.tag.endswith("Series"):
            continue
        obs = {}
        for o in s:
            v = o.attrib.get("OBS_VALUE")
            if v not in (None, "", "NaN"):
                obs[o.attrib["TIME_PERIOD"]] = float(v)
        out[s.attrib["IDBANK"]] = {"titre": s.attrib.get("TITLE_FR", ""), "freq": s.attrib.get("FREQ"),
                                   "maj": s.attrib.get("LAST_UPDATE", ""), "obs": obs}
    return out


def bce_csv(cle: str) -> dict[str, dict[str, float]]:
    """{cle de serie (sans prefixe GFS.): {periode: valeur}}."""
    out: dict[str, dict[str, float]] = {}
    with _api(cle).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("OBS_VALUE") not in (None, ""):
                out.setdefault(r["KEY"].split(".", 1)[1], {})[r["TIME_PERIOD"]] = float(r["OBS_VALUE"])
    return out


def bce_programme(cle: str) -> dict[str, float]:
    """Achats nets cumules (M EUR) des titres publics francais a chaque fin d'annee (fichier PSPP ou PEPP de la BCE)."""
    lignes = list(csv.reader(_api(cle).open(encoding="utf-8")))
    dates = next(l for l in lignes if len(l) > 2 and l[0] == "" and l[1])[1:]
    france = next(l for l in lignes if l and l[0] == "France")  # premier bloc : achats nets mensuels
    cumul, out = 0.0, {}
    for d, v in zip(dates, france[1:]):
        m = re.match(r"(?:\d{2}/(\d{2})/(\d{4}))|(?:([A-Za-z]{3})-(\d{2}))$", d.strip())
        if not m or v.strip() == "":
            continue
        cumul += float(v.replace(",", ""))
        if m.group(1):
            mois, an = int(m.group(1)), m.group(2)
        else:
            mois = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].index(m.group(3)) + 1
            an = "20" + m.group(4)
        out[f"{an}-{mois:02d}"] = cumul
    return out


def texte_document(cle: str) -> str:
    """Texte brut d'un document telecharge (HTML ou PDF), espaces normalises, pour verifier les citations."""
    p = _api(cle)
    if p.suffix == ".pdf":
        t = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, check=True).stdout
    else:
        t = unescape(re.sub(r"<[^>]+>", " ", p.read_text(encoding="utf-8", errors="replace")))
    return re.sub(r"\s+", " ", t.replace(" ", " ").replace("\xa0", " "))


def texte_lake(rel: str) -> str:
    t = (LAKE / rel).read_text(encoding="utf-8", errors="replace")
    t = unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t.replace(" ", " ").replace("\xa0", " ").replace("‑", "-"))


def insee_d41() -> tuple[dict[str, dict[str, float]], str]:
    """Interets (D41, emplois) par sous-secteur d'apres Insee Melodi DD_CNA_APU (data/lake), en Md EUR.

    S13 : consolide ; sous-secteurs : non consolide (montants verses a tout secteur, y compris autres APU).
    """
    z = LAKE / "comptes_nationaux" / "insee_dd_cna_apu.zip"
    voulu = {("S13", "C"): "S13", ("S13111", "N"): "S13111", ("S13112", "N"): "S13112",
             ("S1311", "N"): "S1311", ("S1313", "N"): "S1313", ("S1314", "N"): "S1314"}
    out: dict[str, dict[str, float]] = {v: {} for v in voulu.values()}
    with zipfile.ZipFile(z) as zf:
        nom = next(n for n in zf.namelist() if n.endswith("_data.csv"))
        with zf.open(nom) as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter=";"):
                if r["STO"] != "D41" or r["ACCOUNTING_ENTRY"] != "D" or r["COUNTERPART_SECTOR"] != "S1":
                    continue
                k = voulu.get((r["REF_SECTOR"], r["CONSOLIDATION"]))
                if k and r["OBS_VALUE"] not in ("", None) and ANNEE_DEBUT <= int(r["TIME_PERIOD"]) <= ANNEE_FIN:
                    out[k][str(r["TIME_PERIOD"])] = round(float(r["OBS_VALUE"]) * 10 ** (int(r["UNIT_MULT"] or 6) - 9), 3)
    date = datetime.fromtimestamp(z.stat().st_mtime, tz=timezone.utc).date().isoformat()
    return out, date


# --------------------------------------------------------------------------------------------------------------
# Chiffres publies dans des documents (verifies dans le texte telecharge)
# --------------------------------------------------------------------------------------------------------------

# Chaque entree : cle du document, citation exacte (espaces normalises) qui doit figurer dans le texte.
CITATIONS = {
    "sensibilite": ("senat_plf2026_efe", "entraînerait une hausse de la charge de la dette de + 3,2 milliards d'euros à 1 an, "
                                         "+ 23,5 milliards d'euros à 5 ans et + 33,5 milliards d'euros à 9 ans"),
    "tableau_financement": ("senat_plf2026_efe", "Besoin de financement 305,7 303,5 297,7 305,7 Amortissement de titres d'État à "
                                                 "moyen et long terme 155,1 168,2 168,0 175,8 Valeur nominale 151,1 166,1 166,1 173,4 "
                                                 "Suppléments d'indexation dus 4,0 2,1 1,9 2,4"),
    "emissions_tableau": ("senat_plf2026_efe", "Émissions de titres à moyen et long terme, nettes des rachats 285,0 300,0 300,0 310,0"),
    "deficit_tableau": ("senat_plf2026_efe", "Déficit budgétaire 155,9 139,0 130,5 124,4"),
    "charge_2026_plf": ("senat_plf2026_efe", "à 58,0 milliards d'euros , contre 53,5 milliards d'euros en loi de finances initiale pour 2025 "
                                             "(50,8 milliards d'euros en révisé 2025)"),
    "p117_interets": ("senat_plf2026_efe", "dont 98 % des crédits sont alloués au paiement des intérêts de la dette"),
    "charge_2027": ("senat_plf2027_efe", "à 71,9 milliards d’euros (en AE et en CP), contre 58,0 milliards d’euros en LFI 2026"),
    "revise_2026": ("senat_plf2027_efe", "(61,6 milliards d’euros en révisé 2026)"),
    "programme_2026": ("senat_plf2027_efe", "s’établit à 310 milliards d’euros, conformément à la loi de finances du 19 février 2026"),
    "realise_2026": ("senat_plf2027_efe", "19 octobre 2026, 286,2 milliards d’euros d’émissions nettes des rachats ont été"),
    "amortissements_2027": ("senat_plf2027_efe", "189,2 milliards d’euros (contre 169,8 milliards d’euros en 2026)"),
    "emissions_2027": ("senat_plf2027_efe", "nettes des rachats, pour 340,0 milliards d’euros"),
    "non_residents": ("senat_r902", "En 1996, les non-résidents détenaient 28,7 % de cette dette"),
    "non_residents_pic": ("senat_r902", "jusqu’à un pic de 66,4 % fin 2009"),
    "non_residents_creux": ("senat_r902", "pour atteindre un creux à 47,5 % fin 2021"),
    "non_residents_2025": ("senat_r902", "réaugmente progressivement jusqu’à près de 56 % aujourd’hui"),
}

CITATIONS_LAKE = {
    "cades_2024": ("secu/secu_placss2024_texte.html", "CADES ‑ 154,1 ‑ 163,6 Résultat de l’exercice"),
    "cades_2025": ("secu/secu_placss2025_texte.html", "CADES -138,1 -154,1 Résultat de l’exercice"),
    "cades_resultat_2025": ("secu/secu_placss2025_texte.html", "CADES 16,2 16,0 FRR"),
    "cades_resultat_2024": ("secu/secu_placss2024_texte.html", "CADES 16,0 18,3 FRR"),
    "passif_net_2024": ("secu/secu_placss2024_texte.html", "s’élève à 93,4 milliards d’euros au 31 décembre 2024"),
    "passif_net_2025": ("secu/secu_placss2025_texte.html", "s’élève à 99,7 milliards d’euros au 31 décembre 2025"),
    "reprise_2026": ("secu/secu_placss2025_texte.html", "une nouvelle reprise de dette par la CADES à hauteur de 15 milliards d’euros"),
}


def _norm(s: str) -> str:
    s = s.replace("‑", "-").replace("‑", "-").replace("’", "'").replace(" ", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s)


def verifier_citations() -> dict:
    """Controle les citations dans les documents ; leve une erreur si une citation n'y est plus."""
    textes, resultat, manquants = {}, {}, []
    for cle, (doc, cit) in CITATIONS.items():
        if doc not in textes:
            textes[doc] = _norm(texte_document(doc))
        if _norm(cit) not in textes[doc]:
            manquants.append(f"{doc} : {cit[:80]}")
        resultat.setdefault(doc, {"statut": "vérifié", "citations": 0})["citations"] += 1
    for cle, (rel, cit) in CITATIONS_LAKE.items():
        if rel not in textes:
            textes[rel] = _norm(texte_lake(rel))
        if _norm(cit) not in textes[rel]:
            manquants.append(f"{rel} : {cit[:80]}")
        resultat.setdefault(rel, {"statut": "vérifié", "citations": 0})["citations"] += 1
    if manquants:
        raise SystemExit("Citations introuvables dans les documents (montant a revoir) :\n  " + "\n  ".join(manquants))
    return resultat


# --------------------------------------------------------------------------------------------------------------
# Construction des fichiers
# --------------------------------------------------------------------------------------------------------------

def _r(x: float | None, n: int = 3) -> float | None:
    return None if x is None else round(x, n)


def _annees() -> list[str]:
    return [str(a) for a in range(ANNEE_DEBUT, ANNEE_FIN + 1)]


def _src(cle: str) -> dict:
    url, _ext, titre, licence = RESEAU[cle]
    return {"titre": titre, "url": url, "licence": licence}


LIB_SECTEUR = {"S13": "Ensemble des administrations publiques", "S1311": "Administration centrale (État et ODAC)",
               "S1313": "Administrations publiques locales (APUL)", "S1314": "Administrations de sécurité sociale (ASSO)"}

INSEE_ENCOURS = {  # idbank -> (code, libelle)
    "010777610": ("Etat", "État"),
    "010777613": ("ODAC", "Organismes divers d'administration centrale (ODAC)"),
    "010777626": ("APUL", "Administrations publiques locales (APUL)"),
    "010777625": ("ASSO", "Administrations de sécurité sociale (ASSO)"),
    "010777616": ("Ensemble", "Ensemble des administrations publiques"),
}
INSEE_PCT_PIB = "010777608"


def pib() -> tuple[dict[str, float], str]:
    lignes, maj = eurostat("eurostat_nama_10_gdp")
    return {l["time"]: l["valeur"] / 1000 for l in lignes}, maj


def encours(pib_md: dict[str, float]) -> dict:
    bdm = insee_bdm("insee_dette_trim_apu_2020")
    lignes, maj_es = eurostat("eurostat_gov_10dd_edpt1")

    insee = {}
    dernier_t = max(bdm["010777616"]["obs"])
    for idb, (code, lib) in INSEE_ENCOURS.items():
        obs = bdm[idb]["obs"]
        md = {a: _r(obs.get(f"{a}-Q4"), 1) for a in _annees() if f"{a}-Q4" in obs}
        pct = {a: _r(v / pib_md[a] * 100, 1) for a, v in md.items() if a in pib_md}
        insee[code] = {"libelle": lib, "idbank": idb, "md": md, "pct_pib": pct,
                       "pct_pib_mode": "calculé (encours fin d'année / PIB Eurostat nama_10_gdp)",
                       "dernier_trimestre": {"periode": dernier_t, "md": obs.get(dernier_t)}}
    pct_publie = {a: v for a in _annees() if (v := bdm[INSEE_PCT_PIB]["obs"].get(f"{a}-Q4")) is not None}
    insee["Ensemble"]["pct_pib_publie"] = pct_publie
    insee["Ensemble"]["pct_pib_publie_idbank"] = INSEE_PCT_PIB

    euro = {}
    for l in lignes:
        if l["na_item"] != "GD" or l["sector"] not in LIB_SECTEUR:
            continue
        e = euro.setdefault(l["sector"], {"libelle": LIB_SECTEUR[l["sector"]], "md": {}, "pct_pib": {}})
        if l["unit"] == "MIO_EUR":
            e["md"][l["time"]] = _r(l["valeur"] / 1000, 1)
        elif l["unit"] == "PC_GDP":
            e["pct_pib"][l["time"]] = l["valeur"]
    for e in euro.values():
        e["md"] = dict(sorted(e["md"].items()))
        e["pct_pib"] = dict(sorted(e["pct_pib"].items()))
        e["pct_pib_mode"] = "publié"

    bce = bce_csv("bce_gfs_detenteurs")
    bce_sect = {}
    for sect in ("S13", "S1311", "S1313", "S1314"):
        obs = bce.get(f"A.N.FR.W0.{sect}.S1.C.L.LE.GD.T._Z.XDC._T.F.V.N._T", {})
        md = {a: _r(v / 1000, 1) for a, v in sorted(obs.items())}
        bce_sect[sect] = {"libelle": LIB_SECTEUR[sect], "md": md,
                          "pct_pib": {a: _r(v / pib_md[a] * 100, 1) for a, v in md.items() if a in pib_md},
                          "pct_pib_mode": "calculé (encours / PIB Eurostat nama_10_gdp)"}
    derniere = max(set(insee["Ensemble"]["md"]) & set(euro["S13"]["md"]))
    ecarts = []
    for a in sorted(set(insee["Ensemble"]["md"]) & set(euro["S13"]["md"])):
        paires = [
            ("Ensemble APU", insee["Ensemble"]["md"][a], euro["S13"]["md"][a]),
            ("Administration centrale (Insee État + ODAC / Eurostat S1311)",
             _r(insee["Etat"]["md"][a] + insee["ODAC"]["md"][a], 1), euro["S1311"]["md"].get(a)),
            ("APUL / S1313", insee["APUL"]["md"][a], euro["S1313"]["md"].get(a)),
            ("ASSO / S1314", insee["ASSO"]["md"][a], euro["S1314"]["md"].get(a)),
        ]
        for agr, vi, ve in paires:
            if vi is not None and ve is not None and abs(vi - ve) >= 0.5:
                ecarts.append({"annee": a, "agregat": agr, "insee_md": vi, "eurostat_md": ve, "ecart_md": _r(vi - ve, 1),
                               "explication": EXPLI_ECART_ENCOURS})
    for a in sorted(set(bce_sect["S13"]["md"]) & set(euro["S13"]["md"])):
        if abs(bce_sect["S13"]["md"][a] - euro["S13"]["md"][a]) >= 0.5:
            ecarts.append({"annee": a, "agregat": "Ensemble APU (BCE GFS / Eurostat)", "bce_md": bce_sect["S13"]["md"][a],
                           "eurostat_md": euro["S13"]["md"][a], "ecart_md": _r(bce_sect["S13"]["md"][a] - euro["S13"]["md"][a], 1),
                           "explication": "Millésimes de révision différents ; les sources ne documentent pas l'écart."})
    return {
        "millesime": f"{ANNEE_DEBUT}-{derniere} (fin d'année) ; dernier trimestre Insee : {dernier_t}",
        "source": "Insee BDM DETTE-TRIM-APU-2020 (base 2020) ; Eurostat gov_10dd_edpt1 (notification PDE) ; BCE GFS ; PIB Eurostat nama_10_gdp",
        "unite": "milliards d'euros (md) ; pct_pib en % du PIB",
        "definition": "Dette au sens de Maastricht : dette brute, consolidée entre administrations publiques, en valeur nominale "
                      "(numéraire et dépôts, titres de créance, crédits). Fin d'année = 4e trimestre.",
        "avertissement": "Les sous-secteurs Insee séparent l'État et les ODAC ; Eurostat et la BCE les réunissent (administration centrale, "
                         "S1311). Eurostat ne publie les sous-secteurs qu'à partir de 2021 dans ce jeu ; la BCE remonte à 2000. Les écarts "
                         "entre sources sont listés tels quels.",
        "derniere_annee": derniere,
        "sources": {"insee": {**_src("insee_dette_trim_apu_2020"), "maj": bdm["010777616"]["maj"][:10]},
                    "eurostat": {**_src("eurostat_gov_10dd_edpt1"), "maj": maj_es},
                    "pib": _src("eurostat_nama_10_gdp")},
        "insee": insee,
        "eurostat": euro,
        "bce": {"definition": "BCE GFS, mêmes données de Maastricht, séries longues des sous-secteurs (non consolidées entre "
                              "sous-secteurs : la dette d'un sous-secteur détenue par un autre y reste comptée).",
                "source": _src("bce_gfs_detenteurs"), "secteurs": bce_sect},
        "ecarts": ecarts,
    }


EXPLI_ECART_ENCOURS = ("Insee publie la contribution de chaque sous-secteur à la dette consolidée de l'ensemble (titres détenus par "
                       "une autre administration retirés) ; Eurostat publie la dette de chaque sous-secteur consolidée en son sein "
                       "seulement (titres de l'État détenus par la sécurité sociale ou les collectivités comptés). Écart de "
                       "définition, pas d'erreur.")


def interets(pib_md: dict[str, float], c04: dict) -> dict:
    lignes, maj = eurostat("eurostat_gov_10a_main")
    ser: dict[tuple, dict[str, float]] = {}
    for l in lignes:
        ser.setdefault((l["na_item"], l["sector"], l["unit"]), {})[l["time"]] = l["valeur"]
    nat_euro = {}
    for s in ("S13", "S1311", "S1313", "S1314"):
        md = {a: _r(v / 1000, 3) for a, v in sorted(ser.get(("D41PAY", s, "MIO_EUR"), {}).items())}
        te = ser.get(("TE", s, "MIO_EUR"), {})
        nat_euro[s] = {"libelle": LIB_SECTEUR[s], "md": md,
                       "pct_pib": dict(sorted(ser.get(("D41PAY", s, "PC_GDP"), {}).items())),
                       "part_depenses": {a: _r(ser[("D41PAY", s, "MIO_EUR")][a] / te[a], 4) for a in md if te.get(a)}}
    d41, date_insee = insee_d41()
    lib_insee = {"S13": "Ensemble des APU (consolidé)", "S1311": "Administration centrale", "S13111": "État",
                 "S13112": "ODAC", "S1313": "APUL", "S1314": "ASSO"}
    nat_insee = {k: {"libelle": lib_insee[k], "md": dict(sorted(v.items()))} for k, v in d41.items()}
    derniere_nat = max(nat_euro["S13"]["md"])

    # Programme 117 (comptabilite budgetaire) : execution reprise de realisations/117.json
    r117 = json.loads((SITE / "realisations" / "117.json").read_text(encoding="utf-8"))
    par_an = {str(a["annee"]): a for a in r117["prevu_depense"]["annees"]}
    budg = {}
    for a in _annees():
        x = par_an.get(a)
        if x and x.get("depense_constatee_eur") is not None:
            budg[a] = {"md": _r(x["depense_constatee_eur"] / 1e9, 3), "statut": "exécution",
                       "source": "site/data/realisations/117.json : " + x["source"]}
        elif int(a) < 2006:
            budg[a] = {"md": None, "statut": "trou", "motif": "Pas de programme 117 avant la LOLF (budget 2006) : charge de la dette "
                                                              "alors votée par chapitres, non publiée en données ouvertes par la collecte."}
        elif a == "2026":
            budg[a] = {"md": 58.0, "statut": "LFI 2026 (crédits votés, charge de la dette de l'État)",
                       "source": "Sénat, L'essentiel PLF 2027, mission Engagements financiers de l'État, p. 1 et 7 (vérifié)",
                       "revise_md": 61.6, "revise_source": "même document, p. 7 : révisé 2026 (vérifié)"}
        else:
            budg[a] = {"md": None, "statut": "trou",
                       "motif": (x or {}).get("trou") or "Exécution par programme non trouvée en données ouvertes "
                                                        "(data.economie.gouv.fr, data.gouv.fr) par la collecte."}
    smb = json.loads((RAW / "situation_budgetaire.json").read_text(encoding="utf-8"))
    ligne = next(x for x in smb if "dette" in x["ligne_d_information"].lower())
    ecarts_b = []
    for a in ("2024", "2025"):
        v = ligne.get(f"31_12_{a}")
        if v is not None and budg.get(a, {}).get("md") is not None:
            ecarts_b.append({"annee": a, "programme_117_md": budg[a]["md"], "autre_md": _r(v / 1e9, 3),
                             "autre_source": "DGFiP, situation mensuelle budgétaire au 31/12 (data/raw/situation_budgetaire.json), "
                                             "ligne « Charges de la dette de l'État » du budget général",
                             "ecart_md": _r(budg[a]["md"] - v / 1e9, 3),
                             "explication": "Périmètre différent : la ligne de la situation mensuelle couvre les charges de la dette "
                                            "du budget général, le programme 117 inclut aussi la trésorerie de l'État."})
    ecarts_b.append({"annee": "2025", "programme_117_md": budg["2025"]["md"], "autre_md": 50.8,
                     "autre_source": "Sénat, rapport général PLF 2026 : charge de la dette de l'État en « révisé 2025 » (prévision d'octobre 2025, vérifié)",
                     "ecart_md": _r(budg["2025"]["md"] - 50.8, 3), "explication": "Prévision révisée contre exécution constatée."})
    for a in sorted(set(nat_insee["S13111"]["md"]) & {k for k, v in budg.items() if v.get("md") is not None and v["statut"] == "exécution"}):
        ecarts_b.append({"annee": a, "programme_117_md": budg[a]["md"], "autre_md": nat_insee["S13111"]["md"][a],
                         "autre_source": "Insee, comptes nationaux : intérêts D41 versés par l'État (S13111)",
                         "ecart_md": _r(budg[a]["md"] - nat_insee["S13111"]["md"][a], 3),
                         "explication": "Comptabilité budgétaire (décaissements de l'année, primes et décotes à l'émission, provision "
                                        "pour indexation) contre comptabilité nationale (intérêts courus) : écart attendu, jamais lissé."})

    # Part de 100 EUR d'impot qui paie des interets (cas C04, comptabilite nationale)
    annee_ratio = derniere_nat
    correspondance = {"Etat": "S1311", "Securite sociale": "S1314", "Collectivites locales": "S1313", "Plusieurs": "S13"}

    def evaluer(par_admin: dict) -> dict:
        total = sum(par_admin.values())
        lignes_cas, interets_eur = {}, 0.0
        for adm, montant in par_admin.items():
            ratio = nat_euro[correspondance[adm]]["part_depenses"][annee_ratio]
            lignes_cas[adm] = {"montant_annuel_eur": _r(montant, 2), "sur_100_eur": _r(montant / total * 100, 2),
                               "secteur": correspondance[adm], "part_interets_dans_depenses": ratio,
                               "interets_annuel_eur": _r(montant * ratio, 2)}
            interets_eur += montant * ratio
        return {"total_annuel_eur": _r(total, 2), "par_administration": lignes_cas,
                "interets_annuel_eur": _r(interets_eur, 2), "interets_sur_100_eur": _r(interets_eur / total * 100, 2)}
    princ = c04["variantes"][c04["variante_principale"]]
    variantes = {}
    for cle, v in c04["variantes"].items():
        ev = evaluer(v["par_administration_eur"])
        variantes[cle] = {"commune": v["commune"], "definition": v["definition"], "teom_eur": v["teom_eur"],
                          "fourchette_eur": v["fourchette_eur"], "total_annuel_eur": ev["total_annuel_eur"],
                          "interets_annuel_eur": ev["interets_annuel_eur"], "interets_sur_100_eur": ev["interets_sur_100_eur"]}
    principal = evaluer(princ["par_administration_eur"])
    racine_etat = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    md117 = _cherche_md(racine_etat, "117")
    part_117 = md117 / racine_etat["md"] if md117 else None
    cas = {
        "profil": c04["profil"],
        "calcul": c04["calcul"],
        "perimetre": princ["definition"],
        "commune": princ["commune"],
        "fourchette_eur": princ["fourchette_eur"],
        **principal,
        "annee_ratios": annee_ratio,
        "variantes": variantes,
        "ecart_variantes": "Seule la TEOM change d'une variante à l'autre (taux de la commune, base de logement estimée) ; "
                           "sans commune, la TEOM n'est pas chiffrée (0 €). Prélevé sur salaire et IR : 7 638,36 € ; taxes sur la "
                           "consommation : valeurs centrales de prelevements/tva_conso.json (5e décile), identiques partout.",
        "methode": "Comptabilité nationale : pour chaque administration qui reçoit une part de ce que paie le foyer, part des intérêts "
                   "(D41) dans ses dépenses totales (TE, Eurostat gov_10a_main), appliquée à cette part. « Plusieurs » (taxes sans "
                   "destinataire publié) prend le ratio de l'ensemble des APU. Les transferts entre administrations ne sont pas suivis "
                   "au second degré.",
        "lecture_budgetaire_etat": {
            "comptabilite": "budgétaire (ne pas additionner à la lecture nationale)",
            "part_programme_117_dans_arbre_etat": _r(part_117, 4),
            "arbre": racine_etat.get("millesime"),
            "eur_sur_100_de_la_part_etat": _r(part_117 * 100, 2) if part_117 else None,
            "lecture": "Sur 100 € versés au budget de l'État, part dépensée par le programme 117 (charge de la dette et trésorerie) "
                       "dans l'arbre État du site.",
        },
    }
    rend = bce_csv("bce_gfs_rendements")
    taux = {}
    for k, nom in (("M.N.FR.W0.S13.S1.N.L.LE.F3.T._Z.RT._T.F.V.A1._T", "encours"),
                   ("M.N.FR.W0.S13.S1.N.LI.LX.F3.T._Z.RT._T.F.V.A12._T", "emissions_12_mois")):
        obs = rend.get(k, {})
        taux[nom] = {p[:4]: v for p, v in sorted(obs.items()) if p.endswith("-12")}
        if obs:
            dernier = max(obs)
            taux[nom]["dernier"] = {"periode": dernier, "pct": obs[dernier]}
    return {
        "millesime": f"Programme 117 : exécution 2010-2025 (trous signalés), LFI 2026 ; comptabilité nationale : {ANNEE_DEBUT}-{derniere_nat}",
        "source": "site/data/realisations/117.json (PLR, RAP, PLRG) ; Sénat (LFI et révisé 2026) ; Eurostat gov_10a_main ; "
                  "Insee DD_CNA_APU ; BCE GFS",
        "unite": "milliards d'euros (md) ; pct_pib en % du PIB ; part_depenses = intérêts / dépenses totales du secteur",
        "avertissement": "Deux comptabilités, jamais additionnées : budgétaire (programme 117, décaissements de l'année) et nationale "
                         "(D41, intérêts dus). Les écarts sont listés tels quels.",
        "derniere_annee_nationale": derniere_nat,
        "budgetaire": {
            "comptabilite": "budgétaire (crédits de paiement consommés)",
            "programme": "117", "libelle": r117["libelle"],
            "note": "98 % des crédits du programme 117 servent au paiement des intérêts (Sénat, rapport général PLF 2026, vérifié).",
            "annees": budg,
            "previsions": {"2027": {"md": 71.9, "statut": "PLF 2027", "source": "Sénat, L'essentiel PLF 2027, p. 1 (vérifié)"}},
            "ecarts": ecarts_b,
        },
        "nationale": {
            "comptabilite": "nationale (SEC 2010, intérêts D41 dus, droits constatés)",
            "eurostat": {"source": {**_src("eurostat_gov_10a_main"), "maj": maj}, "secteurs": nat_euro},
            "insee": {"source": {"titre": "Insee Melodi DD_CNA_APU (comptes des administrations publiques, base 2020)",
                                 "url": "https://api.insee.fr/melodi/file/DD_CNA_APU/DD_CNA_APU_CSV_FR", "licence": "Licence Ouverte 2.0",
                                 "maj": date_insee},
                      "secteurs": nat_insee},
            "annee_2026": "Non publiée : les comptes nationaux 2026 paraissent au printemps 2027.",
            "ecarts": [{"annee": a, "secteur": "S13", "eurostat_md": nat_euro["S13"]["md"][a], "insee_md": nat_insee["S13"]["md"][a],
                        "ecart_md": _r(nat_euro["S13"]["md"][a] - nat_insee["S13"]["md"][a], 3),
                        "explication": "Eurostat D41PAY (intérêts au sens de la notification) contre Insee D41 consolidé (avant "
                                       "correction des services d'intermédiation financière) : les sources ne documentent pas l'écart."}
                       for a in sorted(set(nat_euro["S13"]["md"]) & set(nat_insee["S13"]["md"]))
                       if abs(nat_euro["S13"]["md"][a] - nat_insee["S13"]["md"][a]) >= 0.05],
        },
        "cas_type": cas,
        "sensibilite": {
            "choc": "+1 point pérenne sur l'ensemble de la courbe des taux, par rapport au scénario de référence du PLF 2026",
            "perimetre": "charge de la dette de l'État (comptabilité budgétaire)",
            "auteur": "Agence France Trésor, reprise par le Sénat",
            "source": "Sénat, rapport général PLF 2026, mission Engagements financiers de l'État (vérifié)",
            "hausse_md": {"1 an": 3.2, "5 ans": 23.5, "9 ans": 33.5},
            "note": "Le PLF 2027 publie la même sensibilité en graphique seulement (rapport sur la dette des APU annexé au PLF 2027) : "
                    "valeurs non reprises.",
        },
        "rendements_moyens_pct": {"source": _src("bce_gfs_rendements"),
                                  "definition": "Rendement nominal moyen des titres de dette des APU (BCE) : encours, et émissions des 12 derniers mois ; valeur de décembre.",
                                  **taux},
    }


def _cherche_md(n: dict, programme: str) -> float | None:
    total = 0.0
    trouve = False

    def visite(x):
        nonlocal total, trouve
        if str(x.get("id", "")).split("/")[-1] == programme and x.get("niveau") == "programme":
            total += x["md"]
            trouve = True
            return
        if "fichier" in x and not x.get("enfants"):
            p = SITE / x["fichier"]
            if p.exists():
                for e in json.loads(p.read_text(encoding="utf-8")).get("enfants", []):
                    visite(e)
            return
        for e in x.get("enfants", []):
            visite(e)
    visite(n)
    return total if trouve else None


LIB_DETENTEUR = {
    "S2": "Non-résidents (reste du monde, dont BCE et autres banques centrales)",
    "S121": "Banque de France (banque centrale nationale)",
    "S122_S123": "Banques et fonds monétaires résidents",
    "S124-S129": "Autres sociétés financières résidentes (assureurs, fonds de pension, OPC non monétaires, autres)",
    "S11_S14_S15": "Sociétés non financières, ménages et institutions sans but lucratif résidents (non séparés par la source)",
}
BCE_DET = {"W1.S13.S1": "S2", "W2.S13.S121": "S121", "W2.S13.S12T": "S122_S123", "W2.S13.S12P": "S124-S129", "W2.S13.S1U": "S11_S14_S15"}


def detenteurs() -> dict:
    lignes, maj = eurostat("eurostat_gov_10dd_ggd")
    md: dict[str, dict[str, float]] = {}
    for l in lignes:
        if l["na_item"] == "GD" and l["sector"] == "S13" and l["maturity"] == "TOTAL" and l["unit"] == "MIO_EUR":
            md.setdefault(l["sector2"], {})[l["time"]] = l["valeur"] / 1000
    total = md["S1_S2"]
    euro = {}
    for k, lib in LIB_DETENTEUR.items():
        euro[k] = {"libelle": lib, "md": {a: _r(v, 1) for a, v in sorted(md.get(k, {}).items())},
                   "part": {a: _r(v / total[a], 4) for a, v in sorted(md.get(k, {}).items()) if total.get(a)}}
    derniere = max(total)
    somme = sum(md.get(k, {}).get(derniere, 0) for k in LIB_DETENTEUR)
    bce = bce_csv("bce_gfs_detenteurs")
    bce_md = {}
    for suffixe, code in BCE_DET.items():
        k = f"A.N.FR.{suffixe}.C.L.LE.GD.T._Z.XDC._T.F.V.N._T"
        bce_md[code] = {a: _r(v / 1000, 1) for a, v in sorted(bce.get(k, {}).items())}
    bce_total = {a: _r(v / 1000, 1) for a, v in bce.get("A.N.FR.W0.S13.S1.C.L.LE.GD.T._Z.XDC._T.F.V.N._T", {}).items()}
    bce_part = {c: {a: _r(v / bce_total[a], 4) for a, v in ser.items() if bce_total.get(a)} for c, ser in bce_md.items()}
    ecarts = []
    for code, ser in bce_md.items():
        ref = md.get(code, {})
        for a, v in ser.items():
            if a in ref and abs(ref[a] - v) >= 0.5:
                ecarts.append({"annee": a, "detenteur": code, "eurostat_md": _r(ref[a], 1), "bce_md": v, "ecart_md": _r(ref[a] - v, 1)})
    pspp, pepp = bce_programme("bce_pspp"), bce_programme("bce_pepp")
    fin_annee = lambda d: {k[:4]: _r(v / 1000, 1) for k, v in d.items() if k.endswith("-12")}  # noqa: E731
    dernier_pspp, dernier_pepp = max(pspp), max(pepp)
    return {
        "millesime": f"Eurostat {min(total)}-{derniere}, BCE {min(bce_total)}-{max(bce_total)} (fin d'année)",
        "source": "Eurostat gov_10dd_ggd (dette de Maastricht par secteur détenteur) ; BCE GFS (contrôle) ; BCE PSPP et PEPP ; "
                  "Banque de France via Sénat (rapport n° 902)",
        "unite": "milliards d'euros (md) ; part = fraction de la dette de Maastricht des APU",
        "definition": "Dette de Maastricht des administrations publiques (consolidée, valeur nominale), ventilée selon le secteur "
                      "qui la détient. Les assureurs ne sont pas isolés (« autres sociétés financières ») ; les ménages ne sont pas "
                      "séparés des sociétés non financières.",
        "avertissement": "Les titres achetés par la BCE elle-même et par les autres banques centrales sont comptés chez les "
                         "non-résidents ; ceux achetés par la Banque de France (dont PSPP et PEPP) chez la banque centrale. "
                         "Un fonds étranger qui détient des titres pour le compte de ménages français est un non-résident.",
        "derniere_annee": derniere,
        "total_md": {a: _r(v, 1) for a, v in sorted(total.items())},
        "controle_somme_derniere_annee": {"somme_md": _r(somme, 1), "total_md": _r(total[derniere], 1)},
        "sources": {"eurostat": {**_src("eurostat_gov_10dd_ggd"), "maj": maj}, "bce": _src("bce_gfs_detenteurs")},
        "eurostat": euro,
        "bce": {"definition": "BCE GFS : mêmes données de Maastricht, série longue depuis 2000 (Eurostat : depuis 2020 dans ce jeu).",
                "total_md": dict(sorted(bce_total.items())), "detenteurs_md": bce_md, "parts": bce_part},
        "ecarts": ecarts,
        "eurosysteme_achats_nets_cumules": {
            "definition": "Achats nets cumulés de titres publics français (valeur comptable, depuis le début de chaque programme), "
                          "par l'ensemble de l'Eurosystème (Banque de France et BCE). Ce n'est ni un encours nominal ni la seule "
                          "Banque de France : ne pas comparer directement à la ligne S121.",
            "source": {"pspp": _src("bce_pspp"), "pepp": _src("bce_pepp")},
            "pspp_md": fin_annee(pspp) | {"dernier": {"periode": dernier_pspp, "md": _r(pspp[dernier_pspp] / 1000, 1)}},
            "pepp_md": fin_annee(pepp) | {"dernier": {"periode": dernier_pepp, "md": _r(pepp[dernier_pepp] / 1000, 1)}},
        },
        "banque_de_france_publie": {
            "definition": "Part des titres de dette des administrations centrales détenue par les non-résidents (Banque de France, "
                          "comptes nationaux financiers), reprise par le Sénat ; périmètre et valorisation différents d'Eurostat.",
            "source": "Sénat, rapport d'information n° 902 (2024-2025), synthèse (vérifié)",
            "points": [{"date": "1996", "part": 0.287}, {"date": "fin 2009 (pic)", "part": 0.664},
                       {"date": "fin 2021 (creux)", "part": 0.475}, {"date": "2025 (« près de 56 % »)", "part": 0.56}],
        },
    }


def financement() -> dict:
    bdm = insee_bdm("insee_dette_negociable_etat")

    def decembres(idb):
        return {p[:4]: _r(v / 1000, 1) for p, v in sorted(bdm[idb]["obs"].items()) if p.endswith("-12")}
    dernier = max(bdm["001711531"]["obs"])
    neg = {
        "source": {**_src("insee_dette_negociable_etat"), "maj": bdm["001711531"]["maj"][:10]},
        "definition": "Dette négociable de l'État (OAT, BTAN jusqu'en 2013, BTF), valeur nominale, fin décembre ; les OAT indexées "
                      "sur l'inflation comprennent le supplément d'indexation.",
        "total_md": decembres("001711531"),
        "court_terme_md": decembres("001711532"),
        "moyen_long_terme_md": decembres("001711533"),
        "taux_fixe_md": decembres("001738853"),
        "indexee_inflation_md": decembres("001738854"),
        "dernier": {"periode": dernier, **{k: _r(bdm[i]["obs"][dernier] / 1000, 1) for k, i in
                                           (("total_md", "001711531"), ("indexee_inflation_md", "001738854"),
                                            ("court_terme_md", "001711532"))}},
    }
    neg["part_indexee"] = {a: _r(v / neg["total_md"][a], 4) for a, v in neg["indexee_inflation_md"].items() if neg["total_md"].get(a)}

    em, rb = bce_csv("bce_gfs_emissions"), bce_csv("bce_gfs_remboursements")
    em = em.get("M.N.FR.W0.S13.S1.N.LI.F.F3.T._Z.EUR._T.F.V.N._T", {})
    rb = rb.get("M.N.FR.W0.S13.S1.N.LD.F.F3.T._Z.EUR._T.F.V.N._T", {})

    def annuel(d):
        out, mois = {}, {}
        for p, v in d.items():
            out[p[:4]] = out.get(p[:4], 0) + v
            mois[p[:4]] = mois.get(p[:4], 0) + 1
        return {a: _r(v / 1000, 1) for a, v in sorted(out.items()) if mois[a] == 12}
    mat = bce_csv("bce_gfs_maturite")
    res = mat.get("M.N.FR.W0.S13.S1.N.L.LE.F3.TT._Z.YR._T.F.V.A1._T", {})
    ori = mat.get("M.N.FR.W0.S13.S1.N.L.LE.F3.T._Z.YR._T.F.V.A1._T", {})
    return {
        "millesime": f"Dette négociable : {min(neg['total_md'])}-{dernier} ; programme de financement de l'État : 2024-2027 ; titres des APU (BCE) : "
                     f"{min(annuel(em) or {'?': 0})}-{max(annuel(em) or {'?': 0})}",
        "source": "Insee BDM DETTE-NEGOCIABLE-ETAT (données AFT) ; tableau de financement de l'État (PAP « Engagements financiers de "
                  "l'État » PLF 2026, repris par le Sénat) ; Sénat, L'essentiel PLF 2027 ; BCE GFS",
        "unite": "milliards d'euros (md) ; maturités en années",
        "avertissement": "Le programme de financement porte sur l'État seul (comptabilité budgétaire, prévisions puis exécution) ; "
                         "les émissions et remboursements BCE couvrent les titres de toutes les administrations publiques (CADES, "
                         "collectivités, etc.) : ne pas les comparer terme à terme.",
        "dette_negociable_etat": neg,
        "programme_financement_etat": {
            "source": "Sénat, rapport général PLF 2026 (tableau repris du PAP « Engagements financiers de l'État ») et L'essentiel "
                      "PLF 2027 (vérifiés)",
            "definition": "Émissions de titres à moyen et long terme nettes des rachats ; amortissements de titres d'État à moyen et "
                          "long terme (valeur nominale + suppléments d'indexation).",
            "annees": {
                "2024": {"statut": "exécution", "emissions_nettes_rachats_md": 285.0, "amortissements_md": 155.1,
                         "dont_valeur_nominale_md": 151.1, "dont_supplements_indexation_md": 4.0, "deficit_budgetaire_md": 155.9,
                         "besoin_financement_md": 305.7},
                "2025": {"statut": "LFI 2025", "emissions_nettes_rachats_md": 300.0, "amortissements_md": 168.2,
                         "dont_valeur_nominale_md": 166.1, "dont_supplements_indexation_md": 2.1, "deficit_budgetaire_md": 139.0,
                         "besoin_financement_md": 303.5,
                         "revise": {"emissions_nettes_rachats_md": 300.0, "amortissements_md": 168.0, "deficit_budgetaire_md": 130.5,
                                    "besoin_financement_md": 297.7}},
                "2026": {"statut": "LFI 2026", "emissions_nettes_rachats_md": 310.0, "amortissements_md": 175.8,
                         "dont_valeur_nominale_md": 173.4, "dont_supplements_indexation_md": 2.4, "deficit_budgetaire_md": 124.4,
                         "besoin_financement_md": 305.7, "realise_au_19_10_2026_md": 286.2,
                         "note": "Le montant de 310 Md€ est celui du PLF 2026, confirmé par la loi de finances du 19 février 2026."},
                "2027": {"statut": "PLF 2027", "emissions_nettes_rachats_md": 340.0, "amortissements_md": 189.2,
                         "besoin_financement_md": 339.7},
            },
            "ecarts": [{"annee": "2026", "agregat": "amortissements de titres à moyen et long terme",
                        "valeurs_md": {"PLF 2026 (Sénat, rapport général)": 175.8, "PLF 2027 (Sénat, L'essentiel)": 169.8},
                        "explication": "Prévision initiale contre chiffre repris un an plus tard ; la source ne détaille pas la différence."}],
        },
        "titres_apu_bce": {
            "source": {"emissions": _src("bce_gfs_emissions"), "remboursements": _src("bce_gfs_remboursements"),
                       "maturite": _src("bce_gfs_maturite")},
            "definition": "Titres de dette de toutes les administrations publiques (non consolidés), émissions et remboursements bruts "
                          "annuels (somme des 12 mois), maturité moyenne en décembre. Séries mensuelles disponibles depuis décembre 2007.",
            "emissions_brutes_md": annuel(em),
            "remboursements_bruts_md": annuel(rb),
            "maturite_residuelle_moyenne_ans": {p[:4]: v for p, v in sorted(res.items()) if p.endswith("-12")}
            | ({"dernier": {"periode": max(res), "ans": res[max(res)]}} if res else {}),
            "maturite_initiale_moyenne_ans": {p[:4]: v for p, v in sorted(ori.items()) if p.endswith("-12")},
        },
    }


def dette_sociale(encours_doc: dict) -> dict:
    asso = encours_doc["insee"]["ASSO"]
    return {
        "definition": "La dette sociale est une partie de la dette publique (ASSO, sous-secteur S1314) : elle n'est pas en plus. "
                      "La CADES amortit la dette des régimes de base reprise par la loi ; son résultat annuel est l'amortissement.",
        "asso_maastricht_md": {a: asso["md"][a] for a in sorted(asso["md"]) if int(a) >= 2015},
        "cades": {
            "source": "PLACSS 2024 et 2025, rapport annexé (situation patrimoniale au 31 décembre), data/lake/secu (vérifié)",
            "situation_nette_md": {"2023": -145.3, "2024": -138.1, "2025": -121.9},
            "calcul": "situation nette = report à nouveau + résultat de l'exercice (2023 : -163,6 + 18,3 ; 2024 : -154,1 + 16,0 ; "
                      "2025 : -138,1 + 16,2). Fonds propres négatifs : dette restant à amortir au sens comptable, pas l'encours "
                      "d'emprunts de la CADES.",
            "dette_amortie_md": {"2023": 18.3, "2024": 16.0, "2025": 16.2},
            "reprise_prevue_2026_md": 15.0,
        },
        "passif_net_securite_sociale_md": {"2024": 93.4, "2025": 99.7,
                                           "perimetre": "régimes de base, FSV, CADES et FRR (sans régimes complémentaires) ; PLACSS"},
        "liens_secu": [
            {"fichier": "secu/arbre/racine.json", "noeud": "cades", "millesime": "Exécution 2024",
             "contenu": "dépenses de la CADES : amortissement, intérêts et frais"},
            {"fichier": "secu/arbre_2025/racine.json", "noeud": "cades", "millesime": "Exécution 2025",
             "contenu": "dette sociale amortie dans l'année"},
        ],
        "liens_prelevements": "La CRDS et une part de la CSG vont à la CADES (destinataire « cades » de prelevements/affectation.json).",
    }


# Cas type C04 (2 100 EUR net, celibataire, locataire) : repartition par administration calculee le 17/11/2026 avec le
# module de calcul du site, a l'identique de l'ecran resultat (web/src/ecrans/saisie.ts : calculer(profil, {affectation,
# commune}) puis assembler(..., {tva, affectation, tfDep, ligneCommune}, habitudes inconnues) puis parAdministration).
# La variante principale (Lyon, 69123) reproduit la carte du site : 13 891,94 EUR (12 428,23 a 14 031,18). La seule
# difference entre variantes est la TEOM (payee par le locataire via ses charges) ; sans commune elle n'est pas chiffree.
# Recontrole dans tests/test_dette.py : prelevements sur salaire = reference OpenFisca de cas_types.json.
_SANS_TEOM = {"Securite sociale": 7969.54, "Etat": 3146.69, "Plusieurs": 1504.69}
C04 = {
    "profil": {"cas_type": "C04", "libelle": "Célibataire au salaire médian (2 100 € net par mois), locataire"},
    "calcul": "web/src/calcul (calculer, assembler, parAdministration) appelé comme l'écran résultat (web/src/ecrans/saisie.ts), "
              "affectation 2025, taxes sur la consommation centrales (habitudes inconnues), calcul du 17/11/2026",
    "variante_principale": "lyon",
    "variantes": {
        "lyon": {"commune": "69123 (Lyon)", "teom_eur": 110.57, "fourchette_eur": {"bas": 12428.23, "central": 13891.94, "haut": 14031.18},
                 "definition": "Périmètre de la carte du site : prélevé sur salaire et IR, taxes sur la consommation centrales, TEOM "
                               "de la commune (locataire à Lyon)",
                 "par_administration_eur": {**_SANS_TEOM, "Collectivites locales": 1271.03}},
        "nantes": {"commune": "44109 (Nantes, commune du cas type C04 dans tests/cas_types)", "teom_eur": 155.57,
                   "fourchette_eur": {"bas": 12474.56, "central": 13936.94, "haut": 14060.5},
                   "definition": "Même périmètre, TEOM de Nantes",
                   "par_administration_eur": {**_SANS_TEOM, "Collectivites locales": 1316.03}},
        "sans_commune": {"commune": None, "teom_eur": 0.0, "fourchette_eur": {"bas": 12318.99, "central": 13781.37, "haut": 13781.37},
                         "definition": "Même périmètre sans commune saisie : TEOM non chiffrée (0 €)",
                         "par_administration_eur": {**_SANS_TEOM, "Collectivites locales": 1160.46}},
    },
    "salaire_seul_eur": {"Securite sociale": 6634.36, "Etat": 1004.0},
}


def produire() -> None:
    verifs = verifier_citations()
    pib_md, _ = pib()
    enc = encours(pib_md)
    itr = interets(pib_md, C04)
    det = detenteurs()
    fin = financement()
    soc = dette_sociale(enc)
    SORTIE.mkdir(parents=True, exist_ok=True)
    for vieux in SORTIE.glob("*.json"):
        vieux.unlink()

    def ecrire(nom, doc):
        (SORTIE / nom).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    ecrire("encours.json", enc)
    ecrire("interets.json", itr)
    ecrire("detenteurs.json", det)
    ecrire("financement.json", fin)

    a = enc["derniere_annee"]
    an = itr["derniere_annee_nationale"]
    ad = det["derniere_annee"]
    index = {
        "millesime": f"Encours {a} ; intérêts {an} (comptabilité nationale) et 2025-2026 (programme 117) ; détenteurs {ad}",
        "source": "Insee, Eurostat, BCE, data.economie.gouv.fr (via realisations/117.json), Sénat, PLACSS (détail dans chaque fichier)",
        "unite": "milliards d'euros (md)",
        "avertissement": "Présentation factuelle : chaque chiffre porte sa source et sa définition ; les écarts entre sources sont "
                         "affichés, jamais lissés ; comptabilité budgétaire et nationale ne sont jamais additionnées.",
        "fichiers": {"encours": "dette/encours.json", "interets": "dette/interets.json", "detenteurs": "dette/detenteurs.json",
                     "financement": "dette/financement.json"},
        "synthese": {
            "encours_maastricht": {"annee": a, "md": enc["insee"]["Ensemble"]["md"][a], "pct_pib": enc["eurostat"]["S13"]["pct_pib"][a],
                                   "source": "Insee (md, base 2020) ; Eurostat (% du PIB)",
                                   "eurostat_md": enc["eurostat"]["S13"]["md"][a],
                                   "dernier_trimestre": enc["insee"]["Ensemble"]["dernier_trimestre"]},
            "interets_apu_d41": {"annee": an, "md": itr["nationale"]["eurostat"]["secteurs"]["S13"]["md"][an],
                                 "pct_pib": itr["nationale"]["eurostat"]["secteurs"]["S13"]["pct_pib"].get(an),
                                 "insee_md": itr["nationale"]["insee"]["secteurs"]["S13"]["md"].get(an),
                                 "source": "Eurostat gov_10a_main (D41PAY) ; Insee DD_CNA_APU"},
            "programme_117": {"2025": itr["budgetaire"]["annees"]["2025"]["md"], "2026_lfi": itr["budgetaire"]["annees"]["2026"]["md"],
                              "2026_revise": itr["budgetaire"]["annees"]["2026"]["revise_md"],
                              "source": "PLRG 2025 (exécution) ; Sénat (LFI et révisé 2026)"},
            "interets_sur_100_eur_cas_c04": itr["cas_type"]["interets_sur_100_eur"],
            "non_residents_part": det["eurostat"]["S2"]["part"].get(ad),
            "banque_de_france_part": det["eurostat"]["S121"]["part"].get(ad),
        },
        "dette_sociale": soc,
        "verification_documents": verifs,
        "sources_inaccessibles": INACCESSIBLES,
        "recherche_publique": {"date": "2026-11-17", "trouvailles": RECHERCHE_PUBLIQUE},
    }
    ecrire("index.json", index)
    print(f"site/data/dette : 5 fichiers ; encours {a} = {index['synthese']['encours_maastricht']['md']} Md€ ; "
          f"intérêts D41 {an} = {index['synthese']['interets_apu_d41']['md']} Md€ ; "
          f"sur 100 € (C04) = {index['synthese']['interets_sur_100_eur_cas_c04']} €")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "produire"
    if cmd == "collecter":
        collecter()
    elif cmd == "produire":
        produire()
    else:
        raise SystemExit("usage : python pipeline/dette.py [collecter|produire]")
