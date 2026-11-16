"""Conversion des fichiers tabulaires de l'entrepot brut en Parquet zstd (DuckDB).

Regle : un fichier tabulaire (CSV, TSV, JSON tabulaire, NDJSON, XLS, XLSX, contenu tabulaire d'un ZIP)
est stocke en Parquet zstd et l'original n'est pas garde. Tout le reste (PDF, XML DILA, tar.gz, 7z,
Parquet deja present...) est garde tel quel. Si une conversion echoue, l'original est garde et la
raison est notee.

Fidelite : les colonnes sont lues en texte (all_varchar) pour ne rien perdre (codes INSEE, SIREN
ou departements a zero initial, montants au format francais...). Les types se posent a la lecture
(CAST dans DuckDB), pas a l'archivage. Les cellules vides deviennent NULL.

Le format est detecte sur le contenu (octets magiques), pas sur l'extension : l'entrepot contient
des noms comme `.www_downlo` ou `.csv_utf8`.

Usage :
  python collecte/conversion.py fichier [fichier...]            # convertit a cote, affiche le gain
  python collecte/conversion.py --mesure --dest /tmp/x id1 id2  # mesure sur des sources du manifeste
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

FORMATS_TABULAIRES = {"csv", "json", "ndjson", "xlsx", "xls", "zip"}
MAX_MEMBRES_ZIP = 5000


@dataclass
class Sortie:
    chemin: Path          # fichier produit (ou original garde)
    nom: str              # nom relatif dans l'objet stocke (ex. "a.csv.parquet", "archive.zip/x.parquet")
    octets: int
    lignes: int | None = None
    converti: bool = True


@dataclass
class Resultat:
    source: Path
    format: str
    octets_avant: int
    sorties: list[Sortie] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)
    garde_original: bool = False

    @property
    def octets_apres(self) -> int:
        return sum(s.octets for s in self.sorties)

    @property
    def converti(self) -> bool:
        return any(s.converti for s in self.sorties)

    def resume(self) -> dict:
        d = {"format": self.format, "converti": self.converti, "octets_avant": self.octets_avant,
             "octets_apres": self.octets_apres}
        if self.erreurs:
            d["conversion_erreurs"] = [e[:300] for e in self.erreurs[:10]]
        return d


# ---------------------------------------------------------------- detection

def detecter(chemin: Path) -> str:
    """Format d'apres le contenu : csv, json, ndjson, xlsx, xls, zip, parquet, pdf, xml, gzip, 7z,
    ods, docx, ole (doc...), html, autre."""
    with chemin.open("rb") as f:
        tete = f.read(65536)
    if not tete:
        return "vide"
    if tete.startswith(b"PK\x03\x04") or tete.startswith(b"PK\x05\x06"):
        try:
            with zipfile.ZipFile(chemin) as z:
                noms = z.namelist()
        except zipfile.BadZipFile:
            return "autre"
        if "[Content_Types].xml" in noms and any(n.startswith("xl/") for n in noms):
            return "xlsx"
        if "[Content_Types].xml" in noms:
            return "docx"  # docx, pptx : documents bureautiques, gardes tels quels
        if "mimetype" in noms:
            return "ods"
        return "zip"
    if tete.startswith(b"\xd0\xcf\x11\xe0"):
        return "xls" if (b"W\x00o\x00r\x00k\x00b\x00o\x00o\x00k" in tete or b"Workbook" in tete
                         or chemin.suffix.lower() == ".xls") else "ole"
    if tete.startswith(b"%PDF"):
        return "pdf"
    if tete.startswith(b"PAR1"):
        return "parquet"
    if tete.startswith(b"\x1f\x8b"):
        return "gzip"
    if tete.startswith(b"7z\xbc\xaf"):
        return "7z"
    texte = tete.lstrip(b"\xef\xbb\xbf \t\r\n")
    if texte.startswith(b"<"):
        debut = texte[:512].lower()
        return "html" if (b"<html" in debut or b"<!doctype html" in debut) else "xml"
    if texte.startswith(b"["):
        return "json"
    if texte.startswith(b"{"):
        # NDJSON : la premiere ligne est un objet complet
        ligne = texte.split(b"\n", 1)[0].strip()
        try:
            json.loads(ligne)
            return "ndjson" if b"\n" in texte.strip() else "json_objet"
        except ValueError:
            return "json_objet"  # objet unique (JSON-stat, enveloppe d'API...) : pas tabulaire
    if b"\x00" in tete[:4096]:
        return "autre"
    premiere = texte.split(b"\n", 1)[0]
    if any(premiere.count(s) >= 1 for s in (b";", b",", b"\t", b"|")):
        return "csv"
    return "texte"


# ---------------------------------------------------------------- duckdb

def connexion(memoire: str | None = None, threads: int | None = None, temp: Path | None = None):
    """Connexion DuckDB bridee (le VPS est partage) : memoire et coeurs limites, debordement sur disque."""
    import duckdb
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    con.execute(f"SET memory_limit = '{memoire or os.environ.get('OVMI_DUCKDB_MEMOIRE', '1GB')}'")
    con.execute(f"SET threads = {int(threads or os.environ.get('OVMI_DUCKDB_THREADS', '2'))}")
    if temp:
        temp.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory = '{_sql(str(temp))}'")
    return con


def _sql(s: str) -> str:
    return s.replace("'", "''")


def _copier(con, select: str, cible: Path) -> int:
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_name(cible.name + ".tmp")
    con.execute(f"COPY ({select}) TO '{_sql(str(tmp))}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL "
                f"{int(os.environ.get('OVMI_ZSTD_NIVEAU', '9'))})")
    os.replace(tmp, cible)
    return con.execute(f"SELECT count(*) FROM read_parquet('{_sql(str(cible))}')").fetchone()[0]


def _vers_utf8(src: Path, cible: Path) -> str:
    """Transcode en UTF-8 un texte Windows-1252 (ou, a defaut, Latin-1 qui accepte tout octet)."""
    for enc in ("cp1252", "latin-1"):
        try:
            with src.open("r", encoding=enc, newline="") as fi, cible.open("w", encoding="utf-8", newline="") as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
            return enc
        except UnicodeDecodeError:
            continue
    raise RuntimeError("encodage inconnu")


def _option(v) -> str | None:
    return None if v in (None, "", "(empty)") else v


def convertir_csv(con, src: Path, cible: Path) -> int:
    """CSV/TSV : dialecte detecte par le sniffer DuckDB, colonnes en texte, lecture stricte
    (une ligne mal formee fait echouer la conversion : l'original est alors garde). Aucune ligne
    n'est sautee : un preambule (titre au-dessus du tableau) est garde comme lignes de donnees.
    Fichier non UTF-8 : transcodage temporaire (Windows-1252 puis Latin-1)."""
    lu, transcode = src, None
    try:
        try:
            _utf8_strict(src)
        except UnicodeDecodeError:
            transcode = cible.with_name(cible.name + ".utf8.csv")
            _vers_utf8(src, transcode)
            lu = transcode
        s = con.execute(f"SELECT Delimiter, Quote, Escape, HasHeader, SkipRows, len(Columns) FROM "
                        f"sniff_csv('{_sql(str(lu))}', sample_size=20480)").fetchone()
        delim, quote, escape, entete, saut, ncol = s
        if ncol == 1:
            with lu.open("rb") as fh:
                premiere = fh.readline()
            if any(sep in premiere for sep in (b";", b",", b"\t", b"|")):
                raise RuntimeError("dialecte ambigu (lignes de largeurs differentes ?)")
        opts = [f"delim='{_sql(delim)}'", "all_varchar=true", "skip=0", "comment=''", "strict_mode=true",
                "max_line_size=20000000"]
        if saut:
            opts += ["header=false", "null_padding=true"]
        else:
            opts.append(f"header={'true' if entete else 'false'}")
        opts.append(f"quote='{_sql(_option(quote) or '')}'")
        if _option(escape):
            opts.append(f"escape='{_sql(escape)}'")
        return _copier(con, f"SELECT * FROM read_csv('{_sql(str(lu))}', {', '.join(opts)})", cible)
    finally:
        if transcode:
            transcode.unlink(missing_ok=True)


def _utf8_strict(src: Path):
    """Leve UnicodeDecodeError si le fichier n'est pas de l'UTF-8 valide (lecture par blocs)."""
    import codecs
    dec = codecs.getincrementaldecoder("utf-8")("strict")
    with src.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 22), b""):
            dec.decode(bloc)
        dec.decode(b"", final=True)


def convertir_json(con, src: Path, cible: Path, fmt: str) -> int:
    """JSON tabulaire seulement : tableau d'objets ou NDJSON (un objet unique n'est pas tabulaire et
    reste tel quel). Colonnes inferees par DuckDB ; si le schema ne s'unifie pas, repli fidele :
    une ligne par enregistrement dans une colonne `json` (texte JSON d'origine, requetable avec
    json_extract)."""
    forme = "array" if fmt == "json" else "newline_delimited"
    taille = 32 * 2**20
    try:
        return _copier(con, f"SELECT * FROM read_json('{_sql(str(src))}', format='{forme}', records=true, "
                            f"maximum_object_size={taille})", cible)
    except Exception:
        return _copier(con, f"SELECT json FROM read_json_objects('{_sql(str(src))}', format='{forme}', "
                            f"maximum_object_size={taille})", cible)


def _feuilles_vers_parquet(feuilles, cible_base: Path, nom_base: str) -> list[Sortie]:
    """feuilles : iterable de (nom_feuille, largeur, iterable de lignes). Chaque feuille non vide ->
    un Parquet ecrit par lots (memoire bornee), toutes les cellules en texte, sans en-tete interprete
    (colonnes c0, c1, ... : les lignes de titre des tableurs restent des lignes)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    sorties = []
    for nom_feuille, largeur, lignes in feuilles:
        if not largeur:
            continue
        suffixe = re.sub(r"[^\w.-]+", "_", nom_feuille).strip("_") or "feuille"
        cible = cible_base.with_name(f"{cible_base.name}.{suffixe}.parquet")
        tmp = cible.with_name(cible.name + ".tmp")
        schema = pa.schema([(f"c{i}", pa.string()) for i in range(largeur)])
        writer, n, utiles, lot = None, 0, 0, []

        def vider():
            nonlocal writer, lot
            cols = [[r[i] if i < len(r) else None for r in lot] for i in range(largeur)]
            if writer is None:
                writer = pq.ParquetWriter(tmp, schema, compression="zstd", compression_level=9)
            writer.write_table(pa.Table.from_arrays([pa.array(c, pa.string()) for c in cols], schema=schema))
            lot = []

        try:
            for ligne in lignes:
                valeurs = [None if v is None or v == "" else str(v) for v in ligne][:largeur]
                lot.append(valeurs)
                n += 1
                if any(v is not None for v in valeurs):
                    utiles = n
                if len(lot) >= 20000:
                    vider()
            if utiles == 0:
                if writer:
                    writer.close()
                tmp.unlink(missing_ok=True)
                continue
            if lot:
                vider()
            writer.close()
        except Exception:
            if writer:
                writer.close()
            tmp.unlink(missing_ok=True)
            raise
        os.replace(tmp, cible)
        sorties.append(Sortie(cible, f"{nom_base}.{suffixe}.parquet", cible.stat().st_size, n))
    return sorties


def convertir_xlsx(con, src: Path, cible_base: Path, nom_base: str) -> list[Sortie]:
    import openpyxl
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    try:
        def largeur(ws) -> int:
            # les dimensions declarees d'un xlsx sont souvent fausses : premiere passe de mesure
            n = 0
            for ligne in ws.iter_rows(values_only=True):
                for i in range(len(ligne) - 1, n - 1, -1):
                    if ligne[i] is not None and ligne[i] != "":
                        n = i + 1
                        break
            return n
        return _feuilles_vers_parquet(((ws.title, largeur(ws), ws.iter_rows(values_only=True))
                                       for ws in wb.worksheets), cible_base, nom_base)
    finally:
        wb.close()


def convertir_xls(con, src: Path, cible_base: Path, nom_base: str) -> list[Sortie]:
    import xlrd  # optionnel (deploy/requirements-vps.txt) : sans lui, le .xls est garde tel quel
    wb = xlrd.open_workbook(str(src), on_demand=True)
    try:
        def lignes(sh):
            for i in range(sh.nrows):
                yield sh.row_values(i)
        return _feuilles_vers_parquet(((sh.name, sh.ncols, lignes(sh)) for sh in wb.sheets()), cible_base, nom_base)
    finally:
        wb.release_resources()


# ---------------------------------------------------------------- point d'entree

def _convertir_simple(con, src: Path, fmt: str, dest: Path, nom: str) -> list[Sortie]:
    """Un fichier deja detecte comme tabulaire (hors zip) -> sorties Parquet dans dest."""
    if fmt == "csv":
        cible = dest / f"{nom}.parquet"
        return [Sortie(cible, f"{nom}.parquet", 0, convertir_csv(con, src, cible))]
    if fmt in ("json", "ndjson"):
        cible = dest / f"{nom}.parquet"
        return [Sortie(cible, f"{nom}.parquet", 0, convertir_json(con, src, cible, fmt))]
    if fmt == "xlsx":
        return convertir_xlsx(con, src, dest / nom, nom)
    if fmt == "xls":
        return convertir_xls(con, src, dest / nom, nom)
    raise ValueError(f"format non tabulaire : {fmt}")


def _taille(sorties: list[Sortie]) -> list[Sortie]:
    for s in sorties:
        s.octets = s.chemin.stat().st_size
    return sorties


def convertir(src: Path, dest: Path | None = None, con=None) -> Resultat:
    """Convertit `src` si tabulaire. Les Parquet sont ecrits dans `dest` (defaut : a cote de src).
    Ne supprime jamais `src` : c'est a l'appelant (stockage.py) de le faire une fois l'envoi verifie.
    Si res.garde_original, l'original fait partie des sorties (converti=False)."""
    src = Path(src)
    dest = Path(dest) if dest else src.parent
    dest.mkdir(parents=True, exist_ok=True)
    fmt = detecter(src)
    res = Resultat(src, fmt, src.stat().st_size)
    if fmt not in FORMATS_TABULAIRES:
        res.garde_original = True
        res.sorties = [Sortie(src, src.name, res.octets_avant, converti=False)]
        return res
    propre = con is None
    con = con or connexion(temp=dest / ".duckdb_tmp")
    try:
        if fmt == "zip":
            _convertir_zip(con, src, dest, res)
        else:
            try:
                res.sorties = _taille(_convertir_simple(con, src, fmt, dest, src.name))
                if not res.sorties:
                    raise RuntimeError("aucune donnee tabulaire")
            except Exception as exc:
                _nettoyer(res.sorties)
                res.erreurs.append(f"{fmt} : {exc}")
                res.garde_original = True
                res.sorties = [Sortie(src, src.name, res.octets_avant, converti=False)]
    finally:
        if propre:
            con.close()
            shutil.rmtree(dest / ".duckdb_tmp", ignore_errors=True)
    return res


def _nettoyer(sorties: list[Sortie]):
    for s in sorties:
        if s.converti:
            s.chemin.unlink(missing_ok=True)


def _convertir_zip(con, src: Path, dest: Path, res: Resultat):
    """Archive : chaque membre tabulaire -> Parquet ; les autres membres (et ceux dont la conversion
    echoue) sont regroupes dans une archive `_reste.zip` (rien n'est perdu). L'archive d'origine est
    gardee entiere si elle est illisible, sans membre tabulaire, trop grosse pour le disque, ou si
    le resultat n'est pas plus petit."""
    racine = dest / (src.name + ".d")
    gardes: list[tuple[Path, str]] = []
    try:
        with zipfile.ZipFile(src) as z:
            membres = [i for i in z.infolist() if not i.is_dir()]
            if not membres or len(membres) > MAX_MEMBRES_ZIP:
                raise RuntimeError(f"{len(membres)} membres")
            if sum(i.file_size for i in membres) > shutil.disk_usage(dest).free * 0.5:
                raise RuntimeError("contenu decompresse trop gros pour le disque libre")
            for info in membres:
                rel = _rel_sur(info.filename)
                brut = racine / "_brut" / rel
                brut.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as fi, brut.open("wb") as fo:
                    shutil.copyfileobj(fi, fo, 1 << 20)
                fmt = detecter(brut)
                if fmt in FORMATS_TABULAIRES - {"zip"}:
                    try:
                        sorties = _convertir_simple(con, brut, fmt, (racine / rel).parent, Path(rel).name)
                        if not sorties:
                            raise RuntimeError("aucune donnee tabulaire")
                        for s in _taille(sorties):
                            parent = Path(rel).parent
                            s.nom = f"{src.name}/{s.nom}" if str(parent) == "." else f"{src.name}/{parent}/{s.nom}"
                            res.sorties.append(s)
                        brut.unlink()
                        continue
                    except Exception as exc:
                        res.erreurs.append(f"{rel} ({fmt}) : {exc}")
                gardes.append((brut, rel))
        if not any(s.converti for s in res.sorties):
            raise RuntimeError("aucun membre tabulaire")
        if gardes:
            reste = racine / "_reste.zip"
            with zipfile.ZipFile(reste, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zo:
                for brut, rel in gardes:
                    zo.write(brut, rel)
            res.sorties.append(Sortie(reste, f"{src.name}/_reste.zip", reste.stat().st_size, converti=False))
        shutil.rmtree(racine / "_brut", ignore_errors=True)
        if res.octets_apres >= res.octets_avant:
            raise RuntimeError("pas de gain")
    except Exception as exc:
        shutil.rmtree(racine, ignore_errors=True)
        if not str(exc).startswith(("aucun membre tabulaire", "pas de gain")):
            res.erreurs.append(f"zip : {exc}")
        res.garde_original = True
        res.sorties = [Sortie(src, src.name, res.octets_avant, converti=False)]


def _rel_sur(nom: str) -> str:
    """Chemin de membre sans remontee (../) ni chemin absolu."""
    parties = [re.sub(r"[^\w.\- ]+", "_", p) for p in nom.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return "/".join(parties) or "membre"


def nettoyer_resultat(res: Resultat):
    """Supprime les produits de conversion (pas l'original)."""
    _nettoyer(res.sorties)
    for s in res.sorties:
        if not s.converti and s.chemin != res.source:
            s.chemin.unlink(missing_ok=True)
    shutil.rmtree(res.source.parent / (res.source.name + ".d"), ignore_errors=True)


# ---------------------------------------------------------------- mesure

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cibles", nargs="+", help="fichiers, ou identifiants de sources avec --mesure")
    ap.add_argument("--mesure", action="store_true", help="les cibles sont des sources du manifeste")
    ap.add_argument("--dest", type=Path, help="dossier des Parquet produits (defaut : a cote)")
    a = ap.parse_args(argv)
    fichiers = []
    if a.mesure:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import collecte as C
        m = C.lire_manifeste()
        for sid in a.cibles:
            for f in m[sid].get("fichiers", []):
                p = C.ROOT / f["chemin"]
                if p.exists():
                    fichiers.append((sid, p))
    else:
        fichiers = [(None, Path(c)) for c in a.cibles]
    tot_av = tot_ap = 0
    lignes = []
    con = connexion(temp=(a.dest or Path("/tmp")) / ".duckdb_tmp")
    for sid, p in fichiers:
        d = (a.dest / (sid or "") / p.parent.name) if a.dest else None
        res = convertir(p, d, con=con)
        tot_av += res.octets_avant
        tot_ap += res.octets_apres
        lignes.append({"source": sid, "fichier": p.name, **res.resume()})
        print(f"{res.format:<8} {'conv' if res.converti else 'garde':<5} {res.octets_avant / 1e6:9.2f} Mo -> "
              f"{res.octets_apres / 1e6:9.2f} Mo  {sid or ''} {p.name[:60]} {'; '.join(res.erreurs)[:120]}", flush=True)
        if a.dest:
            nettoyer_resultat(res)
    if tot_av:
        print(f"\nTOTAL {tot_av / 1e6:.1f} Mo -> {tot_ap / 1e6:.1f} Mo ({100 * (1 - tot_ap / tot_av):.0f} % de gain)")
    if a.dest:
        (a.dest / "mesure.json").write_text(json.dumps(lignes, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
