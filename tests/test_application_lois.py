"""Application des lois (pipeline/application_lois.py) : lecture, catégories financières, cohérence des comptes,
confidentialité, neutralité, reproductibilité.

Les tests sur site/data/application_lois tournent sans réseau ni entrepôt ; la reproductibilité demande l'entrepôt
(data/lake/application_lois), sautée sinon.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "application_lois"
LAKE = ROOT / "data" / "lake" / "application_lois"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
import application_lois as al  # noqa: E402
from test_neutralite import fautes, textes  # noqa: E402

INTERDITS = {"classement", "rang", "score", "note", "palmares", "taux_par_annee", "taux_moyen", "presidence",
             "gouvernement", "mots_cles"}
JUGEMENTS = re.compile(r"(?<!\w)(?:retards?|en retard|lenteur\w*|mauvais\w*|bon élève|échec\w*|réussi\w*|succès|"
                       r"inacceptable\w*|insuffisan\w*|satisfaisant\w*|trop)(?!\w)", re.I)


def lire(rel: str) -> dict:
    return json.loads((DATA / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index() -> dict:
    return lire("index.json")


@pytest.fixture(scope="module")
def finances() -> dict:
    return lire("lois_finances.json")


@pytest.fixture(scope="module")
def toutes() -> list[dict]:
    return [x for f in sorted((DATA / "lois").glob("*.json")) for x in json.loads(f.read_text(encoding="utf-8"))["lois"]]


# --- Fonctions de lecture (sans données) ---------------------------------------------------------------------------


@pytest.mark.parametrize("titre, attendu", [
    ("LOI n° 2026-103 du 19 février 2026 de finances pour 2026", "lf_initiale"),
    ("LOI de finances rectificative pour 2002 (n° 2002-1050 du 6 août 2002)", "lf_rectificative"),
    ("LOI n° 2025-1173 du 8 décembre 2025 de finances de fin de gestion pour 2025", "lf_fin_de_gestion"),
    ("LOI n° 2025-1403 du 30 décembre 2025 de financement de la sécurité sociale pour 2026", "lfss"),
    ("LOI n° 2023-270 du 14 avril 2023 de financement rectificative de la sécurité sociale pour 2023",
     "lfss_rectificative"),
    ("LOI n° 2025-1316 du 26 décembre 2025 spéciale prévue par l'article 45 de la loi organique n° 2001-692",
     "loi_speciale"),
    ("LOI n° 2006-888 du 19 juillet 2006 portant règlement définitif du budget de 2005", "reglement"),
    ("LOI n° 2024-1 du 1er janvier 2024 relative aux résultats de la gestion et portant approbation des comptes",
     "reglement"),
    ("LOI n° 2023-1195 du 18 décembre 2023 de programmation des finances publiques pour les années 2023 à 2027",
     "programmation_finances_publiques"),
    ("LOI organique n° 2005-881 du 2 août 2005 relative aux lois de financement de la sécurité sociale", None),
    ("LOI n° 2022-355 du 14 mars 2022 relative aux lois de financement de la sécurité sociale", None),
    ("LOI n° 2010-1249 du 22 octobre 2010 de régulation bancaire et financière", None),
])
def test_categorie_lue_dans_le_titre(titre, attendu):
    c = al.categorie(titre)
    assert (c[0] if c else None) == attendu


def test_dates_entiers_et_booleens():
    assert al.date_iso("24/10/2024") == "2024-10-24" and al.date_iso("1/6/2024") == "2024-06-01"
    assert al.date_iso("2024-10-24") == "2024-10-24" and al.date_iso("") is None and al.date_iso("mars 2027") is None
    assert al.entier("") is None and al.entier("0") == 0 and al.entier("12") == 12
    assert al.oui_non("oui") is True and al.oui_non("non") is False and al.oui_non("") is None


def test_titre_avec_civilite_remplace_par_sa_reference():
    t = "LOI n° 2030-12 du 3 mars 2030 portant hommage à M. Dupont"
    assert al.titre_publiable(t) == "Loi n° 2030-12 du 3 mars 2030"
    assert al.titre_publiable("LOI n° 2026-103 du 19 février 2026 de finances pour 2026").startswith("LOI n° 2026-103")


def test_texte_libre_filtre():
    prenoms = {"JEAN", "MARIE"}
    assert al.texte_publiable("Conditions d'application de l'article 3", prenoms) == (
        "Conditions d'application de l'article 3", None)
    t, motif = al.texte_publiable("Décret pris sur le rapport de Jean Martin", prenoms)
    assert t is None and "filtre de noms de personnes" in motif
    assert al.texte_publiable("", prenoms) == (None, None)


def test_delais_calcules_sur_les_mesures_appliquees_seulement():
    ms = [{"etat": "appliqué", "delai_jours": 10}, {"etat": "appliqué", "delai_jours": 30},
          {"etat": "en attente d'application", "delai_jours": None}, {"etat": "appliqué", "delai_jours": None},
          {"etat": "sans objet", "delai_jours": None}]
    d = al.delais(ms)
    assert (d["mesures"], d["minimum_jours"], d["mediane_jours"], d["maximum_jours"]) == (2, 10, 20.0, 30)
    assert d["calcule_par_le_site"] is True and d["methode"]
    assert al.delais([{"etat": "en attente d'application", "delai_jours": None}]) is None


# --- Fichiers publiés ----------------------------------------------------------------------------------------------


def test_index_sources_et_fichiers(index):
    assert {s["fichier"] for s in index["sources"]} == {"lois", "mesures"}
    for s in index["sources"]:
        assert s["licence"] == "Licence Ouverte 2.0" and al.JEU in s["url"]
    assert index["comptes"]["lois_comptes_incoherents"] == 0
    assert index["comptes"]["mesures_sans_loi_connue"] == 0
    for a in index["par_annee"]["annees"]:
        assert (ROOT / "site" / "data" / a["fichier"]).exists()
    assert index["par_annee"]["calcule_par_le_site"] is True and "Aucun taux par année" in index["par_annee"]["methode"]
    verdicts = {t["verdict"] for t in index["recherche_publique"]["trouvailles"]}
    assert verdicts <= {"réutilisable tel quel", "à adapter", "inspiration seulement"}


def test_comptes_par_annee_egalent_les_lois(index, toutes):
    par = {}
    for x in toutes:
        par.setdefault(x["annee"], []).append(x)
    assert sorted(par) == sorted(a["annee"] for a in index["par_annee"]["annees"])
    for a in index["par_annee"]["annees"]:
        lx = par[a["annee"]]
        assert a["lois"] == len(lx)
        assert a["mesures_a_appliquer"] == sum(x["mesures_a_appliquer"] or 0 for x in lx)
        assert a["mesures_appliquees"] == sum(x["mesures_appliquees"] or 0 for x in lx)
        assert a["mesures_en_attente"] == sum(x["mesures_en_attente"] for x in lx)
        assert a["mesures_sans_objet"] == sum(x["mesures_sans_objet"] for x in lx)
    assert index["comptes"]["lois"] == len(toutes)


def test_chaque_loi_coherente_avec_ses_mesures(toutes):
    for x in toutes:
        assert x["comptes_coherents"], x["id"]
        if not x["mesures_a_appliquer"]:
            assert x["taux_application_publie"] is None and "non reprise" in x["taux_note"], x["id"]
        else:
            # taux publié par LexImpact, repris tel quel (jamais recalculé, seulement contrôlé)
            assert x["taux_application_publie"] == pytest.approx(x["mesures_appliquees"] / x["mesures_a_appliquer"],
                                                                 abs=1e-6), x["id"]
        if x["fichier_mesures"] is None:
            assert x["mesures_dans_l_echeancier"] == 0
            continue
        m = json.loads((ROOT / "site" / "data" / x["fichier_mesures"]).read_text(encoding="utf-8"))
        assert m["loi"]["id"] == x["id"] and len(m["mesures"]) == x["mesures_dans_l_echeancier"]
        etats = Counter(y["etat"] for y in m["mesures"])
        assert etats["appliqué"] == x["mesures_appliquees"]
        assert etats["en attente d'application"] == x["mesures_en_attente"]
        assert etats["sans objet"] == x["mesures_sans_objet"]
        nums = [y["numero"] for y in m["mesures"]]
        assert nums == sorted(nums), x["id"]
        assert m["loi"]["delais"] == x["delais"]


def test_ordre_neutre_par_date(finances):
    listes = [finances["lois"]] + [json.loads(f.read_text(encoding="utf-8"))["lois"]
                                   for f in sorted((DATA / "lois").glob("*.json"))]
    for lst in listes:
        cles = [(x["date_publication"], x["id"]) for x in lst]
        assert [c[0] for c in cles] == sorted((c[0] for c in cles), reverse=True)
    assert finances["ordre"]["cles"] == ["-date_publication", "id"]


def test_lois_finances_priorite(finances, toutes):
    assert {x["id"] for x in finances["lois"]} == {x["id"] for x in toutes if x["categorie"]}
    cats = Counter(x["categorie"] for x in finances["lois"])
    assert cats["lf_initiale"] >= 20 and cats["lfss"] >= 20
    annees_lfi = {x["titre"] for x in finances["lois"] if x["categorie"] == "lf_initiale"}
    assert any("de finances pour 2026" in t for t in annees_lfi)
    assert {c["categorie"]: c["lois"] for c in finances["categories"]} == {
        cid: cats.get(cid, 0) for cid, _, _ in al.CATEGORIES}


def test_mesures_en_attente_sans_delai():
    for f in sorted((DATA / "mesures").glob("*.json"))[:400]:
        for m in json.loads(f.read_text(encoding="utf-8"))["mesures"]:
            if m["etat"] == "en attente d'application":
                assert m["delai_jours"] is None, f.name
            if m["decret_url"]:
                assert m["decret_url"].endswith(m["decret"])


def test_tailles_entetes_et_poids_navigateur():
    for f in DATA.rglob("*.json"):
        n = f.stat().st_size
        assert n < 5_000_000, f
        assert n < 1_000_000, f"{f.name} : trop lourd pour le navigateur"  # écran /decisions/application-des-lois
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"] and re.match(r"^\d{4}-\d{2}-\d{2}$", d["collecte_le"]), f


def test_confidentialite_aucun_nom_de_personne():
    for f in DATA.rglob("*.json"):
        brut = f.read_text(encoding="utf-8")
        assert not re.search(r'"(presidence|gouvernement|mots_cles|president|premier_ministre)"', brut), f
        d = json.loads(brut)
        for loi in d.get("lois", []) + ([d["loi"]] if "loi" in d else []):
            assert not al.CIVILITE.search(loi["titre"]), loi["id"]
        for m in d.get("mesures", []):
            for k in ("objet", "observations", "base_legale"):
                if m[k]:
                    assert not re.search(r"\b(M\.|Mme|Monsieur|Madame)\s", m[k]), (f.name, k)


def test_neutralite_aucun_qualificatif_ni_classement():
    for f in [DATA / "index.json", DATA / "lois_finances.json"] + sorted((DATA / "lois").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for cle, t in textes(d):
            assert not fautes(t), (f.name, cle, t[:80])
            assert not JUGEMENTS.search(t), (f.name, cle, t[:80])
        brut = json.dumps(d)
        for k in INTERDITS:
            assert f'"{k}"' not in brut, (f.name, k)


def test_contrat_declare_les_fichiers_de_l_axe():
    contrat = (ROOT / "docs" / "contrat_interface.md").read_text(encoding="utf-8")
    assert "`application_lois/" in contrat
    vc = (ROOT / "docs" / "valider_contrat.py").read_text(encoding="utf-8")
    for motif in ("application_lois/index.json", "application_lois/lois_finances.json", "application_lois/lois/*.json",
                  "application_lois/mesures/*.json"):
        assert motif in vc, motif


def _empreintes(dossier: Path) -> dict:
    return {str(p.relative_to(dossier)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(dossier.rglob("*.json"))}


@pytest.mark.skipif(not any(LAKE.rglob("*.csv")), reason="entrepôt data/lake/application_lois absent")
def test_production_reproductible_octet_pour_octet(tmp_path):
    al.produire(tmp_path / "a")
    al.produire(tmp_path / "b")
    a, b = _empreintes(tmp_path / "a"), _empreintes(tmp_path / "b")
    assert a == b and a == _empreintes(DATA)
