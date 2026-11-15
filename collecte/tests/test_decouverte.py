"""Tests hors reseau de la decouverte (parsing des catalogues ODS et data.gouv.fr) et du rapport."""
import decouverte as D
import rapport as R
from conftest import FauxResp, client


def enregistrement_ods(did, titre, champs=(), n=100, desc="", pj=0):
    return {"dataset_id": did, "has_records": n > 0, "attachments": [{}] * pj,
            "fields": [{"name": c, "label": c} for c in champs],
            "metas": {"default": {"title": titre, "description": desc, "keyword": None, "theme": ["BUDGET DE L'ETAT"],
                                  "publisher": "DGFiP", "records_count": n, "modified": "2025-01-01",
                                  "license": "Licence Ouverte v2.0 (Etalab)"}}}


def test_lecture_catalogue_ods_paginee():
    base = "https://ods.test"
    url = f"{base}/api/explore/v2.1/catalog/datasets"

    def route(h, p):
        tous = [enregistrement_ods(f"d{i}", f"Jeu {i}") for i in range(5)]
        return FauxResp(json_data={"total_count": 5, "results": tous[p["offset"]:p["offset"] + p["limit"]]})
    jeux = D.lire_catalogue_ods(client({url: route}), base, par_page=2)
    assert [j["dataset_id"] for j in jeux] == ["d0", "d1", "d2", "d3", "d4"]


def test_jeu_ods_score_et_personnes_physiques():
    r = enregistrement_ods("aides", "Aides de minimis versees aux entreprises", ["nom_beneficiaire", "prenom", "montant", "nom_commune"], n=1000)
    j = D.jeu_ods("economie", "https://data.economie.gouv.fr", r)
    assert j["id"] == "economie__aides" and j["nb_lignes"] == 1000
    assert j["score"] >= 4 and "aide" in j["etiquettes"]
    assert j["personnes_physiques"] is True and "prenom" in j["pp_motif"] and "nom_commune" not in j["pp_motif"]
    assert j["domaine"] == "beneficiaires"


def test_jeu_ods_sans_lien_score_faible():
    r = enregistrement_ods("bornes", "Bornes de recharge electrique", ["nom_station", "puissance"])
    r["metas"]["default"]["theme"] = ["Transport"]
    j = D.jeu_ods("drees", "https://x", r)
    assert j["score"] < 4 and j["personnes_physiques"] is False


def test_champ_personne():
    assert D.champ_personne("prenom")
    assert D.champ_personne("nom")
    assert D.champ_personne("nom_candidat")
    assert not D.champ_personne("nom_commune")
    assert not D.champ_personne("nombre")
    assert not D.champ_personne("libelle_programme")


def test_jeu_datagouv_doublon_et_taille():
    d = {"id": "abc", "slug": "budget-vert", "title": "Budget vert de l'Etat", "description": "", "tags": [],
         "organization": {"id": "534fff8ea3a7292c64a77f02", "name": "MEF"},
         "resources": [{"type": "main", "format": "csv", "filesize": 2_000_000}, {"type": "documentation", "filesize": 9}],
         "harvest": {"domain": "data.economie.gouv.fr", "remote_id": "https://data.economie.gouv.fr/explore/dataset/plf-budget-vert/"},
         "license": "lov2", "last_update": "2025"}
    j = D.jeu_datagouv(d, {"data.economie.gouv.fr": "economie"})
    assert j["doublon_de"] == "economie__plf-budget-vert"
    assert j["taille_estimee_mo"] == 2.0 and j["nb_ressources"] == 1
    assert j["score"] >= 5  # budget dans le titre + bonus producteur
    assert D.jeu_datagouv({**d, "archived": "2020"}, {}) is None


def test_jeu_datagouv_candidats_marque_personnes():
    d = {"id": "x", "title": "Comptes de campagne des candidats aux legislatives", "resources": [], "tags": [],
         "organization": {"id": "534fff63a3a7292c64a77d67"}}
    j = D.jeu_datagouv(d, {})
    assert j["personnes_physiques"] is True and j["domaine"] == "politique"


def test_pages_datagouv_suit_next_page():
    url = f"{D.DATAGOUV_API}/datasets/"

    def route(h, p):
        return FauxResp(json_data={"data": [{"id": f"p{p['page']}"}], "next_page": "n" if p["page"] < 3 else None})
    assert [x["id"] for x in D.pages_datagouv(client({url: route}), {"q": "budget"})] == ["p1", "p2", "p3"]
    assert len(list(D.pages_datagouv(client({url: route}), {"q": "budget"}, max_pages=2))) == 2


def test_rapport_genere_depuis_manifeste():
    m = {"a": {"domaine": "etat", "statut": "ok", "titre": "A", "fichiers": [{"octets": 2_000_000, "lignes": 10}]},
         "b": {"domaine": "politique", "statut": "erreur", "erreur": "HTTP 500", "personnes_physiques": True, "titre": "B",
               "fichiers": []},
         "c": {"domaine": "etat", "statut": "ok", "titre": "C", "fichiers": [{"octets": 1_000_000, "lignes": 5}],
               "ignores": [{"titre": "gros", "octets": 3e8, "motif": "lourd"}]}}
    s = R.synthese(m)
    assert s["total"]["ok"] == 2 and s["total"]["erreurs"] == 1 and s["total"]["lignes"] == 15
    assert s["domaines"]["etat"]["octets"] == 3_000_000
    txt = R.generer(m, {"genere_le": "x", "jeux": [{"id": "a", "portail": "economie", "score": 5}]},
                    {"sources": [], "non_collectables": [{"source": "AFT", "motif": "403"}]})
    assert "`b` [erreur] : HTTP 500" in txt and "gros" in txt and "AFT : 403" in txt
    assert "—" not in txt
