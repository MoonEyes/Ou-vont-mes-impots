# tests/test_controle.py
"""Bloc contrôle (juridictions financières), influence (HATVP), aides aux entreprises : pipeline/controle.py."""
import json
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
SITE = RACINE / "site" / "data"
SORTIE = SITE / "controle"
sys.path.insert(0, str(RACINE / "pipeline"))
import controle  # noqa: E402

FICHIERS = sorted(SORTIE.rglob("*.json"))
pytestmark = pytest.mark.skipif(not (SORTIE / "index.json").exists(), reason="site/data/controle absent")


def charger(chemin):
    return json.loads(Path(chemin).read_text(encoding="utf-8"))


# --- Fonctions pures -------------------------------------------------------------------------------------------------

def test_tranches_de_depense():
    assert controle.tranche_depense("< 10 000 euros") == (0.0, 10000.0)
    assert controle.tranche_depense("> = 100 000 euros et < 200 000 euros") == (100000.0, 200000.0)
    assert controle.tranche_depense("> = 10 000 000 euros") == (10000000.0, None)
    assert controle.tranche_depense(None) is None


def test_decoupage_des_cibles_ministerielles():
    connus = sorted(["Premier ministre", "Economie et finances", "Environnement, énergie et mer",
                     "Autres : à préciser"], key=len, reverse=True)
    assert controle.decouper_cibles("Premier ministre, Economie et finances, Environnement, énergie et mer",
                                    connus) == ["Premier ministre", "Economie et finances",
                                                "Environnement, énergie et mer"]
    assert controle.decouper_cibles("Economie et finances, Autres : à préciser", connus)[-1] == "Autres : à préciser"


def test_texte_avec_personne_ecarte():
    assert controle.texte_sans_personne("Réponse de M. Jean DUPONT, maire") is None
    assert controle.texte_sans_personne("Réponse de Mme Durand") is None
    assert controle.texte_sans_personne("La chambre a contrôlé les comptes de la commune.") is not None
    assert controle.cible_publiable("Autre : Jean DUPONT") == "texte libre non publié"


def test_constats_chiffres_du_resume():
    c = controle.constats_chiffres("Le déficit a atteint 155,9 Md€ en 2024. Rien ici.")
    assert c and c[0]["valeur_eur"] == pytest.approx(155.9e9)
    assert controle.constats_chiffres(None) == []


def test_demandeur_parlementaire_ne_rattache_pas_au_programme_511():
    progs = {"511": {"libelle": "Assemblée nationale", "mission": "Pouvoirs publics", "operateurs": []},
             "176": {"libelle": "Police nationale", "mission": "Sécurités", "operateurs": []}}
    assert controle.rattacher_programmes("Les politiques de lutte contre le tabagisme (Assemblée nationale)",
                                         progs)[0] == []
    assert controle.rattacher_programmes("Certification des comptes de l'Assemblée nationale", progs)[0] == ["511"]
    assert controle.rattacher_programmes("Les frais d'enquête dans la police nationale", progs)[0] == ["176"]


@pytest.mark.skipif(not (SITE / "local" / "geo" / "44.json").exists(), reason="référentiel géographique absent")
def test_codes_departement_et_epci():
    geo = controle.referentiel_geo()
    assert controle.code_departement(geo, "LOIRE-ATLANTIQUE, FRANCE") == "44"
    assert controle.code_departement(geo, "SAVOIE (FRANCE)") == "73"
    assert controle.code_departement(geo, "LOIRET (45)") == "45"
    assert controle.code_departement(geo, "COTES D ARMOR") == "22"
    r = controle.rattacher_collectivite(geo, "COMMUNE", "ABBARETZ", "ABBARETZ", "LOIRE-ATLANTIQUE")
    assert r["niveau"] == "commune" and r["codes"]["commune"] == "44001" and r["codes"]["epci"] == "244400537"
    r = controle.rattacher_collectivite(geo, "COMMUNAUTE DE COMMUNES", "COMMUNAUTE DE COMMUNES DE NOZAY", None,
                                        "LOIRE-ATLANTIQUE")
    assert r["niveau"] == "epci" and r["codes"]["epci"] == "244400537"


# --- Fichiers produits ---------------------------------------------------------------------------------------------

def test_entete_et_taille():
    assert FICHIERS
    for f in FICHIERS:
        d = charger(f)
        assert d.get("millesime") and d.get("source"), f
        assert f.stat().st_size < 5_000_000, f


def test_aucune_personne_physique():
    interdits = {"dirigeants", "collaborateurs", "clients", "prenom", "civilite", "emailDeContact",
                 "telephoneDeContact", "reponses", "auteur_reponse"}
    civ = re.compile(r"(?<![\w.])(M\.|Mme|Monsieur|Madame)\s+[A-ZÉ]")

    def parcourir(x, chemin):
        if isinstance(x, dict):
            for k, v in x.items():
                assert k not in interdits, f"{chemin}: clé {k}"
                parcourir(v, chemin)
        elif isinstance(x, list):
            for v in x:
                parcourir(v, chemin)
        elif isinstance(x, str):
            assert not civ.search(x), f"{chemin}: {x[:80]}"

    for f in FICHIERS:
        parcourir(charger(f), f.name)


def test_organisations_lobbying():
    d = charger(SORTIE / "lobbying" / "organisations.json")
    col = d["colonnes"]
    i_type, i_cat = col.index("type_identifiant"), col.index("categorie")
    for o in d["organisations"]:
        assert o[i_type] in ("SIREN", "RNA", "HATVP")
        assert o[i_cat] not in ("Travailleur indépendant", "Consultant indépendant", "Avocat indépendant")
        for an, bas, haut in o[col.index("depenses_declarees")]:
            assert haut is None or haut >= bas
    cache = controle.charger_sirene()
    if cache:
        for o in d["organisations"]:
            # cache partiel (runner GitHub à froid, résolution reprenable) : seules les entrées connues sont vérifiées
            if o[i_type] == "SIREN" and o[0] in cache:
                assert controle.sirene.personne_morale((cache[o[0]] or {}).get("cj")), o[0]
    assert d["exclus"]["organisations"] >= 0


def test_cibles_sans_personne_et_missions_connues():
    d = charger(SORTIE / "lobbying" / "ministeres.json")
    missions = {json.loads(f.read_text(encoding="utf-8"))["mission"]
                for f in (SITE / "realisations").glob("[0-9]*.json")}
    for c in d["cibles"]:
        assert set(c["missions_lolf"]) <= missions, c
    for m, x in d["correspondance_ministere_missions"].items():
        assert set(x["missions"]) <= missions, m


def test_collectivites_codes_coherents():
    for f in (SORTIE / "publications" / "collectivites").glob("*.json"):
        d = charger(f)
        assert d["departement"]["code"] == f.stem
        for p in d["publications"]:
            c = p["codes"]
            if not f.stem.startswith("region_"):
                assert c["departement"] == f.stem
            if c["commune"]:
                assert c["commune"][:2] == c["departement"][:2] or c["departement"].startswith("97")
        assert sum(d["comptes_par_niveau"].values()) == len(d["publications"])


def test_programmes_rattaches_existent():
    d = charger(SORTIE / "publications" / "programmes.json")
    ids = {p["id"] for p in d["publications"]}
    for p, x in d["programmes"].items():
        assert (SITE / "realisations" / f"{p}.json").exists()
        assert set(x["publications"]) <= ids
    for p in d["publications"]:
        assert p["programmes"] and p["rattachement"]


MOTS_EVALUATIFS = re.compile(r"\b(excessi|insuffisan|mauvais|gaspill|scandal|abusi|inefficac|efficace|"
                             r"exorbitant|opaque|colossa|énorme|dérive)", re.I)


def test_aides_estimations_jamais_tranchees():
    d = charger(SORTIE / "aides_entreprises.json")
    e = d["estimations"]
    assert len(e) >= 10
    for x in e:
        assert x["perimetre"] and x["source"] and x["annee_publication"]
        for champ in ("perimetre", "publication", "auteur", "composantes_note"):
            assert not MOTS_EVALUATIFS.search(x.get(champ) or ""), (x["id"], champ)
    assert d["fourchette"]["basse_md"] == min(x["md"] for x in e)
    assert d["fourchette"]["haute_md"] == max(x.get("md_haut") or x["md"] for x in e)
    assert not any(k in d for k in ("total_retenu", "estimation_retenue", "montant_officiel"))
    for x in e:
        if x.get("composantes_md"):
            assert sum(x["composantes_md"].values()) == pytest.approx(x["md"], abs=1)
    for l in d["donnees_du_site"]:
        assert (SITE / l["fichier"]).exists(), l["fichier"]
    v = d["verification_documents"]["estimations"]
    assert set(v.values()) <= {"vérifié", "document absent"}


def test_index_recherche_publique_et_sources():
    d = charger(SORTIE / "index.json")
    assert {r["verdict"] for r in d["recherche_publique"]} <= {"réutilisable tel quel", "à adapter",
                                                                "inspiration seulement"}
    assert all(r["licence"] and r["mise_a_jour"] for r in d["recherche_publique"])
    assert any("ccomptes" in s["source"] for s in d["sources_inaccessibles"])
    for dep in d["controle"]["departements"]:
        assert (SITE / dep["fichier"]).exists()
