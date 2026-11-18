"""Controle d'integrite des fichiers telecharges (sans dependance hors bibliotheque standard).

Un fichier n'est accepte que s'il est complet : taille egale a Content-Length quand le serveur
l'annonce, et format coherent avec son extension :
  - PDF : en-tete %PDF- au debut, marqueur %%EOF dans la fin du fichier ;
  - ZIP et formats bureautiques en ZIP (xlsx, xlsm, docx, ods, odt, pptx) : archive lisible
    (repertoire central present, sommes CRC verifiees jusqu'a 512 Mo) ;
  - JSON / GeoJSON : analysable (jusqu'a 256 Mo ; au-dela, ouverture et fermeture coherentes) ;
    NDJSON / JSONL : derniere ligne analysable ;
  - CSV / TSV : derniere ligne complete (terminee par un saut de ligne, ou sinon meme nombre de
    champs que l'en-tete) ;
  - Parquet : marqueur PAR1 au debut et a la fin ; gzip : flux complet ; xls/doc (OLE) : taille
    alignee sur les secteurs ;
  - toute extension de donnees : refus d'une page HTML recue a la place du fichier.

Utilisable par tout module de collecte :
    from integrite import IntegriteInvalide, verifier_fichier, verifier_octets
    verifier_fichier(Path("x.pdf.part"), nom="x.pdf", octets_attendus=123)   # leve IntegriteInvalide
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import zipfile
from pathlib import Path
from typing import BinaryIO

FORMATS_ZIP = {".zip", ".xlsx", ".xlsm", ".docx", ".pptx", ".ods", ".odt", ".odp"}
FORMATS_JSON = {".json", ".geojson"}
FORMATS_NDJSON = {".ndjson", ".jsonl"}
FORMATS_CSV = {".csv", ".tsv"}
FORMATS_OLE = {".xls", ".doc", ".ppt"}
# extensions pour lesquelles une page HTML recue est forcement une erreur (refus, page d'attente...)
FORMATS_DONNEES = ({".pdf", ".parquet", ".gz", ".txt", ".bin"} | FORMATS_ZIP | FORMATS_JSON | FORMATS_NDJSON
                   | FORMATS_CSV | FORMATS_OLE)
SEUIL_JSON_COMPLET = 256 * 10**6
SEUIL_ZIP_CRC = 512 * 10**6
SEUIL_GZIP = 512 * 10**6
QUEUE = 64 * 1024


class IntegriteInvalide(RuntimeError):
    """Le fichier recu est incomplet ou ne correspond pas au format annonce."""


def extension(nom: str | Path) -> str:
    return Path(str(nom).split("?")[0]).suffix.lower()


def _queue(f: BinaryIO, taille: int, n: int = QUEUE) -> bytes:
    f.seek(max(0, taille - n))
    return f.read(n)


def _tete(f: BinaryIO, n: int = QUEUE) -> bytes:
    f.seek(0)
    return f.read(n)


def _est_html(tete: bytes) -> bool:
    debut = tete.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return debut.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))


def _pdf(f, taille):
    if b"%PDF-" not in _tete(f, 1024):
        raise IntegriteInvalide("PDF sans en-tete %PDF- (page d'erreur ou fichier d'un autre type)")
    if b"%%EOF" not in _queue(f, taille, 4096):
        raise IntegriteInvalide("PDF sans marqueur %%EOF final (fichier tronque)")


def _zip(f, taille):
    try:
        with zipfile.ZipFile(f) as z:
            membres = z.infolist()
            if not membres:
                raise IntegriteInvalide("archive ZIP vide")
            if taille <= SEUIL_ZIP_CRC:
                mauvais = z.testzip()
                if mauvais:
                    raise IntegriteInvalide(f"archive ZIP corrompue (CRC faux sur {mauvais})")
            else:  # gros fichier : on lit au moins le dernier membre, le plus expose a une troncature
                with z.open(membres[-1]) as m:
                    while m.read(1 << 20):
                        pass
    except (zipfile.BadZipFile, EOFError, OSError, ValueError) as exc:
        raise IntegriteInvalide(f"archive ZIP illisible (tronquee ?) : {exc}") from exc


def _texte(octets: bytes) -> str:
    if octets[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return octets.decode("utf-16", errors="replace")
    return octets.decode("utf-8-sig", errors="replace")


def _json(f, taille):
    if taille <= SEUIL_JSON_COMPLET:
        f.seek(0)
        try:
            json.loads(_texte(f.read()))
        except ValueError as exc:
            raise IntegriteInvalide(f"JSON non analysable (tronque ?) : {exc}"[:300]) from exc
        return
    debut = _texte(_tete(f, 4096)).lstrip()[:1]
    fin = _texte(_queue(f, taille, 4096)).rstrip()[-1:]
    if (debut, fin) not in (("{", "}"), ("[", "]")):
        raise IntegriteInvalide(f"JSON mal ferme (debut {debut!r}, fin {fin!r}) : fichier tronque")


def _ndjson(f, taille):
    lignes = [l for l in _texte(_queue(f, taille)).splitlines() if l.strip()]
    if not lignes:
        return
    try:
        json.loads(lignes[-1])
    except ValueError as exc:
        raise IntegriteInvalide(f"derniere ligne NDJSON incomplete : {exc}"[:300]) from exc


def _csv(f, taille):
    tete = _tete(f)
    if tete[:2] in (b"\xff\xfe", b"\xfe\xff"):  # UTF-16 : on decode le tout (alignement incertain en queue)
        if taille > SEUIL_JSON_COMPLET:
            return
        f.seek(0)
        texte_tete = texte_queue = _texte(f.read())
    else:
        texte_tete = tete.decode("utf-8-sig", errors="replace")
        texte_queue = _queue(f, taille).decode("utf-8", errors="replace")
    if texte_queue.endswith(("\n", "\r")):
        return
    lignes = texte_tete.splitlines()
    if not lignes or (taille <= len(tete) and len(lignes) == 1):
        return  # fichier d'une seule ligne
    entete, derniere = lignes[0], texte_queue.splitlines()[-1]
    sep = max([";", ",", "\t", "|"], key=entete.count)
    n_entete = len(next(csv.reader([entete], delimiter=sep)))
    if derniere.count('"') % 2:
        raise IntegriteInvalide("CSV : derniere ligne coupee au milieu d'un champ entre guillemets")
    n_derniere = len(next(csv.reader([derniere], delimiter=sep)))
    if n_derniere != n_entete:
        raise IntegriteInvalide(f"CSV : derniere ligne incomplete ({n_derniere} champs sur {n_entete})")


def _parquet(f, taille):
    if taille < 12 or _tete(f, 4) != b"PAR1" or _queue(f, taille, 4) != b"PAR1":
        raise IntegriteInvalide("parquet incomplet (marqueur PAR1 final absent)")


def _gzip(f, taille):
    if _tete(f, 2) != b"\x1f\x8b":
        raise IntegriteInvalide("fichier .gz sans signature gzip")
    if taille > SEUIL_GZIP:
        return
    f.seek(0)
    try:
        with gzip.GzipFile(fileobj=f) as g:
            while g.read(1 << 20):
                pass
    except (EOFError, OSError, zipfile.BadZipFile) as exc:
        raise IntegriteInvalide(f"flux gzip incomplet : {exc}") from exc


def _ole(f, taille):
    tete = _tete(f, 512)
    if tete[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        if tete[:2] == b"PK":   # xlsx servi avec une extension .xls : on le controle comme une archive
            return _zip(f, taille)
        if _est_html(tete):
            raise IntegriteInvalide("page HTML recue a la place du fichier")
        return  # .xls en HTML/XML exporte par certains portails : pas de controle structurel
    secteur = 1 << int.from_bytes(tete[30:32], "little")
    if secteur in (512, 4096) and (taille - 512) % secteur:
        raise IntegriteInvalide(f"fichier OLE (xls/doc) tronque : taille non alignee sur {secteur} octets")


CONTROLES = {".pdf": _pdf, ".parquet": _parquet, ".gz": _gzip,
             **{e: _zip for e in FORMATS_ZIP}, **{e: _json for e in FORMATS_JSON},
             **{e: _ndjson for e in FORMATS_NDJSON}, **{e: _csv for e in FORMATS_CSV},
             **{e: _ole for e in FORMATS_OLE}}


def verifier_flux(f: BinaryIO, taille: int, nom: str | Path, octets_attendus: int | None = None) -> None:
    """Controle un fichier deja ouvert en binaire (positionnable). Leve IntegriteInvalide."""
    if octets_attendus is not None and taille != int(octets_attendus):
        raise IntegriteInvalide(f"taille {taille} octets au lieu de {octets_attendus} annonces (transfert tronque)")
    if taille == 0:
        raise IntegriteInvalide("fichier vide")
    ext = extension(nom)
    if ext in FORMATS_DONNEES and ext not in FORMATS_OLE and _est_html(_tete(f, 512)):
        raise IntegriteInvalide("page HTML recue a la place du fichier (refus, erreur ou page d'attente)")
    controle = _par_signature(_tete(f, 1024)) or CONTROLES.get(ext)
    if controle:
        controle(f, taille)


def _par_signature(tete: bytes):
    """Le contenu prime sur l'extension (une ressource annoncee csv peut etre servie zippee)."""
    if tete.startswith(b"PK\x03\x04"):
        return _zip
    if tete.startswith(b"%PDF-"):
        return _pdf
    if tete.startswith(b"PAR1"):
        return _parquet
    if tete.startswith(b"\x1f\x8b"):
        return _gzip
    if tete.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return _ole
    return None


def verifier_fichier(chemin: Path, *, nom: str | Path | None = None, octets_attendus: int | None = None) -> None:
    """Controle le fichier `chemin` ; `nom` donne l'extension quand chemin est un temporaire (.part)."""
    chemin = Path(chemin)
    with chemin.open("rb") as f:
        verifier_flux(f, chemin.stat().st_size, nom or chemin.name, octets_attendus)


def verifier_octets(contenu: bytes, nom: str | Path, octets_attendus: int | None = None) -> None:
    """Controle un contenu deja en memoire (reponse non diffusee en flux)."""
    verifier_flux(io.BytesIO(contenu), len(contenu), nom, octets_attendus)


def est_valide(chemin: Path, nom: str | Path | None = None) -> bool:
    try:
        verifier_fichier(chemin, nom=nom)
        return True
    except (IntegriteInvalide, OSError):
        return False
