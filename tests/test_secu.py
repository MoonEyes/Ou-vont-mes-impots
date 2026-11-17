"""Sécurité sociale (pipeline/secu.py) : cohérence des arbres publiés dans site/data/secu, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
SECU = SITE / "secu"
sys.path.insert(0, str(ROOT / "pipeline"))
import secu  # noqa: E402

if not (SECU / "index.json").exists():
    pytest.skip("site/data/secu absent : lancer `python pipeline/secu.py produire`", allow_module_level=True)

INDEX = json.loads((SECU / "index.json").read_text(encoding="utf-8"))


def charger(rel):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


def parcourir(n, visite):
    """Parcourt l'arbre en chargeant les sous-arbres découpés ; visite(noeud, enfants)."""
    if "fichier" in n:
        sous = charger(n["fichier"])
        assert sous["id"] == n["id"] and abs(sous["md"] - n["md"]) < 1e-6
        n = sous
    enfants = n.get("enfants", [])
    visite(n, enfants)
    for e in enfants:
        parcourir(e, visite)


@pytest.mark.parametrize("vue", ["arbre", "arbre_2025", "cps"])
def test_chaque_noeud_vaut_la_somme_de_ses_enfants(vue):
    racine = charger(INDEX["vues"][vue]["fichier"])
    assert abs(racine["md"] - INDEX["vues"][vue]["total_md"]) < 1e-6
    ecarts = []

    def visite(n, enfants):
        if enfants and abs(sum(e["md"] for e in enfants) - n["md"]) > 2e-5:
            ecarts.append(n["id"])
    parcourir(racine, visite)
    assert not ecarts, ecarts[:5]


@pytest.mark.parametrize("vue", ["arbre", "arbre_2025", "cps"])
def test_feuilles_tracees_et_sources_declarees(vue):
    racine = charger(INDEX["vues"][vue]["fichier"])
    declarees = set(racine["sources_detail"]) | set(INDEX["sources"])
    feuilles = []

    def visite(n, enfants):
        assert set(n["sources"]) <= declarees, n["id"]
        if not enfants:
            feuilles.append(n)
            assert n["mode"] in {"publie", "tableau_image", "derive", "ecart"}
            assert n["tracabilite_pct"] == (100.0 if n["mode"] in ("publie", "tableau_image") else 0.0)
            if n["mode"] in ("derive", "ecart"):
                assert n.get("note") or n["id"].endswith(("arrondis", "non_ventile", "_nv")), n["id"]
    parcourir(racine, visite)
    direct = sum(abs(f["md"]) for f in feuilles if f["mode"] in ("publie", "tableau_image"))
    total = sum(abs(f["md"]) for f in feuilles)
    assert abs(100 * direct / total - INDEX["vues"][vue]["tracabilite_pct"]) < 0.1


def noeuds(rel):
    out = {}
    parcourir(charger(rel), lambda n, e: out.__setitem__(n["id"], n))
    return out


def test_montants_publies_du_placss_2024():
    n = noeuds("secu/arbre/racine.json")
    assert n["robss"]["md"] == pytest.approx(secu.ROBSS_2024_TOTAL_Y_C_FSV, abs=1e-6)
    for k, v in secu.ROBSS_2024.items():
        assert n[f"robss/{k}"]["md"] == pytest.approx(v, abs=1e-6)
    assert n["robss/fsv"]["md"] == pytest.approx(20.457, abs=1e-6)
    assert n["robss/transferts_internes"]["md"] < 0
    # ONDAM 2024 constaté (256,4 Md€) = sous-objectifs maladie + médico-social (branche autonomie)
    ondam = sum(n[f"robss/maladie/{k}"]["md"] for k in ("ondam_soins_de_ville", "ondam_etablissements", "ondam_fir",
                                                       "ondam_autres", "ondam_crise"))
    ondam += n["robss/autonomie/ondam_pa"]["md"] + n["robss/autonomie/ondam_ph"]["md"]
    assert ondam == pytest.approx(256.4, abs=0.1)
    assert n["unedic"]["md"] == pytest.approx(45.201, abs=1e-6)
    assert n["cades/amortissement"]["md"] == pytest.approx(16.0, abs=0.05)


def test_ecarts_entre_sources_visibles_et_non_lisses():
    n = noeuds("secu/arbre/racine.json")
    e = {x["source"]: x["md"] for x in n["robss/maladie"]["ecarts"]}
    assert e["placss2024_a1_maladie"] == 218.9 and e["dss_chiffres_cles_2024"] == 234.6
    assert n["robss/maladie/hors_ondam"]["mode"] == "ecart"


def test_destinataires_existent_dans_affectation():
    aff = SITE / "prelevements" / "affectation.json"
    if not aff.exists():
        pytest.skip("prelevements/affectation.json absent")
    connus = set(json.loads(aff.read_text(encoding="utf-8"))["destinataires"])
    trouves = set()
    for vue in INDEX["vues"].values():
        parcourir(charger(vue["fichier"]), lambda n, e: trouves.add(n["destinataire"]) if "destinataire" in n else None)
    assert trouves and trouves <= connus, trouves - connus
    assert {"cnam", "cnav", "cnaf", "cnsa", "branche_atmp", "agirc_arrco", "unedic", "cades"} <= trouves


def test_vue_drees_conserve_le_total_publie():
    n = noeuds("secu/cps/racine.json")
    assert n["racine"]["md"] == pytest.approx(933.16053, abs=1e-4)
    assert INDEX["vues"]["cps"]["profondeur"] >= 5


def test_aucune_donnee_individuelle():
    for p in SECU.rglob("*.json"):
        t = p.read_text(encoding="utf-8").lower()
        assert "prenom" not in t and "prénom" not in t and "siren" not in t, p


def test_fichiers_compacts_et_entete():
    for p in SECU.rglob("*.json"):
        assert p.stat().st_size < 1_000_000, p
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d.get("millesime") and d.get("source"), p


def test_recherche_publique_classee():
    verdicts = {t["verdict"].split(" (")[0] for t in INDEX["recherche_publique"]["trouvailles"]}
    assert verdicts <= {"réutilisable tel quel", "à adapter", "inspiration seulement", "aucun dépôt pertinent"}


@pytest.mark.skipif(not (secu.BRUT / secu.SOURCES["unedic"]["fichier"]).exists(), reason="entrepôt absent")
def test_unedic_detail_somme_au_total():
    u = secu.lire_unedic()
    assert u["2024"]["total"] == 45201


@pytest.mark.skipif(not all((secu.BRUT / s["fichier"]).exists() for s in secu.SOURCES.values()),
                    reason="entrepôt absent")
def test_montants_saisis_retrouves_dans_les_documents():
    verif = secu.verifier_documents()
    assert all(v["statut"].startswith("vérifié") or "absent" in v["statut"] for v in verif.values())
