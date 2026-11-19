"""Liste de prénoms du filtre des noms de personnes : versionnée, autonome, reproductible (pipeline/prenoms_ref.py).

Sans elle, une machine neuve (mise à jour hebdomadaire) filtrait avec 17 prénoms et pouvait publier des noms.
"""
from __future__ import annotations

import csv
import inspect
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import associations  # noqa: E402
import fonds_europeens  # noqa: E402
import local  # noqa: E402
import prenoms_ref  # noqa: E402

MINIMUM = 3000  # « quelques milliers » : en dessous, le filtre ne protège plus


def _recharger(monkeypatch):
    monkeypatch.setattr(local, "_PRENOMS", None)
    associations.prenoms.cache_clear()


@pytest.mark.parametrize("nom", ["FICHIER_PRENOMS", "FICHIER_PRENOMS_SIRENE"])
def test_fichier_versionne_dans_le_depot(nom):
    f = getattr(local, nom)
    assert f.resolve().is_relative_to(ROOT.resolve()), "la liste doit être dans le dépôt"
    assert "data/lake" not in f.as_posix() and "_cache" not in f.as_posix()
    suivi = subprocess.run(["git", "ls-files", "--error-unmatch", str(f.relative_to(ROOT))], cwd=ROOT,
                           capture_output=True, text=True)
    if suivi.returncode not in (0, 1) or "not a git repository" in suivi.stderr:
        pytest.skip("pas de dépôt git")
    assert suivi.returncode == 0, f"{f.relative_to(ROOT)} n'est pas versionné"
    assert f.stat().st_size < 200_000, "fichier compact attendu"


def test_liste_chargee_compte_quelques_milliers_de_prenoms(monkeypatch):
    _recharger(monkeypatch)
    p = local.prenoms()
    assert len(p) >= MINIMUM, f"{len(p)} prénoms chargés seulement"
    assert len(associations.prenoms()) == len(p)
    for x in ("JEAN", "MARIE", "MOHAMED", "NATHALIE", "KEVIN", "FATIMA", "LUCAS", "EMMA"):
        assert x in p, x
    assert not (p & local.NON_PRENOMS) and not (p & local.MOTS_OUTILS)


def test_filtre_sans_aucun_fichier_hors_depot(monkeypatch, tmp_path):
    """Caches et stock SIRENE absents (machine neuve) : la même liste complète est chargée."""
    _recharger(monkeypatch)
    attendu = set(local.prenoms())
    _recharger(monkeypatch)
    vide = tmp_path / "lac_vide"
    monkeypatch.setattr(local, "LAKE", vide)
    monkeypatch.setattr(local, "CACHE", vide / "_cache" / "local")
    monkeypatch.setattr(associations, "CACHE", vide / "_cache" / "associations")
    monkeypatch.setattr(associations, "STOCK_SIRENE", vide / "absent.parquet")
    assert local.prenoms() == attendu and len(attendu) >= MINIMUM
    assert set(associations.prenoms()) == attendu
    for fn in (local.prenoms, associations.prenoms, local.lire_liste_prenoms):
        src = inspect.getsource(fn)
        for interdit in ("CACHE", "LAKE", "parquet", "STOCK_SIRENE", "duckdb", "PRENOMS_MINIMAUX", "lire_cache"):
            assert interdit not in src, f"{fn.__qualname__} dépend encore de {interdit}"


@pytest.mark.parametrize("nom", ["FICHIER_PRENOMS", "FICHIER_PRENOMS_SIRENE"])
def test_fichier_absent_erreur_sans_repli(monkeypatch, tmp_path, nom):
    _recharger(monkeypatch)
    monkeypatch.setattr(local, nom, tmp_path / "absent.txt")
    with pytest.raises(RuntimeError, match="aucun repli"):
        local.prenoms()
    with pytest.raises(RuntimeError, match="aucun repli"):
        local.lire_liste_prenoms(tmp_path / "absent.txt")
    (tmp_path / "vide.txt").write_text("# en-tête seul\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="aucun repli"):
        local.lire_liste_prenoms(tmp_path / "vide.txt")


def test_entete_documente_source_licence_et_seuil():
    lignes = local.FICHIER_PRENOMS.read_text(encoding="utf-8").splitlines()
    entete = "\n".join(l for l in lignes if l.startswith("#"))
    corps = [l for l in lignes if not l.startswith("#")]
    assert prenoms_ref.SOURCE["url"] in entete and prenoms_ref.SOURCE["page"] in entete
    assert "Licence Ouverte" in entete and "Insee" in entete
    assert f"au moins {prenoms_ref.SEUIL} fois" in entete
    assert f"# Nombre : {len(corps)}" in lignes
    assert corps == sorted(set(corps)), "liste triée, sans doublon"
    assert all(l.isalpha() and l.isupper() and l.isascii() and len(l) >= 3 for l in corps)


def test_complement_sirene_documente_et_charge():
    lignes = local.FICHIER_PRENOMS_SIRENE.read_text(encoding="utf-8").splitlines()
    entete = "\n".join(l for l in lignes if l.startswith("#"))
    corps = [l for l in lignes if not l.startswith("#")]
    assert "SIRENE" in entete and "Licence Ouverte" in entete and f"au moins {prenoms_ref.SEUIL_SIRENE}" in entete
    assert f"# Nombre : {len(corps)}" in lignes and len(corps) >= 1000
    assert corps == sorted(set(corps))
    p = local.prenoms()
    # prénoms d'adultes nés hors de France, rares dans l'état civil : couverts par le complément
    for x in ("IRYNA", "KRZYSZTOF", "ABDELMAJID"):
        assert x in corps and x in p, x


def _zip_insee(lignes: list[tuple[str, str, str, str]]) -> bytes:
    t = io.StringIO()
    w = csv.writer(t, delimiter=";", lineterminator="\n")
    w.writerow(["sexe", "prenom", "periode", "valeur"])
    w.writerows(lignes)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("prenoms-2024-nat.csv", t.getvalue())
    return b.getvalue()


def test_derivation_seuil_et_normalisation():
    z = _zip_insee([("1", "JÉRÔME", "1970", "300"), ("1", "JEROME", "1971", "200"), ("2", "ZOÉ", "2010", "495"),
                    ("1", "JEAN-PIERRE", "1950", "9000"), ("1", "_PRENOMS_RARES", "1950", "9000"),
                    ("1", "AL", "1990", "900"), ("2", "LÉA", "2005", "500"), ("1", "M'BAREK", "1960", "800"),
                    ("2", "ANNE", "1960", "XX")])
    assert prenoms_ref.deriver(z, 500) == ["JEROME", "LEA"]
    assert prenoms_ref.deriver(z, 500) == prenoms_ref.deriver(z, 500)  # déterministe


def test_apostrophe_typographique_ne_cree_pas_de_prenom():
    p = {"UNE", "DUNE", "JEAN"}  # « d’une » translittéré sans apostrophe donnerait le mot « DUNE »
    assert not local.contient_nom_de_personne("Organisation d’une fête de quartier", p - {"UNE"})
    assert local.contient_nom_de_personne("Subvention à Jean Dupont", p)


def test_intitule_europeen_adresse_precise_retire():
    p = local.prenoms()
    t, motif = fonds_europeens.intitule_publiable(
        "Accompagnement social de 34 familles du site 165 rue de Paris à Bobigny", p)
    assert t is None and motif == "adresse_precise"
    assert fonds_europeens.intitule_publiable("Aide à Jean Dupont pour son projet", p) == (
        None, "nom_de_personne_possible")
    assert fonds_europeens.intitule_publiable("Ouvrir l'école aux parents 2018-19", p) == (
        "Ouvrir l'école aux parents 2018-19", None)
    assert fonds_europeens.intitule_publiable("", p) == (None, None)


def test_aucun_intitule_europeen_publie_avec_adresse_precise():
    import json
    for f in sorted((ROOT / "site" / "data" / "fonds_europeens" / "operations").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        i = d["colonnes"].index("intitule")
        fautes = [o[i] for o in d["operations"] if o[i] and local.objet_avec_adresse(o[i])]
        assert not fautes, f"{f.name} : intitulés avec adresse précise : {fautes[:3]}"
