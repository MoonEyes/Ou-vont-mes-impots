"""Contrat d'interface : site/data respecte docs/schemas (docs/valider_contrat.py), sans reseau."""
import copy
import glob
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "docs"))
import valider_contrat as vc  # noqa: E402

jsonschema = pytest.importorskip("jsonschema")
SITE = vc.SITE


def test_validateur_passe_sur_les_donnees_du_depot():
    r = subprocess.run([sys.executable, str(ROOT / "docs" / "valider_contrat.py"), "--quiet"],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert " 0 non conformes" in r.stdout


def test_tout_fichier_versionne_de_site_data_a_un_schema():
    """Un JSON committe dans site/data sans schema = contrat a completer (les fichiers en cours, non suivis, passent)."""
    r = subprocess.run(["git", "ls-files", "site/data"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("pas de depot git")
    suivis = {ROOT / f for f in r.stdout.split() if f.endswith(".json")}
    couverts = {Path(p) for _, motif, _ in vc.FICHIERS for p in glob.glob(str(SITE / motif))}
    orphelins = sorted(str(p.relative_to(ROOT)) for p in suivis - couverts)
    assert not orphelins, f"sans schema : {orphelins[:10]}"


def _erreurs(schema, doc):
    return vc.erreurs(vc.validateur(jsonschema, schema), doc)


def _charger(rel):
    chemins = sorted(glob.glob(str(SITE / rel)))
    if not chemins:
        pytest.skip(f"{rel} absent")
    return json.loads(Path(chemins[0]).read_text(encoding="utf-8"))


def test_millesime_et_source_obligatoires():
    doc = _charger("cofog.json")
    del doc["millesime"]
    assert _erreurs("cofog.schema.json", doc)


def test_personne_physique_jamais_nommee_dans_un_top():
    doc = _charger("beneficiaires/programme_*.json")
    if doc.get("associations") is None:
        pytest.skip("pas d'associations dans le premier fichier")
    mauvais = copy.deepcopy(doc)
    mauvais["associations"]["top"][0]["categorie_juridique"] = "1000"  # entrepreneur individuel
    assert _erreurs("beneficiaires_programme.schema.json", mauvais)
    mauvais = copy.deepcopy(doc)
    mauvais["associations"]["top"][0]["prenom"] = "X"
    assert _erreurs("beneficiaires_programme.schema.json", mauvais)


def test_candidats_liste_blanche_de_champs():
    doc = _charger("vie_politique/candidats/*.json")
    doc["candidats"][0]["adresse"] = "1 rue X"
    assert _erreurs("vie_politique_candidats.schema.json", doc)


def test_scrutin_sans_candidat_nomme():
    doc = _charger("vie_politique/scrutins/*.json")
    doc["candidats"] = [{"candidat": "X"}]
    assert _erreurs("vie_politique_scrutin.schema.json", doc)


def test_conservation_des_groupes_controlee():
    doc = _charger("beneficiaires/france2030.json")
    doc["ensemble"]["total_eur"] += 1000
    assert vc.conservation_groupes(doc)


def test_lien_fichier_casse_detecte():
    doc = {"realisations_concretes": {"fichier_beneficiaires": "beneficiaires/programme_000.json"}}
    assert vc.liens_fichiers(SITE / "realisations" / "000.json", doc)
