"""Délibérations et budgets au format national (pipeline/deliberations.py) : règles de confidentialité, lecture
générique des jeux, couverture ; puis contrôles des fichiers publiés dans site/data/deliberations (sautés si absent).
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "deliberations"
sys.path.insert(0, str(ROOT / "pipeline"))
import deliberations as dl  # noqa: E402

PRENOMS = {"JEAN", "MARIE", "PIERRE", "SOPHIE", "NICOLAS"}


@pytest.fixture(autouse=True)
def prenoms_fixes(monkeypatch):
    monkeypatch.setattr(dl.local, "_PRENOMS", set(PRENOMS))


# --- Règles (sans données) -------------------------------------------------------------------------------------------

def test_noms_de_personnes_exclus():
    assert dl.classer("Recrutement de Mme Durand au poste d'adjoint", "4") == (None, "nom_possible")
    assert dl.classer("Indemnités de M. Martin", "5") == (None, "nom_possible")
    assert dl.classer("Délégation à Sophie Bernard", "5") == (None, "nom_possible")
    o, m = dl.classer("Budget primitif 2025 : vote", "7")
    assert o == "Budget primitif 2025 : vote" and m is None


@pytest.mark.parametrize("objet", [
    "Droit de préemption urbain : acquisition au 12 rue des Lilas",
    "Cession de la parcelle AB 123 au lieu-dit La Lande",
    "Acquisition propriété Dupont",
    "Vente d'un terrain aux consorts Le Goff",
    "Préemption du bien DURAND",
    "ACQUISITION TERRAIN COMMUNAL",          # tout en capitales : prudence
    "Échange de terrains avec l'indivision",
    "Bail emphytéotique section ZK numéro 45",
    "URBANISME - Acquisition des terrains de Gerbith",
    "FONCIER - Cession ROBERT",
    "D - Proposition achat maison 5 les champs de roz",
])
def test_foncier_designant_un_particulier_exclu(objet):
    assert dl.classer(objet, "3") == (None, "foncier_particulier"), objet


@pytest.mark.parametrize("objet,mat", [
    ("Modification simplifiée du PLU", "2"),
    ("Instauration du droit de préemption urbain sur les zones U et AU du PLUi", "2"),
    ("Tarifs de la cantine scolaire", "7"),
    ("Logement de l'école : révision du loyer au 1er janvier 2024", "3"),
    ("Bail commercial de 9 ans pour le local de la mairie", "3"),
    ("URBANISME - Modification simplifiée n°2 du PLU", "2"),
    ("Domaine public : Convention d'occupation avec ENEDIS", "3"),
])
def test_objets_generaux_publies(objet, mat):
    o, m = dl.classer(objet, mat)
    assert m is None and o == objet


def test_adresse_exclue_partout():
    assert dl.classer("Aide à la rénovation de façade, 3 rue des Lilas", "7") == (None, "adresse_possible")


def test_objet_tronque_et_vide():
    o, _ = dl.classer("Travaux " + "x" * 300, "1")
    assert len(o) == dl.LONGUEUR_OBJET
    assert dl.classer("", "1") == (None, "objet_vide") and dl.classer(None, "1") == (None, "objet_vide")


def test_liens():
    assert dl.lien_publiable("https://exemple.fr/actes/2025/delib_12.pdf") == "https://exemple.fr/actes/2025/delib_12.pdf"
    assert dl.lien_publiable("ftp://exemple.fr/a.pdf") is None and dl.lien_publiable("") is None
    assert dl.lien_publiable("https://exemple.fr/actes/vente_jean_dupont.pdf") is None
    assert dl.lien_publiable("https://exemple.fr/actes/M._Durand.pdf") is None


def test_dates_et_matieres():
    assert dl.date_iso("2025-02-03") == "2025-02-03" and dl.date_iso("03/02/2025") == "2025-02-03"
    assert dl.date_iso("2025/02/03 10:00") == "2025-02-03"
    assert dl.date_iso("31/02/2025") is None and dl.date_iso("") is None and dl.date_iso("1790-01-01") is None and dl.date_iso("1869-01-14") == "1869-01-14"
    assert dl.code_matiere("7.5") == "7.5" and dl.code_matiere("7-5") == "7.5" and dl.code_matiere("abc") == ""
    assert dl.matiere("7.10") == "7" and dl.matiere("") == "0"


def test_etapes_budgetaires():
    assert dl.etape("Budget primitif") == "budget_primitif" and dl.etape("COMPTE ADMINISTRATIF") == "compte_administratif"
    assert dl.etape("Décision modificative n°2") == "decision_modificative" and dl.etape("xyz") == "autre"


def test_lecture_generique_csv_et_json(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("COLL_NOM;COLL_SIRET;DELIB_ID;DELIB_DATE;DELIB_MATIERE_CODE;DELIB_OBJET;VOTE_POUR;DELIB_URL\n"
                 "Commune X;21440109300015;D1;2025-01-02;7.1;Budget;12;https://x.fr/1.pdf\n", encoding="utf-8")
    cols, rows = dl.lignes_fichier(f)
    assert "COLL_SIRET" in cols and rows[0]["DELIB_OBJET"] == "Budget"
    g = tmp_path / "b.json"
    g.write_text(json.dumps({"data": [{"COLL_SIRET": "21440109300015", "DELIB_DATE": "2025-01-02",
                                        "DELIB_OBJET": "Budget"}]}), encoding="utf-8")
    cols, rows = dl.lignes_fichier(g)
    assert rows[0]["COLL_SIRET"] == "21440109300015"


def test_extrait_budget(tmp_path):
    brut = tmp_path / "b.csv"
    brut.write_text(
        "BGT_NATDEC,BGT_ANNEE,BGT_SIRET,BGT_NOM,BGT_CONTNAT,BGT_NATURE,BGT_OPBUDG,BGT_CODRD,BGT_MTREAL,BGT_MTPROPNOUV,"
        "BGT_MTPREV,BGT_CREDOUV\n"
        "budget primitif,2025,21440109300015,Commune,21,2152,réel,dépense,,1000,,\n"
        "budget primitif,2025,21440109300015,Commune,23,2313,réel,dépense,,\"2 500,5\",,\n"
        "budget primitif,2025,21440109300015,Commune,204,2041582,réel,dépense,,300,,\n"
        "budget primitif,2025,21440109300015,Commune,21,2152,ordre,dépense,,999,,\n"
        "budget primitif,2025,21440109300015,Commune,011,6064,réel,dépense,,50,,\n", encoding="utf-8")
    dest = tmp_path / "x.extrait.csv"
    assert dl.extraire_budget(brut, dest, "csv")["etat"] == "lu"
    lignes = dest.read_text(encoding="utf-8").splitlines()
    assert lignes[0].startswith("siret;annee;etape;poste")
    postes = {l.split(";")[3]: l.split(";")[5] for l in lignes[1:]}
    assert postes["c21"] == "1000.0" and postes["c23"] == "2500.5" and postes["c204"] == "300.0"
    assert "hors" in postes and "autre" in postes  # ordre et fonctionnement à part


def test_aucun_vote_ni_texte_publie():
    """Les colonnes de vote et le texte des actes ne sont jamais lus dans la production."""
    code = (ROOT / "pipeline" / "deliberations.py").read_text(encoding="utf-8")
    lecture = code[code.index("def lire_deliberations"):code.index("def produire(")]
    assert "vote" not in lecture.lower()


# --- Fichiers publiés -----------------------------------------------------------------------------------------------

publie = pytest.mark.skipif(not (DOSSIER / "index.json").exists(), reason="site/data/deliberations absent")


@publie
def test_index_couverture_et_absence():
    idx = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
    assert idx["millesime"] and idx["source"] and idx["absence"] == dl.ABSENCE
    c = idx["couverture"]["commune"]
    assert 0 < c["publient"] <= c["total"] and 0 < c["part_nombre"] < 1 and 0 < c["part_population"] < 1
    assert idx["statut_couverture"] == "calculé par le site"
    for s, v in idx["collectivites"].items():
        assert re.match(r"^\d{9}$", s) and (DOSSIER / "collectivites" / f"{s}.json").exists()
        assert v["type"] in dl.LIB_TYPES


@publie
def test_fichiers_petits_sans_personne():
    civ = re.compile(r"\b(M\.|Mme|Monsieur|Madame)\s", re.I)
    for f in sorted(DOSSIER.rglob("*.json")):
        assert f.stat().st_size < dl.MAX_OCTETS, f
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"]
        for lignes in (d.get("recentes") or {}).values():
            for date_, code, objet, lien, jeu in lignes:
                assert re.match(r"^\d{4}-\d{2}-\d{2}$", date_) and objet and not civ.search(objet), objet
                assert lien is None or lien.startswith("http")
        texte = f.read_text(encoding="utf-8").lower()
        assert "vote_pour" not in texte and "vote_contre" not in texte
