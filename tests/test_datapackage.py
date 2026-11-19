"""Données réutilisables : docs/datapackage/ (pipeline/datapackage.py) décrit tout site/data, sans réseau.

Le descripteur versionné couvre chaque fichier versionné de site/data (par le motif de sa ressource, pour rester vrai
quand la mise à jour hebdomadaire ajoute un fichier à une famille existante) ; chaque ressource porte une licence et
au moins une source ; la génération est reproductible, y compris sans entrepôt (clone sans data/lake).
"""
from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import datapackage as dpk  # noqa: E402

SORTIE = ROOT / "docs" / "datapackage"
pytestmark = pytest.mark.skipif(not (SORTIE / "datapackage.json").exists(), reason="docs/datapackage absent")


@pytest.fixture(scope="module")
def descripteur() -> dict:
    return json.loads((SORTIE / "datapackage.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def versionnes() -> list[str]:
    r = subprocess.run(["git", "ls-files", "site/data"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("pas de dépôt git")
    return sorted(p.removeprefix("site/data/") for p in r.stdout.splitlines() if (ROOT / p).is_file())


@pytest.fixture(scope="module")
def genere(monkeypatch_module) -> dict[str, str]:
    monkeypatch_module.setenv("SOURCE_DATE_EPOCH", "1767225600")
    return dpk.construire()


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def test_le_datapackage_couvre_tous_les_fichiers_versionnes(descripteur, versionnes):
    motifs = [r["motif"].removeprefix("site/data/") for r in descripteur["resources"] if r.get("motif")]
    tables = {r["path"].split("/site/data/", 1)[1] for r in descripteur["resources"]
              if r.get("type") == "table" and "/site/data/" in r["path"]}
    hors = [f for f in versionnes if f not in tables and not any(dpk.correspond(f, m) for m in motifs)]
    assert not hors, f"{len(hors)} fichiers de site/data hors datapackage (python pipeline/datapackage.py) : {hors[:10]}"


def test_l_inventaire_genere_liste_exactement_les_fichiers_versionnes(genere, versionnes):
    lignes = list(csv.DictReader(io.StringIO(genere["fichiers.csv"])))
    assert sorted(li["chemin"] for li in lignes) == versionnes
    assert all(li["ressource"] != "hors-contrat" for li in lignes)
    for li in lignes:
        assert li["url"].startswith(("https://mooneyes.github.io/", "https://raw.githubusercontent.com/"))
        assert li["url"].endswith("/" + li["chemin"])


def test_chaque_ressource_a_une_licence_et_une_source(descripteur):
    connues = {lic["path"] for lic in dpk.LICENCES.values()}
    for r in descripteur["resources"]:
        assert r.get("licenses"), r["name"]
        for lic in r["licenses"]:
            assert lic.get("name") and lic.get("path") in connues, (r["name"], lic)
        assert r.get("sources"), r["name"]
        for s in r["sources"]:
            assert s.get("title"), (r["name"], s)
            if "licence_normalisee" in s:
                assert s["licence_normalisee"] in dpk.LIBELLES_LICENCE, (r["name"], s)


def test_licence_odbl_si_une_source_de_l_etape_est_sous_odbl(descripteur):
    for r in descripteur["resources"]:
        odbl_source = any(s.get("licence_normalisee") == "ODbL-1.0" for s in r["sources"])
        noms = {lic["name"] for lic in r["licenses"]}
        assert ("ODbL-1.0" in noms) == odbl_source, r["name"]


def test_ressources_bien_formees(descripteur):
    noms = [r["name"] for r in descripteur["resources"]]
    assert len(noms) == len(set(noms))
    for r in descripteur["resources"]:
        assert re.fullmatch(r"[a-z0-9._-]+", r["name"]), r["name"]
        assert not r["path"].startswith("/") and ".." not in r["path"], r["path"]
        if r.get("jsonSchema"):
            assert (ROOT / "docs" / "schemas" / r["jsonSchema"].rsplit("/", 1)[1]).exists(), r["jsonSchema"]
        if r.get("motif"):
            assert r["nombre_fichiers"] >= 1 and r["millesimes"], r["name"]


def test_tables_csv_reprennent_les_schemas_du_datapackage_racine(descripteur):
    racine = {r["path"]: r for r in json.loads((ROOT / "datapackage.json").read_text(encoding="utf-8"))["resources"]}
    for r in descripteur["resources"]:
        if "/site/data/" in r["path"] and r.get("type") == "table":
            src = racine.get("site/data/" + r["path"].split("/site/data/", 1)[1])
            assert src and r["schema"] == src["schema"], r["name"]


def test_chaque_ressource_cite_la_version_de_ses_entrees_quand_elle_est_connue(descripteur):
    """pipeline/lignee.json : une ressource d'une étape relevée cite chaque fichier d'entrée (sha256, date)."""
    lig = json.loads((ROOT / "pipeline" / "lignee.json").read_text(encoding="utf-8"))["etapes"]
    vues = set()
    for r in descripteur["resources"]:
        etape = r.get("etape_pipeline")
        if etape not in lig:
            assert "versions_sources" not in r, r["name"]
            continue
        v = r["versions_sources"]
        vues.add(etape)
        assert v["releve"] == "pipeline/lignee.json" and v["date_sources"] == lig[etape]["date_sources"], r["name"]
        attendu = {c: f["sha256"] for c, f in lig[etape]["fichiers"].items()}
        assert {f["chemin"]: f["sha256"] for f in v["fichiers"]} == attendu, r["name"]
        for f in v["fichiers"]:
            assert re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) and f["chemin"].startswith("data/lake/"), f
            assert f["collecte_le"] == lig[etape]["fichiers"][f["chemin"]]["collecte_le"], f
    assert vues == {e for e in lig if lig[e]["fichiers"]} & {r.get("etape_pipeline") for r in descripteur["resources"]}
    assert "pipeline/lignee.json" in descripteur["versions_sources"]


def test_contributeurs_generiques_sans_nom_de_personne(descripteur):
    assert [c["title"] for c in descripteur["contributors"]] == [dpk.PROJET]
    texte = (SORTIE / "datapackage.json").read_text(encoding="utf-8") + (SORTIE / "dcat.jsonld").read_text(
        encoding="utf-8") + (SORTIE / "schemaorg.jsonld").read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", texte), "adresse électronique dans les métadonnées"


def test_generation_reproductible(genere, monkeypatch_module):
    assert dpk.construire() == genere


def test_sans_entrepot_la_lignee_versionnee_est_relue(monkeypatch, tmp_path):
    """Clone sans data/lake : sources.csv et la date sont relus dans docs/datapackage/, rien ne change."""
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    monkeypatch.setattr(dpk.reproductible, "MANIFESTE", tmp_path / "absent.json")
    sans = dpk.construire()
    assert sans["sources.csv"] == (SORTIE / "sources.csv").read_text(encoding="utf-8")
    assert json.loads(sans["datapackage.json"])["created"] == json.loads(
        (SORTIE / "datapackage.json").read_text(encoding="utf-8"))["created"]


def test_dcat_et_schema_org(descripteur):
    dcat = json.loads((SORTIE / "dcat.jsonld").read_text(encoding="utf-8"))
    assert dcat["@type"] == "dcat:Dataset" and dcat["dct:license"]["@id"].startswith("https://www.etalab.gouv.fr/")
    assert len(dcat["dcat:distribution"]) == len(descripteur["resources"]) + 1
    so = json.loads((SORTIE / "schemaorg.jsonld").read_text(encoding="utf-8"))
    assert so["@type"] == "Dataset" and so["creator"]["name"] == dpk.PROJET and so["isAccessibleForFree"] is True


def test_validation_frictionless_du_descripteur(descripteur):
    frictionless = pytest.importorskip("frictionless")
    rapport = frictionless.Package.validate_descriptor(descripteur)
    assert rapport.valid, rapport.flatten(["message"])[:5]
