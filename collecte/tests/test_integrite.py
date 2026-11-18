"""Controle d'integrite des telechargements (collecte/integrite.py, collecte.telecharger, pipeline/fetch.get)
contre un petit serveur HTTP local qui coupe la connexion, annonce une taille fausse ou sert un PDF
sans %%EOF. Aucun acces a Internet."""
import gzip
import io
import json
import socket
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

import collecte as C
import integrite as I

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline"))
import fetch  # noqa: E402

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n" + b"x" * 5000 + b"\ntrailer\n<<>>\nstartxref\n0\n%%EOF\n"


def _zip() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.csv", "id;v\n" + "".join(f"{i};{i * 7}\n" for i in range(2000)))
    return b.getvalue()


ZIP = _zip()
CSV = b"id;libelle;montant\n1;a;10\n2;b;20\n3;c;30\n"
JSON = json.dumps([{"a": i} for i in range(300)]).encode()


class Serveur(BaseHTTPRequestHandler):
    """Routes : /<cas>/<nom>. compteur[cas] = nombre de requetes recues."""
    compteur: dict = {}
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _envoyer(self, code, corps, longueur=None, entetes=None, couper_a=None):
        self.send_response(code)
        for k, v in (entetes or {}).items():
            self.send_header(k, v)
        if longueur is not None:
            self.send_header("Content-Length", str(longueur))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(corps[:couper_a] if couper_a is not None else corps)
        self.wfile.flush()
        self.close_connection = True

    def do_GET(self):
        cas = self.path.strip("/").split("/")[0].split("?")[0]
        n = Serveur.compteur[cas] = Serveur.compteur.get(cas, 0) + 1
        if cas == "pdf_ok":
            return self._envoyer(200, PDF, len(PDF))
        if cas == "pdf_coupe":            # Content-Length juste, connexion coupee a mi-chemin
            return self._envoyer(200, PDF, len(PDF), couper_a=len(PDF) // 2)
        if cas == "pdf_coupe_puis_ok":    # coupure au 1er essai, complet au 2e
            return self._envoyer(200, PDF, len(PDF), couper_a=1000 if n == 1 else None)
        if cas == "pdf_taille_fausse":    # annonce plus court que le vrai fichier : client lit 60 %
            return self._envoyer(200, PDF, int(len(PDF) * 0.6))
        if cas == "pdf_sans_longueur":    # pas de Content-Length, fermeture apres 4,8/7,6 du fichier
            return self._envoyer(200, PDF, None, couper_a=int(len(PDF) * 4.8 / 7.6))
        if cas == "pdf_sans_eof":
            corps = PDF.replace(b"%%EOF", b"")
            return self._envoyer(200, corps, len(corps))
        if cas == "html_au_lieu_du_pdf":
            corps = b"<!DOCTYPE html><html><body>Veuillez patienter</body></html>"
            return self._envoyer(200, corps, len(corps))
        if cas == "zip_tronque":
            return self._envoyer(200, ZIP[: len(ZIP) - 200], None)
        if cas == "zip_ok":
            return self._envoyer(200, ZIP, len(ZIP))
        if cas == "json_tronque":
            return self._envoyer(200, JSON[:-40], None)
        if cas == "json_gzip":            # Content-Length = taille compressee : ne doit pas etre refuse
            z = gzip.compress(JSON)
            return self._envoyer(200, z, len(z), {"Content-Encoding": "gzip"})
        if cas == "csv_tronque":
            return self._envoyer(200, CSV[:-6], None)
        if cas == "csv_ok":
            return self._envoyer(200, CSV, len(CSV))
        if cas == "interdit":
            return self._envoyer(403, b"interdit", 8)
        if cas == "trop_de_requetes":
            return self._envoyer(429, b"lent", 4, {"Retry-After": "1"})
        return self._envoyer(404, b"absent", 6)


@pytest.fixture(scope="module")
def serveur():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Serveur)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


@pytest.fixture
def lac(tmp_path, monkeypatch):
    Serveur.compteur.clear()
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    for v in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    return tmp_path


def client(essais=3):
    s = requests.Session()
    s.trust_env = False   # serveur local : pas de mandataire
    return C.Client(pause=0, session=s, essais=essais, read_timeout=10)


# ---------------------------------------------------------------- collecte.telecharger

def test_pdf_complet_accepte(serveur, lac):
    res = C.telecharger(client(), f"{serveur}/pdf_ok/a.pdf", lac / "a.pdf")
    assert (lac / "a.pdf").read_bytes() == PDF and res["octets"] == len(PDF)
    assert not (lac / "a.pdf.part").exists() and not (lac / "a.pdf.part.json").exists()


@pytest.mark.parametrize("cas", ["pdf_coupe", "pdf_taille_fausse", "pdf_sans_longueur", "pdf_sans_eof",
                                 "html_au_lieu_du_pdf"])
def test_pdf_invalide_refuse_et_version_valide_conservee(serveur, lac, cas):
    cible = lac / "compte_general.pdf"
    cible.write_bytes(PDF)                       # version valide deja presente
    with pytest.raises(RuntimeError, match="version precedente conservee"):
        C.telecharger(client(), f"{serveur}/{cas}/x.pdf", cible, essais_flux=3)
    assert cible.read_bytes() == PDF             # jamais remplacee
    assert not (lac / "compte_general.pdf.part").exists() or cas == "pdf_coupe"
    assert Serveur.compteur[cas] == 3            # 3 essais espaces, puis echec explicite


def test_pdf_sans_eof_leve_integrite_invalide(serveur, lac):
    with pytest.raises(I.IntegriteInvalide, match="%%EOF"):
        C.telecharger(client(), f"{serveur}/pdf_sans_eof/x.pdf", lac / "x.pdf", essais_flux=2)
    assert not (lac / "x.pdf").exists()


def test_coupure_puis_reussite_au_second_essai(serveur, lac):
    C.telecharger(client(), f"{serveur}/pdf_coupe_puis_ok/x.pdf", lac / "x.pdf")
    assert (lac / "x.pdf").read_bytes() == PDF and Serveur.compteur["pdf_coupe_puis_ok"] == 2


@pytest.mark.parametrize("cas,nom", [("zip_tronque", "a.zip"), ("zip_tronque", "a.xlsx"),
                                     ("json_tronque", "a.json"), ("csv_tronque", "a.csv")])
def test_formats_tronques_refuses(serveur, lac, cas, nom):
    with pytest.raises(I.IntegriteInvalide):
        C.telecharger(client(), f"{serveur}/{cas}/{nom}", lac / nom, essais_flux=2)
    assert not (lac / nom).exists()


@pytest.mark.parametrize("cas,nom", [("zip_ok", "a.zip"), ("csv_ok", "a.csv"), ("json_gzip", "a.json")])
def test_formats_complets_acceptes(serveur, lac, cas, nom):
    C.telecharger(client(), f"{serveur}/{cas}/{nom}", lac / nom)
    assert (lac / nom).exists()


def test_403_ni_reessaye_ni_contourne(serveur, lac):
    (lac / "x.pdf").write_bytes(PDF)
    with pytest.raises(RuntimeError, match="acces refuse"):
        C.telecharger(client(), f"{serveur}/interdit/x.pdf", lac / "x.pdf")
    assert Serveur.compteur["interdit"] == 1 and (lac / "x.pdf").read_bytes() == PDF


def test_429_pas_de_reprises_supplementaires(serveur, lac):
    # seules les reprises polies du Client (Retry-After) ; la boucle d'integrite n'en ajoute pas
    with pytest.raises(RuntimeError, match="injoignable"):
        C.telecharger(client(essais=2), f"{serveur}/trop_de_requetes/x.pdf", lac / "x.pdf", essais_flux=5)
    assert Serveur.compteur["trop_de_requetes"] == 2


def test_collecter_garde_la_version_precedente(serveur, lac, monkeypatch):
    monkeypatch.setattr(C, "ROOT", lac)
    monkeypatch.setattr(C, "LAKE", lac / "data" / "lake")
    cible = lac / "data" / "lake" / "etat" / "s" / "b.pdf"
    cible.parent.mkdir(parents=True)
    cible.write_bytes(PDF)
    vieux = {"chemin": "data/lake/etat/s/b.pdf", "octets": len(PDF), "sha256": "x", "signature": None}
    src = {"id": "s", "type": "urls", "domaine": "etat", "titre": "T",
           "urls": [{"url": f"{serveur}/csv_ok/a.csv", "nom": "a.csv"}, {"url": f"{serveur}/pdf_coupe/b.pdf", "nom": "b.pdf"}]}
    e = C.collecter(client(), src, {"statut": "ok", "fichiers": [vieux]}, {}, timeout_s=120)
    assert e["statut"] == "partiel" and cible.read_bytes() == PDF
    assert any(f["chemin"].endswith("b.pdf") and f.get("donnees_anterieures") for f in e["fichiers"])


# ---------------------------------------------------------------- pipeline/fetch.get

def test_fetch_refuse_json_tronque(serveur, lac):
    with pytest.raises(SystemExit, match="incomplet"):
        fetch.get(f"{serveur}/json_tronque/x", tries=2, controle="json")
    assert Serveur.compteur["json_tronque"] == 2


def test_fetch_refuse_coupure_et_taille_fausse(serveur, lac):
    with pytest.raises(SystemExit):
        fetch.get(f"{serveur}/pdf_coupe/x", tries=2)
    with pytest.raises(SystemExit):
        fetch.get(f"{serveur}/pdf_taille_fausse/x", tries=2, controle="pdf")


def test_fetch_accepte_complet_et_gzip(serveur, lac):
    assert fetch.get(f"{serveur}/csv_ok/x", controle="csv").content == CSV
    assert fetch.get(f"{serveur}/json_gzip/x", controle="json").json()[0] == {"a": 0}


def test_fetch_403_immediat(serveur, lac):
    with pytest.raises(SystemExit, match="aucun contournement"):
        fetch.get(f"{serveur}/interdit/x")
    assert Serveur.compteur["interdit"] == 1


def test_fetch_write_json_atomique(lac):
    p = lac / "raw" / "s.json"
    fetch.write_json(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1} and not (lac / "raw" / "s.json.part").exists()


# ---------------------------------------------------------------- integrite.py seul

def test_csv_sans_saut_final_mais_complet_accepte():
    I.verifier_octets(b"a;b;c\n1;2;3\n4;5;6", "x.csv")
    with pytest.raises(I.IntegriteInvalide):
        I.verifier_octets(b"a;b;c\n1;2;3\n4;5", "x.csv")
    with pytest.raises(I.IntegriteInvalide):
        I.verifier_octets(b'a;b;c\n1;2;3\n4;5;"texte coup', "x.csv")


def test_signature_prime_sur_extension_et_taille_annoncee():
    I.verifier_octets(ZIP, "ressource.csv")              # csv servi zippe : controle en archive
    with pytest.raises(I.IntegriteInvalide):
        I.verifier_octets(ZIP[:-100], "ressource.csv")
    with pytest.raises(I.IntegriteInvalide, match="annonces"):
        I.verifier_octets(PDF, "x.pdf", octets_attendus=len(PDF) + 1)


def test_parquet_ole_ndjson():
    with pytest.raises(I.IntegriteInvalide, match="incomplet"):
        I.verifier_octets(b"PAR1-coupe", "x.parquet")
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 22 + (9).to_bytes(2, "little") + b"\0" * (512 - 32)
    I.verifier_octets(ole + b"\0" * 1024, "x.xls")
    with pytest.raises(I.IntegriteInvalide, match="OLE"):
        I.verifier_octets(ole + b"\0" * 1000, "x.xls")
    I.verifier_octets(b'{"a":1}\n{"b":2}\n', "x.ndjson")
    with pytest.raises(I.IntegriteInvalide):
        I.verifier_octets(b'{"a":1}\n{"b":', "x.ndjson")
