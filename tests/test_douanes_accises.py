"""Douane et accises (pipeline/douanes_accises.py) : règles du module et cohérence des fichiers publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "douanes_accises"
sys.path.insert(0, str(ROOT / "pipeline"))
import douanes_accises as da  # noqa: E402


def _charger(nom: str) -> dict:
    return json.loads((DOSSIER / nom).read_text(encoding="utf-8"))


def _champ(d, chemin: str):
    for k in chemin.split("."):
        d = d[k]
    return d


# --- fonctions pures -----------------------------------------------------------------------------------------------

def test_absence_jamais_zero():
    for v in (None, "", "-", "*", "nc", " - "):
        assert da.nombre_publie(v) is None, v
    assert da.nombre_publie("2 197,30") == 2197.3
    assert da.nombre_publie("259*") == 259
    assert da.nombre_publie("0,0000576") == 0.0000576
    assert da.nombre_publie("37 919,49") == 37919.49


def test_normalisation_des_motifs_pdf():
    assert da._norm("DÉDOUANEMENT 3 317") == da._norm("dedouanement3317")
    assert da._norm("dontTICPE 31 660") == "dontticpe31660"


def test_produits_et_identifiants():
    assert da.IDS_PRODUITS == ["energies", "tabacs", "alcools_boissons", "droits_douane", "autres"]
    for groupe in (da.LIGNES_INSEE, da.LIGNES_OCDE):
        ids = [x[1] if groupe is da.LIGNES_INSEE else x[2] for x in groupe]
        assert len(ids) == len(set(ids))
    assert {x[2] for x in da.LIGNES_INSEE} == set(da.IDS_PRODUITS)
    assert {x[3] for x in da.LIGNES_OCDE} == set(da.IDS_PRODUITS)
    assert set(da.POSTE_PRODUIT.values()) <= set(da.IDS_PRODUITS)
    postes = [p for p, _, _ in da.POSTES]
    assert len(postes) == len(set(postes)) and set(da.POSTE_PRODUIT) <= set(postes)


def test_saisies_des_bilans_completes():
    postes = {p for p, _, _ in da.POSTES}
    assert set(da.BILAN_2022) <= postes
    for annee, (cle, valeurs) in da.BILANS_UNE_COLONNE.items():
        assert cle in da.SOURCES and set(valeurs) <= postes, annee
        assert "total" in valeurs and "droits_douane" in valeurs
        for poste, (brut, motif) in valeurs.items():
            assert motif is None or brut.replace("*", "").strip() in motif or brut in ("-", "*"), (annee, poste)


def test_sources_documentees():
    for cle, s in da.SOURCES.items():
        assert s["url"].startswith("https://") and s["licence"] and s["verdict"], cle
    assert all(x["constat"] and x["effet"] for x in da.SOURCES_INACCESSIBLES)
    verdicts = {t["verdict"] for t in da.RECHERCHE_PUBLIQUE["trouvailles"]}
    assert any(v.startswith("réutilisable tel quel") for v in verdicts)


# --- fichiers publiés ----------------------------------------------------------------------------------------------

pytestmark_fichiers = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                                         reason="site/data/douanes_accises absent")


@pytestmark_fichiers
def test_entetes_et_tailles():
    for nom in ("index.json", "series.json", "affectation.json", "perception.json"):
        d = _charger(nom)
        assert d["millesime"] and d["source"], nom
        assert (DOSSIER / nom).stat().st_size < 1_000_000, nom
    idx = _charger("index.json")
    for nom in idx["fichiers"].values():
        assert (SITE / nom).exists(), nom


@pytestmark_fichiers
def test_series_insee():
    s = _charger("series.json")
    assert s["annees"][0] == "1995" and len(s["annees"]) >= 30
    for ligne in s["lignes"]:
        assert ligne["produit"] in da.IDS_PRODUITS
        assert set(ligne["valeurs"]) == set(s["annees"])
        assert all(v is None or isinstance(v, (int, float)) for v in ligne["valeurs"].values())
    ticpe = next(x for x in s["lignes"] if x["id"] == "ticpe")["valeurs"]
    assert all(ticpe[a] is not None and ticpe[a] > 10 for a in s["annees"])


@pytestmark_fichiers
def test_affectation_sommes_et_parts():
    a = _charger("affectation.json")
    benef = [b["id"] for b in a["beneficiaires"]]
    assert benef == ["administration_centrale", "securite_sociale", "collectivites", "union_europeenne"]
    sans_ventilation = {(c["ligne"], str(c["annee"])) for c in a["controles"]}
    for ligne in a["lignes"]:
        for annee, p in ligne["serie"].items():
            assert p["total_md"] != 0
            vals = list(p["par_beneficiaire_md"].values())
            if (ligne["id"], annee) in sans_ventilation:
                assert all(v is None for v in vals)
                continue
            assert abs(sum(vals) - p["total_md"]) <= 0.003, (ligne["id"], annee)
            assert abs(sum(p["parts"].values()) - 1) <= 0.001, (ligne["id"], annee)
    douane = next(x for x in a["lignes"] if x["id"] == "droits_douane_ue")
    assert all(p["parts"]["union_europeenne"] == 1.0 for p in douane["serie"].values())


@pytestmark_fichiers
def test_perception_null_explique_et_controles_recalculables():
    p = _charger("perception.json")
    assert p["unite"] == "millions d'euros"
    assert all(v["statut"] in ("vérifié",) or v["statut"].startswith("document absent")
               for v in p["verification_documents"].values())
    postes = {x["id"]: x for x in p["postes"]}
    for x in p["postes"]:
        for annee, v in x["valeurs_m"].items():
            if v is None:
                assert annee in x.get("marques", {}), (x["id"], annee)
    for c in p["controles"]:
        assert c["ecart_m"] == round(c["somme_detail_m"] - c["publie_m"], 2)
        assert postes[c["poste"]]["valeurs_m"][str(c["annee"])] == c["publie_m"]


@pytestmark_fichiers
def test_index_ecarts_et_liens():
    idx = _charger("index.json")
    assert [x["id"] for x in idx["produits"]] == da.IDS_PRODUITS
    for e in idx["ecarts"]:
        if e["insee_md"] is not None and e["ocde_md"] is not None:
            assert e["ecart_ocde_insee_md"] == round(e["ocde_md"] - e["insee_md"], 3)
        if e["insee_md"] is not None and e["douane_percu_md"] is not None:
            assert e["ecart_douane_insee_md"] == round(e["douane_percu_md"] - e["insee_md"], 3)
    for lien in idx["liens"]:
        f = SITE / lien["fichier"]
        if f.exists():  # vue d'un autre axe : le champ cité doit exister
            _champ(json.loads(f.read_text(encoding="utf-8")), lien["champ"])
    for p in idx["produits"]:
        r = p["repartition_derniere_annee"]
        if r:
            assert abs(sum(v for v in r["par_beneficiaire_md"].values() if v is not None) - r["total_md"]) <= 0.005


@pytestmark_fichiers
def test_pas_de_total_recopie_de_recettes():
    """Les totaux Eurostat de recettes.json ne sont pas recopiés : on y renvoie par un lien."""
    texte = (DOSSIER / "series.json").read_text(encoding="utf-8") + (DOSSIER / "index.json").read_text(encoding="utf-8")
    assert '"D214A"' not in texte
    assert any(lien["fichier"] == "recettes.json" for lien in _charger("index.json")["liens"])


@pytest.mark.skipif(not (da.BRUT / da.SOURCES["insee_t_3217"]["fichier"]).exists(),
                    reason="entrepôt data/lake/douanes_accises absent (runner sans entrepôt)")
def test_production_identique_aux_fichiers_publies(tmp_path):
    da.produire(tmp_path)
    for nom in ("index.json", "series.json", "affectation.json", "perception.json"):
        assert (tmp_path / nom).read_bytes() == (DOSSIER / nom).read_bytes(), nom
