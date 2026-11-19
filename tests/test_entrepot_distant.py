"""Entrepôt distant (pipeline/entrepot_distant.py), garde-fou de lignes (pipeline/garde_lignes.py) et branchement dans
.github/workflows/data.yml. Sans réseau : le bucket est simulé par un serveur HTTP local."""
from __future__ import annotations

import datetime as dt
import hashlib
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import entrepot_distant as ed  # noqa: E402
import garde_lignes as gl  # noqa: E402


# --- Lecture distante --------------------------------------------------------------------------------------------

def test_config_non_configuree_ne_fait_rien(capsys, monkeypatch):
    for k in ("OVMI_LAC_URL", "OVMI_LAC_ENDPOINT", "OVMI_LAC_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    assert ed.main(["restaurer"]) == 0
    assert "non configuré" in capsys.readouterr().out


def test_config_anonyme_ou_signee():
    c = ed.ConfigLecture({"OVMI_LAC_ENDPOINT": "s3.gra.io.cloud.ovh.net", "OVMI_LAC_BUCKET": "lac-public"})
    assert c.configuree and c.mode.startswith("anonyme")
    assert c.url("_entrees/index.json") == "https://s3.gra.io.cloud.ovh.net/lac-public/_entrees/index.json"
    assert c.entetes(c.url("x")) == {}
    s = ed.ConfigLecture({"OVMI_LAC_URL": "https://b.s3.gra.io.cloud.ovh.net", "OVMI_S3_LECTURE_ID": "ID",
                          "OVMI_S3_LECTURE_SECRET": "SECRET"})
    assert s.mode.startswith("signé")
    assert s.entetes(s.url("_entrees/index.json"))["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=ID/")


def test_config_refuse_le_bucket_prive_et_le_http():
    with pytest.raises(SystemExit):
        ed.ConfigLecture({"OVMI_LAC_ENDPOINT": "e", "OVMI_LAC_BUCKET": "prive", "OVMI_BUCKET_PRIVE": "prive"})
    with pytest.raises(SystemExit):
        ed.ConfigLecture({"OVMI_LAC_ENDPOINT": "e", "OVMI_LAC_BUCKET": "prive/sous", "OVMI_BUCKET_PRIVE": "prive"})
    with pytest.raises(SystemExit):
        ed.ConfigLecture({"OVMI_LAC_URL": "http://exemple"})


def test_signature_v4_deterministe():
    t = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc)
    url = "https://s3.gra.io.cloud.ovh.net/lac/_entrees/index.json"
    a = ed.signer_get(url, "ID", "SECRET", "gra", t)
    assert a == ed.signer_get(url, "ID", "SECRET", "gra", t)
    assert a != ed.signer_get(url, "ID", "AUTRE", "gra", t)
    assert a["x-amz-date"] == "20261119T120000Z"
    assert "Credential=ID/20261119/gra/s3/aws4_request" in a["Authorization"]
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in a["Authorization"]
    assert "SECRET" not in json.dumps(a)


def test_chemins_et_objets():
    assert ed.chemin_sur("data/lake/etat/x.csv")
    for mauvais in ("data/lake/../../etc/passwd", "/data/lake/x", "site/data/x.json", "data/lake/a\\b"):
        assert not ed.chemin_sur(mauvais)
    assert ed.est_restreint("data/lake/_restreint/beneficiaires/x.parquet")
    assert not ed.est_restreint("data/lake/_restreintX/x")
    with pytest.raises(ValueError):
        ed.objet("../index.json")


@pytest.fixture
def bac(tmp_path, monkeypatch):
    """Dépôt simulé (data/lake) et bucket simulé (serveur HTTP local servant un dossier)."""
    racine, bucket = tmp_path / "depot", tmp_path / "bucket"
    (racine / "data" / "lake").mkdir(parents=True)
    bucket.mkdir()
    monkeypatch.setattr(ed, "ROOT", racine)
    monkeypatch.setattr(ed, "LAKE", racine / "data" / "lake")
    monkeypatch.setattr(ed, "MANIFESTE", racine / "data" / "lake" / "manifest.json")
    monkeypatch.setattr(ed, "LIGNEE", racine / "pipeline" / "lignee.json")

    class Gestion(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(bucket), **k)

        def log_message(self, *a):
            pass

    serveur = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    cfg = ed.ConfigLecture({})
    cfg.base = f"http://127.0.0.1:{serveur.server_address[1]}"   # https exigé hors test
    yield racine, bucket, cfg
    serveur.shutdown()


def _deposer(bucket: Path, contenu: bytes) -> str:
    sha = hashlib.sha256(contenu).hexdigest()
    p = bucket / ed.objet(sha)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu)
    return sha


def test_restaurer_verifie_refuse_et_date(bac):
    racine, bucket, cfg = bac
    bon = b"annee;montant\n2024;1\n"
    sha = _deposer(bucket, bon)
    sha_restreint = _deposer(bucket, b"personne")
    index = {"fichiers": {
        "data/lake/etat/plrg/a.csv": {"sha256": sha, "octets": len(bon), "source": "etat_plrg_2024",
                                      "domaine": "etat", "collecte_le": "2026-11-17T18:38:26+00:00"},
        "data/lake/_restreint/benef/x.parquet": {"sha256": sha_restreint, "octets": 8, "source": "s"},
        "data/lake/../../evasion.txt": {"sha256": sha, "octets": len(bon), "source": None},
        "data/lake/etat/corrompu.csv": {"sha256": "0" * 64, "octets": 3, "source": None},
    }}
    (bucket / "_entrees").mkdir(exist_ok=True)
    (bucket / "_entrees" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    b = ed.restaurer(cfg, None)
    assert b["restaures"] == 1 and len(b["refuses"]) == 2 and len(b["absents_distants"]) == 1
    assert (racine / "data/lake/etat/plrg/a.csv").read_bytes() == bon
    assert not (racine / "data/lake/_restreint").exists()
    assert not (racine.parent / "evasion.txt").exists()
    man = json.loads((racine / "data/lake/manifest.json").read_text(encoding="utf-8"))
    assert man["etat_plrg_2024"]["collecte_le"] == "2026-11-17T18:38:26+00:00"   # date de la version, pas du jour
    assert ed.restaurer(cfg, None)["deja_presents"] == 1                      # rien n'est retéléchargé


def test_restaurer_rejette_un_objet_altere(bac):
    racine, bucket, cfg = bac
    sha = hashlib.sha256(b"vrai").hexdigest()
    p = bucket / ed.objet(sha)
    p.parent.mkdir(parents=True)
    p.write_bytes(b"faux")
    (bucket / "_entrees" / "index.json").write_text(json.dumps(
        {"fichiers": {"data/lake/etat/v.csv": {"sha256": sha, "octets": 4, "source": None}}}), encoding="utf-8")
    b = ed.restaurer(cfg, None)
    assert b["restaures"] == 0 and "empreinte différente" in b["absents_distants"][0]
    assert not (racine / "data/lake/etat/v.csv").exists()


def test_lignee_et_etat(bac, monkeypatch):
    racine, _, _ = bac
    (racine / "pipeline").mkdir()
    f = racine / "data/lake/secu/r.json"
    f.parent.mkdir(parents=True)
    f.write_text("[1]", encoding="utf-8")
    (racine / "data/lake/secu/collecte.json").write_text("{}", encoding="utf-8")   # journal : hors lignée
    monkeypatch.setattr(ed, "entrees_etape", lambda e, entrees=None: [
        {"chemin": "data/lake/secu", "type": "hors_catalogue", "source": None, "url": None}])
    ed.lignee(["retraites"], {"retraites": "2026-11-17T00:00:00Z"})
    doc = json.loads((racine / "pipeline/lignee.json").read_text(encoding="utf-8"))
    assert list(doc["etapes"]["retraites"]["fichiers"]) == ["data/lake/secu/r.json"]
    assert ed.etat_lignee("retraites", racine) == (True, "versions enregistrées présentes")
    assert ed.env_lignee("retraites") == {"SOURCE_DATE_EPOCH": "1794873600"}
    f.write_text("[1, 2]", encoding="utf-8")
    ok, motif = ed.etat_lignee("retraites", racine)
    assert not ok and "autre(s) version(s)" in motif
    assert not ed.etat_lignee("inconnue", racine)[0]


def test_verifier_reconstruction(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "entrees_etape", lambda e, entrees=None: [
        {"chemin": "data/lake/_restreint/x" if e == "sport" else "data/lake/etat/x"}])
    monkeypatch.setattr(ed, "charger_entrees", lambda: {"etapes": {}})
    j = tmp_path / "journal.json"
    j.write_text(json.dumps({"etapes": [{"etape": "base", "statut": "produit"},
                                        {"etape": "sport", "statut": "conserve", "motif": "entrée absente"}]}))
    assert ed.verifier(j) == (0, [])                       # zone restreinte : régénérée sur le VPS seulement
    assert ed.verifier(j, hors_ci_restreint=False)[0] == ed.CODE_INCOMPLET
    j.write_text(json.dumps({"etapes": [{"etape": "decisions", "statut": "conserve", "motif": "cache absent"}]}))
    code, inc = ed.verifier(j)
    assert code == ed.CODE_INCOMPLET and inc[0].startswith("decisions : conserve")


def test_diagnostic_couvre_toutes_les_etapes():
    import tout
    d = ed.diagnostic()
    assert list(d) == [e.id for e in tout.ordre()]
    for eid, x in d.items():
        assert x["verdict"], eid
        assert all(e["recollecte"].startswith("VPS seulement") for e in x["entrees"] if e["restreint"])


# --- Garde-fou de lignes -----------------------------------------------------------------------------------------

def test_compter():
    assert gl.compter(b'{"a": [1, 2, {"b": [3]}], "c": {"d": []}}', "x.json") == 4
    assert gl.compter(b"a,b\n1,2\n3,4\n", "x.csv") == 2
    assert gl.compter(b"pas du json", "x.json") == 0
    assert gl.compter(b"\x00", "x.parquet") == 0
    assert gl.axe("site/data/local/communes/44.json") == "site/data/local"
    assert gl.axe("site/data/cofog.json") == "site/data/cofog.json"


def test_controler_et_autorisations(tmp_path, monkeypatch):
    f = tmp_path / "pertes.json"
    f.write_text(json.dumps({"pertes": [
        {"axe": "local", "lignes_max": 10, "motif": "doublons retirés par la source", "jusqu_au": "2099-01-01"},
        {"axe": "secu", "lignes_max": 1000, "motif": "", "jusqu_au": "2099-01-01"},        # sans motif : nul
        {"axe": "dette", "lignes_max": 1000, "motif": "ancien", "jusqu_au": "2000-01-01"},  # périmée
    ]}), encoding="utf-8")
    monkeypatch.setattr(gl, "AUTORISATIONS", f)
    permis = gl.autorisations()
    assert set(permis) == {"site/data/local"}
    avant = {"site/data/local": 100, "site/data/secu": 50, "site/data/dette": 5, "site/data/ue": 3}
    refus, admises = gl.controler(avant, {"site/data/local": 92, "site/data/secu": 49, "site/data/dette": 6,
                                          "site/data/ue": 3}, permis)
    assert len(admises) == 1 and "doublons" in admises[0]
    assert refus == ["site/data/secu : 50 -> 49 lignes (1 perdues), sans motif compté"]
    refus, _ = gl.controler({"site/data/local": 100}, {"site/data/local": 80}, permis)
    assert "au-delà des 10 admises" in refus[0]
    refus, _ = gl.controler({"site/data/ue": 3}, {}, permis)            # axe supprimé : tout est perdu
    assert refus and "3 perdues" in refus[0]


def test_garde_fou_sur_un_depot_git(tmp_path, monkeypatch):
    r = tmp_path / "depot"
    (r / "site/data/axe").mkdir(parents=True)
    (r / "site/data/axe/a.json").write_text(json.dumps({"lignes": [1, 2, 3]}), encoding="utf-8")
    (r / "site/data/meta.json").write_text(json.dumps({"x": [1, 2]}), encoding="utf-8")
    g = ["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    subprocess.run([*g, "add", "."], check=True)
    subprocess.run([*g, "commit", "-qm", "i"], check=True)
    monkeypatch.setattr(gl, "ROOT", r)
    monkeypatch.setattr(gl, "AUTORISATIONS", r / "absent.json")
    assert gl.main([]) == 0
    (r / "site/data/axe/a.json").write_text(json.dumps({"lignes": [1, 2]}), encoding="utf-8")
    (r / "site/data/meta.json").write_text("{}", encoding="utf-8")         # ignoré (horodatage)
    assert gl.main([]) == gl.CODE_PERTE
    (r / "site/data/axe/b.json").write_text(json.dumps([9]), encoding="utf-8")   # découpage : rien de perdu
    assert gl.main([]) == 0


# --- Branchement dans le workflow --------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def data_yml():
    return yaml.safe_load((ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8"))


def test_workflow_lit_le_bucket_public_en_lecture_seule(data_yml):
    pas = {p.get("name"): p for p in data_yml["jobs"]["produire"]["steps"]}
    r = pas["Restaurer l'entrepot depuis le bucket public (lecture seule)"]
    assert "entrepot_distant.py restaurer" in r["run"]
    assert not any("PRIVE" in k for k in r["env"])                         # aucun accès au bucket privé
    assert set(k for k in r["env"] if "S3" in k) == {"OVMI_S3_LECTURE_ID", "OVMI_S3_LECTURE_SECRET"}
    noms = [p.get("name") for p in data_yml["jobs"]["produire"]["steps"]]
    assert noms.index("Restaurer l'entrepot (cache)") < noms.index(r["name"]) < noms.index(
        "Completer l'entrepot (sources du catalogue lues par les etapes)")
    for p in data_yml["jobs"]["produire"]["steps"]:
        if "actions/cache" in str(p.get("uses")):
            assert "!data/lake/_restreint" in p["with"]["path"]
    assert data_yml["jobs"]["produire"]["permissions"] == {"contents": "read"}


def test_workflow_reconstruction_et_garde_fou(data_yml):
    assert data_yml[True]["workflow_dispatch"]["inputs"]["reconstruction"]["type"] == "boolean"
    pas = {p.get("name"): p for p in data_yml["jobs"]["produire"]["steps"]}
    assert "pipeline/garde_lignes.py" in pas["Valider (Frictionless, contrat --strict, pytest)"]["run"]
    assert "entrepot_distant.py verifier" in pas["Reconstruction complete (tous les axes produits ?)"]["run"]
    cond = data_yml["jobs"]["publier"]["if"]
    assert "needs.produire.outputs.complet == 'oui'" in cond and "reconstruction != 'true'" in cond
    assert "needs.produire.outputs.tests == 'ok'" in cond
