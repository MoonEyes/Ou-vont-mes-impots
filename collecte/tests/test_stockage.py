"""Tests hors reseau du stockage objet : conversion Parquet, deduplication, historique, reprise apres
echec d'envoi, separation du prive, manifeste distant, absence de secret dans le depot.
Le transfert est simule (FauxTransfert) ; un test de bout en bout utilise un vrai rclone avec un
remote de type « local » (saute si rclone n'est pas installe)."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("duckdb")  # deploy/requirements-vps.txt

import collecte as C
import conversion
import stockage as S
from conftest import FauxResp, client

DEPOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- outils

class FauxTransfert:
    """Remote en memoire : {"bucket/cle": octets}. `pannes` : nombre d'envois a faire echouer."""

    def __init__(self, pannes=0):
        self.objets = {}
        self.envois = []
        self.pannes = pannes

    def envoyer(self, local, distant):
        self.envois.append(distant)
        if self.pannes:
            self.pannes -= 1
            raise S.ErreurEnvoi("coupure reseau simulee")
        data = Path(local).read_bytes()
        self.objets[distant] = data
        return {"octets": len(data), "md5": hashlib.md5(data).hexdigest(), "verification": "md5"}

    def info(self, distant):
        return {"Size": len(self.objets[distant])} if distant in self.objets else None

    def supprimer(self, distant):
        self.objets.pop(distant, None)

    def recuperer(self, distant, local):
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        Path(local).write_bytes(self.objets[distant])


ENV = {"OVMI_BUCKET_PUBLIC": "pub", "OVMI_BUCKET_PRIVE": "prive", "OVMI_REMOTE": "ovh"}


def flux(transfert=None, env=ENV, **kw):
    return S.Flux(S.Config.depuis_env(env), transfert or FauxTransfert(), **kw)


def fichier(lac, rel, contenu: bytes, restreint=False):
    p = lac / ("_restreint" if restreint else "") / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu)
    return {"chemin": str(p.relative_to(lac.parent.parent)), "sha256": hashlib.sha256(contenu).hexdigest(),
            "octets": len(contenu)}


CSV = "code;libelle;montant\n01001;Abergement;12,5\n02002;Aisne;7\n".encode()


# ---------------------------------------------------------------- conversion

def test_conversion_csv_parquet_fidele(tmp_path):
    src = tmp_path / "a.www_downlo"  # extension trompeuse : detection sur le contenu
    src.write_bytes(CSV)
    res = conversion.convertir(src)
    assert res.format == "csv" and res.converti and not res.garde_original
    import pyarrow.parquet as pq
    t = pq.read_table(res.sorties[0].chemin).to_pydict()
    assert t["code"] == ["01001", "02002"]  # zeros initiaux conserves (colonnes en texte)
    assert t["montant"] == ["12,5", "7"]
    assert res.sorties[0].nom == "a.www_downlo.parquet" and res.sorties[0].lignes == 2
    assert src.exists()  # l'original n'est efface qu'apres envoi verifie


def test_conversion_csv_latin1(tmp_path):
    src = tmp_path / "b.csv"
    src.write_bytes("commune;montant\nÉvreux;3\nSèvres;4\n".encode("cp1252"))
    res = conversion.convertir(src)
    import pyarrow.parquet as pq
    assert pq.read_table(res.sorties[0].chemin).to_pydict()["commune"] == ["Évreux", "Sèvres"]


def test_conversion_json_tabulaire_ndjson_et_objet(tmp_path):
    a = tmp_path / "a.json"
    a.write_text(json.dumps([{"x": 1, "y": "a"}, {"x": 2, "y": "b"}]))
    n = tmp_path / "n.ndjson"
    n.write_text('{"x": 1}\n{"x": 2}\n{"x": 3}\n')
    o = tmp_path / "o.json"
    o.write_text(json.dumps({"version": "2.0", "value": {"0": 1}}))  # JSON-stat : pas tabulaire
    assert conversion.convertir(a).sorties[0].lignes == 2
    assert conversion.convertir(n).sorties[0].lignes == 3
    r = conversion.convertir(o)
    assert r.format == "json_objet" and r.garde_original and not r.erreurs and r.sorties[0].chemin == o


def test_conversion_xlsx_toutes_feuilles(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Donnees 2024"
    ws.append(["Titre du tableau"])
    ws.append(["dep", "montant"])
    ws.append(["01", 3.5])
    wb.create_sheet("vide")
    wb.save(tmp_path / "t.xlsx")
    res = conversion.convertir(tmp_path / "t.xlsx")
    assert res.format == "xlsx" and len(res.sorties) == 1
    import pyarrow.parquet as pq
    t = pq.read_table(res.sorties[0].chemin).to_pydict()
    assert t["c0"] == ["Titre du tableau", "dep", "01"] and t["c1"] == [None, "montant", "3.5"]


def test_conversion_pdf_garde_et_csv_casse_garde(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 ...")
    r = conversion.convertir(pdf)
    assert r.format == "pdf" and r.garde_original and not r.erreurs
    casse = tmp_path / "casse.csv"
    casse.write_bytes(b"a;b\n1;2\n3;4;5;6\n7;8\n")
    r = conversion.convertir(casse)
    assert r.garde_original and r.erreurs and r.sorties[0].chemin == casse  # echec note, original garde


def test_conversion_zip_tabulaire_et_reste(tmp_path):
    z = tmp_path / "archive.zip"
    gros = "id;val\n" + "".join(f"{i:05d};{i % 7}\n" for i in range(20000))
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zo:
        zo.writestr("dossier/donnees.csv", gros)
        zo.writestr("LISEZMOI.pdf", b"%PDF-1.4 notice")
    res = conversion.convertir(z)
    noms = sorted(s.nom for s in res.sorties)
    assert noms == ["archive.zip/_reste.zip", "archive.zip/dossier/donnees.csv.parquet"]
    assert res.octets_apres < res.octets_avant
    with zipfile.ZipFile(next(s.chemin for s in res.sorties if s.nom.endswith("_reste.zip"))) as zr:
        assert zr.read("LISEZMOI.pdf") == b"%PDF-1.4 notice"  # rien n'est perdu
    conversion.nettoyer_resultat(res)
    assert not (tmp_path / "archive.zip.d").exists() and z.exists()


# ---------------------------------------------------------------- flux : envoi, deduplication, historique

def test_envoi_converti_puis_efface_et_manifeste(lac):
    f = fichier(lac, "etat/src1/a.csv", CSV)
    e = {"domaine": "etat", "zone": "publique", "fichiers": [f]}
    fx = flux()
    S.Flux.traiter_source(fx, "src1", e, {}, date="2026-11-16")
    st = f["stockage"]
    assert f["objet"] == "s3://pub/etat/src1/2026-11-16/a.csv.parquet"
    assert list(fx.transfert.objets) == ["pub/etat/src1/2026-11-16/a.csv.parquet"]
    assert st["sha256_brut"] == f["sha256"] and st["octets_avant"] == len(CSV) and st["octets_apres"] > 0
    assert st["converti"] is True and len(st["versions"]) == 1 and e["stockage_statut"] == "ok"
    assert not (C.ROOT / f["chemin"]).exists()  # efface en local apres verification
    assert not (lac / "_envoi" / "src1").exists()


def test_pas_de_doublon_si_empreinte_inchangee(lac):
    f = fichier(lac, "etat/src1/a.csv", CSV)
    e = {"domaine": "etat", "fichiers": [f]}
    fx = flux()
    fx.traiter_source("src1", e, {}, date="2026-11-09")
    ancien = json.loads(json.dumps(e))
    # semaine suivante : meme contenu retelecharge
    f2 = fichier(lac, "etat/src1/a.csv", CSV)
    e2 = {"domaine": "etat", "fichiers": [f2]}
    fx.traiter_source("src1", e2, ancien, date="2026-11-16")
    assert len(fx.transfert.envois) == 1  # rien renvoye
    assert f2["stockage"]["date_version"] == "2026-11-09" and f2["stockage"]["verifie_le"]
    assert not (C.ROOT / f2["chemin"]).exists() and fx.dedupliques == 1


def test_historique_nouvelle_version_si_contenu_change(lac):
    fx = flux()
    f = fichier(lac, "etat/src1/a.csv", CSV)
    e = {"domaine": "etat", "fichiers": [f]}
    fx.traiter_source("src1", e, {}, date="2026-11-09")
    ancien = json.loads(json.dumps(e))
    f2 = fichier(lac, "etat/src1/a.csv", CSV + b"03003;Allier;1\n")
    e2 = {"domaine": "etat", "fichiers": [f2]}
    fx.traiter_source("src1", e2, ancien, date="2026-11-16")
    assert sorted(fx.transfert.objets) == ["pub/etat/src1/2026-11-09/a.csv.parquet",
                                          "pub/etat/src1/2026-11-16/a.csv.parquet"]
    assert [v["date_version"] for v in f2["stockage"]["versions"]] == ["2026-11-09", "2026-11-16"]


def test_reprise_apres_echec_envoi(lac):
    t = FauxTransfert(pannes=1)
    fx = flux(t)
    f = fichier(lac, "etat/src1/a.csv", CSV)
    e = {"domaine": "etat", "fichiers": [f]}
    fx.traiter_source("src1", e, {}, date="2026-11-16")
    assert f["envoi_en_attente"] and "coupure" in f["erreur_envoi"] and e["stockage_statut"] == "echec"
    assert (C.ROOT / f["chemin"]).exists() and not t.objets and fx.echecs == 1  # brut garde en local
    assert "stockage" not in f
    # passage suivant : la collecte reutilise l'entree (fichier local present) et l'envoi reprend
    ancien = json.loads(json.dumps(e))
    e2 = {"domaine": "etat", "fichiers": [dict(ancien["fichiers"][0])]}
    fx.traiter_source("src1", e2, ancien, date="2026-11-23")
    f2 = e2["fichiers"][0]
    assert "envoi_en_attente" not in f2 and f2["stockage"]["date_version"] == "2026-11-23"
    assert not (C.ROOT / f2["chemin"]).exists() and list(t.objets) == ["pub/etat/src1/2026-11-23/a.csv.parquet"]


def test_echec_partiel_ne_laisse_pas_d_objet_orphelin(lac):
    z = lac / "etat" / "src1" / "a.zip"
    z.parent.mkdir(parents=True)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zo:
        zo.writestr("x.csv", "id;v\n" + "".join(f"{i};{i}\n" for i in range(5000)))
        zo.writestr("y.csv", "id;w\n" + "".join(f"{i};{i}\n" for i in range(5000)))
    contenu = z.read_bytes()
    f = {"chemin": str(z.relative_to(C.ROOT)), "sha256": hashlib.sha256(contenu).hexdigest(), "octets": len(contenu)}

    class SecondEnvoiEnPanne(FauxTransfert):
        def envoyer(self, local, distant):
            if self.envois:
                self.envois.append(distant)
                raise S.ErreurEnvoi("panne")
            return super().envoyer(local, distant)
    t = SecondEnvoiEnPanne()
    flux(t).traiter_source("src1", {"domaine": "etat", "fichiers": [f]}, {}, date="2026-11-16")
    assert len(t.envois) == 2 and t.objets == {} and z.exists() and f["envoi_en_attente"]


# ---------------------------------------------------------------- separation du prive

def test_restreint_vers_bucket_prive_jamais_public(lac):
    t = FauxTransfert()
    fx = flux(t)
    fr = fichier(lac, "beneficiaires/src_p/noms.csv", CSV, restreint=True)
    fp = fichier(lac, "etat/src1/a.csv", CSV)
    fx.traiter_source("src_p", {"domaine": "beneficiaires", "zone": "restreinte", "fichiers": [fr]}, {}, date="2026-11-16")
    # meme si l'entree a perdu son marquage, le chemin _restreint/ suffit
    fr2 = fichier(lac, "beneficiaires/src_q/noms.csv", CSV + b"x;y;z\n", restreint=True)
    fx.traiter_source("src_q", {"domaine": "beneficiaires", "fichiers": [fr2]}, {}, date="2026-11-16")
    fx.traiter_source("src1", {"domaine": "etat", "fichiers": [fp]}, {}, date="2026-11-16")
    assert all(k.startswith("prive/") for k in t.objets if "/src_p/" in k or "/src_q/" in k)
    assert [k for k in t.objets if k.startswith("pub/")] == ["pub/etat/src1/2026-11-16/a.csv.parquet"]
    assert fr["objet"].startswith("s3://prive/") and fr["stockage"]["zone"] == "privee"


def test_restreint_sans_bucket_prive_reste_en_local(lac):
    t = FauxTransfert()
    fx = flux(t, env={"OVMI_BUCKET_PUBLIC": "pub"})
    fr = fichier(lac, "beneficiaires/src_p/noms.csv", CSV, restreint=True)
    e = {"domaine": "beneficiaires", "zone": "restreinte", "fichiers": [fr]}
    fx.traiter_source("src_p", e, {}, date="2026-11-16")
    assert t.envois == [] and (C.ROOT / fr["chemin"]).exists() and fr["envoi_en_attente"]
    assert "OVMI_BUCKET_PRIVE" in fr["erreur_envoi"]


def test_config_refuse_prive_egal_public_et_exige_public():
    with pytest.raises(S.ErreurConfig):
        S.Config.depuis_env({"OVMI_BUCKET_PUBLIC": "b", "OVMI_BUCKET_PRIVE": "b"})
    with pytest.raises(S.ErreurConfig):
        S.Config.depuis_env({"OVMI_BUCKET_PUBLIC": "b/public", "OVMI_BUCKET_PRIVE": "b"})
    with pytest.raises(S.ErreurConfig):
        S.Config.depuis_env({})
    assert S.Config.depuis_env({"OVMI_BUCKET_PUBLIC": "b/public", "OVMI_BUCKET_PRIVE": "b/prive"}).bucket(True) == "b/prive"


def test_manifeste_sauvegarde_public_filtre_et_prive_complet(lac):
    t = FauxTransfert()
    fx = flux(t)
    C.maj_manifeste("pub_src", {"domaine": "etat", "zone": "publique", "fichiers": []})
    C.maj_manifeste("priv_src", {"domaine": "beneficiaires", "zone": "restreinte", "fichiers": []})
    S.sauver_manifeste(fx)
    public = json.loads(t.objets["pub/_manifeste/manifest.json"])
    prive = json.loads(t.objets["prive/_manifeste/manifest.json"])
    assert list(public) == ["pub_src"] and sorted(prive) == ["priv_src", "pub_src"]
    assert any(k.startswith("prive/_manifeste/historique/") for k in t.objets)
    # restauration sur une machine neuve
    C.MANIFEST.unlink()
    assert S.restaurer_manifeste(fx) and sorted(C.lire_manifeste()) == ["priv_src", "pub_src"]


def test_migration_entrepot_local(lac):
    t = FauxTransfert()
    fx = flux(t)
    f1 = fichier(lac, "etat/src1/a.csv", CSV)
    f2 = fichier(lac, "etat/src1/doc.pdf", b"%PDF-1.4 rapport")
    C.maj_manifeste("src1", {"domaine": "etat", "zone": "publique", "collecte_le": "2026-11-15T10:00:00+00:00",
                             "statut": "ok", "fichiers": [f1, f2]})
    assert S.migrer(fx, essai=True, journal=lambda *a: None)["fichiers"] == 2 and not t.objets
    S.migrer(fx, journal=lambda *a: None)
    m = C.lire_manifeste()["src1"]
    assert {f["objet"] for f in m["fichiers"]} == {"s3://pub/etat/src1/2026-11-15/a.csv.parquet",
                                                   "s3://pub/etat/src1/2026-11-15/doc.pdf"}
    assert not (lac / "etat" / "src1" / "a.csv").exists() and "pub/_manifeste/manifest.json" in t.objets
    n = len(t.envois)
    assert S.migrer(fx, journal=lambda *a: None)["sources"] == 0  # relance : rien a faire
    assert len(t.envois) == n


# ---------------------------------------------------------------- branchement dans collecte.py (--flux)

def test_collecte_flux_reutilise_un_fichier_stocke_sans_le_retelecharger(lac, monkeypatch):
    monkeypatch.setattr(C, "STOCKE_A_DISTANCE", True)
    vieux = {"chemin": "data/lake/etat/x.csv", "octets": 5, "signature": "sig1",
             "stockage": {"sha256_brut": "abc", "objets": [{"url": "s3://pub/etat/x/2026-11-09/x.csv.parquet"}]}}
    assert C._fichier_reutilisable(vieux, "sig1")
    assert not C._fichier_reutilisable({**vieux, "envoi_en_attente": True}, "sig1")
    monkeypatch.setattr(C, "STOCKE_A_DISTANCE", False)
    assert not C._fichier_reutilisable(vieux, "sig1")


def test_collecte_flux_requete_conditionnelle_sans_fichier_local(lac, monkeypatch):
    monkeypatch.setattr(C, "STOCKE_A_DISTANCE", True)
    vu = {}

    def route(h, p):
        vu.update(h)
        return FauxResp(304)
    res = C.telecharger(client({"u": route}), "u", lac / "x.csv", ancien={"etag": '"e1"'})
    assert res == {"inchange": True} and vu["If-None-Match"] == '"e1"'


def test_collecte_main_flux_sans_configuration(lac, monkeypatch, capsys):
    for k in ("OVMI_BUCKET_PUBLIC", "OVMI_BUCKET_PRIVE"):
        monkeypatch.delenv(k, raising=False)
    assert C.main(["--flux", "inexistant"]) == 78
    assert "OVMI_BUCKET_PUBLIC" in capsys.readouterr().err


# ---------------------------------------------------------------- bout en bout avec un vrai rclone (remote local)

@pytest.mark.skipif(not shutil.which("rclone"), reason="rclone non installe")
def test_bout_en_bout_rclone_remote_local(lac, tmp_path, monkeypatch):
    distant = tmp_path / "s3"
    monkeypatch.setenv("RCLONE_CONFIG_TESTLOCAL_TYPE", "local")
    monkeypatch.setenv("RCLONE_CONFIG", str(tmp_path / "absent.conf"))
    env = {"OVMI_REMOTE": "testlocal", "OVMI_BUCKET_PUBLIC": f"{distant}/pub", "OVMI_BUCKET_PRIVE": f"{distant}/prive",
           "OVMI_BWLIMIT": "50M"}
    fx = S.Flux.depuis_env(env=env)
    f = fichier(lac, "etat/src1/a.csv", CSV)
    fr = fichier(lac, "beneficiaires/src_p/n.csv", CSV, restreint=True)
    C.maj_manifeste("src1", {"domaine": "etat", "zone": "publique", "collecte_le": "2026-11-16T03:00:00+00:00",
                             "fichiers": [f]})
    C.maj_manifeste("src_p", {"domaine": "beneficiaires", "zone": "restreinte",
                              "collecte_le": "2026-11-16T03:00:00+00:00", "fichiers": [fr]})
    S.migrer(fx, journal=lambda *a: None)
    assert fx.echecs == 0 and fx.envoyes == 2
    pub = sorted(str(p.relative_to(distant / "pub")) for p in (distant / "pub").rglob("*") if p.is_file())
    assert pub == ["_manifeste/manifest.json", "etat/src1/2026-11-16/a.csv.parquet"]
    assert (distant / "prive" / "beneficiaires" / "src_p" / "2026-11-16" / "n.csv.parquet").exists()
    assert "src_p" not in json.loads((distant / "pub" / "_manifeste" / "manifest.json").read_text())
    m = C.lire_manifeste()
    assert m["src1"]["fichiers"][0]["stockage"]["objets"][0]["verification"] == "md5"
    # restauration
    sortis = S.restaurer_source(fx, "src1", tmp_path / "restau")
    assert [p.name for p in sortis] == ["a.csv.parquet"] and sortis[0].stat().st_size > 0


# ---------------------------------------------------------------- aucun secret dans le depot

MOTIFS_SECRETS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"(?i)(secret_access_key|access_key_id|github_token|password)\s*[=:]\s*['\"]?[A-Za-z0-9/+]{16,}"),
]


def test_aucun_secret_dans_les_fichiers_du_depot():
    try:
        fichiers = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=DEPOT,
                                  capture_output=True, text=True, check=True).stdout.split("\n")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("pas un depot git")
    trouves = []
    for rel in filter(None, fichiers):
        p = DEPOT / rel
        if not p.is_file() or p.stat().st_size > 5_000_000 or p.suffix in (".gz", ".parquet", ".png", ".pdf"):
            continue
        texte = p.read_text(encoding="utf-8", errors="ignore")
        trouves += [f"{rel}: {m.group(0)[:30]}" for motif in MOTIFS_SECRETS for m in motif.finditer(texte)]
    assert trouves == []


def test_alerte_ne_publie_ni_zone_restreinte_ni_secret(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("alerte", DEPOT / "deploy" / "alerte.py")
    alerte = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(alerte)
    (tmp_path / "journaux").mkdir()
    (tmp_path / "journaux" / "collecte-2026-11-16.log").write_text(
        "ERREUR src_a lien mort\nERREUR data/lake/_restreint/x illisible\nERREUR secret=abc\n=== fin du lot : code 2\n")
    texte = alerte.extrait_journal(tmp_path)
    assert "src_a" in texte and "_restreint" not in texte and "secret" not in texte


def test_env_exemple_sans_valeur_secrete():
    exemple = DEPOT / "deploy" / "env.exemple"
    assert exemple.exists()
    for ligne in exemple.read_text(encoding="utf-8").splitlines():
        if ligne.strip().startswith("#") or "=" not in ligne:
            continue
        cle, valeur = ligne.split("=", 1)
        if any(m in cle for m in ("SECRET", "ACCESS_KEY", "TOKEN", "PASSWORD")):
            assert valeur.strip().strip('"') == "", f"{cle} doit rester vide dans env.exemple"
