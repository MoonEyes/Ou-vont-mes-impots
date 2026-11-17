"""Cohérence de pipeline/tout.py (orchestrateur) avec le dépôt : chaque dossier de site/data a une étape productrice,
chaque étape a son module, son relevé d'entrées (pipeline/entrees_lac.json) et ses schémas (docs/valider_contrat.py).
Aucun réseau, aucune commande lancée."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import tout  # noqa: E402
import valider_contrat as vc  # noqa: E402

SITE = ROOT / "site" / "data"


def test_toutes_les_etapes_ont_leur_module_et_un_ordre():
    ids = [e.id for e in tout.ordre()]
    assert len(ids) == len(set(ids))
    assert ids[-1] == "datapackage"
    for e in tout.ETAPES:
        for c in e.collecter + e.produire:
            assert (ROOT / c[0]).exists(), c
        for d in e.deps:
            assert ids.index(d) < ids.index(e.id), (e.id, d)


def test_chaque_dossier_de_site_data_a_une_etape_productrice():
    sorties = {s.removeprefix("site/data/") for e in tout.ETAPES for s in e.sorties if s.startswith("site/data/")}
    sorties.add("mise_a_jour.json")   # rapport de pipeline/tout.py lui-même
    for p in sorted(SITE.iterdir()):
        if p.name.startswith("."):
            continue
        assert p.name in sorties, f"site/data/{p.name} : aucune étape de pipeline/tout.py ne le produit"


def test_chaque_etape_a_son_releve_d_entrees():
    entrees = json.loads((ROOT / "pipeline" / "entrees_lac.json").read_text(encoding="utf-8"))
    sans_entree = {"datapackage"}   # ne lit que site/data
    assert {e.id for e in tout.ETAPES} - sans_entree <= set(entrees["etapes"])


def test_chaque_axe_est_declare_au_validateur_et_au_contrat():
    contrat = (ROOT / "docs" / "contrat_interface.md").read_text(encoding="utf-8")
    motifs = [m for _, m, _ in vc.FICHIERS]
    for e in tout.ETAPES:
        for s in e.sorties:
            if not s.startswith("site/data/") or "." in Path(s).name:
                continue
            nom = s.removeprefix("site/data/")
            assert any(m.startswith(nom + "/") for m in motifs), f"{nom} absent de docs/valider_contrat.py"
            assert f"`{nom}/" in contrat or f"`{nom.split('/')[0]}/" in contrat, f"{nom} absent du contrat"


def test_plan_s_affiche_sans_rien_lancer():
    r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "tout.py"), "--plan"], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert "datapackage" in r.stdout and "durée estimée" in r.stdout


def test_rapport_de_passage_ne_cite_que_des_etapes_connues():
    rapport = json.loads((SITE / "mise_a_jour.json").read_text(encoding="utf-8"))
    connues = {e.id for e in tout.ETAPES}
    for x in rapport["etapes"]:
        assert x["etape"] in connues, x["etape"]
        assert x["statut"] in rapport["statuts"]
