"""Séries longues (pipeline/series.py) : fonctions pures et cohérence des fichiers publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "series"
sys.path.insert(0, str(ROOT / "pipeline"))
import series  # noqa: E402

SDMX = b"""<?xml version='1.0' encoding='UTF-8'?><message:StructureSpecificData
 xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"><message:DataSet>
<Series IDBANK="011814639" TITLE_FR="Indice annuel" LAST_UPDATE="2026-02-27">
<Obs TIME_PERIOD="2025" OBS_VALUE="100.0"/><Obs TIME_PERIOD="2004" OBS_VALUE="71.39"/>
<Obs TIME_PERIOD="2005" OBS_VALUE="72.64"/><Obs TIME_PERIOD="2006" OBS_VALUE="NaN"/></Series>
</message:DataSet></message:StructureSpecificData>"""


def _json(nom: str):
    p = DOSSIER / nom
    if not p.exists():
        pytest.skip(f"{p} absent")
    return json.loads(p.read_text(encoding="utf-8"))


# --- fonctions pures (toujours testées) ------------------------------------------------------------------------------

def test_lecture_sdmx_ordonnee_sans_valeur_absente():
    s = series.lire_bdm(SDMX)
    assert s["idbank"] == "011814639" and s["maj"] == "2026-02-27"
    assert list(s["obs"]) == ["2004", "2005", "2025"]   # NaN retiré, jamais 0 ; ordre chronologique


def test_euros_constants_et_debut_de_serie():
    p = series.prix(series.lire_bdm(SDMX))
    assert p["annee_reference"] == "2025" and "2004" not in p["indice"]   # séries à partir de 2005
    assert p["coefficient"]["2025"] == 1.0
    assert p["coefficient"]["2005"] == round(100.0 / 72.64, 6)


def test_jsonstat_statuts_par_position():
    data = {"id": ["cofog99", "time"], "size": [2, 2],
            "dimension": {"cofog99": {"category": {"index": {"GF01": 0, "GF02": 1}, "label": {}}},
                          "time": {"category": {"index": {"2023": 0, "2024": 1}, "label": {}}}},
            "value": {"0": 1000.0, "1": 2000.0, "3": 4000.0}, "status": {"1": "p", "3": "b"}}
    lignes, _ = series.lire_jsonstat(data)
    par = {(l["cofog99"], l["time"]): (l["valeur"], l["statut"]) for l in lignes}
    assert par[("GF01", "2023")] == (1000.0, None)
    assert par[("GF01", "2024")] == (2000.0, "p")
    assert par[("GF02", "2024")] == (4000.0, "b")
    assert ("GF02", "2023") not in par   # valeur absente : pas de ligne, jamais 0


def test_sources_documentees():
    for cle, (url, ext, titre, licence) in series.RESEAU.items():
        assert url.startswith("https://") and ext in ("xml", "json") and titre and licence, cle
    assert set(series.NOMS_FONCTIONS) == set(series.FONCTIONS)
    verdicts = {t["verdict"] for t in series.RECHERCHE_PUBLIQUE}
    assert verdicts <= {"réutilisable tel quel", "à adapter", "inspiration seulement"}


# --- fichiers publiés ---------------------------------------------------------------------------------------------

def test_index_prix_et_pib():
    idx = _json("index.json")
    assert idx["millesime"] and idx["source"]
    ref = idx["annee_reference"]
    prix = idx["prix"]
    assert prix["indice"][ref] == 100.0 and prix["source"]["url"].startswith("https://bdm.insee.fr/")
    annees = sorted(prix["indice"])
    assert annees[0] == idx["annee_debut"] == "2005"
    assert [int(a) for a in annees] == list(range(2005, int(annees[-1]) + 1))   # aucune année manquante
    for a in annees:
        assert prix["coefficient"][a] == pytest.approx(prix["indice"][ref] / prix["indice"][a], rel=1e-4)
    pib = idx["pib"]
    assert sorted(pib["md"])[0] == "2005" and all(v > 1000 for v in pib["md"].values())
    for e in pib["comparaison"]["ecarts"]:
        assert e["ecart_md"] == pytest.approx(e["insee_md"] - e["eurostat_md"], abs=0.11)


def test_pib_coherent_avec_la_dette_publiee():
    """Même PIB à 0,2 point près : part du PIB de la dette (Eurostat, publiée) et dette / PIB Insee (calculée)."""
    idx = _json("index.json")
    enc_p = SITE / "dette" / "encours.json"
    if not enc_p.exists():
        pytest.skip("dette/encours.json absent")
    s13 = json.loads(enc_p.read_text(encoding="utf-8"))["eurostat"]["S13"]
    communes = [a for a in idx["pib"]["md"] if a in s13["md"] and a in s13.get("pct_pib", {})]
    assert communes
    for a in communes:
        assert s13["md"][a] / idx["pib"]["md"][a] * 100 == pytest.approx(s13["pct_pib"][a], abs=0.2), a


def test_ruptures_signalees():
    idx = _json("index.json")
    series_rupt = {r["serie"] for r in idx["ruptures"]}
    assert {"prix", "pib", "comptes", "depenses_administration"} <= series_rupt
    for b in idx["pib"]["annees_baisse"]:
        assert any(r["serie"] == "pib" and r["annee"] == b["annee"] for r in idx["ruptures"])
    for r in idx["ruptures"]:
        assert "—" not in r["lecture"]


def test_fonctions_somme_et_ecarts():
    f = _json("fonctions.json")
    assert [x["code"] for x in f["fonctions"]] == list(series.FONCTIONS)
    assert f["annees"][0] == "2005"
    for a in f["annees"]:
        vals = [x["md"].get(a) for x in f["fonctions"]]
        if None in vals or f["total"]["md"].get(a) is None:
            continue
        assert sum(vals) == pytest.approx(f["total"]["md"][a], abs=0.05), a   # les dix fonctions font le total
    for e in f["ecarts"]:
        assert e["ecart_md"] == pytest.approx(e["total_cofog_md"] - e["depenses_totales_md"], abs=0.11)
        assert abs(e["ecart_md"]) < 0.02 * e["depenses_totales_md"]   # même grandeur : écart faible attendu
    for x in [f["total"]] + f["fonctions"]:
        assert set(x["provisoire"]) <= set(f["annees"]) and set(x["rupture"]) <= set(f["annees"])


def test_fichiers_repris_existent_et_non_recopies():
    idx = _json("index.json")
    for cle, chemin in idx["fichiers"].items():
        assert (SITE / chemin).exists(), (cle, chemin)
    assert sorted(p.name for p in DOSSIER.glob("*.json")) == ["fonctions.json", "index.json"]
    for p in DOSSIER.glob("*.json"):
        assert p.stat().st_size < 1_000_000   # chargé par le navigateur


@pytest.mark.skipif(not (series.API / "insee_ipc.xml").exists(), reason="data/lake/series absent")
def test_produire_reproductible(tmp_path, monkeypatch):
    avant = {p.name: p.read_bytes() for p in DOSSIER.glob("*.json")}
    series.produire()
    apres = {p.name: p.read_bytes() for p in DOSSIER.glob("*.json")}
    assert avant == apres
