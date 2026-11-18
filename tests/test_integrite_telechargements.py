"""Transversal : tout fichier telecharge par un module de pipeline/ passe par le controle d'integrite.

Analyse statique simple (ast, sans reseau) : une fonction qui recoit des octets du reseau (requests.get,
iter_content, .content d'une reponse, .raw, ou appel d'une fonction de telechargement) et les ecrit sur
disque (write_bytes, open en "wb"/"ab", copyfileobj) doit aussi appeler collecte/integrite.py :
remplacer_si_valide, verifier_fichier, verifier_flux, verifier_octets, ou fetch.get(..., controle=...).
Le controle se fait sur le temporaire avant le renommage atomique : une version valide deja presente
n'est jamais remplacee par un fichier tronque (cas du PDF de la Securite sociale tronque en 2026).

Seuls les modules suivis par git sont analyses (un fichier en cours chez un autre agent l'est a son commit).
Un second groupe de tests verifie le comportement de remplacer_si_valide (fichier local, sans reseau).
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE))

CONTROLES = {"remplacer_si_valide", "verifier_fichier", "verifier_flux", "verifier_octets"}
SOURCES_RESEAU = {"iter_content", "content", "raw"}          # attributs d'une reponse requests
APPELS_RESEAU = ("telecharg", "http_get")                    # fonctions de telechargement du depot


def modules() -> list[Path]:
    try:
        sortie = subprocess.run(["git", "ls-files", "pipeline/*.py"], cwd=ROOT, capture_output=True, text=True,
                                check=True).stdout.split()
        suivis = [ROOT / s for s in sortie if (ROOT / s).exists()]
    except (OSError, subprocess.CalledProcessError):
        suivis = []
    return sorted(suivis or PIPELINE.glob("*.py"))


def _nom_appel(n: ast.Call) -> str:
    f = n.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _mode_ecriture(n: ast.Call) -> bool:
    """open(x, "wb"), Path.open("ab"), gzip.open(x, "wb")..."""
    if _nom_appel(n) not in ("open", "GzipFile"):
        return False
    valeurs = list(n.args) + [k.value for k in n.keywords if k.arg == "mode"]
    return any(isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value[:1] in "wa" and "b" in v.value
               for v in valeurs)


def analyser(fonction: ast.AST) -> tuple[bool, bool, bool]:
    """(recoit du reseau, ecrit sur disque, passe par le controle d'integrite)"""
    reseau = ecrit = controle = False
    for n in ast.walk(fonction):
        if isinstance(n, ast.Attribute) and n.attr in SOURCES_RESEAU:
            reseau = True
        if isinstance(n, (ast.Attribute, ast.Name)) and (n.attr if isinstance(n, ast.Attribute) else n.id) in CONTROLES:
            controle = True
        if isinstance(n, ast.Call):
            nom = _nom_appel(n)
            if (nom == "get" and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "requests") or any(m in nom for m in APPELS_RESEAU):
                reseau = True
            if nom in ("write_bytes", "copyfileobj") or _mode_ecriture(n):
                ecrit = True
            if any(k.arg == "controle" for k in n.keywords):
                controle = True
    return reseau, ecrit, controle


def fautifs(source: str) -> list[str]:
    arbre = ast.parse(source)
    sortie = []
    for f in ast.walk(arbre):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            reseau, ecrit, controle = analyser(f)
            if reseau and ecrit and not controle:
                sortie.append(f"{f.name} (ligne {f.lineno})")
    return sortie


@pytest.mark.parametrize("module", modules(), ids=lambda p: p.name)
def test_telechargement_controle(module: Path):
    mauvais = fautifs(module.read_text(encoding="utf-8"))
    assert not mauvais, (f"pipeline/{module.name} ecrit un fichier telecharge sans controle d'integrite : "
                         f"{', '.join(mauvais)}. Ecrire dans un temporaire puis "
                         "fetch.remplacer_si_valide(tmp, dest, octets_attendus=fetch.octets_annonces(r)) "
                         "(ou fetch.get(..., controle=\"pdf\"|\"csv\"|...)).")


def test_analyse_detecte_un_oubli():
    oubli = ("import requests\n"
             "def telecharger(url, dest):\n"
             "    r = requests.get(url)\n"
             "    tmp = dest.with_suffix('.part')\n"
             "    tmp.write_bytes(r.content)\n"
             "    tmp.replace(dest)\n")
    assert fautifs(oubli) == ["telecharger (ligne 2)"]
    flux = ("def telecharger(url, dest):\n"
            "    with requests.get(url, stream=True) as r, open(dest, 'wb') as f:\n"
            "        for b in r.iter_content(1 << 20):\n"
            "            f.write(b)\n")
    assert fautifs(flux) == ["telecharger (ligne 1)"]
    corrige = oubli.replace("    tmp.replace(dest)\n", "    fetch.remplacer_si_valide(tmp, dest)\n")
    assert fautifs(corrige) == []
    lecture_seule = ("def sonder(u):\n"
                     "    r = requests.get(u, stream=True)\n"
                     "    return next(r.iter_content(8), b'')\n")
    assert fautifs(lecture_seule) == []


# --- remplacer_si_valide : temporaire controle, renommage atomique, version valide conservee -----------------------

PDF_COMPLET = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_pdf_tronque_ne_remplace_pas_la_version_presente(tmp_path):
    import fetch
    dest = tmp_path / "lfss.pdf"
    dest.write_bytes(PDF_COMPLET)
    tmp = tmp_path / "lfss.pdf.part"
    tmp.write_bytes(PDF_COMPLET[:30])            # transfert coupe : pas de %%EOF
    with pytest.raises(RuntimeError, match="EOF"):
        fetch.remplacer_si_valide(tmp, dest)
    assert dest.read_bytes() == PDF_COMPLET and not tmp.exists()


def test_page_html_et_taille_annoncee(tmp_path):
    import fetch
    dest = tmp_path / "donnees.csv"
    tmp = tmp_path / "donnees.csv.part"
    tmp.write_bytes(b"<!DOCTYPE html><html><body>Request Rejected</body></html>")
    with pytest.raises(RuntimeError, match="HTML"):
        fetch.remplacer_si_valide(tmp, dest)
    assert not dest.exists() and not tmp.exists()
    tmp.write_bytes(b"a;b\n1;2\n")
    with pytest.raises(RuntimeError, match="tronque"):
        fetch.remplacer_si_valide(tmp, dest, octets_attendus=100)
    assert not dest.exists()


def test_fichier_valide_remplace_atomiquement(tmp_path):
    import fetch
    dest = tmp_path / "lfss.pdf"
    dest.write_bytes(b"%PDF-1.4\nancien\n%%EOF\n")
    tmp = tmp_path / "lfss.pdf.part"
    tmp.write_bytes(PDF_COMPLET)
    fetch.remplacer_si_valide(tmp, dest, octets_attendus=len(PDF_COMPLET))
    assert dest.read_bytes() == PDF_COMPLET and not tmp.exists()


def test_octets_annonces():
    import fetch

    class R:
        def __init__(self, h):
            self.headers = h
    assert fetch.octets_annonces(R({"Content-Length": "42"})) == 42
    assert fetch.octets_annonces(R({"Content-Length": "42", "Content-Encoding": "gzip"})) is None
    assert fetch.octets_annonces(R({})) is None
