"""Décision du propriétaire du 19/11/2026 (option B) : le nom d'une organisation masquée par le filtre des noms de
personnes n'est rétabli que si le répertoire SIRENE confirme une personne morale (SIREN sur la ligne, catégorie
juridique de personne morale, raison sociale de l'unité légale). Fonction partagée :
sirene.nom_publiable_personne_morale. Tout le reste reste masqué (textes libres, noms sans SIREN, entrepreneurs
individuels, association dont la raison sociale est un nom de personne seul).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import local  # noqa: E402
import sirene  # noqa: E402

SITE = ROOT / "site" / "data"
F = sirene.nom_publiable_personne_morale


@pytest.mark.parametrize("siren, nom", [("609849153", "LILLY FRANCE"), ("622042422", "YARA FRANCE")])
def test_societe_confirmee_par_sirene_nommee(siren, nom):
    # Le filtre de prénoms masque ces dénominations (« Lilly », « Yara » sont des prénoms de la liste Insee)...
    assert local.contient_nom_de_personne(nom)
    # ... mais SIREN + catégorie de société + raison sociale SIRENE : nom rétabli, tel qu'écrit au répertoire.
    assert F(siren, "5710", nom) == nom
    assert F(siren, "5710", nom, "O") == nom


@pytest.mark.parametrize("nom", ["LILLY FRANCE", "YARA FRANCE"])
@pytest.mark.parametrize("siren", [None, "", "60984915", "ABCDEFGHI"])
def test_meme_nom_sans_siren_masque(siren, nom):
    assert F(siren, "5710", nom) is None


@pytest.mark.parametrize("cj", ["1000", None, "", "0000", "2110", "2210", "2310", "2385"])
def test_entrepreneur_individuel_ou_groupement_de_personnes_masque(cj):
    assert F("609849153", cj, "LILLY FRANCE") is None


def test_raison_sociale_absente_ou_diffusion_partielle_masquee():
    assert F("609849153", "5710", None) is None
    assert F("609849153", "5710", "  ") is None
    assert F("609849153", "5710", "LILLY FRANCE", "P") is None


def test_civilite_ou_domiciliation_dans_la_raison_sociale_masquee():
    assert F("123456789", "5499", "M. JEAN DUPONT SARL") is None
    assert F("123456789", "9220", "ASSOCIATION X CHEZ MME MARTIN") is None


def test_regle_des_noms_de_personne_seuls_inchangee():
    # Association, fondation, organisme public : raison sociale « Prénom Nom » seule, règle du 18/11 (masquée).
    assert F("894572692", "9220", "MIA MIA") is None
    assert F("123456789", "9300", "JEAN DUPONT") is None
    assert F("484152657", "9220", "ASSOCIATION MEDINA") == "ASSOCIATION MEDINA"
    # Société au nom de son fondateur : nommée, comme dans les marchés et les aides (tests/test_noms_de_personnes.py).
    assert F("123456789", "5499", "JEAN DUPONT") == "JEAN DUPONT"
    assert sirene.societe("5710") and sirene.societe("6540") and not sirene.societe("9220")
    assert not sirene.societe("1000")


@pytest.mark.parametrize("texte", ["Subvention à Jean Dupont", "Convention avec Lilly France pour la recherche",
                                   "Projet de Marie Martin", "Mme Durand, présidente"])
def test_texte_libre_contenant_un_prenom_reste_masque(texte):
    # Les textes libres (objets, intitulés, délibérations) ne passent jamais par la fonction : filtre inchangé.
    assert local.objet_publiable(texte) is None


def test_raisons_sociales_lit_la_denomination_de_l_unite_legale(tmp_path, monkeypatch):
    duckdb = pytest.importorskip("duckdb")
    p = tmp_path / "sirene_unite_legale.parquet"
    con = duckdb.connect()
    con.execute(f"""copy (select * from (values
        ('609849153', '5710', 'LILLY FRANCE', 'ENSEIGNE LILLY', 'O'),
        ('111111111', '1000', NULL, NULL, 'O'),
        ('222222222', '9220', NULL, 'NOM USUEL SEUL', 'P'))
        t(siren, categorieJuridiqueUniteLegale, denominationUniteLegale, denominationUsuelle1UniteLegale,
          statutDiffusionUniteLegale)) to '{p}' (format parquet)""")
    monkeypatch.setattr(local, "CACHE", tmp_path)
    r = local.raisons_sociales({"609849153", "111111111", "222222222", "333333333"})
    assert r["609849153"] == ("5710", "LILLY FRANCE", "O")
    assert r["111111111"] == ("1000", None, "O")  # jamais de nom pour une personne physique
    assert r["222222222"] == ("9220", None, "P")  # dénomination usuelle jamais reprise
    assert "333333333" not in r
    assert F("609849153", *r["609849153"]) == "LILLY FRANCE"
    assert F("222222222", *r["222222222"]) is None


def test_une_seule_fonction_partagee():
    """Les pipelines qui masquaient une dénomination d'organisation appellent la même fonction."""
    for module in ("associations", "entites", "subventions", "projets_subventionnes"):
        assert "nom_publiable_personne_morale" in (ROOT / "pipeline" / f"{module}.py").read_text(encoding="utf-8"), module


def _entites_noms() -> dict:
    noms = {}
    for f in SITE.glob("entites/fiches/*.json"):
        for s, x in json.loads(f.read_text(encoding="utf-8")).get("fiches", {}).items():
            noms[s] = (x["denomination"], x["categorie_juridique"])
    return noms


@pytest.mark.skipif(not (SITE / "entites" / "fiches").is_dir(), reason="données entites absentes")
def test_donnees_publiees_entites():
    noms = _entites_noms()
    assert noms.get("609849153") == ("LILLY FRANCE", "5710")
    assert noms.get("622042422") == ("YARA FRANCE", "5710")
    for s, (nom, cj) in noms.items():
        assert sirene.personne_morale(cj), (s, nom)
        assert not local.CIVILITE_RE.search(nom), (s, nom)


@pytest.mark.skipif(not (SITE / "associations" / "programmes").is_dir(), reason="données associations absentes")
def test_donnees_publiees_associations_noms_masques_restent_absents():
    """Raisons sociales « Prénom Nom » seules d'associations : toujours agrégées (MIA MIA, TIA PAULA)."""
    import associations
    for f in SITE.glob("associations/programmes/*.json"):
        for l in json.loads(f.read_text(encoding="utf-8"))["lignes"]:
            assert l[0] not in ("894572692", "517648911"), (f.name, l[:2])
            assert not associations.denomination_nominative(l[1]) or sirene.societe(l[2]), (f.name, l[:3])
