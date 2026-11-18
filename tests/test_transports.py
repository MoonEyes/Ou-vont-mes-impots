"""Transports (pipeline/transports.py) : règles du module et cohérence des fichiers publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "transports"
sys.path.insert(0, str(ROOT / "pipeline"))
import transports  # noqa: E402

# --- fonctions pures (toujours testées) ------------------------------------------------------------------------------


def test_absence_jamais_zero():
    for v in (None, "", "-", "nd", "nc", True, float("nan")):
        assert transports.nombre(v) is None, v
    assert transports.nombre("1 234,5") == 1234.5 and transports.nombre(0) == 0
    assert transports.arrondi(794.4030256100001) == 794.403 and transports.arrondi(561.0) == 561


def test_libelles_normalises():
    assert transports.norm("Taxe sur l’exploitation (1)") == "taxe sur l'exploitation"
    assert transports.norm("  SNCF-Intercités (3) ") == "sncf-intercites"
    assert transports._reconnaitre("Fraction d'accises perçue sur les carburants (Ex TICPE)",
                                   transports.RECETTES_AFITF) == "accises_carburants"
    assert transports._reconnaitre("TICPE", transports.RECETTES_AFITF) == "accises_carburants"
    assert transports._reconnaitre("Taxe sur l’exploitation des infrastructures de transport de longue distance (TEITL)",
                                   transports.RECETTES_AFITF) == "teitld"
    assert transports._reconnaitre("Transports collectifs et mobilités", transports.MODES_AFITF) == "tca"


def test_ecart_recalculable_et_tolerance():
    e = transports.ecart("x", 2024, "a", 110, "b", 100, "lecture")
    assert e["ecart"] == 10 and e["ecart_pct"] == 10.0
    assert transports.ecart("x", 2024, "a", None, "b", 100, "l") is None
    assert transports.ecart("x", 2024, "a", 100.0004, "b", 100, "l", tolerance=0.001) is None


def test_controle_somme_publie_l_ecart_sans_corriger():
    t = {"onglet": "T", "annees": [2023, 2024],
         "lignes": {"total": {"valeurs": [10, 12]}, "a": {"valeurs": [4, 5]}, "b": {"valeurs": [6, None]}}}
    out = transports.controle_somme(t, "total", ["a", "b"], "essai")
    assert len(out) == 1 and out[0]["annee"] == 2024 and out[0]["ecart"] == 7 and out[0]["lignes_vides"] == ["b"]
    assert t["lignes"]["total"]["valeurs"] == [10, 12]


def test_sources_documentees_et_au_catalogue():
    cat = {s["id"]: s for s in json.loads(transports.CATALOGUE.read_text(encoding="utf-8"))["sources"]}
    for cle, s in transports.SOURCES.items():
        assert s["id_catalogue"] in cat, cle
        assert s["page"].startswith("https://") and s["licence"] and s["producteur"] and s["verdict"], cle
    for t in transports.RECHERCHE_PUBLIQUE["trouvailles"]:
        assert t["url"].startswith("https://") and t["licence"] and t["verdict"]


# --- fichiers publiés --------------------------------------------------------------------------------------------------

publie = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                            reason="site/data/transports absent : lancer `python pipeline/transports.py produire`")


def charger(nom):
    return json.loads((DOSSIER / nom).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def afitf():
    return charger("afitf.json")


@publie
def test_budgets_afitf_retombent_sur_leurs_totaux(afitf):
    assert [b["annee"] for b in afitf["budgets"]] == sorted(b["annee"] for b in afitf["budgets"])
    assert {b["nature"] for b in afitf["budgets"]} <= {"budget exécuté", "budget initial"}
    for b in afitf["budgets"]:
        assert [m["id"] for m in b["modes"]] == [k for k, _ in transports.MODES_AFITF]
        for col in ("ae", "cp"):
            assert abs(sum(m[col] or 0 for m in b["modes"]) - b["total"][col]) <= 1, (b["annee"], col)
        assert abs(sum(r["montant"] or 0 for r in b["recettes"]) - b["total_recettes"]) <= 1, b["annee"]
        for c in b["controles"]:   # écart publié = exactement le plan de relance du mode
            m = next(m for m in b["modes"] if m["id"] == c["mode"])
            assert abs(c["ecart"] - m["dont_plan_de_relance"][c["colonne"]]) <= 1


@publie
def test_ordres_de_grandeur(afitf):
    b2024 = next(b for b in afitf["budgets"] if b["annee"] == 2024)
    assert 4.0e9 < b2024["total"]["cp"] < 4.6e9 and 4.0e9 < b2024["total_recettes"] < 4.4e9
    vm = charger("versement_mobilite.json")["serie"]
    ens = next(li for li in vm["lignes"] if li["id"] == "ensemble")["valeurs"]
    assert 10_000 < ens[vm["annees"].index(2024)] < 15_000 and vm["statut_annees"]["2024"] == "provisoire"
    p = {x["numero"]: x for x in charger("programmes.json")["programmes"]}
    assert 203 in p and 2.5e9 < next(a for a in p[203]["actions"] if a["code"] == "203-41")["execution_2024"] < 4e9


@publie
def test_tableaux_alignes_et_absences_null():
    for nom in ("afitf.json", "ferroviaire.json", "programmes.json", "versement_mobilite.json"):
        def tableaux(x):
            if isinstance(x, dict):
                if "onglet" in x and "lignes" in x:
                    yield x
                for v in x.values():
                    yield from tableaux(v)
            elif isinstance(x, list):
                for v in x:
                    yield from tableaux(v)
        vus = 0
        for t in tableaux(charger(nom)):
            vus += 1
            for li in t["lignes"]:
                assert len(li["valeurs"]) == len(t["annees"]), (nom, t["onglet"], li["id"])
            nuls = {(li["id"], a) for li in t["lignes"] for a, v in zip(t["annees"], li["valeurs"]) if v is None}
            assert nuls == {(a["ligne"], a["annee"]) for a in t["absences"]}, (nom, t["onglet"])
        assert vus, nom


@publie
def test_liens_vers_fichiers_existants_et_aucun_montant_par_commune():
    def liens(x):
        if isinstance(x, dict):
            if isinstance(x.get("fichier"), str):
                yield x["fichier"]
            for v in x.values():
                yield from liens(v)
        elif isinstance(x, list):
            for v in x:
                yield from liens(v)
    for nom in ("index.json", "programmes.json", "versement_mobilite.json"):
        for f in liens(charger(nom)):
            assert (SITE / f).exists(), (nom, f)
    texte = (DOSSIER / "versement_mobilite.json").read_text(encoding="utf-8")
    assert "communes" not in json.loads(texte)


@publie
def test_ecarts_montres_sans_trancher():
    idx = charger("index.json")
    for e in idx["ecarts"]:
        assert e["source"] != e["autre_source"] and e["lecture_ecart"]
        assert abs((e["valeur"] - e["autre_valeur"]) - e["ecart"]) < 0.01
    assert set(idx["fichiers"]) == {"afitf", "ferroviaire", "programmes", "versement_mobilite"}
    for r in idx["reperes"]:
        assert r["valeur"] is None or r["valeur"] > 0


def test_reproductible_si_entrepot_present(tmp_path, monkeypatch):
    if not (transports.LAKE / transports.SOURCES["sdes"]["entrepot"]).exists():
        pytest.skip("entrepôt absent (data/lake/transports) : lancer `python pipeline/transports.py collecter`")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1767225600")
    transports.produire(tmp_path / "a")
    transports.produire(tmp_path / "b")
    for f in sorted((tmp_path / "a").iterdir()):
        assert f.read_bytes() == (tmp_path / "b" / f.name).read_bytes(), f.name
