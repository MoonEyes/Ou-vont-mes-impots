"""Douane et accises (pipeline/douanes_accises.py) : produit par accise, recettes perçues par la douane, affectation.

Les tests sur site/data/douanes_accises tournent sans réseau ; la reproduction octet pour octet demande l'entrepôt
(data/lake/douanes_accises), sautée sinon.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "douanes_accises"
LAKE = ROOT / "data" / "lake" / "douanes_accises"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "docs"))
from test_neutralite import fautes, textes  # noqa: E402

FICHIERS = {"index.json": "douanes_accises_index.schema.json", "produits.json": "douanes_accises_produits.schema.json",
            "collecte.json": "douanes_accises_collecte.schema.json",
            "affectation.json": "douanes_accises_affectation.schema.json"}


def _lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def docs():
    return {nom: _lire(nom) for nom in FICHIERS}


def test_entetes_et_tailles(docs):
    for nom, d in docs.items():
        assert d["millesime"] and d["source"], nom
        assert (DATA / nom).stat().st_size < 1_000_000, nom
    assert sorted(p.name for p in DATA.glob("*.json")) == sorted(FICHIERS)


def test_schemas(docs):
    import valider_contrat as vc
    for nom, schema in FICHIERS.items():
        v = vc.validateur(vc.charger_jsonschema(), schema)
        erreurs = vc.erreurs(v, docs[nom])
        assert not erreurs, (nom, erreurs)


def test_produits_alignes_et_sans_doublon_des_agregats(docs):
    p = docs["produits.json"]
    assert p["annees"] == list(range(p["annees"][0], p["annees"][-1] + 1))
    assert p["annees"][0] <= 1995 and p["annees"][-1] >= 2024
    ids = [x["id"] for x in p["produits"]]
    assert len(ids) == len(set(ids))
    for x in p["produits"]:
        assert len(x["valeurs_md"]) == len(p["annees"]), x["id"]
        assert all(v is None or v >= 0 for v in x["valeurs_md"]), x["id"]
    # Aucun agrégat d'Eurostat recopié : renvoi vers recettes.json.
    assert p["renvoi_agregats"]["fichier"] == "recettes.json"
    assert not {"D214A", "D2", "D214"} & set(ids)
    tic = next(x for x in p["produits"] if x["id"] == "accise_produits_energetiques")
    assert 25 < tic["valeurs_md"][p["annees"].index(2024)] < 40


def test_collecte_nulls_justifies_et_coherence(docs):
    c = docs["collecte.json"]
    n = len(c["annees"])
    assert c["annees"] == sorted(c["annees"]) and len(set(c["annees"])) == n
    for p in c["postes"]:
        assert len(p["valeurs_m"]) == n, p["id"]
        for a, v in zip(c["annees"], p["valeurs_m"]):
            if v is None:
                assert str(a) in p.get("null_raisons", {}), (p["id"], a)
            else:
                assert v >= 0, (p["id"], a)
    total = next(p for p in c["postes"] if p["id"] == "total")
    assert None not in total["valeurs_m"]
    groupes = {p["id"]: p["valeurs_m"] for p in c["postes"]}
    for ligne in c["coherence"]:
        i = c["annees"].index(ligne["annee"])
        somme = sum(groupes[g][i] for g in c["groupes"] if g in groupes and groupes[g][i] is not None)
        assert abs(somme - ligne["somme_groupes_m"]) < 0.01
        assert abs(ligne["total_publie_m"] - ligne["somme_groupes_m"] - ligne["ecart_m"]) < 0.01
        assert abs(ligne["ecart_m"]) < 0.5 / 100 * ligne["total_publie_m"], ligne
    for d in c["destination"]:
        if d["statut"] == "non_publie":  # attribution non écrite par la source : aucune part publiée
            assert d["parts"] == []
            continue
        assert abs(sum(x["pct"] for x in d["parts"]) - 100) < 0.2, d["annee"]
        assert {x["destinataire"] for x in d["parts"]} <= set(c["destinataires"])


def test_affectation(docs):
    a = docs["affectation.json"]
    e = a["energie"]
    # La ventilation 2025 du site n'est pas recopiée dans la série des exécutions.
    assert e["deja_dans_le_site"]["annee"] not in e["executions"]["annees"]
    assert e["executions"]["annees"] == sorted(e["executions"]["annees"])
    for ed in e["editions"]:
        assert ed["statuts"][0] == "execution"
        lignes = {ln["id"]: ln["valeurs_md"] for ln in ed["lignes"]}
        for k in range(3):
            transferts = sum(lignes[x][k] or 0 for x in ("collectivites_territoriales", "afitf", "idfm", "zni_cspe",
                                                         "autres") if x in lignes)
            # brute État = brute totale + transferts (signes de la source), aux arrondis du tableau près
            assert abs(lignes["brute_totale"][k] + transferts - lignes["brute_etat"][k]) <= 0.25, (ed["document"], k)
        for ln in ed["lignes"]:
            if "destinataire" in ln:
                assert ln["destinataire"] in a["destinataires"]
    for produit in ("tabacs", "alcools"):
        cles = a[produit]["cles"]
        for i, an in enumerate(cles["annees"]):
            assert abs(sum(p["pct"][i] or 0 for p in cles["parts"]) - 100) < 0.011, (produit, an)
        assert {p["destinataire"] for p in cles["parts"]} <= set(a["destinataires"])
    fp = a["droits_de_douane"]["frais_perception"]
    assert [x["annee"] for x in fp] == sorted(x["annee"] for x in fp)
    assert all(x["citation"] for x in fp)


def test_verification_et_recherche(docs):
    i = docs["index.json"]
    assert i["verification_documents"]
    for doc, v in i["verification_documents"].items():
        assert v["statut"] == "vérifié" and not v["manquants"] and v["motifs"] > 0, doc
    assert {s["id"] for s in i["sources"]} >= set(i["verification_documents"])
    assert i["recherche_publique"]["verdict"]
    for t in i["recherche_publique"]["trouvailles"]:
        assert t["classement"] and t["licence"]


def test_ecarts_montres_sans_trancher(docs):
    for bloc in docs["index.json"]["ecarts_entre_sources"]:
        for ln in bloc["lignes"]:
            assert abs(ln["comptes_nationaux_md"] - ln["percu_douane_md"] - ln["ecart_md"]) < 0.002


def test_neutralite(docs):
    erreurs = [(nom, cle, t, f) for nom, d in docs.items() for cle, t in textes(d) for f in fautes(t)]
    assert not erreurs, erreurs[:5]


@pytest.mark.skipif(not (LAKE / "douanes_bilan_2025.pdf").exists(), reason="entrepôt data/lake/douanes_accises absent")
def test_reproduction_octet_pour_octet(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "pipeline" / "douanes_accises.py"), "produire", "--sortie",
                    str(tmp_path)], check=True, capture_output=True)
    for nom in FICHIERS:
        assert (tmp_path / nom).read_bytes() == (DATA / nom).read_bytes(), nom
