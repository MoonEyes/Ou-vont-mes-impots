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
                       capture_output=True, text=True, timeout=1800)  # en parallele : 4 min sur 2 coeurs charges
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


def test_parts_d_un_prelevement_source_somment_a_un():
    doc = _charger("prelevements/affectation.json")
    pid = next(k for k, v in doc["prelevements"].items() if v["statut"] == "sourcee")
    doc["prelevements"][pid]["ventilation"][0]["part"] += 0.01
    assert vc.sommes_de_parts("prelevements_affectation.schema.json", doc)


def test_lot_parallele_et_cache_donnent_le_meme_resultat(tmp_path):
    """Un fichier non conforme est signale avec ou sans cache ; un fichier conforme ne l'est jamais ; l'empreinte
    (cache) n'est donnee qu'a un fichier conforme et ne masque pas un contenu modifie."""
    bon, mauvais = tmp_path / "bon.json", tmp_path / "mauvais.json"
    bon.write_bytes((SITE / "meta.json").read_bytes())
    mauvais.write_text('{"genere_le": 3}', encoding="utf-8")
    vc._init_processus(set())
    r1 = {c: (e, k) for c, e, k in vc._valider_lot(("meta.schema.json", [str(bon), str(mauvais)]))}
    assert r1[str(bon)][0] == [] and r1[str(bon)][1]
    assert r1[str(mauvais)][0] and r1[str(mauvais)][1] is None
    vc._init_processus({r1[str(bon)][1]})
    r2 = {c: (e, k) for c, e, k in vc._valider_lot(("meta.schema.json", [str(bon), str(mauvais)]))}
    assert r2 == r1
    bon.write_text('{"genere_le": 3}', encoding="utf-8")   # meme chemin, contenu devenu non conforme
    assert vc._valider_lot(("meta.schema.json", [str(bon)]))[0][1]
    vc._init_processus(set())
