"""Performance (pipeline/performance.py) : fonctions pures et cohérence des fichiers publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "performance"
REAL = ROOT / "site" / "data" / "realisations"
sys.path.insert(0, str(ROOT / "pipeline"))
import performance as pf  # noqa: E402

INTERDITS = {"cout_par_resultat", "montant_par_resultat", "note_efficacite", "efficacite", "ecart_a_la_cible",
             "ecarts_a_la_cible", "taux_avancement", "indic_ta", "classement", "rang", "score"}


# --- fonctions pures ------------------------------------------------------------------------------------------------

def test_url_source_vers_le_jeu():
    assert pf.url_source("data.economie.gouv.fr/plf-2025-performance") == \
        "https://data.economie.gouv.fr/explore/dataset/plf-2025-performance/"
    assert pf.url_source("data.economie.gouv.fr/performance-de-la-depense (RAP 2024)").startswith(
        "https://data.economie.gouv.fr/explore/dataset/performance-de-la-depense/")
    assert pf.url_source("autre texte") == "autre texte"


def test_valeurs_absentes_jamais_zero():
    assert pf.nombre_ditp("") is None and pf.nombre_ditp(None) is None and pf.nombre_ditp("nd") is None
    assert pf.nombre_ditp("0") == 0.0 and pf.nombre_ditp("55.6") == 55.6


def test_codes_departement():
    assert pf.code_departement("D01") == "01"
    assert pf.code_departement("D2A") == "2A"
    assert pf.code_departement("D976") == "976"
    with pytest.raises(ValueError):
        pf.code_departement("R52")


def _serie(**kw):
    base = {"id": "999-1", "code_indicateur": "P999-1-1", "objectif": "o", "indicateur": "i", "sous_indicateur": None,
            "unite": "%", "indicateur_de_contexte": None, "libelles_anterieurs": None, "rapprochement": {"code": 2},
            "valeurs": [{"annee": 2024, "valeur": 12.0, "brut": "12", "source": "RAP 2025"},
                        {"annee": 2023, "valeur": None, "brut": "Non déterminé", "source": "RAP 2025"}],
            "cibles": [{"annee": 2024, "valeur": 15.0, "brut": "15", "source": "PAP 2025"},
                       {"annee": 2027, "valeur": 20.0, "brut": "20", "source": "PAP 2025", "note": "cible de moyen terme"}]}
    base.update(kw)
    return base


def test_lignes_cible_et_realise_cote_a_cote_sans_ecart():
    lignes = {l["annee"]: l for l in pf.lignes_indicateur(_serie())}
    assert sorted(lignes) == [2023, 2024, 2027]
    assert lignes[2024] == {"annee": 2024, "cible": 15.0, "cible_publiee": "15", "source_cible": "PAP 2025",
                            "realise": 12.0, "realise_publie": "12", "source_realise": "RAP 2025"}
    assert lignes[2023]["realise"] is None and lignes[2023]["realise_publie"] == "Non déterminé"
    assert "cible" not in lignes[2023]
    assert lignes[2027]["cible_note"] == "cible de moyen terme" and "realise" not in lignes[2027]
    assert not any(k in INTERDITS for l in lignes.values() for k in l)


def test_correspondance_statuts():
    ordre = ["RAP 2025", "RAP 2024", "PAP 2025", "RAP 2019"]
    assert pf.correspondance_serie(_serie(), "999", ordre, {}) is None   # publiée en 2025, libellé inchangé
    c = pf.correspondance_serie(_serie(libelles_anterieurs=["ancien"]), "999", ordre, {})
    assert c["statuts"] == ["libellé modifié"] and c["meme_code_au_rap_2025"] is None
    vieux = _serie(valeurs=[{"annee": 2018, "valeur": 1.0, "brut": "1", "source": "RAP 2019"}], cibles=[])
    c = pf.correspondance_serie(vieux, "999", ordre, {("999", "P999-1-1"): ["autre intitulé"]})
    assert c["statuts"] == ["absent des documents 2025"] and c["derniere_source"] == "RAP 2019"
    assert c["meme_code_au_rap_2025"] == ["autre intitulé"]
    assert pf.correspondance_serie(vieux, "999", ordre, {})["meme_code_au_rap_2025"] == []


def test_credits_autres_montants_listes_jamais_additionnes():
    r = {"programme": "999", "prevu_depense": {"annees": [
        {"annee": 2024, "vote_lfi_eur": 10.0, "depense_constatee_eur": 5_000_000_000.0, "source": "s"},
        {"annee": 2021, "vote_lfi_eur": None, "depense_constatee_eur": None, "source": None, "trou": "Trou 2021"}]}}
    autres = {("999", 2024): [{"montant_eur": 5_100_000_000, "fichier": "arbre/racine.json", "source": "a",
                               "millesime": "m", "perimetre": "p", "precision": "x"}]}
    c = {x["annee"]: x for x in pf.credits_programme(r, autres)}
    assert c[2024]["depense_constatee_eur"] == 5_000_000_000.0
    assert c[2024]["autres_montants_publies"][0]["montant_eur"] == 5_100_000_000
    assert c[2024]["autres_montants_publies"][0]["egal_a_la_depense_constatee"] is False
    assert c[2021]["depense_constatee_eur"] is None and c[2021]["trou"] == "Trou 2021"


# --- fichiers publiés -----------------------------------------------------------------------------------------------

def _charger(rel):
    p = DOSSIER / rel
    if not p.exists():
        pytest.skip(f"{p} absent (lancer python pipeline/performance.py produire)")
    return json.loads(p.read_text(encoding="utf-8"))


def _cles(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _cles(v)
    elif isinstance(x, list):
        for v in x:
            yield from _cles(v)


def test_entetes_tailles_et_aucun_ratio():
    fichiers = sorted(DOSSIER.rglob("*.json"))
    if not fichiers:
        pytest.skip("site/data/performance absent")
    for p in fichiers:
        assert p.stat().st_size < 1_000_000, p
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"] and d["collecte_le"], p
        assert not INTERDITS & set(_cles(d)), p


def test_avertissements_de_la_page():
    idx = _charger("index.json")
    texte = " ".join(idx["avertissements"])
    assert "choisis par les ministères eux-mêmes" in texte
    assert "ni un succès ni un échec en soi" in texte
    assert any("REPSS" in n["source"] or "sécurité sociale" in n["source"] for n in idx["non_exploites"])
    assert idx["miroirs_data_gouv"]["RAP 2025"].startswith("https://www.data.gouv.fr/")


def test_table_reliee_aux_credits_publies_par_programme_et_annee():
    idx = _charger("index.json")
    progs = [p for m in idx["missions"] for p in m["programmes"]]
    assert len(progs) == idx["comptes"]["programmes"] > 100
    for p in progs[:: max(1, len(progs) // 25)]:
        d = _charger(f"programmes/{p['programme']}.json")
        r = json.loads((REAL / f"{p['programme']}.json").read_text(encoding="utf-8"))
        assert d["mission"] == r["mission"] == p["mission"]
        attendu = {a["annee"]: (a.get("vote_lfi_eur"), a.get("depense_constatee_eur"))
                   for a in r["prevu_depense"]["annees"]}
        assert {c["annee"]: (c["vote_lfi_eur"], c["depense_constatee_eur"]) for c in d["credits"]} == attendu
        for s in d["series"]:
            assert s["lignes"]
            for l in s["lignes"]:
                if "cible_publiee" in l:
                    assert l["source_cible"] in d["sources"]
                if "realise_publie" in l:
                    assert l["source_realise"] in d["sources"]
        assert sum(len(s["lignes"]) for s in d["series"]) == d["nombre_lignes"]


def test_table_reprend_les_series_sans_les_modifier():
    d = _charger("programmes/102.json")
    r = json.loads((REAL / "102.json").read_text(encoding="utf-8"))
    serie = {i["id"]: i for i in r["resultats_mesures"]["indicateurs"]}
    for s in d["series"]:
        i = serie[s["serie"]]
        for l in s["lignes"]:
            v = next((x for x in i["valeurs"] if x["annee"] == l["annee"]), None)
            assert (v is None) == ("realise_publie" not in l)
            if v:
                assert (l["realise"], l["realise_publie"]) == (v["valeur"], v["brut"])


def test_correspondance_comptes_coherents():
    c = _charger("correspondance.json")
    n_lib = n_abs = 0
    for p in c["programmes"]:
        d = _charger(f"programmes/{p['programme']}.json")
        n_lib += sum("libellé modifié" in x["statuts"] for x in d["correspondance"])
        n_abs += sum("absent des documents 2025" in x["statuts"] for x in d["correspondance"])
    assert (n_lib, n_abs) == (c["comptes"]["libelle_modifie"], c["comptes"]["absent_des_documents_2025"])


def test_barometre_departements_et_france():
    b = _charger("barometre/index.json")
    assert len(b["departements"]) == 101 and len(b["indicateurs"]) >= 100
    assert {d["code"] for d in b["departements"]} >= {"01", "2A", "2B", "44", "976"}
    fr = _charger("barometre/FR.json")
    assert fr["nom"] == "France" and fr["indicateurs"]
    d = _charger("barometre/44.json")
    for i in d["indicateurs"]:
        for cle in ("initiale", "valeurs", "cibles"):
            dates = [x[0] for x in i[cle]]
            assert dates == sorted(dates)
            assert all(isinstance(x[1], (int, float)) for x in i[cle])


def test_grands_projets_numeriques_relies_sans_total_ni_ratio():
    import re
    d = DOSSIER
    if not (d / "index.json").exists():
        pytest.skip("site/data/performance absent")
    idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
    liens = idx["liens_par_programme"]
    assert liens["application_des_lois_de_finances"]["relie"] is False   # publié par loi, jamais par programme
    n = 0
    for f in sorted((d / "programmes").glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8")).get("grands_projets_numeriques")
        if not g:
            continue
        n += 1
        assert not {k for k in g if re.search(r"total|ratio|somme|par_euro", k)}
        for pr in g["projets"]:
            assert pr["editions"] == sorted(pr["editions"], key=lambda e: e["annee"])
            for e in pr["editions"]:
                assert e["edition"].startswith(str(e["annee"]))
    assert n == liens["grands_projets_numeriques"]["programmes"]
