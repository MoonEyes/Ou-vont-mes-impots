"""Dépenses fiscales et niches sociales (pipeline/niches.py) : contrôles sur site/data/niches, sans réseau ni entrepôt."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "niches"
sys.path.insert(0, str(ROOT / "pipeline"))
import niches  # noqa: E402

if not (DOSSIER / "index.json").exists():
    pytest.skip("site/data/niches absent", allow_module_level=True)


def _j(nom):
    return json.loads((DOSSIER / nom).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mesures():
    return _j("mesures.json")["mesures"]


@pytest.fixture(scope="module")
def index():
    return _j("index.json")


@pytest.fixture(scope="module")
def programmes():
    return _j("programmes.json")


def test_entete_et_taille():
    for f in DOSSIER.glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d.get("millesime") and d.get("source"), f.name
        assert f.stat().st_size < 5_000_000, f.name


def test_jetons_jamais_zero(mesures):
    """« nc », « ε », « - » restent des chaînes, avec meur à null ; un montant numérique a meur égal."""
    vus = set()
    for m in mesures:
        for a, c in m["couts"].items():
            if c["brut"] in ("nc", "ε", "-"):
                vus.add(c["brut"])
                assert c["meur"] is None, (m["id"], a, c)
            else:
                assert c["meur"] == float(c["brut"].replace(",", ".")), (m["id"], a, c)
    assert vus == {"nc", "ε", "-"}


def test_statut_constate_ou_estime(mesures):
    for m in mesures:
        for a, c in m["couts"].items():
            assert c["statut"] == ("constaté" if int(a) == c["plf"] - 2 else "estimé"), (m["id"], a, c)
            assert c["plf"] - 2 <= int(a) <= c["plf"]


def test_totaux_recalculables_et_conformes_aux_totaux_publies(mesures, index):
    for a, t in index["totaux"].items():
        s = sum(m["couts"][a]["meur"] or 0 for m in mesures
                if a in m["couts"] and not m["couts"][a].get("hors_reference"))
        assert abs(s - t["chiffre_meur"]) < 0.5, a
        n = sum(1 for m in mesures if a in m["couts"] and not m["couts"][a].get("hors_reference"))
        assert n == t["mesures"] == t["chiffrees"] + t["nc"] + t["epsilon"] + t["sans_effet"], a
    # années constatées : la somme des fiches retrouve le total publié de la DGFiP à 1 M€ près
    for a in ("2022", "2023", "2024"):
        assert index["totaux"][a]["statut"] == "constaté"
        assert abs(index["totaux"][a]["ecart_meur"]) <= 1, a
    assert index["totaux"]["2024"]["total_publie_meur"] == 89406
    # années estimées : écart publié, jamais lissé
    assert index["totaux"]["2026"]["ecart_meur"] > 0


def test_toutes_les_annees_2019_2026(index):
    assert sorted(index["totaux"]) == [str(a) for a in range(2019, 2027)]


def test_credit_impot_recherche(mesures):
    cir = next(m for m in mesures if m["id"] == "200302")
    assert cir["programme"]["code"] == "172"
    assert cir["programme"]["noeud_arbre"].endswith("/172")
    assert cir["couts"]["2024"] == {"brut": "7800", "meur": 7800.0, "statut": "constaté", "plf": 2026}
    assert cir["beneficiaires"]["nature"] == "Entreprises" and cir["beneficiaires"]["nombre"] > 10000
    assert cir["evaluation_2011"]["note"] == 3


def test_programmes_existent_dans_l_arbre(programmes):
    arbre = json.loads((SITE / "arbre" / "racine.json").read_text(encoding="utf-8"))
    ids = set()

    def walk(n):
        ids.add(n["id"])
        for e in n.get("enfants", []):
            walk(e)
    walk(arbre)
    for p in programmes["programmes"]:
        assert p["noeud"] in ids, p["noeud"]
        assert p["noeud"].endswith("/" + p["programme"])


def test_conservation_par_programme(mesures, programmes):
    """Somme des programmes + hors arbre = somme des mesures de l'édition de référence ; les coûts `hors_reference`
    restent hors des sommes (publiés à part) ; un programme sans mesure chiffrée est null avec sa mention, jamais 0."""
    groupes = programmes["programmes"] + programmes["hors_arbre"]
    for a in ("2024", "2025", "2026"):
        couts = [m["couts"][a] for m in mesures if a in m["couts"]]
        s_mes = sum(c["meur"] or 0 for c in couts if not c.get("hors_reference"))
        s_prog = sum(g["fiscal_meur"][a] or 0 for g in groupes)
        assert abs(s_mes - s_prog) < 1, a
        s_hors = sum(c["meur"] or 0 for c in couts if c.get("hors_reference"))
        assert abs(s_hors - sum(g.get("hors_reference_meur", {}).get(a, 0) for g in groupes)) < 1, a
        for g in groupes:
            assert (g["fiscal_meur"][a] is None) == (a in g.get("mention", {})), (g["programme"], a)
    c = programmes["couverture"]
    assert 0.9 <= c["part_rattachee"] <= 1


def test_aucun_beneficiaire_nomme(index, mesures):
    assert index["beneficiaires_nommes"]["nommes"] == 0
    for m in mesures:
        assert not {"siren", "denomination", "nom", "prenom"} & set(m), m["id"]


def test_recherche_publique_et_sources_inaccessibles(index):
    assert {r["verdict"] for r in index["recherche_publique"]} <= {"réutilisable tel quel", "à adapter",
                                                                    "inspiration seulement"}
    assert any("budget.gouv.fr" in s["source"] for s in index["sources_inaccessibles"])
    assert all(v["verdict"] == "vérifié" for v in index["verification_documents"].values())


def test_niches_sociales():
    s = _j("sociales.json")
    non_comp = s["exonerations_non_compensees"]["lignes"]
    for a in ("2024", "2025", "2026"):
        somme = sum(e["meur"][a] or 0 for e in non_comp if e["niveau"] == "mesure")
        assert abs(somme - non_comp[0]["meur"][a]) <= 3, a
    comp = s["allegements_et_exonerations_compensees"]["lignes"]
    groupe = next(e for e in comp if e["libelle"] == "EXONÉRATIONS CIBLÉES COMPENSÉES")
    somme = sum(e["meur"]["2024"] or 0 for e in comp if e["niveau"] == "mesure" and e["mission"])
    assert abs(somme - groupe["meur"]["2024"]) <= 5
    total = next(e for e in s["exemptions_assiette"]["lignes"] if e["niveau"] == "total")
    assert total["annees"]["2025"]["nettes_md"] == 15.5
    assert s["urssaf"]["totaux_meur"]["2024"] > 50_000


# --- analyseurs (sans fichier) -----------------------------------------------------------------------------------


def test_valeur():
    assert niches.valeur("nc") == {"brut": "nc", "meur": None}
    assert niches.valeur("ε") == {"brut": "ε", "meur": None}
    assert niches.valeur("-") == {"brut": "-", "meur": None}
    assert niches.valeur("7 800") == {"brut": "7800", "meur": 7800.0}
    assert niches.valeur(12) == {"brut": "12", "meur": 12.0}
    assert niches.valeur(None) is None and niches.valeur("") is None


FICHE = """         200310 – Crédit d'impôt en faveur de l'innovation
Finalité : Augmenter les dépenses de recherche et d'innovation
          Impact budgétaire (en millions d'euros)                      Création                               2012

    Réalisation          Prévision            Prévision                Modification                           2025

       2024                2025                 2026                   Fin du fait générateur                 2027

        330                  nc                  ε                     Fin d'incidence budgétaire             2028

Bénéficiaires                           11 387 Entreprises
Fiabilité du réalisé                    Très bonne
Norme fiscale de référence              Absence de crédit d'impôt
Méthode de chiffrage                    Reconstitution de base taxable à partir de données autres que fiscales
Référence                               code général des impôts 244 quater B-II-k, 199 ter B, 220 B, 223 O-1-b
Mission et programme                    Recherche et enseignement supérieur/ P192 Recherche et enseignement supérieur en matière économique
                                        et industrielle
"""


def test_lire_fiche():
    r = niches.lire_fiche("200310", FICHE.splitlines(), 2026)
    assert r["couts"] == {"2024": {"brut": "330", "meur": 330.0}, "2025": {"brut": "nc", "meur": None},
                          "2026": {"brut": "ε", "meur": None}}
    assert r["beneficiaires"] == {"nombre": 11387, "nature": "Entreprises"}
    assert r["programme"]["code"] == "192"
    assert r["programme"]["libelle"].endswith("et industrielle")
    assert r["creation"] == "2012" and r["fin_fait_generateur"] == "2027" and r["fin_incidence"] == "2028"
    assert r["methode"].startswith("Reconstitution")


def test_fiche_annees_inattendues_refusee():
    with pytest.raises(ValueError):
        niches.lire_fiche("200310", FICHE.splitlines(), 2025)
