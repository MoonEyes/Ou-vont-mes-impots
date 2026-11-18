"""Solidarités des départements (pipeline/solidarites_departements.py) : règles du module et cohérence des fichiers
publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "solidarites_departements"
sys.path.insert(0, str(ROOT / "pipeline"))
import solidarites_departements as sd  # noqa: E402


# --- fonctions pures (toujours testées) ------------------------------------------------------------------------------

def test_absence_jamais_zero():
    for v in (None, "", "-", "nd", "NR", " ", True):
        assert sd.nombre(v) is None and sd.entier(v) is None, v
    assert sd.marque("-") == "-" and sd.marque("nd") == "nd" and sd.marque(12) is None and sd.marque(None) is None
    assert sd.entier(0) == 0 and sd.entier("1 234") == 1234 and sd.entier(12.6) == 13
    assert sd.euros(None) is None and sd.euros(2.5) == 2 and sd.euros(3.5) == 4
    assert sd.par_habitant(100, None) is None and sd.par_habitant(None, 10) is None
    assert sd.par_habitant(1000, 3) == 333.33


def test_collectivites_lues_par_siren():
    # le code 67A de l'OFGL porte deux lignes par exercice jusqu'en 2020 (Bas-Rhin, Haut-Rhin)
    assert sd.code_comptes("67A", "226700011", 2019) == "67"
    assert sd.code_comptes("67A", "226800019", 2019) == "68"
    assert sd.code_comptes("67A", "200094332", 2021) == "6AE"
    with pytest.raises(SystemExit):
        sd.code_comptes("67A", "999999999", 2021)
    assert sd.code_comptes("69", "226900017", 2014) == "69"
    assert sd.code_comptes("69", "226900017", 2015) == "69D"
    assert sd.code_comptes("691", "200046977", 2015) == "69M"
    assert sd.code_comptes("44", "224400028", 2024) == "44"
    assert sd.departements_de("6AE") == ["67", "68"] and sd.departements_de("20R") == ["2A", "2B"]
    assert sd.departements_de("69M") == ["69"] and sd.departements_de("971") == ["971"]


def test_meme_perimetre_seulement_pour_les_ecarts():
    assert sd.code_drees_pour("67", 2020) == "67" and sd.code_drees_pour("67", 2021) is None
    assert sd.code_drees_pour("6AE", 2020) is None and sd.code_drees_pour("6AE", 2021) == "6AE"
    assert sd.code_drees_pour("69", 2014) == "69" and sd.code_drees_pour("69", 2015) is None
    assert sd.code_drees_pour("2A", 2017) == "2A" and sd.code_drees_pour("2A", 2018) is None
    assert sd.code_drees_pour("01", 2024) == "01"


def test_financeur_du_rsa():
    rec = {"93": {"premiere_annee_entiere": 2022}, "09": {"premiere_annee_entiere": 2023, "debut": "décembre 2022"}}
    assert sd.financeur_rsa("01", 2024, rec) == "departement"
    assert sd.financeur_rsa("93", 2021, rec) == "departement" and sd.financeur_rsa("93", 2022, rec) == "etat"
    assert sd.financeur_rsa("09", 2022, rec) == "departement_puis_etat"
    assert sd.financeur_rsa("09", 2023, rec) == "etat"


def test_reste_a_charge_calcule_et_null_si_composante_absente():
    vals = {"allocations_rsa": 100.0, "allocations_apa": 50.0, "allocations_pch": 30.0, "frais_hebergement": 9.0,
            "ticpe": 60.0, "fmdi": 5.0, "cnsa": 20.0}
    assert sd.reste_a_charge(vals, "01", 2024, {}) == {"rsa": 35, "apa_pch": 60}
    assert sd.reste_a_charge({**vals, "fmdi": None}, "01", 2024, {})["rsa"] is None
    assert sd.reste_a_charge({**vals, "cnsa": None}, "01", 2024, {})["apa_pch"] is None
    # RSA financé par l'État : pas de reste à charge du RSA ; APA et PCH toujours calculés
    r = sd.reste_a_charge(vals, "93", 2024, {"93": {"premiere_annee_entiere": 2022}})
    assert r == {"rsa": None, "apa_pch": 60}
    # collectivité unique : TICPE régionale et départementale confondues
    assert sd.reste_a_charge(vals, "972", 2016, {})["rsa"] is None
    assert sd.reste_a_charge(vals, "972", 2015, {})["rsa"] == 35
    assert sd.reste_a_charge(vals, "20R", 2018, {})["rsa"] is None


def test_ecart_publie_jamais_tranche():
    e = sd.ecart("a", 110, "b", 100, annee=2024)
    assert e["ecart"] == 10 and e["ecart_pct"] == 10.0 and e["annee"] == 2024
    assert sd.ecart("a", None, "b", 100) is None and sd.ecart("a", 5, "b", None) is None
    assert sd.ecart("a", 5, "b", 0)["ecart_pct"] is None


def test_entetes_drees():
    assert sd._annees_entete(["Code région", "Code département", "Département", "2002", 2003, "2010 (2)", None]) == {
        3: 2002, 4: 2003, 5: 2010}
    assert sd._cle_total("TOTAL estimé France métropolitaine") == "metropole"
    assert sd._cle_total("TOTAL estimé DROM, hors Mayotte") == "drom"
    assert sd._cle_total("TOTAL estimé France entière, hors Mayotte") == "france"
    assert sd._cle_total("TOTAL estimé France") == "france"
    assert sd._cle_total("Ain") is None


def test_sources_documentees():
    for cle, s in sd.SOURCES.items():
        assert s["titre"] and s["page"] and s["producteur"] and s["licence"] and s["millesime"], cle
        assert s["verdict"].startswith(("réutilisable tel quel", "à adapter", "inspiration seulement")), cle
        if s.get("url"):
            assert s["url"].startswith("https://"), cle
    assert set(sd.COLLECTABLES) >= {s["id_catalogue"] for s in sd.SOURCES.values() if s.get("id_catalogue")}
    catalogue = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    ids = {s["id"] for s in catalogue["sources"]}
    assert set(sd.COLLECTABLES) <= ids, set(sd.COLLECTABLES) - ids
    for t in sd.RECHERCHE_PUBLIQUE["trouvailles"]:
        assert t["licence"] and t["verdict"] and (t.get("dernier_commit") or t.get("mise_a_jour")), t["nom"]
    assert any("CNSA" in i["source"] for i in sd.INACCESSIBLES)


def test_series_et_colonnes_uniques():
    ids = [s[0] for s in sd.SERIES]
    assert len(ids) == len(set(ids))
    assert {s[3] for s in sd.SERIES} <= set(sd.GROUPES)
    assert len(sd.COLONNES) == len(set(sd.COLONNES)) == 7
    for cle, f in sd.RESTE_A_CHARGE.items():
        assert set(f["allocations"] + f["recettes"]) <= set(sd.COLONNES), cle
    assert set(sd.LECTURES_ECARTS) == set(sd.SOURCES_ECARTS)


# --- fichiers publiés --------------------------------------------------------------------------------------------------

fichiers = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                              reason="site/data/solidarites_departements absent : lancer "
                                     "`python pipeline/solidarites_departements.py produire`")


def charger(rel):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index():
    return charger("solidarites_departements/index.json")


@pytest.fixture(scope="module")
def comptes():
    return charger("solidarites_departements/comptes.json")


@pytest.fixture(scope="module")
def benef():
    return charger("solidarites_departements/beneficiaires.json")


@pytest.fixture(scope="module")
def ecarts():
    return charger("solidarites_departements/ecarts.json")


@fichiers
def test_entetes_et_fichiers(index, comptes, benef, ecarts):
    for d in (index, comptes, benef, ecarts):
        assert d["millesime"] and d["source"] and d["date_sources"]
    for rel in index["fichiers"].values():
        assert (SITE / rel).exists(), rel
    for f in DOSSIER.glob("*.json"):
        assert f.stat().st_size < sd.MAX_OCTETS, f.name


@fichiers
def test_departements_du_site_couverts(index, comptes, benef):
    codes = [d["code"] for d in index["departements"]]
    assert len(codes) == 101 and codes == sorted(codes)
    for d in index["departements"]:
        assert d["comptes"], d["code"]
        assert d["beneficiaires"], d["code"]
        for c in d["comptes"]:
            assert d["code"] in comptes["collectivites"][c]["departements"], (d["code"], c)
        for c in d["beneficiaires"]:
            assert d["code"] in benef["collectivites"][c]["departements"], (d["code"], c)
        for rel in d["liens"].values():
            assert (SITE / rel).exists(), rel


@fichiers
def test_comptes_alignes_et_par_habitant(comptes):
    n = len(comptes["colonnes"])
    for code, c in comptes["collectivites"].items():
        assert set(c["eur"]) == set(c["eur_hab"]) == set(c["reste_a_charge_calcule_eur"]), code
        for a, ligne in c["eur"].items():
            assert len(ligne) == n
            pop = c["population"].get(a)
            for v, h in zip(ligne, c["eur_hab"][a]):
                assert v is None or v >= 0, (code, a)
                if v is None or not pop:
                    assert h is None, (code, a)
                else:
                    assert h == round(v / pop, 2), (code, a)


@fichiers
def test_reste_a_charge_recalculable(comptes):
    cols = comptes["colonnes"]
    i = {k: cols.index(k) for k in cols}
    for code, c in comptes["collectivites"].items():
        for a, (rsa, apa_pch) in c["reste_a_charge_calcule_eur"].items():
            v = c["eur"][a]
            if apa_pch is not None:
                attendu = v[i["allocations_apa"]] + v[i["allocations_pch"]] - v[i["cnsa"]]
                assert abs(apa_pch - attendu) <= 2, (code, a)
            else:
                assert None in (v[i["allocations_apa"]], v[i["allocations_pch"]], v[i["cnsa"]]), (code, a)
            if rsa is not None:
                assert abs(rsa - (v[i["allocations_rsa"]] - v[i["ticpe"]] - v[i["fmdi"]])) <= 2, (code, a)
                assert c.get("financeur_rsa", {}).get(a, "departement") != "etat", (code, a)
            fin = c.get("financeur_rsa", {}).get(a)
            if fin == "etat":
                assert rsa is None, (code, a)
    assert comptes["reste_a_charge"]["statut"] == "calculé" and comptes["reste_a_charge"]["limites"]


@fichiers
def test_alsace_rhone_corse_sans_double_compte(comptes):
    c = comptes["collectivites"]
    assert max(c["67"]["eur"]) <= "2020" and max(c["68"]["eur"]) <= "2020" and min(c["6AE"]["eur"]) >= "2021"
    assert c["67"]["sirens"] == ["226700011"] and c["68"]["sirens"] == ["226800019"]
    assert max(c["69"]["eur"]) <= "2014" and min(c["69D"]["eur"]) >= "2015" and min(c["69M"]["eur"]) >= "2015"
    assert max(c["2A"]["eur"]) <= "2017" and min(c["20R"]["eur"]) >= "2018"
    for code in ("6AE", "20R", "69M", "972", "973"):
        assert c[code]["perimetre"], code


@fichiers
def test_ordres_de_grandeur(index, benef):
    t = index["totaux"]["2024"]["eur"]
    assert 9e9 < t["allocations_rsa"] < 12e9
    assert 6e9 < t["allocations_apa"] < 9e9
    assert 3e9 < t["allocations_pch"] < 5e9
    assert 3e8 < t["fmdi"] < 6e8
    series = {s["id"]: s for s in benef["series"]}
    fr = benef["totaux"]["france"]
    dernier = {sid: fr[sid][series[sid]["annees"].index(2024)] for sid in ("apa", "ase_accueillis", "rsa", "pch")}
    assert 1_200_000 < dernier["apa"] < 1_700_000
    assert 180_000 < dernier["ase_accueillis"] < 300_000
    assert 1_600_000 < dernier["rsa"] < 2_100_000
    assert 300_000 < dernier["pch"] < 600_000


@fichiers
def test_beneficiaires_alignes_et_jamais_negatifs(benef):
    series = {s["id"]: s for s in benef["series"]}
    for code, c in benef["collectivites"].items():
        for sid, v in c["valeurs"].items():
            assert len(v) == len(series[sid]["annees"]), (code, sid)
            assert all(x is None or x >= 0 for x in v), (code, sid)
    for z, t in benef["totaux"].items():
        for sid, v in t.items():
            assert len(v) == len(series[sid]["annees"]), (z, sid)
    assert "6EA" not in benef["collectivites"] and "20" not in benef["collectivites"]
    assert "rupture" in series["rsa"] and benef["collectivites"]["01"].get("rsa_2016_ancien_systeme")


@fichiers
def test_ecarts_recalculables(index, comptes, ecarts):
    cols = ecarts["colonnes"]
    assert ecarts["lignes"] and set(ecarts["grandeurs"]) == set(sd.LECTURES_ECARTS)
    i = comptes["colonnes"]
    for l in ecarts["lignes"]:
        g, code, an, v, autre, e, pct = l
        assert e == v - autre, l
        if autre:
            assert abs(pct - round((v - autre) / autre * 100, 1)) < 0.06, l
        if g.startswith("allocations_"):
            assert comptes["collectivites"][code]["eur"][str(an)][i.index(g)] == v, l
    assert sum(g["lignes"] for g in ecarts["grandeurs"].values()) == len(ecarts["lignes"])
    assert index["ecarts_departements"]["lignes"] == len(ecarts["lignes"])
    assert len(cols) == 7
    for e in index["ecarts"]:
        assert e["ecart"] == e["valeur"] - e["autre_valeur"] and e["lecture_ecart"]
        assert abs(e["ecart_pct"]) < 5, e  # comptes et enquête Aide sociale : même ordre de grandeur national


@fichiers
def test_aucune_copie_des_depenses_drees(comptes, benef):
    """Les dépenses par poste de la DREES restent dans territoires/ : ce module y renvoie sans les recopier."""
    texte = json.dumps(comptes) + json.dumps(benef)
    for cle in ('"postes"', '"rsa_insertion"', '"ase_placements"', '"brute"', '"nette"'):
        assert cle not in texte, cle


@fichiers
def test_sources_et_recherche_publique(index):
    assert index["recherche_publique"]["trouvailles"]
    assert {i["source"] for i in index["sources_inaccessibles"]} >= {i["source"] for i in sd.INACCESSIBLES}
    for k, s in index["sources"].items():
        if s.get("entrepot"):
            assert s["entrepot"].startswith("data/lake/"), k
