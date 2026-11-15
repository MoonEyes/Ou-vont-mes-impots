"""Tests hors reseau du collecteur : telechargement, reprise, plans de sources, manifeste."""
import hashlib
import json

import pytest

import collecte as C
from conftest import FauxResp, client

ODS = "https://ods.test"


def _parquet_valide() -> bytes:
    import io
    import pyarrow as pa
    import pyarrow.parquet as pq
    b = io.BytesIO()
    pq.write_table(pa.table({"a": [1, 2]}), b)
    return b.getvalue()


PARQUET_OK = _parquet_valide()
PORTAILS = {"t": ODS}
META = {"has_records": True, "metas": {"default": {"modified": "2025-01-01T00:00:00+00:00",
                                                   "data_processed": "x", "metadata_processed": "y"}}}


def test_telecharger_simple_et_sha(lac):
    corps = b"a;b\n1;2\n3;4\n"
    c = client({"u": FauxResp(200, corps, {"ETag": '"e1"', "Last-Modified": "lm"})})
    res = C.telecharger(c, "u", lac / "x.csv")
    assert res["sha256"] == hashlib.sha256(corps).hexdigest()
    assert res["octets"] == len(corps) and res["etag"] == '"e1"'
    assert (lac / "x.csv").read_bytes() == corps
    assert not (lac / "x.csv.part").exists()


def test_telecharger_conditionnel_304(lac):
    (lac).mkdir(parents=True)
    (lac / "x.csv").write_bytes(b"ancien")
    vu = {}

    def route(h, p):
        vu.update(h)
        return FauxResp(304)
    c = client({"u": route})
    res = C.telecharger(c, "u", lac / "x.csv", ancien={"etag": '"e1"', "last_modified": "lm"})
    assert res == {"inchange": True}
    assert vu["If-None-Match"] == '"e1"'
    assert (lac / "x.csv").read_bytes() == b"ancien"


def test_telecharger_reprise_range_apres_coupure(lac):
    corps = b"0123456789abcdefghij"
    appels = []

    def route(h, p):
        appels.append(h)
        if "Range" in h:
            debut = int(h["Range"].split("=")[1].rstrip("-"))
            return FauxResp(206, corps[debut:], {"ETag": '"v"'})
        return FauxResp(200, corps, {"ETag": '"v"'}, coupe_apres=8)
    c = client({"u": route})
    res = C.telecharger(c, "u", lac / "f.bin")
    assert (lac / "f.bin").read_bytes() == corps
    assert res["sha256"] == hashlib.sha256(corps).hexdigest()
    assert appels[1]["Range"] == "bytes=8-" and appels[1]["If-Range"] == '"v"'


def test_refus_acces_non_contourne(lac):
    c = client({"u": FauxResp(403, b"interdit")})
    with pytest.raises(RuntimeError, match="acces refuse"):
        C.telecharger(c, "u", lac / "f.bin")
    assert len(c.s.appels) == 1


def test_delai_depasse(lac):
    c = client({"u": FauxResp(200, b"x" * 100)})
    with pytest.raises(C.DelaiDepasse):
        C.telecharger(c, "u", lac / "f.bin", deadline=0.0001)


def test_plan_pieces_jointes_forme_ods_v21():
    api = f"{ODS}/api/explore/v2.1/catalog/datasets/ds"
    pj = {"links": [], "attachments": [
        {"href": f"{api}/attachments/plr_nomenclature_xls",
         "metas": {"id": "plr_nomenclature_xls", "title": "PLR-Nomenclature.xls", "mimetype": "application/vnd.ms-excel"}}]}
    c = client({api: FauxResp(json_data={**META, "has_records": False}), f"{api}/attachments": FauxResp(json_data=pj)})
    plan = C.plan_source(c, {"id": "s", "type": "ods_pieces_jointes", "portail": "t", "dataset": "ds"}, PORTAILS)
    f = plan["fichiers"][0]
    assert f["url"] == f"{api}/attachments/plr_nomenclature_xls"
    assert f["nom"] == "s/PLR-Nomenclature.xls"
    assert f["signature"].startswith("2025-01-01")


def test_plan_ods_export_refuse_jeu_sans_enregistrements():
    api = f"{ODS}/api/explore/v2.1/catalog/datasets/ds"
    c = client({api: FauxResp(json_data={**META, "has_records": False})})
    with pytest.raises(RuntimeError, match="sans enregistrements"):
        C.plan_source(c, {"id": "s", "type": "ods_export", "portail": "t", "dataset": "ds"}, PORTAILS)


def test_plan_datagouv_ignore_lourd_et_html():
    ds = {"last_update": "d", "resources": [
        {"id": "aaaaaaaa1", "title": "gros.csv", "format": "csv", "url": "https://x/gros.csv", "filesize": 5 * 10**8, "type": "main"},
        {"id": "bbbbbbbb2", "title": "petit.csv", "format": "csv", "url": "https://x/petit.csv", "filesize": 10, "type": "main"},
        {"id": "cccccccc3", "title": "page", "format": "html", "url": "https://x/page", "type": "main"}]}
    c = client({f"{C.DATAGOUV_API}/datasets/abc/": FauxResp(json_data=ds)})
    plan = C.plan_source(c, {"id": "s", "type": "datagouv", "dataset": "abc", "toutes": True}, {}, max_octets=10**8)
    assert [f["url"] for f in plan["fichiers"]] == ["https://x/petit.csv"]
    assert plan["ignores"][0]["motif"] == "lourd"


def test_collecter_puis_reprise_sans_retelechargement(lac):
    api = f"{ODS}/api/explore/v2.1/catalog/datasets/ds"
    routes = {api: FauxResp(json_data=META), f"{api}/exports/parquet": FauxResp(200, PARQUET_OK)}
    src = {"id": "s", "type": "ods_export", "portail": "t", "dataset": "ds", "domaine": "etat", "titre": "T"}
    c = client(routes)
    e1 = C.collecter(c, src, {}, PORTAILS, timeout_s=60)
    assert e1["statut"] == "ok" and e1["fichiers"][0]["change"] is True
    assert e1["zone"] == "publique" and (lac / "etat" / "s.parquet").exists()
    C.maj_manifeste("s", e1)
    c2 = client(routes)
    e2 = C.collecter(c2, src, C.lire_manifeste()["s"], PORTAILS, timeout_s=60)
    assert e2["statut"] == "ok" and e2["inchange"] is True
    assert [u for u, _, _ in c2.s.appels] == [api]  # seulement la metadonnee, pas l'export
    # changement amont : nouvelle signature -> retelechargement
    routes[api] = FauxResp(json_data={**META, "metas": {"default": {"modified": "2026"}}})
    c3 = client(routes)
    e3 = C.collecter(c3, src, e2, PORTAILS, timeout_s=60)
    assert f"{api}/exports/parquet" in [u for u, _, _ in c3.s.appels]
    assert e3["fichiers"][0]["change"] is False  # meme contenu


def test_collecter_personnes_physiques_zone_restreinte(lac):
    src = {"id": "p", "type": "url", "url": "https://x/p.csv", "format": "csv", "domaine": "politique",
           "titre": "T", "personnes_physiques": True}
    e = C.collecter(client({"https://x/p.csv": FauxResp(200, b"nom;prenom\na;b\n")}), src, {}, {}, timeout_s=60)
    assert e["zone"] == "restreinte" and e["personnes_physiques"] is True
    assert e["fichiers"][0]["chemin"] == "data/lake/_restreint/politique/p.csv"
    assert e["fichiers"][0]["lignes"] == 1 and e["fichiers"][0]["colonnes"] == ["nom", "prenom"]


def test_erreur_conserve_trace_des_fichiers_anterieurs(lac):
    ancien = {"statut": "ok", "fichiers": [{"chemin": "data/lake/etat/s.csv", "octets": 3, "sha256": "h"}]}
    src = {"id": "s", "type": "url", "url": "https://x/s.csv", "format": "csv", "domaine": "etat", "titre": "T"}
    e = C.collecter(client({"https://x/s.csv": FauxResp(404, b"absent")}), src, ancien, {}, timeout_s=60)
    assert e["statut"] == "erreur" and e["fichiers"][0]["donnees_anterieures"] is True


def test_manifeste_maj_conserve_les_autres_entrees(lac):
    C.maj_manifeste("a", {"statut": "ok"})
    C.maj_manifeste("b", {"statut": "erreur"})
    m = json.loads((lac / "manifest.json").read_text())
    assert set(m) == {"a", "b"}
    assert not (lac / "manifest.json.tmp").exists()


def test_sources_depuis_decouvertes_filtre_et_types():
    dec = [
        {"id": "economie__a", "portail": "economie", "dataset": "a", "score": 6, "nb_lignes": 10},
        {"id": "economie__b", "portail": "economie", "dataset": "b", "score": 6, "nb_lignes": 0, "nb_pieces_jointes": 2},
        {"id": "economie__c", "portail": "economie", "dataset": "c", "score": 1, "nb_lignes": 10},
        {"id": "economie__deja", "portail": "economie", "dataset": "deja", "score": 9, "nb_lignes": 10},
        {"id": "datagouv__d", "portail": "datagouv", "dataset": "d", "score": 7, "personnes_physiques": True},
        {"id": "datagouv__e", "portail": "datagouv", "dataset": "e", "score": 7, "doublon_de": "economie__a"},
    ]
    cat = [{"id": "x", "type": "ods_export", "portail": "economie", "dataset": "deja"}]
    s = {x["id"]: x for x in C.sources_depuis_decouvertes(dec, cat, 4)}
    assert set(s) == {"economie__a", "economie__b", "datagouv__d"}
    assert s["economie__a"]["type"] == "ods_export"
    assert s["economie__b"]["type"] == "ods_pieces_jointes"
    assert s["datagouv__d"]["type"] == "datagouv" and s["datagouv__d"]["personnes_physiques"] is True


def test_catalogue_reel_coherent():
    cat = C.charger_catalogue()
    ids = [s["id"] for s in cat["sources"]]
    assert len(ids) == len(set(ids))
    for s in cat["sources"]:
        assert s["type"] in {"ods_export", "ods_pieces_jointes", "datagouv", "datagouv_ressources", "eurostat", "url", "urls"}
        if s["type"].startswith("ods"):
            assert s["portail"] in cat["portails"]
        assert "—" not in json.dumps(s, ensure_ascii=False)


def test_ressource_en_echec_donne_statut_partiel(lac):
    src = {"id": "m", "type": "urls", "domaine": "etat", "titre": "T",
           "urls": [{"url": "https://x/a.csv", "nom": "a.csv"}, {"url": "https://x/b.pdf", "nom": "b.pdf"}]}
    e = C.collecter(client({"https://x/a.csv": FauxResp(200, b"a\n1\n"), "https://x/b.pdf": FauxResp(403, b"non")}),
                    src, {}, {}, timeout_s=60)
    assert e["statut"] == "partiel" and len(e["fichiers"]) == 1
    assert "acces refuse" in e["erreurs_fichiers"][0]["erreur"]


def test_jeu_sans_ressource_neutre_et_lourd_differe(lac):
    url = f"{C.DATAGOUV_API}/datasets/v/"
    src = {"id": "v", "type": "datagouv", "dataset": "v", "domaine": "etat", "titre": "T", "toutes": True}
    e = C.collecter(client({url: FauxResp(json_data={"resources": []})}), src, {}, {}, timeout_s=60)
    assert e["statut"] == "sans_ressource"
    gros = {"resources": [{"id": "r1234567", "title": "g", "format": "csv", "url": "https://x/g", "filesize": 10**9}]}
    e = C.collecter(client({url: FauxResp(json_data=gros)}), src, {}, {}, timeout_s=60, max_octets=10**8)
    assert e["statut"] == "lourd_ignore" and e["ignores"][0]["octets"] == 10**9


def test_tests_ne_touchent_pas_le_vrai_manifeste(lac):
    assert C.MANIFEST == lac / "manifest.json"
    C.maj_manifeste("z", {"statut": "ok", "domaine": "etat"})
    assert (lac / "manifest.json").exists()


def test_fichier_trop_lourd_interrompu_et_differe(lac):
    src = {"id": "g", "type": "url", "url": "https://x/g.bin", "domaine": "etat", "titre": "T"}
    e = C.collecter(client({"https://x/g.bin": FauxResp(200, b"x" * 40)}), src, {}, {}, timeout_s=60, max_octets=10)
    assert e["statut"] == "lourd_ignore"
    assert not list(lac.rglob("*.part"))


def test_reclasser_deplace_les_fichiers(lac):
    (lac / "politique").mkdir(parents=True)
    (lac / "politique" / "economie__x.parquet").write_bytes(b"abc")
    C.maj_manifeste("economie__x", {"statut": "ok", "domaine": "politique", "origine": "decouverte",
                                    "fichiers": [{"chemin": "data/lake/politique/economie__x.parquet", "octets": 3}]})
    assert C.reclasser([{"id": "economie__x", "domaine": "fiscalite"}]) == 1
    e = C.lire_manifeste()["economie__x"]
    assert e["domaine"] == "fiscalite" and e["fichiers"][0]["chemin"] == "data/lake/fiscalite/economie__x.parquet"
    assert (lac / "fiscalite" / "economie__x.parquet").read_bytes() == b"abc"


def test_parquet_tronque_refuse(lac):
    api = f"{ODS}/api/explore/v2.1/catalog/datasets/ds"
    src = {"id": "s", "type": "ods_export", "portail": "t", "dataset": "ds", "domaine": "etat", "titre": "T"}
    e = C.collecter(client({api: FauxResp(json_data=META), f"{api}/exports/parquet": FauxResp(200, b"PAR1-coupe")}),
                    src, {}, PORTAILS, timeout_s=60)
    assert e["statut"] == "erreur" and "incomplet" in e["erreur"]
    assert not (lac / "etat" / "s.parquet").exists()
