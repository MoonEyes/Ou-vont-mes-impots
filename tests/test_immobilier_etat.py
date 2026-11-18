"""Immobilier de l'État (pipeline/immobilier_etat.py) : contrat, sommes, confidentialité, neutralité, reproductibilité.

Les tests sur site/data/immobilier_etat tournent sans réseau ni entrepôt ; la reproductibilité et la relecture des
documents demandent l'entrepôt (data/lake/immobilier_etat) et sont sautées sinon. Les tests unitaires des lecteurs
travaillent sur de petits fichiers écrits dans un dossier temporaire.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "immobilier_etat"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
import immobilier_etat as ie  # noqa: E402
from test_neutralite import fautes, textes  # noqa: E402

FICHIERS = ["index.json", "parc.json", "valeur.json", "cessions.json", "loyers.json", "compte.json"]
# Qualificatifs propres au sujet, en plus du lexique partagé : aucun jugement sur une vente, un loyer ou un bâtiment.
JUGEMENTS = re.compile(r"(?<!\w)(?:brad\w*|dilapid\w*|bijoux de famille|bonne affaire|mauvaise affaire|vétuste\w*|"
                       r"luxueu\w*|somptu\w*|abusi\w*|ruineu\w*|économie réalisée)(?!\w)", re.I)
CLES_PERSONNELLES = {"adresse", "adresse_complete", "latitude", "longitude", "point_geo", "geom", "designation_site",
                     "designation_batiment_terrain", "libelle_proprietaire", "commune", "lieu_dit", "voie", "numero",
                     "code_insee", "code_postal", "bailleur", "acquereur", "prenom", "nom_proprietaire"}
ENTREPOT = (ie.LAKE / ie.PARC["2021"]["fichier"]).exists() and (ie.DOCS / ie.DOC["dpt"]["fichier"]).exists() \
    and shutil.which("pdftotext") is not None
avec_entrepot = pytest.mark.skipif(not ENTREPOT, reason="entrepôt data/lake/immobilier_etat ou pdftotext absent")


def _lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


def _cles(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _cles(v)
    elif isinstance(x, list):
        for v in x:
            yield from _cles(v)


def _chaines(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _chaines(v)
    elif isinstance(x, list):
        for v in x:
            yield from _chaines(v)
    elif isinstance(x, str):
        yield x


# --- Fichiers publiés ---------------------------------------------------------------------------------------------------

def test_entete_taille_et_json_compact():
    for nom in FICHIERS:
        brut = (DATA / nom).read_bytes()
        d = json.loads(brut)
        assert d["millesime"] and d["source"] and d["unite"] and len(d["avertissement"]) > 20, nom
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["collecte_le"]), nom
        assert len(brut) < 5 * 10**6, nom
        assert b"\n" not in brut, nom


def test_index_liste_les_fichiers_et_la_recherche_publique():
    idx = _lire("index.json")
    assert sorted(f["fichier"] for f in idx["fichiers"]) == sorted(f"immobilier_etat/{n}" for n in FICHIERS
                                                                     if n != "index.json")
    for f in idx["fichiers"]:
        assert (DATA.parent / f["fichier"]).exists(), f
    verdicts = {t["verdict"] for t in idx["recherche_publique"]["trouvailles"]}
    assert verdicts <= {"réutilisable tel quel", "à adapter", "inspiration seulement", "aucun dépôt trouvé"}
    assert all(t["licence"] and t["date"] for t in idx["recherche_publique"]["trouvailles"])
    for c in idx["chiffres_cles"].values():
        assert re.fullmatch(r"\d{4}", c["annee"]) and c["source"] and c["statut"] in ("tracé", "approché", "non publié")


def test_aucune_donnee_personnelle_ni_localisation_fine():
    for nom in FICHIERS:
        d = _lire(nom)
        assert not (set(_cles(d)) & CLES_PERSONNELLES), nom
        for s in _chaines(d):
            assert "PERSONNE PHYSIQUE" not in s and "PARTENAIRE GENERIQUE" not in s, (nom, s[:80])


def test_libelles_neutres():
    for nom in FICHIERS:
        d = _lire(nom)
        for cle, t in textes(d):
            assert not fautes(t), (nom, cle, t[:120])
            assert not JUGEMENTS.search(t), (nom, cle, t[:120])


def test_parc_agregats_coherents():
    parc = _lire("parc.json")
    for pub in parc["publications"]:
        tot = pub["total"]
        assert tot["biens"] == tot["batiments"] + tot["autres_biens"]
        for cle in ("par_ministere", "par_departement", "par_region", "par_type_de_bien", "par_type_proprietaire"):
            assert sum(x["biens"] for x in pub[cle]) == tot["biens"], (pub["au"], cle)
            assert sum(x["batiments"] for x in pub[cle]) == tot["batiments"], (pub["au"], cle)
            s = [x["surface_batiments_m2"] for x in pub[cle] if x["surface_batiments_m2"] is not None]
            assert abs(sum(s) - tot["surface_batiments_m2"]) <= len(s), (pub["au"], cle)
        assert sum(pub["par_groupe_proprietaire"].values()) == tot["biens"]
        for m in pub["par_ministere"]:
            assert sum(m["par_groupe_proprietaire"].values()) == m["biens"]
            assert m["departement_non_renseigne"] <= m["biens"]
        ordre = [(-m["biens"], m["ministere"]) for m in pub["par_ministere"]]
        assert ordre == sorted(ordre)
        assert [d["code"] for d in pub["par_departement"]] == sorted(d["code"] for d in pub["par_departement"])


def test_parc_publications_partielles_signalees():
    parc = _lire("parc.json")
    assert [p["au"] for p in parc["publications"]] == ["2021-12-31", "2022-12-31", "2023-12-31"]
    assert parc["publications"][0]["perimetre_publication"] == "publication complète du jeu"
    assert all(p["perimetre_publication"] == "mise à jour partielle" for p in parc["publications"][1:])
    objets = {e["objet"] for e in parc["ecarts_entre_sources"]}
    assert {"nombre de biens du parc", "surface des terrains et espaces"} <= objets


def test_series_du_document_budgetaire():
    parc, valeur, loyers = _lire("parc.json"), _lire("valeur.json"), _lire("loyers.json")
    inv = parc["inventaire_document_budgetaire"]["series"]["global"]
    for a in inv["total"]:
        assert inv["total"][a] == inv["batiments"][a] + inv["terrains"][a], a
    pt = parc["surfaces_document_budgetaire"]["par_type"]
    for a in pt["annees"]:
        assert sum(l["valeurs"][a] for l in pt["lignes"]) == pt["total"][a], a
    v = valeur["valeur_comptable_patrimoine_controle"]["valeurs_meur"]
    assert list(v) == [str(a) for a in range(2012, 2024)]
    vm = valeur["valeur_nette_comptable_par_ministere"]
    for a in vm["annees"]:  # la source arrondit chaque ligne au million : 3 M€ d'écart au plus
        assert abs(sum(l["valeurs_meur"].get(a, 0) for l in vm["lignes"]) - vm["total_meur"][a]) <= 3, a
    # 2023 : la valeur du tableau général comprend les logements concédés, la ventilation par ministère non
    assert v["2023"] - vm["total_meur"]["2023"] == valeur["logements_concedes_2023"]["valeur_meur"]
    lp = loyers["loyers_payes"]["valeurs_meur"]
    dep = {l["poste"]: l["valeurs_meur"] for l in loyers["depenses_immobilieres"]["lignes"]}["Loyers"]
    for a in dep:
        assert dep[a] == lp[a], a


def test_grands_baux_sans_bailleur():
    gb = _lire("loyers.json")["grands_baux"]
    assert len(gb["baux"]) == len(ie.GRANDS_BAUX)
    for b in gb["baux"]:
        assert set(b) == {"ministere", "date_effet", "surface_m2", "occupant", "loyer_annuel_ht_eur", "departement",
                          "loyer_par_m2_eur", "page"}
        # le prix au m² publié correspond au loyer divisé par la surface (au centime près, arrondi de la source)
        assert abs(b["loyer_annuel_ht_eur"] / b["surface_m2"] - b["loyer_par_m2_eur"]) < 0.02, b
    assert sum(m["baux"] for m in gb["par_ministere"]) == len(gb["baux"])
    assert abs(sum(m["loyer_annuel_ht_eur"] for m in gb["par_ministere"])
               - sum(b["loyer_annuel_ht_eur"] for b in gb["baux"])) < 1


def test_compte_equilibre_par_annee():
    c = _lire("compte.json")
    assert list(c["par_annee"]) == ["2023", "2024", "2025"]
    for a, v in c["par_annee"].items():
        r, s = v["recettes"], v["solde"]
        for sec in r["sections"]:
            assert abs(sum(l["execution_eur"] or 0 for l in sec["lignes_execution"]) - sec["execution_eur"]) < 0.01
        assert abs(r["execution_eur"] - s["recettes_eur"]) <= 1, a
        assert abs(sum(p["execution_eur"] for p in v["depenses"]) - s["depenses_eur"]) <= 1, a
        assert abs(s["debut_eur"] + s["recettes_eur"] - s["depenses_eur"] - s["fin_eur"]) <= 1, a
    # continuité : le solde de fin d'une année est le solde de début de la suivante
    ans = list(c["par_annee"])
    for a, b in zip(ans, ans[1:]):
        assert abs(c["par_annee"][a]["solde"]["fin_eur"] - c["par_annee"][b]["solde"]["debut_eur"]) <= 1
    # rapprochement avec le rapport annuel de performances 2025 (arrondi à l'euro)
    for rr in c["rapport_annuel_2025"]["recettes"]:
        if rr["ligne"] == "total":
            assert abs(rr["execution_eur"] - c["par_annee"]["2025"]["recettes"]["execution_eur"]) <= 1


def test_cessions_deux_mesures_jamais_additionnees():
    ce = _lire("cessions.json")
    ca = ce["outil_de_suivi_des_cessions"]["par_administration_occupante"]
    for a in ca["annees"]:
        somme = sum(l["valeurs_eur"].get(a, 0) for l in ca["lignes"])
        ecart = next((e for e in ca["ecarts_somme_total"] if e["annee"] == a), None)
        assert (somme == ca["total_eur"][a]) == (ecart is None), a
        if ecart:
            assert ecart["difference"] == ca["total_eur"][a] - somme
    e = ce["ecarts_entre_sources"][0]
    assert len(e["valeurs"]) == 2 and "total" not in e
    h = ce["historique_2013_2017"]
    assert sum(h["par_annee"].values()) == h["total"]
    for cle in ("par_nature_de_bien", "par_procedure", "par_nature_juridique_acquereur", "par_departement"):
        assert sum(x["total"] for x in h[cle]) == h["total"], cle


# --- Tests unitaires ------------------------------------------------------------------------------------------------------

def test_nombre_et_format():
    assert ie.nombre("1 234,5") == 1234.5 and ie.nombre("") is None and ie.nombre("nc") is None
    assert ie.nombre("N/A") is None and ie.nombre("0") == 0.0
    assert ie._fr(1234567) == "1 234 567" and ie._fr(17.4) == "17,4" and ie._fr(5) == "5"


def test_departements_et_groupes():
    assert ie._dept("") == "non_renseigne" and ie._dept("N/A") == "sans_departement"
    assert ie._dept("1") == "01" and ie._dept("2a") == "2A" and ie._dept("971") == "971"
    assert ie._dept("DF") == "autre_code"
    assert ie._groupe("Etat") == "etat" and ie._groupe("Personne Physique") == "prive"
    assert ie._groupe("Commune") == "autre_personne_publique" and ie._groupe("Etat | Commune") == "plusieurs"
    assert ie._groupe("") == "non_renseigne"


def test_sequence_dans_l_ordre():
    t = "Loyers (en M€) 1 579 1 660 1 540 Variation"
    assert ie.sequence(t, ["Loyers (en M€)", "1 579", "1 660", "1 540"])
    assert not ie.sequence(t, ["Loyers (en M€)", "1 660", "1 579"])
    assert not ie.sequence(t, ["Loyers", "1 540"], fenetre=3)


def test_agreger_parc_sur_un_petit_fichier(tmp_path, monkeypatch):
    entete = "code_chorus;id;designation_site;adresse;dept;libelle_nouvelle_region;ministere;type;type_proprietaire;" \
             "libelle_proprietaire;surface_m2;erp;date_de_reference;latitude;longitude\n"
    lignes = ["a;1;Site A;1 rue X;75;Ile-de-France;Culture;Bureau;Etat;ETAT;100.0;Oui;2021-12-31;48.8;2.3",
              "b;2;Site B;;;Ile-de-France;Culture;Espace naturel;Personne Physique;PERSONNE PHYSIQUE;5000;Non;2021-12-31;;",
              "c;3;Site C;2 rue Y;N/A;Étranger;Justice;Logement;Commune;COMMUNE;;Non;2021-12-31;;"]
    (tmp_path / "p.csv").write_text(entete + "\n".join(lignes) + "\n", encoding="utf-8")
    monkeypatch.setattr(ie, "LAKE", tmp_path)
    monkeypatch.setitem(ie.PARC, "test", {**ie.PARC["2021"], "fichier": "p.csv"})
    r = ie.agreger_parc("test")
    assert r["total"] == {"biens": 3, "batiments": 2, "surface_batiments_m2": 100, "batiments_avec_surface": 1,
                          "autres_biens": 1, "surface_autres_biens_m2": 5000, "autres_biens_avec_surface": 1}
    assert {d["code"] for d in r["par_departement"]} == {"75", "non_renseigne", "sans_departement"}
    assert r["par_groupe_proprietaire"] == {"autre_personne_publique": 1, "etat": 1, "prive": 1}
    texte = json.dumps(r, ensure_ascii=False)
    for interdit in ("rue X", "Site A", "48.8", "PERSONNE PHYSIQUE"):
        assert interdit not in texte


def test_recettes_plrg_sur_un_petit_fichier(tmp_path, monkeypatch):
    (tmp_path / "plrg_2099_cs_recouvrements.csv").write_text(
        "Categorie;Compte;Section;Ligne_de_prevision;Ligne_d'execution;Total_des_evaluations;Recouvrements_effectues\n"
        "CAS;Gestion du patrimoine immobilier de l'État;S - 761;Produits des cessions immobilières - 76101;0;100;0\n"
        "CAS;Gestion du patrimoine immobilier de l'État;S - 761;Produits des cessions immobilières - 76101;"
        "Cessions A - 761601;0;30,5\n"
        "CAS;Autre compte;S - 1;L - 10101;X - 101011;0;999\n", encoding="utf-8")
    monkeypatch.setattr(ie, "PLRG", tmp_path)
    r = ie.plrg_recettes(2099)
    assert r["evaluation_eur"] == 100 and r["execution_eur"] == 30.5
    assert r["sections"][0]["lignes_execution"] == [{"code": "761601", "libelle": "Cessions A", "execution_eur": 30.5}]


# --- Entrepôt : relecture des documents et reproductibilité --------------------------------------------------------------

@avec_entrepot
def test_production_reproductible_octet_pour_octet(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    ie.produire(a)
    ie.produire(b)
    for nom in FICHIERS:
        assert (a / nom).read_bytes() == (b / nom).read_bytes(), nom
        assert (a / nom).read_bytes() == (DATA / nom).read_bytes(), f"{nom} : site/data à régénérer"


@avec_entrepot
def test_une_ligne_absente_du_document_arrete_la_production():
    with pytest.raises(ValueError):
        ie.verifier("dpt", 23, ["Loyers (en M€)", "9 999 999"], "test")
    with pytest.raises(ValueError):
        ie.citer("rap", 12, "Phrase qui ne figure pas dans le rapport annuel de performances.")
