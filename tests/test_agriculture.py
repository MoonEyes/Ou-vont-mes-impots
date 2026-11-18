"""Agriculture (pipeline/agriculture.py) : règles du module et cohérence des fichiers publiés, sans réseau."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "agriculture"
sys.path.insert(0, str(ROOT / "pipeline"))
import agriculture  # noqa: E402


# --- fonctions pures (toujours testées) ------------------------------------------------------------------------------

def test_secret_et_vide_jamais_zero():
    assert agriculture.valeur("S") == (None, True)
    assert agriculture.valeur("") == (None, False)
    assert agriculture.valeur(" ") == (None, False)
    assert agriculture.valeur("nc") == (None, False)
    assert agriculture.valeur("1 234") == (1234, False)
    assert agriculture.valeur("0") == (0, False)


def test_territoires_de_la_source():
    assert agriculture.territoire("FR - France hors TOM") == ("france", "FR", "France hors TOM")
    assert agriculture.territoire("FR métro - France métropolitaine")[0:2] == ("ensemble", "FR_METRO")
    assert agriculture.territoire("94 - Région Corse") == ("region", "94", "Région Corse")
    assert agriculture.territoire("2A - Corse-du-Sud") == ("departement", "2A", "Corse-du-Sud")
    assert agriculture.territoire("971 - Guadeloupe") == ("departement", "971", "Guadeloupe")


def test_indicateurs_connus_et_inconnus_refuses():
    assert agriculture.indicateur("nombre de bénéficiaires") == ("beneficiaires", "exploitations")
    assert agriculture.indicateur("montant total (1000 euros)") == ("montant_total_eur", "euros")
    assert agriculture.indicateur("montant des DPU (1000 euros)") == ("montant_eur", "euros")
    with pytest.raises(SystemExit):
        agriculture.indicateur("montant mystère (1000 euros)")
    with pytest.raises(SystemExit):
        agriculture.indicateur("surface primée")


def test_montant_retenu_jamais_une_somme_de_composantes():
    assert agriculture.montant_retenu({"montant_total_eur", "montant_prime_de_base_eur"}) == "montant_total_eur"
    assert agriculture.montant_retenu({"montant_eur", "complement_extensification_eur"}) == "montant_eur"
    assert agriculture.montant_retenu({"montant_prime_de_base_eur", "complement_extensification_eur"}) is None


def test_programmes_feader():
    assert agriculture.type_programme("2014FR06RDNP001") == "national"
    assert agriculture.type_programme("2014FR06RDRN001") == "reseau_rural"
    assert agriculture.type_programme("2014FR06RDRP041") == "regional"


def test_sources_documentees_et_aucune_source_nominative():
    for cle, s in agriculture.SOURCES.items():
        assert s["url"].startswith("https://") and s["page"].startswith("https://"), cle
        assert s["licence"] and s["producteur"] and s["millesime"] and s["verdict"], cle
    assert any("Telepac" in i["source"] for i in agriculture.INACCESSIBLES)
    ecartes = [t for t in agriculture.RECHERCHE_PUBLIQUE["trouvailles"] if t["classement"] == "écarté"]
    assert any("personnes morales" in t["nom"] for t in ecartes)


def test_catalogue_declare_les_sources_du_module():
    cat = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    ids = {s["id"]: s for s in cat["sources"]}
    for s in agriculture.SOURCES.values():
        assert s["id_catalogue"] in ids
        assert ids[s["id_catalogue"]]["domaine"] == "agriculture"
        assert not ids[s["id_catalogue"]].get("personnes_physiques")


def test_lecture_d_un_tableau_agreste_minimal(tmp_path):
    csv = ("Titre;;;;\n;Période;;;\n;2009;;;\n;Indicateurs;;;\n"
           "Géographie;Droits à paiement unique DPU : nombre de bénéficiaires;"
           "Droits à paiement unique DPU : montant des DPU (1000 euros);"
           "Indemnité compensatoire de handicaps naturels (ICHN) : montant (1000 euros)\n"
           "94 - Région Corse;10;30;5\n2A - Corse-du-Sud;4;S;2\n2B - Haute-Corse;6;20;3\n;\nSource : Agreste;;;\n")
    f = tmp_path / "pac.csv"
    f.write_bytes(csv.encode("latin-1"))
    pac = agriculture.lire_pac(f)
    assert [c["indicateur"] for c in pac["colonnes"]] == ["beneficiaires", "montant_eur", "montant_eur"]
    assert [t["code"] for t in pac["territoires"]] == ["94", "2A", "2B"]
    corse_sud = pac["territoires"][1]
    assert corse_sud["region"] == "94" and corse_sud["valeurs"] == [4, None, 2000]
    ctrl = agriculture.controles_pac(pac)
    assert ctrl["ecarts"] == [] and ctrl["comparaisons_avec_cellule_secrete"] == 1
    doc = agriculture.doc_pac(pac, "2026-11-18")
    p = doc["territoires"][1]["par_annee"]["2009"]
    assert p["aides_sans_montant"] == ["dpu"] and p["somme_montants_retenus_eur"] == 2000
    assert doc["cellules_secretes"] == [{"niveau": "departement", "territoire": "2A", "annee": 2009, "aide": "dpu", "indicateur": "montant_eur"}]


def test_ecart_publie_quand_le_total_ne_retombe_pas(tmp_path):
    csv = ("Géographie;Prime herbagère agroenvironnementale (PHAE) : montant (1000 euros)\n"
           "94 - Région Corse;10\n2A - Corse-du-Sud;4\n2B - Haute-Corse;4\n")
    lignes = ";2009\n" + csv
    f = tmp_path / "pac.csv"
    f.write_bytes(lignes.encode("latin-1"))
    ctrl = agriculture.controles_pac(agriculture.lire_pac(f))
    assert ctrl["ecarts"] == [{"objet": "region_contre_departements", "niveau": "region", "territoire": "94", "annee": 2009,
                               "aide": "phae", "indicateur": "montant_eur", "valeur_publiee": 10000,
                               "somme_des_lignes": 8000, "ecart": -2000}]


# --- fichiers publiés --------------------------------------------------------------------------------------------------

fichiers = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                              reason="site/data/agriculture absent : lancer `python pipeline/agriculture.py produire`")


def charger(rel):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


@fichiers
def test_entete_et_taille():
    for f in sorted(DOSSIER.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and re.search(r"https://", d["source"]), f.name
        assert f.stat().st_size < 1_000_000, f.name


@fichiers
def test_aucun_beneficiaire_individuel():
    interdits = {"beneficiaire", "nom_beneficiaire", "raison_sociale", "siren", "siret", "commune", "code_postal"}
    for f in sorted(DOSSIER.glob("*.json")):
        def parcourir(x):
            if isinstance(x, dict):
                assert not (set(x) & interdits), f"{f.name} : {set(x) & interdits}"
                for v in x.values():
                    parcourir(v)
            elif isinstance(x, list):
                for v in x:
                    parcourir(v)
        parcourir(json.loads(f.read_text(encoding="utf-8")))
    pac = charger("agriculture/pac_departements.json")
    assert {t["niveau"] for t in pac["territoires"]} == {"france", "ensemble", "region", "departement"}


@fichiers
def test_pac_departements_coherente():
    pac = charger("agriculture/pac_departements.json")
    n = len(pac["colonnes"])
    deps = [t for t in pac["territoires"] if t["niveau"] == "departement"]
    assert len(deps) >= 96 and len({t["code"] for t in deps}) == len(deps)
    assert len({(t["niveau"], t["code"]) for t in pac["territoires"]}) == len(pac["territoires"])
    for t in pac["territoires"]:
        assert len(t["valeurs"]) == n, t["code"]
        for an, p in t["par_annee"].items():
            vals = list(p["montants_retenus_eur"].values())
            assert p["somme_montants_retenus_eur"] == (sum(vals) if vals else None)
            assert not set(p["montants_retenus_eur"]) & set(p["aides_sans_montant"])
    cles = {(c["annee"], c["aide"], c["indicateur"]) for c in pac["colonnes"]}
    assert len(cles) == n
    par_code = {(t["niveau"], t["code"]): t for t in pac["territoires"]}
    for s in pac["cellules_secretes"]:
        k = next(i for i, c in enumerate(pac["colonnes"]) if (c["annee"], c["aide"], c["indicateur"]) ==
                 (s["annee"], s["aide"], s["indicateur"]))
        assert par_code[(s["niveau"], s["territoire"])]["valeurs"][k] is None


@fichiers
def test_developpement_rural_coherent():
    d = charger("agriculture/developpement_rural.json")["feader_2014_2022"]
    for p in d["programmes"]:
        # total publié par la source : un écart de plus de 1 000 euros avec la somme de ses deux parts est listé
        if abs(p["total_eur"] - (p["ue_eur"] + p["contrepartie_nationale_eur"])) > 1000:
            assert p["cci"] in {e["cci"] for e in d["ecarts_total_source"]["programmes"]}
        if p["type"] == "regional":
            assert p["region"]["departements"], p["cci"]
        else:
            assert p["region"] is None
    assert d["serie"][-1]["annee"] == d["annee_situation"]
    assert d["serie"][-1]["ue_eur"] == d["national"]["ue_eur"]


@fichiers
def test_etat_renvoie_sans_recopier_les_depenses_fiscales():
    e = charger("agriculture/etat.json")
    assert [p["programme"] for p in e["programmes"]] == agriculture.PROGRAMMES_ETAT
    df = e["depenses_fiscales"]
    if df:
        assert set(df) == {"fichier", "programme", "noeud", "mesures", "fichier_mesures", "lecture"}
        assert all(re.fullmatch(r"\d+", m) for m in df["mesures"])
    for p in e["programmes"]:
        r = charger(p["fichier_realisations"])
        publiees = {a["annee"]: a["depense_constatee_eur"] for a in r["prevu_depense"]["annees"]}
        for a in p["annees"]:
            v = publiees[a["annee"]]
            assert a["depense_constatee_eur"] == (None if v is None else int(round(v)))


@fichiers
def test_liens_vers_des_fichiers_presents():
    def liens(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k.startswith("fichier") and isinstance(v, str) and v.endswith(".json"):
                    yield v
                yield from liens(v)
        elif isinstance(x, list):
            for v in x:
                yield from liens(v)
    for f in sorted(DOSSIER.glob("*.json")):
        for rel in liens(json.loads(f.read_text(encoding="utf-8"))):
            assert (SITE / rel).exists(), f"{f.name} -> {rel}"
